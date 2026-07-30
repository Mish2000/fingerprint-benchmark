"""The 6,000-comparison SourceAFIS run, in four commands.

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

This module is allowed to know things the rest of the harness is not. It knows
that SD300A is 500 ppi, that the protocol yields 6,000 pairs, that
``sourceafis_bridge_jar`` is the role a SourceAFIS bundle holds. Those are facts
about *this experiment*, and the entire reason for an ``experiments`` package is
that they have somewhere to live other than the planner (docs/adr/0007).

One bookkeeping note. ``prepare`` writes a small pointer at
``workspace/experiments/<experiment_id>/current-run.json`` so the later commands
can find the run without being told its id. It is a bookmark, not evidence:
nothing downstream trusts anything in it beyond the run id, and every check
re-derives what it needs from the run's own manifests. Pass ``--run-id`` to
ignore it entirely.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from fpbench.adapters.sourceafis_java.adapter import ADAPTER_ID, SourceAfisJavaAdapter
from fpbench.adapters.sourceafis_java.config import (
    BRIDGE_JAR_ROLE,
    SourceAfisJavaConfig,
)
from fpbench.core.enums import ChecksumStatus, EnvironmentStatus, ProtocolStage
from fpbench.core.errors import ConfigurationError, ResearchPreflightError
from fpbench.core.execution_models import ExecutionProfile
from fpbench.core.execution_plan_models import ExecutionPlan
from fpbench.core.identifiers import ImageId, PairId
from fpbench.core.models import Cohort, ComparisonPair, ImageRecord
from fpbench.core.provenance_models import SoftwareProvenance
from fpbench.core.research_models import ResearchRunReceipt, ResearchRunState
from fpbench.core.result_models import RunDefinition
from fpbench.core.runtime_models import RunRuntimeReference, RuntimeBundleDefinition
from fpbench.core.serialization import read_json, write_json
from fpbench.datasets import create_provider, load_dataset_spec, summarise_subjects
from fpbench.datasets.sd300 import ppi_policy
from fpbench.execution.batch_runner import RunExecutionSummary, SequentialRunExecutor
from fpbench.execution.completion import RunCompletionService, build_run_completion
from fpbench.execution.planner import build_execution_plan
from fpbench.execution.progress import inspect_run_progress
from fpbench.execution.research import ResearchModeAdapter, inspect_research_run
from fpbench.execution.result_set import build_result_set
from fpbench.execution.run_definition import create_run_definition
from fpbench.execution.runner import SingleJobRunner
from fpbench.experiments.operational_summary import (
    build_operational_summary,
    write_operational_summary,
)
from fpbench.experiments.research_receipt import (
    build_research_receipt,
    write_evidence_copy,
)
from fpbench.experiments.sourceafis_validation import validate_sourceafis_result_set
from fpbench.imaging.identity import IdentityImagePreparer
from fpbench.protocols.sd300_protocol import SD300Protocol
from fpbench.storage.manifest_store import ManifestStore
from fpbench.storage.plan_store import PlanStore
from fpbench.storage.result_set_store import ResultSetStore
from fpbench.storage.result_store import ResultStore
from fpbench.storage.runtime_bundle_store import RuntimeBundleStore

__all__ = [
    "ExperimentConfig",
    "PreparedResearchRun",
    "load_experiment_config",
    "prepare_sourceafis_native_run",
    "execute_sourceafis_native_run",
    "inspect_sourceafis_native_run",
    "finalize_sourceafis_native_run",
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

#: The shape the supervisor's protocol implies: 50 subjects, ten anatomical
#: fingers, four stages, three releases. Asserted here rather than in the
#: planner, because the planner must stay true for any protocol and these
#: numbers are true only for this one.
EXPECTED_SUBJECTS = 50
EXPECTED_FINGERS = 10
EXPECTED_RELEASES = ("SD300A", "SD300B", "SD300C")
EXPECTED_PER_RELEASE = EXPECTED_SUBJECTS * EXPECTED_FINGERS * len(ProtocolStage)  # 2,000
EXPECTED_PER_STAGE = EXPECTED_SUBJECTS * EXPECTED_FINGERS * len(EXPECTED_RELEASES)  # 1,500
EXPECTED_JOBS = EXPECTED_PER_RELEASE * len(EXPECTED_RELEASES)  # 6,000

_POINTER_NAME = "current-run.json"


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


# -------------------------------------------------------------- prepared run


@dataclass(frozen=True, slots=True)
class PreparedResearchRun:
    """Everything ``execute`` and ``finalize`` need, already checked."""

    config: ExperimentConfig
    software: SoftwareProvenance

    dataset_root: Path
    workspace: Path

    protocol: SD300Protocol
    cohort: Cohort
    images: Mapping[ImageId, ImageRecord]
    pairs: Mapping[PairId, ComparisonPair]

    bundle: RuntimeBundleDefinition
    adapter: ResearchModeAdapter

    run: RunDefinition
    plan: ExecutionPlan
    runtime_reference: RunRuntimeReference

    @property
    def result_store(self) -> ResultStore:
        return ResultStore(self.workspace)

    @property
    def plan_store(self) -> PlanStore:
        return PlanStore(self.workspace)

    @property
    def result_set_store(self) -> ResultSetStore:
        return ResultSetStore(self.workspace)

    @property
    def bundle_store(self) -> RuntimeBundleStore:
        return RuntimeBundleStore(self.workspace)


# ---------------------------------------------------------------- prepare


def prepare_sourceafis_native_run(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    dataset_root: Path | None = None,
    config: ExperimentConfig | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    build_jar: Path | None = None,
) -> PreparedResearchRun:
    """Pin everything, check everything, and write the run, plan and binding.

    Idempotent: the same inputs a second time produce the same run id, the same
    plan id and the same bundle id, and nothing is overwritten.

    Raises:
        ResearchPreflightError: the source tree is dirty, the dataset is not
            fully verified, or the protocol does not yield the expected 6,000
            comparisons.
    """
    workspace = Path(workspace)
    config = config or load_experiment_config(repository_root=repository_root)

    # 1. Which code is about to run, and is all of it committed?
    software = capture_research_provenance(repository_root)

    # 2-3. The build jar has to work before it is worth copying anywhere.
    development = _development_config(
        repository_root=repository_root, build_jar=build_jar
    )
    build_report = SourceAfisJavaAdapter(development).validate_environment()
    if build_report.status is not EnvironmentStatus.READY:
        raise ResearchPreflightError(
            "the SourceAFIS bridge is not usable, so there is nothing to pin: "
            f"{build_report.message or 'no detail given'}"
        )

    # 4. Copy it somewhere a rebuild cannot reach.
    bundle_store = RuntimeBundleStore(workspace)
    bundle = bundle_store.materialize(
        adapter_id=ADAPTER_ID,
        assets={BRIDGE_JAR_ROLE: development.bridge_jar},
        materialization_policy=config.materialization_policy,
    )
    asset = bundle.asset(BRIDGE_JAR_ROLE)

    # 5-6. An adapter that will run the copy and nothing but the copy.
    adapter = _research_adapter(
        development=development,
        bundle=bundle,
        bundle_store=bundle_store,
        software=software,
    )
    environment = adapter.validate_environment()
    if environment.status is not EnvironmentStatus.READY:
        raise ResearchPreflightError(
            "the pinned SourceAFIS runtime is not usable: "
            f"{environment.message or 'no detail given'}"
        )

    # 7-8. The experiment itself.
    protocol, cohort, images, pairs, pair_metadata = _prepare_dataset(
        workspace=workspace,
        dataset_root=dataset_root,
        config=config,
    )
    _require_expected_shape(cohort=cohort, pairs=pairs, images=images)

    # 9-11. Derive and write.
    run = create_run_definition(
        protocol_id=protocol.protocol_id,
        cohort_id=cohort.cohort_id,
        pair_manifest_hash=pair_metadata["pair_manifest_hash"],
        algorithm=adapter.descriptor,
        environment=environment,
        execution_profile=config.execution_profile,
        replicate_index=config.replicate_index,
    )
    plan = build_execution_plan(
        run=run, pairs=pairs.values(), pair_manifest_metadata=pair_metadata
    )
    _require_expected_plan(plan)

    result_store = ResultStore(workspace)
    result_store.ensure_run(run)
    PlanStore(workspace).ensure_plan(plan)

    reference = RunRuntimeReference.create(
        run_id=run.run_id,
        run_fingerprint=run.run_fingerprint,
        environment_fingerprint=run.environment_fingerprint,
        bundle=bundle,
        created_utc=_utc_now(),
    )
    result_store.ensure_runtime_reference(reference)
    _write_pointer(
        workspace,
        config.experiment_id,
        {
            "experiment_id": config.experiment_id,
            "run_id": run.run_id,
            "plan_id": plan.plan_id,
            "runtime_bundle_id": bundle.bundle_id,
            "bridge_jar_sha256": asset.sha256,
            "source_commit": software.source_revision,
            "prepared_utc": _utc_now(),
        },
    )

    return PreparedResearchRun(
        config=config,
        software=software,
        dataset_root=Path(_dataset_root(config, dataset_root)),
        workspace=workspace,
        protocol=protocol,
        cohort=cohort,
        images=images,
        pairs=pairs,
        bundle=bundle,
        adapter=adapter,
        run=run,
        plan=plan,
        runtime_reference=reference,
    )


# ---------------------------------------------------------------- execute


def execute_sourceafis_native_run(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    dataset_root: Path | None = None,
    max_new_jobs: int | None = None,
    config: ExperimentConfig | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
) -> RunExecutionSummary:
    """Execute some or all of a prepared run, revalidating the runtime around it.

    The bundle's full digest is checked before the executor starts and again
    after it stops; the adapter's cheap file-identity check runs before every
    comparison in between. ``finalize=False`` throughout, so no completion can
    be written by an executor that does not know a runtime bundle exists
    (docs/adr/0018, docs/adr/0020).
    """
    prepared = _load_prepared(
        workspace=workspace,
        dataset_root=dataset_root,
        config=config,
        repository_root=repository_root,
        run_id=run_id,
    )

    bundle_store = prepared.bundle_store
    bundle_store.require_valid(prepared.runtime_reference.bundle_id)

    result_store = prepared.result_store
    executor = SequentialRunExecutor(
        plan=prepared.plan,
        pair_index=prepared.pairs,
        job_runner=SingleJobRunner(
            run=prepared.run,
            adapter=prepared.adapter,
            preparer=IdentityImagePreparer(),
            result_store=result_store,
            dataset_root=prepared.dataset_root,
            image_index=prepared.images,
            workspace_root=prepared.workspace,
        ),
        result_store=result_store,
        completion_service=RunCompletionService(result_store=result_store),
        plan_store=prepared.plan_store,
    )

    summary = executor.execute(max_new_jobs=max_new_jobs, finalize=False)

    bundle_store.require_valid(prepared.runtime_reference.bundle_id)

    progress = inspect_run_progress(
        run=prepared.run, plan=prepared.plan, result_store=result_store
    )
    result_store.write_derived(prepared.run.run_id, "progress.json", progress)
    write_operational_summary(
        result_store=result_store,
        run_id=prepared.run.run_id,
        summary=build_operational_summary(
            run=prepared.run,
            plan=prepared.plan,
            pairs=prepared.pairs,
            result_store=result_store,
            runtime_bundle_id=prepared.runtime_reference.bundle_id,
        ),
    )
    return summary


# ----------------------------------------------------------------- status


def inspect_sourceafis_native_run(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    dataset_root: Path | None = None,
    config: ExperimentConfig | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
) -> ResearchRunState:
    """Report how far along the evidence chain the run is. Never writes."""
    workspace = Path(workspace)
    config = config or load_experiment_config(repository_root=repository_root)
    resolved = run_id or _read_pointer(workspace, config.experiment_id)

    result_store = ResultStore(workspace)
    run = result_store.read_run(resolved)
    plan = PlanStore(workspace).read_plan(resolved)
    return inspect_research_run(run=run, plan=plan, result_store=result_store)


# --------------------------------------------------------------- finalize


def finalize_sourceafis_native_run(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    dataset_root: Path | None = None,
    config: ExperimentConfig | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
) -> ResearchRunReceipt:
    """Revalidate everything, then write the completion, result set and receipt.

    The order is the point (docs/adr/0020):

        runtime bundle → source revision → clean tree → core audit →
        SourceAFIS evidence → result set → completion → summary → receipt

    Any failure leaves all three durable artefacts unwritten. A run that cannot
    be finalised is not a run with a missing file; it is a run whose results
    cannot be attributed, and giving it a completion manifest would say
    otherwise.
    """
    prepared = _load_prepared(
        workspace=workspace,
        dataset_root=dataset_root,
        config=config,
        repository_root=repository_root,
        run_id=run_id,
    )
    result_store = prepared.result_store

    # 1-3. Runtime and source, before anything is written.
    prepared.bundle_store.require_valid(prepared.runtime_reference.bundle_id)

    # 4. The generic audit: is there one sound result per planned job?
    completion_service = RunCompletionService(result_store=result_store)
    audit = completion_service.audit(run=prepared.run, plan=prepared.plan)
    if not audit.is_clean:
        raise ResearchPreflightError(
            f"run {prepared.run.run_id} does not audit cleanly: "
            f"{[issue.code.value for issue in audit.errors][:5]}"
        )

    # 5. The SourceAFIS-specific one: is every result the run it claims to be?
    validation = validate_sourceafis_result_set(
        run=prepared.run,
        plan=prepared.plan,
        pairs=prepared.pairs,
        images=prepared.images,
        result_store=result_store,
        runtime_reference=prepared.runtime_reference,
    )
    if not validation.is_clean:
        raise ResearchPreflightError(
            f"run {prepared.run.run_id} failed SourceAFIS validation "
            f"({validation.blocking_failures} blocking failure(s)): "
            f"{[issue.code.value for issue in validation.errors][:5]}"
        )

    # 6. The identity the decision stage will cite.
    manifest, entries = build_result_set(
        run=prepared.run,
        plan=prepared.plan,
        result_store=result_store,
        runtime_reference=prepared.runtime_reference,
    )
    prepared.result_set_store.ensure_result_set(manifest, entries)

    # 7. Only now may the run be called verified.
    completion = build_run_completion(
        run=prepared.run, plan=prepared.plan, audit=audit
    )
    result_store.ensure_completion(completion)

    # 8. Cost and failures, derived and disposable.
    summary = build_operational_summary(
        run=prepared.run,
        plan=prepared.plan,
        pairs=prepared.pairs,
        result_store=result_store,
        result_set=manifest,
        runtime_bundle_id=prepared.runtime_reference.bundle_id,
    )
    write_operational_summary(
        result_store=result_store, run_id=prepared.run.run_id, summary=summary
    )

    # 9. The one artefact that leaves the workspace.
    receipt = build_research_receipt(
        run=prepared.run,
        plan=prepared.plan,
        pairs=prepared.pairs,
        software=prepared.software,
        runtime_reference=prepared.runtime_reference,
        result_set=manifest,
        audit=audit,
        validation=validation,
        completion=completion,
        dataset_id=prepared.protocol.dataset_id,
        timing_summary=_timing_summary(summary),
    )
    result_store.ensure_research_receipt(receipt)

    # 10. Read all of it back. A file that cannot be re-read is not evidence.
    result_store.read_completion(prepared.run.run_id)
    prepared.result_set_store.verify_result_set(prepared.run.run_id)
    result_store.read_research_receipt(prepared.run.run_id)

    state = inspect_research_run(
        run=prepared.run, plan=prepared.plan, result_store=result_store
    )
    if not state.is_research_ready:
        raise ResearchPreflightError(
            f"run {prepared.run.run_id} finalised but did not reach "
            f"RESEARCH_READY: {state.status.value} {list(state.issues)[:3]}"
        )

    write_evidence_copy(receipt, repository_root=Path(repository_root))
    return receipt


# ----------------------------------------------------------------- helpers


def capture_research_provenance(repository_root: Path) -> SoftwareProvenance:
    """The clean, committed revision a research run must be started from."""
    from fpbench.provenance.software import capture_software_provenance

    return capture_software_provenance(
        repository_root=Path(repository_root), require_clean=True
    )


def _development_config(
    *, repository_root: Path, build_jar: Path | None
) -> SourceAfisJavaConfig:
    settings: dict[str, Any] = {"project_root": Path(repository_root)}
    if build_jar is not None:
        settings["bridge_jar"] = Path(build_jar)
    return SourceAfisJavaConfig(**settings)


def _research_adapter(
    *,
    development: SourceAfisJavaConfig,
    bundle: RuntimeBundleDefinition,
    bundle_store: RuntimeBundleStore,
    software: SoftwareProvenance,
) -> ResearchModeAdapter:
    asset = bundle.asset(BRIDGE_JAR_ROLE)
    pinned = development.pinned_to(
        bridge_jar=bundle_store.asset_path(bundle.bundle_id, BRIDGE_JAR_ROLE),
        runtime_bundle_id=bundle.bundle_id,
        runtime_bundle_fingerprint=bundle.bundle_fingerprint,
        expected_bridge_jar_sha256=asset.sha256,
        expected_bridge_jar_size=asset.size_bytes,
        fpbench_source_revision=software.source_revision,
    )
    return ResearchModeAdapter(
        delegate=SourceAfisJavaAdapter(pinned),
        software=software,
        runtime_bundle=bundle,
    )


def _dataset_root(config: ExperimentConfig, override: Path | None) -> Path:
    spec = load_dataset_spec(config.dataset_config, root_override=override)
    return spec.root


def _prepare_dataset(
    *,
    workspace: Path,
    dataset_root: Path | None,
    config: ExperimentConfig,
) -> tuple[
    SD300Protocol,
    Cohort,
    Mapping[ImageId, ImageRecord],
    Mapping[PairId, ComparisonPair],
    Mapping[str, str],
]:
    """Build the manifests once, then read them for ever after.

    The first invocation hashes 113 GB to prove the delivery matches NIST's own
    digests, and writes an immutable manifest recording that it did. Every
    invocation after that reads the manifest: the evidence is the manifest, and
    re-hashing to produce the same answer would be a ritual rather than a check
    (docs/adr/0005).
    """
    protocol = SD300Protocol.from_config_file(config.protocol_config)
    spec = load_dataset_spec(config.dataset_config, root_override=dataset_root)
    provider = create_provider(spec)
    manifests = ManifestStore(workspace)

    images: list[ImageRecord] = []
    subjects: list[Any] = []
    manifest_hashes: dict[str, str] = {}

    for release in protocol.releases:
        if not manifests.images_path(protocol.dataset_id, release).is_file():
            report = provider.validate(release)
            manifests.write_validation_report(
                report, dataset_id=protocol.dataset_id, release=release
            )
            if not report.is_clean:
                raise ResearchPreflightError(
                    f"{release}: dataset validation found blocking errors; a "
                    "research run cannot be built on it"
                )
            release_images = list(
                provider.scan(
                    release, verify_checksums=config.require_verified_checksums
                )
            )
            manifests.write_images(
                release_images, dataset_id=protocol.dataset_id, release=release
            )
            manifests.write_subjects(
                summarise_subjects(release_images),
                dataset_id=protocol.dataset_id,
                release=release,
            )

        release_images = manifests.read_images(protocol.dataset_id, release)
        metadata = manifests.image_manifest_metadata(protocol.dataset_id, release)
        if metadata.get("validation_override_reason"):
            raise ResearchPreflightError(
                f"{release}: the image manifest was written under a validation "
                "override; a research run may not rest on overridden validation"
            )
        images += release_images
        subjects += manifests.read_subjects(protocol.dataset_id, release)
        manifest_hashes[release] = manifests.image_manifest_hash(
            protocol.dataset_id, release
        )

    cohort = protocol.build_cohort(subjects, manifest_hashes)
    pairs = protocol.build_pairs(cohort, images)

    if not manifests.cohort_path(protocol.protocol_id, cohort.cohort_id).is_file():
        manifests.write_cohort(cohort)
    if not manifests.pairs_path(protocol.protocol_id, cohort.cohort_id).is_file():
        manifests.write_pairs(pairs, cohort=cohort)

    stored_cohort = manifests.read_cohort(protocol.protocol_id, cohort.cohort_id)
    if stored_cohort.subject_ids != cohort.subject_ids:
        raise ResearchPreflightError(
            f"the stored cohort {cohort.cohort_id} holds different subjects than "
            "the protocol now selects; a research run cannot straddle two cohorts"
        )
    stored_pairs = manifests.read_pairs(protocol.protocol_id, cohort.cohort_id)
    if {str(pair.pair_id) for pair in stored_pairs} != {
        str(pair.pair_id) for pair in pairs
    }:
        raise ResearchPreflightError(
            "the stored pair manifest does not hold the comparisons the protocol "
            "now generates"
        )

    pair_metadata = manifests.pair_manifest_metadata(
        protocol.protocol_id, cohort.cohort_id
    )
    return (
        protocol,
        cohort,
        {image.image_id: image for image in images},
        {pair.pair_id: pair for pair in stored_pairs},
        pair_metadata,
    )


def _require_expected_shape(
    *,
    cohort: Cohort,
    pairs: Mapping[PairId, ComparisonPair],
    images: Mapping[ImageId, ImageRecord],
) -> None:
    """The dataset preflight of section 22-23, asserted before anything runs."""
    if len(cohort.subject_ids) != EXPECTED_SUBJECTS:
        raise ResearchPreflightError(
            f"the cohort holds {len(cohort.subject_ids)} subjects, expected "
            f"{EXPECTED_SUBJECTS}"
        )
    if len(pairs) != EXPECTED_JOBS:
        raise ResearchPreflightError(
            f"the protocol yields {len(pairs)} comparisons, expected {EXPECTED_JOBS}"
        )

    participating: set[ImageId] = set()
    for pair in pairs.values():
        participating.add(pair.left_image_id)
        participating.add(pair.right_image_id)

    unverified: list[str] = []
    blocked: list[str] = []
    absent: list[str] = []
    for image_id in sorted(participating):
        record = images.get(image_id)
        if record is None:
            absent.append(str(image_id))
            continue
        if not record.is_usable or record.blocking_issues:
            blocked.append(str(image_id))
        if record.checksum_status is not ChecksumStatus.VERIFIED:
            unverified.append(str(image_id))

    if absent:
        raise ResearchPreflightError(
            f"{len(absent)} participating image(s) are not in the image manifest"
        )
    if blocked:
        raise ResearchPreflightError(
            f"{len(blocked)} participating image(s) carry blocking validation "
            "issues and may not enter a research run"
        )
    if unverified:
        raise ResearchPreflightError(
            f"{len(unverified)} participating image(s) have no VERIFIED checksum "
            "evidence; rebuild the image manifests with verify_checksums=True"
        )

    for pair in pairs.values():
        expected = ppi_policy.effective_ppi(pair.release)
        for side, image_id in (
            ("left", pair.left_image_id),
            ("right", pair.right_image_id),
        ):
            actual = images[image_id].effective_ppi
            if actual != expected:
                raise ResearchPreflightError(
                    f"pair {pair.pair_id}'s {side} image is recorded at {actual} "
                    f"ppi; {pair.release} is used at {expected} (docs/adr/0004)"
                )


def _require_expected_plan(plan: ExecutionPlan) -> None:
    if plan.total_jobs != EXPECTED_JOBS:
        raise ResearchPreflightError(
            f"the execution plan holds {plan.total_jobs} jobs, expected "
            f"{EXPECTED_JOBS}"
        )
    stage_counts = dict(plan.definition.stage_counts)
    expected_stages = {stage.value: EXPECTED_PER_STAGE for stage in ProtocolStage}
    if stage_counts != expected_stages:
        raise ResearchPreflightError(
            f"the plan's stage counts are {stage_counts}, expected {expected_stages}"
        )
    release_counts = dict(plan.definition.release_counts)
    expected_releases = {
        release: EXPECTED_PER_RELEASE for release in EXPECTED_RELEASES
    }
    if release_counts != expected_releases:
        raise ResearchPreflightError(
            f"the plan's release counts are {release_counts}, expected "
            f"{expected_releases}"
        )


def _load_prepared(
    *,
    workspace: Path,
    dataset_root: Path | None,
    config: ExperimentConfig | None,
    repository_root: Path,
    run_id: str | None,
) -> PreparedResearchRun:
    """Reconstruct a prepared run from what ``prepare`` already wrote.

    Never re-materialises and never re-plans. It re-captures the source
    provenance, though, and refuses to continue under a different commit: a run
    resumed from other code is a different run, even when the difference is a
    typo in a docstring (docs/adr/0017).
    """
    workspace = Path(workspace)
    config = config or load_experiment_config(repository_root=repository_root)
    software = capture_research_provenance(repository_root)

    resolved = run_id or _read_pointer(workspace, config.experiment_id)
    result_store = ResultStore(workspace)
    run = result_store.read_run(resolved)
    plan = PlanStore(workspace).read_plan(resolved)
    reference = result_store.read_runtime_reference(resolved)

    recorded = run.environment.runtime.get("fpbench.source.revision")
    if recorded != software.source_revision:
        raise ResearchPreflightError(
            f"run {resolved} was created from commit {str(recorded)[:12]} but this "
            f"invocation is running commit {software.source_revision[:12]}. A run "
            "cannot be resumed under different code; check out the original "
            "commit, or prepare a new run (docs/adr/0017)"
        )

    bundle_store = RuntimeBundleStore(workspace)
    bundle = bundle_store.read_bundle(reference.bundle_id)
    adapter = _research_adapter(
        development=_development_config(
            repository_root=repository_root, build_jar=None
        ),
        bundle=bundle,
        bundle_store=bundle_store,
        software=software,
    )

    protocol, cohort, images, pairs, _ = _prepare_dataset(
        workspace=workspace, dataset_root=dataset_root, config=config
    )

    return PreparedResearchRun(
        config=config,
        software=software,
        dataset_root=Path(_dataset_root(config, dataset_root)),
        workspace=workspace,
        protocol=protocol,
        cohort=cohort,
        images=images,
        pairs=pairs,
        bundle=bundle,
        adapter=adapter,
        run=run,
        plan=plan,
        runtime_reference=reference,
    )


def _pointer_path(workspace: Path, experiment_id: str) -> Path:
    return Path(workspace) / "experiments" / experiment_id / _POINTER_NAME


def _write_pointer(
    workspace: Path, experiment_id: str, payload: Mapping[str, Any]
) -> Path:
    return write_json(_pointer_path(workspace, experiment_id), dict(payload))


def _read_pointer(workspace: Path, experiment_id: str) -> str:
    path = _pointer_path(workspace, experiment_id)
    if not path.is_file():
        raise ResearchPreflightError(
            f"no prepared run for {experiment_id} in this workspace; run "
            "'prepare' first, or pass --run-id"
        )
    payload = read_json(path)
    run_id = str(payload.get("run_id") or "")
    if not run_id:
        raise ResearchPreflightError(f"{path} names no run")
    return run_id


def _timing_summary(summary: Mapping[str, Any]) -> dict[str, str]:
    """The few timing numbers a receipt may carry, rendered as strings.

    Operational only. A receipt that carried a distribution would be one step
    from carrying a score distribution, and the difference has to be visible in
    the file rather than remembered.
    """
    timings = summary.get("timings_ms") or {}
    adapter = timings.get("adapter") or {}
    fields = ("count", "min", "median", "p95", "p99", "max")
    rendered = {
        f"adapter_ms.{field}": str(adapter[field])
        for field in fields
        if field in adapter
    }
    span = summary.get("wall_clock_span_seconds")
    if span is not None:
        rendered["wall_clock_span_seconds"] = str(span)
    return rendered


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


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
    parser.add_argument(
        "--config", type=Path, default=DEFAULT_EXPERIMENT_CONFIG
    )
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
            state = inspect_sourceafis_native_run(
                **shared, run_id=arguments.run_id
            )
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
