"""The seven hard gates, run in order, and the selection that follows.

The engine has no verdict parameter, for the reason Stage 8E's decision engine
has none and Stage 9A's qualification has none: an engine that accepted an
outcome and then validated it would be a very elaborate way of writing the
outcome down. It reads
:mod:`fpbench.experiments.stage10a_candidate_evidence`, applies the gate order
frozen in :mod:`fpbench.experiments.stage10a_candidate_identity`, and reports
what follows.

**Fail-fast is the design, not an optimisation.** A candidate stops at the first
gate it fails, and every later gate is published ``NOT_REACHED``. That is why
identity and input domain come first: both can be settled by reading, and
settling either negatively means several hundred megabytes of checkpoint are
never fetched and a runtime is never built (docs/adr/0089).

**A gate is never weighted.** There is no score, no total and no threshold at
which enough gates make a candidate acceptable. Selection happens only among
candidates that passed all seven, and among those it uses an ordered list of
criteria that deliberately excludes accuracy reported by the authors
(docs/adr/0093).

Nothing here reads SD300, reads a prior algorithm's scores, downloads a
checkpoint, imports a runtime, or produces a number.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from fpbench.core.algorithm4_errors import (
    PreflightGateError,
    Stage10AFinalizationError,
)
from fpbench.core.serialization import stable_hash
from fpbench.core.third_party_models import (
    LicenseEvidence,
    LicenseObservation,
    LicenseObservationStatus,
    LocalArtifactPlacement,
    NonBlockingRestriction,
    RedistributionDecision,
    ResearchUseAssessment,
    ThirdPartyComponentKind,
    ThirdPartyUsageManifest,
    ThirdPartyUsageRecord,
    UpstreamIdentity,
)
from fpbench.experiments import stage10a_candidate_evidence as observed
from fpbench.experiments import stage10a_candidate_identity as frozen
from fpbench.third_party import (
    assess_research_use,
    build_placement,
    build_usage_manifest,
    build_usage_record,
    policy_fingerprint,
    project_purpose,
    resolve_placement_path,
    resolve_third_party_root,
    verify_placed_artifact,
    verify_usage_record,
)

__all__ = [
    "MANIFEST_ID",
    "Blocker",
    "GateResult",
    "CandidatePreflight",
    "PreflightOutcome",
    "require_stage8e_is_the_policy_this_reuses",
    "acquired_components",
    "build_usage_audit",
    "placement_for_source_archive",
    "source_archive_status",
    "run_gate_identity",
    "run_gate_input_domain",
    "run_candidate_preflight",
    "run_preflight",
    "candidate_set_document",
    "candidate_document",
    "preflight_report_document",
    "candidate_comparison_document",
    "marker_blocker_rows",
    "usage_manifest_document",
    "audit_tracked_bytes_against_candidate_artifacts",
    "require_no_candidate_bytes_in_git",
    "TrackedByteAudit",
    "TrackedByteFinding",
]

MANIFEST_ID = "algorithm4_preflight_third_party_usage"


# ------------------------------------------------------------ the closed stage


def require_stage8e_is_the_policy_this_reuses(repository_root: Path) -> None:
    """Confirm the policy Stage 10A calls is the policy it was written against.

    Three checks, each catching a different way this could go wrong: the
    published Stage 8E marker still says what it said, the live purpose and
    policy still fingerprint to what that marker recorded, and Stage 8E still
    declares the research-only policy ready.

    Raises:
        Stage10AFinalizationError: any of the three disagrees. Stage 10A does
            not repair Stage 8E and does not proceed around it — a corrective
            policy stage is the response, not a quiet edit from here.
    """
    relative = "evidence/stage8e-research-only-policy/stage-8e-finalization.json"
    path = Path(repository_root) / PurePosixPath(relative)
    try:
        marker = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Stage10AFinalizationError(
            f"cannot read the Stage 8E marker Stage 10A reuses at {relative}: {exc}"
        ) from exc
    if not isinstance(marker, dict):
        raise Stage10AFinalizationError("the Stage 8E marker is not a JSON object")

    expected = {
        "outcome": frozen.STAGE8E_OUTCOME,
        "stage_8e_finalization_fingerprint": frozen.STAGE8E_FINALIZATION_FINGERPRINT,
        "purpose_fingerprint": frozen.STAGE8E_PURPOSE_FINGERPRINT,
        "policy_fingerprint": frozen.STAGE8E_POLICY_FINGERPRINT,
    }
    for key, value in expected.items():
        found = marker.get(key)
        if found != value:
            raise Stage10AFinalizationError(
                f"the Stage 8E marker's {key} is {found!r} and Stage 10A was "
                f"written against {value!r}. Stage 8E is a closed stage; a "
                "capability it lacks is a corrective policy stage, not an edit "
                "from here"
            )

    declaration = project_purpose()
    if declaration.purpose_fingerprint != frozen.STAGE8E_PURPOSE_FINGERPRINT:
        raise Stage10AFinalizationError(
            "the live project purpose no longer fingerprints to what Stage 8E "
            "published; every Stage 10A decision would be taken under a "
            "different premise"
        )
    if policy_fingerprint() != frozen.STAGE8E_POLICY_FINGERPRINT:
        raise Stage10AFinalizationError(
            "the live third-party policy no longer fingerprints to what Stage 8E "
            "published"
        )


# ---------------------------------------------------- Stage 8E over what was used

#: Exactly one third-party component was acquired by Stage 10A: the JIPNet
#: source archive, which is what the identity gate rests on. No checkpoint was
#: fetched for either candidate, because neither reached the artifact gate. A
#: record for something nobody obtained would be a record of nothing.
_SOURCE_ARCHIVE_ID = "jipnet_source_archive"

_SOURCE_BASIS = (
    "The repository carries one coherent notice, the MIT licence, which permits "
    "use without restricting the field of endeavour. Local execution for "
    "personal educational research follows from the notice and needs no "
    "intersection and no risk acceptance (docs/adr/0082)."
)

_SOURCE_REDISTRIBUTION_BASIS = (
    "MIT permits redistribution with the notice retained. This project "
    "redistributes nothing regardless (docs/adr/0083)."
)


def _source_archive_relative_location() -> str:
    return (
        f"{frozen.ARTIFACT_STORE_PREFIX}/jipnet/source/"
        f"{observed.JIPNET_REPOSITORY.archive_filename}"
    )


def _source_upstream_identity() -> UpstreamIdentity:
    repository = observed.JIPNET_REPOSITORY
    return UpstreamIdentity(
        upstream_name=repository.upstream_name,
        upstream_locator=repository.archive_locator,
        exact_version=repository.commit,
        upstream_commit=repository.commit,
        artifact_filename=repository.archive_filename,
        artifact_sha256=repository.archive_sha256,
        artifact_size_bytes=repository.archive_size_bytes,
        identity_established=True,
    )


def _source_observation() -> LicenseObservation:
    repository = observed.JIPNET_REPOSITORY
    return LicenseObservation(
        observation_id=f"{_SOURCE_ARCHIVE_ID}_observation",
        component_kind=ThirdPartyComponentKind.SOURCE_CODE,
        subject=(
            "the XiongjunGuan/JIPNet source tree at the pinned commit, including "
            "the official inference route and the reproduced comparison routes"
        ),
        status=LicenseObservationStatus.OPEN_SOURCE_PERMISSIVE,
        declared_license_names=("MIT License",),
        spdx_identifiers=("MIT",),
        evidence=(
            LicenseEvidence(
                locator=(
                    f"{repository.html_locator}/blob/{repository.commit}/LICENSE"
                ),
                description="the repository LICENSE file, the MIT licence text",
                document_sha256=repository.license_document_sha256,
            ),
            LicenseEvidence(
                locator=(
                    f"{repository.html_locator}/blob/{repository.commit}/README.md"
                ),
                description=(
                    "the repository README, whose License section states the "
                    "project is released under the MIT licence"
                ),
                document_sha256=repository.readme_document_sha256,
            ),
        ),
        stated_restrictions=(
            "MIT requires the copyright notice and permission notice to be "
            "retained in copies or substantial portions of the software.",
        ),
    )


def acquired_components() -> tuple[str, ...]:
    """Every third-party component Stage 10A actually obtained."""
    return (_SOURCE_ARCHIVE_ID,)


@dataclass(frozen=True, slots=True)
class UsageAudit:
    """The Stage 8E record for what Stage 10A obtained, verified."""

    observation: LicenseObservation
    assessment: ResearchUseAssessment
    record: ThirdPartyUsageRecord
    manifest: ThirdPartyUsageManifest
    audit_fingerprint: str

    @property
    def opens_execution(self) -> bool:
        return self.assessment.decision.opens_execution


def build_usage_audit() -> UsageAudit:
    """Run the one component through the engine Stage 8E froze.

    Raises:
        Stage10AFinalizationError: the mapping does not survive its own
            re-derivation. Publishing a decision nobody checked would be worse
            than publishing none.
    """
    observation = _source_observation()
    assessment = assess_research_use(
        observation,
        assessment_id=f"{_SOURCE_ARCHIVE_ID}_research_use",
        basis=_SOURCE_BASIS,
        non_blocking_restrictions=(
            NonBlockingRestriction.ATTRIBUTION_AND_NOTICE_RETENTION,
        ),
        identity_established=True,
    )
    record = build_usage_record(
        record_id=_SOURCE_ARCHIVE_ID,
        observation=observation,
        assessment=assessment,
        upstream_identity=_source_upstream_identity(),
        redistribution_decision=RedistributionDecision.CONDITIONAL,
        redistribution_basis=_SOURCE_REDISTRIBUTION_BASIS,
        notes=(
            "Acquired twice from the same locator and byte-identical both "
            "times. Read to answer the identity and input-domain gates; not "
            "executed, because neither candidate reached a gate that would run "
            "anything.",
        ),
    )
    report = verify_usage_record(record, observation, assessment)
    if not report.verified:
        raise Stage10AFinalizationError(
            f"{_SOURCE_ARCHIVE_ID}: the mapping does not survive re-derivation: "
            f"{report.findings}"
        )
    manifest = build_usage_manifest(
        manifest_id=MANIFEST_ID,
        subject=(
            "every third-party component Stage 10A obtained: one official "
            "source archive, and no checkpoint of either candidate"
        ),
        records=(record,),
    )
    return UsageAudit(
        observation=observation,
        assessment=assessment,
        record=record,
        manifest=manifest,
        audit_fingerprint=stable_hash(
            {
                "schema": "stage_10a_usage_audit_v1",
                "observation": observation.observation_fingerprint,
                "assessment": assessment.assessment_fingerprint,
                "usage": record.usage_fingerprint,
                "manifest": manifest.manifest_fingerprint,
            },
            length=64,
        ),
    )


def placement_for_source_archive() -> LocalArtifactPlacement:
    """Where the pinned source archive belongs, expressed without naming a machine."""
    return build_placement(
        placement_id=f"{_SOURCE_ARCHIVE_ID}_placement",
        component_role="JIPNet source snapshot at the pinned commit",
        component_kind=ThirdPartyComponentKind.SOURCE_CODE,
        relative_location=_source_archive_relative_location(),
        expected_sha256=observed.JIPNET_REPOSITORY.archive_sha256,
        expected_size_bytes=observed.JIPNET_REPOSITORY.archive_size_bytes,
        upstream_identity=_source_upstream_identity(),
    )


@dataclass(frozen=True, slots=True)
class SourceArchiveStatus:
    """What this machine has of the one archive Stage 10A obtained.

    Absence is an ordinary state — it is true of every CI runner by design — so
    it is reported rather than raised. A file of the right name whose bytes are
    different is a finding.
    """

    identity_frozen: bool
    present: bool
    verified: bool
    findings: tuple[str, ...] = ()


def source_archive_status(
    *, root: Path | None = None, repository_root: Path | None = None
) -> SourceArchiveStatus:
    """Look for the pinned archive, without requiring it to be here."""
    try:
        store = (
            Path(root)
            if root is not None
            else resolve_third_party_root(repository_root=repository_root)
        )
    except Exception:  # pragma: no cover - an unusable store is simply absent
        return SourceArchiveStatus(
            identity_frozen=True,
            present=False,
            verified=False,
            findings=("no local artifact store is resolvable here",),
        )
    verification = verify_placed_artifact(placement_for_source_archive(), root=store)
    findings: list[str] = []
    if not verification.present:
        findings.append("absent from the local artifact store")
    else:
        if not verification.size_matches:
            findings.append(
                f"{verification.observed_size_bytes} bytes on disk and "
                f"{observed.JIPNET_REPOSITORY.archive_size_bytes} expected"
            )
        if not verification.digest_matches:
            findings.append("the bytes on disk are not the bytes expected")
    return SourceArchiveStatus(
        identity_frozen=True,
        present=verification.present,
        verified=verification.verified,
        findings=tuple(findings),
    )


def store_path_for_source_archive(*, root: Path) -> Path:
    """The absolute path of the archive on this machine, for a local caller.

    The only function here that produces one, and it goes through Stage 8E's
    resolver so that a location which escaped the store is a refusal rather than
    a read somewhere else on the disk. No value it returns reaches published
    evidence.
    """
    return resolve_placement_path(placement_for_source_archive(), root=Path(root))


# ------------------------------------------------------------------- the gates


@dataclass(frozen=True, slots=True)
class Blocker:
    """One reason a candidate cannot enter fpbench as Algorithm 4.

    Four fields, all mandatory. A blocker nobody can point at is a blocker
    nobody can lift, and a blocker with no stated consequence is an opinion.
    """

    candidate_id: str
    gate: frozen.PreflightGate
    blocker_code: frozen.BlockerCode
    affected_component: str
    evidence: str
    why_this_blocks_algorithm_4: str

    def __post_init__(self) -> None:
        permitted = dict(frozen.GATE_BLOCKERS)[self.gate]
        if self.blocker_code not in permitted:
            raise PreflightGateError(
                f"{self.candidate_id}: {self.blocker_code.value} does not belong "
                f"to {self.gate.value}; it belongs to another gate and raising "
                "it here would put the reason in the wrong place"
            )
        for name in ("affected_component", "evidence", "why_this_blocks_algorithm_4"):
            if not str(getattr(self, name)).strip():
                raise PreflightGateError(
                    f"{self.candidate_id}/{self.blocker_code.value}: {name} is "
                    "empty"
                )


@dataclass(frozen=True, slots=True)
class GateResult:
    """One gate's conclusion for one candidate."""

    candidate_id: str
    gate: frozen.PreflightGate
    status: frozen.GateStatus
    summary: str
    blockers: tuple[Blocker, ...] = ()

    def __post_init__(self) -> None:
        if self.status is frozen.GateStatus.PASS and self.blockers:
            raise PreflightGateError(
                f"{self.candidate_id}/{self.gate.value}: a gate that passed "
                "carries no blockers; a blocker is not a reservation to be "
                "weighed"
            )
        if self.status is frozen.GateStatus.FAIL and not self.blockers:
            raise PreflightGateError(
                f"{self.candidate_id}/{self.gate.value}: a gate that failed "
                "names why"
            )
        if self.status is frozen.GateStatus.NOT_REACHED and self.blockers:
            raise PreflightGateError(
                f"{self.candidate_id}/{self.gate.value}: a gate that was never "
                "reached cannot have found anything"
            )


