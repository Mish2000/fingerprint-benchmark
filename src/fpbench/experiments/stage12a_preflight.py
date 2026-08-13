"""The ten hard gates, run in order, and the verdict that follows.

The engine has no verdict parameter, for the reason Stage 8E's decision engine
has none and Stage 10B's and Stage 11A's preflights have none: an engine that
accepted an outcome and then validated it would be a very elaborate way of
writing the outcome down. It reads the acquisition state of this machine, the
inspection record beside a delivered package, the qualification record a run
left behind, and Stage 8E's own policy, applies the order frozen in
:mod:`fpbench.experiments.stage12a_idkit_identity`, and reports what follows.

**Fail-fast is the design, not an optimisation.** The run stops at the first gate
that fails and every later gate is published ``NOT_REACHED``.

**Pending stops the run without judging it.** Acquisition may report ``PENDING``,
and a pending acquisition stops the run in exactly the same mechanical way a
failure does — and means the opposite. Every later gate is ``NOT_REACHED``, no
blocker is raised, no marker is written, and nothing has been established about
IDKit either way (docs/adr/0108).

**A gate is answered from the package or it is not answered.** Every runner below
reaches its conclusion from the delivered bytes, from a record a run on this
machine produced, or from Stage 8E's policy. None of them reads a support
article: what a vendor's undated page says a default is worth is not what the
delivered engine was constructed with (docs/adr/0110).

Nothing here reads SD300, reads a prior algorithm's scores, downloads anything,
activates a licence, loads a vendor library or produces a score.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from fpbench.core.idkit_preflight_errors import (
    IdkitGateError,
    IdkitSensitiveEvidenceError,
    Stage12AFinalizationError,
)
from fpbench.core.serialization import stable_hash
from fpbench.experiments import stage12a_idkit_identity as frozen
from fpbench.experiments import stage12a_idkit_observations as observed
from fpbench.experiments.stage12a_acquisition import (
    AcquisitionState,
    acquisition_state,
    artifact_store_prefix_path,
    require_no_idkit_bytes_in_git,
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
    "PACKAGE_INSPECTION_NAME",
    "Blocker",
    "PendingReason",
    "GateResult",
    "IdkitPreflight",
    "require_stage8e_is_the_policy_this_reuses",
    "require_stage11b_is_the_closed_predecessor",
    "require_no_idkit_bytes_in_git",
    "acquisition_state",
    "unresolved_score_affecting_settings",
    "package_inspection",
    "qualification_record",
    "research_use_assessment",
    "redistribution_record",
    "run_preflight",
    "evidence_document",
    "marker_blocker_rows",
    "find_sensitive_material",
    "require_no_sensitive_material",
]

#: What the maintainer writes into the store after inspecting a delivered
#: package: the binding they selected, the runtime closure, the input route, the
#: representation, every setting with its provenance, the score contract and the
#: licence's actual entitlement. Outside Git, like everything else in the store.
PACKAGE_INSPECTION_NAME = "package-inspection.json"


# ------------------------------------------------------------ the closed stages


def require_stage8e_is_the_policy_this_reuses(repository_root: Path) -> None:
    """Confirm the policy Stage 12A reuses is the policy it was written against.

    Raises:
        Stage12AFinalizationError: the published Stage 8E marker, the live
            purpose or the live policy has moved. Stage 12A does not repair
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
            raise Stage12AFinalizationError(
                f"the Stage 8E marker's {key} is {found!r} and Stage 12A was "
                f"written against {value!r}. Stage 8E is a closed stage; a "
                "capability it lacks is a corrective policy stage, not an edit "
                "from here"
            )
    declaration = project_purpose()
    if declaration.purpose_fingerprint != frozen.STAGE8E_PURPOSE_FINGERPRINT:
        raise Stage12AFinalizationError(
            "the live project purpose no longer fingerprints to what Stage 8E "
            "published; every Stage 12A decision would be taken under a "
            "different premise"
        )
    if policy_fingerprint() != frozen.STAGE8E_POLICY_FINGERPRINT:
        raise Stage12AFinalizationError(
            "the live third-party policy no longer fingerprints to what Stage 8E "
            "published"
        )


def require_stage11b_is_the_closed_predecessor(repository_root: Path) -> str:
    """Confirm Stage 11B still says what Stage 12A was written after.

    Stage 12A exists because Stage 11B finished Algorithm 4 and opened a search
    for Algorithm 5. Binding that marker's fingerprint is what makes "Stage 11B
    was not re-opened to make room for this" a checkable claim rather than an
    intention.

    Returns:
        The predecessor fingerprint, for the marker to carry.

    Raises:
        Stage12AFinalizationError: Stage 11B's marker has moved.
    """
    relative = f"{frozen.STAGE_11B_EVIDENCE_DIRECTORY}/stage-11b-finalization.json"
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
            raise Stage12AFinalizationError(
                f"the Stage 11B marker's {key} is {found!r} and Stage 12A was "
                f"written after {value!r}. Stage 11B is immutable here"
            )
    if marker.get("opens_algorithm_5_search") is not True:
        raise Stage12AFinalizationError(
            "Stage 11B's marker no longer opens a search for Algorithm 5, and "
            "that search is the only thing Stage 12A is a response to"
        )
    return frozen.STAGE_11B_FINALIZATION_FINGERPRINT


def _read_marker(
    repository_root: Path, relative: str, stage: str
) -> Mapping[str, Any]:
    path = Path(repository_root) / PurePosixPath(relative)
    try:
        marker = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Stage12AFinalizationError(
            f"cannot read the {stage} marker Stage 12A binds at {relative}: {exc}"
        ) from exc
    if not isinstance(marker, dict):
        raise Stage12AFinalizationError(f"the {stage} marker is not a JSON object")
    return marker


# ----------------------------------------------------------------- Stage 8E

#: What Stage 8E is asked about, and the one thing that can be said about it
#: today. Innovatrics' licence terms arrive *with the package*, and this project
#: has not received one — so there is no notice to read, no locator to cite and
#: no assessment to derive.
#:
#: A placeholder assessment would be worse than none: it would put a
#: ``MAY_EXECUTE_LOCALLY`` into the evidence of a stage that never saw a licence.
_NO_LICENSE_EVIDENCE_YET = (
    "Innovatrics delivers its licence terms with the package, through the "
    "customer portal. No package has been delivered here, so no notice has been "
    "read, and Stage 8E has been asked nothing. The policy is bound by "
    "fingerprint and will be applied to the EULA that actually arrives."
)


def research_use_assessment(
    inspection: Mapping[str, Any] | None,
) -> ResearchUseAssessment | None:
    """What Stage 8E returns over the notices that arrived with the package.

    Returns:
        ``None`` where no package has been delivered. That is not a refusal and
        must not be published as one: Stage 10B established that a component
        nobody obtained is a component Stage 8E assessed zero of, and a ``false``
        there would read as a research-use refusal nobody made (docs/adr/0095).
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
        # Stage 8E computes the conservative answer from at least two plausible
        # readings and refuses to assume one. That is its rule and Stage 12A
        # applies it rather than working around it: a single reading of a
        # field-of-use-limited licence is that reading, and calling it an
        # intersection would dress an ordinary conclusion up as a careful one.
        raise Stage12AFinalizationError(
            "the delivered licence limits the field of use and only "
            f"{len(readings)} plausible reading was recorded. Stage 8E needs at "
            "least two to compute the conservative answer, and Stage 12A does not "
            "assume one on its behalf"
        )
    restrictions = tuple(
        NonBlockingRestriction(str(item))
        for item in licence.get("non_blocking_restrictions", ())
        if str(item) in {member.value for member in NonBlockingRestriction}
    )
    observation = LicenseObservation(
        observation_id="innovatrics_idkit_delivered_license",
        component_kind=ThirdPartyComponentKind.RUNTIME_BINARY,
        subject=(
            "the Innovatrics IDKit package as delivered, under the terms that "
            "arrived with it"
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
        assessment_id="innovatrics_idkit_local_research_execution",
        basis=str(licence.get("basis", "")),
        non_blocking_restrictions=restrictions,
        intersection_readings=readings,
        identity_established=True,
    )


def _assessment_or_refusal(
    inspection: Mapping[str, Any] | None,
) -> tuple[ResearchUseAssessment | None, str | None]:
    """Stage 8E's decision, or the reason it declined to make one.

    Stage 8E raises where the facts it was given are inconsistent with each
    other. That is a refusal to decide, not a crash, and the gate turns it into a
    named blocker rather than letting it escape and take the whole preflight down
    — a stage that cannot report on a badly-recorded licence is a stage that
    cannot report.
    """
    from fpbench.core.errors import FpbenchError

    try:
        return research_use_assessment(inspection), None
    except FpbenchError as exc:
        return None, f"Stage 8E declined to decide on these facts: {exc}"


def redistribution_record() -> RedistributionRecord:
    """What fpbench does by way of redistribution. Nothing, under either outcome.

    True before a package arrives and true afterwards: the package, its models
    and every native library stay in the local artifact store, outside the
    working tree, and the repository holds only descriptions of them — a
    filename, a size, a digest (docs/adr/0083).
    """
    return RedistributionRecord(
        decision=RedistributionDecision.NOT_ALLOWED,
        basis=(
            "A vendor SDK delivered through a customer portal is not "
            "redistributable, and fpbench redistributes nothing in any case. No "
            "package byte, model, licence or template enters this repository."
        ),
        redistributed_by_fpbench=False,
    )


# ------------------------------------------------------------------- the gates


@dataclass(frozen=True, slots=True)
class Blocker:
    """One reason IDKit cannot enter fpbench as Algorithm 5.

    ``how_this_would_be_lifted`` is mandatory. A blocker nobody can act on is a
    blocker nobody can lift, and every blocker this stage can raise is one a
    person could lift deliberately.
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
            raise IdkitGateError(
                f"{self.blocker_code.value} does not belong to {self.gate.value}; "
                f"it belongs to "
                f"{[item.value for item in frozen.gate_of_blocker(self.blocker_code)]}"
                " and raising it here would put the reason in the wrong place"
            )
        for name in (
            "affected_component",
            "evidence",
            "why_this_blocks_algorithm_5",
            "how_this_would_be_lifted",
        ):
            if not str(getattr(self, name)).strip():
                raise IdkitGateError(f"{self.blocker_code.value}: {name} is empty")


@dataclass(frozen=True, slots=True)
class PendingReason:
    """Why the acquisition gate has not answered yet.

    Structurally a sibling of :class:`Blocker` and semantically its opposite. A
    blocker says something is wrong with the route; a pending reason says an
    official route was walked and somebody else has to move next. Nothing about
    the candidate follows from one (docs/adr/0108).
    """

    acquisition_status: frozen.AcquisitionStatus
    what_was_walked: str
    what_is_outstanding: tuple[str, ...]
    what_it_would_answer: str

    def __post_init__(self) -> None:
        if not self.acquisition_status.is_pending:
            raise IdkitGateError(
                f"{self.acquisition_status.value} is not a pending state, and a "
                "pending reason built on it would hide either a delivery or a "
                "refusal"
            )
        if not str(self.what_was_walked).strip():
            raise IdkitGateError("a pending reason says what was actually tried")
        if not self.what_is_outstanding:
            raise IdkitGateError(
                "a pending reason names what would move it; one that named "
                "nothing would be indistinguishable from giving up"
            )


