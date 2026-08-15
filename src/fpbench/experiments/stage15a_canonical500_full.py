"""G5 — the 6,000 canonical comparisons, and the configuration that fixes them.

Stage 15A does not rehearse. The qualification ran on non-SD300 fixtures and
proved three things — the artifact is the published artifact, the route is
upstream's own, and the same input gives the same bits — and this module turns
that into the production execution directly. There is no SD300 pilot in front of
it, because a pilot over the evaluation set is an SD300 run that nobody counted.

What runs:

.. code-block:: text

    prepset_be560e047991                     the same 3,000 canonical 500 ppi PNGs
          |
          v
    fingerprints_matching_subprocess         one frozen interpreter, held open
          |
          v
    FingerprintsMatching                     .fingerprints_matching(left, right)
    .fingerprints_matching(image_path1, image_path2)
          |
          v
    6,000 stored raw outcomes                immutable, and never a threshold

Every comparison ends in exactly one of two states. A finite number is a
``RAW_SCORE``. Upstream raising while processing the prints is an
``ALGORITHMIC_FAILURE`` carrying no number. There is no third outcome: an
infrastructure failure is not recorded, it stops the run, because a benchmark
that stored "the machine broke" beside "these fingers do not match" would have
put the two in the same column.

The configuration below selects nothing. Every identifier in it names something
an earlier finalised stage produced, and preparation re-derives each one before a
run exists.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from fpbench.core.errors import ConfigurationError
from fpbench.core.execution_models import ExecutionProfile
from fpbench.core.research_models import ResearchReceipt, ResearchRunState
from fpbench.experiments import stage15a_identity as frozen
from fpbench.experiments import stage15a_runtime as runtime
from fpbench.experiments.algorithm_research import (
    REPOSITORY_ROOT,
    AlgorithmResearchExperimentSpec,
    PreparedAlgorithmResearchRun,
    RunExecutionSummary,
)
from fpbench.experiments.stage15a_research import (
    execute_fingerprints_matching_research_run,
    finalize_fingerprints_matching_research_run,
    inspect_fingerprints_matching_research_experiment,
    prepare_fingerprints_matching_research_run,
)
from fpbench.experiments.stage15a_validation import SD300_CANONICAL500_INPUT_SET
from fpbench.core.config_values import (
    require_yaml_exact_int,
    require_yaml_mapping,
    require_yaml_non_empty_str,
)
from fpbench.imaging.canonical500 import Canonical500ImagePreparer
from fpbench.storage.prepared_image_set_store import PreparedImageSetStore

__all__ = [
    "EXPERIMENT_CONFIG",
    "DEFAULT_WORKSPACE",
    "Stage15ACanonical500Config",
    "load_stage15a_canonical500_config",
    "build_stage15a_canonical500_spec",
    "preflight_stage15a_canonical500_run",
    "prepare_stage15a_canonical500_run",
    "execute_stage15a_canonical500_run",
    "inspect_stage15a_canonical500_experiment",
    "finalize_stage15a_canonical500_run",
    "main",
]

EXPERIMENT_CONFIG = (
    REPOSITORY_ROOT
    / "configs"
    / "experiments"
    / "fingerprints_matching_canonical500_full_v1.yaml"
)
DEFAULT_WORKSPACE = REPOSITORY_ROOT / "workspace"

_HEX = set("0123456789abcdef")


@dataclass(frozen=True, slots=True)
class Stage15ACanonical500Config:
    """The experiment document, parsed and checked against the frozen identity."""

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

    expected_jobs: int
    expected_per_release: int
    expected_per_stage: int
    expected_releases: tuple[str, ...]
    expected_subjects: int
    expected_participating_images: int
    expected_source_ppi: Mapping[str, int]

    preparation_set_id: str
    preparation_set_fingerprint: str
    transform_profile_id: str
    transform_profile_fingerprint: str
    transform_runtime_fingerprint: str

    reference_run_id: str
    reference_plan_id: str
    reference_result_set_id: str
    reference_cohort_id: str
    reference_pair_manifest_hash: str


def _require_frozen(label: str, value: Any, expected: Any, path: Path) -> None:
    if value != expected:
        raise ConfigurationError(
            f"{path}: {label} is {value!r}, and Stage 15A is frozen at {expected!r}"
        )


def _require_digest(value: str, label: str) -> str:
    digest = str(value).strip().lower()
    if len(digest) != 64 or not set(digest) <= _HEX:
        raise ConfigurationError(f"{label} must be a 64-character hexadecimal digest")
    return digest


def _require_no_decision_keys(document: Any, path: Path, trail: str = "") -> None:
    """Refuse a key that would make this a decision stage, at any depth."""
    if isinstance(document, Mapping):
        for key, value in document.items():
            name = str(key)
            if name.lower() in frozen.FORBIDDEN_CONFIG_KEYS:
                where = f"{trail}.{name}" if trail else name
                raise ConfigurationError(
                    f"{path}: {where} may not appear in a Stage 15A experiment. "
                    "This stage produces raw outcomes; thresholds, calibration "
                    "and metrics are later layers over these stored scores "
                    "(docs/adr/0003)"
                )
            _require_no_decision_keys(value, path, f"{trail}.{name}" if trail else name)
    elif isinstance(document, list):
        for index, item in enumerate(document):
            _require_no_decision_keys(item, path, f"{trail}[{index}]")


def _load_execution_profile(path: Path) -> ExecutionProfile:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(document, Mapping):
        raise ConfigurationError(f"{path}: expected a mapping at the top level")
    profile = require_yaml_mapping(document, "profile", where=path)
    parameters = document.get("parameters") or {}
    if not isinstance(parameters, Mapping):
        raise ConfigurationError(f"{path}: parameters must be a mapping")
    return ExecutionProfile(
        profile_id=require_yaml_non_empty_str(profile, "profile_id", where=path),
        preparer_id=require_yaml_non_empty_str(profile, "preparer_id", where=path),
        timeout_seconds=float(
            require_yaml_exact_int(profile, "timeout_seconds", where=path, minimum=1)
        ),
        deterministic_seed=require_yaml_exact_int(
            profile, "deterministic_seed", where=path, minimum=0
        ),
        parameters={str(key): str(value) for key, value in parameters.items()},
    )


def load_stage15a_canonical500_config(
    *,
    path: Path = EXPERIMENT_CONFIG,
    repository_root: Path = REPOSITORY_ROOT,
) -> Stage15ACanonical500Config:
    """Read the experiment document, and refuse it if it has drifted.

    The file restates every identity the code already freezes. Restating catches
    a typo; it does not stop somebody editing both the file and its own checks,
    which is why the comparison runs against
    :mod:`fpbench.experiments.stage15a_identity` rather than against the file
    itself (docs/adr/0031).
    """
    path = Path(path)
    if not path.is_file():
        raise ConfigurationError(f"experiment config not found: {path}")
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(document, Mapping):
        raise ConfigurationError(f"{path}: expected a mapping at the top level")

    # Everything except ``reporting``, whose keys are the *denials* — a document
    # that may not mention a threshold still has to be able to say it produces
    # no score statistic (spec section 33).
    _require_no_decision_keys(
        {key: value for key, value in document.items() if key != "reporting"}, path
    )

    _require_frozen(
        "experiment_id", document.get("experiment_id"), frozen.EXPERIMENT_ID, path
    )
    if document.get("kind") != "research":
        raise ConfigurationError(f"{path}: kind must be 'research'")
    if document.get("require_verified_checksums") is not True:
        raise ConfigurationError(
            f"{path}: require_verified_checksums must be true; the reference run "
            "required it and an aligned run may not require less"
        )

    artifact = require_yaml_mapping(document, "artifact", where=path)
    _require_frozen(
        "artifact.package",
        artifact.get("package"),
        frozen.PACKAGE_REQUIREMENT,
        path,
    )
    _require_frozen("artifact.license", artifact.get("license"), frozen.LICENSE, path)
    _require_frozen(
        "artifact.runtime_artifact_sha256",
        _require_digest(
            str(artifact.get("runtime_artifact_sha256", "")),
            "artifact.runtime_artifact_sha256",
        ),
        frozen.RUNTIME_ARTIFACT_SHA256,
        path,
    )
    _require_frozen(
        "artifact.source_artifact_sha256",
        _require_digest(
            str(artifact.get("source_artifact_sha256", "")),
            "artifact.source_artifact_sha256",
        ),
        frozen.SOURCE_ARTIFACT_SHA256,
        path,
    )
    _require_frozen(
        "artifact.algorithm_id",
        artifact.get("algorithm_id"),
        frozen.PRODUCTION_ALGORITHM_ID,
        path,
    )
    _require_frozen(
        "artifact.adapter_id", artifact.get("adapter_id"), frozen.ADAPTER_ID, path
    )

    runtime_document = require_yaml_mapping(document, "runtime", where=path)
    for key, expected in (
        ("python_version", frozen.PINNED_PYTHON_VERSION),
        ("numpy", frozen.PINNED_NUMPY),
        ("opencv_python", frozen.PINNED_OPENCV),
        ("cv2_library", frozen.PINNED_CV2_LIBRARY),
    ):
        _require_frozen(f"runtime.{key}", runtime_document.get(key), expected, path)
    if runtime_document.get("research_mode") is not True:
        raise ConfigurationError(f"{path}: runtime.research_mode must be true")

    reference = require_yaml_mapping(document, "reference", where=path)
    for key, expected in (
        ("run_id", frozen.REFERENCE_RUN_ID),
        ("plan_id", frozen.REFERENCE_PLAN_ID),
        ("result_set_id", frozen.REFERENCE_RESULT_SET_ID),
        ("cohort_id", frozen.REFERENCE_COHORT_ID),
        ("pair_manifest_hash", frozen.REFERENCE_PAIR_MANIFEST_HASH),
    ):
        _require_frozen(f"reference.{key}", reference.get(key), expected, path)

    preparation = require_yaml_mapping(document, "preparation", where=path)
    for key, expected in (
        ("set_id", frozen.PREPARATION_SET_ID),
        ("set_fingerprint", frozen.PREPARATION_SET_FINGERPRINT),
        ("transform_profile_id", frozen.TRANSFORM_PROFILE_ID),
        ("transform_profile_fingerprint", frozen.TRANSFORM_PROFILE_FINGERPRINT),
        ("transform_runtime_fingerprint", frozen.TRANSFORM_RUNTIME_FINGERPRINT),
    ):
        _require_frozen(f"preparation.{key}", preparation.get(key), expected, path)

    expected_document = require_yaml_mapping(document, "expected", where=path)
    for key, expected in (
        ("jobs", frozen.EXPECTED_JOBS),
        ("pairs_per_release", frozen.EXPECTED_PER_RELEASE),
        ("pairs_per_stage", frozen.EXPECTED_PER_STAGE),
        ("pairs_per_release_stage", frozen.EXPECTED_PER_RELEASE_STAGE),
        ("subjects", frozen.EXPECTED_SUBJECTS),
        ("participating_images", frozen.EXPECTED_PARTICIPATING_IMAGES),
    ):
        _require_frozen(f"expected.{key}", expected_document.get(key), expected, path)
    releases = tuple(str(r) for r in expected_document.get("releases", ()))
    _require_frozen("expected.releases", releases, frozen.EXPECTED_RELEASES, path)
    source_ppi = {
        str(k): int(v)
        for k, v in (expected_document.get("source_ppi") or {}).items()
    }
    _require_frozen(
        "expected.source_ppi", source_ppi, dict(frozen.EXPECTED_SOURCE_PPI), path
    )

    operations = require_yaml_mapping(document, "operations", where=path)
    for key, wanted in (
        ("comparisons_per_job", 1),
        ("logical_extractions_per_comparison", 2),
    ):
        if operations.get(key) != wanted:
            raise ConfigurationError(
                f"{path}: operations.{key} must be {wanted}; SELF counts as two "
                "extractions exactly like every other comparison "
                "(spec sections 14 and 27)"
            )
    if str(operations.get("template_cache")) != "none":
        raise ConfigurationError(
            f"{path}: operations.template_cache must be 'none'. The upstream "
            "entry point re-extracts both sides on every call, and a cache would "
            "make SELF a comparison of one feature set with itself"
        )

    execution = require_yaml_mapping(document, "execution", where=path)
    if execution.get("sequential") is not True:
        raise ConfigurationError(f"{path}: execution.sequential must be true")
    _require_frozen(
        "execution.max_workers", execution.get("max_workers"), frozen.MAX_WORKERS, path
    )
    _require_frozen(
        "execution.retries", execution.get("retries"), frozen.RETRIES, path
    )
    _require_frozen(
        "execution.job_deadline_seconds",
        execution.get("job_deadline_seconds"),
        frozen.JOB_DEADLINE_SECONDS,
        path,
    )

    reporting = require_yaml_mapping(document, "reporting", where=path)
    for key, wanted in sorted(frozen.REQUIRED_REPORTING_SWITCHES.items()):
        if reporting.get(key) is not wanted:
            raise ConfigurationError(
                f"{path}: reporting.{key} must be {str(wanted).lower()}, got "
                f"{reporting.get(key)!r}. Stage 15A publishes operational facts "
                "and no biometric metric"
            )

    root = Path(repository_root)
    profile_path = root / str(execution.get("profile_config"))
    profile = _load_execution_profile(profile_path)
    _require_frozen(
        "execution.profile_id",
        profile.profile_id,
        frozen.EXECUTION_PROFILE_ID,
        profile_path,
    )

    return Stage15ACanonical500Config(
        experiment_id=frozen.EXPERIMENT_ID,
        kind="research",
        replicate_index=int(document.get("replicate_index", 0)),
        dataset_config=root / str(document.get("dataset_config")),
        protocol_config=root / str(document.get("protocol_config")),
        algorithm_config=root / str(document.get("algorithm_config")),
        require_verified_checksums=True,
        research_mode=True,
        materialization_policy=str(runtime_document.get("materialization_policy")),
        execution_profile=profile,
        expected_jobs=frozen.EXPECTED_JOBS,
        expected_per_release=frozen.EXPECTED_PER_RELEASE,
        expected_per_stage=frozen.EXPECTED_PER_STAGE,
        expected_releases=frozen.EXPECTED_RELEASES,
        expected_subjects=frozen.EXPECTED_SUBJECTS,
        expected_participating_images=frozen.EXPECTED_PARTICIPATING_IMAGES,
        expected_source_ppi=dict(frozen.EXPECTED_SOURCE_PPI),
        preparation_set_id=frozen.PREPARATION_SET_ID,
        preparation_set_fingerprint=frozen.PREPARATION_SET_FINGERPRINT,
        transform_profile_id=frozen.TRANSFORM_PROFILE_ID,
        transform_profile_fingerprint=frozen.TRANSFORM_PROFILE_FINGERPRINT,
        transform_runtime_fingerprint=frozen.TRANSFORM_RUNTIME_FINGERPRINT,
        reference_run_id=frozen.REFERENCE_RUN_ID,
        reference_plan_id=frozen.REFERENCE_PLAN_ID,
        reference_result_set_id=frozen.REFERENCE_RESULT_SET_ID,
        reference_cohort_id=frozen.REFERENCE_COHORT_ID,
        reference_pair_manifest_hash=frozen.REFERENCE_PAIR_MANIFEST_HASH,
    )


def build_stage15a_canonical500_spec(
    config: Stage15ACanonical500Config,
) -> AlgorithmResearchExperimentSpec:
    """Translate the configuration into what the shared engine understands."""
    return AlgorithmResearchExperimentSpec(
        experiment_id=config.experiment_id,
        kind=config.kind,
        replicate_index=config.replicate_index,
        dataset_config=config.dataset_config,
        protocol_config=config.protocol_config,
        algorithm_config=config.algorithm_config,
        require_verified_checksums=config.require_verified_checksums,
        research_mode=config.research_mode,
        materialization_policy=config.materialization_policy,
        execution_profile=config.execution_profile,
        expected_jobs=config.expected_jobs,
        expected_per_release=config.expected_per_release,
        expected_per_stage=config.expected_per_stage,
        expected_releases=config.expected_releases,
        expected_subjects=config.expected_subjects,
        expected_participating_images=config.expected_participating_images,
        evidence_directory=frozen.EVIDENCE_DIRECTORY,
        preparation_set_id=config.preparation_set_id,
        preparation_set_fingerprint=config.preparation_set_fingerprint,
        transform_profile_id=config.transform_profile_id,
        transform_profile_fingerprint=config.transform_profile_fingerprint,
        expected_source_ppi=dict(config.expected_source_ppi),
    )


def _preparer_factory(
    workspace: Path, spec: AlgorithmResearchExperimentSpec
) -> Canonical500ImagePreparer:
    """Bind a preparer to the exact set this run declares.

    A constructor call rather than a search. The set is named by id *and* by
    fingerprint, so a preparer that went looking would switch inputs the next
    time somebody materialised a new one (docs/adr/0033).
    """
    return Canonical500ImagePreparer(
        store=PreparedImageSetStore(Path(workspace)),
        preparation_set_id=str(spec.preparation_set_id),
        preparation_set_fingerprint=str(spec.preparation_set_fingerprint),
    )


# --------------------------------------------------------------------- driving


def preflight_stage15a_canonical500_run(
    *,
    repository_root: Path = REPOSITORY_ROOT,
    workspace: Path = DEFAULT_WORKSPACE,
) -> dict[str, Any]:
    """Check every input the 6,000 run will read, and write nothing.

    What to run before deciding whether to start the execution: the artifact
    digests, the frozen runtime closure and the experiment document, all without
    creating a run.
    """
    root = Path(repository_root)
    config = load_stage15a_canonical500_config(repository_root=root)
    closure = runtime.build_runtime_closure(repository_root=root)
    prepared_set = (
        Path(workspace) / "prepared-images" / config.preparation_set_id / "manifest.json"
    )
    return {
        "experiment_id": config.experiment_id,
        "config_loads": True,
        "runtime_gate_state": closure.gate_state,
        "artifacts_verify": closure.artifacts_verify,
        "wheels_verify": closure.wheels_verify,
        "runtime_manifest_fingerprint": runtime.runtime_manifest_fingerprint(closure),
        "prepared_set_present": prepared_set.is_file(),
        "expected_jobs": config.expected_jobs,
        "job_deadline_seconds": int(config.execution_profile.timeout_seconds),
        "reference_run_id": config.reference_run_id,
    }


def prepare_stage15a_canonical500_run(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    dataset_root: Path | None = None,
    repository_root: Path = REPOSITORY_ROOT,
) -> PreparedAlgorithmResearchRun:
    """Check everything, then write the run, the plan and the runtime binding.

    No raw result is written here, and none can be: this function never reaches
    the executor.
    """
    root = Path(repository_root)
    config = load_stage15a_canonical500_config(repository_root=root)
    closure = runtime.build_runtime_closure(repository_root=root)
    runtime.require_ready(closure)
    return prepare_fingerprints_matching_research_run(
        spec=build_stage15a_canonical500_spec(config),
        preparer_factory=_preparer_factory,
        workspace=Path(workspace),
        dataset_root=dataset_root,
        repository_root=root,
        expected_input_set=SD300_CANONICAL500_INPUT_SET,
    )


def execute_stage15a_canonical500_run(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    dataset_root: Path | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
    max_new_jobs: int | None = None,
) -> RunExecutionSummary:
    """Execute some or all of the prepared run, one comparison at a time.

    May be stopped and resumed. A result that is already stored is verified and
    skipped, never re-executed and never overwritten, so resuming cannot change a
    number that has already been recorded (spec section 29).
    """
    root = Path(repository_root)
    config = load_stage15a_canonical500_config(repository_root=root)
    return execute_fingerprints_matching_research_run(
        spec=build_stage15a_canonical500_spec(config),
        preparer_factory=_preparer_factory,
        workspace=Path(workspace),
        dataset_root=dataset_root,
        repository_root=root,
        run_id=run_id,
        max_new_jobs=max_new_jobs,
        expected_input_set=SD300_CANONICAL500_INPUT_SET,
    )


def inspect_stage15a_canonical500_experiment(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    dataset_root: Path | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
) -> ResearchRunState:
    """Report where Stage 15A's run stands. Never writes."""
    root = Path(repository_root)
    config = load_stage15a_canonical500_config(repository_root=root)
    return inspect_fingerprints_matching_research_experiment(
        spec=build_stage15a_canonical500_spec(config),
        preparer_factory=_preparer_factory,
        workspace=Path(workspace),
        dataset_root=dataset_root,
        repository_root=root,
        run_id=run_id,
        expected_input_set=SD300_CANONICAL500_INPUT_SET,
    )


def finalize_stage15a_canonical500_run(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    dataset_root: Path | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
) -> ResearchReceipt:
    """Revalidate everything and publish the run's own research receipt."""
    root = Path(repository_root)
    config = load_stage15a_canonical500_config(repository_root=root)
    return finalize_fingerprints_matching_research_run(
        spec=build_stage15a_canonical500_spec(config),
        preparer_factory=_preparer_factory,
        workspace=Path(workspace),
        dataset_root=dataset_root,
        repository_root=root,
        run_id=run_id,
        expected_input_set=SD300_CANONICAL500_INPUT_SET,
    )


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    command = argv[0] if argv else "preflight"
    if command == "preflight":
        print(
            json.dumps(
                preflight_stage15a_canonical500_run(repository_root=Path(".")),
                indent=2,
                sort_keys=True,
                default=str,
            )
        )
        return 0
    if command == "status":
        state = inspect_stage15a_canonical500_experiment(repository_root=Path("."))
        print(state.status, state.run_id)
        return 0
    print(f"unknown command {command!r}; expected preflight or status", file=sys.stderr)
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
