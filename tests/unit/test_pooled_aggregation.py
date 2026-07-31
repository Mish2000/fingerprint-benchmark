"""Pooled values sum counts. They are not averages of release percentages.

The distinction is invisible when the releases are the same size, which they are
in this protocol — 500 comparisons each — so the tests use *deliberately unequal*
releases. A world with 10, 20 and 30 units makes the two formulas disagree, which
is the only way an assertion about which one was used can mean anything
(docs/adr/0028).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from fpbench.core.errors import MetricDerivationError
from fpbench.core.metric_models import CountFamily
from fpbench.metrics import aggregate_count_records, release_order_of
from metricworld import UnitScript, all_matching, build_metric_world

pytestmark = pytest.mark.metrics


def _uneven_world():
    """Three releases of different sizes, with different failure profiles.

    ``SD300A`` has ten clean units, ``SD300B`` twenty of which four fail their
    mated comparison, ``SD300C`` thirty of which one is undecidable. No two
    release rates are equal, and none equals the pooled rate.
    """
    from fpbench.core.enums import DecisionValue

    a = all_matching(10)
    b = tuple(
        UnitScript(mated=DecisionValue.NON_MATCH if index < 4 else DecisionValue.MATCH)
        for index in range(20)
    )
    c = tuple(
        UnitScript(mated=None if index == 0 else DecisionValue.MATCH)
        for index in range(30)
    )
    return build_metric_world({"SD300A": a, "SD300B": b, "SD300C": c})


@pytest.fixture(scope="module")
def world():
    return _uneven_world()


@pytest.fixture(scope="module")
def parts(world):
    counts = world.counts()
    return counts, world.observations(counts)


def test_pooled_numerator_equals_the_release_sum(world, parts) -> None:
    _, observations = parts
    metric = "plain_roll_mated_unconditional_fnmr_decided"
    releases = [
        world.observation(observations, metric, release).numerator_count
        for release in world.releases
    ]
    pooled = world.observation(observations, metric, "pooled")
    assert pooled.numerator_count == sum(releases) == 4


def test_pooled_denominator_equals_the_release_sum(world, parts) -> None:
    _, observations = parts
    metric = "plain_roll_mated_unconditional_fnmr_decided"
    releases = [
        world.observation(observations, metric, release).denominator_count
        for release in world.releases
    ]
    pooled = world.observation(observations, metric, "pooled")
    # 10 + 20 + 29: the one undecidable comparison in SD300C is not a decided
    # attempt and does not reach this denominator.
    assert pooled.denominator_count == sum(releases) == 59


def test_pooled_rate_is_not_the_mean_of_the_release_rates(world, parts) -> None:
    _, observations = parts
    metric = "plain_roll_mated_unconditional_fnmr_decided"
    rates = [
        Decimal(world.observation(observations, metric, release).numerator_count)
        / Decimal(world.observation(observations, metric, release).denominator_count)
        for release in world.releases
    ]
    mean_of_rates = sum(rates) / Decimal(len(rates))

    pooled = world.observation(observations, metric, "pooled")
    pooled_rate = Decimal(pooled.numerator_count) / Decimal(pooled.denominator_count)

    assert pooled_rate == Decimal(4) / Decimal(59)
    assert pooled_rate != mean_of_rates


def test_pooled_count_records_are_the_sums_too(world, parts) -> None:
    counts, _ = parts
    for family in CountFamily.ORDER:
        pooled = world.count_record(counts, family, "pooled")
        releases = [
            world.count_record(counts, family, release) for release in world.releases
        ]
        assert pooled.total_count == sum(record.total_count for record in releases)
        for key in pooled.counts:
            assert pooled.get(key) == sum(record.get(key) for record in releases)


def test_a_missing_release_is_rejected(world) -> None:
    with pytest.raises(MetricDerivationError, match="does not cover"):
        aggregate_count_records(world.sources, releases=("SD300A", "SD300B"))


def test_a_duplicate_release_is_rejected(world) -> None:
    with pytest.raises(MetricDerivationError, match="declares a release twice"):
        release_order_of(
            world.sources,
            expected_releases=("SD300A", "SD300A", "SD300B", "SD300C"),
        )


def test_an_unexpected_release_is_rejected_when_the_experiment_declares_them(
    world,
) -> None:
    with pytest.raises(MetricDerivationError, match="unexpected"):
        release_order_of(
            world.sources, expected_releases=("SD300A", "SD300B")
        )


def test_release_order_is_stable_and_declared(world) -> None:
    assert release_order_of(world.sources) == ("SD300A", "SD300B", "SD300C")
    assert release_order_of(
        world.sources, expected_releases=("SD300C", "SD300B", "SD300A")
    ) == ("SD300C", "SD300B", "SD300A")


def test_pooled_observation_is_last_in_every_metric_block(world, parts) -> None:
    _, observations = parts
    scopes = [observation.scope.label for observation in observations]
    block = len(world.releases) + 1
    for start in range(0, len(scopes), block):
        assert scopes[start : start + block] == [*world.releases, "pooled"]
