"""The SELF-filtered view of the pair manifest.

The protocol reports the PLAIN-ROLL stage twice:

  a. over all 500 pairs;
  b. over only those pairs whose finger survived both SELF stages.

A finger that fails either SELF stage disqualifies its PLAIN-ROLL pair — it is
enough for a finger to fail in PLAIN SELF, regardless of how it did in ROLL
SELF.

This is a *derived view*, never a mutation: ``pairs.parquet`` stays exactly as
generated. Per-finger eligibility is persisted beneath the run and decision
profile that produced it, because thresholds and algorithm versions change the
answer. A pair that fails SELF is not deleted from the protocol; it simply does
not appear in result (b).

The function takes the set of disqualified fingers as an argument rather than
reading results itself, so it stays independent of how results are stored.
"""

from __future__ import annotations

from typing import AbstractSet, Iterable, Mapping, Sequence

from fpbench.core.enums import FingerprintPosition, ProtocolStage
from fpbench.core.errors import ProtocolError
from fpbench.core.identifiers import ImageId, PairId, SubjectId
from fpbench.core.models import ComparisonPair, ImageRecord, SelfEligibilityRecord

__all__ = [
    "FingerKey",
    "finger_key_of",
    "collect_failed_fingers",
    "build_self_eligibility",
    "select_self_eligible_pairs",
]

#: Identifies one anatomical finger of one subject within one release.
FingerKey = tuple[str, SubjectId, FingerprintPosition]


def finger_key_of(image: ImageRecord) -> FingerKey:
    if image.position is None:
        raise ProtocolError(
            f"image {image.image_id} has no anatomical finger and cannot be "
            f"used in SELF filtering"
        )
    return (image.release, image.subject_id, image.position)


def _index_images(images: Iterable[ImageRecord]) -> Mapping[ImageId, ImageRecord]:
    return {image.image_id: image for image in images}


def collect_failed_fingers(
    pairs: Sequence[ComparisonPair],
    images: Iterable[ImageRecord],
    failed_pair_ids: AbstractSet[PairId],
) -> frozenset[FingerKey]:
    """Map failed SELF pairs back to the fingers they disqualify.

    ``failed_pair_ids`` is whatever the caller counts as a failure — a
    non-match, an extraction failure, or both. That judgement belongs to the
    analysis layer, not here; this function only performs the mapping.

    Pairs from non-SELF stages are ignored, so the full pair manifest can be
    passed in without pre-filtering.
    """
    by_id = _index_images(images)
    failed: set[FingerKey] = set()
    for pair in pairs:
        if not pair.protocol_stage.is_self or pair.pair_id not in failed_pair_ids:
            continue
        image = by_id.get(pair.left_image_id)
        if image is None:
            raise ProtocolError(
                f"pair {pair.pair_id} references unknown image {pair.left_image_id}"
            )
        failed.add(finger_key_of(image))
    return frozenset(failed)


def build_self_eligibility(
    pairs: Sequence[ComparisonPair],
    images: Iterable[ImageRecord],
    failed_pair_ids: AbstractSet[PairId],
) -> tuple[SelfEligibilityRecord, ...]:
    """Build the explicit per-finger decision table for one decision profile."""
    by_id = _index_images(images)
    stages: dict[FingerKey, dict[ProtocolStage, bool]] = {}
    for pair in pairs:
        if not pair.protocol_stage.is_self:
            continue
        image = by_id.get(pair.left_image_id)
        if image is None:
            raise ProtocolError(
                f"pair {pair.pair_id} references unknown image {pair.left_image_id}"
            )
        key = finger_key_of(image)
        per_stage = stages.setdefault(key, {})
        if pair.protocol_stage in per_stage:
            raise ProtocolError(
                f"duplicate {pair.protocol_stage.value} pair for {key}"
            )
        per_stage[pair.protocol_stage] = pair.pair_id not in failed_pair_ids

    records: list[SelfEligibilityRecord] = []
    required = (ProtocolStage.PLAIN_SELF, ProtocolStage.ROLL_SELF)
    for key in sorted(stages):
        per_stage = stages[key]
        missing = [stage.value for stage in required if stage not in per_stage]
        if missing:
            raise ProtocolError(f"missing SELF stage(s) {missing} for {key}")
        plain_passed = per_stage[ProtocolStage.PLAIN_SELF]
        roll_passed = per_stage[ProtocolStage.ROLL_SELF]
        reasons = []
        if not plain_passed:
            reasons.append("plain_self_failed")
        if not roll_passed:
            reasons.append("roll_self_failed")
        records.append(
            SelfEligibilityRecord(
                release=key[0],
                subject_id=key[1],
                finger_position=key[2],
                plain_self_passed=plain_passed,
                roll_self_passed=roll_passed,
                eligible=not reasons,
                exclusion_reason=";".join(reasons) or None,
            )
        )
    return tuple(records)


def select_self_eligible_pairs(
    pairs: Sequence[ComparisonPair],
    images: Iterable[ImageRecord],
    failed_fingers: AbstractSet[FingerKey],
    *,
    stages: Sequence[ProtocolStage] = (
        ProtocolStage.PLAIN_ROLL_MATED,
        ProtocolStage.PLAIN_ROLL_NON_MATED,
    ),
) -> tuple[ComparisonPair, ...]:
    """The subset of ``stages`` pairs where neither side's finger failed SELF.

    Both sides are checked: a non-mated pair joins two different fingers, and a
    failure on either of them makes the comparison uninformative.
    """
    by_id = _index_images(images)
    wanted = set(stages)
    eligible: list[ComparisonPair] = []

    for pair in pairs:
        if pair.protocol_stage not in wanted:
            continue
        sides = (pair.left_image_id, pair.right_image_id)
        keys = []
        for image_id in sides:
            image = by_id.get(image_id)
            if image is None:
                raise ProtocolError(
                    f"pair {pair.pair_id} references unknown image {image_id}"
                )
            keys.append(finger_key_of(image))
        if not any(key in failed_fingers for key in keys):
            eligible.append(pair)

    return tuple(eligible)
