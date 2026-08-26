"""A licence observation must be tied to the upstream it was taken over.

``ThirdPartyUsageRecord`` carries an observation, an assessment and an
``UpstreamIdentity``. Two of the three used to be checked against each other and
the identity was not, so a record could describe upstream X's licence beside
upstream Y's bytes and read as entirely ordinary.

:func:`fpbench.third_party.manifest.bind_component` is where that is refused,
and :func:`~fpbench.third_party.manifest.build_usage_record` now takes only its
output — there is no argument list that accepts the three parts separately.

**Three states, not two.** The basis is derived, never declared:

* the documents prove their own pairing (a licence read at the upstream's own
  locator, or at its exact commit);
* they do not, but the artifact was acquired, so the publisher can say what
  they checked — a :class:`PublisherAttestation` is required;
* they do not and nothing was acquired — an unresolved, documentation-only
  identity, which carries no attestation because there is no act to attest to,
  and which may never open execution.

The exemption list below is the last thing left of the old shape and goes with
the call-site migration.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from fpbench.core.third_party_errors import ThirdPartyUsageError
from fpbench.core.third_party_models import (
    AttestationMethod,
    AttestationReference,
    AttestationReferenceRole,
    IdentityLinkBasis,
    LicenseEvidence,
    LicenseObservation,
    LicenseObservationStatus,
    PublisherAttestation,
    ResearchUseBlocker,
    ThirdPartyComponentKind,
    UpstreamIdentity,
    upstream_identity_fingerprint,
)
from fpbench.provenance.upstream_binding import bind_component

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

def _call_sites() -> set[str]:
    """Every module that calls ``build_usage_record``."""
    found: set[str] = set()
    for path in sorted((REPOSITORY_ROOT / "src").rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:  # pragma: no cover - the tree compiles in CI
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            target = node.func
            name = getattr(target, "id", None) or getattr(target, "attr", None)
            if name != "build_usage_record":
                continue
            passed = {kw.arg for kw in node.keywords}
            if passed & {"observation", "assessment", "upstream_identity"}:
                found.add(path.relative_to(REPOSITORY_ROOT).as_posix())
    return found


def test_no_production_path_builds_a_record_from_unbound_parts() -> None:
    """There is no exemption list any more, and this is why there can be none.

    ``build_usage_record`` takes a ``BoundUpstreamComponent`` and nothing else,
    so a call passing the three loose parts is a TypeError rather than a record
    nobody bound. The scan stays because the signature could be widened again,
    and a widened signature with no caller looks exactly like a safe one.
    """
    unbound = sorted(_call_sites())
    assert not unbound, (
        f"{unbound} build a third-party usage record from unbound parts. Use "
        "fpbench.third_party.manifest.bind_component"
    )


# ------------------------------------------------------------------- fixtures


def _observation_at(
    *locators: str, kind: ThirdPartyComponentKind = ThirdPartyComponentKind.SOURCE_CODE
) -> LicenseObservation:
    return LicenseObservation(
        observation_id="probe_observation",
        component_kind=kind,
        subject="a probe used only by this test",
        status=LicenseObservationStatus.OPEN_SOURCE_PERMISSIVE,
        declared_license_names=("MIT",),
        spdx_identifiers=("MIT",),
        evidence=tuple(
            LicenseEvidence(locator=locator, description="the licence")
            for locator in locators
        ),
        notes=("no real upstream",),
    )


def _identity(
    name: str = "probe/upstream",
    *,
    locator: str | None = None,
    established: bool = True,
    sha256: str | None = None,
    filename: str | None = None,
    size: int | None = None,
    commit: str | None = "a" * 40,
) -> UpstreamIdentity:
    return UpstreamIdentity(
        upstream_name=name,
        upstream_locator=locator or f"https://example.invalid/{name}",
        exact_version="1.0.0",
        upstream_commit=commit,
        artifact_filename=filename,
        artifact_sha256=sha256,
        artifact_size_bytes=size,
        identity_established=established,
    )


def _assessment(observation: LicenseObservation, **kwargs):
    from fpbench.third_party import assess_research_use

    return assess_research_use(
        observation,
        assessment_id="probe_research_use",
        basis="a probe used only by this test",
        **kwargs,
    )


#: Any full-length hex string. Only the tracked-blob gate resolves these
#: against Git; every other test needs the shape of a commit and no more.
PROBE_COMMIT = "0" * 40


def _ref(
    role: AttestationReferenceRole,
    *,
    path: str | None = None,
    commit: str | None = None,
    digest: str | None = None,
) -> AttestationReference:
    if path is not None and commit is None:
        commit = PROBE_COMMIT
    return AttestationReference(role=role, path=path, commit=commit, digest=digest)


def _default_references() -> tuple[AttestationReference, ...]:
    """What ``BUILT_HERE`` needs: a definition, and what it consumed."""
    return (
        _ref(
            AttestationReferenceRole.BUILD_DEFINITION,
            path="integrations/sourceafis-java/pom.xml",
        ),
        _ref(
            AttestationReferenceRole.SOURCE_PIN,
            path="docs/policy/third-party-usage.md",
        ),
    )


def _attestation(
    identity: UpstreamIdentity,
    *,
    method: AttestationMethod = AttestationMethod.BUILT_HERE,
    references: tuple[AttestationReference, ...] | None = None,
    basis: str = "the probe's own build produced it",
) -> PublisherAttestation:
    return PublisherAttestation(
        method=method,
        basis=basis,
        evidence_references=(
            _default_references() if references is None else references
        ),
        asserted_upstream_identity_fingerprint=upstream_identity_fingerprint(identity),
    )


def _bind(observation, identity, *, attestation=None, assessment=None):
    return bind_component(
        observation=observation,
        assessment=assessment or _assessment(observation),
        upstream_identity=identity,
        publisher_attestation=attestation,
    )


# ------------------------------------------------------- the derivation itself


def test_two_identities_have_two_fingerprints() -> None:
    assert upstream_identity_fingerprint(_identity("one")) != (
        upstream_identity_fingerprint(_identity("two"))
    )


def test_a_licence_read_from_the_upstream_itself_derives_its_own_link() -> None:
    identity = _identity()
    bound = _bind(_observation_at(f"{identity.upstream_locator}/LICENSE"), identity)
    assert bound.identity_link_basis is IdentityLinkBasis.EVIDENCE_LOCATOR


def test_the_exact_upstream_locator_counts_as_the_licence_itself() -> None:
    identity = _identity()
    bound = _bind(_observation_at(identity.upstream_locator), identity)
    assert bound.identity_link_basis is IdentityLinkBasis.EVIDENCE_LOCATOR


def test_a_locator_carrying_the_commit_derives_the_link_too() -> None:
    identity = _identity()
    bound = _bind(
        _observation_at(
            f"https://elsewhere.invalid/{identity.upstream_commit}/LICENSE"
        ),
        identity,
    )
    assert bound.identity_link_basis is IdentityLinkBasis.UPSTREAM_COMMIT


def test_a_neighbouring_path_is_not_the_same_upstream() -> None:
    """``.../flx/data`` must not match ``.../flx/database``."""
    identity = _identity(locator="https://example.invalid/flx/data", commit=None)
    bound = _bind(
        _observation_at("https://example.invalid/flx/database/LICENSE"),
        identity,
        attestation=_attestation(identity),
    )
    assert bound.identity_link_basis is IdentityLinkBasis.PUBLISHER_ASSERTION


def test_a_parent_locator_is_not_proof_for_a_component_beneath_it() -> None:
    """A repository-wide LICENSE is evidence about the repository."""
    child = _identity(
        locator="https://example.invalid/vendor/unrelated-component", commit=None
    )
    bound = _bind(
        _observation_at("https://example.invalid/vendor/LICENSE"),
        child,
        attestation=_attestation(child),
    )
    assert bound.identity_link_basis is IdentityLinkBasis.PUBLISHER_ASSERTION


def test_the_surviving_direction_is_still_evidence_inside_the_upstream() -> None:
    identity = _identity(locator="https://example.invalid/vendor")
    bound = _bind(_observation_at("https://example.invalid/vendor/LICENSE"), identity)
    assert bound.identity_link_basis is IdentityLinkBasis.EVIDENCE_LOCATOR


# ---------------------------------------------------------------- the binding


def test_a_bound_component_carries_all_four_fingerprints() -> None:
    observation = _observation_at("https://example.invalid/probe/upstream/LICENSE")
    identity = _identity()
    assessment = _assessment(observation)
    bound = _bind(observation, identity, assessment=assessment)
    assert bound.observation_fingerprint == observation.observation_fingerprint
    assert bound.assessment_fingerprint == assessment.assessment_fingerprint
    assert bound.upstream_identity_fingerprint == upstream_identity_fingerprint(
        identity
    )
    assert len(bound.binding_fingerprint) == 64


def test_swapping_the_identity_changes_the_binding() -> None:
    """The property the record schema could not express."""

    def bound_for(name: str) -> str:
        identity = _identity(name)
        return _bind(
            _observation_at(f"{identity.upstream_locator}/LICENSE"), identity
        ).binding_fingerprint

    assert bound_for("one") != bound_for("two")


def test_the_basis_is_inside_the_binding_fingerprint() -> None:
    """A record cannot be re-signed as derived without the evidence for it."""
    identity = _identity()
    derived = _bind(_observation_at(f"{identity.upstream_locator}/LICENSE"), identity)
    asserted = _bind(
        _observation_at("file:///elsewhere/LICENSE"),
        identity,
        attestation=_attestation(identity),
    )
    assert derived.binding_fingerprint != asserted.binding_fingerprint


def test_an_unproven_pairing_with_no_attestation_is_refused() -> None:
    """The whole hole, in one call: an identity nobody vouched for."""
    identity = _identity()
    with pytest.raises(ThirdPartyUsageError, match="needs a PublisherAttestation"):
        _bind(_observation_at("file:///home/somebody/notes/LICENSE.txt"), identity)


def test_a_derived_link_may_not_carry_an_attestation() -> None:
    """An attestation nothing checks reads like one that was checked."""
    identity = _identity()
    with pytest.raises(ThirdPartyUsageError, match="nothing checks"):
        _bind(
            _observation_at(f"{identity.upstream_locator}/LICENSE"),
            identity,
            attestation=_attestation(identity),
        )


# ------------------------------------- an attestation is about ONE component


def test_an_attestation_does_not_transfer_to_another_upstream() -> None:
    """Gap 2: the same statement filed against two different identities.

    ``asserted_component_identity`` was free text, so one attestation could be
    recycled across components without anything noticing. It is a fingerprint
    now, and it is checked against the identity it is attached to.
    """
    mine = _identity("mine", commit=None)
    theirs = _identity("theirs", commit=None)
    recycled = _attestation(mine)
    with pytest.raises(ThirdPartyUsageError, match="does not transfer"):
        _bind(
            _observation_at("file:///elsewhere/LICENSE"),
            theirs,
            attestation=recycled,
        )


def test_the_asserted_identity_is_inside_the_attestation_fingerprint() -> None:
    mine = _attestation(_identity("mine", commit=None))
    theirs = _attestation(_identity("theirs", commit=None))
    assert mine.attestation_fingerprint != theirs.attestation_fingerprint


def test_an_attestation_with_nothing_behind_it_is_refused() -> None:
    identity = _identity()
    with pytest.raises(ThirdPartyUsageError, match="names what it rests on"):
        PublisherAttestation(
            method=AttestationMethod.BUILT_HERE,
            basis="because I say so",
            evidence_references=(),
            asserted_upstream_identity_fingerprint=upstream_identity_fingerprint(
                identity
            ),
        )


def test_an_attestation_with_an_empty_basis_is_refused() -> None:
    identity = _identity()
    with pytest.raises(Exception):
        PublisherAttestation(
            method=AttestationMethod.BUILT_HERE,
            basis="   ",
            evidence_references=_default_references(),
            asserted_upstream_identity_fingerprint=upstream_identity_fingerprint(
                identity
            ),
        )


# --------------------------------------------- each method needs its own facts


def test_a_pinned_digest_method_needs_a_pinned_digest() -> None:
    """Gap 3: the method read as a claim and checked nothing."""
    identity = _identity(commit=None)
    with pytest.raises(ThirdPartyUsageError, match="pins no digest"):
        _bind(
            _observation_at("file:///elsewhere/LICENSE"),
            identity,
            attestation=_attestation(
                identity,
                method=AttestationMethod.PINNED_ARTIFACT_DIGEST,
                references=(
                    _ref(
                        AttestationReferenceRole.ARTIFACT_DIGEST,
                        digest="e" * 64,
                    ),
                ),
            ),
        )


def test_a_pinned_digest_method_must_name_the_digest_it_rests_on() -> None:
    identity = _identity(
        commit=None, filename="probe.bin", sha256="b" * 64, size=17
    )
    with pytest.raises(ThirdPartyUsageError, match="own digest as an ARTIFACT_DIGEST"):
        _bind(
            _observation_at("file:///elsewhere/LICENSE"),
            identity,
            attestation=_attestation(
                identity,
                method=AttestationMethod.PINNED_ARTIFACT_DIGEST,
                references=(
                    _ref(
                        AttestationReferenceRole.ARTIFACT_DIGEST,
                        digest="e" * 64,
                    ),
                ),
            ),
        )


def test_a_pinned_digest_method_passes_when_the_digest_is_named() -> None:
    identity = _identity(
        commit=None, filename="probe.bin", sha256="b" * 64, size=17
    )
    bound = _bind(
        _observation_at("file:///elsewhere/LICENSE"),
        identity,
        attestation=_attestation(
            identity,
            method=AttestationMethod.PINNED_ARTIFACT_DIGEST,
            references=(
                _ref(AttestationReferenceRole.ARTIFACT_DIGEST, digest="b" * 64),
            ),
        ),
    )
    assert bound.identity_link_basis is IdentityLinkBasis.PUBLISHER_ASSERTION


def test_a_package_coordinate_method_refuses_a_url() -> None:
    identity = _identity(locator="https://example.invalid/not-a-coordinate", commit=None)
    with pytest.raises(ThirdPartyUsageError, match="not one in any scheme"):
        _bind(
            _observation_at("file:///elsewhere/LICENSE"),
            identity,
            attestation=_attestation(
                identity, method=AttestationMethod.PACKAGE_COORDINATE
            ),
        )


@pytest.mark.parametrize(
    "method",
    [
        AttestationMethod.BUILD_ENUMERATION,
        AttestationMethod.BUILT_HERE,
        AttestationMethod.OUT_OF_BAND_DELIVERY,
    ],
)
def test_a_method_resting_on_this_repository_needs_a_file_in_it(
    method: AttestationMethod,
) -> None:
    identity = _identity(commit=None, filename="p.bin", sha256="b" * 64, size=3)
    with pytest.raises(ThirdPartyUsageError):
        _bind(
            _observation_at("file:///elsewhere/LICENSE"),
            identity,
            attestation=_attestation(
                identity,
                method=method,
                references=(
                    _ref(AttestationReferenceRole.ARTIFACT_DIGEST, digest="b" * 64),
                ),
            ),
        )


def test_every_method_declares_a_precondition() -> None:
    """A member added without a rule would be accepted by the ``else`` nobody wrote."""
    from fpbench.core.third_party_models import require_method_has_its_facts

    identity = _identity(
        commit=None, filename="probe.bin", sha256="b" * 64, size=17
    )
    for method in AttestationMethod:
        attestation = _attestation(
            identity,
            method=method,
            references=(
                _ref(AttestationReferenceRole.ARTIFACT_DIGEST, digest="b" * 64),
            ),
        )
        try:
            require_method_has_its_facts(
                upstream_identity=identity, attestation=attestation
            )
        except ThirdPartyUsageError as exc:
            assert "no precondition is declared" not in str(exc), method


# ------------------------------------ the unresolved, documentation-only state


def _unacquired() -> UpstreamIdentity:
    """An upstream named by somebody's README and never fetched."""
    return _identity(
        "never-downloaded",
        locator="google-drive-file:0123456789",
        established=False,
        commit=None,
    )


