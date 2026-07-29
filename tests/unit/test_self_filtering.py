from __future__ import annotations

from fpbench.core.enums import FingerprintPosition, ProtocolStage
from fpbench.protocols.pair_generation import PairPlan, generate_pairs
from fpbench.protocols.self_filtering import (
    build_self_eligibility,
    collect_failed_fingers,
    select_self_eligible_pairs,
)
from test_pair_generation import RELEASE, SUBJECTS, cohort, images

ALL_PAIRS = generate_pairs(cohort(), images(), PairPlan())
THUMB = (RELEASE, SUBJECTS[0], FingerprintPosition.RIGHT_THUMB)


def _cross_impression(pairs):
    return [p for p in pairs if not p.protocol_stage.is_self]


def test_no_failures_leaves_every_cross_impression_pair():
    eligible = select_self_eligible_pairs(ALL_PAIRS, images(), frozenset())
    assert len(eligible) == len(_cross_impression(ALL_PAIRS))


def test_self_stages_are_never_part_of_the_filtered_view():
    eligible = select_self_eligible_pairs(ALL_PAIRS, images(), frozenset())
    assert all(not pair.protocol_stage.is_self for pair in eligible)


def test_a_failed_finger_removes_its_mated_pair():
    eligible = select_self_eligible_pairs(ALL_PAIRS, images(), {THUMB})
    mated = [p for p in eligible if p.protocol_stage is ProtocolStage.PLAIN_ROLL_MATED]
    assert all(not p.pair_id.endswith(f"{SUBJECTS[0]}_f01_mated") for p in mated)


def test_a_failed_finger_removes_impostor_pairs_on_either_side():
    """f01 appears on the left of f01->f02 and on the right of f10->f01."""
    eligible = select_self_eligible_pairs(ALL_PAIRS, images(), {THUMB})
    remaining = {p.pair_id for p in eligible}
    assert f"sd300a_{SUBJECTS[0]}_f01_vs_f02_nonmated" not in remaining
    assert f"sd300a_{SUBJECTS[0]}_f10_vs_f01_nonmated" not in remaining
    # 1 mated + 2 non-mated for this finger, and nothing else.
    assert len(remaining) == len(_cross_impression(ALL_PAIRS)) - 3


def test_other_subjects_are_untouched():
    eligible = select_self_eligible_pairs(ALL_PAIRS, images(), {THUMB})
    assert any(SUBJECTS[1] in p.pair_id and "_f01_" in p.pair_id for p in eligible)


def test_failing_plain_self_alone_is_enough_to_disqualify():
    plain_self = next(
        p for p in ALL_PAIRS if p.protocol_stage is ProtocolStage.PLAIN_SELF
    )
    failed = collect_failed_fingers(ALL_PAIRS, images(), {plain_self.pair_id})
    assert failed == {THUMB}


def test_non_self_failures_are_ignored_when_collecting():
    mated = next(
        p for p in ALL_PAIRS if p.protocol_stage is ProtocolStage.PLAIN_ROLL_MATED
    )
    assert collect_failed_fingers(ALL_PAIRS, images(), {mated.pair_id}) == frozenset()


def test_plain_and_roll_failures_of_the_same_finger_collapse_to_one_key():
    self_pairs = [
        p.pair_id
        for p in ALL_PAIRS
        if p.protocol_stage.is_self
        and p.left_image_id.startswith(f"sd300a_{SUBJECTS[0]}_")
        and p.left_image_id.endswith("_f01")
    ]
    assert len(self_pairs) == 2
    assert collect_failed_fingers(ALL_PAIRS, images(), set(self_pairs)) == {THUMB}


def test_the_original_manifest_is_never_mutated():
    before = list(ALL_PAIRS)
    select_self_eligible_pairs(ALL_PAIRS, images(), {THUMB})
    assert list(ALL_PAIRS) == before


def test_explicit_eligibility_records_keep_plain_and_roll_decisions_separate():
    self_pairs = [
        pair
        for pair in ALL_PAIRS
        if pair.protocol_stage.is_self
        and pair.left_image_id.endswith("_f01")
        and SUBJECTS[0] in pair.left_image_id
    ]
    plain = next(
        pair for pair in self_pairs
        if pair.protocol_stage is ProtocolStage.PLAIN_SELF
    )
    [record] = [
        record
        for record in build_self_eligibility(
            ALL_PAIRS, images(), {plain.pair_id}
        )
        if (record.release, record.subject_id, record.finger_position) == THUMB
    ]
    assert not record.plain_self_passed
    assert record.roll_self_passed
    assert not record.eligible
    assert record.exclusion_reason == "plain_self_failed"
