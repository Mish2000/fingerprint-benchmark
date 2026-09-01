"""Strict loading of the frozen `final_baseline_reporting_v1` profile.

The report profile decides how the Stage 21A numbers are *shown* — scopes,
tables, disclosures, the contextual native-rule table.  Like the evaluation
policy it can only be re-validated, never reinterpreted: every literal the
freeze fixed is required verbatim, and an unknown key is an error rather than
a shrug.
"""

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
from fpbench.final_baseline.constants import EXPECTED_RELEASES, POOLED_SCOPE

__all__ = [
    "NativeDocumentedRule",
    "FinalBaselineReporting",
    "load_final_baseline_reporting",
]


#: The complete vocabulary a native documented rule may use.  A new rule kind
#: is a protocol change, not a config edit.
_RULE_COMPARATORS: Mapping[str, tuple[str, float] | None] = {
    "score_greater_than_or_equal_to_40": ("greater_than_or_equal", 40.0),
    "score_greater_than_40": ("greater_than", 40.0),
    "none": None,
    "none_unless_formally_authorized_as_native_documented_rule": None,
}

_TOP_KEYS = frozenset(
    {
        "schema_version",
        "report_id",
        "comparison_ref",
        "biometric_columns",
        "scopes",
        "primary_table",
        "primary_far_target",
        "show_requested_and_observed_far",
        "show_operational_counts",
        "interpolation",
        "pooled",
        "secondary_view",
        "legacy_negative_population",
        "native_documented_rules",
    }
)
_POOLED_KEYS = frozenset(
    {"aggregation", "interpretation", "release_dependence_disclosure"}
)
_SECONDARY_KEYS = frozenset({"id", "primary_result", "membership"})
_NEGATIVE_KEYS = frozenset({"id", "label", "used_as_primary_far_denominator"})
_NATIVE_KEYS = frozenset(
    {"purpose", "direct_cross_algorithm_ranking", "methods"}
)


@dataclass(frozen=True, slots=True)
class NativeDocumentedRule:
    """One method's upstream-documented decision rule, or its absence."""

    algorithm_id: str
    rule: str
    comparator: str | None
    threshold: float | None

    @property
    def exists(self) -> bool:
        return self.comparator is not None

    def accepts(self, score: float) -> bool:
        if self.comparator == "greater_than_or_equal":
            return score >= float(self.threshold)  # type: ignore[arg-type]
        if self.comparator == "greater_than":
            return score > float(self.threshold)  # type: ignore[arg-type]
        raise ConfigurationError(
            f"{self.algorithm_id} has no native documented rule to apply"
        )


@dataclass(frozen=True, slots=True)
class FinalBaselineReporting:
    report_id: str
    comparison_ref: str
    scopes: tuple[str, ...]
    primary_far_target: Fraction
    release_dependence_disclosure: str
    secondary_view_id: str
    secondary_view_membership: str
    legacy_negative_label: str
    native_rules: tuple[NativeDocumentedRule, ...]

    def native_rule(self, algorithm_id: str) -> NativeDocumentedRule:
        for rule in self.native_rules:
            if rule.algorithm_id == algorithm_id:
                return rule
        raise ConfigurationError(
            f"no native documented rule entry for {algorithm_id!r}"
        )


def _mapping(document: Mapping[str, Any], key: str, where: str) -> Mapping[str, Any]:
    value = document.get(key)
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"{where}: missing or malformed '{key}' section")
    return value


def _literal(document: Mapping[str, Any], key: str, expected: str, where: str) -> str:
    actual = require_yaml_non_empty_str(document, key, where=where)
    if actual != expected:
        raise ConfigurationError(
            f"{where}: '{key}' must be {expected!r}, got {actual!r}"
        )
    return actual


