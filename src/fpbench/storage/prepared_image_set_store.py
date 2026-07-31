"""Immutable, content-addressed storage for canonical image sets.

The rules are the runtime bundle's rules applied to 3,000 files instead of one,
plus two the bundle store never needed.

**Write the bytes, then verify the bytes, then rename.** A canonical PNG is
written to a temporary sibling, flushed, ``fsync``-ed, re-read from that
temporary path and only then renamed into place. A copy that was truncated
mid-write never becomes an artefact, and a rename is the one filesystem
operation that is atomic on every platform this runs on.

**The filename is the digest.** Not the image id, not the subject id: a
directory listing of a redistribution-restricted dataset is an inventory of it,
and inventories are what this project keeps out of anything shareable. It also
means two entries that genuinely produced the same bytes share one file, and
that identical bytes arriving twice is a verified no-op rather than a rewrite.

**Nothing is repaired.** A file that no longer hashes to its own name is
reported, never replaced. Silently restoring it would destroy the evidence that
something changed it — which, for an input set every algorithm is compared over,
is the only thing anyone would want to know.

Layout is in :mod:`fpbench.storage.layout`, including why the PNGs sit at the
workspace level rather than inside the set directory.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import os
import stat
from pathlib import Path
from typing import Mapping

import pyarrow as pa
import pyarrow.parquet as pq

from fpbench.core.errors import PreparedImageSetConflictError, StorageError
from fpbench.core.imaging_models import (
    PREPARATION_SET_SCHEMA_VERSION,
    ImageTransformProfile,
    PreparationDefinition,
    PreparationFinalizationMarker,
    PreparationReceipt,
    PreparationTransformAudit,
    PreparedImageEntry,
    PreparedImageSetManifest,
    TransformRuntimeManifest,
    ordered_prepared_entries_hash,
    preparation_receipt_fingerprint,
)
from fpbench.core.identifiers import ImageId
from fpbench.core.serialization import read_json, stable_hash, to_plain, write_json
from fpbench.storage import layout, prepared_image_schemas

__all__ = ["PreparedImageSetStore", "ImageWriteOutcome"]

_PROFILE = "transform-profile.json"
_RUNTIME = "transform-runtime.json"
_DEFINITION = "preparation-definition.json"
_MANIFEST = "manifest.json"
_ENTRIES = "entries.parquet"
_SUMMARY = "preparation-summary.json"
_RECEIPT = "preparation-receipt.json"
_TRANSFORM_AUDIT = "preparation-transform-audit.json"
_FINALIZATION = "preparation-finalization.json"
_ENTRIES_DIRECTORY = "entries"

_READ_CHUNK = 1 << 20


class ImageWriteOutcome:
    """Whether a canonical PNG was written now or was already there, verified."""

    __slots__ = ("relative_path", "absolute_path", "reused")

    def __init__(self, *, relative_path: str, absolute_path: Path, reused: bool) -> None:
        self.relative_path = relative_path
        self.absolute_path = absolute_path
        self.reused = reused


class PreparedImageSetStore:
    """Where canonical images and their manifests live, and what may replace them."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    # ------------------------------------------------------------------ paths

    @property
    def prepared_images_root(self) -> Path:
        return layout.prepared_images_root(self.root)

    def pending_dir(self, definition_id: str) -> Path:
        return layout.prepared_image_pending_directory(self.root, definition_id)

    def set_dir(self, preparation_set_id: str) -> Path:
        return layout.prepared_image_set_directory(self.root, preparation_set_id)

    def image_path(self, encoded_sha256: str) -> Path:
        return layout.prepared_image_blob_path(self.root, encoded_sha256)

    def image_relative_path(self, encoded_sha256: str) -> str:
        return (
            self.image_path(encoded_sha256)
            .relative_to(self.root)
            .as_posix()
        )

    def entry_path(self, definition_id: str, image_id: str) -> Path:
        return self.pending_dir(definition_id) / _ENTRIES_DIRECTORY / f"{image_id}.json"

    def profile_path(self, container: Path) -> Path:
        return container / _PROFILE

    def runtime_path(self, container: Path) -> Path:
        return container / _RUNTIME

    def definition_path(self, container: Path) -> Path:
        return container / _DEFINITION

    def manifest_path(self, preparation_set_id: str) -> Path:
        return self.set_dir(preparation_set_id) / _MANIFEST

    def entries_table_path(self, preparation_set_id: str) -> Path:
        return self.set_dir(preparation_set_id) / _ENTRIES

    def summary_path(self, preparation_set_id: str) -> Path:
        return self.set_dir(preparation_set_id) / _SUMMARY

    def receipt_path(self, preparation_set_id: str) -> Path:
        return self.set_dir(preparation_set_id) / _RECEIPT

    def transform_audit_path(self, preparation_set_id: str) -> Path:
        return self.set_dir(preparation_set_id) / _TRANSFORM_AUDIT

    def finalization_path(self, preparation_set_id: str) -> Path:
        return self.set_dir(preparation_set_id) / _FINALIZATION

    # ---------------------------------------------------------------- presence

    def has_definition(self, definition_id: str) -> bool:
        return self.definition_path(self.pending_dir(definition_id)).is_file()

    def has_manifest(self, preparation_set_id: str) -> bool:
        return self.manifest_path(preparation_set_id).is_file()

    def has_receipt(self, preparation_set_id: str) -> bool:
        return self.receipt_path(preparation_set_id).is_file()

    def has_transform_audit(self, preparation_set_id: str) -> bool:
        return self.transform_audit_path(preparation_set_id).is_file()

    def has_summary(self, preparation_set_id: str) -> bool:
        return self.summary_path(preparation_set_id).is_file()

    def has_finalization(self, preparation_set_id: str) -> bool:
        return self.finalization_path(preparation_set_id).is_file()

    def has_entry(self, definition_id: str, image_id: str) -> bool:
        return self.entry_path(definition_id, str(image_id)).is_file()

    def preparation_set_ids(self) -> tuple[str, ...]:
        directory = self.prepared_images_root
        if not directory.is_dir():
            return ()
        return tuple(
            sorted(
                path.name
                for path in directory.iterdir()
                if path.is_dir()
                and path.name.startswith("prepset_")
                and (path / _MANIFEST).is_file()
            )
        )

    # ------------------------------------------------------- profile / runtime

    def ensure_transform_profile(
        self, container: Path, profile: ImageTransformProfile
    ) -> Path:
        """Store the profile beside the images it produced, or confirm it matches.

        Stored, not merely referenced. ``configs/imaging/`` lives in a repository
        that will keep changing, and a set pointing at "the profile in configs"
        would silently mean something different after the next edit. This copy is
        what the pixels were actually produced under.
        """
        path = self.profile_path(Path(container))
        if path.is_file():
            stored = self.read_transform_profile(container)
            if stored.profile_fingerprint != profile.profile_fingerprint:
                raise PreparedImageSetConflictError(
                    f"{path} already holds transform profile "
                    f"{stored.profile_id} ({stored.profile_fingerprint[:12]}...); "
                    f"refusing to replace it with {profile.profile_fingerprint[:12]}..."
                )
            return path
        return write_json(path, profile)

    def ensure_runtime(
        self, container: Path, runtime: TransformRuntimeManifest
    ) -> Path:
        path = self.runtime_path(Path(container))
        if path.is_file():
            stored = self.read_runtime(container)
            if stored.runtime_fingerprint != runtime.runtime_fingerprint:
                raise PreparedImageSetConflictError(
                    f"{path} already holds transform runtime "
                    f"{stored.runtime_id}; refusing to replace it with "
                    f"{runtime.runtime_id}"
                )
            return path
        return write_json(path, runtime)

    def ensure_definition(self, definition: PreparationDefinition) -> Path:
        path = self.definition_path(self.pending_dir(definition.definition_id))
        if path.is_file():
            stored = self.read_definition(self.pending_dir(definition.definition_id))
            if stored.definition_fingerprint != definition.definition_fingerprint:
                raise PreparedImageSetConflictError(
                    f"{path} already defines a different preparation"
                )
            return path
        return write_json(path, definition)

    # -------------------------------------------------------------- image bytes

    def ensure_image(
        self, *, encoded_bytes: bytes, encoded_sha256: str
    ) -> ImageWriteOutcome:
        """Write one canonical PNG, atomically and exactly once.

        The digest is recomputed over the caller's bytes before anything is
        written, so a caller cannot file bytes under someone else's name. If the
        target already exists it is re-hashed: identical bytes are a verified
        no-op, different bytes under the same digest mean the stored file was
        replaced and are a conflict, never a repair.

        Raises:
            PreparedImageSetConflictError: the stored file is not what its own
                name says it is.
            StorageError: the copy did not survive its own verification.
        """
        payload = bytes(encoded_bytes)
        actual = hashlib.sha256(payload).hexdigest()
        expected = str(encoded_sha256).strip().lower()
        if actual != expected:
            raise StorageError(
                f"a canonical image was offered under {expected[:12]}... but its "
                f"bytes hash to {actual[:12]}..."
            )

        target = self.image_path(actual)
        relative = self.image_relative_path(actual)

        if target.exists() or target.is_symlink():
            self._require_stored_blob_intact(target, actual)
            return ImageWriteOutcome(
                relative_path=relative, absolute_path=target, reused=True
            )

        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f"{target.name}.{os.getpid()}.tmp")
        try:
            with tmp.open("wb") as writer:
                writer.write(payload)
                writer.flush()
                os.fsync(writer.fileno())
            # Re-read the temporary file rather than trusting the write. A
            # filesystem that acknowledged bytes it did not keep is exactly the
            # failure this whole store exists to make visible.
            written = tmp.read_bytes()
            if hashlib.sha256(written).hexdigest() != actual:
                raise StorageError(
                    f"the canonical image written for {actual[:12]}... did not "
                    "survive its own write"
                )
            try:
                tmp.replace(target)
            except FileExistsError:  # pragma: no cover - POSIX replaces silently
                self._require_stored_blob_intact(target, actual)
                return ImageWriteOutcome(
                    relative_path=relative, absolute_path=target, reused=True
                )
        finally:
            tmp.unlink(missing_ok=True)

        _fsync_directory(target.parent)
        _make_read_only(target)

        # And once more from the final path, because that is the path everything
        # downstream will actually open.
        self._require_stored_blob_intact(target, actual)
        return ImageWriteOutcome(
            relative_path=relative, absolute_path=target, reused=False
        )

    def read_image_bytes(self, encoded_sha256: str) -> bytes:
        path = self.image_path(encoded_sha256)
        if not path.is_file():
            raise StorageError(f"canonical image not found: {path.name}")
        return path.read_bytes()

    # ------------------------------------------------------------------ entries

    def ensure_entry(self, definition_id: str, entry: PreparedImageEntry) -> Path:
        """Record one finished image, or confirm the recorded one is already it."""
        path = self.entry_path(definition_id, str(entry.image_id))
        if path.is_file():
            stored = self.read_entry_by_image_id(definition_id, entry.image_id)
            if stored.entry_hash != entry.entry_hash:
                raise PreparedImageSetConflictError(
                    f"{path} already records a different canonical artefact for "
                    f"{entry.image_id}: {stored.entry_hash[:12]}... versus "
                    f"{entry.entry_hash[:12]}..."
                )
            if stored.ordinal != entry.ordinal:
                raise PreparedImageSetConflictError(
                    f"{path} records {entry.image_id} at ordinal {stored.ordinal}, "
                    f"not {entry.ordinal}"
                )
            return path
        return write_json(path, entry)

    def read_entry_by_image_id(
        self, definition_id: str, image_id: str
    ) -> PreparedImageEntry:
        path = self.entry_path(definition_id, str(image_id))
        payload = self._read_json(path, "prepared-image entry")
        try:
            return PreparedImageEntry(**payload)
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError(f"{path}: unreadable prepared-image entry ({exc})") from exc

    def pending_entry_image_ids(self, definition_id: str) -> tuple[str, ...]:
        directory = self.pending_dir(definition_id) / _ENTRIES_DIRECTORY
        if not directory.is_dir():
            return ()
        return tuple(
            sorted(path.stem for path in directory.iterdir() if path.suffix == ".json")
        )

    # ----------------------------------------------------------------- manifest

    def ensure_manifest(
        self,
        *,
        manifest: PreparedImageSetManifest,
        entries: tuple[PreparedImageEntry, ...],
        profile: ImageTransformProfile,
        runtime: TransformRuntimeManifest,
        definition: PreparationDefinition,
    ) -> Path:
        """Publish the finished set, or confirm the published one is already it.

        The manifest is written **last** of the five files, because it is the
        marker that says the set is readable. A crash between the entries table
        and the manifest leaves a visibly unfinished directory rather than an
        identity pointing at rows that were never written.
        """
        entries = tuple(entries)
        self._require_coherent(
            manifest=manifest,
            entries=entries,
            profile=profile,
            runtime=runtime,
            definition=definition,
        )

        set_id = manifest.preparation_set_id
        manifest_path = self.manifest_path(set_id)
        if manifest_path.is_file():
            stored = self.read_manifest(set_id)
            if stored.preparation_set_fingerprint != manifest.preparation_set_fingerprint:
                raise PreparedImageSetConflictError(
                    f"{manifest_path} already holds prepared-image set "
                    f"{stored.preparation_set_id}; refusing to replace it"
                )
            return manifest_path.parent

        container = self.set_dir(set_id)
        container.mkdir(parents=True, exist_ok=True)
        self.ensure_transform_profile(container, profile)
        self.ensure_runtime(container, runtime)
        self.ensure_definition_copy(container, definition)
        self.ensure_entries_table(manifest, entries)
        write_json(manifest_path, manifest)
        return manifest_path.parent

    def ensure_definition_copy(
        self, container: Path, definition: PreparationDefinition
    ) -> Path:
        path = self.definition_path(Path(container))
        if path.is_file():
            stored = self.read_definition(container)
            if stored.definition_fingerprint != definition.definition_fingerprint:
                raise PreparedImageSetConflictError(
                    f"{path} already holds a different preparation definition"
                )
            return path
        return write_json(path, definition)

    def ensure_entries_table(
        self,
        manifest: PreparedImageSetManifest,
        entries: tuple[PreparedImageEntry, ...],
    ) -> Path:
        table = prepared_image_schemas.prepared_entries_to_table(entries)
        path = self.entries_table_path(manifest.preparation_set_id)
        path.parent.mkdir(parents=True, exist_ok=True)

        from fpbench import __version__

        stamped = table.replace_schema_metadata(
            {
                **(table.schema.metadata or {}),
                b"row_kind": b"prepared_image_entries",
                b"schema_version": PREPARATION_SET_SCHEMA_VERSION.encode(),
                b"preparation_set_id": manifest.preparation_set_id.encode(),
                b"preparation_set_fingerprint": (
                    manifest.preparation_set_fingerprint.encode()
                ),
                b"ordered_entries_hash": manifest.ordered_entries_hash.encode(),
                b"transform_profile_id": manifest.transform_profile_id.encode(),
                b"transform_profile_fingerprint": (
                    manifest.transform_profile_fingerprint.encode()
                ),
                b"transform_runtime_fingerprint": (
                    manifest.transform_runtime_fingerprint.encode()
                ),
                b"pair_manifest_hash": manifest.pair_manifest_hash.encode(),
                b"row_count": str(len(entries)).encode(),
                b"fpbench_version": __version__.encode(),
                b"created_utc": _dt.datetime.now(_dt.timezone.utc)
                .isoformat(timespec="seconds")
                .encode(),
            }
        )
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            pq.write_table(stamped, tmp, compression="zstd")
            tmp.replace(path)
        finally:
            tmp.unlink(missing_ok=True)
        return path

    def ensure_summary(
        self, *, preparation_set_id: str, summary: Mapping[str, object]
    ) -> Path:
        """Write the operational counts once, or confirm they match.

        Compared on a content hash that excludes ``generated_utc``: the same
        verified set summarised twice is the same summary.
        """
        path = self.summary_path(preparation_set_id)
        if path.is_file():
            stored = self.read_summary(preparation_set_id)
            if preparation_summary_content_hash(
                stored
            ) != preparation_summary_content_hash(summary):
                raise PreparedImageSetConflictError(
                    f"{path} already carries a different preparation summary"
                )
            return path
        return write_json(path, dict(summary))

    def ensure_receipt(
        self, *, preparation_set_id: str, receipt: PreparationReceipt
    ) -> Path:
        path = self.receipt_path(preparation_set_id)
        if path.is_file():
            try:
                stored = self.read_receipt(preparation_set_id)
            except StorageError:
                payload = read_json(path)
                if _is_preparation_receipt_schema_upgrade(payload, receipt):
                    _archive_preparation_publication(path)
                    return write_json(path, receipt)
                raise
            if preparation_receipt_fingerprint(
                stored
            ) != preparation_receipt_fingerprint(receipt):
                raise PreparedImageSetConflictError(
                    f"{path} already carries a different preparation receipt"
                )
            return path
        return write_json(path, receipt)

    def ensure_transform_audit(
        self, *, preparation_set_id: str, audit: PreparationTransformAudit
    ) -> Path:
        """Write the full transform audit once, or confirm it is equivalent."""
        path = self.transform_audit_path(preparation_set_id)
        if path.is_file():
            stored = self.read_transform_audit(preparation_set_id)
            if stored.audit_fingerprint != audit.audit_fingerprint:
                raise PreparedImageSetConflictError(
                    f"{path} already carries a different transform audit"
                )
            return path
        return write_json(path, audit)

    def ensure_finalization(
        self, *, preparation_set_id: str, marker: PreparationFinalizationMarker
    ) -> Path:
        """Write the last file, the one that makes the rest authoritative."""
        path = self.finalization_path(preparation_set_id)
        if path.is_file():
            try:
                stored = self.read_finalization(preparation_set_id)
            except StorageError:
                payload = read_json(path)
                if _is_preparation_finalization_schema_upgrade(payload, marker):
                    _archive_preparation_publication(path)
                    return write_json(path, marker)
                raise
            if stored.finalization_fingerprint != marker.finalization_fingerprint:
                raise PreparedImageSetConflictError(
                    f"{path} already finalises a different preparation"
                )
            return path
        return write_json(path, marker)

    # --------------------------------------------------------------------- read

    def read_transform_profile(self, container: Path) -> ImageTransformProfile:
        path = self.profile_path(Path(container))
        payload = self._read_json(path, "transform profile")
        try:
            return ImageTransformProfile(**payload)
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError(f"{path}: unreadable transform profile ({exc})") from exc

    def read_runtime(self, container: Path) -> TransformRuntimeManifest:
        path = self.runtime_path(Path(container))
        payload = self._read_json(path, "transform runtime")
        try:
            return TransformRuntimeManifest(**payload)
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError(f"{path}: unreadable transform runtime ({exc})") from exc

    def read_definition(self, container: Path) -> PreparationDefinition:
        path = self.definition_path(Path(container))
        payload = self._read_json(path, "preparation definition")
        try:
            return PreparationDefinition(
                **{
                    **payload,
                    "ordered_image_ids": tuple(
                        ImageId(item) for item in payload["ordered_image_ids"]
                    ),
                }
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError(
                f"{path}: unreadable preparation definition ({exc})"
            ) from exc

    def read_manifest(self, preparation_set_id: str) -> PreparedImageSetManifest:
        path = self.manifest_path(preparation_set_id)
        payload = self._read_json(path, "prepared-image set manifest")
        try:
            manifest = PreparedImageSetManifest(**payload)
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError(
                f"{path}: unreadable prepared-image set manifest ({exc})"
            ) from exc
        if manifest.preparation_set_id != preparation_set_id:
            raise StorageError(
                f"{path}: the manifest names set {manifest.preparation_set_id} but "
                f"was read from {preparation_set_id}"
            )
        return manifest

    def read_entries(self, preparation_set_id: str) -> tuple[PreparedImageEntry, ...]:
        path = self.entries_table_path(preparation_set_id)
        if not path.is_file():
            raise StorageError(f"prepared-image entries not found: {path}")
        try:
            with pq.ParquetFile(path) as reader:
                table = reader.read()
        except (pa.ArrowInvalid, OSError) as exc:
            raise StorageError(f"{path}: unreadable parquet ({exc})") from exc
        try:
            return tuple(prepared_image_schemas.table_to_prepared_entries(table))
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError(
                f"{path}: unreadable prepared-image entries ({exc})"
            ) from exc

    def read_summary(self, preparation_set_id: str) -> Mapping[str, object]:
        path = self.summary_path(preparation_set_id)
        return self._read_json(path, "preparation summary")

    def read_receipt(self, preparation_set_id: str) -> PreparationReceipt:
        path = self.receipt_path(preparation_set_id)
        payload = self._read_json(path, "preparation receipt")
        try:
            return PreparationReceipt(**payload)
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError(f"{path}: unreadable preparation receipt ({exc})") from exc

    def read_transform_audit(
        self, preparation_set_id: str
    ) -> PreparationTransformAudit:
        path = self.transform_audit_path(preparation_set_id)
        payload = self._read_json(path, "preparation transform audit")
        try:
            return PreparationTransformAudit(
                **{**payload, "issues": tuple(payload.get("issues") or ())}
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError(
                f"{path}: unreadable preparation transform audit ({exc})"
            ) from exc

    def read_finalization(
        self, preparation_set_id: str
    ) -> PreparationFinalizationMarker:
        path = self.finalization_path(preparation_set_id)
        payload = self._read_json(path, "preparation finalization marker")
        try:
            return PreparationFinalizationMarker(**payload)
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError(
                f"{path}: unreadable preparation finalization marker ({exc})"
            ) from exc

    def entries_table_content_hash(self, preparation_set_id: str) -> str:
        """A digest of the rows, not of the parquet file.

        Parquet embeds a write timestamp and a library version, so two byte
        different files can hold identical rows. The marker binds what the rows
        say.
        """
        entries = self.read_entries(preparation_set_id)
        return stable_hash(
            {
                "schema": "prepared_entries_table_content_hash_v1",
                "entries": [to_plain(entry) for entry in entries],
            },
            length=64,
        )

    # ------------------------------------------------------------------- verify

    def verify_entry(
        self, entry: PreparedImageEntry, *, profile: ImageTransformProfile
    ) -> Path:
        """Confirm one entry's canonical artefact is on disk and still itself.

        Storage-level only: the file exists, is a regular file, is not a
        symlink, is the size the entry records, hashes to the name it is filed
        under and to the digest the entry records, and decodes to the raster the
        entry records. Whether the *source* still hashes to what the entry says
        needs the dataset, and lives in :mod:`fpbench.imaging.verify`.
        """
        from fpbench.core.errors import ImagingError
        from fpbench.imaging.canonical import verify_canonical_png

        path = self.root / entry.relative_path
        expected_path = self.image_path(entry.output_encoded_sha256)
        if path.resolve() != expected_path.resolve():
            raise PreparedImageSetConflictError(
                f"{entry.image_id}: the entry points at {entry.relative_path}, but a "
                "canonical artefact is addressed by the digest of its own bytes"
            )
        self._require_stored_blob_intact(path, entry.output_encoded_sha256)
        try:
            verify_canonical_png(
                path,
                profile=profile,
                expected_width=entry.output_width,
                expected_height=entry.output_height,
                expected_pixel_sha256=entry.output_pixel_sha256,
                expected_encoded_sha256=entry.output_encoded_sha256,
                expected_size_bytes=entry.output_size_bytes,
                image_label=str(entry.image_id),
            )
        except ImagingError as exc:
            raise PreparedImageSetConflictError(str(exc)) from exc
        return path

    def verify_set(self, preparation_set_id: str) -> PreparedImageSetManifest:
        """Re-read the whole set and re-check what storage is able to check.

        Ordering, ordinals, the ordered-entries hash, the manifest's own
        fingerprint, agreement between manifest, profile, runtime and definition,
        and every artefact's bytes. It does **not** re-read the source images or
        re-derive the pixels — that needs the dataset, and it lives in
        :func:`fpbench.imaging.verify.verify_prepared_image_set`. A prepared-image
        set is not evidence of itself, and neither is this method.
        """
        manifest = self.read_manifest(preparation_set_id)
        entries = self.read_entries(preparation_set_id)
        container = self.set_dir(preparation_set_id)
        profile = self.read_transform_profile(container)
        runtime = self.read_runtime(container)
        definition = self.read_definition(container)
        self._require_coherent(
            manifest=manifest,
            entries=entries,
            profile=profile,
            runtime=runtime,
            definition=definition,
        )
        for entry in entries:
            self.verify_entry(entry, profile=profile)
        return manifest

    # ---------------------------------------------------------------- internals

    def _read_json(self, path: Path, what: str):
        if not path.is_file():
            raise StorageError(f"{what} not found: {path}")
        try:
            return read_json(path)
        except (OSError, ValueError) as exc:
            raise StorageError(f"{path}: unreadable {what} ({exc})") from exc

    def _require_stored_blob_intact(self, path: Path, expected_sha256: str) -> None:
        if path.is_symlink():
            raise PreparedImageSetConflictError(
                f"{path.name} is a symlink; a prepared set owns its bytes rather "
                "than pointing at someone else's"
            )
        if not path.is_file():
            raise PreparedImageSetConflictError(
                f"{path.name} is not a regular file"
            )
        # A hardlink shares an inode with whatever else points at it, so a writer
        # somewhere else could rewrite an artefact that looks immutable here. On
        # filesystems that cannot report a link count this check is skipped
        # rather than guessed at.
        try:
            links = path.stat().st_nlink
        except OSError:  # pragma: no cover - platform dependent
            links = 1
        if links > 1:
            raise PreparedImageSetConflictError(
                f"{path.name} has {links} hard links; a canonical artefact must be "
                "the only name for its bytes, or something else can rewrite it"
            )
        digest, size = _digest_file(path)
        if digest != expected_sha256:
            raise PreparedImageSetConflictError(
                f"{path.name} hashes to {digest[:12]}..., expected "
                f"{str(expected_sha256)[:12]}...; the stored artefact was replaced"
            )
        if size <= 0:  # pragma: no cover - a zero-byte PNG cannot hash to a digest
            raise PreparedImageSetConflictError(f"{path.name} is empty")

    def _require_coherent(
        self,
        *,
        manifest: PreparedImageSetManifest,
        entries: tuple[PreparedImageEntry, ...],
        profile: ImageTransformProfile,
        runtime: TransformRuntimeManifest,
        definition: PreparationDefinition,
    ) -> None:
        """Structural agreement. Re-derivation lives in ``imaging.verify``."""
        if not entries:
            raise StorageError("a prepared-image set with no entries is not one")
        if len(entries) != manifest.total_images:
            raise StorageError(
                f"the set declares {manifest.total_images} images but carries "
                f"{len(entries)}"
            )
        if [entry.ordinal for entry in entries] != list(range(len(entries))):
            raise StorageError(
                "entry ordinals must be 0..n-1 with no gaps and no repeats"
            )
        image_ids = [str(entry.image_id) for entry in entries]
        if len(set(image_ids)) != len(image_ids):
            raise StorageError(
                "two entries cover the same image; a canonical set holds one "
                "artefact per source image"
            )
        if image_ids != sorted(image_ids):
            raise StorageError(
                "entries are not in ascending image-id order; materialisation "
                "order is part of the set's identity and must not depend on how a "
                "filesystem enumerated a directory"
            )
        if ordered_prepared_entries_hash(entries) != manifest.ordered_entries_hash:
            raise StorageError(
                "the manifest's ordered-entries hash does not cover these rows"
            )

        for label, actual, expected in (
            ("transform profile id", profile.profile_id, manifest.transform_profile_id),
            (
                "transform profile fingerprint",
                profile.profile_fingerprint,
                manifest.transform_profile_fingerprint,
            ),
            ("transform runtime id", runtime.runtime_id, manifest.transform_runtime_id),
            (
                "transform runtime fingerprint",
                runtime.runtime_fingerprint,
                manifest.transform_runtime_fingerprint,
            ),
            ("dataset id", definition.dataset_id, manifest.dataset_id),
            (
                "image manifest hash",
                definition.image_manifest_hash,
                manifest.image_manifest_hash,
            ),
            ("protocol id", definition.protocol_id, manifest.protocol_id),
            ("cohort id", definition.cohort_id, manifest.cohort_id),
            (
                "cohort fingerprint",
                definition.cohort_fingerprint,
                manifest.cohort_fingerprint,
            ),
            (
                "pair manifest hash",
                definition.pair_manifest_hash,
                manifest.pair_manifest_hash,
            ),
            (
                "definition profile fingerprint",
                definition.transform_profile_fingerprint,
                manifest.transform_profile_fingerprint,
            ),
            (
                "definition runtime fingerprint",
                definition.transform_runtime_fingerprint,
                manifest.transform_runtime_fingerprint,
            ),
            (
                "definition source commit",
                definition.source_commit,
                runtime.source_revision,
            ),
        ):
            if actual != expected:
                raise StorageError(
                    f"the stored {label} is {actual!r}, but the set names "
                    f"{expected!r}"
                )

        if definition.expected_total_images != manifest.total_images:
            raise StorageError(
                f"the definition promised {definition.expected_total_images} images "
                f"and the set holds {manifest.total_images}"
            )
        if list(definition.ordered_image_ids) != [
            entry.image_id for entry in entries
        ]:
            raise StorageError(
                "the set does not hold exactly the images its definition promised"
            )

        target = profile.target_ppi
        for entry in entries:
            if entry.transform_profile_fingerprint != profile.profile_fingerprint:
                raise StorageError(
                    f"{entry.image_id} was produced under a different transform "
                    "profile than the one stored beside it"
                )
            if entry.transform_runtime_fingerprint != runtime.runtime_fingerprint:
                raise StorageError(
                    f"{entry.image_id} was produced under a different transform "
                    "runtime than the one stored beside it"
                )
            if entry.transform_profile_id != profile.profile_id:
                raise StorageError(
                    f"{entry.image_id} names transform profile "
                    f"{entry.transform_profile_id!r}, not {profile.profile_id!r}"
                )
            if entry.output_effective_ppi != target:
                raise StorageError(
                    f"{entry.image_id} is {entry.output_effective_ppi} ppi; this "
                    f"profile targets {target}"
                )
            if entry.output_media_type != profile.output_media_type:
                raise StorageError(
                    f"{entry.image_id} is {entry.output_media_type}, not "
                    f"{profile.output_media_type}"
                )


def preparation_summary_content_hash(summary: Mapping[str, object]) -> str:
    """A digest of a preparation summary with its generation time removed."""
    payload = {
        key: value
        for key, value in dict(summary).items()
        if key not in {"generated_utc", "materialisation_wall_seconds"}
    }
    return stable_hash(
        {"schema": "preparation_summary_content_hash_v1", "summary": to_plain(payload)},
        length=64,
    )


def _is_preparation_receipt_schema_upgrade(
    stored: Mapping[str, object], new: PreparationReceipt
) -> bool:
    if str(stored.get("schema_version")) != "1" or new.schema_version != "2":
        return False
    current = dict(to_plain(new))
    ignored = {"schema_version", "created_utc"}
    return all(
        key in current and value == current[key]
        for key, value in stored.items()
        if key not in ignored
    )


def _is_preparation_finalization_schema_upgrade(
    stored: Mapping[str, object], new: PreparationFinalizationMarker
) -> bool:
    if str(stored.get("schema_version")) != "1" or new.schema_version != "2":
        return False
    invariant = (
        "preparation_set_id",
        "preparation_set_fingerprint",
        "transform_profile_fingerprint",
        "transform_runtime_fingerprint",
        "entries_table_content_hash",
        "summary_content_hash",
        "source_commit",
        "source_tree_clean",
    )
    return all(stored.get(key) == getattr(new, key) for key in invariant)


def _archive_preparation_publication(path: Path) -> Path:
    payload = read_json(path)
    version = str(payload.get("schema_version") or "unknown")
    fingerprint = stable_hash(payload, length=64)[:12]
    archive = (
        path.parent
        / "publication-history"
        / f"{path.stem}-v{version}-{fingerprint}.json"
    )
    if archive.is_file():
        if read_json(archive) != payload:
            raise PreparedImageSetConflictError(
                f"{archive} already holds different publication history"
            )
        return archive
    return write_json(archive, payload)


# ------------------------------------------------------------------ file helpers


def _digest_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(_READ_CHUNK), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _fsync_directory(path: Path) -> None:
    """Best effort: Windows cannot open a directory for fsync, and that is fine.

    The rename itself is atomic on both platforms; this only shortens the window
    in which a power loss could lose the directory entry.
    """
    try:  # pragma: no cover - platform dependent
        fd = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:  # pragma: no cover - platform dependent
        os.fsync(fd)
    except OSError:
        pass
    finally:  # pragma: no cover - platform dependent
        os.close(fd)


def _make_read_only(path: Path) -> None:
    """Best effort. The guarantee is the digest, not the permission bit."""
    try:
        mode = path.stat().st_mode
        path.chmod(mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    except OSError:  # pragma: no cover - platform dependent
        pass
