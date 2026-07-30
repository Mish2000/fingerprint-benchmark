"""Copying an external executable into a place it cannot change from.

The problem this solves is small and fatal. The SourceAFIS bridge jar lives in
``integrations/sourceafis-java/target/``, which is build output: one ``mvnw
package`` replaces it, at the same path, with different bytes. A run that
recorded the *path* — or that recorded the digest once during preflight and
then kept launching whatever was at that path — could execute two different
programs and attribute both to one environment fingerprint (docs/adr/0018).

So before a research run starts, the bytes are copied once into::

    <workspace>/runtime/bundles/<bundle_id>/
    ├── bundle.json
    └── assets/fpbench-sourceafis-bridge.jar

and ``bundle_id`` is derived from the contents. The same jar built on another
machine six months later materialises to the same id; a jar that differs by one
byte materialises somewhere else entirely and can never be mistaken for it.

Three rules make the copy trustworthy:

**Copy, never link.** No symlink and — importantly — no hardlink. A hardlink
would share an inode with the build output, so ``mvnw package`` writing in place
would silently rewrite the "immutable" asset too. The whole point is to stop
depending on a path nobody controls.

**Verify the copy, not the source.** The digest is computed over the bytes as
they are written and compared against the digest of the bytes as they were
read. A copy that was truncated or corrupted mid-write never becomes an asset.

**Write the manifest last.** ``bundle.json`` is the marker that says a bundle is
complete. A crash between assets leaves a directory with no manifest — visibly
unfinished — rather than a manifest describing assets that were never written.

There is no overwrite and no repair. A bundle directory whose contents no
longer match its own fingerprint is reported, never fixed: silently restoring a
file would destroy the evidence that something replaced it.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import os
import stat
from pathlib import Path
from typing import Mapping

from fpbench.core.errors import RuntimeBundleConflictError, StorageError
from fpbench.core.runtime_models import (
    CONTENT_ADDRESSED_COPY_V1,
    RuntimeAssetDefinition,
    RuntimeBundleDefinition,
    RuntimeBundleVerification,
    runtime_bundle_fingerprint,
    runtime_bundle_id,
)
from fpbench.core.serialization import read_json, write_json
from fpbench.storage import layout

__all__ = ["RuntimeBundleStore", "MEDIA_TYPES", "DEFAULT_MEDIA_TYPE", "media_type_for"]

_BUNDLE_MANIFEST = "bundle.json"
_READ_CHUNK = 1 << 20

#: Suffix to media type. Small and explicit: a guess from ``mimetypes`` depends
#: on the machine's registry, and a media type that differs between two
#: machines would change the bundle fingerprint for the same bytes.
MEDIA_TYPES: Mapping[str, str] = {
    ".jar": "application/java-archive",
    ".zip": "application/zip",
    ".so": "application/x-sharedlib",
    ".dll": "application/vnd.microsoft.portable-executable",
    ".exe": "application/vnd.microsoft.portable-executable",
}

DEFAULT_MEDIA_TYPE = "application/octet-stream"


def media_type_for(filename: str) -> str:
    return MEDIA_TYPES.get(Path(filename).suffix.lower(), DEFAULT_MEDIA_TYPE)


class RuntimeBundleStore:
    """Content-addressed, immutable storage for external runtime assets."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    # ------------------------------------------------------------------ paths

    @property
    def bundles_root(self) -> Path:
        return layout.runtime_bundles_root(self.root)

    def bundle_dir(self, bundle_id: str) -> Path:
        return layout.runtime_bundle_directory(self.root, bundle_id)

    def bundle_manifest_path(self, bundle_id: str) -> Path:
        return self.bundle_dir(bundle_id) / _BUNDLE_MANIFEST

    def assets_dir(self, bundle_id: str) -> Path:
        return layout.runtime_bundle_assets_directory(self.root, bundle_id)

    def asset_path(self, bundle_id: str, role: str) -> Path:
        """Where the file for ``role`` lives. Raises if the bundle has no such role."""
        bundle = self.read_bundle(bundle_id)
        asset = bundle.asset(role)
        return self.bundle_dir(bundle_id) / asset.relative_path

    def has_bundle(self, bundle_id: str) -> bool:
        return self.bundle_manifest_path(bundle_id).is_file()

    def bundle_ids(self) -> tuple[str, ...]:
        if not self.bundles_root.is_dir():
            return ()
        return tuple(
            sorted(
                path.name
                for path in self.bundles_root.iterdir()
                if (path / _BUNDLE_MANIFEST).is_file()
            )
        )

    # ----------------------------------------------------------- materialise

    def materialize(
        self,
        *,
        adapter_id: str,
        assets: Mapping[str, Path],
        materialization_policy: str = CONTENT_ADDRESSED_COPY_V1,
    ) -> RuntimeBundleDefinition:
        """Copy ``assets`` into an immutable bundle and return its definition.

        Args:
            adapter_id: The adapter these assets belong to. Part of the
                fingerprint, so the same jar under two adapters is two bundles.
            assets: ``role -> source path``. Each source must be an existing
                regular file — not a symlink, not a directory.

        Returns:
            The bundle definition, whether it was written now or already there.

        Raises:
            StorageError: a source is unusable, or a copy did not survive.
            RuntimeBundleConflictError: a bundle with this id exists and
                describes something else.
        """
        if not assets:
            raise StorageError("a runtime bundle needs at least one asset")

        described: list[RuntimeAssetDefinition] = []
        digests: dict[str, tuple[str, int]] = {}
        for role, source in sorted(assets.items()):
            path = self._require_regular_file(Path(source), role)
            digest, size = _digest_file(path)
            digests[role] = (digest, size)
            described.append(
                RuntimeAssetDefinition.create(
                    role=role,
                    filename=path.name,
                    sha256=digest,
                    size_bytes=size,
                    media_type=media_type_for(path.name),
                )
            )

        fingerprint = runtime_bundle_fingerprint(
            adapter_id=adapter_id,
            materialization_policy=materialization_policy,
            assets=described,
        )
        bundle_id = runtime_bundle_id(fingerprint)

        if self.has_bundle(bundle_id):
            stored = self.read_bundle(bundle_id)
            if stored.bundle_fingerprint != fingerprint:
                raise RuntimeBundleConflictError(
                    f"runtime bundle {bundle_id} already describes "
                    f"{stored.bundle_fingerprint[:12]}..., not {fingerprint[:12]}..."
                )
            # Same bytes, same bundle: a no-op, but only after confirming the
            # stored copy is still the one it claims to be.
            verification = self.verify_bundle(bundle_id)
            if not verification.is_valid:
                raise RuntimeBundleConflictError(
                    f"runtime bundle {bundle_id} is on disk but no longer intact: "
                    f"{'; '.join(verification.issues[:3])}"
                )
            return stored

        definition = RuntimeBundleDefinition(
            bundle_id=bundle_id,
            bundle_fingerprint=fingerprint,
            adapter_id=adapter_id,
            materialization_policy=materialization_policy,
            assets=tuple(described),
            created_utc=_utc_now(),
        )

        assets_dir = self.assets_dir(bundle_id)
        assets_dir.mkdir(parents=True, exist_ok=True)
        for asset in definition.assets:
            source = Path(assets[asset.role])
            target = self.bundle_dir(bundle_id) / asset.relative_path
            self._copy_verified(source, target, expected=digests[asset.role])

        # Last, and only now: the marker that the bundle is complete.
        write_json(self.bundle_manifest_path(bundle_id), definition)
        return definition

    # ------------------------------------------------------------------ read

    def read_bundle(self, bundle_id: str) -> RuntimeBundleDefinition:
        path = self.bundle_manifest_path(bundle_id)
        if not path.is_file():
            raise StorageError(f"runtime bundle manifest not found: {path}")
        payload = read_json(path)
        try:
            return RuntimeBundleDefinition(
                bundle_id=payload["bundle_id"],
                bundle_fingerprint=payload["bundle_fingerprint"],
                adapter_id=payload["adapter_id"],
                materialization_policy=payload["materialization_policy"],
                assets=tuple(
                    RuntimeAssetDefinition(
                        asset_id=item["asset_id"],
                        role=item["role"],
                        filename=item["filename"],
                        sha256=item["sha256"],
                        size_bytes=item["size_bytes"],
                        media_type=item["media_type"],
                        relative_path=item["relative_path"],
                    )
                    for item in payload["assets"]
                ),
                created_utc=payload["created_utc"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError(
                f"{path}: unreadable runtime bundle manifest ({exc})"
            ) from exc

    # ---------------------------------------------------------------- verify

    def verify_bundle(self, bundle_id: str) -> RuntimeBundleVerification:
        """Re-read every asset and confirm it is still what the manifest says.

        The expensive check — it hashes every byte — and therefore the one run
        before an executor starts and again after it stops, rather than before
        every comparison. The cheap per-comparison check is the adapter's
        (docs/adr/0018).

        Never raises for a damaged bundle: the damage is the answer. It raises
        only when the manifest itself cannot be read, because then there is no
        claim to check against.
        """
        bundle = self.read_bundle(bundle_id)
        issues: list[str] = []
        verified = 0

        for asset in bundle.assets:
            path = self.bundle_dir(bundle_id) / asset.relative_path
            label = f"{asset.role}/{asset.filename}"
            if not path.exists():
                issues.append(f"{label} is missing")
                continue
            if path.is_symlink() or not path.is_file():
                issues.append(f"{label} is not a regular file")
                continue
            size = path.stat().st_size
            if size != asset.size_bytes:
                issues.append(
                    f"{label} is {size} bytes, expected {asset.size_bytes}"
                )
                continue
            digest, _ = _digest_file(path)
            if digest != asset.sha256:
                issues.append(
                    f"{label} hashes to {digest[:12]}..., expected "
                    f"{asset.sha256[:12]}..."
                )
                continue
            verified += 1

        recomputed = runtime_bundle_fingerprint(
            adapter_id=bundle.adapter_id,
            materialization_policy=bundle.materialization_policy,
            assets=bundle.assets,
        )
        if recomputed != bundle.bundle_fingerprint:
            issues.append("the manifest does not fingerprint to its own id")
        if runtime_bundle_id(recomputed) != bundle.bundle_id:
            issues.append("the manifest is stored under a foreign bundle id")

        return RuntimeBundleVerification(
            bundle_id=bundle.bundle_id,
            bundle_fingerprint=bundle.bundle_fingerprint,
            verified_assets=verified,
            issues=tuple(issues),
            inspected_utc=_utc_now(),
        )

    def require_valid(self, bundle_id: str) -> RuntimeBundleVerification:
        """Verify, and raise if anything is wrong.

        For the callers that cannot continue on a damaged runtime — which is
        every caller in a research run.
        """
        verification = self.verify_bundle(bundle_id)
        if not verification.is_valid:
            raise RuntimeBundleConflictError(
                f"runtime bundle {bundle_id} failed verification: "
                f"{'; '.join(verification.issues[:3])}"
            )
        return verification

    # --------------------------------------------------------------- internal

    @staticmethod
    def _require_regular_file(source: Path, role: str) -> Path:
        if source.is_symlink():
            raise StorageError(
                f"runtime asset {role!r} is a symlink; a bundle must own its bytes, "
                "not point at someone else's"
            )
        if not source.exists():
            raise StorageError(f"runtime asset {role!r} does not exist: {source.name}")
        if not source.is_file():
            raise StorageError(
                f"runtime asset {role!r} is not a regular file: {source.name}"
            )
        return source

    def _copy_verified(
        self, source: Path, target: Path, *, expected: tuple[str, int]
    ) -> Path:
        """Copy bytes, hash what was written, fsync, then replace atomically."""
        expected_digest, expected_size = expected
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")

        digest = hashlib.sha256()
        written = 0
        try:
            with source.open("rb") as reader, tmp.open("wb") as writer:
                for chunk in iter(lambda: reader.read(_READ_CHUNK), b""):
                    writer.write(chunk)
                    digest.update(chunk)
                    written += len(chunk)
                writer.flush()
                os.fsync(writer.fileno())

            if digest.hexdigest() != expected_digest or written != expected_size:
                raise StorageError(
                    f"the copy of {source.name} does not match the source it was "
                    "read from; the file changed while it was being materialised"
                )
            tmp.replace(target)
        finally:
            tmp.unlink(missing_ok=True)

        _make_read_only(target)
        return target


def _digest_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(_READ_CHUNK), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _make_read_only(path: Path) -> None:
    """Best effort. A filesystem that refuses is not a reason to fail a run.

    The permission bit is a courtesy — it makes an accidental overwrite awkward.
    It is not the guarantee; the guarantee is that ``verify_bundle`` recomputes
    the digest and notices.
    """
    try:
        mode = path.stat().st_mode
        path.chmod(mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    except OSError:  # pragma: no cover - platform dependent
        pass


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()
