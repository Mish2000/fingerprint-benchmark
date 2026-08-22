"""Tying a licence observation to the upstream it was actually taken over.

:func:`fpbench.third_party.manifest.build_usage_record` binds the observation to
the assessment by fingerprint and requires both to name one component *kind*. It
does not bind either to the ``UpstreamIdentity`` beside them. Any identity of a
matching kind is accepted, so a record can describe upstream X's licence next to
upstream Y's bytes and read as ordinary.

Nothing here is a subtle failure once it happens: a redistribution decision or a
research-use assessment would be attached to bytes it was never made about.

**Why it lives in ``provenance`` and not in ``third_party``.** Stage 8E's
published boundary requires ``fpbench/third_party/`` to hold exactly the modules
it names, and a module added there is a finding against that stage. This
concern — which artifact is which — is provenance, and ``fpbench.provenance``
already holds the other two answers to it.

**Why this is a new module rather than a stricter ``build_usage_record``.**
``third_party/manifest.py`` is inside Stage 8E's ``_SOURCE_FILES``, and Stage
8E's finalization fingerprint is frozen into Stage 10A, 10B, **11A**, 12A and
13A. Stage 11A's fingerprint is in turn frozen into
``verifinger_java.identity.PIPELINE_METADATA``, which reaches
``algorithm_fingerprint`` and is therefore stored in every one of Stage 11B's
500 raw results. Adding a required argument there does not re-issue five
markers; it invalidates a run that needs the VeriFinger trial re-activated and a
JVM to reproduce.

So the enforcement lives here, every new stage uses it, and
``tests/contract/test_third_party_identity_binding.py`` names the call sites
still on the unbound path — which makes the exemption a list that can only
shrink, rather than a silence.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from fpbench.core.serialization import stable_hash
from fpbench.core.third_party_errors import ThirdPartyUsageError
from fpbench.core.third_party_models import (
    LicenseObservation,
    ResearchUseAssessment,
    ThirdPartyComponentKind,
    UpstreamIdentity,
)

__all__ = [
    "BoundUpstreamComponent",
    "IdentityLinkBasis",
    "derive_identity_link",
    "upstream_identity_fingerprint",
    "bind_component",
]


class IdentityLinkBasis(str, Enum):
    """How the observation was tied to the upstream identity beside it.

    The point of publishing this is that a reader can tell the two apart. A
    record whose licence was read *from the upstream's own locator* proves its
    own pairing; a record whose licence was read from a local evidence file
    beside an artifact fetched from a package index does not, and rests on the
    publisher having checked. Both are legitimate; only one is self-evident, and
    until now the record said nothing about which it was.
    """

    #: An evidence locator is the upstream locator, or sits under it. The
    #: notices were read from the upstream artifact itself.
    EVIDENCE_LOCATOR = "DERIVED_FROM_EVIDENCE_LOCATOR"
    #: An evidence locator carries the upstream's exact commit. The notices were
    #: read at the revision the identity names.
    UPSTREAM_COMMIT = "DERIVED_FROM_UPSTREAM_COMMIT"
    #: Nothing in the two documents links them. The publisher's assertion is all
    #: there is, and the record says so rather than implying more.
    PUBLISHER_ASSERTION = "ASSERTED_BY_THE_PUBLISHER"


def _locators(observation: LicenseObservation) -> tuple[str, ...]:
    return tuple(
        str(item.locator).strip()
        for item in observation.evidence
        if str(getattr(item, "locator", "")).strip()
    )


def derive_identity_link(
    observation: LicenseObservation, identity: UpstreamIdentity
) -> IdentityLinkBasis:
    """Read the pairing out of the two documents, where it is there to read.

    Deliberately narrow. It answers "do these two documents *themselves* say
    they are about one component", and returns
    :attr:`IdentityLinkBasis.PUBLISHER_ASSERTION` whenever they do not — which
    is the honest answer for a licence read from a local evidence file beside an
    artifact fetched from a package index. Guessing from a fuzzy name match
    would turn an unproven pairing into a proven-looking one, which is the whole
    failure being addressed.
    """
    if not isinstance(observation, LicenseObservation):
        raise ThirdPartyUsageError("deriving a link needs a recorded observation")
    if not isinstance(identity, UpstreamIdentity):
        raise ThirdPartyUsageError("deriving a link needs an upstream identity")

    locators = _locators(observation)
    upstream = str(identity.upstream_locator or "").strip()
    if upstream:
        for locator in locators:
            if locator == upstream:
                return IdentityLinkBasis.EVIDENCE_LOCATOR
            # A licence file inside the artifact the identity names. The
            # separator matters: ".../flx/data" must not match ".../flx/database".
            if locator.startswith(upstream.rstrip("/") + "/"):
                return IdentityLinkBasis.EVIDENCE_LOCATOR
            if upstream.startswith(locator.rstrip("/") + "/"):
                return IdentityLinkBasis.EVIDENCE_LOCATOR

    commit = str(identity.upstream_commit or "").strip()
    if len(commit) >= 40 and any(commit in locator for locator in locators):
        return IdentityLinkBasis.UPSTREAM_COMMIT

    return IdentityLinkBasis.PUBLISHER_ASSERTION


def upstream_identity_fingerprint(identity: UpstreamIdentity) -> str:
    """A digest of exactly which upstream thing an identity names.

    Derived rather than stored. ``UpstreamIdentity`` travels inside
    ``ThirdPartyUsageRecord``, whose fingerprint is load-bearing in several
    published markers, so a new field on it would change documents describing
    runs nobody re-did. A function computes the same value and touches nothing.
    """
    if not isinstance(identity, UpstreamIdentity):
        raise ThirdPartyUsageError("an upstream identity fingerprint needs one")
    return stable_hash(
        {
            "schema": "third_party_upstream_identity_v1",
            "upstream_name": identity.upstream_name,
            "upstream_locator": identity.upstream_locator,
            "exact_version": identity.exact_version,
            "upstream_commit": identity.upstream_commit,
            "artifact_filename": identity.artifact_filename,
            "artifact_sha256": identity.artifact_sha256,
            "artifact_size_bytes": identity.artifact_size_bytes,
            "identity_established": identity.identity_established,
        },
        length=64,
    )


@dataclass(frozen=True, slots=True)
class BoundUpstreamComponent:
    """One component: its licence observation, its assessment and its identity.

    Constructed by :func:`bind_component` and by nothing else, so the three
    cannot be assembled from different sources and passed on together.
    """

    component_kind: ThirdPartyComponentKind
    observation: LicenseObservation
    assessment: ResearchUseAssessment
    upstream_identity: UpstreamIdentity

    observation_fingerprint: str
    assessment_fingerprint: str
    upstream_identity_fingerprint: str
    binding_fingerprint: str

    #: How the pairing was established. Part of the binding fingerprint, so a
    #: record cannot be re-signed as derived without the evidence that derives
    #: it.
    identity_link_basis: IdentityLinkBasis = IdentityLinkBasis.PUBLISHER_ASSERTION


def bind_component(
    *,
    observation: LicenseObservation,
    assessment: ResearchUseAssessment,
    upstream_identity: UpstreamIdentity,
    identity_is_the_observed_component: bool,
) -> BoundUpstreamComponent:
    """Bind the three, and refuse a set that does not describe one component.

    ``identity_is_the_observed_component`` has no default and is not
    decoration. Nothing in the published schemas links a
    :class:`LicenseObservation` to an :class:`UpstreamIdentity` — the
    observation's ``subject`` is deliberately free prose and the identity's
    ``upstream_name`` is a different string on every real component — so this is
    the caller stating, in one place a reviewer can find, that the notices it
    read were the notices shipped with these bytes.

    Where the pairing *is* derivable, it is derived rather than believed:
    :func:`derive_identity_link` reads it out of the two documents, the result
    is published as :attr:`BoundUpstreamComponent.identity_link_basis`, and a
    caller passing ``False`` over evidence that says otherwise is refused. Where
    it is not derivable — a licence read from a local evidence file beside an
    artifact fetched from a package index — the assertion stands and the record
    says, in a field, that an assertion is what it is.

    That is the honest position: derived where the evidence allows, and visibly
    asserted where it does not. A stage that cannot say ``True`` here honestly
    has not established the pairing and should not publish the record.

    Raises:
        ThirdPartyUsageError: the three do not describe one component.
    """
    if not isinstance(observation, LicenseObservation):
        raise ThirdPartyUsageError("a bound component needs a recorded observation")
    if not isinstance(assessment, ResearchUseAssessment):
        raise ThirdPartyUsageError("a bound component needs a derived assessment")
    if not isinstance(upstream_identity, UpstreamIdentity):
        raise ThirdPartyUsageError("a bound component needs an upstream identity")

    if assessment.observation_fingerprint != observation.observation_fingerprint:
        raise ThirdPartyUsageError(
            f"the assessment was taken over observation "
            f"{assessment.observation_fingerprint[:12]}... and the observation "
            f"offered is {observation.observation_fingerprint[:12]}..."
        )
    if assessment.component_kind is not observation.component_kind:
        raise ThirdPartyUsageError(
            f"the observation is about a {observation.component_kind.value} and "
            f"the assessment about a {assessment.component_kind.value}"
        )
    if type(identity_is_the_observed_component) is not bool:
        raise ThirdPartyUsageError(
            "identity_is_the_observed_component must be an exact bool"
        )
    basis = derive_identity_link(observation, upstream_identity)
    if not identity_is_the_observed_component:
        if basis is not IdentityLinkBasis.PUBLISHER_ASSERTION:
            raise ThirdPartyUsageError(
                f"the caller denies that {upstream_identity.upstream_name!r} is "
                f"the component observation {observation.observation_id!r} was "
                f"taken over, and the two documents say otherwise ({basis.value}). "
                "One of them is wrong, and it is not for this function to pick"
            )
        raise ThirdPartyUsageError(
            f"the caller does not assert that {upstream_identity.upstream_name!r} "
            f"is the component observation {observation.observation_id!r} was "
            "taken over. An unbound pairing is what this type exists to stop"
        )

    identity_fingerprint = upstream_identity_fingerprint(upstream_identity)
    return BoundUpstreamComponent(
        component_kind=observation.component_kind,
        observation=observation,
        assessment=assessment,
        upstream_identity=upstream_identity,
        observation_fingerprint=observation.observation_fingerprint,
        assessment_fingerprint=assessment.assessment_fingerprint,
        upstream_identity_fingerprint=identity_fingerprint,
        identity_link_basis=basis,
        binding_fingerprint=stable_hash(
            {
                "schema": "third_party_component_binding_v2",
                "component_kind": observation.component_kind.value,
                "observation": observation.observation_fingerprint,
                "assessment": assessment.assessment_fingerprint,
                "upstream_identity": identity_fingerprint,
                "identity_link_basis": basis.value,
            },
            length=64,
        ),
    )
