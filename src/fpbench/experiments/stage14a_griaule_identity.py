"""What Stage 14A is, frozen: one candidate, four gates, five states, four outcomes.

This is deliberately the smallest stage since Stage 8A, and the smallness is the
design rather than a shortcut. Stage 12A and Stage 13A each defined ten gates and
published thirteen documents, and both of them ended at the first one: Innovatrics
refused an evaluation licence, and the FingerCell trial entitlement never
arrived. Two full preflight harnesses were built for candidates that could not be
executed at all.

So Stage 14A asks one question before it builds anything: *can an official,
current Griaule GBS Fingerprint SDK package be obtained with the trial that is
distributed with it, and does that package define a complete authoritative route
from* ``canonical_500`` *to a native 1:1 similarity score?* Four gates, eight
small documents, no bridge, no adapter, no runtime experiment and no execution
(docs/adr/0123).

The gate order is the whole argument. G1 is acquisition, because every question
after it is a question about delivered bytes. G2 asks whether the image can enter
the extractor unmodified, because a route that needs fpbench to crop is not this
algorithm's route. G3 asks whether a scalar similarity score is reachable without
a decision, because a route with no raw score is not worth measuring. G4 asks
whether anything outside the frozen route can still move the score.

Nothing here downloads anything, activates anything, loads a library, reads
SD300, reads a prior algorithm's score, or produces a number.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from fpbench.core.griaule_preflight_errors import GriauleCandidateIdentityError
from fpbench.core.identifiers import validate_id

__all__ = [
    "STAGE_14A_SCHEMA_VERSION",
    "STAGE_FINALIZATION_KIND",
    "ALGORITHM_SLOT",
    "STAGE_14A_PASS_OUTCOME",
    "STAGE_14A_FAIL_OUTCOME",
    "STAGE_14A_PENDING_OUTCOME",
    "STAGE_14A_INCOMPLETE_OUTCOME",
    "STAGE_14A_OUTCOMES",
    "STAGE_14A_FINAL_OUTCOMES",
    "CANDIDATE_ID",
    "IMPLEMENTATION_ORIGIN",
    "PRODUCT_FAMILY",
    "IMPLEMENTATION_VERSION_SENTINEL",
    "PRODUCTION_ALGORITHM_ID_FROZEN",
    "PACKAGE_IDENTITY_FIELDS",
    "VERSION_IS_NOT_TAKEN_FROM_THE_WEBSITE",
    "EVIDENCE_DIRECTORY",
    "README_NAME",
    "PREDECESSOR_BINDING_NAME",
    "ACQUISITION_STATUS_NAME",
    "PACKAGE_MANIFEST_NAME",
    "RESEARCH_USE_TRIAL_NAME",
    "INPUT_ROUTE_NAME",
    "SCORE_CONTRACT_NAME",
    "ROUTE_CLOSURE_NAME",
    "PREFLIGHT_REPORT_NAME",
    "STAGE_14A_FINALIZATION_NAME",
    "REQUIRED_EVIDENCE_FILES",
    "DERIVABLE_EVIDENCE_FILES",
    "PreflightGate",
    "GATE_ORDER",
    "GATE_COUNT",
    "GateStatus",
    "GATE_DOCUMENTS",
    "gate_documents",
    "BlockerCode",
    "GATE_BLOCKERS",
    "gate_of_blocker",
    "PendingKind",
    "RequiredAction",
    "GATE_ACTIONS",
    "gate_of_action",
    "FailureClass",
    "LocatorCategory",
    "OFFICIAL_DELIVERY_CHANNELS",
    "REFUSED_ACQUISITION_SOURCES",
    "ACQUISITION_PASS_CONDITIONS",
    "BENCHMARK_INPUT_PROFILE",
    "BENCHMARK_INPUT_PPI",
    "BENCHMARK_INPUT_PIXEL_FORMAT",
    "REQUIRED_INPUT_PPI",
    "IDEAL_INPUT_ROUTE",
    "PERMITTED_DECODE_ROUTE",
    "DECODE_EQUIVALENCE_REQUIREMENTS",
    "REFUSED_PREPROCESSING",
    "VENDOR_INTERNAL_CROP_IS_ALGORITHM_BEHAVIOUR",
    "UPSTREAM_EXTRACTION_PIXEL_LIMIT",
    "UPSTREAM_CAPTURE_PIXEL_LIMIT",
    "SCORE_DIRECTION_EXPECTED_UPSTREAM",
    "SCORE_CONTRACT_QUESTIONS",
    "SCORE_SHAPE_IS_NOT_ASSUMED",
    "THRESHOLD_IS_NOT_A_DECISION_HERE",
    "UPSTREAM_DEFAULT_THRESHOLD_INDICATION",
    "UPSTREAM_DEFAULT_ROTATION_TOLERANCE_INDICATION",
    "FPBENCH_SCORE_TRANSFORMATION",
    "CALIBRATION_PERFORMED",
    "THRESHOLD_PRODUCED",
    "PAIR_ROLE_BINDING",
    "SETTING_INVENTORY_FIELDS",
    "SETTINGS_TO_ACCOUNT_FOR",
    "SettingProvenance",
    "DEFAULT_FPBENCH_CHANGED",
    "NO_SETTING_IS_CHOSEN_BY_TRYING_VALUES",
    "STAGE_14A_DOES_NOT",
    "SENSITIVE_EVIDENCE_KEYS",
    "SENSITIVE_VALUE_PATTERNS",
    "FORBIDDEN_PUBLISHED_KEYS",
    "STAGE_13A_OUTCOME",
    "STAGE_13A_FAILURE_CLASS",
    "STAGE_13A_FINALIZATION_FINGERPRINT",
    "STAGE_13A_EVIDENCE_DIRECTORY",
    "STAGE_11B_OUTCOME",
    "STAGE_11B_FINALIZATION_FINGERPRINT",
    "STAGE8E_OUTCOME",
    "STAGE8E_FINALIZATION_FINGERPRINT",
    "STAGE8E_PURPOSE_FINGERPRINT",
    "STAGE8E_POLICY_FINGERPRINT",
    "ARTIFACT_STORE_PREFIX",
    "STAGE_14A_SOURCE_FILES",
    "all_frozen_identifiers",
]

STAGE_14A_SCHEMA_VERSION = "1"
STAGE_FINALIZATION_KIND = "stage_14a_finalization"

#: The slot this candidate would occupy. Algorithm 4 is VeriFinger 2025.2, taken
#: by Stage 11A and filled with 6,000 canonical raw outcomes by Stage 11B. Stage
#: 12A and Stage 13A each opened this slot and failed to fill it; this is the
#: third attempt at it.
ALGORITHM_SLOT = "algorithm_5"


# ---------------------------------------------------------------- the outcomes

#: The artifact and its route qualified. All four gates passed against a
#: delivered package, and Stage 14B may proceed to a bounded runtime
#: qualification and then straight to the production adapter.
STAGE_14A_PASS_OUTCOME = "GRIAULE_ARTIFACT_ROUTE_PREFLIGHT_PASS"

#: An authoritative attempt or inspection disproved viability. Something was
#: tried, or something delivered was read, and it settles that this candidate
#: cannot carry Algorithm 5 on the terms this benchmark requires.
STAGE_14A_FAIL_OUTCOME = "GRIAULE_ARTIFACT_ROUTE_PREFLIGHT_FAIL"

#: An official route was walked and somebody outside this project has to move
#: next. Nothing whatever follows about the candidate. No marker is written
#: (docs/adr/0121).
STAGE_14A_PENDING_OUTCOME = "GRIAULE_PREFLIGHT_PENDING_ACCESS"

#: A step this project can take for itself has not been taken yet. Also not a
#: statement about the candidate, and also no marker (docs/adr/0121).
STAGE_14A_INCOMPLETE_OUTCOME = "GRIAULE_PREFLIGHT_INCOMPLETE"

STAGE_14A_OUTCOMES: tuple[str, ...] = (
    STAGE_14A_PASS_OUTCOME,
    STAGE_14A_FAIL_OUTCOME,
    STAGE_14A_PENDING_OUTCOME,
    STAGE_14A_INCOMPLETE_OUTCOME,
)

#: The two outcomes a marker may carry. Both non-final outcomes are deliberately
#: absent: a marker is a finalization, and neither "somebody else has to answer"
#: nor "we have not finished" is final.
STAGE_14A_FINAL_OUTCOMES: tuple[str, ...] = (
    STAGE_14A_PASS_OUTCOME,
    STAGE_14A_FAIL_OUTCOME,
)


# --------------------------------------------------------------- the candidate

CANDIDATE_ID = validate_id("griaule_gbs_fingerprint_sdk_1to1")

#: Where the implementation must come from. The same value Stage 11A, Stage 12A
#: and Stage 13A used, carrying the same obligation: the vendor's own channel,
#: never a mirror, a catalogue site or a reseller.
IMPLEMENTATION_ORIGIN = "VENDOR_OFFICIAL_SDK"

#: The product family, fixed upstream because Griaule publishes it under this
#: name. The version is not fixed here and cannot be.
PRODUCT_FAMILY = "GBS Fingerprint SDK"

#: What the implementation version is until a package exists. Griaule's public
#: documentation names three builds — x86-64, x86 and Linux — and no version
#: number, no build number and no release date for any of them. A version frozen
#: from that page would pin a string rather than an artifact, and the whole point
#: of this stage is that only the delivered bytes settle identity
#: (docs/adr/0110).
IMPLEMENTATION_VERSION_SENTINEL = "UNRESOLVED_UNTIL_PACKAGE"

#: Whether a production algorithm id may be minted from this stage. It may not.
PRODUCTION_ALGORITHM_ID_FROZEN = False

#: What a delivered package has to settle before anything downstream is decided.
#: Every one is a property of bytes this project holds and hashed itself.
PACKAGE_IDENTITY_FIELDS: tuple[str, ...] = (
    "product_version",
    "build_or_revision",
    "platform",
    "binding",
    "package_sha256",
)

#: The rule the field above exists to enforce, stated so a test can assert it.
VERSION_IS_NOT_TAKEN_FROM_THE_WEBSITE = True


# ------------------------------------------------------------------- evidence

#: Assembled from parts for the reason every stage since 8C assembles its own
#: name: this module's source is audited for literals that name published
#: evidence, and the audit has to be able to tell "my own directory" from
#: "somebody else's".
EVIDENCE_DIRECTORY = Path("evidence") / ("stage14a-" + "griaule-preflight")

README_NAME = "README.md"
PREDECESSOR_BINDING_NAME = "predecessor-binding.json"
ACQUISITION_STATUS_NAME = "acquisition-status.json"
PACKAGE_MANIFEST_NAME = "package-manifest.json"
RESEARCH_USE_TRIAL_NAME = "research-use-trial.json"
INPUT_ROUTE_NAME = "input-route.json"
SCORE_CONTRACT_NAME = "score-contract.json"
ROUTE_CLOSURE_NAME = "route-closure.json"
PREFLIGHT_REPORT_NAME = "preflight-report.json"
STAGE_14A_FINALIZATION_NAME = "stage-14a-finalization.json"

#: Eight documents, a README and a marker that exists only under a final
#: outcome. Stage 13A published thirteen documents for a candidate that never ran
#: a single comparison; this stage publishes what its four questions need and
#: nothing else.
REQUIRED_EVIDENCE_FILES: tuple[str, ...] = (
    README_NAME,
    PREDECESSOR_BINDING_NAME,
    ACQUISITION_STATUS_NAME,
    PACKAGE_MANIFEST_NAME,
    RESEARCH_USE_TRIAL_NAME,
    INPUT_ROUTE_NAME,
    SCORE_CONTRACT_NAME,
    ROUTE_CLOSURE_NAME,
    PREFLIGHT_REPORT_NAME,
    STAGE_14A_FINALIZATION_NAME,
)

#: What the engine derives. The README is written by hand and the marker is
#: derived against the committed bytes of everything else, so neither is here.
DERIVABLE_EVIDENCE_FILES: tuple[str, ...] = tuple(
    name
    for name in REQUIRED_EVIDENCE_FILES
    if name not in (README_NAME, STAGE_14A_FINALIZATION_NAME)
)


# -------------------------------------------------------------- the four gates


class PreflightGate(str, Enum):
    """Exactly four gates. Not three, and not five.

    Every one of them is a question about a *delivered package*, which is why G1
    comes first and why nothing after it can be answered while G1 is open. A
    documentation page can shape all four questions and settle none of them.
    """

    OFFICIAL_ARTIFACT_AND_TRIAL_ACCESS = "OFFICIAL_ARTIFACT_AND_TRIAL_ACCESS"
    DIRECT_CANONICAL500_INPUT_ROUTE = "DIRECT_CANONICAL500_INPUT_ROUTE"
    SINGLE_FINGER_RAW_1TO1_SCORE_ROUTE = "SINGLE_FINGER_RAW_1TO1_SCORE_ROUTE"
    SCORE_AFFECTING_ROUTE_CLOSURE = "SCORE_AFFECTING_ROUTE_CLOSURE"


GATE_ORDER: tuple[PreflightGate, ...] = (
    PreflightGate.OFFICIAL_ARTIFACT_AND_TRIAL_ACCESS,
    PreflightGate.DIRECT_CANONICAL500_INPUT_ROUTE,
    PreflightGate.SINGLE_FINGER_RAW_1TO1_SCORE_ROUTE,
    PreflightGate.SCORE_AFFECTING_ROUTE_CLOSURE,
)

GATE_COUNT = len(GATE_ORDER)


class GateStatus(str, Enum):
    """What one gate concluded. Five states, and three of them are not verdicts.

    The vocabulary is the stage's central distinction, and it is wider than
    Stage 12A's and Stage 13A's because this stage can be stopped in two
    different ways that look identical from the outside:

    .. code-block:: text

        vendor or external dependency outstanding
            -> PENDING_ACCESS

        local action not yet performed
            -> ACTION_REQUIRED

        authoritative attempt or inspection disproved viability
            -> FAIL

    Only ``PASS`` and ``FAIL`` are final, and only those two produce a marker.
    ``PENDING_ACCESS`` says an official route was walked and somebody else has to
    move; ``ACTION_REQUIRED`` says this project has a step left to take. Neither
    says anything about the candidate, and collapsing either into ``FAIL`` would
    publish a verdict nobody reached (docs/adr/0121).

    ``NOT_REACHED`` is narrower than all of them: the run had already stopped, so
    this question was never asked at all.
    """

    PASS = "PASS"
    FAIL = "FAIL"
    PENDING_ACCESS = "PENDING_ACCESS"
    ACTION_REQUIRED = "ACTION_REQUIRED"
    NOT_REACHED = "NOT_REACHED"

    @property
    def is_final(self) -> bool:
        """Whether this status can appear in a finalized stage."""
        return self in (GateStatus.PASS, GateStatus.FAIL)

    @property
    def stops_the_run(self) -> bool:
        """Whether the gates after this one can still be asked.

        Every gate after G1 is a question about delivered bytes, so unlike Stage
        13A — where a training-provenance search needed no runtime and could be
        answered out of order — nothing here can be answered around a gate that
        did not pass. All four non-passing states therefore stop the run, and the
        difference between them is carried in the status rather than in the
        control flow.
        """
        return self is not GateStatus.PASS


#: The documents each gate reports through. G1 reports through three, because it
#: answers three separable questions — was an official package obtained, what
#: exactly is it, and what did its delivered terms and bundled trial permit — and
#: a reader checking the second should not have to read the other two. The
#: predecessor binding and the preflight report belong to no gate.
GATE_DOCUMENTS: tuple[tuple[PreflightGate, tuple[str, ...]], ...] = (
    (
        PreflightGate.OFFICIAL_ARTIFACT_AND_TRIAL_ACCESS,
        (ACQUISITION_STATUS_NAME, PACKAGE_MANIFEST_NAME, RESEARCH_USE_TRIAL_NAME),
    ),
    (PreflightGate.DIRECT_CANONICAL500_INPUT_ROUTE, (INPUT_ROUTE_NAME,)),
    (PreflightGate.SINGLE_FINGER_RAW_1TO1_SCORE_ROUTE, (SCORE_CONTRACT_NAME,)),
    (PreflightGate.SCORE_AFFECTING_ROUTE_CLOSURE, (ROUTE_CLOSURE_NAME,)),
)


def gate_documents(gate: PreflightGate) -> tuple[str, ...]:
    """The documents one gate reports through."""
    for item, names in GATE_DOCUMENTS:
        if item is gate:
            return names
    raise GriauleCandidateIdentityError(  # pragma: no cover - GATE_ORDER is total
        f"{gate!r} is not a Stage 14A gate"
    )


class BlockerCode(str, Enum):
    """Why Griaule cannot enter fpbench as Algorithm 5. A closed list.

    Every member names something that was *observed*: a refusal that arrived, a
    confirmation that no package is available for this use, or a delivered
    artifact that was read and found to require something this benchmark refuses.
    None of them can be raised because a step has not been taken yet or because a
    reply has not arrived — those are :class:`RequiredAction` and
    :class:`PendingKind`, and keeping the three vocabularies disjoint is what
    stops "nobody answered us" from being published as "it does not work"
    (docs/adr/0121).
    """

    # G1
    VENDOR_ACCESS_REFUSED = "VENDOR_ACCESS_REFUSED"
    OFFICIAL_PACKAGE_UNAVAILABLE = "OFFICIAL_PACKAGE_UNAVAILABLE"
    RESEARCH_USE_BLOCKED = "RESEARCH_USE_BLOCKED"
    BUNDLED_TRIAL_ROUTE_UNAVAILABLE = "BUNDLED_TRIAL_ROUTE_UNAVAILABLE"

    # G2
    FPBENCH_PREPROCESSING_REQUIRED = "FPBENCH_PREPROCESSING_REQUIRED"
    DIRECT_INPUT_ROUTE_UNRESOLVED = "DIRECT_INPUT_ROUTE_UNRESOLVED"

    # G3
    RAW_SCORE_ROUTE_UNAVAILABLE = "RAW_SCORE_ROUTE_UNAVAILABLE"
    RAW_SCORE_ROUTE_UNRESOLVED = "RAW_SCORE_ROUTE_UNRESOLVED"

    # G4
    SCORE_AFFECTING_CHOICE_UNRESOLVED = "SCORE_AFFECTING_CHOICE_UNRESOLVED"
    PACKAGE_ROUTE_IDENTITY_UNRESOLVED = "PACKAGE_ROUTE_IDENTITY_UNRESOLVED"


GATE_BLOCKERS: tuple[tuple[PreflightGate, tuple[BlockerCode, ...]], ...] = (
    (
        PreflightGate.OFFICIAL_ARTIFACT_AND_TRIAL_ACCESS,
        (
            BlockerCode.VENDOR_ACCESS_REFUSED,
            BlockerCode.OFFICIAL_PACKAGE_UNAVAILABLE,
            BlockerCode.RESEARCH_USE_BLOCKED,
            BlockerCode.BUNDLED_TRIAL_ROUTE_UNAVAILABLE,
        ),
    ),
    (
        PreflightGate.DIRECT_CANONICAL500_INPUT_ROUTE,
        (
            BlockerCode.FPBENCH_PREPROCESSING_REQUIRED,
            BlockerCode.DIRECT_INPUT_ROUTE_UNRESOLVED,
        ),
    ),
    (
        PreflightGate.SINGLE_FINGER_RAW_1TO1_SCORE_ROUTE,
        (
            BlockerCode.RAW_SCORE_ROUTE_UNAVAILABLE,
            BlockerCode.RAW_SCORE_ROUTE_UNRESOLVED,
        ),
    ),
    (
        PreflightGate.SCORE_AFFECTING_ROUTE_CLOSURE,
        (
            BlockerCode.SCORE_AFFECTING_CHOICE_UNRESOLVED,
            BlockerCode.PACKAGE_ROUTE_IDENTITY_UNRESOLVED,
        ),
    ),
)


def gate_of_blocker(code: BlockerCode) -> tuple[PreflightGate, ...]:
    """Which gate or gates may raise one blocker."""
    return tuple(gate for gate, codes in GATE_BLOCKERS if code in codes)


class PendingKind(str, Enum):
    """Why a gate is waiting on somebody outside this project.

    Available at G1 only. Every gate after it is answered by reading bytes this
    project holds, so a pending state there would be describing a wait that does
    not exist.
    """

    #: An official request has been sent and no reply has arrived.
    VENDOR_REQUEST_SENT_AWAITING_REPLY = "VENDOR_REQUEST_SENT_AWAITING_REPLY"

    #: The vendor replied, and the reply neither delivers a package nor refuses
    #: one: it asks for something, or routes the request onward.
    VENDOR_REPLY_REQUIRES_FURTHER_STEPS = "VENDOR_REPLY_REQUIRES_FURTHER_STEPS"


class RequiredAction(str, Enum):
    """A step this project can take for itself, and has not taken yet.

    Disjoint from :class:`BlockerCode` on purpose. An action says something about
    this project's progress and nothing whatever about Griaule (docs/adr/0121).
    """

    #: Every official route has been walked, none of them offers the package
    #: without asking, and the request itself has not been sent.
    SEND_ONE_OFFICIAL_ACQUISITION_REQUEST = "SEND_ONE_OFFICIAL_ACQUISITION_REQUEST"

    #: A package is in the store and has not been hashed and recorded.
    HASH_AND_DECLARE_THE_DELIVERED_PACKAGE = "HASH_AND_DECLARE_THE_DELIVERED_PACKAGE"

    #: A package is declared and its delivered documentation, headers and terms
    #: have not been read into an inspection record.
    INSPECT_THE_DELIVERED_PACKAGE = "INSPECT_THE_DELIVERED_PACKAGE"


GATE_ACTIONS: tuple[tuple[PreflightGate, tuple[RequiredAction, ...]], ...] = (
    (
        PreflightGate.OFFICIAL_ARTIFACT_AND_TRIAL_ACCESS,
        (
            RequiredAction.SEND_ONE_OFFICIAL_ACQUISITION_REQUEST,
            RequiredAction.HASH_AND_DECLARE_THE_DELIVERED_PACKAGE,
            RequiredAction.INSPECT_THE_DELIVERED_PACKAGE,
        ),
    ),
    (PreflightGate.DIRECT_CANONICAL500_INPUT_ROUTE, ()),
    (PreflightGate.SINGLE_FINGER_RAW_1TO1_SCORE_ROUTE, ()),
    (PreflightGate.SCORE_AFFECTING_ROUTE_CLOSURE, ()),
)


def gate_of_action(action: RequiredAction) -> tuple[PreflightGate, ...]:
    """Which gate or gates may report one outstanding action."""
    return tuple(gate for gate, actions in GATE_ACTIONS if action in actions)


class FailureClass(str, Enum):
    """What kind of failure a FAIL is. One per blocker, and no default.

    ``GRIAULE_ARTIFACT_ROUTE_PREFLIGHT_FAIL`` reads the same whether a vendor
    refused a package or a delivered header exposed a thresholded-only decision,
    and those are not the same finding.
    """

    VENDOR_ACCESS_REFUSED = "VENDOR_ACCESS_REFUSED"
    OFFICIAL_PACKAGE_UNAVAILABLE = "OFFICIAL_PACKAGE_UNAVAILABLE"
    RESEARCH_USE_BLOCKED = "RESEARCH_USE_BLOCKED"
    BUNDLED_TRIAL_ROUTE_UNAVAILABLE = "BUNDLED_TRIAL_ROUTE_UNAVAILABLE"
    FPBENCH_PREPROCESSING_REQUIRED = "FPBENCH_PREPROCESSING_REQUIRED"
    DIRECT_INPUT_ROUTE_UNRESOLVED = "DIRECT_INPUT_ROUTE_UNRESOLVED"
    RAW_SCORE_ROUTE_UNAVAILABLE = "RAW_SCORE_ROUTE_UNAVAILABLE"
    RAW_SCORE_ROUTE_UNRESOLVED = "RAW_SCORE_ROUTE_UNRESOLVED"
    SCORE_AFFECTING_CHOICE_UNRESOLVED = "SCORE_AFFECTING_CHOICE_UNRESOLVED"
    PACKAGE_ROUTE_IDENTITY_UNRESOLVED = "PACKAGE_ROUTE_IDENTITY_UNRESOLVED"


# ------------------------------------------------------------- G1: acquisition


class LocatorCategory(str, Enum):
    """Where a package came from. Only the first three are acceptable.

    The refused members exist so that a route somebody walked can be *recorded*
    as walked and refused, rather than quietly omitted. Stage 12A found IDKit
    packages on catalogue sites and at a reseller, and Griaule's situation is
    worse: the search results include a download host advertising a cracked
    build. Naming the category is how the evidence shows the route was seen and
    declined rather than missed.
    """

    VENDOR_SELF_SERVICE_DOWNLOAD = "VENDOR_SELF_SERVICE_DOWNLOAD"
    VENDOR_SUPPORT_DELIVERY = "VENDOR_SUPPORT_DELIVERY"
    VENDOR_SALES_DELIVERY = "VENDOR_SALES_DELIVERY"

    THIRD_PARTY_MIRROR = "THIRD_PARTY_MIRROR"
    SOFTWARE_CATALOGUE = "SOFTWARE_CATALOGUE"
    RESELLER_OR_DISTRIBUTOR = "RESELLER_OR_DISTRIBUTOR"
    UNLICENSED_REDISTRIBUTION = "UNLICENSED_REDISTRIBUTION"

    @property
    def is_official(self) -> bool:
        return self in (
            LocatorCategory.VENDOR_SELF_SERVICE_DOWNLOAD,
            LocatorCategory.VENDOR_SUPPORT_DELIVERY,
            LocatorCategory.VENDOR_SALES_DELIVERY,
        )


#: The channels through which a package may legitimately arrive.
OFFICIAL_DELIVERY_CHANNELS: tuple[str, ...] = (
    LocatorCategory.VENDOR_SELF_SERVICE_DOWNLOAD.value,
    LocatorCategory.VENDOR_SUPPORT_DELIVERY.value,
    LocatorCategory.VENDOR_SALES_DELIVERY.value,
)

#: What this stage will not accept a package from, whatever it contains.
REFUSED_ACQUISITION_SOURCES: tuple[str, ...] = (
    "a download mirror",
    "a software-catalogue or freeware site",
    "a third-party repository",
    "a reseller or distributor store",
    "an archive somebody uploaded",
    "a copy received from another project",
    "any build offered with a licence bypass, keygen or crack",
)

#: Everything G1 requires before it may pass. Every one is about bytes and
#: documents this project physically holds.
ACQUISITION_PASS_CONDITIONS: tuple[str, ...] = (
    "an official package was physically obtained through a vendor channel",
    "its exact bytes were hashed here",
    "the documentation delivered with it was obtained",
    "the licence or EULA delivered with it was obtained",
    "the trial mechanism distributed with it is present",
    "the exact package identity was recorded from the artifact",
)


# --------------------------------------------------------------- G2: the input

BENCHMARK_INPUT_PROFILE = "canonical_500"
BENCHMARK_INPUT_PPI = 500
BENCHMARK_INPUT_PIXEL_FORMAT = "gray8"
REQUIRED_INPUT_PPI = 500

#: The route that passes G2: the full canonical matrix handed to the vendor's own
#: loader, with every geometric decision after that made inside the vendor's
#: extractor.
IDEAL_INPUT_ROUTE: tuple[str, ...] = (
    "canonical gray8 500 ppi",
    "the full original pixel matrix, unmodified",
    "the official Griaule image object or loader",
    "the official extraction entry point",
    "any crop the extractor performs internally",
)

#: The only adaptation permitted, and only where the delivered API accepts no
#: other container. A file format is a container; the pixels inside it are the
#: input.
PERMITTED_DECODE_ROUTE: tuple[str, ...] = (
    "the canonical PNG",
    "a lossless decode to gray8",
    "the identical gray8 pixel values",
    "the container the delivered API accepts",
    "500 ppi recorded in the container's own resolution metadata",
)

#: What makes the adaptation above a container change rather than a preprocessing
#: step. Both must hold, and both are checkable without running anything.
DECODE_EQUIVALENCE_REQUIREMENTS: tuple[str, ...] = (
    "every pixel value is identical",
    "the geometry is unchanged: same width, same height, no crop, no pad",
)

#: What fpbench will not do to an image on the way into an extractor, under any
#: justification. If the delivered API requires the caller to supply an image
#: already reduced to the extractor's limit, that is a hard reject rather than a
#: compatibility step.
REFUSED_PREPROCESSING: tuple[str, ...] = (
    "cropping to the extractor's pixel limit",
    "choosing a crop origin",
    "resizing",
    "padding",
    "rotating",
    "selecting a region of interest",
    "enhancement",
    "normalisation",
)

#: The distinction G2 turns on. Griaule's documentation states that extraction
#: accepts at most 500 x 500 pixels and that larger images are cropped. A crop
#: the vendor's own extractor performs on a full image it was handed is part of
#: the algorithm under test and is published as such; a crop fpbench performs is
#: fpbench choosing which part of the finger the algorithm sees
#: (docs/adr/0124).
VENDOR_INTERNAL_CROP_IS_ALGORITHM_BEHAVIOUR = True

#: What the public documentation says those limits are. Recorded to shape the
#: question and never to settle it: the delivered headers and samples decide
#: whether the caller or the extractor is the one that has to respect them.
UPSTREAM_EXTRACTION_PIXEL_LIMIT = (500, 500)
UPSTREAM_CAPTURE_PIXEL_LIMIT = (1280, 1280)


# --------------------------------------------------------------- G3: the score

#: What the vendor's biometric documentation describes, and therefore what the
#: delivered header is expected to confirm. An expectation, not a finding.
SCORE_DIRECTION_EXPECTED_UPSTREAM = "HIGHER_IS_MORE_SIMILAR"

#: What the delivered header has to answer before G3 can pass. Every one is a
#: property of a function signature and its documented semantics.
SCORE_CONTRACT_QUESTIONS: tuple[str, ...] = (
    "does one image produce exactly one template through the delivered "
    "extraction entry point",
    "do two templates produce a scalar similarity score through the delivered "
    "1:1 verification entry point",
    "is that score reachable without the API collapsing it into a match or "
    "no-match answer",
    "what is the score's native numeric type",
    "what is the score's direction",
    "does the configured threshold change the number, or only the decision "
    "taken about it",
)

#: The rule that keeps G3 honest. The numeric type, the range and the exact
#: return or out-parameter semantics come from the delivered header, never from
#: the documentation site and never from a previous product generation.
SCORE_SHAPE_IS_NOT_ASSUMED = True

#: What fpbench does with a threshold. Nothing. The benchmark stores raw scores
#: and derives decisions in its own decision layer, from its own protocol.
THRESHOLD_IS_NOT_A_DECISION_HERE = True

#: What the public documentation states the defaults are. Upstream observations
#: only: they are recorded so that the delivered defaults can be compared against
#: them, and they are never applied, tuned or calibrated.
UPSTREAM_DEFAULT_THRESHOLD_INDICATION = 20
UPSTREAM_DEFAULT_ROTATION_TOLERANCE_INDICATION = -1

#: What fpbench does to a score once it has one. Nothing, in either direction.
FPBENCH_SCORE_TRANSFORMATION = "NONE"

#: Neither of these happens in this stage, and both are named so a marker that
#: claimed otherwise would fail to construct.
CALIBRATION_PERFORMED = False
THRESHOLD_PRODUCED = False

#: How the two images of a pair map onto the delivered comparison call. Taken
#: from the API under test rather than from this project's vocabulary, and
#: applied to every pair regardless of what the two orderings score
#: (docs/adr/0119). The right-hand words are filled in from the delivered header
#: at G3; until then the binding names the positions and not the parameters.
PAIR_ROLE_BINDING: tuple[tuple[str, str], ...] = (
    ("pair.left", "first_template"),
    ("pair.right", "second_template"),
)


# ------------------------------------------------------------- G4: the closure

#: What has to be recorded about every knob that can reach the score.
SETTING_INVENTORY_FIELDS: tuple[str, ...] = (
    "name",
    "type",
    "delivered_default_value",
    "source_authority",
    "score_affecting",
    "fpbench_changed",
)

#: The knobs G4 must account for if the delivered package has them. Not a closed
#: list of what exists — it is a list of what may not be *missing* from the
#: inventory. The first two are already proven to exist by the vendor's own
#: public documentation, which is why an inventory that omitted them would be
#: visibly incomplete rather than arguably complete.
SETTINGS_TO_ACCOUNT_FOR: tuple[str, ...] = (
    "verification threshold",
    "rotation tolerance",
    "template format",
    "image resolution metadata",
    "extraction options",
    "quality options",
    "matching profile or options",
)


class SettingProvenance(str, Enum):
    """Where a setting's value came from, and whether that is an authority."""

    #: Read off the delivered engine, header or configuration as shipped.
    DELIVERED_DEFAULT = "DELIVERED_DEFAULT"

    #: Stated by the delivered documentation that arrived with the package.
    DELIVERED_DOCUMENTATION = "DELIVERED_DOCUMENTATION"

    #: Stated by the vendor's public documentation site and not yet confirmed
    #: against the package. Shapes the question; settles nothing.
    UPSTREAM_PUBLIC_PAGE = "UPSTREAM_PUBLIC_PAGE"

    #: Chosen by fpbench. Never acceptable for a score-affecting setting.
    FPBENCH_CHOICE = "FPBENCH_CHOICE"

    #: Nobody recorded where it came from.
    UNRESOLVED = "UNRESOLVED"

    @property
    def is_upstream_authority(self) -> bool:
        """Whether a score-affecting setting may rest on this provenance."""
        return self in (
            SettingProvenance.DELIVERED_DEFAULT,
            SettingProvenance.DELIVERED_DOCUMENTATION,
        )


