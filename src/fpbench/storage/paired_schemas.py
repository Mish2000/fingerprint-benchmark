"""Arrow schemas for the five paired-comparison tables.

Written out explicitly, like every other schema in this package, and with the
same rule stage 6A's prepared entries follow: every integer column is ``int64``
and every read checks exactness. A count that came back as ``6000.0`` would
still compare equal in Python and would hash differently, which is precisely the
failure a stored fingerprint exists to catch.

Two columns are nullable and both are nullable for a reason.
``score_delta_decimal`` is absent whenever either side produced no score, and
``difference_numerator``/``difference_denominator`` are absent whenever the two
rates are not comparable. In both cases "absent" is a different claim from
"zero", and collapsing them would turn "we could not compare these" into "we
compared these and found no difference".
"""

from __future__ import annotations

from typing import Iterable

import pyarrow as pa

from fpbench.core.enums import (
    ComparabilityStatus,
    DecisionOutcome,
    ExecutionStatus,
    ProtocolStage,
    ScoreRelation,
)
from fpbench.core.paired_models import (
    CommonEligibleMatedEntry,
    MetricScopeRef,
    PairedComparisonRecord,
    PairedRateObservation,
    SelfEligibilityTransitionRecord,
    TransitionCountRecord,
)
from fpbench.core.serialization import require_exact_int

__all__ = [
    "PAIRED_COMPARISON_SCHEMA",
    "ELIGIBILITY_TRANSITION_SCHEMA",
    "COMMON_ELIGIBLE_SCHEMA",
    "TRANSITION_COUNT_SCHEMA",
    "PAIRED_OBSERVATION_SCHEMA",
    "paired_comparisons_to_table",
    "table_to_paired_comparisons",
    "eligibility_transitions_to_table",
    "table_to_eligibility_transitions",
    "common_eligible_to_table",
    "table_to_common_eligible",
    "transition_counts_to_table",
    "table_to_transition_counts",
    "paired_observations_to_table",
    "table_to_paired_observations",
]


PAIRED_COMPARISON_SCHEMA = pa.schema(
    [
        pa.field("ordinal", pa.int64(), nullable=False),
        pa.field("pair_id", pa.string(), nullable=False),
        pa.field("release", pa.string(), nullable=False),
        pa.field("protocol_stage", pa.string(), nullable=False),
        pa.field("native_job_id", pa.string(), nullable=False),
        pa.field("canonical_job_id", pa.string(), nullable=False),
        pa.field("native_raw_result_hash", pa.string(), nullable=False),
        pa.field("canonical_raw_result_hash", pa.string(), nullable=False),
        pa.field("native_decision_hash", pa.string(), nullable=False),
        pa.field("canonical_decision_hash", pa.string(), nullable=False),
        pa.field("native_execution_status", pa.string(), nullable=False),
        pa.field("canonical_execution_status", pa.string(), nullable=False),
        pa.field("native_failure_code", pa.string(), nullable=True),
        pa.field("canonical_failure_code", pa.string(), nullable=True),
        pa.field("native_outcome", pa.string(), nullable=False),
        pa.field("canonical_outcome", pa.string(), nullable=False),
        pa.field("score_relation", pa.string(), nullable=False),
        pa.field("score_delta_decimal", pa.string(), nullable=True),
        pa.field("record_hash", pa.string(), nullable=False),
    ]
)

ELIGIBILITY_TRANSITION_SCHEMA = pa.schema(
    [
        pa.field("ordinal", pa.int64(), nullable=False),
        pa.field("eligibility_unit_id", pa.string(), nullable=False),
        pa.field("release", pa.string(), nullable=False),
        pa.field("subject_id", pa.string(), nullable=False),
        pa.field("finger_id", pa.int64(), nullable=False),
        pa.field("native_record_hash", pa.string(), nullable=False),
        pa.field("canonical_record_hash", pa.string(), nullable=False),
        pa.field("native_status", pa.string(), nullable=False),
        pa.field("canonical_status", pa.string(), nullable=False),
        pa.field("record_hash", pa.string(), nullable=False),
    ]
)

