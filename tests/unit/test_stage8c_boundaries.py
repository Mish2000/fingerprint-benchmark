"""Stage 8C is a seam and some configuration, and this is where that is checked.

Two claims, both structural, both walked rather than asserted in prose:

**No orchestration was added.**  ``flx_research.py`` supplies an integration and
forwards four commands.  It contains no job loop, opens no raw result, starts no
subprocess, builds no runtime bundle, writes no receipt and computes no
fingerprint of its own beyond proving the pinned bytes are the repository's.

**No prior algorithm's results are reachable.**  Stage 8C reads the reference
run's identity, plan, pair manifest, prepared inputs and readiness.  It must not
be able to reach a SourceAFIS or NBIS score, a decision, an eligibility set, a
metric or a cross-algorithm comparison — not because nobody wrote the call, but
because the import graph does not contain it (spec section 18, docs/adr/0076).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from fpbench.experiments.flx_adapter import RUNTIME_ASSET_ROLES
from fpbench.core.errors import ConfigurationError, ResearchPreflightError
from fpbench.experiments import flx_research
from fpbench.experiments.algorithm_research import REPOSITORY_ROOT
from fpbench.experiments.flx_research import (
    INTEGRATION_ID,
    flx_research_integration,
    resolve_bundle_root,
)
from fpbench.experiments.research_integration import DevelopmentAdapterRuntime

pytestmark = pytest.mark.stage8c_contract

#: Every module Stage 8C owns. The boundary claims are made about all of them,
#: not only the one that would obviously break.
STAGE_8C_SOURCES = (
    "src/fpbench/experiments/flx_adapter.py",
    "src/fpbench/experiments/flx_failure_mapping.py",
    "src/fpbench/experiments/flx_canonical500_full.py",
    "src/fpbench/experiments/flx_research.py",
    "src/fpbench/experiments/flx_validation.py",
    "src/fpbench/experiments/stage8c_identity.py",
)

#: Deriving anything from a raw score is Stage 8D's, and reading another
#: algorithm's scores is nobody's (spec section 18).
FORBIDDEN_IMPORT_PREFIXES = (
    "fpbench.cross_algorithm",
    "fpbench.decisions",
    "fpbench.derivations",
    "fpbench.eligibility",
    "fpbench.evaluation",
    "fpbench.metrics",
    "fpbench.paired",
)

#: Modules that would let Stage 8C open another algorithm's stored rows.
FORBIDDEN_EXPERIMENT_MODULES = (
    "fpbench.experiments.algorithm_decisions",
    "fpbench.experiments.algorithm_evaluation",
    "fpbench.experiments.decision_source_integration",
    "fpbench.experiments.nbis_canonical500_decisions",
    "fpbench.experiments.nbis_canonical500_evaluation",
    "fpbench.experiments.nbis_canonical500_full",
    "fpbench.experiments.nbis_research",
    "fpbench.experiments.nbis_validation",
    "fpbench.experiments.sourceafis_canonical500_decisions",
    "fpbench.experiments.sourceafis_canonical500_evaluation",
    "fpbench.experiments.sourceafis_decisions",
    "fpbench.experiments.sourceafis_evaluation",
    "fpbench.experiments.sourceafis_native_vs_canonical500",
    "fpbench.experiments.sourceafis_research",
    "fpbench.experiments.sourceafis_validation",
    "fpbench.experiments.sourceafis_vs_nbis_canonical500",
)

#: torch belongs in the isolated worker, which the research engine never
#: imports (docs/adr/0072).
FORBIDDEN_RUNTIME_IMPORTS = ("torch", "torchvision")


def _sources() -> tuple[Path, ...]:
    return tuple(REPOSITORY_ROOT / relative for relative in STAGE_8C_SOURCES)


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(Path(path).read_text(encoding="utf-8"), filename=str(path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


def _string_literals(path: Path) -> list[str]:
    tree = ast.parse(Path(path).read_text(encoding="utf-8"), filename=str(path))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


# ------------------------------------------------------------ the import graph


def test_every_stage_8c_source_exists() -> None:
    for path in _sources():
        assert path.is_file(), f"missing Stage 8C source: {path}"


@pytest.mark.parametrize("relative", STAGE_8C_SOURCES)
def test_no_stage_8c_module_imports_a_downstream_derivation(relative: str) -> None:
    imported = _imported_modules(REPOSITORY_ROOT / relative)
    blocked = sorted(
        name
        for name in imported
        if any(
            name == prefix or name.startswith(prefix + ".")
            for prefix in FORBIDDEN_IMPORT_PREFIXES
        )
    )
    assert not blocked, f"{relative} imports {blocked}"


@pytest.mark.parametrize("relative", STAGE_8C_SOURCES)
def test_no_stage_8c_module_imports_another_algorithms_experiment(
    relative: str,
) -> None:
    imported = _imported_modules(REPOSITORY_ROOT / relative)
    blocked = sorted(imported & set(FORBIDDEN_EXPERIMENT_MODULES))
    assert not blocked, f"{relative} imports {blocked}"


@pytest.mark.parametrize("relative", STAGE_8C_SOURCES)
def test_torch_stays_in_the_worker(relative: str) -> None:
    imported = _imported_modules(REPOSITORY_ROOT / relative)
    blocked = sorted(
        name for name in imported if name.split(".")[0] in FORBIDDEN_RUNTIME_IMPORTS
    )
    assert not blocked, f"{relative} imports {blocked}"


@pytest.mark.parametrize("relative", STAGE_8C_SOURCES)
def test_no_stage_8c_module_names_another_algorithms_stored_rows(
    relative: str,
) -> None:
    forbidden = (
        "evidence/sourceafis-",
        "evidence/nbis-",
        "results/run_7ac1cecc0bb3",
        "results/run_f0468f28ffba",
    )
    for literal in _string_literals(REPOSITORY_ROOT / relative):
        normalized = literal.replace("\\", "/").lower()
        for reference in forbidden:
            assert reference not in normalized, (
                f"{relative} names a forbidden prior-stage input: {literal!r}"
            )


def test_the_only_reference_run_read_is_the_sourceafis_canonical_identity() -> None:
    """The one permitted reach into another experiment, and what it is for.

    Stage 7C established the pattern: the reference run's *readiness* is read
    through its own wrapper, and nothing else is. The import is deliberately
    inside a function so the dependency is visibly one call wide, and it must
    be the canonical-run wrapper rather than anything that opens result rows.
    """
    path = REPOSITORY_ROOT / "src/fpbench/experiments/flx_canonical500_full.py"
    imported = _imported_modules(path)
    reference_imports = sorted(
        name
        for name in imported
        if name.startswith("fpbench.experiments.sourceafis")
    )
    assert reference_imports in (
        [],
        ["fpbench.experiments.sourceafis_canonical500_full"],
    ), reference_imports


# --------------------------------------------------------- no orchestration


def test_the_research_wrapper_defines_no_orchestration() -> None:
    """``flx_research.py`` forwards; it does not run anything.

    The names below are how orchestration shows up: a loop over jobs, a store
    being written, a process being started, a receipt being built.
    """
    source = (REPOSITORY_ROOT / "src/fpbench/experiments/flx_research.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            function = node.func
            if isinstance(function, ast.Name):
                called.add(function.id)
            elif isinstance(function, ast.Attribute):
                called.add(function.attr)

    forbidden = {
        "SequentialRunExecutor",
        "SingleJobRunner",
        "RunCompletionService",
        "build_execution_plan",
        "build_result_set",
        "build_research_receipt",
        "build_run_completion",
        "create_run_definition",
        "write_raw_result",
        "read_raw_result",
        "ensure_result_set",
        "ensure_research_receipt",
        "materialize",
        "Popen",
        "run",
    }
    assert not (called & forbidden), sorted(called & forbidden)


def test_the_research_wrapper_imports_no_storage_or_execution_machinery() -> None:
    imported = _imported_modules(
        REPOSITORY_ROOT / "src/fpbench/experiments/flx_research.py"
    )
    blocked = sorted(
        name
        for name in imported
        if name.startswith("fpbench.storage.") or name.startswith("fpbench.execution.")
    )
    assert not blocked, blocked


def test_the_adapter_never_learns_what_a_pair_is() -> None:
    """The adapter takes two prepared images and a context, and nothing else.

    ``ComparisonContext`` carries no pair id, no stage, no subject and no ground
    truth by construction, so this checks the other direction: the adapter never
    imports a model that would let it acquire one (docs/adr/0010).
    """
    imported = _imported_modules(
        REPOSITORY_ROOT / "src/fpbench/experiments/flx_adapter.py"
    )
    assert "fpbench.core.models" not in imported
    assert "fpbench.protocols.sd300_protocol" not in imported
    assert not any(name.startswith("fpbench.datasets") for name in imported)


# ------------------------------------------------------------- the integration


def test_the_integration_declares_this_routes_three_roles() -> None:
    integration = flx_research_integration(bundle_root=REPOSITORY_ROOT / "absent")
    assert integration.integration_id == INTEGRATION_ID
    assert integration.adapter_id == "flx_pytorch_subprocess"
    assert integration.runtime_asset_roles == RUNTIME_ASSET_ROLES
    assert integration.primary_runtime_asset_role == "flx_worker_script"


def test_the_integration_fingerprint_is_stable() -> None:
    first = flx_research_integration(bundle_root=REPOSITORY_ROOT / "absent")
    second = flx_research_integration(bundle_root=REPOSITORY_ROOT / "elsewhere")
    # The seam's identity is its declarations, not where a 2 GB bundle happens
    # to live on one machine.
    assert first.integration_fingerprint == second.integration_fingerprint


def test_the_development_runtime_pins_exactly_the_three_committed_files() -> None:
    integration = flx_research_integration(bundle_root=REPOSITORY_ROOT / "absent")
    development = integration.create_development_runtime(REPOSITORY_ROOT, Path(), {})
    assert isinstance(development, DevelopmentAdapterRuntime)
    assert development.roles == frozenset(RUNTIME_ASSET_ROLES)
    assert development.assets["flx_worker_script"] == flx_research.WORKER_SCRIPT
    assert development.assets["flx_runtime_lock"] == flx_research.RUNTIME_LOCK_CONFIG
    assert development.assets["flx_runtime_policy"] == flx_research.RUNTIME_POLICY_CONFIG


def test_no_pinned_role_is_the_checkpoint_or_the_source_archive() -> None:
    # docs/adr/0077: the weights are never copied into a workspace.
    integration = flx_research_integration(bundle_root=REPOSITORY_ROOT / "absent")
    development = integration.create_development_runtime(REPOSITORY_ROOT, Path(), {})
    for path in development.assets.values():
        assert path.suffix not in {".pyt", ".gz", ".tar"}
        assert "checkpoint" not in path.as_posix()


def test_an_unknown_development_override_is_refused() -> None:
    integration = flx_research_integration(bundle_root=REPOSITORY_ROOT / "absent")
    with pytest.raises(ConfigurationError):
        integration.create_development_runtime(
            REPOSITORY_ROOT, Path(), {"build_directory": "somewhere"}
        )


def test_a_missing_committed_file_stops_everything_before_an_adapter_exists(
    tmp_path: Path,
) -> None:
    integration = flx_research_integration(bundle_root=REPOSITORY_ROOT / "absent")
    with pytest.raises(ResearchPreflightError, match="missing"):
        integration.create_development_runtime(tmp_path, Path(), {})


def test_the_bundle_root_is_named_and_never_searched_for(monkeypatch) -> None:
    monkeypatch.delenv(flx_research.BUNDLE_ROOT_ENV_VAR, raising=False)
    explicit = resolve_bundle_root(REPOSITORY_ROOT / "explicit")
    assert explicit == (REPOSITORY_ROOT / "explicit").resolve()

    monkeypatch.setenv(flx_research.BUNDLE_ROOT_ENV_VAR, str(REPOSITORY_ROOT / "env"))
    assert resolve_bundle_root() == (REPOSITORY_ROOT / "env").resolve()
    # An explicit path still wins over the variable.
    assert resolve_bundle_root(REPOSITORY_ROOT / "explicit") == (
        REPOSITORY_ROOT / "explicit"
    ).resolve()
