"""Where an execution plan lives.

Layout, beside the run it belongs to::

    results/<run_id>/plan/jobs.parquet    one row per planned job
    results/<run_id>/plan/plan.json       the definition

**Write order matters.** ``jobs.parquet`` is written first and ``plan.json``
second, because ``plan.json`` is the marker that says the plan is complete. A
crash between the two leaves a jobs file with no definition — visibly
unfinished, and safely replaced — rather than a definition pointing at jobs
that were never written.

**No overwrite.** Ensuring the same plan again is a no-op; a different plan
under the same run is a `PlanConflictError`. Since a run's identity already
covers its pair manifest, a legitimately different set of comparisons produces
a different run and lands somewhere else entirely (docs/adr/0011).
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Iterator, Mapping

import pyarrow as pa
import pyarrow.parquet as pq

from fpbench.core.errors import PlanConflictError, StorageError
from fpbench.core.execution_plan_models import (
    PLAN_SCHEMA_VERSION,
    ExecutionPlan,
    ExecutionPlanDefinition,
    PlannedJob,
    job_manifest_hash,
)
from fpbench.core.serialization import read_json, write_json
from fpbench.storage import plan_schemas
from fpbench.storage.layout import run_directory

__all__ = ["PlanStore"]

_PLAN_MANIFEST = "plan.json"
_JOBS_FILE = "jobs.parquet"


class PlanStore:
    """Immutable storage for one execution plan per run."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    # ------------------------------------------------------------------ paths

    def plan_dir(self, run_id: str) -> Path:
        return run_directory(self.root, run_id) / "plan"

    def plan_manifest_path(self, run_id: str) -> Path:
        return self.plan_dir(run_id) / _PLAN_MANIFEST

    def jobs_path(self, run_id: str) -> Path:
        return self.plan_dir(run_id) / _JOBS_FILE

    def has_plan(self, run_id: str) -> bool:
        return self.plan_manifest_path(run_id).is_file()

    # ------------------------------------------------------------------- write

    def ensure_plan(self, plan: ExecutionPlan) -> Path:
        """Store ``plan``, or confirm the stored one is already it.

        Returns:
            The plan directory.

        Raises:
            PlanConflictError: a different plan is already stored for this run.
        """
        run_id = plan.definition.run_id
        manifest_path = self.plan_manifest_path(run_id)

        if manifest_path.is_file():
            stored = self.read_plan_definition(run_id)
            if stored.plan_fingerprint != plan.definition.plan_fingerprint:
                raise PlanConflictError(
                    f"run {run_id} already has plan {stored.plan_id} "
                    f"({stored.plan_fingerprint[:12]}...); refusing to replace it "
                    f"with {plan.plan_id} ({plan.definition.plan_fingerprint[:12]}...)"
                )
            return manifest_path.parent

        self._write_jobs(plan)
        write_json(manifest_path, plan.definition)
        return manifest_path.parent

    def _write_jobs(self, plan: ExecutionPlan) -> Path:
        path = self.jobs_path(plan.definition.run_id)
        path.parent.mkdir(parents=True, exist_ok=True)

        from fpbench import __version__

        table = plan_schemas.planned_jobs_to_table(plan.jobs)
        definition = plan.definition
        stamped = table.replace_schema_metadata(
            {
                **(table.schema.metadata or {}),
                b"schema_version": PLAN_SCHEMA_VERSION.encode(),
                b"plan_id": definition.plan_id.encode(),
                b"plan_fingerprint": definition.plan_fingerprint.encode(),
                b"run_id": definition.run_id.encode(),
                b"run_fingerprint": definition.run_fingerprint.encode(),
                b"pair_manifest_hash": definition.pair_manifest_hash.encode(),
                b"job_manifest_hash": definition.job_manifest_hash.encode(),
                b"job_count": str(definition.total_jobs).encode(),
                b"fpbench_version": __version__.encode(),
                b"created_utc": _dt.datetime.now(_dt.timezone.utc)
                .isoformat(timespec="seconds")
                .encode(),
            }
        )

        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            pq.write_table(stamped, tmp, compression="zstd")
            tmp.replace(path)
        finally:
            tmp.unlink(missing_ok=True)
        return path

    # -------------------------------------------------------------------- read

    def read_plan_definition(self, run_id: str) -> ExecutionPlanDefinition:
        path = self.plan_manifest_path(run_id)
        if not path.is_file():
            raise StorageError(f"execution plan not found: {path}")
        payload = read_json(path)
        try:
            return ExecutionPlanDefinition(
                plan_id=payload["plan_id"],
                plan_fingerprint=payload["plan_fingerprint"],
                run_id=payload["run_id"],
                run_fingerprint=payload["run_fingerprint"],
                pair_manifest_hash=payload["pair_manifest_hash"],
                total_jobs=payload["total_jobs"],
                stage_counts=payload["stage_counts"],
                release_counts=payload["release_counts"],
                job_manifest_hash=payload["job_manifest_hash"],
                created_utc=payload["created_utc"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError(f"{path}: unreadable execution plan ({exc})") from exc

    def iter_planned_jobs(self, run_id: str) -> Iterator[PlannedJob]:
        yield from self._read_jobs(run_id)

    def read_plan(self, run_id: str) -> ExecutionPlan:
        """Read the plan back and re-derive its job manifest hash.

        The hash is recomputed rather than trusted. A plan is the thing every
        later integrity check is measured against, so a plan that has been
        edited on disk must fail loudly here rather than quietly redefine what
        the run was supposed to be.
        """
        definition = self.read_plan_definition(run_id)
        jobs = tuple(self._read_jobs(run_id))
        try:
            plan = ExecutionPlan(definition=definition, jobs=jobs)
        except ValueError as exc:
            raise StorageError(
                f"{self.plan_dir(run_id)}: stored plan is inconsistent ({exc})"
            ) from exc

        recomputed = job_manifest_hash(definition.run_fingerprint, jobs)
        if recomputed != definition.job_manifest_hash:
            raise StorageError(
                f"{self.jobs_path(run_id)}: job manifest hash does not match "
                f"plan.json; the stored plan has been altered"
            )
        return plan

    def plan_metadata(self, run_id: str) -> Mapping[str, str]:
        path = self.jobs_path(run_id)
        if not path.is_file():
            raise StorageError(f"execution plan jobs not found: {path}")
        try:
            metadata = pq.read_schema(path).metadata or {}
        except (pa.ArrowInvalid, OSError) as exc:
            raise StorageError(f"{path}: unreadable parquet ({exc})") from exc
        return {key.decode(): value.decode() for key, value in metadata.items()}

    # --------------------------------------------------------------- internal

    def _read_jobs(self, run_id: str) -> list[PlannedJob]:
        path = self.jobs_path(run_id)
        if not path.is_file():
            raise StorageError(f"execution plan jobs not found: {path}")
        try:
            table = pq.read_table(path)
        except (pa.ArrowInvalid, OSError) as exc:
            raise StorageError(f"{path}: unreadable parquet ({exc})") from exc
        try:
            return plan_schemas.table_to_planned_jobs(table)
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError(f"{path}: unreadable planned jobs ({exc})") from exc
