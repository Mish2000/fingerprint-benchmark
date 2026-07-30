"""Where a run's artefacts live on disk.

One definition, shared by every store that writes under a run, so that the
result store and the plan store cannot drift into disagreeing about where a run
directory is::

    <workspace>/results/<run_id>/
    ├── run.json
    ├── plan/
    │   ├── plan.json
    │   └── jobs.parquet
    ├── raw/jobs/<job_id>.parquet
    ├── derived/            regenerable: progress, audit snapshots
    └── completion.json
"""

from __future__ import annotations

from pathlib import Path

from fpbench.core.identifiers import validate_id

__all__ = ["results_root", "run_directory", "derived_directory"]


def results_root(root: Path) -> Path:
    return Path(root) / "results"


def run_directory(root: Path, run_id: str) -> Path:
    return results_root(root) / validate_id(run_id)


def derived_directory(root: Path, run_id: str) -> Path:
    """Regenerable artefacts. Everything here may be deleted or overwritten."""
    return run_directory(root, run_id) / "derived"
