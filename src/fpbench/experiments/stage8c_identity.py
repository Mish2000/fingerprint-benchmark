"""Everything Stage 8C froze before the first SD300 byte was read.

These constants are the stage's contract with itself.  They are asserted by the
acceptance tests, checked against the published Stage 8B evidence at preparation
time, restated in ``configs/experiments/flx_canonical500_full_v1.yaml`` so that
a reviewer sees them in a diff, and republished in the Stage 8C finalization.  A
later change to any of them is a different experiment with a different identity
rather than a quiet correction to this one.

Nothing here is derived at import time and nothing here reads a workspace.  The
identities that *must* be derived — the run, the plan, the result set, the
completion and their fingerprints — are deliberately absent: inventing them in
advance would mean the run had an identity before it had inputs (spec section 4).

This module exists in addition to the three the specification proposed, for the
same reason :mod:`fpbench.flx.identity` exists: the config loader, the research
integration and the finalization marker all need the frozen values, and a shared
constant module is the alternative to an import cycle between them.
"""

from __future__ import annotations

from pathlib import Path

from fpbench.core.identifiers import validate_id

__all__ = [
    "STAGE_8C_SCHEMA_VERSION",
    "EXPERIMENT_ID",
    "INTEGRATION_ID",
    "EXECUTION_PROFILE_ID",
    "ALIGNMENT_PROFILE_ID",
    "STAGE_FINALIZATION_KIND",
    "EVIDENCE_DIRECTORY",
    "ALIGNMENT_REPORT_NAME",
    "STAGE_8C_FINALIZATION_NAME",
    "STAGE8B_FINALIZATION_FINGERPRINT",
    "STAGE8B_OUTCOME",
    "ALGORITHM_ID",
    "ADAPTER_ID",
    "ADAPTER_VERSION",
    "RUNTIME_PROFILE_ID",
    "RUNTIME_MANIFEST_FINGERPRINT",
    "PREPROCESSING_PROFILE_ID",
    "PREPROCESSING_PROFILE_FINGERPRINT",
    "REPRESENTATION_PROFILE_ID",
    "REPRESENTATION_PROFILE_FINGERPRINT",
    "SCORE_PROFILE_ID",
    "SCORE_PROFILE_FINGERPRINT",
    "ADAPTER_PROFILE_FINGERPRINT",
    "SOURCE_COMMIT",
    "SOURCE_ARCHIVE_SHA256",
    "CHECKPOINT_FILENAME",
    "CHECKPOINT_SHA256",
    "CHECKPOINT_SIZE_BYTES",
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
    "EXPECTED_PARTICIPATING_IMAGES",
    "EXPECTED_SUBJECTS",
    "EXPECTED_RELEASES",
    "EXPECTED_PER_RELEASE_STAGE",
    "PREPROCESS_CALLS_PER_COMPARISON",
    "LOGICAL_EXTRACTIONS_PER_COMPARISON",
    "COMPARISONS_PER_JOB",
    "INFERENCE_BATCH_ROWS",
    "PLANNED_PREPROCESS_CALLS",
    "PLANNED_LOGICAL_EXTRACTIONS",
    "PLANNED_PHYSICAL_FORWARD_ROWS",
    "PLANNED_COMPARISON_CALLS",
    "WORKER_SCRIPT_ROLE",
    "RUNTIME_LOCK_ROLE",
    "RUNTIME_POLICY_ROLE",
    "RUNTIME_ASSET_ROLES",
    "PRIMARY_RUNTIME_ASSET_ROLE",
    "RUNTIME_ASSET_SOURCES",
    "JOB_DEADLINE_SECONDS",
    "RAW_SCORE_DECIMAL_METADATA_KEY",
    "FORBIDDEN_CONFIG_KEYS",
    "REQUIRED_REPORTING_SWITCHES",
    "PERMITTED_DOWNSTREAM_EXPERIMENTS",
    "REQUIRED_EVIDENCE_FILES",
    "OPTIONAL_EVIDENCE_FILES",
    "all_frozen_identifiers",
]

STAGE_8C_SCHEMA_VERSION = "1"

# ------------------------------------------------------------------- identity
EXPERIMENT_ID = "flx_canonical500_full_v1"
INTEGRATION_ID = "flx_deepprint_texminu_research_v1"
EXECUTION_PROFILE_ID = "flx_canonical500_sequential_no_retry_v1"
ALIGNMENT_PROFILE_ID = "flx_canonical500_alignment_v1"
STAGE_FINALIZATION_KIND = "stage_8c_finalization"

#: Where a committed copy of this run's evidence lives (spec section 28).
EVIDENCE_DIRECTORY = Path("evidence") / "flx-canonical500-raw"

