"""Turning a pair manifest into a frozen list of jobs.

The planner's whole contract is determinism. Given the same run and the same
pair manifest it must produce the same jobs, in the same order, with the same
fingerprint — regardless of what order the pairs were handed over in, what the
filesystem returned, or what time it is (docs/adr/0011).

That is why the order is *imposed* rather than inherited:

    1. protocol stage      SELF first, then mated, then non-mated
    2. release             SD300A, SD300B, SD300C
    3. pair_id             lexicographic, as a final tie-break

Stage order is not arbitrary. Running both SELF stages before any cross-
impression comparison means a partial run already contains the data needed to
judge which fingers are usable at all, which is the first thing worth looking
at when a matcher behaves unexpectedly.

None of that reaches the adapter. The ordering happens here, in the control
plane; a job still carries no stage and no ground truth, and its id is still a
hash (docs/adr/0010).
"""

from __future__ import annotations

import datetime as _dt
from typing import Iterable, Mapping

from fpbench.core.enums import ProtocolStage
from fpbench.core.errors import PlanningError
from fpbench.core.execution_models import FINGERPRINT_LENGTH
from fpbench.core.execution_plan_models import (
    PLAN_ID_LENGTH,
    PLAN_SCHEMA_VERSION,
    ComparisonJob,
    ExecutionPlan,
    ExecutionPlanDefinition,
    PlannedJob,
    job_manifest_hash,
)
from fpbench.core.models import ComparisonPair
from fpbench.core.result_models import RunDefinition
from fpbench.core.serialization import stable_hash
from fpbench.execution.jobs import build_comparison_job

__all__ = ["build_execution_plan", "STAGE_ORDER", "canonical_pair_order"]

#: The order stages are executed in. SELF comparisons come first so that a
#: partial run is still informative.
STAGE_ORDER: Mapping[ProtocolStage, int] = {
    ProtocolStage.PLAIN_SELF: 0,
    ProtocolStage.ROLL_SELF: 1,
    ProtocolStage.PLAIN_ROLL_MATED: 2,
    ProtocolStage.PLAIN_ROLL_NON_MATED: 3,
}


def canonical_pair_order(pair: ComparisonPair) -> tuple[int, str, str]:
    """The sort key that makes a plan independent of input order."""
    try:
        rank = STAGE_ORDER[pair.protocol_stage]
    except KeyError:
        raise PlanningError(
            f"pair {pair.pair_id} has stage {pair.protocol_stage.value!r}, which has "
            f"no place in the execution order; add it to STAGE_ORDER deliberately"
        ) from None
    return (rank, pair.release, str(pair.pair_id))


def build_execution_plan(
    *,
    run: RunDefinition,
    pairs: Iterable[ComparisonPair],
    pair_manifest_metadata: Mapping[str, str],
) -> ExecutionPlan:
    """Derive the immutable plan for ``run`` over ``pairs``.

    Args:
        pair_manifest_metadata: The parquet metadata of the pair manifest these
            pairs came from, as returned by
            :meth:`fpbench.storage.ManifestStore.pair_manifest_metadata`. It is
            checked against the run before anything is built.

    Raises:
        PlanningError: if the pairs do not come from the run's own manifest, or
            if they contain duplicates.
    """
    _require_matching_provenance(run, pair_manifest_metadata)

    ordered = _ordered_pairs(pairs)
    jobs = _jobs_for(run, ordered)

    planned = tuple(
        PlannedJob(ordinal=ordinal, job=job) for ordinal, job in enumerate(jobs)
    )
    manifest_hash = job_manifest_hash(run.run_fingerprint, planned)

    stage_counts = _counts(pair.protocol_stage.value for pair in ordered)
    release_counts = _counts(pair.release for pair in ordered)

    fingerprint = _plan_fingerprint(
        run=run,
        manifest_hash=manifest_hash,
        total_jobs=len(planned),
        stage_counts=stage_counts,
        release_counts=release_counts,
        job_fingerprints=[item.job.job_fingerprint for item in planned],
    )

    definition = ExecutionPlanDefinition(
        plan_id=f"plan_{fingerprint[:PLAN_ID_LENGTH]}",
        plan_fingerprint=fingerprint,
        run_id=run.run_id,
        run_fingerprint=run.run_fingerprint,
        pair_manifest_hash=run.pair_manifest_hash,
        total_jobs=len(planned),
        stage_counts=stage_counts,
        release_counts=release_counts,
        job_manifest_hash=manifest_hash,
        created_utc=_dt.datetime.now(_dt.timezone.utc).isoformat(),
    )
    return ExecutionPlan(definition=definition, jobs=planned)


