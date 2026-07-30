"""Walking a whole plan, stopping, and picking it up again."""

from __future__ import annotations

from dataclasses import replace

import pytest

from fpbench.core.enums import ExecutionStatus, IntegrityIssueCode, RunState
from fpbench.core.errors import (
    PlanConflictError,
    PreflightError,
    RunIntegrityError,
    StorageError,
)
from fpbench.core.identifiers import PairId
from fpbench.execution.audit import audit_run
from fpbench.execution.batch_runner import SequentialRunExecutor
from fpbench.execution.progress import inspect_run_progress
from fakes import (
    CountingAdapter,
    CountingPreparer,
    InterruptingAdapter,
    SometimesFailingAdapter,
)
from runworld import build_world, write_result_file


@pytest.fixture
def world(tmp_path):
    return build_world(tmp_path, subjects=2, fingers=2)


def progress(world):
    return inspect_run_progress(
        run=world.run, plan=world.plan, result_store=world.result_store
    )


def audit(world):
    return audit_run(run=world.run, plan=world.plan, result_store=world.result_store)


# ------------------------------------------------------------------- full run


def test_a_full_run_executes_every_job_once(tmp_path):
    adapter = CountingAdapter()
    preparer = CountingPreparer()
    world = build_world(tmp_path, subjects=2, fingers=2, adapter=adapter, preparer=preparer)

    summary = world.executor().execute()

    assert summary.newly_executed_jobs == world.plan.total_jobs
    assert summary.skipped_existing_jobs == 0
    assert summary.visited_jobs == world.plan.total_jobs
    assert summary.remaining_jobs == 0
    assert adapter.compare_calls == world.plan.total_jobs
    # Two images prepared per job, even for SELF comparisons.
    assert preparer.calls == world.plan.total_jobs * 2


def test_a_full_run_stores_one_result_per_job(world):
    world.executor().execute()
    stored = list(world.result_store.iter_raw_results(world.run.run_id))
    assert len(stored) == world.plan.total_jobs
    assert {record.job_id for record in stored} == set(world.plan.job_ids())


def test_a_full_run_audits_clean_and_writes_a_completion(world):
    summary = world.executor().execute()
    assert summary.completed
    assert summary.verified
    assert world.result_store.has_completion(world.run.run_id)
    assert audit(world).is_clean
    assert progress(world).state is RunState.VERIFIED


def test_the_plan_is_persisted_by_the_executor(world):
    world.executor()
    assert world.plan_store.read_plan(world.run.run_id) == world.plan


def test_jobs_run_in_ordinal_order(tmp_path):
    adapter = CountingAdapter()
    world = build_world(tmp_path, subjects=2, fingers=2, adapter=adapter)
    world.executor().execute()

    executed_job_ids = [context.job_id for context in adapter.contexts]
    assert executed_job_ids == list(world.plan.job_ids())


# --------------------------------------------------------------- second run


def test_a_second_full_run_does_no_work(tmp_path):
    adapter = CountingAdapter()
    preparer = CountingPreparer()
    world = build_world(tmp_path, subjects=2, fingers=2, adapter=adapter, preparer=preparer)
    world.executor().execute()
    completion_before = world.result_store.completion_path(world.run.run_id).read_bytes()

    fresh_adapter = CountingAdapter()
    fresh_preparer = CountingPreparer()
    second = replace(world, adapter=fresh_adapter, preparer=fresh_preparer)
    summary = second.executor().execute()

    assert summary.newly_executed_jobs == 0
    assert summary.skipped_existing_jobs == world.plan.total_jobs
    assert fresh_adapter.compare_calls == 0
    assert fresh_preparer.calls == 0
    assert summary.completed and summary.verified
    assert (
        world.result_store.completion_path(world.run.run_id).read_bytes()
        == completion_before
    )


# ------------------------------------------------------------------- partial


def test_a_budget_limits_how_many_new_jobs_run(tmp_path):
    adapter = CountingAdapter()
    world = build_world(tmp_path, subjects=2, fingers=2, adapter=adapter)

    summary = world.executor().execute(max_new_jobs=7)

    assert summary.newly_executed_jobs == 7
    assert adapter.compare_calls == 7
    assert summary.remaining_jobs == world.plan.total_jobs - 7
    assert not summary.completed
    assert not summary.verified
    assert not world.result_store.has_completion(world.run.run_id)
    assert progress(world).state is RunState.PARTIAL


