"""Assembling one component's observation and decision into the shared record.

This is the contract a new algorithm fills in. Stage 8A, 8B and 8C each argued
about licensing from scratch and reached three differently-shaped conclusions;
from Stage 9A onward an integration writes one
:class:`~fpbench.core.third_party_models.ThirdPartyUsageRecord` per component and
the gate is mechanical.

The builders here do one thing the models cannot do for themselves: they *bind*.
A record cites the observation and the assessment by fingerprint, and
:func:`build_usage_record` refuses to mint one whose parts do not refer to each
other — an assessment of a different observation, an observation of a different
component kind, a decision taken under a different purpose. Those are not
findings to report, they are documents that do not belong together.
"""

from __future__ import annotations

from typing import Iterable, Sequence

from fpbench.core.third_party_errors import ThirdPartyUsageError
from fpbench.core.third_party_models import (
    ArtifactStorageClass,
    LicenseObservation,
    ProjectPurpose,
    RedistributionDecision,
    RedistributionRecord,
    ResearchUseAssessment,
    ResearchUseDecision,
    ThirdPartyComponentKind,
    ThirdPartyUsageManifest,
    ThirdPartyUsageRecord,
    UpstreamIdentity,
)
from fpbench.third_party.policy import third_party_policy
from fpbench.third_party.purpose import project_purpose

__all__ = [
    "BYTES_BEARING_KINDS",
    "DESCRIBED_KINDS",
    "build_usage_record",
    "build_usage_manifest",
    "require_manifest_opens_execution",
    "storage_class_for",
]

#: Component kinds that *are* bytes rather than descriptions of bytes. Each one
#: lives in the local artifact store and never in Git, whatever its licence
#: permits (docs/adr/0083).
BYTES_BEARING_KINDS: frozenset[ThirdPartyComponentKind] = frozenset(
    {
        ThirdPartyComponentKind.MODEL_WEIGHTS,
        ThirdPartyComponentKind.RUNTIME_BINARY,
        ThirdPartyComponentKind.DATASET,
    }
)


#: The two kinds that are *descriptions* of upstream rather than upstream. A
#: Maven coordinate in a POM and a URL in a document bring no bytes into the
#: tree; everything else does, and goes in the local store.
DESCRIBED_KINDS: frozenset[ThirdPartyComponentKind] = frozenset(
    {
        ThirdPartyComponentKind.PACKAGE_DEPENDENCY,
        ThirdPartyComponentKind.DOCUMENTATION,
    }
)


def storage_class_for(kind: ThirdPartyComponentKind) -> ArtifactStorageClass:
    """Where a component of this kind is allowed to live.

    ``SOURCE_CODE`` is in the local store, and that is the part people find
    surprising: an upstream repository is a runtime artifact exactly like a
    checkpoint, acquired at a pinned commit and verified by digest, rather than
    copied into ``vendor/``. What the repository keeps is the acquisition code
    and the digest (spec section 7).

    The default runs the other way round from the obvious one — everything is
    bytes unless it is named as a description — because a kind added later
    should have to argue its way into the repository rather than land there by
    omission.
    """
    if kind in DESCRIBED_KINDS:
        return ArtifactStorageClass.REPOSITORY_METADATA
    return ArtifactStorageClass.LOCAL_ARTIFACT_STORE


def build_usage_record(
    *,
    record_id: str,
    observation: LicenseObservation,
    assessment: ResearchUseAssessment,
    upstream_identity: UpstreamIdentity,
    redistribution_decision: RedistributionDecision,
    redistribution_basis: str,
    storage_class: ArtifactStorageClass | None = None,
    notes: Iterable[str] = (),
) -> ThirdPartyUsageRecord:
    """One component's whole third-party position, bound and fingerprinted.

    Raises:
        ThirdPartyUsageError: the observation, the assessment and the identity do
            not describe the same component. Continuing would produce a record
            about three unrelated things that happened to be passed together.
    """
    if not isinstance(observation, LicenseObservation):
        raise ThirdPartyUsageError("a usage record needs a recorded observation")
    if not isinstance(assessment, ResearchUseAssessment):
        raise ThirdPartyUsageError("a usage record needs a derived assessment")
    if assessment.observation_fingerprint != observation.observation_fingerprint:
        raise ThirdPartyUsageError(
            f"{record_id}: the assessment was taken over observation "
            f"{assessment.observation_fingerprint[:12]}... and the observation "
            f"offered is {observation.observation_fingerprint[:12]}..."
        )
    if assessment.component_kind is not observation.component_kind:
        raise ThirdPartyUsageError(
            f"{record_id}: the observation is about a "
            f"{observation.component_kind.value} and the assessment about a "
            f"{assessment.component_kind.value}. A repository licence is not a "
            "checkpoint licence (docs/adr/0063)"
        )
    declaration = project_purpose()
    if assessment.purpose_fingerprint != declaration.purpose_fingerprint:
        raise ThirdPartyUsageError(
            f"{record_id}: the assessment was taken under a purpose this "
            "repository has not frozen"
        )

    resolved_storage = (
        storage_class_for(observation.component_kind)
        if storage_class is None
        else storage_class
    )
    return ThirdPartyUsageRecord(
        schema_version="1",
        record_id=record_id,
        purpose=ProjectPurpose.PERSONAL_EDUCATIONAL_RESEARCH,
        purpose_fingerprint=declaration.purpose_fingerprint,
        component_kind=observation.component_kind,
        upstream_identity=upstream_identity,
        license_observation_fingerprint=observation.observation_fingerprint,
        license_observation_status=observation.status,
        license_evidence_locators=tuple(
            item.locator for item in observation.evidence
        ),
        research_use_decision=assessment.decision,
        research_use_basis=assessment.basis,
        research_use_assessment_fingerprint=assessment.assessment_fingerprint,
        owner_risk_acceptance=(
            assessment.decision is ResearchUseDecision.OWNER_RISK_ACCEPTED
        ),
        redistribution=RedistributionRecord(
            decision=redistribution_decision,
            basis=redistribution_basis,
            redistributed_by_fpbench=False,
        ),
        storage_class=resolved_storage,
        stored_in_git=False,
        stored_in_ci_artifacts=False,
        notes=tuple(notes),
    )


def build_usage_manifest(
    *,
    manifest_id: str,
    subject: str,
    records: Sequence[ThirdPartyUsageRecord],
) -> ThirdPartyUsageManifest:
    """Every component of one integration, under this repository's one policy."""
    return ThirdPartyUsageManifest(
        manifest_id=manifest_id,
        subject=subject,
        purpose_fingerprint=project_purpose().purpose_fingerprint,
        policy_fingerprint=third_party_policy().policy_fingerprint,
        records=tuple(records),
    )


def require_manifest_opens_execution(manifest: ThirdPartyUsageManifest) -> None:
    """The gate a future stage runs before executing an integration.

    Every component, not the artifact as a whole: a clear source licence has
    never been able to satisfy an absent weights licence, and it still cannot
    (docs/adr/0063).

    Raises:
        ThirdPartyUsageError: at least one component is ``BLOCKED``, named with
            the decision that blocked it.
    """
    blocked = manifest.blocked_records
    if blocked:
        detail = ", ".join(
            f"{record.record_id} ({record.license_observation_status.value})"
            for record in blocked
        )
        raise ThirdPartyUsageError(
            f"{manifest.manifest_id}: these components may not be executed under "
            f"this project's purpose: {detail}"
        )
