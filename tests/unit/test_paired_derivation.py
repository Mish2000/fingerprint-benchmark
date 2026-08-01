"""Aligning, recording, auditing and counting two derivations of the same pairs.

The properties here are the ones that make the comparison mean anything:

*It joins the right rows.* By ``pair_id``, with the job ids allowed to differ
and everything else required to match.

*It refuses to compare misaligned rows.* A missing pair, a duplicate, a swapped
orientation — each is fatal rather than skipped.

*It preserves failure.* ``UNDECIDABLE`` never becomes ``NON_MATCH``, and a pair
where either side produced no score has no delta at all.

*It subtracts only what may be subtracted.* Two rates over different eligible
populations are reported side by side with an explicit refusal, not as a
difference.
"""

from __future__ import annotations

import pytest

from fpbench.core.enums import (
    ComparabilityStatus,
    DecisionOutcome,
    ExecutionStatus,
    FailureCode,
    ProtocolStage,
    ScoreRelation,
)
from fpbench.core.errors import (
    ControlAuditError,
    PairedAlignmentError,
    PairedSourceMismatchError,
)
from fpbench.core.paired_models import (
    ALL_TRANSITION_KEYS,
    ELIGIBILITY_FAMILY,
    MATED_COMMON_ELIGIBLE_FAMILY,
    MATED_UNCONDITIONAL_FAMILY,
    NEGATIVE_SANITY_FAMILY,
    PLAIN_SELF_FAMILY,
    ROLL_SELF_FAMILY,
    exact_rate_difference,
)
from fpbench.paired import (
    align_pairs,
    build_common_eligible_view,
    build_control_audit,
    build_eligibility_transitions,
    build_paired_observations,
    build_paired_records,
    build_transition_counts,
    release_order,
    require_clean_control,
    require_comparable_runs,
)
from fpbench.paired.derive import ALL_ELIGIBILITY_KEYS, OBSERVATION_IDS
from pairedworld import CONTROL_RELEASE, RELEASES, build_paired_world

pytestmark = [pytest.mark.paired_evaluation]

_POLICY_FINGERPRINT = "a" * 64


@pytest.fixture()
def world():
    return build_paired_world()


def _derive(world):
    pair_ids = align_pairs(native=world.native, canonical=world.canonical)
    records = build_paired_records(
        native=world.native, canonical=world.canonical, pair_ids=pair_ids
    )
    transitions = build_eligibility_transitions(
        native=world.native, canonical=world.canonical
    )
    common = build_common_eligible_view(
        native=world.native,
        canonical=world.canonical,
        transitions=transitions,
        records=records,
    )
    return records, transitions, common


# ------------------------------------------------------------------- align


def test_the_two_runs_are_comparable(world):
    require_comparable_runs(native=world.native, canonical=world.canonical)


@pytest.mark.parametrize(
    ("field", "value"),
    (("timeout_seconds", 61.0), ("deterministic_seed", 99)),
)
def test_an_operational_execution_field_difference_is_refused(world, field, value):
    setattr(world.canonical.run.execution_profile, field, value)
    with pytest.raises(PairedSourceMismatchError, match=field):
        require_comparable_runs(native=world.native, canonical=world.canonical)


def test_a_replicate_difference_is_refused(world):
    world.canonical.run.replicate_index = 1
    with pytest.raises(PairedSourceMismatchError, match="replicate_index"):
        require_comparable_runs(native=world.native, canonical=world.canonical)


@pytest.mark.parametrize("parameter", ("retry_policy", "execution_mode", "workers"))
def test_an_arbitrary_non_preparation_parameter_is_refused(world, parameter):
    world.canonical.run.execution_profile.parameters = {
        **world.canonical.run.execution_profile.parameters,
        parameter: "different",
    }
    with pytest.raises(PairedSourceMismatchError, match="operational parameter"):
        require_comparable_runs(native=world.native, canonical=world.canonical)


def test_the_two_exact_execution_profile_ids_are_required(world):
    world.canonical.run.execution_profile.profile_id = "canonical_other_v1"
    with pytest.raises(PairedSourceMismatchError, match="must use execution profile"):
        require_comparable_runs(native=world.native, canonical=world.canonical)


def test_alignment_returns_every_pair_in_manifest_order(world):
    pair_ids = align_pairs(native=world.native, canonical=world.canonical)
    assert pair_ids == world.pair_ids


