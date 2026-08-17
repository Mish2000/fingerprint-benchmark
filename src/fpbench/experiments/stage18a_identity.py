"""What Stage 18A is: an execution, not a qualification.

Every Algorithm 5 stage since 15A has been a gate that a candidate failed to
reach the far side of. Stage 18A deliberately inverts the philosophy: the goal is
raw scores, not reasons to stop. Its single question is

    can the comparison manifest we already ran four algorithms over produce a
    full set of raw OpenAFIS similarity scores, when the minutiae come from the
    SecuGen route OpenAFIS's own author published?

and its completion criterion is arithmetic and nothing else — 6,000 expected
outcomes, 6,000 stored, 0 missing. Five thousand failures and a thousand scores
still completes the stage, because the stage was built to *measure what the
system does*, not to select it.

WHAT THIS IS NOT

.. code-block:: text

    algorithm_5_established   = false
    opens_common_calibration  = false
    publication_eligible      = false
    purpose                   = PRIVATE_REFERENCE_ONLY

Stage 19A (MINDTCT -> OpenAFIS) is the real Algorithm 5 candidate and the one
whose numbers may be published. Stage 18A exists only so that 19A begins with a
working OpenAFIS build, a proven raw 1:1 score contract, and a private sense of
how OpenAFIS behaves when fed by an extractor it was demonstrated against.

THE ONE THING 18A MUST NOT DO

Stage 19A must be derived from the MINDTCT and OpenAFIS specifications, never
from an attempt to make its scores resemble these. A quality cutoff, a minutiae
count, an angle convention or a coordinate scaling chosen because it moved this
run's numbers would make SecuGen a training target. ``FORBIDDEN_STAGE19_USES``
names those uses so the prohibition is a constant rather than a memory.

WHAT IS COMPARABLE TO THE OTHER FOUR ALGORITHMS, AND WHAT IS NOT

Comparable, and identical by construction: the prepared image set, the pair
manifest and its ordering, which side is the probe, that the score is stored raw
with no transform and no threshold, and that a failure is never stored as a zero.

**Not** comparable: the input pixels. The frozen extraction route resizes every
image to 300x400 without preserving the aspect ratio, because that is the sensor
geometry upstream's helper declares. SourceAFIS, NBIS, flx and VeriFinger all
consumed the canonical 500 ppi images at their native dimensions. This is a real
difference in what reached the algorithm, it is mandated by the frozen route, and
it is the main reason these numbers are private.
"""

from __future__ import annotations

from pathlib import Path

__all__ = [
    "STAGE",
    "PURPOSE",
    "EXPERIMENT_ID",
    "ALGORITHM_5_ESTABLISHED",
    "OPENS_COMMON_CALIBRATION",
    "PUBLICATION_ELIGIBLE",
    "OPENAFIS_REPOSITORY",
    "OPENAFIS_COMMIT",
    "OPENAFIS_TREE",
    "OPENAFIS_LICENSE",
    "OPENAFIS_LICENSE_SHA256",
    "OPENAFIS_CONTRACT_FILES",
    "EXTRACTION_ROUTE",
    "SENSOR_WIDTH",
    "SENSOR_HEIGHT",
    "RESAMPLING_FILTER",
    "ASPECT_RATIO_PRESERVED",
    "SECUGEN_DEVICE",
    "SECUGEN_TEMPLATE_FORMAT",
    "SECUGEN_FINGER_INFO",
    "FROZEN_AGAINST_CHANGE",
    "PERMITTED_COMPATIBILITY_FIXES",
    "SCORE_NATIVE_TYPE",
    "SCORE_DIRECTION",
    "SCORE_TRANSFORM",
    "SCORE_THRESHOLD",
    "SCORE_FORMULA",
    "ZERO_IS_A_VALID_SCORE",
    "PAIR_ORIENTATION",
    "PAIR_OUTCOME_STATUSES",
    "OK_STATUS",
    "EXPECTED_PAIR_OUTCOMES",
    "EXPECTED_IMAGES",
    "REFERENCE_PREPARATION_SET_ID",
    "REFERENCE_PREPARATION_SET_FINGERPRINT",
    "REFERENCE_PAIR_MANIFEST_HASH",
    "REFERENCE_COHORT_ID",
    "REFERENCE_PROTOCOL_ID",
    "REFERENCE_DATASET_ID",
    "TEMPLATE_FALLBACK_ORDER",
    "CSV_LAYOUT",
    "FORBIDDEN_CSV_STEPS",
    "DIAGNOSTICS_PERMITTED",
    "DIAGNOSTICS_FORBIDDEN",
    "FORBIDDEN_STAGE19_USES",
    "NOT_REQUIREMENTS",
    "PRIVATE_ROOT_ENV_VAR",
    "PRIVATE_SUBDIRECTORIES",
    "EVIDENCE_DIRECTORY",
    "EVIDENCE_DOCUMENTS",
    "STAGE_18A_FINALIZATION_NAME",
    "OUTCOME_COMPLETE",
    "BOUND_MARKERS",
]


