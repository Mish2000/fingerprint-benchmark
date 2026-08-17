"""MINDTCT's XYT into OpenAFIS's CSV, mechanically and with nothing added.

This module is the whole of what Stage 19A had to invent, and it was deliberately
kept to a format change. Every rule below is derived from one of the two upstream
sources, never from looking at a score.

THE COORDINATE AND ANGLE CONVENTION, FROM BOTH SOURCES

NBIS 5.0.0 ``mindtct/src/lib/mindtct/xytreps.c`` documents what MINDTCT writes
when it is run without ``-m1`` — which is how Algorithm 2 runs it, and how this
route runs it:

.. code-block:: text

    XYT's according to NIST internal rep:
      1. pixel coordinates with origin bottom-left
      2. orientation in degrees on range [0..360] with 0 pointing east
         and increasing counter clockwise
      3. direction pointing out and away from the ridge ending or
         bifurcation valley

and the code agrees with the comment: ``y = ih - minutia->y`` flips the origin to
bottom-left, and ``t = (270 - direction * degrees_per_unit) % 360`` produces the
counter-clockwise-from-east angle. ``results.c`` selects ``NIST_INTERNAL_XYT_REP``
whenever the ``-m1`` flag is absent.

OpenAFIS's requirement is read from ``lib/TripletScalar.cpp``, where a minutia's
angle is related to the geometry by

.. code-block:: cpp

    const auto d = FastMath::rotateAngle(m_minutiae[i].angle(),
                                         FastMath::atan2(y, x));

with ``y`` and ``x`` the differences of the *stored* coordinates and
``FastMath::atan2`` calling ``::atan2f(dy, dx)``. So OpenAFIS requires the angle to
be measured counter-clockwise from +x **in the same plane as the stored y** — the
two must share a handedness, and nothing more is required of them.

MINDTCT's NIST internal representation already satisfies exactly that: its y
increases upward and its angle increases counter-clockwise from east in that same
upward-y plane. **So no inversion and no rotation is applied here.** The only
conversion is degrees to radians.

That reading was verified, not assumed: decoding one of OpenAFIS's own ISO
templates into (x, y, angle) the way its ISO parser does and re-emitting it
through this CSV format reproduces the ISO route's score exactly on twelve pairs.
A misread convention would have disagreed.

WHAT IS DELIBERATELY NOT DONE

.. code-block:: text

    no scaling of x or y     OpenAFIS normalises coordinates itself, by
                             x * 256 / width and y * 256 / height, so a
                             normalisation here would be applied twice
    no filtering             every minutia MINDTCT emitted is carried over
    no quality cutoff        quality has no destination and is dropped, not used
    no sorting               MINDTCT's own order is preserved
    no deduplication         OpenAFIS builds its own Delaunay triplets
    no truncation to 128     see below

The minutia *type* is a constant placeholder. OpenAFIS's ``Minutia`` carries a
type, but ``MinutiaPoint`` — the object that actually enters matching — is built
from x, y and angle only, and the triplets are built from ``MinutiaPoint``. The
type never reaches the similarity computation. That is proved rather than
asserted: ``tests/test_stage19a_contract.py`` scores the same minutiae twice, once
all ``RidgeEnding`` and once all ``RidgeBifurcation``, and requires the identical
result. XYT carries no type, so parsing MINDTCT's ``.min`` file to recover one
would be work in service of a field the matcher discards.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from fpbench.adapters.nbis.xyt import NbisMinutia

__all__ = [
    "MINUTIA_TYPE_RIDGE_ENDING",
    "MINUTIA_TYPE_RIDGE_BIFURCATION",
    "PLACEHOLDER_MINUTIA_TYPE",
    "MINUTIA_TYPE_POLICY",
    "OPENAFIS_MINIMUM_MINUTIAE",
    "OPENAFIS_MAXIMUM_MINUTIAE",
    "ANGLE_CONVERSION",
    "TranslationRefused",
    "TranslatedTemplate",
    "translate_xyt_to_openafis_csv",
]

#: ``Minutia::Type`` in lib/Minutia.h: Invalid = 0, RidgeEnding = 1,
#: RidgeBifurcation = 2. OpenAFIS's CSV reader refuses type 0 outright.
MINUTIA_TYPE_RIDGE_ENDING = 1
MINUTIA_TYPE_RIDGE_BIFURCATION = 2

#: Constant for every minutia, and non-score-bearing. See the module docstring.
PLACEHOLDER_MINUTIA_TYPE = MINUTIA_TYPE_RIDGE_ENDING
MINUTIA_TYPE_POLICY = "constant_placeholder_non_score_bearing"

#: OpenAFIS's own bounds, from ``Template<I, F>`` in lib/Template.h. A template
#: outside them is refused by ``Template::load`` and is a template failure, not
#: something for this module to fix by dropping minutiae.
OPENAFIS_MINIMUM_MINUTIAE = 2
OPENAFIS_MAXIMUM_MINUTIAE = 128

ANGLE_CONVERSION = "radians = degrees * pi / 180; no inversion, no rotation"


class TranslationRefused(Exception):
    """The minutiae cannot become an OpenAFIS template, and are not made to.

    Carries a ``reason`` the failure mapping records. The reasons are properties
    of OpenAFIS's declared limits, so they belong to the matcher rather than to
    this bridge.
    """

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True, slots=True)
class TranslatedTemplate:
    """One OpenAFIS CSV template, and the count that produced it."""

    text: str
    minutiae_count: int


def translate_xyt_to_openafis_csv(
    minutiae: Sequence[NbisMinutia],
    *,
    width: int,
    height: int,
    minutia_type: int = PLACEHOLDER_MINUTIA_TYPE,
) -> TranslatedTemplate:
    """Render MINDTCT minutiae as an OpenAFIS CSV template.

    ``width`` and ``height`` must be the prepared image's real dimensions:
    OpenAFIS scales every coordinate by ``256 / width`` and ``256 / height`` when
    it builds its ``MinutiaPoint``, so passing anything else would silently
    rescale the whole template.

    Args:
        minutia_type: exposed only so a test can prove the type does not reach
            the score. Production always uses the placeholder.

    Raises:
        TranslationRefused: fewer than 2 or more than 128 minutiae. Both are
            OpenAFIS's limits; neither is worked around by dropping or padding.
    """
    if width <= 0 or height <= 0:
        raise TranslationRefused("invalid_raster_dimensions", f"{width}x{height}")

    count = len(minutiae)
    if count < OPENAFIS_MINIMUM_MINUTIAE:
        raise TranslationRefused(
            "minutiae_below_upstream_minimum", f"{count} < {OPENAFIS_MINIMUM_MINUTIAE}"
        )
    if count > OPENAFIS_MAXIMUM_MINUTIAE:
        # Deliberately not the top 128 by quality. Choosing which minutiae survive
        # would be a selection rule fpbench invented, and the score would stop
        # being what MINDTCT and OpenAFIS produce between them.
        raise TranslationRefused(
            "minutiae_above_upstream_maximum", f"{count} > {OPENAFIS_MAXIMUM_MINUTIAE}"
        )

    lines = [f"{width},{height}"]
    for minutia in minutiae:
        # x and y verbatim; theta to radians and nothing else. Nine decimals is
        # far more than OpenAFIS needs — it reads a float and immediately rounds
        # back to whole degrees — and guarantees the round trip is exact.
        radians = minutia.theta * math.pi / 180.0
        lines.append(f"{minutia_type},{minutia.x},{minutia.y},{radians:.9f}")

    return TranslatedTemplate(text="\n".join(lines) + "\n", minutiae_count=count)
