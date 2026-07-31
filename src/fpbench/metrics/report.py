"""Rendering verified numbers as English prose and tables.

This module computes nothing. Every integer it prints was already in a count
record or an observation, and the only arithmetic it performs is turning two
integers into a display percentage — which is why that percentage is always
printed *beside* the fraction rather than instead of it. If a number is not in
the metric set, it does not appear in the report (spec section 66).

Most of the code here is about the two ways a report of this kind lies.

**By rounding.** ``0.6%`` is not checkable and ``2/333`` is. So every rate is
written ``numerator/denominator (percentage%)``, and a metric with nothing to
divide by is written ``undefined (0 included decided attempts)`` rather than
``0.0000%`` — because zero per cent is a measurement and "nothing was measured"
is not (spec sections 51, 26).

**By vocabulary.** A closed-set, same-subject, one-shift impostor check is not a
false-match rate; a conditional result over a filtered population is not an
improvement; a documented threshold is not a calibrated one. The report says all
three explicitly, in sections nobody has to scroll past, and the phrasing for the
sanity check is fixed by specification rather than left to whoever writes the next
one (docs/adr/0029, docs/adr/0030).

The report carries no timestamp. Two runs of ``finalize`` over the same verified
metric set must produce byte-identical Markdown, because the finalization marker
binds its content hash (spec section 68).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from fpbench.core.errors import EvaluationReportError
from fpbench.core.evaluation_models import POOLED_SCOPE_LABEL
from fpbench.core.metric_models import (
    CountFamily,
    EvaluationCountRecord,
    MetricDenominator,
    MetricObservation,
    MetricPolicy,
    MetricSetManifest,
    ReportProfile,
    render_percentage,
)

__all__ = ["ReportContext", "render_report", "DENOMINATOR_PHRASES"]

#: What a zero denominator is called in the report, per denominator. Spelling
#: this out is the difference between "undefined" (unhelpful) and "undefined
#: (0 included decided attempts)" (an explanation).
DENOMINATOR_PHRASES: Mapping[MetricDenominator, str] = {
    MetricDenominator.ALL_ATTEMPTS: "attempts",
    MetricDenominator.DECIDED_ATTEMPTS: "decided attempts",
    MetricDenominator.ALL_ELIGIBILITY_UNITS: "eligibility units",
    MetricDenominator.INCLUDED_CONDITIONAL_ATTEMPTS: "included attempts",
    MetricDenominator.DECIDED_CONDITIONAL_ATTEMPTS: "included decided attempts",
}


@dataclass(frozen=True, slots=True)
class ReportContext:
    """The identity a table of numbers cannot supply.

    Every field is an identifier, a version or a fingerprint. Deliberately no
    paths: where a workspace happens to sit says nothing about the experiment and
    would be the one line in the report that differs between two machines
    (spec section 50).
    """

    algorithm_id: str
    implementation_version: str
    adapter_id: str
    integration_mode: str
    execution_profile_id: str
    resolution_mode: str

    decision_profile_id: str
    threshold: str
    comparator: str
    threshold_origin: str

    run_id: str
    result_set_id: str
    decision_set_id: str
    eligibility_set_id: str
    metric_set_id: str

    run_source_commit: str
    decision_derivation_source_commit: str
    metric_derivation_source_commit: str

    negative_sanity_metadata: Mapping[str, str]


def render_report(
    *,
    context: ReportContext,
    manifest: MetricSetManifest,
    policy: MetricPolicy,
    report_profile: ReportProfile,
    counts: Sequence[EvaluationCountRecord],
    observations: Sequence[MetricObservation],
) -> str:
    """Render the whole report from verified counts and observations."""
    releases = tuple(report_profile.release_order)
    scopes = _scope_labels(releases, report_profile.include_pooled)
    by_count = _index_counts(counts)
    by_observation = _index_observations(observations)

    sections = [
        _title(context, manifest, report_profile),
        _identity_section(context),
        _protocol_section(context),
        _limitations_section(context),
        _self_section(
            policy, report_profile, by_count, by_observation, scopes
        ),
        _eligibility_section(
            policy, report_profile, by_count, by_observation, scopes
        ),
        _unconditional_section(
            policy, report_profile, by_count, by_observation, scopes
        ),
        _conditional_section(
            policy, report_profile, by_count, by_observation, scopes
        ),
        _sanity_section(
            context, policy, report_profile, by_count, by_observation, scopes
        ),
        _operational_section(report_profile, by_count, scopes),
        _not_established_section(),
    ]
    return "\n".join(section.rstrip() + "\n" for section in sections if section)


# ------------------------------------------------------------------- sections


def _title(
    context: ReportContext, manifest: MetricSetManifest, profile: ReportProfile
) -> str:
    return (
        f"# Observed biometric results under decision profile "
        f"`{context.decision_profile_id}`\n"
        f"\n"
        f"Metric set `{manifest.metric_set_id}`.\n"
        f"\n"
        f"Every rate below is published as its exact numerator and denominator. "
        f"The percentage beside a fraction is a rendering of those two integers, "
        f"rounded to {profile.percentage_decimal_places} decimal places for "
        f"reading; the integers are the result.\n"
    )


def _identity_section(context: ReportContext) -> str:
    rows = [
        ("Algorithm", f"`{context.algorithm_id}`"),
        ("Implementation version", f"`{context.implementation_version}`"),
        ("Adapter", f"`{context.adapter_id}`"),
        ("Integration mode", f"`{context.integration_mode}`"),
        ("Execution profile", f"`{context.execution_profile_id}`"),
        ("Resolution", f"`{context.resolution_mode}`"),
        ("Decision profile", f"`{context.decision_profile_id}`"),
        (
            "Threshold",
            f"`{context.threshold}` ({context.comparator}, "
            f"origin `{context.threshold_origin}`)",
        ),
        ("Run", f"`{context.run_id}`"),
        ("Result set", f"`{context.result_set_id}`"),
        ("Decision set", f"`{context.decision_set_id}`"),
        ("Eligibility set", f"`{context.eligibility_set_id}`"),
        ("Metric set", f"`{context.metric_set_id}`"),
        ("Run source commit", f"`{context.run_source_commit}`"),
        (
            "Decision derivation commit",
            f"`{context.decision_derivation_source_commit}`",
        ),
        ("Metric derivation commit", f"`{context.metric_derivation_source_commit}`"),
    ]
    body = "\n".join(f"| {name} | {value} |" for name, value in rows)
    return (
        "## 1. Evaluation identity\n"
        "\n"
        "| Field | Value |\n"
        "| --- | --- |\n"
        f"{body}\n"
    )


def _protocol_section(context: ReportContext) -> str:
    return (
        "## 2. Protocol and threshold\n"
        "\n"
        "Each release contributes, per subject and finger, one PLAIN SELF "
        "comparison, one ROLL SELF comparison, one mated PLAIN–ROLL comparison "
        "and one same-subject different-finger comparison at a fixed cyclic finger "
        "shift.\n"
        "\n"
        f"A comparison is a MATCH when its score satisfies `{context.comparator}` "
        f"against threshold `{context.threshold}`. That threshold has origin "
        f"`{context.threshold_origin}`: it is a number the algorithm's own authors "
        "published, applied here unchanged. **It was not calibrated on this data, "
        "and no other threshold was tried.**\n"
        "\n"
        "A comparison that produced no score at all is `UNDECIDABLE`. It is never "
        "counted as a non-match. Every population below is therefore reported "
        "twice: once over the comparisons that produced a score, and once over "
        "every comparison attempted.\n"
    )


def _limitations_section(context: ReportContext) -> str:
    sanity = context.negative_sanity_metadata
    return (
        "## 3. Important limitations\n"
        "\n"
        "* The threshold is **documented, not calibrated**. Nothing here says it "
        "is the right one, and no search over thresholds was performed.\n"
        "* The cohort is closed: a fixed set of subjects, chosen once. Every "
        "number is an observation about this cohort, not an estimate of a "
        "population.\n"
        "* No confidence interval, standard error or significance test is "
        "reported, because the design was not chosen for estimation.\n"
        "* The negative set is "
        f"`{sanity.get('negative_kind', 'same_subject_different_finger')}` paired "
        f"by `{sanity.get('pairing_strategy', 'cyclic_finger_shift')}`, over a "
        "closed set. It is a sanity check. It is **not** a general false-match "
        "rate and cannot be converted into one by dividing.\n"
        "* Conditional results below cover a filtered population. They are "
        "published only together with the fraction of rows that filter kept.\n"
        "* Releases are reported separately and pooled. Pooled values sum the "
        "release counts and divide once; they are not averages of the release "
        "percentages.\n"
    )


def _self_section(
    policy: MetricPolicy,
    profile: ReportProfile,
    by_count,
    by_observation,
    scopes: tuple[str, ...],
) -> str:
    plain = _decision_table(
        family=CountFamily.PLAIN_SELF,
        decided_metric="plain_self_match_rate_decided",
        attempt_metric="plain_self_match_rate_attempt",
        decided_header="Decided match rate",
        attempt_header="Attempt match rate",
        policy=policy,
        profile=profile,
        by_count=by_count,
        by_observation=by_observation,
        scopes=scopes,
    )
    roll = _decision_table(
        family=CountFamily.ROLL_SELF,
        decided_metric="roll_self_match_rate_decided",
        attempt_metric="roll_self_match_rate_attempt",
        decided_header="Decided match rate",
        attempt_header="Attempt match rate",
        policy=policy,
        profile=profile,
        by_count=by_count,
        by_observation=by_observation,
        scopes=scopes,
    )
    return (
        "## 4. SELF results\n"
        "\n"
        "A SELF comparison compares an image with itself, through two independent "
        "template extractions. It measures whether the pipeline can recognise a "
        "print as itself, which is a precondition for reading anything into a "
        "cross-impression result.\n"
        "\n"
        "### 4.1 PLAIN SELF\n"
        "\n"
        f"{plain}\n"
        "### 4.2 ROLL SELF\n"
        "\n"
        f"{roll}"
    )


def _eligibility_section(
    policy: MetricPolicy,
    profile: ReportProfile,
    by_count,
    by_observation,
    scopes: tuple[str, ...],
) -> str:
    header = (
        "| Release | Units | Eligible | Ineligible | Undetermined | "
        "Eligibility rate |\n"
        "| --- | ---: | ---: | ---: | ---: | ---: |"
    )
    rows = []
    for label in scopes:
        record = _count(by_count, CountFamily.SELF_ELIGIBILITY, label)
        rate = _rate(
            by_observation, policy, profile, "self_eligibility_rate", label
        )
        rows.append(
            f"| {label} | {record.total_count} | {record.get('eligible')} | "
            f"{record.get('ineligible')} | {record.get('undetermined')} | {rate} |"
        )
    table = header + "\n" + "\n".join(rows)
    return (
        "## 5. SELF eligibility\n"
        "\n"
        "A unit is one release, one subject, one finger. It is **eligible** when "
        "both of its SELF comparisons matched, **ineligible** when one of them "
        "returned a non-match, and **undetermined** when one of them produced no "
        "score. The third category is not a kind of failure: it records that "
        "nothing was measured.\n"
        "\n"
        f"{table}\n"
    )


def _unconditional_section(
    policy: MetricPolicy,
    profile: ReportProfile,
    by_count,
    by_observation,
    scopes: tuple[str, ...],
) -> str:
    table = _decision_table(
        family=CountFamily.MATED_UNCONDITIONAL,
        decided_metric="plain_roll_mated_unconditional_fnmr_decided",
        attempt_metric="plain_roll_mated_unconditional_non_success_rate_attempt",
        decided_header="Decision FNMR",
        attempt_header="Attempt non-success rate",
        policy=policy,
        profile=profile,
        by_count=by_count,
        by_observation=by_observation,
        scopes=scopes,
    )
    return (
        "## 6. Unconditional PLAIN–ROLL genuine results\n"
        "\n"
        "Every mated PLAIN–ROLL comparison, with nothing excluded.\n"
        "\n"
        "**Decision FNMR** is mated non-matches over mated comparisons that "
        "produced a score. **Attempt non-success rate** is mated non-matches *plus* "
        "comparisons that produced no score, over every attempt. The two answer "
        "different questions and are never combined.\n"
        "\n"
        f"{table}"
    )


def _conditional_section(
    policy: MetricPolicy,
    profile: ReportProfile,
    by_count,
    by_observation,
    scopes: tuple[str, ...],
) -> str:
    header = (
        "| Release | Total rows | Included | Excluded: ineligible | "
        "Excluded: undetermined | Included MATCH | Included NON_MATCH | "
        "Included UNDECIDABLE | Selection rate | Conditional decision FNMR | "
        "Conditional attempt non-success rate |\n"
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | "
        "---: |"
    )
    rows = []
    for label in scopes:
        record = _count(by_count, CountFamily.MATED_CONDITIONAL, label)
        selection = _rate(
            by_observation,
            policy,
            profile,
            "plain_roll_mated_conditional_selection_rate",
            label,
        )
        fnmr = _rate(
            by_observation,
            policy,
            profile,
            "plain_roll_mated_conditional_fnmr_decided",
            label,
        )
        non_success = _rate(
            by_observation,
            policy,
            profile,
            "plain_roll_mated_conditional_non_success_rate_attempt",
            label,
        )
        rows.append(
            f"| {label} | {record.total_count} | {record.get('included')} | "
            f"{record.get('excluded_ineligible')} | "
            f"{record.get('excluded_undetermined')} | "
            f"{record.get('included_match')} | {record.get('included_non_match')} | "
            f"{record.get('included_undecidable')} | {selection} | {fnmr} | "
            f"{non_success} |"
        )
    table = header + "\n" + "\n".join(rows)
    return (
        "## 7. SELF-conditional PLAIN–ROLL genuine results\n"
        "\n"
        "The same mated comparisons, counted only where the finger passed both "
        "SELF tests. Excluded rows stay in **Total rows** and are accounted for by "
        "the two exclusion columns; they are not in any conditional denominator.\n"
        "\n"
        "The selection rate is part of the result, not context for it. A "
        "conditional rate over a different population is a different measurement "
        "from the unconditional one above — not the same measurement improved.\n"
        "\n"
        f"{table}\n"
    )


def _sanity_section(
    context: ReportContext,
    policy: MetricPolicy,
    profile: ReportProfile,
    by_count,
    by_observation,
    scopes: tuple[str, ...],
) -> str:
    header = (
        "| Release | Attempts | MATCH | NON_MATCH | UNDECIDABLE | "
        "Observed decided match fraction | Observed attempt match fraction |\n"
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"
    )
    rows = []
    for label in scopes:
        record = _count(by_count, CountFamily.NEGATIVE_SANITY, label)
        decided = _rate(
            by_observation,
            policy,
            profile,
            "plain_roll_non_mated_sanity_match_rate_decided",
            label,
        )
        attempt = _rate(
            by_observation,
            policy,
            profile,
            "plain_roll_non_mated_sanity_match_rate_attempt",
            label,
        )
        rows.append(
            f"| {label} | {record.total_count} | {record.get('match')} | "
            f"{record.get('non_match')} | {record.get('undecidable')} | {decided} | "
            f"{attempt} |"
        )
    table = header + "\n" + "\n".join(rows)

    statement_scope = POOLED_SCOPE_LABEL if POOLED_SCOPE_LABEL in scopes else scopes[-1]
    pooled = _count(by_count, CountFamily.NEGATIVE_SANITY, statement_scope)
    matches = pooled.get("match")
    total = pooled.total_count
    if matches == 0:
        statement = (
            f"Observed {matches}/{total} matching decisions in this sanity set."
        )
    else:
        statement = (
            "Observed matches in the closed-set same-subject different-finger "
            f"negative sanity check: {matches}/{total}."
        )

    sanity = context.negative_sanity_metadata
    return (
        "## 8. Same-subject different-finger negative sanity check\n"
        "\n"
        f"{statement}\n"
        "\n"
        f"{table}\n"
        "\n"
        "This set compares two *different* fingers of the *same* subject, paired "
        f"by `{sanity.get('pairing_strategy', 'cyclic_finger_shift')}` over a "
        "closed cohort. It exists to catch a matcher that fires on obviously "
        "different fingers, and a non-zero count here is a reason to investigate "
        "the integration.\n"
        "\n"
        "It is not an impostor experiment: the set is closed, both sides come from "
        "one person, and only one pairing was used. **This is not a general "
        "false-match rate estimate, and the fraction above must not be presented "
        "as one.** A rate over impostors would need a negative-pair design chosen "
        "for estimation, which is a different pair manifest and a different run.\n"
    )


def _operational_section(
    profile: ReportProfile, by_count, scopes: tuple[str, ...]
) -> str:
    header = (
        "| Population | Release | Attempts | Undecidable |\n"
        "| --- | --- | ---: | ---: |"
    )
    rows = []
    for family, name in (
        (CountFamily.PLAIN_SELF, "PLAIN SELF"),
        (CountFamily.ROLL_SELF, "ROLL SELF"),
        (CountFamily.MATED_UNCONDITIONAL, "Mated (unconditional)"),
        (CountFamily.NEGATIVE_SANITY, "Negative sanity"),
    ):
        for label in scopes:
            record = _count(by_count, family, label)
            rows.append(
                f"| {name} | {label} | {record.total_count} | "
                f"{record.get('undecidable')} |"
            )
    conditional_rows = []
    for label in scopes:
        record = _count(by_count, CountFamily.MATED_CONDITIONAL, label)
        conditional_rows.append(
            f"| Mated (SELF-conditional, included only) | {label} | "
            f"{record.get('included')} | {record.get('included_undecidable')} |"
        )
    table = header + "\n" + "\n".join(rows + conditional_rows)
    return (
        "## 9. Operational and failure accounting\n"
        "\n"
        "A comparison that produced no score is `UNDECIDABLE`. It is not a "
        "non-match and never enters a decided denominator. Where these counts are "
        "zero, the decided and attempt rates above coincide numerically; they "
        "remain separate metrics, because the day one of them is non-zero a single "
        "blended number would move for reasons nobody could name.\n"
        "\n"
        f"{table}\n"
    )


def _not_established_section() -> str:
    return (
        "## 10. What these results do not establish\n"
        "\n"
        "* **Not a calibrated threshold.** No threshold was chosen, searched for "
        "or optimised here. No ROC curve, DET curve or equal-error rate was "
        "computed.\n"
        "* **Not a general false-match rate.** The only non-mated comparisons in "
        "this evaluation are same-subject, different-finger, closed-set and "
        "cyclically paired.\n"
        "* **Not a statistical comparison between releases.** The per-release "
        "values are reported side by side and nothing is claimed about the "
        "difference between them. No significance test was performed and none "
        "would be valid on this design.\n"
        "* **Not a resolution finding.** Nothing here says one capture resolution "
        "performs better than another; the releases differ in more than "
        "resolution.\n"
        "* **Not a comparison between algorithms.** One matcher, one build, one "
        "documented threshold.\n"
        "* **Not an estimate with an interval.** No confidence interval, bootstrap "
        "or hypothesis test is reported.\n"
    )


# ----------------------------------------------------------------- formatting


def _decision_table(
    *,
    family: str,
    decided_metric: str,
    attempt_metric: str,
    decided_header: str,
    attempt_header: str,
    policy: MetricPolicy,
    profile: ReportProfile,
    by_count,
    by_observation,
    scopes: tuple[str, ...],
) -> str:
    header = (
        f"| Release | Attempts | MATCH | NON_MATCH | UNDECIDABLE | "
        f"{decided_header} | {attempt_header} |\n"
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"
    )
    rows = []
    for label in scopes:
        record = _count(by_count, family, label)
        decided = _rate(by_observation, policy, profile, decided_metric, label)
        attempt = _rate(by_observation, policy, profile, attempt_metric, label)
        rows.append(
            f"| {label} | {record.total_count} | {record.get('match')} | "
            f"{record.get('non_match')} | {record.get('undecidable')} | {decided} | "
            f"{attempt} |"
        )
    return header + "\n" + "\n".join(rows) + "\n"


def _rate(
    by_observation,
    policy: MetricPolicy,
    profile: ReportProfile,
    metric_id: str,
    scope_label: str,
) -> str:
    """``numerator/denominator (percentage%)``, or an explicit ``undefined``."""
    observation = by_observation.get((metric_id, scope_label))
    if observation is None:
        raise EvaluationReportError(
            f"the report needs metric {metric_id!r} at {scope_label!r}, which the "
            "metric set does not hold. A report is rendered from verified "
            "observations, never computed while formatting"
        )
    if not observation.is_defined:
        denominator = policy.definition(metric_id).denominator
        phrase = DENOMINATOR_PHRASES[denominator]
        return f"undefined (0 {phrase})"

    percentage = render_percentage(
        observation.numerator_count,
        observation.denominator_count,
        decimal_places=profile.percentage_decimal_places,
    )
    if not profile.always_show_fraction:  # pragma: no cover - no such profile yet
        return f"{percentage}%"
    return f"{observation.fraction_text} ({percentage}%)"


def _scope_labels(releases: tuple[str, ...], include_pooled: bool) -> tuple[str, ...]:
    labels = list(releases)
    if include_pooled:
        labels.append(POOLED_SCOPE_LABEL)
    return tuple(labels)


def _index_counts(
    counts: Sequence[EvaluationCountRecord],
) -> Mapping[tuple[str, str], EvaluationCountRecord]:
    return {
        (record.count_family, record.scope.label): record for record in counts
    }


def _index_observations(
    observations: Sequence[MetricObservation],
) -> Mapping[tuple[str, str], MetricObservation]:
    return {
        (observation.metric_id, observation.scope.label): observation
        for observation in observations
    }


def _count(by_count, family: str, scope_label: str) -> EvaluationCountRecord:
    record = by_count.get((family, scope_label))
    if record is None:
        raise EvaluationReportError(
            f"the report needs {family} counts at {scope_label!r}, which the metric "
            "set does not hold"
        )
    return record
