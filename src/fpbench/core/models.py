"""The shared language of the harness.

Scope note (deliberate): this module currently defines only the models that the
dataset, protocol and manifest-storage layers actually exchange. The execution
side of the vocabulary — ``PreparedImage``, ``RawMatchResult``,
``DecisionResult``, ``FailureInfo``, ``ExecutionProfile``,
``AlgorithmDescriptor`` — is intentionally absent until the runner and the
first adapter exist, because their fields cannot be designed honestly without a
concrete consumer.

Every model here is frozen. Manifests are inputs to many runs; a mutable
manifest row is a reproducibility hazard.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from fpbench.core.enums import (
    CohortRole,
    ChecksumStatus,
    FingerprintPosition,
    GroundTruth,
    Impression,
    ProtocolStage,
)
from fpbench.core.identifiers import CohortId, ImageId, PairId, SubjectId

__all__ = [
    "ImageRecord",
    "SubjectRecord",
    "ComparisonPair",
    "CohortSelection",
    "Cohort",
    "SelfEligibilityRecord",
]


@dataclass(frozen=True, slots=True)
class ImageRecord:
    """One image file that physically exists in a dataset release.

    This describes *what is there*, not what participates in an experiment.
    An image that the protocol will never use is still a valid record.

    Attributes:
        relative_path: Path from the dataset root, always with forward slashes,
            so a manifest produced on Windows resolves on Linux.
        position: The anatomical finger, or ``None`` when the image does not
            depict exactly one finger (a simultaneous-capture slap) or when the
            dataset code has no anatomical meaning.
        effective_ppi: The resolution the harness will treat as true. This is
            not necessarily what the file's metadata declares — see
            ``metadata_ppi`` and docs/adr/0004.
        metadata: Dataset-native fields kept verbatim (e.g. SD300 ``frgp``).
            Anything in here is opaque to the protocol and analysis layers.
        expected_sha256: Digest declared by the dataset publisher. This is
            provenance, not proof that the local bytes match it; see
            ``checksum_status``.
        anomalies: Non-blocking validation findings retained for audit.
        blocking_issues: Validation ERROR codes. A record carrying one remains
            in the image manifest for audit but cannot affect eligibility or
            enter a comparison pair.
    """

    image_id: ImageId
    dataset_id: str
    release: str
    subject_id: SubjectId
    impression: Impression
    position: FingerprintPosition | None
    is_multi_finger: bool
    relative_path: str
    effective_ppi: int
    expected_sha256: str
    metadata_ppi: int | None = None
    checksum_status: ChecksumStatus = ChecksumStatus.NOT_VERIFIED
    metadata: Mapping[str, str] = field(default_factory=dict)
    anomalies: tuple[str, ...] = ()
    blocking_issues: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        digest = self.expected_sha256.lower()
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("expected_sha256 must be a 64-character hexadecimal digest")
        object.__setattr__(self, "expected_sha256", digest)
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
        object.__setattr__(self, "anomalies", tuple(self.anomalies))
        object.__setattr__(self, "blocking_issues", tuple(self.blocking_issues))

    @property
    def is_single_finger(self) -> bool:
        return self.position is not None and not self.is_multi_finger

    @property
    def is_usable(self) -> bool:
        return not self.blocking_issues and self.checksum_status is not ChecksumStatus.MISMATCH


@dataclass(frozen=True, slots=True)
class SubjectRecord:
    """What one release holds for one subject.

    Purely derived from :class:`ImageRecord`; persisted because eligibility
    questions are asked far more often than the image manifest is rebuilt.
    """

    subject_id: SubjectId
    dataset_id: str
    release: str
    image_count: int
    plain_positions: tuple[FingerprintPosition, ...]
    roll_positions: tuple[FingerprintPosition, ...]
    multi_finger_count: int

    def has_all_ten(self, impression: Impression) -> bool:
        positions = (
            self.plain_positions
            if impression is Impression.PLAIN
            else self.roll_positions
        )
        return len(set(positions)) == 10


@dataclass(frozen=True, slots=True)
class ComparisonPair:
    """Two images the protocol asks some algorithm to compare.

    The pair carries no threshold, no algorithm and no score. It is generated
    once and reused by every algorithm (docs/adr/0001).
    """

    pair_id: PairId
    dataset_id: str
    release: str
    left_image_id: ImageId
    right_image_id: ImageId
    ground_truth: GroundTruth
    protocol_stage: ProtocolStage


@dataclass(frozen=True, slots=True)
class CohortSelection:
    """How a cohort came to be, recorded so the selection can be re-derived.

    ``candidate_ids`` is the full eligible pool, not just the winners: without
    it, a later change to the eligibility rules is silent.
    """

    seed: int
    size: int
    candidate_ids: tuple[SubjectId, ...]
    criteria: Mapping[str, str]
    image_manifest_hashes: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_ids", tuple(self.candidate_ids))
        object.__setattr__(self, "criteria", MappingProxyType(dict(self.criteria)))
        object.__setattr__(
            self,
            "image_manifest_hashes",
            MappingProxyType(dict(self.image_manifest_hashes)),
        )

    @property
    def candidate_count(self) -> int:
        return len(self.candidate_ids)


@dataclass(frozen=True, slots=True)
class Cohort:
    """The subjects a protocol run is built from."""

    cohort_id: CohortId
    protocol_id: str
    dataset_id: str
    role: CohortRole
    releases: tuple[str, ...]
    subject_ids: tuple[SubjectId, ...]
    selection: CohortSelection


@dataclass(frozen=True, slots=True)
class SelfEligibilityRecord:
    """Per-finger SELF decision derived within one run and decision profile."""

    release: str
    subject_id: SubjectId
    finger_position: FingerprintPosition
    plain_self_passed: bool
    roll_self_passed: bool
    eligible: bool
    exclusion_reason: str | None = None