def _blocked_assessment(observation: LicenseObservation):
    return _assessment(
        observation,
        identity_established=False,
    )


def test_an_unacquired_artifact_derives_the_unresolved_state() -> None:
    identity = _unacquired()
    observation = _observation_at("file:///elsewhere/LICENSE")
    bound = _bind(
        observation,
        identity,
        assessment=_blocked_assessment(observation),
    )
    assert bound.identity_link_basis is IdentityLinkBasis.UNRESOLVED_DOCUMENTATION_ONLY
    assert bound.publisher_attestation is None


def test_the_unresolved_state_may_not_open_execution() -> None:
    assert not IdentityLinkBasis.UNRESOLVED_DOCUMENTATION_ONLY.may_open_execution
    assert IdentityLinkBasis.PUBLISHER_ASSERTION.may_open_execution


def test_an_unresolved_identity_cannot_be_allowed() -> None:
    """Gap 1: documentation-only with a decision that opens execution.

    The old shape made this an attestation method, so an artifact nobody had
    ever downloaded could carry a positive statement, a decision of ``ALLOWED``
    and a manifest that opened execution over it.
    """
    identity = _unacquired()
    observation = _observation_at("file:///elsewhere/LICENSE")
    with pytest.raises(ThirdPartyUsageError, match="the same fact and they disagree"):
        _bind(observation, identity, assessment=_assessment(observation))