def run_gate_identity(candidate_id: str) -> GateResult:
    """Gate 1. Is the executable thing the authors' own?

    Two admissible origins and no others. A reproduction — even an excellent
    one, even one published by researchers who read the paper carefully — is not
    the algorithm it reproduces, and an *adjusted* reproduction is not it twice
    over (docs/adr/0090).
    """
    claim = observed.origin_claim(candidate_id)
    if claim.origin.is_admissible_for_algorithm_4:
        return GateResult(
            candidate_id=candidate_id,
            gate=frozen.PreflightGate.IDENTITY,
            status=frozen.GateStatus.PASS,
            summary=(
                f"{claim.origin.value}: {claim.subject}. "
                f"{claim.upstream_self_description}"
            ),
        )

    discovery = observed.afrnet_source_discovery()
    blockers: list[Blocker] = []
    if not discovery["official_source_found"]:
        blockers.append(
            Blocker(
                candidate_id=candidate_id,
                gate=frozen.PreflightGate.IDENTITY,
                blocker_code=frozen.BlockerCode.OFFICIAL_IMPLEMENTATION_NOT_FOUND,
                affected_component="the AFR-Net inference implementation",
                evidence=(
                    "source-discovery.json: ten locations were searched — the "
                    "arXiv listing and the full paper text, the MSU Biometrics "
                    "publication database, its databases and projects pages, the "
                    "first author's GitHub account, a group organisation, GitHub "
                    "repository search, and the code and model indexes — and none "
                    "yielded source published by the authors"
                ),
                why_this_blocks_algorithm_4=(
                    "Without the authors' own code there is nothing to execute "
                    "under the name AFR-Net. Writing one from the paper would "
                    "make fpbench the implementer of an algorithm it then "
                    "reports numbers for (docs/adr/0066)."
                ),
            )
        )
    if not discovery["official_checkpoint_found"]:
        blockers.append(
            Blocker(
                candidate_id=candidate_id,
                gate=frozen.PreflightGate.IDENTITY,
                blocker_code=frozen.BlockerCode.OFFICIAL_CHECKPOINT_NOT_FOUND,
                affected_component="the AFR-Net trained weights",
                evidence=(
                    "source-discovery.json: no author-supplied checkpoint was "
                    "located at any of the ten searched locations; the model and "
                    "code indexes report no model linked to the paper"
                ),
                why_this_blocks_algorithm_4=(
                    "The paper's results come from weights trained on 1.3M "
                    "images this project does not have. Code without those "
                    "weights would be an untrained architecture, which shares a "
                    "name with the published algorithm and nothing else."
                ),
            )
        )
    if observed.AFRNET_EXCLUDED_EVIDENCE:
        blockers.append(
            Blocker(
                candidate_id=candidate_id,
                gate=frozen.PreflightGate.IDENTITY,
                blocker_code=frozen.BlockerCode.THIRD_PARTY_REIMPLEMENTATION_ONLY,
                affected_component=(
                    "the AFR-Net reproduction distributed inside "
                    "XiongjunGuan/JIPNet"
                ),
                evidence=(
                    "authenticity-report.json: the only executable AFR-Net "
                    "located is the one in the JIPNet repository, whose own "
                    "README states the comparison models are reproduced from "
                    "their papers and some were adjusted for partial-fingerprint "
                    "scenarios; the JIPNet paper states that the pose "
                    "rectification used by AFR-Net could not be performed and "
                    "that PFVNet's AlignNet was substituted"
                ),
                why_this_blocks_algorithm_4=(
                    "A reproduction with a substituted component is a different "
                    "algorithm, and running it under the name AFR-Net would "
                    "publish somebody else's approximation under the original "
                    "authors' name. It remains available as a candidate of its "
                    "own, under its own identity (docs/adr/0090)."
                ),
            )
        )
    return GateResult(
        candidate_id=candidate_id,
        gate=frozen.PreflightGate.IDENTITY,
        status=frozen.GateStatus.FAIL,
        summary=(
            f"{claim.origin.value}: {claim.subject}. Accepted origins are "
            f"{[origin.value for origin in frozen.ACCEPTED_ORIGINS]}."
        ),
        blockers=tuple(blockers),
    )


