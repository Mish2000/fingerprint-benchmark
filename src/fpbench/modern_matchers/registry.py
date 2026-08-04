"""Load and verify the candidate list frozen before Stage 8A qualification."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml

from fpbench.core.errors import CandidateRegistryError
from fpbench.core.modern_matcher_models import CandidateTier, ModernMatcherCandidateRegistry
from fpbench.modern_matchers.loading import registry_from_plain

__all__ = [
    "CANDIDATE_REGISTRY_VERSION",
    "FROZEN_CANDIDATE_TIERS",
    "RESERVE_CANDIDATE_ID",
    "load_candidate_registry",
]

CANDIDATE_REGISTRY_VERSION = "stage8a_candidates_v1"
FROZEN_CANDIDATE_TIERS = {
    "afr_net_official_artifact": CandidateTier.A,
    "mgvit_official_artifact": CandidateTier.B,
    "flx_fixed_length_extractor": CandidateTier.C,
}
RESERVE_CANDIDATE_ID = "id3_finger_sdk"


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_mapping(loader: yaml.SafeLoader, node: yaml.MappingNode, deep: bool = False) -> Mapping[str, Any]:
    result: dict[str, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise CandidateRegistryError(f"duplicate registry key {key!r} at line {key_node.start_mark.line + 1}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


def load_candidate_registry(path: Path) -> ModernMatcherCandidateRegistry:
    path = Path(path)
    if not path.is_file():
        raise CandidateRegistryError(f"candidate registry not found: {path}")
    try:
        payload = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
        registry = registry_from_plain(payload)
    except CandidateRegistryError:
        raise
    except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
        raise CandidateRegistryError(f"{path}: invalid candidate registry ({exc})") from exc
    if registry.candidate_registry_version != CANDIDATE_REGISTRY_VERSION:
        raise CandidateRegistryError(
            f"{path}: expected registry version {CANDIDATE_REGISTRY_VERSION!r}, "
            f"got {registry.candidate_registry_version!r}; adding a candidate requires a new version and ADR"
        )
    actual = {candidate.candidate_id: candidate.tier for candidate in registry.candidates}
    if actual != FROZEN_CANDIDATE_TIERS:
        raise CandidateRegistryError(
            f"{path}: Stage 8A v1 is exactly {FROZEN_CANDIDATE_TIERS}, got {actual}; no fourth candidate or tier change is permitted"
        )
    if registry.reserve_candidate_id != RESERVE_CANDIDATE_ID:
        raise CandidateRegistryError(f"{path}: the non-selectable reserve must remain {RESERVE_CANDIDATE_ID!r}")
    return registry
