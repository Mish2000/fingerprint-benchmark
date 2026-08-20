"""Counting the 6,000 NBIS decisions under the shared metric policy.

    python -m fpbench.experiments.nbis_canonical500_evaluation prepare
    python -m fpbench.experiments.nbis_canonical500_evaluation derive
    python -m fpbench.experiments.nbis_canonical500_evaluation status
    python -m fpbench.experiments.nbis_canonical500_evaluation finalize
    python -m fpbench.experiments.nbis_canonical500_evaluation show

The NBIS sibling of ``sourceafis_canonical500_evaluation``, and a wrapper of the
same size for the same reason: the counting happens in
:mod:`fpbench.experiments.algorithm_evaluation`, shared with both SourceAFIS
chains.

Three things differ from the SourceAFIS wrapper, and all three are data: which
evaluation config names the source, which decision spec sits beneath it, and
where the evidence copies go. The metric policy is *not* one of them — it is the
same file, cited by the same path, because the comparison at the end of stage 7D
depends on the fourteen metrics meaning exactly the same thing on both sides
(spec section 40).

**It applies no threshold.** The decisions arrived already made, from a profile
that reads NIST's documentation and no score at all.
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
    PreflightError,
)
from fpbench.core.evaluation_models import EvaluationState
from fpbench.core.serialization import to_plain
from fpbench.core.json_io import write_json
from fpbench.experiments.algorithm_evaluation import (
    AlgorithmEvaluationExperimentSpec,
    EvaluationExperimentConfig,
    PreparedEvaluation,
    derive_metrics,
    finalize_evaluation,
    inspect_evaluation_experiment,
    prepare_evaluation,
    read_verified_report,
)
from fpbench.experiments.algorithm_evaluation import (
    load_evaluation_config as _load_evaluation_config,
)
from fpbench.experiments.nbis_canonical500_decisions import load_nbis_decision_spec

__all__ = [
    "EXPERIMENT_ID",
    "EVIDENCE_DIRECTORY",
    "DEFAULT_EVALUATION_CONFIG",
    "load_evaluation_config",
    "nbis_evaluation_spec",
    "prepare_nbis_evaluation",
    "derive_nbis_metrics",
    "inspect_nbis_evaluation",
    "finalize_nbis_evaluation",
    "read_nbis_verified_report",
    "main",
]

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_WORKSPACE = REPOSITORY_ROOT / "workspace"

EXPERIMENT_ID = "nbis_canonical500_nistir7391_gt40_evaluation_v1"

DEFAULT_EVALUATION_CONFIG = (
    REPOSITORY_ROOT
    / "configs"
    / "evaluations"
    / "nbis_canonical500_nistir7391_gt40_v1.yaml"
)

#: Kept apart from the two SourceAFIS evaluation directories so that neither can
#: overwrite the other's evidence (spec section 69).
EVIDENCE_DIRECTORY = Path("evidence") / "nbis-canonical500-evaluation"

#: The marker copied out beside the metric set. The SourceAFIS evaluations
#: publish only the receipt and the report; this one publishes the finalization
#: marker as well, because the comparison downstream binds it by fingerprint and
#: a reader should be able to check that without a workspace.
FINALIZATION_EVIDENCE_NAME = "evaluation-finalization.json"


def load_evaluation_config(
    path: Path = DEFAULT_EVALUATION_CONFIG,
    *,
    repository_root: Path = REPOSITORY_ROOT,
) -> EvaluationExperimentConfig:
    return _load_evaluation_config(Path(path), repository_root=repository_root)


def nbis_evaluation_spec(
    *,
    evaluation_config: Path = DEFAULT_EVALUATION_CONFIG,
    repository_root: Path = REPOSITORY_ROOT,
) -> AlgorithmEvaluationExperimentSpec:
    return AlgorithmEvaluationExperimentSpec(
        evaluation_config=Path(evaluation_config),
        decision_spec=load_nbis_decision_spec(repository_root=repository_root),
        evidence_directory=EVIDENCE_DIRECTORY,
    )


# ------------------------------------------------------------------ commands


def prepare_nbis_evaluation(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    spec: AlgorithmEvaluationExperimentSpec | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    require_expected_shape: bool = True,
) -> PreparedEvaluation:
    return prepare_evaluation(
        spec=spec or nbis_evaluation_spec(repository_root=repository_root),
        workspace=Path(workspace),
        repository_root=repository_root,
        require_expected_shape=require_expected_shape,
    )


def derive_nbis_metrics(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    spec: AlgorithmEvaluationExperimentSpec | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    require_expected_shape: bool = True,
) -> str:
    return derive_metrics(
        spec=spec or nbis_evaluation_spec(repository_root=repository_root),
        workspace=Path(workspace),
        repository_root=repository_root,
        require_expected_shape=require_expected_shape,
    )


def inspect_nbis_evaluation(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    spec: AlgorithmEvaluationExperimentSpec | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    metric_set_id_override: str | None = None,
) -> EvaluationState:
    return inspect_evaluation_experiment(
        spec=spec or nbis_evaluation_spec(repository_root=repository_root),
        workspace=Path(workspace),
        repository_root=repository_root,
        metric_set_id_override=metric_set_id_override,
    )


def finalize_nbis_evaluation(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    spec: AlgorithmEvaluationExperimentSpec | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    metric_set_id_override: str | None = None,
) -> str:
    """Finalise, then publish the marker the comparison downstream will bind."""
    resolved = spec or nbis_evaluation_spec(repository_root=repository_root)
    workspace = Path(workspace)
    set_id = finalize_evaluation(
        spec=resolved,
        workspace=workspace,
        repository_root=repository_root,
        metric_set_id_override=metric_set_id_override,
    )
    config = load_evaluation_config(
        resolved.evaluation_config, repository_root=repository_root
    )
    from fpbench.storage.metric_set_store import MetricSetStore

    marker = MetricSetStore(workspace).read_finalization(config.run_id, set_id)
    write_json(
        Path(repository_root) / EVIDENCE_DIRECTORY / FINALIZATION_EVIDENCE_NAME,
        to_plain(marker),
    )
    return set_id


def read_nbis_verified_report(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    spec: AlgorithmEvaluationExperimentSpec | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    metric_set_id_override: str | None = None,
) -> str:
    return read_verified_report(
        spec=spec or nbis_evaluation_spec(repository_root=repository_root),
        workspace=Path(workspace),
        repository_root=repository_root,
        metric_set_id_override=metric_set_id_override,
    )


# --------------------------------------------------------------------- CLI


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m fpbench.experiments.nbis_canonical500_evaluation",
        description=(
            "Count the finished NBIS canonical 500 ppi decisions under the shared "
            "metric policy. Applies no threshold, calibrates nothing and makes no "
            "claim about the other algorithm."
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
        spec = nbis_evaluation_spec(evaluation_config=arguments.config)
        shared = {"workspace": arguments.workspace, "spec": spec}

        if arguments.command == "prepare":
            prepared = prepare_nbis_evaluation(**shared)
            print(f"run          {prepared.run.run_id}")
            print(f"decisions    {prepared.decision_manifest.decision_set_id}")
            print(f"policy       {prepared.policy.policy_id}")
            print(f"definition   {prepared.definition.definition_id}")
            print(f"releases     {', '.join(prepared.releases)}")
            return 0

        if arguments.command == "derive":
            set_id = derive_nbis_metrics(**shared)
            print(f"metric set   {set_id}")
            print("next         finalize")
            return 0

        if arguments.command == "status":
            state = inspect_nbis_evaluation(
                **shared, metric_set_id_override=arguments.metric_set_id
            )
            print(f"run          {state.run_id}")
            print(f"metric set   {state.metric_set_id or '-'}")
            print(f"status       {state.status.value}")
            for issue in state.issues:
                print(f"  issue      {issue}")
            return 0

        if arguments.command == "finalize":
            set_id = finalize_nbis_evaluation(
                **shared, metric_set_id_override=arguments.metric_set_id
            )
            print(f"metric set   {set_id}")
            print(
                f"evidence     evidence/nbis-canonical500-evaluation/{set_id}.json"
            )
            return 0

        print(
            read_nbis_verified_report(
                **shared, metric_set_id_override=arguments.metric_set_id
            )
        )
        return 0
    except (
        PreflightError,
        ConfigurationError,
        DerivationError,
        MetricError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
