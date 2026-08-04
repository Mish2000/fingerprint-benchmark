"""One research run of one algorithm, with nothing about the algorithm in it.

Stage 4B's native run and stage 6A's canonical run differ in exactly one thing:
which :class:`~fpbench.imaging.base.ImagePreparer` produces the file the adapter
opens. Everything else — pinning the executables into a content-addressed
bundle, planning 6,000 comparisons in a fixed order, executing them one at a time
with no retries, auditing, validating, giving the results an identity, writing a
sanitised receipt and a final marker — is the same code, and the argument of
stage 6A depends on it *being* the same code.

Stage 7A widens that argument by one step. The orchestration is not only shared
between two runs of one algorithm; it is shared between algorithms. What used to
be hard-coded here now arrives through
:class:`~fpbench.experiments.research_integration.ResearchAdapterIntegration`:

* which adapter to build, from a local build tree and from a pinned bundle;
* which runtime files that adapter needs, by role, however many there are;
* which stored failures are the algorithm declining a print and which mean the
  harness broke.

There is deliberately no branch on an algorithm identifier anywhere in this
module — no ``if algorithm_id == ...``, no ``match adapter_id``, and nothing that
imports a particular adapter. A structural test enforces it, because the rule is
only worth having if breaking it is noisy (docs/adr/0007, docs/adr/0040).

Four commands, separate because they answer to different failures. ``prepare``
is where a dirty working tree, an unverified dataset or a missing executable
stops everything before a single comparison. ``execute`` may be run as many times
as it takes and revalidates the pinned runtime on the way in and on the way out.
``inspect`` never writes. ``finalize`` is the only command that produces a
completion, a result set or a receipt, and only after re-checking every link
(docs/adr/0020).
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from fpbench.core.enums import EnvironmentStatus, ProtocolStage
from fpbench.core.errors import ResearchPreflightError
from fpbench.core.execution_models import ExecutionProfile
from fpbench.core.execution_plan_models import ExecutionPlan
from fpbench.core.identifiers import ImageId, PairId
from fpbench.core.imaging_models import PreparedImageSetManifest
from fpbench.core.models import Cohort, ComparisonPair, ImageRecord
from fpbench.core.provenance_models import SoftwareProvenance
from fpbench.core.research_models import ResearchReceipt, ResearchRunState
from fpbench.core.result_models import RunDefinition
from fpbench.core.runtime_models import RunRuntimeReference, RuntimeBundleDefinition
from fpbench.core.serialization import read_json, write_json
from fpbench.execution.batch_runner import RunExecutionSummary, SequentialRunExecutor
from fpbench.execution.completion import RunCompletionService, build_run_completion
from fpbench.execution.planner import build_execution_plan
from fpbench.execution.progress import inspect_run_progress
from fpbench.execution.research import ResearchModeAdapter, inspect_research_run
from fpbench.execution.result_set import build_result_set
from fpbench.execution.run_definition import create_run_definition
from fpbench.execution.runner import SingleJobRunner
from fpbench.experiments.operational_summary import (
    build_operational_summary,
    write_operational_summary,
)
from fpbench.experiments.prepared_input_validation import PreparedInputExpectations
from fpbench.experiments.research_integration import (
    AlgorithmValidationReport,
    DevelopmentAdapterRuntime,
    DevelopmentRuntimeFactory,
    ResearchAdapterIntegration,
    ResearchDelegateFactory,
    ResearchResultValidator,
    ResearchValidationContext,
)
from fpbench.experiments.research_receipt import (
    build_research_finalization_marker,
    build_research_receipt,
    verify_research_receipt,
    write_evidence_copy,
)
from fpbench.experiments.sd300_inputs import (
    SD300Inputs,
    load_sd300_inputs,
    participating_image_ids,
    preparation_source_bundle,
    require_expected_shape,
)
from fpbench.imaging.base import ImagePreparer
from fpbench.protocols.sd300_protocol import SD300Protocol
from fpbench.storage.plan_store import PlanStore
from fpbench.storage.result_set_store import ResultSetStore
from fpbench.storage.result_store import ResultStore
from fpbench.storage.runtime_bundle_store import RuntimeBundleStore

__all__ = [
    "AlgorithmResearchExperimentSpec",
    "PreparedAlgorithmResearchRun",
    "PreparerFactory",
    # Re-exported so an experiment wrapper needs one import, not two.
    "AlgorithmValidationReport",
    "DevelopmentAdapterRuntime",
    "DevelopmentRuntimeFactory",
    "ResearchAdapterIntegration",
    "ResearchDelegateFactory",
    "ResearchResultValidator",
    "ResearchValidationContext",
    "RunExecutionSummary",
    "capture_research_provenance",
    "prepare_algorithm_research_run",
    "execute_algorithm_research_run",
    "inspect_algorithm_research_experiment",
    "finalize_algorithm_research_run",
    "read_run_pointer",
    "timing_summary",
]

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]

_POINTER_NAME = "current-run.json"

#: Builds the preparer for one invocation. Takes the workspace so that a
#: preparer backed by an immutable set can find it, and the spec so it can be
#: pinned to the exact set the run declares.
PreparerFactory = Callable[[Path, "AlgorithmResearchExperimentSpec"], ImagePreparer]


@dataclass(frozen=True, slots=True)
class AlgorithmResearchExperimentSpec:
    """Everything that distinguishes one research run from another.

    Note what is absent: nothing here names a build product, an interpreter or a
    tool. ``algorithm_config`` is a path the integration reads and this module
    does not; the day a route needs three executables instead of one, this model
    is unchanged (spec section 10).
    """

    experiment_id: str
    kind: str
    replicate_index: int

    dataset_config: Path
    protocol_config: Path
    algorithm_config: Path

    require_verified_checksums: bool
    research_mode: bool
    materialization_policy: str

    execution_profile: ExecutionProfile

    expected_jobs: int
    expected_per_release: int
    expected_per_stage: int
    expected_releases: tuple[str, ...]
    expected_subjects: int
    expected_participating_images: int | None

    evidence_directory: Path

    #: Present only for a run over a materialised input set. When it is, every
    #: stored result is checked against the set's entries (spec section 75).
    preparation_set_id: str | None = None
    preparation_set_fingerprint: str | None = None
    transform_profile_id: str | None = None
    transform_profile_fingerprint: str | None = None

    #: Which source resolution each release must have been scaled from. Checked
    #: through the preparation entries, never inferred from adapter metadata,
    #: which after canonicalisation says one value for all releases
    #: (spec section 76).
    expected_source_ppi: Mapping[str, int] = field(default_factory=dict)

    @property
    def is_canonical(self) -> bool:
        return self.preparation_set_id is not None


@dataclass(frozen=True, slots=True)
class PreparedAlgorithmResearchRun:
    """Everything ``execute`` and ``finalize`` need, already checked."""

    spec: AlgorithmResearchExperimentSpec
    integration: ResearchAdapterIntegration
    software: SoftwareProvenance
    verifier_software: SoftwareProvenance

    inputs: SD300Inputs
    workspace: Path

    bundle: RuntimeBundleDefinition
    adapter: ResearchModeAdapter
    preparer: ImagePreparer

    run: RunDefinition
    plan: ExecutionPlan
    runtime_reference: RunRuntimeReference
    preparation_preflight_issue: str | None = None

    @property
    def protocol(self) -> SD300Protocol:
        return self.inputs.protocol

    @property
    def cohort(self) -> Cohort:
        return self.inputs.cohort

    @property
    def images(self) -> Mapping[ImageId, ImageRecord]:
        return self.inputs.images

    @property
    def pairs(self) -> Mapping[PairId, ComparisonPair]:
        return self.inputs.pairs

    @property
    def dataset_root(self) -> Path:
        return self.inputs.dataset_root

    @property
    def result_store(self) -> ResultStore:
        return ResultStore(self.workspace)

    @property
    def plan_store(self) -> PlanStore:
        return PlanStore(self.workspace)

    @property
    def result_set_store(self) -> ResultSetStore:
        return ResultSetStore(self.workspace)

    @property
    def bundle_store(self) -> RuntimeBundleStore:
        return RuntimeBundleStore(self.workspace)


# ---------------------------------------------------------------- prepare


def prepare_algorithm_research_run(
    *,
    spec: AlgorithmResearchExperimentSpec,
    integration: ResearchAdapterIntegration,
    preparer_factory: PreparerFactory,
    workspace: Path,
    dataset_root: Path | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    development_overrides: Mapping[str, object] | None = None,
    ) -> PreparedAlgorithmResearchRun:
    """Pin everything, check everything, and write the run, plan and binding.

    Idempotent: the same inputs a second time produce the same run id, the same
    plan id and the same bundle id, and nothing is overwritten.

    Args:
        development_overrides: Passed to the integration's development factory
            untouched. This is how an experiment says "materialise from this
            file rather than the build output" without this module growing a
            parameter that only one algorithm would ever use (spec section 13).
    """
    workspace = Path(workspace)
    repository_root = Path(repository_root)
    software = capture_research_provenance(repository_root)

    development = integration.create_development_runtime(
        repository_root, Path(spec.algorithm_config), dict(development_overrides or {})
    )
    if not isinstance(development, DevelopmentAdapterRuntime):
        raise ResearchPreflightError(
            f"integration {integration.integration_id!r} did not return a "
            "development runtime"
        )
    integration.require_development_runtime(development)

    build_report = development.adapter.validate_environment()
    if build_report.status is not EnvironmentStatus.READY:
        raise ResearchPreflightError(
            "the local build is not usable, so there is nothing to pin: "
            f"{build_report.message or 'no detail given'}"
        )

    bundle_store = RuntimeBundleStore(workspace)
    bundle = bundle_store.materialize(
        adapter_id=integration.adapter_id,
        assets=dict(development.assets),
        materialization_policy=spec.materialization_policy,
    )
    integration.require_bundle_matches(bundle)

    adapter = _research_adapter(
        integration=integration,
        spec=spec,
        repository_root=repository_root,
        bundle=bundle,
        bundle_store=bundle_store,
        software=software,
        include_integration_identity=True,
    )
    # Pinning moved where the bytes live. It must not have moved what the
    # algorithm is, or the environment check above proved nothing about the
    # thing that will actually produce the scores (spec section 15).
    integration.require_same_algorithm(
        development=development.adapter, research=adapter.delegate
    )

    environment = adapter.validate_environment()
    if environment.status is not EnvironmentStatus.READY:
        raise ResearchPreflightError(
            "the pinned runtime is not usable: "
            f"{environment.message or 'no detail given'}"
        )

    inputs = load_sd300_inputs(
        workspace=workspace,
        dataset_root=dataset_root,
        dataset_config=spec.dataset_config,
        protocol_config=spec.protocol_config,
        require_verified_checksums=spec.require_verified_checksums,
        allow_creation=True,
    )
    require_expected_shape(
        cohort=inputs.cohort,
        pairs=inputs.pairs,
        images=inputs.images,
        expected_jobs=spec.expected_jobs,
        expected_subjects=spec.expected_subjects,
        expected_participating_images=spec.expected_participating_images,
    )

    # The preparer gets to refuse before a run exists at all. For a run over a
    # materialised set this is where a missing artefact stops everything — one
    # fault of the run, not 6,000 identical per-pair failures (spec section 56).
    preparer = preparer_factory(workspace, spec)
    preparer.preflight()
    _require_preparer_covers(preparer, inputs)

    run = create_run_definition(
        protocol_id=inputs.protocol.protocol_id,
        cohort_id=inputs.cohort.cohort_id,
        pair_manifest_hash=inputs.pair_manifest_hash,
        algorithm=adapter.descriptor,
        environment=environment,
        execution_profile=spec.execution_profile,
        replicate_index=spec.replicate_index,
    )
    plan = build_execution_plan(
        run=run, pairs=inputs.pairs.values(), pair_manifest_metadata=inputs.pair_metadata
    )
    _require_expected_plan(plan, spec)

    result_store = ResultStore(workspace)
    result_store.ensure_run(run)
    PlanStore(workspace).ensure_plan(plan)

    reference = RunRuntimeReference.create(
        run_id=run.run_id,
        run_fingerprint=run.run_fingerprint,
        environment_fingerprint=run.environment_fingerprint,
        bundle=bundle,
        created_utc=_utc_now(),
    )
    result_store.ensure_runtime_reference(reference)
    pointer: dict[str, Any] = {
        "experiment_id": spec.experiment_id,
        "integration_id": integration.integration_id,
        "integration_fingerprint": integration.integration_fingerprint,
        "run_id": run.run_id,
        "plan_id": plan.plan_id,
        "runtime_bundle_id": bundle.bundle_id,
        "runtime_bundle_fingerprint": bundle.bundle_fingerprint,
        "runtime_asset_roles": list(integration.runtime_asset_roles),
        "source_commit": software.source_revision,
        "prepared_utc": _utc_now(),
    }
    if spec.preparation_set_id:
        pointer["preparation_set_id"] = spec.preparation_set_id
    _write_pointer(workspace, spec.experiment_id, pointer)

    return PreparedAlgorithmResearchRun(
        spec=spec,
        integration=integration,
        software=software,
        verifier_software=software,
        inputs=inputs,
        workspace=workspace,
        bundle=bundle,
        adapter=adapter,
        preparer=preparer,
        run=run,
        plan=plan,
        runtime_reference=reference,
    )


# ---------------------------------------------------------------- execute


def execute_algorithm_research_run(
    *,
    spec: AlgorithmResearchExperimentSpec,
    integration: ResearchAdapterIntegration,
    preparer_factory: PreparerFactory,
    workspace: Path,
    dataset_root: Path | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
    max_new_jobs: int | None = None,
) -> RunExecutionSummary:
    """Execute some or all of a prepared run, revalidating everything around it.

    The bundle's full digest is checked before the executor starts and again
    after it stops — every asset, not the primary one. For a run over a
    materialised set the input set is fully verified at the same two points, and
    every comparison in between does the cheap file-identity check. The threat
    model is accidental drift — a set regenerated in another terminal, an
    executable rebuilt by a stray build command — not an adversary who mutates a
    file and restores it between two checks (spec section 59).
    """
    prepared = _load_prepared(
        spec=spec,
        integration=integration,
        preparer_factory=preparer_factory,
        workspace=workspace,
        dataset_root=dataset_root,
        repository_root=repository_root,
        run_id=run_id,
    )

    bundle_store = prepared.bundle_store
    bundle_store.require_valid(prepared.runtime_reference.bundle_id)

    result_store = prepared.result_store
    executor = SequentialRunExecutor(
        plan=prepared.plan,
        pair_index=prepared.pairs,
        job_runner=SingleJobRunner(
            run=prepared.run,
            adapter=prepared.adapter,
            preparer=prepared.preparer,
            result_store=result_store,
            dataset_root=prepared.dataset_root,
            image_index=prepared.images,
            workspace_root=prepared.workspace,
        ),
        result_store=result_store,
        completion_service=RunCompletionService(result_store=result_store),
        plan_store=prepared.plan_store,
    )

    summary = executor.execute(max_new_jobs=max_new_jobs, finalize=False)

    bundle_store.require_valid(prepared.runtime_reference.bundle_id)
    # The preparer verifies its own inputs again on the way out. For the identity
    # preparer this is a no-op; for a set-backed one it re-reads every artefact.
    prepared.preparer.preflight()

    progress = inspect_run_progress(
        run=prepared.run, plan=prepared.plan, result_store=result_store
    )
    result_store.write_derived(prepared.run.run_id, "progress.json", progress)
    write_operational_summary(
        result_store=result_store,
        run_id=prepared.run.run_id,
        summary=build_operational_summary(
            run=prepared.run,
            plan=prepared.plan,
            pairs=prepared.pairs,
            result_store=result_store,
            runtime_bundle_id=prepared.runtime_reference.bundle_id,
        ),
    )
    return summary


# ----------------------------------------------------------------- status


def inspect_algorithm_research_experiment(
    *,
    spec: AlgorithmResearchExperimentSpec,
    integration: ResearchAdapterIntegration,
    preparer_factory: PreparerFactory,
    workspace: Path,
    dataset_root: Path | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
) -> ResearchRunState:
    """Report how far along the evidence chain the run is. Never writes."""
    prepared = _load_prepared(
        spec=spec,
        integration=integration,
        preparer_factory=preparer_factory,
        workspace=workspace,
        dataset_root=dataset_root,
        repository_root=repository_root,
        run_id=run_id,
        require_source_match=False,
        run_preparer_preflight=False,
        require_clean_verifier=False,
    )
    validation = None
    manifest = None
    if prepared.preparation_preflight_issue is None:
        manifest = _preparation_manifest(prepared)
        validation = _validate(prepared)
    return inspect_research_run(
        run=prepared.run,
        plan=prepared.plan,
        result_store=prepared.result_store,
        pairs=prepared.pairs,
        algorithm_validation=validation,
        primary_asset_role=integration.primary_runtime_asset_role,
        verifier_software=prepared.verifier_software,
        preparation_manifest=manifest,
        external_issues=(
            (prepared.preparation_preflight_issue,)
            if prepared.preparation_preflight_issue
            else ()
        ),
    )


# --------------------------------------------------------------- finalize


def finalize_algorithm_research_run(
    *,
    spec: AlgorithmResearchExperimentSpec,
    integration: ResearchAdapterIntegration,
    preparer_factory: PreparerFactory,
    workspace: Path,
    dataset_root: Path | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
) -> ResearchReceipt:
    """Revalidate everything and publish one last immutable commit marker."""
    prepared = _load_prepared(
        spec=spec,
        integration=integration,
        preparer_factory=preparer_factory,
        workspace=workspace,
        dataset_root=dataset_root,
        repository_root=repository_root,
        run_id=run_id,
        require_source_match=False,
    )
    result_store = prepared.result_store
    primary_role = integration.primary_runtime_asset_role

    prepared.bundle_store.require_valid(prepared.runtime_reference.bundle_id)

    completion_service = RunCompletionService(result_store=result_store)
    audit = completion_service.audit(run=prepared.run, plan=prepared.plan)
    if not audit.is_clean:
        raise ResearchPreflightError(
            f"run {prepared.run.run_id} does not audit cleanly: "
            f"{[issue.code.value for issue in audit.errors][:5]}"
        )

    preparation_manifest = _preparation_manifest(prepared)
    validation = _validate(prepared)
    if not validation.is_clean:
        raise ResearchPreflightError(
            f"run {prepared.run.run_id} failed algorithm validation "
            f"({validation.blocking_failures} blocking failure(s)): "
            f"{[issue.code.value for issue in validation.errors][:5]}"
        )

    manifest, entries = build_result_set(
        run=prepared.run,
        plan=prepared.plan,
        result_store=result_store,
        runtime_reference=prepared.runtime_reference,
    )
    completion = build_run_completion(run=prepared.run, plan=prepared.plan, audit=audit)
    summary = build_operational_summary(
        run=prepared.run,
        plan=prepared.plan,
        pairs=prepared.pairs,
        result_store=result_store,
        result_set=manifest,
        runtime_bundle_id=prepared.runtime_reference.bundle_id,
    )
    receipt = build_research_receipt(
        run=prepared.run,
        plan=prepared.plan,
        pairs=prepared.pairs,
        software=prepared.software,
        runtime_reference=prepared.runtime_reference,
        result_set=manifest,
        audit=audit,
        validation=validation,
        completion=completion,
        dataset_id=prepared.protocol.dataset_id,
        timing_summary=timing_summary(summary),
        preparation_manifest=preparation_manifest,
        primary_asset_role=primary_role,
    )

    prepared.result_set_store.ensure_result_set(manifest, entries)
    result_store.ensure_completion(completion)
    write_operational_summary(
        result_store=result_store, run_id=prepared.run.run_id, summary=summary
    )
    result_store.ensure_research_receipt(receipt)

    stored_completion = result_store.read_completion(prepared.run.run_id)
    stored_result_set = prepared.result_set_store.verify_result_set(prepared.run.run_id)
    stored_receipt = result_store.read_research_receipt(prepared.run.run_id)
    verify_research_receipt(
        run=prepared.run,
        plan=prepared.plan,
        pairs=prepared.pairs,
        runtime_reference=prepared.runtime_reference,
        result_set=stored_result_set,
        current_audit=audit,
        current_algorithm_validation=validation,
        completion=stored_completion,
        receipt=stored_receipt,
        preparation_manifest=preparation_manifest,
        primary_asset_role=primary_role,
    )

    marker = build_research_finalization_marker(
        run=prepared.run,
        plan=prepared.plan,
        runtime_reference=prepared.runtime_reference,
        result_set=stored_result_set,
        audit=audit,
        validation=validation,
        completion=stored_completion,
        receipt=stored_receipt,
        verifier_software=prepared.verifier_software,
    )
    result_store.ensure_research_finalization(marker)

    state = inspect_research_run(
        run=prepared.run,
        plan=prepared.plan,
        result_store=result_store,
        pairs=prepared.pairs,
        algorithm_validation=validation,
        primary_asset_role=primary_role,
        verifier_software=prepared.verifier_software,
        preparation_manifest=preparation_manifest,
    )
    if not state.is_research_ready:
        raise ResearchPreflightError(
            f"run {prepared.run.run_id} finalised but did not reach "
            f"RESEARCH_READY: {state.status.value} {list(state.issues)[:3]}"
        )

    write_evidence_copy(
        stored_receipt,
        repository_root=Path(repository_root),
        directory=spec.evidence_directory,
    )
    return stored_receipt


# ----------------------------------------------------------------- helpers


def capture_research_provenance(repository_root: Path) -> SoftwareProvenance:
    """The clean, committed revision a research run must be started from."""
    from fpbench.provenance.software import capture_software_provenance

    return capture_software_provenance(
        repository_root=Path(repository_root), require_clean=True
    )


def _capture_inspection_provenance(repository_root: Path) -> SoftwareProvenance:
    """Describe the current reader without making a clean tree a prerequisite."""
    from fpbench.provenance.software import capture_software_provenance

    return capture_software_provenance(
        repository_root=Path(repository_root), require_clean=False
    )


def timing_summary(summary: Mapping[str, Any]) -> dict[str, str]:
    """The few timing numbers a receipt may carry, rendered as strings.

    Operational only. A receipt that carried a distribution would be one step
    from carrying a score distribution, and the difference has to be visible in
    the file rather than remembered.
    """
    timings = summary.get("timings_ms") or {}
    adapter = timings.get("adapter") or {}
    fields = ("count", "min", "median", "p95", "p99", "max")
    rendered = {
        f"adapter_ms.{field}": str(adapter[field])
        for field in fields
        if field in adapter
    }
    span = summary.get("wall_clock_span_seconds")
    if span is not None:
        rendered["wall_clock_span_seconds"] = str(span)
    return rendered


def _research_adapter(
    *,
    integration: ResearchAdapterIntegration,
    spec: AlgorithmResearchExperimentSpec,
    repository_root: Path,
    bundle: RuntimeBundleDefinition,
    bundle_store: RuntimeBundleStore,
    software: SoftwareProvenance,
    include_integration_identity: bool,
) -> ResearchModeAdapter:
    """Build the algorithm pinned to ``bundle``, wrapped for research mode.

    The wrapping happens here rather than inside the integration so that every
    algorithm's research environment is assembled by one piece of code. An
    adapter that wrapped itself could report provenance the run never recorded.
    """
    asset_paths = {
        role: bundle_store.asset_path(bundle.bundle_id, role)
        for role in integration.runtime_asset_roles
    }
    delegate = integration.create_research_delegate(
        Path(repository_root),
        Path(spec.algorithm_config),
        bundle,
        asset_paths,
        software,
    )
    delegate = integration.require_adapter(
        delegate, label="pinned research adapter"
    )
    return ResearchModeAdapter(
        delegate=delegate,
        software=software,
        runtime_bundle=bundle,
        integration_id=(integration.integration_id if include_integration_identity else None),
        integration_fingerprint=(
            integration.integration_fingerprint
            if include_integration_identity
            else None
        ),
    )


def _validate(prepared: PreparedAlgorithmResearchRun) -> AlgorithmValidationReport:
    """Ask the algorithm's own validator what it makes of the stored results."""
    context = ResearchValidationContext(
        run=prepared.run,
        plan=prepared.plan,
        pairs=prepared.pairs,
        images=prepared.images,
        result_store=prepared.result_store,
        runtime_reference=prepared.runtime_reference,
        preparation=_preparation_expectations(prepared),
    )
    return prepared.integration.validate_result_set(context)


