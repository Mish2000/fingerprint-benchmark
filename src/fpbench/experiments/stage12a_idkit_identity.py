"""Everything Stage 12A froze before it opened an Innovatrics IDKit package.

These constants are the stage's contract with itself: the one provisional
candidate, the ten hard gates and the order they run in, the acquisition state
machine and which of its states is a refusal, the closed blocker vocabulary, the
three outcomes, the provenance a score-affecting setting must carry, the frozen
workload, the conjunction that admits the candidate, and the keys no published
document may ever carry. They are asserted by the contract suite, republished in
the finalization, and a later change to any of them is a different preflight
rather than a quiet correction to this one.

Stage 12A asks one question:

.. code-block:: text

    does an official, current Innovatrics IDKit package give fpbench a complete,
    upstream-authoritative and reproducible route from canonical_500 to a raw 1:1
    fingerprint score, without fpbench inventing preprocessing, extractor
    settings, matcher settings or a score transformation?

It is allowed to answer "no", and it is allowed to answer "not yet"
(docs/adr/0107, docs/adr/0108).

**The package is the authority, not the version on a course page.** Innovatrics'
learning portal currently publishes material for IDKit SDK 7.6, and that is an
indication of what to look for and nothing more. ``implementation_version``
starts at :data:`IMPLEMENTATION_VERSION_UNRESOLVED` and is settled by the package
reporting on itself (docs/adr/0110).

**Stage 11A and Stage 11B are not re-opened.** Their candidate was VeriFinger,
their slot was Algorithm 4 and Stage 11B published 6,000 canonical raw outcomes
under it. Stage 12A binds Stage 11B's fingerprint as a predecessor, occupies
``algorithm_5``, and edits nothing under either evidence directory.

Nothing here is derived at import time, nothing reads a workspace, nothing
downloads anything, and nothing is a fingerprint image, a score, a template, a
licence byte or a credential.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath

from fpbench.core.identifiers import validate_id
from fpbench.core.idkit_preflight_errors import IdkitCandidateIdentityError

__all__ = [
    "STAGE_12A_SCHEMA_VERSION",
    "STAGE_FINALIZATION_KIND",
    "ALGORITHM_SLOT",
    "STAGE_12A_PASS_OUTCOME",
    "STAGE_12A_FAIL_OUTCOME",
    "STAGE_12A_PENDING_OUTCOME",
    "STAGE_12A_OUTCOMES",
    "STAGE_12A_FINAL_OUTCOMES",
    "CANDIDATE_ID",
    "IMPLEMENTATION_ORIGIN",
    "IMPLEMENTATION_VERSION_UNRESOLVED",
    "PRODUCTION_ALGORITHM_ID_FROZEN",
    "PREFERRED_TARGET_PLATFORM",
    "PLATFORM_IS_FINAL_ONLY_WITH_A_PACKAGE",
    "FINAL_IDENTITY_COMPONENTS",
    "EVIDENCE_DIRECTORY",
    "README_NAME",
    "PREDECESSOR_BINDING_NAME",
    "ACQUISITION_STATUS_NAME",
    "PACKAGE_MANIFEST_NAME",
    "RESEARCH_USE_LICENSE_NAME",
    "RUNTIME_INVENTORY_NAME",
    "INPUT_ROUTE_NAME",
    "FINGERPRINT_ROUTE_PROFILE_NAME",
    "SCORE_CONTRACT_NAME",
    "QUALIFICATION_RUN_NAME",
    "TRAINING_PROVENANCE_NAME",
    "PREFLIGHT_REPORT_NAME",
    "STAGE_12A_FINALIZATION_NAME",
    "REQUIRED_EVIDENCE_FILES",
    "DERIVABLE_EVIDENCE_FILES",
    "PreflightGate",
    "GATE_ORDER",
    "GATE_COUNT",
    "GateStatus",
    "PENDING_CAPABLE_GATES",
    "GATE_DOCUMENTS",
    "gate_documents",
    "BlockerCode",
    "GATE_BLOCKERS",
    "gate_of_blocker",
    "AcquisitionStatus",
    "ACQUISITION_PENDING_STATES",
    "ACQUISITION_REFUSAL_STATES",
    "DeliveryChannel",
    "REFUSED_ACQUISITION_SOURCES",
    "ProductFamily",
    "REFUSED_PRODUCT_FAMILIES",
    "PACKAGE_IDENTITY_FIELDS",
    "RUNTIME_COMPONENT_FIELDS",
    "RUNTIME_COMPONENT_CLASSES",
    "BINDING_SELECTION_CRITERIA",
    "LICENSE_SEPARATED_QUESTIONS",
    "BENCHMARK_INPUT_PROFILE",
    "BENCHMARK_INPUT_PPI",
    "BENCHMARK_INPUT_PIXEL_FORMAT",
    "IDEAL_INPUT_ROUTE",
    "PERMITTED_DECODE_ROUTE",
    "DECODE_EQUIVALENCE_REQUIREMENTS",
    "REFUSED_PREPROCESSING",
    "INTERNAL_BLACK_BOX_PREPROCESSING_IS_ACCEPTABLE",
    "REQUIRED_INPUT_DPI",
    "DPI_MUST_BE_SET_BEFORE_EXTRACTION",
    "RepresentationType",
    "REPRESENTATION_FACTS_TO_ESTABLISH",
    "PUBLISHABLE_REPRESENTATION_FACTS",
    "REFUSED_MULTI_FINGER_CONSTRUCTIONS",
    "SINGLE_FINGER_RECORD_RULE",
    "SettingProvenance",
    "REFUSED_SETTING_PROVENANCE",
    "SETTING_FAMILIES_TO_INVENTORY",
    "SETTING_ROW_FIELDS",
    "ScoreRouteStatus",
    "SCORE_CONTRACT_REQUIREMENTS",
    "INSUFFICIENT_SCORE_SHAPES",
    "REFUSED_THRESHOLD_MANIPULATION",
    "FPBENCH_SCORE_TRANSFORMATION",
    "REFUSED_SCORE_TRANSFORMATIONS",
    "SETTINGS_CLOSURE_FAMILIES",
    "PAIR_ROLE_BINDING",
    "PAIR_ORIENTATION_REQUIREMENTS",
    "REFUSED_ORIENTATION_REDUCTIONS",
    "SELF_SEMANTICS_REQUIREMENTS",
    "DETERMINISM_LEVELS",
    "FAILURE_SEMANTICS_CAUSES",
    "FAILURE_SEMANTICS_RULE",
    "QUALIFICATION_PASSES",
    "QUALIFICATION_MAX_SCORING_COMPARISONS",
    "QUALIFICATION_FIXTURE_SOURCES",
    "QualificationOutcome",
    "QUALIFICATION_RECORD_NAME",
    "QUALIFICATION_RECORD_SCHEMA",
    "FROZEN_COMPARISON_ATTEMPTS",
    "FROZEN_INDEPENDENT_EXTRACTIONS",
    "FROZEN_MATCHER_INVOCATIONS",
    "REPRESENTATION_CACHE_PERMITTED",
    "FrozenWorkload",
    "FROZEN_WORKLOAD",
    "LICENSE_CAPACITY_QUESTIONS",
    "RUNTIME_FEASIBILITY_MEASUREMENTS",
    "TrainingProvenanceStatus",
    "SD300OverlapStatus",
    "SD300_OVERLAP_SURFACES",
    "FailureClass",
    "FORBIDDEN_READS",
    "NON_GOALS",
    "PRODUCTION_INTEGRATION_NOT_CREATED",
    "PERMITTED_CONSTRUCTIONS",
    "ACCEPTANCE_CONDITIONS",
    "SENSITIVE_EVIDENCE_KEYS",
    "SENSITIVE_VALUE_PATTERNS",
    "FORBIDDEN_PUBLISHED_KEYS",
    "STAGE_11B_OUTCOME",
    "STAGE_11B_FINALIZATION_FINGERPRINT",
    "STAGE_11B_EVIDENCE_DIRECTORY",
    "STAGE8E_FINALIZATION_FINGERPRINT",
    "STAGE8E_OUTCOME",
    "STAGE8E_PURPOSE_FINGERPRINT",
    "STAGE8E_POLICY_FINGERPRINT",
    "ARTIFACT_STORE_PREFIX",
    "STAGE_12A_SOURCE_FILES",
    "all_frozen_identifiers",
]

STAGE_12A_SCHEMA_VERSION = "1"
STAGE_FINALIZATION_KIND = "stage_12a_finalization"

#: The slot this candidate would occupy. Algorithm 4 is VeriFinger 2025.2, taken
#: by Stage 11A and filled with 6,000 canonical raw outcomes by Stage 11B; this
#: is the next slot and not a re-run of that one.
ALGORITHM_SLOT = "algorithm_5"


# ---------------------------------------------------------------- the outcomes

#: The route qualified. Every gate passed on a delivered package.
STAGE_12A_PASS_OUTCOME = "IDKIT_PREFLIGHT_PASS"

#: A real blocker was observed. Something about the route, the package or the
#: licence makes it unusable as a benchmark algorithm, and a named blocker says
#: which.
STAGE_12A_FAIL_OUTCOME = "IDKIT_PREFLIGHT_FAIL"

#: Nobody has replied yet. Not a verdict about IDKit and not a defect in it: an
#: official acquisition route exists, has been walked as far as this project can
#: walk it, and is waiting on a vendor or on portal access. No finalization
#: marker is written under this outcome (docs/adr/0108).
STAGE_12A_PENDING_OUTCOME = "IDKIT_PREFLIGHT_PENDING_ACCESS"

STAGE_12A_OUTCOMES: tuple[str, ...] = (
    STAGE_12A_PASS_OUTCOME,
    STAGE_12A_FAIL_OUTCOME,
    STAGE_12A_PENDING_OUTCOME,
)

#: The two outcomes a marker may carry. ``PENDING`` is deliberately absent: a
#: marker is a finalization, and there is nothing final about waiting for an
#: email. The distinction is enforced by the marker itself and by the publisher.
STAGE_12A_FINAL_OUTCOMES: tuple[str, ...] = (
    STAGE_12A_PASS_OUTCOME,
    STAGE_12A_FAIL_OUTCOME,
)


# --------------------------------------------------------------- the candidate

CANDIDATE_ID = validate_id("innovatrics_idkit_fingerprint_1to1")

#: Where an implementation would come from. The same value Stage 11A used for
#: VeriFinger, and it carries the same obligation: an official package from the
#: vendor's own channel, never a mirror.
IMPLEMENTATION_ORIGIN = "VENDOR_OFFICIAL_SDK"

#: What the version is until a package reports its own. Not ``"7.6"``: that
#: number comes from a public course listing, which is an indication of what to
#: look for and not a statement about the bytes this project would run
#: (docs/adr/0110).
IMPLEMENTATION_VERSION_UNRESOLVED = "UNRESOLVED_UNTIL_PACKAGE"

#: Whether a production algorithm id may be minted from this stage. It may not.
#: A benchmark algorithm id pins a version, a platform and a settings profile,
#: and Stage 12A has none of the three until a package is in hand.
PRODUCTION_ALGORITHM_ID_FROZEN = False

#: What to aim at first, and nothing more. The host this project already runs
#: Algorithm 4 on, so a shared platform keeps the comparison cheap — but a
#: platform is chosen from what the vendor actually delivers.
PREFERRED_TARGET_PLATFORM = "windows/x86_64"
PLATFORM_IS_FINAL_ONLY_WITH_A_PACKAGE = True

#: What a final algorithm identity would have to name. Every one of them is a
#: property of a delivered package, which is why none is frozen today.
FINAL_IDENTITY_COMPONENTS: tuple[str, ...] = (
    "exact_product_name",
    "product_family",
    "implementation_version",
    "package_build",
    "package_sha256",
    "platform",
    "selected_official_binding",
    "extraction_settings_profile",
    "matcher_settings_profile",
    "representation_type",
)


# ------------------------------------------------------------------- evidence

#: Assembled from parts for the reason every stage since 8C assembles its own
#: name: this module's source is audited for literals that name published
#: evidence, and the audit has to be able to tell "my own directory" from
#: "somebody else's".
EVIDENCE_DIRECTORY = Path("evidence") / ("stage12a-" + "idkit-preflight")

README_NAME = "README.md"
PREDECESSOR_BINDING_NAME = "predecessor-binding.json"
ACQUISITION_STATUS_NAME = "acquisition-status.json"
PACKAGE_MANIFEST_NAME = "package-manifest.json"
RESEARCH_USE_LICENSE_NAME = "research-use-license.json"
RUNTIME_INVENTORY_NAME = "runtime-inventory.json"
INPUT_ROUTE_NAME = "input-route.json"
FINGERPRINT_ROUTE_PROFILE_NAME = "fingerprint-route-profile.json"
SCORE_CONTRACT_NAME = "score-contract.json"
QUALIFICATION_RUN_NAME = "qualification-run.json"
TRAINING_PROVENANCE_NAME = "training-provenance.json"
PREFLIGHT_REPORT_NAME = "preflight-report.json"
STAGE_12A_FINALIZATION_NAME = "stage-12a-finalization.json"

#: The compact set the specification fixed. Thirteen names, one of which exists
#: only under a final outcome.
REQUIRED_EVIDENCE_FILES: tuple[str, ...] = (
    README_NAME,
    PREDECESSOR_BINDING_NAME,
    ACQUISITION_STATUS_NAME,
    PACKAGE_MANIFEST_NAME,
    RESEARCH_USE_LICENSE_NAME,
    RUNTIME_INVENTORY_NAME,
    INPUT_ROUTE_NAME,
    FINGERPRINT_ROUTE_PROFILE_NAME,
    SCORE_CONTRACT_NAME,
    QUALIFICATION_RUN_NAME,
    TRAINING_PROVENANCE_NAME,
    PREFLIGHT_REPORT_NAME,
    STAGE_12A_FINALIZATION_NAME,
)

#: What the engine derives. The README is written by hand and the marker is
#: derived against the committed bytes of everything else, so neither is here.
DERIVABLE_EVIDENCE_FILES: tuple[str, ...] = tuple(
    name
    for name in REQUIRED_EVIDENCE_FILES
    if name not in (README_NAME, STAGE_12A_FINALIZATION_NAME)
)


# ---------------------------------------------------------------- the ten gates


class PreflightGate(str, Enum):
    """The ten hard gates. Every one of them is mandatory.

    Ten, not seventeen, and no sub-gates. Stage 11A's seventeen were the right
    shape for an artifact this project could download in one command and then
    interrogate at leisure; IDKit is delivered through a customer portal, and the
    risk is no longer "does it do fingerprints" but "does the delivered package
    give a single-finger raw-score route whose settings can all be frozen". Ten
    gates ask exactly that and stop (docs/adr/0107).

    The order is the design. Acquisition is first because every later question is
    a question about a package. The raw score comes before workload and
    provenance because a route with no scalar score is not worth measuring.
    """

    ACQUISITION_ACCESS = "ACQUISITION_ACCESS"
    PACKAGE_RUNTIME_IDENTITY = "PACKAGE_RUNTIME_IDENTITY"
    RESEARCH_USE_AND_LICENSE = "RESEARCH_USE_AND_LICENSE"
    CANONICAL500_INPUT_ROUTE = "CANONICAL500_INPUT_ROUTE"
    SINGLE_FINGER_EXTRACTION_PROFILE = "SINGLE_FINGER_EXTRACTION_PROFILE"
    SINGLE_FINGER_MATCHER_RAW_SCORE = "SINGLE_FINGER_MATCHER_RAW_SCORE"
    SCORE_AFFECTING_SETTINGS_CLOSURE = "SCORE_AFFECTING_SETTINGS_CLOSURE"
    PAIR_SELF_DETERMINISM_FAILURES = "PAIR_SELF_DETERMINISM_FAILURES"
    WORKLOAD_RUNTIME_FEASIBILITY = "WORKLOAD_RUNTIME_FEASIBILITY"
    TRAINING_PROVENANCE = "TRAINING_PROVENANCE"


GATE_ORDER: tuple[PreflightGate, ...] = (
    PreflightGate.ACQUISITION_ACCESS,
    PreflightGate.PACKAGE_RUNTIME_IDENTITY,
    PreflightGate.RESEARCH_USE_AND_LICENSE,
    PreflightGate.CANONICAL500_INPUT_ROUTE,
    PreflightGate.SINGLE_FINGER_EXTRACTION_PROFILE,
    PreflightGate.SINGLE_FINGER_MATCHER_RAW_SCORE,
    PreflightGate.SCORE_AFFECTING_SETTINGS_CLOSURE,
    PreflightGate.PAIR_SELF_DETERMINISM_FAILURES,
    PreflightGate.WORKLOAD_RUNTIME_FEASIBILITY,
    PreflightGate.TRAINING_PROVENANCE,
)

GATE_COUNT = len(GATE_ORDER)


class GateStatus(str, Enum):
    """What one gate concluded.

    ``NOT_REACHED`` is not a soft failure and not a pass: the run had already
    stopped, so this question was never asked.

    ``PENDING`` is narrower still and belongs to exactly one gate. It says an
    official route was walked and has not answered yet. It is not a failure, it
    is not a finding about the candidate, and it never finalises anything
    (docs/adr/0108).
    """

    PASS = "PASS"
    FAIL = "FAIL"
    PENDING = "PENDING"
    NOT_REACHED = "NOT_REACHED"


#: The only gate that may report ``PENDING``. Acquisition is the one question
#: whose answer can legitimately be "somebody else has to reply first"; every
#: other gate is a question this project answers for itself once a package is
#: here, so a pending answer anywhere else would be a way of not deciding.
PENDING_CAPABLE_GATES: tuple[PreflightGate, ...] = (
    PreflightGate.ACQUISITION_ACCESS,
)

#: The documents each gate reports through. Three gates own no document of their
#: own: the settings closure is published inside the profile and score documents
#: it closes over, workload feasibility beside the licence questions it runs
#: against, and pair/SELF/determinism inside the qualification record that
#: produced them. A second document restating one of those would be two
#: authorities for one number.
GATE_DOCUMENTS: tuple[tuple[PreflightGate, tuple[str, ...]], ...] = (
    (PreflightGate.ACQUISITION_ACCESS, (ACQUISITION_STATUS_NAME,)),
    (
        PreflightGate.PACKAGE_RUNTIME_IDENTITY,
        (PACKAGE_MANIFEST_NAME, RUNTIME_INVENTORY_NAME),
    ),
    (PreflightGate.RESEARCH_USE_AND_LICENSE, (RESEARCH_USE_LICENSE_NAME,)),
    (PreflightGate.CANONICAL500_INPUT_ROUTE, (INPUT_ROUTE_NAME,)),
    (
        PreflightGate.SINGLE_FINGER_EXTRACTION_PROFILE,
        (FINGERPRINT_ROUTE_PROFILE_NAME,),
    ),
    (PreflightGate.SINGLE_FINGER_MATCHER_RAW_SCORE, (SCORE_CONTRACT_NAME,)),
    (PreflightGate.SCORE_AFFECTING_SETTINGS_CLOSURE, ()),
    (PreflightGate.PAIR_SELF_DETERMINISM_FAILURES, (QUALIFICATION_RUN_NAME,)),
    (PreflightGate.WORKLOAD_RUNTIME_FEASIBILITY, ()),
    (PreflightGate.TRAINING_PROVENANCE, (TRAINING_PROVENANCE_NAME,)),
)


def gate_documents(gate: PreflightGate) -> tuple[str, ...]:
    """The documents one gate reports through, possibly none."""
    for item, names in GATE_DOCUMENTS:
        if item is gate:
            return names
    raise IdkitCandidateIdentityError(  # pragma: no cover - GATE_ORDER is exhaustive
        f"{gate!r} is not a Stage 12A gate"
    )


class BlockerCode(str, Enum):
    """Why IDKit cannot enter fpbench as Algorithm 5. A closed list.

    Exactly the vocabulary the specification fixed. Each member names something a
    reader could act on, and each is attached to exactly one gate below. "Not
    ideal", "some risk" and "probably fine" are not among them and cannot be
    expressed here.

    None of these can be raised by waiting. ``PORTAL_ACCESS_REQUIRED``,
    ``REQUEST_SENT`` and ``REQUEST_PENDING`` are acquisition states and have no
    blocker code, because a blocker is a finding and none of the three is one
    (docs/adr/0108).
    """

    ACCESS_REFUSED_BY_VENDOR = "ACCESS_REFUSED_BY_VENDOR"
    OFFICIAL_PACKAGE_UNAVAILABLE = "OFFICIAL_PACKAGE_UNAVAILABLE"

    RESEARCH_USE_BLOCKED = "RESEARCH_USE_BLOCKED"
    LICENSE_ACTIVATION_FAILED = "LICENSE_ACTIVATION_FAILED"
    LICENSE_WORKLOAD_INSUFFICIENT = "LICENSE_WORKLOAD_INSUFFICIENT"

    PACKAGE_IDENTITY_UNRESOLVED = "PACKAGE_IDENTITY_UNRESOLVED"
    RUNTIME_COMPONENT_UNRESOLVED = "RUNTIME_COMPONENT_UNRESOLVED"

    CANONICAL500_INPUT_ROUTE_UNRESOLVED = "CANONICAL500_INPUT_ROUTE_UNRESOLVED"
    FPBENCH_PREPROCESSING_CHOICE_REQUIRED = "FPBENCH_PREPROCESSING_CHOICE_REQUIRED"

    SINGLE_FINGER_EXTRACTION_ROUTE_UNRESOLVED = (
        "SINGLE_FINGER_EXTRACTION_ROUTE_UNRESOLVED"
    )
    EXTRACTION_PROFILE_UNRESOLVED = "EXTRACTION_PROFILE_UNRESOLVED"
    MATCHER_PROFILE_UNRESOLVED = "MATCHER_PROFILE_UNRESOLVED"
    RAW_SCORE_ROUTE_UNRESOLVED = "RAW_SCORE_ROUTE_UNRESOLVED"
    HIDDEN_SCORE_AFFECTING_DEFAULT_UNRESOLVED = (
        "HIDDEN_SCORE_AFFECTING_DEFAULT_UNRESOLVED"
    )

    PAIR_ROLE_SEMANTICS_UNRESOLVED = "PAIR_ROLE_SEMANTICS_UNRESOLVED"
    SCORE_NONDETERMINISM_OBSERVED = "SCORE_NONDETERMINISM_OBSERVED"
    LOCAL_SMOKE_FAILED = "LOCAL_SMOKE_FAILED"

    SD300_TRAINING_OVERLAP_FOUND = "SD300_TRAINING_OVERLAP_FOUND"


#: Which gate each blocker belongs to. A blocker raised against a gate that was
#: never reached is a contradiction, and the engine refuses one.
#:
#: ``SINGLE_FINGER_EXTRACTION_ROUTE_UNRESOLVED`` sits at the extraction gate and
#: ``RAW_SCORE_ROUTE_UNRESOLVED`` at the matcher gate even though both can be
#: caused by the same thing — an API that only scores whole user records. They
#: stay separate because the fixes differ: one is a way to build a one-finger
#: record, the other is a way to read a per-pair number out of the matcher.
GATE_BLOCKERS: tuple[tuple[PreflightGate, tuple[BlockerCode, ...]], ...] = (
    (
        PreflightGate.ACQUISITION_ACCESS,
        (
            BlockerCode.ACCESS_REFUSED_BY_VENDOR,
            BlockerCode.OFFICIAL_PACKAGE_UNAVAILABLE,
        ),
    ),
    (
        PreflightGate.PACKAGE_RUNTIME_IDENTITY,
        (
            BlockerCode.PACKAGE_IDENTITY_UNRESOLVED,
            BlockerCode.RUNTIME_COMPONENT_UNRESOLVED,
        ),
    ),
    (
        PreflightGate.RESEARCH_USE_AND_LICENSE,
        (
            BlockerCode.RESEARCH_USE_BLOCKED,
            BlockerCode.LICENSE_ACTIVATION_FAILED,
        ),
    ),
    (
        PreflightGate.CANONICAL500_INPUT_ROUTE,
        (
            BlockerCode.CANONICAL500_INPUT_ROUTE_UNRESOLVED,
            BlockerCode.FPBENCH_PREPROCESSING_CHOICE_REQUIRED,
        ),
    ),
    (
        PreflightGate.SINGLE_FINGER_EXTRACTION_PROFILE,
        (
            BlockerCode.SINGLE_FINGER_EXTRACTION_ROUTE_UNRESOLVED,
            BlockerCode.EXTRACTION_PROFILE_UNRESOLVED,
        ),
    ),
    (
        PreflightGate.SINGLE_FINGER_MATCHER_RAW_SCORE,
        (
            BlockerCode.MATCHER_PROFILE_UNRESOLVED,
            BlockerCode.RAW_SCORE_ROUTE_UNRESOLVED,
        ),
    ),
    (
        PreflightGate.SCORE_AFFECTING_SETTINGS_CLOSURE,
        (BlockerCode.HIDDEN_SCORE_AFFECTING_DEFAULT_UNRESOLVED,),
    ),
    (
        PreflightGate.PAIR_SELF_DETERMINISM_FAILURES,
        (
            BlockerCode.PAIR_ROLE_SEMANTICS_UNRESOLVED,
            BlockerCode.SCORE_NONDETERMINISM_OBSERVED,
            BlockerCode.LOCAL_SMOKE_FAILED,
        ),
    ),
    (
        PreflightGate.WORKLOAD_RUNTIME_FEASIBILITY,
        (BlockerCode.LICENSE_WORKLOAD_INSUFFICIENT,),
    ),
    (
        PreflightGate.TRAINING_PROVENANCE,
        (BlockerCode.SD300_TRAINING_OVERLAP_FOUND,),
    ),
)


def gate_of_blocker(code: BlockerCode) -> tuple[PreflightGate, ...]:
    """Which gate may raise this blocker. Exactly one, checked at import."""
    return tuple(gate for gate, codes in GATE_BLOCKERS if code in codes)


# -------------------------------------------------------------- acquisition


class AcquisitionStatus(str, Enum):
    """Where the attempt to obtain an official package actually stands.

    Seven states, and the difference between the middle three and the last two is
    the whole reason this vocabulary exists. Stage 10B published
    ``ID3_FINGER_SDK_PREFLIGHT_FAIL`` for a vendor nobody had written to, and the
    word "FAIL" then had to be explained in every document that carried it. Here
    the state says it: nobody asked, or somebody asked and is waiting, or the
    vendor said no.
    """

    #: Nothing has been tried.
    NOT_ATTEMPTED = "NOT_ATTEMPTED"

    #: The official route exists and terminates at a login this project has no
    #: account for. Walked as far as it goes without credentials.
    PORTAL_ACCESS_REQUIRED = "PORTAL_ACCESS_REQUIRED"

    #: A request has been sent to the vendor through an official channel.
    REQUEST_SENT = "REQUEST_SENT"

    #: The vendor has acknowledged and not yet delivered.
    REQUEST_PENDING = "REQUEST_PENDING"

    #: The bytes are here.
    PACKAGE_OBTAINED = "PACKAGE_OBTAINED"

    #: The vendor declined. A finding, and the strongest one this gate can make.
    ACCESS_REFUSED = "ACCESS_REFUSED"

    #: The vendor offers no package for the platform this benchmark needs.
    PACKAGE_UNAVAILABLE_FOR_TARGET = "PACKAGE_UNAVAILABLE_FOR_TARGET"

    @property
    def is_pending(self) -> bool:
        return self in ACQUISITION_PENDING_STATES

    @property
    def is_refusal(self) -> bool:
        return self in ACQUISITION_REFUSAL_STATES

    @property
    def is_obtained(self) -> bool:
        return self is AcquisitionStatus.PACKAGE_OBTAINED


#: States that hold the stage open. None of them may become a blocker, and none
#: of them finalises anything.
ACQUISITION_PENDING_STATES: tuple[AcquisitionStatus, ...] = (
    AcquisitionStatus.NOT_ATTEMPTED,
    AcquisitionStatus.PORTAL_ACCESS_REQUIRED,
    AcquisitionStatus.REQUEST_SENT,
    AcquisitionStatus.REQUEST_PENDING,
)

#: The only two states that may produce ``IDKIT_PREFLIGHT_FAIL`` at this gate. A
#: real refusal, or a package that does not exist for the target.
ACQUISITION_REFUSAL_STATES: tuple[AcquisitionStatus, ...] = (
    AcquisitionStatus.ACCESS_REFUSED,
    AcquisitionStatus.PACKAGE_UNAVAILABLE_FOR_TARGET,
)


class DeliveryChannel(str, Enum):
    """Who handed the package over. A closed set of official channels."""

    CUSTOMER_PORTAL = "CUSTOMER_PORTAL"
    VENDOR_SUPPORT = "VENDOR_SUPPORT"
    VENDOR_SALES = "VENDOR_SALES"
    OTHER_VENDOR_OFFICIAL = "OTHER_VENDOR_OFFICIAL"


#: Sources that are not acquisition, whatever they contain. Named as categories
#: rather than as hostnames, because the rule is about provenance and not about
#: any particular site: a package whose chain of custody runs through a third
#: party is a package nobody can pin.
REFUSED_ACQUISITION_SOURCES: tuple[str, ...] = (
    "a download mirror",
    "a software-catalogue or freeware site",
    "a third-party GitHub repository",
    "a reseller or distributor store",
    "an archive somebody uploaded",
    "a copy received from another project",
)


class ProductFamily(str, Enum):
    """Which Innovatrics product the package actually is.

    The one confusion this gate exists to catch. IDKit generates Innovatrics'
    proprietary fingerprint templates and supports 1:1 verification as well as
    1:N identification; the ANSI&ISO SDK is a different product that generates
    and matches standardised templates. A package that turned out to be the
    wrong one would still produce numbers, and they would be numbers about a
    different algorithm.
    """

    IDKIT_SDK = "IDKIT_SDK"
    ANSI_ISO_SDK = "ANSI_ISO_SDK"
    IDKIT_MULTI = "IDKIT_MULTI"
    ENROLLMENT_SDK = "ENROLLMENT_SDK"
    MOBILE_FINGERS_SDK = "MOBILE_FINGERS_SDK"
    UNRESOLVED = "UNRESOLVED"


#: Everything this candidate is not. A delivered package that resolves to one of
#: these is not a smaller version of the candidate; it is a different one, and it
#: would need its own preflight.
REFUSED_PRODUCT_FAMILIES: tuple[ProductFamily, ...] = (
    ProductFamily.ANSI_ISO_SDK,
    ProductFamily.IDKIT_MULTI,
    ProductFamily.ENROLLMENT_SDK,
    ProductFamily.MOBILE_FINGERS_SDK,
)

#: What has to be established about the package before anything is executed. Ten
#: fields, every one of them a property of the delivered bytes.
PACKAGE_IDENTITY_FIELDS: tuple[str, ...] = (
    "exact_product_name",
    "product_family",
    "implementation_version",
    "package_build",
    "package_filename",
    "package_size_bytes",
    "package_sha256",
    "delivery_channel",
    "operating_system",
    "architecture",
)

#: What is recorded for each score-relevant runtime component. Vendor bytes stay
#: in the local artifact store; the repository holds only these descriptions.
RUNTIME_COMPONENT_FIELDS: tuple[str, ...] = (
    "relative_path",
    "role",
    "size_bytes",
    "sha256",
    "version_or_build",
)

#: The classes of thing the fingerprint route can need. The inventory is closed
#: when every one of these has been either found or ruled out.
RUNTIME_COMPONENT_CLASSES: tuple[str, ...] = (
    "native_library",
    "managed_wrapper_or_jar",
    "algorithm_model_or_data_file",
    "runtime_configuration",
    "licensing_runtime_dependency",
)

#: How the one official binding is chosen, in order. There is no requirement that
#: it be C++, .NET or Java: the requirement is that one binding satisfies all
#: five and that the route does not mix a sample from one with a function from
#: another and a default from a support page.
BINDING_SELECTION_CRITERIA: tuple[str, ...] = (
    "version-matched to the delivered package",
    "supplied by the vendor inside that package",
    "ships a complete fingerprint 1:1 sample",
    "exposes every setting that can affect the template or the score",
    "returns the raw scalar score",
)

#: Four questions that are routinely collapsed into one and are not one. A
#: package can be obtainable and its terms still forbid research use; the terms
#: can permit it and the licence still fail to activate; it can activate and its
#: entitlement still not cover 6,000 comparisons.
LICENSE_SEPARATED_QUESTIONS: tuple[str, ...] = (
    "package_obtainable",
    "research_use_permitted",
    "license_activated",
    "workload_permitted",
)


# ------------------------------------------------------------- the input route

BENCHMARK_INPUT_PROFILE = "canonical_500"
BENCHMARK_INPUT_PPI = 500
BENCHMARK_INPUT_PIXEL_FORMAT = "gray8"

#: What the route should be, if the delivered package reads the container the
#: benchmark already holds.
IDEAL_INPUT_ROUTE: tuple[str, ...] = (
    "canonical_500 PNG",
    "official IDKit image loader",
    "explicit 500 DPI before extraction",
    "extraction",
)

#: What the route may be instead. Public support material says IDKit accepts BMP
#: or raw images in memory or in files, which — if the delivered package still
#: behaves that way — means the benchmark's PNG has to be decoded before it is
#: handed over. That is permitted, and only under the proof below: a decode that
#: produced different pixels would be fpbench choosing a preprocessing step and
#: calling it a file format.
PERMITTED_DECODE_ROUTE: tuple[str, ...] = (
    "canonical_500 PNG",
    "deterministic lossless decode",
    "identical width x height x gray8 pixel matrix",
    "official IDKit raw image-buffer API",
    "explicit 500 DPI before extraction",
    "extraction",
)

#: What has to be proved before the decode route may be used. All four, over the
#: images the benchmark will actually run.
DECODE_EQUIVALENCE_REQUIREMENTS: tuple[str, ...] = (
    "the decode is lossless and deterministic on this platform",
    "width and height are unchanged",
    "the pixel format stays 8-bit grayscale",
    "every pixel value is identical to the PNG's decoded matrix",
)

#: Refused whatever the reason, unless upstream's own documented route performs
#: it inside the SDK. Each one changes the pixels a score is computed from, and a
#: benchmark that chose one would be reporting on fpbench's image processing.
REFUSED_PREPROCESSING: tuple[str, ...] = (
    "crop",
    "ROI selection",
    "resize by fpbench",
    "rotation",
    "padding",
    "enhancement",
    "histogram normalization",
    "contrast adjustment",
    "binarization",
    "sharpening",
    "denoising",
    "external minutiae extraction",
)

#: Whatever the SDK does to the pixels inside itself is the algorithm, and the
#: algorithm is what this benchmark measures. Public material says input images
#: are internally resampled to 500 dpi before extraction and that templates then
#: use 500 dpi coordinates — which, at 500 PPI in, is a resample to the
#: resolution the image already has.
INTERNAL_BLACK_BOX_PREPROCESSING_IS_ACCEPTABLE = True

REQUIRED_INPUT_DPI = 500

#: Where the DPI has to be set. Public material says the setting affects
#: extraction rather than 1:1 matching, and that a template remembers the DPI it
#: was extracted under — so setting it afterwards sets it for the next template
#: and not for the one already built. It is metadata about the image, not a
#: change to a pixel.
DPI_MUST_BE_SET_BEFORE_EXTRACTION = True


# --------------------------------------------------- the single-finger route


class RepresentationType(str, Enum):
    """What is actually compared.

    The default this stage wants is the proprietary IDKit representation, because
    that is the product under test. An ANSI or ISO export is a different matching
    scenario with its own accuracy, and choosing one because it is easier to
    store would be benchmarking a different algorithm under this one's name.
    """

    VENDOR_PROPRIETARY_TEMPLATE = "VENDOR_PROPRIETARY_TEMPLATE"
    ANSI_EXPORT = "ANSI_EXPORT"
    ISO_EXPORT = "ISO_EXPORT"
    UNRESOLVED = "UNRESOLVED"


#: What has to be settled about the representation before a score means anything.
REPRESENTATION_FACTS_TO_ESTABLISH: tuple[str, ...] = (
    "representation_type",
    "template_version_if_exposed",
    "single_finger_record_structure",
    "whether_one_user_container_is_required_by_the_api",
    "whether_image_retention_affects_matching",
)

#: The only facts about a template that may be published. The template itself is
#: not among them, and neither is any transformation of it.
PUBLISHABLE_REPRESENTATION_FACTS: tuple[str, ...] = (
    "representation_type",
    "template_version_if_exposed",
    "size_in_bytes",
    "whether_extraction_succeeded",
    "the_status_the_api_returned",
)

#: Ways of building a comparison that are not this benchmark's comparison. The
#: last one is the specific IDKit hazard: its user records can hold several
#: fingerprints and its consolidated score sums per-position maxima across them,
#: which is a different quantity from a single-finger similarity and cannot be
#: recovered from one.
REFUSED_MULTI_FINGER_CONSTRUCTIONS: tuple[str, ...] = (
    "multiple fingers in one record",
    "multiple impressions fused into one representation",
    "a user-level enrolment strategy",
    "an ANSI export used as the compared representation",
    "an ISO export used as the compared representation",
    "a consolidated multi-finger record score",
)

#: The rule, stated once. If the API works through user or record objects, each
#: side holds exactly one fingerprint — and if that cannot be guaranteed, the
#: extraction and matcher gates fail rather than being satisfied approximately.
SINGLE_FINGER_RECORD_RULE = (
    "probe record: exactly one fingerprint; gallery record: exactly one "
    "fingerprint"
)


# ----------------------------------------------------------- setting provenance


class SettingProvenance(str, Enum):
    """Where a setting's value came from. Every one of these is upstream's.

    ``UNRESOLVED`` is the only member that is not an authority, and a
    score-affecting setting carrying it fails the closure gate. A value nobody
    recorded still decides the score.
    """

    DELIVERED_RUNTIME_DEFAULT = "DELIVERED_RUNTIME_DEFAULT"
    VERSION_MATCHED_DOCUMENTED_DEFAULT = "VERSION_MATCHED_DOCUMENTED_DEFAULT"
    OFFICIAL_SAMPLE_EXPLICIT = "OFFICIAL_SAMPLE_EXPLICIT"
    UPSTREAM_EXPLICIT_RECOMMENDATION = "UPSTREAM_EXPLICIT_RECOMMENDATION"
    FPBENCH_PROTOCOL_BINDING = "FPBENCH_PROTOCOL_BINDING"
    UNRESOLVED = "UNRESOLVED"

    @property
    def is_upstream_authority(self) -> bool:
        """Whether this provenance settles a value.

        ``FPBENCH_PROTOCOL_BINDING`` counts, and it is the only member that is
        not upstream's own statement. It covers the deterministic mapping of an
        existing protocol fact onto an API — pair.left to probe, pair.right to
        gallery, 500 DPI for a 500 PPI image — where the value is *derived* from
        something the benchmark already froze rather than chosen because it
        performed better. It may never be used to pick a quality threshold, a
        speed profile or a template size.
        """
        return self is not SettingProvenance.UNRESOLVED


#: The one answer that is never acceptable, kept as a string rather than an enum
#: member so it cannot be selected by accident. A value chosen because it gave
#: better numbers on this project's fingerprints is not a setting; it is a result.
REFUSED_SETTING_PROVENANCE = "FPBENCH_CHOICE_TUNED_ON_OUR_DATA"

#: The families to look for in the delivered package's own documentation. Not a
#: list of parameter names: naming them in advance from another product's API is
#: how a stage ends up freezing a setting that does not exist and missing one
#: that does. The delivered package supplies the names.
SETTING_FAMILIES_TO_INVENTORY: tuple[str, ...] = (
    "resolution/DPI",
    "quality/rejection policy",
    "maximum template size",
    "extraction mode/profile",
    "fingerprint processing mode",
    "rotation/alignment controls",
    "image-format behaviour",
    "template format/version",
    "feature/minutiae limits",
    "speed/accuracy profile",
)

#: What is recorded for every setting found.
SETTING_ROW_FIELDS: tuple[str, ...] = (
    "name",
    "value",
    "can_affect_template_or_score",
    "provenance",
)


# ------------------------------------------------------------- the score route


class ScoreRouteStatus(str, Enum):
    """What the matcher gives back per comparison."""

    #: One scalar, readable independently of the match decision.
    NATIVE_SCALAR = "NATIVE_SCALAR"

    #: One scalar on a vendor-defined scale — for example one normalised against
    #: a claimed FAR. Still raw: the transformation is the vendor's own and is
    #: part of what the algorithm reports (docs/adr/0102 applies unchanged).
    NATIVE_TRANSFORMED_SCALAR = "NATIVE_TRANSFORMED_SCALAR"

    #: A decision, or a score the API only surrenders above a threshold.
    DECISION_ONLY = "DECISION_ONLY"

    UNRESOLVED = "UNRESOLVED"

    @property
    def is_raw_score(self) -> bool:
        return self in (
            ScoreRouteStatus.NATIVE_SCALAR,
            ScoreRouteStatus.NATIVE_TRANSFORMED_SCALAR,
        )


#: What has to be frozen about the score before six thousand of them are worth
#: producing. Every one comes from the delivered API, not from a support article.
SCORE_CONTRACT_REQUIREMENTS: tuple[str, ...] = (
    "exact_api_or_method",
    "result_field",
    "numeric_type",
    "defined_or_observed_range",
    "direction",
    "failure_behaviour",
    "score_bearing_statuses",
    "threshold_relationship",
)

#: Shapes that are not a raw score, however convenient. A benchmark built on any
#: of them would be measuring a threshold somebody chose.
INSUFFICIENT_SCORE_SHAPES: tuple[str, ...] = (
    "MATCH / NO_MATCH",
    "true / false",
    "a candidate list filtered by a threshold",
    "a score returned only above a threshold",
)

#: The specific workaround this stage refuses. Setting the threshold to zero to
#: make the numbers appear is not a raw-score route; it is a decision layer with
#: its knob turned down, and the benchmark's own decision layer belongs to a
#: later stage.
REFUSED_THRESHOLD_MANIPULATION = (
    "lowering or zeroing the matcher threshold in order to read scores that the "
    "API would otherwise withhold"
)

#: What fpbench does to a native score. Nothing.
FPBENCH_SCORE_TRANSFORMATION = "none"

#: Transformations that would each produce a different benchmark. The vendor's
#: own scale may already be a transformation of a FAR — that is the vendor's
#: business and part of what it reports. Applying a second one here is ours, and
#: it is refused.
REFUSED_SCORE_TRANSFORMATIONS: tuple[str, ...] = (
    "convert to FAR",
    "take -log FAR again",
    "rescale to a percentage",
    "rescale to 0..1",
    "z-score",
    "any other normalization",
    "clamp",
)

#: Everything the closure gate has to have frozen. A knob in any of these
#: families whose value and default are both unknown is a hidden score-affecting
#: default, and the gate fails on it.
SETTINGS_CLOSURE_FAMILIES: tuple[str, ...] = (
    "extraction options",
    "matching options",
    "template options",
    "quality/rejection options",
    "rotation parameters",
    "resolution parameters",
    "speed/accuracy modes",
    "score normalization modes",
    "single-finger versus multi-finger modes",
)


# --------------------------------------------- pair orientation, SELF, failures

#: How the benchmark's existing pair order maps onto an asymmetric API. Innovatrics
#: states its fingerprint matching is not commutative and that reversing probe and
#: gallery can change the score, so there is nothing to normalise and no symmetry
#: to hope for. This is a deterministic binding of a fact the protocol already
#: holds — which side of the pair is left — onto the roles the API defines. It is
#: not a parameter and it was not chosen by trying both (docs/adr/0109).
PAIR_ROLE_BINDING: tuple[tuple[str, str], ...] = (
    ("pair.left", "probe"),
    ("pair.right", "gallery"),
)

#: What the qualification has to do about orientation: run both, publish that
#: they can differ, and change nothing on the strength of it.
PAIR_ORIENTATION_REQUIREMENTS: tuple[str, ...] = (
    "score(A, B) is produced under the frozen binding",
    "score(B, A) is produced as a separate comparison",
    "whether the two agree is published as a finding",
    "the frozen binding is applied to every pair regardless of the finding",
)

#: Ways of collapsing the two orientations into one number. Each would hide an
#: asymmetry the vendor has documented, and the maximum is the worst of them: it
#: is a per-pair choice made on the strength of the scores themselves.
REFUSED_ORIENTATION_REDUCTIONS: tuple[str, ...] = (
    "max",
    "min",
    "average",
    "sorting the two paths",
    "choosing whichever orientation scores higher",
)

#: How SELF is built. Two loads, two extractions, two representations. An engine
#: that noticed both sides were the same object could return a constant, and that
#: constant would be a fact about this project's plumbing.
SELF_SEMANTICS_REQUIREMENTS: tuple[str, ...] = (
    "image A is loaded and extracted to a probe representation",
    "image A is loaded and extracted again to a separate gallery representation",
    "the two representations are compared",
    "no representation is reused, cached or shared between the two sides",
)

#: Where the same score has to appear again. Anything less is
#: ``SCORE_NONDETERMINISM_OBSERVED``, and a seed is not forced unless upstream
#: documents a deterministic mode of its own.
DETERMINISM_LEVELS: tuple[str, ...] = (
    "repeat_in_the_same_process",
    "fresh_objects_in_the_same_process",
    "fresh_process",
)

#: What the qualification tries, safely, to find out how the route fails. Each is
#: a cause paired with what it is trying to establish.
FAILURE_SEMANTICS_CAUSES: tuple[tuple[str, str], ...] = (
    (
        "malformed_or_invalid_image",
        "a structurally broken image is refused rather than scored",
    ),
    (
        "valid_but_unextractable_fingerprint",
        "an image the extractor declines produces a status, not a number",
    ),
    ("missing_or_invalid_input", "an absent input is refused before any scoring"),
    (
        "license_unavailable",
        "the licence refusal is reported as itself, where this can be provoked "
        "safely",
    ),
    (
        "matcher_or_api_misuse",
        "a controlled synthetic misuse returns a structured error",
    ),
)

#: The rule every one of those has to satisfy. A failure that arrived as a score
#: of zero would enter the benchmark as a very poor match, and no downstream
#: metric could tell it apart from one. Zero is allowed as a *score*, wherever
#: the matcher legitimately returns it.
FAILURE_SEMANTICS_RULE = (
    "a failure is a structured failure, exception or status, and never a "
    "pseudo-score; a score of 0 is a legitimate score wherever the matcher "
    "returns one"
)


# ------------------------------------------------------------ the qualification

#: The passes a qualification record must carry to answer the gates. Named here
#: rather than in the harness, so a record missing one is detectable by a reader
#: who never ran it.
QUALIFICATION_PASSES: tuple[tuple[str, str], ...] = (
    ("ordinary", "score(A, B) under the frozen role binding"),
    ("repeat_same_process", "score(A, B) again, same process, same objects"),
    (
        "fresh_objects_same_process",
        "score(A, B) again, same process, newly constructed objects",
    ),
    ("fresh_process", "score(A, B) again, in a separate process"),
    ("reversed", "score(B, A), to observe the documented asymmetry"),
    ("self", "SELF(A, A) from two independent extractions"),
)

#: The ceiling on score-producing comparisons in a qualification. Small on
#: purpose: this is a route check, not a measurement, and a licence clock is
#: running once the trial is activated.
QUALIFICATION_MAX_SCORING_COMPARISONS = 20

#: What a qualification may score. Nothing else, and never SD300.
QUALIFICATION_FIXTURE_SOURCES: tuple[str, ...] = (
    "official vendor fingerprint samples shipped inside the delivered package",
    "local non-SD300 fixtures generated by this project",
)


class QualificationOutcome(str, Enum):
    """Whether the bounded run finished, and the record it leaves either way.

    A failed attempt is kept. Stage 11A learned this the expensive way: a run
    that started, loaded the runtime and then broke is evidence about the route,
    and discarding it and reporting "not run yet" would turn a finding into a
    chore.
    """

    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


#: Where the local record lives, and what schema it carries. The record stays in
#: the artifact store beside the package: it names local paths and a machine, and
#: the published document is derived from it rather than being it.
QUALIFICATION_RECORD_NAME = "qualification-attempt.json"
QUALIFICATION_RECORD_SCHEMA = "stage_12a_qualification_v1"


# ---------------------------------------------------------------- the workload

#: The benchmark this candidate would have to survive, stated as three separate
#: numbers because they are three separate demands on a licence.
FROZEN_COMPARISON_ATTEMPTS = 6_000
FROZEN_INDEPENDENT_EXTRACTIONS = 12_000
FROZEN_MATCHER_INVOCATIONS = 6_000

#: Whether a representation may be computed once and reused across comparisons.
#: It may not — which is why the extraction count is twice the comparison count
#: and not a fraction of it (docs/adr/0070).
REPRESENTATION_CACHE_PERMITTED = False


@dataclass(frozen=True, slots=True)
class FrozenWorkload:
    """The demand a licence would have to cover, with the qualification allowance.

    Kept as a small object rather than four loose integers so that the arithmetic
    a capacity check performs is the arithmetic this table states.
    """

    comparison_attempts: int
    independent_extractions: int
    matcher_invocations: int
    qualification_allowance: int

    def __post_init__(self) -> None:
        for name in (
            "comparison_attempts",
            "independent_extractions",
            "matcher_invocations",
            "qualification_allowance",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or value <= 0:
                raise IdkitCandidateIdentityError(f"{name} must be a positive integer")
        if self.independent_extractions != 2 * self.comparison_attempts:
            raise IdkitCandidateIdentityError(
                "every comparison extracts both sides independently, so the "
                "extraction count is twice the comparison count; a smaller "
                "number would be a representation cache nobody declared"
            )
        if self.matcher_invocations != self.comparison_attempts:
            raise IdkitCandidateIdentityError(
                "one matcher invocation per comparison attempt"
            )

    @property
    def total_extractions(self) -> int:
        """Including the qualification's own, each of which also extracts twice."""
        return self.independent_extractions + 2 * self.qualification_allowance

    @property
    def total_matcher_invocations(self) -> int:
        return self.matcher_invocations + self.qualification_allowance


