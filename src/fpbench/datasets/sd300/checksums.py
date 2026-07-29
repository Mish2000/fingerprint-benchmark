"""The SHA-256 manifests NIST ships alongside each image directory.

Every image directory is accompanied by ``checksum_PPI_EXT_IMPRESSION.csv``.
Reading them is cheap; verifying them means hashing 113 GB, so verification is
always opt-in.

The header is not consistent across the delivery: SD300A and SD300C use
``sha256,filename`` while SD300B uses ``sha256,name``. Both are accepted. This
matters more than it looks — a reader that only knows one spelling silently
finds no declared digests at all for the other release, and since an image with
no official digest is refused, the entire 1000 ppi release would drop out of
the study without anything obviously breaking.
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path
from typing import Iterator, Mapping

from fpbench.core.enums import Impression
from fpbench.core.errors import DatasetLayoutError

__all__ = [
    "checksum_filename",
    "load_checksums",
    "sha256_file",
    "iter_mismatches",
]

_READ_CHUNK = 1 << 20

#: Column headers NIST has used for the file name, in order of preference.
_FILENAME_COLUMNS = ("filename", "name")


def checksum_filename(ppi: int, impression: Impression, extension: str = "png") -> str:
    """Name of the NIST checksum file for one impression directory."""
    return f"checksum_{ppi}_{extension}_{impression.value}.csv"


def load_checksums(path: Path) -> dict[str, str]:
    """Read a NIST checksum CSV into ``{filename: sha256}``.

    Digests are lowercased so comparisons never fail on case alone.
    """
    path = Path(path)
    if not path.is_file():
        raise DatasetLayoutError(f"checksum file not found: {path}")

    result: dict[str, str] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or ()
        name_column = next(
            (column for column in _FILENAME_COLUMNS if column in fieldnames), None
        )
        if "sha256" not in fieldnames or name_column is None:
            raise DatasetLayoutError(
                f"{path}: expected a 'sha256' column and one of "
                f"{list(_FILENAME_COLUMNS)}, got {reader.fieldnames}"
            )
        for row in reader:
            filename = (row.get(name_column) or "").strip()
            digest = (row.get("sha256") or "").strip().lower()
            if not filename and not digest:
                continue
            if not filename or len(digest) != 64 or any(
                char not in "0123456789abcdef" for char in digest
            ):
                raise DatasetLayoutError(
                    f"{path}: invalid checksum row for {filename or '<missing filename>'}"
                )
            if filename in result:
                raise DatasetLayoutError(f"{path}: duplicate checksum entry for {filename}")
            result[filename] = digest
    return result


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(_READ_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_mismatches(
    directory: Path, expected: Mapping[str, str]
) -> Iterator[tuple[str, str | None, str]]:
    """Yield ``(filename, actual_digest_or_None, reason)`` for every disagreement.

    ``actual`` is ``None`` when the file listed in the manifest is absent.
    Files present on disk but absent from the manifest are reported too — an
    unexpected extra file is as much a curation signal as a missing one.
    """
    directory = Path(directory)
    on_disk = {p.name for p in directory.iterdir() if p.is_file()}

    for filename, digest in expected.items():
        if filename not in on_disk:
            yield filename, None, "missing_file"
            continue
        actual = sha256_file(directory / filename)
        if actual != digest:
            yield filename, actual, "checksum_mismatch"

    for filename in sorted(on_disk - set(expected)):
        yield filename, None, "unlisted_file"