def test_a_missing_canonical_pair_is_refused():
    world = build_paired_world(drop_canonical_pair="sd300a_s0001_f01_mated")
    with pytest.raises(PairedAlignmentError, match="not in the canonical"):
        align_pairs(native=world.native, canonical=world.canonical)


def test_a_duplicated_canonical_pair_is_refused():
    world = build_paired_world(duplicate_canonical_pair="sd300a_s0001_f01_mated")
    with pytest.raises(PairedAlignmentError, match="more than once"):
        align_pairs(native=world.native, canonical=world.canonical)


def test_a_swapped_orientation_is_refused():
    """Probe and candidate are fixed. Reversing them is a different comparison."""
    world = build_paired_world(swap_canonical_sides="sd300a_s0001_f01_mated")
    with pytest.raises(PairedAlignmentError, match="left image|right image"):
        align_pairs(native=world.native, canonical=world.canonical)


def test_different_job_ids_are_expected_and_accepted(world):
    native_jobs = set(world.native.jobs_by_pair.values())
    canonical_jobs = set(world.canonical.jobs_by_pair.values())
    assert not (native_jobs & canonical_jobs)
    assert align_pairs(native=world.native, canonical=world.canonical)


# ------------------------------------------------------------------ records


def test_every_pair_produces_one_record(world):
    records, _, _ = _derive(world)
    assert len(records) == len(world.comparisons)
    assert [str(record.pair_id) for record in records] == list(world.pair_ids)


def test_a_record_carries_both_sides(world):
    records, _, _ = _derive(world)
    record = records[0]
    assert record.native_job_id != record.canonical_job_id
    assert record.native_raw_result_hash != record.canonical_raw_result_hash
    assert record.record_hash


def test_a_moved_score_is_recorded_with_its_exact_delta():
    world = build_paired_world(
        scores={("sd300b_s0001_f01_mated", ProtocolStage.PLAIN_ROLL_MATED): (39.5, 41.25)}
    )
    records, _, _ = _derive(world)
    record = next(r for r in records if str(r.pair_id) == "sd300b_s0001_f01_mated")
    assert record.score_relation is ScoreRelation.CANONICAL_HIGHER
    assert record.score_delta_decimal == "1.75"
    assert record.native_outcome is DecisionOutcome.NON_MATCH
    assert record.canonical_outcome is DecisionOutcome.MATCH


def test_a_failed_side_has_no_delta_and_no_relation():
    world = build_paired_world(
        scores={("sd300b_s0001_f01_mated", ProtocolStage.PLAIN_ROLL_MATED): (60.0, None)}
    )
    records, _, _ = _derive(world)
    record = next(r for r in records if str(r.pair_id) == "sd300b_s0001_f01_mated")
    assert record.score_relation is ScoreRelation.UNAVAILABLE
    assert record.score_delta_decimal is None
    assert record.canonical_outcome is DecisionOutcome.UNDECIDABLE
    # And it is not a non-match.
    assert record.canonical_outcome is not DecisionOutcome.NON_MATCH


def test_both_sides_failing_is_still_a_recorded_transition():
    world = build_paired_world(
        scores={("sd300b_s0002_f01_mated", ProtocolStage.PLAIN_ROLL_MATED): (None, None)}
    )
    records, _, _ = _derive(world)
    record = next(r for r in records if str(r.pair_id) == "sd300b_s0002_f01_mated")
    assert record.transition == "undecidable_to_undecidable"
    assert record.native_execution_status is ExecutionStatus.FAILURE
    assert record.canonical_execution_status is ExecutionStatus.FAILURE
    assert record.native_failure_code == FailureCode.NO_SCORE.value
    assert record.canonical_failure_code == FailureCode.NO_SCORE.value


# ------------------------------------------------------------------ control


def test_the_control_passes_when_sd300a_reproduces(world):
    records, _, _ = _derive(world)
    audit = build_control_audit(records)
    expected = sum(1 for item in world.comparisons if item.release == CONTROL_RELEASE)
    assert audit.planned_sd300a_pairs == expected
    assert audit.equal_scores == expected
    assert audit.equal_decisions == expected
    assert audit.is_clean
    require_clean_control(audit)


def test_one_unequal_sd300a_score_fails_the_control():
    world = build_paired_world(
        scores={("sd300a_s0001_f01_mated", ProtocolStage.PLAIN_ROLL_MATED): (60.0, 60.5)}
    )
    records, _, _ = _derive(world)
    audit = build_control_audit(records)
    assert not audit.is_clean
    with pytest.raises(ControlAuditError):
        require_clean_control(audit)


