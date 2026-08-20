"""The 6,000 canonical SD300 comparisons, run again by NBIS 5.0.0.

Everything that decides *what* is compared was decided in stage 6A and is read
back here unchanged: the protocol, the cohort, the 6,000-row pair manifest, its
order, and the 3,000 immutable 500 ppi PNGs. Nothing in this module selects a
cohort, generates a pair, resamples an image or writes a PNG, and a structural
test proves it by walking the syntax tree rather than by trusting the sentence
(docs/adr/0051, spec section 5).

What is new is the algorithm, and only the algorithm:

    MINDTCT 5.0.0  ->  BOZORTH3 5.0.0

driven by the adapter stage 7B certified, through the orchestration stage 7A
extracted. This module contains no orchestration of its own. It loads two
configuration files, proves the candidate run is aligned with the reference run
row by row, and hands the resulting spec plus
:func:`~fpbench.experiments.nbis_research.nbis_research_integration` to
:mod:`fpbench.experiments.algorithm_research` (spec section 22).

Three things it deliberately does not do:

* **It reads no SourceAFIS score.** The reference run is opened for its identity,
  its plan, its pair manifest, its prepared inputs and its readiness — and for
  nothing else. There is no join of two result tables here; that belongs to a
  later stage and needs a decision profile that does not exist yet
  (spec section 41, docs/adr/0052).
* **It applies no threshold and computes no metric.** A BOZORTH3 score of 0 is a
  successful comparison, not a NON_MATCH, and the number 40 belongs to a
  different algorithm's scale (docs/adr/0003, docs/adr/0006).
* **It chooses no build.** The certified build is passed in explicitly and
  checked against the id this experiment is defined against. There is no
  "newest", no lexicographic first and no fallback (docs/adr/0053).

The documented invocation is in ``docs/experiments/nbis-canonical500-raw.md``.
There is no command-line entry point on purpose: the run takes hours, it may not
be started under a different commit than it was prepared under, and a convenient
``execute`` verb is exactly how that happens by accident (spec section 48).
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from fpbench.adapters.nbis.build_manifest import BUILD_MANIFEST_FILENAME
from fpbench.adapters.nbis.config import NbisConfig
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
from fpbench.core.serialization import read_json, to_plain
from fpbench.core.json_io import write_json
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
    require_clean_alignment,
    require_execution_controls_equal,
)
from fpbench.experiments.config_values import (
    reject_unknown_keys,
    require_yaml_bool,
    require_yaml_exact_int,
    require_yaml_mapping,
    require_yaml_non_empty_str,
)
from fpbench.experiments.nbis_research import (
    execute_nbis_research_run,
    finalize_nbis_research_run,
    inspect_nbis_research_experiment,
    prepare_nbis_research_run,
    require_certified_build,
)
from fpbench.experiments.nbis_validation import SD300_CANONICAL500_INPUT_SET
from fpbench.experiments.sd300_inputs import SD300Inputs, load_sd300_inputs
from fpbench.experiments.stage7c_finalization import (
    STAGE_7C_FINALIZATION_KIND,
    STAGE_7C_FINALIZATION_SCHEMA_VERSION,
    Stage7CFinalization,
    alignment_report_content_hash,
    stage_7c_finalization_fingerprint,
)
from fpbench.imaging.canonical500 import Canonical500ImagePreparer
from fpbench.storage.prepared_image_set_store import PreparedImageSetStore
from fpbench.storage.result_store import ResultStore
from fpbench.storage.result_set_store import ResultSetStore
from fpbench.storage.runtime_bundle_store import RuntimeBundleStore

__all__ = [
    "EXPERIMENT_ID",
    "EVIDENCE_DIRECTORY",
    "ALIGNMENT_REPORT_NAME",
    "STAGE_7C_FINALIZATION_NAME",
    "FORBIDDEN_CONFIG_KEYS",
    "PERMITTED_DOWNSTREAM_EXPERIMENTS",
    # Re-exported so a caller needs one import: the shape this experiment is,
    # and the sizes ``is_clean`` is measured against.
    "SD300_CANONICAL_EXPECTATIONS",
    "NbisCanonical500ExperimentConfig",
    "NbisCanonical500ExperimentState",
    "load_nbis_canonical500_config",
    "build_nbis_canonical500_spec",
    "verify_nbis_canonical500_alignment",
    "prepare_nbis_canonical500_run",
    "execute_nbis_canonical500_run",
    "inspect_nbis_canonical500_experiment",
    "finalize_nbis_canonical500_run",
    "refresh_nbis_canonical500_stage_finalization",
    "publish_nbis_canonical500_evidence",
    "require_pinned_build",
]

EXPERIMENT_ID = "nbis_canonical500_full_v1"

#: The experiments entitled to derive from this run.
#:
#: Empty while stage 7C was the last word — a decision set over these scores
#: would have meant a threshold chosen by nobody. Stage 7D chose one from NIST's
#: own documentation and wrote it into a committed profile, so these two
#: experiments are now expected. Anything else deriving from this run is still a
#: defect, and the list being data rather than a wildcard is what keeps that
#: true (docs/adr/0057, spec section 82).
PERMITTED_DOWNSTREAM_EXPERIMENTS: frozenset[str] = frozenset(
    {
        "nbis_canonical500_decisions_v1",
        "nbis_canonical500_nistir7391_gt40_evaluation_v1",
    }
)

#: Where a committed copy of this run's evidence lives (spec section 38).
EVIDENCE_DIRECTORY = Path("evidence") / "nbis-canonical500-raw"

#: The alignment report, cached beside the run's other derived artefacts. Like
#: every ``derived/`` file it is regenerable and is never trusted: finalization
#: re-derives it from the manifests and compares (docs/adr/0012).
ALIGNMENT_REPORT_NAME = "canonical-run-alignment.json"

#: The last-written authority that binds the alignment to the general research
#: receipt and finalization chain.
STAGE_7C_FINALIZATION_NAME = "stage-7c-finalization.json"

DEFAULT_EXPERIMENT_CONFIG = (
    REPOSITORY_ROOT / "configs" / "experiments" / f"{EXPERIMENT_ID}.yaml"
)
DEFAULT_WORKSPACE = REPOSITORY_ROOT / "workspace"

#: Keys no Stage 7C configuration file may contain, at any depth. Each one would
#: mean this stage had decided what a score means, and BOZORTH3's scale has no
#: threshold anybody has earned the right to write down (spec section 18).
FORBIDDEN_CONFIG_KEYS: frozenset[str] = frozenset(
    {
        "threshold",
        "decision_profile",
        "match_threshold",
        "acceptance_threshold",
        "calibration",
    }
)

_TOP_LEVEL_KEYS = (
    "experiment_id",
    "kind",
    "replicate_index",
    "dataset_config",
    "protocol_config",
    "algorithm_config",
    "require_verified_checksums",
    "reference",
    "preparation",
    "expected",
    "execution",
    "runtime",
    "build",
    "reporting",
)


# ------------------------------------------------------------------ the config


@dataclass(frozen=True, slots=True)
class NbisCanonical500ExperimentConfig:
    """The pinned description of the Stage 7C run.

    ``execution_profile`` is the reference run's own profile object, read from
    the file the reference run named. It is not restated in the Stage 7C YAML
    and could not be: restating it would create a second place for the timeout
    to live (spec section 19).
    """

    experiment_id: str
    kind: str
    replicate_index: int

    dataset_config: Path
    protocol_config: Path
    algorithm_config: Path
    require_verified_checksums: bool

    reference: ReferenceRunIdentity

    preparation_set_id: str
    preparation_set_fingerprint: str
    transform_profile_id: str
    transform_profile_fingerprint: str
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
    materialization_policy: str
    research_mode: bool

    nbis_build_id: str
    build_root: Path

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


def load_nbis_canonical500_config(
    path: Path = DEFAULT_EXPERIMENT_CONFIG,
    *,
    repository_root: Path = REPOSITORY_ROOT,
) -> NbisCanonical500ExperimentConfig:
    """Read ``configs/experiments/nbis_canonical500_full_v1.yaml``, strictly.

    Every scalar is read with a type-checking helper rather than coerced, every
    unknown key is refused, and a key that would turn this into a decision stage
    is refused wherever it appears in the document (spec sections 17 and 18).
    """
    path = Path(path)
    if not path.is_file():
        raise ConfigurationError(f"experiment config not found: {path}")
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(document, Mapping):
        raise ConfigurationError(f"{path}: expected a mapping at the top level")

    _require_no_decision_keys(document, path)
    reject_unknown_keys(document, _TOP_LEVEL_KEYS, where=path)

    reference = require_yaml_mapping(document, "reference", where=path)
    reject_unknown_keys(
        reference, ("run_id", "plan_id", "result_set_id"), where=f"{path} reference"
    )
    preparation = require_yaml_mapping(document, "preparation", where=path)
    reject_unknown_keys(
        preparation,
        (
            "set_id",
            "set_fingerprint",
            "transform_profile_id",
            "transform_profile_fingerprint",
            "target_ppi",
        ),
        where=f"{path} preparation",
    )
    expected = require_yaml_mapping(document, "expected", where=path)
    reject_unknown_keys(
        expected,
        (
            "jobs",
            "pairs_per_release_stage",
            "pairs_per_release",
            "pairs_per_stage",
            "releases",
            "subjects",
            "participating_images",
            "source_ppi",
        ),
        where=f"{path} expected",
    )
    execution = require_yaml_mapping(document, "execution", where=path)
    reject_unknown_keys(
        execution,
        ("profile_config", "profile_id", "sequential", "retries"),
        where=f"{path} execution",
    )
    runtime = require_yaml_mapping(document, "runtime", where=path)
    reject_unknown_keys(
        runtime, ("materialization_policy", "research_mode"), where=f"{path} runtime"
    )
    build = require_yaml_mapping(document, "build", where=path)
    reject_unknown_keys(build, ("nbis_build_id", "build_root"), where=f"{path} build")
    reporting = require_yaml_mapping(document, "reporting", where=path)
    reject_unknown_keys(
        reporting,
        ("biometric_metrics", "operational_summary", "score_statistics"),
        where=f"{path} reporting",
    )

    for key in ("biometric_metrics", "score_statistics"):
        if require_yaml_bool(reporting, key, where=f"{path} reporting"):
            raise ConfigurationError(
                f"{path}: reporting.{key} must be false. Stage 7C publishes raw "
                "scores and failure codes; a rate or a score distribution is a "
                "biometric claim and needs definitions this stage does not have "
                "(docs/adr/0052)"
            )
    if not require_yaml_bool(execution, "sequential", where=f"{path} execution"):
        raise ConfigurationError(f"{path}: this run is sequential (spec section 20)")
    if require_yaml_exact_int(execution, "retries", where=f"{path} execution") != 0:
        raise ConfigurationError(
            f"{path}: this run performs no retries. A failed comparison is a "
            "recorded outcome, and re-running only the failures would produce a "
            "run whose results came from two attempts (docs/adr/0013)"
        )

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

    preparation_set_id = require_yaml_non_empty_str(
        preparation, "set_id", where=f"{path} preparation"
    )
    preparation_set_fingerprint = require_yaml_non_empty_str(
        preparation, "set_fingerprint", where=f"{path} preparation"
    )
    transform_profile_id = require_yaml_non_empty_str(
        preparation, "transform_profile_id", where=f"{path} preparation"
    )
    transform_profile_fingerprint = require_yaml_non_empty_str(
        preparation, "transform_profile_fingerprint", where=f"{path} preparation"
    )
    target_ppi = require_yaml_exact_int(
        preparation, "target_ppi", where=f"{path} preparation", minimum=1
    )

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

    participating = require_yaml_exact_int(
        expected, "participating_images", where=f"{path} expected", minimum=1
    )
    if participating % len(releases):
        raise ConfigurationError(
            f"{path}: {participating} participating images do not divide evenly "
            f"across {len(releases)} releases"
        )

    source_ppi = require_yaml_mapping(expected, "source_ppi", where=f"{path} expected")
    build_root = require_yaml_non_empty_str(build, "build_root", where=f"{path} build")

    return NbisCanonical500ExperimentConfig(
        experiment_id=require_yaml_non_empty_str(document, "experiment_id", where=path),
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
        reference=ReferenceRunIdentity(
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
        ),
        preparation_set_id=preparation_set_id,
        preparation_set_fingerprint=preparation_set_fingerprint,
        transform_profile_id=transform_profile_id,
        transform_profile_fingerprint=transform_profile_fingerprint,
        target_ppi=target_ppi,
        expected_jobs=require_yaml_exact_int(
            expected, "jobs", where=f"{path} expected", minimum=1
        ),
        expected_per_release=require_yaml_exact_int(
            expected, "pairs_per_release", where=f"{path} expected", minimum=1
        ),
        expected_per_stage=require_yaml_exact_int(
            expected, "pairs_per_stage", where=f"{path} expected", minimum=1
        ),
        expected_per_release_stage=require_yaml_exact_int(
            expected, "pairs_per_release_stage", where=f"{path} expected", minimum=1
        ),
        expected_releases=tuple(str(item) for item in releases),
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
        execution_profile=profile,
        materialization_policy=require_yaml_non_empty_str(
            runtime, "materialization_policy", where=f"{path} runtime"
        ),
        research_mode=require_yaml_bool(
            runtime, "research_mode", where=f"{path} runtime"
        ),
        nbis_build_id=require_yaml_non_empty_str(
            build, "nbis_build_id", where=f"{path} build"
        ),
        build_root=Path(build_root),
    )


def build_nbis_canonical500_spec(
    config: NbisCanonical500ExperimentConfig,
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
class NbisCanonical500ExperimentState:
    """How far along Stage 7C is, and whether it may be called finished.

    Two independent readings, combined by ``and``. The research state says the
    evidence chain is complete and re-verifies from the files; the alignment
    report says the run was given the reference run's own inputs. A run can be
    ``RESEARCH_READY`` and misaligned — that is precisely the failure this stage
    exists to make impossible to publish (spec section 36).
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


