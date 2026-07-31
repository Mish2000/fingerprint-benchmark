"""The 6,000-comparison SourceAFIS run at native resolution, in four commands.

    python -m fpbench.experiments.sourceafis_native_full prepare
    python -m fpbench.experiments.sourceafis_native_full execute [--max-new-jobs N]
    python -m fpbench.experiments.sourceafis_native_full status
    python -m fpbench.experiments.sourceafis_native_full finalize

They are separate commands because they answer to different failures. ``prepare``
is where a dirty working tree, an unverified dataset or a missing jar stops
everything, before a single JVM starts. ``execute`` can be run as many times as
it takes — a hundred jobs before lunch, the rest overnight — and each invocation
revalidates the pinned runtime on the way in and on the way out. ``finalize`` is
the only command that writes a completion, a result set or a receipt, and it
does so only after re-checking every link in the chain (docs/adr/0020).

Since stage 6A the orchestration lives in
:mod:`fpbench.experiments.sourceafis_research`, shared with the canonical run.
This module is what that shared implementation is given: the identity preparer,
the ``native_identity_60s_v1`` execution profile, and no preparation set. The
extraction was deliberate — the argument of stage 6A is that the native and
canonical runs differ in exactly one thing, and two copies of the orchestration
would be two chances for the difference to be something else.

Nothing about this experiment's identity changed when the code moved. Same
execution profile, same preparer id, same descriptor, same 6,000 pairs,
therefore the same ``run_fingerprint`` — ``run_7ac1cecc0bb3`` and its stored
results are untouched (spec section 61).
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from fpbench.core.errors import ConfigurationError, ResearchPreflightError
from fpbench.core.execution_models import ExecutionProfile
from fpbench.core.research_models import ResearchRunReceipt, ResearchRunState
from fpbench.execution.batch_runner import RunExecutionSummary
from fpbench.experiments.research_receipt import EVIDENCE_DIRECTORY
from fpbench.experiments.sd300_inputs import (
    EXPECTED_JOBS,
    EXPECTED_PARTICIPATING_IMAGES,
    EXPECTED_PER_RELEASE,
    EXPECTED_PER_STAGE,
    EXPECTED_RELEASES,
    EXPECTED_SUBJECTS,
)
from fpbench.experiments.sourceafis_research import (
    PreparedResearchRun,
    ResearchExperimentSpec,
    capture_research_provenance,
    execute_research_run,
    finalize_research_run,
    inspect_research_experiment,
    prepare_research_run,
)
from fpbench.imaging.identity import IdentityImagePreparer

__all__ = [
    "ExperimentConfig",
    "PreparedResearchRun",
    "load_experiment_config",
    "prepare_sourceafis_native_run",
    "execute_sourceafis_native_run",
    "inspect_sourceafis_native_run",
    "finalize_sourceafis_native_run",
    "capture_research_provenance",
    "EXPECTED_JOBS",
    "EXPECTED_PER_STAGE",
    "EXPECTED_PER_RELEASE",
    "EXPECTED_SUBJECTS",
    "main",
]

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_EXPERIMENT_CONFIG = (
    REPOSITORY_ROOT / "configs" / "experiments" / "sourceafis_native_full_v1.yaml"
)
DEFAULT_WORKSPACE = REPOSITORY_ROOT / "workspace"


# ------------------------------------------------------------------- config


@dataclass(frozen=True, slots=True)
class ExperimentConfig:
    """The pinned description of this experiment, read from YAML."""

    experiment_id: str
    kind: str
    replicate_index: int

    dataset_config: Path
    protocol_config: Path
    algorithm_config: Path

    require_verified_checksums: bool
    research_mode: bool
    materialization_policy: str

    execution_profile: ExecutionProfile

    def to_spec(self) -> ResearchExperimentSpec:
        """The shared orchestration's view of this experiment."""
        return ResearchExperimentSpec(
            experiment_id=self.experiment_id,
            kind=self.kind,
            replicate_index=self.replicate_index,
            dataset_config=self.dataset_config,
            protocol_config=self.protocol_config,
            algorithm_config=self.algorithm_config,
            require_verified_checksums=self.require_verified_checksums,
            research_mode=self.research_mode,
            materialization_policy=self.materialization_policy,
            execution_profile=self.execution_profile,
            expected_jobs=EXPECTED_JOBS,
            expected_per_release=EXPECTED_PER_RELEASE,
            expected_per_stage=EXPECTED_PER_STAGE,
            expected_releases=EXPECTED_RELEASES,
            expected_subjects=EXPECTED_SUBJECTS,
            expected_participating_images=EXPECTED_PARTICIPATING_IMAGES,
            evidence_directory=EVIDENCE_DIRECTORY,
        )


