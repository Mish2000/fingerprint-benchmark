"""The same 6,000 comparisons, over canonical 500 ppi inputs.

    python -m fpbench.experiments.sourceafis_canonical500_full prepare
    python -m fpbench.experiments.sourceafis_canonical500_full execute [--max-new-jobs N]
    python -m fpbench.experiments.sourceafis_canonical500_full status
    python -m fpbench.experiments.sourceafis_canonical500_full finalize

Everything about this run is the native run — same cohort, same 6,000 pairs in
the same order, same probe/candidate direction, same SourceAFIS 3.18.1, same
unchanged adapter, same Java bridge, same 60-second timeout, sequential, no
retries. The orchestration is literally the same code, in
:mod:`fpbench.experiments.sourceafis_research`.

One thing differs: the file the adapter opens. Instead of the bytes NIST
delivered, it is an artefact from an immutable canonical set, materialised once
by :mod:`fpbench.imaging.canonical` and handed unchanged to every algorithm
evaluated under the same profile (docs/adr/0031, docs/adr/0033).

Consequences worth stating, because each is a thing this stage does *not* do:

* **The algorithm's identity does not change.** No adapter version bump, no
  bridge version bump, no descriptor change. Native and canonical differ in the
  execution profile fingerprint, the preparation set fingerprint and therefore
  the run fingerprint — nowhere else (spec section 66).
* **No score is read.** This module never opens the native run's results. The
  native run and result-set ids appear in the config as an anchor for stage 6B
  and are used by nothing here (spec section 4).
* **Nothing is concluded.** No threshold, no decision, no metric, no paired
  comparison, no statement about resolution. A canonical run reaching
  ``RESEARCH_READY`` means 6,000 scores exist and can be attributed. It does not
  mean they are better.

``preparation_ms`` on a canonical result measures an entry lookup, a
source-record check, a ``stat`` and an object construction — microseconds. The
resampling happened before the run and is reported separately, in the
preparation summary. Comparing it with the native run's ``preparation_ms`` is
meaningless in both directions (spec section 74).
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from fpbench.core.errors import (
    ConfigurationError,
    PreflightError,
    ResearchPreflightError,
)
from fpbench.core.execution_models import ExecutionProfile
from fpbench.core.research_models import ResearchRunReceipt, ResearchRunState
from fpbench.core.serialization import require_exact_int
from fpbench.execution.batch_runner import RunExecutionSummary
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
    execute_research_run,
    finalize_research_run,
    inspect_research_experiment,
    prepare_research_run,
)
from fpbench.imaging.canonical500 import Canonical500ImagePreparer
from fpbench.storage.prepared_image_set_store import PreparedImageSetStore

__all__ = [
    "CanonicalExperimentConfig",
    "load_canonical_experiment_config",
    "load_canonical_execution_profile",
    "canonical_preparer_factory",
    "prepare_sourceafis_canonical500_run",
    "execute_sourceafis_canonical500_run",
    "inspect_sourceafis_canonical500_run",
    "finalize_sourceafis_canonical500_run",
    "EXPERIMENT_ID",
    "EXECUTION_PROFILE_ID",
    "EVIDENCE_DIRECTORY",
    "main",
]

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]

EXPERIMENT_ID = "sourceafis_canonical500_full_v1"
EXECUTION_PROFILE_ID = "canonical_500_lanczos3_60s_v1"

DEFAULT_EXPERIMENT_CONFIG = (
    REPOSITORY_ROOT / "configs" / "experiments" / f"{EXPERIMENT_ID}.yaml"
)
DEFAULT_EXECUTION_PROFILE_CONFIG = (
    REPOSITORY_ROOT / "configs" / "execution" / f"{EXECUTION_PROFILE_ID}.yaml"
)
DEFAULT_WORKSPACE = REPOSITORY_ROOT / "workspace"

#: Where a committed copy of this run's receipt lives.
EVIDENCE_DIRECTORY = Path("evidence") / "sourceafis-canonical500-full"

#: What an unfilled config looks like. The preparation set's id cannot be known
#: until the last image has been materialised, so the two configs are written
#: with this marker and filled in afterwards — and a run refuses to start while
#: the marker is still there rather than inventing a set.
UNRESOLVED = "TO_BE_FILLED_AFTER_MATERIALISATION"


@dataclass(frozen=True, slots=True)
class CanonicalExperimentConfig:
    """The pinned description of the canonical run, read from two YAML files."""

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

    preparation_set_id: str
    preparation_set_fingerprint: str
    transform_profile_id: str
    transform_profile_fingerprint: str

    expected_jobs: int
    expected_per_release: int
    expected_per_stage: int
    expected_participating_images: int
    expected_source_ppi: Mapping[str, int]

    #: Recorded so stage 6B knows which native run to join against. Read by
    #: nothing in this module.
    native_run_id: str
    native_result_set_id: str

    def to_spec(self) -> ResearchExperimentSpec:
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
            expected_jobs=self.expected_jobs,
            expected_per_release=self.expected_per_release,
            expected_per_stage=self.expected_per_stage,
            expected_releases=EXPECTED_RELEASES,
            expected_subjects=EXPECTED_SUBJECTS,
            expected_participating_images=self.expected_participating_images,
            evidence_directory=EVIDENCE_DIRECTORY,
            preparation_set_id=self.preparation_set_id,
            preparation_set_fingerprint=self.preparation_set_fingerprint,
            transform_profile_id=self.transform_profile_id,
            transform_profile_fingerprint=self.transform_profile_fingerprint,
            expected_source_ppi=dict(self.expected_source_ppi),
        )


def load_canonical_execution_profile(
    path: Path = DEFAULT_EXECUTION_PROFILE_CONFIG,
) -> ExecutionProfile:
    """Read ``configs/execution/canonical_500_lanczos3_60s_v1.yaml``.

    Every value under ``parameters`` becomes a string, because that is what
    :class:`ExecutionProfile` holds and the profile hash is taken over exactly
    those strings. A number written as an integer in YAML and as a string in the
    next edit would otherwise be a different execution profile for no reason.
    """
    path = Path(path)
    if not path.is_file():
        raise ConfigurationError(f"execution profile config not found: {path}")
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(document, Mapping):
        raise ConfigurationError(f"{path}: expected a mapping at the top level")

    profile = _section(document, "profile", path)
    parameters = {
        str(key): str(value)
        for key, value in dict(document.get("parameters") or {}).items()
    }
    _require_resolved(parameters, path)

    return ExecutionProfile(
        profile_id=str(profile["profile_id"]),
        preparer_id=str(profile["preparer_id"]),
        timeout_seconds=float(profile["timeout_seconds"]),
        deterministic_seed=require_exact_int(
            profile.get("deterministic_seed", 0), "deterministic_seed"
        ),
        parameters=parameters,
    )


def load_canonical_experiment_config(
    path: Path = DEFAULT_EXPERIMENT_CONFIG,
    *,
    repository_root: Path = REPOSITORY_ROOT,
    execution_profile_config: Path | None = None,
) -> CanonicalExperimentConfig:
    """Read ``configs/experiments/sourceafis_canonical500_full_v1.yaml``."""
    path = Path(path)
    if not path.is_file():
        raise ConfigurationError(f"experiment config not found: {path}")
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(document, Mapping):
        raise ConfigurationError(f"{path}: expected a mapping at the top level")

    experiment = _section(document, "experiment", path)
    source = _section(document, "source", path)
    algorithm = _section(document, "algorithm", path)
    execution = _section(document, "execution", path)
    runtime = document.get("runtime") or {}
    shape = _section(document, "expected_shape", path)
    anchor = _section(document, "comparison_anchor", path)

    if document.get("decisions") or document.get("thresholds"):
        raise ConfigurationError(
            f"{path}: stage 6A applies no threshold and defines no decision profile"
        )
    reporting = document.get("reporting") or {}
    if reporting.get("biometric_metrics"):
        raise ConfigurationError(
            f"{path}: reporting.biometric_metrics must be false; no accuracy claim "
            "may rest on this stage"
        )
    if anchor.get("paired_analysis_in_this_stage"):
        raise ConfigurationError(
            f"{path}: paired analysis belongs to stage 6B; this stage reads no "
            "native score"
        )
    if str(execution.get("execution_profile_id")) != EXECUTION_PROFILE_ID:
        raise ConfigurationError(
            f"{path}: execution.execution_profile_id must be "
            f"{EXECUTION_PROFILE_ID!r}"
        )
    if not execution.get("sequential", True):
        raise ConfigurationError(f"{path}: this run is sequential")
    if require_exact_int(execution.get("retries", 0), "retries") != 0:
        raise ConfigurationError(f"{path}: this run performs no retries")

    profile = load_canonical_execution_profile(
        execution_profile_config or DEFAULT_EXECUTION_PROFILE_CONFIG
    )
    declared = {
        "preparation_set_id": str(source["preparation_set_id"]),
        "preparation_set_fingerprint": str(source["preparation_set_fingerprint"]),
    }
    _require_resolved(declared, path)
    for key, value in declared.items():
        if profile.parameters.get(key) != value:
            raise ConfigurationError(
                f"{path}: the experiment names {key}={value[:16]}... but the "
                f"execution profile names {str(profile.parameters.get(key))[:16]}...; "
                "a run may not straddle two input sets"
            )

    root = Path(repository_root)
    dataset = _section(document, "dataset", path)
    protocol = _section(document, "protocol", path)
    return CanonicalExperimentConfig(
        experiment_id=str(experiment["id"]),
        kind=str(experiment.get("kind", "full_raw_score_run")),
        replicate_index=require_exact_int(
            experiment.get("replicate_index", 0), "replicate_index"
        ),
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
        execution_profile=profile,
        preparation_set_id=declared["preparation_set_id"],
        preparation_set_fingerprint=declared["preparation_set_fingerprint"],
        transform_profile_id=str(profile.parameters["transform_profile_id"]),
        transform_profile_fingerprint=str(
            profile.parameters["transform_profile_fingerprint"]
        ),
        expected_jobs=require_exact_int(
            shape.get("comparisons", EXPECTED_JOBS), "comparisons"
        ),
        expected_per_release=require_exact_int(
            shape.get("per_release", EXPECTED_PER_RELEASE), "per_release"
        ),
        expected_per_stage=require_exact_int(
            shape.get("per_stage", EXPECTED_PER_STAGE), "per_stage"
        ),
        expected_participating_images=require_exact_int(
            shape.get("participating_images", EXPECTED_PARTICIPATING_IMAGES),
            "participating_images",
        ),
        expected_source_ppi={
            str(key): require_exact_int(value, f"source_ppi[{key}]")
            for key, value in dict(shape.get("source_ppi") or {}).items()
        },
        native_run_id=str(anchor["native_run_id"]),
        native_result_set_id=str(anchor["native_result_set_id"]),
    )


def canonical_preparer_factory(
    workspace: Path, spec: ResearchExperimentSpec
) -> Canonical500ImagePreparer:
    """Bind a preparer to the exact set this run declares.

    There is no search for "the latest set". A run names one set by id and by
    fingerprint, and a preparer that went looking would silently switch inputs
    the next time somebody materialised a new one (spec section 55).
    """
    return Canonical500ImagePreparer(
        store=PreparedImageSetStore(Path(workspace)),
        preparation_set_id=str(spec.preparation_set_id),
        preparation_set_fingerprint=str(spec.preparation_set_fingerprint),
    )


# ------------------------------------------------------------------ commands


def prepare_sourceafis_canonical500_run(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    dataset_root: Path | None = None,
    config: CanonicalExperimentConfig | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    build_jar: Path | None = None,
) -> PreparedResearchRun:
    """Pin everything, prove the input set is ready, and write the run and plan.

    The preparation set must already be ``PREPARATION_READY``: verified, with a
    receipt and a finalization marker. A run over a half-materialised set would
    be a run whose inputs nobody had checked (spec section 71).
    """
    config = config or load_canonical_experiment_config(
        repository_root=repository_root
    )
    return prepare_research_run(
        spec=config.to_spec(),
        preparer_factory=canonical_preparer_factory,
        workspace=Path(workspace),
        dataset_root=dataset_root,
        repository_root=repository_root,
        build_jar=build_jar,
    )


def execute_sourceafis_canonical500_run(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    dataset_root: Path | None = None,
    max_new_jobs: int | None = None,
    config: CanonicalExperimentConfig | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
) -> RunExecutionSummary:
    """Execute some or all of a prepared canonical run."""
    config = config or load_canonical_experiment_config(
        repository_root=repository_root
    )
    return execute_research_run(
        spec=config.to_spec(),
        preparer_factory=canonical_preparer_factory,
        workspace=Path(workspace),
        dataset_root=dataset_root,
        repository_root=repository_root,
        run_id=run_id,
        max_new_jobs=max_new_jobs,
    )


def inspect_sourceafis_canonical500_run(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    dataset_root: Path | None = None,
    config: CanonicalExperimentConfig | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
) -> ResearchRunState:
    """Report how far along the evidence chain the run is. Never writes."""
    config = config or load_canonical_experiment_config(
        repository_root=repository_root
    )
    return inspect_research_experiment(
        spec=config.to_spec(),
        preparer_factory=canonical_preparer_factory,
        workspace=Path(workspace),
        dataset_root=dataset_root,
        repository_root=repository_root,
        run_id=run_id,
    )


def finalize_sourceafis_canonical500_run(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    dataset_root: Path | None = None,
    config: CanonicalExperimentConfig | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
) -> ResearchRunReceipt:
    """Revalidate everything and publish one last immutable commit marker."""
    config = config or load_canonical_experiment_config(
        repository_root=repository_root
    )
    return finalize_research_run(
        spec=config.to_spec(),
        preparer_factory=canonical_preparer_factory,
        workspace=Path(workspace),
        dataset_root=dataset_root,
        repository_root=repository_root,
        run_id=run_id,
    )


# ----------------------------------------------------------------- internals


def _section(document: Mapping[str, Any], key: str, path: Path) -> Mapping[str, Any]:
    value = document.get(key)
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"{path}: missing or malformed '{key}' section")
    return value


def _require_resolved(values: Mapping[str, str], path: Path) -> None:
    unresolved = sorted(
        key for key, value in values.items() if UNRESOLVED in str(value)
    )
    if unresolved:
        raise ConfigurationError(
            f"{path}: {', '.join(unresolved)} still holds the placeholder "
            f"{UNRESOLVED!r}. A prepared-image set's id is only known once every "
            "image has been materialised; run the preparation experiment, then "
            "write the exact id and fingerprint into this file"
        )


# --------------------------------------------------------------------- CLI


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m fpbench.experiments.sourceafis_canonical500_full",
        description=(
            "The stage 6A SourceAFIS run over canonical 500 ppi inputs. Produces "
            "raw scores and provenance; applies no threshold, computes no metric, "
            "reads no native score and concludes nothing about resolution."
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
    parser.add_argument(
        "--build-jar",
        type=Path,
        default=None,
        help="Materialise the runtime bundle from this jar instead of the build "
        "output. A Maven shaded jar is not byte-reproducible — rebuilding from "
        "identical source yields different bytes — so pointing this at the jar an "
        "earlier run pinned makes the two runs share one executable, and removes "
        "a variable from any later paired comparison.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(list(argv) if argv is not None else None)
    try:
        config = load_canonical_experiment_config(arguments.config)
    except ConfigurationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    shared = {
        "workspace": arguments.workspace,
        "dataset_root": arguments.dataset_root,
        "config": config,
    }

    try:
        if arguments.command == "prepare":
            prepared = prepare_sourceafis_canonical500_run(
                **shared, build_jar=arguments.build_jar
            )
            print(f"run          {prepared.run.run_id}")
            print(f"plan         {prepared.plan.plan_id} "
                  f"({prepared.plan.total_jobs} jobs)")
            print(f"runtime      {prepared.bundle.bundle_id}")
            print(f"input set    {config.preparation_set_id}")
            print(f"source       {prepared.software.source_revision[:12]}")
            return 0

        if arguments.command == "execute":
            summary = execute_sourceafis_canonical500_run(
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
            state = inspect_sourceafis_canonical500_run(
                **shared, run_id=arguments.run_id
            )
            print(f"run          {state.run_id}")
            print(f"status       {state.status.value}")
            print(f"core state   {state.core_state.value}")
            print(f"results      {state.stored_results} of {state.planned_jobs} "
                  f"({state.missing_results} missing)")
            print(f"input set    {config.preparation_set_id}")
            print(f"runtime      {'valid' if state.runtime_bundle_valid else 'no'}")
            print(f"result set   {'valid' if state.result_set_valid else 'no'}")
            print(f"receipt      {'valid' if state.receipt_valid else 'no'}")
            for issue in state.issues:
                print(f"  issue      {issue}")
            return 0

        receipt = finalize_sourceafis_canonical500_run(
            **shared, run_id=arguments.run_id
        )
        print(f"run          {receipt.run_id}")
        print(f"result set   {receipt.result_set_id}")
        print(f"completion   {receipt.completion_id}")
        print(f"stored       {receipt.stored_results} results "
              f"({receipt.success_count} scored, "
              f"{receipt.algorithmic_failure_count} algorithmic failures)")
        print(
            "receipt      evidence/sourceafis-canonical500-full/"
            f"{receipt.run_id}.json"
        )
        print(receipt.statement)
        return 0
    except (PreflightError, ConfigurationError) as exc:
        # ``PreflightError`` rather than only ``ResearchPreflightError``, which
        # is its subclass: a prepared-image set that will not verify is refused
        # by the *preparer*, and that raises the plain kind. Catching only the
        # subclass would turn the most likely operational failure of this
        # command into a traceback.
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
