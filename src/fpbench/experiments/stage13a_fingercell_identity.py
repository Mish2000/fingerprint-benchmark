"""Everything Stage 13A froze before it loaded a FingerCell runtime.

These constants are the stage's contract with itself: the one candidate, the ten
hard gates and the order they run in, the four gate states and the distinction
between "nobody has done this yet" and "somebody did it and it broke", the closed
blocker and required-action vocabularies, the three outcomes, the provenance a
score-affecting setting must carry, the frozen workload, the conjunction that
admits the candidate, and the keys no published document may ever carry. They are
asserted by the contract suite, republished in the finalization, and a later
change to any of them is a different preflight rather than a quiet correction to
this one.

Stage 13A asks one question:

.. code-block:: text

    does the official FingerCell 3.3 SDK trial Neurotechnology publishes today
    give fpbench a complete, reproducible and upstream-authoritative route from
    canonical_500 to a native raw 1:1 similarity score, without fpbench inventing
    preprocessing, parameter tuning, merging, thresholding or a score
    transformation?

**Acquisition is self-service, so there is no vendor state.** Stage 12A needed
``PENDING_ACCESS`` because an Innovatrics representative had to answer an email
before anything else could happen. Neurotechnology publishes a direct trial
download, so every question this stage asks is one this project can answer for
itself. What replaces ``PENDING`` is :data:`GateStatus.ACTION_REQUIRED`, and it
means something narrower and much more useful: *this project has not performed
the local action yet* (docs/adr/0112).

**The artifact is the authority, not the specification that asked for it.** The
values below that describe FingerCell were read out of the delivered archive —
``Revision.txt``, ``Include/FingerCell.h``, ``Include/FingerCell.hpp``, the
shipped tutorials and the delivered licence agreement — and not out of a product
page. Where a public page and the archive disagree, the archive wins
(docs/adr/0113).

**Stage 12A, Stage 11B and Stage 8E are not re-opened.** Stage 12A closed as
``IDKIT_PREFLIGHT_FAIL`` on a vendor refusal and is bound here as the exact
predecessor. Stage 11B published 6,000 canonical raw outcomes under Algorithm 4
and stays immutable. Stage 8E owns third-party policy and Stage 13A adds no
licensing subsystem of its own.

Nothing here is derived at import time, nothing reads a workspace, nothing
downloads anything, and nothing is a fingerprint image, a score, a template, a
licence byte or a credential.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath

from fpbench.core.fingercell_preflight_errors import FingerCellCandidateIdentityError
from fpbench.core.identifiers import validate_id

__all__ = [
    "STAGE_13A_SCHEMA_VERSION",
    "STAGE_FINALIZATION_KIND",
    "ALGORITHM_SLOT",
    "STAGE_13A_PASS_OUTCOME",
    "STAGE_13A_FAIL_OUTCOME",
    "STAGE_13A_INCOMPLETE_OUTCOME",
    "STAGE_13A_OUTCOMES",
    "STAGE_13A_FINAL_OUTCOMES",
    "CANDIDATE_ID",
    "IMPLEMENTATION_ORIGIN",
    "PRODUCT_FAMILY",
    "DECLARED_PRODUCT_VERSION",
    "PRODUCTION_ALGORITHM_ID_FROZEN",
    "VENDOR_PRODUCT_REVISION_INDICATION",
    "VENDOR_REVISION_HASH_INDICATION",
    "VENDOR_REVISION_HASH_IS_NOT_A_DIGEST",
    "FINAL_IDENTITY_COMPONENTS",
    "EVIDENCE_DIRECTORY",
    "README_NAME",
    "PREDECESSOR_BINDING_NAME",
    "ACQUISITION_MANIFEST_NAME",
    "PACKAGE_RUNTIME_IDENTITY_NAME",
    "RESEARCH_USE_TRIAL_NAME",
    "INPUT_ROUTE_NAME",
    "EXTRACTION_PROFILE_NAME",
    "SCORE_CONTRACT_NAME",
    "SETTINGS_CLOSURE_NAME",
    "QUALIFICATION_RUN_NAME",
    "WORKLOAD_FEASIBILITY_NAME",
    "TRAINING_PROVENANCE_NAME",
    "PREFLIGHT_REPORT_NAME",
    "STAGE_13A_FINALIZATION_NAME",
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
    "RequiredAction",
    "GATE_ACTIONS",
    "gate_of_action",
    "LocatorCategory",
    "REFUSED_ACQUISITION_SOURCES",
    "TOKENIZED_LOCATORS_ARE_NOT_PINNED",
    "ARTIFACT_EVIDENCE_FIELDS",
    "ACQUISITION_PASS_CONDITIONS",
    "ProductFamily",
    "REFUSED_PRODUCT_FAMILIES",
    "PACKAGE_IDENTITY_FIELDS",
    "RUNTIME_COMPONENT_FIELDS",
    "RUNTIME_COMPONENT_ROLES",
    "RUNTIME_COMPONENTS_TO_LOOK_FOR",
    "RUNTIME_CLOSURE_IS_NOT_INHERITED_FROM_A_SIBLING",
    "Binding",
    "BINDING_SELECTION_CRITERIA",
    "BINDING_PREFERENCE_IS_NOT_A_REQUIREMENT",
    "BINDINGS_ARE_NOT_MIXED",
    "VERIFINGER_ALGORITHM_COMPONENTS",
    "PERMITTED_COMMON_RUNTIME_COMPONENTS",
    "CONTAMINATION_CLAIMS_TO_PROVE",
    "TrialStartSemantics",
    "TRIAL_QUESTIONS",
    "LICENSE_SEPARATED_QUESTIONS",
    "SAME_VENDOR_LICENSING_ISOLATION",
    "REFUSED_LICENSE_ACTIONS",
    "BENCHMARK_INPUT_PROFILE",
    "BENCHMARK_INPUT_PPI",
    "BENCHMARK_INPUT_PIXEL_FORMAT",
    "IDEAL_INPUT_ROUTE",
    "PERMITTED_DECODE_ROUTE",
    "DECODE_EQUIVALENCE_REQUIREMENTS",
    "REFUSED_PREPROCESSING",
    "INTERNAL_BLACK_BOX_PREPROCESSING_IS_ACCEPTABLE",
    "REQUIRED_INPUT_PPI",
    "PPI_MUST_BE_EFFECTIVE_AT_EXTRACTION",
    "EMBEDDED_BENCHMARK_SAMPLE_DIMENSIONS",
    "SAMPLE_DIMENSIONS_ARE_NOT_A_PREPROCESSING_RULE",
    "TemplateFormat",
    "REQUIRED_TEMPLATE_FORMAT",
    "REFUSED_TEMPLATE_CONSTRUCTIONS",
    "SINGLE_FINGER_RULE",
    "EXTRACTION_ROUTE",
    "QUALITY_REJECTION_IS_PART_OF_THE_ALGORITHM",
    "REFUSED_QUALITY_THRESHOLD_TUNING",
    "SettingProvenance",
    "REFUSED_SETTING_PROVENANCE",
    "SETTINGS_TO_CLOSE",
    "SETTINGS_LIST_IS_NOT_EXHAUSTIVE",
    "SETTINGS_CLOSURE_COVERS_EXTERNALLY_SELECTABLE_VALUES_ONLY",
    "SETTING_DISCOVERY_SURFACES",
    "SETTING_ROW_FIELDS",
    "SETTINGS_ARE_READ_BEFORE_THEY_ARE_SET",
    "MATCHING_ALGORITHM_EXPECTED_VALUE",
    "MATCHING_ALGORITHM_IS_NOT_FORCED_SILENTLY",
    "ScoreRouteStatus",
    "SCORE_CONTRACT_REQUIREMENTS",
    "SCORE_NATIVE_TYPE",
    "SCORE_DIRECTION",
    "SCORE_RANGE_IS_NOT_ASSUMED",
    "INSUFFICIENT_SCORE_SHAPES",
    "FPBENCH_SCORE_TRANSFORMATION",
    "REFUSED_SCORE_TRANSFORMATIONS",
    "THRESHOLD_PRODUCED",
    "DECISION_PRODUCED",
    "CALIBRATION_PERFORMED",
    "PAIR_ROLE_BINDING",
    "PAIR_ORIENTATION_REQUIREMENTS",
    "REFUSED_ORIENTATION_REDUCTIONS",
    "PAIR_LABELS_ARE_NOT_COPIED_FROM_ANOTHER_CANDIDATE",
    "SELF_SEMANTICS_REQUIREMENTS",
    "TEMPLATE_CACHE_PERMITTED",
    "DETERMINISM_LEVELS",
    "DETERMINISM_REQUIREMENT",
    "MANDATORY_FAILURE_PROBES",
    "OPTIONAL_FAILURE_PROBES",
    "MANDATORY_FAILURE_PROBE_COUNT",
    "FAILURE_SEMANTICS_RULE",
    "FAILED_QUALIFICATION_IS_KEPT",
    "QUALIFICATION_PASSES",
    "QUALIFICATION_MAX_SCORING_COMPARISONS",
    "QUALIFICATION_FIXTURE_SOURCES",
    "QualificationOutcome",
    "QUALIFICATION_RECORD_NAME",
    "QUALIFICATION_RECORD_SCHEMA",
    "SETTINGS_CONTRACT_VERSION",
    "QUALIFICATION_RECORD_BINDING_FIELDS",
    "QUALIFICATION_RECORD_BINDING_IS_MANDATORY_FOR_A_REAL_RUN",
    "FROZEN_COMPARISON_ATTEMPTS",
    "FROZEN_INDEPENDENT_EXTRACTIONS",
    "FROZEN_MATCHER_INVOCATIONS",
    "FrozenWorkload",
    "FROZEN_WORKLOAD",
    "TRIAL_CAPACITY_QUESTIONS",
    "QuotaSchema",
    "UNRESOLVED_QUOTA_BLOCKS_PASS",
    "RUNTIME_TIMING_MEASUREMENTS",
    "VENDOR_EMBEDDED_FIGURES_ARE_NOT_A_PC_ESTIMATE",
    "TrainingProvenanceStatus",
    "SD300OverlapStatus",
    "SD300_OVERLAP_SURFACES",
    "SD300_SEARCH_TERMS",
    "FailureClass",
    "FORBIDDEN_READS",
    "NON_GOALS",
    "PRODUCTION_INTEGRATION_NOT_CREATED",
    "PERMITTED_CONSTRUCTIONS",
    "CI_MUST_NOT",
    "CI_MAY",
    "ACCEPTANCE_CONDITIONS",
    "SENSITIVE_EVIDENCE_KEYS",
    "SENSITIVE_VALUE_PATTERNS",
    "FORBIDDEN_PUBLISHED_KEYS",
    "PUBLISHED_PATHS_ARE_RELATIVE",
    "STAGE_12A_OUTCOME",
    "STAGE_12A_FAILURE_CLASS",
    "STAGE_12A_FINALIZATION_FINGERPRINT",
    "STAGE_12A_EVIDENCE_DIRECTORY",
    "STAGE_11B_OUTCOME",
    "STAGE_11B_FINALIZATION_FINGERPRINT",
    "STAGE8E_FINALIZATION_FINGERPRINT",
    "STAGE8E_OUTCOME",
    "STAGE8E_PURPOSE_FINGERPRINT",
    "STAGE8E_POLICY_FINGERPRINT",
    "ARTIFACT_STORE_PREFIX",
    "STAGE_13A_SOURCE_FILES",
    "all_frozen_identifiers",
]

STAGE_13A_SCHEMA_VERSION = "1"
STAGE_FINALIZATION_KIND = "stage_13a_finalization"

#: The slot this candidate would occupy. Algorithm 4 is VeriFinger 2025.2, taken
#: by Stage 11A and filled with 6,000 canonical raw outcomes by Stage 11B. Stage
#: 12A opened this slot and failed to fill it; this is the next attempt at it.
ALGORITHM_SLOT = "algorithm_5"


# ---------------------------------------------------------------- the outcomes

#: The route qualified. Every gate passed against the delivered trial.
STAGE_13A_PASS_OUTCOME = "FINGERCELL_PREFLIGHT_PASS"

#: A real blocker was observed. An action was performed and it exposed something
#: about the route, the archive or the trial that makes FingerCell unusable as a
#: benchmark algorithm, and a named blocker says which.
STAGE_13A_FAIL_OUTCOME = "FINGERCELL_PREFLIGHT_FAIL"

#: The preflight has not been carried out to the end. Not a verdict about
#: FingerCell and not a defect in it: a local action this project can perform has
#: not been performed yet. No finalization marker is written under this outcome
#: (docs/adr/0112).
STAGE_13A_INCOMPLETE_OUTCOME = "FINGERCELL_PREFLIGHT_INCOMPLETE"

STAGE_13A_OUTCOMES: tuple[str, ...] = (
    STAGE_13A_PASS_OUTCOME,
    STAGE_13A_FAIL_OUTCOME,
    STAGE_13A_INCOMPLETE_OUTCOME,
)

#: The two outcomes a marker may carry. ``INCOMPLETE`` is deliberately absent: a
#: marker is a finalization, and there is nothing final about a job half done.
STAGE_13A_FINAL_OUTCOMES: tuple[str, ...] = (
    STAGE_13A_PASS_OUTCOME,
    STAGE_13A_FAIL_OUTCOME,
)


# --------------------------------------------------------------- the candidate

CANDIDATE_ID = validate_id("neurotechnology_fingercell_3_3_1to1")

#: Where the implementation comes from. The same value Stage 11A and Stage 12A
#: used, carrying the same obligation: the vendor's own channel, never a mirror.
IMPLEMENTATION_ORIGIN = "VENDOR_OFFICIAL_SDK"

#: The product family, fixed upstream. Unlike Stage 12A's version — which had to
#: stay unresolved because no package existed — FingerCell 3.3 is a product and
#: version Neurotechnology publishes and ships under that name.
PRODUCT_FAMILY = "FingerCell"
DECLARED_PRODUCT_VERSION = "3.3"

#: Whether a production algorithm id may be minted from this stage. It may not.
#: A benchmark algorithm id pins a version, a platform and a settings profile,
#: and minting one here would make Stage 13B a formality rather than a decision.
PRODUCTION_ALGORITHM_ID_FROZEN = False

#: What the vendor's release notes said to look for, and nothing more. The
#: delivered ``Revision.txt`` is what settles both, and the preflight compares the
#: two rather than trusting either alone.
VENDOR_PRODUCT_REVISION_INDICATION = "20211013"
VENDOR_REVISION_HASH_INDICATION = "394e593011b1b1dca288371e0af499198f4a77d1"

#: The one confusion this pair invites. The revision hash is 40 hexadecimal
#: characters and looks exactly like something a person might paste into a
#: ``sha256`` field. It is the vendor's own source-revision identifier, it is not
#: a digest of anything this project holds, and it can never stand in for the
#: SHA-256 of the archive (docs/adr/0113).
VENDOR_REVISION_HASH_IS_NOT_A_DIGEST = True

#: What a final algorithm identity has to name. Every one is a property of the
#: delivered archive or of a runtime observed loading it.
FINAL_IDENTITY_COMPONENTS: tuple[str, ...] = (
    "product",
    "product_version",
    "product_revision",
    "archive_sha256",
    "platform",
    "architecture",
    "selected_binding",
    "binding_version",
    "runtime_closure_fingerprint",
    "settings_profile_fingerprint",
)


# ------------------------------------------------------------------- evidence

#: Assembled from parts for the reason every stage since 8C assembles its own
#: name: this module's source is audited for literals that name published
#: evidence, and the audit has to be able to tell "my own directory" from
#: "somebody else's".
EVIDENCE_DIRECTORY = Path("evidence") / ("stage13a-" + "fingercell-preflight")

README_NAME = "README.md"
PREDECESSOR_BINDING_NAME = "predecessor-binding.json"
ACQUISITION_MANIFEST_NAME = "acquisition-manifest.json"
PACKAGE_RUNTIME_IDENTITY_NAME = "package-runtime-identity.json"
RESEARCH_USE_TRIAL_NAME = "research-use-trial.json"
INPUT_ROUTE_NAME = "input-route.json"
EXTRACTION_PROFILE_NAME = "extraction-profile.json"
SCORE_CONTRACT_NAME = "score-contract.json"
SETTINGS_CLOSURE_NAME = "settings-closure.json"
QUALIFICATION_RUN_NAME = "qualification-run.json"
WORKLOAD_FEASIBILITY_NAME = "workload-feasibility.json"
TRAINING_PROVENANCE_NAME = "training-provenance.json"
PREFLIGHT_REPORT_NAME = "preflight-report.json"
STAGE_13A_FINALIZATION_NAME = "stage-13a-finalization.json"

#: Thirteen documents and a README. One document per gate, plus the predecessor
#: binding and the report, plus a marker that exists only under a final outcome.
#: Thirteen small files rather than four large ones, because each answers exactly
#: one question and a reader can check one without reading the others.
REQUIRED_EVIDENCE_FILES: tuple[str, ...] = (
    README_NAME,
    PREDECESSOR_BINDING_NAME,
    ACQUISITION_MANIFEST_NAME,
    PACKAGE_RUNTIME_IDENTITY_NAME,
    RESEARCH_USE_TRIAL_NAME,
    INPUT_ROUTE_NAME,
    EXTRACTION_PROFILE_NAME,
    SCORE_CONTRACT_NAME,
    SETTINGS_CLOSURE_NAME,
    QUALIFICATION_RUN_NAME,
    WORKLOAD_FEASIBILITY_NAME,
    TRAINING_PROVENANCE_NAME,
    PREFLIGHT_REPORT_NAME,
    STAGE_13A_FINALIZATION_NAME,
)

#: What the engine derives. The README is written by hand and the marker is
#: derived against the committed bytes of everything else, so neither is here.
DERIVABLE_EVIDENCE_FILES: tuple[str, ...] = tuple(
    name
    for name in REQUIRED_EVIDENCE_FILES
    if name not in (README_NAME, STAGE_13A_FINALIZATION_NAME)
)


# --------------------------------------------------------------- the ten gates


class PreflightGate(str, Enum):
    """The ten hard gates. Every one of them is mandatory.

    The order is the design. Acquisition is first because every later question is
    a question about a delivered archive. Identity comes before the licence
    because running the wrong product under a valid licence is worse than not
    running at all. The raw score comes before workload and provenance because a
    route with no scalar score is not worth measuring.
    """

    OFFICIAL_ARTIFACT_ACQUISITION = "OFFICIAL_ARTIFACT_ACQUISITION"
    PACKAGE_RUNTIME_IDENTITY = "PACKAGE_RUNTIME_IDENTITY"
    RESEARCH_USE_AND_TRIAL_OPERATION = "RESEARCH_USE_AND_TRIAL_OPERATION"
    CANONICAL500_INPUT_ROUTE = "CANONICAL500_INPUT_ROUTE"
    SINGLE_FINGER_EXTRACTION_PROFILE = "SINGLE_FINGER_EXTRACTION_PROFILE"
    RAW_1TO1_SCORE_CONTRACT = "RAW_1TO1_SCORE_CONTRACT"
    SCORE_AFFECTING_SETTINGS_CLOSURE = "SCORE_AFFECTING_SETTINGS_CLOSURE"
    PAIR_SELF_DETERMINISM_FAILURES = "PAIR_SELF_DETERMINISM_FAILURES"
    FULL_WORKLOAD_FEASIBILITY = "FULL_WORKLOAD_FEASIBILITY"
    TRAINING_PROVENANCE = "TRAINING_PROVENANCE"


GATE_ORDER: tuple[PreflightGate, ...] = (
    PreflightGate.OFFICIAL_ARTIFACT_ACQUISITION,
    PreflightGate.PACKAGE_RUNTIME_IDENTITY,
    PreflightGate.RESEARCH_USE_AND_TRIAL_OPERATION,
    PreflightGate.CANONICAL500_INPUT_ROUTE,
    PreflightGate.SINGLE_FINGER_EXTRACTION_PROFILE,
    PreflightGate.RAW_1TO1_SCORE_CONTRACT,
    PreflightGate.SCORE_AFFECTING_SETTINGS_CLOSURE,
    PreflightGate.PAIR_SELF_DETERMINISM_FAILURES,
    PreflightGate.FULL_WORKLOAD_FEASIBILITY,
    PreflightGate.TRAINING_PROVENANCE,
)

GATE_COUNT = len(GATE_ORDER)


class GateStatus(str, Enum):
    """What one gate concluded.

    The distinction between ``FAIL`` and ``ACTION_REQUIRED`` is carried from this
    stage's first day rather than discovered late, and it is the whole reason
    this vocabulary differs from Stage 12A's:

    .. code-block:: text

        local action not yet performed
            -> ACTION_REQUIRED

        action actually performed and exposed an incompatibility
            -> FAIL

    ``ACTION_REQUIRED`` is not a final outcome, produces no finalization marker,
    and says nothing whatever about FingerCell. Unlike Stage 12A's ``PENDING`` it
    is available at every gate, because every gate here is a question this
    project answers for itself and any of them can be the one not yet reached by
    real work (docs/adr/0112).

    **Only a ``FAIL`` stops the run** (docs/adr/0104). A gate awaiting an action
    is recorded and the run continues, because these gates do not all depend on
    each other: the training-provenance search needs no runtime at all, and
    hiding it behind an uncompiled bridge would let one unpaid chore conceal nine
    later answers. What the run produces while incomplete is therefore a complete
    list of outstanding work rather than a single next step.

    ``NOT_REACHED`` is narrower: the run had already stopped at a failure, so
    this question was never asked at all.
    """

    PASS = "PASS"
    FAIL = "FAIL"
    ACTION_REQUIRED = "ACTION_REQUIRED"
    NOT_REACHED = "NOT_REACHED"

    @property
    def is_final(self) -> bool:
        """Whether this status can appear in a finalized stage."""
        return self in (GateStatus.PASS, GateStatus.FAIL)


#: The documents each gate reports through. Exactly one each, and no document is
#: shared: a second document restating a gate's conclusion would be two
#: authorities for one number. The predecessor binding and the preflight report
#: belong to no gate, which is why they are absent here.
GATE_DOCUMENTS: tuple[tuple[PreflightGate, tuple[str, ...]], ...] = (
    (PreflightGate.OFFICIAL_ARTIFACT_ACQUISITION, (ACQUISITION_MANIFEST_NAME,)),
    (PreflightGate.PACKAGE_RUNTIME_IDENTITY, (PACKAGE_RUNTIME_IDENTITY_NAME,)),
    (PreflightGate.RESEARCH_USE_AND_TRIAL_OPERATION, (RESEARCH_USE_TRIAL_NAME,)),
    (PreflightGate.CANONICAL500_INPUT_ROUTE, (INPUT_ROUTE_NAME,)),
    (PreflightGate.SINGLE_FINGER_EXTRACTION_PROFILE, (EXTRACTION_PROFILE_NAME,)),
    (PreflightGate.RAW_1TO1_SCORE_CONTRACT, (SCORE_CONTRACT_NAME,)),
    (PreflightGate.SCORE_AFFECTING_SETTINGS_CLOSURE, (SETTINGS_CLOSURE_NAME,)),
    (PreflightGate.PAIR_SELF_DETERMINISM_FAILURES, (QUALIFICATION_RUN_NAME,)),
    (PreflightGate.FULL_WORKLOAD_FEASIBILITY, (WORKLOAD_FEASIBILITY_NAME,)),
    (PreflightGate.TRAINING_PROVENANCE, (TRAINING_PROVENANCE_NAME,)),
)


def gate_documents(gate: PreflightGate) -> tuple[str, ...]:
    """The documents one gate reports through."""
    for item, names in GATE_DOCUMENTS:
        if item is gate:
            return names
    raise FingerCellCandidateIdentityError(  # pragma: no cover - GATE_ORDER is total
        f"{gate!r} is not a Stage 13A gate"
    )


class BlockerCode(str, Enum):
    """Why FingerCell cannot enter fpbench as Algorithm 5. A closed list.

    Every member names something that was *observed* — an action was performed
    and the result was incompatible with this benchmark. None of them can be
    raised because a step has not been taken yet; that is what
    :class:`RequiredAction` is for, and keeping the two vocabularies disjoint is
    what stops "we have not tried" from being published as "it does not work"
    (docs/adr/0112).
    """

    OFFICIAL_TRIAL_UNAVAILABLE = "OFFICIAL_TRIAL_UNAVAILABLE"

    PRODUCT_IDENTITY_MISMATCH = "PRODUCT_IDENTITY_MISMATCH"
    RUNTIME_CLOSURE_UNRESOLVED = "RUNTIME_CLOSURE_UNRESOLVED"
    VERIFINGER_COMPONENT_IN_THE_ROUTE = "VERIFINGER_COMPONENT_IN_THE_ROUTE"

    RESEARCH_USE_BLOCKED = "RESEARCH_USE_BLOCKED"
    TRIAL_ACTIVATION_FAILED = "TRIAL_ACTIVATION_FAILED"

    CANONICAL500_ROUTE_UNRESOLVED = "CANONICAL500_ROUTE_UNRESOLVED"
    FPBENCH_PREPROCESSING_REQUIRED = "FPBENCH_PREPROCESSING_REQUIRED"

    EXTRACTION_ROUTE_UNRESOLVED = "EXTRACTION_ROUTE_UNRESOLVED"
    EXTRACTION_PROFILE_UNRESOLVED = "EXTRACTION_PROFILE_UNRESOLVED"

    RAW_SCORE_ROUTE_UNRESOLVED = "RAW_SCORE_ROUTE_UNRESOLVED"
    MATCHER_PROFILE_UNRESOLVED = "MATCHER_PROFILE_UNRESOLVED"

    HIDDEN_SCORE_AFFECTING_SETTING = "HIDDEN_SCORE_AFFECTING_SETTING"

    SCORE_NONDETERMINISM_OBSERVED = "SCORE_NONDETERMINISM_OBSERVED"
    LOCAL_SMOKE_FAILED = "LOCAL_SMOKE_FAILED"

    TRIAL_WORKLOAD_INSUFFICIENT = "TRIAL_WORKLOAD_INSUFFICIENT"

    SD300_OVERLAP_FOUND = "SD300_OVERLAP_FOUND"


#: Which gate each blocker belongs to. A blocker raised against a gate that was
#: never reached is a contradiction, and the engine refuses one.
GATE_BLOCKERS: tuple[tuple[PreflightGate, tuple[BlockerCode, ...]], ...] = (
    (
        PreflightGate.OFFICIAL_ARTIFACT_ACQUISITION,
        (BlockerCode.OFFICIAL_TRIAL_UNAVAILABLE,),
    ),
    (
        PreflightGate.PACKAGE_RUNTIME_IDENTITY,
        (
            BlockerCode.PRODUCT_IDENTITY_MISMATCH,
            BlockerCode.RUNTIME_CLOSURE_UNRESOLVED,
            BlockerCode.VERIFINGER_COMPONENT_IN_THE_ROUTE,
        ),
    ),
    (
        PreflightGate.RESEARCH_USE_AND_TRIAL_OPERATION,
        (
            BlockerCode.RESEARCH_USE_BLOCKED,
            BlockerCode.TRIAL_ACTIVATION_FAILED,
        ),
    ),
    (
        PreflightGate.CANONICAL500_INPUT_ROUTE,
        (
            BlockerCode.CANONICAL500_ROUTE_UNRESOLVED,
            BlockerCode.FPBENCH_PREPROCESSING_REQUIRED,
        ),
    ),
    (
        PreflightGate.SINGLE_FINGER_EXTRACTION_PROFILE,
        (
            BlockerCode.EXTRACTION_ROUTE_UNRESOLVED,
            BlockerCode.EXTRACTION_PROFILE_UNRESOLVED,
        ),
    ),
    (
        PreflightGate.RAW_1TO1_SCORE_CONTRACT,
        (
            BlockerCode.RAW_SCORE_ROUTE_UNRESOLVED,
            BlockerCode.MATCHER_PROFILE_UNRESOLVED,
        ),
    ),
    (
        PreflightGate.SCORE_AFFECTING_SETTINGS_CLOSURE,
        (BlockerCode.HIDDEN_SCORE_AFFECTING_SETTING,),
    ),
    (
        PreflightGate.PAIR_SELF_DETERMINISM_FAILURES,
        (
            BlockerCode.SCORE_NONDETERMINISM_OBSERVED,
            BlockerCode.LOCAL_SMOKE_FAILED,
        ),
    ),
    (
        PreflightGate.FULL_WORKLOAD_FEASIBILITY,
        (BlockerCode.TRIAL_WORKLOAD_INSUFFICIENT,),
    ),
    (
        PreflightGate.TRAINING_PROVENANCE,
        (BlockerCode.SD300_OVERLAP_FOUND,),
    ),
)


def gate_of_blocker(code: BlockerCode) -> tuple[PreflightGate, ...]:
    """Which gate may raise this blocker. Exactly one, checked at import."""
    return tuple(gate for gate, codes in GATE_BLOCKERS if code in codes)


class RequiredAction(str, Enum):
    """A local step this project can perform and has not performed yet.

    The counterpart to :class:`BlockerCode` and its exact opposite in meaning.
    Every member is an act somebody can go and do today without asking a vendor
    for anything — which is the property FingerCell has and IDKit did not.
    """

    #: The official trial archive has not been fetched into the local store.
    ARCHIVE_NOT_ACQUIRED = "ARCHIVE_NOT_ACQUIRED"

    #: The archive is here and nothing has been unpacked or inventoried.
    PACKAGE_NOT_INVENTORIED = "PACKAGE_NOT_INVENTORIED"

    #: One official binding has not been selected from what the archive ships.
    BINDING_NOT_SELECTED = "BINDING_NOT_SELECTED"

    #: The qualification bridge has not been written and compiled against the
    #: selected binding. Deliberately separate from activation: the bridge is
    #: built first so that the trial clock does not run while it is debugged
    #: (docs/adr/0115).
    BRIDGE_NOT_COMPILED = "BRIDGE_NOT_COMPILED"

    #: The trial has not been activated and no licence has been obtained.
    TRIAL_NOT_ACTIVATED = "TRIAL_NOT_ACTIVATED"

    #: No runtime has been loaded, so the loaded-module set is not observed.
    RUNTIME_NOT_EXERCISED = "RUNTIME_NOT_EXERCISED"

    #: Settings have not been read off a constructed engine.
    SETTINGS_NOT_ENUMERATED = "SETTINGS_NOT_ENUMERATED"

    #: The matcher has not been called, so its contract is not observed.
    SCORE_CONTRACT_NOT_OBSERVED = "SCORE_CONTRACT_NOT_OBSERVED"

    #: No settings inventory exists, so nothing can be closed over.
    SETTINGS_CLOSURE_NOT_ESTABLISHED = "SETTINGS_CLOSURE_NOT_ESTABLISHED"

    #: The bounded qualification has not been run.
    QUALIFICATION_NOT_RUN = "QUALIFICATION_NOT_RUN"

    #: Trial capacity and runtime cost have not been measured.
    WORKLOAD_NOT_MEASURED = "WORKLOAD_NOT_MEASURED"

    #: Nobody has searched for a training-set overlap. Explicitly an action and
    #: never a finding: "not searched" must not be published as "overlap".
    PROVENANCE_NOT_SEARCHED = "PROVENANCE_NOT_SEARCHED"


#: Which gate each action belongs to. As with blockers, exactly one owner each,
#: so that "what is outstanding" and "where the run stopped" cannot disagree.
GATE_ACTIONS: tuple[tuple[PreflightGate, tuple[RequiredAction, ...]], ...] = (
    (
        PreflightGate.OFFICIAL_ARTIFACT_ACQUISITION,
        (RequiredAction.ARCHIVE_NOT_ACQUIRED,),
    ),
    (
        PreflightGate.PACKAGE_RUNTIME_IDENTITY,
        (
            RequiredAction.PACKAGE_NOT_INVENTORIED,
            RequiredAction.BINDING_NOT_SELECTED,
            RequiredAction.BRIDGE_NOT_COMPILED,
        ),
    ),
    (
        PreflightGate.RESEARCH_USE_AND_TRIAL_OPERATION,
        (RequiredAction.TRIAL_NOT_ACTIVATED,),
    ),
    (
        PreflightGate.CANONICAL500_INPUT_ROUTE,
        (RequiredAction.RUNTIME_NOT_EXERCISED,),
    ),
    (
        PreflightGate.SINGLE_FINGER_EXTRACTION_PROFILE,
        (RequiredAction.SETTINGS_NOT_ENUMERATED,),
    ),
    (
        PreflightGate.RAW_1TO1_SCORE_CONTRACT,
        (RequiredAction.SCORE_CONTRACT_NOT_OBSERVED,),
    ),
    (
        PreflightGate.SCORE_AFFECTING_SETTINGS_CLOSURE,
        (RequiredAction.SETTINGS_CLOSURE_NOT_ESTABLISHED,),
    ),
    (
        PreflightGate.PAIR_SELF_DETERMINISM_FAILURES,
        (RequiredAction.QUALIFICATION_NOT_RUN,),
    ),
    (
        PreflightGate.FULL_WORKLOAD_FEASIBILITY,
        (RequiredAction.WORKLOAD_NOT_MEASURED,),
    ),
    (
        PreflightGate.TRAINING_PROVENANCE,
        (RequiredAction.PROVENANCE_NOT_SEARCHED,),
    ),
)


def gate_of_action(action: RequiredAction) -> tuple[PreflightGate, ...]:
    """Which gate may report this outstanding action. Exactly one."""
    return tuple(gate for gate, codes in GATE_ACTIONS if action in codes)


# ------------------------------------------------------------- G1 acquisition


class LocatorCategory(str, Enum):
    """How the archive was obtained. A closed set of official routes."""

    #: The vendor publishes a direct download and this project fetched it. The
    #: route FingerCell actually offers, and the reason Stage 13A can start
    #: without asking anybody for permission.
    VENDOR_DIRECT_DOWNLOAD = "VENDOR_DIRECT_DOWNLOAD"

    VENDOR_CUSTOMER_PORTAL = "VENDOR_CUSTOMER_PORTAL"
    VENDOR_SUPPORT_DELIVERY = "VENDOR_SUPPORT_DELIVERY"

    UNRESOLVED = "UNRESOLVED"


#: Sources that are not acquisition, whatever they contain. Named as categories
#: rather than as hostnames, because the rule is about provenance: an archive
#: whose chain of custody runs through a third party is one nobody can pin.
REFUSED_ACQUISITION_SOURCES: tuple[str, ...] = (
    "a download mirror",
    "a software-catalogue or freeware site",
    "a third-party GitHub repository",
    "a reseller or distributor store",
    "an archive somebody uploaded",
    "a copy received from another project",
)

#: A signed or tokenized URL is a fact about one session, not about an artifact.
#: Where the official link redirects to one, the redirect target is never what
#: gets published: the stable vendor locator is, and the digest does the pinning.
TOKENIZED_LOCATORS_ARE_NOT_PINNED = True

#: What the acquisition manifest has to carry. Every field is a property of the
#: bytes that arrived or of the route they arrived by.
ARTIFACT_EVIDENCE_FIELDS: tuple[str, ...] = (
    "official_locator_category",
    "filename",
    "size_bytes",
    "sha256",
    "downloaded_utc",
    "product",
    "product_version",
    "vendor_product_revision",
    "vendor_revision_hash",
)

#: All four, or the gate does not pass. "We found the download page" is not
#: acquisition, and neither is an archive with no documentation beside it.
ACQUISITION_PASS_CONDITIONS: tuple[str, ...] = (
    "the archive was physically obtained",
    "its official origin was verified",
    "its exact bytes were hashed",
    "matching delivered documentation was obtained",
)


# ------------------------------------------------- G2 identity and the runtime


class ProductFamily(str, Enum):
    """Which Neurotechnology product the archive actually is.

    The confusion this gate exists to catch. Every one of the refused members
    below would still produce fingerprint scores, and they would be a different
    algorithm's scores published under this candidate's name.
    """

    FINGERCELL_SDK = "FINGERCELL_SDK"

    VERIFINGER_SDK = "VERIFINGER_SDK"
    MEGAMATCHER_SDK = "MEGAMATCHER_SDK"
    FREE_FINGERPRINT_VERIFICATION_SDK = "FREE_FINGERPRINT_VERIFICATION_SDK"
    FINGERCELL_EMBEDDED_SOURCE_PACKAGE = "FINGERCELL_EMBEDDED_SOURCE_PACKAGE"

    UNRESOLVED = "UNRESOLVED"


#: Everything this candidate is not. A delivered archive that resolves to one of
#: these is not a smaller version of the candidate; it is a different one, and it
#: would need its own preflight. The last member is the subtle one: the embedded
#: source/library package is FingerCell, and it is not the desktop evaluation SDK
#: whose contract this stage qualifies.
REFUSED_PRODUCT_FAMILIES: tuple[ProductFamily, ...] = (
    ProductFamily.VERIFINGER_SDK,
    ProductFamily.MEGAMATCHER_SDK,
    ProductFamily.FREE_FINGERPRINT_VERIFICATION_SDK,
    ProductFamily.FINGERCELL_EMBEDDED_SOURCE_PACKAGE,
)

#: What has to be frozen about the package before anything is executed.
PACKAGE_IDENTITY_FIELDS: tuple[str, ...] = (
    "product",
    "product_version",
    "product_revision",
    "platform",
    "architecture",
    "selected_binding",
    "binding_version",
)

#: What is recorded for each runtime component. Vendor bytes stay in the local
#: artifact store; the repository holds only these descriptions, and the path is
#: always relative to the store root.
RUNTIME_COMPONENT_FIELDS: tuple[str, ...] = (
    "relative_path",
    "component_role",
    "size_bytes",
    "sha256",
    "version_or_revision",
    "source_archive_member",
)


class ComponentRole(str, Enum):
    """What a runtime component does in this route."""

    #: The FingerCell algorithm itself: the extractor and matcher under test.
    FINGERCELL_ALGORITHM = "FINGERCELL_ALGORITHM"

    #: Common Neurotechnology runtime — object model, strings, types.
    COMMON_RUNTIME = "COMMON_RUNTIME"

    #: Image and media handling.
    IMAGE_RUNTIME = "IMAGE_RUNTIME"

    #: The managed or JNI binding, where one is used.
    LANGUAGE_BINDING = "LANGUAGE_BINDING"

    #: Licence acquisition and validation.
    LICENSING = "LICENSING"

    #: Data, configuration or model files the algorithm reads.
    RUNTIME_DATA = "RUNTIME_DATA"

    #: A platform library that is not Neurotechnology's.
    SYSTEM_DEPENDENCY = "SYSTEM_DEPENDENCY"


RUNTIME_COMPONENT_ROLES: tuple[str, ...] = tuple(role.value for role in ComponentRole)

#: The classes of thing the fingerprint route can need. The inventory is closed
#: when every one has been either found or ruled out.
RUNTIME_COMPONENTS_TO_LOOK_FOR: tuple[str, ...] = (
    "the FingerCell native module",
    "the common Neurotechnology runtime",
    "the image and media runtime",
    "the managed or JAR binding, where one is used",
    "licensing components",
    "runtime data, configuration or model files",
)

#: The assumption this gate refuses. Both candidates are Neurotechnology's and
#: both ship modules with the same naming convention, which makes "it is probably
#: the same closure as Algorithm 4" an easy and completely unfounded conclusion.
#: The closure is established from this archive (docs/adr/0114).
RUNTIME_CLOSURE_IS_NOT_INHERITED_FROM_A_SIBLING = True


class Binding(str, Enum):
    """The language binding the route runs through. Exactly one is selected."""

    CPP = "CPP"
    JAVA = "JAVA"
    DOTNET = "DOTNET"
    UNRESOLVED = "UNRESOLVED"


#: How the one binding is chosen, in order. Applied to what the archive actually
#: ships, never to what a product page implies it might.
BINDING_SELECTION_CRITERIA: tuple[str, ...] = (
    "shipped in this exact trial",
    "an official FingerCell sample exists for it",
    "it exposes Extract",
    "it exposes Match",
    "it exposes or allows reading the settings",
    "it supports runtime and module inspection sufficiently",
    "it needs the least additional glue",
)

#: Java was the engineering preference going in, conditional on the archive
#: shipping a complete and suitable sample for it. It is a preference and never a
#: requirement, and the criteria above decide (docs/adr/0116).
BINDING_PREFERENCE_IS_NOT_A_REQUIREMENT = True

#: One binding, all the way through. A route that took a sample from one, a
#: default from another and a function signature from a third would be a route
#: nobody could reproduce.
BINDINGS_ARE_NOT_MIXED = True

#: Components that would make this Algorithm 4 wearing Algorithm 5's name. None
#: of them may appear anywhere in the extraction or matching path.
VERIFINGER_ALGORITHM_COMPONENTS: tuple[str, ...] = (
    "the VeriFinger fingerprint extractor",
    "the VeriFinger fingerprint matcher",
    "a general biometric engine that dispatches to either of them",
    "a VeriFinger template format used as the compared representation",
    "a VeriFinger configuration or settings profile",
)

#: Common Neurotechnology components the FingerCell route may legitimately use.
#: They are permitted only because the FingerCell trial itself ships and requires
#: them, and only when they are pinned as part of *this* runtime closure.
PERMITTED_COMMON_RUNTIME_COMPONENTS: tuple[str, ...] = (
    "the common object/runtime library",
    "the image and media library",
    "the licensing library",
    "platform and C runtime libraries",
)

#: What the contamination guard has to establish, positively, before the route is
#: allowed to produce a number.
CONTAMINATION_CLAIMS_TO_PROVE: tuple[str, ...] = (
    "the FingerCell algorithm module is the extractor under test",
    "the FingerCell algorithm module is the matcher under test",
    "no VeriFinger extractor or matcher is reachable from the route",
    "no prior algorithm's adapter, bridge or configuration is imported",
    "no prior algorithm's scores are read",
)


# ---------------------------------------------------- G3 research use and trial


class TrialStartSemantics(str, Enum):
    """When the 30-day clock actually starts.

    Recorded rather than guessed. A trial whose clock started at download has a
    different amount of time left than one whose clock starts at first licence
    request, and planning 6,000 comparisons around the wrong one is how a run
    dies at comparison four thousand.
    """

    ON_DOWNLOAD = "ON_DOWNLOAD"
    ON_INSTALL = "ON_INSTALL"
    ON_FIRST_LICENSE_REQUEST = "ON_FIRST_LICENSE_REQUEST"
    ON_FIRST_RUNTIME_USE = "ON_FIRST_RUNTIME_USE"
    ON_EXPLICIT_ACTIVATION = "ON_EXPLICIT_ACTIVATION"
    OTHER = "OTHER"

    #: Nobody could tell from the delivered material. Permitted before the first
    #: controlled run, and it must then be published as unresolved rather than
    #: quietly resolved to whichever value made the plan work.
    UNRESOLVED = "UNRESOLVED"


#: What has to be settled from the delivered trial material, not from the public
#: page. Each is separately answerable and they are routinely collapsed into one.
TRIAL_QUESTIONS: tuple[str, ...] = (
    "trial_start_semantics",
    "trial_duration",
    "network_requirement",
    "activation_method",
    "product_entitlement",
)

#: Five questions that are not one question. An archive can be obtainable and its
#: terms still forbid research use; the terms can permit it and the trial still
#: fail to activate; it can activate and still not cover 6,000 comparisons.
LICENSE_SEPARATED_QUESTIONS: tuple[str, ...] = (
    "package_obtainable",
    "research_execution_permitted",
    "trial_operational",
    "trial_duration_sufficient",
    "network_requirement_understood",
)

#: The inference this gate refuses, and Stage 13A's own hazard. Another
#: Neurotechnology product has already been activated on this machine for
#: Algorithm 4, so a running licensing service proves nothing about FingerCell.
#: Evidence is required that the FingerCell component itself was authorised
#: (docs/adr/0114).
SAME_VENDOR_LICENSING_ISOLATION = (
    "a running Neurotechnology licensing service does not imply a valid "
    "FingerCell entitlement; the FingerCell component's own authorization must "
    "be observed"
)

#: Never, under any circumstances, and none of them becomes acceptable because
#: the clock ran out mid-qualification.
REFUSED_LICENSE_ACTIONS: tuple[str, ...] = (
    "reactivating an expired trial",
    "resetting a trial clock",
    "bypassing licence validation",
    "patching or replacing a licensing component",
    "reusing another product's entitlement for FingerCell",
)


# ------------------------------------------------------------- G4 input route

BENCHMARK_INPUT_PROFILE = "canonical_500"
BENCHMARK_INPUT_PPI = 500
BENCHMARK_INPUT_PIXEL_FORMAT = "gray8"

#: What the route should be, if the delivered image loader reads the container
#: the benchmark already holds and preserves its resolution.
IDEAL_INPUT_ROUTE: tuple[str, ...] = (
    "canonical_500 PNG",
    "official NImage loader",
    "correct 500 PPI metadata",
    "FingerCell.Extract",
)

#: What the route may be instead, where the loader does not read or preserve the
#: resolution. Permitted only under the proof below: a decode that produced
#: different pixels would be fpbench choosing a preprocessing step and calling it
#: a file format.
PERMITTED_DECODE_ROUTE: tuple[str, ...] = (
    "canonical_500 PNG",
    "deterministic lossless decode",
    "exact width x height x gray8 pixel matrix",
    "NImage constructed from those exact pixels",
    "explicit 500 PPI",
    "FingerCell.Extract",
)

#: What has to be proved before the decode route may be used, over the images the
#: benchmark will actually run.
DECODE_EQUIVALENCE_REQUIREMENTS: tuple[str, ...] = (
    "the decode is lossless and deterministic on this platform",
    "width and height are unchanged",
    "the pixel format stays 8-bit grayscale",
    "every pixel value is identical to the PNG's decoded matrix",
)

#: Refused whatever the reason, unless upstream's own documented route performs
#: it inside the SDK. Each changes the pixels a score is computed from, and a
#: benchmark that chose one would be reporting on fpbench's image processing.
REFUSED_PREPROCESSING: tuple[str, ...] = (
    "crop",
    "resize",
    "pad",
    "rotate",
    "ROI selection",
    "enhancement",
    "contrast normalization",
    "histogram processing",
    "binarization",
    "external minutiae extraction",
)

#: Whatever the SDK does to the pixels inside itself is the algorithm, and the
#: algorithm is what this benchmark measures.
INTERNAL_BLACK_BOX_PREPROCESSING_IS_ACCEPTABLE = True

REQUIRED_INPUT_PPI = 500

#: Where the resolution has to be true. Not set after extraction — a template
#: remembers the resolution it was extracted under, so setting it afterwards sets
#: it for the next one. And never achieved by rescaling pixels.
PPI_MUST_BE_EFFECTIVE_AT_EXTRACTION = True

#: The dimensions upstream uses as a worked example in its resource and
#: performance specifications, paired there with 180x256 at 385 PPI. Recorded so
#: that the refusal below can name exactly what it is refusing.
EMBEDDED_BENCHMARK_SAMPLE_DIMENSIONS = (234, 332)

#: The mistake this constant exists to prevent. Those dimensions are an example
#: used to state memory and speed figures for an embedded target. They are not a
#: required input size, and turning an embedded benchmark's example into an
#: fpbench preprocessing rule would crop every image in the corpus to fit a
#: footnote (docs/adr/0117).
SAMPLE_DIMENSIONS_ARE_NOT_A_PREPROCESSING_RULE = True


# ------------------------------------------------------- G5 the extraction route


class TemplateFormat(str, Enum):
    """What Extract produces. The delivered enum, in its delivered order."""

    PROPRIETARY = "PROPRIETARY"
    ISO = "ISO"
    MOC = "MOC"
    UNKNOWN = "UNKNOWN"


#: The format under test, and upstream's own default. An ISO or MOC export is a
#: different matching scenario with its own accuracy; choosing one because it is
#: easier to store would be benchmarking a different algorithm under this name.
REQUIRED_TEMPLATE_FORMAT = TemplateFormat.PROPRIETARY

#: Ways of building a comparison that are not this benchmark's comparison. The
#: first is the specific FingerCell hazard: the SDK supports merging several
#: records into one template, which is a real and supported scenario and a
#: different quantity from a single-impression similarity.
REFUSED_TEMPLATE_CONSTRUCTIONS: tuple[str, ...] = (
    "MergeTemplates",
    "multiple impressions",
    "a multi-record template",
    "template stitching",
    "gallery fusion",
    "ISO conversion",
    "MOC conversion",
)

#: The rule, stated once.
SINGLE_FINGER_RULE = (
    "one image -> one fresh Extract -> one template, on each side of every "
    "comparison"
)

#: The route, in order.
EXTRACTION_ROUTE: tuple[str, ...] = (
    "one image",
    "one fresh Extract()",
    "one template buffer",
)

#: Quality rejection is upstream's behaviour and part of the algorithm: below the
#: quality or minutiae thresholds no template is returned at all. So a rejected
#: fingerprint is an extraction failure and never a score of zero, which would
#: enter the benchmark as a very poor match that no metric could distinguish
#: from a real one.
QUALITY_REJECTION_IS_PART_OF_THE_ALGORITHM = True

#: The workaround this stage refuses. Lowering the quality threshold to admit
#: more images is choosing a parameter because it improved coverage on this
#: project's data, which is tuning on the dataset whatever it is called.
REFUSED_QUALITY_THRESHOLD_TUNING = (
    "lowering or zeroing the image quality threshold in order to increase the "
    "number of images that produce a template"
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
        existing protocol fact onto an API — pair.left to reference, 500 PPI for
        a 500 PPI image — where the value is *derived* from something the
        benchmark already froze rather than chosen because it performed better.
        It may never be used to pick a quality threshold, a matching algorithm
        version or a template size.
        """
        return self is not SettingProvenance.UNRESOLVED


