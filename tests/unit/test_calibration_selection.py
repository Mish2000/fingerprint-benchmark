"""The selector, over fixtures small enough to work out by hand.

Every expected answer below is derived in the docstring of the test that asserts
it, because a selection test whose expectation came from running the selector is
a test that a change to the selector cannot fail.

The fixtures cover both score directions, both comparators, a target reached
exactly, a target undershot because ties cannot be split, a population where
every score is identical, an operating point that admits no impostor at all,
comparisons that produced no score, and the two populations being absent.
"""

from __future__ import annotations

import json
import random
from decimal import Decimal

import pytest

from fpbench.calibration.models import LabeledResults, LabeledScore
from fpbench.calibration.protocol import (
    build_calibration_source_binding,
    build_protected_evaluation_registry,
    impostor_ceiling_protocol,
)
from fpbench.calibration.selection import (
    candidate_boundaries,
    evaluate_boundary,
    select_boundary,
    select_operating_point,
)
from fpbench.calibration.verify import verify_operating_point
from fpbench.core.calibration_errors import (
    CalibrationInputError,
    CalibrationLeakageError,
    CalibrationSelectionError,
    CalibrationSourceError,
    CalibrationVerificationError,
)
from fpbench.core.calibration_models import ProtectedEvaluationIdentity
from fpbench.core.enums import (
    CalibrationPairTruth,
    CohortRole,
    ExecutionStatus,
    ProtectedIdentityKind,
    ScoreDirection,
    ThresholdComparator,
)
from fpbench.core.serialization import to_plain

pytestmark = pytest.mark.stage8d_contract

MATED = CalibrationPairTruth.MATED
IMPOSTOR = CalibrationPairTruth.CROSS_SUBJECT_IMPOSTOR
HIGHER = ScoreDirection.HIGHER_IS_BETTER
LOWER = ScoreDirection.LOWER_IS_BETTER
GE = ThresholdComparator.GREATER_THAN_OR_EQUAL
GT = ThresholdComparator.GREATER_THAN
LE = ThresholdComparator.LESS_THAN_OR_EQUAL
LT = ThresholdComparator.LESS_THAN

COMMIT = "0" * 40
WHEN = "2026-08-07T12:00:00Z"


# --------------------------------------------------------------- the fixtures


def results_from(
    direction: ScoreDirection,
    *,
    mated: list[str],
    impostor: list[str],
    mated_failures: int = 0,
    impostor_failures: int = 0,
) -> LabeledResults:
    rows: list[LabeledScore] = []
    for index, score in enumerate(mated):
        rows.append(
            LabeledScore(
                pair_id=f"m{index:03d}",
                truth=MATED,
                execution_status=ExecutionStatus.SUCCESS,
                score=Decimal(score),
            )
        )
    for index, score in enumerate(impostor):
        rows.append(
            LabeledScore(
                pair_id=f"i{index:03d}",
                truth=IMPOSTOR,
                execution_status=ExecutionStatus.SUCCESS,
                score=Decimal(score),
            )
        )
    for index in range(mated_failures):
        rows.append(
            LabeledScore(
                pair_id=f"mf{index:03d}",
                truth=MATED,
                execution_status=ExecutionStatus.FAILURE,
                failure_code="template_extraction_failed",
            )
        )
    for index in range(impostor_failures):
        rows.append(
            LabeledScore(
                pair_id=f"if{index:03d}",
                truth=IMPOSTOR,
                execution_status=ExecutionStatus.FAILURE,
                failure_code="template_extraction_failed",
            )
        )
    return LabeledResults(score_direction=direction, rows=tuple(rows))


def binding(
    direction: ScoreDirection = HIGHER,
    role: CohortRole = CohortRole.DEVELOPMENT,
    *,
    result_set_fingerprint: str = "d" * 64,
    pair_manifest_fingerprint: str = "1" * 64,
):
    return build_calibration_source_binding(
        binding_id="synthetic_binding_v1",
        algorithm_id="synthetic_matcher",
        algorithm_fingerprint="a" * 64,
        integration_id="synthetic_integration",
        integration_fingerprint="b" * 64,
        run_id="run_synthetic01",
        run_fingerprint="c" * 64,
        result_set_id="resultset_syn01",
        result_set_fingerprint=result_set_fingerprint,
        dataset_id="synthetic_dataset",
        dataset_fingerprint="e" * 64,
        cohort_id="synthetic_dev_cohort",
        cohort_fingerprint="f" * 64,
        cohort_role=role,
        pair_manifest_id="synthetic_pairs",
        pair_manifest_fingerprint=pair_manifest_fingerprint,
        score_direction=direction,
    )


