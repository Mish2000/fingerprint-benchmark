#!/usr/bin/env python3
"""Freeze the Stage 20B outcomes, build the diagnostics, publish the evidence.

Runs on Windows, natively, after the run itself has finished on the certified
Linux target — reading 6,000 stored outcomes back over the 9p mount takes far
longer than running them did, and docs/adr/0017 separates the executor from the
verifier exactly so this can happen elsewhere.

Three steps, in order, and none of them touches the route:

.. code-block:: text

    diagnostics   section 28's report, over outcomes that are already frozen
    evidence      the eight documents of section 31
    marker        section 32, with section 25's conditions derived from them

.. code-block:: text

    python scripts/stage20b_publish.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from fpbench.core.serialization import read_json  # noqa: E402
from fpbench.experiments.stage20b_diagnostics import (  # noqa: E402
    build_stage20b_report,
    read_algorithm2_scores,
    read_outcomes,
)
from fpbench.experiments.stage20b_finalization import (  # noqa: E402
    write_stage20b_documents,
)
from fpbench.experiments.stage20b_identity import (  # noqa: E402
    EVIDENCE_DIRECTORY,
    STAGE_20B_FINALIZATION_NAME,
)

DEFAULT_ROOT = Path(
    os.environ.get(
        "FPBENCH_STAGE20B_ROOT", r"C:\Users\sirak\.cache\fpbench\private\stage20b"
    )
)
DEFAULT_GATE_A = Path(
    os.environ.get(
        "FPBENCH_STAGE20B_GATE_A",
        r"C:\Users\sirak\.cache\fpbench\third_party\unibo-mcc-sdk-v2\gate-a"
        r"\gate-a-bridge-reproduction.json",
    )
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage 20B evidence publisher")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--gate-a", type=Path, default=DEFAULT_GATE_A)
    parser.add_argument("--gate-b", type=Path)
    parser.add_argument("--outcomes", type=Path)
    parser.add_argument("--environment", type=Path)
    parser.add_argument(
        "--algorithm2-results",
        type=Path,
        default=REPO / "workspace" / "results" / "run_f0468f28ffba" / "raw",
        help="Algorithm 2's stored raw results, for the section 29 rank comparison",
    )
    args = parser.parse_args()

    root = Path(args.root)
    outcomes_path = args.outcomes or root / "pair-outcomes.jsonl"
    gate_b_path = args.gate_b or root / "gate-b" / "gate-b-mindtct-parity.json"
    environment_path = args.environment or root / "environment.json"

    for label, path in (
        ("outcomes", outcomes_path),
        ("Gate A record", args.gate_a),
        ("Gate B record", gate_b_path),
        ("environment record", environment_path),
    ):
        if not Path(path).is_file():
            print(f"the {label} is absent: {path}", file=sys.stderr)
            return 2

    outcomes = read_outcomes(outcomes_path)
    print(f"read {len(outcomes)} stored outcomes")

    algorithm2 = None
    if args.algorithm2_results and Path(args.algorithm2_results).is_dir():
        algorithm2 = read_algorithm2_scores(args.algorithm2_results)
        print(f"read {len(algorithm2)} Algorithm 2 scores for the rank comparison")

    diagnostics = build_stage20b_report(outcomes, algorithm2=algorithm2)
    diagnostics_path = root / "diagnostic-report.json"
    diagnostics_path.write_bytes(
        (json.dumps(diagnostics, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode(
            "utf-8"
        )
    )
    print(f"diagnostics: {diagnostics_path}")

    readme = REPO / EVIDENCE_DIRECTORY / "README.md"
    if not readme.is_file():
        print(f"write the README first: {readme}", file=sys.stderr)
        return 2

    recorded = read_json(environment_path)
    written = write_stage20b_documents(
        repository_root=REPO,
        gate_a=read_json(args.gate_a),
        gate_b=read_json(gate_b_path),
        diagnostics=diagnostics,
        outcomes=outcomes,
        environment=recorded.get("runtime", {}),
        runtime=recorded.get("dependencies", {}),
        readme=readme.read_text(encoding="utf-8"),
    )
    for name, path in sorted(written.items()):
        print(f"  {name}")

    marker = read_json(written[STAGE_20B_FINALIZATION_NAME])
    print(f"\noutcome: {marker['outcome']}")
    print(
        f"  stored {marker['stored_outcomes']} / score-bearing "
        f"{marker['score_bearing']} / missing {marker['missing']}"
    )
    print(f"  preferred_final_fifth: {marker['preferred_final_fifth']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
