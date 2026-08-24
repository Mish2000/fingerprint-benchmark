"""Publishing a set that is more than one file.

``publish_*`` makes one file appear atomically. A *set* — a manifest plus the
body it describes — is several, and atomicity per file is not atomicity for the
set. The stores all wrote them in the same order:

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
filesystem decides who owns the set.

**And a claim is not the guarantee.** Claiming first stops two writers from
interleaving; it says nothing about what is on the disk when this call returns.
The first version of this module returned a ``write_body`` flag and left the
rest to each caller, which meant every caller had two branches to get right and
the second one was invisible. Three separate defects came out of that single
shape: a body that was never checked, a body checked against a value the caller
supplied, and — twice — a body checked on the branch that writes it and not on
the branch that finds it already there.

So the flag is gone, and with it the branch. The contract of this module is now
one sentence:

    A public publish returns successfully only if, at a linearization point
    before it returns, the set on disk is the set the caller asked to publish.

Which is stronger than "I did not corrupt anything", and is the difference
between the two that kept being lost. Concretely, on **every** outcome — a fresh
publication, a retry over a finished set, a resumed one, a race lost:

* the stored manifest carries this caller's fingerprint, or this is a conflict;
* every body file exists;
* every body equals what the caller passed, by the store's own comparator —
  not necessarily byte-for-byte, because a Parquet body carries a wall clock;
* the whole set is re-read and re-checked before returning.

A partial set with the same fingerprint may be *finished*, and finishing it is
not repairing it: what is already there is verified first, only what is missing
is created, and a body that disagrees is a conflict that no amount of retrying
turns into a repair. Nothing already on disk is ever overwritten under the guise
of recovery (docs/adr/0009, docs/adr/0139).

**What this does not promise.** Nothing here defends against another process
editing a file *after* the verification point and before the caller acts on the
result. That would need a lock held across the whole operation, which this
repository does not take; the guarantee is at the linearization point, and it is
stated that way rather than implied to be broader.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

import pyarrow as pa
import pyarrow.parquet as pq

from fpbench.core.atomic_write import PublishConflictError
from fpbench.core.json_io import publish_json
from fpbench.core.serialization import read_json, to_plain
from fpbench.storage.atomic_parquet import publish_table

__all__ = [
    "SetBody",
    "SetPublication",
    "canonical_document",
    "canonical_table",
    "document_body",
    "publish_set",
    "table_body",
]


@dataclass(frozen=True, slots=True)
class SetBody:
    """One file the manifest describes, and how this store handles it.

    The two callables are what keeps the rule in one place while the formats
    stay in eight. :func:`publish_set` decides *when* a body is verified and
    when it may be created; only the store knows what its bytes mean.
    """

    #: Where the file lives.
    path: Path

    #: Raise if what is stored at :attr:`path` is not what the caller passed.
    #:
    #: Compares against the caller's **in-memory input**, not against the
    #: manifest's description of it. A body checked only against the manifest is
    #: checked against a document that a wrong body can still satisfy.
    #: Unreadable counts as disagreeing: it is a conflict, never a reason to
    #: rewrite.
    verify_existing: Callable[[], None]

    #: Create the file, create-if-absent, when it is missing.
    #:
    #: Must not raise when another writer created it first — two publishers of
    #: the *same* set are both entitled to succeed, and which of them won a
    #: given file is not interesting. The verification that follows decides.
    publish_missing: Callable[[], None]


@dataclass(frozen=True, slots=True)
class SetPublication:
    """What happened. Nothing here gates anything: the checks already ran."""

    #: This caller published the manifest and owns the set.
    created: bool
    #: A manifest was already there when this caller arrived.
    already_published: bool
    #: Bodies this call created, in the order they were declared. Empty means
    #: the set was already whole — which is a successful publication too.
    completed: tuple[Path, ...]


#: Metadata a body carries that says when it was written, not what it holds.
#:
#: A Parquet body is stamped with a wall clock at one-second resolution and the
#: package version. Two writers of the same rows produce files that differ in
#: those bytes and in nothing else, so "the stored body is the expected body" is
#: a question about the rows and the identity stamped beside them — never about
#: the whole file. Comparing bytes here would turn every legitimate retry into a
#: conflict.
_WHEN_NOT_WHAT = frozenset({b"created_utc", b"fpbench_version"})

#: The same distinction for a JSON body, where it is not a stamp but a field.
#:
#: A transform runtime carries ``created_utc`` and its ``runtime_fingerprint``
#: deliberately excludes it — deriving the same set twice produces documents that
#: differ in that field and in nothing else, and the set's identity says they are
#: the same runtime. So the comparison here is over what the fingerprint covers.
#: Only the top level is stripped: a nested wall clock is left to fail loudly
#: rather than be waved through by a rule nobody declared.
_WHEN_NOT_WHAT_DOCUMENT = frozenset({"created_utc", "generated_utc"})


def canonical_document(document: object) -> object:
    """A JSON body reduced to what it means rather than when it was made."""
    plain = to_plain(document)
    if not isinstance(plain, dict):
        return plain
    return {
        key: value
        for key, value in plain.items()
        if key not in _WHEN_NOT_WHAT_DOCUMENT
    }


def canonical_table(table: pa.Table) -> pa.Table:
    """A Parquet body reduced to what it means rather than when it was made."""
    metadata = {
        key: value
        for key, value in (table.schema.metadata or {}).items()
        if key not in _WHEN_NOT_WHAT
    }
    return table.combine_chunks().replace_schema_metadata(metadata)


def _read_table(path: Path, what: str, error: Callable[[str], BaseException]) -> pa.Table:
    try:
        with pq.ParquetFile(path) as reader:
            return reader.read()
    except (pa.ArrowInvalid, OSError) as exc:
        # Unreadable is a disagreement, not an invitation to rewrite.
        raise error(f"{path}: the stored {what} cannot be read ({exc})") from exc


def table_body(
    *,
    path: Path,
    expected: Callable[[], pa.Table],
    what: str,
    error: Callable[[str], BaseException],
) -> SetBody:
    """A Parquet file the manifest describes.

    One ``expected`` serves both halves: it is what gets written when the file
    is missing and what the stored file is compared against when it is not.
    Taking a separate writer would let a store verify one thing and publish
    another, which is the shape this module exists to remove.

    ``expected`` is a callable because building a table costs something and a
    fresh publication should pay for it once.
    """
    path = Path(path)

    def verify_existing() -> None:
        if not path.is_file():
            raise error(f"{what} not found: {path}")
        stored = _read_table(path, what, error)
        if not canonical_table(stored).equals(canonical_table(expected())):
            raise error(
                f"{path} holds a different {what} than the set being published; "
                "refusing to replace it"
            )

    def publish_missing() -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            publish_table(path, expected(), what=what)
        except PublishConflictError:
            # Another publisher of this same set got there first. Both are
            # entitled to succeed; the verification that follows decides.
            return

    return SetBody(
        path=path, verify_existing=verify_existing, publish_missing=publish_missing
    )


def document_body(
    *,
    path: Path,
    expected: object,
    what: str,
    error: Callable[[str], BaseException],
) -> SetBody:
    """A JSON file the manifest describes. Same rule as :func:`table_body`."""
    path = Path(path)

    def verify_existing() -> None:
        if not path.is_file():
            raise error(f"{what} not found: {path}")
        try:
            stored = read_json(path)
        except (OSError, ValueError) as exc:
            raise error(f"{path}: the stored {what} cannot be read ({exc})") from exc
        if canonical_document(stored) != canonical_document(expected):
            raise error(
                f"{path} holds a different {what} than the set being published; "
                "refusing to replace it"
            )

    def publish_missing() -> None:
        try:
            publish_json(path, expected)
        except PublishConflictError:
            return

    return SetBody(
        path=path, verify_existing=verify_existing, publish_missing=publish_missing
    )


def publish_set(
    *,
    manifest_path: Path,
    manifest: object,
    fingerprint: str,
    stored_fingerprint: Callable[[], str],
    bodies: Sequence[SetBody],
    verify_whole_set: Callable[[], None],
    conflict: Callable[[str], BaseException],
) -> SetPublication:
    """Publish a set, and return only once the disk holds it.

    The caller is expected to have checked its own inputs against its own
    manifest before calling: a claim cannot be given back, so a mis-derived set
    must be refused before it takes a name it could then only ever be refused
    under.

    Args:
        manifest_path: The document that says the set exists.
        manifest: What to publish there.
        fingerprint: This caller's identity for the set.
        stored_fingerprint: Reads the fingerprint out of whatever manifest is
            already on disk. A callable rather than a value because it must not
            be paid for on the common path, where nothing is there — and because
            an unreadable manifest should raise here, before any body is
            touched.
        bodies: **Every** file the manifest describes. All of them, because one
            was standing in for the rest: a metric set is six files, and a crash
            between two of them left a set the retry declared finished.
        verify_whole_set: Re-reads the published set and re-checks it as a
            whole. Runs on every outcome, after the per-body checks, because the
            two answer different questions — the bodies are compared against
            what the caller holds, the set against what it claims about itself.
        conflict: Builds this store's own conflict error, given the fingerprint
            found on disk. Raised from here rather than returned, so there is no
            branch a caller can decline to write.

    Returns:
        What happened, for reporting. Not a permission to skip anything.

    Raises:
        BaseException: ``conflict(...)`` when the name belongs to another set;
            whatever ``verify_existing`` raises when a stored body disagrees;
            whatever ``stored_fingerprint`` raises when the manifest is
            unreadable.
    """
    bodies = tuple(bodies)
    manifest_path = Path(manifest_path)

    # 1. Bodies without a manifest. Under manifest-first this cannot be a crash
    #    of ours, so it is either data from before that rule or somebody else's
    #    files under our name. Either way it is decided *before* claiming: if
    #    they are already what we would write, the name is ours to complete; if
    #    they are not, we must not claim a set we would then be refused.
    if not manifest_path.is_file():
        for body in bodies:
            if Path(body.path).is_file():
                body.verify_existing()

    # 2. The claim.
    claimed = False
    if not manifest_path.is_file():
        try:
            claimed = publish_json(manifest_path, manifest).created
        except PublishConflictError:
            # Byte-different under one name. Whether that is a conflict is the
            # fingerprint's answer, below, not this exception's.
            claimed = False

    # 3. Somebody else's manifest is a conflict unless it is this same set —
    #    and that is settled before a single body is read or written.
    if not claimed:
        stored = stored_fingerprint()
        if stored != fingerprint:
            raise conflict(stored)

    # 4. Everything already there must be what we hold. Before anything is
    #    created, so that "one body missing and another different" is a conflict
    #    rather than a repair that completes a set nobody should trust.
    present = [body for body in bodies if Path(body.path).is_file()]
    for body in present:
        body.verify_existing()

    # 5. Only what is missing.
    completed: list[Path] = []
    for body in bodies:
        if not Path(body.path).is_file():
            body.publish_missing()
            completed.append(Path(body.path))

    # 6. Read it all back — including whatever step 5 wrote, and whatever
    #    another publisher of this same set wrote while we were doing it. A file
    #    that is still absent raises from the store's own reader, which is the
    #    layer that knows what to call it.
    for body in bodies:
        body.verify_existing()

    # 7. And the set as a whole, which is a different question from each of its
    #    files being right.
    verify_whole_set()

    return SetPublication(
        created=claimed,
        already_published=not claimed,
        completed=tuple(completed),
    )
