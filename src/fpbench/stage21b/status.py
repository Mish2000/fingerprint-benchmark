"""Operational inspection that never selects or prints a raw score value."""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from fpbench.core.json_io import publish_json
from fpbench.core.serialization import stable_hash
from fpbench.stage21b.errors import Stage21BIntegrityError, Stage21BStoreConflict
from fpbench.stage21b.integrity import verify_sealed_run_directory
from fpbench.stage21b.models import (
    FrozenRunSpec,
    PlannedPair,
    TerminalOutcome,
    ordered_pair_plan_fingerprint,
)


def status_reports(
    workspace: Path, *, algorithm_id: str | None = None
) -> list[dict[str, Any]]:
    root = Path(workspace).resolve() / "stage21b"
    pattern = f"{algorithm_id}/*/run-spec.json" if algorithm_id else "*/*/run-spec.json"
    reports: list[dict[str, Any]] = []
    for spec_path in sorted(root.glob(pattern)):
        try:
            reports.append(_status(spec_path.parent))
        except Exception as exc:
            reports.append(
                {
                    "algorithm_id": spec_path.parent.parent.name,
                    "run_id": spec_path.parent.name,
                    "state": "INVALID/MISMATCHED",
                    "error": f"{type(exc).__name__}: {exc}",
                    "raw_scores_displayed": False,
                }
            )
    return reports


def inspect_run_directory(run_directory: Path) -> dict[str, Any]:
    directory = Path(run_directory).resolve()
    spec = FrozenRunSpec.from_dict(_json(directory / "run-spec.json"))
    database = directory / "checkpoint.sqlite3"
    with _read_connection(database) as connection:
        check = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if check != "ok":
            raise Stage21BIntegrityError(f"checkpoint database is corrupt: {check}")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise Stage21BIntegrityError("checkpoint foreign-key binding is invalid")
        metadata = {
            row["key"]: row["value"]
            for row in connection.execute("SELECT key,value FROM metadata")
        }
        planned_pairs, outcomes = _validate_checkpoint_records(connection, spec)
        planned = len(planned_pairs)
        terminal = len(outcomes)
        distinct_pairs = int(
            connection.execute(
                "SELECT COUNT(DISTINCT pair_id) FROM terminal_outcomes"
            ).fetchone()[0]
        )
        distinct_ordinals = int(
            connection.execute(
                "SELECT COUNT(DISTINCT ordinal) FROM terminal_outcomes"
            ).fetchone()[0]
        )
        unknown = int(
            connection.execute(
                """
                SELECT COUNT(*) FROM terminal_outcomes o
                LEFT JOIN planned_pairs p ON p.pair_id=o.pair_id
                WHERE p.pair_id IS NULL
                """
            ).fetchone()[0]
        )
        status_counts = {
            row["status"]: int(row["n"])
            for row in connection.execute(
                "SELECT status,COUNT(*) AS n FROM terminal_outcomes GROUP BY status"
            )
        }
        open_attempts = int(
            connection.execute(
                "SELECT COUNT(*) FROM attempts WHERE classification='IN_PROGRESS'"
            ).fetchone()[0]
        )
    gates = {
        "sqlite_integrity_ok": check == "ok",
        "database_bound_to_run": metadata.get("run_spec_fingerprint")
        == spec.run_spec_fingerprint,
        "pair_manifest_bound_to_run": metadata.get("pair_manifest_hash")
        == spec.pair_manifest_hash,
        "planned_pair_closure_bound_to_run": metadata.get("plan_hash")
        == spec.planned_pair_input_fingerprint,
        "planned_count_matches_spec": planned == spec.expected_attempts,
        "terminal_count_not_above_plan": terminal <= planned,
        "no_duplicate_terminal_pair_ids": terminal == distinct_pairs,
        "no_duplicate_terminal_ordinals": terminal == distinct_ordinals,
        "no_unknown_terminal_pairs": unknown == 0,
        "terminal_status_partition_valid": sum(status_counts.values()) == terminal,
    }
    if not all(gates.values()):
        raise Stage21BIntegrityError(
            "run integrity failed: "
            + ", ".join(key for key, value in gates.items() if not value)
        )
    sealed = (directory / "result-set.json").is_file()
    sealed_report = (
        verify_sealed_run_directory(directory, require_production_shape=False)
        if sealed
        else None
    )
    return {
        "stage": "21B",
        "algorithm_id": spec.algorithm_id,
        "run_id": spec.run_id,
        "run_spec_fingerprint": spec.run_spec_fingerprint,
        "state": (
            "SUPERSEDED"
            if (directory / "supersession.json").is_file()
            else "SEALED"
            if sealed
            else "EMPTY/NEW"
            if terminal == 0
            else "VALID INCOMPLETE"
        ),
        "planned_count": planned,
        "completed_count": terminal,
        "pending_count": planned - terminal,
        "score_bearing_count": status_counts.get("SUCCESS", 0),
        "algorithm_failure_count": status_counts.get("ALGORITHM_FAILURE", 0),
        "in_progress_infrastructure_attempts": open_attempts,
        "seal_status": "SEALED" if sealed else "UNSEALED",
        "result_set_fingerprint": (
            sealed_report["result_set_fingerprint"] if sealed_report else None
        ),
        "gates": gates,
        "integrity_pass": True,
        "raw_scores_displayed": False,
    }