FROZEN_WORKLOAD = FrozenWorkload(
    comparison_attempts=FROZEN_COMPARISON_ATTEMPTS,
    independent_extractions=FROZEN_INDEPENDENT_EXTRACTIONS,
    matcher_invocations=FROZEN_MATCHER_INVOCATIONS,
    qualification_allowance=QUALIFICATION_MAX_SCORING_COMPARISONS,
)

#: What has to be read off the licence that was actually issued. Not assumed
#: absent because no public page mentioned one: a quota nobody looked for is the
#: quota that stops the run at comparison four thousand (docs/adr/0096 applies
#: unchanged).
LICENSE_CAPACITY_QUESTIONS: tuple[str, ...] = (
    "expiry",
    "machine_binding",
    "feature_entitlement",
    "process_restrictions",
    "quota_or_transaction_limits",
    "offline_or_network_requirement",
)

#: What the qualification measures about runtime cost. The question is whether
#: 6,000 jobs fit inside the licence's life, not how this candidate compares with
#: Algorithm 4 — a comparison on twenty comparisons would be meaningless anyway.
RUNTIME_FEASIBILITY_MEASUREMENTS: tuple[str, ...] = (
    "startup",
    "end_to_end_extraction_and_verification",
    "approximate_memory",
    "cpu_requirements",
)


