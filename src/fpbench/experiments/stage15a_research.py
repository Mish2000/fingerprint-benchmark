"""``fingerprints-matching``, plugged into the shared research engine.

The engine materialises a runtime bundle, defines a run, plans the comparisons,
executes them one at a time, audits, validates, gives the results an identity and
writes a receipt. None of that knows which algorithm is running, and Stage 15A is
the fifth test of that claim — a route with no vendor, no licence, no model file
and no build step, whose entire implementation is 4,492 bytes of pure Python.

What is left here is the part that *is* about this candidate. Four answers:

* how to build the adapter from this repository's bridge and the frozen runtime;
* how to build it again, pinned to a materialised bundle;
* which two files have to be pinned;
* which recorded failures are the algorithm declining a print.

**The two pinned assets are chosen deliberately.** The bridge script is the glue
a reviewer reads, and the published wheel is the algorithm itself — 4,492 bytes
that fit in a bundle whole, so this run's attribution does not depend on an
installed tree staying untouched. The frozen interpreter, numpy and OpenCV are
too large for a bundle and are pinned the other way, by the digest closure in
:mod:`fpbench.experiments.stage15a_runtime`, which the adapter verifies before it
reports itself ready.

**No SD300 run is defined here.** The 6,000 comparisons belong to
:mod:`fpbench.experiments.stage15a_canonical500_full`; a module that already knew
how to start the real run would make starting it an accident.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from fpbench.adapters.base import FingerprintAlgorithmAdapter
from fpbench.adapters.fingerprints_matching.adapter import FingerprintsMatchingAdapter
from fpbench.core.errors import ConfigurationError, ResearchPreflightError
from fpbench.core.provenance_models import SoftwareProvenance
from fpbench.core.research_models import ResearchReceipt, ResearchRunState
from fpbench.core.runtime_models import RuntimeBundleDefinition
from fpbench.experiments import stage15a_identity as frozen
from fpbench.experiments import stage15a_runtime as runtime
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
from fpbench.experiments.research_integration import (
    DevelopmentAdapterRuntime,
    ResearchAdapterIntegration,
    ResearchValidationContext,
)
from fpbench.experiments.stage15a_validation import (
    ExpectedInputSet,
    Stage15AValidationReport,
    validate_fingerprints_matching_result_set,
)
from fpbench.third_party.artifacts import file_sha256

__all__ = [
    "INTEGRATION_ID",
    "BRIDGE_SCRIPT_ROLE",
    "UPSTREAM_WHEEL_ROLE",
    "RUNTIME_ASSET_ROLES",
    "PRIMARY_RUNTIME_ASSET_ROLE",
    "BRIDGE_SCRIPT",
    "fingerprints_matching_research_integration",
    "prepare_fingerprints_matching_research_run",
    "execute_fingerprints_matching_research_run",
    "inspect_fingerprints_matching_research_experiment",
    "finalize_fingerprints_matching_research_run",
]

INTEGRATION_ID = "fingerprints_matching_research_v1"

BRIDGE_SCRIPT_ROLE = "bridge_script"
UPSTREAM_WHEEL_ROLE = "upstream_wheel"

#: Both roles reach the bundle fingerprint. The wheel is the algorithm; the
#: bridge is everything fpbench contributes to running it, and it is small enough
#: to read in one sitting (docs/adr/0042).
RUNTIME_ASSET_ROLES: tuple[str, ...] = (UPSTREAM_WHEEL_ROLE, BRIDGE_SCRIPT_ROLE)
PRIMARY_RUNTIME_ASSET_ROLE = UPSTREAM_WHEEL_ROLE

BRIDGE_SCRIPT = REPOSITORY_ROOT / "integrations" / "fingerprints-matching" / "bridge.py"


def fingerprints_matching_research_integration(
    *,
    expected_input_set: ExpectedInputSet | None = None,
) -> ResearchAdapterIntegration:
    """Everything the shared engine needs in order to run this candidate."""

    def development(
        repository_root: Path,
        algorithm_config: Path,
        overrides: Mapping[str, object],
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

    def validate(context: ResearchValidationContext) -> Stage15AValidationReport:
        return validate_fingerprints_matching_result_set(
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
        adapter_id=frozen.ADAPTER_ID,
        runtime_asset_roles=RUNTIME_ASSET_ROLES,
        primary_runtime_asset_role=PRIMARY_RUNTIME_ASSET_ROLE,
        create_development_runtime=development,
        create_research_delegate=delegate,
        validate_result_set=validate,
    )


def _runtime_assets(repository_root: Path) -> dict[str, Path]:
    """The two files this run pins, checked before anything is copied."""
    root = Path(repository_root)
    bridge = (root / BRIDGE_SCRIPT.relative_to(REPOSITORY_ROOT)).resolve()
    if not bridge.is_file():
        raise ResearchPreflightError(
            "the fingerprints-matching bridge script is missing: "
            f"{BRIDGE_SCRIPT.relative_to(REPOSITORY_ROOT).as_posix()}"
        )

    wheel = (
        runtime.artifacts_directory(repository_root=root) / frozen.RUNTIME_ARTIFACT_NAME
    ).resolve()
    if not wheel.is_file():
        raise ResearchPreflightError(
            "the published wheel is not in the local artifact store; fetch it "
            "with `make stage15a-acquire` before preparing a run"
        )
    observed = file_sha256(wheel)
    if observed != frozen.RUNTIME_ARTIFACT_SHA256:
        raise ResearchPreflightError(
            "the wheel in the local store is not the bytes PyPI published for "
            f"0.1.0: expected {frozen.RUNTIME_ARTIFACT_SHA256[:16]}…, found "
            f"{observed[:16]}…"
        )
    return {UPSTREAM_WHEEL_ROLE: wheel, BRIDGE_SCRIPT_ROLE: bridge}


def _development_runtime(
    repository_root: Path, overrides: Mapping[str, object]
) -> DevelopmentAdapterRuntime:
    """The route as it exists on this machine, and the two files to pin.

    The adapter's environment check verifies the whole frozen closure — the
    interpreter, numpy, OpenCV and the installed module digests — so a runtime
    that has drifted stops everything here rather than six thousand times later.
    """
    unknown = sorted(set(overrides))
    if unknown:
        raise ConfigurationError(
            f"unknown fingerprints-matching development overrides: {unknown}"
        )
    root = Path(repository_root)
    return DevelopmentAdapterRuntime(
        adapter=FingerprintsMatchingAdapter(repository_root=root),
        assets=_runtime_assets(root),
    )


def _research_delegate(
    repository_root: Path,
    bundle: RuntimeBundleDefinition,
    asset_paths: Mapping[str, Path],
) -> FingerprintAlgorithmAdapter:
    """The same route, with this run's own bytes proved to be the ones that ran.

    The bridge executes from its repository path, and the pinned copy is proved
    byte-identical to the file that will execute. That establishes the same fact
    — the bytes in this run's bundle are the bytes that ran — without redirecting
    a route the qualification was performed against.

    Returns the plain adapter. The engine wraps it in ``ResearchModeAdapter``;
    doing that here as well would put the research environment in two places and
    let them disagree.
    """
    root = Path(repository_root)
    live = _runtime_assets(root)
    for role in RUNTIME_ASSET_ROLES:
        pinned = Path(asset_paths[role])
        if not pinned.is_file():
            raise ResearchPreflightError(
                f"the bundle is missing its {role} and cannot attribute this run"
            )
        if file_sha256(pinned) != file_sha256(live[role]):
            raise ResearchPreflightError(
                f"the pinned {role} is not the file that will execute. A run "
                "whose bundle and whose route disagree is not one run "
                "(docs/adr/0018)"
            )

    closure = runtime.build_runtime_closure(repository_root=root)
    runtime.require_ready(closure)
    return FingerprintsMatchingAdapter(
        repository_root=root,
        runtime_manifest_fingerprint=runtime.runtime_manifest_fingerprint(closure),
    )


# ------------------------------------------------------------- thin wrappers


def prepare_fingerprints_matching_research_run(
    *,
    spec: AlgorithmResearchExperimentSpec,
    preparer_factory: PreparerFactory,
    workspace: Path,
    dataset_root: Path | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    expected_input_set: ExpectedInputSet | None = None,
) -> PreparedAlgorithmResearchRun:
    """Pin everything, check everything, and write the run, plan and binding."""
    return prepare_algorithm_research_run(
        spec=spec,
        integration=fingerprints_matching_research_integration(
            expected_input_set=expected_input_set
        ),
        preparer_factory=preparer_factory,
        workspace=Path(workspace),
        dataset_root=dataset_root,
        repository_root=repository_root,
    )


def execute_fingerprints_matching_research_run(
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
        integration=fingerprints_matching_research_integration(
            expected_input_set=expected_input_set
        ),
        preparer_factory=preparer_factory,
        workspace=Path(workspace),
        dataset_root=dataset_root,
        repository_root=repository_root,
        run_id=run_id,
        max_new_jobs=max_new_jobs,
    )


def inspect_fingerprints_matching_research_experiment(
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
        integration=fingerprints_matching_research_integration(
            expected_input_set=expected_input_set
        ),
        preparer_factory=preparer_factory,
        workspace=Path(workspace),
        dataset_root=dataset_root,
        repository_root=repository_root,
        run_id=run_id,
    )


def finalize_fingerprints_matching_research_run(
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
        integration=fingerprints_matching_research_integration(
            expected_input_set=expected_input_set
        ),
        preparer_factory=preparer_factory,
        workspace=Path(workspace),
        dataset_root=dataset_root,
        repository_root=repository_root,
        run_id=run_id,
    )