def run_gate_input_domain(candidate_id: str) -> GateResult:
    """Gate 2. Can ``canonical_500`` reach this model's declared input?

    Not "would the tensor fit". The question is whether an upstream authority
    defines the conversion, because a conversion fpbench chose would put
    fpbench's judgement inside a number published under somebody else's method
    name (docs/adr/0091, docs/adr/0092).
    """
    contract = observed.input_domain_contract(candidate_id)
    if contract.resolution.admits_candidate:
        return GateResult(
            candidate_id=candidate_id,
            gate=frozen.PreflightGate.INPUT_DOMAIN,
            status=frozen.GateStatus.PASS,
            summary=(
                f"{contract.resolution.value} under "
                f"{contract.transformation_authority}"
            ),
        )

    declared = contract.declared_input
    geometry = (
        f"{declared.geometry_pixels[0]}x{declared.geometry_pixels[1]}"
        if declared.geometry_pixels
        else "an undeclared geometry"
    )
    return GateResult(
        candidate_id=candidate_id,
        gate=frozen.PreflightGate.INPUT_DOMAIN,
        status=frozen.GateStatus.FAIL,
        summary=(
            f"{contract.resolution.value}: the released model declares a "
            f"{geometry} input and no upstream authority defines how a full "
            f"{frozen.BENCHMARK_INPUT_PPI} ppi fingerprint becomes one."
        ),
        blockers=(
            Blocker(
                candidate_id=candidate_id,
                gate=frozen.PreflightGate.INPUT_DOMAIN,
                blocker_code=frozen.BlockerCode.BENCHMARK_INPUT_ROUTE_UNRESOLVED,
                affected_component=(
                    f"{frozen.BENCHMARK_INPUT_PROFILE} to the declared "
                    f"{geometry} model input"
                ),
                evidence=(
                    "input-domain-contract.json: the official inference script "
                    "reads two images and hands them to the model with no crop "
                    "and no resize, cv2.resize appears nowhere in the "
                    "repository, and the only full-fingerprint-to-patch function "
                    "lives in the training-data construction script"
                ),
                why_this_blocks_algorithm_4=(
                    "There is no published, deterministic, inference-time "
                    "conversion from an arbitrary full fingerprint to the "
                    "required patch. Every comparison fpbench ran would depend "
                    "on a step nobody upstream defined."
                ),
            ),
            Blocker(
                candidate_id=candidate_id,
                gate=frozen.PreflightGate.INPUT_DOMAIN,
                blocker_code=frozen.BlockerCode.FPBENCH_PREPROCESSING_CHOICE_REQUIRED,
                affected_component="the patch construction the route would need",
                evidence=(
                    "input-domain-contract.json: the upstream construction "
                    "samples the patch centre from the common mask of an "
                    "already-aligned genuine pair and applies a rotation drawn "
                    "uniformly from [-180, 180] degrees, and its first step "
                    "cannot run at all because it needs a commercial SDK the "
                    "authors could not release"
                ),
                why_this_blocks_algorithm_4=(
                    "Closing the gap would mean fpbench choosing a crop centre, "
                    "a crop size, a rotation and a border fill. Those are not "
                    "free parameters: they decide which ridges the network sees, "
                    "and therefore they decide the score (docs/adr/0064, "
                    "docs/adr/0092)."
                ),
            ),
            Blocker(
                candidate_id=candidate_id,
                gate=frozen.PreflightGate.INPUT_DOMAIN,
                blocker_code=frozen.BlockerCode.INPUT_DOMAIN_INCOMPATIBLE,
                affected_component=(
                    f"the released model's input domain against "
                    f"{frozen.BENCHMARK_INPUT_PROFILE}"
                ),
                evidence=(
                    "input-domain-contract.json: as released, the model's domain "
                    "is paired partial patches whose crop is a property of the "
                    "pair, and the benchmark's domain is single full 500 ppi "
                    "fingerprints prepared independently of any comparison"
                ),
                why_this_blocks_algorithm_4=(
                    "A benchmark input cannot be a function of the gallery image "
                    "it will be compared against, and this model's input is. "
                    "The two domains differ in what an input *is*, not only in "
                    "its size. This says the released artifact does not fit this "
                    "benchmark, not that no future release could."
                ),
            ),
        ),
    )


