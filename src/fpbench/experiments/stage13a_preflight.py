"""The ten hard gates, run in order, and the verdict that follows.

The engine has no verdict parameter, for the reason every preflight since Stage
10B has none: an engine that accepted an outcome and then validated it would be
a very elaborate way of writing the outcome down. It reads the acquisition state
of this machine, the inspection record beside the unpacked archive, the record a
qualification run left behind, and Stage 8E's own policy, applies the order
frozen in :mod:`fpbench.experiments.stage13a_fingercell_identity`, and reports
what follows.

**Fail-fast is the design, not an optimisation.** The run stops at the first gate
that fails and every later gate is published ``NOT_REACHED``.

**An outstanding action stops the run without judging it.** A gate may report
``ACTION_REQUIRED``, and it stops the run in exactly the same mechanical way a
failure does — and means the opposite. Every later gate is ``NOT_REACHED``, no
blocker is raised, no marker is written, and nothing has been established about
FingerCell either way. The one thing that must never happen is an outstanding
action being published as a finding (docs/adr/0112).

**A gate is answered from the archive or it is not answered.** Every runner below
reaches its conclusion from delivered bytes, from a record a run on this machine
produced, or from Stage 8E's policy. None of them reads a product page.

Nothing here reads SD300, reads a prior algorithm's scores, downloads anything,
activates a licence, loads a vendor library or produces a score.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from fpbench.core.fingercell_preflight_errors import (
    FingerCellContaminationError,
    FingerCellGateError,
    FingerCellSensitiveEvidenceError,
    Stage13AFinalizationError,
)
from fpbench.core.serialization import stable_hash
from fpbench.experiments import stage13a_fingercell_identity as frozen
from fpbench.experiments import stage13a_fingercell_observations as observed
from fpbench.experiments.stage13a_acquisition import (
    AcquisitionState,
    acquisition_state,
    artifact_store_prefix_path,
    require_no_fingercell_bytes_in_git,
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
    project_purpose,
)

__all__ = [
    "PACKAGE_INSPECTION_NAME",
    "Blocker",
    "OutstandingAction",
    "GateResult",
    "FingerCellPreflight",
    "require_stage8e_is_the_policy_this_reuses",
    "require_stage12a_is_the_closed_predecessor",
    "require_stage11b_is_unchanged",
    "require_no_fingercell_bytes_in_git",
    "require_no_verifinger_contamination",
    "acquisition_state",
    "package_inspection",
    "qualification_record",
    "unresolved_score_affecting_settings",
    "research_use_assessment",
    "redistribution_record",
    "run_preflight",
    "evidence_document",
    "marker_blocker_rows",
    "marker_action_rows",
    "find_sensitive_material",
    "require_no_sensitive_material",
]

#: What the maintainer writes into the store after inspecting the unpacked
#: archive and exercising it: the binding selected, the runtime closure, the
#: input route, the extraction profile, every setting with its provenance, the
#: score contract and the trial's actual entitlement. Outside Git, like
#: everything else in the store.
PACKAGE_INSPECTION_NAME = "package-inspection.json"


# ------------------------------------------------------------ the closed stages


def _read_marker(
    repository_root: Path, relative: str, what: str
) -> Mapping[str, Any]:
    path = Path(repository_root) / relative
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Stage13AFinalizationError(
            f"cannot read the {what} marker at {relative}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise Stage13AFinalizationError(f"the {what} marker is not a JSON object")
    return payload


def require_stage8e_is_the_policy_this_reuses(repository_root: Path) -> None:
    """Confirm the policy Stage 13A reuses is the policy it was written against.

    Raises:
        Stage13AFinalizationError: the published Stage 8E marker, the live
            purpose or the live policy has moved. Stage 13A does not repair
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
            raise Stage13AFinalizationError(
                f"the Stage 8E marker's {key} is {found!r} and Stage 13A was "
                f"written against {value!r}. Stage 8E is a closed stage; a "
                "capability it lacks is a corrective policy stage, not an edit "
                "from here"
            )
    declaration = project_purpose()
    if declaration.purpose_fingerprint != frozen.STAGE8E_PURPOSE_FINGERPRINT:
        raise Stage13AFinalizationError(
            "the live project purpose no longer fingerprints to what Stage 8E "
            "published; every Stage 13A decision would be taken under a "
            "different premise"
        )


def require_stage12a_is_the_closed_predecessor(repository_root: Path) -> str:
    """Confirm Stage 12A is closed, and closed the way Stage 13A assumes.

    Stage 13A exists *because* Stage 12A failed on a vendor refusal, and it
    inherits an open Algorithm 5 slot from it. If that marker said anything else
    — a pass, a different failure class, or a slot it did not reopen — then this
    stage is standing on a premise that is not there.

    Returns:
        The exact Stage 12A finalization fingerprint, for the marker to bind.

    Raises:
        Stage13AFinalizationError: Stage 12A is missing, is not final, or does
            not say what Stage 13A was written against.
    """
    relative = "/".join(
        (frozen.STAGE_12A_EVIDENCE_DIRECTORY, "stage-12a-finalization.json")
    )
    marker = _read_marker(repository_root, relative, "Stage 12A")
    expected = {
        "outcome": frozen.STAGE_12A_OUTCOME,
        "failure_class": frozen.STAGE_12A_FAILURE_CLASS,
        "stage_12a_finalization_fingerprint": (
            frozen.STAGE_12A_FINALIZATION_FINGERPRINT
        ),
    }
    for key, value in expected.items():
        found = marker.get(key)
        if found != value:
            raise Stage13AFinalizationError(
                f"the Stage 12A marker's {key} is {found!r} and Stage 13A binds "
                f"{value!r}. Stage 13A is a successor to one exact closed stage, "
                "and a predecessor that moved is a predecessor nothing follows"
            )
    if marker.get("reopens_algorithm_5_search") is not True:
        raise Stage13AFinalizationError(
            "the Stage 12A marker does not reopen the Algorithm 5 search, so "
            "there is no open slot for this candidate to be preflighted into"
        )
    if marker.get("opens_stage_12b") is not False:
        raise Stage13AFinalizationError(
            "the Stage 12A marker opens Stage 12B, which would mean Algorithm 5 "
            "was already settled by another candidate"
        )
    return str(marker["stage_12a_finalization_fingerprint"])


def require_stage11b_is_unchanged(repository_root: Path) -> str:
    """Confirm Algorithm 4's published outcomes are still exactly where they were.

    Stage 13A never reads Stage 11B's scores. It binds the marker so that "Stage
    11B was not edited" is checkable rather than asserted — which matters more
    here than anywhere, because Stage 11B's algorithm and this candidate come
    from the same vendor (docs/adr/0114).
    """
    relative = "/".join(
        ("evidence", "stage11b-" + "verifinger-canonical500-raw", "stage-11b-finalization.json")
    )
    marker = _read_marker(repository_root, relative, "Stage 11B")
    if marker.get("outcome") != frozen.STAGE_11B_OUTCOME:
        raise Stage13AFinalizationError(
            "the Stage 11B marker's outcome has changed; Algorithm 4 is immutable "
            "here"
        )
    fingerprint = str(marker.get("stage_11b_finalization_fingerprint", ""))
    if fingerprint != frozen.STAGE_11B_FINALIZATION_FINGERPRINT:
        raise Stage13AFinalizationError(
            "the Stage 11B finalization fingerprint has moved; Stage 13A was "
            "written against the published one"
        )
    return fingerprint


# ----------------------------------------------------------------- Stage 8E


