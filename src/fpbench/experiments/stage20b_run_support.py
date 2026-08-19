"""The small pieces the Stage 20B drivers share, and nothing that decides a score.

Two things live here, both of them plumbing:

* :func:`to_local` — the workspace manifests hold Windows paths, and the run
  executes on the certified Linux target. Translating ``C:\\x`` to ``/mnt/c/x``
  is not a research decision, but writing it twice would be an invitation to
  write it differently the second time.
* :func:`as_prepared` — one published preparation entry as the adapter contract's
  :class:`~fpbench.core.execution_models.PreparedImage`. The entry hash is read
  straight from the published parquet rather than through Stage 18A's input
  reader, because that module's bytes are pinned by Stage 18A's finalization
  marker and widening its dataclass for a Stage 20B need would invalidate a
  published fingerprint.

Nothing here selects a pair, a cohort or an image.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from fpbench.core.enums import ChecksumStatus
from fpbench.core.execution_models import PreparedImage
from fpbench.experiments.stage18a_inputs import REPOSITORY_ROOT

__all__ = [
    "PREPARATION_PROFILE_ID",
    "PREPARATION_SET_DIRECTORY",
    "to_local",
    "entry_hashes",
    "as_prepared",
]

PREPARATION_PROFILE_ID = "canonical_gray8_500ppi_lanczos3_v1"
PREPARATION_SET_DIRECTORY = "prepset_be560e047991"


def to_local(path: Path) -> Path:
    """A workspace path as the path *this* process can open.

    A no-op on Windows. Under WSL, ``C:\\x\\y`` becomes ``/mnt/c/x/y``, which is
    the same bytes reached through the 9p mount rather than a copy of them.
    """
    text = str(path)
    if len(text) > 2 and text[1] == ":":
        return Path("/mnt/" + text[0].lower() + text[2:].replace("\\", "/"))
    return Path(text)


def entry_hashes(repository_root: Path = REPOSITORY_ROOT) -> Mapping[str, str]:
    """``image_id -> the preparation set's own per-entry hash``."""
    import pyarrow.parquet as pq

    table = pq.read_table(
        Path(repository_root)
        / "workspace"
        / "prepared-images"
        / PREPARATION_SET_DIRECTORY
        / "entries.parquet",
        columns=["image_id", "entry_hash"],
    )
    return {row["image_id"]: row["entry_hash"] for row in table.to_pylist()}


def as_prepared(entry, entry_hash: str) -> PreparedImage:
    """One preparation entry as the adapter contract's ``PreparedImage``."""
    return PreparedImage(
        image_id=entry.image_id,
        local_path=to_local(entry.path),
        effective_ppi=500,
        media_type="image/png",
        expected_sha256=entry.output_encoded_sha256,
        checksum_status=ChecksumStatus.VERIFIED,
        preparation_profile_id=PREPARATION_PROFILE_ID,
        preparation_hash=entry_hash,
        prepared_sha256=entry.output_encoded_sha256,
        pixel_sha256=entry.output_pixel_sha256,
        pixel_width=entry.output_width,
        pixel_height=entry.output_height,
    )
