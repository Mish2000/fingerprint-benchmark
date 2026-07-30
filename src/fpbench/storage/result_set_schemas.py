"""The Arrow schema for a result-set index.

Three columns and nothing else. This table is not a copy of the results — it is
a *list of which results*, in which order, hashing to what. Duplicating scores
here would create a second place they could disagree, which is the opposite of
what the record is for (docs/adr/0019).

Written out explicitly, like every other schema in this package, so a reader
never has to hope a column type was inferred the same way twice.
"""

from __future__ import annotations

from typing import Iterable

import pyarrow as pa

from fpbench.core.result_set_models import ResultSetEntry

__all__ = [
    "RESULT_SET_ENTRY_SCHEMA",
    "result_set_entries_to_table",
    "table_to_result_set_entries",
]

RESULT_SET_ENTRY_SCHEMA = pa.schema(
    [
        pa.field("ordinal", pa.int32(), nullable=False),
        pa.field("job_id", pa.string(), nullable=False),
        pa.field("result_hash", pa.string(), nullable=False),
    ]
)


def result_set_entries_to_table(entries: Iterable[ResultSetEntry]) -> pa.Table:
    rows = [
        {
            "ordinal": entry.ordinal,
            "job_id": entry.job_id,
            "result_hash": entry.result_hash,
        }
        for entry in entries
    ]
    columns = {
        field.name: [row[field.name] for row in rows]
        for field in RESULT_SET_ENTRY_SCHEMA
    }
    return pa.table(columns, schema=RESULT_SET_ENTRY_SCHEMA)


def table_to_result_set_entries(table: pa.Table) -> list[ResultSetEntry]:
    """Rebuild entries, sorted by ordinal.

    Sorting rather than trusting row order means the set survives being
    rewritten by any tool that does not preserve it — and order is part of this
    record's identity, so recovering it has to be deterministic.
    """
    rows = sorted(table.to_pylist(), key=lambda row: row["ordinal"])
    return [
        ResultSetEntry(
            ordinal=row["ordinal"],
            job_id=row["job_id"],
            result_hash=row["result_hash"],
        )
        for row in rows
    ]
