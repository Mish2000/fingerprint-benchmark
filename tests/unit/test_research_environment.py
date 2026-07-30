"""Folding provenance into an environment, without losing what was there.

The environment fingerprint is already inside the run fingerprint, so anything
added here changes the run's identity. That is the mechanism by which a commit
becomes part of what a run *is* — and the reason this function is strict about
contradictions rather than tidy about them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fpbench.core.enums import EnvironmentStatus
from fpbench.core.errors import ResearchPreflightError
from fpbench.core.execution_models import EnvironmentReport, environment_fingerprint
from fpbench.provenance.environment import build_research_environment
from fpbench.storage.runtime_bundle_store import RuntimeBundleStore
from runworld import FAKE_ASSET_ROLE, research_provenance, write_fake_asset

ADAPTER = "sourceafis_java_subprocess"


@pytest.fixture
def bundle(tmp_path: Path):
    return RuntimeBundleStore(tmp_path / "workspace").materialize(
        adapter_id=ADAPTER,
        assets={FAKE_ASSET_ROLE: write_fake_asset(tmp_path / "build")},
    )


def _ready(**overrides) -> EnvironmentReport:
    settings = {
        "status": EnvironmentStatus.READY,
        "implementation_version": "3.18.1",
        "runtime": {"java.version": "17.0.9"},
        "dependencies": {"sourceafis": "3.18.1"},
    }
    settings.update(overrides)
    return EnvironmentReport(**settings)


def test_the_adapter_facts_survive(bundle):
    research = build_research_environment(
        adapter_environment=_ready(),
        software=research_provenance(),
        runtime_bundle=bundle,
    )
    assert research.runtime["java.version"] == "17.0.9"
    assert research.dependencies["sourceafis"] == "3.18.1"
    assert research.implementation_version == "3.18.1"


def test_the_source_revision_reaches_the_environment(bundle):
    software = research_provenance()
    research = build_research_environment(
        adapter_environment=_ready(),
        software=software,
        runtime_bundle=bundle,
    )
    assert research.runtime["fpbench.source.kind"] == "git"
    assert research.runtime["fpbench.source.revision"] == software.source_revision
    assert research.runtime["fpbench.source.clean"] == "true"
    assert research.runtime["python.implementation"] == "CPython"


def test_the_runtime_bundle_reaches_the_environment(bundle):
    research = build_research_environment(
        adapter_environment=_ready(),
        software=research_provenance(),
        runtime_bundle=bundle,
    )
    assert research.dependencies["runtime.bundle.id"] == bundle.bundle_id
    assert (
        research.dependencies["runtime.bundle.fingerprint"]
        == bundle.bundle_fingerprint
    )
    asset = bundle.asset(FAKE_ASSET_ROLE)
    assert (
        research.dependencies[f"runtime.asset.{FAKE_ASSET_ROLE}.sha256"]
        == asset.sha256
    )
    assert research.dependencies["pyarrow"]
    assert research.dependencies["fpbench.package"] == "0.1.0"


def test_the_original_report_is_not_modified(bundle):
    original = _ready()
    before = environment_fingerprint(original)
    build_research_environment(
        adapter_environment=original,
        software=research_provenance(),
        runtime_bundle=bundle,
    )
    assert environment_fingerprint(original) == before
    assert "fpbench.source.revision" not in original.runtime


def test_a_different_commit_changes_the_environment_fingerprint(bundle):
    first = build_research_environment(
        adapter_environment=_ready(),
        software=research_provenance(revision="a" * 40),
        runtime_bundle=bundle,
    )
    second = build_research_environment(
        adapter_environment=_ready(),
        software=research_provenance(revision="b" * 40),
        runtime_bundle=bundle,
    )
    assert environment_fingerprint(first) != environment_fingerprint(second)


def test_a_different_bundle_changes_the_environment_fingerprint(tmp_path, bundle):
    other = RuntimeBundleStore(tmp_path / "workspace").materialize(
        adapter_id=ADAPTER,
        assets={
            FAKE_ASSET_ROLE: write_fake_asset(tmp_path / "rebuild", b"other bytes")
        },
    )
    first = build_research_environment(
        adapter_environment=_ready(),
        software=research_provenance(),
        runtime_bundle=bundle,
    )
    second = build_research_environment(
        adapter_environment=_ready(),
        software=research_provenance(),
        runtime_bundle=other,
    )
    assert environment_fingerprint(first) != environment_fingerprint(second)


def test_an_unavailable_adapter_cannot_be_dressed_up_as_research(bundle):
    unavailable = EnvironmentReport(
        status=EnvironmentStatus.UNAVAILABLE,
        implementation_version="3.18.1",
        message="java is not installed",
    )
    with pytest.raises(ResearchPreflightError, match="unavailable"):
        build_research_environment(
            adapter_environment=unavailable,
            software=research_provenance(),
            runtime_bundle=bundle,
        )


def test_a_dirty_tree_cannot_produce_a_research_environment(bundle):
    with pytest.raises(ResearchPreflightError, match="clean source revision"):
        build_research_environment(
            adapter_environment=_ready(),
            software=research_provenance(clean=False),
            runtime_bundle=bundle,
        )


def test_a_contradicting_adapter_value_is_refused_rather_than_overwritten(bundle):
    """An adapter naming a different bundle is a conflict, not a stale field."""
    lying = _ready(dependencies={"runtime.bundle.id": "runtime_deadbeef0000"})
    with pytest.raises(ResearchPreflightError, match="contradiction"):
        build_research_environment(
            adapter_environment=lying,
            software=research_provenance(),
            runtime_bundle=bundle,
        )


def test_an_agreeing_adapter_value_is_accepted(bundle):
    agreeing = _ready(
        dependencies={
            "runtime.bundle.id": bundle.bundle_id,
            "runtime.bundle.fingerprint": bundle.bundle_fingerprint,
        }
    )
    research = build_research_environment(
        adapter_environment=agreeing,
        software=research_provenance(),
        runtime_bundle=bundle,
    )
    assert research.dependencies["runtime.bundle.id"] == bundle.bundle_id