# --------------------------------------------------------- training provenance


class TrainingProvenanceStatus(str, Enum):
    """What is known about what the algorithm was trained on."""

    PROPRIETARY_UNDISCLOSED = "PROPRIETARY_UNDISCLOSED"
    DISCLOSED = "DISCLOSED"
    VENDOR_STATEMENT_OBTAINED = "VENDOR_STATEMENT_OBTAINED"
    NOT_REACHED = "NOT_REACHED"


class SD300OverlapStatus(str, Enum):
    """Whether this candidate was built on the benchmark's own evaluation data.

    ``NO_EVIDENCE_FOUND`` is the honest positive answer and the one the policy
    accepts: a search was made and nothing turned up. It is not the same as
    ``NOT_REACHED``, which says nobody looked because the run had stopped, and it
    is not the same as a vendor letter — which would be stronger and is not a
    prerequisite, because it was not one for Algorithm 4 either.
    """

    NO_EVIDENCE_FOUND = "NO_EVIDENCE_FOUND"
    OVERLAP_FOUND = "OVERLAP_FOUND"
    VENDOR_DENIAL_OBTAINED = "VENDOR_DENIAL_OBTAINED"
    NOT_REACHED = "NOT_REACHED"


#: Every use of SD300 that would disqualify the candidate. Training is the
#: obvious one; the other four are the ones a vendor would not usually call
#: training and which leak the evaluation set into the model just as effectively.
SD300_OVERLAP_SURFACES: tuple[str, ...] = (
    "training",
    "validation",
    "model selection",
    "calibration",
    "development testing that affected the released model",
)