#: What ``fpbench_changed`` is for every setting unless something changes it, and
#: nothing in this stage does.
DEFAULT_FPBENCH_CHANGED = False

#: The rule G4 exists to enforce. A value is accepted because the vendor
#: delivered it, never because it produced better numbers — this stage runs no
#: comparison at all, so it could not know which value did.
NO_SETTING_IS_CHOSEN_BY_TRYING_VALUES = True


# ---------------------------------------------------------- what this stage is not

#: Published in the report so the boundary is a claim a reader can check rather
#: than a promise in prose.
STAGE_14A_DOES_NOT: tuple[str, ...] = (
    "activate a trial",
    "execute anything that produces a biometric score",
    "run a determinism experiment",
    "measure performance",
    "read SD300 image bytes, its pair manifest or its scores",
    "read any prior algorithm's scores",
    "create a fingerprint algorithm adapter",
    "integrate anything into the algorithm registry",
    "run the 6,000-pair canonical workload",
    "produce a threshold profile",
    "calibrate anything",
    "produce a metric",
)


# ------------------------------------------------------------------ the guards

#: Keys whose mere presence in a published document is a leak.
SENSITIVE_EVIDENCE_KEYS: frozenset[str] = frozenset(
    {
        "license_key",
        "licence_key",
        "license_file",
        "licence_file",
        "serial_number",
        "activation_code",
        "machine_id",
        "hardware_id",
        "trial_token",
        "token",
        "password",
        "secret",
        "api_key",
        "signed_url",
        "download_token",
        "customer_id",
        "account_id",
        "email",
        "email_address",
        "path",
        "absolute_path",
        "local_path",
        "home_directory",
    }
)

