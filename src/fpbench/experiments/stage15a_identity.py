"""What Stage 15A is, frozen in code rather than only in a configuration file.

Stage 15A is the first Algorithm 5 candidate that needed nobody's permission and
nobody's answer. Three predecessors ended at a vendor: Innovatrics refused an
evaluation licence, FingerCell's trial entitlement never arrived, and Griaule was
never asked because no official route serves the package. The selection rule
changed in response, and it is the first thing this module freezes: self-service
acquisition and runnable-without-vendor-action are now hard requirements
(docs/adr/0126).

What follows from that is a stage with no acquisition preflight and no readiness
stage in front of it. The artifact is 4,492 bytes of pure Python on PyPI under
MIT. It is either qualified and run in one pass, or it is not Algorithm 5.

Nothing here is a threshold, a calibration profile, an FMR target or a score
statistic, and nothing here will become one. Stage 15A ends at 6,000 stored raw
outcomes (spec sections 21, 33 and 35).
"""

from __future__ import annotations

from pathlib import Path

from fpbench.adapters.fingerprints_matching import identity as adapter_identity

__all__ = [
    "CANDIDATE_ID",
    "ALGORITHM_SLOT",
    "IMPLEMENTATION_ORIGIN",
    "PACKAGE_NAME",
    "PACKAGE_VERSION",
    "PACKAGE_REQUIREMENT",
    "RUNTIME_ARTIFACT_SHA256",
    "SOURCE_ARTIFACT_SHA256",
    "RUNTIME_ARTIFACT_NAME",
    "SOURCE_ARTIFACT_NAME",
    "RUNTIME_ARTIFACT_SIZE_BYTES",
    "SOURCE_ARTIFACT_SIZE_BYTES",
    "LICENSE",
    "UPSTREAM_INDEX",
    "PRODUCTION_ALGORITHM_ID",
    "ADAPTER_ID",
    "ADAPTER_VERSION",
    "EXPERIMENT_ID",
    "EVIDENCE_DIRECTORY",
    "STAGE_15A_FINALIZATION_NAME",
    "EVIDENCE_DOCUMENTS",
    "OUTCOME_COMPLETE",
    "OUTCOME_FAIL",
    "OUTCOMES",
    "GATES",
    "GATE_ORDER",
    "GATE_STATES",
    "SELECTION_POLICY",
    "SUPERSEDED_CANDIDATE",
    "STAGE_14A_FINAL_OUTCOME",
    "REASON_NOT_CONTINUED",
    "VENDOR_REQUEST_SENT",
    "RESERVE_CANDIDATE",
    "OUT_OF_QUEUE_CANDIDATES",
    "ENTRY_MODULE",
    "ENTRY_CLASS",
    "ENTRY_FUNCTION",
    "ENTRY_QUALNAME",
    "UPSTREAM_MODULE_DIGESTS",
    "UPSTREAM_ROUTE_STEPS",
    "REFUSED_FPBENCH_STEPS",
    "LEFT_ARGUMENT",
    "RIGHT_ARGUMENT",
    "SCORE_NATIVE_TYPE",
    "SCORE_DIRECTION",
    "SCORE_RANGE",
    "FPBENCH_SCORE_TRANSFORMATION",
    "DECISION_THRESHOLD",
    "UPSTREAM_README_THRESHOLD",
    "SYMMETRY_REQUIRED",
    "PINNED_PYTHON_VERSION",
    "PINNED_PLATFORM",
    "PINNED_MACHINE",
    "PINNED_NUMPY",
    "PINNED_OPENCV",
    "RUNTIME_WHEELS",
    "OPENCV_GENERATION_RULE",
    "QUALIFICATION_MAX_COMPARISONS",
    "QUALIFICATION_CASES",
    "FAILURE_PROBES",
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
    "EXPECTED_MATCH_INVOCATIONS",
    "BOUND_MARKERS",
    "FORBIDDEN_READS",
    "FORBIDDEN_CONFIG_KEYS",
    "REQUIRED_REPORTING_SWITCHES",
    "HARD_FAIL_CONDITIONS",
]


# ------------------------------------------------------------ candidate identity
#
# Imported from the adapter package rather than restated here. The adapter has to
# know who it is, an adapter may not import this layer, and two copies of a
# digest is one copy too many.

CANDIDATE_ID = adapter_identity.ALGORITHM_ID
ALGORITHM_SLOT = "algorithm_5"
IMPLEMENTATION_ORIGIN = adapter_identity.IMPLEMENTATION_ORIGIN

