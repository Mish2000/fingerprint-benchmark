"""SourceAFIS, plugged into the shared research engine.

Stage 6A extracted one orchestration from two experiments, so that the native and
canonical runs could not differ in anything except how their images were
prepared. Stage 7A extracts it one step further: the orchestration is now in
:mod:`fpbench.experiments.algorithm_research` and knows nothing about SourceAFIS,
Java or jars. What is left here is the part that *is* about SourceAFIS.

Which is: how to build the adapter from the Maven output, how to build it again
pinned to a materialised bundle, which file has to be pinned, and which recorded
failures are SourceAFIS declining a print rather than the harness breaking. Four
answers, assembled into one
:class:`~fpbench.experiments.research_integration.ResearchAdapterIntegration` and
handed to the engine.

Nothing about this experiment's identity changed when the code moved — again.
Same execution profiles, same preparer ids, same descriptor, same 6,000 pairs,
therefore the same ``run_fingerprint``: ``run_7ac1cecc0bb3`` and
``run_4c59fa02a6ab`` and everything derived from them are untouched.

The old names are re-exported below and keep working. ``ResearchExperimentSpec``
*is* ``AlgorithmResearchExperimentSpec`` — an alias, not a wrapper, so a spec
built through either name is the same object to the engine.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from fpbench.adapters.base import FingerprintAlgorithmAdapter
from fpbench.adapters.sourceafis_java.adapter import ADAPTER_ID, SourceAfisJavaAdapter
from fpbench.adapters.sourceafis_java.config import (
    BRIDGE_JAR_ROLE,
    SourceAfisJavaConfig,
)
from fpbench.core.errors import ConfigurationError
from fpbench.core.provenance_models import SoftwareProvenance
from fpbench.core.research_models import ResearchReceipt, ResearchRunState
from fpbench.core.runtime_models import RuntimeBundleDefinition
from fpbench.experiments.algorithm_research import (
    REPOSITORY_ROOT,
    AlgorithmResearchExperimentSpec,
    PreparedAlgorithmResearchRun,
    PreparerFactory,
    RunExecutionSummary,
    capture_research_provenance,
    execute_algorithm_research_run,
    finalize_algorithm_research_run,
    inspect_algorithm_research_experiment,
    prepare_algorithm_research_run,
    read_run_pointer,
    timing_summary,
)
from fpbench.experiments.research_integration import (
    DevelopmentAdapterRuntime,
    ResearchAdapterIntegration,
    ResearchValidationContext,
)
from fpbench.experiments.sourceafis_validation import (
    CanonicalPreparationExpectations,
    SourceAfisValidationReport,
    validate_sourceafis_result_set,
)

__all__ = [
    "sourceafis_research_integration",
    "INTEGRATION_ID",
    # Compatibility names. Same objects, older spellings.
    "ResearchExperimentSpec",
    "PreparedResearchRun",
    "PreparerFactory",
    "capture_research_provenance",
    "prepare_research_run",
    "execute_research_run",
    "inspect_research_experiment",
    "finalize_research_run",
    "read_run_pointer",
    "timing_summary",
    "REPOSITORY_ROOT",
]

#: This integration's own identity, distinct from the adapter's. A second way of
#: driving the same adapter — a different runtime layout, say — would be a
#: different integration and would say so.
INTEGRATION_ID = "sourceafis_java_research_v1"

#: The old names, aliased rather than wrapped: a spec built through either one is
#: the same class, so ``isinstance`` and equality behave as they always did.
ResearchExperimentSpec = AlgorithmResearchExperimentSpec
PreparedResearchRun = PreparedAlgorithmResearchRun


# ------------------------------------------------------------- the integration


def sourceafis_research_integration() -> ResearchAdapterIntegration:
    """Everything the shared engine needs in order to run SourceAFIS.

    A function rather than a module constant so that a caller gets a fresh,
    immutable record and cannot accidentally mutate a shared one — and so that
    the wrapper's only job stays visible: assemble this, pass it in.
    """
    return ResearchAdapterIntegration(
        integration_id=INTEGRATION_ID,
        adapter_id=ADAPTER_ID,
        runtime_asset_roles=(BRIDGE_JAR_ROLE,),
        primary_runtime_asset_role=BRIDGE_JAR_ROLE,
        create_development_runtime=_development_runtime,
        create_research_delegate=_research_delegate,
        validate_result_set=_validate_result_set,
    )


def _development_runtime(
    repository_root: Path,
    algorithm_config: Path,
    overrides: Mapping[str, object],
) -> DevelopmentAdapterRuntime:
    """The adapter as it exists after ``mvnw package``, and the jar to pin.

    ``build_jar`` is the one override this algorithm has. A Maven shaded jar is
    not byte-reproducible, so pinning the exact executable an earlier run used
    means naming the file rather than rebuilding it — and that is a fact about
    Maven, which is why it arrives as an override instead of as a parameter on
    the shared engine (spec section 13).
    """
    unknown = sorted(set(overrides) - {"build_jar"})
    if unknown:
        raise ConfigurationError(
            f"unknown sourceafis development overrides: {unknown}"
        )
    settings: dict[str, Any] = {"project_root": Path(repository_root)}
    build_jar = overrides.get("build_jar")
    if build_jar is not None:
        settings["bridge_jar"] = Path(str(build_jar))
    config = SourceAfisJavaConfig(**settings)
    return DevelopmentAdapterRuntime(
        adapter=SourceAfisJavaAdapter(config),
        assets={BRIDGE_JAR_ROLE: config.bridge_jar},
    )


def _research_delegate(
    repository_root: Path,
    algorithm_config: Path,
    bundle: RuntimeBundleDefinition,
    asset_paths: Mapping[str, Path],
    software: SoftwareProvenance,
) -> FingerprintAlgorithmAdapter:
    """The same adapter, refusing to run anything but the pinned bytes.

    Returns the plain SourceAFIS adapter. The engine wraps it in
    ``ResearchModeAdapter``; doing that here as well would put the research
    environment in two places and let them disagree.
    """
    asset = bundle.asset(BRIDGE_JAR_ROLE)
    pinned = SourceAfisJavaConfig(project_root=Path(repository_root)).pinned_to(
        bridge_jar=Path(asset_paths[BRIDGE_JAR_ROLE]),
        runtime_bundle_id=bundle.bundle_id,
        runtime_bundle_fingerprint=bundle.bundle_fingerprint,
        expected_bridge_jar_sha256=asset.sha256,
        expected_bridge_jar_size=asset.size_bytes,
        fpbench_source_revision=software.source_revision,
    )
    return SourceAfisJavaAdapter(pinned)


def _validate_result_set(
    context: ResearchValidationContext,
) -> SourceAfisValidationReport:
    """SourceAFIS's own reading of a finished run's stored results.

    Which failure codes are biometric outcomes and which mean broken
    infrastructure is an algorithm-specific judgement, which is exactly why the
    engine asks rather than deciding (docs/adr/0013, spec section 24).
    """
    return validate_sourceafis_result_set(
        run=context.run,
        plan=context.plan,
        pairs=context.pairs,
        images=context.images,
        result_store=context.result_store,
        runtime_reference=context.runtime_reference,
        preparation=context.preparation,
    )


# ----------------------------------------------------- compatibility commands
#
# The four commands under their stage 4B names. Each one supplies the SourceAFIS
# integration and forwards; there is no orchestration here, and a structural test
# proves it (spec section 61).


def prepare_research_run(
    *,
    spec: ResearchExperimentSpec,
    preparer_factory: PreparerFactory,
    workspace: Path,
    dataset_root: Path | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    build_jar: Path | None = None,
) -> PreparedResearchRun:
    """Pin everything, check everything, and write the run, plan and binding."""
    return prepare_algorithm_research_run(
        spec=spec,
        integration=sourceafis_research_integration(),
        preparer_factory=preparer_factory,
        workspace=Path(workspace),
        dataset_root=dataset_root,
        repository_root=repository_root,
        development_overrides=({"build_jar": build_jar} if build_jar else {}),
    )


def execute_research_run(
    *,
    spec: ResearchExperimentSpec,
    preparer_factory: PreparerFactory,
    workspace: Path,
    dataset_root: Path | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
    max_new_jobs: int | None = None,
) -> RunExecutionSummary:
    """Execute some or all of a prepared run, revalidating everything around it."""
    return execute_algorithm_research_run(
        spec=spec,
        integration=sourceafis_research_integration(),
        preparer_factory=preparer_factory,
        workspace=Path(workspace),
        dataset_root=dataset_root,
        repository_root=repository_root,
        run_id=run_id,
        max_new_jobs=max_new_jobs,
    )


def inspect_research_experiment(
    *,
    spec: ResearchExperimentSpec,
    preparer_factory: PreparerFactory,
    workspace: Path,
    dataset_root: Path | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
) -> ResearchRunState:
    """Report how far along the evidence chain the run is. Never writes."""
    return inspect_algorithm_research_experiment(
        spec=spec,
        integration=sourceafis_research_integration(),
        preparer_factory=preparer_factory,
        workspace=Path(workspace),
        dataset_root=dataset_root,
        repository_root=repository_root,
        run_id=run_id,
    )


def finalize_research_run(
    *,
    spec: ResearchExperimentSpec,
    preparer_factory: PreparerFactory,
    workspace: Path,
    dataset_root: Path | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
) -> ResearchReceipt:
    """Revalidate everything and publish one last immutable commit marker."""
    return finalize_algorithm_research_run(
        spec=spec,
        integration=sourceafis_research_integration(),
        preparer_factory=preparer_factory,
        workspace=Path(workspace),
        dataset_root=dataset_root,
        repository_root=repository_root,
        run_id=run_id,
    )


#: Kept importable because stage 6A code names it. The model itself moved to
#: :mod:`fpbench.experiments.prepared_input_validation`.
__all__.append("CanonicalPreparationExpectations")
