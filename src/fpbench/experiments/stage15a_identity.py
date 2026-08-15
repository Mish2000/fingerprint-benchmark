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

CANDIDATE_ID = "fingerprints_matching_0_1_0"
ALGORITHM_SLOT = "algorithm_5"
IMPLEMENTATION_ORIGIN = "OPEN_SOURCE_PYPI_ARTIFACT"

PACKAGE_NAME = "fingerprints-matching"
PACKAGE_VERSION = "0.1.0"
PACKAGE_REQUIREMENT = f"{PACKAGE_NAME}=={PACKAGE_VERSION}"

#: The two digests PyPI publishes for 0.1.0. Written here before anything was
#: fetched, so the download is checked against the record rather than the record
#: written from the download.
RUNTIME_ARTIFACT_NAME = "fingerprints_matching-0.1.0-py3-none-any.whl"
RUNTIME_ARTIFACT_SHA256 = (
    "cb9196c21ac63aeb6002ca2e60fec0b2764d822d23f97d86b637f461a2d6cb9c"
)
RUNTIME_ARTIFACT_SIZE_BYTES = 4492

SOURCE_ARTIFACT_NAME = "fingerprints_matching-0.1.0.tar.gz"
SOURCE_ARTIFACT_SHA256 = (
    "5533cdadae5067559cc84742cbe3c9521f993bedff42d64f9da05daa85818e37"
)
SOURCE_ARTIFACT_SIZE_BYTES = 3676

LICENSE = "MIT"
UPSTREAM_INDEX = "https://pypi.org/project/fingerprints-matching/0.1.0/"

#: Unfrozen until G3 passes. The production identity is what the benchmark will
#: carry on 6,000 stored results, and naming it before the candidate has been
#: shown to be deterministic would be naming an algorithm that might not exist.
PRODUCTION_ALGORITHM_ID = "fingerprints_matching_0_1_0"
ADAPTER_ID = "fingerprints_matching_subprocess"
ADAPTER_VERSION = "1"


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

ENTRY_MODULE = "fingerprints_matching.fingerprints_matching"
ENTRY_CLASS = "FingerprintsMatching"
ENTRY_FUNCTION = "fingerprints_matching"
ENTRY_QUALNAME = f"{ENTRY_MODULE}.{ENTRY_CLASS}.{ENTRY_FUNCTION}"

#: The installed module bytes, taken from the published wheel. The wheel and the
#: sdist ship byte-identical modules, which is why one pair of digests answers
#: for both distributions.
UPSTREAM_MODULE_DIGESTS: dict[str, str] = {
    "fingerprints_matching/__init__.py": (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    ),
    "fingerprints_matching/fingerprints_matching.py": (
        "7439704c4dbe4f24b0188a5ee9f84c783421c9e5b47a7f4376aade793f2b5270"
    ),
    "fingerprints_matching/minutiae_matching.py": (
        "16a009804eb2a7b3531c450b49757ad40f4b1bdb455908c5df3b1e9c8dfe6cfa"
    ),
}

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

LEFT_ARGUMENT = "image_path1"
RIGHT_ARGUMENT = "image_path2"

SCORE_NATIVE_TYPE = "float"
SCORE_DIRECTION = "HIGHER_MORE_SIMILAR"

#: Upstream declares no range and fpbench does not derive one. The matcher
#: normalises by ``len(minutiae1)`` and clamps each per-minutia contribution at
#: zero, which bounds the value in practice — but a bound nobody published is an
#: observation, and publishing it as a contract would invite a later stage to
#: build a threshold on it.
SCORE_RANGE = "UNSPECIFIED"

FPBENCH_SCORE_TRANSFORMATION = "NONE"
DECISION_THRESHOLD = "NONE"

#: The package's README suggests 0.9 separates same-finger from different-finger.
#: It is upstream's guidance to its own users, it is recorded because it exists,
#: and it is not fpbench's threshold, not an operating point and not calibration.
UPSTREAM_README_THRESHOLD = 0.9

#: Not required, and its absence is not a defect. ``match`` divides by
#: ``len(minutiae1)``, so the first argument sets the denominator and the two
#: orderings are different questions. Observed asymmetry binds left→first and
#: right→second into the algorithm's identity (docs/adr/0109).
SYMMETRY_REQUIRED = False


# ------------------------------------------------------------- the frozen runtime

PINNED_PYTHON_VERSION = "3.12.13"
PINNED_PLATFORM = "Windows-11-10.0.26200-SP0"
PINNED_MACHINE = "AMD64"

PINNED_NUMPY = "1.26.4"

#: The ``opencv-python`` *distribution* version. The ``cv2`` library it installs
#: reports ``4.7.0`` — a different string for a different thing, and the closure
#: checks both so that neither can be quietly substituted for the other.
PINNED_OPENCV = "4.7.0.72"
PINNED_CV2_LIBRARY = "4.7.0"

#: Every wheel in the frozen environment, by digest. OpenCV is on this list as a
#: first-class part of the algorithm's identity, not as packaging detail: the
#: contours ``findContours`` returns are the direct input to feature extraction,
#: so a different OpenCV is a different feature extractor (docs/adr/0125).
RUNTIME_WHEELS: dict[str, dict[str, object]] = {
    "fingerprints-matching": {
        "version": PACKAGE_VERSION,
        "filename": RUNTIME_ARTIFACT_NAME,
        "sha256": RUNTIME_ARTIFACT_SHA256,
        "size_bytes": RUNTIME_ARTIFACT_SIZE_BYTES,
    },
    "numpy": {
        "version": PINNED_NUMPY,
        "filename": "numpy-1.26.4-cp312-cp312-win_amd64.whl",
        "sha256": (
            "08beddf13648eb95f8d867350f6a018a4be2e5ad54c8d8caed89ebca558b2818"
        ),
        "size_bytes": 15517754,
    },
    "opencv-python": {
        "version": PINNED_OPENCV,
        "filename": "opencv_python-4.7.0.72-cp37-abi3-win_amd64.whl",
        "sha256": (
            "812af57553ec1c6709060c63f6b7e9ad07ddc0f592f3ccc6d00c71e0fe0e6376"
        ),
        "size_bytes": 38163649,
    },
}

#: How the OpenCV pin was chosen, stated before it was resolved and independent
#: of any score. The package declares ``opencv-python`` with no bound, so fpbench
#: must pick one; it picks the release that was current when the artifact was
#: published — 0.1.0 was uploaded on 2023-04-04 and 4.7.0.72 shipped 2023-02-22.
#: numpy follows from that choice rather than being chosen: 1.26.4 is the only
#: numpy 1.x line that supports the reference interpreter and satisfies the
#: OpenCV wheel's ABI (docs/adr/0125).
OPENCV_GENERATION_RULE = "CONTEMPORARY_WITH_ARTIFACT_PUBLICATION"


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
JOB_DEADLINE_SECONDS = 180
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
