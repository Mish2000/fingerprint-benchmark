"""The one input shape this route accepts, checked before any process starts.

MINDTCT is handed the prepared file byte for byte. That is only defensible if the
file really is what the route says it is, so the check happens here, in Python,
before a subprocess exists: an 8-bit greyscale PNG whose pixels the harness has
not touched, at an effective 500 ppi.

Everything else is refused *as a comparison failure*, not as an exception — an
RGB image is a fact about the input set, and the run records it and carries on
(docs/adr/0013). The single exception is a file whose bytes no longer hash to
what the prepared image says they are, which is not a property of this pair at
all: it means the artefact changed after preflight approved it, and every result
already written is then attributable to something that is no longer there
(docs/adr/0033, spec section 20).

Nothing here decodes a pixel. The chunk table is walked, IHDR is read and its CRC
checked, and the file is required to have image data and to end properly. That is
enough to know the format and the raster size, and stopping there is what keeps
this module free of an image library the harness deliberately does not have in
the adapter layer.

The ``pHYs`` chunk is deliberately **not** consulted. Whether it is present, and
what it says, is exactly what stage 7B measured and found MINDTCT ignores; a
check here would quietly reintroduce the dependency the measurement removed
(docs/adr/0047, spec section 22).
"""

from __future__ import annotations

import hashlib
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

from fpbench.core.errors import PreparedImageDriftError
from fpbench.core.execution_models import PreparedImage

__all__ = [
    "REQUIRED_EFFECTIVE_PPI",
    "REQUIRED_MEDIA_TYPE",
    "MIN_SIDE_PIXELS",
    "MAX_SIDE_PIXELS",
    "NbisInputRejected",
    "Gray8Raster",
    "require_gray8_500ppi_png",
]

#: The only resolution this route runs at. Not configurable: 500 ppi is part of
#: the algorithm identity, and running at another resolution is another
#: experiment (docs/adr/0047).
REQUIRED_EFFECTIVE_PPI = 500

REQUIRED_MEDIA_TYPE = "image/png"

#: A raster too small for MINDTCT's fixed-size spatial windows is not something
#: to hand it and hope. The upper bound is a sanity limit, not a policy.
MIN_SIDE_PIXELS = 64
MAX_SIDE_PIXELS = 20000

_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_GRAYSCALE_COLOUR_TYPE = 0
_REQUIRED_BIT_DEPTH = 8

_COLOUR_TYPE_NAMES = {
    0: "greyscale",
    2: "truecolour",
    3: "indexed colour",
    4: "greyscale with alpha",
    6: "truecolour with alpha",
}


class NbisInputRejected(Exception):
    """The prepared image is not the input this route is defined over.

    Carries a short ``reason`` the failure mapping puts in the stored result. It
    names the shape that was wrong and never the file it came from.
    """

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True, slots=True)
class Gray8Raster:
    """What the check learned about the file, and nothing more."""

    width: int
    height: int
    size_bytes: int


def require_gray8_500ppi_png(image: PreparedImage) -> Gray8Raster:
    """Confirm one prepared image is this route's input, or refuse it.

    Raises:
        NbisInputRejected: it is not a single-frame 8-bit greyscale PNG, is not
            at 500 ppi, is missing, or is an unusable size.
        PreparedImageDriftError: it is the right shape but the wrong bytes. Fatal
            to the invocation rather than recorded, because a result written
            afterwards would name an input that no longer exists.
    """
    if image.media_type != REQUIRED_MEDIA_TYPE:
        raise NbisInputRejected(
            "unsupported_media_type",
            f"{image.media_type!r}; this route reads PNG only and never converts",
        )
    if int(image.effective_ppi) != REQUIRED_EFFECTIVE_PPI:
        raise NbisInputRejected(
            "unsupported_resolution",
            f"{image.effective_ppi} ppi; this route is defined at "
            f"{REQUIRED_EFFECTIVE_PPI} only",
        )

    path = Path(image.local_path)
    if path.is_symlink():
        raise NbisInputRejected("input_not_a_regular_file", "the input is a symlink")
    if not path.is_file():
        raise NbisInputRejected("input_missing", "the prepared image is not there")

    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise NbisInputRejected(
            "input_unreadable", type(exc).__name__
        ) from exc

    raster = _read_gray8_header(payload)

    expected_digest = image.prepared_sha256 or image.expected_sha256
    expected_size = image.prepared_size_bytes
    actual_digest = hashlib.sha256(payload).hexdigest()
    if actual_digest != expected_digest or (
        expected_size is not None and len(payload) != int(expected_size)
    ):
        raise PreparedImageDriftError(
            f"the prepared image {image.image_id} on disk is not the artefact the "
            "run was defined over: it no longer hashes to what the preparer "
            "recorded. No further comparison may be attributed to this run "
            "(docs/adr/0033)"
        )
    return raster