_GATE_RUNNERS = {
    frozen.PreflightGate.IDENTITY: run_gate_identity,
    frozen.PreflightGate.INPUT_DOMAIN: run_gate_input_domain,
}

def _unreached_reason(candidate_id: str, stopped_at: frozen.PreflightGate) -> str:
    """Why one gate was never asked of one candidate.

    Per candidate, not per gate. AFR-Net's input-domain gate and JIPNet's are
    both real questions, and only one of them went unasked — a shared sentence
    saying "no candidate reached this gate" would be false about the other
    (spec section 18).
    """
    return (
        f"{candidate_id} stopped at {stopped_at.value}, so this question was "
        "never asked of it and nothing was downloaded, constructed or executed "
        "for it"
    )


def run_candidate_preflight(candidate_id: str) -> "CandidatePreflight":
    """Run the gate order for one candidate and stop at the first failure."""
    item = frozen.candidate(candidate_id)
    results: list[GateResult] = []
    stopped_at: frozen.PreflightGate | None = None
    for gate in frozen.GATE_ORDER:
        if stopped_at is not None:
            results.append(
                GateResult(
                    candidate_id=candidate_id,
                    gate=gate,
                    status=frozen.GateStatus.NOT_REACHED,
                    summary=_unreached_reason(candidate_id, stopped_at),
                )
            )
            continue
        runner = _GATE_RUNNERS.get(gate)
        if runner is None:
            # The candidate is still alive and there is no runner. That is a
            # gate this stage would have had to perform, and did not write,
            # which must never be reported as a pass.
            raise PreflightGateError(  # pragma: no cover - unreachable today
                f"{candidate_id} survived to {gate.value} and Stage 10A has no "
                "runner for it. A gate without a runner is an unanswered "
                "question, not a passed one"
            )
        result = runner(candidate_id)
        results.append(result)
        if result.status is frozen.GateStatus.FAIL:
            stopped_at = gate
    return CandidatePreflight(
        candidate_id=item.candidate_id,
        results=tuple(results),
        stopped_at=stopped_at,
    )


