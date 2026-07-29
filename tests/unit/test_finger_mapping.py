"""The mapping is the one place a silent error would fabricate genuine pairs."""

from __future__ import annotations

import pytest

from fpbench.core.enums import FingerprintPosition, Impression
from fpbench.datasets.sd300.finger_mapping import (
    MULTI_FINGER_FRGP,
    expected_frgps,
    resolve_position,
)


def test_plain_thumbs_are_remapped_from_11_and_12():
    assert resolve_position(Impression.PLAIN, 11).position is FingerprintPosition.RIGHT_THUMB
    assert resolve_position(Impression.PLAIN, 12).position is FingerprintPosition.LEFT_THUMB


@pytest.mark.parametrize("frgp", [2, 3, 4, 5, 7, 8, 9, 10])
def test_segmented_plain_fingers_keep_their_number(frgp):
    assert resolve_position(Impression.PLAIN, frgp).position == FingerprintPosition(frgp)


@pytest.mark.parametrize("frgp", range(1, 11))
def test_rolled_positions_are_identity(frgp):
    resolution = resolve_position(Impression.ROLL, frgp)
    assert resolution.position == FingerprintPosition(frgp)
    assert not resolution.is_multi_finger


@pytest.mark.parametrize("frgp", sorted(MULTI_FINGER_FRGP))
def test_simultaneous_captures_have_no_anatomical_finger(frgp):
    resolution = resolve_position(Impression.PLAIN, frgp)
    assert resolution.position is None
    assert resolution.is_multi_finger
    assert resolution.is_known


@pytest.mark.parametrize("frgp", [1, 6])
def test_plain_thumbs_do_not_appear_under_their_anatomical_codes(frgp):
    """SD300 has no plain 01/06; seeing one means the release is not what we think."""
    resolution = resolve_position(Impression.PLAIN, frgp)
    assert resolution.position is None
    assert not resolution.is_known


def test_frgp_15_is_unknown_not_a_multi_finger_capture():
    resolution = resolve_position(Impression.PLAIN, 15)
    assert resolution.position is None
    assert not resolution.is_multi_finger
    assert not resolution.is_known


def test_a_complete_subject_needs_ten_of_each():
    assert len(expected_frgps(Impression.PLAIN)) == 10
    assert len(expected_frgps(Impression.ROLL)) == 10