@dataclass(frozen=True, slots=True)
class GateResult:
    """One gate's conclusion."""

    gate: frozen.PreflightGate
    status: frozen.GateStatus
    summary: str
    blockers: tuple[Blocker, ...] = ()
    pending: PendingReason | None = None

    def __post_init__(self) -> None:
        if self.status is frozen.GateStatus.PASS and (self.blockers or self.pending):
            raise IdkitGateError(
                f"{self.gate.value}: a gate that passed carries no blockers and "
                "nothing outstanding; a blocker is not a reservation to be weighed"
            )
        if self.status is frozen.GateStatus.FAIL and not self.blockers:
            raise IdkitGateError(f"{self.gate.value}: a gate that failed names why")
        if self.status is frozen.GateStatus.FAIL and self.pending:
            raise IdkitGateError(
                f"{self.gate.value}: a gate that failed found something wrong with "
                "the route, and something outstanding beside it would blur the two "
                "claims this stage keeps apart"
            )
        if self.status is frozen.GateStatus.PENDING:
            if self.gate not in frozen.PENDING_CAPABLE_GATES:
                raise IdkitGateError(
                    f"{self.gate.value} may not report PENDING. Acquisition is the "
                    "one question whose answer can be 'somebody else has to reply "
                    "first'; anywhere else it would be a way of not deciding"
                )
            if self.blockers:
                raise IdkitGateError(
                    f"{self.gate.value}: a pending gate found nothing wrong; a "
                    "blocker here would say something about IDKit that nothing "
                    "established"
                )
            if self.pending is None:
                raise IdkitGateError(
                    f"{self.gate.value}: a pending gate says what it is waiting for"
                )
        if self.status is frozen.GateStatus.NOT_REACHED and (
            self.blockers or self.pending
        ):
            raise IdkitGateError(
                f"{self.gate.value}: a gate that was never reached cannot have "
                "found anything"
            )
        for blocker in self.blockers:
            if blocker.gate is not self.gate:
                raise IdkitGateError(
                    f"{self.gate.value}: carries a blocker raised at "
                    f"{blocker.gate.value}"
                )


# --------------------------------------------------------- what this machine has

#: One run's worth of answers about this machine, computed once. Ten gates asking
#: the store the same three questions would hash a package ten times.
_RUN_CACHE: dict[str, Any] = {}


def _cached(key: str, factory: Any) -> Any:
    if key not in _RUN_CACHE:
        _RUN_CACHE[key] = factory()
    return _RUN_CACHE[key]


def _acquisition() -> AcquisitionState:
    return _cached("acquisition", acquisition_state)


