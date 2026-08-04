from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from fpbench.core.errors import CandidateRegistryError, Stage8AFinalizationError
from fpbench.core.serialization import write_json
from fpbench.modern_matchers.verify import ensure_publishable, verify_stage8a_evidence
from stage8aworld import build_evidence_world

pytestmark = pytest.mark.stage8a_contract


def _set(document: Any, path: str, value: Any) -> None:
    parts = path.split(".")
    current = document
    for part in parts[:-1]:
        current = current[int(part)] if isinstance(current, list) else current[part]
    last = parts[-1]
    if isinstance(current, list):
        current[int(last)] = value
    else:
        current[last] = value


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("artifact_manifest.source_commit", "b" * 40),
        ("artifact_manifest.components.1.model_variant", "OtherVariant_512"),
        ("artifact_manifest.components.1.embedding_dimension", 256),
        (
            "preprocessing_profile.operations.0.action",
            "silently inverted grayscale",
        ),
        ("representation_profile.representation_shape.0", 256),
        ("score_profile.similarity_function", "invented cosine"),
        ("score_profile.normalization", "different normalization"),
        ("score_profile.score_direction", "lower_is_better"),
        ("determinism_report.runtime_version", "different-runtime"),
        ("artifact_manifest.license_records.1.conclusion", "blocked"),
        ("decision_path.documented_threshold", "0.75"),
    ],
)
def test_any_qualification_claim_edit_invalidates_the_evidence(
    tmp_path: Path, path: str, value: Any
) -> None:
    world = build_evidence_world(tmp_path)
    report = next(
        item
        for item in world.reports
        if item.candidate_id == "flx_fixed_length_extractor"
    )
    target = world.store.qualification_path(report.candidate_id)
    payload = json.loads(target.read_text(encoding="utf-8"))
    _set(payload, path, value)
    write_json(target, payload)

    with pytest.raises((ValueError, Stage8AFinalizationError)):
        verify_stage8a_evidence(
            repository_root=world.repository_root,
            registry_config=world.registry_config,
            policy_config=world.policy_config,
            require_git_provenance=False,
        )


def test_candidate_tier_tampering_is_detected(tmp_path: Path) -> None:
    world = build_evidence_world(tmp_path)
    payload = json.loads(world.store.registry_path.read_text(encoding="utf-8"))
    payload["candidates"][0]["tier"] = "C"
    write_json(world.store.registry_path, payload)

    with pytest.raises((ValueError, Stage8AFinalizationError)):
        verify_stage8a_evidence(
            repository_root=world.repository_root,
            registry_config=world.registry_config,
            policy_config=world.policy_config,
            require_git_provenance=False,
        )


def test_selection_policy_tampering_is_detected(tmp_path: Path) -> None:
    world = build_evidence_world(tmp_path)
    payload = json.loads(world.policy_config.read_text(encoding="utf-8"))
    payload["tie_breakers"][0], payload["tie_breakers"][1] = (
        payload["tie_breakers"][1],
        payload["tie_breakers"][0],
    )
    write_json(world.policy_config, payload)

    with pytest.raises((ValueError, CandidateRegistryError, Stage8AFinalizationError)):
        verify_stage8a_evidence(
            repository_root=world.repository_root,
            registry_config=world.registry_config,
            policy_config=world.policy_config,
            require_git_provenance=False,
        )


def test_duplicate_json_keys_are_rejected_before_model_loading(tmp_path: Path) -> None:
    world = build_evidence_world(tmp_path)
    text = world.store.selection_path.read_text(encoding="utf-8")
    world.store.selection_path.write_text(
        text.replace(
            '  "schema_version": "1",',
            '  "schema_version": "1",\n  "schema_version": "1",',
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(Stage8AFinalizationError, match="duplicate JSON key"):
        verify_stage8a_evidence(
            repository_root=world.repository_root,
            registry_config=world.registry_config,
            policy_config=world.policy_config,
            require_git_provenance=False,
        )


@pytest.mark.parametrize(
    "document",
    [
        {"weights_bytes": "not publishable"},
        {"license_key": "secret"},
        {"image_bytes": "secret"},
        {"embedding_values": [1, 2]},
        {"raw_scores": [1, 2]},
        {"storage_reference": "C:\\private\\artifact"},
    ],
)
def test_publication_sanitizer_rejects_private_payloads(document) -> None:
    with pytest.raises(Stage8AFinalizationError):
        ensure_publishable(document)
