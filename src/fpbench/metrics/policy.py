"""The catalogue of metrics, and reading which of them a policy switches on.

Metric ids are **fixed in code**, not composed from a config file. That is the
opposite of how the decision profile works, and deliberately so: a threshold is
a number somebody chooses, whereas ``plain_roll_mated_unconditional_fnmr_decided``
is a *definition*, and a definition assembled at load time from YAML fragments is
a definition that can be quietly re-pointed at a different denominator. Here the
YAML says which metrics to compute; it cannot say what one means.

Each entry in :data:`METRIC_CATALOGUE` names four things that together fix the
number: the count family it reads, the numerator, the denominator, and a
one-line interpretation that travels into the policy fingerprint. Two of them
carry ``prohibited_labels`` as well — the sanity-check metrics — so that the
refusal to call them a false-match rate is part of their identity rather than a
footnote (docs/adr/0030).

The display fields (`percentage_decimal_places`, `always_show_fraction`,
`zero_format`) are parsed from the same file but belong to the
:class:`~fpbench.core.metric_models.ReportProfile`, which is built here too.
Rounding a percentage differently changes how a report reads and changes nothing
about what was measured, so it must not change the metric-set id (spec section
23).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from fpbench.core.enums import ProtocolStage
from fpbench.core.errors import MetricPolicyError
from fpbench.core.evaluation_view_models import (
    MATED_CONDITIONAL_VIEW,
    MATED_UNCONDITIONAL_VIEW,
    NON_MATED_SANITY_VIEW,
)
from fpbench.core.metric_models import (
    POOLED_AGGREGATION_SUM_COUNTS,
    UNIT_OF_ANALYSIS_COMPARISON,
    ZERO_FORMAT_OBSERVED_ZERO,
    CountFamily,
    MetricDefinition,
    MetricDenominator,
    MetricNumerator,
    MetricPolicy,
    ReportProfile,
    metric_policy_fingerprint,
    report_profile_fingerprint,
)

__all__ = [
    "METRIC_CATALOGUE",
    "METRIC_CATALOGUE_ORDER",
    "CATALOGUE_SWITCHES",
    "REPORT_PROFILE_TEMPLATES",
    "NEGATIVE_SANITY_METADATA",
    "load_metric_policy",
    "build_metric_policy",
    "build_report_profile",
    "DEFAULT_REPORT_PROFILE_ID",
]

DEFAULT_REPORT_PROFILE_ID = "biometric_evaluation_markdown_en_v1"

#: What the negative set is, in the policy's own metadata and therefore inside
#: its fingerprint. Removing any of it changes the metric-set id.
NEGATIVE_SANITY_METADATA: Mapping[str, str] = {
    "negative_kind": "same_subject_different_finger",
    "pairing_strategy": "cyclic_finger_shift",
    "closed_set": "true",
    "primary_fmr_estimate": "false",
    "purpose": "negative_sanity_check",
}

#: What the sanity-check metrics may never be called. Inside their definitions,
#: therefore inside the policy fingerprint: renaming the refusal away changes the
#: metric set's identity rather than passing unnoticed (docs/adr/0025).
_SANITY_PROHIBITED = (
    "general_fmr",
    "population_fmr",
    "impostor_fmr",
    "false_match_rate",
    "fmr",
)


def _definition(
    metric_id: str,
    *,
    family: str,
    numerator: MetricNumerator,
    denominator: MetricDenominator,
    view_kind: str | None,
    stage: ProtocolStage | None,
    interpretation: str,
    prohibited: tuple[str, ...] = (),
) -> MetricDefinition:
    return MetricDefinition(
        metric_id=metric_id,
        metric_family=family,
        numerator=numerator,
        denominator=denominator,
        source_view_kind=view_kind,
        source_protocol_stage=stage.value if stage is not None else None,
        interpretation=interpretation,
        prohibited_labels=prohibited,
    )


#: Every metric this project defines, in report order. A metric that is not here
#: cannot be computed, whatever a config file asks for.
METRIC_CATALOGUE: Mapping[str, MetricDefinition] = {
    definition.metric_id: definition
    for definition in (
        # ------------------------------------------------------------- SELF
        _definition(
            "plain_self_match_rate_decided",
            family=CountFamily.PLAIN_SELF,
            numerator=MetricNumerator.MATCH,
            denominator=MetricDenominator.DECIDED_ATTEMPTS,
            view_kind=None,
            stage=ProtocolStage.PLAIN_SELF,
            interpretation=(
                "Observed fraction of PLAIN SELF comparisons that matched, among "
                "those that produced a score. Comparisons that produced no score "
                "are not in the denominator."
            ),
        ),
        _definition(
            "plain_self_match_rate_attempt",
            family=CountFamily.PLAIN_SELF,
            numerator=MetricNumerator.MATCH,
            denominator=MetricDenominator.ALL_ATTEMPTS,
            view_kind=None,
            stage=ProtocolStage.PLAIN_SELF,
            interpretation=(
                "Observed fraction of all attempted PLAIN SELF comparisons that "
                "matched. Comparisons that produced no score are in the "
                "denominator and count against this rate."
            ),
        ),
        _definition(
            "roll_self_match_rate_decided",
            family=CountFamily.ROLL_SELF,
            numerator=MetricNumerator.MATCH,
            denominator=MetricDenominator.DECIDED_ATTEMPTS,
            view_kind=None,
            stage=ProtocolStage.ROLL_SELF,
            interpretation=(
                "Observed fraction of ROLL SELF comparisons that matched, among "
                "those that produced a score."
            ),
        ),
        _definition(
            "roll_self_match_rate_attempt",
            family=CountFamily.ROLL_SELF,
            numerator=MetricNumerator.MATCH,
            denominator=MetricDenominator.ALL_ATTEMPTS,
            view_kind=None,
            stage=ProtocolStage.ROLL_SELF,
            interpretation=(
                "Observed fraction of all attempted ROLL SELF comparisons that "
                "matched."
            ),
        ),
        # ------------------------------------------------------ eligibility
        _definition(
            "self_eligibility_rate",
            family=CountFamily.SELF_ELIGIBILITY,
            numerator=MetricNumerator.ELIGIBLE,
            denominator=MetricDenominator.ALL_ELIGIBILITY_UNITS,
            view_kind=None,
            stage=None,
            interpretation=(
                "Observed fraction of release/subject/finger units whose PLAIN and "
                "ROLL SELF comparisons both matched under this decision profile."
            ),
        ),
        _definition(
            "self_ineligible_rate",
            family=CountFamily.SELF_ELIGIBILITY,
            numerator=MetricNumerator.INELIGIBLE,
            denominator=MetricDenominator.ALL_ELIGIBILITY_UNITS,
            view_kind=None,
            stage=None,
            interpretation=(
                "Observed fraction of units disqualified by a SELF non-match. "
                "Distinct from undetermined: this is a measured failure, not a "
                "missing measurement."
            ),
        ),
        _definition(
            "self_undetermined_rate",
            family=CountFamily.SELF_ELIGIBILITY,
            numerator=MetricNumerator.UNDETERMINED,
            denominator=MetricDenominator.ALL_ELIGIBILITY_UNITS,
            view_kind=None,
            stage=None,
            interpretation=(
                "Observed fraction of units whose eligibility could not be "
                "determined because a SELF comparison produced no score."
            ),
        ),
        # ------------------------------------------- unconditional genuine
        _definition(
            "plain_roll_mated_unconditional_fnmr_decided",
            family=CountFamily.MATED_UNCONDITIONAL,
            numerator=MetricNumerator.NON_MATCH,
            denominator=MetricDenominator.DECIDED_ATTEMPTS,
            view_kind=MATED_UNCONDITIONAL_VIEW,
            stage=ProtocolStage.PLAIN_ROLL_MATED,
            interpretation=(
                "Observed mated non-match fraction among mated PLAIN-ROLL "
                "comparisons that produced a score, under this decision profile. "
                "Undecidable comparisons are excluded from the denominator and "
                "reported separately."
            ),
        ),
        _definition(
            "plain_roll_mated_unconditional_non_success_rate_attempt",
            family=CountFamily.MATED_UNCONDITIONAL,
            numerator=MetricNumerator.NON_SUCCESS,
            denominator=MetricDenominator.ALL_ATTEMPTS,
            view_kind=MATED_UNCONDITIONAL_VIEW,
            stage=ProtocolStage.PLAIN_ROLL_MATED,
            interpretation=(
                "Observed fraction of all attempted mated PLAIN-ROLL comparisons "
                "that did not result in a match, counting both non-matches and "
                "comparisons that produced no score. This is an attempt-level "
                "operational rate, not an FNMR."
            ),
            prohibited=("fnmr_without_qualifier",),
        ),
        # --------------------------------------------- conditional genuine
        _definition(
            "plain_roll_mated_conditional_selection_rate",
            family=CountFamily.MATED_CONDITIONAL,
            numerator=MetricNumerator.INCLUDED,
            denominator=MetricDenominator.ALL_ATTEMPTS,
            view_kind=MATED_CONDITIONAL_VIEW,
            stage=ProtocolStage.PLAIN_ROLL_MATED,
            interpretation=(
                "Fraction of mated rows the SELF condition kept. Any conditional "
                "result below is a statement about this subset only, and cannot be "
                "read without it."
            ),
        ),
        _definition(
            "plain_roll_mated_conditional_fnmr_decided",
            family=CountFamily.MATED_CONDITIONAL,
            numerator=MetricNumerator.NON_MATCH,
            denominator=MetricDenominator.DECIDED_CONDITIONAL_ATTEMPTS,
            view_kind=MATED_CONDITIONAL_VIEW,
            stage=ProtocolStage.PLAIN_ROLL_MATED,
            interpretation=(
                "Observed mated non-match fraction among SELF-eligible mated "
                "comparisons that produced a score. The population differs from the "
                "unconditional metric; the two are not a before-and-after."
            ),
        ),
        _definition(
            "plain_roll_mated_conditional_non_success_rate_attempt",
            family=CountFamily.MATED_CONDITIONAL,
            numerator=MetricNumerator.NON_SUCCESS,
            denominator=MetricDenominator.INCLUDED_CONDITIONAL_ATTEMPTS,
            view_kind=MATED_CONDITIONAL_VIEW,
            stage=ProtocolStage.PLAIN_ROLL_MATED,
            interpretation=(
                "Observed fraction of SELF-eligible mated attempts that did not "
                "result in a match. Excluded rows are not in this denominator; they "
                "are accounted for by the selection rate."
            ),
            prohibited=("fnmr_without_qualifier",),
        ),
        # ---------------------------------------------------- negative sanity
        _definition(
            "plain_roll_non_mated_sanity_match_rate_decided",
            family=CountFamily.NEGATIVE_SANITY,
            numerator=MetricNumerator.MATCH,
            denominator=MetricDenominator.DECIDED_ATTEMPTS,
            view_kind=NON_MATED_SANITY_VIEW,
            stage=ProtocolStage.PLAIN_ROLL_NON_MATED,
            interpretation=(
                "Observed matching decisions in the closed-set, same-subject, "
                "different-finger negative sanity check, among comparisons that "
                "produced a score. This is not a false-match rate: the set is "
                "closed, same-subject, and uses one fixed cyclic pairing."
            ),
            prohibited=_SANITY_PROHIBITED,
        ),
        _definition(
            "plain_roll_non_mated_sanity_match_rate_attempt",
            family=CountFamily.NEGATIVE_SANITY,
            numerator=MetricNumerator.MATCH,
            denominator=MetricDenominator.ALL_ATTEMPTS,
            view_kind=NON_MATED_SANITY_VIEW,
            stage=ProtocolStage.PLAIN_ROLL_NON_MATED,
            interpretation=(
                "Observed matching decisions in the closed-set, same-subject, "
                "different-finger negative sanity check, over all attempted "
                "comparisons. This is not a false-match rate."
            ),
            prohibited=_SANITY_PROHIBITED,
        ),
    )
}

#: Report and computation order. The catalogue dict preserves insertion order,
#: but relying on that implicitly would make a reordering invisible.
METRIC_CATALOGUE_ORDER: tuple[str, ...] = tuple(METRIC_CATALOGUE)

#: Which YAML flag switches each metric on. ``(section, subsection, key)``, with
#: ``None`` for a section that has no subsection.
CATALOGUE_SWITCHES: Mapping[str, tuple[str, str | None, str]] = {
    "plain_self_match_rate_decided": ("self", "plain", "match_rate_decided"),
    "plain_self_match_rate_attempt": ("self", "plain", "match_rate_attempt"),
    "roll_self_match_rate_decided": ("self", "roll", "match_rate_decided"),
    "roll_self_match_rate_attempt": ("self", "roll", "match_rate_attempt"),
    "self_eligibility_rate": ("eligibility", None, "eligible_rate"),
    "self_ineligible_rate": ("eligibility", None, "retain_ineligible"),
    "self_undetermined_rate": ("eligibility", None, "retain_undetermined"),
    "plain_roll_mated_unconditional_fnmr_decided": (
        "mated_unconditional",
        None,
        "decision_fnmr",
    ),
    "plain_roll_mated_unconditional_non_success_rate_attempt": (
        "mated_unconditional",
        None,
        "attempt_non_success_rate",
    ),
    "plain_roll_mated_conditional_selection_rate": (
        "mated_conditional",
        None,
        "selection_rate",
    ),
    "plain_roll_mated_conditional_fnmr_decided": (
        "mated_conditional",
        None,
        "decision_fnmr",
    ),
    "plain_roll_mated_conditional_non_success_rate_attempt": (
        "mated_conditional",
        None,
        "attempt_non_success_rate",
    ),
    "plain_roll_non_mated_sanity_match_rate_decided": (
        "negative_sanity",
        None,
        "decision_match_rate",
    ),
    "plain_roll_non_mated_sanity_match_rate_attempt": (
        "negative_sanity",
        None,
        "attempt_match_rate",
    ),
}


@dataclass(frozen=True, slots=True)
class _ReportProfileTemplate:
    """Everything about a report profile except which releases exist."""

    percentage_decimal_places: int
    always_show_fraction: bool
    include_pooled: bool
    language: str


#: The report profiles this project knows how to render. The release order is not
#: here: three SD300 releases are a property of one experiment, and the generic
#: renderer must not hardcode them (spec section 29).
REPORT_PROFILE_TEMPLATES: Mapping[str, _ReportProfileTemplate] = {
    DEFAULT_REPORT_PROFILE_ID: _ReportProfileTemplate(
        percentage_decimal_places=4,
        always_show_fraction=True,
        include_pooled=True,
        # English, so that a reader who does not share the author's first
        # language can still check the numbers in the repository.
        language="en",
    ),
}


# ------------------------------------------------------------------- loading


def load_metric_policy(path: Path) -> MetricPolicy:
    """Read ``configs/metrics/<name>.yaml`` into an immutable policy.

    Raises:
        MetricPolicyError: the file is missing, malformed, switches on a metric
            this project does not define, or asks for a rule this stage refuses.
    """
    path = Path(path)
    if not path.is_file():
        raise MetricPolicyError(f"metric policy not found: {path}")
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(document, Mapping):
        raise MetricPolicyError(f"{path}: expected a mapping at the top level")

    policy = _section(document, "policy", path)
    unit = _section(document, "unit_of_analysis", path)
    display = _section(document, "display", path)

    kind = str(unit.get("kind", "")).strip()
    if kind != UNIT_OF_ANALYSIS_COMPARISON:
        raise MetricPolicyError(
            f"{path}: unit_of_analysis.kind is {kind!r}; this stage counts one "
            f"comparison as one unit ({UNIT_OF_ANALYSIS_COMPARISON})"
        )
    weighting = str(unit.get("subject_weighting", "none")).strip()
    if weighting != "none":
        raise MetricPolicyError(
            f"{path}: subject_weighting {weighting!r} is not supported. Weighting "
            "subjects equally rather than comparisons equally is a defensible "
            "choice and a different metric; it needs its own policy and its own "
            "ADR (docs/adr/0028)"
        )
    pooled = str(unit.get("pooled_aggregation", "")).strip()
    if pooled != POOLED_AGGREGATION_SUM_COUNTS:
        raise MetricPolicyError(
            f"{path}: pooled_aggregation is {pooled!r}; pooled values sum counts "
            f"and divide once ({POOLED_AGGREGATION_SUM_COUNTS}), never average "
            "release percentages (docs/adr/0028)"
        )

    # Two refusals that are the substance of two ADRs, checked before anything
    # is computed rather than at rendering time.
    sanity = _optional_section(document, "negative_sanity")
    if _flag(sanity.get("label_as_fmr", False)):
        raise MetricPolicyError(
            f"{path}: negative_sanity.label_as_fmr may not be true. The impostor "
            "set here is closed, same-subject and cyclically paired; labelling its "
            "match fraction an FMR would claim a population estimate this design "
            "cannot support (docs/adr/0030)"
        )
    conditional = _optional_section(document, "mated_conditional")
    if conditional and not _flag(conditional.get("retain_exclusion_reasons", False)):
        raise MetricPolicyError(
            f"{path}: mated_conditional.retain_exclusion_reasons may not be false. "
            "A conditional result without its exclusion counts cannot be read "
            "(docs/adr/0029)"
        )

    selected: list[MetricDefinition] = []
    for metric_id in METRIC_CATALOGUE_ORDER:
        section, subsection, key = CATALOGUE_SWITCHES[metric_id]
        block = _optional_section(document, section)
        if subsection is not None:
            block = block.get(subsection) or {}
            if not isinstance(block, Mapping):
                raise MetricPolicyError(
                    f"{path}: malformed '{section}.{subsection}' section"
                )
        if _flag(block.get(key, False)):
            selected.append(METRIC_CATALOGUE[metric_id])
    if not selected:
        raise MetricPolicyError(
            f"{path}: no metric is switched on; a policy that computes nothing is "
            "not a policy"
        )

    unknown = _unknown_switches(document)
    if unknown:
        raise MetricPolicyError(
            f"{path}: {sorted(unknown)} do not name any metric this project "
            f"defines. Metric definitions live in code so that a config file "
            f"cannot re-point one at a different denominator"
        )

    metadata = {
        "grouping_releases": str(
            (_optional_section(document, "grouping")).get("releases", "from_protocol")
        ),
        "include_pooled": _render_flag(
            (_optional_section(document, "grouping")).get("include_pooled", True)
        ),
        "negative_sanity_label_as_fmr": "false",
        "conditional_retains_exclusion_reasons": "true",
        # What the impostor set is, carried by the policy so that a metric set
        # read on its own still says so. Stage 5A's view manifest carries the
        # same facts and the metric set pins that view's fingerprint — but a
        # reader holding only ``metric-policy.json`` would otherwise have to
        # follow a fingerprint to find out that the negative fraction is a
        # closed-set sanity check (spec section 45, docs/adr/0025).
        **{
            f"negative_sanity_{key}": value
            for key, value in NEGATIVE_SANITY_METADATA.items()
        },
    }
    extra = document.get("metadata") or {}
    if isinstance(extra, Mapping):
        metadata.update({str(k): str(v) for k, v in extra.items()})

    try:
        return build_metric_policy(
            policy_id=str(policy["policy_id"]),
            policy_version=str(policy.get("policy_version", "1")),
            metric_definitions=tuple(selected),
            percentage_decimal_places=int(display.get("percentage_decimal_places", 4)),
            always_show_fraction=_flag(display.get("always_show_fraction", True)),
            zero_format=str(display.get("zero_format", ZERO_FORMAT_OBSERVED_ZERO)),
            metadata=metadata,
        )
    except KeyError as exc:
        raise MetricPolicyError(f"{path}: missing required key {exc}") from None
    except (TypeError, ValueError) as exc:
        raise MetricPolicyError(f"{path}: {exc}") from None


def build_metric_policy(**fields: Any) -> MetricPolicy:
    """Derive a policy's fingerprint and construct it.

    Separate from the loader so a test can build one without a file, and so the
    fingerprint is computed in exactly one place.
    """
    fields = dict(fields)
    fields.setdefault("unit_of_analysis", UNIT_OF_ANALYSIS_COMPARISON)
    fields.setdefault("pooled_aggregation", POOLED_AGGREGATION_SUM_COUNTS)
    fields["metric_definitions"] = tuple(fields["metric_definitions"])
    fields.setdefault("metadata", {})

    probe = _PolicyProbe(**fields)
    fingerprint = metric_policy_fingerprint(probe)  # type: ignore[arg-type]
    return MetricPolicy(policy_fingerprint=fingerprint, **fields)


def build_report_profile(
    *, profile_id: str, release_order: tuple[str, ...]
) -> ReportProfile:
    """Compose a known report profile with this experiment's release order."""
    try:
        template = REPORT_PROFILE_TEMPLATES[profile_id]
    except KeyError:
        raise MetricPolicyError(
            f"report profile {profile_id!r} is not one this project defines; "
            f"expected one of {sorted(REPORT_PROFILE_TEMPLATES)}"
        ) from None

    fields = {
        "report_profile_id": profile_id,
        "percentage_decimal_places": template.percentage_decimal_places,
        "always_show_fraction": template.always_show_fraction,
        "include_pooled": template.include_pooled,
        "release_order": tuple(release_order),
        "language": template.language,
    }
    probe = _ReportProbe(**fields)
    fingerprint = report_profile_fingerprint(probe)  # type: ignore[arg-type]
    return ReportProfile(report_profile_fingerprint=fingerprint, **fields)


