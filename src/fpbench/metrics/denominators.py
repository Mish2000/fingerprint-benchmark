"""The one place a numerator and a denominator become integers.

Everything about this module is about closing a single hole. If an aggregation
function computed ``3/487`` and handed a verifier the pair, the verifier could
check that ``3 ≤ 487`` and nothing else — in particular it could not tell that
487 was the *decided* count where the metric claimed to be over all attempts. So
no function is allowed to pass a denominator around. Both the aggregation and the
verification call :func:`resolve`, which derives both integers from a stored
count record and a metric definition, and the metric definition names its
denominator with an enum member rather than a number (spec section 47).

The compatibility table below is the second half of the same idea. A denominator
is only meaningful over some populations: ``ALL_ELIGIBILITY_UNITS`` over the
mated view is not a slightly wrong answer, it is a category error, and it fails
here rather than producing a number that looks plausible.

``NON_SUCCESS`` gets its own restriction. ``NON_MATCH + UNDECIDABLE`` is the
honest attempt-level answer for a *genuine* comparison, where both mean "this
finger was not recognised". Over an impostor set the same sum would mean nothing:
a failed impostor comparison is not a near miss (docs/adr/0027, docs/adr/0030).
"""

from __future__ import annotations

from typing import Mapping

from fpbench.core.errors import MetricPolicyError
from fpbench.core.metric_models import (
    CountFamily,
    EvaluationCountRecord,
    MetricDefinition,
    MetricDenominator,
    MetricNumerator,
)

__all__ = [
    "resolve",
    "resolve_numerator",
    "resolve_denominator",
    "DENOMINATORS_FOR_FAMILY",
    "NUMERATORS_FOR_FAMILY",
    "GENUINE_FAMILIES",
]

#: Families whose comparisons are known-mated, and therefore the only ones over
#: which ``NON_SUCCESS`` means anything.
GENUINE_FAMILIES: frozenset[str] = frozenset(
    {CountFamily.MATED_UNCONDITIONAL, CountFamily.MATED_CONDITIONAL}
)

#: Which denominators a family can support. Anything outside this is a category
#: error rather than an unusual choice.
DENOMINATORS_FOR_FAMILY: Mapping[str, frozenset[MetricDenominator]] = {
    CountFamily.PLAIN_SELF: frozenset(
        {MetricDenominator.ALL_ATTEMPTS, MetricDenominator.DECIDED_ATTEMPTS}
    ),
    CountFamily.ROLL_SELF: frozenset(
        {MetricDenominator.ALL_ATTEMPTS, MetricDenominator.DECIDED_ATTEMPTS}
    ),
    CountFamily.SELF_ELIGIBILITY: frozenset(
        {MetricDenominator.ALL_ELIGIBILITY_UNITS}
    ),
    CountFamily.MATED_UNCONDITIONAL: frozenset(
        {MetricDenominator.ALL_ATTEMPTS, MetricDenominator.DECIDED_ATTEMPTS}
    ),
    # ``ALL_ATTEMPTS`` here is every mated row, included or not: it is the
    # denominator of the selection rate, and the only denominator in the stage
    # that spans excluded rows (spec section 16).
    CountFamily.MATED_CONDITIONAL: frozenset(
        {
            MetricDenominator.ALL_ATTEMPTS,
            MetricDenominator.INCLUDED_CONDITIONAL_ATTEMPTS,
            MetricDenominator.DECIDED_CONDITIONAL_ATTEMPTS,
        }
    ),
    CountFamily.NEGATIVE_SANITY: frozenset(
        {MetricDenominator.ALL_ATTEMPTS, MetricDenominator.DECIDED_ATTEMPTS}
    ),
}

#: Which numerators a family can support.
NUMERATORS_FOR_FAMILY: Mapping[str, frozenset[MetricNumerator]] = {
    CountFamily.PLAIN_SELF: frozenset(
        {
            MetricNumerator.MATCH,
            MetricNumerator.NON_MATCH,
            MetricNumerator.UNDECIDABLE,
        }
    ),
    CountFamily.ROLL_SELF: frozenset(
        {
            MetricNumerator.MATCH,
            MetricNumerator.NON_MATCH,
            MetricNumerator.UNDECIDABLE,
        }
    ),
    CountFamily.SELF_ELIGIBILITY: frozenset(
        {
            MetricNumerator.ELIGIBLE,
            MetricNumerator.INELIGIBLE,
            MetricNumerator.UNDETERMINED,
        }
    ),
    CountFamily.MATED_UNCONDITIONAL: frozenset(
        {
            MetricNumerator.MATCH,
            MetricNumerator.NON_MATCH,
            MetricNumerator.UNDECIDABLE,
            MetricNumerator.NON_SUCCESS,
        }
    ),
    CountFamily.MATED_CONDITIONAL: frozenset(
        {
            MetricNumerator.MATCH,
            MetricNumerator.NON_MATCH,
            MetricNumerator.UNDECIDABLE,
            MetricNumerator.NON_SUCCESS,
            MetricNumerator.INCLUDED,
            MetricNumerator.EXCLUDED_INELIGIBLE,
            MetricNumerator.EXCLUDED_UNDETERMINED,
        }
    ),
    # No ``NON_SUCCESS``: over impostor comparisons the sum of non-matches and
    # failures is not a meaningful quantity.
    CountFamily.NEGATIVE_SANITY: frozenset(
        {
            MetricNumerator.MATCH,
            MetricNumerator.NON_MATCH,
            MetricNumerator.UNDECIDABLE,
        }
    ),
}


