"""The 6,000 canonical SD300 comparisons, run again by the qualified flx route.

Everything that decides *what* is compared was decided in stage 6A and is read
back here unchanged: the protocol, the cohort, the 6,000-row pair manifest, its
order, and the 3,000 immutable 500 ppi PNGs.  Nothing in this module selects a
cohort, generates a pair, resamples an image or writes a PNG.

What is new is the algorithm, and only the algorithm:

    canonical gray8 PNG bytes
      -> declared 299x299 transform
      -> DeepPrint_TexMinu_512_without_localization
      -> dot(texture) + dot(minutia)

driven by the route stage 8B qualified, through the orchestration stage 7A
extracted.  This module contains no orchestration of its own.  It loads two
configuration files, proves the candidate run is aligned with the reference run
row by row, proves the route is the one Stage 8B qualified, and hands the
resulting spec plus
:func:`~fpbench.experiments.flx_research.flx_research_integration` to
:mod:`fpbench.experiments.algorithm_research` (spec section 19).

Four things it deliberately does not do:

* **It reads no SourceAFIS or NBIS score.**  The reference run is opened for its
  identity, its plan, its pair manifest, its prepared inputs and its readiness —
  and for nothing else.  There is no join of two result tables here
  (docs/adr/0076, spec section 18).
* **It applies no threshold and computes no metric.**  A flx score of 0 is a
  successful comparison, not a NON_MATCH, and no operating point exists on this
  scale (docs/adr/0003, docs/adr/0065).
* **It publishes no score statistic.**  Not a minimum, not a mean, not a
  histogram, not an example row.  A distribution is a threshold in disguise
  (docs/adr/0076).
* **It materialises no image.**  Every pixel it reads belongs to
  ``prepset_be560e047991`` and was written by stage 6A (docs/adr/0074).

There is no command-line entry point on purpose: the run takes hours, it may not
be started under a different commit than it was prepared under, and a convenient
``execute`` verb is exactly how that happens by accident (spec section 20).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from fpbench.core.errors import ConfigurationError, ResearchPreflightError
from fpbench.core.execution_models import ExecutionProfile
from fpbench.core.identifiers import validate_id
from fpbench.core.imaging_models import PreparedImageEntry
from fpbench.core.research_models import (
    ResearchReceipt,
    ResearchRunState,
    research_receipt_content_hash,
    research_receipt_fingerprint,
)
from fpbench.core.run_state_models import IntegrityIssue
from fpbench.core.serialization import read_json, to_plain, write_json
from fpbench.execution.batch_runner import RunExecutionSummary
from fpbench.experiments.algorithm_research import (
    REPOSITORY_ROOT,
    AlgorithmResearchExperimentSpec,
    PreparedAlgorithmResearchRun,
    capture_research_provenance,
    read_run_pointer,
)
from fpbench.experiments.canonical_run_alignment import (
    SD300_CANONICAL_EXPECTATIONS,
    AlignmentExpectations,
    CanonicalRunAlignmentReport,
    ReferenceRunIdentity,
    build_canonical_run_alignment_report,
    canonical_run_alignment_fingerprint,
    load_candidate_alignment_side,
    load_reference_alignment_side,
    require_canonical_input_controls_equal,
    require_clean_alignment,
)
from fpbench.experiments.config_values import (
    reject_unknown_keys,
    require_yaml_bool,
    require_yaml_exact_int,
    require_yaml_mapping,
    require_yaml_non_empty_str,
)
from fpbench.experiments.flx_research import (
    execute_flx_research_run,
    finalize_flx_research_run,
    inspect_flx_research_experiment,
    prepare_flx_research_run,
)
from fpbench.experiments.flx_validation import (
    SD300_CANONICAL500_INPUT_SET,
    validate_flx_result_set,
)
from fpbench.experiments.sd300_inputs import SD300Inputs, load_sd300_inputs
from fpbench.experiments.stage8b_binding import require_stage8b_binding
from fpbench.experiments.stage8c_identity import (
    ALIGNMENT_REPORT_NAME,
    EVIDENCE_DIRECTORY,
    EXPERIMENT_ID,
    FORBIDDEN_CONFIG_KEYS,
    PERMITTED_DOWNSTREAM_EXPERIMENTS,
    REQUIRED_REPORTING_SWITCHES,
    STAGE_8C_FINALIZATION_NAME,
)
from fpbench.imaging.canonical500 import Canonical500ImagePreparer
from fpbench.storage.plan_store import PlanStore
from fpbench.storage.prepared_image_set_store import PreparedImageSetStore
from fpbench.storage.result_set_store import ResultSetStore
from fpbench.storage.result_store import ResultStore
from fpbench.storage.runtime_bundle_store import RuntimeBundleStore

__all__ = [
    "EXPERIMENT_ID",
    "EVIDENCE_DIRECTORY",
    "ALIGNMENT_REPORT_NAME",
    "STAGE_8C_FINALIZATION_NAME",
    "FORBIDDEN_CONFIG_KEYS",
    "PERMITTED_DOWNSTREAM_EXPERIMENTS",
    "SD300_CANONICAL_EXPECTATIONS",
    "DEFAULT_EXPERIMENT_CONFIG",
    "DEFAULT_WORKSPACE",
    "Stage8BBinding",
    "FlxArtifactIdentity",
    "FlxOperationCounts",
    "FlxCanonical500ExperimentConfig",
    "FlxCanonical500ExperimentState",
    "load_flx_canonical500_config",
    "build_flx_canonical500_spec",
    "preflight_flx_canonical500_run",
    "verify_flx_canonical500_alignment",
    "prepare_flx_canonical500_run",
    "execute_flx_canonical500_run",
    "inspect_flx_canonical500_experiment",
    "finalize_flx_canonical500_run",
    "refresh_flx_canonical500_stage_finalization",
    "publish_flx_canonical500_evidence",
    "publish_flx_canonical500_finalization",
    "check_no_cross_algorithm_comparison",
]

DEFAULT_EXPERIMENT_CONFIG = (
    REPOSITORY_ROOT / "configs" / "experiments" / f"{EXPERIMENT_ID}.yaml"
)
DEFAULT_WORKSPACE = REPOSITORY_ROOT / "workspace"

_TOP_LEVEL_KEYS = (
    "experiment_id",
    "kind",
    "replicate_index",
    "dataset_config",
    "protocol_config",
    "algorithm_config",
    "require_verified_checksums",
    "stage8b",
    "artifact",
    "reference",
    "preparation",
    "expected",
    "operations",
    "execution",
    "runtime",
    "reporting",
)

_STAGE8B_KEYS = (
    "finalization_fingerprint",
    "outcome",
    "algorithm_id",
    "adapter_id",
    "adapter_version",
    "runtime_profile_id",
    "runtime_manifest_fingerprint",
    "preprocessing_profile_id",
    "preprocessing_profile_fingerprint",
    "representation_profile_id",
    "representation_profile_fingerprint",
    "score_profile_id",
    "score_profile_fingerprint",
    "adapter_profile_fingerprint",
)
_ARTIFACT_KEYS = (
    "source_commit",
    "source_archive_sha256",
    "checkpoint_filename",
    "checkpoint_sha256",
    "checkpoint_size_bytes",
)
_REFERENCE_KEYS = (
    "run_id",
    "plan_id",
    "result_set_id",
    "cohort_id",
    "pair_manifest_hash",
)
_PREPARATION_KEYS = (
    "set_id",
    "set_fingerprint",
    "transform_profile_id",
    "transform_profile_fingerprint",
    "transform_runtime_fingerprint",
    "target_ppi",
)
_EXPECTED_KEYS = (
    "jobs",
    "pairs_per_release_stage",
    "pairs_per_release",
    "pairs_per_stage",
    "releases",
    "subjects",
    "participating_images",
    "source_ppi",
)
_OPERATIONS_KEYS = (
    "preprocess_calls_per_comparison",
    "logical_extractions_per_comparison",
    "comparisons_per_job",
    "inference_batch_rows",
    "inference_batch_rule",
    "represented_row",
)
_EXECUTION_KEYS = (
    "profile_config",
    "profile_id",
    "sequential",
    "max_workers",
    "retries",
    "job_deadline_seconds",
)
_RUNTIME_KEYS = (
    "materialization_policy",
    "research_mode",
    "image_materialization_policy",
)
_REPORTING_KEYS = tuple(sorted(REQUIRED_REPORTING_SWITCHES))

_HEX = frozenset("0123456789abcdef")


# ------------------------------------------------------------------ the config


@dataclass(frozen=True, slots=True)
class Stage8BBinding:
    """The qualified route, as the experiment restates it.

    Checked against :mod:`fpbench.experiments.stage8c_identity` when the file is
    loaded, and against the *published Stage 8B evidence* when a run is
    prepared. The first check catches a typo; the second catches a stage that
    was republished under the same numbers (spec section 3).
    """

    finalization_fingerprint: str
    outcome: str

    algorithm_id: str
    adapter_id: str
    adapter_version: int

    runtime_profile_id: str
    runtime_manifest_fingerprint: str
    preprocessing_profile_id: str
    preprocessing_profile_fingerprint: str
    representation_profile_id: str
    representation_profile_fingerprint: str
    score_profile_id: str
    score_profile_fingerprint: str
    adapter_profile_fingerprint: str

    @property
    def profile_fingerprints(self) -> Mapping[str, str]:
        return {
            "runtime_manifest": self.runtime_manifest_fingerprint,
            "preprocessing": self.preprocessing_profile_fingerprint,
            "representation": self.representation_profile_fingerprint,
            "score": self.score_profile_fingerprint,
            "adapter": self.adapter_profile_fingerprint,
        }


@dataclass(frozen=True, slots=True)
class FlxArtifactIdentity:
    """The source archive and checkpoint, neither of which ever moves."""

    source_commit: str
    source_archive_sha256: str
    checkpoint_filename: str
    checkpoint_sha256: str
    checkpoint_size_bytes: int


@dataclass(frozen=True, slots=True)
class FlxOperationCounts:
    """How many operations of each kind one job performs, and one run plans.

    The two extraction counts are separate on purpose. ``logical_extractions``
    is how many representations exist; ``physical_forward_rows`` is how much
    arithmetic the checkpoint did, and it is twice as large because the pinned
    texture branch cannot process a batch of one (docs/adr/0070,
    docs/adr/0075).
    """

    preprocess_calls_per_comparison: int
    logical_extractions_per_comparison: int
    comparisons_per_job: int
    inference_batch_rows: int
    inference_batch_rule: str
    represented_row: int

    jobs: int

    @property
    def planned_preprocess_calls(self) -> int:
        return self.jobs * self.preprocess_calls_per_comparison

    @property
    def planned_logical_extractions(self) -> int:
        return self.jobs * self.logical_extractions_per_comparison

    @property
    def planned_physical_forward_rows(self) -> int:
        return self.planned_logical_extractions * self.inference_batch_rows

    @property
    def planned_comparison_calls(self) -> int:
        return self.jobs * self.comparisons_per_job


@dataclass(frozen=True, slots=True)
class FlxCanonical500ExperimentConfig:
    """The pinned description of the Stage 8C run.

    ``execution_profile`` is Stage 8C's own profile object, read from the file
    the experiment names. Unlike Stage 7C it is *not* the reference run's: the
    reference run's 60-second job deadline was chosen for a Java matcher, and
    this route spends five separately deadlined operations inside one job. Every
    parameter that decides which pixels are opened is identical, and that is
    what the alignment checks (docs/adr/0074).
    """

    experiment_id: str
    kind: str
    replicate_index: int

    dataset_config: Path
    protocol_config: Path
    algorithm_config: Path
    require_verified_checksums: bool

    stage8b: Stage8BBinding
    artifact: FlxArtifactIdentity

    reference: ReferenceRunIdentity
    reference_cohort_id: str
    reference_pair_manifest_hash: str

    preparation_set_id: str
    preparation_set_fingerprint: str
    transform_profile_id: str
    transform_profile_fingerprint: str
    transform_runtime_fingerprint: str
    target_ppi: int

    expected_jobs: int
    expected_per_release: int
    expected_per_stage: int
    expected_per_release_stage: int
    expected_releases: tuple[str, ...]
    expected_subjects: int
    expected_participating_images: int
    expected_source_ppi: Mapping[str, int]

    operations: FlxOperationCounts

    execution_profile: ExecutionProfile
    job_deadline_seconds: int
    max_workers: int
    materialization_policy: str
    image_materialization_policy: str
    research_mode: bool

    @property
    def alignment_expectations(self) -> AlignmentExpectations:
        return AlignmentExpectations(
            pair_count=self.expected_jobs,
            prepared_entry_count=self.expected_participating_images,
            pairs_per_release_stage=self.expected_per_release_stage,
            prepared_entries_per_release=(
                self.expected_participating_images // len(self.expected_releases)
            ),
            releases=self.expected_releases,
        )


def load_flx_canonical500_config(
    path: Path = DEFAULT_EXPERIMENT_CONFIG,
    *,
    repository_root: Path = REPOSITORY_ROOT,
) -> FlxCanonical500ExperimentConfig:
    """Read ``configs/experiments/flx_canonical500_full_v1.yaml``, strictly.

    Every scalar is read with a type-checking helper rather than coerced, every
    unknown key is refused, every frozen identity is compared with
    :mod:`fpbench.experiments.stage8c_identity`, and a key that would turn this
    into a decision stage is refused wherever it appears in the document
    (spec sections 17 and 20).
    """
    from fpbench.experiments import stage8c_identity as frozen

    path = Path(path)
    if not path.is_file():
        raise ConfigurationError(f"experiment config not found: {path}")
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(document, Mapping):
        raise ConfigurationError(f"{path}: expected a mapping at the top level")

    _require_no_decision_keys(document, path)
    reject_unknown_keys(document, _TOP_LEVEL_KEYS, where=path)

    stage8b = require_yaml_mapping(document, "stage8b", where=path)
    reject_unknown_keys(stage8b, _STAGE8B_KEYS, where=f"{path} stage8b")
    artifact = require_yaml_mapping(document, "artifact", where=path)
    reject_unknown_keys(artifact, _ARTIFACT_KEYS, where=f"{path} artifact")
    reference = require_yaml_mapping(document, "reference", where=path)
    reject_unknown_keys(reference, _REFERENCE_KEYS, where=f"{path} reference")
    preparation = require_yaml_mapping(document, "preparation", where=path)
    reject_unknown_keys(preparation, _PREPARATION_KEYS, where=f"{path} preparation")
    expected = require_yaml_mapping(document, "expected", where=path)
    reject_unknown_keys(expected, _EXPECTED_KEYS, where=f"{path} expected")
    operations = require_yaml_mapping(document, "operations", where=path)
    reject_unknown_keys(operations, _OPERATIONS_KEYS, where=f"{path} operations")
    execution = require_yaml_mapping(document, "execution", where=path)
    reject_unknown_keys(execution, _EXECUTION_KEYS, where=f"{path} execution")
    runtime = require_yaml_mapping(document, "runtime", where=path)
    reject_unknown_keys(runtime, _RUNTIME_KEYS, where=f"{path} runtime")
    reporting = require_yaml_mapping(document, "reporting", where=path)
    reject_unknown_keys(reporting, _REPORTING_KEYS, where=f"{path} reporting")

    _require_reporting_switches(reporting, path)
    _require_execution_controls(execution, path)

    root = Path(repository_root)
    profile_config = (
        root
        / require_yaml_non_empty_str(
            execution, "profile_config", where=f"{path} execution"
        )
    ).resolve()
    profile = _load_execution_profile(profile_config)
    declared_profile_id = require_yaml_non_empty_str(
        execution, "profile_id", where=f"{path} execution"
    )
    if profile.profile_id != declared_profile_id:
        raise ConfigurationError(
            f"{path}: execution.profile_id is {declared_profile_id!r} but "
            f"{profile_config.name} defines {profile.profile_id!r}"
        )
    if declared_profile_id != frozen.EXECUTION_PROFILE_ID:
        raise ConfigurationError(
            f"{path}: Stage 8C runs under {frozen.EXECUTION_PROFILE_ID!r}, not "
            f"{declared_profile_id!r}"
        )

    job_deadline = require_yaml_exact_int(
        execution, "job_deadline_seconds", where=f"{path} execution", minimum=1
    )
    if float(profile.timeout_seconds) != float(job_deadline):
        raise ConfigurationError(
            f"{path}: execution.job_deadline_seconds is {job_deadline} but "
            f"{profile_config.name} gives a job {profile.timeout_seconds} seconds; "
            "two files may not disagree about the budget a comparison ran under"
        )
    if job_deadline != frozen.JOB_DEADLINE_SECONDS:
        raise ConfigurationError(
            f"{path}: the frozen Stage 8C job deadline is "
            f"{frozen.JOB_DEADLINE_SECONDS} seconds, not {job_deadline} "
            "(spec section 11)"
        )

    binding = _load_stage8b_binding(stage8b, path, frozen)
    artifact_identity = _load_artifact_identity(artifact, path, frozen)

    preparation_set_id = require_yaml_non_empty_str(
        preparation, "set_id", where=f"{path} preparation"
    )
    preparation_set_fingerprint = _require_digest(
        require_yaml_non_empty_str(
            preparation, "set_fingerprint", where=f"{path} preparation"
        ),
        f"{path} preparation.set_fingerprint",
    )
    transform_profile_id = require_yaml_non_empty_str(
        preparation, "transform_profile_id", where=f"{path} preparation"
    )
    transform_profile_fingerprint = _require_digest(
        require_yaml_non_empty_str(
            preparation, "transform_profile_fingerprint", where=f"{path} preparation"
        ),
        f"{path} preparation.transform_profile_fingerprint",
    )
    transform_runtime_fingerprint = _require_digest(
        require_yaml_non_empty_str(
            preparation, "transform_runtime_fingerprint", where=f"{path} preparation"
        ),
        f"{path} preparation.transform_runtime_fingerprint",
    )
    target_ppi = require_yaml_exact_int(
        preparation, "target_ppi", where=f"{path} preparation", minimum=1
    )

    for label, value, expected_value in (
        ("preparation.set_id", preparation_set_id, frozen.PREPARATION_SET_ID),
        (
            "preparation.set_fingerprint",
            preparation_set_fingerprint,
            frozen.PREPARATION_SET_FINGERPRINT,
        ),
        (
            "preparation.transform_profile_id",
            transform_profile_id,
            frozen.TRANSFORM_PROFILE_ID,
        ),
        (
            "preparation.transform_profile_fingerprint",
            transform_profile_fingerprint,
            frozen.TRANSFORM_PROFILE_FINGERPRINT,
        ),
        (
            "preparation.transform_runtime_fingerprint",
            transform_runtime_fingerprint,
            frozen.TRANSFORM_RUNTIME_FINGERPRINT,
        ),
    ):
        _require_frozen(label, value, expected_value, path)

    # The experiment and the execution profile must name one input set. Two
    # files disagreeing about which pixels a run opened is the failure the
    # canonical stage exists to make impossible (docs/adr/0031).
    for key, value in (
        ("preparation_set_id", preparation_set_id),
        ("preparation_set_fingerprint", preparation_set_fingerprint),
        ("transform_profile_id", transform_profile_id),
        ("transform_profile_fingerprint", transform_profile_fingerprint),
        ("target_ppi", str(target_ppi)),
    ):
        if profile.parameters.get(key) != value:
            raise ConfigurationError(
                f"{path}: the experiment names {key}={value[:16]}... but execution "
                f"profile {profile.profile_id} names "
                f"{str(profile.parameters.get(key))[:16]}...; a run may not "
                "straddle two input sets"
            )

    releases = expected.get("releases")
    if not isinstance(releases, list) or not all(
        isinstance(item, str) and item.strip() for item in releases
    ):
        raise ConfigurationError(
            f"{path}: expected.releases must be a list of release names"
        )
    release_names = tuple(str(item) for item in releases)
    if release_names != frozen.EXPECTED_RELEASES:
        raise ConfigurationError(
            f"{path}: Stage 8C covers {list(frozen.EXPECTED_RELEASES)}, not "
            f"{list(release_names)}"
        )

    participating = require_yaml_exact_int(
        expected, "participating_images", where=f"{path} expected", minimum=1
    )
    if participating % len(release_names):
        raise ConfigurationError(
            f"{path}: {participating} participating images do not divide evenly "
            f"across {len(release_names)} releases"
        )
    expected_jobs = require_yaml_exact_int(
        expected, "jobs", where=f"{path} expected", minimum=1
    )
    for label, value, expected_value in (
        ("expected.jobs", expected_jobs, frozen.EXPECTED_JOBS),
        (
            "expected.participating_images",
            participating,
            frozen.EXPECTED_PARTICIPATING_IMAGES,
        ),
    ):
        _require_frozen(label, value, expected_value, path)

    source_ppi = require_yaml_mapping(expected, "source_ppi", where=f"{path} expected")
    counts = _load_operation_counts(operations, path, frozen, jobs=expected_jobs)

    reference_identity = ReferenceRunIdentity(
        run_id=validate_id(
            require_yaml_non_empty_str(reference, "run_id", where=f"{path} reference")
        ),
        plan_id=validate_id(
            require_yaml_non_empty_str(reference, "plan_id", where=f"{path} reference")
        ),
        result_set_id=validate_id(
            require_yaml_non_empty_str(
                reference, "result_set_id", where=f"{path} reference"
            )
        ),
        preparation_set_id=preparation_set_id,
        preparation_set_fingerprint=preparation_set_fingerprint,
    )
    reference_cohort_id = require_yaml_non_empty_str(
        reference, "cohort_id", where=f"{path} reference"
    )
    reference_pair_manifest_hash = _require_digest(
        require_yaml_non_empty_str(
            reference, "pair_manifest_hash", where=f"{path} reference"
        ),
        f"{path} reference.pair_manifest_hash",
    )
    for label, value, expected_value in (
        ("reference.run_id", reference_identity.run_id, frozen.REFERENCE_RUN_ID),
        ("reference.plan_id", reference_identity.plan_id, frozen.REFERENCE_PLAN_ID),
        (
            "reference.result_set_id",
            reference_identity.result_set_id,
            frozen.REFERENCE_RESULT_SET_ID,
        ),
        ("reference.cohort_id", reference_cohort_id, frozen.REFERENCE_COHORT_ID),
        (
            "reference.pair_manifest_hash",
            reference_pair_manifest_hash,
            frozen.REFERENCE_PAIR_MANIFEST_HASH,
        ),
    ):
        _require_frozen(label, value, expected_value, path)

    experiment_id = require_yaml_non_empty_str(document, "experiment_id", where=path)
    _require_frozen("experiment_id", experiment_id, frozen.EXPERIMENT_ID, path)

    image_policy = require_yaml_non_empty_str(
        runtime, "image_materialization_policy", where=f"{path} runtime"
    )
    if image_policy != "reference_existing_prepared_images":
        raise ConfigurationError(
            f"{path}: runtime.image_materialization_policy must be "
            "'reference_existing_prepared_images'. Stage 8C creates no "
            "PreparedImageSet (spec section 2)"
        )

    return FlxCanonical500ExperimentConfig(
        experiment_id=experiment_id,
        kind=require_yaml_non_empty_str(document, "kind", where=path),
        replicate_index=require_yaml_exact_int(
            document, "replicate_index", where=path, minimum=0
        ),
        dataset_config=(
            root / require_yaml_non_empty_str(document, "dataset_config", where=path)
        ).resolve(),
        protocol_config=(
            root / require_yaml_non_empty_str(document, "protocol_config", where=path)
        ).resolve(),
        algorithm_config=(
            root / require_yaml_non_empty_str(document, "algorithm_config", where=path)
        ).resolve(),
        require_verified_checksums=require_yaml_bool(
            document, "require_verified_checksums", where=path
        ),
        stage8b=binding,
        artifact=artifact_identity,
        reference=reference_identity,
        reference_cohort_id=reference_cohort_id,
        reference_pair_manifest_hash=reference_pair_manifest_hash,
        preparation_set_id=preparation_set_id,
        preparation_set_fingerprint=preparation_set_fingerprint,
        transform_profile_id=transform_profile_id,
        transform_profile_fingerprint=transform_profile_fingerprint,
        transform_runtime_fingerprint=transform_runtime_fingerprint,
        target_ppi=target_ppi,
        expected_jobs=expected_jobs,
        expected_per_release=require_yaml_exact_int(
            expected, "pairs_per_release", where=f"{path} expected", minimum=1
        ),
        expected_per_stage=require_yaml_exact_int(
            expected, "pairs_per_stage", where=f"{path} expected", minimum=1
        ),
        expected_per_release_stage=require_yaml_exact_int(
            expected, "pairs_per_release_stage", where=f"{path} expected", minimum=1
        ),
        expected_releases=release_names,
        expected_subjects=require_yaml_exact_int(
            expected, "subjects", where=f"{path} expected", minimum=1
        ),
        expected_participating_images=participating,
        expected_source_ppi={
            str(key): require_yaml_exact_int(
                source_ppi, str(key), where=f"{path} expected.source_ppi", minimum=1
            )
            for key in source_ppi
        },
        operations=counts,
        execution_profile=profile,
        job_deadline_seconds=job_deadline,
        max_workers=require_yaml_exact_int(
            execution, "max_workers", where=f"{path} execution", minimum=1
        ),
        materialization_policy=require_yaml_non_empty_str(
            runtime, "materialization_policy", where=f"{path} runtime"
        ),
        image_materialization_policy=image_policy,
        research_mode=require_yaml_bool(
            runtime, "research_mode", where=f"{path} runtime"
        ),
    )


def build_flx_canonical500_spec(
    config: FlxCanonical500ExperimentConfig,
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
        evidence_directory=EVIDENCE_DIRECTORY,
        preparation_set_id=config.preparation_set_id,
        preparation_set_fingerprint=config.preparation_set_fingerprint,
        transform_profile_id=config.transform_profile_id,
        transform_profile_fingerprint=config.transform_profile_fingerprint,
        expected_source_ppi=dict(config.expected_source_ppi),
    )


# ------------------------------------------------------------------- the state


@dataclass(frozen=True, slots=True)
class FlxCanonical500ExperimentState:
    """How far along Stage 8C is, and whether it may be called finished.

    Two independent readings, combined by ``and``. The research state says the
    evidence chain is complete and re-verifies from the files; the alignment
    report says the run was given the reference run's own inputs. A run can be
    ``RESEARCH_READY`` and misaligned — that is precisely the failure this stage
    exists to make impossible to publish (spec section 23).
    """

    research_state: ResearchRunState
    alignment_report: CanonicalRunAlignmentReport
    issues: tuple[IntegrityIssue, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "issues", tuple(self.issues))

    @property
    def is_ready(self) -> bool:
        return (
            self.research_state.is_research_ready
            and self.alignment_report.is_clean
            and not self.issues
        )

    @property
    def run_id(self) -> str:
        return self.research_state.run_id

    @property
    def status(self) -> str:
        """The explicit Stage 8C state (spec section 23)."""
        if self.is_ready:
            return "FLX_CANONICAL500_RAW_READY"
        if self.issues or not self.alignment_report.is_clean:
            return "BLOCKED"
        return self.research_state.status.value


# ------------------------------------------------------------------ preflight


def preflight_flx_canonical500_run(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    dataset_root: Path | None = None,
    config: FlxCanonical500ExperimentConfig | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    bundle_root: Path | None = None,
    require_clean_tree: bool = True,
) -> Mapping[str, Any]:
    """Check every input Stage 8C will read, and write nothing.

    Everything ``prepare`` checks before it creates a run, run on its own so an
    operator can find out that an artifact is missing without a half-prepared
    workspace to clean up. It reads; it does not plan, does not materialise and
    does not touch the executor (spec section 34).
    """
    workspace = Path(workspace)
    repository_root = Path(repository_root)
    config = config or load_flx_canonical500_config(repository_root=repository_root)

    findings: dict[str, Any] = {"experiment_id": config.experiment_id}
    if require_clean_tree:
        software = capture_research_provenance(repository_root)
        findings["source_commit"] = software.source_revision
        findings["source_tree_clean"] = software.source_tree_clean

    published = require_stage8b_binding(
        config.stage8b, config.artifact, repository_root=repository_root
    )
    findings["stage8b_outcome"] = published.outcome
    findings["stage8b_finalization_fingerprint"] = published.finalization_fingerprint

    # The 2.06 GB runtime, rehashed in full: the archive, the five imported
    # source files and all 875,770,140 checkpoint bytes. This is the one check
    # that needs the bundle to be present, and it is the reason a missing
    # checkpoint is one fault of the run (docs/adr/0072).
    from fpbench.core.flx_errors import FlxError
    from fpbench.experiments.flx_research import resolve_bundle_root
    from fpbench.flx.artifacts import FlxRuntimeBundle, verify_bundle_artifacts

    root = resolve_bundle_root(bundle_root)
    try:
        findings["artifacts"] = dict(
            verify_bundle_artifacts(FlxRuntimeBundle(root))
        )
    except FlxError as exc:
        raise ResearchPreflightError(
            f"the pinned flx runtime bundle does not verify: {exc}"
        ) from exc

    context = _load_alignment_context(
        workspace=workspace,
        dataset_root=dataset_root,
        config=config,
        repository_root=repository_root,
        run_id=None,
    )
    require_clean_alignment(context.report)
    require_canonical_input_controls_equal(
        context.reference_run,
        build_flx_canonical500_spec(config),
        reference_materialization_policy=context.reference_materialization_policy,
    )
    findings["alignment_fingerprint"] = context.report.alignment_fingerprint
    findings["prepared_entries"] = len(context.prepared_entries)
    findings["pairs"] = len(context.inputs.pairs)
    findings["pair_manifest_hash"] = context.inputs.pair_manifest_hash
    findings["planned_operations"] = {
        "preprocess_calls": config.operations.planned_preprocess_calls,
        "logical_extraction_calls": config.operations.planned_logical_extractions,
        "physical_forward_rows": config.operations.planned_physical_forward_rows,
        "comparison_calls": config.operations.planned_comparison_calls,
    }
    return findings


# ------------------------------------------------------------------- alignment


def verify_flx_canonical500_alignment(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    dataset_root: Path | None = None,
    config: FlxCanonical500ExperimentConfig | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
    require_clean: bool = True,
) -> CanonicalRunAlignmentReport:
    """Prove the flx run is over the reference run's own inputs, row by row.

    Loads both sides from the workspace's manifests and compares them; see
    :mod:`fpbench.experiments.canonical_run_alignment` for what "compares" means
    here, which is every field of every pair and every field of every prepared
    image, never a count against a count (spec section 6).

    Args:
        run_id: The flx run to align. When it is ``None`` and no run has been
            prepared yet, the candidate side is the pair manifest as the planner
            will order it — which is what preparation checks *before* creating a
            run.

    Raises:
        ResearchPreflightError: ``require_clean`` and the alignment is not clean.
    """
    config = config or load_flx_canonical500_config(repository_root=repository_root)
    context = _load_alignment_context(
        workspace=Path(workspace),
        dataset_root=dataset_root,
        config=config,
        repository_root=Path(repository_root),
        run_id=run_id,
    )
    report = context.report
    if require_clean:
        require_clean_alignment(report)
    return report


# ------------------------------------------------------------------- commands


def prepare_flx_canonical500_run(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    dataset_root: Path | None = None,
    config: FlxCanonical500ExperimentConfig | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    bundle_root: Path | None = None,
) -> PreparedAlgorithmResearchRun:
    """Check everything, then write the run, the plan and the runtime binding.

    In order, and each step is a place the whole thing stops (spec section 21):

    1. the working tree is clean and committed;
    2. the Stage 8B finalization is read and its outcome permits execution;
    3. the source archive and the checkpoint re-hash to their frozen digests;
    4. the runtime bundle's three pinned files are present and committed;
    5. every Stage 8B profile is rebuilt from this source and matches;
    6. the prepared-image set verifies in full;
    7. all 3,000 PNGs and their rasters are checked through it;
    8. the reference SourceAFIS run is ``RESEARCH_READY``;
    9. the pair manifest is loaded with ``allow_creation=False`` — not rebuilt;
    10. the alignment report is derived;
    11. it is clean, and the input controls match, or nothing further happens;
    12. the engine creates the run;
    13. the engine plans exactly 6,000 jobs;
    14. the alignment is re-derived against the plan that now exists;
    15. the derived report is stored in the workspace.

    No raw result is written here, and none can be: this function never reaches
    the executor.
    """
    workspace = Path(workspace)
    repository_root = Path(repository_root)
    config = config or load_flx_canonical500_config(repository_root=repository_root)

    # 1-7. Everything about the route and the inputs, before a run exists.
    preflight_flx_canonical500_run(
        workspace=workspace,
        dataset_root=dataset_root,
        config=config,
        repository_root=repository_root,
        bundle_root=bundle_root,
    )

    # 8-11. The inputs again, kept this time so the comparison is not repeated.
    context = _load_alignment_context(
        workspace=workspace,
        dataset_root=dataset_root,
        config=config,
        repository_root=repository_root,
        run_id=None,
    )
    require_clean_alignment(context.report)
    require_canonical_input_controls_equal(
        context.reference_run,
        build_flx_canonical500_spec(config),
        reference_materialization_policy=context.reference_materialization_policy,
    )

    # 12-13. The general engine. Everything algorithm-specific arrives through
    # the flx integration; nothing about this run is orchestrated here.
    prepared = prepare_flx_research_run(
        spec=build_flx_canonical500_spec(config),
        preparer_factory=_preparer_factory,
        workspace=workspace,
        dataset_root=dataset_root,
        repository_root=repository_root,
        bundle_root=bundle_root,
        expected_input_set=SD300_CANONICAL500_INPUT_SET,
    )

    # 14-15. The same comparison again, now against a plan that exists.
    final = _rebuild_alignment(
        context=context,
        config=config,
        run_id=prepared.run.run_id,
        plan=prepared.plan,
        result_set_id=None,
    )
    require_clean_alignment(final)
    _write_alignment_report(workspace, prepared.run.run_id, final)
    return prepared


def execute_flx_canonical500_run(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    dataset_root: Path | None = None,
    config: FlxCanonical500ExperimentConfig | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
    max_new_jobs: int | None = None,
    bundle_root: Path | None = None,
) -> RunExecutionSummary:
    """Execute some or all of the prepared run, one comparison at a time.

    May be stopped and resumed as often as necessary. A result that is already
    stored is verified and skipped, never re-executed and never overwritten, so
    resuming cannot change a number that has already been recorded. A resume
    under a different source commit is refused by the engine, because a run
    whose results came from two revisions is not one run (docs/adr/0005,
    docs/adr/0017, spec section 13).
    """
    config = config or load_flx_canonical500_config(repository_root=repository_root)
    return execute_flx_research_run(
        spec=build_flx_canonical500_spec(config),
        preparer_factory=_preparer_factory,
        workspace=Path(workspace),
        dataset_root=dataset_root,
        repository_root=Path(repository_root),
        run_id=run_id,
        max_new_jobs=max_new_jobs,
        bundle_root=bundle_root,
        expected_input_set=SD300_CANONICAL500_INPUT_SET,
    )


def inspect_flx_canonical500_experiment(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    dataset_root: Path | None = None,
    config: FlxCanonical500ExperimentConfig | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
    bundle_root: Path | None = None,
) -> FlxCanonical500ExperimentState:
    """Report where Stage 8C stands. Never writes.

    Both halves are re-derived from the sources rather than read back: the
    research state re-verifies the receipt and the marker against the stored
    results, and the alignment report is rebuilt from the two pair manifests and
    the prepared-set entries. A stored alignment report that was edited *and*
    re-fingerprinted consistently still fails here, because it is compared with
    one derived from the files it describes.

    A dirty working tree does not skip any of it (spec section 23).
    """
    workspace = Path(workspace)
    repository_root = Path(repository_root)
    config = config or load_flx_canonical500_config(repository_root=repository_root)
    spec = build_flx_canonical500_spec(config)

    research_state = inspect_flx_research_experiment(
        spec=spec,
        preparer_factory=_preparer_factory,
        workspace=workspace,
        dataset_root=dataset_root,
        repository_root=repository_root,
        run_id=run_id,
        bundle_root=bundle_root,
        expected_input_set=SD300_CANONICAL500_INPUT_SET,
    )
    report = verify_flx_canonical500_alignment(
        workspace=workspace,
        dataset_root=dataset_root,
        config=config,
        repository_root=repository_root,
        run_id=research_state.run_id,
        require_clean=False,
    )

    issues: list[IntegrityIssue] = []
    issues.extend(_compare_stored_alignment(workspace, research_state.run_id, report))
    issues.extend(
        _check_no_derivations(
            workspace, research_state.run_id, repository_root=repository_root
        )
    )
    return FlxCanonical500ExperimentState(
        research_state=research_state,
        alignment_report=report,
        issues=tuple(issues),
    )


def finalize_flx_canonical500_run(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    dataset_root: Path | None = None,
    config: FlxCanonical500ExperimentConfig | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
    bundle_root: Path | None = None,
) -> ResearchReceipt:
    """Revalidate everything, publish the receipt, and prove the route held.

    The engine does the audit, the result set, the flx validation, the receipt
    and the marker — and it raises unless the run reaches ``RESEARCH_READY``, so
    by the time it returns, that part of Stage 8C readiness is established. What
    this function adds is what the engine has no business knowing about: the
    alignment is re-derived and compared with the one preparation stored, the
    Stage 8B binding is re-checked against the published qualification, and
    nothing downstream of a raw score may exist.

    **Why the combined check is not a second full inspection.** The engine's last
    act is writing the committable receipt into ``evidence/``. A check that
    re-captured software provenance afterwards would refuse the working tree
    finalization had just modified, and would do so on every successful run. The
    independent combined reading is
    :func:`inspect_flx_canonical500_experiment`, run once the evidence has been
    committed (docs/adr/0017).
    """
    workspace = Path(workspace)
    repository_root = Path(repository_root)
    config = config or load_flx_canonical500_config(repository_root=repository_root)
    resolved = run_id or read_run_pointer(workspace, config.experiment_id)
    capture_research_provenance(repository_root)

    require_stage8b_binding(
        config.stage8b, config.artifact, repository_root=repository_root
    )
    context = _load_alignment_context(
        workspace=workspace,
        dataset_root=dataset_root,
        config=config,
        repository_root=repository_root,
        run_id=resolved,
    )
    require_clean_alignment(context.report)
    require_canonical_input_controls_equal(
        context.reference_run,
        build_flx_canonical500_spec(config),
        reference_materialization_policy=context.reference_materialization_policy,
    )
    stored_issues = tuple(
        _compare_stored_alignment(workspace, resolved, context.report)
    )
    if stored_issues:
        raise ResearchPreflightError(
            "the alignment report stored at preparation is not the one this "
            f"workspace now derives: {stored_issues[0].message}"
        )

    receipt = finalize_flx_research_run(
        spec=build_flx_canonical500_spec(config),
        preparer_factory=_preparer_factory,
        workspace=workspace,
        dataset_root=dataset_root,
        repository_root=repository_root,
        run_id=resolved,
        bundle_root=bundle_root,
        expected_input_set=SD300_CANONICAL500_INPUT_SET,
    )

    remaining = tuple(
        _check_no_derivations(workspace, resolved, repository_root=repository_root)
    )
    if remaining or not context.report.is_clean:
        raise ResearchPreflightError(
            f"run {resolved} finalised but Stage 8C is not ready: alignment "
            f"{'clean' if context.report.is_clean else 'not clean'}, "
            f"issues {[issue.message for issue in remaining][:2]}"
        )
    _write_operational_summary(
        workspace=workspace,
        run_id=resolved,
        config=config,
        dataset_root=dataset_root,
        repository_root=repository_root,
        bundle_root=bundle_root,
    )
    return receipt


def refresh_flx_canonical500_stage_finalization(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    dataset_root: Path | None = None,
    config: FlxCanonical500ExperimentConfig | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
    bundle_root: Path | None = None,
) -> Mapping[str, Any]:
    """Re-derive the alignment and the operational summary without rerunning flx.

    The migration path when verifier code changes after a completed run. It
    requires a clean committed verifier tree, rechecks the general research
    chain and every alignment source, rewrites only regenerable Stage 8C
    artefacts, and never opens or executes a raw comparison job.
    """
    workspace = Path(workspace)
    repository_root = Path(repository_root)
    config = config or load_flx_canonical500_config(repository_root=repository_root)
    resolved = run_id or read_run_pointer(workspace, config.experiment_id)
    capture_research_provenance(repository_root)

    state = inspect_flx_canonical500_experiment(
        workspace=workspace,
        dataset_root=dataset_root,
        config=config,
        repository_root=repository_root,
        run_id=resolved,
        bundle_root=bundle_root,
    )
    if not state.research_state.is_research_ready:
        raise ResearchPreflightError(
            f"run {resolved} is not RESEARCH_READY: "
            f"{list(state.research_state.issues)[:3]}"
        )
    report = verify_flx_canonical500_alignment(
        workspace=workspace,
        dataset_root=dataset_root,
        config=config,
        repository_root=repository_root,
        run_id=resolved,
        require_clean=True,
    )
    downstream = tuple(
        _check_no_derivations(workspace, resolved, repository_root=repository_root)
    )
    if downstream:
        raise ResearchPreflightError(
            f"run {resolved} has downstream derivations: "
            f"{[issue.message for issue in downstream][:2]}"
        )
    _write_alignment_report(workspace, resolved, report)
    return _write_operational_summary(
        workspace=workspace,
        run_id=resolved,
        config=config,
        dataset_root=dataset_root,
        repository_root=repository_root,
        bundle_root=bundle_root,
    )


# ------------------------------------------------------------------ evidence


def publish_flx_canonical500_evidence(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    repository_root: Path = REPOSITORY_ROOT,
    config: FlxCanonical500ExperimentConfig | None = None,
    run_id: str | None = None,
) -> tuple[Path, ...]:
    """Copy the committable artefacts out of the workspace.

    Copies; it does not compose — with the one documented exception of the
    operational summary, which was already composed and stored by ``finalize``
    and is copied from there. The receipt, the marker, the alignment report and
    the validation report are already written, already sanitised and already
    fingerprinted; building a second version of any of them here would be
    publishing something no check has ever seen.

    The one file assembled here is ``runtime-provenance.json``, and it is an
    index rather than a claim: every value in it is copied out of the stored run
    definition, the stored runtime reference and the stored alignment report, so
    that a reader can see the route's identity without opening a workspace. It
    carries no score, no threshold and no path.

    ``stage-8c-finalization.json`` is **not** written here. It is the last file
    committed, derived against the Git blobs of the commit that published
    everything else (spec section 37, commits 5 and 6).

    ``README.md`` is written by hand beside them, because a human has to say what
    the run was for.
    """
    workspace = Path(workspace)
    repository_root = Path(repository_root)
    config = config or load_flx_canonical500_config(repository_root=repository_root)
    resolved = run_id or read_run_pointer(workspace, config.experiment_id)

    from fpbench.experiments.operational_summary import OPERATIONAL_SUMMARY_NAME

    result_store = ResultStore(workspace)
    directory = repository_root / EVIDENCE_DIRECTORY
    alignment = read_json(result_store.derived_path(resolved, ALIGNMENT_REPORT_NAME))
    summary = read_json(result_store.derived_path(resolved, OPERATIONAL_SUMMARY_NAME))
    validation = _stored_validation_report(
        workspace=workspace, run_id=resolved, config=config
    )
    written: list[Path] = []
    for name, value in (
        (f"run_{resolved}.json", _run_document(workspace, resolved)),
        ("research-receipt.json", result_store.read_research_receipt(resolved)),
        (
            "research-finalization.json",
            result_store.read_research_finalization(resolved),
        ),
        ("alignment-report.json", alignment),
        ("operational-summary.json", summary),
        ("algorithm-validation.json", validation),
        (
            "runtime-provenance.json",
            _runtime_provenance(
                workspace=workspace,
                run_id=resolved,
                config=config,
                alignment=alignment,
            ),
        ),
    ):
        written.append(write_json(directory / name, value))
    return tuple(written)


def _run_document(workspace: Path, run_id: str) -> Mapping[str, Any]:
    """The stored run definition, published unchanged."""
    return to_plain(ResultStore(workspace).read_run(run_id))


def _stored_validation_report(
    *, workspace: Path, run_id: str, config: FlxCanonical500ExperimentConfig
) -> Mapping[str, Any]:
    """The flx validation pass, re-derived from the stored results.

    Published because the general engine has an independent validation report
    and Stage 8C's carries the two extraction counts and the Decimal check
    (spec section 28). It carries counts and failure codes; it carries no score.
    """
    result_store = ResultStore(workspace)
    run = result_store.read_run(run_id)
    plan = PlanStore(workspace).read_plan(run_id)
    reference = result_store.read_runtime_reference(run_id)
    inputs = load_sd300_inputs(
        workspace=workspace,
        dataset_root=None,
        dataset_config=config.dataset_config,
        protocol_config=config.protocol_config,
        require_verified_checksums=config.require_verified_checksums,
        allow_creation=False,
    )
    report = validate_flx_result_set(
        run=run,
        plan=plan,
        pairs=inputs.pairs,
        images=inputs.images,
        result_store=result_store,
        runtime_reference=reference,
        preparation=None,
        expected_input_set=SD300_CANONICAL500_INPUT_SET,
    )
    published = dict(to_plain(report))
    # The wall clock is the one field that would make two identical passes
    # produce two different documents.
    published.pop("inspected_utc", None)
    return published


def _runtime_provenance(
    *,
    workspace: Path,
    run_id: str,
    config: FlxCanonical500ExperimentConfig,
    alignment: Mapping[str, Any],
) -> dict[str, Any]:
    """What ran, what it ran on, and what it was aligned against.

    Every field is read out of an artefact that is already stored and already
    verified. Nothing is recomputed and nothing is inferred.
    """
    from fpbench.core.research_models import NO_CONCLUSION_STATEMENT

    result_store = ResultStore(workspace)
    run = result_store.read_run(run_id)
    reference = result_store.read_runtime_reference(run_id)
    dependencies = dict(run.environment.dependencies)
    runtime = dict(run.environment.runtime)
    return {
        "schema_version": "1",
        "kind": "stage_8c_runtime_provenance",
        "statement": NO_CONCLUSION_STATEMENT,
        "experiment_id": config.experiment_id,
        "source_commit": runtime.get("fpbench.source.revision"),
        "run_id": run.run_id,
        "run_fingerprint": run.run_fingerprint,
        "algorithm": {
            "algorithm_id": run.algorithm.algorithm_id,
            "adapter_id": run.algorithm.adapter_id,
            "adapter_version": run.algorithm.adapter_version,
            "adapter_contract_version": run.algorithm.adapter_contract_version,
            "implementation_version": run.algorithm.implementation_version,
            "score_direction": run.algorithm.score_direction.value,
            "descriptor_fingerprint": run.algorithm_fingerprint,
        },
        "integration": {
            "integration_id": runtime.get("fpbench.integration.id"),
            "integration_fingerprint": runtime.get("fpbench.integration.fingerprint"),
        },
        "runtime": {
            "bundle_id": reference.bundle_id,
            "bundle_fingerprint": reference.bundle_fingerprint,
            "asset_sha256s": dict(sorted(dict(reference.asset_sha256s).items())),
            "runtime_profile_id": runtime.get("flx.runtime_profile_id"),
            "runtime_manifest_fingerprint": runtime.get(
                "flx.runtime_manifest_fingerprint"
            ),
            "device": runtime.get("flx.device"),
            "torch_num_threads": runtime.get("flx.torch_num_threads"),
            "torch_version": dependencies.get("flx.torch_version"),
            "numpy_version": dependencies.get("flx.numpy_version"),
            "blas_implementation": dependencies.get("flx.blas_implementation"),
            "dependency_lock_sha256": dependencies.get("flx.dependency_lock_sha256"),
        },
        "artifacts": {
            "source_commit": config.artifact.source_commit,
            "source_archive_sha256": config.artifact.source_archive_sha256,
            "checkpoint_filename": config.artifact.checkpoint_filename,
            "checkpoint_sha256": config.artifact.checkpoint_sha256,
            "checkpoint_size_bytes": config.artifact.checkpoint_size_bytes,
            "checkpoint_published": False,
            "weights_license_status": "unresolved",
        },
        "profiles": {
            "preprocessing_profile_fingerprint": dependencies.get(
                "flx.preprocessing_profile_fingerprint"
            ),
            "representation_profile_fingerprint": dependencies.get(
                "flx.representation_profile_fingerprint"
            ),
            "score_profile_fingerprint": dependencies.get(
                "flx.score_profile_fingerprint"
            ),
            "adapter_profile_fingerprint": dependencies.get(
                "flx.adapter_profile_fingerprint"
            ),
        },
        "stage8b": {
            "finalization_fingerprint": config.stage8b.finalization_fingerprint,
            "outcome": config.stage8b.outcome,
        },
        "execution_profile": {
            "profile_id": run.execution_profile.profile_id,
            "profile_hash": run.execution_profile_hash,
            "preparer_id": run.execution_profile.preparer_id,
            "job_deadline_seconds": str(run.execution_profile.timeout_seconds),
            "deterministic_seed": str(run.execution_profile.deterministic_seed),
            "replicate_index": str(run.replicate_index),
            "max_workers": str(config.max_workers),
            "retries": "0",
        },
        "inputs": {
            "protocol_id": run.protocol_id,
            "cohort_id": str(run.cohort_id),
            "pair_manifest_hash": run.pair_manifest_hash,
            "preparation_set_id": config.preparation_set_id,
            "preparation_set_fingerprint": config.preparation_set_fingerprint,
            "transform_profile_id": config.transform_profile_id,
            "transform_profile_fingerprint": config.transform_profile_fingerprint,
            "transform_runtime_fingerprint": config.transform_runtime_fingerprint,
        },
        "reference": {
            "run_id": config.reference.run_id,
            "plan_id": config.reference.plan_id,
            "result_set_id": config.reference.result_set_id,
        },
        "alignment_fingerprint": alignment.get("alignment_fingerprint"),
    }


def publish_flx_canonical500_finalization(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    repository_root: Path = REPOSITORY_ROOT,
    config: FlxCanonical500ExperimentConfig | None = None,
    run_id: str | None = None,
    verifier_source_commit: str,
    created_utc: str | None = None,
) -> Any:
    """Derive the last file, over the exact bytes of the ones already committed.

    Written after everything else is committed, and never beside it. Its content
    hashes are taken over the published files as they sit in the working tree at
    the commit that published them, so the marker binds bytes a reviewer can
    check out rather than bytes only this machine ever saw
    (spec section 26, section 37 commit 6).
    """
    import datetime as _dt

    from fpbench.experiments.stage8c_finalization import (
        STAGE_8C_FINALIZATION_KIND,
        STAGE_8C_FINALIZATION_SCHEMA_VERSION,
        Stage8CFinalization,
        alignment_report_content_hash,
        file_sha256,
        operational_summary_content_hash,
        published_evidence_names,
        require_expected_evidence_files,
        require_no_forbidden_published_data,
        stage_8c_finalization_fingerprint,
    )

    workspace = Path(workspace)
    repository_root = Path(repository_root)
    config = config or load_flx_canonical500_config(repository_root=repository_root)
    resolved = run_id or read_run_pointer(workspace, config.experiment_id)
    directory = repository_root / EVIDENCE_DIRECTORY

    names = tuple(
        name
        for name in published_evidence_names(repository_root)
        if name != STAGE_8C_FINALIZATION_NAME
    )
    run_file = require_expected_evidence_files(names + (STAGE_8C_FINALIZATION_NAME,))
    require_no_forbidden_published_data(repository_root)

    published_binding = require_stage8b_binding(
        config.stage8b, config.artifact, repository_root=repository_root
    )
    result_store = ResultStore(workspace)
    run = result_store.read_run(resolved)
    plan = PlanStore(workspace).read_plan(resolved)
    reference = result_store.read_runtime_reference(resolved)
    result_set = ResultSetStore(workspace).verify_result_set(resolved)
    completion = result_store.read_completion(resolved)
    receipt = result_store.read_research_receipt(resolved)
    research_finalization = result_store.read_research_finalization(resolved)

    alignment = read_json(result_store.derived_path(resolved, ALIGNMENT_REPORT_NAME))
    validation = read_json(directory / "algorithm-validation.json")
    summary = read_json(directory / "operational-summary.json")
    runtime = dict(run.environment.runtime)
    dependencies = dict(run.environment.dependencies)

    claims = {
        "schema_version": STAGE_8C_FINALIZATION_SCHEMA_VERSION,
        "kind": STAGE_8C_FINALIZATION_KIND,
        "outcome": "FLX_CANONICAL500_RAW_READY",
        "stage8b_finalization_fingerprint": published_binding.finalization_fingerprint,
        "stage8b_outcome": published_binding.outcome,
        "algorithm_id": run.algorithm.algorithm_id,
        "integration_id": str(runtime["fpbench.integration.id"]),
        "integration_fingerprint": str(runtime["fpbench.integration.fingerprint"]),
        "source_archive_sha256": config.artifact.source_archive_sha256,
        "checkpoint_sha256": config.artifact.checkpoint_sha256,
        "runtime_bundle_id": reference.bundle_id,
        "runtime_bundle_fingerprint": reference.bundle_fingerprint,
        "runtime_manifest_fingerprint": config.stage8b.runtime_manifest_fingerprint,
        "preprocessing_profile_fingerprint": str(
            dependencies["flx.preprocessing_profile_fingerprint"]
        ),
        "representation_profile_fingerprint": str(
            dependencies["flx.representation_profile_fingerprint"]
        ),
        "score_profile_fingerprint": str(dependencies["flx.score_profile_fingerprint"]),
        "adapter_profile_fingerprint": str(
            dependencies["flx.adapter_profile_fingerprint"]
        ),
        "run_id": run.run_id,
        "run_fingerprint": run.run_fingerprint,
        "plan_id": plan.plan_id,
        "plan_fingerprint": plan.definition.plan_fingerprint,
        "result_set_id": result_set.result_set_id,
        "result_set_fingerprint": result_set.result_set_fingerprint,
        "completion_id": completion.completion_id,
        "completion_fingerprint": completion.completion_fingerprint,
        "run_source_commit": str(runtime["fpbench.source.revision"]),
        "run_source_tree_clean": runtime.get("fpbench.source.clean") == "true",
        "reference_run_id": config.reference.run_id,
        "reference_plan_id": config.reference.plan_id,
        "reference_result_set_id": config.reference.result_set_id,
        "pair_manifest_hash": run.pair_manifest_hash,
        "preparation_set_id": config.preparation_set_id,
        "preparation_set_fingerprint": config.preparation_set_fingerprint,
        "transform_profile_fingerprint": config.transform_profile_fingerprint,
        "transform_runtime_fingerprint": config.transform_runtime_fingerprint,
        "audit_fingerprint": completion.audit_fingerprint,
        "algorithm_validation_fingerprint": str(validation["validation_fingerprint"]),
        "research_receipt_fingerprint": research_receipt_fingerprint(receipt),
        "research_receipt_content_hash": research_receipt_content_hash(receipt),
        "research_finalization_fingerprint": (
            research_finalization.finalization_fingerprint
        ),
        "alignment_fingerprint": str(alignment["alignment_fingerprint"]),
        "alignment_report_content_hash": alignment_report_content_hash(
            read_json(directory / "alignment-report.json")
        ),
        "operational_summary_fingerprint": str(summary["summary_fingerprint"])
        if "summary_fingerprint" in summary
        else operational_summary_content_hash(summary),
        "operational_summary_content_hash": operational_summary_content_hash(summary),
        "planned_count": plan.total_jobs,
        "stored_count": int(validation["total_results"]),
        "success_count": int(validation["successful_results"]),
        "algorithmic_failure_count": int(validation["algorithmic_failures"]),
        "blocking_failure_count": int(validation["blocking_failures"]),
        "preprocess_call_count": int(validation["preprocess_calls"]),
        "logical_extraction_call_count": int(validation["logical_extraction_calls"]),
        "physical_forward_row_count": int(validation["physical_forward_rows"]),
        "comparison_call_count": int(validation["comparison_calls"]),
        "permits_decisions": False,
        "opens_stage_8d": True,
        "prior_result_scores_read": False,
        "score_statistics_published": False,
        "evidence_content_hashes": {
            name: file_sha256(directory / name) for name in sorted(names)
        },
        "verifier_source_commit": str(verifier_source_commit).strip().lower(),
        "verifier_source_tree_clean": True,
    }
    marker = Stage8CFinalization(
        **claims,
        stage_8c_finalization_fingerprint=stage_8c_finalization_fingerprint(claims),
        created_utc=created_utc
        or _dt.datetime.now(_dt.timezone.utc).isoformat(),
    )
    write_json(directory / STAGE_8C_FINALIZATION_NAME, marker)
    del run_file
    return marker


# ------------------------------------------------------- operational summary


def _write_operational_summary(
    *,
    workspace: Path,
    run_id: str,
    config: FlxCanonical500ExperimentConfig,
    dataset_root: Path | None,
    repository_root: Path,
    bundle_root: Path | None,
) -> Mapping[str, Any]:
    """The engine's summary, plus the two extraction counts it cannot know.

    Composed rather than copied, and this is the one document that is. The
    engine's summary is stored and verified; the operation counts come from the
    flx validation report, which measured them over the same stored results. The
    alternative — teaching the generic summary about a batch rule — would put an
    algorithm inside the engine (docs/adr/0075, docs/adr/0007).

    Finalization re-derives this document and compares its content hash, so a
    composed file is no more trusted than a copied one.
    """
    from fpbench.experiments.operational_summary import (
        OPERATIONAL_SUMMARY_NAME,
        build_operational_summary,
    )

    spec = build_flx_canonical500_spec(config)
    result_store = ResultStore(workspace)
    run = result_store.read_run(run_id)
    plan = PlanStore(workspace).read_plan(run_id)
    reference = result_store.read_runtime_reference(run_id)
    inputs = load_sd300_inputs(
        workspace=workspace,
        dataset_root=dataset_root,
        dataset_config=config.dataset_config,
        protocol_config=config.protocol_config,
        require_verified_checksums=config.require_verified_checksums,
        allow_creation=False,
    )
    engine_summary = build_operational_summary(
        run=run,
        plan=plan,
        pairs=inputs.pairs,
        result_store=result_store,
        result_set=_result_set_manifest(workspace, run_id),
        runtime_bundle_id=reference.bundle_id,
    )
    validation = validate_flx_result_set(
        run=run,
        plan=plan,
        pairs=inputs.pairs,
        images=inputs.images,
        result_store=result_store,
        runtime_reference=reference,
        preparation=None,
        expected_input_set=SD300_CANONICAL500_INPUT_SET,
    )
    summary = dict(engine_summary)
    summary["algorithm_operations"] = _algorithm_operations(config, validation)
    write_json(result_store.derived_path(run_id, OPERATIONAL_SUMMARY_NAME), summary)
    del spec, bundle_root, repository_root
    return summary


def _algorithm_operations(
    config: FlxCanonical500ExperimentConfig, validation: Any
) -> dict[str, Any]:
    """Both extraction counts, and the rule that makes them different.

    A reader never has to know docs/adr/0070 to interpret the numbers, because
    the rule that produced the second one is printed beside it (docs/adr/0075).
    """
    from fpbench.flx import identity as flx_identity

    return {
        "planned": {
            "preprocess_calls": config.operations.planned_preprocess_calls,
            "logical_extraction_calls": config.operations.planned_logical_extractions,
            "physical_forward_rows": config.operations.planned_physical_forward_rows,
            "comparison_calls": config.operations.planned_comparison_calls,
        },
        "measured": {
            "preprocess_calls": validation.preprocess_calls,
            "logical_extraction_calls": validation.logical_extraction_calls,
            "physical_forward_rows": validation.physical_forward_rows,
            "comparison_calls": validation.comparison_calls,
        },
        "batch_rule": {
            "inference_batch_rows": flx_identity.INFERENCE_BATCH_ROWS,
            "inference_batch_rule": flx_identity.INFERENCE_BATCH_RULE,
            "represented_row": flx_identity.REPRESENTED_ROW,
            "statement": (
                "one logical extraction is one representation and two physical "
                "forward rows; the two counts are never conflated "
                "(docs/adr/0070, docs/adr/0075)"
            ),
        },
        "worker": {
            "max_workers": config.max_workers,
            "job_deadline_seconds": config.job_deadline_seconds,
            "retries": 0,
        },
    }


def _result_set_manifest(workspace: Path, run_id: str) -> Any:
    try:
        return ResultSetStore(workspace).read_manifest(run_id)
    except Exception:  # pragma: no cover - absent before finalization
        return None


# ----------------------------------------------------------------- internals


@dataclass(frozen=True, slots=True)
class _AlignmentContext:
    """Everything one alignment pass loaded, kept so it is loaded once.

    Verifying the prepared set re-reads and re-hashes 3,000 PNGs, and loading
    the reference run re-verifies its whole evidence chain. Preparation needs
    the comparison twice — once before the run exists and once against the plan
    that now does — and doing all of that twice would be minutes of work to
    reach an answer already in memory.
    """

    inputs: SD300Inputs
    prepared_entries: Mapping[str, PreparedImageEntry]
    reference_run: Any
    reference_side: Any
    reference_materialization_policy: str | None
    report: CanonicalRunAlignmentReport


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


def _load_alignment_context(
    *,
    workspace: Path,
    dataset_root: Path | None,
    config: FlxCanonical500ExperimentConfig,
    repository_root: Path,
    run_id: str | None,
) -> _AlignmentContext:
    """Load both sides once, from the manifests, and compare them."""
    spec = build_flx_canonical500_spec(config)

    # The pair manifest is *read*. ``allow_creation=False`` is what makes that
    # true rather than intended: with it, a workspace missing the manifest is an
    # error instead of an invitation to build a new one (spec section 21).
    inputs = load_sd300_inputs(
        workspace=workspace,
        dataset_root=dataset_root,
        dataset_config=config.dataset_config,
        protocol_config=config.protocol_config,
        require_verified_checksums=config.require_verified_checksums,
        allow_creation=False,
    )
    if inputs.pair_manifest_hash != config.reference_pair_manifest_hash:
        raise ResearchPreflightError(
            f"the workspace pair manifest hashes to "
            f"{inputs.pair_manifest_hash[:12]}..., but Stage 8C is defined "
            f"against {config.reference_pair_manifest_hash[:12]}..."
        )
    if str(inputs.cohort.cohort_id) != config.reference_cohort_id:
        raise ResearchPreflightError(
            f"the workspace cohort is {inputs.cohort.cohort_id}, but Stage 8C is "
            f"defined against {config.reference_cohort_id}"
        )

    preparer = _preparer_factory(workspace, spec)
    preparer.preflight()
    entries = preparer.prepared_entries()
    runtime_fingerprint = str(
        preparer.run_metadata().get("transform_runtime_fingerprint")
    )
    if runtime_fingerprint != config.transform_runtime_fingerprint:
        raise ResearchPreflightError(
            f"the prepared set was materialised by transform runtime "
            f"{runtime_fingerprint[:12]}..., but Stage 8C is defined against "
            f"{config.transform_runtime_fingerprint[:12]}..."
        )

    reference_state = _reference_research_state(
        workspace=workspace,
        dataset_root=dataset_root,
        repository_root=repository_root,
    )
    reference_side = load_reference_alignment_side(
        workspace=workspace,
        expected=config.reference,
        research_state=reference_state,
    )

    plan = None
    result_set_id = None
    if run_id:
        plan = PlanStore(workspace).read_plan(run_id)
        result_set_id = _result_set_id(workspace, run_id)

    candidate_side = load_candidate_alignment_side(
        pairs=inputs.pairs,
        pair_manifest_hash=inputs.pair_manifest_hash,
        protocol_id=inputs.protocol.protocol_id,
        cohort_id=str(inputs.cohort.cohort_id),
        preparation_set_id=config.preparation_set_id,
        preparation_set_fingerprint=config.preparation_set_fingerprint,
        prepared_entries=entries,
        images=inputs.images,
        plan=plan,
        run_id=run_id,
        result_set_id=result_set_id,
    )
    report = build_canonical_run_alignment_report(
        reference=reference_side,
        candidate=candidate_side,
        expected_reference=config.reference,
        expectations=config.alignment_expectations,
    )

    reference_run = ResultStore(workspace).read_run(config.reference.run_id)
    return _AlignmentContext(
        inputs=inputs,
        prepared_entries=entries,
        reference_run=reference_run,
        reference_side=reference_side,
        reference_materialization_policy=_materialization_policy(
            workspace, config.reference.run_id
        ),
        report=report,
    )


def _rebuild_alignment(
    *,
    context: _AlignmentContext,
    config: FlxCanonical500ExperimentConfig,
    run_id: str,
    plan: Any,
    result_set_id: str | None,
) -> CanonicalRunAlignmentReport:
    """The same comparison, restated against a plan that now exists.

    Cheap, because both sides are already in memory. It matters because the
    order checked before ``prepare`` was the order the planner *would* impose,
    and this is the order it did (spec section 21, step 14).
    """
    candidate_side = load_candidate_alignment_side(
        pairs=context.inputs.pairs,
        pair_manifest_hash=context.inputs.pair_manifest_hash,
        protocol_id=context.inputs.protocol.protocol_id,
        cohort_id=str(context.inputs.cohort.cohort_id),
        preparation_set_id=config.preparation_set_id,
        preparation_set_fingerprint=config.preparation_set_fingerprint,
        prepared_entries=context.prepared_entries,
        images=context.inputs.images,
        plan=plan,
        run_id=run_id,
        result_set_id=result_set_id,
    )
    return build_canonical_run_alignment_report(
        reference=context.reference_side,
        candidate=candidate_side,
        expected_reference=config.reference,
        expectations=config.alignment_expectations,
    )


def _reference_research_state(
    *,
    workspace: Path,
    dataset_root: Path | None,
    repository_root: Path,
) -> ResearchRunState:
    """Ask the reference experiment's own wrapper how its run is doing.

    Imported here rather than at module scope so that the dependency is visibly
    one function wide. Stage 8C reads the reference run's *readiness*; it does
    not import its adapter, its decision profile or its scores (spec section 18).
    """
    from fpbench.experiments.sourceafis_canonical500_full import (
        inspect_sourceafis_canonical500_run,
    )

    return inspect_sourceafis_canonical500_run(
        workspace=workspace,
        dataset_root=dataset_root,
        repository_root=repository_root,
    )


def _materialization_policy(workspace: Path, run_id: str) -> str | None:
    try:
        reference = ResultStore(workspace).read_runtime_reference(run_id)
        return (
            RuntimeBundleStore(workspace)
            .read_bundle(reference.bundle_id)
            .materialization_policy
        )
    except Exception:  # pragma: no cover - absence is reported by the alignment
        return None


def _result_set_id(workspace: Path, run_id: str) -> str | None:
    try:
        return ResultSetStore(workspace).read_manifest(run_id).result_set_id
    except Exception:
        return None


def _write_alignment_report(
    workspace: Path, run_id: str, report: CanonicalRunAlignmentReport
) -> Path:
    return ResultStore(workspace).write_derived(run_id, ALIGNMENT_REPORT_NAME, report)


def _compare_stored_alignment(
    workspace: Path, run_id: str, derived: CanonicalRunAlignmentReport
) -> list[IntegrityIssue]:
    """The stored report must be the one the files still produce."""
    from fpbench.core.enums import IntegrityIssueCode, IntegritySeverity

    path = ResultStore(workspace).derived_path(run_id, ALIGNMENT_REPORT_NAME)
    if not path.is_file():
        return [
            IntegrityIssue(
                code=IntegrityIssueCode.PLAN_CONFLICT,
                severity=IntegritySeverity.ERROR,
                message=(
                    f"run {run_id} carries no stored alignment report; preparation "
                    "writes one and finalization compares against it"
                ),
            )
        ]
    stored = read_json(path)
    issues: list[IntegrityIssue] = []
    try:
        expectations = _alignment_expectations_from_plain(stored.get("expectations"))
    except (KeyError, TypeError, ValueError) as exc:
        return [
            IntegrityIssue(
                code=IntegrityIssueCode.PLAN_CONFLICT,
                severity=IntegritySeverity.ERROR,
                message=f"the stored alignment expectations are invalid: {exc}",
                relative_path=str(path.relative_to(workspace)),
            )
        ]
    recomputed = canonical_run_alignment_fingerprint(
        reference_run_id=str(stored.get("reference_run_id")),
        reference_plan_id=str(stored.get("reference_plan_id")),
        reference_result_set_id=str(stored.get("reference_result_set_id")),
        candidate_run_id=stored.get("candidate_run_id"),
        candidate_plan_id=stored.get("candidate_plan_id"),
        pair_manifest_hash=str(stored.get("pair_manifest_hash")),
        preparation_set_id=str(stored.get("preparation_set_id")),
        preparation_set_fingerprint=str(stored.get("preparation_set_fingerprint")),
        reference_pair_count=int(stored.get("reference_pair_count", -1)),
        candidate_pair_count=int(stored.get("candidate_pair_count", -1)),
        equal_pair_ids=int(stored.get("equal_pair_ids", -1)),
        equal_pair_semantics=int(stored.get("equal_pair_semantics", -1)),
        reference_prepared_entries=int(stored.get("reference_prepared_entries", -1)),
        candidate_prepared_entries=int(stored.get("candidate_prepared_entries", -1)),
        equal_prepared_entries=int(stored.get("equal_prepared_entries", -1)),
        pair_id_sequence_sha256=str(stored.get("pair_id_sequence_sha256")),
        pair_semantics_sha256=str(stored.get("pair_semantics_sha256")),
        prepared_entries_sha256=str(stored.get("prepared_entries_sha256")),
        issues=_issues_from_plain(stored.get("issues") or []),
        expectations=expectations,
    )
    if recomputed != stored.get("alignment_fingerprint"):
        issues.append(
            IntegrityIssue(
                code=IntegrityIssueCode.PLAN_CONFLICT,
                severity=IntegritySeverity.ERROR,
                message=(
                    "the stored alignment report does not fingerprint to what it "
                    "carries; it has been edited since it was written"
                ),
            )
        )
    if expectations != derived.expectations:
        issues.append(
            IntegrityIssue(
                code=IntegrityIssueCode.PLAN_CONFLICT,
                severity=IntegritySeverity.ERROR,
                message=(
                    "the stored alignment expectations are not the experiment "
                    "shape this workspace now derives"
                ),
                relative_path=str(path.relative_to(workspace)),
            )
        )
    if stored.get("alignment_fingerprint") != derived.alignment_fingerprint:
        issues.append(
            IntegrityIssue(
                code=IntegrityIssueCode.PLAN_CONFLICT,
                severity=IntegritySeverity.ERROR,
                message=(
                    "the stored alignment report is not the one this workspace now "
                    f"derives ({str(stored.get('alignment_fingerprint'))[:12]}... "
                    f"vs {derived.alignment_fingerprint[:12]}...)"
                ),
            )
        )
    return issues


def _alignment_expectations_from_plain(value: Any) -> AlignmentExpectations:
    if not isinstance(value, Mapping):
        raise TypeError("expectations must be an object")
    return AlignmentExpectations(
        pair_count=int(value["pair_count"]),
        prepared_entry_count=int(value["prepared_entry_count"]),
        pairs_per_release_stage=int(value["pairs_per_release_stage"]),
        prepared_entries_per_release=int(value["prepared_entries_per_release"]),
        releases=tuple(value["releases"]),
    )


def _issues_from_plain(items: Any) -> tuple[IntegrityIssue, ...]:
    from fpbench.core.enums import IntegrityIssueCode, IntegritySeverity

    rebuilt: list[IntegrityIssue] = []
    for item in items or ():
        rebuilt.append(
            IntegrityIssue(
                code=IntegrityIssueCode(item["code"]),
                severity=IntegritySeverity(item["severity"]),
                message=str(item["message"]),
                job_id=item.get("job_id"),
                relative_path=item.get("relative_path"),
                details=dict(item.get("details") or {}),
            )
        )
    return tuple(rebuilt)


def _check_no_derivations(
    workspace: Path,
    run_id: str,
    *,
    permitted_experiments: frozenset[str] | None = None,
    repository_root: Path = REPOSITORY_ROOT,
) -> list[IntegrityIssue]:
    """Nothing derives from this run, because nothing is entitled to yet.

    Stage 8C produces raw scores and nothing else. A decision set over them
    would mean somebody chose a threshold for the flx scale, and there is no
    such threshold to choose: Stage 8D must freeze its source, comparator and
    boundary semantics in a separate prior act, and may not choose one from
    these scores (docs/adr/0076, spec sections 27 and 39).

    The allowlist is data rather than a wildcard, so the day Stage 8D pins a
    profile the rule becomes "accounted for by a named experiment" without this
    function changing shape — which is exactly how Stage 7C's equivalent aged.

    The check uses the real models and stores. A filename search would pass a
    directory somebody renamed (spec section 27).
    """
    from fpbench.core.derivation_models import DerivationDefinition
    from fpbench.core.enums import IntegrityIssueCode, IntegritySeverity
    from fpbench.core.errors import StorageError
    from fpbench.core.evaluation_models import MetricDerivationDefinition
    from fpbench.storage import layout
    from fpbench.storage.paired_evaluation_store import PairedEvaluationStore

    if permitted_experiments is None:
        permitted_experiments = PERMITTED_DOWNSTREAM_EXPERIMENTS

    issues: list[IntegrityIssue] = []
    derivations_root = layout.derivations_root(workspace)
    accounted_for = False
    if derivations_root.is_dir():
        for path in sorted(derivations_root.rglob("definition.json")):
            try:
                payload = read_json(path)
                definition = _load_downstream_definition(
                    payload,
                    decision_model=DerivationDefinition,
                    metric_model=MetricDerivationDefinition,
                )
            except (OSError, StorageError, TypeError, ValueError) as exc:
                issues.append(
                    IntegrityIssue(
                        code=IntegrityIssueCode.PLAN_CONFLICT,
                        severity=IntegritySeverity.ERROR,
                        message=f"unreadable downstream definition: {exc}",
                        relative_path=path.relative_to(workspace).as_posix(),
                    )
                )
                continue
            if definition.run_id != run_id:
                continue
            owner = _owning_experiment_id(path, derivations_root)
            if owner in permitted_experiments:
                accounted_for = True
                continue
            kind = (
                "decision/eligibility"
                if isinstance(definition, DerivationDefinition)
                else "metric"
            )
            issues.append(
                IntegrityIssue(
                    code=IntegrityIssueCode.PLAN_CONFLICT,
                    severity=IntegritySeverity.ERROR,
                    message=(
                        f"{kind} definition {definition.definition_id} derives "
                        f"from run {run_id} under experiment {owner!r}; Stage 8C "
                        "permits no downstream derivation at all "
                        "(docs/adr/0076)"
                    ),
                    relative_path=path.relative_to(workspace).as_posix(),
                )
            )

    run_directory = ResultStore(workspace).run_dir(run_id)
    if not accounted_for:
        for name in ("decisions", "metrics", "eligibility"):
            path = run_directory / name
            if path.exists():
                issues.append(
                    IntegrityIssue(
                        code=IntegrityIssueCode.PLAN_CONFLICT,
                        severity=IntegritySeverity.ERROR,
                        message=(
                            f"run {run_id} carries a {name}/ directory that no "
                            "pinned derivation accounts for; a threshold was "
                            "applied outside an experiment (docs/adr/0076)"
                        ),
                        relative_path=f"results/{run_id}/{name}",
                    )
                )

    paired_store = PairedEvaluationStore(workspace)
    if paired_store.paired_root.is_dir():
        try:
            run_fingerprint = ResultStore(workspace).read_run(run_id).run_fingerprint
        except StorageError as exc:
            issues.append(
                IntegrityIssue(
                    code=IntegrityIssueCode.PLAN_CONFLICT,
                    severity=IntegritySeverity.ERROR,
                    message=f"cannot identify run {run_id} for paired checks: {exc}",
                )
            )
            return issues
        for directory in sorted(paired_store.paired_root.iterdir()):
            paired_id = directory.name
            if not paired_store.definition_path(paired_id).is_file():
                continue
            relative = (
                paired_store.definition_path(paired_id)
                .relative_to(workspace)
                .as_posix()
            )
            try:
                if paired_store.has_receipt(paired_id):
                    receipt = paired_store.read_receipt(paired_id)
                    cites_run = run_id in {
                        receipt.native_run_id,
                        receipt.canonical_run_id,
                    }
                else:
                    definition = paired_store.read_definition(paired_id)
                    cites_run = run_fingerprint in {
                        definition.native_run_fingerprint,
                        definition.canonical_run_fingerprint,
                    }
            except StorageError as exc:
                issues.append(
                    IntegrityIssue(
                        code=IntegrityIssueCode.PLAN_CONFLICT,
                        severity=IntegritySeverity.ERROR,
                        message=f"unreadable paired evaluation: {exc}",
                        relative_path=relative,
                    )
                )
                continue
            if cites_run:
                issues.append(
                    IntegrityIssue(
                        code=IntegrityIssueCode.PLAN_CONFLICT,
                        severity=IntegritySeverity.ERROR,
                        message=(
                            f"paired evaluation {paired_id} cites run {run_id}; "
                            "Stage 8C has no paired evaluation"
                        ),
                        relative_path=relative,
                    )
                )

    issues.extend(check_no_cross_algorithm_comparison(repository_root, run_id))
    return issues


def check_no_cross_algorithm_comparison(
    repository_root: Path, run_id: str
) -> list[IntegrityIssue]:
    """No comparison of this run against SourceAFIS or NBIS exists.

    Stage 7D built the cross-algorithm machinery, and it is exactly what must
    not be pointed at these scores: a comparison needs both sides to have
    decisions, and the flx side has none because no threshold exists for its
    scale (docs/adr/0076, spec section 27).

    A published comparison is a bundle under ``evidence/``, not a workspace
    store, so that is where this looks. Each candidate is parsed with the real
    :class:`~fpbench.core.cross_algorithm_models.CrossAlgorithmEvaluationDefinition`
    and its two named run ids are compared — never a text search of the file and
    never the directory's name (spec section 27).
    """
    from fpbench.core.cross_algorithm_models import CrossAlgorithmEvaluationDefinition
    from fpbench.core.enums import IntegrityIssueCode, IntegritySeverity
    from fpbench.core.errors import StorageError

    issues: list[IntegrityIssue] = []
    evidence_root = Path(repository_root) / "evidence"
    if not evidence_root.is_dir():
        return issues
    for path in sorted(evidence_root.glob("*/algcompare_*.json")):
        relative = path.relative_to(repository_root).as_posix()
        try:
            payload = read_json(path)
            definition = CrossAlgorithmEvaluationDefinition(
                **dict(payload["definition"])
            )
        except (OSError, StorageError, KeyError, TypeError, ValueError) as exc:
            issues.append(
                IntegrityIssue(
                    code=IntegrityIssueCode.PLAN_CONFLICT,
                    severity=IntegritySeverity.ERROR,
                    message=f"unreadable cross-algorithm definition: {exc}",
                    relative_path=relative,
                )
            )
            continue
        if run_id in {definition.left_run_id, definition.right_run_id}:
            issues.append(
                IntegrityIssue(
                    code=IntegrityIssueCode.PLAN_CONFLICT,
                    severity=IntegritySeverity.ERROR,
                    message=(
                        f"cross-algorithm comparison {definition.definition_id} "
                        f"cites run {run_id}; Stage 8C publishes no comparison "
                        "with another algorithm (docs/adr/0076)"
                    ),
                    relative_path=relative,
                )
            )
    return issues


def _owning_experiment_id(definition_path: Path, derivations_root: Path) -> str:
    """Which experiment's directory a definition file sits under."""
    try:
        relative = definition_path.relative_to(derivations_root)
    except ValueError:  # pragma: no cover - the caller globbed from this root
        return ""
    return relative.parts[0] if relative.parts else ""


