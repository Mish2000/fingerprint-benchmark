from __future__ import annotations

from fractions import Fraction

import pytest

from fpbench.baseline_evaluation import (
    BaselineEvaluationError,
    BaselinePopulation,
    BoundaryKind,
    EvaluationAttempt,
    build_scope_sweeps,
    build_score_sweep,
    common_score_population,
    evaluate_comparison_roster,
    select_far_target_point,
)
from fpbench.core.enums import ExecutionStatus, GroundTruth, ScoreDirection

pytestmark = pytest.mark.stage21a_contract


def _attempt(
    pair_id: str,
    population: BaselinePopulation,
    score: int | float | None,
    *,
    release: str = "SD300A",
) -> EvaluationAttempt:
    return EvaluationAttempt(
        pair_id=pair_id,
        release=release,
        population=population,
        ground_truth=(
            GroundTruth.MATED
            if population is BaselinePopulation.GENUINE
            else GroundTruth.NON_MATED
        ),
        status=(ExecutionStatus.SUCCESS if score is not None else ExecutionStatus.FAILURE),
        score=score,
    )


def test_ties_move_together_even_when_truth_differs() -> None:
    rows = (
        _attempt("g_high", BaselinePopulation.GENUINE, 10),
        _attempt("g_tie", BaselinePopulation.GENUINE, 5),
        _attempt("i_tie", BaselinePopulation.IMPOSTOR, 5),
        _attempt("i_low", BaselinePopulation.IMPOSTOR, 1),
    )
    sweep = build_score_sweep(rows, score_direction=ScoreDirection.HIGHER_IS_BETTER)
    at_five = next(point for point in sweep.points if point.score_cut == 5)
    assert at_five.genuine.accepted == 2
    assert at_five.impostor.accepted == 1
    assert not any(
        point.genuine.accepted == 2 and point.impostor.accepted == 0
        for point in sweep.points
    )


@pytest.mark.parametrize(
    "direction, cuts",
    [
        (ScoreDirection.HIGHER_IS_BETTER, [3, 2, 1]),
        (ScoreDirection.LOWER_IS_BETTER, [1, 2, 3]),
    ],
)
def test_unique_raw_scores_are_walked_in_the_declared_direction(direction, cuts) -> None:
    rows = (
        _attempt("g1", BaselinePopulation.GENUINE, 3),
        _attempt("g2", BaselinePopulation.GENUINE, 2),
        _attempt("i1", BaselinePopulation.IMPOSTOR, 1),
    )
    sweep = build_score_sweep(rows, score_direction=direction)
    assert [point.score_cut for point in sweep.points[1:]] == cuts


def test_failures_remain_in_denominators_and_never_become_zero_scores() -> None:
    rows = (
        _attempt("g_score", BaselinePopulation.GENUINE, 4),
        _attempt("g_fail", BaselinePopulation.GENUINE, None),
        _attempt("i_score", BaselinePopulation.IMPOSTOR, 2),
        _attempt("i_fail", BaselinePopulation.IMPOSTOR, None),
    )
    sweep = build_score_sweep(rows, score_direction=ScoreDirection.HIGHER_IS_BETTER)
    first, last = sweep.points[0], sweep.points[-1]
    assert first.boundary_kind is BoundaryKind.ACCEPT_NONE
    assert (first.tar.fraction, first.far.fraction, first.frr.fraction) == (0, 0, 1)
    assert last.accepts_all_score_bearing
    assert last.tar.fraction == Fraction(1, 2)
    assert last.far.fraction == Fraction(1, 2)
    assert last.frr.fraction == Fraction(1, 2)
    assert last.genuine.operational.planned_attempts == 2
    assert last.genuine.operational.score_bearing_attempts == 1
    assert last.genuine.operational.algorithm_failures == 1
    for point in sweep.points:
        assert point.tar.fraction + point.frr.fraction == 1


def test_a_failure_carrying_a_number_is_refused() -> None:
    with pytest.raises(BaselineEvaluationError, match="must not be converted"):
        EvaluationAttempt(
            pair_id="failure",
            release="SD300A",
            population=BaselinePopulation.GENUINE,
            ground_truth=GroundTruth.MATED,
            status=ExecutionStatus.FAILURE,
            score=0,
        )


def test_target_lookup_never_interpolates_or_exceeds_the_target() -> None:
    rows = (
        _attempt("g10", BaselinePopulation.GENUINE, 10),
        _attempt("g9", BaselinePopulation.GENUINE, 9),
        _attempt("g1", BaselinePopulation.GENUINE, 1),
        _attempt("i8", BaselinePopulation.IMPOSTOR, 8),
        _attempt("i2", BaselinePopulation.IMPOSTOR, 2),
    )
    sweep = build_score_sweep(rows, score_direction=ScoreDirection.HIGHER_IS_BETTER)
    observed = select_far_target_point(sweep, Fraction(1, 4))
    assert observed.requested_far == Fraction(1, 4)
    assert observed.observed.far.fraction == 0
    assert observed.observed.tar.fraction == Fraction(2, 3)
    assert observed.interpolation_performed is False


