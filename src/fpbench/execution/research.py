"""How much of a run's evidence chain is actually in place.

``VERIFIED`` is a strong claim and still not the one a thesis needs. It says
every planned comparison has a result and an audit found nothing wrong with any
of them. It says nothing about *which build of which matcher* produced them,
*which revision of this harness* drove it, or whether the exact ordered
collection of scores has an identity a later chapter can cite and re-check.

``RESEARCH_READY`` is the claim that all four hold at once, re-tested from the
files every time it is asked for. Like ``RunProgress``, nothing here is cached
and no manifest is taken at its word: a completion, a runtime reference, a
result set and a receipt are each a *claim about files*, and each is compared
against the files it claims about (docs/adr/0012, docs/adr/0020).

:class:`ResearchModeAdapter` is the other half. A research run's environment
fingerprint covers its source revision and its runtime bundle, so the adapter
the runner preflights against has to report that same environment — otherwise
every resumed invocation would fail preflight against the run it created. The
wrapper adds nothing of its own: it re-derives the research environment from
the delegate's live report on every call, so a jar that changed since the run
was defined still surfaces as a mismatch rather than being papered over.
"""

from __future__ import annotations

import datetime as _dt

from fpbench.adapters.base import FingerprintAlgorithmAdapter
from fpbench.core.enums import EnvironmentStatus, ResearchRunStatus, RunState
from fpbench.core.errors import StorageError
from fpbench.core.execution_models import (
    AlgorithmDescriptor,
    ComparisonContext,
    EnvironmentReport,
    PreparedImage,
    RawMatchResult,
)
from fpbench.core.execution_plan_models import ExecutionPlan
from fpbench.core.provenance_models import SoftwareProvenance
from fpbench.core.research_models import ResearchRunState
from fpbench.core.result_models import RunDefinition
from fpbench.core.runtime_models import RuntimeBundleDefinition
from fpbench.execution.progress import inspect_run_progress
from fpbench.provenance.environment import build_research_environment
from fpbench.storage.plan_store import PlanStore
from fpbench.storage.result_set_store import ResultSetStore
from fpbench.storage.result_store import ResultStore
from fpbench.storage.runtime_bundle_store import RuntimeBundleStore

__all__ = ["ResearchModeAdapter", "inspect_research_run"]


class ResearchModeAdapter(FingerprintAlgorithmAdapter):
    """An adapter that reports its environment with provenance folded in.

    Delegates ``descriptor`` and ``compare`` untouched — the algorithm's
    identity and its scores are none of this class's business, and a wrapper
    that altered either would be exactly the algorithm-specific machinery
    docs/adr/0007 exists to prevent.
    """

    def __init__(
        self,
        *,
        delegate: FingerprintAlgorithmAdapter,
        software: SoftwareProvenance,
        runtime_bundle: RuntimeBundleDefinition,
    ) -> None:
        self._delegate = delegate
        self._software = software
        self._runtime_bundle = runtime_bundle

    @property
    def delegate(self) -> FingerprintAlgorithmAdapter:
        return self._delegate

    @property
    def descriptor(self) -> AlgorithmDescriptor:
        return self._delegate.descriptor

    def validate_environment(self) -> EnvironmentReport:
        """The delegate's environment, plus source revision and runtime bundle.

        An UNAVAILABLE delegate is returned unchanged rather than being
        decorated: there is no useful research environment on a machine that
        cannot run the algorithm at all, and the reason must survive intact for
        whoever reads the report.
        """
        report = self._delegate.validate_environment()
        if report.status is not EnvironmentStatus.READY:
            return report
        return build_research_environment(
            adapter_environment=report,
            software=self._software,
            runtime_bundle=self._runtime_bundle,
        )

    def compare(
        self,
        left: PreparedImage,
        right: PreparedImage,
        context: ComparisonContext,
    ) -> RawMatchResult:
        return self._delegate.compare(left, right, context)


def inspect_research_run(
    *,
    run: RunDefinition,
    plan: ExecutionPlan,
    result_store: ResultStore,
    plan_store: PlanStore | None = None,
    result_set_store: ResultSetStore | None = None,
    bundle_store: RuntimeBundleStore | None = None,
) -> ResearchRunState:
    """Recompute how far along the evidence chain ``run`` is.

    Never raises for a run that is merely unfinished or even broken; the state
    is the answer. It raises only when a store cannot be constructed at all.
    """
    plan_store = plan_store or PlanStore(result_store.root)
    result_set_store = result_set_store or ResultSetStore(result_store.root)
    bundle_store = bundle_store or RuntimeBundleStore(result_store.root)

    progress = inspect_run_progress(run=run, plan=plan, result_store=result_store)
    issues: list[str] = []

    prepared = (
        result_store.run_manifest_path(run.run_id).is_file()
        and plan_store.has_plan(run.run_id)
        and result_store.has_runtime_reference(run.run_id)
    )

    runtime_present = result_store.has_runtime_reference(run.run_id)
    runtime_valid = False
    if runtime_present:
        runtime_valid = _check_runtime(
            run=run,
            result_store=result_store,
            bundle_store=bundle_store,
            issues=issues,
        )

    result_set_present = result_set_store.has_result_set(run.run_id)
    result_set_valid = False
    if result_set_present:
        result_set_valid = _check_result_set(
            run=run,
            plan=plan,
            result_store=result_store,
            result_set_store=result_set_store,
            issues=issues,
        )

    receipt_present = result_store.has_research_receipt(run.run_id)
    receipt_valid = False
    if receipt_present:
        receipt_valid = _check_receipt(
            run=run,
            plan=plan,
            result_store=result_store,
            result_set_store=result_set_store,
            issues=issues,
        )

    status = _status(
        prepared=prepared,
        progress_state=progress.state,
        stored=progress.stored_results,
        missing=progress.missing_results,
        runtime_valid=runtime_valid,
        result_set_valid=result_set_valid,
        receipt_valid=receipt_valid,
        issues=issues,
    )

    return ResearchRunState(
        run_id=run.run_id,
        plan_id=plan.plan_id,
        status=status,
        core_state=progress.state,
        planned_jobs=progress.planned_jobs,
        stored_results=progress.stored_results,
        missing_results=progress.missing_results,
        runtime_reference_present=runtime_present,
        runtime_bundle_valid=runtime_valid,
        result_set_present=result_set_present,
        result_set_valid=result_set_valid,
        receipt_present=receipt_present,
        receipt_valid=receipt_valid,
        issues=tuple(issues),
        inspected_utc=_dt.datetime.now(_dt.timezone.utc).isoformat(),
    )