# ---------------------------------------------------------------- stage identity

STAGE = "18A"
PURPOSE = "PRIVATE_REFERENCE_ONLY"
EXPERIMENT_ID = "secugen_openafis_private_reference_v1"

# Published as constants rather than derived, so that no run can quietly promote
# itself. Stage 19A is the stage that may set the first two.
ALGORITHM_5_ESTABLISHED = False
OPENS_COMMON_CALIBRATION = False
PUBLICATION_ELIGIBLE = False


# ------------------------------------------------------------- OpenAFIS identity

OPENAFIS_REPOSITORY = "neilharan/openafis"
OPENAFIS_COMMIT = "3ae1c757c6dafea977a33ef51380e37f1715e626"
OPENAFIS_TREE = "6d822f7744b4e522b03872e74f583c1897b1f63e"
OPENAFIS_LICENSE = "BSD-2-Clause"
OPENAFIS_LICENSE_SHA256 = "34bc04061cf0e76ec91a87d03f819fa6b3319b59fb5081f737a745ee5301596b"

# The files that decide what a score means. Pinned by digest so that a rebuild
# against a moved tree cannot silently change the contract this stage published.
OPENAFIS_CONTRACT_FILES = {
    "lib/Match.cpp": "46f254c24393112cc07b7fa452346e873edfc8a8971f9608197613f9694aa533",
    "lib/Match.h": "0a5421178cce46a08ba80962ed4aeb4e51ec2198c9adb35255870dc830aac7a5",
    "lib/Param.h": "058dca6dd906c8c21d93b43e0be614beca2580bfb01e6134387801e7a083b1c5",
    "lib/Template.cpp": "c815a69b995aaa444a6b00be4e5827ab708874fbac18ca6003d337f6aea6acfa",
    "lib/Template.h": "62a1aa0e408c32acfa8a07e01c9a5dcfa9ba63f5ece67a24c3b52735f43ee665",
    "lib/TemplateISO19794_2_2005.cpp": "f1dc41b1e1d63b58ea3c8a03b4cbb7a3bd4e2380ea4cbf7dffba0f65d21fcb09",
    "lib/TemplateISO19794_2_2005.h": "33724433966af079cd826ac838d0fa3003164bf1d6e89275cb37fd164939c5ca",
    "lib/TemplateCSV.cpp": "f1cf1752de526bcd178a5996e4b90b2fbcd0fd13978926ef82038307a23af1b5",
    "lib/TemplateCSV.h": "b3f794391c39344e178013e6220a67d82013d3f0e6725c8a23258897d6db84ca",
    "data/extract.py": "3df2fc318bca2e2d2faf24e08484d25a7d4e98097712899f70013a510c76bb01",
    "README.md": "b2c82af85ada49c7955ae24fc9e045d029224b9e9750f7c854a04b1931b0f687",
}


# ------------------------------------------------------------- extraction route

