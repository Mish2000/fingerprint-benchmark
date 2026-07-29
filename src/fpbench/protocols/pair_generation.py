"""Enumerating the comparisons the protocol defines.

Four stages, each producing one pair per (release, subject, finger):

    PLAIN_SELF            plain image against itself
    ROLL_SELF             rolled image against itself
    PLAIN_ROLL_MATED      plain against rolled, same anatomical finger
    PLAIN_ROLL_NON_MATED  plain against rolled, deliberately different finger

For a 50-subject cohort that is 500 pairs per stage per release.

The non-mated stage pairs finger *i* in plain with finger *i + shift* in roll
within the same subject, wrapping around at ten. Same subject, different
anatomical finger, so every such pair is guaranteed to be an impostor while
staying as visually similar as the data allows. The alternative — pairing
across subjects — is easier for a matcher and would understate the false match
rate. See docs/adr/0008.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from fpbench.core.enums import (
    FingerprintPosition,
    GroundTruth,
    Impression,
    ProtocolStage,
)
from fpbench.core.errors import ProtocolError
from fpbench.core.identifiers import PairId, SubjectId, compose_id
from fpbench.core.models import Cohort, ComparisonPair, ImageRecord

__all__ = ["PairPlan", "ImageIndex", "build_image_index", "generate_pairs"]

#: (release, subject, impression, position) -> image
ImageIndex = Mapping[
    tuple[str, SubjectId, Impression, FingerprintPosition], ImageRecord
]


@dataclass(frozen=True, slots=True)
class PairPlan:
    """Which stages to generate, and how the impostor stage is constructed."""

    plain_self: bool = True
    roll_self: bool = True
    plain_roll_mated: bool = True
    plain_roll_non_mated: bool = True
    non_mated_finger_shift: int = 1

    def __post_init__(self) -> None:
        if self.plain_roll_non_mated and self.non_mated_finger_shift % 10 == 0:
            raise ProtocolError(
                "non_mated_finger_shift must not be a multiple of 10: a shift of "
                "zero would pair a finger with itself and produce mated pairs"
            )


def build_image_index(images: Iterable[ImageRecord]) -> ImageIndex:
    """Index single-finger images for pairing.

    Multi-finger simultaneous captures are dropped here — this is the single
    point at which the protocol excludes them, so no later stage has to
    remember to.

    Raises:
        ProtocolError: if two images claim the same slot, which would make
            pairing non-deterministic.
    """
    index: dict[
        tuple[str, SubjectId, Impression, FingerprintPosition], ImageRecord
    ] = {}
    for image in images:
        if not image.is_single_finger or not image.is_usable:
            continue
        key = (image.release, image.subject_id, image.impression, image.position)
        existing = index.get(key)
        if existing is not None:
            raise ProtocolError(
                f"two images map to {key}: {existing.image_id} and {image.image_id}"
            )
        index[key] = image
    return index


def _require(
    index: ImageIndex,
    release: str,
    subject_id: SubjectId,
    impression: Impression,
    position: FingerprintPosition,
) -> ImageRecord:
    try:
        return index[(release, subject_id, impression, position)]
    except KeyError:
        raise ProtocolError(
            f"cohort subject {subject_id} has no usable {impression.value} image for "
            f"{position.label} in {release}; the cohort criteria should have "
            f"excluded this subject"
        ) from None


def _shifted(position: FingerprintPosition, shift: int) -> FingerprintPosition:
    return FingerprintPosition(((position.value - 1 + shift) % 10) + 1)


def generate_pairs(
    cohort: Cohort, images: Sequence[ImageRecord], plan: PairPlan
) -> tuple[ComparisonPair, ...]:
    """Produce every pair the plan calls for, in a stable order.

    Ordering is (release, subject, finger, stage) so regeneration yields a
    semantically identical manifest with the same content hash.
    """
    index = build_image_index(images)
    pairs: list[ComparisonPair] = []

    for release in cohort.releases:
        for subject_id in cohort.subject_ids:
            for position in FingerprintPosition:
                plain = _require(index, release, subject_id, Impression.PLAIN, position)
                roll = _require(index, release, subject_id, Impression.ROLL, position)

                if plan.plain_self:
                    pairs.append(
                        _pair(
                            release,
                            subject_id,
                            position,
                            plain,
                            plain,
                            GroundTruth.MATED,
                            ProtocolStage.PLAIN_SELF,
                            "plain_self",
                        )
                    )
                if plan.roll_self:
                    pairs.append(
                        _pair(
                            release,
                            subject_id,
                            position,
                            roll,
                            roll,
                            GroundTruth.MATED,
                            ProtocolStage.ROLL_SELF,
                            "roll_self",
                        )
                    )
                if plan.plain_roll_mated:
                    pairs.append(
                        _pair(
                            release,
                            subject_id,
                            position,
                            plain,
                            roll,
                            GroundTruth.MATED,
                            ProtocolStage.PLAIN_ROLL_MATED,
                            "mated",
                        )
                    )
                if plan.plain_roll_non_mated:
                    other = _shifted(position, plan.non_mated_finger_shift)
                    impostor = _require(
                        index, release, subject_id, Impression.ROLL, other
                    )
                    pairs.append(
                        _pair(
                            release,
                            subject_id,
                            position,
                            plain,
                            impostor,
                            GroundTruth.NON_MATED,
                            ProtocolStage.PLAIN_ROLL_NON_MATED,
                            f"vs_{other.label}_nonmated",
                        )
                    )

    return tuple(pairs)


def _pair(
    release: str,
    subject_id: SubjectId,
    position: FingerprintPosition,
    left: ImageRecord,
    right: ImageRecord,
    ground_truth: GroundTruth,
    stage: ProtocolStage,
    suffix: str,
) -> ComparisonPair:
    return ComparisonPair(
        pair_id=PairId(
            compose_id(release, subject_id, position.label, suffix)
        ),
        dataset_id=left.dataset_id,
        release=release,
        left_image_id=left.image_id,
        right_image_id=right.image_id,
        ground_truth=ground_truth,
        protocol_stage=stage,
    )