def resolve(
    *, definition: MetricDefinition, record: EvaluationCountRecord
) -> tuple[int, int]:
    """Derive ``(numerator, denominator)`` for one metric over one count record.

    Called by the aggregation that produces observations *and* by the verifier
    that re-checks them, so the two cannot disagree about what a denominator was.

    Raises:
        MetricPolicyError: the record is not the family the metric reads, or the
            metric names a numerator or denominator that population cannot
            supply.
    """
    if record.count_family != definition.metric_family:
        raise MetricPolicyError(
            f"metric {definition.metric_id} reads count family "
            f"{definition.metric_family!r}, but was handed a "
            f"{record.count_family!r} record"
        )
    return (
        resolve_numerator(definition=definition, record=record),
        resolve_denominator(definition=definition, record=record),
    )


def resolve_numerator(
    *, definition: MetricDefinition, record: EvaluationCountRecord
) -> int:
    """The integer on top of the line, read from the stored counts."""
    family = definition.metric_family
    numerator = definition.numerator
    _require_supported(
        family=family,
        value=numerator,
        allowed=NUMERATORS_FOR_FAMILY[family],
        what="numerator",
        metric_id=definition.metric_id,
    )
    if numerator is MetricNumerator.NON_SUCCESS and family not in GENUINE_FAMILIES:
        raise MetricPolicyError(
            f"metric {definition.metric_id} counts non-successes over "
            f"{family!r}. NON_MATCH + UNDECIDABLE is the honest attempt-level "
            "answer for a mated comparison; over an impostor set it is not a "
            "quantity anyone can interpret (docs/adr/0027)"
        )

    if family == CountFamily.SELF_ELIGIBILITY:
        return record.get(numerator.value)

    if family == CountFamily.MATED_CONDITIONAL:
        if numerator is MetricNumerator.NON_SUCCESS:
            return record.get("included_non_match") + record.get(
                "included_undecidable"
            )
        if numerator in (
            MetricNumerator.INCLUDED,
            MetricNumerator.EXCLUDED_INELIGIBLE,
            MetricNumerator.EXCLUDED_UNDETERMINED,
        ):
            return record.get(numerator.value)
        # Outcome numerators over the conditional family always mean the
        # *included* outcome. An excluded row has an outcome too, and counting it
        # here would put rows in a numerator that its denominator excludes.
        return record.get(f"included_{numerator.value}")

    if numerator is MetricNumerator.NON_SUCCESS:
        return record.get("non_match") + record.get("undecidable")
    return record.get(numerator.value)


def resolve_denominator(
    *, definition: MetricDefinition, record: EvaluationCountRecord
) -> int:
    """The integer under the line, read from the stored counts.

    Never supplied by a caller. That is the whole point of the module.
    """
    family = definition.metric_family
    denominator = definition.denominator
    _require_supported(
        family=family,
        value=denominator,
        allowed=DENOMINATORS_FOR_FAMILY[family],
        what="denominator",
        metric_id=definition.metric_id,
    )

    if denominator is MetricDenominator.ALL_ATTEMPTS:
        return record.total_count
    if denominator is MetricDenominator.ALL_ELIGIBILITY_UNITS:
        return record.total_count
    if denominator is MetricDenominator.DECIDED_ATTEMPTS:
        return record.get("decided")
    if denominator is MetricDenominator.INCLUDED_CONDITIONAL_ATTEMPTS:
        return record.get("included")
    return record.get("included_decided")


def _require_supported(
    *,
    family: str,
    value: object,
    allowed: frozenset,
    what: str,
    metric_id: str,
) -> None:
    if value not in allowed:
        rendered = sorted(item.value for item in allowed)
        raise MetricPolicyError(
            f"metric {metric_id} names {what} {getattr(value, 'value', value)!r} "
            f"over count family {family!r}, which supports {rendered}. A "
            "denominator that the population cannot supply is a category error, "
            "not an unusual choice"
        )
