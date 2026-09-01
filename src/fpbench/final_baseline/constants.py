"""Frozen constants for the final-baseline TAR/FAR/FRR reporting boundary.

This component is the only reporting layer permitted to read raw score values
across the whole roster. It turns the six legacy mated result sets plus the
six sealed Stage 21B cross-subject result sets into the frozen Stage 21A
report, and nothing else.  Everything it may compute was predeclared by
Stage 21A; everything it may not compute is refused by
:mod:`fpbench.baseline_evaluation` and by the loaders in this package.
"""

from __future__ import annotations

from pathlib import Path

from fpbench.stage21b.constants import (
    EXPECTED_METHODS,
    EXPECTED_PAIRS_PER_METHOD,
    EXPECTED_PAIRS_PER_RELEASE,
    EXPECTED_RELEASES,
    LEGACY_PAIR_COUNT,
    LEGACY_PAIR_MANIFEST_HASH,
    PREPARATION_SET_ID,
    STAGE21A_EVIDENCE,
    STAGE21B_EVIDENCE,
)

__all__ = [
    "COMPONENT",
    "OUTCOME",
    "EVIDENCE_DIRECTORY",
    "FINALIZATION_NAME",
    "EVIDENCE_DOCUMENTS",
    "REPORT_NAME",
    "POLICY_PATH",
    "REPORTING_PATH",
    "EXPECTED_GENUINE_PER_METHOD",
    "EXPECTED_GENUINE_PER_RELEASE",
    "EXPECTED_METHODS",
    "EXPECTED_PAIRS_PER_METHOD",
    "EXPECTED_PAIRS_PER_RELEASE",
    "EXPECTED_RELEASES",
    "LEGACY_PAIR_COUNT",
    "LEGACY_PAIR_MANIFEST_HASH",
    "PREPARATION_SET_ID",
    "POOLED_SCOPE",
    "STAGE21A_EVIDENCE",
    "STAGE21B_EVIDENCE",
    "STAGE21A_MARKER_FINGERPRINT_KEY",
    "STAGE21B_MARKER_FINGERPRINT_KEY",
]

COMPONENT = "final_baseline_reporting"
OUTCOME = "FINAL_BASELINE_TAR_FAR_FRR_REPORT_READY"

EVIDENCE_DIRECTORY = Path("evidence/final-baseline-tar-far-frr")
FINALIZATION_NAME = "final-baseline-finalization.json"
REPORT_NAME = "final-baseline-report.md"

#: Everything the publisher writes, in publication order.  The marker is not in
#: this tuple for the same reason it is not in Stage 21A's: it is derived over
#: the exact bytes of the others and written last.
EVIDENCE_DOCUMENTS = (
    "evaluation-inputs.json",
    "tar-far-frr-results.json",
    "native-documented-rules-context.json",
    REPORT_NAME,
)

POLICY_PATH = Path("configs/comparisons/final_baseline_tar_far_frr_v1.yaml")
REPORTING_PATH = Path("configs/reports/final_baseline_reporting_v1.yaml")

#: The legacy plain↔roll mated family: 500 fingers per release, three releases.
EXPECTED_GENUINE_PER_METHOD = 1_500
EXPECTED_GENUINE_PER_RELEASE = 500

POOLED_SCOPE = "pooled"

STAGE21A_MARKER_FINGERPRINT_KEY = "stage_21a_finalization_fingerprint"
STAGE21B_MARKER_FINGERPRINT_KEY = "stage_21b_finalization_fingerprint"