def _load_downstream_definition(
    payload: Mapping[str, Any], *, decision_model: Any, metric_model: Any
) -> Any:
    from fpbench.core.errors import StorageError

    errors: list[str] = []
    for model in (decision_model, metric_model):
        try:
            return model(**payload)
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"{model.__name__}: {exc}")
    raise StorageError("; ".join(errors))


def _require_frozen(label: str, value: Any, expected: Any, path: Path) -> None:
    if value != expected:
        raise ConfigurationError(
            f"{path}: {label} is {value!r}, but Stage 8C is frozen against "
            f"{expected!r}. Changing it is a different experiment, not a "
            "correction to this one (spec section 3)"
        )


def _require_digest(value: str, where: str) -> str:
    digest = str(value).strip().lower()
    if len(digest) != 64 or not set(digest) <= _HEX:
        raise ConfigurationError(
            f"{where} must be a 64-character hexadecimal digest"
        )
    return digest


def _require_reporting_switches(reporting: Mapping[str, Any], path: Path) -> None:
    """Exactly four switches, each with exactly one permitted value."""
    for key, required in sorted(REQUIRED_REPORTING_SWITCHES.items()):
        actual = require_yaml_bool(reporting, key, where=f"{path} reporting")
        if actual is not required:
            raise ConfigurationError(
                f"{path}: reporting.{key} must be {str(required).lower()}. Stage 8C "
                "publishes stored comparison outcomes and operational counts; a "
                "rate, a score distribution or an exported score row is a "
                "biometric claim and needs definitions this stage does not have "
                "(docs/adr/0076)"
            )