class FailureClass(str, Enum):
    """What kind of failure a ``FAIL`` outcome is.

    ``IDKIT_PREFLIGHT_FAIL`` reads the same whether the vendor refused the
    package or the delivered API turned out to have no per-pair score, and those
    are very different results for anybody deciding what to do next.
    """

    VENDOR_ACCESS_REFUSED = "VENDOR_ACCESS_REFUSED"
    PACKAGE_UNAVAILABLE_FOR_TARGET = "PACKAGE_UNAVAILABLE_FOR_TARGET"
    RESEARCH_USE_BLOCKED = "RESEARCH_USE_BLOCKED"
    LICENSE_INSUFFICIENT = "LICENSE_INSUFFICIENT"
    ROUTE_NOT_QUALIFIABLE = "ROUTE_NOT_QUALIFIABLE"
    TRAINING_OVERLAP = "TRAINING_OVERLAP"


# ------------------------------------------------------------- what is refused

#: What Stage 12A must not read, in either direction. The dataset, because a
#: candidate qualified on the evaluation set is a candidate qualified on the
#: answer sheet; the other algorithms' scores, because there is no reason for a
#: candidate's preflight to know how its predecessors did.
FORBIDDEN_READS: tuple[str, ...] = (
    "sd300_image_bytes",
    "sd300_pair_manifest",
    "sd300_scores",
    "sourceafis_scores",
    "nbis_scores",
    "flx_scores",
    "verifinger_scores",
)