#: Value shapes that are licence material or a machine path whatever key they sit
#: under. Assembled as source strings so the module carries no example of the
#: thing it refuses.
SENSITIVE_VALUE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("a GUID", r"\b[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\b"),
    ("a Windows drive path", r"\b[A-Za-z]:[\\/](?:Users|Program Files|ProgramData)\b"),
    ("a POSIX home path", r"(?:^|[\s\"'])/(?:home|Users)/[^\s\"']+"),
    ("an e-mail address", r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    ("a signed or tokenized URL", r"https?://[^\s\"']*[?&](?:token|sig|signature)="),
)

#: Keys a Stage 14A document may never carry at all, for reasons that have
#: nothing to do with secrecy: this stage produces no score, no template and no
#: image, so a document holding one would be publishing something no gate
#: produced.
FORBIDDEN_PUBLISHED_KEYS: frozenset[str] = frozenset(
    {
        "score",
        "scores",
        "similarity",
        "similarity_score",
        "template",
        "templates",
        "template_bytes",
        "minutiae",
        "image",
        "image_bytes",
        "pixels",
        "decision",
        "threshold_value_applied",
    }
)


# --------------------------------------------------------------- bound stages

#: Stage 14A exists because Stage 13A closed without filling the Algorithm 5
#: slot. The fingerprint below is taken from that stage's own republished marker
#: and is what makes this a successor rather than a restart.
STAGE_13A_OUTCOME = "FINGERCELL_PREFLIGHT_FAIL"
STAGE_13A_FAILURE_CLASS = "OPERATIONAL_TRIAL_ENTITLEMENT_NOT_ESTABLISHED"
STAGE_13A_FINALIZATION_FINGERPRINT = (
    "b24bdb672926abfb5dd5a9e03a4c3aab39f51488d9a5413092adef392d99871d"
)
STAGE_13A_EVIDENCE_DIRECTORY = "/".join(
    ("evidence", "stage13a-" + "fingercell-preflight")
)