def find_run_directory(
    workspace: Path, *, algorithm_id: str, run_id: str | None = None
) -> Path:
    directory = Path(workspace).resolve() / "stage21b" / algorithm_id
    if run_id:
        target = directory / run_id
        if not (target / "run-spec.json").is_file():
            raise Stage21BIntegrityError(f"Stage 21B run not found: {target}")
        return target
    candidates = [
        path.parent
        for path in directory.glob("*/run-spec.json")
        if not (path.parent / "supersession.json").is_file()
    ]
    if len(candidates) != 1:
        raise Stage21BIntegrityError(
            f"{algorithm_id}: specify --run-id; found {len(candidates)} active runs"
        )
    return candidates[0]


def record_supersession(
    run_directory: Path, *, reason: str, superseded_by_run_id: str
) -> Path:
    directory = Path(run_directory).resolve()
    spec = FrozenRunSpec.from_dict(_json(directory / "run-spec.json"))
    text = " ".join(str(reason).split())
    if not text:
        raise ValueError("supersession reason must not be empty")
    if superseded_by_run_id == spec.run_id:
        raise ValueError("a run cannot supersede itself")
    path = directory / "supersession.json"
    document = {
        "schema_version": "1",
        "stage": "21B",
        "status": "superseded",
        "run_id": spec.run_id,
        "run_spec_fingerprint": spec.run_spec_fingerprint,
        "superseded_reason": text,
        "superseded_by_run_id": superseded_by_run_id,
        "recorded_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    try:
        publish_json(path, document)
    except Exception as exc:
        raise Stage21BStoreConflict(f"cannot record supersession: {exc}") from exc
    return path


def _status(directory: Path) -> dict[str, Any]:
    spec = FrozenRunSpec.from_dict(_json(directory / "run-spec.json"))
    with _read_connection(directory / "checkpoint.sqlite3") as connection:
        counts = {
            row["status"]: int(row["n"])
            for row in connection.execute(
                "SELECT status,COUNT(*) AS n FROM terminal_outcomes GROUP BY status"
            )
        }
        completed = sum(counts.values())
        attempts = int(connection.execute("SELECT COUNT(*) FROM attempts").fetchone()[0])
        infra = int(
            connection.execute(
                "SELECT COUNT(*) FROM attempts WHERE classification LIKE 'INFRASTRUCTURE_%'"
            ).fetchone()[0]
        )
        infrastructure_failures = {
            str(row["failure_code"]): int(row["n"])
            for row in connection.execute(
                """
                SELECT failure_code,COUNT(*) AS n FROM attempts
                 WHERE classification LIKE 'INFRASTRUCTURE_%'
              GROUP BY failure_code ORDER BY failure_code
                """
            )
        }
        failures = {
            str(row["failure_code"]): int(row["n"])
            for row in connection.execute(
                """
                SELECT failure_code,COUNT(*) AS n FROM attempts
                WHERE classification='ALGORITHM_FAILURE'
                GROUP BY failure_code ORDER BY failure_code
                """
            )
        }
        elapsed = float(
            connection.execute(
                "SELECT COALESCE(SUM(wall_time_ms),0) FROM terminal_outcomes"
            ).fetchone()[0]
        )
        last = connection.execute(
            "SELECT MAX(finished_utc) FROM attempts WHERE finished_utc IS NOT NULL"
        ).fetchone()[0]
    sealed = (directory / "result-set.json").is_file()
    superseded = (directory / "supersession.json").is_file()
    return {
        "algorithm_id": spec.algorithm_id,
        "run_id": spec.run_id,
        "result_set_id": spec.result_set_id,
        "state": (
            "SUPERSEDED"
            if superseded
            else "SEALED"
            if sealed
            else "EMPTY/NEW"
            if completed == 0
            else "VALID INCOMPLETE"
        ),
        "planned_count": spec.expected_attempts,
        "completed_count": completed,
        "pending_count": spec.expected_attempts - completed,
        "score_bearing_count": counts.get("SUCCESS", 0),
        "algorithm_failure_count": counts.get("ALGORITHM_FAILURE", 0),
        "attempt_records": attempts,
        "infrastructure_events": infra,
        "infrastructure_classifications": infrastructure_failures,
        "failure_classifications": failures,
        "elapsed_adapter_wall_ms": elapsed,
        "adapter_busy_throughput_terminal_per_second": (
            completed / (elapsed / 1000.0) if completed and elapsed > 0 else None
        ),
        "throughput_definition": (
            "terminal outcomes divided by summed adapter invocation wall time"
        ),
        "last_checkpoint": last,
        "seal_status": "SEALED" if sealed else "UNSEALED",
        "raw_scores_displayed": False,
    }


@contextmanager
def _read_connection(path: Path) -> Iterator[sqlite3.Connection]:
    if not Path(path).is_file():
        raise Stage21BIntegrityError(f"checkpoint database is missing: {path}")
    connection = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    try:
        yield connection
    finally:
        connection.close()


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Stage21BIntegrityError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise Stage21BIntegrityError(f"{path}: expected a JSON object")
    return value


def _validate_checkpoint_records(
    connection: sqlite3.Connection, spec: FrozenRunSpec
) -> tuple[tuple[PlannedPair, ...], tuple[TerminalOutcome, ...]]:
    """Read-only validation used by ``stage21b-integrity`` on incomplete runs."""
    planned_rows = connection.execute(
        "SELECT ordinal,pair_id,payload_json FROM planned_pairs ORDER BY ordinal"
    ).fetchall()
    try:
        planned = tuple(
            PlannedPair.from_dict(json.loads(str(row["payload_json"])))
            for row in planned_rows
        )
    except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise Stage21BIntegrityError(f"planned-pair checkpoint payload is invalid: {exc}") from exc
    if [pair.ordinal for pair in planned] != list(range(len(planned))):
        raise Stage21BIntegrityError("planned-pair ordinals are not the frozen 0..n order")
    if any(
        row["ordinal"] != pair.ordinal
        or row["pair_id"] != pair.pair_id
        or str(row["payload_json"]) != _canonical_json(pair.to_dict())
        for row, pair in zip(planned_rows, planned, strict=True)
    ):
        raise Stage21BIntegrityError("planned-pair index and canonical payload disagree")
    if len(planned) != spec.expected_attempts:
        raise Stage21BIntegrityError("planned-pair count differs from the run specification")
    if stable_hash([pair.pair_id for pair in planned], length=64) != spec.pair_ids_sha256:
        raise Stage21BIntegrityError("planned pair IDs/order differ from the run specification")
    if ordered_pair_plan_fingerprint(planned) != spec.planned_pair_input_fingerprint:
        raise Stage21BIntegrityError("planned pair/input closure differs from the run specification")

    outcome_rows = connection.execute(
        "SELECT * FROM terminal_outcomes ORDER BY ordinal"
    ).fetchall()
    outcomes: list[TerminalOutcome] = []
    for row in outcome_rows:
        pair_id = str(row["pair_id"])
        try:
            outcome = TerminalOutcome.from_dict(json.loads(str(row["payload_json"])))
        except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            raise Stage21BIntegrityError(
                f"{pair_id}: terminal payload is invalid: {exc}"
            ) from exc
        if str(row["payload_json"]) != _canonical_json(outcome.to_dict()):
            raise Stage21BIntegrityError(f"{pair_id}: terminal payload is not canonical")
        bindings = (
            outcome.run_id == spec.run_id,
            outcome.run_spec_fingerprint == spec.run_spec_fingerprint,
            outcome.result_set_id == spec.result_set_id,
            outcome.algorithm_id == spec.algorithm_id,
            outcome.adapter_id == spec.adapter_id,
            outcome.adapter_descriptor_fingerprint
            == spec.adapter_descriptor_fingerprint,
            outcome.runtime_identity_fingerprint == spec.runtime_identity_fingerprint,
        )
        if not all(bindings):
            raise Stage21BIntegrityError(f"{pair_id}: terminal payload belongs to another run")
        if not 0 <= outcome.pair.ordinal < len(planned) or planned[outcome.pair.ordinal] != outcome.pair:
            raise Stage21BIntegrityError(f"{pair_id}: terminal pair differs from the frozen plan")
        if (
            pair_id != outcome.pair.pair_id
            or int(row["ordinal"]) != outcome.pair.ordinal
            or str(row["status"]) != outcome.status.value
            or float(row["wall_time_ms"]).hex() != outcome.wall_time_ms.hex()
            or str(row["outcome_hash"]) != outcome.outcome_hash
        ):
            raise Stage21BIntegrityError(
                f"{pair_id}: terminal index and canonical payload disagree"
            )
        attempt = connection.execute(
            """
            SELECT * FROM attempts
             WHERE pair_id=? AND classification IN ('SUCCESS','ALGORITHM_FAILURE')
            """,
            (pair_id,),
        ).fetchall()
        if len(attempt) != 1:
            raise Stage21BIntegrityError(
                f"{pair_id}: terminal outcome does not have exactly one terminal attempt"
            )
        journal = attempt[0]
        if (
            int(journal["attempt_number"]) != outcome.attempt
            or journal["classification"] != outcome.status.value
            or journal["started_utc"] != outcome.started_utc
            or journal["finished_utc"] != outcome.finished_utc
            or journal["failure_code"] != outcome.failure_code
            or journal["failure_stage"] != outcome.failure_stage
        ):
            raise Stage21BIntegrityError(
                f"{pair_id}: terminal outcome and attempt provenance disagree"
            )
        outcomes.append(outcome)
    terminal_attempts = int(
        connection.execute(
            "SELECT COUNT(*) FROM attempts WHERE classification IN ('SUCCESS','ALGORITHM_FAILURE')"
        ).fetchone()[0]
    )
    if terminal_attempts != len(outcomes):
        raise Stage21BIntegrityError("terminal attempt exists without a canonical outcome")
    return planned, tuple(outcomes)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