#: What this stage is not. Each of these is Stage 12B's, and building one here
#: would mean building it before knowing whether there is a route to build it on.
NON_GOALS: tuple[str, ...] = (
    "a generic FingerprintAlgorithmAdapter",
    "a canonical experiment configuration",
    "the 6,000-comparison runner",
    "a ResultSet",
    "a threshold",
    "a calibration",
    "a metric",
    "a ranking against Algorithm 4",
)

#: Restated as denials for the marker, so that "no production adapter exists" is
#: a checked claim rather than an intention.
PRODUCTION_INTEGRATION_NOT_CREATED: tuple[str, ...] = (
    "production_adapter_created",
    "canonical_experiment_config_created",
    "benchmark_run_performed",
    "result_set_produced",
    "threshold_produced",
    "calibration_performed",
    "metrics_produced",
)

#: What this stage may build. The list is short and every item is disposable: if
#: the candidate fails, none of it becomes part of the benchmark.
PERMITTED_CONSTRUCTIONS: tuple[str, ...] = (
    "a small qualification harness",
    "a vendor API probe",
    "package inspection",
    "a fake SDK for the harness's own contract",
    "schemas",
    "a local smoke on non-SD300 fixtures",
)

#: The conjunction that admits the candidate. Every one must hold, and the
#: marker's ``PASS`` validation checks them one by one. There is no weighting and
#: no score at which enough of them is enough.
ACCEPTANCE_CONDITIONS: tuple[str, ...] = (
    "an official package was actually obtained",
    "the exact package, build and version are pinned",
    "one official binding was selected",
    "the runtime dependency closure is known",
    "Stage 8E permits local research use",
    "the licence activates legitimately",
    "the licence covers the frozen workload",
    "the canonical_500 route is resolved",
    "no pixel preprocessing was invented by fpbench",
    "500 DPI semantics are frozen before extraction",
    "the single-fingerprint extraction route is resolved",
    "the proprietary IDKit representation is resolved",
    "no multi-finger consolidation is involved",
    "every extraction setting is frozen",
    "the exact 1:1 matcher route is resolved",
    "a raw scalar score is accessible independently of the decision",
    "every matcher setting is frozen",
    "fpbench applies no score transformation",
    "pair.left to probe and pair.right to gallery are frozen",
    "SELF was demonstrated from two independent extractions",
    "repeat and restart determinism passed",
    "failure semantics passed",
    "a local non-SD300 smoke passed",
    "training provenance is recorded",
    "no positive SD300 overlap evidence was found",
    "no SD300 byte, manifest or score was consulted",
    "no prior algorithm's scores were consulted",
)


