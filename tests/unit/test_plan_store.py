"""A stored plan must come back exactly as it went in, or not at all."""

from __future__ import annotations

from dataclasses import replace

import pyarrow.parquet as pq
import pytest

from fpbench.core.errors import PlanConflictError, StorageError
from fpbench.core.execution_plan_models import ExecutionPlanDefinition
from fpbench.core.identifiers import PairId
from fpbench.storage.plan_store import PlanStore
from runworld import build_world


@pytest.fixture
def world(tmp_path):
    return build_world(tmp_path, subjects=2, fingers=2)


@pytest.fixture
def store(world) -> PlanStore:
    return world.plan_store


# ---------------------------------------------------------------- round trip


def test_plan_round_trips(store, world):
    store.ensure_plan(world.plan)
    assert store.read_plan(world.run.run_id) == world.plan


def test_definition_round_trips_without_reading_the_jobs(store, world):
    store.ensure_plan(world.plan)
    assert store.read_plan_definition(world.run.run_id) == world.plan.definition


def test_planned_jobs_come_back_in_ordinal_order(store, world):
    store.ensure_plan(world.plan)
    jobs = list(store.iter_planned_jobs(world.run.run_id))
    assert [item.ordinal for item in jobs] == list(range(world.plan.total_jobs))
    assert jobs == list(world.plan.jobs)


def test_one_row_per_planned_job(store, world):
    store.ensure_plan(world.plan)
    table = pq.read_table(store.jobs_path(world.run.run_id))
    assert table.num_rows == world.plan.total_jobs


def test_the_plan_lands_where_documented(store, world):
    store.ensure_plan(world.plan)
    run_dir = world.workspace / "results" / world.run.run_id
    assert store.plan_manifest_path(world.run.run_id) == run_dir / "plan" / "plan.json"
    assert store.jobs_path(world.run.run_id) == run_dir / "plan" / "jobs.parquet"
    assert store.plan_manifest_path(world.run.run_id).is_file()


def test_the_jobs_table_carries_no_protocol_information(store, world):
    store.ensure_plan(world.plan)
    columns = set(pq.read_schema(store.jobs_path(world.run.run_id)).names)
    assert {"protocol_stage", "ground_truth", "threshold", "decision"} & columns == set()


# ------------------------------------------------------------------ metadata


def test_required_metadata_is_written(store, world):
    store.ensure_plan(world.plan)
    metadata = store.plan_metadata(world.run.run_id)
    for key in (
        "schema_version",
        "plan_id",
        "plan_fingerprint",
        "run_id",
        "run_fingerprint",
        "pair_manifest_hash",
        "job_manifest_hash",
        "job_count",
        "fpbench_version",
        "created_utc",
    ):
        assert metadata[key], f"missing metadata: {key}"
    assert metadata["job_count"] == str(world.plan.total_jobs)
    assert metadata["plan_id"] == world.plan.plan_id


# ----------------------------------------------------------------- idempotence


def test_ensuring_the_same_plan_twice_is_a_no_op(store, world):
    store.ensure_plan(world.plan)
    before = store.plan_manifest_path(world.run.run_id).read_bytes()
    jobs_before = store.jobs_path(world.run.run_id).read_bytes()
    store.ensure_plan(world.plan)
    assert store.plan_manifest_path(world.run.run_id).read_bytes() == before
    assert store.jobs_path(world.run.run_id).read_bytes() == jobs_before


def test_a_different_plan_under_the_same_run_conflicts(store, world):
    store.ensure_plan(world.plan)
    impostor = replace(
        world.plan,
        definition=replace(world.plan.definition, plan_fingerprint="e" * 64, plan_id="plan_eeeeeeeeeeee"),
    )
    with pytest.raises(PlanConflictError):
        store.ensure_plan(impostor)


def test_there_is_no_way_to_force_an_overwrite():
    import inspect

    signature = inspect.signature(PlanStore.ensure_plan)
    assert "overwrite" not in signature.parameters
    assert "force" not in signature.parameters


def test_the_write_leaves_no_temporary_file(store, world):
    store.ensure_plan(world.plan)
    assert list(store.plan_dir(world.run.run_id).glob("*.tmp")) == []


# ------------------------------------------------------------------ integrity


def test_a_missing_plan_is_a_storage_error(store, world):
    with pytest.raises(StorageError, match="execution plan not found"):
        store.read_plan_definition(world.run.run_id)


def test_a_corrupt_plan_manifest_is_a_storage_error(store, world):
    store.ensure_plan(world.plan)
    store.plan_manifest_path(world.run.run_id).write_text("{}", encoding="utf-8")
    with pytest.raises(StorageError, match="unreadable execution plan"):
        store.read_plan_definition(world.run.run_id)


def test_a_corrupt_jobs_table_is_a_storage_error(store, world):
    store.ensure_plan(world.plan)
    store.jobs_path(world.run.run_id).write_bytes(b"not parquet at all")
    with pytest.raises(StorageError, match="unreadable parquet"):
        store.read_plan(world.run.run_id)


def test_an_edited_job_list_fails_its_manifest_hash(store, world):
    """plan.json vouches for jobs.parquet; editing one job must break that.

    The edit keeps the job count and every uniqueness rule intact, so the only
    thing that can catch it is the recomputed manifest hash.
    """
    store.ensure_plan(world.plan)
    last = world.plan.jobs[-1]
    tampered = replace(
        last, job=replace(last.job, pair_id=PairId(f"{last.job.pair_id}_edited"))
    )
    forged = replace(world.plan, jobs=world.plan.jobs[:-1] + (tampered,))

    store.jobs_path(world.run.run_id).unlink()
    store._write_jobs(forged)  # noqa: SLF001 - deliberately forging damage

    with pytest.raises(StorageError, match="job manifest hash"):
        store.read_plan(world.run.run_id)


def test_a_truncated_job_list_fails_the_declared_count(store, world):
    store.ensure_plan(world.plan)
    truncated = replace(
        world.plan,
        definition=_definition_for(
            world.plan.definition, total_jobs=world.plan.total_jobs - 1
        ),
        jobs=world.plan.jobs[:-1],
    )
    store.jobs_path(world.run.run_id).unlink()
    store._write_jobs(truncated)  # noqa: SLF001 - deliberately forging damage

    with pytest.raises(StorageError, match="inconsistent"):
        store.read_plan(world.run.run_id)


def test_two_runs_keep_separate_plans(tmp_path):
    first = build_world(tmp_path / "a", subjects=1, fingers=2)
    second = build_world(tmp_path / "b", subjects=2, fingers=2)
    first.plan_store.ensure_plan(first.plan)
    second.plan_store.ensure_plan(second.plan)
    assert first.plan_store.read_plan(first.run.run_id).total_jobs == 8
    assert second.plan_store.read_plan(second.run.run_id).total_jobs == 16


def _definition_for(definition: ExecutionPlanDefinition, *, total_jobs: int):
    """A definition with a reduced job count, keeping the counts consistent."""
    stages = dict(definition.stage_counts)
    for key in list(stages):
        if stages[key] > 0:
            stages[key] -= 1
            break
    releases = dict(definition.release_counts)
    for key in list(releases):
        if releases[key] > 0:
            releases[key] -= 1
            break
    return replace(
        definition,
        total_jobs=total_jobs,
        stage_counts=stages,
        release_counts=releases,
    )