def registry():
    """A registry that protects something real but unrelated to the fixtures."""
    return build_protected_evaluation_registry(
        registry_id="synthetic_protected_v1",
        registry_version="1",
        entries=[
            ProtectedEvaluationIdentity(
                kind=ProtectedIdentityKind.RESULT_SET,
                identity="resultset_protected",
                fingerprint="9" * 64,
                label="a protected evaluation result set",
            )
        ],
    )


def choose(protocol, results, **overrides):
    fields = dict(
        protected_registry=registry(),
        created_source_commit=COMMIT,
        created_source_tree_clean=True,
        created_utc=WHEN,
    )
    fields.update(overrides)
    return select_operating_point(
        protocol, binding(results.score_direction), results, **fields
    )


# ---------------------------------------------------------------- boundaries


def test_boundaries_come_from_the_scores_and_span_both_extremes() -> None:
    """docs/adr/0080: no epsilon, and the family is closed.

    Over the scores {1, 2, 3} the six candidates are >=1, >1, >=2, >2, >=3, >3.
    ``>= 1`` accepts everything and ``> 3`` accepts nothing, so both extremes are
    reachable without inventing a number no comparison produced.
    """
    results = results_from(HIGHER, mated=["3"], impostor=["1", "2"])
    boundaries = candidate_boundaries(results)
    assert len(boundaries) == 6
    assert {(b.canonical_threshold, b.comparator.value) for b in boundaries} == {
        ("1", "greater_than_or_equal"),
        ("1", "greater_than"),
        ("2", "greater_than_or_equal"),
        ("2", "greater_than"),
        ("3", "greater_than_or_equal"),
        ("3", "greater_than"),
    }
    accepts_all = evaluate_boundary(boundaries[0], results)
    assert accepts_all.permissiveness == 3
    accepts_none = evaluate_boundary(boundaries[-1], results)
    assert accepts_none.permissiveness == 0


def test_a_lower_is_better_matcher_gets_the_other_two_comparators() -> None:
    results = results_from(LOWER, mated=["1"], impostor=["5"])
    comparators = {b.comparator for b in candidate_boundaries(results)}
    assert comparators == {LE, LT}


# ----------------------------------------------------------------- selection


def test_a_target_reached_exactly() -> None:
    """Higher-is-better, impostors 1..4, mated 5..8, ceiling 1/4.

    ``>= 4`` admits exactly one impostor (the 4), and 1/4 does not exceed 1/4.
    ``>= 3`` would admit two, which does. So 4 is the most permissive inclusive
    boundary inside the ceiling, and the target is met exactly rather than
    undershot.
    """
    protocol = impostor_ceiling_protocol(
        protocol_id="quarter_v1", numerator=1, denominator=4
    )
    results = results_from(
        HIGHER, mated=["5", "6", "7", "8"], impostor=["1", "2", "3", "4"]
    )
    point = choose(protocol, results)
    assert point.threshold == "4"
    assert point.comparator is GE
    assert point.observed_impostor_matches == 1
    assert point.observed_impostor_scored == 4
    assert point.observed_mated_matches == 4


def test_a_target_undershot_because_ties_cannot_be_split() -> None:
    """Impostors 0.4, 0.4, 0.4, 0.7, 0.7; mated 0.9, 0.9; ceiling 1/5.

    One impostor match out of five would satisfy the ceiling, and no boundary
    produces one: ``>= 0.7`` admits both 0.7s and ``>= 0.4`` admits all five.
    Accepting one of the two 0.7s is not available, because a boundary decides a
    *value*. So the selection undershoots to zero rather than splitting the tie
    (docs/adr/0080).
    """
    protocol = impostor_ceiling_protocol(
        protocol_id="fifth_v1", numerator=1, denominator=5
    )
    results = results_from(
        HIGHER, mated=["0.9", "0.9"], impostor=["0.4", "0.4", "0.4", "0.7", "0.7"]
    )
    point = choose(protocol, results)
    assert point.threshold == "0.9"
    assert point.comparator is GE
    assert point.observed_impostor_matches == 0
    assert point.observed_mated_matches == 2


def test_a_zero_impostor_match_operating_point_is_a_normal_outcome() -> None:
    """The same fixture: admitting no impostor at all is an answer, not a failure."""
    protocol = impostor_ceiling_protocol(
        protocol_id="fifth_v1", numerator=1, denominator=5
    )
    results = results_from(
        HIGHER, mated=["0.9", "0.9"], impostor=["0.4", "0.4", "0.4", "0.7", "0.7"]
    )
    point = choose(protocol, results)
    assert point.observed_impostor_matches == 0
    assert point.observed_impostor_scored == 5


