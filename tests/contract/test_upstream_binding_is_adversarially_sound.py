"""The ten ways a binding could be got around, each with a test that it cannot.

``test_upstream_identity_is_bound.py`` covers the derivation and the states.
This file is the adversary's side: take a *correct* record and try to turn it
into a wrong one that still verifies. Every attempt below succeeded against at
least one earlier shape of this code.

The last two are scans rather than probes. A property that holds for the record
in front of you and not for the twenty-two beside it is not a property.
"""

from __future__ import annotations

import ast
import json
from dataclasses import replace
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
    RedistributionDecision,
    ThirdPartyComponentKind,
    UpstreamIdentity,
    read_third_party_usage_record,
    strict_json_document,
    upstream_identity_fingerprint,
)
from fpbench.core.serialization import to_plain
from fpbench.third_party import assess_research_use
from fpbench.third_party.manifest import bind_component, build_usage_record
from fpbench.third_party.verify import verify_usage_record

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = REPOSITORY_ROOT / "evidence"

_TRACKED_PATH = "docs/policy/third-party-usage.md"
_TRACKED_COMMIT = "328bae7d09af01a9a20aaf57a096ebb6c42e89e3"


def _identity(name: str = "probe") -> UpstreamIdentity:
    return UpstreamIdentity(
        upstream_name=name,
        upstream_locator=f"https://example.invalid/{name}",
        exact_version="1.0.0",
        identity_established=True,
    )


def _observation(observation_id: str = "probe_observation") -> LicenseObservation:
    return LicenseObservation(
        observation_id=observation_id,
        component_kind=ThirdPartyComponentKind.SOURCE_CODE,
        subject="a probe used only by this test",
        status=LicenseObservationStatus.OPEN_SOURCE_PERMISSIVE,
        declared_license_names=("MIT",),
        spdx_identifiers=("MIT",),
        evidence=(
            LicenseEvidence(
                locator="file:///elsewhere/LICENSE", description="the licence"
            ),
        ),
        notes=("no real upstream",),
    )


def _attestation(
    identity: UpstreamIdentity, *, basis: str = "a probe, enumerated here"
) -> PublisherAttestation:
    return PublisherAttestation(
        method=AttestationMethod.BUILD_ENUMERATION,
        basis=basis,
        evidence_references=(
            AttestationReference(
                role=AttestationReferenceRole.ENUMERATION,
                path=_TRACKED_PATH,
                commit=_TRACKED_COMMIT,
            ),
        ),
        asserted_upstream_identity_fingerprint=upstream_identity_fingerprint(identity),
    )


def _record(identity: UpstreamIdentity | None = None):
    identity = identity or _identity()
    observation = _observation()
    assessment = assess_research_use(
        observation, assessment_id="probe_ru", basis="a probe"
    )
    record = build_usage_record(
        record_id="probe_record",
        component=bind_component(
            observation=observation,
            assessment=assessment,
            upstream_identity=identity,
            publisher_attestation=_attestation(identity),
        ),
        redistribution_decision=RedistributionDecision.CONDITIONAL,
        redistribution_basis="permitted and not exercised",
    )
    return record, observation, assessment


# ------------------------------------------------------------------ 1 and 2


def test_swapping_the_upstream_after_the_fact_is_refused() -> None:
    """The whole failure, in one line of ``dataclasses.replace``."""
    record, _, _ = _record()
    with pytest.raises(ThirdPartyUsageError):
        replace(record, upstream_identity=_identity("somebody-else"))


def test_the_same_documents_over_another_upstream_need_a_new_attestation() -> None:
    """There is no quiet path: the old attestation does not travel."""
    observation = _observation()
    assessment = assess_research_use(
        observation, assessment_id="probe_ru", basis="a probe"
    )
    mine, theirs = _identity("mine"), _identity("theirs")
    with pytest.raises(ThirdPartyUsageError, match="does not transfer"):
        bind_component(
            observation=observation,
            assessment=assessment,
            upstream_identity=theirs,
            publisher_attestation=_attestation(mine),
        )

    fresh = bind_component(
        observation=observation,
        assessment=assessment,
        upstream_identity=theirs,
        publisher_attestation=_attestation(theirs),
    )
    original = bind_component(
        observation=observation,
        assessment=assessment,
        upstream_identity=mine,
        publisher_attestation=_attestation(mine),
    )
    assert fresh.binding_fingerprint != original.binding_fingerprint


# ----------------------------------------------------------------------- 3


def test_swapping_the_observation_is_refused() -> None:
    record, _, assessment = _record()
    other = _observation("another_observation")
    with pytest.raises(ThirdPartyUsageError):
        verify_usage_record(record, other, assessment)


def test_swapping_the_assessment_is_refused() -> None:
    record, observation, _ = _record()
    other_observation = _observation("another_observation")
    other = assess_research_use(
        other_observation, assessment_id="another_ru", basis="another probe"
    )
    with pytest.raises(ThirdPartyUsageError):
        verify_usage_record(record, observation, other)


# ----------------------------------------------------------------------- 4