def package_inspection() -> Mapping[str, Any] | None:
    """The inspection record beside a delivered package, or ``None``.

    Guarded on the way in: the record is written by hand on a machine that also
    holds licence material, and a hardware ID must not travel from the store into
    a document some later code path publishes.
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
    from fpbench.experiments.stage12a_qualification import (
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


def _inspection_section(name: str) -> Mapping[str, Any] | None:
    inspection = _cached("inspection", package_inspection)
    if not inspection:
        return None
    section = inspection.get(name)
    return section if isinstance(section, Mapping) else None


def _inspection_rows(name: str) -> tuple[Mapping[str, Any], ...]:
    inspection = _cached("inspection", package_inspection)
    if not inspection:
        return ()
    rows = inspection.get(name)
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return ()
    return tuple(item for item in rows if isinstance(item, Mapping))


def _unresolved_settings(rows: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    """Every score-affecting setting with no upstream authority behind a value.

    The count this returns is the stage's central finding about configuration. A
    setting nobody recorded still decides the score, and "it was whatever the
    engine happened to be constructed with" is not an authority — it becomes one
    only when somebody reads it off a running engine and records it as a
    ``DELIVERED_RUNTIME_DEFAULT``.
    """
    unresolved: list[str] = []
    for row in rows:
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


def unresolved_score_affecting_settings() -> tuple[str, ...]:
    """Every score-affecting setting, across both profiles, with no authority.

    The count the marker publishes. Zero where the inventory is closed, and never
    zero merely because nobody has recorded an inventory: a package that has not
    been inspected has no settings rows, and a caller that read this as "nothing
    is unresolved" would be reading an absence as an answer.
    """
    return _unresolved_settings(
        (
            *_inspection_rows("extraction_settings"),
            *_inspection_rows("matcher_settings"),
        )
    )


def _not_reached_reason(stopped_at: frozen.PreflightGate, pending: bool) -> str:
    if pending:
        return (
            f"the run paused at {stopped_at.value} while an official acquisition "
            "route is outstanding, so this question was never asked: nothing was "
            "delivered, inspected, activated, loaded or executed for it"
        )
    return (
        f"the run stopped at {stopped_at.value}, so this question was never "
        "asked: nothing was inspected, activated, loaded or executed for it"
    )


# ------------------------------------------------------------------- gate 1


def _gate_acquisition_access() -> GateResult:
    """G1. Is an official package here, with its documentation and a licence route?

    Three things, and all three come from the delivery rather than from a page
    about it: the package, the documentation that matches the version delivered,
    and a legitimate route to a licence. A package with no documentation cannot
    settle a settings inventory; a package with no licence route cannot be run at
    all.

    The gate has three outcomes rather than two, and the third is the point of
    this stage's design. A vendor that has not replied is not a vendor that
    refused (docs/adr/0108).
    """
    state = _acquisition()
    gate = frozen.PreflightGate.ACQUISITION_ACCESS
    if state.obtained and state.declaration is not None:
        declaration = state.declaration
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.PASS,
            summary=(
                f"{declaration.exact_product_name} "
                f"{declaration.implementation_version} was delivered through "
                f"{declaration.delivery_channel.value}, its matching "
                "documentation was obtained, a legitimate licensing route "
                "exists, and the file in the local store matches the declared "
                f"{declaration.package_size_bytes}-byte size and its digest. "
                f"{len(observed.REFUSED_ROUTES)} non-vendor routes were found and "
                "refused on provenance"
            ),
        )
    if state.is_refusal:
        code = (
            frozen.BlockerCode.ACCESS_REFUSED_BY_VENDOR
            if state.status is frozen.AcquisitionStatus.ACCESS_REFUSED
            else frozen.BlockerCode.OFFICIAL_PACKAGE_UNAVAILABLE
        )
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.FAIL,
            blockers=(
                Blocker(
                    gate=gate,
                    blocker_code=code,
                    affected_component="the official Innovatrics IDKit package",
                    evidence=f"acquisition-status.json: {state.basis}",
                    why_this_blocks_algorithm_5=(
                        "Every remaining gate is a question about a delivered "
                        "package — its identity, its runtime closure, its input "
                        "route, its profiles, its score API. None of them can be "
                        "answered about a package nobody holds, and answering "
                        "them from a support article would be publishing a "
                        "benchmark route this project had never opened"
                    ),
                    how_this_would_be_lifted=(
                        "Only the vendor can lift it, by supplying a package for "
                        "this target under terms this project can accept. It is "
                        "not lifted by obtaining the package from a mirror, a "
                        "catalogue site or a reseller: a package whose chain of "
                        "custody does not run to the vendor is a package nothing "
                        "can pin"
                    ),
                ),
            ),
            summary=f"the vendor route closed: {state.status.value}",
        )
    if state.status.is_pending:
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.PENDING,
            pending=PendingReason(
                acquisition_status=state.status,
                what_was_walked=state.basis,
                what_is_outstanding=observed.WHAT_WOULD_CHANGE_THE_STATUS,
                what_it_would_answer=(
                    "Everything below this gate. The package's exact identity, "
                    "its runtime closure, whether it reads the benchmark's PNG or "
                    "needs a raw buffer, whether a single fingerprint can be "
                    "compared against a single fingerprint without a consolidated "
                    "record score, whether a raw scalar is readable independently "
                    "of the decision, and whether every setting behind that "
                    "scalar can be frozen"
                ),
            ),
            summary=(
                f"{state.status.value}: {len(observed.ACQUISITION_ROUTES)} official "
                "routes were walked and none of them delivers a package to a "
                "project without a customer account. Nothing was refused"
            ),
        )
    # Bytes without a declaration: not possession, and not a finding either.
    return GateResult(  # pragma: no cover - requires a half-populated store
        gate=gate,
        status=frozen.GateStatus.PENDING,
        pending=PendingReason(
            acquisition_status=frozen.AcquisitionStatus.PORTAL_ACCESS_REQUIRED,
            what_was_walked=state.basis,
            what_is_outstanding=(
                "record what was delivered in the store's package declaration: "
                "the product, the family, the version, the build, the filename, "
                "the size, the digest, the delivery channel and the platform",
            ),
            what_it_would_answer=(
                "Whether the bytes in the store are a vendor delivery this "
                "project may pin, or something nobody recorded the provenance of"
            ),
        ),
        summary=f"{state.presence.value}: {state.detail}",
    )


# ------------------------------------------------------------------- gate 2


def _gate_package_runtime_identity() -> GateResult:
    """G2. Is the thing that would compute a score exactly identified?

    Two halves. The **package** is identified from the delivery: the product, the
    family, the version, the build, the filename, the size, the digest, the
    channel and the platform. The **runtime** is the transitive closure —
    everything the fingerprint route actually loads, each with a path, a role, a
    size and a digest.

    The family check is not a formality. IDKit generates the vendor's proprietary
    templates and does 1:1 and 1:N; the ANSI&ISO SDK is a different product for
    standardised templates. A package that turned out to be the wrong one would
    still produce numbers.
    """
    gate = frozen.PreflightGate.PACKAGE_RUNTIME_IDENTITY
    state = _acquisition()
    declaration = state.declaration
    if declaration is None:  # pragma: no cover - unreachable behind a passing G1
        return _identity_failure(
            gate,
            frozen.BlockerCode.PACKAGE_IDENTITY_UNRESOLVED,
            "no package declaration is present although acquisition passed",
        )
    if declaration.product_family in frozen.REFUSED_PRODUCT_FAMILIES:
        return _identity_failure(
            gate,
            frozen.BlockerCode.PACKAGE_IDENTITY_UNRESOLVED,
            (
                f"the delivered package resolves to "
                f"{declaration.product_family.value}, and this candidate is "
                f"{frozen.ProductFamily.IDKIT_SDK.value}. The two are different "
                "products with different templates and different accuracy"
            ),
        )
    if declaration.implementation_version == frozen.IMPLEMENTATION_VERSION_UNRESOLVED:
        return _identity_failure(
            gate,
            frozen.BlockerCode.PACKAGE_IDENTITY_UNRESOLVED,
            (
                "the delivered package has not reported its own version. The "
                "number on the vendor's course page is an indication of what to "
                "look for and is not a statement about these bytes"
            ),
        )

    components = _inspection_rows("runtime_components")
    if not components:
        return _identity_failure(
            gate,
            frozen.BlockerCode.RUNTIME_COMPONENT_UNRESOLVED,
            (
                "no runtime inventory has been recorded for the delivered "
                "package. A route assembled from components nobody listed is a "
                "route whose identity cannot be pinned, and a library swapped "
                "underneath it would change every score without changing anything "
                "this stage published"
            ),
        )
    incomplete = tuple(
        str(row.get("relative_path", "<unnamed>"))
        for row in components
        if any(
            not str(row.get(field, "")).strip()
            for field in frozen.RUNTIME_COMPONENT_FIELDS
            if field != "version_or_build"
        )
    )
    if incomplete:
        return _identity_failure(
            gate,
            frozen.BlockerCode.RUNTIME_COMPONENT_UNRESOLVED,
            (
                f"{len(incomplete)} recorded runtime components are missing a "
                f"path, a role, a size or a digest: {list(incomplete[:5])}"
            ),
        )
    binding = _inspection_section("binding") or {}
    unmet = tuple(
        criterion
        for criterion, key in zip(
            frozen.BINDING_SELECTION_CRITERIA,
            (
                "version_matched",
                "vendor_supplied",
                "ships_a_1to1_sample",
                "exposes_every_setting",
                "returns_raw_score",
            ),
        )
        if not bool(binding.get(key))
    )
    if unmet:
        return _identity_failure(
            gate,
            frozen.BlockerCode.RUNTIME_COMPONENT_UNRESOLVED,
            (
                "the selected binding does not satisfy "
                f"{len(unmet)} of the {len(frozen.BINDING_SELECTION_CRITERIA)} "
                f"selection criteria: {list(unmet)}"
            ),
        )
    return GateResult(
        gate=gate,
        status=frozen.GateStatus.PASS,
        summary=(
            f"{frozen.IMPLEMENTATION_ORIGIN}: "
            f"{declaration.exact_product_name} "
            f"{declaration.implementation_version} build "
            f"{declaration.package_build}, resolved to "
            f"{declaration.product_family.value} and pinned by digest on "
            f"{declaration.operating_system}/{declaration.architecture}. The "
            f"runtime closure names {len(components)} score-relevant components, "
            f"each with a path, a role, a size and a digest, and one official "
            f"binding — {binding.get('binding_id', 'unnamed')} — satisfies all "
            f"{len(frozen.BINDING_SELECTION_CRITERIA)} selection criteria"
        ),
    )


def _identity_failure(
    gate: frozen.PreflightGate, code: frozen.BlockerCode, evidence: str
) -> GateResult:
    return GateResult(
        gate=gate,
        status=frozen.GateStatus.FAIL,
        blockers=(
            Blocker(
                gate=gate,
                blocker_code=code,
                affected_component="the delivered IDKit package and its runtime",
                evidence=evidence,
                why_this_blocks_algorithm_5=(
                    "An algorithm identity that cannot name the exact package, "
                    "build and loaded components is an identity a later run "
                    "cannot reproduce, and a benchmark whose algorithm cannot be "
                    "reproduced is a benchmark of nothing in particular"
                ),
                how_this_would_be_lifted=(
                    "Record the missing identity in the store's package "
                    "declaration and inspection record and re-run. Everything "
                    "needed is a property of the delivered bytes; nothing has to "
                    "be requested from the vendor"
                ),
            ),
        ),
        summary=evidence,
    )


# ------------------------------------------------------------------- gate 3


def _gate_research_use_and_license() -> GateResult:
    """G3. Does Stage 8E permit this, and does the licence actually activate?

    Two questions kept apart on purpose. Stage 8E answers whether the terms that
    arrived with the package permit one person executing it locally for
    non-commercial research; activation answers whether the thing then runs.
    Permission without a licence is a route nobody can walk, and a licence
    without permission is not a permission.
    """
    gate = frozen.PreflightGate.RESEARCH_USE_AND_LICENSE
    inspection = _cached("inspection", package_inspection)
    assessment, refusal = _assessment_or_refusal(inspection)
    if assessment is None:
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.FAIL,
            blockers=(
                Blocker(
                    gate=gate,
                    blocker_code=frozen.BlockerCode.RESEARCH_USE_BLOCKED,
                    affected_component="the licence delivered with the package",
                    evidence=refusal
                    or (
                        "no licence notice has been recorded for the delivered "
                        "package, so Stage 8E has been asked nothing and no "
                        "decision exists"
                    ),
                    why_this_blocks_algorithm_5=(
                        "A component whose terms nobody read may not be executed "
                        "under a policy whose whole purpose is that somebody read "
                        "them"
                    ),
                    how_this_would_be_lifted=(
                        "Record the EULA that arrived with the package — its "
                        "locator, its digest and what it states — in the store's "
                        "inspection record, and re-run. Stage 8E's engine derives "
                        "the decision; nothing here asserts one"
                    ),
                ),
            ),
            summary="no delivered licence notice has been recorded",
        )
    if not assessment.decision.opens_execution:
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.FAIL,
            blockers=(
                Blocker(
                    gate=gate,
                    blocker_code=frozen.BlockerCode.RESEARCH_USE_BLOCKED,
                    affected_component="the Innovatrics IDKit package",
                    evidence=(
                        "research-use-license.json: Stage 8E returned "
                        f"{assessment.decision.value} over the notices delivered "
                        f"with the package, with blockers "
                        f"{[item.value for item in assessment.blockers]}"
                    ),
                    why_this_blocks_algorithm_5=(
                        "A component this project may not execute cannot be "
                        "qualified by executing it, and a benchmark route nobody "
                        "is permitted to run is not a route"
                    ),
                    how_this_would_be_lifted=(
                        "Only upstream can lift it, by terms that permit the "
                        "declared use. It is not lifted by reading the notices "
                        "again more optimistically (docs/adr/0082)"
                    ),
                ),
            ),
            summary=f"Stage 8E returned {assessment.decision.value}",
        )
    licence = _inspection_section("license") or {}
    if not bool(licence.get("activated")):
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.FAIL,
            blockers=(
                Blocker(
                    gate=gate,
                    blocker_code=frozen.BlockerCode.LICENSE_ACTIVATION_FAILED,
                    affected_component="the licence for the delivered package",
                    evidence=(
                        "research-use-license.json: Stage 8E opens execution and "
                        "no licence has been activated on this machine"
                    ),
                    why_this_blocks_algorithm_5=(
                        "The SDK checks its licence before it will do anything, "
                        "so without one there is no route to smoke, no version to "
                        "read from a running library and no score to contract over"
                    ),
                    how_this_would_be_lifted=(
                        "Generate a licence through the vendor's own portal for "
                        "this machine, after the harness compiles and links — not "
                        "before, so that a time-limited clock is not spent on "
                        "build errors (docs/adr/0111). Nothing about the licence "
                        "is bypassed, reset or worked around"
                    ),
                ),
            ),
            summary="the licence has not been activated",
        )
    return GateResult(
        gate=gate,
        status=frozen.GateStatus.PASS,
        summary=(
            f"{assessment.decision.value} with intended-use permission "
            f"{assessment.intended_use_permission_status.value} over the notices "
            "delivered with the package, and a licence activated through the "
            "vendor's own route. Redistribution is "
            f"{redistribution_record().decision.value}, which changes nothing: "
            "fpbench redistributes nothing"
        ),
    )


# ------------------------------------------------------------------- gate 4


def _gate_canonical500_input_route() -> GateResult:
    """G4. Can ``canonical_500`` enter through an official route unchanged?

    The benchmark's images are 8-bit grayscale PNGs at 500 PPI. Public material
    says IDKit takes BMP or raw images, so the likely route is a decode into the
    identical gray8 matrix and the official raw-buffer API — which is permitted
    exactly as far as the pixels are proved identical, and no further. A decode
    that changed one pixel would be fpbench choosing a preprocessing step and
    calling it a file format.
    """
    gate = frozen.PreflightGate.CANONICAL500_INPUT_ROUTE
    route = _inspection_section("input_route") or {}
    if not route:
        return _input_failure(
            gate,
            frozen.BlockerCode.CANONICAL500_INPUT_ROUTE_UNRESOLVED,
            (
                "no input route has been recorded for the delivered package: "
                "whether it reads the benchmark's PNG directly, or takes a raw "
                "buffer, is unknown"
            ),
        )
    applied = tuple(
        str(item)
        for item in route.get("fpbench_preprocessing_applied", ())
        if str(item) in frozen.REFUSED_PREPROCESSING
    )
    if applied or bool(route.get("fpbench_preprocessing_required")):
        return _input_failure(
            gate,
            frozen.BlockerCode.FPBENCH_PREPROCESSING_CHOICE_REQUIRED,
            (
                "the route needs fpbench to change the pixels before the SDK sees "
                f"them: {list(applied) or 'unspecified preprocessing'}. Every one "
                "of these decides part of the score, and choosing one would make "
                "this a benchmark of fpbench's image processing"
            ),
        )
    accepts_png = bool(route.get("reads_png_directly"))
    if not accepts_png:
        if not bool(route.get("raw_buffer_api_available")):
            return _input_failure(
                gate,
                frozen.BlockerCode.CANONICAL500_INPUT_ROUTE_UNRESOLVED,
                (
                    "the delivered package reads neither the benchmark's PNG nor "
                    "a raw gray8 buffer through an official API, so there is no "
                    "route from canonical_500 that does not go through a "
                    "conversion fpbench would have to choose"
                ),
            )
        unproved = tuple(
            requirement
            for requirement, key in zip(
                frozen.DECODE_EQUIVALENCE_REQUIREMENTS,
                (
                    "decode_is_lossless_and_deterministic",
                    "dimensions_unchanged",
                    "pixel_format_unchanged",
                    "every_pixel_identical",
                ),
            )
            if not bool(route.get(key))
        )
        if unproved:
            return _input_failure(
                gate,
                frozen.BlockerCode.CANONICAL500_INPUT_ROUTE_UNRESOLVED,
                (
                    "the raw-buffer route is available and the decode has not "
                    f"been proved equivalent: {list(unproved)}"
                ),
            )
    if not bool(route.get("dpi_set_before_extraction")):
        return _input_failure(
            gate,
            frozen.BlockerCode.CANONICAL500_INPUT_ROUTE_UNRESOLVED,
            (
                f"the route does not declare {frozen.REQUIRED_INPUT_DPI} DPI "
                "before extraction. Setting it afterwards sets it for the next "
                "template and leaves the one already built carrying whatever was "
                "in force at the time"
            ),
        )
    return GateResult(
        gate=gate,
        status=frozen.GateStatus.PASS,
        summary=(
            (
                "the delivered package reads the benchmark's PNG through its own "
                "loader"
                if accepts_png
                else "the benchmark's PNG is decoded losslessly into the identical "
                "gray8 matrix and handed to the official raw-buffer API, with "
                "every pixel proved identical"
            )
            + f", and {frozen.REQUIRED_INPUT_DPI} DPI is declared before each "
            f"extraction. All {len(frozen.REFUSED_PREPROCESSING)} refused "
            "preprocessing steps stay refused, and whatever the SDK does to the "
            "pixels internally is the algorithm under test"
        ),
    )


def _input_failure(
    gate: frozen.PreflightGate, code: frozen.BlockerCode, evidence: str
) -> GateResult:
    return GateResult(
        gate=gate,
        status=frozen.GateStatus.FAIL,
        blockers=(
            Blocker(
                gate=gate,
                blocker_code=code,
                affected_component="the canonical_500 input route",
                evidence=f"input-route.json: {evidence}",
                why_this_blocks_algorithm_5=(
                    "The benchmark's four existing algorithms all see the same "
                    "pixels. An algorithm that saw different ones would be "
                    "compared against them on a different input, and the "
                    "comparison would be measuring the difference in the input"
                ),
                how_this_would_be_lifted=(
                    "An official route in the delivered package that takes the "
                    "benchmark's image unchanged — its own PNG loader, or a raw "
                    "buffer API fed by a decode proved identical pixel for pixel"
                ),
            ),
        ),
        summary=evidence,
    )


# ------------------------------------------------------------------- gate 5


def _gate_single_finger_extraction_profile() -> GateResult:
    """G5. One image in, one single-finger proprietary representation out.

    The gate where this candidate is most likely to fail, and the reason is
    structural rather than accidental: IDKit organises fingerprints into user
    records, and a record holding several fingers is scored by summing
    per-position maxima. That number is not a single-finger similarity and cannot
    be recovered from one. If the API can only be driven through records, each
    record here holds exactly one fingerprint — and if that cannot be guaranteed,
    this gate fails rather than being satisfied approximately.
    """
    gate = frozen.PreflightGate.SINGLE_FINGER_EXTRACTION_PROFILE
    profile = _inspection_section("representation") or {}
    if not profile:
        return _extraction_failure(
            gate,
            frozen.BlockerCode.SINGLE_FINGER_EXTRACTION_ROUTE_UNRESOLVED,
            "no representation profile has been recorded for the delivered package",
        )
    try:
        representation = frozen.RepresentationType(
            str(profile.get("representation_type", ""))
        )
    except ValueError:
        representation = frozen.RepresentationType.UNRESOLVED
    if representation is frozen.RepresentationType.UNRESOLVED:
        return _extraction_failure(
            gate,
            frozen.BlockerCode.SINGLE_FINGER_EXTRACTION_ROUTE_UNRESOLVED,
            "the compared representation has not been resolved",
        )
    if representation is not frozen.RepresentationType.VENDOR_PROPRIETARY_TEMPLATE:
        return _extraction_failure(
            gate,
            frozen.BlockerCode.SINGLE_FINGER_EXTRACTION_ROUTE_UNRESOLVED,
            (
                f"the route compares {representation.value}. The product under "
                "test generates the vendor's proprietary template, and a "
                "standardised export is a different matching scenario with its "
                "own accuracy — choosing one because it is easier to handle "
                "would benchmark a different algorithm under this one's name"
            ),
        )
    if not bool(profile.get("one_fingerprint_per_record_guaranteed")):
        return _extraction_failure(
            gate,
            frozen.BlockerCode.SINGLE_FINGER_EXTRACTION_ROUTE_UNRESOLVED,
            (
                "the delivered API cannot be driven so that each compared record "
                "holds exactly one fingerprint. A consolidated multi-finger score "
                "sums per-position maxima and is not the quantity this benchmark "
                "compares"
            ),
        )
    unresolved = _unresolved_settings(_inspection_rows("extraction_settings"))
    if unresolved:
        return _extraction_failure(
            gate,
            frozen.BlockerCode.EXTRACTION_PROFILE_UNRESOLVED,
            (
                f"{len(unresolved)} score-affecting extraction settings have no "
                f"upstream provenance behind a value: {list(unresolved)}"
            ),
        )
    rows = _inspection_rows("extraction_settings")
    return GateResult(
        gate=gate,
        status=frozen.GateStatus.PASS,
        summary=(
            f"one image produces one {representation.value}, each compared record "
            f"holds exactly one fingerprint, and {len(rows)} extraction settings "
            "are inventoried with an upstream provenance behind every "
            f"score-affecting value. None of the "
            f"{len(frozen.REFUSED_MULTI_FINGER_CONSTRUCTIONS)} refused multi-finger "
            "constructions is involved"
        ),
    )


def _extraction_failure(
    gate: frozen.PreflightGate, code: frozen.BlockerCode, evidence: str
) -> GateResult:
    return GateResult(
        gate=gate,
        status=frozen.GateStatus.FAIL,
        blockers=(
            Blocker(
                gate=gate,
                blocker_code=code,
                affected_component="the single-finger extraction route",
                evidence=f"fingerprint-route-profile.json: {evidence}",
                why_this_blocks_algorithm_5=(
                    "This benchmark compares one fingerprint against one "
                    "fingerprint. A representation built from several, or a "
                    "representation nobody identified, is not that comparison, "
                    "and a score computed over it cannot be placed beside the "
                    "four algorithms that did make it"
                ),
                how_this_would_be_lifted=(
                    "An official route in the delivered package that extracts one "
                    "single-finger proprietary representation per image, and a "
                    "recorded value with an upstream provenance for every setting "
                    "that can change it"
                ),
            ),
        ),
        summary=evidence,
    )


# ------------------------------------------------------------------- gate 6


def _gate_single_finger_matcher_raw_score() -> GateResult:
    """G6. One probe, one gallery, one scalar — and no threshold inside it.

    The decisive gate. A decision is not a score, a candidate list filtered by a
    threshold is not a score, and a score the API surrenders only above a
    threshold is not a raw score either. The last case has an obvious workaround
    and this stage refuses it: setting the threshold to zero to make the numbers
    appear is a decision layer with its knob turned down, and the benchmark's own
    decision layer belongs to a later stage.
    """
    gate = frozen.PreflightGate.SINGLE_FINGER_MATCHER_RAW_SCORE
    contract = _inspection_section("score_contract") or {}
    if not contract:
        return _matcher_failure(
            gate,
            frozen.BlockerCode.RAW_SCORE_ROUTE_UNRESOLVED,
            "no score contract has been recorded for the delivered package",
        )
    try:
        route = frozen.ScoreRouteStatus(str(contract.get("route_status", "")))
    except ValueError:
        route = frozen.ScoreRouteStatus.UNRESOLVED
    if not route.is_raw_score:
        return _matcher_failure(
            gate,
            frozen.BlockerCode.RAW_SCORE_ROUTE_UNRESOLVED,
            (
                f"the matcher route is {route.value}. "
                f"{list(frozen.INSUFFICIENT_SCORE_SHAPES)} are not raw scores, and "
                f"neither is a number obtained by {frozen.REFUSED_THRESHOLD_MANIPULATION}"
            ),
        )
    if bool(contract.get("threshold_applied_inside_the_score")):
        return _matcher_failure(
            gate,
            frozen.BlockerCode.RAW_SCORE_ROUTE_UNRESOLVED,
            (
                "the returned number has a decision inside it. The threshold "
                "belongs to this benchmark's decision layer, in a later stage, "
                "and a score that already carries one cannot be given a different "
                "threshold afterwards"
            ),
        )
    missing = tuple(
        requirement
        for requirement in frozen.SCORE_CONTRACT_REQUIREMENTS
        if not str(contract.get(requirement, "")).strip()
    )
    if missing:
        return _matcher_failure(
            gate,
            frozen.BlockerCode.RAW_SCORE_ROUTE_UNRESOLVED,
            f"the score contract leaves {list(missing)} unrecorded",
        )
    transformation = str(contract.get("fpbench_score_transformation", "")).strip()
    if transformation != frozen.FPBENCH_SCORE_TRANSFORMATION:
        return _matcher_failure(
            gate,
            frozen.BlockerCode.RAW_SCORE_ROUTE_UNRESOLVED,
            (
                f"the route applies {transformation!r} to the native score. The "
                "vendor's own scale may already be a transformation of a claimed "
                "FAR — that is part of what the algorithm reports — and a second "
                "transformation here would be this project's"
            ),
        )
    unresolved = _unresolved_settings(_inspection_rows("matcher_settings"))
    if unresolved:
        return _matcher_failure(
            gate,
            frozen.BlockerCode.MATCHER_PROFILE_UNRESOLVED,
            (
                f"{len(unresolved)} score-affecting matcher settings have no "
                f"upstream provenance behind a value: {list(unresolved)}"
            ),
        )
    rows = _inspection_rows("matcher_settings")
    return GateResult(
        gate=gate,
        status=frozen.GateStatus.PASS,
        summary=(
            f"{route.value}: one {contract.get('numeric_type')} per comparison "
            f"from {contract.get('exact_api_or_method')}, "
            f"{contract.get('direction')}, readable independently of the decision "
            f"— {contract.get('threshold_relationship')}. "
            f"{len(rows)} matcher settings are inventoried with an upstream "
            "provenance behind every score-affecting value, and fpbench applies "
            f"{frozen.FPBENCH_SCORE_TRANSFORMATION} transformation in either "
            "direction"
        ),
    )


def _matcher_failure(
    gate: frozen.PreflightGate, code: frozen.BlockerCode, evidence: str
) -> GateResult:
    return GateResult(
        gate=gate,
        status=frozen.GateStatus.FAIL,
        blockers=(
            Blocker(
                gate=gate,
                blocker_code=code,
                affected_component="the 1:1 matcher and its raw score",
                evidence=f"score-contract.json: {evidence}",
                why_this_blocks_algorithm_5=(
                    "Every downstream layer this benchmark has — thresholds, "
                    "decisions, rates, comparisons against four other algorithms "
                    "— is built on a raw per-pair scalar. Without one there is "
                    "nothing to build them on, and a candidate that only answers "
                    "match or no-match answers a question this benchmark does not "
                    "ask"
                ),
                how_this_would_be_lifted=(
                    "An official API in the delivered package that returns the "
                    "similarity for a single probe against a single gallery, "
                    "whatever the decision would have been, with every setting "
                    "behind it recorded"
                ),
            ),
        ),
        summary=evidence,
    )


# ------------------------------------------------------------------- gate 7


def _gate_score_affecting_settings_closure() -> GateResult:
    """G7. Is every external control that can move the score frozen?

    G5 and G6 said the route exists. This asks whether anything outside it can
    still change what it returns. A knob whose value and default are both unknown
    is a hidden score-affecting default, and the honest thing to do with one is
    fail — because the alternative is publishing a profile called frozen while
    part of what decides the score is unrecorded.
    """
    gate = frozen.PreflightGate.SCORE_AFFECTING_SETTINGS_CLOSURE
    closure = _inspection_section("settings_closure") or {}
    rows = (
        *_inspection_rows("extraction_settings"),
        *_inspection_rows("matcher_settings"),
    )
    unresolved = _unresolved_settings(rows)
    unclosed = tuple(
        family
        for family in frozen.SETTINGS_CLOSURE_FAMILIES
        if not bool(closure.get(family))
    )
    if unresolved or unclosed:
        detail = []
        if unresolved:
            detail.append(
                f"{len(unresolved)} score-affecting settings carry no upstream "
                f"provenance: {list(unresolved)}"
            )
        if unclosed:
            detail.append(
                f"{len(unclosed)} of the "
                f"{len(frozen.SETTINGS_CLOSURE_FAMILIES)} control families have "
                f"not been closed over: {list(unclosed)}"
            )
        evidence = "; ".join(detail)
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.FAIL,
            blockers=(
                Blocker(
                    gate=gate,
                    blocker_code=(
                        frozen.BlockerCode.HIDDEN_SCORE_AFFECTING_DEFAULT_UNRESOLVED
                    ),
                    affected_component="the settings closure over the whole route",
                    evidence=evidence,
                    why_this_blocks_algorithm_5=(
                        "A setting nobody recorded still decides the score. A run "
                        "produced under an unrecorded default cannot be "
                        "reproduced, and a difference between this algorithm and "
                        "another could be a difference between two defaults"
                    ),
                    how_this_would_be_lifted=(
                        "Read each value off the constructed engine and record it "
                        "as a DELIVERED_RUNTIME_DEFAULT, or cite the "
                        "version-matched documentation or the official sample "
                        "that states it. What is refused is choosing a value "
                        "because it produced fewer failures on this project's "
                        "fingerprints"
                    ),
                ),
            ),
            summary=evidence,
        )
    return GateResult(
        gate=gate,
        status=frozen.GateStatus.PASS,
        summary=(
            f"{len(rows)} settings across "
            f"{len(frozen.SETTINGS_CLOSURE_FAMILIES)} control families are frozen, "
            "every score-affecting one with an upstream provenance. No value was "
            "chosen by fpbench on the strength of what it did to the numbers"
        ),
    )


# ------------------------------------------------------------------- gate 8


def _gate_pair_self_determinism_failures() -> GateResult:
    """G8. What a bounded local run on non-SD300 fixtures actually found.

    Four questions in one gate because one run answers all four: both pair
    orientations, SELF from two independent extractions, the same score again on
    repeat and on restart, and a failure that arrives as a status rather than as
    a number.

    Asymmetry is expected here rather than feared. The vendor states the matcher
    is not commutative, so both orderings are run to publish that they can
    differ — and the frozen binding is applied to every pair regardless, because
    a maximum or an average would hide exactly the thing that was just measured
    (docs/adr/0109).
    """
    gate = frozen.PreflightGate.PAIR_SELF_DETERMINISM_FAILURES
    record = _cached("qualification", qualification_record)
    if record is None:
        return _qualification_failure(
            gate,
            frozen.BlockerCode.LOCAL_SMOKE_FAILED,
            (
                "no qualification run by the delivered SDK is present. A record "
                "produced by the fake engine proves the harness and answers no "
                "gate"
            ),
        )
    if str(record.get("status")) != frozen.QualificationOutcome.SUCCESS.value:
        return _qualification_failure(
            gate,
            frozen.BlockerCode.LOCAL_SMOKE_FAILED,
            (
                f"a qualification run reached {record.get('failed_at_pass')!r} and "
                f"failed there: {record.get('failure_detail')}. The runtime had "
                "started, so this is an observation about the route rather than "
                "an outstanding chore"
            ),
        )
    orientation = record.get("pair_orientation")
    if not isinstance(orientation, Mapping) or not orientation.get(
        "both_orderings_produced_a_score"
    ):
        return _qualification_failure(
            gate,
            frozen.BlockerCode.PAIR_ROLE_SEMANTICS_UNRESOLVED,
            "both orderings were not scored, so the role semantics are unobserved",
        )
    self_semantics = record.get("self_semantics")
    if not isinstance(self_semantics, Mapping) or not self_semantics.get(
        "score_present"
    ):
        return _qualification_failure(
            gate,
            frozen.BlockerCode.LOCAL_SMOKE_FAILED,
            "SELF(A, A) produced no score from two independent extractions",
        )
    determinism = record.get("determinism")
    failed_levels = sorted(
        level
        for level in frozen.DETERMINISM_LEVELS
        if not (isinstance(determinism, Mapping) and determinism.get(level))
    )
    if failed_levels:
        return _qualification_failure(
            gate,
            frozen.BlockerCode.SCORE_NONDETERMINISM_OBSERVED,
            (
                f"the same comparison produced a different score at {failed_levels}. "
                "No seed is forced unless upstream documents a deterministic mode "
                "of its own, so deliberate nondeterminism with no reproducible "
                "mode is a refusal for this benchmark"
            ),
        )
    failures = record.get("failure_semantics")
    scored_failures = tuple(
        str(item.get("cause"))
        for item in (failures if isinstance(failures, Sequence) else ())
        if isinstance(item, Mapping) and item.get("produced_a_score")
    )
    if scored_failures:
        return _qualification_failure(
            gate,
            frozen.BlockerCode.LOCAL_SMOKE_FAILED,
            (
                f"{list(scored_failures)} produced a score instead of a status. A "
                "failure that arrives as a number enters the benchmark as a very "
                "poor match and no metric can tell the two apart"
            ),
        )
    symmetric = orientation.get("score_digests_equal")
    return GateResult(
        gate=gate,
        status=frozen.GateStatus.PASS,
        summary=(
            f"{record.get('scoring_comparisons')} score-producing comparisons on "
            f"{record.get('fixture_kind')} fixtures, inside the ceiling of "
            f"{frozen.QUALIFICATION_MAX_SCORING_COMPARISONS}. Both orderings "
            "scored and their digests "
            + ("agree" if symmetric else "differ, as the vendor documents")
            + f"; the frozen binding {dict(frozen.PAIR_ROLE_BINDING)} is applied "
            "regardless. SELF scored from two independent extractions, the score "
            f"repeated at all {len(frozen.DETERMINISM_LEVELS)} determinism levels "
            "including a process restart, and "
            f"{len(failures) if isinstance(failures, Sequence) else 0} provoked "
            "failure causes each arrived as a status rather than a number"
        ),
    )


def _qualification_failure(
    gate: frozen.PreflightGate, code: frozen.BlockerCode, evidence: str
) -> GateResult:
    return GateResult(
        gate=gate,
        status=frozen.GateStatus.FAIL,
        blockers=(
            Blocker(
                gate=gate,
                blocker_code=code,
                affected_component="the bounded local qualification run",
                evidence=f"qualification-run.json: {evidence}",
                why_this_blocks_algorithm_5=(
                    "A route that will not survive twenty comparisons on fixtures "
                    "nobody chose for it will not survive six thousand, and every "
                    "downstream number would inherit whatever went wrong"
                ),
                how_this_would_be_lifted=(
                    "Diagnose the recorded pass, fix the cause if it is this "
                    "project's, and re-run the qualification. If the cause is "
                    "upstream's, that is the finding and the candidate is refused "
                    "on it"
                ),
            ),
        ),
        summary=evidence,
    )


# ------------------------------------------------------------------- gate 9


def _gate_workload_runtime_feasibility() -> GateResult:
    """G9. Does the licence in hand cover the run, and does the run fit in it?

    Not "is there a quota". A quota nobody looked for is the quota that stops the
    benchmark at comparison four thousand, so the entitlement is read off the
    licence that was actually issued and the arithmetic is done against the
    frozen workload rather than against an impression of it.
    """
    gate = frozen.PreflightGate.WORKLOAD_RUNTIME_FEASIBILITY
    licence = _inspection_section("license") or {}
    workload = frozen.FROZEN_WORKLOAD
    unanswered = tuple(
        question
        for question in frozen.LICENSE_CAPACITY_QUESTIONS
        if question not in licence
    )
    if unanswered:
        return _workload_failure(
            gate,
            (
                f"{len(unanswered)} of the "
                f"{len(frozen.LICENSE_CAPACITY_QUESTIONS)} licence-capacity "
                f"questions are unanswered: {list(unanswered)}. Absence of a "
                "public statement about a quota is not evidence that there is none"
            ),
        )
    quota = licence.get("quota_or_transaction_limits")
    if quota is not None:
        try:
            allowed = int(quota)
        except (TypeError, ValueError):
            return _workload_failure(
                gate, f"the recorded transaction quota {quota!r} is not a number"
            )
        if allowed < workload.total_matcher_invocations:
            return _workload_failure(
                gate,
                (
                    f"the licence allows {allowed} transactions and the frozen "
                    f"workload needs {workload.total_matcher_invocations} matcher "
                    f"invocations over {workload.total_extractions} extractions"
                ),
            )
    runtime = _cached("qualification", qualification_record)
    if runtime is None or not isinstance(runtime.get("runtime"), Mapping):
        return _workload_failure(
            gate,
            (
                "no runtime measurement exists, so whether 6,000 jobs fit inside "
                "the licence's life is unknown"
            ),
        )
    measured = runtime["runtime"]
    return GateResult(
        gate=gate,
        status=frozen.GateStatus.PASS,
        summary=(
            f"the licence covers {workload.comparison_attempts} comparison "
            f"attempts, {workload.total_extractions} independent extractions and "
            f"{workload.total_matcher_invocations} matcher invocations including "
            f"the qualification allowance of {workload.qualification_allowance}; "
            f"all {len(frozen.LICENSE_CAPACITY_QUESTIONS)} capacity questions are "
            f"answered from the issued licence. One comparison measured "
            f"{measured.get('end_to_end_seconds')}s end to end after "
            f"{measured.get('startup_seconds')}s of startup, which is a "
            "feasibility check and not a performance comparison"
        ),
    )


def _workload_failure(gate: frozen.PreflightGate, evidence: str) -> GateResult:
    return GateResult(
        gate=gate,
        status=frozen.GateStatus.FAIL,
        blockers=(
            Blocker(
                gate=gate,
                blocker_code=frozen.BlockerCode.LICENSE_WORKLOAD_INSUFFICIENT,
                affected_component="the issued licence and the frozen workload",
                evidence=evidence,
                why_this_blocks_algorithm_5=(
                    "A benchmark run that stops halfway produces a partial result "
                    "set, and a partial result set cannot be compared with four "
                    "complete ones. The time to discover a quota is before the "
                    "run, not during it (docs/adr/0096)"
                ),
                how_this_would_be_lifted=(
                    "Read the entitlement off the issued licence and record it, "
                    "or obtain one whose capacity covers the workload. Splitting "
                    "the run across several licences is not among the responses"
                ),
            ),
        ),
        summary=evidence,
    )


# ------------------------------------------------------------------ gate 10


def _gate_training_provenance() -> GateResult:
    """G10. Was this algorithm built on the benchmark's own evaluation data?

    The standard is the one Algorithm 4 was held to and no higher. A vendor
    letter denying SD300 use would be stronger evidence and is not a
    prerequisite: what is required is that a search was made across training,
    validation, model selection, calibration and development testing, and that
    nothing was found. A positive finding fails the candidate outright.
    """
    gate = frozen.PreflightGate.TRAINING_PROVENANCE
    provenance = _inspection_section("training_provenance") or {}
    try:
        overlap = frozen.SD300OverlapStatus(str(provenance.get("sd300_overlap_status", "")))
    except ValueError:
        overlap = frozen.SD300OverlapStatus.NOT_REACHED
    if overlap is frozen.SD300OverlapStatus.OVERLAP_FOUND:
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.FAIL,
            blockers=(
                Blocker(
                    gate=gate,
                    blocker_code=frozen.BlockerCode.SD300_TRAINING_OVERLAP_FOUND,
                    affected_component="the released IDKit fingerprint model",
                    evidence=(
                        "training-provenance.json: "
                        f"{provenance.get('overlap_evidence', 'an overlap was found')}"
                    ),
                    why_this_blocks_algorithm_5=(
                        "A benchmark whose algorithm was built on its own "
                        "evaluation set reports the algorithm's memory rather "
                        "than its accuracy, and the number would be wrong in the "
                        "flattering direction"
                    ),
                    how_this_would_be_lifted=(
                        "It would not be. A released model that saw SD300 in "
                        "training, validation, model selection, calibration or "
                        "development testing cannot be evaluated on SD300, and no "
                        "amount of care downstream repairs it"
                    ),
                ),
            ),
            summary="SD300 overlap was found",
        )
    if overlap is frozen.SD300OverlapStatus.NOT_REACHED:
        return GateResult(
            gate=gate,
            status=frozen.GateStatus.FAIL,
            blockers=(
                Blocker(
                    gate=gate,
                    blocker_code=frozen.BlockerCode.SD300_TRAINING_OVERLAP_FOUND,
                    affected_component="the released IDKit fingerprint model",
                    evidence=(
                        "training-provenance.json: no search has been recorded "
                        f"across the {len(frozen.SD300_OVERLAP_SURFACES)} surfaces "
                        "an evaluation set can leak through"
                    ),
                    why_this_blocks_algorithm_5=(
                        "'Nobody looked' and 'we looked and found nothing' are "
                        "different claims, and only the second one is evidence"
                    ),
                    how_this_would_be_lifted=(
                        "Search the vendor's public material and any technical "
                        "documentation delivered with the package for SD300 use "
                        "across training, validation, model selection, "
                        "calibration and development testing, and record the "
                        "result as NO_EVIDENCE_FOUND — or obtain an explicit "
                        "statement from the vendor, which would be stronger"
                    ),
                ),
            ),
            summary="no SD300 overlap search has been recorded",
        )
    try:
        status = frozen.TrainingProvenanceStatus(
            str(provenance.get("training_provenance_status", ""))
        )
    except ValueError:
        status = frozen.TrainingProvenanceStatus.PROPRIETARY_UNDISCLOSED
    return GateResult(
        gate=gate,
        status=frozen.GateStatus.PASS,
        summary=(
            f"{status.value} with overlap status {overlap.value}: a search across "
            f"{len(frozen.SD300_OVERLAP_SURFACES)} surfaces turned up no positive "
            "evidence that the released model saw SD300. The standard is the one "
            "Algorithm 4 was held to; a vendor denial would be stronger and is not "
            "a prerequisite"
        ),
    )


_GATE_RUNNERS = {
    frozen.PreflightGate.ACQUISITION_ACCESS: _gate_acquisition_access,
    frozen.PreflightGate.PACKAGE_RUNTIME_IDENTITY: _gate_package_runtime_identity,
    frozen.PreflightGate.RESEARCH_USE_AND_LICENSE: _gate_research_use_and_license,
    frozen.PreflightGate.CANONICAL500_INPUT_ROUTE: _gate_canonical500_input_route,
    frozen.PreflightGate.SINGLE_FINGER_EXTRACTION_PROFILE: (
        _gate_single_finger_extraction_profile
    ),
    frozen.PreflightGate.SINGLE_FINGER_MATCHER_RAW_SCORE: (
        _gate_single_finger_matcher_raw_score
    ),
    frozen.PreflightGate.SCORE_AFFECTING_SETTINGS_CLOSURE: (
        _gate_score_affecting_settings_closure
    ),
    frozen.PreflightGate.PAIR_SELF_DETERMINISM_FAILURES: (
        _gate_pair_self_determinism_failures
    ),
    frozen.PreflightGate.WORKLOAD_RUNTIME_FEASIBILITY: (
        _gate_workload_runtime_feasibility
    ),
    frozen.PreflightGate.TRAINING_PROVENANCE: _gate_training_provenance,
}


# ------------------------------------------------------------------ the whole


@dataclass(frozen=True, slots=True)
class IdkitPreflight:
    """The whole preflight: every gate, the verdict, and the outcome."""

    results: tuple[GateResult, ...]
    stopped_at: frozen.PreflightGate | None
    paused_at: frozen.PreflightGate | None
    preflight_fingerprint: str

    def __post_init__(self) -> None:
        seen = tuple(result.gate for result in self.results)
        if seen != frozen.GATE_ORDER:
            raise IdkitGateError(
                f"the gates were reported as {seen} and the frozen order is "
                f"{frozen.GATE_ORDER}"
            )
        failed = [
            result.gate
            for result in self.results
            if result.status is frozen.GateStatus.FAIL
        ]
        pending = [
            result.gate
            for result in self.results
            if result.status is frozen.GateStatus.PENDING
        ]
        if len(failed) > 1:
            raise IdkitGateError(
                f"fail-fast means one failing gate, and these failed: {failed}"
            )
        if failed and failed[0] is not self.stopped_at:
            raise IdkitGateError(
                f"the stopping gate is {self.stopped_at} and the failing gate is "
                f"{failed[0]}"
            )
        if not failed and self.stopped_at is not None:
            raise IdkitGateError(f"stopped at {self.stopped_at} with no failing gate")
        if len(pending) > 1:
            raise IdkitGateError(
                f"only acquisition may pend, and these pended: {pending}"
            )
        if pending and pending[0] is not self.paused_at:
            raise IdkitGateError(
                f"the pausing gate is {self.paused_at} and the pending gate is "
                f"{pending[0]}"
            )
        if not pending and self.paused_at is not None:
            raise IdkitGateError(f"paused at {self.paused_at} with no pending gate")
        if failed and pending:
            raise IdkitGateError(
                "a run that failed did not also pause: a failure is a finding "
                "about the candidate and a pause is a finding about nothing"
            )

    @property
    def passed(self) -> bool:
        """Every gate passed. Not "no gate failed": NOT_REACHED is not a pass."""
        return all(
            result.status is frozen.GateStatus.PASS for result in self.results
        )

    @property
    def is_pending(self) -> bool:
        return self.paused_at is not None

    @property
    def outcome(self) -> str:
        if self.passed:
            return frozen.STAGE_12A_PASS_OUTCOME
        if self.is_pending:
            return frozen.STAGE_12A_PENDING_OUTCOME
        return frozen.STAGE_12A_FAIL_OUTCOME

    @property
    def opens_stage_12b(self) -> bool:
        return self.passed

    @property
    def failure_class(self) -> frozen.FailureClass | None:
        """What kind of failure this is, derived from the blocker that stopped it.

        ``IDKIT_PREFLIGHT_FAIL`` reads the same whether the vendor refused the
        package or the delivered API had no per-pair score, and those are very
        different results for anybody deciding what to do next.
        """
        if self.passed or self.is_pending:
            return None
        codes = {blocker.blocker_code for blocker in self.blockers}
        if frozen.BlockerCode.ACCESS_REFUSED_BY_VENDOR in codes:
            return frozen.FailureClass.VENDOR_ACCESS_REFUSED
        if frozen.BlockerCode.OFFICIAL_PACKAGE_UNAVAILABLE in codes:
            return frozen.FailureClass.PACKAGE_UNAVAILABLE_FOR_TARGET
        if frozen.BlockerCode.RESEARCH_USE_BLOCKED in codes:
            return frozen.FailureClass.RESEARCH_USE_BLOCKED
        if codes & {
            frozen.BlockerCode.LICENSE_ACTIVATION_FAILED,
            frozen.BlockerCode.LICENSE_WORKLOAD_INSUFFICIENT,
        }:
            return frozen.FailureClass.LICENSE_INSUFFICIENT
        if frozen.BlockerCode.SD300_TRAINING_OVERLAP_FOUND in codes:
            return frozen.FailureClass.TRAINING_OVERLAP
        return frozen.FailureClass.ROUTE_NOT_QUALIFIABLE

    @property
    def sd300_overlap_status(self) -> frozen.SD300OverlapStatus:
        if (
            self.status(frozen.PreflightGate.TRAINING_PROVENANCE)
            is not frozen.GateStatus.PASS
        ):
            return frozen.SD300OverlapStatus.NOT_REACHED
        return frozen.SD300OverlapStatus.NO_EVIDENCE_FOUND

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
    def blockers(self) -> tuple[Blocker, ...]:
        return tuple(
            sorted(
                (blocker for result in self.results for blocker in result.blockers),
                key=lambda item: item.blocker_code.value,
            )
        )

    @property
    def pending_reason(self) -> PendingReason | None:
        for result in self.results:
            if result.pending is not None:
                return result.pending
        return None

    def result(self, gate: frozen.PreflightGate) -> GateResult:
        for item in self.results:
            if item.gate is gate:
                return item
        raise KeyError(gate)  # pragma: no cover - GATE_ORDER is exhaustive

    def status(self, gate: frozen.PreflightGate) -> frozen.GateStatus:
        return self.result(gate).status


def run_preflight() -> IdkitPreflight:
    """Run the gate order, and stop at the first failure or pause."""
    _RUN_CACHE.clear()
    results: list[GateResult] = []
    stopped_at: frozen.PreflightGate | None = None
    paused_at: frozen.PreflightGate | None = None
    for gate in frozen.GATE_ORDER:
        if stopped_at is not None or paused_at is not None:
            results.append(
                GateResult(
                    gate=gate,
                    status=frozen.GateStatus.NOT_REACHED,
                    summary=_not_reached_reason(
                        stopped_at or paused_at,  # type: ignore[arg-type]
                        paused_at is not None,
                    ),
                )
            )
            continue
        runner = _GATE_RUNNERS[gate]
        result = runner()
        results.append(result)
        if result.status is frozen.GateStatus.FAIL:
            stopped_at = gate
        elif result.status is frozen.GateStatus.PENDING:
            paused_at = gate
    return IdkitPreflight(
        results=tuple(results),
        stopped_at=stopped_at,
        paused_at=paused_at,
        preflight_fingerprint=stable_hash(
            {
                "schema": "stage_12a_preflight_v1",
                "candidate_id": frozen.CANDIDATE_ID,
                "gates": [
                    (result.gate.value, result.status.value) for result in results
                ],
                "blockers": sorted(
                    blocker.blocker_code.value
                    for result in results
                    for blocker in result.blockers
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
    list. Both are refusals — this returns them so that a test can assert on the
    finding, and :func:`require_no_sensitive_material` is the raising form.
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
    """The raising form, for the reader and for the publisher.

    Raises:
        IdkitSensitiveEvidenceError: the document carries something shaped like
            licence material. Nothing is redacted: a redaction that silently
            succeeds is how the second one gets missed.
    """
    findings = find_sensitive_material(node)
    if findings:
        raise IdkitSensitiveEvidenceError(
            f"{where} carries licence material and will not be used: "
            f"{list(findings)}"
        )


# --------------------------------------------------------- published documents


def _gate_rows(preflight: IdkitPreflight) -> tuple[Mapping[str, Any], ...]:
    return tuple(
        {
            "gate": result.gate.value,
            "status": result.status.value,
            "summary": result.summary,
            "documents": list(frozen.gate_documents(result.gate)),
            "blockers": [item.blocker_code.value for item in result.blockers],
        }
        for result in preflight.results
    )


def _gate_status(preflight: IdkitPreflight, gate: frozen.PreflightGate) -> str:
    return preflight.status(gate).value


def predecessor_binding_document(preflight: IdkitPreflight) -> Mapping[str, Any]:
    """What this stage rests on, and what it may not touch."""
    return {
        "schema": "stage_12a_predecessor_binding_v1",
        "algorithm_slot": frozen.ALGORITHM_SLOT,
        "candidate_id": frozen.CANDIDATE_ID,
        "predecessor": {
            "stage": "11B",
            "outcome": frozen.STAGE_11B_OUTCOME,
            "finalization_fingerprint": frozen.STAGE_11B_FINALIZATION_FINGERPRINT,
            "what_it_established": (
                "6,000 canonical raw 1:1 outcomes under VeriFinger 2025.2 as "
                "Algorithm 4, and a marker that opens a search for Algorithm 5"
            ),
        },
        "policy": {
            "stage": "8E",
            "outcome": frozen.STAGE8E_OUTCOME,
            "finalization_fingerprint": frozen.STAGE8E_FINALIZATION_FINGERPRINT,
            "purpose_fingerprint": frozen.STAGE8E_PURPOSE_FINGERPRINT,
            "policy_fingerprint": frozen.STAGE8E_POLICY_FINGERPRINT,
            "reused_not_reopened": True,
        },
        "stage_11a_evidence_changed": False,
        "stage_11b_evidence_changed": False,
        "stage_8e_evidence_changed": False,
        "production_algorithm_id_frozen": frozen.PRODUCTION_ALGORITHM_ID_FROZEN,
        "implementation_version": frozen.IMPLEMENTATION_VERSION_UNRESOLVED,
        "preferred_target_platform": frozen.PREFERRED_TARGET_PLATFORM,
        "platform_is_final_only_with_a_package": (
            frozen.PLATFORM_IS_FINAL_ONLY_WITH_A_PACKAGE
        ),
        "final_identity_components": list(frozen.FINAL_IDENTITY_COMPONENTS),
    }


def acquisition_status_document(preflight: IdkitPreflight) -> Mapping[str, Any]:
    """Where the attempt to obtain a package stands, and how it got there."""
    state = _acquisition()
    reason = preflight.pending_reason
    return {
        "schema": "stage_12a_acquisition_status_v1",
        "gate": frozen.PreflightGate.ACQUISITION_ACCESS.value,
        "gate_status": _gate_status(
            preflight, frozen.PreflightGate.ACQUISITION_ACCESS
        ),
        "acquisition_status": state.status.value,
        "package_presence": state.presence.value,
        "is_pending": state.is_pending,
        "is_refusal": state.is_refusal,
        "basis": state.basis,
        "walked_utc": observed.PUBLIC_OBSERVATIONS[0].retrieved_utc,
        "official_routes": [dict(row) for row in observed.route_rows()],
        "refused_route_categories": [
            {"category": category, "why_it_is_refused": detail}
            for category, detail in observed.REFUSED_ROUTES
        ],
        "refused_acquisition_sources": list(frozen.REFUSED_ACQUISITION_SOURCES),
        "official_delivery_channels": [item.value for item in frozen.DeliveryChannel],
        "what_would_change_the_status": (
            list(reason.what_is_outstanding)
            if reason is not None
            else list(observed.WHAT_WOULD_CHANGE_THE_STATUS)
        ),
        "pending_is_not_a_failure": True,
        "vendor_was_not_asked_and_did_not_refuse": state.is_pending,
    }


def package_manifest_document(preflight: IdkitPreflight) -> Mapping[str, Any]:
    """What was delivered, or what is not known because nothing was."""
    state = _acquisition()
    declaration = state.declaration
    return {
        "schema": "stage_12a_package_manifest_v1",
        "gate": frozen.PreflightGate.PACKAGE_RUNTIME_IDENTITY.value,
        "gate_status": _gate_status(
            preflight, frozen.PreflightGate.PACKAGE_RUNTIME_IDENTITY
        ),
        "identity_fields_required": list(frozen.PACKAGE_IDENTITY_FIELDS),
        "identity": dict(declaration.identity_row) if declaration else None,
        "documentation_obtained": (
            declaration.documentation_obtained if declaration else False
        ),
        "advertised_product_family": observed.ADVERTISED_PRODUCT_FAMILY.value,
        "advertised_version_indication": observed.ADVERTISED_VERSION_INDICATION,
        "advertised_version_is_authoritative": not (
            observed.ADVERTISED_VERSION_IS_NOT_AUTHORITATIVE
        ),
        "refused_product_families": [
            item.value for item in frozen.REFUSED_PRODUCT_FAMILIES
        ],
        "binding_selection_criteria": list(frozen.BINDING_SELECTION_CRITERIA),
        "selected_binding": _inspection_section("binding") or None,
        "vendor_bytes_in_repository": False,
        "public_observations": [dict(row) for row in observed.observation_rows()],
    }


def research_use_license_document(preflight: IdkitPreflight) -> Mapping[str, Any]:
    """Stage 8E's decision, or the reason there is not one."""
    inspection = _cached("inspection", package_inspection)
    assessment, refusal = _assessment_or_refusal(inspection)
    redistribution = redistribution_record()
    licence = _inspection_section("license") or {}
    return {
        "schema": "stage_12a_research_use_license_v1",
        "gate": frozen.PreflightGate.RESEARCH_USE_AND_LICENSE.value,
        "gate_status": _gate_status(
            preflight, frozen.PreflightGate.RESEARCH_USE_AND_LICENSE
        ),
        "stage8e_policy_fingerprint": frozen.STAGE8E_POLICY_FINGERPRINT,
        "stage8e_finalization_fingerprint": frozen.STAGE8E_FINALIZATION_FINGERPRINT,
        "four_separate_questions": list(frozen.LICENSE_SEPARATED_QUESTIONS),
        "package_obtainable": _acquisition().obtained,
        "research_use_decision": (
            assessment.decision.value if assessment is not None else None
        ),
        "research_use_opens_execution": (
            assessment.decision.opens_execution if assessment is not None else None
        ),
        "research_use_blocked": False,
        "third_party_components_assessed": 0 if assessment is None else 1,
        "license_activated": bool(licence.get("activated")),
        "why_no_assessment_exists": (
            None
            if assessment is not None
            else (refusal or _NO_LICENSE_EVIDENCE_YET)
        ),
        "redistribution_decision": redistribution.decision.value,
        "redistributed_by_fpbench": redistribution.redistributed_by_fpbench,
        "never_published": [
            "a licence file or its bytes",
            "portal credentials",
            "a hardware identifier",
            "a serial",
            "a customer identifier",
            "a signed download URL",
            "personal vendor correspondence",
        ],
        "license_bypass_attempted": False,
    }


