"""Strict loading of the Stage 21A final-comparison roster.

The roster is selected from already-finalized metadata.  This module deliberately
has no result-store dependency, so loading it cannot inspect a raw score value.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from fpbench.core.config_values import (
    reject_unknown_keys,
    require_yaml_bool,
    require_yaml_exact_int,
    require_yaml_non_empty_str,
)
from fpbench.core.errors import ConfigurationError

__all__ = [
    "ADDITIONAL_METHOD_ROLE",
    "BaselineRosterConfig",
    "BaselineRosterExclusion",
    "BaselineRosterMethod",
    "FINAL_BASELINE_ROSTER_ID",
    "PRIMARY_BASELINE_ROLE",
    "load_baseline_roster_config",
]


FINAL_BASELINE_ROSTER_ID = "final_baseline_roster_v1"
PRIMARY_BASELINE_ROLE = "primary_baseline"
ADDITIONAL_METHOD_ROLE = "additional_experimentally_evaluated_method"
_ALLOWED_ROLES = frozenset({PRIMARY_BASELINE_ROLE, ADDITIONAL_METHOD_ROLE})

_TOP_KEYS = frozenset(
    {
        "schema_version",
        "roster_id",
        "selection_uses_score_values",
        "methods",
        "common_score_population",
        "excluded_completed_routes",
    }
)
_METHOD_KEYS = frozenset({"algorithm_id", "role"})
_COMMON_KEYS = frozenset({"membership", "primary_result"})
_EXCLUSION_KEYS = frozenset(
    {"algorithm_id", "reason", "decision_uses_score_values"}
)


@dataclass(frozen=True, slots=True)
class BaselineRosterMethod:
    algorithm_id: str
    role: str


@dataclass(frozen=True, slots=True)
class BaselineRosterExclusion:
    algorithm_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class BaselineRosterConfig:
    roster_id: str
    methods: tuple[BaselineRosterMethod, ...]
    common_score_membership: str
    common_score_primary: bool
    exclusions: tuple[BaselineRosterExclusion, ...]

    @property
    def method_ids(self) -> tuple[str, ...]:
        return tuple(method.algorithm_id for method in self.methods)

    @property
    def method_bindings(self) -> tuple[tuple[str, str], ...]:
        return tuple((method.algorithm_id, method.role) for method in self.methods)


def _mapping(document: Mapping[str, Any], key: str, where: str) -> Mapping[str, Any]:
    value = document.get(key)
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"{where}: missing or malformed '{key}' section")
    return value


def _mapping_sequence(
    document: Mapping[str, Any],
    key: str,
    *,
    where: str,
    allow_empty: bool,
) -> tuple[Mapping[str, Any], ...]:
    value = document.get(key)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ConfigurationError(f"{where}: '{key}' must be a YAML list")
    if not value and not allow_empty:
        raise ConfigurationError(f"{where}: '{key}' must not be empty")
    rows: list[Mapping[str, Any]] = []
    for index, row in enumerate(value):
        if not isinstance(row, Mapping):
            raise ConfigurationError(f"{where}: {key}[{index}] must be a mapping")
        rows.append(row)
    return tuple(rows)


def load_baseline_roster_config(path: Path) -> BaselineRosterConfig:
    """Load the score-independent, five-plus-method final roster."""
    path = Path(path)
    if not path.is_file():
        raise ConfigurationError(f"baseline roster config not found: {path}")
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(document, Mapping):
        raise ConfigurationError(f"{path}: expected a top-level mapping")
    where = str(path)
    reject_unknown_keys(document, _TOP_KEYS, where=where)
    if require_yaml_exact_int(document, "schema_version", where=where, minimum=1) != 1:
        raise ConfigurationError(f"{where}: schema_version must be 1")

    roster_id = require_yaml_non_empty_str(document, "roster_id", where=where)
    if roster_id != FINAL_BASELINE_ROSTER_ID:
        raise ConfigurationError(
            f"{where}: roster_id must remain {FINAL_BASELINE_ROSTER_ID!r}"
        )
    if require_yaml_bool(document, "selection_uses_score_values", where=where):
        raise ConfigurationError(
            f"{where}: roster selection must not use score values"
        )

    methods: list[BaselineRosterMethod] = []
    for index, row in enumerate(
        _mapping_sequence(document, "methods", where=where, allow_empty=False)
    ):
        row_where = f"{where}: methods[{index}]"
        reject_unknown_keys(row, _METHOD_KEYS, where=row_where)
        algorithm_id = require_yaml_non_empty_str(
            row, "algorithm_id", where=row_where
        )
        role = require_yaml_non_empty_str(row, "role", where=row_where)
        if role not in _ALLOWED_ROLES:
            raise ConfigurationError(
                f"{row_where}: role must be one of {sorted(_ALLOWED_ROLES)!r}"
            )
        methods.append(BaselineRosterMethod(algorithm_id=algorithm_id, role=role))
    method_ids = [method.algorithm_id for method in methods]
    if len(method_ids) != len(set(method_ids)):
        raise ConfigurationError(f"{where}: roster algorithm_ids must be unique")
    if len(methods) < 5:
        raise ConfigurationError(f"{where}: final comparison requires at least five methods")
    if sum(method.role == PRIMARY_BASELINE_ROLE for method in methods) < 5:
        raise ConfigurationError(
            f"{where}: the five frozen primary baselines must remain present"
        )

    common = _mapping(document, "common_score_population", where)
    common_where = f"{where}: common_score_population"
    reject_unknown_keys(common, _COMMON_KEYS, where=common_where)
    membership = require_yaml_non_empty_str(common, "membership", where=common_where)
    if membership != "all_roster_methods":
        raise ConfigurationError(
            f"{common_where}: membership must remain 'all_roster_methods'"
        )
    common_primary = require_yaml_bool(common, "primary_result", where=common_where)
    if common_primary:
        raise ConfigurationError(
            f"{common_where}: common-score analysis must remain secondary"
        )

    exclusions: list[BaselineRosterExclusion] = []
    for index, row in enumerate(
        _mapping_sequence(
            document,
            "excluded_completed_routes",
            where=where,
            allow_empty=True,
        )
    ):
        row_where = f"{where}: excluded_completed_routes[{index}]"
        reject_unknown_keys(row, _EXCLUSION_KEYS, where=row_where)
        algorithm_id = require_yaml_non_empty_str(
            row, "algorithm_id", where=row_where
        )
        reason = require_yaml_non_empty_str(row, "reason", where=row_where)
        if require_yaml_bool(row, "decision_uses_score_values", where=row_where):
            raise ConfigurationError(
                f"{row_where}: an exclusion decision must not use score values"
            )
        exclusions.append(
            BaselineRosterExclusion(algorithm_id=algorithm_id, reason=reason)
        )
    excluded_ids = [exclusion.algorithm_id for exclusion in exclusions]
    if len(excluded_ids) != len(set(excluded_ids)):
        raise ConfigurationError(f"{where}: excluded algorithm_ids must be unique")
    overlap = sorted(set(method_ids) & set(excluded_ids))
    if overlap:
        raise ConfigurationError(
            f"{where}: methods cannot also be excluded: {overlap}"
        )

    return BaselineRosterConfig(
        roster_id=roster_id,
        methods=tuple(methods),
        common_score_membership=membership,
        common_score_primary=common_primary,
        exclusions=tuple(exclusions),
    )
