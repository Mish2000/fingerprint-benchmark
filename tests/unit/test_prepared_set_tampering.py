"""Change one thing in a finished set, and it must stop verifying.

Fifteen separate edits, each of them the kind of thing that could plausibly
happen by accident: a manifest hand-edited to fix a typo, a PNG re-saved by an
image viewer, a parquet file rewritten by a tool that reordered the rows. None
of them is malicious and every one of them makes the set a different set.

The property is uniform: after any of these, verification reports issues and the
status is ``INVALID`` — never ``PARTIAL``, which would suggest materialising
more images would help, and never quietly repaired.
"""

from __future__ import annotations

import dataclasses
import json
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from fpbench.core.enums import PreparationStatus
from fpbench.core.imaging_models import (
    PREPARATION_TRANSFORM_AUDIT_SCHEMA_VERSION,
    PreparationTransformAudit,
    PreparedImageEntry,
    PreparedImageSetManifest,
    ordered_prepared_entries_hash,
    preparation_set_fingerprint,
    preparation_set_id,
    preparation_transform_audit_fingerprint,
    prepared_image_entry_hash,
)
from fpbench.core.serialization import write_json
from fpbench.imaging.status import inspect_preparation
from fpbench.imaging.verify import verify_prepared_image_set
from canonicalworld import build_canonical_world, publish_receipt_and_marker

pytestmark = [pytest.mark.imaging, pytest.mark.canonical500]


@pytest.fixture()
def world(tmp_path):
    built = build_canonical_world(tmp_path)
    publish_receipt_and_marker(built)
    return built


def _verify(world):
    return verify_prepared_image_set(
        store=world.store,
        preparation_set_id_value=world.preparation_set_id,
        images=world.images,
        dataset_root=world.dataset_root,
        source_bundle=world.source_bundle,
    )


def _status(world):
    return inspect_preparation(
        store=world.store,
        definition=world.definition,
        images=world.images,
        dataset_root=world.dataset_root,
        source_bundle=world.source_bundle,
    )


def _writable(path: Path) -> Path:
    path.chmod(path.stat().st_mode | stat.S_IWUSR)
    return path


def _edit_json(path: Path, **changes):
    payload = json.loads(path.read_text("utf-8"))
    payload.update(changes)
    write_json(path, payload)


def _edit_entries_parquet(world, index: int, **changes):
    """Rewrite the entries table with one row altered.

    The row is written straight through pyarrow rather than through the store,
    because the store would refuse — which is the point: the tamper has to be
    something that could reach the disk.
    """
    import pyarrow.parquet as pq

    from fpbench.storage.prepared_image_schemas import PREPARED_IMAGE_ENTRY_SCHEMA

    path = world.store.entries_table_path(world.preparation_set_id)
    with pq.ParquetFile(path) as reader:
        table = reader.read()
    rows = table.to_pylist()
    rows[index].update(changes)
    import pyarrow as pa

    columns = {
        field.name: [row[field.name] for row in rows]
        for field in PREPARED_IMAGE_ENTRY_SCHEMA
    }
    pq.write_table(
        pa.table(columns, schema=PREPARED_IMAGE_ENTRY_SCHEMA), path, compression="zstd"
    )


def _replace_output(
    victim: PreparedImageEntry, replacement: PreparedImageEntry
) -> PreparedImageEntry:
    fields = {
        field.name: getattr(victim, field.name)
        for field in dataclasses.fields(victim)
        if field.name != "entry_hash"
    }
    fields.update(
        output_pixel_sha256=replacement.output_pixel_sha256,
        output_encoded_sha256=replacement.output_encoded_sha256,
        output_size_bytes=replacement.output_size_bytes,
        relative_path=replacement.relative_path,
    )
    return PreparedImageEntry(
        **fields,
        entry_hash=prepared_image_entry_hash(SimpleNamespace(**fields)),
    )


def _assert_invalid(world):
    verification = _verify(world)
    assert not verification.is_valid, "the tampered set still verified"
    assert _status(world).status is PreparationStatus.INVALID


def test_a_baseline_set_verifies(world):
    verification = _verify(world)
    assert verification.is_valid
    assert verification.transform_audit is not None
    audit = verification.transform_audit
    assert audit.is_clean
    assert audit.planned_images == audit.verified_sources
    assert audit.planned_images == audit.recomputed_transforms
    assert audit.planned_images == audit.matching_pixel_hashes
    assert audit.planned_images == audit.matching_encoded_hashes
    assert _status(world).status is PreparationStatus.PREPARATION_READY


