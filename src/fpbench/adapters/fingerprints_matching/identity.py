"""Who this algorithm is, frozen, before a single SD300 pixel is opened.

Everything the adapter needs in order to know what it is running lives here, in
the adapter package, because an adapter may import ``fpbench.core`` and itself
and nothing else of fpbench. The stage that *uses* this algorithm —
:mod:`fpbench.experiments.stage15a_identity` — imports these names and adds the
things an adapter has no business knowing: gates, evidence documents, a reference
run, a workload and an outcome vocabulary.

Two things this module deliberately does not contain.

**No threshold.** The package's README suggests 0.9 to its own users. That number
is recorded in the stage's route contract because it exists, and it is not this
benchmark's operating point (docs/adr/0003).

**No path.** Where the frozen runtime lives is a fact about a machine. It reaches
no fingerprint, no result and no evidence document.

Everything here is a constant, so this module imports nothing that needs OpenCV,
numpy or the package itself. That is what lets CI check the identity of an
algorithm it is not going to install.
"""

from __future__ import annotations

__all__ = [
    "ALGORITHM_ID",
    "ADAPTER_ID",
    "ADAPTER_VERSION",
    "DISPLAY_NAME",
    "PACKAGE_NAME",
    "PACKAGE_VERSION",
    "PACKAGE_REQUIREMENT",
    "LICENSE",
    "IMPLEMENTATION_ORIGIN",
    "UPSTREAM_INDEX",
    "RUNTIME_ARTIFACT_NAME",
    "RUNTIME_ARTIFACT_SHA256",
    "RUNTIME_ARTIFACT_SIZE_BYTES",
    "SOURCE_ARTIFACT_NAME",
    "SOURCE_ARTIFACT_SHA256",
    "SOURCE_ARTIFACT_SIZE_BYTES",
    "ENTRY_MODULE",
    "ENTRY_CLASS",
    "ENTRY_FUNCTION",
    "ENTRY_QUALNAME",
    "UPSTREAM_MODULE_DIGESTS",
    "LEFT_ARGUMENT",
    "RIGHT_ARGUMENT",
    "SCORE_DIRECTION",
    "SCORE_RANGE",
    "FPBENCH_SCORE_TRANSFORMATION",
    "DECISION_THRESHOLD",
    "SYMMETRY_REQUIRED",
    "REQUIRED_EXTRACTION_COUNT",
    "PINNED_PYTHON_VERSION",
    "PINNED_PLATFORM",
    "PINNED_MACHINE",
    "PINNED_NUMPY",
    "PINNED_OPENCV",
    "PINNED_CV2_LIBRARY",
    "RUNTIME_WHEELS",
    "OPENCV_GENERATION_RULE",
    "STORE_RELATIVE",
    "THIRD_PARTY_ROOT_ENV",
    "DEFAULT_STORE_RELATIVE",
    "JOB_DEADLINE_SECONDS",
    "FORBIDDEN_CONFIG_KEYS",
]

ALGORITHM_ID = "fingerprints_matching_0_1_0"
ADAPTER_ID = "fingerprints_matching_subprocess"
ADAPTER_VERSION = "1"
DISPLAY_NAME = "fingerprints-matching 0.1.0"

PACKAGE_NAME = "fingerprints-matching"
PACKAGE_VERSION = "0.1.0"
PACKAGE_REQUIREMENT = f"{PACKAGE_NAME}=={PACKAGE_VERSION}"

LICENSE = "MIT"
IMPLEMENTATION_ORIGIN = "OPEN_SOURCE_PYPI_ARTIFACT"
UPSTREAM_INDEX = "https://pypi.org/project/fingerprints-matching/0.1.0/"

#: The two digests PyPI publishes for 0.1.0, written down before anything was
#: fetched so a download is checked against the record rather than the record
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


# ------------------------------------------------------------------- the route

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


# ----------------------------------------------------------- the score contract

LEFT_ARGUMENT = "image_path1"
RIGHT_ARGUMENT = "image_path2"

SCORE_DIRECTION = "HIGHER_MORE_SIMILAR"
SCORE_RANGE = "UNSPECIFIED"
FPBENCH_SCORE_TRANSFORMATION = "NONE"
DECISION_THRESHOLD = "NONE"

#: Not required, and its absence is not a defect. ``match`` divides by
#: ``len(minutiae1)``, so the first argument sets the denominator and the two
#: orderings are different questions (docs/adr/0109).
SYMMETRY_REQUIRED = False

#: Two independent extractions per comparison, SELF included. The upstream entry
#: point performs both itself and shares nothing between them.
REQUIRED_EXTRACTION_COUNT = 2


# ------------------------------------------------------------ the frozen runtime

PINNED_PYTHON_VERSION = "3.12.13"
PINNED_PLATFORM = "Windows-11-10.0.26200-SP0"
PINNED_MACHINE = "AMD64"

PINNED_NUMPY = "1.26.4"

#: The ``opencv-python`` *distribution* version. The ``cv2`` library it installs
#: reports ``4.7.0`` — a different string for a different thing, and the closure
#: checks both so neither can be quietly substituted for the other.
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
#: of any score: the release that was current when the artifact was published —
#: 0.1.0 was uploaded 2023-04-04 and 4.7.0.72 shipped 2023-02-22 (docs/adr/0125).
OPENCV_GENERATION_RULE = "CONTEMPORARY_WITH_ARTIFACT_PUBLICATION"

#: Where this candidate lives under the third-party store root. The root itself is
#: resolved at runtime and never written down here (docs/adr/0083).
STORE_RELATIVE = "fingerprints-matching"

#: Restated rather than imported, because ``fpbench.third_party`` is above this
#: layer. The store module remains the authority; a contract test asserts these
#: two agree with it, so a divergence is a failing test rather than a silent
#: second answer to "where do artifacts live?".
THIRD_PARTY_ROOT_ENV = "FPBENCH_THIRD_PARTY_ROOT"
DEFAULT_STORE_RELATIVE = (".cache", "fpbench", "third_party")

#: Generous against a route whose whole cost is one decode, one Otsu pass and an
#: O(n1·n2) loop in Python, and fixed before the canonical set was opened.
JOB_DEADLINE_SECONDS = 180

#: Keys that would turn this adapter into a decision layer. Refused at
#: construction, so an adapter one configuration key away from applying a
#: threshold does not exist.
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
