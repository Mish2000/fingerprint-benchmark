"""Change one thing in the published evidence, and verification must refuse.

The published tree is copied into a temporary repository and then damaged one
field at a time.  Using the real documents rather than synthetic ones matters:
a tampering test over a fixture proves the fixture is tamper-evident.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from fpbench.core.flx_errors import Stage8BFinalizationError
from fpbench.flx.verify import verify_stage8b_evidence
from fpbench.storage.flx_store import Stage8BEvidenceStore

pytestmark = pytest.mark.stage8b_contract

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = REPOSITORY_ROOT / "evidence" / Stage8BEvidenceStore.DIRECTORY_NAME
CONFIGS = REPOSITORY_ROOT / "configs" / "flx"


@pytest.fixture
def published(tmp_path: Path) -> Path:
    """A portable copy of the real publication, with no Git metadata."""
    for relative in (
        "evidence/stage8b-flx-runtime-qualification",
        "evidence/stage8a-modern-matcher-selection",
    ):
        shutil.copytree(REPOSITORY_ROOT / relative, tmp_path / relative)
    return tmp_path


def _verify(root: Path):
    return verify_stage8b_evidence(
        repository_root=root,
        lock_config=CONFIGS / "flx_runtime_lock_v1.txt",
        policy_config=CONFIGS / "stage8b_flx_runtime_policy_v1.yaml",
        require_git_provenance=False,
    )


def _edit(root: Path, name: str, **changes) -> None:
    path = root / "evidence" / Stage8BEvidenceStore.DIRECTORY_NAME / name
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.update(changes)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_the_untouched_publication_verifies(published: Path) -> None:
    result = _verify(published)

    assert result.gate_count == 15
    assert result.evidence_files_verified == 10
    assert result.opens_stage_8c is True


@pytest.mark.parametrize(
    ("name", "changes"),
    [
        ("artifact-binding.json", {"checkpoint_sha256": "b" * 64}),
        ("artifact-binding.json", {"checkpoint_size_bytes": 875770139}),
        ("artifact-binding.json", {"source_commit": "0" * 40}),
        ("artifact-binding.json", {"source_archive_sha256": "c" * 64}),
        ("runtime-manifest.json", {"torch_version": "2.12.1+cpu"}),
        ("runtime-manifest.json", {"torch_num_threads": 8}),
        ("runtime-manifest.json", {"dependency_lock_sha256": "d" * 64}),
        ("preprocessing-profile.json", {"padding_fill_value": 0}),
        ("preprocessing-profile.json", {"antialias": False}),
        ("preprocessing-profile.json", {"interpolation": "NEAREST"}),
        ("preprocessing-profile.json", {"output_dtype": "float64"}),
        ("representation-profile.json", {"concatenation_order": ["minutia", "texture"]}),
        ("representation-profile.json", {"inference_batch_rows": 1}),
        ("score-profile.json", {"formula": "cosine(left, right)"}),
        ("score-profile.json", {"branch_weights": ["0.6", "0.4"]}),
        ("adapter-profile.json", {"adapter_version": 2}),
        ("adapter-profile.json", {"caches_representations": True}),
        ("runtime-probe.json", {"biometric_inputs_read": True}),
        ("runtime-probe.json", {"checkpoint_loaded": False}),
        ("qualification-report.json", {"permits_decisions": True}),
        ("qualification-report.json", {"weights_license_status": "resolved"}),
        ("stage-8b-finalization.json", {"outcome": "FLX_RUNTIME_BLOCKED"}),
        ("stage-8b-finalization.json", {"checkpoint_sha256": "e" * 64}),
        ("stage-8b-finalization.json", {"biometric_inputs_read": True}),
    ],
)
def test_tampering_with_a_published_claim_is_refused(
    published: Path, name: str, changes: dict
) -> None:
    _edit(published, name, **changes)

    with pytest.raises(Stage8BFinalizationError):
        _verify(published)


def test_a_forged_fingerprint_does_not_rescue_a_tampered_document(
    published: Path,
) -> None:
    # Recomputing the fingerprint over the edited claims makes the document
    # internally consistent; it is still not what the finalization bound.
    path = published / "evidence" / Stage8BEvidenceStore.DIRECTORY_NAME / "score-profile.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["nominal_maximum"] = "3"
    from fpbench.core.flx_models import semantic_fingerprint

    payload["fingerprint"] = semantic_fingerprint("flx_score_profile_v1", payload)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(Stage8BFinalizationError):
        _verify(published)


def test_a_missing_evidence_file_is_refused(published: Path) -> None:
    (published / "evidence" / Stage8BEvidenceStore.DIRECTORY_NAME / "score-profile.json").unlink()

    with pytest.raises(Stage8BFinalizationError, match="exactly the frozen publication"):
        _verify(published)


def test_an_extra_evidence_file_is_refused(published: Path) -> None:
    (
        published / "evidence" / Stage8BEvidenceStore.DIRECTORY_NAME / "notes.json"
    ).write_text("{}", encoding="utf-8")

    with pytest.raises(Stage8BFinalizationError, match="exactly the frozen publication"):
        _verify(published)


def test_a_duplicate_json_key_is_refused(published: Path) -> None:
    path = published / "evidence" / Stage8BEvidenceStore.DIRECTORY_NAME / "score-profile.json"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("{", '{\n  "profile_id": "x",', 1), encoding="utf-8")

    with pytest.raises(Stage8BFinalizationError, match="duplicate JSON key"):
        _verify(published)


def test_an_embedding_smuggled_into_the_evidence_is_refused(published: Path) -> None:
    _edit(published, "runtime-probe.json", embedding_values=[0.1, 0.2, 0.3])

    with pytest.raises(Stage8BFinalizationError, match="forbidden in public"):
        _verify(published)


def test_a_machine_local_path_in_the_evidence_is_refused(published: Path) -> None:
    _edit(published, "runtime-manifest.json", cpu_model="/home/someone/private/box")

    with pytest.raises(Stage8BFinalizationError, match="machine-local absolute path"):
        _verify(published)


def test_a_readme_naming_a_private_path_is_refused(published: Path) -> None:
    readme = published / "evidence" / Stage8BEvidenceStore.DIRECTORY_NAME / "README.md"
    readme.write_text("Checkpoint cached at C:\\private\\weights.pyt\n", encoding="utf-8")

    with pytest.raises(Stage8BFinalizationError, match="machine-local absolute path"):
        _verify(published)


def test_a_content_hash_that_no_longer_matches_the_bytes_is_refused(
    published: Path,
) -> None:
    # The claims are untouched; only the file's exact bytes moved.
    path = published / "evidence" / Stage8BEvidenceStore.DIRECTORY_NAME / "adapter-profile.json"
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(Stage8BFinalizationError):
        _verify(published)


def test_the_stage8a_binding_must_still_be_there(published: Path) -> None:
    shutil.rmtree(published / "evidence" / "stage8a-modern-matcher-selection")

    with pytest.raises(Stage8BFinalizationError, match="published Stage 8A finalization"):
        _verify(published)


def test_an_altered_stage8a_finalization_breaks_the_binding(published: Path) -> None:
    path = (
        published
        / "evidence"
        / "stage8a-modern-matcher-selection"
        / "stage-8a-finalization.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["fingerprint"] = "f" * 64
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(Stage8BFinalizationError):
        _verify(published)