PACKAGE_NAME = adapter_identity.PACKAGE_NAME
PACKAGE_VERSION = adapter_identity.PACKAGE_VERSION
PACKAGE_REQUIREMENT = adapter_identity.PACKAGE_REQUIREMENT

RUNTIME_ARTIFACT_NAME = adapter_identity.RUNTIME_ARTIFACT_NAME
RUNTIME_ARTIFACT_SHA256 = adapter_identity.RUNTIME_ARTIFACT_SHA256
RUNTIME_ARTIFACT_SIZE_BYTES = adapter_identity.RUNTIME_ARTIFACT_SIZE_BYTES

SOURCE_ARTIFACT_NAME = adapter_identity.SOURCE_ARTIFACT_NAME
SOURCE_ARTIFACT_SHA256 = adapter_identity.SOURCE_ARTIFACT_SHA256
SOURCE_ARTIFACT_SIZE_BYTES = adapter_identity.SOURCE_ARTIFACT_SIZE_BYTES

LICENSE = adapter_identity.LICENSE
UPSTREAM_INDEX = adapter_identity.UPSTREAM_INDEX

PRODUCTION_ALGORITHM_ID = adapter_identity.ALGORITHM_ID
ADAPTER_ID = adapter_identity.ADAPTER_ID
ADAPTER_VERSION = adapter_identity.ADAPTER_VERSION


# --------------------------------------------------------------------- the stage

EXPERIMENT_ID = "fingerprints_matching_canonical500_full_v1"
EVIDENCE_DIRECTORY = Path("evidence/stage15a-fingerprints-matching")
STAGE_15A_FINALIZATION_NAME = "stage-15a-finalization.json"

#: Eight documents, and no ninth. Stage 12A and Stage 13A each published thirteen
#: for candidates that never produced a score; the cost of that is what this
#: stage's shape is a reaction to.
EVIDENCE_DOCUMENTS: tuple[str, ...] = (
    "README.md",
    "predecessor-selection.json",
    "artifact-runtime-identity.json",
    "upstream-route-contract.json",
    "qualification.json",
    "canonical-run-binding.json",
    "result-integrity.json",
    STAGE_15A_FINALIZATION_NAME,
)

OUTCOME_COMPLETE = "FINGERPRINTS_MATCHING_CANONICAL500_RAW_COMPLETE"
OUTCOME_FAIL = "FINGERPRINTS_MATCHING_QUALIFICATION_FAIL"

#: The only two strings that close this stage. There is no pending state and no
#: incomplete state, because nothing here waits on anybody: every input is a
#: public artifact this project can fetch, hash and run by itself.
OUTCOMES: tuple[str, ...] = (OUTCOME_COMPLETE, OUTCOME_FAIL)


# ---------------------------------------------------------------------- the gates

GATES: dict[str, str] = {
    "G1": "ARTIFACT_AND_RUNTIME_IDENTITY",
    "G2": "UPSTREAM_IMAGE_TO_SCORE_CONTRACT",
    "G3": "DETERMINISM_AND_FAILURE_CONTRACT",
    "G4": "PRODUCTION_ADAPTER_FREEZE",
    "G5": "CANONICAL500_RAW_EXECUTION",
    "G6": "RESULTSET_INTEGRITY_AND_FINALIZATION",
}
GATE_ORDER: tuple[str, ...] = ("G1", "G2", "G3", "G4", "G5", "G6")

#: Four states and no fifth. ``PENDING_ACCESS`` does not exist in this stage's
#: vocabulary: a self-service candidate can never be waiting on a vendor, and a
#: state nobody can reach is a state that will eventually be reached by accident.
GATE_STATES: tuple[str, ...] = ("PASS", "FAIL", "NOT_REACHED", "ACTION_REQUIRED")


# ------------------------------------------------- what this supersedes, and why

#: The rule that retired the commercial search. Both are hard requirements: a
#: candidate that needs a vendor to act is not a candidate this project can
#: qualify on its own schedule, and three consecutive stages proved it.
SELECTION_POLICY: dict[str, str] = {
    "self_service_acquisition": "HARD_REQUIREMENT",
    "runnable_without_vendor_action": "HARD_REQUIREMENT",
}

SUPERSEDED_CANDIDATE = "griaule_gbs_fingerprint_sdk_1to1"

#: Stage 14A has no final outcome and is not being given one. It remains a
#: non-final investigation in which nobody was ever contacted, and turning that
#: into a FAIL after the fact would publish a vendor position that does not exist
#: (docs/adr/0104, docs/adr/0121).
STAGE_14A_FINAL_OUTCOME = "NONE"
REASON_NOT_CONTINUED = "SELF_SERVICE_ACQUISITION_NOT_ESTABLISHED"
VENDOR_REQUEST_SENT = False

