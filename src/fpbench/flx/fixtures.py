"""Synthetic, non-biometric inputs for qualifying the route.

**None of these is a fingerprint.**  They are procedurally generated rasters
that exercise the transform, the model and the comparator.  No biometric
conclusion can be drawn from them and none is attempted: Stage 8B reads no
SD300 image, no SD4, no FVC, no MCYT and no upstream sample (spec section 16).

They are generated rather than committed, in pure stdlib, so the fixture set is
reproducible from this file alone and content-addressed by its own digest.

The default shape is 381x891 because that is the shape the Stage 6A canonical
pipeline actually produces, so the padding path under test is the padding path
that would run.  ``fixture_odd_padding`` exists because 891 - 381 is even, and
the parity rule is only interesting when it is not.
"""

from __future__ import annotations

import hashlib
import math
import struct
import zlib
from typing import Callable, Mapping

__all__ = [
    "CANONICAL_WIDTH",
    "CANONICAL_HEIGHT",
    "FIXTURE_BUILDERS",
    "build_fixture",
    "build_all_fixtures",
    "fixture_digests",
    "gray8_png",
    "corrupt_png",
    "wrong_bit_depth_png",
    "paletted_png",
]

CANONICAL_WIDTH = 381
CANONICAL_HEIGHT = 891

#: About 0.46 mm between ridges at 500 ppi, which is the human range.  Close
#: enough that the model sees ridge-like structure; nothing more is claimed.
_RIDGES_PER_INCH = 55.0
_PPI = 500


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def gray8_png(width: int, height: int, sample: Callable[[int, int], int]) -> bytes:
    """One non-interlaced 8-bit grayscale PNG, deterministic in ``sample``."""
    raster = bytearray()
    for row in range(height):
        raster.append(0)  # filter type 0: none
        for column in range(width):
            raster.append(max(0, min(255, sample(column, row))))
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
        + _chunk(b"pHYs", struct.pack(">IIB", 19685, 19685, 1))  # 500 ppi
        + _chunk(b"IDAT", zlib.compress(bytes(raster), 9))
        + _chunk(b"IEND", b"")
    )


def _white(width: int, height: int) -> bytes:
    return gray8_png(width, height, lambda x, y: 255)


def _gradient(width: int, height: int) -> bytes:
    span = max(1, width + height - 2)
    return gray8_png(width, height, lambda x, y: (255 * (x + y)) // span)


def _ridges(width: int, height: int) -> bytes:
    period = _PPI / _RIDGES_PER_INCH
    centre_x, centre_y = width / 2.0, height / 2.0

    def sample(x: int, y: int) -> int:
        dx, dy = x - centre_x, y - centre_y
        radius = math.hypot(dx, dy)
        angle = math.atan2(dy, dx)
        # A whorl: radius and angle both advance the phase.
        phase = (radius + period * angle / (2 * math.pi)) * (2 * math.pi / period)
        return int(128 + 110 * math.cos(phase))

    return gray8_png(width, height, sample)


def _seeded_noise(width: int, height: int) -> bytes:
    # An explicit LCG, so the values do not depend on any random module's
    # implementation staying put across releases.
    def sample(x: int, y: int) -> int:
        state = (x * 1103515245 + y * 12345 + 2531011) & 0x7FFFFFFF
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
        return (state >> 16) & 0xFF

    return gray8_png(width, height, sample)


FIXTURE_BUILDERS: Mapping[str, Callable[[], bytes]] = {
    "fixture_white": lambda: _white(CANONICAL_WIDTH, CANONICAL_HEIGHT),
    "fixture_gradient": lambda: _gradient(CANONICAL_WIDTH, CANONICAL_HEIGHT),
    "fixture_synthetic_ridges": lambda: _ridges(CANONICAL_WIDTH, CANONICAL_HEIGHT),
    "fixture_seeded_noise": lambda: _seeded_noise(CANONICAL_WIDTH, CANONICAL_HEIGHT),
    # 201 - 100 is odd, so this is the one that exercises the parity rule.
    "fixture_odd_padding": lambda: _ridges(100, 201),
    # Wider than tall, so padding lands on top and bottom instead.
    "fixture_landscape": lambda: _gradient(240, 137),
}


def build_fixture(name: str) -> bytes:
    try:
        return FIXTURE_BUILDERS[name]()
    except KeyError:
        raise KeyError(f"unknown Stage 8B fixture {name!r}") from None


def build_all_fixtures() -> dict[str, bytes]:
    return {name: build_fixture(name) for name in FIXTURE_BUILDERS}


def fixture_digests() -> dict[str, str]:
    return {
        name: hashlib.sha256(payload).hexdigest()
        for name, payload in build_all_fixtures().items()
    }


# ------------------------------------------------ deliberately invalid input


def corrupt_png() -> bytes:
    """A valid header whose image data is not a deflate stream."""
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 0, 0, 0, 0))
        + _chunk(b"IDAT", b"not a deflate stream")
        + _chunk(b"IEND", b"")
    )


def truncated_png() -> bytes:
    """Cut inside the image data, so a chunk body runs off the end."""
    return _white(64, 64)[:-24]


def png_without_iend() -> bytes:
    """Complete chunks, but the stream never terminates."""
    return _white(64, 64)[:-12]


def gamma_tagged_png() -> bytes:
    """Grayscale, but carrying a gAMA the decoder would have to interpret."""
    payload = _white(8, 8)
    # A chunk starts four bytes before its type, at its length field.
    insert = payload.index(b"IDAT") - 4
    return payload[:insert] + _chunk(b"gAMA", struct.pack(">I", 45455)) + payload[insert:]


def wrong_bit_depth_png() -> bytes:
    """16-bit grayscale: a decoder would convert it down without saying so."""
    raster = bytearray()
    for _ in range(8):
        raster.append(0)
        raster.extend(b"\x12\x34" * 8)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 16, 0, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(bytes(raster), 9))
        + _chunk(b"IEND", b"")
    )


def paletted_png() -> bytes:
    """Colour type 3 with a palette: ambiguous, and refused rather than resolved."""
    raster = bytearray()
    for _ in range(8):
        raster.append(0)
        raster.extend(bytes(range(8)))
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 3, 0, 0, 0))
        + _chunk(b"PLTE", bytes(range(24)))
        + _chunk(b"IDAT", zlib.compress(bytes(raster), 9))
        + _chunk(b"IEND", b"")
    )


def interlaced_png() -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 0, 0, 0, 1))
        + _chunk(b"IDAT", zlib.compress(b"\0" * 72, 9))
        + _chunk(b"IEND", b"")
    )


def animated_png() -> bytes:
    """An APNG control chunk: more than one frame, so it is not one image."""
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 0, 0, 0, 0))
        + _chunk(b"acTL", struct.pack(">II", 2, 0))
        + _chunk(b"IDAT", zlib.compress(b"\0" * 72, 9))
        + _chunk(b"IEND", b"")
    )