def load_experiment_config(
    path: Path = DEFAULT_EXPERIMENT_CONFIG,
    *,
    repository_root: Path = REPOSITORY_ROOT,
) -> ExperimentConfig:
    """Read ``configs/experiments/<name>.yaml``."""
    path = Path(path)
    if not path.is_file():
        raise ConfigurationError(f"experiment config not found: {path}")
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(document, Mapping):
        raise ConfigurationError(f"{path}: expected a mapping at the top level")

    experiment = _section(document, "experiment", path)
    dataset = _section(document, "dataset", path)
    protocol = _section(document, "protocol", path)
    algorithm = _section(document, "algorithm", path)
    execution = _section(document, "execution", path)
    runtime = _section(document, "runtime", path)

    decisions = document.get("decisions") or {}
    if decisions.get("profiles"):
        raise ConfigurationError(
            f"{path}: stage 4B applies no threshold and defines no decision "
            "profile; remove decisions.profiles (docs/adr/0003)"
        )
    reporting = document.get("reporting") or {}
    if reporting.get("biometric_metrics"):
        raise ConfigurationError(
            f"{path}: reporting.biometric_metrics must be false; no accuracy claim "
            "may rest on this stage"
        )

    root = Path(repository_root)
    return ExperimentConfig(
        experiment_id=str(experiment["id"]),
        kind=str(experiment.get("kind", "full_raw_score_run")),
        replicate_index=int(experiment.get("replicate_index", 0)),
        dataset_config=(root / str(dataset["ref"])).resolve(),
        protocol_config=(root / str(protocol["ref"])).resolve(),
        algorithm_config=(root / str(algorithm["ref"])).resolve(),
        require_verified_checksums=bool(
            dataset.get("require_verified_checksums", True)
        ),
        research_mode=bool(runtime.get("research_mode", True)),
        materialization_policy=str(
            runtime.get("materialization_policy", "content_addressed_copy_v1")
        ),
        execution_profile=ExecutionProfile(
            profile_id=str(execution["profile_id"]),
            preparer_id=str(execution["preparer_id"]),
            timeout_seconds=float(execution["timeout_seconds"]),
            deterministic_seed=int(execution.get("deterministic_seed", 0)),
            parameters={
                str(k): str(v)
                for k, v in dict(execution.get("parameters") or {}).items()
            },
        ),
    )


def _section(document: Mapping[str, Any], key: str, path: Path) -> Mapping[str, Any]:
    value = document.get(key)
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"{path}: missing or malformed '{key}' section")
    return value


def _identity_preparer(workspace: Path, spec: ResearchExperimentSpec):
    """The native run's preparer: the dataset's own bytes, untouched."""
    return IdentityImagePreparer()


# ------------------------------------------------------------------ commands


def prepare_sourceafis_native_run(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    dataset_root: Path | None = None,
    config: ExperimentConfig | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    build_jar: Path | None = None,
) -> PreparedResearchRun:
    """Pin everything, check everything, and write the run, plan and binding."""
    config = config or load_experiment_config(repository_root=repository_root)
    return prepare_research_run(
        spec=config.to_spec(),
        preparer_factory=_identity_preparer,
        workspace=Path(workspace),
        dataset_root=dataset_root,
        repository_root=repository_root,
        build_jar=build_jar,
    )


def execute_sourceafis_native_run(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    dataset_root: Path | None = None,
    max_new_jobs: int | None = None,
    config: ExperimentConfig | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
) -> RunExecutionSummary:
    """Execute some or all of a prepared run, revalidating the runtime around it."""
    config = config or load_experiment_config(repository_root=repository_root)
    return execute_research_run(
        spec=config.to_spec(),
        preparer_factory=_identity_preparer,
        workspace=Path(workspace),
        dataset_root=dataset_root,
        repository_root=repository_root,
        run_id=run_id,
        max_new_jobs=max_new_jobs,
    )