RESERVE_CANDIDATE = "fingerflow_3_0_1"

#: Closed by the research that selected this candidate, and not reopened here.
OUT_OF_QUEUE_CANDIDATES: tuple[str, ...] = (
    "fingerprintMatcher",
    "MCC",
    "OpenAFIS",
    "JIPNet",
    "AFR-Net",
    "IDKit",
    "FingerCell",
    "Griaule",
    "id3",
)


# ------------------------------------------------------------- the upstream route

ENTRY_MODULE = adapter_identity.ENTRY_MODULE
ENTRY_CLASS = adapter_identity.ENTRY_CLASS
ENTRY_FUNCTION = adapter_identity.ENTRY_FUNCTION
ENTRY_QUALNAME = adapter_identity.ENTRY_QUALNAME
UPSTREAM_MODULE_DIGESTS = adapter_identity.UPSTREAM_MODULE_DIGESTS

#: Every step between two paths and a float, and all of them upstream's. Read out
#: of the installed module, not out of the package's README.
UPSTREAM_ROUTE_STEPS: tuple[str, ...] = (
    "image_path1, image_path2",
    "cv2.imread",
    "cv2.cvtColor BGR2GRAY",
    "cv2.threshold THRESH_BINARY_INV|THRESH_OTSU",
    "cv2.findContours RETR_EXTERNAL CHAIN_APPROX_SIMPLE",
    "cv2.convexHull returnPoints=False",
    "cv2.convexityDefects",
    "minutiae_matching.extract_minutiae x2",
    "minutiae_matching.match",
    "python float",
)

#: What fpbench does not add. Each of these exists inside the package route or
#: not at all; inserting one here would make the benchmark a co-author of the
#: algorithm.
REFUSED_FPBENCH_STEPS: tuple[str, ...] = (
    "alignment",
    "crop",
    "enhancement",
    "resize",
    "roi",
    "score_transform",
    "segmentation",
    "thresholding",
)


# -------------------------------------------------------------- the score contract

LEFT_ARGUMENT = adapter_identity.LEFT_ARGUMENT
RIGHT_ARGUMENT = adapter_identity.RIGHT_ARGUMENT

SCORE_NATIVE_TYPE = "float"
SCORE_DIRECTION = adapter_identity.SCORE_DIRECTION

#: Upstream declares no range and fpbench does not derive one. The matcher
#: normalises by ``len(minutiae1)`` and clamps each per-minutia contribution at
#: zero, which bounds the value in practice — but a bound nobody published is an
#: observation, and publishing it as a contract would invite a later stage to
#: build a threshold on it.
SCORE_RANGE = adapter_identity.SCORE_RANGE

FPBENCH_SCORE_TRANSFORMATION = adapter_identity.FPBENCH_SCORE_TRANSFORMATION
DECISION_THRESHOLD = adapter_identity.DECISION_THRESHOLD

#: The package's README suggests 0.9 separates same-finger from different-finger.
#: It is upstream's guidance to its own users, it is recorded because it exists,
#: and it is not fpbench's threshold, not an operating point and not calibration.
UPSTREAM_README_THRESHOLD = 0.9

#: Not required, and its absence is not a defect. ``match`` divides by
#: ``len(minutiae1)``, so the first argument sets the denominator and the two
#: orderings are different questions. Observed asymmetry binds left to the first
#: argument and right to the second, in the algorithm's identity (docs/adr/0109).
SYMMETRY_REQUIRED = adapter_identity.SYMMETRY_REQUIRED


# ------------------------------------------------------------- the frozen runtime
#
# Imported for the same reason the identity above is: the adapter verifies this
# closure before it reports itself ready, and it may not import this layer.

PINNED_PYTHON_VERSION = adapter_identity.PINNED_PYTHON_VERSION
PINNED_PLATFORM = adapter_identity.PINNED_PLATFORM
PINNED_MACHINE = adapter_identity.PINNED_MACHINE

PINNED_NUMPY = adapter_identity.PINNED_NUMPY
PINNED_OPENCV = adapter_identity.PINNED_OPENCV
PINNED_CV2_LIBRARY = adapter_identity.PINNED_CV2_LIBRARY

RUNTIME_WHEELS = adapter_identity.RUNTIME_WHEELS
OPENCV_GENERATION_RULE = adapter_identity.OPENCV_GENERATION_RULE


# ----------------------------------------------------------------- qualification

#: G3 spends at most twenty comparisons. It is a determinism and failure-contract
#: proof, not a second research stage.
QUALIFICATION_MAX_COMPARISONS = 20

