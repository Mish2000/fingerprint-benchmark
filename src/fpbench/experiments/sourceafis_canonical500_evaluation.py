"""Counting the 6,000 canonical SourceAFIS decisions, in five commands.

    python -m fpbench.experiments.sourceafis_canonical500_evaluation prepare
    python -m fpbench.experiments.sourceafis_canonical500_evaluation derive
    python -m fpbench.experiments.sourceafis_canonical500_evaluation status
    python -m fpbench.experiments.sourceafis_canonical500_evaluation finalize
    python -m fpbench.experiments.sourceafis_canonical500_evaluation show

The canonical sibling of ``sourceafis_native_evaluation``, and a wrapper of the
same size: the arithmetic happens in
:mod:`fpbench.experiments.sourceafis_evaluation`, shared with the native
evaluation, under the identical metric policy.

**The metrics are not redefined because the input is canonical.** Same fourteen
metrics, same numerators, same denominators, same pooling rule. A metric whose
denominator changed with the input would make the two evaluations
incommensurable, which is the opposite of the point (spec section 22).

The report this produces stands alone. It says what the canonical run measured
and under which threshold, and it makes no comparison with the native run at
all — that comparison is a third artefact with its own identity, its own policy
and its own refusals (spec section 23).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from fpbench.core.errors import (
    ConfigurationError,
    DerivationError,
    MetricError,
    MetricPolicyError,
    PreflightError,
    StorageError,
)
from fpbench.core.evaluation_models import EvaluationState
from fpbench.experiments.sourceafis_canonical500_decisions import (
    load_canonical_decision_spec,
)
from fpbench.experiments.sourceafis_evaluation import (
    EvaluationExperimentConfig,
    PreparedEvaluation,
    SourceAfisEvaluationExperimentSpec,
    derive_metrics,
    finalize_evaluation,
    inspect_evaluation_experiment,
    prepare_evaluation,
    read_verified_report,
)
from fpbench.experiments.sourceafis_evaluation import (
    load_evaluation_config as _load_evaluation_config,
)

__all__ = [
    "EVIDENCE_DIRECTORY",
    "DEFAULT_EVALUATION_CONFIG",
    "load_evaluation_config",
    "canonical_evaluation_spec",
    "prepare_canonical_evaluation",
    "derive_canonical_metrics",
    "inspect_canonical_evaluation",
    "finalize_canonical_evaluation",
    "read_canonical_verified_report",
    "main",
]

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_WORKSPACE = REPOSITORY_ROOT / "workspace"
DEFAULT_EVALUATION_CONFIG = (
    REPOSITORY_ROOT
    / "configs"
    / "evaluations"
    / "sourceafis_canonical500_threshold40_v1.yaml"
)

#: One JSON and one Markdown file per canonical metric set.
EVIDENCE_DIRECTORY = Path("evidence") / "sourceafis-canonical500-evaluation"


def load_evaluation_config(
    path: Path = DEFAULT_EVALUATION_CONFIG,
    *,
    repository_root: Path = REPOSITORY_ROOT,
) -> EvaluationExperimentConfig:
    return _load_evaluation_config(path, repository_root=repository_root)


def canonical_evaluation_spec(
    *,
    evaluation_config: Path = DEFAULT_EVALUATION_CONFIG,
    repository_root: Path = REPOSITORY_ROOT,
) -> SourceAfisEvaluationExperimentSpec:
    """What the shared engine is given for the canonical evaluation."""
    return SourceAfisEvaluationExperimentSpec(
        evaluation_config=Path(evaluation_config),
        decision_spec=load_canonical_decision_spec(repository_root=repository_root),
        evidence_directory=EVIDENCE_DIRECTORY,
    )


# ------------------------------------------------------------------ commands


def prepare_canonical_evaluation(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    repository_root: Path = REPOSITORY_ROOT,
    require_expected_shape: bool = True,
    permissive_provenance: bool = False,
    evaluation_config: Path = DEFAULT_EVALUATION_CONFIG,
) -> PreparedEvaluation:
    return prepare_evaluation(
        spec=canonical_evaluation_spec(
            evaluation_config=evaluation_config, repository_root=repository_root
        ),
        workspace=Path(workspace),
        repository_root=repository_root,
        require_expected_shape=require_expected_shape,
        permissive_provenance=permissive_provenance,
    )


def derive_canonical_metrics(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    repository_root: Path = REPOSITORY_ROOT,
    require_expected_shape: bool = True,
    evaluation_config: Path = DEFAULT_EVALUATION_CONFIG,
) -> str:
    return derive_metrics(
        spec=canonical_evaluation_spec(
            evaluation_config=evaluation_config, repository_root=repository_root
        ),
        workspace=Path(workspace),
        repository_root=repository_root,
        require_expected_shape=require_expected_shape,
    )


def inspect_canonical_evaluation(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    repository_root: Path = REPOSITORY_ROOT,
    metric_set_id_override: str | None = None,
    evaluation_config: Path = DEFAULT_EVALUATION_CONFIG,
) -> EvaluationState:
    return inspect_evaluation_experiment(
        spec=canonical_evaluation_spec(
            evaluation_config=evaluation_config, repository_root=repository_root
        ),
        workspace=Path(workspace),
        repository_root=repository_root,
        metric_set_id_override=metric_set_id_override,
    )


def finalize_canonical_evaluation(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    repository_root: Path = REPOSITORY_ROOT,
    metric_set_id_override: str | None = None,
    evaluation_config: Path = DEFAULT_EVALUATION_CONFIG,
) -> str:
    return finalize_evaluation(
        spec=canonical_evaluation_spec(
            evaluation_config=evaluation_config, repository_root=repository_root
        ),
        workspace=Path(workspace),
        repository_root=repository_root,
        metric_set_id_override=metric_set_id_override,
    )


def read_canonical_verified_report(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    repository_root: Path = REPOSITORY_ROOT,
    metric_set_id_override: str | None = None,
    evaluation_config: Path = DEFAULT_EVALUATION_CONFIG,
) -> str:
    return read_verified_report(
        spec=canonical_evaluation_spec(
            evaluation_config=evaluation_config, repository_root=repository_root
        ),
        workspace=Path(workspace),
        repository_root=repository_root,
        metric_set_id_override=metric_set_id_override,
    )


# --------------------------------------------------------------------- CLI


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m fpbench.experiments.sourceafis_canonical500_evaluation",
        description=(
            "Count the finished canonical 500 ppi decision derivation under the "
            "same immutable metric policy the native evaluation used. Applies no "
            "threshold, redefines no denominator, and compares nothing with the "
            "native run."
        ),
    )
    parser.add_argument(
        "command", choices=("prepare", "derive", "status", "finalize", "show")
    )
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument("--config", type=Path, default=DEFAULT_EVALUATION_CONFIG)
    parser.add_argument("--metric-set-id", default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(list(argv) if argv is not None else None)
    try:
        shared = {
            "workspace": arguments.workspace,
            "evaluation_config": arguments.config,
        }

        if arguments.command == "prepare":
            prepared = prepare_canonical_evaluation(**shared)
            print(f"run          {prepared.run.run_id}")
            print(f"decision set {prepared.decision_manifest.decision_set_id}")
            print(f"eligibility  {prepared.eligibility_manifest.eligibility_set_id}")
            print(f"policy       {prepared.policy.policy_id} "
                  f"({len(prepared.policy.metric_definitions)} metrics)")
            print(f"profile      {prepared.report_profile.report_profile_id}")
            print(f"releases     {', '.join(prepared.releases)}")
            print(f"definition   {prepared.definition.definition_id}")
            return 0

        if arguments.command == "derive":
            set_id = derive_canonical_metrics(**shared)
            print(f"metric set   {set_id}")
            print("next         finalize")
            return 0

        if arguments.command == "status":
            state = inspect_canonical_evaluation(
                **shared, metric_set_id_override=arguments.metric_set_id
            )
            print(f"run          {state.run_id}")
            print(f"metric set   {state.metric_set_id or '-'}")
            print(f"status       {state.status.value}")
            print(f"source       "
                  f"{'decision_ready' if state.source_decision_ready else 'not ready'}")
            print(f"counts       {state.total_count_records} records "
                  f"{'valid' if state.counts_valid else 'unverified'}")
            print(f"observations {state.total_observations} "
                  f"{'valid' if state.observations_valid else 'unverified'}")
            print(f"summary      {'valid' if state.summary_valid else 'no'}")
            print(f"report       {'valid' if state.report_valid else 'no'}")
            print(f"receipt      {'valid' if state.receipt_valid else 'no'}")
            print(f"finalized    {'valid' if state.finalization_valid else 'no'}")
            for issue in state.issues:
                print(f"  issue      {issue}")
            return 0

        if arguments.command == "finalize":
            set_id = finalize_canonical_evaluation(
                **shared, metric_set_id_override=arguments.metric_set_id
            )
            print(f"metric set   {set_id}")
            print(
                f"evidence     evidence/sourceafis-canonical500-evaluation/"
                f"{set_id}.json"
            )
            print(
                f"             evidence/sourceafis-canonical500-evaluation/"
                f"{set_id}.md"
            )
            print("status       evaluation_ready")
            return 0

        print(
            read_canonical_verified_report(
                **shared, metric_set_id_override=arguments.metric_set_id
            )
        )
        return 0
    except (
        PreflightError,
        ConfigurationError,
        DerivationError,
        MetricError,
        MetricPolicyError,
        StorageError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
