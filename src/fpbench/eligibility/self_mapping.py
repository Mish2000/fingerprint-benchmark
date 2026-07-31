"""Finding the three comparisons that concern one finger, in one release.

The protocol produces 6,000 pairs; this module regroups 4,500 of them into 1,500
units of the form *(release, subject, anatomical finger)*, each holding its PLAIN
SELF comparison, its ROLL SELF comparison and the mated PLAIN–ROLL comparison
those two govern.

Everything is derived from the frozen pair manifest and the image manifests —
never from filenames. A mapping rebuilt by parsing names would be a second
implementation of the protocol, free to disagree with the one that generated the
pairs, and the disagreement would show up as a conditional report over the wrong
comparisons.

The validation here is unusually blunt: every way the mapping could be wrong is
a hard error rather than a skipped unit. A missing ROLL SELF does not mean
"exclude this finger"; it means the pair manifest and the protocol disagree, and
no eligibility answer derived from it would mean anything (docs/adr/0023).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

from fpbench.core.eligibility_models import SelfEligibilityUnit, eligibility_unit_id
from fpbench.core.enums import ExecutionStatus, GroundTruth, Impression, ProtocolStage
from fpbench.core.errors import SelfMappingError
from fpbench.core.identifiers import ImageId, PairId
from fpbench.core.models import ComparisonPair, ImageRecord
from fpbench.core.result_models import RawResultRecord
from fpbench.core.serialization import freeze_str_mapping

__all__ = [
    "SelfIndependenceRequirement",
    "DEFAULT_SELF_INDEPENDENCE",
    "UnitKey",
    "build_self_eligibility_units",
    "require_self_independence_evidence",
]

#: (release, subject, canonical finger). The release is in the key because the
#: same finger scanned at 500 and at 2000 ppi is two measurements, and a rule
#: about "this finger" that spanned them would silently mix resolutions.
UnitKey = tuple[str, str, int]


@dataclass(frozen=True, slots=True)
class SelfIndependenceRequirement:
    """What a SELF result must prove before it may decide anything.

    A SELF comparison is an image against *itself*. If an adapter extracted one
    template and matched it with itself, the comparison would score perfectly
    and prove nothing — and the whole point of the SELF stage is to detect
    fingers a matcher cannot handle. So a SELF result has to carry evidence that
    both sides were extracted independently.

    These are adapter-contract terms, not one algorithm's vocabulary, and the
    requirement is a parameter so that an adapter which words its evidence
    differently can supply its own.
    """

    required_metadata: Mapping[str, str] = field(
        default_factory=lambda: {
            "extraction_policy": "independent_both_sides",
            "extraction_count": "2",
            "template_cache": "disabled",
        }
    )
    forbid_artifacts: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "required_metadata",
            freeze_str_mapping(self.required_metadata),
        )


DEFAULT_SELF_INDEPENDENCE = SelfIndependenceRequirement()


def build_self_eligibility_units(
    *,
    pairs: Sequence[ComparisonPair],
    images: Mapping[ImageId, ImageRecord],
    jobs_by_pair: Mapping[str, str],
    protocol_id: str,
    cohort_id: str,
) -> tuple[SelfEligibilityUnit, ...]:
    """Group the protocol's comparisons into eligibility units.

    Args:
        jobs_by_pair: ``pair_id -> job_id`` from the execution plan. Units cite
            jobs as well as pairs, because decisions are keyed by job.

    Returns:
        One unit per (release, subject, finger), in a deterministic order:
        release, then subject, then finger.

    Raises:
        SelfMappingError: any unit is missing a comparison, has two of one, or
            links comparisons that do not belong to the same finger.
    """
    plain_self: dict[UnitKey, ComparisonPair] = {}
    roll_self: dict[UnitKey, ComparisonPair] = {}
    mated: dict[UnitKey, ComparisonPair] = {}

    for pair in pairs:
        stage = pair.protocol_stage
        if stage is ProtocolStage.PLAIN_ROLL_NON_MATED:
            continue  # impostor pairs concern two fingers and govern no unit
        if stage is ProtocolStage.PLAIN_SELF:
            key = _self_unit_key(pair, images, Impression.PLAIN)
            _claim(plain_self, key, pair, "PLAIN SELF")
        elif stage is ProtocolStage.ROLL_SELF:
            key = _self_unit_key(pair, images, Impression.ROLL)
            _claim(roll_self, key, pair, "ROLL SELF")
        elif stage is ProtocolStage.PLAIN_ROLL_MATED:
            key = _mated_unit_key(pair, images)
            _claim(mated, key, pair, "mated PLAIN-ROLL")

    keys = sorted(set(plain_self) | set(roll_self) | set(mated))
    units: list[SelfEligibilityUnit] = []
    for key in keys:
        release, subject, finger = key
        where = f"{release}/{subject}/finger {finger}"
        plain_pair = _require(plain_self, key, "PLAIN SELF", where)
        roll_pair = _require(roll_self, key, "ROLL SELF", where)
        mated_pair = _require(mated, key, "mated PLAIN-ROLL", where)

        units.append(
            SelfEligibilityUnit(
                eligibility_unit_id=eligibility_unit_id(
                    protocol_id=protocol_id,
                    cohort_id=cohort_id,
                    release=release,
                    subject_id=subject,
                    canonical_finger=finger,
                ),
                release=release,
                subject_id=subject,
                canonical_finger=finger,
                plain_self_pair_id=str(plain_pair.pair_id),
                plain_self_job_id=_job_for(jobs_by_pair, plain_pair),
                roll_self_pair_id=str(roll_pair.pair_id),
                roll_self_job_id=_job_for(jobs_by_pair, roll_pair),
                mated_pair_id=str(mated_pair.pair_id),
                mated_job_id=_job_for(jobs_by_pair, mated_pair),
            )
        )

    identifiers = [unit.eligibility_unit_id for unit in units]
    if len(set(identifiers)) != len(identifiers):
        raise SelfMappingError(
            "two eligibility units derived the same id; the protocol, cohort, "
            "release, subject and finger together must be unique"
        )
    return tuple(units)


def require_self_independence_evidence(
    *,
    results: Iterable[RawResultRecord],
    requirement: SelfIndependenceRequirement = DEFAULT_SELF_INDEPENDENCE,
) -> None:
    """Refuse SELF results that do not prove two independent extractions.

    Only successful results are checked: a comparison that produced no score
    made no claim about how it was performed, and its eligibility contribution
    is ``UNDECIDABLE`` regardless.

    Raises:
        SelfMappingError: a SELF result cannot support a conclusion about the
            finger it concerns.
    """
    for record in results:
        if record.status is not ExecutionStatus.SUCCESS:
            continue
        for key, expected in requirement.required_metadata.items():
            actual = record.adapter_metadata.get(key)
            if actual is None:
                raise SelfMappingError(
                    f"SELF result {record.job_id} does not record {key}; without it "
                    "there is no evidence both sides were extracted independently, "
                    "and a self-comparison that reused one template proves nothing"
                )
            if actual != expected:
                raise SelfMappingError(
                    f"SELF result {record.job_id} records {key}={actual!r}, "
                    f"expected {expected!r}"
                )
        if requirement.forbid_artifacts and record.artifacts:
            raise SelfMappingError(
                f"SELF result {record.job_id} carries a stored template artefact; "
                "this stage stores none, and a cached template is exactly what the "
                "independence requirement rules out"
            )


# ----------------------------------------------------------------- internals


def _image(images: Mapping[ImageId, ImageRecord], image_id: ImageId, pair: ComparisonPair) -> ImageRecord:
    record = images.get(image_id)
    if record is None:
        raise SelfMappingError(
            f"pair {pair.pair_id} names image {image_id}, which is not in the image "
            "manifest"
        )
    if record.position is None:
        raise SelfMappingError(
            f"pair {pair.pair_id} uses image {image_id}, which depicts no single "
            "anatomical finger and cannot belong to an eligibility unit"
        )
    return record


def _self_unit_key(
    pair: ComparisonPair,
    images: Mapping[ImageId, ImageRecord],
    impression: Impression,
) -> UnitKey:
    """The unit a SELF pair belongs to, with the pair's own shape checked."""
    if pair.left_image_id != pair.right_image_id:
        raise SelfMappingError(
            f"{pair.protocol_stage.value} pair {pair.pair_id} compares two different "
            "images; a SELF comparison is an image against itself"
        )
    left = _image(images, pair.left_image_id, pair)
    if left.impression is not impression:
        raise SelfMappingError(
            f"{pair.protocol_stage.value} pair {pair.pair_id} uses a "
            f"{left.impression.value} image; the stage requires {impression.value}"
        )
    if left.release != pair.release:
        raise SelfMappingError(
            f"pair {pair.pair_id} is filed under release {pair.release} but its "
            f"image belongs to {left.release}"
        )
    return (left.release, str(left.subject_id), int(left.position))


