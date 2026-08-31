"""The non-score constants frozen by Stage 21B's execution contract."""

from __future__ import annotations

from pathlib import Path

STAGE = "21B"
OUTCOME = "FINAL_BASELINE_CROSS_SUBJECT_RAW_RESULTS_READY"

ROSTER_ID = "final_baseline_roster_v1"
PROTOCOL_ID = "sd300_cross_subject_non_mated_v1"
POPULATION = "plain_roll_cross_subject_non_mated"
GROUND_TRUTH = "NON_MATED"

EXPECTED_METHODS = 6
EXPECTED_PAIRS_PER_METHOD = 73_500
EXPECTED_TOTAL_ATTEMPTS = 441_000
EXPECTED_PAIRS_PER_RELEASE = 24_500
EXPECTED_RELEASES = ("SD300A", "SD300B", "SD300C")
FUTURE_TEST_RELEASE = "SD300B"

PREPARATION_SET_ID = "prepset_be560e047991"
PREPARATION_PROFILE_ID = "canonical_gray8_500ppi_lanczos3_v1"
EFFECTIVE_PPI = 500

LEGACY_PAIR_COUNT = 6_000
LEGACY_PAIR_MANIFEST_HASH = (
    "ee4d942e23cdc112e17ed69e0abc603d5f26e17cc5839edc9aa412edc57dfe3b"
)

STAGE21A_EVIDENCE = Path("evidence/stage21a-final-baseline-evaluation-protocol")
STAGE21B_EVIDENCE = Path("evidence/stage21b-cross-subject-baseline-expansion")
STAGE21B_WORKSPACE = Path("stage21b")
EXECUTION_POLICY_PATH = Path("configs/stage21b/frozen_execution_v1.yaml")

STAGE21A_MARKER = "stage-21a-finalization.json"
STAGE21B_MARKER = "stage-21b-finalization.json"

FORBIDDEN_EVALUATION_TOKENS = frozenset(
    {
        "tar",
        "far",
        "frr",
        "eer",
        "auc",
        "roc",
        "threshold",
        "calibration",
        "normalization",
        "ranking",
        "score_sweep",
    }
)
