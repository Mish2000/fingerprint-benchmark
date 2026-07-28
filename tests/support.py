"""Builders for synthetic SD300-shaped data.

Kept out of ``conftest.py`` so that tests can import the builders directly;
``tests/`` is on the path via ``pythonpath`` in pyproject.toml.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

from fpbench.core.enums import Impression
from fpbench.datasets.sd300.checksums import checksum_filename
from fpbench.datasets.sd300.finger_mapping import expected_frgps

__all__ = [
    "PLAIN_FRGPS",
    "ROLL_FRGPS",
    "MULTI_FINGER_FRGPS",
    "make_png",
    "build_release",
]

PLAIN_FRGPS = sorted(expected_frgps(Impression.PLAIN))
ROLL_FRGPS = sorted(expected_frgps(Impression.ROLL))
MULTI_FINGER_FRGPS = [13, 14]


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def make_png(width: int = 8, height: int = 8, ppi: int | None = 500) -> bytes:
    """A structurally valid 8-bit greyscale PNG, optionally declaring a resolution.

    Only the header matters to the harness — no pixel data is ever decoded —
    but the file is kept valid so any image tool can open it too.
    """
    parts = [b"\x89PNG\r\n\x1a\n"]
    parts.append(_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)))
    if ppi is not None:
        per_metre = round(ppi / 0.0254)
        parts.append(_chunk(b"pHYs", struct.pack(">IIB", per_metre, per_metre, 1)))
    raw = b"".join(b"\x00" + b"\xff" * width for _ in range(height))
    parts.append(_chunk(b"IDAT", zlib.compress(raw)))
    parts.append(_chunk(b"IEND", b""))
    return b"".join(parts)


def build_release(
    root: Path,
    release: str,
    ppi: int,
    subjects: list[str],
    *,
    directory: str | None = None,
    declared_ppi: int | None = None,
    omit: set[tuple[str, str, int]] | None = None,
) -> Path:
    """Create a synthetic SD300-shaped release on disk.

    Args:
        declared_ppi: What the PNG headers should claim, when it differs from
            ``ppi``. Used to reproduce the SD300C metadata defect.
        omit: ``(subject, impression, frgp)`` triples to leave out, so that
            incomplete subjects can be exercised.
    """
    omit = omit or set()
    directory = directory or release.lower()
    images = root / directory / "images" / str(ppi)

    for impression, frgps in (
        (Impression.PLAIN, PLAIN_FRGPS + MULTI_FINGER_FRGPS),
        (Impression.ROLL, ROLL_FRGPS),
    ):
        target = images / "png" / impression.value
        target.mkdir(parents=True, exist_ok=True)
        rows = ["sha256,filename"]
        for subject in subjects:
            for frgp in frgps:
                if (subject, impression.value, frgp) in omit:
                    continue
                name = f"{subject}_{impression.value}_{ppi}_{frgp:02d}.png"
                payload = make_png(ppi=declared_ppi or ppi)
                (target / name).write_bytes(payload)
                rows.append(f"{_sha256(payload)},{name}")
        (images / checksum_filename(ppi, impression)).write_text(
            "\n".join(rows) + "\n", encoding="utf-8"
        )
    return root


def _sha256(payload: bytes) -> str:
    import hashlib

    return hashlib.sha256(payload).hexdigest()
