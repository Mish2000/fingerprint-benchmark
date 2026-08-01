"""SourceAFIS's identity is what two finished runs are attributed to.

``run_7ac1cecc0bb3`` and ``run_4c59fa02a6ab`` both record an
``algorithm_fingerprint``, and every stored decision, metric and paired
evaluation downstream of them is bound to it. Changing anything the fingerprint
covers — a metadata key, a version string, an adapter version, a capability —
would leave 12,000 stored results attributed to an algorithm that no longer
exists under that name.

Stage 7A moved the pipeline description from a dict literal to
:class:`AlgorithmPipelineMetadata`. That is a refactor, and this file is what
makes it a refactor rather than a claim: the expected values below were read out
of ``workspace/results/run_7ac1cecc0bb3/run.json`` and must survive every future
tidy-up of the adapter (spec sections 6, 27 and 70).

Needs no JVM. The descriptor is built from constants and does not consult the
environment.
"""

from __future__ import annotations

import pytest

from fpbench.adapters.sourceafis_java.adapter import (
    ADAPTER_ID,
    ALGORITHM_ID,
    PIPELINE,
    PIPELINE_METADATA,
    SourceAfisJavaAdapter,
)
from fpbench.core.enums import ScoreDirection
from fpbench.core.execution_models import descriptor_fingerprint

pytestmark = pytest.mark.adapter_contract

#: Copied from the two finished runs' manifests, not recomputed from the code.
STORED_ALGORITHM_FINGERPRINT = (
    "5a1784faae1e82c12c374e050fcd6cfd41aa25b7a9ade3905d099df2e06a9531"
)

#: The exact mapping ``run.json`` records under ``algorithm.metadata``.
STORED_PIPELINE_METADATA = {
    "bridge_protocol": "fpbench.sourceafis.bridge.v1",
    "dpi_policy": "explicit_effective_ppi",
    "extractor_id": "sourceafis_java",
    "extractor_version": "3.18.1",
    "family_id": "sourceafis",
    "implementation_language": "java",
    "input_mode": "encoded_image",
    "integration_mode": "subprocess_per_comparison",
    "matcher_id": "sourceafis_java",
    "matcher_version": "3.18.1",
    "pipeline_kind": "end_to_end_image_matcher",
    "probe_side": "left",
    "seed_usage": "ignored_algorithm_has_no_seed",
    "template_cache": "disabled",
    "template_persistence": "disabled",
    "upstream_artifact": "com.machinezoo.sourceafis:sourceafis:3.18.1",
}


def test_the_descriptor_fingerprint_is_the_one_the_finished_runs_record():
    descriptor = SourceAfisJavaAdapter().descriptor
    assert descriptor_fingerprint(descriptor) == STORED_ALGORITHM_FINGERPRINT


def test_every_pipeline_metadata_key_and_value_is_unchanged():
    assert dict(PIPELINE_METADATA) == STORED_PIPELINE_METADATA


def test_the_typed_model_renders_exactly_the_mapping_it_replaced():
    """A dict literal and a typed model must be indistinguishable downstream."""
    assert dict(PIPELINE.as_descriptor_metadata()) == STORED_PIPELINE_METADATA


def test_the_identity_fields_are_unchanged():
    descriptor = SourceAfisJavaAdapter().descriptor
    assert descriptor.algorithm_id == ALGORITHM_ID == "sourceafis_java"
    assert descriptor.adapter_id == ADAPTER_ID == "sourceafis_java_subprocess"
    assert descriptor.adapter_version == "1"
    assert descriptor.adapter_contract_version == "1"
    assert descriptor.implementation_version == "3.18.1"
    assert descriptor.score_direction is ScoreDirection.HIGHER_IS_BETTER
    assert descriptor.deterministic is True


def test_no_capability_was_added():
    """A capability reaches the fingerprint, so adding one is a new algorithm."""
    assert SourceAfisJavaAdapter().descriptor.capabilities == ()


def test_the_descriptor_is_the_same_object_twice_running():
    adapter = SourceAfisJavaAdapter()
    assert adapter.descriptor == adapter.descriptor
