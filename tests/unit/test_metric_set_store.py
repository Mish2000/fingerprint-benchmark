"""A metric set is immutable, round-trips exactly, and recognises itself.

Idempotence is the property being protected. The same decisions, the same
policy and the same metric code must produce the same metric-set id, the same
observation hashes and the same report bytes, on a second run and on another
machine — otherwise "re-derive it and check" is not something anyone can do
(spec section 68).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fpbench.core.errors import MetricSetConflictError, StorageError
from fpbench.storage.metric_set_store import MetricSetStore
from metricworld import SPEC_EXAMPLE_SCRIPT, all_matching, build_metric_world

pytestmark = pytest.mark.metrics


@pytest.fixture
def world():
    return build_metric_world(
        {
            "SD300A": SPEC_EXAMPLE_SCRIPT,
            "SD300B": all_matching(10),
            "SD300C": all_matching(10),
        }
    )


def test_the_metric_set_round_trips_through_parquet_and_json(
    world, tmp_path: Path
) -> None:
    definition, policy, profile, manifest, counts, observations = (
        world.store_metric_set(tmp_path)
    )
    store = MetricSetStore(tmp_path)

    assert store.read_definition(world.run_id, manifest.metric_set_id) == definition
    assert store.read_policy(world.run_id, manifest.metric_set_id) == policy
    assert (
        store.read_report_profile(world.run_id, manifest.metric_set_id) == profile
    )
    assert store.read_manifest(world.run_id, manifest.metric_set_id) == manifest
    assert store.read_counts(world.run_id, manifest.metric_set_id) == counts
    assert (
        store.read_observations(world.run_id, manifest.metric_set_id) == observations
    )


def test_a_pooled_row_survives_the_nullable_release_column(
    world, tmp_path: Path
) -> None:
    _, _, _, manifest, _, _ = world.store_metric_set(tmp_path)
    stored = MetricSetStore(tmp_path).read_counts(
        world.run_id, manifest.metric_set_id
    )
    pooled = [record for record in stored if record.scope.is_pooled]
    assert len(pooled) == 6
    assert all(record.scope.release is None for record in pooled)


def test_storing_the_same_set_twice_is_a_no_op(world, tmp_path: Path) -> None:
    first = world.store_metric_set(tmp_path)
    manifest = first[3]
    written = MetricSetStore(tmp_path).manifest_path(
        world.run_id, manifest.metric_set_id
    )
    stamp = written.stat().st_mtime_ns

    second = world.store_metric_set(tmp_path)
    assert second[3].metric_set_id == manifest.metric_set_id
    assert written.stat().st_mtime_ns == stamp


def test_the_same_inputs_produce_the_same_identities(world) -> None:
    twin = build_metric_world(dict(world.scripts), release_order=world.releases)

    left = world.metric_set()
    right = twin.metric_set()

    assert left[0].definition_id == right[0].definition_id
    assert left[3].metric_set_id == right[3].metric_set_id
    assert [item.observation_hash for item in left[5]] == [
        item.observation_hash for item in right[5]
    ]


def test_a_different_metric_set_under_the_same_id_is_a_conflict(
    world, tmp_path: Path
) -> None:
    definition, policy, profile, manifest, counts, observations = world.metric_set()
    store = MetricSetStore(tmp_path)
    store.ensure_metric_set(
        definition=definition,
        policy=policy,
        report_profile=profile,
        manifest=manifest,
        counts=counts,
        observations=observations,
    )

    # Same id, different contents. Only reachable by editing a stored file,
    # which is exactly what the conflict is for.
    forged = _forge_manifest(manifest)
    with pytest.raises(MetricSetConflictError, match="refusing to replace"):
        store.ensure_metric_set(
            definition=definition,
            policy=policy,
            report_profile=profile,
            manifest=forged,
            counts=counts,
            observations=observations,
        )


def test_a_manifest_whose_row_count_disagrees_is_refused(
    world, tmp_path: Path
) -> None:
    definition, policy, profile, manifest, counts, observations = world.metric_set()
    with pytest.raises(StorageError, match="count records"):
        MetricSetStore(tmp_path).ensure_metric_set(
            definition=definition,
            policy=policy,
            report_profile=profile,
            manifest=manifest,
            counts=counts[:-1],
            observations=observations,
        )


def test_observations_out_of_canonical_order_are_refused(
    world, tmp_path: Path
) -> None:
    definition, policy, profile, manifest, counts, observations = world.metric_set()
    shuffled = (observations[1], observations[0], *observations[2:])
    with pytest.raises(StorageError):
        MetricSetStore(tmp_path).ensure_metric_set(
            definition=definition,
            policy=policy,
            report_profile=profile,
            manifest=manifest,
            counts=counts,
            observations=shuffled,
        )


def test_the_report_is_written_once_and_conflicts_on_a_change(
    world, tmp_path: Path
) -> None:
    set_id = world.finalize(tmp_path)
    store = MetricSetStore(tmp_path)
    original = store.read_report(world.run_id, set_id)

    store.ensure_report(run_id=world.run_id, metric_set_id=set_id, markdown=original)
    with pytest.raises(MetricSetConflictError, match="different evaluation report"):
        store.ensure_report(
            run_id=world.run_id, metric_set_id=set_id, markdown=original + "\nedited\n"
        )


def test_the_stored_report_is_byte_identical_to_a_fresh_render(
    world, tmp_path: Path
) -> None:
    set_id = world.finalize(tmp_path)
    store = MetricSetStore(tmp_path)
    counts = store.read_counts(world.run_id, set_id)
    observations = store.read_observations(world.run_id, set_id)
    manifest = store.read_manifest(world.run_id, set_id)

    assert store.read_report(world.run_id, set_id) == world.render(
        manifest, counts, observations
    )


def test_parquet_metadata_names_the_metric_set(world, tmp_path: Path) -> None:
    _, _, _, manifest, _, _ = world.store_metric_set(tmp_path)
    metadata = MetricSetStore(tmp_path).record_metadata(
        world.run_id, manifest.metric_set_id
    )
    assert metadata["metric_set_id"] == manifest.metric_set_id
    assert metadata["metric_set_fingerprint"] == manifest.metric_set_fingerprint
    assert metadata["row_kind"] == "metric_observations"


def _forge_manifest(manifest):
    """A manifest with the same id and a different fingerprint.

    Constructed by hand because the model refuses the combination — which is the
    point: the only way to reach this state is to edit a file on disk.
    """

    class _Forged:
        pass

    forged = _Forged()
    for name in manifest.__slots__:
        setattr(forged, name, getattr(manifest, name))
    forged.metric_set_fingerprint = "f" * 64
    return forged
