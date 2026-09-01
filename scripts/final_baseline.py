#!/usr/bin/env python3
"""Operate the frozen final-baseline TAR/FAR/FRR report."""

from __future__ import annotations

import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from fpbench.final_baseline.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main(repository_root=REPOSITORY_ROOT))