#: Algorithm 4's 6,000 published outcomes. Bound and never read.
STAGE_11B_OUTCOME = "VERIFINGER_CANONICAL500_RAW_COMPLETE"
STAGE_11B_FINALIZATION_FINGERPRINT = (
    "3d271490edda9e3e9d066485c2d93e82e2eceb4556668df7d65a8207e591684c"
)

#: The third-party research-use policy, reused and not reopened. It is applied to
#: the terms that arrive *with a package*, never to a marketing page.
STAGE8E_OUTCOME = "RESEARCH_ONLY_THIRD_PARTY_POLICY_READY"
STAGE8E_FINALIZATION_FINGERPRINT = (
    "c08648dece292603eb9d4b6fff0b3412523af0730da59141b6e7a32ee02540e8"
)
STAGE8E_PURPOSE_FINGERPRINT = (
    "a62ab45681bdbd9cc4e741e1e5522583746b5d29f1fe911fa687fc7fee405443"
)
STAGE8E_POLICY_FINGERPRINT = (
    "de9cdbaa23522c4a15337d86b0ec2df8af8b79383a1f8014294e8c7855bf972a"
)

#: Where a delivered package would live, inside the local artifact store and
#: never inside the working tree.
ARTIFACT_STORE_PREFIX = "griaule-gbs-fingerprint"

