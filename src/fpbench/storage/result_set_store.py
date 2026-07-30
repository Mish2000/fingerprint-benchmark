"""Where a run's raw results acquire an identity of their own.

Layout, beside the run they belong to::

    results/<run_id>/result-set/results.parquet   one row per planned job
    results/<run_id>/result-set/manifest.json     the identity

**Write order matters**, for the same reason it does in the plan store:
``results.parquet`` first, ``manifest.json`` second, because the manifest is
the marker that says the set is complete. A crash between the two leaves an
index with no identity — visibly unfinished — rather than an identity pointing
at rows that were never written.

**Nothing is trusted twice.** Writing a result set re-reads every raw result
file and re-derives its hash. An index that merely repeated numbers handed to
it would be a second place for the truth to live, and the first thing a
downstream analysis would have to stop believing (docs/adr/0019).

**No overwrite.** The same set again is a no-op; a different set under the same
run is a conflict. One changed score produces a different fingerprint, and a
different fingerprint is a different body of evidence — never a correction.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Mapping

import pyarrow as pa
import pyarrow.parquet as pq

from fpbench.core.enums import ExecutionStatus
from fpbench.core.errors import ResultSetConflictError, StorageError
from fpbench.core.result_models import raw_result_hash
from fpbench.core.result_set_models import (
    RESULT_SET_SCHEMA_VERSION,
    ResultSetEntry,
    ResultSetManifest,
    ordered_results_hash,
    result_set_fingerprint,
    result_set_id,
)
from fpbench.core.serialization import read_json, write_json
from fpbench.storage import layout, result_set_schemas
from fpbench.storage.result_store import ResultStore

__all__ = ["ResultSetStore"]

_MANIFEST = "manifest.json"
_ENTRIES = "results.parquet"


class ResultSetStore:
    """Immutable storage for one result-set identity per run."""

    def __init__(self, root: Path, *, result_store: ResultStore | None = None) -> None:
        self.root = Path(root)
        self._results = result_store or ResultStore(self.root)

    # ------------------------------------------------------------------ paths

    def result_set_dir(self, run_id: str) -> Path:
        return layout.result_set_directory(self.root, run_id)

    def manifest_path(self, run_id: str) -> Path:
        return self.result_set_dir(run_id) / _MANIFEST

    def entries_path(self, run_id: str) -> Path:
        return self.result_set_dir(run_id) / _ENTRIES

    def has_result_set(self, run_id: str) -> bool:
        return self.manifest_path(run_id).is_file()

    # ------------------------------------------------------------------ write

    def ensure_result_set(
        self,
        manifest: ResultSetManifest,
        entries: tuple[ResultSetEntry, ...],
    ) -> Path:
        """Store the set, or confirm the stored one is already it.

        Returns:
            The result-set directory.

        Raises:
            StorageError: the manifest and its entries disagree, or an entry
                does not describe the result file on disk.
            ResultSetConflictError: a different result set is already stored.
        """
        entries = tuple(entries)
        self._require_coherent(manifest, entries)
        self._require_entries_match_stored_results(manifest.run_id, entries)

        manifest_path = self.manifest_path(manifest.run_id)
        if manifest_path.is_file():
            stored, _ = self.read_result_set(manifest.run_id)
            if stored.result_set_fingerprint != manifest.result_set_fingerprint:
                raise ResultSetConflictError(
                    f"run {manifest.run_id} already holds result set "
                    f"{stored.result_set_id} "
                    f"({stored.result_set_fingerprint[:12]}...); refusing to replace "
                    f"it with {manifest.result_set_id} "
                    f"({manifest.result_set_fingerprint[:12]}...)"
                )
            return manifest_path.parent

        self._write_entries(manifest, entries)
        write_json(manifest_path, manifest)
        return manifest_path.parent

    # ------------------------------------------------------------------- read

    def read_result_set(
        self, run_id: str
    ) -> tuple[ResultSetManifest, tuple[ResultSetEntry, ...]]:
        """Read the set back and re-derive its hashes.

        The ordered-results hash is recomputed rather than trusted, for the same
        reason ``PlanStore.read_plan`` recomputes its job manifest hash: this
        record is what every later citation is measured against, so an edited
        index must fail loudly here rather than quietly redefine the evidence.
        """
        manifest = self.read_manifest(run_id)
        entries = tuple(self._read_entries(run_id))

        if ordered_results_hash(entries) != manifest.ordered_results_hash:
            raise StorageError(
                f"{self.entries_path(run_id)}: ordered results hash does not match "
                f"manifest.json; the stored result set has been altered"
            )
        recomputed = result_set_fingerprint(
            run_fingerprint=manifest.run_fingerprint,
            plan_fingerprint=manifest.plan_fingerprint,
            runtime_bundle_fingerprint=manifest.runtime_bundle_fingerprint,
            entries=entries,
            success_count=manifest.success_count,
            failure_count=manifest.failure_count,
        )
        if recomputed != manifest.result_set_fingerprint:
            raise StorageError(
                f"{self.result_set_dir(run_id)}: the stored result set does not "
                f"fingerprint to its own id"
            )
        return manifest, entries

    def read_manifest(self, run_id: str) -> ResultSetManifest:
        path = self.manifest_path(run_id)
        if not path.is_file():
            raise StorageError(f"result-set manifest not found: {path}")
        payload = read_json(path)
        try:
            return ResultSetManifest(
                result_set_id=payload["result_set_id"],
                result_set_fingerprint=payload["result_set_fingerprint"],
                run_id=payload["run_id"],
                run_fingerprint=payload["run_fingerprint"],
                plan_id=payload["plan_id"],
                plan_fingerprint=payload["plan_fingerprint"],
                runtime_bundle_id=payload["runtime_bundle_id"],
                runtime_bundle_fingerprint=payload["runtime_bundle_fingerprint"],
                total_results=payload["total_results"],
                success_count=payload["success_count"],
                failure_count=payload["failure_count"],
                ordered_results_hash=payload["ordered_results_hash"],
                created_utc=payload["created_utc"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError(
                f"{path}: unreadable result-set manifest ({exc})"
            ) from exc

    def result_set_metadata(self, run_id: str) -> Mapping[str, str]:
        path = self.entries_path(run_id)
        if not path.is_file():
            raise StorageError(f"result-set entries not found: {path}")
        try:
            metadata = pq.read_schema(path).metadata or {}
        except (pa.ArrowInvalid, OSError) as exc:
            raise StorageError(f"{path}: unreadable parquet ({exc})") from exc
        return {key.decode(): value.decode() for key, value in metadata.items()}

    # ----------------------------------------------------------------- verify

    def verify_result_set(self, run_id: str) -> ResultSetManifest:
        """Read the set and confirm every entry still describes its result file.

        Raises:
            StorageError: anything about the set is no longer true.
        """
        manifest, entries = self.read_result_set(run_id)
        self._require_entries_match_stored_results(run_id, entries)
        self._require_status_counts(manifest, entries)
        return manifest

    # --------------------------------------------------------------- internal

    def _require_coherent(
        self, manifest: ResultSetManifest, entries: tuple[ResultSetEntry, ...]
    ) -> None:
        if not entries:
            raise StorageError("a result set with no entries is not a result set")
        if len(entries) != manifest.total_results:
            raise StorageError(
                f"result set declares {manifest.total_results} results but carries "
                f"{len(entries)}"
            )
        if [entry.ordinal for entry in entries] != list(range(len(entries))):
            raise StorageError(
                "result-set ordinals must be 0..n-1 with no gaps and no repeats"
            )
        job_ids = [entry.job_id for entry in entries]
        if len(set(job_ids)) != len(job_ids):
            raise StorageError("a job may appear at most once in a result set")
        if ordered_results_hash(entries) != manifest.ordered_results_hash:
            raise StorageError(
                "the manifest's ordered results hash does not cover these entries"
            )
        recomputed = result_set_fingerprint(
            run_fingerprint=manifest.run_fingerprint,
            plan_fingerprint=manifest.plan_fingerprint,
            runtime_bundle_fingerprint=manifest.runtime_bundle_fingerprint,
            entries=entries,
            success_count=manifest.success_count,
            failure_count=manifest.failure_count,
        )
        if recomputed != manifest.result_set_fingerprint:
            raise StorageError(
                "the manifest does not fingerprint to the set it describes"
            )
        if result_set_id(recomputed) != manifest.result_set_id:
            raise StorageError("the manifest is stored under a foreign result-set id")

    def _require_entries_match_stored_results(
        self, run_id: str, entries: tuple[ResultSetEntry, ...]
    ) -> None:
        """Re-read every result and re-derive its hash.

        Expensive and non-negotiable. An index nobody checked against the files
        is a claim, not evidence.
        """
        stored = set(self._results.stored_job_ids(run_id))
        indexed = {entry.job_id for entry in entries}

        missing = sorted(indexed - stored)
        if missing:
            raise StorageError(
                f"result set names {len(missing)} job(s) with no stored result: "
                f"{missing[:3]}"
            )
        extra = sorted(stored - indexed)
        if extra:
            raise StorageError(
                f"run {run_id} holds {len(extra)} result(s) the set does not "
                f"account for: {extra[:3]}"
            )

        for entry in entries:
            record = self._results.read_raw_result(run_id, entry.job_id)
            actual = raw_result_hash(record)
            if actual != entry.result_hash:
                raise StorageError(
                    f"result {entry.job_id} hashes to {actual[:12]}..., but the "
                    f"result set records {entry.result_hash[:12]}..."
                )

    def _require_status_counts(
        self, manifest: ResultSetManifest, entries: tuple[ResultSetEntry, ...]
    ) -> None:
        successes = 0
        failures = 0
        for entry in entries:
            record = self._results.read_raw_result(manifest.run_id, entry.job_id)
            if record.status is ExecutionStatus.SUCCESS:
                successes += 1
            else:
                failures += 1
        if (successes, failures) != (manifest.success_count, manifest.failure_count):
            raise StorageError(
                f"result set claims {manifest.success_count} successes and "
                f"{manifest.failure_count} failures; the files hold {successes} "
                f"and {failures}"
            )

    def _write_entries(
        self, manifest: ResultSetManifest, entries: tuple[ResultSetEntry, ...]
    ) -> Path:
        path = self.entries_path(manifest.run_id)
        path.parent.mkdir(parents=True, exist_ok=True)

        from fpbench import __version__

        table = result_set_schemas.result_set_entries_to_table(entries)
        stamped = table.replace_schema_metadata(
            {
                **(table.schema.metadata or {}),
                b"schema_version": RESULT_SET_SCHEMA_VERSION.encode(),
                b"result_set_id": manifest.result_set_id.encode(),
                b"result_set_fingerprint": manifest.result_set_fingerprint.encode(),
                b"ordered_results_hash": manifest.ordered_results_hash.encode(),
                b"run_id": manifest.run_id.encode(),
                b"run_fingerprint": manifest.run_fingerprint.encode(),
                b"plan_id": manifest.plan_id.encode(),
                b"plan_fingerprint": manifest.plan_fingerprint.encode(),
                b"runtime_bundle_id": manifest.runtime_bundle_id.encode(),
                b"row_count": str(len(entries)).encode(),
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

    def _read_entries(self, run_id: str) -> list[ResultSetEntry]:
        path = self.entries_path(run_id)
        if not path.is_file():
            raise StorageError(f"result-set entries not found: {path}")
        try:
            table = pq.read_table(path)
        except (pa.ArrowInvalid, OSError) as exc:
            raise StorageError(f"{path}: unreadable parquet ({exc})") from exc
        try:
            return result_set_schemas.table_to_result_set_entries(table)
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError(f"{path}: unreadable result-set entries ({exc})") from exc
