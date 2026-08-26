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

**The third part used to be unbound.** ``UpstreamIdentity`` travelled beside the
other two and nothing checked that it was the same component, so a record could
carry upstream X's licence next to upstream Y's bytes and read as ordinary.
:func:`bind_component` is now the only way in: it derives how the observation
and the identity are tied, demands a :class:`PublisherAttestation` where they
are not tied by anything the documents say, and returns a
:class:`BoundUpstreamComponent` that :func:`build_usage_record` takes *instead
of* the three loose parts. There is no argument list that accepts them
separately, which is what makes the binding unbypassable rather than merely
available.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Iterable, Sequence

from fpbench.core.third_party_errors import ThirdPartyUsageError
from fpbench.core.third_party_models import (
    THIRD_PARTY_USAGE_SCHEMA_VERSION,
    ArtifactStorageClass,
    AttestationMethod,
    BoundUpstreamComponent,
    IdentityLinkBasis,
    LicenseObservation,
    ProjectPurpose,
    PublisherAttestation,
    RedistributionDecision,
    RedistributionRecord,
    ResearchUseAssessment,
    ResearchUseDecision,
    ThirdPartyComponentKind,
    ThirdPartyUsageManifest,
    ThirdPartyUsageRecord,
    UpstreamIdentity,
    attestation_reference_paths,
    derive_identity_link as _derive_identity_link_from_locators,
    record_has_execution_eligible_identity,
    upstream_identity_fingerprint,
)
from fpbench.third_party.policy import third_party_policy
from fpbench.third_party.purpose import project_purpose

__all__ = [
    "BYTES_BEARING_KINDS",
    "DESCRIBED_KINDS",
    "AttestationMethod",
    "BoundUpstreamComponent",
    "IdentityLinkBasis",
    "PublisherAttestation",
    "bind_component",
    "require_attestation_references_are_tracked",
    "require_bound_component_references_are_tracked",
    "build_usage_record",
    "build_usage_manifest",
    "derive_identity_link",
    "require_manifest_opens_execution",
    "storage_class_for",
    "upstream_identity_fingerprint",
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


def derive_identity_link(
    observation: LicenseObservation, identity: UpstreamIdentity
) -> IdentityLinkBasis:
    """Read the pairing out of an observation and the identity beside it.

    A thin wrapper over the derivation in ``core``, which works on locators so
    that the same rule runs over a live observation and over a record read back
    from disk.
    """
    if not isinstance(observation, LicenseObservation):
        raise ThirdPartyUsageError("deriving a link needs a recorded observation")
    return _derive_identity_link_from_locators(
        tuple(item.locator for item in observation.evidence), identity
    )


def bind_component(
    *,
    observation: LicenseObservation,
    assessment: ResearchUseAssessment,
    upstream_identity: UpstreamIdentity,
    publisher_attestation: PublisherAttestation | None = None,
) -> BoundUpstreamComponent:
    """Tie the three together, or refuse a set that is not one component.

    The basis is **derived**, never argued. Where an evidence locator is the
    upstream's own locator, or sits inside it, or carries its exact commit, the
    two documents prove their own pairing and no attestation is accepted —
    there would be nothing for it to add and no way to tell a true one from a
    decorative one. Where they prove nothing, a :class:`PublisherAttestation`
    is required, and it is a document with a closed method vocabulary and a
    mandatory basis rather than the ``bool`` that used to sit here. A caller
    cannot declare a link derived, and cannot publish an assertion that says
    nothing.

    Raises:
        ThirdPartyUsageError: the three do not describe one component, or the
            attestation does not answer the basis it was filed under.
    """
    return BoundUpstreamComponent(
        component_kind=getattr(observation, "component_kind", None),
        observation=observation,
        assessment=assessment,
        upstream_identity=upstream_identity,
        identity_link_basis=derive_identity_link(observation, upstream_identity),
        publisher_attestation=publisher_attestation,
    )


def build_usage_record(
    *,
    record_id: str,
    component: BoundUpstreamComponent,
    redistribution_decision: RedistributionDecision,
    redistribution_basis: str,
    storage_class: ArtifactStorageClass | None = None,
    notes: Iterable[str] = (),
) -> ThirdPartyUsageRecord:
    """One component's whole third-party position, bound and fingerprinted.

    Takes a :class:`BoundUpstreamComponent` rather than an observation, an
    assessment and an identity. That is the whole point: the three used to
    arrive separately and only two of them were checked against each other, so
    there was a legal call that produced a record about upstream Y wearing
    upstream X's licence. There is now no such call to make.

    Raises:
        ThirdPartyUsageError: the argument is not a bound component, or the
            assessment inside it was taken under a purpose this repository has
            not frozen.
    """
    if not isinstance(component, BoundUpstreamComponent):
        raise ThirdPartyUsageError(
            f"{record_id}: a usage record is built from a BoundUpstreamComponent. "
            "Call bind_component first; passing the observation, the assessment "
            "and the identity separately is the hole this signature closed"
        )
    observation = component.observation
    assessment = component.assessment

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
        schema_version=THIRD_PARTY_USAGE_SCHEMA_VERSION,
        record_id=record_id,
        purpose=ProjectPurpose.PERSONAL_EDUCATIONAL_RESEARCH,
        purpose_fingerprint=declaration.purpose_fingerprint,
        component_kind=observation.component_kind,
        upstream_identity=component.upstream_identity,
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
        upstream_identity_fingerprint=component.upstream_identity_fingerprint,
        identity_link_basis=component.identity_link_basis,
        publisher_attestation=component.publisher_attestation,
        binding_fingerprint=component.binding_fingerprint,
    )