COMMON_ELIGIBLE_SCHEMA = pa.schema(
    [
        pa.field("ordinal", pa.int64(), nullable=False),
        pa.field("pair_id", pa.string(), nullable=False),
        pa.field("release", pa.string(), nullable=False),
        pa.field("native_eligibility_status", pa.string(), nullable=False),
        pa.field("canonical_eligibility_status", pa.string(), nullable=False),
        pa.field("included", pa.bool_(), nullable=False),
        pa.field("native_job_id", pa.string(), nullable=False),
        pa.field("canonical_job_id", pa.string(), nullable=False),
        pa.field("native_decision_hash", pa.string(), nullable=False),
        pa.field("canonical_decision_hash", pa.string(), nullable=False),
        pa.field("native_outcome", pa.string(), nullable=False),
        pa.field("canonical_outcome", pa.string(), nullable=False),
        pa.field("entry_hash", pa.string(), nullable=False),
    ]
)

TRANSITION_COUNT_SCHEMA = pa.schema(
    [
        pa.field("ordinal", pa.int64(), nullable=False),
        pa.field("family", pa.string(), nullable=False),
        pa.field("scope_kind", pa.string(), nullable=False),
        pa.field("release", pa.string(), nullable=True),
        pa.field("total", pa.int64(), nullable=False),
        pa.field(
            "counts",
            pa.map_(pa.string(), pa.int64()),
            nullable=False,
        ),
        pa.field(
            "source_fingerprints",
            pa.map_(pa.string(), pa.string()),
            nullable=False,
        ),
        pa.field("record_hash", pa.string(), nullable=False),
    ]
)

PAIRED_OBSERVATION_SCHEMA = pa.schema(
    [
        pa.field("ordinal", pa.int64(), nullable=False),
        pa.field("observation_id", pa.string(), nullable=False),
        pa.field("scope_kind", pa.string(), nullable=False),
        pa.field("release", pa.string(), nullable=True),
        pa.field("native_numerator", pa.int64(), nullable=False),
        pa.field("native_denominator", pa.int64(), nullable=False),
        pa.field("canonical_numerator", pa.int64(), nullable=False),
        pa.field("canonical_denominator", pa.int64(), nullable=False),
        pa.field("difference_numerator", pa.int64(), nullable=True),
        pa.field("difference_denominator", pa.int64(), nullable=True),
        pa.field("comparability", pa.string(), nullable=False),
        pa.field("policy_fingerprint", pa.string(), nullable=False),
        pa.field("observation_hash", pa.string(), nullable=False),
    ]
)


def _table(schema: pa.Schema, rows: list[dict]) -> pa.Table:
    columns = {field.name: [row[field.name] for row in rows] for field in schema}
    return pa.table(columns, schema=schema)


def _require_schema(table: pa.Table, schema: pa.Schema, what: str) -> None:
    if table.schema != schema:
        raise ValueError(
            f"the {what} table does not carry its declared schema; a column "
            "added, removed or retyped changes what a row means"
        )


def _exact_ints(row: dict, schema: pa.Schema) -> None:
    for field in schema:
        if not pa.types.is_integer(field.type):
            continue
        value = row[field.name]
        if value is None and field.nullable:
            continue
        require_exact_int(value, field.name)


# ------------------------------------------------------------- comparisons


def paired_comparisons_to_table(
    records: Iterable[PairedComparisonRecord],
) -> pa.Table:
    return _table(
        PAIRED_COMPARISON_SCHEMA,
        [
            {
                "ordinal": record.ordinal,
                "pair_id": str(record.pair_id),
                "release": record.release,
                "protocol_stage": record.protocol_stage.value,
                "native_job_id": record.native_job_id,
                "canonical_job_id": record.canonical_job_id,
                "native_raw_result_hash": record.native_raw_result_hash,
                "canonical_raw_result_hash": record.canonical_raw_result_hash,
                "native_decision_hash": record.native_decision_hash,
                "canonical_decision_hash": record.canonical_decision_hash,
                "native_execution_status": record.native_execution_status.value,
                "canonical_execution_status": record.canonical_execution_status.value,
                "native_failure_code": record.native_failure_code,
                "canonical_failure_code": record.canonical_failure_code,
                "native_outcome": record.native_outcome.value,
                "canonical_outcome": record.canonical_outcome.value,
                "score_relation": record.score_relation.value,
                "score_delta_decimal": record.score_delta_decimal,
                "record_hash": record.record_hash,
            }
            for record in records
        ],
    )


