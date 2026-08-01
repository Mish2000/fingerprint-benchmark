"""Applying a documented threshold to a finished SourceAFIS run, once.

Stage 5A wrote this logic for the native run. Stage 6B needs the identical logic
for the canonical run, and the honest way to get it is not to copy the file.

The two derivations differ in five things and no more: which experiment's run
pointer to read, which decision profile to apply, which protocol config states
the impostor shift, where the evidence copy goes, and what shape to expect. All
five are data. Everything else — revalidating the source run, applying the
threshold, deriving SELF eligibility, building the three views, verifying each of
them, writing the receipt and the marker, computing status — is one
implementation, and the argument of stage 6B depends on it *being* one
implementation.

If the two derivations were two files, then a difference between the native and
canonical numbers could be a difference in how they were derived. It cannot be,
because there is only one derivation.

Scope note, deliberate: this engine generalises over *two SourceAFIS runs*, not
over algorithms. It still reads a SourceAFIS validation report and still knows
what a bridge jar is. Hardening the interface for a second algorithm is a
separate piece of work with a different shape, and doing it speculatively here
would lock in the wrong one (spec section 3).
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from fpbench.adapters.sourceafis_java.config import BRIDGE_JAR_ROLE
from fpbench.core.derivation_models import (
    DecisionDerivationReceipt,
    DecisionDerivationState,
    DerivationDefinition,
    derivation_definition_fingerprint,
)
from fpbench.core.enums import ResearchRunStatus
from fpbench.core.errors import (
    DecisionDerivationError,
    DecisionFinalizationError,
    ResearchPreflightError,
    StorageError,
)
from fpbench.core.evaluation_view_models import (
    MATED_CONDITIONAL_VIEW,
    MATED_UNCONDITIONAL_VIEW,
    NON_MATED_SANITY_VIEW,
)
from fpbench.core.identifiers import PairId
from fpbench.core.models import ComparisonPair, ImageRecord
from fpbench.core.provenance_models import (
    SoftwareProvenance,
    software_provenance_fingerprint,
)
from fpbench.core.serialization import read_json, write_json
from fpbench.decisions import (
    DecisionProfile,
    apply_decision_profile,
    load_decision_profile,
    require_profile_applies_to_run,
    verify_decision_set,
)
from fpbench.derivations import (
    build_derivation_finalization_marker,
    build_derivation_receipt,
    inspect_decision_derivation,
    write_derivation_evidence_copy,
)
from fpbench.eligibility import (
    build_self_eligibility_units,
    derive_self_eligibility,
    require_self_independence_evidence,
    verify_eligibility_set,
)
from fpbench.evaluation import (
    build_mated_conditional_view,
    build_mated_unconditional_view,
    build_non_mated_sanity_view,
    verify_evaluation_view,
)
from fpbench.execution.research import inspect_research_run
from fpbench.experiments.sourceafis_research import read_run_pointer
from fpbench.experiments.sourceafis_validation import (
    CanonicalPreparationExpectations,
    validate_sourceafis_result_set,
)
from fpbench.storage.decision_set_store import DecisionSetStore
from fpbench.storage.definition_store import DefinitionStore
from fpbench.storage.eligibility_set_store import EligibilitySetStore
from fpbench.storage.evaluation_view_store import EvaluationViewStore
from fpbench.storage.manifest_store import ManifestStore
from fpbench.storage.plan_store import PlanStore
from fpbench.storage.result_set_store import ResultSetStore
from fpbench.storage.result_store import ResultStore

__all__ = [
    "SourceAfisDecisionExperimentSpec",
    "PreparedDerivation",
    "PreparationExpectationsFactory",
    "load_non_mated_finger_shift",
    "load_decision_source",
    "prepare_decision_derivation",
    "derive_decisions",
    "inspect_decisions",
    "finalize_decision_derivation",
    "read_decision_set_pointer",
    "VIEW_KINDS",
]

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]

_POINTER_NAME = "current-decision-set.json"

VIEW_KINDS = (
    MATED_UNCONDITIONAL_VIEW,
    MATED_CONDITIONAL_VIEW,
    NON_MATED_SANITY_VIEW,
)

#: Builds the canonical-input expectations a validator checks each result
#: against, given the workspace. ``None`` for a run whose images were passed
#: through untouched — there is no input set to check against, and inventing one
#: would fail 6,000 already-stored native results on a check they were never
#: subject to (spec section 61 of stage 6A).
PreparationExpectationsFactory = Any


@dataclass(frozen=True, slots=True)
class SourceAfisDecisionExperimentSpec:
    """The five things that distinguish one SourceAFIS derivation from another.

    ``source_experiment_id`` and ``protocol_config`` are additions to the shape
    the specification sketches. The engine has to resolve *which run* without
    importing either run experiment's module — that import is the coupling
    section 12 forbids — so the wrapper reads its own run config and hands over
    the two facts the engine needs from it.
    """

    experiment_id: str

    source_experiment_id: str
    source_experiment_config: Path
    protocol_config: Path

    decision_profile_config: Path
    evidence_directory: Path

    expected_decisions: int
    expected_eligibility_units: int
    expected_rows_per_view: int
    expected_units_per_release: int

    non_mated_finger_shift: int

    #: Present only for a derivation over a canonical run. The engine passes it
    #: straight to the SourceAFIS validator and never interprets it.
    preparation_expectations: PreparationExpectationsFactory = None


def load_non_mated_finger_shift(protocol_config: Path) -> int:
    """Read the impostor shift from the protocol rather than assuming it.

    The non-mated view records the pairing strategy it was actually built over,
    so a protocol that changed its shift must not be silently reported under the
    old one (docs/adr/0025).
    """
    document = yaml.safe_load(Path(protocol_config).read_text(encoding="utf-8")) or {}
    pairs = document.get("pairs") or {}
    non_mated = pairs.get("plain_roll_non_mated") or {}
    if isinstance(non_mated, bool):
        non_mated = {}
    return int(non_mated.get("finger_shift", 1))


@dataclass(frozen=True, slots=True)
class PreparedDerivation:
    """Everything ``derive``, ``status`` and ``finalize`` need, already checked."""

    spec: SourceAfisDecisionExperimentSpec
    software: SoftwareProvenance
    workspace: Path

    run: Any
    plan: Any
    pairs: Mapping[PairId, ComparisonPair]
    images: Mapping[str, ImageRecord]
    pair_manifest_hash: str

    result_set: Any
    result_set_entries: tuple

    profile: DecisionProfile
    definition: DerivationDefinition | None
    units: tuple
    research_status: ResearchRunStatus

    @property
    def config(self) -> SourceAfisDecisionExperimentSpec:
        """Historical name. Stage 5A callers said ``prepared.config``."""
        return self.spec

    @property
    def result_store(self) -> ResultStore:
        return ResultStore(self.workspace)

    @property
    def decision_store(self) -> DecisionSetStore:
        return DecisionSetStore(self.workspace)

    @property
    def eligibility_store(self) -> EligibilitySetStore:
        return EligibilitySetStore(self.workspace)

    @property
    def view_store(self) -> EvaluationViewStore:
        return EvaluationViewStore(self.workspace)


# ---------------------------------------------------------------- prepare


def prepare_decision_derivation(
    *,
    spec: SourceAfisDecisionExperimentSpec,
    workspace: Path,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
    require_expected_shape: bool = True,
) -> PreparedDerivation:
    """Pin the source, the profile and the derivation code. Decide nothing.

    Raises:
        ResearchPreflightError: the tree is dirty, or the source run is not
            research-ready.
        DecisionProfileApplicabilityError: the profile does not describe this run.
    """
    workspace = Path(workspace)
    software = _capture_research_provenance(repository_root)

    prepared = load_decision_source(
        spec=spec,
        workspace=workspace,
        repository_root=repository_root,
        run_id=run_id,
        software=software,
        require_expected_shape=require_expected_shape,
        require_definition=False,
    )

    definition = prepared.definition
    if definition is None:  # the clean-provenance capture above guarantees one
        raise ResearchPreflightError(
            "a clean derivation definition could not be constructed"
        )
    store = definition_store(workspace, spec.experiment_id)
    try:
        store.write(prepared.run.run_id, definition)
    except StorageError as exc:
        raise ResearchPreflightError(
            f"{exc}; a different source, profile or commit is a different "
            "derivation and needs its own definition"
        ) from exc
    return prepared


# ----------------------------------------------------------------- derive


def derive_decisions(
    *,
    spec: SourceAfisDecisionExperimentSpec,
    workspace: Path,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
    require_expected_shape: bool = True,
) -> str:
    """Build the decisions, the eligibility set and the three views.

    Returns:
        The decision set id.

    Idempotent: the same scores, profile and derivation code produce the same
    ids and rewrite nothing. Writes no finalization marker — until that exists,
    everything here is retryable work in progress (docs/adr/0020).
    """
    prepared = prepare_decision_derivation(
        spec=spec,
        workspace=workspace,
        repository_root=repository_root,
        run_id=run_id,
        require_expected_shape=require_expected_shape,
    )

    decision_set = apply_decision_profile(
        profile=prepared.profile,
        run=prepared.run,
        plan=prepared.plan,
        result_set=prepared.result_set,
        result_set_entries=prepared.result_set_entries,
        result_store=prepared.result_store,
        derivation_software=prepared.software,
    )
    verify_decision_set(
        profile=prepared.profile,
        manifest=decision_set.manifest,
        records=decision_set.records,
        run=prepared.run,
        plan=prepared.plan,
        result_set=prepared.result_set,
        result_set_entries=prepared.result_set_entries,
        result_store=prepared.result_store,
    )
    if require_expected_shape:
        _require_decision_shape(spec, decision_set.manifest)

    set_id = decision_set.manifest.decision_set_id
    prepared.decision_store.ensure_decision_set(
        profile=prepared.profile,
        manifest=decision_set.manifest,
        records=decision_set.records,
    )

    # SELF results must still prove two independent extractions before any
    # verdict rests on them. That a canonical SELF comparison points both sides
    # at one immutable PNG does not weaken it: independence is a property of
    # template extraction, not of resampling (docs/adr/0035, spec section 16).
    self_jobs = {unit.plain_self_job_id for unit in prepared.units} | {
        unit.roll_self_job_id for unit in prepared.units
    }
    require_self_independence_evidence(
        results=(
            prepared.result_store.read_raw_result(prepared.run.run_id, job_id)
            for job_id in sorted(self_jobs)
        )
    )

    decisions_by_job = decision_set.by_job()
    eligibility = derive_self_eligibility(
        run=prepared.run,
        units=prepared.units,
        decisions=decisions_by_job,
        decision_set=decision_set.manifest,
        pair_manifest_hash=prepared.pair_manifest_hash,
    )
    verify_eligibility_set(
        manifest=eligibility.manifest,
        records=eligibility.records,
        units=prepared.units,
        decisions=decisions_by_job,
        decision_set=decision_set.manifest,
        pair_manifest_hash=prepared.pair_manifest_hash,
    )
    if require_expected_shape:
        _require_eligibility_shape(spec, eligibility.records)

    prepared.eligibility_store.ensure_eligibility_set(
        decision_set_id=set_id,
        manifest=eligibility.manifest,
        records=eligibility.records,
    )

    views = _build_views(prepared, decision_set, eligibility)
    for view in views:
        verify_evaluation_view(
            manifest=view.manifest,
            entries=view.entries,
            run=prepared.run,
            plan=prepared.plan,
            pairs=prepared.pairs,
            decisions=decisions_by_job,
            decision_set=decision_set.manifest,
            eligibility=(
                eligibility.manifest
                if view.manifest.view_kind == MATED_CONDITIONAL_VIEW
                else None
            ),
            eligibility_records=eligibility.records,
            pair_manifest_hash=prepared.pair_manifest_hash,
            non_mated_finger_shift=spec.non_mated_finger_shift,
        )
        if (
            require_expected_shape
            and view.manifest.total_rows != spec.expected_rows_per_view
        ):
            raise DecisionDerivationError(
                f"view {view.manifest.view_kind} holds {view.manifest.total_rows} "
                f"rows, expected {spec.expected_rows_per_view}"
            )
        prepared.view_store.ensure_view(
            run_id=prepared.run.run_id,
            decision_set_id=set_id,
            manifest=view.manifest,
            entries=view.entries,
        )

    # Read everything back before claiming anything was written.
    prepared.decision_store.read_decision_set(prepared.run.run_id, set_id)
    prepared.eligibility_store.read_eligibility_set(prepared.run.run_id, set_id)
    for kind in VIEW_KINDS:
        prepared.view_store.read_view(prepared.run.run_id, set_id, kind)

    write_decision_set_pointer(
        workspace, spec.experiment_id, prepared.run.run_id, set_id
    )
    return set_id


# ----------------------------------------------------------------- status


def inspect_decisions(
    *,
    spec: SourceAfisDecisionExperimentSpec,
    workspace: Path,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
    decision_set_id: str | None = None,
) -> DecisionDerivationState:
    """Recompute the chain and report where it stands. Never writes."""
    workspace = Path(workspace)
    # Status must work on a dirty tree — it is how you find out what went wrong.
    software = _capture_permissive(repository_root)
    prepared = load_decision_source(
        spec=spec,
        workspace=workspace,
        repository_root=repository_root,
        run_id=run_id,
        software=software,
        require_expected_shape=False,
        require_definition=False,
    )
    resolved_set = decision_set_id or read_decision_set_pointer(
        workspace, spec.experiment_id, prepared.run.run_id
    )
    store = definition_store(workspace, spec.experiment_id)

    return inspect_decision_derivation(
        run=prepared.run,
        plan=prepared.plan,
        pairs=prepared.pairs,
        units=prepared.units,
        result_set=prepared.result_set,
        result_set_entries=prepared.result_set_entries,
        result_store=prepared.result_store,
        research_status=prepared.research_status,
        decision_profile=prepared.profile,
        definition=store.read_active(prepared.run.run_id),
        decision_set_id=resolved_set,
        pair_manifest_hash=prepared.pair_manifest_hash,
        non_mated_finger_shift=spec.non_mated_finger_shift,
        workspace=workspace,
    )


# --------------------------------------------------------------- finalize


def finalize_decision_derivation(
    *,
    spec: SourceAfisDecisionExperimentSpec,
    workspace: Path,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
    decision_set_id: str | None = None,
) -> DecisionDerivationReceipt:
    """Re-verify everything, then write the receipt and the marker.

    Order, and it is the point: source run, raw result set, decisions,
    eligibility, views, receipt, read-back, marker. A failure before the marker
    leaves the intermediates in place and retryable, and the derivation is simply
    not authoritative yet.
    """
    workspace = Path(workspace)
    software = _capture_research_provenance(repository_root)
    prepared = load_decision_source(
        spec=spec,
        workspace=workspace,
        repository_root=repository_root,
        run_id=run_id,
        software=software,
        require_expected_shape=True,
    )
    set_id = decision_set_id or read_decision_set_pointer(
        workspace, spec.experiment_id, prepared.run.run_id
    )
    if set_id is None:
        raise DecisionFinalizationError(
            "no derivation has been produced for this run; run 'derive' first"
        )

    store = prepared.decision_store
    profile, decision_manifest, records = store.read_decision_set(
        prepared.run.run_id, set_id
    )
    verify_decision_set(
        profile=profile,
        manifest=decision_manifest,
        records=records,
        run=prepared.run,
        plan=prepared.plan,
        result_set=prepared.result_set,
        result_set_entries=prepared.result_set_entries,
        result_store=prepared.result_store,
    )
    decisions_by_job = {record.job_id: record for record in records}

    eligibility_manifest, eligibility_records = (
        prepared.eligibility_store.read_eligibility_set(prepared.run.run_id, set_id)
    )
    verify_eligibility_set(
        manifest=eligibility_manifest,
        records=eligibility_records,
        units=prepared.units,
        decisions=decisions_by_job,
        decision_set=decision_manifest,
        pair_manifest_hash=prepared.pair_manifest_hash,
    )

    view_manifests = {}
    for kind in VIEW_KINDS:
        manifest, entries = prepared.view_store.read_view(
            prepared.run.run_id, set_id, kind
        )
        verify_evaluation_view(
            manifest=manifest,
            entries=entries,
            run=prepared.run,
            plan=prepared.plan,
            pairs=prepared.pairs,
            decisions=decisions_by_job,
            decision_set=decision_manifest,
            eligibility=(
                eligibility_manifest if kind == MATED_CONDITIONAL_VIEW else None
            ),
            eligibility_records=eligibility_records,
            pair_manifest_hash=prepared.pair_manifest_hash,
            non_mated_finger_shift=spec.non_mated_finger_shift,
        )
        view_manifests[kind] = manifest

    receipt = build_derivation_receipt(
        run=prepared.run,
        result_set=prepared.result_set,
        decision_set=decision_manifest,
        eligibility=eligibility_manifest,
        unconditional_view=view_manifests[MATED_UNCONDITIONAL_VIEW],
        conditional_view=view_manifests[MATED_CONDITIONAL_VIEW],
        non_mated_view=view_manifests[NON_MATED_SANITY_VIEW],
        derivation_software=prepared.software,
        pair_manifest_hash=prepared.pair_manifest_hash,
    )
    store.ensure_receipt(decision_set_id=set_id, receipt=receipt)
    stored_receipt = store.read_receipt(prepared.run.run_id, set_id)

    marker = build_derivation_finalization_marker(
        run=prepared.run,
        result_set=prepared.result_set,
        decision_set=decision_manifest,
        eligibility=eligibility_manifest,
        unconditional_view=view_manifests[MATED_UNCONDITIONAL_VIEW],
        conditional_view=view_manifests[MATED_CONDITIONAL_VIEW],
        non_mated_view=view_manifests[NON_MATED_SANITY_VIEW],
        receipt=stored_receipt,
        derivation_software=prepared.software,
    )
    store.ensure_finalization(
        run_id=prepared.run.run_id, decision_set_id=set_id, marker=marker
    )

    state = inspect_decision_derivation(
        run=prepared.run,
        plan=prepared.plan,
        pairs=prepared.pairs,
        units=prepared.units,
        result_set=prepared.result_set,
        result_set_entries=prepared.result_set_entries,
        result_store=prepared.result_store,
        research_status=prepared.research_status,
        decision_profile=prepared.profile,
        definition=prepared.definition,
        decision_set_id=set_id,
        pair_manifest_hash=prepared.pair_manifest_hash,
        non_mated_finger_shift=spec.non_mated_finger_shift,
        workspace=workspace,
    )
    if not state.is_decision_ready:
        raise DecisionFinalizationError(
            f"derivation {set_id} finalised but did not reach DECISION_READY: "
            f"{state.status.value} {list(state.issues)[:3]}"
        )

    write_derivation_evidence_copy(
        stored_receipt,
        repository_root=Path(repository_root),
        directory=spec.evidence_directory,
    )
    return stored_receipt


# ----------------------------------------------------------------- source


def load_decision_source(
    *,
    spec: SourceAfisDecisionExperimentSpec,
    workspace: Path,
    repository_root: Path,
    run_id: str | None,
    software: SoftwareProvenance,
    require_expected_shape: bool = True,
    require_definition: bool = True,
) -> PreparedDerivation:
    """Load and revalidate the finished research run and everything it implies.

    Public because the evaluation engine needs exactly this and nothing else: the
    same run, the same pair manifest, the same profile, revalidated the same way.
    A second implementation of "read the source chain" would be a second place for
    the two stages to disagree about what they are counting.

    The run is resolved through :func:`read_run_pointer` — the shared research
    layer — rather than by importing either run experiment's module. That import
    is the coupling section 12 forbids, and it would also make the canonical
    derivation depend on the native experiment for no reason.
    """
    workspace = Path(workspace)
    resolved_run = run_id or read_run_pointer(workspace, spec.source_experiment_id)

    result_store = ResultStore(workspace)
    run = result_store.read_run(resolved_run)
    plan = PlanStore(workspace).read_plan(resolved_run)
    result_set, result_set_entries = ResultSetStore(workspace).read_result_set(
        resolved_run
    )

    manifests = ManifestStore(workspace)
    protocol_id = run.protocol_id
    cohort_id = str(run.cohort_id)
    pairs_list = manifests.read_pairs(protocol_id, cohort_id)
    pairs = {pair.pair_id: pair for pair in pairs_list}
    pair_metadata = manifests.pair_manifest_metadata(protocol_id, cohort_id)
    pair_manifest_hash = pair_metadata["pair_manifest_hash"]

    # The dataset the pairs belong to, taken from the pairs themselves rather
    # than from a config that may have moved on since the run was executed.
    dataset_ids = {pair.dataset_id for pair in pairs_list}
    if len(dataset_ids) != 1:
        raise DecisionDerivationError(
            f"the pair manifest spans datasets {sorted(dataset_ids)}; a derivation "
            "covers one"
        )
    dataset_id = dataset_ids.pop()

    images: dict[str, ImageRecord] = {}
    for release in sorted({pair.release for pair in pairs_list}):
        for image in manifests.read_images(dataset_id, release):
            images[image.image_id] = image

    # The source run's own algorithm-evidence validation is re-run here rather
    # than taken on trust, because "research ready" is a claim about the current
    # files and this derivation is about to rest its entire weight on it.
    runtime_reference = result_store.read_runtime_reference(resolved_run)
    validation = validate_sourceafis_result_set(
        run=run,
        plan=plan,
        pairs=pairs,
        images=images,
        result_store=result_store,
        runtime_reference=runtime_reference,
        preparation=_preparation_expectations(spec, workspace),
    )
    research = inspect_research_run(
        run=run,
        plan=plan,
        result_store=result_store,
        pairs=pairs,
        algorithm_validation=validation,
        primary_asset_role=BRIDGE_JAR_ROLE,
        verifier_software=software,
    )
    if (
        require_expected_shape
        and research.status is not ResearchRunStatus.RESEARCH_READY
    ):
        raise ResearchPreflightError(
            f"run {resolved_run} is {research.status.value}, not research_ready; "
            f"decisions may only be derived from a finished run "
            f"{list(research.issues)[:3]}"
        )

    profile = load_decision_profile(
        spec.decision_profile_config,
        algorithm_fingerprint=run.algorithm_fingerprint,
    )
    require_profile_applies_to_run(profile=profile, run=run)

    jobs_by_pair = {
        str(planned.job.pair_id): planned.job.job_id for planned in plan.jobs
    }
    units = build_self_eligibility_units(
        pairs=pairs_list,
        images=images,
        jobs_by_pair=jobs_by_pair,
        protocol_id=protocol_id,
        cohort_id=cohort_id,
    )
    if require_expected_shape:
        _require_unit_shape(spec, units)

    definition = None
    if software.is_research_grade:
        claims = {
            "run_id": run.run_id,
            "run_fingerprint": run.run_fingerprint,
            "result_set_id": result_set.result_set_id,
            "result_set_fingerprint": result_set.result_set_fingerprint,
            "decision_profile_id": profile.profile_id,
            "decision_profile_fingerprint": profile.profile_fingerprint,
            "derivation_software": software,
            "derivation_software_fingerprint": software_provenance_fingerprint(
                software
            ),
            "derivation_source_commit": software.source_revision,
        }
        fingerprint = derivation_definition_fingerprint(claims)
        definition = DerivationDefinition(
            **claims,
            definition_id=f"derivation_{fingerprint[:12]}",
            definition_fingerprint=fingerprint,
            created_utc=_utc_now(),
        )

    if require_definition:
        if definition is None:
            raise ResearchPreflightError(
                "a derivation requires committed, clean software provenance"
            )
        store = definition_store(workspace, spec.experiment_id)
        stored_definition = store.read_active(run.run_id)
        if stored_definition is None:
            raise ResearchPreflightError(
                "no derivation definition is pinned for this run; run 'prepare' "
                "before deriving or finalising"
            )
        if (
            stored_definition.definition_fingerprint
            != definition.definition_fingerprint
        ):
            raise ResearchPreflightError(
                f"this run pins {stored_definition.definition_id}, but the current "
                f"source and environment compute {definition.definition_id}"
            )
        definition = stored_definition

    return PreparedDerivation(
        spec=spec,
        software=software,
        workspace=workspace,
        run=run,
        plan=plan,
        pairs=pairs,
        images=images,
        pair_manifest_hash=pair_manifest_hash,
        result_set=result_set,
        result_set_entries=result_set_entries,
        profile=profile,
        definition=definition,
        units=units,
        research_status=research.status,
    )


# ----------------------------------------------------------------- internals


def _preparation_expectations(
    spec: SourceAfisDecisionExperimentSpec, workspace: Path
) -> CanonicalPreparationExpectations | None:
    factory = spec.preparation_expectations
    if factory is None:
        return None
    return factory(workspace)


def _build_views(prepared: PreparedDerivation, decision_set, eligibility):
    decisions_by_job = decision_set.by_job()
    return (
        build_mated_unconditional_view(
            run=prepared.run,
            plan=prepared.plan,
            pairs=prepared.pairs,
            decisions=decisions_by_job,
            decision_set=decision_set.manifest,
            pair_manifest_hash=prepared.pair_manifest_hash,
        ),
        build_mated_conditional_view(
            run=prepared.run,
            plan=prepared.plan,
            pairs=prepared.pairs,
            decisions=decisions_by_job,
            decision_set=decision_set.manifest,
            eligibility=eligibility.manifest,
            eligibility_records=eligibility.records,
            pair_manifest_hash=prepared.pair_manifest_hash,
        ),
        build_non_mated_sanity_view(
            run=prepared.run,
            plan=prepared.plan,
            pairs=prepared.pairs,
            decisions=decisions_by_job,
            decision_set=decision_set.manifest,
            pair_manifest_hash=prepared.pair_manifest_hash,
            finger_shift=prepared.spec.non_mated_finger_shift,
        ),
    )


def _require_decision_shape(spec: SourceAfisDecisionExperimentSpec, manifest) -> None:
    if manifest.total_decisions != spec.expected_decisions:
        raise DecisionDerivationError(
            f"the derivation holds {manifest.total_decisions} decisions, expected "
            f"{spec.expected_decisions}"
        )
    if manifest.undecidable_count:
        # Every stored result of both runs is a success — each run's own receipt
        # says so. An undecidable decision would mean the scores changed under
        # the receipt, which is a contradiction rather than a new outcome.
        raise DecisionDerivationError(
            f"{manifest.undecidable_count} comparison(s) could not be decided, but "
            "the source run's receipt records no failures; the raw results and the "
            "receipt disagree"
        )


def _require_eligibility_shape(
    spec: SourceAfisDecisionExperimentSpec, records: Sequence
) -> None:
    if len(records) != spec.expected_eligibility_units:
        raise DecisionDerivationError(
            f"the derivation holds {len(records)} eligibility units, expected "
            f"{spec.expected_eligibility_units}"
        )
    per_release: dict[str, int] = {}
    for record in records:
        per_release[record.release] = per_release.get(record.release, 0) + 1
    unexpected = {
        release: count
        for release, count in per_release.items()
        if count != spec.expected_units_per_release
    }
    if unexpected:
        raise DecisionDerivationError(
            f"eligibility units per release are {per_release}, expected "
            f"{spec.expected_units_per_release} each"
        )


def _require_unit_shape(
    spec: SourceAfisDecisionExperimentSpec, units: Sequence
) -> None:
    if len(units) != spec.expected_eligibility_units:
        raise DecisionDerivationError(
            f"the pair manifest yields {len(units)} eligibility units, expected "
            f"{spec.expected_eligibility_units}"
        )


def _capture_research_provenance(repository_root: Path) -> SoftwareProvenance:
    from fpbench.provenance.software import capture_software_provenance

    return capture_software_provenance(
        repository_root=Path(repository_root), require_clean=True
    )


def _capture_permissive(repository_root: Path) -> SoftwareProvenance:
    from fpbench.provenance.software import capture_software_provenance

    return capture_software_provenance(
        repository_root=Path(repository_root), require_clean=False
    )


def definition_store(workspace: Path, experiment_id: str) -> DefinitionStore:
    """The namespaced definition store, still reading stage 5A's flat file.

    The native derivation this project has already finalised was pinned by a
    ``definition.json`` sitting directly beside the pointer. That file is cited
    by a committed receipt and a finalization marker; moving it would invalidate
    a verified chain to achieve nothing, so the store reads it where it is and
    writes any *new* definition under its own id.
    """
    return DefinitionStore(
        Path(workspace),
        experiment_id=experiment_id,
        loader=lambda payload: DerivationDefinition(**payload),
        pointer_name=_POINTER_NAME,
    )


def _pointer_path(workspace: Path, experiment_id: str, run_id: str) -> Path:
    return Path(workspace) / "derivations" / experiment_id / run_id / _POINTER_NAME


def write_decision_set_pointer(
    workspace: Path, experiment_id: str, run_id: str, decision_set_id: str
) -> Path:
    return write_json(
        _pointer_path(workspace, experiment_id, run_id),
        {
            "experiment_id": experiment_id,
            "run_id": run_id,
            "decision_set_id": decision_set_id,
            "derived_utc": _utc_now(),
        },
    )


def read_decision_set_pointer(
    workspace: Path, experiment_id: str, run_id: str
) -> str | None:
    path = _pointer_path(workspace, experiment_id, run_id)
    if not path.is_file():
        return None
    payload = read_json(path)
    return str(payload.get("decision_set_id") or "") or None


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()
