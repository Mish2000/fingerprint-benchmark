"""The native-versus-canonical paired comparison, in five commands.

    python -m fpbench.experiments.sourceafis_native_vs_canonical500 prepare
    python -m fpbench.experiments.sourceafis_native_vs_canonical500 derive
    python -m fpbench.experiments.sourceafis_native_vs_canonical500 status
    python -m fpbench.experiments.sourceafis_native_vs_canonical500 finalize
    python -m fpbench.experiments.sourceafis_native_vs_canonical500 show

No Java is run and no score is recomputed. Both chains are already finished,
already verified and already published; this reads them, joins them by
``pair_id``, and counts what changed.

The order of ``derive`` is the argument of the whole stage. Alignment first,
because a comparison of misaligned rows is not a comparison. Then the paired
records. Then the **SD300A control** — and if that fails, everything stops there.
Only after the control passes are the transitions, the common-eligible view and
the rates computed, because only then does "what changed" have a single
candidate explanation.

What this produces is a set of observed transitions and exact rate differences.
It establishes no resolution superiority, no causality, no significance and no
general false-match rate, and the report says so in its own last section.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from fpbench.core.enums import PairedEvaluationStatus
from fpbench.core.errors import (
    ConfigurationError,
    PairedEvaluationError,
    PairedFinalizationError,
    PreflightError,
    StorageError,
)
from fpbench.core.paired_models import (
    PairedEvaluationDefinition,
    PairedEvaluationManifest,
    common_eligible_view_hash,
    ordered_eligibility_transitions_hash,
    ordered_paired_observations_hash,
    ordered_paired_records_hash,
    ordered_transition_counts_hash,
    paired_evaluation_definition_fingerprint,
    paired_evaluation_fingerprint,
    paired_evaluation_id,
    PAIRED_EVALUATION_ID_LENGTH,
)
from fpbench.core.provenance_models import (
    SoftwareProvenance,
    software_provenance_fingerprint,
)
from fpbench.core.json_io import write_json
from fpbench.paired import (
    align_pairs,
    build_common_eligible_view,
    build_control_audit,
    build_eligibility_transitions,
    build_paired_finalization_marker,
    build_paired_observations,
    build_paired_receipt,
    build_paired_records,
    build_paired_summary,
    build_transition_counts,
    inspect_paired_evaluation,
    load_paired_policy,
    load_paired_side,
    release_order,
    render_paired_report,
    require_clean_control,
    require_comparable_runs,
    verify_paired_receipt,
    write_paired_evidence_copies,
)
from fpbench.paired.status import PairedEvaluationState
from fpbench.storage.paired_evaluation_store import (
    PairedEvaluationStore,
    paired_summary_content_hash,
    report_content_hash,
)

__all__ = [
    "PairedComparisonConfig",
    "load_paired_config",
    "prepare_paired_evaluation",
    "derive_paired_evaluation",
    "inspect_paired_experiment",
    "verify_paired_evaluation_against_sources",
    "finalize_paired_evaluation",
    "read_verified_paired_report",
    "EXPERIMENT_ID",
    "main",
]

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_WORKSPACE = REPOSITORY_ROOT / "workspace"

EXPERIMENT_ID = "sourceafis_native_vs_canonical500_v1"
DEFAULT_CONFIG = (
    REPOSITORY_ROOT / "configs" / "comparisons" / f"{EXPERIMENT_ID}.yaml"
)

_POINTER_NAME = "current-paired-evaluation.json"
_UNRESOLVED = "TO_BE_FILLED"


# -------------------------------------------------------------------- config


@dataclass(frozen=True, slots=True)
class PairedComparisonConfig:
    """The two chains, named exactly, and the policy that compares them."""

    experiment_id: str

    native: Mapping[str, str]
    canonical: Mapping[str, str]

    policy_config: Path
    evidence_directory: Path


def load_paired_config(
    path: Path = DEFAULT_CONFIG, *, repository_root: Path = REPOSITORY_ROOT
) -> PairedComparisonConfig:
    """Read ``configs/comparisons/<name>.yaml``.

    Every id is exact. There is no "latest": a comparison that resolved its own
    inputs would silently become a different comparison the next time either
    chain was re-derived (spec section 26).
    """
    path = Path(path)
    if not path.is_file():
        raise ConfigurationError(f"paired comparison config not found: {path}")
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(document, Mapping):
        raise ConfigurationError(f"{path}: expected a mapping at the top level")

    experiment = _section(document, "experiment", path)
    native = _section(document, "native", path)
    canonical = _section(document, "canonical", path)
    policy = _section(document, "policy", path)

    required = (
        "run_id",
        "result_set_id",
        "decision_set_id",
        "eligibility_set_id",
        "metric_set_id",
    )
    sides = {}
    for label, block in (("native", native), ("canonical", canonical)):
        values = {}
        for key in required:
            if key not in block:
                raise ConfigurationError(f"{path}: {label}.{key} is required")
            value = str(block[key])
            if _UNRESOLVED in value or value.lower() == "latest":
                raise ConfigurationError(
                    f"{path}: {label}.{key} is {value!r}. Every id must be exact — "
                    "derive the chain first, then write the id it produced"
                )
            values[key] = value
        sides[label] = values

    return PairedComparisonConfig(
        experiment_id=str(experiment["id"]),
        native=sides["native"],
        canonical=sides["canonical"],
        policy_config=(
            Path(repository_root) / str(policy["ref"])
            if "ref" in policy
            else Path(repository_root)
            / "configs"
            / "comparisons"
            / "policies"
            / f"{policy['policy_id']}.yaml"
        ),
        evidence_directory=Path("evidence") / "sourceafis-native-vs-canonical500",
    )


# ------------------------------------------------------------------ prepared


@dataclass(frozen=True, slots=True)
class PreparedPairedComparison:
    """Both chains, revalidated, plus the definition that pins them."""

    config: PairedComparisonConfig
    policy: Any
    software: SoftwareProvenance
    workspace: Path

    native: Any
    canonical: Any
    definition: PairedEvaluationDefinition

    @property
    def store(self) -> PairedEvaluationStore:
        return PairedEvaluationStore(self.workspace)


# ------------------------------------------------------------------- prepare


def prepare_paired_evaluation(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    config: PairedComparisonConfig | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    require_clean: bool = True,
    write_pointer: bool = True,
    definition_software: SoftwareProvenance | None = None,
) -> PreparedPairedComparison:
    """Load and revalidate both chains, prove they are comparable, pin nothing else.

    No transition is computed here. ``prepare`` exists so that a mismatched
    cohort, a rebuilt jar or an unfinalised evaluation stops the comparison
    before it produces numbers that look meaningful (spec section 58).
    """
    workspace = Path(workspace)
    config = config or load_paired_config(repository_root=repository_root)
    verifier_software = _capture(repository_root, require_clean=require_clean)
    definition_software = definition_software or verifier_software
    policy = load_paired_policy(config.policy_config)

    from fpbench.experiments.sourceafis_canonical500_evaluation import (
        canonical_evaluation_spec,
    )
    from fpbench.experiments.sourceafis_native_evaluation import (
        native_evaluation_spec,
    )

    native_evaluation = native_evaluation_spec(repository_root=repository_root)
    canonical_evaluation = canonical_evaluation_spec(
        repository_root=repository_root
    )
    native = load_paired_side(
        label="native",
        spec=native_evaluation.decision_spec,
        evaluation_spec=native_evaluation,
        workspace=workspace,
        repository_root=repository_root,
        run_id=config.native["run_id"],
        decision_set_id=config.native["decision_set_id"],
        metric_set_id=config.native["metric_set_id"],
        software=verifier_software,
    )
    canonical = load_paired_side(
        label="canonical",
        spec=canonical_evaluation.decision_spec,
        evaluation_spec=canonical_evaluation,
        workspace=workspace,
        repository_root=repository_root,
        run_id=config.canonical["run_id"],
        decision_set_id=config.canonical["decision_set_id"],
        metric_set_id=config.canonical["metric_set_id"],
        software=verifier_software,
    )
    _require_declared_ids(config, native, canonical)
    require_comparable_runs(native=native, canonical=canonical)

    definition = _build_definition(
        native=native,
        canonical=canonical,
        policy=policy,
        software=definition_software,
    )
    prepared = PreparedPairedComparison(
        config=config,
        policy=policy,
        software=definition_software,
        workspace=workspace,
        native=native,
        canonical=canonical,
        definition=definition,
    )
    if write_pointer:
        _write_pointer(
            workspace,
            config.experiment_id,
            carry_forward_pointer(
                _read_pointer_payload(workspace, config.experiment_id),
                {
                    "experiment_id": config.experiment_id,
                    "definition_id": definition.definition_id,
                    "native_run_id": native.run.run_id,
                    "canonical_run_id": canonical.run.run_id,
                    "prepared_utc": _utc_now(),
                },
            ),
        )
    return prepared


# -------------------------------------------------------------------- derive


def derive_paired_evaluation(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    config: PairedComparisonConfig | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    require_clean: bool = True,
) -> str:
    """Align, record, audit the control, then aggregate. Returns the paired id."""
    prepared = prepare_paired_evaluation(
        workspace=workspace,
        config=config,
        repository_root=repository_root,
        require_clean=require_clean,
    )
    native, canonical = prepared.native, prepared.canonical

    rebuilt = _rebuild_paired_evaluation(prepared)
    records = rebuilt.records
    transitions = rebuilt.transitions
    common = rebuilt.common
    control = rebuilt.control
    counts = rebuilt.counts
    observations = rebuilt.observations
    manifest = rebuilt.manifest
    paired_id = manifest.paired_evaluation_id

    store = prepared.store
    store.ensure_definition(paired_id, prepared.definition)
    store.ensure_policy(paired_id, dict(prepared.policy.document))
    store.ensure_records(paired_id, records)
    store.ensure_eligibility_transitions(paired_id, transitions)
    store.ensure_common_eligible_view(paired_id, common)
    store.ensure_counts(paired_id, counts)
    store.ensure_observations(paired_id, observations)
    store.ensure_control_audit(paired_id, control)
    store.ensure_manifest(manifest)

    # Read it all back and re-check before claiming anything was written.
    store.verify_paired_evaluation(paired_id)

    _write_pointer(
        prepared.workspace,
        prepared.config.experiment_id,
        {
            "experiment_id": prepared.config.experiment_id,
            "definition_id": prepared.definition.definition_id,
            "paired_evaluation_id": paired_id,
            "native_run_id": native.run.run_id,
            "canonical_run_id": canonical.run.run_id,
            "derived_utc": _utc_now(),
        },
    )
    return paired_id


# -------------------------------------------------------------------- status


def inspect_paired_experiment(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    config: PairedComparisonConfig | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    paired_evaluation_id_override: str | None = None,
) -> PairedEvaluationState:
    """Report where the comparison stands. Never writes."""
    workspace = Path(workspace)
    config = config or load_paired_config(repository_root=repository_root)
    resolved = paired_evaluation_id_override or _read_pointer(
        workspace, config.experiment_id, "paired_evaluation_id"
    )
    store = PairedEvaluationStore(workspace)
    state = inspect_paired_evaluation(
        store=store, paired_evaluation_id=resolved
    )
    if not state.manifest_valid:
        return state
    try:
        return verify_paired_evaluation_against_sources(
            workspace=workspace,
            config=config,
            repository_root=repository_root,
            paired_evaluation_id=str(resolved),
            storage_state=state,
        )
    except (
        ConfigurationError,
        PairedEvaluationError,
        PreflightError,
        StorageError,
        OSError,
        TypeError,
        ValueError,
    ) as exc:
        return replace(
            state,
            status=PairedEvaluationStatus.INVALID,
            finalization_valid=False,
            issues=(*state.issues, f"source verification failed: {exc}"),
            inspected_utc=_utc_now(),
        )


@dataclass(frozen=True, slots=True)
class _RebuiltPairedEvaluation:
    records: tuple
    transitions: tuple
    common: tuple
    control: Any
    releases: tuple[str, ...]
    counts: tuple
    observations: tuple
    manifest: PairedEvaluationManifest


def _rebuild_paired_evaluation(prepared: PreparedPairedComparison) -> _RebuiltPairedEvaluation:
    """Recompute every paired artefact from the two verified source chains."""
    native, canonical = prepared.native, prepared.canonical
    pair_ids = align_pairs(native=native, canonical=canonical)
    records = build_paired_records(
        native=native, canonical=canonical, pair_ids=pair_ids
    )
    transitions = build_eligibility_transitions(native=native, canonical=canonical)
    common = build_common_eligible_view(
        native=native,
        canonical=canonical,
        transitions=transitions,
        records=records,
    )
    control = build_control_audit(records)
    require_clean_control(control)
    releases = release_order(native)
    counts = build_transition_counts(
        records=records,
        transitions=transitions,
        common_eligible=common,
        releases=releases,
        source_fingerprints=_source_fingerprints(native, canonical),
    )
    observations = build_paired_observations(
        records=records,
        transitions=transitions,
        common_eligible=common,
        releases=releases,
        policy_fingerprint=prepared.policy.policy_fingerprint,
    )
    manifest = _build_manifest(
        definition=prepared.definition,
        records=records,
        transitions=transitions,
        common=common,
        counts=counts,
        observations=observations,
        control=control,
    )
    return _RebuiltPairedEvaluation(
        records=records,
        transitions=transitions,
        common=common,
        control=control,
        releases=releases,
        counts=counts,
        observations=observations,
        manifest=manifest,
    )


def verify_paired_evaluation_against_sources(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    config: PairedComparisonConfig | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    paired_evaluation_id: str,
    storage_state: PairedEvaluationState | None = None,
) -> PairedEvaluationState:
    """Rebuild a stored comparison from both source chains without writing.

    Storage verification is intentionally only the first layer. This verifier
    reloads both runs, decision/eligibility/metric sets and the frozen policy,
    aligns all pairs, rebuilds every table and publication artefact, and finally
    proves that the ready marker names those canonical results.
    """
    workspace = Path(workspace)
    config = config or load_paired_config(repository_root=repository_root)
    store = PairedEvaluationStore(workspace)
    state = storage_state or inspect_paired_evaluation(
        store=store, paired_evaluation_id=paired_evaluation_id
    )
    if not state.manifest_valid:
        raise PairedFinalizationError(
            f"paired comparison {paired_evaluation_id} is not storage-valid"
        )

    stored_definition = store.read_definition(paired_evaluation_id)
    prepared = prepare_paired_evaluation(
        workspace=workspace,
        config=config,
        repository_root=repository_root,
        require_clean=False,
        write_pointer=False,
        definition_software=stored_definition.derivation_software,
    )
    if prepared.definition.definition_fingerprint != stored_definition.definition_fingerprint:
        raise PairedFinalizationError(
            "the stored paired definition does not match the two current source chains"
        )

    stored_policy = load_paired_policy(store.policy_path(paired_evaluation_id))
    if stored_policy.policy_fingerprint != prepared.policy.policy_fingerprint:
        raise PairedFinalizationError(
            "policy.json does not match the configured paired-comparison policy"
        )
    if stored_policy.policy_fingerprint != stored_definition.policy_fingerprint:
        raise PairedFinalizationError(
            "policy.json fingerprint does not match the paired definition"
        )

    rebuilt = _rebuild_paired_evaluation(prepared)
    stored_manifest = store.verify_paired_evaluation(paired_evaluation_id)
    if rebuilt.manifest.paired_evaluation_id != paired_evaluation_id:
        raise PairedFinalizationError(
            f"the sources derive {rebuilt.manifest.paired_evaluation_id}, not "
            f"{paired_evaluation_id}"
        )
    if (
        rebuilt.manifest.paired_evaluation_fingerprint
        != stored_manifest.paired_evaluation_fingerprint
    ):
        raise PairedFinalizationError(
            "the stored paired tables do not match a fresh derivation from the sources"
        )

    stored_observations = store.read_observations(paired_evaluation_id)
    if any(
        observation.policy_fingerprint != stored_policy.policy_fingerprint
        for observation in stored_observations
    ):
        raise PairedFinalizationError(
            "an observation does not carry policy.json's fingerprint"
        )

    native_ids = _side_ids(config.native)
    canonical_ids = _side_ids(config.canonical)
    if store.has_summary(paired_evaluation_id):
        stored_summary = store.read_summary(paired_evaluation_id)
        expected_summary = build_paired_summary(
            manifest=stored_manifest,
            native_ids=native_ids,
            canonical_ids=canonical_ids,
            control=rebuilt.control,
            counts=rebuilt.counts,
            observations=rebuilt.observations,
            records=rebuilt.records,
            generated_utc=str(stored_summary.get("generated_utc") or "verified"),
        )
        if paired_summary_content_hash(stored_summary) != paired_summary_content_hash(
            expected_summary
        ):
            raise PairedFinalizationError(
                "summary.json does not match a fresh summary from the sources"
            )

    if store.has_report(paired_evaluation_id):
        expected_report = render_paired_report(
            manifest=stored_manifest,
            policy_id=stored_policy.policy_id,
            native_ids=native_ids,
            canonical_ids=canonical_ids,
            native_source_commit=_run_commit(prepared.native),
            canonical_source_commit=_run_commit(prepared.canonical),
            derivation_commit=stored_definition.derivation_software.source_revision,
            control=rebuilt.control,
            counts=rebuilt.counts,
            observations=rebuilt.observations,
            records=rebuilt.records,
            common_eligible=rebuilt.common,
            transitions=rebuilt.transitions,
            releases=rebuilt.releases,
        )
        if store.read_report(paired_evaluation_id) != expected_report:
            raise PairedFinalizationError(
                "report.md is not byte-identical to a fresh rendering from the sources"
            )

    if store.has_receipt(paired_evaluation_id):
        receipt = store.read_receipt(paired_evaluation_id)
        if (
            receipt.source_commit
            != stored_definition.derivation_software.source_revision
            or receipt.source_tree_clean
            != stored_definition.derivation_software.source_tree_clean
        ):
            raise PairedFinalizationError(
                "the paired receipt names different derivation software"
            )
        verify_paired_receipt(
            receipt=receipt,
            manifest=stored_manifest,
            policy_id=stored_policy.policy_id,
            policy_fingerprint=stored_policy.policy_fingerprint,
            native_ids=native_ids,
            canonical_ids=canonical_ids,
            canonical_preparation_set_id=_canonical_preparation_set_id(repository_root),
            pair_manifest_hash=prepared.native.pair_manifest_hash,
            control=rebuilt.control,
            counts=rebuilt.counts,
            observations=rebuilt.observations,
        )

    if store.has_finalization(paired_evaluation_id):
        marker = store.read_finalization(paired_evaluation_id)
        receipt = store.read_receipt(paired_evaluation_id)
        expected_marker = build_paired_finalization_marker(
            manifest=stored_manifest,
            control=rebuilt.control,
            summary_content_hash=paired_summary_content_hash(
                store.read_summary(paired_evaluation_id)
            ),
            report_content_hash=report_content_hash(
                store.read_report(paired_evaluation_id)
            ),
            receipt=receipt,
            source_commit=stored_definition.derivation_software.source_revision,
            source_tree_clean=stored_definition.derivation_software.source_tree_clean,
            created_utc=marker.created_utc,
        )
        if marker.finalization_fingerprint != expected_marker.finalization_fingerprint:
            raise PairedFinalizationError(
                "the finalization marker does not cover the canonical source-derived artefacts"
            )

    return state


# ------------------------------------------------------------------ finalize


def finalize_paired_evaluation(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    config: PairedComparisonConfig | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    paired_evaluation_id_override: str | None = None,
) -> str:
    """Re-derive everything from the two chains, then publish the marker last.

    The comparison is rebuilt from scratch — aligned, recorded, audited,
    aggregated — and compared against what is stored, rather than the stored
    artefacts being checked for internal consistency. The report is re-rendered
    and required to match byte for byte (spec sections 60 and 75).
    """
    prepared = prepare_paired_evaluation(
        workspace=workspace, config=config, repository_root=repository_root
    )
    native, canonical = prepared.native, prepared.canonical
    store = prepared.store

    rebuilt = _rebuild_paired_evaluation(prepared)
    records = rebuilt.records
    transitions = rebuilt.transitions
    common = rebuilt.common
    control = rebuilt.control
    releases = rebuilt.releases
    counts = rebuilt.counts
    observations = rebuilt.observations
    manifest = rebuilt.manifest
    paired_id = paired_evaluation_id_override or manifest.paired_evaluation_id
    if paired_id != manifest.paired_evaluation_id:
        raise PairedFinalizationError(
            f"the stored comparison is {paired_id} but the sources now derive "
            f"{manifest.paired_evaluation_id}; the two chains changed underneath it"
        )
    if not store.has_manifest(paired_id):
        raise PairedFinalizationError(
            f"no paired comparison {paired_id} has been derived; run 'derive' first"
        )

    stored_manifest = store.verify_paired_evaluation(paired_id)
    if (
        stored_manifest.paired_evaluation_fingerprint
        != manifest.paired_evaluation_fingerprint
    ):
        raise PairedFinalizationError(
            "the stored comparison does not match a fresh derivation from the two "
            "chains"
        )

    native_ids = _side_ids(prepared.config.native)
    canonical_ids = _side_ids(prepared.config.canonical)

    summary = build_paired_summary(
        manifest=stored_manifest,
        native_ids=native_ids,
        canonical_ids=canonical_ids,
        control=control,
        counts=counts,
        observations=observations,
        records=records,
        generated_utc=_utc_now(),
    )
    store.ensure_summary(paired_id, summary)
    stored_summary = store.read_summary(paired_id)

    markdown = render_paired_report(
        manifest=stored_manifest,
        policy_id=prepared.policy.policy_id,
        native_ids=native_ids,
        canonical_ids=canonical_ids,
        native_source_commit=_run_commit(native),
        canonical_source_commit=_run_commit(canonical),
        derivation_commit=prepared.software.source_revision,
        control=control,
        counts=counts,
        observations=observations,
        records=records,
        common_eligible=common,
        transitions=transitions,
        releases=releases,
    )
    store.ensure_report(paired_id, markdown)
    stored_markdown = store.read_report(paired_id)
    if stored_markdown != markdown:
        raise PairedFinalizationError(
            "the stored paired report is not byte-identical to a fresh rendering"
        )

    receipt = build_paired_receipt(
        manifest=stored_manifest,
        policy_id=prepared.policy.policy_id,
        policy_fingerprint=prepared.policy.policy_fingerprint,
        native_ids=native_ids,
        canonical_ids=canonical_ids,
        canonical_preparation_set_id=_canonical_preparation_set_id(repository_root),
        pair_manifest_hash=native.pair_manifest_hash,
        control=control,
        counts=counts,
        observations=observations,
        source_commit=prepared.software.source_revision,
        source_tree_clean=prepared.software.source_tree_clean,
    )
    store.ensure_receipt(paired_id, receipt)
    stored_receipt = store.read_receipt(paired_id)
    verify_paired_receipt(
        receipt=stored_receipt,
        manifest=stored_manifest,
        policy_id=prepared.policy.policy_id,
        policy_fingerprint=prepared.policy.policy_fingerprint,
        native_ids=native_ids,
        canonical_ids=canonical_ids,
        canonical_preparation_set_id=_canonical_preparation_set_id(repository_root),
        pair_manifest_hash=native.pair_manifest_hash,
        control=control,
        counts=counts,
        observations=observations,
    )

    marker = build_paired_finalization_marker(
        manifest=stored_manifest,
        control=control,
        summary_content_hash=paired_summary_content_hash(stored_summary),
        report_content_hash=report_content_hash(stored_markdown),
        receipt=stored_receipt,
        source_commit=prepared.software.source_revision,
        source_tree_clean=prepared.software.source_tree_clean,
    )
    store.ensure_finalization(paired_id, marker)

    state = verify_paired_evaluation_against_sources(
        workspace=workspace,
        config=prepared.config,
        repository_root=repository_root,
        paired_evaluation_id=paired_id,
        storage_state=inspect_paired_evaluation(
            store=store, paired_evaluation_id=paired_id
        ),
    )
    if not state.is_paired_evaluation_ready:
        raise PairedFinalizationError(
            f"paired comparison {paired_id} finalised but did not reach "
            f"PAIRED_EVALUATION_READY: {state.status.value} "
            f"{list(state.issues)[:3]}"
        )

    write_paired_evidence_copies(
        receipt=stored_receipt,
        markdown=stored_markdown,
        repository_root=Path(repository_root),
        directory=prepared.config.evidence_directory,
    )
    _write_pointer(
        prepared.workspace,
        prepared.config.experiment_id,
        {
            "experiment_id": prepared.config.experiment_id,
            "definition_id": prepared.definition.definition_id,
            "paired_evaluation_id": paired_id,
            "native_run_id": native.run.run_id,
            "canonical_run_id": canonical.run.run_id,
            "finalized_utc": _utc_now(),
        },
    )
    return paired_id


# ---------------------------------------------------------------------- show


def read_verified_paired_report(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    config: PairedComparisonConfig | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    paired_evaluation_id_override: str | None = None,
) -> str:
    """The report, but only from a comparison that is fully verified."""
    state = inspect_paired_experiment(
        workspace=workspace,
        config=config,
        repository_root=repository_root,
        paired_evaluation_id_override=paired_evaluation_id_override,
    )
    if not state.is_paired_evaluation_ready:
        raise PairedFinalizationError(
            f"this comparison is {state.status.value}, not "
            f"paired_evaluation_ready; there is no verified report to show "
            f"{list(state.issues)[:3]}"
        )
    return PairedEvaluationStore(Path(workspace)).read_report(
        str(state.paired_evaluation_id)
    )


# ----------------------------------------------------------------- internals


def _require_declared_ids(
    config: PairedComparisonConfig, native, canonical
) -> None:
    """The config's ids must be the ids the workspace actually holds."""
    for label, declared, side in (
        ("native", config.native, native),
        ("canonical", config.canonical, canonical),
    ):
        actual = {
            "run_id": side.run.run_id,
            "result_set_id": side.result_set.result_set_id,
            "decision_set_id": side.decision_manifest.decision_set_id,
            "eligibility_set_id": side.eligibility_manifest.eligibility_set_id,
            "metric_set_id": side.metric_manifest.metric_set_id,
        }
        for key, value in declared.items():
            if actual[key] != value:
                raise PairedEvaluationError(
                    f"{label}.{key} is declared as {value!r} but the workspace "
                    f"holds {actual[key]!r}"
                )


