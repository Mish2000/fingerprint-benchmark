"""Applying a documented threshold to a finished run, once, for any algorithm.

Stage 5A wrote this logic for one SourceAFIS run. Stage 6B generalised it over
*two SourceAFIS runs* and said so explicitly: the engine still read a SourceAFIS
validation report and still knew what a bridge jar was, and hardening the
interface for a second algorithm was left as separate work with a different
shape. This module is that work.

What it does, in this order, for whichever algorithm it is handed
(spec section 23):

1. load and re-verify the source run — through the integration, which is the
   only part that differs;
2. load the decision profile and refuse it if it does not describe this run;
3. load the exact result set the run's identity names;
4. apply the threshold to every stored result, in plan order;
5. verify the decision set by re-deriving it from the raw scores;
6. build the SELF eligibility units from the frozen pair manifest;
7. require every SELF result to prove two independent template extractions;
8. derive SELF eligibility, and verify it;
9. build the three evaluation views, and verify each;
10. write everything into immutable stores and read it back;
11. build the receipt, then the finalization marker;
12. derive the status by recomputing the whole chain.

**Nothing in this module names an algorithm.** There is no ``sourceafis``, no
``nbis``, no ``bridge``, no ``jar``, no ``mindtct`` and no ``bozorth`` — not in
an import, not in a branch, not in a string. A structural test walks the syntax
tree and proves it, because a sentence in a docstring is not a guarantee
(docs/adr/0056, spec sections 20 and 76).

That matters for one specific reason. The comparison stage 7D ends with is only
meaningful if the two sets of decisions were derived by the same code. If they
were derived by two modules, then any difference between the two sets of numbers
could be a difference in the derivation, and no amount of care about thresholds
would recover the argument.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from fpbench.core.derivation_models import (
    DERIVATION_RECEIPT_SCHEMA_VERSION,
    DecisionDerivationReceipt,
    DecisionDerivationState,
    DerivationDefinition,
    SourceFinalizationIdentity,
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
from fpbench.eligibility.self_mapping import (
    DEFAULT_SELF_INDEPENDENCE,
    SelfIndependenceRequirement,
)
from fpbench.evaluation import (
    build_mated_conditional_view,
    build_mated_unconditional_view,
    build_non_mated_sanity_view,
    verify_evaluation_view,
)
from fpbench.experiments.algorithm_research import read_run_pointer
from fpbench.experiments.decision_source_integration import (
    DecisionSourceIntegration,
    PreparationBinding,
    VerifiedDecisionSource,
)
from fpbench.storage.decision_set_store import DecisionSetStore
from fpbench.storage.definition_store import DefinitionStore
from fpbench.storage.eligibility_set_store import EligibilitySetStore
from fpbench.storage.evaluation_view_store import EvaluationViewStore
from fpbench.storage.result_store import ResultStore

__all__ = [
    "AlgorithmDecisionExperimentSpec",
    "PreparedDerivation",
    "PreparationBinding",
    "load_non_mated_finger_shift",
    "load_decision_source",
    "prepare_decision_derivation",
    "derive_decisions",
    "inspect_decisions",
    "finalize_decision_derivation",
    "read_decision_set_pointer",
    "definition_store",
    "VIEW_KINDS",
]

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]

_POINTER_NAME = "current-decision-set.json"

VIEW_KINDS = (
    MATED_UNCONDITIONAL_VIEW,
    MATED_CONDITIONAL_VIEW,
    NON_MATED_SANITY_VIEW,
)


@dataclass(frozen=True, slots=True)
class AlgorithmDecisionExperimentSpec:
    """What distinguishes one derivation from another. All of it is data.

    ``integration`` is the only field that carries behaviour, and it carries
    exactly one behaviour: how to load and re-verify a finished run of one
    algorithm. Everything else is a path, a count or a string.
    """

    experiment_id: str

    #: Whose run pointer to read when no run id is given. A bookmark; the run's
    #: own identity is what everything downstream binds.
    source_experiment_id: str
    protocol_config: Path

    decision_profile_config: Path
    evidence_directory: Path

    expected_decisions: int
    expected_eligibility_units: int
    expected_rows_per_view: int
    expected_units_per_release: int

    non_mated_finger_shift: int

    integration: DecisionSourceIntegration

    #: What a SELF result has to prove before a verdict may rest on it. A
    #: parameter because adapters word their evidence differently — one route
    #: records template persistence separately from template caching, and a
    #: requirement that assumed one vocabulary would silently skip the check on
    #: the other (spec section 32).
    self_independence: SelfIndependenceRequirement = DEFAULT_SELF_INDEPENDENCE

    #: ``"1"`` writes the receipt shape already published for SourceAFIS. ``"2"``
    #: additionally binds the derivation definition, the derivation software and
    #: the source run's stage marker (spec section 36).
    receipt_schema_version: str = DERIVATION_RECEIPT_SCHEMA_VERSION

    #: Retained so the stage 5A/6B wrappers can keep passing what they always
    #: passed. The engine does not read it.
    source_experiment_config: Path | None = None

    #: Extra files the finalize step publishes beside the receipt, as
    #: ``filename -> callable(prepared, set_id) -> JSON-serialisable``. Empty for
    #: the SourceAFIS chains, whose evidence directories are already committed
    #: and may not grow a file (spec sections 25 and 37).
    extra_evidence: Mapping[str, Any] = field(default_factory=dict)


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

    spec: AlgorithmDecisionExperimentSpec
    software: SoftwareProvenance
    workspace: Path

    source: VerifiedDecisionSource

    profile: DecisionProfile
    definition: DerivationDefinition | None
    units: tuple

    # -------------------------------------------------- the source, unpacked
    #
    # Stage 5A callers reach for ``prepared.run`` and ``prepared.pairs``. Those
    # names still work, and now read through to one verified object rather than
    # to eleven separately-passed values.

    @property
    def run(self) -> Any:
        return self.source.run

    @property
    def plan(self) -> Any:
        return self.source.plan

    @property
    def pairs(self) -> Mapping[PairId, ComparisonPair]:
        return self.source.pairs

    @property
    def images(self) -> Mapping[str, ImageRecord]:
        return self.source.images

    @property
    def pair_manifest_hash(self) -> str:
        return self.source.pair_manifest_hash

    @property
    def result_set(self) -> Any:
        return self.source.result_set

    @property
    def result_set_entries(self) -> tuple:
        return self.source.result_set_entries

    @property
    def research_status(self) -> ResearchRunStatus:
        return self.source.research_status

    @property
    def source_finalization(self) -> SourceFinalizationIdentity:
        return self.source.source_finalization

    @property
    def config(self) -> AlgorithmDecisionExperimentSpec:
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
    spec: AlgorithmDecisionExperimentSpec,
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
    # The pointer names the active definition. Stage 5A's native derivation gets
    # away without one because its definition sits in the legacy flat file that
    # `read_active` falls back to; a derivation with no such file — every new one
    # — needs the pointer or nothing can find what it pinned.
    store.write_pointer(prepared.run.run_id, definition_id=definition.definition_id)
    return prepared


# ----------------------------------------------------------------- derive


def derive_decisions(
    *,
    spec: AlgorithmDecisionExperimentSpec,
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
    # template extraction, not of resampling (docs/adr/0035, spec section 32).
    self_jobs = {unit.plain_self_job_id for unit in prepared.units} | {
        unit.roll_self_job_id for unit in prepared.units
    }
    require_self_independence_evidence(
        results=(
            prepared.result_store.read_raw_result(prepared.run.run_id, job_id)
            for job_id in sorted(self_jobs)
        ),
        requirement=spec.self_independence,
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

    definition_store(workspace, spec.experiment_id).write_pointer(
        prepared.run.run_id,
        definition_id=(
            prepared.definition.definition_id if prepared.definition else None
        ),
        decision_set_id=set_id,
    )
    return set_id


# ----------------------------------------------------------------- status


def inspect_decisions(
    *,
    spec: AlgorithmDecisionExperimentSpec,
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
        source_finalization=prepared.source_finalization,
    )


# --------------------------------------------------------------- finalize


def finalize_decision_derivation(
    *,
    spec: AlgorithmDecisionExperimentSpec,
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
        schema_version=spec.receipt_schema_version,
        definition=prepared.definition,
        source_finalization=prepared.source_finalization,
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
        schema_version=spec.receipt_schema_version,
        source_finalization=prepared.source_finalization,
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
        source_finalization=prepared.source_finalization,
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
    _write_extra_evidence(
        spec=spec,
        prepared=prepared,
        decision_set_id=set_id,
        repository_root=Path(repository_root),
    )
    return stored_receipt


# ----------------------------------------------------------------- source


def load_decision_source(
    *,
    spec: AlgorithmDecisionExperimentSpec,
    workspace: Path,
    repository_root: Path,
    run_id: str | None,
    software: SoftwareProvenance,
    require_expected_shape: bool = True,
    require_definition: bool = True,
) -> PreparedDerivation:
    """Load and revalidate the finished run and everything it implies.

    Public because the evaluation engine needs exactly this and nothing else: the
    same run, the same pair manifest, the same profile, revalidated the same way.
    A second implementation of "read the source chain" would be a second place for
    the two stages to disagree about what they are counting.

    The algorithm-specific half — which validator runs, which markers must exist,
    which prepared-image set the results must claim — arrives through
    ``spec.integration`` and is never inspected here.
    """
    workspace = Path(workspace)
    integration = spec.integration
    resolved_run = run_id or read_run_pointer(workspace, spec.source_experiment_id)

    binding: PreparationBinding | None = None
    if integration.preparation_binding_factory is not None:
        binding = integration.preparation_binding_factory(workspace)

    source = integration.load_verified_source(
        workspace=workspace,
        repository_root=Path(repository_root),
        run_id=resolved_run,
        software=software,
        require_ready=require_expected_shape,
        preparation_binding=binding,
    )
    integration.require_source_algorithm(source)
    if require_expected_shape and not source.is_research_ready:
        raise ResearchPreflightError(
            f"run {resolved_run} is {source.research_status.value}, not "
            "research_ready; decisions may only be derived from a finished run"
        )

    run = source.run
    profile = load_decision_profile(
        spec.decision_profile_config,
        algorithm_fingerprint=run.algorithm_fingerprint,
    )
    require_profile_applies_to_run(profile=profile, run=run)

    pairs_list = list(source.pairs.values())
    jobs_by_pair = {
        str(planned.job.pair_id): planned.job.job_id for planned in source.plan.jobs
    }
    units = build_self_eligibility_units(
        pairs=pairs_list,
        images=source.images,
        jobs_by_pair=jobs_by_pair,
        protocol_id=run.protocol_id,
        cohort_id=str(run.cohort_id),
    )
    if require_expected_shape:
        _require_unit_shape(spec, units)

    definition = None
    if software.is_research_grade:
        claims = {
            "run_id": run.run_id,
            "run_fingerprint": run.run_fingerprint,
            "result_set_id": source.result_set.result_set_id,
            "result_set_fingerprint": source.result_set.result_set_fingerprint,
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
        source=source,
        profile=profile,
        definition=definition,
        units=units,
    )


# ----------------------------------------------------------------- internals


def _write_extra_evidence(
    *,
    spec: AlgorithmDecisionExperimentSpec,
    prepared: PreparedDerivation,
    decision_set_id: str,
    repository_root: Path,
) -> tuple[Path, ...]:
    """Publish whatever else this experiment's evidence directory declares.

    Each entry is written through the same write-once helper as the receipt, so
    a second finalize either produces identical bytes or refuses. Nothing is
    composed here: every value is copied out of an artefact the workspace has
    already verified.
    """
    from fpbench.derivations.receipt import write_evidence_document

    written: list[Path] = []
    directory = Path(repository_root) / spec.evidence_directory
    for name, build in dict(spec.extra_evidence).items():
        written.append(
            write_evidence_document(
                directory / name, build(prepared, decision_set_id)
            )
        )
    return tuple(written)


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


def _require_decision_shape(spec: AlgorithmDecisionExperimentSpec, manifest) -> None:
    if manifest.total_decisions != spec.expected_decisions:
        raise DecisionDerivationError(
            f"the derivation holds {manifest.total_decisions} decisions, expected "
            f"{spec.expected_decisions}"
        )
    if manifest.undecidable_count:
        # Every stored result of these runs is a success — each run's own receipt
        # says so. An undecidable decision would mean the scores changed under
        # the receipt, which is a contradiction rather than a new outcome
        # (spec section 29).
        raise DecisionDerivationError(
            f"{manifest.undecidable_count} comparison(s) could not be decided, but "
            "the source run's receipt records no failures; the raw results and the "
            "receipt disagree"
        )


def _require_eligibility_shape(
    spec: AlgorithmDecisionExperimentSpec, records: Sequence
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
    spec: AlgorithmDecisionExperimentSpec, units: Sequence
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


def read_decision_set_pointer(
    workspace: Path, experiment_id: str, run_id: str
) -> str | None:
    """Which decision set this workspace last derived. A bookmark, not evidence.

    Every artefact it names carries its own identity, and every command
    re-derives what it needs; the pointer only saves the caller from typing an
    id.
    """
    return definition_store(workspace, experiment_id).read_pointer_value(
        run_id, "decision_set_id"
    )


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()