def table_to_paired_comparisons(table: pa.Table) -> list[PairedComparisonRecord]:
    _require_schema(table, PAIRED_COMPARISON_SCHEMA, "paired comparison")
    rows = sorted(table.to_pylist(), key=lambda row: row["ordinal"])
    records = []
    for row in rows:
        _exact_ints(row, PAIRED_COMPARISON_SCHEMA)
        records.append(
            PairedComparisonRecord(
                ordinal=row["ordinal"],
                pair_id=row["pair_id"],
                release=row["release"],
                protocol_stage=ProtocolStage(row["protocol_stage"]),
                native_job_id=row["native_job_id"],
                canonical_job_id=row["canonical_job_id"],
                native_raw_result_hash=row["native_raw_result_hash"],
                canonical_raw_result_hash=row["canonical_raw_result_hash"],
                native_decision_hash=row["native_decision_hash"],
                canonical_decision_hash=row["canonical_decision_hash"],
                native_execution_status=ExecutionStatus(
                    row["native_execution_status"]
                ),
                canonical_execution_status=ExecutionStatus(
                    row["canonical_execution_status"]
                ),
                native_failure_code=row["native_failure_code"],
                canonical_failure_code=row["canonical_failure_code"],
                native_outcome=DecisionOutcome(row["native_outcome"]),
                canonical_outcome=DecisionOutcome(row["canonical_outcome"]),
                score_relation=ScoreRelation(row["score_relation"]),
                score_delta_decimal=row["score_delta_decimal"],
                record_hash=row["record_hash"],
            )
        )
    return records


# ---------------------------------------------------- eligibility transitions


def eligibility_transitions_to_table(
    records: Iterable[SelfEligibilityTransitionRecord],
) -> pa.Table:
    return _table(
        ELIGIBILITY_TRANSITION_SCHEMA,
        [
            {
                "ordinal": record.ordinal,
                "eligibility_unit_id": record.eligibility_unit_id,
                "release": record.release,
                "subject_id": record.subject_id,
                "finger_id": record.finger_id,
                "native_record_hash": record.native_record_hash,
                "canonical_record_hash": record.canonical_record_hash,
                "native_status": record.native_status,
                "canonical_status": record.canonical_status,
                "record_hash": record.record_hash,
            }
            for record in records
        ],
    )


def table_to_eligibility_transitions(
    table: pa.Table,
) -> list[SelfEligibilityTransitionRecord]:
    _require_schema(table, ELIGIBILITY_TRANSITION_SCHEMA, "eligibility transition")
    rows = sorted(table.to_pylist(), key=lambda row: row["ordinal"])
    records = []
    for row in rows:
        _exact_ints(row, ELIGIBILITY_TRANSITION_SCHEMA)
        records.append(SelfEligibilityTransitionRecord(**row))
    return records


# ------------------------------------------------------------ common eligible


def common_eligible_to_table(
    entries: Iterable[CommonEligibleMatedEntry],
) -> pa.Table:
    return _table(
        COMMON_ELIGIBLE_SCHEMA,
        [
            {
                "ordinal": entry.ordinal,
                "pair_id": str(entry.pair_id),
                "release": entry.release,
                "native_eligibility_status": entry.native_eligibility_status,
                "canonical_eligibility_status": entry.canonical_eligibility_status,
                "included": entry.included,
                "native_job_id": entry.native_job_id,
                "canonical_job_id": entry.canonical_job_id,
                "native_decision_hash": entry.native_decision_hash,
                "canonical_decision_hash": entry.canonical_decision_hash,
                "native_outcome": entry.native_outcome.value,
                "canonical_outcome": entry.canonical_outcome.value,
                "entry_hash": entry.entry_hash,
            }
            for entry in entries
        ],
    )


