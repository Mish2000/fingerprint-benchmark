"""The vocabulary of a single comparison.

These models sit between the protocol and an algorithm. Everything here
describes *how a comparison was carried out and what came back* — never what
the comparison means. There is no threshold, no decision, no ground truth and
no protocol stage anywhere in this module, and that absence is the point
(docs/adr/0003, docs/adr/0010).

Every model is frozen, and every mapping and sequence is re-frozen in
``__post_init__``. A caller that keeps a reference to the dict it passed in
must not be able to change a stored result afterwards.

Invariants are enforced at construction rather than checked by the caller, so
an adapter cannot hand back a result that is internally contradictory. The
runner still re-validates defensively: an adapter that bypasses the
constructor is a bug to be recorded, not a crash (docs/adr/0006).
"""

from __future__ import annotations

import math
import platform
import sys
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import Mapping

from fpbench.core.enums import (
    ChecksumStatus,
    EnvironmentStatus,
    ExecutionStatus,
    FailureCode,
    FailureStage,
    ScoreDirection,
)
from fpbench.core.identifiers import ImageId, validate_id
from fpbench.core.serialization import freeze_str_mapping as _freeze_str_mapping
from fpbench.core.serialization import stable_hash

__all__ = [
    "PreparedImage",
    "ArtifactReference",
    "FailureInfo",
    "RawMatchResult",
    "AlgorithmDescriptor",
    "EnvironmentReport",
    "ExecutionProfile",
    "ComparisonContext",
    "TimingBreakdown",
    "descriptor_fingerprint",
    "environment_fingerprint",
    "execution_profile_fingerprint",
    "runtime_description",
    "FINGERPRINT_LENGTH",
]

#: Fingerprints are full SHA-256 hex digests. Truncation happens where an
#: identifier needs to be short (``run_id``), never in the fingerprint itself.
FINGERPRINT_LENGTH = 64

#: Slack allowed when checking that a total duration covers its parts. The
#: segments are measured separately, so float rounding can leave the sum a hair
#: above the total without anything actually being wrong.
_TIMING_TOLERANCE_MS = 1.0

_HEX = frozenset("0123456789abcdef")


# ---------------------------------------------------------------- validation


def _require_sha256(value: str, field_name: str) -> str:
    digest = value.strip().lower()
    if len(digest) != 64 or not set(digest) <= _HEX:
        raise ValueError(f"{field_name} must be a 64-character hexadecimal digest")
    return digest


