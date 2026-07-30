"""The cheap check that the jar under the adapter has not been swapped.

A full SHA-256 of a 27 MB shaded jar takes long enough that doing it before
each of 6,000 comparisons would add real time to a run for no new information —
the expensive check already runs before the executor starts and again after it
stops. What is needed in between is something that costs one ``stat`` and still
notices a replacement.

That is what a file identity is: device, inode (or the Windows file index),
size and modification time in nanoseconds. Replacing a file — by rebuild, by
copy, by ``mv`` — changes at least one of them on every filesystem this project
runs on. Writing *into* the same inode without changing its size or mtime is
the one case this would miss, and the post-run full digest is what covers it.

A mismatch is never a comparison failure. It means the results already written
were produced by something that is no longer there, which is a fact about the
whole run rather than about one pair (docs/adr/0018).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fpbench.core.errors import RuntimeDriftError

__all__ = ["FileIdentity", "snapshot_file_identity", "require_unchanged"]


@dataclass(frozen=True, slots=True)
class FileIdentity:
    """Everything ``stat`` knows that changes when a file is replaced.

    ``device`` and ``inode`` are zero on filesystems that do not report them.
    They are compared anyway: two zeroes compare equal and simply contribute
    nothing, which is the correct behaviour for a check that must never produce
    a false alarm.
    """

    device: int
    inode: int
    size_bytes: int
    mtime_ns: int

    @classmethod
    def of(cls, path: Path) -> "FileIdentity":
        status = Path(path).stat()
        return cls(
            device=int(getattr(status, "st_dev", 0) or 0),
            inode=int(getattr(status, "st_ino", 0) or 0),
            size_bytes=int(status.st_size),
            mtime_ns=int(status.st_mtime_ns),
        )

    def describe(self) -> str:
        """A short rendering for an error message. Carries no path."""
        return (
            f"size={self.size_bytes} mtime_ns={self.mtime_ns} "
            f"inode={self.inode} device={self.device}"
        )


def snapshot_file_identity(path: Path) -> FileIdentity:
    """Record what the file is now, so a later call can tell if it changed.

    Raises:
        RuntimeDriftError: the file is missing, or is not a regular file.
    """
    return _require_regular_file(Path(path))


def require_unchanged(path: Path, expected: FileIdentity, *, label: str) -> None:
    """Confirm ``path`` is still the file ``expected`` was taken from.

    Raises:
        RuntimeDriftError: it is not.
    """
    current = _require_regular_file(Path(path))
    if current != expected:
        raise RuntimeDriftError(
            f"the pinned {label} changed while the run was using it: "
            f"expected {expected.describe()}, found {current.describe()}. "
            "No further comparison may be attributed to this run "
            "(docs/adr/0018)"
        )


def _require_regular_file(path: Path) -> FileIdentity:
    if path.is_symlink():
        raise RuntimeDriftError(
            f"the pinned runtime asset {path.name} is now a symlink; a bundle "
            "owns its bytes and must not point at someone else's"
        )
    if not path.exists():
        raise RuntimeDriftError(
            f"the pinned runtime asset {path.name} is no longer present"
        )
    if not path.is_file():
        raise RuntimeDriftError(
            f"the pinned runtime asset {path.name} is no longer a regular file"
        )
    return FileIdentity.of(path)