# Transcribed from data/extract.py at the pinned commit. Every step is upstream's.
EXTRACTION_ROUTE = (
    "fpbench canonical_gray8_500",
    "Pillow Image.open",
    "resize 300x400 LANCZOS, aspect ratio NOT preserved",
    "8-bit raw image",
    "SGFPM_Create",
    "SGFPM_Init(SG_DEV_FDU05)",
    "SGFPM_SetTemplateFormat(ISO19794)",
    "SGFPM_GetMaxTemplateSize",
    "SGFingerInfo(FingerNumber=UNKNOWN, ViewNumber=0, ImpressionType=LIVE_SCAN_PLAIN, ImageQuality=0)",
    "SGFPM_CreateTemplate",
    "SGFPM_GetTemplateSize",
    "exact ISO template bytes",
)

SENSOR_WIDTH = 300
SENSOR_HEIGHT = 400
RESAMPLING_FILTER = "LANCZOS"

# Both of these are wrong on their face and are kept anyway: 300x400 distorts
# every canonical image, and a rolled impression is still declared plain. The
# stage is a reference for the route the author provided, not for the SecuGen
# pipeline fpbench would have designed.
ASPECT_RATIO_PRESERVED = False
SECUGEN_DEVICE = "SG_DEV_FDU05"
SECUGEN_TEMPLATE_FORMAT = "TEMPLATE_FORMAT_ISO19794"
SECUGEN_FINGER_INFO = {
    "FingerNumber": "SG_FINGPOS_UK",
    "ViewNumber": 0,
    "ImpressionType": "SG_IMPTYPE_LP",
    "ImageQuality": 0,
}

# Aggressive on plumbing, conservative on the algorithm. These are the algorithm.
FROZEN_AGAINST_CHANGE = (
    "300x400",
    "LANCZOS",
    "ISO template format",
    "minutiae filtering",
    "minutiae selection",
    "image enhancement invented by fpbench",
    "score transformation",
    "OpenAFIS matching parameters",
)

PERMITTED_COMPATIBILITY_FIXES = (
    "DLL path fixes",
    "library-name fixes",
    "Python compatibility fixes",
    "Pillow API rename",
    "cffi declaration compatibility",
    "32/64-bit fixes",
    "CMake/MSVC fixes",
    "path quoting",
    "buffer contiguity fixes",
    "process wrapper",
    "batch wrapper",
)


# ---------------------------------------------------------------- score contract

SCORE_NATIVE_TYPE = "uint8_t"
SCORE_DIRECTION = "HIGHER_MORE_SIMILAR"
SCORE_TRANSFORM = "NONE"
SCORE_THRESHOLD = "NONE"

# Read out of lib/Match.cpp, not out of the README. `result` is assigned only when
# `maxMatched > Param::MinimumMinutiae` (4); otherwise it keeps its initial 0.
SCORE_FORMULA = "100 * maxMatched^2 / (probe_minutiae_count * candidate_minutiae_count)"
ZERO_IS_A_VALID_SCORE = True

PAIR_ORIENTATION = {"left": "probe", "right": "candidate"}


# ------------------------------------------------------------- outcome statuses

OK_STATUS = "OK"

# Section 11's closed list. `score = 0` is always OK, and a failed extraction is
# never stored as a zero — the two live in different columns on purpose.
PAIR_OUTCOME_STATUSES = (
    "OK",
    "SECU_GEN_EXTRACTION_FAILED_LEFT",
    "SECU_GEN_EXTRACTION_FAILED_RIGHT",
    "SECU_GEN_EXTRACTION_FAILED_BOTH",
    "OPENAFIS_TEMPLATE_LOAD_FAILED",
    "OPENAFIS_MATCH_PROCESS_FAILED",
    "INFRASTRUCTURE_FAILURE",
)


# -------------------------------------------------------------- protocol anchors

EXPECTED_PAIR_OUTCOMES = 6000
EXPECTED_IMAGES = 3000

