from __future__ import annotations

from pathlib import Path

import pytest

from fpbench.core.errors import Stage8AFinalizationError
from fpbench.core.serialization import write_json
from fpbench.modern_matchers.finalization import (
    build_stage8a_finalization,
    file_sha256,
)
from fpbench.modern_matchers.verify import verify_stage8a_evidence
from stage8aworld import COMMIT, NOW, build_evidence_world, rebuild

pytestmark = pytest.mark.stage8a_contract

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_CONFIG = (
    REPOSITORY_ROOT
    / "configs"
    / "modern-matchers"
    / "stage8a_candidates_v1.yaml"
)
POLICY_CONFIG = (
    REPOSITORY_ROOT
    / "configs"
    / "modern-matchers"
    / "stage8a_selection_policy_v1.yaml"
)


def _verify(world):
    return verify_stage8a_evidence(
        repository_root=world.repository_root,
        registry_config=world.registry_config,
        policy_config=world.policy_config,
        require_git_provenance=False,
    )


def test_a_complete_no_ready_evidence_chain_reverifies(tmp_path: Path) -> None:
    world = build_evidence_world(tmp_path)
    verification = _verify(world)

    assert verification.is_valid
    assert verification.candidate_count == 3
    assert verification.required_artifacts_verified == 0
    assert world.finalization.registry_content_hash == file_sha256(
        world.store.registry_path
    )


def test_exact_readme_bytes_are_part_of_finalization(tmp_path: Path) -> None:
    world = build_evidence_world(tmp_path)
    world.store.readme_path.write_text("changed after finalization\n", encoding="utf-8")

    with pytest.raises(Stage8AFinalizationError, match="README exact bytes changed"):
        _verify(world)


def test_publication_tree_rejects_any_unfinalized_extra_file(tmp_path: Path) -> None:
    world = build_evidence_world(tmp_path)
    (world.store.evidence_dir / "notes.txt").write_text(
        "not part of the finalized publication\n",
        encoding="utf-8",
    )

    with pytest.raises(Stage8AFinalizationError, match="exactly the frozen"):
        _verify(world)


def test_readme_cannot_publish_a_machine_local_path(tmp_path: Path) -> None:
    world = build_evidence_world(tmp_path)
    world.store.readme_path.write_text(
        "Local cache: C:\\private\\matcher.bin\n",
        encoding="utf-8",
    )
    marker = build_stage8a_finalization(
        store=world.store,
        registry=world.registry,
        reports=world.reports,
        decision=world.decision,
        policy=world.policy,
        verifier_source_commit=COMMIT,
        verifier_source_tree_clean=True,
        created_utc=NOW,
        require_git_provenance=False,
    )
    write_json(world.store.finalization_path, marker)

    with pytest.raises(Stage8AFinalizationError, match="machine-local"):
        _verify(world)


def test_finalization_requires_a_clean_verifier_tree(tmp_path: Path) -> None:
    world = build_evidence_world(tmp_path)
    with pytest.raises(ValueError, match="clean verifier source tree"):
        build_stage8a_finalization(
            store=world.store,
            registry=world.registry,
            reports=world.reports,
            decision=world.decision,
            policy=world.policy,
            verifier_source_commit=COMMIT,
            verifier_source_tree_clean=False,
            created_utc=NOW,
            require_git_provenance=False,
        )


def test_duplicate_qualification_reports_are_not_silently_collapsed(
    tmp_path: Path,
) -> None:
    world = build_evidence_world(tmp_path)
    reports = world.reports + (world.reports[0],)

    with pytest.raises(Stage8AFinalizationError, match="exactly one"):
        build_stage8a_finalization(
            store=world.store,
            registry=world.registry,
            reports=reports,
            decision=world.decision,
            policy=world.policy,
            verifier_source_commit=COMMIT,
            verifier_source_tree_clean=True,
            created_utc=NOW,
            require_git_provenance=False,
        )


def test_verifier_requires_finalization_to_cover_every_qualification(
    tmp_path: Path,
) -> None:
    world = build_evidence_world(tmp_path)
    forged = rebuild(
        world.finalization,
        qualification_fingerprints={},
        qualification_content_hashes={},
    )
    write_json(world.store.finalization_path, forged)

    with pytest.raises(Stage8AFinalizationError):
        _verify(world)


def test_selected_outcome_cannot_drop_required_local_artifact_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = build_evidence_world(tmp_path, ready=True)
    monkeypatch.setattr(
        "fpbench.modern_matchers.verify.build_frozen_qualification_reports",
        lambda **_: world.reports,
    )
    assert world.finalization.required_local_artifact_fingerprints
    forged = rebuild(world.finalization, required_local_artifact_fingerprints={})
    write_json(world.store.finalization_path, forged)

    with pytest.raises(Stage8AFinalizationError):
        _verify(world)


def test_production_verifier_rejects_an_alternate_registry_before_loading(
    tmp_path: Path,
) -> None:
    alternate = tmp_path / "alternate-registry.json"
    alternate.write_text("not Stage 8A evidence\n", encoding="utf-8")

    with pytest.raises(
        Stage8AFinalizationError,
        match="exact repository-owned Stage 8A path",
    ):
        verify_stage8a_evidence(
            repository_root=REPOSITORY_ROOT,
            registry_config=alternate,
            policy_config=POLICY_CONFIG,
        )


def test_production_artifact_root_cannot_enter_a_prior_result_tree() -> None:
    with pytest.raises(
        Stage8AFinalizationError,
        match="forbidden prior-stage inputs",
    ):
        verify_stage8a_evidence(
            repository_root=REPOSITORY_ROOT,
            registry_config=REGISTRY_CONFIG,
            policy_config=POLICY_CONFIG,
            artifact_root=REPOSITORY_ROOT / "workspace" / "results",
        )
