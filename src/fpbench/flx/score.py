"""The raw score, and the one rule for turning a machine float into a Decimal.

Two dot products added together.  No weights, no calibration, no normalization,
no threshold, no fallback.  Everything a matcher usually does after this point
happens in a later stage, or not at all (docs/adr/0065).

The serialization rule matters more than it looks.  A Python ``float`` handed
straight to ``Decimal`` produces the exact binary value —
``Decimal(0.1)`` is ``0.1000000000000000055511151231257827021181583404541015625`` —
which is faithful and unreadable, and which makes two runs that agree to the
last bit look different in a diff.  Rounding, on the other hand, throws away
bits that a later stage may need.  The rule takes the middle: a canonical
17-significant-digit string — not the shortest round-tripping form, which is
what ``repr`` gives, but the digit count that is always sufficient to recover
an IEEE double exactly — and then a Decimal built from that string.
"""

from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation
from typing import Mapping

from fpbench.core.flx_errors import FlxScoreError
from fpbench.core.flx_models import (
    STAGE8B_SCHEMA_VERSION,
    FlxScoreProfile,
    FlxScoreSerializationProfile,
)
from fpbench.flx import identity

__all__ = [
    "SCORE_FORMULA",
    "canonical_decimal_text",
    "decimal_from_scalar",
    "decimal_from_worker_text",
    "verify_nominal_range",
    "build_score_serialization_profile",
    "build_score_profile",
]

SCORE_FORMULA = "dot(texture_left, texture_right) + dot(minutia_left, minutia_right)"


def canonical_decimal_text(value: float) -> str:
    """Step 2 of the rule: the canonical 17-significant-digit decimal string."""
    if not isinstance(value, float):
        raise FlxScoreError(f"expected an IEEE scalar, got {type(value).__name__}")
    if not math.isfinite(value):
        raise FlxScoreError(f"a raw score must be finite, got {value!r}")
    return f"{value:.{identity.DECIMAL_SIGNIFICANT_DIGITS}g}"


def decimal_from_scalar(value: float) -> Decimal:
    """The whole rule: preserve the scalar, canonicalize, then construct."""
    return decimal_from_worker_text(canonical_decimal_text(value))


def decimal_from_worker_text(text: str) -> Decimal:
    """Step 3, applied to the text the pinned comparator's scalar produced."""
    try:
        score = Decimal(str(text))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise FlxScoreError(f"{text!r} is not a canonical decimal score") from exc
    if not score.is_finite():
        raise FlxScoreError(f"a raw score must be finite, got {text!r}")
    return score


def verify_nominal_range(score: Decimal) -> Decimal:
    """Check the declared range, allowing float32 normalization slack.

    [-2, 2] is the range for two exactly-unit vectors.  Normalizing in float32
    leaves each norm within an ulp of one, so a SELF comparison lands just
    above 2.  The allowance is bounded and derived from the format; the score
    itself is never clamped, because a later stage may need the bits.
    """
    if not isinstance(score, Decimal):
        raise FlxScoreError(
            f"the public compare API returns Decimal, not {type(score).__name__}"
        )
    tolerance = Decimal(identity.SCORE_RANGE_VALIDATION_TOLERANCE)
    minimum = Decimal(identity.SCORE_MINIMUM) - tolerance
    maximum = Decimal(identity.SCORE_MAXIMUM) + tolerance
    if not minimum <= score <= maximum:
        raise FlxScoreError(
            f"raw score {score} is outside the nominal range "
            f"[{identity.SCORE_MINIMUM}, {identity.SCORE_MAXIMUM}] by more than the "
            f"{identity.SCORE_RANGE_VALIDATION_TOLERANCE} float32 normalization "
            f"allowance under {identity.SCORE_RANGE_VALIDATION_POLICY}"
        )
    return score


def build_score_serialization_profile() -> FlxScoreSerializationProfile:
    return FlxScoreSerializationProfile.create(
        schema_version=STAGE8B_SCHEMA_VERSION,
        profile_id=identity.SCORE_SERIALIZATION_PROFILE_ID,
        significant_digits=identity.DECIMAL_SIGNIFICANT_DIGITS,
        intermediate_form=(
            "canonical decimal string with 17 significant digits, the digit count "
            "that always suffices to recover an IEEE double exactly"
        ),
        constructed_from="the scalar returned by the pinned numpy.dot comparator",
        rounding_before_storage=False,
    )


def build_score_profile() -> FlxScoreProfile:
    return FlxScoreProfile.create(
        schema_version=STAGE8B_SCHEMA_VERSION,
        profile_id=identity.SCORE_PROFILE_ID,
        formula=SCORE_FORMULA,
        score_direction=identity.SCORE_DIRECTION,
        nominal_minimum=identity.SCORE_MINIMUM,
        nominal_maximum=identity.SCORE_MAXIMUM,
        range_validation_tolerance=identity.SCORE_RANGE_VALIDATION_TOLERANCE,
        range_validation_policy=identity.SCORE_RANGE_VALIDATION_POLICY,
        branch_weights=("1", "1"),
        serialization=build_score_serialization_profile(),
        returns_decimal=True,
        symmetric=True,
        calibration="none",
        normalization="none",
        threshold="none",
        fallback_matcher="none",
        quality_adjustment="none",
        realignment="none",
    )


def score_from_worker(payload: Mapping[str, object]) -> Decimal:
    """Read the comparator's answer, and check the parts add up to the whole."""
    texture = decimal_from_worker_text(str(payload["texture_score"]))
    minutia = decimal_from_worker_text(str(payload["minutia_score"]))
    raw = decimal_from_worker_text(str(payload["raw_score"]))
    # The branches carry weight one each; if the reported total is not their
    # sum, something between the dot products and here applied a weighting.
    if canonical_decimal_text(float(texture) + float(minutia)) != canonical_decimal_text(
        float(raw)
    ):
        raise FlxScoreError(
            f"the reported raw score {raw} is not the sum of its branch scores "
            f"({texture} + {minutia}); this profile adds no weighting"
        )
    return verify_nominal_range(raw)