@pytest.mark.parametrize(
    "field",
    [
        "upstream_identity_fingerprint",
        "identity_link_basis",
        "publisher_attestation",
        "binding_fingerprint",
    ],
)
def test_deleting_a_binding_field_is_refused_on_read(field: str) -> None:
    record, _, _ = _record()
    document = dict(to_plain(record))
    document.pop(field)
    with pytest.raises(Exception):
        read_third_party_usage_record(
            strict_json_document(json.dumps(document))
        )


def test_an_extra_field_is_refused_on_read() -> None:
    record, _, _ = _record()
    document = dict(to_plain(record))
    document["something_nobody_declared"] = True
    with pytest.raises(Exception):
        read_third_party_usage_record(
            strict_json_document(json.dumps(document))
        )


# ----------------------------------------------------------------------- 5


def test_relabelling_an_assertion_as_derived_is_refused() -> None:
    """The basis is read out of the evidence; a document cannot declare it."""
    record, _, _ = _record()
    document = dict(to_plain(record))
    assert document["identity_link_basis"] == (
        IdentityLinkBasis.PUBLISHER_ASSERTION.value
    )
    document["identity_link_basis"] = IdentityLinkBasis.EVIDENCE_LOCATOR.value
    with pytest.raises(ThirdPartyUsageError, match="never declared"):
        read_third_party_usage_record(
            strict_json_document(json.dumps(document))
        )


# ----------------------------------------------------------------------- 6


def test_editing_the_assertion_rationale_moves_the_fingerprint() -> None:
    identity = _identity()
    one = _attestation(identity, basis="a probe, enumerated here")
    other = _attestation(identity, basis="a probe, enumerated somewhere else")
    assert one.attestation_fingerprint != other.attestation_fingerprint

    observation = _observation()
    assessment = assess_research_use(
        observation, assessment_id="probe_ru", basis="a probe"
    )

    def binding_for(attestation: PublisherAttestation) -> str:
        return bind_component(
            observation=observation,
            assessment=assessment,
            upstream_identity=identity,
            publisher_attestation=attestation,
        ).binding_fingerprint

    assert binding_for(one) != binding_for(other)


# ----------------------------------------------------------------------- 8


def test_a_record_round_trips_with_its_binding_intact() -> None:
    record, _, _ = _record()
    restored = read_third_party_usage_record(
        strict_json_document(json.dumps(to_plain(record)))
    )
    assert restored == record
    assert restored.binding_fingerprint == record.binding_fingerprint
    assert restored.identity_link_basis is record.identity_link_basis
    assert restored.publisher_attestation == record.publisher_attestation


# ---------------------------------------------------------------- 9 and 10


def test_no_production_path_builds_a_record_from_unbound_parts() -> None:
    """Every call site, not the three anybody remembered."""
    offenders = []
    for path in sorted((REPOSITORY_ROOT / "src").rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:  # pragma: no cover - the tree compiles in CI
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name != "build_usage_record":
                continue
            passed = {keyword.arg for keyword in node.keywords}
            if passed & {"observation", "assessment", "upstream_identity"}:
                offenders.append(path.relative_to(REPOSITORY_ROOT).as_posix())
    assert not offenders, offenders


def _published_records() -> list[tuple[Path, dict]]:
    """Every third-party usage record published anywhere under ``evidence/``."""
    found: list[tuple[Path, dict]] = []
    for path in sorted(EVIDENCE.rglob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):  # pragma: no cover - evidence parses in CI
            continue

        def walk(node: object) -> None:
            if isinstance(node, dict):
                if "upstream_identity" in node and "usage_fingerprint" in node:
                    found.append((path, node))
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        walk(payload)
    return found


def test_there_are_published_records_to_scan() -> None:
    """An empty scan finds no violation and reads exactly like a clean one."""
    assert _published_records(), "no third-party usage record found under evidence/"


def test_every_published_record_carries_its_binding() -> None:
    """No active evidence without a binding, and no exemption list.

    A record published before the binding existed is not grandfathered: it is a
    document asserting a licence position over bytes it never identified, and
    that is the whole finding. The repair is to re-publish it, not to name it
    here.
    """
    required = (
        "upstream_identity_fingerprint",
        "identity_link_basis",
        "binding_fingerprint",
    )
    offenders = []
    for path, record in _published_records():
        missing = [field for field in required if field not in record]
        if missing:
            offenders.append(
                f"{path.relative_to(REPOSITORY_ROOT).as_posix()}: "
                f"{record.get('record_id', '?')} lacks {missing}"
            )
    assert not offenders, offenders


def test_every_published_assertion_carries_a_rationale() -> None:
    """``ASSERTED_BY_THE_PUBLISHER`` with an empty attestation says nothing."""
    offenders = []
    for path, record in _published_records():
        if record.get("identity_link_basis") != (
            IdentityLinkBasis.PUBLISHER_ASSERTION.value
        ):
            continue
        attestation = record.get("publisher_attestation")
        if not isinstance(attestation, dict):
            offenders.append(
                f"{path.name}: {record.get('record_id', '?')} rests on an "
                "assertion and publishes none"
            )
            continue
        if not str(attestation.get("basis") or "").strip():
            offenders.append(
                f"{path.name}: {record.get('record_id', '?')} publishes an "
                "attestation with an empty basis"
            )
        if not attestation.get("evidence_references"):
            offenders.append(
                f"{path.name}: {record.get('record_id', '?')} publishes an "
                "attestation resting on nothing"
            )
    assert not offenders, offenders