#: The alignment report, cached beside the run's other derived artefacts. Like
#: every ``derived/`` file it is regenerable and never trusted: finalization
#: re-derives it from the manifests and compares (docs/adr/0012).
ALIGNMENT_REPORT_NAME = "canonical-run-alignment.json"

#: The last-written authority, and the last file committed (spec section 26).
STAGE_8C_FINALIZATION_NAME = "stage-8c-finalization.json"

# --------------------------------------------------------- the Stage 8B route
# Restated from evidence/stage8b-flx-runtime-qualification/. Preparation reads
# the published documents and refuses on any disagreement, so these are a
# reviewable copy of an authority rather than a second authority.
STAGE8B_FINALIZATION_FINGERPRINT = (
    "aa6897bf25c7b6565647da3566e6ab6446ae6104b2511034fed0fdb08cb13373"
)
STAGE8B_OUTCOME = "FLX_RAW_SCORE_EXECUTION_READY"

ALGORITHM_ID = "flx_deepprint_texminu_512_without_localization"
ADAPTER_ID = "flx_pytorch_subprocess"
ADAPTER_VERSION = 1

RUNTIME_PROFILE_ID = "flx_cpu_linux_x86_64_v1"
RUNTIME_MANIFEST_FINGERPRINT = (
    "948dd24f43835bc5a9777ef75e2ba4f31950d26a850bda971032d0ae08857a02"
)
PREPROCESSING_PROFILE_ID = "fpbench_canonical500_to_flx299_squarepad_v1"
PREPROCESSING_PROFILE_FINGERPRINT = (
    "9c0bbb9c5eabe646051fa659bee0aad7de50b7e56d566cc0d2d55fc4ab2e19f2"
)
REPRESENTATION_PROFILE_ID = "flx_texminu_256x2_v1"
REPRESENTATION_PROFILE_FINGERPRINT = (
    "7b9f84b05feaf61d3050bd489561d52c80d825d449e11490360b4e197b3a25a5"
)
SCORE_PROFILE_ID = "flx_texminu_equal_branch_dot_v1"
SCORE_PROFILE_FINGERPRINT = (
    "69848f2416a997484430ce0f6b5cf054586cb0e58968e986479e90ddc6563a61"
)
ADAPTER_PROFILE_FINGERPRINT = (
    "dc4c0ccc1fdb4028584f38c340e1761bd3261bf01e42b965f1785425fcc7d84c"
)

# ------------------------------------------------------------------ artifacts
SOURCE_COMMIT = "7accfca1f33b9b42bfd220e43cd5bc13b4a7fa13"
SOURCE_ARCHIVE_SHA256 = (
    "60fa2c8894ea90efe2bb0553cd331d8ef84611b973b6126eaf6d162d1aa9b7e2"
)
CHECKPOINT_FILENAME = "best_model.pyt"
CHECKPOINT_SHA256 = (
    "2683a04427bacd54adc00cfdc97474625b1e11e5a9e6672c5129f033018f8a28"
)
CHECKPOINT_SIZE_BYTES = 875770140

# ------------------------------------------------------- the canonical run
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

# ---------------------------------------------------------------- the shape
EXPECTED_JOBS = 6000
EXPECTED_PARTICIPATING_IMAGES = 3000
EXPECTED_SUBJECTS = 50
EXPECTED_RELEASES = ("SD300A", "SD300B", "SD300C")
EXPECTED_PER_RELEASE_STAGE = 500

# ------------------------------------------------------------- the operations
#
# Two sides, prepared and extracted independently, then one comparison. SELF is
# not a special case: both sides of a SELF pair go through their own preprocess
# and their own extraction, and the two representations are distinct objects
# even when their contents are bitwise equal (spec section 9).
PREPROCESS_CALLS_PER_COMPARISON = 2
LOGICAL_EXTRACTIONS_PER_COMPARISON = 2
COMPARISONS_PER_JOB = 1

#: Re-exported from Stage 8B rather than restated, because the doubling is a
#: property of the pinned texture branch and not a Stage 8C choice
#: (docs/adr/0070). The assertion that the two agree is a contract test.
INFERENCE_BATCH_ROWS = 2

PLANNED_PREPROCESS_CALLS = EXPECTED_JOBS * PREPROCESS_CALLS_PER_COMPARISON
PLANNED_LOGICAL_EXTRACTIONS = EXPECTED_JOBS * LOGICAL_EXTRACTIONS_PER_COMPARISON
#: 24,000. Never called "extractions" (docs/adr/0075).
PLANNED_PHYSICAL_FORWARD_ROWS = PLANNED_LOGICAL_EXTRACTIONS * INFERENCE_BATCH_ROWS
PLANNED_COMPARISON_CALLS = EXPECTED_JOBS * COMPARISONS_PER_JOB

