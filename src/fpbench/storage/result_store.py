"""Where raw results live, and the rules that keep them trustworthy.

Layout under the workspace root::

    results/<run_id>/run.json
    results/<run_id>/raw/jobs/<job_id>.parquet

**One file per job**, not one growing table. Parquet has no safe append, and a
single shared file would mean every comparison races every other one. A file
per job buys atomicity, resume, duplicate prevention and — later — parallel
execution, for the price of a consolidated table that can be regenerated from
these files whenever it is wanted (docs/adr/0009).

**No overwrite, ever.** There is no ``overwrite=True`` on this class. A result
file that already exists is either the same result, in which case the runner
skips the job, or a different one, in which case something is wrong and the
correct answer is a new run rather than a lost measurement.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Iterator, Mapping

import pyarrow as pa
import pyarrow.parquet as pq

from fpbench.core.enums import EnvironmentStatus, ScoreDirection
from fpbench.core.errors import ResultConflictError, StorageError
from fpbench.core.execution_models import (
    AlgorithmDescriptor,
    EnvironmentReport,
    ExecutionProfile,
)
from fpbench.core.identifiers import CohortId, validate_id
from fpbench.core.research_models import (
    ResearchFinalizationMarker,
    ResearchRunReceipt,
)
from fpbench.core.result_models import (
    RESULT_SCHEMA_VERSION,
    RawResultRecord,
    RunDefinition,
    raw_result_hash,
)
from fpbench.core.run_state_models import RunCompletion
from fpbench.core.runtime_models import RunRuntimeReference
from fpbench.core.serialization import read_json, stable_hash, to_plain, write_json
from fpbench.storage import layout, result_schemas

__all__ = ["ResultStore"]

_RUN_MANIFEST = "run.json"
_COMPLETION_MANIFEST = "completion.json"
_RUNTIME_REFERENCE = "runtime.json"
_RESEARCH_RECEIPT = "research-receipt.json"
_RESEARCH_FINALIZATION = "research-finalization.json"

_PREPARATION_RECEIPT_FIELDS = frozenset(
    {
        "preparation_set_id",
        "preparation_set_fingerprint",
        "transform_profile_id",
        "transform_profile_fingerprint",
        "transform_runtime_fingerprint",
    }
)


class ResultStore:
    """Append-only storage for run manifests and raw comparison results."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    # ------------------------------------------------------------------ paths

    @property
    def results_root(self) -> Path:
        return layout.results_root(self.root)

    def run_dir(self, run_id: str) -> Path:
        return layout.run_directory(self.root, run_id)

    def run_manifest_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / _RUN_MANIFEST

    def raw_jobs_dir(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "raw" / "jobs"

    def raw_result_path(self, run_id: str, job_id: str) -> Path:
        return self.raw_jobs_dir(run_id) / f"{validate_id(job_id)}.parquet"

    def completion_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / _COMPLETION_MANIFEST

    def runtime_reference_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / _RUNTIME_REFERENCE

    def research_receipt_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / _RESEARCH_RECEIPT

    def research_finalization_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / _RESEARCH_FINALIZATION

    def derived_path(self, run_id: str, name: str) -> Path:
        """A regenerable artefact. Free to overwrite, free to delete."""
        return layout.derived_directory(self.root, run_id) / name

    # -------------------------------------------------------------------- run

    def ensure_run(self, run: RunDefinition) -> Path:
        """Make sure ``run.json`` exists and describes exactly this run.

        Idempotent by design: re-running after a crash must be a no-op, not a
        conflict. Only a *different* run claiming the same id is an error, and
        since the id is derived from the fingerprint that should be impossible
        without a hash collision or a hand-edited file.

        Returns:
            The run directory.
        """
        path = self.run_manifest_path(run.run_id)
        if path.is_file():
            existing = self.read_run(run.run_id)
            if existing.run_fingerprint != run.run_fingerprint:
                raise ResultConflictError(
                    f"{path} already describes run fingerprint "
                    f"{existing.run_fingerprint[:12]}..., not "
                    f"{run.run_fingerprint[:12]}..."
                )
            return path.parent

        write_json(path, run)
        return path.parent

    def read_run(self, run_id: str) -> RunDefinition:
        path = self.run_manifest_path(run_id)
        if not path.is_file():
            raise StorageError(f"run manifest not found: {path}")
        payload = read_json(path)
        try:
            return _run_from_payload(payload)
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError(f"{path}: unreadable run manifest ({exc})") from exc

    def run_ids(self) -> tuple[str, ...]:
        if not self.results_root.is_dir():
            return ()
        return tuple(
            sorted(
                p.name
                for p in self.results_root.iterdir()
                if (p / _RUN_MANIFEST).is_file()
            )
        )

    # ------------------------------------------------------------- completion

    def has_completion(self, run_id: str) -> bool:
        return self.completion_path(run_id).is_file()

    def ensure_completion(self, completion: RunCompletion) -> Path:
        """Write ``completion.json`` once, or confirm the stored one matches.

        Idempotent for the same fingerprint, a conflict for a different one.
        There is no overwrite: a run that has already been declared verified
        cannot quietly be declared verified about something else.
        """
        path = self.completion_path(completion.run_id)
        if path.is_file():
            stored = self.read_completion(completion.run_id)
            if stored.completion_fingerprint != completion.completion_fingerprint:
                raise ResultConflictError(
                    f"{path} already declares completion "
                    f"{stored.completion_fingerprint[:12]}..., not "
                    f"{completion.completion_fingerprint[:12]}..."
                )
            return path
        return write_json(path, completion)

    def read_completion(self, run_id: str) -> RunCompletion:
        path = self.completion_path(run_id)
        if not path.is_file():
            raise StorageError(f"completion manifest not found: {path}")
        payload = read_json(path)
        try:
            return RunCompletion(
                completion_id=payload["completion_id"],
                completion_fingerprint=payload["completion_fingerprint"],
                run_id=payload["run_id"],
                run_fingerprint=payload["run_fingerprint"],
                plan_id=payload["plan_id"],
                plan_fingerprint=payload["plan_fingerprint"],
                pair_manifest_hash=payload["pair_manifest_hash"],
                audit_fingerprint=payload["audit_fingerprint"],
                planned_jobs=payload["planned_jobs"],
                success_count=payload["success_count"],
                failure_count=payload["failure_count"],
                completed_utc=payload["completed_utc"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError(
                f"{path}: unreadable completion manifest ({exc})"
            ) from exc

    def write_derived(self, run_id: str, name: str, value: object) -> Path:
        """Persist a regenerable snapshot. Overwriting is expected here."""
        return write_json(self.derived_path(run_id, name), value)

    # -------------------------------------------------------- runtime binding

    def has_runtime_reference(self, run_id: str) -> bool:
        return self.runtime_reference_path(run_id).is_file()

    def ensure_runtime_reference(self, reference: RunRuntimeReference) -> Path:
        """Record which runtime bundle this run is bound to, once.

        Written before the first comparison and never rewritten. A run that
        changes its executable half way through is not one run, and the correct
        response is a new bundle and a new run rather than an edited binding
        (docs/adr/0018).
        """
        path = self.runtime_reference_path(reference.run_id)
        if path.is_file():
            stored = self.read_runtime_reference(reference.run_id)
            if (
                stored.runtime_reference_fingerprint
                != reference.runtime_reference_fingerprint
            ):
                raise ResultConflictError(
                    f"{path} already binds run {reference.run_id} to runtime "
                    f"{stored.bundle_id}; refusing to rebind it to "
                    f"{reference.bundle_id}"
                )
            return path
        return write_json(path, reference)

    def read_runtime_reference(self, run_id: str) -> RunRuntimeReference:
        path = self.runtime_reference_path(run_id)
        if not path.is_file():
            raise StorageError(f"runtime reference not found: {path}")
        payload = read_json(path)
        try:
            return RunRuntimeReference(
                runtime_reference_id=payload["runtime_reference_id"],
                runtime_reference_fingerprint=payload[
                    "runtime_reference_fingerprint"
                ],
                run_id=payload["run_id"],
                run_fingerprint=payload["run_fingerprint"],
                environment_fingerprint=payload["environment_fingerprint"],
                bundle_id=payload["bundle_id"],
                bundle_fingerprint=payload["bundle_fingerprint"],
                asset_sha256s=payload["asset_sha256s"],
                created_utc=payload["created_utc"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError(
                f"{path}: unreadable runtime reference ({exc})"
            ) from exc

    # ------------------------------------------------------- research receipt

    def has_research_receipt(self, run_id: str) -> bool:
        return self.research_receipt_path(run_id).is_file()

    def ensure_research_receipt(self, receipt: ResearchRunReceipt) -> Path:
        """Write the sanitised receipt once, or confirm the stored one matches."""
        from fpbench.core.research_models import research_receipt_fingerprint

        path = self.research_receipt_path(receipt.run_id)
        if path.is_file():
            stored = self.read_research_receipt(receipt.run_id)
            if research_receipt_fingerprint(stored) != research_receipt_fingerprint(
                receipt
            ):
                if _is_research_receipt_schema_upgrade(stored, receipt):
                    _archive_publication(path)
                    return write_json(path, receipt)
                raise ResultConflictError(
                    f"{path} already carries a different research receipt for run "
                    f"{receipt.run_id}"
                )
            return path
        return write_json(path, receipt)

    def read_research_receipt(self, run_id: str) -> ResearchRunReceipt:
        path = self.research_receipt_path(run_id)
        if not path.is_file():
            raise StorageError(f"research receipt not found: {path}")
        payload = read_json(path)
        try:
            return ResearchRunReceipt(**payload)
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError(f"{path}: unreadable research receipt ({exc})") from exc

    # ------------------------------------------------ research finalization

    def has_research_finalization(self, run_id: str) -> bool:
        return self.research_finalization_path(run_id).is_file()

    def ensure_research_finalization(
        self, marker: ResearchFinalizationMarker
    ) -> Path:
        """Publish the immutable, last-written authority for finalization."""
        path = self.research_finalization_path(marker.run_id)
        if path.is_file():
            stored = self.read_research_finalization(marker.run_id)
            if stored.finalization_fingerprint != marker.finalization_fingerprint:
                if _is_research_finalization_schema_upgrade(stored, marker):
                    _archive_publication(path)
                    return write_json(path, marker)
                raise ResultConflictError(
                    f"{path} already commits a different research finalization "
                    f"for run {marker.run_id}"
                )
            return path
        return write_json(path, marker)

    def read_research_finalization(
        self, run_id: str
    ) -> ResearchFinalizationMarker:
        path = self.research_finalization_path(run_id)
        if not path.is_file():
            raise StorageError(f"research finalization marker not found: {path}")
        payload = read_json(path)
        try:
            return ResearchFinalizationMarker(**payload)
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError(
                f"{path}: unreadable research finalization marker ({exc})"
            ) from exc

    # ------------------------------------------------------------ raw results

    def stored_job_ids(self, run_id: str) -> tuple[str, ...]:
        """Every job id that has a result file, sorted.

        Reads the directory rather than any counter: the files are the only
        thing that can say what was actually stored (docs/adr/0012).
        """
        directory = self.raw_jobs_dir(run_id)
        if not directory.is_dir():
            return ()
        return tuple(sorted(path.stem for path in directory.glob("*.parquet")))

    def has_raw_result(self, run_id: str, job_id: str) -> bool:
        return self.raw_result_path(run_id, job_id).is_file()

    def write_raw_result(self, result: RawResultRecord) -> Path:
        """Persist one result. Refuses to touch an existing file.

        There is no override. The runner is expected to have called
        :meth:`has_raw_result` first if it intends to resume.
        """
        path = self.raw_result_path(result.run_id, result.job_id)
        if path.exists():
            raise ResultConflictError(
                f"{path} already exists; raw results are immutable "
                "(docs/adr/0009)"
            )

        table = result_schemas.raw_results_to_table([result])
        stamped = table.replace_schema_metadata(
            {
                **(table.schema.metadata or {}),
                **{
                    key.encode(): value.encode()
                    for key, value in self._metadata_for(result).items()
                },
            }
        )

        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            pq.write_table(stamped, tmp, compression="zstd")
            tmp.replace(path)
        finally:
            tmp.unlink(missing_ok=True)
        return path

    def read_raw_result(self, run_id: str, job_id: str) -> RawResultRecord:
        path = self.raw_result_path(run_id, job_id)
        table = self._read_table(path)
        records = result_schemas.table_to_raw_results(table)
        if len(records) != 1:
            raise StorageError(
                f"{path}: expected exactly one result row, found {len(records)}"
            )
        return records[0]

    def iter_raw_results(self, run_id: str) -> Iterator[RawResultRecord]:
        """Every stored result for a run, ordered by ``job_id``.

        Sorted so that iterating a run is reproducible; directory order is not.
        """
        directory = self.raw_jobs_dir(run_id)
        if not directory.is_dir():
            return
        for path in sorted(directory.glob("*.parquet")):
            yield self.read_raw_result(run_id, path.stem)

    def raw_result_metadata(self, run_id: str, job_id: str) -> Mapping[str, str]:
        path = self.raw_result_path(run_id, job_id)
        if not path.is_file():
            raise StorageError(f"result not found: {path}")
        try:
            metadata = pq.read_schema(path).metadata or {}
        except pa.ArrowInvalid as exc:
            raise StorageError(f"{path}: unreadable parquet ({exc})") from exc
        return {key.decode(): value.decode() for key, value in metadata.items()}

    # --------------------------------------------------------------- internal

    def _metadata_for(self, result: RawResultRecord) -> Mapping[str, str]:
        from fpbench import __version__

        return {
            "schema_version": RESULT_SCHEMA_VERSION,
            "result_hash": raw_result_hash(result),
            "run_id": result.run_id,
            "job_id": result.job_id,
            "job_fingerprint": result.job_fingerprint,
            "pair_manifest_hash": result.pair_manifest_hash,
            "algorithm_fingerprint": result.algorithm_fingerprint,
            "execution_profile_hash": result.execution_profile_hash,
            "fpbench_version": __version__,
            "created_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(
                timespec="seconds"
            ),
            "row_count": "1",
        }

    @staticmethod
    def _read_table(path: Path) -> pa.Table:
        """Read one result file and close it before returning.

        ``pq.read_table`` leaves the underlying handle to be closed whenever the
        reader is collected, which on Windows means a file that was just read can
        still be locked against deletion or replacement for an arbitrary while.
        Reading through an explicit context manager makes the close deterministic
        — a run that reads six thousand results and then tidies up should not
        depend on when the garbage collector last ran.
        """
        if not path.is_file():
            raise StorageError(f"result not found: {path}")
        try:
            with pq.ParquetFile(path) as reader:
                return reader.read()
        except (pa.ArrowInvalid, OSError) as exc:
            raise StorageError(f"{path}: unreadable parquet ({exc})") from exc


def _is_research_receipt_schema_upgrade(
    stored: ResearchRunReceipt, new: ResearchRunReceipt
) -> bool:
    if stored.schema_version != "1" or new.schema_version != "2":
        return False
    old = dict(to_plain(stored))
    current = dict(to_plain(new))
    ignored = {"schema_version", "created_utc", *_PREPARATION_RECEIPT_FIELDS}
    return all(old[key] == current[key] for key in old if key not in ignored)


def _is_research_finalization_schema_upgrade(
    stored: ResearchFinalizationMarker, new: ResearchFinalizationMarker
) -> bool:
    if stored.schema_version != "1" or new.schema_version != "2":
        return False
    invariant = (
        "run_id",
        "run_fingerprint",
        "plan_id",
        "plan_fingerprint",
        "environment_fingerprint",
        "runtime_reference_fingerprint",
        "result_set_fingerprint",
        "audit_fingerprint",
        "sourceafis_validation_fingerprint",
        "completion_fingerprint",
    )
    return all(getattr(stored, key) == getattr(new, key) for key in invariant)


def _archive_publication(path: Path) -> Path:
    payload = read_json(path)
    version = str(payload.get("schema_version") or "unknown")
    fingerprint = stable_hash(payload, length=64)[:12]
    archive = (
        path.parent
        / "publication-history"
        / f"{path.stem}-v{version}-{fingerprint}.json"
    )
    if archive.is_file():
        if read_json(archive) != payload:
            raise ResultConflictError(
                f"{archive} already holds different publication history"
            )
        return archive
    return write_json(archive, payload)


def _run_from_payload(payload: Mapping[str, object]) -> RunDefinition:
    """Rebuild a run manifest from its JSON form."""
    algorithm = payload["algorithm"]
    environment = payload["environment"]
    profile = payload["execution_profile"]

    return RunDefinition(
        run_id=payload["run_id"],
        run_fingerprint=payload["run_fingerprint"],
        protocol_id=payload["protocol_id"],
        cohort_id=CohortId(payload["cohort_id"]),
        pair_manifest_hash=payload["pair_manifest_hash"],
        algorithm=AlgorithmDescriptor(
            algorithm_id=algorithm["algorithm_id"],
            display_name=algorithm["display_name"],
            adapter_id=algorithm["adapter_id"],
            adapter_version=algorithm["adapter_version"],
            adapter_contract_version=algorithm["adapter_contract_version"],
            implementation_version=algorithm["implementation_version"],
            score_direction=ScoreDirection(algorithm["score_direction"]),
            deterministic=algorithm["deterministic"],
            capabilities=tuple(algorithm["capabilities"]),
            metadata=algorithm["metadata"],
        ),
        algorithm_fingerprint=payload["algorithm_fingerprint"],
        environment=EnvironmentReport(
            status=EnvironmentStatus(environment["status"]),
            implementation_version=environment["implementation_version"],
            runtime=environment["runtime"],
            dependencies=environment["dependencies"],
            message=environment["message"],
        ),
        environment_fingerprint=payload["environment_fingerprint"],
        execution_profile=ExecutionProfile(
            profile_id=profile["profile_id"],
            preparer_id=profile["preparer_id"],
            timeout_seconds=profile["timeout_seconds"],
            deterministic_seed=profile["deterministic_seed"],
            parameters=profile["parameters"],
        ),
        execution_profile_hash=payload["execution_profile_hash"],
        replicate_index=payload["replicate_index"],
        created_utc=payload["created_utc"],
    )