QUALIFICATION_CASES: tuple[str, ...] = (
    "A_B_repeated",
    "A_B_fresh_object",
    "A_B_fresh_process",
    "B_A",
    "A_A",
)

FAILURE_PROBES: tuple[str, ...] = (
    "blank_valid_image",
    "malformed_image",
    "missing_path",
    "unreadable_invalid_image",
)


# --------------------------------------------------------------------- execution

EXECUTION_PROFILE_ID = "fingerprints_matching_canonical500_sequential_no_retry_v1"

#: Generous against a route whose whole cost is one decode, one Otsu pass and an
#: O(n1·n2) loop in Python. Fixed before the canonical set was opened, from
#: qualification timings alone: a deadline tuned after seeing which pairs are
#: slow has stopped being a guard (spec section 28).
JOB_DEADLINE_SECONDS = adapter_identity.JOB_DEADLINE_SECONDS
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


# --------------------------------------------------------------------- the workload

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
EXPECTED_SOURCE_PPI: dict[str, int] = {"SD300A": 500, "SD300B": 1000, "SD300C": 2000}

#: Two extractions and one match per comparison, SELF included. The upstream
#: entry point performs both extractions itself and shares nothing between them,
#: which is what makes SELF an honest two-sided comparison rather than a cache
#: hit (spec sections 14 and 27).
EXPECTED_LOGICAL_EXTRACTIONS = EXPECTED_JOBS * 2
EXPECTED_MATCH_INVOCATIONS = EXPECTED_JOBS


# ------------------------------------------------------------------ what is bound

BOUND_MARKERS: tuple[dict[str, str], ...] = (
    {
        "stage": "14A",
        "outcome": STAGE_14A_FINAL_OUTCOME,
        "why": (
            "the superseded candidate. Bound as a non-final investigation with no "
            "request sent, and left exactly as HEAD published it"
        ),
    },
    {
        "stage": "11B",
        "finalization_fingerprint": (
            "3d271490edda9e3e9d066485c2d93e82e2eceb4556668df7d65a8207e591684c"
        ),
        "outcome": "VERIFINGER_CANONICAL500_RAW_COMPLETE",
        "why": (
            "Algorithm 4's 6,000 published outcomes, and the run this one is "
            "aligned against. Bound and never read for its scores"
        ),
    },
    {
        "stage": "8E",
        "finalization_fingerprint": (
            "c08648dece292603eb9d4b6fff0b3412523af0730da59141b6e7a32ee02540e8"
        ),
        "outcome": "RESEARCH_ONLY_THIRD_PARTY_POLICY_READY",
        "why": "the third-party research-use policy, reused and not reopened",
    },
)

FORBIDDEN_READS: tuple[str, ...] = (
    "sourceafis_scores",
    "nbis_scores",
    "flx_scores",
    "verifinger_scores",
)

#: Keys that would turn this into a decision, calibration or evaluation stage.
#: Refused wherever they appear in the experiment document, at any depth.
FORBIDDEN_CONFIG_KEYS: frozenset[str] = adapter_identity.FORBIDDEN_CONFIG_KEYS

REQUIRED_REPORTING_SWITCHES: dict[str, bool] = {
    "operational_summary": True,
    "biometric_metrics": False,
    "score_statistics": False,
    "score_export": False,
}


# ------------------------------------------------------------ hard fail conditions

#: Any one of these closes Stage 15A and reopens the Algorithm 5 search at the
#: reserve candidate. A print the algorithm cannot process is deliberately not on
#: this list, as long as the refusal is deterministic and carries no score.
HARD_FAIL_CONDITIONS: tuple[str, ...] = (
    "PUBLISHED_BYTES_DO_NOT_MATCH_PINNED_ARTIFACTS",
    "CANONICAL_IMAGE_CANNOT_ENTER_UPSTREAM_ROUTE_DIRECTLY",
    "RAW_SCORE_REQUIRES_FPBENCH_TO_CHOOSE_A_THRESHOLD",
    "FPBENCH_MUST_IMPLEMENT_OR_REPAIR_THE_SCORE_FORMULA",
    "ZERO_FEATURE_CASE_REQUIRES_AN_INVENTED_FALLBACK_SCORE",
    "SAME_FROZEN_INPUT_AND_PROCESS_IS_NONDETERMINISTIC",
    "RUNTIME_DEPENDENCY_CANNOT_BE_FROZEN_REPRODUCIBLY",
    "EXECUTION_PRODUCES_INFRASTRUCTURE_LEVEL_INSTABILITY",
    "RESULT_SET_IS_NOT_SCORE_BEARING",
)