#: The one answer that is never acceptable, kept as a string rather than an enum
#: member so it cannot be selected by accident.
REFUSED_SETTING_PROVENANCE = "FPBENCH_CHOICE_TUNED_ON_OUR_DATA"

#: The settings known to exist for this product, as a floor and not a ceiling.
SETTINGS_TO_CLOSE: tuple[str, ...] = (
    "MaximalMinutiaCount",
    "MinimalMinutiaCount",
    "LargeTemplate",
    "TemplateFormat",
    "ImageQualityThreshold",
    "MatchingAlgorithm",
    "resolution and image metadata behaviour",
    "inherited object properties that reach FingerCell",
    "any option an official sample sets explicitly",
)

#: The most important sentence in this module. The list above is what was known
#: before the archive was opened; the archive is entitled to have more. A closure
#: built by ticking off a list written in advance is not a closure.
SETTINGS_LIST_IS_NOT_EXHAUSTIVE = True

#: And the sentence that bounds it. The gate closes the settings upstream
#: *offers* — the ones its documentation describes, its bindings expose, its
#: samples set, or its own property enumeration reports on a constructed engine.
#: It does not close implementation internals, and it is not a licence to hunt
#: for names inside a shipped binary: a symbol that is not externally selectable
#: is not a setting this benchmark could have chosen differently, so freezing it
#: would say nothing about reproducibility (docs/adr/0120).
SETTINGS_CLOSURE_COVERS_EXTERNALLY_SELECTABLE_VALUES_ONLY = True

