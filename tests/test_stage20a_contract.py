"""The Stage 20A MCC route is a representation change and nothing more."""

from __future__ import annotations

import inspect
import math

import pytest

from fpbench.adapters.nbis.xyt import NbisMinutia
from fpbench.experiments import stage20a_mcc_contract as contract

pytestmark = pytest.mark.stage20a_contract


def _minutia(x: int, y: int, theta: int, quality: int = 50) -> NbisMinutia:
    return NbisMinutia(x=x, y=y, theta=theta, quality=quality)


def test_the_candidate_names_both_extractor_and_matcher() -> None:
    assert contract.CANDIDATE_ID == "nbis_mindtct_mcc_sdk_v2"
    assert contract.OUTCOME == "MINDTCT_MCC_SDK_V2_ROUTE_PASS"


def test_the_exact_public_apis_are_frozen() -> None:
    assert "CreateMccTemplate" in contract.TEMPLATE_API
    assert "BioLab.Biometrics.Mcc.Sdk.Minutia[]" in contract.TEMPLATE_API
    assert contract.MATCH_API.startswith("System.Double ")
    assert contract.MATCH_API.endswith("(System.Object,System.Object)")


def test_coordinates_change_origin_by_the_upstream_subtraction_only() -> None:
    source = [_minutia(19, 1, 0), _minutia(35, 90, 0)]
    result = contract.translate_xyt_to_mcc_input(source, width=100, height=100)
    assert [(item.x, item.y) for item in result.minutiae] == [(19, 99), (35, 10)]


def test_direction_changes_units_only() -> None:
    source = [_minutia(1, 1, theta) for theta in (0, 1, 45, 90, 180, 270, 359)]
    result = contract.translate_xyt_to_mcc_input(source, width=10, height=10)
    for original, translated in zip(source, result.minutiae):
        assert translated.direction == original.theta * math.pi / 180.0


def test_real_geometry_and_canonical_resolution_are_carried_directly() -> None:
    result = contract.translate_xyt_to_mcc_input(
        [_minutia(10, 20, 30)], width=381, height=891
    )
    assert (result.image_width, result.image_height) == (381, 891)
    assert result.image_resolution == 500


def test_quality_has_no_destination_and_cannot_change_the_geometry() -> None:
    low = contract.translate_xyt_to_mcc_input(
        [_minutia(10, 20, 30, quality=0)], width=100, height=100
    )
    high = contract.translate_xyt_to_mcc_input(
        [_minutia(10, 20, 30, quality=100)], width=100, height=100
    )
    assert low == high
    assert not hasattr(low.minutiae[0], "quality")


def test_every_minutia_survives_in_mindtct_order_even_above_128() -> None:
    source = [
        _minutia(x=i % 200, y=1 + i % 198, theta=i % 360, quality=100 - i % 101)
        for i in range(205)
    ]
    result = contract.translate_xyt_to_mcc_input(source, width=200, height=200)
    assert len(result.minutiae) == len(source)
    assert [item.x for item in result.minutiae] == [item.x for item in source]


def test_duplicates_survive_and_there_is_no_sort_or_deduplication() -> None:
    source = [
        _minutia(90, 10, 20, quality=1),
        _minutia(2, 80, 40, quality=99),
        _minutia(90, 10, 20, quality=50),
    ]
    result = contract.translate_xyt_to_mcc_input(source, width=100, height=100)
    assert [(item.x, item.y) for item in result.minutiae] == [
        (90, 90),
        (2, 20),
        (90, 90),
    ]


def test_no_score_affecting_choice_can_be_passed_to_the_translator() -> None:
    assert set(inspect.signature(contract.translate_xyt_to_mcc_input).parameters) == {
        "minutiae",
        "width",
        "height",
    }


def test_every_consumed_field_has_a_non_project_status() -> None:
    assert "PROJECT_CHOICE" not in contract.FIELD_CONTRACT.values()
    assert contract.FIELD_CONTRACT == {
        "x": "DIRECT",
        "y": "DERIVED_MECHANICALLY",
        "theta": "DERIVED_MECHANICALLY",
        "quality": "IGNORED_BY_MCC",
        "width": "DIRECT",
        "height": "DIRECT",
        "resolution": "DIRECT",
        "minutia_type": "IGNORED_BY_MCC",
        "finger_position": "IGNORED_BY_MCC",
    }


def test_invalid_mindtct_geometry_is_refused_instead_of_clamped_or_wrapped() -> None:
    with pytest.raises(contract.MccTranslationRefused, match="invalid_raster_dimensions"):
        contract.translate_xyt_to_mcc_input([], width=0, height=100)
    with pytest.raises(contract.MccTranslationRefused, match="minutia_outside_mindtct_raster"):
        contract.translate_xyt_to_mcc_input(
            [_minutia(100, 2, 0)], width=100, height=100
        )


def test_the_exact_nbis_subtraction_is_not_replaced_by_a_border_clamp() -> None:
    result = contract.translate_xyt_to_mcc_input(
        [_minutia(2, 0, 0)], width=100, height=100
    )
    assert result.minutiae[0].y == 100