def load_final_baseline_reporting(
    path: Path, *, roster_method_ids: tuple[str, ...]
) -> FinalBaselineReporting:
    path = Path(path)
    if not path.is_file():
        raise ConfigurationError(f"final baseline reporting config not found: {path}")
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(document, Mapping):
        raise ConfigurationError(f"{path}: expected a top-level mapping")
    where = str(path)
    reject_unknown_keys(document, _TOP_KEYS, where=where)
    if require_yaml_exact_int(document, "schema_version", where=where, minimum=1) != 1:
        raise ConfigurationError(f"{where}: schema_version must be 1")

    report_id = _literal(document, "report_id", "final_baseline_reporting_v1", where)
    comparison_ref = _literal(
        document,
        "comparison_ref",
        "configs/comparisons/final_baseline_tar_far_frr_v1.yaml",
        where,
    )

    columns = document.get("biometric_columns")
    if tuple(columns or ()) != ("TAR", "FAR", "FRR"):
        raise ConfigurationError(f"{where}: biometric_columns must be [TAR, FAR, FRR]")
    scopes = tuple(document.get("scopes") or ())
    if scopes != (*EXPECTED_RELEASES, POOLED_SCOPE):
        raise ConfigurationError(
            f"{where}: scopes must be {[*EXPECTED_RELEASES, POOLED_SCOPE]}"
        )

    _literal(document, "primary_table", "same_target_far", where)
    primary_raw = document.get("primary_far_target")
    if isinstance(primary_raw, bool) or primary_raw is None:
        raise ConfigurationError(f"{where}: primary_far_target must be numeric")
    primary = Fraction(str(primary_raw))
    if primary != Fraction(1, 1000):
        raise ConfigurationError(f"{where}: primary_far_target must remain 0.001")
    if not require_yaml_bool(document, "show_requested_and_observed_far", where=where):
        raise ConfigurationError(
            f"{where}: show_requested_and_observed_far must remain true"
        )
    if not require_yaml_bool(document, "show_operational_counts", where=where):
        raise ConfigurationError(f"{where}: show_operational_counts must remain true")
    if require_yaml_bool(document, "interpolation", where=where):
        raise ConfigurationError(f"{where}: interpolation must remain false")

    pooled = _mapping(document, "pooled", where)
    pooled_where = f"{where}: pooled"
    reject_unknown_keys(pooled, _POOLED_KEYS, where=pooled_where)
    _literal(pooled, "aggregation", "sum_numerators_and_denominators", pooled_where)
    _literal(pooled, "interpretation", "descriptive_summary", pooled_where)
    disclosure = require_yaml_non_empty_str(
        pooled, "release_dependence_disclosure", where=pooled_where
    )

    secondary = _mapping(document, "secondary_view", where)
    secondary_where = f"{where}: secondary_view"
    reject_unknown_keys(secondary, _SECONDARY_KEYS, where=secondary_where)
    secondary_id = _literal(secondary, "id", "common_score_population", secondary_where)
    if require_yaml_bool(secondary, "primary_result", where=secondary_where):
        raise ConfigurationError(
            f"{secondary_where}: the common-score view must remain secondary"
        )
    membership = _literal(
        secondary,
        "membership",
        "pairs_scored_by_every_roster_method",
        secondary_where,
    )

    negative = _mapping(document, "legacy_negative_population", where)
    negative_where = f"{where}: legacy_negative_population"
    reject_unknown_keys(negative, _NEGATIVE_KEYS, where=negative_where)
    _literal(negative, "id", "plain_roll_non_mated", negative_where)
    negative_label = require_yaml_non_empty_str(negative, "label", where=negative_where)
    if require_yaml_bool(
        negative, "used_as_primary_far_denominator", where=negative_where
    ):
        raise ConfigurationError(
            f"{negative_where}: the sanity population may not become the FAR denominator"
        )

    native = _mapping(document, "native_documented_rules", where)
    native_where = f"{where}: native_documented_rules"
    reject_unknown_keys(native, _NATIVE_KEYS, where=native_where)
    _literal(native, "purpose", "separate_context_table_only", native_where)
    _literal(
        native, "direct_cross_algorithm_ranking", "forbidden", native_where
    )
    methods = _mapping(native, "methods", native_where)
    if tuple(sorted(methods)) != tuple(sorted(roster_method_ids)):
        raise ConfigurationError(
            f"{native_where}: rule entries must cover exactly the roster methods; "
            f"got {sorted(methods)}, roster is {sorted(roster_method_ids)}"
        )
    rules: list[NativeDocumentedRule] = []
    for algorithm_id in roster_method_ids:
        entry = methods[algorithm_id]
        entry_where = f"{native_where}: {algorithm_id}"
        if not isinstance(entry, Mapping):
            raise ConfigurationError(f"{entry_where}: must be a mapping")
        reject_unknown_keys(entry, frozenset({"rule"}), where=entry_where)
        rule = require_yaml_non_empty_str(entry, "rule", where=entry_where)
        if rule not in _RULE_COMPARATORS:
            raise ConfigurationError(
                f"{entry_where}: unknown native rule {rule!r}; the vocabulary is "
                f"{sorted(_RULE_COMPARATORS)}"
            )
        resolved = _RULE_COMPARATORS[rule]
        rules.append(
            NativeDocumentedRule(
                algorithm_id=algorithm_id,
                rule=rule,
                comparator=None if resolved is None else resolved[0],
                threshold=None if resolved is None else resolved[1],
            )
        )

    return FinalBaselineReporting(
        report_id=report_id,
        comparison_ref=comparison_ref,
        scopes=scopes,
        primary_far_target=primary,
        release_dependence_disclosure=disclosure,
        secondary_view_id=secondary_id,
        secondary_view_membership=membership,
        legacy_negative_label=negative_label,
        native_rules=tuple(rules),
    )
