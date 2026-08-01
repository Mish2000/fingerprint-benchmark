"""The real algorithm, through the generic engine, with nothing hand-wired.

The engine is exercised elsewhere with a matcher that hashes digests and with a
two-executable fixture. Neither of those has a JVM under it, a 27 MB jar to pin,
a version to interrogate at preflight, or a validator with opinions about
metadata. This file runs the fourth command sequence — prepare, execute,
finalize, inspect — with SourceAFIS itself, through
``sourceafis_research_integration()`` and nothing else.

Forty comparisons over a synthetic SD300-shaped delivery. **The images are not
fingerprints and no biometric claim follows from any score here**: what is being
tested is that the shared orchestration drives a real algorithm to
``RESEARCH_READY`` without knowing anything about it (spec section 62).
"""

from __future__ import annotations

import pytest

from fpbench.adapters.sourceafis_java.adapter import ADAPTER_ID
from fpbench.adapters.sourceafis_java.config import (
    BRIDGE_JAR_ROLE,
    SourceAfisJavaConfig,
)
from fpbench.core.enums import ResearchRunStatus
from fpbench.experiments.algorithm_research import (
    execute_algorithm_research_run,
    finalize_algorithm_research_run,
    inspect_algorithm_research_experiment,
    prepare_algorithm_research_run,
)
from fpbench.experiments.sourceafis_research import sourceafis_research_integration
from fpbench.imaging.identity import IdentityImagePreparer
from engineworld import build_engine_world, git_available
from sourceafis_support import require_bridge

pytestmark = [
    pytest.mark.sourceafis,
    pytest.mark.adapter_contract,
    pytest.mark.skipif(not git_available(), reason="git is not installed"),
]


def identity_preparer(workspace, spec):
    return IdentityImagePreparer()


@pytest.fixture(scope="module")
def finished(tmp_path_factory):
    require_bridge()
    world = build_engine_world(
        tmp_path_factory.mktemp("engine_sourceafis"),
        subject_count=1,
        experiment_id="sourceafis_engine_smoke_v1",
    )
    shared = {
        "spec": world.spec,
        "integration": sourceafis_research_integration(),
        "preparer_factory": identity_preparer,
        "workspace": world.workspace,
        "dataset_root": world.dataset_root,
        "repository_root": world.repository_root,
    }
    # The engine world is a throwaway repository, so it has no Maven output. The
    # jar is named through the development override — which is exactly what that
    # override exists for, and what a real run uses to pin the exact executable
    # an earlier run used (spec section 13).
    prepared = prepare_algorithm_research_run(
        **shared, development_overrides={"build_jar": SourceAfisJavaConfig().bridge_jar}
    )
    summary = execute_algorithm_research_run(**shared)
    receipt = finalize_algorithm_research_run(**shared)
    state = inspect_algorithm_research_experiment(**shared)
    return {
        "world": world,
        "prepared": prepared,
        "summary": summary,
        "receipt": receipt,
        "state": state,
    }


def test_the_engine_pinned_the_real_jar(finished):
    bundle = finished["prepared"].bundle
    assert bundle.adapter_id == ADAPTER_ID
    assert {asset.role for asset in bundle.assets} == {BRIDGE_JAR_ROLE}
    assert bundle.asset(BRIDGE_JAR_ROLE).size_bytes > 1_000_000


def test_the_run_records_sourceafis_identity(finished):
    descriptor = finished["prepared"].run.algorithm
    assert descriptor.algorithm_id == "sourceafis_java"
    assert descriptor.adapter_id == ADAPTER_ID
    assert descriptor.implementation_version == "3.18.1"


def test_every_planned_comparison_ran_through_a_real_jvm(finished):
    summary = finished["summary"]
    assert summary.newly_executed_jobs == finished["world"].expected_jobs == 40
    assert summary.remaining_jobs == 0


def test_the_sourceafis_validator_was_the_one_that_ran(finished):
    """Results carry the metadata only the real adapter writes."""
    prepared = finished["prepared"]
    record = prepared.result_store.read_raw_result(
        prepared.run.run_id, prepared.plan.jobs[0].job.job_id
    )
    assert record.adapter_metadata["sourceafis_version"] == "3.18.1"
    assert record.adapter_metadata["extraction_policy"] == "independent_both_sides"
    assert record.adapter_metadata["runtime_bundle_id"] == prepared.bundle.bundle_id


def test_the_run_reaches_research_ready(finished):
    state = finished["state"]
    assert state.status is ResearchRunStatus.RESEARCH_READY, list(state.issues)


def test_the_receipt_makes_no_biometric_claim(finished):
    receipt = finished["receipt"]
    assert receipt.stored_results == 40
    assert receipt.blocking_failure_count == 0
    assert receipt.statement
