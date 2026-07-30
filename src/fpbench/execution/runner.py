"""Carrying out one comparison, completely and exactly once.

The runner is the only component that sees everything: the run, the pair, the
images, the preparer, the adapter and the store. It is also the only one that
is allowed to, and it stays algorithm-agnostic in exchange — the adapter and
the preparer are injected, and there is no ``if algorithm_id == ...`` here or
anywhere downstream of here (docs/adr/0007).

Two behaviours are worth stating up front, because everything else follows from
them.

**A job produces at most one result, ever.** Before doing any work the runner
looks for a stored result under the same ``run_id`` and ``job_id``. If one
exists with the same ``job_fingerprint``, the job is skipped: no preparation,
no adapter call, no write. That is what makes an interrupted run resumable
rather than restartable. A stored result whose fingerprint disagrees is a
conflict, and conflicts are never resolved by overwriting.

**A failure is recorded, not raised.** An image that will not load, an adapter
that throws, an adapter that returns nonsense — each becomes a stored result
with ``status = failure`` and a specific failure code. A run of 6,000
comparisons must not die on the first bad pair, and a comparison that never
produced a score must never be silently counted as a non-match (docs/adr/0006).

Preflight is the exception. A mismatched adapter, an unavailable environment or
the wrong preparer is a fault of the *run*, and it raises before any job
executes rather than producing thousands of identical per-pair failures.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from time import perf_counter_ns
from typing import Mapping

from fpbench.adapters.base import FingerprintAlgorithmAdapter
from fpbench.adapters.errors import AdapterContractViolation
from fpbench.core.enums import (
    ExecutionStatus,
    FailureCode,
    FailureStage,
    ScoreDirection,
)
from fpbench.core.errors import (
    ExecutionError,
    ImagePreparationError,
    PreflightError,
    ResultConflictError,
)
from fpbench.core.execution_models import (
    ComparisonContext,
    FailureInfo,
    PreparedImage,
    RawMatchResult,
    TimingBreakdown,
    descriptor_fingerprint,
    environment_fingerprint,
)
from fpbench.core.identifiers import ImageId
from fpbench.core.models import ComparisonPair, ImageRecord
from fpbench.core.result_models import RawResultRecord, RunDefinition
from fpbench.execution.jobs import ComparisonJob
from fpbench.imaging.base import ImagePreparer
from fpbench.storage.result_store import ResultStore

__all__ = ["JobDisposition", "JobExecutionOutcome", "SingleJobRunner"]

_NS_PER_MS = 1_000_000
_MAX_MESSAGE_CHARS = 500


class JobDisposition(str, Enum):
    """What the runner actually did with a job."""

    EXECUTED = "executed"
    SKIPPED_EXISTING = "skipped_existing"


@dataclass(frozen=True, slots=True)
class JobExecutionOutcome:
    """The stored result, plus whether this call produced it.

    ``result`` is always present: on a skip it is the result read back from
    disk, so a caller never has to care which path was taken.
    """

    disposition: JobDisposition
    result: RawResultRecord


class _RecordedFailure(Exception):
    """Internal signal: stop this job and store ``info`` as its result."""

    def __init__(self, info: FailureInfo) -> None:
        super().__init__(info.message)
        self.info = info


class SingleJobRunner:
    """Executes one :class:`ComparisonJob` at a time against one adapter."""

    def __init__(
        self,
        *,
        run: RunDefinition,
        adapter: FingerprintAlgorithmAdapter,
        preparer: ImagePreparer,
        result_store: ResultStore,
        dataset_root: Path,
        image_index: Mapping[ImageId, ImageRecord],
        workspace_root: Path,
    ) -> None:
        self._run = run
        self._adapter = adapter
        self._preparer = preparer
        self._result_store = result_store
        self._dataset_root = Path(dataset_root).resolve()
        self._image_index = dict(image_index)
        self._workspace_root = Path(workspace_root).resolve()
        self._preflight()

    @property
    def run(self) -> RunDefinition:
        """The run this runner is bound to.

        Exposed so that a batch executor can check its plan against the same
        run without reaching into private state.
        """
        return self._run

    @property
    def result_store(self) -> ResultStore:
        return self._result_store

    # --------------------------------------------------------------- preflight

    def _preflight(self) -> None:
        """Prove the injected parts are the ones the run was defined against."""
        descriptor = self._adapter.descriptor
        if descriptor != self._run.algorithm:
            raise PreflightError(
                f"adapter describes {descriptor.algorithm_id!r} but the run was "
                f"defined for {self._run.algorithm.algorithm_id!r}"
            )
        if descriptor_fingerprint(descriptor) != self._run.algorithm_fingerprint:
            raise PreflightError(
                "adapter descriptor fingerprint does not match the run definition"
            )

        environment = self._adapter.validate_environment()
        if not environment.is_ready:
            raise PreflightError(
                f"adapter environment is {environment.status.value}: "
                f"{environment.message or 'no detail given'}"
            )
        if environment_fingerprint(environment) != self._run.environment_fingerprint:
            raise PreflightError(
                "adapter environment fingerprint does not match the run definition; "
                "the machine or its dependencies changed since the run was defined"
            )

        expected_preparer = self._run.execution_profile.preparer_id
        if self._preparer.preparer_id != expected_preparer:
            raise PreflightError(
                f"execution profile requires preparer {expected_preparer!r}, "
                f"got {self._preparer.preparer_id!r}"
            )

        self._result_store.ensure_run(self._run)

    # ----------------------------------------------------------------- execute

    def execute(
        self, job: ComparisonJob, pair: ComparisonPair
    ) -> JobExecutionOutcome:
        """Run one comparison, or return the result already stored for it."""
        total_start = perf_counter_ns()
        started_utc = _utc_now()

        self._require_consistent(job, pair)

        existing = self._existing_outcome(job)
        if existing is not None:
            return existing

        preparation_ns = 0
        adapter_ns = 0
        failure: FailureInfo | None = None
        match_result: RawMatchResult | None = None
        left_record: ImageRecord | None = None
        right_record: ImageRecord | None = None
        working_directory: Path | None = None
        artifact_directory: Path | None = None
        left: PreparedImage | None = None
        right: PreparedImage | None = None
        context: ComparisonContext | None = None

        try:
            left_record = self._require_image(job.left_image_id)
            right_record = self._require_image(job.right_image_id)
        except _RecordedFailure as exc:
            failure = exc.info
        except Exception as exc:  # noqa: BLE001 - one bad input must be recorded
            failure = self._failure(
                FailureCode.INTERNAL_ERROR,
                FailureStage.INPUT,
                f"{type(exc).__name__}: {exc}",
                details={
                    "kind": "runner_exception",
                    "exception_type": type(exc).__name__,
                },
            )

        if failure is None:
            try:
                working_directory, artifact_directory = self._job_directories(job)
            except Exception as exc:  # noqa: BLE001 - filesystem setup is per-job
                failure = self._failure(
                    FailureCode.INTERNAL_ERROR,
                    FailureStage.PREPARATION,
                    f"{type(exc).__name__}: {exc}",
                    details={
                        "kind": "job_directory_exception",
                        "exception_type": type(exc).__name__,
                    },
                )

        if failure is None:
            assert left_record is not None and right_record is not None
            preparation_start = perf_counter_ns()
            try:
                # Both sides are prepared independently, even when the job is a
                # SELF comparison and they are the same image. Skipping the
                # second call would make SELF take a different code path from
                # every other stage, which is exactly the path a bug would hide
                # in.
                left = self._prepare(left_record)
                right = self._prepare(right_record)
            except ImagePreparationError as exc:
                failure = self._failure(
                    FailureCode.PREPARATION_FAILED,
                    FailureStage.PREPARATION,
                    str(exc),
                )
            except Exception as exc:  # noqa: BLE001 - one bad image must be recorded
                failure = self._failure(
                    FailureCode.INTERNAL_ERROR,
                    FailureStage.PREPARATION,
                    f"{type(exc).__name__}: {exc}",
                    details={
                        "kind": "preparer_exception",
                        "exception_type": type(exc).__name__,
                    },
                )
            finally:
                preparation_ns = perf_counter_ns() - preparation_start

        if failure is None:
            assert working_directory is not None and artifact_directory is not None
            try:
                context = ComparisonContext(
                    run_id=self._run.run_id,
                    job_id=job.job_id,
                    attempt=job.attempt,
                    working_directory=working_directory,
                    artifact_directory=artifact_directory,
                    timeout_seconds=self._run.execution_profile.timeout_seconds,
                    deterministic_seed=self._run.execution_profile.deterministic_seed,
                )
            except Exception as exc:  # noqa: BLE001 - context setup is per-job
                failure = self._failure(
                    FailureCode.INTERNAL_ERROR,
                    FailureStage.PREPARATION,
                    f"{type(exc).__name__}: {exc}",
                    details={
                        "kind": "runner_exception",
                        "exception_type": type(exc).__name__,
                    },
                )

        if failure is None:
            assert left is not None and right is not None and context is not None
            adapter_start = perf_counter_ns()
            try:
                match_result = self._adapter.compare(left, right, context)
                self._validate_adapter_result(match_result)
            except TimeoutError as exc:
                # Stage 3A does not cancel in-process work; it only records a
                # timeout an adapter chose to raise.
                failure = self._failure(
                    FailureCode.TIMEOUT,
                    FailureStage.TIMEOUT,
                    str(exc) or "adapter timed out",
                    retryable=True,
                )
            except AdapterContractViolation as exc:
                failure = self._failure(
                    FailureCode.INTERNAL_ERROR,
                    FailureStage.ADAPTER,
                    str(exc),
                    details={"kind": "adapter_contract_violation"},
                )
            except Exception as exc:  # noqa: BLE001 - deliberately broad
                # KeyboardInterrupt, SystemExit and GeneratorExit derive from
                # BaseException and keep propagating. Any ordinary exception is
                # one bad comparison, not a reason to lose the run.
                failure = self._failure(
                    FailureCode.INTERNAL_ERROR,
                    FailureStage.ADAPTER,
                    f"{type(exc).__name__}: {exc}",
                    details={"exception_type": type(exc).__name__},
                )
            finally:
                adapter_ns = perf_counter_ns() - adapter_start

        if failure is not None:
            match_result = RawMatchResult.failed(
                failure=failure,
                score_direction=self._run.algorithm.score_direction,
            )

        assert match_result is not None  # every path above sets one
        finished_utc = _utc_now()
        total_ns = perf_counter_ns() - total_start

        record = self._build_record(
            job=job,
            result=match_result,
            started_utc=started_utc,
            finished_utc=finished_utc,
            timings=TimingBreakdown(
                preparation_ms=preparation_ns / _NS_PER_MS,
                adapter_ms=adapter_ns / _NS_PER_MS,
                total_ms=total_ns / _NS_PER_MS,
                adapter_components_ms=match_result.timing_components_ms,
            ),
        )
        self._result_store.write_raw_result(record)
        return JobExecutionOutcome(JobDisposition.EXECUTED, record)

    # ----------------------------------------------------------------- helpers

    def _require_consistent(self, job: ComparisonJob, pair: ComparisonPair) -> None:
        """Guard against being handed a job and a pair that do not belong together.

        A programming error, not a comparison outcome, so it raises rather than
        producing a stored failure: writing a result for the wrong pair would
        be worse than not writing one at all.
        """
        if job.run_id != self._run.run_id:
            raise ExecutionError(
                f"job {job.job_id} belongs to run {job.run_id}, not {self._run.run_id}"
            )
        if job.pair_id != pair.pair_id:
            raise ExecutionError(
                f"job {job.job_id} covers pair {job.pair_id}, not {pair.pair_id}"
            )
        if (job.left_image_id, job.right_image_id) != (
            pair.left_image_id,
            pair.right_image_id,
        ):
            raise ExecutionError(
                f"job {job.job_id} does not match the images of pair {pair.pair_id}"
            )

    def _existing_outcome(self, job: ComparisonJob) -> JobExecutionOutcome | None:
        if not self._result_store.has_raw_result(self._run.run_id, job.job_id):
            return None
        stored = self._result_store.read_raw_result(self._run.run_id, job.job_id)
        if stored.job_fingerprint != job.job_fingerprint:
            raise ResultConflictError(
                f"a result for job {job.job_id} already exists with a different "
                f"fingerprint; refusing to overwrite it (docs/adr/0009)"
            )
        return JobExecutionOutcome(JobDisposition.SKIPPED_EXISTING, stored)

    def _require_image(self, image_id: ImageId) -> ImageRecord:
        record = self._image_index.get(image_id)
        if record is None:
            raise _RecordedFailure(
                self._failure(
                    FailureCode.INPUT_INVALID,
                    FailureStage.INPUT,
                    f"image {image_id} is not in the image manifest",
                )
            )
        if not record.is_usable:
            raise _RecordedFailure(
                self._failure(
                    FailureCode.INPUT_INVALID,
                    FailureStage.INPUT,
                    f"image {image_id} is blocked by dataset validation",
                    details={"reason": "blocked_image"},
                )
            )
        return record

    def _prepare(self, record: ImageRecord) -> PreparedImage:
        return self._preparer.prepare(
            record, self._dataset_root, self._run.execution_profile
        )

    def _job_directories(self, job: ComparisonJob) -> tuple[Path, Path]:
        """Scratch and artefact directories for one job.

        Artefacts live under the workspace so that an ``ArtifactReference`` can
        stay workspace-relative and therefore portable. ``work/`` is disposable
        by design.
        """
        working = self._workspace_root / "work" / self._run.run_id / job.job_id
        artifacts = self._workspace_root / "artifacts" / self._run.run_id / job.job_id
        working.mkdir(parents=True, exist_ok=True)
        artifacts.mkdir(parents=True, exist_ok=True)
        return working, artifacts

    def _validate_adapter_result(self, result: object) -> None:
        """Re-check what the model already enforces, plus what it cannot.

        The model's own invariants make an honest adapter unable to build a
        contradictory result. This exists for the dishonest case — an adapter
        that constructs one by other means — and for the one rule the model has
        no way to check, since it does not know which descriptor it came from.
        """
        if not isinstance(result, RawMatchResult):
            raise AdapterContractViolation(
                f"compare() returned {type(result).__name__}, not RawMatchResult"
            )
        expected: ScoreDirection = self._run.algorithm.score_direction
        if result.score_direction is not expected:
            raise AdapterContractViolation(
                f"result declares score direction {result.score_direction.value!r} "
                f"but the descriptor declares {expected.value!r}"
            )
        if result.status is ExecutionStatus.SUCCESS:
            score = result.raw_score
            if score is None or result.failure is not None:
                raise AdapterContractViolation(
                    "a successful result must carry a score and no failure"
                )
            if score != score or score in (float("inf"), float("-inf")):
                raise AdapterContractViolation(f"raw_score is not finite: {score!r}")
        elif result.raw_score is not None or result.failure is None:
            raise AdapterContractViolation(
                "a failed result must carry a failure and no score"
            )

    def _build_record(
        self,
        *,
        job: ComparisonJob,
        result: RawMatchResult,
        started_utc: str,
        finished_utc: str,
        timings: TimingBreakdown,
    ) -> RawResultRecord:
        run = self._run
        return RawResultRecord(
            result_id=job.job_id,
            run_id=run.run_id,
            job_id=job.job_id,
            job_fingerprint=job.job_fingerprint,
            protocol_id=run.protocol_id,
            cohort_id=run.cohort_id,
            pair_manifest_hash=run.pair_manifest_hash,
            pair_id=job.pair_id,
            left_image_id=job.left_image_id,
            right_image_id=job.right_image_id,
            algorithm_id=run.algorithm.algorithm_id,
            algorithm_fingerprint=run.algorithm_fingerprint,
            execution_profile_id=run.execution_profile.profile_id,
            execution_profile_hash=run.execution_profile_hash,
            attempt=job.attempt,
            started_utc=started_utc,
            finished_utc=finished_utc,
            status=result.status,
            raw_score=result.raw_score,
            score_direction=result.score_direction,
            failure=result.failure,
            timings=timings,
            artifacts=result.artifacts,
            adapter_metadata=result.metadata,
            runner_metadata={
                "runner": "single_job_runner",
                "preparer_id": self._preparer.preparer_id,
            },
        )

    def _failure(
        self,
        code: FailureCode,
        stage: FailureStage,
        message: str,
        *,
        retryable: bool = False,
        details: Mapping[str, str] | None = None,
    ) -> FailureInfo:
        return FailureInfo(
            code=code,
            stage=stage,
            message=self._sanitise(message),
            retryable=retryable,
            details=details or {},
        )

    def _sanitise(self, message: str) -> str:
        """Make a message safe to put in a report.

        Local roots are replaced with placeholders so a stored failure does not
        pin the result to one machine's directory layout, and the text is
        truncated so a verbose exception cannot bloat every row of a run.
        """
        text = message.strip() or "no detail given"
        for root, placeholder in (
            (str(self._dataset_root), "<dataset_root>"),
            (str(self._workspace_root), "<workspace>"),
        ):
            if root:
                text = text.replace(root, placeholder)
        if len(text) > _MAX_MESSAGE_CHARS:
            text = text[: _MAX_MESSAGE_CHARS - 3] + "..."
        return text


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()
