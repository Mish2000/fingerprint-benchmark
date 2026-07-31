"""Getting from a manifest row to the bytes it describes, safely.

Two small jobs that would otherwise be done slightly differently in four places.

**Resolving a path.** The same rules the identity preparer already applies: the
relative path must really be relative, it must not escape the dataset root once
resolved, the target must exist, and it must be a regular file rather than a
symlink pointing somewhere else. A canonical set that materialised a file from
outside the dataset root would be evidence about a file nobody agreed to.

**Fingerprinting a record.** A prepared entry records which *manifest row* it was
produced from, not only which bytes. The two differ in a way that matters: the
manifest is where ``effective_ppi`` lives, and ``effective_ppi`` is what decided
the scale. An image manifest rebuilt with a different resolution policy would
leave the file's digest unchanged and the transformation wrong, and only a
fingerprint over the row catches that (docs/adr/0032).
"""

from __future__ import annotations

import stat
from pathlib import Path, PurePosixPath, PureWindowsPath

from fpbench.core.errors import ImagingError
from fpbench.core.models import ImageRecord
from fpbench.core.serialization import stable_hash

__all__ = ["resolve_source_path", "source_record_fingerprint"]


def resolve_source_path(record: ImageRecord, dataset_root: Path) -> Path:
    """Locate one source image inside the dataset root.

    Raises:
        ImagingError: the path is absolute, escapes the root, does not exist, is
            not a regular file, or is a symlink.
    """
    relative = record.relative_path
    if PurePosixPath(relative).is_absolute() or PureWindowsPath(relative).is_absolute():
        raise ImagingError(
            f"{record.image_id}: relative_path must be relative, got {relative!r}"
        )

    root = Path(dataset_root).resolve()
    parts = tuple(
        part
        for part in PurePosixPath(relative.replace("\\", "/")).parts
        if part not in ("", ".")
    )
    unresolved = root.joinpath(*parts)

    # Inspect the names before resolving them. Once ``resolve()`` has followed a
    # link, ``is_symlink()`` sees only the target and an in-root link becomes
    # indistinguishable from the delivery's own directory or file.
    current = root
    for part in parts:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            break
        except OSError as exc:
            raise ImagingError(
                f"{record.image_id}: cannot inspect source path component "
                f"{part!r} ({type(exc).__name__})"
            ) from exc
        if stat.S_ISLNK(mode):
            raise ImagingError(
                f"{record.image_id}: source path component {part!r} is a symlink; "
                "a canonical artefact must be derived from the delivery's own bytes"
            )

    candidate = unresolved.resolve()
    if not candidate.is_relative_to(root):
        raise ImagingError(
            f"{record.image_id}: {relative!r} resolves outside the dataset root"
        )
    if not candidate.exists():
        raise ImagingError(f"{record.image_id}: source file not found: {relative}")
    if not candidate.is_file():
        raise ImagingError(f"{record.image_id}: {relative} is not a regular file")
    return candidate


def source_record_fingerprint(record: ImageRecord) -> str:
    """A digest of the manifest row a canonical artefact was produced from.

    Excludes ``relative_path``: where a delivery is unpacked is not a property of
    the image, and two machines with different roots must agree. Includes
    ``effective_ppi`` and ``metadata_ppi`` separately, because the whole SD300C
    question is that they disagree and only one of them is authoritative
    (docs/adr/0004).
    """
    return stable_hash(
        {
            "schema": "source_image_record_fingerprint_v1",
            "image_id": str(record.image_id),
            "dataset_id": record.dataset_id,
            "release": record.release,
            "subject_id": str(record.subject_id),
            "impression": record.impression.value,
            "position": int(record.position) if record.position is not None else None,
            "is_multi_finger": bool(record.is_multi_finger),
            "effective_ppi": record.effective_ppi,
            "metadata_ppi": record.metadata_ppi,
            "expected_sha256": record.expected_sha256,
            "checksum_status": record.checksum_status.value,
            "blocking_issues": list(record.blocking_issues),
        },
        length=64,
    )
