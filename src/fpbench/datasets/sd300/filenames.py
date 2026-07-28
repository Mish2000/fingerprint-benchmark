"""Parsing of SD300 image file names.

The SD300 README specifies the form ``SUBJECT_IMPRESSION_PPI_FRGP.EXT``, where
FRGP is the ANSI/NIST-ITL 1-2011 Update:2015 friction ridge generalized
position code.

This module only *describes* a file name. It does not decide whether the image
is usable, which anatomical finger it shows, or whether it belongs in an
experiment.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from fpbench.core.enums import Impression

__all__ = ["SD300Filename", "FilenameParseError", "parse_filename", "try_parse"]

# SUBJECT_IMPRESSION_PPI_FRGP.EXT
_FILENAME_PATTERN = re.compile(
    r"^(?P<subject>\d+)"
    r"_(?P<impression>plain|roll)"
    r"_(?P<ppi>\d+)"
    r"_(?P<frgp>\d+)"
    r"\.(?P<extension>[A-Za-z0-9]+)$"
)


class FilenameParseError(ValueError):
    """A file name does not follow the SD300 naming scheme."""


@dataclass(frozen=True, slots=True)
class SD300Filename:
    subject: str
    impression: Impression
    ppi: int
    frgp: int
    extension: str

    @property
    def stem(self) -> str:
        return f"{self.subject}_{self.impression.value}_{self.ppi}_{self.frgp:02d}"

    def __str__(self) -> str:
        return f"{self.stem}.{self.extension}"


def parse_filename(name: str) -> SD300Filename:
    """Parse an SD300 file name, raising :class:`FilenameParseError` if malformed."""
    match = _FILENAME_PATTERN.match(name)
    if match is None:
        raise FilenameParseError(f"not an SD300 image file name: {name!r}")
    return SD300Filename(
        subject=match.group("subject"),
        impression=Impression(match.group("impression")),
        ppi=int(match.group("ppi")),
        frgp=int(match.group("frgp")),
        extension=match.group("extension").lower(),
    )


def try_parse(name: str) -> SD300Filename | None:
    """Parse, returning ``None`` instead of raising. For bulk scanning."""
    try:
        return parse_filename(name)
    except FilenameParseError:
        return None
