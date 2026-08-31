"""Evaluation-blind execution of one frozen Stage 21B method run."""

from __future__ import annotations

import datetime as dt
import hashlib
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from fpbench.adapters.base import FingerprintAlgorithmAdapter
from fpbench.core.enums import EnvironmentStatus, ExecutionStatus
from fpbench.core.evidence_sanitisation import (
    find_absolute_paths,
    redact_absolute_paths,
)
from fpbench.core.execution_models import (
    ComparisonContext,
    RawMatchResult,
    descriptor_fingerprint,
    environment_fingerprint,
)
from fpbench.core.serialization import stable_hash
from fpbench.execution.adapter_result_validation import (
    MAX_METADATA_VALUE_CHARS,
    forbidden_metadata_present,
)
from fpbench.execution.blinding import RunBlinding
from fpbench.stage21b.adapters import FailureClassifier, FailureDisposition
from fpbench.stage21b.errors import (
    Stage21BInfrastructureInterruption,
    Stage21BPreflightError,
)
from fpbench.stage21b.models import (
    FrozenRunSpec,
    PlannedPair,
    Stage21BOutcomeStatus,
    TerminalOutcome,
)
from fpbench.stage21b.store import Stage21BResultStore


class PreparedPairResolver(Protocol):
    def resolve_pair(self, pair: PlannedPair) -> tuple[Any, Any]: ...


class InvocationGuard(Protocol):
    def before_invocation(self, *, pair: PlannedPair, spec: FrozenRunSpec) -> None: ...

    def after_batch(self, *, spec: FrozenRunSpec) -> None: ...


ProgressCallback = Callable[[dict[str, Any]], None]