def _require_non_empty(value: str, field_name: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError(f"{field_name} must not be empty")
    return text


def _require_finite_non_negative(value: float, field_name: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{field_name} must be a finite, non-negative number")
    return number


def _freeze_timing_mapping(
    value: Mapping[str, float], field_name: str
) -> Mapping[str, float]:
    return MappingProxyType(
        {
            str(key): _require_finite_non_negative(item, f"{field_name}[{key}]")
            for key, item in dict(value).items()
        }
    )


def _require_relative_path(value: str, field_name: str) -> str:
    text = _require_non_empty(value, field_name)
    if PurePosixPath(text).is_absolute() or PureWindowsPath(text).is_absolute():
        raise ValueError(f"{field_name} must be workspace-relative, got {text!r}")
    if ".." in PurePosixPath(text.replace("\\", "/")).parts:
        raise ValueError(f"{field_name} must not escape the workspace, got {text!r}")
    return text


def _require_absolute(path: Path, field_name: str) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        raise ValueError(f"{field_name} must be an absolute path, got {candidate}")
    return candidate


def _require_positive_timeout(value: float) -> float:
    timeout = float(value)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout_seconds must be a finite positive number")
    return timeout


# ------------------------------------------------------------- prepared image


@dataclass(frozen=True, slots=True)
class PreparedImage:
    """One image, ready to hand to an adapter.

    Carries the provenance an adapter may legitimately need — resolution, media
    type, the publisher's digest and whether the local bytes were checked
    against it — and nothing that would let it infer what the comparison is
    for. There is no subject, no finger, no impression and no pair here.

    ``local_path`` is absolute and valid only for the lifetime of the run. It is
    deliberately never written into a stored result: a result that embeds one
    machine's paths is not portable evidence.
    """

    image_id: ImageId
    local_path: Path
    effective_ppi: int
    media_type: str
    expected_sha256: str
    checksum_status: ChecksumStatus
    preparation_profile_id: str
    preparation_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "local_path", _require_absolute(self.local_path, "local_path")
        )
        if int(self.effective_ppi) <= 0:
            raise ValueError("effective_ppi must be positive")
        object.__setattr__(self, "effective_ppi", int(self.effective_ppi))
        object.__setattr__(
            self, "media_type", _require_non_empty(self.media_type, "media_type")
        )
        object.__setattr__(
            self,
            "expected_sha256",
            _require_sha256(self.expected_sha256, "expected_sha256"),
        )
        object.__setattr__(
            self,
            "preparation_hash",
            _require_sha256(self.preparation_hash, "preparation_hash"),
        )
        validate_id(self.preparation_profile_id)


# ------------------------------------------------------------------ artifacts


@dataclass(frozen=True, slots=True)
class ArtifactReference:
    """A pointer to a file an adapter produced, never the file's contents.

    Templates, minutiae files and converted images can be large; a result row
    holds a reference and a digest so the payload can be verified later without
    bloating the result store. Paths are workspace-relative so an artefact
    written on one machine can still be found on another.
    """

    artifact_id: str
    kind: str
    relative_path: str
    sha256: str
    size_bytes: int
    media_type: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "artifact_id", _require_non_empty(self.artifact_id, "artifact_id")
        )
        object.__setattr__(self, "kind", _require_non_empty(self.kind, "kind"))
        object.__setattr__(
            self,
            "relative_path",
            _require_relative_path(self.relative_path, "relative_path"),
        )
        object.__setattr__(self, "sha256", _require_sha256(self.sha256, "sha256"))
        if int(self.size_bytes) < 0:
            raise ValueError("size_bytes must not be negative")
        object.__setattr__(self, "size_bytes", int(self.size_bytes))
        object.__setattr__(self, "metadata", _freeze_str_mapping(self.metadata))


# ------------------------------------------------------------------- failures


@dataclass(frozen=True, slots=True)
class FailureInfo:
    """Why a comparison produced no score.

    Everything here may end up in a report, so it must be safe to show: a short
    message, no traceback, no absolute dataset path. The exception type belongs
    in ``details`` when it helps; the stack trace belongs in the log.
    """

    code: FailureCode
    stage: FailureStage
    message: str
    retryable: bool = False
    details: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "message", _require_non_empty(self.message, "message"))
        object.__setattr__(self, "details", _freeze_str_mapping(self.details))


# ------------------------------------------------------------------ raw result