@dataclass(frozen=True, slots=True)
class CandidatePreflight:
    """One candidate's whole preflight: every gate, and the verdict that follows."""

    candidate_id: str
    results: tuple[GateResult, ...]
    stopped_at: frozen.PreflightGate | None

    def __post_init__(self) -> None:
        seen = tuple(result.gate for result in self.results)
        if seen != frozen.GATE_ORDER:
            raise PreflightGateError(
                f"{self.candidate_id}: the gates were reported as {seen} and the "
                f"frozen order is {frozen.GATE_ORDER}"
            )
        failed = [
            result.gate
            for result in self.results
            if result.status is frozen.GateStatus.FAIL
        ]
        if len(failed) > 1:
            raise PreflightGateError(
                f"{self.candidate_id}: fail-fast means one failing gate, and "
                f"these failed: {failed}"
            )
        if failed and failed[0] is not self.stopped_at:
            raise PreflightGateError(
                f"{self.candidate_id}: the stopping gate is {self.stopped_at} "
                f"and the failing gate is {failed[0]}"
            )
        if not failed and self.stopped_at is not None:
            raise PreflightGateError(
                f"{self.candidate_id}: stopped at {self.stopped_at} with no "
                "failing gate"
            )

    @property
    def identity(self) -> frozen.CandidateIdentity:
        return frozen.candidate(self.candidate_id)

    @property
    def passed(self) -> bool:
        """Every gate passed. Not "no gate failed": a NOT_REACHED gate is not a pass."""
        return all(
            result.status is frozen.GateStatus.PASS for result in self.results
        )

    @property
    def verdict(self) -> str:
        identity = self.identity
        return identity.pass_outcome if self.passed else identity.fail_outcome

    @property
    def blockers(self) -> tuple[Blocker, ...]:
        return tuple(
            blocker for result in self.results for blocker in result.blockers
        )

    def result(self, gate: frozen.PreflightGate) -> GateResult:
        for item in self.results:
            if item.gate is gate:
                return item
        raise KeyError(gate)  # pragma: no cover - GATE_ORDER is exhaustive

    def status(self, gate: frozen.PreflightGate) -> frozen.GateStatus:
        return self.result(gate).status


@dataclass(frozen=True, slots=True)
class PreflightOutcome:
    """Both candidates, the outcome, and the selection if there is one.

    The outcome is derived. There is no parameter through which a caller could
    supply one, and no path by which a failing candidate becomes a selection
    (docs/adr/0093).
    """

    candidates: tuple[CandidatePreflight, ...]
    outcome: str
    selected_candidate: str | None
    tie_break_applied: bool
    preflight_fingerprint: str

    def candidate(self, candidate_id: str) -> CandidatePreflight:
        for item in self.candidates:
            if item.candidate_id == candidate_id:
                return item
        raise KeyError(candidate_id)

    @property
    def survivors(self) -> tuple[CandidatePreflight, ...]:
        return tuple(item for item in self.candidates if item.passed)

    @property
    def blockers(self) -> tuple[Blocker, ...]:
        """Every blocker, in the order the marker stores them.

        Sorted here rather than at the marker, so that the claims a caller
        builds and the claims the marker normalises are the same object. They
        have to be: the marker fingerprints itself after normalising, and a
        reordering between the two would look like a tampered fingerprint.
        """
        return tuple(
            sorted(
                (blocker for item in self.candidates for blocker in item.blockers),
                key=lambda item: (item.candidate_id, item.blocker_code.value),
            )
        )


def run_preflight() -> PreflightOutcome:
    """Run both candidates and derive the stage outcome.

    Raises:
        PreflightGateError: two candidates survived. Stage 10A froze an ordered
            tie-break but implemented no comparator, because implementing one
            against a case that did not arise would be implementing it against
            a guess. Two survivors is a real state and it needs a decision, so
            it stops here rather than picking (docs/adr/0093).
    """
    candidates = tuple(
        run_candidate_preflight(item.candidate_id) for item in frozen.CANDIDATES
    )
    survivors = tuple(item for item in candidates if item.passed)
    if not survivors:
        return _outcome(
            candidates,
            outcome=frozen.STAGE_10A_NO_SURVIVOR_OUTCOME,
            selected=None,
            tie_break_applied=False,
        )
    if len(survivors) == 1:
        return _outcome(
            candidates,
            outcome=frozen.STAGE_10A_SELECTED_OUTCOME,
            selected=survivors[0].candidate_id,
            tie_break_applied=False,
        )
    raise PreflightGateError(  # pragma: no cover - unreachable today
        "both candidates survived every hard gate. The tie-break criteria are "
        "frozen and ordered but no comparator was written, because Stage 10A "
        "would have had to invent the comparisons to write one. This is a "
        "decision, not a computation"
    )


def _outcome(
    candidates: tuple[CandidatePreflight, ...],
    *,
    outcome: str,
    selected: str | None,
    tie_break_applied: bool,
) -> PreflightOutcome:
    if outcome not in frozen.STAGE_10A_OUTCOMES:
        raise PreflightGateError(f"{outcome!r} is not a Stage 10A outcome")
    if (selected is None) != (outcome == frozen.STAGE_10A_NO_SURVIVOR_OUTCOME):
        raise PreflightGateError(
            "a selected candidate and the SELECTED outcome go together, and "
            "neither appears without the other"
        )
    if selected is not None:
        chosen = next(
            item for item in candidates if item.candidate_id == selected
        )
        if not chosen.passed:
            raise PreflightGateError(
                f"{selected} was selected and did not pass every hard gate"
            )
    return PreflightOutcome(
        candidates=candidates,
        outcome=outcome,
        selected_candidate=selected,
        tie_break_applied=tie_break_applied,
        preflight_fingerprint=stable_hash(
            {
                "schema": "stage_10a_preflight_v1",
                "outcome": outcome,
                "selected_candidate": selected,
                "tie_break_applied": tie_break_applied,
                "candidates": [
                    {
                        "candidate_id": item.candidate_id,
                        "verdict": item.verdict,
                        "gates": [
                            (result.gate.value, result.status.value)
                            for result in item.results
                        ],
                        "blockers": sorted(
                            blocker.blocker_code.value for blocker in item.blockers
                        ),
                    }
                    for item in candidates
                ],
                "reconnaissance": observed.reconnaissance_fingerprint(),
            },
            length=64,
        ),
    )


# --------------------------------------------------------- published documents


