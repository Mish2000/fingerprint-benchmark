"""Command-line contract for final-baseline reporting operations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from fpbench.core.errors import ConfigurationError
from fpbench.final_baseline.constants import COMPONENT
from fpbench.final_baseline.errors import FinalBaselineError
from fpbench.final_baseline.evaluate import collect_final_baseline_inputs, evaluate_final_baseline
from fpbench.final_baseline.evidence import (
    publish_final_baseline_evidence,
    verify_final_baseline_evidence,
)


def main(argv: list[str] | None = None, *, repository_root: Path | None = None) -> int:
    root = Path(repository_root or Path.cwd()).resolve()
    parser = _parser(root)
    args = parser.parse_args(argv)
    try:
        result = _dispatch(args, root)
    except (FinalBaselineError, ConfigurationError, OSError, ValueError) as exc:
        print(f"final-baseline reporting refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def _parser(root: Path) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace", type=Path, default=root / "workspace", help="local workspace root"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "preflight",
        help="verify Stage 21A/21B and re-verify every score source; writes nothing",
    )
    commands.add_parser(
        "evaluate",
        help="compute the frozen report and print the pooled primary ranking; "
        "writes no evidence",
    )
    publish = commands.add_parser(
        "publish", help="compute, publish and seal the final-baseline reporting evidence"
    )
    publish.add_argument(
        "--source-tree-clean-attested",
        action="store_true",
        help=(
            "attest that the preceding tree was clean and this change set is "
            "self-contained; required by the frozen PASS gate"
        ),
    )
    commands.add_parser(
        "verify", help="verify committed final-baseline reporting evidence without the workspace"
    )
    return parser


def _dispatch(args: argparse.Namespace, root: Path) -> Any:
    if args.command == "preflight":
        inputs = collect_final_baseline_inputs(
            repository_root=root, workspace=Path(args.workspace).resolve()
        )
        return {
            "component": COMPONENT,
            "status": "READY_TO_EVALUATE",
            "methods": [
                {
                    "algorithm_id": method.algorithm_id,
                    "genuine_planned": method.genuine.planned_attempts,
                    "genuine_failures": method.genuine.algorithm_failures,
                    "impostor_planned": method.impostor.planned_attempts,
                    "impostor_failures": method.impostor.algorithm_failures,
                }
                for method in inputs.methods
            ],
        }
    if args.command == "evaluate":
        inputs = collect_final_baseline_inputs(
            repository_root=root, workspace=Path(args.workspace).resolve()
        )
        return evaluate_final_baseline(inputs).summary
    if args.command == "publish":
        if not args.source_tree_clean_attested:
            raise FinalBaselineError(
                "publishing requires --source-tree-clean-attested; commit "
                "everything first, then attest"
            )
        return publish_final_baseline_evidence(
            repository_root=root,
            workspace=Path(args.workspace).resolve(),
            source_tree_clean_attested=True,
        )
    if args.command == "verify":
        return verify_final_baseline_evidence(root)
    raise AssertionError(args.command)