def runtime_inventory_document(preflight: IdkitPreflight) -> Mapping[str, Any]:
    """Everything the fingerprint route loads, each pinned by digest."""
    components = _inspection_rows("runtime_components")
    return {
        "schema": "stage_12a_runtime_inventory_v1",
        "gate": frozen.PreflightGate.PACKAGE_RUNTIME_IDENTITY.value,
        "gate_status": _gate_status(
            preflight, frozen.PreflightGate.PACKAGE_RUNTIME_IDENTITY
        ),
        "component_classes_to_close_over": list(frozen.RUNTIME_COMPONENT_CLASSES),
        "recorded_fields": list(frozen.RUNTIME_COMPONENT_FIELDS),
        "component_count": len(components),
        "components": [dict(row) for row in components],
        "closure_complete": bool(components),
        "vendor_bytes_stay_outside_git": True,
        "artifact_store_prefix": frozen.ARTIFACT_STORE_PREFIX,
    }


def input_route_document(preflight: IdkitPreflight) -> Mapping[str, Any]:
    """How ``canonical_500`` would reach the extractor, and what stays refused."""
    route = _inspection_section("input_route") or {}
    return {
        "schema": "stage_12a_input_route_v1",
        "gate": frozen.PreflightGate.CANONICAL500_INPUT_ROUTE.value,
        "gate_status": _gate_status(
            preflight, frozen.PreflightGate.CANONICAL500_INPUT_ROUTE
        ),
        "benchmark_input": {
            "profile": frozen.BENCHMARK_INPUT_PROFILE,
            "pixels_per_inch": frozen.BENCHMARK_INPUT_PPI,
            "pixel_format": frozen.BENCHMARK_INPUT_PIXEL_FORMAT,
            "container": "PNG",
        },
        "ideal_route": list(frozen.IDEAL_INPUT_ROUTE),
        "permitted_decode_route": list(frozen.PERMITTED_DECODE_ROUTE),
        "decode_equivalence_requirements": list(
            frozen.DECODE_EQUIVALENCE_REQUIREMENTS
        ),
        "refused_preprocessing": list(frozen.REFUSED_PREPROCESSING),
        "internal_vendor_preprocessing_is_the_algorithm": (
            frozen.INTERNAL_BLACK_BOX_PREPROCESSING_IS_ACCEPTABLE
        ),
        "required_input_dpi": frozen.REQUIRED_INPUT_DPI,
        "dpi_must_be_set_before_extraction": frozen.DPI_MUST_BE_SET_BEFORE_EXTRACTION,
        "observed_route": dict(route) if route else None,
        "fpbench_preprocessing_required": bool(
            route.get("fpbench_preprocessing_required")
        ),
        "canonical500_route_resolved": _gate_status(
            preflight, frozen.PreflightGate.CANONICAL500_INPUT_ROUTE
        )
        == frozen.GateStatus.PASS.value,
    }


