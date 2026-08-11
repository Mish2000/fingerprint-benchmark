"""The seventeen hard gates, run in order, and the verdict that follows.

The engine has no verdict parameter, for the reason Stage 8E's decision engine
has none and Stage 10B's preflight has none: an engine that accepted an outcome
and then validated it would be a very elaborate way of writing the outcome down.
It reads the frozen record in
:mod:`fpbench.experiments.stage11a_verifinger_observations`, the state of the
local artifact store, and Stage 8E's own policy, applies the order frozen in
:mod:`fpbench.experiments.stage11a_verifinger_identity`, and reports what follows.

**Fail-fast is the design, not an optimisation.** The candidate stops at the
first gate it fails and every later gate is published ``NOT_REACHED``. The order
is the specification's: the artifact first, because every other question is a
question about an artifact; the raw score before latency and provenance, because
a route with no scalar score is not worth measuring (spec section 44).

**A gate is answered from the artifact or it is not answered.** Every runner
below reaches its conclusion from bytes that were pinned by digest — the archive,
the manual that ships inside it, upstream's own tutorials — or from the state of
this machine. Where the answer needs a *running licensed engine*, the runner says
so and does not substitute documentation for it: what a manual says a default is
worth is not what the engine was constructed with.

Nothing here reads SD300, reads a prior algorithm's scores, downloads anything,
activates a licence, loads a vendor library or produces a score.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from fpbench.core.serialization import stable_hash
from fpbench.core.verifinger_preflight_errors import (
    Stage11AFinalizationError,
    VeriFingerGateError,
    VeriFingerSensitiveEvidenceError,
)
from fpbench.experiments import stage11a_artifacts as store
from fpbench.experiments import stage11a_verifinger_identity as frozen
from fpbench.experiments import stage11a_verifinger_observations as observed
from fpbench.third_party import (
    LicenseEvidence,
    LicenseObservation,
    LicenseObservationStatus,
    NonBlockingRestriction,
    PlausibleReading,
    RedistributionDecision,
    RedistributionRecord,
    ResearchUseAssessment,
    ThirdPartyComponentKind,
    assess_research_use,
    policy_fingerprint,
    project_purpose,
)

__all__ = [
    "Blocker",
    "GateResult",
    "VeriFingerPreflight",
    "require_stage8e_is_the_policy_this_reuses",
    "require_stage10b_is_the_closed_predecessor",
    "license_observation",
    "research_use_assessment",
    "redistribution_record",
    "unresolved_score_affecting_settings",
    "run_preflight",
    "evidence_document",
    "marker_blocker_rows",
    "marker_pending_action_rows",
    "find_sensitive_material",
    "require_no_sensitive_material",
]


# ------------------------------------------------------------ the closed stages


def require_stage8e_is_the_policy_this_reuses(repository_root: Path) -> None:
    """Confirm the policy Stage 11A reuses is the policy it was written against.

    Raises:
        Stage11AFinalizationError: the published Stage 8E marker, the live
            purpose or the live policy has moved. Stage 11A does not repair
            Stage 8E and does not proceed around it — a corrective policy stage
            is the response, not a quiet edit from here.
    """
    relative = "evidence/stage8e-research-only-policy/stage-8e-finalization.json"
    marker = _read_marker(repository_root, relative, "Stage 8E")
    expected = {
        "outcome": frozen.STAGE8E_OUTCOME,
        "stage_8e_finalization_fingerprint": frozen.STAGE8E_FINALIZATION_FINGERPRINT,
        "purpose_fingerprint": frozen.STAGE8E_PURPOSE_FINGERPRINT,
        "policy_fingerprint": frozen.STAGE8E_POLICY_FINGERPRINT,
    }
    for key, value in expected.items():
        found = marker.get(key)
        if found != value:
            raise Stage11AFinalizationError(
                f"the Stage 8E marker's {key} is {found!r} and Stage 11A was "
                f"written against {value!r}. Stage 8E is a closed stage; a "
                "capability it lacks is a corrective policy stage, not an edit "
                "from here"
            )
    declaration = project_purpose()
    if declaration.purpose_fingerprint != frozen.STAGE8E_PURPOSE_FINGERPRINT:
        raise Stage11AFinalizationError(
            "the live project purpose no longer fingerprints to what Stage 8E "
            "published; every Stage 11A decision would be taken under a "
            "different premise"
        )
    if policy_fingerprint() != frozen.STAGE8E_POLICY_FINGERPRINT:
        raise Stage11AFinalizationError(
            "the live third-party policy no longer fingerprints to what Stage 8E "
            "published"
        )


def require_stage10b_is_the_closed_predecessor(repository_root: Path) -> str:
    """Confirm Stage 10B still says what Stage 11A was written after.

    Stage 11A exists because Stage 10B failed on access and opened a candidate
    search. Binding that marker's fingerprint is what makes "Stage 10B was not
    re-opened to admit VeriFinger" a checkable claim rather than an intention.

    Returns:
        The predecessor fingerprint, for the marker to carry.

    Raises:
        Stage11AFinalizationError: Stage 10B's marker has moved.
    """
    relative = f"{frozen.STAGE_10B_EVIDENCE_DIRECTORY}/stage-10b-finalization.json"
    marker = _read_marker(repository_root, relative, "Stage 10B")
    expected = {
        "outcome": frozen.STAGE_10B_OUTCOME,
        "stage_10b_finalization_fingerprint": (
            frozen.STAGE_10B_FINALIZATION_FINGERPRINT
        ),
    }
    for key, value in expected.items():
        found = marker.get(key)
        if found != value:
            raise Stage11AFinalizationError(
                f"the Stage 10B marker's {key} is {found!r} and Stage 11A was "
                f"written after {value!r}. Stage 10B is immutable here"
            )
    if marker.get("opens_candidate_search") is not True:
        raise Stage11AFinalizationError(
            "Stage 10B's marker no longer opens a candidate search, and a "
            "candidate search is the only thing Stage 11A is a response to"
        )
    if marker.get("stage_10c_reserved_for_this_candidate") is not True:
        raise Stage11AFinalizationError(
            "Stage 10B reserved Stage 10C for id3, and Stage 11A exists as a "
            "separate number precisely so that reservation holds"
        )
    return frozen.STAGE_10B_FINALIZATION_FINGERPRINT


def _read_marker(
    repository_root: Path, relative: str, stage: str
) -> Mapping[str, Any]:
    import json

    path = Path(repository_root) / PurePosixPath(relative)
    try:
        marker = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Stage11AFinalizationError(
            f"cannot read the {stage} marker Stage 11A binds at {relative}: {exc}"
        ) from exc
    if not isinstance(marker, dict):
        raise Stage11AFinalizationError(f"the {stage} marker is not a JSON object")
    return marker


# ------------------------------------------------------------------- Stage 8E


#: Every licence notice this stage read, each inside the pinned archive and each
#: cited by the digest of the document it was read from.
_LICENSE_EVIDENCE = (
    LicenseEvidence(
        locator="Neurotec_Biometric_2025_2_SDK/Documentation/SDK License.html",
        description=(
            "the SDK licence agreement shipped inside the pinned archive, headed "
            "'VeriFinger 2025.2, VeriLook 2025.2, VeriEye 2025.2, VeriSpeak "
            "2025.2, MegaMatcher 2025.2 SDK'"
        ),
        document_sha256=(
            "e630df7aa7d72f7f030875cf911ffab7f2a2e1fd3b99de26b8f803a95e7aee10"
        ),
    ),
    LicenseEvidence(
        locator="Neurotec_Biometric_2025_2_SDK/Documentation/Activation.pdf",
        description=(
            "the activation guide shipped inside the same archive, which states "
            "the trial terms and that engaging with the products through trial "
            "or activation constitutes agreement to the licence agreement"
        ),
        document_sha256=(
            "7bfd029689c56796bcb7f5b5e3a2d94daefe325eb8e904afeb5a2e36ae2162b3"
        ),
    ),
)

#: The restrictions the agreement actually states, in Stage 8E's shared
#: vocabulary. Every one is recorded, respected, and not a blocker: none of them
#: touches one person running one program on one machine and publishing no bytes
#: (docs/adr/0081).
_NON_BLOCKING_RESTRICTIONS = (
    NonBlockingRestriction.NON_COMMERCIAL_ONLY,
    NonBlockingRestriction.NO_REDISTRIBUTION,
    NonBlockingRestriction.NO_SUBLICENSING,
    NonBlockingRestriction.COMMERCIAL_LICENSE_REQUIRED_FOR_COMMERCIAL_DEPLOYMENT,
    NonBlockingRestriction.ATTRIBUTION_AND_NOTICE_RETENTION,
)


def license_observation() -> LicenseObservation:
    """What Neurotechnology's notices say about the acquired archive.

    ``NON_COMMERCIAL`` is the narrowest member of Stage 8E's closed vocabulary
    that is *true of the route this stage acquired*. The agreement is a
    proprietary commercial SDK licence, and the vocabulary has no member for one;
    but the artifact here was obtained under the trial, and the vendor's own
    activation guide states that the purpose of a trial product is to explore SDK
    functionality rather than end-user deployment, with a commercial licence
    required for anything beyond it. Recording that as ``NON_COMMERCIAL`` with
    ``COMMERCIAL_LICENSE_REQUIRED_FOR_COMMERCIAL_DEPLOYMENT`` beside it states
    both halves.

    Stage 8E is closed, so its vocabulary was not extended to add a proprietary
    member; the mismatch is published in the usage-binding document instead of
    being resolved by editing a finished stage (docs/adr/0099).
    """
    return LicenseObservation(
        observation_id="verifinger_2025_2_sdk_trial_license",
        component_kind=ThirdPartyComponentKind.RUNTIME_BINARY,
        subject=(
            "the VeriFinger 2025.2 SDK as delivered in the pinned "
            "Neurotec_Biometric_2025_2_SDK archive, under its trial licence"
        ),
        status=LicenseObservationStatus.NON_COMMERCIAL,
        declared_license_names=("Neurotechnology SDK License Agreement",),
        evidence=_LICENSE_EVIDENCE,
        stated_restrictions=(
            "a personal, non-exclusive licence to use the SDK for designing, "
            "developing, testing and distributing Licensee Products",
            "the SDK may only be used for a purpose or in a manner for which it "
            "was designed",
            "sharing, publishing, renting, leasing or transferring the software "
            "is forbidden, as is redistribution other than as prescribed",
            "reverse engineering, decompiling and deriving the algorithms is "
            "forbidden, as is circumventing the protection mechanisms",
            "copyright and attribution notices may not be removed or obscured",
            "the trial is a 30-day period whose purpose is to explore SDK "
            "functionality rather than end-user deployment",
        ),
        notes=(
            "Read from the agreement inside the pinned archive rather than from "
            "a licence page on the vendor's website, so the terms and the "
            "runtime cannot drift apart.",
            "Stage 11A executes nothing, so this observation records permission "
            "and not performance.",
        ),
    )


#: How a reasonable reader could understand the notices. Both notices are read
#: separately, because "the EULA permits development and testing" and "the trial
#: is for exploring functionality" are different sentences in different documents
#: and the conservative answer is the intersection of them.
_PLAUSIBLE_READINGS = (
    PlausibleReading(
        notice_locator=(
            "Neurotec_Biometric_2025_2_SDK/Documentation/SDK License.html"
        ),
        permits_local_execution=True,
        permits_non_commercial_use=True,
        permits_educational_research=True,
    ),
    PlausibleReading(
        notice_locator=(
            "Neurotec_Biometric_2025_2_SDK/Documentation/Activation.pdf"
        ),
        permits_local_execution=True,
        permits_non_commercial_use=True,
        permits_educational_research=True,
    ),
)


def research_use_assessment() -> ResearchUseAssessment:
    """Whether fpbench may execute this component locally, under its purpose.

    Derived rather than asserted: the caller supplies the observation, the
    restrictions and the readings, and Stage 8E's own engine returns the one
    decision that follows (docs/adr/0082).
    """
    return assess_research_use(
        license_observation(),
        assessment_id="verifinger_2025_2_local_research_execution",
        basis=(
            "One person, on one machine, runs the vendor's own 1:1 verification "
            "route over fingerprint images, keeps every byte of the SDK outside "
            "this public repository, publishes no template and sells nothing. "
            "Every plausible reading of both notices permits local execution for "
            "non-commercial educational research: the agreement grants use for "
            "designing, developing and testing, and the trial exists to explore "
            "the SDK's functionality. The restrictions that do bite — no "
            "redistribution, no sublicensing, a commercial licence for "
            "deployment, notice retention — are recorded and respected, and none "
            "of them touches this operation (docs/adr/0081, docs/adr/0082)."
        ),
        non_blocking_restrictions=_NON_BLOCKING_RESTRICTIONS,
        intersection_readings=_PLAUSIBLE_READINGS,
        identity_established=True,
    )


def redistribution_record() -> RedistributionRecord:
    """What upstream permits by way of redistribution, and what fpbench does."""
    return RedistributionRecord(
        decision=RedistributionDecision.NOT_ALLOWED,
        basis=(
            "The agreement forbids sharing, publishing, renting or leasing the "
            "software and any redistribution other than as prescribed. fpbench "
            "redistributes nothing in any case: the archive, the manual, the "
            "data files and every native library stay in the local artifact "
            "store, outside the working tree, and the repository holds only "
            "descriptions of them — a locator, a size, a digest (docs/adr/0083)."
        ),
        redistributed_by_fpbench=False,
    )


# ------------------------------------------------------------------- the gates


@dataclass(frozen=True, slots=True)
class Blocker:
    """One reason VeriFinger cannot enter fpbench as Algorithm 4.

    ``how_this_would_be_lifted`` is mandatory. A blocker nobody can act on is a
    blocker nobody can lift, and every blocker this stage can raise is one a
    person could lift deliberately.
    """

    gate: frozen.PreflightGate
    blocker_code: frozen.BlockerCode
    affected_component: str
    evidence: str
    why_this_blocks_algorithm_4: str
    how_this_would_be_lifted: str

    def __post_init__(self) -> None:
        permitted = dict(frozen.GATE_BLOCKERS)[self.gate]
        if self.blocker_code not in permitted:
            raise VeriFingerGateError(
                f"{self.blocker_code.value} does not belong to "
                f"{self.gate.value}; it belongs to "
                f"{[item.value for item in frozen.gate_of_blocker(self.blocker_code)]}"
                " and raising it here would put the reason in the wrong place"
            )
        for name in (
            "affected_component",
            "evidence",
            "why_this_blocks_algorithm_4",
            "how_this_would_be_lifted",
        ):
            if not str(getattr(self, name)).strip():
                raise VeriFingerGateError(f"{self.blocker_code.value}: {name} is empty")


@dataclass(frozen=True, slots=True)
class PendingAction:
    """Why a gate was not asked, where the reason is a deed rather than a defect.

    Structurally a sibling of :class:`Blocker` and semantically its opposite. A
    blocker says something is wrong with the route; a pending action says nobody
    has done a specific thing yet, names the thing, and names what doing it would
    answer. Nothing about the candidate follows from one (docs/adr/0104).
    """

    gate: frozen.PreflightGate
    action_code: frozen.PendingActionCode
    what_is_missing: str
    what_to_do: str
    what_it_would_answer: str

    def __post_init__(self) -> None:
        permitted = frozen.gate_pending_actions(self.gate)
        if self.action_code not in permitted:
            raise VeriFingerGateError(
                f"{self.action_code.value} does not belong to {self.gate.value}"
            )
        for name in ("what_is_missing", "what_to_do", "what_it_would_answer"):
            if not str(getattr(self, name)).strip():
                raise VeriFingerGateError(f"{self.action_code.value}: {name} is empty")


@dataclass(frozen=True, slots=True)
class GateResult:
    """One gate's conclusion."""

    gate: frozen.PreflightGate
    status: frozen.GateStatus
    summary: str
    blockers: tuple[Blocker, ...] = ()
    pending_actions: tuple[PendingAction, ...] = ()

    def __post_init__(self) -> None:
        if self.status is frozen.GateStatus.PASS and (
            self.blockers or self.pending_actions
        ):
            raise VeriFingerGateError(
                f"{self.gate.value}: a gate that passed carries no blockers and "
                "no outstanding actions; a blocker is not a reservation to be "
                "weighed"
            )
        if self.status is frozen.GateStatus.FAIL and not self.blockers:
            raise VeriFingerGateError(f"{self.gate.value}: a gate that failed names why")
        if self.status is frozen.GateStatus.FAIL and self.pending_actions:
            raise VeriFingerGateError(
                f"{self.gate.value}: a gate that failed found something wrong "
                "with the route, and an outstanding chore beside it would blur "
                "the two claims this stage keeps apart"
            )
        if self.status is frozen.GateStatus.ACTION_REQUIRED:
            if self.blockers:
                raise VeriFingerGateError(
                    f"{self.gate.value}: a gate awaiting an action found nothing "
                    "wrong; a blocker here would say something about VeriFinger "
                    "that nothing established"
                )
            if not self.pending_actions:
                raise VeriFingerGateError(
                    f"{self.gate.value}: a gate awaiting an action names which"
                )
        if self.status is frozen.GateStatus.NOT_REACHED and (
            self.blockers or self.pending_actions
        ):
            raise VeriFingerGateError(
                f"{self.gate.value}: a gate that was never reached cannot have "
                "found anything"
            )
        for blocker in self.blockers:
            if blocker.gate is not self.gate:
                raise VeriFingerGateError(
                    f"{self.gate.value}: carries a blocker raised at "
                    f"{blocker.gate.value}"
                )
        for action in self.pending_actions:
            if action.gate is not self.gate:
                raise VeriFingerGateError(
                    f"{self.gate.value}: carries an action raised at "
                    f"{action.gate.value}"
                )


