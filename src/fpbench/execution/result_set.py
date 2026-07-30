"""Turning a finished run into a citable collection of results.

The plan says which comparisons a run owes. The audit says the results on disk
match it. Neither of them produces a *name* for the thing an analysis will
actually consume — and the stage after this one has to be able to write down
"decisions D were derived from result set R" and have that be checkable
(docs/adr/0019).

So this module walks the plan in ordinal order, reads every result, hashes it,
and folds the ordered list into one fingerprint. That is deliberately the
expensive way round: the hashes are re-derived from the files rather than
copied from anywhere, because an index built from a cache would agree with the
cache instead of with the evidence.

The container lives in ``core`` so the storage layer can persist it. The rules
for deriving one live here, and this module re-exports the container so callers
import model and factory from one place.
"""

from __future__ import annotations

import datetime as _dt

from fpbench.core.enums import ExecutionStatus
from fpbench.core.errors import IncompleteRunError, RunIntegrityError
from fpbench.core.execution_plan_models import ExecutionPlan
from fpbench.core.result_models import RunDefinition, raw_result_hash
from fpbench.core.result_set_models import (
    ResultSetEntry,
    ResultSetManifest,
    ordered_results_hash,
    result_set_fingerprint,
    result_set_id,
)
from fpbench.core.runtime_models import RunRuntimeReference
from fpbench.storage.result_store import ResultStore

__all__ = [
    "ResultSetEntry",
    "ResultSetManifest",
    "build_result_set",
]


def build_result_set(
    *,
    run: RunDefinition,
    plan: ExecutionPlan,
    result_store: ResultStore,
    runtime_reference: RunRuntimeReference,
    created_utc: str | None = None,
) -> tuple[ResultSetManifest, tuple[ResultSetEntry, ...]]:
    """Derive the immutable identity of ``run``'s raw results.

    Args:
        runtime_reference: The bundle binding written when the run was
            prepared. Its fingerprint enters the result-set fingerprint, so the
            same pairs scored by two builds of the same matcher cannot produce
            one identity.
        created_utc: Overridable only so that tests can prove it does *not*
            reach the fingerprint.

    Raises:
        IncompleteRunError: some planned job has no stored result.
        RunIntegrityError: the runtime reference does not describe this run, or
            a stored result does not belong to the job that planned it.
    """
    if runtime_reference.run_id != run.run_id:
        raise RunIntegrityError(
            f"runtime reference belongs to run {runtime_reference.run_id}, not "
            f"{run.run_id}"
        )
    if runtime_reference.run_fingerprint != run.run_fingerprint:
        raise RunIntegrityError(
            "runtime reference and run agree on the run id but not on its "
            "fingerprint"
        )

    missing: list[str] = []
    entries: list[ResultSetEntry] = []
    successes = 0
    failures = 0

    for planned in plan.jobs:
        job_id = planned.job.job_id
        if not result_store.has_raw_result(run.run_id, job_id):
            missing.append(job_id)
            continue
        record = result_store.read_raw_result(run.run_id, job_id)
        if record.job_fingerprint != planned.job.job_fingerprint:
            raise RunIntegrityError(
                f"result {job_id} was produced by a different unit of work than "
                "the plan asked for; it cannot enter this run's result set"
            )
        entries.append(
            ResultSetEntry(
                ordinal=planned.ordinal,
                job_id=job_id,
                result_hash=raw_result_hash(record),
            )
        )
        if record.status is ExecutionStatus.SUCCESS:
            successes += 1
        else:
            failures += 1

    if missing:
        raise IncompleteRunError(
            f"run {run.run_id} cannot have a result set: {len(missing)} planned "
            f"job(s) have no result, starting with {missing[0]}"
        )

    ordered = tuple(entries)
    fingerprint = result_set_fingerprint(
        run_fingerprint=run.run_fingerprint,
        plan_fingerprint=plan.definition.plan_fingerprint,
        runtime_bundle_fingerprint=runtime_reference.bundle_fingerprint,
        entries=ordered,
        success_count=successes,
        failure_count=failures,
    )

    manifest = ResultSetManifest(
        result_set_id=result_set_id(fingerprint),
        result_set_fingerprint=fingerprint,
        run_id=run.run_id,
        run_fingerprint=run.run_fingerprint,
        plan_id=plan.plan_id,
        plan_fingerprint=plan.definition.plan_fingerprint,
        runtime_bundle_id=runtime_reference.bundle_id,
        runtime_bundle_fingerprint=runtime_reference.bundle_fingerprint,
        total_results=len(ordered),
        success_count=successes,
        failure_count=failures,
        ordered_results_hash=ordered_results_hash(ordered),
        created_utc=created_utc or _dt.datetime.now(_dt.timezone.utc).isoformat(),
    )
    return manifest, ordered