def _build_definition(*, native, canonical, policy, software):
    claims_source = dict(
        native_run_fingerprint=native.run.run_fingerprint,
        canonical_run_fingerprint=canonical.run.run_fingerprint,
        native_result_set_fingerprint=native.result_set.result_set_fingerprint,
        canonical_result_set_fingerprint=canonical.result_set.result_set_fingerprint,
        native_decision_set_fingerprint=(
            native.decision_manifest.decision_set_fingerprint
        ),
        canonical_decision_set_fingerprint=(
            canonical.decision_manifest.decision_set_fingerprint
        ),
        native_eligibility_set_fingerprint=(
            native.eligibility_manifest.eligibility_set_fingerprint
        ),
        canonical_eligibility_set_fingerprint=(
            canonical.eligibility_manifest.eligibility_set_fingerprint
        ),
        native_metric_set_fingerprint=native.metric_manifest.metric_set_fingerprint,
        canonical_metric_set_fingerprint=(
            canonical.metric_manifest.metric_set_fingerprint
        ),
        pair_manifest_hash=native.pair_manifest_hash,
        policy_fingerprint=policy.policy_fingerprint,
        derivation_software_fingerprint=software_provenance_fingerprint(software),
    )
    from fpbench.core.paired_models import PAIRED_SCHEMA_VERSION

    fingerprint = paired_evaluation_definition_fingerprint(
        {"paired_schema_version": PAIRED_SCHEMA_VERSION, **claims_source}
    )
    return PairedEvaluationDefinition(
        definition_id=f"paireddef_{fingerprint[:PAIRED_EVALUATION_ID_LENGTH]}",
        definition_fingerprint=fingerprint,
        derivation_software=software,
        created_utc=_utc_now(),
        **claims_source,
    )