def unresolved_score_affecting_settings() -> tuple[observed.PublishedSetting, ...]:
    """Every score-affecting setting with no upstream authority behind a value.

    The count this returns is the stage's central finding about configuration. A
    setting nobody recorded still decides the score, and "it was whatever the
    engine happened to be constructed with" is not an upstream authority — it
    becomes one only when somebody reads it off a running engine and records it
    as a ``DELIVERED_RUNTIME_DEFAULT`` (spec section 15).
    """
    return tuple(
        item
        for item in (
            *observed.PUBLISHED_EXTRACTOR_SETTINGS,
            *observed.PUBLISHED_MATCHER_SETTINGS,
        )
        if item.is_unresolved_score_affecting_default
    )


def _unresolved(items: tuple[observed.PublishedSetting, ...]) -> tuple[str, ...]:
    return tuple(
        item.name for item in items if item.is_unresolved_score_affecting_default
    )


#: One run's worth of answers about the local machine, computed once.
#:
#: Seventeen gates asking the store the same three questions meant hashing four
#: and a half gigabytes seventeen times, which turned a preflight into a
#: ninety-second operation. The cache is cleared at the top of every
#: :func:`run_preflight`, so a run always sees one consistent picture of the
#: machine and never a picture from the previous one.
_RUN_CACHE: dict[str, Any] = {}


def _cached(key: str, factory: Any) -> Any:
    if key not in _RUN_CACHE:
        _RUN_CACHE[key] = factory()
    return _RUN_CACHE[key]


def _qualification_state() -> Any:
    return _cached("qualification", store.qualification_run_state)


def _record() -> Mapping[str, Any] | None:
    """The verified qualification record, or ``None`` if there is not one."""
    state = _qualification_state()
    return state.record if state.answers_execution_gates else None


def _platform_lock() -> Mapping[str, Any] | None:
    record = _record()
    lock = None if record is None else record.get("platform_lock")
    return lock if isinstance(lock, Mapping) else None


def _delivered_defaults() -> Mapping[str, Any]:
    """The settings a running engine actually reported a value for.

    ``UNREADABLE:*`` is filtered out here rather than at the reader, so no gate
    can accidentally treat "the engine would not tell us" as a value. A setting
    nobody could read is exactly as unfrozen as a setting nobody looked for
    (spec correction 2).
    """
    record = _record()
    values = {} if record is None else record.get("delivered_runtime_defaults") or {}
    if not isinstance(values, Mapping):
        return {}
    return {
        name: value
        for name, value in values.items()
        if frozen.setting_value_is_resolved(value)
    }


def _failed_run() -> Any:
    """The state of a run that started and did not finish, or ``None``.

    Kept separate from :func:`_record` because the two mean opposite things: a
    record answers gates, and a failure *is* an answer — a real observed blocker
    rather than an outstanding chore (spec correction 5).
    """
    state = _qualification_state()
    return state if getattr(state, "failed", False) else None


def _execution_failure_blocker(gate: frozen.PreflightGate) -> Blocker:
    """The blocker a failed qualification run raises, wherever it is noticed."""
    state = _failed_run()
    return Blocker(
        gate=gate,
        blocker_code=frozen.BlockerCode.LOCAL_SMOKE_FAILED,
        affected_component=(
            "the bounded qualification run, which started and did not finish"
        ),
        evidence=(
            f"a qualification run on this machine reached {state.failed_at_stage!r} "
            f"and failed there: {state.failure_detail}. The runtime had started, "
            "so this is an observation about the route rather than an outstanding "
            "action."
        ),
        why_this_blocks_algorithm_4=(
            "Every gate that needs a running engine is unanswerable while the "
            "engine cannot complete a bounded pass over two synthetic "
            "fingerprints. A route that will not survive four comparisons will "
            "not survive six thousand."
        ),
        how_this_would_be_lifted=(
            "Diagnose the recorded step, fix the cause if it is this project's, "
            "and re-run `make stage11a-qualify`. If the cause is upstream's, that "
            "is the finding and the candidate is refused on it."
        ),
    )


def _pending_action_code() -> frozen.PendingActionCode:
    """Which of the three run reasons is actually true on this machine.

    Asked rather than assumed. "The trial is not activated" and "there is no
    Java toolchain here" are different chores with different owners, and a gate
    that reported the wrong one would send somebody to do the wrong thing.
    """
    from fpbench.experiments.stage11a_qualification import check_preconditions

    found = _cached("preconditions", check_preconditions).status.pending_action
    return found or frozen.PendingActionCode.QUALIFICATION_RUN_NOT_PERFORMED


#: What each outstanding action actually asks for, in the order the chores have
#: to be done. An earlier version told every gate to activate the trial, which
#: was wrong on a machine with no Java: it would have started a 30-day clock to
#: discover that nothing could compile against the bindings (spec correction 8).
_WHAT_TO_DO = {
    frozen.PendingActionCode.JAVA_RUNTIME_NOT_AVAILABLE: (
        "Install the toolchain first, **before** touching the trial. The main "
        "2025.2 archive ships no Python binding, so the qualification runs "
        "through upstream's Java binding, and this project pins openjdk=17 in "
        "environment.yml. Then run `make stage11a-qualify-check`, which writes "
        "nothing and starts no clock, and confirm the harness compiles against "
        "the pinned bindings. Only then is activating the trial worth doing."
    ),
    frozen.PendingActionCode.TRIAL_LICENCE_NOT_ACTIVATED: (
        "Activate the 30-day trial once, on the one platform this route is "
        "locked to — the vendor's documented route is Trial = true in the "
        "licensing configuration and starting the licensing service, with no "
        "serial number, no account and no personal information. Then run "
        "`make stage11a-qualify`. No licence is bypassed, no trial reset and no "
        "protection mechanism touched (spec section 32)."
    ),
    frozen.PendingActionCode.QUALIFICATION_RUN_NOT_PERFORMED: (
        "Everything checkable is in place: the artifacts verify and a Java "
        "toolchain is available. Run `make stage11a-qualify`. It will ask the "
        "SDK for the FingerExtractor and FingerMatcher licences and stop with "
        "TRIAL_LICENCE_NOT_ACTIVATED if the 30-day trial has not been activated "
        "— the licence is the one precondition that cannot be checked without "
        "loading the SDK, so the harness asks it rather than predicting it. The "
        "run scores only synthetic fixtures and never SD300."
    ),
    frozen.PendingActionCode.RUNTIME_PLATFORM_NOT_LOCKED: (
        "The platform is locked by the qualification run itself, which records "
        "the operating system, the architecture, the native libraries it loaded "
        "and the language runtime. Run `make stage11a-qualify-check` first: it "
        "reports which chore is actually outstanding on this machine."
    ),
}


def _what_to_do(code: frozen.PendingActionCode) -> str:
    return _WHAT_TO_DO[code]


def _execution_action(
    gate: frozen.PreflightGate,
    *,
    missing: str,
    answers: str,
    code: frozen.PendingActionCode | None = None,
) -> PendingAction:
    """The one action shape nine gates share.

    Written once rather than nine times, because nine copies of the same sentence
    drift into nine slightly different claims — and the claim matters. Nothing
    here failed. Nothing ran.
    """
    state = _qualification_state()
    return PendingAction(
        gate=gate,
        action_code=code or _pending_action_code(),
        what_is_missing=(
            f"{missing}. {state.reason}"
            + (
                f" The record present here does not verify: {state.invalid_reason}."
                if state.invalid_reason
                else ""
            )
        ),
        what_to_do=_what_to_do(code or _pending_action_code()),
        what_it_would_answer=answers,
    )


# ------------------------------------------------------------------ gate 1


def _gate_official_artifact_acquisition() -> GateResult:
    """Gate 1. Is an exact official artifact here?

    The gate Stage 10B could not pass, and the reason this stage exists in the
    shape it does: Neurotechnology publishes a direct locator, so the answer is
    settled by fetching the bytes and hashing them rather than by reading a page
    about how to request them (docs/adr/0100).
    """
    state = _cached("acquisition", store.acquisition_state)
    if state.obtained:
        return GateResult(
            gate=frozen.PreflightGate.OFFICIAL_ARTIFACT_ACQUISITION,
            status=frozen.GateStatus.PASS,
            summary=(
                f"{len(state.states)} official artifacts obtained from "
                "Neurotechnology's own download host and verified by size and "
                "SHA-256: the "
                f"{observed.SDK_ARCHIVE.size_bytes}-byte 2025.2 SDK archive and "
                f"the {observed.DOCUMENTATION_PDF.size_bytes}-byte manual, which "
                "is byte-for-byte the manual inside the archive. One route was "
                f"chosen — {observed.SDK_ARCHIVE.route.value} — and "
                f"{len(observed.REJECTED_ROUTES)} was not."
            ),
        )
    detail = "; ".join(
        f"{item.filename}: {item.presence.value} — {item.detail}"
        for item in state.unverified
    )
    return GateResult(
        gate=frozen.PreflightGate.OFFICIAL_ARTIFACT_ACQUISITION,
        status=frozen.GateStatus.FAIL,
        blockers=(
            Blocker(
                gate=frozen.PreflightGate.OFFICIAL_ARTIFACT_ACQUISITION,
                blocker_code=frozen.BlockerCode.OFFICIAL_ARTIFACT_NOT_OBTAINABLE,
                affected_component="the official VeriFinger 2025.2 artifacts",
                evidence=(
                    "acquisition-manifest.json names the locator, filename, byte "
                    f"size and SHA-256 of each artifact. On this machine: {detail}"
                ),
                why_this_blocks_algorithm_4=(
                    "Every remaining gate is a question about the artifact's own "
                    "bytes — its identity, its models, its input route, its "
                    "profiles, its score API. None of them can be answered "
                    "about an archive nobody holds, and answering them from a "
                    "product page would be publishing a benchmark route this "
                    "project had never opened."
                ),
                how_this_would_be_lifted=(
                    "Fetch the artifacts from the recorded official locators "
                    "into the local artifact store under this stage's prefix, "
                    "and re-run. The locators need no account, no form and no "
                    "vendor approval."
                ),
            ),
        ),
        summary=(
            "the frozen artifacts are not present and verified in the local "
            "artifact store"
        ),
    )


# ------------------------------------------------------------------ gate 2