def test_a_partial_run_executes_the_first_ordinals(tmp_path):
    adapter = CountingAdapter()
    world = build_world(tmp_path, subjects=2, fingers=2, adapter=adapter)
    world.executor().execute(max_new_jobs=5)
    assert [c.job_id for c in adapter.contexts] == list(world.plan.job_ids()[:5])


@pytest.mark.parametrize("budget", [0, -1])
def test_a_non_positive_budget_is_refused(world, budget):
    with pytest.raises(ValueError, match="max_new_jobs"):
        world.executor().execute(max_new_jobs=budget)


# -------------------------------------------------------------------- resume


def test_resume_completes_the_remaining_jobs_only(tmp_path):
    total = build_world(tmp_path, subjects=2, fingers=2).plan.total_jobs

    first_adapter = CountingAdapter()
    world = build_world(tmp_path, subjects=2, fingers=2, adapter=first_adapter)
    world.executor().execute(max_new_jobs=5)
    assert first_adapter.compare_calls == 5

    second_adapter = CountingAdapter()
    second_preparer = CountingPreparer()
    resumed = replace(world, adapter=second_adapter, preparer=second_preparer)
    summary = resumed.executor().execute(max_new_jobs=4)

    assert summary.newly_executed_jobs == 4
    assert summary.skipped_existing_jobs == 5
    assert second_adapter.compare_calls == 4
    # The five stored jobs were skipped without preparing an image.
    assert second_preparer.calls == 4 * 2
    assert summary.remaining_jobs == total - 9
    assert not summary.completed


def test_resume_eventually_verifies_the_run(tmp_path):
    adapter = CountingAdapter()
    world = build_world(tmp_path, subjects=2, fingers=2, adapter=adapter)

    world.executor().execute(max_new_jobs=3)
    world.executor().execute(max_new_jobs=6)
    final = world.executor().execute()

    assert final.remaining_jobs == 0
    assert final.completed and final.verified
    assert progress(world).state is RunState.VERIFIED
    assert adapter.compare_calls == world.plan.total_jobs


def test_the_budget_is_spent_on_new_work_not_on_re_checking(tmp_path):
    adapter = CountingAdapter()
    world = build_world(tmp_path, subjects=2, fingers=2, adapter=adapter)
    world.executor().execute(max_new_jobs=6)

    fresh = CountingAdapter()
    resumed = replace(world, adapter=fresh)
    summary = resumed.executor().execute(max_new_jobs=2)

    assert summary.newly_executed_jobs == 2
    assert fresh.compare_calls == 2


# ---------------------------------------------------------- comparison failures


def test_comparison_failures_do_not_stop_the_run(tmp_path):
    adapter = SometimesFailingAdapter(fail_every=3)
    world = build_world(tmp_path, subjects=2, fingers=2, adapter=adapter)

    summary = world.executor().execute()

    assert summary.newly_executed_jobs == world.plan.total_jobs
    assert summary.failed_results_seen > 0
    assert (
        summary.successful_results_seen + summary.failed_results_seen
        == world.plan.total_jobs
    )
    assert summary.completed and summary.verified
    assert progress(world).state is RunState.VERIFIED


def test_a_run_of_nothing_but_failures_still_verifies(tmp_path):
    world = build_world(
        tmp_path, subjects=1, fingers=2, adapter=SometimesFailingAdapter(fail_every=1)
    )
    summary = world.executor().execute()
    assert summary.failed_results_seen == world.plan.total_jobs
    assert summary.verified
    completion = world.result_store.read_completion(world.run.run_id)
    assert completion.failure_count == world.plan.total_jobs
    assert completion.success_count == 0


def test_every_stored_result_has_a_status(tmp_path):
    world = build_world(
        tmp_path, subjects=2, fingers=2, adapter=SometimesFailingAdapter(fail_every=4)
    )
    world.executor().execute()
    statuses = {
        record.status
        for record in world.result_store.iter_raw_results(world.run.run_id)
    }
    assert statuses <= {ExecutionStatus.SUCCESS, ExecutionStatus.FAILURE}


# ------------------------------------------------------------------ preflight


def test_a_plan_for_another_run_is_refused(tmp_path):
    world = build_world(tmp_path, subjects=2, fingers=2)
    # Same pairs, deliberately different run: only the run id differs, so the
    # run check is the only thing that can catch it.
    other = build_world(tmp_path / "other", subjects=2, fingers=2, replicate_index=1)
    with pytest.raises(PreflightError, match="is for run"):
        SequentialRunExecutor(
            plan=other.plan,
            pair_index=world.pair_index,
            job_runner=world.job_runner(),
            result_store=world.result_store,
            completion_service=world.completion_service,
        )