def _require_execution_controls(execution: Mapping[str, Any], path: Path) -> None:
    if not require_yaml_bool(execution, "sequential", where=f"{path} execution"):
        raise ConfigurationError(
            f"{path}: this run is sequential. One worker holds the model; two "
            "would double the peak RAM and make the order of results depend on "
            "scheduling (spec section 12)"
        )
    if require_yaml_exact_int(execution, "max_workers", where=f"{path} execution") != 1:
        raise ConfigurationError(
            f"{path}: this run uses exactly one worker (spec section 11)"
        )
    if require_yaml_exact_int(execution, "retries", where=f"{path} execution") != 0:
        raise ConfigurationError(
            f"{path}: this run performs no retries. A failed comparison is a "
            "recorded outcome, and re-running only the failures would produce a "
            "run whose results came from two attempts (docs/adr/0013)"
        )


def _load_stage8b_binding(
    stage8b: Mapping[str, Any], path: Path, frozen: Any
) -> Stage8BBinding:
    where = f"{path} stage8b"
    values = {
        "finalization_fingerprint": _require_digest(
            require_yaml_non_empty_str(stage8b, "finalization_fingerprint", where=where),
            f"{where}.finalization_fingerprint",
        ),
        "outcome": require_yaml_non_empty_str(stage8b, "outcome", where=where),
        "algorithm_id": require_yaml_non_empty_str(stage8b, "algorithm_id", where=where),
        "adapter_id": require_yaml_non_empty_str(stage8b, "adapter_id", where=where),
        "adapter_version": require_yaml_exact_int(
            stage8b, "adapter_version", where=where, minimum=1
        ),
        "runtime_profile_id": require_yaml_non_empty_str(
            stage8b, "runtime_profile_id", where=where
        ),
        "runtime_manifest_fingerprint": _require_digest(
            require_yaml_non_empty_str(
                stage8b, "runtime_manifest_fingerprint", where=where
            ),
            f"{where}.runtime_manifest_fingerprint",
        ),
        "preprocessing_profile_id": require_yaml_non_empty_str(
            stage8b, "preprocessing_profile_id", where=where
        ),
        "preprocessing_profile_fingerprint": _require_digest(
            require_yaml_non_empty_str(
                stage8b, "preprocessing_profile_fingerprint", where=where
            ),
            f"{where}.preprocessing_profile_fingerprint",
        ),
        "representation_profile_id": require_yaml_non_empty_str(
            stage8b, "representation_profile_id", where=where
        ),
        "representation_profile_fingerprint": _require_digest(
            require_yaml_non_empty_str(
                stage8b, "representation_profile_fingerprint", where=where
            ),
            f"{where}.representation_profile_fingerprint",
        ),
        "score_profile_id": require_yaml_non_empty_str(
            stage8b, "score_profile_id", where=where
        ),
        "score_profile_fingerprint": _require_digest(
            require_yaml_non_empty_str(stage8b, "score_profile_fingerprint", where=where),
            f"{where}.score_profile_fingerprint",
        ),
        "adapter_profile_fingerprint": _require_digest(
            require_yaml_non_empty_str(
                stage8b, "adapter_profile_fingerprint", where=where
            ),
            f"{where}.adapter_profile_fingerprint",
        ),
    }
    for label, expected in (
        ("finalization_fingerprint", frozen.STAGE8B_FINALIZATION_FINGERPRINT),
        ("outcome", frozen.STAGE8B_OUTCOME),
        ("algorithm_id", frozen.ALGORITHM_ID),
        ("adapter_id", frozen.ADAPTER_ID),
        ("adapter_version", frozen.ADAPTER_VERSION),
        ("runtime_profile_id", frozen.RUNTIME_PROFILE_ID),
        ("runtime_manifest_fingerprint", frozen.RUNTIME_MANIFEST_FINGERPRINT),
        ("preprocessing_profile_id", frozen.PREPROCESSING_PROFILE_ID),
        ("preprocessing_profile_fingerprint", frozen.PREPROCESSING_PROFILE_FINGERPRINT),
        ("representation_profile_id", frozen.REPRESENTATION_PROFILE_ID),
        (
            "representation_profile_fingerprint",
            frozen.REPRESENTATION_PROFILE_FINGERPRINT,
        ),
        ("score_profile_id", frozen.SCORE_PROFILE_ID),
        ("score_profile_fingerprint", frozen.SCORE_PROFILE_FINGERPRINT),
        ("adapter_profile_fingerprint", frozen.ADAPTER_PROFILE_FINGERPRINT),
    ):
        _require_frozen(f"stage8b.{label}", values[label], expected, path)
    return Stage8BBinding(**values)


