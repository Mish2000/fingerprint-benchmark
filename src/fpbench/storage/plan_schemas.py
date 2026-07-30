"""The Arrow schema for a stored execution plan.

One row per planned job, in ordinal order. Written out explicitly for the same
reason every other schema here is: a column type that depends on the contents
of a particular batch is not an interface anyone can rely on.

Note what the schema does not have: no ``protocol_stage``, no ``ground_truth``,
no threshold. Stage counts belong to the plan definition as an aggregate; they
have no business sitting next to each individual job, where they would be one
careless join away from reaching an adapter (docs/adr/0010).
"""

from __future__ import annotations

from typing import Iterable

import pyarrow as pa

from fpbench.core.execution_plan_models import ComparisonJob, PlannedJob
from fpbench.core.identifiers import ImageId, PairId

__all__ = ["PLANNED_JOB_SCHEMA", "planned_jobs_to_table", "table_to_planned_jobs"]

PLANNED_JOB_SCHEMA = pa.schema(
    [
        pa.field("ordinal", pa.int32(), nullable=False),
        pa.field("job_id", pa.string(), nullable=False),
        pa.field("job_fingerprint", pa.string(), nullable=False),
        pa.field("run_id", pa.string(), nullable=False),
        pa.field("pair_id", pa.string(), nullable=False),
        pa.field("left_image_id", pa.string(), nullable=False),
        pa.field("right_image_id", pa.string(), nullable=False),
        pa.field("attempt", pa.int32(), nullable=False),
    ]
)


def planned_jobs_to_table(planned: Iterable[PlannedJob]) -> pa.Table:
    rows = [
        {
            "ordinal": item.ordinal,
            "job_id": item.job.job_id,
            "job_fingerprint": item.job.job_fingerprint,
            "run_id": item.job.run_id,
            "pair_id": str(item.job.pair_id),
            "left_image_id": str(item.job.left_image_id),
            "right_image_id": str(item.job.right_image_id),
            "attempt": item.job.attempt,
        }
        for item in planned
    ]
    columns = {
        field.name: [row[field.name] for row in rows] for field in PLANNED_JOB_SCHEMA
    }
    return pa.table(columns, schema=PLANNED_JOB_SCHEMA)


def table_to_planned_jobs(table: pa.Table) -> list[PlannedJob]:
    """Rebuild planned jobs, sorted by ordinal.

    Sorting here rather than trusting row order means a plan survives being
    rewritten by any tool that does not preserve it.
    """
    rows = sorted(table.to_pylist(), key=lambda row: row["ordinal"])
    return [
        PlannedJob(
            ordinal=row["ordinal"],
            job=ComparisonJob(
                job_id=row["job_id"],
                job_fingerprint=row["job_fingerprint"],
                run_id=row["run_id"],
                pair_id=PairId(row["pair_id"]),
                left_image_id=ImageId(row["left_image_id"]),
                right_image_id=ImageId(row["right_image_id"]),
                attempt=row["attempt"],
            ),
        )
        for row in rows
    ]
