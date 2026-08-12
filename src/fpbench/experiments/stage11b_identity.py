"""What Stage 11B is, frozen in code rather than only in a configuration file.

The experiment configuration restates every identity below so a reviewer sees
them in a diff. Restating catches a typo; it does not stop somebody editing both
the file and its own checks. So the frozen values live here, the loader compares
the file against them, and changing what Stage 11B runs means changing code that
a test asserts against published evidence (docs/adr/0031, spec section 25).

Nothing here is a threshold, a calibration profile, an FMR target or a score
statistic, and nothing here will become one. Stage 11B ends at 6,000 stored raw
outcomes (spec sections 21, 33 and 35).
"""

from __future__ import annotations

from pathlib import Path

__all__ = [
    "EXPERIMENT_ID",
    "EVIDENCE_DIRECTORY",
    "STAGE_11B_FINALIZATION_NAME",
    "OPERATIONAL_SUMMARY_NAME",
    "SMOKE_REPORT_NAME",
    "EVIDENCE_DOCUMENTS",
    "OUTCOME",
    "EXECUTION_PROFILE_ID",
    "JOB_DEADLINE_SECONDS",
    "MAX_WORKERS",
    "RETRIES",
    "REFERENCE_RUN_ID",
    "REFERENCE_PLAN_ID",
    "REFERENCE_RESULT_SET_ID",
    "REFERENCE_COHORT_ID",
    "REFERENCE_PAIR_MANIFEST_HASH",
    "PREPARATION_SET_ID",
    "PREPARATION_SET_FINGERPRINT",
    "TRANSFORM_PROFILE_ID",
    "TRANSFORM_PROFILE_FINGERPRINT",
    "TRANSFORM_RUNTIME_FINGERPRINT",
    "EXPECTED_JOBS",
    "EXPECTED_RELEASES",
    "EXPECTED_PER_RELEASE",
    "EXPECTED_PER_STAGE",
    "EXPECTED_PER_RELEASE_STAGE",
    "EXPECTED_SUBJECTS",
    "EXPECTED_PARTICIPATING_IMAGES",
    "EXPECTED_SOURCE_PPI",
    "EXPECTED_LOGICAL_EXTRACTIONS",
    "EXPECTED_VERIFY_INVOCATIONS",
    "FORBIDDEN_CONFIG_KEYS",
    "REQUIRED_REPORTING_SWITCHES",
    "SMOKE_MAX_SCORES",
]

EXPERIMENT_ID = "verifinger_canonical500_full_v1"
EVIDENCE_DIRECTORY = Path("evidence/stage11b-verifinger-canonical500-raw")
STAGE_11B_FINALIZATION_NAME = "stage-11b-finalization.json"
OPERATIONAL_SUMMARY_NAME = "operational-summary.json"
SMOKE_REPORT_NAME = "adapter-smoke.json"

#: The nine documents this stage publishes, and no twentieth. Everything generic
#: — the run definition, the plan, the result set, the receipt — stays in the
#: engine's own structure and is not copied out under a Stage 11B name
#: (spec section 40).
EVIDENCE_DOCUMENTS: tuple[str, ...] = (
    "README.md",
    "algorithm-profile.json",
    "runtime-binding.json",
    "adapter-profile.json",
    "bridge-contract.json",
    SMOKE_REPORT_NAME,
    "canonical-run-binding.json",
    OPERATIONAL_SUMMARY_NAME,
    STAGE_11B_FINALIZATION_NAME,
)

#: What closing this stage means, and the only string that does.
OUTCOME = "VERIFINGER_CANONICAL500_RAW_COMPLETE"


# ------------------------------------------------------------------ execution

EXECUTION_PROFILE_ID = "verifinger_canonical500_sequential_no_retry_v1"

