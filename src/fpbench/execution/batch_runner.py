"""Walking a plan from start to finish, in as many sittings as it takes.

Sequential by design. Nothing here is parallel, and 6,000 jobs at a few
milliseconds each does not need it — but the *storage* layout underneath is
already the one that makes parallelism safe (one immutable file per job, no
shared table, no locks), so adding workers later changes this class and nothing
below it.

The two behaviours the whole class exists for:

**A stopped run loses nothing.** Interrupt it at job 4,137 and 4,137 results
are on disk, complete and readable. Start it again and it executes 1,863 jobs,
not 6,000. That falls out of job identity being derived rather than assigned —
:class:`SingleJobRunner` recognises its own earlier work — so this class does
not reimplement resume, it simply asks.

**A failed comparison is not a failed run.** An adapter that cannot score a
pair produces a stored failure, and the walk continues. What stops the walk is
a *conflict*: a result that contradicts the plan, a corrupt file, a job that
does not match its pair. Those mean the directory can no longer be trusted, and
continuing would mix incomparable results together (docs/adr/0013).

The executor never sees a score and never names an algorithm. It moves through
ordinals, hands each job to the runner it was given, and counts what comes back.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Mapping

from fpbench.core.enums import ExecutionStatus
from fpbench.core.errors import PlanConflictError, PreflightError
from fpbench.core.execution_plan_models import ExecutionPlan
from fpbench.core.identifiers import PairId
from fpbench.core.models import ComparisonPair
from fpbench.core.result_models import RunDefinition
from fpbench.execution.completion import RunCompletionService
from fpbench.execution.runner import JobDisposition, SingleJobRunner
from fpbench.storage.plan_store import PlanStore
from fpbench.storage.result_store import ResultStore

__all__ = ["RunExecutionSummary", "SequentialRunExecutor"]


@dataclass(frozen=True, slots=True)
class RunExecutionSummary:
    """What one call to :meth:`SequentialRunExecutor.execute` did.

    Scoped to the invocation, not the run. ``newly_executed_jobs`` is what this
    call performed; ``remaining_jobs`` is what the *run* still owes, which is
    the number a caller needs in order to decide whether to go again.
    """

    run_id: str
    plan_id: str

    visited_jobs: int
    newly_executed_jobs: int
    skipped_existing_jobs: int

    successful_results_seen: int
    failed_results_seen: int

    planned_jobs: int
    remaining_jobs: int

    started_utc: str
    finished_utc: str

    completed: bool
    verified: bool


class SequentialRunExecutor:
    """Executes an entire plan, one job at a time, resumably."""

    def __init__(
        self,
        *,
        plan: ExecutionPlan,
        pair_index: Mapping[PairId, ComparisonPair],
        job_runner: SingleJobRunner,
        result_store: ResultStore,
        completion_service: RunCompletionService,
        plan_store: PlanStore | None = None,
    ) -> None:
        self._plan = plan
        self._pair_index = dict(pair_index)
        self._job_runner = job_runner
        self._result_store = result_store
        self._completion_service = completion_service
        self._plan_store = plan_store or PlanStore(result_store.root)
        self._preflight()

    @property
    def run(self) -> RunDefinition:
        return self._job_runner.run

    @property
    def plan(self) -> ExecutionPlan:
        return self._plan

    # --------------------------------------------------------------- preflight

    def _preflight(self) -> None:
        """Prove the plan, the pairs and the runner all describe one run.

        All of this is fatal. A mismatch here would produce results that look
        fine and cannot be attributed to anything, which is worse than a run
        that refuses to start.
        """
        run = self._job_runner.run

        if self._plan.definition.run_id != run.run_id:
            raise PreflightError(
                f"plan {self._plan.plan_id} is for run {self._plan.definition.run_id}, "
                f"but the job runner is bound to {run.run_id}"
            )
        if self._plan.definition.run_fingerprint != run.run_fingerprint:
            raise PreflightError(
                "plan and run agree on the run id but not on its fingerprint"
            )
        if self._plan.definition.pair_manifest_hash != run.pair_manifest_hash:
            raise PreflightError(
                "plan was built against a different pair manifest than the run"
            )

        for planned in self._plan.jobs:
            job = planned.job
            pair = self._pair_index.get(job.pair_id)
            if pair is None:
                raise PreflightError(
                    f"planned pair {job.pair_id} is not in the supplied pair index"
                )
            if str(pair.pair_id) != str(job.pair_id):
                raise PreflightError(
                    f"pair index maps {job.pair_id} to a pair calling itself "
                    f"{pair.pair_id}"
                )
            if (pair.left_image_id, pair.right_image_id) != (
                job.left_image_id,
                job.right_image_id,
            ):
                raise PreflightError(
                    f"pair {pair.pair_id} does not hold the images planned for "
                    f"job {job.job_id}"
                )

        # The run manifest is written by SingleJobRunner's own preflight; this
        # confirms it describes the same run rather than assuming it.
        stored_run = self._result_store.read_run(run.run_id)
        if stored_run.run_fingerprint != run.run_fingerprint:
            raise PreflightError(
                f"stored run manifest for {run.run_id} describes a different run"
            )

        self._plan_store.ensure_plan(self._plan)
        stored_plan = self._plan_store.read_plan_definition(run.run_id)
        if stored_plan.plan_fingerprint != self._plan.definition.plan_fingerprint:
            raise PlanConflictError(
                f"stored plan for {run.run_id} is {stored_plan.plan_id}, not "
                f"{self._plan.plan_id}"
            )

    # ----------------------------------------------------------------- execute

    def execute(self, *, max_new_jobs: int | None = None) -> RunExecutionSummary:
        """Walk the plan in ordinal order, executing what is not already done.

        Args:
            max_new_jobs: Stop after performing this many *new* comparisons.
                Jobs already stored are checked and skipped without counting
                against the budget, so a resumed run makes real progress rather
                than spending its allowance re-confirming old work. ``None``
                means finish the plan.

        Returns:
            A summary of this invocation. ``completed`` and ``verified`` refer
            to the run as a whole.
        """
        if max_new_jobs is not None and int(max_new_jobs) <= 0:
            raise ValueError("max_new_jobs must be a positive number of jobs, or None")

        started_utc = _utc_now()
        visited = 0
        executed = 0
        skipped = 0
        successes = 0
        failures = 0

        for planned in self._plan.jobs:
            if max_new_jobs is not None and executed >= max_new_jobs:
                break

            job = planned.job
            pair = self._pair_index[job.pair_id]

            # Any exception from here propagates on purpose. A conflict or a
            # corrupt file means the directory is no longer coherent, and the
            # correct response is to stop before writing more into it.
            outcome = self._job_runner.execute(job, pair)

            visited += 1
            if outcome.disposition is JobDisposition.EXECUTED:
                executed += 1
            else:
                skipped += 1

            if outcome.result.status is ExecutionStatus.SUCCESS:
                successes += 1
            else:
                failures += 1

        remaining = self._remaining_jobs()
        completed = remaining == 0
        verified = False
        if completed:
            # Only now is a full audit meaningful, and only a clean one earns a
            # completion manifest. An unclean audit raises rather than silently
            # returning a run that looks finished.
            self._completion_service.finalise(run=self.run, plan=self._plan)
            verified = True

        return RunExecutionSummary(
            run_id=self.run.run_id,
            plan_id=self._plan.plan_id,
            visited_jobs=visited,
            newly_executed_jobs=executed,
            skipped_existing_jobs=skipped,
            successful_results_seen=successes,
            failed_results_seen=failures,
            planned_jobs=self._plan.total_jobs,
            remaining_jobs=remaining,
            started_utc=started_utc,
            finished_utc=_utc_now(),
            completed=completed,
            verified=verified,
        )

    # ----------------------------------------------------------------- helpers

    def _remaining_jobs(self) -> int:
        """Planned jobs with no result file, counted from the filesystem.

        Not from the loop above: a previous invocation's work counts too, and
        the files are the only thing that knows about it (docs/adr/0012).
        """
        run_id = self.run.run_id
        return sum(
            1
            for planned in self._plan.jobs
            if not self._result_store.has_raw_result(run_id, planned.job.job_id)
        )


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()
