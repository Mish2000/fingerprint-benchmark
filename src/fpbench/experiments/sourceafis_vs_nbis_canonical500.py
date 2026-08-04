"""SourceAFIS and NBIS, over the same 6,000 comparisons, side by side.

    python -m fpbench.experiments.sourceafis_vs_nbis_canonical500 prepare
    python -m fpbench.experiments.sourceafis_vs_nbis_canonical500 derive
    python -m fpbench.experiments.sourceafis_vs_nbis_canonical500 status
    python -m fpbench.experiments.sourceafis_vs_nbis_canonical500 finalize
    python -m fpbench.experiments.sourceafis_vs_nbis_canonical500 show

The last gate of stage 7D, and the thinnest module in it. Every judgement it
could make has already been made somewhere with a fingerprint on it: the
thresholds in two committed profiles, the methodology in a committed protocol,
the refusals in a committed policy, the counting rules in one metric policy both
chains cite. What is left here is loading, checking and publishing.

Three checks decide whether anything is published at all:

1. **Both chains are ``EVALUATION_READY``.** A comparison cannot outrank the
   metrics beneath it.
2. **Stage 7C's alignment still holds**, re-derived from the manifests, and is
   the one the frozen protocol names. Without it the two sets of decisions are
   not over the same inputs and the paired rows are not pairs
   (docs/adr/0054, spec section 57).
3. **The fair-comparability audit is clean** — same pairs, same meanings, same
   prepared images, same eligibility policy, same metric policy, same execution
   profile, nothing calibrated, no test cohort used, no operating points
   equated, no raw scores compared (spec section 56).

There is no ``--latest`` and no fallback. Every id comes from a committed config,
and a placeholder in it is an error rather than an invitation.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from fpbench.core.cross_algorithm_models import (
    CrossAlgorithmEvaluationDefinition,
    cross_algorithm_definition_fingerprint,
)
from fpbench.core.errors import ConfigurationError, DerivationError, PreflightError
from fpbench.core.provenance_models import (
    SoftwareProvenance,
    software_provenance_fingerprint,
)
from fpbench.core.serialization import to_plain
from fpbench.cross_algorithm import (
    ComparisonSide,
    CrossAlgorithmError,
    EVIDENCE_DIRECTORY,
    build_comparison_records,
    build_cross_algorithm_finalization,
    build_cross_algorithm_receipt,
    build_fair_comparability_audit,
    derive_cross_algorithm_evaluation,
    inspect_cross_algorithm_evaluation,
    load_comparison_policy,
    render_report,
    report_content_hash,
    require_clean_audit,
    verify_derivation,
    write_evidence,
)
from fpbench.cross_algorithm.align import load_fair_measurement_protocol
from fpbench.experiments.sd300_inputs import EXPECTED_JOBS, EXPECTED_PER_STAGE

__all__ = [
    "EXPERIMENT_ID",
    "EVIDENCE_DIRECTORY",
    "DEFAULT_COMPARISON_CONFIG",
    "ComparisonExperimentConfig",
    "PreparedComparison",
    "load_comparison_config",
    "prepare_comparison",
    "derive_comparison",
    "inspect_comparison",
    "finalize_comparison",
    "read_verified_comparison_report",
    "main",
]

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_WORKSPACE = REPOSITORY_ROOT / "workspace"

EXPERIMENT_ID = "sourceafis_vs_nbis_canonical500_documented_points_v1"

DEFAULT_COMPARISON_CONFIG = (
    REPOSITORY_ROOT
    / "configs"
    / "comparisons"
    / f"{EXPERIMENT_ID}.yaml"
)

_UNRESOLVED = "TO_BE_FILLED"

AUDIT_EVIDENCE_NAME = "fair-comparability-audit.json"
FINALIZATION_EVIDENCE_NAME = "cross-algorithm-finalization.json"

_RELEASES = ("SD300A", "SD300B", "SD300C")


# ------------------------------------------------------------------- config


@dataclass(frozen=True, slots=True)
class _SideConfig:
    label: str
    run_id: str
    result_set_id: str
    decision_set_id: str
    eligibility_set_id: str
    metric_set_id: str


@dataclass(frozen=True, slots=True)
class ComparisonExperimentConfig:
    """Which two chains to compare, under which protocol and which policy."""

    experiment_id: str
    protocol_config: Path
    policy_config: Path
    alignment_fingerprint: str
    left: _SideConfig
    right: _SideConfig


def load_comparison_config(
    path: Path = DEFAULT_COMPARISON_CONFIG,
    *,
    repository_root: Path = REPOSITORY_ROOT,
) -> ComparisonExperimentConfig:
    """Read ``configs/comparisons/<name>.yaml``, refusing placeholders.

    Raises:
        ConfigurationError: the file is missing, malformed, or still carries an
            id that has not been bound to a real artefact.
    """
    path = Path(path)
    if not path.is_file():
        raise ConfigurationError(f"comparison config not found: {path}")
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(document, Mapping):
        raise ConfigurationError(f"{path}: expected a mapping at the top level")

    sides = {}
    for name in ("left", "right"):
        block = document.get(name)
        if not isinstance(block, Mapping):
            raise ConfigurationError(f"{path}: missing or malformed {name!r} section")
        for key in (
            "label",
            "run_id",
            "result_set_id",
            "decision_set_id",
            "eligibility_set_id",
            "metric_set_id",
        ):
            if key not in block:
                raise ConfigurationError(f"{path}: {name}.{key} is required")
            if _UNRESOLVED in str(block[key]):
                raise ConfigurationError(
                    f"{path}: {name}.{key} still holds a placeholder. Derive the "
                    "chain first, then write the exact id into this file"
                )
        sides[name] = _SideConfig(
            label=str(block["label"]),
            run_id=str(block["run_id"]),
            result_set_id=str(block["result_set_id"]),
            decision_set_id=str(block["decision_set_id"]),
            eligibility_set_id=str(block["eligibility_set_id"]),
            metric_set_id=str(block["metric_set_id"]),
        )

    experiment = document.get("experiment") or {}
    protocol = document.get("protocol") or {}
    policy = document.get("policy") or {}
    alignment = document.get("alignment") or {}
    for label, block, key in (
        ("protocol", protocol, "ref"),
        ("policy", policy, "ref"),
        ("alignment", alignment, "fingerprint"),
        ("experiment", experiment, "experiment_id"),
    ):
        if not isinstance(block, Mapping) or key not in block:
            raise ConfigurationError(f"{path}: {label}.{key} is required")

    root = Path(repository_root)
    return ComparisonExperimentConfig(
        experiment_id=str(experiment["experiment_id"]),
        protocol_config=root / str(protocol["ref"]),
        policy_config=root / str(policy["ref"]),
        alignment_fingerprint=str(alignment["fingerprint"]),
        left=sides["left"],
        right=sides["right"],
    )


# ------------------------------------------------------------------ prepared


@dataclass(frozen=True, slots=True)
class PreparedComparison:
    """Both verified chains, the frozen protocol, and the fairness audit."""

    config: ComparisonExperimentConfig
    software: SoftwareProvenance
    workspace: Path

    protocol: Any
    policy: Any
    audit: Any
    definition: CrossAlgorithmEvaluationDefinition

    left: ComparisonSide
    right: ComparisonSide

    left_evaluation_ready: bool
    right_evaluation_ready: bool

    alignment_fingerprint: str
    pair_manifest_hash: str
    pairs: Mapping[Any, Any]


def _load_side(
    workspace: Path, side: _SideConfig, *, stage_finalization: str | None
) -> ComparisonSide:
    from fpbench.storage.decision_set_store import DecisionSetStore
    from fpbench.storage.eligibility_set_store import EligibilitySetStore
    from fpbench.storage.metric_set_store import MetricSetStore
    from fpbench.storage.result_set_store import ResultSetStore
    from fpbench.storage.result_store import ResultStore

    run = ResultStore(workspace).read_run(side.run_id)
    result_set = ResultSetStore(workspace).read_manifest(side.run_id)
    if result_set.result_set_id != side.result_set_id:
        raise CrossAlgorithmError(
            f"run {side.run_id} holds result set {result_set.result_set_id}, but "
            f"this comparison names {side.result_set_id}"
        )
    profile, decision_manifest, decisions = DecisionSetStore(
        workspace
    ).read_decision_set(side.run_id, side.decision_set_id)
    eligibility_manifest, eligibility_records = EligibilitySetStore(
        workspace
    ).read_eligibility_set(side.run_id, side.decision_set_id)
    if eligibility_manifest.eligibility_set_id != side.eligibility_set_id:
        raise CrossAlgorithmError(
            f"decision set {side.decision_set_id} carries eligibility set "
            f"{eligibility_manifest.eligibility_set_id}, but this comparison names "
            f"{side.eligibility_set_id}"
        )
    metric_manifest = MetricSetStore(workspace).read_manifest(
        side.run_id, side.metric_set_id
    )
    if metric_manifest.decision_set_id != side.decision_set_id:
        raise CrossAlgorithmError(
            f"metric set {side.metric_set_id} counts decision set "
            f"{metric_manifest.decision_set_id}, not {side.decision_set_id}"
        )
    return ComparisonSide(
        label=side.label,
        run=run,
        result_set=result_set,
        decision_profile=profile,
        decision_manifest=decision_manifest,
        decisions=tuple(decisions),
        eligibility_manifest=eligibility_manifest,
        eligibility_records=tuple(eligibility_records),
        metric_manifest=metric_manifest,
        stage_finalization_fingerprint=stage_finalization,
    )


def prepare_comparison(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    config: ComparisonExperimentConfig | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    permissive_provenance: bool = False,
) -> PreparedComparison:
    """Load both chains, re-derive the alignment, and build the fairness audit.

    Compares nothing. A failure here means the comparison must not be built, and
    saying so before any table exists is the whole point of a separate command.
    """
    workspace = Path(workspace)
    repository_root = Path(repository_root)
    config = config or load_comparison_config(repository_root=repository_root)
    software = _capture_provenance(repository_root, permissive=permissive_provenance)

    protocol = load_fair_measurement_protocol(config.protocol_config)
    policy = load_comparison_policy(config.policy_config)
    if policy.policy_fingerprint != protocol.comparison_policy_fingerprint:
        raise CrossAlgorithmError(
            "the comparison policy on disk is not the one the frozen protocol "
            "names; a policy edited after the methodology was committed does not "
            "govern this comparison"
        )
    if config.alignment_fingerprint != protocol.alignment_fingerprint:
        raise CrossAlgorithmError(
            "the comparison config and the frozen protocol name different "
            "alignments"
        )

    left_ready = _left_evaluation_ready(
        workspace=workspace, repository_root=repository_root
    )
    right_ready = _right_evaluation_ready(
        workspace=workspace, repository_root=repository_root
    )

    stage_finalization, alignment = _stage_7c(
        workspace=workspace,
        repository_root=repository_root,
        run_id=config.right.run_id,
    )

    left = _load_side(workspace, config.left, stage_finalization=None)
    right = _load_side(
        workspace, config.right, stage_finalization=stage_finalization
    )

    audit = build_fair_comparability_audit(
        protocol=protocol,
        left=left,
        right=right,
        alignment_fingerprint=alignment.alignment_fingerprint,
        alignment_is_clean=alignment.is_clean,
        alignment_equal_pair_ids=alignment.equal_pair_ids,
        alignment_equal_pair_semantics=alignment.equal_pair_semantics,
        alignment_equal_prepared_entries=alignment.equal_prepared_entries,
        expected_pairs=EXPECTED_JOBS,
        expected_prepared_entries=alignment.expectations.prepared_entry_count,
    )

    pairs, pair_manifest_hash = _pairs(workspace, left.run)
    definition = _build_definition(
        protocol=protocol,
        left=left,
        right=right,
        pair_manifest_hash=pair_manifest_hash,
        software=software,
    )
    return PreparedComparison(
        config=config,
        software=software,
        workspace=workspace,
        protocol=protocol,
        policy=policy,
        audit=audit,
        definition=definition,
        left=left,
        right=right,
        left_evaluation_ready=left_ready,
        right_evaluation_ready=right_ready,
        alignment_fingerprint=alignment.alignment_fingerprint,
        pair_manifest_hash=pair_manifest_hash,
        pairs=pairs,
    )


def _build_definition(
    *,
    protocol: Any,
    left: ComparisonSide,
    right: ComparisonSide,
    pair_manifest_hash: str,
    software: SoftwareProvenance,
) -> CrossAlgorithmEvaluationDefinition:
    claims = {
        "protocol_id": protocol.protocol_id,
        "protocol_fingerprint": protocol.protocol_fingerprint,
        "left_label": left.label,
        "left_run_id": left.run.run_id,
        "left_run_fingerprint": left.run.run_fingerprint,
        "left_result_set_fingerprint": left.result_set.result_set_fingerprint,
        "left_decision_set_id": left.decision_manifest.decision_set_id,
        "left_decision_set_fingerprint": (
            left.decision_manifest.decision_set_fingerprint
        ),
        "left_eligibility_set_id": left.eligibility_manifest.eligibility_set_id,
        "left_eligibility_set_fingerprint": (
            left.eligibility_manifest.eligibility_set_fingerprint
        ),
        "left_metric_set_id": left.metric_manifest.metric_set_id,
        "left_metric_set_fingerprint": left.metric_manifest.metric_set_fingerprint,
        "left_decision_profile_fingerprint": left.decision_profile.profile_fingerprint,
        "right_label": right.label,
        "right_run_id": right.run.run_id,
        "right_run_fingerprint": right.run.run_fingerprint,
        "right_result_set_fingerprint": right.result_set.result_set_fingerprint,
        "right_decision_set_id": right.decision_manifest.decision_set_id,
        "right_decision_set_fingerprint": (
            right.decision_manifest.decision_set_fingerprint
        ),
        "right_eligibility_set_id": right.eligibility_manifest.eligibility_set_id,
        "right_eligibility_set_fingerprint": (
            right.eligibility_manifest.eligibility_set_fingerprint
        ),
        "right_metric_set_id": right.metric_manifest.metric_set_id,
        "right_metric_set_fingerprint": right.metric_manifest.metric_set_fingerprint,
        "right_decision_profile_fingerprint": (
            right.decision_profile.profile_fingerprint
        ),
        "alignment_fingerprint": protocol.alignment_fingerprint,
        "pair_manifest_hash": pair_manifest_hash,
        "preparation_set_fingerprint": protocol.preparation_set_fingerprint,
        "eligibility_policy_id": protocol.eligibility_policy_id,
        "eligibility_policy_version": protocol.eligibility_policy_version,
        "metric_policy_fingerprint": protocol.metric_policy_fingerprint,
        "comparison_policy_fingerprint": protocol.comparison_policy_fingerprint,
        "comparison_software_fingerprint": software_provenance_fingerprint(software),
        "comparison_source_commit": software.source_revision,
    }
    fingerprint = cross_algorithm_definition_fingerprint(claims)
    return CrossAlgorithmEvaluationDefinition(
        **claims,
        definition_id=f"algcomparedef_{fingerprint[:12]}",
        definition_fingerprint=fingerprint,
        created_utc=_utc_now(),
    )


# ------------------------------------------------------------------- derive


def derive_comparison(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    config: ComparisonExperimentConfig | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    prepared: PreparedComparison | None = None,
) -> tuple[PreparedComparison, Any, str]:
    """Build the paired records, the transitions, the counts and the report.

    Returns:
        The prepared comparison, its derivation, and the rendered Markdown.
    """
    prepared = prepared or prepare_comparison(
        workspace=workspace, config=config, repository_root=repository_root
    )
    if not (prepared.left_evaluation_ready and prepared.right_evaluation_ready):
        raise CrossAlgorithmError(
            "both chains must be EVALUATION_READY before they can be compared"
        )
    require_clean_audit(prepared.audit)

    records = build_comparison_records(
        left=prepared.left, right=prepared.right, pairs=prepared.pairs
    )
    derivation = derive_cross_algorithm_evaluation(
        definition_fingerprint=prepared.definition.definition_fingerprint,
        audit_fingerprint=prepared.audit.audit_fingerprint,
        left=prepared.left,
        right=prepared.right,
        records=records,
        releases=_RELEASES,
    )
    verify_derivation(derivation=derivation, manifest=derivation.manifest)
    markdown = render_report(
        definition=prepared.definition,
        manifest=derivation.manifest,
        audit=prepared.audit,
        observations=derivation.observations,
        counts=derivation.counts,
        transitions=derivation.transitions,
        common_eligible=derivation.common_eligible,
        releases=_RELEASES,
    )
    return prepared, derivation, markdown


# ------------------------------------------------------------------- status


def inspect_comparison(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    config: ComparisonExperimentConfig | None = None,
    repository_root: Path = REPOSITORY_ROOT,
) -> Any:
    """Re-derive everything and compare it with what was published."""
    prepared = prepare_comparison(
        workspace=workspace,
        config=config,
        repository_root=repository_root,
        permissive_provenance=True,
    )
    prepared, derivation, markdown = derive_comparison(
        workspace=workspace,
        config=config,
        repository_root=repository_root,
        prepared=prepared,
    )
    directory = Path(repository_root) / EVIDENCE_DIRECTORY
    published_receipt, published_marker, published_report = _read_published(
        directory, derivation.manifest.evaluation_id
    )
    return inspect_cross_algorithm_evaluation(
        protocol=prepared.protocol,
        definition=prepared.definition,
        audit=prepared.audit,
        derivation=derivation,
        left=prepared.left,
        right=prepared.right,
        left_evaluation_ready=prepared.left_evaluation_ready,
        right_evaluation_ready=prepared.right_evaluation_ready,
        stored_manifest=derivation.manifest if published_receipt else None,
        stored_receipt=published_receipt,
        stored_marker=published_marker,
        stored_report=published_report,
        report_content_hash=report_content_hash(markdown),
        expected_records=EXPECTED_JOBS,
        expected_transitions=EXPECTED_PER_STAGE,
    )


# ----------------------------------------------------------------- finalize


def finalize_comparison(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    config: ComparisonExperimentConfig | None = None,
    repository_root: Path = REPOSITORY_ROOT,
) -> str:
    """Re-verify everything, then publish the audit, the comparison and the marker.

    Order, and it is the point: sources, alignment, audit, records, aggregates,
    report, receipt, marker. A failure before the marker leaves the earlier files
    in place and retryable, and the comparison is simply not authoritative yet.
    """
    repository_root = Path(repository_root)
    prepared, derivation, markdown = derive_comparison(
        workspace=workspace, config=config, repository_root=repository_root
    )
    if not prepared.software.is_research_grade:
        raise CrossAlgorithmError(
            "publishing a comparison needs a committed, clean source revision"
        )

    content_hash = report_content_hash(markdown)
    receipt = build_cross_algorithm_receipt(
        protocol=prepared.protocol,
        definition=prepared.definition,
        manifest=derivation.manifest,
        audit=prepared.audit,
        left=prepared.left,
        right=prepared.right,
        report_content_hash=content_hash,
        comparison_software=prepared.software,
    )
    marker = build_cross_algorithm_finalization(
        receipt=receipt,
        manifest=derivation.manifest,
        protocol=prepared.protocol,
        audit=prepared.audit,
        report_content_hash=content_hash,
        comparison_software=prepared.software,
    )

    directory = repository_root / EVIDENCE_DIRECTORY
    evaluation_id = derivation.manifest.evaluation_id
    write_evidence(directory / AUDIT_EVIDENCE_NAME, prepared.audit)
    write_evidence(
        directory / f"{evaluation_id}.json",
        {
            "receipt": to_plain(receipt),
            "definition": to_plain(prepared.definition),
            "manifest": to_plain(derivation.manifest),
            "observations": to_plain(derivation.observations),
            "counts": to_plain(derivation.counts),
        },
    )
    write_evidence(directory / f"{evaluation_id}.md", markdown, is_markdown=True)
    write_evidence(directory / FINALIZATION_EVIDENCE_NAME, marker)
    return evaluation_id


def read_verified_comparison_report(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    config: ComparisonExperimentConfig | None = None,
    repository_root: Path = REPOSITORY_ROOT,
) -> str:
    """Return the report, but only from a comparison that is fully verified."""
    state = inspect_comparison(
        workspace=workspace, config=config, repository_root=repository_root
    )
    if not state.is_cross_algorithm_ready:
        raise CrossAlgorithmError(
            f"this comparison is {state.status.value}, not cross_algorithm_ready; "
            f"there is no verified report to show {list(state.issues)[:3]}"
        )
    path = (
        Path(repository_root)
        / EVIDENCE_DIRECTORY
        / f"{state.evaluation_id}.md"
    )
    return path.read_text(encoding="utf-8")


# ----------------------------------------------------------------- internals


def _read_published(directory: Path, evaluation_id: str):
    from fpbench.core.cross_algorithm_models import (
        CrossAlgorithmEvaluationReceipt,
        CrossAlgorithmFinalization,
    )
    from fpbench.core.serialization import read_json

    receipt = marker = report = None
    bundle_path = directory / f"{evaluation_id}.json"
    if bundle_path.is_file():
        payload = read_json(bundle_path)
        receipt = CrossAlgorithmEvaluationReceipt(**payload["receipt"])
    marker_path = directory / FINALIZATION_EVIDENCE_NAME
    if marker_path.is_file():
        marker = CrossAlgorithmFinalization(**read_json(marker_path))
    report_path = directory / f"{evaluation_id}.md"
    if report_path.is_file():
        report = report_path.read_text(encoding="utf-8")
    return receipt, marker, report


def _left_evaluation_ready(*, workspace: Path, repository_root: Path) -> bool:
    from fpbench.experiments.sourceafis_canonical500_evaluation import (
        inspect_canonical_evaluation,
    )

    return inspect_canonical_evaluation(
        workspace=workspace, repository_root=repository_root
    ).is_evaluation_ready


def _right_evaluation_ready(*, workspace: Path, repository_root: Path) -> bool:
    from fpbench.experiments.nbis_canonical500_evaluation import (
        inspect_nbis_evaluation,
    )

    return inspect_nbis_evaluation(
        workspace=workspace, repository_root=repository_root
    ).is_evaluation_ready


def _stage_7c(*, workspace: Path, repository_root: Path, run_id: str):
    """Re-derive Stage 7C's alignment and read back its marker."""
    from fpbench.core.serialization import read_json
    from fpbench.experiments.nbis_canonical500_full import (
        STAGE_7C_FINALIZATION_NAME,
        verify_nbis_canonical500_alignment,
    )
    from fpbench.storage.result_store import ResultStore

    alignment = verify_nbis_canonical500_alignment(
        workspace=workspace,
        repository_root=repository_root,
        run_id=run_id,
        require_clean=False,
    )
    path = ResultStore(workspace).derived_path(run_id, STAGE_7C_FINALIZATION_NAME)
    if not path.is_file():
        raise CrossAlgorithmError(
            f"run {run_id} carries no Stage 7C finalization marker"
        )
    return str(read_json(path)["stage_7c_finalization_fingerprint"]), alignment