#: Every module whose bytes decide this preflight. The marker fingerprints all of
#: them together, so a decision cannot be changed without the marker moving.
STAGE_14A_SOURCE_FILES: tuple[str, ...] = tuple(
    "/".join(parts)
    for parts in (
        ("src", "fpbench", "core", "griaule_preflight_errors.py"),
        ("src", "fpbench", "experiments", "stage14a_griaule_identity.py"),
        ("src", "fpbench", "experiments", "stage14a_griaule_observations.py"),
        ("src", "fpbench", "experiments", "stage14a_acquisition.py"),
        ("src", "fpbench", "experiments", "stage14a_preflight.py"),
        ("src", "fpbench", "experiments", "stage14a_finalization.py"),
    )
)


def all_frozen_identifiers() -> tuple[str, ...]:
    """Every enumerated name this stage can publish, for a drift test to pin."""
    return tuple(
        sorted(
            {member.value for member in PreflightGate}
            | {member.value for member in GateStatus}
            | {member.value for member in BlockerCode}
            | {member.value for member in PendingKind}
            | {member.value for member in RequiredAction}
            | {member.value for member in FailureClass}
            | {member.value for member in LocatorCategory}
            | {member.value for member in SettingProvenance}
            | set(STAGE_14A_OUTCOMES)
        )
    )