def _gate_runtime_identity() -> GateResult:
    """Gate 2. Is the thing that would compute a score exactly identified?

    Two halves, and the artifact supplies only one of them.

    The **product** is identified beyond doubt from inside the pinned bytes: the
    version compiled into each native library's own resource block, the archive's
    revision file, the licence agreement's heading, and upstream's own tutorial
    declaring the version it is written for. Four independent statements, all
    2025.2, none of them a web page (spec section 6).

    The **runtime** is not, until a platform is locked. The trial is
    single-platform and the archive carries builds for five; which set of native
    libraries would actually compute a score is part of what a score means, and
    today no run has fixed it. That is a deed nobody has done, not a defect in
    the product, so the gate reports an action rather than a blocker
    (docs/adr/0104).
    """
    libraries = observed.WINDOWS_X64_NATIVE_LIBRARIES
    versions = {item.product_version for item in libraries}
    if len(versions) != 1:
        return GateResult(
            gate=frozen.PreflightGate.RUNTIME_IDENTITY,
            status=frozen.GateStatus.FAIL,
            blockers=(
                Blocker(
                    gate=frozen.PreflightGate.RUNTIME_IDENTITY,
                    blocker_code=frozen.BlockerCode.ARTIFACT_IDENTITY_UNRESOLVED,
                    affected_component="the native libraries of the chosen platform",
                    evidence=(
                        "the libraries do not agree about their own version: "
                        f"{sorted(versions)}"
                    ),
                    why_this_blocks_algorithm_4=(
                        "A route assembled from libraries of different builds is "
                        "a route with no identity to pin."
                    ),
                    how_this_would_be_lifted=(
                        "Re-acquire the archive and re-read the version "
                        "resources; a mixture means the inspected tree is not "
                        "the delivered one."
                    ),
                ),
            ),
            summary="the native libraries disagree about their own version",
        )

    product = (
        f"{observed.PRODUCT_IDENTITY_CLAIM.product_name} by "
        f"{observed.PRODUCT_IDENTITY_CLAIM.vendor}, identified from inside the "
        f"pinned bytes by "
        f"{len(observed.PRODUCT_IDENTITY_CLAIM.supporting_sources)} independent "
        f"statements; {len(libraries)} native libraries carry ProductVersion "
        f"{sorted(versions)[0]!r} and the archive declares revision 20260612"
    )
    lock = _platform_lock()
    if lock is None:
        return GateResult(
            gate=frozen.PreflightGate.RUNTIME_IDENTITY,
            status=frozen.GateStatus.ACTION_REQUIRED,
            pending_actions=(
                _execution_action(
                    frozen.PreflightGate.RUNTIME_IDENTITY,
                    code=frozen.PendingActionCode.RUNTIME_PLATFORM_NOT_LOCKED,
                    missing=(
                        "the platform this route is bound to, and the version the "
                        "running library reports"
                    ),
                    answers=(
                        "Which operating system, architecture, native libraries "
                        "and language runtime a VeriFinger score would come from "
                        "— the half of runtime identity that a file cannot state "
                        f"about itself. The lock records "
                        f"{len(frozen.RUNTIME_PLATFORM_LOCK_FIELDS)} fields at "
                        "activation, because the trial is single-platform and "
                        "alternating between two under one algorithm fingerprint "
                        "is refused whichever is chosen."
                    ),
                ),
            ),
            summary=(
                f"{frozen.IMPLEMENTATION_ORIGIN}: {product}. The platform is not "
                "locked and no version has been read from a running library, so "
                "the runtime half of the identity is outstanding."
            ),
        )
    return GateResult(
        gate=frozen.PreflightGate.RUNTIME_IDENTITY,
        status=frozen.GateStatus.PASS,
        summary=(
            f"{frozen.IMPLEMENTATION_ORIGIN}: {product}. The runtime is locked to "
            f"{lock.get('operating_system')}/{lock.get('architecture')} on "
            f"{lock.get('java_runtime_version')}, and no version here was read "
            "from a web page."
        ),
    )


# ------------------------------------------------------------------ gate 3


def _gate_research_use_permission() -> GateResult:
    """Gate 3. Does Stage 8E permit executing this component locally?

    Answered through Stage 8E's own mechanism and not beside it: an observation
    of what the notices say, an assessment derived from it, and a redistribution
    record. The notices are the ones inside the pinned archive (spec section 7).
    """
    assessment = research_use_assessment()
    if not assessment.decision.opens_execution:
        return GateResult(
            gate=frozen.PreflightGate.RESEARCH_USE_PERMISSION,
            status=frozen.GateStatus.FAIL,
            blockers=(
                Blocker(
                    gate=frozen.PreflightGate.RESEARCH_USE_PERMISSION,
                    blocker_code=frozen.BlockerCode.RESEARCH_USE_BLOCKED,
                    affected_component="the VeriFinger 2025.2 SDK",
                    evidence=(
                        "third-party-usage-binding.json: Stage 8E returned "
                        f"{assessment.decision.value} over the notices inside the "
                        "pinned archive, with blockers "
                        f"{[item.value for item in assessment.blockers]}"
                    ),
                    why_this_blocks_algorithm_4=(
                        "A component this project may not execute cannot be "
                        "qualified by executing it, and a benchmark route nobody "
                        "is permitted to run is not a route."
                    ),
                    how_this_would_be_lifted=(
                        "Only upstream can lift it, by terms that permit the "
                        "declared use. It is not lifted by reading the notices "
                        "again more optimistically (docs/adr/0082)."
                    ),
                ),
            ),
            summary=f"Stage 8E returned {assessment.decision.value}",
        )
    return GateResult(
        gate=frozen.PreflightGate.RESEARCH_USE_PERMISSION,
        status=frozen.GateStatus.PASS,
        summary=(
            f"{assessment.decision.value} with intended-use permission "
            f"{assessment.intended_use_permission_status.value}: every plausible "
            f"reading of {len(_PLAUSIBLE_READINGS)} notices inside the pinned "
            "archive permits one person executing this locally for non-commercial "
            f"educational research. {len(_NON_BLOCKING_RESTRICTIONS)} restrictions "
            "are recorded and respected, and redistribution is "
            f"{redistribution_record().decision.value} — which changes nothing, "
            "because fpbench redistributes nothing."
        ),
    )


# ------------------------------------------------------------------ gate 4


def _gate_artifact_closure() -> GateResult:
    """Gate 4. Is the runtime dependency closure complete?

    The question is whether anything the route needs lives outside the pinned
    bytes. It does not: the fingerprint algorithm's two data files ship inside
    the archive, and there is no model download at first use to pin separately
    (spec section 9).
    """
    data_files = observed.FINGER_DATA_FILES
    if not data_files:  # pragma: no cover - a constant-table mistake
        return GateResult(
            gate=frozen.PreflightGate.ARTIFACT_CLOSURE,
            status=frozen.GateStatus.FAIL,
            blockers=(
                Blocker(
                    gate=frozen.PreflightGate.ARTIFACT_CLOSURE,
                    blocker_code=(
                        frozen.BlockerCode.REQUIRED_RUNTIME_COMPONENT_MISSING
                    ),
                    affected_component="the fingerprint algorithm's data files",
                    evidence="no fingerprint data file was found in the archive",
                    why_this_blocks_algorithm_4=(
                        "An algorithm whose model is fetched from somewhere else "
                        "is an algorithm that can change without the pinned "
                        "package changing."
                    ),
                    how_this_would_be_lifted=(
                        "Locate the model, pin it by size and digest as an "
                        "artifact in its own right, and re-run."
                    ),
                ),
            ),
            summary="the closure could not be completed",
        )
    total = sum(item.size_bytes for item in data_files)
    return GateResult(
        gate=frozen.PreflightGate.ARTIFACT_CLOSURE,
        status=frozen.GateStatus.PASS,
        summary=(
            f"closed over {observed.ARCHIVE_MEMBER_COUNT} archive members "
            f"totalling {observed.ARCHIVE_UNCOMPRESSED_BYTES} bytes, every one "
            f"hashed. The fingerprint algorithm's {len(data_files)} data files — "
            f"{total} bytes — are inside the pinned archive, so nothing is "
            f"fetched at first use and the {frozen.EMBEDDED_MODEL_MARKER} case "
            "does not arise for them. No external model, service or accelerator "
            "is required."
        ),
    )


# ------------------------------------------------------------------ gate 5


def _gate_canonical500_input_route() -> GateResult:
    """Gate 5. Can ``canonical_500`` enter through an official route unchanged?

    Three things have to hold: the container is in the official input domain, the
    resolution the benchmark already carries is the resolution the SDK works in,
    and the official route asks fpbench to do nothing to the pixels
    (spec sections 11 and 12).
    """
    if frozen.BENCHMARK_INPUT_PIXEL_FORMAT != "gray8":  # pragma: no cover
        raise VeriFingerGateError("the benchmark input profile has changed")
    if "PNG" not in observed.SUPPORTED_IMAGE_CONTAINERS:  # pragma: no cover
        return GateResult(
            gate=frozen.PreflightGate.CANONICAL500_INPUT_ROUTE,
            status=frozen.GateStatus.FAIL,
            blockers=(
                Blocker(
                    gate=frozen.PreflightGate.CANONICAL500_INPUT_ROUTE,
                    blocker_code=(
                        frozen.BlockerCode.CANONICAL500_INPUT_ROUTE_UNRESOLVED
                    ),
                    affected_component="the canonical_500 PNG input",
                    evidence="PNG is not in the official input domain",
                    why_this_blocks_algorithm_4=(
                        "Converting the benchmark's images to suit a candidate "
                        "would be fpbench choosing a preprocessing step."
                    ),
                    how_this_would_be_lifted=(
                        "An upstream statement that the container is supported."
                    ),
                ),
            ),
            summary="PNG is not in the official input domain",
        )
    return GateResult(
        gate=frozen.PreflightGate.CANONICAL500_INPUT_ROUTE,
        status=frozen.GateStatus.PASS,
        summary=(
            "the pinned manual puts PNG in the official input domain, requires "
            "resolution attributes on a fingerprint image, and expresses minutia "
            "coordinates in 500 DPI units — which is what canonical_500 already "
            "is. Upstream's own 1:1 tutorial sets a file name and verifies: no "
            f"crop, no resize, no rotation, no enhancement. All "
            f"{len(frozen.REFUSED_PREPROCESSING)} refused preprocessing steps "
            "stay refused, and the segmentation and quality processing the SDK "
            "performs internally needs no external choice from fpbench."
        ),
    )


# ------------------------------------------------------------------ gate 6


def _profile_gate(
    gate: frozen.PreflightGate,
    settings: tuple[observed.PublishedSetting, ...],
    *,
    what: str,
) -> GateResult:
    """Gates 6 and 8. Is every setting that can change the score frozen?

    Two halves, and both are required. The **inventory** is closed: the pinned
    manual publishes the complete set and this stage enumerated it rather than
    guessing at names from another vendor's API. The **values** need an upstream
    authority each, and the manual states a default for every ``Faces.*``
    parameter and for no ``Fingers.*`` or ``Matching.*`` one — so the remaining
    values are delivered runtime defaults, readable only off a constructed
    engine (spec sections 14, 15 and 20; docs/adr/0101).

    Passing on a closed inventory alone would publish a profile called frozen
    while most of the settings that decide the score had no recorded value. That
    is the failure the whole apparatus exists to prevent — but it is a chore
    outstanding, not a fault in the product, so the gate waits rather than
    condemning (docs/adr/0104).
    """
    unresolved = _unresolved(settings)
    delivered = _delivered_defaults()
    still_open = tuple(name for name in unresolved if name not in delivered)
    from_sample = tuple(
        item.name
        for item in settings
        if item.is_score_affecting
        and item.provenance is frozen.SettingProvenance.OFFICIAL_SAMPLE_EXPLICIT
    )
    if not still_open:
        read = len(unresolved)
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.PASS,
            summary=(
                f"{len(settings)} published {what} settings inventoried; "
                f"{len(from_sample)} carry a value from the authoritative sample "
                f"and {read} were read off the constructed engine as delivered "
                "runtime defaults. No value was chosen by fpbench."
            ),
        )
    return GateResult(
        gate=gate,
        status=frozen.GateStatus.ACTION_REQUIRED,
        pending_actions=(
            _execution_action(
                gate,
                missing=(
                    f"a value with an upstream provenance for {len(still_open)} "
                    f"score-affecting {what} settings: " + ", ".join(still_open)
                ),
                answers=(
                    "Each of these changes the score, and the pinned manual "
                    "states a default for none of them — while stating defaults "
                    "for the face-side settings in the same tables, so the "
                    "absence is a property of the document rather than of the "
                    "reading. One constructed engine reports all of them, and "
                    "each becomes a DELIVERED_RUNTIME_DEFAULT: an upstream "
                    "authority, recorded rather than chosen."
                ),
            ),
        ),
        summary=(
            f"the inventory is closed over {len(settings)} published {what} "
            f"settings; {len(from_sample)} score-affecting values come from the "
            f"authoritative sample and {len(still_open)} are delivered runtime "
            "defaults nobody has read yet"
        ),
    )


def _gate_extraction_profile() -> GateResult:
    return _profile_gate(
        frozen.PreflightGate.EXTRACTION_PROFILE,
        observed.PUBLISHED_EXTRACTOR_SETTINGS,
        what="extraction",
    )


# ------------------------------------------------------------------ gate 7


def _gate_representation_profile() -> GateResult:
    """Gate 7. Which representation is actually compared?

    The pinned manual and upstream's own tutorials answer it: the matchers
    receive the proprietary template, and ISO and ANSI records are export formats
    the enrolment tutorial writes only when asked. Choosing ISO because it is
    easier to store would be choosing a different algorithm (spec section 18).
    """
    return GateResult(
        gate=frozen.PreflightGate.REPRESENTATION_PROFILE,
        status=frozen.GateStatus.PASS,
        summary=(
            f"{frozen.RepresentationType.VENDOR_PROPRIETARY_TEMPLATE.value}: the "
            "manual states that a packed proprietary template is what the "
            "matchers should receive, and upstream's 1:1 tutorial exports "
            "nothing. ISO and ANSI are export formats and MINEX is a separate "
            "matching scenario, so an interoperable route would be a different "
            f"profile with its own identity. Only "
            f"{len(frozen.PUBLISHABLE_REPRESENTATION_FACTS)} facts about a "
            "template are publishable and the template itself is not among them."
        ),
    )


# ------------------------------------------------------------------ gate 8


def _gate_matcher_profile() -> GateResult:
    """Gate 8, and the preset the specification warns about.

    ``FingersMatchingSpeed`` is Low, Medium and High, documented as an accuracy
    trade-off — one of which will produce nicer distributions on any dataset. It
    is settled here because **upstream's own 1:1 tutorial sets it**, and the
    profile identity records that it is the official-sample route rather than
    "the VeriFinger default", because the manual states no default
    (spec sections 16, 17 and 20).
    """
    return _profile_gate(
        frozen.PreflightGate.MATCHER_PROFILE,
        observed.PUBLISHED_MATCHER_SETTINGS,
        what="matching",
    )


# ------------------------------------------------------------------ gate 9


def _gate_raw_score_route() -> GateResult:
    """Gate 9. Is there exactly one scalar raw score, with no threshold in it?

    The decisive gate, and the artifact answers it. The manual defines the result
    of a comparison as a similarity score, higher meaning more similar; publishes
    the score-to-FAR correspondence explicitly; and keeps the threshold in a
    separate settable engine property. Upstream's own 1:1 tutorial reads the
    integer score under ``MATCH_NOT_FOUND`` as well as under ``OK``, which is the
    proof that the number survives a negative decision rather than being replaced
    by one (spec sections 21 to 24, docs/adr/0102).
    """
    return GateResult(
        gate=frozen.PreflightGate.RAW_SCORE_ROUTE,
        status=frozen.GateStatus.PASS,
        summary=(
            f"{frozen.ScoreRouteStatus.NATIVE_TRANSFORMED_SCALAR.value}: one "
            f"{observed.DOCUMENTED_SCORE_TYPE} per attempt, "
            f"{observed.DOCUMENTED_SCORE_DIRECTION}, on the vendor's own "
            "claimed-FAR scale with "
            f"{len(observed.DOCUMENTED_SCORE_ANCHORS)} published anchor points. "
            "The threshold is a separate engine property and the sample reads "
            "the score under both outcomes, so no threshold is inside the "
            "number. fpbench converts nothing in either direction."
        ),
    )


