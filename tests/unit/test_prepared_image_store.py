"""Storage rules for canonical artefacts: atomic, content-addressed, immutable.

The runtime bundle store's rules, applied to 3,000 files instead of one, plus
two the bundle store never needed: an artefact must be the *only* name for its
bytes, and identical bytes arriving twice must be a verified no-op rather than a
rewrite.

Nothing here is ever repaired. A file that no longer hashes to its own name is
reported, never replaced — silently restoring it would destroy the evidence that
something changed the input every algorithm is being compared over.
"""

from __future__ import annotations

import os
import stat

import pytest

from fpbench.core.errors import PreparedImageSetConflictError, StorageError
from fpbench.core.imaging_models import (
    ordered_prepared_entries_hash,
    preparation_set_fingerprint,
)
from fpbench.storage.prepared_image_schemas import (
    PREPARED_IMAGE_ENTRY_SCHEMA,
    prepared_entries_to_table,
    table_to_prepared_entries,
)
from fpbench.storage.prepared_image_set_store import PreparedImageSetStore
from canonicalworld import build_canonical_world, publish_receipt_and_marker

pytestmark = [pytest.mark.imaging, pytest.mark.canonical500]


def _writable(path):
    """Windows refuses to modify a read-only file; the store makes them read-only."""
    path.chmod(path.stat().st_mode | stat.S_IWUSR)
    return path


# ------------------------------------------------------------ writing images


def test_an_image_is_written_atomically_and_verified_from_its_final_path(tmp_path):
    store = PreparedImageSetStore(tmp_path)
    payload = b"\x89PNG\r\n\x1a\n" + b"pretend png bytes"
    import hashlib

    digest = hashlib.sha256(payload).hexdigest()

    outcome = store.ensure_image(encoded_bytes=payload, encoded_sha256=digest)
    assert outcome.reused is False
    assert outcome.absolute_path.read_bytes() == payload
    assert outcome.relative_path.endswith(f"{digest}.png")
    assert f"/{digest[:2]}/" in outcome.relative_path
    # No temporary file survived.
    assert not list(outcome.absolute_path.parent.glob("*.tmp"))


def test_the_same_bytes_a_second_time_are_a_verified_no_op(tmp_path):
    store = PreparedImageSetStore(tmp_path)
    payload = b"identical bytes"
    import hashlib

    digest = hashlib.sha256(payload).hexdigest()

    first = store.ensure_image(encoded_bytes=payload, encoded_sha256=digest)
    before = first.absolute_path.stat().st_mtime_ns
    second = store.ensure_image(encoded_bytes=payload, encoded_sha256=digest)

    assert second.reused is True
    assert second.absolute_path == first.absolute_path
    assert first.absolute_path.stat().st_mtime_ns == before


def test_bytes_offered_under_someone_elses_digest_are_refused(tmp_path):
    store = PreparedImageSetStore(tmp_path)
    with pytest.raises(StorageError, match="bytes hash to"):
        store.ensure_image(encoded_bytes=b"one thing", encoded_sha256="a" * 64)


def test_different_bytes_found_under_an_existing_digest_are_a_conflict(tmp_path):
    store = PreparedImageSetStore(tmp_path)
    payload = b"the original"
    import hashlib

    digest = hashlib.sha256(payload).hexdigest()
    outcome = store.ensure_image(encoded_bytes=payload, encoded_sha256=digest)

    _writable(outcome.absolute_path).write_bytes(b"something else entirely")
    with pytest.raises(PreparedImageSetConflictError, match="was replaced"):
        store.ensure_image(encoded_bytes=payload, encoded_sha256=digest)


