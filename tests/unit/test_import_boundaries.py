"""The dependency rules, enforced over the syntax tree rather than by review.

An adapter that can import ``fpbench.protocols`` can reach the pair manifest, and
an adapter that can reach the pair manifest can tell a genuine pair from an
impostor one. Nothing would announce that it had happened: the results would look
ordinary and be worthless (docs/adr/0001, docs/adr/0010).

So the rules are tested. Imports inside function bodies count — a deferred import
is still an import, and it is exactly where a boundary violation would hide.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import fpbench

pytestmark = pytest.mark.adapter_contract

SOURCE_ROOT = Path(fpbench.__file__).resolve().parent

#: Packages an adapter may not see. ``protocols`` and ``storage`` are the
#: dangerous ones; the rest are layers above it, and an adapter that imported one
#: would have inverted the dependency graph.
FORBIDDEN_FOR_ADAPTERS = (
    "fpbench.protocols",
    "fpbench.storage",
    "fpbench.decisions",
    "fpbench.eligibility",
    "fpbench.metrics",
    "fpbench.paired",
    "fpbench.evaluation",
    "fpbench.experiments",
)

#: Strings that would mean the generic research engine had learned an algorithm.
#: ``jar`` and ``bridge`` are on the list because a default value naming one is
#: the same failure as an import (spec section 7).
FORBIDDEN_IN_THE_ENGINE = (
    "sourceafis",
    "java",
    "jar",
    "bridge",
    "mindtct",
    "bozorth",
    "nbis",
)


def python_files(package: str) -> list[Path]:
    root = SOURCE_ROOT / Path(package.replace("fpbench.", "").replace(".", "/"))
    return sorted(path for path in root.rglob("*.py"))


def imports_of(path: Path) -> set[str]:
    """Every module this file imports, including inside function bodies."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


# ----------------------------------------------------------------- adapters


@pytest.mark.parametrize("forbidden", FORBIDDEN_FOR_ADAPTERS)
def test_no_adapter_imports_a_layer_above_it(forbidden):
    offenders: list[str] = []
    for path in python_files("fpbench.adapters"):
        for module in imports_of(path):
            if module == forbidden or module.startswith(f"{forbidden}."):
                offenders.append(f"{path.relative_to(SOURCE_ROOT)} -> {module}")
    assert offenders == [], f"adapters must not import {forbidden}: {offenders}"


def test_adapters_import_core_and_themselves_and_nothing_else_of_fpbench():
    """Stated positively, so a new forbidden package is covered automatically."""
    offenders: list[str] = []
    for path in python_files("fpbench.adapters"):
        for module in imports_of(path):
            if not module.startswith("fpbench"):
                continue
            if module.startswith(("fpbench.core", "fpbench.adapters")):
                continue
            if module == "fpbench":
                continue
            offenders.append(f"{path.relative_to(SOURCE_ROOT)} -> {module}")
    assert offenders == [], f"adapters reached outside core: {offenders}"


def test_the_adapter_support_tools_are_reusable_by_any_adapter():
    """They may import core and the contract, and nothing else of fpbench."""
    offenders: list[str] = []
    for path in python_files("fpbench.adapters.support"):
        for module in imports_of(path):
            if not module.startswith("fpbench"):
                continue
            if module.startswith(("fpbench.core", "fpbench.adapters")):
                continue
            offenders.append(f"{path.relative_to(SOURCE_ROOT)} -> {module}")
    assert offenders == [], offenders


# ------------------------------------------------------------- the engine


def engine_source() -> str:
    from fpbench.experiments import algorithm_research

    return Path(algorithm_research.__file__).read_text(encoding="utf-8")


def test_the_generic_engine_imports_no_adapter_package():
    from fpbench.experiments import algorithm_research

    offenders = sorted(
        module
        for module in imports_of(Path(algorithm_research.__file__))
        if module.startswith("fpbench.adapters")
        or module.endswith("sourceafis_validation")
        or module.endswith("sourceafis_research")
    )
    assert offenders == [], f"the engine imports an algorithm: {offenders}"


@pytest.mark.parametrize("token", FORBIDDEN_IN_THE_ENGINE)
def test_the_generic_engine_never_names_an_algorithm(token):
    """Not in code, not in a default value, not in prose (spec section 7)."""
    text = engine_source().lower()
    assert token not in text, f"{token!r} appears in the generic research engine"


def test_the_engine_does_import_the_integration_it_is_driven_by():
    """The positive half: it is generic, not empty."""
    from fpbench.experiments import algorithm_research

    imported = imports_of(Path(algorithm_research.__file__))
    assert "fpbench.experiments.research_integration" in imported


# ------------------------------------------------------------- the stores


