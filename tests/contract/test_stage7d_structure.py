"""The boundaries stage 7D depends on, checked by reading the syntax trees.

Every claim here is one a docstring already makes. A docstring is not a
guarantee: the whole argument of stage 7D is that the two algorithms' decisions
were produced by the same code, and a sentence saying so would survive an import
that made it false.

So each test parses the module and walks the tree (spec section 76).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.stage7d_contract

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src" / "fpbench"

#: Words that name a particular algorithm. A shared engine that contained any of
#: them would be an engine that could tell the two chains apart.
ALGORITHM_WORDS = ("sourceafis", "nbis", "bridge", "jar", "mindtct", "bozorth")

#: The engines the two chains share, and which must therefore name no algorithm.
NEUTRAL_MODULES = (
    "experiments/algorithm_decisions.py",
    "experiments/algorithm_evaluation.py",
    "experiments/decision_source_integration.py",
)


def _tree(relative: str) -> ast.Module:
    return ast.parse((SOURCE_ROOT / relative).read_text(encoding="utf-8"))


def _source(relative: str) -> str:
    return (SOURCE_ROOT / relative).read_text(encoding="utf-8")


def _imported_modules(tree: ast.Module) -> set[str]:
    """Every module named by an ``import`` anywhere, including inside functions."""
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _identifiers(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, ast.keyword) and node.arg:
            names.add(node.arg)
    return names


def _strings(tree: ast.Module) -> set[str]:
    """String constants, minus the docstrings — prose is allowed to name things."""
    docstrings = {
        ast.get_docstring(node, clean=False)
        for node in ast.walk(tree)
        if isinstance(
            node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        )
    }
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value not in docstrings
    }


# ------------------------------------------------- the engines name no algorithm


@pytest.mark.parametrize("relative", NEUTRAL_MODULES)
def test_a_shared_engine_imports_no_algorithm(relative):
    imported = _imported_modules(_tree(relative))
    offending = sorted(
        module
        for module in imported
        if any(word in module.lower() for word in ALGORITHM_WORDS)
    )
    assert not offending, (
        f"{relative} imports {offending}; a shared engine that could reach one "
        "algorithm's module is an engine the two chains do not share equally"
    )


@pytest.mark.parametrize("relative", NEUTRAL_MODULES)
def test_a_shared_engine_names_no_algorithm_in_code(relative):
    tree = _tree(relative)
    vocabulary = _identifiers(tree) | _strings(tree)
    offending = sorted(
        name
        for name in vocabulary
        if any(word in str(name).lower() for word in ALGORITHM_WORDS)
    )
    assert not offending, (
        f"{relative} names {offending} outside its prose; a branch or a literal "
        "that mentions an algorithm is a place the two chains can diverge"
    )


@pytest.mark.parametrize("relative", NEUTRAL_MODULES)
def test_a_shared_engine_has_no_adapter_import(relative):
    imported = _imported_modules(_tree(relative))
    offending = sorted(
        module for module in imported if module.startswith("fpbench.adapters")
    )
    assert not offending, f"{relative} imports {offending}"


# ---------------------------------------------- the lower layers stay unaware


@pytest.mark.parametrize(
    "package", ["eligibility", "metrics", "evaluation", "decisions"]
)
def test_a_counting_layer_imports_no_algorithm(package):
    for path in sorted((SOURCE_ROOT / package).glob("*.py")):
        imported = _imported_modules(
            ast.parse(path.read_text(encoding="utf-8"))
        )
        offending = sorted(
            module
            for module in imported
            if module.startswith("fpbench.adapters")
            or any(word in module.lower() for word in ALGORITHM_WORDS)
        )
        assert not offending, f"{package}/{path.name} imports {offending}"


# ------------------------------------------- the wrappers apply no threshold


#: Names only the decision engine may use. A wrapper that called any of them
#: would be applying a threshold of its own (spec section 24).
_THRESHOLD_APPLICATION = (
    "decide_score",
    "apply_decision_profile",
    "derive_self_eligibility",
    "build_mated_unconditional_view",
    "build_mated_conditional_view",
    "build_non_mated_sanity_view",
    "build_derivation_receipt",
    "build_derivation_finalization_marker",
)


@pytest.mark.parametrize(
    "relative",
    [
        "experiments/sourceafis_decisions.py",
        "experiments/sourceafis_native_decisions.py",
        "experiments/sourceafis_canonical500_decisions.py",
        "experiments/nbis_canonical500_decisions.py",
    ],
)
def test_a_decision_wrapper_applies_no_threshold(relative):
    vocabulary = _identifiers(_tree(relative))
    offending = sorted(set(_THRESHOLD_APPLICATION) & vocabulary)
    assert not offending, (
        f"{relative} calls {offending}; a wrapper builds a spec and an "
        "integration, and the engine does the rest (spec section 24)"
    )


@pytest.mark.parametrize(
    "relative",
    [
        "experiments/sourceafis_decisions.py",
        "experiments/nbis_canonical500_decisions.py",
    ],
)
def test_a_decision_wrapper_carries_no_threshold_literal(relative):
    """No wrapper writes a number that could be a threshold.

    Checked over the syntax tree rather than the text, because the prose in these
    modules quotes the rule on purpose — explaining that NIST documented `score >
    40` is exactly what a wrapper's docstring is for. What may not exist is the
    number as *code*: the threshold lives in a committed YAML file with a
    fingerprint, and a literal here would be a second place it lived.
    """
    tree = _tree(relative)
    numbers = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float))
        and not isinstance(node.value, bool)
    }
    assert 40 not in numbers, (
        f"{relative} carries 40 as a code literal; the threshold belongs to the "
        "profile file"
    )
    assignments = {
        target.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    keywords = {
        node.arg
        for node in ast.walk(tree)
        if isinstance(node, ast.keyword) and node.arg
    }
    offending = sorted(
        name for name in assignments | keywords if "threshold" in name.lower()
    )
    assert not offending, (
        f"{relative} assigns or passes {offending}; a wrapper names a profile "
        "file, never a threshold"
    )


# ------------------------------------- the comparison never reaches a score


def _cross_algorithm_files() -> list[Path]:
    return sorted((SOURCE_ROOT / "cross_algorithm").glob("*.py")) + [
        SOURCE_ROOT / "core" / "cross_algorithm_models.py"
    ]


#: What reading a score would look like. ``raw_score`` is the field on a stored
#: result; ``ResultStore`` is the only thing that can hand one over; the rest are
#: the arithmetic a score comparison would need (spec sections 52 and 76).
_SCORE_ACCESS = (
    "raw_score",
    "raw_scores",
    "score_delta",
    "score_ratio",
    "score_relation",
    "normalised_score",
    "normalized_score",
    "rank_correlation",
    "decide_score",
    "threshold_decimal",
)


@pytest.mark.parametrize("path", _cross_algorithm_files(), ids=lambda p: p.name)
def test_the_comparison_package_never_reads_a_raw_score(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    vocabulary = _identifiers(tree)
    offending = sorted(set(_SCORE_ACCESS) & vocabulary)
    assert not offending, (
        f"cross_algorithm/{path.name} uses {offending}; the two algorithms' "
        "scores are not on a common scale (docs/adr/0060)"
    )


@pytest.mark.parametrize("path", _cross_algorithm_files(), ids=lambda p: p.name)
def test_the_comparison_package_imports_no_score_source(path):
    imported = _imported_modules(ast.parse(path.read_text(encoding="utf-8")))
    forbidden = (
        "fpbench.adapters",
        "fpbench.storage.result_store",
        "fpbench.decisions.apply",
        "fpbench.execution",
        "fpbench.paired",
    )
    offending = sorted(
        module
        for module in imported
        if any(module.startswith(prefix) for prefix in forbidden)
    )
    assert not offending, f"cross_algorithm/{path.name} imports {offending}"


def test_the_comparison_package_does_not_reuse_the_paired_schema():
    """Section 53: the paired schema's assumptions are false between algorithms."""
    for path in _cross_algorithm_files():
        source = path.read_text(encoding="utf-8")
        for forbidden in (
            "PairedComparisonRecord",
            "NativeCanonicalControlAudit",
            "native_run",
            "canonical_run_id",
        ):
            assert forbidden not in source, (
                f"cross_algorithm/{path.name} mentions {forbidden!r}; that schema "
                "assumes one algorithm, one threshold and a meaningful score delta"
            )


def test_the_comparison_models_use_left_and_right_rather_than_native_and_canonical():
    source = (SOURCE_ROOT / "core" / "cross_algorithm_models.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    fields = {
        node.target.id
        for node in ast.walk(tree)
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }
    assert any(name.startswith("left_") for name in fields)
    assert any(name.startswith("right_") for name in fields)
    assert not [
        name
        for name in fields
        if name.startswith("native_") or name.startswith("canonical_")
    ]
