"""Every metric divides by the population it names, and by no other.

These are the tests that would catch the failure this stage was designed
against: a rate computed over ``decided`` comparisons and reported as though it
covered every attempt. The two numbers are equal whenever nothing failed, which
is most of the time, which is why the check has to be structural rather than
numeric — each assertion pins the denominator to a *specific count* in a
scripted world where the two differ (docs/adr/0027).
"""

from __future__ import annotations

import pytest

from fpbench.core.errors import MetricPolicyError
from fpbench.core.metric_models import (
    CountFamily,
    MetricDefinition,
    MetricDenominator,
    MetricNumerator,
)
from fpbench.metrics.denominators import resolve
from metricworld import SPEC_EXAMPLE_SCRIPT, UnitScript, build_metric_world

pytestmark = pytest.mark.metrics


@pytest.fixture(scope="module")
def world():
    return build_metric_world({"SD300A": SPEC_EXAMPLE_SCRIPT})


@pytest.fixture(scope="module")
def parts(world):
    counts = world.counts()
    return counts, world.observations(counts)


def _pair(world, parts, metric_id: str, scope: str = "SD300A") -> tuple[int, int]:
    _, observations = parts
    observation = world.observation(observations, metric_id, scope)
    return observation.numerator_count, observation.denominator_count


def test_self_decided_match_rate_uses_the_decided_denominator(world, parts) -> None:
    counts, _ = parts
    record = world.count_record(counts, CountFamily.PLAIN_SELF, "SD300A")
    assert record.get("decided") == 9 and record.total_count == 10
    assert _pair(world, parts, "plain_self_match_rate_decided") == (8, 9)


def test_self_attempt_match_rate_uses_all_attempts(world, parts) -> None:
    assert _pair(world, parts, "plain_self_match_rate_attempt") == (8, 10)


def test_the_two_self_rates_differ_by_exactly_the_undecidable_count(
    world, parts
) -> None:
    counts, _ = parts
    record = world.count_record(counts, CountFamily.PLAIN_SELF, "SD300A")
    decided = _pair(world, parts, "plain_self_match_rate_decided")
    attempt = _pair(world, parts, "plain_self_match_rate_attempt")
    assert decided[0] == attempt[0]
    assert attempt[1] - decided[1] == record.get("undecidable")


def test_unconditional_fnmr_excludes_undecidable_from_its_denominator(
    world, parts
) -> None:
    counts, _ = parts
    record = world.count_record(counts, CountFamily.MATED_UNCONDITIONAL, "SD300A")
    assert record.get("undecidable") == 1
    assert _pair(world, parts, "plain_roll_mated_unconditional_fnmr_decided") == (2, 9)


def test_attempt_non_success_includes_undecidable_in_its_numerator(
    world, parts
) -> None:
    numerator, denominator = _pair(
        world, parts, "plain_roll_mated_unconditional_non_success_rate_attempt"
    )
    counts, _ = parts
    record = world.count_record(counts, CountFamily.MATED_UNCONDITIONAL, "SD300A")
    assert numerator == record.get("non_match") + record.get("undecidable") == 3
    assert denominator == 10


def test_conditional_fnmr_uses_included_decided_only(world, parts) -> None:
    counts, _ = parts
    record = world.count_record(counts, CountFamily.MATED_CONDITIONAL, "SD300A")
    assert record.total_count == 10 and record.get("included") == 6
    assert _pair(world, parts, "plain_roll_mated_conditional_fnmr_decided") == (1, 6)


def test_excluded_rows_never_enter_a_conditional_denominator(world, parts) -> None:
    counts, _ = parts
    record = world.count_record(counts, CountFamily.MATED_CONDITIONAL, "SD300A")
    excluded = (
        record.get("excluded_ineligible") + record.get("excluded_undetermined")
    )
    assert excluded == 4
    for metric_id in (
        "plain_roll_mated_conditional_fnmr_decided",
        "plain_roll_mated_conditional_non_success_rate_attempt",
    ):
        _, denominator = _pair(world, parts, metric_id)
        assert denominator <= record.get("included")


def test_selection_rate_uses_all_mated_rows(world, parts) -> None:
    assert _pair(world, parts, "plain_roll_mated_conditional_selection_rate") == (
        6,
        10,
    )