@dataclass(frozen=True, slots=True)
class RawMatchResult:
    """What an adapter returns: a score, or a reason there is none.

    Never a decision. ``raw_score`` is the algorithm's own number in the
    algorithm's own scale; turning it into MATCH or NON_MATCH happens elsewhere,
    later, possibly several times against the same stored score
    (docs/adr/0003).

    Prefer :meth:`success` and :meth:`failed` over the constructor — they make
    the two valid shapes hard to confuse.
    """

    status: ExecutionStatus
    raw_score: float | None
    score_direction: ScoreDirection
    failure: FailureInfo | None = None
    artifacts: tuple[ArtifactReference, ...] = ()
    timing_components_ms: Mapping[str, float] = field(default_factory=dict)
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifacts", tuple(self.artifacts))
        object.__setattr__(
            self,
            "timing_components_ms",
            _freeze_timing_mapping(self.timing_components_ms, "timing_components_ms"),
        )
        object.__setattr__(self, "metadata", _freeze_str_mapping(self.metadata))

        if self.status is ExecutionStatus.SUCCESS:
            if self.raw_score is None:
                raise ValueError("a successful result must carry a score")
            if self.failure is not None:
                raise ValueError("a successful result must not carry a failure")
            score = float(self.raw_score)
            if not math.isfinite(score):
                raise ValueError("raw_score must be finite")
            object.__setattr__(self, "raw_score", score)
        else:
            if self.raw_score is not None:
                raise ValueError("a failed result must not carry a score")
            if self.failure is None:
                raise ValueError("a failed result must explain itself")

        identifiers = [artifact.artifact_id for artifact in self.artifacts]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("artifact_id must be unique within a result")

    @classmethod
    def success(
        cls,
        *,
        raw_score: float,
        score_direction: ScoreDirection,
        artifacts: tuple[ArtifactReference, ...] = (),
        timing_components_ms: Mapping[str, float] | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> "RawMatchResult":
        return cls(
            status=ExecutionStatus.SUCCESS,
            raw_score=raw_score,
            score_direction=score_direction,
            failure=None,
            artifacts=artifacts,
            timing_components_ms=timing_components_ms or {},
            metadata=metadata or {},
        )

    @classmethod
    def failed(
        cls,
        *,
        failure: FailureInfo,
        score_direction: ScoreDirection,
        artifacts: tuple[ArtifactReference, ...] = (),
        timing_components_ms: Mapping[str, float] | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> "RawMatchResult":
        return cls(
            status=ExecutionStatus.FAILURE,
            raw_score=None,
            score_direction=score_direction,
            failure=failure,
            artifacts=artifacts,
            timing_components_ms=timing_components_ms or {},
            metadata=metadata or {},
        )


# ----------------------------------------------------------------- algorithms


@dataclass(frozen=True, slots=True)
class AlgorithmDescriptor:
    """Everything about an algorithm that could change its results.

    The version fields are separate on purpose. ``adapter_version`` moves when
    this repository's wrapper changes; ``implementation_version`` moves when the
    matcher underneath it does. Conflating them makes it impossible to say which
    one explains a difference in results.
    """

    algorithm_id: str
    display_name: str
    adapter_id: str
    adapter_version: str
    adapter_contract_version: str
    implementation_version: str
    score_direction: ScoreDirection
    deterministic: bool
    capabilities: tuple[str, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Only the two identifiers are constrained to the id charset. Versions
        # are opaque strings on purpose: a real adapter may want "1.4.2",
        # "dummy-sha256-v1" or a container digest there.
        validate_id(self.algorithm_id)
        validate_id(self.adapter_id)
        for name in (
            "display_name",
            "adapter_version",
            "adapter_contract_version",
            "implementation_version",
        ):
            object.__setattr__(
                self, name, _require_non_empty(getattr(self, name), name)
            )
        object.__setattr__(
            self,
            "capabilities",
            tuple(sorted({str(item) for item in self.capabilities})),
        )
        object.__setattr__(self, "metadata", _freeze_str_mapping(self.metadata))


def descriptor_fingerprint(descriptor: AlgorithmDescriptor) -> str:
    """A 64-character digest of everything that makes results comparable.

    ``display_name`` is excluded: it exists to be read by people, and renaming a
    matcher in a report must not invalidate results that are otherwise
    identical.
    """
    return stable_hash(
        {
            "schema": "algorithm_descriptor_fingerprint_v1",
            "algorithm_id": descriptor.algorithm_id,
            "adapter_id": descriptor.adapter_id,
            "adapter_version": descriptor.adapter_version,
            "adapter_contract_version": descriptor.adapter_contract_version,
            "implementation_version": descriptor.implementation_version,
            "score_direction": descriptor.score_direction.value,
            "deterministic": descriptor.deterministic,
            "capabilities": list(descriptor.capabilities),
            "metadata": dict(descriptor.metadata),
        },
        length=FINGERPRINT_LENGTH,
    )


# ---------------------------------------------------------------- environment


@dataclass(frozen=True, slots=True)
class EnvironmentReport:
    """Whether an adapter can run here, and on top of what.

    The runner refuses to start a run whose adapter reports ``UNAVAILABLE``. A
    missing dependency is one fault of the run, not six thousand identical
    per-pair failures.
    """

    status: EnvironmentStatus
    implementation_version: str
    runtime: Mapping[str, str] = field(default_factory=dict)
    dependencies: Mapping[str, str] = field(default_factory=dict)
    message: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "implementation_version",
            _require_non_empty(self.implementation_version, "implementation_version"),
        )
        object.__setattr__(self, "runtime", _freeze_str_mapping(self.runtime))
        object.__setattr__(
            self, "dependencies", _freeze_str_mapping(self.dependencies)
        )

    @property
    def is_ready(self) -> bool:
        return self.status is EnvironmentStatus.READY


def environment_fingerprint(report: EnvironmentReport) -> str:
    """A 64-character digest of the environment a result was produced in.

    ``message`` is excluded — it is diagnostic prose, not a property of the
    environment.
    """
    return stable_hash(
        {
            "schema": "environment_fingerprint_v1",
            "status": report.status.value,
            "implementation_version": report.implementation_version,
            "runtime": dict(report.runtime),
            "dependencies": dict(report.dependencies),
        },
        length=FINGERPRINT_LENGTH,
    )


def runtime_description() -> Mapping[str, str]:
    """The interpreter facts every in-process adapter shares."""
    return MappingProxyType(
        {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": platform.system(),
            "machine": platform.machine(),
            "pointer_size": str(sys.maxsize.bit_length() + 1),
        }
    )


# ------------------------------------------------------------------- profiles


@dataclass(frozen=True, slots=True)
class ExecutionProfile:
    """How images are prepared, and how long an adapter may take.

    Contains no threshold and no decision profile. Two runs that differ only in
    threshold share an execution profile and therefore share their raw scores;
    that is what makes re-thresholding free (docs/adr/0003).
    """

    profile_id: str
    preparer_id: str
    timeout_seconds: float
    deterministic_seed: int
    parameters: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        validate_id(self.profile_id)
        validate_id(self.preparer_id)
        object.__setattr__(
            self, "timeout_seconds", _require_positive_timeout(self.timeout_seconds)
        )
        object.__setattr__(self, "deterministic_seed", int(self.deterministic_seed))
        object.__setattr__(self, "parameters", _freeze_str_mapping(self.parameters))


def execution_profile_fingerprint(profile: ExecutionProfile) -> str:
    """A 64-character digest of the execution profile."""
    return stable_hash(
        {
            "schema": "execution_profile_fingerprint_v1",
            "profile_id": profile.profile_id,
            "preparer_id": profile.preparer_id,
            "timeout_seconds": profile.timeout_seconds,
            "deterministic_seed": profile.deterministic_seed,
            "parameters": dict(profile.parameters),
        },
        length=FINGERPRINT_LENGTH,
    )


# -------------------------------------------------------------------- context


@dataclass(frozen=True, slots=True)
class ComparisonContext:
    """The operational facts an adapter is allowed to know.

    Note what is absent: no ``pair_id``, no ``protocol_stage``, no
    ``ground_truth``, no subject, no finger, no threshold. An adapter that
    cannot tell a genuine pair from an impostor pair cannot accidentally treat
    them differently, and ``job_id`` is a hash precisely so that nothing about
    the pair can be read back out of it (docs/adr/0010).
    """

    run_id: str
    job_id: str
    attempt: int
    working_directory: Path
    artifact_directory: Path
    timeout_seconds: float
    deterministic_seed: int

    def __post_init__(self) -> None:
        validate_id(self.run_id)
        validate_id(self.job_id)
        if int(self.attempt) < 1:
            raise ValueError("attempt is 1-based")
        object.__setattr__(self, "attempt", int(self.attempt))
        object.__setattr__(
            self,
            "working_directory",
            _require_absolute(self.working_directory, "working_directory"),
        )
        object.__setattr__(
            self,
            "artifact_directory",
            _require_absolute(self.artifact_directory, "artifact_directory"),
        )
        object.__setattr__(
            self, "timeout_seconds", _require_positive_timeout(self.timeout_seconds)
        )
        object.__setattr__(self, "deterministic_seed", int(self.deterministic_seed))


# --------------------------------------------------------------------- timing


@dataclass(frozen=True, slots=True)
class TimingBreakdown:
    """Where the wall clock went.

    ``total_ms`` excludes writing the result, so that comparing two algorithms
    compares the algorithms and not the disk underneath them.
    """

    preparation_ms: float
    adapter_ms: float
    total_ms: float
    adapter_components_ms: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("preparation_ms", "adapter_ms", "total_ms"):
            object.__setattr__(
                self, name, _require_finite_non_negative(getattr(self, name), name)
            )
        object.__setattr__(
            self,
            "adapter_components_ms",
            _freeze_timing_mapping(self.adapter_components_ms, "adapter_components_ms"),
        )
        parts = self.preparation_ms + self.adapter_ms
        if self.total_ms + _TIMING_TOLERANCE_MS < parts:
            raise ValueError(
                f"total_ms ({self.total_ms:.3f}) is smaller than the sum of its "
                f"parts ({parts:.3f}); a total must cover what it contains"
            )