def fingerprint_route_profile_document(
    preflight: IdkitPreflight,
) -> Mapping[str, Any]:
    """The representation, the single-finger rule, and the extraction settings."""
    profile = _inspection_section("representation") or {}
    rows = _inspection_rows("extraction_settings")
    closure = _inspection_section("settings_closure") or {}
    return {
        "schema": "stage_12a_fingerprint_route_profile_v1",
        "gate": frozen.PreflightGate.SINGLE_FINGER_EXTRACTION_PROFILE.value,
        "gate_status": _gate_status(
            preflight, frozen.PreflightGate.SINGLE_FINGER_EXTRACTION_PROFILE
        ),
        "settings_closure_gate_status": _gate_status(
            preflight, frozen.PreflightGate.SCORE_AFFECTING_SETTINGS_CLOSURE
        ),
        "single_finger_record_rule": frozen.SINGLE_FINGER_RECORD_RULE,
        "refused_multi_finger_constructions": list(
            frozen.REFUSED_MULTI_FINGER_CONSTRUCTIONS
        ),
        "representation_facts_to_establish": list(
            frozen.REPRESENTATION_FACTS_TO_ESTABLISH
        ),
        "publishable_representation_facts": list(
            frozen.PUBLISHABLE_REPRESENTATION_FACTS
        ),
        "observed_representation": dict(profile) if profile else None,
        "setting_families_to_inventory": list(frozen.SETTING_FAMILIES_TO_INVENTORY),
        "setting_row_fields": list(frozen.SETTING_ROW_FIELDS),
        "setting_provenance_vocabulary": [
            item.value for item in frozen.SettingProvenance
        ],
        "refused_setting_provenance": frozen.REFUSED_SETTING_PROVENANCE,
        "extraction_settings": [dict(row) for row in rows],
        "unresolved_score_affecting_settings": list(_unresolved_settings(rows)),
        "settings_closure_families": list(frozen.SETTINGS_CLOSURE_FAMILIES),
        "settings_closure": dict(closure) if closure else None,
        "template_bytes_published": False,
    }


