"""The ten hard gates, run in order, and the verdict that follows.

The engine has no verdict parameter, for the reason Stage 8E's decision engine
has none, Stage 9A's qualification has none and Stage 10A's preflight has none:
an engine that accepted an outcome and then validated it would be a very
elaborate way of writing the outcome down. It reads
:mod:`fpbench.experiments.stage10b_id3_observations` and the state of the local
artifact store, applies the gate order frozen in
:mod:`fpbench.experiments.stage10b_id3_identity`, and reports what follows.

**Fail-fast is the design, not an optimisation.** The candidate stops at the
first gate it fails, and every later gate is published ``NOT_REACHED``. That is
why product identity and acquisition come first: both can be settled without a
package, and settling acquisition negatively means no licence is requested, no
activation is attempted, no model is downloaded and no runtime is built
(docs/adr/0094).

**Access is not research use.** Stage 8E decides whether this project may
execute a third-party component under its declared purpose. This stage decides
whether the project holds a working copy and an active licence. A component can
be permitted and still be inoperable, and no amount of permission produces a
package (docs/adr/0095).

Nothing here reads SD300, reads a prior algorithm's scores, downloads a package,
imports a vendor runtime, activates a licence, or produces a score.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from fpbench.core.id3_preflight_errors import (
    Id3AccessQualificationError,
    Id3GateError,
    SensitiveEvidenceError,
    Stage10BFinalizationError,
)
from fpbench.core.serialization import stable_hash
from fpbench.experiments import stage10b_id3_identity as frozen
from fpbench.experiments import stage10b_id3_observations as observed
from fpbench.third_party import (
    policy_fingerprint,
    project_purpose,
    resolve_third_party_root,
)

__all__ = [
    "Blocker",
    "GateResult",
    "Id3Preflight",
    "PackageAcquisition",
    "LicenseCapability",
    "WorkloadBudget",
    "TrackedByteAudit",
    "TrackedByteFinding",
    "require_stage8e_is_the_policy_this_reuses",
    "require_stage10a_is_the_closed_predecessor",
    "package_acquisition_state",
    "license_capability_state",
    "workload_budget",
    "run_gate_product_identity",
    "run_gate_acquisition_access",
    "run_preflight",
    "candidate_identity_document",
    "public_product_observations_document",
    "access_qualification_document",
    "license_capability_report_document",
    "sdk_package_manifest_document",
    "model_artifact_manifest_document",
    "input_domain_contract_document",
    "extraction_profile_document",
    "matcher_profile_document",
    "score_contract_document",
    "training_provenance_document",
    "runtime_smoke_document",
    "preflight_report_document",
    "evidence_document",
    "marker_blocker_rows",
    "find_sensitive_material",
    "require_no_sensitive_material",
    "audit_tracked_bytes_against_id3_artifacts",
    "require_no_id3_bytes_in_git",
]


# ------------------------------------------------------------ the closed stages


def require_stage8e_is_the_policy_this_reuses(repository_root: Path) -> None:
    """Confirm the policy Stage 10B reuses is the policy it was written against.

    Three checks, each catching a different way this could go wrong: the
    published Stage 8E marker still says what it said, the live purpose and
    policy still fingerprint to what that marker recorded, and Stage 8E still
    declares the research-only policy ready.

    Raises:
        Stage10BFinalizationError: any of the three disagrees. Stage 10B does not
            repair Stage 8E and does not proceed around it — a corrective policy
            stage is the response, not a quiet edit from here.
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
            raise Stage10BFinalizationError(
                f"the Stage 8E marker's {key} is {found!r} and Stage 10B was "
                f"written against {value!r}. Stage 8E is a closed stage; a "
                "capability it lacks is a corrective policy stage, not an edit "
                "from here"
            )

    declaration = project_purpose()
    if declaration.purpose_fingerprint != frozen.STAGE8E_PURPOSE_FINGERPRINT:
        raise Stage10BFinalizationError(
            "the live project purpose no longer fingerprints to what Stage 8E "
            "published; every Stage 10B decision would be taken under a "
            "different premise"
        )
    if policy_fingerprint() != frozen.STAGE8E_POLICY_FINGERPRINT:
        raise Stage10BFinalizationError(
            "the live third-party policy no longer fingerprints to what Stage 8E "
            "published"
        )


def require_stage10a_is_the_closed_predecessor(repository_root: Path) -> str:
    """Confirm Stage 10A still says what Stage 10B was written after.

    Stage 10B exists because Stage 10A ended without a survivor and opened a
    candidate search. Binding that marker's fingerprint is what makes "Stage 10A
    was not re-opened to admit id3" a checkable claim rather than an intention:
    adding a candidate to Stage 10A's frozen set would move this digest and stop
    Stage 10B from publishing at all (docs/adr/0094).

    Returns:
        The predecessor fingerprint, for the marker to carry.

    Raises:
        Stage10BFinalizationError: Stage 10A's marker has moved.
    """
    relative = f"{frozen.STAGE_10A_EVIDENCE_DIRECTORY}/stage-10a-finalization.json"
    marker = _read_marker(repository_root, relative, "Stage 10A")
    expected = {
        "outcome": frozen.STAGE_10A_OUTCOME,
        "stage_10a_finalization_fingerprint": (
            frozen.STAGE_10A_FINALIZATION_FINGERPRINT
        ),
    }
    for key, value in expected.items():
        found = marker.get(key)
        if found != value:
            raise Stage10BFinalizationError(
                f"the Stage 10A marker's {key} is {found!r} and Stage 10B was "
                f"written after {value!r}. Stage 10A is immutable here: its "
                "candidate set was frozen before its result was known, and "
                "changing it now would change the question after the answer "
                "(docs/adr/0094)"
            )
    if marker.get("opens_candidate_search") is not True:
        raise Stage10BFinalizationError(
            "Stage 10A's marker no longer opens a candidate search, and a "
            "candidate search is the only thing Stage 10B is a response to"
        )
    return frozen.STAGE_10A_FINALIZATION_FINGERPRINT


def _read_marker(
    repository_root: Path, relative: str, stage: str
) -> Mapping[str, Any]:
    import json

    path = Path(repository_root) / PurePosixPath(relative)
    try:
        marker = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Stage10BFinalizationError(
            f"cannot read the {stage} marker Stage 10B binds at {relative}: {exc}"
        ) from exc
    if not isinstance(marker, dict):
        raise Stage10BFinalizationError(f"the {stage} marker is not a JSON object")
    return marker


# ------------------------------------------------------------ what is held here


@dataclass(frozen=True, slots=True)
class PackageAcquisition:
    """What this machine holds of the id3 Finger SDK package.

    ``frozen_identity_available`` is the field that matters. Until a package has
    been delivered, there is no filename, digest, size or platform to freeze, so
    there is nothing a probe could verify a file against. Material sitting in the
    store with no frozen identity is therefore reported as a *finding* rather
    than as an acquisition: an unverifiable copy is not a copy of anything in
    particular (spec section 8).
    """

    status: frozen.AcquisitionStatus
    frozen_identity_available: bool
    store_resolvable: bool
    store_holds_material: bool
    findings: tuple[str, ...] = ()

    @property
    def obtained(self) -> bool:
        return self.status is frozen.AcquisitionStatus.OBTAINED


def package_acquisition_state(
    *, root: Path | None = None, repository_root: Path | None = None
) -> PackageAcquisition:
    """Look for a delivered package, without requiring one to be here.

    Absence is the ordinary state — it is true of every CI runner by design, and
    of this project today — so it is reported rather than raised.
    """
    try:
        store = (
            Path(root)
            if root is not None
            else resolve_third_party_root(repository_root=repository_root)
        )
    except Exception:  # pragma: no cover - an unusable store is simply absent
        return PackageAcquisition(
            status=frozen.AcquisitionStatus.NOT_ATTEMPTED_HERE,
            frozen_identity_available=False,
            store_resolvable=False,
            store_holds_material=False,
            findings=("no local artifact store is resolvable here",),
        )

    prefix = Path(store) / frozen.ARTIFACT_STORE_PREFIX
    holds = prefix.is_dir() and any(
        item.is_file() for item in prefix.rglob("*")
    )
    findings: list[str] = []
    if holds:
        findings.append(
            "the store holds material under this stage's prefix and Stage 10B "
            "froze no package identity to verify it against; nothing here may "
            "be treated as the delivered SDK"
        )
    else:
        findings.append("no delivered package is present in the local artifact store")
    findings.append(
        "no package identity is frozen, because no package was delivered: the "
        "vendor's published route delivers one only on request"
    )
    return PackageAcquisition(
        status=frozen.AcquisitionStatus.NOT_ATTEMPTED_HERE,
        frozen_identity_available=False,
        store_resolvable=True,
        store_holds_material=holds,
        findings=tuple(findings),
    )