# ------------------------------------------------------------------ gates 10-13


def _gate_pair_orientation() -> GateResult:
    """Gate 10. Does ``score(A, B)`` equal ``score(B, A)``?

    A question about behaviour, and only running answers it. The API names its
    arguments reference and candidate and returns the result on the reference
    side, so the roles are distinguished — but whether the number depends on
    which side is which is not something a manual can be read off (spec 25).
    """
    orientation = (_record() or {}).get("pair_orientation")
    if isinstance(orientation, Mapping) and orientation.get(
        "both_orderings_produced_a_score"
    ):
        symmetric = bool(orientation.get("score_digests_equal"))
        return GateResult(
            gate=frozen.PreflightGate.PAIR_ORIENTATION,
            status=frozen.GateStatus.PASS,
            summary=(
                "both orderings were scored on synthetic fixtures and the score "
                + (
                    "digests agree, so the route is symmetric on this evidence"
                    if symmetric
                    else "digests differ, so the reference/probe orientation the "
                    "API defines is preserved rather than averaged away"
                )
            ),
        )
    return GateResult(
        gate=frozen.PreflightGate.PAIR_ORIENTATION,
        status=frozen.GateStatus.ACTION_REQUIRED,
        pending_actions=(
            _execution_action(
                frozen.PreflightGate.PAIR_ORIENTATION,
                missing="both orderings of a fixture pair, actually scored",
                answers=(
                    "Whether the two orderings agree. If they differ, a run that "
                    "fed pairs in whichever order they arrived would be averaging "
                    "two different measurements without saying so — and fpbench "
                    "may neither average them nor take their maximum, so the "
                    "orientation has to be discovered and preserved."
                ),
            ),
        ),
        summary="both orderings must be run on fixtures, and nothing has been run",
    )


def _gate_self_semantics() -> GateResult:
    """Gate 11. Can ``SELF(A, A)`` be executed as two independent extractions?"""
    self_result = (_record() or {}).get("self_semantics")
    if isinstance(self_result, Mapping) and self_result.get("score_present"):
        return GateResult(
            gate=frozen.PreflightGate.SELF_SEMANTICS,
            status=frozen.GateStatus.PASS,
            summary=(
                "SELF(A, A) produced a score from "
                f"{self_result.get('independent_extractions')} independent "
                "extractions with no representation reused between the two "
                "sides, so the engine does not shortcut equal inputs"
            ),
        )
    return GateResult(
        gate=frozen.PreflightGate.SELF_SEMANTICS,
        status=frozen.GateStatus.ACTION_REQUIRED,
        pending_actions=(
            _execution_action(
                frozen.PreflightGate.SELF_SEMANTICS,
                missing="SELF(A, A) executed as two independent extractions",
                answers=(
                    "Whether the engine shortcuts equal inputs. A pairwise route "
                    "that noticed both sides were the same file could return a "
                    "constant, and that constant would be a number about this "
                    "project's own plumbing rather than about the algorithm. The "
                    "rule is frozen either way — two loads, two extractions, no "
                    "representation reuse (docs/adr/0070)."
                ),
            ),
        ),
        summary="the SELF rule is frozen and its demonstration needs a running engine",
    )


def _gate_score_determinism() -> GateResult:
    """Gate 12. Is the score identical at all three levels?"""
    determinism = (_record() or {}).get("determinism")
    if isinstance(determinism, Mapping) and determinism:
        failed = sorted(
            level for level in frozen.DETERMINISM_LEVELS if not determinism.get(level)
        )
        if not failed:
            return GateResult(
                gate=frozen.PreflightGate.SCORE_DETERMINISM,
                status=frozen.GateStatus.PASS,
                summary=(
                    "one fixture pair produced the same score digest at all "
                    f"{len(frozen.DETERMINISM_LEVELS)} levels, including across a "
                    "process restart"
                ),
            )
        return GateResult(
            gate=frozen.PreflightGate.SCORE_DETERMINISM,
            status=frozen.GateStatus.FAIL,
            blockers=(
                Blocker(
                    gate=frozen.PreflightGate.SCORE_DETERMINISM,
                    blocker_code=frozen.BlockerCode.SCORE_NONDETERMINISM_OBSERVED,
                    affected_component="the score of one fixture pair",
                    evidence=(
                        "the qualification run scored the same pair repeatedly "
                        f"and the score changed at: {failed}"
                    ),
                    why_this_blocks_algorithm_4=(
                        "A benchmark whose numbers move between runs is not a "
                        "benchmark. The templates themselves may vary without "
                        "that being a failure — this stage qualifies a "
                        "verification route, not byte-identical proprietary "
                        "templates — but the score may not (spec sections 28, 29)."
                    ),
                    how_this_would_be_lifted=(
                        "An upstream statement that inference is stochastic, and "
                        "a stage that decides explicitly what to do about it. "
                        "That is not an allowance inside this one."
                    ),
                ),
            ),
            summary=f"the score is not stable at {failed}",
        )
    return GateResult(
        gate=frozen.PreflightGate.SCORE_DETERMINISM,
        status=frozen.GateStatus.ACTION_REQUIRED,
        pending_actions=(
            _execution_action(
                frozen.PreflightGate.SCORE_DETERMINISM,
                missing=(
                    "the same fixture pair scored at all "
                    f"{len(frozen.DETERMINISM_LEVELS)} levels"
                ),
                answers=(
                    "Whether a VeriFinger score is reproducible at all. This is "
                    "the one gate whose failure would be a genuine methodological "
                    "blocker rather than a chore, which is why it is measured "
                    "rather than assumed."
                ),
            ),
        ),
        summary="determinism is measured, and nothing has been measured",
    )


def _gate_failure_semantics() -> GateResult:
    """Gate 13. What does each failure class actually return?"""
    failures = (_record() or {}).get("failure_semantics")
    if isinstance(failures, list) and failures:
        scored = [
            item
            for item in failures
            if isinstance(item, Mapping) and item.get("score_present")
        ]
        if scored:
            return GateResult(
                gate=frozen.PreflightGate.FAILURE_SEMANTICS,
                status=frozen.GateStatus.FAIL,
                blockers=(
                    Blocker(
                        gate=frozen.PreflightGate.FAILURE_SEMANTICS,
                        blocker_code=frozen.BlockerCode.LOCAL_SMOKE_FAILED,
                        affected_component=(
                            "the failure classes that returned a score"
                        ),
                        evidence=(
                            "these failure classes produced a score rather than "
                            "an outcome: "
                            f"{[item.get('failure_class') for item in scored]}"
                        ),
                        why_this_blocks_algorithm_4=(
                            "A failure that arrives as a number enters a rate as "
                            "a comparison that never happened."
                        ),
                        how_this_would_be_lifted=(
                            "An adapter that maps the status to an outcome before "
                            "any score is read — which is Stage 11B's work, and "
                            "has to be designed knowing this."
                        ),
                    ),
                ),
                summary=f"{len(scored)} failure classes returned a score",
            )
        return GateResult(
            gate=frozen.PreflightGate.FAILURE_SEMANTICS,
            status=frozen.GateStatus.PASS,
            summary=(
                f"all {len(failures)} failure classes were exercised and each "
                "produced an outcome rather than a score"
            ),
        )
    return GateResult(
        gate=frozen.PreflightGate.FAILURE_SEMANTICS,
        status=frozen.GateStatus.ACTION_REQUIRED,
        pending_actions=(
            _execution_action(
                frozen.PreflightGate.FAILURE_SEMANTICS,
                missing=(
                    f"the {len(frozen.FAILURE_SEMANTICS_CLASSES)} failure classes, "
                    "each actually provoked"
                ),
                answers=(
                    "What each failure returns. A failure that arrives as a score "
                    "of 0 is a false match rate computed over comparisons that "
                    "never happened. The API has a status type beside the score, "
                    "which is the right shape — but which status each failure "
                    "produces, and whether a score sits beside it, is behaviour."
                ),
            ),
        ),
        summary="failure behaviour is observed, and nothing has been observed",
    )


# ------------------------------------------------------------------ gate 14


def _gate_network_dependency() -> GateResult:
    """Gate 14. Is the network in the licence check or in the computation?

    The distinction that decides whether the route is reproducible at all, and
    the pinned notices answer it. Internet Activation is defined in the agreement
    as storing a licence file locally that lets the component run *on that
    computer* after a licence check, with a connection needed briefly at least
    once in seven days. The extraction and matching components are native
    libraries in the archive and the data files they load are beside them; the
    server-side components the agreement lists are separately licensed and the
    1:1 route does not use them (docs/adr/0103).
    """
    return GateResult(
        gate=frozen.PreflightGate.NETWORK_DEPENDENCY,
        status=frozen.GateStatus.PASS,
        summary=(
            f"{frozen.NetworkRole.LICENSE_VALIDATION_ONLY.value}: a constant "
            "connection is required during evaluation and the pinned agreement "
            "defines what it is for — checking a licence that permits the "
            "component to run on this computer. The biometric computation is "
            "local native code over local data files, so no part of the score "
            "depends on a service that could change without the pinned package "
            "changing."
        ),
    )


# ------------------------------------------------------------------ gate 15


def _gate_runtime_feasibility() -> GateResult:
    """Gate 15. Does the route run here, at a workable cost?"""
    feasibility = (_record() or {}).get("feasibility")
    if isinstance(feasibility, Mapping) and feasibility:
        if feasibility.get("accelerator_required"):
            return GateResult(
                gate=frozen.PreflightGate.RUNTIME_FEASIBILITY,
                status=frozen.GateStatus.FAIL,
                blockers=(
                    Blocker(
                        gate=frozen.PreflightGate.RUNTIME_FEASIBILITY,
                        blocker_code=(
                            frozen.BlockerCode.REQUIRED_RUNTIME_COMPONENT_MISSING
                        ),
                        affected_component="an accelerator this project does not have",
                        evidence="the qualification run reported one as required",
                        why_this_blocks_algorithm_4=frozen.RARE_DEPENDENCY_RULE,
                        how_this_would_be_lifted=(
                            "Hardware this project does not have, or an upstream "
                            "route that does not need it."
                        ),
                    ),
                ),
                summary="the route needs an accelerator this project does not have",
            )
        return GateResult(
            gate=frozen.PreflightGate.RUNTIME_FEASIBILITY,
            status=frozen.GateStatus.PASS,
            summary=(
                "measured on fixtures only: startup "
                f"{feasibility.get('startup_millis')} ms, "
                f"{feasibility.get('extraction_invocations')} extractions in "
                f"{feasibility.get('extraction_millis_total')} ms, "
                f"{feasibility.get('matching_invocations')} matches in "
                f"{feasibility.get('matching_millis_total')} ms, about "
                f"{feasibility.get('peak_heap_megabytes')} MB of heap, no "
                "accelerator required. Orders of magnitude, not a benchmark, and "
                "no comparison with any other algorithm."
            ),
        )
    return GateResult(
        gate=frozen.PreflightGate.RUNTIME_FEASIBILITY,
        status=frozen.GateStatus.ACTION_REQUIRED,
        pending_actions=(
            _execution_action(
                frozen.PreflightGate.RUNTIME_FEASIBILITY,
                missing=(
                    f"the {len(frozen.RUNTIME_FEASIBILITY_MEASUREMENTS)} "
                    "feasibility measurements"
                ),
                answers=(
                    "What the route costs per operation. A second per extraction "
                    "turns the frozen workload's "
                    f"{frozen.FROZEN_WORKLOAD.extraction_invocations} extractions "
                    "into hours, and that is worth knowing before the run rather "
                    "than during it — and it is what the licence-capacity gate "
                    "needs in order to decide anything at all."
                ),
            ),
        ),
        summary="latency and memory are measured, and nothing has been measured",
    )


# ------------------------------------------------------------------ gate 16


def _gate_license_capacity() -> GateResult:
    """Gate 16. Can the licence carry the whole frozen workload?

    Unlike Stage 10B's candidate there is a number: thirty days, stated in the
    pinned activation guide, with no API-call quota stated anywhere in it. The
    other half of the question — whether the workload fits inside those thirty
    days — is arithmetic over a latency the feasibility gate measures, so this
    gate waits for that rather than guessing at it (spec section 35).
    """
    terms = observed.TRIAL_TERMS
    load = frozen.FROZEN_WORKLOAD
    feasibility = (_record() or {}).get("feasibility")
    if isinstance(feasibility, Mapping) and feasibility:
        # One number, because the route has one entry point. ``verify`` loads
        # both images, extracts both templates and matches them behind a single
        # call, so the protocol costs 6,000 verify calls. The 12,000 extractions
        # remain the logical execution semantics — two independent extractions
        # per comparison — and are not a second thing to bill for
        # (spec correction 7).
        calls = max(int(feasibility.get("verify_invocations") or 0), 1)
        per_verify_millis = (
            float(feasibility.get("end_to_end_verify_millis_total") or 0) / calls
        )
        projected_seconds = (
            per_verify_millis * frozen.FROZEN_VERIFICATION_ATTEMPTS
        ) / 1000.0
        window_seconds = terms.duration_days * 24 * 3600
        if projected_seconds >= window_seconds:
            return GateResult(
                gate=frozen.PreflightGate.LICENSE_CAPACITY,
                status=frozen.GateStatus.FAIL,
                blockers=(
                    Blocker(
                        gate=frozen.PreflightGate.LICENSE_CAPACITY,
                        blocker_code=(
                            frozen.BlockerCode.LICENSE_WORKLOAD_CAPACITY_INSUFFICIENT
                        ),
                        affected_component=(
                            f"the {terms.duration_days}-day trial against "
                            f"{frozen.FROZEN_VERIFICATION_ATTEMPTS} verification "
                            "attempts"
                        ),
                        evidence=(
                            "the measured end-to-end verify latency projects the "
                            "frozen workload to about "
                            f"{projected_seconds / 3600:.1f} hours, against a "
                            f"{terms.duration_days}-day window"
                        ),
                        why_this_blocks_algorithm_4=(
                            "A quota or a clock that runs out partway through "
                            "6,000 comparisons produces a partial run, and a "
                            "partial run is not a smaller result."
                        ),
                        how_this_would_be_lifted=(
                            "A developer licence rather than a trial, or a route "
                            "whose per-operation cost fits the window."
                        ),
                    ),
                ),
                summary="the frozen workload does not fit the trial window",
            )
        return GateResult(
            gate=frozen.PreflightGate.LICENSE_CAPACITY,
            status=frozen.GateStatus.PASS,
            summary=(
                f"{frozen.FROZEN_VERIFICATION_ATTEMPTS} verification attempts at "
                f"the measured end-to-end latency project to about "
                f"{projected_seconds / 3600:.1f} hours, inside the "
                f"{terms.duration_days}-day trial window. No API-call quota is "
                "stated anywhere in the pinned activation guide, and that absence "
                "is recorded as an absence rather than read as permission."
            ),
        )
    return GateResult(
        gate=frozen.PreflightGate.LICENSE_CAPACITY,
        status=frozen.GateStatus.ACTION_REQUIRED,
        pending_actions=(
            _execution_action(
                frozen.PreflightGate.LICENSE_CAPACITY,
                missing=(
                    "the end-to-end verify latency the expiry has to be weighed "
                    "against"
                ),
                answers=(
                    f"Whether {frozen.FROZEN_VERIFICATION_ATTEMPTS} verification "
                    f"attempts fit inside {terms.duration_days} days. The expiry "
                    "is known and the per-call cost is not, so the product of the "
                    "two is not known either. The protocol's "
                    f"{load.extraction_invocations} extractions remain its "
                    "logical semantics — two per comparison — and are not billed "
                    "separately, because the route's only entry point is one "
                    "verify call per attempt. Two further terms are recorded "
                    "rather than assumed away: the trial needs a constant "
                    "internet connection, and it excludes simultaneous use of "
                    "licensed Neurotechnology products on the same computer."
                ),
            ),
        ),
        summary=(
            f"a {terms.duration_days}-day trial with no stated call quota, and a "
            "per-operation cost nobody has measured"
        ),
    )


