"""One SourceAFIS research run, parameterised by how its images are prepared.

Stage 4B's native run and stage 6A's canonical run differ in exactly one thing:
which :class:`~fpbench.imaging.base.ImagePreparer` produces the file the adapter
opens. Everything else — pinning the jar into a content-addressed bundle,
planning 6,000 comparisons in a fixed order, executing them one subprocess at a
time with no retries, auditing, validating, giving the results an identity,
writing a sanitised receipt and a final marker — is the same code, and the
argument of stage 6A depends on it *being* the same code.

Two copies would be two chances for the difference to be something other than
the preparer. So there is one implementation, and the two experiments inject:

* an execution profile, which is what makes the two runs different runs;
* a preparer factory;
* the expected shape, which both share;
* an evidence directory and, for the canonical run, the preparation set its
  results must all belong to.

There is deliberately no ``if resolution_mode == "canonical_500"`` here, in the
executor, or in the runner. Resampling happened hours earlier, in
:mod:`fpbench.imaging.canonical`, and by the time this module runs there is
nothing left to branch on (docs/adr/0007, docs/adr/0031).
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from fpbench.adapters.sourceafis_java.adapter import ADAPTER_ID, SourceAfisJavaAdapter
from fpbench.adapters.sourceafis_java.config import (
    BRIDGE_JAR_ROLE,
    SourceAfisJavaConfig,
)
from fpbench.core.enums import EnvironmentStatus, ProtocolStage
from fpbench.core.errors import ResearchPreflightError
from fpbench.core.execution_models import ExecutionProfile
from fpbench.core.execution_plan_models import ExecutionPlan
from fpbench.core.identifiers import ImageId, PairId
from fpbench.core.imaging_models import PreparedImageSetManifest
from fpbench.core.models import Cohort, ComparisonPair, ImageRecord
from fpbench.core.provenance_models import SoftwareProvenance
from fpbench.core.research_models import ResearchRunReceipt, ResearchRunState
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
from fpbench.experiments.sourceafis_validation import (
    CanonicalPreparationExpectations,
    validate_sourceafis_result_set,
)
from fpbench.imaging.base import ImagePreparer
from fpbench.protocols.sd300_protocol import SD300Protocol
from fpbench.storage.plan_store import PlanStore
from fpbench.storage.result_set_store import ResultSetStore
from fpbench.storage.result_store import ResultStore
from fpbench.storage.runtime_bundle_store import RuntimeBundleStore

__all__ = [
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
]

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]

_POINTER_NAME = "current-run.json"

#: Builds the preparer for one invocation. Takes the workspace so that a
#: preparer backed by an immutable set can find it, and the spec so it can be
#: pinned to the exact set the run declares.
PreparerFactory = Callable[[Path, "ResearchExperimentSpec"], ImagePreparer]


@dataclass(frozen=True, slots=True)
class ResearchExperimentSpec:
    """Everything that distinguishes one SourceAFIS research run from another."""

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
    #: which after canonicalisation says 500 for all three (spec section 76).
    expected_source_ppi: Mapping[str, int] = field(default_factory=dict)

    @property
    def is_canonical(self) -> bool:
        return self.preparation_set_id is not None


@dataclass(frozen=True, slots=True)
class PreparedResearchRun:
    """Everything ``execute`` and ``finalize`` need, already checked."""

    spec: ResearchExperimentSpec
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


def prepare_research_run(
    *,
    spec: ResearchExperimentSpec,
    preparer_factory: PreparerFactory,
    workspace: Path,
    dataset_root: Path | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    build_jar: Path | None = None,
) -> PreparedResearchRun:
    """Pin everything, check everything, and write the run, plan and binding.

    Idempotent: the same inputs a second time produce the same run id, the same
    plan id and the same bundle id, and nothing is overwritten.
    """
    workspace = Path(workspace)
    software = capture_research_provenance(repository_root)

    development = _development_config(
        repository_root=repository_root, build_jar=build_jar
    )
    build_report = SourceAfisJavaAdapter(development).validate_environment()
    if build_report.status is not EnvironmentStatus.READY:
        raise ResearchPreflightError(
            "the SourceAFIS bridge is not usable, so there is nothing to pin: "
            f"{build_report.message or 'no detail given'}"
        )

    bundle_store = RuntimeBundleStore(workspace)
    bundle = bundle_store.materialize(
        adapter_id=ADAPTER_ID,
        assets={BRIDGE_JAR_ROLE: development.bridge_jar},
        materialization_policy=spec.materialization_policy,
    )
    asset = bundle.asset(BRIDGE_JAR_ROLE)

    adapter = _research_adapter(
        development=development,
        bundle=bundle,
        bundle_store=bundle_store,
        software=software,
    )
    environment = adapter.validate_environment()
    if environment.status is not EnvironmentStatus.READY:
        raise ResearchPreflightError(
            "the pinned SourceAFIS runtime is not usable: "
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

    # The preparer gets to refuse before a run exists at all. For a canonical
    # run this is where a missing artefact stops everything — one fault of the
    # run, not 6,000 identical per-pair failures (spec section 56).
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
        "run_id": run.run_id,
        "plan_id": plan.plan_id,
        "runtime_bundle_id": bundle.bundle_id,
        "bridge_jar_sha256": asset.sha256,
        "source_commit": software.source_revision,
        "prepared_utc": _utc_now(),
    }
    if spec.preparation_set_id:
        pointer["preparation_set_id"] = spec.preparation_set_id
    _write_pointer(workspace, spec.experiment_id, pointer)

    return PreparedResearchRun(
        spec=spec,
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
    """Execute some or all of a prepared run, revalidating everything around it.

    The bundle's full digest is checked before the executor starts and again
    after it stops. For a canonical run the input set is fully verified at the
    same two points, and every comparison in between does the cheap file-identity
    check. The threat model is accidental drift — a set regenerated in another
    terminal, a jar rebuilt by a stray ``mvnw package`` — not an adversary who
    mutates a file and restores it between two checks (spec section 59).
    """
    prepared = _load_prepared(
        spec=spec,
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
    # preparer this is a no-op; for a canonical one it re-reads 3,000 artefacts.
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
    prepared = _load_prepared(
        spec=spec,
        preparer_factory=preparer_factory,
        workspace=workspace,
        dataset_root=dataset_root,
        repository_root=repository_root,
        run_id=run_id,
        require_source_match=False,
        run_preparer_preflight=False,
    )
    validation = None
    manifest = None
    if prepared.preparation_preflight_issue is None:
        preparation = _preparation_expectations(prepared)
        manifest = _preparation_manifest(prepared)
        validation = validate_sourceafis_result_set(
            run=prepared.run,
            plan=prepared.plan,
            pairs=prepared.pairs,
            images=prepared.images,
            result_store=prepared.result_store,
            runtime_reference=prepared.runtime_reference,
            preparation=preparation,
        )
    return inspect_research_run(
        run=prepared.run,
        plan=prepared.plan,
        result_store=prepared.result_store,
        pairs=prepared.pairs,
        algorithm_validation=validation,
        primary_asset_role=BRIDGE_JAR_ROLE,
        verifier_software=prepared.verifier_software,
        preparation_manifest=manifest,
        external_issues=(
            (prepared.preparation_preflight_issue,)
            if prepared.preparation_preflight_issue
            else ()
        ),
    )


# --------------------------------------------------------------- finalize


def finalize_research_run(
    *,
    spec: ResearchExperimentSpec,
    preparer_factory: PreparerFactory,
    workspace: Path,
    dataset_root: Path | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
) -> ResearchRunReceipt:
    """Revalidate everything and publish one last immutable commit marker."""
    prepared = _load_prepared(
        spec=spec,
        preparer_factory=preparer_factory,
        workspace=workspace,
        dataset_root=dataset_root,
        repository_root=repository_root,
        run_id=run_id,
        require_source_match=False,
    )
    result_store = prepared.result_store

    prepared.bundle_store.require_valid(prepared.runtime_reference.bundle_id)

    completion_service = RunCompletionService(result_store=result_store)
    audit = completion_service.audit(run=prepared.run, plan=prepared.plan)
    if not audit.is_clean:
        raise ResearchPreflightError(
            f"run {prepared.run.run_id} does not audit cleanly: "
            f"{[issue.code.value for issue in audit.errors][:5]}"
        )

    preparation = _preparation_expectations(prepared)
    preparation_manifest = _preparation_manifest(prepared)
    validation = validate_sourceafis_result_set(
        run=prepared.run,
        plan=prepared.plan,
        pairs=prepared.pairs,
        images=prepared.images,
        result_store=result_store,
        runtime_reference=prepared.runtime_reference,
        preparation=preparation,
    )
    if not validation.is_clean:
        raise ResearchPreflightError(
            f"run {prepared.run.run_id} failed SourceAFIS validation "
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
        primary_asset_role=BRIDGE_JAR_ROLE,
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


def _development_config(
    *, repository_root: Path, build_jar: Path | None
) -> SourceAfisJavaConfig:
    settings: dict[str, Any] = {"project_root": Path(repository_root)}
    if build_jar is not None:
        settings["bridge_jar"] = Path(build_jar)
    return SourceAfisJavaConfig(**settings)


def _research_adapter(
    *,
    development: SourceAfisJavaConfig,
    bundle: RuntimeBundleDefinition,
    bundle_store: RuntimeBundleStore,
    software: SoftwareProvenance,
) -> ResearchModeAdapter:
    asset = bundle.asset(BRIDGE_JAR_ROLE)
    pinned = development.pinned_to(
        bridge_jar=bundle_store.asset_path(bundle.bundle_id, BRIDGE_JAR_ROLE),
        runtime_bundle_id=bundle.bundle_id,
        runtime_bundle_fingerprint=bundle.bundle_fingerprint,
        expected_bridge_jar_sha256=asset.sha256,
        expected_bridge_jar_size=asset.size_bytes,
        fpbench_source_revision=software.source_revision,
    )
    return ResearchModeAdapter(
        delegate=SourceAfisJavaAdapter(pinned),
        software=software,
        runtime_bundle=bundle,
    )


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


def _require_expected_plan(plan: ExecutionPlan, spec: ResearchExperimentSpec) -> None:
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
    prepared: PreparedResearchRun,
) -> CanonicalPreparationExpectations | None:
    """What every stored result of a canonical run must claim about its inputs.

    ``None`` for a native run: there is no input set to check results against,
    and inventing one would make the identity preparer's results fail a check
    they were never subject to (spec section 61).
    """
    spec = prepared.spec
    if not spec.is_canonical:
        return None
    preparer = prepared.preparer
    entries_of = getattr(preparer, "prepared_entries", None)
    if entries_of is None:  # pragma: no cover - only a canonical preparer gets here
        raise ResearchPreflightError(
            "a canonical run needs a preparer backed by a prepared-image set"
        )
    entries = entries_of()
    return CanonicalPreparationExpectations(
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
    prepared: PreparedResearchRun,
) -> PreparedImageSetManifest | None:
    if not prepared.spec.is_canonical:
        return None
    manifest_of = getattr(prepared.preparer, "prepared_manifest", None)
    if manifest_of is None:  # pragma: no cover - only canonical preparers reach here
        raise ResearchPreflightError(
            "a canonical run needs a verified PreparedImageSetManifest"
        )
    return manifest_of()


def _load_prepared(
    *,
    spec: ResearchExperimentSpec,
    preparer_factory: PreparerFactory,
    workspace: Path,
    dataset_root: Path | None,
    repository_root: Path,
    run_id: str | None,
    require_source_match: bool = True,
    run_preparer_preflight: bool = True,
) -> PreparedResearchRun:
    """Reconstruct a prepared run from what ``prepare`` already wrote.

    Never re-materialises and never re-plans. Execution requires the current
    revision to match the executor revision recorded by the run. Status and
    finalization instead preserve that recorded provenance while capturing the
    clean verifier revision that is checking it; otherwise a verifier fix could
    never be applied to an older completed run (docs/adr/0017).
    """
    workspace = Path(workspace)
    verifier_software = capture_research_provenance(repository_root)

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
    adapter = _research_adapter(
        development=_development_config(
            repository_root=repository_root, build_jar=None
        ),
        bundle=bundle,
        bundle_store=bundle_store,
        software=software,
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
            preparation_preflight_issue = (
                f"preparation-set preflight failed: {exc}"
            )

    return PreparedResearchRun(
        spec=spec,
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
    own manifests.
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
