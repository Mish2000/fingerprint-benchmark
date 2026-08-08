"""The repository-wide rule, and the mechanical derivation of every decision.

The rule, in one sentence:

    Third-party licensing does not block local personal educational research
    execution merely because commercial use, redistribution, sublicensing or
    publication is restricted.

That sentence is not "licences do not matter". Upstream rights are recorded
faithfully in a :class:`~fpbench.core.third_party_models.LicenseObservation` and
are never rewritten to suit a decision. What changes is which of those recorded
facts is allowed to *stop* something: a restriction on an operation this project
does not perform stops nothing, because the project has frozen a declaration
saying it does not perform it (docs/adr/0081, docs/adr/0082).

The short list that does stop something is in :data:`BLOCKING_CONDITIONS`, and it
is short on purpose. Everything else is in :data:`NON_BLOCKING_RESTRICTIONS`,
recorded and respected and not a blocker.

**Nothing here decides anything by hand.** :func:`assess_research_use` is given
the observation and the facts, and derives the decision; it does not accept one.
That is the difference between a policy and a habit — Stage 9A and every stage
after it fill in the facts and get the same answer this stage would have given.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from fpbench.core.third_party_errors import (
    LicenseObservationError,
    ResearchUseDecisionError,
)
from fpbench.core.third_party_models import (
    IntendedUsePermissionStatus,
    LicenseObservation,
    LicenseObservationStatus,
    NonBlockingRestriction,
    OwnerRiskAcceptance,
    ProjectPurpose,
    ResearchUseAssessment,
    ResearchUseBlocker,
    ResearchUseDecision,
    ThirdPartyComponentKind,
    ThirdPartyPolicy,
    UpstreamModificationStrategy,
)
from fpbench.third_party.purpose import project_purpose

__all__ = [
    "POLICY_ID",
    "POLICY_VERSION",
    "POLICY_STATEMENT",
    "NON_BLOCKING_RESTRICTIONS",
    "BLOCKING_CONDITIONS",
    "OWNER_RISK_CONDITIONS",
    "REPOSITORY_PERMITTED_CONTENT",
    "REPOSITORY_FORBIDDEN_CONTENT",
    "MODIFICATION_STRATEGY_ORDER",
    "INTENDED_OPERATION",
    "PlausibleReading",
    "third_party_policy",
    "policy_fingerprint",
    "intersection_permits_intended_use",
    "needs_intersection",
    "decide",
    "assess_research_use",
]

POLICY_ID = "fpbench_research_only_third_party_v1"
POLICY_VERSION = "1"

POLICY_STATEMENT = (
    "Third-party licensing does not block local personal educational research "
    "execution merely because commercial use, redistribution, sublicensing or "
    "publication is restricted. Upstream rights are recorded faithfully and "
    "separately from the decision to execute. fpbench redistributes no "
    "third-party bytes. Legal ambiguity stays visible and may be explicitly "
    "risk-accepted for local research instead of silently becoming an "
    "engineering blocker."
)

#: The exact operation every assessment in this repository is about. One string,
#: so that two records cannot quietly be about different things.
INTENDED_OPERATION = (
    "local execution on the project owner's own machine, for personal "
    "educational research, publishing no third-party bytes"
)

#: Restrictions that are real, recorded, respected — and not blockers, because
#: none of them touches what this project actually does (docs/adr/0081).
NON_BLOCKING_RESTRICTIONS: tuple[NonBlockingRestriction, ...] = tuple(
    NonBlockingRestriction
)

#: The closed list of things that do block. Every member is either a prohibition
#: on the exact operation, or a reason the artifact cannot honestly be described.
BLOCKING_CONDITIONS: tuple[ResearchUseBlocker, ...] = tuple(ResearchUseBlocker)

#: All five, and all five are required together. Fewer than five is a decision to
#: block, not a weaker acceptance (docs/adr/0084).
OWNER_RISK_CONDITIONS: tuple[str, ...] = (
    "the artifact was intentionally published by its official authors",
    "the artifact is publicly obtainable without circumventing any access control",
    "the intended operation is local research only",
    "no located term expressly prohibits that use",
    "no bytes will be redistributed by this project",
)

#: What the public repository may hold about a third-party component.
REPOSITORY_PERMITTED_CONTENT: tuple[str, ...] = (
    "acquisition code",
    "upstream URLs and identifiers",
    "upstream commit SHAs",
    "exact versions",
    "SHA-256 digests",
    "expected byte sizes",
    "configuration",
    "dependency locks",
    "artifact metadata",
    "provenance records",
    "project-written integration glue",
    "generated evidence",
)

#: What it may not, whatever the licence permits (docs/adr/0083).
REPOSITORY_FORBIDDEN_CONTENT: tuple[str, ...] = (
    "a copy of an upstream repository",
    "model weights",
    "a checkpoint",
    "a runtime bundle",
    "a compiled upstream binary",
    "a dataset",
    "fingerprint images",
    "extracted embeddings",
    "an upstream archive",
)

#: The ladder for changing upstream source, in the order it must be tried.
MODIFICATION_STRATEGY_ORDER: tuple[UpstreamModificationStrategy, ...] = (
    UpstreamModificationStrategy.WRAPPER_WITHOUT_UPSTREAM_MODIFICATION,
    UpstreamModificationStrategy.PROJECT_OWNED_TRANSFORMATION_RECIPE,
    UpstreamModificationStrategy.LOCAL_PATCH,
)


def third_party_policy() -> ThirdPartyPolicy:
    """The frozen policy document, rebuilt from source.

    Derived rather than read, for the reason the purpose declaration is: the
    published ``third-party-policy.json`` is then something the evidence gate can
    *check*, and an edit to the committed JSON is a finding.
    """
    return ThirdPartyPolicy(
        schema_version="1",
        policy_id=POLICY_ID,
        policy_version=POLICY_VERSION,
        statement=POLICY_STATEMENT,
        purpose_fingerprint=project_purpose().purpose_fingerprint,
        non_blocking_restrictions=NON_BLOCKING_RESTRICTIONS,
        blocking_conditions=BLOCKING_CONDITIONS,
        owner_risk_conditions=OWNER_RISK_CONDITIONS,
        vendoring_default="DO_NOT_VENDOR",
        repository_permitted_content=REPOSITORY_PERMITTED_CONTENT,
        repository_forbidden_content=REPOSITORY_FORBIDDEN_CONTENT,
        modification_strategy_order=MODIFICATION_STRATEGY_ORDER,
        ci_downloads_restricted_artifacts=False,
        ci_uploads_third_party_bytes=False,
        publishes_container_images_with_third_party_artifacts=False,
        dataset_rights_unchanged=True,
    )


def policy_fingerprint() -> str:
    return third_party_policy().policy_fingerprint


# ------------------------------------------------------------ the intersection


@dataclass(frozen=True, slots=True)
class PlausibleReading:
    """One way a reasonable reader could understand a component's notices.

    Used where notices conflict — a permissive ``LICENSE`` file beside a README
    that says "academic use only". The project does not pick a winner, because it
    does not have to: the question is not "which notice governs?" but "is there
    any reading under which our exact operation is not permitted?"
    (docs/adr/0082).
    """

    notice_locator: str
    permits_local_execution: bool
    permits_non_commercial_use: bool
    permits_educational_research: bool

    def __post_init__(self) -> None:
        if not str(self.notice_locator).strip():
            raise LicenseObservationError("a plausible reading names the notice it reads")
        for name in (
            "permits_local_execution",
            "permits_non_commercial_use",
            "permits_educational_research",
        ):
            if type(getattr(self, name)) is not bool:
                raise LicenseObservationError(f"{name} must be a boolean")

    @property
    def permits_intended_use(self) -> bool:
        return (
            self.permits_local_execution
            and self.permits_non_commercial_use
            and self.permits_educational_research
        )


def intersection_permits_intended_use(
    readings: Sequence[PlausibleReading],
) -> bool:
    """Whether every plausible reading permits this project's exact operation.

    The conjunction, not the majority and not the most likely. If one reasonable
    reading of one notice forbids local non-commercial educational use, the
    intersection does not contain it and the answer is ``False`` — which is a
    blocker, and correctly so.

    Raises:
        LicenseObservationError: fewer than two readings. An "intersection" over
            a single reading is that reading, and calling it an intersection
            would dress an ordinary licence conclusion up as a conservative one.
    """
    readings = tuple(readings)
    if len(readings) < 2:
        raise LicenseObservationError(
            "an intersection needs at least two plausible readings; with one "
            "reading there is nothing to intersect"
        )
    for reading in readings:
        if not isinstance(reading, PlausibleReading):
            raise LicenseObservationError("every reading must be a PlausibleReading")
    return all(reading.permits_intended_use for reading in readings)


# ------------------------------------------------------------- the decision rule


def needs_intersection(
    status: LicenseObservationStatus,
    restrictions: Sequence[NonBlockingRestriction],
) -> bool:
    """Whether the conservative answer has to be computed rather than assumed.

    True when the notices conflict, or when anything in sight limits the *field*
    of use rather than the manner of it. Extracted so that the derivation below
    and the verifier in :mod:`fpbench.third_party.verify` cannot drift: a
    verifier with its own copy of this predicate would eventually be checking a
    different policy from the one that decided.
    """
    return status is LicenseObservationStatus.CONFLICTING_NOTICES or (
        status.limits_field_of_use
        or any(restriction.limits_field_of_use for restriction in restrictions)
    )


def decide(
    *,
    blockers: Sequence[ResearchUseBlocker],
    owner_risk_accepted: bool,
    intersection_required: bool,
) -> tuple[ResearchUseDecision, IntendedUsePermissionStatus]:
    """The whole decision table, in one place and in this order.

    Order matters and is the policy: a blocker beats everything, an accepted risk
    is the answer only where nothing was established, and an intersection is
    distinguished from a plain permission so that a later reader can see which
    kind of "yes" this was (docs/adr/0082, docs/adr/0084).
    """
    if blockers:
        return ResearchUseDecision.BLOCKED, IntendedUsePermissionStatus.UNRESOLVED
    if owner_risk_accepted:
        return (
            ResearchUseDecision.OWNER_RISK_ACCEPTED,
            IntendedUsePermissionStatus.UNRESOLVED,
        )
    if intersection_required:
        return (
            ResearchUseDecision.ALLOWED_UNDER_RESTRICTIVE_INTERSECTION,
            IntendedUsePermissionStatus.ESTABLISHED,
        )
    return ResearchUseDecision.ALLOWED, IntendedUsePermissionStatus.ESTABLISHED


# --------------------------------------------------------------- the assessment


def assess_research_use(
    observation: LicenseObservation,
    *,
    assessment_id: str,
    basis: str,
    non_blocking_restrictions: Iterable[NonBlockingRestriction] = (),
    located_prohibitions: Iterable[ResearchUseBlocker] = (),
    identity_established: bool = True,
    intersection_readings: Sequence[PlausibleReading] | None = None,
    owner_risk_acceptance: OwnerRiskAcceptance | None = None,
    dataset_access_terms_satisfied: bool | None = None,
) -> ResearchUseAssessment:
    """Derive the one decision that follows from these facts.

    The caller supplies observations and facts. It does not supply a decision,
    and there is no parameter through which it could: an engine that accepted a
    verdict and then validated it would be a very elaborate way of writing the
    verdict down (docs/adr/0082).

    Args:
        observation: what upstream's notices say. Cited by fingerprint in the
            result, so it cannot be edited underneath the decision.
        non_blocking_restrictions: the restrictions the notices state, in the
            shared vocabulary. Recorded, respected, and not blockers.
        located_prohibitions: blockers that were actually found — an express
            prohibition of research use, of biometric use, of the modification
            faithful execution requires, access terms that cannot be satisfied,
            or an artifact obtained by circumventing a technical restriction.
        identity_established: whether the exact bytes and provenance are pinned.
            An artifact nobody can name is blocked whatever its licence says.
        intersection_readings: supplied where the notices conflict or restrict
            the field of use, so that the conservative answer can be computed
            rather than asserted.
        owner_risk_acceptance: supplied only where no permission was established
            at all. Not a finding that the use is permitted (docs/adr/0084).
        dataset_access_terms_satisfied: required for, and only for, a dataset.
            Stage 8E did not make dataset restrictions non-blocking.

    Raises:
        ResearchUseDecisionError: the facts are inconsistent with each other —
            an intersection offered where nothing restricts the field of use, a
            risk acceptance offered where terms were identified, or a dataset
            record with no dataset answer.
    """
    if not isinstance(observation, LicenseObservation):
        raise ResearchUseDecisionError(
            "an assessment is about one recorded observation, not about a "
            "recollection of one"
        )
    restrictions = tuple(non_blocking_restrictions)
    blockers = list(located_prohibitions)
    kind = observation.component_kind
    declaration = project_purpose()

    _require_restrictions_match_the_status(observation, restrictions)

    if type(identity_established) is not bool:
        raise ResearchUseDecisionError("identity_established must be a boolean")
    if not identity_established:
        blockers.append(ResearchUseBlocker.ARTIFACT_IDENTITY_NOT_ESTABLISHED)

    is_dataset = kind is ThirdPartyComponentKind.DATASET
    if is_dataset and dataset_access_terms_satisfied is None:
        raise ResearchUseDecisionError(
            f"{assessment_id}: a dataset assessment states whether its own access "
            "terms are satisfied. Biometric access terms, privacy and data-use "
            "conditions are outside this policy and stay blocking "
            "(spec section 11)"
        )
    if not is_dataset and dataset_access_terms_satisfied is not None:
        raise ResearchUseDecisionError(
            f"{assessment_id}: dataset_access_terms_satisfied belongs to a "
            f"dataset assessment and this is a {kind.value} assessment"
        )
    if is_dataset and dataset_access_terms_satisfied is not True:
        blockers.append(ResearchUseBlocker.DATASET_ACCESS_TERMS_NOT_SATISFIED)

    notices_conflict = (
        observation.status is LicenseObservationStatus.CONFLICTING_NOTICES
    )
    intersection_required = needs_intersection(observation.status, restrictions)
    permission_unresolved = not observation.status.identifies_terms and not notices_conflict

    intersection_holds = False
    if intersection_readings is not None:
        if not intersection_required:
            raise ResearchUseDecisionError(
                f"{assessment_id}: an intersection was offered, and nothing here "
                "restricts the field of use or conflicts. That is an ordinary "
                "ALLOWED, and calling it an intersection would overstate the care "
                "taken"
            )
        intersection_holds = intersection_permits_intended_use(intersection_readings)
        if not intersection_holds:
            blockers.append(
                ResearchUseBlocker.INTENDED_RESEARCH_USE_EXPRESSLY_PROHIBITED
            )
    elif intersection_required and not permission_unresolved:
        raise ResearchUseDecisionError(
            f"{assessment_id}: the notices restrict the field of use or conflict, "
            "so the conservative answer has to be computed from the readings "
            "rather than assumed"
        )

    if owner_risk_acceptance is not None:
        if not isinstance(owner_risk_acceptance, OwnerRiskAcceptance):
            raise ResearchUseDecisionError(
                "owner_risk_acceptance must be an OwnerRiskAcceptance"
            )
        if not permission_unresolved:
            raise ResearchUseDecisionError(
                f"{assessment_id}: risk is accepted where permission is "
                "unresolved. Terms were identified here, so the answer follows "
                "from them rather than from the owner"
            )
        if is_dataset:
            raise ResearchUseDecisionError(
                f"{assessment_id}: dataset rights are not risk-accepted "
                "(spec section 11)"
            )
    elif permission_unresolved and not blockers:
        blockers.append(
            ResearchUseBlocker.PERMISSION_UNRESOLVED_AND_NOT_RISK_ACCEPTED
        )

    # The decision, from the one table. Nothing else in this project chooses one.
    decision, permission = decide(
        blockers=blockers,
        owner_risk_accepted=owner_risk_acceptance is not None,
        intersection_required=intersection_required,
    )

    return ResearchUseAssessment(
        schema_version="1",
        assessment_id=assessment_id,
        observation_fingerprint=observation.observation_fingerprint,
        component_kind=kind,
        purpose=ProjectPurpose.PERSONAL_EDUCATIONAL_RESEARCH,
        purpose_fingerprint=declaration.purpose_fingerprint,
        intended_operation=INTENDED_OPERATION,
        decision=decision,
        basis=basis,
        intended_use_permission_status=permission,
        non_blocking_restrictions=restrictions,
        blockers=tuple(blockers),
        intersection_permits_intended_use=intersection_holds,
        owner_risk_acceptance=owner_risk_acceptance,
        dataset_access_terms_satisfied=dataset_access_terms_satisfied,
    )


def _require_restrictions_match_the_status(
    observation: LicenseObservation,
    restrictions: tuple[NonBlockingRestriction, ...],
) -> None:
    """The named restrictions and the observed status have to agree.

    Two directions, and both have bitten real records:

    * a status that limits the field of use — ``ACADEMIC_ONLY``,
      ``RESEARCH_ONLY``, ``NON_COMMERCIAL``, ``SOURCE_AVAILABLE`` — with no
      field-limiting restriction named is a record that read the notice and then
      lost what it said;
    * a field-limiting restriction under ``OPEN_SOURCE_PERMISSIVE`` is the
      opposite mistake, and it is the one that matters: an OSI-conforming licence
      cannot restrict the field of endeavour, so a record claiming both has
      mis-read one of them.
    """
    for restriction in restrictions:
        if not isinstance(restriction, NonBlockingRestriction):
            raise ResearchUseDecisionError(
                "non_blocking_restrictions must hold NonBlockingRestriction members"
            )
    limited_by_status = observation.status.limits_field_of_use
    limited_by_restriction = any(
        restriction.limits_field_of_use for restriction in restrictions
    )
    if limited_by_status and not limited_by_restriction:
        raise ResearchUseDecisionError(
            f"{observation.observation_id}: the status is "
            f"{observation.status.value} and no field-of-use restriction is "
            "named, so the record has lost what the notice said"
        )
    if (
        observation.status is LicenseObservationStatus.OPEN_SOURCE_PERMISSIVE
        and limited_by_restriction
    ):
        raise ResearchUseDecisionError(
            f"{observation.observation_id}: OPEN_SOURCE_PERMISSIVE alongside a "
            "field-of-use restriction. A licence that restricts the field of "
            "endeavour is source-available, not open source, and one of the two "
            "readings here is wrong"
        )