def _require_preparer_covers(preparer: ImagePreparer, inputs: SD300Inputs) -> None:
    """Prove a set-backed preparer can answer every question the run will ask.

    Only meaningful for a preparer that owns a fixed set of artefacts, so it is
    asked for rather than assumed: the identity preparer has no such method and
    needs none.
    """
    require_bundle = getattr(preparer, "require_source_bundle", None)
    if require_bundle is not None:
        require_bundle(preparation_source_bundle(inputs))

    require = getattr(preparer, "require_expected_images", None)
    if require is None:
        return
    require(set(participating_image_ids(inputs.pairs)))


def _require_expected_plan(
    plan: ExecutionPlan, spec: AlgorithmResearchExperimentSpec
) -> None:
    if plan.total_jobs != spec.expected_jobs:
        raise ResearchPreflightError(
            f"the execution plan holds {plan.total_jobs} jobs, expected "
            f"{spec.expected_jobs}"
        )
    stage_counts = dict(plan.definition.stage_counts)
    expected_stages = {stage.value: spec.expected_per_stage for stage in ProtocolStage}
    if stage_counts != expected_stages:
        raise ResearchPreflightError(
            f"the plan's stage counts are {stage_counts}, expected {expected_stages}"
        )
    release_counts = dict(plan.definition.release_counts)
    expected_releases = {
        release: spec.expected_per_release for release in spec.expected_releases
    }
    if release_counts != expected_releases:
        raise ResearchPreflightError(
            f"the plan's release counts are {release_counts}, expected "
            f"{expected_releases}"
        )


