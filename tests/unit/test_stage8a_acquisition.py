from __future__ import annotations

from pathlib import Path

import pytest

from fpbench.core.errors import CandidateArtifactError
from fpbench.core.modern_matcher_models import (
    ComponentKind,
    LicenseConclusion,
    LicenseScope,
)
from fpbench.modern_matchers.acquisition import load_acquisition_manifests
from fpbench.modern_matchers.registry import load_candidate_registry

pytestmark = pytest.mark.stage8a_contract

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = (
    REPOSITORY_ROOT
    / "configs"
    / "modern-matchers"
    / "stage8a_candidates_v1.yaml"
)
MANIFEST_DIRECTORY = (
    REPOSITORY_ROOT / "integrations" / "modern-matchers" / "manifests"
)


def _manifests():
    registry = load_candidate_registry(REGISTRY_PATH)
    manifests = load_acquisition_manifests(
        MANIFEST_DIRECTORY, registry=registry
    )
    return registry, {item.candidate_id: item for item in manifests}


def test_acquisition_covers_the_frozen_registry_without_qualifying_papers() -> None:
    registry, manifests = _manifests()
    assert set(manifests) == {
        candidate.candidate_id for candidate in registry.candidates
    }
    for candidate_id in (
        "afr_net_official_artifact",
        "mgvit_official_artifact",
    ):
        manifest = manifests[candidate_id]
        assert not manifest.checkpoint_components
        assert [component.role for component in manifest.components] == ["paper"]
        assert not manifest.required_components_available_offline


def test_flx_code_checkpoint_and_licences_have_separate_identities() -> None:
    _registry, manifests = _manifests()
    manifest = manifests["flx_fixed_length_extractor"]
    checkpoint = next(
        item for item in manifest.components if item.kind is ComponentKind.CHECKPOINT
    )
    assert manifest.source_commit == "7accfca1f33b9b42bfd220e43cd5bc13b4a7fa13"
    assert checkpoint.filename == "best_model.pyt"
    assert checkpoint.size_bytes == 875_770_140
    assert checkpoint.sha256 == (
        "2683a04427bacd54adc00cfdc97474625b1e11e5a9e6672c5129f033018f8a28"
    )
    assert checkpoint.model_variant == "DeepPrint_TexMinu_512_without_localization"
    assert checkpoint.embedding_dimension == 512

    licences = {record.scope: record for record in manifest.license_records}
    assert licences[LicenseScope.SOURCE_CODE].conclusion is LicenseConclusion.CLEAR
    assert licences[LicenseScope.WEIGHTS].conclusion is LicenseConclusion.UNCLEAR
    assert checkpoint.license_record_fingerprint == licences[LicenseScope.WEIGHTS].fingerprint
    assert any(
        item.role == "dependency_lock" and not item.present
        for item in manifest.components
    )


def test_no_checkpoint_bytes_are_committed_beside_the_manifests() -> None:
    integration_root = MANIFEST_DIRECTORY.parent
    assert not list(integration_root.rglob("*.pyt"))
    assert not list(integration_root.rglob("*.pt"))


def test_acquisition_rejects_a_duplicate_json_key(tmp_path: Path) -> None:
    registry, _manifests_by_id = _manifests()
    for source in MANIFEST_DIRECTORY.glob("*.json"):
        text = source.read_text(encoding="utf-8")
        if source.name == "afr_net_official_artifact.json":
            text = text.replace(
                '  "schema_version": "1",',
                '  "schema_version": "1",\n  "schema_version": "1",',
                1,
            )
        (tmp_path / source.name).write_text(text, encoding="utf-8")

    with pytest.raises(CandidateArtifactError, match="duplicate JSON key"):
        load_acquisition_manifests(tmp_path, registry=registry)
