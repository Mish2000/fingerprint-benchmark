#!/usr/bin/env python3
"""Drive Stage 21A and Stage 21B into the final baseline report.

This orchestrator adds no semantics of its own: every step is one of the
frozen stage commands, run in the frozen order, and every step is idempotent
or resumable.  Stop it anywhere; `status` and `next` always know what remains.

    python scripts/final_baseline_pipeline.py status
    python scripts/final_baseline_pipeline.py next
    python scripts/final_baseline_pipeline.py run --adapter-configs <yaml>

`run` stops at the two commit points (after publishing Stage 21B evidence and
before publishing the final report) and prints the exact git commands instead of committing for
you — a finalization marker belongs to a commit a human meant to make.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

import yaml  # noqa: E402

from fpbench.experiments.stage21a_finalization import (  # noqa: E402
    verify_stage21a_evidence,
)
from fpbench.stage21b.bindings import load_stage21a_binding  # noqa: E402
from fpbench.stage21b.constants import (  # noqa: E402
    EXPECTED_PAIRS_PER_METHOD,
    STAGE21B_EVIDENCE,
)
from fpbench.stage21b.evidence import verify_stage21b_evidence  # noqa: E402
from fpbench.stage21b.status import status_reports  # noqa: E402
from fpbench.final_baseline.constants import EVIDENCE_DIRECTORY as FINAL_BASELINE_EVIDENCE  # noqa: E402
from fpbench.final_baseline.evidence import verify_final_baseline_evidence  # noqa: E402


def _check(callable_, *args: Any, **kwargs: Any) -> tuple[bool, str]:
    try:
        callable_(*args, **kwargs)
        return True, ""
    except Exception as exc:  # noqa: BLE001 - status must report, not crash
        return False, f"{type(exc).__name__}: {exc}"


def _stage21b_runs(workspace: Path) -> list[dict[str, Any]]:
    binding = load_stage21a_binding(REPOSITORY_ROOT)
    reports = status_reports(workspace)
    present = {row["algorithm_id"]: row for row in reports}
    merged = []
    for algorithm_id in binding.algorithm_ids:
        row = present.get(
            algorithm_id,
            {
                "algorithm_id": algorithm_id,
                "state": "NOT_STARTED",
                "planned_count": EXPECTED_PAIRS_PER_METHOD,
                "completed_count": 0,
                "pending_count": EXPECTED_PAIRS_PER_METHOD,
            },
        )
        merged.append(row)
    return merged


def _status(workspace: Path) -> dict[str, Any]:
    ok_21a, err_21a = _check(verify_stage21a_evidence, REPOSITORY_ROOT)
    ok_21b, err_21b = _check(verify_stage21b_evidence, REPOSITORY_ROOT)
    ok_report, report_error = _check(
        verify_final_baseline_evidence, REPOSITORY_ROOT
    )
    runs = _stage21b_runs(workspace) if ok_21a else []
    return {
        "stage21a_evidence_verified": ok_21a,
        "stage21a_error": err_21a,
        "stage21b_runs": runs,
        "stage21b_evidence_verified": ok_21b,
        "stage21b_error": "" if ok_21b else err_21b,
        "final_baseline_evidence_verified": ok_report,
        "final_baseline_error": "" if ok_report else report_error,
    }


def _adapter_configs(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(document, dict):
        raise SystemExit(f"{path}: expected a mapping of algorithm_id -> config path")
    return {str(key): str(value) for key, value in document.items()}


def _next_commands(
    status: dict[str, Any], adapter_configs: dict[str, str], workspace: Path
) -> list[str]:
    python = "python"
    if not status["stage21a_evidence_verified"]:
        return [
            "# Stage 21A evidence does not verify on this tree:",
            f"#   {status['stage21a_error']}",
            f"{python} scripts/stage21a_freeze.py --verify",
        ]
    commands: list[str] = []
    unsealed = [
        row for row in status["stage21b_runs"] if row.get("state") != "SEALED"
    ]
    for row in unsealed:
        algorithm_id = row["algorithm_id"]
        config = adapter_configs.get(
            algorithm_id, f"<path-to-{algorithm_id}-adapter-config.json>"
        )
        commands.append(
            f"{python} scripts/stage21b.py --workspace {workspace} run "
            f"--algorithm {algorithm_id} --adapter-config {config}"
        )
    if unsealed:
        commands.append("# (each run is resumable; rerun the same command after any stop)")
        return commands
    if not status["stage21b_evidence_verified"]:
        commands.append(f"{python} scripts/stage21b.py --workspace {workspace} alignment")
        commands.append(f"{python} scripts/stage21b.py --workspace {workspace} publish")
        commands.append(
            "# verify the Stage 21B publication registry entry (runbook step 2), then:"
        )
        commands.append(
            f"git add {STAGE21B_EVIDENCE.as_posix()} "
            "src/fpbench/experiments/publication_registry.py && "
            'git commit -m "Publish the Stage 21B cross-subject raw-result receipts"'
        )
        return commands
    if not status["final_baseline_evidence_verified"]:
        commands.append(f"{python} scripts/final_baseline.py --workspace {workspace} preflight")
        commands.append(
            f"{python} scripts/final_baseline.py --workspace {workspace} publish "
            "--source-tree-clean-attested"
        )
        commands.append(
            f"git add {FINAL_BASELINE_EVIDENCE.as_posix()} && "
            'git commit -m "Publish the final baseline TAR/FAR/FRR report"'
        )
        return commands
    commands.append("# Nothing remains: the final baseline report is published.")
    commands.append(
        f"# Read it at {FINAL_BASELINE_EVIDENCE.as_posix()}/final-baseline-report.md"
    )
    return commands


def _run_step(command: list[str]) -> None:
    printable = " ".join(command)
    print(f"\n=== running: {printable}", flush=True)
    completed = subprocess.run(command, cwd=REPOSITORY_ROOT)
    if completed.returncode != 0:
        raise SystemExit(
            f"step failed with exit code {completed.returncode}: {printable}\n"
            "Fix the reported refusal, then rerun the pipeline; every step is "
            "resumable."
        )


def _run(workspace: Path, adapter_configs: dict[str, str]) -> None:
    status = _status(workspace)
    if not status["stage21a_evidence_verified"]:
        raise SystemExit(
            "Stage 21A evidence does not verify; nothing may run over an "
            f"unverified protocol: {status['stage21a_error']}"
        )
    unsealed = [
        row for row in status["stage21b_runs"] if row.get("state") != "SEALED"
    ]
    for row in unsealed:
        algorithm_id = row["algorithm_id"]
        config = adapter_configs.get(algorithm_id)
        if not config:
            raise SystemExit(
                f"no adapter config for {algorithm_id}; pass --adapter-configs "
                "with all six paths (see the runbook)"
            )
        _run_step(
            [
                sys.executable,
                str(REPOSITORY_ROOT / "scripts" / "stage21b.py"),
                "--workspace",
                str(workspace),
                "run",
                "--algorithm",
                algorithm_id,
                "--adapter-config",
                config,
            ]
        )
    status = _status(workspace)
    if not status["stage21b_evidence_verified"]:
        _run_step(
            [
                sys.executable,
                str(REPOSITORY_ROOT / "scripts" / "stage21b.py"),
                "--workspace",
                str(workspace),
                "alignment",
            ]
        )
        _run_step(
            [
                sys.executable,
                str(REPOSITORY_ROOT / "scripts" / "stage21b.py"),
                "--workspace",
                str(workspace),
                "publish",
            ]
        )
        print(
            "\n=== commit point: Stage 21B receipts are written. Commit them, "
            "then rerun this pipeline:\n"
            f"    git add {STAGE21B_EVIDENCE.as_posix()}\n"
            '    git commit -m "Publish the Stage 21B cross-subject raw-result '
            'receipts"\n'
        )
        return
    if not status["final_baseline_evidence_verified"]:
        _run_step(
            [
                sys.executable,
                str(REPOSITORY_ROOT / "scripts" / "final_baseline.py"),
                "--workspace",
                str(workspace),
                "preflight",
            ]
        )
        _run_step(
            [
                sys.executable,
                str(REPOSITORY_ROOT / "scripts" / "final_baseline.py"),
                "--workspace",
                str(workspace),
                "publish",
                "--source-tree-clean-attested",
            ]
        )
        print(
            "\n=== commit point: final-baseline evidence is written. Commit it:\n"
            f"    git add {FINAL_BASELINE_EVIDENCE.as_posix()}\n"
            '    git commit -m "Publish the final baseline TAR/FAR/FRR report"\n'
        )
        return
    print("\nNothing remains: the final baseline report is published and verifies.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace", type=Path, default=REPOSITORY_ROOT / "workspace"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    next_parser = commands.add_parser("next")
    next_parser.add_argument("--adapter-configs", type=Path)
    run_parser = commands.add_parser("run")
    run_parser.add_argument("--adapter-configs", type=Path)
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    if args.command == "status":
        print(json.dumps(_status(workspace), indent=2, ensure_ascii=False))
        return 0
    if args.command == "next":
        adapter_configs = _adapter_configs(getattr(args, "adapter_configs", None))
        for line in _next_commands(_status(workspace), adapter_configs, workspace):
            print(line)
        return 0
    if args.command == "run":
        adapter_configs = _adapter_configs(getattr(args, "adapter_configs", None))
        _run(workspace, adapter_configs)
        return 0
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
