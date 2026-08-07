"""Everything Stage 8D froze before the calibration engine was written.

These constants are the stage's contract with itself. They are asserted by the
contract tests, checked against the published evidence of the stages they
restate, and republished in the Stage 8D finalization. A later change to any of
them is a different stage with a different identity rather than a quiet
correction to this one.

Nothing here is derived at import time, nothing here reads a workspace, and
nothing here is a score. The protected identities below are exactly that —
identities — copied from documents that were published to be read: run ids, run
fingerprints, result-set fingerprints, a cohort fingerprint, a pair-manifest
hash. Stage 8D reads no score row of any of them (docs/adr/0079, spec section 24).

This module exists for the same reason :mod:`fpbench.experiments.stage8c_identity`
does: the registry builder, the synthetic qualification and the finalization
marker all need the frozen values, and a shared constant module is the
alternative to an import cycle between them.
"""

from __future__ import annotations

from pathlib import Path

from fpbench.core.enums import ProtectedIdentityKind
from fpbench.core.identifiers import validate_id

__all__ = [
    "STAGE_8D_SCHEMA_VERSION",
    "STAGE_FINALIZATION_KIND",
    "STAGE_8D_OUTCOME",
    "EVIDENCE_DIRECTORY",
    "STAGE_8D_FINALIZATION_NAME",
    "PROTECTED_REGISTRY_NAME",
    "SYNTHETIC_QUALIFICATION_NAME",
    "CONTRACT_REPORT_NAME",
    "REQUIRED_EVIDENCE_FILES",
    "REGISTRY_ID",
    "REGISTRY_VERSION",
    "PROTECTED_IDENTITIES",
    "PROTECTED_SOURCE_DOCUMENTS",
    "STAGE8C_FINALIZATION_FINGERPRINT",
    "STAGE8C_OUTCOME",
    "FORBIDDEN_PUBLISHED_KEYS",
    "CALIBRATION_PACKAGE_MODULES",
    "STAGE_8D_SOURCE_FILES",
    "all_frozen_identifiers",
]

STAGE_8D_SCHEMA_VERSION = "1"
STAGE_FINALIZATION_KIND = "stage_8d_finalization"

#: What a complete Stage 8D asserts, and the exact spelling of it. It says the
#: machinery exists and was qualified on synthetic fixtures. It does not say a
#: threshold was chosen (docs/adr/0078).
STAGE_8D_OUTCOME = "CALIBRATION_INFRASTRUCTURE_READY"

EVIDENCE_DIRECTORY = Path("evidence") / "stage8d-calibration-infrastructure"

#: The last-written authority, and the last file committed.
STAGE_8D_FINALIZATION_NAME = "stage-8d-finalization.json"
PROTECTED_REGISTRY_NAME = "protected-evaluation-registry.json"
SYNTHETIC_QUALIFICATION_NAME = "synthetic-qualification.json"
CONTRACT_REPORT_NAME = "calibration-contract-report.json"

#: Exactly what the evidence directory holds. An extra file is a finding.
REQUIRED_EVIDENCE_FILES = (
    "README.md",
    SYNTHETIC_QUALIFICATION_NAME,
    PROTECTED_REGISTRY_NAME,
    CONTRACT_REPORT_NAME,
    STAGE_8D_FINALIZATION_NAME,
)

# ----------------------------------------------------------- the closed stage
#
# Restated from evidence/flx-canonical500-raw/. Stage 8D reads that marker to
# confirm the stage it follows is the stage it thinks it follows, and refuses on
# disagreement. Nothing under that directory is edited (docs/adr/0078).
STAGE8C_FINALIZATION_FINGERPRINT = (
    "0c09483efb92b3e6689cb202f2ce0af193e237791c40ed95ff3a698f179abec2"
)
STAGE8C_OUTCOME = "FLX_CANONICAL500_RAW_READY"

# ------------------------------------------------------- protected evaluation
#
# The identities of the material a calibration may never draw a threshold from:
# the dataset, the one cohort this project has, the canonical pair manifest, the
# shared prepared-image set, and the canonical run and ResultSet of each
# algorithm that has executed the 6,000 comparisons.
#
# Every value here appears verbatim in a committed evidence document, and the
# registry builder re-reads those documents and refuses on any disagreement — so
# this is a reviewable copy of an authority rather than a second authority.
#
# The labels are prose for a reader. Nothing in ``fpbench.calibration`` reads
# them, and nothing anywhere branches on them: the engine asks only whether a
# binding's fingerprint is in this set (docs/adr/0079).
REGISTRY_ID = "fpbench_protected_evaluation_v1"
REGISTRY_VERSION = "1"

