"""The declared transform: every question answered, and the parity rule tested."""

from __future__ import annotations

import pytest

from fpbench.core.flx_errors import FlxPreprocessingError, FlxRepresentationError
from fpbench.core.flx_models import REQUIRED_PREPROCESSING_STEPS
from fpbench.flx import identity
from fpbench.flx.preprocessing import (
    PREPROCESSING_STEPS,
    build_preprocessing_profile,
    expected_padding,
    verify_model_input,
)
from fpbench.flx.representation import ModelInput

pytestmark = pytest.mark.stage8b_contract

SIDE = identity.MODEL_INPUT_SIDE
VALUES = b"\x00" * (4 * SIDE * SIDE)


def _model_input(**changes) -> ModelInput:
    claims = dict(
        shape=(1, SIDE, SIDE),
        dtype="float32",
        values=VALUES,
        source_width=381,
        source_height=891,
        padded_side=891,
        pad_left=255,
        pad_top=0,
        pad_right=255,
        pad_bottom=0,
        minimum=0.0,
        maximum=1.0,
    )
    claims.update(changes)
    return ModelInput(**claims)


def test_the_profile_answers_every_required_question_in_order() -> None:
    profile = build_preprocessing_profile()

    assert tuple(step.step_id for step in profile.steps) == REQUIRED_PREPROCESSING_STEPS
    assert len(PREPROCESSING_STEPS) == len(REQUIRED_PREPROCESSING_STEPS)
    for step in profile.steps:
        assert step.action and step.rationale


def test_the_profile_states_the_frozen_transform() -> None:
    profile = build_preprocessing_profile()

    assert profile.profile_id == identity.PREPROCESSING_PROFILE_ID
    assert profile.output_shape == (1, SIDE, SIDE)
    assert profile.output_dtype == "float32"
    assert (profile.value_minimum, profile.value_maximum) == ("0", "1")
    assert profile.padding_fill_value == 255
    assert profile.interpolation == "torchvision.transforms.InterpolationMode.BILINEAR"
    assert profile.antialias is True
    assert profile.dataset_independent and profile.subject_independent


def test_the_profile_is_stable() -> None:
    assert build_preprocessing_profile().fingerprint == build_preprocessing_profile().fingerprint


@pytest.mark.parametrize(
    ("width", "height", "expected"),
    [
        # The canonical shape: an even difference, split exactly.
        (381, 891, {"side": 891, "left": 255, "top": 0, "right": 255, "bottom": 0}),
        # Odd differences: the extra pixel goes right and bottom, both ways round.
        (100, 201, {"side": 201, "left": 50, "top": 0, "right": 51, "bottom": 0}),
        (201, 100, {"side": 201, "left": 0, "top": 50, "right": 0, "bottom": 51}),
        # Wider than tall: padding lands on top and bottom.
        (240, 137, {"side": 240, "left": 0, "top": 51, "right": 0, "bottom": 52}),
        # Already square: nothing is added.
        (299, 299, {"side": 299, "left": 0, "top": 0, "right": 0, "bottom": 0}),
        (1, 2, {"side": 2, "left": 0, "top": 0, "right": 1, "bottom": 0}),
    ],
)
def test_the_padding_parity_rule_is_fixed_in_both_directions(width, height, expected) -> None:
    assert dict(expected_padding(width, height)) == expected


def test_padding_always_produces_a_square() -> None:
    for width in range(1, 40):
        for height in range(1, 40):
            padding = expected_padding(width, height)
            assert width + padding["left"] + padding["right"] == padding["side"]
            assert height + padding["top"] + padding["bottom"] == padding["side"]


def test_upstreams_rule_would_not_have_produced_a_square() -> None:
    # docs/adr/0071: upstream applies the same floor to both sides and then
    # asserts squareness, which cannot hold for an odd difference.
    width, height = 100, 201
    upstream_pad = int((height - width) / 2)
    assert width + 2 * upstream_pad != height

    padding = expected_padding(width, height)
    assert width + padding["left"] + padding["right"] == height


def test_a_degenerate_source_size_is_refused() -> None:
    with pytest.raises(FlxPreprocessingError, match="cannot be"):
        expected_padding(0, 10)


def test_a_model_input_matching_the_frozen_rule_is_accepted() -> None:
    verify_model_input(_model_input())


def test_padding_the_worker_did_not_place_where_the_rule_says_is_refused() -> None:
    with pytest.raises(FlxPreprocessingError, match="padding placement is"):
        verify_model_input(_model_input(pad_left=256, pad_right=254))


def test_a_value_outside_the_unit_range_is_refused() -> None:
    with pytest.raises(FlxRepresentationError, match="escapes"):
        _model_input(minimum=-0.1)


def test_a_wrong_output_shape_is_refused() -> None:
    with pytest.raises(FlxRepresentationError, match="model input shape"):
        _model_input(shape=(3, SIDE, SIDE))


def test_a_wrong_dtype_is_refused() -> None:
    with pytest.raises(FlxRepresentationError, match="model input dtype"):
        _model_input(dtype="float64")


def test_a_short_tensor_is_refused() -> None:
    with pytest.raises(FlxRepresentationError, match="carries"):
        _model_input(values=b"\x00" * 16)


def test_the_transform_declares_no_normalization_or_channel_replication() -> None:
    actions = {step_id: action for step_id, action, _ in PREPROCESSING_STEPS}
    assert actions["normalization"].startswith("none")
    assert actions["channel_replication"] == "none"
    assert actions["crop"] == "no crop"
    assert actions["polarity"].startswith("no inversion")
    assert actions["re_encoding"].startswith("none")