def test_an_unresolved_identity_refuses_an_attestation() -> None:
    identity = _unacquired()
    observation = _observation_at("file:///elsewhere/LICENSE")
    with pytest.raises(ThirdPartyUsageError, match="no act to attest to"):
        _bind(
            observation,
            identity,
            assessment=_blocked_assessment(observation),
            attestation=_attestation(identity),
        )


def test_an_unresolved_identity_carrying_measured_bytes_is_refused() -> None:
    """Bytes that were measured were acquired."""
    from fpbench.core.third_party_models import (
        IdentityLinkBasis as Basis,
        require_binding_state_is_coherent,
    )
    from fpbench.core.third_party_models import ResearchUseDecision

    identity = UpstreamIdentity(
        upstream_name="never-downloaded",
        upstream_locator="google-drive-file:0123456789",
        exact_version="1.0.0",
        artifact_filename="weights.pt",
        artifact_sha256="c" * 64,
        artifact_size_bytes=99,
        identity_established=False,
    )
    with pytest.raises(ThirdPartyUsageError, match="digest or a size"):
        require_binding_state_is_coherent(
            upstream_identity=identity,
            identity_link_basis=Basis.UNRESOLVED_DOCUMENTATION_ONLY,
            publisher_attestation=None,
            research_use_decision=ResearchUseDecision.BLOCKED,
            blockers=(ResearchUseBlocker.ARTIFACT_IDENTITY_NOT_ESTABLISHED,),
        )


