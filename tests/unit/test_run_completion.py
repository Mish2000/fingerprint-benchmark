"""A run becomes VERIFIED once, on the strength of one clean audit."""

from __future__ import annotations

from dataclasses import replace

import pytest

from fpbench.core.errors import (
    IncompleteRunError,
    ResultConflictError,
    RunIntegrityError,
    StorageError,
)
from fpbench.core.run_state_models import RunCompletion
from fpbench.execution.audit import audit_run
from fpbench.execution.completion import (
    build_run_completion,
    completion_fingerprint_of,
)
from fakes import SometimesFailingAdapter
from runworld import build_world


@pytest.fixture
def world(tmp_path):
    return build_world(tmp_path, subjects=2, fingers=2)


def execute_all(world, *, count=None):
    runner = world.job_runner()
    for planned in world.plan.jobs[:count]:
        runner.execute(planned.job, world.pair_index[planned.job.pair_id])
    return world


def audit(world):
    return audit_run(run=world.run, plan=world.plan, result_store=world.result_store)


# ------------------------------------------------------------------- building


def test_a_clean_finished_run_produces_a_completion(world):
    execute_all(world)
    completion = build_run_completion(
        run=world.run, plan=world.plan, audit=audit(world)
    )
    assert completion.run_id == world.run.run_id
    assert completion.plan_id == world.plan.plan_id
    assert completion.planned_jobs == world.plan.total_jobs
    assert completion.success_count == world.plan.total_jobs
    assert completion.failure_count == 0
    assert completion.completion_id == f"completion_{completion.completion_fingerprint[:12]}"
    assert completion_fingerprint_of(completion) == completion.completion_fingerprint


def test_a_completion_names_the_audit_it_rests_on(world):
    execute_all(world)
    report = audit(world)
    completion = build_run_completion(run=world.run, plan=world.plan, audit=report)
    assert completion.audit_fingerprint == report.audit_fingerprint


def test_a_run_full_of_failures_can_still_complete(tmp_path):
    """docs/adr/0013: failures are results, and a run of them is finished."""
    world = build_world(
        tmp_path, subjects=2, fingers=2, adapter=SometimesFailingAdapter(fail_every=1)
    )
    execute_all(world)
    completion = build_run_completion(
        run=world.run, plan=world.plan, audit=audit(world)
    )
    assert completion.failure_count == world.plan.total_jobs
    assert completion.success_count == 0


def test_an_unfinished_run_cannot_complete(world):
    execute_all(world, count=3)
    with pytest.raises(RunIntegrityError, match="missing"):
        build_run_completion(run=world.run, plan=world.plan, audit=audit(world))


def test_a_run_with_an_extra_result_cannot_complete(world):
    execute_all(world)
    store = world.result_store
    source = store.raw_result_path(world.run.run_id, world.plan.jobs[0].job.job_id)
    (store.raw_jobs_dir(world.run.run_id) / "job_00000000000000ff.parquet").write_bytes(
        source.read_bytes()
    )
    with pytest.raises(RunIntegrityError):
        build_run_completion(run=world.run, plan=world.plan, audit=audit(world))


def test_a_run_with_a_damaged_result_cannot_complete(world):
    execute_all(world)
    store = world.result_store
    store.raw_result_path(
        world.run.run_id, world.plan.jobs[0].job.job_id
    ).write_bytes(b"not parquet")
    with pytest.raises(RunIntegrityError):
        build_run_completion(run=world.run, plan=world.plan, audit=audit(world))


def test_the_completion_accounts_for_every_planned_job():
    """The model itself refuses a total that does not add up."""
    with pytest.raises(ValueError, match="accounts for every planned job"):
        RunCompletion(
            completion_id="completion_abc123abc123",
            completion_fingerprint="a" * 64,
            run_id="run_abc123abc123",
            run_fingerprint="b" * 64,
            plan_id="plan_abc123abc123",
            plan_fingerprint="c" * 64,
            pair_manifest_hash="d" * 64,
            audit_fingerprint="e" * 64,
            planned_jobs=10,
            success_count=4,
            failure_count=4,
            completed_utc="2026-07-30T00:00:00+00:00",
        )


# ------------------------------------------------------------------ finalising


def test_finalise_writes_the_manifest_where_documented(world):
    execute_all(world)
    world.completion_service.finalise(run=world.run, plan=world.plan)
    path = world.result_store.completion_path(world.run.run_id)
    assert path == world.workspace / "results" / world.run.run_id / "completion.json"
    assert path.is_file()


def test_finalising_twice_is_a_no_op(world):
    execute_all(world)
    world.completion_service.finalise(run=world.run, plan=world.plan)
    before = world.result_store.completion_path(world.run.run_id).read_bytes()
    world.completion_service.finalise(run=world.run, plan=world.plan)
    assert world.result_store.completion_path(world.run.run_id).read_bytes() == before


def test_a_different_completion_under_the_same_run_conflicts(world):
    execute_all(world)
    _, completion = world.completion_service.finalise(run=world.run, plan=world.plan)
    impostor = replace(
        completion,
        completion_fingerprint="f" * 64,
        completion_id="completion_ffffffffffff",
    )
    with pytest.raises(ResultConflictError):
        world.result_store.ensure_completion(impostor)


def test_finalise_refuses_a_run_that_does_not_audit_clean(world):
    execute_all(world, count=3)
    with pytest.raises(RunIntegrityError):
        world.completion_service.finalise(run=world.run, plan=world.plan)
    assert not world.result_store.has_completion(world.run.run_id)


def test_the_completion_round_trips(world):
    execute_all(world)
    _, completion = world.completion_service.finalise(run=world.run, plan=world.plan)
    assert world.result_store.read_completion(world.run.run_id) == completion


def test_reading_an_absent_completion_is_a_storage_error(world):
    with pytest.raises(StorageError, match="completion manifest not found"):
        world.result_store.read_completion(world.run.run_id)


def test_a_corrupt_completion_is_a_storage_error(world):
    execute_all(world)
    world.completion_service.finalise(run=world.run, plan=world.plan)
    world.result_store.completion_path(world.run.run_id).write_text(
        "{}", encoding="utf-8"
    )
    with pytest.raises(StorageError, match="unreadable completion manifest"):
        world.result_store.read_completion(world.run.run_id)


def test_the_store_offers_no_way_to_overwrite_a_completion():
    import inspect

    from fpbench.storage.result_store import ResultStore

    signature = inspect.signature(ResultStore.ensure_completion)
    assert "overwrite" not in signature.parameters
    assert "force" not in signature.parameters


def test_an_incomplete_audit_raises_the_incomplete_error(world, monkeypatch):
    """A clean audit that still lacks results is a distinct failure mode."""
    execute_all(world)
    report = audit(world)
    shrunken = replace(report, valid_results=report.valid_results - 1)
    with pytest.raises(IncompleteRunError):
        build_run_completion(run=world.run, plan=world.plan, audit=shrunken)
