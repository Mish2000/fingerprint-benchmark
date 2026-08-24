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
from fpbench.core.evidence_sanitisation import (
    find_absolute_paths,
    redact_absolute_paths,
)
from fpbench.core.serialization import read_json, stable_hash, to_plain

__all__ = [
    "PublishConflictError",
    "PublishOutcome",
    "PublishedFile",
    "json_bytes",
    "publish_evidence_document",
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


def publish_evidence_document(path: Path, payload: Any) -> Path:
    """Write one evidence document, with no machine's paths left in it.

    Two steps, and the second is the one that matters.
    :func:`~fpbench.core.evidence_sanitisation.redact_absolute_paths` replaces
    the roots it recognises; the check afterwards refuses anything *still*
    shaped like an absolute path, so a root nobody anticipated stops the
    publication instead of being published.

    This is the door a stage's documents go through. Before it existed the
    redactor was available and uncalled, which is how
    ``stage11a-.../runtime-identity.json`` came to publish seven module paths
    under the author's home directory while its own marker declared there were
    none (evidence/README.md, docs/adr/0139).

    Sorted keys and LF, matching what the stage writers already emitted, so
    routing an existing writer through this changes no byte of a clean document.

    Written through :func:`~fpbench.core.atomic_write.replace_bytes` rather than
    ``Path.write_bytes``. An evidence marker is *meant* to be regenerated, so
    replace-if-present is the right semantic — but the bare write was not even
    atomic against a crash, which for the one door every stage's documents go
    through meant a truncated marker could be left where a whole one had been.
    The bytes are identical either way.
    """
    redacted = redact_absolute_paths(payload)
    leaks = find_absolute_paths(redacted, path=Path(path).name)
    if leaks:
        location, text = leaks[0]
        raise ValueError(
            f"{Path(path).name} still names an absolute path after redaction: "
            f"{location} = {text!r}. Evidence carries no machine's layout"
        )
    body = json.dumps(redacted, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    replace_bytes(Path(path), body.encode("utf-8"), what="evidence document")
    return Path(path)