def test_self_consistent_valid_png_substitution_fails_fresh_transform_audit(world):
    """Rehashing every stored claim cannot turn the wrong B/C raster into Lanczos."""
    victim = next(entry for entry in world.entries if not entry.is_identity)
    replacement = next(
        entry
        for entry in world.entries
        if entry.image_id != victim.image_id
        and entry.source_effective_ppi == victim.source_effective_ppi
    )
    changed = _replace_output(victim, replacement)
    entries = tuple(
        changed if item.image_id == victim.image_id else item
        for item in world.entries
    )
    fingerprint = preparation_set_fingerprint(
        dataset_id=world.manifest.dataset_id,
        image_manifest_hash=world.manifest.image_manifest_hash,
        protocol_id=world.manifest.protocol_id,
        cohort_id=world.manifest.cohort_id,
        cohort_fingerprint=world.manifest.cohort_fingerprint,
        pair_manifest_hash=world.manifest.pair_manifest_hash,
        transform_profile_fingerprint=world.profile.profile_fingerprint,
        transform_runtime_fingerprint=world.runtime.runtime_fingerprint,
        entries=entries,
    )
    manifest = PreparedImageSetManifest(
        **{
            **{
                field.name: getattr(world.manifest, field.name)
                for field in dataclasses.fields(world.manifest)
            },
            "preparation_set_id": preparation_set_id(fingerprint),
            "preparation_set_fingerprint": fingerprint,
            "ordered_entries_hash": ordered_prepared_entries_hash(entries),
        }
    )
    store = world.store
    store.ensure_manifest(
        manifest=manifest,
        entries=entries,
        profile=world.profile,
        runtime=world.runtime,
        definition=world.definition,
    )

    claims = {
        "schema_version": PREPARATION_TRANSFORM_AUDIT_SCHEMA_VERSION,
        "preparation_set_id": manifest.preparation_set_id,
        "preparation_set_fingerprint": manifest.preparation_set_fingerprint,
        "planned_images": len(entries),
        "verified_sources": len(entries),
        "recomputed_transforms": len(entries),
        "matching_output_dimensions": len(entries),
        "matching_transform_actions": len(entries),
        "matching_pixel_hashes": len(entries),
        "matching_encoded_hashes": len(entries),
        "issues": (),
    }
    audit = PreparationTransformAudit(
        **claims,
        audit_fingerprint=preparation_transform_audit_fingerprint(claims),
        created_utc=world.manifest.created_utc,
    )
    store.ensure_transform_audit(
        preparation_set_id=manifest.preparation_set_id, audit=audit
    )

    from fpbench.experiments.preparation_receipt import (
        build_preparation_finalization_marker,
        build_preparation_receipt,
    )
    from fpbench.storage.prepared_image_set_store import (
        preparation_summary_content_hash,
    )

    summary = {
        "preparation_set_id": manifest.preparation_set_id,
        "total_images": len(entries),
        "generated_utc": world.manifest.created_utc,
    }
    store.ensure_summary(
        preparation_set_id=manifest.preparation_set_id, summary=summary
    )
    receipt = build_preparation_receipt(
        manifest=manifest,
        entries=entries,
        profile=world.profile,
        runtime=world.runtime,
        audit=audit,
        images=world.images,
    )
    store.ensure_receipt(
        preparation_set_id=manifest.preparation_set_id, receipt=receipt
    )
    marker = build_preparation_finalization_marker(
        manifest=manifest,
        profile=world.profile,
        runtime=world.runtime,
        receipt=receipt,
        audit=audit,
        entries_table_content_hash=store.entries_table_content_hash(
            manifest.preparation_set_id
        ),
        summary_content_hash=preparation_summary_content_hash(summary),
    )
    store.ensure_finalization(
        preparation_set_id=manifest.preparation_set_id, marker=marker
    )

    verification = verify_prepared_image_set(
        store=store,
        preparation_set_id_value=manifest.preparation_set_id,
        images=world.images,
        dataset_root=world.dataset_root,
        source_bundle=world.source_bundle,
    )
    assert not verification.is_valid
    assert any(
        "re-running the transform produces raster" in issue
        for issue in verification.issues
    )


def test_tampering_with_a_source_file(world):
    entry = world.entries[0]
    record = world.images[entry.image_id]
    path = world.dataset_root / record.relative_path
    _writable(path).write_bytes(path.read_bytes()[:-8] + b"\x00" * 8)
    _assert_invalid(world)


def test_tampering_with_a_source_digest_claim(world):
    _edit_entries_parquet(world, 0, source_expected_sha256="a" * 64)
    _assert_invalid(world)


def test_tampering_with_a_recorded_source_resolution(world):
    _edit_entries_parquet(world, 0, source_effective_ppi=1000)
    _assert_invalid(world)


def test_tampering_with_recorded_source_dimensions(world):
    _edit_entries_parquet(world, 0, source_width=999)
    _assert_invalid(world)


def test_tampering_with_recorded_output_dimensions(world):
    _edit_entries_parquet(world, 0, output_width=999)
    _assert_invalid(world)


def test_tampering_with_a_pixel_hash(world):
    _edit_entries_parquet(world, 0, output_pixel_sha256="b" * 64)
    _assert_invalid(world)


