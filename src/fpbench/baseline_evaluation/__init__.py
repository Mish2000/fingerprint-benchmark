"""Final-baseline TAR/FAR/FRR reporting, isolated from calibration."""

from fpbench.baseline_evaluation.models import (
    BaselineEvaluationError,
    BaselinePopulation,
    BoundaryKind,
    EvaluationAttempt,
    FarTargetPoint,
    OperationalCounts,
    PopulationPointCounts,
    Rate,
    ScoreSweep,
    ScoreSweepPoint,
    ScoreValue,
)
from fpbench.baseline_evaluation.sweep import (
    build_score_sweep,
    build_scope_sweeps,
    common_score_population,
    evaluate_comparison_roster,
    select_far_target_point,
)
from fpbench.baseline_evaluation.policy import (
    BaselineEvaluationPolicy,
    load_baseline_evaluation_policy,
)
from fpbench.baseline_evaluation.roster import (
    ADDITIONAL_METHOD_ROLE,
    FINAL_BASELINE_ROSTER_ID,
    PRIMARY_BASELINE_ROLE,
    BaselineRosterConfig,
    BaselineRosterExclusion,
    BaselineRosterMethod,
    load_baseline_roster_config,
)

__all__ = [
    "BaselineEvaluationError",
    "BaselineEvaluationPolicy",
    "BaselinePopulation",
    "BaselineRosterConfig",
    "BaselineRosterExclusion",
    "BaselineRosterMethod",
    "BoundaryKind",
    "EvaluationAttempt",
    "FarTargetPoint",
    "OperationalCounts",
    "PopulationPointCounts",
    "Rate",
    "ScoreSweep",
    "ScoreSweepPoint",
    "ScoreValue",
    "ADDITIONAL_METHOD_ROLE",
    "FINAL_BASELINE_ROSTER_ID",
    "PRIMARY_BASELINE_ROLE",
    "build_score_sweep",
    "build_scope_sweeps",
    "common_score_population",
    "evaluate_comparison_roster",
    "select_far_target_point",
    "load_baseline_evaluation_policy",
    "load_baseline_roster_config",
]