def candidate_set_document() -> Mapping[str, Any]:
    """The two candidates, the gate order, and what this stage will not do."""
    return {
        "schema": "stage_10a_candidate_set_v1",
        "algorithm_slot": frozen.ALGORITHM_SLOT,
        "question": (
            "which, if either, of these candidates can enter fpbench as "
            "Algorithm 4 without an fpbench reconstruction, without invented "
            "preprocessing, and without SD300 being consulted to make it fit"
        ),
        "candidate_count": len(frozen.CANDIDATES),
        "candidates": [
            {
                "candidate_id": item.candidate_id,
                "marker_token": item.marker_token,
                "display_name": item.display_name,
                "paper": item.paper_locator,
                "paper_preprint": item.paper_arxiv_locator,
                "authors": list(item.authors),
                "pass_outcome": item.pass_outcome,
                "fail_outcome": item.fail_outcome,
                "first_document": item.first_document,
            }
            for item in frozen.CANDIDATES
        ],
        "declared_non_candidates": [
            {"identity": name, "description": description}
            for name, description in frozen.DECLARED_NON_CANDIDATES
        ],
        "gate_order": [gate.value for gate in frozen.GATE_ORDER],
        "gates_are_conjunctive_and_unweighted": True,
        "accepted_implementation_origins": [
            origin.value for origin in frozen.ACCEPTED_ORIGINS
        ],
        "tie_break_criteria": [
            {
                "order": item.order,
                "criterion_id": item.criterion_id,
                "description": item.description,
            }
            for item in frozen.TIE_BREAK_CRITERIA
        ],
        "tie_break_uses_reported_performance": False,
        "benchmark_input": {
            "profile": frozen.BENCHMARK_INPUT_PROFILE,
            "ppi": frozen.BENCHMARK_INPUT_PPI,
            "pixel_format": frozen.BENCHMARK_INPUT_PIXEL_FORMAT,
        },
        "score_contract_requirements": list(frozen.SCORE_CONTRACT_REQUIREMENTS),
        "score_contract_requirements_were_applied_to_a_candidate": False,
        "reconnaissance_fingerprint": observed.reconnaissance_fingerprint(),
        "non_goals": [
            "no production adapter",
            "no AlgorithmConfig",
            "no 6,000 comparisons",
            "no SD300 read",
            "no DecisionProfile",
            "no threshold",
            "no calibration",
            "no metrics",
            "no fine-tuning or retraining",
            "no crop or hyperparameter optimisation",
            "no model selection from benchmark performance",
        ],
    }


def _not_reached_document(
    preflight: "CandidatePreflight", gate: frozen.PreflightGate, schema: str
) -> dict[str, Any]:
    result = preflight.result(gate)
    if result.status is not frozen.GateStatus.NOT_REACHED:
        raise PreflightGateError(  # pragma: no cover - the caller checks first
            f"{preflight.candidate_id}/{gate.value} is {result.status.value} and "
            "cannot be published as a gate that was never reached"
        )
    return {
        "schema": schema,
        "candidate": preflight.candidate_id,
        "gate": gate.value,
        "gate_status": frozen.GateStatus.NOT_REACHED.value,
        "why_not_reached": result.summary,
    }


def candidate_document(
    preflight: CandidatePreflight, name: str, *, repository_root: Path
) -> Mapping[str, Any]:
    """One of a candidate's nine documents, derived from the gates that ran.

    A document whose gate was never reached carries the gate, the reason, and
    the observations that happened to be gathered before the candidate stopped —
    labelled as observations, never as conclusions. Everything else in it is
    absent rather than guessed (spec section 40).
    """
    candidate_id = preflight.candidate_id
    identity = preflight.identity

    if name == identity.first_document:
        if candidate_id == frozen.AFRNET.candidate_id:
            return observed.afrnet_source_discovery()
        return observed.jipnet_source_manifest()

    if name == frozen.AUTHENTICITY_REPORT_NAME:
        result = preflight.result(frozen.PreflightGate.IDENTITY)
        return {
            **observed.authenticity_report(candidate_id),
            "gate_status": result.status.value,
            "gate_summary": result.summary,
        }

    if name == frozen.INPUT_DOMAIN_CONTRACT_NAME:
        result = preflight.result(frozen.PreflightGate.INPUT_DOMAIN)
        return {
            **observed.input_domain_contract_document(candidate_id),
            "gate_status": result.status.value,
            "gate_summary": result.summary,
        }

    if name == frozen.ARTIFACT_MANIFEST_NAME:
        document = _not_reached_document(
            preflight,
            frozen.PreflightGate.ARTIFACTS,
            "stage_10a_artifact_manifest_v1",
        )
        document["bytes_downloaded"] = 0
        document["artifact_store_environment_variable"] = "FPBENCH_THIRD_PARTY_ROOT"
        document["manifests_hold_no_absolute_path"] = True
        document["would_have_had_to_close_over"] = [
            {
                "artifact_role": sketch.artifact_role,
                "component_kind": sketch.component_kind.value,
                "locator": sketch.locator,
                "locator_kind": sketch.locator_kind,
                "locator_is_an_identity": False,
                "required_by": sketch.required_by,
                "transitive_from": sketch.transitive_from,
            }
            for sketch in observed.artifact_sketches(candidate_id)
        ]
        document["notes"] = [
            "A sketch of the gate's scope, not a manifest: no digest, no size "
            "and no local placement, because nothing was fetched. A Drive "
            "folder is a place and not an identity, and Stage 10A never treats "
            "one as an identity (docs/adr/0083).",
        ]
        return document

    if name == frozen.INFERENCE_ROUTE_AUDIT_NAME:
        document = _not_reached_document(
            preflight,
            frozen.PreflightGate.INFERENCE_ROUTE,
            "stage_10a_inference_route_audit_v1",
        )
        document["observations_recorded_before_the_stop"] = [
            {
                "observation_id": item.observation_id,
                "statement": item.statement,
                "locator": item.locator,
            }
            for item in observed.route_observations(candidate_id)
        ]
        document["these_observations_are_not_a_gate_conclusion"] = True
        return document

    if name == frozen.SCORE_CONTRACT_NAME:
        document = _not_reached_document(
            preflight,
            frozen.PreflightGate.SCORE_CONTRACT,
            "stage_10a_score_contract_v1",
        )
        document["observations_recorded_before_the_stop"] = [
            {
                "observation_id": item.observation_id,
                "statement": item.statement,
                "locator": item.locator,
            }
            for item in observed.score_observations(candidate_id)
        ]
        document["these_observations_are_not_a_gate_conclusion"] = True
        document["pair_order_symmetry_established"] = False
        document["fpbench_may_symmetrise_a_pairwise_score"] = False
        document["self_comparison_shortcut_permitted"] = False
        document["requirements_this_gate_would_have_applied"] = list(
            frozen.SCORE_CONTRACT_REQUIREMENTS
        )
        return document

    if name == frozen.TRAINING_PROVENANCE_NAME:
        provenance = observed.training_provenance(candidate_id)
        document = _not_reached_document(
            preflight,
            frozen.PreflightGate.TRAINING_PROVENANCE,
            "stage_10a_training_provenance_v1",
        )
        document["observations_recorded_before_the_stop"] = [
            {
                "dataset": item.name,
                "role": item.role.value,
                "detail": item.detail,
            }
            for item in provenance.datasets
        ]
        document["these_observations_are_not_a_gate_conclusion"] = True
        document["sd300_overlap_status"] = provenance.sd300_overlap_status.value
        document["sd300_overlap_found"] = (
            provenance.sd300_overlap_status.is_automatic_rejection
        )
        document["sd300_basis"] = provenance.sd300_basis
        document["no_evidence_found_is_not_proven_absent"] = True
        document["sd300_data_read_by_this_stage"] = False
        document["future_development_dataset_exclusions"] = list(
            provenance.future_development_dataset_exclusions
        )
        document["upstream_discrepancies"] = list(provenance.discrepancies)
        document["notes"] = list(provenance.notes)
        return document

    if name == frozen.RUNTIME_SMOKE_NAME:
        document = _not_reached_document(
            preflight,
            frozen.PreflightGate.RUNTIME_SMOKE,
            "stage_10a_runtime_smoke_v1",
        )
        document["synthetic_fixtures_written"] = 0
        document["checkpoint_loaded"] = False
        document["forward_pass_executed"] = False
        document["sd300_images_used"] = False
        document["red_flags_recorded_before_the_stop"] = [
            {
                "observation_id": item.observation_id,
                "statement": item.statement,
                "locator": item.locator,
            }
            for item in observed.runtime_observations(candidate_id)
        ]
        document["these_observations_are_not_a_gate_conclusion"] = True
        return document

    if name == frozen.PREFLIGHT_REPORT_NAME:
        return preflight_report_document(preflight, repository_root=repository_root)

    raise PreflightGateError(  # pragma: no cover - the caller iterates the frozen list
        f"{candidate_id}: {name!r} is not one of this candidate's documents"
    )