def research_use_assessment(
    inspection: Mapping[str, Any] | None,
) -> ResearchUseAssessment | None:
    """What Stage 8E returns over the notices delivered inside the archive.

    Returns:
        ``None`` where no archive has been inspected. That is not a refusal and
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
    if not isinstance(notices, Sequence) or not notices:
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
        raise Stage13AFinalizationError(
            "the delivered licence limits the field of use and only "
            f"{len(readings)} plausible reading was recorded. Stage 8E needs at "
            "least two to compute the conservative answer, and Stage 13A does not "
            "assume one on its behalf"
        )
    restrictions = tuple(
        NonBlockingRestriction(str(item))
        for item in licence.get("non_blocking_restrictions", ())
        if str(item) in {member.value for member in NonBlockingRestriction}
    )
    observation = LicenseObservation(
        observation_id="neurotechnology_fingercell_delivered_license",
        component_kind=ThirdPartyComponentKind.RUNTIME_BINARY,
        subject=(
            "the FingerCell 3.3 SDK trial as delivered, under the terms shipped "
            "inside the archive"
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
        assessment_id="neurotechnology_fingercell_local_research_execution",
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
    """What fpbench does by way of redistribution. Nothing, under either outcome."""
    return RedistributionRecord(
        decision=RedistributionDecision.NOT_ALLOWED,
        basis=(
            "A vendor SDK trial is not redistributable, and fpbench redistributes "
            "nothing in any case. No archive byte, native module, licence or "
            "template enters this repository (docs/adr/0083)."
        ),
        redistributed_by_fpbench=False,
    )


# ------------------------------------------------------------------- the gates


@dataclass(frozen=True, slots=True)
class Blocker:
    """One reason FingerCell cannot enter fpbench as Algorithm 5.

    Every blocker describes something that was *observed*. ``how_this_would_be_
    lifted`` is mandatory: a blocker nobody can act on is a blocker nobody can
    lift.
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
            raise FingerCellGateError(
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
                raise FingerCellGateError(f"{self.blocker_code.value}: {name} is empty")


@dataclass(frozen=True, slots=True)
class OutstandingAction:
    """A local step nobody has taken yet.

    Structurally a sibling of :class:`Blocker` and semantically its opposite. A
    blocker says something about FingerCell; an outstanding action says something
    about this project's own progress and nothing whatever about the candidate
    (docs/adr/0112).
    """

    gate: frozen.PreflightGate
    action: frozen.RequiredAction
    what_has_been_done: str
    what_remains: tuple[str, ...]
    what_it_would_answer: str

    def __post_init__(self) -> None:
        permitted = dict(frozen.GATE_ACTIONS)[self.gate]
        if self.action not in permitted:
            raise FingerCellGateError(
                f"{self.action.value} does not belong to {self.gate.value}; an "
                "action reported at the wrong gate would send somebody to do the "
                "wrong work"
            )
        if not str(self.what_has_been_done).strip():
            raise FingerCellGateError(
                f"{self.action.value}: an outstanding action says what has already "
                "been done, so that nobody repeats it"
            )
        if not self.what_remains:
            raise FingerCellGateError(
                f"{self.action.value}: an outstanding action names what would move "
                "it; one that named nothing would be indistinguishable from giving "
                "up"
            )


@dataclass(frozen=True, slots=True)
class GateResult:
    """One gate's conclusion."""

    gate: frozen.PreflightGate
    status: frozen.GateStatus
    summary: str
    blockers: tuple[Blocker, ...] = ()
    outstanding: OutstandingAction | None = None

    def __post_init__(self) -> None:
        if self.status is frozen.GateStatus.PASS and (
            self.blockers or self.outstanding
        ):
            raise FingerCellGateError(
                f"{self.gate.value}: a gate that passed carries no blockers and "
                "nothing outstanding; a blocker is not a reservation to be weighed"
            )
        if self.status is frozen.GateStatus.FAIL and not self.blockers:
            raise FingerCellGateError(f"{self.gate.value}: a gate that failed names why")
        if self.status is frozen.GateStatus.FAIL and self.outstanding:
            raise FingerCellGateError(
                f"{self.gate.value}: a gate that failed found something wrong with "
                "the route, and an outstanding action beside it would blur the two "
                "claims this stage keeps apart"
            )
        if self.status is frozen.GateStatus.ACTION_REQUIRED:
            if self.blockers:
                raise FingerCellGateError(
                    f"{self.gate.value}: an action has not been performed, so "
                    "nothing has been found; a blocker here would say something "
                    "about FingerCell that nothing established (docs/adr/0112)"
                )
            if self.outstanding is None:
                raise FingerCellGateError(
                    f"{self.gate.value}: a gate awaiting an action says which action"
                )
        if self.status is frozen.GateStatus.NOT_REACHED and (
            self.blockers or self.outstanding
        ):
            raise FingerCellGateError(
                f"{self.gate.value}: a gate that was never reached cannot have "
                "found anything and cannot be waiting for anything"
            )
        for blocker in self.blockers:
            if blocker.gate is not self.gate:
                raise FingerCellGateError(
                    f"{self.gate.value}: carries a blocker raised at "
                    f"{blocker.gate.value}"
                )


# --------------------------------------------------------- what this machine has

_RUN_CACHE: dict[str, Any] = {}


def _cached(key: str, factory: Any) -> Any:
    if key not in _RUN_CACHE:
        _RUN_CACHE[key] = factory()
    return _RUN_CACHE[key]


def _acquisition() -> AcquisitionState:
    return _cached("acquisition", acquisition_state)


def package_inspection() -> Mapping[str, Any] | None:
    """The inspection record beside the unpacked archive, or ``None``.

    Guarded on the way in: the record is written on a machine that also holds
    licence material, and a machine ID must not travel from the store into a
    document some later code path publishes.
    """
    state = _acquisition()
    if not state.obtained:
        return None
    try:
        path = artifact_store_prefix_path() / PACKAGE_INSPECTION_NAME
    except Exception:  # pragma: no cover - an unusable store
        return None
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    require_no_sensitive_material(payload, where="the package inspection record")
    return payload


def qualification_record() -> Mapping[str, Any] | None:
    """The record a qualification left behind, if it answers gates.

    A record produced by the fake engine is read and then discarded here. It
    proves the harness and nothing else, and a gate that accepted it would be a
    gate that passed on this project's own test double.
    """
    from fpbench.experiments.stage13a_qualification import (
        EngineKind,
        read_record,
        record_path,
    )

    try:
        payload = read_record(record_path())
    except Exception:  # pragma: no cover - an unusable store
        return None
    if payload is None:
        return None
    if str(payload.get("engine_kind")) != EngineKind.DELIVERED_SDK.value:
        return None
    return payload


def _section(name: str) -> Mapping[str, Any] | None:
    inspection = _cached("inspection", package_inspection)
    if not inspection:
        return None
    section = inspection.get(name)
    return section if isinstance(section, Mapping) else None


def _rows(name: str) -> tuple[Mapping[str, Any], ...]:
    inspection = _cached("inspection", package_inspection)
    if not inspection:
        return ()
    rows = inspection.get(name)
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return ()
    return tuple(item for item in rows if isinstance(item, Mapping))


def unresolved_score_affecting_settings() -> tuple[str, ...]:
    """Every score-affecting setting with no upstream authority behind a value.

    The count this returns is the stage's central finding about configuration. A
    setting nobody recorded still decides the score, and "it was whatever the
    engine happened to be constructed with" is not an authority — it becomes one
    only when somebody reads it off a running engine and records it as a
    ``DELIVERED_RUNTIME_DEFAULT``.

    Never zero merely because nobody recorded an inventory: an archive that has
    not been exercised has no settings rows, and a caller reading this as
    "nothing is unresolved" would be reading an absence as an answer.
    """
    unresolved: list[str] = []
    for row in _rows("settings"):
        if not bool(row.get("can_affect_template_or_score", True)):
            continue
        try:
            provenance = frozen.SettingProvenance(str(row.get("provenance", "")))
        except ValueError:
            unresolved.append(str(row.get("name", "<unnamed>")))
            continue
        if not provenance.is_upstream_authority:
            unresolved.append(str(row.get("name", "<unnamed>")))
    return tuple(sorted(unresolved))


def _not_reached_reason(stopped_at: frozen.PreflightGate) -> str:
    """Why a gate was never asked. Only a failure produces one (docs/adr/0104)."""
    return (
        f"the run stopped at {stopped_at.value}, so this question was never "
        "asked: nothing was activated, loaded or executed for it"
    )


# ------------------------------------------------------------------- gate 1


def _gate_official_artifact_acquisition() -> GateResult:
    """G1. Is the official trial archive here, hashed, and with its documentation?

    Four things, and all four come from the delivery rather than from a page
    about it. The gate is deliberately the first action of the whole stage: this
    is the one candidate whose acquisition needs nobody's permission, and writing
    an adapter before fetching the bytes is how a stage ends up describing an API
    the archive does not contain.
    """
    from fpbench.experiments.stage13a_acquisition import ArtifactPresence

    gate = frozen.PreflightGate.OFFICIAL_ARTIFACT_ACQUISITION
    state = _acquisition()

    if state.presence is ArtifactPresence.VERIFIED and state.declaration is not None:
        declaration = state.declaration
        if not declaration.documentation_obtained:
            return GateResult(
                gate=gate,
                status=frozen.GateStatus.ACTION_REQUIRED,
                summary=(
                    "the archive is here and verified, and no delivered "
                    "documentation has been recorded beside it"
                ),
                outstanding=OutstandingAction(
                    gate=gate,
                    action=frozen.RequiredAction.ARCHIVE_NOT_ACQUIRED,
                    what_has_been_done=(
                        "the official trial archive was fetched from the vendor's "
                        "own direct locator and verified by size and digest"
                    ),
                    what_remains=(
                        "record that the delivered documentation, licence "
                        "agreement and revision stamp were obtained with it",
                    ),
                    what_it_would_answer=(
                        "whether the delivery is complete enough to settle a "
                        "settings inventory from"
                    ),
                ),
            )
        agreement = (
            "and its revision agrees with the vendor's published release notes"
            if declaration.revision_agrees_with_release_notes
            else (
                "and its revision does NOT match the published release notes, "
                "which the identity gate resolves"
            )
        )
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.PASS,
            summary=(
                f"{declaration.filename} was obtained from the vendor's own "
                "untokenized direct locator, is "
                f"{declaration.size_bytes} bytes, hashes to the pinned digest, "
                f"arrived with its delivered documentation {agreement}"
            ),
        )

    if state.presence is ArtifactPresence.ABSENT:
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.ACTION_REQUIRED,
            summary=(
                "no trial archive is in the local artifact store. Nothing has "
                "been found out about FingerCell and nothing has gone wrong: the "
                "download has not been performed on this machine"
            ),
            outstanding=OutstandingAction(
                gate=gate,
                action=frozen.RequiredAction.ARCHIVE_NOT_ACQUIRED,
                what_has_been_done=(
                    "the vendor's public download page and release notes were "
                    "read, and the official direct locator was identified as "
                    "stable and untokenized"
                ),
                what_remains=(
                    "fetch the official trial archive into the local artifact "
                    "store",
                    "record its size, digest and download date",
                    "record that the delivered documentation came with it",
                ),
                what_it_would_answer=(
                    "every later gate, all of which are questions about specific "
                    "delivered bytes"
                ),
            ),
        )

    return GateResult(
        gate=gate,
        status=frozen.GateStatus.ACTION_REQUIRED,
        summary=(
            f"the store is {state.presence.value}: {state.detail}. This is a "
            "local bookkeeping state and not a finding about FingerCell"
        ),
        outstanding=OutstandingAction(
            gate=gate,
            action=frozen.RequiredAction.ARCHIVE_NOT_ACQUIRED,
            what_has_been_done=(
                f"the store was inspected and reports {state.presence.value}"
            ),
            what_remains=(
                "re-fetch or re-declare the archive so that a declaration and the "
                "bytes beside it agree by size and digest",
            ),
            what_it_would_answer=(
                "whether the bytes this stage would qualify are the bytes the "
                "vendor published"
            ),
        ),
    )


# ------------------------------------------------------------------- gate 2


def _gate_package_runtime_identity() -> GateResult:
    """G2. Is this exactly FingerCell 3.3, and is its runtime closure pinned?

    Two questions the same document answers, plus the one that is specific to
    this candidate: whether the extractor and matcher in the route are
    FingerCell's own. Both this vendor's fingerprint products ship modules under
    the same naming convention, and a route that reached the other one would
    still produce numbers (docs/adr/0114).
    """
    gate = frozen.PreflightGate.PACKAGE_RUNTIME_IDENTITY
    state = _acquisition()
    declaration = state.declaration
    identity = _section("package_identity")
    closure = _rows("runtime_closure")
    contamination = _section("contamination")

    if declaration is not None and not declaration.is_the_expected_product:
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.FAIL,
            summary=(
                f"the delivered archive declares itself {declaration.product} "
                f"{declaration.product_version} and this candidate is "
                f"{frozen.PRODUCT_FAMILY} {frozen.DECLARED_PRODUCT_VERSION}"
            ),
            blockers=(
                Blocker(
                    gate=gate,
                    blocker_code=frozen.BlockerCode.PRODUCT_IDENTITY_MISMATCH,
                    affected_component="the delivered archive",
                    evidence=(
                        f"the declaration names {declaration.product} "
                        f"{declaration.product_version}"
                    ),
                    why_this_blocks_algorithm_5=(
                        "a different Neurotechnology product would produce "
                        "fingerprint scores under this candidate's name, and they "
                        "would be a different algorithm's scores"
                    ),
                    how_this_would_be_lifted=(
                        "obtain the FingerCell 3.3 SDK trial itself, or open a "
                        "separate preflight for whatever this archive is"
                    ),
                ),
            ),
        )

    if not identity:
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.ACTION_REQUIRED,
            summary=(
                "the archive is verified and nothing has been inventoried from "
                "it: no binding is selected and no runtime closure is pinned"
            ),
            outstanding=OutstandingAction(
                gate=gate,
                action=frozen.RequiredAction.PACKAGE_NOT_INVENTORIED,
                what_has_been_done=(
                    "the archive was unpacked and its layout, headers, delivered "
                    "samples and tutorials, licence agreement and revision stamp "
                    "were read"
                ),
                what_remains=(
                    "record the package identity as the archive reports it",
                    "select exactly one official binding against the frozen "
                    "criteria",
                    "pin the runtime closure with a role, size and digest per "
                    "component",
                    "establish positively that no sibling-product extractor or "
                    "matcher is in the route",
                ),
                what_it_would_answer=(
                    "which product, revision and modules the later gates are "
                    "asking their questions about"
                ),
            ),
        )

    if not closure:
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.ACTION_REQUIRED,
            summary="a package identity is recorded and no runtime closure is",
            outstanding=OutstandingAction(
                gate=gate,
                action=frozen.RequiredAction.BINDING_NOT_SELECTED,
                what_has_been_done="the package identity was recorded",
                what_remains=(
                    "pin every component the selected binding actually loads",
                ),
                what_it_would_answer=(
                    "what would have to be reproduced to reproduce a score"
                ),
            ),
        )

    binding = str(identity.get("selected_binding", "")).strip()
    if not binding or binding == frozen.Binding.UNRESOLVED.value:
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.ACTION_REQUIRED,
            summary="no single official binding has been selected",
            outstanding=OutstandingAction(
                gate=gate,
                action=frozen.RequiredAction.BINDING_NOT_SELECTED,
                what_has_been_done="the archive was inventoried",
                what_remains=("select exactly one binding and record why",),
                what_it_would_answer="which API the qualification bridge targets",
            ),
        )

    bridge_source = str(identity.get("bridge_source_fingerprint", "")).strip()
    bridge_binary = str(identity.get("bridge_binary_sha256", "")).strip()
    if (
        not bool(identity.get("bridge_compiled"))
        or len(bridge_source) != 64
        or len(bridge_binary) != 64
    ):
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.ACTION_REQUIRED,
            summary=(
                f"the {binding} binding is selected and no identified qualification "
                "bridge has been built against it. A bridge that was compiled but "
                "not pinned would let one build's twenty comparisons answer for "
                "every later build"
            ),
            outstanding=OutstandingAction(
                gate=gate,
                action=frozen.RequiredAction.BRIDGE_NOT_COMPILED,
                what_has_been_done=(
                    "the archive is verified, inventoried, and one official "
                    f"binding ({binding}) has been selected from what it ships"
                ),
                what_remains=(
                    "write the small qualification bridge against that binding",
                    "compile and link it against the delivered headers and "
                    "libraries",
                    "record its source fingerprint and the digest of the built "
                    "binary, so that a run can be bound to the exact build that "
                    "produced it",
                ),
                what_it_would_answer=(
                    "whether the route compiles at all — which is worth knowing "
                    "before a 30-day clock starts, not after (docs/adr/0115)"
                ),
            ),
        )

    observed = _rows("observed_runtime_closure")
    if not observed:
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.ACTION_REQUIRED,
            summary=(
                "the declared link closure is settled and no process has been "
                "observed loading anything. A library may load a further "
                "component during construction or extraction without appearing "
                "in any link closure, so what is declared cannot rule one out"
            ),
            outstanding=OutstandingAction(
                gate=gate,
                action=frozen.RequiredAction.RUNTIME_CLOSURE_NOT_OBSERVED,
                what_has_been_done=(
                    "the vendor's own build files name the four libraries the "
                    "official 1:1 route links, and the built bridge records the "
                    "same four as its dependencies; neither names the general "
                    "biometrics module that carries the sibling engine"
                ),
                what_remains=(
                    "run the bridge once and record which shared objects the "
                    f"process actually mapped, via {frozen.RUNTIME_CLOSURE_OBSERVATION_METHOD}",
                    "confirm that no sibling extractor or matcher is among them",
                ),
                what_it_would_answer=(
                    "whether the route that produces a score is FingerCell's own "
                    "all the way down, rather than only at link time"
                ),
            ),
        )

    if contamination and bool(contamination.get("sibling_algorithm_in_route")):
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.FAIL,
            summary=(
                "a sibling-product extractor or matcher was observed in the "
                "route"
            ),
            blockers=(
                Blocker(
                    gate=gate,
                    blocker_code=(
                        frozen.BlockerCode.VERIFINGER_COMPONENT_IN_THE_ROUTE
                    ),
                    affected_component="the extraction and matching route",
                    evidence=str(
                        contamination.get("evidence", "recorded by the inspection")
                    ),
                    why_this_blocks_algorithm_5=(
                        "the numbers would be Algorithm 4's, published under "
                        "Algorithm 5's name, and nothing downstream could tell"
                    ),
                    how_this_would_be_lifted=(
                        "route extraction and matching through the FingerCell "
                        "module itself, using common runtime components only for "
                        "image handling and licensing"
                    ),
                ),
            ),
        )

    missing_roles = {
        frozen.ComponentRole.FINGERCELL_ALGORITHM.value
    } - {str(row.get("component_role")) for row in closure}
    if missing_roles:
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.FAIL,
            summary=(
                "the runtime closure pins no FingerCell algorithm module, so "
                "nothing in it is the thing under test"
            ),
            blockers=(
                Blocker(
                    gate=gate,
                    blocker_code=frozen.BlockerCode.RUNTIME_CLOSURE_UNRESOLVED,
                    affected_component="the runtime closure",
                    evidence=f"no component carries the role {sorted(missing_roles)}",
                    why_this_blocks_algorithm_5=(
                        "a closure without the algorithm in it cannot say what "
                        "produced a score"
                    ),
                    how_this_would_be_lifted=(
                        "record the FingerCell module with its role, size and "
                        "digest"
                    ),
                ),
            ),
        )

    return GateResult(
        gate=gate,
        status=frozen.GateStatus.PASS,
        summary=(
            f"the archive is {frozen.PRODUCT_FAMILY} "
            f"{frozen.DECLARED_PRODUCT_VERSION} revision "
            f"{identity.get('product_revision')} on "
            f"{identity.get('platform')}/{identity.get('architecture')}, the "
            f"{binding} binding is selected, a qualification bridge is built and "
            f"pinned by source and binary digest, {len(closure)} runtime "
            "components are pinned by digest, and the extractor and matcher in "
            "the route are FingerCell's own"
        ),
    )


