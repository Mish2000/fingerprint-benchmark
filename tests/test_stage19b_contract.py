"""The frozen Stage 19B protocol: one change, and proof it is the only one.

Stage 19B removes exactly one thing — OpenAFIS's refusal of templates above 128
minutiae — and every test here defends that nothing else moved with it.

The load-bearing test is :func:`test_the_uncapped_translator_is_inert_below_128`.
Disabling the C++ refusal is only half the change: fpbench's own translator
enforced the same ceiling, so the patched build would never have been asked the
question. The sibling that removes it must be byte-identical to the original
everywhere the original worked, or Gate A's conclusion does not carry through the
adapter.

Needs no NBIS build, no OpenAFIS binary and no dataset.
"""

from __future__ import annotations

import pytest

from fpbench.adapters.nbis.xyt import NbisMinutia
from fpbench.adapters.openafis import capacity_extended as variant
from fpbench.adapters.openafis import adapter as base
from fpbench.adapters.openafis.translation import (
    OPENAFIS_MAXIMUM_MINUTIAE,
    OPENAFIS_MINIMUM_MINUTIAE,
    TranslationRefused,
    translate_xyt_to_openafis_csv,
)

pytestmark = pytest.mark.stage19b_contract


def minutiae(count: int) -> list[NbisMinutia]:
    return [
        NbisMinutia(x=10 + i, y=20 + 2 * i, theta=(7 * i) % 360, quality=i % 101)
        for i in range(count)
    ]


# ------------------------------------------------------- the translator inertness


@pytest.mark.parametrize("count", list(range(OPENAFIS_MINIMUM_MINUTIAE, OPENAFIS_MAXIMUM_MINUTIAE + 1)))
def test_the_uncapped_translator_is_inert_below_128(count):
    """Byte-identical output for every count the original accepts. All 127 of them."""
    source = minutiae(count)
    assert (
        variant.translate_xyt_to_openafis_csv_uncapped(source, width=381, height=891).text
        == translate_xyt_to_openafis_csv(source, width=381, height=891).text
    )


def test_the_uncapped_translator_still_refuses_below_the_lower_bound():
    # Stage 19B removes the upper limit only. Upstream still refuses fewer than
    # two minutiae, and so must we.
    with pytest.raises(TranslationRefused) as raised:
        variant.translate_xyt_to_openafis_csv_uncapped(minutiae(1), width=381, height=891)
    assert raised.value.reason == "minutiae_below_upstream_minimum"


def test_the_uncapped_translator_carries_every_minutia_above_128():
    for count in (129, 205, 279, 373, 500):
        result = variant.translate_xyt_to_openafis_csv_uncapped(minutiae(count), width=381, height=891)
        assert result.minutiae_count == count
        assert len(result.text.strip().split("\n")) - 1 == count


def test_the_original_translator_was_not_changed():
    # The whole reason the sibling exists: translation.py is pinned by Stage 19A.
    with pytest.raises(TranslationRefused):
        translate_xyt_to_openafis_csv(minutiae(129), width=381, height=891)
    assert OPENAFIS_MAXIMUM_MINUTIAE == 128


def test_the_uncapped_translator_has_no_new_knob():
    import inspect

    assert set(inspect.signature(variant.translate_xyt_to_openafis_csv_uncapped).parameters) == {
        "minutiae", "width", "height", "minutia_type",
    }


# ------------------------------------------------------------------- identity


def test_the_variant_does_not_claim_upstreams_identity():
    assert variant.ALGORITHM_ID == "nbis_mindtct_openafis_capacity_extended"
    assert variant.ALGORITHM_ID != base.ALGORITHM_ID
    assert variant.ADAPTER_ID != base.ADAPTER_ID


def test_the_modification_is_declared_in_the_descriptor_not_only_beside_it():
    metadata = variant.PIPELINE_METADATA
    assert metadata["upstream_modified"] == "true"
    assert metadata["base_openafis_commit"] == "3ae1c757c6dafea977a33ef51380e37f1715e626"
    assert metadata["modification"] == (
        "disable_template_upper_minutiae_rejection_for_stage19b_csv_route"
    )
    assert variant.RESULT_METADATA["upstream_modified"] == "true"


def test_nothing_that_decides_a_score_differs_from_the_base_route():
    # The experiment is only meaningful if the matcher's capacity is the sole
    # difference. Every score-affecting field must be inherited unchanged.
    for key in (
        "angle_conversion",
        "coordinate_scaling",
        "minutia_type_policy",
        "minutiae_quality_transferred",
        "minutiae_filtering",
        "minutiae_ordering",
        "probe_side",
        "openafis_threshold",
        "openafis_score_transform",
        "mindtct_m1",
        "mindtct_contrast_boost",
        "input_mode",
        "dpi_policy",
        "template_cache",
        "extractor_id",
    ):
        assert variant.PIPELINE_METADATA[key] == base.PIPELINE_METADATA[key], key


def test_the_shared_extractor_is_still_declared():
    assert variant.PIPELINE_METADATA["shares_extractor_with"] == "nbis_mindtct_bozorth3"


def test_nothing_was_chosen_from_the_secugen_reference():
    assert variant.RESULT_METADATA["secugen_reference_used_for_parameter_selection"] == "false"


def test_the_variant_inherits_compare_rather_than_reimplementing_it():
    # If compare were overridden, the extraction, probe side and failure
    # vocabulary would all be free to drift from the base route.
    assert "compare" not in vars(variant.OpenAfisCapacityExtendedAdapter)
    assert variant.OpenAfisCapacityExtendedAdapter.compare is base.OpenAfisAdapter.compare


def test_only_translate_and_the_identity_are_overridden():
    """The variant may redefine how a template is rendered and what it calls
    itself. Anything else it redefined would be a second change hiding behind
    the first."""
    # `from_config` is a classmethod, so vars() holds the descriptor rather than a
    # callable; filter by name instead of by callability.
    ignored = {"__doc__", "__module__", "__abstractmethods__", "_abc_impl"}
    redefined = set(vars(variant.OpenAfisCapacityExtendedAdapter)) - ignored
    assert redefined == {"__init__", "from_config", "_translate", "validate_environment"}


def test_the_variant_is_registered_separately():
    from fpbench.adapters.registry import registered_adapters

    ids = set(registered_adapters())
    assert "nbis_mindtct_openafis_subprocess" in ids
    assert "nbis_mindtct_openafis_capacity_extended_subprocess" in ids


def test_the_adr_exists():
    from fpbench.experiments.stage18a_inputs import REPOSITORY_ROOT

    adr = REPOSITORY_ROOT / "docs" / "adr" / "0136-a-modified-matcher-gets-its-own-identity.md"
    assert adr.is_file()