def preflight_report_document(
    preflight: CandidatePreflight, *, repository_root: Path
) -> Mapping[str, Any]:
    """One candidate's verdict, gate by gate, with every blocker named."""
    identity = preflight.identity
    decisive = _DECISIVE_QUESTIONS[preflight.candidate_id]
    return {
        "schema": "stage_10a_preflight_report_v1",
        "candidate": identity.candidate_id,
        "marker_token": identity.marker_token,
        "display_name": identity.display_name,
        "verdict": preflight.verdict,
        "passed_every_hard_gate": preflight.passed,
        "stopped_at_gate": (
            preflight.stopped_at.value if preflight.stopped_at else None
        ),
        "decisive_question": decisive[0],
        "decisive_answer": decisive[1],
        "decisive_answer_basis": decisive[2],
        "gates": [
            {
                "order": index,
                "gate": result.gate.value,
                "status": result.status.value,
                "summary": result.summary,
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
            }
            for blocker in preflight.blockers
        ],
        "what_this_candidate_cost": {
            "checkpoint_bytes_downloaded": 0,
            "runtime_environments_built": 0,
            "sd300_images_read": 0,
            "scores_produced": 0,
        },
    }


#: The two questions the user asked to appear verbatim in the report, and the
#: one-word answers they asked for. Not a paragraph (spec sections 35 and 36).
_DECISIVE_QUESTIONS: Mapping[str, tuple[str, str, str]] = {
    frozen.AFRNET.candidate_id: (
        "Does an original-author-supplied executable AFR-Net artifact set exist "
        "that defines the published verification score route sufficiently for "
        "fpbench?",
        "NO",
        "Ten locations were searched. None yielded source or weights published "
        "by Grosz and Jain. The only executable AFR-Net located is a third "
        "party's reproduction with a substituted alignment stage, and that is "
        "not AFR-Net.",
    ),
    frozen.JIPNET.candidate_id: (
        "Can the exact released JIPNet checkpoint consume fpbench canonical500 "
        "full fingerprints through a published deterministic inference "
        "transformation, without fpbench inventing a partial-patch "
        "construction?",
        "NO",
        "The official inference script performs no crop and no resize, the "
        "repository contains no resize at all, and the only "
        "full-fingerprint-to-patch function belongs to training-data "
        "construction — where the crop depends on the paired image, on a "
        "random rotation, and on a commercial SDK step the authors state "
        "cannot run.",
    ),
}


def candidate_comparison_document(outcome: PreflightOutcome) -> Mapping[str, Any]:
    """Both candidates side by side, and why no ranking was performed."""
    return {
        "schema": "stage_10a_candidate_comparison_v1",
        "outcome": outcome.outcome,
        "selected_candidate": (
            frozen.candidate(outcome.selected_candidate).marker_token
            if outcome.selected_candidate
            else None
        ),
        "survivor_count": len(outcome.survivors),
        "ranking_performed": False,
        "why_no_ranking": (
            "Ranking happens only among candidates that passed every hard gate, "
            "and here there are none. Scoring candidates that failed different "
            "gates against each other would produce a winner with an unresolved "
            "blocker, which is the shape Stage 9A's FLARE reading rejected "
            "(docs/adr/0093)."
        ),
        "tie_break_applied": outcome.tie_break_applied,
        "tie_break_criteria_frozen": [
            item.criterion_id for item in frozen.TIE_BREAK_CRITERIA
        ],
        "selection_based_on_reported_performance": False,
        "reported_performance_read": False,
        "gate_matrix": [
            {
                "gate": gate.value,
                **{
                    item.candidate_id: item.status(gate).value
                    for item in outcome.candidates
                },
            }
            for gate in frozen.GATE_ORDER
        ],
        "verdicts": {
            item.candidate_id: item.verdict for item in outcome.candidates
        },
        "stopped_at": {
            item.candidate_id: (
                item.stopped_at.value if item.stopped_at else None
            )
            for item in outcome.candidates
        },
        "blocker_codes": {
            item.candidate_id: sorted(
                blocker.blocker_code.value for blocker in item.blockers
            )
            for item in outcome.candidates
        },
        "the_two_candidates_failed_for_unrelated_reasons": True,
        "notes": [
            "AFR-Net stopped on authenticity: there is no author-supplied "
            "artifact to qualify. JIPNet stopped on input domain: the artifact "
            "is official and well documented, and it is a matcher for a "
            "different kind of input than this benchmark produces.",
            "Neither verdict is a judgement about the quality of either method.",
        ],
    }


