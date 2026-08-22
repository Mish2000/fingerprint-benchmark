"""Publishing a set that is more than one file.

``publish_*`` makes one file appear atomically. A *set* — a manifest plus the
parquet body it describes — is two, and atomicity per file is not atomicity for
the pair. The stores all wrote them in the same order:

.. code-block:: text

    if the manifest exists: compare fingerprints and return
    write entries.parquet          <- replace, so it clobbers
    publish manifest.json          <- create-if-absent, so it refuses

Two writers with different content both pass the guard, both replace the
entries, and then one publishes the manifest and the other is refused. The set
left on disk is one writer's manifest over the other writer's rows — and the
manifest's own fingerprint says nothing is wrong, because it describes rows that
are no longer there.

**The manifest is the claim.** It is published *first*, create-if-absent, so the
filesystem decides who owns the set; only the owner writes the body, and a
second writer never touches the body at all.

That inverts the old crash story, so the new one is handled explicitly. A crash
between the manifest and the body leaves a set whose manifest is present and
whose rows are missing. :func:`publish_set` detects exactly that — same
fingerprint, any required file absent — and lets the caller finish the
publication it started. A *different* fingerprint is still a conflict and is
still never resolved by overwriting (docs/adr/0009).

**Every** body file counts, not a representative one. A metric set is six files;
naming only ``counts.parquet`` meant a crash between it and
``observations.parquet`` produced a set whose retry reported success over rows
that were never written.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from fpbench.core.atomic_write import PublishConflictError
from fpbench.core.json_io import publish_json

__all__ = ["SetClaim", "publish_set"]


@dataclass(frozen=True, slots=True)
class SetClaim:
    """Who owns this set, and whether its body still has to be written."""

    #: This caller published the manifest and owns the set.
    owned: bool
    #: The body must be written: either because this caller owns the set, or
    #: because the owner did not finish and left the same manifest behind.
    write_body: bool
    #: A manifest was already there when this caller arrived.
    already_published: bool


def publish_set(
    *,
    manifest_path: Path,
    manifest: object,
    body_paths: Sequence[Path],
    stored_fingerprint: Callable[[], str],
    fingerprint: str,
) -> SetClaim:
    """Claim a multi-file set by publishing its manifest first.

    Args:
        manifest_path: The document that says the set exists.
        manifest: What to publish there.
        body_paths: **Every** file the manifest describes. Only their
            *existence* is read here; writing them is the caller's job, and only
            when :attr:`SetClaim.write_body` says so. All of them, because one
            was standing in for the rest: a metric set is six files, and a crash
            between ``counts.parquet`` and ``observations.parquet`` left a set
            the retry declared finished.
        stored_fingerprint: Reads the fingerprint out of whatever manifest is
            already on disk. A callable rather than a value because it must not
            be paid for on the common path, where nothing is there.
        fingerprint: This caller's identity for the set.

    Raises:
        Exception: whatever ``stored_fingerprint`` raises if the stored manifest
            is unreadable. A conflict is the caller's to raise, from the
            comparison this returns.
    """
    if Path(manifest_path).is_file():
        # Already published. There is nothing to claim, and the manifest is not
        # rendered at all — the stored one decides, and a caller holding an
        # unserialisable object still gets the comparison rather than an
        # encoder error.
        claimed = False
    else:
        try:
            published = publish_json(manifest_path, manifest)
            claimed = published.created
        except PublishConflictError:
            # Byte-different under one name. Whether that is a conflict depends
            # on the fingerprint, which the caller compares.
            claimed = False

    if claimed:
        return SetClaim(owned=True, write_body=True, already_published=False)

    # Somebody else's manifest. If it is *this* set and its body never arrived,
    # the previous publication stopped half way and can be finished; the rows
    # are determined by the fingerprint, so writing them is not a guess.
    same_set = stored_fingerprint() == fingerprint
    incomplete = any(not Path(path).is_file() for path in body_paths)
    return SetClaim(
        owned=False,
        write_body=same_set and incomplete,
        already_published=True,
    )