# ------------------------------------------------------------------ gate 17


def _gate_training_provenance() -> GateResult:
    """Gate 17. Was this algorithm developed on the evaluation cohort?

    A commercial vendor is not asked to publish its training corpus as a
    condition of entry; that condition would exclude every commercial matcher by
    accident rather than by decision. What is required is that the record says
    plainly what is undisclosed, and never converts silence into absence
    (spec sections 36 to 38).
    """
    return GateResult(
        gate=frozen.PreflightGate.TRAINING_PROVENANCE,
        status=frozen.GateStatus.PASS,
        summary=(
            f"{frozen.TrainingProvenanceStatus.PROPRIETARY_UNDISCLOSED.value} "
            f"with {frozen.SD300OverlapStatus.NO_EVIDENCE_FOUND.value}: no pinned "
            "source mentions SD300 in any role, and none describes the corpus the "
            "algorithm was developed on. That is an absence of evidence, recorded "
            "as one and never converted into PROVEN_ABSENT. No score distribution "
            "was consulted to answer it."
        ),
    )


_GATE_RUNNERS = {
    frozen.PreflightGate.OFFICIAL_ARTIFACT_ACQUISITION: (
        _gate_official_artifact_acquisition
    ),
    frozen.PreflightGate.RUNTIME_IDENTITY: _gate_runtime_identity,
    frozen.PreflightGate.RESEARCH_USE_PERMISSION: _gate_research_use_permission,
    frozen.PreflightGate.ARTIFACT_CLOSURE: _gate_artifact_closure,
    frozen.PreflightGate.CANONICAL500_INPUT_ROUTE: _gate_canonical500_input_route,
    frozen.PreflightGate.EXTRACTION_PROFILE: _gate_extraction_profile,
    frozen.PreflightGate.REPRESENTATION_PROFILE: _gate_representation_profile,
    frozen.PreflightGate.MATCHER_PROFILE: _gate_matcher_profile,
    frozen.PreflightGate.RAW_SCORE_ROUTE: _gate_raw_score_route,
    frozen.PreflightGate.PAIR_ORIENTATION: _gate_pair_orientation,
    frozen.PreflightGate.SELF_SEMANTICS: _gate_self_semantics,
    frozen.PreflightGate.SCORE_DETERMINISM: _gate_score_determinism,
    frozen.PreflightGate.FAILURE_SEMANTICS: _gate_failure_semantics,
    frozen.PreflightGate.NETWORK_DEPENDENCY: _gate_network_dependency,
    frozen.PreflightGate.RUNTIME_FEASIBILITY: _gate_runtime_feasibility,
    frozen.PreflightGate.LICENSE_CAPACITY: _gate_license_capacity,
    frozen.PreflightGate.TRAINING_PROVENANCE: _gate_training_provenance,
}


def _unreached_reason(stopped_at: frozen.PreflightGate) -> str:
    return (
        f"the candidate stopped at {stopped_at.value}, so this question was "
        "never asked"
    )


@dataclass(frozen=True, slots=True)
class VeriFingerPreflight:
    """The whole preflight: every gate, the verdict, and the outcome."""

    results: tuple[GateResult, ...]
    stopped_at: frozen.PreflightGate | None
    preflight_fingerprint: str

    def __post_init__(self) -> None:
        seen = tuple(result.gate for result in self.results)
        if seen != frozen.GATE_ORDER:
            raise VeriFingerGateError(
                f"the gates were reported as {seen} and the frozen order is "
                f"{frozen.GATE_ORDER}"
            )
        failed = [
            result.gate
            for result in self.results
            if result.status is frozen.GateStatus.FAIL
        ]
        if len(failed) > 1:
            raise VeriFingerGateError(
                f"fail-fast means one failing gate, and these failed: {failed}"
            )
        if failed and failed[0] is not self.stopped_at:
            raise VeriFingerGateError(
                f"the stopping gate is {self.stopped_at} and the failing gate is "
                f"{failed[0]}"
            )
        if not failed and self.stopped_at is not None:
            raise VeriFingerGateError(f"stopped at {self.stopped_at} with no failure")

    @property
    def passed(self) -> bool:
        """Every gate passed. Not "no gate failed": neither ACTION_REQUIRED nor
        NOT_REACHED is a pass."""
        return all(result.status is frozen.GateStatus.PASS for result in self.results)

    @property
    def blocked(self) -> bool:
        """A real blocker was found. The only state that says something is wrong."""
        return any(
            result.status is frozen.GateStatus.FAIL for result in self.results
        )

    @property
    def incomplete(self) -> bool:
        """Everything asked was answered, and something was not asked."""
        return not self.passed and not self.blocked

    @property
    def verdict(self) -> str:
        if self.blocked:
            return frozen.CANDIDATE_FAIL_VERDICT
        return (
            frozen.CANDIDATE_PASS_VERDICT
            if self.passed
            else frozen.CANDIDATE_INCOMPLETE_VERDICT
        )

    @property
    def outcome(self) -> str:
        return self.verdict

    @property
    def selected_candidate(self) -> str | None:
        return frozen.CANDIDATE_ID if self.passed else None

    @property
    def failure_class(self) -> frozen.FailureClass | None:
        """What kind of failure this is, and ``None`` unless there is one.

        An incomplete preflight has no failure class, and that is the whole
        correction: classifying "nobody has run it" as a failure of any kind was
        saying something about VeriFinger that nothing had established
        (docs/adr/0104).
        """
        if not self.blocked:
            return None
        codes = {blocker.blocker_code for blocker in self.blockers}
        if frozen.BlockerCode.OFFICIAL_ARTIFACT_NOT_OBTAINABLE in codes:
            return frozen.FailureClass.ARTIFACT_NOT_OBTAINED
        if frozen.BlockerCode.RESEARCH_USE_BLOCKED in codes:
            return frozen.FailureClass.RESEARCH_USE_REFUSED
        if frozen.BlockerCode.SD300_TRAINING_OVERLAP_FOUND in codes:
            return frozen.FailureClass.SD300_DEVELOPMENT_OVERLAP
        if frozen.BlockerCode.LICENSE_WORKLOAD_CAPACITY_INSUFFICIENT in codes:
            return frozen.FailureClass.LICENSE_CAPACITY_INSUFFICIENT
        if codes & {
            frozen.BlockerCode.SCORE_NONDETERMINISM_OBSERVED,
            frozen.BlockerCode.LOCAL_SMOKE_FAILED,
        }:
            return frozen.FailureClass.EXECUTION_NOT_ESTABLISHED
        return frozen.FailureClass.ROUTE_NOT_QUALIFIABLE

    @property
    def artifact_was_opened(self) -> bool:
        """Whether this stage's conclusions rest on the artifact's own bytes."""
        return (
            self.status(frozen.PreflightGate.OFFICIAL_ARTIFACT_ACQUISITION)
            is frozen.GateStatus.PASS
        )

    @property
    def sd300_overlap_status(self) -> frozen.SD300OverlapStatus:
        if (
            self.status(frozen.PreflightGate.TRAINING_PROVENANCE)
            is frozen.GateStatus.PASS
        ):
            return frozen.SD300OverlapStatus.NO_EVIDENCE_FOUND
        return frozen.SD300OverlapStatus.NOT_REACHED

    @property
    def gates_reached(self) -> int:
        return sum(
            1
            for result in self.results
            if result.status is not frozen.GateStatus.NOT_REACHED
        )

    @property
    def gates_passed(self) -> int:
        return sum(
            1 for result in self.results if result.status is frozen.GateStatus.PASS
        )

    @property
    def gates_awaiting_action(self) -> int:
        return sum(
            1
            for result in self.results
            if result.status is frozen.GateStatus.ACTION_REQUIRED
        )

    @property
    def blockers(self) -> tuple[Blocker, ...]:
        return tuple(
            sorted(
                (blocker for result in self.results for blocker in result.blockers),
                key=lambda item: item.blocker_code.value,
            )
        )

    @property
    def pending_actions(self) -> tuple[PendingAction, ...]:
        return tuple(
            sorted(
                (
                    action
                    for result in self.results
                    for action in result.pending_actions
                ),
                key=lambda item: (
                    list(frozen.GATE_ORDER).index(item.gate),
                    item.action_code.value,
                ),
            )
        )

    @property
    def distinct_pending_action_codes(self) -> tuple[str, ...]:
        return tuple(
            sorted({action.action_code.value for action in self.pending_actions})
        )

    def result(self, gate: frozen.PreflightGate) -> GateResult:
        for item in self.results:
            if item.gate is gate:
                return item
        raise KeyError(gate)  # pragma: no cover - GATE_ORDER is exhaustive

    def status(self, gate: frozen.PreflightGate) -> frozen.GateStatus:
        return self.result(gate).status


def run_preflight() -> VeriFingerPreflight:
    """Run the gate order, stopping only at a real blocker.

    **A gate awaiting an action does not stop the run**, and that is the change
    the second review forced. Fail-fast exists so that a broken route is not
    investigated expensively; it was never meant to make an unpaid chore hide
    nine later answers. Most of these gates do not depend on each other — the
    representation, the raw score, the network role and the provenance are all
    answerable from the artifact whatever the extraction profile is doing — so
    they are asked, and the ones that genuinely need a run each say so for
    themselves (docs/adr/0104).
    """
    _RUN_CACHE.clear()
    results: list[GateResult] = []
    stopped_at: frozen.PreflightGate | None = None
    for gate in frozen.GATE_ORDER:
        if stopped_at is not None:
            results.append(
                GateResult(
                    gate=gate,
                    status=frozen.GateStatus.NOT_REACHED,
                    summary=_unreached_reason(stopped_at),
                )
            )
            continue
        runner = _GATE_RUNNERS.get(gate)
        if runner is None:  # pragma: no cover - the table is exhaustive
            raise VeriFingerGateError(
                f"the candidate survived to {gate.value} and Stage 11A has no "
                "runner for it. A gate without a runner is an unanswered "
                "question, not a passed one"
            )
        result = runner()
        # A run that started and failed converts every outstanding action into a
        # real blocker, in one place rather than in nine gate bodies. The gates
        # ask "has this been measured"; whether the reason it was not is a chore
        # or a failure is one fact about the machine, and it belongs here
        # (spec correction 5).
        if result.status is frozen.GateStatus.ACTION_REQUIRED and _failed_run():
            result = GateResult(
                gate=gate,
                status=frozen.GateStatus.FAIL,
                summary=(
                    "a qualification run started on this machine and failed, so "
                    "this question has an answer and the answer is adverse"
                ),
                blockers=(_execution_failure_blocker(gate),),
            )
        results.append(result)
        if result.status is frozen.GateStatus.FAIL:
            stopped_at = gate
    return VeriFingerPreflight(
        results=tuple(results),
        stopped_at=stopped_at,
        preflight_fingerprint=stable_hash(
            {
                "schema": "stage_11a_preflight_v2",
                "candidate_id": frozen.CANDIDATE_ID,
                "gates": [
                    (result.gate.value, result.status.value) for result in results
                ],
                "blockers": sorted(
                    blocker.blocker_code.value
                    for result in results
                    for blocker in result.blockers
                ),
                "pending_actions": sorted(
                    f"{action.gate.value}:{action.action_code.value}"
                    for result in results
                    for action in result.pending_actions
                ),
                "observations": observed.observations_fingerprint(),
            },
            length=64,
        ),
    )


# --------------------------------------------------------------- the secret guard

_SENSITIVE_PATTERNS = tuple(
    (name, re.compile(source)) for name, source in frozen.SENSITIVE_VALUE_PATTERNS
)


def find_sensitive_material(node: Any, trail: str = "") -> tuple[str, ...]:
    """Every place a document carries a credential, by key or by value shape.

    Walks the document as *data*. A key match is reported wherever it appears; a
    value match is reported for any string, at any depth, including inside a
    list.
    """
    found: list[str] = []
    if isinstance(node, Mapping):
        for key, value in node.items():
            name = str(key)
            where = f"{trail}.{name}" if trail else name
            if name.strip().lower() in frozen.SENSITIVE_EVIDENCE_KEYS:
                found.append(f"{where}: a key that names licence material")
            found.extend(find_sensitive_material(value, where))
    elif isinstance(node, (list, tuple)):
        for index, item in enumerate(node):
            found.extend(find_sensitive_material(item, f"{trail}[{index}]"))
    elif isinstance(node, str):
        for name, pattern in _SENSITIVE_PATTERNS:
            if pattern.search(node):
                found.append(f"{trail or '<root>'}: a value shaped like {name}")
    return tuple(sorted(set(found)))


def require_no_sensitive_material(node: Any, *, where: str) -> None:
    """The raising form, for the publisher.

    Raises:
        VeriFingerSensitiveEvidenceError: the document carries, or is about to
            carry, something shaped like licence material. The publisher stops
            rather than redacting: a redaction that silently succeeds is how the
            second one gets missed (spec section 43).
    """
    findings = find_sensitive_material(node)
    if findings:
        raise VeriFingerSensitiveEvidenceError(
            f"{where} carries licence material and will not be published: "
            f"{list(findings)}"
        )


# --------------------------------------------------------- published documents


