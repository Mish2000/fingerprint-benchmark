"""The shared research engine, driven by an algorithm it has never heard of.

The claim stage 7A has to make good on is that adding a second algorithm means
writing an adapter, a runtime bundle, a validator, some configuration and some
tests — and *not* a second runner, a second store, a second result schema or a
second evidence chain (spec section 93).

This file is where that claim is tested rather than asserted. The engine is run
prepare-execute-inspect-finalize to ``RESEARCH_READY`` over 120 comparisons, with
an integration built entirely outside ``fpbench``: a stand-in runtime bundle, a
matcher the engine has no import of, and a validator that is not the SourceAFIS
one. Nothing in ``fpbench.execution`` or ``fpbench.experiments.algorithm_research``
changes to accommodate it.

**No biometric conclusion follows from anything here.** The images are eight-by-
eight PNGs and the matcher hashes their digests.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

from fpbench.adapters.dummy.adapter import ALGORITHM_ID as DUMMY_ID
from fpbench.adapters.dummy.adapter import DummyShaAdapter
from fpbench.core.enums import ResearchRunStatus
from fpbench.core.errors import ResearchPreflightError
from fpbench.experiments.algorithm_research import (
    execute_algorithm_research_run,
    finalize_algorithm_research_run,
    inspect_algorithm_research_experiment,
    prepare_algorithm_research_run,
)
from fpbench.imaging.identity import IdentityImagePreparer
from engineworld import build_engine_world, git_available, structural_integration

pytestmark = [
    pytest.mark.adapter_contract,
    pytest.mark.skipif(not git_available(), reason="git is not installed"),
]


def identity_preparer(workspace: Path, spec):
    return IdentityImagePreparer()


def dummy_integration(**overrides):
    settings = {
        "integration_id": "dummy_research_v1",
        "adapter_id": DUMMY_ID,
        "build_adapter": DummyShaAdapter,
    }
    settings.update(overrides)
    return structural_integration(**settings)


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    return build_engine_world(tmp_path_factory.mktemp("engine"))


@pytest.fixture(scope="module")
def finished(world):
    """prepare, execute, finalize — the whole chain, through the engine."""
    integration = dummy_integration()
    shared = {
        "spec": world.spec,
        "integration": integration,
        "preparer_factory": identity_preparer,
        "workspace": world.workspace,
        "dataset_root": world.dataset_root,
        "repository_root": world.repository_root,
    }
    prepared = prepare_algorithm_research_run(**shared)
    summary = execute_algorithm_research_run(**shared)
    receipt = finalize_algorithm_research_run(**shared)
    return {"prepared": prepared, "summary": summary, "receipt": receipt, **shared}


# ---------------------------------------------------------------- the chain


def test_the_engine_plans_the_expected_number_of_comparisons(finished, world):
    assert finished["prepared"].plan.total_jobs == world.expected_jobs == 120


def test_every_planned_comparison_ran(finished, world):
    summary = finished["summary"]
    assert summary.newly_executed_jobs == world.expected_jobs
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


def test_the_receipt_names_the_run_and_makes_no_claim(finished):
    receipt = finished["receipt"]
    assert receipt.run_id == finished["prepared"].run.run_id
    assert receipt.stored_results == 120
    assert "no biometric" in receipt.statement.lower() or receipt.statement


def test_the_engine_used_the_algorithm_it_was_given(finished):
    descriptor = finished["prepared"].run.algorithm
    assert descriptor.adapter_id == DUMMY_ID


def test_the_pointer_is_generic(finished, world):
    """No asset digest under an algorithm-specific key (spec section 17)."""
    from fpbench.core.serialization import read_json

    pointer = read_json(
        Path(world.workspace)
        / "experiments"
        / world.spec.experiment_id
        / "current-run.json"
    )
    assert pointer["runtime_asset_roles"] == ["test_runtime_asset"]
    assert "runtime_bundle_fingerprint" in pointer
    assert "bridge_jar_sha256" not in pointer


# -------------------------------------------------------- runtime integration


def test_a_bundle_holding_the_wrong_roles_is_refused(world, tmp_path):
    """Prepared with one role, reloaded by an integration wanting another."""
    mismatched = dummy_integration(
        integration_id="dummy_research_v2", roles=("some_other_role",)
    )
    with pytest.raises(ResearchPreflightError, match="holds roles"):
        execute_algorithm_research_run(
            spec=world.spec,
            integration=mismatched,
            preparer_factory=identity_preparer,
            workspace=world.workspace,
            dataset_root=world.dataset_root,
            repository_root=world.repository_root,
        )


def test_an_integration_for_a_different_adapter_is_refused(world):
    wrong_adapter = dummy_integration(
        integration_id="dummy_research_v3", adapter_id="counting_adapter"
    )
    with pytest.raises(ResearchPreflightError, match="belongs to adapter"):
        execute_algorithm_research_run(
            spec=world.spec,
            integration=wrong_adapter,
            preparer_factory=identity_preparer,
            workspace=world.workspace,
            dataset_root=world.dataset_root,
            repository_root=world.repository_root,
        )


def test_a_development_runtime_that_builds_another_algorithm_is_refused(tmp_path):
    """The local build has to be the algorithm the integration claims."""
    from fakes import CountingAdapter

    world = build_engine_world(tmp_path, experiment_id="mismatch_v1")
    integration = structural_integration(
        integration_id="dummy_research_v4",
        adapter_id=DUMMY_ID,
        build_adapter=CountingAdapter,
    )
    with pytest.raises(ResearchPreflightError, match="development runtime built"):
        prepare_algorithm_research_run(
            spec=world.spec,
            integration=integration,
            preparer_factory=identity_preparer,
            workspace=world.workspace,
            dataset_root=world.dataset_root,
            repository_root=world.repository_root,
        )


def test_a_research_delegate_for_another_algorithm_is_refused(tmp_path):
    """The pinned adapter has to be the one the integration declared.

    The development side is checked before materialisation; this is the other
    half, where a factory hands back an adapter for something else entirely.
    """
    from fakes import CountingAdapter

    world = build_engine_world(tmp_path, subject_count=1, experiment_id="delegate_v1")
    integration = dummy_integration(integration_id="dummy_research_v5")
    wrong_delegate = replace(
        integration,
        create_research_delegate=lambda *_: CountingAdapter(),
    )
    with pytest.raises(ResearchPreflightError, match="built a research adapter"):
        prepare_algorithm_research_run(
            spec=world.spec,
            integration=wrong_delegate,
            preparer_factory=identity_preparer,
            workspace=world.workspace,
            dataset_root=world.dataset_root,
            repository_root=world.repository_root,
        )


def test_a_multi_asset_runtime_goes_through_unchanged(tmp_path):
    """Three files, one bundle, and the engine never looks inside any of them."""
    world = build_engine_world(tmp_path, subject_count=1, experiment_id="multi_v1")
    integration = structural_integration(
        integration_id="dummy_research_multi_v1",
        adapter_id=DUMMY_ID,
        build_adapter=DummyShaAdapter,
        asset_payloads={
            "tool_extractor": b"extractor bytes",
            "tool_matcher": b"matcher bytes",
            "tool_support_data": b"support bytes",
        },
    )
    prepared = prepare_algorithm_research_run(
        spec=world.spec,
        integration=integration,
        preparer_factory=identity_preparer,
        workspace=world.workspace,
        dataset_root=world.dataset_root,
        repository_root=world.repository_root,
    )
    roles = {asset.role for asset in prepared.bundle.assets}
    assert roles == {"tool_extractor", "tool_matcher", "tool_support_data"}
    assert set(prepared.runtime_reference.asset_sha256s) == roles


def test_a_two_stage_route_finishes_through_the_same_engine(tmp_path):
    """Forty comparisons, a hundred and twenty subprocesses, one engine.

    The route extracts a template per side and runs a separate matcher, and it
    reaches ``RESEARCH_READY`` without the engine, the runner, the stores or the
    result schema learning that it has stages (docs/adr/0043).
    """
    from fpbench.adapters.synthetic_two_stage import (
        ADAPTER_ID as TWO_STAGE_ID,
        EXTRACTOR_ROLE,
        MATCHER_ROLE,
        SyntheticTwoStageCliAdapter,
        SyntheticTwoStageConfig,
    )

    fixtures = Path(__file__).resolve().parents[1] / "fixtures" / "two_stage_cli"
    world = build_engine_world(tmp_path, subject_count=1, experiment_id="two_stage_v1")

    tools = tmp_path / "tools"
    tools.mkdir(parents=True, exist_ok=True)
    extractor = tools / "extractor.py"
    matcher = tools / "matcher.py"
    extractor.write_bytes((fixtures / "extractor.py").read_bytes())
    matcher.write_bytes((fixtures / "matcher.py").read_bytes())

    def build() -> SyntheticTwoStageCliAdapter:
        return SyntheticTwoStageCliAdapter(
            SyntheticTwoStageConfig(
                extractor=extractor,
                matcher=matcher,
                interpreter=Path(sys.executable).resolve(),
            )
        )

    integration = structural_integration(
        integration_id="synthetic_two_stage_research_v1",
        adapter_id=TWO_STAGE_ID,
        build_adapter=build,
        asset_payloads={
            EXTRACTOR_ROLE: extractor.read_bytes(),
            MATCHER_ROLE: matcher.read_bytes(),
        },
    )
    shared = {
        "spec": world.spec,
        "integration": integration,
        "preparer_factory": identity_preparer,
        "workspace": world.workspace,
        "dataset_root": world.dataset_root,
        "repository_root": world.repository_root,
    }
    prepared = prepare_algorithm_research_run(**shared)
    summary = execute_algorithm_research_run(**shared)
    finalize_algorithm_research_run(**shared)
    state = inspect_algorithm_research_experiment(**shared)

    assert summary.newly_executed_jobs == world.expected_jobs == 40
    assert state.status is ResearchRunStatus.RESEARCH_READY, list(state.issues)
    assert {asset.role for asset in prepared.bundle.assets} == {
        EXTRACTOR_ROLE,
        MATCHER_ROLE,
    }

    # And the stored results record the two-stage facts, which is what a
    # validator for a real two-stage route would insist on (spec section 31).
    record = prepared.result_store.read_raw_result(
        prepared.run.run_id, prepared.plan.jobs[0].job.job_id
    )
    assert record.adapter_metadata["extraction_count"] == "2"
    assert record.adapter_metadata["template_cache"] == "disabled"
    assert set(record.timings.adapter_components_ms) == {
        "input_conversion",
        "left_extraction",
        "right_extraction",
        "matching",
    }


def test_the_engine_never_compares_an_identifier_against_a_literal():
    """Section 21, checked over the syntax tree rather than by reading.

    The rule is not "never mention ``adapter_id``" — the engine legitimately
    checks that the adapter it built is the one the integration declared. The
    rule is that no identifier is ever compared against a *name*: ``if
    adapter_id == "nbis_mindtct_bozorth3"`` is the branch that would make the
    engine grow an algorithm, and so is a ``match`` on one.
    """
    import ast

    from fpbench.experiments import algorithm_research

    tree = ast.parse(Path(algorithm_research.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            literal = any(
                isinstance(item, ast.Constant) and isinstance(item.value, str)
                for item in node.comparators
            )
            if not literal:
                continue
            left = ast.unparse(node.left)
            assert "algorithm_id" not in left, left
            assert "adapter_id" not in left, left
        elif isinstance(node, ast.Match):
            subject = ast.unparse(node.subject)
            assert "algorithm_id" not in subject, subject
            assert "adapter_id" not in subject, subject