def inspect_sourceafis_native_run(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    dataset_root: Path | None = None,
    config: ExperimentConfig | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
) -> ResearchRunState:
    """Report how far along the evidence chain the run is. Never writes."""
    config = config or load_experiment_config(repository_root=repository_root)
    return inspect_research_experiment(
        spec=config.to_spec(),
        preparer_factory=_identity_preparer,
        workspace=Path(workspace),
        dataset_root=dataset_root,
        repository_root=repository_root,
        run_id=run_id,
    )


def finalize_sourceafis_native_run(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    dataset_root: Path | None = None,
    config: ExperimentConfig | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
) -> ResearchRunReceipt:
    """Revalidate everything and publish one last immutable commit marker."""
    config = config or load_experiment_config(repository_root=repository_root)
    return finalize_research_run(
        spec=config.to_spec(),
        preparer_factory=_identity_preparer,
        workspace=Path(workspace),
        dataset_root=dataset_root,
        repository_root=repository_root,
        run_id=run_id,
    )


# --------------------------------------------------------------------- CLI


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m fpbench.experiments.sourceafis_native_full",
        description=(
            "The stage 4B SourceAFIS native full run. Produces raw scores and "
            "provenance; applies no threshold and makes no accuracy claim."
        ),
    )
    parser.add_argument(
        "command", choices=("prepare", "execute", "status", "finalize")
    )
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=None,
        help="Overrides FPBENCH_SD300_ROOT for this invocation.",
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_EXPERIMENT_CONFIG)
    parser.add_argument(
        "--max-new-jobs",
        type=int,
        default=None,
        help="Stop after this many new comparisons. Existing results are checked "
        "and skipped without counting against the budget.",
    )
    parser.add_argument("--run-id", default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(list(argv) if argv is not None else None)
    config = load_experiment_config(arguments.config)
    shared = {
        "workspace": arguments.workspace,
        "dataset_root": arguments.dataset_root,
        "config": config,
    }

    try:
        if arguments.command == "prepare":
            prepared = prepare_sourceafis_native_run(**shared)
            print(f"run          {prepared.run.run_id}")
            print(f"plan         {prepared.plan.plan_id} "
                  f"({prepared.plan.total_jobs} jobs)")
            print(f"runtime      {prepared.bundle.bundle_id}")
            print(f"source       {prepared.software.source_revision[:12]}")
            return 0

        if arguments.command == "execute":
            summary = execute_sourceafis_native_run(
                **shared,
                max_new_jobs=arguments.max_new_jobs,
                run_id=arguments.run_id,
            )
            print(f"run          {summary.run_id}")
            print(f"executed     {summary.newly_executed_jobs}")
            print(f"skipped      {summary.skipped_existing_jobs}")
            print(f"remaining    {summary.remaining_jobs} of {summary.planned_jobs}")
            print(f"completed    {summary.completed} (verified {summary.verified})")
            if summary.completed:
                print("next         finalize")
            return 0

        if arguments.command == "status":
            state = inspect_sourceafis_native_run(**shared, run_id=arguments.run_id)
            print(f"run          {state.run_id}")
            print(f"status       {state.status.value}")
            print(f"core state   {state.core_state.value}")
            print(f"results      {state.stored_results} of {state.planned_jobs} "
                  f"({state.missing_results} missing)")
            print(f"runtime      {'valid' if state.runtime_bundle_valid else 'no'}")
            print(f"result set   {'valid' if state.result_set_valid else 'no'}")
            print(f"receipt      {'valid' if state.receipt_valid else 'no'}")
            for issue in state.issues:
                print(f"  issue      {issue}")
            return 0

        receipt = finalize_sourceafis_native_run(**shared, run_id=arguments.run_id)
        print(f"run          {receipt.run_id}")
        print(f"result set   {receipt.result_set_id}")
        print(f"completion   {receipt.completion_id}")
        print(f"stored       {receipt.stored_results} results "
              f"({receipt.success_count} scored, "
              f"{receipt.algorithmic_failure_count} algorithmic failures)")
        print(f"receipt      evidence/sourceafis-native-full/{receipt.run_id}.json")
        print(receipt.statement)
        return 0
    except (ResearchPreflightError, ConfigurationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
