"""Who is allowed to declare a run finished.

The executor knows about plans, jobs and result files. It does not know that a
runtime bundle exists, and it must not learn: a batch loop that had to
understand provenance would be a batch loop that could get provenance wrong.

So a research run takes the decision away from it. ``finalize=False`` means the
executor may find every result present and still not write a completion —
somebody else revalidates the executable and the source revision first
(docs/adr/0020). The default stays ``True``, and every stage 3B behaviour has
to survive that unchanged.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fpbench.core.enums import RunState
from fpbench.core.errors import ProcessTreeTerminationError, RuntimeDriftError
from fpbench.execution.progress import inspect_run_progress
from runworld import build_world


@pytest.fixture
def world(tmp_path: Path):
    return build_world(tmp_path)


# ------------------------------------------------------- unchanged behaviour


def test_the_default_still_audits_and_completes(world):
    summary = world.executor().execute()
    assert summary.completed and summary.verified
    assert world.result_store.has_completion(world.run.run_id)


def test_asking_for_it_explicitly_is_the_same(tmp_path):
    world = build_world(tmp_path)
    summary = world.executor().execute(finalize=True)
    assert summary.completed and summary.verified
    assert world.result_store.has_completion(world.run.run_id)


def test_a_partial_run_is_unaffected_by_the_flag(tmp_path):
    world = build_world(tmp_path)
    summary = world.executor().execute(max_new_jobs=2, finalize=False)
    assert not summary.completed
    assert summary.remaining_jobs == world.plan.total_jobs - 2
    assert not world.result_store.has_completion(world.run.run_id)


# ------------------------------------------------------ external finalisation


def test_all_results_present_but_not_verified(world):
    summary = world.executor().execute(finalize=False)

    assert summary.completed
    assert not summary.verified
    assert summary.remaining_jobs == 0
    assert not world.result_store.has_completion(world.run.run_id)


def test_the_run_reads_as_complete_rather_than_verified(world):
    world.executor().execute(finalize=False)
    progress = inspect_run_progress(
        run=world.run, plan=world.plan, result_store=world.result_store
    )
    assert progress.state is RunState.COMPLETE
    assert progress.missing_results == 0


def test_an_external_finalizer_can_still_complete_it_afterwards(world):
    world.executor().execute(finalize=False)
    report, completion = world.completion_service.finalise(
        run=world.run, plan=world.plan
    )

    assert report.is_clean
    assert completion.planned_jobs == world.plan.total_jobs
    assert inspect_run_progress(
        run=world.run, plan=world.plan, result_store=world.result_store
    ).state is RunState.VERIFIED


def test_resuming_an_unfinalised_run_repeats_no_work(world):
    first = world.executor().execute(finalize=False)
    second = world.executor().execute(finalize=False)

    assert first.newly_executed_jobs == world.plan.total_jobs
    assert second.newly_executed_jobs == 0
    assert second.skipped_existing_jobs == world.plan.total_jobs
    assert second.completed and not second.verified


# --------------------------------------------------------------- fatal drift


class _DriftingAdapter:
    """Delegates until the ``after``-th comparison, then reports drift.

    Wraps a real adapter rather than replacing it, because a resumed run must
    preflight against a descriptor that matches the run definition exactly.
    """

    def __init__(self, delegate, *, after: int) -> None:
        self._delegate = delegate
        self.after = after
        self.compare_calls = 0

    @property
    def descriptor(self):
        return self._delegate.descriptor

    def validate_environment(self):
        return self._delegate.validate_environment()

    def compare(self, left, right, context):
        self.compare_calls += 1
        if self.compare_calls > self.after:
            raise RuntimeDriftError("the pinned jar was replaced mid-run")
        return self._delegate.compare(left, right, context)


def test_runtime_drift_stops_the_executor_immediately(tmp_path):
    world = build_world(tmp_path)
    drifting = _DriftingAdapter(world.adapter, after=3)

    with pytest.raises(RuntimeDriftError):
        world.executor(job_runner=_runner(world, drifting)).execute()

    assert drifting.compare_calls == 4
    stored = world.result_store.stored_job_ids(world.run.run_id)
    assert len(stored) == 3, "the drifting job must not have produced a result"


def test_runtime_drift_writes_no_completion_and_no_result_set(tmp_path):
    world = build_world(tmp_path)
    with pytest.raises(RuntimeDriftError):
        world.executor(job_runner=_runner(world, _DriftingAdapter(world.adapter, after=1))).execute()

    assert not world.result_store.has_completion(world.run.run_id)
    assert not world.result_set_store.has_result_set(world.run.run_id)
    assert not world.result_store.has_research_receipt(world.run.run_id)


def test_runtime_drift_is_never_recorded_as_a_comparison_failure(tmp_path):
    world = build_world(tmp_path)
    with pytest.raises(RuntimeDriftError):
        world.executor(job_runner=_runner(world, _DriftingAdapter(world.adapter, after=2))).execute()

    for record in world.result_store.iter_raw_results(world.run.run_id):
        assert record.failure is None, "drift must not become an INTERNAL_ERROR row"


def test_uncertain_process_tree_termination_is_fatal_and_unrecorded(tmp_path):
    world = build_world(tmp_path)

    class _UncertainTermination(_DriftingAdapter):
        def compare(self, left, right, context):
            raise ProcessTreeTerminationError("a descendant may still be alive")

    with pytest.raises(ProcessTreeTerminationError):
        world.executor(
            job_runner=_runner(world, _UncertainTermination(world.adapter, after=0))
        ).execute()

    assert world.result_store.stored_job_ids(world.run.run_id) == ()


def _runner(world, adapter):
    from fpbench.execution.runner import SingleJobRunner

    return SingleJobRunner(
        run=world.run,
        adapter=adapter,
        preparer=world.preparer,
        result_store=world.result_store,
        dataset_root=world.dataset_root,
        image_index=world.images,
        workspace_root=world.workspace,
    )