#: Where to look, so that "we checked" means something specific. Every surface is
#: one upstream published or the SDK itself reports.
SETTING_DISCOVERY_SURFACES: tuple[str, ...] = (
    "the delivered API documentation",
    "the delivered sample and tutorial sources",
    "the delivered headers and language bindings",
    "the runtime object's own property enumeration on a constructed engine",
)

#: What is recorded for every setting found.
SETTING_ROW_FIELDS: tuple[str, ...] = (
    "name",
    "runtime_value",
    "documented_default",
    "effective_value",
    "provenance",
    "can_affect_template_or_score",
)

#: The order, and it matters. Construct the engine, read everything obtainable,
#: compare against the documentation, and only then configure anything — and only
#: where the official route explicitly requires it. Using a generic property
#: setter to "pin" defaults before reading them destroys the evidence that they
#: were the defaults (docs/adr/0118).
SETTINGS_ARE_READ_BEFORE_THEY_ARE_SET = True

#: What the delivered documentation states the matching algorithm default is, and
#: what a constructed engine is therefore expected to report.
MATCHING_ALGORITHM_EXPECTED_VALUE = 0

#: What to do when it does not report that. Not force it back: understand why
#: first. A silent correction would hide a delivered runtime disagreeing with its
#: own documentation, which is a finding about the artifact.
MATCHING_ALGORITHM_IS_NOT_FORCED_SILENTLY = True


