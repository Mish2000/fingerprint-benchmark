"""The frozen Stage 20A MINDTCT-to-MCC input and score route.

The official MCC SDK v2.0 has no raster-image entry point. Its narrowest public
template API accepts the original image geometry plus an array of ``Minutia``
values containing only ``X``, ``Y`` and ``Direction``. This module records the
mechanical representation change from the already-frozen MINDTCT 5.0.0 XYT
output. It is a qualification contract, not a production adapter.

No rule here was selected from an SD300 score. The two coordinate systems are
published by their respective upstreams:

* MINDTCT's default XYT is bottom-left origin, x right, with direction in degrees
  counter-clockwise from east; ``xytreps.c`` writes ``y = image_height - y``.
* MCC's minutiae input is upper-left origin, x right/y down, with direction in
  radians counter-clockwise from the horizontal axis to the right (SDK manual,
  Appendix A).

The inverse origin change is therefore the same exact subtraction, while the
physical direction needs only the documented degrees-to-radians unit change.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from fpbench.adapters.nbis.xyt import NbisMinutia

__all__ = [
    "CANDIDATE_ID",
    "OUTCOME",
    "MCC_INPUT_RESOLUTION",
    "TEMPLATE_API",
    "MATCH_API",
    "FIELD_CONTRACT",
    "FORBIDDEN_ROUTE_OPERATIONS",
    "MccInputMinutia",
    "MccTemplateInput",
    "MccTranslationRefused",
    "translate_xyt_to_mcc_input",
]


CANDIDATE_ID = "nbis_mindtct_mcc_sdk_v2"
OUTCOME = "MINDTCT_MCC_SDK_V2_ROUTE_PASS"
MCC_INPUT_RESOLUTION = 500

TEMPLATE_API = (
    "System.Object BioLab.Biometrics.Mcc.Sdk.MccSdk.CreateMccTemplate("
    "System.Int32,System.Int32,System.Int32,BioLab.Biometrics.Mcc.Sdk.Minutia[])"
)
MATCH_API = (
    "System.Double BioLab.Biometrics.Mcc.Sdk.MccSdk.MatchMccTemplates("
    "System.Object,System.Object)"
)

FIELD_CONTRACT = {
    "x": "DIRECT",
    "y": "DERIVED_MECHANICALLY",
    "theta": "DERIVED_MECHANICALLY",
    "quality": "IGNORED_BY_MCC",
    "width": "DIRECT",
    "height": "DIRECT",
    "resolution": "DIRECT",
    "minutia_type": "IGNORED_BY_MCC",
    "finger_position": "IGNORED_BY_MCC",
}

FORBIDDEN_ROUTE_OPERATIONS = (
    "best-N selection",
    "central-minutiae selection",
    "crop",
    "deduplication",
    "enhancement",
    "quality cutoff",
    "resize",
    "rotation optimization",
    "sorting",
)


class MccTranslationRefused(ValueError):
    """An XYT value cannot be represented by the documented MCC input route."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True, slots=True)
class MccInputMinutia:
    """Exactly the three fields exposed by ``MccSdk.Minutia``."""

    x: int
    y: int
    direction: float


@dataclass(frozen=True, slots=True)
class MccTemplateInput:
    """Arguments for the official in-memory MCC template-construction API."""

    image_width: int
    image_height: int
    image_resolution: int
    minutiae: tuple[MccInputMinutia, ...]


def translate_xyt_to_mcc_input(
    minutiae: Sequence[NbisMinutia], *, width: int, height: int
) -> MccTemplateInput:
    """Translate every MINDTCT XYT minutia into the official MCC struct.

    The function intentionally has no cutoff, limit, ranking, type, DPI, angle
    convention, or configuration parameter. Canonical 500 ppi is part of this
    route's identity. Every accepted input minutia survives in original order.
    """
    if width <= 0 or height <= 0:
        raise MccTranslationRefused(
            "invalid_raster_dimensions", f"{width}x{height}"
        )

    translated: list[MccInputMinutia] = []
    for index, minutia in enumerate(minutiae, start=1):
        if not 0 <= minutia.x < width or not 0 <= minutia.y < height:
            raise MccTranslationRefused(
                "minutia_outside_mindtct_raster", f"minutia {index}"
            )
        if not 0 <= minutia.theta <= 359:
            raise MccTranslationRefused(
                "invalid_mindtct_direction", f"minutia {index}"
            )

        translated.append(
            MccInputMinutia(
                x=minutia.x,
                # Exact inverse of NBIS xytreps.c's `y = image_height - y`.
                # No border clamp is added; the SDK remains the authority on its
                # own accepted coordinate domain, which it does not document.
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
