"""Exhaustive, tie-atomic TAR/FAR/FRR score sweeps."""

from __future__ import annotations

from collections import defaultdict
from fractions import Fraction
from typing import Iterable, Mapping, Sequence

from fpbench.core.enums import ExecutionStatus, ScoreDirection
from fpbench.baseline_evaluation.models import (
    BaselineEvaluationError,
    BaselinePopulation,
    BoundaryKind,
    EvaluationAttempt,
    FarTargetPoint,
    OperationalCounts,
    PopulationPointCounts,
    ScoreSweep,
    ScoreSweepPoint,
    ScoreValue,
)

__all__ = [
    "build_score_sweep",
    "build_scope_sweeps",
    "common_score_population",
    "evaluate_comparison_roster",
    "select_far_target_point",
]


def _operational(
    attempts: Sequence[EvaluationAttempt], population: BaselinePopulation
) -> OperationalCounts:
    selected = [attempt for attempt in attempts if attempt.population is population]
    scored = sum(attempt.status is ExecutionStatus.SUCCESS for attempt in selected)
    return OperationalCounts(
        planned_attempts=len(selected),
        score_bearing_attempts=scored,
        algorithm_failures=len(selected) - scored,
    )


def _point(
    *,
    ordinal: int,
    boundary_kind: BoundaryKind,
    score_cut: ScoreValue | None,
    comparator: str | None,
    genuine_operational: OperationalCounts,
    impostor_operational: OperationalCounts,
    genuine_accepted: int,
    impostor_accepted: int,
    accepts_all: bool,
) -> ScoreSweepPoint:
    return ScoreSweepPoint(
        ordinal=ordinal,
        boundary_kind=boundary_kind,
        score_cut=score_cut,
        comparator=comparator,
        genuine=PopulationPointCounts(genuine_operational, genuine_accepted),
        impostor=PopulationPointCounts(impostor_operational, impostor_accepted),
        accepts_all_score_bearing=accepts_all,
    )


def build_score_sweep(
    attempts: Iterable[EvaluationAttempt],
    *,
    score_direction: ScoreDirection,
    scope: str = "pooled",
) -> ScoreSweep:
    """Walk every unique raw score without splitting a tie.

    Failures remain in the planned denominators and never enter an accepted
    numerator.  No score is normalised or compared with another algorithm's
    score scale.
    """
    rows = tuple(attempts)
    if not rows:
        raise BaselineEvaluationError("cannot sweep an empty attempt population")
    if not isinstance(score_direction, ScoreDirection):
        raise BaselineEvaluationError("score_direction must be a ScoreDirection")
    ids = [attempt.pair_id for attempt in rows]
    if len(ids) != len(set(ids)):
        raise BaselineEvaluationError("each planned pair must appear exactly once")
    genuine_operational = _operational(rows, BaselinePopulation.GENUINE)
    impostor_operational = _operational(rows, BaselinePopulation.IMPOSTOR)
    if genuine_operational.planned_attempts == 0:
        raise BaselineEvaluationError("scope contains no genuine attempts")
    if impostor_operational.planned_attempts == 0:
        raise BaselineEvaluationError("scope contains no impostor attempts")

    grouped: dict[ScoreValue, list[EvaluationAttempt]] = defaultdict(list)
    for attempt in rows:
        if attempt.status is ExecutionStatus.SUCCESS:
            assert attempt.score is not None
            grouped[attempt.score].append(attempt)
    reverse = score_direction is ScoreDirection.HIGHER_IS_BETTER
    unique_scores = sorted(grouped, reverse=reverse)
    comparator = "greater_than_or_equal" if reverse else "less_than_or_equal"

    # If every attempt failed, accept-none and accept-all-score-bearing are the
    # same observed point.  It is explicitly marked as both endpoints.
    points: list[ScoreSweepPoint] = [
        _point(
            ordinal=0,
            boundary_kind=BoundaryKind.ACCEPT_NONE,
            score_cut=None,
            comparator=None,
            genuine_operational=genuine_operational,
            impostor_operational=impostor_operational,
            genuine_accepted=0,
            impostor_accepted=0,
            accepts_all=not unique_scores,
        )
    ]
    genuine_accepted = 0
    impostor_accepted = 0
    for ordinal, score in enumerate(unique_scores, start=1):
        tied = grouped[score]
        genuine_accepted += sum(
            attempt.population is BaselinePopulation.GENUINE for attempt in tied
        )
        impostor_accepted += sum(
            attempt.population is BaselinePopulation.IMPOSTOR for attempt in tied
        )
        points.append(
            _point(
                ordinal=ordinal,
                boundary_kind=BoundaryKind.OBSERVED_SCORE_CUT,
                score_cut=score,
                comparator=comparator,
                genuine_operational=genuine_operational,
                impostor_operational=impostor_operational,
                genuine_accepted=genuine_accepted,
                impostor_accepted=impostor_accepted,
                accepts_all=ordinal == len(unique_scores),
            )
        )

    sweep = ScoreSweep(scope=scope, score_direction=score_direction, points=tuple(points))
    _verify_monotonicity(sweep)
    return sweep