# The same inputs the other four algorithms ran over. Not "equivalent" — the same
# identifiers, checked before a run exists.
REFERENCE_PREPARATION_SET_ID = "prepset_be560e047991"
REFERENCE_PREPARATION_SET_FINGERPRINT = "be560e047991a0d58af8f86a4576f8b78dc350e643af82f0e2405350d9e2fd3f"
REFERENCE_PAIR_MANIFEST_HASH = "ee4d942e23cdc112e17ed69e0abc603d5f26e17cc5839edc9aa412edc57dfe3b"
REFERENCE_COHORT_ID = "sd300_50_subjects_test_22f8d52a7478"
REFERENCE_PROTOCOL_ID = "sd300_50_subjects"
REFERENCE_DATASET_ID = "sd300"


# ------------------------------------------------------- template handoff to OpenAFIS

# Section 8. A serialization difference is not a blocker; a content change is.
TEMPLATE_FALLBACK_ORDER = (
    "A. SecuGen ISO -> native OpenAFIS ISO parser",
    "B. SecuGen ISO19794-2:2005 compatible variant",
    "C. faithful serialization bridge: SecuGen minutiae -> OpenAFIS CSV",
)

# Read out of lib/TemplateCSV.cpp, which upstream calls "used for debug only".
CSV_LAYOUT = ("line 1: width,height", "each minutia: type,x,y,angle_in_radians")

FORBIDDEN_CSV_STEPS = (
    "filter",
    "sort for quality",
    "drop minutiae",
    "invent type",
    "change angles heuristically",
    "scale coordinates for better scores",
)


# ------------------------------------------------------------------- diagnostics

# Section 16. Permitted because they describe the run; forbidden because the
# negative set is not a true impostor population and this stage is not calibration.
DIAGNOSTICS_PERMITTED = (
    "template extraction coverage",
    "score-bearing comparisons",
    "score histogram 0..100",
    "SELF distribution",
    "PLAIN-ROLL mated distribution",
    "same-subject/different-finger sanity distribution",
    "score uniqueness / quantization",
    "median / p95 extraction time",
    "median / p95 OpenAFIS match time",
    "A->B versus B->A differences",
)

DIAGNOSTICS_FORBIDDEN = ("TAR", "FAR", "FMR", "EER", "best threshold")


# ------------------------------------------------------- what 18A may not decide

FORBIDDEN_STAGE19_USES = (
    "which MINDTCT quality cutoff",
    "how many minutiae to keep",
    "which angle conversion correlates better",
    "which coordinate scaling produces more similar scores",
)

NOT_REQUIREMENTS = (
    "training provenance",
    "SD300 training-overlap investigation",
    "production adapter",
    "registry integration",
    "common calibration",
    "threshold",
    "TAR/FAR",
    "statistical significance",
    "cross-platform reproducibility",
    "Linux SecuGen",
    "performance optimization",
    "vendor-quality documentation",
    "score symmetry",
    "minimum coverage criterion",
)


# ----------------------------------------------------------------------- storage

# No vendor binary and no score reaches git. The repository carries bindings only.
PRIVATE_ROOT_ENV_VAR = "FPBENCH_PRIVATE_ROOT"
PRIVATE_SUBDIRECTORIES = ("sdk", "templates", "results", "failures", "timings")

EVIDENCE_DIRECTORY = Path("evidence") / "stage18a-secugen-openafis-reference"
STAGE_18A_FINALIZATION_NAME = "stage-18a-finalization.json"
EVIDENCE_DOCUMENTS = (
    "README.md",
    "openafis-identity.json",
    "route-contract.json",
    "private-run-binding.json",
)

OUTCOME_COMPLETE = "SECU_GEN_OPENAFIS_PRIVATE_RAW_COMPLETE"

# Predecessors this stage binds. Fingerprints are read live out of the published
# documents rather than written here, because three of them have moved already.
BOUND_MARKERS = (
    {
        "stage": "17A",
        "why": "the predecessor candidate, closed at its score-contract gate. It left Algorithm 5 open, which is why OpenAFIS was revisited",
    },
    {
        "stage": "15A",
        "why": "the algorithm whose slot is still contested. Bound and never read for its scores",
    },
    {
        "stage": "8E",
        "why": "the third-party research-use policy, reused and not reopened",
    },
)