def _preparation_expectations(
    prepared: PreparedAlgorithmResearchRun,
) -> PreparedInputExpectations | None:
    """What every stored result of a set-backed run must claim about its inputs.

    ``None`` for a run over the delivered bytes: there is no input set to check
    results against, and inventing one would make the identity preparer's
    results fail a check they were never subject to (spec section 61).
    """
    spec = prepared.spec
    if not spec.is_canonical:
        return None
    preparer = prepared.preparer
    entries_of = getattr(preparer, "prepared_entries", None)
    if entries_of is None:  # pragma: no cover - only a set-backed preparer gets here
        raise ResearchPreflightError(
            "a run over a materialised set needs a preparer backed by one"
        )
    entries = entries_of()
    return PreparedInputExpectations(
        execution_profile_id=spec.execution_profile.profile_id,
        preparer_id=preparer.preparer_id,
        preparer_version=preparer.preparer_version,
        runner_metadata_schema=preparer.runner_metadata_schema,
        preparation_set_id=str(spec.preparation_set_id),
        preparation_set_fingerprint=str(spec.preparation_set_fingerprint),
        transform_profile_id=str(spec.transform_profile_id),
        transform_profile_fingerprint=str(spec.transform_profile_fingerprint),
        transform_runtime_fingerprint=str(
            preparer.run_metadata()["transform_runtime_fingerprint"]
        ),
        target_ppi=int(spec.execution_profile.parameters["target_ppi"]),
        entries=entries,
        expected_source_ppi=dict(spec.expected_source_ppi),
    )