def test_an_unresolved_identity_blocked_for_another_reason_is_refused() -> None:
    from fpbench.core.third_party_models import (
        IdentityLinkBasis as Basis,
        ResearchUseDecision,
        require_binding_state_is_coherent,
    )

    with pytest.raises(ThirdPartyUsageError, match="the same fact and they disagree"):
        require_binding_state_is_coherent(
            upstream_identity=_unacquired(),
            identity_link_basis=Basis.UNRESOLVED_DOCUMENTATION_ONLY,
            publisher_attestation=None,
            research_use_decision=ResearchUseDecision.BLOCKED,
            blockers=(ResearchUseBlocker.BIOMETRIC_USE_EXPRESSLY_PROHIBITED,),
        )


def test_an_unresolved_component_never_opens_a_manifest() -> None:
    """The other half of the same rule, at the gate a stage actually calls.

    ``bind_component`` refuses the decision, so the record cannot be ALLOWED;
    this is the belt to that pair of braces, and it names the reason rather
    than reporting a generic blocked component.
    """
    from fpbench.core.third_party_models import RedistributionDecision
    from fpbench.third_party.manifest import (
        build_usage_manifest,
        build_usage_record,
        require_manifest_opens_execution,
    )

    identity = _unacquired()
    observation = _observation_at("file:///elsewhere/LICENSE")
    record = build_usage_record(
        record_id="probe_unresolved",
        component=_bind(
            observation,
            identity,
            assessment=_blocked_assessment(observation),
        ),
        redistribution_decision=RedistributionDecision.NOT_ESTABLISHED,
        redistribution_basis="never obtained, so never redistributed",
    )
    assert record.identity_link_basis is (
        IdentityLinkBasis.UNRESOLVED_DOCUMENTATION_ONLY
    )
    manifest = build_usage_manifest(
        manifest_id="probe_manifest",
        subject="a probe used only by this test",
        records=(record,),
    )
    with pytest.raises(ThirdPartyUsageError, match="never acquired"):
        require_manifest_opens_execution(manifest)