# ------------------------------------------------------------------- the build


def require_pinned_build(
    build_directory: Path | None,
    *,
    config: NbisCanonical500ExperimentConfig,
    repository_root: Path,
) -> Path:
    """One named, certified build, or nothing.

    Raises:
        ConfigurationError: no directory was given, or it is not the build this
            experiment is defined against. There is deliberately no search: the
            newest build, the first in lexicographic order and "the one that is
            there" are all ways for a rebuild to silently change which
            executables 6,000 results are attributed to (docs/adr/0053).
        ResearchPreflightError: the build is present but not certified.
    """
    if build_directory is None:
        expected_path = f"{config.build_root.as_posix()}/{config.nbis_build_id}"
        raise ConfigurationError(
            "this experiment is defined against NBIS build "
            f"{config.nbis_build_id}; pass it explicitly, as "
            "development_overrides={'build_directory': Path('"
            + expected_path
            + "')}. No build is selected automatically (spec section 12)"
        )
    directory = Path(build_directory)
    if not directory.is_absolute():
        directory = (Path(repository_root) / directory).resolve()
    if directory.name != config.nbis_build_id:
        raise ConfigurationError(
            f"the pinned build directory is {directory.name!r}, but this "
            f"experiment is defined against build {config.nbis_build_id!r}. A "
            "different build is a different runtime and needs a different run"
        )
    if not (directory / BUILD_MANIFEST_FILENAME).is_file():
        raise ConfigurationError(
            f"{directory.name} carries no {BUILD_MANIFEST_FILENAME}; build it with "
            "'python integrations/nbis/build.py build' and certify it with "
            "'... test' before a research run may pin it"
        )
    require_certified_build(
        NbisConfig(
            mindtct_executable=directory / "bin" / "mindtct",
            bozorth3_executable=directory / "bin" / "bozorth3",
            build_manifest=directory / BUILD_MANIFEST_FILENAME,
        ),
        repository_root=Path(repository_root),
    )
    return directory


