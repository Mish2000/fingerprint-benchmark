"""Explicit existing-P2-runtime regression checks; synthetic pixels only."""

import ast
import copy
import inspect
import math
import os
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(os.environ["FPBENCH_L3_METHOD_DIR"]) / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import ridge
from analysis import scale_policy
from fingerprint_new_method import experiment004_transfer as original

PERIODS = (16, 20, 24, 34, 46)
ANGLES = (0, 15, 30, 40, 45, 60, 75, 90, -15, -30, -45, -60)


def stripes(period, angle, shape=(256, 256), amplitude=100):
    y, x = np.indices(shape, dtype=np.float64)
    theta = math.radians(angle)
    return (
        np.rint(
            127.5
            + amplitude
            * np.cos(2 * np.pi * (x * np.cos(theta) + y * np.sin(theta)) / period)
        )
        .clip(0, 255)
        .astype(np.uint8)
    )


@pytest.mark.parametrize("period", PERIODS)
@pytest.mark.parametrize("angle", ANGLES)
def test_corrected_diagonal_and_axis_periods(period, angle):
    result = ridge.estimate_tile_ridge_period(stripes(period, angle))
    assert result is not None and abs(result[0] - period) <= 1


def test_original_bug_is_reproduced_without_mutating_legacy_module():
    before = original.estimate_tile_ridge_period
    correct = sum(
        (value := before(stripes(p, a))) is not None and abs(value[0] - p) <= 1
        for p in PERIODS
        for a in ANGLES
    )
    assert correct == 10
    assert original.estimate_tile_ridge_period is before
    assert original.estimate_tile_ridge_period(stripes(20, 45)) is None


def test_tile_implementation_diff_is_exactly_the_rotation_sign():
    old = ast.parse(inspect.getsource(original.estimate_tile_ridge_period))
    expected = copy.deepcopy(old)
    changes = 0
    for node in ast.walk(expected):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "rotation_degrees" for t in node.targets
        ):
            node.value = ast.parse("math.degrees(orientation) - 90.0", mode="eval").body
            changes += 1
    assert changes == 1
    assert ast.dump(expected) == ast.dump(
        ast.parse(inspect.getsource(ridge.estimate_tile_ridge_period))
    )


@pytest.mark.parametrize(
    "image", [np.full((256, 256), 128, dtype=np.uint8), stripes(20, -30, amplitude=5)]
)
def test_blank_and_weak_tile_guards_are_preserved(image):
    assert ridge.estimate_tile_ridge_period(image) is None
    assert original.estimate_tile_ridge_period(image) is None


def test_blank_image_and_minimum_tile_guard():
    assert (
        ridge.estimate_ridge_period(np.full((512, 512), 128, np.uint8))["status"]
        == "UNRELIABLE_TOO_FEW_TILES"
    )
    assert (
        ridge.estimate_ridge_period(stripes(20, 30))["status"]
        == "UNRELIABLE_TOO_FEW_TILES"
    )
    assert (
        ridge.aggregate([10, 20, 30, 40, 50], [1] * 5, 5).status
        == "UNRELIABLE_DISPERSION"
    )


def test_fixed_image_aggregation_and_unchanged_resize_on_non_square_pixels():
    gray = stripes(20, -30, (537, 719))
    estimate = ridge.estimate_ridge_period(gray)
    assert estimate["status"] == "OK" and estimate["period_px"] == 20
    assert estimate["candidate_tiles"] == 20
    historical = scale_policy(estimate, 34.0, (0.2, 1.5))
    assert historical["factor"] == 1.7 and historical["status"] != "OK"
    with pytest.raises(ValueError):
        ridge.resize_from_policy(gray, historical)
    for target in (16, 34):
        policy = scale_policy(estimate, target, (0.2, 3.0))
        factor = target / 20
        expected = cv2.resize(
            gray,
            None,
            fx=factor,
            fy=factor,
            interpolation=cv2.INTER_AREA if factor < 1 else cv2.INTER_CUBIC,
        )
        np.testing.assert_array_equal(ridge.resize_from_policy(gray, policy), expected)