# ------------------------------------------------------------------- gate 3


def _gate_research_use_and_trial_operation() -> GateResult:
    """G3. Do the delivered terms permit this, and does the trial actually run?

    Five separate questions that are routinely collapsed into one, and the
    same-vendor isolation question this candidate adds: a Neurotechnology
    licensing service is already running on this host for Algorithm 4, and it
    proves nothing whatever about a FingerCell entitlement.
    """
    gate = frozen.PreflightGate.RESEARCH_USE_AND_TRIAL_OPERATION
    inspection = _cached("inspection", package_inspection)
    trial = _section("trial")
    assessment, refusal = _assessment_or_refusal(inspection)

    if refusal is not None:
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.FAIL,
            summary=refusal,
            blockers=(
                Blocker(
                    gate=gate,
                    blocker_code=frozen.BlockerCode.RESEARCH_USE_BLOCKED,
                    affected_component="the delivered licence agreement",
                    evidence=refusal,
                    why_this_blocks_algorithm_5=(
                        "Stage 8E is the only authority on whether this project "
                        "may execute a third-party component, and it declined to "
                        "decide on the facts recorded"
                    ),
                    how_this_would_be_lifted=(
                        "record the delivered notices completely enough for the "
                        "policy to reach a conservative answer"
                    ),
                ),
            ),
        )

    # The delivered route was walked to its end and returned no entitlement.
    # This is a FAIL rather than an outstanding action precisely because there is
    # nothing left to perform: every documented step for this platform succeeded,
    # and the licensing service answered that it has nothing for this component
    # (docs/adr/0124).
    if trial is not None and str(trial.get("route_exhausted", "")).lower() == "true":
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.FAIL,
            summary=(
                "the delivered trial route was walked to its end in this "
                "environment and produced no FingerCell entitlement: the "
                "licensing service runs and answers, the client half of the "
                "trial switch is on, and the subsystem reports the licence as "
                "not obtained rather than the service as unreachable"
            ),
            blockers=(
                Blocker(
                    gate=gate,
                    blocker_code=(
                        frozen.BlockerCode
                        .FINGERCELL_TRIAL_ENTITLEMENT_UNAVAILABLE_IN_QUALIFIED_ENVIRONMENT
                    ),
                    affected_component="the FingerCell trial entitlement",
                    evidence=str(
                        trial.get("detail", "no entitlement was issued")
                    ),
                    why_this_blocks_algorithm_5=(
                        "without an entitlement for the FingerCell component "
                        "nothing can be extracted or matched, so no gate below "
                        "this one can be answered about the delivered runtime at "
                        "all. The archive, its identity, the binding and the "
                        "compiled bridge are all in hand and none of them can be "
                        "exercised"
                    ),
                    how_this_would_be_lifted=(
                        "by an entitlement issued for this component through the "
                        "vendor's own route — which may mean a trial provisioning "
                        "step this project has not been able to reach, or a "
                        "licence obtained under different arrangements. It is not "
                        "lifted by a serial-number workaround, by substituting a "
                        "commercial licence, or by any reset or bypass"
                    ),
                ),
            ),
        )

    if assessment is None or trial is None:
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.ACTION_REQUIRED,
            summary=(
                "the delivered licence agreement has been read and no trial has "
                "been activated on this machine, so nothing has requested a "
                "FingerCell entitlement"
            ),
            outstanding=OutstandingAction(
                gate=gate,
                action=frozen.RequiredAction.TRIAL_NOT_ACTIVATED,
                what_has_been_done=(
                    "the delivered licence agreement and activation guide were "
                    "read: the grant covers designing, developing and testing, "
                    "the trial period is 30 days, activation is an explicit act, "
                    "and no restriction on publishing measurements was found. "
                    "The delivered licensing service was then started by the "
                    "documented route for this platform, from the delivered "
                    "activation directory and with the delivered configuration "
                    "unchanged; it starts, reports the same revision as the "
                    "archive, and the host reaches the vendor over the network. "
                    "A licence request for the FingerCell component through the "
                    "official route did not yield an entitlement, and the service "
                    "recorded no request"
                ),
                what_remains=(
                    "resolve how trial entitlements are provisioned for this "
                    "platform at all: the delivered Linux activation utility "
                    "reports that every one of its activation paths takes a "
                    "serial number, and a trial ships none",
                    "obtain a licence for the FingerCell component specifically, "
                    "and record that it was FingerCell's own entitlement",
                    "record the trial start semantics, duration and network "
                    "requirement as the delivered material states them",
                ),
                what_it_would_answer=(
                    "whether the route can be executed at all, and for how long"
                ),
            ),
        )

    if not assessment.may_execute_locally:
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.FAIL,
            summary="Stage 8E does not permit local research execution",
            blockers=(
                Blocker(
                    gate=gate,
                    blocker_code=frozen.BlockerCode.RESEARCH_USE_BLOCKED,
                    affected_component="the delivered licence agreement",
                    evidence=str(assessment.basis),
                    why_this_blocks_algorithm_5=(
                        "an algorithm this project may not execute cannot be "
                        "benchmarked by it"
                    ),
                    how_this_would_be_lifted=(
                        "only by terms that permit local, non-commercial research "
                        "execution"
                    ),
                ),
            ),
        )

    if not bool(trial.get("activated")):
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.FAIL,
            summary="the trial was activated and did not yield a usable licence",
            blockers=(
                Blocker(
                    gate=gate,
                    blocker_code=frozen.BlockerCode.TRIAL_ACTIVATION_FAILED,
                    affected_component="the FingerCell trial entitlement",
                    evidence=str(trial.get("detail", "activation did not succeed")),
                    why_this_blocks_algorithm_5=(
                        "without an entitlement for the FingerCell component "
                        "itself nothing can be extracted or matched"
                    ),
                    how_this_would_be_lifted=(
                        "a successful activation through the vendor's own route; "
                        "never by resetting, bypassing or reusing another "
                        "product's licence"
                    ),
                ),
            ),
        )

    if str(trial.get("entitlement_component", "")).strip() != frozen.PRODUCT_FAMILY:
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.FAIL,
            summary=(
                "the entitlement obtained is not FingerCell's own, and a running "
                "licensing service for another product of this vendor is not "
                "evidence about this one"
            ),
            blockers=(
                Blocker(
                    gate=gate,
                    blocker_code=frozen.BlockerCode.TRIAL_ACTIVATION_FAILED,
                    affected_component="the licence entitlement",
                    evidence=(
                        "entitlement_component is "
                        f"{trial.get('entitlement_component')!r}"
                    ),
                    why_this_blocks_algorithm_5=(
                        "Algorithm 4 already runs on this host under this "
                        "vendor's licensing service, so an unqualified 'licence "
                        "obtained' says nothing about FingerCell"
                    ),
                    how_this_would_be_lifted=(
                        "obtain and record the FingerCell component entitlement "
                        "specifically"
                    ),
                ),
            ),
        )

    semantics = str(trial.get("start_semantics", ""))
    return GateResult(
        gate=gate,
        status=frozen.GateStatus.PASS,
        summary=(
            "the delivered terms permit local research execution, the FingerCell "
            "component's own trial entitlement was obtained, and the clock "
            f"semantics are recorded as {semantics or 'UNRESOLVED'}"
        ),
    )


# ------------------------------------------------------------------- gate 4


def _gate_canonical500_input_route() -> GateResult:
    """G4. Does canonical_500 reach the extractor unmodified, at a true 500 PPI?"""
    gate = frozen.PreflightGate.CANONICAL500_INPUT_ROUTE
    route = _section("input_route")

    if route is None:
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.ACTION_REQUIRED,
            summary=(
                "no runtime has been exercised, so nothing is known about how "
                "the delivered image loader treats a canonical_500 PNG"
            ),
            outstanding=OutstandingAction(
                gate=gate,
                action=frozen.RequiredAction.RUNTIME_NOT_EXERCISED,
                what_has_been_done=(
                    "the delivered extraction tutorial was read and shows the "
                    "official route loading an image and passing it straight to "
                    "the extractor, with no preprocessing outside the SDK"
                ),
                what_remains=(
                    "load a canonical_500 PNG through the delivered image loader",
                    "observe whether the resolution survives the load",
                    "if it does not, prove the decode route pixel-for-pixel",
                    "confirm the effective resolution at the point of extraction",
                ),
                what_it_would_answer=(
                    "whether the benchmark's own images can enter the algorithm "
                    "without fpbench choosing a preprocessing step"
                ),
            ),
        )

    if bool(route.get("fpbench_preprocessing_required")):
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.FAIL,
            summary="the route cannot be walked without fpbench modifying pixels",
            blockers=(
                Blocker(
                    gate=gate,
                    blocker_code=frozen.BlockerCode.FPBENCH_PREPROCESSING_REQUIRED,
                    affected_component="the canonical_500 input route",
                    evidence=str(route.get("detail", "recorded by the inspection")),
                    why_this_blocks_algorithm_5=(
                        "a benchmark that preprocessed its inputs would be "
                        "reporting on fpbench's image processing rather than on "
                        "the algorithm"
                    ),
                    how_this_would_be_lifted=(
                        "an upstream route that accepts the canonical image as it "
                        "is, or a decode that provably preserves every pixel"
                    ),
                ),
            ),
        )

    if int(route.get("effective_ppi", 0)) != frozen.REQUIRED_INPUT_PPI:
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.FAIL,
            summary=(
                f"the effective resolution at extraction is "
                f"{route.get('effective_ppi')!r} and not "
                f"{frozen.REQUIRED_INPUT_PPI}"
            ),
            blockers=(
                Blocker(
                    gate=gate,
                    blocker_code=frozen.BlockerCode.CANONICAL500_ROUTE_UNRESOLVED,
                    affected_component="the image resolution semantics",
                    evidence=f"effective_ppi is {route.get('effective_ppi')!r}",
                    why_this_blocks_algorithm_5=(
                        "the extractor reads the image's resolution, so a wrong "
                        "one silently changes what is extracted"
                    ),
                    how_this_would_be_lifted=(
                        "set the resolution on the image object before extraction "
                        "— never after it, and never by rescaling pixels"
                    ),
                ),
            ),
        )

    return GateResult(
        gate=gate,
        status=frozen.GateStatus.PASS,
        summary=(
            "canonical_500 reaches the extractor with every pixel unchanged and "
            f"an effective {frozen.REQUIRED_INPUT_PPI} PPI, by the "
            f"{route.get('route_kind', 'recorded')} route"
        ),
    )