def test_a_lower_is_better_selection_runs_the_other_way() -> None:
    """Distances: mated 1..4 are close, impostors 5..8 are far, ceiling 1/4.

    ``<= 5`` admits exactly one impostor. ``<= 6`` admits two. So 5 is the most
    permissive boundary inside the ceiling, and it is spelled with ``<=`` rather
    than ``>=`` because a smaller distance is a better match.
    """
    protocol = impostor_ceiling_protocol(
        protocol_id="quarter_v1", numerator=1, denominator=4
    )
    results = results_from(
        LOWER, mated=["1", "2", "3", "4"], impostor=["5", "6", "7", "8"]
    )
    point = choose(protocol, results)
    assert point.threshold == "5"
    assert point.comparator is LE
    assert point.observed_impostor_matches == 1
    assert point.observed_mated_matches == 4


def test_when_every_score_is_identical_the_answer_is_a_strict_boundary() -> None:
    """Four impostors and four mated, all scoring 1, ceiling 1/4.

    ``>= 1`` admits all four impostors — 4/4 exceeds 1/4. ``> 1`` admits none.
    There is nothing in between, because there is one distinct score. The
    selection returns "accept nothing", spelled as a strict boundary at the only
    score that exists rather than as an invented number above it.
    """
    protocol = impostor_ceiling_protocol(
        protocol_id="quarter_v1", numerator=1, denominator=4
    )
    results = results_from(
        HIGHER, mated=["1", "1", "1", "1"], impostor=["1", "1", "1", "1"]
    )
    point = choose(protocol, results)
    assert point.threshold == "1"
    assert point.comparator is GT
    assert point.observed_impostor_matches == 0
    assert point.observed_mated_matches == 0
    assert point.observed_mated_non_matches == 4


def test_duplicate_scores_are_counted_and_never_separated() -> None:
    """Three impostors at 0.4 count as three, and share one decision."""
    protocol = impostor_ceiling_protocol(
        protocol_id="half_v1", numerator=1, denominator=2
    )
    results = results_from(
        HIGHER, mated=["0.9"], impostor=["0.4", "0.4", "0.4", "0.9"]
    )
    point = choose(protocol, results)
    # >= 0.9 admits the one impostor at 0.9: 1/4 is inside 1/2.
    # >= 0.4 admits all four: 4/4 is not.
    assert point.threshold == "0.9"
    assert point.observed_impostor_matches == 1
    assert point.observed_impostor_scored == 4


def test_the_inclusive_spelling_wins_when_two_boundaries_decide_identically() -> None:
    """Over {0.4, 0.7}, ``>= 0.7`` and ``> 0.4`` accept exactly the same score.

    They are one threshold with two names. The canonical one is the inclusive
    spelling, so the operating point has a stable identity and no decision moves
    either way.
    """
    protocol = impostor_ceiling_protocol(
        protocol_id="tenth_v1", numerator=1, denominator=10
    )
    results = results_from(HIGHER, mated=["0.7"], impostor=["0.4", "0.4"])
    outcome = select_boundary(protocol, results)
    assert outcome.boundary.comparator is GE
    assert outcome.boundary.canonical_threshold == "0.7"


# --------------------------------------------------- one objective, not two


def test_the_mated_scores_do_not_influence_which_boundary_is_chosen() -> None:
    """Spec section 16: genuine performance is measured, never optimised for.

    Two fixtures with identical impostor scores and wildly different mated ones.
    If the selector were weighing genuine performance at all — even as a
    tie-break — these would diverge. They do not: the boundary, the comparator
    and the impostor counts are identical, and only the mated counts differ.
    """
    protocol = impostor_ceiling_protocol(
        protocol_id="quarter_v1", numerator=1, denominator=4
    )
    impostor = ["1", "2", "3", "4"]
    generous = results_from(HIGHER, mated=["5", "6", "7", "8"], impostor=impostor)
    dismal = results_from(HIGHER, mated=["1", "1", "1", "2"], impostor=impostor)

    first, second = choose(protocol, generous), choose(protocol, dismal)
    assert first.threshold == second.threshold
    assert first.comparator is second.comparator
    assert first.observed_impostor_matches == second.observed_impostor_matches
    # The consequence is recorded, and it is a consequence: four mated matches
    # under one fixture, none under the other, at the very same boundary.
    assert first.observed_mated_matches == 4
    assert second.observed_mated_matches == 0
    assert second.observed_mated_non_matches == 4


