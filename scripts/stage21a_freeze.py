#!/usr/bin/env python3
"""Create the Stage 21A manifest and evidence; never run an algorithm."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from fpbench.experiments.stage21a_finalization import (  # noqa: E402
    freeze_stage21a,
    verify_stage21a_evidence,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace", type=Path, default=REPOSITORY_ROOT / "workspace"
    )
    parser.add_argument(
        "--source-tree-clean-attested",
        action="store_true",
        help=(
            "attest that the pre-stage tree was clean and this change set is "
            "self-contained; required by the frozen PASS gate"
        ),
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="verify committed Stage 21A evidence without reading the workspace",
    )
    args = parser.parse_args()
    marker = (
        verify_stage21a_evidence(REPOSITORY_ROOT)
        if args.verify
        else freeze_stage21a(
            repository_root=REPOSITORY_ROOT,
            workspace=args.workspace,
            source_tree_clean_attested=args.source_tree_clean_attested,
        )
    )
    print(json.dumps(marker, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