def test_tampering_with_an_encoded_hash(world):
    _edit_entries_parquet(world, 0, output_encoded_sha256="c" * 64)
    _assert_invalid(world)


def test_tampering_with_an_entry_hash(world):
    _edit_entries_parquet(world, 0, entry_hash="d" * 64)
    _assert_invalid(world)


def test_tampering_with_the_entry_order(world):
    """Two rows swapped: same images, different ordered hash, different set."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    from fpbench.storage.prepared_image_schemas import PREPARED_IMAGE_ENTRY_SCHEMA

    path = world.store.entries_table_path(world.preparation_set_id)
    with pq.ParquetFile(path) as reader:
        table = reader.read()
    rows = table.to_pylist()
    rows[0]["ordinal"], rows[1]["ordinal"] = rows[1]["ordinal"], rows[0]["ordinal"]
    columns = {
        field.name: [row[field.name] for row in rows]
        for field in PREPARED_IMAGE_ENTRY_SCHEMA
    }
    pq.write_table(
        pa.table(columns, schema=PREPARED_IMAGE_ENTRY_SCHEMA), path, compression="zstd"
    )
    _assert_invalid(world)


def test_tampering_with_one_byte_of_a_canonical_png(world):
    entry = world.entries[0]
    path = world.artifact_path(entry)
    data = bytearray(path.read_bytes())
    data[-5] ^= 0xFF
    _writable(path).write_bytes(bytes(data))
    _assert_invalid(world)


def test_tampering_with_a_canonical_png_phys(world):
    """Same pixels, a resolution the file no longer has the right to declare."""
    import io

    from PIL import Image

    entry = world.entries[0]
    path = world.artifact_path(entry)
    with Image.open(io.BytesIO(path.read_bytes())) as image:
        image.load()
        raster = image.tobytes()
        size = image.size
    buffer = io.BytesIO()
    with Image.frombytes("L", size, raster) as image:
        image.save(buffer, format="PNG", optimize=False, compress_level=9,
                   dpi=(1000, 1000))
    _writable(path).write_bytes(buffer.getvalue())
    _assert_invalid(world)


def test_tampering_with_a_canonical_png_chunk_set(world):
    """A text chunk added: same pixels, a file that may not be published."""
    import struct
    import zlib

    entry = world.entries[0]
    path = world.artifact_path(entry)
    data = path.read_bytes()
    body = b"Comment\x00added later"
    chunk = (
        struct.pack(">I", len(body))
        + b"tEXt"
        + body
        + struct.pack(">I", zlib.crc32(b"tEXt" + body) & 0xFFFFFFFF)
    )
    index = data.index(b"IDAT") - 4
    _writable(path).write_bytes(data[:index] + chunk + data[index:])
    _assert_invalid(world)


def test_tampering_with_the_manifest_fingerprint(world):
    path = world.store.manifest_path(world.preparation_set_id)
    payload = json.loads(path.read_text("utf-8"))
    payload["ordered_entries_hash"] = "e" * 64
    write_json(path, payload)
    _assert_invalid(world)


def test_tampering_with_the_stored_runtime(world):
    from canonicalworld import make_runtime

    path = world.store.set_dir(world.preparation_set_id) / "transform-runtime.json"
    other = make_runtime(pillow_version="99.0.0")
    write_json(path, other)
    _assert_invalid(world)


def test_tampering_with_the_stored_profile(world):
    path = world.store.set_dir(world.preparation_set_id) / "transform-profile.json"
    payload = json.loads(path.read_text("utf-8"))
    payload["forbidden_operations"]["sharpen"] = False
    write_json(path, payload)
    _assert_invalid(world)


def test_tampering_with_a_receipt_field(world):
    path = world.store.receipt_path(world.preparation_set_id)
    _edit_json(path, total_images=99999)
    _assert_invalid(world)


def test_tampering_with_the_finalization_marker(world):
    path = world.store.finalization_path(world.preparation_set_id)
    _edit_json(path, receipt_content_hash="f" * 64)
    _assert_invalid(world)


def test_deleting_a_canonical_artefact(world):
    entry = world.entries[0]
    path = world.artifact_path(entry)
    _writable(path).unlink()
    _assert_invalid(world)


def test_replacing_the_summary(world):
    world.store.summary_path(world.preparation_set_id).write_text(
        json.dumps({"preparation_set_id": world.preparation_set_id,
                    "total_images": 1, "generated_utc": "2020-01-01T00:00:00+00:00"}),
        encoding="utf-8",
    )
    _assert_invalid(world)


def test_a_manifest_naming_a_different_number_of_images(world):
    """The kind of edit that looks harmless and is not."""
    manifest = dataclasses.replace(world.manifest, created_utc=world.manifest.created_utc)
    payload = json.loads(
        world.store.manifest_path(world.preparation_set_id).read_text("utf-8")
    )
    payload["total_images"] = manifest.total_images + 1
    write_json(world.store.manifest_path(world.preparation_set_id), payload)
    _assert_invalid(world)
