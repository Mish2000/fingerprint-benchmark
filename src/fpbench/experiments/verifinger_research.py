"""VeriFinger, plugged into the shared research engine.

Stage 7A moved the research orchestration into
:mod:`fpbench.experiments.algorithm_research`, which knows nothing about any
algorithm: it materialises a runtime bundle, defines a run, plans the
comparisons, executes them one at a time, audits, validates, gives the results an
identity, writes a receipt and a marker. Stage 7B tested that claim with a second
algorithm and Stage 8C with a third. Stage 11B tests it with a commercial SDK
whose 4.7 GB of vendor bytes may never enter the workspace — and the engine is
unchanged (spec section 20).

What is left here is the part that *is* about VeriFinger. Four answers:

* how to build the adapter from this repository's own files and a local
  installation;
* how to build it again, pinned to a materialised bundle;
* which three files have to be pinned;
* which recorded failures are VeriFinger declining a print rather than the
  harness breaking.

They are assembled into one
:class:`~fpbench.experiments.research_integration.ResearchAdapterIntegration` and
handed to the engine. There is no orchestration in this module: no job loop, no
raw result opened, no subprocess started, no runtime bundle built by hand, no
receipt and no finalization marker.

**No SD300 run is defined here.** Stage 11A qualified the route; the 6,000
comparisons are Stage 11B's, and the configuration for them lives in
:mod:`fpbench.experiments.verifinger_canonical500_full` — a wrapper that already
knew how to start the real run would make starting it an accident.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Mapping

from fpbench.adapters.base import FingerprintAlgorithmAdapter
from fpbench.adapters.verifinger_java.adapter import VeriFingerJavaAdapter
from fpbench.adapters.verifinger_java.config import (
    BRIDGE_JAR_ROLE,
    DEFAULT_BRIDGE_JAR,
    DEFAULT_RUNTIME_MANIFEST,
    DEFAULT_RUNTIME_POLICY,
    PRIMARY_RUNTIME_ASSET_ROLE,
    RUNTIME_ASSET_ROLES,
    RUNTIME_MANIFEST_ROLE,
    RUNTIME_POLICY_ROLE,
    VeriFingerJavaConfig,
    resolve_installation,
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
from fpbench.experiments.research_integration import (
    DevelopmentAdapterRuntime,
    ResearchAdapterIntegration,
    ResearchValidationContext,
)
from fpbench.experiments.verifinger_validation import (
    ExpectedInputSet,
    VeriFingerValidationReport,
    validate_verifinger_result_set,
)
from fpbench.adapters.verifinger_java import identity, runtime as runtime_closure

__all__ = [
    "INTEGRATION_ID",
    "BRIDGE_JAR",
    "RUNTIME_MANIFEST_CONFIG",
    "RUNTIME_POLICY_CONFIG",
    "verifinger_research_integration",
    "prepare_verifinger_research_run",
    "execute_verifinger_research_run",
    "inspect_verifinger_research_experiment",
    "finalize_verifinger_research_run",
]

#: This integration's own identity, distinct from the adapter's. A second way of
#: driving the same adapter — a persistent worker, a Linux runtime — would be a
#: different integration and would say so (spec section 3).
INTEGRATION_ID = "verifinger_2025_2_1to1_research_v1"

#: The three repository-owned files a run pins. Everything the SDK contributes is
#: pinned by the runtime manifest instead and re-verified before the run, during
#: it and after it (spec sections 16, 17 and 19).
BRIDGE_JAR = REPOSITORY_ROOT / DEFAULT_BRIDGE_JAR
RUNTIME_MANIFEST_CONFIG = REPOSITORY_ROOT / DEFAULT_RUNTIME_MANIFEST
RUNTIME_POLICY_CONFIG = REPOSITORY_ROOT / DEFAULT_RUNTIME_POLICY


# ------------------------------------------------------------- the integration


def verifinger_research_integration(
    *,
    installation: Path | None = None,
    expected_input_set: ExpectedInputSet | None = None,
    expected_runtime_manifest_fingerprint: str | None = None,
) -> ResearchAdapterIntegration:
    """Everything the shared engine needs in order to run VeriFinger.

    A function rather than a module constant so that a caller gets a fresh,
    immutable record and cannot accidentally mutate a shared one — and so that
    this module's only job stays visible: assemble this, pass it in.

    Args:
        installation: Where the prepared SDK lives. Resolved once here so the
            development runtime and the pinned research delegate cannot end up
            addressing two different installations.
        expected_input_set: Which materialised input set the experiment is
            entitled to have used.
        expected_runtime_manifest_fingerprint: Which runtime closure every
            stored result must name.
    """
    # The adapter never goes looking for an installation; the experiment layer
    # is where the local artifact store is known, so it resolves the default
    # once and both the development runtime and the pinned delegate get it.
    resolved_installation = _resolve_installation(installation)

    def development(
        repository_root: Path,
        algorithm_config: Path,
        overrides: Mapping[str, object],
    ) -> DevelopmentAdapterRuntime:
        return _development_runtime(
            repository_root, overrides, default_installation=resolved_installation
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
            bundle,
            asset_paths,
            software,
            installation=resolved_installation,
        )

    def validate(context: ResearchValidationContext) -> VeriFingerValidationReport:
        """VeriFinger's own reading of a finished run's stored results.

        Which failure codes are biometric outcomes and which mean broken
        infrastructure is an algorithm-specific judgement, which is exactly why
        the engine asks rather than deciding (docs/adr/0013).
        """
        return validate_verifinger_result_set(
            run=context.run,
            plan=context.plan,
            pairs=context.pairs,
            images=context.images,
            result_store=context.result_store,
            runtime_reference=context.runtime_reference,
            preparation=context.preparation,
            expected_input_set=expected_input_set,
            expected_runtime_manifest_fingerprint=(
                expected_runtime_manifest_fingerprint
            ),
        )

    return ResearchAdapterIntegration(
        integration_id=INTEGRATION_ID,
        adapter_id=identity.ADAPTER_ID,
        runtime_asset_roles=RUNTIME_ASSET_ROLES,
        primary_runtime_asset_role=PRIMARY_RUNTIME_ASSET_ROLE,
        create_development_runtime=development,
        create_research_delegate=delegate,
        validate_result_set=validate,
    )



def _resolve_installation(override: Path | None) -> Path:
    """An explicit path, then the environment, then the local artifact store."""
    from fpbench.adapters.verifinger_java.config import UNRESOLVED_INSTALLATION
    from fpbench.experiments.verifinger_runtime_manifest import default_installation

    resolved = resolve_installation(override)
    if resolved == UNRESOLVED_INSTALLATION:
        return default_installation(repository_root=REPOSITORY_ROOT)
    return resolved


def _development_runtime(
    repository_root: Path,
    overrides: Mapping[str, object],
    *,
    default_installation: Path,
) -> DevelopmentAdapterRuntime:
    """The route as it exists on this machine, and the three files to pin.

    The adapter is built from the repository's own bridge jar, manifest and
    policy — the files a reviewer reads — and from the installation the operator
    named. Its environment check verifies all seventeen runtime components,
    obtains the licences and reads the delivered defaults, so a missing DLL, an
    unactivated trial or a drifted default stops everything here rather than six
    thousand times later (spec section 18).
    """
    unknown = sorted(set(overrides) - {"installation"})
    if unknown:
        raise ConfigurationError(f"unknown VeriFinger development overrides: {unknown}")

    root = Path(repository_root)
    config = VeriFingerJavaConfig(
        bridge_jar=_repository_file(root, BRIDGE_JAR, "bridge jar", built=True),
        runtime_manifest=_repository_file(
            root, RUNTIME_MANIFEST_CONFIG, "runtime manifest"
        ),
        runtime_policy=_repository_file(root, RUNTIME_POLICY_CONFIG, "runtime policy"),
        installation=_resolve_installation(
            overrides.get("installation") or default_installation
        ),
        research_mode=False,
    )
    return DevelopmentAdapterRuntime(
        adapter=VeriFingerJavaAdapter(config), assets=dict(config.runtime_assets())
    )


def _research_delegate(
    repository_root: Path,
    bundle: RuntimeBundleDefinition,
    asset_paths: Mapping[str, Path],
    software: SoftwareProvenance,
    *,
    installation: Path,
) -> FingerprintAlgorithmAdapter:
    """The same route, running only bytes this run pinned.

    The bridge jar, the manifest and the policy are all read from the bundle's
    own copies, so a run is literally driven by the executable, the closure and
    the policy it recorded. The SDK itself is not copied — it is re-verified
    against the manifest in the bundle, which is the only way to pin 4.7 GB of
    licence-restricted vendor bytes without redistributing them
    (spec sections 16 and 17).

    Returns the plain VeriFinger adapter. The engine wraps it in
    ``ResearchModeAdapter``; doing that here as well would put the research
    environment in two places and let them disagree.
    """
    _require_bundle_digests(bundle, asset_paths)
    manifest_path = Path(asset_paths[RUNTIME_MANIFEST_ROLE]).resolve()
    manifest = runtime_closure.read_runtime_manifest(manifest_path)
    _require_pinned_matches_repository(Path(repository_root), asset_paths)

    jar = Path(asset_paths[BRIDGE_JAR_ROLE]).resolve()
    digest, size = _file_digest(jar)
    config = VeriFingerJavaConfig(
        bridge_jar=jar,
        runtime_manifest=manifest_path,
        runtime_policy=Path(asset_paths[RUNTIME_POLICY_ROLE]).resolve(),
        installation=_resolve_installation(installation),
    ).pinned_to(
        bridge_jar=jar,
        runtime_manifest=manifest_path,
        runtime_policy=Path(asset_paths[RUNTIME_POLICY_ROLE]).resolve(),
        runtime_bundle_id=bundle.bundle_id,
        runtime_bundle_fingerprint=bundle.bundle_fingerprint,
        expected_bridge_jar_sha256=digest,
        expected_bridge_jar_size=size,
        expected_runtime_manifest_fingerprint=manifest.fingerprint,
        fpbench_source_revision=software.source_revision,
    )
    return VeriFingerJavaAdapter(config)


def _repository_file(
    repository_root: Path, expected: Path, what: str, *, built: bool = False
) -> Path:
    """One file, at the path this integration names and nowhere else."""
    relative = expected.relative_to(REPOSITORY_ROOT)
    path = (Path(repository_root) / relative).resolve()
    if not path.is_file():
        hint = "; run 'make verifinger-build'" if built else ""
        raise ResearchPreflightError(
            f"the VeriFinger {what} is missing: {relative.as_posix()}{hint}"
        )
    if path.is_symlink():
        raise ResearchPreflightError(
            f"the VeriFinger {what} may not be a link: {relative.as_posix()}"
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
        digest, size = _file_digest(Path(asset_paths[role]))
        if digest != asset.sha256 or size != asset.size_bytes:
            raise ResearchPreflightError(
                f"the pinned {role!r} is not the file runtime bundle "
                f"{bundle.bundle_id} holds"
            )


def _require_pinned_matches_repository(
    repository_root: Path, asset_paths: Mapping[str, Path]
) -> None:
    """The manifest and policy in the bundle are the repository's own.

    Byte identity, not path identity. The bundle is what executes; the
    repository copies are what a reviewer reads. A run whose pinned policy said
    something different from the committed one would be publishing evidence
    about a route nobody reviewed.

    The bridge jar is deliberately *not* checked this way: it is a build output,
    and rebuilding it on the same source produces different bytes on a different
    day. What pins it is its own digest, recorded in the bundle and in every
    stored result.
    """
    for role, expected in (
        (RUNTIME_MANIFEST_ROLE, RUNTIME_MANIFEST_CONFIG),
        (RUNTIME_POLICY_ROLE, RUNTIME_POLICY_CONFIG),
    ):
        committed = _repository_file(
            repository_root, expected, role.replace("_", " ")
        )
        pinned_digest, _ = _file_digest(Path(asset_paths[role]))
        committed_digest, _ = _file_digest(committed)
        if pinned_digest != committed_digest:
            raise ResearchPreflightError(
                f"the {role} pinned into this run's runtime bundle "
                f"({pinned_digest[:12]}...) is not the committed file "
                f"({committed_digest[:12]}...). A run may not be resumed under a "
                "different runtime closure or a different policy (docs/adr/0017)"
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
        raise ResearchPreflightError(
            f"cannot hash pinned runtime asset: {exc}"
        ) from exc
    return digest.hexdigest(), size


# --------------------------------------------------------- experiment commands
#
# Four thin forwards. Each one supplies the VeriFinger integration and passes
# everything else through untouched; there is no orchestration here.


def prepare_verifinger_research_run(
    *,
    spec: AlgorithmResearchExperimentSpec,
    preparer_factory: PreparerFactory,
    workspace: Path,
    dataset_root: Path | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    installation: Path | None = None,
    expected_input_set: ExpectedInputSet | None = None,
    expected_runtime_manifest_fingerprint: str | None = None,
) -> PreparedAlgorithmResearchRun:
    """Pin everything, check everything, and write the run, plan and binding."""
    return prepare_algorithm_research_run(
        spec=spec,
        integration=verifinger_research_integration(
            installation=installation,
            expected_input_set=expected_input_set,
            expected_runtime_manifest_fingerprint=(
                expected_runtime_manifest_fingerprint
            ),
        ),
        preparer_factory=preparer_factory,
        workspace=Path(workspace),
        dataset_root=dataset_root,
        repository_root=repository_root,
        development_overrides={"installation": installation} if installation else {},
    )


def execute_verifinger_research_run(
    *,
    spec: AlgorithmResearchExperimentSpec,
    preparer_factory: PreparerFactory,
    workspace: Path,
    dataset_root: Path | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
    max_new_jobs: int | None = None,
    installation: Path | None = None,
    expected_input_set: ExpectedInputSet | None = None,
    expected_runtime_manifest_fingerprint: str | None = None,
) -> RunExecutionSummary:
    """Execute some or all of a prepared run, revalidating everything around it."""
    return execute_algorithm_research_run(
        spec=spec,
        integration=verifinger_research_integration(
            installation=installation,
            expected_input_set=expected_input_set,
            expected_runtime_manifest_fingerprint=(
                expected_runtime_manifest_fingerprint
            ),
        ),
        preparer_factory=preparer_factory,
        workspace=Path(workspace),
        dataset_root=dataset_root,
        repository_root=repository_root,
        run_id=run_id,
        max_new_jobs=max_new_jobs,
    )


def inspect_verifinger_research_experiment(
    *,
    spec: AlgorithmResearchExperimentSpec,
    preparer_factory: PreparerFactory,
    workspace: Path,
    dataset_root: Path | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
    installation: Path | None = None,
    expected_input_set: ExpectedInputSet | None = None,
    expected_runtime_manifest_fingerprint: str | None = None,
) -> ResearchRunState:
    """Report how far along the evidence chain the run is. Never writes."""
    return inspect_algorithm_research_experiment(
        spec=spec,
        integration=verifinger_research_integration(
            installation=installation,
            expected_input_set=expected_input_set,
            expected_runtime_manifest_fingerprint=(
                expected_runtime_manifest_fingerprint
            ),
        ),
        preparer_factory=preparer_factory,
        workspace=Path(workspace),
        dataset_root=dataset_root,
        repository_root=repository_root,
        run_id=run_id,
    )


def finalize_verifinger_research_run(
    *,
    spec: AlgorithmResearchExperimentSpec,
    preparer_factory: PreparerFactory,
    workspace: Path,
    dataset_root: Path | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
    installation: Path | None = None,
    expected_input_set: ExpectedInputSet | None = None,
    expected_runtime_manifest_fingerprint: str | None = None,
) -> ResearchReceipt:
    """Revalidate everything and publish one last immutable commit marker."""
    return finalize_algorithm_research_run(
        spec=spec,
        integration=verifinger_research_integration(
            installation=installation,
            expected_input_set=expected_input_set,
            expected_runtime_manifest_fingerprint=(
                expected_runtime_manifest_fingerprint
            ),
        ),
        preparer_factory=preparer_factory,
        workspace=Path(workspace),
        dataset_root=dataset_root,
        repository_root=repository_root,
        run_id=run_id,
    )