def _gate_header(
    preflight: VeriFingerPreflight, gate: frozen.PreflightGate, schema: str
) -> dict[str, Any]:
    result = preflight.result(gate)
    return {
        "schema": schema,
        "candidate": frozen.CANDIDATE_ID,
        "gate": gate.value,
        "gate_status": result.status.value,
        "gate_status_is_a_finding": result.status.is_a_finding,
        "gate_summary": result.summary,
        "blocker_codes": [item.blocker_code.value for item in result.blockers],
        "pending_action_codes": [
            item.action_code.value for item in result.pending_actions
        ],
        "pending_actions": [
            {
                "action_code": item.action_code.value,
                "what_is_missing": item.what_is_missing,
                "what_to_do": item.what_to_do,
                "what_it_would_answer": item.what_it_would_answer,
            }
            for item in result.pending_actions
        ],
    }


def _candidate_identity_document(
    preflight: VeriFingerPreflight,
) -> Mapping[str, Any]:
    claim = observed.PRODUCT_IDENTITY_CLAIM
    load = frozen.FROZEN_WORKLOAD
    return {
        "schema": "stage_11a_candidate_identity_v1",
        "algorithm_slot": frozen.ALGORITHM_SLOT,
        "question": (
            "does an official, exact VeriFinger 2025.2 artifact let fpbench take "
            "canonical_500 in and get a reproducible raw 1:1 score out, with "
            "every externally selectable behaviour that can affect that score "
            "defined by Neurotechnology rather than invented here"
        ),
        "candidate_id": frozen.CANDIDATE_ID,
        "candidate_id_is_provisional": True,
        "implementation_origin": frozen.IMPLEMENTATION_ORIGIN,
        "production_algorithm_id_frozen": frozen.PRODUCTION_ALGORITHM_ID_FROZEN,
        "final_identity_would_have_to_name": list(frozen.FINAL_IDENTITY_COMPONENTS),
        "product_name": claim.product_name,
        "vendor": claim.vendor,
        "declared_version": claim.declared_version,
        "identity_sources_inside_the_artifact": list(claim.supporting_sources),
        "declared_non_candidates": [
            {"identity": name, "description": description}
            for name, description in frozen.DECLARED_NON_CANDIDATES
        ],
        "predecessor": {
            "stage": "stage_10b",
            "outcome": frozen.STAGE_10B_OUTCOME,
            "finalization_fingerprint": frozen.STAGE_10B_FINALIZATION_FINGERPRINT,
            "relation": (
                "Stage 10B preflighted the id3 Finger SDK, failed at its "
                "acquisition gate, reserved Stage 10C for that candidate and "
                "opened a candidate search. Stage 11A is that search's next "
                "candidate and adds nothing to Stage 10B."
            ),
            "stage_10b_evidence_modified_by_stage_11a": False,
        },
        "gate_order": [gate.value for gate in frozen.GATE_ORDER],
        "gates_are_conjunctive_and_unweighted": True,
        "gate_count_defined": frozen.GATE_COUNT,
        "gates_reached": preflight.gates_reached,
        "gates_passed": preflight.gates_passed,
        "benchmark_input": {
            "profile": frozen.BENCHMARK_INPUT_PROFILE,
            "ppi": frozen.BENCHMARK_INPUT_PPI,
            "pixel_format": frozen.BENCHMARK_INPUT_PIXEL_FORMAT,
        },
        "frozen_workload": {
            "participating_images": load.participating_images,
            "participating_images_is_a_cohort_not_an_operation_count": True,
            "comparison_attempts": load.comparison_attempts,
            "extractions_per_comparison": 2,
            "extraction_invocations": load.extraction_invocations,
            "matcher_invocations": load.matcher_invocations,
            "execution_semantics_source": (
                "the Stage 8C execution semantics, which published 12,000 "
                "logical extractions over the same 6,000 comparisons"
            ),
        },
        "setting_provenance_vocabulary": [
            item.value
            for item in frozen.SettingProvenance
            if item is not frozen.SettingProvenance.UNRESOLVED
        ],
        "refused_setting_provenance": frozen.REFUSED_SETTING_PROVENANCE,
        "non_goals": list(frozen.NON_GOALS),
        "production_integration_not_created": [
            {"surface": name, "created": False}
            for name in frozen.PRODUCTION_INTEGRATION_NOT_CREATED
        ],
        "stage_11b_scope_if_this_passes": list(frozen.STAGE_11B_SCOPE),
        "observations_fingerprint": observed.observations_fingerprint(),
    }


def _acquisition_manifest_document(
    preflight: VeriFingerPreflight,
) -> Mapping[str, Any]:
    document = _gate_header(
        preflight,
        frozen.PreflightGate.OFFICIAL_ARTIFACT_ACQUISITION,
        "stage_11a_acquisition_manifest_v1",
    )
    state = _cached("acquisition", store.acquisition_state)
    document["acquisition_status"] = state.status.value
    document["possession"] = state.possession.value
    document["artifact_route_chosen"] = observed.SDK_ARCHIVE.route.value
    document["routes_are_never_mixed"] = True
    document["pin_fields_required_before_import"] = list(
        frozen.ACQUISITION_PIN_FIELDS
    )
    document["excluded_from_evidence"] = list(frozen.EXCLUDED_FROM_EVIDENCE)
    document["acquired_artifacts"] = [
        {
            "artifact_id": item.artifact_id,
            "route": item.route.value,
            "official_locator_category": item.official_locator_category,
            "locator": item.locator,
            "filename": item.filename,
            "size_bytes": item.size_bytes,
            "sha256": item.sha256,
            "downloaded_utc": item.downloaded_utc,
            "declared_version": item.declared_version,
            "target_operating_systems": list(item.target_operating_systems),
            "target_architectures": list(item.target_architectures),
            "role": item.role,
            "local_verification": state.state(item.artifact_id).presence.value,
        }
        for item in observed.ACQUIRED_ARTIFACTS
    ]
    document["rejected_routes"] = [
        {
            "route": item.route.value,
            "locator": item.locator,
            "filename": item.filename,
            "size_bytes": item.size_bytes,
            "declared_version": item.declared_version,
            "why_not_this_route": item.why_not_this_route,
            "bytes_downloaded": 0,
        }
        for item in observed.REJECTED_ROUTES
    ]
    document["documentation_is_a_separate_pinned_artifact"] = True
    document["documentation_matches_the_copy_inside_the_archive"] = True
    document["observations"] = observed.observation_rows(
        observed.ACQUISITION_OBSERVATIONS
    )
    document["notes"] = [
        "Stage 10B's candidate published no self-service download and the honest "
        "result was that nobody had walked the route. This vendor publishes a "
        "direct locator, so the first act of this stage was the download "
        "(docs/adr/0100).",
        "No signed URL, token, cookie or credential took part in either "
        "transfer, and the artifact class has no field one could be recorded in.",
    ]
    return document


def _artifact_manifest_document(preflight: VeriFingerPreflight) -> Mapping[str, Any]:
    document = _gate_header(
        preflight,
        frozen.PreflightGate.OFFICIAL_ARTIFACT_ACQUISITION,
        "stage_11a_artifact_manifest_v1",
    )
    closure = preflight.result(frozen.PreflightGate.ARTIFACT_CLOSURE)
    document["closure_gate"] = frozen.PreflightGate.ARTIFACT_CLOSURE.value
    document["closure_gate_status"] = closure.status.value
    document["closure_gate_summary"] = closure.summary
    document["archive_member_count"] = observed.ARCHIVE_MEMBER_COUNT
    document["archive_uncompressed_bytes"] = observed.ARCHIVE_UNCOMPRESSED_BYTES
    document["every_member_was_hashed"] = True
    document["artifact_classes_inventoried"] = list(frozen.ARTIFACT_CLOSURE_CLASSES)
    document["external_model_downloads_required"] = 0
    document["embedded_model_marker"] = frozen.EMBEDDED_MODEL_MARKER
    document["checkpoint_file_required"] = False
    document["why_no_checkpoint_is_required"] = (
        "This is a black-box commercial matcher. Its algorithm data ships as "
        "vendor data files inside the pinned archive, and where a model has no "
        "separate file at all the correct record is "
        f"{frozen.EMBEDDED_MODEL_MARKER} rather than a missing artifact "
        "(spec section 10)."
    )
    document["fingerprint_data_files"] = [
        {
            "relative_path": item.relative_path,
            "size_bytes": item.size_bytes,
            "sha256": item.sha256,
            "role": item.role,
            "inside_the_pinned_archive": True,
        }
        for item in observed.FINGER_DATA_FILES
    ]
    document["cited_members"] = [
        {
            "relative_path": item.relative_path,
            "size_bytes": item.size_bytes,
            "sha256": item.sha256,
            "role": item.role,
        }
        for item in observed.CITED_ARCHIVE_MEMBERS
    ]
    document["java_binding_jars"] = [
        {
            "relative_path": item.relative_path,
            "size_bytes": item.size_bytes,
            "sha256": item.sha256,
            "role": item.role,
        }
        for item in observed.JAVA_BINDING_JARS
    ]
    document["rare_dependency_rule"] = frozen.RARE_DEPENDENCY_RULE
    document["accelerator_required"] = False
    document["further_proprietary_service_required"] = False
    document["bytes_of_any_of_this_in_git"] = 0
    document["observations"] = observed.observation_rows(
        observed.CLOSURE_OBSERVATIONS
    )
    return document


def _runtime_identity_document(preflight: VeriFingerPreflight) -> Mapping[str, Any]:
    document = _gate_header(
        preflight,
        frozen.PreflightGate.RUNTIME_IDENTITY,
        "stage_11a_runtime_identity_v1",
    )
    document["identity_fields_required"] = list(frozen.RUNTIME_IDENTITY_FIELDS)
    document["identity_source"] = "PINNED_ARTIFACT_BINARIES_AND_DOCUMENTS"
    document["a_web_page_version_is_not_an_algorithm_identity"] = True
    document["web_page_version_used_as_identity"] = False
    document["runtime_reported_version_read_by_execution"] = False
    document["why_not_read_by_execution"] = (
        _qualification_state().reason
    )
    document["declared_version"] = observed.PRODUCT_IDENTITY_CLAIM.declared_version
    document["archive_revision_number"] = "20260612"
    document["archive_revision_hash"] = (
        "0738caf6a69459241bff6e800789cd61c160bbce"
    )
    document["language_bindings_in_the_archive"] = list(
        observed.LANGUAGE_BINDINGS_IN_ARCHIVE
    )
    document["python_binding_in_main_sdk"] = observed.PYTHON_BINDING_IN_MAIN_SDK
    document["python_package_version"] = None
    document["python_abi"] = None
    document["why_the_python_fields_are_null"] = (
        "The main 2025.2 archive ships no Python binding, so there is no Python "
        "package version and no Python ABI to record for this route. The "
        "vendor's Python distribution is version 2025.1 and is a different "
        "artifact, refused at the route decision (spec section 3)."
    )
    document["operating_systems_available"] = list(
        observed.SDK_ARCHIVE.target_operating_systems
    )
    document["architectures_available"] = list(
        observed.SDK_ARCHIVE.target_architectures
    )
    document["platform_locked"] = False
    document["why_platform_not_locked"] = (
        "The trial is single-platform, so the target is a decision taken before "
        "activation. No activation has been attempted, so no platform has been "
        "locked, and alternating between two platforms under one algorithm "
        "fingerprint is refused whichever one is eventually chosen."
    )
    document["native_libraries"] = [
        {
            "relative_path": item.relative_path,
            "size_bytes": item.size_bytes,
            "sha256": item.sha256,
            "product_name": item.product_name,
            "file_description": item.file_description,
            "product_version": item.product_version,
        }
        for item in observed.WINDOWS_X64_NATIVE_LIBRARIES
    ]
    document["observations"] = observed.observation_rows(
        observed.IDENTITY_OBSERVATIONS
    )
    return document


def _third_party_usage_binding_document(
    preflight: VeriFingerPreflight,
) -> Mapping[str, Any]:
    document = _gate_header(
        preflight,
        frozen.PreflightGate.RESEARCH_USE_PERMISSION,
        "stage_11a_third_party_usage_binding_v1",
    )
    observation = license_observation()
    assessment = research_use_assessment()
    redistribution = redistribution_record()
    document["mechanism"] = "stage_8e"
    document["stage_8e_policy_fingerprint"] = frozen.STAGE8E_POLICY_FINGERPRINT
    document["stage_8e_purpose_fingerprint"] = frozen.STAGE8E_PURPOSE_FINGERPRINT
    document["license_observation"] = {
        "observation_id": observation.observation_id,
        "component_kind": observation.component_kind.value,
        "subject": observation.subject,
        "status": observation.status.value,
        "declared_license_names": list(observation.declared_license_names),
        "stated_restrictions": list(observation.stated_restrictions),
        "evidence": [
            {
                "locator": item.locator,
                "description": item.description,
                "document_sha256": item.document_sha256,
            }
            for item in observation.evidence
        ],
        "observation_fingerprint": observation.observation_fingerprint,
    }
    document["research_use_assessment"] = {
        "assessment_id": assessment.assessment_id,
        "observation_fingerprint": assessment.observation_fingerprint,
        "decision": assessment.decision.value,
        "opens_execution": assessment.decision.opens_execution,
        "intended_use_permission_status": (
            assessment.intended_use_permission_status.value
        ),
        "intersection_permits_intended_use": (
            assessment.intersection_permits_intended_use
        ),
        "non_blocking_restrictions": [
            item.value for item in assessment.non_blocking_restrictions
        ],
        "blockers": [item.value for item in assessment.blockers],
        "basis": assessment.basis,
        "assessment_fingerprint": assessment.assessment_fingerprint,
    }
    document["redistribution_record"] = {
        "decision": redistribution.decision.value,
        "redistributed_by_fpbench": redistribution.redistributed_by_fpbench,
        "basis": redistribution.basis,
    }
    document["vocabulary_limitation"] = (
        "Stage 8E's observation vocabulary has no member for a proprietary "
        "commercial SDK licence. NON_COMMERCIAL is the narrowest member that is "
        "true of the route acquired here — the trial, whose stated purpose is to "
        "explore SDK functionality rather than to deploy — and it is published "
        "beside COMMERCIAL_LICENSE_REQUIRED_FOR_COMMERCIAL_DEPLOYMENT so that "
        "both halves are visible. Stage 8E is closed and was not extended to add "
        "a member (docs/adr/0099)."
    )
    document["open_question_for_stage_11b"] = (
        "The agreement does not address publishing measurements obtained with "
        "the SDK. Stage 11A publishes no score, so the question is not live "
        "here; a stage that published 6,000 of them would have to settle it "
        "first, and it is recorded now rather than discovered then."
    )
    document["usage_manifest_written"] = False
    document["why_no_usage_manifest"] = (
        "A manifest binds components this project executes. Stage 11A executes "
        "nothing, so the record here is the observation, the assessment and the "
        "redistribution position — and a manifest of executed components would "
        "describe an execution that did not happen."
    )
    document["observations"] = observed.observation_rows(observed.LICENSE_OBSERVATIONS)
    return document


