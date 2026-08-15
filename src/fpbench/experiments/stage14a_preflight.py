"""The four gates, run in order, and the outcome that follows.

The engine has no verdict parameter, for the reason no preflight engine in this
project has one: an engine that accepted an outcome and then validated it would
be a very elaborate way of writing the outcome down. It reads the acquisition
state of this machine, the inspection record beside a delivered package, and
Stage 8E's own policy, applies the order frozen in
:mod:`fpbench.experiments.stage14a_griaule_identity`, and reports what follows.

**Every gate stops the run.** Unlike Stage 13A — where a training-provenance
search needed no runtime and could be answered out of order — all three gates
after acquisition are questions about delivered bytes. There is nothing to ask
around a package nobody holds, so the run halts at the first gate that does not
pass and every later gate is published ``NOT_REACHED``.

**Three of the five states are not verdicts.** ``PENDING_ACCESS`` says an
official route was walked and somebody else has to move. ``ACTION_REQUIRED``
says this project has a step left to take. ``NOT_REACHED`` says the question was
never asked. None of them is a finding about Griaule, none of them writes a
marker, and collapsing any of them into ``FAIL`` would publish a verdict nobody
reached (docs/adr/0121).

**A gate is answered from the package or it is not answered.** The vendor's
documentation site shaped all four questions and settles none of them: it is
undated, it targets an operating system generation two releases old, and it
describes a migration from a 2009 product. What it says a default is worth is not
what a delivered engine was constructed with (docs/adr/0110).

Nothing here reads SD300, reads a prior algorithm's scores, downloads anything,
activates a licence, loads a vendor library or produces a score.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from fpbench.core.griaule_preflight_errors import (
    GriauleGateError,
    GriauleSensitiveEvidenceError,
    Stage14AFinalizationError,
)
from fpbench.core.serialization import stable_hash
from fpbench.experiments import stage14a_griaule_identity as frozen
from fpbench.experiments import stage14a_griaule_observations as observed
from fpbench.experiments.stage14a_acquisition import (
    REQUEST_DRAFT,
    REQUEST_SENT_UTC,
    REQUEST_STATUS,
    AcquisitionState,
    AcquisitionStatus,
    acquisition_state,
    package_inspection,
)
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
    "PendingReason",
    "OutstandingAction",
    "GateResult",
    "GriaulePreflight",
    "require_stage8e_is_the_policy_this_reuses",
    "require_stage13a_is_the_closed_predecessor",
    "require_stage11b_is_unchanged",
    "research_use_assessment",
    "redistribution_record",
    "unresolved_score_affecting_settings",
    "run_preflight",
    "evidence_document",
    "marker_blocker_rows",
    "find_sensitive_material",
    "require_no_sensitive_material",
]


# ------------------------------------------------------------ the closed stages


def _read_marker(
    repository_root: Path, relative: str, stage: str
) -> Mapping[str, Any]:
    path = Path(repository_root) / PurePosixPath(relative)
    try:
        marker = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Stage14AFinalizationError(
            f"cannot read the {stage} marker Stage 14A binds at {relative}: {exc}"
        ) from exc
    if not isinstance(marker, dict):
        raise Stage14AFinalizationError(f"the {stage} marker is not a JSON object")
    return marker


def require_stage8e_is_the_policy_this_reuses(repository_root: Path) -> None:
    """Confirm the policy Stage 14A reuses is the policy it was written against.

    Raises:
        Stage14AFinalizationError: the published Stage 8E marker, the live
            purpose or the live policy has moved. Stage 14A does not repair
            Stage 8E and does not proceed around it.
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
            raise Stage14AFinalizationError(
                f"the Stage 8E marker's {key} is {found!r} and Stage 14A was "
                f"written against {value!r}. Stage 8E is a closed stage; a "
                "capability it lacks is a corrective policy stage, not an edit "
                "from here"
            )
    if project_purpose().purpose_fingerprint != frozen.STAGE8E_PURPOSE_FINGERPRINT:
        raise Stage14AFinalizationError(
            "the live project purpose no longer fingerprints to what Stage 8E "
            "published; every Stage 14A decision would be taken under a different "
            "premise"
        )
    if policy_fingerprint() != frozen.STAGE8E_POLICY_FINGERPRINT:
        raise Stage14AFinalizationError(
            "the live third-party policy no longer fingerprints to what Stage 8E "
            "published"
        )


def require_stage13a_is_the_closed_predecessor(repository_root: Path) -> str:
    """Confirm Stage 13A still says what Stage 14A was written after.

    Stage 14A exists because Stage 13A closed on an unobtainable FingerCell trial
    entitlement and returned the Algorithm 5 slot to the search. Binding that
    marker's fingerprint is what makes "Stage 13A was not re-opened to make room
    for this" a checkable claim rather than an intention.

    Returns:
        The predecessor fingerprint, for the marker to carry.

    Raises:
        Stage14AFinalizationError: Stage 13A's marker has moved.
    """
    relative = f"{frozen.STAGE_13A_EVIDENCE_DIRECTORY}/stage-13a-finalization.json"
    marker = _read_marker(repository_root, relative, "Stage 13A")
    expected = {
        "outcome": frozen.STAGE_13A_OUTCOME,
        "failure_class": frozen.STAGE_13A_FAILURE_CLASS,
        "stage_13a_finalization_fingerprint": (
            frozen.STAGE_13A_FINALIZATION_FINGERPRINT
        ),
    }
    for key, value in expected.items():
        found = marker.get(key)
        if found != value:
            raise Stage14AFinalizationError(
                f"the Stage 13A marker's {key} is {found!r} and Stage 14A was "
                f"written after {value!r}. Stage 13A is immutable here"
            )
    if marker.get("reopens_algorithm_5_search") is not True:
        raise Stage14AFinalizationError(
            "Stage 13A's marker no longer reopens the Algorithm 5 search, and "
            "that search is the only thing Stage 14A is a response to"
        )
    if marker.get("opens_stage_13b") is not False:
        raise Stage14AFinalizationError(
            "Stage 13A's marker now opens Stage 13B, which would mean FingerCell "
            "is the candidate and this stage has no reason to exist"
        )
    return frozen.STAGE_13A_FINALIZATION_FINGERPRINT


def require_stage11b_is_unchanged(repository_root: Path) -> str:
    """Confirm Algorithm 4's published outcomes have not moved.

    Bound and never read. Stage 14A consults no prior algorithm's scores; what it
    checks is that the stage which produced them is still closed at the same
    fingerprint.
    """
    relative = "/".join(
        ("evidence", "stage11b-" + "verifinger-canonical500-raw", "stage-11b-finalization.json")
    )
    marker = _read_marker(repository_root, relative, "Stage 11B")
    expected = {
        "outcome": frozen.STAGE_11B_OUTCOME,
        "stage_11b_finalization_fingerprint": (
            frozen.STAGE_11B_FINALIZATION_FINGERPRINT
        ),
    }
    for key, value in expected.items():
        found = marker.get(key)
        if found != value:
            raise Stage14AFinalizationError(
                f"the Stage 11B marker's {key} is {found!r} and Stage 14A was "
                f"written after {value!r}. Algorithm 4 is immutable here"
            )
    return frozen.STAGE_11B_FINALIZATION_FINGERPRINT


# -------------------------------------------------------------------- Stage 8E

#: What Stage 8E is asked about, and the one thing that can be said about it
#: today. Griaule delivers its licence terms *with the package*, and this project
#: has not received one — so there is no notice to read, no locator to cite and no
#: assessment to derive.
#:
#: A placeholder assessment would be worse than none: it would put a
#: ``MAY_EXECUTE_LOCALLY`` into the evidence of a stage that never saw a licence.
_NO_LICENSE_EVIDENCE_YET = (
    "Griaule delivers its licence terms with the package, and the public "
    "documentation states only that a trial licence is distributed inside it. No "
    "package has been delivered here, so no notice has been read and Stage 8E "
    "has been asked nothing. The policy is bound by fingerprint and will be "
    "applied to the terms that actually arrive, never to the documentation page."
)


