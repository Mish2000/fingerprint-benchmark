"""Verify and display the finished Stage 8A selection authority.

Unlike the earlier benchmark experiments, this command has no workspace and
no execute mode.  It reads only the frozen registry, selection policy,
acquisition manifests, and the sanitised Stage 8A evidence directory.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Sequence

from fpbench.modern_matchers.verify import verify_stage8a_evidence

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REGISTRY_CONFIG = (
    REPOSITORY_ROOT
    / "configs"
    / "modern-matchers"
    / "stage8a_candidates_v1.yaml"
)
DEFAULT_POLICY_CONFIG = (
    REPOSITORY_ROOT
    / "configs"
    / "modern-matchers"
    / "stage8a_selection_policy_v1.yaml"
)


def verify_stage8a():
    artifact_root_value = os.environ.get("FPBENCH_STAGE8A_ARTIFACT_ROOT")
    return verify_stage8a_evidence(
        repository_root=REPOSITORY_ROOT,
        registry_config=DEFAULT_REGISTRY_CONFIG,
        policy_config=DEFAULT_POLICY_CONFIG,
        artifact_root=(
            Path(artifact_root_value) if artifact_root_value else None
        ),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="verify the immutable Stage 8A modern-matcher selection"
    )
    parser.add_argument(
        "command",
        choices=("status", "verify"),
        help="both commands re-derive the complete evidence chain",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _parser().parse_args(argv)
    result = verify_stage8a()
    print(result.outcome.value)
    print(f"qualification reports verified: {result.candidate_count}")
    print(f"required local artifact bundles verified: {result.required_artifacts_verified}")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised as a module command
    raise SystemExit(main())