def _verify_monotonicity(sweep: ScoreSweep) -> None:
    previous = sweep.points[0]
    for current in sweep.points[1:]:
        if current.tar.fraction < previous.tar.fraction:
            raise BaselineEvaluationError("TAR decreased as the cut became more lenient")
        if current.far.fraction < previous.far.fraction:
            raise BaselineEvaluationError("FAR decreased as the cut became more lenient")
        if current.frr.fraction > previous.frr.fraction:
            raise BaselineEvaluationError("FRR increased as the cut became more lenient")
        if current.tar.fraction + current.frr.fraction != 1:
            raise BaselineEvaluationError("TAR + FRR must equal one")
        previous = current


def _target_fraction(value: Fraction | float | int | str) -> Fraction:
    try:
        target = value if isinstance(value, Fraction) else Fraction(str(value))
    except (ValueError, ZeroDivisionError) as exc:
        raise BaselineEvaluationError(f"invalid FAR target {value!r}") from exc
    if not 0 <= target <= 1:
        raise BaselineEvaluationError("FAR target must lie in [0, 1]")
    return target


def select_far_target_point(
    sweep: ScoreSweep, target: Fraction | float | int | str
) -> FarTargetPoint:
    """Choose highest TAR at FAR<=target, then lower FAR, without interpolation."""
    requested = _target_fraction(target)
    eligible = [point for point in sweep.points if point.far.fraction <= requested]
    # accept-none always has FAR zero, so this can only fail if a malformed sweep
    # bypassed ScoreSweep's constructor.
    if not eligible:  # pragma: no cover - defensive contract
        raise BaselineEvaluationError("sweep has no point at or below FAR target")
    chosen = max(
        eligible,
        key=lambda point: (
            point.tar.fraction,
            -point.far.fraction,
            -point.accepted_score_bearing,
            -point.ordinal,
        ),
    )
    return FarTargetPoint(requested_far=requested, observed=chosen)


def build_scope_sweeps(
    attempts: Iterable[EvaluationAttempt],
    *,
    score_direction: ScoreDirection,
    releases: Sequence[str],
) -> Mapping[str, ScoreSweep]:
    """Build per-release sweeps plus a pooled sweep from summed attempts."""
    rows = tuple(attempts)
    if not releases or len(releases) != len(set(releases)):
        raise BaselineEvaluationError("releases must be a non-empty distinct sequence")
    unknown = sorted({row.release for row in rows} - set(releases))
    if unknown:
        raise BaselineEvaluationError(f"attempts name unknown releases {unknown}")
    sweeps: dict[str, ScoreSweep] = {}
    for release in releases:
        sweeps[release] = build_score_sweep(
            (row for row in rows if row.release == release),
            score_direction=score_direction,
            scope=release,
        )
    # This is intentionally one sweep over all attempts.  It therefore sums
    # numerators and denominators; it cannot become an average of release rates.
    sweeps["pooled"] = build_score_sweep(
        rows, score_direction=score_direction, scope="pooled"
    )
    return sweeps