def test_storage_imports_core_and_itself_and_nothing_else_of_fpbench():
    """The rule that decides where every persisted model lives.

    ``storage`` may import only ``core``, which is why the containers sit in
    ``core`` and the rules for deriving them sit in the package that owns them.
    A store that imported its own parser from a derivation package would invert
    that: the layer underneath would depend on the layer above, and the argument
    for splitting model from factory would stop holding.

    It was a stated rule and nothing checked it. Stage 8D's calibration store was
    first written with a deferred ``from fpbench.calibration.models import ...``
    inside three methods — deferred, so an import cycle would not have caught it
    either. It now reads its parser from ``core``, where the containers already
    live.

    One exception is recorded rather than hidden, and it is recorded so that a
    second one has to be argued for rather than merged.
    """
    #: `PreparedImageSetStore.verify` re-decodes a stored PNG to check it is the
    #: raster its entry records, and the decoder is `imaging.canonical`. Deferred
    #: to the method, and left alone here: moving a PNG decoder into `core` to
    #: satisfy the rule would put image handling in the module that is supposed to
    #: import nothing outside the standard library, which is a worse trade.
    KNOWN_EXCEPTIONS = {
        "storage/prepared_image_set_store.py -> fpbench.imaging.canonical",
    }
    offenders: list[str] = []
    for path in python_files("fpbench.storage"):
        for module in imports_of(path):
            if not module.startswith("fpbench"):
                continue
            if module.startswith(("fpbench.core", "fpbench.storage")):
                continue
            if module == "fpbench":
                continue
            relative = path.relative_to(SOURCE_ROOT).as_posix()
            offenders.append(f"{relative} -> {module}")
    assert set(offenders) <= KNOWN_EXCEPTIONS, (
        f"storage reached above core: {sorted(set(offenders) - KNOWN_EXCEPTIONS)}"
    )


# ------------------------------------------------------- the shared modules


def test_the_shared_input_checks_import_no_adapter():
    from fpbench.experiments import prepared_input_validation

    offenders = sorted(
        module
        for module in imports_of(Path(prepared_input_validation.__file__))
        if module.startswith("fpbench.adapters")
    )
    assert offenders == [], offenders


def test_the_universal_metadata_rules_live_below_the_experiments():
    """``execution`` may not import ``experiments``; the list is in execution."""
    from fpbench.execution import adapter_result_validation

    offenders = sorted(
        module
        for module in imports_of(Path(adapter_result_validation.__file__))
        if module.startswith(("fpbench.experiments", "fpbench.adapters"))
    )
    assert offenders == [], offenders


def test_the_receipt_builder_no_longer_depends_on_an_adapter():
    from fpbench.experiments import research_receipt

    offenders = sorted(
        module
        for module in imports_of(Path(research_receipt.__file__))
        if module.startswith("fpbench.adapters")
    )
    assert offenders == [], offenders


# ------------------------------------------------------------ the runner


def test_the_runner_still_takes_only_an_adapter_a_preparer_and_a_store():
    """Section 72: a two-stage route must not have widened the runner."""
    import inspect

    from fpbench.execution.runner import SingleJobRunner

    parameters = set(inspect.signature(SingleJobRunner.__init__).parameters)
    assert parameters == {
        "self",
        "run",
        "adapter",
        "preparer",
        "result_store",
        "dataset_root",
        "image_index",
        "workspace_root",
    }
    for forbidden in ("extractor", "matcher", "template_store", "runtime_bundle",
                      "integration"):
        assert forbidden not in parameters


def test_the_raw_result_schema_version_did_not_move():
    """Section 73: algorithm-specific facts go in the existing fields."""
    from fpbench.core.result_models import RESULT_SCHEMA_VERSION

    assert RESULT_SCHEMA_VERSION == "1"


def test_the_adapter_contract_version_did_not_move():
    from fpbench.adapters.base import ADAPTER_CONTRACT_VERSION

    assert ADAPTER_CONTRACT_VERSION == "1"


def test_the_mandatory_adapter_surface_is_still_three_members():
    """No ``extract``, no ``match_templates``, no ``quality`` (docs/adr/0039)."""
    from fpbench.adapters.base import FingerprintAlgorithmAdapter

    abstract = set(FingerprintAlgorithmAdapter.__abstractmethods__)
    assert abstract == {"descriptor", "validate_environment", "compare"}


def test_no_template_store_was_introduced():
    """docs/adr/0041: templates stay adapter-local until two algorithms exist."""
    forbidden = ("TemplateArtifact", "TemplateStore", "TemplateManifest",
                 "TemplateCache")
    offenders: list[str] = []
    for path in SOURCE_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        defined = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.ClassDef, ast.FunctionDef))
        }
        for name in forbidden:
            if name in defined:
                offenders.append(f"{path.relative_to(SOURCE_ROOT)}: {name}")
    assert offenders == [], offenders
