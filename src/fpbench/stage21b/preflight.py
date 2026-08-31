"""Production preflight and assembly for one Stage 21B algorithm run."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import platform
import shutil
import sqlite3
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import pyarrow

from fpbench.core.json_io import publish_json
from fpbench.stage21b.adapters import (
    CertifiedAdapterRuntime,
    accepted_predecessor_digests,
    classifier_for,
    load_certified_adapter,
)
from fpbench.stage21b.bindings import (
    AlgorithmBinding,
    PairManifestSnapshot,
    Stage21ABinding,
    load_frozen_pairs,
    load_stage21a_binding,
)
from fpbench.stage21b.constants import (
    EXECUTION_POLICY_PATH,
    EXPECTED_PAIRS_PER_METHOD,
    PREPARATION_PROFILE_ID,
    PREPARATION_SET_ID,
    PROTOCOL_ID,
)
from fpbench.stage21b.errors import Stage21BPreflightError, Stage21BStoreConflict
from fpbench.stage21b.models import (
    FrozenRunSpec,
    PlannedPair,
    ordered_pair_plan_fingerprint,
)
from fpbench.stage21b.policy import ExecutionPolicy, RoutePolicy, load_execution_policy
from fpbench.stage21b.prepared import FrozenPreparedInputs
from fpbench.stage21b.runner import Stage21BRunner
from fpbench.stage21b.source_freeze import (
    ExecutionSourceGuard,
    ExecutionSourceSnapshot,
    build_execution_source_snapshot,
    source_file_sha256,
)
from fpbench.stage21b.store import Stage21BResultStore


@dataclass(slots=True)
class PreparedStage21BRun:
    repository_root: Path
    workspace: Path
    stage21a: Stage21ABinding
    pair_manifest: PairManifestSnapshot
    algorithm: AlgorithmBinding
    policy: ExecutionPolicy
    route: RoutePolicy
    prepared_inputs: FrozenPreparedInputs
    planned_pairs: tuple[PlannedPair, ...]
    runtime: CertifiedAdapterRuntime
    preflight_smoke: Mapping[str, Any]
    source: ExecutionSourceSnapshot
    spec: FrozenRunSpec
    store: Stage21BResultStore
    guard: ExecutionSourceGuard
    available_bytes: int
    minimum_free_bytes: int

    def report(self) -> dict[str, Any]:
        return {
            "stage": "21B",
            "preflight": "PASS",
            "algorithm_id": self.algorithm.algorithm_id,
            "adapter_id": self.algorithm.adapter_id,
            "run_id": self.store.spec.run_id,
            "run_spec_fingerprint": self.store.spec.run_spec_fingerprint,
            "state": self.store.state(),
            "stage21a_finalization_fingerprint": self.stage21a.finalization_fingerprint,
            "roster_id": self.stage21a.roster_id,
            "roster_size": len(self.stage21a.algorithms),
            "pair_manifest_hash": self.pair_manifest.pair_manifest_hash,
            "planned_pairs": len(self.planned_pairs),
            "preparation_set_id": self.prepared_inputs.manifest.preparation_set_id,
            "preparation_profile_id": self.prepared_inputs.manifest.transform_profile_id,
            "runtime_identity_fingerprint": self.runtime.runtime_identity_fingerprint,
            "environment_validation_ms": self.runtime.environment_validation_ms,
            "preflight_smoke": dict(self.preflight_smoke),
            "execution_source_fingerprint": self.source.fingerprint,
            "workspace_available_bytes": self.available_bytes,
            "minimum_free_bytes": self.minimum_free_bytes,
            "benchmark_scores_created_by_preflight": 0,
        }

    def runner(self, *, progress=None) -> Stage21BRunner:
        return Stage21BRunner(
            spec=self.store.spec,
            adapter=self.runtime.adapter,
            prepared_inputs=self.prepared_inputs,
            store=self.store,
            failure_classifier=classifier_for(self.route.failure_classifier),
            invocation_guard=self.guard,
            progress=progress,
        )

    def close(self) -> None:
        close = getattr(self.runtime.adapter, "close", None)
        if callable(close):
            close()


def prepare_stage21b_run(
    *,
    repository_root: Path,
    workspace: Path,
    algorithm_id: str,
    adapter_config: Path,
    require_clean_source: bool = True,
    verify_prepared_bytes: bool = True,
) -> PreparedStage21BRun:
    """Run every non-scoring gate and claim/open the immutable logical run."""
    root = Path(repository_root).resolve()
    work = Path(workspace).resolve()
    work.mkdir(parents=True, exist_ok=True)
    _require_writable(work)

    stage21a = load_stage21a_binding(root, require_predecessor_files=True)
    policy_path = root / EXECUTION_POLICY_PATH
    policy = load_execution_policy(policy_path)
    policy.require_roster_adapters(stage21a.adapter_ids)
    if (root / policy.roster_ref).resolve() != (
        root / "configs/comparisons/final_baseline_roster_v1.yaml"
    ).resolve():
        raise Stage21BPreflightError("execution policy does not reference the frozen roster")
    if policy.preparation_set_id != PREPARATION_SET_ID:
        raise Stage21BPreflightError("execution policy changed preparation-set identity")
    if policy.preparation_profile_id != PREPARATION_PROFILE_ID:
        raise Stage21BPreflightError("execution policy changed preparation profile")

    algorithm = stage21a.algorithm(algorithm_id)
    route = policy.routes[algorithm.adapter_id]
    pair_manifest = load_frozen_pairs(workspace=work, binding=stage21a)
    image_ids = {
        str(image_id)
        for pair in pair_manifest.pairs
        for image_id in (pair.left_image_id, pair.right_image_id)
    }
    prepared = FrozenPreparedInputs(
        workspace=work,
        required_image_ids=image_ids,
        verify_prepared_bytes=verify_prepared_bytes,
    )
    planned_pairs = prepared.plan(pair_manifest.pairs)
    if len(planned_pairs) != EXPECTED_PAIRS_PER_METHOD:
        raise Stage21BPreflightError("prepared plan is not the frozen 73,500 pairs")

    runtime = load_certified_adapter(
        config_path=adapter_config,
        binding=algorithm,
        accepted_predecessor_digests=accepted_predecessor_digests(
            root, binding=algorithm
        ),
    )
    preflight_smoke = _preflight_smoke_attestation(
        repository_root=root,
        runtime=runtime,
        algorithm=algorithm,
    )
    algorithm_config = root / route.algorithm_config
    source = build_execution_source_snapshot(
        repository_root=root,
        algorithm_config=algorithm_config,
        private_adapter_config_sha256=runtime.adapter_config_sha256,
        runtime_identity_fingerprint=runtime.runtime_identity_fingerprint,
        include_flx=algorithm.adapter_id == "flx_pytorch_subprocess",
        require_clean=require_clean_source,
    )
    minimum_free = max(512 * 1024 * 1024, len(planned_pairs) * 16_384)
    available = shutil.disk_usage(work).free
    if available < minimum_free:
        raise Stage21BPreflightError(
            f"result workspace has {available} bytes free; {minimum_free} required"
        )

    runtime_binding = {
        **runtime.binding_document(),
        "orchestrator_runtime": _orchestrator_runtime(),
        "failure_classifier": route.failure_classifier,
        "timeout_seconds": route.timeout_seconds,
        "execution_strategy": policy.execution_strategy,
        "concurrency": policy.concurrency,
        "optimizations_enabled": policy.optimizations_enabled,
        "preflight_smoke": preflight_smoke,
    }
    spec = FrozenRunSpec.create(
        created_utc=_utc_now(),
        stage21a_finalization_fingerprint=stage21a.finalization_fingerprint,
        stage21a_source_fingerprint=stage21a.source_fingerprint,
        high_resolution_reservation_fingerprint=(
            stage21a.high_resolution_reservation_fingerprint
        ),
        roster_id=stage21a.roster_id,
        roster_fingerprint=stage21a.roster_fingerprint,
        algorithm_id=algorithm.algorithm_id,
        adapter_id=algorithm.adapter_id,
        integration_id=algorithm.integration_id,
        implementation_version=algorithm.implementation_version,
        adapter_descriptor_fingerprint=runtime.descriptor_fingerprint,
        runtime_identity_fingerprint=runtime.runtime_identity_fingerprint,
        runtime_binding=runtime_binding,
        predecessor_finalization_fingerprint=(
            algorithm.predecessor_finalization_fingerprint
        ),
        score_direction=algorithm.score_direction,
        protocol_id=PROTOCOL_ID,
        protocol_config_sha256=stage21a.protocol_config_sha256,
        pair_manifest_hash=pair_manifest.pair_manifest_hash,
        pair_ids_sha256=pair_manifest.pair_ids_sha256,
        planned_pair_input_fingerprint=ordered_pair_plan_fingerprint(planned_pairs),
        pair_count=len(planned_pairs),
        preparation_set_id=prepared.manifest.preparation_set_id,
        preparation_set_fingerprint=prepared.preparation_set_fingerprint,
        preparation_profile_id=prepared.manifest.transform_profile_id,
        preparation_profile_fingerprint=prepared.preparation_profile_fingerprint,
        execution_source_fingerprint=source.fingerprint,
        execution_source_revision=source.revision,
        algorithm_execution_config_sha256=source_file_sha256(algorithm_config),
        private_adapter_config_sha256=runtime.adapter_config_sha256,
        expected_attempts=len(planned_pairs),
        timeout_seconds=route.timeout_seconds,
        concurrency=policy.concurrency,
        execution_strategy=policy.execution_strategy,
        metrics_allowed=False,
        calibration_allowed=False,
        threshold_allowed=False,
        score_transform_allowed=False,
        orchestrator_algorithm_retries=policy.orchestrator_algorithm_retries,
        infrastructure_resume_allowed=policy.infrastructure_resume_allowed,
    )
    _require_no_active_collision(work, algorithm.algorithm_id, spec.run_id)
    store = Stage21BResultStore(
        workspace=work, spec=spec, planned_pairs=planned_pairs
    )
    _publish_source_binding(
        store,
        source,
        runtime.adapter_config_sha256,
        environment_validation_ms=runtime.environment_validation_ms,
    )
    guard = ExecutionSourceGuard(
        repository_root=root,
        snapshot=source,
        private_adapter_config=adapter_config,
        private_adapter_config_sha256=runtime.adapter_config_sha256,
        pair_manifest_hash=pair_manifest.pair_manifest_hash,
        pair_count=len(planned_pairs),
    )
    return PreparedStage21BRun(
        repository_root=root,
        workspace=work,
        stage21a=stage21a,
        pair_manifest=pair_manifest,
        algorithm=algorithm,
        policy=policy,
        route=route,
        prepared_inputs=prepared,
        planned_pairs=planned_pairs,
        runtime=runtime,
        preflight_smoke=preflight_smoke,
        source=source,
        spec=store.spec,
        store=store,
        guard=guard,
        available_bytes=available,
        minimum_free_bytes=minimum_free,
    )


def _publish_source_binding(
    store: Stage21BResultStore,
    source: ExecutionSourceSnapshot,
    adapter_config_sha256: str,
    *,
    environment_validation_ms: float,
) -> None:
    path = store.run_dir / "execution-source-binding.json"
    document = {
        "schema_version": "1",
        "stage": "21B",
        "run_id": store.spec.run_id,
        "run_spec_fingerprint": store.spec.run_spec_fingerprint,
        "execution_source_fingerprint": source.fingerprint,
        "execution_source_revision": source.revision,
        "file_sha256s": dict(source.file_sha256s),
        "private_adapter_config_sha256": adapter_config_sha256,
        "runtime_identity_fingerprint": store.spec.runtime_identity_fingerprint,
        "preflight_environment_validation_ms": environment_validation_ms,
        "preflight_environment_validation_timing_definition": (
            "wall time for the certified adapter validate_environment call"
        ),
    }
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise Stage21BPreflightError(
                f"existing execution-source binding is unreadable: {exc}"
            ) from exc
        stable_keys = (
            "schema_version",
            "stage",
            "run_id",
            "run_spec_fingerprint",
            "execution_source_fingerprint",
            "execution_source_revision",
            "file_sha256s",
            "private_adapter_config_sha256",
            "runtime_identity_fingerprint",
        )
        if any(existing.get(key) != document.get(key) for key in stable_keys):
            raise Stage21BPreflightError(
                "existing execution-source binding belongs to another frozen run"
            )
        return
    try:
        publish_json(path, document)
    except Exception as exc:
        raise Stage21BPreflightError(f"cannot bind execution source: {exc}") from exc


def _preflight_smoke_attestation(
    *,
    repository_root: Path,
    runtime: CertifiedAdapterRuntime,
    algorithm: AlgorithmBinding,
) -> dict[str, Any]:
    """Exercise a route's live non-SD300 smoke when one is callable.

    VeriFinger exposes a production adapter smoke over vendor fixtures and is
    run on every fresh preflight.  The other frozen routes' fixture/qualification
    checks are predecessor gates rather than reusable adapter hooks; their
    hash-bound accepted finalization plus freshly re-hashed runtime closure is
    recorded explicitly instead of pretending a new smoke ran.
    """
    if algorithm.adapter_id != "verifinger_java_subprocess":
        return {
            "mode": "HASH_BOUND_PREDECESSOR_QUALIFICATION",
            "outcome": "PASS",
            "predecessor_finalization_fingerprint": (
                algorithm.predecessor_finalization_fingerprint
            ),
            "runtime_assets_reverified_this_preflight": True,
            "live_fixture_smoke_available": False,
            "benchmark_scores_produced": 0,
            "raw_score_values_recorded": False,
        }

    try:
        from fpbench.experiments.verifinger_smoke import run_production_smoke

        config = getattr(runtime.adapter, "config", None)
        installation = getattr(config, "installation", None)
        report = run_production_smoke(
            repository_root=repository_root,
            installation=installation,
        )
    except Exception as exc:
        raise Stage21BPreflightError(
            f"VeriFinger non-SD300 production smoke failed: {exc}"
        ) from exc
    if (
        not report.passed
        or report.sd300_used
        or report.benchmark_scores_produced != 0
        or not all(report.claims.values())
    ):
        raise Stage21BPreflightError(
            "VeriFinger production smoke did not establish a non-SD300 PASS"
        )
    current_manifest = runtime.environment.dependencies.get(
        "verifinger.runtime_manifest.fingerprint"
    )
    if current_manifest != report.runtime_manifest_fingerprint:
        raise Stage21BPreflightError(
            "VeriFinger smoke used a different runtime manifest than Stage 21B"
        )
    return {
        "mode": "LIVE_NON_SD300_PRODUCTION_SMOKE",
        "outcome": "PASS",
        "fixture_kind": report.fixture_kind,
        "runtime_manifest_fingerprint": report.runtime_manifest_fingerprint,
        "algorithm_profile_fingerprint": report.algorithm_profile_fingerprint,
        "claims": dict(sorted(report.claims.items())),
        "scores_produced": report.scores_produced,
        "benchmark_scores_produced": 0,
        "raw_score_values_recorded": False,
    }


def _require_writable(workspace: Path) -> None:
    directory = workspace / "stage21b"
    directory.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.NamedTemporaryFile(prefix="preflight-", dir=directory, delete=True):
            pass
    except OSError as exc:
        raise Stage21BPreflightError(
            f"Stage 21B result workspace is not writable: {exc}"
        ) from exc


def _require_no_active_collision(
    workspace: Path, algorithm_id: str, proposed_run_id: str
) -> None:
    directory = Path(workspace) / "stage21b" / algorithm_id
    active = sorted(
        path.parent.name
        for path in directory.glob("*/run-spec.json")
        if not (path.parent / "supersession.json").is_file()
    )
    conflicts = [run_id for run_id in active if run_id != proposed_run_id]
    if conflicts:
        raise Stage21BStoreConflict(
            f"{algorithm_id} already has active run(s) {conflicts}; the proposed "
            f"identity is {proposed_run_id}. Record explicit supersession first"
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _orchestrator_runtime() -> dict[str, str]:
    return {
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "python_executable_identity": Path(sys.executable).name,
        "platform_system": platform.system(),
        "platform_machine": platform.machine(),
        "sqlite_version": sqlite3.sqlite_version,
        "pyarrow_version": pyarrow.__version__,
    }


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()
