"""Small, dependency-free records shared by the isolated bridge processes."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path


def digest(path: Path) -> str:
    with Path(path).open("rb") as stream:
        return (
            hashlib.file_digest(stream, "sha256").hexdigest()
            if hasattr(hashlib, "file_digest")
            else _digest_stream(stream)
        )


def _digest_stream(stream) -> str:
    result = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        result.update(chunk)
    return result.hexdigest()


def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    """One writer, no replacement of an earlier result."""
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def fingerprint(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def validate_xy(points, height: int, width: int) -> None:
    for x, y in points:
        if not (
            math.isfinite(x) and math.isfinite(y) and 0 <= x < width and 0 <= y < height
        ):
            raise ValueError(
                "Point outside zero-based x=column/y=row image coordinates"
            )


def survey_xy(rows):
    """writeCoordinates already adds +8 and writes zero-based row,column."""
    return [(column, row) for row, column in rows]


def native_xy(points, factor: float):
    """Invert cv2.resize(fx=factor, fy=factor), including pixel centres."""
    if not math.isfinite(factor) or factor <= 0:
        raise ValueError("Invalid image scale")
    return [((x + 0.5) / factor - 0.5, (y + 0.5) / factor - 0.5) for x, y in points]


def score_sweep(genuine, impostor):
    """Descriptive, scored-only >= sweep; ties are indivisible, no interpolation."""
    if not genuine or not impostor:
        return []
    groups = {}
    for label, scores in enumerate((genuine, impostor)):
        for value in scores:
            if not math.isfinite(value):
                raise ValueError("Nonfinite score")
            groups.setdefault(value, [0, 0])[label] += 1
    accepted_genuine = accepted_impostor = 0
    rows = [
        {"threshold": None, "accept_none": True, "tar": 0.0, "far": 0.0, "frr": 1.0}
    ]
    for threshold in sorted(groups, reverse=True):
        g, i = groups[threshold]
        accepted_genuine += g
        accepted_impostor += i
        rows.append(
            {
                "threshold": threshold,
                "accept_none": False,
                "tar": accepted_genuine / len(genuine),
                "far": accepted_impostor / len(impostor),
                "frr": (len(genuine) - accepted_genuine) / len(genuine),
            }
        )
    return rows