# --------------------------------------------------------------- the guards

#: Keys that name licence material or a credential. Refused at any depth of any
#: published document, whatever the surrounding prose was trying to say.
SENSITIVE_EVIDENCE_KEYS: frozenset[str] = frozenset(
    {
        "password",
        "passphrase",
        "secret",
        "license_bytes",
        "licence_bytes",
        "license_file_bytes",
        "license_buffer",
        "license_key",
        "licence_key",
        "license_id",
        "activation_key",
        "activationkey",
        "serial",
        "serial_number",
        "serialnumber",
        "hardware_id",
        "hardwareid",
        "hw_id",
        "hwid",
        "machine_id",
        "machineid",
        "device_id",
        "deviceid",
        "computer_id",
        "customer_id",
        "customer_login",
        "portal_username",
        "portal_password",
        "account_id",
        "signed_url",
        "presigned_url",
        "download_token",
        "access_token",
        "refresh_token",
        "bearer_token",
        "session_cookie",
        "cookie",
        "cookies",
        "authorization",
        "api_key",
        "credentials",
        "vendor_correspondence",
        "email_body",
        "contact_email",
    }
)

#: Value shapes that look like a credential or a machine wherever they appear.
#: Written as regular-expression *sources* rather than compiled patterns so this
#: module stays a table of constants and the engine owns the compilation.
#:
#: The two path patterns are here because Stage 12A publishes runtime paths, and
#: a runtime path that starts at a home directory names a person.
SENSITIVE_VALUE_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        "uuid_shape",
        r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{12}\b",
    ),
    (
        # Upper case and digits only, deliberately. A case-insensitive version
        # matched hyphenated lower-case slugs in the support-article locators
        # this stage publishes, and a guard that refuses a URL is a guard
        # somebody switches off.
        "grouped_serial_shape",
        r"\b[A-Z0-9]{4,6}-[A-Z0-9]{4,6}-[A-Z0-9]{4,6}-[A-Z0-9]{4,6}\b",
    ),
    ("bearer_token_shape", r"\bBearer\s+[A-Za-z0-9._\-]{16,}\b"),
    ("private_key_block", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ("basic_auth_in_locator", r"://[^/\s:@]+:[^/\s@]+@"),
    (
        "signed_url_query",
        r"[?&](X-Amz-Signature|Signature|Expires|token|access_key)=",
    ),
    ("long_base64_blob", r"\b[A-Za-z0-9+/]{120,}={0,2}\b"),
    ("windows_user_path", r"[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s\"']+"),
    ("posix_home_path", r"(?<![\w./])/home/[^\s/\"']+"),
)

