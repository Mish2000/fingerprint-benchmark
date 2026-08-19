#!/usr/bin/env python3
"""Gate A: the production bridge must reproduce Stage 20A's numbers exactly.

Runs on the machine that has the vendor assembly. Five comparisons over the
official ``SampleMinutiae`` files, through the production bridge and the
production payload format, compared bit for bit against the doubles Stage 20A's
qualification probe recorded.

There is no tolerance. If Gate A does not pass, nothing else in Stage 20B runs.

.. code-block:: text

    python scripts/stage20b_gate_a.py --build
    python scripts/stage20b_gate_a.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from fpbench.experiments.stage20b_gates import (  # noqa: E402
    GATE_A_PASS,
    run_gate_a,
)
from fpbench.experiments.stage20b_mcc_runtime import (  # noqa: E402
    OFFICIAL_SAMPLES,
    build_bridge,
    resolve_runtime,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage 20B Gate A")
    parser.add_argument(
        "--build", action="store_true", help="compile the production bridge first"
    )
    parser.add_argument("--output", type=Path, help="where to write the gate record")
    args = parser.parse_args()

    runtime = build_bridge(repository_root=REPO) if args.build else resolve_runtime(
        repository_root=REPO
    )
    if not runtime.bridge.is_file():
        print(f"the production bridge is absent: {runtime.bridge}", file=sys.stderr)
        print("run with --build on a Windows host with .NET Framework 4.x", file=sys.stderr)
        return 2

    record = run_gate_a(
        bridge=runtime.bridge,
        samples=runtime.samples,
        sample_files=OFFICIAL_SAMPLES,
        workspace=runtime.store / "gate-a",
    )
    for row in record["comparisons"]:
        mark = "exact" if row["exact"] else "MISMATCH"
        print(
            f"  {row['comparison']:<18} {row['status']:<4} "
            f"{row['production_score']!r} vs {row['stage20a_score']!r}  {mark}"
        )
    print(f"\n{record['outcome']}  ({record['exact_matches']}/{record['expected_comparisons']} exact)")

    output = args.output or (runtime.store / "gate-a" / "gate-a-bridge-reproduction.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(
        (json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    )
    print(f"written: {output}")
    return 0 if record["outcome"] == GATE_A_PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