def _preparation_manifest(
    prepared: PreparedAlgorithmResearchRun,
) -> PreparedImageSetManifest | None:
    if not prepared.spec.is_canonical:
        return None
    manifest_of = getattr(prepared.preparer, "prepared_manifest", None)
    if manifest_of is None:  # pragma: no cover - only set-backed preparers reach here
        raise ResearchPreflightError(
            "a run over a materialised set needs a verified PreparedImageSetManifest"
        )
    return manifest_of()


def _load_prepared(
    *,
    spec: AlgorithmResearchExperimentSpec,
    integration: ResearchAdapterIntegration,
    preparer_factory: PreparerFactory,
    workspace: Path,
    dataset_root: Path | None,
    repository_root: Path,
    run_id: str | None,
    require_source_match: bool = True,
    run_preparer_preflight: bool = True,
    require_clean_verifier: bool = True,
) -> PreparedAlgorithmResearchRun:
    """Reconstruct a prepared run from what ``prepare`` already wrote.

    Never re-materialises and never re-plans. Execution requires the current
    revision to match the executor revision recorded by the run. Status and
    finalization instead preserve that recorded provenance while capturing the
    verifier revision that is checking it; otherwise a verifier fix could never
    be applied to an older completed run (docs/adr/0017). Finalization requires
    that verifier to be clean. Status records a dirty or unavailable verifier
    without refusing to read already-published evidence.
    """
    workspace = Path(workspace)
    repository_root = Path(repository_root)
    verifier_software = (
        capture_research_provenance(repository_root)
        if require_clean_verifier
        else _capture_inspection_provenance(repository_root)
    )

    resolved = run_id or _read_pointer(workspace, spec.experiment_id)
    result_store = ResultStore(workspace)
    run = result_store.read_run(resolved)
    plan = PlanStore(workspace).read_plan(resolved)
    reference = result_store.read_runtime_reference(resolved)
    software = _software_recorded_by_run(run)

    recorded = run.environment.runtime.get("fpbench.source.revision")
    if require_source_match and recorded != verifier_software.source_revision:
        raise ResearchPreflightError(
            f"run {resolved} was created from commit {str(recorded)[:12]} but this "
            f"invocation is running commit {verifier_software.source_revision[:12]}. "
            "A run cannot be resumed under different code; check out the original "
            "commit, or prepare a new run (docs/adr/0017)"
        )

    bundle_store = RuntimeBundleStore(workspace)
    bundle = bundle_store.read_bundle(reference.bundle_id)
    # Re-checked on every reload, not only when the bundle was created: a bundle
    # that acquired a role, lost one, or belongs to another adapter is not the
    # runtime this run was defined against (spec section 64).
    integration.require_bundle_matches(bundle)
    recorded_integration_id = run.environment.runtime.get(
        "fpbench.integration.id"
    )
    recorded_integration_fingerprint = run.environment.runtime.get(
        "fpbench.integration.fingerprint"
    )
    recorded_integration = (
        recorded_integration_id,
        recorded_integration_fingerprint,
    )
    if any(value is not None for value in recorded_integration):
        if not all(value is not None for value in recorded_integration):
            raise ResearchPreflightError(
                f"run {run.run_id} carries an incomplete research integration identity"
            )
        if (
            recorded_integration_id != integration.integration_id
            or recorded_integration_fingerprint != integration.integration_fingerprint
        ):
            raise ResearchPreflightError(
                f"run {run.run_id} was prepared with integration "
                f"{recorded_integration_id!r} "
                f"({str(recorded_integration_fingerprint)[:12]}...), but this "
                f"invocation supplied {integration.integration_id!r} "
                f"({integration.integration_fingerprint[:12]}...)"
            )
    adapter = _research_adapter(
        integration=integration,
        spec=spec,
        repository_root=repository_root,
        bundle=bundle,
        bundle_store=bundle_store,
        software=software,
        include_integration_identity=recorded_integration_id is not None,
    )

    inputs = load_sd300_inputs(
        workspace=workspace,
        dataset_root=dataset_root,
        dataset_config=spec.dataset_config,
        protocol_config=spec.protocol_config,
        require_verified_checksums=spec.require_verified_checksums,
    )

    preparer = preparer_factory(workspace, spec)
    preparation_preflight_issue = None
    if run_preparer_preflight:
        preparer.preflight()
        _require_preparer_covers(preparer, inputs)
    else:
        # Status describes a broken chain; it does not refuse to speak about
        # one. A set that will not verify becomes issues on the returned state,
        # by way of a validation pass with no entries to check against — which
        # is exactly what a reader needs to see.
        from fpbench.core.errors import PreflightError

        try:
            preparer.preflight()
            _require_preparer_covers(preparer, inputs)
        except PreflightError as exc:
            preparation_preflight_issue = f"preparation-set preflight failed: {exc}"

    return PreparedAlgorithmResearchRun(
        spec=spec,
        integration=integration,
        software=software,
        verifier_software=verifier_software,
        inputs=inputs,
        workspace=workspace,
        bundle=bundle,
        adapter=adapter,
        preparer=preparer,
        run=run,
        plan=plan,
        runtime_reference=reference,
        preparation_preflight_issue=preparation_preflight_issue,
    )


