"""A small world whose every answer is known before the code runs.

Ten units, arranged so that no two published fractions are equal. That last part
is the design: in a world where the decided and attempt rates happened to
coincide, a bug that used one denominator for both would pass every assertion.
Here PLAIN decided is 8/9 and PLAIN attempt is 8/10, the unconditional FNMR is
2/9 and the conditional one is 1/6, and each of the ten fractions the
specification fixes is checked exactly (spec section 79).
"""

from __future__ import annotations

import pytest

from fpbench.core.metric_models import CountFamily
from metricworld import SPEC_EXAMPLE_SCRIPT, build_metric_world

pytestmark = pytest.mark.metrics


@pytest.fixture(scope="module")
def world():
    return build_metric_world({"SD300A": SPEC_EXAMPLE_SCRIPT})


@pytest.fixture(scope="module")
def parts(world):
    counts = world.counts()
    return counts, world.observations(counts)


@pytest.mark.parametrize(
    "family,expected",
    [
        (
            CountFamily.PLAIN_SELF,
            {"match": 8, "non_match": 1, "undecidable": 1, "decided": 9},
        ),
        (
            CountFamily.ROLL_SELF,
            {"match": 7, "non_match": 2, "undecidable": 1, "decided": 9},
        ),
        (
            CountFamily.SELF_ELIGIBILITY,
            {"eligible": 6, "ineligible": 3, "undetermined": 1},
        ),
        (
            CountFamily.MATED_UNCONDITIONAL,
            {"match": 7, "non_match": 2, "undecidable": 1, "decided": 9},
        ),
        (
            CountFamily.NEGATIVE_SANITY,
            {"match": 1, "non_match": 8, "undecidable": 1, "decided": 9},
        ),
    ],
)
def test_the_aggregate_counts_are_the_scripted_ones(
    world, parts, family, expected
) -> None:
    counts, _ = parts
    record = world.count_record(counts, family, "SD300A")
    assert record.total_count == 10
    assert dict(record.counts) == expected


def test_the_conditional_counts_are_the_scripted_ones(world, parts) -> None:
    counts, _ = parts
    record = world.count_record(counts, CountFamily.MATED_CONDITIONAL, "SD300A")
    assert record.total_count == 10
    assert dict(record.counts) == {
        "included": 6,
        "excluded_ineligible": 3,
        "excluded_undetermined": 1,
        "included_decided": 6,
        "included_match": 5,
        "included_non_match": 1,
        "included_undecidable": 0,
    }


@pytest.mark.parametrize(
    "metric_id,fraction",
    [
        ("plain_self_match_rate_decided", "8/9"),
        ("plain_self_match_rate_attempt", "8/10"),
        ("roll_self_match_rate_decided", "7/9"),
        ("roll_self_match_rate_attempt", "7/10"),
        ("self_eligibility_rate", "6/10"),
        ("self_ineligible_rate", "3/10"),
        ("self_undetermined_rate", "1/10"),
        ("plain_roll_mated_unconditional_fnmr_decided", "2/9"),
        ("plain_roll_mated_unconditional_non_success_rate_attempt", "3/10"),
        ("plain_roll_mated_conditional_selection_rate", "6/10"),
        ("plain_roll_mated_conditional_fnmr_decided", "1/6"),
        ("plain_roll_mated_conditional_non_success_rate_attempt", "1/6"),
        ("plain_roll_non_mated_sanity_match_rate_decided", "1/9"),
        ("plain_roll_non_mated_sanity_match_rate_attempt", "1/10"),
    ],
)
def test_every_published_fraction_is_exactly_the_expected_one(
    world, parts, metric_id, fraction
) -> None:
    _, observations = parts
    observation = world.observation(observations, metric_id, "SD300A")
    assert observation.fraction_text == fraction


def test_a_single_release_pools_to_itself(world, parts) -> None:
    _, observations = parts
    for metric_id in world.policy.metric_ids:
        release = world.observation(observations, metric_id, "SD300A")
        pooled = world.observation(observations, metric_id, "pooled")
        assert (pooled.numerator_count, pooled.denominator_count) == (
            release.numerator_count,
            release.denominator_count,
        )


def test_counts_stay_exact_and_percentages_are_display_only(world, parts) -> None:
    _, observations = parts
    observation = world.observation(
        observations, "plain_self_match_rate_decided", "SD300A"
    )
    # 8/9 has no exact decimal expansion; the stored value is the fraction.
    assert (observation.numerator_count, observation.denominator_count) == (8, 9)
    assert observation.percentage(decimal_places=4) == "88.8889"
    assert observation.percentage(decimal_places=2) == "88.89"