@dataclass(frozen=True, slots=True)
class LicenseCapability:
    """What is known about a licence, and what may be said about it publicly.

    Every publishable field is optional and every one of them is ``None`` until
    a licence exists. The fields that are *not* here are the point: no key, no
    hardware code, no customer identifier and no licence bytes appear on this
    class, so no code path can carry one into a document (docs/adr/0098).
    """

    license_present: bool
    activation_attempted: bool
    activation_verified: bool
    capacity: frozen.LicenseCapacityStatus
    license_type: str | None
    enabled_module_names: tuple[str, ...]
    expiry_category: str | None
    remaining_days_category: str | None
    sufficient_for_declared_workload: bool | None
    basis: str

    def __post_init__(self) -> None:
        if self.activation_verified and not self.license_present:
            raise Id3AccessQualificationError(
                "activation cannot be verified without a licence being present"
            )
        if self.capacity.admits_candidate and not self.activation_verified:
            raise Id3AccessQualificationError(
                "a capacity called sufficient rests on an activated licence; "
                "sufficiency asserted without one is a guess about a quota "
                "nobody has read (docs/adr/0096)"
            )
        if self.sufficient_for_declared_workload is True and not (
            self.capacity.admits_candidate
        ):
            raise Id3AccessQualificationError(
                "sufficient_for_declared_workload disagrees with the capacity "
                "status beside it"
            )


def license_capability_state() -> LicenseCapability:
    """What this project knows about an id3 licence today.

    Derived from the published evaluation terms rather than asserted. The
    vendor advertises a limit without a number and publishes no metering
    semantics, so even a licence in hand would leave the capacity question open
    until the delivered documentation answered it (spec section 5).
    """
    terms = observed.EVALUATION_TERMS
    unresolved_reasons: list[str] = []
    if not terms.api_call_limit_is_numeric:
        unresolved_reasons.append(
            f"the advertised limit is the phrase {terms.api_call_limit_statement!r} "
            "with no number"
        )
    if not terms.metering_semantics_published:
        unresolved_reasons.append(
            "no public statement says which operations consume the quota — "
            "extraction, matching, model loading, or every API call"
        )
    return LicenseCapability(
        license_present=False,
        activation_attempted=False,
        activation_verified=False,
        capacity=frozen.LicenseCapacityStatus.UNRESOLVED,
        license_type=None,
        enabled_module_names=(),
        expiry_category=None,
        remaining_days_category=None,
        sufficient_for_declared_workload=None,
        basis="; ".join(unresolved_reasons),
    )


@dataclass(frozen=True, slots=True)
class WorkloadBudget:
    """What the frozen workload costs under each metering semantics it could have.

    A table rather than a number, because the unknown is not the size of the run
    — that has been fixed at 3,000 extractions and 6,000 comparisons since the
    canonical protocol was frozen — but which of those operations a quota
    counts. Publishing the cost under each reading is what turns "we do not know
    whether it fits" into something a vendor can be asked one question about
    (docs/adr/0096).
    """

    workload: frozen.FrozenWorkload
    costs_by_metering_semantics: Mapping[str, int]
    resolved: bool
    basis: str


def workload_budget() -> WorkloadBudget:
    """The arithmetic, under every metering semantics the licence could use."""
    load = frozen.FROZEN_WORKLOAD
    costs = {
        "extraction_only": load.extractions,
        "matching_only": load.comparisons,
        "extraction_and_matching": load.extractions + load.comparisons,
        "every_api_call_upper_bound": load.total_metered_operations_upper_bound,
    }
    return WorkloadBudget(
        workload=load,
        costs_by_metering_semantics=dict(sorted(costs.items())),
        resolved=False,
        basis=(
            "The workload is frozen and the metering is not. Under the most "
            f"expensive published reading the run costs at most "
            f"{load.total_metered_operations_upper_bound} metered operations, "
            "which is the figure a licence would have to cover before a single "
            "comparison is run. No reading of the public terms establishes "
            "whether an evaluation licence covers it."
        ),
    )


# ------------------------------------------------------------------- the gates


@dataclass(frozen=True, slots=True)
class Blocker:
    """One reason the id3 Finger SDK cannot enter fpbench as Algorithm 4.

    Four fields, all mandatory. A blocker nobody can point at is a blocker
    nobody can lift, and a blocker with no stated consequence is an opinion.
    ``how_this_would_be_lifted`` is required too, because an access blocker is
    exactly the kind that a person can lift next week and this project should be
    able to say how (docs/adr/0095).
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
            raise Id3GateError(
                f"{self.blocker_code.value} does not belong to "
                f"{self.gate.value}; it belongs to "
                f"{[item.value for item in frozen.gate_of_blocker(self.blocker_code)]} "
                "and raising it here would put the reason in the wrong place"
            )
        for name in (
            "affected_component",
            "evidence",
            "why_this_blocks_algorithm_4",
            "how_this_would_be_lifted",
        ):
            if not str(getattr(self, name)).strip():
                raise Id3GateError(f"{self.blocker_code.value}: {name} is empty")


@dataclass(frozen=True, slots=True)
class GateResult:
    """One gate's conclusion."""

    gate: frozen.PreflightGate
    status: frozen.GateStatus
    summary: str
    blockers: tuple[Blocker, ...] = ()

    def __post_init__(self) -> None:
        if self.status is frozen.GateStatus.PASS and self.blockers:
            raise Id3GateError(
                f"{self.gate.value}: a gate that passed carries no blockers; a "
                "blocker is not a reservation to be weighed"
            )
        if self.status is frozen.GateStatus.FAIL and not self.blockers:
            raise Id3GateError(f"{self.gate.value}: a gate that failed names why")
        if self.status is frozen.GateStatus.NOT_REACHED and self.blockers:
            raise Id3GateError(
                f"{self.gate.value}: a gate that was never reached cannot have "
                "found anything"
            )
        for blocker in self.blockers:
            if blocker.gate is not self.gate:
                raise Id3GateError(
                    f"{self.gate.value}: carries a blocker raised at "
                    f"{blocker.gate.value}"
                )


def run_gate_product_identity() -> GateResult:
    """Gate 1. Is this the vendor's Finger SDK, and not something beside it?

    The vendor ships more than one fingerprint product and the public sample
    repository is not the SDK. The claim passes on locators that name the
    product: the product page, the SDK index that lists it separately from the
    vendor's other SDKs, a reference tree titled with a version, and the
    vendor's own samples stating which SDK version they require (spec section 3).
    """
    claim = observed.PRODUCT_IDENTITY_CLAIM
    return GateResult(
        gate=frozen.PreflightGate.PRODUCT_IDENTITY,
        status=frozen.GateStatus.PASS,
        summary=(
            f"{frozen.IMPLEMENTATION_ORIGIN}: {claim.product_name} by "
            f"{claim.vendor}, publicly documented at version "
            f"{claim.declared_sdk_version_public}, named by "
            f"{len(claim.supporting_locators)} locators and distinguished from "
            f"{len(claim.distinguished_from)} products it is not. This "
            "establishes which product Stage 10B is about; it establishes "
            "nothing about a package, because no package has been delivered."
        ),
    )


