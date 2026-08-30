"""Strict loading of the Stage 21A evaluation-policy freeze."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Mapping

import yaml

from fpbench.core.config_values import (
    reject_unknown_keys,
    require_yaml_bool,
    require_yaml_exact_int,
    require_yaml_non_empty_str,
)
from fpbench.core.errors import ConfigurationError
from fpbench.baseline_evaluation.roster import (
    BaselineRosterConfig,
    load_baseline_roster_config,
)

__all__ = ["BaselineEvaluationPolicy", "load_baseline_evaluation_policy"]


@dataclass(frozen=True, slots=True)
class BaselineEvaluationPolicy:
    comparison_id: str
    roster_config: Path
    roster: BaselineRosterConfig
    allowed_metrics: tuple[str, ...]
    genuine_population: str
    impostor_population: str
    primary_far_target: Fraction
    far_targets: tuple[Fraction, ...]
    per_release: bool
    pooled: bool
    common_score_secondary: bool


_TOP_KEYS = frozenset(
    {
        "schema_version",
        "comparison",
        "metrics",
        "populations",
        "primary_view",
        "threshold_evaluation",
        "far_targets",
        "reporting",
    }
)
_COMPARISON_KEYS = frozenset({"id", "roster_ref"})
_METRIC_KEYS = frozenset({"allowed"})
_POPULATION_KEYS = frozenset(
    {"genuine", "impostor", "eligibility_filtering", "self_role"}
)
_PRIMARY_KEYS = frozenset(
    {
        "denominator",
        "genuine_failure",
        "impostor_failure",
        "operational_counts",
    }
)
_SWEEP_KEYS = frozenset(
    {
        "mode",
        "calibration",
        "create_operational_threshold",
        "create_threshold_profile",
        "interpolation",
        "ties",
        "score_normalization",
        "cross_algorithm_raw_score_comparison",
        "algorithm_parameters_changed",
    }
)
_TARGET_KEYS = frozenset({"primary", "secondary"})
_REPORTING_KEYS = frozenset(
    {"per_release", "pooled", "pooled_aggregation", "common_score_secondary"}
)


def _mapping(document: Mapping[str, Any], key: str, where: str) -> Mapping[str, Any]:
    value = document.get(key)
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"{where}: missing or malformed '{key}' section")
    return value


def _strings(document: Mapping[str, Any], key: str, where: str) -> tuple[str, ...]:
    value = document.get(key)
    if not isinstance(value, (list, tuple)) or isinstance(value, str):
        raise ConfigurationError(f"{where}: '{key}' must be a YAML list")
    result = tuple(value)
    if not result or any(not isinstance(item, str) or not item for item in result):
        raise ConfigurationError(f"{where}: '{key}' must contain non-empty strings")
    if len(result) != len(set(result)):
        raise ConfigurationError(f"{where}: '{key}' contains duplicates")
    return result


def _literal(document: Mapping[str, Any], key: str, expected: str, where: str) -> None:
    actual = require_yaml_non_empty_str(document, key, where=where)
    if actual != expected:
        raise ConfigurationError(
            f"{where}: '{key}' must be {expected!r}, got {actual!r}"
        )


def _false(document: Mapping[str, Any], key: str, where: str) -> None:
    if require_yaml_bool(document, key, where=where):
        raise ConfigurationError(f"{where}: '{key}' must remain false")


def _fraction(value: object, where: str) -> Fraction:
    if isinstance(value, bool):
        raise ConfigurationError(f"{where}: FAR target must be numeric")
    try:
        result = Fraction(str(value))
    except (ValueError, ZeroDivisionError) as exc:
        raise ConfigurationError(f"{where}: invalid FAR target {value!r}") from exc
    if not 0 < result <= 1:
        raise ConfigurationError(f"{where}: FAR target must lie in (0, 1]")
    return result


def load_baseline_evaluation_policy(path: Path) -> BaselineEvaluationPolicy:
    path = Path(path)
    if not path.is_file():
        raise ConfigurationError(f"baseline evaluation config not found: {path}")
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(document, Mapping):
        raise ConfigurationError(f"{path}: expected a top-level mapping")
    where = str(path)
    reject_unknown_keys(document, _TOP_KEYS, where=where)
    if require_yaml_exact_int(document, "schema_version", where=where, minimum=1) != 1:
        raise ConfigurationError(f"{where}: schema_version must be 1")

    comparison = _mapping(document, "comparison", where)
    metrics = _mapping(document, "metrics", where)
    populations = _mapping(document, "populations", where)
    primary = _mapping(document, "primary_view", where)
    sweep = _mapping(document, "threshold_evaluation", where)
    targets = _mapping(document, "far_targets", where)
    reporting = _mapping(document, "reporting", where)
    for section, allowed, label in (
        (comparison, _COMPARISON_KEYS, "comparison"),
        (metrics, _METRIC_KEYS, "metrics"),
        (populations, _POPULATION_KEYS, "populations"),
        (primary, _PRIMARY_KEYS, "primary_view"),
        (sweep, _SWEEP_KEYS, "threshold_evaluation"),
        (targets, _TARGET_KEYS, "far_targets"),
        (reporting, _REPORTING_KEYS, "reporting"),
    ):
        reject_unknown_keys(section, allowed, where=f"{where}: {label}")

    allowed_metrics = _strings(metrics, "allowed", f"{where}: metrics")
    if allowed_metrics != ("TAR", "FAR", "FRR"):
        raise ConfigurationError("Stage 21 reporting permits only TAR, FAR and FRR")

    populations_where = f"{where}: populations"
    genuine = require_yaml_non_empty_str(
        populations, "genuine", where=populations_where
    )
    impostor = require_yaml_non_empty_str(
        populations, "impostor", where=populations_where
    )
    if genuine != "plain_roll_mated" or impostor != (
        "plain_roll_cross_subject_non_mated"
    ):
        raise ConfigurationError("the frozen genuine or impostor population changed")
    _literal(populations, "eligibility_filtering", "forbidden", populations_where)
    _literal(populations, "self_role", "diagnostic_only", populations_where)

    primary_where = f"{where}: primary_view"
    _literal(primary, "denominator", "all_planned_attempts", primary_where)
    _literal(primary, "genuine_failure", "not_accepted", primary_where)
    _literal(primary, "impostor_failure", "not_false_accept", primary_where)
    counts = _strings(primary, "operational_counts", primary_where)
    if counts != ("planned_attempts", "score_bearing_attempts", "algorithm_failures"):
        raise ConfigurationError(f"{primary_where}: operational counts changed")

    sweep_where = f"{where}: threshold_evaluation"
    _literal(sweep, "mode", "exhaustive_score_sweep", sweep_where)
    _false(sweep, "calibration", sweep_where)
    _false(sweep, "create_operational_threshold", sweep_where)
    _false(sweep, "create_threshold_profile", sweep_where)
    _literal(sweep, "interpolation", "forbidden", sweep_where)
    _literal(sweep, "ties", "move_together", sweep_where)
    _literal(sweep, "score_normalization", "forbidden", sweep_where)
    _literal(
        sweep,
        "cross_algorithm_raw_score_comparison",
        "forbidden",
        sweep_where,
    )
    _false(sweep, "algorithm_parameters_changed", sweep_where)

    primary_target = _fraction(targets.get("primary"), f"{where}: far_targets.primary")
    secondary_raw = targets.get("secondary")
    if not isinstance(secondary_raw, (list, tuple)) or isinstance(secondary_raw, str):
        raise ConfigurationError(f"{where}: far_targets.secondary must be a list")
    secondary = tuple(
        _fraction(value, f"{where}: far_targets.secondary[{index}]")
        for index, value in enumerate(secondary_raw)
    )
    all_targets = (primary_target, *secondary)
    if primary_target != Fraction(1, 1000) or set(all_targets) != {
        Fraction(1, 100),
        Fraction(1, 1000),
        Fraction(1, 10000),
    }:
        raise ConfigurationError("the three predeclared FAR targets changed")

    reporting_where = f"{where}: reporting"
    per_release = require_yaml_bool(
        reporting, "per_release", where=reporting_where
    )
    pooled = require_yaml_bool(reporting, "pooled", where=reporting_where)
    common = require_yaml_bool(
        reporting, "common_score_secondary", where=reporting_where
    )
    if not (per_release and pooled and common):
        raise ConfigurationError("all frozen reporting views must remain enabled")
    _literal(
        reporting,
        "pooled_aggregation",
        "sum_numerators_and_denominators",
        reporting_where,
    )

    comparison_id = require_yaml_non_empty_str(
        comparison, "id", where=f"{where}: comparison"
    )
    if comparison_id != "final_baseline_tar_far_frr_v1":
        raise ConfigurationError(
            f"{where}: comparison id must remain 'final_baseline_tar_far_frr_v1'"
        )
    roster_ref = require_yaml_non_empty_str(
        comparison, "roster_ref", where=f"{where}: comparison"
    )
    if roster_ref != "configs/comparisons/final_baseline_roster_v1.yaml":
        raise ConfigurationError(f"{where}: the frozen roster_ref changed")
    repo_root = path.resolve().parent.parent.parent
    roster_config = (repo_root / roster_ref).resolve()
    roster = load_baseline_roster_config(roster_config)

    return BaselineEvaluationPolicy(
        comparison_id=comparison_id,
        roster_config=roster_config,
        roster=roster,
        allowed_metrics=allowed_metrics,
        genuine_population=genuine,
        impostor_population=impostor,
        primary_far_target=primary_target,
        far_targets=all_targets,
        per_release=per_release,
        pooled=pooled,
        common_score_secondary=common,
    )
