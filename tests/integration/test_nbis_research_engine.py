"""NBIS driven to ``RESEARCH_READY`` by the engine stage 7A extracted.

The claim stage 7B has to make good on is that the second algorithm needs an
adapter, a validator, some configuration and some tests — and *not* a second
runner, a second store, a second result schema or a second evidence chain
(spec section 49).

So the whole chain runs here: prepare, execute, finalize, inspect, over a small
synthetic delivery of real 500 ppi greyscale rasters, through the same
``SingleJobRunner``, the same ``ResultStore``, the same ``ResultSetStore``, the
same receipt and the same finalization mechanism the two SourceAFIS runs used.
Nothing in ``fpbench.execution`` or
``fpbench.experiments.algorithm_research`` changes to accommodate it.

**No biometric conclusion follows from anything here.** The images are synthetic
warped ridges and the tools underneath are stand-ins that hash bytes; what is
being tested is the plumbing. The same chain against a real certified NBIS build
is in ``test_nbis_upstream.py``.

Two variants, because a stand-in cannot be both correctly named and runnable
everywhere. The first drives the real ``NbisAdapter`` and the real NBIS
validator through the engine, and runs anywhere. The second additionally uses
the real ``nbis_research_integration``, which looks for ``bin/mindtct`` by that
exact name, and therefore needs a platform where a file called ``mindtct`` can be
executed.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from fpbench.adapters.nbis.adapter import ADAPTER_ID, ALGORITHM_ID
from fpbench.adapters.nbis.config import (
    BOZORTH3_ROLE,
    BUILD_MANIFEST_ROLE,
    MINDTCT_ROLE,
    RUNTIME_ASSET_ROLES,
)
from fpbench.core.enums import ResearchRunStatus
from fpbench.core.serialization import to_plain
from fpbench.experiments.algorithm_research import (
    execute_algorithm_research_run,
    finalize_algorithm_research_run,
    inspect_algorithm_research_experiment,
    prepare_algorithm_research_run,
)
from fpbench.experiments.nbis_research import nbis_research_integration
from fpbench.experiments.nbis_validation import validate_nbis_result_set
from fpbench.experiments.research_integration import (
    DevelopmentAdapterRuntime,
    ResearchAdapterIntegration,
)
from fpbench.storage.result_store import ResultStore
from engineworld import build_engine_world, git_available
from nbisworld import (
    build_stand_in,
    certify_host,
    identity_preparer,
    ridge_payload,
    sealed_repository,
)

pytestmark = [
    pytest.mark.nbis_contract,
    pytest.mark.adapter_contract,
    pytest.mark.skipif(not git_available(), reason="git is not installed"),
]

#: Enough comparisons to exercise all four protocol stages and both SELF stages,
#: and few enough to run in a CI job with three subprocesses per comparison.
SUBJECT_COUNT = 1


def nbis_validator(context):
    return validate_nbis_result_set(
        run=context.run,
        plan=context.plan,
        pairs=context.pairs,
        images=context.images,
        result_store=context.result_store,
        runtime_reference=context.runtime_reference,
        preparation=context.preparation,
    )


def adapter_only_integration(build) -> ResearchAdapterIntegration:
    """The real adapter and the real validator, with the build already chosen.

    Everything the NBIS integration does except resolving ``bin/mindtct`` by
    name, which is the one part a stand-in cannot satisfy on every platform.
    """

    def development(repository_root, algorithm_config, overrides):
        return DevelopmentAdapterRuntime(
            adapter=build.adapter(), assets=dict(build.assets())
        )

    def delegate(repository_root, algorithm_config, bundle, asset_paths, software):
        from fpbench.adapters.nbis.adapter import NbisAdapter
        from fpbench.adapters.nbis.config import NbisConfig

        return NbisAdapter(
            NbisConfig(
                mindtct_executable=Path(asset_paths[MINDTCT_ROLE]),
                bozorth3_executable=Path(asset_paths[BOZORTH3_ROLE]),
                build_manifest=Path(asset_paths[BUILD_MANIFEST_ROLE]),
                research_mode=True,
            )
        )

    return ResearchAdapterIntegration(
        integration_id="nbis_stand_in_research_v1",
        adapter_id=ADAPTER_ID,
        runtime_asset_roles=RUNTIME_ASSET_ROLES,
        primary_runtime_asset_role=MINDTCT_ROLE,
        create_development_runtime=development,
        create_research_delegate=delegate,
        validate_result_set=nbis_validator,
    )


@pytest.fixture(scope="module")
def world(tmp_path_factory, monkeymodule):
    root = tmp_path_factory.mktemp("nbis-engine")
    certify_host(monkeymodule)
    build = build_stand_in(root / "nbis-build")
    engine = build_engine_world(
        root,
        subject_count=SUBJECT_COUNT,
        experiment_id="nbis_engine_smoke_v1",
        payload_factory=ridge_payload,
    )
    return {"build": build, "engine": engine}


@pytest.fixture(scope="module")
def monkeymodule():
    from _pytest.monkeypatch import MonkeyPatch

    patch = MonkeyPatch()
    yield patch
    patch.undo()


@pytest.fixture(scope="module")
def finished(world):
    """prepare, execute, finalize — the whole chain, through the engine."""
    engine = world["engine"]
    shared = {
        "spec": engine.spec,
        "integration": adapter_only_integration(world["build"]),
        "preparer_factory": identity_preparer,
        "workspace": engine.workspace,
        "dataset_root": engine.dataset_root,
        "repository_root": engine.repository_root,
    }
    prepared = prepare_algorithm_research_run(**shared)
    summary = execute_algorithm_research_run(**shared)
    receipt = finalize_algorithm_research_run(**shared)
    return {"prepared": prepared, "summary": summary, "receipt": receipt, **shared}


# ------------------------------------------------------------------ the chain


def test_every_planned_comparison_ran(finished, world):
    summary = finished["summary"]
    assert summary.newly_executed_jobs == world["engine"].expected_jobs
    assert summary.remaining_jobs == 0


def test_the_run_reaches_research_ready(finished):
    state = inspect_algorithm_research_experiment(
        spec=finished["spec"],
        integration=finished["integration"],
        preparer_factory=identity_preparer,
        workspace=finished["workspace"],
        dataset_root=finished["dataset_root"],
        repository_root=finished["repository_root"],
    )
    assert state.status is ResearchRunStatus.RESEARCH_READY, list(state.issues)


def test_the_engine_used_the_route_it_was_given(finished):
    descriptor = finished["prepared"].run.algorithm
    assert descriptor.algorithm_id == ALGORITHM_ID
    assert descriptor.adapter_id == ADAPTER_ID
    assert descriptor.implementation_version == "5.0.0"


def test_all_three_runtime_files_are_pinned(finished):
    prepared = finished["prepared"]
    assert {asset.role for asset in prepared.bundle.assets} == set(RUNTIME_ASSET_ROLES)
    assert set(prepared.runtime_reference.asset_sha256s) == set(RUNTIME_ASSET_ROLES)


def test_the_receipt_names_every_runtime_asset_and_the_validation(finished):
    receipt = finished["receipt"]
    prepared = finished["prepared"]
    assert dict(receipt.runtime_asset_sha256s) == dict(
        prepared.runtime_reference.asset_sha256s
    )
    assert receipt.algorithm_validation_fingerprint
    assert receipt.stored_results == prepared.plan.total_jobs


def test_the_evidence_carries_no_first_algorithm_vocabulary(finished, world):
    """Section 49: the generic receipt says nothing about SourceAFIS."""
    receipt = finished["receipt"]
    marker = ResultStore(world["engine"].workspace).read_research_finalization(
        receipt.run_id
    )
    rendered = json.dumps(
        {"receipt": to_plain(receipt), "marker": to_plain(marker)}, sort_keys=True
    ).lower()
    for forbidden in ("sourceafis", "bridge", "jar"):
        assert forbidden not in rendered
    for forbidden in ("threshold", "minutiae"):
        assert forbidden not in rendered
    assert marker.algorithm_validation_fingerprint


def test_the_stored_results_record_the_two_stage_facts(finished):
    prepared = finished["prepared"]
    record = prepared.result_store.read_raw_result(
        prepared.run.run_id, prepared.plan.jobs[0].job.job_id
    )
    assert record.adapter_metadata["pipeline"] == ALGORITHM_ID
    assert record.adapter_metadata["extraction_count"] == "2"
    assert record.adapter_metadata["template_cache"] == "disabled"
    assert record.adapter_metadata["template_persistence"] == "disabled"
    assert record.adapter_metadata["effective_ppi"] == "500"
    assert set(record.timings.adapter_components_ms) == {
        "input_staging",
        "left_extraction",
        "right_extraction",
        "matching",
        "cleanup",
    }


def test_no_result_carries_an_artifact(finished):
    prepared = finished["prepared"]
    for planned in prepared.plan.jobs:
        record = prepared.result_store.read_raw_result(
            prepared.run.run_id, planned.job.job_id
        )
        assert record.artifacts == ()


def test_the_workspace_holds_no_intermediate_after_the_run(finished, world):
    """Section 32, at the scale the runner actually leaves directories at."""
    workspace = Path(world["engine"].workspace)
    leftovers = [
        path.name
        for path in (workspace / "work").rglob("*")
        if path.is_file()
    ]
    assert leftovers == []
    published = [
        path.name
        for path in (workspace / "artifacts").rglob("*")
        if path.is_file()
    ]
    assert published == []


def test_the_runner_signature_did_not_change():
    """Section 52: no core module had to learn that this route has stages."""
    import inspect

    from fpbench.execution.runner import SingleJobRunner

    assert set(inspect.signature(SingleJobRunner.__init__).parameters) == {
        "self",
        "run",
        "adapter",
        "preparer",
        "result_store",
        "dataset_root",
        "image_index",
        "workspace_root",
    }


def test_the_raw_result_schema_did_not_change():
    from fpbench.core.result_models import RESULT_SCHEMA_VERSION

    assert RESULT_SCHEMA_VERSION == "1"


# ------------------------------------------- the integration itself, unmodified


@pytest.mark.skipif(
    os.name == "nt",
    reason="a stand-in cannot be both named 'mindtct' and startable on Windows",
)
def test_the_nbis_integration_itself_drives_the_engine(tmp_path, monkeypatch):
    """The real ``nbis_research_integration``, end to end (spec section 38).

    Everything the variant above skips: resolving ``bin/mindtct`` and
    ``bin/bozorth3`` by name out of a certified build directory, checking the
    manifest against the source lock, the patch series and the build script, and
    rebuilding the adapter pinned to the materialised bundle.
    """
    certify_host(monkeypatch)
    build = build_stand_in(tmp_path / "nbis-build", real_names=True)
    engine = build_engine_world(
        tmp_path,
        subject_count=1,
        experiment_id="nbis_integration_smoke_v1",
        payload_factory=ridge_payload,
        prepare_repository=lambda root: sealed_repository(root, build.manifest()),
    )
    shared = {
        "spec": engine.spec,
        "integration": nbis_research_integration(),
        "preparer_factory": identity_preparer,
        "workspace": engine.workspace,
        "dataset_root": engine.dataset_root,
        "repository_root": engine.repository_root,
    }
    prepared = prepare_algorithm_research_run(
        **shared, development_overrides={"build_directory": build.directory}
    )
    summary = execute_algorithm_research_run(**shared)
    finalize_algorithm_research_run(**shared)
    state = inspect_algorithm_research_experiment(**shared)

    assert summary.newly_executed_jobs == engine.expected_jobs
    assert state.status is ResearchRunStatus.RESEARCH_READY, list(state.issues)
    assert {asset.role for asset in prepared.bundle.assets} == set(RUNTIME_ASSET_ROLES)