# ------------------------------------------------------------------- alignment


def verify_nbis_canonical500_alignment(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    dataset_root: Path | None = None,
    config: NbisCanonical500ExperimentConfig | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
    require_clean: bool = True,
) -> CanonicalRunAlignmentReport:
    """Prove the NBIS run is over the reference run's own inputs, row by row.

    Loads both sides from the workspace's manifests and compares them; see
    :mod:`fpbench.experiments.canonical_run_alignment` for what "compares" means
    here, which is every field of every pair and every field of every prepared
    image, never a count against a count (spec section 6).

    Args:
        run_id: The NBIS run to align. When it is ``None`` and no run has been
            prepared yet, the candidate side is the pair manifest as the planner
            will order it — which is what preparation checks *before* creating a
            run (spec section 24).

    Raises:
        ResearchPreflightError: ``require_clean`` and the alignment is not clean.
    """
    config = config or load_nbis_canonical500_config(repository_root=repository_root)
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


def prepare_nbis_canonical500_run(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    dataset_root: Path | None = None,
    config: NbisCanonical500ExperimentConfig | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    development_overrides: Mapping[str, object] | None = None,
) -> PreparedAlgorithmResearchRun:
    """Check everything, then write the run, the plan and the runtime binding.

    In order, and each step is a place the whole thing stops (spec section 24):

    1. the working tree is clean and committed;
    2. the named build is present and certified;
    3. the prepared-image set verifies and is ``PREPARATION_READY``;
    4. the reference SourceAFIS run is ``RESEARCH_READY``;
    5. its result set is the one this experiment names;
    6. the pair manifest is loaded — not rebuilt;
    7. the alignment report is derived;
    8. it is clean, or nothing further happens;
    9. the engine creates the run;
    10. the engine plans 6,000 jobs;
    11. the alignment is re-derived against the plan that now exists.

    No raw result is written here, and none can be: this function never reaches
    the executor.
    """
    workspace = Path(workspace)
    repository_root = Path(repository_root)
    config = config or load_nbis_canonical500_config(repository_root=repository_root)

    # 1. A research run is created from a commit or not at all (docs/adr/0017).
    capture_research_provenance(repository_root)

    # 2. One named build, verified before anything else touches it.
    overrides = dict(development_overrides or {})
    unknown = sorted(set(overrides) - {"build_directory"})
    if unknown:
        raise ConfigurationError(
            f"unknown development overrides for {EXPERIMENT_ID}: {unknown}"
        )
    build_directory = require_pinned_build(
        overrides.get("build_directory"),  # type: ignore[arg-type]
        config=config,
        repository_root=repository_root,
    )

    # 3-8. The inputs, and the proof they are the reference run's inputs.
    context = _load_alignment_context(
        workspace=workspace,
        dataset_root=dataset_root,
        config=config,
        repository_root=repository_root,
        run_id=None,
    )
    require_clean_alignment(context.report)
    require_execution_controls_equal(
        context.reference_run,
        build_nbis_canonical500_spec(config),
        reference_materialization_policy=context.reference_materialization_policy,
    )

    # 9-10. The general engine. Everything algorithm-specific arrives through
    # the NBIS integration; nothing about this run is orchestrated here.
    prepared = prepare_nbis_research_run(
        spec=build_nbis_canonical500_spec(config),
        preparer_factory=_preparer_factory,
        workspace=workspace,
        dataset_root=dataset_root,
        repository_root=repository_root,
        build_directory=build_directory,
        expected_input_set=SD300_CANONICAL500_INPUT_SET,
    )

    # 11. The same comparison again, now against a plan that exists.
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


