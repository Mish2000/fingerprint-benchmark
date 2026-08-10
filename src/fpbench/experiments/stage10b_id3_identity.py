"""Everything Stage 10B froze before it looked at the id3 Finger SDK.

These constants are the stage's contract with itself: the one provisional
candidate, the ten hard gates and the order they run in, the closed blocker
vocabulary, the two outcomes, the frozen workload the licence would have to
cover, and the keys no published document may ever carry. They are asserted by
the contract suite, republished in the finalization, and a later change to any
of them is a different preflight rather than a quiet correction to this one.

Stage 10B asks one question:

.. code-block:: text

    does a package of the id3 Finger SDK exist here that is exact, legally and
    practically operable for local research, and that defines a complete 1:1
    route from canonical_500 to a raw score with no score-affecting choice left
    to fpbench?

It is allowed to answer "no" (docs/adr/0094).

**Stage 10A is not re-opened.** Its candidate set was frozen before its result
was known, it ended ``ALGORITHM4_PREFLIGHT_NO_SURVIVOR``, and its marker opened
a candidate search rather than an artifact qualification. Adding id3 to that set
after the fact would change the research question after the answer was visible.
Stage 10B binds Stage 10A's final fingerprint as a predecessor and edits nothing
under its evidence directory (docs/adr/0094).

Nothing here is derived at import time, nothing reads a workspace, nothing
downloads anything, and nothing is a fingerprint image, a score, a licence byte
or a credential. What is here about upstream is a *description*: a URL, a commit
SHA, a digest, a size, a published class member, a sentence of a vendor page.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath

from fpbench.core.id3_preflight_errors import Id3CandidateIdentityError
from fpbench.core.identifiers import validate_id

__all__ = [
    "STAGE_10B_SCHEMA_VERSION",
    "STAGE_FINALIZATION_KIND",
    "ALGORITHM_SLOT",
    "STAGE_10B_SELECTED_OUTCOME",
    "STAGE_10B_BLOCKED_OUTCOME",
    "STAGE_10B_OUTCOMES",
    "CANDIDATE_PASS_VERDICT",
    "CANDIDATE_FAIL_VERDICT",
    "CANDIDATE_VERDICTS",
    "CANDIDATE_ID",
    "IMPLEMENTATION_ORIGIN",
    "PRODUCTION_ALGORITHM_ID_FROZEN",
    "FINAL_IDENTITY_COMPONENTS",
    "COMPLETE_IDENTITY_FINGERPRINT_COMPONENTS",
    "ACQUISITION_CHECKLIST",
    "LICENSE_CAPACITY_QUESTIONS",
    "DECLARED_NON_CANDIDATES",
    "EVIDENCE_DIRECTORY",
    "README_NAME",
    "CANDIDATE_IDENTITY_NAME",
    "PUBLIC_PRODUCT_OBSERVATIONS_NAME",
    "ACCESS_QUALIFICATION_NAME",
    "SDK_PACKAGE_MANIFEST_NAME",
    "LICENSE_CAPABILITY_REPORT_NAME",
    "MODEL_ARTIFACT_MANIFEST_NAME",
    "INPUT_DOMAIN_CONTRACT_NAME",
    "EXTRACTION_PROFILE_NAME",
    "MATCHER_PROFILE_NAME",
    "SCORE_CONTRACT_NAME",
    "TRAINING_PROVENANCE_NAME",
    "RUNTIME_SMOKE_NAME",
    "PREFLIGHT_REPORT_NAME",
    "STAGE_10B_FINALIZATION_NAME",
    "REQUIRED_EVIDENCE_FILES",
    "PreflightGate",
    "GATE_ORDER",
    "GATE_COUNT",
    "GateStatus",
    "GATE_DOCUMENTS",
    "gate_documents",
    "BlockerCode",
    "GATE_BLOCKERS",
    "gate_of_blocker",
    "AcquisitionStatus",
    "OperationalAccessDecision",
    "LicenseCapacityStatus",
    "SingleFingerRouteStatus",
    "RawScoreRouteStatus",
    "TrainingProvenanceStatus",
    "SD300OverlapStatus",
    "BENCHMARK_INPUT_PROFILE",
    "BENCHMARK_INPUT_PPI",
    "BENCHMARK_INPUT_PIXEL_FORMAT",
    "FROZEN_WORKLOAD",
    "FrozenWorkload",
    "SCORE_CONTRACT_REQUIREMENTS",
    "SELF_SEMANTICS_REQUIREMENTS",
    "RUNTIME_TARGET_FIELDS",
    "ADMISSIBLE_RUNTIME_TARGETS",
    "LOCAL_SMOKE_STEPS",
    "PUBLISHABLE_LICENSE_FACTS",
    "SENSITIVE_EVIDENCE_KEYS",
    "SENSITIVE_VALUE_PATTERNS",
    "FORBIDDEN_PUBLISHED_KEYS",
    "STAGE_10A_FINALIZATION_FINGERPRINT",
    "STAGE_10A_OUTCOME",
    "STAGE_10A_EVIDENCE_DIRECTORY",
    "STAGE8E_FINALIZATION_FINGERPRINT",
    "STAGE8E_OUTCOME",
    "STAGE8E_PURPOSE_FINGERPRINT",
    "STAGE8E_POLICY_FINGERPRINT",
    "ARTIFACT_STORE_PREFIX",
    "ID3_ARTIFACT_MARKER",
    "NON_GOALS",
    "PRODUCTION_INTEGRATION_NOT_CREATED",
    "STAGE_10B_SOURCE_FILES",
    "STAGE_10B_ADRS",
    "STAGE_10B_DOCUMENTS",
    "all_frozen_identifiers",
]

STAGE_10B_SCHEMA_VERSION = "1"
STAGE_FINALIZATION_KIND = "stage_10b_finalization"

#: The benchmark slot this preflight is qualifying a candidate for. Nothing here
#: fills it, and Stage 10B cannot fill it on its own: a pass opens Stage 10C.
ALGORITHM_SLOT = "algorithm_4"

#: The two outcomes, and there are exactly two. A blocked outcome is a complete
#: result — the whole point of a preflight is that it may cost nothing and still
#: answer the question (docs/adr/0094).
STAGE_10B_SELECTED_OUTCOME = "ALGORITHM4_CANDIDATE_SELECTED"
STAGE_10B_BLOCKED_OUTCOME = "ID3_FINGER_SDK_PREFLIGHT_FAIL"
STAGE_10B_OUTCOMES = (STAGE_10B_SELECTED_OUTCOME, STAGE_10B_BLOCKED_OUTCOME)

CANDIDATE_PASS_VERDICT = "ID3_FINGER_SDK_PREFLIGHT_PASS"
CANDIDATE_FAIL_VERDICT = "ID3_FINGER_SDK_PREFLIGHT_FAIL"
CANDIDATE_VERDICTS = (CANDIDATE_PASS_VERDICT, CANDIDATE_FAIL_VERDICT)


# ------------------------------------------------------------ the one candidate

#: Provisional, and provisional is the point. This names the *subject* of the
#: preflight, not a production algorithm: no ``AlgorithmConfig`` carries it, no
#: run reports under it, and nothing downstream may treat it as an algorithm id
#: (spec section 2).
CANDIDATE_ID = "id3_finger_sdk_1to1"

#: One origin, and it is not one of Stage 10A's. ``AUTHOR_OFFICIAL_*`` describes
#: researchers publishing the code behind their paper; a commercial vendor
#: shipping its own product is a different relation between the artifact and the
#: thing it implements, and calling it by Stage 10A's name would blur the two.
IMPLEMENTATION_ORIGIN = "VENDOR_OFFICIAL_SDK"

#: Nothing is frozen as a production identity yet, and this says so in a field
#: rather than in prose so that a later stage cannot quietly assume otherwise.
PRODUCTION_ALGORITHM_ID_FROZEN = False

#: What a final identity would have to name, once there is a package to name it
#: from. Every one of these is score-affecting, which is why none of them may be
#: left to a default nobody wrote down (docs/adr/0097).
FINAL_IDENTITY_COMPONENTS: tuple[str, ...] = (
    "exact SDK version, as reported by the delivered package at runtime",
    "every model artifact loaded, by digest",
    "the extractor profile: models, template format, data formats, thread count "
    "and every extraction flag",
    "the matcher profile: every published matcher option and its chosen value",
    "the runtime: operating system, architecture, Python ABI and native library "
    "identity",
)

#: What must be fingerprintable in one piece before the candidate can pass. A
#: setting that cannot be named cannot be pinned, and a route with one unnamed
#: setting is a route that can change under a benchmark without anything moving
#: in this repository (spec section 18, docs/adr/0097).
COMPLETE_IDENTITY_FINGERPRINT_COMPONENTS: tuple[str, ...] = (
    "package",
    "models",
    "extractor settings",
    "matcher settings",
    "template data formats",
    "input profile",
    "score API",
)

#: The six things Gate 2 has to establish, in the order it establishes them. A
#: package that cannot be obtained stops the list at its first line, and each
#: later line is a separate way for access to fail with the package in hand
#: (spec section 4).
ACQUISITION_CHECKLIST: tuple[str, ...] = (
    "exact SDK package obtainable",
    "target platform supported",
    "evaluation or developer licence obtainable",
    "licence activation succeeds",
    "required Finger modules are enabled",
    "licence is usable for local research",
)

#: What a licence has to answer before its capacity can be called sufficient.
#: The first four are one question asked four ways, because the metering
#: semantics decide which of them matters (spec section 5).
LICENSE_CAPACITY_QUESTIONS: tuple[str, ...] = (
    "does extraction consume quota?",
    "does matching consume quota?",
    "does model loading consume quota?",
    "does every API call consume quota?",
    "how much quota is available?",
    "how much quota remains?",
    "when does it expire?",
)

#: Products this stage names so that nobody later mistakes one for the subject.
#: The vendor ships more than one fingerprint product and the samples repository
#: is not the SDK, so "id3" alone identifies nothing (spec section 3).
DECLARED_NON_CANDIDATES: tuple[tuple[str, str], ...] = (
    (
        "id3_microfinger_sdk",
        "A separate id3 product with its own product page. Not the Finger SDK, "
        "and not the subject of this preflight.",
    ),
    (
        "id3_minex_submission",
        "The MINEX-evaluated template generator and matcher submitted to NIST. "
        "An evaluation submission is a configuration of a product under a "
        "protocol, not the delivered package this stage would have to pin.",
    ),
    (
        "id3_finger_sdk_samples_repository",
        "The public sample sources at github.com/id3Technologies/finger-sdk-"
        "samples. They document a route and they contain no SDK: the samples "
        "README states the package itself arrives only on request.",
    ),
    (
        "id3_finger_toolkit_python_wrapper_from_a_third_party",
        "Any third-party redistribution or wrapper of the SDK. Stage 10B "
        "qualifies the vendor's own package or nothing (docs/adr/0095).",
    ),
)


# --------------------------------------------------------- the published files

EVIDENCE_DIRECTORY = Path("evidence") / "stage10b-id3-finger-sdk-preflight"

README_NAME = "README.md"
CANDIDATE_IDENTITY_NAME = "candidate-identity.json"
PUBLIC_PRODUCT_OBSERVATIONS_NAME = "public-product-observations.json"
ACCESS_QUALIFICATION_NAME = "access-qualification.json"
SDK_PACKAGE_MANIFEST_NAME = "sdk-package-manifest.json"
LICENSE_CAPABILITY_REPORT_NAME = "license-capability-report.json"
MODEL_ARTIFACT_MANIFEST_NAME = "model-artifact-manifest.json"
INPUT_DOMAIN_CONTRACT_NAME = "input-domain-contract.json"
EXTRACTION_PROFILE_NAME = "extraction-profile.json"
MATCHER_PROFILE_NAME = "matcher-profile.json"
SCORE_CONTRACT_NAME = "score-contract.json"
TRAINING_PROVENANCE_NAME = "training-provenance.json"
RUNTIME_SMOKE_NAME = "runtime-smoke.json"
PREFLIGHT_REPORT_NAME = "preflight-report.json"

#: The last-written authority, and the last file committed.
STAGE_10B_FINALIZATION_NAME = "stage-10b-finalization.json"

#: Exactly what the evidence directory holds, in the order the documents depend
#: on each other. An extra file is a finding (spec section 40).
REQUIRED_EVIDENCE_FILES: tuple[str, ...] = (
    README_NAME,
    CANDIDATE_IDENTITY_NAME,
    PUBLIC_PRODUCT_OBSERVATIONS_NAME,
    ACCESS_QUALIFICATION_NAME,
    SDK_PACKAGE_MANIFEST_NAME,
    LICENSE_CAPABILITY_REPORT_NAME,
    MODEL_ARTIFACT_MANIFEST_NAME,
    INPUT_DOMAIN_CONTRACT_NAME,
    EXTRACTION_PROFILE_NAME,
    MATCHER_PROFILE_NAME,
    SCORE_CONTRACT_NAME,
    TRAINING_PROVENANCE_NAME,
    RUNTIME_SMOKE_NAME,
    PREFLIGHT_REPORT_NAME,
    STAGE_10B_FINALIZATION_NAME,
)


# ---------------------------------------------------------------- the ten gates


class PreflightGate(str, Enum):
    """The ten hard gates. Every one of them is mandatory.

    There is no weighting between them and no score at which enough gates make
    the candidate acceptable. The order is the design: product identity and
    acquisition come first because a package that cannot be obtained makes every
    later question unanswerable, and answering them first costs nothing but
    reading (docs/adr/0094).
    """

    PRODUCT_IDENTITY = "PRODUCT_IDENTITY"
    ACQUISITION_ACCESS = "ACQUISITION_ACCESS"
    PACKAGE_IDENTITY = "PACKAGE_IDENTITY"
    INPUT_DOMAIN = "INPUT_DOMAIN"
    EXTRACTION_PROFILE = "EXTRACTION_PROFILE"
    MATCHER_PROFILE = "MATCHER_PROFILE"
    RAW_SCORE_ROUTE = "RAW_SCORE_ROUTE"
    WORKLOAD_FEASIBILITY = "WORKLOAD_FEASIBILITY"
    TRAINING_PROVENANCE = "TRAINING_PROVENANCE"
    LOCAL_SMOKE = "LOCAL_SMOKE"


GATE_ORDER: tuple[PreflightGate, ...] = (
    PreflightGate.PRODUCT_IDENTITY,
    PreflightGate.ACQUISITION_ACCESS,
    PreflightGate.PACKAGE_IDENTITY,
    PreflightGate.INPUT_DOMAIN,
    PreflightGate.EXTRACTION_PROFILE,
    PreflightGate.MATCHER_PROFILE,
    PreflightGate.RAW_SCORE_ROUTE,
    PreflightGate.WORKLOAD_FEASIBILITY,
    PreflightGate.TRAINING_PROVENANCE,
    PreflightGate.LOCAL_SMOKE,
)

GATE_COUNT = len(GATE_ORDER)


class GateStatus(str, Enum):
    """What one gate concluded.

    ``NOT_REACHED`` is not a soft failure and not a pass. It records that the
    candidate had already stopped, so this question was never asked. Publishing
    it as anything else would be inventing a conclusion.
    """

    PASS = "PASS"
    FAIL = "FAIL"
    NOT_REACHED = "NOT_REACHED"


#: The documents each gate reports through. Two gates own two documents each:
#: acquisition owns both the access record and the licence-capability report
#: because quota is part of whether access is usable at all, and package
#: identity owns both the package manifest and the model inventory because a
#: model loaded transitively is part of the package's identity (spec sections 5
#: and 10).
GATE_DOCUMENTS: tuple[tuple[PreflightGate, tuple[str, ...]], ...] = (
    (PreflightGate.PRODUCT_IDENTITY, (PUBLIC_PRODUCT_OBSERVATIONS_NAME,)),
    (
        PreflightGate.ACQUISITION_ACCESS,
        (ACCESS_QUALIFICATION_NAME, LICENSE_CAPABILITY_REPORT_NAME),
    ),
    (
        PreflightGate.PACKAGE_IDENTITY,
        (SDK_PACKAGE_MANIFEST_NAME, MODEL_ARTIFACT_MANIFEST_NAME),
    ),
    (PreflightGate.INPUT_DOMAIN, (INPUT_DOMAIN_CONTRACT_NAME,)),
    (PreflightGate.EXTRACTION_PROFILE, (EXTRACTION_PROFILE_NAME,)),
    (PreflightGate.MATCHER_PROFILE, (MATCHER_PROFILE_NAME,)),
    (PreflightGate.RAW_SCORE_ROUTE, (SCORE_CONTRACT_NAME,)),
    (PreflightGate.WORKLOAD_FEASIBILITY, ()),
    (PreflightGate.TRAINING_PROVENANCE, (TRAINING_PROVENANCE_NAME,)),
    (PreflightGate.LOCAL_SMOKE, (RUNTIME_SMOKE_NAME,)),
)


def gate_documents(gate: PreflightGate) -> tuple[str, ...]:
    """The documents one gate reports through, possibly none.

    ``WORKLOAD_FEASIBILITY`` has none of its own: the arithmetic it would run
    belongs beside the licence capacity it would run against, and a second
    document holding the same budget twice would be two authorities for one
    number (spec sections 5 and 28).
    """
    for item, names in GATE_DOCUMENTS:
        if item is gate:
            return names
    raise Id3CandidateIdentityError(  # pragma: no cover - GATE_ORDER is exhaustive
        f"{gate!r} is not a Stage 10B gate"
    )


class BlockerCode(str, Enum):
    """Why the id3 Finger SDK cannot enter fpbench as Algorithm 4. A closed list.

    Exactly the vocabulary the specification fixed (spec section 39). Each
    member names something a reader could act on, and each is attached to
    exactly one gate below. "Not ideal", "some risk" and "probably fine" are not
    among them and cannot be expressed here.
    """

    ID3_PACKAGE_NOT_OBTAINABLE = "ID3_PACKAGE_NOT_OBTAINABLE"
    ID3_LICENSE_NOT_OBTAINABLE = "ID3_LICENSE_NOT_OBTAINABLE"
    ID3_LICENSE_ACTIVATION_FAILED = "ID3_LICENSE_ACTIVATION_FAILED"
    ID3_REQUIRED_MODULE_NOT_LICENSED = "ID3_REQUIRED_MODULE_NOT_LICENSED"
    LICENSE_WORKLOAD_CAPACITY_UNRESOLVED = "LICENSE_WORKLOAD_CAPACITY_UNRESOLVED"
    LICENSE_WORKLOAD_CAPACITY_INSUFFICIENT = "LICENSE_WORKLOAD_CAPACITY_INSUFFICIENT"

    SDK_VERSION_IDENTITY_UNRESOLVED = "SDK_VERSION_IDENTITY_UNRESOLVED"
    REQUIRED_MODEL_MISSING = "REQUIRED_MODEL_MISSING"
    MODEL_IDENTITY_UNRESOLVED = "MODEL_IDENTITY_UNRESOLVED"

    CANONICAL500_INPUT_ROUTE_UNRESOLVED = "CANONICAL500_INPUT_ROUTE_UNRESOLVED"
    SINGLE_FINGER_INPUT_ROUTE_UNRESOLVED = "SINGLE_FINGER_INPUT_ROUTE_UNRESOLVED"
    FPBENCH_PREPROCESSING_CHOICE_REQUIRED = "FPBENCH_PREPROCESSING_CHOICE_REQUIRED"

    EXTRACTION_PROFILE_UNRESOLVED = "EXTRACTION_PROFILE_UNRESOLVED"
    MATCHER_PROFILE_UNRESOLVED = "MATCHER_PROFILE_UNRESOLVED"
    HIDDEN_DEFAULT_UNRESOLVED = "HIDDEN_DEFAULT_UNRESOLVED"

    RAW_SCORE_ROUTE_UNRESOLVED = "RAW_SCORE_ROUTE_UNRESOLVED"
    PAIR_ORDER_SEMANTICS_UNRESOLVED = "PAIR_ORDER_SEMANTICS_UNRESOLVED"
    SCORE_NONDETERMINISM_OBSERVED = "SCORE_NONDETERMINISM_OBSERVED"

    RESEARCH_USE_BLOCKED = "RESEARCH_USE_BLOCKED"
    SD300_TRAINING_OVERLAP_FOUND = "SD300_TRAINING_OVERLAP_FOUND"
    LOCAL_SMOKE_FAILED = "LOCAL_SMOKE_FAILED"


#: Which gate each blocker belongs to. A blocker raised against a gate that was
#: never reached is a contradiction, and the engine refuses one.
#:
#: ``RESEARCH_USE_BLOCKED`` sits at acquisition beside the operational blockers
#: and stays a separate code, because the two questions are separate: a
#: component may be permitted for research and still be unusable for want of a
#: licence, and a licence in hand never turns a research-use refusal into
#: permission (docs/adr/0095).
GATE_BLOCKERS: tuple[tuple[PreflightGate, tuple[BlockerCode, ...]], ...] = (
    (PreflightGate.PRODUCT_IDENTITY, ()),
    (
        PreflightGate.ACQUISITION_ACCESS,
        (
            BlockerCode.ID3_PACKAGE_NOT_OBTAINABLE,
            BlockerCode.ID3_LICENSE_NOT_OBTAINABLE,
            BlockerCode.ID3_LICENSE_ACTIVATION_FAILED,
            BlockerCode.ID3_REQUIRED_MODULE_NOT_LICENSED,
            BlockerCode.LICENSE_WORKLOAD_CAPACITY_UNRESOLVED,
            BlockerCode.LICENSE_WORKLOAD_CAPACITY_INSUFFICIENT,
            BlockerCode.RESEARCH_USE_BLOCKED,
        ),
    ),
    (
        PreflightGate.PACKAGE_IDENTITY,
        (
            BlockerCode.SDK_VERSION_IDENTITY_UNRESOLVED,
            BlockerCode.REQUIRED_MODEL_MISSING,
            BlockerCode.MODEL_IDENTITY_UNRESOLVED,
        ),
    ),
    (
        PreflightGate.INPUT_DOMAIN,
        (
            BlockerCode.CANONICAL500_INPUT_ROUTE_UNRESOLVED,
            BlockerCode.SINGLE_FINGER_INPUT_ROUTE_UNRESOLVED,
            BlockerCode.FPBENCH_PREPROCESSING_CHOICE_REQUIRED,
        ),
    ),
    (
        PreflightGate.EXTRACTION_PROFILE,
        (
            BlockerCode.EXTRACTION_PROFILE_UNRESOLVED,
            BlockerCode.HIDDEN_DEFAULT_UNRESOLVED,
        ),
    ),
    (PreflightGate.MATCHER_PROFILE, (BlockerCode.MATCHER_PROFILE_UNRESOLVED,)),
    (
        PreflightGate.RAW_SCORE_ROUTE,
        (
            BlockerCode.RAW_SCORE_ROUTE_UNRESOLVED,
            BlockerCode.PAIR_ORDER_SEMANTICS_UNRESOLVED,
        ),
    ),
    (
        PreflightGate.WORKLOAD_FEASIBILITY,
        (BlockerCode.LICENSE_WORKLOAD_CAPACITY_INSUFFICIENT,),
    ),
    (PreflightGate.TRAINING_PROVENANCE, (BlockerCode.SD300_TRAINING_OVERLAP_FOUND,)),
    (
        PreflightGate.LOCAL_SMOKE,
        (
            BlockerCode.LOCAL_SMOKE_FAILED,
            BlockerCode.SCORE_NONDETERMINISM_OBSERVED,
        ),
    ),
)


def gate_of_blocker(code: BlockerCode) -> tuple[PreflightGate, ...]:
    """Every gate a blocker code may be raised at.

    Two codes belong to two gates each, and deliberately:
    ``LICENSE_WORKLOAD_CAPACITY_INSUFFICIENT`` can be established from the
    licence terms at acquisition or from the arithmetic once the route is known,
    and it means the same thing either way (spec sections 5 and 28).
    """
    return tuple(gate for gate, codes in GATE_BLOCKERS if code in codes)


# --------------------------------------------------------------- vocabularies


class AcquisitionStatus(str, Enum):
    """Whether the delivered package is here.

    ``NOT_ATTEMPTED_HERE`` and ``REFUSED_BY_VENDOR`` are separate and never
    merged. This project not having asked is a fact about this project; the
    vendor having declined is a fact about the route. Both block the gate, and
    only one of them is about id3.
    """

    OBTAINED = "OBTAINED"
    NOT_ATTEMPTED_HERE = "NOT_ATTEMPTED_HERE"
    REQUESTED_AND_PENDING = "REQUESTED_AND_PENDING"
    REFUSED_BY_VENDOR = "REFUSED_BY_VENDOR"
    UNAVAILABLE_FOR_TARGET_PLATFORM = "UNAVAILABLE_FOR_TARGET_PLATFORM"


class OperationalAccessDecision(str, Enum):
    """Whether fpbench can actually run the component, today, on this machine.

    Not a licence observation and not a research-use decision. Stage 8E answers
    "may this project execute this component under its declared purpose"; this
    answers "does this project hold a working copy and an active licence". A
    component can be ``ALLOWED`` by Stage 8E and ``NO_ACCESS`` here, and that
    combination blocks execution just as firmly (docs/adr/0095).
    """

    OPERABLE = "OPERABLE"
    NO_PACKAGE = "NO_PACKAGE"
    NO_LICENSE = "NO_LICENSE"
    LICENSE_INACTIVE = "LICENSE_INACTIVE"
    CAPACITY_INSUFFICIENT = "CAPACITY_INSUFFICIENT"
    UNRESOLVED = "UNRESOLVED"

    @property
    def opens_execution(self) -> bool:
        return self is OperationalAccessDecision.OPERABLE


class LicenseCapacityStatus(str, Enum):
    """Whether the licence can carry the frozen workload.

    ``UNRESOLVED`` is a failure, not a caution. A capacity nobody can state is
    a run that stops in the middle of six thousand comparisons, and a partial
    run is not a result (docs/adr/0096).
    """

    SUFFICIENT = "SUFFICIENT"
    INSUFFICIENT = "INSUFFICIENT"
    UNRESOLVED = "UNRESOLVED"
    NOT_REACHED = "NOT_REACHED"

    @property
    def admits_candidate(self) -> bool:
        return self is LicenseCapacityStatus.SUFFICIENT


class SingleFingerRouteStatus(str, Enum):
    """Which published route a single already-segmented impression takes.

    The benchmark holds single-finger impressions, and the vendor's headline
    sample is a four-finger slap. Whether a single finger goes straight to
    template creation or through detection and ROI extraction first is a
    question for the delivered package's own documentation and samples — never
    for whichever branch looks reasonable (spec sections 13 and 14).
    """

    IMAGE_TO_TEMPLATE = "IMAGE_TO_TEMPLATE"
    DETECTION_ROI_TO_TEMPLATE = "DETECTION_ROI_TO_TEMPLATE"
    UNRESOLVED = "UNRESOLVED"
    NOT_REACHED = "NOT_REACHED"

    @property
    def admits_candidate(self) -> bool:
        return self in (
            SingleFingerRouteStatus.IMAGE_TO_TEMPLATE,
            SingleFingerRouteStatus.DETECTION_ROI_TO_TEMPLATE,
        )


class RawScoreRouteStatus(str, Enum):
    """Which of the published comparison APIs the raw route uses.

    One of them, chosen from the delivered package's documented single-finger
    route, and never a mixture: the two carry different semantics, and a run
    that used one for some pairs and one for others would be two experiments
    reported as one (spec section 20).
    """

    COMPARE_TEMPLATES = "COMPARE_TEMPLATES"
    COMPARE_TEMPLATE_RECORDS = "COMPARE_TEMPLATE_RECORDS"
    UNRESOLVED = "UNRESOLVED"
    NOT_REACHED = "NOT_REACHED"

    @property
    def admits_candidate(self) -> bool:
        return self in (
            RawScoreRouteStatus.COMPARE_TEMPLATES,
            RawScoreRouteStatus.COMPARE_TEMPLATE_RECORDS,
        )


class TrainingProvenanceStatus(str, Enum):
    """What is known about what the shipped models were trained on.

    ``PROPRIETARY_UNDISCLOSED`` is an acceptable answer for a commercial
    product. Demanding a full training corpus from a vendor as a condition of
    entry would be a condition no vendor meets, and refusing every commercial
    matcher on that ground would be a methodological choice made by accident
    (spec section 29).
    """

    PUBLICLY_DOCUMENTED = "PUBLICLY_DOCUMENTED"
    PARTIALLY_DOCUMENTED = "PARTIALLY_DOCUMENTED"
    PROPRIETARY_UNDISCLOSED = "PROPRIETARY_UNDISCLOSED"
    NOT_REACHED = "NOT_REACHED"


class SD300OverlapStatus(str, Enum):
    """Whether the evaluation cohort appears in the product's training history.

    ``PROVEN_ABSENT`` requires an upstream statement that the dataset was not
    used. Silence is ``NO_EVIDENCE_FOUND``, and the two are never merged: a
    vendor that publishes FVC and MINEX results has not said anything at all
    about SD300.
    """

    POSITIVE_OVERLAP_FOUND = "POSITIVE_OVERLAP_FOUND"
    NO_EVIDENCE_FOUND = "NO_EVIDENCE_FOUND"
    PROVEN_ABSENT = "PROVEN_ABSENT"
    NOT_REACHED = "NOT_REACHED"

    @property
    def is_automatic_rejection(self) -> bool:
        return self is SD300OverlapStatus.POSITIVE_OVERLAP_FOUND


# ---------------------------------------------------------------- the benchmark

#: What a future Algorithm 4 adapter would receive, and the only thing it would
#: receive. Not SD300B at 1000 ppi, not SD300C at 2000 ppi, and no further
#: resampling inside fpbench: the canonical profile already produced 500 ppi
#: gray8, which is the resolution this SDK's own documentation requires
#: (docs/adr/0031, spec sections 11 and 12).
BENCHMARK_INPUT_PROFILE = "canonical_500"
BENCHMARK_INPUT_PPI = 500
BENCHMARK_INPUT_PIXEL_FORMAT = "gray8"


@dataclass(frozen=True, slots=True)
class FrozenWorkload:
    """The complete run a licence would have to carry, fixed before asking.

    Fixed in advance on purpose. A capacity question asked against a workload
    that can be trimmed later is a capacity question with no answer, and
    "we will see how far the quota goes" is how a benchmark ends up reporting
    part of a protocol as if it were the protocol (docs/adr/0096).
    """

    participating_images: int
    extractions: int
    comparisons: int
    qualification_operations_upper_bound: int

    def __post_init__(self) -> None:
        for name in (
            "participating_images",
            "extractions",
            "comparisons",
            "qualification_operations_upper_bound",
        ):
            value = int(getattr(self, name))
            if value <= 0:
                raise Id3CandidateIdentityError(
                    f"{name} must be a positive count; a workload with a zero in "
                    "it is a workload nobody has to plan for"
                )
            object.__setattr__(self, name, value)
        if self.extractions != self.participating_images:
            raise Id3CandidateIdentityError(
                "one extraction per participating image, and one image per "
                "extraction. SELF pairs are two independent extractions of the "
                "same image and are counted at the comparison, not here "
                "(docs/adr/0070)"
            )

    @property
    def total_metered_operations_upper_bound(self) -> int:
        """The largest number of API calls the run could consume.

        An upper bound rather than an estimate, because the metering semantics
        are exactly what is unknown: if model loading, extraction and matching
        all consume quota, this is what it costs; if only some do, the true
        figure is lower and the bound still holds.
        """
        return (
            self.extractions
            + self.comparisons
            + self.qualification_operations_upper_bound
        )


#: 3,000 participating images, one extraction each, 6,000 comparisons, and a
#: bounded allowance for the qualification itself. The first three come from the
#: canonical protocol this project has already run three times; the fourth is a
#: ceiling this stage sets so that the qualification cannot quietly become the
#: thing that exhausts the licence (spec section 28).
FROZEN_WORKLOAD = FrozenWorkload(
    participating_images=3_000,
    extractions=3_000,
    comparisons=6_000,
    qualification_operations_upper_bound=200,
)


# ------------------------------------------------------- what the score must be

#: What the raw-score gate requires of the route, stated here rather than
#: derived, because these are requirements and not findings.
SCORE_CONTRACT_REQUIREMENTS: tuple[str, ...] = (
    "exactly one integer per 1:1 attempt, from one chosen comparison API, and "
    "never a mixture of two",
    "a nominal range of 0 to 65535 and a direction where a higher score means "
    "more similar, each read from the delivered package's own documentation",
    "no threshold anywhere in the raw route: not FingerMatcherThreshold, not a "
    "vendor recommended threshold, and not an is_match flag derived from either "
    "(spec section 22)",
    "declared failure semantics for image decode, model loading, extraction, "
    "matching and licence, each mapped to an outcome; an extraction failure is "
    "never converted into a score",
    "0 is a valid score and is never used as a failure sentinel, so a failure "
    "is carried by an outcome rather than by a number (spec section 27)",
    "pair-order semantics established rather than assumed: score(A, B) and "
    "score(B, A) are run on fixtures, and if they differ fpbench keeps the "
    "reference/probe orientation the API defines rather than averaging or "
    "maximising the two",
    "a quality value, a pose or any second output is diagnostic and never "
    "modifies the score",
)

#: The SELF rule, frozen at Stage 10B even though the adapter that would obey it
#: belongs to Stage 10C. A pairwise matcher makes this easy to get wrong: a
#: route that takes two images can answer ``SELF(A, A)`` by noticing the inputs
#: are the same object and returning a constant, and the constant would then be
#: a number this project published about its own eligibility logic rather than
#: about the algorithm (docs/adr/0070, spec sections 24 and 25).
SELF_SEMANTICS_REQUIREMENTS: tuple[str, ...] = (
    "SELF(A, A) performs two independent extractions of A and compares the two "
    "resulting templates",
    "a template extracted once and compared with itself is refused, however "
    "much cheaper it is",
    "a maximum-score shortcut for equal inputs is refused",
    "no representation cache may live between the two sides of a comparison; a "
    "smoke run may verify this with invocation counters, and never by publishing "
    "template bytes",
)

#: What locking a runtime target means, once there is a package to lock one for.
#: The evaluation licence is single-platform, so this is a decision that has to
#: be made before activation rather than discovered afterwards (spec section 33).
RUNTIME_TARGET_FIELDS: tuple[str, ...] = (
    "operating_system",
    "architecture",
    "python_abi",
    "native_library_identity",
)

#: The two targets this project could host. One is chosen before activation and
#: recorded; alternating between them under one algorithm fingerprint is refused.
ADMISSIBLE_RUNTIME_TARGETS: tuple[tuple[str, str], ...] = (
    ("windows", "x86_64"),
    ("linux", "x86_64"),
)

#: The bounded smoke, in order, and it runs only after the nine gates above it
#: (spec section 30). It is still not a production adapter.
LOCAL_SMOKE_STEPS: tuple[str, ...] = (
    "import the exact Python binding from the delivered package",
    "read the library version from the running library, not from a web page",
    "check the licence and record only its non-sensitive facts",
    "load the exact models, by digest",
    "build the extractor with the frozen profile",
    "build the matcher with the frozen profile",
    "create a template from a non-SD300 fixture",
    "create a second, independently extracted template",
    "produce one finite integer score",
    "repeat the score in the same process",
    "restart the process",
    "repeat the score again and compare it with the first",
)


# ------------------------------------------------------------ what is publishable

#: The only licence facts a public document may carry. Anything not on this list
#: is either irrelevant or a secret, and there is no third category
#: (spec section 6, docs/adr/0098).
PUBLISHABLE_LICENSE_FACTS: tuple[str, ...] = (
    "license_type",
    "enabled_module_names",
    "expiry_category",
    "remaining_days_category",
    "sufficient_for_declared_workload",
)

#: Keys the finalization verifier refuses at any depth of any published
#: document. Not a warning and not a redaction: the publisher stops.
SENSITIVE_EVIDENCE_KEYS: frozenset[str] = frozenset(
    {
        "password",
        "passphrase",
        "secret",
        "activation_key",
        "activationkey",
        "license_key",
        "licence_key",
        "serial_number",
        "serial",
        "hardware_code",
        "hardwarecode",
        "license_bytes",
        "licence_bytes",
        "license_file_bytes",
        "license_buffer",
        "customer_login",
        "customer_id",
        "customer_password",
        "account_id",
        "product_reference",
        "access_token",
        "refresh_token",
        "bearer_token",
        "session_cookie",
        "cookie",
        "cookies",
        "authorization",
        "api_key",
        "credentials",
    }
)

#: Value shapes that look like credentials wherever they appear, checked against
#: every published string. The first is the activation-key format the vendor's
#: own samples print; the rest are the ordinary shapes a copied secret takes.
#:
#: Written as regular-expression *sources* rather than compiled patterns so this
#: module stays a table of constants and the engine owns the compilation.
SENSITIVE_VALUE_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        "activation_key_shape",
        r"\b[A-Za-z0-9]{8}-[A-Za-z0-9]{4}-[A-Za-z0-9]{4}-[A-Za-z0-9]{4}-"
        r"[A-Za-z0-9]{12}\b",
    ),
    ("bearer_token_shape", r"\bBearer\s+[A-Za-z0-9._\-]{16,}\b"),
    ("private_key_block", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ("basic_auth_in_locator", r"://[^/\s:@]+:[^/\s@]+@"),
    ("long_base64_blob", r"\b[A-Za-z0-9+/]{120,}={0,2}\b"),
)

#: Refused at any depth of a published Stage 10B document, in addition to the
#: sensitive keys above. Each one would mean an upstream byte, a tensor, a
#: fingerprint image, a score or a machine-specific path had reached the evidence
#: of a stage whose entire subject is that none of them do.
#:
#: As in Stage 8E, Stage 9A and Stage 10A, no member may be a value of a
#: published vocabulary: these documents count things into maps keyed by enum
#: value, so a forbidden key named ``source_code`` would refuse a count of
#: source-code components rather than a body of source code.
FORBIDDEN_PUBLISHED_KEYS: frozenset[str] = frozenset(
    {
        "license_text",
        "license_body",
        "source_text",
        "file_contents",
        "contents",
        "payload",
        "blob",
        "base64",
        "weights",
        "state_dict",
        "model_bytes",
        "template_bytes",
        "template_data",
        "minutiae",
        "tensor",
        "tensors",
        "embedding",
        "embeddings",
        "image_bytes",
        "score",
        "scores",
        "raw_score",
        "raw_scores",
        "observed_score",
        "threshold",
        "thresholds",
        "reported_eer",
        "reported_fmr",
        "reported_fnmr",
        "subject_id",
        "subject_ids",
        "pair_id",
        "pair_ids",
        "image_id",
        "image_ids",
        "absolute_path",
        "local_path",
        "artifact_root",
        "home_directory",
    }
) | SENSITIVE_EVIDENCE_KEYS


# ------------------------------------------------------------- the closed stages
#
# Stage 10B reads two published markers and edits neither. Stage 10A is its
# predecessor and stays immutable; Stage 8E owns third-party policy and Stage 10B
# adds no licensing subsystem of its own (spec sections 1 and 7).

#: Stage 10A as re-closed over its two corrective fixes. Binding the fingerprint
#: rather than the directory is what makes "Stage 10A was not edited" checkable
#: instead of asserted.
STAGE_10A_FINALIZATION_FINGERPRINT = (
    "48d42c4362d8925d2a6b9912fcb959c61e76a71f99f4c84aaaeda4d3df64d8eb"
)
STAGE_10A_OUTCOME = "ALGORITHM4_PREFLIGHT_NO_SURVIVOR"

#: Assembled from parts rather than written out, for the reason Stage 8C, 8D, 8E,
#: 9A and 10A assemble theirs: Stage 10B's own source is audited for literals
#: that name another stage's published evidence, and a written-out path here
#: would make the audit refuse the module that performs it.
STAGE_10A_EVIDENCE_DIRECTORY = "/".join(
    ("evidence", "stage10a-" + "algorithm4-candidate-preflight")
)

STAGE8E_FINALIZATION_FINGERPRINT = (
    "c08648dece292603eb9d4b6fff0b3412523af0730da59141b6e7a32ee02540e8"
)
STAGE8E_OUTCOME = "RESEARCH_ONLY_THIRD_PARTY_POLICY_READY"
STAGE8E_PURPOSE_FINGERPRINT = (
    "a62ab45681bdbd9cc4e741e1e5522583746b5d29f1fe911fa687fc7fee405443"
)
STAGE8E_POLICY_FINGERPRINT = (
    "de9cdbaa23522c4a15337d86b0ec2df8af8b79383a1f8014294e8c7855bf972a"
)

#: Where the store would keep Stage 10B's artifacts, relative to
#: ``FPBENCH_THIRD_PARTY_ROOT``. Manifests hold no absolute path and none of
#: these is a place on any machine (docs/adr/0083).
ARTIFACT_STORE_PREFIX = "id3-finger-sdk"

#: The pytest marker for tests that need the SDK on this machine. They are not
#: part of the public CI, which fetches nothing and activates nothing
#: (spec sections 37 and 38).
ID3_ARTIFACT_MARKER = "id3_artifact"


# -------------------------------------------------------------- what is not done

NON_GOALS: tuple[str, ...] = (
    "no production adapter",
    "no configs/algorithms/id3 configuration",
    "no 6,000-comparison runner",
    "no ResultSet",
    "no threshold",
    "no DecisionProfile",
    "no calibration",
    "no metrics",
    "no SD300 read of any kind, including one image to see whether it works",
    "no licence activation in CI and no credentials in CI",
    "no selection of a fusion variant from vendor-reported accuracy",
)

#: The production surfaces this stage does not create, named individually so a
#: reviewer can check for each one rather than trusting a sentence
#: (spec section 35).
PRODUCTION_INTEGRATION_NOT_CREATED: tuple[str, ...] = (
    "algorithm_config",
    "production_adapter",
    "comparison_runner",
    "result_set",
    "threshold",
    "decision_profile",
    "calibration",
    "metrics",
)


# --------------------------------------------------------------- the source set

#: Every source file Stage 10B owns outright, audited for import boundaries and
#: pinned by the marker. A change to any of them changes what this preflight
#: concluded.
STAGE_10B_SOURCE_FILES: tuple[str, ...] = (
    "src/fpbench/core/id3_preflight_errors.py",
    "src/fpbench/experiments/stage10b_id3_identity.py",
    "src/fpbench/experiments/stage10b_id3_observations.py",
    "src/fpbench/experiments/stage10b_preflight.py",
    "src/fpbench/experiments/stage10b_finalization.py",
)

STAGE_10B_ADRS: tuple[str, ...] = (
    "docs/adr/0094-stage-10b-preflights-id3-before-algorithm-4-selection.md",
    "docs/adr/0095-proprietary-access-and-research-use-are-separate-gates.md",
    (
        "docs/adr/0096-evaluation-license-capacity-must-cover-the-frozen-"
        "workload.md"
    ),
    (
        "docs/adr/0097-id3-extractor-and-matcher-defaults-are-part-of-algorithm-"
        "identity.md"
    ),
    (
        "docs/adr/0098-id3-secrets-and-license-material-never-enter-public-"
        "evidence.md"
    ),
)

STAGE_10B_DOCUMENTS: tuple[str, ...] = (
    "docs/experiments/stage10b-id3-finger-sdk-preflight.md",
    "docs/algorithms/algorithm4-candidates/id3-finger-sdk.md",
)


def all_frozen_identifiers() -> tuple[str, ...]:
    """Every Stage 10B identifier, validated as a safe path and key component."""
    identifiers = (
        STAGE_FINALIZATION_KIND,
        ALGORITHM_SLOT,
        CANDIDATE_ID,
        ARTIFACT_STORE_PREFIX.replace("-", "_"),
        ID3_ARTIFACT_MARKER,
        *(name for name, _ in DECLARED_NON_CANDIDATES),
        *PRODUCTION_INTEGRATION_NOT_CREATED,
        *PUBLISHABLE_LICENSE_FACTS,
        *RUNTIME_TARGET_FIELDS,
    )
    for identifier in identifiers:
        validate_id(identifier)
    return identifiers


def _require_no_duplicate_documents() -> None:
    """Every gate document is one of the published files, and named once."""
    seen: list[str] = []
    for _, names in GATE_DOCUMENTS:
        seen.extend(names)
    duplicates = sorted({name for name in seen if seen.count(name) > 1})
    if duplicates:  # pragma: no cover - a constant-table mistake
        raise Id3CandidateIdentityError(
            f"two gates report through the same document: {duplicates}"
        )
    unknown = sorted(set(seen) - set(REQUIRED_EVIDENCE_FILES))
    if unknown:  # pragma: no cover - a constant-table mistake
        raise Id3CandidateIdentityError(
            f"a gate reports through a document nothing publishes: {unknown}"
        )
    covered = tuple(gate for gate, _ in GATE_DOCUMENTS)
    if covered != GATE_ORDER:  # pragma: no cover - a constant-table mistake
        raise Id3CandidateIdentityError(
            "the gate-document table and the gate order disagree"
        )


def _require_evidence_paths_are_plain() -> None:
    """No published name escapes the evidence directory."""
    for name in REQUIRED_EVIDENCE_FILES:
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or len(path.parts) != 1:
            raise Id3CandidateIdentityError(  # pragma: no cover - constant table
                f"{name!r} is not a plain file name below the evidence directory"
            )


_require_no_duplicate_documents()
_require_evidence_paths_are_plain()
