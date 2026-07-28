"""Translation from SD300 FRGP codes to anatomical fingers.

This is the single place where the dataset's position vocabulary is converted
into the harness vocabulary. Getting it wrong silently produces pairs that look
genuine but are not, so the mapping is written out explicitly rather than
computed.

SD300 card layout, per the README and the files on disk:

    roll  FRGP 01-10  rolled impressions, one per finger, in card order
    plain FRGP 02-05  segmented distal joints, right index .. right little
    plain FRGP 07-10  segmented distal joints, left index .. left little
    plain FRGP 11     right thumb plain impression   -> anatomical finger 1
    plain FRGP 12     left thumb plain impression    -> anatomical finger 6
    plain FRGP 13     right four-finger simultaneous capture  (multi-finger)
    plain FRGP 14     left four-finger simultaneous capture   (multi-finger)

Note that the plain thumbs arrive under 11/12 while the segmented plain fingers
keep their anatomical numbers; plain 01 and plain 06 do not exist. FRGP 13/14
are simultaneous captures containing four fingers in one image and must never
enter a comparison — they are the images the protocol excludes.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from fpbench.core.enums import FingerprintPosition, Impression

__all__ = [
    "PositionResolution",
    "PLAIN_FRGP_TO_POSITION",
    "ROLL_FRGP_TO_POSITION",
    "MULTI_FINGER_FRGP",
    "resolve_position",
    "expected_frgps",
]

PLAIN_FRGP_TO_POSITION: Mapping[int, FingerprintPosition] = MappingProxyType(
    {
        2: FingerprintPosition.RIGHT_INDEX,
        3: FingerprintPosition.RIGHT_MIDDLE,
        4: FingerprintPosition.RIGHT_RING,
        5: FingerprintPosition.RIGHT_LITTLE,
        7: FingerprintPosition.LEFT_INDEX,
        8: FingerprintPosition.LEFT_MIDDLE,
        9: FingerprintPosition.LEFT_RING,
        10: FingerprintPosition.LEFT_LITTLE,
        11: FingerprintPosition.RIGHT_THUMB,
        12: FingerprintPosition.LEFT_THUMB,
    }
)

ROLL_FRGP_TO_POSITION: Mapping[int, FingerprintPosition] = MappingProxyType(
    {position.value: position for position in FingerprintPosition}
)

#: Simultaneous-capture plain images. Excluded from every comparison.
MULTI_FINGER_FRGP: frozenset[int] = frozenset({13, 14, 15})


@dataclass(frozen=True, slots=True)
class PositionResolution:
    """What an FRGP code means for a given impression type.

    ``is_known`` separates "we know this is not a single finger" from "we do not
    recognise this code at all"; both yield ``position is None``, but only the
    second one is a validation finding.
    """

    position: FingerprintPosition | None
    is_multi_finger: bool
    is_known: bool


_UNKNOWN = PositionResolution(position=None, is_multi_finger=False, is_known=False)


def resolve_position(impression: Impression, frgp: int) -> PositionResolution:
    """Map an SD300 FRGP code to an anatomical finger."""
    if frgp in MULTI_FINGER_FRGP:
        return PositionResolution(position=None, is_multi_finger=True, is_known=True)

    table = (
        PLAIN_FRGP_TO_POSITION
        if impression is Impression.PLAIN
        else ROLL_FRGP_TO_POSITION
    )
    position = table.get(frgp)
    if position is None:
        return _UNKNOWN
    return PositionResolution(position=position, is_multi_finger=False, is_known=True)


def expected_frgps(impression: Impression) -> frozenset[int]:
    """The FRGP codes a complete subject should have for this impression type."""
    table = (
        PLAIN_FRGP_TO_POSITION
        if impression is Impression.PLAIN
        else ROLL_FRGP_TO_POSITION
    )
    return frozenset(table)
