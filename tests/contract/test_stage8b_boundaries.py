"""Structural guards keeping Stage 8B out of the dataset, the results and Stage 8A.

Stage 8B is a route from image bytes to a score.  It has no business knowing
what a pair is, which subject an image belongs to, or what the other two
algorithms decided — and the qualification layer must stay importable without
torch so that these tests can run anywhere.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.stage8b_contract

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "src/fpbench"
STAGE8B_FILES = tuple(sorted((SOURCE_ROOT / "flx").rglob("*.py"))) + (
    SOURCE_ROOT / "core/flx_models.py",
    SOURCE_ROOT / "core/flx_errors.py",
)

FORBIDDEN_IMPORTS = (
    "fpbench.datasets",
    "fpbench.protocols",
    "fpbench.decisions",
    "fpbench.derivations",
    "fpbench.eligibility",
    "fpbench.evaluation",
    "fpbench.metrics",
    "fpbench.paired",
    "fpbench.cross_algorithm",
    "fpbench.experiments",
)
FORBIDDEN_INPUT_REFERENCES = (
    "workspace/prepared",
    "workspace/results",
    "workspace/derivations",
    "evidence/sourceafis-",
    "evidence/nbis-",
)
#: Stage 8A's published finalization pins these byte for byte.  Stage 8B may
#: read them and may not touch them (docs/adr/0067).
STAGE8A_AUTHORITY_PATHS = (
    "src/fpbench/core/errors.py",
    "src/fpbench/core/identifiers.py",
    "src/fpbench/core/modern_matcher_models.py",
    "src/fpbench/core/serialization.py",
    "src/fpbench/modern_matchers",
    "src/fpbench/storage/__init__.py",
    "src/fpbench/storage/modern_matcher_store.py",
)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_stage8b_imports_no_dataset_decision_or_evaluation_layer() -> None:
    offenders = [
        f"{path.relative_to(SOURCE_ROOT)} -> {module}"
        for path in STAGE8B_FILES
        for module in _imports(path)
        if any(module.startswith(prefix) for prefix in FORBIDDEN_IMPORTS)
    ]
    assert offenders == []


def test_no_stage8b_source_names_a_forbidden_workspace_or_evidence_tree() -> None:
    offenders: list[str] = []
    for path in STAGE8B_FILES:
        source = path.read_text(encoding="utf-8").lower().replace("\\", "/")
        for token in FORBIDDEN_INPUT_REFERENCES:
            if token in source:
                offenders.append(f"{path.name}: {token}")
    assert offenders == []


def test_the_qualification_layer_imports_without_torch() -> None:
    # The evidence, the schemas and the gates must be readable on a machine
    # that has no ML runtime at all; only the worker needs torch.
    probe = (
        "import sys;"
        "sys.modules['torch'] = None;"
        "sys.modules['torchvision'] = None;"
        "import fpbench.flx, fpbench.core.flx_models, fpbench.core.flx_errors;"
        "print('ok')"
    )
    completed = subprocess.run(
        (sys.executable, "-c", probe),
        capture_output=True,
        text=True,
        cwd=REPOSITORY_ROOT,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    assert "ok" in completed.stdout


def test_no_stage8b_source_imports_torch_at_module_scope() -> None:
    offenders = [
        f"{path.relative_to(SOURCE_ROOT)} -> {module}"
        for path in STAGE8B_FILES
        for module in _imports(path)
        if module.split(".")[0] in {"torch", "torchvision"}
    ]
    assert offenders == []


def test_stage8b_did_not_touch_the_stage8a_authority_source() -> None:
    # The binding is against whatever commit Stage 8A's published finalization
    # names as its verifier — not against Stage 8A's publication commit, which
    # the boundary repair itself moved past (docs/adr/0067).
    import json

    finalization = json.loads(
        (
            REPOSITORY_ROOT
            / "evidence"
            / "stage8a-modern-matcher-selection"
            / "stage-8a-finalization.json"
        ).read_text(encoding="utf-8")
    )
    completed = subprocess.run(
        (
            "git",
            "-C",
            str(REPOSITORY_ROOT),
            "diff",
            "--name-only",
            finalization["verifier_source_commit"],
            "--",
            *STAGE8A_AUTHORITY_PATHS,
        ),
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        pytest.skip("no readable Git provenance for the Stage 8A authority check")
    assert completed.stdout.strip() == ""


def test_stage8b_did_not_widen_the_existing_adapter_or_result_contracts() -> None:
    from fpbench.adapters.base import ADAPTER_CONTRACT_VERSION, FingerprintAlgorithmAdapter
    from fpbench.core.result_models import RESULT_SCHEMA_VERSION

    assert ADAPTER_CONTRACT_VERSION == "1"
    assert FingerprintAlgorithmAdapter.__abstractmethods__ == {
        "descriptor",
        "validate_environment",
        "compare",
    }
    assert RESULT_SCHEMA_VERSION == "1"


def test_stage8b_defines_no_representation_or_embedding_store() -> None:
    forbidden = {
        "RepresentationStore",
        "EmbeddingStore",
        "EmbeddingCache",
        "RepresentationCache",
        "TemplateStore",
    }
    offenders: list[str] = []
    for path in STAGE8B_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        defined = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.ClassDef, ast.FunctionDef))
        }
        offenders.extend(f"{path.name}: {name}" for name in sorted(defined & forbidden))
    assert offenders == []