def research_use_assessment(
    inspection: Mapping[str, Any] | None,
) -> ResearchUseAssessment | None:
    """What Stage 8E returns over the notices that arrived with the package.

    Returns:
        ``None`` where no package has been delivered. That is not a refusal and
        must not be published as one: a component nobody obtained is a component
        Stage 8E assessed zero of, and a ``false`` there would read as a
        research-use refusal nobody made (docs/adr/0095).
    """
    if not inspection:
        return None
    licence = inspection.get("license")
    if not isinstance(licence, Mapping):
        return None
    notices = licence.get("notices")
    if not isinstance(notices, Sequence) or isinstance(notices, (str, bytes)):
        return None
    if not notices:
        return None

    evidence = tuple(
        LicenseEvidence(
            locator=str(item.get("locator", "")),
            description=str(item.get("description", "")),
            document_sha256=str(item.get("document_sha256", "")),
        )
        for item in notices
        if isinstance(item, Mapping)
    )
    readings = tuple(
        PlausibleReading(
            notice_locator=str(item.get("locator", "")),
            permits_local_execution=bool(item.get("permits_local_execution")),
            permits_non_commercial_use=bool(item.get("permits_non_commercial_use")),
            permits_educational_research=bool(
                item.get("permits_educational_research")
            ),
        )
        for item in notices
        if isinstance(item, Mapping)
    )
    try:
        status = LicenseObservationStatus(str(licence.get("observation_status", "")))
    except ValueError:
        status = LicenseObservationStatus.UNRESOLVED
    if status.limits_field_of_use and len(readings) < 2:
        # Stage 8E computes the conservative answer from at least two plausible
        # readings and refuses to assume one. Stage 14A applies that rule rather
        # than working around it.
        raise Stage14AFinalizationError(
            "the delivered licence limits the field of use and only "
            f"{len(readings)} plausible reading was recorded. Stage 8E needs at "
            "least two to compute the conservative answer, and Stage 14A does not "
            "assume one on its behalf"
        )
    restrictions = tuple(
        NonBlockingRestriction(str(item))
        for item in licence.get("non_blocking_restrictions", ())
        if str(item) in {member.value for member in NonBlockingRestriction}
    )
    observation = LicenseObservation(
        observation_id="griaule_gbs_fingerprint_delivered_license",
        component_kind=ThirdPartyComponentKind.RUNTIME_BINARY,
        subject=(
            "the Griaule GBS Fingerprint SDK package as delivered, under the "
            "terms that arrived with it"
        ),
        status=status,
        declared_license_names=tuple(
            str(item) for item in licence.get("declared_license_names", ())
        ),
        evidence=evidence,
        stated_restrictions=tuple(
            str(item) for item in licence.get("stated_restrictions", ())
        ),
    )
    return assess_research_use(
        observation,
        assessment_id="griaule_gbs_fingerprint_local_research_execution",
        basis=str(licence.get("basis", "")),
        non_blocking_restrictions=restrictions,
        intersection_readings=readings,
        identity_established=True,
    )


def _assessment_or_refusal(
    inspection: Mapping[str, Any] | None,
) -> tuple[ResearchUseAssessment | None, str | None]:
    """Stage 8E's decision, or the reason it declined to make one."""
    from fpbench.core.errors import FpbenchError

    try:
        return research_use_assessment(inspection), None
    except FpbenchError as exc:
        return None, f"Stage 8E declined to decide on these facts: {exc}"


def redistribution_record() -> RedistributionRecord:
    """What fpbench does by way of redistribution. Nothing, under either outcome.

    True before a package arrives and afterwards: the package, its libraries and
    its licence stay in the local artifact store, outside the working tree, and
    the repository holds only descriptions of them (docs/adr/0083).
    """
    return RedistributionRecord(
        decision=RedistributionDecision.NOT_ALLOWED,
        basis=(
            "A vendor SDK delivered under a licence is not redistributable, and "
            "fpbench redistributes nothing in any case. No package byte, library, "
            "licence or template enters this repository."
        ),
        redistributed_by_fpbench=False,
    )


# ------------------------------------------------------------------- the gates


@dataclass(frozen=True, slots=True)
class Blocker:
    """One reason Griaule cannot enter fpbench as Algorithm 5.

    Every blocker describes something that was *observed*: a refusal that
    arrived, or a delivered artifact that was read. ``how_this_would_be_lifted``
    is mandatory — a blocker nobody can act on is a blocker nobody can lift.
    """

    gate: frozen.PreflightGate
    blocker_code: frozen.BlockerCode
    affected_component: str
    evidence: str
    why_this_blocks_algorithm_5: str
    how_this_would_be_lifted: str

    def __post_init__(self) -> None:
        permitted = dict(frozen.GATE_BLOCKERS)[self.gate]
        if self.blocker_code not in permitted:
            raise GriauleGateError(
                f"{self.blocker_code.value} does not belong to {self.gate.value}; "
                "it belongs to "
                f"{[i.value for i in frozen.gate_of_blocker(self.blocker_code)]}"
                " and raising it here would put the reason in the wrong place"
            )
        for name in (
            "affected_component",
            "evidence",
            "why_this_blocks_algorithm_5",
            "how_this_would_be_lifted",
        ):
            if not str(getattr(self, name)).strip():
                raise GriauleGateError(f"{self.blocker_code.value}: {name} is empty")

    def as_row(self) -> Mapping[str, str]:
        return {
            "gate": self.gate.value,
            "blocker_code": self.blocker_code.value,
            "affected_component": self.affected_component,
            "evidence": self.evidence,
            "why_this_blocks_algorithm_5": self.why_this_blocks_algorithm_5,
            "how_this_would_be_lifted": self.how_this_would_be_lifted,
        }


@dataclass(frozen=True, slots=True)
class PendingReason:
    """Why a gate is waiting on somebody outside this project.

    Structurally a sibling of :class:`Blocker` and semantically its opposite. A
    blocker says something is wrong with the route; a pending reason says an
    official route was walked and somebody else has to move next. Nothing about
    the candidate follows from one (docs/adr/0121).
    """

    kind: frozen.PendingKind
    what_was_walked: str
    what_is_outstanding: tuple[str, ...]
    what_it_would_answer: str

    def __post_init__(self) -> None:
        if not str(self.what_was_walked).strip():
            raise GriauleGateError("a pending reason says what was actually tried")
        if not self.what_is_outstanding:
            raise GriauleGateError(
                "a pending reason names what would move it; one that named "
                "nothing would be indistinguishable from giving up"
            )
        if not str(self.what_it_would_answer).strip():
            raise GriauleGateError(
                "a pending reason says what the answer would settle"
            )

    def as_row(self) -> Mapping[str, Any]:
        return {
            "kind": self.kind.value,
            "what_was_walked": self.what_was_walked,
            "what_is_outstanding": list(self.what_is_outstanding),
            "what_it_would_answer": self.what_it_would_answer,
        }


@dataclass(frozen=True, slots=True)
class OutstandingAction:
    """A step this project can take for itself, and has not taken yet.

    Also a sibling of :class:`Blocker` and also its opposite, in a different
    direction from :class:`PendingReason`: this one says something about this
    project's own progress (docs/adr/0121).
    """

    gate: frozen.PreflightGate
    action: frozen.RequiredAction
    what_has_been_done: str
    what_remains: tuple[str, ...]
    what_it_would_answer: str

    def __post_init__(self) -> None:
        permitted = dict(frozen.GATE_ACTIONS)[self.gate]
        if self.action not in permitted:
            raise GriauleGateError(
                f"{self.action.value} does not belong to {self.gate.value}; an "
                "action reported at the wrong gate would send somebody to do the "
                "wrong work"
            )
        if not str(self.what_has_been_done).strip():
            raise GriauleGateError(
                f"{self.action.value}: an outstanding action says what has already "
                "been done, so that nobody repeats it"
            )
        if not self.what_remains:
            raise GriauleGateError(
                f"{self.action.value}: an outstanding action names what would move "
                "it; one that named nothing would be indistinguishable from "
                "giving up"
            )

    def as_row(self) -> Mapping[str, Any]:
        return {
            "gate": self.gate.value,
            "action": self.action.value,
            "what_has_been_done": self.what_has_been_done,
            "what_remains": list(self.what_remains),
            "what_it_would_answer": self.what_it_would_answer,
        }


@dataclass(frozen=True, slots=True)
class GateResult:
    """One gate's conclusion."""

    gate: frozen.PreflightGate
    status: frozen.GateStatus
    summary: str
    blockers: tuple[Blocker, ...] = ()
    pending: PendingReason | None = None
    outstanding: OutstandingAction | None = None

    def __post_init__(self) -> None:
        attachments = bool(self.blockers) + (self.pending is not None) + (
            self.outstanding is not None
        )
        if self.status is frozen.GateStatus.PASS and attachments:
            raise GriauleGateError(
                f"{self.gate.value}: a gate that passed carries no blockers, no "
                "pending reason and nothing outstanding; a blocker is not a "
                "reservation to be weighed"
            )
        if self.status is frozen.GateStatus.FAIL:
            if not self.blockers:
                raise GriauleGateError(f"{self.gate.value}: a gate that failed names why")
            if self.pending is not None or self.outstanding is not None:
                raise GriauleGateError(
                    f"{self.gate.value}: a gate that failed found something wrong "
                    "with the route, and a wait or a chore beside it would blur "
                    "the three claims this stage keeps apart"
                )
        if self.status is frozen.GateStatus.PENDING_ACCESS:
            if self.blockers:
                raise GriauleGateError(
                    f"{self.gate.value}: nobody has answered, so nothing has been "
                    "found; a blocker here would say something about Griaule that "
                    "nothing established (docs/adr/0121)"
                )
            if self.pending is None:
                raise GriauleGateError(
                    f"{self.gate.value}: a gate waiting on somebody else says on "
                    "what, and what would move it"
                )
            if self.outstanding is not None:
                raise GriauleGateError(
                    f"{self.gate.value}: a gate cannot be waiting on somebody else "
                    "and on this project at the same time; one of the two is the "
                    "next move"
                )
        if self.status is frozen.GateStatus.ACTION_REQUIRED:
            if self.blockers:
                raise GriauleGateError(
                    f"{self.gate.value}: an action has not been performed, so "
                    "nothing has been found; a blocker here would say something "
                    "about Griaule that nothing established (docs/adr/0121)"
                )
            if self.outstanding is None:
                raise GriauleGateError(
                    f"{self.gate.value}: a gate awaiting an action says which action"
                )
            if self.pending is not None:
                raise GriauleGateError(
                    f"{self.gate.value}: a gate cannot be waiting on this project "
                    "and on somebody else at the same time"
                )
        if self.status is frozen.GateStatus.NOT_REACHED and attachments:
            raise GriauleGateError(
                f"{self.gate.value}: a gate that was never reached cannot have "
                "found anything and cannot be waiting for anything"
            )
        for blocker in self.blockers:
            if blocker.gate is not self.gate:
                raise GriauleGateError(
                    f"{self.gate.value}: carries a blocker raised at "
                    f"{blocker.gate.value}"
                )
        if self.outstanding is not None and self.outstanding.gate is not self.gate:
            raise GriauleGateError(
                f"{self.gate.value}: carries an action reported at "
                f"{self.outstanding.gate.value}"
            )
        if not str(self.summary).strip():
            raise GriauleGateError(f"{self.gate.value}: a gate result says what it found")