# ----------------------------------------------------------------- internals


def _require_matching_provenance(
    run: RunDefinition, metadata: Mapping[str, str]
) -> None:
    """Refuse pairs that do not belong to this run.

    A plan built from the wrong manifest would execute perfectly and produce
    results nobody could attribute. Cheaper to refuse than to detect later.
    """
    expected = {
        "protocol_id": run.protocol_id,
        "cohort_id": str(run.cohort_id),
        "pair_manifest_hash": run.pair_manifest_hash,
    }
    for key, wanted in expected.items():
        actual = metadata.get(key)
        if actual is None:
            raise PlanningError(
                f"pair manifest metadata is missing {key!r}; cannot confirm the "
                f"pairs belong to run {run.run_id}"
            )
        if actual != wanted:
            raise PlanningError(
                f"pair manifest {key} is {actual!r} but run {run.run_id} was "
                f"defined against {wanted!r}"
            )


def _ordered_pairs(pairs: Iterable[ComparisonPair]) -> tuple[ComparisonPair, ...]:
    collected = list(pairs)
    if not collected:
        raise PlanningError("cannot plan a run with no pairs")

    seen: dict[str, ComparisonPair] = {}
    for pair in collected:
        key = str(pair.pair_id)
        previous = seen.get(key)
        if previous is not None:
            # Silently keeping the first would make the plan depend on input
            # order, which is the one thing a plan may never do.
            raise PlanningError(
                f"pair id {key!r} appears more than once in the manifest"
            )
        seen[key] = pair

    return tuple(sorted(collected, key=canonical_pair_order))


def _jobs_for(
    run: RunDefinition, pairs: tuple[ComparisonPair, ...]
) -> tuple[ComparisonJob, ...]:
    jobs = tuple(build_comparison_job(run, pair, attempt=1) for pair in pairs)

    for label, values in (
        ("job_id", [job.job_id for job in jobs]),
        ("job_fingerprint", [job.job_fingerprint for job in jobs]),
    ):
        duplicates = _duplicates(values)
        if duplicates:
            raise PlanningError(
                f"duplicate {label} in plan: {sorted(duplicates)[:3]}; two distinct "
                f"pairs cannot share one unit of work"
            )
    return jobs


def _duplicates(values: list[str]) -> set[str]:
    seen: set[str] = set()
    repeated: set[str] = set()
    for value in values:
        if value in seen:
            repeated.add(value)
        seen.add(value)
    return repeated


def _counts(values: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


def _plan_fingerprint(
    *,
    run: RunDefinition,
    manifest_hash: str,
    total_jobs: int,
    stage_counts: Mapping[str, int],
    release_counts: Mapping[str, int],
    job_fingerprints: list[str],
) -> str:
    """The digest behind ``plan_id``.

    Includes the ordered job fingerprints as well as the job manifest hash.
    That is redundant on its face — but the two cover different things, and a
    plan whose *order* changed while its contents did not is still a different
    plan.
    """
    return stable_hash(
        {
            "schema": "execution_plan_fingerprint_v1",
            "plan_schema_version": PLAN_SCHEMA_VERSION,
            "run_fingerprint": run.run_fingerprint,
            "pair_manifest_hash": run.pair_manifest_hash,
            "job_manifest_hash": manifest_hash,
            "total_jobs": total_jobs,
            "stage_counts": dict(stage_counts),
            "release_counts": dict(release_counts),
            "job_fingerprints": list(job_fingerprints),
        },
        length=FINGERPRINT_LENGTH,
    )
