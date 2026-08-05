"""flx, plugged into the shared research engine.

Stage 7A moved the research orchestration into
:mod:`fpbench.experiments.algorithm_research`, which knows nothing about any
algorithm: it materialises a runtime bundle, defines a run, plans the
comparisons, executes them one at a time, audits, validates, gives the results an
identity, writes a receipt and a marker.  Stage 7B tested that claim with a
second algorithm.  Stage 8C tests it with a third that is nothing like the first
two — a persistent Python worker holding an 875 MB checkpoint, returning a
Decimal — and the engine is unchanged.

What is left here is the part that *is* about flx.  Four answers:

* how to build the adapter from the repository's own files and a local bundle;
* how to build it again, pinned to a materialised bundle;
* which three files have to be pinned;
* which recorded failures are flx declining a print rather than the harness
  breaking.

They are assembled into one
:class:`~fpbench.experiments.research_integration.ResearchAdapterIntegration` and
handed to the engine.  There is no orchestration in this module: no job loop, no
raw results opened, no subprocess started, no runtime bundle built by hand, no
receipt, no finalization marker and no digest computed here beyond proving the
pinned bytes are the repository's own.

**No SD300 run is defined here.**  Stage 8B qualified the route; the 6,000
comparisons are Stage 8C's, and the configuration for them lives in
:mod:`fpbench.experiments.flx_canonical500_full` — a wrapper that already knew
how to start the real run would make starting it an accident.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Mapping

from fpbench.adapters.base import FingerprintAlgorithmAdapter
from fpbench.experiments.flx_adapter import ADAPTER_ID, FlxAdapter
from fpbench.experiments.flx_adapter import (
    PRIMARY_RUNTIME_ASSET_ROLE,
    RUNTIME_ASSET_ROLES,
    RUNTIME_LOCK_ROLE,
    RUNTIME_POLICY_ROLE,
    WORKER_SCRIPT_ROLE,
    FlxConfig,
)
from fpbench.core.errors import ConfigurationError, ResearchPreflightError
from fpbench.core.provenance_models import SoftwareProvenance
from fpbench.core.research_models import ResearchReceipt, ResearchRunState
from fpbench.core.runtime_models import RuntimeBundleDefinition
from fpbench.experiments.algorithm_research import (
    REPOSITORY_ROOT,
    AlgorithmResearchExperimentSpec,
    PreparedAlgorithmResearchRun,
    PreparerFactory,
    RunExecutionSummary,
    execute_algorithm_research_run,
    finalize_algorithm_research_run,
    inspect_algorithm_research_experiment,
    prepare_algorithm_research_run,
)
from fpbench.experiments.flx_validation import (
    ExpectedInputSet,
    FlxValidationReport,
    validate_flx_result_set,
)
from fpbench.experiments.research_integration import (
    DevelopmentAdapterRuntime,
    ResearchAdapterIntegration,
    ResearchValidationContext,
)
from fpbench.flx.artifacts import FlxRuntimeBundle

__all__ = [
    "INTEGRATION_ID",
    "BUNDLE_ROOT_ENV_VAR",
    "WORKER_SCRIPT",
    "RUNTIME_LOCK_CONFIG",
    "RUNTIME_POLICY_CONFIG",
    "flx_research_integration",
    "resolve_bundle_root",
    "prepare_flx_research_run",
    "execute_flx_research_run",
    "inspect_flx_research_experiment",
    "finalize_flx_research_run",
]

#: This integration's own identity, distinct from the adapter's. A second way of
#: driving the same adapter — a GPU runtime profile, a container image — would be
#: a different integration and would say so.
INTEGRATION_ID = "flx_deepprint_texminu_research_v1"

#: How an operator names the 2.06 GB runtime bundle. It cannot be committed and
#: it is not searched for: an explicit path, then this variable, then the
#: default cache location, and nothing else.
BUNDLE_ROOT_ENV_VAR = "FPBENCH_FLX_BUNDLE"

#: The three repository-owned files a run pins. Everything the checkpoint and
#: the source archive contribute is pinned by frozen digest instead and
#: re-verified before every model load (docs/adr/0077).
WORKER_SCRIPT = REPOSITORY_ROOT / "integrations" / "flx" / "worker" / "flx_worker.py"
RUNTIME_LOCK_CONFIG = REPOSITORY_ROOT / "configs" / "flx" / "flx_runtime_lock_v1.txt"
RUNTIME_POLICY_CONFIG = (
    REPOSITORY_ROOT / "configs" / "flx" / "stage8b_flx_runtime_policy_v1.yaml"
)


# ------------------------------------------------------------- the integration


def flx_research_integration(
    *,
    bundle_root: Path | None = None,
    expected_input_set: ExpectedInputSet | None = None,
) -> ResearchAdapterIntegration:
    """Everything the shared engine needs in order to run flx.

    A function rather than a module constant so that a caller gets a fresh,
    immutable record and cannot accidentally mutate a shared one — and so that
    this module's only job stays visible: assemble this, pass it in.

    Args:
        bundle_root: Where the pinned 2.06 GB runtime lives. Resolved once here
            so that the development runtime and the pinned research delegate
            cannot end up addressing two different bundles.
        expected_input_set: Which materialised input set the experiment is
            entitled to have used. Stage 8C passes
            ``SD300_CANONICAL500_INPUT_SET``.
    """
    resolved_root = resolve_bundle_root(bundle_root)

    def development(
        repository_root: Path,
        algorithm_config: Path,
        overrides: Mapping[str, object],
    ) -> DevelopmentAdapterRuntime:
        return _development_runtime(
            repository_root, algorithm_config, overrides, default_root=resolved_root
        )

    def delegate(
        repository_root: Path,
        algorithm_config: Path,
        bundle: RuntimeBundleDefinition,
        asset_paths: Mapping[str, Path],
        software: SoftwareProvenance,
    ) -> FingerprintAlgorithmAdapter:
        return _research_delegate(
            repository_root,
            algorithm_config,
            bundle,
            asset_paths,
            software,
            bundle_root=resolved_root,
        )

    def validate(context: ResearchValidationContext) -> FlxValidationReport:
        """flx's own reading of a finished run's stored results.

        Which failure codes are biometric outcomes and which mean broken
        infrastructure is an algorithm-specific judgement, which is exactly why
        the engine asks rather than deciding (docs/adr/0013).
        """
        return validate_flx_result_set(
            run=context.run,
            plan=context.plan,
            pairs=context.pairs,
            images=context.images,
            result_store=context.result_store,
            runtime_reference=context.runtime_reference,
            preparation=context.preparation,
            expected_input_set=expected_input_set,
        )

    return ResearchAdapterIntegration(
        integration_id=INTEGRATION_ID,
        adapter_id=ADAPTER_ID,
        runtime_asset_roles=RUNTIME_ASSET_ROLES,
        primary_runtime_asset_role=PRIMARY_RUNTIME_ASSET_ROLE,
        create_development_runtime=development,
        create_research_delegate=delegate,
        validate_result_set=validate,
    )


def resolve_bundle_root(override: object | None = None) -> Path:
    """Which pinned runtime to use, said out loud rather than guessed.

    In order: an explicit path, then ``FPBENCH_FLX_BUNDLE``, then the default
    cache location. There is deliberately no scan of a parent directory and no
    "newest bundle": a second bundle appearing on a machine must not silently
    change which weights 6,000 results are attributed to.
    """
    if override is not None:
        return Path(str(override)).expanduser().resolve()
    from_environment = os.environ.get(BUNDLE_ROOT_ENV_VAR)
    if from_environment:
        return Path(from_environment).expanduser().resolve()
    return Path(FlxRuntimeBundle.from_environment().root).expanduser().resolve()


def _development_runtime(
    repository_root: Path,
    algorithm_config: Path,
    overrides: Mapping[str, object],
    *,
    default_root: Path,
) -> DevelopmentAdapterRuntime:
    """The route as it exists on this machine, and the three files to pin.

    The adapter is built from the repository's own worker script, lock and
    policy — the files a reviewer reads — and from the bundle root the operator
    named. Its environment check loads the checkpoint, so a truncated artifact
    or a torch that no longer matches the lock stops everything here rather than
    six thousand times later.
    """
    unknown = sorted(set(overrides) - {"bundle_root"})
    if unknown:
        raise ConfigurationError(f"unknown flx development overrides: {unknown}")

    root = Path(repository_root)
    config = FlxConfig(
        bundle_root=resolve_bundle_root(overrides.get("bundle_root") or default_root),
        worker_script=_repository_file(root, WORKER_SCRIPT, "worker script"),
        runtime_lock=_repository_file(root, RUNTIME_LOCK_CONFIG, "runtime lock"),
        runtime_policy=_repository_file(root, RUNTIME_POLICY_CONFIG, "runtime policy"),
        research_mode=False,
    )
    return DevelopmentAdapterRuntime(
        adapter=FlxAdapter(config), assets=dict(config.runtime_assets())
    )


def _research_delegate(
    repository_root: Path,
    algorithm_config: Path,
    bundle: RuntimeBundleDefinition,
    asset_paths: Mapping[str, Path],
    software: SoftwareProvenance,
    *,
    bundle_root: Path,
) -> FingerprintAlgorithmAdapter:
    """The same route, running only bytes this run pinned.

    The lock and the policy are read from the bundle's own copies, so a run is
    literally driven by the deadlines and the dependency set it recorded.

    The worker script is handled differently and deliberately so.  Stage 8B's
    :class:`~fpbench.flx.integration.FlxLearnedFingerprintIntegration` starts the
    script at its repository path, and Stage 8C does not reach into a qualified
    route to redirect it.  Instead the pinned copy is proved byte-identical to
    the file that will execute, which establishes the same fact — the bytes in
    this run's bundle are the bytes that ran — without modifying anything the
    Stage 8B qualification rests on.  A repository script that differs from the
    pinned one is a hard failure, not a warning.

    Returns the plain flx adapter. The engine wraps it in
    ``ResearchModeAdapter``; doing that here as well would put the research
    environment in two places and let them disagree.
    """
    root = Path(repository_root)
    _require_bundle_digests(bundle, asset_paths)
    _require_pinned_worker_script(root, Path(asset_paths[WORKER_SCRIPT_ROLE]))
    config = FlxConfig(
        bundle_root=resolve_bundle_root(bundle_root),
        worker_script=Path(asset_paths[WORKER_SCRIPT_ROLE]).resolve(),
        runtime_lock=Path(asset_paths[RUNTIME_LOCK_ROLE]).resolve(),
        runtime_policy=Path(asset_paths[RUNTIME_POLICY_ROLE]).resolve(),
        research_mode=True,
    )
    return FlxAdapter(config)


def _repository_file(repository_root: Path, expected: Path, what: str) -> Path:
    """One committed file, at the path this integration names and nowhere else."""
    relative = expected.relative_to(REPOSITORY_ROOT)
    path = (Path(repository_root) / relative).resolve()
    if not path.is_file():
        raise ResearchPreflightError(
            f"the flx {what} is missing: {relative.as_posix()}"
        )
    if path.is_symlink():
        raise ResearchPreflightError(
            f"the flx {what} may not be a link: {relative.as_posix()}"
        )
    return path


def _require_bundle_digests(
    bundle: RuntimeBundleDefinition, asset_paths: Mapping[str, Path]
) -> None:
    """The pinned files are the bundle's own, byte for byte.

    The bundle store already verifies itself; this is the other direction — that
    the adapter was handed the assets of *this* bundle and not, say, the
    repository's copies of the same names (docs/adr/0018).
    """
    missing = sorted(set(RUNTIME_ASSET_ROLES) - set(asset_paths))
    if missing:
        raise ResearchPreflightError(
            f"runtime bundle {bundle.bundle_id} supplied no path for {missing}"
        )
    for role in RUNTIME_ASSET_ROLES:
        asset = bundle.asset(role)
        path = Path(asset_paths[role])
        digest, size = _file_digest(path)
        if digest != asset.sha256 or size != asset.size_bytes:
            raise ResearchPreflightError(
                f"the pinned {role!r} is not the file runtime bundle "
                f"{bundle.bundle_id} holds"
            )


def _require_pinned_worker_script(repository_root: Path, pinned: Path) -> None:
    """The script that will execute is the script this run pinned.

    Byte identity, not path identity. It is the whole reason the worker script
    is a pinned role at all (docs/adr/0077).
    """
    executed = _repository_file(repository_root, WORKER_SCRIPT, "worker script")
    pinned_digest, _ = _file_digest(pinned)
    executed_digest, _ = _file_digest(executed)
    if pinned_digest != executed_digest:
        raise ResearchPreflightError(
            "the worker script pinned into this run's runtime bundle "
            f"({pinned_digest[:12]}...) is not the script that would execute "
            f"({executed_digest[:12]}...). A run may not be resumed under a "
            "different worker (docs/adr/0017, docs/adr/0077)"
        )


def _file_digest(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    try:
        with Path(path).open("rb") as stream:
            for block in iter(lambda: stream.read(1 << 20), b""):
                digest.update(block)
                size += len(block)
    except OSError as exc:
        raise ResearchPreflightError(f"cannot hash pinned runtime asset: {exc}") from exc
    return digest.hexdigest(), size


# --------------------------------------------------------- experiment commands
#
# Four thin forwards. Each one supplies the flx integration and passes everything
# else through untouched; there is no orchestration here, and a structural test
# proves it.


def prepare_flx_research_run(
    *,
    spec: AlgorithmResearchExperimentSpec,
    preparer_factory: PreparerFactory,
    workspace: Path,
    dataset_root: Path | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    bundle_root: Path | None = None,
    expected_input_set: ExpectedInputSet | None = None,
) -> PreparedAlgorithmResearchRun:
    """Pin everything, check everything, and write the run, plan and binding."""
    return prepare_algorithm_research_run(
        spec=spec,
        integration=flx_research_integration(
            bundle_root=bundle_root, expected_input_set=expected_input_set
        ),
        preparer_factory=preparer_factory,
        workspace=Path(workspace),
        dataset_root=dataset_root,
        repository_root=repository_root,
        development_overrides={"bundle_root": bundle_root} if bundle_root else {},
    )


def execute_flx_research_run(
    *,
    spec: AlgorithmResearchExperimentSpec,
    preparer_factory: PreparerFactory,
    workspace: Path,
    dataset_root: Path | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
    max_new_jobs: int | None = None,
    bundle_root: Path | None = None,
    expected_input_set: ExpectedInputSet | None = None,
) -> RunExecutionSummary:
    """Execute some or all of a prepared run, revalidating everything around it."""
    return execute_algorithm_research_run(
        spec=spec,
        integration=flx_research_integration(
            bundle_root=bundle_root, expected_input_set=expected_input_set
        ),
        preparer_factory=preparer_factory,
        workspace=Path(workspace),
        dataset_root=dataset_root,
        repository_root=repository_root,
        run_id=run_id,
        max_new_jobs=max_new_jobs,
    )


def inspect_flx_research_experiment(
    *,
    spec: AlgorithmResearchExperimentSpec,
    preparer_factory: PreparerFactory,
    workspace: Path,
    dataset_root: Path | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
    bundle_root: Path | None = None,
    expected_input_set: ExpectedInputSet | None = None,
) -> ResearchRunState:
    """Report how far along the evidence chain the run is. Never writes."""
    return inspect_algorithm_research_experiment(
        spec=spec,
        integration=flx_research_integration(
            bundle_root=bundle_root, expected_input_set=expected_input_set
        ),
        preparer_factory=preparer_factory,
        workspace=Path(workspace),
        dataset_root=dataset_root,
        repository_root=repository_root,
        run_id=run_id,
    )


def finalize_flx_research_run(
    *,
    spec: AlgorithmResearchExperimentSpec,
    preparer_factory: PreparerFactory,
    workspace: Path,
    dataset_root: Path | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
    bundle_root: Path | None = None,
    expected_input_set: ExpectedInputSet | None = None,
) -> ResearchReceipt:
    """Revalidate everything and publish one last immutable commit marker."""
    return finalize_algorithm_research_run(
        spec=spec,
        integration=flx_research_integration(
            bundle_root=bundle_root, expected_input_set=expected_input_set
        ),
        preparer_factory=preparer_factory,
        workspace=Path(workspace),
        dataset_root=dataset_root,
        repository_root=repository_root,
        run_id=run_id,
    )
