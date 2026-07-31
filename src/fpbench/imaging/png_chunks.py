"""Reading a PNG's chunk inventory without trusting a decoder to summarise it.

Pillow will happily open a paletted image, an image with an embedded ICC
profile, or an image whose ``gAMA`` says its samples are not linear — and hand
back an ``L``-mode raster in every case, having quietly applied a policy nobody
in this project chose. That policy would then be the experiment's, invisibly.

So the container is inspected directly. Twelve bytes of header per chunk, a
length, a type and a CRC: enough to answer three questions the decoder cannot be
asked to answer honestly.

*What is actually in this file?* — a source carrying ``PLTE``, ``tRNS``,
``gAMA``, ``sRGB`` or ``iCCP`` is ambiguous, and ambiguity is refused rather
than resolved by whichever library happens to be installed (spec section 15).

*What did we write?* — a canonical output may contain ``IHDR``, ``pHYs``,
``IDAT`` and ``IEND``, and nothing else. No timestamp, no software name, no
source filename: metadata is where a dataset inventory leaks (spec section 28).

*Is the resolution really declared?* — ``pHYs`` is parsed rather than inferred
from a ``dpi`` keyword, because the number that matters is the one in the file.

The parser is deliberately strict and stdlib-only. It validates the signature,
every CRC and the terminating ``IEND``; a file that does not parse is not
silently treated as a file with no interesting chunks.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from typing import Mapping, Sequence

from fpbench.core.errors import ImagingError

__all__ = [
    "PNG_SIGNATURE",
    "PngChunk",
    "PngChunkInventory",
    "SOURCE_AMBIGUOUS_CHUNKS",
    "CANONICAL_ALLOWED_CHUNKS",
    "CANONICAL_FORBIDDEN_CHUNKS",
    "KNOWN_CHUNK_TYPES",
    "PngPhys",
    "PngHeader",
    "parse_png_chunks",
    "read_png_inventory",
]

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

#: Chunk types this module names explicitly. Anything outside it is still
#: reported — an unknown chunk is a finding, not something to skip.
KNOWN_CHUNK_TYPES: tuple[str, ...] = (
    "IHDR",
    "PLTE",
    "tRNS",
    "gAMA",
    "sRGB",
    "iCCP",
    "pHYs",
    "tEXt",
    "zTXt",
    "iTXt",
    "eXIf",
    "tIME",
    "IDAT",
    "IEND",
)

#: Present in a source image, these make "what are this file's grey values?"
#: a question with more than one defensible answer. A palette or an alpha
#: channel changes what a sample means; ``gAMA``, ``sRGB`` and ``iCCP`` change
#: how it should be interpreted before it is compared. None of them is repaired
#: here, and none is ignored: the image is refused and the profile is asked to
#: say what should happen to it (spec section 15).
SOURCE_AMBIGUOUS_CHUNKS: frozenset[str] = frozenset(
    {"PLTE", "tRNS", "gAMA", "sRGB", "iCCP"}
)

#: Everything a canonical output may contain. ``IDAT`` may repeat.
CANONICAL_ALLOWED_CHUNKS: frozenset[str] = frozenset({"IHDR", "pHYs", "IDAT", "IEND"})

#: Named separately from "not allowed" so that the error message can say *this
#: is metadata we deliberately strip* rather than *this is unexpected*.
CANONICAL_FORBIDDEN_CHUNKS: frozenset[str] = frozenset(
    {"PLTE", "tRNS", "gAMA", "sRGB", "iCCP", "tEXt", "zTXt", "iTXt", "eXIf", "tIME"}
)

#: PNG colour type 0. The only one a canonical grayscale artefact may declare.
PNG_COLOUR_TYPE_GRAYSCALE = 0

#: pHYs unit specifier 1 = metre. 0 means "aspect ratio only", which declares no
#: resolution at all.
PNG_PHYS_UNIT_METRE = 1


@dataclass(frozen=True, slots=True)
class PngChunk:
    """One chunk's type, size and position. Never its payload, except for headers.

    IDAT payloads of a 2000-ppi fingerprint run to megabytes and nothing here
    needs them; keeping only the offsets makes an inventory cheap enough to take
    for all 3,000 images twice.
    """

    ordinal: int
    chunk_type: str
    length: int
    offset: int


@dataclass(frozen=True, slots=True)
class PngHeader:
    """The IHDR fields, parsed rather than inferred."""

    width: int
    height: int
    bit_depth: int
    colour_type: int
    compression_method: int
    filter_method: int
    interlace_method: int

    @property
    def is_grayscale(self) -> bool:
        return self.colour_type == PNG_COLOUR_TYPE_GRAYSCALE

    @property
    def is_interlaced(self) -> bool:
        return self.interlace_method != 0


@dataclass(frozen=True, slots=True)
class PngPhys:
    """The declared physical resolution, in pixels per unit."""

    pixels_per_unit_x: int
    pixels_per_unit_y: int
    unit_specifier: int

    @property
    def declares_metre(self) -> bool:
        return self.unit_specifier == PNG_PHYS_UNIT_METRE


@dataclass(frozen=True, slots=True)
class PngChunkInventory:
    """Everything this module can say about a PNG container."""

    chunks: tuple[PngChunk, ...]
    header: PngHeader
    phys: PngPhys | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "chunks", tuple(self.chunks))

    @property
    def chunk_types(self) -> tuple[str, ...]:
        """Every chunk type in file order, repeats included."""
        return tuple(chunk.chunk_type for chunk in self.chunks)

    @property
    def distinct_chunk_types(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.chunk_types)))

    def counts(self) -> Mapping[str, int]:
        counts: dict[str, int] = {}
        for chunk in self.chunks:
            counts[chunk.chunk_type] = counts.get(chunk.chunk_type, 0) + 1
        return dict(sorted(counts.items()))

    def has(self, chunk_type: str) -> bool:
        return chunk_type in set(self.chunk_types)

    # ------------------------------------------------------------- policies

    def source_ambiguities(self) -> tuple[str, ...]:
        """Chunks that make this source's grey values ambiguous.

        ``pHYs`` is deliberately absent from the result even when it is wrong.
        SD300C declares 5080 ppi in 10,115 files and the harness has already
        decided, in writing, that the manifest's effective ppi is authoritative
        and the header is not consulted (docs/adr/0004, docs/adr/0032). A value
        nothing reads cannot make anything ambiguous.
        """
        present = set(self.chunk_types)
        return tuple(sorted(present & SOURCE_AMBIGUOUS_CHUNKS))

    def canonical_violations(self) -> tuple[str, ...]:
        """Why this file is not a canonical output. Empty when it is."""
        problems: list[str] = []
        types = list(self.chunk_types)
        present = set(types)

        forbidden = sorted(present & CANONICAL_FORBIDDEN_CHUNKS)
        if forbidden:
            problems.append(
                "carries metadata a canonical artefact must not: "
                + ", ".join(forbidden)
            )
        unknown = sorted(present - CANONICAL_ALLOWED_CHUNKS - CANONICAL_FORBIDDEN_CHUNKS)
        if unknown:
            problems.append("carries unexpected chunk(s): " + ", ".join(unknown))

        if not types or types[0] != "IHDR":
            problems.append("does not start with IHDR")
        if not types or types[-1] != "IEND":
            problems.append("does not end with IEND")
        if types.count("IHDR") != 1:
            problems.append(f"holds {types.count('IHDR')} IHDR chunks, expected one")
        if types.count("pHYs") != 1:
            problems.append(
                f"holds {types.count('pHYs')} pHYs chunks; a canonical artefact "
                "declares its resolution exactly once"
            )
        if types.count("IDAT") < 1:
            problems.append("holds no IDAT chunk")

        # pHYs must precede IDAT, per the PNG specification. A decoder that read
        # it afterwards would be reading a file no other decoder has to accept.
        if "pHYs" in present and "IDAT" in present:
            if types.index("pHYs") > types.index("IDAT"):
                problems.append("declares pHYs after the first IDAT")

        return tuple(problems)


def parse_png_chunks(data: bytes) -> PngChunkInventory:
    """Walk the container and return what is in it.

    Raises:
        ImagingError: the signature, a length, a CRC or the chunk ordering is
            wrong. A file that does not parse here is not passed on to a decoder
            in the hope that it copes.
    """
    payload = bytes(data)
    if not payload.startswith(PNG_SIGNATURE):
        raise ImagingError("not a PNG: the eight-byte signature is missing")

    chunks: list[PngChunk] = []
    header: PngHeader | None = None
    phys: PngPhys | None = None

    offset = len(PNG_SIGNATURE)
    total = len(payload)
    ordinal = 0
    seen_end = False

    while offset < total:
        if seen_end:
            raise ImagingError(
                f"{total - offset} trailing byte(s) after IEND; a PNG ends at IEND"
            )
        if total - offset < 12:
            raise ImagingError(
                f"truncated PNG: {total - offset} byte(s) left, a chunk needs 12"
            )
        (length,) = struct.unpack(">I", payload[offset : offset + 4])
        chunk_type_bytes = payload[offset + 4 : offset + 8]
        try:
            chunk_type = chunk_type_bytes.decode("ascii")
        except UnicodeDecodeError:
            raise ImagingError(
                f"chunk at byte {offset} has a non-ASCII type"
            ) from None
        if not chunk_type.isalpha():
            raise ImagingError(
                f"chunk at byte {offset} has an unusable type {chunk_type!r}"
            )
        end = offset + 8 + length
        if end + 4 > total:
            raise ImagingError(
                f"{chunk_type} at byte {offset} declares {length} bytes, which runs "
                "past the end of the file"
            )
        body = payload[offset + 8 : end]
        (declared_crc,) = struct.unpack(">I", payload[end : end + 4])
        actual_crc = zlib.crc32(chunk_type_bytes + body) & 0xFFFFFFFF
        if declared_crc != actual_crc:
            raise ImagingError(
                f"{chunk_type} at byte {offset} fails its CRC; the file is corrupt"
            )

        if chunk_type == "IHDR":
            header = _parse_ihdr(body)
        elif chunk_type == "pHYs":
            phys = _parse_phys(body)
        elif chunk_type == "IEND":
            seen_end = True

        chunks.append(
            PngChunk(
                ordinal=ordinal, chunk_type=chunk_type, length=length, offset=offset
            )
        )
        ordinal += 1
        offset = end + 4

    if header is None:
        raise ImagingError("the PNG carries no IHDR chunk")
    if not seen_end:
        raise ImagingError("the PNG is truncated: no IEND chunk")

    return PngChunkInventory(chunks=tuple(chunks), header=header, phys=phys)


def read_png_inventory(path) -> PngChunkInventory:
    """Read a file and parse its chunks."""
    from pathlib import Path

    return parse_png_chunks(Path(path).read_bytes())


# ----------------------------------------------------------------- internals


def _parse_ihdr(body: bytes) -> PngHeader:
    if len(body) != 13:
        raise ImagingError(f"IHDR is {len(body)} bytes, expected 13")
    width, height, depth, colour, compression, filtering, interlace = struct.unpack(
        ">IIBBBBB", body
    )
    if width == 0 or height == 0:
        raise ImagingError(f"IHDR declares a {width}x{height} image")
    return PngHeader(
        width=width,
        height=height,
        bit_depth=depth,
        colour_type=colour,
        compression_method=compression,
        filter_method=filtering,
        interlace_method=interlace,
    )


def _parse_phys(body: bytes) -> PngPhys:
    if len(body) != 9:
        raise ImagingError(f"pHYs is {len(body)} bytes, expected 9")
    x, y, unit = struct.unpack(">IIB", body)
    return PngPhys(pixels_per_unit_x=x, pixels_per_unit_y=y, unit_specifier=unit)


def describe(types: Sequence[str]) -> str:
    """A short, stable rendering of a chunk inventory for a message."""
    return ", ".join(types) if types else "(none)"
