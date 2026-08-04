"""Rendering a comparison so that its limits are as visible as its numbers.

The report is the artefact somebody will read on its own, print, paste into a
chapter and quote from. Every design choice here is about what a reader can
conclude from it *without* the rest of the repository.

The population hierarchy is fixed and is the order of the sections
(spec section 58):

    A. the full mated population — all 1,500 attempts, the primary analysis;
    B. eligibility and exclusions — 1,500 units, both sides;
    C. common eligible — the intersection, a secondary analysis;
    D. each side's own conditional set — descriptive only when they differ.

Every rate is printed as ``numerator / denominator`` beside its percentage,
because a percentage alone cannot be checked and cannot be pooled. A difference
is printed only where the populations permit one, and where they do not the cell
says why rather than being left blank (spec sections 61 and 62).

The refusal to conclude is printed verbatim, at the top and at the bottom.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Mapping, Sequence

from fpbench.core.cross_algorithm_models import (
    NO_SUPERIORITY_STATEMENT,
    OPERATING_POINT_RELATION,
    CrossAlgorithmCommonEligibleEntry,
    CrossAlgorithmCountRecord,
    CrossAlgorithmEligibilityTransition,
    CrossAlgorithmEvaluationDefinition,
    CrossAlgorithmEvaluationManifest,
    CrossAlgorithmObservation,
    FairComparabilityAudit,
)
from fpbench.core.enums import (
    CrossAlgorithmPopulation,
    CrossAlgorithmTransitionFamily,
    DecisionOutcome,
    SelfEligibilityStatus,
)
from fpbench.core.serialization import stable_hash
from fpbench.cross_algorithm.derive import POOLED_SCOPE, PRIMARY_METRIC_ID

__all__ = ["render_report", "report_content_hash"]

_DECIMALS = 4

#: What each metric is called in prose, and — where it matters — what it is
#: deliberately *not* called. The negative-sanity entries carry their disclaimer
#: in the label itself, because a table row is exactly where the word "FMR"
#: would otherwise appear (docs/adr/0030).
_LABELS: Mapping[str, str] = {
    "plain_self_match_rate_attempt": "PLAIN SELF match rate (all attempts)",
    "plain_self_match_rate_decided": "PLAIN SELF match rate (decided only)",
    "roll_self_match_rate_attempt": "ROLL SELF match rate (all attempts)",
    "roll_self_match_rate_decided": "ROLL SELF match rate (decided only)",
    "plain_roll_mated_unconditional_non_success_rate_attempt": (
        "mated non-success rate (all 1,500 attempts) - PRIMARY"
    ),
    "plain_roll_mated_unconditional_fnmr_decided": (
        "mated FNMR (decided attempts only)"
    ),
    "plain_roll_mated_conditional_selection_rate": (
        "eligible units selected (of all units)"
    ),
    "plain_roll_mated_conditional_fnmr_decided": (
        "conditional FNMR over each side's own eligible set"
    ),
    "plain_roll_mated_conditional_non_success_rate_attempt": (
        "conditional non-success rate over each side's own eligible set"
    ),
    "plain_roll_mated_common_eligible_non_success_rate_attempt": (
        "non-success rate over the common eligible set"
    ),
    "plain_roll_mated_common_eligible_fnmr_decided": (
        "FNMR over the common eligible set (decided only)"
    ),
    "plain_roll_non_mated_sanity_match_rate_attempt": (
        "same-subject sanity match rate (all attempts) - NOT an FMR"
    ),
    "plain_roll_non_mated_sanity_match_rate_decided": (
        "same-subject sanity match rate (decided only) - NOT an FMR"
    ),
}

#: Why a difference is absent, in the reader's language rather than the model's.
_POPULATION_NOTE: Mapping[CrossAlgorithmPopulation, str] = {
    CrossAlgorithmPopulation.SAME_POPULATION: "same population",
    CrossAlgorithmPopulation.DIFFERENT_DECIDED_POPULATIONS: (
        "different decided populations - difference undefined"
    ),
    CrossAlgorithmPopulation.DIFFERENT_ELIGIBLE_POPULATIONS: (
        "different eligible populations - difference undefined"
    ),
    CrossAlgorithmPopulation.COMMON_ELIGIBLE_POPULATION: (
        "common eligible set - one denominator, both sides"
    ),
    CrossAlgorithmPopulation.DESCRIPTIVE_ONLY: "descriptive only",
    CrossAlgorithmPopulation.NOT_COMPARABLE: "not comparable",
}

_FAMILY_TITLES: Mapping[CrossAlgorithmTransitionFamily, str] = {
    CrossAlgorithmTransitionFamily.PLAIN_SELF: "PLAIN SELF",
    CrossAlgorithmTransitionFamily.ROLL_SELF: "ROLL SELF",
    CrossAlgorithmTransitionFamily.MATED_UNCONDITIONAL: (
        "mated PLAIN-ROLL, all attempts"
    ),
    CrossAlgorithmTransitionFamily.MATED_COMMON_ELIGIBLE: (
        "mated PLAIN-ROLL, common eligible only"
    ),
    CrossAlgorithmTransitionFamily.NEGATIVE_SANITY: (
        "same-subject different-finger sanity set"
    ),
}


def _percent(numerator: int, denominator: int) -> str:
    if denominator <= 0:
        return "undefined"
    value = Decimal(numerator) * 100 / Decimal(denominator)
    return f"{value:.{_DECIMALS}f}%"


def _fraction(numerator: int, denominator: int) -> str:
    return f"{numerator}/{denominator}"


def _difference_cell(observation: CrossAlgorithmObservation) -> str:
    note = _POPULATION_NOTE[observation.population]
    if observation.difference_numerator is None:
        return f"- ({note})"
    numerator = int(observation.difference_numerator)
    denominator = int(observation.difference_denominator)
    percent = Decimal(numerator) * 100 / Decimal(denominator)
    sign = "+" if percent >= 0 else ""
    return f"{numerator}/{denominator} = {sign}{percent:.{_DECIMALS}f} pp"


def render_report(
    *,
    definition: CrossAlgorithmEvaluationDefinition,
    manifest: CrossAlgorithmEvaluationManifest,
    audit: FairComparabilityAudit,
    observations: Sequence[CrossAlgorithmObservation],
    counts: Sequence[CrossAlgorithmCountRecord],
    transitions: Sequence[CrossAlgorithmEligibilityTransition],
    common_eligible: Sequence[CrossAlgorithmCommonEligibleEntry],
    releases: Sequence[str],
) -> str:
    """Render the whole comparison as Markdown, deterministically."""
    left = definition.left_label
    right = definition.right_label
    lines: list[str] = []
    add = lines.append

    add(f"# {left} and {right} at their documented operating points")
    add("")
    add(f"> {NO_SUPERIORITY_STATEMENT}")
    add("")
    add(f"- comparison: `{manifest.evaluation_id}`")
    add(f"- protocol: `{definition.protocol_id}` (`{definition.protocol_fingerprint[:12]}...`)")
    add(f"- operating-point relation: `{OPERATING_POINT_RELATION}`")
    add(f"- left = `{left}`, right = `{right}`; every difference is right minus left")
    add(f"- alignment: `{definition.alignment_fingerprint[:12]}...` (stage 7C, re-verified)")
    add(f"- pairs: `{definition.pair_manifest_hash[:12]}...`, {manifest.total_records} compared")
    add(f"- fair-comparability audit: `{audit.audit_fingerprint[:12]}...`, "
        f"{'clean' if audit.is_clean else 'NOT CLEAN'}")
    add("")

    add("## The two operating points")
    add("")
    add("| side | algorithm | rule | origin |")
    add("| --- | --- | --- | --- |")
    add(f"| left | `{left}` | documented | `{audit.left_profile_origin}` |")
    add(f"| right | `{right}` | documented | `{audit.right_profile_origin}` |")
    add("")
    add(
        "Both thresholds are written `40`. They come from two documents about two "
        "score scales and are not the same operating point; no claim of equal "
        "false-match rate, equal security level or equivalent threshold is made "
        "or implied."
    )
    add("")

    add("## A. Full mated population - the primary analysis")
    add("")
    add(
        "All 1,500 mated PLAIN-ROLL attempts, the same denominator on both sides, "
        "nothing filtered. `NON_MATCH` and `UNDECIDABLE` are both counted as "
        "non-successes."
    )
    add("")
    _add_metric_table(
        add,
        observations,
        left=left,
        right=right,
        metrics=(
            PRIMARY_METRIC_ID,
            "plain_roll_mated_unconditional_fnmr_decided",
        ),
        releases=releases,
    )

    add("## B. Eligibility and exclusions")
    add("")
    add(f"{len(transitions)} eligibility units, one per release, subject and finger.")
    add("")
    _add_eligibility_matrix(add, counts, left=left, right=right, releases=releases)
    _add_metric_table(
        add,
        observations,
        left=left,
        right=right,
        metrics=("plain_roll_mated_conditional_selection_rate",),
        releases=releases,
    )

    add("## C. Common eligible - a controlled secondary analysis")
    add("")
    add(
        f"{len(common_eligible)} units are ELIGIBLE on both sides. This set filters "
        "out exactly the units that were hard for either algorithm, so it answers "
        "a narrower question than section A: when both algorithms have shown that "
        "a finger's plain and rolled impressions match themselves, how did the "
        "plain-to-rolled decisions differ? It is not the primary result."
    )
    add("")
    _add_metric_table(
        add,
        observations,
        left=left,
        right=right,
        metrics=(
            "plain_roll_mated_common_eligible_non_success_rate_attempt",
            "plain_roll_mated_common_eligible_fnmr_decided",
        ),
        releases=releases,
    )

    add("## D. Each side's own conditional set - descriptive only")
    add("")
    add(
        "Each algorithm's conditional rates over *its own* eligible set. Where the "
        "two eligible sets differ these are two measurements over two populations "
        "and their difference is undefined; the table says so rather than "
        "subtracting them."
    )
    add("")
    _add_metric_table(
        add,
        observations,
        left=left,
        right=right,
        metrics=(
            "plain_roll_mated_conditional_non_success_rate_attempt",
            "plain_roll_mated_conditional_fnmr_decided",
        ),
        releases=releases,
    )

    add("## SELF comparisons")
    add("")
    add(
        "PLAIN and ROLL are reported separately. The all-attempt denominator is "
        "1,500 on both sides and is directly comparable; the decided-only rates "
        "are comparable only where both sides decided the same attempts."
    )
    add("")
    _add_metric_table(
        add,
        observations,
        left=left,
        right=right,
        metrics=(
            "plain_self_match_rate_attempt",
            "plain_self_match_rate_decided",
            "roll_self_match_rate_attempt",
            "roll_self_match_rate_decided",
        ),
        releases=releases,
    )

    add("## Negative sanity set - not a false-match rate")
    add("")
    add(
        "The same 1,500 same-subject, different-finger pairs on both sides, built "
        "by one fixed cyclic pairing. It is a closed set chosen for sanity rather "
        "than for estimation: it is not an FMR, not a false-match-rate estimate, "
        "and not a statement about impostor population performance."
    )
    add("")
    _add_metric_table(
        add,
        observations,
        left=left,
        right=right,
        metrics=(
            "plain_roll_non_mated_sanity_match_rate_attempt",
            "plain_roll_non_mated_sanity_match_rate_decided",
        ),
        releases=releases,
    )

    add("## Decision transition matrices")
    add("")
    add(
        "Every matrix carries all nine cells, including the zeros. Rows are the "
        f"`{left}` outcome, columns the `{right}` outcome."
    )
    add("")
    for family in CrossAlgorithmTransitionFamily:
        _add_transition_matrix(add, counts, family=family, left=left, right=right)

    add("## What this comparison does not establish")
    add("")
    add(NO_SUPERIORITY_STATEMENT)
    add("")
    add(
        "No threshold was calibrated. No SD300 score was read in order to choose "
        "one. No raw score was compared, normalised, subtracted or correlated "
        "across the two algorithms. No confidence interval and no significance "
        "test was computed."
    )
    add("")
    return "\n".join(lines) + "\n"


def _add_metric_table(
    add,
    observations: Sequence[CrossAlgorithmObservation],
    *,
    left: str,
    right: str,
    metrics: Sequence[str],
    releases: Sequence[str],
) -> None:
    scopes = tuple(releases) + (POOLED_SCOPE,)
    by_key = {
        (observation.metric_id, observation.scope): observation
        for observation in observations
    }
    add(f"| metric | scope | {left} | {right} | right - left |")
    add("| --- | --- | --- | --- | --- |")
    for metric in metrics:
        for scope in scopes:
            observation = by_key.get((metric, scope))
            if observation is None:
                continue
            add(
                f"| {_LABELS.get(metric, metric)} | {scope} "
                f"| {_fraction(observation.left_numerator, observation.left_denominator)} "
                f"= {_percent(observation.left_numerator, observation.left_denominator)} "
                f"| {_fraction(observation.right_numerator, observation.right_denominator)} "
                f"= {_percent(observation.right_numerator, observation.right_denominator)} "
                f"| {_difference_cell(observation)} |"
            )
    add("")


def _add_transition_matrix(
    add,
    counts: Sequence[CrossAlgorithmCountRecord],
    *,
    family: CrossAlgorithmTransitionFamily,
    left: str,
    right: str,
) -> None:
    cells = {
        (record.left_outcome, record.right_outcome): record.count
        for record in counts
        if record.family is family
        and record.scope == POOLED_SCOPE
        and record.left_outcome is not None
    }
    if not cells:
        return
    add(f"### {_FAMILY_TITLES[family]}")
    add("")
    add(f"| {left} \\ {right} | " + " | ".join(o.value for o in DecisionOutcome) + " |")
    add("| --- | --- | --- | --- |")
    for left_outcome in DecisionOutcome:
        row = " | ".join(
            str(cells.get((left_outcome, right_outcome), 0))
            for right_outcome in DecisionOutcome
        )
        add(f"| {left_outcome.value} | {row} |")
    add("")


def _add_eligibility_matrix(
    add,
    counts: Sequence[CrossAlgorithmCountRecord],
    *,
    left: str,
    right: str,
    releases: Sequence[str],
) -> None:
    cells: dict[tuple[str, str], int] = {}
    for record in counts:
        if not record.scope.startswith(f"eligibility:{POOLED_SCOPE}:"):
            continue
        _, _, left_status, right_status = record.scope.split(":")
        cells[(left_status, right_status)] = record.count
    if not cells:
        return
    add(f"### Eligibility transitions ({left} to {right}, pooled)")
    add("")
    statuses = [status.value for status in SelfEligibilityStatus]
    add(f"| {left} \\ {right} | " + " | ".join(statuses) + " |")
    add("| --- | --- | --- | --- |")
    for left_status in statuses:
        row = " | ".join(
            str(cells.get((left_status, right_status), 0)) for right_status in statuses
        )
        add(f"| {left_status} | {row} |")
    add("")


def report_content_hash(markdown: str) -> str:
    """Digest the rendered bytes, so a report edited afterwards stops verifying."""
    return stable_hash(
        {"schema": "cross_algorithm_report_v1", "markdown": markdown}, length=64
    )
