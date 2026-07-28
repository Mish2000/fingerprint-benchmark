"""Checking an SD300 release on disk against what it declares.

Two independent sources of truth are compared:

  * the file name, which encodes subject, impression, PPI and FRGP;
  * the PNG header, which declares pixel dimensions and physical resolution.

Header reading is stdlib only — the ``pHYs`` and ``IHDR`` chunks are parsed
directly, no pixels are decoded and no file is modified. That keeps validation
dependency-free and fast enough to run over all 58,305 images.

Validation reports; it never repairs. The SD300C PPI defect is recorded as a
warning on every affected file and resolved by policy, not by rewriting NIST's
data (docs/adr/0004).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

from fpbench.datasets.base import Severity, ValidationIssue
from fpbench.datasets.sd300 import ppi_policy
from fpbench.datasets.sd300.filenames import SD300Filename
from fpbench.datasets.sd300.finger_mapping import resolve_position

__all__ = [
    "PngHeader",
    "PngHeaderError",
    "read_png_header",
    "metres_to_ppi",
    "IssueCode",
    "load_header",
    "validate_file",
    "iter_image_files",
]

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_METRES_PER_INCH = 0.0254


class IssueCode:
    """Validation finding codes.

    Kept as plain string constants rather than an enum: they are written into
    manifests and reports, and must stay readable and stable there.
    """

    FILENAME_UNPARSEABLE = "filename_unparseable"
    FILENAME_PPI_MISMATCH = "filename_ppi_mismatch"
    UNKNOWN_FRGP = "unknown_frgp"
    PNG_HEADER_UNREADABLE = "png_header_unreadable"
    MISSING_PHYS_CHUNK = "missing_phys_chunk"
    METADATA_PPI_ANOMALY = "metadata_ppi_anomaly"
    UNEXPECTED_METADATA_PPI = "unexpected_metadata_ppi"
    NON_SQUARE_RESOLUTION = "non_square_resolution"


class PngHeaderError(ValueError):
    """The file is not a readable PNG, or its header is truncated."""


@dataclass(frozen=True, slots=True)
class PngHeader:
    width: int
    height: int
    bit_depth: int
    colour_type: int
    ppi_x: int | None
    ppi_y: int | None

    @property
    def ppi(self) -> int | None:
        """The declared resolution when it is square, else ``None``."""
        if self.ppi_x is not None and self.ppi_x == self.ppi_y:
            return self.ppi_x
        return None


def metres_to_ppi(pixels_per_metre: int) -> int:
    """Convert a PNG ``pHYs`` value to pixels per inch, rounded to the nearest."""
    return round(pixels_per_metre * _METRES_PER_INCH)


def read_png_header(path: Path) -> PngHeader:
    """Read IHDR and pHYs without decoding image data.

    Stops at the first IDAT chunk: everything of interest precedes the pixel
    data, so a few hundred bytes are read per file regardless of its size.
    """
    with Path(path).open("rb") as handle:
        if handle.read(8) != _PNG_SIGNATURE:
            raise PngHeaderError(f"{path}: not a PNG file")

        width = height = bit_depth = colour_type = None
        ppi_x = ppi_y = None

        while True:
            prefix = handle.read(8)
            if len(prefix) < 8:
                break
            length, chunk_type = struct.unpack(">I4s", prefix)

            if chunk_type == b"IHDR":
                data = handle.read(length)
                if len(data) < 13:
                    raise PngHeaderError(f"{path}: truncated IHDR")
                width, height, bit_depth, colour_type = struct.unpack(
                    ">IIBB", data[:10]
                )
                handle.seek(4, 1)  # CRC
            elif chunk_type == b"pHYs":
                data = handle.read(length)
                if len(data) < 9:
                    raise PngHeaderError(f"{path}: truncated pHYs")
                per_metre_x, per_metre_y, unit = struct.unpack(">IIB", data[:9])
                if unit == 1:  # 1 == metre; 0 == unknown/aspect-ratio only
                    ppi_x = metres_to_ppi(per_metre_x)
                    ppi_y = metres_to_ppi(per_metre_y)
                handle.seek(4, 1)
            elif chunk_type in (b"IDAT", b"IEND"):
                break
            else:
                handle.seek(length + 4, 1)

        if width is None:
            raise PngHeaderError(f"{path}: no IHDR chunk")

    return PngHeader(
        width=width,
        height=height,
        bit_depth=bit_depth,
        colour_type=colour_type,
        ppi_x=ppi_x,
        ppi_y=ppi_y,
    )


def load_header(path: Path) -> tuple[PngHeader | None, str | None]:
    """Read a PNG header, returning ``(header, None)`` or ``(None, reason)``."""
    try:
        return read_png_header(path), None
    except (PngHeaderError, OSError) as exc:
        return None, str(exc)


def validate_file(
    *,
    release: str,
    relative_path: str,
    parsed: SD300Filename | None,
    header: PngHeader | None = None,
    header_error: str | None = None,
) -> tuple[ValidationIssue, ...]:
    """Findings for one image file.

    ``parsed`` and ``header`` are passed in rather than re-derived: the caller
    already needs both to build an :class:`ImageRecord`, and reading a header
    twice across 58k files is not free. Passing neither ``header`` nor
    ``header_error`` means header checks were not requested and are skipped.
    """
    issues: list[ValidationIssue] = []

    def add(code: str, severity: Severity, detail: str) -> None:
        issues.append(
            ValidationIssue(
                code=code,
                severity=severity,
                detail=detail,
                relative_path=relative_path,
            )
        )

    if parsed is None:
        add(
            IssueCode.FILENAME_UNPARSEABLE,
            Severity.ERROR,
            "file name does not match SUBJECT_IMPRESSION_PPI_FRGP.EXT",
        )
        return tuple(issues)

    expected_ppi = ppi_policy.nominal_ppi(release)
    if parsed.ppi != expected_ppi:
        add(
            IssueCode.FILENAME_PPI_MISMATCH,
            Severity.ERROR,
            f"file name declares {parsed.ppi} ppi, release {release} is {expected_ppi} ppi",
        )

    if not resolve_position(parsed.impression, parsed.frgp).is_known:
        add(
            IssueCode.UNKNOWN_FRGP,
            Severity.WARNING,
            f"FRGP {parsed.frgp} has no known meaning for {parsed.impression.value} images",
        )

    if header_error is not None:
        add(IssueCode.PNG_HEADER_UNREADABLE, Severity.ERROR, header_error)
        return tuple(issues)

    if header is None:
        return tuple(issues)

    if header.ppi_x is None:
        add(
            IssueCode.MISSING_PHYS_CHUNK,
            Severity.WARNING,
            "PNG declares no physical resolution",
        )
        return tuple(issues)

    if header.ppi_x != header.ppi_y:
        add(
            IssueCode.NON_SQUARE_RESOLUTION,
            Severity.WARNING,
            f"pHYs declares {header.ppi_x}x{header.ppi_y} ppi",
        )

    declared = header.ppi_x
    effective = ppi_policy.effective_ppi(release)
    if declared != effective:
        if ppi_policy.is_known_metadata_anomaly(release, declared):
            add(
                IssueCode.METADATA_PPI_ANOMALY,
                Severity.WARNING,
                f"pHYs declares {declared} ppi; known {release} defect, "
                f"treated as {effective} ppi by policy",
            )
        else:
            add(
                IssueCode.UNEXPECTED_METADATA_PPI,
                Severity.ERROR,
                f"pHYs declares {declared} ppi, which is neither the effective "
                f"{effective} ppi nor a documented {release} anomaly",
            )

    return tuple(issues)


def iter_image_files(directory: Path, extension: str = "png") -> Iterator[Path]:
    """Yield image files in one impression directory, in sorted order.

    Sorted so that a scan is reproducible across filesystems.
    """
    if not directory.is_dir():
        return
    suffix = f".{extension.lower()}"
    yield from sorted(
        p for p in directory.iterdir() if p.is_file() and p.suffix.lower() == suffix
    )


def count_by_severity(issues: Iterable[ValidationIssue]) -> dict[str, int]:
    counts = {severity.value: 0 for severity in Severity}
    for issue in issues:
        counts[issue.severity.value] += 1
    return counts
