"""What Stage 16A is, frozen in code rather than only in a configuration file.

FingerFlow 3.0.1 was Stage 15A's reserve candidate and is this stage's active
one. It arrives with everything the selection rule asks for: MIT, on PyPI,
pretrained weights the author published behind ordinary download links, local CPU
execution, and a matcher that returns a continuous 1:1 confidence with no
threshold inside it. Nobody has to be asked for anything.

What it does not arrive with is a single, stated way to get from an image to the
array ``Matcher.verify`` consumes. That is the whole question this stage asks,
and the gate order is arranged so it is asked early: G1 establishes the bytes,
G2 tries to close the route, and nothing downstream of G2 runs unless it closes.

**Why the route matters more than the scores.** Stage 15A ended with a valid,
complete result set from a candidate whose feature extraction collapses on a
single degenerate contour. Nothing about its scores diagnosed that; the mechanism
did. So this stage refuses to reach a conclusion about FingerFlow from score
behaviour, refuses to compare it against the four algorithms already run, and
puts the structural question first (docs/adr/0130, docs/adr/0131).

Nothing here is a threshold, a calibration profile, an FMR target or a score
statistic, and nothing here will become one. Stage 16A ends either at 6,000
stored raw outcomes or at a named gate that did not close.
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
    "UPSTREAM_COMMIT",
    "UPSTREAM_TAG",
    "RUNTIME_ARTIFACT_NAME",
    "RUNTIME_ARTIFACT_SHA256",
    "RUNTIME_ARTIFACT_SIZE_BYTES",
    "SOURCE_ARTIFACT_NAME",
    "SOURCE_ARTIFACT_SHA256",
    "SOURCE_ARTIFACT_SIZE_BYTES",
    "CheckpointRecord",
    "REQUIRED_CHECKPOINT_ROLES",
    "CHECKPOINTS",
    "UPSTREAM_SOURCE_DIGESTS",
    "EXPERIMENT_ID",
    "EVIDENCE_DIRECTORY",
    "STAGE_16A_FINALIZATION_NAME",
    "EVIDENCE_DOCUMENTS",
    "OUTCOME_COMPLETE",
    "OUTCOME_ROUTE_FAIL",
    "OUTCOME_QUALIFICATION_FAIL",
    "OUTCOMES",
    "GATES",
    "GATE_ORDER",
    "GATE_STATES",
    "ROUTE_AUTHORITIES",
    "SETTLING_AUTHORITIES",
    "ROUTE_QUESTIONS",
    "ROUTE_STEPS",
    "MINUTIAE_COLUMNS",
    "CORE_COLUMNS",
    "VERIFY_NET_FEATURE_COUNT",
    "VERIFY_NET_NEIGHBOURS",
    "LEFT_ARGUMENT",
    "RIGHT_ARGUMENT",
    "SCORE_NATIVE_TYPE",
    "SCORE_DIRECTION",
    "SCORE_RANGE",
    "FPBENCH_SCORE_TRANSFORMATION",
    "DECISION_THRESHOLD",
    "CALIBRATION",
    "SYMMETRY_REQUIRED",
    "SYMMETRY_REPAIRS_REFUSED",
    "PINNED_PYTHON_VERSION",
    "PINNED_PLATFORM",
    "PINNED_MACHINE",
    "PINNED_DEVICE_MODE",
    "QUALIFICATION_MAX_COMPARISONS",
    "QUALIFICATION_CASES",
    "FAILURE_PROBES",
    "NON_RESULT_CLASSES",
    "EXPLICIT_ALGORITHMIC_NON_RESULT",
    "UNHANDLED_IMPLEMENTATION_EXCEPTION",
    "EXECUTION_PROFILE_ID",
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
    "EXPECTED_PER_RELEASE_STAGE",
    "EXPECTED_PARTICIPATING_IMAGES",
    "EXPECTED_LOGICAL_EXTRACTIONS",
    "EXPECTED_MATCH_INVOCATIONS",
    "SD300_PILOT",
    "PREDECESSOR_STAGE",
    "PREDECESSOR_OUTCOME",
    "PREDECESSOR_SELECTED_FOR_ALGORITHM_5",
    "PREDECESSOR_REASON",
    "PREDECESSOR_EVIDENCE",
    "PREDECESSOR_REASON_IS_NOT",
    "BOUND_MARKERS",
    "FORBIDDEN_READS",
    "REQUIRED_REPORTING_SWITCHES",
    "FORBIDDEN_CONFIG_KEYS",
    "ALGORITHM_5_ACCEPTANCE_CONDITIONS",
    "HARD_FAIL_CONDITIONS",
]


# ------------------------------------------------------------ candidate identity

CANDIDATE_ID = "fingerflow_3_0_1"
ALGORITHM_SLOT = "algorithm_5"
DISPLAY_NAME = "FingerFlow 3.0.1"
IMPLEMENTATION_ORIGIN = "OPEN_SOURCE_PYPI_ARTIFACT"

PACKAGE_NAME = "fingerflow"
PACKAGE_VERSION = "3.0.1"
PACKAGE_REQUIREMENT = f"{PACKAGE_NAME}=={PACKAGE_VERSION}"

LICENSE = "MIT"
UPSTREAM_INDEX = "https://pypi.org/project/fingerflow/3.0.1/"
UPSTREAM_REPOSITORY = "https://github.com/jakubarendac/fingerflow"

#: The commit tag ``v3.0.1`` points at. The published distribution and the
#: repository are two different things and this stage reads both, so both are
#: pinned: the artifact answers "what runs", the commit answers "what does the
#: author say the route is".
UPSTREAM_COMMIT = "a0a53259ec575704d19ae0ae770335536e567583"
UPSTREAM_TAG = "v3.0.1"

#: The two digests PyPI publishes for 3.0.1, written down before anything was
#: fetched so a download is checked against the record rather than the record
#: written from the download.
RUNTIME_ARTIFACT_NAME = "fingerflow-3.0.1-py3-none-any.whl"
RUNTIME_ARTIFACT_SHA256 = (
    "d256c1351b74b2e746386a3c32c61e92d569a8ba9f79cb9f9e084367000e3c35"
)
RUNTIME_ARTIFACT_SIZE_BYTES = 54538

SOURCE_ARTIFACT_NAME = "fingerflow-3.0.1.tar.gz"
SOURCE_ARTIFACT_SHA256 = (
    "f73ad527224d3b9f4587254a3bc6154a5411de12488803fb47a11faea1d2e678"
)
SOURCE_ARTIFACT_SIZE_BYTES = 46105


# ---------------------------------------------------------------- the checkpoints


class CheckpointRecord(dict):
    """One published checkpoint: what it is for, where it came from, what it is.

    A plain mapping rather than a dataclass, because these are written straight
    into evidence and a record that needs converting is a record that can be
    converted two ways.
    """

    def __init__(
        self,
        *,
        role: str,
        stored_as: str,
        served_as: str,
        source: str,
        locator: str,
        sha256: str,
        size_bytes: int,
        needed_for: str,
    ) -> None:
        super().__init__(
            role=role,
            stored_as=stored_as,
            served_as=served_as,
            source=source,
            locator=locator,
            sha256=sha256,
            size_bytes=size_bytes,
            needed_for=needed_for,
        )


#: The five roles the route names. ``verify_net`` is one role with five published
#: weights behind it, and *which* of the five is a question for G2, not G1.
REQUIRED_CHECKPOINT_ROLES: tuple[str, ...] = (
    "coarse_net",
    "fine_net",
    "classify_net",
    "core_net",
    "verify_net",
)

#: Every checkpoint the upstream README publishes, with the digest this project
#: computed on acquisition. Upstream ships no digests of its own, which is the
#: whole reason these exist: without them "the CoarseNet weights" names a file
#: nobody can check, and a re-acquisition years from now is unfalsifiable.
#:
#: Two of the nine README links are dead. ``CoarseNet`` and ``FineNet`` return
#: HTTP 404 from Google Drive on every endpoint tried — ``/uc``, ``/file/d/`` and
#: ``drive.usercontent`` — and both are served by the Dropbox mirror the *same*
#: README publishes beside the Drive link. That is why acquisition records a
#: source per checkpoint rather than assuming one host: the artifact is still
#: self-service, and saying otherwise because the first link failed would be a
#: finding about a URL rather than about the candidate (docs/adr/0129).
CHECKPOINTS: tuple[CheckpointRecord, ...] = (
    CheckpointRecord(
        role="coarse_net",
        stored_as="CoarseNet.h5",
        served_as="CoarseNet.h5",
        source="dropbox",
        locator="https://www.dropbox.com/s/gppil4wybdjcihy/CoarseNet.h5?dl=1",
        sha256="fa9df6c854636723dab479b1d79fb3981966a86af129d7e2a45b048482a0bf19",
        size_bytes=81112872,
        needed_for="minutiae extraction — the coarse map, segmentation and orientation",
    ),
    CheckpointRecord(
        role="fine_net",
        stored_as="FineNet.h5",
        served_as="FineNet.h5",
        source="dropbox",
        locator="https://www.dropbox.com/s/k7q2vs9255jf2dh/FineNet.h5?dl=1",
        sha256="b88a45e97e071ce28cc5c0549d166296763d31cacb55853422da2854b8910645",
        size_bytes=654226304,
        needed_for="minutiae verification — the per-patch score fused into CoarseNet's",
    ),
    CheckpointRecord(
        role="classify_net",
        stored_as="ClassifyNet.h5",
        served_as="ClassifyNet_6_classes.h5",
        source="google_drive",
        locator="1dfQDW8yxjmFPVu0Ddui2voxdngOrU3rc",
        sha256="b9bfb708191bf4da661f8a038fefc7bf8d9a77079ea9c10a502600393c2ddcb5",
        size_bytes=619422104,
        needed_for="minutia class, which is column 5 of the matcher's input",
    ),
    CheckpointRecord(
        role="core_net",
        stored_as="CoreNet.weights",
        served_as="CoreNet.weights",
        source="google_drive",
        locator="1v091s0eY4_VOLU9BqDXVSaZcFnA9qJPl",
        sha256="6a71a5e32a7b37e71f062435a79d92ab66f703d4f34565ed18d20d1eaf2f973a",
        size_bytes=256015980,
        needed_for="core detection — every feature vector is built relative to a core",
    ),
    CheckpointRecord(
        role="verify_net",
        stored_as="VerifyNet-10.h5",
        served_as="VerfifyNet-10.h5",
        source="google_drive",
        locator="1cEz3oCYS4JCUiZxpU5o8lYesMOVgR0rt",
        sha256="89cfd445437d0388b28c580b81e73987e2eb6575a27016deab55aeb63b6f22c5",
        size_bytes=61376,
        needed_for="matching at precision 10",
    ),
    CheckpointRecord(
        role="verify_net",
        stored_as="VerifyNet-14.h5",
        served_as="VerfiyNet-14.h5",
        source="google_drive",
        locator="1CI7z1r99AEV6Lrm2bQeGEFmVdQ8colUW",
        sha256="7ca10f22716c0af7f47fb8e80c828ea038563eec4acbdc571b1f4f31048639df",
        size_bytes=63424,
        needed_for="matching at precision 14",
    ),
    CheckpointRecord(
        role="verify_net",
        stored_as="VerifyNet-20.h5",
        served_as="VerfiyNet-20.h5",
        source="google_drive",
        locator="1lP1zDHTa7TemWPluv89ueFWCa95RnLF-",
        sha256="c1915e0da71168a36d88c8e05e5714b60c1df90dd06587d5e62a549c83be091f",
        size_bytes=67520,
        needed_for="matching at precision 20",
    ),
    CheckpointRecord(
        role="verify_net",
        stored_as="VerifyNet-24.h5",
        served_as="VerfiyNet-24.h5",
        source="google_drive",
        locator="1h2RwuM1-mgiF4dfwslbgiI7-K8F4aw2A",
        sha256="bb925bba3f8313c8ef1b3559f3ec80a133b9fab2a15f75f576990ba326ce1ec1",
        size_bytes=69568,
        needed_for="matching at precision 24",
    ),
    CheckpointRecord(
        role="verify_net",
        stored_as="VerifyNet-30.h5",
        served_as="VerfiyNet-30.h5",
        source="google_drive",
        locator="1gQEzJKlCmUqe7Sx-W-6H1w1NGY8M98bX",
        sha256="8d5926725338732ee0781fa4d9be5fb13c62c88f26f8a5b8a95f6dfecb00e3f9",
        size_bytes=71616,
        needed_for="matching at precision 30",
    ),
)


#: The upstream files this stage reads to decide the route, hashed at
#: :data:`UPSTREAM_COMMIT`. The analysis is bound to bytes for the same reason
#: Stage 15A parsed the installed module instead of quoting the README: prose
#: about code is not code, and a repository moves.
UPSTREAM_SOURCE_DIGESTS: dict[str, str] = {
    "README.md": "f80536538425ef936dab662c6872ccd5c7beb1fe0cdcc18bf934904a3902fed3",
    "requirements.txt": (
        "33f240b71e72672d9483c9f8775bec62f8556f7a35c24a7ec1aabab1a1b0e949"
    ),
    "scripts/utils/generate_encodings_for_matching.py": (
        "0e6beb1b6676d13273fc3e178076cd979b97717728b67211161839bb0d1d9fa5"
    ),
    "scripts/extractor/visualise_feature_vector.py": (
        "80d8d43805c6e9d4801106fcf464cc0ae2b419ab573ac68ef08e52a3b4b4b3e1"
    ),
    "scripts/matcher/evaluate_matcher.py": (
        "7b44e555569ec17328610e572ae6c769e43b576074f97aa66103e265552ade96"
    ),
    "scripts/matcher/utils/utils.py": (
        "c2a00b3eba38ab9d68a73a2ce088e341535efb5516a7d894dfbdb47437914224"
    ),
    "scripts/utils/change_minutiae_count.py": (
        "a75d0c9e1533d615b78eed1b8e06f891f5cf0632aa1f61b2122ab6dd13c83ffb"
    ),
    "src/fingerflow/matcher/matcher.py": (
        "bd59dea36519514805d002fff37db2a468f4bb8a8aee54b2089c7414e8f6a0be"
    ),
    "src/fingerflow/matcher/verify_net.py": (
        "6435e0c6019ff110dcb4241035584d850a3afb4cab5acc777cb1fd36583eb4c5"
    ),
    "src/fingerflow/matcher/VerifyNet/utils.py": (
        "e357ea89aed1483c073dde5244afa8248884fb360e63da9159c5394efdf7d84e"
    ),
    "src/fingerflow/matcher/VerifyNet/constants.py": (
        "2a40cec5998260960caeb99a37ef8662bab9f42646e7658342855a7e4512fcc2"
    ),
    "src/fingerflow/matcher/VerifyNet/verify_net_model.py": (
        "1a01e6c36b520f8b8139312c8b289ba64e19e8f5fcbe38471b4b965e9bf0b31d"
    ),
    "src/fingerflow/extractor/extractor.py": (
        "bf348e74be2a6d7515b05efbee21bb65d37c4c85e4772dbd24c2f2d68ed33e17"
    ),
    "src/fingerflow/extractor/utils.py": (
        "795559d766b5f12214235330ed397fbf18bb0402ed2dac8085bfc59b2c302869"
    ),
    "src/fingerflow/extractor/core_net.py": (
        "7d2bf80c9412a4a304d59be63058ee8dc2b6650d14f346795f3ddfe8f7314175"
    ),
    "src/fingerflow/extractor/CoreNet/utils.py": (
        "df0ba071e7b52b94e06c1b4fa4a259487058812991ec4e51a5760da42b01fa94"
    ),
    "src/fingerflow/extractor/ClassifyNet/utils.py": (
        "11f47ba84ada8e95816d23b3996593accf84c74b8111074682bc31e041b88bd8"
    ),
}


# --------------------------------------------------------------------- the stage

EXPERIMENT_ID = "fingerflow_canonical500_full_v1"
EVIDENCE_DIRECTORY = Path("evidence/stage16a-fingerflow")
STAGE_16A_FINALIZATION_NAME = "stage-16a-finalization.json"

#: Nine documents, and no tenth. There is no Stage 16B: if the gates close, the
#: adapter and the 6,000 happen inside this stage; if they do not, this stage
#: closes early and the Algorithm 5 search continues elsewhere.
EVIDENCE_DOCUMENTS: tuple[str, ...] = (
    "README.md",
    "predecessor-selection.json",
    "artifact-runtime-identity.json",
    "upstream-inference-route.json",
    "score-contract.json",
    "qualification.json",
    "canonical-run-binding.json",
    "result-integrity.json",
    STAGE_16A_FINALIZATION_NAME,
)

OUTCOME_COMPLETE = "FINGERFLOW_CANONICAL500_RAW_COMPLETE"
OUTCOME_ROUTE_FAIL = "FINGERFLOW_ROUTE_CLOSURE_FAIL"
OUTCOME_QUALIFICATION_FAIL = "FINGERFLOW_QUALIFICATION_FAIL"

#: Three, and there is no pending state. Every input is a public artifact this
#: project can fetch, hash and run by itself, so nothing here can be waiting on
#: anybody. ``ROUTE_CLOSURE_FAIL`` is named apart from the general qualification
#: failure because it is a finding about the *documentation* of an algorithm, not
#: about its behaviour, and a later reader must not have to guess which happened.
OUTCOMES: tuple[str, ...] = (
    OUTCOME_COMPLETE,
    OUTCOME_ROUTE_FAIL,
    OUTCOME_QUALIFICATION_FAIL,
)


# ---------------------------------------------------------------------- the gates

GATES: dict[str, str] = {
    "G1": "EXACT_UPSTREAM_IDENTITY",
    "G2": "UPSTREAM_INFERENCE_ROUTE_CLOSURE",
    "G3": "SCORE_CONTRACT_FREEZE",
    "G4": "NON_SD300_QUALIFICATION",
    "G5": "PRODUCTION_ADAPTER_FREEZE",
    "G6": "CANONICAL500_RAW_EXECUTION",
    "G7": "RESULT_INTEGRITY_AND_ALGORITHM_5_DECISION",
}
GATE_ORDER: tuple[str, ...] = ("G1", "G2", "G3", "G4", "G5", "G6", "G7")

#: Three states and no fourth. ``PENDING`` does not exist in this stage's
#: vocabulary for the reason it did not exist in Stage 15A's: a self-service
#: candidate can never be waiting on a vendor, and a state nobody can reach is a
#: state that will eventually be reached by accident.
GATE_STATES: tuple[str, ...] = ("PASS", "FAIL", "NOT_REACHED")


# ------------------------------------------------------------------- the route

#: The decision rule, in the order it is applied. Only the last one fails, and it
#: fails for a reason worth stating plainly: an answer fpbench picks is an answer
#: fpbench is responsible for, and this benchmark measures algorithms rather than
#: co-authoring them. No experiment is run to see which alternative scores better
#: — that would choose the route from the evaluation data.
ROUTE_AUTHORITIES: tuple[str, ...] = (
    "OFFICIAL_INFERENCE_EXAMPLE",
    "SINGLE_UNAMBIGUOUS_UPSTREAM_IMPLEMENTATION",
    "UPSTREAM_DECLARED_DEFAULT",
    "FPBENCH_WOULD_HAVE_TO_CHOOSE",
)

#: The three that settle a question. The fourth does not.
SETTLING_AUTHORITIES: frozenset[str] = frozenset(ROUTE_AUTHORITIES[:3])

#: Every question that must be answered before an image can become a score, in
#: the order the route asks them. Each one either carries an upstream authority
#: or it does not; the gate is the conjunction.
ROUTE_QUESTIONS: tuple[str, ...] = (
    "which_core_is_selected",
    "how_minutiae_are_ordered",
    "how_many_minutiae_are_retained",
    "how_nearest_minutiae_selection_works",
    "how_coordinates_are_made_core_relative",
    "whether_angles_are_transformed",
    "whether_rotation_augmentation_belongs_to_inference",
    "what_happens_if_no_core_is_detected",
    "what_happens_below_the_required_minutiae_count",
    "which_verify_net_precision_and_checkpoint",
)

#: The route as the author's own components describe it. Recorded so that the
#: gate's finding is a statement about a *specific* pipeline rather than about
#: "FingerFlow" in general.
ROUTE_STEPS: tuple[str, ...] = (
    "canonical_500 PNG",
    "extractor.utils.preprocess_image_data — BGR2GRAY, crop to a multiple of 8",
    "MinutiaeNet: CoarseNet + FineNet — candidate minutiae and their scores",
    "ClassifyNet — the class column",
    "CoreNet (YOLOv4) — core bounding boxes and their scores",
    "core selection + core_distance + minutiae subset  << NOT IN THE PACKAGE >>",
    "VerifyNet/utils.enhance_minutiae_points — drop x,y, append 5 neighbour distances",
    "VerifyNet/utils.preprocess_predict_input",
    "Matcher.verify -> VerifyNet.verify_fingerprints -> model.predict",
    "float confidence",
)

#: What ``Extractor.extract_minutiae`` returns, from
#: ``ClassifyNet/utils.format_classified_data`` and ``CoreNet/utils.get_detection_data``.
MINUTIAE_COLUMNS: tuple[str, ...] = ("x", "y", "angle", "score", "class")
CORE_COLUMNS: tuple[str, ...] = ("x1", "y1", "x2", "y2", "score", "w", "h")

#: ``MINUTIAE_FEATURES`` and ``MINUTIA_NEIGHBORS`` in
#: ``matcher/VerifyNet/constants.py``. They are the arithmetic that fixes the
#: matcher's input at six columns: nine features = six columns, minus x and y,
#: plus five neighbour distances.
VERIFY_NET_FEATURE_COUNT = 9
VERIFY_NET_NEIGHBOURS = 5


# ------------------------------------------------------------- the score contract

LEFT_ARGUMENT = "anchor"
RIGHT_ARGUMENT = "sample"

SCORE_NATIVE_TYPE = "float"
SCORE_DIRECTION = "HIGHER_MORE_SIMILAR"

#: The README says 0-1 and the final layer is a sigmoid, so the range is bounded
#: by construction. It is recorded as observed rather than as a contract, because
#: a published range is the first thing a later stage would build a threshold on.
SCORE_RANGE = "UNSPECIFIED"

FPBENCH_SCORE_TRANSFORMATION = "NONE"
DECISION_THRESHOLD = "NONE"
CALIBRATION = "NONE"

#: Not assumed either way. ``verify`` runs both sides through one shared
#: embedding network and combines them with a euclidean distance, which is
#: symmetric in principle — but ``BatchNormalization`` sits between the distance
#: and the sigmoid, so the observation is made rather than predicted. If the two
#: orderings differ, the orientation is frozen (docs/adr/0109).
SYMMETRY_REQUIRED = False

#: What may never be done about an asymmetry. Both would invent a score the
#: algorithm never produced.
SYMMETRY_REPAIRS_REFUSED: tuple[str, ...] = ("averaging", "maximum_of_both_orderings")


# ------------------------------------------------------------- the frozen runtime

PINNED_PYTHON_VERSION = "3.12.13"
PINNED_PLATFORM = "Windows-11-10.0.26200-SP0"
PINNED_MACHINE = "AMD64"

#: Stated rather than discovered. FingerFlow supports CUDA and would use it if it
#: found it; a run that silently used a GPU on one machine and a CPU on another
#: would be two runs.
PINNED_DEVICE_MODE = "CPU"


# ----------------------------------------------------------------- qualification

#: G4 spends at most twenty comparisons. It is a determinism and failure-contract
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
    "malformed_image",
    "blank_valid_image",
    "missing_input",
    "no_core_or_insufficient_minutiae",
    "invalid_matcher_feature_input",
)

#: The split Stage 15A's `convexityDefects` collapse would have been caught by,
#: had a fixture reached it. These two are not degrees of the same thing.
EXPLICIT_ALGORITHMIC_NON_RESULT = "EXPLICIT_ALGORITHMIC_NON_RESULT"
UNHANDLED_IMPLEMENTATION_EXCEPTION = "UNHANDLED_IMPLEMENTATION_EXCEPTION"

NON_RESULT_CLASSES: dict[str, str] = {
    EXPLICIT_ALGORITHMIC_NON_RESULT: (
        "upstream states the condition and returns from it — no core detected, "
        "fewer minutiae than the model accepts. A result: the algorithm declined "
        "this input, and the result set records the refusal"
    ),
    UNHANDLED_IMPLEMENTATION_EXCEPTION: (
        "a valid fingerprint reached an internal tensor, index, shape or OpenCV "
        "exception and the route aborted. Not a result, not a template-extraction "
        "failure and not evidence about the fingerprint — a defect in the route, "
        "and a qualification failure (docs/adr/0131)"
    ),
}


# --------------------------------------------------------------------- execution

EXECUTION_PROFILE_ID = "fingerflow_canonical500_sequential_no_retry_v1"
MAX_WORKERS = 1
RETRIES = 0

#: No pilot. A pilot over the evaluation set is an SD300 run nobody counted; the
#: qualification runs on non-SD300 fixtures and the 6,000 are the production
#: execution.
SD300_PILOT = False


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


# ------------------------------------------------------------------ the workload

EXPECTED_JOBS = 6000
EXPECTED_RELEASES: tuple[str, ...] = ("SD300A", "SD300B", "SD300C")
EXPECTED_PER_RELEASE = 2000
EXPECTED_PER_RELEASE_STAGE = 500
EXPECTED_PARTICIPATING_IMAGES = 3000

#: Two extractions and one match per comparison, SELF included: SELF is two
#: independent extractions of the same image, never one cached template used
#: twice, which is what makes its score an observation rather than an identity.
EXPECTED_LOGICAL_EXTRACTIONS = EXPECTED_JOBS * 2
EXPECTED_MATCH_INVOCATIONS = EXPECTED_JOBS


# ---------------------------------------------------- what Stage 15A was, exactly

PREDECESSOR_STAGE = "15A"
PREDECESSOR_OUTCOME = "FINGERPRINTS_MATCHING_CANONICAL500_RAW_COMPLETE"
PREDECESSOR_SELECTED_FOR_ALGORITHM_5 = False
PREDECESSOR_REASON = "STRUCTURAL_EXTRACTION_ROUTE_FAILURE"

#: Five statements about a mechanism. Not one of them is a number, and that is
#: deliberate: the finding has to survive somebody disagreeing about whether
#: twenty-two scores are few.
PREDECESSOR_EVIDENCE: tuple[str, ...] = (
    "route deterministic",
    "matcher stage succeeds whenever both sides extract",
    "widespread failures originate in feature extraction",
    "single invalid contour aborts an otherwise processable image",
    "remediation would require modifying upstream algorithm",
)

#: What the reason is not, published beside what it is. Stage 15A's raw results
#: are untouched and its scores were not consulted to choose a successor — using
#: them would rank two algorithms before there is a common operating point, which
#: is the one thing every stage since 7D has refused to do (docs/adr/0130).
PREDECESSOR_REASON_IS_NOT: tuple[str, ...] = (
    "low genuine scores",
    "poor discrimination",
    "worse than another matcher",
)


# ------------------------------------------------------------------ what is bound

BOUND_MARKERS: tuple[dict[str, str], ...] = (
    {
        "stage": "15A",
        "finalization_fingerprint": (
            "3c1711e2732b81b41ccd610540295cf70dc3308332731b54b2a6e95f4d30927c"
        ),
        "outcome": PREDECESSOR_OUTCOME,
        "why": (
            "the predecessor candidate. Its evidence stands unmodified and its "
            "scores were not read; only its extraction mechanism is cited. The "
            "fingerprint is the one Stage 15A carries after its result set id "
            "was bound into the marker that had published it as null — an "
            "evidence correction, with no rerun and no conclusion moved"
        ),
    },
    {
        "stage": "11B",
        "finalization_fingerprint": (
            "3d271490edda9e3e9d066485c2d93e82e2eceb4556668df7d65a8207e591684c"
        ),
        "outcome": "VERIFINGER_CANONICAL500_RAW_COMPLETE",
        "why": (
            "Algorithm 4's 6,000 published outcomes, and the run this one would "
            "be aligned against. Bound and never read for its scores"
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

REQUIRED_REPORTING_SWITCHES: dict[str, bool] = {
    "operational_summary": True,
    "biometric_metrics": False,
    "score_statistics": False,
    "score_export": False,
}

#: Keys that would turn this into a decision, calibration or evaluation stage.
#: Refused wherever they appear in a published document, at any depth, unless
#: every occurrence states an absence.
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


# ---------------------------------------------------- accepting Algorithm 5 at all

#: Four conditions, all of them conjunctive, and the fourth deliberately carries
#: no number. Stage 15A was accepted on "at least one score", which turned out to
#: mean twenty-two comparisons of two different prints out of six thousand. That
#: criterion is retired. The replacement is not a threshold invented after the
#: fact either: if FingerFlow approached the same extreme, the stage stops before
#: the marker and the decision is made on the mechanism, by a person.
ALGORITHM_5_ACCEPTANCE_CONDITIONS: tuple[str, ...] = (
    "the inference route is upstream-authoritative and closed",
    "no systemic implementation exception on valid fingerprint input",
    "extraction and matching do not collapse from an internal defect across the dataset",
    "a materially large number of score-bearing comparisons between two different impressions",
)

#: Any one of these closes Stage 16A without Algorithm 5.
HARD_FAIL_CONDITIONS: tuple[str, ...] = (
    "SELF_SERVICE_ARTIFACT_INCOMPLETE",
    "UPSTREAM_INFERENCE_ROUTE_NOT_CLOSED",
    "FPBENCH_WOULD_HAVE_TO_CHOOSE_A_SCORE_AFFECTING_STEP",
    "SAME_FROZEN_INPUT_AND_PROCESS_IS_NONDETERMINISTIC",
    "UNHANDLED_IMPLEMENTATION_EXCEPTION_ON_VALID_INPUT",
    "RAW_SCORE_REQUIRES_FPBENCH_TO_CHOOSE_A_THRESHOLD",
    "ASYMMETRY_REPAIRED_INSTEAD_OF_FROZEN",
    "SYSTEMIC_FAILURE_MECHANISM_ACROSS_THE_DATASET",
    "RESULT_SET_IS_NOT_SCORE_BEARING",
)
