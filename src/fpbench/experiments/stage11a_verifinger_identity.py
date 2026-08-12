"""Everything Stage 11A froze before it opened the VeriFinger artifact.

These constants are the stage's contract with itself: the one provisional
candidate, the seventeen hard gates and the order they run in, the closed blocker
vocabulary, the two outcomes, the provenance vocabulary a score-affecting setting
must be labelled with, the frozen workload, the conjunction that admits the
candidate, and the keys no published document may ever carry. They are asserted
by the contract suite, republished in the finalization, and a later change to any
of them is a different preflight rather than a quiet correction to this one.

Stage 11A asks one question:

.. code-block:: text

    does an official, exact VeriFinger 2025.2 artifact let fpbench take
    canonical_500 in and get a reproducible raw 1:1 score out, with every
    externally selectable behaviour that can affect that score defined by
    Neurotechnology rather than invented here?

It is allowed to answer "no" (docs/adr/0099).

**This stage acquires.** Stage 10B stopped at a vendor who publishes no
self-service download, and the honest result was that nobody had walked the
route. Neurotechnology publishes a direct locator, so Stage 11A's first real act
is the download — not an adapter, and not another reading of a product page
(docs/adr/0100). What follows the download is inspection of the pinned bytes.

**Stage 10B is not re-opened.** Its candidate was id3, its gates were id3's, and
its marker reserved Stage 10C for id3 and opened a candidate search. Stage 11A is
that search's next candidate: it binds Stage 10B's fingerprint as a predecessor
and edits nothing under its evidence directory.

Nothing here is derived at import time, nothing reads a workspace, nothing
downloads anything, and nothing is a fingerprint image, a score, a licence byte
or a credential.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath

from fpbench.core.identifiers import validate_id
from fpbench.core.verifinger_preflight_errors import VeriFingerCandidateIdentityError

__all__ = [
    "STAGE_11A_SCHEMA_VERSION",
    "STAGE_FINALIZATION_KIND",
    "ALGORITHM_SLOT",
    "STAGE_11A_SELECTED_OUTCOME",
    "STAGE_11A_BLOCKED_OUTCOME",
    "STAGE_11A_OUTCOMES",
    "CANDIDATE_PASS_VERDICT",
    "CANDIDATE_FAIL_VERDICT",
    "CANDIDATE_VERDICTS",
    "CANDIDATE_ID",
    "IMPLEMENTATION_ORIGIN",
    "PRODUCTION_ALGORITHM_ID_FROZEN",
    "FINAL_IDENTITY_COMPONENTS",
    "DECLARED_NON_CANDIDATES",
    "EVIDENCE_DIRECTORY",
    "README_NAME",
    "CANDIDATE_IDENTITY_NAME",
    "ACQUISITION_MANIFEST_NAME",
    "ARTIFACT_MANIFEST_NAME",
    "RUNTIME_IDENTITY_NAME",
    "THIRD_PARTY_USAGE_BINDING_NAME",
    "INPUT_DOMAIN_CONTRACT_NAME",
    "EXTRACTION_PROFILE_NAME",
    "REPRESENTATION_PROFILE_NAME",
    "MATCHER_PROFILE_NAME",
    "SCORE_CONTRACT_NAME",
    "PAIR_SEMANTICS_NAME",
    "DETERMINISM_REPORT_NAME",
    "RUNTIME_FEASIBILITY_NAME",
    "TRAINING_PROVENANCE_NAME",
    "PREFLIGHT_REPORT_NAME",
    "STAGE_11A_FINALIZATION_NAME",
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
    "ArtifactRoute",
    "AcquisitionStatus",
    "PossessionStatus",
    "SettingProvenance",
    "REFUSED_SETTING_PROVENANCE",
    "RepresentationType",
    "ScoreRouteStatus",
    "NetworkRole",
    "TrainingProvenanceStatus",
    "SD300OverlapStatus",
    "FailureClass",
    "ACQUISITION_PIN_FIELDS",
    "EXCLUDED_FROM_EVIDENCE",
    "RUNTIME_IDENTITY_FIELDS",
    "ARTIFACT_CLOSURE_CLASSES",
    "EMBEDDED_MODEL_MARKER",
    "BENCHMARK_INPUT_PROFILE",
    "BENCHMARK_INPUT_PPI",
    "BENCHMARK_INPUT_PIXEL_FORMAT",
    "CANONICAL500_REQUIRED_ROUTE",
    "REFUSED_PREPROCESSING",
    "INTERNAL_BLACK_BOX_PREPROCESSING_IS_ACCEPTABLE",
    "EXTRACTOR_PROFILE_INVENTORY",
    "MATCHER_PROFILE_INVENTORY",
    "REPRESENTATION_CANDIDATES",
    "PUBLISHABLE_REPRESENTATION_FACTS",
    "SCORE_CONTRACT_REQUIREMENTS",
    "PAIR_ORIENTATION_REQUIREMENTS",
    "SELF_SEMANTICS_REQUIREMENTS",
    "DETERMINISM_LEVELS",
    "FAILURE_SEMANTICS_CLASSES",
    "NETWORK_DEPENDENCY_QUESTIONS",
    "RUNTIME_FEASIBILITY_MEASUREMENTS",
    "FEASIBILITY_LATENCY_MEASURE",
    "RARE_DEPENDENCY_RULE",
    "LICENSE_CAPACITY_QUESTIONS",
    "FrozenWorkload",
    "FROZEN_WORKLOAD",
    "FIXTURE_POLICY",
    "SD300_DENIALS",
    "ScoreClass",
    "RUNTIME_PLATFORM_LOCK_FIELDS",
    "QUALIFICATION_RUN_STEPS",
    "QUALIFICATION_RUN_MAX_SCORES",
    "QUALIFICATION_RUN_INPUT_COMPONENTS",
    "QUALIFICATION_PASSES",
    "QualificationOutcome",
    "FAILURE_SEMANTICS_CAUSES",
    "FIXTURE_VERSION",
    "UNREADABLE_SETTING_PREFIX",
    "setting_value_is_resolved",
    "FROZEN_VERIFICATION_ATTEMPTS",
    "PendingActionCode",
    "GATE_PENDING_ACTIONS",
    "gate_pending_actions",
    "EXECUTION_DEPENDENT_GATES",
    "STAGE_11A_INCOMPLETE_OUTCOME",
    "CANDIDATE_INCOMPLETE_VERDICT",
    "AUTHORITATIVE_ROUTE_SAMPLE",
    "ACCEPTANCE_CONDITIONS",
    "NON_GOALS",
    "PRODUCTION_INTEGRATION_NOT_CREATED",
    "SENSITIVE_EVIDENCE_KEYS",
    "SENSITIVE_VALUE_PATTERNS",
    "FORBIDDEN_PUBLISHED_KEYS",
    "STAGE_10B_FINALIZATION_FINGERPRINT",
    "STAGE_10B_OUTCOME",
    "STAGE_10B_EVIDENCE_DIRECTORY",
    "STAGE8E_FINALIZATION_FINGERPRINT",
    "STAGE8E_OUTCOME",
    "STAGE8E_PURPOSE_FINGERPRINT",
    "STAGE8E_POLICY_FINGERPRINT",
    "ARTIFACT_STORE_PREFIX",
    "VERIFINGER_ARTIFACT_MARKER",
    "STAGE_11B_SCOPE",
    "STAGE_11A_SOURCE_FILES",
    "QUALIFICATION_HARNESS_SOURCE",
    "STAGE_11A_ADRS",
    "STAGE_11A_DOCUMENTS",
    "all_frozen_identifiers",
]

STAGE_11A_SCHEMA_VERSION = "1"
STAGE_FINALIZATION_KIND = "stage_11a_finalization"

#: The benchmark slot this preflight is qualifying a candidate for. Nothing here
#: fills it: a pass opens Stage 11B, and Stage 11B is the integration.
ALGORITHM_SLOT = "algorithm_4"

#: Three outcomes, and the third one is the important correction.
#:
#: The specification expected two, on the reasoning that a direct download makes
#: acquisition binary. That reasoning was right about *acquisition* and wrong
#: about the stage: most of these gates are questions about a running licensed
#: engine, and "nobody has run it yet" is not the same claim as "this route
#: cannot work". Publishing the first as ``VERIFINGER_PREFLIGHT_FAIL`` said
#: something about VeriFinger that nothing had established — the same
#: overstatement Stage 10B was careful to avoid between ``NOT_OBTAINED`` and
#: ``UNAVAILABLE``, one layer up.
#:
#: ``INCOMPLETE`` means every question that was asked was answered and some were
#: not asked, with a named action that would ask them. ``FAIL`` is reserved for a
#: real blocker: something the artifact, the notices or an execution actually
#: showed to be wrong with the route (docs/adr/0104).
STAGE_11A_SELECTED_OUTCOME = "VERIFINGER_PREFLIGHT_PASS"
STAGE_11A_BLOCKED_OUTCOME = "VERIFINGER_PREFLIGHT_FAIL"
STAGE_11A_INCOMPLETE_OUTCOME = "VERIFINGER_PREFLIGHT_INCOMPLETE"
STAGE_11A_OUTCOMES = (
    STAGE_11A_SELECTED_OUTCOME,
    STAGE_11A_INCOMPLETE_OUTCOME,
    STAGE_11A_BLOCKED_OUTCOME,
)

CANDIDATE_PASS_VERDICT = STAGE_11A_SELECTED_OUTCOME
CANDIDATE_FAIL_VERDICT = STAGE_11A_BLOCKED_OUTCOME
CANDIDATE_INCOMPLETE_VERDICT = STAGE_11A_INCOMPLETE_OUTCOME
CANDIDATE_VERDICTS = (
    CANDIDATE_PASS_VERDICT,
    CANDIDATE_INCOMPLETE_VERDICT,
    CANDIDATE_FAIL_VERDICT,
)


# ------------------------------------------------------------ the one candidate

#: Provisional, and provisional is the point. This names the *subject* of the
#: preflight, not a production algorithm: no ``AlgorithmConfig`` carries it, no
#: run reports under it, and nothing downstream may treat it as an algorithm id
#: (spec section 1).
CANDIDATE_ID = "neurotechnology_verifinger_2025_2_1to1"

IMPLEMENTATION_ORIGIN = "VENDOR_OFFICIAL_SDK"

#: Nothing is frozen as a production identity yet, and this says so in a field
#: rather than in prose so that a later stage cannot quietly assume otherwise.
PRODUCTION_ALGORITHM_ID_FROZEN = False

#: What a final identity would have to name (spec section 1). Every one of these
#: is score-affecting or selects between score-affecting behaviours, which is why
#: none may be left to a value nobody wrote down.
FINAL_IDENTITY_COMPONENTS: tuple[str, ...] = (
    "the delivered package, by filename, byte size and SHA-256",
    "the build, as the artifact itself reports it rather than as a web page "
    "prints it",
    "the platform: operating system, architecture and the exact native "
    "libraries loaded",
    "the template profile: which representation is compared, and in which "
    "format",
    "the extractor profile: every externally selectable extraction setting and "
    "its value",
    "the matcher profile: every externally selectable matching setting and its "
    "value",
)

#: Products and packages this stage names so that nobody later mistakes one for
#: the subject. Neurotechnology ships one archive containing five SDKs, and two
#: of the entries below are the ways that archive is most easily confused with
#: something else (spec section 3).
DECLARED_NON_CANDIDATES: tuple[tuple[str, str], ...] = (
    (
        "neurotec_biometric_python_packages_2025_1",
        "The vendor's experimental Python packages. A separate download, a "
        "separate distribution, and — decisively — version 2025.1 rather than "
        "2025.2. Qualifying it would qualify a different product version from "
        "the one this stage is named for, and mixing its runtime files with the "
        "2025.2 archive's is refused outright (spec section 3).",
    ),
    (
        "neurotec_megamatcher_2025_2",
        "MegaMatcher 2025.2 SDK, shipped inside the same archive. A different "
        "product with its own licences and its own matcher; sharing an archive "
        "is not sharing an identity.",
    ),
    (
        "neurotechnology_verifinger_algorithm_demo",
        "The separately downloadable Algorithm Demo application. A GUI over the "
        "technology, not the SDK this stage would integrate.",
    ),
    (
        "neurotechnology_verifinger_nist_submission",
        "Any MINEX, PFT or FpVTE submission. An evaluation submission is a "
        "configuration of a product under somebody else's protocol, not the "
        "delivered package this stage pins.",
    ),
    (
        "verifinger_standard_versus_extended_sdk",
        "Standard and Extended are different licence sets over the same "
        "archive. Which components a licence enables is part of the identity, "
        "and this stage records it rather than assuming Standard.",
    ),
)


# --------------------------------------------------------- the published files

EVIDENCE_DIRECTORY = Path("evidence") / "stage11a-verifinger-2025_2-preflight"

README_NAME = "README.md"
CANDIDATE_IDENTITY_NAME = "candidate-identity.json"
ACQUISITION_MANIFEST_NAME = "acquisition-manifest.json"
ARTIFACT_MANIFEST_NAME = "artifact-manifest.json"
RUNTIME_IDENTITY_NAME = "runtime-identity.json"
THIRD_PARTY_USAGE_BINDING_NAME = "third-party-usage-binding.json"
INPUT_DOMAIN_CONTRACT_NAME = "input-domain-contract.json"
EXTRACTION_PROFILE_NAME = "extraction-profile.json"
REPRESENTATION_PROFILE_NAME = "representation-profile.json"
MATCHER_PROFILE_NAME = "matcher-profile.json"
SCORE_CONTRACT_NAME = "score-contract.json"
PAIR_SEMANTICS_NAME = "pair-semantics.json"
DETERMINISM_REPORT_NAME = "determinism-report.json"
RUNTIME_FEASIBILITY_NAME = "runtime-feasibility.json"
TRAINING_PROVENANCE_NAME = "training-provenance.json"
PREFLIGHT_REPORT_NAME = "preflight-report.json"

#: The last-written authority, and the last file committed.
STAGE_11A_FINALIZATION_NAME = "stage-11a-finalization.json"

#: Exactly the structure the specification asks for, in the order the documents
#: depend on each other. An extra file is a finding (spec section 47).
REQUIRED_EVIDENCE_FILES: tuple[str, ...] = (
    README_NAME,
    CANDIDATE_IDENTITY_NAME,
    ACQUISITION_MANIFEST_NAME,
    ARTIFACT_MANIFEST_NAME,
    RUNTIME_IDENTITY_NAME,
    THIRD_PARTY_USAGE_BINDING_NAME,
    INPUT_DOMAIN_CONTRACT_NAME,
    EXTRACTION_PROFILE_NAME,
    REPRESENTATION_PROFILE_NAME,
    MATCHER_PROFILE_NAME,
    SCORE_CONTRACT_NAME,
    PAIR_SEMANTICS_NAME,
    DETERMINISM_REPORT_NAME,
    RUNTIME_FEASIBILITY_NAME,
    TRAINING_PROVENANCE_NAME,
    PREFLIGHT_REPORT_NAME,
    STAGE_11A_FINALIZATION_NAME,
)


# ------------------------------------------------------------ the seventeen gates


class PreflightGate(str, Enum):
    """The seventeen hard gates. Every one of them is mandatory.

    There is no weighting between them and no score at which enough gates make
    the candidate acceptable. The order is the specification's fail-fast order:
    acquisition first because everything else is a question about an artifact,
    and the raw score before latency and provenance because a route with no
    scalar score is not worth measuring (spec section 44).
    """

    OFFICIAL_ARTIFACT_ACQUISITION = "OFFICIAL_ARTIFACT_ACQUISITION"
    RUNTIME_IDENTITY = "RUNTIME_IDENTITY"
    RESEARCH_USE_PERMISSION = "RESEARCH_USE_PERMISSION"
    ARTIFACT_CLOSURE = "ARTIFACT_CLOSURE"
    CANONICAL500_INPUT_ROUTE = "CANONICAL500_INPUT_ROUTE"
    EXTRACTION_PROFILE = "EXTRACTION_PROFILE"
    REPRESENTATION_PROFILE = "REPRESENTATION_PROFILE"
    MATCHER_PROFILE = "MATCHER_PROFILE"
    RAW_SCORE_ROUTE = "RAW_SCORE_ROUTE"
    PAIR_ORIENTATION = "PAIR_ORIENTATION"
    SELF_SEMANTICS = "SELF_SEMANTICS"
    SCORE_DETERMINISM = "SCORE_DETERMINISM"
    FAILURE_SEMANTICS = "FAILURE_SEMANTICS"
    NETWORK_DEPENDENCY = "NETWORK_DEPENDENCY"
    RUNTIME_FEASIBILITY = "RUNTIME_FEASIBILITY"
    LICENSE_CAPACITY = "LICENSE_CAPACITY"
    TRAINING_PROVENANCE = "TRAINING_PROVENANCE"


GATE_ORDER: tuple[PreflightGate, ...] = (
    PreflightGate.OFFICIAL_ARTIFACT_ACQUISITION,
    PreflightGate.RUNTIME_IDENTITY,
    PreflightGate.RESEARCH_USE_PERMISSION,
    PreflightGate.ARTIFACT_CLOSURE,
    PreflightGate.CANONICAL500_INPUT_ROUTE,
    PreflightGate.EXTRACTION_PROFILE,
    PreflightGate.REPRESENTATION_PROFILE,
    PreflightGate.MATCHER_PROFILE,
    PreflightGate.RAW_SCORE_ROUTE,
    PreflightGate.PAIR_ORIENTATION,
    PreflightGate.SELF_SEMANTICS,
    PreflightGate.SCORE_DETERMINISM,
    PreflightGate.FAILURE_SEMANTICS,
    PreflightGate.NETWORK_DEPENDENCY,
    PreflightGate.RUNTIME_FEASIBILITY,
    PreflightGate.LICENSE_CAPACITY,
    PreflightGate.TRAINING_PROVENANCE,
)

GATE_COUNT = len(GATE_ORDER)


class GateStatus(str, Enum):
    """What one gate concluded. Four states, and the differences all matter.

    ``PASS`` — asked and answered.

    ``FAIL`` — asked and answered badly. A real blocker: something about the
    route was shown to be wrong. This is the only status that stops the run.

    ``ACTION_REQUIRED`` — not asked, because a named prerequisite has not been
    done, and the prerequisite is one a person can do. It is not a failure and
    must never be reported as one: "nobody has activated the trial" says nothing
    about VeriFinger. Later gates still run, because most of them do not depend
    on this one (docs/adr/0104).

    ``NOT_REACHED`` — not asked, because the run had already stopped at a
    ``FAIL``. Publishing it as anything else would be inventing a conclusion.
    """

    PASS = "PASS"
    FAIL = "FAIL"
    ACTION_REQUIRED = "ACTION_REQUIRED"
    NOT_REACHED = "NOT_REACHED"

    @property
    def is_a_finding(self) -> bool:
        """Whether the gate actually decided something about the candidate."""
        return self in (GateStatus.PASS, GateStatus.FAIL)

    @property
    def was_asked(self) -> bool:
        return self.is_a_finding


#: The documents each gate reports through. Several gates share the preflight
#: report rather than owning a file, and two own two files each: acquisition owns
#: both the acquisition manifest and the artifact manifest, because what was
#: fetched and what is inside it are different claims (spec section 47).
GATE_DOCUMENTS: tuple[tuple[PreflightGate, tuple[str, ...]], ...] = (
    (
        PreflightGate.OFFICIAL_ARTIFACT_ACQUISITION,
        (ACQUISITION_MANIFEST_NAME, ARTIFACT_MANIFEST_NAME),
    ),
    (PreflightGate.RUNTIME_IDENTITY, (RUNTIME_IDENTITY_NAME,)),
    (PreflightGate.RESEARCH_USE_PERMISSION, (THIRD_PARTY_USAGE_BINDING_NAME,)),
    (PreflightGate.ARTIFACT_CLOSURE, ()),
    (PreflightGate.CANONICAL500_INPUT_ROUTE, (INPUT_DOMAIN_CONTRACT_NAME,)),
    (PreflightGate.EXTRACTION_PROFILE, (EXTRACTION_PROFILE_NAME,)),
    (PreflightGate.REPRESENTATION_PROFILE, (REPRESENTATION_PROFILE_NAME,)),
    (PreflightGate.MATCHER_PROFILE, (MATCHER_PROFILE_NAME,)),
    (PreflightGate.RAW_SCORE_ROUTE, (SCORE_CONTRACT_NAME,)),
    (PreflightGate.PAIR_ORIENTATION, (PAIR_SEMANTICS_NAME,)),
    (PreflightGate.SELF_SEMANTICS, ()),
    (PreflightGate.SCORE_DETERMINISM, (DETERMINISM_REPORT_NAME,)),
    (PreflightGate.FAILURE_SEMANTICS, ()),
    (PreflightGate.NETWORK_DEPENDENCY, ()),
    (PreflightGate.RUNTIME_FEASIBILITY, (RUNTIME_FEASIBILITY_NAME,)),
    (PreflightGate.LICENSE_CAPACITY, ()),
    (PreflightGate.TRAINING_PROVENANCE, (TRAINING_PROVENANCE_NAME,)),
)


def gate_documents(gate: PreflightGate) -> tuple[str, ...]:
    """The documents one gate reports through, possibly none.

    A gate with no document of its own reports through the preflight report. The
    alternative — one file per gate — would have produced five documents whose
    entire content was a status and a sentence, and a reader would have to open
    all of them to find the one that mattered.
    """
    for item, names in GATE_DOCUMENTS:
        if item is gate:
            return names
    raise VeriFingerCandidateIdentityError(  # pragma: no cover - GATE_ORDER covers
        f"{gate!r} is not a Stage 11A gate"
    )


class BlockerCode(str, Enum):
    """Why VeriFinger cannot enter fpbench as Algorithm 4. A closed list.

    Exactly the vocabulary the specification fixed, and deliberately minimal
    (spec section 46). Each member names something a reader could act on, and
    each is attached to at least one gate below. "Not ideal", "some risk" and
    "probably fine" are not among them and cannot be expressed here.
    """

    OFFICIAL_ARTIFACT_NOT_OBTAINABLE = "OFFICIAL_ARTIFACT_NOT_OBTAINABLE"
    ARTIFACT_IDENTITY_UNRESOLVED = "ARTIFACT_IDENTITY_UNRESOLVED"
    RESEARCH_USE_BLOCKED = "RESEARCH_USE_BLOCKED"
    REQUIRED_RUNTIME_COMPONENT_MISSING = "REQUIRED_RUNTIME_COMPONENT_MISSING"

    CANONICAL500_INPUT_ROUTE_UNRESOLVED = "CANONICAL500_INPUT_ROUTE_UNRESOLVED"
    FPBENCH_PREPROCESSING_CHOICE_REQUIRED = "FPBENCH_PREPROCESSING_CHOICE_REQUIRED"

    EXTRACTION_PROFILE_UNRESOLVED = "EXTRACTION_PROFILE_UNRESOLVED"
    REPRESENTATION_PROFILE_UNRESOLVED = "REPRESENTATION_PROFILE_UNRESOLVED"
    MATCHER_PROFILE_UNRESOLVED = "MATCHER_PROFILE_UNRESOLVED"
    HIDDEN_SCORE_AFFECTING_DEFAULT_UNRESOLVED = (
        "HIDDEN_SCORE_AFFECTING_DEFAULT_UNRESOLVED"
    )

    RAW_SCORE_ROUTE_UNRESOLVED = "RAW_SCORE_ROUTE_UNRESOLVED"
    PAIR_ORDER_SEMANTICS_UNRESOLVED = "PAIR_ORDER_SEMANTICS_UNRESOLVED"
    SCORE_NONDETERMINISM_OBSERVED = "SCORE_NONDETERMINISM_OBSERVED"

    REMOTE_COMPUTATION_IDENTITY_UNRESOLVED = "REMOTE_COMPUTATION_IDENTITY_UNRESOLVED"
    LICENSE_WORKLOAD_CAPACITY_INSUFFICIENT = "LICENSE_WORKLOAD_CAPACITY_INSUFFICIENT"

    SD300_TRAINING_OVERLAP_FOUND = "SD300_TRAINING_OVERLAP_FOUND"
    LOCAL_SMOKE_FAILED = "LOCAL_SMOKE_FAILED"


#: Which gates each blocker may be raised at. A blocker raised against a gate
#: that was never reached is a contradiction, and the engine refuses one.
#:
#: ``LOCAL_SMOKE_FAILED`` belongs to every execution-dependent gate rather than
#: to one: the smoke is not a gate of its own here — it is *how* those gates are
#: answered at all, and a run that starts and dies is the same finding wherever
#: it is noticed (spec sections 25, 26, 28 and 33). The vocabulary itself is
#: unchanged; only which gates may raise which member.
GATE_BLOCKERS: tuple[tuple[PreflightGate, tuple[BlockerCode, ...]], ...] = (
    (
        PreflightGate.OFFICIAL_ARTIFACT_ACQUISITION,
        (BlockerCode.OFFICIAL_ARTIFACT_NOT_OBTAINABLE,),
    ),
    (
        PreflightGate.RUNTIME_IDENTITY,
        (BlockerCode.ARTIFACT_IDENTITY_UNRESOLVED, BlockerCode.LOCAL_SMOKE_FAILED),
    ),
    (PreflightGate.RESEARCH_USE_PERMISSION, (BlockerCode.RESEARCH_USE_BLOCKED,)),
    (
        PreflightGate.ARTIFACT_CLOSURE,
        (
            BlockerCode.REQUIRED_RUNTIME_COMPONENT_MISSING,
            BlockerCode.ARTIFACT_IDENTITY_UNRESOLVED,
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
        PreflightGate.EXTRACTION_PROFILE,
        (
            BlockerCode.EXTRACTION_PROFILE_UNRESOLVED,
            BlockerCode.HIDDEN_SCORE_AFFECTING_DEFAULT_UNRESOLVED,
            BlockerCode.LOCAL_SMOKE_FAILED,
        ),
    ),
    (
        PreflightGate.REPRESENTATION_PROFILE,
        (BlockerCode.REPRESENTATION_PROFILE_UNRESOLVED,),
    ),
    (
        PreflightGate.MATCHER_PROFILE,
        (
            BlockerCode.MATCHER_PROFILE_UNRESOLVED,
            BlockerCode.HIDDEN_SCORE_AFFECTING_DEFAULT_UNRESOLVED,
            BlockerCode.LOCAL_SMOKE_FAILED,
        ),
    ),
    (PreflightGate.RAW_SCORE_ROUTE, (BlockerCode.RAW_SCORE_ROUTE_UNRESOLVED,)),
    (
        PreflightGate.PAIR_ORIENTATION,
        (
            BlockerCode.PAIR_ORDER_SEMANTICS_UNRESOLVED,
            BlockerCode.LOCAL_SMOKE_FAILED,
        ),
    ),
    (PreflightGate.SELF_SEMANTICS, (BlockerCode.LOCAL_SMOKE_FAILED,)),
    (
        PreflightGate.SCORE_DETERMINISM,
        (BlockerCode.SCORE_NONDETERMINISM_OBSERVED, BlockerCode.LOCAL_SMOKE_FAILED),
    ),
    (PreflightGate.FAILURE_SEMANTICS, (BlockerCode.LOCAL_SMOKE_FAILED,)),
    (
        PreflightGate.NETWORK_DEPENDENCY,
        (BlockerCode.REMOTE_COMPUTATION_IDENTITY_UNRESOLVED,),
    ),
    (
        PreflightGate.RUNTIME_FEASIBILITY,
        (
            BlockerCode.REQUIRED_RUNTIME_COMPONENT_MISSING,
            BlockerCode.LOCAL_SMOKE_FAILED,
        ),
    ),
    (
        PreflightGate.LICENSE_CAPACITY,
        (
            BlockerCode.LICENSE_WORKLOAD_CAPACITY_INSUFFICIENT,
            BlockerCode.LOCAL_SMOKE_FAILED,
        ),
    ),
    (PreflightGate.TRAINING_PROVENANCE, (BlockerCode.SD300_TRAINING_OVERLAP_FOUND,)),
)


def gate_of_blocker(code: BlockerCode) -> tuple[PreflightGate, ...]:
    """Every gate a blocker code may be raised at."""
    return tuple(gate for gate, codes in GATE_BLOCKERS if code in codes)


class PendingActionCode(str, Enum):
    """Why a gate was not asked, where the reason is a deed rather than a defect.

    A **separate, deliberately tiny vocabulary**, and not part of
    :class:`BlockerCode`. The specification fixed the blocker list as a closed
    set of things that would be wrong with the route; none of these is one of
    those. Merging them would have made "the maintainer has not activated a
    trial" indistinguishable from "the score is not reproducible", which is
    exactly the confusion the third gate status exists to remove
    (docs/adr/0104).

    Each names something one person can do in an afternoon.
    """

    QUALIFICATION_RUN_NOT_PERFORMED = "QUALIFICATION_RUN_NOT_PERFORMED"
    TRIAL_LICENCE_NOT_ACTIVATED = "TRIAL_LICENCE_NOT_ACTIVATED"
    JAVA_RUNTIME_NOT_AVAILABLE = "JAVA_RUNTIME_NOT_AVAILABLE"
    RUNTIME_PLATFORM_NOT_LOCKED = "RUNTIME_PLATFORM_NOT_LOCKED"


#: The three reasons a qualification run has not happened. Any of them can be the
#: reason for any execution-dependent gate, so they travel together: the gate
#: reports the one that is actually true on this machine, and the harness decides
#: which that is by checking rather than by assuming.
_RUN_NOT_PERFORMED_REASONS: tuple[PendingActionCode, ...] = (
    PendingActionCode.QUALIFICATION_RUN_NOT_PERFORMED,
    PendingActionCode.TRIAL_LICENCE_NOT_ACTIVATED,
    PendingActionCode.JAVA_RUNTIME_NOT_AVAILABLE,
)

#: Which pending actions each gate may report. Every execution-dependent gate
#: shares the run reasons, because one run answers all of them; the platform lock
#: additionally belongs to runtime identity, which is what a platform is part of.
GATE_PENDING_ACTIONS: tuple[tuple[PreflightGate, tuple[PendingActionCode, ...]], ...] = (
    (
        PreflightGate.RUNTIME_IDENTITY,
        (PendingActionCode.RUNTIME_PLATFORM_NOT_LOCKED, *_RUN_NOT_PERFORMED_REASONS),
    ),
    (PreflightGate.EXTRACTION_PROFILE, _RUN_NOT_PERFORMED_REASONS),
    (PreflightGate.MATCHER_PROFILE, _RUN_NOT_PERFORMED_REASONS),
    (PreflightGate.PAIR_ORIENTATION, _RUN_NOT_PERFORMED_REASONS),
    (PreflightGate.SELF_SEMANTICS, _RUN_NOT_PERFORMED_REASONS),
    (PreflightGate.SCORE_DETERMINISM, _RUN_NOT_PERFORMED_REASONS),
    (PreflightGate.FAILURE_SEMANTICS, _RUN_NOT_PERFORMED_REASONS),
    (PreflightGate.RUNTIME_FEASIBILITY, _RUN_NOT_PERFORMED_REASONS),
    (PreflightGate.LICENSE_CAPACITY, _RUN_NOT_PERFORMED_REASONS),
)


def gate_pending_actions(gate: PreflightGate) -> tuple[PendingActionCode, ...]:
    """The pending actions one gate may report, possibly none."""
    for item, codes in GATE_PENDING_ACTIONS:
        if item is gate:
            return codes
    return ()


#: The gates that cannot be answered by reading files, in the order a single
#: qualification run would answer them. Published so that "one run closes nine
#: gates" is a checkable claim rather than an encouraging sentence.
EXECUTION_DEPENDENT_GATES: tuple[PreflightGate, ...] = tuple(
    gate for gate, _ in GATE_PENDING_ACTIONS
)


# --------------------------------------------------------------- vocabularies


class ArtifactRoute(str, Enum):
    """Which distribution the qualification is about. Exactly one (spec section 3).

    The routes are never mixed. A runtime file from the Python distribution
    beside a runtime file from the main SDK would be a route nobody published,
    and the score it produced would belong to neither.
    """

    MAIN_SDK_PACKAGE = "MAIN_SDK_PACKAGE"
    PYTHON_RESEARCH_PACKAGE = "PYTHON_RESEARCH_PACKAGE"
    DOCUMENTATION_BUNDLE = "DOCUMENTATION_BUNDLE"


class AcquisitionStatus(str, Enum):
    """Whether the official artifact was fetched here.

    ``OBTAINED`` requires bytes on this machine whose digest and size were both
    verified. Nothing weaker is an acquisition.
    """

    OBTAINED = "OBTAINED"
    NOT_ATTEMPTED_HERE = "NOT_ATTEMPTED_HERE"
    LOCATOR_UNAVAILABLE = "LOCATOR_UNAVAILABLE"
    REQUIRES_VENDOR_APPROVAL = "REQUIRES_VENDOR_APPROVAL"
    TRANSFER_INCOMPLETE = "TRANSFER_INCOMPLETE"

    @property
    def opens_inspection(self) -> bool:
        return self is AcquisitionStatus.OBTAINED


class PossessionStatus(str, Enum):
    """Whether this project holds the thing. A fact about this project."""

    OBTAINED = "OBTAINED"
    NOT_OBTAINED = "NOT_OBTAINED"


class SettingProvenance(str, Enum):
    """Where a score-affecting setting's value came from (spec section 15).

    Four authorities, all of them upstream. The vocabulary exists so that a value
    can never be recorded without saying who chose it, and so that the one
    forbidden answer has no member to hide behind.
    """

    UPSTREAM_DOCUMENTED_DEFAULT = "UPSTREAM_DOCUMENTED_DEFAULT"
    DELIVERED_RUNTIME_DEFAULT = "DELIVERED_RUNTIME_DEFAULT"
    OFFICIAL_SAMPLE_EXPLICIT = "OFFICIAL_SAMPLE_EXPLICIT"
    UPSTREAM_EXPLICIT_RECOMMENDATION = "UPSTREAM_EXPLICIT_RECOMMENDATION"
    UNRESOLVED = "UNRESOLVED"

    @property
    def is_upstream_authority(self) -> bool:
        return self is not SettingProvenance.UNRESOLVED


#: The one provenance a route called VeriFinger may not carry, kept as a string
#: rather than as an enum member so that no code path can select it (spec
#: section 15).
REFUSED_SETTING_PROVENANCE = "FPBENCH_CHOICE"


class RepresentationType(str, Enum):
    """Which representation the matcher actually compares (spec section 18).

    Interoperable formats are not preferred because they are easier to store.
    The route being qualified is the route upstream defines, and a different
    representation is a different algorithm profile with its own identity.
    """

    VENDOR_PROPRIETARY_TEMPLATE = "VENDOR_PROPRIETARY_TEMPLATE"
    ISO_MINUTIAE_TEMPLATE = "ISO_MINUTIAE_TEMPLATE"
    ANSI_MINUTIAE_TEMPLATE = "ANSI_MINUTIAE_TEMPLATE"
    OTHER_VENDOR_TEMPLATE = "OTHER_VENDOR_TEMPLATE"
    UNRESOLVED = "UNRESOLVED"
    NOT_REACHED = "NOT_REACHED"

    @property
    def admits_candidate(self) -> bool:
        return self not in (
            RepresentationType.UNRESOLVED,
            RepresentationType.NOT_REACHED,
        )


class ScoreRouteStatus(str, Enum):
    """Whether one scalar raw score is available, and of what kind.

    ``NATIVE_TRANSFORMED_SCALAR`` is a pass. A score that is a claimed FAR, a
    log-FAR or a normalised similarity is acceptable precisely as long as it is
    the number upstream's own API returns; what is refused is fpbench converting
    one thing into another (spec section 24).
    """

    NATIVE_SCALAR = "NATIVE_SCALAR"
    NATIVE_TRANSFORMED_SCALAR = "NATIVE_TRANSFORMED_SCALAR"
    BOOLEAN_ONLY = "BOOLEAN_ONLY"
    UNRESOLVED = "UNRESOLVED"
    NOT_REACHED = "NOT_REACHED"

    @property
    def admits_candidate(self) -> bool:
        return self in (
            ScoreRouteStatus.NATIVE_SCALAR,
            ScoreRouteStatus.NATIVE_TRANSFORMED_SCALAR,
        )


class NetworkRole(str, Enum):
    """What the required internet connection is for (spec section 31).

    The distinction decides whether the route is reproducible at all. A licence
    check over the network leaves the algorithm on this machine; a score computed
    on somebody's server can change without one byte moving in the pinned
    package, and that is a reproducibility blocker rather than an inconvenience.
    """

    LICENSE_VALIDATION_ONLY = "LICENSE_VALIDATION_ONLY"
    PARTICIPATES_IN_BIOMETRIC_COMPUTATION = "PARTICIPATES_IN_BIOMETRIC_COMPUTATION"
    UNRESOLVED = "UNRESOLVED"
    NOT_REACHED = "NOT_REACHED"

    @property
    def admits_candidate(self) -> bool:
        return self is NetworkRole.LICENSE_VALIDATION_ONLY


class TrainingProvenanceStatus(str, Enum):
    """What is known about what the shipped algorithm was developed on.

    ``PROPRIETARY_UNDISCLOSED`` is an acceptable answer for a commercial product
    provided the record says so plainly rather than pretending to an absence
    (spec section 37).
    """

    PUBLICLY_DOCUMENTED = "PUBLICLY_DOCUMENTED"
    PARTIALLY_DOCUMENTED = "PARTIALLY_DOCUMENTED"
    PROPRIETARY_UNDISCLOSED = "PROPRIETARY_UNDISCLOSED"
    NOT_REACHED = "NOT_REACHED"


class SD300OverlapStatus(str, Enum):
    """Whether the evaluation cohort appears in the product's development history.

    ``PROVEN_ABSENT`` requires an upstream statement that the dataset was not
    used. Silence is ``NO_EVIDENCE_FOUND``, and the two are never merged
    (spec sections 36 and 37).
    """

    POSITIVE_OVERLAP_FOUND = "POSITIVE_OVERLAP_FOUND"
    NO_EVIDENCE_FOUND = "NO_EVIDENCE_FOUND"
    PROVEN_ABSENT = "PROVEN_ABSENT"
    NOT_REACHED = "NOT_REACHED"

    @property
    def is_automatic_rejection(self) -> bool:
        return self is SD300OverlapStatus.POSITIVE_OVERLAP_FOUND


class FailureClass(str, Enum):
    """What kind of failure a blocked outcome is, in one word.

    Published beside the outcome because ``VERIFINGER_PREFLIGHT_FAIL`` reads the
    same whether the artifact could not be had, its terms forbade the use, or the
    route was inspected and found unqualifiable — and those are very different
    results.
    """

    ARTIFACT_NOT_OBTAINED = "ARTIFACT_NOT_OBTAINED"
    RESEARCH_USE_REFUSED = "RESEARCH_USE_REFUSED"
    ROUTE_NOT_QUALIFIABLE = "ROUTE_NOT_QUALIFIABLE"
    EXECUTION_NOT_ESTABLISHED = "EXECUTION_NOT_ESTABLISHED"
    LICENSE_CAPACITY_INSUFFICIENT = "LICENSE_CAPACITY_INSUFFICIENT"
    SD300_DEVELOPMENT_OVERLAP = "SD300_DEVELOPMENT_OVERLAP"


# ----------------------------------------------------------------- acquisition

#: What must be pinned before a single byte of the artifact is imported
#: (spec section 4). Recorded from the transfer itself, not from a page about it.
ACQUISITION_PIN_FIELDS: tuple[str, ...] = (
    "official locator category",
    "exact filename",
    "byte size",
    "sha256",
    "download date",
    "declared version",
    "target operating system and architecture",
)

#: What never becomes evidence, however convenient it would be (spec section 4).
EXCLUDED_FROM_EVIDENCE: tuple[str, ...] = (
    "signed URLs",
    "tokens",
    "credentials",
    "session cookies",
    "machine or hardware identifiers",
    "licence file bytes",
)

#: What the runtime-identity gate must produce, as far as the route allows
#: (spec section 6). A web page's version number is not on this list, and that is
#: the point: a version read from a page identifies the page.
RUNTIME_IDENTITY_FIELDS: tuple[str, ...] = (
    "product version, as the artifact itself declares it",
    "build or revision identifier",
    "language binding version",
    "native library identities",
    "operating system",
    "architecture",
    "language ABI",
)

#: The transitive closure the artifact gate has to walk (spec section 9). A model
#: that lives outside the archive is an artifact in its own right and needs its
#: own size and digest.
ARTIFACT_CLOSURE_CLASSES: tuple[str, ...] = (
    "embedded models",
    "external model or data files",
    "configuration databases",
    "licence runtime",
    "native dependencies",
)

#: What a model with no separate file is recorded as. Not an omission from the
#: inventory, and not a ``.pth`` this stage would demand from a black-box
#: commercial matcher (spec section 10).
EMBEDDED_MODEL_MARKER = "EMBEDDED_IN_PINNED_VENDOR_ARTIFACT"


# ---------------------------------------------------------------- the benchmark

BENCHMARK_INPUT_PROFILE = "canonical_500"
BENCHMARK_INPUT_PPI = 500
BENCHMARK_INPUT_PIXEL_FORMAT = "gray8"

#: The route this stage wants to prove, in order (spec section 11).
CANONICAL500_REQUIRED_ROUTE: tuple[str, ...] = (
    "canonical_500 PNG",
    "the official VeriFinger image loader",
    "explicit 500 ppi metadata, where the API requires it",
    "official fingerprint extraction",
)

#: What fpbench may not do to an image on the way in (spec section 12), unless
#: the operation is an explicit part of the official route.
REFUSED_PREPROCESSING: tuple[str, ...] = (
    "crop",
    "region-of-interest selection",
    "resize",
    "rotate",
    "enhancement",
    "histogram manipulation",
    "minutiae generation outside VeriFinger",
)

#: Segmentation, alignment and quality processing performed *inside* the pinned
#: SDK, where fpbench has no external choice about it, need no explanation. The
#: requirement is to freeze every behaviour that can be selected from outside —
#: not to know the vendor's mathematics (spec section 13).
INTERNAL_BLACK_BOX_PREPROCESSING_IS_ACCEPTABLE = True

#: The one upstream sample this stage takes settings from, named rather than
#: implied.
#:
#: Upstream ships many tutorials and they do not agree with each other: the
#: enrolment tutorial sets ``FingersTemplateSize`` and the verification tutorial
#: does not, so a profile assembled from both would be a configuration no
#: upstream program has ever run. ``OFFICIAL_SAMPLE_EXPLICIT`` therefore means
#: *this* sample and no other, and a setting the authoritative sample leaves
#: alone is a delivered runtime default to be read — not a value borrowed from a
#: neighbour (docs/adr/0105).
AUTHORITATIVE_ROUTE_SAMPLE = (
    "Tutorials/Biometrics/Java/verify-finger — upstream's own complete 1:1 "
    "verification program, the only sample in the archive that performs the "
    "whole route this benchmark needs"
)

#: What the extractor-profile gate must find values and provenances for
#: (spec section 14). These are the *classes* of setting to look for; the names
#: the 2025.2 package actually publishes are discovered, never assumed.
EXTRACTOR_PROFILE_INVENTORY: tuple[str, ...] = (
    "template type",
    "template size or profile",
    "extraction mode",
    "quality mode",
    "processing speed or accuracy mode",
    "image resolution handling",
    "rotation or alignment options",
    "finger position or type fields",
    "model or profile identifiers",
    "any other extraction flag",
)

#: The matching side of the same inventory (spec section 20).
MATCHER_PROFILE_INVENTORY: tuple[str, ...] = (
    "rotation tolerance",
    "matching mode",
    "normalization",
    "speed or accuracy mode",
    "template compatibility mode",
    "any threshold-related setting",
    "any quality weighting",
)

#: The representations a fingerprint SDK might compare (spec section 18).
REPRESENTATION_CANDIDATES: tuple[str, ...] = (
    "proprietary fingerprint template",
    "ISO template",
    "ANSI template",
    "another vendor template type",
)

#: What may be published about a template, and it is never the template
#: (spec section 19). Representations stay ephemeral.
PUBLISHABLE_REPRESENTATION_FACTS: tuple[str, ...] = (
    "type",
    "format or profile identifier",
    "size metadata, where publishing it is safe",
    "configuration fingerprint",
)


# ------------------------------------------------------- what the score must be

#: What the decisive gate requires of the route (spec sections 21 to 24).
SCORE_CONTRACT_REQUIREMENTS: tuple[str, ...] = (
    "exactly one scalar score per 1:1 attempt, from one chosen comparison API",
    "a stated numeric type",
    "a nominal or defined range, where upstream defines one",
    "a stated direction",
    "stated reference and probe semantics",
    "no threshold already applied inside the number: a route whose only output "
    "is a boolean fails outright, and where a score and a boolean both exist "
    "the raw route takes the score and stops",
    "a transformed native quantity — a claimed FAR, a log-FAR, a normalised "
    "similarity — is acceptable while it is the number upstream returns; "
    "fpbench performs no conversion of its own",
)

#: How the pair-orientation question is settled (spec section 25). Never by
#: averaging and never by taking a maximum: those hide the contract instead of
#: recording it.
PAIR_ORIENTATION_REQUIREMENTS: tuple[str, ...] = (
    "score(A, B) and score(B, A) are both run, on fixtures that are not SD300",
    "if they agree, symmetry is recorded as observed rather than assumed",
    "if they differ, the reference/probe contract is discovered and preserved",
    "fpbench never averages the two and never takes the maximum",
)

#: The SELF rule, frozen here even though the adapter that would obey it belongs
#: to Stage 11B (spec section 26).
SELF_SEMANTICS_REQUIREMENTS: tuple[str, ...] = (
    "SELF(A, A) loads A twice and extracts it twice, independently",
    "the two resulting representations are compared with each other",
    "representation reuse between the two sides is refused",
    "an equal-input shortcut returning a constant is refused",
)

#: The three levels determinism is checked at (spec section 28).
DETERMINISM_LEVELS: tuple[str, ...] = (
    "same objects, same process",
    "fresh objects, same process",
    "fresh process, clean restart",
)

#: Every way the route can fail, each of which must map to an outcome rather than
#: to a number (spec section 30).
FAILURE_SEMANTICS_CLASSES: tuple[str, ...] = (
    "invalid image",
    "unsupported image",
    "missing runtime component",
    "extraction failure",
    "matcher failure",
    "licence or runtime failure",
)

#: The question the network gate has to answer, and the two answers that are not
#: the same answer (spec section 31).
NETWORK_DEPENDENCY_QUESTIONS: tuple[str, ...] = (
    "is the network used for licence validation only?",
    "or does the network participate in the biometric computation?",
    "if a remote service computes any part of the score, can that service be "
    "pinned at all?",
)

#: What runtime feasibility measures, on fixtures, and what it is not
#: (spec section 33). It is not a benchmark and it is not a comparison.
RUNTIME_FEASIBILITY_MEASUREMENTS: tuple[str, ...] = (
    "import or startup cost",
    "end-to-end verification latency, to an order of magnitude",
    "approximate peak memory",
    "CPU or GPU requirement",
)

#: What the feasibility gate measures, and why it is not two numbers.
#:
#: The 1:1 route's only entry point is ``verify(reference, candidate)``, which
#: loads both images, extracts both templates and matches them behind one call.
#: An earlier harness timed the construction of the two ``NSubject`` objects and
#: called it extraction latency; that measured object allocation, because the
#: extraction happens inside ``verify``. There is one honest number here and this
#: is it (spec correction 7).
FEASIBILITY_LATENCY_MEASURE = "end_to_end_verify_latency"

#: What the capacity arithmetic multiplies. The protocol performs 6,000
#: verification attempts; the 12,000 extractions remain the logical execution
#: semantics — two independent extractions per comparison — and are *not* a
#: second thing to bill for, because the route bills per verify call.
FROZEN_VERIFICATION_ATTEMPTS = 6_000

#: The rule that turns an exotic dependency into a refusal rather than a project
#: (spec section 34).
RARE_DEPENDENCY_RULE = (
    "a route that needs an accelerator this project does not have, or a further "
    "proprietary external service that cannot be pinned, is a failure or an "
    "explicit blocker — never something to be worked around"
)

#: What a licence has to answer before its capacity can be called sufficient
#: (spec section 35). Being a trial is not an answer to any of them.
LICENSE_CAPACITY_QUESTIONS: tuple[str, ...] = (
    "when does it expire?",
    "is there an API-call quota, and what is it?",
    "which machines or platforms may it run on?",
    "does it require an internet connection, and how often?",
    "can it complete the whole frozen workload before any of the above bites?",
)


@dataclass(frozen=True, slots=True)
class FrozenWorkload:
    """The complete run a licence and a runtime would have to carry.

    Fixed in advance on purpose. A capacity question asked against a workload
    that can be trimmed later is a capacity question with no answer, and
    "we will see how far it gets" is how a benchmark ends up reporting part of a
    protocol under the protocol's name.
    """

    participating_images: int
    comparison_attempts: int
    extraction_invocations: int
    matcher_invocations: int

    def __post_init__(self) -> None:
        for name in (
            "participating_images",
            "comparison_attempts",
            "extraction_invocations",
            "matcher_invocations",
        ):
            value = int(getattr(self, name))
            if value <= 0:
                raise VeriFingerCandidateIdentityError(
                    f"{name} must be a positive count; a workload with a zero in "
                    "it is a workload nobody has to plan for"
                )
            object.__setattr__(self, name, value)
        if self.extraction_invocations != 2 * self.comparison_attempts:
            raise VeriFingerCandidateIdentityError(
                "each comparison extracts both of its sides independently, so a "
                "run of N comparisons performs 2N extractions. Counting one "
                "extraction per participating image would be counting a "
                "representation cache this project refuses to have: SELF(A, A) "
                "extracts A twice, and every other pair extracts both sides "
                "afresh (docs/adr/0070, spec section 27)"
            )
        if self.matcher_invocations != self.comparison_attempts:
            raise VeriFingerCandidateIdentityError(
                "one matcher invocation per comparison attempt; a run that "
                "matched more or fewer times than it compared would be a "
                "different protocol"
            )


#: The canonical protocol this project has already run three times, expressed in
#: the operations an execution actually performs (spec section 27).
FROZEN_WORKLOAD = FrozenWorkload(
    participating_images=3_000,
    comparison_attempts=6_000,
    extraction_invocations=12_000,
    matcher_invocations=6_000,
)

class ScoreClass(str, Enum):
    """Which kind of number a score is, because the two are not the same object.

    A **qualification score** is produced on a synthetic or vendor-sample fixture
    while proving that the route works: it answers "is this deterministic", "is
    ``score(A,B)`` equal to ``score(B,A)``", "does ``SELF(A,A)`` behave". It is a
    property of the harness, it is never published as a value, and there must be
    thousands of them before a benchmark exists.

    A **benchmark score** is a measurement of the evaluation cohort. Stage 11A
    produces none, ever, and neither does any stage before the algorithm is
    admitted.

    Collapsing the two into one "scores_produced: 0" claim, as an earlier version
    of this marker did, made the qualification run this stage *requires*
    impossible to describe (docs/adr/0104).
    """

    QUALIFICATION_FIXTURE = "QUALIFICATION_FIXTURE"
    BENCHMARK_COHORT = "BENCHMARK_COHORT"

    @property
    def may_be_produced_by_this_stage(self) -> bool:
        return self is ScoreClass.QUALIFICATION_FIXTURE

    @property
    def may_be_published_as_a_value(self) -> bool:
        """Neither may. Counts, equalities and orders of magnitude only."""
        return False


#: What the qualification run must record about the platform it ran on, chosen
#: and locked *at activation* rather than discovered afterwards. The trial is
#: single-platform, so this is a decision taken once; alternating between two
#: platforms under one algorithm fingerprint is refused whichever is chosen.
RUNTIME_PLATFORM_LOCK_FIELDS: tuple[str, ...] = (
    "operating_system",
    "architecture",
    "native_library_directory",
    "native_library_digests",
    "java_runtime_version",
    "java_vendor",
    "locked_utc",
)

#: What one bounded qualification run has to answer, in order. Every item maps to
#: a gate that cannot be answered by reading files, and the run performs all of
#: them or none: a partial record is not a smaller answer, it is an unfinished
#: one.
QUALIFICATION_RUN_STEPS: tuple[str, ...] = (
    "lock the platform and record the native libraries actually loaded",
    "obtain the FingerExtractor and FingerMatcher licences from the local "
    "licensing service",
    "read the library version from the running library",
    "construct the engine and read every published setting's delivered default",
    "extract a template from a synthetic fixture",
    "extract a second template from the same fixture, independently",
    "score both orderings of a fixture pair",
    "score SELF(A, A) as two independent extractions",
    "repeat one pair with the same objects, with fresh objects, and after a "
    "process restart",
    "exercise each failure class and record what it returns",
    "measure startup, end-to-end verification latency and peak memory",
)

#: The bound. A qualification run is small on purpose: it exists to establish a
#: contract, not to measure accuracy, and a harness that drifted towards the
#: benchmark's size would start to look like an unpublished experiment.
QUALIFICATION_RUN_MAX_SCORES = 64

#: Every failure class, with the cause the harness uses to provoke it. A class
#: "checked" by whatever happened to go wrong is not checked; each of these is a
#: deliberate, reproducible cause, and three of them need their own process
#: because they are about a runtime that is missing something.
FAILURE_SEMANTICS_CAUSES: tuple[tuple[str, str], ...] = (
    (
        "invalid image",
        "a file carrying the PNG signature over a body that is not a valid "
        "image, so the decoder is reached and fails",
    ),
    (
        "unsupported image",
        "a file whose bytes are not an image in any container the loader "
        "accepts",
    ),
    (
        "missing runtime component",
        "a second process run against an installation with the fingerprint data "
        "file deliberately withheld, so the engine loads and the algorithm's own "
        "dependency is absent",
    ),
    (
        "extraction failure",
        "a valid, decodable image with no ridge structure at all, so extraction "
        "runs and produces no template",
    ),
    (
        "matcher failure",
        "a comparison whose reference side has no template, so the matcher is "
        "reached with nothing to match",
    ),
    (
        "licence or runtime failure",
        "a third process that deliberately does not obtain the finger licences "
        "before calling the engine",
    ),
)

#: The three passes one qualification performs. Separate processes because two of
#: the failure classes are about a runtime that is *missing* something, and a
#: process cannot un-load a data file it has already loaded.
QUALIFICATION_PASSES: tuple[tuple[str, str], ...] = (
    ("full", "the licensed route, on the complete installation"),
    ("restart", "the same route again, to settle the fresh-process determinism level"),
    ("no-models", "the licensed route against an installation missing Fingers.ndf"),
    ("no-licence", "the complete installation, with no licence obtained"),
)

#: What the run's identity is computed over (spec correction 3). A record that
#: cannot say which bytes produced it is a record about nothing in particular,
#: and every one of these can change a score.
QUALIFICATION_RUN_INPUT_COMPONENTS: tuple[str, ...] = (
    "the pinned SDK archive",
    "every native library, binding jar and data file actually loaded",
    "the Java harness source",
    "the Python qualification driver source",
    "the fixture generator version",
)

#: Bumped whenever the synthetic fixtures change in any way that could move a
#: score. It is part of the run's identity, so a record produced against older
#: fixtures does not silently answer for newer ones.
FIXTURE_VERSION = "1"


class QualificationOutcome(str, Enum):
    """How a qualification run ended, and it is not the same as whether it passed.

    ``COMPLETED`` means every step ran and the record carries their answers.
    ``FAILED`` means the runtime started and something went wrong afterwards —
    which is a **real observed blocker**, not a return to "nobody has run it".
    A harness whose failure looked the same as its absence could never move this
    stage off ``INCOMPLETE`` (spec correction 5).
    """

    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

    @property
    def is_a_finding(self) -> bool:
        return True

    @property
    def answers_execution_gates(self) -> bool:
        return self is QualificationOutcome.COMPLETED


#: The marker a delivered default carries when the engine would not report it.
#: Counted as unresolved wherever a value is required: a setting nobody could
#: read is exactly as unfrozen as a setting nobody looked for, and treating the
#: string as a value would let an unreadable profile pass (spec correction 2).
UNREADABLE_SETTING_PREFIX = "UNREADABLE:"


def setting_value_is_resolved(value: object) -> bool:
    """Whether a delivered-default reading actually settled anything."""
    if not isinstance(value, str) or not value.strip():
        return False
    return not value.startswith(UNREADABLE_SETTING_PREFIX)


#: What may be put through the route before the candidate passes
#: (spec section 39).
FIXTURE_POLICY: tuple[str, ...] = (
    "synthetic ridge-like fixtures generated into a temporary directory",
    "an official vendor sample fingerprint shipped inside the pinned artifact, "
    "if a synthetic fixture will not extract",
    "a vendor sample stays in the local artifact store and never enters Git "
    "while its redistribution terms are anything but clear",
)

#: The three denials the marker carries about the evaluation cohort
#: (spec section 40). Not one image, not one pair, not one score.
SD300_DENIALS: tuple[str, ...] = (
    "sd300_image_bytes_read",
    "sd300_pair_manifest_read",
    "sd300_scores_read",
)

#: The conjunction that admits the candidate (spec section 48). Conjunctive and
#: unweighted: there is no arrangement of fifteen conditions in which fourteen
#: are enough.
ACCEPTANCE_CONDITIONS: tuple[str, ...] = (
    "official artifact obtained",
    "exact package identity pinned",
    "Stage 8E permits execution",
    "complete runtime dependency closure",
    "canonical_500 route resolved",
    "extractor profile resolved",
    "representation profile resolved",
    "matcher profile resolved",
    "raw scalar score resolved",
    "SELF semantics demonstrated",
    "pair orientation resolved",
    "restart determinism demonstrated",
    "workload, runtime and licence feasible",
    "no positive SD300 development overlap",
    "no SD300 consulted",
)


# -------------------------------------------------------------- what is not done

NON_GOALS: tuple[str, ...] = (
    "no production adapter",
    "no configs/algorithms/verifinger configuration",
    "no generic-engine adapter",
    "no ResultSet",
    "no 6,000-comparison runner",
    "no threshold",
    "no DecisionProfile",
    "no calibration",
    "no metrics",
    "no SD300 read of any kind, including one image to see whether it works",
    "no licence activation in CI and no credentials in CI",
    "no selection of a preset from score distributions or vendor-reported "
    "accuracy",
)

#: The production surfaces this stage does not create, named individually so a
#: reviewer can check for each one rather than trusting a sentence
#: (spec section 41).
PRODUCTION_INTEGRATION_NOT_CREATED: tuple[str, ...] = (
    "algorithm_config",
    "generic_engine_adapter",
    "production_adapter",
    "comparison_runner",
    "result_set",
    "threshold",
    "decision_profile",
    "calibration",
    "metrics",
)

#: What a passing Stage 11A would open, named here so that the boundary between
#: qualification and integration is written down before either happens
#: (spec section 50).
STAGE_11B_SCOPE: tuple[str, ...] = (
    "VeriFinger production integration",
    "the generic adapter",
    "runtime qualification",
    "a frozen AlgorithmConfig",
    "raw-score execution readiness",
    "and still no threshold and no calibration",
)


# ------------------------------------------------------------ what is publishable

#: Keys the finalization verifier refuses at any depth of any published document.
#: Not a warning and not a redaction: the publisher stops (spec section 43).
SENSITIVE_EVIDENCE_KEYS: frozenset[str] = frozenset(
    {
        "password",
        "passphrase",
        "secret",
        "activation_key",
        "activationkey",
        "activation_id",
        "serial_number",
        "serial",
        "serialnumber",
        "license_key",
        "licence_key",
        "license_bytes",
        "licence_bytes",
        "license_file_bytes",
        "license_buffer",
        "hardware_code",
        "hardwarecode",
        "machine_id",
        "machineid",
        "device_id",
        "deviceid",
        "computer_id",
        "customer_id",
        "customer_login",
        "account_id",
        "signed_url",
        "presigned_url",
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
#: every published string. Written as regular-expression *sources* rather than
#: compiled patterns so this module stays a table of constants and the engine
#: owns the compilation.
SENSITIVE_VALUE_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        "neurotechnology_serial_shape",
        r"\b[A-Za-z0-9]{4}-[A-Za-z0-9]{4}-[A-Za-z0-9]{4}-[A-Za-z0-9]{4}\b",
    ),
    (
        "uuid_shape",
        r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{12}\b",
    ),
    ("bearer_token_shape", r"\bBearer\s+[A-Za-z0-9._\-]{16,}\b"),
    ("private_key_block", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ("basic_auth_in_locator", r"://[^/\s:@]+:[^/\s@]+@"),
    (
        "signed_url_query",
        r"[?&](X-Amz-Signature|Signature|Expires|token|access_key)=",
    ),
    ("long_base64_blob", r"\b[A-Za-z0-9+/]{120,}={0,2}\b"),
)

#: Refused at any depth of a published Stage 11A document, in addition to the
#: sensitive keys above. Each one would mean an upstream byte, a template, a
#: fingerprint image, a score or a machine-specific path had reached the evidence
#: of a stage whose entire subject is that none of them do.
#:
#: As in Stage 8E, 9A, 10A and 10B, no member may be a value of a published
#: vocabulary: these documents count things into maps keyed by enum value, so a
#: forbidden key named ``source_code`` would refuse a count of source-code
#: components rather than a body of source code.
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
# Stage 11A reads two published markers and edits neither. Stage 10B is its
# predecessor and stays immutable; Stage 8E owns third-party policy and Stage 11A
# adds no licensing subsystem of its own.

#: Stage 10B as re-closed over its final corrections. Binding the fingerprint
#: rather than the directory is what makes "Stage 10B was not edited" checkable
#: instead of asserted.
STAGE_10B_FINALIZATION_FINGERPRINT = (
    "48bf4a9b745bec9d73607152561249f6e5981c7053fca4adfd78c15acb23697a"
)
STAGE_10B_OUTCOME = "ID3_FINGER_SDK_PREFLIGHT_FAIL"

#: Assembled from parts rather than written out, for the reason Stage 8C, 8D, 8E,
#: 9A, 10A and 10B assemble theirs: Stage 11A's own source is audited for
#: literals that name another stage's published evidence, and a written-out path
#: here would make the audit refuse the module that performs it.
STAGE_10B_EVIDENCE_DIRECTORY = "/".join(
    ("evidence", "stage10b-" + "id3-finger-sdk-preflight")
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

#: Where the store keeps Stage 11A's artifacts, relative to
#: ``FPBENCH_THIRD_PARTY_ROOT``. Manifests hold no absolute path and this is not
#: a place on any machine (docs/adr/0083).
ARTIFACT_STORE_PREFIX = "verifinger-2025-2"

#: The pytest marker for tests that need the artifact on this machine. They are
#: not part of the public CI, which downloads nothing (spec section 42).
VERIFINGER_ARTIFACT_MARKER = "verifinger_artifact"


# --------------------------------------------------------------- the source set

STAGE_11A_SOURCE_FILES: tuple[str, ...] = (
    "src/fpbench/core/verifinger_preflight_errors.py",
    "src/fpbench/experiments/stage11a_verifinger_identity.py",
    "src/fpbench/experiments/stage11a_verifinger_observations.py",
    "src/fpbench/experiments/stage11a_artifacts.py",
    "src/fpbench/experiments/stage11a_qualification.py",
    "src/fpbench/experiments/stage11a_preflight.py",
    "src/fpbench/experiments/stage11a_finalization.py",
)

STAGE_11A_ADRS: tuple[str, ...] = (
    "docs/adr/0099-stage-11a-qualifies-verifinger-from-the-artifact-itself.md",
    "docs/adr/0100-preflight-acquires-when-upstream-publishes-a-direct-locator.md",
    "docs/adr/0101-every-score-affecting-setting-carries-an-upstream-provenance.md",
    "docs/adr/0102-a-native-transformed-score-is-a-raw-score.md",
    "docs/adr/0103-network-for-licensing-is-not-network-in-the-computation.md",
    (
        "docs/adr/0104-a-preflight-that-was-not-run-is-not-a-preflight-that-"
        "failed.md"
    ),
    "docs/adr/0105-one-upstream-sample-is-the-route-not-several.md",
    (
        "docs/adr/0106-the-qualification-harness-must-be-able-to-reach-pass.md"
    ),
)

#: The qualification harness lives in the repository and is reviewable; the
#: bytes it drives never do.
QUALIFICATION_HARNESS_SOURCE = (
    "integrations/verifinger-qualification/VeriFingerQualification.java"
)

STAGE_11A_DOCUMENTS: tuple[str, ...] = (
    "docs/experiments/stage11a-verifinger-2025_2-preflight.md",
    "docs/algorithms/algorithm4-candidates/verifinger-2025-2.md",
)


def all_frozen_identifiers() -> tuple[str, ...]:
    """Every Stage 11A identifier, validated as a safe path and key component."""
    identifiers = (
        STAGE_FINALIZATION_KIND,
        ALGORITHM_SLOT,
        CANDIDATE_ID,
        ARTIFACT_STORE_PREFIX.replace("-", "_"),
        VERIFINGER_ARTIFACT_MARKER,
        REFUSED_SETTING_PROVENANCE.lower(),
        *(name for name, _ in DECLARED_NON_CANDIDATES),
        *PRODUCTION_INTEGRATION_NOT_CREATED,
        *SD300_DENIALS,
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
        raise VeriFingerCandidateIdentityError(
            f"two gates report through the same document: {duplicates}"
        )
    unknown = sorted(set(seen) - set(REQUIRED_EVIDENCE_FILES))
    if unknown:  # pragma: no cover - a constant-table mistake
        raise VeriFingerCandidateIdentityError(
            f"a gate reports through a document nothing publishes: {unknown}"
        )
    covered = tuple(gate for gate, _ in GATE_DOCUMENTS)
    if covered != GATE_ORDER:  # pragma: no cover - a constant-table mistake
        raise VeriFingerCandidateIdentityError(
            "the gate-document table and the gate order disagree"
        )
    blocked = tuple(gate for gate, _ in GATE_BLOCKERS)
    if blocked != GATE_ORDER:  # pragma: no cover - a constant-table mistake
        raise VeriFingerCandidateIdentityError(
            "the gate-blocker table and the gate order disagree"
        )
    orphans = sorted(
        code.value for code in BlockerCode if not gate_of_blocker(code)
    )
    if orphans:  # pragma: no cover - a constant-table mistake
        raise VeriFingerCandidateIdentityError(
            f"blocker codes belong to no gate: {orphans}"
        )
    pending_orphans = sorted(
        code.value
        for code in PendingActionCode
        if not any(code in codes for _, codes in GATE_PENDING_ACTIONS)
    )
    if pending_orphans:  # pragma: no cover - a constant-table mistake
        raise VeriFingerCandidateIdentityError(
            f"pending-action codes belong to no gate: {pending_orphans}"
        )
    shared = {code.value for code in BlockerCode} & {
        code.value for code in PendingActionCode
    }
    if shared:  # pragma: no cover - a constant-table mistake
        raise VeriFingerCandidateIdentityError(
            "a code is both a blocker and a pending action, which would make a "
            f"deed indistinguishable from a defect: {sorted(shared)}"
        )
    unknown_gates = sorted(
        gate.value for gate, _ in GATE_PENDING_ACTIONS if gate not in GATE_ORDER
    )
    if unknown_gates:  # pragma: no cover - a constant-table mistake
        raise VeriFingerCandidateIdentityError(
            f"pending actions are attached to gates nothing runs: {unknown_gates}"
        )


def _require_evidence_paths_are_plain() -> None:
    """No published name escapes the evidence directory."""
    for name in REQUIRED_EVIDENCE_FILES:
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or len(path.parts) != 1:
            raise VeriFingerCandidateIdentityError(  # pragma: no cover - constants
                f"{name!r} is not a plain file name below the evidence directory"
            )


def _require_refused_provenance_is_not_a_member() -> None:
    """``FPBENCH_CHOICE`` must not be selectable as a provenance."""
    if REFUSED_SETTING_PROVENANCE in {item.value for item in SettingProvenance}:
        raise VeriFingerCandidateIdentityError(  # pragma: no cover - constants
            "FPBENCH_CHOICE is a member of the provenance vocabulary, which "
            "would make the one refused answer selectable (spec section 15)"
        )


_require_no_duplicate_documents()
_require_evidence_paths_are_plain()
_require_refused_provenance_is_not_a_member()