# ----------------------------------------------------------------- internals


def _status(
    *,
    prepared: bool,
    progress_state: RunState,
    stored: int,
    missing: int,
    runtime_valid: bool,
    result_set_valid: bool,
    receipt_valid: bool,
    issues: list[str],
) -> ResearchRunStatus:
    if progress_state is RunState.INVALID or issues:
        return ResearchRunStatus.INVALID
    if not prepared:
        return ResearchRunStatus.NOT_PREPARED
    if not runtime_valid:
        return ResearchRunStatus.INVALID
    if stored == 0:
        return ResearchRunStatus.PREPARED
    if missing:
        return ResearchRunStatus.PARTIAL
    if progress_state is not RunState.VERIFIED:
        return ResearchRunStatus.RESULTS_COMPLETE
    if result_set_valid and receipt_valid:
        return ResearchRunStatus.RESEARCH_READY
    return ResearchRunStatus.CORE_VERIFIED


def _check_runtime(
    *,
    run: RunDefinition,
    result_store: ResultStore,
    bundle_store: RuntimeBundleStore,
    issues: list[str],
) -> bool:
    try:
        reference = result_store.read_runtime_reference(run.run_id)
    except (StorageError, ValueError) as exc:
        issues.append(f"the runtime reference cannot be read ({type(exc).__name__})")
        return False

    if reference.run_fingerprint != run.run_fingerprint:
        issues.append("the runtime reference describes a different run")
        return False
    if reference.environment_fingerprint != run.environment_fingerprint:
        issues.append("the runtime reference describes a different environment")
        return False

    # The run's own environment has to name the same bundle. Without this a
    # reference could be swapped for one pointing at a different executable
    # while the run manifest went on claiming the original.
    dependencies = run.environment.dependencies
    for key, expected in (
        ("runtime.bundle.id", reference.bundle_id),
        ("runtime.bundle.fingerprint", reference.bundle_fingerprint),
    ):
        if dependencies.get(key) != expected:
            issues.append(
                f"the run environment's {key} does not match the runtime reference"
            )
            return False

    try:
        verification = bundle_store.verify_bundle(reference.bundle_id)
    except (StorageError, ValueError) as exc:
        issues.append(f"the runtime bundle cannot be read ({type(exc).__name__})")
        return False
    if not verification.is_valid:
        issues.append(f"runtime bundle: {verification.issues[0]}")
        return False

    bundle = bundle_store.read_bundle(reference.bundle_id)
    if dict(bundle.asset_sha256s()) != dict(reference.asset_sha256s):
        issues.append("the runtime bundle no longer holds the assets the run used")
        return False
    return True


def _check_result_set(
    *,
    run: RunDefinition,
    plan: ExecutionPlan,
    result_store: ResultStore,
    result_set_store: ResultSetStore,
    issues: list[str],
) -> bool:
    try:
        manifest = result_set_store.verify_result_set(run.run_id)
    except (StorageError, ValueError) as exc:
        issues.append(f"the result set does not hold up ({exc})")
        return False
    if manifest.run_fingerprint != run.run_fingerprint:
        issues.append("the result set describes a different run")
        return False
    if manifest.plan_fingerprint != plan.definition.plan_fingerprint:
        issues.append("the result set describes a different plan")
        return False
    if manifest.total_results != plan.total_jobs:
        issues.append(
            f"the result set holds {manifest.total_results} results for "
            f"{plan.total_jobs} planned jobs"
        )
        return False
    return True


def _check_receipt(
    *,
    run: RunDefinition,
    plan: ExecutionPlan,
    result_store: ResultStore,
    result_set_store: ResultSetStore,
    issues: list[str],
) -> bool:
    try:
        receipt = result_store.read_research_receipt(run.run_id)
    except (StorageError, ValueError) as exc:
        issues.append(f"the research receipt cannot be read ({type(exc).__name__})")
        return False

    if receipt.run_fingerprint != run.run_fingerprint:
        issues.append("the research receipt describes a different run")
        return False
    if receipt.plan_fingerprint != plan.definition.plan_fingerprint:
        issues.append("the research receipt describes a different plan")
        return False

    try:
        manifest = result_set_store.read_manifest(run.run_id)
    except (StorageError, ValueError):
        issues.append("the research receipt cites a result set that is not stored")
        return False
    if receipt.result_set_fingerprint != manifest.result_set_fingerprint:
        issues.append("the research receipt cites a different result set")
        return False

    try:
        completion = result_store.read_completion(run.run_id)
    except (StorageError, ValueError):
        issues.append("the research receipt cites a completion that is not stored")
        return False
    if receipt.completion_fingerprint != completion.completion_fingerprint:
        issues.append("the research receipt cites a different completion")
        return False
    return True