def _build_manifest(
    *, definition, records, transitions, common, counts, observations, control
) -> PairedEvaluationManifest:
    records_hash = ordered_paired_records_hash(records)
    eligibility_hash = ordered_eligibility_transitions_hash(transitions)
    common_hash = common_eligible_view_hash(common)
    counts_hash = ordered_transition_counts_hash(counts)
    observations_hash = ordered_paired_observations_hash(observations)
    included = sum(1 for entry in common if entry.included)

    fingerprint = paired_evaluation_fingerprint(
        definition_fingerprint=definition.definition_fingerprint,
        ordered_records_hash=records_hash,
        ordered_eligibility_hash=eligibility_hash,
        common_eligible_hash=common_hash,
        ordered_counts_hash=counts_hash,
        ordered_observations_hash=observations_hash,
        control_fingerprint=control.audit_fingerprint,
        total_paired_comparisons=len(records),
        total_eligibility_units=len(transitions),
        total_common_eligible_rows=included,
    )
    return PairedEvaluationManifest(
        paired_evaluation_id=paired_evaluation_id(fingerprint),
        paired_evaluation_fingerprint=fingerprint,
        definition_fingerprint=definition.definition_fingerprint,
        total_paired_comparisons=len(records),
        total_eligibility_units=len(transitions),
        total_common_eligible_rows=included,
        ordered_paired_records_hash=records_hash,
        ordered_eligibility_transitions_hash=eligibility_hash,
        common_eligible_view_hash=common_hash,
        ordered_count_records_hash=counts_hash,
        ordered_observations_hash=observations_hash,
        control_audit_fingerprint=control.audit_fingerprint,
        created_utc=_utc_now(),
    )


