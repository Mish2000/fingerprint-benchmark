"""The transform and the extraction, run for real against the pinned runtime."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from fpbench.core.flx_errors import FlxArtifactError, FlxWorkerError
from fpbench.flx import fixtures, identity
from fpbench.flx.artifacts import FlxRuntimeBundle, verify_bundle_artifacts
from fpbench.flx.policy import load_runtime_policy
from fpbench.flx.preprocessing import expected_padding
from fpbench.flx.worker import FlxWorkerSession

pytestmark = pytest.mark.flx_runtime

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
POLICY = load_runtime_policy(
    REPOSITORY_ROOT / "configs" / "flx" / "stage8b_flx_runtime_policy_v1.yaml"
)
PREPROCESS_DEADLINE = float(POLICY.preprocess_deadline_seconds)
EXTRACT_DEADLINE = float(POLICY.extract_deadline_seconds)


@pytest.fixture(scope="module")
def loaded_session():
    bundle = FlxRuntimeBundle.from_environment()
    try:
        verify_bundle_artifacts(bundle)
    except FlxArtifactError as exc:
        pytest.skip(f"no verified flx runtime bundle: {exc}")
    with FlxWorkerSession(
        bundle, startup_deadline_seconds=float(POLICY.max_worker_startup_seconds)
    ) as worker:
        worker.load_runtime(deadline_seconds=float(POLICY.max_model_load_seconds))
        yield worker


# ------------------------------------------------------------ preprocessing


@pytest.mark.parametrize("name", sorted(fixtures.FIXTURE_BUILDERS))
def test_every_fixture_preprocesses_to_the_declared_tensor(loaded_session, name) -> None:
    model_input = loaded_session.preprocess(
        fixtures.build_fixture(name), deadline_seconds=PREPROCESS_DEADLINE
    )

    side = identity.MODEL_INPUT_SIDE
    tolerance = identity.VALUE_RANGE_TOLERANCE
    assert model_input.shape == (1, side, side)
    assert model_input.dtype == "float32"
    assert len(model_input.values) == 4 * side * side
    assert -tolerance <= model_input.minimum <= model_input.maximum <= 1.0 + tolerance
    # Finiteness of every sample, not just the reported extremes.
    values = struct.unpack(f"<{side * side}f", model_input.values)
    assert all(value == value for value in values)
    assert all(-1e30 < value < 1e30 for value in values)


@pytest.mark.parametrize("name", ["fixture_odd_padding", "fixture_landscape", "fixture_white"])
def test_padding_lands_exactly_where_the_frozen_rule_says(loaded_session, name) -> None:
    model_input = loaded_session.preprocess(
        fixtures.build_fixture(name), deadline_seconds=PREPROCESS_DEADLINE
    )
    expected = expected_padding(model_input.source_width, model_input.source_height)

    assert model_input.padded_side == expected["side"]
    assert (model_input.pad_left, model_input.pad_right) == (expected["left"], expected["right"])
    assert (model_input.pad_top, model_input.pad_bottom) == (expected["top"], expected["bottom"])


def test_the_padded_corners_carry_the_fill_value(loaded_session) -> None:
    # fixture_odd_padding is 100x201, so the left and right thirds are fill.
    model_input = loaded_session.preprocess(
        fixtures.build_fixture("fixture_odd_padding"), deadline_seconds=PREPROCESS_DEADLINE
    )

    # 255/255 is exactly 1.0, and a corner is far enough inside the padding
    # that bilinear resampling cannot have mixed image content into it.
    assert model_input.sample(2, 2) == pytest.approx(1.0, abs=1e-6)
    assert model_input.sample(2, identity.MODEL_INPUT_SIDE - 3) == pytest.approx(1.0, abs=1e-6)


def test_an_all_white_image_stays_white_within_the_resampling_allowance(
    loaded_session,
) -> None:
    # The antialiased resize computes its weights in float32 and they do not
    # sum to exactly one, so a constant image does not resize to a constant.
    # The excursion is bounded and not clamped away.
    model_input = loaded_session.preprocess(
        fixtures.build_fixture("fixture_white"), deadline_seconds=PREPROCESS_DEADLINE
    )

    tolerance = identity.VALUE_RANGE_TOLERANCE
    assert 1.0 - tolerance <= model_input.minimum <= 1.0 + tolerance
    assert 1.0 - tolerance <= model_input.maximum <= 1.0 + tolerance
    assert model_input.minimum != 1.0 or model_input.maximum != 1.0


def test_preprocessing_is_bitwise_deterministic(loaded_session) -> None:
    payload = fixtures.build_fixture("fixture_synthetic_ridges")
    first = loaded_session.preprocess(payload, deadline_seconds=PREPROCESS_DEADLINE)
    second = loaded_session.preprocess(payload, deadline_seconds=PREPROCESS_DEADLINE)

    assert first.content_hash == second.content_hash
    assert first.values == second.values


def test_different_fixtures_produce_different_tensors(loaded_session) -> None:
    hashes = {
        name: loaded_session.preprocess(
            fixtures.build_fixture(name), deadline_seconds=PREPROCESS_DEADLINE
        ).content_hash
        for name in sorted(fixtures.FIXTURE_BUILDERS)
    }
    assert len(set(hashes.values())) == len(hashes)


@pytest.mark.parametrize(
    ("builder", "code"),
    [
        ("corrupt_png", "PNG_BAD_DEFLATE"),
        ("truncated_png", "PNG_TRUNCATED"),
        ("png_without_iend", "PNG_NO_IEND"),
        ("wrong_bit_depth_png", "PNG_UNEXPECTED_BIT_DEPTH"),
        ("paletted_png", "PNG_UNEXPECTED_COLOUR_TYPE"),
        ("gamma_tagged_png", "PNG_AMBIGUOUS_CHUNK"),
        ("interlaced_png", "PNG_INTERLACED"),
        ("animated_png", "PNG_MULTI_FRAME"),
    ],
)
def test_a_malformed_or_ambiguous_input_is_refused_by_name(
    loaded_session, builder, code
) -> None:
    payload = getattr(fixtures, builder)()

    with pytest.raises(FlxWorkerError, match=code):
        loaded_session.preprocess(payload, deadline_seconds=PREPROCESS_DEADLINE)


def test_input_that_is_not_a_png_at_all_is_refused(loaded_session) -> None:
    with pytest.raises(FlxWorkerError, match="PNG_BAD_SIGNATURE"):
        loaded_session.preprocess(b"GIF89a", deadline_seconds=PREPROCESS_DEADLINE)


# ------------------------------------------------------------- extraction


def test_extraction_produces_two_normalized_branches(loaded_session) -> None:
    model_input = loaded_session.preprocess(
        fixtures.build_fixture("fixture_synthetic_ridges"), deadline_seconds=PREPROCESS_DEADLINE
    )
    representation = loaded_session.extract(model_input, deadline_seconds=EXTRACT_DEADLINE)

    assert len(representation.texture) == 256
    assert len(representation.minutia) == 256
    assert len(representation.concatenated) == 512
    assert representation.shape == (512,)
    assert representation.dtype == "float32"
    assert representation.is_l2_normalized()
    assert all(value == value for value in representation.concatenated)


def test_every_fixture_extracts_to_a_finite_representation(loaded_session) -> None:
    for name in sorted(fixtures.FIXTURE_BUILDERS):
        model_input = loaded_session.preprocess(
            fixtures.build_fixture(name), deadline_seconds=PREPROCESS_DEADLINE
        )
        representation = loaded_session.extract(model_input, deadline_seconds=EXTRACT_DEADLINE)
        assert representation.is_l2_normalized(), name
        assert representation.texture_norm > 0 and representation.minutia_norm > 0, name


def test_repeated_extraction_in_one_process_is_bitwise_equal(loaded_session) -> None:
    model_input = loaded_session.preprocess(
        fixtures.build_fixture("fixture_gradient"), deadline_seconds=PREPROCESS_DEADLINE
    )
    first = loaded_session.extract(model_input, deadline_seconds=EXTRACT_DEADLINE)
    second = loaded_session.extract(model_input, deadline_seconds=EXTRACT_DEADLINE)

    assert first.content_hash == second.content_hash
    assert first is not second


def test_a_representation_is_bitwise_invariant_to_batch_position_and_context(
    loaded_session,
) -> None:
    inputs = {
        symbol: loaded_session.preprocess(
            fixtures.build_fixture(fixture_name), deadline_seconds=PREPROCESS_DEADLINE
        )
        for symbol, fixture_name in (
            ("A", "fixture_synthetic_ridges"),
            ("B", "fixture_gradient"),
            ("C", "fixture_seeded_noise"),
        )
    }
    contexts = (
        ((inputs["A"], inputs["A"]), 0),
        ((inputs["A"], inputs["B"]), 0),
        ((inputs["B"], inputs["A"]), 1),
        ((inputs["A"], inputs["C"]), 0),
        ((inputs["C"], inputs["A"]), 1),
    )

    representations = tuple(
        loaded_session.probe_batch_context(
            batch, represented_row, deadline_seconds=EXTRACT_DEADLINE
        )
        for batch, represented_row in contexts
    )

    assert len({item.texture_bytes for item in representations}) == 1
    assert len({item.minutia_bytes for item in representations}) == 1


def test_each_extraction_returns_a_new_object(loaded_session) -> None:
    # Spec section 9: equality is allowed, sharing a mutable buffer is not.
    model_input = loaded_session.preprocess(
        fixtures.build_fixture("fixture_white"), deadline_seconds=PREPROCESS_DEADLINE
    )
    first = loaded_session.extract(model_input, deadline_seconds=EXTRACT_DEADLINE)
    second = loaded_session.extract(model_input, deadline_seconds=EXTRACT_DEADLINE)

    assert first is not second
    assert first.texture_bytes is not second.texture_bytes


def test_different_inputs_produce_different_representations(loaded_session) -> None:
    hashes = set()
    for name in ("fixture_white", "fixture_gradient", "fixture_synthetic_ridges", "fixture_seeded_noise"):
        model_input = loaded_session.preprocess(
            fixtures.build_fixture(name), deadline_seconds=PREPROCESS_DEADLINE
        )
        hashes.add(loaded_session.extract(model_input, deadline_seconds=EXTRACT_DEADLINE).content_hash)
    assert len(hashes) == 4


def test_extraction_refuses_a_tensor_of_the_wrong_shape(loaded_session) -> None:
    with pytest.raises(FlxWorkerError, match="EXTRACT_WRONG_INPUT_SHAPE"):
        loaded_session.request(
            "extract",
            deadline_seconds=EXTRACT_DEADLINE,
            shape=[1, 224, 224],
            dtype="float32",
            values="",
        )


def test_extraction_refuses_a_tensor_of_the_wrong_dtype(loaded_session) -> None:
    side = identity.MODEL_INPUT_SIDE
    with pytest.raises(FlxWorkerError, match="EXTRACT_WRONG_INPUT_DTYPE"):
        loaded_session.request(
            "extract",
            deadline_seconds=EXTRACT_DEADLINE,
            shape=[1, side, side],
            dtype="float64",
            values="",
        )
