"""The comparator's contract, and the one rule for serializing a float."""

from __future__ import annotations

from decimal import Decimal

import pytest

from fpbench.core.flx_errors import FlxScoreError
from fpbench.flx import identity
from fpbench.flx.score import (
    SCORE_FORMULA,
    build_score_profile,
    build_score_serialization_profile,
    canonical_decimal_text,
    decimal_from_scalar,
    decimal_from_worker_text,
    score_from_worker,
    verify_nominal_range,
)

pytestmark = pytest.mark.stage8b_contract


def test_the_formula_is_the_sum_of_two_branch_dot_products() -> None:
    assert SCORE_FORMULA == (
        "dot(texture_left, texture_right) + dot(minutia_left, minutia_right)"
    )


def test_the_canonical_text_round_trips_the_scalar_exactly() -> None:
    for value in (0.1, 1.0, -2.0, 1.9999999999999998, 5e-324, 1.2345678901234567):
        assert float(canonical_decimal_text(value)) == value


def test_the_rule_does_not_expose_the_binary_expansion() -> None:
    # Decimal(0.1) is 0.1000000000000000055511151231257827021181583404541015625:
    # faithful, unreadable, and it makes two identical runs look different.
    # Seventeen digits is not the shortest round-tripping form — repr gives
    # "0.1" — but it is the count that always suffices, which is what the
    # frozen rule asks for.
    assert str(decimal_from_scalar(0.1)) == "0.10000000000000001"
    assert decimal_from_scalar(0.1) != Decimal(0.1)
    assert len(str(Decimal(0.1))) > 20


def test_the_rule_does_not_round_away_information() -> None:
    value = 1.2345678901234567
    assert float(decimal_from_scalar(value)) == value


def test_a_non_finite_scalar_is_refused() -> None:
    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(FlxScoreError, match="must be finite"):
            decimal_from_scalar(value)


def test_a_non_float_scalar_is_refused() -> None:
    with pytest.raises(FlxScoreError, match="expected an IEEE scalar"):
        canonical_decimal_text(Decimal("1"))


def test_worker_text_that_is_not_a_decimal_is_refused() -> None:
    with pytest.raises(FlxScoreError, match="not a canonical decimal score"):
        decimal_from_worker_text("about two")


def test_a_non_finite_worker_text_is_refused() -> None:
    for text in ("nan", "inf", "-inf", "Infinity"):
        with pytest.raises(FlxScoreError, match="must be finite"):
            decimal_from_worker_text(text)


def test_the_nominal_range_is_enforced() -> None:
    assert verify_nominal_range(Decimal("2")) == Decimal("2")
    assert verify_nominal_range(Decimal("-2")) == Decimal("-2")
    for outside in ("2.001", "-2.001", "17"):
        with pytest.raises(FlxScoreError, match="outside the nominal range"):
            verify_nominal_range(Decimal(outside))


def test_the_range_allows_float32_normalization_slack_but_not_more() -> None:
    # A SELF comparison lands at 2 + 2**-23 because each branch is normalized
    # in float32; the allowance is 2**-21, derived from the format.
    assert verify_nominal_range(Decimal("2.0000001192092896"))
    tolerance = Decimal(repr(identity.SCORE_RANGE_TOLERANCE))
    assert verify_nominal_range(Decimal("2") + tolerance)
    with pytest.raises(FlxScoreError, match="normalization allowance"):
        verify_nominal_range(Decimal("2") + tolerance * 2)


def test_the_range_allowance_is_not_the_determinism_tolerance() -> None:
    # Two runs of the same comparison must still agree bit for bit.
    assert identity.NUMERIC_TOLERANCE == "0"
    assert identity.SCORE_RANGE_TOLERANCE > 0


def test_a_python_float_is_refused_where_a_decimal_is_required() -> None:
    with pytest.raises(FlxScoreError, match="returns Decimal, not float"):
        verify_nominal_range(1.5)  # type: ignore[arg-type]


def test_a_reported_total_that_is_not_the_branch_sum_is_refused() -> None:
    # A hidden weighting would show up exactly here.
    with pytest.raises(FlxScoreError, match="not the sum of its branch scores"):
        score_from_worker(
            {"texture_score": "0.5", "minutia_score": "0.25", "raw_score": "0.65"}
        )


def test_an_equal_branch_sum_is_accepted_and_returned_as_decimal() -> None:
    score = score_from_worker(
        {"texture_score": "0.5", "minutia_score": "0.25", "raw_score": "0.75"}
    )

    assert isinstance(score, Decimal)
    assert score == Decimal("0.75")


def test_a_score_outside_the_range_is_refused_even_if_the_parts_agree() -> None:
    with pytest.raises(FlxScoreError, match="outside the nominal range"):
        score_from_worker(
            {"texture_score": "1.6", "minutia_score": "1.6", "raw_score": "3.2"}
        )


def test_the_serialization_profile_states_the_frozen_rule() -> None:
    profile = build_score_serialization_profile()

    assert profile.profile_id == identity.SCORE_SERIALIZATION_PROFILE_ID
    assert profile.significant_digits == 17
    assert profile.rounding_before_storage is False


def test_the_score_profile_carries_no_hidden_machinery() -> None:
    profile = build_score_profile()

    assert profile.profile_id == identity.SCORE_PROFILE_ID
    assert profile.branch_weights == ("1", "1")
    assert profile.score_direction == "higher_is_more_similar"
    assert (profile.nominal_minimum, profile.nominal_maximum) == ("-2", "2")
    assert profile.returns_decimal is True
    assert profile.symmetric is True
    for field in ("calibration", "normalization", "threshold", "fallback_matcher",
                  "quality_adjustment", "realignment"):
        assert getattr(profile, field) == "none", field


def test_the_score_profile_is_stable() -> None:
    assert build_score_profile().fingerprint == build_score_profile().fingerprint