def test_an_equal_score_with_a_different_status_fails_the_control():
    world = build_paired_world(
        scores={("sd300a_s0002_f01_mated", ProtocolStage.PLAIN_ROLL_MATED): (60.0, None)}
    )
    records, _, _ = _derive(world)
    audit = build_control_audit(records)
    assert not audit.is_clean
    assert audit.compared_scores < audit.planned_sd300a_pairs


def test_a_difference_outside_sd300a_does_not_fail_the_control():
    world = build_paired_world(
        scores={("sd300c_s0001_f01_mated", ProtocolStage.PLAIN_ROLL_MATED): (60.0, 20.0)}
    )
    records, _, _ = _derive(world)
    assert build_control_audit(records).is_clean


def test_the_control_does_not_round(world):
    """A difference far below display precision still fails."""
    broken = build_paired_world(
        scores={
            ("sd300a_s0001_f01_mated", ProtocolStage.PLAIN_ROLL_MATED): (
                60.0,
                60.00000001,
            )
        }
    )
    records, _, _ = _derive(broken)
    assert not build_control_audit(records).is_clean


def test_the_control_compares_failure_codes_exactly():
    pair_id = "sd300a_s0001_f01_mated"
    world = build_paired_world(
        scores={(pair_id, ProtocolStage.PLAIN_ROLL_MATED): (None, None)}
    )
    canonical_job = world.canonical.jobs_by_pair[pair_id]
    result = world.canonical.result_store.read_raw_result(
        world.canonical.run.run_id, canonical_job
    )
    result.failure.code = FailureCode.TIMEOUT
    records, _, _ = _derive(world)
    audit = build_control_audit(records)
    assert not audit.is_clean
    assert any("failure code changed" in issue for issue in audit.issues)


# ------------------------------------------------------------- eligibility


def test_every_unit_produces_one_transition(world):
    _, transitions, _ = _derive(world)
    assert len(transitions) == len(world.native.eligibility_records)
    assert [item.ordinal for item in transitions] == list(range(len(transitions)))


def test_common_eligible_requires_both_sides_eligible(world):
    _, transitions, common = _derive(world)
    for entry in common:
        expected = (
            entry.native_eligibility_status == "eligible"
            and entry.canonical_eligibility_status == "eligible"
        )
        assert entry.included is expected


def test_a_unit_eligible_on_one_side_only_is_excluded():
    """A ROLL SELF that matches natively and not canonically drops the finger."""
    world = build_paired_world(
        scores={("sd300b_s0003_f01_rollself", ProtocolStage.ROLL_SELF): (85.0, 10.0)}
    )
    _, transitions, common = _derive(world)
    transition = next(
        item
        for item in transitions
        if item.release == "SD300B" and item.finger_id == 1 and item.subject_id == "s0003"
    )
    assert transition.native_status == "eligible"
    assert transition.canonical_status == "ineligible"
    assert not transition.common_eligible

    entry = next(
        item for item in common if str(item.pair_id) == "sd300b_s0003_f01_mated"
    )
    assert entry.included is False


def test_excluded_rows_stay_in_the_view(world):
    """A view that dropped them could not state its own selection fraction."""
    broken = build_paired_world(
        scores={("sd300c_s0001_f02_rollself", ProtocolStage.ROLL_SELF): (85.0, 10.0)}
    )
    _, _, common = _derive(broken)
    mated = sum(
        1
        for item in broken.comparisons
        if item.stage is ProtocolStage.PLAIN_ROLL_MATED
    )
    assert len(common) == mated
    assert any(not entry.included for entry in common)


# ------------------------------------------------------------- transitions


def test_every_family_is_counted_at_every_scope(world):
    records, transitions, common = _derive(world)
    counts = build_transition_counts(
        records=records,
        transitions=transitions,
        common_eligible=common,
        releases=release_order(world.native),
        source_fingerprints={},
    )
    families = {record.family for record in counts}
    assert families == {
        PLAIN_SELF_FAMILY,
        ROLL_SELF_FAMILY,
        MATED_UNCONDITIONAL_FAMILY,
        MATED_COMMON_ELIGIBLE_FAMILY,
        NEGATIVE_SANITY_FAMILY,
        ELIGIBILITY_FAMILY,
    }
    scopes = {record.scope.label for record in counts}
    assert scopes == {*RELEASES, "pooled"}
    assert len(counts) == len(families) * (len(RELEASES) + 1)