#: Chosen before SD300 was opened, from qualification and smoke timings alone.
#: Stage 11A measured 2.29 s per end-to-end verify and the smoke measures the
#: same order of magnitude with JVM startup included; 180 seconds is a margin of
#: roughly fifty. It is deliberately generous *and* deliberately fixed: tuning a
#: deadline after seeing which pairs are slow is how a timeout stops being a
#: guard (spec section 28).
JOB_DEADLINE_SECONDS = 180

#: One at a time. Also the gentlest possible load on a trial licence
#: (spec section 28).
MAX_WORKERS = 1
RETRIES = 0


# ------------------------------------------------- the canonical reference run

REFERENCE_RUN_ID = "run_4c59fa02a6ab"
REFERENCE_PLAN_ID = "plan_b4ae66e91923"
REFERENCE_RESULT_SET_ID = "resultset_087b084fb8a8"
REFERENCE_COHORT_ID = "sd300_50_subjects_test_22f8d52a7478"
REFERENCE_PAIR_MANIFEST_HASH = (
    "ee4d942e23cdc112e17ed69e0abc603d5f26e17cc5839edc9aa412edc57dfe3b"
)

PREPARATION_SET_ID = "prepset_be560e047991"
PREPARATION_SET_FINGERPRINT = (
    "be560e047991a0d58af8f86a4576f8b78dc350e643af82f0e2405350d9e2fd3f"
)
TRANSFORM_PROFILE_ID = "canonical_gray8_500ppi_lanczos3_v1"
TRANSFORM_PROFILE_FINGERPRINT = (
    "28abd453d86918132c03a57a2ace1a59024b5fb9c2e02eb5339e2a61e4597373"
)
TRANSFORM_RUNTIME_FINGERPRINT = (
    "31a0a4346a3dd07843513cc1de5b167d8f2795b230a82bac709913032b74579c"
)


# --------------------------------------------------------------- the workload

EXPECTED_JOBS = 6000
EXPECTED_RELEASES: tuple[str, ...] = ("SD300A", "SD300B", "SD300C")
EXPECTED_PER_RELEASE = 2000
EXPECTED_PER_STAGE = 1500
EXPECTED_PER_RELEASE_STAGE = 500
EXPECTED_SUBJECTS = 50
EXPECTED_PARTICIPATING_IMAGES = 3000

#: Which resolution each release's artefacts were scaled *from*. Checked through
#: the preparation entries: by the time the adapter reads a file it is already
#: 500 ppi and the source resolution is no longer inferable (docs/adr/0032).
EXPECTED_SOURCE_PPI = {"SD300A": 500, "SD300B": 1000, "SD300C": 2000}

#: Two extractions and one verify per comparison, SELF included. Twelve thousand
#: and six thousand over the run (spec sections 14 and 27).
EXPECTED_LOGICAL_EXTRACTIONS = EXPECTED_JOBS * 2
EXPECTED_VERIFY_INVOCATIONS = EXPECTED_JOBS


# ------------------------------------------------------------- what may not be

#: Keys that would turn this into a decision, calibration or evaluation stage.
#: Refused wherever they appear in the experiment document, at any depth
#: (spec section 21).
FORBIDDEN_CONFIG_KEYS: frozenset[str] = frozenset(
    {
        "accuracy",
        "calibration",
        "calibration_profile",
        "decision_profile",
        "decision_threshold",
        "eer",
        "far",
        "far_target",
        "fmr",
        "fmr_target",
        "fnmr",
        "metrics",
        "operating_point",
        "roc",
        "score_statistics",
        "threshold",
    }
)

#: The reporting switches the experiment must set, and to what. A stage that
#: could publish a histogram by flipping a flag is a stage one flag away from
#: publishing a threshold (spec sections 33 and 35).
REQUIRED_REPORTING_SWITCHES: dict[str, bool] = {
    "operational_summary": True,
    "biometric_metrics": False,
    "score_statistics": False,
    "score_export": False,
}

#: The production smoke produces at most this many scores before SD300 is
#: opened. Small on purpose: it is a proof that the production adapter works,
#: not a second qualification (spec section 23).
SMOKE_MAX_SCORES = 20