# ------------------------------- establishment is orthogonal to the basis


def test_an_unacquired_artifact_with_a_matching_locator_cannot_be_allowed() -> None:
    """The bypass the unrelated-locator case could not reach.

    ``derive_identity_link`` answers the locator and commit questions first, so
    an identity that was never acquired but whose licence happened to sit at
    its own upstream locator derived ``DERIVED_FROM_EVIDENCE_LOCATOR``, missed
    every unresolved-state check, took ``ALLOWED`` and opened a manifest.

    The fix is not to reorder the derivation --- the link really is proven, and
    saying otherwise would be a second lie --- but to ask the other question
    too, always.
    """
    identity = _identity(
        "never-downloaded",
        locator="https://example.invalid/vendor",
        established=False,
        commit=None,
    )
    observation = _observation_at("https://example.invalid/vendor/LICENSE")
    with pytest.raises(ThirdPartyUsageError, match="the same fact and they disagree"):
        _bind(observation, identity, assessment=_assessment(observation))


def test_a_proven_link_over_unobtained_bytes_keeps_its_basis_and_stays_shut() -> None:
    """Both answers survive: the pairing is derived, the gate is still closed."""
    from fpbench.core.third_party_models import (
        RedistributionDecision,
        record_may_open_execution,
    )
    from fpbench.third_party.manifest import build_usage_record

    identity = _identity(
        "never-downloaded",
        locator="https://example.invalid/vendor",
        established=False,
        commit=None,
    )
    observation = _observation_at("https://example.invalid/vendor/LICENSE")
    bound = _bind(
        observation, identity, assessment=_blocked_assessment(observation)
    )
    assert bound.identity_link_basis is IdentityLinkBasis.EVIDENCE_LOCATOR
    record = build_usage_record(
        record_id="probe_proven_but_absent",
        component=bound,
        redistribution_decision=RedistributionDecision.NOT_ESTABLISHED,
        redistribution_basis="never obtained, so never redistributed",
    )
    assert record.identity_link_basis.may_open_execution
    assert not record_may_open_execution(record)