# ----------------------------------------------------------------- internals


class _PolicyProbe:
    """A stand-in with exactly the attributes the policy fingerprint reads.

    Building the real object first is impossible — it validates its own
    fingerprint — and giving :class:`MetricPolicy` a mutable escape hatch would
    be worse than this.
    """

    __slots__ = (
        "policy_id",
        "policy_version",
        "unit_of_analysis",
        "pooled_aggregation",
        "metric_definitions",
        "percentage_decimal_places",
        "always_show_fraction",
        "zero_format",
        "metadata",
    )

    def __init__(self, **fields: Any) -> None:
        for name in self.__slots__:
            setattr(self, name, fields.get(name))
        self.metric_definitions = tuple(self.metric_definitions or ())
        self.metadata = dict(self.metadata or {})


class _ReportProbe:
    """The attributes ``report_profile_fingerprint`` reads, and nothing else."""

    __slots__ = (
        "report_profile_id",
        "percentage_decimal_places",
        "always_show_fraction",
        "include_pooled",
        "release_order",
        "language",
    )

    def __init__(self, **fields: Any) -> None:
        for name in self.__slots__:
            setattr(self, name, fields.get(name))
        self.release_order = tuple(str(item).strip() for item in self.release_order)
        self.language = str(self.language).strip().lower()


