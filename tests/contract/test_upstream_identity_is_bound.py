"""A licence observation must be tied to the upstream it was taken over.

``build_usage_record`` accepts any ``UpstreamIdentity`` of a matching component
kind, so a record can carry upstream X's licence beside upstream Y's bytes.
:mod:`fpbench.provenance.upstream_binding` is where that is refused.

The list below is the point of this file. Three call sites still build records
on the unbound path, and they cannot move: ``third_party/manifest.py`` is inside
Stage 8E's source fingerprint, Stage 8E's fingerprint is frozen into Stage 11A's
preflight, Stage 11A's is inside ``verifinger_java.identity.PIPELINE_METADATA``,
and that reaches ``algorithm_fingerprint`` — which is stored in all 500 of Stage
11B's raw results. A required argument there invalidates a licensed-SDK run
rather than re-issuing a marker.

So the exemption is a list that can only shrink. A *new* unbound call site fails
this test.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from fpbench.core.third_party_errors import ThirdPartyUsageError
from fpbench.provenance.upstream_binding import (
    bind_component,
    upstream_identity_fingerprint,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

#: Call sites that build a usage record without going through
#: :func:`bind_component`, and are frozen where they are.
_UNBOUND_BY_A_PUBLISHED_RUN = frozenset(
    {
        "src/fpbench/experiments/stage8e_research_only_policy.py",
        "src/fpbench/experiments/stage9a_flare_artifacts.py",
        "src/fpbench/experiments/stage10a_preflight.py",
    }
)


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
            if name == "build_usage_record":
                found.add(path.relative_to(REPOSITORY_ROOT).as_posix())
    return found


def test_no_new_call_site_joins_the_unbound_path() -> None:
    new = sorted(_call_sites() - _UNBOUND_BY_A_PUBLISHED_RUN)
    assert not new, (
        f"{new} build a third-party usage record without binding the upstream "
        "identity to the licence observation. Use "
        "fpbench.provenance.upstream_binding.bind_component; the exemption "
        "list is for call sites frozen by a published run, and it does not grow"
    )


def test_every_exempt_call_site_still_exists() -> None:
    """An exemption for a file that moved is an exemption nobody will remove."""
    missing = sorted(
        relative
        for relative in _UNBOUND_BY_A_PUBLISHED_RUN
        if not (REPOSITORY_ROOT / relative).is_file()
    )
    assert not missing, f"these exempt call sites are gone: {missing}"

    stale = sorted(_UNBOUND_BY_A_PUBLISHED_RUN - _call_sites())
    assert not stale, (
        f"{stale} no longer call build_usage_record — remove them from the "
        "exemption list"
    )


# --------------------------------------------------------------- the binding


def _component(kind_name: str = "SOURCE_CODE"):
    from fpbench.core.third_party_models import (
        LicenseEvidence,
        LicenseObservation,
        LicenseObservationStatus,
        ThirdPartyComponentKind,
    )
    from fpbench.third_party import assess_research_use

    kind = getattr(ThirdPartyComponentKind, kind_name)
    observation = LicenseObservation(
        observation_id="probe_observation",
        component_kind=kind,
        subject="a probe used only by this test",
        status=LicenseObservationStatus.OPEN_SOURCE_PERMISSIVE,
        declared_license_names=("MIT",),
        spdx_identifiers=("MIT",),
        # A status that identifies terms has to name the notice they came
        # from; the model refuses a claim with no reading behind it.
        evidence=(
            LicenseEvidence(
                locator="https://example.invalid/probe/LICENSE",
                description="the probe's licence file",
            ),
        ),
        notes=("no real upstream",),
    )
    return observation


def _identity(name: str = "probe/upstream"):
    from fpbench.core.third_party_models import UpstreamIdentity

    return UpstreamIdentity(
        upstream_name=name,
        upstream_locator=f"https://example.invalid/{name}",
        exact_version="1.0.0",
        upstream_commit="a" * 40,
        identity_established=True,
    )


def test_two_identities_have_two_fingerprints() -> None:
    assert upstream_identity_fingerprint(_identity("one")) != (
        upstream_identity_fingerprint(_identity("two"))
    )


def test_a_caller_that_will_not_assert_the_pairing_is_refused() -> None:
    """The whole hole, in one call: an identity nobody vouched for."""
    from fpbench.third_party import assess_research_use

    observation = _component()
    with pytest.raises(ThirdPartyUsageError, match="does not assert"):
        bind_component(
            observation=observation,
            assessment=assess_research_use(
                observation,
                assessment_id="probe_research_use",
                basis="a probe used only by this test",
            ),
            upstream_identity=_identity(),
            identity_is_the_observed_component=False,
        )


def test_a_bound_component_carries_all_three_fingerprints() -> None:
    from fpbench.third_party import assess_research_use

    observation = _component()
    assessment = assess_research_use(
        observation,
        assessment_id="probe_research_use",
        basis="a probe used only by this test",
    )
    identity = _identity()
    bound = bind_component(
        observation=observation,
        assessment=assessment,
        upstream_identity=identity,
        identity_is_the_observed_component=True,
    )
    assert bound.observation_fingerprint == observation.observation_fingerprint
    assert bound.assessment_fingerprint == assessment.assessment_fingerprint
    assert bound.upstream_identity_fingerprint == upstream_identity_fingerprint(identity)
    assert len(bound.binding_fingerprint) == 64


def test_swapping_the_identity_changes_the_binding() -> None:
    """The property the record schema could not express."""
    from fpbench.third_party import assess_research_use

    observation = _component()
    assessment = assess_research_use(
        observation,
        assessment_id="probe_research_use",
        basis="a probe used only by this test",
    )

    def bound_for(name: str) -> str:
        return bind_component(
            observation=observation,
            assessment=assessment,
            upstream_identity=_identity(name),
            identity_is_the_observed_component=True,
        ).binding_fingerprint

    assert bound_for("one") != bound_for("two")
