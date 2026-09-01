"""Render the final-baseline Markdown report from its published documents.

The renderer reads only the three evidence documents — never a live sweep —
so the committed report can be re-rendered from committed bytes and compared,
the same discipline the metric-set verifier applies to its own renderings.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any, Mapping

from fpbench.final_baseline.errors import FinalBaselineError
from fpbench.final_baseline.reporting import FinalBaselineReporting

__all__ = ["render_final_baseline_report"]

_GOVERNING_SENTENCE = (
    "This report states observed TAR, FAR and FRR at predeclared FAR targets, "
    "swept over each algorithm's own raw-score scale on identical planned "
    "pairs. It performs no calibration, selects no operational threshold, "
    "normalizes no score, compares no raw score across algorithms, and "
    "interpolates nothing."
)


def _percent(rate: Mapping[str, int]) -> str:
    numerator = int(rate["numerator"])
    denominator = int(rate["denominator"])
    value = 100 * Fraction(numerator, denominator)
    return f"{float(value):.4f}% ({numerator}/{denominator})"


def _cut(cell: Mapping[str, Any]) -> str:
    if cell["boundary_kind"] == "accept_none":
        return "accept none"
    comparator = {
        "greater_than_or_equal": "≥",
        "less_than_or_equal": "≤",
    }.get(str(cell["comparator"]), str(cell["comparator"]))
    return f"{comparator} {cell['score_cut']!r}"


def _method_label(method: Mapping[str, Any]) -> str:
    name = str(method["display_name"])
    if method["role"] == "additional_experimentally_evaluated_method":
        return f"{name} †"
    return name


def _target_heading(target: str, primary_target: str) -> str:
    suffix = " (primary)" if target == primary_target else ""
    return f"FAR target ≤ {target}{suffix}"


def _view_table(
    *,
    lines: list[str],
    scope: str,
    target: str,
    target_index: int,
    algorithm_order: list[str],
    per_algorithm: Mapping[str, Any],
    labels: Mapping[str, str],
) -> None:
    lines.append(f"#### {scope}")
    lines.append("")
    lines.append(
        "| Method | TAR | FRR | Observed FAR | Score cut (own scale) | "
        "Genuine scored/planned | Impostor scored/planned |"
    )
    lines.append("|---|---|---|---|---|---|---|")
    for algorithm_id in algorithm_order:
        entry = per_algorithm[algorithm_id]
        if "scopes" not in entry:
            lines.append(
                f"| {labels[algorithm_id]} | unavailable: {entry['unavailable']} "
                "| — | — | — | — | — |"
            )
            continue
        cell = entry["scopes"][scope]["far_targets"][target_index]
        operational = entry["scopes"][scope]["operational"]
        genuine = operational["genuine"]
        impostor = operational["impostor"]
        lines.append(
            "| {label} | {tar} | {frr} | {far} | {cut} | {gs}/{gp} | {ns}/{np} |".format(
                label=labels[algorithm_id],
                tar=_percent(cell["tar"]),
                frr=_percent(cell["frr"]),
                far=_percent(cell["far"]),
                cut=_cut(cell),
                gs=genuine["score_bearing_attempts"],
                gp=genuine["planned_attempts"],
                ns=impostor["score_bearing_attempts"],
                np=impostor["planned_attempts"],
            )
        )
    lines.append("")


def render_final_baseline_report(
    *,
    inputs_document: Mapping[str, Any],
    results_document: Mapping[str, Any],
    context_document: Mapping[str, Any],
    reporting: FinalBaselineReporting,
) -> str:
    methods = list(inputs_document["methods"])
    labels = {
        str(method["algorithm_id"]): _method_label(method) for method in methods
    }
    roster_order = [str(method["algorithm_id"]) for method in methods]
    scopes = [str(scope) for scope in results_document["scopes"]]
    targets = [str(target) for target in results_document["far_targets"]]
    primary_target = str(results_document["primary_far_target"])
    if set(scopes) != set(reporting.scopes):
        raise FinalBaselineError("results document scopes disagree with the report profile")

    lines: list[str] = []
    lines.append("# Final baseline comparison — TAR / FAR / FRR")
    lines.append("")
    lines.append(f"> {_GOVERNING_SENTENCE}")
    lines.append("")
    lines.append(f"- Comparison: `{results_document['comparison_id']}`")
    lines.append(f"- Roster: `{results_document['roster_id']}`")
    lines.append(f"- Report profile: `{results_document['report_id']}`")
    lines.append(
        "- Stage 21A finalization: "
        f"`{inputs_document['stage21a_finalization_fingerprint']}`"
    )
    lines.append(
        "- Stage 21B finalization: "
        f"`{inputs_document['stage21b_finalization_fingerprint']}`"
    )
    lines.append(
        f"- Genuine population: `{inputs_document['genuine_population']}` "
        "(legacy plain↔roll mated, 500 per release)"
    )
    lines.append(
        f"- Impostor population: `{inputs_document['impostor_population']}` "
        "(exhaustive cross-subject, 24,500 per release)"
    )
    lines.append("")
    lines.append(
        "† additional experimentally evaluated method (retained beyond the "
        "five primary baselines)."
    )
    lines.append("")

    lines.append("## How to read this report")
    lines.append("")
    lines.append(
        "- The reporting point is the highest observed TAR at or below each "
        "predeclared FAR target; equal scores move together and nothing is "
        "interpolated."
    )
    lines.append(
        "- A genuine algorithm failure is not accepted (it stays in the TAR/FRR "
        "denominator); an impostor failure is not a false accept (it stays in "
        "the FAR denominator)."
    )
    lines.append(
        "- A score cut is an observed reporting boundary on one algorithm's own "
        "scale. It is not an operating threshold, it is never reused by "
        "execution, and cuts are never compared across algorithms."
    )
    lines.append(f"- Ranking rule: {results_document['ranking_rule']}.")
    lines.append("")

    lines.append("## Primary view — all planned attempts")
    lines.append("")
    primary_view = results_document["views"]["primary_all_attempt"]
    rankings = results_document["rankings"]
    for target_index, target in enumerate(targets):
        lines.append(f"### {_target_heading(target, primary_target)}")
        lines.append("")
        for scope in scopes:
            _view_table(
                lines=lines,
                scope=scope,
                target=target,
                target_index=target_index,
                algorithm_order=list(rankings[scope][target]),
                per_algorithm=primary_view,
                labels=labels,
            )

    lines.append("## Secondary view — common-score population")
    lines.append("")
    membership = results_document["views"]["secondary_common_score_membership"]
    lines.append(
        f"Membership: {membership['definition']} — "
        f"{membership['genuine_pairs']} genuine and "
        f"{membership['impostor_pairs']} impostor pairs scored by every roster "
        "method. This view is secondary only; the all-attempt view above is the "
        "primary result."
    )
    lines.append("")
    secondary_view = results_document["views"]["secondary_common_score"]
    for target_index, target in enumerate(targets):
        lines.append(f"### {_target_heading(target, primary_target)}")
        lines.append("")
        for scope in scopes:
            _view_table(
                lines=lines,
                scope=scope,
                target=target,
                target_index=target_index,
                algorithm_order=roster_order,
                per_algorithm=secondary_view,
                labels=labels,
            )

    lines.append("## Context — native documented rules")
    lines.append("")
    lines.append(
        "Where an upstream author documents a decision rule, the observed "
        "outcome at that rule is shown for context. These operating points were "
        "chosen by different documents on different scales; ranking algorithms "
        "against each other on this table is forbidden."
    )
    lines.append("")
    lines.append("| Method | Documented rule | Scope | TAR | FRR | Observed FAR |")
    lines.append("|---|---|---|---|---|---|")
    context_methods = context_document["methods"]
    for algorithm_id in roster_order:
        entry = context_methods[algorithm_id]
        if entry["scopes"] is None:
            lines.append(
                f"| {labels[algorithm_id]} | {entry['rule']} | — | — | "
                "— | — |"
            )
            continue
        for scope in scopes:
            cell = entry["scopes"][scope]
            lines.append(
                "| {label} | {rule} | {scope} | {tar} | {frr} | {far} |".format(
                    label=labels[algorithm_id],
                    rule=entry["rule"],
                    scope=scope,
                    tar=_percent(cell["tar"]),
                    frr=_percent(cell["frr"]),
                    far=_percent(cell["far"]),
                )
            )
    lines.append("")

    lines.append("## Disclosures")
    lines.append("")
    lines.append(f"- {reporting.release_dependence_disclosure}")
    lines.append(
        "- Pooled rows sum numerators and denominators across the three "
        "releases; they are a descriptive summary, not an average of release "
        "rates and not a fourth independent experiment."
    )
    lines.append(
        f"- The legacy negative population (“{reporting.legacy_negative_label}”) "
        "is not used as a FAR denominator anywhere in this report."
    )
    lines.append(
        "- SELF comparisons are diagnostic only; no eligibility filtering is "
        "applied to any population in this report."
    )
    lines.append(
        "- No calibration was performed, no operational threshold was created, "
        "no score was normalized, and no raw score was compared across "
        "algorithms in producing this report."
    )
    lines.append("")
    return "\n".join(lines)
