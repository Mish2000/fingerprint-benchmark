"""A route's identity names every tool on it.

The model's whole job is to stop ``bozorth3`` being an acceptable answer to
"which algorithm produced this score?" when MINDTCT extracted the templates
(docs/adr/0014, spec section 68).
"""

from __future__ import annotations

import pytest

from fpbench.adapters.pipeline_metadata import (
    PIPELINE_METADATA_FIELDS,
    AlgorithmPipelineMetadata,
)

pytestmark = pytest.mark.adapter_contract


def two_stage(**overrides) -> AlgorithmPipelineMetadata:
    settings: dict[str, object] = {
        "family_id": "example_family",
        "pipeline_kind": "extract_then_match",
        "extractor_id": "example_extractor",
        "extractor_version": "1.0",
        "matcher_id": "example_matcher",
        "matcher_version": "2.0",
        "implementation_language": "c",
        "integration_mode": "subprocess_per_stage",
        "input_mode": "raw_image",
        "dpi_policy": "explicit_effective_ppi",
        "probe_side": "left",
        "template_cache": "disabled",
        "template_persistence": "disabled",
        "seed_usage": "ignored_algorithm_has_no_seed",
    }
    settings.update(overrides)
    return AlgorithmPipelineMetadata(**settings)  # type: ignore[arg-type]


def test_every_named_field_reaches_the_descriptor_metadata():
    metadata = two_stage().as_descriptor_metadata()
    assert set(PIPELINE_METADATA_FIELDS) <= set(metadata)
    assert metadata["extractor_id"] == "example_extractor"
    assert metadata["matcher_id"] == "example_matcher"


def test_a_two_stage_route_names_both_halves_separately():
    """The whole point: one field could not describe MINDTCT plus Bozorth3."""
    metadata = two_stage().as_descriptor_metadata()
    assert metadata["extractor_id"] != metadata["matcher_id"]
    assert metadata["extractor_version"] != metadata["matcher_version"]


@pytest.mark.parametrize("field", PIPELINE_METADATA_FIELDS)
def test_no_field_may_be_left_blank(field):
    with pytest.raises(ValueError, match=field):
        two_stage(**{field: "   "})


def test_extra_carries_route_specific_keys():
    metadata = two_stage(extra={"container_digest": "sha256:abc"})
    rendered = metadata.as_descriptor_metadata()
    assert rendered["container_digest"] == "sha256:abc"


def test_extra_may_not_redeclare_a_named_field():
    with pytest.raises(ValueError, match="redeclare"):
        two_stage(extra={"probe_side": "right"})


def test_the_rendered_mapping_is_read_only():
    metadata = two_stage().as_descriptor_metadata()
    with pytest.raises(TypeError):
        metadata["probe_side"] = "right"  # type: ignore[index]


def test_the_model_itself_is_frozen():
    metadata = two_stage()
    with pytest.raises(Exception):
        metadata.probe_side = "right"  # type: ignore[misc]