# --------------------------------------------------------- what this machine has

_RUN_CACHE: dict[str, Any] = {}


def _cached(key: str, factory: Any) -> Any:
    if key not in _RUN_CACHE:
        _RUN_CACHE[key] = factory()
    return _RUN_CACHE[key]


def _acquisition() -> AcquisitionState:
    return _cached("acquisition", acquisition_state)


def _inspection() -> Mapping[str, Any] | None:
    return _cached("inspection", package_inspection)


def _section(name: str) -> Mapping[str, Any] | None:
    inspection = _inspection()
    if not inspection:
        return None
    section = inspection.get(name)
    return section if isinstance(section, Mapping) else None


def _rows(name: str) -> tuple[Mapping[str, Any], ...]:
    inspection = _inspection()
    if not inspection:
        return ()
    rows = inspection.get(name)
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return ()
    return tuple(item for item in rows if isinstance(item, Mapping))


def unresolved_score_affecting_settings() -> tuple[str, ...]:
    """Every score-affecting setting with no upstream authority behind a value.

    The count this returns is G4's central finding. A setting nobody recorded
    still decides the score, and "the vendor's website says the default is 20" is
    not an authority over a delivered engine — it becomes one only when somebody
    reads the value off the package that arrived.

    Never zero merely because nobody recorded an inventory: a package that has
    not been inspected has no settings rows, and a caller reading this as
    "nothing is unresolved" would be reading an absence as an answer.
    """
    unresolved: list[str] = []
    for row in _rows("settings"):
        if not bool(row.get("score_affecting", True)):
            continue
        try:
            provenance = frozen.SettingProvenance(str(row.get("source_authority", "")))
        except ValueError:
            unresolved.append(str(row.get("name", "<unnamed>")))
            continue
        if not provenance.is_upstream_authority:
            unresolved.append(str(row.get("name", "<unnamed>")))
    return tuple(sorted(unresolved))


def missing_setting_categories() -> tuple[str, ...]:
    """Every knob category G4 requires an answer about and the inventory omits.

    The vendor's own public documentation proves at least the first two exist, so
    an inventory that never mentions them is visibly incomplete rather than
    arguably complete. A category may legitimately be answered "this package has
    no such setting" — what it may not be is absent.
    """
    if not _inspection():
        return frozen.SETTINGS_TO_ACCOUNT_FOR
    accounted = {
        str(row.get("category", "")).strip().lower()
        for row in _rows("settings")
    } | {
        str(item).strip().lower()
        for item in (_section("settings_closure") or {}).get(
            "categories_with_no_such_setting", ()
        )
        if isinstance(item, str)
    }
    return tuple(
        category
        for category in frozen.SETTINGS_TO_ACCOUNT_FOR
        if category.lower() not in accounted
    )


def _not_reached_reason(stopped_at: frozen.PreflightGate) -> str:
    """Why a gate was never asked."""
    return (
        f"the run stopped at {stopped_at.value}, so this question was never "
        "asked: nothing was obtained, read, loaded or executed for it"
    )


def _no_package_summary(state: AcquisitionState) -> str:
    return (
        "no official package has been delivered, and this gate is a question "
        f"about delivered bytes. Acquisition stands at {state.status.value}"
    )


# --------------------------------------------------------------------- gate 1


def _gate_official_artifact_and_trial_access() -> GateResult:
    """G1. Is an official package here, hashed, with its terms and bundled trial?

    Acquisition comes first because every later question is a question about
    delivered bytes. This gate has four possible non-pass answers and they mean
    four different things, which is the reason this stage has five gate states
    rather than Stage 12A's four or Stage 13A's four.
    """
    gate = frozen.PreflightGate.OFFICIAL_ARTIFACT_AND_TRIAL_ACCESS
    state = _acquisition()
    walked = ", ".join(
        route.route_id
        for route in observed.OFFICIAL_ROUTES
        if route.retrieval is observed.RetrievalStatus.RETRIEVED
    )

    if state.status is AcquisitionStatus.ACCESS_REFUSED:
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.FAIL,
            summary="the vendor was asked for a package and declined",
            blockers=(
                Blocker(
                    gate=gate,
                    blocker_code=frozen.BlockerCode.VENDOR_ACCESS_REFUSED,
                    affected_component="the official Griaule GBS Fingerprint SDK package",
                    evidence=state.detail,
                    why_this_blocks_algorithm_5=(
                        "every remaining gate is a question about a delivered "
                        "package — its identity, its input route, its score API, "
                        "its settings. None of them can be answered about a "
                        "package nobody holds, and answering them from a "
                        "documentation page would be publishing a benchmark route "
                        "this project had never opened"
                    ),
                    how_this_would_be_lifted=(
                        "only the vendor can lift it, by supplying a package under "
                        "terms this project can accept. It is not lifted by taking "
                        "the package from a mirror, a catalogue site or a reseller"
                    ),
                ),
            ),
        )
    if state.status is AcquisitionStatus.PACKAGE_UNAVAILABLE:
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.FAIL,
            summary="the vendor confirmed no package is available for this use",
            blockers=(
                Blocker(
                    gate=gate,
                    blocker_code=frozen.BlockerCode.OFFICIAL_PACKAGE_UNAVAILABLE,
                    affected_component="the official Griaule GBS Fingerprint SDK package",
                    evidence=state.detail,
                    why_this_blocks_algorithm_5=(
                        "there is no artifact to identify, no route to inspect and "
                        "no score contract to read"
                    ),
                    how_this_would_be_lifted=(
                        "by the vendor publishing or supplying a package for this "
                        "product under terms this project can accept"
                    ),
                ),
            ),
        )
    if state.status.is_pending:
        kind = (
            frozen.PendingKind.VENDOR_REQUEST_SENT_AWAITING_REPLY
            if state.status is AcquisitionStatus.REQUEST_PENDING
            else frozen.PendingKind.VENDOR_REPLY_REQUIRES_FURTHER_STEPS
        )
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.PENDING_ACCESS,
            summary=(
                "an official route was walked and somebody outside this project "
                f"has to move next: {state.detail}"
            ),
            pending=PendingReason(
                kind=kind,
                what_was_walked=(
                    f"the vendor's own routes ({walked}), none of which serves the "
                    "package, followed by one request through the route the "
                    f"vendor's documentation names, sent {REQUEST_SENT_UTC}"
                ),
                what_is_outstanding=tuple(observed.WHAT_WOULD_CHANGE_THE_STATUS[1:]),
                what_it_would_answer=(
                    "whether an official, current package with its bundled trial "
                    "can be obtained at all — which is the only question Stage 14A "
                    "asks before any code is written against this candidate"
                ),
            ),
        )
    if state.status is AcquisitionStatus.REQUEST_NOT_SENT:
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.ACTION_REQUIRED,
            summary=(
                "every official route was walked and none of them serves the "
                "package; the one request this project owes has not been sent"
            ),
            outstanding=OutstandingAction(
                gate=gate,
                action=frozen.RequiredAction.SEND_ONE_OFFICIAL_ACQUISITION_REQUEST,
                what_has_been_done=(
                    f"the vendor's official routes were retrieved ({walked}): the "
                    "SDK documentation page and every link on it, the "
                    "documentation site's own complete page index, the corporate "
                    "site's download path, the corporate contact page and the "
                    "support knowledge base including a search of its articles. "
                    "None publishes the package, and the refused third-party "
                    "sources were identified and recorded as refused"
                ),
                what_remains=(observed.WHAT_WOULD_CHANGE_THE_STATUS[0],),
                what_it_would_answer=(
                    "whether the package and its bundled 90-day trial can be "
                    "obtained for academic, research-only, non-commercial use. "
                    "Until it is sent, nothing whatever is established about "
                    "Griaule — including that it is unwilling"
                ),
            ),
        )
    if state.status is AcquisitionStatus.DECLARATION_REQUIRED:
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.ACTION_REQUIRED,
            summary=f"a package is expected or present and is not pinned: {state.detail}",
            outstanding=OutstandingAction(
                gate=gate,
                action=frozen.RequiredAction.HASH_AND_DECLARE_THE_DELIVERED_PACKAGE,
                what_has_been_done=(
                    "the vendor route produced a package, or bytes are already in "
                    f"the local artifact store: {state.detail}"
                ),
                what_remains=(
                    "place the package in the local artifact store, outside the "
                    "working tree",
                    "hash its exact bytes here rather than accepting a published "
                    "digest",
                    "record the product version, build, platform and delivery "
                    "channel from the artifact itself",
                ),
                what_it_would_answer=(
                    "the package identity every later gate is a question about"
                ),
            ),
        )

    declaration = state.declaration
    if not state.obtained or declaration is None:  # pragma: no cover - defensive
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.ACTION_REQUIRED,
            summary=f"the package is not established here: {state.detail}",
            outstanding=OutstandingAction(
                gate=gate,
                action=frozen.RequiredAction.HASH_AND_DECLARE_THE_DELIVERED_PACKAGE,
                what_has_been_done=state.detail,
                what_remains=("obtain, hash and declare the official package",),
                what_it_would_answer="the package identity",
            ),
        )

    inspection = _inspection()
    if inspection is None:
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.ACTION_REQUIRED,
            summary=(
                "the package is here and pinned, and nobody has read its delivered "
                "documentation, headers, samples and terms"
            ),
            outstanding=OutstandingAction(
                gate=gate,
                action=frozen.RequiredAction.INSPECT_THE_DELIVERED_PACKAGE,
                what_has_been_done=(
                    f"the package was obtained through {declaration.official_locator_category.value} "
                    "and hashed here"
                ),
                what_remains=(
                    "read the delivered licence or EULA and record its notices",
                    "confirm the bundled trial mechanism is present in the package",
                    "read the delivered headers and samples for the input route "
                    "and the score contract",
                    "inventory every delivered setting that can reach the score",
                ),
                what_it_would_answer="all three remaining gates",
            ),
        )

    missing = [
        name
        for name, present in (
            ("its delivered documentation", declaration.documentation_obtained),
            ("its delivered licence or EULA", declaration.license_obtained),
            ("the bundled trial mechanism", declaration.bundled_trial_present),
        )
        if not present
    ]
    if missing:
        code = (
            frozen.BlockerCode.BUNDLED_TRIAL_ROUTE_UNAVAILABLE
            if not declaration.bundled_trial_present
            else frozen.BlockerCode.OFFICIAL_PACKAGE_UNAVAILABLE
        )
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.FAIL,
            summary=f"the delivered package arrived without {', '.join(missing)}",
            blockers=(
                Blocker(
                    gate=gate,
                    blocker_code=code,
                    affected_component="the delivered Griaule package",
                    evidence=(
                        f"the package declaration records that {', '.join(missing)} "
                        "is not present with the delivered bytes"
                    ),
                    why_this_blocks_algorithm_5=(
                        "the vendor's documentation states the trial is "
                        "distributed inside the package. A package delivered "
                        "without it, or without the terms that govern it, cannot "
                        "be executed here at all — which is exactly the wall "
                        "Stage 13A hit after obtaining an archive it could never "
                        "run"
                    ),
                    how_this_would_be_lifted=(
                        "by the vendor supplying the missing part through the same "
                        "official channel. It is not lifted by a serial-number "
                        "workaround, by substituting a commercial licence, or by "
                        "any reset or bypass"
                    ),
                ),
            ),
        )

    assessment, refusal = _assessment_or_refusal(inspection)
    if refusal is not None or assessment is None:
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.ACTION_REQUIRED,
            summary=(
                refusal
                or "the delivered terms have not been recorded in a form Stage 8E "
                "can decide on"
            ),
            outstanding=OutstandingAction(
                gate=gate,
                action=frozen.RequiredAction.INSPECT_THE_DELIVERED_PACKAGE,
                what_has_been_done="the package was obtained, hashed and unpacked",
                what_remains=(
                    "record the delivered licence notices, their locators and "
                    "their digests, and at least two plausible readings where the "
                    "terms limit the field of use",
                ),
                what_it_would_answer=(
                    "whether Stage 8E's frozen policy opens local research "
                    "execution over these terms"
                ),
            ),
        )
    if not assessment.may_execute_locally:
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.FAIL,
            summary="the delivered terms do not open local research execution",
            blockers=(
                Blocker(
                    gate=gate,
                    blocker_code=frozen.BlockerCode.RESEARCH_USE_BLOCKED,
                    affected_component="the delivered Griaule licence terms",
                    evidence=(
                        "Stage 8E's frozen policy, applied to the notices "
                        f"delivered with the package, returns {assessment.decision.value}"
                    ),
                    why_this_blocks_algorithm_5=(
                        "this project executes third-party components only where "
                        "the terms that arrived with them permit local, "
                        "non-commercial research use. A package that may not be "
                        "run is a package no gate below this one can be asked "
                        "about"
                    ),
                    how_this_would_be_lifted=(
                        "by terms that permit it — which is a licensing "
                        "arrangement with the vendor, not a re-reading of the same "
                        "notice"
                    ),
                ),
            ),
        )
    return GateResult(
        gate=gate,
        status=frozen.GateStatus.PASS,
        summary=(
            f"the official package was obtained through "
            f"{declaration.official_locator_category.value}, hashed here, and "
            "arrived with its documentation, its terms and the bundled trial; "
            "Stage 8E's policy opens local research execution over those terms"
        ),
    )