# ------------------------------------------------------------- G6 the score route


class ScoreRouteStatus(str, Enum):
    """What the matcher gives back per comparison."""

    #: One scalar, readable independently of any match decision.
    NATIVE_SCALAR = "NATIVE_SCALAR"

    #: A decision, or a score the API only surrenders above a threshold.
    DECISION_ONLY = "DECISION_ONLY"

    UNRESOLVED = "UNRESOLVED"

    @property
    def is_raw_score(self) -> bool:
        return self is ScoreRouteStatus.NATIVE_SCALAR


#: What has to be frozen about the score before six thousand of them are worth
#: producing. Every one comes from the delivered API.
SCORE_CONTRACT_REQUIREMENTS: tuple[str, ...] = (
    "exact_api_or_method",
    "native_numeric_type",
    "direction",
    "range_status",
    "failure_behaviour",
    "threshold_relationship",
    "fpbench_transformation",
)

#: The native type and direction the delivered API defines.
SCORE_NATIVE_TYPE = "signed_integer"
SCORE_DIRECTION = "HIGHER_IS_MORE_SIMILAR"

#: What must not be invented. Where the delivered runtime and documentation
#: define no range, none is published: a range observed over twenty qualification
#: comparisons is a fact about those twenty comparisons.
SCORE_RANGE_IS_NOT_ASSUMED = True