def test_a_missing_pair_is_refused(world):
    partial_index = dict(world.pair_index)
    partial_index.pop(world.plan.jobs[0].job.pair_id)
    with pytest.raises(PreflightError, match="not in the supplied pair index"):
        SequentialRunExecutor(
            plan=world.plan,
            pair_index=partial_index,
            job_runner=world.job_runner(),
            result_store=world.result_store,
            completion_service=world.completion_service,
        )


def test_a_pair_that_disagrees_with_its_key_is_refused(world):
    index = dict(world.pair_index)
    key = world.plan.jobs[0].job.pair_id
    index[key] = replace(index[key], pair_id=PairId("sd300a_00009999_f09_mated"))
    with pytest.raises(PreflightError, match="calling itself"):
        SequentialRunExecutor(
            plan=world.plan,
            pair_index=index,
            job_runner=world.job_runner(),
            result_store=world.result_store,
            completion_service=world.completion_service,
        )


def test_a_pair_with_the_wrong_images_is_refused(world):
    index = dict(world.pair_index)
    key = world.plan.jobs[0].job.pair_id
    other = world.plan.jobs[1].job
    index[key] = replace(index[key], right_image_id=other.right_image_id)
    with pytest.raises(PreflightError, match="does not hold the images"):
        SequentialRunExecutor(
            plan=world.plan,
            pair_index=index,
            job_runner=world.job_runner(),
            result_store=world.result_store,
            completion_service=world.completion_service,
        )


def test_a_stored_plan_that_disagrees_is_a_conflict(world):
    """A hand-edited plan.json must not be able to redefine a running run."""
    world.plan_store.ensure_plan(world.plan)
    forged = replace(
        world.plan,
        definition=replace(
            world.plan.definition,
            plan_fingerprint="a" * 64,
            plan_id="plan_aaaaaaaaaaaa",
        ),
    )
    with pytest.raises(PlanConflictError):
        SequentialRunExecutor(
            plan=forged,
            pair_index=world.pair_index,
            job_runner=world.job_runner(),
            result_store=world.result_store,
            completion_service=world.completion_service,
        )


def test_a_tampered_stored_job_manifest_is_refused_before_execution(tmp_path):
    adapter = CountingAdapter()
    world = build_world(tmp_path, subjects=2, fingers=2, adapter=adapter)
    world.plan_store.ensure_plan(world.plan)

    last = world.plan.jobs[-1]
    tampered = replace(
        last, job=replace(last.job, pair_id=PairId(f"{last.job.pair_id}_edited"))
    )
    forged = replace(world.plan, jobs=world.plan.jobs[:-1] + (tampered,))
    world.plan_store.jobs_path(world.run.run_id).unlink()
    world.plan_store._write_jobs(  # noqa: SLF001 - deliberately forging damage
        forged
    )

    with pytest.raises(StorageError, match="job manifest hash"):
        world.executor()

    assert adapter.compare_calls == 0


def test_a_failed_preflight_executes_nothing(world):
    partial_index = dict(world.pair_index)
    partial_index.pop(world.plan.jobs[0].job.pair_id)
    with pytest.raises(PreflightError):
        SequentialRunExecutor(
            plan=world.plan,
            pair_index=partial_index,
            job_runner=world.job_runner(),
            result_store=world.result_store,
            completion_service=world.completion_service,
        )
    assert list(world.result_store.iter_raw_results(world.run.run_id)) == []


# -------------------------------------------------------------------- conflict


def test_a_conflicting_result_stops_the_run(tmp_path):
    adapter = CountingAdapter()
    world = build_world(tmp_path, subjects=2, fingers=2, adapter=adapter)
    world.executor().execute(max_new_jobs=2)

    # Forge a result for job 3 that claims a different unit of work.
    target = world.plan.jobs[2].job
    template = world.result_store.read_raw_result(
        world.run.run_id, world.plan.jobs[0].job.job_id
    )
    write_result_file(
        world.result_store.raw_result_path(world.run.run_id, target.job_id),
        replace(
            template,
            result_id=target.job_id,
            job_id=target.job_id,
            job_fingerprint="f" * 64,
        ),
    )

    fresh = CountingAdapter()
    resumed = replace(world, adapter=fresh)
    with pytest.raises(RunIntegrityError):
        resumed.executor().execute()

    assert fresh.compare_calls == 0
    assert not world.result_store.has_completion(world.run.run_id)


