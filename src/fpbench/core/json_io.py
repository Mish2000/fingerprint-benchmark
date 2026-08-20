"""JSON documents, written the way this repository publishes a file.

Every JSON document in the workspace used to go through
``fpbench.core.serialization.write_json``, which writes a *fixed* sibling
``.tmp`` and replaces it. That is atomic against a crash and open to a
concurrent writer: two processes storing the same document write over each
other's scratch file, and the document that lands can be a mixture of both.

The fix belongs in ``write_json`` itself, and cannot go there.
``core/serialization.py`` is one of the seven paths Stage 8A's published
verifier pins byte-for-byte against its ``verifier_source_commit``, and editing
it turns a committed evidence gate red. The established response in this
repository is a sibling module rather than a widened allowlist — Stage 8B, 8D
and 8E each added one — so that is what this is.

``to_plain`` and ``read_json`` are re-exported from ``serialization`` unchanged:
the *encoding* was never the problem, only the writing. Callers should import
both halves from here, so that one module names how a JSON document is read and
written.

Two writers, and the choice between them is a statement about the document:

``write_json``
    Replaces whatever is there. For documents that are meant to be regenerated —
    evidence markers, reports, indexes. Byte-identical output to the pinned
    ``write_json``, written through a uniquely-named temp.

``publish_json``
    Creates the document exactly once and reports whether *this* caller is the
    one that created it. For immutable artefacts, where a second writer is a
    fact worth stopping for rather than an overwrite (docs/adr/0009).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fpbench.core.atomic_write import (
    PublishConflictError,
    PublishedFile,
    PublishOutcome,
    publish_bytes,
    replace_bytes,
)
from fpbench.core.serialization import read_json, stable_hash, to_plain

__all__ = [
    "PublishConflictError",
    "PublishOutcome",
    "PublishedFile",
    "json_bytes",
    "publish_json",
    "read_json",
    "stable_hash",
    "to_plain",
    "write_json",
]


def json_bytes(value: Any) -> bytes:
    """The exact bytes the writers below store, for hashing or comparison.

    ``\\n`` line endings on every platform, because these are the bytes a
    digest is taken over: a document whose fingerprint depends on the
    checkout's newline convention is not content-addressed.

    Identical to what the pinned ``serialization.write_json`` produces on a
    POSIX checkout, and — deliberately — on a Windows one too, where the old
    text-mode writer emitted ``\\r\\n``.
    """
    payload = json.dumps(to_plain(value), indent=2, ensure_ascii=False, sort_keys=False)
    return (payload + "\n").encode("utf-8")


def write_json(path: Path, value: Any) -> Path:
    """Write ``value`` as pretty, deterministic JSON, replacing any existing file.

    Creates parent directories. Atomic against a crash *and* against another
    writer's scratch file, which the fixed-``.tmp`` version was not.
    """
    replace_bytes(Path(path), json_bytes(value), what="JSON document")
    return Path(path)


def publish_json(path: Path, value: Any) -> PublishedFile:
    """Write ``value`` as JSON exactly once, refusing to replace another writer.

    Returns the publication outcome, so a caller can tell "I stored this" from
    "somebody else had already stored exactly this" — a distinction a
    replace-based writer cannot make.

    Raises:
        PublishConflictError: another writer published *different* bytes at this
            path first.
    """
    return publish_bytes(Path(path), json_bytes(value), what="JSON document")