def test_there_is_exactly_one_selection_rule_to_apply() -> None:
    """A second rule would be a second protocol, not a setting on this one."""
    from fpbench.core.enums import ThresholdSelectionRule

    assert len(list(ThresholdSelectionRule)) == 1
    protocol = impostor_ceiling_protocol(
        protocol_id="quarter_v1", numerator=1, denominator=4
    )
    assert (
        protocol.threshold_selection_rule
        is ThresholdSelectionRule.MOST_PERMISSIVE_WITHIN_IMPOSTOR_CEILING
    )


# ------------------------------------------------------------------ failures


def test_failures_are_excluded_from_the_rate_and_reported_beside_it() -> None:
    """docs/adr/0006: a comparison that produced no score is not a non-match.

    Four impostor attempts, one of which failed. The ceiling of 1/3 is applied to
    the three that produced a score, and the fourth appears only as a failure.
    """
    protocol = impostor_ceiling_protocol(
        protocol_id="third_v1", numerator=1, denominator=3
    )
    results = results_from(
        HIGHER,
        mated=["8", "9"],
        impostor=["1", "2", "3"],
        mated_failures=1,
        impostor_failures=1,
    )
    point = choose(protocol, results)
    assert point.observed_impostor_scored == 3
    assert point.observed_impostor_attempts == 4
    assert point.impostor_failures == 1
    assert point.observed_mated_scored == 2
    assert point.observed_mated_attempts == 3
    assert point.mated_failures == 1
    assert point.observed_mated_matches + point.observed_mated_non_matches == 2


def test_an_impostor_population_that_wholly_failed_has_no_rate() -> None:
    protocol = impostor_ceiling_protocol(
        protocol_id="third_v1", numerator=1, denominator=3
    )
    results = results_from(HIGHER, mated=["8"], impostor=[], impostor_failures=3)
    with pytest.raises(CalibrationSelectionError, match="not a rate"):
        choose(protocol, results)


# ---------------------------------------------------------- missing populations


def test_a_missing_impostor_population_is_refused() -> None:
    protocol = impostor_ceiling_protocol(
        protocol_id="third_v1", numerator=1, denominator=3
    )
    results = results_from(HIGHER, mated=["1", "2"], impostor=[])
    with pytest.raises(CalibrationInputError, match="cross-subject impostor"):
        choose(protocol, results)


def test_a_missing_genuine_population_is_refused() -> None:
    protocol = impostor_ceiling_protocol(
        protocol_id="third_v1", numerator=1, denominator=3
    )
    results = results_from(HIGHER, mated=[], impostor=["1", "2"])
    with pytest.raises(CalibrationInputError, match="no mated comparisons"):
        choose(protocol, results)


# --------------------------------------------------------------- the bindings


def test_a_binding_and_its_results_must_agree_about_the_score_direction() -> None:
    protocol = impostor_ceiling_protocol(
        protocol_id="third_v1", numerator=1, denominator=3
    )
    results = results_from(HIGHER, mated=["8"], impostor=["1"])
    with pytest.raises(CalibrationSourceError, match="which side of a boundary"):
        select_operating_point(
            protocol,
            binding(LOWER),
            results,
            protected_registry=registry(),
            created_source_commit=COMMIT,
            created_source_tree_clean=True,
            created_utc=WHEN,
        )


def test_one_body_of_results_carries_exactly_one_score_direction() -> None:
    """There is no way to mix two algorithms' scales: the field is singular."""
    results = results_from(HIGHER, mated=["8"], impostor=["1"])
    assert results.score_direction is HIGHER
    assert not hasattr(results.rows[0], "score_direction")


def test_an_evaluation_role_is_refused_before_a_score_is_read() -> None:
    """docs/adr/0079, and the ordering is the claim being tested.

    ``labeled_results`` is an object that raises the moment anything touches it.
    If the refusal came after the scores were counted, this test would see that
    error instead of the leakage one.
    """

    class Explosive:
        def __getattr__(self, name):  # pragma: no cover - must never run
            raise AssertionError(f"the selector read {name} before refusing")

    protocol = impostor_ceiling_protocol(
        protocol_id="third_v1", numerator=1, denominator=3
    )
    with pytest.raises(CalibrationLeakageError, match="may only be chosen"):
        select_operating_point(
            protocol,
            binding(HIGHER, CohortRole.EVALUATION),
            Explosive(),
            protected_registry=registry(),
            created_source_commit=COMMIT,
            created_source_tree_clean=True,
            created_utc=WHEN,
        )


def test_a_development_role_is_accepted() -> None:
    protocol = impostor_ceiling_protocol(
        protocol_id="third_v1", numerator=1, denominator=3
    )
    results = results_from(HIGHER, mated=["8", "9"], impostor=["1", "2", "3"])
    point = choose(protocol, results)
    assert point.operating_point_id.startswith("oppoint_")