def _software_recorded_by_run(run: RunDefinition) -> SoftwareProvenance:
    """Reconstruct executor provenance from the immutable run environment."""
    from fpbench.core.provenance_models import TRACKED_DEPENDENCIES

    runtime = run.environment.runtime
    dependencies = run.environment.dependencies
    try:
        return SoftwareProvenance(
            provenance_kind=runtime["fpbench.source.kind"],
            source_revision=runtime["fpbench.source.revision"],
            source_tree_clean=runtime["fpbench.source.clean"] == "true",
            package_version=dependencies["fpbench.package"],
            python_version=runtime["python.version"],
            python_implementation=runtime["python.implementation"],
            dependency_versions={
                name: dependencies[name] for name in TRACKED_DEPENDENCIES
            },
        )
    except (KeyError, ValueError) as exc:
        raise ResearchPreflightError(
            f"run {run.run_id} does not carry complete executor provenance ({exc})"
        ) from exc


def _pointer_path(workspace: Path, experiment_id: str) -> Path:
    return Path(workspace) / "experiments" / experiment_id / _POINTER_NAME


def _write_pointer(
    workspace: Path, experiment_id: str, payload: Mapping[str, Any]
) -> Path:
    return write_json(_pointer_path(workspace, experiment_id), dict(payload))


def read_run_pointer(workspace: Path, experiment_id: str) -> str:
    """Which run an experiment last prepared in this workspace.

    A bookmark, not evidence. Nothing downstream trusts anything in the pointer
    beyond the run id, and every check re-derives what it needs from the run's
    own manifests — which is also why a pointer written by an older stage, with
    keys this one no longer writes, is still perfectly readable.
    """
    path = _pointer_path(workspace, experiment_id)
    if not path.is_file():
        raise ResearchPreflightError(
            f"no prepared run for {experiment_id} in this workspace; run "
            "'prepare' first, or pass --run-id"
        )
    payload = read_json(path)
    resolved = str(payload.get("run_id") or "")
    if not resolved:
        raise ResearchPreflightError(f"{path} names no run")
    return resolved


_read_pointer = read_run_pointer


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()
