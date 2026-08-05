"""What a representation must be, and what it must refuse to be."""

from __future__ import annotations

import base64
import struct

import pytest

from fpbench.core.flx_errors import FlxRepresentationError
from fpbench.flx import identity
from fpbench.flx.representation import FlxRepresentation, build_representation_profile

pytestmark = pytest.mark.stage8b_contract

WIDTH = identity.TEXTURE_DIMENSIONS


def _unit_vector(width: int = WIDTH, first: float = 1.0) -> bytes:
    values = [first] + [0.0] * (width - 1)
    return struct.pack(f"<{width}f", *values)


def _representation(**changes) -> FlxRepresentation:
    claims = dict(
        texture_bytes=_unit_vector(),
        minutia_bytes=_unit_vector(),
        texture_norm=1.0,
        minutia_norm=1.0,
    )
    claims.update(changes)
    return FlxRepresentation(**claims)


def test_a_representation_exposes_both_branches_and_their_concatenation() -> None:
    representation = _representation()

    assert len(representation.texture) == identity.TEXTURE_DIMENSIONS
    assert len(representation.minutia) == identity.MINUTIA_DIMENSIONS
    assert len(representation.concatenated) == identity.CONCATENATED_DIMENSIONS
    assert representation.shape == (identity.CONCATENATED_DIMENSIONS,)
    assert representation.dtype == "float32"


def test_the_concatenation_is_texture_then_minutia() -> None:
    texture = struct.pack(f"<{WIDTH}f", *([0.5] * WIDTH))
    minutia = struct.pack(f"<{WIDTH}f", *([0.25] * WIDTH))
    representation = _representation(
        texture_bytes=texture, minutia_bytes=minutia, texture_norm=8.0, minutia_norm=4.0
    )

    concatenated = representation.concatenated
    assert concatenated[:WIDTH] == tuple([0.5] * WIDTH)
    assert concatenated[WIDTH:] == tuple([0.25] * WIDTH)


def test_a_wrong_branch_width_is_refused() -> None:
    with pytest.raises(FlxRepresentationError, match="expected 1024 bytes"):
        _representation(texture_bytes=_unit_vector(128))


def test_a_non_finite_value_is_refused() -> None:
    for bad in (float("nan"), float("inf"), float("-inf")):
        payload = struct.pack(f"<{WIDTH}f", *([bad] + [0.0] * (WIDTH - 1)))
        with pytest.raises(FlxRepresentationError, match="non-finite"):
            _representation(texture_bytes=payload)


def test_a_zero_norm_branch_is_refused() -> None:
    with pytest.raises(FlxRepresentationError, match="zero-norm branch"):
        _representation(minutia_norm=0.0)


def test_a_non_finite_norm_is_refused() -> None:
    with pytest.raises(FlxRepresentationError, match="norm is not finite"):
        _representation(texture_norm=float("nan"))


def test_l2_normalization_is_checked_not_assumed() -> None:
    assert _representation().is_l2_normalized()
    assert not _representation(texture_norm=1.7).is_l2_normalized()


def test_equal_representations_hash_alike_and_differing_ones_do_not() -> None:
    assert _representation().content_hash == _representation().content_hash
    other = _representation(texture_bytes=_unit_vector(first=0.5), texture_norm=0.5)
    assert other.content_hash != _representation().content_hash


def test_a_representation_from_the_worker_copies_its_buffers() -> None:
    # Spec section 14: equality between representations is fine, sharing a
    # buffer that the next extraction overwrites is not.
    payload = {
        "texture": base64.b64encode(_unit_vector()).decode("ascii"),
        "minutia": base64.b64encode(_unit_vector()).decode("ascii"),
        "texture_norm": 1.0,
        "minutia_norm": 1.0,
    }
    first = FlxRepresentation.from_worker(payload)
    second = FlxRepresentation.from_worker(payload)

    assert first is not second
    assert first.texture_bytes is not second.texture_bytes
    assert first.content_hash == second.content_hash


def test_the_representation_profile_states_the_frozen_shape_and_batch_rule() -> None:
    profile = build_representation_profile()

    assert profile.profile_id == identity.REPRESENTATION_PROFILE_ID
    assert profile.concatenated_dimensions == 512
    assert profile.concatenation_order == ("texture", "minutia")
    assert profile.inference_batch_rows == 2
    assert profile.inference_batch_rule == "duplicate_pair_take_first_row"
    assert profile.represented_row == 0
    assert profile.duplicate_rows_must_be_bitwise_equal is True
    assert profile.localization_used is False
    assert profile.pose_input_required is False
    assert profile.reweighting_applied is False
    assert profile.persisted is False


def test_each_branch_names_the_upstream_module_that_normalizes_it() -> None:
    branches = {branch.branch_id: branch for branch in build_representation_profile().branches}

    assert branches["texture"].upstream_module.endswith("_Branch_TextureEmbedding")
    assert branches["minutia"].upstream_module.endswith("_Branch_MinutiaEmbedding")
    for branch in branches.values():
        assert branch.normalization == "l2_per_branch"
        assert branch.dimensions == 256


def test_the_representation_profile_is_stable() -> None:
    assert build_representation_profile().fingerprint == build_representation_profile().fingerprint