def test_the_gate_refuses_a_proven_link_over_unobtained_bytes() -> None:
    from fpbench.core.third_party_models import RedistributionDecision
    from fpbench.third_party.manifest import (
        build_usage_manifest,
        build_usage_record,
        require_manifest_opens_execution,
    )

    identity = _identity(
        "never-downloaded",
        locator="https://example.invalid/vendor",
        established=False,
        commit=None,
    )
    observation = _observation_at("https://example.invalid/vendor/LICENSE")
    record = build_usage_record(
        record_id="probe_proven_but_absent",
        component=_bind(
            observation, identity, assessment=_blocked_assessment(observation)
        ),
        redistribution_decision=RedistributionDecision.NOT_ESTABLISHED,
        redistribution_basis="never obtained, so never redistributed",
    )
    manifest = build_usage_manifest(
        manifest_id="probe_manifest",
        subject="a probe used only by this test",
        records=(record,),
    )
    with pytest.raises(ThirdPartyUsageError, match="never acquired"):
        require_manifest_opens_execution(manifest)


# ------------------------------------- the preconditions reject a bare word


@pytest.mark.parametrize(
    "method",
    [
        AttestationMethod.BUILD_ENUMERATION,
        AttestationMethod.BUILT_HERE,
        AttestationMethod.OUT_OF_BAND_DELIVERY,
    ],
)
def test_a_bare_word_is_not_a_repository_reference(
    method: AttestationMethod,
) -> None:
    """``("garbage",)`` satisfied "not a URL" and named nothing.

    Refused one level earlier now: a reference is a role plus a blob, and a
    bare word is not a path this repository could resolve at any revision.
    """
    del method  # refused before any method is consulted
    with pytest.raises(ThirdPartyUsageError, match="not a normalised, relative path"):
        _ref(AttestationReferenceRole.SOURCE_PIN, path="garbage")


def test_a_package_coordinate_must_be_canonical_in_a_known_scheme() -> None:
    """``garbage:thing`` is two words and a colon."""
    identity = _identity(locator="garbage:thing", commit=None)
    with pytest.raises(ThirdPartyUsageError, match="not one in any scheme"):
        _bind(
            _observation_at("file:///elsewhere/LICENSE"),
            identity,
            attestation=_attestation(
                identity, method=AttestationMethod.PACKAGE_COORDINATE
            ),
        )


def test_a_real_maven_coordinate_passes() -> None:
    identity = _identity(locator="com.machinezoo.sourceafis:sourceafis", commit=None)
    bound = _bind(
        _observation_at("file:///elsewhere/LICENSE"),
        identity,
        attestation=_attestation(
            identity, method=AttestationMethod.PACKAGE_COORDINATE
        ),
    )
    assert bound.identity_link_basis is IdentityLinkBasis.PUBLISHER_ASSERTION


def test_out_of_band_delivery_needs_the_bytes_it_delivered() -> None:
    """Nothing can re-fetch it, so the digest is the only identity there is."""
    identity = _identity(commit=None)
    with pytest.raises(ThirdPartyUsageError, match="pins no digest"):
        _bind(
            _observation_at("file:///elsewhere/LICENSE"),
            identity,
            attestation=_attestation(
                identity,
                method=AttestationMethod.OUT_OF_BAND_DELIVERY,
                references=(
                    _ref(
                        AttestationReferenceRole.TERMS_RECORD,
                        path="data/README.md",
                    ),
                ),
            ),
        )


def test_built_here_needs_a_source_pin_and_not_only_a_build_definition() -> None:
    identity = _identity(commit=None)
    with pytest.raises(ThirdPartyUsageError, match="SOURCE_PIN role"):
        _bind(
            _observation_at("file:///elsewhere/LICENSE"),
            identity,
            attestation=_attestation(
                identity,
                method=AttestationMethod.BUILT_HERE,
                references=(
                    _ref(
                        AttestationReferenceRole.BUILD_DEFINITION,
                        path="integrations/sourceafis-java/pom.xml",
                    ),
                ),
            ),
        )


