"""Re-deriving a third-party position, rather than believing it.

A usage record is not evidence of itself. Verification takes the observation it
cites, runs the decision table again over the facts the assessment recorded, and
compares — the decision, the permission status, the identities, and the three
flags that say this project publishes nothing.

It also re-derives the **binding**: which upstream the observation was taken
over, how that was established, and the digest covering all of it. That part
used to be missing, so a record could pass every check here while naming
somebody else's bytes — the two documents it compared were the only two it
knew about.

Two kinds of disagreement, deliberately not the same kind of event.

**These documents do not belong together.** A record citing an observation with a
different fingerprint, or an assessment about a different component kind, is not
a failed verification; it is a verification that cannot be attempted. That
raises.

**These documents disagree.** The parts refer to each other correctly and
re-derivation produces something else — a different decision, a different
permission status, a storage class the policy would not have assigned. That is a
finding, and it is *returned*, because the caller publishing an audit needs to
say what disagreed rather than catch an exception and reconstruct it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fpbench.core.third_party_errors import ThirdPartyUsageError
from fpbench.core.third_party_models import (
    LicenseObservation,
    ResearchUseAssessment,
    ResearchUseBlocker,
    ResearchUseDecision,
    ThirdPartyUsageManifest,
    ThirdPartyUsageRecord,
    derive_identity_link,
    license_observation_fingerprint,
    record_has_execution_eligible_identity,
    publisher_attestation_fingerprint,
    research_use_assessment_fingerprint,
    third_party_usage_fingerprint,
    upstream_binding_fingerprint,
    upstream_identity_fingerprint,
)
from fpbench.third_party.manifest import storage_class_for
from fpbench.third_party.policy import decide, needs_intersection, third_party_policy
from fpbench.third_party.purpose import project_purpose

__all__ = ["UsageVerificationReport", "verify_usage_record", "verify_usage_manifest"]


@dataclass(frozen=True, slots=True)
class UsageVerificationReport:
    """What a re-derivation found, in a form an audit can publish.

    ``verified`` is the only summary and it is the conjunction of the flags below
    it. There is no partial credit: a record whose fingerprints reproduce but
    whose decision does not is not "mostly right", it is a different decision.
    """

    record_id: str
    stored_decision: ResearchUseDecision
    recomputed_decision: ResearchUseDecision

    observation_fingerprint_reproduced: bool
    assessment_fingerprint_reproduced: bool
    record_fingerprint_reproduced: bool
    decision_reproduced: bool
    purpose_binding_holds: bool
    storage_class_follows_policy: bool
    publishes_nothing: bool
    #: The three parts still describe one component, and the digest that says
    #: so re-derives. Without this in the conjunction, a record whose identity
    #: had been swapped verified as long as its other seven flags held.
    upstream_binding_reproduced: bool = True

    findings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def verified(self) -> bool:
        return (
            self.observation_fingerprint_reproduced
            and self.assessment_fingerprint_reproduced
            and self.record_fingerprint_reproduced
            and self.decision_reproduced
            and self.purpose_binding_holds
            and self.storage_class_follows_policy
            and self.publishes_nothing
            and self.upstream_binding_reproduced
            and not self.findings
        )


def verify_usage_record(
    record: ThirdPartyUsageRecord,
    observation: LicenseObservation,
    assessment: ResearchUseAssessment,
) -> UsageVerificationReport:
    """Run the decision table again and compare it with what was recorded.

    The re-derivation is over the facts the assessment *stored* — the blockers it
    named, whether a risk was accepted, and whether the observation's status and
    restrictions require an intersection. The plausible readings themselves are
    not stored, so the boolean they produced is taken as given; what is checked
    is that the decision follows from it. That is the honest limit of this
    verification and it is worth stating: it re-derives the policy, not the
    reading of a notice.

    Raises:
        ThirdPartyUsageError: the three documents are not about the same
            component, so there is nothing to verify against.
    """
    if not isinstance(record, ThirdPartyUsageRecord):
        raise ThirdPartyUsageError("verification needs a stored usage record")
    if record.license_observation_fingerprint != observation.observation_fingerprint:
        raise ThirdPartyUsageError(
            f"{record.record_id} cites observation "
            f"{record.license_observation_fingerprint[:12]}... and is being "
            f"verified against {observation.observation_fingerprint[:12]}..."
        )
    if record.research_use_assessment_fingerprint != assessment.assessment_fingerprint:
        raise ThirdPartyUsageError(
            f"{record.record_id} cites assessment "
            f"{record.research_use_assessment_fingerprint[:12]}... and is being "
            f"verified against {assessment.assessment_fingerprint[:12]}..."
        )
    if not (
        record.component_kind
        is observation.component_kind
        is assessment.component_kind
    ):
        raise ThirdPartyUsageError(
            f"{record.record_id}: the record, the observation and the assessment "
            "are about different component kinds"
        )

    findings: list[str] = []

    observation_ok = (
        license_observation_fingerprint(observation)
        == observation.observation_fingerprint
    )
    if not observation_ok:
        findings.append("the observation does not fingerprint to what it says")

    assessment_ok = (
        research_use_assessment_fingerprint(assessment)
        == assessment.assessment_fingerprint
    )
    if not assessment_ok:
        findings.append("the assessment does not fingerprint to what it decides")

    record_ok = third_party_usage_fingerprint(record) == record.usage_fingerprint
    if not record_ok:
        findings.append("the record does not fingerprint to what it carries")

    binding_ok = _reproduce_the_binding(record, observation, assessment, findings)

    recomputed, permission = decide(
        blockers=assessment.blockers,
        owner_risk_accepted=assessment.owner_risk_acceptance is not None,
        intersection_required=needs_intersection(
            observation.status, assessment.non_blocking_restrictions
        ),
    )
    decision_ok = (
        recomputed is assessment.decision
        and recomputed is record.research_use_decision
        and permission is assessment.intended_use_permission_status
    )
    if not decision_ok:
        findings.append(
            f"the decision re-derives as {recomputed.value} under "
            f"{permission.value}, and is stored as "
            f"{assessment.decision.value} under "
            f"{assessment.intended_use_permission_status.value}"
        )

    declaration = project_purpose()
    policy = third_party_policy()
    purpose_ok = (
        record.purpose_fingerprint == declaration.purpose_fingerprint
        and assessment.purpose_fingerprint == declaration.purpose_fingerprint
        and policy.purpose_fingerprint == declaration.purpose_fingerprint
    )
    if not purpose_ok:
        findings.append(
            "the record was assessed under a purpose this repository has not frozen"
        )

    expected_storage = storage_class_for(record.component_kind)
    storage_ok = record.storage_class is expected_storage
    if not storage_ok:
        findings.append(
            f"a {record.component_kind.value} component belongs in "
            f"{expected_storage.value} and this record claims "
            f"{record.storage_class.value}"
        )

    publishes_nothing = (
        record.stored_in_git is False
        and record.stored_in_ci_artifacts is False
        and record.redistribution.redistributed_by_fpbench is False
    )
    if not publishes_nothing:
        findings.append("the record claims this project publishes third-party bytes")

    return UsageVerificationReport(
        record_id=record.record_id,
        stored_decision=record.research_use_decision,
        recomputed_decision=recomputed,
        observation_fingerprint_reproduced=observation_ok,
        assessment_fingerprint_reproduced=assessment_ok,
        record_fingerprint_reproduced=record_ok,
        decision_reproduced=decision_ok,
        purpose_binding_holds=purpose_ok,
        storage_class_follows_policy=storage_ok,
        publishes_nothing=publishes_nothing,
        upstream_binding_reproduced=binding_ok,
        findings=tuple(findings),
    )


def _reproduce_the_binding(
    record: ThirdPartyUsageRecord,
    observation: LicenseObservation,
    assessment: ResearchUseAssessment,
    findings: list[str],
) -> bool:
    """Re-derive every part of the binding from the documents, not the record.

    Four separate questions, because a single "the binding fingerprint matches"
    would pass on a record that had been rewritten consistently. The digest is
    checked *last*, over values this function computed rather than values the
    record supplied:

    * the identity fingerprint, from the identity beside the record;
    * the evidence locators, against the observation the record cites --- a
      record that quietly edited its own copy could otherwise derive a basis
      the observation does not support;
    * the basis, from those locators and that identity;
    * the attestation's own fingerprint, where there is one.
    """
    findings_before = len(findings)

    identity_fingerprint = upstream_identity_fingerprint(record.upstream_identity)
    if record.upstream_identity_fingerprint != identity_fingerprint:
        findings.append(
            "the upstream identity fingerprint does not cover the identity the "
            "record carries"
        )

    published_locators = tuple(record.license_evidence_locators)
    observed_locators = tuple(item.locator for item in observation.evidence)
    if published_locators != observed_locators:
        findings.append(
            "the record's licence evidence locators are not the observation's: "
            f"{list(published_locators)} against {list(observed_locators)}"
        )

    basis = derive_identity_link(observed_locators, record.upstream_identity)
    if record.identity_link_basis is not basis:
        findings.append(
            f"the record publishes {record.identity_link_basis.value} and the "
            f"observation and identity derive {basis.value}"
        )

    attestation = record.publisher_attestation
    attestation_fingerprint = None
    if attestation is not None:
        attestation_fingerprint = attestation.attestation_fingerprint
        if publisher_attestation_fingerprint(attestation) != attestation_fingerprint:
            findings.append(
                "the publisher attestation does not fingerprint to what it says"
            )
    if not basis.requires_attestation and attestation is not None:
        findings.append(
            f"the record is {basis.value} and carries an attestation nothing checks"
        )
    if basis.requires_attestation and attestation is None:
        findings.append(
            "the record rests on the publisher's assertion and carries none"
        )
    if attestation is not None:
        filed_against = upstream_identity_fingerprint(record.upstream_identity)
        if attestation.asserted_upstream_identity_fingerprint != filed_against:
            findings.append(
                "the attestation was made about a different upstream identity "
                "than the one this record carries"
            )
    blocks_on_identity = (
        ResearchUseBlocker.ARTIFACT_IDENTITY_NOT_ESTABLISHED in assessment.blockers
    )
    if blocks_on_identity is record.upstream_identity.identity_established:
        findings.append(
            "the identity says established="
            f"{record.upstream_identity.identity_established} and the assessment "
            f"{'blocks' if blocks_on_identity else 'does not block'} on "
            "ARTIFACT_IDENTITY_NOT_ESTABLISHED, which are the same fact"
        )
    if not record_has_execution_eligible_identity(record):
        if record.research_use_decision is not ResearchUseDecision.BLOCKED:
            findings.append(
                "the record has an unresolved upstream identity and a decision "
                f"of {record.research_use_decision.value}"
            )
        if (
            record.upstream_identity.artifact_sha256 is not None
            or record.upstream_identity.artifact_size_bytes is not None
        ):
            findings.append(
                "the record has an unresolved upstream identity and measured "
                "bytes, which cannot both be true"
            )

    expected = upstream_binding_fingerprint(
        component_kind=record.component_kind,
        observation_fingerprint=observation.observation_fingerprint,
        assessment_fingerprint=record.research_use_assessment_fingerprint,
        identity_fingerprint=identity_fingerprint,
        identity_link_basis=basis,
        attestation_fingerprint=attestation_fingerprint,
    )
    if record.binding_fingerprint != expected:
        findings.append(
            "the binding fingerprint does not cover the three documents this "
            "record ties together"
        )

    return len(findings) == findings_before


def verify_usage_manifest(
    manifest: ThirdPartyUsageManifest,
    observations: dict[str, LicenseObservation],
    assessments: dict[str, ResearchUseAssessment],
) -> tuple[UsageVerificationReport, ...]:
    """Every record of one manifest, keyed by ``record_id``.

    Raises:
        ThirdPartyUsageError: a record has no observation or no assessment to
            verify against. A manifest that could be partially verified would
            report "no findings" for the components nobody looked at.
    """
    reports = []
    for record in manifest.records:
        observation = observations.get(record.record_id)
        assessment = assessments.get(record.record_id)
        if observation is None or assessment is None:
            raise ThirdPartyUsageError(
                f"{manifest.manifest_id}: {record.record_id} has no "
                f"{'observation' if observation is None else 'assessment'} to "
                "verify against"
            )
        reports.append(verify_usage_record(record, observation, assessment))
    return tuple(reports)