def table_to_common_eligible(table: pa.Table) -> list[CommonEligibleMatedEntry]:
    _require_schema(table, COMMON_ELIGIBLE_SCHEMA, "common-eligible mated")
    rows = sorted(table.to_pylist(), key=lambda row: row["ordinal"])
    entries = []
    for row in rows:
        _exact_ints(row, COMMON_ELIGIBLE_SCHEMA)
        entries.append(
            CommonEligibleMatedEntry(
                ordinal=row["ordinal"],
                pair_id=row["pair_id"],
                release=row["release"],
                native_eligibility_status=row["native_eligibility_status"],
                canonical_eligibility_status=row["canonical_eligibility_status"],
                included=row["included"],
                native_job_id=row["native_job_id"],
                canonical_job_id=row["canonical_job_id"],
                native_decision_hash=row["native_decision_hash"],
                canonical_decision_hash=row["canonical_decision_hash"],
                native_outcome=DecisionOutcome(row["native_outcome"]),
                canonical_outcome=DecisionOutcome(row["canonical_outcome"]),
                entry_hash=row["entry_hash"],
            )
        )
    return entries


# ------------------------------------------------------------------- counts


def transition_counts_to_table(records: Iterable[TransitionCountRecord]) -> pa.Table:
    return _table(
        TRANSITION_COUNT_SCHEMA,
        [
            {
                "ordinal": record.ordinal,
                "family": record.family,
                "scope_kind": record.scope.scope_kind,
                "release": record.scope.release,
                "total": record.total,
                "counts": list(dict(record.counts).items()),
                "source_fingerprints": list(dict(record.source_fingerprints).items()),
                "record_hash": record.record_hash,
            }
            for record in records
        ],
    )


def table_to_transition_counts(table: pa.Table) -> list[TransitionCountRecord]:
    _require_schema(table, TRANSITION_COUNT_SCHEMA, "transition count")
    rows = sorted(table.to_pylist(), key=lambda row: row["ordinal"])
    records = []
    for row in rows:
        _exact_ints(row, TRANSITION_COUNT_SCHEMA)
        counts = dict(row["counts"])
        for value in counts.values():
            require_exact_int(value, "counts")
        records.append(
            TransitionCountRecord(
                ordinal=row["ordinal"],
                family=row["family"],
                scope=MetricScopeRef(
                    scope_kind=row["scope_kind"], release=row["release"]
                ),
                total=row["total"],
                counts=counts,
                source_fingerprints=dict(row["source_fingerprints"]),
                record_hash=row["record_hash"],
            )
        )
    return records


# ------------------------------------------------------------- observations


def paired_observations_to_table(
    observations: Iterable[PairedRateObservation],
) -> pa.Table:
    return _table(
        PAIRED_OBSERVATION_SCHEMA,
        [
            {
                "ordinal": observation.ordinal,
                "observation_id": observation.observation_id,
                "scope_kind": observation.scope.scope_kind,
                "release": observation.scope.release,
                "native_numerator": observation.native_numerator,
                "native_denominator": observation.native_denominator,
                "canonical_numerator": observation.canonical_numerator,
                "canonical_denominator": observation.canonical_denominator,
                "difference_numerator": observation.difference_numerator,
                "difference_denominator": observation.difference_denominator,
                "comparability": observation.comparability.value,
                "policy_fingerprint": observation.policy_fingerprint,
                "observation_hash": observation.observation_hash,
            }
            for observation in observations
        ],
    )


def table_to_paired_observations(table: pa.Table) -> list[PairedRateObservation]:
    _require_schema(table, PAIRED_OBSERVATION_SCHEMA, "paired observation")
    rows = sorted(table.to_pylist(), key=lambda row: row["ordinal"])
    observations = []
    for row in rows:
        _exact_ints(row, PAIRED_OBSERVATION_SCHEMA)
        observations.append(
            PairedRateObservation(
                ordinal=row["ordinal"],
                observation_id=row["observation_id"],
                scope=MetricScopeRef(
                    scope_kind=row["scope_kind"], release=row["release"]
                ),
                native_numerator=row["native_numerator"],
                native_denominator=row["native_denominator"],
                canonical_numerator=row["canonical_numerator"],
                canonical_denominator=row["canonical_denominator"],
                difference_numerator=row["difference_numerator"],
                difference_denominator=row["difference_denominator"],
                comparability=ComparabilityStatus(row["comparability"]),
                policy_fingerprint=row["policy_fingerprint"],
                observation_hash=row["observation_hash"],
            )
        )
    return observations
