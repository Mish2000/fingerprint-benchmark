"""Declaring a run finished, once, on the strength of a clean audit.

``COMPLETE`` and ``VERIFIED`` are different claims. The first says every planned
job has a result. The second says somebody checked those results against the
plan and found nothing wrong. Only the second is worth reporting, and the only
evidence that it happened is ``completion.json``.

The manifest names the audit it rests on by fingerprint, so a completion cannot
be quietly reused after the results underneath it changed: a different set of
files audits to a different fingerprint, which would produce a different
completion fingerprint and a conflict rather than a silent pass.

A run may be verified with failures in it. 30 comparisons that produced no score
out of 6,000 is a finished run with 30 failures to analyse, not a broken one
(docs/adr/0013).
"""

from __future__ import annotations

import datetime as _dt

from fpbench.core.errors import IncompleteRunError, RunIntegrityError
from fpbench.core.execution_models import FINGERPRINT_LENGTH
from fpbench.core.execution_plan_models import ExecutionPlan
from fpbench.core.result_models import RunDefinition
from fpbench.core.run_state_models import (
    COMPLETION_ID_LENGTH,
    COMPLETION_SCHEMA_VERSION,
    RunAuditReport,
    RunCompletion,
)
from fpbench.core.serialization import stable_hash
from fpbench.execution.audit import audit_run
from fpbench.storage.result_store import ResultStore

__all__ = ["RunCompletionService", "build_run_completion"]


def build_run_completion(
    *,
    run: RunDefinition,
    plan: ExecutionPlan,
    audit: RunAuditReport,
    completed_utc: str | None = None,
) -> RunCompletion:
    """Derive the completion manifest for a clean, finished audit.

    Raises:
        RunIntegrityError: the audit found errors.
        IncompleteRunError: some planned job has no valid result.
    """
    if not audit.is_clean:
        raise RunIntegrityError(
            f"run {run.run_id} cannot be completed: "
            f"{[issue.code.value for issue in audit.errors][:5]}"
        )
    if audit.missing_job_ids or audit.extra_result_job_ids:
        raise RunIntegrityError(
            f"run {run.run_id} has {len(audit.missing_job_ids)} missing and "
            f"{len(audit.extra_result_job_ids)} unaccounted result(s)"
        )
    if audit.valid_results != plan.total_jobs:
        raise IncompleteRunError(
            f"run {run.run_id} has {audit.valid_results} valid results for "
            f"{plan.total_jobs} planned jobs"
        )

    fingerprint = stable_hash(
        {
            "schema": "run_completion_fingerprint_v1",
            "completion_schema_version": COMPLETION_SCHEMA_VERSION,
            "run_fingerprint": run.run_fingerprint,
            "plan_fingerprint": plan.definition.plan_fingerprint,
            "audit_fingerprint": audit.audit_fingerprint,
            "planned_jobs": plan.total_jobs,
            "success_count": audit.success_count,
            "failure_count": audit.failure_count,
        },
        length=FINGERPRINT_LENGTH,
    )

    return RunCompletion(
        completion_id=f"completion_{fingerprint[:COMPLETION_ID_LENGTH]}",
        completion_fingerprint=fingerprint,
        run_id=run.run_id,
        run_fingerprint=run.run_fingerprint,
        plan_id=plan.plan_id,
        plan_fingerprint=plan.definition.plan_fingerprint,
        pair_manifest_hash=run.pair_manifest_hash,
        audit_fingerprint=audit.audit_fingerprint,
        planned_jobs=plan.total_jobs,
        success_count=audit.success_count,
        failure_count=audit.failure_count,
        completed_utc=completed_utc
        or _dt.datetime.now(_dt.timezone.utc).isoformat(),
    )


class RunCompletionService:
    """Audits a run and, if it is sound, records that fact permanently."""

    def __init__(self, *, result_store: ResultStore) -> None:
        self._result_store = result_store

    def audit(self, *, run: RunDefinition, plan: ExecutionPlan) -> RunAuditReport:
        return audit_run(run=run, plan=plan, result_store=self._result_store)

    def finalise(
        self, *, run: RunDefinition, plan: ExecutionPlan
    ) -> tuple[RunAuditReport, RunCompletion]:
        """Audit, then write the completion manifest.

        Raises:
            RunIntegrityError: the audit was not clean. Nothing is written; a
                run with an integrity problem must not acquire a manifest
                saying otherwise.
        """
        report = self.audit(run=run, plan=plan)
        completion = build_run_completion(run=run, plan=plan, audit=report)
        self._result_store.ensure_completion(completion)
        return report, completion