def _source_fingerprints(native, canonical) -> Mapping[str, str]:
    return {
        "native_decision_set": native.decision_manifest.decision_set_fingerprint,
        "canonical_decision_set": (
            canonical.decision_manifest.decision_set_fingerprint
        ),
        "native_eligibility_set": (
            native.eligibility_manifest.eligibility_set_fingerprint
        ),
        "canonical_eligibility_set": (
            canonical.eligibility_manifest.eligibility_set_fingerprint
        ),
    }


def _side_ids(declared: Mapping[str, str]) -> Mapping[str, str]:
    return dict(declared)


def _run_commit(side) -> str:
    store = side.result_store
    run_id = side.run.run_id
    if not store.has_research_receipt(run_id):
        return "unrecorded"
    return store.read_research_receipt(run_id).source_commit


def _canonical_preparation_set_id(repository_root: Path) -> str:
    from fpbench.experiments.sourceafis_canonical500_full import (
        load_canonical_experiment_config,
    )

    return load_canonical_experiment_config(
        repository_root=repository_root
    ).preparation_set_id


def _capture(repository_root: Path, *, require_clean: bool) -> SoftwareProvenance:
    from fpbench.provenance.software import capture_software_provenance

    return capture_software_provenance(
        repository_root=Path(repository_root), require_clean=require_clean
    )