def _aligned_attempts(
    attempts_by_algorithm: Mapping[str, Sequence[EvaluationAttempt]],
) -> tuple[tuple[str, ...], Mapping[str, Mapping[str, EvaluationAttempt]]]:
    if not attempts_by_algorithm:
        raise BaselineEvaluationError("comparison roster cannot be empty")
    indexed: dict[str, dict[str, EvaluationAttempt]] = {}
    reference_ids: tuple[str, ...] | None = None
    reference_metadata: dict[str, tuple[str, BaselinePopulation]] = {}
    for algorithm_id, attempts in attempts_by_algorithm.items():
        if not algorithm_id.strip():
            raise BaselineEvaluationError("algorithm_id must be non-empty")
        ids = [attempt.pair_id for attempt in attempts]
        if len(ids) != len(set(ids)):
            raise BaselineEvaluationError(f"{algorithm_id} repeats a pair id")
        if reference_ids is None:
            reference_ids = tuple(ids)
            reference_metadata = {
                attempt.pair_id: (attempt.release, attempt.population)
                for attempt in attempts
            }
        elif set(ids) != set(reference_ids):
            raise BaselineEvaluationError(
                f"{algorithm_id} does not cover the common planned pair population"
            )
        per_id = {attempt.pair_id: attempt for attempt in attempts}
        for pair_id, attempt in per_id.items():
            if (attempt.release, attempt.population) != reference_metadata[pair_id]:
                raise BaselineEvaluationError(
                    f"{algorithm_id} disagrees about pair {pair_id}'s population"
                )
        indexed[algorithm_id] = per_id
    assert reference_ids is not None
    return reference_ids, indexed


def common_score_population(
    attempts_by_algorithm: Mapping[str, Sequence[EvaluationAttempt]],
) -> Mapping[str, tuple[EvaluationAttempt, ...]]:
    """Return the identical pair subset scored by every roster member."""
    pair_order, indexed = _aligned_attempts(attempts_by_algorithm)
    common_ids = tuple(
        pair_id
        for pair_id in pair_order
        if all(
            per_algorithm[pair_id].status is ExecutionStatus.SUCCESS
            for per_algorithm in indexed.values()
        )
    )
    if not common_ids:
        raise BaselineEvaluationError("the common-score population is empty")
    return {
        algorithm_id: tuple(per_algorithm[pair_id] for pair_id in common_ids)
        for algorithm_id, per_algorithm in indexed.items()
    }


def evaluate_comparison_roster(
    attempts_by_algorithm: Mapping[str, Sequence[EvaluationAttempt]],
    *,
    score_directions: Mapping[str, ScoreDirection],
    far_targets: Sequence[Fraction | float | int | str],
    releases: Sequence[str],
) -> dict[str, object]:
    """Compute primary all-attempt and secondary common-score reporting views."""
    _aligned_attempts(attempts_by_algorithm)
    if set(score_directions) != set(attempts_by_algorithm):
        raise BaselineEvaluationError(
            "every and only roster algorithms must declare a score direction"
        )
    targets = tuple(_target_fraction(target) for target in far_targets)
    if not targets or len(targets) != len(set(targets)):
        raise BaselineEvaluationError("FAR targets must be non-empty and distinct")

    common = common_score_population(attempts_by_algorithm)

    def evaluate_view(
        populations: Mapping[str, Sequence[EvaluationAttempt]],
    ) -> dict[str, object]:
        result: dict[str, object] = {}
        for algorithm_id, attempts in populations.items():
            sweeps = build_scope_sweeps(
                attempts,
                score_direction=score_directions[algorithm_id],
                releases=releases,
            )
            result[algorithm_id] = {
                "sweeps": sweeps,
                "far_targets": {
                    scope: tuple(
                        select_far_target_point(sweep, target) for target in targets
                    )
                    for scope, sweep in sweeps.items()
                },
            }
        return result

    return {
        "primary_all_attempt": evaluate_view(attempts_by_algorithm),
        "secondary_common_score": evaluate_view(common),
    }