def score_contract_document(preflight: IdkitPreflight) -> Mapping[str, Any]:
    """What one comparison returns, and what fpbench does to it."""
    contract = _inspection_section("score_contract") or {}
    rows = _inspection_rows("matcher_settings")
    return {
        "schema": "stage_12a_score_contract_v1",
        "gate": frozen.PreflightGate.SINGLE_FINGER_MATCHER_RAW_SCORE.value,
        "gate_status": _gate_status(
            preflight, frozen.PreflightGate.SINGLE_FINGER_MATCHER_RAW_SCORE
        ),
        "requirements": list(frozen.SCORE_CONTRACT_REQUIREMENTS),
        "insufficient_score_shapes": list(frozen.INSUFFICIENT_SCORE_SHAPES),
        "refused_threshold_manipulation": frozen.REFUSED_THRESHOLD_MANIPULATION,
        "fpbench_score_transformation": frozen.FPBENCH_SCORE_TRANSFORMATION,
        "refused_score_transformations": list(frozen.REFUSED_SCORE_TRANSFORMATIONS),
        "observed_contract": dict(contract) if contract else None,
        "raw_score_route_resolved": _gate_status(
            preflight, frozen.PreflightGate.SINGLE_FINGER_MATCHER_RAW_SCORE
        )
        == frozen.GateStatus.PASS.value,
        "matcher_settings": [dict(row) for row in rows],
        "unresolved_score_affecting_settings": list(_unresolved_settings(rows)),
        "threshold_belongs_to_a_later_stage": True,
    }