# ------------------------------------------------------------- the byte guard


@dataclass(frozen=True, slots=True)
class TrackedByteFinding:
    """One tracked file that is byte-for-byte a candidate artifact."""

    path: str
    component_role: str
    sha256: str


@dataclass(frozen=True, slots=True)
class TrackedByteAudit:
    """Every tracked file, checked against the exact digests Stage 10A froze."""

    tracked_file_count: int
    known_digest_count: int
    findings: tuple[TrackedByteFinding, ...]

    @property
    def clean(self) -> bool:
        return not self.findings


def candidate_artifact_digests() -> Mapping[str, tuple[str, str]]:
    """Every exact digest Stage 10A knows, keyed by digest.

    The source archive and every upstream file this stage cites. A tracked file
    matching any of them would mean an upstream byte entered a public repository
    that promises to hold none (docs/adr/0083).
    """
    digests: dict[str, tuple[str, str]] = {
        observed.JIPNET_REPOSITORY.archive_sha256: (
            _SOURCE_ARCHIVE_ID,
            "the JIPNet source archive at the pinned commit",
        )
    }
    for item in observed.JIPNET_PINNED_FILES:
        digests[item.sha256] = (
            f"jipnet:{item.relative_path}",
            f"an upstream file this stage cites: {item.relative_path}",
        )
    return digests


def _tracked_files(repository_root: Path) -> tuple[str, ...]:
    try:
        completed = subprocess.run(
            ("git", "-C", str(repository_root), "ls-files", "-z"),
            check=False,
            capture_output=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Stage10AFinalizationError(
            f"cannot list tracked files for the Stage 10A byte guard: {exc}"
        ) from exc
    if completed.returncode != 0:
        raise Stage10AFinalizationError(
            "cannot list tracked files for the Stage 10A byte guard: "
            + completed.stderr.decode("utf-8", "replace").strip()
        )
    return tuple(
        name
        for name in completed.stdout.decode("utf-8", "replace").split("\0")
        if name
    )


def audit_tracked_bytes_against_candidate_artifacts(
    repository_root: Path,
) -> TrackedByteAudit:
    """Hash every tracked file and compare it with the frozen digests."""
    repository_root = Path(repository_root)
    known = candidate_artifact_digests()
    findings: list[TrackedByteFinding] = []
    tracked = _tracked_files(repository_root)
    for relative in tracked:
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
                    path=relative,
                    component_role=found[1],
                    sha256=digest.hexdigest(),
                )
            )
    return TrackedByteAudit(
        tracked_file_count=len(tracked),
        known_digest_count=len(known),
        findings=tuple(sorted(findings, key=lambda item: item.path)),
    )


def require_no_candidate_bytes_in_git(repository_root: Path) -> TrackedByteAudit:
    """The raising form, for a gate.

    Raises:
        Stage10AFinalizationError: a tracked file is byte-for-byte a candidate
            artifact.
    """
    audit = audit_tracked_bytes_against_candidate_artifacts(repository_root)
    if not audit.clean:
        detail = "; ".join(
            f"{finding.path} is {finding.component_role}"
            for finding in audit.findings
        )
        raise Stage10AFinalizationError(
            f"candidate bytes are tracked in this public repository: {detail}"
        )
    return audit


def usage_manifest_document(audit: UsageAudit) -> Mapping[str, Any]:
    """The Stage 8E record for what Stage 10A obtained, in Stage 8E's vocabulary."""
    return {
        "manifest_id": audit.manifest.manifest_id,
        "subject": audit.manifest.subject,
        "purpose_fingerprint": audit.manifest.purpose_fingerprint,
        "policy_fingerprint": audit.manifest.policy_fingerprint,
        "manifest_fingerprint": audit.manifest.manifest_fingerprint,
        "audit_fingerprint": audit.audit_fingerprint,
        "opens_execution": audit.opens_execution,
        "records": [
            {
                "record_id": audit.record.record_id,
                "component_kind": audit.record.component_kind.value,
                "license_observation_status": (
                    audit.record.license_observation_status.value
                ),
                "license_observation_fingerprint": (
                    audit.record.license_observation_fingerprint
                ),
                "license_evidence_locators": list(
                    audit.record.license_evidence_locators
                ),
                "research_use_decision": audit.record.research_use_decision.value,
                "research_use_assessment_fingerprint": (
                    audit.record.research_use_assessment_fingerprint
                ),
                "non_blocking_restrictions": [
                    restriction.value
                    for restriction in audit.assessment.non_blocking_restrictions
                ],
                "blockers": [
                    blocker.value for blocker in audit.assessment.blockers
                ],
                "redistribution_decision": (
                    audit.record.redistribution.decision.value
                ),
                "redistributed_by_fpbench": (
                    audit.record.redistribution.redistributed_by_fpbench
                ),
                "storage_class": audit.record.storage_class.value,
                "stored_in_git": audit.record.stored_in_git,
                "stored_in_ci_artifacts": audit.record.stored_in_ci_artifacts,
                "usage_fingerprint": audit.record.usage_fingerprint,
            }
        ],
        "checkpoints_acquired": 0,
        "notes": [
            "Stage 8E decided this. Stage 10A supplied the observation and the "
            "facts and supplied no verdict; there is no parameter through which "
            "it could have (docs/adr/0082).",
            "Stage 10A added no licensing subsystem and no per-candidate policy. "
            "One component was obtained, so there is one record.",
        ],
    }


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
                    "candidate": blocker.candidate_id,
                    "gate": blocker.gate.value,
                    "blocker_code": blocker.blocker_code.value,
                    "affected_component": blocker.affected_component,
                    "evidence": blocker.evidence,
                    "why_this_blocks_algorithm_4": (
                        blocker.why_this_blocks_algorithm_4
                    ),
                }.items()
            )
        )
        for blocker in sorted(
            blockers,
            key=lambda item: (item.candidate_id, item.blocker_code.value),
        )
    )
