"""Arrow schemas for aggregate counts and metric observations.

Written out in full, like every other schema here. Inference would be actively
harmful for two reasons specific to this table.

``release`` is nullable *by meaning*: it is null exactly on the pooled row, and a
batch that happened to contain no pooled row would infer a non-nullable column
the next batch could not be written into. The same is true of the two optional
source fingerprints on an observation, and of ``fraction_text``, which is null
exactly when a metric had nothing to divide by.

The counts themselves are stored as a sorted list of ``(name, value)`` structs
rather than as one column per outcome. A map would have been tidier, but the six
count families carry different key sets — a conditional record has seven counts,
a decision record four — and one wide table with a dozen mostly-null integer
columns is the kind of schema where a missing value and a zero become
indistinguishable.
"""

from __future__ import annotations

from typing import Iterable

import pyarrow as pa

from fpbench.core.enums import MetricObservationStatus, MetricScopeKind
from fpbench.core.metric_models import (
    EvaluationCountRecord,
    MetricObservation,
    MetricScope,
)

__all__ = [
    "COUNT_RECORD_SCHEMA",
    "METRIC_OBSERVATION_SCHEMA",
    "counts_to_table",
    "table_to_counts",
    "observations_to_table",
    "table_to_observations",
]


_COUNT_ENTRY = pa.struct(
    [
        pa.field("name", pa.string(), nullable=False),
        pa.field("value", pa.int64(), nullable=False),
    ]
)


COUNT_RECORD_SCHEMA = pa.schema(
    [
        pa.field("ordinal", pa.int32(), nullable=False),
        pa.field("count_family", pa.string(), nullable=False),
        pa.field("scope_kind", pa.string(), nullable=False),
        # Null exactly on the pooled row.
        pa.field("release", pa.string(), nullable=True),
        pa.field("total_count", pa.int64(), nullable=False),
        pa.field("counts", pa.list_(_COUNT_ENTRY), nullable=False),
        pa.field("source_fingerprint", pa.string(), nullable=False),
        pa.field("count_record_hash", pa.string(), nullable=False),
    ]
)


METRIC_OBSERVATION_SCHEMA = pa.schema(
    [
        pa.field("ordinal", pa.int32(), nullable=False),
        pa.field("metric_id", pa.string(), nullable=False),
        pa.field("scope_kind", pa.string(), nullable=False),
        pa.field("release", pa.string(), nullable=True),
        pa.field("numerator_count", pa.int64(), nullable=False),
        pa.field("denominator_count", pa.int64(), nullable=False),
        pa.field("status", pa.string(), nullable=False),
        # Null exactly when the denominator is zero. Never "0/0".
        pa.field("fraction_text", pa.string(), nullable=True),
        pa.field("source_decision_set_fingerprint", pa.string(), nullable=False),
        # Null for metrics that do not depend on eligibility.
        pa.field("source_eligibility_set_fingerprint", pa.string(), nullable=True),
        # Null for metrics counted from the decision set directly.
        pa.field("source_view_fingerprint", pa.string(), nullable=True),
        pa.field("metric_policy_fingerprint", pa.string(), nullable=False),
        pa.field("observation_hash", pa.string(), nullable=False),
    ]
)


def _table(rows: list[dict], schema: pa.Schema) -> pa.Table:
    columns = {field.name: [row[field.name] for row in rows] for field in schema}
    return pa.table(columns, schema=schema)


def _scope_of(row: dict) -> MetricScope:
    return MetricScope(
        scope_kind=MetricScopeKind(row["scope_kind"]),
        release=row["release"],
    )


# ------------------------------------------------------------------- counts


def counts_to_table(records: Iterable[EvaluationCountRecord]) -> pa.Table:
    rows = [
        {
            "ordinal": record.ordinal,
            "count_family": record.count_family,
            "scope_kind": record.scope.scope_kind.value,
            "release": record.scope.release,
            "total_count": record.total_count,
            "counts": [
                {"name": name, "value": value}
                for name, value in sorted(record.counts.items())
            ],
            "source_fingerprint": record.source_fingerprint,
            "count_record_hash": record.count_record_hash,
        }
        for record in records
    ]
    return _table(rows, COUNT_RECORD_SCHEMA)


def table_to_counts(table: pa.Table) -> list[EvaluationCountRecord]:
    rows = sorted(table.to_pylist(), key=lambda row: row["ordinal"])
    return [
        EvaluationCountRecord(
            ordinal=row["ordinal"],
            count_family=row["count_family"],
            scope=_scope_of(row),
            total_count=row["total_count"],
            counts={
                str(entry["name"]): entry["value"] for entry in row["counts"]
            },
            source_fingerprint=row["source_fingerprint"],
            count_record_hash=row["count_record_hash"],
        )
        for row in rows
    ]


# ------------------------------------------------------------- observations


def observations_to_table(observations: Iterable[MetricObservation]) -> pa.Table:
    rows = [
        {
            "ordinal": observation.ordinal,
            "metric_id": observation.metric_id,
            "scope_kind": observation.scope.scope_kind.value,
            "release": observation.scope.release,
            "numerator_count": observation.numerator_count,
            "denominator_count": observation.denominator_count,
            "status": observation.status.value,
            "fraction_text": observation.fraction_text,
            "source_decision_set_fingerprint": (
                observation.source_decision_set_fingerprint
            ),
            "source_eligibility_set_fingerprint": (
                observation.source_eligibility_set_fingerprint
            ),
            "source_view_fingerprint": observation.source_view_fingerprint,
            "metric_policy_fingerprint": observation.metric_policy_fingerprint,
            "observation_hash": observation.observation_hash,
        }
        for observation in observations
    ]
    return _table(rows, METRIC_OBSERVATION_SCHEMA)


def table_to_observations(table: pa.Table) -> list[MetricObservation]:
    rows = sorted(table.to_pylist(), key=lambda row: row["ordinal"])
    return [
        MetricObservation(
            ordinal=row["ordinal"],
            metric_id=row["metric_id"],
            scope=_scope_of(row),
            numerator_count=row["numerator_count"],
            denominator_count=row["denominator_count"],
            status=MetricObservationStatus(row["status"]),
            fraction_text=row["fraction_text"],
            source_decision_set_fingerprint=row["source_decision_set_fingerprint"],
            source_eligibility_set_fingerprint=row[
                "source_eligibility_set_fingerprint"
            ],
            source_view_fingerprint=row["source_view_fingerprint"],
            metric_policy_fingerprint=row["metric_policy_fingerprint"],
            observation_hash=row["observation_hash"],
        )
        for row in rows
    ]