def execute_nbis_canonical500_run(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    dataset_root: Path | None = None,
    config: NbisCanonical500ExperimentConfig | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
    max_new_jobs: int | None = None,
) -> RunExecutionSummary:
    """Execute some or all of the prepared run, one comparison at a time.

    May be stopped and resumed as often as necessary. A result that is already
    stored is verified and skipped, never re-executed and never overwritten, so
    resuming cannot change a number that has already been recorded
    (spec section 26, docs/adr/0005).
    """
    config = config or load_nbis_canonical500_config(repository_root=repository_root)
    return execute_nbis_research_run(
        spec=build_nbis_canonical500_spec(config),
        preparer_factory=_preparer_factory,
        workspace=Path(workspace),
        dataset_root=dataset_root,
        repository_root=Path(repository_root),
        run_id=run_id,
        max_new_jobs=max_new_jobs,
        expected_input_set=SD300_CANONICAL500_INPUT_SET,
    )


def inspect_nbis_canonical500_experiment(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    dataset_root: Path | None = None,
    config: NbisCanonical500ExperimentConfig | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
) -> NbisCanonical500ExperimentState:
    """Report where Stage 7C stands. Never writes.

    Both halves are re-derived from the sources rather than read back: the
    research state re-verifies the receipt and the marker against the stored
    results, and the alignment report is rebuilt from the two pair manifests and
    the prepared-set entries. A stored alignment report that was edited *and*
    re-fingerprinted consistently still fails here, because it is compared with
    one derived from the files it describes (spec section 37).
    """
    workspace = Path(workspace)
    repository_root = Path(repository_root)
    config = config or load_nbis_canonical500_config(repository_root=repository_root)
    spec = build_nbis_canonical500_spec(config)

    research_state = inspect_nbis_research_experiment(
        spec=spec,
        preparer_factory=_preparer_factory,
        workspace=workspace,
        dataset_root=dataset_root,
        repository_root=repository_root,
        run_id=run_id,
        expected_input_set=SD300_CANONICAL500_INPUT_SET,
    )
    report = verify_nbis_canonical500_alignment(
        workspace=workspace,
        dataset_root=dataset_root,
        config=config,
        repository_root=repository_root,
        run_id=research_state.run_id,
        require_clean=False,
    )

    issues: list[IntegrityIssue] = []
    issues.extend(
        _compare_stored_alignment(workspace, research_state.run_id, report)
    )
    issues.extend(_check_no_derivations(workspace, research_state.run_id))
    issues.extend(
        _compare_stage_7c_finalization(
            workspace=workspace,
            run_id=research_state.run_id,
            config=config,
            derived_alignment=report,
        )
    )
    return NbisCanonical500ExperimentState(
        research_state=research_state,
        alignment_report=report,
        issues=tuple(issues),
    )


