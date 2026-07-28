"""Closed vocabularies shared by every subsystem.

Nothing here is specific to a dataset, a protocol or an algorithm. Dataset
native codes (SD300 FRGP, impression codes, ...) are translated into these
values at the dataset boundary and never leak past it.
"""

from __future__ import annotations

from enum import Enum, IntEnum

__all__ = [
    "Hand",
    "Impression",
    "FingerprintPosition",
    "GroundTruth",
    "ProtocolStage",
    "CohortRole",
]


class Hand(str, Enum):
    RIGHT = "right"
    LEFT = "left"


class Impression(str, Enum):
    """How the friction ridge was deposited on the card."""

    PLAIN = "plain"
    ROLL = "roll"


class FingerprintPosition(IntEnum):
    """Anatomical finger, numbered as in ANSI/NIST-ITL FRGP 1-10.

    This is the *anatomical* identity used for pairing. It is deliberately not
    the dataset's raw position code: SD300 stores a plain right thumb under
    FRGP 11, and the mapping back to finger 1 belongs to the dataset layer.
    """

    RIGHT_THUMB = 1
    RIGHT_INDEX = 2
    RIGHT_MIDDLE = 3
    RIGHT_RING = 4
    RIGHT_LITTLE = 5
    LEFT_THUMB = 6
    LEFT_INDEX = 7
    LEFT_MIDDLE = 8
    LEFT_RING = 9
    LEFT_LITTLE = 10

    @property
    def hand(self) -> Hand:
        return Hand.RIGHT if self.value <= 5 else Hand.LEFT

    @property
    def label(self) -> str:
        """Stable short label used inside identifiers, e.g. ``f01``."""
        return f"f{self.value:02d}"


ALL_POSITIONS: frozenset[FingerprintPosition] = frozenset(FingerprintPosition)


class GroundTruth(str, Enum):
    """Whether two images are known to originate from the same anatomical finger.

    A SELF comparison (an image against itself) is MATED; it is distinguished
    from a genuine cross-impression comparison by :class:`ProtocolStage`, not
    by its ground truth.
    """

    MATED = "mated"
    NON_MATED = "non_mated"


class ProtocolStage(str, Enum):
    """The experiment step a pair belongs to."""

    PLAIN_SELF = "plain_self"
    ROLL_SELF = "roll_self"
    PLAIN_ROLL_MATED = "plain_roll_mated"
    PLAIN_ROLL_NON_MATED = "plain_roll_non_mated"

    @property
    def is_self(self) -> bool:
        return self in (ProtocolStage.PLAIN_SELF, ProtocolStage.ROLL_SELF)


class CohortRole(str, Enum):
    """What a cohort may be used for.

    The distinction exists to make threshold-calibration leakage detectable in
    code rather than in review: calibration must refuse a TEST cohort.
    """

    TEST = "test"
    DEVELOPMENT = "development"