#: Shapes that are not a raw score, however convenient.
INSUFFICIENT_SCORE_SHAPES: tuple[str, ...] = (
    "MATCH / NO_MATCH",
    "true / false",
    "a candidate list filtered by a threshold",
    "a score returned only above a threshold",
)

#: What fpbench does to a native score. Nothing.
FPBENCH_SCORE_TRANSFORMATION = "NONE"

#: Transformations that would each produce a different benchmark.
REFUSED_SCORE_TRANSFORMATIONS: tuple[str, ...] = (
    "convert to FAR",
    "take -log FAR",
    "rescale to a percentage",
    "rescale to 0..1",
    "z-score",
    "any other normalization",
    "clamp",
)

#: There is no decision layer inside Algorithm 5. Upstream publishes a threshold
#: and FAR mapping; that is an operating point, it belongs to the shared
#: calibration a later stage performs, and none of it happens here.
THRESHOLD_PRODUCED = False
DECISION_PRODUCED = False
CALIBRATION_PERFORMED = False


# --------------------------------------------- pair orientation, SELF, failures

#: How the benchmark's existing pair order maps onto the delivered API's own
#: role names. The API calls them reference and candidate, so those are the words
#: used here.
PAIR_ROLE_BINDING: tuple[tuple[str, str], ...] = (
    ("pair.left", "reference"),
    ("pair.right", "candidate"),
)