def test_every_cell_is_present_even_when_zero(world):
    records, transitions, common = _derive(world)
    counts = build_transition_counts(
        records=records,
        transitions=transitions,
        common_eligible=common,
        releases=release_order(world.native),
        source_fingerprints={},
    )
    for record in counts:
        expected = (
            ALL_ELIGIBILITY_KEYS
            if record.family == ELIGIBILITY_FAMILY
            else ALL_TRANSITION_KEYS
        )
        assert set(record.counts) == set(expected)
        assert len(record.counts) == 9


def test_pooled_counts_are_the_sum_of_the_release_counts(world):
    records, transitions, common = _derive(world)
    counts = build_transition_counts(
        records=records,
        transitions=transitions,
        common_eligible=common,
        releases=release_order(world.native),
        source_fingerprints={},
    )
    by_key = {(record.family, record.scope.label): record for record in counts}
    for family in {record.family for record in counts}:
        pooled = by_key[(family, "pooled")]
        for cell in pooled.counts:
            assert pooled.counts[cell] == sum(
                by_key[(family, release)].counts[cell] for release in RELEASES
            )
        assert pooled.total == sum(
            by_key[(family, release)].total for release in RELEASES
        )


def test_every_row_lands_in_exactly_one_cell(world):
    records, transitions, common = _derive(world)
    counts = build_transition_counts(
        records=records,
        transitions=transitions,
        common_eligible=common,
        releases=release_order(world.native),
        source_fingerprints={},
    )
    for record in counts:
        assert sum(record.counts.values()) == record.total


# ------------------------------------------------------------ observations


def test_every_rate_is_observed_at_every_scope(world):
    records, transitions, common = _derive(world)
    observations = build_paired_observations(
        records=records,
        transitions=transitions,
        common_eligible=common,
        releases=release_order(world.native),
        policy_fingerprint=_POLICY_FINGERPRINT,
    )
    assert len(observations) == len(OBSERVATION_IDS) * (len(RELEASES) + 1)
    assert {item.observation_id for item in observations} == set(OBSERVATION_IDS)


def test_attempt_rates_are_directly_comparable(world):
    records, transitions, common = _derive(world)
    observations = build_paired_observations(
        records=records,
        transitions=transitions,
        common_eligible=common,
        releases=release_order(world.native),
        policy_fingerprint=_POLICY_FINGERPRINT,
    )
    for observation in observations:
        if observation.observation_id in {
            "plain_self_attempt_match_fraction",
            "roll_self_attempt_match_fraction",
            "self_eligibility_fraction",
            "mated_unconditional_attempt_non_success_fraction",
            "negative_sanity_attempt_match_fraction",
        }:
            assert observation.native_denominator == observation.canonical_denominator
            assert observation.comparability is ComparabilityStatus.DIRECTLY_COMPARABLE
            assert observation.has_difference


def test_per_run_conditional_rates_are_never_subtracted(world):
    """Their denominators are each run's own eligible set (spec section 41)."""
    records, transitions, common = _derive(world)
    observations = build_paired_observations(
        records=records,
        transitions=transitions,
        common_eligible=common,
        releases=release_order(world.native),
        policy_fingerprint=_POLICY_FINGERPRINT,
    )
    conditional = [
        item
        for item in observations
        if item.observation_id == "per_run_conditional_mated_decision_fnmr"
    ]
    assert conditional
    for observation in conditional:
        assert observation.comparability in {
            ComparabilityStatus.DIFFERENT_SELECTION,
            ComparabilityStatus.UNDEFINED,
        }
        assert not observation.has_difference


def _decided_mated_observations(world):
    records, transitions, common = _derive(world)
    return [
        observation
        for observation in build_paired_observations(
            records=records,
            transitions=transitions,
            common_eligible=common,
            releases=release_order(world.native),
            policy_fingerprint=_POLICY_FINGERPRINT,
        )
        if observation.scope.label == "pooled"
        and observation.observation_id
        in {
            "mated_unconditional_decision_fnmr",
            "common_eligible_mated_decision_fnmr",
        }
    ]


def test_identical_decided_pair_sets_are_directly_comparable():
    pair_id = "sd300b_s0001_f01_mated"
    observations = _decided_mated_observations(
        build_paired_world(
            scores={(pair_id, ProtocolStage.PLAIN_ROLL_MATED): (None, None)}
        )
    )
    assert observations
    assert all(
        item.comparability is ComparabilityStatus.DIRECTLY_COMPARABLE
        and item.has_difference
        for item in observations
    )