# ------------------------------------------------------------------- gate 5


def _gate_single_finger_extraction_profile() -> GateResult:
    """G5. One image, one fresh extraction, one proprietary template. No merging."""
    gate = frozen.PreflightGate.SINGLE_FINGER_EXTRACTION_PROFILE
    profile = _section("extraction")
    settings = _rows("settings")

    if profile is None or not settings:
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.ACTION_REQUIRED,
            summary=(
                "no settings have been read off a constructed engine, so the "
                "extraction profile is not established"
            ),
            outstanding=OutstandingAction(
                gate=gate,
                action=frozen.RequiredAction.SETTINGS_NOT_ENUMERATED,
                what_has_been_done=(
                    "the delivered binding was read: it exposes typed accessors "
                    "for the quality threshold, the matching algorithm and the "
                    "template format, and the module carries further property "
                    "names the typed surface does not reach"
                ),
                what_remains=(
                    "construct the engine and enumerate its properties through "
                    "the supported property mechanism before setting anything",
                    "record each setting's runtime value, documented default and "
                    "provenance",
                    "confirm the delivered default template format",
                ),
                what_it_would_answer=(
                    "what the algorithm was actually configured with when it "
                    "produced a template"
                ),
            ),
        )

    if bool(profile.get("merging_used")) or bool(profile.get("template_cache_used")):
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.FAIL,
            summary=(
                "the extraction route consolidates or reuses templates, which is "
                "a different quantity from a single-impression similarity"
            ),
            blockers=(
                Blocker(
                    gate=gate,
                    blocker_code=frozen.BlockerCode.EXTRACTION_ROUTE_UNRESOLVED,
                    affected_component="the extraction route",
                    evidence=(
                        f"merging_used={profile.get('merging_used')!r}, "
                        f"template_cache_used={profile.get('template_cache_used')!r}"
                    ),
                    why_this_blocks_algorithm_5=(
                        "a merged or cached template cannot be recovered into a "
                        "one-image-one-template comparison"
                    ),
                    how_this_would_be_lifted=(
                        "extract each side of every comparison freshly, from one "
                        "image, with no merging"
                    ),
                ),
            ),
        )

    fmt = str(profile.get("template_format", ""))
    if fmt != frozen.REQUIRED_TEMPLATE_FORMAT.value:
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.FAIL,
            summary=(
                f"the compared representation is {fmt!r} and this stage compares "
                f"{frozen.REQUIRED_TEMPLATE_FORMAT.value}"
            ),
            blockers=(
                Blocker(
                    gate=gate,
                    blocker_code=frozen.BlockerCode.EXTRACTION_PROFILE_UNRESOLVED,
                    affected_component="the template format",
                    evidence=f"template_format is {fmt!r}",
                    why_this_blocks_algorithm_5=(
                        "an ISO or MOC export is a different matching scenario "
                        "with its own accuracy"
                    ),
                    how_this_would_be_lifted=(
                        "use the delivered default proprietary format"
                    ),
                ),
            ),
        )

    return GateResult(
        gate=gate,
        status=frozen.GateStatus.PASS,
        summary=(
            "one image produces one fresh proprietary template through one "
            f"extraction call, with no merging and no cache, under {len(settings)} "
            "recorded settings"
        ),
    )


# ------------------------------------------------------------------- gate 6


def _gate_raw_1to1_score_contract() -> GateResult:
    """G6. Is a native raw integer score readable without any decision?"""
    gate = frozen.PreflightGate.RAW_1TO1_SCORE_CONTRACT
    contract = _section("score_contract")

    if contract is None:
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.ACTION_REQUIRED,
            summary=(
                "the matcher has not been called, so its contract has not been "
                "observed on this machine"
            ),
            outstanding=OutstandingAction(
                gate=gate,
                action=frozen.RequiredAction.SCORE_CONTRACT_NOT_OBSERVED,
                what_has_been_done=(
                    "the delivered header and binding were read: the matcher takes "
                    "a reference record and a candidate record and writes a native "
                    "signed integer through an out-parameter, a bigger score means "
                    "more similar, and the official tutorial prints it with no "
                    "threshold anywhere near it"
                ),
                what_remains=(
                    "call the matcher through the compiled bridge",
                    "record the observed native type and direction",
                    "record that the score is readable with no decision, and that "
                    "upstream defines no range rather than inventing one",
                ),
                what_it_would_answer=(
                    "whether the archive keeps the contract its own documentation "
                    "states — which is the whole reason this candidate was chosen"
                ),
            ),
        )

    try:
        status = frozen.ScoreRouteStatus(str(contract.get("route_status", "")))
    except ValueError:
        status = frozen.ScoreRouteStatus.UNRESOLVED
    if not status.is_raw_score:
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.FAIL,
            summary=f"the matcher route is {status.value} and not a raw scalar",
            blockers=(
                Blocker(
                    gate=gate,
                    blocker_code=frozen.BlockerCode.RAW_SCORE_ROUTE_UNRESOLVED,
                    affected_component="the matcher",
                    evidence=f"route_status is {status.value}",
                    why_this_blocks_algorithm_5=(
                        "a decision is somebody's threshold, and this benchmark's "
                        "operating point belongs to a later shared calibration"
                    ),
                    how_this_would_be_lifted=(
                        "read the scalar the matcher returns, without lowering or "
                        "zeroing any threshold to make it appear"
                    ),
                ),
            ),
        )

    if str(contract.get("direction", "")) != frozen.SCORE_DIRECTION:
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.FAIL,
            summary=(
                f"the score direction is {contract.get('direction')!r} and the "
                f"delivered binding documents {frozen.SCORE_DIRECTION}"
            ),
            blockers=(
                Blocker(
                    gate=gate,
                    blocker_code=frozen.BlockerCode.MATCHER_PROFILE_UNRESOLVED,
                    affected_component="the matcher",
                    evidence=f"direction is {contract.get('direction')!r}",
                    why_this_blocks_algorithm_5=(
                        "a reversed direction would invert every comparison "
                        "downstream"
                    ),
                    how_this_would_be_lifted=(
                        "record the direction the delivered binding documents"
                    ),
                ),
            ),
        )

    if bool(contract.get("threshold_applied_inside_the_score")):
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.FAIL,
            summary="the score is only exposed relative to a threshold",
            blockers=(
                Blocker(
                    gate=gate,
                    blocker_code=frozen.BlockerCode.RAW_SCORE_ROUTE_UNRESOLVED,
                    affected_component="the matcher",
                    evidence="threshold_applied_inside_the_score is true",
                    why_this_blocks_algorithm_5=(
                        "a thresholded score is a decision wearing a number's "
                        "clothes"
                    ),
                    how_this_would_be_lifted=(
                        "obtain the score independently of any decision"
                    ),
                ),
            ),
        )

    return GateResult(
        gate=gate,
        status=frozen.GateStatus.PASS,
        summary=(
            f"the matcher returns a native {contract.get('native_type')} through "
            f"{contract.get('api')}, higher meaning more similar, readable with no "
            f"decision and with {frozen.FPBENCH_SCORE_TRANSFORMATION} applied by "
            "fpbench"
        ),
    )


# ------------------------------------------------------------------- gate 7


def _gate_score_affecting_settings_closure() -> GateResult:
    """G7. Does every score-affecting setting carry an upstream authority?"""
    gate = frozen.PreflightGate.SCORE_AFFECTING_SETTINGS_CLOSURE
    settings = _rows("settings")
    unresolved = unresolved_score_affecting_settings()

    if not settings:
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.ACTION_REQUIRED,
            summary=(
                "no settings inventory exists, so there is nothing to close over. "
                "A count of zero here would read as a closed inventory rather than "
                "as an absent one"
            ),
            outstanding=OutstandingAction(
                gate=gate,
                action=frozen.RequiredAction.SETTINGS_CLOSURE_NOT_ESTABLISHED,
                what_has_been_done=(
                    "the delivered binding's typed property surface was read, and "
                    "the algorithm module was found to carry further property "
                    "names that surface never reaches - so the closure is already "
                    "known to be wider than any list written in advance"
                ),
                what_remains=(
                    "enumerate the constructed engine's properties through the "
                    "supported property mechanism, before setting anything",
                    "give every score-affecting setting an upstream provenance",
                    "confirm the matching algorithm is at its delivered default "
                    "rather than forcing it there",
                ),
                what_it_would_answer=(
                    "what the algorithm was actually configured with when it "
                    "produced a score, which is what makes a run reproducible"
                ),
            ),
        )

    if unresolved:
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.FAIL,
            summary=(
                f"{len(unresolved)} score-affecting setting(s) have no upstream "
                f"authority behind their value: {list(unresolved)}"
            ),
            blockers=(
                Blocker(
                    gate=gate,
                    blocker_code=frozen.BlockerCode.HIDDEN_SCORE_AFFECTING_SETTING,
                    affected_component="the settings profile",
                    evidence=f"unresolved: {list(unresolved)}",
                    why_this_blocks_algorithm_5=(
                        "a value nobody recorded still decides the score, and a "
                        "benchmark that could not say what it ran under could not "
                        "be reproduced"
                    ),
                    how_this_would_be_lifted=(
                        "read each value off the constructed engine and record it "
                        "as a delivered runtime default, or find the upstream "
                        "statement that settles it"
                    ),
                ),
            ),
        )

    matching = next(
        (row for row in settings if str(row.get("name")) == "MatchingAlgorithm"),
        None,
    )
    if matching is not None:
        effective = matching.get("effective_value")
        if int(effective if effective is not None else -1) != (
            frozen.MATCHING_ALGORITHM_EXPECTED_VALUE
        ):
            return GateResult(
                gate=gate,
                status=frozen.GateStatus.FAIL,
                summary=(
                    f"MatchingAlgorithm is {effective!r} and the delivered "
                    "documentation gives "
                    f"{frozen.MATCHING_ALGORITHM_EXPECTED_VALUE} as the default"
                ),
                blockers=(
                    Blocker(
                        gate=gate,
                        blocker_code=(
                            frozen.BlockerCode.HIDDEN_SCORE_AFFECTING_SETTING
                        ),
                        affected_component="MatchingAlgorithm",
                        evidence=f"effective_value is {effective!r}",
                        why_this_blocks_algorithm_5=(
                            "the matching algorithm version selects a different "
                            "matcher, and a delivered runtime disagreeing with "
                            "its own documentation is a finding about the "
                            "artifact rather than something to correct silently"
                        ),
                        how_this_would_be_lifted=(
                            "establish why the delivered default differs, and "
                            "resolve it against a version-matched authority — "
                            "never by forcing the documented value quietly"
                        ),
                    ),
                ),
            )

    return GateResult(
        gate=gate,
        status=frozen.GateStatus.PASS,
        summary=(
            f"all {len(settings)} recorded settings that can affect a template or "
            "a score carry an upstream authority, and MatchingAlgorithm is at its "
            "delivered default"
        ),
    )


# ------------------------------------------------------------------- gate 8


