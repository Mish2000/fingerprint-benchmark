"""Applying threshold 40 to the 6,000 SourceAFIS scores, in four commands.

    python -m fpbench.experiments.sourceafis_native_decisions prepare
    python -m fpbench.experiments.sourceafis_native_decisions derive
    python -m fpbench.experiments.sourceafis_native_decisions status
    python -m fpbench.experiments.sourceafis_native_decisions finalize

The shape mirrors ``sourceafis_native_full`` deliberately, because the failure
modes are the same shape too. ``prepare`` is where a dirty tree, a source run
that is not research-ready, or a profile that does not describe this algorithm
build stops everything before a single decision exists. ``derive`` does the work
and can be repeated. ``finalize`` re-verifies the whole chain and only then
writes the receipt and the marker that make it authoritative.

This module reads. It never runs Java, never touches a raw result file except to
hash it, and never writes anything under the run's own directories other than
the new ``decisions/`` subtree. The 6,000 scores it interprets are exactly the
6,000 scores stage 4B produced, and they are not modified by anything here
(docs/adr/0022).

What it does *not* do bears repeating, because a file called
"native_decisions" invites the assumption: it computes no rate, no
distribution, and no accuracy figure of any kind. It says which comparisons
crossed a documented threshold and which fingers are usable for conditional
reporting. Turning that into a measurement needs denominators nobody has agreed
yet (docs/adr/0003).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from fpbench.core.derivation_models import (
    DecisionDerivationState,
    DecisionDerivationReceipt,
    DerivationDefinition,
    derivation_definition_fingerprint,
)
from fpbench.core.enums import ProtocolStage, ResearchRunStatus
from fpbench.core.errors import (
    ConfigurationError,
    DecisionDerivationError,
    DecisionFinalizationError,
    DecisionProfileError,
    DerivationError,
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
from fpbench.adapters.sourceafis_java.config import BRIDGE_JAR_ROLE
from fpbench.experiments.sourceafis_native_full import (
    REPOSITORY_ROOT,
    capture_research_provenance,
    load_experiment_config,
)
from fpbench.experiments.sourceafis_validation import validate_sourceafis_result_set
from fpbench.storage.decision_set_store import DecisionSetStore
from fpbench.storage.definition_store import DefinitionStore
from fpbench.storage.eligibility_set_store import EligibilitySetStore
from fpbench.storage.evaluation_view_store import EvaluationViewStore
from fpbench.storage.manifest_store import ManifestStore
from fpbench.storage.plan_store import PlanStore
from fpbench.storage.result_set_store import ResultSetStore
from fpbench.storage.result_store import ResultStore

__all__ = [
    "DecisionExperimentConfig",
    "PreparedDerivation",
    "load_decision_experiment_config",
    "load_decision_source",
    "prepare_decision_derivation",
    "derive_decisions",
    "inspect_sourceafis_native_decisions",
    "finalize_decision_derivation",
    "EXPECTED_DECISIONS",
    "EXPECTED_ELIGIBILITY_UNITS",
    "EXPECTED_VIEW_ROWS",
    "main",
]

DEFAULT_WORKSPACE = REPOSITORY_ROOT / "workspace"
DEFAULT_DECISION_CONFIG = (
    REPOSITORY_ROOT
    / "configs"
    / "decisions"
    / "sourceafis_java_3_18_1_documented_40_v1.yaml"
)

#: The shape stage 4B's run implies. Asserted in this module rather than in the
#: generic derivation code, for the same reason the 6,000-job counts live in the
#: run's experiment module: they are true of this protocol, not of derivations.
EXPECTED_DECISIONS = 6_000
EXPECTED_ELIGIBILITY_UNITS = 1_500
EXPECTED_UNITS_PER_RELEASE = 500
EXPECTED_VIEW_ROWS = 1_500

_EXPERIMENT_ID = "sourceafis_native_decisions_v1"
_POINTER_NAME = "current-decision-set.json"


# ------------------------------------------------------------------- config


@dataclass(frozen=True, slots=True)
class DecisionExperimentConfig:
    """Which run to decide, with which profile."""

    experiment_id: str
    decision_profile_config: Path
    source_experiment_config: Path
    non_mated_finger_shift: int


def load_decision_experiment_config(
    *,
    decision_profile_config: Path = DEFAULT_DECISION_CONFIG,
    repository_root: Path = REPOSITORY_ROOT,
) -> DecisionExperimentConfig:
    """Assemble the derivation's configuration.

    The protocol's impostor shift is read from the protocol config rather than
    assumed, because the non-mated view has to record the pairing strategy it
    was actually built over (docs/adr/0025).
    """
    source = load_experiment_config(repository_root=repository_root)
    document = yaml.safe_load(
        Path(source.protocol_config).read_text(encoding="utf-8")
    ) or {}
    pairs = document.get("pairs") or {}
    non_mated = pairs.get("plain_roll_non_mated") or {}
    if isinstance(non_mated, bool):
        non_mated = {}
    shift = int(non_mated.get("finger_shift", 1))

    return DecisionExperimentConfig(
        experiment_id=_EXPERIMENT_ID,
        decision_profile_config=Path(decision_profile_config),
        source_experiment_config=Path(source.protocol_config),
        non_mated_finger_shift=shift,
    )


# --------------------------------------------------------------- prepared


@dataclass(frozen=True, slots=True)
class PreparedDerivation:
    """Everything ``derive``, ``status`` and ``finalize`` need, already checked."""

    config: DecisionExperimentConfig
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
    workspace: Path = DEFAULT_WORKSPACE,
    config: DecisionExperimentConfig | None = None,
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
    config = config or load_decision_experiment_config(
        repository_root=repository_root
    )
    software = capture_research_provenance(repository_root)

    prepared = _load_source(
        workspace=workspace,
        repository_root=repository_root,
        run_id=run_id,
        config=config,
        software=software,
        require_expected_shape=require_expected_shape,
        require_definition=False,
    )

    definition = prepared.definition
    if definition is None:  # capture_research_provenance guarantees this is clean
        raise ResearchPreflightError(
            "a clean derivation definition could not be constructed"
        )
    store = _definition_store(workspace, config.experiment_id)
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
    workspace: Path = DEFAULT_WORKSPACE,
    config: DecisionExperimentConfig | None = None,
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
        workspace=workspace,
        config=config,
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
        _require_decision_shape(decision_set.manifest)

    set_id = decision_set.manifest.decision_set_id
    prepared.decision_store.ensure_decision_set(
        profile=prepared.profile,
        manifest=decision_set.manifest,
        records=decision_set.records,
    )

    # SELF results must still prove two independent extractions before any
    # verdict rests on them (spec section 28).
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
        _require_eligibility_shape(eligibility.records)

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
            non_mated_finger_shift=prepared.config.non_mated_finger_shift,
        )
        if require_expected_shape and view.manifest.total_rows != EXPECTED_VIEW_ROWS:
            raise DecisionDerivationError(
                f"view {view.manifest.view_kind} holds {view.manifest.total_rows} "
                f"rows, expected {EXPECTED_VIEW_ROWS}"
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
    for kind in (MATED_UNCONDITIONAL_VIEW, MATED_CONDITIONAL_VIEW, NON_MATED_SANITY_VIEW):
        prepared.view_store.read_view(prepared.run.run_id, set_id, kind)

    _write_pointer(workspace, prepared.config.experiment_id, prepared.run.run_id, set_id)
    return set_id


# ----------------------------------------------------------------- status


def inspect_sourceafis_native_decisions(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    config: DecisionExperimentConfig | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
    decision_set_id: str | None = None,
) -> DecisionDerivationState:
    """Recompute the chain and report where it stands. Never writes."""
    workspace = Path(workspace)
    config = config or load_decision_experiment_config(
        repository_root=repository_root
    )
    # Status must work on a dirty tree — it is how you find out what went wrong.
    software = _capture_permissive(repository_root)
    prepared = _load_source(
        workspace=workspace,
        repository_root=repository_root,
        run_id=run_id,
        config=config,
        software=software,
        require_expected_shape=False,
        require_definition=False,
    )
    resolved_set = decision_set_id or _read_pointer(
        workspace, config.experiment_id, prepared.run.run_id
    )
    store = _definition_store(workspace, config.experiment_id)
    definition = store.read_active(prepared.run.run_id)

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
        definition=definition,
        decision_set_id=resolved_set,
        pair_manifest_hash=prepared.pair_manifest_hash,
        non_mated_finger_shift=prepared.config.non_mated_finger_shift,
        workspace=workspace,
    )


# --------------------------------------------------------------- finalize


def finalize_decision_derivation(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    config: DecisionExperimentConfig | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
    decision_set_id: str | None = None,
) -> DecisionDerivationReceipt:
    """Re-verify everything, then write the receipt and the marker.

    Order, and it is the point (spec section 52): source run, raw result set,
    decisions, eligibility, views, receipt, read-back, marker. A failure before
    the marker leaves the intermediates in place and retryable, and the
    derivation is simply not authoritative yet.
    """
    workspace = Path(workspace)
    config = config or load_decision_experiment_config(
        repository_root=repository_root
    )
    software = capture_research_provenance(repository_root)
    prepared = _load_source(
        workspace=workspace,
        repository_root=repository_root,
        run_id=run_id,
        config=config,
        software=software,
        require_expected_shape=True,
    )
    set_id = decision_set_id or _read_pointer(
        workspace, config.experiment_id, prepared.run.run_id
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
    for kind in (MATED_UNCONDITIONAL_VIEW, MATED_CONDITIONAL_VIEW, NON_MATED_SANITY_VIEW):
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
            non_mated_finger_shift=prepared.config.non_mated_finger_shift,
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
        non_mated_finger_shift=prepared.config.non_mated_finger_shift,
        workspace=workspace,
    )
    if not state.is_decision_ready:
        raise DecisionFinalizationError(
            f"derivation {set_id} finalised but did not reach DECISION_READY: "
            f"{state.status.value} {list(state.issues)[:3]}"
        )

    write_derivation_evidence_copy(
        stored_receipt, repository_root=Path(repository_root)
    )
    return stored_receipt


# ----------------------------------------------------------------- helpers


def load_decision_source(
    *,
    workspace: Path,
    repository_root: Path,
    run_id: str | None,
    config: DecisionExperimentConfig,
    software: SoftwareProvenance,
    require_expected_shape: bool = True,
    require_definition: bool = True,
) -> PreparedDerivation:
    """Load and revalidate the finished research run and everything it implies.

    Public because stage 5B needs exactly this and nothing else: the same run,
    the same pair manifest, the same profile, revalidated the same way. A second
    implementation of "read the source chain" would be a second place for the two
    stages to disagree about what they are counting.
    """
    return _load_source(
        workspace=workspace,
        repository_root=repository_root,
        run_id=run_id,
        config=config,
        software=software,
        require_expected_shape=require_expected_shape,
        require_definition=require_definition,
    )


def _load_source(
    *,
    workspace: Path,
    repository_root: Path,
    run_id: str | None,
    config: DecisionExperimentConfig,
    software: SoftwareProvenance,
    require_expected_shape: bool,
    require_definition: bool = True,
) -> PreparedDerivation:
    """Read the finished research run and everything derived from its manifests."""
    from fpbench.experiments.sourceafis_native_full import load_experiment_config
    from fpbench.experiments.sourceafis_research import (
        read_run_pointer as _read_run_pointer,
    )

    source_config = load_experiment_config(repository_root=repository_root)
    resolved_run = run_id or _read_run_pointer(workspace, source_config.experiment_id)

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
    # files and this derivation is about to rest its entire weight on it
    # (spec section 2).
    runtime_reference = result_store.read_runtime_reference(resolved_run)
    validation = validate_sourceafis_result_set(
        run=run,
        plan=plan,
        pairs=pairs,
        images=images,
        result_store=result_store,
        runtime_reference=runtime_reference,
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
    if require_expected_shape and research.status is not ResearchRunStatus.RESEARCH_READY:
        raise ResearchPreflightError(
            f"run {resolved_run} is {research.status.value}, not research_ready; "
            f"decisions may only be derived from a finished run "
            f"{list(research.issues)[:3]}"
        )

    profile = load_decision_profile(
        config.decision_profile_config,
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
        _require_unit_shape(units)

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
        store = _definition_store(workspace, config.experiment_id)
        stored_definition = store.read_active(run.run_id)
        if stored_definition is None:
            raise ResearchPreflightError(
                "no derivation definition is pinned for this run; run 'prepare' "
                "before deriving or finalising"
            )
        if stored_definition.definition_fingerprint != definition.definition_fingerprint:
            raise ResearchPreflightError(
                f"this run pins {stored_definition.definition_id}, but the current "
                f"source and environment compute {definition.definition_id}"
            )
        definition = stored_definition

    return PreparedDerivation(
        config=config,
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
            finger_shift=prepared.config.non_mated_finger_shift,
        ),
    )


def _require_decision_shape(manifest) -> None:
    if manifest.total_decisions != EXPECTED_DECISIONS:
        raise DecisionDerivationError(
            f"the derivation holds {manifest.total_decisions} decisions, expected "
            f"{EXPECTED_DECISIONS}"
        )
    if manifest.undecidable_count:
        # Every one of the 6,000 stored results is a success — the run's own
        # receipt says so. An undecidable decision would mean the scores changed
        # under the receipt, which is a contradiction rather than a new outcome.
        raise DecisionDerivationError(
            f"{manifest.undecidable_count} comparison(s) could not be decided, but "
            "the source run's receipt records no failures; the raw results and the "
            "receipt disagree"
        )


def _require_eligibility_shape(records: Sequence) -> None:
    if len(records) != EXPECTED_ELIGIBILITY_UNITS:
        raise DecisionDerivationError(
            f"the derivation holds {len(records)} eligibility units, expected "
            f"{EXPECTED_ELIGIBILITY_UNITS}"
        )
    per_release: dict[str, int] = {}
    for record in records:
        per_release[record.release] = per_release.get(record.release, 0) + 1
    unexpected = {
        release: count
        for release, count in per_release.items()
        if count != EXPECTED_UNITS_PER_RELEASE
    }
    if unexpected:
        raise DecisionDerivationError(
            f"eligibility units per release are {per_release}, expected "
            f"{EXPECTED_UNITS_PER_RELEASE} each"
        )


def _require_unit_shape(units: Sequence) -> None:
    if len(units) != EXPECTED_ELIGIBILITY_UNITS:
        raise DecisionDerivationError(
            f"the pair manifest yields {len(units)} eligibility units, expected "
            f"{EXPECTED_ELIGIBILITY_UNITS}"
        )


def _capture_permissive(repository_root: Path) -> SoftwareProvenance:
    from fpbench.provenance.software import capture_software_provenance

    return capture_software_provenance(
        repository_root=Path(repository_root), require_clean=False
    )


def _definition_store(workspace: Path, experiment_id: str) -> DefinitionStore:
    """The namespaced definition store, still reading stage 5A's flat file.

    The derivation this project has already finalised was pinned by a
    ``definition.json`` sitting directly beside the pointer. That file is cited
    by a committed receipt and a finalization marker; moving it would invalidate
    a verified chain to achieve nothing, so the store reads it where it is and
    writes any *new* definition under its own id (spec section 35).
    """
    return DefinitionStore(
        Path(workspace),
        experiment_id=experiment_id,
        loader=lambda payload: DerivationDefinition(**payload),
        pointer_name=_POINTER_NAME,
    )


def _pointer_path(workspace: Path, experiment_id: str, run_id: str) -> Path:
    return Path(workspace) / "derivations" / experiment_id / run_id / _POINTER_NAME


def _write_pointer(
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


def _read_pointer(workspace: Path, experiment_id: str, run_id: str) -> str | None:
    path = _pointer_path(workspace, experiment_id, run_id)
    if not path.is_file():
        return None
    payload = read_json(path)
    return str(payload.get("decision_set_id") or "") or None


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


# --------------------------------------------------------------------- CLI


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m fpbench.experiments.sourceafis_native_decisions",
        description=(
            "Apply a documented threshold to a finished SourceAFIS run. Produces "
            "decisions, SELF eligibility and evaluation views; computes no metric "
            "and makes no accuracy claim."
        ),
    )
    parser.add_argument("command", choices=("prepare", "derive", "status", "finalize"))
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument("--profile", type=Path, default=DEFAULT_DECISION_CONFIG)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--decision-set-id", default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(list(argv) if argv is not None else None)
    try:
        config = load_decision_experiment_config(
            decision_profile_config=arguments.profile
        )
        shared = {"workspace": arguments.workspace, "config": config}

        if arguments.command == "prepare":
            prepared = prepare_decision_derivation(**shared, run_id=arguments.run_id)
            print(f"run          {prepared.run.run_id}")
            print(f"result set   {prepared.result_set.result_set_id}")
            print(f"profile      {prepared.profile.profile_id}")
            print(f"threshold    {prepared.profile.threshold} "
                  f"({prepared.profile.comparator.value}, "
                  f"{prepared.profile.origin.value})")
            print(f"definition   {prepared.definition.definition_id}")
            print(f"units        {len(prepared.units)}")
            return 0

        if arguments.command == "derive":
            set_id = derive_decisions(**shared, run_id=arguments.run_id)
            print(f"decision set {set_id}")
            print("next         finalize")
            return 0

        if arguments.command == "status":
            state = inspect_sourceafis_native_decisions(
                **shared,
                run_id=arguments.run_id,
                decision_set_id=arguments.decision_set_id,
            )
            print(f"run          {state.run_id}")
            print(f"decision set {state.decision_set_id or '-'}")
            print(f"status       {state.status.value}")
            print(f"source       "
                  f"{'research_ready' if state.source_research_ready else 'not ready'}")
            print(f"decisions    {state.total_decisions} "
                  f"({state.decided_count} decided, "
                  f"{state.undecidable_count} undecidable) "
                  f"{'valid' if state.decision_set_valid else 'unverified'}")
            print(f"eligibility  {state.total_eligibility_units} units "
                  f"{'valid' if state.eligibility_valid else 'unverified'}")
            print(f"views        {state.views_valid} of 3 valid")
            print(f"receipt      {'valid' if state.receipt_valid else 'no'}")
            print(f"finalized    {'valid' if state.finalization_valid else 'no'}")
            for issue in state.issues:
                print(f"  issue      {issue}")
            return 0

        receipt = finalize_decision_derivation(
            **shared,
            run_id=arguments.run_id,
            decision_set_id=arguments.decision_set_id,
        )
        print(f"run          {receipt.run_id}")
        print(f"decision set {receipt.decision_set_id}")
        print(f"eligibility  {receipt.eligibility_set_id} "
              f"({receipt.total_eligibility_units} units)")
        print(f"decisions    {receipt.total_decisions} "
              f"({receipt.decided_count} decided, "
              f"{receipt.undecidable_count} undecidable)")
        for kind, rows in sorted(receipt.view_total_rows.items()):
            print(f"  view       {kind}: {rows} rows")
        print(f"receipt      evidence/sourceafis-native-decisions/"
              f"{receipt.decision_set_id}.json")
        print(receipt.statement)
        return 0
    except (
        ResearchPreflightError,
        ConfigurationError,
        DecisionProfileError,
        DerivationError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