def test_a_symlink_where_an_artefact_should_be_is_refused(tmp_path):
    store = PreparedImageSetStore(tmp_path)
    payload = b"real bytes"
    import hashlib

    digest = hashlib.sha256(payload).hexdigest()
    target = store.image_path(digest)
    target.parent.mkdir(parents=True, exist_ok=True)

    elsewhere = tmp_path / "elsewhere.png"
    elsewhere.write_bytes(payload)
    try:
        target.symlink_to(elsewhere)
    except (OSError, NotImplementedError):  # pragma: no cover - needs privilege
        pytest.skip("this platform does not allow creating symlinks here")

    with pytest.raises(PreparedImageSetConflictError, match="symlink"):
        store.ensure_image(encoded_bytes=payload, encoded_sha256=digest)


def test_a_hardlinked_artefact_is_refused(tmp_path):
    """A hardlink shares an inode, so a writer elsewhere can rewrite it.

    That is exactly the failure the runtime bundle store learned the hard way:
    an "immutable" asset that shares storage with build output is not immutable
    (docs/adr/0018, spec section 40).
    """
    store = PreparedImageSetStore(tmp_path)
    payload = b"linked bytes"
    import hashlib

    digest = hashlib.sha256(payload).hexdigest()
    outcome = store.ensure_image(encoded_bytes=payload, encoded_sha256=digest)

    second_name = tmp_path / "another-name.png"
    try:
        os.link(outcome.absolute_path, second_name)
    except (OSError, NotImplementedError, AttributeError):  # pragma: no cover
        pytest.skip("this platform does not support hard links here")

    with pytest.raises(PreparedImageSetConflictError, match="hard link"):
        store.ensure_image(encoded_bytes=payload, encoded_sha256=digest)


def test_a_stray_temporary_file_is_ignored(tmp_path):
    store = PreparedImageSetStore(tmp_path)
    payload = b"good bytes"
    import hashlib

    digest = hashlib.sha256(payload).hexdigest()
    target = store.image_path(digest)
    target.parent.mkdir(parents=True, exist_ok=True)
    (target.parent / f"{target.name}.99999.tmp").write_bytes(b"half a file")

    outcome = store.ensure_image(encoded_bytes=payload, encoded_sha256=digest)
    assert outcome.absolute_path.read_bytes() == payload


# ---------------------------------------------------------------- manifests


def test_a_finished_set_verifies(tmp_path):
    world = build_canonical_world(tmp_path)
    manifest = world.store.verify_set(world.preparation_set_id)
    assert manifest.total_images == len(world.entries)


def test_the_set_id_matches_the_directory_it_is_stored_in(tmp_path):
    world = build_canonical_world(tmp_path)
    directory = world.store.set_dir(world.preparation_set_id)
    assert directory.name == world.manifest.preparation_set_id
    assert (
        world.store.read_manifest(world.preparation_set_id).preparation_set_id
        == directory.name
    )


def test_the_same_set_again_is_a_no_op(tmp_path):
    world = build_canonical_world(tmp_path)
    world.store.ensure_manifest(
        manifest=world.manifest,
        entries=world.entries,
        profile=world.profile,
        runtime=world.runtime,
        definition=world.definition,
    )
    assert world.store.verify_set(world.preparation_set_id)


def test_a_different_set_under_the_same_id_is_a_conflict(tmp_path):
    import dataclasses

    world = build_canonical_world(tmp_path)
    forged = dataclasses.replace(
        world.manifest,
        preparation_set_fingerprint=world.manifest.preparation_set_fingerprint,
        created_utc="2099-01-01T00:00:00+00:00",
    )
    # Same identity, genuinely different content: drop an entry.
    with pytest.raises(StorageError):
        world.store.ensure_manifest(
            manifest=forged,
            entries=world.entries[:-1],
            profile=world.profile,
            runtime=world.runtime,
            definition=world.definition,
        )


def test_a_manifest_read_from_a_foreign_directory_is_refused(tmp_path):
    world = build_canonical_world(tmp_path)
    other = world.store.set_dir("prepset_000000000000")
    other.mkdir(parents=True, exist_ok=True)
    import shutil

    shutil.copy(
        world.store.manifest_path(world.preparation_set_id), other / "manifest.json"
    )
    with pytest.raises(StorageError, match="was read from"):
        world.store.read_manifest("prepset_000000000000")


