"""Where the pinned artifacts live, and proof that they are still themselves.

Nothing here downloads and nothing here trusts a path.  Every load rehashes the
source archive, the extracted files the worker imports, and the checkpoint,
because an artifact that was correct when the bundle was built is not evidence
that it is correct now (spec section 4).

The digests of the imported source files are not derived from the archive at
runtime.  They are frozen constants, checked against the archive when the
bundle is built, so a tampered extraction cannot pass by rewriting the archive
and the tree together.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from fpbench.core.flx_errors import FlxArtifactError
from fpbench.core.flx_models import STAGE8B_SCHEMA_VERSION, FlxArtifactBinding
from fpbench.flx import identity
from fpbench.flx.lock import file_sha256

__all__ = [
    "IMPORTED_SOURCE_FILES",
    "STAGE8A_CRLF_NORMALIZED_DIGESTS",
    "SOURCE_ARCHIVE_SIZE_BYTES",
    "FlxRuntimeBundle",
    "verify_bundle_artifacts",
    "build_artifact_binding",
]

SOURCE_ARCHIVE_SIZE_BYTES = 7149830

#: Exactly the files ``import flx.models.deep_print_arch`` reaches, digested as
#: they appear *inside the pinned archive*.  These are the bytes Python
#: compiles, so these are the bytes that are pinned.
IMPORTED_SOURCE_FILES: Mapping[str, tuple[str, int]] = {
    "LICENSE": (
        "a5681bf9b05db14d86776930017c647ad9e6e56ff6bbcfdf21e5848288dfaf1b",
        7651,
    ),
    "flx/__init__.py": (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        0,
    ),
    "flx/models/__init__.py": (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        0,
    ),
    "flx/models/InceptionV4.py": (
        "1710c5f122cb7f4a4173fb34c57b32abdb6276ef9285e1922b67fef229e8cf73",
        9291,
    ),
    "flx/models/deep_print_arch.py": (
        "b2bfaa2806cdd68c3d7c42e61d3ebdfd4cef356f73e400932c3037705d7c71f1",
        15235,
    ),
    "flx/models/localization_network.py": (
        "a2360367889030acac780a13609607d92e729e3fe628178bdea7c07d766f1259",
        2279,
    ),
}

#: Stage 8A digested the same files fetched over ``raw.githubusercontent.com``
#: on a Windows host, and recorded them with CRLF line endings.  Those digests
#: are correct for the bytes Stage 8A hashed and describe the same content, but
#: they are not the digests of the files inside the pinned archive.  Measured,
#: for all five components Stage 8A pinned individually: converting the archive
#: bytes to CRLF reproduces the Stage 8A digest exactly.
#:
#: The archive digest itself, ``60fa2c88…``, is unaffected and matches, so the
#: two records agree about *what* the source is.  Stage 8B binds to the archive
#: and to the archive's own file digests, because those are the bytes that get
#: executed.  ``tests/unit/test_stage8b_artifacts.py`` re-derives the CRLF
#: relationship rather than asserting it, so the reconciliation stays true.
STAGE8A_CRLF_NORMALIZED_DIGESTS: Mapping[str, tuple[str, int]] = {
    "LICENSE": (
        "f831e7eed577481687a9bc0b48024e5e40b6f655fcde073ede964b50be5d55d9",
        7815,
    ),
    "flx/models/deep_print_arch.py": (
        "cd47acea82815d5451f84ad5985f0630c5a0115762e0f504552c73f6f2fbafd9",
        15695,
    ),
    "flx/data/image_helpers.py": (
        "7f93fb781c857183edb0e2be6229feebb18d099a3060818f2287dbad6c2debcd",
        2345,
    ),
    "flx/data/image_loader.py": (
        "cadf869df515b8dfa441d6a3f4acf3db69e5b248eb6114e2c8e033239a6af4a6",
        4484,
    ),
    "flx/benchmarks/matchers.py": (
        "7c882182eedac5e25a2a9df2c7ce5e571d0eaac86ddd73512c3f06413fb441d7",
        1970,
    ),
}


@dataclass(frozen=True, slots=True)
class FlxRuntimeBundle:
    """The on-disk runtime, addressed by a root the caller supplies explicitly."""

    root: Path

    @classmethod
    def from_environment(cls) -> "FlxRuntimeBundle":
        configured = os.environ.get("FPBENCH_FLX_BUNDLE")
        if configured:
            return cls(Path(configured))
        return cls(
            Path.home() / ".cache" / "fpbench" / "flx" / identity.RUNTIME_PROFILE_ID
        )

    @property
    def wheels(self) -> Path:
        return self.root / "wheels"

    @property
    def venv(self) -> Path:
        return self.root / "venv"

    @property
    def venv_python(self) -> Path:
        windows = self.venv / "Scripts" / "python.exe"
        return windows if windows.exists() else self.venv / "bin" / "python"

    @property
    def source_archive(self) -> Path:
        return self.root / "source" / "fixed-length-fingerprint-extractors-7accfca.tar.gz"

    @property
    def source_tree(self) -> Path:
        return self.root / "source" / "tree"

    @property
    def checkpoint(self) -> Path:
        return self.root / "checkpoint" / identity.CHECKPOINT_FILENAME

    @property
    def manifest(self) -> Path:
        return self.root / "bundle-manifest.json"

    def disk_bytes(self) -> int:
        total = 0
        for path in self.root.rglob("*"):
            try:
                if path.is_file() and not path.is_symlink():
                    total += path.stat().st_size
            except OSError:
                continue
        return total


def _require_regular_file(path: Path, what: str) -> Path:
    try:
        info = path.lstat()
    except OSError as exc:
        raise FlxArtifactError(f"{what} is missing: {path}") from exc
    if path.is_symlink():
        raise FlxArtifactError(f"{what} may not be a link: {path}")
    if not info.st_mode & 0o100000:
        raise FlxArtifactError(f"{what} is not a regular file: {path}")
    return path


def _check_shape(path: Path, size: int, what: str) -> None:
    _require_regular_file(path, what)
    actual_size = path.stat().st_size
    if actual_size != size:
        raise FlxArtifactError(
            f"{what}: byte size changed (expected {size}, got {actual_size})"
        )


def _check_digest(path: Path, digest: str, what: str) -> None:
    actual_digest = file_sha256(path)
    if actual_digest != digest:
        raise FlxArtifactError(
            f"{what}: SHA-256 changed (expected {digest}, got {actual_digest})"
        )


def verify_bundle_artifacts(bundle: FlxRuntimeBundle) -> Mapping[str, Any]:
    """Rehash everything the runtime will read.  Any mismatch is fatal.

    Presence and size are checked for every artifact before any of them is
    hashed.  A truncated 835 MiB checkpoint should be reported as a truncated
    checkpoint, not discovered after eight hundred megabytes of SHA-256.
    """
    artifacts: tuple[tuple[Path, str, int, str], ...] = (
        (
            bundle.source_archive,
            identity.SOURCE_ARCHIVE_SHA256,
            SOURCE_ARCHIVE_SIZE_BYTES,
            "source archive",
        ),
        *(
            (bundle.source_tree / relative, digest, size, f"source file {relative}")
            for relative, (digest, size) in IMPORTED_SOURCE_FILES.items()
        ),
        (
            bundle.checkpoint,
            identity.CHECKPOINT_SHA256,
            identity.CHECKPOINT_SIZE_BYTES,
            "checkpoint",
        ),
    )
    for path, _, size, what in artifacts:
        _check_shape(path, size, what)
    for path, digest, _, what in artifacts:
        _check_digest(path, digest, what)
    return {
        "source_archive_sha256": identity.SOURCE_ARCHIVE_SHA256,
        "source_files_verified": len(IMPORTED_SOURCE_FILES),
        "checkpoint_sha256": identity.CHECKPOINT_SHA256,
        "checkpoint_size_bytes": identity.CHECKPOINT_SIZE_BYTES,
        "bundle_disk_bytes": bundle.disk_bytes(),
    }


def build_artifact_binding(
    bundle: FlxRuntimeBundle,
    *,
    stage8a_manifest_fingerprint: str,
    inspected_utc: str,
) -> FlxArtifactBinding:
    """Verify first, then state what was verified.  Never the other way round."""
    verify_bundle_artifacts(bundle)
    return FlxArtifactBinding.create(
        schema_version=STAGE8B_SCHEMA_VERSION,
        binding_id="flx_artifact_binding_v1",
        algorithm_id=identity.ALGORITHM_ID,
        source_commit=identity.SOURCE_COMMIT,
        source_archive_sha256=identity.SOURCE_ARCHIVE_SHA256,
        source_tree_verified_files=len(IMPORTED_SOURCE_FILES),
        checkpoint_filename=identity.CHECKPOINT_FILENAME,
        checkpoint_sha256=identity.CHECKPOINT_SHA256,
        checkpoint_size_bytes=identity.CHECKPOINT_SIZE_BYTES,
        checkpoint_variant=identity.CHECKPOINT_VARIANT,
        implementation_origin=identity.IMPLEMENTATION_ORIGIN,
        upstream_study=identity.UPSTREAM_STUDY,
        upstream_relationship=identity.UPSTREAM_RELATIONSHIP,
        stage8a_manifest_fingerprint=stage8a_manifest_fingerprint,
        weights_license_status=identity.WEIGHTS_LICENSE_STATUS,
        redistribution_allowed=identity.REDISTRIBUTION_ALLOWED,
        publication_permission=identity.PUBLICATION_PERMISSION,
        checkpoint_committed_to_git=False,
        downloaded_during_inference=False,
        inspected_utc=inspected_utc,
    )