def _input_domain_contract_document(
    preflight: VeriFingerPreflight,
) -> Mapping[str, Any]:
    document = _gate_header(
        preflight,
        frozen.PreflightGate.CANONICAL500_INPUT_ROUTE,
        "stage_11a_input_domain_contract_v1",
    )
    document["benchmark_input"] = {
        "profile": frozen.BENCHMARK_INPUT_PROFILE,
        "ppi": frozen.BENCHMARK_INPUT_PPI,
        "pixel_format": frozen.BENCHMARK_INPUT_PIXEL_FORMAT,
    }
    document["required_route"] = list(frozen.CANONICAL500_REQUIRED_ROUTE)
    document["supported_image_containers"] = list(observed.SUPPORTED_IMAGE_CONTAINERS)
    document["png_is_in_the_official_input_domain"] = True
    document["resolution_must_be_declared_on_a_fingerprint_image"] = True
    document["fpbench_preprocessing_performed"] = []
    document["refused_preprocessing"] = list(frozen.REFUSED_PREPROCESSING)
    document["internal_black_box_preprocessing_is_acceptable"] = (
        frozen.INTERNAL_BLACK_BOX_PREPROCESSING_IS_ACCEPTABLE
    )
    document["internal_black_box_note"] = (
        "The SDK performs its own segmentation, alignment and quality "
        "assessment inside the pinned binaries. fpbench has no external choice "
        "about any of it and therefore needs no account of the mathematics; what "
        "must be frozen is every behaviour that *can* be selected from outside "
        "(spec section 13)."
    )
    document["sd300b_1000_ppi_offered_to_this_candidate"] = False
    document["sd300c_2000_ppi_offered_to_this_candidate"] = False
    document["sd300_bytes_read"] = False
    document["observations"] = observed.observation_rows(observed.INPUT_OBSERVATIONS)
    return document


def _profile_document(
    preflight: VeriFingerPreflight,
    gate: frozen.PreflightGate,
    schema: str,
    settings: tuple[observed.PublishedSetting, ...],
    inventory: tuple[str, ...],
    extra_observations: tuple[observed.Observation, ...],
) -> Mapping[str, Any]:
    """One profile, counted over its own settings and nobody else's.

    Every count here is scoped to *this* gate. An earlier version published a
    seven in the extraction blocker and a nine in the marker — the first counting
    extraction settings and the second counting extraction and matching together
    — with nothing saying which was which. Two numbers with one name is worse
    than either alone, so each document counts its own and the total is derived
    and labelled where it is used (docs/adr/0104).
    """
    document = _gate_header(preflight, gate, schema)
    unresolved = _unresolved(settings)
    delivered = _delivered_defaults()
    read_now = tuple(name for name in unresolved if name in delivered)
    still_open = tuple(name for name in unresolved if name not in delivered)
    from_sample = tuple(
        item.name
        for item in settings
        if item.is_score_affecting
        and item.provenance is frozen.SettingProvenance.OFFICIAL_SAMPLE_EXPLICIT
    )
    document["scope"] = (
        "this document counts only the settings of this gate; the other profile "
        "gate counts its own, and no number here spans both"
    )
    document["inventory_classes_searched"] = list(inventory)
    document["inventory_closed"] = True
    document["inventory_names_were_discovered_not_assumed"] = True
    document["published_settings"] = [
        dict(row, delivered_runtime_default=delivered.get(row["setting_name"]))
        for row in observed.setting_rows(settings)
    ]
    document["setting_count"] = len(settings)
    document["score_affecting_count"] = sum(
        1 for item in settings if item.is_score_affecting
    )
    document["score_affecting_from_authoritative_sample"] = list(from_sample)
    document["score_affecting_read_from_the_running_engine"] = list(read_now)
    document["score_affecting_still_without_provenance"] = list(still_open)
    document["score_affecting_still_without_provenance_count"] = len(still_open)
    document["profile_frozen"] = not still_open
    document["authoritative_sample"] = frozen.AUTHORITATIVE_ROUTE_SAMPLE
    document["settings_taken_from_any_other_sample"] = 0
    document["why_one_sample_only"] = (
        "Upstream ships many tutorials and they configure the engine "
        "differently: the enrolment tutorial sets a template size the "
        "verification tutorial never touches, and the verification tutorial sets "
        "a matching speed the enrolment tutorial never touches. A profile taking "
        "one value from each would be a configuration no upstream program has "
        "ever run, so only the complete 1:1 program counts (docs/adr/0105)."
    )
    document["permitted_provenances"] = [
        item.value
        for item in frozen.SettingProvenance
        if item is not frozen.SettingProvenance.UNRESOLVED
    ]
    document["refused_provenance"] = frozen.REFUSED_SETTING_PROVENANCE
    document["settings_chosen_by_fpbench"] = 0
    document["preset_selected_from_score_distributions"] = False
    document["preset_selected_from_vendor_reported_accuracy"] = False
    document["profile_identity_would_name_the_official_sample_route"] = True
    document["observations"] = observed.observation_rows(extra_observations)
    return document


def _extraction_profile_document(
    preflight: VeriFingerPreflight,
) -> Mapping[str, Any]:
    return _profile_document(
        preflight,
        frozen.PreflightGate.EXTRACTION_PROFILE,
        "stage_11a_extraction_profile_v1",
        observed.PUBLISHED_EXTRACTOR_SETTINGS,
        frozen.EXTRACTOR_PROFILE_INVENTORY,
        observed.EXTRACTION_OBSERVATIONS,
    )


def _matcher_profile_document(preflight: VeriFingerPreflight) -> Mapping[str, Any]:
    return _profile_document(
        preflight,
        frozen.PreflightGate.MATCHER_PROFILE,
        "stage_11a_matcher_profile_v1",
        observed.PUBLISHED_MATCHER_SETTINGS,
        frozen.MATCHER_PROFILE_INVENTORY,
        observed.MATCHER_OBSERVATIONS,
    )


def _representation_profile_document(
    preflight: VeriFingerPreflight,
) -> Mapping[str, Any]:
    document = _gate_header(
        preflight,
        frozen.PreflightGate.REPRESENTATION_PROFILE,
        "stage_11a_representation_profile_v1",
    )
    # PASS, not "anything but NOT_REACHED": with a third status in play, a gate
    # awaiting an action has established nothing either.
    reached = (
        preflight.status(frozen.PreflightGate.REPRESENTATION_PROFILE)
        is frozen.GateStatus.PASS
    )
    document["representation_candidates"] = list(frozen.REPRESENTATION_CANDIDATES)
    document["representation_type"] = (
        frozen.RepresentationType.VENDOR_PROPRIETARY_TEMPLATE.value
        if reached
        else frozen.RepresentationType.NOT_REACHED.value
    )
    document["these_are_observations_not_a_settled_profile"] = not reached
    document["interoperable_format_chosen_for_convenience"] = False
    document["iso_and_ansi_are_export_formats_here"] = True
    document["minex_is_a_separate_matching_scenario"] = True
    document["templates_are_ephemeral"] = True
    document["template_bytes_published"] = 0
    document["publishable_facts"] = list(frozen.PUBLISHABLE_REPRESENTATION_FACTS)
    document["template_size_metadata"] = None
    document["why_size_metadata_is_null"] = (
        "Template size depends on the extraction profile, and the extraction "
        "profile is not frozen. A size published now would describe a "
        "configuration nobody has chosen."
    )
    document["observations"] = observed.observation_rows(
        observed.REPRESENTATION_OBSERVATIONS
    )
    return document


def _score_contract_document(preflight: VeriFingerPreflight) -> Mapping[str, Any]:
    document = _gate_header(
        preflight,
        frozen.PreflightGate.RAW_SCORE_ROUTE,
        "stage_11a_score_contract_v1",
    )
    reached = (
        preflight.status(frozen.PreflightGate.RAW_SCORE_ROUTE)
        is frozen.GateStatus.PASS
    )
    document["requirements"] = list(frozen.SCORE_CONTRACT_REQUIREMENTS)
    document["raw_score_route_status"] = (
        frozen.ScoreRouteStatus.NATIVE_TRANSFORMED_SCALAR.value
        if reached
        else frozen.ScoreRouteStatus.NOT_REACHED.value
    )

    # What the pinned manual and upstream's own 1:1 tutorial say. Kept in one
    # labelled block rather than spread across the document as flat fields,
    # because this gate was not reached: a reader who sees `numeric_type:
    # integer` beside `gate_status: NOT_REACHED` should be able to tell in one
    # glance which of the two is a finding. Where the gate *is* reached the same
    # values are promoted to settled fields below.
    documented = {
        "scalar_per_attempt": 1,
        "numeric_type": observed.DOCUMENTED_SCORE_TYPE,
        "direction": observed.DOCUMENTED_SCORE_DIRECTION,
        "nominal_range_published_by_upstream": False,
        "why_no_nominal_range": (
            "Upstream defines the scale by its correspondence with a claimed "
            "false acceptance rate rather than by a maximum. A range invented "
            "here would be fpbench asserting a bound the vendor does not state."
        ),
        "native_transform": observed.DOCUMENTED_SCORE_TRANSFORM,
        "upstream_anchor_points": [
            {"claimed_far": far, "score_value": value}
            for far, value in observed.DOCUMENTED_SCORE_ANCHORS
        ],
        "threshold_is_a_separate_engine_property": True,
        "boolean_only_api": False,
        "official_one_to_one_route": list(observed.OFFICIAL_ONE_TO_ONE_ROUTE),
    }
    document["documented_by_the_pinned_artifact"] = documented
    document["these_are_observations_not_a_settled_contract"] = not reached
    if reached:
        document["settled_contract"] = documented
    else:
        document["settled_contract"] = None
        document["why_nothing_is_settled_here"] = (
            "The gate was never reached, so nothing above it was applied. What "
            "the manual states is recorded because a reader comparing this stage "
            "with the next one needs to see what was already known — and because "
            "publishing it as a conclusion would be exactly the substitution "
            "this stage refuses elsewhere."
        )

    # Requirements and refusals, which hold under either outcome because they are
    # rules rather than findings.
    document["fpbench_conversion_performed"] = False
    document["threshold_applied_inside_the_number"] = False
    document["raw_route_stops_at_the_score"] = True
    document["vendor_threshold_constants_enter_this_stage"] = False
    document["failure_semantics_classes"] = list(frozen.FAILURE_SEMANTICS_CLASSES)
    document["a_failure_may_never_become_a_score_of_zero"] = True
    document["failure_semantics_gate_status"] = preflight.status(
        frozen.PreflightGate.FAILURE_SEMANTICS
    ).value
    document["observations"] = observed.observation_rows(observed.SCORE_OBSERVATIONS)
    document["notes"] = [
        "This is the gate the specification calls decisive, and the artifact "
        "does answer it: a scalar exists, it is not a boolean, and no threshold "
        "has been applied to it. The gate order put an unresolved extraction "
        "profile in front of it, so the answer is recorded and not applied "
        "(docs/adr/0102).",
        "A transformed native quantity is still a raw score. What would not be "
        "is a number fpbench computed from one.",
    ]
    return document


def _pair_semantics_document(preflight: VeriFingerPreflight) -> Mapping[str, Any]:
    document = _gate_header(
        preflight,
        frozen.PreflightGate.PAIR_ORIENTATION,
        "stage_11a_pair_semantics_v1",
    )
    orientation = (_record() or {}).get("pair_orientation") or {}
    self_result = (_record() or {}).get("self_semantics") or {}
    document["requirements"] = list(frozen.PAIR_ORIENTATION_REQUIREMENTS)
    document["api_distinguishes_reference_and_probe"] = True
    document["orderings_scored"] = int(orientation.get("orderings_scored") or 0)
    document["symmetry_observed"] = (
        bool(orientation.get("score_digests_equal")) if orientation else None
    )
    document["a_gate_that_did_not_run_publishes_no_boolean"] = True
    document["fpbench_may_average_the_two_orderings"] = False
    document["fpbench_may_take_the_maximum"] = False
    document["self_semantics_requirements"] = list(
        frozen.SELF_SEMANTICS_REQUIREMENTS
    )
    document["self_independent_extraction_required"] = True
    document["self_semantics_gate_status"] = preflight.status(
        frozen.PreflightGate.SELF_SEMANTICS
    ).value
    document["self_demonstrated"] = bool(self_result.get("score_present"))
    document["self_independent_extractions"] = (
        int(self_result.get("independent_extractions") or 0) or None
    )
    document["self_representation_reused"] = (
        bool(self_result.get("representation_reused")) if self_result else None
    )
    document["comparisons_were_scored_on_fixtures_only"] = True
    document["score_values_published"] = 0
    document["how_scores_were_compared_without_publishing_them"] = (
        "the harness emits a SHA-256 over each score and never the score, so "
        "equality across orderings, across objects and across a process restart "
        "is a digest comparison and no value ever leaves the JVM "
        "(docs/adr/0104)"
    )
    document["fixtures_that_may_be_used"] = list(frozen.FIXTURE_POLICY)
    document["sd300_used_for_any_of_this"] = False
    document["observations"] = observed.observation_rows(
        observed.EXECUTION_OBSERVATIONS
    )
    return document


