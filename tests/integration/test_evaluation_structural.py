"""The full 6,000-decision shape, end to end, without SourceAFIS or SD300.

The real evaluation is 6,000 decisions, 1,500 eligibility units and three views
of 1,500 rows each, over three releases of 500. Everything about that shape can
be exercised without a matcher and without the dataset, because the metric engine
never sees either — it reads decisions. So this test builds the exact shape with
scripted outcomes and drives the whole chain to ``EVALUATION_READY``.

What it is checking is not arithmetic; the exact-value test does that on ten
units where every answer can be written down. It is checking that nothing in the
pipeline is quietly quadratic, that the partitioning holds at scale, and that
every pooled value is the sum of three releases rather than of two or four.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fpbench.core.enums import DecisionValue, EvaluationStatus
from fpbench.core.metric_models import CountFamily
from fpbench.storage.metric_set_store import MetricSetStore
from metricworld import UnitScript, build_metric_world

pytestmark = pytest.mark.metrics

RELEASES = ("SD300A", "SD300B", "SD300C")
UNITS_PER_RELEASE = 500


def _release_scripts(seed: int) -> tuple[UnitScript, ...]:
    """500 units with a small, deterministic sprinkling of every outcome.

    The failure pattern differs per release so that no two releases produce the
    same numbers — a pooled value that happened to equal a release value would
    let a partitioning bug pass.
    """
    scripts = []
    for index in range(UNITS_PER_RELEASE):
        plain = DecisionValue.MATCH
        roll = DecisionValue.MATCH
        mated = DecisionValue.MATCH
        negative = DecisionValue.NON_MATCH

        if index % (37 + seed) == 0:
            roll = DecisionValue.NON_MATCH
        if index % (53 + seed) == 0:
            plain = None
        if index % (23 + seed) == 0:
            mated = DecisionValue.NON_MATCH
        if index % (97 + seed) == 0:
            mated = None
        if index % (199 + seed) == 0:
            negative = DecisionValue.MATCH

        scripts.append(
            UnitScript(plain=plain, roll=roll, mated=mated, negative=negative)
        )
    return tuple(scripts)


@pytest.fixture(scope="module")
def world():
    return build_metric_world(
        {release: _release_scripts(index) for index, release in enumerate(RELEASES)},
        release_order=RELEASES,
    )


def test_the_scripted_chain_has_the_real_runs_shape(world) -> None:
    assert len(world.sources.decisions) == 6_000
    assert len(world.sources.eligibility_records) == 1_500
    for kind in world.sources.view_entries:
        assert len(world.sources.view_entries[kind]) == 1_500


def test_every_release_contributes_five_hundred_of_everything(world) -> None:
    counts = world.counts()
    for family in CountFamily.ORDER:
        for release in RELEASES:
            record = world.count_record(counts, family, release)
            assert record.total_count == UNITS_PER_RELEASE, (family, release)


def test_all_expected_observations_are_created(world) -> None:
    counts = world.counts()
    observations = world.observations(counts)
    expected = len(world.policy.metric_ids) * (len(RELEASES) + 1)
    assert len(observations) == expected

    seen = {
        (observation.metric_id, observation.scope.label)
        for observation in observations
    }
    for metric_id in world.policy.metric_ids:
        for scope in (*RELEASES, "pooled"):
            assert (metric_id, scope) in seen


def test_every_pooled_value_equals_the_sum_of_three_releases(world) -> None:
    counts = world.counts()
    observations = world.observations(counts)
    for metric_id in world.policy.metric_ids:
        pooled = world.observation(observations, metric_id, "pooled")
        numerator = sum(
            world.observation(observations, metric_id, release).numerator_count
            for release in RELEASES
        )
        denominator = sum(
            world.observation(observations, metric_id, release).denominator_count
            for release in RELEASES
        )
        assert (pooled.numerator_count, pooled.denominator_count) == (
            numerator,
            denominator,
        ), metric_id


def test_pooled_counts_total_fifteen_hundred(world) -> None:
    counts = world.counts()
    for family in CountFamily.ORDER:
        assert world.count_record(counts, family, "pooled").total_count == 1_500


def test_the_whole_chain_stores_round_trips_and_reaches_evaluation_ready(
    world, tmp_path: Path
) -> None:
    set_id = world.finalize(tmp_path)
    store = MetricSetStore(tmp_path)

    definition, policy, profile, manifest, counts, observations = (
        store.read_metric_set(world.run_id, set_id)
    )
    assert manifest.total_count_records == len(CountFamily.ORDER) * (
        len(RELEASES) + 1
    )
    assert manifest.total_observations == len(policy.metric_ids) * (
        len(RELEASES) + 1
    )

    state = world.inspect(tmp_path, set_id)
    assert state.status is EvaluationStatus.EVALUATION_READY, state.issues
    assert state.total_count_records == 24
    assert state.total_observations == 56

    receipt = store.read_receipt(world.run_id, set_id)
    assert dict(receipt.structural_counts) == {
        "decisions": 6_000,
        "eligibility_units": 1_500,
        "unconditional_rows": 1_500,
        "conditional_rows": 1_500,
        "negative_sanity_rows": 1_500,
    }
    assert set(receipt.metrics) == set(policy.metric_ids)
    for by_scope in receipt.metrics.values():
        assert set(by_scope) == {*RELEASES, "pooled"}


def test_the_report_covers_every_release_and_pools_them(world, tmp_path: Path) -> None:
    set_id = world.finalize(tmp_path)
    report = MetricSetStore(tmp_path).read_report(world.run_id, set_id)
    for release in RELEASES:
        assert f"| {release} |" in report
    assert "| pooled |" in report
