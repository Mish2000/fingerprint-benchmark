"""MINDTCT's XYT into the official MCC minutiae input, and nothing else.

Three rules, all of them mechanical, all of them settled by Stage 20A from the
two upstreams' own published conventions rather than from anything SD300 did:

.. code-block:: text

    x_mcc         = x_xyt
    y_mcc         = image_height - y_xyt
    direction_mcc = theta_xyt_degrees * pi / 180

MINDTCT writes XYT with a bottom-left origin — ``xytreps.c`` emits
``y = image_height - y`` — and a direction in degrees counter-clockwise from
east. The MCC SDK documents (Appendix A) an upper-left origin with *y* increasing
downward and a direction in radians counter-clockwise from the same axis. The
origin change is therefore the identical subtraction run backwards, and the
angle needs only its documented unit change. Neither was chosen; both were read.

**Quality, minutia type and finger position are dropped because the API has
nowhere to put them.** ``MccSdk.Minutia`` is a struct of exactly ``X:int``,
``Y:int`` and ``Direction:double``. This is not fpbench electing to ignore
information — it is the surface the SDK exposes.

**Every minutia survives, in MINDTCT's order.** No cutoff, no top-N, no sort, no
deduplication, no rotation search. A translator that quietly kept the best 128
would be a second minutiae filter nobody asked for, and the scores would stop
being MCC's answer about NBIS's minutiae.

This module is the adapter's own copy of the rule. The qualification contract in
``fpbench.experiments.stage20a_mcc_contract`` is frozen by Stage 20A's published
marker and lives above the adapter layer, so it cannot be imported from here;
``tests/test_stage20b_contract.py`` asserts the two agree exactly instead.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from fpbench.adapters.mcc.identity import BRIDGE_PROTOCOL, MCC_INPUT_RESOLUTION
from fpbench.adapters.nbis.xyt import NbisMinutia

__all__ = [
    "MccInputMinutia",
    "MccTemplateInput",
    "MccTranslationRefused",
    "translate_xyt_to_mcc_input",
    "render_bridge_payload",
]


class MccTranslationRefused(ValueError):
    """An XYT value cannot be represented by the documented MCC input route.

    Carries a short ``reason`` so the failure mapping can say *what* was wrong
    without putting a path or anybody's minutia into a stored result.
    """

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True, slots=True)
class MccInputMinutia:
    """Exactly the three fields ``MccSdk.Minutia`` exposes."""

    x: int
    y: int
    direction: float


@dataclass(frozen=True, slots=True)
class MccTemplateInput:
    """One side, as ``CreateMccTemplate(width, height, resolution, minutiae)``."""

    image_width: int
    image_height: int
    image_resolution: int
    minutiae: tuple[MccInputMinutia, ...]


def translate_xyt_to_mcc_input(
    minutiae: Sequence[NbisMinutia], *, width: int, height: int
) -> MccTemplateInput:
    """Translate every MINDTCT minutia into the official MCC struct.

    Args:
        minutiae: MINDTCT's own output, parsed and in its own order.
        width: the canonical raster's width, passed straight through.
        height: the canonical raster's height, which the *y* rule also needs.

    Raises:
        MccTranslationRefused: the raster has no area, a minutia lies outside it,
            or a direction is not one MINDTCT could have written. Refused rather
            than repaired: a coordinate this route cannot represent is an
            extraction fact, and clamping it would invent a minutia.
    """
    if width <= 0 or height <= 0:
        raise MccTranslationRefused("invalid_raster_dimensions", f"{width}x{height}")

    translated: list[MccInputMinutia] = []
    for index, minutia in enumerate(minutiae, start=1):
        if not 0 <= minutia.x < width or not 0 <= minutia.y < height:
            raise MccTranslationRefused(
                "minutia_outside_mindtct_raster", f"minutia {index}"
            )
        if not 0 <= minutia.theta <= 359:
            raise MccTranslationRefused("invalid_mindtct_direction", f"minutia {index}")

        translated.append(
            MccInputMinutia(
                x=minutia.x,
                # The exact inverse of xytreps.c's `y = image_height - y`. No
                # border clamp: the SDK stays the authority on the coordinate
                # domain it accepts, which it does not document.
                y=height - minutia.y,
                direction=minutia.theta * math.pi / 180.0,
            )
        )

    return MccTemplateInput(
        image_width=width,
        image_height=height,
        image_resolution=MCC_INPUT_RESOLUTION,
        minutiae=tuple(translated),
    )


def render_bridge_payload(left: MccTemplateInput, right: MccTemplateInput) -> str:
    """The two sides as the bridge's wire format.

    Deliberately the SDK's own documented minutiae text format twice over —
    width, height, resolution, count, then one ``x y direction`` row each — so
    that a payload can be read against Bologna's own ``SampleMinutiae`` examples
    rather than against a format this project invented.

    ``repr`` is what writes each direction: it is Python's shortest round-tripping
    form, and ``Double.TryParse`` on the other side recovers the identical
    ``System.Double``. A fixed number of decimal places would quietly hand the
    matcher a different angle from the one computed here.
    """
    lines = [BRIDGE_PROTOCOL]
    for label, side in (("LEFT", left), ("RIGHT", right)):
        lines.append(
            f"{label} {side.image_width} {side.image_height} "
            f"{side.image_resolution} {len(side.minutiae)}"
        )
        lines.extend(
            f"{minutia.x} {minutia.y} {minutia.direction!r}"
            for minutia in side.minutiae
        )
    return "\n".join(lines) + "\n"
