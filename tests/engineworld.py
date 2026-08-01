"""A whole research experiment, at a scale that runs in a second.

The shared engine's four commands read configuration files, build manifests,
capture git provenance, materialise a runtime bundle and execute a plan. Testing
it against a stubbed-out version of any of that would test the stub, so this
module builds the real thing small: a real (synthetic) SD300-shaped delivery, a
real dataset config, a real protocol config, a real one-commit git repository,
and a real workspace.

Three subjects, one release, ten fingers, four stages — 120 comparisons. Enough
to exercise every seam the 6,000-comparison run has, and quick enough to run in
ordinary CI with no dataset and no JVM.

**Nothing here is a fingerprint and nothing here is a result.** The images are
eight-by-eight PNGs; every score any adapter produces over them is arithmetic on
digests. What the fixtures prove is that the engine is indifferent to which
algorithm it is driving (spec section 62).
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from fpbench.adapters.base import FingerprintAlgorithmAdapter
from fpbench.core.enums import ExecutionStatus, ProtocolStage
from fpbench.core.execution_models import ExecutionProfile
from fpbench.core.run_state_models import IntegrityIssue
from fpbench.core.serialization import stable_hash
from fpbench.experiments.algorithm_research import AlgorithmResearchExperimentSpec
from fpbench.experiments.research_integration import (
    DevelopmentAdapterRuntime,
    ResearchAdapterIntegration,
    ResearchValidationContext,
)
from support import build_release

__all__ = [
    "EngineWorld",
    "build_engine_world",
    "structural_integration",
    "structural_result_validator",
    "git_available",
]

RELEASE = "SD300A"
PPI = 500
FINGERS = 10
IMPRESSIONS = 2

#: A role name for a runtime asset that stands in for a real executable. The
#: dummy matcher needs no files at all, so the bundle it pins is a placeholder —
#: which is itself worth exercising, because the engine must not care what is in
#: one.
STAND_IN_ROLE = "test_runtime_asset"

PROFILE = ExecutionProfile(
    profile_id="native_identity_60s_v1",
    preparer_id="identity",
    timeout_seconds=60.0,
    deterministic_seed=0,
    parameters={"resolution_mode": "native", "shared_resampling": "none"},
)


def git_available() -> bool:
    return shutil.which("git") is not None


@dataclass(frozen=True, slots=True)
class EngineWorld:
    """The paths and the spec one engine-driven experiment needs."""

    repository_root: Path
    dataset_root: Path
    workspace: Path
    spec: AlgorithmResearchExperimentSpec
    subject_count: int

    @property
    def expected_jobs(self) -> int:
        return self.spec.expected_jobs


def build_engine_world(
    root: Path,
    *,
    subject_count: int = 3,
    experiment_id: str = "engine_smoke_v1",
) -> EngineWorld:
    """Everything the engine reads, written to disk and committed."""
    repository_root = Path(root) / "repo"
    dataset_root = Path(root) / "delivery"
    workspace = Path(root) / "workspace"

    subjects = [f"{1000 + index:08d}" for index in range(subject_count)]
    build_release(dataset_root, RELEASE, PPI, subjects)

    configs = repository_root / "configs"
    (configs / "datasets").mkdir(parents=True, exist_ok=True)
    (configs / "protocols").mkdir(parents=True, exist_ok=True)
    (configs / "algorithms").mkdir(parents=True, exist_ok=True)

    dataset_config = configs / "datasets" / "synthetic.yaml"
    dataset_config.write_text(
        "dataset:\n"
        "  id: sd300\n"
        "  provider: sd300\n"
        f"  root: {dataset_root.as_posix()}\n"
        "  options:\n"
        "    image_format: png\n"
        "    releases:\n"
        f"      {RELEASE}:\n"
        f"        directory: {RELEASE.lower()}\n",
        encoding="utf-8",
    )

    protocol_config = configs / "protocols" / "synthetic.yaml"
    protocol_config.write_text(
        "protocol:\n"
        "  id: sd300_50_subjects\n"
        "dataset:\n"
        "  id: sd300\n"
        "  ref: configs/datasets/synthetic.yaml\n"
        "cohort:\n"
        f"  size: {subject_count}\n"
        "  seed: 20260728\n"
        "  role: test\n"
        f"  releases: [{RELEASE}]\n"
        "  require:\n"
        "    all_ten_plain: true\n"
        "    all_ten_roll: true\n"
        "    common_across_releases: true\n"
        "pairs:\n"
        "  plain_self: true\n"
        "  roll_self: true\n"
        "  plain_roll_mated: true\n"
        "  plain_roll_non_mated:\n"
        "    enabled: true\n"
        "    finger_shift: 1\n",
        encoding="utf-8",
    )

    algorithm_config = configs / "algorithms" / "synthetic.yaml"
    algorithm_config.write_text("algorithm:\n  id: synthetic\n", encoding="utf-8")

    _commit_everything(repository_root)

    per_stage = subject_count * FINGERS
    spec = AlgorithmResearchExperimentSpec(
        experiment_id=experiment_id,
        kind="full_raw_score_run",
        replicate_index=0,
        dataset_config=dataset_config,
        protocol_config=protocol_config,
        algorithm_config=algorithm_config,
        require_verified_checksums=True,
        research_mode=True,
        materialization_policy="content_addressed_copy_v1",
        execution_profile=PROFILE,
        expected_jobs=per_stage * len(ProtocolStage),
        expected_per_release=per_stage * len(ProtocolStage),
        expected_per_stage=per_stage,
        expected_releases=(RELEASE,),
        expected_subjects=subject_count,
        expected_participating_images=subject_count * FINGERS * IMPRESSIONS,
        evidence_directory=Path("evidence") / "engine-smoke",
    )
    return EngineWorld(
        repository_root=repository_root,
        dataset_root=dataset_root,
        workspace=workspace,
        spec=spec,
        subject_count=subject_count,
    )


def _commit_everything(repository_root: Path) -> None:
    """One commit, clean tree: what research provenance insists on."""
    repository_root.mkdir(parents=True, exist_ok=True)
    # Build output is ignored here for the same reason it is ignored in the real
    # repository: an integration that writes its own executables must not make
    # the tree dirty and stop the next research command. ``evidence/`` is ignored
    # only in this throwaway world — the real repository commits it — because a
    # test that finalises and then asks for status would otherwise be refused for
    # having uncommitted output it produced itself.
    (repository_root / ".gitignore").write_text(
        "build/\nworkspace/\nevidence/\n", encoding="utf-8"
    )
    _git(repository_root, "init", "--quiet")
    _git(repository_root, "config", "user.email", "tests@example.invalid")
    _git(repository_root, "config", "user.name", "fpbench tests")
    _git(repository_root, "add", ".")
    _git(repository_root, "commit", "--quiet", "-m", "engine world")


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *arguments],
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout


# ---------------------------------------------------------------- integration


def structural_result_validator(
    context: ResearchValidationContext,
) -> "StructuralValidationReport":
    """A validator that counts rather than judges.

    Every real algorithm brings its own, because which failure codes are
    biometric outcomes is an algorithm-specific judgement. This one asserts
    nothing about a pipeline; it exists so the engine can be driven end to end by
    an adapter that has no pipeline to assert about.

    Its local algorithm-neutral report satisfies ``AlgorithmValidationReport``
    directly, proving the protocol is usable without importing or reusing the
    first algorithm's validator model.
    """
    successes = 0
    total = 0
    failures: dict[str, int] = {}
    for planned in context.plan.jobs:
        record = context.result_store.read_raw_result(
            context.run.run_id, planned.job.job_id
        )
        total += 1
        if record.status is ExecutionStatus.SUCCESS:
            successes += 1
        elif record.failure is not None:
            code = record.failure.code.value
            failures[code] = failures.get(code, 0) + 1

    return StructuralValidationReport(
        run_id=context.run.run_id,
        plan_id=context.plan.plan_id,
        total_results=total,
        successful_results=successes,
        algorithmic_failures=total - successes,
        blocking_failures=0,
        failure_counts=failures,
        errors=(),
        validation_fingerprint=stable_hash(
            {
                "schema": "structural_validation_v1",
                "run_fingerprint": context.run.run_fingerprint,
                "plan_fingerprint": context.plan.definition.plan_fingerprint,
                "total": total,
                "successes": successes,
                "failures": dict(sorted(failures.items())),
            },
            length=64,
        ),
        inspected_utc="2026-07-30T00:00:00+00:00",
    )


@dataclass(frozen=True, slots=True)
class StructuralValidationReport:
    run_id: str
    plan_id: str
    total_results: int
    successful_results: int
    algorithmic_failures: int
    blocking_failures: int
    failure_counts: Mapping[str, int]
    errors: tuple[IntegrityIssue, ...]
    validation_fingerprint: str
    inspected_utc: str

    @property
    def is_clean(self) -> bool:
        return self.blocking_failures == 0 and not self.errors


def structural_integration(
    *,
    integration_id: str,
    adapter_id: str,
    build_adapter: Callable[[], FingerprintAlgorithmAdapter],
    asset_payloads: Mapping[str, bytes] | None = None,
    roles: Sequence[str] = (STAND_IN_ROLE,),
    validator=structural_result_validator,
) -> ResearchAdapterIntegration:
    """An integration over an adapter that needs no build of its own.

    ``asset_payloads`` decides what goes into the runtime bundle. The default is
    one stand-in file; a multi-asset test passes three. Either way the engine
    materialises whatever it is handed and never looks inside.
    """
    payloads = dict(
        asset_payloads
        or {role: f"stand-in bytes for {role}".encode("utf-8") for role in roles}
    )

    def development(
        repository_root: Path, algorithm_config: Path, overrides: Mapping[str, object]
    ) -> DevelopmentAdapterRuntime:
        build_directory = Path(overrides.get("build_directory") or repository_root)
        build_directory = build_directory / "build"
        build_directory.mkdir(parents=True, exist_ok=True)
        assets: dict[str, Path] = {}
        for role, payload in payloads.items():
            path = build_directory / f"{role}.bin"
            path.write_bytes(payload)
            assets[role] = path
        return DevelopmentAdapterRuntime(adapter=build_adapter(), assets=assets)

    def delegate(
        repository_root: Path,
        algorithm_config: Path,
        bundle,
        asset_paths: Mapping[str, Path],
        software,
    ) -> FingerprintAlgorithmAdapter:
        # A real adapter would pin itself to these paths. This one has nothing to
        # pin, and the engine must still treat it exactly the same.
        assert set(asset_paths) == set(payloads)
        return build_adapter()

    return ResearchAdapterIntegration(
        integration_id=integration_id,
        adapter_id=adapter_id,
        runtime_asset_roles=tuple(payloads),
        primary_runtime_asset_role=next(iter(sorted(payloads))),
        create_development_runtime=development,
        create_research_delegate=delegate,
        validate_result_set=validator,
    )