# ----------------------------------------------------------- the pinned bytes
#
# Three small, committed, repository-owned files. The source archive and the
# 875 MB checkpoint are pinned by frozen digest and re-hashed before every model
# load instead of being copied: a second copy of licence-unresolved weights in
# the workspace is a redistribution nobody has established permission for
# (docs/adr/0077, docs/adr/0068, docs/adr/0072).
WORKER_SCRIPT_ROLE = "flx_worker_script"
RUNTIME_LOCK_ROLE = "flx_runtime_lock"
RUNTIME_POLICY_ROLE = "flx_runtime_policy"
RUNTIME_ASSET_ROLES = (WORKER_SCRIPT_ROLE, RUNTIME_LOCK_ROLE, RUNTIME_POLICY_ROLE)
PRIMARY_RUNTIME_ASSET_ROLE = WORKER_SCRIPT_ROLE

#: Where each pinned role comes from, relative to the repository root.
RUNTIME_ASSET_SOURCES = {
    WORKER_SCRIPT_ROLE: "integrations/flx/worker/flx_worker.py",
    RUNTIME_LOCK_ROLE: "configs/flx/flx_runtime_lock_v1.txt",
    RUNTIME_POLICY_ROLE: "configs/flx/stage8b_flx_runtime_policy_v1.yaml",
}

#: The engine's whole-job deadline. It covers two preprocess calls, two
#: extractions, one comparison and a 60 s orchestration margin, and it does not
#: replace Stage 8B's per-operation deadlines (spec section 11).
JOB_DEADLINE_SECONDS = 480

#: Where the canonical 17-significant-digit text of a raw score is stored. The
#: IEEE double in ``raw_score`` is the same number; 17 digits is the count that
#: always recovers a double exactly, and the validator proves the two agree for
#: every stored success (docs/adr/0077, docs/adr/0073).
RAW_SCORE_DECIMAL_METADATA_KEY = "flx.raw_score_decimal"

# ------------------------------------------------------------- what is refused
#
# Refused at any depth of a Stage 8C configuration document. Each one would mean
# this stage had decided what a score means, and the flx scale has no threshold
# anybody has earned the right to write down (docs/adr/0076, spec section 17).
FORBIDDEN_CONFIG_KEYS: frozenset[str] = frozenset(
    {
        "threshold",
        "decision_profile",
        "match_threshold",
        "acceptance_threshold",
        "calibration",
        "eer",
        "far",
        "fmr",
        "fnmr",
        "roc",
        "det",
        "score_bins",
        "score_statistics",
    }
)

#: The four reporting switches and the only value each may hold. ``score_statistics``
#: is on the forbidden list *and* required here; it is the single fixed
#: exception, allowed only as ``reporting.score_statistics: false`` and nowhere
#: else in the document (spec section 17).
REQUIRED_REPORTING_SWITCHES = {
    "operational_summary": True,
    "biometric_metrics": False,
    "score_statistics": False,
    "score_export": False,
}

#: The experiments entitled to derive from this run.
#:
#: Empty, and it stays empty for as long as Stage 8C is the last word. A
#: decision set over these scores would mean somebody chose a threshold for the
#: flx scale, and there is no such threshold to choose: Stage 8D must freeze its
#: source, comparator and boundary semantics in a separate prior act, and may
#: not choose it from these scores (docs/adr/0076, spec sections 27 and 39).
PERMITTED_DOWNSTREAM_EXPERIMENTS: frozenset[str] = frozenset()

#: Exactly what ``evidence/flx-canonical500-raw/`` holds. An extra file is a
#: finding (spec section 28).
REQUIRED_EVIDENCE_FILES = (
    "README.md",
    "research-receipt.json",
    "research-finalization.json",
    "alignment-report.json",
    "operational-summary.json",
    "runtime-provenance.json",
    "algorithm-validation.json",
    STAGE_8C_FINALIZATION_NAME,
)

#: ``run_<run_id>.json`` cannot be named before the run exists, so it is matched
#: by shape rather than listed. Exactly one must be present.
OPTIONAL_EVIDENCE_FILES = ()


def all_frozen_identifiers() -> tuple[str, ...]:
    """Every Stage 8C identifier, validated as a safe path and key component."""
    identifiers = (
        EXPERIMENT_ID,
        INTEGRATION_ID,
        EXECUTION_PROFILE_ID,
        ALIGNMENT_PROFILE_ID,
        STAGE_FINALIZATION_KIND,
        ALGORITHM_ID,
        ADAPTER_ID,
        RUNTIME_PROFILE_ID,
        PREPROCESSING_PROFILE_ID,
        REPRESENTATION_PROFILE_ID,
        SCORE_PROFILE_ID,
        PREPARATION_SET_ID,
        TRANSFORM_PROFILE_ID,
        *RUNTIME_ASSET_ROLES,
    )
    for identifier in identifiers:
        validate_id(identifier)
    return identifiers