class _ClassifiedInfrastructureFailure(Exception):
    def __init__(self, *, code: str, stage: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.message = message


class Stage21BRunner:
    """Run pending manifest rows sequentially and store one terminal outcome each.

    Infrastructure faults stop the batch and leave the pair pending.  A returned
    matcher failure is terminal only after the predecessor-specific classifier
    says it is an algorithm failure.  No score or score-derived statistic is
    exposed by this class.
    """

    def __init__(
        self,
        *,
        spec: FrozenRunSpec,
        adapter: FingerprintAlgorithmAdapter,
        prepared_inputs: PreparedPairResolver,
        store: Stage21BResultStore,
        failure_classifier: FailureClassifier,
        invocation_guard: InvocationGuard | None = None,
        progress: ProgressCallback | None = None,
        progress_interval: int = 250,
        blinding: RunBlinding | None = None,
    ) -> None:
        self.spec = spec
        self.adapter = adapter
        self.prepared_inputs = prepared_inputs
        self.store = store
        self.failure_classifier = failure_classifier
        self.invocation_guard = invocation_guard
        self.progress = progress
        if type(progress_interval) is not int or progress_interval < 1:
            raise ValueError("progress_interval must be a positive exact integer")
        self.progress_interval = progress_interval
        self.blinding = blinding or RunBlinding()
        self._closed = False
        try:
            self._preflight()
        except BaseException:
            # A runner that cannot establish its frozen identity must not leave
            # a subprocess/worker allocated.  Preserve the preflight failure;
            # cleanup here is best-effort because no run has started or can be
            # sealed.
            try:
                self.close()
            except Exception:
                pass
            raise

    def _preflight(self) -> None:
        if self.store.spec.run_spec_fingerprint != self.spec.run_spec_fingerprint:
            raise Stage21BPreflightError("runner and result store use different run specs")
        descriptor = self.adapter.descriptor
        if descriptor.algorithm_id != self.spec.algorithm_id:
            raise Stage21BPreflightError("adapter algorithm differs from the frozen run")
        if descriptor.adapter_id != self.spec.adapter_id:
            raise Stage21BPreflightError("adapter route differs from the frozen run")
        if descriptor.implementation_version != self.spec.implementation_version:
            raise Stage21BPreflightError("adapter implementation version changed")
        if descriptor.score_direction.value != self.spec.score_direction:
            raise Stage21BPreflightError("adapter score direction changed")
        if descriptor_fingerprint(descriptor) != self.spec.adapter_descriptor_fingerprint:
            raise Stage21BPreflightError("adapter descriptor fingerprint changed")
        environment = self.adapter.validate_environment()
        if environment.status is not EnvironmentStatus.READY:
            raise Stage21BPreflightError(
                "adapter environment is unavailable: "
                + (environment.message or "no detail")
            )
        expected_environment = str(
            self.spec.runtime_binding.get("environment_fingerprint", "")
        )
        if environment_fingerprint(environment) != expected_environment:
            raise Stage21BPreflightError("adapter environment changed since preflight")

    def run(self, *, max_pairs: int | None = None) -> dict[str, Any]:
        """Execute a complete run, or an operationally bounded prefix.

        ``max_pairs`` is a checkpointing convenience, never a new population:
        it takes the first pending rows in manifest order and leaves the run
        explicitly incomplete.
        """
        if self._closed:
            raise Stage21BPreflightError(
                "a closed Stage 21B runner cannot execute another batch; resume with "
                "a freshly preflighted runner"
            )
        try:
            if max_pairs is not None and (
                type(max_pairs) is not int or max_pairs < 1
            ):
                raise ValueError("max_pairs must be a positive exact integer")
            if self.store.is_sealed:
                return self.store.status_report()

            self.store.recover_interrupted_attempts()
            pending = self.store.pending_pairs()
            selected = pending if max_pairs is None else pending[:max_pairs]
            for index, pair in enumerate(selected, start=1):
                self._execute(pair)
                # The operational report is a set of aggregates over the whole
                # journal, and the journal is the size of the run: at 73,500
                # stored outcomes one report costs ~1.2 s, so building one per
                # comparison would add roughly twelve hours per method to a
                # benchmark that computes nothing from it.  Report on an
                # interval and at the end of the batch instead.
                if self.progress is not None and (
                    index == len(selected) or index % self.progress_interval == 0
                ):
                    self.progress(self.store.status_report())
        finally:
            try:
                if self.invocation_guard is not None:
                    self.invocation_guard.after_batch(spec=self.spec)
            finally:
                # Adapter cleanup is part of the batch's infrastructure
                # contract, not an afterthought owned by the CLI.  In
                # particular FLX proves that its worker stopped: a failure here
                # must leave the completed outcomes resumable but unsealed.
                self._close_after_batch()

        if max_pairs is None and not self.store.pending_pairs():
            self.store.seal()
        return self.store.status_report()

    def close(self) -> None:
        if self._closed:
            return
        close = getattr(self.adapter, "close", None)
        if callable(close):
            close()
        self._closed = True

    def _close_after_batch(self) -> None:
        try:
            self.close()
        except Exception as exc:
            raise Stage21BInfrastructureInterruption(
                "adapter cleanup failed; the Stage 21B result set remains unsealed: "
                f"{_safe_message(exc)}"
            ) from exc

    def _execute(self, pair: PlannedPair) -> None:
        if self.invocation_guard is not None:
            self.invocation_guard.before_invocation(pair=pair, spec=self.spec)
        self._require_frozen_invocation(pair)
        started_utc = _utc_now()
        attempt_id, attempt_number = self.store.begin_attempt(
            pair.pair_id, started_utc=started_utc
        )
        job_id = _job_id(self.spec.run_id, pair.pair_id)
        working = (self.store.run_dir / "work" / job_id).resolve()
        artifacts = (self.store.run_dir / "artifacts" / job_id).resolve()
        working.mkdir(parents=True, exist_ok=True)
        artifacts.mkdir(parents=True, exist_ok=True)

        try:
            left, right = self.prepared_inputs.resolve_pair(pair)
            blinded_left = self.blinding.blind(left, working)
            blinded_right = self.blinding.blind(right, working)
            context = ComparisonContext(
                run_id=self.spec.run_id,
                job_id=job_id,
                attempt=attempt_number,
                working_directory=working,
                artifact_directory=artifacts,
                timeout_seconds=self.spec.timeout_seconds,
                deterministic_seed=_seed(self.spec.run_id, pair.pair_id),
            )
            # Descriptor drift is cheap to test and is checked immediately before
            # every matcher call.  Runtime bytes are guarded by the certified
            # adapters themselves and by the invocation guard.
            if descriptor_fingerprint(self.adapter.descriptor) != self.spec.adapter_descriptor_fingerprint:
                raise Stage21BPreflightError("adapter identity changed during the run")
            began = time.perf_counter_ns()
            result = self.adapter.compare(blinded_left, blinded_right, context)
            wall_time_ms = (time.perf_counter_ns() - began) / 1_000_000.0
            terminal = self._terminal(
                pair=pair,
                job_id=job_id,
                attempt=attempt_number,
                started_utc=started_utc,
                finished_utc=_utc_now(),
                wall_time_ms=wall_time_ms,
                result=result,
            )
            self.store.record_terminal(attempt_id, terminal)
        except _ClassifiedInfrastructureFailure as exc:
            finished = _utc_now()
            try:
                self.store.record_infrastructure_failure(
                    attempt_id,
                    finished_utc=finished,
                    code=exc.code,
                    stage=exc.stage,
                    message=_safe_text(exc.message, "infrastructure_failure"),
                )
            except Exception:
                pass
            raise Stage21BInfrastructureInterruption(
                f"run stopped before a terminal outcome for {pair.pair_id}: "
                f"{_safe_text(exc.message, 'infrastructure_failure')}"
            ) from exc
        except Exception as exc:
            finished = _utc_now()
            try:
                self.store.record_infrastructure_failure(
                    attempt_id,
                    finished_utc=finished,
                    code="stage21b_infrastructure_interruption",
                    stage="infrastructure",
                    message=_safe_message(exc),
                )
            except Exception:
                # The open attempt is deliberately recoverable if the same
                # storage outage also prevents recording its diagnosis.
                pass
            raise Stage21BInfrastructureInterruption(
                f"run stopped before a terminal outcome for {pair.pair_id}: "
                f"{_safe_message(exc)}"
            ) from exc
        finally:
            self.blinding.discard(working)
            _discard_empty_directory(working)
            # An adapter that produced no artefact leaves an empty job
            # directory behind; 73,500 of them per method is housekeeping the
            # filesystem should not be asked to carry.
            _discard_empty_directory(artifacts)

    def _terminal(
        self,
        *,
        pair: PlannedPair,
        job_id: str,
        attempt: int,
        started_utc: str,
        finished_utc: str,
        wall_time_ms: float,
        result: RawMatchResult,
    ) -> TerminalOutcome:
        if not isinstance(result, RawMatchResult):
            raise TypeError("certified adapter did not return RawMatchResult")
        if result.score_direction.value != self.spec.score_direction:
            raise Stage21BPreflightError("adapter result changed score direction")
        forbidden = forbidden_metadata_present(result.metadata)
        if forbidden:
            raise Stage21BPreflightError(
                "adapter returned evaluation/identity metadata: " + ", ".join(forbidden)
            )
        _require_no_evaluation_keys(result.metadata)
        _require_no_evaluation_keys(result.timing_components_ms, "adapter_timing_ms")

        metadata = _safe_mapping(dict(result.metadata), "adapter_metadata")
        timing = {str(key): float(value) for key, value in result.timing_components_ms.items()}
        artifact_root = self.store.run_dir / "artifacts" / job_id
        artifact_rows = tuple(
            _artifact_document(item, artifact_root=artifact_root)
            for item in result.artifacts
        )
        common: dict[str, Any] = {
            "schema_version": "1",
            "run_id": self.spec.run_id,
            "run_spec_fingerprint": self.spec.run_spec_fingerprint,
            "result_set_id": self.spec.result_set_id,
            "algorithm_id": self.spec.algorithm_id,
            "adapter_id": self.spec.adapter_id,
            "adapter_descriptor_fingerprint": self.spec.adapter_descriptor_fingerprint,
            "runtime_identity_fingerprint": self.spec.runtime_identity_fingerprint,
            "job_id": job_id,
            "attempt": attempt,
            "pair": pair,
            "started_utc": started_utc,
            "finished_utc": finished_utc,
            "wall_time_ms": wall_time_ms,
            "adapter_timing_ms": timing,
            "adapter_metadata": metadata,
            "artifacts": artifact_rows,
        }
        if result.status is ExecutionStatus.SUCCESS:
            if result.raw_score is None:
                raise ValueError("successful adapter outcome has no raw score")
            score = float(result.raw_score)
            return TerminalOutcome(
                **common,
                status=Stage21BOutcomeStatus.SUCCESS,
                raw_score=score,
                raw_score_hex=score.hex(),
                failure_classification=None,
                failure_code=None,
                failure_stage=None,
                failure_message=None,
                failure_details={},
            )
        if result.status is not ExecutionStatus.FAILURE or result.failure is None:
            raise ValueError("adapter returned an invalid terminal shape")
        disposition = self.failure_classifier(result.failure)
        if disposition is FailureDisposition.INFRASTRUCTURE:
            raise _ClassifiedInfrastructureFailure(
                code=result.failure.code.value,
                stage=result.failure.stage.value,
                message=result.failure.message,
            )
        if disposition is not FailureDisposition.ALGORITHM:
            raise ValueError("failure classifier returned an unknown disposition")
        details = _safe_mapping(dict(result.failure.details), "failure_details")
        return TerminalOutcome(
            **common,
            status=Stage21BOutcomeStatus.ALGORITHM_FAILURE,
            raw_score=None,
            raw_score_hex=None,
            failure_classification=FailureDisposition.ALGORITHM.value,
            failure_code=result.failure.code.value,
            failure_stage=result.failure.stage.value,
            failure_message=_safe_text(result.failure.message, "failure_message"),
            failure_details=details,
        )

    def _require_frozen_invocation(self, pair: PlannedPair) -> None:
        if self.spec.pair_count != len(self.store.planned_pairs):
            raise Stage21BPreflightError("pair count changed before matcher invocation")
        if pair.ordinal >= len(self.store.planned_pairs):
            raise Stage21BPreflightError("pair ordinal is outside the frozen manifest")
        if self.store.planned_pairs[pair.ordinal] != pair:
            raise Stage21BPreflightError("pair differs from the frozen manifest plan")
        if pair.ground_truth != "NON_MATED":
            raise Stage21BPreflightError("Stage 21B cannot invoke a MATED pair")


def _artifact_document(value: Any, *, artifact_root: Path) -> dict[str, Any]:
    document = {
        "artifact_id": value.artifact_id,
        "kind": value.kind,
        "relative_path": value.relative_path,
        "sha256": value.sha256,
        "size_bytes": value.size_bytes,
        "media_type": value.media_type,
        "metadata": _safe_mapping(dict(value.metadata), "artifact.metadata"),
    }
    _require_no_evaluation_keys(document)
    leaks = find_absolute_paths(document, path="artifact")
    if leaks:
        raise Stage21BPreflightError("adapter artifact reference contains an absolute path")
    root = Path(artifact_root).resolve()
    candidate = (root / str(value.relative_path)).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file() or candidate.is_symlink():
        raise Stage21BPreflightError(
            "adapter artifact reference is absent or outside its immutable job directory"
        )
    digest = hashlib.sha256()
    size = 0
    with candidate.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
            size += len(block)
    if digest.hexdigest() != value.sha256 or size != value.size_bytes:
        raise Stage21BPreflightError(
            "adapter artifact bytes do not match their provenance reference"
        )
    return document


def _require_no_evaluation_keys(value: Any, path: str = "metadata") -> None:
    forbidden = {
        "tar",
        "far",
        "frr",
        "eer",
        "auc",
        "roc",
        "threshold",
        "calibration",
        "normalization",
        "normalisation",
        "ranking",
        "score_sweep",
    }
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if normalized in forbidden:
                raise Stage21BPreflightError(
                    f"Stage 21B adapter payload contains forbidden field {path}.{key}"
                )
            _require_no_evaluation_keys(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _require_no_evaluation_keys(item, f"{path}[{index}]")


def _safe_mapping(value: dict[str, Any], label: str) -> dict[str, str]:
    rendered = {str(key): str(item) for key, item in value.items()}
    oversized = [
        key
        for key, item in rendered.items()
        if len(key) > MAX_METADATA_VALUE_CHARS
        or len(item) > MAX_METADATA_VALUE_CHARS
    ]
    if oversized:
        raise Stage21BPreflightError(
            f"{label} contains an oversized payload under {oversized[0]!r}"
        )
    safe = redact_absolute_paths(rendered)
    leaks = find_absolute_paths(safe, path=label)
    if leaks:
        raise Stage21BPreflightError(f"{label} contains a machine-specific path")
    return dict(safe)


def _safe_text(value: object, label: str) -> str:
    text = " ".join(str(value).split())
    if not text:
        text = label
    safe = str(redact_absolute_paths(text))
    if find_absolute_paths(safe, path=label):
        raise Stage21BPreflightError(f"{label} contains a machine-specific path")
    return safe[:800]


def _safe_message(exc: BaseException) -> str:
    return _safe_text(f"{type(exc).__name__}: {exc}", "infrastructure_failure")


def _job_id(run_id: str, pair_id: str) -> str:
    digest = stable_hash(
        {"schema": "stage21b_job_id_v1", "run_id": run_id, "pair_id": pair_id},
        length=32,
    )
    return f"job21b_{digest}"


def _seed(run_id: str, pair_id: str) -> int:
    encoded = f"stage21b-seed-v1\0{run_id}\0{pair_id}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(encoded).digest()[:4], "big")


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _discard_empty_directory(path: Path) -> None:
    try:
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    except OSError:
        pass