def _load_artifact_identity(
    artifact: Mapping[str, Any], path: Path, frozen: Any
) -> FlxArtifactIdentity:
    where = f"{path} artifact"
    identity = FlxArtifactIdentity(
        source_commit=require_yaml_non_empty_str(artifact, "source_commit", where=where),
        source_archive_sha256=_require_digest(
            require_yaml_non_empty_str(artifact, "source_archive_sha256", where=where),
            f"{where}.source_archive_sha256",
        ),
        checkpoint_filename=require_yaml_non_empty_str(
            artifact, "checkpoint_filename", where=where
        ),
        checkpoint_sha256=_require_digest(
            require_yaml_non_empty_str(artifact, "checkpoint_sha256", where=where),
            f"{where}.checkpoint_sha256",
        ),
        checkpoint_size_bytes=require_yaml_exact_int(
            artifact, "checkpoint_size_bytes", where=where, minimum=1
        ),
    )
    for label, value, expected in (
        ("artifact.source_commit", identity.source_commit, frozen.SOURCE_COMMIT),
        (
            "artifact.source_archive_sha256",
            identity.source_archive_sha256,
            frozen.SOURCE_ARCHIVE_SHA256,
        ),
        (
            "artifact.checkpoint_filename",
            identity.checkpoint_filename,
            frozen.CHECKPOINT_FILENAME,
        ),
        (
            "artifact.checkpoint_sha256",
            identity.checkpoint_sha256,
            frozen.CHECKPOINT_SHA256,
        ),
        (
            "artifact.checkpoint_size_bytes",
            identity.checkpoint_size_bytes,
            frozen.CHECKPOINT_SIZE_BYTES,
        ),
    ):
        _require_frozen(label, value, expected, path)
    return identity


