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
from dataclasses import dataclass
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
from fpbench.core.serialization import write_json
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
) -> PreparedPairedComparison:
    """Load and revalidate both chains, prove they are comparable, pin nothing else.

    No transition is computed here. ``prepare`` exists so that a mismatched
    cohort, a rebuilt jar or an unfinalised evaluation stops the comparison
    before it produces numbers that look meaningful (spec section 58).
    """
    workspace = Path(workspace)
    config = config or load_paired_config(repository_root=repository_root)
    software = _capture(repository_root, require_clean=require_clean)
    policy = load_paired_policy(config.policy_config)

    from fpbench.experiments.sourceafis_canonical500_decisions import (
        load_canonical_decision_spec,
    )
    from fpbench.experiments.sourceafis_native_decisions import (
        load_decision_experiment_config,
    )

    native = load_paired_side(
        label="native",
        spec=load_decision_experiment_config(repository_root=repository_root),
        workspace=workspace,
        repository_root=repository_root,
        run_id=config.native["run_id"],
        decision_set_id=config.native["decision_set_id"],
        metric_set_id=config.native["metric_set_id"],
        software=software,
    )
    canonical = load_paired_side(
        label="canonical",
        spec=load_canonical_decision_spec(repository_root=repository_root),
        workspace=workspace,
        repository_root=repository_root,
        run_id=config.canonical["run_id"],
        decision_set_id=config.canonical["decision_set_id"],
        metric_set_id=config.canonical["metric_set_id"],
        software=software,
    )
    _require_declared_ids(config, native, canonical)
    require_comparable_runs(native=native, canonical=canonical)

    definition = _build_definition(
        native=native,
        canonical=canonical,
        policy=policy,
        software=software,
    )
    prepared = PreparedPairedComparison(
        config=config,
        policy=policy,
        software=software,
        workspace=workspace,
        native=native,
        canonical=canonical,
        definition=definition,
    )
    _write_pointer(
        workspace,
        config.experiment_id,
        {
            "experiment_id": config.experiment_id,
            "definition_id": definition.definition_id,
            "native_run_id": native.run.run_id,
            "canonical_run_id": canonical.run.run_id,
            "prepared_utc": _utc_now(),
        },
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

    # Before any aggregate. A failed control withdraws the interpretation every
    # later number depends on, so producing them would be producing something
    # nobody could read (spec section 59, step 6).
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
    return inspect_paired_evaluation(
        store=PairedEvaluationStore(workspace), paired_evaluation_id=resolved
    )


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

    pair_ids = align_pairs(native=native, canonical=canonical)
    records = build_paired_records(
        native=native, canonical=canonical, pair_ids=pair_ids
    )
    transitions = build_eligibility_transitions(native=native, canonical=canonical)
    common = build_common_eligible_view(
        native=native, canonical=canonical, transitions=transitions, records=records
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

    state = inspect_paired_evaluation(store=store, paired_evaluation_id=paired_id)
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


def _read_pointer(workspace: Path, experiment_id: str, key: str) -> str | None:
    from fpbench.core.serialization import read_json

    path = _pointer_path(workspace, experiment_id)
    if not path.is_file():
        return None
    payload = read_json(path)
    return str(payload.get(key) or "") or None


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
