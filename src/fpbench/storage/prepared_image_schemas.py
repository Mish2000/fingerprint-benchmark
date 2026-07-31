"""The Arrow schema for a prepared-image set's entries.

Written out explicitly, like every other schema in this package, and with one
extra constraint the others do not need: every integer column is ``int64`` and
every round trip is checked for exactness. A prepared entry's integers are
integrity-bearing — a width that came back as ``500.0`` would still compare
equal to ``500`` in Python and would hash differently in ``entry_hash``, so the
reader rejects anything that is not an exact ``int`` rather than coercing it
(spec section 10).

``source_declared_ppi`` is the one nullable column. Most PNGs declare a physical
resolution and SD300C's is famously wrong, but a source with no ``pHYs`` at all
is perfectly legal and "absent" is not the same claim as "zero".
"""

from __future__ import annotations

from typing import Iterable

import pyarrow as pa

from fpbench.core.imaging_models import PreparedImageEntry
from fpbench.core.serialization import require_exact_int

__all__ = [
    "PREPARED_IMAGE_ENTRY_SCHEMA",
    "prepared_entries_to_table",
    "table_to_prepared_entries",
]

PREPARED_IMAGE_ENTRY_SCHEMA = pa.schema(
    [
        pa.field("ordinal", pa.int64(), nullable=False),
        pa.field("image_id", pa.string(), nullable=False),
        pa.field("source_record_fingerprint", pa.string(), nullable=False),
        pa.field("source_expected_sha256", pa.string(), nullable=False),
        pa.field("source_size_bytes", pa.int64(), nullable=False),
        pa.field("source_effective_ppi", pa.int64(), nullable=False),
        pa.field("source_declared_ppi", pa.string(), nullable=True),
        pa.field("source_width", pa.int64(), nullable=False),
        pa.field("source_height", pa.int64(), nullable=False),
        pa.field("source_pixel_sha256", pa.string(), nullable=False),
        pa.field("transform_profile_id", pa.string(), nullable=False),
        pa.field("transform_profile_fingerprint", pa.string(), nullable=False),
        pa.field("transform_runtime_fingerprint", pa.string(), nullable=False),
        pa.field("transform_action", pa.string(), nullable=False),
        pa.field("scale_numerator", pa.int64(), nullable=False),
        pa.field("scale_denominator", pa.int64(), nullable=False),
        pa.field("output_width", pa.int64(), nullable=False),
        pa.field("output_height", pa.int64(), nullable=False),
        pa.field("output_effective_ppi", pa.int64(), nullable=False),
        pa.field("output_pixel_sha256", pa.string(), nullable=False),
        pa.field("output_encoded_sha256", pa.string(), nullable=False),
        pa.field("output_size_bytes", pa.int64(), nullable=False),
        pa.field("output_media_type", pa.string(), nullable=False),
        pa.field("relative_path", pa.string(), nullable=False),
        pa.field("entry_hash", pa.string(), nullable=False),
    ]
)

_INTEGER_COLUMNS = frozenset(
    field.name
    for field in PREPARED_IMAGE_ENTRY_SCHEMA
    if pa.types.is_integer(field.type)
)


def prepared_entries_to_table(entries: Iterable[PreparedImageEntry]) -> pa.Table:
    rows = [
        {
            "ordinal": entry.ordinal,
            "image_id": str(entry.image_id),
            "source_record_fingerprint": entry.source_record_fingerprint,
            "source_expected_sha256": entry.source_expected_sha256,
            "source_size_bytes": entry.source_size_bytes,
            "source_effective_ppi": entry.source_effective_ppi,
            "source_declared_ppi": entry.source_declared_ppi,
            "source_width": entry.source_width,
            "source_height": entry.source_height,
            "source_pixel_sha256": entry.source_pixel_sha256,
            "transform_profile_id": entry.transform_profile_id,
            "transform_profile_fingerprint": entry.transform_profile_fingerprint,
            "transform_runtime_fingerprint": entry.transform_runtime_fingerprint,
            "transform_action": entry.transform_action,
            "scale_numerator": entry.scale_numerator,
            "scale_denominator": entry.scale_denominator,
            "output_width": entry.output_width,
            "output_height": entry.output_height,
            "output_effective_ppi": entry.output_effective_ppi,
            "output_pixel_sha256": entry.output_pixel_sha256,
            "output_encoded_sha256": entry.output_encoded_sha256,
            "output_size_bytes": entry.output_size_bytes,
            "output_media_type": entry.output_media_type,
            "relative_path": entry.relative_path,
            "entry_hash": entry.entry_hash,
        }
        for entry in entries
    ]
    columns = {
        field.name: [row[field.name] for row in rows]
        for field in PREPARED_IMAGE_ENTRY_SCHEMA
    }
    return pa.table(columns, schema=PREPARED_IMAGE_ENTRY_SCHEMA)


def table_to_prepared_entries(table: pa.Table) -> list[PreparedImageEntry]:
    """Rebuild entries, sorted by ordinal, with every integer checked exactly.

    Sorting rather than trusting row order means a set survives being rewritten
    by any tool that does not preserve it — and order is part of the set's
    identity, so recovering it has to be deterministic.
    """
    if table.schema != PREPARED_IMAGE_ENTRY_SCHEMA:
        raise ValueError(
            "the entries table does not carry the prepared-image entry schema; "
            "a column added, removed or retyped changes what a row means"
        )
    rows = sorted(table.to_pylist(), key=lambda row: row["ordinal"])
    entries: list[PreparedImageEntry] = []
    for row in rows:
        for column in _INTEGER_COLUMNS:
            require_exact_int(row[column], column)
        entries.append(
            PreparedImageEntry(
                ordinal=row["ordinal"],
                image_id=row["image_id"],
                source_record_fingerprint=row["source_record_fingerprint"],
                source_expected_sha256=row["source_expected_sha256"],
                source_size_bytes=row["source_size_bytes"],
                source_effective_ppi=row["source_effective_ppi"],
                source_declared_ppi=row["source_declared_ppi"],
                source_width=row["source_width"],
                source_height=row["source_height"],
                source_pixel_sha256=row["source_pixel_sha256"],
                transform_profile_id=row["transform_profile_id"],
                transform_profile_fingerprint=row["transform_profile_fingerprint"],
                transform_runtime_fingerprint=row["transform_runtime_fingerprint"],
                transform_action=row["transform_action"],
                scale_numerator=row["scale_numerator"],
                scale_denominator=row["scale_denominator"],
                output_width=row["output_width"],
                output_height=row["output_height"],
                output_effective_ppi=row["output_effective_ppi"],
                output_pixel_sha256=row["output_pixel_sha256"],
                output_encoded_sha256=row["output_encoded_sha256"],
                output_size_bytes=row["output_size_bytes"],
                output_media_type=row["output_media_type"],
                relative_path=row["relative_path"],
                entry_hash=row["entry_hash"],
            )
        )
    return entries