def test_a_traversing_path_is_not_a_repository_reference() -> None:
    with pytest.raises(ThirdPartyUsageError, match="not a normalised, relative path"):
        _ref(AttestationReferenceRole.ENUMERATION, path="../../etc/passwd")


def test_the_blocker_and_the_identity_flag_must_agree_both_ways() -> None:
    """One fact, stated twice. Only one direction used to be checked.

    An assessment blocking on ``ARTIFACT_IDENTITY_NOT_ESTABLISHED`` beside an
    identity claiming ``identity_established=True`` verified with no findings:
    the record said the identity was both settled and not.
    """
    identity = _identity()
    observation = _observation_at("file:///elsewhere/LICENSE")
    with pytest.raises(ThirdPartyUsageError, match="the same fact and they disagree"):
        _bind(
            observation,
            identity,
            assessment=_blocked_assessment(observation),
            attestation=_attestation(identity),
        )


def test_a_record_read_back_with_an_unresolved_identity_may_not_be_allowed() -> None:
    """The path where the blockers are not visible at all.

    ``ThirdPartyUsageRecord`` carries a decision and not the assessment behind
    it, so the symmetric check above cannot run there. What it *can* see is
    that an unestablished identity took a decision that opens execution, and
    that is refused on its own.
    """
    from fpbench.core.third_party_models import (
        IdentityLinkBasis as Basis,
        ResearchUseDecision,
        require_binding_state_is_coherent,
    )

    with pytest.raises(ThirdPartyUsageError, match="cannot be cleared for execution"):
        require_binding_state_is_coherent(
            upstream_identity=_unacquired(),
            identity_link_basis=Basis.UNRESOLVED_DOCUMENTATION_ONLY,
            publisher_attestation=None,
            research_use_decision=ResearchUseDecision.ALLOWED,
            blockers=None,
        )


def test_a_blocked_record_has_an_eligible_identity_and_still_may_not_run() -> None:
    """The two predicates answer two questions and are named for them."""
    from fpbench.core.third_party_models import (
        record_has_execution_eligible_identity,
        record_may_open_execution,
    )
    from fpbench.core.third_party_models import RedistributionDecision
    from fpbench.third_party.manifest import build_usage_record

    identity = _identity()
    observation = LicenseObservation(
        observation_id="probe_observation",
        component_kind=ThirdPartyComponentKind.SOURCE_CODE,
        subject="a probe used only by this test",
        status=LicenseObservationStatus.NO_LICENSE_FOUND,
        declared_license_names=(),
        spdx_identifiers=(),
        evidence=(),
        notes=("no licence was found",),
    )
    record = build_usage_record(
        record_id="probe_blocked",
        component=_bind(
            observation,
            identity,
            attestation=_attestation(identity),
        ),
        redistribution_decision=RedistributionDecision.NOT_ESTABLISHED,
        redistribution_basis="not established",
    )
    assert record.research_use_decision.opens_execution is False
    assert record_has_execution_eligible_identity(record) is True
    assert record_may_open_execution(record) is False


# ---------------------------------------- a pinned document is a real blob

#: A path this repository carries, and the commit its blob sits at. Both are
#: real: the point of the gate below is that it resolves them against Git.
_TRACKED_PATH = "docs/policy/third-party-usage.md"
_TRACKED_COMMIT = "328bae7d09af01a9a20aaf57a096ebb6c42e89e3"
_BUILD_PATH = "integrations/sourceafis-java/pom.xml"
_BUILD_COMMIT = "16073f93587f1a135266849fc90f2a31cccef98c"


def _tracked_attestation(identity: UpstreamIdentity) -> PublisherAttestation:
    return _attestation(
        identity,
        references=(
            _ref(
                AttestationReferenceRole.BUILD_DEFINITION,
                path=_BUILD_PATH,
                commit=_BUILD_COMMIT,
            ),
            _ref(
                AttestationReferenceRole.SOURCE_PIN,
                path=_TRACKED_PATH,
                commit=_TRACKED_COMMIT,
            ),
        ),
    )


def test_a_reference_pinned_at_a_real_commit_resolves() -> None:
    from fpbench.third_party.manifest import (
        require_attestation_references_are_tracked,
    )

    require_attestation_references_are_tracked(
        REPOSITORY_ROOT, _tracked_attestation(_identity(commit=None))
    )