def _load_operation_counts(
    operations: Mapping[str, Any], path: Path, frozen: Any, *, jobs: int
) -> FlxOperationCounts:
    where = f"{path} operations"
    counts = FlxOperationCounts(
        preprocess_calls_per_comparison=require_yaml_exact_int(
            operations, "preprocess_calls_per_comparison", where=where, minimum=1
        ),
        logical_extractions_per_comparison=require_yaml_exact_int(
            operations, "logical_extractions_per_comparison", where=where, minimum=1
        ),
        comparisons_per_job=require_yaml_exact_int(
            operations, "comparisons_per_job", where=where, minimum=1
        ),
        inference_batch_rows=require_yaml_exact_int(
            operations, "inference_batch_rows", where=where, minimum=1
        ),
        inference_batch_rule=require_yaml_non_empty_str(
            operations, "inference_batch_rule", where=where
        ),
        represented_row=require_yaml_exact_int(
            operations, "represented_row", where=where, minimum=0
        ),
        jobs=jobs,
    )
    for label, value, expected in (
        (
            "operations.preprocess_calls_per_comparison",
            counts.preprocess_calls_per_comparison,
            frozen.PREPROCESS_CALLS_PER_COMPARISON,
        ),
        (
            "operations.logical_extractions_per_comparison",
            counts.logical_extractions_per_comparison,
            frozen.LOGICAL_EXTRACTIONS_PER_COMPARISON,
        ),
        (
            "operations.comparisons_per_job",
            counts.comparisons_per_job,
            frozen.COMPARISONS_PER_JOB,
        ),
        (
            "operations.inference_batch_rows",
            counts.inference_batch_rows,
            frozen.INFERENCE_BATCH_ROWS,
        ),
    ):
        _require_frozen(label, value, expected, path)
    # Asserted against Stage 8B's own frozen rule rather than restated: the
    # doubling is a property of the pinned texture branch (docs/adr/0070).
    from fpbench.flx import identity as flx_identity

    if counts.inference_batch_rule != flx_identity.INFERENCE_BATCH_RULE:
        raise ConfigurationError(
            f"{path}: operations.inference_batch_rule is "
            f"{counts.inference_batch_rule!r}, but the qualified route uses "
            f"{flx_identity.INFERENCE_BATCH_RULE!r}"
        )
    if counts.represented_row != flx_identity.REPRESENTED_ROW:
        raise ConfigurationError(
            f"{path}: operations.represented_row is {counts.represented_row}, but "
            f"the qualified route represents row {flx_identity.REPRESENTED_ROW}"
        )
    return counts


