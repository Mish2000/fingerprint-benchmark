"""Read the runtime lock, and check it against what is actually importable.

Stage 8A's finding was ``DEPENDENCY_VERSIONS_NOT_LOCKED``.  A lock answers it
only if something checks it, so this module does two separate jobs: it parses
the pinned file, and it compares those pins to the distributions a live
interpreter reports.  Neither job trusts the other.

Nothing here imports torch.  The observations come from the worker as plain
data; the parent only judges them.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from fpbench.core.flx_errors import FlxRuntimeLockError
from fpbench.core.flx_models import STAGE8B_SCHEMA_VERSION, FlxDependencyPin

__all__ = [
    "LockedDistribution",
    "RuntimeLock",
    "load_runtime_lock",
    "file_sha256",
]

_FILENAME = re.compile(r"^#\s(?P<filename>[A-Za-z0-9_.+-]+\.whl)$")
_SIZE = re.compile(r"^#\s+size:\s(?P<size>\d+)$")
_INDEX = re.compile(r"^#\s+index:\s(?P<index>\S+)$")
_REQUIREMENT = re.compile(r"^(?P<name>[A-Za-z0-9_.-]+)==(?P<version>[A-Za-z0-9_.+!-]+)\s*\\$")
_HASH = re.compile(r"^\s+--hash=sha256:(?P<digest>[0-9a-f]{64})$")
_OPTION = re.compile(r"^--[a-z-]+(?:[=\s]\S+)?$")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as stream:
            for block in iter(lambda: stream.read(1 << 20), b""):
                digest.update(block)
    except OSError as exc:
        raise FlxRuntimeLockError(f"cannot hash {path}: {exc}") from exc
    return digest.hexdigest()


def _canonical(name: str) -> str:
    """PEP 503 normalization, so ``typing_extensions`` and ``typing-extensions`` agree."""
    return re.sub(r"[-_.]+", "-", name).lower()


@dataclass(frozen=True, slots=True)
class LockedDistribution:
    name: str
    version: str
    filename: str
    sha256: str
    size_bytes: int
    index: str

    @property
    def canonical_name(self) -> str:
        return _canonical(self.name)

    def as_pin(self) -> FlxDependencyPin:
        return FlxDependencyPin.create(
            schema_version=STAGE8B_SCHEMA_VERSION,
            name=self.name,
            version=self.version,
            artifact_filename=self.filename,
            artifact_sha256=self.sha256,
            source_index=self.index,
        )


@dataclass(frozen=True, slots=True)
class RuntimeLock:
    path: Path
    sha256: str
    distributions: tuple[LockedDistribution, ...]

    @property
    def by_name(self) -> Mapping[str, LockedDistribution]:
        return {item.canonical_name: item for item in self.distributions}

    def pins(self) -> tuple[FlxDependencyPin, ...]:
        return tuple(
            item.as_pin() for item in sorted(self.distributions, key=lambda d: d.canonical_name)
        )

    def require_version(self, name: str) -> str:
        try:
            return self.by_name[_canonical(name)].version
        except KeyError:
            raise FlxRuntimeLockError(f"{name} is not pinned by {self.path.name}") from None

    def verify_installed(self, observed: Mapping[str, str]) -> None:
        """Compare the lock against what a live interpreter actually imported.

        Both directions matter.  A missing distribution means the worker could
        not be running what we pinned; an extra one means something entered the
        runtime that the lock never named, which is exactly how an unpinned
        dependency hides.
        """
        expected = {name: item.version for name, item in self.by_name.items()}
        actual = {_canonical(name): str(version) for name, version in observed.items()}
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        if missing or extra:
            raise FlxRuntimeLockError(
                "the installed runtime is not the locked one; "
                f"missing={missing}, unpinned={extra}"
            )
        drifted = sorted(
            f"{name} locked {expected[name]} but installed {actual[name]}"
            for name in expected
            if expected[name] != actual[name]
        )
        if drifted:
            raise FlxRuntimeLockError(f"pinned dependency drift: {drifted}")


def _parse(lines: Iterable[str], path: Path) -> tuple[LockedDistribution, ...]:
    distributions: list[LockedDistribution] = []
    filename: str | None = None
    size: int | None = None
    index: str | None = None
    pending: tuple[str, str] | None = None

    for number, raw in enumerate(lines, start=1):
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        if pending is not None:
            match = _HASH.match(line)
            if match is None:
                raise FlxRuntimeLockError(
                    f"{path}:{number}: a pinned requirement must be followed by its --hash"
                )
            name, version = pending
            assert filename is not None and size is not None and index is not None
            distributions.append(
                LockedDistribution(
                    name=name,
                    version=version,
                    filename=filename,
                    sha256=match.group("digest"),
                    size_bytes=size,
                    index=index,
                )
            )
            pending = filename = size = index = None
            continue
        if match := _FILENAME.match(line):
            filename, size, index = match.group("filename"), None, None
            continue
        if match := _SIZE.match(line):
            size = int(match.group("size"))
            continue
        if match := _INDEX.match(line):
            index = match.group("index")
            continue
        if line.startswith("#"):
            continue
        if _OPTION.match(line):
            continue
        if match := _REQUIREMENT.match(line):
            if filename is None or size is None or index is None:
                raise FlxRuntimeLockError(
                    f"{path}:{number}: a pin must be preceded by its wheel filename, "
                    "size and index; a version without the bytes it names is not a lock"
                )
            pending = (match.group("name"), match.group("version"))
            continue
        raise FlxRuntimeLockError(f"{path}:{number}: unparsable lock line {line!r}")

    if pending is not None:
        raise FlxRuntimeLockError(f"{path}: the file ends before the last --hash")
    return tuple(distributions)


def load_runtime_lock(path: Path) -> RuntimeLock:
    path = Path(path)
    if not path.is_file():
        raise FlxRuntimeLockError(f"runtime lock not found: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise FlxRuntimeLockError(f"{path}: unreadable runtime lock ({exc})") from exc
    distributions = _parse(text.splitlines(), path)
    if not distributions:
        raise FlxRuntimeLockError(f"{path}: a lock with no pinned distributions is not a lock")
    names = [item.canonical_name for item in distributions]
    if len(set(names)) != len(names):
        raise FlxRuntimeLockError(f"{path}: a distribution may be pinned only once")
    for required in ("torch", "torchvision", "numpy"):
        if required not in names:
            raise FlxRuntimeLockError(f"{path}: the worker cannot run without {required} pinned")
    return RuntimeLock(path=path, sha256=file_sha256(path), distributions=distributions)


def verify_wheel_directory(lock: RuntimeLock, directory: Path) -> tuple[Path, ...]:
    """Rehash every wheel the lock names, in the order the lock names them."""
    directory = Path(directory)
    verified: list[Path] = []
    for distribution in lock.distributions:
        wheel = directory / distribution.filename
        if not wheel.is_file():
            raise FlxRuntimeLockError(f"locked wheel is missing from the bundle: {wheel.name}")
        actual_size = wheel.stat().st_size
        if actual_size != distribution.size_bytes:
            raise FlxRuntimeLockError(
                f"{wheel.name}: byte size changed "
                f"(expected {distribution.size_bytes}, got {actual_size})"
            )
        if file_sha256(wheel) != distribution.sha256:
            raise FlxRuntimeLockError(f"{wheel.name}: SHA-256 changed")
        verified.append(wheel)
    return tuple(verified)


def unexpected_wheels(lock: RuntimeLock, directory: Path) -> Sequence[str]:
    locked = {distribution.filename for distribution in lock.distributions}
    return sorted(
        wheel.name for wheel in Path(directory).glob("*.whl") if wheel.name not in locked
    )