def _pairs(workspace: Path, run: Any):
    from fpbench.storage.manifest_store import ManifestStore

    manifests = ManifestStore(Path(workspace))
    protocol_id = run.protocol_id
    cohort_id = str(run.cohort_id)
    pairs = {pair.pair_id: pair for pair in manifests.read_pairs(protocol_id, cohort_id)}
    metadata = manifests.pair_manifest_metadata(protocol_id, cohort_id)
    return pairs, metadata["pair_manifest_hash"]


def _capture_provenance(
    repository_root: Path, *, permissive: bool
) -> SoftwareProvenance:
    from fpbench.provenance.software import capture_software_provenance

    return capture_software_provenance(
        repository_root=Path(repository_root), require_clean=not permissive
    )


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


# --------------------------------------------------------------------- CLI


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m fpbench.experiments.sourceafis_vs_nbis_canonical500",
        description=(
            "Compare the finished SourceAFIS and NBIS chains over the same 6,000 "
            "comparisons, at their independently documented operating points. "
            "Compares no raw score, equates no threshold and concludes nothing."
        ),
    )
    parser.add_argument(
        "command", choices=("prepare", "derive", "status", "finalize", "show")
    )
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument("--config", type=Path, default=DEFAULT_COMPARISON_CONFIG)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(list(argv) if argv is not None else None)
    try:
        config = load_comparison_config(arguments.config)
        shared = {"workspace": arguments.workspace, "config": config}

        if arguments.command == "prepare":
            prepared = prepare_comparison(**shared)
            print(f"protocol     {prepared.protocol.protocol_id}")
            print(f"policy       {prepared.policy.policy_id}")
            print(f"left         {prepared.left.label} "
                  f"{prepared.left.decision_manifest.decision_set_id}")
            print(f"right        {prepared.right.label} "
                  f"{prepared.right.decision_manifest.decision_set_id}")
            print(f"alignment    {prepared.alignment_fingerprint[:12]}...")
            print(f"audit        "
                  f"{'clean' if prepared.audit.is_clean else list(prepared.audit.failures)}")
            print(f"definition   {prepared.definition.definition_id}")
            return 0

        if arguments.command == "derive":
            _, derivation, _ = derive_comparison(**shared)
            print(f"comparison   {derivation.manifest.evaluation_id}")
            print(f"records      {derivation.manifest.total_records}")
            print(f"transitions  {derivation.manifest.total_transitions}")
            print(f"common       {derivation.manifest.total_common_eligible}")
            print(f"observations {derivation.manifest.total_observations}")
            print("next         finalize")
            return 0

        if arguments.command == "status":
            state = inspect_comparison(**shared)
            print(f"comparison   {state.evaluation_id or '-'}")
            print(f"status       {state.status.value}")
            print(f"audit        {'clean' if state.audit_clean else 'not clean'}")
            print(f"records      {state.total_records}")
            print(f"transitions  {state.total_transitions}")
            print(f"common       {state.total_common_eligible}")
            print(f"observations {state.total_observations}")
            for issue in state.issues:
                print(f"  issue      {issue}")
            return 0

        if arguments.command == "finalize":
            evaluation_id = finalize_comparison(**shared)
            print(f"comparison   {evaluation_id}")
            print(
                f"evidence     evidence/sourceafis-vs-nbis-canonical500/"
                f"{evaluation_id}.md"
            )
            return 0

        print(read_verified_comparison_report(**shared))
        return 0
    except (
        PreflightError,
        ConfigurationError,
        DerivationError,
        CrossAlgorithmError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