#: Refused at any depth of a published Stage 12A document, in addition to the
#: sensitive keys above. Each would mean an upstream byte, a template, an image,
#: a score or a machine-specific path had reached the evidence of a stage whose
#: whole subject is that none of them does.
#:
#: As in every stage since 8E, no member may be a value of a published
#: vocabulary: these documents count things into maps keyed by enum value, and a
#: forbidden key named ``score`` must not refuse a map entry that counts scores.
FORBIDDEN_PUBLISHED_KEYS: frozenset[str] = frozenset(
    {
        "license_text",
        "license_body",
        "eula_text",
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
        "template_buffer",
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
        "matching_score",
        "consolidated_score",
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


# ------------------------------------------------------------ the closed stages
#
# Stage 12A reads two published markers and edits neither. Stage 11B is its
# predecessor and stays immutable; Stage 8E owns third-party policy and Stage 12A
# adds no licensing subsystem of its own.

#: Stage 11B as published: 6,000 canonical raw VeriFinger outcomes, and the
#: marker that opened a search for Algorithm 5. Binding the fingerprint rather
#: than the directory is what makes "Stage 11B was not edited" checkable instead
#: of asserted.
STAGE_11B_FINALIZATION_FINGERPRINT = (
    "3d271490edda9e3e9d066485c2d93e82e2eceb4556668df7d65a8207e591684c"
)
STAGE_11B_OUTCOME = "VERIFINGER_CANONICAL500_RAW_COMPLETE"

#: Assembled from parts rather than written out, for the reason every stage since
#: 8C assembles its predecessor's path: this module's source is audited for
#: literals that name another stage's published evidence, and a written-out path
#: here would make the audit refuse the module that performs it.
STAGE_11B_EVIDENCE_DIRECTORY = "/".join(
    ("evidence", "stage11b-" + "verifinger-canonical500-raw")
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

#: Where the store keeps Stage 12A's package, relative to the third-party root.
#: Outside the repository, always.
ARTIFACT_STORE_PREFIX = "innovatrics-idkit"

#: The bytes that decide this preflight. The marker fingerprints them, so a
#: change to any one of them after publication is detectable.
STAGE_12A_SOURCE_FILES: tuple[str, ...] = (
    "src/fpbench/core/idkit_preflight_errors.py",
    "src/fpbench/experiments/stage12a_idkit_identity.py",
    "src/fpbench/experiments/stage12a_idkit_observations.py",
    "src/fpbench/experiments/stage12a_acquisition.py",
    "src/fpbench/experiments/stage12a_qualification.py",
    "src/fpbench/experiments/stage12a_preflight.py",
    "src/fpbench/experiments/stage12a_finalization.py",
)


def all_frozen_identifiers() -> tuple[str, ...]:
    """Every identifier-shaped constant this module froze, for the contract suite."""
    return (
        CANDIDATE_ID,
        ALGORITHM_SLOT,
        *(gate.value for gate in GATE_ORDER),
        *(status.value for status in GateStatus),
        *(code.value for code in BlockerCode),
        *(status.value for status in AcquisitionStatus),
        *(channel.value for channel in DeliveryChannel),
        *(family.value for family in ProductFamily),
        *(item.value for item in SettingProvenance),
        *(item.value for item in RepresentationType),
        *(item.value for item in ScoreRouteStatus),
        *(item.value for item in TrainingProvenanceStatus),
        *(item.value for item in SD300OverlapStatus),
        *(item.value for item in FailureClass),
        *(item.value for item in QualificationOutcome),
        *STAGE_12A_OUTCOMES,
    )


# ------------------------------------------------------- checked at import time
#
# Each of these is a mistake that would otherwise be found by a reader of the
# published evidence rather than by the module that produced it.


def _require_gate_documents_are_complete() -> None:
    covered = tuple(gate for gate, _ in GATE_DOCUMENTS)
    if covered != GATE_ORDER:
        raise IdkitCandidateIdentityError(
            "every gate declares which documents it reports through, in the "
            f"frozen order; {covered} is not {GATE_ORDER}"
        )
    published: list[str] = []
    for _, names in GATE_DOCUMENTS:
        published.extend(names)
    duplicated = sorted({name for name in published if published.count(name) > 1})
    if duplicated:
        raise IdkitCandidateIdentityError(
            f"two gates would report through the same document {duplicated}, "
            "which would give one document two authorities"
        )
    unknown = sorted(set(published) - set(REQUIRED_EVIDENCE_FILES))
    if unknown:
        raise IdkitCandidateIdentityError(
            f"a gate reports through a document nothing publishes: {unknown}"
        )


def _require_every_blocker_belongs_to_one_gate() -> None:
    covered = tuple(gate for gate, _ in GATE_BLOCKERS)
    if covered != GATE_ORDER:
        raise IdkitCandidateIdentityError(
            "every gate declares its blockers, in the frozen order"
        )
    for code in BlockerCode:
        owners = gate_of_blocker(code)
        if len(owners) != 1:
            raise IdkitCandidateIdentityError(
                f"{code.value} belongs to {[item.value for item in owners]}; a "
                "blocker raised at two gates would put the reason in two places"
            )


def _require_acquisition_states_are_partitioned() -> None:
    pending = set(ACQUISITION_PENDING_STATES)
    refusal = set(ACQUISITION_REFUSAL_STATES)
    overlap = pending & refusal
    if overlap:
        raise IdkitCandidateIdentityError(
            f"{sorted(item.value for item in overlap)} is both a pending state "
            "and a refusal, and the difference between the two is the point"
        )
    accounted = pending | refusal | {AcquisitionStatus.PACKAGE_OBTAINED}
    missing = sorted(item.value for item in set(AcquisitionStatus) - accounted)
    if missing:
        raise IdkitCandidateIdentityError(
            f"{missing} is neither pending, a refusal, nor possession; an "
            "unclassified state would reach the outcome as a guess"
        )


def _require_refused_provenance_is_not_a_member() -> None:
    if REFUSED_SETTING_PROVENANCE in {item.value for item in SettingProvenance}:
        raise IdkitCandidateIdentityError(
            "the refused provenance is not a member of the vocabulary; making it "
            "one would make it selectable"
        )


def _require_evidence_paths_are_plain() -> None:
    for name in REQUIRED_EVIDENCE_FILES:
        pure = PurePosixPath(name)
        if len(pure.parts) != 1 or name != pure.name:
            raise IdkitCandidateIdentityError(
                f"published evidence is flat and {name!r} is not a plain filename"
            )
    if len(set(REQUIRED_EVIDENCE_FILES)) != len(REQUIRED_EVIDENCE_FILES):
        raise IdkitCandidateIdentityError("a document is published twice")


def _require_forbidden_keys_are_not_vocabulary() -> None:
    vocabulary = {value.lower() for value in all_frozen_identifiers()}
    collision = sorted(FORBIDDEN_PUBLISHED_KEYS & vocabulary)
    if collision:
        raise IdkitCandidateIdentityError(
            f"{collision} is both a forbidden key and a published vocabulary "
            "value, so the guard would refuse a document for counting things"
        )


def _require_source_files_include_this_module() -> None:
    this = "src/fpbench/experiments/stage12a_idkit_identity.py"
    if this not in STAGE_12A_SOURCE_FILES:
        raise IdkitCandidateIdentityError(
            "the source fingerprint must cover the module that froze the "
            "vocabulary, or the vocabulary could change without the marker moving"
        )


_require_gate_documents_are_complete()
_require_every_blocker_belongs_to_one_gate()
_require_acquisition_states_are_partitioned()
_require_refused_provenance_is_not_a_member()
_require_evidence_paths_are_plain()
_require_forbidden_keys_are_not_vocabulary()
_require_source_files_include_this_module()