def _section(document: Mapping[str, Any], key: str, path: Path) -> Mapping[str, Any]:
    value = document.get(key)
    if not isinstance(value, Mapping):
        raise MetricPolicyError(f"{path}: missing or malformed '{key}' section")
    return value


def _optional_section(document: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = document.get(key)
    return value if isinstance(value, Mapping) else {}


def _unknown_switches(document: Mapping[str, Any]) -> set[str]:
    """Flags in the metric sections that switch on nothing.

    A typo in a config file that silently computes one metric fewer is exactly
    the kind of failure this stage exists to make impossible, so an unrecognised
    switch is an error rather than a shrug.
    """
    known: dict[str, set[str]] = {}
    for section, subsection, key in CATALOGUE_SWITCHES.values():
        name = section if subsection is None else f"{section}.{subsection}"
        known.setdefault(name, set()).add(key)

    # Keys that configure rather than select, and are checked elsewhere.
    known.setdefault("eligibility", set()).update({"eligible_rate"})
    allowed_extra = {
        "mated_conditional": {"retain_exclusion_reasons"},
        "negative_sanity": {"label_as_fmr"},
    }

    unknown: set[str] = set()
    for section in ("self", "eligibility", "mated_unconditional", "mated_conditional", "negative_sanity"):
        block = _optional_section(document, section)
        for key, value in block.items():
            if isinstance(value, Mapping):
                name = f"{section}.{key}"
                for inner in value:
                    if inner not in known.get(name, set()):
                        unknown.add(f"{name}.{inner}")
                continue
            permitted = known.get(section, set()) | allowed_extra.get(section, set())
            if str(key) not in permitted:
                unknown.add(f"{section}.{key}")
    return unknown


def _flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "yes", "1"}:
        return True
    if text in {"false", "no", "0", ""}:
        return False
    raise MetricPolicyError(f"{value!r} is not a boolean flag")


def _render_flag(value: Any) -> str:
    return "true" if _flag(value) else "false"
