"""What Stage 17A is: one question, asked before anything is built.

Three consecutive Algorithm 5 stages spent their effort on machinery a candidate
never reached. Stage 16A built an acquisition path, a runtime closure and a route
parser for FingerFlow and then failed at its second gate. The lesson is not that
the machinery was wrong; it is that the *order* was. So this stage inverts it.

``fingerprintMatcher`` 1.0.6 satisfies every acquisition condition on paper: MIT,
on PyPI, a wheel and an sdist with fixed digests, pure Python, OS-independent,
and a documented entry point ``match_fingerprints(image1, image2)``. What its
public documentation never says is what that call *returns* — whether it is a
scalar, whether it is raw, and which direction means "more similar".

That is the only question this stage asks first, and it is asked by reading the
published module. Not GitHub: the repository does not currently show
``fingerprintmatcher.py`` at its root, and the artifact PyPI actually distributes
is the thing that would run. If the answer is no, the stage closes and nothing
else is written (docs/adr/0133).
"""

from __future__ import annotations

from pathlib import Path

__all__ = [
    "CANDIDATE_ID",
    "ALGORITHM_SLOT",
    "DISPLAY_NAME",
    "IMPLEMENTATION_ORIGIN",
    "PACKAGE_NAME",
    "PACKAGE_VERSION",
    "PACKAGE_REQUIREMENT",
    "LICENSE",
    "UPSTREAM_INDEX",
    "UPSTREAM_REPOSITORY",
    "RUNTIME_ARTIFACT_NAME",
    "RUNTIME_ARTIFACT_SHA256",
    "RUNTIME_ARTIFACT_SIZE_BYTES",
    "SOURCE_ARTIFACT_NAME",
    "SOURCE_ARTIFACT_SHA256",
    "SOURCE_ARTIFACT_SIZE_BYTES",
    "MODULE_NAME",
    "MODULE_SHA256",
    "ENTRY_CLASS",
    "ENTRY_FUNCTION",
    "ENTRY_QUALNAME",
    "ENTRY_SIGNATURE",
    "AUTHORITY_IS_THE_DISTRIBUTION",
    "WHY_NOT_THE_REPOSITORY",
    "DECLARED_DEPENDENCIES",
    "EXPERIMENT_ID",
    "EVIDENCE_DIRECTORY",
    "STAGE_17A_FINALIZATION_NAME",
    "EVIDENCE_DOCUMENTS",
    "OUTCOME_COMPLETE",
    "OUTCOME_SCORE_CONTRACT_FAIL",
    "OUTCOMES",
    "GATES",
    "GATE_ORDER",
    "GATE_STATES",
    "SCORE_CONTRACT_QUESTIONS",
    "IMMEDIATE_STOP_CONDITIONS",
    "REFUSED_FPBENCH_STEPS",
    "PREDECESSOR_STAGE",
    "PREDECESSOR_OUTCOME",
    "PREDECESSOR_REASON",
    "BOUND_MARKERS",
    "FORBIDDEN_READS",
    "FORBIDDEN_CONFIG_KEYS",
]


# ------------------------------------------------------------ candidate identity

CANDIDATE_ID = "fingerprintmatcher_1_0_6"
ALGORITHM_SLOT = "algorithm_5"
DISPLAY_NAME = "fingerprintMatcher 1.0.6"
IMPLEMENTATION_ORIGIN = "OPEN_SOURCE_PYPI_ARTIFACT"

PACKAGE_NAME = "fingerprintMatcher"
PACKAGE_VERSION = "1.0.6"
PACKAGE_REQUIREMENT = f"{PACKAGE_NAME}=={PACKAGE_VERSION}"

LICENSE = "MIT"
UPSTREAM_INDEX = "https://pypi.org/project/fingerprintMatcher/1.0.6/"
UPSTREAM_REPOSITORY = "https://github.com/Tharunk07/fingerprintMatcher"

#: The two digests PyPI publishes, written down before anything was fetched.
RUNTIME_ARTIFACT_NAME = "fingerprintMatcher-1.0.6-py3-none-any.whl"
RUNTIME_ARTIFACT_SHA256 = (
    "4491a191b6f874acdfe287fb47bff788d6b01c88e71d4c247e3fd7baceb2e5b2"
)
RUNTIME_ARTIFACT_SIZE_BYTES = 3126

SOURCE_ARTIFACT_NAME = "fingerprintMatcher-1.0.6.tar.gz"
SOURCE_ARTIFACT_SHA256 = (
    "50692faf63ca8bccb83ea8a2adfac7284e389b05bc19347c86a513a85f868411"
)
SOURCE_ARTIFACT_SIZE_BYTES = 3008

#: The whole package is one file, and the wheel and the sdist ship it
#: byte-identically. One digest therefore answers for both distributions, which
#: is the fact that makes "read the artifact" a single, checkable act.
MODULE_NAME = "fingerprintmatcher.py"
MODULE_SHA256 = "590edeae5835576729cf3529d4c371230dbdc36bd3f9b06c1b88f75535c59652"

ENTRY_CLASS = "fingerprintMatcher"
ENTRY_FUNCTION = "match_fingerprints"
ENTRY_QUALNAME = f"fingerprintmatcher.{ENTRY_CLASS}.{ENTRY_FUNCTION}"
ENTRY_SIGNATURE: tuple[str, ...] = ("self", "img1_path", "img2_path")