def test_target_ties_choose_lower_far_then_the_stricter_observed_cut() -> None:
    rows = (
        _attempt("g", BaselinePopulation.GENUINE, 10),
        _attempt("i_low", BaselinePopulation.IMPOSTOR, 1),
        _attempt("i_lower", BaselinePopulation.IMPOSTOR, 0),
    )
    sweep = build_score_sweep(rows, score_direction=ScoreDirection.HIGHER_IS_BETTER)
    chosen = select_far_target_point(sweep, 1).observed
    assert chosen.score_cut == 10
    assert chosen.far.fraction == 0
    assert chosen.tar.fraction == 1


def test_rates_are_monotone_as_the_cut_becomes_more_lenient() -> None:
    rows = tuple(
        _attempt(f"g{score}", BaselinePopulation.GENUINE, score)
        for score in (9, 7, 4)
    ) + tuple(
        _attempt(f"i{score}", BaselinePopulation.IMPOSTOR, score)
        for score in (8, 3, 1)
    )
    points = build_score_sweep(
        rows, score_direction=ScoreDirection.HIGHER_IS_BETTER
    ).points
    assert [p.tar.fraction for p in points] == sorted(p.tar.fraction for p in points)
    assert [p.far.fraction for p in points] == sorted(p.far.fraction for p in points)
    assert [p.frr.fraction for p in points] == sorted(
        (p.frr.fraction for p in points), reverse=True
    )


def test_pooled_is_sum_of_counts_not_mean_of_release_rates() -> None:
    rows = (
        _attempt("a_g_score", BaselinePopulation.GENUINE, 2, release="SD300A"),
        _attempt("a_i_score", BaselinePopulation.IMPOSTOR, 1, release="SD300A"),
        _attempt("b_g_score", BaselinePopulation.GENUINE, 2, release="SD300B"),
        _attempt("b_g_fail1", BaselinePopulation.GENUINE, None, release="SD300B"),
        _attempt("b_g_fail2", BaselinePopulation.GENUINE, None, release="SD300B"),
        _attempt("b_i_score", BaselinePopulation.IMPOSTOR, 1, release="SD300B"),
    )
    sweeps = build_scope_sweeps(
        rows,
        score_direction=ScoreDirection.HIGHER_IS_BETTER,
        releases=("SD300A", "SD300B"),
    )
    assert sweeps["SD300A"].points[-1].tar.fraction == 1
    assert sweeps["SD300B"].points[-1].tar.fraction == Fraction(1, 3)
    assert sweeps["pooled"].points[-1].tar.fraction == Fraction(1, 2)
    assert Fraction(1, 2) != (Fraction(1, 1) + Fraction(1, 3)) / 2


def test_common_score_population_uses_the_same_pairs_for_every_algorithm() -> None:
    base = (
        _attempt("g1", BaselinePopulation.GENUINE, 5),
        _attempt("g2", BaselinePopulation.GENUINE, 4),
        _attempt("i1", BaselinePopulation.IMPOSTOR, 1),
        _attempt("i2", BaselinePopulation.IMPOSTOR, 0),
    )
    other = tuple(
        replace_score(attempt, None if attempt.pair_id == "g2" else attempt.score)
        for attempt in base
    )
    common = common_score_population({"one": base, "two": other})
    assert [row.pair_id for row in common["one"]] == ["g1", "i1", "i2"]
    assert [row.pair_id for row in common["two"]] == ["g1", "i1", "i2"]


def replace_score(attempt: EvaluationAttempt, score: int | float | None) -> EvaluationAttempt:
    return _attempt(
        attempt.pair_id,
        attempt.population,
        score,
        release=attempt.release,
    )


def test_roster_evaluation_keeps_all_attempt_primary_and_common_score_secondary() -> None:
    first = (
        _attempt("g1", BaselinePopulation.GENUINE, 5),
        _attempt("g2", BaselinePopulation.GENUINE, 4),
        _attempt("i1", BaselinePopulation.IMPOSTOR, 1),
    )
    second = tuple(
        replace_score(row, None if row.pair_id == "g2" else row.score)
        for row in first
    )
    evaluated = evaluate_comparison_roster(
        {"one": first, "two": second},
        score_directions={
            "one": ScoreDirection.HIGHER_IS_BETTER,
            "two": ScoreDirection.HIGHER_IS_BETTER,
        },
        far_targets=(0.01, 0.001, 0.0001),
        releases=("SD300A",),
    )
    primary = evaluated["primary_all_attempt"]["two"]["sweeps"]["pooled"]
    secondary = evaluated["secondary_common_score"]["two"]["sweeps"]["pooled"]
    assert primary.points[-1].genuine.operational.planned_attempts == 2
    assert secondary.points[-1].genuine.operational.planned_attempts == 1
