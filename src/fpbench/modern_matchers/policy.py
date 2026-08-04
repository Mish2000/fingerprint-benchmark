"""The fixed, gate-first Stage 8A selection policy."""

from __future__ import annotations

from pathlib import Path

import yaml

from fpbench.core.errors import CandidateRegistryError
from fpbench.core.modern_matcher_models import SelectionPolicy
from fpbench.modern_matchers.loading import selection_policy_from_plain
from fpbench.modern_matchers.registry import _UniqueKeyLoader

__all__ = ["TIE_BREAKERS", "load_selection_policy"]

TIE_BREAKERS = (
    "official_or_author_supplied",
    "algorithm_completeness",
    "no_external_completion_component",
    "documented_checkpoint_threshold",
    "dataset_independent_preprocessing",
    "smaller_simpler_runtime",
    "less_new_adapter_code",
    "architecture_diversity",
    "research_recency",
)


def load_selection_policy(path: Path) -> SelectionPolicy:
    path = Path(path)
    if not path.is_file():
        raise CandidateRegistryError(f"selection policy not found: {path}")
    try:
        payload = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
        policy = selection_policy_from_plain(payload)
    except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
        raise CandidateRegistryError(f"{path}: invalid Stage 8A selection policy ({exc})") from exc
    if policy.tie_breakers != TIE_BREAKERS:
        raise CandidateRegistryError(
            f"{path}: tie breakers must remain in their frozen order {TIE_BREAKERS}"
        )
    return policy