#: Which artifact answers. The repository is recorded as a locator and is not the
#: authority: it does not currently show ``fingerprintmatcher.py`` at its root,
#: while PyPI distributes a module that would actually execute. A qualification
#: that read the repository would be describing code nobody installs.
AUTHORITY_IS_THE_DISTRIBUTION = True
WHY_NOT_THE_REPOSITORY = (
    "the official repository does not presently show fingerprintmatcher.py at "
    "its root, and PyPI is what a `pip install` resolves. The bytes that would "
    "run are the bytes that get read"
)

#: What the package asks for. Recorded because the pair is contradictory —
#: opencv-python and opencv-contrib-python are alternative builds of one module
#: and are not supported side by side — and because the entry point calls
#: cv2.xfeatures2d.SIFT_create, which the main distribution does not provide.
DECLARED_DEPENDENCIES: tuple[str, ...] = (
    "opencv-python>=4.9.0",
    "opencv-contrib-python",
)


# --------------------------------------------------------------------- the stage

EXPERIMENT_ID = "fingerprintmatcher_canonical500_full_v1"
EVIDENCE_DIRECTORY = Path("evidence/stage17a-fingerprintmatcher")
STAGE_17A_FINALIZATION_NAME = "stage-17a-finalization.json"

#: Five documents, and no sixth. The smallest evidence set this project has
#: published, in proportion to a stage that reads one file and stops.
EVIDENCE_DOCUMENTS: tuple[str, ...] = (
    "README.md",
    "artifact-identity.json",
    "score-contract.json",
    "upstream-route.json",
    STAGE_17A_FINALIZATION_NAME,
)

OUTCOME_COMPLETE = "FINGERPRINTMATCHER_CANONICAL500_RAW_COMPLETE"
OUTCOME_SCORE_CONTRACT_FAIL = "FINGERPRINTMATCHER_SCORE_CONTRACT_FAIL"

#: Two outcomes. There is no separate route-failure outcome, because the route
#: gate is not reachable unless the score contract holds — and if it holds, a
#: route gap would be a qualification failure of the ordinary kind.
OUTCOMES: tuple[str, ...] = (OUTCOME_COMPLETE, OUTCOME_SCORE_CONTRACT_FAIL)


# ---------------------------------------------------------------------- the gates

GATES: dict[str, str] = {
    "G1": "OFFICIAL_ARTIFACT_IDENTITY",
    "G2": "RAW_SCORE_CONTRACT",
    "G3": "UPSTREAM_ROUTE_CLOSURE",
    "G4": "NON_SD300_QUALIFICATION",
    "G5": "PRODUCTION_ADAPTER_FREEZE",
    "G6": "CANONICAL500_RAW_EXECUTION",
    "G7": "RESULT_INTEGRITY_AND_ALGORITHM_5_DECISION",
}
GATE_ORDER: tuple[str, ...] = ("G1", "G2", "G3", "G4", "G5", "G6", "G7")
GATE_STATES: tuple[str, ...] = ("PASS", "FAIL", "NOT_REACHED")


# ------------------------------------------------------- the one decisive gate

#: G2, in full. Both must hold; either one failing closes the stage.
SCORE_CONTRACT_QUESTIONS: tuple[str, ...] = (
    "does the entry point return a native scalar before any decision is applied",
    "is the score direction provable from the implementation",
)

#: Any one of these closes Stage 17A where it stands.
IMMEDIATE_STOP_CONDITIONS: tuple[str, ...] = (
    "BOOLEAN_OR_THRESHOLD_ONLY_OUTPUT",
    "SCORE_DIRECTION_NOT_PROVABLE",
    "FPBENCH_WOULD_HAVE_TO_SUPPLY_PREPROCESSING",
    "UNHANDLED_SYSTEMATIC_IMPLEMENTATION_DEFECT_ON_VALID_FINGERPRINTS",
)

#: What fpbench does not add, on any candidate. Listed here so that a later
#: change which quietly inserts one is a diff against a published contract.
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


# ---------------------------------------------------------------- what is bound

PREDECESSOR_STAGE = "16A"
PREDECESSOR_OUTCOME = "FINGERFLOW_ROUTE_CLOSURE_FAIL"
PREDECESSOR_REASON = "UPSTREAM_INFERENCE_ROUTE_NOT_CLOSED"

BOUND_MARKERS: tuple[dict[str, str], ...] = (
    {
        "stage": "16A",
        "finalization_fingerprint": (
            "78bec17615d59e3362c6ed8b1fae35564d8262f471a01ded3c7be9c5a8f8d670"
        ),
        "outcome": PREDECESSOR_OUTCOME,
        "why": (
            "the predecessor candidate, closed at its route gate. It left "
            "Algorithm 5 open with no reserve named, which is why this stage "
            "exists"
        ),
    },
    {
        "stage": "15A",
        "finalization_fingerprint": (
            "9377dc90d27a09521675d9e0f7fb33e0c60678e822f33d2bf05e84045062ff2f"
        ),
        "outcome": "FINGERPRINTS_MATCHING_CANONICAL500_RAW_COMPLETE",
        "why": (
            "the algorithm whose slot is still contested. Bound and never read "
            "for its scores"
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
    "fingerprints_matching_scores",
)

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
