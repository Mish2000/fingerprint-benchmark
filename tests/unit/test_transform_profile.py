"""The transform profile parser, which is deliberately unforgiving.

It has no defaults. Every field must be present in the file, including the
eleven operations the profile forbids, because a default is a decision made by
whoever wrote the parser, applied to an experiment they will never see, and
recorded nowhere. If a profile omits ``sharpen: true`` and the parser fills it
in, the *file* no longer says what the transformation was — and two profiles
that read differently in git can fingerprint the same.
"""

from __future__ import annotations

import copy

import pytest
import yaml

from fpbench.core.errors import TransformProfileError
from fpbench.core.imaging_models import (
    FORBIDDEN_OPERATIONS,
    image_transform_profile_fingerprint,
)
from fpbench.imaging.transform_profile import (
    DEFAULT_PROFILE_PATH,
    load_transform_profile,
    parse_transform_profile,
)

pytestmark = [pytest.mark.imaging, pytest.mark.canonical500]


@pytest.fixture(scope="module")
def document():
    return yaml.safe_load(DEFAULT_PROFILE_PATH.read_text("utf-8"))


def _without(document, section: str, key: str):
    copied = copy.deepcopy(document)
    copied[section].pop(key)
    return copied


def _with(document, section: str, key: str, value):
    copied = copy.deepcopy(document)
    copied[section][key] = value
    return copied


def test_the_committed_profile_parses_and_is_the_canonical_500_one():
    profile = load_transform_profile()
    assert profile.profile_id == "canonical_gray8_500ppi_lanczos3_v1"
    assert profile.target_ppi == 500
    assert profile.resampler_engine == "pillow"
    assert profile.resampler_filter == "lanczos"
    assert profile.resampler_radius == 3
    assert profile.reducing_gap is None
    assert profile.direct_source_to_target is True
    assert profile.allow_upsampling is False
    assert profile.dimension_rounding == "nearest_half_up"
    assert profile.output_pixels_per_meter_x == 19685
    assert profile.output_pixels_per_meter_y == 19685
    assert profile.output_compression_level == 9
    assert profile.output_optimize is False
    assert profile.output_interlaced is False
    assert profile.missing_forbidden_operations() == ()


def test_the_fingerprint_covers_the_profile_and_nothing_else():
    profile = load_transform_profile()
    assert profile.profile_fingerprint == image_transform_profile_fingerprint(profile)
    assert len(profile.profile_fingerprint) == 64


def test_the_fingerprint_excludes_the_file_it_was_read_from(tmp_path, document):
    """The same specification, elsewhere on disk, is the same specification."""
    elsewhere = tmp_path / "copied-somewhere-else.yaml"
    elsewhere.write_text(yaml.safe_dump(document), encoding="utf-8")
    assert (
        load_transform_profile(elsewhere).profile_fingerprint
        == load_transform_profile().profile_fingerprint
    )


@pytest.mark.parametrize("operation", FORBIDDEN_OPERATIONS)
def test_omitting_a_forbidden_operation_is_an_error(document, operation):
    broken = copy.deepcopy(document)
    broken["forbidden_operations"].pop(operation)
    with pytest.raises(TransformProfileError, match=operation):
        parse_transform_profile(broken)


@pytest.mark.parametrize("operation", ["sharpen", "invert", "crop"])
def test_permitting_a_forbidden_operation_is_an_error(document, operation):
    with pytest.raises(TransformProfileError, match="permits"):
        parse_transform_profile(_with(document, "forbidden_operations", operation, False))


def test_a_reducing_gap_is_refused(document):
    """Pillow's shortcut is a second resampling nobody asked for."""
    with pytest.raises(TransformProfileError, match="reducing_gap"):
        parse_transform_profile(_with(document, "pixel_transform", "reducing_gap", "2.0"))


@pytest.mark.parametrize("filter_name", ["bicubic", "bilinear", "box", "nearest", "hamming"])
def test_another_resampler_needs_another_profile(document, filter_name):
    with pytest.raises(TransformProfileError, match="resampler_filter"):
        parse_transform_profile(
            _with(document, "pixel_transform", "resampler_filter", filter_name)
        )


@pytest.mark.parametrize("engine", ["opencv", "scipy", "libvips"])
def test_another_engine_needs_another_profile(document, engine):
    with pytest.raises(TransformProfileError, match="resampler_engine"):
        parse_transform_profile(
            _with(document, "pixel_transform", "resampler_engine", engine)
        )


def test_a_chained_resize_path_is_refused(document):
    with pytest.raises(TransformProfileError, match="resize_path"):
        parse_transform_profile(
            _with(document, "pixel_transform", "resize_path", "two_stage")
        )


def test_bankers_rounding_cannot_be_selected(document):
    with pytest.raises(TransformProfileError, match="dimension_rounding"):
        parse_transform_profile(
            _with(document, "resolution", "dimension_rounding", "nearest_half_even")
        )


def test_upsampling_cannot_be_permitted(document):
    with pytest.raises(TransformProfileError, match="upsampling"):
        parse_transform_profile(_with(document, "resolution", "upsampling", "allowed"))


def test_the_declared_output_resolution_must_match_the_target(document):
    with pytest.raises(TransformProfileError, match="output.ppi"):
        parse_transform_profile(_with(document, "output", "ppi", 1000))


def test_the_pixels_per_metre_must_match_the_target(document):
    with pytest.raises(TransformProfileError, match="pixels_per_meter"):
        parse_transform_profile(
            _with(document, "output", "png_pixels_per_meter_x", 39370)
        )


def test_optimize_cannot_be_enabled(document):
    with pytest.raises(TransformProfileError, match="optimize"):
        parse_transform_profile(_with(document, "output", "optimize", True))


def test_interlacing_cannot_be_enabled(document):
    with pytest.raises(TransformProfileError, match="interlace"):
        parse_transform_profile(_with(document, "output", "interlace", True))


def test_a_sixteen_bit_input_contract_needs_its_own_profile(document):
    with pytest.raises(TransformProfileError, match="bit_depth"):
        parse_transform_profile(_with(document, "input", "bit_depth", 16))


def test_alpha_and_palette_must_stay_forbidden(document):
    for key in ("alpha", "palette"):
        with pytest.raises(TransformProfileError, match=key):
            parse_transform_profile(_with(document, "input", key, "allowed"))


def test_text_and_colour_management_must_be_stripped(document):
    for key in ("strip_text_chunks", "strip_colour_management_chunks"):
        with pytest.raises(TransformProfileError, match=key):
            parse_transform_profile(_with(document, "output", key, False))


def test_timestamps_must_stay_forbidden(document):
    with pytest.raises(TransformProfileError, match="timestamps"):
        parse_transform_profile(_with(document, "output", "timestamps", "allowed"))


@pytest.mark.parametrize(
    ("section", "key"),
    [
        ("profile", "profile_id"),
        ("resolution", "target_ppi"),
        ("pixel_transform", "resampler_filter"),
        ("output", "compression_level"),
        ("input", "frame_count"),
    ],
)
def test_a_missing_field_is_an_error_rather_than_a_default(document, section, key):
    with pytest.raises(TransformProfileError, match=key):
        parse_transform_profile(_without(document, section, key))


def test_a_non_integer_target_resolution_is_rejected(document):
    with pytest.raises(TransformProfileError, match="exact integer"):
        parse_transform_profile(_with(document, "resolution", "target_ppi", 500.0))


def test_a_missing_file_is_reported_clearly(tmp_path):
    with pytest.raises(TransformProfileError, match="not found"):
        load_transform_profile(tmp_path / "absent.yaml")
