"""The 6,000 canonical SD300 comparisons, run again by the qualified VeriFinger route.

Everything that decides *what* is compared was decided in Stage 6A and is read
back here unchanged: the protocol, the cohort, the 6,000-row pair manifest, its
order, and the 3,000 immutable 500 ppi PNGs. Nothing in this module selects a
cohort, generates a pair, resamples an image or writes a PNG.

What is new is the algorithm, and only the algorithm::

    canonical gray8 500 ppi PNG
      -> VeriFinger 2025.2, through upstream's own Java binding
      -> verify(reference, candidate) in its own JVM
      -> one native integer score

driven by the route Stage 11A qualified, through the orchestration Stage 7A
extracted. This module contains no orchestration of its own. It loads two
configuration files, proves the candidate run is aligned with the reference run
row by row, proves the route is the one Stage 11A qualified, and hands the
resulting spec plus
:func:`~fpbench.experiments.verifinger_research.verifinger_research_integration`
to :mod:`fpbench.experiments.algorithm_research`.

Four things it deliberately does not do:

* **It reads no SourceAFIS, NBIS or flx score.** The reference run is opened for
  its identity, its plan, its pair manifest, its prepared inputs and its
  readiness — and for nothing else. There is no join of two result tables here
  (spec section 30).
* **It applies no threshold and computes no metric.** A VeriFinger score of 2 is
  a successful comparison, not a NON_MATCH, and the vendor's 48 is not an
  operating point fpbench chose (docs/adr/0003, spec sections 10 and 35).
* **It publishes no score statistic.** Not a minimum, not a mean, not a
  histogram, not an example row. A distribution is a threshold in disguise
  (spec section 33).
* **It materialises no image.** Every pixel it reads belongs to
  ``prepset_be560e047991`` and was written by Stage 6A (spec section 6).

There is no command-line entry point on purpose: the run takes hours, it may not
be started under a different commit than it was prepared under, and a convenient
``execute`` verb is exactly how that happens by accident.
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
from fpbench.core.research_models import ResearchReceipt, ResearchRunState
from fpbench.core.run_state_models import IntegrityIssue
from fpbench.core.serialization import read_json, to_plain, write_json
from fpbench.execution.batch_runner import RunExecutionSummary
from fpbench.experiments import stage11b_identity as frozen
from fpbench.experiments.algorithm_research import (
    REPOSITORY_ROOT,
    AlgorithmResearchExperimentSpec,
    PreparedAlgorithmResearchRun,
    capture_research_provenance,
    read_run_pointer,
)
from fpbench.experiments.canonical_run_alignment import (
    AlignmentExpectations,
    CanonicalRunAlignmentReport,
    ReferenceRunIdentity,
    build_canonical_run_alignment_report,
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
from fpbench.experiments.sd300_inputs import SD300Inputs, load_sd300_inputs
from fpbench.experiments.stage11a_binding import require_stage11a_binding
from fpbench.experiments.verifinger_research import (
    execute_verifinger_research_run,
    finalize_verifinger_research_run,
    inspect_verifinger_research_experiment,
    prepare_verifinger_research_run,
)
from fpbench.experiments.verifinger_validation import (
    SD300_CANONICAL500_INPUT_SET,
    validate_verifinger_result_set,
)
from fpbench.imaging.canonical500 import Canonical500ImagePreparer
from fpbench.storage.plan_store import PlanStore
from fpbench.storage.prepared_image_set_store import PreparedImageSetStore
from fpbench.storage.result_set_store import ResultSetStore
from fpbench.storage.result_store import ResultStore
from fpbench.adapters.verifinger_java import identity, runtime as runtime_closure
from fpbench.experiments import verifinger_policy as policy

__all__ = [
    "EXPERIMENT_ID",
    "EVIDENCE_DIRECTORY",
    "DEFAULT_EXPERIMENT_CONFIG",
    "DEFAULT_WORKSPACE",
    "VeriFingerCanonical500Config",
    "VeriFingerCanonical500State",
    "load_verifinger_canonical500_config",
    "build_verifinger_canonical500_spec",
    "preflight_verifinger_canonical500_run",
    "verify_verifinger_canonical500_alignment",
    "prepare_verifinger_canonical500_run",
    "execute_verifinger_canonical500_run",
    "inspect_verifinger_canonical500_experiment",
    "finalize_verifinger_canonical500_run",
]

EXPERIMENT_ID = frozen.EXPERIMENT_ID
EVIDENCE_DIRECTORY = frozen.EVIDENCE_DIRECTORY
DEFAULT_EXPERIMENT_CONFIG = (
    REPOSITORY_ROOT / "configs" / "experiments" / f"{EXPERIMENT_ID}.yaml"
)
DEFAULT_WORKSPACE = REPOSITORY_ROOT / "workspace"
ALIGNMENT_REPORT_NAME = "verifinger-canonical500-alignment.json"

_TOP_LEVEL_KEYS = (
    "experiment_id",
    "kind",
    "replicate_index",
    "dataset_config",
    "protocol_config",
    "algorithm_config",
    "require_verified_checksums",
    "stage11a",
    "algorithm",
    "runtime_closure",
    "reference",
    "preparation",
    "expected",
    "operations",
    "execution",
    "runtime",
    "reporting",
)
_STAGE11A_KEYS = (
    "finalization_fingerprint",
    "outcome",
    "selected_candidate",
    "algorithm_slot",
    "gates_passed",
    "opens_stage_11b",
)
_ALGORITHM_KEYS = (
    "id",
    "adapter_id",
    "adapter_version",
    "implementation_version",
    "vendor",
    "profile_fingerprint",
)
_CLOSURE_KEYS = (
    "manifest",
    "manifest_fingerprint",
    "policy",
    "policy_id",
    "sdk_archive_sha256",
    "components",
    "native_libraries",
    "model_data_files",
    "classpath_jars",
)
_REFERENCE_KEYS = ("run_id", "plan_id", "result_set_id", "cohort_id", "pair_manifest_hash")
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
    "comparisons_per_job",
    "logical_extractions_per_comparison",
    "verify_invocations_per_comparison",
    "jvm_processes_per_comparison",
    "representation_cache",
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
_REPORTING_KEYS = tuple(sorted(frozen.REQUIRED_REPORTING_SWITCHES))

_HEX = frozenset("0123456789abcdef")


# ------------------------------------------------------------------ the config


@dataclass(frozen=True, slots=True)
class VeriFingerCanonical500Config:
    """The pinned description of the Stage 11B run."""

    experiment_id: str
    kind: str
    replicate_index: int

    dataset_config: Path
    protocol_config: Path
    algorithm_config: Path
    require_verified_checksums: bool

    stage11a_finalization_fingerprint: str
    stage11a_outcome: str

    algorithm_profile_fingerprint: str
    runtime_manifest_fingerprint: str
    runtime_manifest_path: Path
    runtime_policy_path: Path
    sdk_archive_sha256: str

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

    @property
    def planned_logical_extractions(self) -> int:
        return self.expected_jobs * identity.REQUIRED_EXTRACTION_COUNT

    @property
    def planned_verify_invocations(self) -> int:
        return self.expected_jobs


def load_verifinger_canonical500_config(
    path: Path = DEFAULT_EXPERIMENT_CONFIG,
    *,
    repository_root: Path = REPOSITORY_ROOT,
) -> VeriFingerCanonical500Config:
    """Read ``configs/experiments/verifinger_canonical500_full_v1.yaml``, strictly.

    Every scalar is read with a type-checking helper rather than coerced, every
    unknown key is refused, every frozen identity is compared with
    :mod:`fpbench.experiments.stage11b_identity`, and a key that would turn this
    into a decision stage is refused wherever it appears in the document
    (spec section 21).
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
    reject_unknown_keys(document, _TOP_LEVEL_KEYS, where=path)

    stage11a = require_yaml_mapping(document, "stage11a", where=path)
    reject_unknown_keys(stage11a, _STAGE11A_KEYS, where=f"{path} stage11a")
    algorithm = require_yaml_mapping(document, "algorithm", where=path)
    reject_unknown_keys(algorithm, _ALGORITHM_KEYS, where=f"{path} algorithm")
    closure = require_yaml_mapping(document, "runtime_closure", where=path)
    reject_unknown_keys(closure, _CLOSURE_KEYS, where=f"{path} runtime_closure")
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
    _require_operations(operations, path)

    root = Path(repository_root)
    profile_config = (
        root
        / require_yaml_non_empty_str(execution, "profile_config", where=f"{path} execution")
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
            f"{path}: Stage 11B runs under {frozen.EXECUTION_PROFILE_ID!r}, not "
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
            f"{path}: the frozen Stage 11B job deadline is "
            f"{frozen.JOB_DEADLINE_SECONDS} seconds, not {job_deadline}. It was "
            "chosen from qualification and smoke timings before SD300 was opened "
            "and may not be tuned afterwards (spec section 28)"
        )

    # --- the Stage 11A binding, as the file restates it -------------------
    stage11a_fingerprint = _require_digest(
        require_yaml_non_empty_str(
            stage11a, "finalization_fingerprint", where=f"{path} stage11a"
        ),
        f"{path} stage11a.finalization_fingerprint",
    )
    stage11a_outcome = require_yaml_non_empty_str(
        stage11a, "outcome", where=f"{path} stage11a"
    )
    for label, value, wanted in (
        (
            "stage11a.finalization_fingerprint",
            stage11a_fingerprint,
            identity.STAGE_11A_FINALIZATION_FINGERPRINT,
        ),
        ("stage11a.outcome", stage11a_outcome, identity.STAGE_11A_OUTCOME),
        (
            "stage11a.selected_candidate",
            require_yaml_non_empty_str(
                stage11a, "selected_candidate", where=f"{path} stage11a"
            ),
            identity.STAGE_11A_SELECTED_CANDIDATE,
        ),
        (
            "stage11a.algorithm_slot",
            require_yaml_non_empty_str(
                stage11a, "algorithm_slot", where=f"{path} stage11a"
            ),
            identity.ALGORITHM_SLOT,
        ),
        ("stage11a.gates_passed", stage11a.get("gates_passed"), 17),
        ("stage11a.opens_stage_11b", stage11a.get("opens_stage_11b"), True),
    ):
        _require_frozen(label, value, wanted, path)

    # --- the production identity ------------------------------------------
    profile_fingerprint = _require_digest(
        require_yaml_non_empty_str(
            algorithm, "profile_fingerprint", where=f"{path} algorithm"
        ),
        f"{path} algorithm.profile_fingerprint",
    )
    for label, value, wanted in (
        (
            "algorithm.id",
            require_yaml_non_empty_str(algorithm, "id", where=f"{path} algorithm"),
            identity.ALGORITHM_ID,
        ),
        (
            "algorithm.adapter_id",
            require_yaml_non_empty_str(
                algorithm, "adapter_id", where=f"{path} algorithm"
            ),
            identity.ADAPTER_ID,
        ),
        (
            "algorithm.adapter_version",
            require_yaml_non_empty_str(
                algorithm, "adapter_version", where=f"{path} algorithm"
            ),
            identity.ADAPTER_VERSION,
        ),
        (
            "algorithm.implementation_version",
            require_yaml_non_empty_str(
                algorithm, "implementation_version", where=f"{path} algorithm"
            ),
            identity.IMPLEMENTATION_VERSION,
        ),
        (
            "algorithm.vendor",
            require_yaml_non_empty_str(algorithm, "vendor", where=f"{path} algorithm"),
            identity.VENDOR,
        ),
        (
            "algorithm.profile_fingerprint",
            profile_fingerprint,
            identity.algorithm_profile_fingerprint(),
        ),
    ):
        _require_frozen(label, value, wanted, path)

    # --- the runtime closure ----------------------------------------------
    manifest_fingerprint = _require_digest(
        require_yaml_non_empty_str(
            closure, "manifest_fingerprint", where=f"{path} runtime_closure"
        ),
        f"{path} runtime_closure.manifest_fingerprint",
    )
    manifest_path = (
        root
        / require_yaml_non_empty_str(closure, "manifest", where=f"{path} runtime_closure")
    ).resolve()
    policy_path = (
        root
        / require_yaml_non_empty_str(closure, "policy", where=f"{path} runtime_closure")
    ).resolve()
    manifest = runtime_closure.read_runtime_manifest(manifest_path)
    for label, value, wanted in (
        ("runtime_closure.manifest_fingerprint", manifest_fingerprint, manifest.fingerprint),
        (
            "runtime_closure.policy_id",
            require_yaml_non_empty_str(closure, "policy_id", where=f"{path} runtime_closure"),
            policy.POLICY_ID,
        ),
        (
            "runtime_closure.sdk_archive_sha256",
            require_yaml_non_empty_str(
                closure, "sdk_archive_sha256", where=f"{path} runtime_closure"
            ),
            manifest.sdk_archive_sha256,
        ),
        ("runtime_closure.components", closure.get("components"), len(manifest.components)),
        (
            "runtime_closure.native_libraries",
            closure.get("native_libraries"),
            len(runtime_closure.NATIVE_LIBRARY_NAMES),
        ),
        (
            "runtime_closure.model_data_files",
            closure.get("model_data_files"),
            len(runtime_closure.MODEL_DATA_FILES),
        ),
        (
            "runtime_closure.classpath_jars",
            closure.get("classpath_jars"),
            len(runtime_closure.CLASSPATH_JARS),
        ),
    ):
        _require_frozen(label, value, wanted, path)

    # --- the canonical reference ------------------------------------------
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
    for label, value, wanted in (
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
        ("preparation.target_ppi", target_ppi, identity.REQUIRED_EFFECTIVE_PPI),
    ):
        _require_frozen(label, value, wanted, path)

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
            f"{path}: Stage 11B covers {list(frozen.EXPECTED_RELEASES)}, not "
            f"{list(release_names)}"
        )

    participating = require_yaml_exact_int(
        expected, "participating_images", where=f"{path} expected", minimum=1
    )
    expected_jobs = require_yaml_exact_int(
        expected, "jobs", where=f"{path} expected", minimum=1
    )
    for label, value, wanted in (
        ("expected.jobs", expected_jobs, frozen.EXPECTED_JOBS),
        (
            "expected.participating_images",
            participating,
            frozen.EXPECTED_PARTICIPATING_IMAGES,
        ),
    ):
        _require_frozen(label, value, wanted, path)

    source_ppi = require_yaml_mapping(expected, "source_ppi", where=f"{path} expected")
    resolved_source_ppi = {
        str(key): require_yaml_exact_int(
            source_ppi, str(key), where=f"{path} expected.source_ppi", minimum=1
        )
        for key in source_ppi
    }
    if resolved_source_ppi != dict(frozen.EXPECTED_SOURCE_PPI):
        raise ConfigurationError(
            f"{path}: expected.source_ppi is {resolved_source_ppi}, and Stage 11B "
            f"is frozen at {dict(frozen.EXPECTED_SOURCE_PPI)}"
        )

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
    for label, value, wanted in (
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
        _require_frozen(label, value, wanted, path)

    experiment_id = require_yaml_non_empty_str(document, "experiment_id", where=path)
    _require_frozen("experiment_id", experiment_id, frozen.EXPERIMENT_ID, path)

    image_policy = require_yaml_non_empty_str(
        runtime, "image_materialization_policy", where=f"{path} runtime"
    )
    if image_policy != "reference_existing_prepared_images":
        raise ConfigurationError(
            f"{path}: runtime.image_materialization_policy must be "
            "'reference_existing_prepared_images'. Stage 11B creates no "
            "PreparedImageSet (spec section 6)"
        )

    return VeriFingerCanonical500Config(
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
        stage11a_finalization_fingerprint=stage11a_fingerprint,
        stage11a_outcome=stage11a_outcome,
        algorithm_profile_fingerprint=profile_fingerprint,
        runtime_manifest_fingerprint=manifest_fingerprint,
        runtime_manifest_path=manifest_path,
        runtime_policy_path=policy_path,
        sdk_archive_sha256=manifest.sdk_archive_sha256,
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
        expected_source_ppi=resolved_source_ppi,
        execution_profile=profile,
        job_deadline_seconds=job_deadline,
        max_workers=require_yaml_exact_int(
            execution, "max_workers", where=f"{path} execution", minimum=1
        ),
        materialization_policy=require_yaml_non_empty_str(
            runtime, "materialization_policy", where=f"{path} runtime"
        ),
        image_materialization_policy=image_policy,
        research_mode=require_yaml_bool(runtime, "research_mode", where=f"{path} runtime"),
    )


def build_verifinger_canonical500_spec(
    config: VeriFingerCanonical500Config,
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
class VeriFingerCanonical500State:
    """How far along Stage 11B is, and whether it may be called finished."""

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
        if self.is_ready:
            return "VERIFINGER_CANONICAL500_RAW_READY"
        if self.issues or not self.alignment_report.is_clean:
            return "BLOCKED"
        return self.research_state.status.value


# ------------------------------------------------------------------ preflight


def preflight_verifinger_canonical500_run(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    dataset_root: Path | None = None,
    config: VeriFingerCanonical500Config | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    installation: Path | None = None,
    require_clean_tree: bool = True,
) -> Mapping[str, Any]:
    """Check every input Stage 11B will read, and write nothing.

    Everything ``prepare`` checks before it creates a run, run on its own so an
    operator can find out that the trial has lapsed or a DLL has moved without a
    half-prepared workspace to clean up.
    """
    workspace = Path(workspace)
    repository_root = Path(repository_root)
    config = config or load_verifinger_canonical500_config(
        repository_root=repository_root
    )
    findings, _ = _preflight_inputs(
        workspace=workspace,
        dataset_root=dataset_root,
        config=config,
        repository_root=repository_root,
        installation=installation,
        require_clean_tree=require_clean_tree,
    )
    return findings


def _preflight_inputs(
    *,
    workspace: Path,
    dataset_root: Path | None,
    config: VeriFingerCanonical500Config,
    repository_root: Path,
    installation: Path | None,
    require_clean_tree: bool,
    run_smoke: bool = True,
) -> tuple[dict[str, Any], "_AlignmentContext"]:
    """Every check, and the loaded context, so a caller pays for it once."""
    findings: dict[str, Any] = {"experiment_id": config.experiment_id}
    if require_clean_tree:
        software = capture_research_provenance(repository_root)
        findings["source_commit"] = software.source_revision
        findings["source_tree_clean"] = software.source_tree_clean

    published = require_stage11a_binding(
        declared_fingerprint=config.stage11a_finalization_fingerprint,
        declared_outcome=config.stage11a_outcome,
        repository_root=repository_root,
    )
    findings["stage11a_outcome"] = published.outcome
    findings["stage11a_finalization_fingerprint"] = published.finalization_fingerprint
    findings["stage11a_gates_passed"] = published.gates_passed

    # The committed policy says what this route does; this proves it says what
    # the source actually does (spec section 37).
    loaded_policy = policy.read_runtime_policy(config.runtime_policy_path)
    policy.require_policy_matches_source(loaded_policy)
    findings["runtime_policy_id"] = loaded_policy.policy_id
    findings["runtime_policy_fingerprint"] = loaded_policy.fingerprint

    # The full closure pass: every DLL, jar and model file re-hashed, and every
    # one of them re-read out of the pinned SDK archive to prove where it came
    # from (spec section 16).
    findings["runtime_closure"] = _verify_runtime_closure(
        config=config, repository_root=repository_root, installation=installation
    )
    findings["algorithm_profile_fingerprint"] = identity.algorithm_profile_fingerprint()

    # The production adapter's own smoke, on fixtures that are not SD300, before
    # a single benchmark pair is opened. If it passes there is no further review
    # stage: the full run starts (spec sections 23 and 24).
    if run_smoke:
        from fpbench.experiments.verifinger_smoke import run_production_smoke

        smoke = run_production_smoke(
            repository_root=repository_root, installation=installation
        )
        if not smoke.passed:
            raise ResearchPreflightError(
                "the production adapter smoke did not establish its claims, so "
                f"SD300 may not be opened: {dict(smoke.claims)}"
            )
        findings["production_smoke"] = smoke.as_document()

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
        build_verifinger_canonical500_spec(config),
        reference_materialization_policy=context.reference_materialization_policy,
    )
    findings["alignment_fingerprint"] = context.report.alignment_fingerprint
    findings["prepared_entries"] = len(context.prepared_entries)
    findings["pairs"] = len(context.inputs.pairs)
    findings["pair_manifest_hash"] = context.inputs.pair_manifest_hash
    findings["planned_operations"] = {
        "comparison_attempts": config.expected_jobs,
        "logical_extractions": config.planned_logical_extractions,
        "verify_invocations": config.planned_verify_invocations,
    }
    return findings, context


def _verify_runtime_closure(
    *,
    config: VeriFingerCanonical500Config,
    repository_root: Path,
    installation: Path | None,
) -> Mapping[str, Any]:
    """Re-hash every runtime component and prove it came from the pinned archive.

    Raises:
        ResearchPreflightError: any component is absent, altered, or is not the
            bytes the archive holds under that name. One fault of the run, found
            before a single comparison.
    """
    from fpbench.core.verifinger_errors import VeriFingerRuntimeClosureError
    from fpbench.experiments.stage11a_artifacts import artifact_store_prefix_path
    from fpbench.experiments.stage11a_verifinger_observations import SDK_ARCHIVE
    from fpbench.experiments.verifinger_runtime_manifest import default_installation

    manifest = runtime_closure.read_runtime_manifest(config.runtime_manifest_path)
    if manifest.fingerprint != config.runtime_manifest_fingerprint:
        raise ResearchPreflightError(
            f"the runtime manifest hashes to {manifest.fingerprint[:12]}..., and "
            f"the experiment names {config.runtime_manifest_fingerprint[:12]}..."
        )
    tree = (
        Path(installation).resolve()
        if installation is not None
        else default_installation(repository_root=repository_root)
    )
    archive = (
        artifact_store_prefix_path(repository_root=repository_root)
        / SDK_ARCHIVE.filename
    )
    try:
        verified = runtime_closure.verify_installation(tree, manifest)
        proved = runtime_closure.verify_against_archive(archive, manifest)
    except VeriFingerRuntimeClosureError as exc:
        raise ResearchPreflightError(
            f"the pinned VeriFinger runtime does not verify: {exc}"
        ) from exc
    return {
        "manifest_fingerprint": manifest.fingerprint,
        "components_verified_on_disk": len(verified),
        "components_proved_from_the_pinned_archive": len(proved),
        "sdk_archive_sha256": manifest.sdk_archive_sha256,
        "platform": manifest.platform,
    }


# ------------------------------------------------------------------- alignment


def verify_verifinger_canonical500_alignment(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    dataset_root: Path | None = None,
    config: VeriFingerCanonical500Config | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
    require_clean: bool = True,
) -> CanonicalRunAlignmentReport:
    """Prove the VeriFinger run is over the reference run's own inputs, row by row."""
    config = config or load_verifinger_canonical500_config(
        repository_root=repository_root
    )
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


def prepare_verifinger_canonical500_run(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    dataset_root: Path | None = None,
    config: VeriFingerCanonical500Config | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    installation: Path | None = None,
) -> PreparedAlgorithmResearchRun:
    """Check everything, then write the run, the plan and the runtime binding.

    In order, and each step is a place the whole thing stops:

    1. the working tree is clean and committed;
    2. the published Stage 11A evidence verifies and permits execution;
    3. the committed runtime policy describes what this source does;
    4. all seventeen runtime components hash correctly and came from the archive;
    5. the prepared-image set verifies in full;
    6. the reference SourceAFIS run is ``RESEARCH_READY``;
    7. the pair manifest is loaded with ``allow_creation=False`` — not rebuilt;
    8. the alignment report is derived and is clean;
    9. the engine creates the run and plans exactly 6,000 jobs;
    10. the alignment is re-derived against the plan that now exists.

    No raw result is written here, and none can be: this function never reaches
    the executor.
    """
    workspace = Path(workspace)
    repository_root = Path(repository_root)
    config = config or load_verifinger_canonical500_config(
        repository_root=repository_root
    )

    findings, context = _preflight_inputs(
        workspace=workspace,
        dataset_root=dataset_root,
        config=config,
        repository_root=repository_root,
        installation=installation,
        require_clean_tree=True,
    )

    prepared = prepare_verifinger_research_run(
        spec=build_verifinger_canonical500_spec(config),
        preparer_factory=_preparer_factory,
        workspace=workspace,
        dataset_root=dataset_root,
        repository_root=repository_root,
        installation=installation,
        expected_input_set=SD300_CANONICAL500_INPUT_SET,
        expected_runtime_manifest_fingerprint=config.runtime_manifest_fingerprint,
    )

    final = _rebuild_alignment(
        context=context, config=config, run_id=prepared.run.run_id, plan=prepared.plan
    )
    require_clean_alignment(final)
    _write_alignment_report(workspace, prepared.run.run_id, final)
    # The smoke ran before the run existed; it is stored against the run it
    # cleared, so the published evidence can name the pass that authorised it
    # rather than one performed at some other time (spec section 23).
    write_json(
        ResultStore(workspace).derived_path(
            prepared.run.run_id, frozen.SMOKE_REPORT_NAME
        ),
        findings["production_smoke"],
    )
    return prepared


def execute_verifinger_canonical500_run(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    dataset_root: Path | None = None,
    config: VeriFingerCanonical500Config | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
    max_new_jobs: int | None = None,
    installation: Path | None = None,
) -> RunExecutionSummary:
    """Execute some or all of the prepared run, one comparison at a time.

    May be stopped and resumed as often as necessary. A result that is already
    stored is verified and skipped, never re-executed and never overwritten, so
    resuming cannot change a number that has already been recorded — and a power
    failure after 3,174 jobs costs 3,174 jobs of wall clock, not of results
    (spec section 29). A resume under a different source commit is refused by the
    engine, because a run whose results came from two revisions is not one run.
    """
    config = config or load_verifinger_canonical500_config(
        repository_root=repository_root
    )
    return execute_verifinger_research_run(
        spec=build_verifinger_canonical500_spec(config),
        preparer_factory=_preparer_factory,
        workspace=Path(workspace),
        dataset_root=dataset_root,
        repository_root=Path(repository_root),
        run_id=run_id,
        max_new_jobs=max_new_jobs,
        installation=installation,
        expected_input_set=SD300_CANONICAL500_INPUT_SET,
        expected_runtime_manifest_fingerprint=config.runtime_manifest_fingerprint,
    )


def inspect_verifinger_canonical500_experiment(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    dataset_root: Path | None = None,
    config: VeriFingerCanonical500Config | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
    installation: Path | None = None,
) -> VeriFingerCanonical500State:
    """Report where Stage 11B stands. Never writes."""
    workspace = Path(workspace)
    repository_root = Path(repository_root)
    config = config or load_verifinger_canonical500_config(
        repository_root=repository_root
    )
    research_state = inspect_verifinger_research_experiment(
        spec=build_verifinger_canonical500_spec(config),
        preparer_factory=_preparer_factory,
        workspace=workspace,
        dataset_root=dataset_root,
        repository_root=repository_root,
        run_id=run_id,
        installation=installation,
        expected_input_set=SD300_CANONICAL500_INPUT_SET,
        expected_runtime_manifest_fingerprint=config.runtime_manifest_fingerprint,
    )
    report = verify_verifinger_canonical500_alignment(
        workspace=workspace,
        dataset_root=dataset_root,
        config=config,
        repository_root=repository_root,
        run_id=research_state.run_id,
        require_clean=False,
    )
    issues = tuple(_compare_stored_alignment(workspace, research_state.run_id, report))
    return VeriFingerCanonical500State(
        research_state=research_state, alignment_report=report, issues=issues
    )


def finalize_verifinger_canonical500_run(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    dataset_root: Path | None = None,
    config: VeriFingerCanonical500Config | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
    installation: Path | None = None,
) -> ResearchReceipt:
    """Revalidate everything, publish the receipt, and prove the route held.

    The engine does the audit, the result set, the VeriFinger validation, the
    receipt and the marker — and it raises unless the run reaches
    ``RESEARCH_READY``. What this function adds is what the engine has no
    business knowing about: the Stage 11A binding is re-checked, the runtime
    closure is re-hashed one last time, and the alignment is re-derived and
    compared with the one preparation stored.
    """
    workspace = Path(workspace)
    repository_root = Path(repository_root)
    config = config or load_verifinger_canonical500_config(
        repository_root=repository_root
    )
    resolved = run_id or read_run_pointer(workspace, config.experiment_id)
    capture_research_provenance(repository_root)

    require_stage11a_binding(
        declared_fingerprint=config.stage11a_finalization_fingerprint,
        declared_outcome=config.stage11a_outcome,
        repository_root=repository_root,
    )
    policy.require_policy_matches_source(
        policy.read_runtime_policy(config.runtime_policy_path)
    )
    # The after-the-run half of the closure guard (spec section 19).
    _verify_runtime_closure(
        config=config, repository_root=repository_root, installation=installation
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
        build_verifinger_canonical500_spec(config),
        reference_materialization_policy=context.reference_materialization_policy,
    )
    stored_issues = tuple(_compare_stored_alignment(workspace, resolved, context.report))
    if stored_issues:
        raise ResearchPreflightError(
            "the alignment report stored at preparation is not the one this "
            f"workspace now derives: {stored_issues[0].message}"
        )

    receipt = finalize_verifinger_research_run(
        spec=build_verifinger_canonical500_spec(config),
        preparer_factory=_preparer_factory,
        workspace=workspace,
        dataset_root=dataset_root,
        repository_root=repository_root,
        run_id=resolved,
        installation=installation,
        expected_input_set=SD300_CANONICAL500_INPUT_SET,
        expected_runtime_manifest_fingerprint=config.runtime_manifest_fingerprint,
    )
    return receipt


# ----------------------------------------------------------------- internals


@dataclass(frozen=True, slots=True)
class _AlignmentContext:
    """Everything one alignment pass loaded, kept so it is loaded once."""

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
    config: VeriFingerCanonical500Config,
    repository_root: Path,
    run_id: str | None,
) -> _AlignmentContext:
    """Load both sides once, from the manifests, and compare them."""
    spec = build_verifinger_canonical500_spec(config)

    # The pair manifest is *read*. ``allow_creation=False`` is what makes that
    # true rather than intended: with it, a workspace missing the manifest is an
    # error instead of an invitation to build a new one (spec section 26).
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
            f"{inputs.pair_manifest_hash[:12]}..., but Stage 11B is defined "
            f"against {config.reference_pair_manifest_hash[:12]}..."
        )
    if str(inputs.cohort.cohort_id) != config.reference_cohort_id:
        raise ResearchPreflightError(
            f"the workspace cohort is {inputs.cohort.cohort_id}, but Stage 11B is "
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
            f"{runtime_fingerprint[:12]}..., but Stage 11B is defined against "
            f"{config.transform_runtime_fingerprint[:12]}..."
        )

    reference_side = load_reference_alignment_side(
        workspace=workspace,
        expected=config.reference,
        research_state=_reference_research_state(
            workspace=workspace,
            dataset_root=dataset_root,
            repository_root=repository_root,
        ),
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
    return _AlignmentContext(
        inputs=inputs,
        prepared_entries=entries,
        reference_run=ResultStore(workspace).read_run(config.reference.run_id),
        reference_side=reference_side,
        reference_materialization_policy=_materialization_policy(
            workspace, config.reference.run_id
        ),
        report=report,
    )


def _rebuild_alignment(
    *,
    context: _AlignmentContext,
    config: VeriFingerCanonical500Config,
    run_id: str,
    plan: Any,
) -> CanonicalRunAlignmentReport:
    """The same comparison, restated against a plan that now exists.

    Cheap, because both sides are already in memory. It matters because the order
    checked before ``prepare`` was the order the planner *would* impose, and this
    is the order it did.
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
        result_set_id=None,
    )
    return build_canonical_run_alignment_report(
        reference=context.reference_side,
        candidate=candidate_side,
        expected_reference=config.reference,
        expectations=config.alignment_expectations,
    )


def _reference_research_state(
    *, workspace: Path, dataset_root: Path | None, repository_root: Path
) -> ResearchRunState:
    """Ask the reference experiment's own wrapper how its run is doing.

    Imported here rather than at module scope so the dependency is visibly one
    function wide. Stage 11B reads the reference run's *readiness*; it does not
    import its adapter, its decision profile or its scores (spec section 30).
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
    except Exception:  # pragma: no cover - a reference run without a binding
        return None
    return getattr(reference, "materialization_policy", None)


def _result_set_id(workspace: Path, run_id: str) -> str | None:
    try:
        return ResultSetStore(workspace).read_manifest(run_id).result_set_id
    except Exception:  # pragma: no cover - absent before finalization
        return None


def _alignment_path(workspace: Path, run_id: str) -> Path:
    return ResultStore(workspace).derived_path(run_id, ALIGNMENT_REPORT_NAME)


def _write_alignment_report(
    workspace: Path, run_id: str, report: CanonicalRunAlignmentReport
) -> Path:
    return write_json(_alignment_path(workspace, run_id), to_plain(report))


def _compare_stored_alignment(
    workspace: Path, run_id: str, derived: CanonicalRunAlignmentReport
):
    """The stored alignment report is the one this workspace still derives."""
    from fpbench.core.enums import IntegrityIssueCode, IntegritySeverity

    path = _alignment_path(workspace, run_id)
    if not path.is_file():
        yield IntegrityIssue(
            code=IntegrityIssueCode.RESULT_METADATA_MISSING,
            severity=IntegritySeverity.ERROR,
            message="no alignment report was stored when this run was prepared",
        )
        return
    stored = read_json(path)
    if str(stored.get("alignment_fingerprint")) != derived.alignment_fingerprint:
        yield IntegrityIssue(
            code=IntegrityIssueCode.RESULT_METADATA_MISSING,
            severity=IntegritySeverity.ERROR,
            message=(
                "the stored alignment report fingerprints to "
                f"{str(stored.get('alignment_fingerprint'))[:12]}..., and this "
                f"workspace derives {derived.alignment_fingerprint[:12]}..."
            ),
        )


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


def _require_no_decision_keys(document: Any, path: Path, trail: str = "") -> None:
    """Refuse a key that would make this a decision stage, at any depth."""
    if isinstance(document, Mapping):
        for key, value in document.items():
            name = str(key)
            if name.lower() in frozen.FORBIDDEN_CONFIG_KEYS:
                where = f"{trail}.{name}" if trail else name
                raise ConfigurationError(
                    f"{path}: {where} may not appear in a Stage 11B experiment. "
                    "This stage produces raw outcomes; thresholds, calibration "
                    "and metrics are later layers over these stored scores "
                    "(docs/adr/0003, spec sections 21 and 35)"
                )
            _require_no_decision_keys(value, path, f"{trail}.{name}" if trail else name)
    elif isinstance(document, list):
        for index, item in enumerate(document):
            _require_no_decision_keys(item, path, f"{trail}[{index}]")


def _require_reporting_switches(reporting: Mapping[str, Any], path: Path) -> None:
    for key, wanted in sorted(frozen.REQUIRED_REPORTING_SWITCHES.items()):
        value = reporting.get(key)
        if value is not wanted:
            raise ConfigurationError(
                f"{path}: reporting.{key} must be {str(wanted).lower()}, got "
                f"{value!r}. Stage 11B publishes operational facts and no "
                "biometric metric (spec sections 33 and 35)"
            )


def _require_execution_controls(execution: Mapping[str, Any], path: Path) -> None:
    if execution.get("sequential") is not True:
        raise ConfigurationError(
            f"{path}: execution.sequential must be true; Stage 11B runs one "
            "comparison at a time (spec section 28)"
        )
    if execution.get("max_workers") != frozen.MAX_WORKERS:
        raise ConfigurationError(
            f"{path}: execution.max_workers must be {frozen.MAX_WORKERS}"
        )
    if execution.get("retries") != frozen.RETRIES:
        raise ConfigurationError(
            f"{path}: execution.retries must be {frozen.RETRIES}; a failed "
            "comparison is a recorded outcome, and re-running only the failures "
            "would produce a run whose results came from two attempts "
            "(docs/adr/0013)"
        )


def _require_operations(operations: Mapping[str, Any], path: Path) -> None:
    for key, wanted in (
        ("comparisons_per_job", 1),
        ("logical_extractions_per_comparison", identity.REQUIRED_EXTRACTION_COUNT),
        ("verify_invocations_per_comparison", 1),
        ("jvm_processes_per_comparison", 1),
    ):
        if operations.get(key) != wanted:
            raise ConfigurationError(
                f"{path}: operations.{key} must be {wanted}; SELF counts as two "
                "extractions exactly like every other comparison "
                "(spec sections 14 and 27)"
            )
    if str(operations.get("representation_cache")) != "disabled":
        raise ConfigurationError(
            f"{path}: operations.representation_cache must be 'disabled'"
        )


def _require_frozen(label: str, value: Any, expected: Any, path: Path) -> None:
    if value != expected:
        raise ConfigurationError(
            f"{path}: {label} is {value!r}, and Stage 11B is frozen at {expected!r}"
        )


def _require_digest(value: str, label: str) -> str:
    digest = str(value).strip().lower()
    if len(digest) != 64 or not set(digest) <= _HEX:
        raise ConfigurationError(f"{label} must be a 64-character hexadecimal digest")
    return digest
