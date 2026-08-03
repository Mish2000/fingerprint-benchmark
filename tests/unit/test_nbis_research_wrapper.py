"""The NBIS integration is a seam, and the wrapper around it is four forwards.

Stage 7A's claim was that a second algorithm needs an adapter, a validator, some
configuration and some tests — and *not* a second runner, a second engine, a
second evidence chain or a second copy of the orchestration. This file is where
the second half of that is checked: that ``nbis_research.py`` contains no
orchestration at all, and that nothing in the NBIS route reaches for the first
algorithm's code (spec sections 38, 39 and 50).

The build-manifest checks in the development and delegate factories are the other
subject here. They run *before* an adapter exists, so an uncertified build cannot
reach the engine at all — and until somebody seals the source lock with the
digests of the archives NIST published, no NBIS research run can be prepared.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from fpbench.adapters.nbis.adapter import ADAPTER_ID
from fpbench.adapters.nbis.config import (
    BOZORTH3_ROLE,
    BUILD_MANIFEST_ROLE,
    MINDTCT_ROLE,
    RUNTIME_ASSET_ROLES,
)
from fpbench.core.errors import ConfigurationError, ResearchPreflightError
from fpbench.experiments import nbis_research
from fpbench.experiments.nbis_research import (
    INTEGRATION_ID,
    nbis_research_integration,
    resolve_build_directory,
)
from fpbench.experiments.research_integration import DevelopmentAdapterRuntime
from nbisworld import build_stand_in, certify_host, sealed_repository

pytestmark = pytest.mark.nbis_contract


@pytest.fixture
def certified(monkeypatch):
    """Let this machine past the certified-target gate.

    Stage 7B certifies Linux x86_64, and the gate is asserted on its own in
    ``test_nbis_adapter.py``. Here it would otherwise be the only thing any of
    these tests ever reached.
    """
    certify_host(monkeypatch)


# ------------------------------------------------------------- the seam


def test_the_integration_declares_all_three_roles():
    integration = nbis_research_integration()
    assert integration.integration_id == INTEGRATION_ID
    assert integration.integration_id == "nbis_mindtct_bozorth3_research_v1"
    assert integration.adapter_id == ADAPTER_ID
    assert integration.runtime_asset_roles == RUNTIME_ASSET_ROLES
    assert integration.primary_runtime_asset_role == MINDTCT_ROLE


def test_the_integration_fingerprint_is_stable():
    assert (
        nbis_research_integration().integration_fingerprint
        == nbis_research_integration().integration_fingerprint
    )


def test_each_call_returns_a_fresh_record():
    assert nbis_research_integration() is not nbis_research_integration()


# ------------------------------------------------------ development runtime


def test_the_development_runtime_pins_all_three_files(tmp_path, certified):
    build = build_stand_in(tmp_path / "build", real_names=True)
    repository = sealed_repository(tmp_path / "repo", build.manifest())
    runtime = nbis_research._development_runtime(
        repository, tmp_path / "algorithm.yaml", {"build_directory": build.directory}
    )
    assert isinstance(runtime, DevelopmentAdapterRuntime)
    assert set(runtime.assets) == {MINDTCT_ROLE, BOZORTH3_ROLE, BUILD_MANIFEST_ROLE}
    assert runtime.adapter.descriptor.adapter_id == ADAPTER_ID
    nbis_research_integration().require_development_runtime(runtime)


def test_an_unsealed_source_lock_stops_a_research_run(tmp_path, certified):
    """No research run can be prepared until the archives have been recorded.

    Built as its own checkout rather than read from this one, so the rule is
    tested whether or not the repository's lock has been sealed yet.
    """
    from fpbench.core.serialization import write_json

    build = build_stand_in(tmp_path / "build", real_names=True)
    repository = sealed_repository(tmp_path / "repo", build.manifest())
    entry = {
        "version": "5.0.0",
        "source": "official_nist_nigos",
        "url": None,
        "sha256": None,
        "size_bytes": 0,
    }
    write_json(
        repository / "integrations" / "nbis" / "nbis-5.0.0.lock.json",
        {"schema_version": "1", "release": dict(entry), "tests": dict(entry)},
    )
    with pytest.raises(ResearchPreflightError, match="never been sealed"):
        nbis_research._development_runtime(
            repository, tmp_path / "algorithm.yaml", {"build_directory": build.directory}
        )


def test_a_manifest_that_does_not_describe_the_binaries_stops_a_research_run(tmp_path):
    build = build_stand_in(tmp_path / "build")
    repository = sealed_repository(tmp_path / "repo", build.manifest())
    build.bozorth3.write_bytes(build.bozorth3.read_bytes() + b"\n")
    with pytest.raises(ResearchPreflightError, match="not certified"):
        nbis_research._development_runtime(
            repository, tmp_path / "algorithm.yaml", {"build_directory": build.directory}
        )


def test_a_locked_archive_the_build_did_not_use_stops_a_research_run(tmp_path):
    build = build_stand_in(tmp_path / "build")
    repository = sealed_repository(tmp_path / "repo", build.manifest())
    lock = repository / "integrations" / "nbis" / "nbis-5.0.0.lock.json"
    lock.write_text(
        lock.read_text(encoding="utf-8").replace(
            build.manifest().source_archive_sha256, "a" * 64
        ),
        encoding="utf-8",
    )
    with pytest.raises(ResearchPreflightError, match="not certified"):
        nbis_research._development_runtime(
            repository, tmp_path / "algorithm.yaml", {"build_directory": build.directory}
        )


def test_a_different_patch_series_stops_a_research_run(tmp_path):
    """Section 7: a behavioural change to NBIS is never accepted silently."""
    build = build_stand_in(tmp_path / "build")
    repository = sealed_repository(tmp_path / "repo", build.manifest())
    series = repository / "integrations" / "nbis" / "patches" / "series.json"
    patch = series.parent / "0001-something.patch"
    patch.write_text("--- a\n+++ b\n", encoding="utf-8")
    series.write_text(
        '{"schema_version": "1", "patches": [{"file": "0001-something.patch"}]}',
        encoding="utf-8",
    )
    with pytest.raises(ResearchPreflightError, match="not certified"):
        nbis_research._development_runtime(
            repository, tmp_path / "algorithm.yaml", {"build_directory": build.directory}
        )


def test_a_different_build_script_stops_a_research_run(tmp_path):
    build = build_stand_in(tmp_path / "build")
    repository = sealed_repository(tmp_path / "repo", build.manifest())
    script = repository / "integrations" / "nbis" / "verify_build.py"
    script.write_text("# not the build script that produced this\n", encoding="utf-8")
    with pytest.raises(ResearchPreflightError, match="not certified"):
        nbis_research._development_runtime(
            repository, tmp_path / "algorithm.yaml", {"build_directory": build.directory}
        )


def test_an_unknown_development_override_is_refused(tmp_path):
    with pytest.raises(ConfigurationError, match="unknown"):
        nbis_research._development_runtime(
            tmp_path, tmp_path / "algorithm.yaml", {"jar": "no"}
        )


# --------------------------------------------------------- research delegate


def bundle_for(build, workspace: Path):
    from fpbench.storage.runtime_bundle_store import RuntimeBundleStore

    return RuntimeBundleStore(workspace).materialize(
        adapter_id=ADAPTER_ID, assets=dict(build.assets())
    )


def test_the_delegate_runs_only_the_pinned_bytes(tmp_path, certified):
    build = build_stand_in(tmp_path / "build", real_names=True)
    repository = sealed_repository(tmp_path / "repo", build.manifest())
    workspace = tmp_path / "workspace"
    bundle = bundle_for(build, workspace)
    from fpbench.storage.runtime_bundle_store import RuntimeBundleStore

    store = RuntimeBundleStore(workspace)
    paths = {
        role: store.asset_path(bundle.bundle_id, role) for role in RUNTIME_ASSET_ROLES
    }
    delegate = nbis_research._research_delegate(
        repository, tmp_path / "algorithm.yaml", bundle, paths, _software()
    )
    assert delegate.config.research_mode is True
    assert delegate.config.mindtct_executable == paths[MINDTCT_ROLE]
    assert delegate.config.build_manifest == paths[BUILD_MANIFEST_ROLE]
    assert build.directory not in delegate.config.mindtct_executable.parents


def test_the_delegate_refuses_a_file_the_bundle_does_not_hold(tmp_path):
    build = build_stand_in(tmp_path / "build")
    repository = sealed_repository(tmp_path / "repo", build.manifest())
    workspace = tmp_path / "workspace"
    bundle = bundle_for(build, workspace)
    from fpbench.storage.runtime_bundle_store import RuntimeBundleStore

    store = RuntimeBundleStore(workspace)
    paths = {
        role: store.asset_path(bundle.bundle_id, role) for role in RUNTIME_ASSET_ROLES
    }
    # The build directory's own copy: same name, same content, different bytes on
    # disk once one of them is edited.
    paths[BOZORTH3_ROLE] = build.bozorth3
    build.bozorth3.write_bytes(build.bozorth3.read_bytes() + b"\n")
    with pytest.raises(ResearchPreflightError):
        nbis_research._research_delegate(
            repository, tmp_path / "algorithm.yaml", bundle, paths, _software()
        )


def _software():
    from fpbench.core.provenance_models import PROVENANCE_KIND_GIT, SoftwareProvenance

    return SoftwareProvenance(
        provenance_kind=PROVENANCE_KIND_GIT,
        source_revision="0" * 40,
        source_tree_clean=True,
        package_version="0.1.0",
        python_version="3.12.0",
        python_implementation="CPython",
        dependency_versions={},
    )


# ------------------------------------------------------- the build directory


def test_an_explicit_build_directory_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("FPBENCH_NBIS_BUILD_DIR", str(tmp_path / "from-environment"))
    assert resolve_build_directory(tmp_path / "explicit") == (
        tmp_path / "explicit"
    ).resolve()


def test_the_environment_variable_is_used_when_there_is_no_override(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("FPBENCH_NBIS_BUILD_DIR", str(tmp_path / "chosen"))
    assert resolve_build_directory() == (tmp_path / "chosen").resolve()


def test_no_certified_build_is_an_error_rather_than_a_guess(tmp_path, monkeypatch):
    monkeypatch.delenv("FPBENCH_NBIS_BUILD_DIR", raising=False)
    with pytest.raises(ConfigurationError, match="no certified NBIS build"):
        resolve_build_directory(build_root=tmp_path / "empty")


def test_two_certified_builds_need_a_choice(tmp_path, monkeypatch):
    """Picking the newest would let a rebuild silently change a run's runtime."""
    monkeypatch.delenv("FPBENCH_NBIS_BUILD_DIR", raising=False)
    root = tmp_path / "builds"
    for name in ("aaaaaaaaaaaa", "bbbbbbbbbbbb"):
        directory = root / name
        directory.mkdir(parents=True)
        (directory / "nbis-build-manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="name the one to pin"):
        resolve_build_directory(build_root=root)


def test_one_certified_build_needs_no_choice(tmp_path, monkeypatch):
    monkeypatch.delenv("FPBENCH_NBIS_BUILD_DIR", raising=False)
    root = tmp_path / "builds"
    directory = root / "aaaaaaaaaaaa"
    directory.mkdir(parents=True)
    (directory / "nbis-build-manifest.json").write_text("{}", encoding="utf-8")
    assert resolve_build_directory(build_root=root) == directory.resolve()


def test_a_build_without_a_manifest_is_not_a_certified_build(tmp_path, monkeypatch):
    monkeypatch.delenv("FPBENCH_NBIS_BUILD_DIR", raising=False)
    root = tmp_path / "builds"
    (root / "aaaaaaaaaaaa" / "bin").mkdir(parents=True)
    with pytest.raises(ConfigurationError, match="no certified NBIS build"):
        resolve_build_directory(build_root=root)


# ------------------------------------------------------------- forwarding


@pytest.mark.parametrize(
    "wrapper,engine",
    [
        ("prepare_nbis_research_run", "prepare_algorithm_research_run"),
        ("execute_nbis_research_run", "execute_algorithm_research_run"),
        ("inspect_nbis_research_experiment", "inspect_algorithm_research_experiment"),
        ("finalize_nbis_research_run", "finalize_algorithm_research_run"),
    ],
)
def test_every_command_forwards_the_nbis_integration(monkeypatch, wrapper, engine):
    seen: dict[str, object] = {}

    def capture(**kwargs):
        seen.update(kwargs)
        return "forwarded"

    monkeypatch.setattr(nbis_research, engine, capture)
    result = getattr(nbis_research, wrapper)(
        spec="the-spec", preparer_factory="the-preparer", workspace=Path("/w")
    )
    assert result == "forwarded"
    assert seen["spec"] == "the-spec"
    assert seen["integration"].integration_id == INTEGRATION_ID
    assert seen["integration"].adapter_id == ADAPTER_ID


# ----------------------------------------------------- structural isolation


def imports_of(path: Path) -> set[str]:
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


def nbis_sources() -> list[Path]:
    import fpbench
    from fpbench.experiments import nbis_validation

    root = Path(fpbench.__file__).resolve().parent
    return [
        *sorted((root / "adapters" / "nbis").rglob("*.py")),
        Path(nbis_validation.__file__),
        Path(nbis_research.__file__),
    ]


def test_no_nbis_module_imports_the_first_algorithm():
    """Section 50: two routes, one shared engine, no shared adapter code."""
    offenders: list[str] = []
    for path in nbis_sources():
        for module in imports_of(path):
            if "sourceafis" in module:
                offenders.append(f"{path.name} -> {module}")
    assert offenders == [], offenders


def test_no_nbis_module_mentions_the_first_algorithm_at_all():
    offenders = [
        path.name
        for path in nbis_sources()
        if "sourceafis" in path.read_text(encoding="utf-8").lower()
    ]
    assert offenders == [], offenders


def test_the_nbis_adapter_package_imports_only_core_and_adapters():
    import fpbench

    root = Path(fpbench.__file__).resolve().parent
    offenders: list[str] = []
    for path in sorted((root / "adapters" / "nbis").rglob("*.py")):
        for module in imports_of(path):
            if not module.startswith("fpbench") or module == "fpbench":
                continue
            if module.startswith(("fpbench.core", "fpbench.adapters")):
                continue
            offenders.append(f"{path.name} -> {module}")
    assert offenders == [], offenders


def test_the_wrapper_holds_no_orchestration():
    """Section 39: it assembles an integration and forwards. That is all."""
    source = Path(nbis_research.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
            continue
        iterated = ast.unparse(getattr(node, "iter", node))
        for subject in ("job", "plan", "pair", "result", "entry", "comparison"):
            assert subject not in iterated, (
                f"the wrapper loops over {iterated!r}; iterating the work is the "
                "engine's job"
            )
    # Over the syntax tree, not over the text: the module's own docstring says
    # what it does not do, and a prose ban would be defeated by explaining it.
    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            used.add(node.attr)
        elif isinstance(node, ast.Import):
            used.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            used.update(alias.name for alias in node.names)
            if node.module:
                used.add(node.module.split(".")[0])
    for forbidden in (
        "read_raw_result",
        "subprocess",
        "materialize",
        "build_research_receipt",
        "build_research_finalization_marker",
        "hashlib",
        "SingleJobRunner",
        "ResultStore",
    ):
        assert forbidden not in used, forbidden


def test_the_wrapper_defines_no_full_run_configuration():
    """Section 16: the 6,000-comparison configuration is not in this module.

    Stage 7C has since written that configuration, in its own experiment module
    and its own YAML file. What stage 7B's rule protects is unchanged and is what
    is checked here: ``nbis_research.py`` certifies the route and knows nothing
    about SD300, so importing it can never start a run over the dataset.
    """
    repository = Path(__file__).resolve().parents[2]
    assert not (
        repository / "configs" / "algorithms" / "nbis_canonical500_full_v1.yaml"
    ).exists(), "an experiment is not an algorithm"

    # Over the code, not over the text: the module's docstring explains that the
    # 6,000 SD300 comparisons are stage 7C's, and a prose ban would be defeated
    # by explaining it.
    tree = ast.parse(Path(nbis_research.__file__).read_text(encoding="utf-8"))
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    literals = " ".join(
        node.value.lower()
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    )
    for forbidden in ("sd300", "prepset_", "run_4c59fa02a6ab", "6000"):
        assert forbidden not in literals, forbidden