def qualification_run_document(preflight: IdkitPreflight) -> Mapping[str, Any]:
    """What a bounded run found, or the fact that no delivered SDK has run.

    The published form of the record, not the record: the local one names a store
    path and a machine, and neither belongs in a public repository.
    """
    record = _cached("qualification", qualification_record)
    return {
        "schema": "stage_12a_qualification_run_v1",
        "gate": frozen.PreflightGate.PAIR_SELF_DETERMINISM_FAILURES.value,
        "gate_status": _gate_status(
            preflight, frozen.PreflightGate.PAIR_SELF_DETERMINISM_FAILURES
        ),
        "workload_gate_status": _gate_status(
            preflight, frozen.PreflightGate.WORKLOAD_RUNTIME_FEASIBILITY
        ),
        "pair_role_binding": {left: right for left, right in frozen.PAIR_ROLE_BINDING},
        "pair_orientation_requirements": list(frozen.PAIR_ORIENTATION_REQUIREMENTS),
        "refused_orientation_reductions": list(frozen.REFUSED_ORIENTATION_REDUCTIONS),
        "self_semantics_requirements": list(frozen.SELF_SEMANTICS_REQUIREMENTS),
        "determinism_levels": list(frozen.DETERMINISM_LEVELS),
        "failure_semantics_rule": frozen.FAILURE_SEMANTICS_RULE,
        "failure_semantics_causes": [
            {"cause": cause, "what_it_establishes": expectation}
            for cause, expectation in frozen.FAILURE_SEMANTICS_CAUSES
        ],
        "required_passes": [
            {"pass": name, "what_it_is": description}
            for name, description in frozen.QUALIFICATION_PASSES
        ],
        "max_scoring_comparisons": frozen.QUALIFICATION_MAX_SCORING_COMPARISONS,
        "permitted_fixture_sources": list(frozen.QUALIFICATION_FIXTURE_SOURCES),
        "sd300_fixtures_used": False,
        "run_by_delivered_sdk": record is not None,
        "run": _published_run(record),
        "frozen_workload": {
            "comparison_attempts": frozen.FROZEN_WORKLOAD.comparison_attempts,
            "independent_extractions": frozen.FROZEN_WORKLOAD.independent_extractions,
            "matcher_invocations": frozen.FROZEN_WORKLOAD.matcher_invocations,
            "qualification_allowance": (
                frozen.FROZEN_WORKLOAD.qualification_allowance
            ),
            "representation_cache_permitted": frozen.REPRESENTATION_CACHE_PERMITTED,
        },
        "license_capacity_questions": list(frozen.LICENSE_CAPACITY_QUESTIONS),
        "runtime_feasibility_measurements": list(
            frozen.RUNTIME_FEASIBILITY_MEASUREMENTS
        ),
    }


