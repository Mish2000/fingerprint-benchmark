"""NBIS, plugged into the shared research engine.

Stage 7A moved the research orchestration into
:mod:`fpbench.experiments.algorithm_research`, which knows nothing about any
algorithm: it materialises a runtime bundle, defines a run, plans the
comparisons, executes them one at a time, audits, validates, gives the results an
identity, writes a receipt and a marker. Stage 7B is the first time that claim is
tested by something other than the algorithm it was extracted from.

What is left here is the part that *is* about NBIS. Four answers:

* how to build the adapter from a certified build directory;
* how to build it again, pinned to a materialised bundle;
* which three files have to be pinned;
* which recorded failures are NBIS declining a print rather than the harness
  breaking.

They are assembled into one
:class:`~fpbench.experiments.research_integration.ResearchAdapterIntegration` and
handed to the engine. There is no orchestration in this module: no job loop, no
raw results opened, no subprocess, no runtime bundle built by hand, no receipt,
no finalization marker and no digest computed here. A structural test says so,
because "I did not add one" is not evidence (spec section 39).

**No SD300 run is defined here.** Stage 7B certifies the route; the 6,000
comparisons are stage 7C's, and the configuration for them is deliberately
absent — a wrapper that already knew how to start the real run would make
starting it an accident (spec section 16).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from fpbench.adapters.base import FingerprintAlgorithmAdapter
from fpbench.adapters.nbis.adapter import ADAPTER_ID, NbisAdapter
from fpbench.adapters.nbis.build_manifest import (
    BUILD_MANIFEST_FILENAME,
    EXPECTED_NBIS_VERSION,
    NbisBuildManifestError,
    read_build_manifest,
    verify_against_repository,
    verify_build_manifest,
)
from fpbench.adapters.nbis.config import (
    BOZORTH3_ROLE,
    BUILD_MANIFEST_ROLE,
    MINDTCT_ROLE,
    PRIMARY_RUNTIME_ASSET_ROLE,
    RUNTIME_ASSET_ROLES,
    NbisConfig,
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
from fpbench.experiments.nbis_validation import (
    ExpectedInputSet,
    NbisValidationReport,
    validate_nbis_result_set,
)
from fpbench.experiments.research_integration import (
    DevelopmentAdapterRuntime,
    ResearchAdapterIntegration,
    ResearchValidationContext,
)

__all__ = [
    "nbis_research_integration",
    "INTEGRATION_ID",
    "NBIS_INTEGRATION_DIRECTORY",
    "BUILD_ROOT",
    "BUILD_DIRECTORY_ENV_VAR",
    "resolve_build_directory",
    "prepare_nbis_research_run",
    "execute_nbis_research_run",
    "inspect_nbis_research_experiment",
    "finalize_nbis_research_run",
]

#: This integration's own identity, distinct from the adapter's. A second way of
#: driving the same adapter — a different runtime layout, a container image —
#: would be a different integration and would say so.
INTEGRATION_ID = "nbis_mindtct_bozorth3_research_v1"

#: Where the lock, the patch series and the build scripts live. The manifest is
#: checked against all three before an adapter is built (spec section 12).
NBIS_INTEGRATION_DIRECTORY = REPOSITORY_ROOT / "integrations" / "nbis"

#: Where ``build.py`` puts certified builds.
BUILD_ROOT = REPOSITORY_ROOT / "build" / f"nbis-{EXPECTED_NBIS_VERSION}"

#: How an operator names the build to pin when several are present. A build id is
#: a digest over the sources, the patch series, the build script, the compiler and
#: the flags, so it is machine-specific by construction and cannot be committed.
BUILD_DIRECTORY_ENV_VAR = "FPBENCH_NBIS_BUILD_DIR"


# ------------------------------------------------------------- the integration


def nbis_research_integration(
    *, expected_input_set: ExpectedInputSet | None = None
) -> ResearchAdapterIntegration:
    """Everything the shared engine needs in order to run NBIS.

    A function rather than a module constant so that a caller gets a fresh,
    immutable record and cannot accidentally mutate a shared one — and so that
    this module's only job stays visible: assemble this, pass it in.

    Args:
        expected_input_set: Which materialised input set the experiment is
            entitled to have used, when it has one. Stage 7B passes nothing;
            stage 7C will pass ``SD300_CANONICAL500_INPUT_SET``.
    """

    def validate(context: ResearchValidationContext) -> NbisValidationReport:
        """NBIS's own reading of a finished run's stored results.

        Which failure codes are biometric outcomes and which mean broken
        infrastructure is an algorithm-specific judgement, which is exactly why
        the engine asks rather than deciding (docs/adr/0013).
        """
        return validate_nbis_result_set(
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
        create_development_runtime=_development_runtime,
        create_research_delegate=_research_delegate,
        validate_result_set=validate,
    )


def resolve_build_directory(
    override: object | None = None, *, build_root: Path | None = None
) -> Path:
    """Which certified build to pin, said out loud rather than guessed.

    In order: an explicit override, then ``FPBENCH_NBIS_BUILD_DIR``, then the one
    certified build under ``build/nbis-5.0.0/``. Two certified builds with no
    choice made is an error rather than a coin toss — picking the newest would
    mean a rebuild silently changed which executables a run was attributed to.

    Raises:
        ConfigurationError: no certified build, or more than one and no choice.
    """
    if override is not None:
        return Path(str(override)).resolve()
    from_environment = os.environ.get(BUILD_DIRECTORY_ENV_VAR)
    if from_environment:
        return Path(from_environment).resolve()

    root = Path(build_root or BUILD_ROOT)
    candidates = (
        sorted(
            path
            for path in root.iterdir()
            if path.is_dir() and (path / BUILD_MANIFEST_FILENAME).is_file()
        )
        if root.is_dir()
        else []
    )
    if not candidates:
        raise ConfigurationError(
            f"no certified NBIS build under {root.name}/. Build one with "
            "'python integrations/nbis/build.py build' and certify it with "
            "'... test', or set "
            f"{BUILD_DIRECTORY_ENV_VAR}"
        )
    if len(candidates) > 1:
        raise ConfigurationError(
            f"{len(candidates)} certified NBIS builds are present "
            f"({[path.name for path in candidates]}); name the one to pin with "
            f"{BUILD_DIRECTORY_ENV_VAR} rather than letting an ordering decide "
            "which executables a run is attributed to"
        )
    return candidates[0].resolve()


def _development_runtime(
    repository_root: Path,
    algorithm_config: Path,
    overrides: Mapping[str, object],
) -> DevelopmentAdapterRuntime:
    """The adapter as it exists after ``build.py test``, and the three files to pin.

    The build manifest is read and fully verified here — against the two
    executables, against the locked archives, and against this repository's patch
    series and build script — *before* an adapter exists. A manifest that does not
    hold up is a ``ResearchPreflightError`` and not an unavailable environment:
    there is no research reading of "we pinned an uncertified build"
    (spec section 12).
    """
    unknown = sorted(set(overrides) - {"build_directory"})
    if unknown:
        raise ConfigurationError(f"unknown nbis development overrides: {unknown}")

    directory = resolve_build_directory(overrides.get("build_directory"))
    config = NbisConfig(
        mindtct_executable=directory / "bin" / "mindtct",
        bozorth3_executable=directory / "bin" / "bozorth3",
        build_manifest=directory / BUILD_MANIFEST_FILENAME,
    )
    _require_certified(config, repository_root=Path(repository_root))
    return DevelopmentAdapterRuntime(
        adapter=NbisAdapter(config), assets=dict(config.runtime_assets())
    )


def _research_delegate(
    repository_root: Path,
    algorithm_config: Path,
    bundle: RuntimeBundleDefinition,
    asset_paths: Mapping[str, Path],
    software: SoftwareProvenance,
) -> FingerprintAlgorithmAdapter:
    """The same adapter, running only the pinned bytes.

    Built entirely from the bundle's own paths: this function never looks at a
    build directory, never resolves ``FPBENCH_NBIS_BUILD_DIR`` and never falls
    back to one. The pinned manifest is the manifest that gets read, and it is
    verified against the pinned executables before the adapter exists.

    Returns the plain NBIS adapter. The engine wraps it in ``ResearchModeAdapter``;
    doing that here as well would put the research environment in two places and
    let them disagree.
    """
    config = NbisConfig(
        mindtct_executable=Path(asset_paths[MINDTCT_ROLE]),
        bozorth3_executable=Path(asset_paths[BOZORTH3_ROLE]),
        build_manifest=Path(asset_paths[BUILD_MANIFEST_ROLE]),
        research_mode=True,
    )
    _require_certified(config, repository_root=Path(repository_root))
    _require_bundle_digests(config, bundle)
    return NbisAdapter(config)


def _require_certified(config: NbisConfig, *, repository_root: Path) -> None:
    """The build manifest describes these files, these sources and this repository."""
    try:
        manifest = read_build_manifest(config.build_manifest)
        verify_build_manifest(
            manifest,
            mindtct=config.mindtct_executable,
            bozorth3=config.bozorth3_executable,
        )
        verify_against_repository(
            manifest,
            integration_directory=Path(repository_root) / "integrations" / "nbis",
        )
    except NbisBuildManifestError as exc:
        raise ResearchPreflightError(
            f"the NBIS build is not certified for research use: {exc}"
        ) from exc


def _require_bundle_digests(
    config: NbisConfig, bundle: RuntimeBundleDefinition
) -> None:
    """The pinned files are the bundle's own, byte for byte.

    The bundle store already verifies itself; this is the other direction — that
    the adapter was handed the assets of *this* bundle and not, say, the build
    directory's copies of the same names (docs/adr/0018).
    """
    from fpbench.adapters.nbis.build_manifest import file_digest

    for role, path in sorted(config.runtime_assets().items()):
        asset = bundle.asset(role)
        digest, size = file_digest(Path(path))
        if digest != asset.sha256 or size != asset.size_bytes:
            raise ResearchPreflightError(
                f"the pinned {role!r} is not the file runtime bundle "
                f"{bundle.bundle_id} holds"
            )


# --------------------------------------------------------- experiment commands
#
# Four thin forwards. Each one supplies the NBIS integration and passes
# everything else through untouched; there is no orchestration here, and a
# structural test proves it (spec section 39).


def prepare_nbis_research_run(
    *,
    spec: AlgorithmResearchExperimentSpec,
    preparer_factory: PreparerFactory,
    workspace: Path,
    dataset_root: Path | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    build_directory: Path | None = None,
    expected_input_set: ExpectedInputSet | None = None,
) -> PreparedAlgorithmResearchRun:
    """Pin everything, check everything, and write the run, plan and binding."""
    return prepare_algorithm_research_run(
        spec=spec,
        integration=nbis_research_integration(expected_input_set=expected_input_set),
        preparer_factory=preparer_factory,
        workspace=Path(workspace),
        dataset_root=dataset_root,
        repository_root=repository_root,
        development_overrides=(
            {"build_directory": build_directory} if build_directory else {}
        ),
    )


def execute_nbis_research_run(
    *,
    spec: AlgorithmResearchExperimentSpec,
    preparer_factory: PreparerFactory,
    workspace: Path,
    dataset_root: Path | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
    max_new_jobs: int | None = None,
    expected_input_set: ExpectedInputSet | None = None,
) -> RunExecutionSummary:
    """Execute some or all of a prepared run, revalidating everything around it."""
    return execute_algorithm_research_run(
        spec=spec,
        integration=nbis_research_integration(expected_input_set=expected_input_set),
        preparer_factory=preparer_factory,
        workspace=Path(workspace),
        dataset_root=dataset_root,
        repository_root=repository_root,
        run_id=run_id,
        max_new_jobs=max_new_jobs,
    )


def inspect_nbis_research_experiment(
    *,
    spec: AlgorithmResearchExperimentSpec,
    preparer_factory: PreparerFactory,
    workspace: Path,
    dataset_root: Path | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
    expected_input_set: ExpectedInputSet | None = None,
) -> ResearchRunState:
    """Report how far along the evidence chain the run is. Never writes."""
    return inspect_algorithm_research_experiment(
        spec=spec,
        integration=nbis_research_integration(expected_input_set=expected_input_set),
        preparer_factory=preparer_factory,
        workspace=Path(workspace),
        dataset_root=dataset_root,
        repository_root=repository_root,
        run_id=run_id,
    )


def finalize_nbis_research_run(
    *,
    spec: AlgorithmResearchExperimentSpec,
    preparer_factory: PreparerFactory,
    workspace: Path,
    dataset_root: Path | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
    expected_input_set: ExpectedInputSet | None = None,
) -> ResearchReceipt:
    """Revalidate everything and publish one last immutable commit marker."""
    return finalize_algorithm_research_run(
        spec=spec,
        integration=nbis_research_integration(expected_input_set=expected_input_set),
        preparer_factory=preparer_factory,
        workspace=Path(workspace),
        dataset_root=dataset_root,
        repository_root=repository_root,
        run_id=run_id,
    )