def _gate_pair_self_determinism_failures() -> GateResult:
    """G8. Did a bounded run demonstrate orientation, SELF, determinism, failures?"""
    gate = frozen.PreflightGate.PAIR_SELF_DETERMINISM_FAILURES
    record = _cached("qualification", qualification_record)

    if record is None:
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.ACTION_REQUIRED,
            summary=(
                "no qualification record produced by the delivered SDK exists on "
                "this machine"
            ),
            outstanding=OutstandingAction(
                gate=gate,
                action=frozen.RequiredAction.QUALIFICATION_NOT_RUN,
                what_has_been_done=(
                    "the harness was written and driven end to end against a fake "
                    "engine: six passes, both orientations, SELF from two "
                    "extractions, a real process restart and all four mandatory "
                    "failure probes"
                ),
                what_remains=(
                    "run the same harness against the delivered SDK, within the "
                    "twenty-comparison ceiling",
                ),
                what_it_would_answer=(
                    "whether the delivered matcher is deterministic and how it "
                    "actually fails"
                ),
            ),
        )

    from fpbench.experiments.stage13a_qualification import QualificationOutcome

    if str(record.get("status")) != QualificationOutcome.SUCCESS.value:
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.FAIL,
            summary=(
                "a qualification run against the delivered SDK started and did "
                f"not finish: {record.get('failure_detail')}"
            ),
            blockers=(
                Blocker(
                    gate=gate,
                    blocker_code=frozen.BlockerCode.LOCAL_SMOKE_FAILED,
                    affected_component="the delivered route",
                    evidence=(
                        f"failed at {record.get('failed_at')}: "
                        f"{record.get('failure_detail')}"
                    ),
                    why_this_blocks_algorithm_5=(
                        "a route that breaks on twenty comparisons will not "
                        "survive six thousand"
                    ),
                    how_this_would_be_lifted=(
                        "a completed run whose record carries every pass"
                    ),
                ),
            ),
        )

    determinism = record.get("determinism")
    determinism = determinism if isinstance(determinism, Mapping) else {}
    failed_levels = [
        level for level in frozen.DETERMINISM_LEVELS if not determinism.get(level)
    ]
    if failed_levels:
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.FAIL,
            summary=f"the same comparison did not reproduce at {failed_levels}",
            blockers=(
                Blocker(
                    gate=gate,
                    blocker_code=frozen.BlockerCode.SCORE_NONDETERMINISM_OBSERVED,
                    affected_component="the matcher",
                    evidence=f"determinism failed at {failed_levels}",
                    why_this_blocks_algorithm_5=(
                        "a benchmark whose numbers change between runs is not a "
                        "benchmark"
                    ),
                    how_this_would_be_lifted=(
                        "a documented deterministic mode, or an explanation of "
                        "the variation that a protocol can accommodate"
                    ),
                ),
            ),
        )

    probes = record.get("failure_probes")
    probes = probes if isinstance(probes, Sequence) else ()
    correct = {
        str(item.get("cause"))
        for item in probes
        if isinstance(item, Mapping) and item.get("behaved_correctly")
    }
    required = {name for name, _ in frozen.MANDATORY_FAILURE_PROBES}
    absent = sorted(required - correct)
    if absent:
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.FAIL,
            summary=(
                f"{len(absent)} of the {frozen.MANDATORY_FAILURE_PROBE_COUNT} "
                f"mandatory failure probes did not behave correctly: {absent}"
            ),
            blockers=(
                Blocker(
                    gate=gate,
                    blocker_code=frozen.BlockerCode.LOCAL_SMOKE_FAILED,
                    affected_component="the route's failure semantics",
                    evidence=f"probes not satisfied: {absent}",
                    why_this_blocks_algorithm_5=(
                        "a failure that arrived as a number would enter the "
                        "benchmark as a very poor match, and no metric could tell "
                        "it apart from one"
                    ),
                    how_this_would_be_lifted=(
                        "a route that reports every one of these as an exception, "
                        "a status or an error code"
                    ),
                ),
            ),
        )

    orientation = record.get("pair_orientation")
    orientation = orientation if isinstance(orientation, Mapping) else {}
    if orientation.get("reduction_applied"):
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.FAIL,
            summary="the run reduced the two orientations into one number",
            blockers=(
                Blocker(
                    gate=gate,
                    blocker_code=frozen.BlockerCode.LOCAL_SMOKE_FAILED,
                    affected_component="the pair orientation binding",
                    evidence=f"reduction_applied is {orientation.get('reduction_applied')!r}",
                    why_this_blocks_algorithm_5=(
                        "reducing the orientations hides an asymmetry, and "
                        "choosing the higher one is a per-pair decision taken on "
                        "the strength of the scores themselves"
                    ),
                    how_this_would_be_lifted=(
                        "apply the frozen binding to every pair and publish the "
                        "asymmetry as a finding"
                    ),
                ),
            ),
        )

    agree = orientation.get("score_digests_equal")
    return GateResult(
        gate=gate,
        status=frozen.GateStatus.PASS,
        summary=(
            f"{record.get('scoring_comparisons')} comparisons reproduced exactly "
            "at all three levels, SELF came from two independent extractions, all "
            f"{frozen.MANDATORY_FAILURE_PROBE_COUNT} mandatory failure probes "
            "behaved correctly, and the two orientations "
            + ("agreed" if agree else "differed, which is published and not reduced")
        ),
    )


# ------------------------------------------------------------------- gate 9


def _gate_full_workload_feasibility() -> GateResult:
    """G9. Does the trial cover 6,000 comparisons and 12,000 extractions?"""
    gate = frozen.PreflightGate.FULL_WORKLOAD_FEASIBILITY
    workload = _section("workload")

    if workload is None:
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.ACTION_REQUIRED,
            summary=(
                "trial capacity and runtime cost have not been measured on this "
                "machine"
            ),
            outstanding=OutstandingAction(
                gate=gate,
                action=frozen.RequiredAction.WORKLOAD_NOT_MEASURED,
                what_has_been_done=(
                    "the delivered activation guide was read: 30 days, an "
                    "explicit activation, and a constant network requirement for "
                    "trial products"
                ),
                what_remains=(
                    "read the issued trial's expiration, entitlement and any "
                    "transaction quota off the runtime",
                    "record the quota metering semantics",
                    "measure startup, two extractions and one match, and project "
                    f"{frozen.FROZEN_WORKLOAD.total_logical_operations} logical "
                    "operations against the remaining window",
                ),
                what_it_would_answer=(
                    "whether the full benchmark fits inside the trial at all"
                ),
            ),
        )

    try:
        schema = frozen.QuotaSchema(str(workload.get("quota_schema", "")))
    except ValueError:
        schema = frozen.QuotaSchema.UNRESOLVED
    if schema is frozen.QuotaSchema.UNRESOLVED:
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.FAIL,
            summary=(
                "the trial's metering is unresolved and could stop the frozen "
                "workload part-way"
            ),
            blockers=(
                Blocker(
                    gate=gate,
                    blocker_code=frozen.BlockerCode.TRIAL_WORKLOAD_INSUFFICIENT,
                    affected_component="the trial entitlement",
                    evidence="quota_schema is UNRESOLVED",
                    why_this_blocks_algorithm_5=(
                        "a quota nobody looked for is the quota that stops the "
                        "run at comparison four thousand; the absence of a "
                        "documented limit is not evidence that none is metered"
                    ),
                    how_this_would_be_lifted=(
                        "read the issued licence's metering, or establish from "
                        "the runtime that none applies"
                    ),
                ),
            ),
        )
    if not bool(workload.get("sufficient")):
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.FAIL,
            summary="the trial does not cover the frozen workload",
            blockers=(
                Blocker(
                    gate=gate,
                    blocker_code=frozen.BlockerCode.TRIAL_WORKLOAD_INSUFFICIENT,
                    affected_component="the trial entitlement",
                    evidence=str(workload.get("detail", "capacity is short")),
                    why_this_blocks_algorithm_5=(
                        "a partial benchmark run is not a benchmark run"
                    ),
                    how_this_would_be_lifted=(
                        "a licence whose window and metering cover "
                        f"{frozen.FROZEN_WORKLOAD.total_logical_operations} "
                        "logical operations"
                    ),
                ),
            ),
        )

    return GateResult(
        gate=gate,
        status=frozen.GateStatus.PASS,
        summary=(
            f"the trial meters {schema.value} and covers "
            f"{frozen.FROZEN_WORKLOAD.comparison_attempts} comparisons and "
            f"{frozen.FROZEN_WORKLOAD.independent_extractions} independent "
            "extractions inside the remaining window"
        ),
    )


# ------------------------------------------------------------------ gate 10


def _gate_training_provenance() -> GateResult:
    """G10. Was the algorithm built on the benchmark's own evaluation data?"""
    gate = frozen.PreflightGate.TRAINING_PROVENANCE
    provenance = _section("training_provenance")

    if provenance is None:
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.ACTION_REQUIRED,
            summary=(
                "nobody has searched the delivered material and the vendor's "
                "public statements for a training-set overlap"
            ),
            outstanding=OutstandingAction(
                gate=gate,
                action=frozen.RequiredAction.PROVENANCE_NOT_SEARCHED,
                what_has_been_done=(
                    "the standard is fixed: the same one Algorithm 4 was held to"
                ),
                what_remains=(
                    "search the delivered documentation and the vendor's public "
                    f"material for {list(frozen.SD300_SEARCH_TERMS)}",
                    "cover every surface that leaks an evaluation set into a "
                    f"model: {list(frozen.SD300_OVERLAP_SURFACES)}",
                ),
                what_it_would_answer=(
                    "whether this candidate was tuned on the answer sheet. Not "
                    "searching is an outstanding action and never evidence of "
                    "overlap"
                ),
            ),
        )

    try:
        overlap = frozen.SD300OverlapStatus(str(provenance.get("overlap_status", "")))
    except ValueError:
        overlap = frozen.SD300OverlapStatus.NOT_SEARCHED

    if overlap is frozen.SD300OverlapStatus.NOT_SEARCHED:
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.ACTION_REQUIRED,
            summary="a provenance section exists and records that nobody searched",
            outstanding=OutstandingAction(
                gate=gate,
                action=frozen.RequiredAction.PROVENANCE_NOT_SEARCHED,
                what_has_been_done="a provenance section was opened",
                what_remains=("perform the search and record what it found",),
                what_it_would_answer="whether any overlap evidence exists",
            ),
        )

    if overlap is frozen.SD300OverlapStatus.OVERLAP_FOUND:
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.FAIL,
            summary="positive evidence of an overlap with the evaluation set",
            blockers=(
                Blocker(
                    gate=gate,
                    blocker_code=frozen.BlockerCode.SD300_OVERLAP_FOUND,
                    affected_component="the algorithm's training provenance",
                    evidence=str(provenance.get("detail", "recorded by the search")),
                    why_this_blocks_algorithm_5=(
                        "a candidate built on this benchmark's evaluation data "
                        "would be scored on its own training set"
                    ),
                    how_this_would_be_lifted=(
                        "it would not be; a different candidate would be needed"
                    ),
                ),
            ),
        )

    return GateResult(
        gate=gate,
        status=frozen.GateStatus.PASS,
        summary=(
            f"the search covered {list(frozen.SD300_SEARCH_TERMS)} across "
            f"{len(frozen.SD300_OVERLAP_SURFACES)} surfaces and concluded "
            f"{overlap.value}; training provenance stays "
            f"{frozen.TrainingProvenanceStatus.PROPRIETARY_UNDISCLOSED.value}"
        ),
    )


_GATE_RUNNERS = {
    frozen.PreflightGate.OFFICIAL_ARTIFACT_ACQUISITION: (
        _gate_official_artifact_acquisition
    ),
    frozen.PreflightGate.PACKAGE_RUNTIME_IDENTITY: _gate_package_runtime_identity,
    frozen.PreflightGate.RESEARCH_USE_AND_TRIAL_OPERATION: (
        _gate_research_use_and_trial_operation
    ),
    frozen.PreflightGate.CANONICAL500_INPUT_ROUTE: _gate_canonical500_input_route,
    frozen.PreflightGate.SINGLE_FINGER_EXTRACTION_PROFILE: (
        _gate_single_finger_extraction_profile
    ),
    frozen.PreflightGate.RAW_1TO1_SCORE_CONTRACT: _gate_raw_1to1_score_contract,
    frozen.PreflightGate.SCORE_AFFECTING_SETTINGS_CLOSURE: (
        _gate_score_affecting_settings_closure
    ),
    frozen.PreflightGate.PAIR_SELF_DETERMINISM_FAILURES: (
        _gate_pair_self_determinism_failures
    ),
    frozen.PreflightGate.FULL_WORKLOAD_FEASIBILITY: _gate_full_workload_feasibility,
    frozen.PreflightGate.TRAINING_PROVENANCE: _gate_training_provenance,
}


