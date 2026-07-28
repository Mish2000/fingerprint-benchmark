"""Which resolution the harness treats as true, and why.

Three distinct quantities are easy to conflate, so they are named separately
throughout the codebase:

nominal_ppi
    The resolution the release is published at, per its README and its
    directory name. 500 / 1000 / 2000.

metadata_ppi
    The resolution the individual PNG file declares in its ``pHYs`` chunk.
    Advisory only.

effective_ppi
    The resolution the harness uses for every downstream decision. This is the
    authoritative value.

For SD300A and SD300B all three agree for every file. For SD300C, 10,115 of
19,435 files declare 5080 ppi in ``pHYs`` while being genuinely 2000 ppi
images: their pixel dimensions are exactly 2x the SD300B (1000 ppi) versions of
the same captures, where a true 5080 ppi scan would have to be 5.08x. 5080 is
the scanner's optical resolution leaking into the header.

The policy is therefore: ignore ``pHYs`` for SD300C and use 2000. Source files
are never rewritten — the anomaly is recorded, not repaired. See
docs/adr/0004-sd300c-effective-ppi.md.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

from fpbench.core.errors import ConfigurationError

__all__ = [
    "NOMINAL_PPI",
    "EFFECTIVE_PPI",
    "KNOWN_METADATA_PPI_ANOMALIES",
    "nominal_ppi",
    "effective_ppi",
    "is_known_metadata_anomaly",
]

NOMINAL_PPI: Mapping[str, int] = MappingProxyType(
    {"SD300A": 500, "SD300B": 1000, "SD300C": 2000}
)

EFFECTIVE_PPI: Mapping[str, int] = MappingProxyType(
    {"SD300A": 500, "SD300B": 1000, "SD300C": 2000}
)

#: Metadata values that are known-wrong for a release and must not be treated
#: as an unexpected finding. Anything outside this set is a hard error.
KNOWN_METADATA_PPI_ANOMALIES: Mapping[str, frozenset[int]] = MappingProxyType(
    {"SD300C": frozenset({5080})}
)


def _lookup(table: Mapping[str, int], release: str) -> int:
    try:
        return table[release]
    except KeyError:
        raise ConfigurationError(
            f"unknown SD300 release {release!r}; known: {sorted(NOMINAL_PPI)}"
        ) from None


def nominal_ppi(release: str) -> int:
    return _lookup(NOMINAL_PPI, release)


def effective_ppi(release: str) -> int:
    return _lookup(EFFECTIVE_PPI, release)


def is_known_metadata_anomaly(release: str, metadata_ppi: int) -> bool:
    """True if this ``pHYs`` value is a documented defect for this release."""
    return metadata_ppi in KNOWN_METADATA_PPI_ANOMALIES.get(release, frozenset())