# --------------------------------------------------------------------- gate 2


def _gate_direct_canonical500_input_route() -> GateResult:
    """G2. Does the canonical image reach the extractor unmodified?

    The gate the vendor's documented 500 x 500 extraction limit makes interesting.
    A crop the extractor performs on a full image it was handed is part of the
    algorithm under test. A crop the caller is required to perform first is
    fpbench choosing which part of the finger the algorithm sees, and that is a
    hard reject rather than a compatibility step (docs/adr/0124).
    """
    gate = frozen.PreflightGate.DIRECT_CANONICAL500_INPUT_ROUTE
    state = _acquisition()
    route = _section("input_route")
    if route is None:
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.NOT_REACHED,
            summary=_no_package_summary(state),
        )

    if bool(route.get("fpbench_preprocessing_required")):
        performed = [
            str(item)
            for item in route.get("required_preprocessing", ())
            if isinstance(item, str)
        ]
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.FAIL,
            summary=(
                "the delivered API requires the caller to modify the image before "
                f"extraction: {', '.join(performed) or 'unspecified preprocessing'}"
            ),
            blockers=(
                Blocker(
                    gate=gate,
                    blocker_code=frozen.BlockerCode.FPBENCH_PREPROCESSING_REQUIRED,
                    affected_component="the delivered extraction entry point",
                    evidence=(
                        "the delivered headers and samples show the extractor "
                        "rejecting or mishandling a full canonical image, and the "
                        "official route requires the caller to supply an image "
                        f"already reduced: {', '.join(performed) or 'unspecified'}"
                    ),
                    why_this_blocks_algorithm_5=(
                        "fpbench would be choosing which part of each finger the "
                        "algorithm sees, and that choice would silently enter "
                        "every score in the result set. Two algorithms compared "
                        "over inputs one of them had cropped by fpbench are not "
                        "being compared on the same protocol"
                    ),
                    how_this_would_be_lifted=(
                        "by an official entry point that accepts the full image "
                        "and performs any reduction itself. It is not lifted by "
                        "choosing a sensible crop"
                    ),
                ),
            ),
        )

    equality = route.get("pixel_equality")
    geometry = route.get("geometry_unchanged")
    container = str(route.get("container") or "")
    effective_ppi = route.get("effective_ppi")
    if container and (equality is not True or geometry is not True):
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.FAIL,
            summary=(
                f"the route converts the canonical image into {container} and the "
                "conversion is not pixel-for-pixel identical"
            ),
            blockers=(
                Blocker(
                    gate=gate,
                    blocker_code=frozen.BlockerCode.DIRECT_INPUT_ROUTE_UNRESOLVED,
                    affected_component="the container adaptation",
                    evidence=(
                        f"pixel_equality={equality!r} and "
                        f"geometry_unchanged={geometry!r} for the "
                        f"{container} adaptation"
                    ),
                    why_this_blocks_algorithm_5=(
                        "a container change is permitted precisely because it "
                        "changes nothing. One that alters a pixel value or the "
                        "geometry is preprocessing wearing a file extension"
                    ),
                    how_this_would_be_lifted=(
                        "by a lossless decode that preserves every gray8 value and "
                        "the exact width and height"
                    ),
                ),
            ),
        )
    if effective_ppi is None or int(effective_ppi) != frozen.REQUIRED_INPUT_PPI:
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.FAIL,
            summary=(
                f"the resolution reaching the extractor is {effective_ppi!r} and "
                f"this benchmark's canonical input is {frozen.REQUIRED_INPUT_PPI} ppi"
            ),
            blockers=(
                Blocker(
                    gate=gate,
                    blocker_code=frozen.BlockerCode.DIRECT_INPUT_ROUTE_UNRESOLVED,
                    affected_component="the resolution the extractor is told about",
                    evidence=f"effective_ppi={effective_ppi!r} at extraction",
                    why_this_blocks_algorithm_5=(
                        "the vendor's own documentation gives extraction a "
                        "resolution range, so the number the extractor is told is "
                        "an input to the algorithm. A route that loses it, or "
                        "carries a different one, is not the canonical route"
                    ),
                    how_this_would_be_lifted=(
                        "by an official route that carries 500 ppi into the "
                        "extractor through the container's own metadata or the "
                        "API's own resolution parameter"
                    ),
                ),
            ),
        )

    internal_crop = bool(route.get("vendor_internal_crop"))
    note = (
        " The extractor performs its own internal crop on the full image, which is "
        "algorithm behaviour and is published as such."
        if internal_crop
        else ""
    )
    return GateResult(
        gate=gate,
        status=frozen.GateStatus.PASS,
        summary=(
            "the full canonical gray8 matrix reaches the delivered extraction "
            f"entry point unmodified at {frozen.REQUIRED_INPUT_PPI} ppi, with "
            "every geometric decision after that made inside the vendor's own "
            f"code.{note}"
        ),
    )


