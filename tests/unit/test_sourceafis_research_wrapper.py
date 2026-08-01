"""The SourceAFIS experiment wrapper configures; it does not orchestrate.

Checked structurally, by imports and by which functions are called — never by
counting lines. A short module that opened result files would still be an
orchestration, and a long one that only assembled configuration would still be a
wrapper (spec section 61).

The property matters because it is the whole of stage 7A's claim: if driving
SourceAFIS still needs a private copy of "materialise, execute, build a result
set, write a receipt", then the second algorithm will need one too.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

pytestmark = pytest.mark.adapter_contract

WRAPPER = "fpbench.experiments.sourceafis_research"
ENGINE = "fpbench.experiments.algorithm_research"

#: The names that actually carry out a research run. A wrapper that calls any of
#: them is running the experiment itself rather than describing it.
ORCHESTRATION_CALLS = (
    "materialize",
    "SequentialRunExecutor",
    "SingleJobRunner",
    "build_result_set",
    "build_run_completion",
    "build_research_receipt",
    "build_research_finalization_marker",
    "verify_research_receipt",
    "inspect_research_run",
    "build_execution_plan",
    "create_run_definition",
    "build_operational_summary",
    "write_operational_summary",
    "write_evidence_copy",
)


def _tree(module_name: str) -> ast.Module:
    module = importlib.import_module(module_name)
    return ast.parse(Path(module.__file__).read_text(encoding="utf-8"))


def _imported_modules(module_name: str) -> set[str]:
    imported: set[str] = set()
    for node in ast.walk(_tree(module_name)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


def _called_names(module_name: str) -> set[str]:
    called: set[str] = set()
    for node in ast.walk(_tree(module_name)):
        if isinstance(node, ast.Call):
            rendered = ast.unparse(node.func)
            called.add(rendered.rsplit(".", 1)[-1])
    return called


# ------------------------------------------------------------ uses the engine


def test_the_wrapper_calls_the_shared_engine():
    assert ENGINE in _imported_modules(WRAPPER)
    called = _called_names(WRAPPER)
    for name in (
        "prepare_algorithm_research_run",
        "execute_algorithm_research_run",
        "inspect_algorithm_research_experiment",
        "finalize_algorithm_research_run",
    ):
        assert name in called, f"the wrapper does not call {name}"


def test_the_wrapper_supplies_an_integration():
    from fpbench.experiments.sourceafis_research import sourceafis_research_integration

    integration = sourceafis_research_integration()
    assert integration.adapter_id == "sourceafis_java_subprocess"
    assert integration.runtime_asset_roles == ("sourceafis_bridge_jar",)
    assert integration.primary_runtime_asset_role == "sourceafis_bridge_jar"
    assert integration.integration_id == "sourceafis_java_research_v1"


def test_two_calls_produce_equal_but_independent_records():
    from fpbench.experiments.sourceafis_research import sourceafis_research_integration

    first = sourceafis_research_integration()
    second = sourceafis_research_integration()
    assert first is not second
    assert first.runtime_asset_roles == second.runtime_asset_roles


# ------------------------------------------------------- orchestrates nothing


@pytest.mark.parametrize("name", ORCHESTRATION_CALLS)
def test_the_wrapper_does_not_orchestrate(name):
    assert name not in _called_names(WRAPPER), (
        f"sourceafis_research calls {name}; that belongs to the shared engine"
    )


def test_the_wrapper_imports_no_store_and_no_executor():
    imported = _imported_modules(WRAPPER)
    forbidden = (
        "fpbench.storage.runtime_bundle_store",
        "fpbench.storage.result_store",
        "fpbench.storage.result_set_store",
        "fpbench.storage.plan_store",
        "fpbench.execution.batch_runner",
        "fpbench.execution.runner",
        "fpbench.execution.planner",
        "fpbench.execution.result_set",
        "fpbench.execution.completion",
    )
    offenders = sorted(set(forbidden) & imported)
    assert offenders == [], f"the wrapper reaches into the engine's layers: {offenders}"


# ----------------------------------------------------------- keeps its names


def test_the_stage_4b_names_still_resolve():
    from fpbench.experiments import sourceafis_research as wrapper

    for name in (
        "ResearchExperimentSpec",
        "PreparedResearchRun",
        "prepare_research_run",
        "execute_research_run",
        "inspect_research_experiment",
        "finalize_research_run",
        "read_run_pointer",
        "capture_research_provenance",
        "timing_summary",
    ):
        assert hasattr(wrapper, name), f"{name} disappeared from the wrapper"


def test_the_spec_aliases_are_the_engines_own_classes():
    """An alias, not a wrapper: a spec built either way is the same object."""
    from fpbench.experiments.algorithm_research import (
        AlgorithmResearchExperimentSpec,
        PreparedAlgorithmResearchRun,
    )
    from fpbench.experiments.sourceafis_research import (
        PreparedResearchRun,
        ResearchExperimentSpec,
    )

    assert ResearchExperimentSpec is AlgorithmResearchExperimentSpec
    assert PreparedResearchRun is PreparedAlgorithmResearchRun


def test_the_two_run_experiments_still_import_the_wrapper():
    """Stage 6A's arrangement is unchanged; only what it delegates to moved."""
    for module in (
        "fpbench.experiments.sourceafis_native_full",
        "fpbench.experiments.sourceafis_canonical500_full",
    ):
        assert WRAPPER in _imported_modules(module)


def test_the_preparation_expectations_alias_survives():
    from fpbench.experiments.prepared_input_validation import PreparedInputExpectations
    from fpbench.experiments.sourceafis_validation import (
        CanonicalPreparationExpectations,
    )

    assert CanonicalPreparationExpectations is PreparedInputExpectations