def run_gate_acquisition_access() -> GateResult:
    """Gate 2. Can this project obtain and operate the package at all?

    The most important fail-fast in the stage. Everything after it — the exact
    package identity, the model inventory, the input route, the two profiles,
    the score API, the smoke — is a question about a delivered package, and none
    of them can be answered about a package nobody has (docs/adr/0095).

    Capacity is decided here too. The evaluation licence is advertised with a
    limit and no number, and no public statement says which operations consume
    it, so the capacity is ``UNRESOLVED`` — which is a failure and not a caution
    (docs/adr/0096).
    """
    route = observed.ACQUISITION_ROUTE
    package = package_acquisition_state()
    licence = license_capability_state()
    budget = workload_budget()

    blockers: list[Blocker] = []
    if not package.obtained:
        blockers.append(
            Blocker(
                gate=frozen.PreflightGate.ACQUISITION_ACCESS,
                blocker_code=frozen.BlockerCode.ID3_PACKAGE_NOT_OBTAINABLE,
                affected_component="the delivered id3 Finger SDK package",
                evidence=(
                    "access-qualification.json: the vendor publishes no "
                    "self-service download. Its own samples state that the SDK "
                    "archive and the activation key arrive together, and only "
                    "after a request to the vendor has been accepted. No such "
                    "request has been made from this project, so no package has "
                    "been delivered and there is nothing here to identify."
                ),
                why_this_blocks_algorithm_4=(
                    "Every remaining gate is a question about a delivered "
                    "package: its exact version, its models, its input route, "
                    "its extraction and matcher profiles and its score API. None "
                    "of them can be answered from a product page, and answering "
                    "them from one would be publishing a benchmark route this "
                    "project had never seen."
                ),
                how_this_would_be_lifted=(
                    "The maintainer requests an evaluation or developer licence "
                    "from the vendor in their own name, receives the archive and "
                    "the activation key, and re-runs this stage. The request is "
                    "a person-to-vendor exchange; it is not something this "
                    "preflight performs, and no credential from it enters this "
                    "repository (docs/adr/0098)."
                ),
            )
        )
    if not licence.license_present:
        blockers.append(
            Blocker(
                gate=frozen.PreflightGate.ACQUISITION_ACCESS,
                blocker_code=frozen.BlockerCode.ID3_LICENSE_NOT_OBTAINABLE,
                affected_component="an activated id3 Finger SDK licence",
                evidence=(
                    "access-qualification.json: activation runs against an "
                    "activation key issued by the vendor and a host hardware "
                    "code, and the vendor's own sample checks a licence file "
                    "before any other SDK call. No activation key has been "
                    "issued to this project and no activation has been "
                    "attempted."
                ),
                why_this_blocks_algorithm_4=(
                    "The SDK refuses every call before its licence check, so "
                    "without a licence there is no route to smoke, no version to "
                    "read from the running library and no score to contract "
                    "over. This is an operational access finding and not a "
                    "licence-terms finding: nothing here says the terms forbid "
                    "research use (docs/adr/0095)."
                ),
                how_this_would_be_lifted=(
                    "The same vendor request that delivers the package delivers "
                    "the activation key. Activation then happens locally, on one "
                    "chosen platform, and this stage records only the licence "
                    "type, the enabled modules and an expiry category."
                ),
            )
        )
    if not licence.capacity.admits_candidate:
        blockers.append(
            Blocker(
                gate=frozen.PreflightGate.ACQUISITION_ACCESS,
                blocker_code=(
                    frozen.BlockerCode.LICENSE_WORKLOAD_CAPACITY_UNRESOLVED
                ),
                affected_component=(
                    "the evaluation licence's capacity against the frozen "
                    "workload"
                ),
                evidence=(
                    "license-capability-report.json: the free evaluation is "
                    f"advertised as {observed.EVALUATION_TERMS.duration_days} days "
                    f"with {observed.EVALUATION_TERMS.api_call_limit_statement!r} "
                    "and a single platform. No number accompanies the limit and "
                    "no public statement says which operations consume it, while "
                    "the frozen workload costs at most "
                    f"{budget.workload.total_metered_operations_upper_bound} "
                    "metered operations."
                ),
                why_this_blocks_algorithm_4=(
                    "A quota that runs out partway through 6,000 comparisons "
                    "produces a partial run, and a partial run is not a result. "
                    "Capacity is a hard gate precisely so that this is settled "
                    "before the first comparison rather than discovered during "
                    "the four thousandth (docs/adr/0096)."
                ),
                how_this_would_be_lifted=(
                    "The delivered licence documentation, or one question to the "
                    "vendor, states which operations are metered and how many "
                    "remain. Sufficiency is then arithmetic against the frozen "
                    "workload, and it is recorded as a boolean beside the "
                    "workload it was computed against."
                ),
            )
        )

    if not blockers:  # pragma: no cover - unreachable while nothing is delivered
        return GateResult(
            gate=frozen.PreflightGate.ACQUISITION_ACCESS,
            status=frozen.GateStatus.PASS,
            summary=(
                f"{frozen.OperationalAccessDecision.OPERABLE.value}: a delivered "
                "package, an activated licence and a capacity sufficient for the "
                "frozen workload"
            ),
        )
    decision = (
        frozen.OperationalAccessDecision.NO_PACKAGE
        if not package.obtained
        else frozen.OperationalAccessDecision.NO_LICENSE
    )
    return GateResult(
        gate=frozen.PreflightGate.ACQUISITION_ACCESS,
        status=frozen.GateStatus.FAIL,
        summary=(
            f"{decision.value}: {route.request_channel} is the only published "
            "route to a package and a licence, no request has been made from "
            "here, and the advertised evaluation capacity cannot be checked "
            "against the frozen workload."
        ),
        blockers=tuple(blockers),
    )


#: The gates that have a runner. A gate reached with no runner is an unanswered
#: question and never a pass — the engine raises rather than assume one
#: (docs/adr/0094).
_GATE_RUNNERS = {
    frozen.PreflightGate.PRODUCT_IDENTITY: run_gate_product_identity,
    frozen.PreflightGate.ACQUISITION_ACCESS: run_gate_acquisition_access,
}


def _unreached_reason(stopped_at: frozen.PreflightGate) -> str:
    return (
        f"the candidate stopped at {stopped_at.value}, so this question was "
        "never asked: nothing was downloaded, activated, loaded or executed for "
        "it"
    )


@dataclass(frozen=True, slots=True)
class Id3Preflight:
    """The whole preflight: every gate, the verdict, and the outcome."""

    results: tuple[GateResult, ...]
    stopped_at: frozen.PreflightGate | None
    preflight_fingerprint: str

    def __post_init__(self) -> None:
        seen = tuple(result.gate for result in self.results)
        if seen != frozen.GATE_ORDER:
            raise Id3GateError(
                f"the gates were reported as {seen} and the frozen order is "
                f"{frozen.GATE_ORDER}"
            )
        failed = [
            result.gate
            for result in self.results
            if result.status is frozen.GateStatus.FAIL
        ]
        if len(failed) > 1:
            raise Id3GateError(
                f"fail-fast means one failing gate, and these failed: {failed}"
            )
        if failed and failed[0] is not self.stopped_at:
            raise Id3GateError(
                f"the stopping gate is {self.stopped_at} and the failing gate is "
                f"{failed[0]}"
            )
        if not failed and self.stopped_at is not None:
            raise Id3GateError(
                f"stopped at {self.stopped_at} with no failing gate"
            )

    @property
    def passed(self) -> bool:
        """Every gate passed. Not "no gate failed": NOT_REACHED is not a pass."""
        return all(
            result.status is frozen.GateStatus.PASS for result in self.results
        )

    @property
    def verdict(self) -> str:
        return (
            frozen.CANDIDATE_PASS_VERDICT
            if self.passed
            else frozen.CANDIDATE_FAIL_VERDICT
        )

    @property
    def outcome(self) -> str:
        return (
            frozen.STAGE_10B_SELECTED_OUTCOME
            if self.passed
            else frozen.STAGE_10B_BLOCKED_OUTCOME
        )

    @property
    def selected_candidate(self) -> str | None:
        return frozen.CANDIDATE_ID if self.passed else None

    @property
    def gates_reached(self) -> int:
        return sum(
            1
            for result in self.results
            if result.status is not frozen.GateStatus.NOT_REACHED
        )

    @property
    def blockers(self) -> tuple[Blocker, ...]:
        """Every blocker, in the order the marker stores them.

        Sorted here rather than at the marker, so that the claims a caller
        builds and the claims the marker normalises are the same object.
        """
        return tuple(
            sorted(
                (blocker for result in self.results for blocker in result.blockers),
                key=lambda item: item.blocker_code.value,
            )
        )

    def result(self, gate: frozen.PreflightGate) -> GateResult:
        for item in self.results:
            if item.gate is gate:
                return item
        raise KeyError(gate)  # pragma: no cover - GATE_ORDER is exhaustive

    def status(self, gate: frozen.PreflightGate) -> frozen.GateStatus:
        return self.result(gate).status


