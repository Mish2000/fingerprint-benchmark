"""The frozen list of comparisons a run will carry out.

A plan is the bridge between "these 6,000 pairs are the experiment" and "these
6,000 jobs were executed". It exists so that the second sentence can be checked
against the first — without it, a run that quietly performed 5,999 comparisons
would look exactly like one that performed 6,000.

Everything here is derived, never assigned. Given the same run and the same
pair manifest, the planner produces byte-identical jobs in an identical order
with an identical fingerprint, no matter what order the pairs arrived in
(docs/adr/0011).

Note what a plan does *not* contain: no ground truth, no protocol stage per
job, no threshold. The stage counts live in the plan definition, as an
aggregate for reporting; individual jobs stay as blind as they are everywhere
else, so a plan can be handed around without leaking the answer
(docs/adr/0010).
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterator, Mapping

from fpbench.core.identifiers import ImageId, PairId, validate_id
from fpbench.core.serialization import stable_hash

__all__ = [
    "ComparisonJob",
    "PlannedJob",
    "ExecutionPlanDefinition",
    "ExecutionPlan",
    "job_manifest_hash",
    "PLAN_SCHEMA_VERSION",
    "PLAN_ID_LENGTH",
]

#: Bumped when the meaning of a plan changes. Inside the fingerprint, so a bump
#: separates new plans from old rather than silently reusing their ids.
PLAN_SCHEMA_VERSION = "1"

#: Twelve hex characters, matching ``run_id``. A workspace holds a handful of
#: plans, and the id is read by people far more often than it is compared.
PLAN_ID_LENGTH = 12


def _freeze_counts(value: Mapping[str, int], field_name: str) -> Mapping[str, int]:
    counts = {}
    for key, count in dict(value).items():
        number = int(count)
        if number < 0:
            raise ValueError(f"{field_name}[{key}] must not be negative")
        counts[str(key)] = number
    return MappingProxyType(counts)


@dataclass(frozen=True, slots=True)
class ComparisonJob:
    """A single planned comparison.

    Carries ``pair_id`` because the runner and the result store need to join
    back to the pair manifest. The adapter never sees this object — it receives
    a :class:`~fpbench.core.execution_models.ComparisonContext`, which does not
    include the pair.

    Built by :func:`fpbench.execution.jobs.build_comparison_job`, which is where
    the identity rules live.
    """

    job_id: str
    job_fingerprint: str
    run_id: str
    pair_id: PairId
    left_image_id: ImageId
    right_image_id: ImageId
    attempt: int = 1

    def __post_init__(self) -> None:
        if int(self.attempt) < 1:
            raise ValueError("attempt is 1-based")
        object.__setattr__(self, "attempt", int(self.attempt))


@dataclass(frozen=True, slots=True)
class PlannedJob:
    """One comparison, and where it sits in the canonical order.

    ``ordinal`` is execution order, not priority. It exists so that a partially
    executed run can be described precisely and resumed deterministically.
    """

    ordinal: int
    job: ComparisonJob

    def __post_init__(self) -> None:
        if int(self.ordinal) < 0:
            raise ValueError("ordinal is 0-based and must not be negative")
        object.__setattr__(self, "ordinal", int(self.ordinal))
        if self.job.attempt != 1:
            raise ValueError(
                "stage 3B plans only contain first attempts; retries would need "
                "their own plan entry rather than replacing this one"
            )


@dataclass(frozen=True, slots=True)
class ExecutionPlanDefinition:
    """A plan's identity and shape, without the jobs themselves.

    Small enough to read, hash and store on its own, which is what makes
    ``plan.json`` a useful marker that a plan was written completely.
    """

    plan_id: str
    plan_fingerprint: str

    run_id: str
    run_fingerprint: str
    pair_manifest_hash: str

    total_jobs: int
    stage_counts: Mapping[str, int]
    release_counts: Mapping[str, int]

    job_manifest_hash: str
    created_utc: str

    def __post_init__(self) -> None:
        validate_id(self.plan_id)
        validate_id(self.run_id)
        for name in ("plan_fingerprint", "run_fingerprint", "pair_manifest_hash", "job_manifest_hash"):
            value = str(getattr(self, name)).strip().lower()
            if len(value) != 64 or not set(value) <= set("0123456789abcdef"):
                raise ValueError(f"{name} must be a 64-character hexadecimal digest")
            object.__setattr__(self, name, value)

        if int(self.total_jobs) <= 0:
            raise ValueError("a plan with no jobs is not a plan")
        object.__setattr__(self, "total_jobs", int(self.total_jobs))

        object.__setattr__(
            self, "stage_counts", _freeze_counts(self.stage_counts, "stage_counts")
        )
        object.__setattr__(
            self, "release_counts", _freeze_counts(self.release_counts, "release_counts")
        )
        for name in ("stage_counts", "release_counts"):
            total = sum(getattr(self, name).values())
            if total != self.total_jobs:
                raise ValueError(
                    f"{name} sums to {total} but the plan holds {self.total_jobs} jobs"
                )


@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    """A plan definition together with its jobs, in execution order."""

    definition: ExecutionPlanDefinition
    jobs: tuple[PlannedJob, ...]

    def __post_init__(self) -> None:
        jobs = tuple(self.jobs)
        object.__setattr__(self, "jobs", jobs)

        if len(jobs) != self.definition.total_jobs:
            raise ValueError(
                f"plan declares {self.definition.total_jobs} jobs but carries {len(jobs)}"
            )
        if [planned.ordinal for planned in jobs] != list(range(len(jobs))):
            raise ValueError("ordinals must be 0..n-1 with no gaps and no repeats")

        for label, values in (
            ("job_id", [planned.job.job_id for planned in jobs]),
            ("job_fingerprint", [planned.job.job_fingerprint for planned in jobs]),
            ("pair_id", [str(planned.job.pair_id) for planned in jobs]),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"{label} must be unique within a plan")

        stray = {
            planned.job.run_id
            for planned in jobs
            if planned.job.run_id != self.definition.run_id
        }
        if stray:
            raise ValueError(
                f"plan for run {self.definition.run_id} contains jobs from {sorted(stray)}"
            )

    @property
    def plan_id(self) -> str:
        return self.definition.plan_id

    @property
    def run_id(self) -> str:
        return self.definition.run_id

    @property
    def total_jobs(self) -> int:
        return self.definition.total_jobs

    def __iter__(self) -> Iterator[PlannedJob]:
        return iter(self.jobs)

    def job_ids(self) -> tuple[str, ...]:
        return tuple(planned.job.job_id for planned in self.jobs)

    def pair_ids(self) -> tuple[PairId, ...]:
        return tuple(planned.job.pair_id for planned in self.jobs)


def job_manifest_hash(
    run_fingerprint: str, planned: Iterable[PlannedJob]
) -> str:
    """A digest of a job list, with no timestamp anywhere in it.

    Lives here rather than in the planner so that the storage layer can verify
    a stored plan without importing the execution layer, and so that there is
    exactly one definition of what a job list hashes to.
    """
    return stable_hash(
        {
            "schema": "execution_job_manifest_v1",
            "run_fingerprint": run_fingerprint,
            "jobs": [
                {
                    "ordinal": item.ordinal,
                    "job_id": item.job.job_id,
                    "job_fingerprint": item.job.job_fingerprint,
                    "pair_id": str(item.job.pair_id),
                    "left_image_id": str(item.job.left_image_id),
                    "right_image_id": str(item.job.right_image_id),
                    "attempt": item.job.attempt,
                }
                for item in planned
            ],
        },
        length=64,
    )
