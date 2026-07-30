"""How far a run has got, recomputed from the files that prove it.

There is no counter. Progress is derived every time it is asked for, from the
immutable plan and the result files actually present on disk, because a counter
can say "5,000 done" while 4,999 files exist and nothing about the counter would
reveal the difference (docs/adr/0012).

This is the cheap question. It reads every stored result once — it has to, to
tell a success from a failure — but it does not compare every field of
provenance. That is :func:`fpbench.execution.audit.audit_run`, and it is the
only thing allowed to conclude that a run is sound. What this function *can*
do is refuse to call a run ``VERIFIED`` without a completion manifest, and drop
straight to ``INVALID`` the moment something does not add up.
"""

from __future__ import annotations

import datetime as _dt

from fpbench.core.enums import ExecutionStatus, RunState
from fpbench.core.errors import StorageError
from fpbench.core.execution_plan_models import ExecutionPlan
from fpbench.core.result_models import RunDefinition
from fpbench.core.run_state_models import COMPLETION_ID_LENGTH, RunProgress
from fpbench.execution.audit import audit_run
from fpbench.execution.completion import completion_fingerprint_of
from fpbench.storage.result_store import ResultStore

__all__ = ["inspect_run_progress", "PROGRESS_SNAPSHOT_NAME"]

#: Where a cached snapshot goes, under the run's ``derived/`` directory. It may
#: be overwritten and deleted freely; regenerating it costs one pass.
PROGRESS_SNAPSHOT_NAME = "progress.json"


def inspect_run_progress(
    *,
    run: RunDefinition,
    plan: ExecutionPlan,
    result_store: ResultStore,
) -> RunProgress:
    """Recompute the state of ``run`` from its plan and its stored results."""
    planned_ids = plan.job_ids()

    stored = 0
    successful = 0
    failed = 0
    unreadable = 0
    provenance_conflict = False

    for job_id in planned_ids:
        if not result_store.has_raw_result(run.run_id, job_id):
            continue
        stored += 1
        try:
            record = result_store.read_raw_result(run.run_id, job_id)
        except (StorageError, ValueError):
            unreadable += 1
            continue

        # A light provenance check only. It catches results that plainly belong
        # somewhere else; everything subtler is the audit's job.
        if record.run_id != run.run_id or record.job_id != job_id:
            provenance_conflict = True

        if record.status is ExecutionStatus.SUCCESS:
            successful += 1
        else:
            failed += 1

    extra = len(set(result_store.stored_job_ids(run.run_id)) - set(planned_ids))
    completion_present = result_store.has_completion(run.run_id)
    completion_valid = completion_present and _completion_matches(
        run=run, plan=plan, result_store=result_store
    )

    state = _state(
        planned=len(planned_ids),
        stored=stored,
        extra=extra,
        unreadable=unreadable,
        provenance_conflict=provenance_conflict,
        completion_present=completion_present,
        completion_valid=completion_valid,
    )

    return RunProgress(
        run_id=run.run_id,
        plan_id=plan.plan_id,
        state=state,
        planned_jobs=len(planned_ids),
        stored_results=stored,
        successful_results=successful,
        failed_results=failed,
        missing_results=len(planned_ids) - stored,
        extra_results=extra,
        unreadable_results=unreadable,
        completion_manifest_present=completion_present,
        inspected_utc=_dt.datetime.now(_dt.timezone.utc).isoformat(),
    )


def _completion_matches(
    *, run: RunDefinition, plan: ExecutionPlan, result_store: ResultStore
) -> bool:
    """Whether the stored completion manifest actually describes this run and plan.

    A manifest naming a different plan is worse than no manifest: it would let a
    stale verification vouch for results it never saw.
    """
    try:
        completion = result_store.read_completion(run.run_id)
        expected_fingerprint = completion_fingerprint_of(completion)
        expected_id = f"completion_{expected_fingerprint[:COMPLETION_ID_LENGTH]}"
        if completion.completion_fingerprint != expected_fingerprint:
            return False
        if completion.completion_id != expected_id:
            return False
        if not (
            completion.run_id == run.run_id
            and completion.run_fingerprint == run.run_fingerprint
            and completion.plan_id == plan.plan_id
            and completion.plan_fingerprint == plan.definition.plan_fingerprint
            and completion.pair_manifest_hash == run.pair_manifest_hash
            and completion.planned_jobs == plan.total_jobs
            and bool(completion.completed_utc.strip())
        ):
            return False
        audit = audit_run(run=run, plan=plan, result_store=result_store)
    except (StorageError, ValueError):
        return False
    return (
        audit.is_clean
        and audit.audit_fingerprint == completion.audit_fingerprint
        and audit.valid_results == completion.planned_jobs
        and audit.success_count == completion.success_count
        and audit.failure_count == completion.failure_count
    )


def _state(
    *,
    planned: int,
    stored: int,
    extra: int,
    unreadable: int,
    provenance_conflict: bool,
    completion_present: bool,
    completion_valid: bool,
) -> RunState:
    if (
        extra
        or unreadable
        or provenance_conflict
        or (completion_present and not completion_valid)
    ):
        return RunState.INVALID
    if completion_valid:
        return RunState.VERIFIED
    if stored == 0:
        return RunState.PLANNED
    if stored < planned:
        return RunState.PARTIAL
    return RunState.COMPLETE
