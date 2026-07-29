"""The Arrow schema for a stored raw result, and its conversions.

Written out in full rather than inferred, for the same reason the manifest
schemas are: a column type that depends on whether a particular batch happened
to contain a null is not an interface anyone can rely on.

``failure``, ``timings`` and ``artifacts`` are real nested types — structs,
maps and lists — not JSON blobs in a string column. A failure taxonomy that can
only be read by parsing text is a taxonomy nobody will query, and the whole
point of separating failure from non-match (docs/adr/0006) is that failures get
analysed.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

import pyarrow as pa

from fpbench.core.enums import (
    ExecutionStatus,
    FailureCode,
    FailureStage,
    ScoreDirection,
)
from fpbench.core.execution_models import (
    ArtifactReference,
    FailureInfo,
    TimingBreakdown,
)
from fpbench.core.identifiers import CohortId, ImageId, PairId
from fpbench.core.result_models import RawResultRecord

__all__ = [
    "RAW_RESULT_SCHEMA",
    "raw_results_to_table",
    "table_to_raw_results",
]

_STRING_MAP = pa.map_(pa.string(), pa.string())
_TIMING_MAP = pa.map_(pa.string(), pa.float64())

_FAILURE_STRUCT = pa.struct(
    [
        pa.field("code", pa.string(), nullable=False),
        pa.field("stage", pa.string(), nullable=False),
        pa.field("message", pa.string(), nullable=False),
        pa.field("retryable", pa.bool_(), nullable=False),
        pa.field("details", _STRING_MAP, nullable=False),
    ]
)

_TIMINGS_STRUCT = pa.struct(
    [
        pa.field("preparation_ms", pa.float64(), nullable=False),
        pa.field("adapter_ms", pa.float64(), nullable=False),
        pa.field("total_ms", pa.float64(), nullable=False),
        pa.field("adapter_components_ms", _TIMING_MAP, nullable=False),
    ]
)

_ARTIFACT_STRUCT = pa.struct(
    [
        pa.field("artifact_id", pa.string(), nullable=False),
        pa.field("kind", pa.string(), nullable=False),
        pa.field("relative_path", pa.string(), nullable=False),
        pa.field("sha256", pa.string(), nullable=False),
        pa.field("size_bytes", pa.int64(), nullable=False),
        pa.field("media_type", pa.string(), nullable=True),
        pa.field("metadata", _STRING_MAP, nullable=False),
    ]
)

RAW_RESULT_SCHEMA = pa.schema(
    [
        pa.field("result_id", pa.string(), nullable=False),
        pa.field("run_id", pa.string(), nullable=False),
        pa.field("job_id", pa.string(), nullable=False),
        pa.field("job_fingerprint", pa.string(), nullable=False),
        pa.field("protocol_id", pa.string(), nullable=False),
        pa.field("cohort_id", pa.string(), nullable=False),
        pa.field("pair_manifest_hash", pa.string(), nullable=False),
        pa.field("pair_id", pa.string(), nullable=False),
        pa.field("left_image_id", pa.string(), nullable=False),
        pa.field("right_image_id", pa.string(), nullable=False),
        pa.field("algorithm_id", pa.string(), nullable=False),
        pa.field("algorithm_fingerprint", pa.string(), nullable=False),
        pa.field("execution_profile_id", pa.string(), nullable=False),
        pa.field("execution_profile_hash", pa.string(), nullable=False),
        pa.field("attempt", pa.int32(), nullable=False),
        pa.field("started_utc", pa.string(), nullable=False),
        pa.field("finished_utc", pa.string(), nullable=False),
        pa.field("status", pa.string(), nullable=False),
        # Null exactly when status is failure; never a sentinel value, because
        # a sentinel score would be indistinguishable from a real one.
        pa.field("raw_score", pa.float64(), nullable=True),
        pa.field("score_direction", pa.string(), nullable=False),
        pa.field("failure", _FAILURE_STRUCT, nullable=True),
        pa.field("timings", _TIMINGS_STRUCT, nullable=False),
        pa.field("artifacts", pa.list_(_ARTIFACT_STRUCT), nullable=False),
        pa.field("adapter_metadata", _STRING_MAP, nullable=False),
        pa.field("runner_metadata", _STRING_MAP, nullable=False),
    ]
)


def _failure_to_row(failure: FailureInfo | None) -> dict[str, Any] | None:
    if failure is None:
        return None
    return {
        "code": failure.code.value,
        "stage": failure.stage.value,
        "message": failure.message,
        "retryable": failure.retryable,
        "details": dict(failure.details),
    }


def _row_to_failure(row: Mapping[str, Any] | None) -> FailureInfo | None:
    if row is None:
        return None
    return FailureInfo(
        code=FailureCode(row["code"]),
        stage=FailureStage(row["stage"]),
        message=row["message"],
        retryable=row["retryable"],
        details=_as_str_dict(row["details"]),
    )


def _artifact_to_row(artifact: ArtifactReference) -> dict[str, Any]:
    return {
        "artifact_id": artifact.artifact_id,
        "kind": artifact.kind,
        "relative_path": artifact.relative_path,
        "sha256": artifact.sha256,
        "size_bytes": artifact.size_bytes,
        "media_type": artifact.media_type,
        "metadata": dict(artifact.metadata),
    }


def _row_to_artifact(row: Mapping[str, Any]) -> ArtifactReference:
    return ArtifactReference(
        artifact_id=row["artifact_id"],
        kind=row["kind"],
        relative_path=row["relative_path"],
        sha256=row["sha256"],
        size_bytes=row["size_bytes"],
        media_type=row["media_type"],
        metadata=_as_str_dict(row["metadata"]),
    )


def _as_str_dict(value: Any) -> dict[str, str]:
    """Arrow hands maps back as a list of key/value tuples."""
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return {str(k): str(v) for k, v in value.items()}
    return {str(k): str(v) for k, v in value}


def _as_float_dict(value: Any) -> dict[str, float]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return {str(k): float(v) for k, v in value.items()}
    return {str(k): float(v) for k, v in value}


def raw_results_to_table(records: Iterable[RawResultRecord]) -> pa.Table:
    rows: Sequence[Mapping[str, Any]] = [
        {
            "result_id": record.result_id,
            "run_id": record.run_id,
            "job_id": record.job_id,
            "job_fingerprint": record.job_fingerprint,
            "protocol_id": record.protocol_id,
            "cohort_id": str(record.cohort_id),
            "pair_manifest_hash": record.pair_manifest_hash,
            "pair_id": str(record.pair_id),
            "left_image_id": str(record.left_image_id),
            "right_image_id": str(record.right_image_id),
            "algorithm_id": record.algorithm_id,
            "algorithm_fingerprint": record.algorithm_fingerprint,
            "execution_profile_id": record.execution_profile_id,
            "execution_profile_hash": record.execution_profile_hash,
            "attempt": record.attempt,
            "started_utc": record.started_utc,
            "finished_utc": record.finished_utc,
            "status": record.status.value,
            "raw_score": record.raw_score,
            "score_direction": record.score_direction.value,
            "failure": _failure_to_row(record.failure),
            "timings": {
                "preparation_ms": record.timings.preparation_ms,
                "adapter_ms": record.timings.adapter_ms,
                "total_ms": record.timings.total_ms,
                "adapter_components_ms": dict(record.timings.adapter_components_ms),
            },
            "artifacts": [_artifact_to_row(a) for a in record.artifacts],
            "adapter_metadata": dict(record.adapter_metadata),
            "runner_metadata": dict(record.runner_metadata),
        }
        for record in records
    ]
    columns = {
        field.name: [row[field.name] for row in rows] for field in RAW_RESULT_SCHEMA
    }
    return pa.table(columns, schema=RAW_RESULT_SCHEMA)


def table_to_raw_results(table: pa.Table) -> list[RawResultRecord]:
    records = []
    for row in table.to_pylist():
        timings = row["timings"]
        records.append(
            RawResultRecord(
                result_id=row["result_id"],
                run_id=row["run_id"],
                job_id=row["job_id"],
                job_fingerprint=row["job_fingerprint"],
                protocol_id=row["protocol_id"],
                cohort_id=CohortId(row["cohort_id"]),
                pair_manifest_hash=row["pair_manifest_hash"],
                pair_id=PairId(row["pair_id"]),
                left_image_id=ImageId(row["left_image_id"]),
                right_image_id=ImageId(row["right_image_id"]),
                algorithm_id=row["algorithm_id"],
                algorithm_fingerprint=row["algorithm_fingerprint"],
                execution_profile_id=row["execution_profile_id"],
                execution_profile_hash=row["execution_profile_hash"],
                attempt=row["attempt"],
                started_utc=row["started_utc"],
                finished_utc=row["finished_utc"],
                status=ExecutionStatus(row["status"]),
                raw_score=row["raw_score"],
                score_direction=ScoreDirection(row["score_direction"]),
                failure=_row_to_failure(row["failure"]),
                timings=TimingBreakdown(
                    preparation_ms=timings["preparation_ms"],
                    adapter_ms=timings["adapter_ms"],
                    total_ms=timings["total_ms"],
                    adapter_components_ms=_as_float_dict(
                        timings["adapter_components_ms"]
                    ),
                ),
                artifacts=tuple(
                    _row_to_artifact(a) for a in (row["artifacts"] or ())
                ),
                adapter_metadata=_as_str_dict(row["adapter_metadata"]),
                runner_metadata=_as_str_dict(row["runner_metadata"]),
            )
        )
    return records
