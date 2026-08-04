"""Stage 8A: qualify third-party matcher artefacts without benchmark data."""

from fpbench.modern_matchers.policy import TIE_BREAKERS, load_selection_policy
from fpbench.modern_matchers.registry import (
    CANDIDATE_REGISTRY_VERSION,
    FROZEN_CANDIDATE_TIERS,
    RESERVE_CANDIDATE_ID,
    load_candidate_registry,
)

__all__ = [
    "CANDIDATE_REGISTRY_VERSION",
    "FROZEN_CANDIDATE_TIERS",
    "RESERVE_CANDIDATE_ID",
    "TIE_BREAKERS",
    "load_candidate_registry",
    "load_selection_policy",
]