#: What the qualification does about orientation: run both, publish whether they
#: agree, and change nothing on the strength of it.
PAIR_ORIENTATION_REQUIREMENTS: tuple[str, ...] = (
    "score(A, B) is produced under the frozen binding",
    "score(B, A) is produced as a separate comparison, for observation only",
    "whether the two agree is published as a finding",
    "no symmetry is required and none is assumed",
    "the frozen binding is applied to every pair regardless of the finding",
)

#: Ways of collapsing the two orientations into one number. The last is the worst
#: of them: it is a per-pair choice made on the strength of the scores themselves.
REFUSED_ORIENTATION_REDUCTIONS: tuple[str, ...] = (
    "average",
    "max",
    "min",
    "sorting the two paths",
    "choosing whichever orientation scores higher",
)

#: Stage 12A planned ``left -> probe`` and ``right -> gallery`` for an API that
#: used those words. This API uses different ones. Copying a protocol label from
#: another candidate is how a binding ends up describing an API that is not there
#: (docs/adr/0119).
PAIR_LABELS_ARE_NOT_COPIED_FROM_ANOTHER_CANDIDATE = True

#: How SELF is built. Two loads, two extractions, two templates. An engine that
#: noticed both sides were the same object could return a constant, and that
#: constant would be a fact about this project's plumbing.
SELF_SEMANTICS_REQUIREMENTS: tuple[str, ...] = (
    "image A is loaded into a fresh image object and extracted to template A1",
    "image A is loaded again into a separate image object and extracted to A2",
    "Match(A1, A2) is the SELF comparison",
    "no template is reused, cached or shared between the two sides",
)

#: Whether a template may be computed once and reused. It may not — which is why
#: the extraction count is twice the comparison count and not a fraction of it.
TEMPLATE_CACHE_PERMITTED = False

#: Where the same score has to appear again.
DETERMINISM_LEVELS: tuple[str, ...] = (
    "repeat_in_the_same_process",
    "fresh_objects_in_the_same_process",
    "fresh_process",
)

#: And what "the same" means. Not "close enough": the exact same native integer.
DETERMINISM_REQUIREMENT = "the exact same native integer at all three levels"

#: The four probes a qualification must provoke. All four, not a subset — the
#: lesson Stage 12A's specification left on the table. Each is a cause paired
#: with what it establishes.
MANDATORY_FAILURE_PROBES: tuple[tuple[str, str], ...] = (
    (
        "malformed_image",
        "a structurally broken image is refused rather than scored",
    ),
    (
        "valid_image_without_fingerprint_structure",
        "an image the extractor declines produces a status, not a number",
    ),
    (
        "missing_or_invalid_input",
        "an absent or invalid input is refused before any scoring",
    ),
    (
        "invalid_matcher_or_template_invocation",
        "a controlled invalid matcher call returns a structured error",
    ),
)

#: A fifth, and only if it can be provoked without touching the trial. Provoking
#: it by expiring, resetting or corrupting a licence is refused outright.
OPTIONAL_FAILURE_PROBES: tuple[tuple[str, str], ...] = (
    (
        "license_unavailable",
        "the licence refusal is reported as itself, where this can be provoked "
        "without altering, bypassing or resetting the trial",
    ),
)

MANDATORY_FAILURE_PROBE_COUNT = len(MANDATORY_FAILURE_PROBES)

#: The rule every probe has to satisfy. Zero remains a legitimate *score*
#: wherever the matcher genuinely returns it.
FAILURE_SEMANTICS_RULE = (
    "a failure arrives as an exception, a status or an error code, and never as "
    "a pseudo-score; a score of 0 is a legitimate score wherever the matcher "
    "returns one"
)

#: A run that started and then broke is evidence about the route. Discarding it
#: and reporting the gate as ``ACTION_REQUIRED`` would turn a finding into a
#: chore, and ``ACTION_REQUIRED`` is reserved for actions never performed.
FAILED_QUALIFICATION_IS_KEPT = True


# ------------------------------------------------------------ the qualification

#: The passes a qualification record must carry to answer the gates.
QUALIFICATION_PASSES: tuple[tuple[str, str], ...] = (
    ("ordinary", "score(A, B) under the frozen role binding"),
    ("repeat_same_objects", "score(A, B) again, same process, same objects"),
    (
        "fresh_objects_same_process",
        "score(A, B) again, same process, newly constructed objects",
    ),
    ("fresh_process", "score(A, B) again, in a separate process"),
    ("reversed", "score(B, A), for observation only"),
    ("self", "SELF(A, A) from two independent extractions"),
)

#: The ceiling on score-producing comparisons. Small on purpose: this is a route
#: check, not a measurement, and a 30-day clock is running once the trial starts.
QUALIFICATION_MAX_SCORING_COMPARISONS = 20

#: What a qualification may score. Nothing else, and never SD300.
QUALIFICATION_FIXTURE_SOURCES: tuple[str, ...] = (
    "official vendor fingerprint samples shipped inside the delivered archive",
    "local non-SD300 fixtures generated by this project",
)


class QualificationOutcome(str, Enum):
    """Whether the bounded run finished, and the record it leaves either way."""

    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


#: Where the local record lives, and what schema it carries. The record stays in
#: the artifact store beside the archive: it names local paths and a machine, and
#: the published document is derived from it rather than being it.
QUALIFICATION_RECORD_NAME = "qualification-attempt.json"
QUALIFICATION_RECORD_SCHEMA = "stage_13a_qualification_v1"

#: The version of the settings contract a run was performed under. Bumped by hand
#: whenever the closure's shape changes, so that a record produced under an older
#: understanding of "which settings matter" cannot silently answer for a newer one.
SETTINGS_CONTRACT_VERSION = "1"

#: What a qualification record is bound to. ``engine_kind`` alone is not enough:
#: a record produced against a different trial archive, a different bridge or an
#: earlier driver would otherwise close a gate it knows nothing about.
#:
#: The two bridge fields are the ones that matter most and are the easiest to
#: forget. A bridge is edited far more often than an archive is re-downloaded, so
#: without them the twenty comparisons that qualified one build would go on
#: answering for every later one. ``bridge_source_fingerprint`` moves when the
#: source changes and ``bridge_binary_sha256`` moves when the *built artifact*
#: changes — which also catches a rebuild against different headers or libraries
#: from identical source.
#:
#: A reader recomputes what it can and refuses a stale record.
QUALIFICATION_RECORD_BINDING_FIELDS: tuple[str, ...] = (
    "archive_sha256",
    "product_revision",
    "bridge_source_fingerprint",
    "bridge_binary_sha256",
    "selected_binding",
    "settings_contract_version",
    "runtime_closure_fingerprint",
    "driver_fingerprint",
    "fixture_fingerprint",
    "platform",
    "architecture",
)

#: Every binding field must be present and non-empty before a record produced by
#: the delivered SDK may answer a gate. A record that left one blank would be a
#: record nobody could tell apart from one produced by a different build.
QUALIFICATION_RECORD_BINDING_IS_MANDATORY_FOR_A_REAL_RUN = True


# ---------------------------------------------------------------- the workload

#: The benchmark this candidate would have to survive, stated as three separate
#: numbers because they are three separate demands on a trial.
FROZEN_COMPARISON_ATTEMPTS = 6_000
FROZEN_INDEPENDENT_EXTRACTIONS = 12_000
FROZEN_MATCHER_INVOCATIONS = 6_000