# ------------------------------------------------------------------ the whole


@dataclass(frozen=True, slots=True)
class FingerCellPreflight:
    """The whole preflight: every gate, the verdict, and the outcome."""

    results: tuple[GateResult, ...]
    stopped_at: frozen.PreflightGate | None
    preflight_fingerprint: str

    def __post_init__(self) -> None:
        seen = tuple(result.gate for result in self.results)
        if seen != frozen.GATE_ORDER:
            raise FingerCellGateError(
                f"the gates were reported as {seen} and the frozen order is "
                f"{frozen.GATE_ORDER}"
            )
        failed = [r.gate for r in self.results if r.status is frozen.GateStatus.FAIL]
        if len(failed) > 1:
            raise FingerCellGateError(
                f"fail-fast means one failing gate, and these failed: {failed}"
            )
        if failed and failed[0] is not self.stopped_at:
            raise FingerCellGateError(
                f"the stopping gate is {self.stopped_at} and the failing gate is "
                f"{failed[0]}"
            )
        if not failed and self.stopped_at is not None:
            raise FingerCellGateError(
                f"stopped at {self.stopped_at} with no failing gate"
            )
        # A gate that was never reached can only follow a failure. Outstanding
        # actions do not stop the run, so they never produce one (docs/adr/0104).
        if self.stopped_at is None:
            unreached = [
                r.gate
                for r in self.results
                if r.status is frozen.GateStatus.NOT_REACHED
            ]
            if unreached:
                raise FingerCellGateError(
                    f"{unreached} were never reached and nothing failed. Only a "
                    "failure stops the run; an outstanding action is recorded and "
                    "the run continues, so that one unpaid chore cannot hide nine "
                    "later answers (docs/adr/0104)"
                )

    @property
    def passed(self) -> bool:
        """Every gate passed. Not "no gate failed": NOT_REACHED is not a pass."""
        return all(r.status is frozen.GateStatus.PASS for r in self.results)

    @property
    def is_incomplete(self) -> bool:
        return any(
            r.status is frozen.GateStatus.ACTION_REQUIRED for r in self.results
        )

    @property
    def outcome(self) -> str:
        if self.passed:
            return frozen.STAGE_13A_PASS_OUTCOME
        # A failure dominates an outstanding action. Something was found wrong
        # with the candidate, and a chore left unperformed elsewhere does not
        # soften that — it is usually stranded *by* the failure, because a route
        # that cannot be executed cannot be observed either (docs/adr/0124).
        if self.stopped_at is not None:
            return frozen.STAGE_13A_FAIL_OUTCOME
        if self.is_incomplete:
            return frozen.STAGE_13A_INCOMPLETE_OUTCOME
        return frozen.STAGE_13A_FAIL_OUTCOME

    @property
    def opens_stage_13b(self) -> bool:
        return self.passed

    @property
    def reopens_algorithm_5_search(self) -> bool:
        """A final failure returns selection to the next Algorithm 5 candidate."""
        return self.outcome == frozen.STAGE_13A_FAIL_OUTCOME

    @property
    def failure_class(self) -> frozen.FailureClass | None:
        """What kind of failure this is, derived from the blocker that stopped it."""
        if self.outcome != frozen.STAGE_13A_FAIL_OUTCOME:
            return None
        codes = {blocker.blocker_code for blocker in self.blockers}
        if frozen.BlockerCode.VERIFINGER_COMPONENT_IN_THE_ROUTE in codes:
            return frozen.FailureClass.PRODUCT_IDENTITY_MISMATCH
        if (
            frozen.BlockerCode
            .FINGERCELL_TRIAL_ENTITLEMENT_UNAVAILABLE_IN_QUALIFIED_ENVIRONMENT
            in codes
        ):
            return frozen.FailureClass.OPERATIONAL_TRIAL_ENTITLEMENT_NOT_ESTABLISHED
        for code in codes:
            try:
                return frozen.FailureClass(code.value)
            except ValueError:  # pragma: no cover - checked at import
                continue
        return frozen.FailureClass.LOCAL_SMOKE_FAILED

    @property
    def sd300_overlap_status(self) -> frozen.SD300OverlapStatus:
        result = self.result(frozen.PreflightGate.TRAINING_PROVENANCE)
        if result.status is frozen.GateStatus.PASS:
            section = _section("training_provenance") or {}
            try:
                return frozen.SD300OverlapStatus(str(section.get("overlap_status", "")))
            except ValueError:  # pragma: no cover - the gate already validated it
                return frozen.SD300OverlapStatus.NO_EVIDENCE_FOUND
        if result.status is frozen.GateStatus.ACTION_REQUIRED:
            return frozen.SD300OverlapStatus.NOT_SEARCHED
        if result.status is frozen.GateStatus.FAIL:
            return frozen.SD300OverlapStatus.OVERLAP_FOUND
        return frozen.SD300OverlapStatus.NOT_REACHED

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
    def blockers(self) -> tuple[Blocker, ...]:
        return tuple(
            sorted(
                (b for r in self.results for b in r.blockers),
                key=lambda item: item.blocker_code.value,
            )
        )

    @property
    def outstanding_actions(self) -> tuple[OutstandingAction, ...]:
        """Every action still to be performed, in gate order.

        A list rather than a single next step, because the run no longer stops at
        the first one. What an incomplete Stage 13A publishes is the whole
        remaining job (docs/adr/0104).
        """
        return tuple(
            result.outstanding
            for result in self.results
            if result.outstanding is not None
        )

    def result(self, gate: frozen.PreflightGate) -> GateResult:
        for item in self.results:
            if item.gate is gate:
                return item
        raise KeyError(gate)  # pragma: no cover - GATE_ORDER is exhaustive

    def status(self, gate: frozen.PreflightGate) -> frozen.GateStatus:
        return self.result(gate).status


