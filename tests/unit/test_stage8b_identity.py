"""The Stage 8B identities are frozen, and the freeze is what is tested.

Every constant here is embedded in a fingerprint and republished in evidence.
A test that reads the constant and asserts it equals itself would be worthless,
so these assert the literal frozen values and the properties that make them
usable as identities.
"""

from __future__ import annotations

import pytest

from fpbench.core.identifiers import InvalidIdentifierError, validate_id
from fpbench.flx import identity

pytestmark = pytest.mark.stage8b_contract


def test_the_frozen_identifiers_are_exactly_the_declared_ones() -> None:
    assert identity.ALGORITHM_ID == "flx_deepprint_texminu_512_without_localization"
    assert identity.ADAPTER_ID == "flx_pytorch_subprocess"
    assert identity.ADAPTER_VERSION == 1
    assert identity.RUNTIME_PROFILE_ID == "flx_cpu_linux_x86_64_v1"
    assert identity.PREPROCESSING_PROFILE_ID == "fpbench_canonical500_to_flx299_squarepad_v1"
    assert identity.REPRESENTATION_PROFILE_ID == "flx_texminu_256x2_v1"
    assert identity.SCORE_PROFILE_ID == "flx_texminu_equal_branch_dot_v1"
    assert identity.SCORE_SERIALIZATION_PROFILE_ID == "ieee_scalar_to_decimal17_v1"
    assert identity.QUALIFICATION_PROTOCOL_ID == "stage8b_flx_runtime_adapter_qualification_v1"


def test_every_identifier_is_a_safe_path_and_key_component() -> None:
    for identifier in identity.all_frozen_identifiers():
        assert validate_id(identifier) == identifier


def test_the_algorithm_id_never_claims_to_be_deepprint_itself() -> None:
    # docs/adr/0069: the name must carry the implementation, the variant and
    # the absent localization, so it cannot be read as the published DeepPrint.
    assert identity.ALGORITHM_ID.startswith("flx_")
    assert "without_localization" in identity.ALGORITHM_ID
    assert identity.IMPLEMENTATION_ORIGIN == "independent_reimplementation"
    assert "BIOSIG 2023" in identity.UPSTREAM_STUDY


def test_the_artifact_identities_match_the_stage8a_acquisition_manifest() -> None:
    assert identity.SOURCE_COMMIT == "7accfca1f33b9b42bfd220e43cd5bc13b4a7fa13"
    assert identity.SOURCE_ARCHIVE_SHA256 == (
        "60fa2c8894ea90efe2bb0553cd331d8ef84611b973b6126eaf6d162d1aa9b7e2"
    )
    assert identity.CHECKPOINT_FILENAME == "best_model.pyt"
    assert identity.CHECKPOINT_SHA256 == (
        "2683a04427bacd54adc00cfdc97474625b1e11e5a9e6672c5129f033018f8a28"
    )
    assert identity.CHECKPOINT_SIZE_BYTES == 875770140
    assert identity.CHECKPOINT_VARIANT == "DeepPrint_TexMinu_512_without_localization"


def test_the_stage8a_manifest_still_states_the_same_artifact_identities() -> None:
    # A drift between the two would mean Stage 8B is executing something other
    # than what Stage 8A inspected, which is the one thing the binding exists
    # to prevent.
    import json
    from pathlib import Path

    manifest_path = (
        Path(__file__).resolve().parents[2]
        / "integrations"
        / "modern-matchers"
        / "manifests"
        / "flx_fixed_length_extractor.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    components = {item["component_id"]: item for item in manifest["components"]}

    assert manifest["source_commit"] == identity.SOURCE_COMMIT
    assert manifest["source_archive_sha256"] == identity.SOURCE_ARCHIVE_SHA256
    checkpoint = components["flx_checkpoint"]
    assert checkpoint["filename"] == identity.CHECKPOINT_FILENAME
    assert checkpoint["sha256"] == identity.CHECKPOINT_SHA256
    assert checkpoint["size_bytes"] == identity.CHECKPOINT_SIZE_BYTES
    assert checkpoint["model_variant"] == identity.CHECKPOINT_VARIANT


def test_the_representation_shape_is_two_branches_of_256() -> None:
    assert identity.TEXTURE_DIMENSIONS == 256
    assert identity.MINUTIA_DIMENSIONS == 256
    assert identity.CONCATENATED_DIMENSIONS == 512


def test_the_inference_batch_rule_is_frozen_with_its_reason() -> None:
    # docs/adr/0070: the pinned texture branch has no batch-of-one path.
    assert identity.INFERENCE_BATCH_ROWS == 2
    assert identity.INFERENCE_BATCH_RULE == "duplicate_pair_take_first_row"
    assert identity.REPRESENTED_ROW == 0
    assert identity.REPRESENTED_ROW < identity.INFERENCE_BATCH_ROWS


def test_the_transform_targets_are_frozen() -> None:
    assert identity.MODEL_INPUT_SIDE == 299
    assert identity.PAD_FILL_VALUE == 255


def test_the_score_contract_is_frozen() -> None:
    assert identity.SCORE_MINIMUM == "-2"
    assert identity.SCORE_MAXIMUM == "2"
    assert identity.SCORE_DIRECTION == "higher_is_more_similar"
    assert identity.DECIMAL_SIGNIFICANT_DIGITS == 17


def test_the_tolerance_is_bitwise_equality() -> None:
    # Spec section 18: this is fixed before the probe and may not be widened
    # after a measurement has been seen.
    assert identity.NUMERIC_TOLERANCE == "0"


def test_the_training_only_allowlist_is_frozen_before_the_checkpoint_is_opened() -> None:
    assert identity.TRAINING_ONLY_CHECKPOINT_KEYS == (
        "loss_state_dict",
        "optimizer_state_dict",
    )


def test_the_licence_status_cannot_be_read_as_resolved() -> None:
    assert identity.WEIGHTS_LICENSE_STATUS == "unresolved"
    assert identity.REDISTRIBUTION_ALLOWED == "not_established"
    assert identity.PUBLICATION_PERMISSION == "not_established"


def test_the_evidence_publication_is_exactly_ten_named_files() -> None:
    assert identity.EVIDENCE_DIRECTORY_NAME == "stage8b-flx-runtime-qualification"
    assert identity.REQUIRED_EVIDENCE_FILES == (
        "README.md",
        "artifact-binding.json",
        "runtime-manifest.json",
        "preprocessing-profile.json",
        "representation-profile.json",
        "score-profile.json",
        "adapter-profile.json",
        "runtime-probe.json",
        "qualification-report.json",
        "stage-8b-finalization.json",
    )
    assert len(set(identity.REQUIRED_EVIDENCE_FILES)) == 10


def test_an_identifier_with_unsafe_characters_would_be_rejected() -> None:
    with pytest.raises(InvalidIdentifierError):
        validate_id("flx/pytorch subprocess")
