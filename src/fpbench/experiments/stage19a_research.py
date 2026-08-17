"""MINDTCT + OpenAFIS, plugged into the shared research engine.

Stage 7A moved the research orchestration into
:mod:`fpbench.experiments.algorithm_research`, which knows nothing about any
algorithm: it materialises a runtime bundle, defines a run, plans the
comparisons, executes them one at a time, audits, validates, gives the results an
identity, writes a receipt and a marker. This module supplies only the part that
is about *this* route.

Four answers, and no orchestration:

* how to build the adapter from a certified NBIS build and a built bridge;
* how to build it again, pinned to a materialised bundle;
* which three files have to be pinned;
* which recorded failures are the algorithm declining a print rather than the
  harness breaking.

**Three runtime assets, not four.** MINDTCT, the build manifest that says it is
the certified MINDTCT, and the OpenAFIS bridge. BOZORTH3 is read during
verification — the manifest describes both executables and half a verification is
not one — but it is not pinned as a runtime asset, because it plays no part in
producing an ``nbis_mindtct_openafis`` score.

**The extractor is deliberately the same file Algorithm 2 runs.** Not an
equivalent build, not a rebuild: the same certified build directory, resolved the
same way. That is what makes the pair of algorithms a controlled matcher
comparison rather than two loosely related pipelines (docs/adr/0135).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from fpbench.adapters.base import FingerprintAlgorithmAdapter
from fpbench.adapters.nbis.build_manifest import (
    BUILD_MANIFEST_FILENAME,
    EXPECTED_NBIS_VERSION,
)
from fpbench.adapters.openafis.adapter import ADAPTER_ID, OpenAfisAdapter
from fpbench.adapters.openafis.config import (
    BUILD_MANIFEST_ROLE,
    MINDTCT_ROLE,
    OPENAFIS_BRIDGE_ROLE,
    PRIMARY_RUNTIME_ASSET_ROLE,
    RUNTIME_ASSET_ROLES,
    OpenAfisConfig,
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
from fpbench.experiments.nbis_research import require_certified_build, resolve_build_directory
from fpbench.experiments.research_integration import (
    DevelopmentAdapterRuntime,
    ResearchAdapterIntegration,
    ResearchValidationContext,
)
from fpbench.experiments.stage19a_validation import (
    ExpectedInputSet,
    Stage19AValidationReport,
    validate_stage19a_result_set,
)

__all__ = [
    "INTEGRATION_ID",
    "BRIDGE_ENV_VAR",
    "RUNTIME_ASSET_ROLES",
    "PRIMARY_RUNTIME_ASSET_ROLE",
    "resolve_bridge",
    "stage19a_research_integration",
    "prepare_stage19a_research_run",
    "execute_stage19a_research_run",
    "inspect_stage19a_research_experiment",
    "finalize_stage19a_research_run",
]

INTEGRATION_ID = "nbis_mindtct_openafis_research_v1"

#: Where the built OpenAFIS bridge is. There is no default path and no PATH
#: lookup: the bridge is compiled from a pinned upstream tree on the machine that
#: runs it, so its location is a fact about that machine.
BRIDGE_ENV_VAR = "FPBENCH_OPENAFIS_BRIDGE"


def resolve_bridge(override: object | None = None) -> Path:
    """Which bridge binary to pin, said out loud rather than guessed.

    Raises:
        ConfigurationError: neither an override nor the environment variable.
    """
    if override is not None:
        return Path(str(override)).resolve()
    from_environment = os.environ.get(BRIDGE_ENV_VAR, "").strip()
    if from_environment:
        return Path(from_environment).resolve()
    raise ConfigurationError(
        f"no OpenAFIS bridge named. Build it with 'make -C integrations/openafis "
        f"FPBENCH_OPENAFIS_SOURCE=...' and set {BRIDGE_ENV_VAR} to the binary"
    )


# ------------------------------------------------------------- the integration


def stage19a_research_integration(
    *, expected_input_set: ExpectedInputSet | None = None
) -> ResearchAdapterIntegration:
    """Everything the shared engine needs in order to run Algorithm 5."""

    def development(
        repository_root: Path, algorithm_config: Path, overrides: Mapping[str, object]
    ) -> DevelopmentAdapterRuntime:
        return _development_runtime(repository_root, overrides)

    def delegate(
        repository_root: Path,
        algorithm_config: Path,
        bundle: RuntimeBundleDefinition,
        asset_paths: Mapping[str, Path],
        software: SoftwareProvenance,
    ) -> FingerprintAlgorithmAdapter:
        return _research_delegate(repository_root, bundle, asset_paths)

    def validate(context: ResearchValidationContext) -> Stage19AValidationReport:
        """This route's own reading of a finished run's stored results.

        Which failure codes are the algorithm declining a print and which mean a
        broken machine is an algorithm-specific judgement, which is why the engine
        asks rather than deciding (docs/adr/0013).
        """
        return validate_stage19a_result_set(
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


def _config_from_build(directory: Path, bridge: Path, *, research_mode: bool = False) -> OpenAfisConfig:
    return OpenAfisConfig(
        mindtct_executable=directory / "bin" / "mindtct",
        bozorth3_executable=directory / "bin" / "bozorth3",
        build_manifest=directory / BUILD_MANIFEST_FILENAME,
        openafis_bridge=bridge,
        research_mode=research_mode,
    )


def _development_runtime(
    repository_root: Path, overrides: Mapping[str, object]
) -> DevelopmentAdapterRuntime:
    """The adapter as it exists after ``build.py test`` plus a built bridge.

    The build manifest is fully verified here — against both executables, the
    locked archives, and this repository's patch series and build script —
    *before* an adapter exists. Reused from the NBIS route rather than
    reimplemented: it is the same certified build, and a second copy of the check
    could drift from the first.
    """
    unknown = sorted(set(overrides) - {"build_directory", "openafis_bridge"})
    if unknown:
        raise ConfigurationError(f"unknown stage19a development overrides: {unknown}")

    directory = resolve_build_directory(overrides.get("build_directory"))
    bridge = resolve_bridge(overrides.get("openafis_bridge"))
    config = _config_from_build(directory, bridge)

    # The NBIS half, checked by the NBIS route's own verifier.
    from fpbench.adapters.nbis.config import NbisConfig

    require_certified_build(
        NbisConfig(
            mindtct_executable=config.mindtct_executable,
            bozorth3_executable=config.bozorth3_executable,
            build_manifest=config.build_manifest,
        ),
        repository_root=Path(repository_root),
    )
    if not bridge.is_file():
        raise ResearchPreflightError(
            "the OpenAFIS bridge named is not a file; a run cannot be attributed to a matcher that is not there"
        )
    return DevelopmentAdapterRuntime(
        adapter=OpenAfisAdapter(config), assets=dict(config.runtime_assets())
    )


def _research_delegate(
    repository_root: Path, bundle: RuntimeBundleDefinition, asset_paths: Mapping[str, Path]
) -> FingerprintAlgorithmAdapter:
    """The same adapter, running only the pinned bytes.

    Built entirely from the bundle's own paths: this function never resolves a
    build directory or the bridge environment variable, and never falls back to
    one. Returns the plain adapter — the engine wraps it in ``ResearchModeAdapter``,
    and doing that here as well would put the research environment in two places.
    """
    from fpbench.adapters.nbis.config import NbisConfig

    mindtct = Path(asset_paths[MINDTCT_ROLE])
    manifest = Path(asset_paths[BUILD_MANIFEST_ROLE])
    bridge = Path(asset_paths[OPENAFIS_BRIDGE_ROLE])

    # The manifest describes both executables, so bozorth3 is read from beside
    # the pinned mindtct in order to verify it. It is not a runtime asset.
    config = OpenAfisConfig(
        mindtct_executable=mindtct,
        bozorth3_executable=mindtct.parent / "bozorth3",
        build_manifest=manifest,
        openafis_bridge=bridge,
        research_mode=True,
    )
    require_certified_build(
        NbisConfig(
            mindtct_executable=config.mindtct_executable,
            bozorth3_executable=config.bozorth3_executable,
            build_manifest=config.build_manifest,
        ),
        repository_root=Path(repository_root),
    )
    _require_bundle_digests(config, bundle)
    return OpenAfisAdapter(config)


def _require_bundle_digests(config: OpenAfisConfig, bundle: RuntimeBundleDefinition) -> None:
    """Every pinned asset is byte-identical to what the bundle recorded."""
    from fpbench.third_party.artifacts import file_sha256

    recorded = {asset.role: asset.sha256 for asset in bundle.assets}
    for role, path in config.runtime_assets().items():
        expected = recorded.get(role)
        if expected is None:
            raise ResearchPreflightError(f"the runtime bundle records no asset for role {role!r}")
        actual = file_sha256(Path(path))
        if actual != expected:
            raise ResearchPreflightError(
                f"the pinned {role} is not the file the bundle recorded"
            )


# ------------------------------------------------------ the four engine verbs


def prepare_stage19a_research_run(
    spec: AlgorithmResearchExperimentSpec,
    *,
    preparer_factory: PreparerFactory | None = None,
    expected_input_set: ExpectedInputSet | None = None,
) -> PreparedAlgorithmResearchRun:
    return prepare_algorithm_research_run(
        spec,
        integration=stage19a_research_integration(expected_input_set=expected_input_set),
        preparer_factory=preparer_factory,
    )


def execute_stage19a_research_run(
    prepared: PreparedAlgorithmResearchRun,
    *,
    expected_input_set: ExpectedInputSet | None = None,
) -> RunExecutionSummary:
    return execute_algorithm_research_run(
        prepared,
        integration=stage19a_research_integration(expected_input_set=expected_input_set),
    )


def inspect_stage19a_research_experiment(
    spec: AlgorithmResearchExperimentSpec,
    *,
    expected_input_set: ExpectedInputSet | None = None,
) -> ResearchRunState:
    return inspect_algorithm_research_experiment(
        spec,
        integration=stage19a_research_integration(expected_input_set=expected_input_set),
    )


def finalize_stage19a_research_run(
    spec: AlgorithmResearchExperimentSpec,
    *,
    expected_input_set: ExpectedInputSet | None = None,
) -> ResearchReceipt:
    return finalize_algorithm_research_run(
        spec,
        integration=stage19a_research_integration(expected_input_set=expected_input_set),
    )