# --------------------------------------------------------------------- gate 3


def _gate_single_finger_raw_1to1_score_route() -> GateResult:
    """G3. One image to one template, two templates to one raw scalar score.

    The vendor's documentation describes a threshold as the minimum score needed
    to state that two fingerprints match, which is consistent both with an API
    that returns the score and with one that returns only the comparison. Which
    of the two the delivered header exposes is the whole gate.
    """
    gate = frozen.PreflightGate.SINGLE_FINGER_RAW_1TO1_SCORE_ROUTE
    state = _acquisition()
    contract = _section("score_contract")
    if contract is None:
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.NOT_REACHED,
            summary=_no_package_summary(state),
        )

    if not bool(contract.get("single_image_single_template")):
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.FAIL,
            summary=(
                "the delivered extraction entry point does not produce one "
                "template from one image"
            ),
            blockers=(
                Blocker(
                    gate=gate,
                    blocker_code=frozen.BlockerCode.RAW_SCORE_ROUTE_UNAVAILABLE,
                    affected_component="the delivered extraction entry point",
                    evidence=str(
                        contract.get("single_image_single_template_detail")
                        or "the delivered header does not expose a one-image, "
                        "one-template extraction"
                    ),
                    why_this_blocks_algorithm_5=(
                        "this benchmark compares one finger against one finger. A "
                        "route that consolidates several impressions into one "
                        "template would score a different comparison from the one "
                        "the protocol defines"
                    ),
                    how_this_would_be_lifted=(
                        "by a delivered entry point that extracts a single "
                        "template from a single image without consolidation"
                    ),
                ),
            ),
        )

    if not bool(contract.get("raw_score_reachable")):
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.FAIL,
            summary=(
                "the delivered verification entry point exposes only a "
                "thresholded decision"
            ),
            blockers=(
                Blocker(
                    gate=gate,
                    blocker_code=frozen.BlockerCode.RAW_SCORE_ROUTE_UNAVAILABLE,
                    affected_component="the delivered 1:1 verification entry point",
                    evidence=str(
                        contract.get("raw_score_detail")
                        or "the delivered header returns a match or no-match "
                        "answer and no scalar score"
                    ),
                    why_this_blocks_algorithm_5=(
                        "this benchmark stores raw scores and derives every "
                        "decision in its own decision layer from its own "
                        "protocol. A route that returns only a decision has made "
                        "the decision with a threshold this project did not "
                        "choose, and no amount of downstream work recovers the "
                        "score it was taken from"
                    ),
                    how_this_would_be_lifted=(
                        "by an official entry point that returns the similarity "
                        "score itself. It is not lifted by sweeping the threshold "
                        "to reconstruct one"
                    ),
                ),
            ),
        )

    native_type = str(contract.get("native_type") or "")
    direction = str(contract.get("direction") or "")
    threshold_changes_score = contract.get("threshold_changes_the_score")
    unresolved = [
        name
        for name, value in (
            ("native_type", native_type),
            ("direction", direction),
        )
        if not value.strip()
    ]
    if threshold_changes_score is None:
        unresolved.append("threshold_changes_the_score")
    if unresolved:
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.FAIL,
            summary=(
                "a scalar score is reachable and its contract is not settled: "
                f"{', '.join(unresolved)} unrecorded"
            ),
            blockers=(
                Blocker(
                    gate=gate,
                    blocker_code=frozen.BlockerCode.RAW_SCORE_ROUTE_UNRESOLVED,
                    affected_component="the delivered score contract",
                    evidence=(
                        f"the inspection record leaves {', '.join(unresolved)} "
                        "unrecorded"
                    ),
                    why_this_blocks_algorithm_5=(
                        "a score whose type and direction nobody established is a "
                        "number this benchmark cannot compare against another "
                        "algorithm's. The direction in particular decides what "
                        "every downstream evaluation means"
                    ),
                    how_this_would_be_lifted=(
                        "by reading the numeric type, the direction and the "
                        "threshold's effect off the delivered header, rather than "
                        "assuming any of them from the documentation site"
                    ),
                ),
            ),
        )
    if bool(threshold_changes_score):
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.FAIL,
            summary="the configured threshold changes the score, not only the decision",
            blockers=(
                Blocker(
                    gate=gate,
                    blocker_code=frozen.BlockerCode.RAW_SCORE_ROUTE_UNAVAILABLE,
                    affected_component="the delivered 1:1 verification entry point",
                    evidence=str(
                        contract.get("threshold_detail")
                        or "the delivered header shows the threshold entering the "
                        "returned number"
                    ),
                    why_this_blocks_algorithm_5=(
                        "a score that carries a threshold inside it is a decision "
                        "in numeric clothing. Storing it as a raw score would put "
                        "a choice this project did not make into every result"
                    ),
                    how_this_would_be_lifted=(
                        "by a route that returns the similarity score with the "
                        "threshold applied only to the decision beside it"
                    ),
                ),
            ),
        )
    return GateResult(
        gate=gate,
        status=frozen.GateStatus.PASS,
        summary=(
            "one image produces one template through the delivered extraction "
            "entry point, two templates produce a native "
            f"{native_type} similarity score through the delivered 1:1 "
            f"verification entry point, the direction is {direction}, and the "
            "configured threshold decides only the answer taken about the score"
        ),
    )


# --------------------------------------------------------------------- gate 4


def _gate_score_affecting_route_closure() -> GateResult:
    """G4. Is there any score-affecting choice fpbench would have to invent?

    Small on purpose. Not a full runtime qualification — nothing is executed here
    — but an inventory: every knob the delivered package exposes that could reach
    a template or a score, each with a value and the authority behind it.
    """
    gate = frozen.PreflightGate.SCORE_AFFECTING_ROUTE_CLOSURE
    state = _acquisition()
    if _inspection() is None:
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.NOT_REACHED,
            summary=_no_package_summary(state),
        )

    # Where each identity field is settled. The digest and the three descriptive
    # fields come from the declaration, because they are properties of the bytes
    # this project hashed; the binding is a property of what the package turned
    # out to contain, so it comes from the inspection.
    declaration = state.declaration
    identity = _section("package_identity") or {}
    from_declaration = {
        "product_version": getattr(declaration, "product_version", ""),
        "build_or_revision": getattr(declaration, "build_or_revision", ""),
        "platform": getattr(declaration, "platform", ""),
        "package_sha256": getattr(declaration, "sha256", ""),
    }
    identity_gaps = [
        field
        for field in frozen.PACKAGE_IDENTITY_FIELDS
        if not str(from_declaration.get(field, identity.get(field, ""))).strip()
    ]
    if identity_gaps:
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.FAIL,
            summary=(
                "the frozen route cannot be identified: "
                f"{', '.join(identity_gaps)} unrecorded"
            ),
            blockers=(
                Blocker(
                    gate=gate,
                    blocker_code=frozen.BlockerCode.PACKAGE_ROUTE_IDENTITY_UNRESOLVED,
                    affected_component="the delivered package identity",
                    evidence=(
                        f"the package declaration and inspection leave "
                        f"{', '.join(identity_gaps)} unrecorded"
                    ),
                    why_this_blocks_algorithm_5=(
                        "an algorithm identity that does not pin the exact "
                        "artifact, build and platform would let a later run "
                        "substitute a different implementation under the same "
                        "name"
                    ),
                    how_this_would_be_lifted=(
                        "by recording each of them from the delivered artifact"
                    ),
                ),
            ),
        )

    unresolved = unresolved_score_affecting_settings()
    missing = missing_setting_categories()
    if unresolved or missing:
        parts = []
        if unresolved:
            parts.append(f"{len(unresolved)} setting(s) with no delivered authority")
        if missing:
            parts.append(f"{len(missing)} knob categor(ies) never accounted for")
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.FAIL,
            summary=f"the route is not closed: {', and '.join(parts)}",
            blockers=(
                Blocker(
                    gate=gate,
                    blocker_code=frozen.BlockerCode.SCORE_AFFECTING_CHOICE_UNRESOLVED,
                    affected_component="the delivered settings surface",
                    evidence=(
                        f"unresolved: {list(unresolved)}; never accounted for: "
                        f"{list(missing)}"
                    ),
                    why_this_blocks_algorithm_5=(
                        "a value nobody recorded still decides the score. If "
                        "fpbench has to choose one, the benchmark is measuring a "
                        "configuration this project invented rather than the "
                        "implementation the vendor ships"
                    ),
                    how_this_would_be_lifted=(
                        "by reading each value off the delivered package or its "
                        "delivered documentation. It is not lifted by testing "
                        "which value works best — this stage runs no comparison "
                        "and could not know"
                    ),
                ),
            ),
        )
    return GateResult(
        gate=gate,
        status=frozen.GateStatus.PASS,
        summary=(
            f"every knob category is accounted for and every score-affecting "
            "setting rests on a delivered value; fpbench changes none of them"
        ),
    )


