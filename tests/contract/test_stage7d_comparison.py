"""What a fair comparison refuses, and what it does when the populations differ.

The interesting cases are all failures. A comparison of two chains that were
given the same inputs under the same policies is arithmetic; the questions worth
testing are what happens when one of those premises quietly stops holding —
because that is the state in which a table of numbers still renders and stops
meaning what it says (spec sections 71 to 74).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

import crossalgorithmworld as world
from fpbench.core.enums import (
    CrossAlgorithmPopulation,
    CrossAlgorithmTransitionFamily,
    DecisionOutcome,
    ProtocolStage,
    SelfEligibilityStatus,
)
from fpbench.core.errors import ConfigurationError
from fpbench.cross_algorithm import (
    CrossAlgorithmError,
    build_comparison_records,
    derive_cross_algorithm_evaluation,
    load_comparison_policy,
    render_report,
    report_content_hash,
    require_clean_audit,
    require_complete_matrices,
    require_no_score_comparison,
    verify_derivation,
)
from fpbench.cross_algorithm.align import load_fair_measurement_protocol

pytestmark = pytest.mark.stage7d_contract

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = (
    REPOSITORY_ROOT
    / "configs"
    / "comparisons"
    / "policies"
    / "documented_operating_points_v1.yaml"
)
PROTOCOL_PATH = (
    REPOSITORY_ROOT
    / "configs"
    / "experiments"
    / "stage7d_fair_measurement_protocol_v1.json"
)


def _derive(left, right, pairs, protocol, audit=None):
    audit = audit or world.clean_audit(left, right, protocol)
    require_clean_audit(audit)
    records = build_comparison_records(left=left, right=right, pairs=pairs)
    return audit, derive_cross_algorithm_evaluation(
        definition_fingerprint=world.digest("definition"),
        audit_fingerprint=audit.audit_fingerprint,
        left=left,
        right=right,
        records=records,
        releases=world.RELEASES,
    )


# ------------------------------------------------------- the committed files


def test_the_committed_comparison_policy_loads_and_fingerprints():
    policy = load_comparison_policy(POLICY_PATH)
    assert policy.policy_id == "documented_operating_points_v1"
    assert policy.primary_population == "mated_unconditional_all_attempts"


def test_the_committed_protocol_declares_the_relation_and_no_calibration():
    protocol = load_fair_measurement_protocol(PROTOCOL_PATH)
    assert protocol.operating_point_relation == (
        "independently_documented_not_equated"
    )
    assert protocol.raw_score_comparison is False
    assert protocol.calibration_performed is False
    assert protocol.test_cohort_used is False
    assert (
        protocol.sourceafis_decision_profile_fingerprint
        != protocol.nbis_decision_profile_fingerprint
    )


def test_the_committed_protocol_names_the_committed_policy():
    protocol = load_fair_measurement_protocol(PROTOCOL_PATH)
    assert (
        protocol.comparison_policy_fingerprint
        == load_comparison_policy(POLICY_PATH).policy_fingerprint
    )


@pytest.mark.parametrize(
    "section, key",
    [
        ("scores", "compare_raw"),
        ("scores", "normalise"),
        ("scores", "subtract"),
        ("scores", "correlate"),
        ("statistics", "confidence_intervals"),
        ("statistics", "significance_tests"),
        ("negative_sanity", "label_as_fmr"),
        ("claims", "superiority"),
        ("claims", "causality"),
        ("claims", "equal_fmr"),
        ("operating_points", "calibration_allowed"),
        ("operating_points", "test_cohort_allowed"),
    ],
)
def test_a_policy_that_switches_on_a_refusal_is_rejected(tmp_path, section, key):
    text = POLICY_PATH.read_text(encoding="utf-8")
    lines = []
    seen = False
    for line in text.splitlines():
        if line.startswith(f"{section}:"):
            seen = True
        if seen and line.strip().startswith(f"{key}:"):
            line = line.split(":")[0] + ": true"
            seen = False
        lines.append(line)
    path = tmp_path / "policy.yaml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match=key):
        load_comparison_policy(path)


def test_an_unknown_policy_key_is_refused(tmp_path):
    path = tmp_path / "policy.yaml"
    path.write_text(
        POLICY_PATH.read_text(encoding="utf-8") + "\nextras:\n  anything: true\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError, match="unknown section"):
        load_comparison_policy(path)


def test_a_policy_that_equates_the_operating_points_is_refused(tmp_path):
    path = tmp_path / "policy.yaml"
    path.write_text(
        POLICY_PATH.read_text(encoding="utf-8").replace(
            "relation: independently_documented_not_equated",
            "relation: equal_fmr",
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError, match="not the same operating point"):
        load_comparison_policy(path)


def test_a_protocol_edited_after_committing_no_longer_constructs(tmp_path):
    import json

    payload = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    payload["metric_policy_fingerprint"] = world.digest("something-else")
    path = tmp_path / "protocol.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="protocol_fingerprint"):
        load_fair_measurement_protocol(path)


def test_only_the_late_bound_identities_may_be_bound_afterwards():
    """Section 13: four ids may be filled in, and nothing else may move.

    The committed protocol has all four bound now, so the three cases are:
    rebinding one to the value it already has is a no-op, rebinding it to a
    different value is refused, and a field that was inside the frozen
    fingerprint is refused whatever it is set to.
    """
    protocol = load_fair_measurement_protocol(PROTOCOL_PATH)
    assert protocol.is_bound

    same = protocol.bind(nbis_decision_set_id=protocol.nbis_decision_set_id)
    assert same.protocol_fingerprint == protocol.protocol_fingerprint
    assert same.nbis_decision_set_id == protocol.nbis_decision_set_id

    with pytest.raises(ValueError, match="already bound"):
        protocol.bind(nbis_decision_set_id="decisionset_000000000000")
    with pytest.raises(ValueError, match="may not change"):
        protocol.bind(metric_policy_id="something_else")


def test_binding_an_identity_never_moves_the_protocol_fingerprint():
    """The four late fields sit outside the digest by construction."""
    import dataclasses

    protocol = load_fair_measurement_protocol(PROTOCOL_PATH)
    unbound = dataclasses.replace(
        protocol,
        nbis_decision_set_id=None,
        nbis_eligibility_set_id=None,
        nbis_metric_set_id=None,
        cross_algorithm_evaluation_id=None,
    )
    assert unbound.protocol_fingerprint == protocol.protocol_fingerprint
    assert not unbound.is_bound


# --------------------------------------------------------- the fairness gate


def test_a_fair_world_produces_a_clean_audit():
    left, right, _pairs, protocol = world.build_world()
    assert world.clean_audit(left, right, protocol).is_clean


@pytest.mark.parametrize(
    "override, expected",
    [
        ({"left_calibrated": True}, "left_calibrated"),
        ({"right_calibrated": True}, "right_calibrated"),
        ({"left_test_cohort": True}, "test_cohort_used"),
        ({"right_equated": True}, "operating_points_equated"),
        (
            {"right_metric_policy_fingerprint": world.digest("other")},
            "metric_policy_equal",
        ),
        ({"right_eligibility_policy_version": "2"}, "eligibility_policy_equal"),
        ({"right_execution_profile_hash": "other"}, "execution_profile_equal"),
    ],
)
def test_the_audit_refuses_a_world_that_is_not_comparable(override, expected):
    left, right, _pairs, protocol = world.build_world(**override)
    audit = world.clean_audit(left, right, protocol)
    assert not audit.is_clean
    assert expected in audit.failures
    with pytest.raises(CrossAlgorithmError):
        require_clean_audit(audit)


def test_a_short_pair_set_is_refused():
    left, right, _pairs, protocol = world.build_world()
    trimmed = dataclasses.replace(right, decisions=right.decisions[:-1])
    audit = world.clean_audit(left, trimmed, protocol)
    assert not audit.is_clean
    assert "pair_ids_equal" in audit.failures


def test_one_changed_pair_id_is_refused():
    left, right, pairs, protocol = world.build_world()
    decisions = list(right.decisions)
    decisions[3].pair_id = "pair_somewhere_else"
    moved = dataclasses.replace(right, decisions=tuple(decisions))
    audit = world.clean_audit(left, moved, protocol)
    assert "pair_ids_equal" in audit.failures
    with pytest.raises(CrossAlgorithmError, match="ordinal"):
        build_comparison_records(left=left, right=moved, pairs=pairs)


def test_a_dirty_alignment_is_refused():
    left, right, _pairs, protocol = world.build_world()
    audit = world.clean_audit(
        left, right, protocol, alignment_is_clean=False
    )
    assert "pair_semantics_equal" in audit.failures
    assert "prepared_entries_equal" in audit.failures


def test_an_alignment_the_protocol_does_not_name_is_refused():
    left, right, _pairs, protocol = world.build_world()
    audit = world.clean_audit(
        left, right, protocol, alignment_fingerprint=world.digest("other-alignment")
    )
    assert not audit.is_clean


# --------------------------------------------------------- the populations


def test_equal_eligible_sets_are_marked_same_population():
    left, right, pairs, protocol = world.build_world()
    _audit, derivation = _derive(left, right, pairs, protocol)
    conditional = _observation(
        derivation, "plain_roll_mated_conditional_non_success_rate_attempt", "pooled"
    )
    assert conditional.population is CrossAlgorithmPopulation.SAME_POPULATION


def test_different_eligible_sets_leave_the_conditional_difference_undefined():
    """Spec section 73: a side-specific conditional delta is not defined."""
    key = world.outcome_key(ProtocolStage.PLAIN_SELF, "SD300A", 0)
    left, right, pairs, protocol = world.build_world(
        right_outcomes={key: "non_match"}
    )
    _audit, derivation = _derive(left, right, pairs, protocol)

    conditional = _observation(
        derivation, "plain_roll_mated_conditional_non_success_rate_attempt", "pooled"
    )
    assert conditional.population is (
        CrossAlgorithmPopulation.DIFFERENT_ELIGIBLE_POPULATIONS
    )
    assert conditional.difference_numerator is None

    # The unconditional denominator stays the full population on both sides.
    unconditional = _observation(
        derivation,
        "plain_roll_mated_unconditional_non_success_rate_attempt",
        "pooled",
    )
    assert unconditional.left_denominator == unconditional.right_denominator
    assert unconditional.left_denominator == world.total_units()
    assert unconditional.population is CrossAlgorithmPopulation.SAME_POPULATION

    # The common-eligible denominator is the intersection, identical both sides.
    common = _observation(
        derivation,
        "plain_roll_mated_common_eligible_non_success_rate_attempt",
        "pooled",
    )
    assert common.left_denominator == common.right_denominator
    assert common.left_denominator == len(derivation.common_eligible)
    assert common.left_denominator < world.total_units()
    assert common.population is CrossAlgorithmPopulation.COMMON_ELIGIBLE_POPULATION


def test_the_common_eligible_set_is_the_intersection():
    left_key = world.outcome_key(ProtocolStage.PLAIN_SELF, "SD300A", 0)
    right_key = world.outcome_key(ProtocolStage.ROLL_SELF, "SD300B", 1)
    left, right, pairs, protocol = world.build_world(
        left_outcomes={left_key: "non_match"},
        right_outcomes={right_key: "non_match"},
    )
    _audit, derivation = _derive(left, right, pairs, protocol)
    assert len(derivation.common_eligible) == world.total_units() - 2
    for entry in derivation.common_eligible:
        transition = next(
            item
            for item in derivation.transitions
            if item.eligibility_unit_id == entry.eligibility_unit_id
        )
        assert transition.left_status is SelfEligibilityStatus.ELIGIBLE
        assert transition.right_status is SelfEligibilityStatus.ELIGIBLE


def test_the_eligibility_transition_matrix_has_all_nine_cells():
    left, right, pairs, protocol = world.build_world()
    _audit, derivation = _derive(left, right, pairs, protocol)
    cells = {
        record.scope
        for record in derivation.counts
        if record.scope.startswith("eligibility:pooled:")
    }
    assert len(cells) == 9


# ------------------------------------------------------------- undecidable


def test_a_failed_comparison_is_undecidable_and_never_a_non_match():
    """Spec section 74, on both sides."""
    left_key = world.outcome_key(ProtocolStage.PLAIN_ROLL_MATED, "SD300A", 0)
    right_key = world.outcome_key(ProtocolStage.ROLL_SELF, "SD300C", 1)
    left, right, pairs, protocol = world.build_world(
        left_outcomes={left_key: "undecidable"},
        right_outcomes={right_key: "undecidable"},
    )
    _audit, derivation = _derive(left, right, pairs, protocol)

    undecidable = [
        record
        for record in derivation.records
        if DecisionOutcome.UNDECIDABLE in (record.left_outcome, record.right_outcome)
    ]
    assert len(undecidable) == 2
    assert all(
        DecisionOutcome.NON_MATCH not in (r.left_outcome, r.right_outcome)
        for r in undecidable
    )

    # The failed mated comparison is inside the attempt denominator and outside
    # the decided one.
    attempt = _observation(
        derivation,
        "plain_roll_mated_unconditional_non_success_rate_attempt",
        "pooled",
    )
    decided = _observation(
        derivation, "plain_roll_mated_unconditional_fnmr_decided", "pooled"
    )
    assert attempt.left_denominator == world.total_units()
    assert decided.left_denominator == world.total_units() - 1
    assert attempt.left_numerator == 1  # the undecidable one is a non-success
    assert decided.left_numerator == 0  # and is not a non-match

    # The decided populations now differ, so the decided rates do not subtract.
    assert decided.population is (
        CrossAlgorithmPopulation.DIFFERENT_DECIDED_POPULATIONS
    )
    assert decided.difference_numerator is None

    # A SELF comparison that could not be decided makes its unit UNDETERMINED.
    undetermined = [
        transition
        for transition in derivation.transitions
        if transition.right_status is SelfEligibilityStatus.UNDETERMINED
    ]
    assert len(undetermined) == 1

    require_complete_matrices(derivation.counts, releases=world.RELEASES)


# --------------------------------------------------------------- tampering


def test_a_removed_common_eligible_row_fails_verification():
    left, right, pairs, protocol = world.build_world()
    _audit, derivation = _derive(left, right, pairs, protocol)
    derivation.common_eligible = derivation.common_eligible[:-1]
    with pytest.raises(CrossAlgorithmError, match="common eligible"):
        verify_derivation(derivation=derivation, manifest=derivation.manifest)


def test_a_removed_transition_cell_fails_verification():
    left, right, pairs, protocol = world.build_world()
    _audit, derivation = _derive(left, right, pairs, protocol)
    derivation.counts = tuple(
        record
        for record in derivation.counts
        if not (
            record.family is CrossAlgorithmTransitionFamily.MATED_UNCONDITIONAL
            and record.scope == "pooled"
            and record.left_outcome is DecisionOutcome.UNDECIDABLE
            and record.right_outcome is DecisionOutcome.UNDECIDABLE
        )
    )
    with pytest.raises(CrossAlgorithmError):
        verify_derivation(derivation=derivation, manifest=derivation.manifest)


def test_a_reordered_pair_changes_the_records_hash():
    left, right, pairs, protocol = world.build_world()
    _audit, derivation = _derive(left, right, pairs, protocol)
    derivation.records = tuple(reversed(derivation.records))
    with pytest.raises(CrossAlgorithmError, match="comparison records"):
        verify_derivation(derivation=derivation, manifest=derivation.manifest)


def test_an_edited_report_changes_its_content_hash():
    left, right, pairs, protocol = world.build_world()
    audit, derivation = _derive(left, right, pairs, protocol)
    definition = _definition(protocol, left, right)
    markdown = render_report(
        definition=definition,
        manifest=derivation.manifest,
        audit=audit,
        observations=derivation.observations,
        counts=derivation.counts,
        transitions=derivation.transitions,
        common_eligible=derivation.common_eligible,
        releases=world.RELEASES,
    )
    assert report_content_hash(markdown) != report_content_hash(
        markdown.replace("PRIMARY", "primary")
    )


# ---------------------------------------------------------------- no scores


def test_a_document_carrying_a_score_field_is_refused():
    for forbidden in (
        {"left_score": 41},
        {"nbis_score": 41},
        {"score_delta": 3},
        {"rank_correlation": 0.8},
        {"nested": [{"normalised_score": 1}]},
    ):
        with pytest.raises(ValueError, match="must not appear"):
            require_no_score_comparison(forbidden)


def test_the_derived_artefacts_carry_no_score():
    left, right, pairs, protocol = world.build_world()
    _audit, derivation = _derive(left, right, pairs, protocol)
    require_no_score_comparison(derivation.records, path="records")
    require_no_score_comparison(derivation.observations, path="observations")
    require_no_score_comparison(derivation.counts, path="counts")


def test_the_report_never_uses_the_words_a_conclusion_would_need():
    left, right, pairs, protocol = world.build_world()
    audit, derivation = _derive(left, right, pairs, protocol)
    markdown = render_report(
        definition=_definition(protocol, left, right),
        manifest=derivation.manifest,
        audit=audit,
        observations=derivation.observations,
        counts=derivation.counts,
        transitions=derivation.transitions,
        common_eligible=derivation.common_eligible,
        releases=world.RELEASES,
    )
    lowered = markdown.lower()
    for forbidden in (
        "more accurate",
        "less accurate",
        "safer",
        "better algorithm",
        "statistically significant",
        "score delta",
    ):
        assert forbidden not in lowered
    assert "does not establish equal FMR" in markdown
    assert "NOT an FMR" in markdown


# ---------------------------------------------------------------- internals


def _observation(derivation, metric_id, scope):
    return next(
        observation
        for observation in derivation.observations
        if observation.metric_id == metric_id and observation.scope == scope
    )


def _definition(protocol, left, right):
    from fpbench.core.cross_algorithm_models import (
        CrossAlgorithmEvaluationDefinition,
        cross_algorithm_definition_fingerprint,
    )

    claims = {
        "protocol_id": protocol.protocol_id,
        "protocol_fingerprint": protocol.protocol_fingerprint,
        "left_label": left.label,
        "left_run_id": left.run.run_id,
        "left_run_fingerprint": left.run.run_fingerprint,
        "left_result_set_fingerprint": left.result_set.result_set_fingerprint,
        "left_decision_set_id": left.decision_manifest.decision_set_id,
        "left_decision_set_fingerprint": (
            left.decision_manifest.decision_set_fingerprint
        ),
        "left_eligibility_set_id": left.eligibility_manifest.eligibility_set_id,
        "left_eligibility_set_fingerprint": (
            left.eligibility_manifest.eligibility_set_fingerprint
        ),
        "left_metric_set_id": left.metric_manifest.metric_set_id,
        "left_metric_set_fingerprint": left.metric_manifest.metric_set_fingerprint,
        "left_decision_profile_fingerprint": left.decision_profile.profile_fingerprint,
        "right_label": right.label,
        "right_run_id": right.run.run_id,
        "right_run_fingerprint": right.run.run_fingerprint,
        "right_result_set_fingerprint": right.result_set.result_set_fingerprint,
        "right_decision_set_id": right.decision_manifest.decision_set_id,
        "right_decision_set_fingerprint": (
            right.decision_manifest.decision_set_fingerprint
        ),
        "right_eligibility_set_id": right.eligibility_manifest.eligibility_set_id,
        "right_eligibility_set_fingerprint": (
            right.eligibility_manifest.eligibility_set_fingerprint
        ),
        "right_metric_set_id": right.metric_manifest.metric_set_id,
        "right_metric_set_fingerprint": right.metric_manifest.metric_set_fingerprint,
        "right_decision_profile_fingerprint": (
            right.decision_profile.profile_fingerprint
        ),
        "alignment_fingerprint": protocol.alignment_fingerprint,
        "pair_manifest_hash": world.digest("pairs"),
        "preparation_set_fingerprint": protocol.preparation_set_fingerprint,
        "eligibility_policy_id": protocol.eligibility_policy_id,
        "eligibility_policy_version": protocol.eligibility_policy_version,
        "metric_policy_fingerprint": protocol.metric_policy_fingerprint,
        "comparison_policy_fingerprint": protocol.comparison_policy_fingerprint,
        "comparison_software_fingerprint": world.digest("software"),
        "comparison_source_commit": "0" * 40,
    }
    fingerprint = cross_algorithm_definition_fingerprint(claims)
    return CrossAlgorithmEvaluationDefinition(
        **claims,
        definition_id=f"algcomparedef_{fingerprint[:12]}",
        definition_fingerprint=fingerprint,
        created_utc="2026-08-04T00:00:00+00:00",
    )
