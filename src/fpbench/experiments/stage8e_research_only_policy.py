"""Stage 8E's experiment layer: the legacy audit, the guard, and the qualification.

Three jobs, and the first one is what makes the other two mean anything.

**The legacy audit.** Every third-party component this project already depends on
— SourceAFIS and its shaded closure, the two NIST archives and the build made
from them, the learned extractor's source, checkpoint, two sub-licensed subtrees
and CPU runtime bundle, and NIST SD300 itself — is run through the *same* engine
Stage 9A will use. Twelve components, twelve observations, twelve decisions, four
manifests. Nothing historical is rewritten: Stage 8A's ``LICENSE_BLOCKED`` and
Stage 8B's ``weights_license_status: unresolved`` are exactly as published, and
this is a new mapping beside them (docs/adr/0084).

The frozen facts in :mod:`fpbench.experiments.stage8e_identity` are checked
against the documents they were copied from, so the constants are a reviewable
copy of an authority rather than a second one.

**The repository audit.** What Git actually tracks, and what the workflows
actually do. The repository is public, so ``.gitignore`` is a convenience and
this is the enforcement (docs/adr/0083).

**The policy qualification.** Every claim the policy makes, exercised on fixtures
this module builds from nothing: that a non-commercial restriction does not
block, that a conflict resolves by intersection rather than by picking a winner,
that an absent licence does not become permission, that a dataset cannot be
risk-accepted. There is no dataset, no runtime, no checkpoint and no network in
any of it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from fpbench.core.third_party_errors import (
    LicenseObservationError,
    ResearchUseDecisionError,
    Stage8EFinalizationError,
    ThirdPartyUsageError,
)
from fpbench.core.serialization import stable_hash, to_plain
from fpbench.core.third_party_models import (
    LicenseEvidence,
    LicenseObservation,
    LicenseObservationStatus,
    NonBlockingRestriction,
    OwnerRiskAcceptance,
    RedistributionDecision,
    ResearchUseAssessment,
    ResearchUseBlocker,
    ResearchUseDecision,
    ThirdPartyComponentKind,
    ThirdPartyUsageManifest,
    ThirdPartyUsageRecord,
    UpstreamIdentity,
)
from fpbench.experiments import stage8e_identity as frozen
from fpbench.third_party.manifest import build_usage_manifest, build_usage_record
from fpbench.third_party.policy import (
    PlausibleReading,
    assess_research_use,
    third_party_policy,
)
from fpbench.third_party.purpose import project_purpose
from fpbench.third_party.repository_guard import (
    RepositoryArtifactAudit,
    audit_repository_artifacts,
)
from fpbench.third_party.verify import verify_usage_record

__all__ = [
    "OWNER",
    "OWNER_RISK_BASIS",
    "FORBIDDEN_WORKFLOW_TOKENS",
    "REQUIRED_IGNORE_PATTERNS",
    "LegacyComponentMapping",
    "LegacyAudit",
    "WorkflowFinding",
    "WorkflowAudit",
    "RepositoryAudit",
    "PolicyCase",
    "PolicyQualification",
    "read_published_legacy_values",
    "require_frozen_legacy_facts_match_published_evidence",
    "require_stage8d_is_the_stage_this_follows",
    "build_legacy_audit",
    "audit_workflows",
    "build_repository_audit",
    "run_policy_qualification",
    "policy_contract_report",
]

#: Who accepts a risk. One string, because "the owner" of this project is one
#: person and a record that named a team would be inventing one.
OWNER = "the project owner"

OWNER_RISK_BASIS = (
    "The project owner is proceeding with a local research operation despite an "
    "ambiguity nobody resolved. This is not a finding that the use is permitted "
    "(docs/adr/0084)."
)

#: Tokens no workflow may contain, and the policy field each one would falsify.
#: Matched as substrings of the workflow text, which is blunt and is meant to be:
#: a rule that tried to understand YAML semantics would have a parser to be wrong
#: about (spec sections 14, 15, 16).
FORBIDDEN_WORKFLOW_TOKENS: tuple[tuple[str, str], ...] = (
    ("actions/upload-artifact", "ci_uploads_third_party_bytes"),
    ("docker/build-push-action", "publishes_container_images_with_third_party_artifacts"),
    ("docker push", "publishes_container_images_with_third_party_artifacts"),
    ("ghcr.io", "publishes_container_images_with_third_party_artifacts"),
    ("nigos.nist.gov", "ci_downloads_restricted_artifacts"),
    ("codeload.github.com", "ci_downloads_restricted_artifacts"),
    ("drive.google.com", "ci_downloads_restricted_artifacts"),
    ("google-drive-file", "ci_downloads_restricted_artifacts"),
)

#: Ignore patterns that must remain in ``.gitignore``. Not the enforcement — the
#: tracked-file guard is — but their disappearance is worth reporting, because it
#: is how the next accident starts.
REQUIRED_IGNORE_PATTERNS: tuple[str, ...] = (
    "workspace/**",
    "data/**",
    "*.png",
    "*.pgm",
    "*.wsq",
)


# ------------------------------------------------------------ published facts


def _read_document(repository_root: Path, relative: str) -> Mapping[str, Any]:
    path = Path(repository_root) / PurePosixPath(relative)
    if not path.is_file():
        raise Stage8EFinalizationError(
            f"Stage 8E cannot audit its legacy components: {relative} is not "
            "published"
        )
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Stage8EFinalizationError(
            f"{relative} is not readable JSON: {exc}"
        ) from exc
    if not isinstance(document, dict):
        raise Stage8EFinalizationError(f"{relative} is not a JSON object")
    return document


def _dotted(document: Mapping[str, Any], key: str, *, where: str) -> str:
    """Read ``a.b.c`` out of a nested document, refusing anything but a scalar."""
    node: Any = document
    for part in key.split("."):
        if not isinstance(node, Mapping) or part not in node:
            raise Stage8EFinalizationError(
                f"{where} does not carry {key!r}, which Stage 8E's legacy audit "
                "is checked against"
            )
        node = node[part]
    if isinstance(node, bool) or not isinstance(node, (str, int)):
        raise Stage8EFinalizationError(f"{where}: {key!r} is not a scalar")
    return str(node)


def read_published_legacy_values(repository_root: Path) -> dict[str, str]:
    """Every value Stage 8E's legacy facts are checked against.

    Keyed by ``<document>:<key>`` so that two documents carrying the same key
    name stay distinguishable. Nothing else is read from these documents: no
    score row, no result file, no workspace (docs/adr/0062 in spirit — a policy
    stage has even less business in the data than a selection stage did).
    """
    values: dict[str, str] = {}
    for relative, keys in frozen.LEGACY_SOURCE_DOCUMENTS:
        document = _read_document(repository_root, relative)
        for key in keys:
            values[f"{relative}:{key}"] = _dotted(document, key, where=relative)
    return values


def require_frozen_legacy_facts_match_published_evidence(
    repository_root: Path,
) -> dict[str, str]:
    """Every frozen digest must appear in a document that already published it.

    Checked by *value* rather than by position. A frozen digest no published
    document carries would mean the audit is describing a component this
    repository does not have — at best a typo, at worst an audit of something
    imaginary.
    """
    published = read_published_legacy_values(repository_root)
    known = set(published.values())
    missing = [
        f"{component.record_id} ({component.artifact_sha256[:12]}...)"
        for component in frozen.LEGACY_COMPONENTS
        if component.artifact_sha256 is not None
        and component.artifact_sha256 not in known
    ]
    if missing:
        raise Stage8EFinalizationError(
            "these frozen component digests are not present in the published "
            f"documents they were copied from: {missing}"
        )
    return published


def require_stage8d_is_the_stage_this_follows(repository_root: Path) -> None:
    """Confirm the closed stage is the one Stage 8E thinks it follows.

    Read-only, and it is the only thing Stage 8E does with Stage 8D's evidence.
    Nothing under that directory is edited and nothing is re-derived.
    """
    document = _read_document(
        repository_root,
        "evidence/stage8d-calibration-infrastructure/stage-8d-finalization.json",
    )
    fingerprint = str(document.get("stage_8d_finalization_fingerprint", "")).strip()
    outcome = str(document.get("outcome", "")).strip()
    if fingerprint != frozen.STAGE8D_CURRENT_FINALIZATION_FINGERPRINT:
        raise Stage8EFinalizationError(
            "the published Stage 8D marker is not the one Stage 8E was frozen "
            f"against: {fingerprint[:12]}... vs "
            f"{frozen.STAGE8D_CURRENT_FINALIZATION_FINGERPRINT[:12]}..."
        )
    if outcome != frozen.STAGE8D_OUTCOME:
        raise Stage8EFinalizationError(
            f"the published Stage 8D outcome is {outcome!r}, not "
            f"{frozen.STAGE8D_OUTCOME!r}"
        )
    if document.get("opens_algorithm_expansion") is not True:
        raise Stage8EFinalizationError(
            "the published Stage 8D marker does not open algorithm expansion"
        )


# -------------------------------------------------------------- legacy audit


@dataclass(frozen=True, slots=True)
class LegacyComponentMapping:
    """One legacy component, run through the engine a future algorithm will use."""

    record_id: str
    route: str
    observation: LicenseObservation
    assessment: ResearchUseAssessment
    record: ThirdPartyUsageRecord


@dataclass(frozen=True, slots=True)
class LegacyAudit:
    """Every already-integrated component, mapped and counted.

    Publishes identities, statuses and decisions. It publishes no licence text,
    no upstream source, no checkpoint byte and no score — the digests in it are
    expectations about files that live outside this repository, and every one of
    them was already published here before Stage 8E existed.
    """

    mappings: tuple[LegacyComponentMapping, ...]
    manifests: tuple[ThirdPartyUsageManifest, ...]
    audit_fingerprint: str

    def by_decision(self) -> Mapping[str, int]:
        counts: dict[str, int] = {}
        for mapping in self.mappings:
            key = mapping.assessment.decision.value
            counts[key] = counts.get(key, 0) + 1
        return {key: counts[key] for key in sorted(counts)}

    def by_status(self) -> Mapping[str, int]:
        counts: dict[str, int] = {}
        for mapping in self.mappings:
            key = mapping.observation.status.value
            counts[key] = counts.get(key, 0) + 1
        return {key: counts[key] for key in sorted(counts)}

    def by_kind(self) -> Mapping[str, int]:
        counts: dict[str, int] = {}
        for mapping in self.mappings:
            key = mapping.record.component_kind.value
            counts[key] = counts.get(key, 0) + 1
        return {key: counts[key] for key in sorted(counts)}

    @property
    def risk_accepted_count(self) -> int:
        return sum(
            1
            for mapping in self.mappings
            if mapping.assessment.decision is ResearchUseDecision.OWNER_RISK_ACCEPTED
        )

    @property
    def blocked_count(self) -> int:
        return sum(
            1
            for mapping in self.mappings
            if mapping.assessment.decision is ResearchUseDecision.BLOCKED
        )

    def mapping(self, record_id: str) -> LegacyComponentMapping:
        for mapping in self.mappings:
            if mapping.record_id == record_id:
                return mapping
        raise KeyError(record_id)


def _observation_for(component: frozen.LegacyComponent) -> LicenseObservation:
    return LicenseObservation(
        observation_id=f"{component.record_id}_observation",
        component_kind=component.kind,
        subject=component.subject,
        status=component.status,
        declared_license_names=component.license_names,
        spdx_identifiers=component.spdx,
        evidence=tuple(
            LicenseEvidence(
                locator=locator, description=description, document_sha256=digest
            )
            for locator, description, digest in component.evidence
        ),
        stated_restrictions=component.stated_restrictions,
        notes=component.notes,
    )


def _assessment_for(
    component: frozen.LegacyComponent, observation: LicenseObservation
) -> ResearchUseAssessment:
    acceptance = None
    if component.risk_accepted:
        acceptance = OwnerRiskAcceptance(
            published_intentionally_by_official_authors=True,
            publicly_obtainable_without_circumvention=True,
            intended_operation_is_local_research_only=True,
            no_located_term_expressly_prohibits_the_use=True,
            no_bytes_will_be_redistributed=True,
            accepted_by=OWNER,
            basis=OWNER_RISK_BASIS,
        )
    readings = (
        tuple(
            PlausibleReading(
                notice_locator=locator,
                permits_local_execution=local,
                permits_non_commercial_use=non_commercial,
                permits_educational_research=educational,
            )
            for locator, local, non_commercial, educational in (
                component.intersection_readings
            )
        )
        or None
    )
    return assess_research_use(
        observation,
        assessment_id=f"{component.record_id}_research_use",
        basis=component.basis,
        non_blocking_restrictions=component.restrictions,
        identity_established=True,
        intersection_readings=readings,
        owner_risk_acceptance=acceptance,
        dataset_access_terms_satisfied=component.dataset_access_terms_satisfied,
    )


def build_legacy_audit(repository_root: Path | None = None) -> LegacyAudit:
    """Map every legacy component, then verify each mapping re-derives.

    ``repository_root`` is optional so that a contract test can build the audit
    without a checkout of the published evidence. Every path that *publishes*
    anything passes it, so the check against the documents the facts were copied
    from is skipped only where there is nothing to check against.

    Raises:
        Stage8EFinalizationError: a mapping does not survive its own
            verification. The audit does not report that as a finding — it fails,
            because an audit that published a partially-verifying mapping would
            be publishing a decision nobody had checked.
    """
    if repository_root is not None:
        require_frozen_legacy_facts_match_published_evidence(repository_root)

    mappings: list[LegacyComponentMapping] = []
    for component in frozen.LEGACY_COMPONENTS:
        observation = _observation_for(component)
        assessment = _assessment_for(component, observation)
        record = build_usage_record(
            record_id=component.record_id,
            observation=observation,
            assessment=assessment,
            upstream_identity=UpstreamIdentity(
                upstream_name=component.upstream_name,
                upstream_locator=component.upstream_locator,
                exact_version=component.exact_version,
                upstream_commit=component.upstream_commit,
                artifact_filename=component.artifact_filename,
                artifact_sha256=component.artifact_sha256,
                artifact_size_bytes=component.artifact_size_bytes,
                identity_established=True,
            ),
            redistribution_decision=component.redistribution,
            redistribution_basis=component.redistribution_basis,
            notes=component.notes,
        )
        report = verify_usage_record(record, observation, assessment)
        if not report.verified:
            raise Stage8EFinalizationError(
                f"{component.record_id}: the mapping does not survive "
                f"re-derivation: {report.findings}"
            )
        mappings.append(
            LegacyComponentMapping(
                record_id=component.record_id,
                route=component.route,
                observation=observation,
                assessment=assessment,
                record=record,
            )
        )

    manifests = tuple(
        build_usage_manifest(
            manifest_id=f"{route}_third_party_usage",
            subject=f"every third-party component of the {route} route",
            records=tuple(
                mapping.record for mapping in mappings if mapping.route == route
            ),
        )
        for route in frozen.LEGACY_ROUTES
    )
    ordered = tuple(sorted(mappings, key=lambda item: item.record_id))
    return LegacyAudit(
        mappings=ordered,
        manifests=manifests,
        audit_fingerprint=stable_hash(
            {
                "schema": "stage_8e_legacy_component_audit_v1",
                "records": [
                    {
                        "record_id": mapping.record_id,
                        "route": mapping.route,
                        "observation_fingerprint": (
                            mapping.observation.observation_fingerprint
                        ),
                        "assessment_fingerprint": (
                            mapping.assessment.assessment_fingerprint
                        ),
                        "usage_fingerprint": mapping.record.usage_fingerprint,
                    }
                    for mapping in ordered
                ],
                "manifests": [
                    manifest.manifest_fingerprint for manifest in manifests
                ],
            },
            length=64,
        ),
    )


# ---------------------------------------------------------- repository audit


@dataclass(frozen=True, slots=True)
class WorkflowFinding:
    workflow: str
    token: str
    policy_field: str


@dataclass(frozen=True, slots=True)
class WorkflowAudit:
    """What the public CI does, checked against what the policy says it does not.

    Three claims live in the frozen policy — CI downloads no restricted artifact,
    uploads no third-party byte, and publishes no container image containing one
    — and a policy document asserting them while a workflow quietly did otherwise
    would be worse than no policy at all (spec sections 14–16).
    """

    workflow_count: int
    scanned_tokens: tuple[str, ...]
    findings: tuple[WorkflowFinding, ...]

    @property
    def clean(self) -> bool:
        return not self.findings


def audit_workflows(repository_root: Path) -> WorkflowAudit:
    directory = Path(repository_root) / ".github" / "workflows"
    if not directory.is_dir():
        raise Stage8EFinalizationError(
            "Stage 8E audits the public CI, and .github/workflows is not present"
        )
    findings: list[WorkflowFinding] = []
    workflows = sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in (".yml", ".yaml")
    )
    for path in workflows:
        text = path.read_text(encoding="utf-8")
        for token, policy_field in FORBIDDEN_WORKFLOW_TOKENS:
            if token in text:
                findings.append(
                    WorkflowFinding(
                        workflow=path.name, token=token, policy_field=policy_field
                    )
                )
    return WorkflowAudit(
        workflow_count=len(workflows),
        scanned_tokens=tuple(token for token, _field in FORBIDDEN_WORKFLOW_TOKENS),
        findings=tuple(findings),
    )


@dataclass(frozen=True, slots=True)
class RepositoryAudit:
    """The tracked-bytes guard, the workflow scan, and the ignore coverage.

    Three layers, in decreasing order of authority. The tracked-file guard is the
    enforcement; the workflow scan is what stops CI becoming the leak the guard
    cannot see; the ignore coverage is a convenience whose *absence* is worth
    reporting and whose presence proves nothing (docs/adr/0083).
    """

    artifacts: RepositoryArtifactAudit
    workflows: WorkflowAudit
    missing_ignore_patterns: tuple[str, ...]
    repository_audit_fingerprint: str

    @property
    def clean(self) -> bool:
        return (
            self.artifacts.clean
            and self.workflows.clean
            and not self.missing_ignore_patterns
        )


def build_repository_audit(repository_root: Path) -> RepositoryAudit:
    repository_root = Path(repository_root)
    artifacts = audit_repository_artifacts(repository_root)
    workflows = audit_workflows(repository_root)
    ignore_path = repository_root / ".gitignore"
    ignore_text = (
        ignore_path.read_text(encoding="utf-8") if ignore_path.is_file() else ""
    )
    ignore_lines = {line.strip() for line in ignore_text.splitlines()}
    missing = tuple(
        pattern for pattern in REQUIRED_IGNORE_PATTERNS if pattern not in ignore_lines
    )
    return RepositoryAudit(
        artifacts=artifacts,
        workflows=workflows,
        missing_ignore_patterns=missing,
        repository_audit_fingerprint=stable_hash(
            {
                "schema": "stage_8e_repository_audit_v1",
                "artifacts": artifacts.audit_fingerprint,
                "scanned_tokens": list(workflows.scanned_tokens),
                "workflow_findings": [
                    to_plain(finding) for finding in workflows.findings
                ],
                "missing_ignore_patterns": list(missing),
            },
            length=64,
        ),
    )


# ------------------------------------------------------ policy qualification
#
# Every claim the policy makes, exercised on fixtures this module invents. No
# dataset, no runtime, no checkpoint, no network and no workspace: the whole
# qualification is pure Python over notices that were never issued.


@dataclass(frozen=True, slots=True)
class PolicyCase:
    """What one fixture proved, in a form the evidence can publish."""

    case_id: str
    claim: str
    kind: str
    outcome: str

    def __post_init__(self) -> None:
        if self.kind not in ("decision", "refusal", "identity"):
            raise Stage8EFinalizationError(
                f"{self.case_id}: a policy case decides, refuses, or establishes "
                f"an identity, not {self.kind!r}"
            )


@dataclass(frozen=True, slots=True)
class PolicyQualification:
    cases: tuple[PolicyCase, ...]
    decision_cases: int
    refusal_cases: int
    identity_cases: int
    qualification_fingerprint: str

    def case(self, case_id: str) -> PolicyCase:
        for case in self.cases:
            if case.case_id == case_id:
                return case
        raise KeyError(case_id)


def _observation(
    status: LicenseObservationStatus,
    *,
    observation_id: str = "fixture_observation",
    kind: ThirdPartyComponentKind = ThirdPartyComponentKind.SOURCE_CODE,
    names: tuple[str, ...] = (),
    restrictions: tuple[str, ...] = (),
    evidence_count: int = 1,
) -> LicenseObservation:
    return LicenseObservation(
        observation_id=observation_id,
        component_kind=kind,
        subject="a fixture that describes no real upstream project",
        status=status,
        declared_license_names=names,
        stated_restrictions=restrictions,
        evidence=tuple(
            LicenseEvidence(
                locator=f"fixture://notice/{index}",
                description="a notice invented for this fixture",
            )
            for index in range(evidence_count)
        ),
    )


def _acceptance(**overrides: Any) -> OwnerRiskAcceptance:
    fields: dict[str, Any] = {
        "published_intentionally_by_official_authors": True,
        "publicly_obtainable_without_circumvention": True,
        "intended_operation_is_local_research_only": True,
        "no_located_term_expressly_prohibits_the_use": True,
        "no_bytes_will_be_redistributed": True,
        "accepted_by": OWNER,
        "basis": OWNER_RISK_BASIS,
    }
    fields.update(overrides)
    return OwnerRiskAcceptance(**fields)


def _refusal_case(case_id: str, claim: str, expected: type, call) -> PolicyCase:
    """Run something that must fail, and record *which* refusal it produced.

    The expected class is checked rather than "some exception". A dataset
    refusal that happened to arrive as a parse error would be a refusal nobody
    could rely on, and a catalogue recording it as a pass would be worse than no
    catalogue.
    """
    try:
        call()
    except expected as exc:
        return PolicyCase(
            case_id=case_id, claim=claim, kind="refusal", outcome=type(exc).__name__
        )
    except Exception as exc:  # noqa: BLE001 - naming the wrong refusal is the point
        raise Stage8EFinalizationError(
            f"{case_id}: expected {expected.__name__}, got {type(exc).__name__}: {exc}"
        ) from None
    raise Stage8EFinalizationError(
        f"{case_id}: expected {expected.__name__} and nothing was raised"
    )


def run_policy_qualification() -> PolicyQualification:
    """Run every fixture, in a fixed order, and return one identity over them.

    Raises:
        Stage8EFinalizationError: a fixture produced the wrong decision, raised
            the wrong refusal, or did not raise at all. The qualification does
            not report a failure — it fails, because a Stage 8E that published a
            partially-passing catalogue would be publishing a policy nobody had
            qualified.
    """
    cases: list[PolicyCase] = []

    def expect(condition: bool, case_id: str, detail: str) -> None:
        if not condition:
            raise Stage8EFinalizationError(f"{case_id}: {detail}")

    def decision_case(case_id: str, claim: str, assessment: ResearchUseAssessment):
        cases.append(
            PolicyCase(
                case_id=case_id,
                claim=claim,
                kind="decision",
                outcome=assessment.decision.value,
            )
        )
        return assessment

    # ------------------------------------------------------------ decisions

    permissive = decision_case(
        "permissive_licence_is_allowed_outright",
        "a permissive licence with notice conditions permits local research use",
        assess_research_use(
            _observation(
                LicenseObservationStatus.OPEN_SOURCE_PERMISSIVE,
                names=("Apache License 2.0",),
                restrictions=("Retain notices in a distribution.",),
            ),
            assessment_id="fixture_permissive",
            basis="its conditions attach to distribution, and there is none",
            non_blocking_restrictions=(
                NonBlockingRestriction.ATTRIBUTION_AND_NOTICE_RETENTION,
            ),
        ),
    )
    expect(
        permissive.decision is ResearchUseDecision.ALLOWED,
        "permissive_licence_is_allowed_outright",
        "expected ALLOWED",
    )

    copyleft = decision_case(
        "copyleft_does_not_block_local_execution",
        "strong copyleft attaches to conveying, and running is not conveying",
        assess_research_use(
            _observation(
                LicenseObservationStatus.OPEN_SOURCE_COPYLEFT,
                names=("GNU General Public License v3.0",),
                restrictions=("Source obligations apply on conveying the work.",),
            ),
            assessment_id="fixture_copyleft",
            basis="nothing is conveyed, so no source obligation is triggered",
            non_blocking_restrictions=(
                NonBlockingRestriction.STRONG_COPYLEFT,
                NonBlockingRestriction.COPYLEFT,
            ),
        ),
    )
    expect(
        copyleft.decision is ResearchUseDecision.ALLOWED,
        "copyleft_does_not_block_local_execution",
        "expected ALLOWED; copyleft is not a field-of-use restriction",
    )

    non_commercial = decision_case(
        "non_commercial_only_does_not_block",
        "a non-commercial restriction cannot block a non-commercial project",
        assess_research_use(
            _observation(
                LicenseObservationStatus.NON_COMMERCIAL,
                names=("a bespoke non-commercial licence",),
                restrictions=("Commercial use requires a separate licence.",),
            ),
            assessment_id="fixture_non_commercial",
            basis="the declared purpose forecloses every use this restricts",
            non_blocking_restrictions=(
                NonBlockingRestriction.NON_COMMERCIAL_ONLY,
                NonBlockingRestriction.COMMERCIAL_LICENSE_REQUIRED_FOR_COMMERCIAL_DEPLOYMENT,
            ),
            intersection_readings=(
                PlausibleReading(
                    notice_locator="fixture://notice/0",
                    permits_local_execution=True,
                    permits_non_commercial_use=True,
                    permits_educational_research=True,
                ),
                PlausibleReading(
                    notice_locator="fixture://notice/0-strict",
                    permits_local_execution=True,
                    permits_non_commercial_use=True,
                    permits_educational_research=True,
                ),
            ),
        ),
    )
    expect(
        non_commercial.decision
        is ResearchUseDecision.ALLOWED_UNDER_RESTRICTIVE_INTERSECTION,
        "non_commercial_only_does_not_block",
        "expected ALLOWED_UNDER_RESTRICTIVE_INTERSECTION",
    )

    conflicting = decision_case(
        "conflicting_notices_resolve_by_intersection",
        "a permissive LICENSE beside an academic-only README needs no winner",
        assess_research_use(
            _observation(
                LicenseObservationStatus.CONFLICTING_NOTICES,
                names=("Apache License 2.0", "academic use only"),
                restrictions=(
                    "The LICENSE file and the README state different terms.",
                ),
                evidence_count=2,
            ),
            assessment_id="fixture_conflicting",
            basis="every plausible reading permits local educational research",
            non_blocking_restrictions=(
                NonBlockingRestriction.NOTICE_CONFLICT_WITH_PERMISSIVE_INTERSECTION,
                NonBlockingRestriction.ACADEMIC_OR_RESEARCH_ONLY,
            ),
            intersection_readings=(
                PlausibleReading(
                    notice_locator="fixture://notice/0",
                    permits_local_execution=True,
                    permits_non_commercial_use=True,
                    permits_educational_research=True,
                ),
                PlausibleReading(
                    notice_locator="fixture://notice/1",
                    permits_local_execution=True,
                    permits_non_commercial_use=True,
                    permits_educational_research=True,
                ),
            ),
        ),
    )
    expect(
        conflicting.decision
        is ResearchUseDecision.ALLOWED_UNDER_RESTRICTIVE_INTERSECTION
        and conflicting.intersection_permits_intended_use,
        "conflicting_notices_resolve_by_intersection",
        "expected the intersection decision without resolving the conflict",
    )

    blocked_intersection = decision_case(
        "one_prohibiting_reading_blocks_the_intersection",
        "the intersection is a conjunction, so one forbidding reading decides it",
        assess_research_use(
            _observation(
                LicenseObservationStatus.CONFLICTING_NOTICES,
                names=("a permissive notice", "an evaluation-only notice"),
                restrictions=("One notice forbids research use outright.",),
                evidence_count=2,
            ),
            assessment_id="fixture_conflict_blocked",
            basis="one reading forbids the exact operation this project performs",
            non_blocking_restrictions=(
                NonBlockingRestriction.NOTICE_CONFLICT_WITH_PERMISSIVE_INTERSECTION,
            ),
            intersection_readings=(
                PlausibleReading(
                    notice_locator="fixture://notice/0",
                    permits_local_execution=True,
                    permits_non_commercial_use=True,
                    permits_educational_research=True,
                ),
                PlausibleReading(
                    notice_locator="fixture://notice/1",
                    permits_local_execution=True,
                    permits_non_commercial_use=True,
                    permits_educational_research=False,
                ),
            ),
        ),
    )
    expect(
        blocked_intersection.decision is ResearchUseDecision.BLOCKED,
        "one_prohibiting_reading_blocks_the_intersection",
        "expected BLOCKED",
    )

    risk = decision_case(
        "no_licence_found_may_be_risk_accepted",
        "an absent licence is risk-accepted, and permission stays UNRESOLVED",
        assess_research_use(
            _observation(
                LicenseObservationStatus.NO_LICENSE_FOUND,
                kind=ThirdPartyComponentKind.MODEL_WEIGHTS,
                evidence_count=0,
            ),
            assessment_id="fixture_no_licence",
            basis="the owner accepted the risk of a local research operation",
            owner_risk_acceptance=_acceptance(),
        ),
    )
    expect(
        risk.decision is ResearchUseDecision.OWNER_RISK_ACCEPTED
        and risk.intended_use_permission_status.value == "UNRESOLVED",
        "no_licence_found_may_be_risk_accepted",
        "expected OWNER_RISK_ACCEPTED with permission left unresolved",
    )

    unaccepted = decision_case(
        "no_licence_found_without_acceptance_is_blocked",
        "silence is not a grant; with no acceptance the absence blocks",
        assess_research_use(
            _observation(
                LicenseObservationStatus.NO_LICENSE_FOUND,
                kind=ThirdPartyComponentKind.MODEL_WEIGHTS,
                evidence_count=0,
            ),
            assessment_id="fixture_no_licence_unaccepted",
            basis="nobody accepted the risk, so the absence of permission stands",
        ),
    )
    expect(
        unaccepted.decision is ResearchUseDecision.BLOCKED,
        "no_licence_found_without_acceptance_is_blocked",
        "expected BLOCKED",
    )

    dataset = decision_case(
        "a_dataset_passes_only_on_its_own_terms",
        "dataset access terms are satisfied, and are what the decision rests on",
        assess_research_use(
            _observation(
                LicenseObservationStatus.RESEARCH_ONLY,
                kind=ThirdPartyComponentKind.DATASET,
                names=("delivery terms agreed on obtaining the corpus",),
                restrictions=("Research use only; no redistribution.",),
            ),
            assessment_id="fixture_dataset",
            basis="the delivery terms were accepted and are satisfied by this use",
            non_blocking_restrictions=(
                NonBlockingRestriction.ACADEMIC_OR_RESEARCH_ONLY,
                NonBlockingRestriction.NO_REDISTRIBUTION,
            ),
            intersection_readings=(
                PlausibleReading(
                    notice_locator="fixture://notice/0",
                    permits_local_execution=True,
                    permits_non_commercial_use=True,
                    permits_educational_research=True,
                ),
                PlausibleReading(
                    notice_locator="fixture://notice/0-strict",
                    permits_local_execution=True,
                    permits_non_commercial_use=True,
                    permits_educational_research=True,
                ),
            ),
            dataset_access_terms_satisfied=True,
        ),
    )
    expect(
        dataset.decision
        is ResearchUseDecision.ALLOWED_UNDER_RESTRICTIVE_INTERSECTION,
        "a_dataset_passes_only_on_its_own_terms",
        "expected the intersection decision for a satisfied dataset",
    )

    prohibited = decision_case(
        "an_express_prohibition_of_biometric_use_blocks",
        "the short list of blockers is what stops something, and it does",
        assess_research_use(
            _observation(
                LicenseObservationStatus.RESEARCH_ONLY,
                names=("a research licence excluding biometrics",),
                restrictions=("Biometric applications are excluded.",),
            ),
            assessment_id="fixture_biometric_prohibited",
            basis="fingerprint recognition is the intended use and it is excluded",
            non_blocking_restrictions=(
                NonBlockingRestriction.ACADEMIC_OR_RESEARCH_ONLY,
            ),
            located_prohibitions=(
                ResearchUseBlocker.BIOMETRIC_USE_EXPRESSLY_PROHIBITED,
            ),
            intersection_readings=(
                PlausibleReading(
                    notice_locator="fixture://notice/0",
                    permits_local_execution=True,
                    permits_non_commercial_use=True,
                    permits_educational_research=True,
                ),
                PlausibleReading(
                    notice_locator="fixture://notice/0-strict",
                    permits_local_execution=True,
                    permits_non_commercial_use=True,
                    permits_educational_research=True,
                ),
            ),
        ),
    )
    expect(
        prohibited.decision is ResearchUseDecision.BLOCKED,
        "an_express_prohibition_of_biometric_use_blocks",
        "expected BLOCKED",
    )

    # ------------------------------------------------------------- identity

    declaration = project_purpose()
    policy = third_party_policy()
    cases.append(
        PolicyCase(
            case_id="the_purpose_and_the_policy_are_derived_not_read",
            claim=(
                "the declaration and the policy rebuild from source to one "
                "identity each"
            ),
            kind="identity",
            outcome=stable_hash(
                {
                    "purpose": declaration.purpose_fingerprint,
                    "policy": policy.policy_fingerprint,
                },
                length=64,
            ),
        )
    )

    same = assess_research_use(
        _observation(
            LicenseObservationStatus.OPEN_SOURCE_PERMISSIVE,
            names=("Apache License 2.0",),
            restrictions=("Retain notices in a distribution.",),
        ),
        assessment_id="fixture_permissive",
        basis="its conditions attach to distribution, and there is none",
        non_blocking_restrictions=(
            NonBlockingRestriction.ATTRIBUTION_AND_NOTICE_RETENTION,
        ),
    )
    expect(
        same.assessment_fingerprint == permissive.assessment_fingerprint,
        "the_same_facts_produce_the_same_assessment",
        "the engine is not deterministic over the same facts",
    )
    cases.append(
        PolicyCase(
            case_id="the_same_facts_produce_the_same_assessment",
            claim="the same observation and facts assess to one identical identity",
            kind="identity",
            outcome=same.assessment_fingerprint,
        )
    )

    # ------------------------------------------------------------- refusals

    cases.append(
        _refusal_case(
            "a_dataset_may_not_be_risk_accepted",
            "dataset rights are outside this policy and stay blocking",
            ResearchUseDecisionError,
            lambda: assess_research_use(
                _observation(
                    LicenseObservationStatus.NO_LICENSE_FOUND,
                    kind=ThirdPartyComponentKind.DATASET,
                    evidence_count=0,
                ),
                assessment_id="fixture_dataset_risk",
                basis="an attempt to wave a dataset through on owner risk",
                owner_risk_acceptance=_acceptance(),
                dataset_access_terms_satisfied=False,
            ),
        )
    )

    cases.append(
        _refusal_case(
            "a_dataset_assessment_must_answer_the_dataset_question",
            "a dataset record with no dataset answer is refused, not defaulted",
            ResearchUseDecisionError,
            lambda: assess_research_use(
                _observation(
                    LicenseObservationStatus.OPEN_SOURCE_PERMISSIVE,
                    kind=ThirdPartyComponentKind.DATASET,
                    names=("a permissive data licence",),
                ),
                assessment_id="fixture_dataset_unanswered",
                basis="a dataset assessed as though it were software",
            ),
        )
    )

    cases.append(
        _refusal_case(
            "a_partial_risk_acceptance_is_refused",
            "four of five conditions is a decision to block",
            ResearchUseDecisionError,
            lambda: _acceptance(no_bytes_will_be_redistributed=False),
        )
    )

    cases.append(
        _refusal_case(
            "risk_cannot_be_accepted_where_terms_were_identified",
            "the owner does not overrule a licence that was actually found",
            ResearchUseDecisionError,
            lambda: assess_research_use(
                _observation(
                    LicenseObservationStatus.OPEN_SOURCE_PERMISSIVE,
                    names=("Apache License 2.0",),
                ),
                assessment_id="fixture_risk_over_terms",
                basis="an attempt to accept risk over an identified licence",
                owner_risk_acceptance=_acceptance(),
            ),
        )
    )

    cases.append(
        _refusal_case(
            "an_intersection_needs_two_readings",
            "an intersection over one reading is that reading",
            LicenseObservationError,
            lambda: assess_research_use(
                _observation(
                    LicenseObservationStatus.ACADEMIC_ONLY,
                    names=("an academic-only licence",),
                    restrictions=("Academic use only.",),
                ),
                assessment_id="fixture_single_reading",
                basis="one reading dressed up as an intersection",
                non_blocking_restrictions=(
                    NonBlockingRestriction.ACADEMIC_OR_RESEARCH_ONLY,
                ),
                intersection_readings=(
                    PlausibleReading(
                        notice_locator="fixture://notice/0",
                        permits_local_execution=True,
                        permits_non_commercial_use=True,
                        permits_educational_research=True,
                    ),
                ),
            ),
        )
    )

    cases.append(
        _refusal_case(
            "a_field_limited_status_needs_the_intersection_computed",
            "a field-of-use restriction may not be waved through unexamined",
            ResearchUseDecisionError,
            lambda: assess_research_use(
                _observation(
                    LicenseObservationStatus.ACADEMIC_ONLY,
                    names=("an academic-only licence",),
                    restrictions=("Academic use only.",),
                ),
                assessment_id="fixture_uncomputed",
                basis="an academic-only licence assumed to be fine",
                non_blocking_restrictions=(
                    NonBlockingRestriction.ACADEMIC_OR_RESEARCH_ONLY,
                ),
            ),
        )
    )

    cases.append(
        _refusal_case(
            "permissive_and_field_limited_cannot_both_be_true",
            "an OSI-conforming licence cannot restrict the field of endeavour",
            ResearchUseDecisionError,
            lambda: assess_research_use(
                _observation(
                    LicenseObservationStatus.OPEN_SOURCE_PERMISSIVE,
                    names=("MIT License",),
                ),
                assessment_id="fixture_contradictory",
                basis="a record that read one of its two notices wrongly",
                non_blocking_restrictions=(
                    NonBlockingRestriction.NON_COMMERCIAL_ONLY,
                ),
            ),
        )
    )

    cases.append(
        _refusal_case(
            "an_observation_may_not_claim_a_licence_it_did_not_find",
            "NO_LICENSE_FOUND means inspected and carrying none",
            LicenseObservationError,
            lambda: _observation(
                LicenseObservationStatus.NO_LICENSE_FOUND,
                names=("Apache License 2.0",),
                evidence_count=0,
            ),
        )
    )

    cases.append(
        _refusal_case(
            "conflicting_notices_need_two_notices",
            "a conflict asserted over one notice is not a conflict",
            LicenseObservationError,
            lambda: _observation(
                LicenseObservationStatus.CONFLICTING_NOTICES,
                names=("Apache License 2.0",),
                evidence_count=1,
            ),
        )
    )

    cases.append(
        _refusal_case(
            "a_usage_record_may_not_say_it_is_stored_in_git",
            "there is no code path that puts a third-party byte in the repository",
            ThirdPartyUsageError,
            lambda: build_usage_record(
                record_id="fixture_in_git",
                observation=_observation(
                    LicenseObservationStatus.OPEN_SOURCE_PERMISSIVE,
                    observation_id="fixture_in_git_observation",
                    names=("MIT License",),
                ),
                assessment=permissive,
                upstream_identity=UpstreamIdentity(
                    upstream_name="a fixture",
                    upstream_locator="https://example.invalid/fixture",
                    exact_version="1",
                ),
                redistribution_decision=RedistributionDecision.ALLOWED,
                redistribution_basis="permitted and not exercised",
            ),
        )
    )

    results = tuple(cases)
    identifiers = [case.case_id for case in results]
    if len(set(identifiers)) != len(identifiers):
        raise Stage8EFinalizationError(
            "two policy cases share an id, so one of them is not being reported"
        )
    return PolicyQualification(
        cases=results,
        decision_cases=sum(1 for case in results if case.kind == "decision"),
        refusal_cases=sum(1 for case in results if case.kind == "refusal"),
        identity_cases=sum(1 for case in results if case.kind == "identity"),
        qualification_fingerprint=stable_hash(
            {
                "schema": "stage_8e_policy_qualification_v1",
                "cases": [to_plain(case) for case in results],
            },
            length=64,
        ),
    )


# ------------------------------------------------------------ contract report


def policy_contract_report(repository_root: Path) -> Mapping[str, Any]:
    """The structural facts the Stage 8E contract suite enforces.

    Everything in it is a property of the source or of the repository, not a
    measurement. Nothing in it is a licence text, an upstream byte or a path on
    anybody's machine.
    """
    from fpbench.experiments.stage8e_finalization import (
        policy_engine_fingerprint,
        source_file_sha256,
        third_party_model_fingerprint,
    )

    repository_root = Path(repository_root)
    qualification = run_policy_qualification()
    package = repository_root / "src" / "fpbench" / "third_party"
    declaration = project_purpose()
    policy = third_party_policy()

    return {
        "schema_version": "1",
        "statement": (
            "The structural facts the Stage 8E contract suite enforces. "
            "Everything here is a property of the source or of the public "
            "repository, not a measurement, and none of it is upstream content."
        ),
        "third_party_model_fingerprint": third_party_model_fingerprint(repository_root),
        "policy_engine_fingerprint": policy_engine_fingerprint(repository_root),
        "third_party_package": {
            "modules": list(frozen.THIRD_PARTY_PACKAGE_MODULES),
            "module_sha256": {
                name: source_file_sha256(package / name)
                for name in frozen.THIRD_PARTY_PACKAGE_MODULES
            },
        },
        "vocabulary": {
            "license_observation_status": sorted(
                member.value for member in LicenseObservationStatus
            ),
            "research_use_decision": sorted(
                member.value for member in ResearchUseDecision
            ),
            "component_kind": sorted(
                member.value for member in ThirdPartyComponentKind
            ),
            "non_blocking_restriction": sorted(
                member.value for member in NonBlockingRestriction
            ),
        },
        "purpose_fingerprint": declaration.purpose_fingerprint,
        "policy_fingerprint": policy.policy_fingerprint,
        "enforced_absences": {
            "repository_holds_no_license_file": not (
                repository_root / "LICENSE"
            ).exists(),
            "forbidden_workflow_tokens": [
                token for token, _field in FORBIDDEN_WORKFLOW_TOKENS
            ],
            "forbidden_published_keys": sorted(frozen.FORBIDDEN_PUBLISHED_KEYS),
        },
        "policy_documents": list(frozen.POLICY_DOCUMENTS),
        "decision_records": list(frozen.STAGE_8E_ADRS),
        "policy_qualification": {
            "qualification_fingerprint": qualification.qualification_fingerprint,
            "case_count": len(qualification.cases),
            "decision_cases": qualification.decision_cases,
            "refusal_cases": qualification.refusal_cases,
            "identity_cases": qualification.identity_cases,
            "cases": [to_plain(case) for case in qualification.cases],
        },
    }
