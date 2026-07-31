"""Pinning the code that actually evaluates the kernel, not just its name.

``Lanczos3`` is a specification. The profile pins the specification; this module
pins the *implementation*, and the two are separate because they fail
separately. A Pillow upgrade that changes one coefficient in the last bit
produces different pixels from an identical profile, and a benchmark whose
inputs differ in the last bit is a benchmark nobody can reproduce.

Recording ``Pillow 12.3.0`` is not enough for that. Two wheels can carry the
same version string and different compiled extensions — a different libjpeg, a
different zlib, a local patch. So the installed distribution's own files are
enumerated through ``importlib.metadata``, hashed, and folded into one digest.

Three things are deliberately kept out of that digest:

* **absolute installation paths** — a virtualenv in ``C:\\Users\\...`` and one in
  ``/opt/conda`` holding identical bytes are the same runtime;
* **``__pycache__``** — byte-compiled output depends on when the interpreter
  first imported a module, which is not a property of the distribution;
* **timestamps** — capturing the same environment twice is one runtime.

What *is* in it, besides Pillow: the interpreter, the platform, the zlib build
Pillow's PNG encoder is linked against (it decides the compressed bytes, though
not the pixels), the dependency lock file's digest, and the fpbench commit.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import platform
from pathlib import Path

from fpbench.core.errors import ImagingError, ResearchPreflightError
from fpbench.core.imaging_models import (
    TransformRuntimeManifest,
    transform_runtime_fingerprint,
    transform_runtime_id,
)
from fpbench.core.provenance_models import (
    SoftwareProvenance,
    software_provenance_fingerprint,
)
from fpbench.core.serialization import stable_hash

__all__ = [
    "DEPENDENCY_LOCK_PATH",
    "PILLOW_DISTRIBUTION",
    "capture_transform_runtime",
    "pillow_distribution_fingerprint",
    "dependency_lock_sha256",
    "pillow_zlib_version",
]

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]

#: The file that pins the resampler. Its digest is part of the runtime identity,
#: so editing the pin — even to a version that happens to already be installed —
#: produces a different runtime and therefore a different prepared-image set.
DEPENDENCY_LOCK_PATH = REPOSITORY_ROOT / "requirements-imaging.lock"

PILLOW_DISTRIBUTION = "Pillow"

_READ_CHUNK = 1 << 20


def capture_transform_runtime(
    *,
    software: SoftwareProvenance,
    dependency_lock: Path = DEPENDENCY_LOCK_PATH,
    created_utc: str | None = None,
) -> TransformRuntimeManifest:
    """Describe the environment that is about to compute canonical pixels.

    Args:
        software: The fpbench build doing the computing. A materialisation
            requires a clean committed tree; that is the caller's check, and this
            function records whatever it is given so that a development capture
            is still possible in a test.

    Raises:
        ImagingError: Pillow is not installed, or its installed distribution
            cannot be enumerated. Both mean there is nothing to pin.
    """
    version, distribution_fingerprint, file_count = pillow_distribution_fingerprint()

    fields = dict(
        software_fingerprint=software_provenance_fingerprint(software),
        dependency_lock_sha256=dependency_lock_sha256(dependency_lock),
        pillow_version=version,
        pillow_distribution_fingerprint=distribution_fingerprint,
        pillow_file_count=file_count,
        python_version=platform.python_version(),
        python_implementation=platform.python_implementation(),
        platform_system=platform.system(),
        platform_machine=platform.machine(),
        zlib_runtime_version=pillow_zlib_version(),
        source_revision=software.source_revision,
        source_tree_clean=software.source_tree_clean,
    )
    fingerprint = transform_runtime_fingerprint(_Draft(**fields))
    return TransformRuntimeManifest(
        runtime_id=transform_runtime_id(fingerprint),
        runtime_fingerprint=fingerprint,
        created_utc=created_utc or _utc_now(),
        **fields,
    )


def pillow_distribution_fingerprint() -> tuple[str, str, int]:
    """``(version, digest over the installed files, file count)``.

    Each regular file belonging to the distribution contributes its
    distribution-relative path, its size and its SHA-256, sorted by path.
    Directories and ``__pycache__`` are skipped; a file the metadata lists but
    that is not on disk is an error, because a distribution missing a file it
    claims is not the distribution it claims to be.
    """
    from importlib.metadata import PackageNotFoundError, distribution

    try:
        found = distribution(PILLOW_DISTRIBUTION)
    except PackageNotFoundError as exc:  # pragma: no cover - unusual install
        raise ImagingError(
            f"{PILLOW_DISTRIBUTION} is not installed; there is no resampler to pin. "
            f"Install the pin in {DEPENDENCY_LOCK_PATH.name}"
        ) from exc

    listed = found.files
    if not listed:  # pragma: no cover - unusual install
        raise ImagingError(
            f"{PILLOW_DISTRIBUTION} reports no installed files, so its bytes cannot "
            "be fingerprinted"
        )

    records: list[dict[str, object]] = []
    for entry in listed:
        relative = str(entry).replace("\\", "/")
        if "__pycache__/" in relative or relative.endswith(".pyc"):
            continue
        located = Path(found.locate_file(entry))
        if located.is_dir():
            continue
        if not located.is_file():
            raise ImagingError(
                f"{PILLOW_DISTRIBUTION} lists {relative} but it is not on disk; the "
                "installed distribution does not match its own metadata"
            )
        digest, size = _digest_file(located)
        records.append({"path": relative, "size": size, "sha256": digest})

    if not records:  # pragma: no cover - unusual install
        raise ImagingError(f"{PILLOW_DISTRIBUTION} contributed no hashable files")

    records.sort(key=lambda record: record["path"])
    fingerprint = stable_hash(
        {
            "schema": "pillow_distribution_fingerprint_v1",
            "distribution": PILLOW_DISTRIBUTION,
            "files": records,
        },
        length=64,
    )
    return str(found.version), fingerprint, len(records)


def dependency_lock_sha256(path: Path = DEPENDENCY_LOCK_PATH) -> str:
    """The digest of the file that pins the resampler.

    Raises:
        ResearchPreflightError: the lock is missing. A canonical set whose
            resampler was never pinned cannot be reproduced from the repository.
    """
    lock = Path(path)
    if not lock.is_file():
        raise ResearchPreflightError(
            f"the imaging dependency lock is missing: {lock}. A prepared-image set "
            "must name the exact resampler it was produced with"
        )
    digest, _ = _digest_file(lock)
    return digest


def pillow_zlib_version() -> str:
    """The zlib build Pillow's PNG encoder is linked against.

    Deliberately Pillow's, not ``zlib.ZLIB_RUNTIME_VERSION``. The stdlib's zlib
    compresses nothing in this pipeline; the one inside Pillow decides the bytes
    of every canonical PNG, and the two are frequently different builds — on this
    project's reference environment the stdlib reports ``1.3.2`` while Pillow
    reports a zlib-ng.
    """
    from PIL import features

    version = features.version("zlib")
    if not version:  # pragma: no cover - Pillow without zlib cannot write PNG
        raise ImagingError(
            "Pillow reports no zlib support, so it cannot encode a canonical PNG"
        )
    return str(version)


# ----------------------------------------------------------------- internals


class _Draft:
    """A runtime-shaped stand-in used only to compute the fingerprint.

    :class:`TransformRuntimeManifest` re-derives and checks its own fingerprint,
    so it cannot be built before one exists. Feeding the rule a stand-in keeps
    the rule in one place instead of copying it here.
    """

    __slots__ = (
        "software_fingerprint",
        "dependency_lock_sha256",
        "pillow_version",
        "pillow_distribution_fingerprint",
        "pillow_file_count",
        "python_version",
        "python_implementation",
        "platform_system",
        "platform_machine",
        "zlib_runtime_version",
        "source_revision",
        "source_tree_clean",
    )

    def __init__(self, **fields: object) -> None:
        for name in self.__slots__:
            setattr(self, name, fields[name])


def _digest_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(_READ_CHUNK), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()