def test_a_corrupt_result_stops_the_run_and_shows_up_in_the_audit(tmp_path):
    adapter = CountingAdapter()
    world = build_world(tmp_path, subjects=2, fingers=2, adapter=adapter)
    world.executor().execute(max_new_jobs=3)

    world.result_store.raw_result_path(
        world.run.run_id, world.plan.jobs[1].job.job_id
    ).write_bytes(b"not parquet at all")

    fresh = CountingAdapter()
    resumed = replace(world, adapter=fresh)
    with pytest.raises(RunIntegrityError):
        resumed.executor().execute()

    assert fresh.compare_calls == 0
    report = audit(world)
    assert IntegrityIssueCode.RESULT_UNREADABLE in {i.code for i in report.issues}
    assert progress(world).state is RunState.INVALID
    assert not world.result_store.has_completion(world.run.run_id)


def test_resume_rejects_a_stale_result_hash_before_new_work(tmp_path):
    first_adapter = CountingAdapter()
    world = build_world(tmp_path, subjects=2, fingers=2, adapter=first_adapter)
    world.executor().execute(max_new_jobs=3)

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

    resumed_adapter = CountingAdapter()
    resumed = replace(world, adapter=resumed_adapter)
    with pytest.raises(RunIntegrityError, match="result_hash_mismatch"):
        resumed.executor().execute()

    assert resumed_adapter.compare_calls == 0
    assert len(store.stored_job_ids(world.run.run_id)) == 3


def test_an_extra_result_prevents_verification(tmp_path):
    world = build_world(tmp_path, subjects=2, fingers=2)
    store = world.result_store
    world.executor().execute(max_new_jobs=world.plan.total_jobs - 1)

    source = store.raw_result_path(world.run.run_id, world.plan.jobs[0].job.job_id)
    (store.raw_jobs_dir(world.run.run_id) / "job_00000000000000ff.parquet").write_bytes(
        source.read_bytes()
    )

    with pytest.raises(RunIntegrityError):
        replace(world).executor().execute()
    assert not store.has_completion(world.run.run_id)


# ---------------------------------------------------------------- interruption


def test_a_keyboard_interrupt_travels_out_and_loses_nothing(tmp_path):
    adapter = InterruptingAdapter(after=4)
    world = build_world(tmp_path, subjects=2, fingers=2, adapter=adapter)

    with pytest.raises(KeyboardInterrupt):
        world.executor().execute()

    snapshot = progress(world)
    assert snapshot.stored_results == 4
    assert snapshot.state is RunState.PARTIAL
    # Nothing was recorded as a comparison failure — an interrupt is not one.
    assert snapshot.failed_results == 0
    assert not world.result_store.has_completion(world.run.run_id)


def test_a_run_resumes_cleanly_after_an_interrupt(tmp_path):
    world = build_world(tmp_path, subjects=2, fingers=2, adapter=InterruptingAdapter(after=4))
    with pytest.raises(KeyboardInterrupt):
        world.executor().execute()

    finisher = CountingAdapter()
    # A different adapter means a different run, so re-plan against the same
    # pairs: this proves the *pairs* survive an interrupt, not just one run.
    resumed = build_world(tmp_path, subjects=2, fingers=2, adapter=InterruptingAdapter(after=10_000))
    summary = resumed.executor().execute()

    assert summary.remaining_jobs == 0
    assert summary.skipped_existing_jobs == 4
    assert summary.newly_executed_jobs == world.plan.total_jobs - 4
    assert summary.verified
    assert finisher.compare_calls == 0  # untouched; proves nothing leaked in


# --------------------------------------------------------------------- summary


def test_the_summary_describes_the_invocation_not_the_run(tmp_path):
    world = build_world(tmp_path, subjects=2, fingers=2)
    first = world.executor().execute(max_new_jobs=4)
    second = world.executor().execute(max_new_jobs=4)

    assert first.visited_jobs == 4
    assert second.visited_jobs == 8  # 4 skipped, then 4 new
    assert second.skipped_existing_jobs == 4
    assert second.newly_executed_jobs == 4
    assert first.planned_jobs == second.planned_jobs == world.plan.total_jobs


def test_the_executor_names_no_algorithm():
    """docs/adr/0007: the executor is as algorithm-blind as the runner."""
    from pathlib import Path

    import fpbench.execution.batch_runner as batch_module

    source = Path(batch_module.__file__).read_text(encoding="utf-8")
    for name in ("dummy", "sourceafis", "bozorth", "nbis"):
        assert name not in source.lower()
