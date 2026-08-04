"""Re-derive the committed Stage 8A authority without datasets or old runs."""

from __future__ import annotations

from pathlib import Path

import pytest

from fpbench.core.modern_matcher_models import Stage8AOutcome
from fpbench.modern_matchers.verify import verify_stage8a_evidence

pytestmark = pytest.mark.stage8a

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


def test_the_committed_stage8a_evidence_rederives_without_any_dataset() -> None:
    verification = verify_stage8a_evidence(
        repository_root=REPOSITORY_ROOT,
        registry_config=REGISTRY_CONFIG,
        policy_config=POLICY_CONFIG,
    )

    assert verification.is_valid
    assert verification.candidate_count == 3
    assert verification.outcome is Stage8AOutcome.NO_MODERN_MATCHER_READY
    assert verification.required_artifacts_verified == 0