def run_preflight() -> Id3Preflight:
    """Run the gate order and stop at the first failure."""
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
        if runner is None:
            raise Id3GateError(  # pragma: no cover - unreachable today
                f"the candidate survived to {gate.value} and Stage 10B has no "
                "runner for it. A gate without a runner is an unanswered "
                "question, not a passed one"
            )
        result = runner()
        results.append(result)
        if result.status is frozen.GateStatus.FAIL:
            stopped_at = gate
    return Id3Preflight(
        results=tuple(results),
        stopped_at=stopped_at,
        preflight_fingerprint=stable_hash(
            {
                "schema": "stage_10b_preflight_v1",
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
    (name, re.compile(source))
    for name, source in frozen.SENSITIVE_VALUE_PATTERNS
)


def find_sensitive_material(node: Any, trail: str = "") -> tuple[str, ...]:
    """Every place a document carries a credential, by key or by value shape.

    Walks the document as *data*. A key match is reported wherever it appears;
    a value match is reported for any string, at any depth, including inside a
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
    """The raising form, for the publisher.

    Raises:
        SensitiveEvidenceError: the document carries, or is about to carry,
            something shaped like licence material. The publisher stops rather
            than redacting: a redaction that silently succeeds is how the second
            one gets missed (docs/adr/0098).
    """
    findings = find_sensitive_material(node)
    if findings:
        raise SensitiveEvidenceError(
            f"{where} carries licence material and will not be published: "
            f"{list(findings)}"
        )


# ------------------------------------------------------------- the byte guard


@dataclass(frozen=True, slots=True)
class TrackedByteFinding:
    """One tracked file that is, or looks like, a vendor artifact."""

    path: str
    component_role: str
    basis: str


@dataclass(frozen=True, slots=True)
class TrackedByteAudit:
    """Every tracked file, checked against what this stage knows about id3."""

    tracked_file_count: int
    known_digest_count: int
    findings: tuple[TrackedByteFinding, ...]

    @property
    def clean(self) -> bool:
        return not self.findings


#: File shapes that are vendor artifacts whatever their bytes turn out to be: a
#: neural model the SDK loads, an activated licence, and the archive the vendor
#: delivers. Names rather than digests, because Stage 10B has no digests to know
#: — that is the state the acquisition gate reports (docs/adr/0083).
_VENDOR_ARTIFACT_SUFFIXES = (".id3nn", ".lic")
_VENDOR_ARTIFACT_NAME_FRAGMENTS = ("id3finger", "id3licenseactivation")


def id3_artifact_digests() -> Mapping[str, tuple[str, str]]:
    """Every exact digest Stage 10B knows, keyed by digest.

    Only the public sample files this stage quotes. A tracked file matching one
    would mean upstream bytes had entered a public repository that promises to
    hold none, even where the bytes are freely readable elsewhere
    (docs/adr/0083).
    """
    return {
        item.sha256: (
            f"id3_samples:{item.relative_path}",
            f"an upstream file this stage cites: {item.relative_path}",
        )
        for item in observed.SAMPLES_PINNED_FILES
    }


def _tracked_files(repository_root: Path) -> tuple[str, ...]:
    try:
        completed = subprocess.run(
            ("git", "-C", str(repository_root), "ls-files", "-z"),
            check=False,
            capture_output=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Stage10BFinalizationError(
            f"cannot list tracked files for the Stage 10B byte guard: {exc}"
        ) from exc
    if completed.returncode != 0:
        raise Stage10BFinalizationError(
            "cannot list tracked files for the Stage 10B byte guard: "
            + completed.stderr.decode("utf-8", "replace").strip()
        )
    return tuple(
        name for name in completed.stdout.decode("utf-8", "replace").split("\0") if name
    )


def audit_tracked_bytes_against_id3_artifacts(
    repository_root: Path,
) -> TrackedByteAudit:
    """Hash every tracked file, and check every tracked name."""
    repository_root = Path(repository_root)
    known = id3_artifact_digests()
    findings: list[TrackedByteFinding] = []
    tracked = _tracked_files(repository_root)
    for relative in tracked:
        lowered = PurePosixPath(relative).name.lower()
        if lowered.endswith(_VENDOR_ARTIFACT_SUFFIXES) or any(
            fragment in lowered for fragment in _VENDOR_ARTIFACT_NAME_FRAGMENTS
        ):
            findings.append(
                TrackedByteFinding(
                    path=relative,
                    component_role="a vendor model, licence or activation tool",
                    basis="name",
                )
            )
            continue
        path = repository_root / PurePosixPath(relative)
        if not path.is_file():
            continue
        digest = hashlib.sha256()
        try:
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1 << 20), b""):
                    digest.update(block)
        except OSError:  # pragma: no cover - a tracked file that cannot be read
            continue
        found = known.get(digest.hexdigest())
        if found is not None:
            findings.append(
                TrackedByteFinding(
                    path=relative, component_role=found[1], basis="digest"
                )
            )
    return TrackedByteAudit(
        tracked_file_count=len(tracked),
        known_digest_count=len(known),
        findings=tuple(sorted(findings, key=lambda item: item.path)),
    )


def require_no_id3_bytes_in_git(repository_root: Path) -> TrackedByteAudit:
    """The raising form, for a gate.

    Raises:
        Stage10BFinalizationError: a tracked file is a vendor artifact by name or
            byte-for-byte an upstream file this stage cites.
    """
    audit = audit_tracked_bytes_against_id3_artifacts(repository_root)
    if not audit.clean:
        detail = "; ".join(
            f"{finding.path} is {finding.component_role} (by {finding.basis})"
            for finding in audit.findings
        )
        raise Stage10BFinalizationError(
            f"id3 material is tracked in this public repository: {detail}"
        )
    return audit


# --------------------------------------------------------- published documents


def _not_reached(preflight: Id3Preflight, gate: frozen.PreflightGate, schema: str):
    result = preflight.result(gate)
    if result.status is not frozen.GateStatus.NOT_REACHED:
        raise Id3GateError(  # pragma: no cover - the caller checks first
            f"{gate.value} is {result.status.value} and cannot be published as a "
            "gate that was never reached"
        )
    return {
        "schema": schema,
        "candidate": frozen.CANDIDATE_ID,
        "gate": gate.value,
        "gate_status": frozen.GateStatus.NOT_REACHED.value,
        "why_not_reached": result.summary,
    }


def candidate_identity_document() -> Mapping[str, Any]:
    """Who the candidate is, provisionally, and what a final identity would need."""
    claim = observed.PRODUCT_IDENTITY_CLAIM
    return {
        "schema": "stage_10b_candidate_identity_v1",
        "algorithm_slot": frozen.ALGORITHM_SLOT,
        "question": (
            "does a package of the id3 Finger SDK exist here that is exact, "
            "legally and practically operable for local research, and that "
            "defines a complete 1:1 route from canonical_500 to a raw score "
            "with no score-affecting choice left to fpbench"
        ),
        "candidate_id": frozen.CANDIDATE_ID,
        "candidate_id_is_provisional": True,
        "implementation_origin": frozen.IMPLEMENTATION_ORIGIN,
        "production_algorithm_id_frozen": frozen.PRODUCTION_ALGORITHM_ID_FROZEN,
        "final_identity_would_have_to_name": list(frozen.FINAL_IDENTITY_COMPONENTS),
        "complete_identity_fingerprint_required_before_pass": list(
            frozen.COMPLETE_IDENTITY_FINGERPRINT_COMPONENTS
        ),
        "product_name": claim.product_name,
        "vendor": claim.vendor,
        "publicly_documented_version": claim.declared_sdk_version_public,
        "publicly_documented_version_is_not_the_package_identity": True,
        "declared_non_candidates": [
            {"identity": name, "description": description}
            for name, description in frozen.DECLARED_NON_CANDIDATES
        ],
        "predecessor": {
            "stage": "stage_10a",
            "outcome": frozen.STAGE_10A_OUTCOME,
            "finalization_fingerprint": frozen.STAGE_10A_FINALIZATION_FINGERPRINT,
            "relation": (
                "Stage 10A froze a candidate set of AFR-Net and JIPNet before "
                "its result was known, ended without a survivor, and opened a "
                "candidate search. Stage 10B is that search's first candidate "
                "and adds nothing to Stage 10A (docs/adr/0094)."
            ),
            "stage_10a_evidence_modified_by_stage_10b": False,
        },
        "gate_order": [gate.value for gate in frozen.GATE_ORDER],
        "gates_are_conjunctive_and_unweighted": True,
        "gate_count_defined": frozen.GATE_COUNT,
        "benchmark_input": {
            "profile": frozen.BENCHMARK_INPUT_PROFILE,
            "ppi": frozen.BENCHMARK_INPUT_PPI,
            "pixel_format": frozen.BENCHMARK_INPUT_PIXEL_FORMAT,
        },
        "frozen_workload": {
            "participating_images": frozen.FROZEN_WORKLOAD.participating_images,
            "extractions": frozen.FROZEN_WORKLOAD.extractions,
            "comparisons": frozen.FROZEN_WORKLOAD.comparisons,
            "qualification_operations_upper_bound": (
                frozen.FROZEN_WORKLOAD.qualification_operations_upper_bound
            ),
        },
        "non_goals": list(frozen.NON_GOALS),
        # A list of rows rather than a map keyed by surface name: "threshold"
        # and "calibration" are refused *keys* in a published document, and a
        # map would refuse a record of not having produced one.
        "production_integration_not_created": [
            {"surface": name, "created": False}
            for name in frozen.PRODUCTION_INTEGRATION_NOT_CREATED
        ],
        "observations_fingerprint": observed.observations_fingerprint(),
    }


def public_product_observations_document(
    preflight: Id3Preflight,
) -> Mapping[str, Any]:
    """Gate 1's document: what the vendor publishes, and what did not resolve."""
    result = preflight.result(frozen.PreflightGate.PRODUCT_IDENTITY)
    claim = observed.PRODUCT_IDENTITY_CLAIM
    return {
        "schema": "stage_10b_public_product_observations_v1",
        "candidate": frozen.CANDIDATE_ID,
        "gate": frozen.PreflightGate.PRODUCT_IDENTITY.value,
        "gate_status": result.status.value,
        "gate_summary": result.summary,
        "observed_utc": observed.OBSERVED_UTC,
        "product_identity": {
            "product_name": claim.product_name,
            "vendor": claim.vendor,
            "publicly_documented_version": claim.declared_sdk_version_public,
            "supporting_locators": list(claim.supporting_locators),
            "distinguished_from": list(claim.distinguished_from),
        },
        "product_observations": observed.observation_rows(
            observed.PRODUCT_OBSERVATIONS
        ),
        "platform_observations": observed.observation_rows(
            observed.PLATFORM_OBSERVATIONS
        ),
        "documentation_observations": observed.observation_rows(
            observed.DOCUMENTATION_OBSERVATIONS
        ),
        "locators_that_did_not_resolve": observed.observation_rows(
            observed.UNRESOLVED_LOCATORS
        ),
        "official_samples_repository": {
            "upstream_name": observed.SAMPLES_REPOSITORY.upstream_name,
            "locator": observed.SAMPLES_REPOSITORY.html_locator,
            "commit": observed.SAMPLES_REPOSITORY.commit,
            "commit_date_utc": observed.SAMPLES_REPOSITORY.commit_date_utc,
            "release_label": observed.SAMPLES_REPOSITORY.release_label,
            "branch_is_not_an_identity": True,
            "cited_files": [
                {
                    "relative_path": item.relative_path,
                    "sha256": item.sha256,
                    "size_bytes": item.size_bytes,
                }
                for item in observed.SAMPLES_PINNED_FILES
            ],
            "this_repository_is_not_the_sdk": True,
        },
        "notes": [
            "A version read from a web page identifies the web page. The "
            "package identity gate reads the version from the delivered "
            "package's own library at runtime, and until then no version here "
            "is an identity (spec section 8).",
            "The documentation locators this stage was written against are "
            "published with the status they returned, including the five that "
            "answer 404, so that a reader can tell a checked citation from a "
            "repeated one.",
        ],
    }


def access_qualification_document(preflight: Id3Preflight) -> Mapping[str, Any]:
    """Gate 2's first document: can this project obtain and operate the SDK?"""
    result = preflight.result(frozen.PreflightGate.ACQUISITION_ACCESS)
    route = observed.ACQUISITION_ROUTE
    package = package_acquisition_state()
    licence = license_capability_state()
    decision = (
        frozen.OperationalAccessDecision.NO_PACKAGE
        if not package.obtained
        else frozen.OperationalAccessDecision.OPERABLE
    )
    return {
        "schema": "stage_10b_access_qualification_v1",
        "candidate": frozen.CANDIDATE_ID,
        "gate": frozen.PreflightGate.ACQUISITION_ACCESS.value,
        "gate_status": result.status.value,
        "gate_summary": result.summary,
        "operational_access_decision": decision.value,
        "operational_access_is_not_research_use": True,
        "research_use_decision_owner": "stage_8e",
        "research_use_blocked_by_this_stage": False,
        "acquisition_route": {
            "self_service_download": route.self_service_download,
            "request_channel": route.request_channel,
            "vendor_acceptance_required": route.vendor_acceptance_required,
            "delivers_package": route.delivers_package,
            "delivers_activation_key": route.delivers_activation_key,
            "activation_is_hardware_bound": route.activation_is_hardware_bound,
            "license_file_required_before_any_api_call": (
                route.license_file_required_before_any_api_call
            ),
            "supporting_locators": list(route.supporting_locators),
        },
        "acquisition_checklist": [
            {"requirement": requirement, "established": False}
            for requirement in frozen.ACQUISITION_CHECKLIST
        ],
        "acquisition_checklist_stops_at": frozen.ACQUISITION_CHECKLIST[0],
        "acquisition_state": {
            "status": package.status.value,
            "package_obtained": package.obtained,
            "frozen_package_identity_available": package.frozen_identity_available,
            "local_artifact_store_resolvable": package.store_resolvable,
            "local_artifact_store_holds_material": package.store_holds_material,
            "findings": list(package.findings),
            "request_made_by_this_project": False,
            "vendor_refused": False,
        },
        "license_state": {
            "license_present": licence.license_present,
            "activation_attempted": licence.activation_attempted,
            "activation_verified": licence.activation_verified,
            "required_modules_confirmed_enabled": False,
            "usable_for_local_research": None,
        },
        "runtime_target": {
            "locked": False,
            "fields_that_must_be_recorded_at_activation": list(
                frozen.RUNTIME_TARGET_FIELDS
            ),
            "admissible_targets": [
                {"operating_system": system, "architecture": architecture}
                for system, architecture in frozen.ADMISSIBLE_RUNTIME_TARGETS
            ],
            "chosen_target": None,
            "why_not_chosen": (
                "The evaluation licence is single-platform, so the target is a "
                "decision taken before activation. No activation has been "
                "attempted, so no target has been locked, and alternating "
                "between two platforms under one algorithm fingerprint is "
                "refused whichever one is eventually chosen (spec section 33)."
            ),
        },
        "third_party_components": {
            "components_obtained": 0,
            "stage_8e_usage_manifest_written": False,
            "why": (
                "Stage 8E's own model refuses a manifest with no components, "
                "because a manifest that describes nothing describes nothing. "
                "The SDK package, its models and its licence are third-party "
                "components and will be enrolled as such when one of them "
                "exists (spec section 7)."
            ),
            "component_kinds_that_would_be_enrolled": [
                "the SDK package archive",
                "each model artifact the extractor loads",
                "the activated licence file, which is stored locally and never "
                "described by its bytes",
            ],
        },
        "secrets_recorded_here": 0,
        "publishable_license_facts": list(frozen.PUBLISHABLE_LICENSE_FACTS),
        "notes": [
            "This gate is the stage's fail-fast. It costs one reading and it "
            "decides whether eight further gates are answerable at all "
            "(docs/adr/0095).",
            "A refusal here is about access, not about the vendor's terms. "
            "Nothing in this document says the licence forbids research use, "
            "and nothing in it would change if it permitted every use.",
        ],
    }


def license_capability_report_document(
    preflight: Id3Preflight,
) -> Mapping[str, Any]:
    """Gate 2's second document, and the arithmetic Gate 8 would have run."""
    result = preflight.result(frozen.PreflightGate.ACQUISITION_ACCESS)
    workload_result = preflight.result(frozen.PreflightGate.WORKLOAD_FEASIBILITY)
    licence = license_capability_state()
    budget = workload_budget()
    terms = observed.EVALUATION_TERMS
    return {
        "schema": "stage_10b_license_capability_report_v1",
        "candidate": frozen.CANDIDATE_ID,
        "gate": frozen.PreflightGate.ACQUISITION_ACCESS.value,
        "gate_status": result.status.value,
        "workload_feasibility_gate_status": workload_result.status.value,
        "capacity_status": licence.capacity.value,
        "capacity_admits_candidate": licence.capacity.admits_candidate,
        "capacity_basis": licence.basis,
        "advertised_evaluation": {
            "offered": terms.offered,
            "duration_days": terms.duration_days,
            "api_call_limit_statement": terms.api_call_limit_statement,
            "api_call_limit_is_numeric": terms.api_call_limit_is_numeric,
            "platform_limit_statement": terms.platform_limit_statement,
            "metering_semantics_published": terms.metering_semantics_published,
            "locator": terms.locator,
        },
        "questions_a_licence_must_answer": list(frozen.LICENSE_CAPACITY_QUESTIONS),
        "none_of_these_questions_is_answered_by_a_public_page": True,
        "frozen_workload": {
            "participating_images": budget.workload.participating_images,
            "extractions": budget.workload.extractions,
            "comparisons": budget.workload.comparisons,
            "qualification_operations_upper_bound": (
                budget.workload.qualification_operations_upper_bound
            ),
            "total_metered_operations_upper_bound": (
                budget.workload.total_metered_operations_upper_bound
            ),
        },
        "cost_under_each_metering_semantics": dict(
            budget.costs_by_metering_semantics
        ),
        "workload_budget_resolved": budget.resolved,
        "workload_budget_basis": budget.basis,
        "publishable_license_facts": {
            "license_type": licence.license_type,
            "enabled_module_names": list(licence.enabled_module_names),
            "expiry_category": licence.expiry_category,
            "remaining_days_category": licence.remaining_days_category,
            "sufficient_for_declared_workload": (
                licence.sufficient_for_declared_workload
            ),
        },
        "every_publishable_fact_is_null_because_no_licence_exists": True,
        "notes": [
            "The workload was frozen before the capacity was asked about, and "
            "not after. A run that is trimmed to fit a quota is a different "
            "protocol reported under the same name (docs/adr/0096).",
            "'We will try it and see' is refused explicitly. A quota exhausted "
            "at comparison four thousand leaves two thousand comparisons that "
            "were never run and a result that cannot be published.",
        ],
    }


def sdk_package_manifest_document(preflight: Id3Preflight) -> Mapping[str, Any]:
    """Gate 3's first document: the identity a delivered package would need."""
    document = dict(
        _not_reached(
            preflight,
            frozen.PreflightGate.PACKAGE_IDENTITY,
            "stage_10b_sdk_package_manifest_v1",
        )
    )
    document["package_obtained"] = False
    document["bytes_downloaded"] = 0
    document["artifact_store_environment_variable"] = "FPBENCH_THIRD_PARTY_ROOT"
    document["manifests_hold_no_absolute_path"] = True
    document["identity_fields_that_would_have_to_be_recorded"] = [
        "delivered package filename",
        "byte size",
        "SHA-256",
        "exact platform and architecture",
        "Python binding version",
        "native library version, read from the running library",
    ]
    document["a_documentation_version_is_not_a_binary_identity"] = True
    document["publicly_documented_version_observed"] = (
        observed.PRODUCT_IDENTITY_CLAIM.declared_sdk_version_public
    )
    document["observations_recorded_before_the_stop"] = observed.observation_rows(
        observed.DOCUMENTATION_OBSERVATIONS
    )
    document["these_observations_are_not_a_gate_conclusion"] = True
    document["notes"] = [
        "The words 'current' and 'latest' identify nothing and are refused as "
        "identities. So is the version printed on a documentation page: the "
        "version that matters is the one the delivered library reports at "
        "runtime (spec section 8).",
    ]
    return document


def model_artifact_manifest_document(preflight: Id3Preflight) -> Mapping[str, Any]:
    """Gate 3's second document: the transitive model closure, unclosed."""
    document = dict(
        _not_reached(
            preflight,
            frozen.PreflightGate.PACKAGE_IDENTITY,
            "stage_10b_model_artifact_manifest_v1",
        )
    )
    document["models_obtained"] = 0
    document["inventory_closed"] = False
    document["artifact_classes_that_must_be_inventoried"] = [
        "native libraries",
        "Python wheels or packages",
        "minutia detector models",
        "minutia encoder models",
        "finger-embedding models, if the delivered package has any",
        "any configuration or model resource loaded transitively",
    ]
    document["recorded_per_artifact"] = [
        "sha256",
        "size_bytes",
        "role",
        "local placement relative to the artifact store",
    ]
    document["embedded_model_marker"] = "EMBEDDED_IN_PINNED_BINARY"
    document["model_names_visible_in_public_sources"] = list(
        observed.REQUIRED_MODEL_NAMES
    )
    document["model_names_are_not_model_identities"] = True
    document["observations_recorded_before_the_stop"] = observed.observation_rows(
        observed.MODEL_OBSERVATIONS + observed.EXTRACTION_OBSERVATIONS
    )
    document["these_observations_are_not_a_gate_conclusion"] = True
    document["notes"] = [
        "The vendor's samples state that model download addresses live in the "
        "SDK's own developer guide, which ships inside the package. The model "
        "set therefore cannot be enumerated without the package, let alone "
        "closed over by digest (spec section 10).",
        "A model whose bytes live inside a pinned native library is recorded as "
        "EMBEDDED_IN_PINNED_BINARY rather than left out of the inventory.",
    ]
    return document


def input_domain_contract_document(preflight: Id3Preflight) -> Mapping[str, Any]:
    """Gate 4's document: how canonical_500 would reach the SDK, if it could."""
    document = dict(
        _not_reached(
            preflight,
            frozen.PreflightGate.INPUT_DOMAIN,
            "stage_10b_input_domain_contract_v1",
        )
    )
    document["benchmark_input"] = {
        "profile": frozen.BENCHMARK_INPUT_PROFILE,
        "ppi": frozen.BENCHMARK_INPUT_PPI,
        "pixel_format": frozen.BENCHMARK_INPUT_PIXEL_FORMAT,
    }
    document["required_route"] = [
        "canonical_500 gray8",
        "the SDK's own image type",
        "an explicit 500 ppi resolution on that image",
        "template creation",
    ]
    document["fpbench_crop_resize_or_rotation"] = False
    document["single_finger_route_status"] = (
        frozen.SingleFingerRouteStatus.NOT_REACHED.value
    )
    document["sd300b_1000_ppi_offered_to_this_candidate"] = False
    document["sd300c_2000_ppi_offered_to_this_candidate"] = False
    document["sd300_bytes_read"] = False
    document["observations_recorded_before_the_stop"] = observed.observation_rows(
        observed.ROUTE_OBSERVATIONS
    )
    document["these_observations_are_not_a_gate_conclusion"] = True
    document["what_would_have_had_to_be_established"] = [
        "that the SDK's image type accepts 8-bit grayscale pixels as the "
        "benchmark already produces them",
        "that the resolution is declared as 500 ppi rather than inferred",
        "that a single already-segmented impression has a documented route, and "
        "which one: straight to template creation, or through detection and ROI "
        "extraction first",
    ]
    document["refused_constructions"] = [
        "choosing a crop because the slap sample crops",
        "resampling canonical_500 to some other resolution to suit a model",
        "selecting a region of interest by any rule fpbench invented",
    ]
    document["if_the_single_finger_route_were_undefined"] = (
        frozen.BlockerCode.SINGLE_FINGER_INPUT_ROUTE_UNRESOLVED.value
    )
    document["notes"] = [
        "The public single-image sample performs no detection and no ROI "
        "extraction, and the product page's headline sample does both because it "
        "starts from a four-finger slap. Two published routes exist and this "
        "benchmark's inputs fit one of them; which one the delivered package "
        "documents for a single finger is a question for the delivered package "
        "(spec sections 13 and 14).",
        "canonical_500 is already 500 ppi 8-bit grayscale, which is the "
        "resolution the SDK's processors require. That is a reason to expect the "
        "gate to pass, and it is not the gate passing.",
    ]
    return document


def extraction_profile_document(preflight: Id3Preflight) -> Mapping[str, Any]:
    """Gate 5's document: what would have to be frozen about extraction."""
    document = dict(
        _not_reached(
            preflight,
            frozen.PreflightGate.EXTRACTION_PROFILE,
            "stage_10b_extraction_profile_v1",
        )
    )
    document["profile_frozen"] = False
    document["fields_that_must_be_frozen"] = [
        "template format",
        "finger data formats",
        "detector model",
        "encoder model",
        "finger-embedding model, if the delivered package has one",
        "thread count",
        "every extraction flag and its value",
    ]
    document["published_options"] = [
        {
            "name": item.name,
            "published_meaning": item.published_meaning,
            "documented_default": item.documented_default,
            "is_score_affecting": item.is_score_affecting,
        }
        for item in observed.PUBLISHED_EXTRACTOR_OPTIONS
    ]
    document["options_with_no_documented_default"] = [
        item.name
        for item in observed.PUBLISHED_EXTRACTOR_OPTIONS
        if item.documented_default is None
    ]
    document["fusion_selection_from_vendor_reported_accuracy"] = False
    document["profile_source_must_be"] = (
        "the documented default single-finger route of the delivered package"
    )
    document["observations_recorded_before_the_stop"] = observed.observation_rows(
        observed.EXTRACTION_OBSERVATIONS
    )
    document["these_observations_are_not_a_gate_conclusion"] = True
    document["notes"] = [
        "The vendor reports four fusion combinations and recommends one by "
        "sensor size. Those figures explain the product; choosing the variant "
        "with the better reported error rate would be fpbench selecting a "
        "configuration on results, which is the thing the whole preflight "
        "exists to prevent (spec section 16, docs/adr/0097).",
        "'Use the full id3 somehow' is not a profile. Either every one of the "
        "fields above has a recorded value and a provenance, or the gate fails.",
    ]
    return document


def matcher_profile_document(preflight: Id3Preflight) -> Mapping[str, Any]:
    """Gate 6's document: every matcher option, and what is known about each."""
    document = dict(
        _not_reached(
            preflight,
            frozen.PreflightGate.MATCHER_PROFILE,
            "stage_10b_matcher_profile_v1",
        )
    )
    document["profile_frozen"] = False
    document["required_per_option"] = [
        "observed runtime value",
        "documented default",
        "chosen value",
        "provenance",
    ]
    document["published_options"] = [
        {
            "name": item.name,
            "published_meaning": item.published_meaning,
            "documented_default": item.documented_default,
            "observed_runtime_value": None,
            "chosen_value": None,
            "provenance": None,
            "is_score_affecting": item.is_score_affecting,
        }
        for item in observed.PUBLISHED_MATCHER_OPTIONS
    ]
    document["options_with_no_documented_default"] = [
        item.name
        for item in observed.PUBLISHED_MATCHER_OPTIONS
        if item.documented_default is None
    ]
    document["undocumented_runtime_default_label"] = "DELIVERED_SDK_DEFAULT"
    document["minex_only_is_not_the_research_default"] = True
    document["minex_only_would_be_a_separate_algorithm_profile"] = True
    document["hidden_score_affecting_defaults_resolved"] = False
    document["observations_recorded_before_the_stop"] = observed.observation_rows(
        observed.MATCHER_OBSERVATIONS
    )
    document["these_observations_are_not_a_gate_conclusion"] = True
    document["notes"] = [
        "All five published matcher options are score-affecting and none of them "
        "carries a documented default. A value read from the delivered package "
        "would be recorded as a DELIVERED_SDK_DEFAULT — a fact about that "
        "package — and never as a documented fact (spec section 17).",
        "minexOnly is not switched on or off to make this route look different "
        "from NBIS. If a MINEX-only configuration is ever wanted it is a "
        "separate algorithm profile with its own identity (spec section 19).",
    ]
    return document


def score_contract_document(preflight: Id3Preflight) -> Mapping[str, Any]:
    """Gate 7's document: the raw-score requirements, and what was observed."""
    document = dict(
        _not_reached(
            preflight,
            frozen.PreflightGate.RAW_SCORE_ROUTE,
            "stage_10b_score_contract_v1",
        )
    )
    document["raw_score_route_status"] = frozen.RawScoreRouteStatus.NOT_REACHED.value
    document["chosen_comparison_api"] = None
    document["apis_may_not_be_mixed"] = True
    document["requirements_this_gate_would_have_applied"] = list(
        frozen.SCORE_CONTRACT_REQUIREMENTS
    )
    document["self_semantics_requirements"] = list(
        frozen.SELF_SEMANTICS_REQUIREMENTS
    )
    document["self_independent_extraction_required"] = True
    document["pair_order_symmetry_established"] = False
    document["fpbench_may_symmetrise_a_pairwise_score"] = False
    document["threshold_in_raw_route"] = False
    document["vendor_threshold_constants_are_not_part_of_the_raw_route"] = True
    document["zero_is_a_valid_score_and_never_a_failure_sentinel"] = True
    document["nan_or_infinity_applies_to_an_integer_score"] = False
    document["a_failure_is_carried_by_an_outcome_and_never_by_a_number"] = True
    document["failure_classes_that_must_be_mapped"] = [
        "image decode",
        "model loading",
        "template extraction",
        "matching",
        "licence",
    ]
    document["extraction_failure_may_become_a_score"] = False
    document["publicly_documented_score"] = {
        "type": "integer",
        "range_min": observed.DOCUMENTED_SCORE_RANGE_MIN,
        "range_max": observed.DOCUMENTED_SCORE_RANGE_MAX,
        "direction": observed.DOCUMENTED_SCORE_DIRECTION,
        "this_is_an_observation_not_a_contract": True,
    }
    document["observations_recorded_before_the_stop"] = observed.observation_rows(
        observed.SCORE_OBSERVATIONS
    )
    document["these_observations_are_not_a_gate_conclusion"] = True
    document["notes"] = [
        "The public documentation and the vendor's own sample both describe an "
        "integer in 0..65535 with the threshold applied afterwards, which is the "
        "shape this project needs. It is recorded as an observation because the "
        "gate that would settle it was never reached, and because a contract is "
        "settled against the delivered package's documentation (spec section 8).",
        "SELF(A, A) is frozen here even though the adapter that will obey it "
        "belongs to Stage 10C: two independent extractions, no path-equality "
        "shortcut, no constant (docs/adr/0070, spec section 24).",
    ]
    return document


def training_provenance_document(preflight: Id3Preflight) -> Mapping[str, Any]:
    """Gate 9's document: what the vendor discloses, and what it does not."""
    document = dict(
        _not_reached(
            preflight,
            frozen.PreflightGate.TRAINING_PROVENANCE,
            "stage_10b_training_provenance_v1",
        )
    )
    document["training_provenance_status"] = (
        frozen.TrainingProvenanceStatus.NOT_REACHED.value
    )
    document["expected_status_for_a_proprietary_product"] = (
        frozen.TrainingProvenanceStatus.PROPRIETARY_UNDISCLOSED.value
    )
    document["full_training_corpus_disclosure_is_not_required"] = True
    document["sd300_overlap_status"] = frozen.SD300OverlapStatus.NOT_REACHED.value
    document["expected_sd300_overlap_status"] = (
        frozen.SD300OverlapStatus.NO_EVIDENCE_FOUND.value
    )
    document["no_evidence_found_is_not_proven_absent"] = True
    document["sd300_data_read_by_this_stage"] = False
    document["public_evaluation_datasets_named_by_the_vendor"] = [
        "FVC2000",
        "FVC2002",
        "FVC2004",
        "MINEX interoperable minutiae",
    ]
    document["an_evaluation_dataset_is_not_a_training_dataset"] = True
    document["observations_recorded_before_the_stop"] = observed.observation_rows(
        observed.PROVENANCE_OBSERVATIONS
    )
    document["these_observations_are_not_a_gate_conclusion"] = True
    document["notes"] = [
        "A commercial vendor is not asked to disclose its training corpus as a "
        "condition of entry; that condition would exclude every commercial "
        "matcher by accident rather than by decision. What is recorded is what "
        "is public, what is undisclosed, and the SD300 overlap status "
        "(spec section 29).",
    ]
    return document


def runtime_smoke_document(preflight: Id3Preflight) -> Mapping[str, Any]:
    """Gate 10's document: the bounded smoke, and that it did not run."""
    document = dict(
        _not_reached(
            preflight,
            frozen.PreflightGate.LOCAL_SMOKE,
            "stage_10b_runtime_smoke_v1",
        )
    )
    document["smoke_executed"] = False
    document["binding_imported"] = False
    document["library_version_read_at_runtime"] = False
    document["license_checked"] = False
    document["models_loaded"] = 0
    document["templates_created"] = 0
    document["scores_produced"] = 0
    document["process_restarts"] = 0
    document["restart_determinism_verified"] = False
    document["sd300_images_used"] = False
    document["steps_the_smoke_would_run"] = list(frozen.LOCAL_SMOKE_STEPS)
    document["fixture_policy"] = {
        "default": "synthetic ridge-like images generated into a temporary directory",
        "fallback": (
            "if the SDK refuses to extract a template from a synthetic image, an "
            "official sample fingerprint shipped inside the evaluation package "
            "may be used locally for structural smoke only"
        ),
        "fallback_copied_into_git_or_evidence": False,
        "fallback_score_published": False,
    }
    document["determinism_rule"] = (
        "the integer score for one pair under one exact route is bit-identical "
        "within a process and across a restart; anything else is "
        f"{frozen.BlockerCode.SCORE_NONDETERMINISM_OBSERVED.value} and a "
        "failure, unless the vendor documents stochastic inference explicitly — "
        "which would be its own stage, not an allowance inside this one"
    )
    document["this_is_not_a_production_adapter"] = True
    document["notes"] = [
        "The smoke is the tenth gate and runs only after the nine above it. It "
        "is bounded on purpose: one pair, two extractions, two scores and a "
        "restart (spec section 30).",
    ]
    return document


def preflight_report_document(preflight: Id3Preflight) -> Mapping[str, Any]:
    """The verdict, gate by gate, with every blocker named."""
    return {
        "schema": "stage_10b_preflight_report_v1",
        "candidate": frozen.CANDIDATE_ID,
        "implementation_origin": frozen.IMPLEMENTATION_ORIGIN,
        "verdict": preflight.verdict,
        "outcome": preflight.outcome,
        "passed_every_hard_gate": preflight.passed,
        "stopped_at_gate": (
            preflight.stopped_at.value if preflight.stopped_at else None
        ),
        "gate_count_defined": frozen.GATE_COUNT,
        "gates_reached": preflight.gates_reached,
        "decisive_question": (
            "Does this project hold an exact, licensed, operable copy of the id3 "
            "Finger SDK that defines a complete 1:1 route from canonical_500 to "
            "a raw score?"
        ),
        "decisive_answer": "NO",
        "decisive_answer_basis": (
            "The vendor publishes no self-service download. Its own samples "
            "state that the archive and the activation key are issued together "
            "after a request has been accepted, and that the SDK checks a "
            "licence file before any other call. No request has been made from "
            "this project, so there is no package, no licence and no route — and "
            "the advertised evaluation quota is a phrase without a number, which "
            "could not be checked against the frozen workload even if there were."
        ),
        "gates": [
            {
                "order": index,
                "gate": result.gate.value,
                "status": result.status.value,
                "summary": result.summary,
                "documents": list(frozen.gate_documents(result.gate)),
                "blocker_codes": [
                    blocker.blocker_code.value for blocker in result.blockers
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
        "no_workaround_was_considered": [
            "no licence bypass",
            "no trial reset",
            "no third-party redistribution of the package",
            "no reconstruction of the algorithm from documentation",
        ],
        "what_this_candidate_cost": {
            "package_bytes_downloaded": 0,
            "model_bytes_downloaded": 0,
            "licences_activated": 0,
            "runtime_environments_built": 0,
            "sd300_images_read": 0,
            "scores_produced": 0,
        },
        "acceptance_conditions": list(_ACCEPTANCE_CONDITIONS),
        "acceptance_conditions_are_conjunctive": True,
        "acceptance_conditions_met": preflight.passed,
    }


#: The conjunction the user set as the bar for admitting id3 as Algorithm 4.
#: Published so that a later run is measured against a written rule rather than
#: against whatever seems reasonable at the time.
_ACCEPTANCE_CONDITIONS: tuple[str, ...] = (
    "an exact official package exists here",
    "the licence is actually usable",
    "the quota covers the complete frozen workload",
    "every required model is known",
    "canonical_500 enters without an invented transformation",
    "the single-finger route is authoritative",
    "every extraction option is frozen",
    "every matcher option is frozen",
    "one raw score exists, free of any external threshold",
    "SELF can be executed as two independent extractions",
    "pair order is understood",
    "the score is restart-deterministic",
    "no SD300 was consulted",
)


_DOCUMENT_BUILDERS = {
    frozen.CANDIDATE_IDENTITY_NAME: lambda preflight: candidate_identity_document(),
    frozen.PUBLIC_PRODUCT_OBSERVATIONS_NAME: public_product_observations_document,
    frozen.ACCESS_QUALIFICATION_NAME: access_qualification_document,
    frozen.SDK_PACKAGE_MANIFEST_NAME: sdk_package_manifest_document,
    frozen.LICENSE_CAPABILITY_REPORT_NAME: license_capability_report_document,
    frozen.MODEL_ARTIFACT_MANIFEST_NAME: model_artifact_manifest_document,
    frozen.INPUT_DOMAIN_CONTRACT_NAME: input_domain_contract_document,
    frozen.EXTRACTION_PROFILE_NAME: extraction_profile_document,
    frozen.MATCHER_PROFILE_NAME: matcher_profile_document,
    frozen.SCORE_CONTRACT_NAME: score_contract_document,
    frozen.TRAINING_PROVENANCE_NAME: training_provenance_document,
    frozen.RUNTIME_SMOKE_NAME: runtime_smoke_document,
    frozen.PREFLIGHT_REPORT_NAME: preflight_report_document,
}


def evidence_document(preflight: Id3Preflight, name: str) -> Mapping[str, Any]:
    """One derivable document by file name, with the secret guard applied.

    Every document passes the guard before any caller sees it, so a document
    that acquired a credential cannot be written even by a caller that never
    checked (docs/adr/0098).
    """
    builder = _DOCUMENT_BUILDERS.get(name)
    if builder is None:
        raise Id3GateError(f"{name!r} is not a derivable Stage 10B document")
    document = builder(preflight)
    require_no_sensitive_material(document, where=name)
    return document


def marker_blocker_rows(
    blockers: Sequence[Blocker],
) -> tuple[Mapping[str, str], ...]:
    """The blockers in exactly the shape the marker stores them.

    Keys sorted and rows sorted, because the marker normalises both and then
    fingerprints itself. Building the claims through this function is what makes
    the normalisation a no-op rather than a silent rewrite.
    """
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
