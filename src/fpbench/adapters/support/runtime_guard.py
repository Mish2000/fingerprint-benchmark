"""The cheap check that the executables under an adapter have not been swapped.

A full SHA-256 of a 27 MB shaded jar takes long enough that doing it before each
of 6,000 comparisons would add real time to a run for no new information — the
expensive check already runs before the executor starts and again after it stops.
What is needed in between is something that costs one ``stat`` per file and still
notices a replacement.

That is what a file identity is: device, inode (or the Windows file index), size
and modification time in nanoseconds. Replacing a file — by rebuild, by copy, by
``mv`` — changes at least one of them on every filesystem this project runs on.
Writing *into* the same inode without changing its size or mtime is the one case
this would miss, and the post-run full digest is what covers it.

A mismatch is never a comparison failure. It means the results already written
were produced by something that is no longer there, which is a fact about the
whole run rather than about one pair (docs/adr/0018).

**Every asset, not the main one.** A two-tool pipeline can be broken by either
tool: NBIS with a rebuilt Bozorth3 and an untouched MINDTCT produces different
scores from the run that was pinned, and a guard that only watched the "primary"
executable would not notice. So the plural form takes the whole role-to-path
mapping and checks all of it, and a bundle that acquired or lost a role since
preflight is drift too (docs/adr/0042).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from fpbench.core.errors import RuntimeDriftError

__all__ = [
    "FileIdentity",
    "snapshot_file_identity",
    "require_unchanged",
    "snapshot_runtime_assets",
    "require_runtime_assets_unchanged",
]


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


def snapshot_runtime_assets(
    assets: Mapping[str, Path],
) -> Mapping[str, FileIdentity]:
    """Snapshot every runtime asset of an adapter, keyed by role.

    Raises:
        RuntimeDriftError: any asset is missing or is not a regular file.
        ValueError: the mapping is empty. An adapter with no runtime assets has
            nothing to guard and should not be asking.
    """
    from types import MappingProxyType

    if not assets:
        raise ValueError("a runtime guard needs at least one asset to watch")
    return MappingProxyType(
        {
            str(role): snapshot_file_identity(Path(path))
            for role, path in sorted(dict(assets).items())
        }
    )


def require_runtime_assets_unchanged(
    assets: Mapping[str, Path],
    expected: Mapping[str, FileIdentity],
    *,
    label: str = "runtime asset",
) -> None:
    """Confirm every pinned asset is still the file preflight approved.

    The role set is compared before the files are: an adapter that suddenly has
    a role it did not have at preflight, or has lost one, is running against a
    different runtime whatever the surviving files say.

    Raises:
        RuntimeDriftError: a role appeared, a role vanished, or a file changed.
    """
    current_roles = set(assets)
    expected_roles = set(expected)
    if current_roles != expected_roles:
        appeared = sorted(current_roles - expected_roles)
        vanished = sorted(expected_roles - current_roles)
        raise RuntimeDriftError(
            "the pinned runtime no longer holds the roles it was validated with: "
            f"appeared={appeared} vanished={vanished}. No further comparison may "
            "be attributed to this run (docs/adr/0018, docs/adr/0042)"
        )
    for role, path in sorted(dict(assets).items()):
        require_unchanged(Path(path), expected[role], label=f"{label} {role!r}")


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
