"""The declared transform, as a document and as a checkable contract.

The nineteen steps below are the profile.  They are not documentation of the
code: ``FlxPreprocessingProfile`` refuses to exist unless every one of them is
answered, in order, which is what makes "we used the default" impossible to
write down (docs/adr/0071).

The padding parity rule and the expected padding placement are also computed
here, in the parent, so the worker's answer can be checked against arithmetic
the parent did independently.
"""

from __future__ import annotations

from typing import Mapping

from fpbench.core.flx_errors import FlxPreprocessingError
from fpbench.core.flx_models import (
    REQUIRED_PREPROCESSING_STEPS,
    STAGE8B_SCHEMA_VERSION,
    FlxPreprocessingProfile,
    FlxPreprocessingStep,
)
from fpbench.flx import identity
from fpbench.flx.representation import ModelInput

__all__ = [
    "PREPROCESSING_STEPS",
    "expected_padding",
    "build_preprocessing_profile",
    "verify_model_input",
]

#: One answer per question the transform could otherwise answer silently.
PREPROCESSING_STEPS: tuple[tuple[str, str, str], ...] = (
    (
        "decode",
        "decode the PNG container directly: signature, per-chunk CRC, IHDR, IEND",
        "a decoder handed a paletted or gamma-tagged file returns a grayscale raster "
        "anyway, having applied a colour policy this project never chose",
    ),
    (
        "channel_count",
        "require exactly one channel (PNG colour type 0)",
        "a three-channel source would be silently averaged by most loaders",
    ),
    (
        "bit_depth",
        "require exactly 8 bits per sample; 1, 2, 4 and 16 are refused",
        "libpng converts 16-bit down without saying so, which changes the pixels",
    ),
    (
        "polarity",
        "no inversion: ridges stay dark on a light background",
        "upstream trained on this polarity and nothing in the artifact declares another",
    ),
    ("crop", "no crop", "every upstream crop rule is corpus-specific (SFinGe, MCYT)"),
    (
        "localization",
        "none: this variant has no localization branch",
        "the checkpoint contains no localization weights",
    ),
    (
        "alignment",
        "no pose estimation, rotation correction or realignment",
        "alignment would be a component the artifact does not supply",
    ),
    (
        "padding",
        "pad symmetrically to a square of side max(width, height)",
        "the model asserts a square 299x299 input; the aspect ratio is preserved rather than stretched",
    ),
    (
        "padding_fill",
        "fill with 255 in the 8-bit domain, which is exactly 1.0 after the conversion",
        "white is the background of a canonical fingerprint image; upstream pads with 1.0",
    ),
    (
        "padding_parity",
        "left = top = floor(total / 2); right = bottom = total - left",
        "upstream applies the same floor to both sides and then asserts squareness, "
        "which cannot hold for an odd difference",
    ),
    (
        "resize",
        "resize the square to 299x299",
        "DEEPPRINT_INPUT_SIZE is asserted by the pinned stem",
    ),
    (
        "interpolation",
        "torchvision InterpolationMode.BILINEAR, named explicitly",
        "the library default is a library decision and can move between releases",
    ),
    (
        "antialias",
        "antialias=True, named explicitly",
        "downsampling without it aliases ridge frequencies, and the default has changed before",
    ),
    ("tensor_shape", "[1, 299, 299], channel first", "the pinned stem takes one channel"),
    ("numeric_dtype", "float32", "the model's parameters are float32"),
    (
        "value_range",
        "[0, 1] by exact uint8 / 255, applied before padding and resizing; the "
        "antialiased resize may leave a sample up to 2**-20 outside that range and "
        "is not clamped",
        "converting first keeps the resize in float instead of quantizing through 8-bit "
        "intermediates, and matches upstream's own order; the resize computes its filter "
        "weights in float32 and they do not sum to exactly one, so a uniformly white "
        "image lands a few ulps either side of 1.0, and clamping it back would change "
        "pixels in a step neither the spec nor upstream performs",
    ),
    (
        "normalization",
        "none: no mean, no standard deviation, no contrast or histogram transform, no ridge enhancement",
        "any of them would be an undeclared component of the algorithm",
    ),
    ("channel_replication", "none", "the stem takes one channel, not three"),
    (
        "re_encoding",
        "none: the canonical PNG bytes are decoded once and never re-encoded",
        "a round trip through an encoder could change a sample and would not be visible",
    ),
)


def expected_padding(width: int, height: int) -> Mapping[str, int]:
    """The frozen parity rule, computed independently of the worker."""
    if width <= 0 or height <= 0:
        raise FlxPreprocessingError(f"a source image cannot be {width}x{height}")
    side = max(width, height)
    horizontal, vertical = side - width, side - height
    left, top = horizontal // 2, vertical // 2
    return {
        "side": side,
        "left": left,
        "top": top,
        "right": horizontal - left,
        "bottom": vertical - top,
    }


def build_preprocessing_profile() -> FlxPreprocessingProfile:
    steps = tuple(
        FlxPreprocessingStep.create(
            schema_version=STAGE8B_SCHEMA_VERSION,
            step_id=step_id,
            action=action,
            rationale=rationale,
        )
        for step_id, action, rationale in PREPROCESSING_STEPS
    )
    if tuple(step.step_id for step in steps) != REQUIRED_PREPROCESSING_STEPS:
        raise FlxPreprocessingError(
            "the declared steps do not answer every required question in order"
        )
    return FlxPreprocessingProfile.create(
        schema_version=STAGE8B_SCHEMA_VERSION,
        profile_id=identity.PREPROCESSING_PROFILE_ID,
        input_contract="canonical 500 ppi 8-bit grayscale PNG, one frame, non-interlaced",
        output_shape=(1, identity.MODEL_INPUT_SIDE, identity.MODEL_INPUT_SIDE),
        output_dtype="float32",
        value_minimum="0",
        value_maximum="1",
        padding_fill_value=identity.PAD_FILL_VALUE,
        padding_parity_rule="left_top_floor_right_bottom_remainder",
        resize_side=identity.MODEL_INPUT_SIDE,
        interpolation="torchvision.transforms.InterpolationMode.BILINEAR",
        antialias=True,
        dataset_independent=True,
        subject_independent=True,
        steps=steps,
    )


def verify_model_input(model_input: ModelInput) -> None:
    """Check the worker's transform against the profile, in the parent."""
    padding = expected_padding(model_input.source_width, model_input.source_height)
    observed = {
        "side": model_input.padded_side,
        "left": model_input.pad_left,
        "top": model_input.pad_top,
        "right": model_input.pad_right,
        "bottom": model_input.pad_bottom,
    }
    if observed != dict(padding):
        raise FlxPreprocessingError(
            f"padding placement is {observed}, the frozen rule gives {dict(padding)}"
        )
    tolerance = identity.VALUE_RANGE_TOLERANCE
    if model_input.minimum < -tolerance or model_input.maximum > 1.0 + tolerance:
        raise FlxPreprocessingError(
            f"values [{model_input.minimum}, {model_input.maximum}] escape [0, 1] "
            f"by more than the {tolerance} float32 resampling allowance"
        )