def test_negative_sanity_rate_never_uses_eligibility(world, parts) -> None:
    _, observations = parts
    for metric_id in (
        "plain_roll_non_mated_sanity_match_rate_decided",
        "plain_roll_non_mated_sanity_match_rate_attempt",
    ):
        observation = world.observation(observations, metric_id, "SD300A")
        assert observation.source_eligibility_set_fingerprint is None
    assert _pair(
        world, parts, "plain_roll_non_mated_sanity_match_rate_decided"
    ) == (1, 9)


def test_a_denominator_the_population_cannot_supply_is_refused(world, parts) -> None:
    counts, _ = parts
    record = world.count_record(counts, CountFamily.NEGATIVE_SANITY, "SD300A")
    nonsense = MetricDefinition(
        metric_id="sanity_over_eligibility_units",
        metric_family=CountFamily.NEGATIVE_SANITY,
        numerator=MetricNumerator.MATCH,
        denominator=MetricDenominator.ALL_ELIGIBILITY_UNITS,
        source_view_kind=None,
        source_protocol_stage=None,
        interpretation="a category error",
    )
    with pytest.raises(MetricPolicyError, match="category error"):
        resolve(definition=nonsense, record=record)


def test_non_success_is_refused_over_an_impostor_population(world, parts) -> None:
    counts, _ = parts
    record = world.count_record(counts, CountFamily.NEGATIVE_SANITY, "SD300A")
    nonsense = MetricDefinition(
        metric_id="sanity_non_success_rate",
        metric_family=CountFamily.NEGATIVE_SANITY,
        numerator=MetricNumerator.NON_SUCCESS,
        denominator=MetricDenominator.ALL_ATTEMPTS,
        source_view_kind=None,
        source_protocol_stage=None,
        interpretation="not a quantity anyone can interpret",
    )
    with pytest.raises(MetricPolicyError):
        resolve(definition=nonsense, record=record)


def test_the_four_rates_do_not_coincide_when_something_fails() -> None:
    """The specification's worked case (section 69), asserted exactly.

    A mated population of ``MATCH=8, NON_MATCH=1, UNDECIDABLE=1`` must produce
    four *different* fractions. The current SD300 run has no failures, so all
    four coincide there; a metric engine that collapsed them would pass every
    test taken from that run and be wrong on the first run that fails.
    """
    from fpbench.core.enums import DecisionValue

    scripts = tuple(
        UnitScript(
            plain=DecisionValue.MATCH,
            roll=DecisionValue.MATCH,
            mated=(
                DecisionValue.NON_MATCH
                if index == 8
                else (None if index == 9 else DecisionValue.MATCH)
            ),
            negative=DecisionValue.NON_MATCH,
        )
        for index in range(10)
    )
    small = build_metric_world({"SD300A": scripts})
    counts = small.counts()
    observations = small.observations(counts)

    record = small.count_record(counts, CountFamily.MATED_UNCONDITIONAL, "SD300A")
    assert dict(record.counts) == {
        "match": 8,
        "non_match": 1,
        "undecidable": 1,
        "decided": 9,
    }

    def fraction(metric_id: str) -> str:
        return small.observation(observations, metric_id, "SD300A").fraction_text

    # The two SELF-style match rates, and the two genuine failure rates.
    assert fraction("plain_roll_mated_unconditional_fnmr_decided") == "1/9"
    assert fraction("plain_roll_mated_unconditional_non_success_rate_attempt") == "2/10"

    conditional_record = small.count_record(
        counts, CountFamily.MATED_CONDITIONAL, "SD300A"
    )
    assert conditional_record.get("included") == 10
    assert fraction("plain_roll_mated_conditional_fnmr_decided") == "1/9"
    assert (
        fraction("plain_roll_mated_conditional_non_success_rate_attempt") == "2/10"
    )


def test_a_metric_cannot_read_another_familys_counts(world, parts) -> None:
    counts, _ = parts
    record = world.count_record(counts, CountFamily.PLAIN_SELF, "SD300A")
    definition = world.policy.definition(
        "plain_roll_mated_unconditional_fnmr_decided"
    )
    with pytest.raises(MetricPolicyError, match="was handed a"):
        resolve(definition=definition, record=record)