def test_entries_out_of_order_are_refused(tmp_path):
    import dataclasses

    world = build_canonical_world(tmp_path)
    shuffled = (world.entries[1], world.entries[0], *world.entries[2:])
    with pytest.raises(StorageError, match="ordinals"):
        world.store.ensure_manifest(
            manifest=dataclasses.replace(world.manifest),
            entries=shuffled,
            profile=world.profile,
            runtime=world.runtime,
            definition=world.definition,
        )


# ------------------------------------------------------------------ parquet


def test_the_parquet_schema_is_explicit_and_round_trips_exactly(tmp_path):
    world = build_canonical_world(tmp_path)
    table = prepared_entries_to_table(world.entries)
    assert table.schema == PREPARED_IMAGE_ENTRY_SCHEMA

    rebuilt = table_to_prepared_entries(table)
    assert [entry.entry_hash for entry in rebuilt] == [
        entry.entry_hash for entry in world.entries
    ]
    for original, restored in zip(world.entries, rebuilt):
        assert type(restored.output_width) is int
        assert restored.output_width == original.output_width
        assert restored.source_declared_ppi == original.source_declared_ppi


def test_a_retyped_column_is_refused(tmp_path):
    import pyarrow as pa

    world = build_canonical_world(tmp_path)
    table = prepared_entries_to_table(world.entries)
    retyped = table.set_column(
        table.schema.get_field_index("output_width"),
        pa.field("output_width", pa.int32(), nullable=False),
        table.column("output_width").cast(pa.int32()),
    )
    with pytest.raises(ValueError, match="prepared-image entry schema"):
        table_to_prepared_entries(retyped)


def test_reading_the_entries_back_from_the_set_preserves_order(tmp_path):
    world = build_canonical_world(tmp_path)
    stored = world.store.read_entries(world.preparation_set_id)
    assert [entry.ordinal for entry in stored] == list(range(len(world.entries)))
    assert ordered_prepared_entries_hash(stored) == world.manifest.ordered_entries_hash


def test_the_set_fingerprint_is_reproducible_from_what_is_stored(tmp_path):
    world = build_canonical_world(tmp_path)
    entries = world.store.read_entries(world.preparation_set_id)
    manifest = world.store.read_manifest(world.preparation_set_id)
    assert (
        preparation_set_fingerprint(
            dataset_id=manifest.dataset_id,
            image_manifest_hash=manifest.image_manifest_hash,
            protocol_id=manifest.protocol_id,
            cohort_id=manifest.cohort_id,
            cohort_fingerprint=manifest.cohort_fingerprint,
            pair_manifest_hash=manifest.pair_manifest_hash,
            transform_profile_fingerprint=manifest.transform_profile_fingerprint,
            transform_runtime_fingerprint=manifest.transform_runtime_fingerprint,
            entries=entries,
        )
        == manifest.preparation_set_fingerprint
    )


def test_a_corrupt_artefact_is_reported_and_never_repaired(tmp_path):
    world = build_canonical_world(tmp_path)
    entry = world.entries[0]
    path = world.artifact_path(entry)
    original = path.read_bytes()
    _writable(path).write_bytes(original[:-4] + b"XXXX")

    with pytest.raises(PreparedImageSetConflictError):
        world.store.verify_entry(entry, profile=world.profile)
    # Nothing put it back.
    assert path.read_bytes() != original


def test_a_receipt_and_marker_complete_the_chain(tmp_path):
    world = build_canonical_world(tmp_path)
    publish_receipt_and_marker(world)
    assert world.store.has_receipt(world.preparation_set_id)
    assert world.store.has_finalization(world.preparation_set_id)

    marker = world.store.read_finalization(world.preparation_set_id)
    assert marker.preparation_set_fingerprint == world.preparation_set_fingerprint
    assert marker.entries_table_content_hash == world.store.entries_table_content_hash(
        world.preparation_set_id
    )