# --------------------------------------------------------------- determinism


def a_selection():
    protocol = impostor_ceiling_protocol(
        protocol_id="quarter_v1", numerator=1, denominator=4
    )
    results = results_from(
        HIGHER,
        mated=["5", "6", "7", "8"],
        impostor=["1", "2", "3", "4"],
        mated_failures=1,
        impostor_failures=2,
    )
    return protocol, results


def test_shuffling_the_rows_changes_nothing_at_all() -> None:
    """Spec section 29: same threshold, same comparator, same counts, same id."""
    protocol, results = a_selection()
    reference = choose(protocol, results)
    generator = random.Random(20260807)
    for _ in range(25):
        rows = list(results.rows)
        generator.shuffle(rows)
        shuffled = LabeledResults(
            score_direction=results.score_direction, rows=tuple(rows)
        )
        point = choose(protocol, shuffled)
        assert point.operating_point_fingerprint == (
            reference.operating_point_fingerprint
        )
        assert point.threshold == reference.threshold
        assert point.comparator is reference.comparator


def test_a_json_round_trip_of_the_result_changes_nothing() -> None:
    from fpbench.calibration.models import (
        read_calibration_operating_point,
        strict_json_document,
    )

    protocol, results = a_selection()
    point = choose(protocol, results)
    restored = read_calibration_operating_point(
        strict_json_document(json.dumps(to_plain(point)))
    )
    assert restored == point


def test_the_wall_clock_does_not_reach_the_identity() -> None:
    protocol, results = a_selection()
    first = choose(protocol, results, created_utc="2026-08-07T12:00:00Z")
    second = choose(protocol, results, created_utc="2031-02-02T02:02:02Z")
    assert first.operating_point_fingerprint == second.operating_point_fingerprint


# ------------------------------------------------------------- verification


def test_a_stored_operating_point_re_derives_from_the_scores_it_cites() -> None:
    protocol, results = a_selection()
    point = choose(protocol, results)
    report = verify_operating_point(
        point,
        protocol,
        binding(results.score_direction),
        results,
        protected_registry=registry(),
    )
    assert report.verified is True
    assert report.findings == ()
    assert report.recomputed_fingerprint == point.operating_point_fingerprint


def test_verification_refuses_a_binding_that_names_a_different_result_set() -> None:
    protocol, results = a_selection()
    point = choose(protocol, results)
    with pytest.raises(CalibrationVerificationError, match="selected from source"):
        verify_operating_point(
            point,
            protocol,
            binding(results.score_direction, result_set_fingerprint="7" * 64),
            results,
            protected_registry=registry(),
        )


def test_verification_refuses_a_binding_that_names_a_different_pair_manifest():
    protocol, results = a_selection()
    point = choose(protocol, results)
    with pytest.raises(CalibrationVerificationError, match="selected from source"):
        verify_operating_point(
            point,
            protocol,
            binding(results.score_direction, pair_manifest_fingerprint="8" * 64),
            results,
            protected_registry=registry(),
        )


def test_verification_refuses_a_protocol_the_point_was_not_selected_under() -> None:
    protocol, results = a_selection()
    point = choose(protocol, results)
    other = impostor_ceiling_protocol(
        protocol_id="tenth_v1", numerator=1, denominator=10
    )
    with pytest.raises(CalibrationVerificationError, match="selected under protocol"):
        verify_operating_point(
            point, other, binding(results.score_direction), results,
            protected_registry=registry(),
        )


def test_verification_reports_a_disagreement_rather_than_raising() -> None:
    """A changed development score is a finding, not an exception.

    The artifacts still refer to each other correctly; what has changed is the
    evidence underneath them, and a qualification report needs to say *what*
    disagreed.
    """
    protocol, results = a_selection()
    point = choose(protocol, results)
    tampered_rows = []
    for row in results.rows:
        if row.pair_id == "i003":
            tampered_rows.append(
                LabeledScore(
                    pair_id=row.pair_id,
                    truth=row.truth,
                    execution_status=row.execution_status,
                    score=Decimal("99"),
                )
            )
        else:
            tampered_rows.append(row)
    tampered = LabeledResults(
        score_direction=results.score_direction, rows=tuple(tampered_rows)
    )
    report = verify_operating_point(
        point,
        protocol,
        binding(results.score_direction),
        tampered,
        protected_registry=registry(),
    )
    assert report.verified is False
    assert report.findings
    assert report.recomputed_fingerprint != point.operating_point_fingerprint