def finalize_nbis_canonical500_run(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    dataset_root: Path | None = None,
    config: NbisCanonical500ExperimentConfig | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
) -> ResearchReceipt:
    """Revalidate everything, publish the receipt, and prove the alignment held.

    The engine does the audit, the result set, the NBIS validation, the receipt
    and the marker — and it raises unless the run reaches ``RESEARCH_READY``, so
    by the time it returns, that half of Stage 7C readiness is established. What
    this function adds is the half the engine has no business knowing about: the
    alignment is re-derived from the manifests, it is compared with the one
    preparation stored, and finalization does not happen unless both are clean
    and identical (spec section 35).

    **Why the combined check is not a second full inspection.** The engine's last
    act is writing the committable receipt into ``evidence/``. A check that
    re-captured software provenance afterwards would refuse the working tree
    finalization had just modified, and would do so on every successful run. The
    independent combined reading is
    :func:`inspect_nbis_canonical500_experiment`, run once the evidence has been
    committed — which is the documented sequence and the one the workspace gate
    exercises (spec sections 45 and 48, docs/adr/0017).
    """
    workspace = Path(workspace)
    repository_root = Path(repository_root)
    config = config or load_nbis_canonical500_config(repository_root=repository_root)
    resolved = run_id or read_run_pointer(workspace, config.experiment_id)
    verifier_software = capture_research_provenance(repository_root)

    context = _load_alignment_context(
        workspace=workspace,
        dataset_root=dataset_root,
        config=config,
        repository_root=repository_root,
        run_id=resolved,
    )
    require_clean_alignment(context.report)
    require_execution_controls_equal(
        context.reference_run,
        build_nbis_canonical500_spec(config),
        reference_materialization_policy=context.reference_materialization_policy,
    )
    stored_issues = tuple(_compare_stored_alignment(workspace, resolved, context.report))
    if stored_issues:
        raise ResearchPreflightError(
            "the alignment report stored at preparation is not the one this "
            f"workspace now derives: {stored_issues[0].message}"
        )

    receipt = finalize_nbis_research_run(
        spec=build_nbis_canonical500_spec(config),
        preparer_factory=_preparer_factory,
        workspace=workspace,
        dataset_root=dataset_root,
        repository_root=repository_root,
        run_id=resolved,
        expected_input_set=SD300_CANONICAL500_INPUT_SET,
    )

    # The other half of readiness, over the artefacts the engine has just
    # written. Nothing downstream of a raw score may exist for this run
    # (docs/adr/0052).
    remaining = tuple(_check_no_derivations(workspace, resolved))
    if remaining or not context.report.is_clean:
        raise ResearchPreflightError(
            f"run {resolved} finalised but Stage 7C is not ready: alignment "
            f"{'clean' if context.report.is_clean else 'not clean'}, "
            f"issues {[issue.message for issue in remaining][:2]}"
        )
    marker = _build_stage_7c_finalization(
        workspace=workspace,
        run_id=resolved,
        config=config,
        derived_alignment=context.report,
        verifier_source_commit=verifier_software.source_revision,
        verifier_source_tree_clean=verifier_software.source_tree_clean,
        created_utc=_utc_now(),
    )
    _write_stage_7c_finalization(workspace, resolved, marker)
    return receipt


def refresh_nbis_canonical500_stage_finalization(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    dataset_root: Path | None = None,
    config: NbisCanonical500ExperimentConfig | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
) -> Stage7CFinalization:
    """Re-derive alignment and its Stage 7C marker without rerunning NBIS.

    This is the migration path when verifier code changes after a completed run.
    It requires a clean committed verifier tree, rechecks the general research
    chain and every alignment source, rewrites only regenerable Stage 7C
    artefacts, and never opens or executes a raw comparison job.
    """
    workspace = Path(workspace)
    repository_root = Path(repository_root)
    config = config or load_nbis_canonical500_config(repository_root=repository_root)
    resolved = run_id or read_run_pointer(workspace, config.experiment_id)
    verifier_software = capture_research_provenance(repository_root)

    research_state = inspect_nbis_research_experiment(
        spec=build_nbis_canonical500_spec(config),
        preparer_factory=_preparer_factory,
        workspace=workspace,
        dataset_root=dataset_root,
        repository_root=repository_root,
        run_id=resolved,
        expected_input_set=SD300_CANONICAL500_INPUT_SET,
    )
    if not research_state.is_research_ready:
        raise ResearchPreflightError(
            f"run {resolved} is not RESEARCH_READY: {list(research_state.issues)[:3]}"
        )
    report = verify_nbis_canonical500_alignment(
        workspace=workspace,
        dataset_root=dataset_root,
        config=config,
        repository_root=repository_root,
        run_id=resolved,
        require_clean=True,
    )
    downstream = tuple(_check_no_derivations(workspace, resolved))
    if downstream:
        raise ResearchPreflightError(
            f"run {resolved} has downstream derivations: "
            f"{[issue.message for issue in downstream][:2]}"
        )

    _write_alignment_report(workspace, resolved, report)
    marker = _build_stage_7c_finalization(
        workspace=workspace,
        run_id=resolved,
        config=config,
        derived_alignment=report,
        verifier_source_commit=verifier_software.source_revision,
        verifier_source_tree_clean=verifier_software.source_tree_clean,
        created_utc=_utc_now(),
    )
    _write_stage_7c_finalization(workspace, resolved, marker)
    return marker


# ------------------------------------------------------------------- evidence