def _published_run(record: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    """The publishable half of a qualification record.

    Score digests are carried and score values are not, because there are none:
    the harness never writes one. What is dropped here is the local detail — the
    inputs fingerprint stays, the driver fingerprint stays, and anything that
    names this machine does not.
    """
    if record is None:
        return None
    runtime = record.get("runtime")
    return {
        "status": record.get("status"),
        "engine_kind": record.get("engine_kind"),
        "scoring_comparisons": record.get("scoring_comparisons"),
        "failed_at_pass": record.get("failed_at_pass"),
        "passes": {
            name: {
                "produced_a_score": value.get("produced_a_score"),
                "failure_status": value.get("failure_status"),
            }
            for name, value in (record.get("passes") or {}).items()
            if isinstance(value, Mapping)
        },
        "pair_orientation": record.get("pair_orientation"),
        "self_semantics": record.get("self_semantics"),
        "determinism": record.get("determinism"),
        "failure_semantics": record.get("failure_semantics"),
        "fixture_kind": record.get("fixture_kind"),
        "inputs_fingerprint": record.get("inputs_fingerprint"),
        "driver_fingerprint": record.get("driver_fingerprint"),
        "runtime": {
            key: value
            for key, value in (runtime or {}).items()
            if key
            in (
                "startup_seconds",
                "end_to_end_seconds",
                "approximate_peak_memory_kb",
                "cpu_count",
            )
        }
        if isinstance(runtime, Mapping)
        else None,
    }


def training_provenance_document(preflight: IdkitPreflight) -> Mapping[str, Any]:
    """What is known about what the released model was trained on."""
    provenance = _inspection_section("training_provenance") or {}
    reached = (
        preflight.status(frozen.PreflightGate.TRAINING_PROVENANCE)
        is not frozen.GateStatus.NOT_REACHED
    )
    return {
        "schema": "stage_12a_training_provenance_v1",
        "gate": frozen.PreflightGate.TRAINING_PROVENANCE.value,
        "gate_status": _gate_status(preflight, frozen.PreflightGate.TRAINING_PROVENANCE),
        "overlap_surfaces_searched": list(frozen.SD300_OVERLAP_SURFACES),
        "training_provenance_status": (
            str(
                provenance.get(
                    "training_provenance_status",
                    frozen.TrainingProvenanceStatus.PROPRIETARY_UNDISCLOSED.value,
                )
            )
            if reached
            else frozen.TrainingProvenanceStatus.NOT_REACHED.value
        ),
        "sd300_overlap_status": preflight.sd300_overlap_status.value,
        "sd300_training_overlap_found": (
            None
            if preflight.sd300_overlap_status is frozen.SD300OverlapStatus.NOT_REACHED
            else preflight.sd300_overlap_status
            is frozen.SD300OverlapStatus.OVERLAP_FOUND
        ),
        "standard_applied": (
            "the standard Algorithm 4 was held to: no positive evidence of SD300 "
            "use, with the status left explicitly at NO_EVIDENCE_FOUND. An "
            "explicit vendor denial would be stronger evidence and is not a "
            "prerequisite"
        ),
        "vendor_statement_obtained": bool(provenance.get("vendor_statement_obtained")),
        "observed": dict(provenance) if provenance else None,
    }


def preflight_report_document(preflight: IdkitPreflight) -> Mapping[str, Any]:
    """The whole run: every gate, the verdict, and what it does not say."""
    reason = preflight.pending_reason
    return {
        "schema": "stage_12a_preflight_report_v1",
        "candidate_id": frozen.CANDIDATE_ID,
        "algorithm_slot": frozen.ALGORITHM_SLOT,
        "implementation_origin": frozen.IMPLEMENTATION_ORIGIN,
        "implementation_version": frozen.IMPLEMENTATION_VERSION_UNRESOLVED,
        "production_algorithm_id_frozen": frozen.PRODUCTION_ALGORITHM_ID_FROZEN,
        "outcome": preflight.outcome,
        "gate_count_defined": frozen.GATE_COUNT,
        "gates_reached": preflight.gates_reached,
        "gates_passed": preflight.gates_passed,
        "stopped_at": preflight.stopped_at.value if preflight.stopped_at else None,
        "paused_at": preflight.paused_at.value if preflight.paused_at else None,
        "failure_class": (
            preflight.failure_class.value if preflight.failure_class else None
        ),
        "gates": [dict(row) for row in _gate_rows(preflight)],
        "blockers": [dict(row) for row in marker_blocker_rows(preflight.blockers)],
        "pending": (
            {
                "acquisition_status": reason.acquisition_status.value,
                "what_was_walked": reason.what_was_walked,
                "what_is_outstanding": list(reason.what_is_outstanding),
                "what_it_would_answer": reason.what_it_would_answer,
                "this_is_not_a_finding_about_the_candidate": True,
            }
            if reason is not None
            else None
        ),
        "acceptance_conditions": list(frozen.ACCEPTANCE_CONDITIONS),
        "non_goals": list(frozen.NON_GOALS),
        "permitted_constructions": list(frozen.PERMITTED_CONSTRUCTIONS),
        "forbidden_reads": list(frozen.FORBIDDEN_READS),
        "opens_stage_12b": preflight.opens_stage_12b,
        "observations_fingerprint": observed.observations_fingerprint(),
        "preflight_fingerprint": preflight.preflight_fingerprint,
    }


_DOCUMENT_BUILDERS = {
    frozen.PREDECESSOR_BINDING_NAME: predecessor_binding_document,
    frozen.ACQUISITION_STATUS_NAME: acquisition_status_document,
    frozen.PACKAGE_MANIFEST_NAME: package_manifest_document,
    frozen.RESEARCH_USE_LICENSE_NAME: research_use_license_document,
    frozen.RUNTIME_INVENTORY_NAME: runtime_inventory_document,
    frozen.INPUT_ROUTE_NAME: input_route_document,
    frozen.FINGERPRINT_ROUTE_PROFILE_NAME: fingerprint_route_profile_document,
    frozen.SCORE_CONTRACT_NAME: score_contract_document,
    frozen.QUALIFICATION_RUN_NAME: qualification_run_document,
    frozen.TRAINING_PROVENANCE_NAME: training_provenance_document,
    frozen.PREFLIGHT_REPORT_NAME: preflight_report_document,
}


def evidence_document(preflight: IdkitPreflight, name: str) -> Mapping[str, Any]:
    """One derivable evidence document, guarded before it is returned."""
    builder = _DOCUMENT_BUILDERS.get(name)
    if builder is None:
        raise Stage12AFinalizationError(
            f"{name!r} is not a derivable Stage 12A evidence document"
        )
    document = builder(preflight)
    require_no_sensitive_material(document, where=f"the derived {name}")
    return document


def marker_blocker_rows(
    blockers: Sequence[Blocker],
) -> tuple[Mapping[str, str], ...]:
    """Blockers in the form the marker stores them."""
    return tuple(
        {
            "gate": item.gate.value,
            "blocker_code": item.blocker_code.value,
            "affected_component": item.affected_component,
            "evidence": item.evidence,
            "why_this_blocks_algorithm_5": item.why_this_blocks_algorithm_5,
            "how_this_would_be_lifted": item.how_this_would_be_lifted,
        }
        for item in sorted(blockers, key=lambda item: item.blocker_code.value)
    )