def test_equal_failure_counts_on_different_pairs_are_not_subtracted():
    observations = _decided_mated_observations(
        build_paired_world(
            scores={
                ("sd300b_s0001_f02_mated", ProtocolStage.PLAIN_ROLL_MATED): (
                    None,
                    60.0,
                ),
                ("sd300b_s0002_f01_mated", ProtocolStage.PLAIN_ROLL_MATED): (
                    60.0,
                    None,
                ),
            }
        )
    )
    assert observations
    assert all(
        item.native_denominator == item.canonical_denominator
        and item.comparability
        is ComparabilityStatus.SAME_ATTEMPTS_DIFFERENT_DECIDED_SUBSETS
        and not item.has_difference
        for item in observations
    )


def test_different_failure_counts_are_not_subtracted():
    observations = _decided_mated_observations(
        build_paired_world(
            scores={
                ("sd300b_s0001_f02_mated", ProtocolStage.PLAIN_ROLL_MATED): (
                    None,
                    60.0,
                )
            }
        )
    )
    assert observations
    assert all(
        item.comparability
        is ComparabilityStatus.SAME_ATTEMPTS_DIFFERENT_DECIDED_SUBSETS
        and not item.has_difference
        for item in observations
    )


def test_the_common_eligible_denominators_are_identical(world):
    records, transitions, common = _derive(world)
    observations = build_paired_observations(
        records=records,
        transitions=transitions,
        common_eligible=common,
        releases=release_order(world.native),
        policy_fingerprint=_POLICY_FINGERPRINT,
    )
    for observation in observations:
        if observation.observation_id.startswith("common_eligible_mated_attempt"):
            assert observation.native_denominator == observation.canonical_denominator


def test_a_difference_is_the_exact_reduced_fraction(world):
    records, transitions, common = _derive(world)
    observations = build_paired_observations(
        records=records,
        transitions=transitions,
        common_eligible=common,
        releases=release_order(world.native),
        policy_fingerprint=_POLICY_FINGERPRINT,
    )
    for observation in observations:
        if not observation.has_difference:
            continue
        assert exact_rate_difference(
            native_numerator=observation.native_numerator,
            native_denominator=observation.native_denominator,
            canonical_numerator=observation.canonical_numerator,
            canonical_denominator=observation.canonical_denominator,
        ) == (observation.difference_numerator, observation.difference_denominator)


def test_a_zero_denominator_is_undefined_rather_than_zero():
    """Every SELF fails on one side, so nothing is common-eligible."""
    scores = {}
    for release in RELEASES:
        for subject in range(1, 4):
            for finger in (1, 2):
                slug = f"{release.lower()}_s{subject:04d}_f{finger:02d}"
                scores[(f"{slug}_plainself", ProtocolStage.PLAIN_SELF)] = (90.0, 90.0)
                scores[(f"{slug}_rollself", ProtocolStage.ROLL_SELF)] = (10.0, 10.0)
    world = build_paired_world(scores=scores)
    records, transitions, common = _derive(world)
    assert not any(entry.included for entry in common)

    observations = build_paired_observations(
        records=records,
        transitions=transitions,
        common_eligible=common,
        releases=release_order(world.native),
        policy_fingerprint=_POLICY_FINGERPRINT,
    )
    conditional = [
        item
        for item in observations
        if item.observation_id == "common_eligible_mated_decision_fnmr"
    ]
    assert conditional
    for observation in conditional:
        assert observation.comparability is ComparabilityStatus.UNDEFINED
        assert not observation.has_difference


def test_a_negative_difference_is_supported(world):
    """Canonical below native is a real, signed finding."""
    broken = build_paired_world(
        scores={
            ("sd300b_s0003_f01_plainself", ProtocolStage.PLAIN_SELF): (90.0, 10.0)
        }
    )
    records, transitions, common = _derive(broken)
    observations = build_paired_observations(
        records=records,
        transitions=transitions,
        common_eligible=common,
        releases=release_order(broken.native),
        policy_fingerprint=_POLICY_FINGERPRINT,
    )
    observation = next(
        item
        for item in observations
        if item.observation_id == "plain_self_attempt_match_fraction"
        and item.scope.label == "SD300B"
    )
    assert observation.canonical_numerator < observation.native_numerator
    assert observation.difference_numerator < 0