def publish_nbis_canonical500_evidence(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    repository_root: Path = REPOSITORY_ROOT,
    config: NbisCanonical500ExperimentConfig | None = None,
    run_id: str | None = None,
) -> tuple[Path, ...]:
    """Copy the committable artefacts out of the workspace.

    Copies; it does not compose. The receipt, the marker, the alignment report
    and the operational summary are already written, already sanitised and
    already fingerprinted — building a second version of any of them here would
    be publishing something no check has ever seen (spec sections 22 and 38).

    The one file assembled here is ``runtime-provenance.json``, and it is an
    index rather than a claim: every value in it is copied out of the stored run
    definition, the stored runtime reference and the stored alignment report, so
    that a reader can see the three runtime digests and the NBIS build manifest
    fingerprint without opening a workspace. It carries no score, no threshold
    and no path (spec section 39).

    ``README.md`` is written by hand beside them, because a human has to say
    what the run was for.
    """
    workspace = Path(workspace)
    repository_root = Path(repository_root)
    config = config or load_nbis_canonical500_config(repository_root=repository_root)
    resolved = run_id or read_run_pointer(workspace, config.experiment_id)

    from fpbench.experiments.operational_summary import OPERATIONAL_SUMMARY_NAME

    result_store = ResultStore(workspace)
    directory = repository_root / EVIDENCE_DIRECTORY
    alignment = read_json(result_store.derived_path(resolved, ALIGNMENT_REPORT_NAME))
    written: list[Path] = []
    for name, value in (
        ("research-receipt.json", result_store.read_research_receipt(resolved)),
        (
            "research-finalization.json",
            result_store.read_research_finalization(resolved),
        ),
        (
            STAGE_7C_FINALIZATION_NAME,
            _read_stage_7c_finalization(workspace, resolved),
        ),
        ("alignment-report.json", alignment),
        (
            "operational-summary.json",
            read_json(result_store.derived_path(resolved, OPERATIONAL_SUMMARY_NAME)),
        ),
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


def _runtime_provenance(
    *,
    workspace: Path,
    run_id: str,
    config: NbisCanonical500ExperimentConfig,
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
    return {
        "schema_version": "1",
        "kind": "stage_7c_runtime_provenance",
        "statement": NO_CONCLUSION_STATEMENT,
        "experiment_id": config.experiment_id,
        "source_commit": run.environment.runtime.get("fpbench.source.revision"),
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
            "integration_id": run.environment.runtime.get("fpbench.integration.id"),
            "integration_fingerprint": run.environment.runtime.get(
                "fpbench.integration.fingerprint"
            ),
        },
        "runtime": {
            "bundle_id": reference.bundle_id,
            "bundle_fingerprint": reference.bundle_fingerprint,
            "asset_sha256s": dict(sorted(dict(reference.asset_sha256s).items())),
            "nbis_build_manifest_fingerprint": dependencies.get(
                "nbis.build_manifest_fingerprint"
            ),
            "nbis_version": dependencies.get("nbis.version"),
            "nbis_png_ppi_policy": dependencies.get("nbis.png_ppi_policy"),
            "nbis_official_tests_passed": dependencies.get(
                "nbis.official_tests.passed"
            ),
            "nbis_official_tests_suite": dependencies.get("nbis.official_tests.suite"),
            "nbis_target": "/".join(
                str(run.environment.runtime.get(key) or "")
                for key in ("nbis.target_os", "nbis.target_architecture")
            ),
            "nbis_compiler_id": run.environment.runtime.get("nbis.compiler_id"),
        },
        "execution_profile": {
            "profile_id": run.execution_profile.profile_id,
            "profile_hash": run.execution_profile_hash,
            "preparer_id": run.execution_profile.preparer_id,
            "timeout_seconds": str(run.execution_profile.timeout_seconds),
            "deterministic_seed": str(run.execution_profile.deterministic_seed),
            "replicate_index": str(run.replicate_index),
        },
        "inputs": {
            "protocol_id": run.protocol_id,
            "cohort_id": str(run.cohort_id),
            "pair_manifest_hash": run.pair_manifest_hash,
            "preparation_set_id": config.preparation_set_id,
            "preparation_set_fingerprint": config.preparation_set_fingerprint,
            "transform_profile_id": config.transform_profile_id,
            "transform_profile_fingerprint": config.transform_profile_fingerprint,
        },
        "reference": {
            "run_id": config.reference.run_id,
            "plan_id": config.reference.plan_id,
            "result_set_id": config.reference.result_set_id,
        },
        "alignment_fingerprint": alignment.get("alignment_fingerprint"),
    }


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
    config: NbisCanonical500ExperimentConfig,
    repository_root: Path,
    run_id: str | None,
) -> _AlignmentContext:
    """Load both sides once, from the manifests, and compare them."""
    spec = build_nbis_canonical500_spec(config)

    # The pair manifest is *read*. ``allow_creation=False`` is what makes that
    # true rather than intended: with it, a workspace missing the manifest is an
    # error instead of an invitation to build a new one (spec section 5).
    inputs = load_sd300_inputs(
        workspace=workspace,
        dataset_root=dataset_root,
        dataset_config=config.dataset_config,
        protocol_config=config.protocol_config,
        require_verified_checksums=config.require_verified_checksums,
        allow_creation=False,
    )

    preparer = _preparer_factory(workspace, spec)
    preparer.preflight()
    entries = preparer.prepared_entries()

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
        from fpbench.storage.plan_store import PlanStore

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
    config: NbisCanonical500ExperimentConfig,
    run_id: str,
    plan: Any,
    result_set_id: str | None,
) -> CanonicalRunAlignmentReport:
    """The same comparison, restated against a plan that now exists.

    Cheap, because both sides are already in memory. It matters because the
    order checked before ``prepare`` was the order the planner *would* impose,
    and this is the order it did (spec section 24, step 11).
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
    one function wide. Stage 7C reads the reference run's *readiness*; it does
    not import its adapter, its decision profile or its scores (spec section 41).
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
        return RuntimeBundleStore(workspace).read_bundle(
            reference.bundle_id
        ).materialization_policy
    except Exception:  # pragma: no cover - absence is reported by the alignment
        return None


def _result_set_id(workspace: Path, run_id: str) -> str | None:
    from fpbench.storage.result_set_store import ResultSetStore

    try:
        return ResultSetStore(workspace).read_manifest(run_id).result_set_id
    except Exception:
        return None


def _write_alignment_report(
    workspace: Path, run_id: str, report: CanonicalRunAlignmentReport
) -> Path:
    return ResultStore(workspace).write_derived(
        run_id, ALIGNMENT_REPORT_NAME, report
    )


def _build_stage_7c_finalization(
    *,
    workspace: Path,
    run_id: str,
    config: NbisCanonical500ExperimentConfig,
    derived_alignment: CanonicalRunAlignmentReport,
    verifier_source_commit: str,
    verifier_source_tree_clean: bool,
    created_utc: str,
) -> Stage7CFinalization:
    result_store = ResultStore(workspace)
    alignment_path = result_store.derived_path(run_id, ALIGNMENT_REPORT_NAME)
    stored_alignment = read_json(alignment_path)
    if stored_alignment.get("alignment_fingerprint") != (
        derived_alignment.alignment_fingerprint
    ):
        raise ResearchPreflightError(
            "the stored alignment report is not the report being finalised"
        )

    run = result_store.read_run(run_id)
    result_set = ResultSetStore(workspace).verify_result_set(run_id)
    receipt = result_store.read_research_receipt(run_id)
    research_finalization = result_store.read_research_finalization(run_id)
    claims = {
        "schema_version": STAGE_7C_FINALIZATION_SCHEMA_VERSION,
        "kind": STAGE_7C_FINALIZATION_KIND,
        "run_id": run.run_id,
        "run_fingerprint": run.run_fingerprint,
        "result_set_id": result_set.result_set_id,
        "result_set_fingerprint": result_set.result_set_fingerprint,
        "research_receipt_fingerprint": research_receipt_fingerprint(receipt),
        "research_receipt_content_hash": research_receipt_content_hash(receipt),
        "research_finalization_fingerprint": (
            research_finalization.finalization_fingerprint
        ),
        "reference_run_id": config.reference.run_id,
        "reference_plan_id": config.reference.plan_id,
        "reference_result_set_id": config.reference.result_set_id,
        "alignment_fingerprint": derived_alignment.alignment_fingerprint,
        "alignment_report_content_hash": alignment_report_content_hash(
            stored_alignment
        ),
        "verifier_source_commit": verifier_source_commit,
        "verifier_source_tree_clean": verifier_source_tree_clean,
    }
    fingerprint = stage_7c_finalization_fingerprint(claims)
    return Stage7CFinalization(
        **claims,
        stage_7c_finalization_fingerprint=fingerprint,
        created_utc=created_utc,
    )


def _write_stage_7c_finalization(
    workspace: Path, run_id: str, marker: Stage7CFinalization
) -> Path:
    return write_json(
        ResultStore(workspace).derived_path(run_id, STAGE_7C_FINALIZATION_NAME),
        marker,
    )


def _read_stage_7c_finalization(
    workspace: Path, run_id: str
) -> Stage7CFinalization:
    from fpbench.core.errors import StorageError

    path = ResultStore(workspace).derived_path(run_id, STAGE_7C_FINALIZATION_NAME)
    if not path.is_file():
        raise StorageError(f"Stage 7C finalization not found: {path}")
    try:
        return Stage7CFinalization(**read_json(path))
    except (KeyError, TypeError, ValueError) as exc:
        raise StorageError(f"{path}: unreadable Stage 7C finalization ({exc})") from exc


def _compare_stage_7c_finalization(
    *,
    workspace: Path,
    run_id: str,
    config: NbisCanonical500ExperimentConfig,
    derived_alignment: CanonicalRunAlignmentReport,
) -> list[IntegrityIssue]:
    from fpbench.core.enums import IntegrityIssueCode, IntegritySeverity
    from fpbench.core.errors import StorageError

    path = ResultStore(workspace).derived_path(run_id, STAGE_7C_FINALIZATION_NAME)
    relative = path.relative_to(workspace).as_posix()
    try:
        stored = _read_stage_7c_finalization(workspace, run_id)
    except StorageError as exc:
        return [
            IntegrityIssue(
                code=IntegrityIssueCode.PLAN_CONFLICT,
                severity=IntegritySeverity.ERROR,
                message=str(exc),
                relative_path=relative,
            )
        ]
    try:
        expected = _build_stage_7c_finalization(
            workspace=workspace,
            run_id=run_id,
            config=config,
            derived_alignment=derived_alignment,
            verifier_source_commit=stored.verifier_source_commit,
            verifier_source_tree_clean=stored.verifier_source_tree_clean,
            created_utc=stored.created_utc,
        )
    except (OSError, ResearchPreflightError, StorageError, ValueError) as exc:
        return [
            IntegrityIssue(
                code=IntegrityIssueCode.PLAN_CONFLICT,
                severity=IntegritySeverity.ERROR,
                message=f"cannot re-derive Stage 7C finalization: {exc}",
                relative_path=relative,
            )
        ]
    if to_plain(stored) == to_plain(expected):
        return []
    return [
        IntegrityIssue(
            code=IntegrityIssueCode.PLAN_CONFLICT,
            severity=IntegritySeverity.ERROR,
            message=(
                "the stored Stage 7C finalization is not the complete chain "
                "this workspace now derives"
            ),
            relative_path=relative,
        )
    ]


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
    permitted_experiments: frozenset[str] = None,  # type: ignore[assignment]
) -> list[IntegrityIssue]:
    """Nothing derives from this run except the experiments entitled to.

    Stage 7C itself produces raw scores and nothing else, and while it was the
    last word that meant *no* derivation could exist: a decision set over this
    run would have meant somebody chose a threshold for BOZORTH3, and there was
    no such threshold to choose (docs/adr/0052).

    Stage 7D chose one, from NIST's own documentation, and wrote it into a
    committed profile. So the rule is now the one it always meant: a derivation
    of this run must be *accounted for* by a named experiment, and anything else
    is still a defect. The named experiments are data — see
    :data:`PERMITTED_DOWNSTREAM_EXPERIMENTS` — and an unrecognised one still
    fails, which is what makes this a check rather than a comment
    (docs/adr/0057, spec sections 27 and 82).
    """
    from fpbench.core.derivation_models import DerivationDefinition
    from fpbench.core.enums import IntegrityIssueCode, IntegritySeverity
    from fpbench.core.evaluation_models import MetricDerivationDefinition
    from fpbench.core.errors import StorageError
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
                        f"from run {run_id} under experiment {owner!r}, which is "
                        "not one this run is derived by"
                    ),
                    relative_path=path.relative_to(workspace).as_posix(),
                )
            )

    # The per-run artefact directories. A directory name cannot say who owns it,
    # so it is only a finding while *nothing* is entitled to have written one —
    # once a permitted experiment has pinned a definition over this run, the
    # definition-level check above is the one with teeth.
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
                            "applied outside an experiment (docs/adr/0052)"
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
            relative = paired_store.definition_path(paired_id).relative_to(
                workspace
            ).as_posix()
            if paired_store.has_receipt(paired_id):
                try:
                    receipt = paired_store.read_receipt(paired_id)
                except StorageError as exc:
                    issues.append(
                        IntegrityIssue(
                            code=IntegrityIssueCode.PLAN_CONFLICT,
                            severity=IntegritySeverity.ERROR,
                            message=f"unreadable paired receipt: {exc}",
                            relative_path=paired_store.receipt_path(paired_id)
                            .relative_to(workspace)
                            .as_posix(),
                        )
                    )
                    continue
                cites_run = run_id in {
                    receipt.native_run_id,
                    receipt.canonical_run_id,
                }
            else:
                try:
                    definition = paired_store.read_definition(paired_id)
                except StorageError as exc:
                    try:
                        cites_run = _legacy_paired_definition_cites_run(
                            paired_store.definition_path(paired_id), run_fingerprint
                        )
                    except (KeyError, TypeError, ValueError) as legacy_exc:
                        issues.append(
                            IntegrityIssue(
                                code=IntegrityIssueCode.PLAN_CONFLICT,
                                severity=IntegritySeverity.ERROR,
                                message=(
                                    f"unreadable paired definition: {exc}; "
                                    f"source identities invalid: {legacy_exc}"
                                ),
                                relative_path=relative,
                            )
                        )
                        continue
                else:
                    cites_run = run_fingerprint in {
                        definition.native_run_fingerprint,
                        definition.canonical_run_fingerprint,
                    }
            if cites_run:
                issues.append(
                    IntegrityIssue(
                        code=IntegrityIssueCode.PLAN_CONFLICT,
                        severity=IntegritySeverity.ERROR,
                        message=(
                            f"paired evaluation {paired_id} cites run {run_id}; "
                            "Stage 7C has no paired evaluation"
                        ),
                        relative_path=relative,
                    )
                )
    return issues


def _owning_experiment_id(definition_path: Path, derivations_root: Path) -> str:
    """Which experiment's directory a definition file sits under.

    ``derivations/<experiment_id>/<run_id>/...``, so the first path component
    below the root is the answer. Read from the layout rather than from the
    file's contents on purpose: a definition does not record which experiment
    pinned it, and the directory is the only place that fact exists.
    """
    try:
        relative = definition_path.relative_to(derivations_root)
    except ValueError:  # pragma: no cover - the caller globbed from this root
        return ""
    return relative.parts[0] if relative.parts else ""


def _legacy_paired_definition_cites_run(path: Path, run_fingerprint: str) -> bool:
    """Read only source identities from a pre-current paired definition.

    Finalised comparisons are identified from their modelled receipt. Current
    unfinished comparisons are identified from ``PairedEvaluationDefinition``.
    This narrow fallback keeps older unfinished definitions readable after the
    definition fingerprint schema changed: it parses two named JSON fields,
    validates them as complete digests and compares exact identities. It never
    greps or searches arbitrary JSON text.
    """
    payload = read_json(path)
    fingerprints: list[str] = []
    for name in ("native_run_fingerprint", "canonical_run_fingerprint"):
        value = str(payload[name]).strip().lower()
        if len(value) != 64 or not set(value) <= set("0123456789abcdef"):
            raise ValueError(f"{name} is not a 64-character hexadecimal digest")
        fingerprints.append(value)
    return run_fingerprint in fingerprints


def _load_downstream_definition(
    payload: Mapping[str, Any], *, decision_model: Any, metric_model: Any
) -> Any:
    errors: list[str] = []
    for model in (decision_model, metric_model):
        try:
            return model(**payload)
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"{model.__name__}: {exc}")
    raise StorageError("; ".join(errors))


def _load_execution_profile(path: Path) -> ExecutionProfile:
    """Read the reference run's execution profile, unchanged.

    A copy of the loader in the SourceAFIS wrapper would be a second place for
    "what a canonical execution profile is" to live, so this one reads the same
    file with the same rules: every parameter is a string, because the profile
    hash is taken over exactly those strings.
    """
    from fpbench.core.serialization import require_exact_int

    path = Path(path)
    if not path.is_file():
        raise ConfigurationError(f"execution profile config not found: {path}")
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(document, Mapping):
        raise ConfigurationError(f"{path}: expected a mapping at the top level")
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


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _require_no_decision_keys(document: Any, path: Path, trail: str = "") -> None:
    """Refuse a threshold anywhere in the document, at any depth."""
    if isinstance(document, Mapping):
        for key, value in document.items():
            name = str(key)
            where = f"{trail}.{name}" if trail else name
            if name.lower() in FORBIDDEN_CONFIG_KEYS:
                raise ConfigurationError(
                    f"{path}: {where!r} is not a Stage 7C setting. This stage "
                    "publishes raw BOZORTH3 scores; where the boundary between "
                    "MATCH and NON_MATCH sits on that scale is stage 7D's "
                    "question, and SourceAFIS's documented 40 is a number on a "
                    "different scale entirely (docs/adr/0052)"
                )
            _require_no_decision_keys(value, path, where)
    elif isinstance(document, (list, tuple)):
        for index, item in enumerate(document):
            _require_no_decision_keys(item, path, f"{trail}[{index}]")
