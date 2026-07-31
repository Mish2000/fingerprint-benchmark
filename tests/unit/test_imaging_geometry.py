"""Dimension arithmetic, where a rounding rule decides a pixel.

Small numbers, and none of it is decorative. A 1001-pixel axis at 1000 ppi is
exactly 500.5 output pixels, and Python's ``round()`` answers 500 because it
breaks ties to even. Half-up answers 501. Both are defensible rules; having
*two* rules is not, and the profile names one.
"""

from __future__ import annotations

import pytest

from fpbench.core.imaging_models import (
    dimension_rounding_error_halves,
    extent_error_ppm,
    scale_dimension,
)

pytestmark = [pytest.mark.imaging, pytest.mark.canonical500]


def test_target_equal_to_source_keeps_every_dimension():
    for pixels in (1, 2, 999, 1000, 1001, 4096):
        assert scale_dimension(pixels, target_ppi=500, source_ppi=500) == pixels


@pytest.mark.parametrize(
    ("pixels", "expected"),
    [(1000, 500), (800, 400), (2, 1), (4096, 2048)],
)
def test_halving_an_even_dimension_is_exact(pixels, expected):
    assert scale_dimension(pixels, target_ppi=500, source_ppi=1000) == expected


@pytest.mark.parametrize(
    ("pixels", "expected"),
    [(1001, 501), (999, 500), (41, 21), (27, 14), (3, 2)],
)
def test_halving_an_odd_dimension_rounds_up(pixels, expected):
    """``.5`` goes up, always.

    ``round(500.5)`` is 500 and ``round(499.5)`` is 500 — two neighbouring
    inputs, the same output, by a rule nobody wrote down. Half-up gives 501 and
    500.
    """
    assert scale_dimension(pixels, target_ppi=500, source_ppi=1000) == expected


@pytest.mark.parametrize(
    ("pixels", "expected"),
    [
        (1000, 250),  # exact
        (1001, 250),  # .25 rounds down
        (1002, 251),  # .50 rounds up
        (1003, 251),  # .75 rounds up
        (1006, 252),  # .50 again, at a different parity
        (65, 16),  # .25
    ],
)
def test_quartering_covers_every_remainder(pixels, expected):
    assert scale_dimension(pixels, target_ppi=500, source_ppi=2000) == expected


def test_no_python_bankers_rounding_anywhere():
    """The property, stated directly over every tie in a wide range.

    Python rounds half to even, so exactly half of these would come out one
    pixel short under ``round()``. Asserting the rule rather than a table means a
    future refactor cannot quietly reintroduce it.
    """
    disagreements = 0
    for pixels in range(2, 4000, 2):
        # An odd multiple of the half-step is a tie under 4x reduction.
        tied = pixels * 2 + 2
        exact = tied * 500 / 2000
        if exact != int(exact) + 0.5:
            continue
        expected_half_up = int(exact) + 1
        assert scale_dimension(tied, target_ppi=500, source_ppi=2000) == expected_half_up
        if round(exact) != expected_half_up:
            disagreements += 1
    assert disagreements > 0, "the test found no tie where the two rules differ"


@pytest.mark.parametrize("pixels", [0, -1, -1000])
def test_a_non_positive_dimension_is_rejected(pixels):
    with pytest.raises(ValueError, match="source_pixels"):
        scale_dimension(pixels, target_ppi=500, source_ppi=1000)


@pytest.mark.parametrize(("target", "source"), [(0, 1000), (500, 0), (-500, 1000)])
def test_a_non_positive_resolution_is_rejected(target, source):
    with pytest.raises(ValueError):
        scale_dimension(100, target_ppi=target, source_ppi=source)


@pytest.mark.parametrize("value", [500.0, "500", True, None])
def test_a_non_integer_is_rejected_rather_than_coerced(value):
    """``500.0`` is not ``500`` here.

    Coercing it would let a JSON round trip change an integrity-bearing field
    while the object it rebuilt still looked right.
    """
    with pytest.raises(ValueError, match="exact integer"):
        scale_dimension(value, target_ppi=500, source_ppi=1000)
    with pytest.raises(ValueError, match="exact integer"):
        scale_dimension(1000, target_ppi=value, source_ppi=1000)
    with pytest.raises(ValueError, match="exact integer"):
        scale_dimension(1000, target_ppi=500, source_ppi=value)


def test_rounding_never_moves_an_axis_by_more_than_half_an_output_pixel():
    for source_ppi in (1000, 2000):
        # Below this an axis rounds away entirely, which is refused rather than
        # rounded — see the test below.
        smallest = source_ppi // 500 // 2 + 1
        for pixels in range(smallest, 600):
            output = scale_dimension(pixels, target_ppi=500, source_ppi=source_ppi)
            error = dimension_rounding_error_halves(
                pixels, output, target_ppi=500, source_ppi=source_ppi
            )
            assert error <= source_ppi


def test_an_axis_that_would_round_away_is_refused_rather_than_clamped():
    """A one-pixel axis at 2000 ppi is a quarter of an output pixel.

    Clamping it to 1 would be inventing a pixel; rounding it to 0 would be
    producing an image with no area. Neither is a resampling, so it raises.
    """
    with pytest.raises(ValueError, match="at least one pixel"):
        scale_dimension(1, target_ppi=500, source_ppi=2000)


def test_an_exact_scale_preserves_the_physical_extent_exactly():
    assert extent_error_ppm(1000, 500, target_ppi=500, source_ppi=1000) == 0
    assert extent_error_ppm(1000, 250, target_ppi=500, source_ppi=2000) == 0
    assert extent_error_ppm(64, 64, target_ppi=500, source_ppi=500) == 0


def test_a_rounded_scale_records_the_extent_it_actually_moved():
    """41 px at 1000 ppi is 0.0410 in; 21 px at 500 ppi is 0.0420 in.

    A 2.44% stretch, which is what rounding a 20.5-pixel axis up to 21 costs. It
    is recorded rather than hidden, because a reader who wants to know whether a
    small image was distorted should not have to redo the arithmetic.
    """
    assert extent_error_ppm(41, 21, target_ppi=500, source_ppi=1000) == 24390
    assert extent_error_ppm(1006, 252, target_ppi=500, source_ppi=2000) == 1988