def _load_execution_profile(path: Path) -> ExecutionProfile:
    """Read the Stage 8C execution profile.

    The same reader Stage 7C uses, for the same reason: every parameter is a
    string, because the profile hash is taken over exactly those strings.
    """
    from fpbench.core.serialization import require_exact_int

    path = Path(path)
    if not path.is_file():
        raise ConfigurationError(f"execution profile config not found: {path}")
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(document, Mapping):
        raise ConfigurationError(f"{path}: expected a mapping at the top level")
    _require_no_decision_keys(document, path)
    profile = document.get("profile")
    if not isinstance(profile, Mapping):
        raise ConfigurationError(f"{path}: missing or malformed 'profile' section")
    parameters = {
        str(key): str(value)
        for key, value in dict(document.get("parameters") or {}).items()
    }
    return ExecutionProfile(
        profile_id=str(profile["profile_id"]),
        preparer_id=str(profile["preparer_id"]),
        timeout_seconds=float(profile["timeout_seconds"]),
        deterministic_seed=require_exact_int(
            profile.get("deterministic_seed", 0), "deterministic_seed"
        ),
        parameters=parameters,
    )


def _require_no_decision_keys(document: Any, path: Path, trail: str = "") -> None:
    """Refuse a threshold-shaped key anywhere in the document, at any depth.

    ``reporting.score_statistics`` is the single fixed exception, and only at
    that exact position with that exact parent: it is a switch that must be
    present and must be ``false``, so refusing the name outright would make the
    required document unloadable (spec section 17).
    """
    if isinstance(document, Mapping):
        for key, value in document.items():
            name = str(key)
            where = f"{trail}.{name}" if trail else name
            if name.lower() in FORBIDDEN_CONFIG_KEYS and where != (
                "reporting.score_statistics"
            ):
                raise ConfigurationError(
                    f"{path}: {where!r} is not a Stage 8C setting. This stage "
                    "publishes stored comparison outcomes; where the boundary "
                    "between MATCH and NON_MATCH sits on the flx scale is stage "
                    "8D's question, and it may not be answered from the SD300 "
                    "scores this run produces (docs/adr/0076)"
                )
            _require_no_decision_keys(value, path, where)
    elif isinstance(document, (list, tuple)):
        for index, item in enumerate(document):
            _require_no_decision_keys(item, path, f"{trail}[{index}]")
