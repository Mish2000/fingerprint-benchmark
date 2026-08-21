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
    "upstream_identity_fingerprint",
    "bind_component",
]


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

    That is weaker than a derived proof and stronger than the previous
    arrangement, which was nothing at all. A stage that cannot say ``True`` here
    honestly has not established the pairing and should not publish the record.

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
    if not identity_is_the_observed_component:
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
        binding_fingerprint=stable_hash(
            {
                "schema": "third_party_component_binding_v1",
                "component_kind": observation.component_kind.value,
                "observation": observation.observation_fingerprint,
                "assessment": assessment.assessment_fingerprint,
                "upstream_identity": identity_fingerprint,
            },
            length=64,
        ),
    )
