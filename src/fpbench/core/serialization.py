"""Stdlib-only conversion between frozen dataclasses and plain data.

Used by the storage layer to reach parquet/JSON without core having to know
either format. ``core`` imports nothing from the rest of the project and
nothing outside the standard library; that is what keeps it safe to import
everywhere.
"""

from __future__ import annotations

import dataclasses
import json
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence, TypeVar

__all__ = ["to_plain", "write_json", "read_json", "stable_hash"]

T = TypeVar("T")


def to_plain(value: Any) -> Any:
    """Recursively convert dataclasses, enums and containers into JSON-safe data.

    Tuples become lists and enums become their ``.value``, so that the result
    round-trips through JSON and through pyarrow without further handling.
    """
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            f.name: to_plain(getattr(value, f.name))
            for f in dataclasses.fields(value)
        }
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(k): to_plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_plain(v) for v in value]
    if isinstance(value, Path):
        return value.as_posix()
    return value


def write_json(path: Path, value: Any) -> Path:
    """Write ``value`` as pretty, deterministic JSON, creating parent dirs.

    Writes via a sibling temp file and replaces atomically, so an interrupted
    write can never leave a half-written manifest behind.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(to_plain(value), indent=2, ensure_ascii=False, sort_keys=False)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def stable_hash(value: Any, *, length: int = 12) -> str:
    """A short, deterministic digest of any plain-convertible value.

    Used to fingerprint selection criteria and configuration so two manifests
    can be compared without diffing them field by field.
    """
    import hashlib

    canonical = json.dumps(to_plain(value), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:length]


def as_tuple(values: Sequence[T] | None) -> tuple[T, ...]:
    """Normalise an optional sequence to a tuple, for frozen dataclass fields."""
    return tuple(values) if values else ()