_GATE_RUNNERS: Mapping[frozen.PreflightGate, Any] = {
    frozen.PreflightGate.OFFICIAL_ARTIFACT_AND_TRIAL_ACCESS: (
        _gate_official_artifact_and_trial_access
    ),
    frozen.PreflightGate.DIRECT_CANONICAL500_INPUT_ROUTE: (
        _gate_direct_canonical500_input_route
    ),
    frozen.PreflightGate.SINGLE_FINGER_RAW_1TO1_SCORE_ROUTE: (
        _gate_single_finger_raw_1to1_score_route
    ),
    frozen.PreflightGate.SCORE_AFFECTING_ROUTE_CLOSURE: (
        _gate_score_affecting_route_closure
    ),
}


# ------------------------------------------------------------------ the whole


@dataclass(frozen=True, slots=True)
class GriaulePreflight:
    """The whole preflight: four gates, the verdict, and the outcome."""

    results: tuple[GateResult, ...]
    stopped_at: frozen.PreflightGate | None
    preflight_fingerprint: str

    def __post_init__(self) -> None:
        seen = tuple(result.gate for result in self.results)
        if seen != frozen.GATE_ORDER:
            raise GriauleGateError(
                f"the gates were reported as {seen} and the frozen order is "
                f"{frozen.GATE_ORDER}"
            )
        stopping = [
            result.gate
            for result in self.results
            if result.status.stops_the_run
            and result.status is not frozen.GateStatus.NOT_REACHED
        ]
        if len(stopping) > 1:
            raise GriauleGateError(
                "every gate after acquisition is a question about delivered "
                f"bytes, so exactly one gate stops the run, and these did: {stopping}"
            )
        if stopping and stopping[0] is not self.stopped_at:
            raise GriauleGateError(
                f"the stopping gate is {self.stopped_at} and the gate that did not "
                f"pass is {stopping[0]}"
            )
        if not stopping and self.stopped_at is not None:
            raise GriauleGateError(
                f"stopped at {self.stopped_at} with every gate passing"
            )
        if self.stopped_at is None:
            unreached = [
                result.gate
                for result in self.results
                if result.status is frozen.GateStatus.NOT_REACHED
            ]
            if unreached:  # pragma: no cover - defensive
                raise GriauleGateError(
                    f"{unreached} were never reached and nothing stopped the run"
                )

    @property
    def passed(self) -> bool:
        """Every gate passed. Not "no gate failed": NOT_REACHED is not a pass."""
        return all(r.status is frozen.GateStatus.PASS for r in self.results)

    @property
    def outcome(self) -> str:
        """What this run established. Two of the four are not verdicts.

        A failure dominates: something was found wrong with the candidate, and a
        wait or a chore stranded behind it does not soften that. Between the two
        non-verdicts, a vendor dependency dominates a local one for the same
        reason — if the request has been sent, the next move is not ours.
        """
        if self.passed:
            return frozen.STAGE_14A_PASS_OUTCOME
        statuses = {result.status for result in self.results}
        if frozen.GateStatus.FAIL in statuses:
            return frozen.STAGE_14A_FAIL_OUTCOME
        if frozen.GateStatus.PENDING_ACCESS in statuses:
            return frozen.STAGE_14A_PENDING_OUTCOME
        if frozen.GateStatus.ACTION_REQUIRED in statuses:
            return frozen.STAGE_14A_INCOMPLETE_OUTCOME
        return frozen.STAGE_14A_FAIL_OUTCOME  # pragma: no cover - unreachable

    @property
    def is_final(self) -> bool:
        return self.outcome in frozen.STAGE_14A_FINAL_OUTCOMES

    @property
    def opens_stage_14b(self) -> bool:
        return self.passed

    @property
    def reopens_algorithm_5_search(self) -> bool:
        """Only a final failure returns selection to the next candidate.

        A pending or incomplete Stage 14A reopens nothing, because it has not
        closed anything: Griaule is still the candidate under examination.
        """
        return self.outcome == frozen.STAGE_14A_FAIL_OUTCOME

    @property
    def failure_class(self) -> frozen.FailureClass | None:
        """What kind of failure this is, derived from the blocker that stopped it."""
        if self.outcome != frozen.STAGE_14A_FAIL_OUTCOME:
            return None
        for blocker in self.blockers:
            return frozen.FailureClass(blocker.blocker_code.value)
        return None  # pragma: no cover - a FAIL always carries a blocker

    @property
    def gates_reached(self) -> int:
        return sum(
            1 for r in self.results if r.status is not frozen.GateStatus.NOT_REACHED
        )

    @property
    def gates_passed(self) -> int:
        return sum(1 for r in self.results if r.status is frozen.GateStatus.PASS)

    @property
    def gates_awaiting_action(self) -> int:
        return sum(
            1 for r in self.results if r.status is frozen.GateStatus.ACTION_REQUIRED
        )

    @property
    def gates_pending_access(self) -> int:
        return sum(
            1 for r in self.results if r.status is frozen.GateStatus.PENDING_ACCESS
        )

    @property
    def blockers(self) -> tuple[Blocker, ...]:
        return tuple(
            sorted(
                (b for r in self.results for b in r.blockers),
                key=lambda item: item.blocker_code.value,
            )
        )

    @property
    def pending_reasons(self) -> tuple[PendingReason, ...]:
        return tuple(r.pending for r in self.results if r.pending is not None)

    @property
    def outstanding_actions(self) -> tuple[OutstandingAction, ...]:
        return tuple(r.outstanding for r in self.results if r.outstanding is not None)

    def result(self, gate: frozen.PreflightGate) -> GateResult:
        for item in self.results:
            if item.gate is gate:
                return item
        raise KeyError(gate)  # pragma: no cover - GATE_ORDER is exhaustive

    def status(self, gate: frozen.PreflightGate) -> frozen.GateStatus:
        return self.result(gate).status


def run_preflight() -> GriaulePreflight:
    """Run the gate order, and stop at the first gate that does not pass."""
    _RUN_CACHE.clear()
    results: list[GateResult] = []
    stopped_at: frozen.PreflightGate | None = None
    for gate in frozen.GATE_ORDER:
        if stopped_at is not None:
            results.append(
                GateResult(
                    gate=gate,
                    status=frozen.GateStatus.NOT_REACHED,
                    summary=_not_reached_reason(stopped_at),
                )
            )
            continue
        result = _GATE_RUNNERS[gate]()
        results.append(result)
        if result.status.stops_the_run:
            stopped_at = gate
    return GriaulePreflight(
        results=tuple(results),
        stopped_at=stopped_at,
        preflight_fingerprint=stable_hash(
            {
                "schema": "stage_14a_preflight_v1",
                "candidate_id": frozen.CANDIDATE_ID,
                "gates": [(r.gate.value, r.status.value) for r in results],
                "blockers": sorted(
                    b.blocker_code.value for r in results for b in r.blockers
                ),
                "pending": sorted(
                    r.pending.kind.value for r in results if r.pending is not None
                ),
                "actions": sorted(
                    r.outstanding.action.value
                    for r in results
                    if r.outstanding is not None
                ),
                "observations": observed.observations_fingerprint(),
            },
            length=64,
        ),
    )


# ------------------------------------------------------------- the secret guard

_SENSITIVE_PATTERNS = tuple(
    (name, re.compile(source)) for name, source in frozen.SENSITIVE_VALUE_PATTERNS
)


def find_sensitive_material(node: Any, trail: str = "") -> tuple[str, ...]:
    """Every place a document carries a credential, by key or by value shape."""
    found: list[str] = []
    if isinstance(node, Mapping):
        for key, value in node.items():
            name = str(key)
            where = f"{trail}.{name}" if trail else name
            if name.strip().lower() in frozen.SENSITIVE_EVIDENCE_KEYS:
                found.append(f"{where}: a key that names licence or personal material")
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
    """The raising form, for the reader and for the publisher.

    Raises:
        GriauleSensitiveEvidenceError: the value carries licence material, a
            machine path or a personal address.
    """
    findings = find_sensitive_material(node)
    if findings:
        raise GriauleSensitiveEvidenceError(f"{where} carries {list(findings)}")


# ---------------------------------------------------------- published documents


def _gate_rows(preflight: GriaulePreflight) -> tuple[Mapping[str, Any], ...]:
    return tuple(
        {
            "gate": result.gate.value,
            "position": index,
            "status": result.status.value,
            "is_final": result.status.is_final,
            "summary": result.summary,
            "documents": list(frozen.gate_documents(result.gate)),
            "blockers": [blocker.blocker_code.value for blocker in result.blockers],
            "pending": result.pending.kind.value if result.pending else None,
            "outstanding_action": (
                result.outstanding.action.value if result.outstanding else None
            ),
        }
        for index, result in enumerate(preflight.results, start=1)
    )


def _status(preflight: GriaulePreflight, gate: frozen.PreflightGate) -> str:
    return preflight.status(gate).value


def marker_blocker_rows(blockers: tuple[Blocker, ...]) -> tuple[Mapping[str, str], ...]:
    """The blocker rows a marker carries."""
    return tuple(blocker.as_row() for blocker in blockers)


