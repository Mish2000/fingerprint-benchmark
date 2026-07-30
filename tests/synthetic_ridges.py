"""Deterministic synthetic ridge images for the SourceAFIS tests.

**These are not fingerprints.** They are procedurally generated whorl-like patterns
with roughly the ridge spacing of a real print — enough structure for SourceAFIS to
extract a template and return a score, and nothing more. No biometric conclusion can
be drawn from them and none is attempted anywhere in the suite.

They are generated rather than committed because SD300 imagery is
redistribution-restricted, and generated in pure stdlib because the project has no
image dependency: the harness never decodes a pixel, so adding Pillow just to write
test fixtures would be a dependency for the tests' sake alone.

The pattern scales with DPI so the *physical* ridge period stays about 0.45 mm at
every resolution. That matters for the DPI tests: handing SourceAFIS a 500-ppi-shaped
image while claiming 2000 ppi would make it scale the ridges down to two pixels and
fail extraction for reasons that have nothing to do with whether 2000 was accepted.

See tests/fixtures/sourceafis/README.md for provenance and pinned digests.
"""

from __future__ import annotations

import hashlib
import math
import struct
import zlib
from functools import lru_cache
from pathlib import Path

__all__ = [
    "whorl_png",
    "corrupt_png",
    "write_fixture",
    "fixture_sha256",
    "RIDGES_PER_INCH",
    "FIXTURE_INCHES",
]

#: About 0.46 mm between ridges, which is the human range.
RIDGES_PER_INCH = 55.0

#: Fingertip-sized, and small enough that a 2000-ppi fixture stays quick to build.
FIXTURE_INCHES = 0.5


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


@lru_cache(maxsize=32)
def whorl_png(dpi: int, seed: int) -> bytes:
    """A greyscale PNG of synthetic curved ridges at ``dpi``.

    Cached: a 2000-ppi fixture is a million pixels of pure-Python trigonometry, and
    several tests want the same one.
    """
    size = int(round(FIXTURE_INCHES * dpi))
    ridge_period = dpi / RIDGES_PER_INCH
    centre_x = size * (0.5 + 0.03 * seed)
    centre_y = size * (0.5 - 0.02 * seed)
    edge = 0.52 * size

    rows = bytearray()
    for y in range(size):
        rows.append(0)  # PNG filter byte: none
        dy = y - centre_y
        for x in range(size):
            dx = x - centre_x
            radius = math.hypot(dx, dy)
            angle = math.atan2(dy, dx)
            # Warping is what creates ridge endings and bifurcations. A plain sine
            # grating has no minutiae at all, and SourceAFIS would find nothing.
            warp = 0.35 * ridge_period * math.sin(3 * angle + 0.7 * seed) + (
                0.20 * ridge_period * math.sin((x + 1.3 * y) / (2.5 * ridge_period) + seed)
            )
            value = 128 + 110 * math.sin(2 * math.pi * (radius + warp) / ridge_period)
            falloff = max(0.0, 1.0 - radius / edge)
            level = int(round(255 - (255 - value) * falloff))
            rows.append(min(255, max(0, level)))

    header = struct.pack(">IIBBBBB", size, size, 8, 0, 0, 0, 0)
    return b"".join(
        [
            b"\x89PNG\r\n\x1a\n",
            _chunk(b"IHDR", header),
            _chunk(b"IDAT", zlib.compress(bytes(rows), 6)),
            _chunk(b"IEND", b""),
        ]
    )


def corrupt_png() -> bytes:
    """Bytes that are not a decodable image, for the decode-failure path."""
    return b"\x89PNG\r\n\x1a\nthis is deliberately not a valid PNG body"


def write_fixture(directory: Path, name: str, payload: bytes) -> Path:
    path = Path(directory) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def fixture_sha256(dpi: int, seed: int) -> str:
    return hashlib.sha256(whorl_png(dpi, seed)).hexdigest()
