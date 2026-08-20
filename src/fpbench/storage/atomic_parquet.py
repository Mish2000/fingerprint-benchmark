"""The one way this repository writes a parquet file.

Every store used to inline the same three lines — fixed sibling ``.tmp``,
``pq.write_table``, ``replace()`` — which meant every store had the same
concurrency bug and each one had to be fixed separately. Both writers here
delegate their atomicity to :mod:`fpbench.core.atomic_write`, so there is one
place to reason about and one place to change.

Choosing between them is a statement about the artefact, not about the caller:

``publish_table``
    The file is an immutable artefact whose name is a claim about its content —
    one job's raw result, one content-addressed blob. Exactly one writer may
    create it, and a writer that loses the race is told so.

``replace_table``
    The file is a derived body that a guarded ``ensure_*`` may legitimately
    rewrite, and whose authority comes from a manifest published beside it.
    Atomic against a crash and against a concurrent writer's *scratch* file;
    the manifest is what serialises the writers themselves.
"""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from fpbench.core.atomic_write import PublishedFile, publish_file, replace_file

__all__ = ["publish_table", "replace_table"]

_COMPRESSION = "zstd"


def publish_table(
    path: Path, table: pa.Table, *, what: str = "parquet artefact"
) -> PublishedFile:
    """Create ``path`` exactly once from ``table``.

    Raises:
        fpbench.core.atomic_write.PublishConflictError: another writer published
            different bytes at this path first.
    """
    return publish_file(
        Path(path),
        lambda temporary: pq.write_table(table, temporary, compression=_COMPRESSION),
        what=what,
    )


def replace_table(
    path: Path, table: pa.Table, *, what: str = "parquet body"
) -> Path:
    """Write ``path`` from ``table``, replacing any existing file, atomically."""
    return replace_file(
        Path(path),
        lambda temporary: pq.write_table(table, temporary, compression=_COMPRESSION),
        what=what,
    )
