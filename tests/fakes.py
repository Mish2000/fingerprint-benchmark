"""Adapters and preparers that exist only to put the runner under pressure.

None of these is registered in the production registry, and none of them is
importable from ``fpbench``. They are misbehaving on purpose: an adapter that
throws, one that returns NaN, one that contradicts its own descriptor. The
runner has to turn each of them into a recorded failure rather than a lost run,
and the only way to know it does is to have specimens.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from fpbench.adapters.base import ADAPTER_CONTRACT_VERSION, FingerprintAlgorithmAdapter
from fpbench.core.enums import (
    ChecksumStatus,
    EnvironmentStatus,
    FailureCode,
    FailureStage,
    FingerprintPosition,
    GroundTruth,
    Impression,
    ProtocolStage,
    ScoreDirection,
)
from fpbench.core.execution_models import (
    AlgorithmDescriptor,
    ComparisonContext,
    EnvironmentReport,
    ExecutionProfile,
    FailureInfo,
    PreparedImage,
    RawMatchResult,
    runtime_description,
)
from fpbench.core.identifiers import ImageId, PairId, SubjectId
from fpbench.core.models import ComparisonPair, ImageRecord
from fpbench.imaging.base import ImagePreparer
from fpbench.imaging.identity import IdentityImagePreparer

__all__ = [
    "sha256_of",
    "image_record",
    "comparison_pair",
    "fake_descriptor",
    "CountingAdapter",
    "FailingAdapter",
    "ExplodingAdapter",
    "TimingOutAdapter",
    "NaNAdapter",
    "WrongDirectionAdapter",
    "UnavailableAdapter",
    "StrayWriteAdapter",
    "CountingPreparer",
    "ExplodingPreparer",
    "SometimesFailingAdapter",
    "InterruptingAdapter",
]

FIXED_SCORE = 42.5


def sha256_of(payload: bytes | str) -> str:
    data = payload.encode("utf-8") if isinstance(payload, str) else payload
    return hashlib.sha256(data).hexdigest()


def image_record(
    *,
    image_id: str,
    relative_path: str,
    expected_sha256: str,
    subject_id: str = "00001000",
    release: str = "SD300A",
    impression: Impression = Impression.PLAIN,
    effective_ppi: int = 500,
    checksum_status: ChecksumStatus = ChecksumStatus.NOT_VERIFIED,
    blocking_issues: tuple[str, ...] = (),
    position: FingerprintPosition | None = None,
) -> ImageRecord:
    """A minimal image record.

    ``position`` defaults to ``None`` because most tests do not care which
    finger a record depicts. Anything that groups records into anatomical units
    — SELF eligibility, for one — does care, and has to say so.
    """
    return ImageRecord(
        image_id=ImageId(image_id),
        dataset_id="sd300",
        release=release,
        subject_id=SubjectId(subject_id),
        impression=impression,
        position=position,
        is_multi_finger=False,
        relative_path=relative_path,
        effective_ppi=effective_ppi,
        expected_sha256=expected_sha256,
        checksum_status=checksum_status,
        blocking_issues=blocking_issues,
    )


def comparison_pair(
    *,
    pair_id: str,
    left_image_id: str,
    right_image_id: str,
    stage: ProtocolStage = ProtocolStage.PLAIN_ROLL_MATED,
    ground_truth: GroundTruth = GroundTruth.MATED,
    release: str = "SD300A",
) -> ComparisonPair:
    return ComparisonPair(
        pair_id=PairId(pair_id),
        dataset_id="sd300",
        release=release,
        left_image_id=ImageId(left_image_id),
        right_image_id=ImageId(right_image_id),
        ground_truth=ground_truth,
        protocol_stage=stage,
    )


def fake_descriptor(
    algorithm_id: str,
    *,
    score_direction: ScoreDirection = ScoreDirection.HIGHER_IS_BETTER,
    deterministic: bool = True,
) -> AlgorithmDescriptor:
    return AlgorithmDescriptor(
        algorithm_id=algorithm_id,
        display_name=f"Test adapter {algorithm_id}",
        adapter_id=algorithm_id,
        adapter_version="1",
        adapter_contract_version=ADAPTER_CONTRACT_VERSION,
        implementation_version="test-1",
        score_direction=score_direction,
        deterministic=deterministic,
    )


class _ReadyAdapter(FingerprintAlgorithmAdapter):
    """Shared plumbing: a valid descriptor, a ready environment, call counting."""

    algorithm_id = "fake_adapter"

    def __init__(self, **descriptor_kwargs) -> None:
        self._descriptor = fake_descriptor(self.algorithm_id, **descriptor_kwargs)
        self.compare_calls = 0
        self.contexts: list[ComparisonContext] = []
        self.prepared: list[tuple[PreparedImage, PreparedImage]] = []

    @property
    def descriptor(self) -> AlgorithmDescriptor:
        return self._descriptor

    def validate_environment(self) -> EnvironmentReport:
        return EnvironmentReport(
            status=EnvironmentStatus.READY,
            implementation_version=self._descriptor.implementation_version,
            runtime=runtime_description(),
            dependencies={},
        )

    def compare(self, left, right, context) -> RawMatchResult:
        self.compare_calls += 1
        self.contexts.append(context)
        self.prepared.append((left, right))
        return self._respond(left, right, context)

    def _respond(self, left, right, context) -> RawMatchResult:
        raise NotImplementedError


class CountingAdapter(_ReadyAdapter):
    """Succeeds with a fixed score. Exists to be counted."""

    algorithm_id = "counting_adapter"

    def _respond(self, left, right, context) -> RawMatchResult:
        return RawMatchResult.success(
            raw_score=FIXED_SCORE,
            score_direction=self.descriptor.score_direction,
            metadata={"probe": "counting"},
        )


class FailingAdapter(_ReadyAdapter):
    """Reports a well-formed failure — the way an adapter is supposed to."""

    algorithm_id = "failing_adapter"

    def _respond(self, left, right, context) -> RawMatchResult:
        return RawMatchResult.failed(
            failure=FailureInfo(
                code=FailureCode.TEMPLATE_EXTRACTION_FAILED,
                stage=FailureStage.EXTRACTION,
                message="no minutiae found",
                retryable=False,
                details={"minutiae": "0"},
            ),
            score_direction=self.descriptor.score_direction,
        )


class ExplodingAdapter(_ReadyAdapter):
    """Raises. Stands in for any adapter bug."""

    algorithm_id = "exploding_adapter"

    def _respond(self, left, right, context) -> RawMatchResult:
        raise RuntimeError("matcher segfaulted spectacularly")


class TimingOutAdapter(_ReadyAdapter):
    """Raises TimeoutError, the one failure the runner marks retryable."""

    algorithm_id = "timing_out_adapter"

    def _respond(self, left, right, context) -> RawMatchResult:
        raise TimeoutError("exceeded the configured budget")


class NaNAdapter(_ReadyAdapter):
    """Returns a NaN score by bypassing the model's own validation.

    An honest adapter cannot build this result; that is the point. It
    reproduces a wrapper that writes into the object after constructing it.
    """

    algorithm_id = "nan_adapter"

    def _respond(self, left, right, context) -> RawMatchResult:
        result = RawMatchResult.success(
            raw_score=1.0, score_direction=self.descriptor.score_direction
        )
        object.__setattr__(result, "raw_score", float("nan"))
        return result


class WrongDirectionAdapter(_ReadyAdapter):
    """Declares one score direction and returns the other."""

    algorithm_id = "wrong_direction_adapter"

    def _respond(self, left, right, context) -> RawMatchResult:
        return RawMatchResult.success(
            raw_score=1.0, score_direction=ScoreDirection.LOWER_IS_BETTER
        )


class UnavailableAdapter(_ReadyAdapter):
    """Cannot run here. Must be caught by preflight, not by 6,000 failures."""

    algorithm_id = "unavailable_adapter"

    def validate_environment(self) -> EnvironmentReport:
        return EnvironmentReport(
            status=EnvironmentStatus.UNAVAILABLE,
            implementation_version=self.descriptor.implementation_version,
            runtime=runtime_description(),
            dependencies={"libmatcher": "missing"},
            message="libmatcher is not installed",
        )

    def _respond(self, left, right, context) -> RawMatchResult:  # pragma: no cover
        raise AssertionError("must never run")


class StrayWriteAdapter(_ReadyAdapter):
    """Writes outside its allotted directories.

    Used to prove the containment check in the contract suite can actually
    fail; a check that never fires is not a check.
    """

    algorithm_id = "stray_write_adapter"

    def __init__(self, target: Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self._target = Path(target)

    def _respond(self, left, right, context) -> RawMatchResult:
        self._target.parent.mkdir(parents=True, exist_ok=True)
        self._target.write_text("I should not be here", encoding="utf-8")
        return RawMatchResult.success(
            raw_score=1.0, score_direction=self.descriptor.score_direction
        )


@dataclass
class CountingPreparer(ImagePreparer):
    """Delegates to the identity preparer and counts how often it was asked.

    SELF comparisons hand the same image in twice; the count is how the tests
    prove the runner does not quietly shortcut the second call.
    """

    delegate: ImagePreparer = None  # type: ignore[assignment]
    calls: int = 0

    def __post_init__(self) -> None:
        if self.delegate is None:
            self.delegate = IdentityImagePreparer()

    @property
    def preparer_id(self) -> str:
        return self.delegate.preparer_id

    def prepare(
        self, image: ImageRecord, dataset_root: Path, profile: ExecutionProfile
    ) -> PreparedImage:
        self.calls += 1
        return self.delegate.prepare(image, dataset_root, profile)


class ExplodingPreparer(ImagePreparer):
    """Raises an unexpected exception before an adapter can be called."""

    @property
    def preparer_id(self) -> str:
        return IdentityImagePreparer().preparer_id

    def prepare(
        self, image: ImageRecord, dataset_root: Path, profile: ExecutionProfile
    ) -> PreparedImage:
        raise RuntimeError("preparer failed unexpectedly")


class SometimesFailingAdapter(_ReadyAdapter):
    """Fails every ``fail_every``-th comparison and scores the rest.

    Stands in for a real matcher on a real dataset, where a handful of images
    simply will not yield a template. A run made of these must still finish and
    still verify (docs/adr/0013).
    """

    algorithm_id = "sometimes_failing_adapter"

    def __init__(self, *, fail_every: int = 3, **kwargs) -> None:
        super().__init__(**kwargs)
        self.fail_every = fail_every

    def _respond(self, left, right, context) -> RawMatchResult:
        if self.compare_calls % self.fail_every == 0:
            return RawMatchResult.failed(
                failure=FailureInfo(
                    code=FailureCode.TEMPLATE_EXTRACTION_FAILED,
                    stage=FailureStage.EXTRACTION,
                    message="no minutiae found",
                ),
                score_direction=self.descriptor.score_direction,
            )
        return RawMatchResult.success(
            raw_score=float(self.compare_calls),
            score_direction=self.descriptor.score_direction,
        )


class InterruptingAdapter(_ReadyAdapter):
    """Raises KeyboardInterrupt once it has been called ``after`` times.

    Reproduces someone pressing Ctrl-C part-way through a long run. The
    exception must travel all the way out: it is not a comparison failure and
    must never be recorded as one.
    """

    algorithm_id = "interrupting_adapter"

    def __init__(self, *, after: int = 3, **kwargs) -> None:
        super().__init__(**kwargs)
        self.after = after

    def _respond(self, left, right, context) -> RawMatchResult:
        if self.compare_calls > self.after:
            raise KeyboardInterrupt("operator stopped the run")
        return RawMatchResult.success(
            raw_score=float(self.compare_calls),
            score_direction=self.descriptor.score_direction,
        )