def require_attestation_references_are_tracked(
    repository_root: Path, attestation: PublisherAttestation
) -> None:
    """Prove every pinned document is a real blob at the commit it names.

    Not ``Path.is_file()``. A file that exists in *this* checkout says nothing
    about what the attestation was made against: the working copy can be dirty,
    the file can be untracked, and the content can differ from the revision the
    reference names. ``git cat-file -e <commit>:<path>`` asks the only question
    that survives a fresh clone --- were these bytes committed at that
    revision.

    Lives here rather than in ``core`` because ``core`` must construct on a
    machine with no repository at all; the model states the pairs, and this
    resolves them.

    Raises:
        ThirdPartyUsageError: a reference names a blob that is not there.
    """
    root = Path(repository_root)
    for commit, path in attestation_reference_paths(attestation):
        # Two questions, and ``cat-file -e`` answers neither on its own: it
        # reports that *an object* exists, so a directory passes as happily as a
        # file and a tag would pass as a commit. Ask for the type instead.
        for revision, wanted, what in (
            (commit, "commit", "a commit"),
            (f"{commit}:{path}", "blob", "a file"),
        ):
            try:
                completed = subprocess.run(
                    ["git", "cat-file", "-t", revision],
                    cwd=str(root),
                    capture_output=True,
                    text=True,
                    check=False,
                )
            except OSError as exc:  # pragma: no cover - Git is present in CI
                raise ThirdPartyUsageError(
                    f"cannot check {path!r} at {commit[:12]}...: {exc}"
                ) from exc
            if completed.returncode != 0:
                raise ThirdPartyUsageError(
                    f"this attestation rests on {path!r} at commit "
                    f"{commit[:12]}..., and {what} is not in this repository. A "
                    "reference nobody can resolve is a reference to nothing"
                )
            found = completed.stdout.strip()
            if found != wanted:
                raise ThirdPartyUsageError(
                    f"this attestation rests on {path!r} at commit "
                    f"{commit[:12]}..., and that names a {found} where {what} "
                    f"was required. A {found} is not something a reader can open"
                )


def require_bound_component_references_are_tracked(
    repository_root: Path, component: BoundUpstreamComponent
) -> None:
    """The same check, for whichever attestation a bound component carries."""
    if component.publisher_attestation is not None:
        require_attestation_references_are_tracked(
            repository_root, component.publisher_attestation
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
    unresolved = tuple(
        record
        for record in manifest.records
        if not record_has_execution_eligible_identity(record)
    )
    if unresolved:
        detail = ", ".join(
            f"{record.record_id} ({record.upstream_identity.upstream_name})"
            for record in unresolved
        )
        raise ThirdPartyUsageError(
            f"{manifest.manifest_id}: these components have no established "
            f"upstream identity and were never acquired: {detail}. A licence "
            "position is about some bytes, and there are no bytes here"
        )

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
