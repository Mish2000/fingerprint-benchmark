"""Score-sweep models for the frozen TAR/FAR/FRR reporting layer.

Nothing in this package is an operating threshold, a decision profile or an
adapter parameter.  A cut is an observed reporting boundary on one algorithm's
own raw-score scale and is never reused by execution.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from fractions import Fraction
from typing import TypeAlias

from fpbench.core.enums import ExecutionStatus, GroundTruth, ScoreDirection

__all__ = [
    "BaselineEvaluationError",
    "BaselinePopulation",
    "BoundaryKind",
    "EvaluationAttempt",
    "FarTargetPoint",
    "OperationalCounts",
    "PopulationPointCounts",
    "Rate",
    "ScoreSweep",
    "ScoreSweepPoint",
    "ScoreValue",
]


ScoreValue: TypeAlias = int | float


class BaselineEvaluationError(ValueError):
    """An input would make TAR, FAR or FRR mean something else."""


class BaselinePopulation(str, Enum):
    GENUINE = "plain_roll_mated"
    IMPOSTOR = "plain_roll_cross_subject_non_mated"


class BoundaryKind(str, Enum):
    ACCEPT_NONE = "accept_none"
    OBSERVED_SCORE_CUT = "observed_score_cut"


@dataclass(frozen=True, slots=True)
class EvaluationAttempt:
    """One planned attempt, including a scoreless algorithm failure."""

    pair_id: str
    release: str
    population: BaselinePopulation
    ground_truth: GroundTruth
    status: ExecutionStatus
    score: ScoreValue | None

    def __post_init__(self) -> None:
        if not self.pair_id.strip() or not self.release.strip():
            raise BaselineEvaluationError("pair_id and release must be non-empty")
        if not isinstance(self.population, BaselinePopulation):
            raise BaselineEvaluationError("population must be a BaselinePopulation")
        if not isinstance(self.ground_truth, GroundTruth):
            raise BaselineEvaluationError("ground_truth must be a GroundTruth")
        expected_truth = (
            GroundTruth.MATED
            if self.population is BaselinePopulation.GENUINE
            else GroundTruth.NON_MATED
        )
        if self.ground_truth is not expected_truth:
            raise BaselineEvaluationError(
                f"{self.population.value} cannot carry {self.ground_truth.value} truth"
            )
        if not isinstance(self.status, ExecutionStatus):
            raise BaselineEvaluationError("status must be an ExecutionStatus")
        if self.status is ExecutionStatus.SUCCESS:
            if isinstance(self.score, bool) or not isinstance(self.score, (int, float)):
                raise BaselineEvaluationError(
                    "a successful attempt must carry its numeric raw score"
                )
            if not math.isfinite(self.score):
                raise BaselineEvaluationError("raw scores must be finite")
        elif self.score is not None:
            raise BaselineEvaluationError(
                "an algorithm failure must not be converted into a numeric score"
            )


@dataclass(frozen=True, slots=True)
class Rate:
    numerator: int
    denominator: int

    def __post_init__(self) -> None:
        if self.denominator <= 0:
            raise BaselineEvaluationError("a biometric rate needs a positive denominator")
        if not 0 <= self.numerator <= self.denominator:
            raise BaselineEvaluationError("rate numerator must lie within its denominator")

    @property
    def fraction(self) -> Fraction:
        return Fraction(self.numerator, self.denominator)

    @property
    def value(self) -> float:
        return float(self.fraction)


@dataclass(frozen=True, slots=True)
class OperationalCounts:
    planned_attempts: int
    score_bearing_attempts: int
    algorithm_failures: int

    def __post_init__(self) -> None:
        if min(
            self.planned_attempts,
            self.score_bearing_attempts,
            self.algorithm_failures,
        ) < 0:
            raise BaselineEvaluationError("operational counts cannot be negative")
        if self.score_bearing_attempts + self.algorithm_failures != self.planned_attempts:
            raise BaselineEvaluationError(
                "score-bearing attempts plus failures must equal planned attempts"
            )


@dataclass(frozen=True, slots=True)
class PopulationPointCounts:
    operational: OperationalCounts
    accepted: int

    def __post_init__(self) -> None:
        if not 0 <= self.accepted <= self.operational.score_bearing_attempts:
            raise BaselineEvaluationError(
                "only score-bearing attempts can be accepted"
            )


@dataclass(frozen=True, slots=True)
class ScoreSweepPoint:
    """Observed TAR/FAR/FRR at one atomic score boundary."""

    ordinal: int
    boundary_kind: BoundaryKind
    score_cut: ScoreValue | None
    comparator: str | None
    genuine: PopulationPointCounts
    impostor: PopulationPointCounts
    accepts_all_score_bearing: bool = False

    @property
    def tar(self) -> Rate:
        return Rate(self.genuine.accepted, self.genuine.operational.planned_attempts)

    @property
    def frr(self) -> Rate:
        return Rate(
            self.genuine.operational.planned_attempts - self.genuine.accepted,
            self.genuine.operational.planned_attempts,
        )

    @property
    def far(self) -> Rate:
        return Rate(self.impostor.accepted, self.impostor.operational.planned_attempts)

    @property
    def accepted_score_bearing(self) -> int:
        return self.genuine.accepted + self.impostor.accepted


@dataclass(frozen=True, slots=True)
class ScoreSweep:
    scope: str
    score_direction: ScoreDirection
    points: tuple[ScoreSweepPoint, ...]

    def __post_init__(self) -> None:
        if not self.points:
            raise BaselineEvaluationError("a score sweep must contain its endpoints")
        if self.points[0].boundary_kind is not BoundaryKind.ACCEPT_NONE:
            raise BaselineEvaluationError("the first sweep point must accept none")
        if not self.points[-1].accepts_all_score_bearing:
            raise BaselineEvaluationError(
                "the final sweep point must accept every score-bearing attempt"
            )


@dataclass(frozen=True, slots=True)
class FarTargetPoint:
    """The best observed, non-interpolated point at a predeclared FAR target."""

    requested_far: Fraction
    observed: ScoreSweepPoint
    interpolation_performed: bool = False

    def __post_init__(self) -> None:
        if not 0 <= self.requested_far <= 1:
            raise BaselineEvaluationError("FAR target must lie in [0, 1]")
        if self.observed.far.fraction > self.requested_far:
            raise BaselineEvaluationError("observed FAR exceeds the requested target")
        if self.interpolation_performed:
            raise BaselineEvaluationError("interpolation is forbidden")
