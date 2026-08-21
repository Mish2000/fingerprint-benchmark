"""A numerator has to live inside its denominator.

The two were validated separately — is this numerator supported by this family,
is this denominator — and never against each other. ``UNDECIDABLE /
DECIDED_ATTEMPTS`` passed both and returned ``1/9``: a fraction whose numerator
counts exactly the comparisons its denominator was defined to exclude.

There is no reading of that number. It is not a low rate or an unusual choice.
"""

from __future__ import annotations

import pytest

from fpbench.core.enums import MetricDenominator, MetricNumerator
from fpbench.core.errors import MetricPolicyError
from fpbench.core.metric_models import MetricDefinition
from fpbench.metrics.denominators import COMPATIBLE_NUMERATORS, require_compatible
from fpbench.metrics.policy import METRIC_CATALOGUE


def _definition(
    numerator: MetricNumerator,
    denominator: MetricDenominator,
    family: str = "plain_self_outcomes",
) -> MetricDefinition:
    return MetricDefinition(
        metric_id="probe_rate_attempt",
        metric_family=family,
        numerator=numerator,
        denominator=denominator,
        source_view_kind=None,
        source_protocol_stage=None,
        interpretation="a probe used only by this test",
    )


@pytest.mark.parametrize(
    "metric_id", sorted(d.metric_id for d in METRIC_CATALOGUE.values())
)
def test_every_published_metric_nests(metric_id: str) -> None:
    """The rule must accept what the repository already publishes."""
    definition = next(
        d for d in METRIC_CATALOGUE.values() if d.metric_id == metric_id
    )
    require_compatible(definition)


def test_the_reviewers_example_is_refused() -> None:
    """``UNDECIDABLE / DECIDED_ATTEMPTS`` — the one that returned ``1/9``."""
    with pytest.raises(MetricPolicyError, match="excludes"):
        require_compatible(
            _definition(MetricNumerator.UNDECIDABLE, MetricDenominator.DECIDED_ATTEMPTS)
        )


def test_non_success_over_decided_attempts_is_refused() -> None:
    """``NON_MATCH + UNDECIDABLE`` cannot sit over a decided-only population."""
    with pytest.raises(MetricPolicyError, match="excludes"):
        require_compatible(
            _definition(
                MetricNumerator.NON_SUCCESS, MetricDenominator.DECIDED_ATTEMPTS
            )
        )


def test_an_undecidable_conditional_over_a_decided_denominator_is_refused() -> None:
    with pytest.raises(MetricPolicyError, match="excludes"):
        require_compatible(
            _definition(
                MetricNumerator.UNDECIDABLE,
                MetricDenominator.DECIDED_CONDITIONAL_ATTEMPTS,
                family="mated_conditional_outcomes",
            )
        )


def test_an_eligibility_numerator_over_an_attempt_denominator_is_refused() -> None:
    """A SELF unit is not a comparison; the two populations never nest."""
    with pytest.raises(MetricPolicyError, match="excludes"):
        require_compatible(
            _definition(
                MetricNumerator.ELIGIBLE,
                MetricDenominator.DECIDED_ATTEMPTS,
                family="self_eligibility_outcomes",
            )
        )


@pytest.mark.parametrize(
    ("numerator", "denominator"),
    [
        (MetricNumerator.MATCH, MetricDenominator.ALL_ATTEMPTS),
        (MetricNumerator.MATCH, MetricDenominator.DECIDED_ATTEMPTS),
        (MetricNumerator.NON_MATCH, MetricDenominator.DECIDED_ATTEMPTS),
        (MetricNumerator.UNDECIDABLE, MetricDenominator.ALL_ATTEMPTS),
        (MetricNumerator.NON_SUCCESS, MetricDenominator.ALL_ATTEMPTS),
    ],
)
def test_a_nesting_pair_is_accepted(
    numerator: MetricNumerator, denominator: MetricDenominator
) -> None:
    require_compatible(_definition(numerator, denominator))


def test_every_denominator_declares_its_population() -> None:
    """A denominator added later must say what is inside it, or nothing can nest."""
    missing = sorted(
        member.value
        for member in MetricDenominator
        if member not in COMPATIBLE_NUMERATORS
    )
    assert not missing, f"these denominators declare no population: {missing}"


def test_resolve_refuses_before_it_reads_a_count(monkeypatch) -> None:
    """The check runs in ``resolve``, not only where a policy is assembled.

    ``resolve`` is what the aggregation and the verifier both call, so a
    definition that reached them another way is still refused.
    """
    from fpbench.metrics import denominators

    class _Record:
        count_family = "plain_self_outcomes"
        total_count = 9

        def get(self, _key: str) -> int:  # pragma: no cover - never reached
            raise AssertionError("resolve read a count before checking the pair")

    with pytest.raises(MetricPolicyError, match="excludes"):
        denominators.resolve(
            definition=_definition(
                MetricNumerator.UNDECIDABLE, MetricDenominator.DECIDED_ATTEMPTS
            ),
            record=_Record(),
        )