# ------------------------------------------------------------------ internals


def _read_gray8_header(payload: bytes) -> Gray8Raster:
    """Walk the chunk table far enough to know the format and the raster size."""
    if len(payload) < len(_SIGNATURE) + 12 or payload[: len(_SIGNATURE)] != _SIGNATURE:
        raise NbisInputRejected("not_a_png", "the PNG signature is missing")

    offset = len(_SIGNATURE)
    header: tuple[int, int, int, int, int, int, int] | None = None
    seen_data = False
    ended = False
    seen: set[bytes] = set()

    while offset + 8 <= len(payload):
        (length,) = struct.unpack(">I", payload[offset : offset + 4])
        kind = payload[offset + 4 : offset + 8]
        body_start = offset + 8
        body_end = body_start + length
        if length > len(payload) or body_end + 4 > len(payload):
            raise NbisInputRejected("malformed_png", "a chunk runs past the file")
        body = payload[body_start:body_end]
        (declared_crc,) = struct.unpack(">I", payload[body_end : body_end + 4])

        if kind in (b"IHDR", b"IEND"):
            if zlib.crc32(kind + body) & 0xFFFFFFFF != declared_crc:
                raise NbisInputRejected("malformed_png", f"{kind.decode()} is corrupt")
        if kind in (b"IHDR", b"IEND", b"PLTE") and kind in seen:
            raise NbisInputRejected(
                "malformed_png", f"{kind.decode()} appears more than once"
            )
        seen.add(kind)

        if kind == b"IHDR":
            if header is not None or offset != len(_SIGNATURE):
                raise NbisInputRejected("malformed_png", "IHDR is not the first chunk")
            if length != 13:
                raise NbisInputRejected("malformed_png", "IHDR is the wrong length")
            # width, height, bit depth, colour type, compression, filter, interlace
            header = struct.unpack(">IIBBBBB", body)
        elif header is None:
            raise NbisInputRejected("malformed_png", "the file does not start with IHDR")
        elif kind == b"IDAT":
            seen_data = True
        elif kind == b"IEND":
            ended = True
            offset = body_end + 4
            break

        offset = body_end + 4

    if header is None:
        raise NbisInputRejected("malformed_png", "there is no IHDR")
    if not seen_data:
        raise NbisInputRejected("malformed_png", "there is no image data")
    if not ended:
        raise NbisInputRejected("malformed_png", "the file is truncated before IEND")

    width, height, bit_depth, colour_type, compression, filter_method, interlace = header

    if compression != 0 or filter_method != 0:
        raise NbisInputRejected(
            "unsupported_png_layout", "the PNG uses a non-standard compression scheme"
        )
    if colour_type != _GRAYSCALE_COLOUR_TYPE:
        raise NbisInputRejected(
            "unsupported_colour_type",
            f"{_COLOUR_TYPE_NAMES.get(colour_type, colour_type)}; this route reads "
            "8-bit greyscale only and never flattens",
        )
    if bit_depth != _REQUIRED_BIT_DEPTH:
        raise NbisInputRejected(
            "unsupported_bit_depth",
            f"{bit_depth}-bit; this route reads 8-bit only and never truncates",
        )
    if interlace != 0:
        raise NbisInputRejected("unsupported_png_layout", "the PNG is interlaced")
    if not (MIN_SIDE_PIXELS <= width <= MAX_SIDE_PIXELS) or not (
        MIN_SIDE_PIXELS <= height <= MAX_SIDE_PIXELS
    ):
        raise NbisInputRejected(
            "unusable_dimensions", f"{width}x{height} pixels"
        )
    return Gray8Raster(width=width, height=height, size_bytes=len(payload))