@dataclass(frozen=True, slots=True)
class FrozenWorkload:
    """The demand a trial would have to cover, with the qualification allowance."""

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
                raise FingerCellCandidateIdentityError(
                    f"{name} must be a positive integer"
                )
        if self.independent_extractions != 2 * self.comparison_attempts:
            raise FingerCellCandidateIdentityError(
                "every comparison extracts both sides independently, so the "
                "extraction count is twice the comparison count; a smaller "
                "number would be a template cache nobody declared"
            )
        if self.matcher_invocations != self.comparison_attempts:
            raise FingerCellCandidateIdentityError(
                "one matcher invocation per comparison attempt"
            )

    @property
    def total_extractions(self) -> int:
        """Including the qualification's own, each of which also extracts twice."""
        return self.independent_extractions + 2 * self.qualification_allowance

    @property
    def total_matcher_invocations(self) -> int:
        return self.matcher_invocations + self.qualification_allowance

    @property
    def total_logical_operations(self) -> int:
        """The number a quota would have to cover, whatever it meters."""
        return self.total_extractions + self.total_matcher_invocations


FROZEN_WORKLOAD = FrozenWorkload(
    comparison_attempts=FROZEN_COMPARISON_ATTEMPTS,
    independent_extractions=FROZEN_INDEPENDENT_EXTRACTIONS,
    matcher_invocations=FROZEN_MATCHER_INVOCATIONS,
    qualification_allowance=QUALIFICATION_MAX_SCORING_COMPARISONS,
)

#: What has to be read off the trial that was actually issued. Not assumed absent
#: because no public page mentioned one: a quota nobody looked for is the quota
#: that stops the run at comparison four thousand.
TRIAL_CAPACITY_QUESTIONS: tuple[str, ...] = (
    "expiration",
    "trial_start_semantics",
    "network_dependency",
    "product_entitlement",
    "process_restrictions",
    "transaction_quota",
    "quota_metering_semantics",
)


class QuotaSchema(str, Enum):
    """How a trial counts, if it counts at all."""

    NONE = "NONE"
    PER_EXTRACTION = "PER_EXTRACTION"
    PER_MATCH = "PER_MATCH"
    PER_OPERATION = "PER_OPERATION"
    OTHER = "OTHER"
    UNRESOLVED = "UNRESOLVED"


#: An unresolved quota that could stop the frozen workload is not a pass. The
#: absence of a documented quota is not evidence that none is metered.
UNRESOLVED_QUOTA_BLOCKS_PASS = True

#: What the qualification measures about runtime cost, and all it measures. The
#: question is whether 6,000 comparisons fit inside the trial window, not how
#: this candidate compares with Algorithm 4 — a comparison on twenty comparisons
#: would be meaningless anyway.
RUNTIME_TIMING_MEASUREMENTS: tuple[str, ...] = (
    "process_startup",
    "two_independent_extractions",
    "one_match",
    "peak_or_approximate_memory",
)

#: Upstream publishes speed and memory figures for embedded targets at specific
#: image dimensions. They describe a microcontroller, not this host, and using
#: them to estimate a desktop run would produce a schedule built on the wrong
#: hardware.
VENDOR_EMBEDDED_FIGURES_ARE_NOT_A_PC_ESTIMATE = True


# --------------------------------------------------------- training provenance


class TrainingProvenanceStatus(str, Enum):
    """What is known about what the algorithm was trained on."""

    PROPRIETARY_UNDISCLOSED = "PROPRIETARY_UNDISCLOSED"
    DISCLOSED = "DISCLOSED"
    VENDOR_STATEMENT_OBTAINED = "VENDOR_STATEMENT_OBTAINED"
    NOT_REACHED = "NOT_REACHED"


class SD300OverlapStatus(str, Enum):
    """Whether this candidate was built on the benchmark's own evaluation data.

    ``NO_EVIDENCE_FOUND`` and ``VENDOR_DENIAL_OBTAINED`` both pass: a search was
    made and nothing turned up, or the vendor said so. ``NOT_SEARCHED`` is
    neither — it is an action nobody performed, it reports as
    ``ACTION_REQUIRED``, and it must never be read as evidence of overlap.
    """

    NO_EVIDENCE_FOUND = "NO_EVIDENCE_FOUND"
    OVERLAP_FOUND = "OVERLAP_FOUND"
    VENDOR_DENIAL_OBTAINED = "VENDOR_DENIAL_OBTAINED"
    NOT_SEARCHED = "NOT_SEARCHED"
    NOT_REACHED = "NOT_REACHED"

    @property
    def passes(self) -> bool:
        return self in (
            SD300OverlapStatus.NO_EVIDENCE_FOUND,
            SD300OverlapStatus.VENDOR_DENIAL_OBTAINED,
        )


#: Every use of SD300 that would disqualify the candidate. Training is the
#: obvious one; the other four are the ones a vendor would not usually call
#: training and which leak the evaluation set into the model just as effectively.
SD300_OVERLAP_SURFACES: tuple[str, ...] = (
    "training",
    "validation",
    "model selection",
    "algorithm tuning",
    "calibration",
    "development testing that affected the release",
)

#: The names the dataset goes by, so a search that finds nothing can say what it
#: looked for.
SD300_SEARCH_TERMS: tuple[str, ...] = (
    "NIST SD300",
    "Special Database 300",
    "SD 300",
)


class FailureClass(str, Enum):
    """What kind of failure a ``FAIL`` outcome is.

    ``FINGERCELL_PREFLIGHT_FAIL`` reads the same whether the trial would not
    activate or the delivered matcher turned out to be nondeterministic, and
    those are very different results for anybody deciding what to do next.
    """

    OFFICIAL_TRIAL_UNAVAILABLE = "OFFICIAL_TRIAL_UNAVAILABLE"
    RESEARCH_USE_BLOCKED = "RESEARCH_USE_BLOCKED"
    TRIAL_ACTIVATION_FAILED = "TRIAL_ACTIVATION_FAILED"
    TRIAL_WORKLOAD_INSUFFICIENT = "TRIAL_WORKLOAD_INSUFFICIENT"
    PRODUCT_IDENTITY_MISMATCH = "PRODUCT_IDENTITY_MISMATCH"
    RUNTIME_CLOSURE_UNRESOLVED = "RUNTIME_CLOSURE_UNRESOLVED"
    CANONICAL500_ROUTE_UNRESOLVED = "CANONICAL500_ROUTE_UNRESOLVED"
    FPBENCH_PREPROCESSING_REQUIRED = "FPBENCH_PREPROCESSING_REQUIRED"
    EXTRACTION_ROUTE_UNRESOLVED = "EXTRACTION_ROUTE_UNRESOLVED"
    EXTRACTION_PROFILE_UNRESOLVED = "EXTRACTION_PROFILE_UNRESOLVED"
    RAW_SCORE_ROUTE_UNRESOLVED = "RAW_SCORE_ROUTE_UNRESOLVED"
    MATCHER_PROFILE_UNRESOLVED = "MATCHER_PROFILE_UNRESOLVED"
    HIDDEN_SCORE_AFFECTING_SETTING = "HIDDEN_SCORE_AFFECTING_SETTING"
    SCORE_NONDETERMINISM_OBSERVED = "SCORE_NONDETERMINISM_OBSERVED"
    LOCAL_SMOKE_FAILED = "LOCAL_SMOKE_FAILED"
    SD300_OVERLAP_FOUND = "SD300_OVERLAP_FOUND"


# ------------------------------------------------------------- what is refused

#: What Stage 13A must not read, in either direction. The dataset, because a
#: candidate qualified on the evaluation set is a candidate qualified on the
#: answer sheet; the other algorithms' scores, because there is no reason for a
#: candidate's preflight to know how its predecessors did — and because one of
#: those predecessors is this vendor's other product.
FORBIDDEN_READS: tuple[str, ...] = (
    "sd300_image_bytes",
    "sd300_pair_manifest",
    "sd300_scores",
    "sourceafis_scores",
    "nbis_scores",
    "flx_scores",
    "verifinger_scores",
)

#: What this stage is not. Each of these is Stage 13B's, and building one here
#: would mean building it before knowing whether there is a route to build it on.
NON_GOALS: tuple[str, ...] = (
    "a FingerprintAlgorithmAdapter",
    "registry integration",
    "a canonical experiment configuration",
    "the 6,000-comparison run",
    "a ResultSet",
    "a decision profile",
    "a calibration",
    "a metric",
)

#: Restated as denials for the marker, so that "no production adapter exists" is
#: a checked claim rather than an intention.
PRODUCTION_INTEGRATION_NOT_CREATED: tuple[str, ...] = (
    "production_adapter_created",
    "registry_integration_created",
    "canonical_experiment_config_created",
    "benchmark_run_performed",
    "result_set_produced",
    "decision_profile_produced",
    "calibration_performed",
    "metrics_produced",
)

#: What this stage may build. Every item is disposable: if the candidate fails,
#: none of it becomes part of the benchmark.
PERMITTED_CONSTRUCTIONS: tuple[str, ...] = (
    "an artifact downloader and inspector",
    "a runtime manifest",
    "a small qualification bridge against the official binding",
    "a fake bridge for CI",
    "a qualification driver",
    "an evidence publisher",
)

#: What public CI must never do. Every one of these needs a vendor artifact, a
#: network call to a licensing service, or a credential — and a credential in a
#: service this project does not control is exactly what this stage refuses.
CI_MUST_NOT: tuple[str, ...] = (
    "download FingerCell",
    "contact a licensing server",
    "activate a trial",
    "load a vendor DLL, shared object or JAR",
    "produce a biometric score",
)

#: What public CI does instead, all of it pure Python on synthetic fixtures.
CI_MAY: tuple[str, ...] = (
    "the gate state machine",
    "the fake engine",
    "the schemas",
    "the artifact manifest parser",
    "the runtime closure validator",
    "the settings closure validator",
    "the qualification record binding",
    "the mandatory failure probes",
    "the secret guard",
    "the finalization invariants",
    "the SD300 and prior-score firewall",
)

