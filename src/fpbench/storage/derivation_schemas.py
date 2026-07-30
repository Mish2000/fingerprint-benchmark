"""Arrow schemas for decisions, eligibility and evaluation views.

Written out in full, like every other schema in this package. Inference would be
particularly bad here: three of these columns are nullable *by meaning* —
``decision`` is null exactly when a comparison could not be decided,
``exclusion_reason`` exactly when a row is included — and a batch that happened
to contain no nulls would infer a non-nullable column that the next batch could
not be written into.

The three tables share this module rather than each having their own, because
they are one record shape argued three ways and keeping them side by side makes
a drift between them visible.
"""

from __future__ import annotations

from typing import Iterable

import pyarrow as pa

from fpbench.core.decision_models import DecisionApplicationStatus, DecisionRecord, DecisionValue
from fpbench.core.eligibility_models import (
    SelfEligibilityDecisionRecord,
    SelfEligibilityReason,
    SelfEligibilityStatus,
)
from fpbench.core.enums import ExecutionStatus
from fpbench.core.evaluation_view_models import EvaluationViewEntry

__all__ = [
    "DECISION_RECORD_SCHEMA",
    "ELIGIBILITY_RECORD_SCHEMA",
    "EVALUATION_VIEW_ENTRY_SCHEMA",
    "decisions_to_table",
    "table_to_decisions",
    "eligibility_to_table",
    "table_to_eligibility",
    "view_entries_to_table",
    "table_to_view_entries",
]


DECISION_RECORD_SCHEMA = pa.schema(
    [
        pa.field("ordinal", pa.int32(), nullable=False),
        pa.field("job_id", pa.string(), nullable=False),
        pa.field("job_fingerprint", pa.string(), nullable=False),
        pa.field("pair_id", pa.string(), nullable=False),
        pa.field("source_result_hash", pa.string(), nullable=False),
        pa.field("result_set_id", pa.string(), nullable=False),
        pa.field("result_set_fingerprint", pa.string(), nullable=False),
        pa.field("decision_profile_id", pa.string(), nullable=False),
        pa.field("decision_profile_fingerprint", pa.string(), nullable=False),
        pa.field("application_status", pa.string(), nullable=False),
        # Null exactly when the comparison produced no score. A failure is not a
        # non-match, and the schema is where that stops being a convention.
        pa.field("decision", pa.string(), nullable=True),
        pa.field("source_execution_status", pa.string(), nullable=False),
        pa.field("source_failure_code", pa.string(), nullable=True),
        pa.field("decision_record_hash", pa.string(), nullable=False),
    ]
)


ELIGIBILITY_RECORD_SCHEMA = pa.schema(
    [
        pa.field("ordinal", pa.int32(), nullable=False),
        pa.field("eligibility_unit_id", pa.string(), nullable=False),
        pa.field("release", pa.string(), nullable=False),
        pa.field("canonical_finger", pa.int32(), nullable=False),
        pa.field("plain_self_pair_id", pa.string(), nullable=False),
        pa.field("plain_self_job_id", pa.string(), nullable=False),
        pa.field("plain_self_decision_hash", pa.string(), nullable=False),
        pa.field("plain_self_decision", pa.string(), nullable=True),
        pa.field("roll_self_pair_id", pa.string(), nullable=False),
        pa.field("roll_self_job_id", pa.string(), nullable=False),
        pa.field("roll_self_decision_hash", pa.string(), nullable=False),
        pa.field("roll_self_decision", pa.string(), nullable=True),
        pa.field("mated_pair_id", pa.string(), nullable=False),
        pa.field("mated_job_id", pa.string(), nullable=False),
        pa.field("status", pa.string(), nullable=False),
        pa.field("reasons", pa.list_(pa.string()), nullable=False),
        pa.field("eligibility_record_hash", pa.string(), nullable=False),
    ]
)


