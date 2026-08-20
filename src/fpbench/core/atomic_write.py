"""Publishing a file so that a second writer can never silently replace the first.

Every store in this repository writes the same three lines: check the target
does not exist, write a *fixed* sibling ``.tmp``, then ``replace()`` it into
place. That sequence is atomic against a crash and wide open against a
concurrent writer. Two workers reaching the same job pass the existence check
together, write over each other's temp file, and both call ``replace()``. The
last one wins, and — this is the part that makes it a correctness bug rather
than an inefficiency — the *first* one returns success. A caller is told its
result was stored while the bytes on disk belong to somebody else.

This module is the one primitive both halves of the fix live in.

**A unique temp per writer.** ``unique_temp_path`` names the scratch file after
the process and a fresh UUID, so no two writers can collide on it even when
they target the same final path.

**Create-if-absent publication.** ``publish_*`` reserves the final name with an
operation the filesystem itself serialises — ``os.link``, falling back to
``O_CREAT | O_EXCL`` where hard links are unavailable — so exactly one writer
can succeed. The loser is *told* it lost: it re-reads the winner's bytes and
compares digests, reporting :attr:`PublishOutcome.ALREADY_IDENTICAL` when the
two agree and raising :class:`PublishConflictError` when they do not. A losing
writer never reports success it did not have.

``replace_*`` remains available for documents that are *meant* to be
regenerated — evidence markers, reports, indexes — and differs from the old
code only in using a unique temp. Immutable artefacts must use ``publish_*``.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import shutil
import threading
from enum import Enum
from pathlib import Path
from typing import Callable

__all__ = [
    "PublishConflictError",
    "PublishOutcome",
    "PublishedFile",
    "unique_temp_path",
    "publish_bytes",
    "publish_file",
    "publish_text",
    "replace_bytes",
    "replace_file",
    "replace_text",
    "sha256_file",
]

#: How much of a file is read at a time when digesting it.
_CHUNK = 1 << 20

#: Eight characters that identify this process among any others writing into the
#: same directory: the low half of the pid, plus two random bytes so that two
#: processes which happen to share it after a pid wrap still differ.
_PROCESS_TOKEN = f"{os.getpid() & 0xFFFF:04x}{secrets.token_hex(2)}"

#: Distinguishes concurrent writers *within* this process. A lock rather than
#: ``itertools.count`` so the wrap-around stays a single atomic step.
_COUNTER_LOCK = threading.Lock()
_COUNTER = 0


class PublishConflictError(OSError):
    """Another writer published *different* bytes at this path first.

    Deliberately not a subclass of any storage error: ``core`` owns no storage
    vocabulary. Storage layers catch it and re-raise their own conflict type.
    """


class PublishOutcome(str, Enum):
    """Which side of the race this writer was on."""

    #: This writer created the file. The bytes on disk are its own.
    PUBLISHED = "published"
    #: Another writer got there first, and stored byte-identical content.
    ALREADY_IDENTICAL = "already_identical"


class PublishedFile:
    """The result of one publication: where it went, who won, and the digest."""

    __slots__ = ("path", "outcome", "sha256")

    def __init__(self, path: Path, outcome: PublishOutcome, sha256: str) -> None:
        self.path = path
        self.outcome = outcome
        self.sha256 = sha256

    @property
    def created(self) -> bool:
        """True when this writer is the one whose bytes are on disk."""
        return self.outcome is PublishOutcome.PUBLISHED

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"PublishedFile(path={self.path!s}, outcome={self.outcome.value}, "
            f"sha256={self.sha256[:12]}...)"
        )


def sha256_file(path: Path) -> str:
    """Digest a file without reading all of it into memory."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def unique_temp_path(path: Path) -> Path:
    """A sibling scratch name no concurrent writer can also choose.

    A sibling rather than a temp directory so the publication below is a
    same-filesystem operation: ``os.link`` and ``os.replace`` both refuse to
    cross devices.

    The name is short and deliberately *not* derived from the target's. Windows
    still enforces a 260-character path limit for these APIs, and appending a
    uniqueness token to an already-deep name is how a scratch file ends up
    unopenable in exactly the nested workspace layouts this repository uses.
    The name is always 17 characters, whatever it is a temp for — the same
    length as ``manifest.json.tmp``, and shorter than the ``<name>.tmp`` this
    replaces for every parquet body in the workspace.
    """
    with _COUNTER_LOCK:
        global _COUNTER
        _COUNTER = (_COUNTER + 1) & 0xFFFF
        ordinal = _COUNTER
    return Path(path).with_name(f".{_PROCESS_TOKEN}{ordinal:04x}.tmp")


