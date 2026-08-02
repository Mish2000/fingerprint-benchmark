"""Reading MINDTCT's XYT file, strictly, and refusing anything else.

An XYT file is four integers per line and nothing else: the minutia's column, its
row, its direction in degrees, and a quality between 0 and 100. It is the entire
interface between the two halves of this route, which is why it is parsed rather
than passed along — a file BOZORTH3 would silently make sense of is not the same
thing as a file MINDTCT actually wrote.

**An empty file is a valid template with no minutiae.** MINDTCT finding nothing in
a print is a fact about the print; it is not a broken extraction, and BOZORTH3
scores such a pair 0 quite happily (spec section 27). What is *not* valid is a
missing file, a directory, a symlink, a hard link, a partial line, a float, a
negative number, a NUL byte or a fifth column — every one of those means the
extractor did not produce what this route is built on, and it is recorded as an
extraction failure rather than parsed around.

The bounds below are the XYT format's own, and they are re-checked against the
official build rather than trusted: ``tests/integration/test_nbis_upstream.py``
extracts from real rasters and asserts every value lands inside them, and that a
value outside them is refused. A parser whose ranges came from somebody's memory
would accept an XYT no NBIS ever wrote (spec section 27).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

__all__ = [
    "NbisMinutia",
    "XytFormatError",
    "MAX_MINUTIAE",
    "MAX_LINE_CHARS",
    "THETA_MIN",
    "THETA_MAX",
    "QUALITY_MIN",
    "QUALITY_MAX",
    "parse_xyt",
    "read_xyt",
]

#: BOZORTH3's own maximum is 150 by default and its compiled ceiling is higher;
#: a thousand lines is far past anything MINDTCT produces from a fingertip and
#: well short of anything that could exhaust memory. A file longer than this is
#: not a template.
MAX_MINUTIAE = 1000

#: Four integers and three spaces. A line an order of magnitude longer than the
#: longest legal one is a payload, not a minutia.
MAX_LINE_CHARS = 200

#: Direction, in degrees. The XYT format carries an absolute angle.
THETA_MIN = 0
THETA_MAX = 359

#: Reliability, scaled to a percentage by MINDTCT when it writes the file.
QUALITY_MIN = 0
QUALITY_MAX = 100


class XytFormatError(ValueError):
    """The extractor's output is not an XYT file this route can use.

    Carries a short ``kind`` so the failure mapping can record *what* was wrong
    without putting a file path or a line of somebody's data into a stored
    result.
    """

    def __init__(self, kind: str, detail: str = "") -> None:
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind = kind
        self.detail = detail


@dataclass(frozen=True, slots=True)
class NbisMinutia:
    """One minutia, exactly as MINDTCT wrote it down.

    Deliberately not normalised, rescaled or reordered. This project's job is to
    carry NBIS's own output to BOZORTH3 unchanged; a parser that helpfully sorted
    or de-duplicated would be a second minutiae filter nobody asked for and the
    scores would stop being NBIS's (spec section 7).
    """

    x: int
    y: int
    theta: int
    quality: int


def parse_xyt(
    text: str, *, image_width: int | None = None, image_height: int | None = None
) -> tuple[NbisMinutia, ...]:
    """Parse XYT text into minutiae, or raise :class:`XytFormatError`.

    Args:
        image_width: When known, every ``x`` must fall inside it. Passing ``None``
            skips the bound rather than inventing one — a caller that does not
            know the raster's width must not pretend to.
        image_height: The same, for ``y``.
    """
    if "\x00" in text:
        raise XytFormatError("invalid_extractor_output", "contains a NUL byte")

    minutiae: list[NbisMinutia] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        if len(raw) > MAX_LINE_CHARS:
            raise XytFormatError(
                "invalid_extractor_output", f"line {number} is unreasonably long"
            )
        if len(minutiae) >= MAX_MINUTIAE:
            raise XytFormatError(
                "invalid_extractor_output",
                f"more than {MAX_MINUTIAE} minutiae",
            )
        minutiae.append(_parse_line(line, number))

    if image_width is not None or image_height is not None:
        _require_inside_raster(minutiae, image_width, image_height)
    return tuple(minutiae)


def read_xyt(
    path: Path,
    *,
    image_width: int | None = None,
    image_height: int | None = None,
) -> tuple[NbisMinutia, ...]:
    """Read one XYT file the extractor claims to have written.

    Raises:
        XytFormatError: it is absent, is not an exclusively owned regular file,
            is not decodable text, or does not parse.
    """
    candidate = Path(path)
    if candidate.is_symlink():
        raise XytFormatError("invalid_extractor_output", "the output is a symlink")
    if not candidate.exists():
        raise XytFormatError("missing_extractor_output", "no XYT file was written")
    if not candidate.is_file():
        raise XytFormatError(
            "invalid_extractor_output", "the output is not a regular file"
        )
    try:
        status = candidate.stat()
    except OSError:  # pragma: no cover - it existed a moment ago
        raise XytFormatError("missing_extractor_output", "the XYT file vanished")
    if getattr(status, "st_nlink", 1) > 1:
        raise XytFormatError(
            "invalid_extractor_output", "the output has multiple hard links"
        )
    try:
        payload = candidate.read_bytes()
    except OSError:
        raise XytFormatError("invalid_extractor_output", "the XYT file is unreadable")
    try:
        text = payload.decode("ascii")
    except UnicodeDecodeError:
        raise XytFormatError(
            "invalid_extractor_output", "the XYT file is not ASCII text"
        )
    return parse_xyt(text, image_width=image_width, image_height=image_height)


# ------------------------------------------------------------------ internals


def _parse_line(line: str, number: int) -> NbisMinutia:
    fields = line.split()
    if len(fields) != 4:
        raise XytFormatError(
            "invalid_extractor_output",
            f"line {number} has {len(fields)} fields, expected 4",
        )
    values = [_require_integer(field, number) for field in fields]
    x, y, theta, quality = values
    if x < 0 or y < 0:
        raise XytFormatError(
            "invalid_extractor_output", f"line {number} has a negative coordinate"
        )
    if not THETA_MIN <= theta <= THETA_MAX:
        raise XytFormatError(
            "invalid_extractor_output",
            f"line {number} has theta {theta}, outside {THETA_MIN}..{THETA_MAX}",
        )
    if not QUALITY_MIN <= quality <= QUALITY_MAX:
        raise XytFormatError(
            "invalid_extractor_output",
            f"line {number} has quality {quality}, outside "
            f"{QUALITY_MIN}..{QUALITY_MAX}",
        )
    return NbisMinutia(x=x, y=y, theta=theta, quality=quality)


def _require_integer(field: str, number: int) -> int:
    """An optionally signed run of digits. ``4.0``, ``+4`` and ``0x4`` are not.

    ``int()`` alone would accept ``" 4 "``, ``"4_0"`` and a unicode digit, none of
    which MINDTCT writes; accepting them would mean the parser is lenient about
    exactly the thing it exists to be strict about.
    """
    text = field
    body = text[1:] if text[:1] == "-" else text
    if not body or not body.isdigit() or not body.isascii():
        raise XytFormatError(
            "invalid_extractor_output",
            f"line {number} has a field that is not an integer",
        )
    return int(text)


def _require_inside_raster(
    minutiae: Sequence[NbisMinutia], width: int | None, height: int | None
) -> None:
    for index, minutia in enumerate(minutiae, start=1):
        if width is not None and minutia.x >= width:
            raise XytFormatError(
                "invalid_extractor_output",
                f"minutia {index} lies outside the raster horizontally",
            )
        if height is not None and minutia.y >= height:
            raise XytFormatError(
                "invalid_extractor_output",
                f"minutia {index} lies outside the raster vertically",
            )
