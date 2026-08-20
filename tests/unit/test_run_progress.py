"""Progress is whatever the files say, and nothing else."""

from __future__ import annotations

from dataclasses import replace

import pytest

from fpbench.core.enums import RunState
from fpbench.core.json_io import write_json
from fpbench.execution.progress import inspect_run_progress
from fpbench.execution.runner import SingleJobRunner
from fakes import SometimesFailingAdapter
from runworld import build_world, write_result_file


@pytest.fixture
def world(tmp_path):
    return build_world(tmp_path, subjects=2, fingers=2)


def progress(world):
    return inspect_run_progress(
        run=world.run, plan=world.plan, result_store=world.result_store
    )


def run_jobs(world, count: int | None = None) -> SingleJobRunner:
    runner = world.job_runner()
    for planned in world.plan.jobs[: count if count is not None else None]:
        runner.execute(planned.job, world.pair_index[planned.job.pair_id])
    return runner


# --------------------------------------------------------------------- states


def test_no_results_means_planned(world):
    world.plan_store.ensure_plan(world.plan)
    world.job_runner()  # writes the run manifest, no results
    snapshot = progress(world)
    assert snapshot.state is RunState.PLANNED
    assert snapshot.stored_results == 0
    assert snapshot.missing_results == world.plan.total_jobs


def test_some_results_means_partial(world):
    run_jobs(world, 3)
    snapshot = progress(world)
    assert snapshot.state is RunState.PARTIAL
    assert snapshot.stored_results == 3
    assert snapshot.missing_results == world.plan.total_jobs - 3


def test_all_results_without_a_completion_manifest_means_complete(world):
    run_jobs(world)
    snapshot = progress(world)
    assert snapshot.state is RunState.COMPLETE
    assert snapshot.missing_results == 0
    assert not snapshot.completion_manifest_present


def test_a_clean_completion_means_verified(world):
    run_jobs(world)
    world.completion_service.finalise(run=world.run, plan=world.plan)
    snapshot = progress(world)
    assert snapshot.state is RunState.VERIFIED
    assert snapshot.completion_manifest_present


def test_an_extra_result_means_invalid(world):
    run_jobs(world)
    stray = world.result_store.raw_jobs_dir(world.run.run_id) / "job_00000000000000ff.parquet"
    stray.write_bytes(
        world.result_store.raw_result_path(
            world.run.run_id, world.plan.jobs[0].job.job_id
        ).read_bytes()
    )
    snapshot = progress(world)
    assert snapshot.state is RunState.INVALID
    assert snapshot.extra_results == 1


def test_a_corrupt_result_means_invalid(world):
    run_jobs(world)
    path = world.result_store.raw_result_path(
        world.run.run_id, world.plan.jobs[0].job.job_id
    )
    path.write_bytes(b"not parquet")
    snapshot = progress(world)
    assert snapshot.state is RunState.INVALID
    assert snapshot.unreadable_results == 1


def test_a_completion_manifest_for_another_plan_does_not_verify(world, tmp_path):
    """A stale manifest must not vouch for results it never saw."""
    run_jobs(world)
    world.completion_service.finalise(run=world.run, plan=world.plan)

    other = build_world(tmp_path / "other", subjects=1, fingers=2)
    snapshot = inspect_run_progress(
        run=world.run, plan=other.plan, result_store=world.result_store
    )
    assert snapshot.state is not RunState.VERIFIED


def test_changed_results_after_completion_make_progress_invalid(world):
    run_jobs(world)
    world.completion_service.finalise(run=world.run, plan=world.plan)

    job = world.plan.jobs[0].job
    store = world.result_store
    record = store.read_raw_result(world.run.run_id, job.job_id)
    stale_hash = store.raw_result_metadata(world.run.run_id, job.job_id)[
        "result_hash"
    ]
    write_result_file(
        store.raw_result_path(world.run.run_id, job.job_id),
        replace(record, raw_score=record.raw_score + 1.0),
        metadata={"result_hash": stale_hash},
    )

    snapshot = progress(world)
    assert snapshot.completion_manifest_present
    assert snapshot.state is RunState.INVALID


def test_a_tampered_completion_fingerprint_makes_progress_invalid(world):
    run_jobs(world)
    world.completion_service.finalise(run=world.run, plan=world.plan)
    completion = world.result_store.read_completion(world.run.run_id)
    write_json(
        world.result_store.completion_path(world.run.run_id),
        replace(completion, completion_fingerprint="0" * 64),
    )

    snapshot = progress(world)
    assert snapshot.completion_manifest_present
    assert snapshot.state is RunState.INVALID


# --------------------------------------------------------------------- counts


def test_success_and_failure_counts_are_taken_from_the_results(tmp_path):
    adapter = SometimesFailingAdapter(fail_every=3)
    world = build_world(tmp_path, subjects=2, fingers=2, adapter=adapter)
    run_jobs(world)

    snapshot = progress(world)
    assert snapshot.stored_results == world.plan.total_jobs
    assert snapshot.successful_results + snapshot.failed_results == snapshot.stored_results
    assert snapshot.failed_results > 0


def test_comparison_failures_do_not_make_a_run_invalid(tmp_path):
    """docs/adr/0013: a failed comparison is a result, not a broken run."""
    world = build_world(
        tmp_path, subjects=2, fingers=2, adapter=SometimesFailingAdapter(fail_every=1)
    )
    run_jobs(world)
    snapshot = progress(world)
    assert snapshot.failed_results == world.plan.total_jobs
    assert snapshot.successful_results == 0
    assert snapshot.state is RunState.COMPLETE


def test_every_planned_job_is_either_stored_or_missing(world):
    run_jobs(world, 5)
    snapshot = progress(world)
    assert snapshot.stored_results + snapshot.missing_results == snapshot.planned_jobs


def test_progress_is_recomputed_not_remembered(world):
    """Deleting a result must move the state backwards (docs/adr/0012)."""
    run_jobs(world)
    assert progress(world).state is RunState.COMPLETE

    world.result_store.raw_result_path(
        world.run.run_id, world.plan.jobs[0].job.job_id
    ).unlink()
    snapshot = progress(world)
    assert snapshot.state is RunState.PARTIAL
    assert snapshot.missing_results == 1


def test_a_cached_snapshot_may_be_overwritten(world):
    """Derived artefacts are disposable by design."""
    run_jobs(world, 2)
    first = world.result_store.write_derived(
        world.run.run_id, "progress.json", progress(world)
    )
    run_jobs(world)
    second = world.result_store.write_derived(
        world.run.run_id, "progress.json", progress(world)
    )
    assert first == second
    assert second.is_file()
