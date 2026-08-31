#!/usr/bin/env python3
"""Operate the frozen Stage 21B cross-subject raw-result runs."""

from __future__ import annotations

import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from fpbench.stage21b.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main(repository_root=REPOSITORY_ROOT))