def test_a_reference_pinned_at_a_commit_that_lacks_it_is_refused() -> None:
    """The check a filesystem test cannot make.

    ``docs/policy/third-party-usage.md`` exists in this checkout, so
    ``Path.is_file()`` would pass here regardless. What matters is whether the
    blob was committed at the revision the reference names, because that is the
    only form that survives a fresh clone --- and the empty tree's commit does
    not carry it.
    """
    from fpbench.third_party.manifest import (
        require_attestation_references_are_tracked,
    )

    identity = _identity(commit=None)
    attestation = _attestation(
        identity,
        references=(
            _ref(
                AttestationReferenceRole.BUILD_DEFINITION,
                path=_BUILD_PATH,
                commit=_BUILD_COMMIT,
            ),
            _ref(
                AttestationReferenceRole.SOURCE_PIN,
                path=_TRACKED_PATH,
                commit="0" * 40,
            ),
        ),
    )
    with pytest.raises(ThirdPartyUsageError, match="not in this repository"):
        require_attestation_references_are_tracked(REPOSITORY_ROOT, attestation)


def test_a_path_that_was_never_committed_is_refused() -> None:
    from fpbench.third_party.manifest import (
        require_attestation_references_are_tracked,
    )

    identity = _identity(commit=None)
    attestation = _attestation(
        identity,
        references=(
            _ref(
                AttestationReferenceRole.BUILD_DEFINITION,
                path=_BUILD_PATH,
                commit=_BUILD_COMMIT,
            ),
            _ref(
                AttestationReferenceRole.SOURCE_PIN,
                path="docs/policy/no-such-document.md",
                commit=_TRACKED_COMMIT,
            ),
        ),
    )
    with pytest.raises(ThirdPartyUsageError, match="not in this repository"):
        require_attestation_references_are_tracked(REPOSITORY_ROOT, attestation)


def test_a_digest_reference_needs_no_commit() -> None:
    """Bytes identify themselves; asking Git about them would be nonsense."""
    with pytest.raises(ThirdPartyUsageError, match="needs no commit"):
        AttestationReference(
            role=AttestationReferenceRole.ARTIFACT_DIGEST,
            digest="a" * 64,
            commit=PROBE_COMMIT,
        )


def test_a_reference_is_a_path_or_a_digest_and_not_both() -> None:
    with pytest.raises(ThirdPartyUsageError, match="both"):
        AttestationReference(
            role=AttestationReferenceRole.SOURCE_PIN,
            path=_TRACKED_PATH,
            commit=_TRACKED_COMMIT,
            digest="a" * 64,
        )
    with pytest.raises(ThirdPartyUsageError, match="neither"):
        AttestationReference(role=AttestationReferenceRole.SOURCE_PIN)


def test_a_path_needs_a_full_commit_and_not_a_short_one() -> None:
    with pytest.raises(ThirdPartyUsageError, match="full 40-character commit"):
        AttestationReference(
            role=AttestationReferenceRole.SOURCE_PIN,
            path=_TRACKED_PATH,
            commit=_TRACKED_COMMIT[:12],
        )


def test_a_document_role_cannot_be_played_by_a_digest() -> None:
    """A build definition is a file somebody can open; bytes are not.

    ``SOURCE_PIN`` is deliberately exempt: what a local build consumed is often
    an artifact rather than a document, and a sealed archive's digest pins it
    better than any file here could.
    """
    AttestationReference(role=AttestationReferenceRole.SOURCE_PIN, digest="a" * 64)
    for role in (
        AttestationReferenceRole.BUILD_DEFINITION,
        AttestationReferenceRole.ENUMERATION,
        AttestationReferenceRole.TERMS_RECORD,
    ):
        with pytest.raises(ThirdPartyUsageError, match="role for a file"):
            AttestationReference(role=role, digest="a" * 64)
    with pytest.raises(ThirdPartyUsageError, match="role for bytes"):
        AttestationReference(
            role=AttestationReferenceRole.ARTIFACT_DIGEST,
            path=_TRACKED_PATH,
            commit=_TRACKED_COMMIT,
        )


def test_the_role_is_inside_the_attestation_fingerprint() -> None:
    """Two paths with their roles swapped are a different statement."""
    identity = _identity(commit=None)
    one = _attestation(
        identity,
        references=(
            _ref(AttestationReferenceRole.BUILD_DEFINITION, path=_BUILD_PATH),
            _ref(AttestationReferenceRole.SOURCE_PIN, path=_TRACKED_PATH),
        ),
    )
    other = _attestation(
        identity,
        references=(
            _ref(AttestationReferenceRole.BUILD_DEFINITION, path=_TRACKED_PATH),
            _ref(AttestationReferenceRole.SOURCE_PIN, path=_BUILD_PATH),
        ),
    )
    assert one.attestation_fingerprint != other.attestation_fingerprint
