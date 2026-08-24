"""Claiming a document that may be written once and never replaced.

Thirty ``ensure_*`` methods across the storage layer were written the same way,
because each was copied from the last::

    if path.is_file():
        stored = read(path)
        if stored.fingerprint != mine.fingerprint:
            raise Conflict(...)
        return path
    return write_json(path, mine)          # <- replaces

The guard is right and the write is not. Two publishers that both find the path
absent both pass the guard and both write, and ``write_json`` replaces — so the
second silently overwrites the first and the stored document is whichever one
happened to finish last. Nothing raises, because the only comparison happens on
the path that was not taken.

:func:`claim_document` inverts it. The filesystem decides who owns the name; a
caller that loses re-reads and applies the same comparison it always did, which
is why the transformation is a restructure rather than a rewrite:

    if not claim_document(path, mine):
        stored = read(path)
        if stored.fingerprint != mine.fingerprint:
            raise Conflict(...)
    return path

**What this is not.** It is not a lock and it does not serialise anything. It
answers exactly one question — did *this* caller create the file — and leaves
the meaning of a lost claim to the caller, because "is that the same document"
is a question about the document and not about storage.

For a set that is more than one file, the claim is the *manifest* and the rule
is in :mod:`fpbench.storage.set_publication`. Publishing several files one
claim at a time would leave a half-written set with no owner.
"""

from __future__ import annotations

from pathlib import Path

from fpbench.core.atomic_write import PublishConflictError, publish_text
from fpbench.core.json_io import publish_json

__all__ = ["claim_document", "claim_text"]


def claim_document(path: Path, payload: object) -> bool:
    """Publish ``payload`` at ``path`` exactly once.

    Args:
        path: The name being claimed.
        payload: What to store there, rendered by the shared JSON writer so the
            bytes are identical to what ``write_json`` would have produced.

    Returns:
        ``True`` when this caller created the file. ``False`` means somebody
        else's bytes are already there — identical or not, which is the
        caller's comparison to make and never an error on its own.
    """
    try:
        return publish_json(Path(path), payload).created
    except PublishConflictError:
        # Byte-different under this name. Whether that is a conflict depends on
        # the fingerprint, and the caller is the only one that can read it.
        return False


def claim_text(path: Path, text: str) -> bool:
    """Publish ``text`` at ``path`` exactly once.

    The same rule as :func:`claim_document` for a document that is not JSON —
    the generated Markdown reports. Those were the last two ``ensure_*`` methods
    still checking ``is_file()`` and then reaching a replacing writer, and they
    are not disposable: both compare a ``report_content_hash`` and raise on
    disagreement, which is a statement that the report belongs to the set.

    Returns:
        ``True`` when this caller created the file. ``False`` means somebody
        else's bytes are already there — and whether they are *the same report*
        is the caller's comparison, because the hash it compares on normalises
        what a byte comparison would not.
    """
    try:
        return publish_text(Path(path), text, what="report").created
    except PublishConflictError:
        return False