EVALUATION_VIEW_ENTRY_SCHEMA = pa.schema(
    [
        pa.field("ordinal", pa.int32(), nullable=False),
        pa.field("pair_id", pa.string(), nullable=False),
        pa.field("job_id", pa.string(), nullable=False),
        pa.field("source_result_hash", pa.string(), nullable=False),
        pa.field("decision_record_hash", pa.string(), nullable=False),
        pa.field("decision_status", pa.string(), nullable=False),
        pa.field("decision", pa.string(), nullable=True),
        pa.field("eligibility_unit_id", pa.string(), nullable=True),
        pa.field("eligibility_record_hash", pa.string(), nullable=True),
        pa.field("eligibility_status", pa.string(), nullable=True),
        pa.field("included", pa.bool_(), nullable=False),
        pa.field("exclusion_reason", pa.string(), nullable=True),
        pa.field("evaluation_entry_hash", pa.string(), nullable=False),
    ]
)


def _table(rows: list[dict], schema: pa.Schema) -> pa.Table:
    columns = {field.name: [row[field.name] for row in rows] for field in schema}
    return pa.table(columns, schema=schema)


# ---------------------------------------------------------------- decisions


def decisions_to_table(records: Iterable[DecisionRecord]) -> pa.Table:
    rows = [
        {
            "ordinal": record.ordinal,
            "job_id": record.job_id,
            "job_fingerprint": record.job_fingerprint,
            "pair_id": record.pair_id,
            "source_result_hash": record.source_result_hash,
            "result_set_id": record.result_set_id,
            "result_set_fingerprint": record.result_set_fingerprint,
            "decision_profile_id": record.decision_profile_id,
            "decision_profile_fingerprint": record.decision_profile_fingerprint,
            "application_status": record.application_status.value,
            "decision": record.decision.value if record.decision else None,
            "source_execution_status": record.source_execution_status.value,
            "source_failure_code": record.source_failure_code,
            "decision_record_hash": record.decision_record_hash,
        }
        for record in records
    ]
    return _table(rows, DECISION_RECORD_SCHEMA)


def table_to_decisions(table: pa.Table) -> list[DecisionRecord]:
    rows = sorted(table.to_pylist(), key=lambda row: row["ordinal"])
    return [
        DecisionRecord(
            ordinal=row["ordinal"],
            job_id=row["job_id"],
            job_fingerprint=row["job_fingerprint"],
            pair_id=row["pair_id"],
            source_result_hash=row["source_result_hash"],
            result_set_id=row["result_set_id"],
            result_set_fingerprint=row["result_set_fingerprint"],
            decision_profile_id=row["decision_profile_id"],
            decision_profile_fingerprint=row["decision_profile_fingerprint"],
            application_status=DecisionApplicationStatus(row["application_status"]),
            decision=DecisionValue(row["decision"]) if row["decision"] else None,
            source_execution_status=ExecutionStatus(row["source_execution_status"]),
            source_failure_code=row["source_failure_code"],
            decision_record_hash=row["decision_record_hash"],
        )
        for row in rows
    ]


# -------------------------------------------------------------- eligibility


def eligibility_to_table(
    records: Iterable[SelfEligibilityDecisionRecord],
) -> pa.Table:
    rows = [
        {
            "ordinal": record.ordinal,
            "eligibility_unit_id": record.eligibility_unit_id,
            "release": record.release,
            "canonical_finger": record.canonical_finger,
            "plain_self_pair_id": record.plain_self_pair_id,
            "plain_self_job_id": record.plain_self_job_id,
            "plain_self_decision_hash": record.plain_self_decision_hash,
            "plain_self_decision": (
                record.plain_self_decision.value
                if record.plain_self_decision
                else None
            ),
            "roll_self_pair_id": record.roll_self_pair_id,
            "roll_self_job_id": record.roll_self_job_id,
            "roll_self_decision_hash": record.roll_self_decision_hash,
            "roll_self_decision": (
                record.roll_self_decision.value if record.roll_self_decision else None
            ),
            "mated_pair_id": record.mated_pair_id,
            "mated_job_id": record.mated_job_id,
            "status": record.status.value,
            "reasons": [reason.value for reason in record.reasons],
            "eligibility_record_hash": record.eligibility_record_hash,
        }
        for record in records
    ]
    return _table(rows, ELIGIBILITY_RECORD_SCHEMA)