def _determinism_report_document(preflight: VeriFingerPreflight) -> Mapping[str, Any]:
    document = _gate_header(
        preflight,
        frozen.PreflightGate.SCORE_DETERMINISM,
        "stage_11a_determinism_report_v1",
    )
    determinism = (_record() or {}).get("determinism") or {}
    document["levels"] = [
        {"level": name, "verified": bool(determinism.get(name))}
        for name in frozen.DETERMINISM_LEVELS
    ]
    document["qualification_scores_produced"] = int(
        (_record() or {}).get("qualification_scores_produced") or 0
    )
    document["benchmark_scores_produced"] = 0
    document["score_values_published"] = 0
    document["process_restarts"] = 1 if determinism else 0
    document["templates_must_be_byte_identical"] = False
    document["why_templates_need_not_be_identical"] = (
        "This stage qualifies a verification route, not a serialisation. If the "
        "proprietary templates vary between extractions while the score does "
        "not, that is acceptable; upstream promises nothing about template bytes "
        "and this project does not require it to (spec section 29)."
    )
    document["score_must_be_identical"] = True
    document["nondeterminism_observed"] = bool(
        determinism and not all(
            determinism.get(level) for level in frozen.DETERMINISM_LEVELS
        )
    )
    document["nondeterminism_would_be"] = (
        frozen.BlockerCode.SCORE_NONDETERMINISM_OBSERVED.value
    )
    network = preflight.status(frozen.PreflightGate.NETWORK_DEPENDENCY)
    network_reached = network is frozen.GateStatus.PASS
    document["network_dependency_gate_status"] = network.value
    document["network_role"] = (
        frozen.NetworkRole.LICENSE_VALIDATION_ONLY.value
        if network_reached
        else frozen.NetworkRole.NOT_REACHED.value
    )
    document["network_questions"] = list(frozen.NETWORK_DEPENDENCY_QUESTIONS)
    document["remote_service_participates_in_the_score"] = (
        False if network_reached else None
    )
    document["what_the_pinned_notices_say_about_the_network"] = (
        "The licence agreement defines Internet Activation as storing a licence "
        "file locally that allows the component to run on that computer after a "
        "licence check, with a connection needed briefly at least once in seven "
        "days; the extraction and matching components are native libraries in "
        "the archive and their data files are beside them. That is what the gate "
        "would conclude from, and it is recorded as an observation while the "
        "gate is unreached (docs/adr/0103)."
    )
    document["licence_was_disconnected_to_test_this"] = False
    document["why_not"] = (
        "There is no bypass experiment in this stage. The network question is "
        "answered from the pinned agreement and the SDK's own structure, using "
        "documented behaviour only (spec section 32)."
    )
    document["observations"] = observed.observation_rows(observed.NETWORK_OBSERVATIONS)
    return document


def _runtime_feasibility_document(
    preflight: VeriFingerPreflight,
) -> Mapping[str, Any]:
    document = _gate_header(
        preflight,
        frozen.PreflightGate.RUNTIME_FEASIBILITY,
        "stage_11a_runtime_feasibility_v1",
    )
    load = frozen.FROZEN_WORKLOAD
    terms = observed.TRIAL_TERMS
    feasibility = (_record() or {}).get("feasibility") or {}
    document["measurements_required"] = list(frozen.RUNTIME_FEASIBILITY_MEASUREMENTS)
    document["measurements_taken"] = len(feasibility)
    document["measurements"] = dict(feasibility) or None
    document["measured_on_fixtures_only"] = True
    document["this_is_not_a_performance_benchmark"] = True
    document["this_is_not_a_comparison_with_another_algorithm"] = True
    document["rare_dependency_rule"] = frozen.RARE_DEPENDENCY_RULE
    document["accelerator_required"] = False
    document["license_capacity_gate_status"] = preflight.status(
        frozen.PreflightGate.LICENSE_CAPACITY
    ).value
    document["license_capacity_questions"] = list(frozen.LICENSE_CAPACITY_QUESTIONS)
    document["trial_terms"] = {
        "duration_days": terms.duration_days,
        "api_call_quota_stated": terms.api_call_quota_stated,
        "requires_constant_internet": terms.requires_constant_internet,
        "excludes_simultaneous_licensed_products": (
            terms.excludes_simultaneous_licensed_products
        ),
        "activation_mandatory": terms.activation_mandatory,
        "activation_transmits_personal_information": (
            terms.activation_transmits_personal_information
        ),
        "platform_bound": terms.platform_bound,
    }
    document["an_absent_quota_statement_is_not_permission"] = True
    document["frozen_workload_operations"] = {
        "comparison_attempts": load.comparison_attempts,
        "extraction_invocations": load.extraction_invocations,
        "matcher_invocations": load.matcher_invocations,
    }
    capacity = preflight.status(frozen.PreflightGate.LICENSE_CAPACITY)
    document["workload_fits_the_licence_window"] = (
        True
        if capacity is frozen.GateStatus.PASS
        else (False if capacity is frozen.GateStatus.FAIL else None)
    )
    document["why_null"] = (
        None
        if capacity.is_a_finding
        else (
            "The window is known and the per-operation cost is not, so the "
            "product of the two is not known either. A false here would claim "
            "the workload had been measured and found not to fit."
        )
    )
    document["observations"] = observed.observation_rows(
        observed.CAPACITY_OBSERVATIONS
    )
    return document


def _training_provenance_document(
    preflight: VeriFingerPreflight,
) -> Mapping[str, Any]:
    document = _gate_header(
        preflight,
        frozen.PreflightGate.TRAINING_PROVENANCE,
        "stage_11a_training_provenance_v1",
    )
    reached = (
        preflight.status(frozen.PreflightGate.TRAINING_PROVENANCE)
        is frozen.GateStatus.PASS
    )
    document["training_provenance_status"] = (
        frozen.TrainingProvenanceStatus.PROPRIETARY_UNDISCLOSED.value
        if reached
        else frozen.TrainingProvenanceStatus.NOT_REACHED.value
    )
    document["full_disclosure_required_of_a_commercial_vendor"] = False
    document["sd300_overlap_status"] = preflight.sd300_overlap_status.value
    document["sd300_training_overlap_found"] = False if reached else None
    document["no_evidence_found_is_not_proven_absent"] = True
    document["proven_absent_would_need_an_upstream_statement"] = True
    document["sd300_data_read_by_this_stage"] = False
    document["performance_used_to_answer_provenance"] = False
    document["why_not"] = (
        "A score distribution that looks good or bad on SD300 says nothing about "
        "whether SD300 was in the development set, and treating it as though it "
        "did would be inventing evidence out of a result (spec section 38)."
    )
    document["observations"] = observed.observation_rows(
        observed.PROVENANCE_OBSERVATIONS
    )
    return document


def _preflight_report_document(preflight: VeriFingerPreflight) -> Mapping[str, Any]:
    extraction = len(
        [
            item
            for item in observed.PUBLISHED_EXTRACTOR_SETTINGS
            if item.is_unresolved_score_affecting_default
            and item.name not in _delivered_defaults()
        ]
    )
    matching = len(
        [
            item
            for item in observed.PUBLISHED_MATCHER_SETTINGS
            if item.is_unresolved_score_affecting_default
            and item.name not in _delivered_defaults()
        ]
    )
    return {
        "schema": "stage_11a_preflight_report_v2",
        "candidate": frozen.CANDIDATE_ID,
        "implementation_origin": frozen.IMPLEMENTATION_ORIGIN,
        "verdict": preflight.verdict,
        "outcome": preflight.outcome,
        "outcome_meanings": {
            frozen.STAGE_11A_SELECTED_OUTCOME: (
                "every gate was asked and every gate passed"
            ),
            frozen.STAGE_11A_INCOMPLETE_OUTCOME: (
                "every gate that was asked passed, and some were not asked "
                "because a named action has not been performed. Nothing was "
                "found wrong with the route"
            ),
            frozen.STAGE_11A_BLOCKED_OUTCOME: (
                "a gate found something wrong with the route"
            ),
        },
        "failure_class": (
            preflight.failure_class.value if preflight.failure_class else None
        ),
        "a_gate_awaiting_an_action_is_not_a_failure": True,
        "artifact_was_obtained_and_opened": preflight.artifact_was_opened,
        "decisive_question": (
            "Does an official, exact VeriFinger 2025.2 artifact let fpbench "
            "take canonical_500 in and get a reproducible raw 1:1 score out, "
            "with every externally selectable behaviour that can affect that "
            "score defined by Neurotechnology?"
        ),
        "decisive_answer": (
            "YES"
            if preflight.passed
            else ("NO" if preflight.blocked else "NOT ANSWERED YET")
        ),
        "what_this_outcome_does_not_say": [
            "that the artifact could not be obtained",
            "that Neurotechnology refused anything",
            "that the licence terms forbid research use",
            "that canonical_500 cannot enter the official route",
            "that the raw score is unsuitable",
            "that the algorithm was developed on SD300",
            "that any methodological blocker was found — none was",
        ],
        "passed_every_hard_gate": preflight.passed,
        "a_blocker_was_found": preflight.blocked,
        "stopped_at_gate": (
            preflight.stopped_at.value if preflight.stopped_at else None
        ),
        "gate_count_defined": frozen.GATE_COUNT,
        "gates_reached": preflight.gates_reached,
        "gates_passed": preflight.gates_passed,
        "gates_awaiting_action": preflight.gates_awaiting_action,
        "score_affecting_settings_without_provenance": {
            "extraction_gate": extraction,
            "matching_gate": matching,
            "total_across_both_gates": extraction + matching,
            "note": (
                "each profile gate counts its own settings; the total is derived "
                "here and labelled, so no single number stands for two different "
                "scopes (docs/adr/0104)"
            ),
        },
        "gates": [
            {
                "order": index,
                "gate": result.gate.value,
                "status": result.status.value,
                "status_is_a_finding": result.status.is_a_finding,
                "summary": result.summary,
                "documents": list(frozen.gate_documents(result.gate)),
                "blocker_codes": [
                    blocker.blocker_code.value for blocker in result.blockers
                ],
                "pending_action_codes": [
                    action.action_code.value for action in result.pending_actions
                ],
            }
            for index, result in enumerate(preflight.results, start=1)
        ],
        "blockers": [
            {
                "gate": blocker.gate.value,
                "blocker_code": blocker.blocker_code.value,
                "affected_component": blocker.affected_component,
                "evidence": blocker.evidence,
                "why_this_blocks_algorithm_4": blocker.why_this_blocks_algorithm_4,
                "how_this_would_be_lifted": blocker.how_this_would_be_lifted,
            }
            for blocker in preflight.blockers
        ],
        "pending_actions": [
            {
                "gate": action.gate.value,
                "action_code": action.action_code.value,
                "what_is_missing": action.what_is_missing,
                "what_to_do": action.what_to_do,
                "what_it_would_answer": action.what_it_would_answer,
            }
            for action in preflight.pending_actions
        ],
        "distinct_pending_action_codes": list(
            preflight.distinct_pending_action_codes
        ),
        "one_run_would_close": [
            gate.value for gate in frozen.EXECUTION_DEPENDENT_GATES
        ],
        "qualification_run_steps": list(frozen.QUALIFICATION_RUN_STEPS),
        "qualification_harness": frozen.QUALIFICATION_HARNESS_SOURCE,
        "no_workaround_was_considered": [
            "no licence bypass",
            "no trial reset",
            "no protection mechanism touched",
            "no network disconnected to test whether matching is local",
            "no redistribution of the artifact",
            "no reconstruction of the algorithm from documentation",
            "no preset chosen from score distributions",
            "no settings combined from two different upstream samples",
        ],
        "what_this_candidate_cost": {
            "artifact_bytes_downloaded": sum(
                item.size_bytes for item in observed.ACQUIRED_ARTIFACTS
            ),
            "artifact_bytes_added_to_git": 0,
            "licences_activated": 1 if _record() else 0,
            "sd300_images_read": 0,
            "qualification_scores_produced": int(
                (_record() or {}).get("qualification_scores_produced") or 0
            ),
            "benchmark_scores_produced": 0,
        },
        "acceptance_conditions": list(frozen.ACCEPTANCE_CONDITIONS),
        "acceptance_conditions_are_conjunctive": True,
        "acceptance_conditions_met": preflight.passed,
        "opens_stage_11b": preflight.passed,
        "opens_candidate_search": preflight.blocked,
        "why_the_search_stays_closed": (
            None
            if preflight.blocked
            else (
                "No methodological blocker was found. Moving to another candidate "
                "while this one has an outstanding chore and no adverse finding "
                "would abandon the strongest candidate so far for a reason nobody "
                "could write down (docs/adr/0104)."
            )
        ),
        "stage_11b_scope": list(frozen.STAGE_11B_SCOPE),
    }


_DOCUMENT_BUILDERS = {
    frozen.CANDIDATE_IDENTITY_NAME: _candidate_identity_document,
    frozen.ACQUISITION_MANIFEST_NAME: _acquisition_manifest_document,
    frozen.ARTIFACT_MANIFEST_NAME: _artifact_manifest_document,
    frozen.RUNTIME_IDENTITY_NAME: _runtime_identity_document,
    frozen.THIRD_PARTY_USAGE_BINDING_NAME: _third_party_usage_binding_document,
    frozen.INPUT_DOMAIN_CONTRACT_NAME: _input_domain_contract_document,
    frozen.EXTRACTION_PROFILE_NAME: _extraction_profile_document,
    frozen.REPRESENTATION_PROFILE_NAME: _representation_profile_document,
    frozen.MATCHER_PROFILE_NAME: _matcher_profile_document,
    frozen.SCORE_CONTRACT_NAME: _score_contract_document,
    frozen.PAIR_SEMANTICS_NAME: _pair_semantics_document,
    frozen.DETERMINISM_REPORT_NAME: _determinism_report_document,
    frozen.RUNTIME_FEASIBILITY_NAME: _runtime_feasibility_document,
    frozen.TRAINING_PROVENANCE_NAME: _training_provenance_document,
    frozen.PREFLIGHT_REPORT_NAME: _preflight_report_document,
}


def evidence_document(
    preflight: VeriFingerPreflight, name: str
) -> Mapping[str, Any]:
    """One derivable document by file name, with the secret guard applied.

    Every document passes the guard before any caller sees it, so a document
    that acquired a credential cannot be written even by a caller that never
    checked (spec section 43).
    """
    builder = _DOCUMENT_BUILDERS.get(name)
    if builder is None:
        raise VeriFingerGateError(f"{name!r} is not a derivable Stage 11A document")
    document = builder(preflight)
    require_no_sensitive_material(document, where=name)
    return document


def marker_blocker_rows(
    blockers: Sequence[Blocker],
) -> tuple[Mapping[str, str], ...]:
    """The blockers in exactly the shape the marker stores them."""
    return tuple(
        dict(
            sorted(
                {
                    "gate": blocker.gate.value,
                    "blocker_code": blocker.blocker_code.value,
                    "affected_component": blocker.affected_component,
                    "evidence": blocker.evidence,
                    "why_this_blocks_algorithm_4": (
                        blocker.why_this_blocks_algorithm_4
                    ),
                    "how_this_would_be_lifted": blocker.how_this_would_be_lifted,
                }.items()
            )
        )
        for blocker in sorted(blockers, key=lambda item: item.blocker_code.value)
    )


def marker_pending_action_rows(
    actions: Sequence[PendingAction],
) -> tuple[Mapping[str, str], ...]:
    """The outstanding actions in exactly the shape the marker stores them."""
    return tuple(
        dict(
            sorted(
                {
                    "gate": action.gate.value,
                    "action_code": action.action_code.value,
                    "what_is_missing": action.what_is_missing,
                    "what_to_do": action.what_to_do,
                    "what_it_would_answer": action.what_it_would_answer,
                }.items()
            )
        )
        # Sorted by the same key the marker normalises with — the gate's own
        # string — so building the rows through this function is a no-op there
        # rather than a silent rewrite that would move the fingerprint.
        for action in sorted(
            actions, key=lambda item: (item.gate.value, item.action_code.value)
        )
    )