def _fsync_dir(directory: Path) -> None:
    """Flush a directory entry, where the platform has such a thing."""
    if os.name == "nt":  # Windows has no directory file descriptor to sync.
        return
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:  # pragma: no cover - unusual filesystems
        return
    try:
        os.fsync(fd)
    except OSError:  # pragma: no cover - unusual filesystems
        pass
    finally:
        os.close(fd)


def _reserve(source: Path, target: Path) -> bool:
    """Create ``target`` from ``source``, only if ``target`` does not exist.

    Returns True when this call created it. ``os.link`` is the primitive of
    choice: the kernel resolves the race, and the winner's inode is already
    complete, so no reader ever sees a partial file. Where hard links are
    unavailable — FAT/exFAT, some network mounts — an ``O_EXCL`` create still
    lets exactly one writer claim the name.
    """
    try:
        os.link(source, target)
        return True
    except FileExistsError:
        return False
    except (OSError, AttributeError, NotImplementedError):
        pass

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_BINARY", 0)
    try:
        handle = os.open(target, flags, 0o644)
    except FileExistsError:
        return False
    with os.fdopen(handle, "wb") as writer, Path(source).open("rb") as reader:
        shutil.copyfileobj(reader, writer)
        writer.flush()
        os.fsync(writer.fileno())
    return True


def publish_file(
    path: Path,
    producer: Callable[[Path], None],
    *,
    what: str = "file",
) -> PublishedFile:
    """Create ``path`` exactly once, from content ``producer`` writes to a temp.

    ``producer`` is handed a unique scratch path and must leave the finished
    content there; it is never handed the final path, so a half-written artefact
    cannot appear under the name other processes read.

    Raises:
        PublishConflictError: another writer published different bytes first.
            Never resolved by overwriting — two writers disagreeing about one
            immutable artefact is a fact worth stopping for (docs/adr/0009).
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = unique_temp_path(target)
    try:
        producer(temporary)
        if not temporary.exists():
            raise OSError(f"the producer for {what} wrote no file at {temporary}")
        mine = sha256_file(temporary)
        if _reserve(temporary, target):
            _fsync_dir(target.parent)
            return PublishedFile(target, PublishOutcome.PUBLISHED, mine)
        theirs = sha256_file(target)
        if theirs == mine:
            return PublishedFile(target, PublishOutcome.ALREADY_IDENTICAL, theirs)
        raise PublishConflictError(
            f"{target} already holds a different {what}: this writer produced "
            f"{mine[:12]}... and the file on disk is {theirs[:12]}.... The first "
            "writer to reach the name keeps it; a second one is never resolved by "
            "overwriting (docs/adr/0009)"
        )
    finally:
        temporary.unlink(missing_ok=True)


def publish_bytes(path: Path, payload: bytes, *, what: str = "file") -> PublishedFile:
    """Publish ``payload`` under ``path``, create-if-absent. See :func:`publish_file`."""
    content = bytes(payload)

    def _write(temporary: Path) -> None:
        with temporary.open("wb") as writer:
            writer.write(content)
            writer.flush()
            os.fsync(writer.fileno())

    return publish_file(path, _write, what=what)


def publish_text(
    path: Path, text: str, *, encoding: str = "utf-8", what: str = "file"
) -> PublishedFile:
    """Publish text under ``path``, create-if-absent.

    ``newline=""`` in effect: the string is encoded as given, so a caller that
    wrote ``\\n`` gets ``\\n`` on every platform. Content-addressed stores depend
    on that — see ``CalibrationStore``.
    """
    return publish_bytes(path, text.encode(encoding), what=what)


def replace_file(
    path: Path, producer: Callable[[Path], None], *, what: str = "file"
) -> Path:
    """Write ``path`` atomically, replacing any existing file.

    For documents that are *meant* to be regenerated. The unique temp is the
    whole difference from the old idiom: two regenerations running at once can
    no longer corrupt each other's scratch file, so whichever finishes last
    installs a *complete* document rather than a mixture of both.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = unique_temp_path(target)
    try:
        producer(temporary)
        if not temporary.exists():
            raise OSError(f"the producer for {what} wrote no file at {temporary}")
        os.replace(temporary, target)
        _fsync_dir(target.parent)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def replace_bytes(path: Path, payload: bytes, *, what: str = "file") -> Path:
    """Replace ``path`` with ``payload``, atomically. See :func:`replace_file`."""
    content = bytes(payload)

    def _write(temporary: Path) -> None:
        with temporary.open("wb") as writer:
            writer.write(content)
            writer.flush()
            os.fsync(writer.fileno())

    return replace_file(path, _write, what=what)


def replace_text(
    path: Path, text: str, *, encoding: str = "utf-8", what: str = "file"
) -> Path:
    """Replace ``path`` with ``text``, atomically. See :func:`replace_file`."""
    return replace_bytes(path, text.encode(encoding), what=what)