def table_to_eligibility(table: pa.Table) -> list[SelfEligibilityDecisionRecord]:
    rows = sorted(table.to_pylist(), key=lambda row: row["ordinal"])
    return [
        SelfEligibilityDecisionRecord(
            ordinal=row["ordinal"],
            eligibility_unit_id=row["eligibility_unit_id"],
            release=row["release"],
            canonical_finger=row["canonical_finger"],
            plain_self_pair_id=row["plain_self_pair_id"],
            plain_self_job_id=row["plain_self_job_id"],
            plain_self_decision_hash=row["plain_self_decision_hash"],
            plain_self_decision=(
                DecisionValue(row["plain_self_decision"])
                if row["plain_self_decision"]
                else None
            ),
            roll_self_pair_id=row["roll_self_pair_id"],
            roll_self_job_id=row["roll_self_job_id"],
            roll_self_decision_hash=row["roll_self_decision_hash"],
            roll_self_decision=(
                DecisionValue(row["roll_self_decision"])
                if row["roll_self_decision"]
                else None
            ),
            mated_pair_id=row["mated_pair_id"],
            mated_job_id=row["mated_job_id"],
            status=SelfEligibilityStatus(row["status"]),
            reasons=tuple(
                SelfEligibilityReason(value) for value in row["reasons"]
            ),
            eligibility_record_hash=row["eligibility_record_hash"],
        )
        for row in rows
    ]


# ------------------------------------------------------------------- views


def view_entries_to_table(entries: Iterable[EvaluationViewEntry]) -> pa.Table:
    rows = [
        {
            "ordinal": entry.ordinal,
            "pair_id": entry.pair_id,
            "job_id": entry.job_id,
            "source_result_hash": entry.source_result_hash,
            "decision_record_hash": entry.decision_record_hash,
            "decision_status": entry.decision_status.value,
            "decision": entry.decision.value if entry.decision else None,
            "eligibility_unit_id": entry.eligibility_unit_id,
            "eligibility_record_hash": entry.eligibility_record_hash,
            "eligibility_status": (
                entry.eligibility_status.value if entry.eligibility_status else None
            ),
            "included": entry.included,
            "exclusion_reason": entry.exclusion_reason,
            "evaluation_entry_hash": entry.evaluation_entry_hash,
        }
        for entry in entries
    ]
    return _table(rows, EVALUATION_VIEW_ENTRY_SCHEMA)


def table_to_view_entries(table: pa.Table) -> list[EvaluationViewEntry]:
    rows = sorted(table.to_pylist(), key=lambda row: row["ordinal"])
    return [
        EvaluationViewEntry(
            ordinal=row["ordinal"],
            pair_id=row["pair_id"],
            job_id=row["job_id"],
            source_result_hash=row["source_result_hash"],
            decision_record_hash=row["decision_record_hash"],
            decision_status=DecisionApplicationStatus(row["decision_status"]),
            decision=DecisionValue(row["decision"]) if row["decision"] else None,
            eligibility_unit_id=row["eligibility_unit_id"],
            eligibility_record_hash=row["eligibility_record_hash"],
            eligibility_status=(
                SelfEligibilityStatus(row["eligibility_status"])
                if row["eligibility_status"]
                else None
            ),
            included=row["included"],
            exclusion_reason=row["exclusion_reason"],
            evaluation_entry_hash=row["evaluation_entry_hash"],
        )
        for row in rows
    ]