def _validate_module() -> None:
    """Checked at import, because a drifted constant is not a runtime condition."""
    if len(GATE_ORDER) != len(set(GATE_ORDER)):  # pragma: no cover - defensive
        raise GriauleCandidateIdentityError("a gate is listed twice")
    if GATE_COUNT != 4:
        raise GriauleCandidateIdentityError(
            f"Stage 14A defines exactly four gates and found {GATE_COUNT}; a "
            "preflight with more would be the full-size stage this one exists "
            "not to be"
        )
    if tuple(gate for gate, _ in GATE_DOCUMENTS) != GATE_ORDER:
        raise GriauleCandidateIdentityError(
            "every gate reports through at least one document, in gate order"
        )
    if tuple(gate for gate, _ in GATE_BLOCKERS) != GATE_ORDER:
        raise GriauleCandidateIdentityError(
            "every gate names the blockers it may raise, in gate order"
        )
    if tuple(gate for gate, _ in GATE_ACTIONS) != GATE_ORDER:
        raise GriauleCandidateIdentityError(
            "every gate names the actions it may report, in gate order"
        )
    documented = [name for _, names in GATE_DOCUMENTS for name in names]
    if len(documented) != len(set(documented)):
        raise GriauleCandidateIdentityError(
            "two gates report through the same document, which would give one "
            "conclusion two authorities"
        )
    missing = set(documented) - set(REQUIRED_EVIDENCE_FILES)
    if missing:
        raise GriauleCandidateIdentityError(
            f"gates report through {sorted(missing)}, which this stage does not "
            "publish"
        )
    codes = [code for _, codes in GATE_BLOCKERS for code in codes]
    if set(codes) != set(BlockerCode):
        raise GriauleCandidateIdentityError(
            "a blocker belongs to no gate, and one nobody can raise is one nobody "
            "can lift"
        )
    for code in BlockerCode:
        try:
            FailureClass(code.value)
        except ValueError as exc:  # pragma: no cover - checked here
            raise GriauleCandidateIdentityError(
                f"{code.value} has no failure class, so a FAIL raised on it could "
                "not say what kind of failure it is"
            ) from exc
    if set(BlockerCode) & {  # pragma: no cover - defensive
        member.value for member in RequiredAction
    }:
        raise GriauleCandidateIdentityError(
            "a blocker and an action share a name, and the two vocabularies are "
            "disjoint by construction"
        )
    actions = [action for _, actions in GATE_ACTIONS for action in actions]
    if set(actions) != set(RequiredAction):
        raise GriauleCandidateIdentityError("an action belongs to no gate")
    if set(DERIVABLE_EVIDENCE_FILES) | {README_NAME, STAGE_14A_FINALIZATION_NAME} != set(
        REQUIRED_EVIDENCE_FILES
    ):  # pragma: no cover - defensive
        raise GriauleCandidateIdentityError("the derivable document list has drifted")
    for digest in (
        STAGE_13A_FINALIZATION_FINGERPRINT,
        STAGE_11B_FINALIZATION_FINGERPRINT,
        STAGE8E_FINALIZATION_FINGERPRINT,
        STAGE8E_PURPOSE_FINGERPRINT,
        STAGE8E_POLICY_FINGERPRINT,
    ):
        if len(digest) != 64 or set(digest) - set("0123456789abcdef"):
            raise GriauleCandidateIdentityError(
                "a bound stage fingerprint is not a 64-character hex digest"
            )


_validate_module()
