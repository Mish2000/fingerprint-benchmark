"""Run, publish and verify the Stage 8B flx runtime qualification.

Three commands, and the split between them is the point.

``probe`` needs the bundle, the checkpoint and the runtime.  It executes the
route on synthetic fixtures and writes nine evidence documents.

``finalize`` writes the tenth, which binds the exact bytes of the other nine.

``verify`` needs none of that.  It re-derives the published chain from the
committed evidence and the repository's own configuration, so the qualification
can be checked on a machine that has neither torch nor the weights.
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from fpbench.core.flx_errors import FlxError
from fpbench.flx import identity
from fpbench.flx.artifacts import FlxRuntimeBundle, build_artifact_binding
from fpbench.flx.integration import build_adapter_profile
from fpbench.flx.lock import load_runtime_lock
from fpbench.flx.policy import load_runtime_policy
from fpbench.flx.preprocessing import build_preprocessing_profile
from fpbench.flx.probe import ProbeInputs, run_runtime_probe
from fpbench.flx.qualification import build_qualification_report
from fpbench.flx.representation import build_representation_profile
from fpbench.flx.runtime import build_runtime_manifest
from fpbench.flx.score import build_score_profile
from fpbench.flx.worker import FlxWorkerSession
from fpbench.storage.flx_store import Stage8BEvidenceStore

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
LOCK_CONFIG = REPOSITORY_ROOT / "configs" / "flx" / "flx_runtime_lock_v1.txt"
POLICY_CONFIG = REPOSITORY_ROOT / "configs" / "flx" / "stage8b_flx_runtime_policy_v1.yaml"

#: The Stage 8A acquisition manifest this binding descends from.
STAGE8A_FLX_MANIFEST_FINGERPRINT = (
    "46b36b0266a3173f22289ce9c2262cc0812cb148d8e1c7b6a3da909a1d6927f3"
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def command_probe(arguments: argparse.Namespace) -> int:
    bundle = FlxRuntimeBundle.from_environment()
    lock = load_runtime_lock(LOCK_CONFIG)
    policy = load_runtime_policy(POLICY_CONFIG)
    created = arguments.created_utc or _now()

    binding = build_artifact_binding(
        bundle,
        stage8a_manifest_fingerprint=STAGE8A_FLX_MANIFEST_FINGERPRINT,
        inspected_utc=created,
    )
    with FlxWorkerSession(
        bundle, startup_deadline_seconds=float(policy.max_worker_startup_seconds)
    ) as session:
        report = session.validate_runtime(
            deadline_seconds=float(policy.max_worker_startup_seconds)
        )
    manifest = build_runtime_manifest(report, lock=lock, created_utc=created)

    probe = run_runtime_probe(
        ProbeInputs(
            bundle=bundle,
            policy=policy,
            artifact_binding_fingerprint=binding.fingerprint,
            runtime_manifest_fingerprint=manifest.fingerprint,
            created_utc=created,
        )
    )
    qualification = build_qualification_report(
        binding=binding, manifest=manifest, probe=probe, qualified_utc=created
    )

    store = Stage8BEvidenceStore(REPOSITORY_ROOT)
    store.ensure(store.ARTIFACT_BINDING_NAME, binding)
    store.ensure(store.RUNTIME_MANIFEST_NAME, manifest)
    store.ensure(store.PREPROCESSING_PROFILE_NAME, build_preprocessing_profile())
    store.ensure(store.REPRESENTATION_PROFILE_NAME, build_representation_profile())
    store.ensure(store.SCORE_PROFILE_NAME, build_score_profile())
    store.ensure(store.ADAPTER_PROFILE_NAME, build_adapter_profile())
    store.ensure(store.RUNTIME_PROBE_NAME, probe)
    store.ensure(store.QUALIFICATION_REPORT_NAME, qualification)

    print(qualification.outcome.value)
    for result in qualification.gates:
        print(f"  {result.gate.value:<28} {result.state.value}")
    operational = probe.operational
    print()
    print(f"worker startup      {operational.worker_startup_seconds} s")
    print(f"model load          {operational.model_load_seconds} s")
    print(f"preprocess (median) {operational.preprocess_seconds} s")
    print(f"extract (median)    {operational.extract_seconds} s")
    print(f"compare (median)    {operational.compare_seconds} s")
    print(f"peak RAM            {operational.peak_ram_bytes} bytes")
    print(f"bundle on disk      {operational.artifact_disk_bytes} bytes")
    print(f"projected 12,000 extractions {operational.projected_12000_extractions_seconds} s")
    print(f"projected 6,000 comparisons  {operational.projected_6000_comparisons_seconds} s")
    print(f"within frozen limits         {operational.within_limits}")
    return 0 if qualification.opens_stage_8c else 1


def command_verify(_: argparse.Namespace) -> int:
    from fpbench.flx.verify import verify_stage8b_evidence

    result = verify_stage8b_evidence(
        repository_root=REPOSITORY_ROOT,
        lock_config=LOCK_CONFIG,
        policy_config=POLICY_CONFIG,
    )
    print(result.outcome.value)
    print(f"gates verified: {result.gate_count}")
    print(f"evidence files verified: {result.evidence_files_verified}")
    print(f"opens stage 8c: {result.opens_stage_8c}")
    return 0


def command_finalize(arguments: argparse.Namespace) -> int:
    from fpbench.flx.finalization import publish_stage8b_finalization

    marker = publish_stage8b_finalization(
        repository_root=REPOSITORY_ROOT,
        lock_config=LOCK_CONFIG,
        policy_config=POLICY_CONFIG,
        verifier_source_commit=arguments.verifier_source_commit,
        created_utc=arguments.created_utc or _now(),
    )
    print(marker.outcome.value)
    print(f"finalization fingerprint: {marker.fingerprint}")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="qualify the flx learned-representation route"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    probe = subparsers.add_parser("probe", help="execute the route and write the evidence")
    probe.add_argument("--created-utc", default=None)
    probe.set_defaults(handler=command_probe)

    finalize = subparsers.add_parser("finalize", help="bind the exact evidence bytes")
    finalize.add_argument("--verifier-source-commit", required=True)
    finalize.add_argument("--created-utc", default=None)
    finalize.set_defaults(handler=command_finalize)

    for name in ("status", "verify"):
        command = subparsers.add_parser(name, help="re-derive the published chain")
        command.set_defaults(handler=command_verify)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        return arguments.handler(arguments)
    except FlxError as exc:
        print(f"error: {exc}")
        return 2


if __name__ == "__main__":  # pragma: no cover - exercised as a module command
    raise SystemExit(main())
