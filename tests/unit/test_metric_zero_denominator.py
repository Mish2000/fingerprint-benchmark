"""A metric over an empty population is undefined, and says so.

An evaluation in which no finger passed both SELF tests is a real outcome, not a
crash. It is also not zero per cent: "no comparison failed" and "no comparison
was covered" are different facts, and rendering the second as ``0.0000%`` would
publish a measurement nobody made (spec sections 26, 70).
"""

from __future__ import annotations

import pytest

from fpbench.core.enums import DecisionValue, MetricObservationStatus
from metricworld import UnitScript, build_metric_world

pytestmark = pytest.mark.metrics


@pytest.fixture(scope="module")
def world():
    """Ten units, every one of them disqualified by a PLAIN SELF non-match."""
    scripts = tuple(
        UnitScript(
            plain=DecisionValue.NON_MATCH,
            roll=DecisionValue.MATCH,
            mated=DecisionValue.MATCH,
            negative=DecisionValue.NON_MATCH,
        )
        for _ in range(10)
    )
    return build_metric_world({"SD300A": scripts})


@pytest.fixture(scope="module")
def parts(world):
    counts = world.counts()
    return counts, world.observations(counts)


def test_nothing_is_included_in_the_conditional_view(world, parts) -> None:
    counts, _ = parts
    record = world.count_record(counts, "mated_conditional_outcomes", "SD300A")
    assert record.total_count == 10
    assert record.get("included") == 0
    assert record.get("excluded_ineligible") == 10
    assert record.get("included_decided") == 0


def test_the_selection_rate_is_zero_over_the_total_not_undefined(
    world, parts
) -> None:
    _, observations = parts
    selection = world.observation(
        observations, "plain_roll_mated_conditional_selection_rate", "SD300A"
    )
    assert selection.status is MetricObservationStatus.DEFINED
    assert selection.fraction_text == "0/10"
    assert selection.percentage(decimal_places=4) == "0.0000"


@pytest.mark.parametrize(
    "metric_id",
    [
        "plain_roll_mated_conditional_fnmr_decided",
        "plain_roll_mated_conditional_non_success_rate_attempt",
    ],
)
def test_conditional_rates_over_an_empty_population_are_undefined(
    world, parts, metric_id
) -> None:
    _, observations = parts
    observation = world.observation(observations, metric_id, "SD300A")
    assert observation.status is MetricObservationStatus.UNDEFINED_ZERO_DENOMINATOR
    assert observation.denominator_count == 0
    assert observation.numerator_count == 0
    assert observation.fraction_text is None
    assert observation.percentage(decimal_places=4) is None


def test_no_division_by_zero_reaches_the_caller(world, parts) -> None:
    # Building the whole observation list is the exercise: nothing here raises,
    # and no NaN or infinity is produced anywhere.
    _, observations = parts
    assert observations
    for observation in observations:
        rendered = observation.percentage(decimal_places=4)
        assert rendered is None or ("nan" not in rendered.lower())
        assert rendered is None or ("inf" not in rendered.lower())


def test_an_undefined_metric_renders_explicitly_in_the_report(world, parts) -> None:
    counts, observations = parts
    manifest = world.manifest(counts, observations)
    markdown = world.render(manifest, counts, observations)
    assert "undefined (0 included decided attempts)" in markdown
    assert "undefined (0 included attempts)" in markdown