def run_preflight() -> FingerCellPreflight:
    """Run the gate order, and stop at the first failure or outstanding action."""
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
        if result.status is frozen.GateStatus.FAIL:
            stopped_at = gate
    return FingerCellPreflight(
        results=tuple(results),
        stopped_at=stopped_at,
        preflight_fingerprint=stable_hash(
            {
                "schema": "stage_13a_preflight_v1",
                "candidate_id": frozen.CANDIDATE_ID,
                "gates": [(r.gate.value, r.status.value) for r in results],
                "blockers": sorted(
                    b.blocker_code.value for r in results for b in r.blockers
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


# --------------------------------------------------------------- the secret guard

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
    """The raising form, for the reader and for the publisher.

    Raises:
        FingerCellSensitiveEvidenceError: the document carries something shaped
            like licence material. Nothing is redacted: a redaction that silently
            succeeds is how the second one gets missed.
    """
    findings = find_sensitive_material(node)
    if findings:
        raise FingerCellSensitiveEvidenceError(
            f"{where} carries licence material and will not be used: {list(findings)}"
        )


# --------------------------------------------------------- the contamination guard

#: Module prefixes no Stage 13A source may import. Assembled from parts so this
#: module's own source does not match the rule it defines.
_FORBIDDEN_SIBLING_IMPORTS = tuple(
    name
    for name in (
        "fpbench.adapters." + "verifinger_java",
        "fpbench.experiments." + "stage11a_qualification",
        "fpbench.experiments." + "stage11b_identity",
        "fpbench.experiments." + "verifinger_smoke",
        "fpbench.experiments." + "verifinger_runtime_manifest",
        "fpbench.experiments." + "verifinger_canonical500_full",
        "fpbench.core." + "verifinger_errors",
    )
)


def require_no_verifinger_contamination(repository_root: Path) -> tuple[str, ...]:
    """Prove that no Stage 13A module reaches the sibling algorithm.

    Stage 13A's own guard, and the reason it has an error class Stage 12A did
    not need. Both candidates come from the same vendor, and the delivered
    FingerCell archive ships common runtime components with the same naming
    convention as the one Algorithm 4 runs on. An import is the cheapest way for
    that boundary to be crossed by accident.

    Returns:
        The modules that were audited.

    Raises:
        FingerCellContaminationError: a Stage 13A module imports a sibling
            algorithm's adapter, bridge, runtime or published identity.
    """
    audited: list[str] = []
    for relative in frozen.STAGE_13A_SOURCE_FILES:
        path = Path(repository_root) / relative
        if not path.is_file():
            continue
        audited.append(relative)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:  # pragma: no cover - the file would not import
            raise FingerCellContaminationError(
                f"{relative} does not parse: {exc}"
            ) from exc
        names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
        for name in names:
            for forbidden in _FORBIDDEN_SIBLING_IMPORTS:
                if name == forbidden or name.startswith(forbidden + "."):
                    raise FingerCellContaminationError(
                        f"{relative} imports {name}, which reaches the sibling "
                        "algorithm. Common runtime components are permitted in "
                        "the *delivered archive*; a code path from this stage "
                        "into Algorithm 4 is not (docs/adr/0114)"
                    )
    return tuple(audited)


# --------------------------------------------------------- published documents


def _gate_rows(preflight: FingerCellPreflight) -> tuple[Mapping[str, Any], ...]:
    return tuple(
        {
            "gate": result.gate.value,
            "status": result.status.value,
            "summary": result.summary,
            "documents": list(frozen.gate_documents(result.gate)),
            "blockers": [item.blocker_code.value for item in result.blockers],
            "outstanding_action": (
                result.outstanding.action.value if result.outstanding else None
            ),
        }
        for result in preflight.results
    )


def _status(preflight: FingerCellPreflight, gate: frozen.PreflightGate) -> str:
    return preflight.status(gate).value


def marker_blocker_rows(blockers: tuple[Blocker, ...]) -> tuple[Mapping[str, str], ...]:
    return tuple(
        {
            "gate": item.gate.value,
            "blocker_code": item.blocker_code.value,
            "affected_component": item.affected_component,
            "evidence": item.evidence,
            "why_this_blocks_algorithm_5": item.why_this_blocks_algorithm_5,
            "how_this_would_be_lifted": item.how_this_would_be_lifted,
        }
        for item in blockers
    )


def marker_action_rows(
    actions: tuple[OutstandingAction, ...],
) -> tuple[Mapping[str, Any], ...]:
    return tuple(
        {
            "gate": action.gate.value,
            "action": action.action.value,
            "what_has_been_done": action.what_has_been_done,
            "what_remains": list(action.what_remains),
            "what_it_would_answer": action.what_it_would_answer,
        }
        for action in actions
    )


def predecessor_binding_document(
    preflight: FingerCellPreflight,
) -> Mapping[str, Any]:
    """What this stage rests on, and what it may not touch."""
    return {
        "schema": "stage_13a_predecessor_binding_v1",
        "algorithm_slot": frozen.ALGORITHM_SLOT,
        "candidate_id": frozen.CANDIDATE_ID,
        "predecessor": {
            "stage": "12A",
            "outcome": frozen.STAGE_12A_OUTCOME,
            "failure_class": frozen.STAGE_12A_FAILURE_CLASS,
            "finalization_fingerprint": frozen.STAGE_12A_FINALIZATION_FINGERPRINT,
            "what_it_established": (
                "an Innovatrics refusal at the acquisition gate, no package, no "
                "execution, and a marker that reopened the Algorithm 5 search"
            ),
            "why_it_is_bound": (
                "Stage 13A exists because that slot is open. Binding the exact "
                "fingerprint is what makes this a successor rather than a restart, "
                "and it is why no placeholder was ever written here: the value was "
                "taken from the closed marker itself"
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
                    "Algorithm 4's 6,000 published outcomes. Bound and never read: "
                    "this stage consults no prior algorithm's scores, and its "
                    "candidate happens to come from the same vendor"
                ),
            },
            {
                "stage": "8E",
                "outcome": frozen.STAGE8E_OUTCOME,
                "finalization_fingerprint": frozen.STAGE8E_FINALIZATION_FINGERPRINT,
                "purpose_fingerprint": frozen.STAGE8E_PURPOSE_FINGERPRINT,
                "policy_fingerprint": frozen.STAGE8E_POLICY_FINGERPRINT,
                "why": "third-party policy, reused and not reopened",
            },
        ],
        "forbidden_reads": list(frozen.FORBIDDEN_READS),
        "sd300_used": False,
        "prior_algorithm_scores_read": False,
    }


def acquisition_manifest_document(
    preflight: FingerCellPreflight,
) -> Mapping[str, Any]:
    """G1: what was fetched, from where, and what it hashes to."""
    state = _acquisition()
    declaration = state.declaration
    return {
        "schema": "stage_13a_acquisition_manifest_v1",
        "gate": frozen.PreflightGate.OFFICIAL_ARTIFACT_ACQUISITION.value,
        "status": _status(
            preflight, frozen.PreflightGate.OFFICIAL_ARTIFACT_ACQUISITION
        ),
        "presence": state.presence.value,
        "obtained": state.obtained,
        "pass_conditions": list(frozen.ACQUISITION_PASS_CONDITIONS),
        "artifact": dict(declaration.identity_row) if declaration else None,
        "documentation_obtained": (
            declaration.documentation_obtained if declaration else False
        ),
        "revision_agrees_with_release_notes": (
            declaration.revision_agrees_with_release_notes if declaration else None
        ),
        "official_locator": observed.OFFICIAL_LOCATOR,
        "official_locator_is_untokenized": observed.OFFICIAL_LOCATOR_IS_UNTOKENIZED,
        "tokenized_locators_are_not_published": (
            frozen.TOKENIZED_LOCATORS_ARE_NOT_PINNED
        ),
        "refused_sources": list(frozen.REFUSED_ACQUISITION_SOURCES),
        "vendor_revision_hash_is_not_a_digest": (
            frozen.VENDOR_REVISION_HASH_IS_NOT_A_DIGEST
        ),
        "public_observations": [dict(row) for row in observed.public_rows()],
        "detail": state.detail,
    }


def package_runtime_identity_document(
    preflight: FingerCellPreflight,
) -> Mapping[str, Any]:
    """G2: which product this is, which binding was chosen, and what it loads."""
    identity = _section("package_identity") or {}
    closure = _rows("runtime_closure")
    contamination = _section("contamination") or {}
    return {
        "schema": "stage_13a_package_runtime_identity_v1",
        "gate": frozen.PreflightGate.PACKAGE_RUNTIME_IDENTITY.value,
        "status": _status(preflight, frozen.PreflightGate.PACKAGE_RUNTIME_IDENTITY),
        "expected_product": frozen.PRODUCT_FAMILY,
        "expected_version": frozen.DECLARED_PRODUCT_VERSION,
        "refused_product_families": [
            item.value for item in frozen.REFUSED_PRODUCT_FAMILIES
        ],
        "identity_fields": list(frozen.PACKAGE_IDENTITY_FIELDS),
        "observed_identity": dict(identity) if identity else None,
        "binding_selection_criteria": list(frozen.BINDING_SELECTION_CRITERIA),
        "binding_preference_is_not_a_requirement": (
            frozen.BINDING_PREFERENCE_IS_NOT_A_REQUIREMENT
        ),
        "bindings_are_not_mixed": frozen.BINDINGS_ARE_NOT_MIXED,
        "runtime_component_fields": list(frozen.RUNTIME_COMPONENT_FIELDS),
        "components_to_look_for": list(frozen.RUNTIME_COMPONENTS_TO_LOOK_FOR),
        "closure_halves": [
            {"half": name, "what_it_settles": what}
            for name, what in frozen.CLOSURE_HALVES
        ],
        "declared_link_closure": [dict(row) for row in closure],
        "observed_runtime_closure": [dict(row) for row in _rows("observed_runtime_closure")],
        "runtime_closure_observation_method": (
            frozen.RUNTIME_CLOSURE_OBSERVATION_METHOD
        ),
        "declared_closure_does_not_prove_runtime_closure": (
            frozen.DECLARED_CLOSURE_DOES_NOT_PROVE_RUNTIME_CLOSURE
        ),
        "runtime_closure_is_not_inherited_from_a_sibling": (
            frozen.RUNTIME_CLOSURE_IS_NOT_INHERITED_FROM_A_SIBLING
        ),
        "contamination": {
            "claims_to_prove": list(frozen.CONTAMINATION_CLAIMS_TO_PROVE),
            "refused_components": list(frozen.VERIFINGER_ALGORITHM_COMPONENTS),
            "permitted_common_components": list(
                frozen.PERMITTED_COMMON_RUNTIME_COMPONENTS
            ),
            # Three separate claims, because they are settled at three different
            # moments and only the third is about what actually ran. Collapsing
            # them into one "contamination clean" would publish a claim stronger
            # than the evidence behind it (docs/adr/0121).
            "no_sibling_dependency_in_vendor_build_declaration": bool(
                contamination.get("no_sibling_in_vendor_build_declaration", False)
            ),
            "no_sibling_dependency_in_bridge_link_closure": bool(
                contamination.get("no_sibling_in_bridge_link_closure", False)
            ),
            "runtime_sibling_component_loaded": (
                contamination.get("runtime_sibling_component_loaded")
                if contamination.get("runtime_sibling_component_loaded") is not None
                else "NOT_YET_OBSERVED"
            ),
            "evidence": contamination.get("evidence"),
        },
        "delivered_observations": [dict(row) for row in observed.delivered_rows()],
    }


def research_use_trial_document(preflight: FingerCellPreflight) -> Mapping[str, Any]:
    """G3: what the delivered terms permit, and whether the trial runs."""
    inspection = _cached("inspection", package_inspection)
    trial = _section("trial") or {}
    assessment, refusal = _assessment_or_refusal(inspection)
    redistribution = redistribution_record()
    return {
        "schema": "stage_13a_research_use_trial_v1",
        "gate": frozen.PreflightGate.RESEARCH_USE_AND_TRIAL_OPERATION.value,
        "status": _status(
            preflight, frozen.PreflightGate.RESEARCH_USE_AND_TRIAL_OPERATION
        ),
        "separated_questions": list(frozen.LICENSE_SEPARATED_QUESTIONS),
        "trial_questions": list(frozen.TRIAL_QUESTIONS),
        "stage8e": {
            "policy_fingerprint": frozen.STAGE8E_POLICY_FINGERPRINT,
            "reused_not_reopened": True,
            "assessed": assessment is not None,
            "may_execute_locally": (
                bool(assessment.may_execute_locally) if assessment else None
            ),
            "declined_to_decide": refusal,
            "why_null_and_not_false": (
                "no component has been assessed, so Stage 8E made no decision. A "
                "false here would read as a research-use refusal nobody made "
                "(docs/adr/0095)"
            ),
        },
        "trial": {
            "activated": bool(trial.get("activated", False)),
            "entitlement_component": trial.get("entitlement_component"),
            "start_semantics": trial.get(
                "start_semantics", frozen.TrialStartSemantics.UNRESOLVED.value
            ),
            "duration_days": trial.get("duration_days", observed.ADVERTISED_TRIAL_DAYS),
            "network_requirement": trial.get(
                "network_requirement", observed.DELIVERED_NETWORK_CLAIM
            ),
            # Not "the clock did not start". Nothing observed says when the
            # 30 days begin, and no delivered or public source this stage read
            # defines it. An activation that did not succeed is not evidence
            # that no clock is running, and the honest value is UNKNOWN.
            "trial_activation_succeeded": False,
            "trial_clock_status": trial.get("clock_status", "UNKNOWN"),
        },
        "activation_attempts": [
            dict(row) for row in _rows("activation_attempts")
        ],
        "same_vendor_licensing_isolation": frozen.SAME_VENDOR_LICENSING_ISOLATION,
        "refused_license_actions": list(frozen.REFUSED_LICENSE_ACTIONS),
        "license_bypass_attempted": False,
        "trial_reset_attempted": False,
        "redistribution": {
            "decision": redistribution.decision.value,
            "redistributed_by_fpbench": redistribution.redistributed_by_fpbench,
            "basis": redistribution.basis,
        },
    }


def input_route_document(preflight: FingerCellPreflight) -> Mapping[str, Any]:
    """G4: how canonical_500 reaches the extractor."""
    route = _section("input_route") or {}
    return {
        "schema": "stage_13a_input_route_v1",
        "gate": frozen.PreflightGate.CANONICAL500_INPUT_ROUTE.value,
        "status": _status(preflight, frozen.PreflightGate.CANONICAL500_INPUT_ROUTE),
        "input_profile": frozen.BENCHMARK_INPUT_PROFILE,
        "input_ppi": frozen.BENCHMARK_INPUT_PPI,
        "pixel_format": frozen.BENCHMARK_INPUT_PIXEL_FORMAT,
        "ideal_route": list(frozen.IDEAL_INPUT_ROUTE),
        "permitted_decode_route": list(frozen.PERMITTED_DECODE_ROUTE),
        "decode_equivalence_requirements": list(
            frozen.DECODE_EQUIVALENCE_REQUIREMENTS
        ),
        "refused_preprocessing": list(frozen.REFUSED_PREPROCESSING),
        "internal_black_box_preprocessing_is_acceptable": (
            frozen.INTERNAL_BLACK_BOX_PREPROCESSING_IS_ACCEPTABLE
        ),
        "ppi_must_be_effective_at_extraction": (
            frozen.PPI_MUST_BE_EFFECTIVE_AT_EXTRACTION
        ),
        "image_dimensions_unchanged": True,
        "embedded_benchmark_sample_dimensions": list(
            frozen.EMBEDDED_BENCHMARK_SAMPLE_DIMENSIONS
        ),
        "sample_dimensions_are_not_a_preprocessing_rule": (
            frozen.SAMPLE_DIMENSIONS_ARE_NOT_A_PREPROCESSING_RULE
        ),
        "observed": dict(route) if route else None,
        "fpbench_preprocessing_required": bool(
            route.get("fpbench_preprocessing_required", False)
        ),
    }


def extraction_profile_document(preflight: FingerCellPreflight) -> Mapping[str, Any]:
    """G5: one image, one template, and what the extractor was configured with."""
    profile = _section("extraction") or {}
    return {
        "schema": "stage_13a_extraction_profile_v1",
        "gate": frozen.PreflightGate.SINGLE_FINGER_EXTRACTION_PROFILE.value,
        "status": _status(
            preflight, frozen.PreflightGate.SINGLE_FINGER_EXTRACTION_PROFILE
        ),
        "route": list(frozen.EXTRACTION_ROUTE),
        "single_finger_rule": frozen.SINGLE_FINGER_RULE,
        "required_template_format": frozen.REQUIRED_TEMPLATE_FORMAT.value,
        "refused_constructions": list(frozen.REFUSED_TEMPLATE_CONSTRUCTIONS),
        "template_cache_permitted": frozen.TEMPLATE_CACHE_PERMITTED,
        "quality_rejection_is_part_of_the_algorithm": (
            frozen.QUALITY_REJECTION_IS_PART_OF_THE_ALGORITHM
        ),
        "refused_quality_threshold_tuning": frozen.REFUSED_QUALITY_THRESHOLD_TUNING,
        "rejection_is_an_extraction_failure_not_a_zero_score": True,
        "observed": dict(profile) if profile else None,
    }


def score_contract_document(preflight: FingerCellPreflight) -> Mapping[str, Any]:
    """G6: the raw 1:1 score, its type, its direction and what fpbench does to it."""
    contract = _section("score_contract") or {}
    return {
        "schema": "stage_13a_score_contract_v1",
        "gate": frozen.PreflightGate.RAW_1TO1_SCORE_CONTRACT.value,
        "status": _status(preflight, frozen.PreflightGate.RAW_1TO1_SCORE_CONTRACT),
        "requirements": list(frozen.SCORE_CONTRACT_REQUIREMENTS),
        "native_type": contract.get("native_type", frozen.SCORE_NATIVE_TYPE),
        "direction": contract.get("direction", frozen.SCORE_DIRECTION),
        "range_status": contract.get("range_status", "NOT_DEFINED_BY_UPSTREAM"),
        "score_range_is_not_assumed": frozen.SCORE_RANGE_IS_NOT_ASSUMED,
        "observed_range_is_not_a_defined_range": True,
        "insufficient_shapes": list(frozen.INSUFFICIENT_SCORE_SHAPES),
        "fpbench_score_transformation": frozen.FPBENCH_SCORE_TRANSFORMATION,
        "refused_transformations": list(frozen.REFUSED_SCORE_TRANSFORMATIONS),
        "threshold_produced": frozen.THRESHOLD_PRODUCED,
        "decision_produced": frozen.DECISION_PRODUCED,
        "calibration_performed": frozen.CALIBRATION_PERFORMED,
        "pair_role_binding": [
            {"pair_side": left, "api_role": right}
            for left, right in frozen.PAIR_ROLE_BINDING
        ],
        "pair_labels_are_not_copied_from_another_candidate": (
            frozen.PAIR_LABELS_ARE_NOT_COPIED_FROM_ANOTHER_CANDIDATE
        ),
        "observed": dict(contract) if contract else None,
    }


def settings_closure_document(preflight: FingerCellPreflight) -> Mapping[str, Any]:
    """G7: every knob that can move a template or a score, with its authority."""
    rows = _rows("settings")
    unresolved = unresolved_score_affecting_settings()
    return {
        "schema": "stage_13a_settings_closure_v1",
        "gate": frozen.PreflightGate.SCORE_AFFECTING_SETTINGS_CLOSURE.value,
        "status": _status(
            preflight, frozen.PreflightGate.SCORE_AFFECTING_SETTINGS_CLOSURE
        ),
        "settings_to_close": list(frozen.SETTINGS_TO_CLOSE),
        "settings_list_is_not_exhaustive": frozen.SETTINGS_LIST_IS_NOT_EXHAUSTIVE,
        "discovery_surfaces": list(frozen.SETTING_DISCOVERY_SURFACES),
        "row_fields": list(frozen.SETTING_ROW_FIELDS),
        "settings_are_read_before_they_are_set": (
            frozen.SETTINGS_ARE_READ_BEFORE_THEY_ARE_SET
        ),
        "provenance_vocabulary": [item.value for item in frozen.SettingProvenance],
        "refused_provenance": frozen.REFUSED_SETTING_PROVENANCE,
        "matching_algorithm_expected_value": (
            frozen.MATCHING_ALGORITHM_EXPECTED_VALUE
        ),
        "matching_algorithm_is_not_forced_silently": (
            frozen.MATCHING_ALGORITHM_IS_NOT_FORCED_SILENTLY
        ),
        "settings": [dict(row) for row in rows],
        "settings_recorded": len(rows),
        "unresolved_score_affecting_settings": list(unresolved),
        "why_zero_is_not_the_default_answer": (
            "an archive that has not been exercised has no settings rows, and a "
            "count of zero over an inventory nobody recorded would read as a "
            "closed inventory"
        ),
    }


def qualification_run_document(preflight: FingerCellPreflight) -> Mapping[str, Any]:
    """G8: pair orientation, SELF, determinism and the four mandatory probes."""
    record = _cached("qualification", qualification_record)
    published: Mapping[str, Any] | None = None
    if record is not None:
        published = {
            "engine_kind": record.get("engine_kind"),
            "status": record.get("status"),
            "scoring_comparisons": record.get("scoring_comparisons"),
            "determinism": record.get("determinism"),
            "pair_orientation": record.get("pair_orientation"),
            "self_semantics": record.get("self_semantics"),
            "failure_probes": record.get("failure_probes"),
            "binding": record.get("binding"),
            "failed_at": record.get("failed_at"),
            "failure_class": record.get("failure_class"),
        }
    return {
        "schema": "stage_13a_qualification_run_v1",
        "gate": frozen.PreflightGate.PAIR_SELF_DETERMINISM_FAILURES.value,
        "status": _status(
            preflight, frozen.PreflightGate.PAIR_SELF_DETERMINISM_FAILURES
        ),
        "max_scoring_comparisons": frozen.QUALIFICATION_MAX_SCORING_COMPARISONS,
        "required_passes": [
            {"pass_name": name, "what_it_is": what}
            for name, what in frozen.QUALIFICATION_PASSES
        ],
        "fixture_sources": list(frozen.QUALIFICATION_FIXTURE_SOURCES),
        "pair_role_binding": [
            {"pair_side": left, "api_role": right}
            for left, right in frozen.PAIR_ROLE_BINDING
        ],
        "orientation_requirements": list(frozen.PAIR_ORIENTATION_REQUIREMENTS),
        "refused_orientation_reductions": list(
            frozen.REFUSED_ORIENTATION_REDUCTIONS
        ),
        "self_semantics_requirements": list(frozen.SELF_SEMANTICS_REQUIREMENTS),
        "determinism_levels": list(frozen.DETERMINISM_LEVELS),
        "determinism_requirement": frozen.DETERMINISM_REQUIREMENT,
        "mandatory_failure_probes": [
            {"cause": cause, "what_it_establishes": what}
            for cause, what in frozen.MANDATORY_FAILURE_PROBES
        ],
        "mandatory_failure_probe_count": frozen.MANDATORY_FAILURE_PROBE_COUNT,
        "optional_failure_probes": [
            {"cause": cause, "what_it_establishes": what}
            for cause, what in frozen.OPTIONAL_FAILURE_PROBES
        ],
        "failure_semantics_rule": frozen.FAILURE_SEMANTICS_RULE,
        "failed_qualification_is_kept": frozen.FAILED_QUALIFICATION_IS_KEPT,
        "record_binding_fields": list(frozen.QUALIFICATION_RECORD_BINDING_FIELDS),
        "run": published,
        "no_score_value_is_published": True,
    }


def workload_feasibility_document(
    preflight: FingerCellPreflight,
) -> Mapping[str, Any]:
    """G9: whether the trial covers the benchmark this candidate would have to run."""
    workload = _section("workload") or {}
    return {
        "schema": "stage_13a_workload_feasibility_v1",
        "gate": frozen.PreflightGate.FULL_WORKLOAD_FEASIBILITY.value,
        "status": _status(preflight, frozen.PreflightGate.FULL_WORKLOAD_FEASIBILITY),
        "frozen_workload": {
            "comparison_attempts": frozen.FROZEN_WORKLOAD.comparison_attempts,
            "independent_extractions": (
                frozen.FROZEN_WORKLOAD.independent_extractions
            ),
            "matcher_invocations": frozen.FROZEN_WORKLOAD.matcher_invocations,
            "qualification_allowance": (
                frozen.FROZEN_WORKLOAD.qualification_allowance
            ),
            "total_extractions": frozen.FROZEN_WORKLOAD.total_extractions,
            "total_matcher_invocations": (
                frozen.FROZEN_WORKLOAD.total_matcher_invocations
            ),
            "total_logical_operations": (
                frozen.FROZEN_WORKLOAD.total_logical_operations
            ),
            "template_cache_permitted": frozen.TEMPLATE_CACHE_PERMITTED,
        },
        "capacity_questions": list(frozen.TRIAL_CAPACITY_QUESTIONS),
        "quota_schema_vocabulary": [item.value for item in frozen.QuotaSchema],
        "unresolved_quota_blocks_pass": frozen.UNRESOLVED_QUOTA_BLOCKS_PASS,
        "timing_measurements": list(frozen.RUNTIME_TIMING_MEASUREMENTS),
        "timing_is_not_a_performance_comparison": True,
        "vendor_embedded_figures_are_not_a_pc_estimate": (
            frozen.VENDOR_EMBEDDED_FIGURES_ARE_NOT_A_PC_ESTIMATE
        ),
        "observed": dict(workload) if workload else None,
    }


def training_provenance_document(
    preflight: FingerCellPreflight,
) -> Mapping[str, Any]:
    """G10: whether this candidate was built on the benchmark's evaluation data."""
    provenance = _section("training_provenance") or {}
    return {
        "schema": "stage_13a_training_provenance_v1",
        "gate": frozen.PreflightGate.TRAINING_PROVENANCE.value,
        "status": _status(preflight, frozen.PreflightGate.TRAINING_PROVENANCE),
        "standard": (
            "the same one Algorithm 4 was held to: proprietary and undisclosed "
            "until something says otherwise"
        ),
        "training_provenance": (
            frozen.TrainingProvenanceStatus.PROPRIETARY_UNDISCLOSED.value
            if preflight.status(frozen.PreflightGate.TRAINING_PROVENANCE)
            is frozen.GateStatus.PASS
            else frozen.TrainingProvenanceStatus.NOT_REACHED.value
        ),
        "search_terms": list(frozen.SD300_SEARCH_TERMS),
        "surfaces": list(frozen.SD300_OVERLAP_SURFACES),
        "overlap_status": preflight.sd300_overlap_status.value,
        "not_searched_is_an_action_not_a_finding": True,
        "sd300_image_bytes_read": False,
        "sd300_pair_manifest_read": False,
        "sd300_scores_read": False,
        "observed": dict(provenance) if provenance else None,
    }


def preflight_report_document(preflight: FingerCellPreflight) -> Mapping[str, Any]:
    """The whole run: every gate, the outcome, and what it does and does not say."""
    return {
        "schema": "stage_13a_preflight_report_v1",
        "candidate_id": frozen.CANDIDATE_ID,
        "algorithm_slot": frozen.ALGORITHM_SLOT,
        "product": frozen.PRODUCT_FAMILY,
        "product_version": frozen.DECLARED_PRODUCT_VERSION,
        "implementation_origin": frozen.IMPLEMENTATION_ORIGIN,
        "outcome": preflight.outcome,
        "gate_count_defined": frozen.GATE_COUNT,
        "gates_reached": preflight.gates_reached,
        "gates_passed": preflight.gates_passed,
        "gates_awaiting_action": preflight.gates_awaiting_action,
        "stopped_at": preflight.stopped_at.value if preflight.stopped_at else None,
        "gate_states": [item.value for item in frozen.GateStatus],
        "action_required_is_not_a_failure": (
            "ACTION_REQUIRED means a local step this project can perform has not "
            "been performed. It is not a finding about FingerCell, it produces no "
            "finalization marker, and it is never published as a blocker "
            "(docs/adr/0112)"
        ),
        "only_a_failure_stops_the_run": (
            "a gate awaiting an action is recorded and the run continues, so that "
            "one unpaid chore cannot hide nine later answers. NOT_REACHED appears "
            "only after a failure (docs/adr/0104)"
        ),
        "gates": [dict(row) for row in _gate_rows(preflight)],
        "blockers": [dict(row) for row in marker_blocker_rows(preflight.blockers)],
        "outstanding_actions": [
            dict(row) for row in marker_action_rows(preflight.outstanding_actions)
        ],
        "failure_class": (
            preflight.failure_class.value if preflight.failure_class else None
        ),
        "acceptance_conditions": list(frozen.ACCEPTANCE_CONDITIONS),
        "non_goals": list(frozen.NON_GOALS),
        "permitted_constructions": list(frozen.PERMITTED_CONSTRUCTIONS),
        "ci_must_not": list(frozen.CI_MUST_NOT),
        "ci_may": list(frozen.CI_MAY),
        "opens_stage_13b": preflight.opens_stage_13b,
        "reopens_algorithm_5_search": preflight.reopens_algorithm_5_search,
        "observations_fingerprint": observed.observations_fingerprint(),
        "preflight_fingerprint": preflight.preflight_fingerprint,
    }


_DOCUMENT_BUILDERS = {
    frozen.PREDECESSOR_BINDING_NAME: predecessor_binding_document,
    frozen.ACQUISITION_MANIFEST_NAME: acquisition_manifest_document,
    frozen.PACKAGE_RUNTIME_IDENTITY_NAME: package_runtime_identity_document,
    frozen.RESEARCH_USE_TRIAL_NAME: research_use_trial_document,
    frozen.INPUT_ROUTE_NAME: input_route_document,
    frozen.EXTRACTION_PROFILE_NAME: extraction_profile_document,
    frozen.SCORE_CONTRACT_NAME: score_contract_document,
    frozen.SETTINGS_CLOSURE_NAME: settings_closure_document,
    frozen.QUALIFICATION_RUN_NAME: qualification_run_document,
    frozen.WORKLOAD_FEASIBILITY_NAME: workload_feasibility_document,
    frozen.TRAINING_PROVENANCE_NAME: training_provenance_document,
    frozen.PREFLIGHT_REPORT_NAME: preflight_report_document,
}


def evidence_document(
    preflight: FingerCellPreflight, name: str
) -> Mapping[str, Any]:
    """Build one published document by name, guarded before it is returned."""
    try:
        builder = _DOCUMENT_BUILDERS[name]
    except KeyError:  # pragma: no cover - DERIVABLE_EVIDENCE_FILES is the caller
        raise Stage13AFinalizationError(
            f"{name} is not a derivable Stage 13A document"
        ) from None
    document = builder(preflight)
    require_no_sensitive_material(document, where=f"the derived {name}")
    return document
