from __future__ import annotations

from collections import Counter
from dataclasses import replace

import pytest

from fpbench.core.enums import (
    CohortRole,
    FingerprintPosition,
    GroundTruth,
    Impression,
    ProtocolStage,
)
from fpbench.core.errors import ProtocolError
from fpbench.core.models import Cohort, CohortSelection, ImageRecord
from fpbench.protocols.pair_generation import (
    PairPlan,
    build_image_index,
    generate_pairs,
)

RELEASE = "SD300A"
SUBJECTS = ("00001000", "00001001")


def image(subject, impression, position, *, multi=False):
    label = position.label if position is not None else "frgp13"
    return ImageRecord(
        image_id=f"sd300a_{subject}_{impression.value}_{label}",
        dataset_id="sd300",
        release=RELEASE,
        subject_id=subject,
        impression=impression,
        position=position,
        is_multi_finger=multi,
        relative_path=f"{subject}_{impression.value}_{label}.png",
        effective_ppi=500,
        expected_sha256="0" * 64,
    )


def images(subjects=SUBJECTS):
    result = []
    for subject in subjects:
        for position in FingerprintPosition:
            result.append(image(subject, Impression.PLAIN, position))
            result.append(image(subject, Impression.ROLL, position))
        result.append(image(subject, Impression.PLAIN, None, multi=True))
    return result


def cohort(subjects=SUBJECTS):
    return Cohort(
        cohort_id="c",
        protocol_id="p",
        dataset_id="sd300",
        role=CohortRole.TEST,
        releases=(RELEASE,),
        subject_ids=subjects,
        selection=CohortSelection(
            seed=1,
            size=len(subjects),
            candidate_ids=subjects,
            criteria={},
            image_manifest_hashes={RELEASE: "a" * 64},
        ),
    )


def test_multi_finger_images_never_reach_the_index():
    index = build_image_index(images())
    assert all(key[3] is not None for key in index)
    assert len(index) == len(SUBJECTS) * 10 * 2


def test_duplicate_slots_are_rejected():
    duplicated = images() + [image(SUBJECTS[0], Impression.PLAIN, FingerprintPosition.RIGHT_THUMB)]
    with pytest.raises(ProtocolError):
        build_image_index(duplicated)


def test_every_stage_produces_one_pair_per_subject_and_finger():
    pairs = generate_pairs(cohort(), images(), PairPlan())
    counts = Counter(pair.protocol_stage for pair in pairs)
    expected = len(SUBJECTS) * 10
    assert counts == {stage: expected for stage in ProtocolStage}


def test_self_pairs_compare_an_image_with_itself():
    pairs = generate_pairs(cohort(), images(), PairPlan())
    for pair in pairs:
        if pair.protocol_stage.is_self:
            assert pair.left_image_id == pair.right_image_id
            assert pair.ground_truth is GroundTruth.MATED


def test_mated_pairs_join_plain_to_roll_for_the_same_finger():
    pairs = [
        p
        for p in generate_pairs(cohort(), images(), PairPlan())
        if p.protocol_stage is ProtocolStage.PLAIN_ROLL_MATED
    ]
    for pair in pairs:
        assert "_plain_" in pair.left_image_id
        assert "_roll_" in pair.right_image_id
        assert pair.left_image_id.split("_")[-1] == pair.right_image_id.split("_")[-1]
        assert pair.ground_truth is GroundTruth.MATED


def test_non_mated_pairs_use_a_different_finger_of_the_same_subject():
    pairs = [
        p
        for p in generate_pairs(cohort(), images(), PairPlan())
        if p.protocol_stage is ProtocolStage.PLAIN_ROLL_NON_MATED
    ]
    assert pairs
    for pair in pairs:
        left_subject = pair.left_image_id.split("_")[1]
        right_subject = pair.right_image_id.split("_")[1]
        assert left_subject == right_subject
        assert pair.left_image_id.split("_")[-1] != pair.right_image_id.split("_")[-1]
        assert pair.ground_truth is GroundTruth.NON_MATED


def test_the_impostor_shift_wraps_at_ten():
    pairs = {
        p.left_image_id: p.right_image_id
        for p in generate_pairs(cohort(), images(), PairPlan())
        if p.protocol_stage is ProtocolStage.PLAIN_ROLL_NON_MATED
    }
    assert pairs[f"sd300a_{SUBJECTS[0]}_plain_f10"].endswith("_roll_f01")


def test_a_shift_of_ten_would_produce_mated_pairs_and_is_rejected():
    with pytest.raises(ProtocolError):
        PairPlan(non_mated_finger_shift=10)


def test_stages_can_be_switched_off_individually():
    plan = PairPlan(plain_self=False, roll_self=False, plain_roll_non_mated=False)
    stages = {p.protocol_stage for p in generate_pairs(cohort(), images(), plan)}
    assert stages == {ProtocolStage.PLAIN_ROLL_MATED}


def test_pair_ids_are_unique_and_generation_is_deterministic():
    first = generate_pairs(cohort(), images(), PairPlan())
    second = generate_pairs(cohort(), images(), PairPlan())
    assert first == second
    assert len({pair.pair_id for pair in first}) == len(first)


def test_an_incomplete_subject_is_a_hard_error():
    """The cohort criteria are supposed to have excluded it; silence would hide a bug."""
    incomplete = [
        img
        for img in images()
        if not (
            img.subject_id == SUBJECTS[0]
            and img.impression is Impression.ROLL
            and img.position is FingerprintPosition.LEFT_INDEX
        )
    ]
    with pytest.raises(ProtocolError):
        generate_pairs(cohort(), incomplete, PairPlan())


def test_a_blocked_image_cannot_enter_the_pair_index():
    blocked = replace(images()[0], blocking_issues=("png_header_unreadable",))
    index = build_image_index([blocked])
    assert index == {}


def test_image_metadata_is_defensively_frozen():
    source = {"frgp": "11"}
    record = replace(images()[0], metadata=source)
    source["frgp"] = "99"
    assert record.metadata["frgp"] == "11"
    with pytest.raises(TypeError):
        record.metadata["frgp"] = "12"
