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

from fpbench.core.errors import ConfigurationError
from fpbench.core.execution_models import ExecutionProfile
from fpbench.core.identifiers import validate_id
from fpbench.core.research_models import ResearchRunState
from fpbench.core.run_state_models import IntegrityIssue
from fpbench.experiments.algorithm_research import (
    REPOSITORY_ROOT,
    AlgorithmResearchExperimentSpec,
)
from fpbench.experiments.canonical_run_alignment import (
    SD300_CANONICAL_EXPECTATIONS,
    AlignmentExpectations,
    CanonicalRunAlignmentReport,
    ReferenceRunIdentity,
)
from fpbench.experiments.config_values import (
    reject_unknown_keys,
    require_yaml_bool,
    require_yaml_exact_int,
    require_yaml_mapping,
    require_yaml_non_empty_str,
)
from fpbench.experiments.stage8c_identity import (
    ALIGNMENT_REPORT_NAME,
    EVIDENCE_DIRECTORY,
    EXPERIMENT_ID,
    FORBIDDEN_CONFIG_KEYS,
    PERMITTED_DOWNSTREAM_EXPERIMENTS,
    REQUIRED_REPORTING_SWITCHES,
    STAGE_8C_FINALIZATION_NAME,
)

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


# ----------------------------------------------------------------- internals


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