def predecessor_binding_document(
    preflight: GriaulePreflight,
) -> Mapping[str, Any]:
    """What this stage is a successor to, and what it may never read."""
    return {
        "schema": "stage_14a_predecessor_binding_v1",
        "algorithm_slot": frozen.ALGORITHM_SLOT,
        "candidate_id": frozen.CANDIDATE_ID,
        "predecessor": {
            "stage": "13A",
            "outcome": frozen.STAGE_13A_OUTCOME,
            "failure_class": frozen.STAGE_13A_FAILURE_CLASS,
            "finalization_fingerprint": frozen.STAGE_13A_FINALIZATION_FINGERPRINT,
            "what_it_established": (
                "that the FingerCell trial archive was obtained, pinned and "
                "compiled against, and that its trial entitlement could not be "
                "established in the qualified environment. No extraction, match "
                "or score was ever produced, and the marker reopened the "
                "Algorithm 5 search"
            ),
            "why_it_is_bound": (
                "Stage 14A exists because that slot is open. Binding the exact "
                "fingerprint is what makes this a successor rather than a "
                "restart, and the value was taken from the closed marker itself "
                "rather than written here as a placeholder"
            ),
        },
        "immutable": [
            {
                "stage": "11B",
                "outcome": frozen.STAGE_11B_OUTCOME,
                "finalization_fingerprint": (
                    frozen.STAGE_11B_FINALIZATION_FINGERPRINT
                ),
                "why": (
                    "Algorithm 4's 6,000 published outcomes. Bound and never "
                    "read: this stage consults no prior algorithm's scores"
                ),
            },
            {
                "stage": "8E",
                "outcome": frozen.STAGE8E_OUTCOME,
                "finalization_fingerprint": (
                    frozen.STAGE8E_FINALIZATION_FINGERPRINT
                ),
                "purpose_fingerprint": frozen.STAGE8E_PURPOSE_FINGERPRINT,
                "policy_fingerprint": frozen.STAGE8E_POLICY_FINGERPRINT,
                "why": (
                    "the third-party research-use policy, reused and not "
                    "reopened. It is applied to the terms delivered with a "
                    "package, never to a marketing page"
                ),
            },
        ],
        "what_this_stage_is_a_response_to": (
            "two Algorithm 5 candidates that ended at acquisition and "
            "entitlement. Stage 12A built ten gates and reached one; Stage 13A "
            "built ten gates, a bridge and a qualification harness, obtained the "
            "archive and still reached three. This stage asks the acquisition and "
            "route questions first and builds nothing until they are answered"
        ),
        "forbidden_reads": [
            "sd300_image_bytes",
            "sd300_pair_manifest",
            "sd300_scores",
            "sourceafis_scores",
            "nbis_scores",
            "flx_scores",
            "verifinger_scores",
            "fingercell_scores",
        ],
        "prior_algorithm_scores_read": False,
        "sd300_used": False,
        "predecessor_gate_status": _status(
            preflight, frozen.PreflightGate.OFFICIAL_ARTIFACT_AND_TRIAL_ACCESS
        ),
    }


def acquisition_status_document(preflight: GriaulePreflight) -> Mapping[str, Any]:
    """G1's first document: every official route, and where acquisition stands."""
    gate = frozen.PreflightGate.OFFICIAL_ARTIFACT_AND_TRIAL_ACCESS
    state = _acquisition()
    result = preflight.result(gate)
    return {
        "schema": "stage_14a_acquisition_status_v1",
        "gate": gate.value,
        "gate_status": result.status.value,
        "acquisition_status": state.status.value,
        "package_presence": state.presence.value,
        "package_obtained": state.obtained,
        "is_pending": state.status.is_pending,
        "is_a_local_action": state.status.is_a_local_action,
        "is_refusal": state.status.is_refusal,
        "request_status": REQUEST_STATUS.value,
        "request_sent": REQUEST_STATUS.is_sent,
        "request_sent_utc": REQUEST_SENT_UTC,
        "request_draft": REQUEST_DRAFT.as_row(),
        "vendor_was_not_asked_and_did_not_refuse": not REQUEST_STATUS.is_sent,
        "self_service_locator_found": observed.SELF_SERVICE_LOCATOR_FOUND,
        "detail": state.detail,
        "official_delivery_channels": list(frozen.OFFICIAL_DELIVERY_CHANNELS),
        "official_routes": [dict(row) for row in observed.route_rows()],
        "named_vendor_contact_routes": list(observed.NAMED_VENDOR_CONTACT_ROUTES),
        "refused_route_categories": [dict(row) for row in observed.refused_rows()],
        "refused_acquisition_sources": list(frozen.REFUSED_ACQUISITION_SOURCES),
        "acquisition_pass_conditions": list(frozen.ACQUISITION_PASS_CONDITIONS),
        "what_would_change_the_status": list(observed.WHAT_WOULD_CHANGE_THE_STATUS),
        "pending_is_not_a_failure": True,
        "an_unsent_request_is_not_a_vendor_silence": True,
        "outstanding_action": (
            result.outstanding.as_row() if result.outstanding else None
        ),
        "pending_reason": result.pending.as_row() if result.pending else None,
    }


def package_manifest_document(preflight: GriaulePreflight) -> Mapping[str, Any]:
    """G1's second document: what the package turned out to be, or nothing."""
    gate = frozen.PreflightGate.OFFICIAL_ARTIFACT_AND_TRIAL_ACCESS
    state = _acquisition()
    declaration = state.declaration
    redistribution = redistribution_record()
    return {
        "schema": "stage_14a_package_manifest_v1",
        "gate": gate.value,
        "gate_status": _status(preflight, gate),
        "candidate_id": frozen.CANDIDATE_ID,
        "algorithm_slot": frozen.ALGORITHM_SLOT,
        "implementation_origin": frozen.IMPLEMENTATION_ORIGIN,
        "product_family": frozen.PRODUCT_FAMILY,
        "implementation_version": (
            declaration.product_version
            if declaration
            else frozen.IMPLEMENTATION_VERSION_SENTINEL
        ),
        "production_algorithm_id_frozen": frozen.PRODUCTION_ALGORITHM_ID_FROZEN,
        "package_obtained": state.obtained,
        "package": declaration.as_row() if declaration else None,
        "identity_fields_required": list(frozen.PACKAGE_IDENTITY_FIELDS),
        "version_is_not_taken_from_the_website": (
            frozen.VERSION_IS_NOT_TAKEN_FROM_THE_WEBSITE
        ),
        "why_the_version_is_a_sentinel": (
            "the vendor's public documentation names three builds and publishes "
            "no version number, no build number and no release date for any of "
            "them. There is no number to freeze even if freezing one from a page "
            "were allowed, and it is not (docs/adr/0110)"
        ),
        "upstream_observations": [dict(row) for row in observed.product_rows()],
        "observations_are_indications_only": True,
        # `redistribution_decision` rather than `decision`: this stage's guard
        # forbids a key called `decision` anywhere in a published document,
        # because a match/no-match answer is exactly what Stage 14A must never
        # carry. A redistribution verdict is a different thing entirely and gets
        # a name that says so.
        "redistribution": {
            "redistribution_decision": redistribution.decision.value,
            "basis": redistribution.basis,
            "redistributed_by_fpbench": redistribution.redistributed_by_fpbench,
        },
    }


def research_use_trial_document(preflight: GriaulePreflight) -> Mapping[str, Any]:
    """G1's third document: what the delivered terms and bundled trial permit."""
    gate = frozen.PreflightGate.OFFICIAL_ARTIFACT_AND_TRIAL_ACCESS
    state = _acquisition()
    inspection = _inspection()
    assessment, refusal = _assessment_or_refusal(inspection)
    return {
        "schema": "stage_14a_research_use_trial_v1",
        "gate": gate.value,
        "gate_status": _status(preflight, gate),
        "stage8e_policy_fingerprint": frozen.STAGE8E_FINALIZATION_FINGERPRINT,
        "policy_applies_to": "the terms delivered with the package",
        "policy_does_not_apply_to": "the vendor's public documentation or marketing pages",
        "license_notices_read": bool(inspection),
        "assessment": (
            {
                "decision": assessment.decision.value,
                "may_execute_locally": assessment.may_execute_locally,
                "basis": assessment.basis,
            }
            if assessment is not None
            else None
        ),
        "assessment_refusal": refusal,
        "why_no_assessment_yet": (
            None if assessment is not None else _NO_LICENSE_EVIDENCE_YET
        ),
        "trial_days_advertised_upstream": observed.ADVERTISED_TRIAL_DAYS,
        "trial_is_advertised_as_bundled": True,
        "bundled_trial_present_in_package": (
            state.declaration.bundled_trial_present if state.declaration else None
        ),
        "trial_activated": False,
        "trial_clock_started": False,
        "license_bypass_attempted": False,
        "trial_reset_attempted": False,
        "why_no_activation_here": (
            "Stage 14A activates nothing. A trial clock that starts before the "
            "route is known to be usable is a clock spent debugging rather than "
            "measuring, which is the mistake Stage 13A's own ADR 0115 was written "
            "against. Activation belongs to Stage 14B, after this stage has "
            "established that there is something worth activating for"
        ),
        "redistributed_by_fpbench": False,
    }


