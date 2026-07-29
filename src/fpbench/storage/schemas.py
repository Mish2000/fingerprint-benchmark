"""Arrow schemas for the manifests, and conversion to and from core models.

The schemas are written out explicitly rather than inferred. Inference would
silently change a column type when a manifest happens to contain no nulls, and
a manifest whose type depends on its contents is not a stable interface.

Enum columns are stored as their string values and small integer codes, not as
dictionary indices: a manifest should stay readable by anything that can open
a parquet file, including tools that know nothing about this project.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

import pyarrow as pa

from fpbench.core.enums import (
    ChecksumStatus,
    FingerprintPosition,
    GroundTruth,
    Impression,
    ProtocolStage,
)
from fpbench.core.identifiers import ImageId, PairId, SubjectId
from fpbench.core.models import (
    ComparisonPair,
    ImageRecord,
    SelfEligibilityRecord,
    SubjectRecord,
)

__all__ = [
    "IMAGE_SCHEMA",
    "SUBJECT_SCHEMA",
    "PAIR_SCHEMA",
    "SELF_ELIGIBILITY_SCHEMA",
    "images_to_table",
    "table_to_images",
    "subjects_to_table",
    "table_to_subjects",
    "pairs_to_table",
    "table_to_pairs",
    "self_eligibility_to_table",
    "table_to_self_eligibility",
]

IMAGE_SCHEMA = pa.schema(
    [
        pa.field("image_id", pa.string(), nullable=False),
        pa.field("dataset_id", pa.string(), nullable=False),
        pa.field("release", pa.string(), nullable=False),
        pa.field("subject_id", pa.string(), nullable=False),
        pa.field("impression", pa.string(), nullable=False),
        # Null for simultaneous-capture slaps and unrecognised position codes.
        pa.field("position", pa.int8(), nullable=True),
        pa.field("is_multi_finger", pa.bool_(), nullable=False),
        pa.field("relative_path", pa.string(), nullable=False),
        pa.field("effective_ppi", pa.int32(), nullable=False),
        # What the file declares; null when its header could not be read.
        pa.field("metadata_ppi", pa.int32(), nullable=True),
        pa.field("expected_sha256", pa.string(), nullable=False),
        pa.field("checksum_status", pa.string(), nullable=False),
        pa.field("metadata", pa.map_(pa.string(), pa.string()), nullable=False),
        pa.field("anomalies", pa.list_(pa.string()), nullable=False),
        pa.field("blocking_issues", pa.list_(pa.string()), nullable=False),
    ]
)

SUBJECT_SCHEMA = pa.schema(
    [
        pa.field("subject_id", pa.string(), nullable=False),
        pa.field("dataset_id", pa.string(), nullable=False),
        pa.field("release", pa.string(), nullable=False),
        pa.field("image_count", pa.int32(), nullable=False),
        pa.field("plain_positions", pa.list_(pa.int8()), nullable=False),
        pa.field("roll_positions", pa.list_(pa.int8()), nullable=False),
        pa.field("multi_finger_count", pa.int32(), nullable=False),
    ]
)

PAIR_SCHEMA = pa.schema(
    [
        pa.field("pair_id", pa.string(), nullable=False),
        pa.field("dataset_id", pa.string(), nullable=False),
        pa.field("release", pa.string(), nullable=False),
        pa.field("left_image_id", pa.string(), nullable=False),
        pa.field("right_image_id", pa.string(), nullable=False),
        pa.field("ground_truth", pa.string(), nullable=False),
        pa.field("protocol_stage", pa.string(), nullable=False),
    ]
)

SELF_ELIGIBILITY_SCHEMA = pa.schema(
    [
        pa.field("release", pa.string(), nullable=False),
        pa.field("subject_id", pa.string(), nullable=False),
        pa.field("finger_position", pa.int8(), nullable=False),
        pa.field("plain_self_passed", pa.bool_(), nullable=False),
        pa.field("roll_self_passed", pa.bool_(), nullable=False),
        pa.field("eligible", pa.bool_(), nullable=False),
        pa.field("exclusion_reason", pa.string(), nullable=True),
    ]
)


def _table(rows: Sequence[Mapping[str, Any]], schema: pa.Schema) -> pa.Table:
    columns = {
        field.name: [row[field.name] for row in rows] for field in schema
    }
    return pa.table(columns, schema=schema)


def _as_dict(value: Any) -> dict[str, str]:
    """Arrow returns maps as a list of key/value tuples."""
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    return {str(k): str(v) for k, v in value}


# ---------------------------------------------------------------------- images


def images_to_table(images: Iterable[ImageRecord]) -> pa.Table:
    rows = [
        {
            "image_id": str(image.image_id),
            "dataset_id": image.dataset_id,
            "release": image.release,
            "subject_id": str(image.subject_id),
            "impression": image.impression.value,
            "position": int(image.position) if image.position is not None else None,
            "is_multi_finger": image.is_multi_finger,
            "relative_path": image.relative_path,
            "effective_ppi": image.effective_ppi,
            "metadata_ppi": image.metadata_ppi,
            "expected_sha256": image.expected_sha256,
            "checksum_status": image.checksum_status.value,
            "metadata": dict(image.metadata),
            "anomalies": list(image.anomalies),
            "blocking_issues": list(image.blocking_issues),
        }
        for image in images
    ]
    return _table(rows, IMAGE_SCHEMA)


def table_to_images(table: pa.Table) -> list[ImageRecord]:
    return [
        ImageRecord(
            image_id=ImageId(row["image_id"]),
            dataset_id=row["dataset_id"],
            release=row["release"],
            subject_id=SubjectId(row["subject_id"]),
            impression=Impression(row["impression"]),
            position=(
                FingerprintPosition(row["position"])
                if row["position"] is not None
                else None
            ),
            is_multi_finger=row["is_multi_finger"],
            relative_path=row["relative_path"],
            effective_ppi=row["effective_ppi"],
            metadata_ppi=row["metadata_ppi"],
            expected_sha256=row["expected_sha256"],
            checksum_status=ChecksumStatus(row["checksum_status"]),
            metadata=_as_dict(row["metadata"]),
            anomalies=tuple(row["anomalies"] or ()),
            blocking_issues=tuple(row["blocking_issues"] or ()),
        )
        for row in table.to_pylist()
    ]


# -------------------------------------------------------------------- subjects


def subjects_to_table(subjects: Iterable[SubjectRecord]) -> pa.Table:
    rows = [
        {
            "subject_id": str(subject.subject_id),
            "dataset_id": subject.dataset_id,
            "release": subject.release,
            "image_count": subject.image_count,
            "plain_positions": [int(p) for p in subject.plain_positions],
            "roll_positions": [int(p) for p in subject.roll_positions],
            "multi_finger_count": subject.multi_finger_count,
        }
        for subject in subjects
    ]
    return _table(rows, SUBJECT_SCHEMA)


def table_to_subjects(table: pa.Table) -> list[SubjectRecord]:
    return [
        SubjectRecord(
            subject_id=SubjectId(row["subject_id"]),
            dataset_id=row["dataset_id"],
            release=row["release"],
            image_count=row["image_count"],
            plain_positions=tuple(
                FingerprintPosition(p) for p in row["plain_positions"]
            ),
            roll_positions=tuple(FingerprintPosition(p) for p in row["roll_positions"]),
            multi_finger_count=row["multi_finger_count"],
        )
        for row in table.to_pylist()
    ]


# ----------------------------------------------------------------------- pairs


def pairs_to_table(pairs: Iterable[ComparisonPair]) -> pa.Table:
    rows = [
        {
            "pair_id": str(pair.pair_id),
            "dataset_id": pair.dataset_id,
            "release": pair.release,
            "left_image_id": str(pair.left_image_id),
            "right_image_id": str(pair.right_image_id),
            "ground_truth": pair.ground_truth.value,
            "protocol_stage": pair.protocol_stage.value,
        }
        for pair in pairs
    ]
    return _table(rows, PAIR_SCHEMA)


def table_to_pairs(table: pa.Table) -> list[ComparisonPair]:
    return [
        ComparisonPair(
            pair_id=PairId(row["pair_id"]),
            dataset_id=row["dataset_id"],
            release=row["release"],
            left_image_id=ImageId(row["left_image_id"]),
            right_image_id=ImageId(row["right_image_id"]),
            ground_truth=GroundTruth(row["ground_truth"]),
            protocol_stage=ProtocolStage(row["protocol_stage"]),
        )
        for row in table.to_pylist()
    ]


# ------------------------------------------------------------ SELF decisions


def self_eligibility_to_table(
    records: Iterable[SelfEligibilityRecord],
) -> pa.Table:
    rows = [
        {
            "release": record.release,
            "subject_id": str(record.subject_id),
            "finger_position": int(record.finger_position),
            "plain_self_passed": record.plain_self_passed,
            "roll_self_passed": record.roll_self_passed,
            "eligible": record.eligible,
            "exclusion_reason": record.exclusion_reason,
        }
        for record in records
    ]
    return _table(rows, SELF_ELIGIBILITY_SCHEMA)


def table_to_self_eligibility(table: pa.Table) -> list[SelfEligibilityRecord]:
    return [
        SelfEligibilityRecord(
            release=row["release"],
            subject_id=SubjectId(row["subject_id"]),
            finger_position=FingerprintPosition(row["finger_position"]),
            plain_self_passed=row["plain_self_passed"],
            roll_self_passed=row["roll_self_passed"],
            eligible=row["eligible"],
            exclusion_reason=row["exclusion_reason"],
        )
        for row in table.to_pylist()
    ]
