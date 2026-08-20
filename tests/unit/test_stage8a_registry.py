from __future__ import annotations

from pathlib import Path

import pytest

from fpbench.core.errors import CandidateRegistryError
from fpbench.core.modern_matcher_models import CandidateTier
from fpbench.core.json_io import write_json
from fpbench.modern_matchers.policy import TIE_BREAKERS, load_selection_policy
from fpbench.modern_matchers.registry import (
    FROZEN_CANDIDATE_TIERS,
    RESERVE_CANDIDATE_ID,
    load_candidate_registry,
)
from stage8aworld import make_candidate, make_policy, make_registry, rebuild

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
REGISTRY = REPOSITORY_ROOT / "configs/modern-matchers/stage8a_candidates_v1.yaml"
POLICY = REPOSITORY_ROOT / "configs/modern-matchers/stage8a_selection_policy_v1.yaml"

pytestmark = pytest.mark.stage8a_contract


def test_the_committed_registry_is_exactly_the_three_frozen_candidates() -> None:
    registry = load_candidate_registry(REGISTRY)
    assert {item.candidate_id: item.tier for item in registry.candidates} == (
        FROZEN_CANDIDATE_TIERS
    )
    assert registry.reserve_candidate_id == RESERVE_CANDIDATE_ID
    assert registry.reserve_candidate_id not in {
        item.candidate_id for item in registry.candidates
    }
    assert registry.frozen_before_qualification


def test_the_committed_policy_keeps_every_gate_and_all_nine_breakers() -> None:
    policy = load_selection_policy(POLICY)
    assert policy.tie_breakers == TIE_BREAKERS
    assert policy.tier_order == (
        CandidateTier.A,
        CandidateTier.B,
        CandidateTier.C,
    )
    assert policy.weighted_score_forbidden
    assert policy.unresolved_tie_action == "fail_closed"


def test_duplicate_yaml_keys_are_rejected(tmp_path: Path) -> None:
    text = REGISTRY.read_text(encoding="utf-8")
    path = tmp_path / "registry.yaml"
    path.write_text(
        text.replace(
            'schema_version: "1"',
            'schema_version: "1"\nschema_version: "1"',
            1,
        ),
        encoding="utf-8",
    )
    with pytest.raises(CandidateRegistryError, match="duplicate registry key"):
        load_candidate_registry(path)


def test_a_fourth_candidate_cannot_enter_registry_v1(tmp_path: Path) -> None:
    registry = make_registry()
    extra = make_candidate("quiet_fourth_candidate", tier=CandidateTier.C)
    changed = rebuild(registry, candidates=registry.candidates + (extra,))
    path = tmp_path / "registry.yaml"
    write_json(path, changed)

    with pytest.raises(CandidateRegistryError, match="no fourth candidate"):
        load_candidate_registry(path)


def test_a_tier_change_requires_a_new_registry(tmp_path: Path) -> None:
    registry = make_registry()
    first = rebuild(registry.candidates[0], tier=CandidateTier.C)
    changed = rebuild(registry, candidates=(first, *registry.candidates[1:]))
    path = tmp_path / "registry.yaml"
    write_json(path, changed)

    with pytest.raises(CandidateRegistryError, match="tier change"):
        load_candidate_registry(path)


def test_the_reserve_cannot_become_a_selectable_candidate() -> None:
    reserve = make_candidate("id3_finger_sdk", tier=CandidateTier.A)
    with pytest.raises(ValueError, match="outside Stage 8A"):
        make_registry((reserve,))


def test_tie_breaker_reordering_changes_identity_and_is_rejected(tmp_path: Path) -> None:
    policy = make_policy()
    changed = rebuild(
        policy,
        tie_breakers=(policy.tie_breakers[1], policy.tie_breakers[0], *policy.tie_breakers[2:]),
    )
    assert changed.fingerprint != policy.fingerprint
    path = tmp_path / "policy.yaml"
    write_json(path, changed)

    with pytest.raises(CandidateRegistryError, match="frozen order"):
        load_selection_policy(path)