def input_route_document(preflight: GriaulePreflight) -> Mapping[str, Any]:
    """G2's document: how a canonical image would reach the extractor."""
    gate = frozen.PreflightGate.DIRECT_CANONICAL500_INPUT_ROUTE
    route = _section("input_route")
    return {
        "schema": "stage_14a_input_route_v1",
        "gate": gate.value,
        "gate_status": _status(preflight, gate),
        "benchmark_input_profile": frozen.BENCHMARK_INPUT_PROFILE,
        "benchmark_input_ppi": frozen.BENCHMARK_INPUT_PPI,
        "benchmark_input_pixel_format": frozen.BENCHMARK_INPUT_PIXEL_FORMAT,
        "required_input_ppi": frozen.REQUIRED_INPUT_PPI,
        "ideal_route": list(frozen.IDEAL_INPUT_ROUTE),
        "permitted_decode_route": list(frozen.PERMITTED_DECODE_ROUTE),
        "decode_equivalence_requirements": list(
            frozen.DECODE_EQUIVALENCE_REQUIREMENTS
        ),
        "refused_preprocessing": list(frozen.REFUSED_PREPROCESSING),
        "vendor_internal_crop_is_algorithm_behaviour": (
            frozen.VENDOR_INTERNAL_CROP_IS_ALGORITHM_BEHAVIOUR
        ),
        "upstream_extraction_pixel_limit": list(frozen.UPSTREAM_EXTRACTION_PIXEL_LIMIT),
        "upstream_capture_pixel_limit": list(frozen.UPSTREAM_CAPTURE_PIXEL_LIMIT),
        "upstream_limit_is_an_indication_not_a_route": True,
        "the_question_this_gate_answers": (
            "whether the caller or the extractor is the one required to respect "
            "the documented 500 x 500 extraction limit. A crop the extractor "
            "performs on a full image it was handed is algorithm behaviour; a "
            "crop the caller must perform first is fpbench choosing which part of "
            "the finger the algorithm sees, and it is a hard reject "
            "(docs/adr/0124)"
        ),
        "observed_route": dict(route) if route else None,
        "fpbench_preprocessing_required": (
            bool(route.get("fpbench_preprocessing_required")) if route else None
        ),
        "route_established": _status(preflight, gate) == frozen.GateStatus.PASS.value,
    }


def score_contract_document(preflight: GriaulePreflight) -> Mapping[str, Any]:
    """G3's document: the raw 1:1 score, or the reason there is none."""
    gate = frozen.PreflightGate.SINGLE_FINGER_RAW_1TO1_SCORE_ROUTE
    contract = _section("score_contract")
    return {
        "schema": "stage_14a_score_contract_v1",
        "gate": gate.value,
        "gate_status": _status(preflight, gate),
        "questions_the_delivered_header_must_answer": list(
            frozen.SCORE_CONTRACT_QUESTIONS
        ),
        "score_shape_is_not_assumed": frozen.SCORE_SHAPE_IS_NOT_ASSUMED,
        "expected_direction_upstream": frozen.SCORE_DIRECTION_EXPECTED_UPSTREAM,
        "observed_contract": dict(contract) if contract else None,
        "single_image_single_template": (
            bool(contract.get("single_image_single_template")) if contract else None
        ),
        "raw_score_reachable": (
            bool(contract.get("raw_score_reachable")) if contract else None
        ),
        "native_type": (str(contract.get("native_type")) if contract else None),
        "direction": (str(contract.get("direction")) if contract else None),
        "threshold": {
            "used_as_a_decision_here": False,
            "applied_inside_the_score": (
                bool(contract.get("threshold_changes_the_score"))
                if contract
                else None
            ),
            "upstream_default_indication": (
                frozen.UPSTREAM_DEFAULT_THRESHOLD_INDICATION
            ),
            "upstream_default_rotation_tolerance_indication": (
                frozen.UPSTREAM_DEFAULT_ROTATION_TOLERANCE_INDICATION
            ),
            "upstream_defaults_are_observations_only": True,
            "calibration": "NONE",
            "why": (
                "this benchmark stores raw scores and derives every decision in "
                "its own decision layer from its own protocol. The vendor's "
                "default of 20 is recorded because it is what the delivered engine "
                "will be constructed with, not because anything here applies it"
            ),
        },
        "fpbench_score_transformation": frozen.FPBENCH_SCORE_TRANSFORMATION,
        "pair_role_binding": [list(pair) for pair in frozen.PAIR_ROLE_BINDING],
        "pair_binding_comes_from_the_api_under_test": True,
        "scores_produced_in_this_stage": 0,
    }


def route_closure_document(preflight: GriaulePreflight) -> Mapping[str, Any]:
    """G4's document: every knob that could reach the score, and its authority."""
    gate = frozen.PreflightGate.SCORE_AFFECTING_ROUTE_CLOSURE
    return {
        "schema": "stage_14a_route_closure_v1",
        "gate": gate.value,
        "gate_status": _status(preflight, gate),
        "setting_inventory_fields": list(frozen.SETTING_INVENTORY_FIELDS),
        "categories_to_account_for": list(frozen.SETTINGS_TO_ACCOUNT_FOR),
        "categories_not_accounted_for": list(missing_setting_categories()),
        "settings": [dict(row) for row in _rows("settings")],
        "unresolved_score_affecting_settings": list(
            unresolved_score_affecting_settings()
        ),
        "default_fpbench_changed": frozen.DEFAULT_FPBENCH_CHANGED,
        "no_setting_is_chosen_by_trying_values": (
            frozen.NO_SETTING_IS_CHOSEN_BY_TRYING_VALUES
        ),
        "provenance_vocabulary": [
            {
                "provenance": member.value,
                "is_upstream_authority": member.is_upstream_authority,
            }
            for member in frozen.SettingProvenance
        ],
        "why_two_categories_cannot_be_empty": (
            "the vendor's own public documentation proves a verification "
            "threshold and a rotation tolerance exist and are matcher parameters. "
            "An inventory that never mentions them would be visibly incomplete "
            "rather than arguably complete"
        ),
        "package_identity_fields": list(frozen.PACKAGE_IDENTITY_FIELDS),
        "route_closed": _status(preflight, gate) == frozen.GateStatus.PASS.value,
    }


def preflight_report_document(preflight: GriaulePreflight) -> Mapping[str, Any]:
    """The whole run: gates, outcome, and what it does and does not say."""
    return {
        "schema": "stage_14a_preflight_report_v1",
        "candidate_id": frozen.CANDIDATE_ID,
        "algorithm_slot": frozen.ALGORITHM_SLOT,
        "product_family": frozen.PRODUCT_FAMILY,
        "implementation_origin": frozen.IMPLEMENTATION_ORIGIN,
        "implementation_version": frozen.IMPLEMENTATION_VERSION_SENTINEL,
        "outcome": preflight.outcome,
        "outcome_is_final": preflight.is_final,
        "writes_a_marker": preflight.is_final,
        "failure_class": (
            preflight.failure_class.value if preflight.failure_class else None
        ),
        "gate_count_defined": frozen.GATE_COUNT,
        "gates_reached": preflight.gates_reached,
        "gates_passed": preflight.gates_passed,
        "gates_pending_access": preflight.gates_pending_access,
        "gates_awaiting_action": preflight.gates_awaiting_action,
        "gates": [dict(row) for row in _gate_rows(preflight)],
        "blockers": [dict(row) for row in marker_blocker_rows(preflight.blockers)],
        "pending_reasons": [
            dict(item.as_row()) for item in preflight.pending_reasons
        ],
        "outstanding_actions": [
            dict(item.as_row()) for item in preflight.outstanding_actions
        ],
        "opens_stage_14b": preflight.opens_stage_14b,
        "reopens_algorithm_5_search": preflight.reopens_algorithm_5_search,
        "predecessor_fingerprint": frozen.STAGE_13A_FINALIZATION_FINGERPRINT,
        "observations_fingerprint": observed.observations_fingerprint(),
        "preflight_fingerprint": preflight.preflight_fingerprint,
        "what_this_stage_does_not_do": list(frozen.STAGE_14A_DOES_NOT),
        "sd300_used": False,
        "prior_algorithm_scores_read": False,
        "scores_produced": 0,
        "what_a_non_final_outcome_means": (
            "GRIAULE_PREFLIGHT_PENDING_ACCESS means an official route was walked "
            "and somebody outside this project has to move next. "
            "GRIAULE_PREFLIGHT_INCOMPLETE means this project has a step left to "
            "take. Neither is a finding about Griaule and neither writes a marker "
            "(docs/adr/0121)"
        ),
    }


_DOCUMENT_BUILDERS: Mapping[str, Any] = {
    frozen.PREDECESSOR_BINDING_NAME: predecessor_binding_document,
    frozen.ACQUISITION_STATUS_NAME: acquisition_status_document,
    frozen.PACKAGE_MANIFEST_NAME: package_manifest_document,
    frozen.RESEARCH_USE_TRIAL_NAME: research_use_trial_document,
    frozen.INPUT_ROUTE_NAME: input_route_document,
    frozen.SCORE_CONTRACT_NAME: score_contract_document,
    frozen.ROUTE_CLOSURE_NAME: route_closure_document,
    frozen.PREFLIGHT_REPORT_NAME: preflight_report_document,
}


def evidence_document(preflight: GriaulePreflight, name: str) -> Mapping[str, Any]:
    """Build one published document by name, guarded before it is returned."""
    try:
        builder = _DOCUMENT_BUILDERS[name]
    except KeyError as exc:
        raise Stage14AFinalizationError(
            f"{name} is not a Stage 14A document; this stage publishes "
            f"{list(frozen.DERIVABLE_EVIDENCE_FILES)}"
        ) from exc
    document = builder(preflight)
    require_no_sensitive_material(document, where=name)
    return document
