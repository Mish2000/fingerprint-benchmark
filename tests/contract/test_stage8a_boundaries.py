"""Structural guards keeping Stage 8A outside datasets, results and adapters."""

from __future__ import annotations

import ast
import dataclasses
import inspect
from pathlib import Path

import pytest

from fpbench.core.modern_matcher_models import CandidateQualificationReport
from fpbench.modern_matchers.base import LearnedFingerprintIntegration
from fpbench.modern_matchers.qualification import QualificationFacts

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "src/fpbench"
STAGE8A_FILES = tuple(sorted((SOURCE_ROOT / "modern_matchers").glob("*.py"))) + (
    SOURCE_ROOT / "core/modern_matcher_models.py",
    SOURCE_ROOT / "storage/modern_matcher_store.py",
)

pytestmark = pytest.mark.stage8a_contract

FORBIDDEN_IMPORTS = (
    "fpbench.datasets",
    "fpbench.protocols",
    "fpbench.execution",
    "fpbench.decisions",
    "fpbench.derivations",
    "fpbench.eligibility",
    "fpbench.evaluation",
    "fpbench.metrics",
    "fpbench.paired",
    "fpbench.cross_algorithm",
    "fpbench.imaging",
    "fpbench.adapters",
    "fpbench.provenance",
    "fpbench.experiments",
    "fpbench.storage.result",
    "fpbench.storage.prepared",
    "fpbench.storage.derivation",
)


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _imports(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_stage8a_imports_no_dataset_result_or_existing_algorithm_layer() -> None:
    offenders: list[str] = []
    for path in STAGE8A_FILES:
        for module in _imports(path):
            if any(module.startswith(prefix) for prefix in FORBIDDEN_IMPORTS):
                offenders.append(f"{path.relative_to(SOURCE_ROOT)} -> {module}")
    assert offenders == []


def test_the_evidence_store_imports_only_core_from_fpbench() -> None:
    path = SOURCE_ROOT / "storage/modern_matcher_store.py"
    offenders = sorted(
        module
        for module in _imports(path)
        if module.startswith("fpbench") and not module.startswith("fpbench.core")
    )
    assert offenders == []


def test_the_learned_contract_is_separate_and_has_exactly_six_operations() -> None:
    methods = {
        name
        for name, value in LearnedFingerprintIntegration.__dict__.items()
        if inspect.isfunction(value) and not name.startswith("__")
    }
    assert methods == {
        "load_runtime",
        "preprocess",
        "extract",
        "compare",
        "validate_runtime",
        "describe_operation",
    }
    compare = inspect.signature(LearnedFingerprintIntegration.compare)
    assert tuple(compare.parameters) == ("self", "left", "right")


def test_qualification_facts_carry_no_pair_label_or_dataset_context() -> None:
    names = {field.name for field in dataclasses.fields(QualificationFacts)}
    forbidden = {
        "dataset",
        "dataset_name",
        "subject",
        "subject_id",
        "label",
        "ground_truth",
        "pair",
        "pair_manifest",
        "result_set",
    }
    assert names.isdisjoint(forbidden)


def test_no_stage8a_source_names_a_forbidden_workspace_or_evidence_tree() -> None:
    forbidden = (
        "workspace/prepared",
        "workspace\\prepared",
        "workspace/results",
        "workspace\\results",
        "workspace/derivations",
        "workspace\\derivations",
        "evidence/sourceafis-",
        "evidence/nbis-",
    )
    offenders: list[str] = []
    for path in STAGE8A_FILES:
        source = path.read_text(encoding="utf-8").lower()
        for token in forbidden:
            if token in source:
                offenders.append(f"{path.name}: {token}")
    assert offenders == []


def test_stage8a_did_not_widen_the_existing_adapter_or_result_contracts() -> None:
    from fpbench.adapters.base import (
        ADAPTER_CONTRACT_VERSION,
        FingerprintAlgorithmAdapter,
    )
    from fpbench.core.result_models import RESULT_SCHEMA_VERSION

    assert ADAPTER_CONTRACT_VERSION == "1"
    assert FingerprintAlgorithmAdapter.__abstractmethods__ == {
        "descriptor",
        "validate_environment",
        "compare",
    }
    assert RESULT_SCHEMA_VERSION == "1"


def test_stage8a_defines_no_persistent_template_or_representation_store() -> None:
    forbidden = {
        "TemplateStore",
        "TemplateManifest",
        "TemplateCache",
        "RepresentationStore",
        "EmbeddingStore",
    }
    offenders: list[str] = []
    for path in STAGE8A_FILES:
        definitions = {
            node.name
            for node in ast.walk(_tree(path))
            if isinstance(node, (ast.ClassDef, ast.FunctionDef))
        }
        for name in sorted(definitions & forbidden):
            offenders.append(f"{path.name}: {name}")
    assert offenders == []