#: The conjunction that admits the candidate. Every one must hold, and the
#: marker's ``PASS`` validation checks them one by one. There is no weighting and
#: no score at which enough of them is enough.
ACCEPTANCE_CONDITIONS: tuple[str, ...] = (
    "Stage 12A closed correctly and its exact fingerprint is bound",
    "the official FingerCell trial was obtained",
    "the exact archive SHA-256 is pinned",
    "the exact FingerCell 3.3 revision is identified",
    "one official binding was selected",
    "the complete runtime closure is pinned",
    "no VeriFinger extractor or matcher is in the route",
    "Stage 8E permits local research execution",
    "the FingerCell-specific trial entitlement works",
    "no licence bypass was attempted",
    "the trial covers the frozen workload",
    "canonical_500 enters without pixel modification",
    "500 PPI semantics are effective at extraction",
    "one image produces one fresh proprietary template",
    "no template merging is involved",
    "no template cache is involved",
    "every extractor setting is frozen",
    "a native raw integer score is accessible",
    "a higher score means more similar",
    "no decision is required to expose the score",
    "fpbench applies no score transformation",
    "MatchingAlgorithm is frozen",
    "every score-affecting setting is closed",
    "pair.left to reference and pair.right to candidate are frozen",
    "SELF was demonstrated from two independent extractions",
    "repeat and restart determinism passed",
    "all four mandatory failure probes passed",
    "a bounded local non-SD300 smoke passed",
    "training provenance was searched",
    "no positive SD300 overlap evidence was found",
    "no SD300 byte, manifest or score was consulted",
    "no prior algorithm's scores were consulted",
    "no production integration was created",
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
        "trial_token",
        "licensing_server",
        "license_server",
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
SENSITIVE_VALUE_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        "uuid_shape",
        r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{12}\b",
    ),
    (
        # Upper case and digits only, deliberately. A case-insensitive version
        # matches hyphenated lower-case slugs in the locators this stage
        # publishes, and a guard that refuses a URL is a guard somebody
        # switches off.
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

#: Refused at any depth of a published Stage 13A document, in addition to the
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
        "merged_score",
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

#: Every runtime path this stage publishes is relative to the artifact store
#: root. An absolute one names a machine and, on this project's own host, a
#: person.
PUBLISHED_PATHS_ARE_RELATIVE = True


# ------------------------------------------------------------ the closed stages
#
# Stage 13A reads three published markers and edits none of them.

#: Stage 12A as closed: an Innovatrics refusal at G1, no package, no execution,
#: and a marker that reopened the Algorithm 5 search. Binding the fingerprint
#: rather than the directory is what makes "Stage 12A was not edited" checkable
#: instead of asserted — and binding it *at all* is what makes Stage 13A a
#: successor rather than a restart.
STAGE_12A_OUTCOME = "IDKIT_PREFLIGHT_FAIL"
STAGE_12A_FAILURE_CLASS = "VENDOR_ACCESS_REFUSED"
STAGE_12A_FINALIZATION_FINGERPRINT = (
    "d3ef1127be38c75b932bdb8d2400da2608fbbf543223f78621535c0f24df321b"
)

#: Assembled from parts rather than written out, for the reason every stage since
#: 8C assembles its predecessor's path: this module's source is audited for
#: literals that name another stage's published evidence, and a written-out path
#: here would make the audit refuse the module that performs it.
STAGE_12A_EVIDENCE_DIRECTORY = "/".join(("evidence", "stage12a-" + "idkit-preflight"))

#: Stage 11B as published: 6,000 canonical raw VeriFinger outcomes under
#: Algorithm 4. Immutable here, and the reason the contamination guard exists.
STAGE_11B_OUTCOME = "VERIFINGER_CANONICAL500_RAW_COMPLETE"
STAGE_11B_FINALIZATION_FINGERPRINT = (
    "3d271490edda9e3e9d066485c2d93e82e2eceb4556668df7d65a8207e591684c"
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

#: Where the store keeps Stage 13A's archive, relative to the third-party root.
#: Outside the repository, always.
ARTIFACT_STORE_PREFIX = "neurotechnology-fingercell"

#: The bytes that decide this preflight. The marker fingerprints them, so a
#: change to any one of them after publication is detectable.
STAGE_13A_SOURCE_FILES: tuple[str, ...] = (
    "src/fpbench/core/fingercell_preflight_errors.py",
    "src/fpbench/experiments/stage13a_fingercell_identity.py",
    "src/fpbench/experiments/stage13a_fingercell_observations.py",
    "src/fpbench/experiments/stage13a_acquisition.py",
    "src/fpbench/experiments/stage13a_qualification.py",
    "src/fpbench/experiments/stage13a_preflight.py",
    "src/fpbench/experiments/stage13a_finalization.py",
)


def all_frozen_identifiers() -> tuple[str, ...]:
    """Every identifier-shaped constant this module froze, for the contract suite."""
    return (
        CANDIDATE_ID,
        ALGORITHM_SLOT,
        *(gate.value for gate in GATE_ORDER),
        *(status.value for status in GateStatus),
        *(code.value for code in BlockerCode),
        *(action.value for action in RequiredAction),
        *(category.value for category in LocatorCategory),
        *(family.value for family in ProductFamily),
        *(role.value for role in ComponentRole),
        *(item.value for item in Binding),
        *(item.value for item in TrialStartSemantics),
        *(item.value for item in TemplateFormat),
        *(item.value for item in SettingProvenance),
        *(item.value for item in ScoreRouteStatus),
        *(item.value for item in QuotaSchema),
        *(item.value for item in TrainingProvenanceStatus),
        *(item.value for item in SD300OverlapStatus),
        *(item.value for item in FailureClass),
        *(item.value for item in QualificationOutcome),
        *STAGE_13A_OUTCOMES,
    )


# ------------------------------------------------------- checked at import time
#
# Each of these is a mistake that would otherwise be found by a reader of the
# published evidence rather than by the module that produced it.


def _require_gate_documents_are_complete() -> None:
    covered = tuple(gate for gate, _ in GATE_DOCUMENTS)
    if covered != GATE_ORDER:
        raise FingerCellCandidateIdentityError(
            "every gate declares which documents it reports through, in the "
            f"frozen order; {covered} is not {GATE_ORDER}"
        )
    published: list[str] = []
    for _, names in GATE_DOCUMENTS:
        published.extend(names)
    duplicated = sorted({name for name in published if published.count(name) > 1})
    if duplicated:
        raise FingerCellCandidateIdentityError(
            f"two gates would report through the same document {duplicated}, "
            "which would give one document two authorities"
        )
    unknown = sorted(set(published) - set(REQUIRED_EVIDENCE_FILES))
    if unknown:
        raise FingerCellCandidateIdentityError(
            f"a gate reports through a document nothing publishes: {unknown}"
        )


def _require_every_blocker_belongs_to_one_gate() -> None:
    covered = tuple(gate for gate, _ in GATE_BLOCKERS)
    if covered != GATE_ORDER:
        raise FingerCellCandidateIdentityError(
            "every gate declares its blockers, in the frozen order"
        )
    for code in BlockerCode:
        owners = gate_of_blocker(code)
        if len(owners) != 1:
            raise FingerCellCandidateIdentityError(
                f"{code.value} belongs to {[item.value for item in owners]}; a "
                "blocker raised at two gates would put the reason in two places"
            )


def _require_every_action_belongs_to_one_gate() -> None:
    covered = tuple(gate for gate, _ in GATE_ACTIONS)
    if covered != GATE_ORDER:
        raise FingerCellCandidateIdentityError(
            "every gate declares its outstanding actions, in the frozen order"
        )
    for action in RequiredAction:
        owners = gate_of_action(action)
        if len(owners) != 1:
            raise FingerCellCandidateIdentityError(
                f"{action.value} belongs to {[item.value for item in owners]}; an "
                "action owned by two gates would leave the run stopping in two "
                "places"
            )


def _require_blockers_and_actions_are_disjoint() -> None:
    """The distinction this stage exists to keep.

    A name that was both a blocker and an outstanding action would be the exact
    confusion :class:`GateStatus` was written to prevent: "we have not tried"
    published as "it does not work" (docs/adr/0112).
    """
    blockers = {code.value for code in BlockerCode}
    actions = {action.value for action in RequiredAction}
    collision = sorted(blockers & actions)
    if collision:
        raise FingerCellCandidateIdentityError(
            f"{collision} is both a blocker and an outstanding action; the "
            "difference between the two is the point of this stage"
        )


def _require_failure_classes_cover_the_blockers() -> None:
    """Every blocker must be classifiable, or a FAIL marker cannot say what kind."""
    classes = {item.value for item in FailureClass}
    uncovered = sorted(
        code.value
        for code in BlockerCode
        if code.value not in classes
        and code is not BlockerCode.VERIFINGER_COMPONENT_IN_THE_ROUTE
    )
    if uncovered:
        raise FingerCellCandidateIdentityError(
            f"{uncovered} can be raised and cannot be classified; a FAIL marker "
            "would have to guess what kind of failure it was"
        )


def _require_evidence_paths_are_plain() -> None:
    for name in REQUIRED_EVIDENCE_FILES:
        pure = PurePosixPath(name)
        if len(pure.parts) != 1 or name != pure.name:
            raise FingerCellCandidateIdentityError(
                f"published evidence is flat and {name!r} is not a plain filename"
            )
    if len(set(REQUIRED_EVIDENCE_FILES)) != len(REQUIRED_EVIDENCE_FILES):
        raise FingerCellCandidateIdentityError("a document is published twice")


def _require_forbidden_keys_are_not_vocabulary() -> None:
    vocabulary = {value.lower() for value in all_frozen_identifiers()}
    collision = sorted(FORBIDDEN_PUBLISHED_KEYS & vocabulary)
    if collision:
        raise FingerCellCandidateIdentityError(
            f"{collision} is both a forbidden key and a published vocabulary "
            "value, so the guard would refuse a document for counting things"
        )


def _require_source_files_include_this_module() -> None:
    this = "src/fpbench/experiments/stage13a_fingercell_identity.py"
    if this not in STAGE_13A_SOURCE_FILES:
        raise FingerCellCandidateIdentityError(
            "the source fingerprint must cover the module that froze the "
            "vocabulary, or the vocabulary could change without the marker moving"
        )


def _require_the_revision_hash_is_not_digest_shaped() -> None:
    """A 40-character hex string must never be mistaken for a SHA-256."""
    if len(VENDOR_REVISION_HASH_INDICATION) == 64:
        raise FingerCellCandidateIdentityError(
            "the vendor revision hash is 64 characters long, which is the one "
            "length at which it could be pasted into a sha256 field unnoticed"
        )


_require_gate_documents_are_complete()
_require_every_blocker_belongs_to_one_gate()
_require_every_action_belongs_to_one_gate()
_require_blockers_and_actions_are_disjoint()
_require_failure_classes_cover_the_blockers()
_require_evidence_paths_are_plain()
_require_forbidden_keys_are_not_vocabulary()
_require_source_files_include_this_module()
_require_the_revision_hash_is_not_digest_shaped()