def _mated_unit_key(
    pair: ComparisonPair, images: Mapping[ImageId, ImageRecord]
) -> UnitKey:
    """The unit a mated PLAIN-ROLL pair belongs to, fully cross-checked."""
    left = _image(images, pair.left_image_id, pair)
    right = _image(images, pair.right_image_id, pair)

    if pair.ground_truth is not GroundTruth.MATED:
        raise SelfMappingError(
            f"pair {pair.pair_id} is staged as mated but its ground truth is "
            f"{pair.ground_truth.value}"
        )
    if left.impression is not Impression.PLAIN or right.impression is not Impression.ROLL:
        raise SelfMappingError(
            f"mated pair {pair.pair_id} must compare a plain left side with a "
            f"rolled right side, got {left.impression.value}/{right.impression.value}"
        )
    if left.release != right.release:
        raise SelfMappingError(
            f"mated pair {pair.pair_id} spans releases {left.release} and "
            f"{right.release}; eligibility is per release"
        )
    if left.release != pair.release:
        raise SelfMappingError(
            f"pair {pair.pair_id} is filed under release {pair.release} but its "
            f"images belong to {left.release}"
        )
    if left.subject_id != right.subject_id:
        raise SelfMappingError(
            f"mated pair {pair.pair_id} spans two subjects"
        )
    if left.position != right.position:
        raise SelfMappingError(
            f"mated pair {pair.pair_id} compares finger {int(left.position)} with "
            f"finger {int(right.position)}; a mated pair is one finger"
        )
    return (left.release, str(left.subject_id), int(left.position))


def _claim(
    registry: dict[UnitKey, ComparisonPair],
    key: UnitKey,
    pair: ComparisonPair,
    label: str,
) -> None:
    existing = registry.get(key)
    if existing is not None:
        release, subject, finger = key
        raise SelfMappingError(
            f"{release}/{subject}/finger {finger} has two {label} comparisons "
            f"({existing.pair_id} and {pair.pair_id}); the protocol defines one"
        )
    registry[key] = pair


def _require(
    registry: Mapping[UnitKey, ComparisonPair],
    key: UnitKey,
    label: str,
    where: str,
) -> ComparisonPair:
    pair = registry.get(key)
    if pair is None:
        raise SelfMappingError(
            f"{where} has no {label} comparison; every eligibility unit needs all "
            "three, and a missing one means the pair manifest and the protocol "
            "disagree"
        )
    return pair


def _job_for(jobs_by_pair: Mapping[str, str], pair: ComparisonPair) -> str:
    job_id = jobs_by_pair.get(str(pair.pair_id))
    if job_id is None:
        raise SelfMappingError(
            f"pair {pair.pair_id} has no planned job; it was never executed and "
            "cannot contribute to eligibility"
        )
    return job_id