def _section(document: Mapping[str, Any], key: str, path: Path) -> Mapping[str, Any]:
    value = document.get(key)
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"{path}: missing or malformed '{key}' section")
    return value


def _pointer_path(workspace: Path, experiment_id: str) -> Path:
    return Path(workspace) / "experiments" / experiment_id / _POINTER_NAME


def _write_pointer(
    workspace: Path, experiment_id: str, payload: Mapping[str, Any]
) -> Path:
    return write_json(_pointer_path(workspace, experiment_id), dict(payload))


def _read_pointer_payload(workspace: Path, experiment_id: str) -> Mapping[str, Any]:
    from fpbench.core.serialization import read_json

    path = _pointer_path(workspace, experiment_id)
    return read_json(path) if path.is_file() else {}


def _read_pointer(workspace: Path, experiment_id: str, key: str) -> str | None:
    payload = _read_pointer_payload(workspace, experiment_id)
    return str(payload.get(key) or "") or None


#: What a re-prepare keeps from the pointer it is about to overwrite.
CARRIED_POINTER_KEYS = ("paired_evaluation_id", "derived_utc", "finalized_utc")


def carry_forward_pointer(
    existing: Mapping[str, Any], fresh: Mapping[str, Any]
) -> dict[str, Any]:
    """Merge a freshly prepared pointer over its predecessor.

    ``derive`` and ``finalize`` both re-prepare before doing anything, so a
    pointer that simply overwrote its predecessor would delete the derived id a
    successful finalisation had just recorded — leaving ``status`` reporting
    ``not_prepared`` over a finished comparison.

    The derived id is carried across only while the definition underneath it is
    unchanged. If the definition moved — a new derivation commit, a re-derived
    input chain — the earlier derivation belongs to a comparison this one is
    not, and pointing at it would be worse than pointing at nothing.
    """
    merged = dict(fresh)
    if existing.get("definition_id") != fresh.get("definition_id"):
        return merged
    for key in CARRIED_POINTER_KEYS:
        carried = existing.get(key)
        if carried:
            merged[key] = carried
    return merged


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


