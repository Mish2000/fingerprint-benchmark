"""Counting a finished derivation, once, for any algorithm.

The sibling of :mod:`fpbench.experiments.algorithm_decisions`, one layer up and
for the same reason. Stage 5B wrote this logic for the native SourceAFIS
derivation; stage 6B needed the identical logic for the canonical one; stage 7D
needs the identical logic for NBIS. Copying the file would mean a difference
between two sets of counts could be a difference in how they were counted, which
is precisely the difference a cross-algorithm comparison must not contain
(docs/adr/0056).

Three things distinguish one evaluation from another: which evaluation config
names the source, which decision spec sits beneath it, and where the evidence
copies go. Everything else is shared, and none of it names an algorithm.

**It applies no threshold and tries no other one.** The threshold arrived with
the decision set, from a profile fixed in a committed YAML file. There is no code
path in this stage that could change it or search for a better one, and that is
not an oversight (docs/adr/0021).

**It counts under one policy for both algorithms.** The metric definitions, the
numerators, the denominators, the pooling rule and the refusal to call the
negative sanity set an FMR all come from
``configs/metrics/plain_roll_biometric_metrics_v1.yaml`` — one file, cited by
both chains, never copied under a second name (spec section 40).
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from fpbench.core.enums import DecisionDerivationStatus
from fpbench.core.errors import (
    ConfigurationError,
    EvaluationFinalizationError,
    MetricDerivationError,
    ResearchPreflightError,
    StorageError,
)
from fpbench.core.evaluation_models import (
    EvaluationState,
    MetricDerivationDefinition,
    metric_derivation_definition_fingerprint,
)
from fpbench.core.evaluation_view_models import (
    MATED_CONDITIONAL_VIEW,
    MATED_UNCONDITIONAL_VIEW,
    NON_MATED_SANITY_VIEW,
)
from fpbench.core.metric_models import (
    MetricPolicy,
    MetricSetManifest,
    ReportProfile,
    metric_set_fingerprint,
    metric_set_id,
    ordered_count_records_hash,
    ordered_observations_hash,
)
from fpbench.core.provenance_models import (
    SoftwareProvenance,
    software_provenance_fingerprint,
)
from fpbench.core.serialization import require_exact_int
from fpbench.derivations import inspect_decision_derivation
from fpbench.experiments.algorithm_decisions import (
    VIEW_KINDS,
    AlgorithmDecisionExperimentSpec,
    definition_store as decision_definition_store,
    load_decision_source,
)
from fpbench.metrics import (
    MetricSources,
    ReportContext,
    aggregate_count_records,
    build_evaluation_finalization_marker,
    build_evaluation_receipt,
    build_evaluation_summary,
    build_observations,
    build_report_context,
    build_report_profile,
    inspect_evaluation,
    load_metric_policy,
    release_order_of,
    render_report,
    structural_counts_of,
    verify_evaluation_report,
    verify_evaluation_summary,
    verify_metric_set,
    write_evaluation_evidence_copies,
)
from fpbench.storage.decision_set_store import DecisionSetStore
from fpbench.storage.definition_store import DefinitionStore
from fpbench.storage.eligibility_set_store import EligibilitySetStore
from fpbench.storage.evaluation_view_store import EvaluationViewStore
from fpbench.storage.metric_set_store import MetricSetStore

__all__ = [
    "AlgorithmEvaluationExperimentSpec",
    "EvaluationExperimentConfig",
    "PreparedEvaluation",
    "load_evaluation_config",
    "prepare_evaluation",
    "derive_metrics",
    "inspect_evaluation_experiment",
    "finalize_evaluation",
    "read_verified_report",
]

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]

_POINTER_NAME = "current-metric-set.json"

#: What an unfilled config looks like. Matched as a substring so that any
#: ``TO_BE_FILLED_AFTER_...`` marker is caught rather than one exact spelling.
_UNRESOLVED = "TO_BE_FILLED"


# ------------------------------------------------------------------- config


@dataclass(frozen=True, slots=True)
class EvaluationExperimentConfig:
    """Which decisions to count, under which policy, rendered how."""

    experiment_id: str
    run_id: str
    decision_set_id: str

    metric_policy_config: Path
    report_profile_id: str

    expected_decisions: int
    expected_eligibility_units: int
    expected_rows_per_view: int
    expected_rows_per_release_per_view: int
    expected_releases: tuple[str, ...]

    #: How many metric observations the policy and the release list imply.
    #: ``None`` when the config does not say — the two SourceAFIS configs were
    #: written before the key existed, and adding it to them would edit files two
    #: published metric sets were produced from (spec section 64).
    expected_metric_observations: int | None = None


@dataclass(frozen=True, slots=True)
class AlgorithmEvaluationExperimentSpec:
    """The three things that distinguish one evaluation from another."""

    evaluation_config: Path
    decision_spec: AlgorithmDecisionExperimentSpec
    evidence_directory: Path


def load_evaluation_config(
    path: Path,
    *,
    repository_root: Path = REPOSITORY_ROOT,
) -> EvaluationExperimentConfig:
    """Read ``configs/evaluations/<name>.yaml``.

    The ``limitations`` block is checked rather than merely read. Every flag in
    it names machinery that does not exist — there is no calibration manifest, no
    bootstrap, no impostor design chosen for estimation — so a config that
    switched one on would be asking for a claim nothing could back
    (docs/adr/0030).
    """
    path = Path(path)
    if not path.is_file():
        raise ConfigurationError(f"evaluation config not found: {path}")
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(document, Mapping):
        raise ConfigurationError(f"{path}: expected a mapping at the top level")

    experiment = _section(document, "experiment", path)
    source = _section(document, "source", path)
    policy = _section(document, "metric_policy", path)
    profile = _section(document, "report_profile", path)
    shape = _section(document, "expected_shape", path)
    limitations = document.get("limitations") or {}
    if not isinstance(limitations, Mapping):
        raise ConfigurationError(f"{path}: malformed 'limitations' section")

    for name in (
        "confidence_intervals",
        "threshold_calibration",
        "general_fmr_claim",
        # Added in stage 7D and absent from the two SourceAFIS configs, which is
        # why it is read with a default rather than required: a file written
        # before the claim existed did not make it (spec section 64).
        "equal_operating_point_claim",
    ):
        if bool(limitations.get(name, False)):
            raise ConfigurationError(
                f"{path}: limitations.{name} may not be true. This stage computes "
                "observed counts under one documented threshold; the machinery "
                "behind that claim does not exist and switching a flag would not "
                "create it"
            )

    releases = tuple(str(item).strip() for item in (shape.get("releases") or ()))
    if not releases:
        raise ConfigurationError(
            f"{path}: expected_shape.releases must name the releases this "
            "evaluation covers"
        )

    # A decision-set id is derived from the decisions and cannot be known before
    # them, so the canonical config is committed with a placeholder and filled in
    # afterwards. An evaluation refuses to run while the placeholder is there
    # rather than inventing a set (the same rule stage 6A applied to the
    # preparation-set id).
    for key in ("run_id", "decision_set_id"):
        if _UNRESOLVED in str(source.get(key, "")):
            raise ConfigurationError(
                f"{path}: source.{key} still holds a placeholder. Run the "
                "derivation first, then write the exact id into this file"
            )

    try:
        return EvaluationExperimentConfig(
            experiment_id=str(experiment["experiment_id"]),
            run_id=str(source["run_id"]),
            decision_set_id=str(source["decision_set_id"]),
            metric_policy_config=Path(repository_root) / str(policy["ref"]),
            report_profile_id=str(profile["profile_id"]),
            expected_decisions=require_exact_int(
                shape["decisions"], "expected_shape.decisions"
            ),
            expected_eligibility_units=require_exact_int(
                shape["eligibility_units"], "expected_shape.eligibility_units"
            ),
            expected_rows_per_view=require_exact_int(
                shape["rows_per_view"], "expected_shape.rows_per_view"
            ),
            expected_rows_per_release_per_view=require_exact_int(
                shape["rows_per_release_per_view"],
                "expected_shape.rows_per_release_per_view",
            ),
            expected_releases=releases,
            expected_metric_observations=(
                require_exact_int(
                    shape["metric_observations"], "expected_shape.metric_observations"
                )
                if "metric_observations" in shape
                else None
            ),
        )
    except KeyError as exc:
        raise ConfigurationError(f"{path}: missing required key {exc}") from None
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{path}: {exc}") from None


# ------------------------------------------------------------------ prepared


@dataclass(frozen=True, slots=True)
class PreparedEvaluation:
    """Everything the four other commands need, already read and revalidated."""

    spec: AlgorithmEvaluationExperimentSpec
    config: EvaluationExperimentConfig
    software: SoftwareProvenance
    workspace: Path

    run: Any
    decision_profile: Any
    result_set: Any
    run_source_commit: str

    decision_manifest: Any
    eligibility_manifest: Any
    view_manifests: Mapping[str, Any]

    decision_status: DecisionDerivationStatus
    decision_finalization_fingerprint: str | None

    sources: MetricSources
    releases: tuple[str, ...]

    policy: MetricPolicy
    report_profile: ReportProfile
    definition: MetricDerivationDefinition | None

    @property
    def metric_store(self) -> MetricSetStore:
        return MetricSetStore(self.workspace)

    @property
    def structural_counts(self) -> Mapping[str, int]:
        return structural_counts_of(
            total_decisions=self.decision_manifest.total_decisions,
            total_eligibility_units=self.eligibility_manifest.total_units,
            unconditional_rows=self.view_manifests[
                MATED_UNCONDITIONAL_VIEW
            ].total_rows,
            conditional_rows=self.view_manifests[MATED_CONDITIONAL_VIEW].total_rows,
            negative_sanity_rows=self.view_manifests[
                NON_MATED_SANITY_VIEW
            ].total_rows,
        )


# ------------------------------------------------------------------- prepare


def prepare_evaluation(
    *,
    spec: AlgorithmEvaluationExperimentSpec,
    workspace: Path,
    repository_root: Path = REPOSITORY_ROOT,
    require_expected_shape: bool = True,
    permissive_provenance: bool = False,
) -> PreparedEvaluation:
    """Pin the source, the policy, the profile and the metric code. Count nothing."""
    workspace = Path(workspace)
    software = (
        _capture_permissive(repository_root)
        if permissive_provenance
        else _capture_research_provenance(repository_root)
    )

    prepared = _load_chain(
        spec=spec,
        workspace=workspace,
        repository_root=repository_root,
        software=software,
        require_expected_shape=require_expected_shape,
    )

    definition = prepared.definition
    if definition is None:
        raise ResearchPreflightError(
            "an evaluation requires committed, clean metric-engine provenance; a "
            "dirty tree cannot produce an authoritative result (docs/adr/0017)"
        )
    store = _definition_store(workspace, prepared.config.experiment_id)
    try:
        store.write(prepared.run.run_id, definition)
    except StorageError as exc:
        raise ResearchPreflightError(
            f"{exc}; a different source, policy or commit is a different "
            "evaluation and needs its own definition"
        ) from exc
    store.write_pointer(prepared.run.run_id, definition_id=definition.definition_id)
    return prepared


# -------------------------------------------------------------------- derive


def derive_metrics(
    *,
    spec: AlgorithmEvaluationExperimentSpec,
    workspace: Path,
    repository_root: Path = REPOSITORY_ROOT,
    require_expected_shape: bool = True,
) -> str:
    """Build the count records and the observations, and store them.

    Idempotent: the same decisions, policy and metric code produce the same id
    and rewrite nothing. Writes no summary, no report and no finalization
    marker — until those exist, everything here is retryable work in progress
    (docs/adr/0020).
    """
    prepared = prepare_evaluation(
        spec=spec,
        workspace=workspace,
        repository_root=repository_root,
        require_expected_shape=require_expected_shape,
    )
    definition = prepared.definition
    assert definition is not None  # prepare_evaluation refuses otherwise

    counts = aggregate_count_records(prepared.sources, releases=prepared.releases)
    observations = build_observations(
        policy=prepared.policy,
        records=counts,
        releases=prepared.releases,
        decision_set_fingerprint=prepared.sources.decision_set_fingerprint,
        eligibility_set_fingerprint=prepared.sources.eligibility_set_fingerprint,
        view_fingerprints={
            kind: prepared.sources.view_fingerprint(kind) for kind in VIEW_KINDS
        },
    )

    expected_observations = prepared.config.expected_metric_observations
    if (
        require_expected_shape
        and expected_observations is not None
        and len(observations) != expected_observations
    ):
        raise MetricDerivationError(
            f"the policy and {len(prepared.releases)} releases produced "
            f"{len(observations)} observations, but this evaluation declares "
            f"{expected_observations}. The count is fourteen metrics times the "
            "releases plus pooled, and a mismatch means one of the three moved"
        )

    manifest = _build_manifest(
        prepared=prepared,
        definition=definition,
        counts=counts,
        observations=observations,
    )

    # Verified in memory before anything is written, so a failure leaves the
    # workspace exactly as it was.
    verify_metric_set(
        definition=definition,
        policy=prepared.policy,
        report_profile=prepared.report_profile,
        manifest=manifest,
        counts=counts,
        observations=observations,
        sources=prepared.sources,
        run=prepared.run,
        result_set=prepared.result_set,
        decision_profile=prepared.decision_profile,
        decision_manifest=prepared.decision_manifest,
        eligibility_manifest=prepared.eligibility_manifest,
        view_manifests=prepared.view_manifests,
        releases=prepared.releases,
    )

    set_id = manifest.metric_set_id
    store = prepared.metric_store
    store.ensure_metric_set(
        definition=definition,
        policy=prepared.policy,
        report_profile=prepared.report_profile,
        manifest=manifest,
        counts=counts,
        observations=observations,
    )

    # Read everything back and verify again before claiming anything was written.
    (
        stored_definition,
        stored_policy,
        stored_profile,
        stored_manifest,
        stored_counts,
        stored_observations,
    ) = store.read_metric_set(prepared.run.run_id, set_id)
    verify_metric_set(
        definition=stored_definition,
        policy=stored_policy,
        report_profile=stored_profile,
        manifest=stored_manifest,
        counts=stored_counts,
        observations=stored_observations,
        sources=prepared.sources,
        run=prepared.run,
        result_set=prepared.result_set,
        decision_profile=prepared.decision_profile,
        decision_manifest=prepared.decision_manifest,
        eligibility_manifest=prepared.eligibility_manifest,
        view_manifests=prepared.view_manifests,
        releases=prepared.releases,
    )

    _definition_store(prepared.workspace, prepared.config.experiment_id).write_pointer(
        prepared.run.run_id,
        definition_id=definition.definition_id,
        metric_set_id=set_id,
    )
    return set_id


# -------------------------------------------------------------------- status


def inspect_evaluation_experiment(
    *,
    spec: AlgorithmEvaluationExperimentSpec,
    workspace: Path,
    repository_root: Path = REPOSITORY_ROOT,
    metric_set_id_override: str | None = None,
) -> EvaluationState:
    """Recompute the chain and report where it stands. Never writes."""
    workspace = Path(workspace)
    prepared = _load_chain(
        spec=spec,
        workspace=workspace,
        repository_root=repository_root,
        software=_capture_permissive(repository_root),
        require_expected_shape=False,
    )
    store = _definition_store(workspace, prepared.config.experiment_id)
    resolved = metric_set_id_override or store.read_pointer_value(
        prepared.run.run_id, "metric_set_id"
    )

    return inspect_evaluation(
        run=prepared.run,
        result_set=prepared.result_set,
        decision_profile=prepared.decision_profile,
        decision_manifest=prepared.decision_manifest,
        eligibility_manifest=prepared.eligibility_manifest,
        run_source_commit=prepared.run_source_commit,
        sources=prepared.sources,
        decision_status=prepared.decision_status,
        decision_finalization_fingerprint=prepared.decision_finalization_fingerprint,
        definition=store.read_active(prepared.run.run_id),
        metric_set_id=resolved,
        releases=prepared.releases,
        structural_counts=prepared.structural_counts,
        workspace=workspace,
    )


# ------------------------------------------------------------------ finalize


def finalize_evaluation(
    *,
    spec: AlgorithmEvaluationExperimentSpec,
    workspace: Path,
    repository_root: Path = REPOSITORY_ROOT,
    metric_set_id_override: str | None = None,
) -> str:
    """Re-verify everything, then write summary, report, receipt and marker.

    Order, and it is the point: source chain, metric set, read-back, summary,
    report, receipt, read-back and hash, marker, status, evidence. A failure
    before the marker leaves the intermediates in place and retryable, and the
    evaluation is simply not authoritative yet.
    """
    workspace = Path(workspace)
    prepared = _load_chain(
        spec=spec,
        workspace=workspace,
        repository_root=repository_root,
        software=_capture_research_provenance(repository_root),
        require_expected_shape=True,
    )
    definition_store_ = _definition_store(workspace, prepared.config.experiment_id)
    set_id = metric_set_id_override or definition_store_.read_pointer_value(
        prepared.run.run_id, "metric_set_id"
    )
    if not set_id:
        raise EvaluationFinalizationError(
            "no metric set has been produced for this run; run 'derive' first"
        )
    if prepared.decision_finalization_fingerprint is None:
        raise EvaluationFinalizationError(
            "the source derivation has no finalization marker; an evaluation "
            "cannot outrank the decisions beneath it"
        )

    store = prepared.metric_store
    (
        definition,
        policy,
        report_profile,
        manifest,
        counts,
        observations,
    ) = store.read_metric_set(prepared.run.run_id, set_id)
    verify_metric_set(
        definition=definition,
        policy=policy,
        report_profile=report_profile,
        manifest=manifest,
        counts=counts,
        observations=observations,
        sources=prepared.sources,
        run=prepared.run,
        result_set=prepared.result_set,
        decision_profile=prepared.decision_profile,
        decision_manifest=prepared.decision_manifest,
        eligibility_manifest=prepared.eligibility_manifest,
        view_manifests=prepared.view_manifests,
        releases=prepared.releases,
    )
    expected_observations = prepared.config.expected_metric_observations
    if (
        expected_observations is not None
        and manifest.total_observations != expected_observations
    ):
        raise EvaluationFinalizationError(
            f"metric set {set_id} holds {manifest.total_observations} observations, "
            f"but this evaluation declares {expected_observations}"
        )

    summary = build_evaluation_summary(
        manifest=manifest,
        run=prepared.run,
        decision_profile=prepared.decision_profile,
        releases=prepared.releases,
        counts=counts,
        observations=observations,
    )
    store.ensure_summary(
        run_id=prepared.run.run_id, metric_set_id=set_id, summary=summary
    )
    stored_summary = store.read_summary(prepared.run.run_id, set_id)
    verify_evaluation_summary(
        summary=stored_summary,
        manifest=manifest,
        counts=counts,
        observations=observations,
        releases=prepared.releases,
        run=prepared.run,
        decision_profile=prepared.decision_profile,
    )

    markdown = render_report(
        context=_report_context(prepared, manifest),
        manifest=manifest,
        policy=policy,
        report_profile=report_profile,
        counts=counts,
        observations=observations,
    )
    store.ensure_report(
        run_id=prepared.run.run_id, metric_set_id=set_id, markdown=markdown
    )
    stored_markdown = store.read_report(prepared.run.run_id, set_id)
    verify_evaluation_report(markdown=stored_markdown, expected_markdown=markdown)

    receipt = build_evaluation_receipt(
        manifest=manifest,
        definition=definition,
        policy=policy,
        observations=observations,
        releases=prepared.releases,
        structural_counts=prepared.structural_counts,
        run_id=prepared.run.run_id,
        result_set_id=prepared.result_set.result_set_id,
        decision_profile_id=prepared.decision_profile.profile_id,
        metric_software=prepared.software,
    )
    store.ensure_receipt(
        run_id=prepared.run.run_id, metric_set_id=set_id, receipt=receipt
    )
    stored_receipt = store.read_receipt(prepared.run.run_id, set_id)

    marker = build_evaluation_finalization_marker(
        definition=definition,
        manifest=manifest,
        summary=stored_summary,
        markdown=markdown,
        receipt=stored_receipt,
        decision_finalization_fingerprint=prepared.decision_finalization_fingerprint,
        metric_software=prepared.software,
    )
    store.ensure_finalization(
        run_id=prepared.run.run_id, metric_set_id=set_id, marker=marker
    )

    state = inspect_evaluation(
        run=prepared.run,
        result_set=prepared.result_set,
        decision_profile=prepared.decision_profile,
        decision_manifest=prepared.decision_manifest,
        eligibility_manifest=prepared.eligibility_manifest,
        run_source_commit=prepared.run_source_commit,
        sources=prepared.sources,
        decision_status=prepared.decision_status,
        decision_finalization_fingerprint=prepared.decision_finalization_fingerprint,
        definition=definition,
        metric_set_id=set_id,
        releases=prepared.releases,
        structural_counts=prepared.structural_counts,
        workspace=workspace,
    )
    if not state.is_evaluation_ready:
        raise EvaluationFinalizationError(
            f"evaluation {set_id} finalised but did not reach EVALUATION_READY: "
            f"{state.status.value} {list(state.issues)[:3]}"
        )

    write_evaluation_evidence_copies(
        receipt=stored_receipt,
        markdown=stored_markdown,
        repository_root=Path(repository_root),
        directory=spec.evidence_directory,
    )
    return set_id


# ---------------------------------------------------------------------- show


def read_verified_report(
    *,
    spec: AlgorithmEvaluationExperimentSpec,
    workspace: Path,
    repository_root: Path = REPOSITORY_ROOT,
    metric_set_id_override: str | None = None,
) -> str:
    """Return the report, but only from an evaluation that is fully verified.

    There is no partial view. A report over an unverified chain is a table of
    numbers with nothing behind it, and the moment it is printed somebody will
    copy it somewhere the caveat does not follow.
    """
    state = inspect_evaluation_experiment(
        spec=spec,
        workspace=workspace,
        repository_root=repository_root,
        metric_set_id_override=metric_set_id_override,
    )
    if not state.is_evaluation_ready:
        raise EvaluationFinalizationError(
            f"this evaluation is {state.status.value}, not evaluation_ready; there "
            f"is no verified report to show {list(state.issues)[:3]}"
        )
    return MetricSetStore(Path(workspace)).read_report(
        state.run_id, str(state.metric_set_id)
    )


# ----------------------------------------------------------------- internals


def _load_chain(
    *,
    spec: AlgorithmEvaluationExperimentSpec,
    workspace: Path,
    repository_root: Path,
    software: SoftwareProvenance,
    require_expected_shape: bool,
) -> PreparedEvaluation:
    """Read the finished derivation and everything the metric engine may see."""
    config = load_evaluation_config(
        spec.evaluation_config, repository_root=repository_root
    )
    decision_spec = spec.decision_spec
    prepared = load_decision_source(
        spec=decision_spec,
        workspace=workspace,
        repository_root=repository_root,
        run_id=config.run_id,
        software=software,
        require_expected_shape=require_expected_shape,
        require_definition=False,
    )

    run_id = prepared.run.run_id
    if run_id != config.run_id:
        raise MetricDerivationError(
            f"this evaluation is defined over run {config.run_id}, but the "
            f"workspace resolved {run_id}"
        )

    decision_store = DecisionSetStore(workspace)
    set_id = config.decision_set_id
    if not decision_store.has_decision_set(run_id, set_id):
        raise MetricDerivationError(
            f"run {run_id} does not hold decision set {set_id}; this evaluation "
            "names one exact set and will not fall back to another"
        )
    _, decision_manifest, decisions = decision_store.read_decision_set(run_id, set_id)

    eligibility_manifest, eligibility_records = EligibilitySetStore(
        workspace
    ).read_eligibility_set(run_id, set_id)

    view_store = EvaluationViewStore(workspace)
    view_manifests = {}
    view_entries = {}
    for kind in VIEW_KINDS:
        manifest, entries = view_store.read_view(run_id, set_id, kind)
        view_manifests[kind] = manifest
        view_entries[kind] = entries

    # The decision chain is revalidated in full rather than taken on trust.
    # "Decision ready" is a claim about the current files, and this evaluation is
    # about to rest its entire weight on it.
    decision_state = inspect_decision_derivation(
        run=prepared.run,
        plan=prepared.plan,
        pairs=prepared.pairs,
        units=prepared.units,
        result_set=prepared.result_set,
        result_set_entries=prepared.result_set_entries,
        result_store=prepared.result_store,
        research_status=prepared.research_status,
        decision_profile=prepared.profile,
        definition=decision_definition_store(
            workspace, decision_spec.experiment_id
        ).read_active(run_id),
        decision_set_id=set_id,
        pair_manifest_hash=prepared.pair_manifest_hash,
        non_mated_finger_shift=decision_spec.non_mated_finger_shift,
        workspace=workspace,
        source_finalization=prepared.source_finalization,
    )
    if require_expected_shape and not decision_state.is_decision_ready:
        raise ResearchPreflightError(
            f"decision set {set_id} is {decision_state.status.value}, not "
            f"decision_ready; metrics may only be computed over a finished "
            f"derivation {list(decision_state.issues)[:3]}"
        )

    finalization_fingerprint = None
    if decision_store.has_finalization(run_id, set_id):
        finalization_fingerprint = decision_store.read_finalization(
            run_id, set_id
        ).finalization_fingerprint

    sources = MetricSources(
        decisions=tuple(decisions),
        decision_set_fingerprint=decision_manifest.decision_set_fingerprint,
        eligibility_records=tuple(eligibility_records),
        eligibility_set_fingerprint=eligibility_manifest.eligibility_set_fingerprint,
        view_manifests=view_manifests,
        view_entries=view_entries,
        pairs=prepared.pairs,
    )
    releases = release_order_of(
        sources,
        expected_releases=config.expected_releases if require_expected_shape else None,
    )
    if require_expected_shape:
        _require_expected_shape(
            config=config,
            decision_manifest=decision_manifest,
            eligibility_manifest=eligibility_manifest,
            view_manifests=view_manifests,
            releases=releases,
        )

    policy = load_metric_policy(config.metric_policy_config)
    report_profile = build_report_profile(
        profile_id=config.report_profile_id, release_order=releases
    )

    definition = None
    if software.is_research_grade:
        claims = {
            "run_id": run_id,
            "result_set_fingerprint": prepared.result_set.result_set_fingerprint,
            "decision_set_id": decision_manifest.decision_set_id,
            "decision_set_fingerprint": decision_manifest.decision_set_fingerprint,
            "eligibility_set_id": eligibility_manifest.eligibility_set_id,
            "eligibility_set_fingerprint": (
                eligibility_manifest.eligibility_set_fingerprint
            ),
            "unconditional_view_fingerprint": view_manifests[
                MATED_UNCONDITIONAL_VIEW
            ].view_fingerprint,
            "conditional_view_fingerprint": view_manifests[
                MATED_CONDITIONAL_VIEW
            ].view_fingerprint,
            "non_mated_view_fingerprint": view_manifests[
                NON_MATED_SANITY_VIEW
            ].view_fingerprint,
            "metric_policy_id": policy.policy_id,
            "metric_policy_fingerprint": policy.policy_fingerprint,
            "report_profile_id": report_profile.report_profile_id,
            "report_profile_fingerprint": report_profile.report_profile_fingerprint,
            "metric_software": software,
            "metric_software_fingerprint": software_provenance_fingerprint(software),
        }
        fingerprint = metric_derivation_definition_fingerprint(claims)
        definition = MetricDerivationDefinition(
            **claims,
            definition_id=f"metricderivation_{fingerprint[:12]}",
            definition_fingerprint=fingerprint,
            created_utc=_utc_now(),
        )

    return PreparedEvaluation(
        spec=spec,
        config=config,
        software=software,
        workspace=workspace,
        run=prepared.run,
        decision_profile=prepared.profile,
        result_set=prepared.result_set,
        run_source_commit=_run_source_commit(prepared),
        decision_manifest=decision_manifest,
        eligibility_manifest=eligibility_manifest,
        view_manifests=view_manifests,
        decision_status=decision_state.status,
        decision_finalization_fingerprint=finalization_fingerprint,
        sources=sources,
        releases=releases,
        policy=policy,
        report_profile=report_profile,
        definition=definition,
    )


def _build_manifest(
    *,
    prepared: PreparedEvaluation,
    definition: MetricDerivationDefinition,
    counts: Sequence[Any],
    observations: Sequence[Any],
) -> MetricSetManifest:
    counts_hash = ordered_count_records_hash(counts)
    observations_hash = ordered_observations_hash(observations)
    fingerprint = metric_set_fingerprint(
        run_fingerprint=prepared.run.run_fingerprint,
        decision_set_fingerprint=prepared.sources.decision_set_fingerprint,
        eligibility_set_fingerprint=prepared.sources.eligibility_set_fingerprint,
        unconditional_view_fingerprint=prepared.sources.view_fingerprint(
            MATED_UNCONDITIONAL_VIEW
        ),
        conditional_view_fingerprint=prepared.sources.view_fingerprint(
            MATED_CONDITIONAL_VIEW
        ),
        non_mated_view_fingerprint=prepared.sources.view_fingerprint(
            NON_MATED_SANITY_VIEW
        ),
        metric_policy_fingerprint=prepared.policy.policy_fingerprint,
        metric_software_fingerprint=definition.metric_software_fingerprint,
        ordered_count_records_hash=counts_hash,
        ordered_observations_hash=observations_hash,
    )
    return MetricSetManifest(
        metric_set_id=metric_set_id(fingerprint),
        metric_set_fingerprint=fingerprint,
        run_id=prepared.run.run_id,
        run_fingerprint=prepared.run.run_fingerprint,
        decision_set_id=prepared.decision_manifest.decision_set_id,
        decision_set_fingerprint=prepared.sources.decision_set_fingerprint,
        eligibility_set_id=prepared.eligibility_manifest.eligibility_set_id,
        eligibility_set_fingerprint=prepared.sources.eligibility_set_fingerprint,
        unconditional_view_fingerprint=prepared.sources.view_fingerprint(
            MATED_UNCONDITIONAL_VIEW
        ),
        conditional_view_fingerprint=prepared.sources.view_fingerprint(
            MATED_CONDITIONAL_VIEW
        ),
        non_mated_view_fingerprint=prepared.sources.view_fingerprint(
            NON_MATED_SANITY_VIEW
        ),
        metric_policy_id=prepared.policy.policy_id,
        metric_policy_fingerprint=prepared.policy.policy_fingerprint,
        report_profile_fingerprint=prepared.report_profile.report_profile_fingerprint,
        metric_software_fingerprint=definition.metric_software_fingerprint,
        metric_source_revision=definition.metric_source_commit,
        total_count_records=len(counts),
        total_observations=len(observations),
        ordered_count_records_hash=counts_hash,
        ordered_observations_hash=observations_hash,
        created_utc=_utc_now(),
    )


def _report_context(
    prepared: PreparedEvaluation, manifest: MetricSetManifest
) -> ReportContext:
    return build_report_context(
        run=prepared.run,
        result_set=prepared.result_set,
        decision_profile=prepared.decision_profile,
        decision_manifest=prepared.decision_manifest,
        eligibility_manifest=prepared.eligibility_manifest,
        metric_manifest=manifest,
        run_source_commit=prepared.run_source_commit,
    )


def _require_expected_shape(
    *,
    config: EvaluationExperimentConfig,
    decision_manifest: Any,
    eligibility_manifest: Any,
    view_manifests: Mapping[str, Any],
    releases: Sequence[str],
) -> None:
    """Assert the protocol's shape before anything is counted."""
    if decision_manifest.total_decisions != config.expected_decisions:
        raise MetricDerivationError(
            f"the decision set holds {decision_manifest.total_decisions} decisions, "
            f"expected {config.expected_decisions}"
        )
    if eligibility_manifest.total_units != config.expected_eligibility_units:
        raise MetricDerivationError(
            f"the eligibility set holds {eligibility_manifest.total_units} units, "
            f"expected {config.expected_eligibility_units}"
        )
    for kind, manifest in view_manifests.items():
        if manifest.total_rows != config.expected_rows_per_view:
            raise MetricDerivationError(
                f"view {kind} holds {manifest.total_rows} rows, expected "
                f"{config.expected_rows_per_view}"
            )
    expected_total = config.expected_rows_per_release_per_view * len(releases)
    if expected_total != config.expected_rows_per_view:
        raise MetricDerivationError(
            f"{len(releases)} releases at "
            f"{config.expected_rows_per_release_per_view} rows each is "
            f"{expected_total}, but each view declares "
            f"{config.expected_rows_per_view}"
        )


def _run_source_commit(prepared: Any) -> str:
    """Which fpbench commit produced the raw scores, from the run's own receipt.

    Three commits reach the report, and they are three different questions: which
    code ran the comparisons, which code applied the threshold, which code counted
    the results. They are frequently not the same commit, and a report that
    printed one of them would invite the reader to assume all three
    (docs/adr/0017).
    """
    store = prepared.result_store
    run_id = prepared.run.run_id
    if not store.has_research_receipt(run_id):
        return "unrecorded"
    return store.read_research_receipt(run_id).source_commit


def _definition_store(workspace: Path, experiment_id: str) -> DefinitionStore:
    return DefinitionStore(
        Path(workspace),
        experiment_id=experiment_id,
        loader=lambda payload: MetricDerivationDefinition(**payload),
        pointer_name=_POINTER_NAME,
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


def _section(document: Mapping[str, Any], key: str, path: Path) -> Mapping[str, Any]:
    value = document.get(key)
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"{path}: missing or malformed '{key}' section")
    return value


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()
