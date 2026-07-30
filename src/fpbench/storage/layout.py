"""Where a run's artefacts live on disk.

One definition, shared by every store that writes under a run, so that the
result store and the plan store cannot drift into disagreeing about where a run
directory is::

    <workspace>/results/<run_id>/
    ├── run.json
    ├── runtime.json        which runtime bundle produced these results
    ├── plan/
    │   ├── plan.json
    │   └── jobs.parquet
    ├── raw/jobs/<job_id>.parquet
    ├── result-set/
    │   ├── manifest.json
    │   └── results.parquet
    ├── derived/            regenerable: progress, audit snapshots, summaries
    ├── completion.json
    └── research-receipt.json

Runtime bundles are not run-scoped. One bundle can back many runs, and its
identity is its contents rather than the run that first materialised it::

    <workspace>/runtime/bundles/<bundle_id>/
    ├── bundle.json
    └── assets/<filename>
"""

from __future__ import annotations

from pathlib import Path

from fpbench.core.identifiers import validate_id

__all__ = [
    "results_root",
    "run_directory",
    "derived_directory",
    "result_set_directory",
    "runtime_root",
    "runtime_bundles_root",
    "runtime_bundle_directory",
    "runtime_bundle_assets_directory",
]


def results_root(root: Path) -> Path:
    return Path(root) / "results"


def run_directory(root: Path, run_id: str) -> Path:
    return results_root(root) / validate_id(run_id)


def derived_directory(root: Path, run_id: str) -> Path:
    """Regenerable artefacts. Everything here may be deleted or overwritten."""
    return run_directory(root, run_id) / "derived"


def result_set_directory(root: Path, run_id: str) -> Path:
    """The immutable identity of this run's raw results (docs/adr/0019)."""
    return run_directory(root, run_id) / "result-set"


def runtime_root(root: Path) -> Path:
    return Path(root) / "runtime"


def runtime_bundles_root(root: Path) -> Path:
    return runtime_root(root) / "bundles"


def runtime_bundle_directory(root: Path, bundle_id: str) -> Path:
    return runtime_bundles_root(root) / validate_id(bundle_id)


def runtime_bundle_assets_directory(root: Path, bundle_id: str) -> Path:
    from fpbench.core.runtime_models import ASSETS_DIRECTORY

    return runtime_bundle_directory(root, bundle_id) / ASSETS_DIRECTORY