# --------------------------------------------------------------------- CLI


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m fpbench.experiments.sourceafis_native_vs_canonical500",
        description=(
            "Compare the native and canonical 500 ppi SourceAFIS derivations pair "
            "by pair. Observes transitions and exact rate differences; establishes "
            "no resolution superiority, no causality and no significance."
        ),
    )
    parser.add_argument(
        "command", choices=("prepare", "derive", "status", "finalize", "show")
    )
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--paired-evaluation-id", default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(list(argv) if argv is not None else None)
    try:
        config = load_paired_config(arguments.config)
        shared = {"workspace": arguments.workspace, "config": config}

        if arguments.command == "prepare":
            prepared = prepare_paired_evaluation(**shared)
            print(f"native       {prepared.native.run.run_id}")
            print(f"canonical    {prepared.canonical.run.run_id}")
            print(f"policy       {prepared.policy.policy_id}")
            print(f"definition   {prepared.definition.definition_id}")
            print(f"pairs        {len(prepared.native.pairs)}")
            return 0

        if arguments.command == "derive":
            paired_id = derive_paired_evaluation(**shared)
            print(f"paired eval  {paired_id}")
            print("next         finalize")
            return 0

        if arguments.command == "status":
            state = inspect_paired_experiment(
                **shared,
                paired_evaluation_id_override=arguments.paired_evaluation_id,
            )
            print(f"paired eval  {state.paired_evaluation_id or '-'}")
            print(f"status       {state.status.value}")
            print(f"comparisons  {state.total_paired_comparisons}")
            print(f"units        {state.total_eligibility_units}")
            print(f"common       {state.total_common_eligible_rows} eligible both")
            print(f"control      {'clean' if state.control_audit_clean else 'FAILED'}")
            print(f"manifest     {'valid' if state.manifest_valid else 'no'}")
            print(f"summary      {'valid' if state.summary_valid else 'no'}")
            print(f"report       {'valid' if state.report_valid else 'no'}")
            print(f"receipt      {'valid' if state.receipt_valid else 'no'}")
            print(f"finalized    {'valid' if state.finalization_valid else 'no'}")
            for issue in state.issues[:10]:
                print(f"  issue      {issue}")
            return 0

        if arguments.command == "finalize":
            paired_id = finalize_paired_evaluation(
                **shared,
                paired_evaluation_id_override=arguments.paired_evaluation_id,
            )
            print(f"paired eval  {paired_id}")
            print(
                f"evidence     evidence/sourceafis-native-vs-canonical500/"
                f"{paired_id}.json"
            )
            print(
                f"             evidence/sourceafis-native-vs-canonical500/"
                f"{paired_id}.md"
            )
            print("status       paired_evaluation_ready")
            return 0

        print(
            read_verified_paired_report(
                **shared,
                paired_evaluation_id_override=arguments.paired_evaluation_id,
            )
        )
        return 0
    except (
        PreflightError,
        ConfigurationError,
        PairedEvaluationError,
        StorageError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