PROTECTED_IDENTITIES: tuple[tuple[ProtectedIdentityKind, str, str, str], ...] = (
    (
        ProtectedIdentityKind.DATASET,
        "sd300",
        "c2ab03a5bb20ccef2c00e5f0522b641941cb93e2676a506eae192b6251813ba9",
        "NIST SD300, by the image manifest hash of the release this project reads",
    ),
    (
        ProtectedIdentityKind.COHORT,
        "sd300_50_subjects_test_22f8d52a7478",
        "3648aa599b07828638742c102f2ab25bb1ac4a9630f1058adc62359164c456f4",
        "the 50-subject evaluation cohort; the only cohort drawn so far",
    ),
    # Identified by its hash on both sides, because that is the only identity
    # this project ever gave it: every document that cites the canonical pair
    # manifest cites ``pair_manifest_hash``, and there is no ``pair_manifest_id``
    # anywhere to copy. Inventing a readable name here would be inventing an
    # identity, which is the one thing a protected-identity list must not do.
    (
        ProtectedIdentityKind.PAIR_MANIFEST,
        "ee4d942e23cdc112e17ed69e0abc603d5f26e17cc5839edc9aa412edc57dfe3b",
        "ee4d942e23cdc112e17ed69e0abc603d5f26e17cc5839edc9aa412edc57dfe3b",
        "the frozen 6,000-comparison pair manifest every algorithm was given",
    ),
    (
        ProtectedIdentityKind.PREPARATION_SET,
        "prepset_be560e047991",
        "be560e047991a0d58af8f86a4576f8b78dc350e643af82f0e2405350d9e2fd3f",
        "the shared canonical 500 ppi prepared-image set",
    ),
    (
        ProtectedIdentityKind.RUN,
        "run_4c59fa02a6ab",
        "4c59fa02a6ab0471bdd46e134c61d74a7b6463276bf7c1bb6bd2e217622ceb5a",
        "the SourceAFIS canonical_500 run",
    ),
    (
        ProtectedIdentityKind.RESULT_SET,
        "resultset_087b084fb8a8",
        "087b084fb8a8001eb92e20d4900dfc759dc5abbc9d5346144c83f5298f61e38b",
        "the SourceAFIS canonical_500 result set",
    ),
    (
        ProtectedIdentityKind.RUN,
        "run_f0468f28ffba",
        "f0468f28ffba544fc7f2df0d4e9844cc0c6f0ed8e5359fd338d49ab6e8022c9f",
        "the NBIS canonical_500 run",
    ),
    (
        ProtectedIdentityKind.RESULT_SET,
        "resultset_73a9d93a8528",
        "73a9d93a8528e95322b69c64af416a234e7bd100cbb6556e66f1ae8c1cdd7fff",
        "the NBIS canonical_500 result set",
    ),
    (
        ProtectedIdentityKind.RUN,
        "run_902136b3b8ae",
        "902136b3b8ae72747959395fb06bd9586a911505adb8b9e7a1d1e13bb32da884",
        "the flx canonical_500 run",
    ),
    (
        ProtectedIdentityKind.RESULT_SET,
        "resultset_d63e523e0436",
        "d63e523e04369ee4e7d57ed63bac3980e656425a832759b71315ca3fc155be5a",
        "the flx canonical_500 result set",
    ),
)

#: Where each protected identity is published, and which keys of that document
#: carry it. The builder reads exactly these keys and nothing else: it never
#: opens a results file, a parquet, or a workspace (spec section 24).
PROTECTED_SOURCE_DOCUMENTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "evidence/sd300-canonical500-images/prepset_be560e047991.json",
        (
            "dataset_id",
            "image_manifest_hash",
            "cohort_id",
            "cohort_fingerprint",
            "pair_manifest_hash",
            "preparation_set_id",
            "preparation_set_fingerprint",
        ),
    ),
    (
        "evidence/sourceafis-canonical500-full/run_4c59fa02a6ab.json",
        ("run_id", "run_fingerprint", "result_set_id", "result_set_fingerprint"),
    ),
    (
        "evidence/nbis-canonical500-raw/stage-7c-finalization.json",
        ("run_id", "run_fingerprint", "result_set_id", "result_set_fingerprint"),
    ),
    (
        "evidence/flx-canonical500-raw/stage-8c-finalization.json",
        ("run_id", "run_fingerprint", "result_set_id", "result_set_fingerprint"),
    ),
)

# ------------------------------------------------------------- what is refused
#
# Refused at any depth of a published Stage 8D document. Each one would mean a
# real score, a real threshold or a distribution of either had reached the
# evidence of a stage that claims to have read none (spec section 36).
FORBIDDEN_PUBLISHED_KEYS: frozenset[str] = frozenset(
    {
        "threshold",
        "thresholds",
        "score",
        "scores",
        "raw_score",
        "raw_scores",
        "score_rows",
        "score_statistics",
        "score_distribution",
        "histogram",
        "percentile",
        "mean_score",
        "median_score",
        "min_score",
        "max_score",
        "roc",
        "det",
        "eer",
        "fmr",
        "fnmr",
        "far",
        "frr",
        "embedding",
        "embeddings",
        "subject_id",
        "subject_ids",
        "finger",
        "finger_id",
        "finger_ids",
        "image_id",
        "image_ids",
        "pair_id",
        "pair_ids",
    }
)

#: The modules the calibration package consists of. Named rather than globbed so
#: that a new module has to be added here deliberately, and so the structural
#: tests fail loudly if one is deleted.
CALIBRATION_PACKAGE_MODULES: tuple[str, ...] = (
    "__init__.py",
    "models.py",
    "protocol.py",
    "selection.py",
    "validation.py",
    "profiles.py",
    "verify.py",
)

#: Every source file Stage 8D owns outright, audited for import boundaries.
STAGE_8D_SOURCE_FILES: tuple[str, ...] = (
    *(f"src/fpbench/calibration/{name}" for name in CALIBRATION_PACKAGE_MODULES),
    "src/fpbench/core/calibration_models.py",
    "src/fpbench/storage/calibration_store.py",
    "src/fpbench/experiments/stage8d_identity.py",
    "src/fpbench/experiments/stage8d_calibration_infrastructure.py",
    "src/fpbench/experiments/stage8d_finalization.py",
)


def all_frozen_identifiers() -> tuple[str, ...]:
    """Every Stage 8D identifier, validated as a safe path and key component."""
    identifiers = (
        REGISTRY_ID,
        STAGE_FINALIZATION_KIND,
        *(identity for _kind, identity, _fingerprint, _label in PROTECTED_IDENTITIES),
    )
    for identifier in identifiers:
        validate_id(identifier)
    return identifiers
