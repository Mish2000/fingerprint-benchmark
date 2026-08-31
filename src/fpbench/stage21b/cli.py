"""Command-line contract for Stage 21B operations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from fpbench.stage21b.bindings import load_frozen_pairs, load_stage21a_binding
from fpbench.stage21b.constants import (
    EXPECTED_PAIRS_PER_METHOD,
    PREPARATION_PROFILE_ID,
    PREPARATION_SET_ID,
)
from fpbench.stage21b.evidence import (
    publish_stage21b_evidence,
    run_contract_suite,
    verify_stage21b_evidence,
)
from fpbench.stage21b.errors import Stage21BError
from fpbench.stage21b.integrity import (
    audit_cross_method_alignment,
    discover_authoritative_run_directories,
)
from fpbench.stage21b.preflight import prepare_stage21b_run
from fpbench.stage21b.status import (
    find_run_directory,
    inspect_run_directory,
    record_supersession,
    status_reports,
)


def main(argv: list[str] | None = None, *, repository_root: Path | None = None) -> int:
    root = Path(repository_root or Path.cwd()).resolve()
    parser = _parser(root)
    args = parser.parse_args(argv)
    try:
        result = _dispatch(args, root)
    except (Stage21BError, OSError, ValueError) as exc:
        print(f"Stage 21B refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def _parser(root: Path) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace", type=Path, default=root / "workspace", help="local workspace root"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    for name in ("preflight", "run"):
        command = commands.add_parser(name)
        command.add_argument("--algorithm", required=True)
        command.add_argument(
            "--adapter-config",
            type=Path,
            required=True,
            help="private path-only adapter configuration (its path is never published)",
        )
        if name == "run":
            command.add_argument(
                "--limit",
                type=int,
                help="execute only this many next pending rows; leaves run incomplete",
            )

    status = commands.add_parser("status")
    status.add_argument("--algorithm")

    integrity = commands.add_parser("integrity")
    integrity.add_argument("--algorithm", required=True)
    integrity.add_argument("--run-id")

    commands.add_parser("alignment")
    commands.add_parser("contract")
    commands.add_parser("publish")
    commands.add_parser("verify")

    supersede = commands.add_parser("supersede")
    supersede.add_argument("--algorithm", required=True)
    supersede.add_argument("--run-id", required=True)
    supersede.add_argument("--reason", required=True)
    supersede.add_argument("--superseded-by-run-id", required=True)
    return parser


def _dispatch(args: argparse.Namespace, root: Path) -> Any:
    workspace = Path(args.workspace).resolve()
    if args.command in {"preflight", "run"}:
        prepared = prepare_stage21b_run(
            repository_root=root,
            workspace=workspace,
            algorithm_id=args.algorithm,
            adapter_config=Path(args.adapter_config).resolve(),
            require_clean_source=True,
            verify_prepared_bytes=True,
        )
        if args.command == "preflight":
            try:
                return prepared.report()
            finally:
                prepared.close()
        def progress(value: dict[str, Any]) -> None:
            # Operational counts only; the runner never hands this a score.
            print(json.dumps(value, ensure_ascii=False), file=sys.stderr, flush=True)

        runner = prepared.runner(progress=progress)
        # ``run`` owns adapter cleanup.  Cleanup success is a prerequisite for
        # sealing, so a second close here could mask the infrastructure error
        # that deliberately leaves a completed batch resumable but unsealed.
        return runner.run(max_pairs=args.limit)

    if args.command == "status":
        reports = status_reports(workspace, algorithm_id=args.algorithm)
        if args.algorithm is None:
            binding = load_stage21a_binding(root)
            present = {row["algorithm_id"] for row in reports}
            reports.extend(
                {
                    "algorithm_id": algorithm_id,
                    "state": "NOT_STARTED",
                    "planned_count": EXPECTED_PAIRS_PER_METHOD,
                    "completed_count": 0,
                    "pending_count": EXPECTED_PAIRS_PER_METHOD,
                    "raw_scores_displayed": False,
                }
                for algorithm_id in binding.algorithm_ids
                if algorithm_id not in present
            )
        return {"stage": "21B", "runs": reports, "raw_scores_displayed": False}

    if args.command == "integrity":
        directory = find_run_directory(
            workspace, algorithm_id=args.algorithm, run_id=args.run_id
        )
        return inspect_run_directory(directory)

    if args.command == "alignment":
        binding = load_stage21a_binding(root)
        frozen_pairs = load_frozen_pairs(workspace=workspace, binding=binding)
        directories = discover_authoritative_run_directories(
            workspace, binding.algorithm_ids
        )
        return audit_cross_method_alignment(
            directories,
            expected_algorithm_ids=binding.algorithm_ids,
            require_production_shape=True,
            expected_pair_manifest_hash=binding.pair_manifest_hash,
            expected_pair_ids_sha256=binding.pair_ids_sha256,
            expected_manifest_pairs=frozen_pairs.pairs,
            expected_preparation_set_id=PREPARATION_SET_ID,
            expected_preparation_profile_id=PREPARATION_PROFILE_ID,
        )

    if args.command == "contract":
        return run_contract_suite(root)
    if args.command == "publish":
        return publish_stage21b_evidence(
            repository_root=root,
            workspace=workspace,
        )
    if args.command == "verify":
        return verify_stage21b_evidence(root)
    if args.command == "supersede":
        directory = find_run_directory(
            workspace, algorithm_id=args.algorithm, run_id=args.run_id
        )
        path = record_supersession(
            directory,
            reason=args.reason,
            superseded_by_run_id=args.superseded_by_run_id,
        )
        return {
            "stage": "21B",
            "status": "superseded",
            "algorithm_id": args.algorithm,
            "run_id": args.run_id,
            "supersession_record": path.name,
        }
    raise AssertionError(args.command)
