"""Transactional checkpoint journal and immutable canonical Stage 21B result sets."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import sqlite3
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

import pyarrow as pa
import pyarrow.parquet as pq

from fpbench.core.json_io import publish_json
from fpbench.core.serialization import stable_hash
from fpbench.stage21b.errors import (
    Stage21BIntegrityError,
    Stage21BSealedError,
    Stage21BStoreConflict,
)
from fpbench.stage21b.models import (
    FrozenRunSpec,
    PlannedPair,
    Stage21BOutcomeStatus,
    TerminalOutcome,
    ordered_pair_plan_fingerprint,
)
from fpbench.storage.atomic_parquet import publish_table

_DB_SCHEMA_VERSION = "1"


class Stage21BResultStore:
    """One algorithm's append-safe run, addressed by its frozen run spec."""

    def __init__(
        self,
        *,
        workspace: Path,
        spec: FrozenRunSpec,
        planned_pairs: Iterable[PlannedPair],
    ) -> None:
        self.workspace = Path(workspace).resolve()
        self.spec = spec
        self.planned_pairs = tuple(planned_pairs)
        self.run_dir = (
            self.workspace / "stage21b" / spec.algorithm_id / spec.run_id
        )
        self.spec_path = self.run_dir / "run-spec.json"
        self.database_path = self.run_dir / "checkpoint.sqlite3"
        self.outcomes_path = self.run_dir / "outcomes.parquet"
        self.attempts_path = self.run_dir / "attempts.parquet"
        self.seal_path = self.run_dir / "result-set.json"
        self.supersession_path = self.run_dir / "supersession.json"
        self._plan_hash = ordered_pair_plan_fingerprint(self.planned_pairs)
        self._require_plan_shape()
        self._initialise()

    # --------------------------------------------------------------- lifecycle

    @property
    def is_sealed(self) -> bool:
        return self.seal_path.is_file()

    @property
    def is_superseded(self) -> bool:
        return self.supersession_path.is_file()

    def state(self) -> str:
        if self.is_superseded:
            return "SUPERSEDED"
        if self.is_sealed:
            return "SEALED"
        completed = self.terminal_count()
        return "EMPTY_NEW" if completed == 0 else "VALID_INCOMPLETE"

    def _initialise(self) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        if self.spec_path.is_file():
            stored = FrozenRunSpec.from_dict(_read_json(self.spec_path))
            if (
                stored.run_spec_fingerprint != self.spec.run_spec_fingerprint
                or stored.semantic_payload() != self.spec.semantic_payload()
            ):
                raise Stage21BStoreConflict(
                    f"{self.spec.run_id} already holds a different frozen run spec"
                )
            # created_utc is deliberately outside the logical identity.  A
            # resumed preflight constructs the same semantic spec at a later
            # instant; the timestamp first claimed on disk remains authoritative.
            self.spec = stored
        else:
            try:
                publish_json(self.spec_path, self.spec.to_dict())
            except Exception as exc:
                if not self.spec_path.is_file():
                    raise Stage21BStoreConflict(
                        f"cannot publish immutable run spec: {exc}"
                    ) from exc
                stored = FrozenRunSpec.from_dict(_read_json(self.spec_path))
                if stored.to_dict() != self.spec.to_dict():
                    raise Stage21BStoreConflict(
                        "another writer published a different run spec"
                    ) from exc

        created = not self.database_path.exists()
        if self.is_sealed:
            if created:
                raise Stage21BStoreConflict("sealed run has no checkpoint database")
            with self._connect(write=False) as connection:
                self._verify_database_binding(connection)
            self.verify_seal()
            return

        with self._connect(write=True) as connection:
            self._create_schema(connection)
            if created:
                self._write_initial_state(connection)
            self._verify_database_binding(connection)

        # A crash can occur after one or both immutable parquet exports were
        # published but before the JSON seal.  Never execute over those files;
        # complete the same deterministic seal when the journal is complete.
        if self.outcomes_path.exists() or self.attempts_path.exists():
            if self.terminal_count() != self.spec.expected_attempts:
                raise Stage21BStoreConflict(
                    "canonical result files exist for an incomplete run"
                )
            self.seal()

    @contextmanager
    def _connect(self, *, write: bool) -> Iterator[sqlite3.Connection]:
        if write and (self.is_sealed or self.is_superseded):
            raise Stage21BSealedError(
                f"run {self.spec.run_id} is {self.state()} and cannot be changed"
            )
        connection = sqlite3.connect(self.database_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        if write:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
        else:
            connection.execute("PRAGMA query_only=ON")
        try:
            yield connection
        finally:
            connection.close()

    @staticmethod
    def _create_schema(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS planned_pairs (
                ordinal INTEGER NOT NULL UNIQUE,
                pair_id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS attempts (
                attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
                pair_id TEXT NOT NULL REFERENCES planned_pairs(pair_id),
                attempt_number INTEGER NOT NULL,
                started_utc TEXT NOT NULL,
                finished_utc TEXT,
                classification TEXT NOT NULL,
                failure_code TEXT,
                failure_stage TEXT,
                failure_message TEXT,
                UNIQUE(pair_id, attempt_number)
            );
            CREATE TABLE IF NOT EXISTS terminal_outcomes (
                pair_id TEXT PRIMARY KEY REFERENCES planned_pairs(pair_id),
                ordinal INTEGER NOT NULL UNIQUE,
                status TEXT NOT NULL,
                wall_time_ms REAL NOT NULL,
                outcome_hash TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS attempts_pair_id ON attempts(pair_id);
            """
        )

    def _write_initial_state(self, connection: sqlite3.Connection) -> None:
        values = {
            "db_schema_version": _DB_SCHEMA_VERSION,
            "run_id": self.spec.run_id,
            "run_spec_fingerprint": self.spec.run_spec_fingerprint,
            "pair_manifest_hash": self.spec.pair_manifest_hash,
            "pair_count": str(self.spec.pair_count),
            "plan_hash": self._plan_hash,
            "created_utc": _utc_now(),
        }
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.executemany(
                "INSERT INTO metadata(key,value) VALUES (?,?)", values.items()
            )
            connection.executemany(
                "INSERT INTO planned_pairs(ordinal,pair_id,payload_json) VALUES (?,?,?)",
                (
                    (
                        pair.ordinal,
                        pair.pair_id,
                        _canonical_json(pair.to_dict()),
                    )
                    for pair in self.planned_pairs
                ),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    def _verify_database_binding(self, connection: sqlite3.Connection) -> None:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise Stage21BIntegrityError(f"checkpoint database is corrupt: {integrity}")
        foreign_key_issue = connection.execute("PRAGMA foreign_key_check").fetchone()
        if foreign_key_issue is not None:
            raise Stage21BIntegrityError(
                "checkpoint database has a broken pair/attempt foreign-key binding"
            )
        metadata = {
            row["key"]: row["value"]
            for row in connection.execute("SELECT key,value FROM metadata")
        }
        expected = {
            "db_schema_version": _DB_SCHEMA_VERSION,
            "run_id": self.spec.run_id,
            "run_spec_fingerprint": self.spec.run_spec_fingerprint,
            "pair_manifest_hash": self.spec.pair_manifest_hash,
            "pair_count": str(self.spec.pair_count),
            "plan_hash": self._plan_hash,
        }
        mismatches = {
            key: (metadata.get(key), value)
            for key, value in expected.items()
            if metadata.get(key) != value
        }
        if mismatches:
            raise Stage21BStoreConflict(
                f"checkpoint belongs to a different frozen run: {mismatches}"
            )
        rows = connection.execute(
            "SELECT ordinal,pair_id,payload_json FROM planned_pairs ORDER BY ordinal"
        ).fetchall()
        if len(rows) != len(self.planned_pairs):
            raise Stage21BIntegrityError("checkpoint planned-pair count changed")
        for stored, expected_pair in zip(rows, self.planned_pairs, strict=True):
            if (
                stored["ordinal"] != expected_pair.ordinal
                or stored["pair_id"] != expected_pair.pair_id
                or stored["payload_json"] != _canonical_json(expected_pair.to_dict())
            ):
                raise Stage21BIntegrityError(
                    f"checkpoint plan differs at ordinal {expected_pair.ordinal}"
                )
        self._verify_existing_records(connection)

    def _verify_existing_records(self, connection: sqlite3.Connection) -> None:
        """Validate every durable outcome before resume can skip it.

        A row count is not enough for resume: an existing terminal row is the
        reason the matcher will *not* be invoked again.  Therefore its canonical
        payload, lossless score identity, frozen pair binding, journal attempt
        and denormalised index columns are all checked here on every open.
        """
        allowed_attempt_states = {
            "IN_PROGRESS",
            "INFRASTRUCTURE_FAILURE",
            "INFRASTRUCTURE_INTERRUPTED",
            Stage21BOutcomeStatus.SUCCESS.value,
            Stage21BOutcomeStatus.ALGORITHM_FAILURE.value,
        }
        attempts_by_pair: dict[str, list[sqlite3.Row]] = {}
        terminal_attempt_rows: dict[str, sqlite3.Row] = {}
        open_attempts = 0
        for row in connection.execute(
            "SELECT * FROM attempts ORDER BY pair_id,attempt_number"
        ):
            pair_id = str(row["pair_id"])
            state = str(row["classification"])
            if state not in allowed_attempt_states:
                raise Stage21BIntegrityError(
                    f"{pair_id}: checkpoint carries unknown attempt state {state!r}"
                )
            attempts_by_pair.setdefault(pair_id, []).append(row)
            if state == "IN_PROGRESS":
                open_attempts += 1
                if row["finished_utc"] is not None:
                    raise Stage21BIntegrityError(
                        f"{pair_id}: in-progress attempt is already finished"
                    )
            else:
                if row["finished_utc"] is None:
                    raise Stage21BIntegrityError(
                        f"{pair_id}: closed attempt has no finish timestamp"
                    )
            if state.startswith("INFRASTRUCTURE_") and (
                not row["failure_code"] or not row["failure_stage"]
            ):
                raise Stage21BIntegrityError(
                    f"{pair_id}: infrastructure attempt has no classification detail"
                )
            if state in {
                Stage21BOutcomeStatus.SUCCESS.value,
                Stage21BOutcomeStatus.ALGORITHM_FAILURE.value,
            }:
                if pair_id in terminal_attempt_rows:
                    raise Stage21BIntegrityError(
                        f"{pair_id}: more than one terminal attempt is journalled"
                    )
                terminal_attempt_rows[pair_id] = row

        if open_attempts > 1:
            raise Stage21BIntegrityError(
                "sequential Stage 21B checkpoint has more than one in-progress attempt"
            )
        for pair_id, rows in attempts_by_pair.items():
            numbers = [int(row["attempt_number"]) for row in rows]
            if numbers != list(range(1, len(rows) + 1)):
                raise Stage21BIntegrityError(
                    f"{pair_id}: attempt numbers are not the canonical 1..n sequence"
                )
            terminal_positions = [
                index
                for index, row in enumerate(rows)
                if row["classification"]
                in {
                    Stage21BOutcomeStatus.SUCCESS.value,
                    Stage21BOutcomeStatus.ALGORITHM_FAILURE.value,
                }
            ]
            if terminal_positions and terminal_positions != [len(rows) - 1]:
                raise Stage21BIntegrityError(
                    f"{pair_id}: an attempt exists after its terminal biometric outcome"
                )

        seen_outcomes: set[str] = set()
        for row in connection.execute(
            "SELECT * FROM terminal_outcomes ORDER BY ordinal"
        ):
            pair_id = str(row["pair_id"])
            try:
                payload_value = json.loads(str(row["payload_json"]))
                outcome = TerminalOutcome.from_dict(payload_value)
            except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
                raise Stage21BIntegrityError(
                    f"{pair_id}: existing terminal payload is invalid: {exc}"
                ) from exc
            if str(row["payload_json"]) != _canonical_json(outcome.to_dict()):
                raise Stage21BIntegrityError(
                    f"{pair_id}: existing terminal payload is not canonical"
                )
            self._require_outcome_binding(outcome)
            if pair_id != outcome.pair.pair_id or int(row["ordinal"]) != outcome.pair.ordinal:
                raise Stage21BIntegrityError(
                    f"{pair_id}: terminal index and canonical payload disagree"
                )
            if str(row["status"]) != outcome.status.value:
                raise Stage21BIntegrityError(
                    f"{pair_id}: terminal status and canonical payload disagree"
                )
            if float(row["wall_time_ms"]).hex() != outcome.wall_time_ms.hex():
                raise Stage21BIntegrityError(
                    f"{pair_id}: terminal timing and canonical payload disagree"
                )
            if str(row["outcome_hash"]) != outcome.outcome_hash:
                raise Stage21BIntegrityError(
                    f"{pair_id}: existing terminal outcome hash is invalid"
                )
            attempt = terminal_attempt_rows.get(pair_id)
            if attempt is None:
                raise Stage21BIntegrityError(
                    f"{pair_id}: terminal outcome has no terminal attempt record"
                )
            if (
                int(attempt["attempt_number"]) != outcome.attempt
                or str(attempt["classification"]) != outcome.status.value
                or str(attempt["started_utc"]) != outcome.started_utc
                or str(attempt["finished_utc"]) != outcome.finished_utc
                or attempt["failure_code"] != outcome.failure_code
                or attempt["failure_stage"] != outcome.failure_stage
            ):
                raise Stage21BIntegrityError(
                    f"{pair_id}: terminal outcome and attempt provenance disagree"
                )
            seen_outcomes.add(pair_id)
        orphaned = sorted(set(terminal_attempt_rows) - seen_outcomes)
        if orphaned:
            raise Stage21BIntegrityError(
                "terminal attempt(s) have no canonical outcome: " + ", ".join(orphaned[:3])
            )

    def _require_outcome_binding(self, outcome: TerminalOutcome) -> None:
        expected_scalars = {
            "run_id": self.spec.run_id,
            "run_spec_fingerprint": self.spec.run_spec_fingerprint,
            "result_set_id": self.spec.result_set_id,
            "algorithm_id": self.spec.algorithm_id,
            "adapter_id": self.spec.adapter_id,
            "adapter_descriptor_fingerprint": self.spec.adapter_descriptor_fingerprint,
            "runtime_identity_fingerprint": self.spec.runtime_identity_fingerprint,
        }
        different = [
            name
            for name, expected in expected_scalars.items()
            if getattr(outcome, name) != expected
        ]
        if different:
            raise Stage21BStoreConflict(
                "terminal outcome belongs to another frozen run: " + ", ".join(different)
            )
        ordinal = outcome.pair.ordinal
        if not 0 <= ordinal < len(self.planned_pairs):
            raise Stage21BStoreConflict("terminal outcome has an unknown pair ordinal")
        if self.planned_pairs[ordinal] != outcome.pair:
            raise Stage21BStoreConflict(
                "terminal outcome does not match the frozen pair plan"
            )

    # --------------------------------------------------------------- attempts

    def recover_interrupted_attempts(self) -> int:
        """Close process-abandoned attempt rows without creating outcomes."""
        self._require_accepting_outcomes()
        with self._connect(write=True) as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE attempts
                   SET finished_utc=?, classification='INFRASTRUCTURE_INTERRUPTED',
                       failure_code='external_interruption',
                       failure_stage='infrastructure',
                       failure_message='the process ended before a terminal outcome was recorded'
                 WHERE classification='IN_PROGRESS'
                """,
                (_utc_now(),),
            )
            connection.commit()
            return int(cursor.rowcount)

    def begin_attempt(self, pair_id: str, *, started_utc: str) -> tuple[int, int]:
        self._require_accepting_outcomes()
        with self._connect(write=True) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                planned = connection.execute(
                    "SELECT 1 FROM planned_pairs WHERE pair_id=?", (pair_id,)
                ).fetchone()
                if planned is None:
                    raise Stage21BStoreConflict(f"unknown pair {pair_id!r}")
                if connection.execute(
                    "SELECT 1 FROM terminal_outcomes WHERE pair_id=?", (pair_id,)
                ).fetchone():
                    raise Stage21BStoreConflict(
                        f"pair {pair_id} already has its one terminal outcome"
                    )
                open_attempt = connection.execute(
                    "SELECT 1 FROM attempts WHERE pair_id=? AND classification='IN_PROGRESS'",
                    (pair_id,),
                ).fetchone()
                if open_attempt:
                    raise Stage21BIntegrityError(
                        f"pair {pair_id} has an unrecovered interrupted attempt"
                    )
                number = int(
                    connection.execute(
                        "SELECT COALESCE(MAX(attempt_number),0)+1 FROM attempts WHERE pair_id=?",
                        (pair_id,),
                    ).fetchone()[0]
                )
                cursor = connection.execute(
                    """
                    INSERT INTO attempts(pair_id,attempt_number,started_utc,classification)
                    VALUES (?,?,?,'IN_PROGRESS')
                    """,
                    (pair_id, number, started_utc),
                )
                connection.commit()
                return int(cursor.lastrowid), number
            except Exception:
                connection.rollback()
                raise

    def record_infrastructure_failure(
        self,
        attempt_id: int,
        *,
        finished_utc: str,
        code: str,
        stage: str,
        message: str,
    ) -> None:
        self._require_accepting_outcomes()
        with self._connect(write=True) as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE attempts
                   SET finished_utc=?, classification='INFRASTRUCTURE_FAILURE',
                       failure_code=?, failure_stage=?, failure_message=?
                 WHERE attempt_id=? AND classification='IN_PROGRESS'
                """,
                (finished_utc, code, stage, _short(message), attempt_id),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                raise Stage21BIntegrityError("attempt is absent or already terminal")
            connection.commit()

    def record_terminal(self, attempt_id: int, outcome: TerminalOutcome) -> None:
        self._require_accepting_outcomes()
        self._require_outcome_binding(outcome)
        payload = _canonical_json(outcome.to_dict())
        with self._connect(write=True) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                attempt = connection.execute(
                    "SELECT pair_id,attempt_number,classification FROM attempts WHERE attempt_id=?",
                    (attempt_id,),
                ).fetchone()
                if attempt is None or attempt["classification"] != "IN_PROGRESS":
                    raise Stage21BIntegrityError("attempt is absent or already terminal")
                if attempt["pair_id"] != outcome.pair.pair_id:
                    raise Stage21BIntegrityError("attempt and outcome name different pairs")
                if attempt["attempt_number"] != outcome.attempt:
                    raise Stage21BIntegrityError("attempt number changed")
                connection.execute(
                    """
                    INSERT INTO terminal_outcomes(
                        pair_id,ordinal,status,wall_time_ms,outcome_hash,payload_json
                    ) VALUES (?,?,?,?,?,?)
                    """,
                    (
                        outcome.pair.pair_id,
                        outcome.pair.ordinal,
                        outcome.status.value,
                        outcome.wall_time_ms,
                        outcome.outcome_hash,
                        payload,
                    ),
                )
                connection.execute(
                    """
                    UPDATE attempts
                       SET finished_utc=?, classification=?, failure_code=?,
                           failure_stage=?, failure_message=?
                     WHERE attempt_id=? AND classification='IN_PROGRESS'
                    """,
                    (
                        outcome.finished_utc,
                        outcome.status.value,
                        outcome.failure_code,
                        outcome.failure_stage,
                        _short(outcome.failure_message or "") or None,
                        attempt_id,
                    ),
                )
                connection.commit()
            except sqlite3.IntegrityError as exc:
                connection.rollback()
                raise Stage21BStoreConflict(
                    f"duplicate canonical outcome rejected for {outcome.pair.pair_id}"
                ) from exc
            except Exception:
                connection.rollback()
                raise

    # --------------------------------------------------------------- reading

    def pending_pairs(self) -> tuple[PlannedPair, ...]:
        with self._connect(write=False) as connection:
            rows = connection.execute(
                """
                SELECT p.payload_json
                  FROM planned_pairs p
             LEFT JOIN terminal_outcomes o ON o.pair_id=p.pair_id
                 WHERE o.pair_id IS NULL
              ORDER BY p.ordinal
                """
            ).fetchall()
        return tuple(PlannedPair.from_dict(json.loads(row[0])) for row in rows)

    def outcomes(self) -> tuple[TerminalOutcome, ...]:
        with self._connect(write=False) as connection:
            rows = connection.execute(
                "SELECT payload_json FROM terminal_outcomes ORDER BY ordinal"
            ).fetchall()
        return tuple(TerminalOutcome.from_dict(json.loads(row[0])) for row in rows)

    def terminal_count(self) -> int:
        with self._connect(write=False) as connection:
            return int(connection.execute("SELECT COUNT(*) FROM terminal_outcomes").fetchone()[0])

    def status_report(self) -> dict[str, Any]:
        with self._connect(write=False) as connection:
            total = int(connection.execute("SELECT COUNT(*) FROM terminal_outcomes").fetchone()[0])
            counts = {
                row["status"]: int(row["n"])
                for row in connection.execute(
                    "SELECT status,COUNT(*) AS n FROM terminal_outcomes GROUP BY status"
                )
            }
            attempts = int(connection.execute("SELECT COUNT(*) FROM attempts").fetchone()[0])
            infra = int(
                connection.execute(
                    "SELECT COUNT(*) FROM attempts WHERE classification LIKE 'INFRASTRUCTURE_%'"
                ).fetchone()[0]
            )
            infrastructure_counts = {
                str(row["failure_code"]): int(row["n"])
                for row in connection.execute(
                    """
                    SELECT failure_code,COUNT(*) AS n FROM attempts
                     WHERE classification LIKE 'INFRASTRUCTURE_%'
                  GROUP BY failure_code ORDER BY failure_code
                    """
                )
            }
            failure_counts = {
                str(row["failure_code"]): int(row["n"])
                for row in connection.execute(
                    """
                    SELECT failure_code,COUNT(*) AS n FROM attempts
                     WHERE classification='ALGORITHM_FAILURE'
                  GROUP BY failure_code ORDER BY failure_code
                    """
                )
            }
            last = connection.execute(
                "SELECT MAX(finished_utc) FROM attempts WHERE finished_utc IS NOT NULL"
            ).fetchone()[0]
            elapsed = float(
                connection.execute(
                    "SELECT COALESCE(SUM(wall_time_ms),0) FROM terminal_outcomes"
                ).fetchone()[0]
            )
        return {
            "algorithm_id": self.spec.algorithm_id,
            "run_id": self.spec.run_id,
            "result_set_id": self.spec.result_set_id,
            "state": self.state(),
            "planned_count": self.spec.expected_attempts,
            "completed_count": total,
            "pending_count": self.spec.expected_attempts - total,
            "score_bearing_count": counts.get(Stage21BOutcomeStatus.SUCCESS.value, 0),
            "algorithm_failure_count": counts.get(
                Stage21BOutcomeStatus.ALGORITHM_FAILURE.value, 0
            ),
            "attempt_records": attempts,
            "infrastructure_events": infra,
            "infrastructure_classifications": infrastructure_counts,
            "failure_classifications": failure_counts,
            "elapsed_adapter_wall_ms": elapsed,
            "adapter_busy_throughput_terminal_per_second": (
                total / (elapsed / 1000.0) if total and elapsed > 0 else None
            ),
            "throughput_definition": (
                "terminal outcomes divided by summed adapter invocation wall time"
            ),
            "last_checkpoint": last,
            "seal_status": "SEALED" if self.is_sealed else "UNSEALED",
        }

    # --------------------------------------------------------------- integrity

    def integrity_report(self, *, require_complete: bool) -> dict[str, Any]:
        outcomes = self.outcomes()
        pair_ids = [item.pair.pair_id for item in outcomes]
        ordinals = [item.pair.ordinal for item in outcomes]
        expected_ids = [item.pair_id for item in self.planned_pairs]
        unknown = sorted(set(pair_ids) - set(expected_ids))
        duplicate_ids = len(pair_ids) - len(set(pair_ids))
        duplicate_ordinals = len(ordinals) - len(set(ordinals))
        successes = sum(item.status is Stage21BOutcomeStatus.SUCCESS for item in outcomes)
        failures = len(outcomes) - successes
        release_counts = dict(Counter(item.pair.release for item in outcomes))
        complete = len(outcomes) == self.spec.expected_attempts
        with self._connect(write=False) as connection:
            open_attempts = int(
                connection.execute(
                    "SELECT COUNT(*) FROM attempts WHERE classification='IN_PROGRESS'"
                ).fetchone()[0]
            )
            terminal_attempts = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM attempts
                     WHERE classification IN ('SUCCESS','ALGORITHM_FAILURE')
                    """
                ).fetchone()[0]
            )
        gates = {
            "planned_attempts_match_spec": len(self.planned_pairs)
            == self.spec.expected_attempts,
            "terminal_outcomes_complete": complete,
            "every_manifest_pair_exactly_once": (
                complete and pair_ids == expected_ids
            ),
            "no_unknown_pairs": not unknown,
            "no_duplicate_pair_ids": duplicate_ids == 0,
            "no_duplicate_ordinals": duplicate_ordinals == 0,
            "success_plus_failure_equals_terminal": successes + failures == len(outcomes),
            "success_requires_score_failure_forbids_score": all(
                (item.status is Stage21BOutcomeStatus.SUCCESS) == (item.raw_score is not None)
                for item in outcomes
            ),
            "all_scores_finite": all(
                item.raw_score is None or math.isfinite(item.raw_score) for item in outcomes
            ),
            "release_counts_exact": (
                not complete
                or release_counts == dict(Counter(pair.release for pair in self.planned_pairs))
            ),
            "ground_truth_non_mated": all(
                item.pair.ground_truth == "NON_MATED" for item in outcomes
            ),
            "canonical_order": ordinals == sorted(ordinals),
            "no_in_progress_attempts": open_attempts == 0,
            "one_terminal_attempt_per_outcome": terminal_attempts == len(outcomes),
        }
        if require_complete and not all(gates.values()):
            failed = sorted(key for key, value in gates.items() if not value)
            raise Stage21BIntegrityError(
                "Stage 21B result integrity failed: " + ", ".join(failed)
            )
        return {
            "run_id": self.spec.run_id,
            "algorithm_id": self.spec.algorithm_id,
            "planned_attempts": self.spec.expected_attempts,
            "terminal_outcomes": len(outcomes),
            "score_bearing_outcomes": successes,
            "algorithm_failures": failures,
            "missing": self.spec.expected_attempts - len(outcomes),
            "duplicate_pair_ids": duplicate_ids,
            "duplicate_ordinals": duplicate_ordinals,
            "unknown_pairs": len(unknown),
            "in_progress_attempts": open_attempts,
            "release_counts": release_counts,
            "gates": gates,
            "integrity_pass": all(gates.values()),
        }

    # ------------------------------------------------------------------- seal

    def seal(self) -> dict[str, Any]:
        if self.is_superseded:
            raise Stage21BSealedError("a superseded run cannot be sealed")
        if self.is_sealed:
            return self.verify_seal()
        report = self.integrity_report(require_complete=True)
        self._freeze_checkpoint_database()
        with self._connect(write=False) as connection:
            open_attempts = int(
                connection.execute(
                    "SELECT COUNT(*) FROM attempts WHERE classification='IN_PROGRESS'"
                ).fetchone()[0]
            )
            attempt_rows = [dict(row) for row in connection.execute("SELECT * FROM attempts ORDER BY attempt_id")]
        if open_attempts:
            raise Stage21BIntegrityError("cannot seal with an in-progress infrastructure attempt")
        outcomes = self.outcomes()
        index = [
            {
                "ordinal": item.pair.ordinal,
                "pair_id": item.pair.pair_id,
                "outcome_hash": item.outcome_hash,
            }
            for item in outcomes
        ]
        ordered_hash = stable_hash(index, length=64)
        result_fingerprint = stable_hash(
            {
                "schema": "stage21b_result_set_v1",
                "run_spec_fingerprint": self.spec.run_spec_fingerprint,
                "result_set_id": self.spec.result_set_id,
                "ordered_outcomes": index,
                "success_count": report["score_bearing_outcomes"],
                "algorithm_failure_count": report["algorithm_failures"],
            },
            length=64,
        )
        outcomes_table = _outcomes_table(
            outcomes,
            metadata={
                "run_id": self.spec.run_id,
                "run_spec_fingerprint": self.spec.run_spec_fingerprint,
                "result_set_id": self.spec.result_set_id,
                "result_set_fingerprint": result_fingerprint,
                "ordered_outcomes_sha256": ordered_hash,
            },
        )
        attempts_table = _attempts_table(
            attempt_rows,
            metadata={
                "run_id": self.spec.run_id,
                "run_spec_fingerprint": self.spec.run_spec_fingerprint,
            },
        )
        try:
            publish_table(self.outcomes_path, outcomes_table, what="Stage 21B outcomes")
            publish_table(self.attempts_path, attempts_table, what="Stage 21B attempts")
        except Exception as exc:
            raise Stage21BStoreConflict(f"cannot publish canonical result files: {exc}") from exc

        failure_counts = Counter(
            item.failure_code
            for item in outcomes
            if item.status is Stage21BOutcomeStatus.ALGORITHM_FAILURE
        )
        infrastructure = Counter(
            row["failure_code"]
            for row in attempt_rows
            if str(row["classification"]).startswith("INFRASTRUCTURE_")
        )
        manifest = {
            "schema_version": "1",
            "stage": "21B",
            "kind": "stage_21b_sealed_raw_result_set",
            "run_id": self.spec.run_id,
            "run_spec_fingerprint": self.spec.run_spec_fingerprint,
            "run_spec_file_sha256": _sha256(self.spec_path),
            "checkpoint_database_sha256": _sha256(self.database_path),
            "result_set_id": self.spec.result_set_id,
            "result_set_fingerprint": result_fingerprint,
            "algorithm_id": self.spec.algorithm_id,
            "adapter_id": self.spec.adapter_id,
            "execution_source_fingerprint": self.spec.execution_source_fingerprint,
            "runtime_identity_fingerprint": self.spec.runtime_identity_fingerprint,
            "pair_manifest_hash": self.spec.pair_manifest_hash,
            "pair_ids_sha256": self.spec.pair_ids_sha256,
            "planned_pair_input_fingerprint": (
                self.spec.planned_pair_input_fingerprint
            ),
            "preparation_set_id": self.spec.preparation_set_id,
            "preparation_set_fingerprint": self.spec.preparation_set_fingerprint,
            "preparation_profile_id": self.spec.preparation_profile_id,
            "planned_attempts": self.spec.expected_attempts,
            "terminal_outcomes": report["terminal_outcomes"],
            "score_bearing_outcomes": report["score_bearing_outcomes"],
            "algorithm_failures": report["algorithm_failures"],
            "failure_classifications": dict(sorted(failure_counts.items())),
            "infrastructure_events_before_completion": dict(sorted(infrastructure.items())),
            "release_counts": report["release_counts"],
            "ordered_outcomes_sha256": ordered_hash,
            "outcomes_file": "outcomes.parquet",
            "outcomes_file_sha256": _sha256(self.outcomes_path),
            "attempts_file": "attempts.parquet",
            "attempts_file_sha256": _sha256(self.attempts_path),
            "attempt_records": len(attempt_rows),
            "timing": _timing_document(outcomes, attempt_rows),
            "integrity_gates": report["gates"],
            "metrics_computed": False,
            "threshold_selected": False,
            "calibration_performed": False,
            "score_transform_performed": False,
            "sealed_utc": _utc_now(),
        }
        source_binding = self.run_dir / "execution-source-binding.json"
        if source_binding.is_file():
            manifest["execution_source_binding_file"] = source_binding.name
            manifest["execution_source_binding_file_sha256"] = _sha256(source_binding)
        manifest["result_set_manifest_fingerprint"] = _document_fingerprint(
            manifest
        )
        try:
            publish_json(self.seal_path, manifest)
        except Exception as exc:
            if not self.seal_path.is_file():
                raise Stage21BStoreConflict(f"cannot publish result-set seal: {exc}") from exc
        return self.verify_seal()

    def verify_seal(self) -> dict[str, Any]:
        if not self.seal_path.is_file():
            raise Stage21BIntegrityError("result set is not sealed")
        manifest = _read_json(self.seal_path)
        claimed_manifest_fingerprint = manifest.get(
            "result_set_manifest_fingerprint"
        )
        manifest_body = dict(manifest)
        manifest_body.pop("result_set_manifest_fingerprint", None)
        if claimed_manifest_fingerprint != _document_fingerprint(manifest_body):
            raise Stage21BIntegrityError("result-set seal fingerprint is invalid")
        for path, key in (
            (self.outcomes_path, "outcomes_file_sha256"),
            (self.attempts_path, "attempts_file_sha256"),
        ):
            if not path.is_file() or _sha256(path) != manifest.get(key):
                raise Stage21BIntegrityError(f"sealed file changed or is missing: {path.name}")
        if manifest.get("run_spec_fingerprint") != self.spec.run_spec_fingerprint:
            raise Stage21BIntegrityError("seal describes another run specification")
        if _sha256(self.spec_path) != manifest.get("run_spec_file_sha256"):
            raise Stage21BIntegrityError("sealed run specification changed")
        if _sha256(self.database_path) != manifest.get("checkpoint_database_sha256"):
            raise Stage21BIntegrityError("sealed checkpoint database changed")
        source_name = manifest.get("execution_source_binding_file")
        if source_name is not None:
            source_path = self.run_dir / str(source_name)
            if (
                not source_path.is_file()
                or _sha256(source_path)
                != manifest.get("execution_source_binding_file_sha256")
            ):
                raise Stage21BIntegrityError("sealed execution-source binding changed")
        table = pq.read_table(self.outcomes_path)
        outcomes = tuple(
            TerminalOutcome.from_dict(json.loads(row["payload_json"]))
            for row in table.to_pylist()
        )
        if len(outcomes) != self.spec.expected_attempts:
            raise Stage21BIntegrityError("sealed result count is incomplete")
        if tuple(item.pair for item in outcomes) != self.planned_pairs:
            raise Stage21BIntegrityError("sealed pair set/order changed")
        index = [
            {
                "ordinal": item.pair.ordinal,
                "pair_id": item.pair.pair_id,
                "outcome_hash": item.outcome_hash,
            }
            for item in outcomes
        ]
        ordered_hash = stable_hash(index, length=64)
        successes = sum(item.status is Stage21BOutcomeStatus.SUCCESS for item in outcomes)
        fingerprint = stable_hash(
            {
                "schema": "stage21b_result_set_v1",
                "run_spec_fingerprint": self.spec.run_spec_fingerprint,
                "result_set_id": self.spec.result_set_id,
                "ordered_outcomes": index,
                "success_count": successes,
                "algorithm_failure_count": len(outcomes) - successes,
            },
            length=64,
        )
        if ordered_hash != manifest.get("ordered_outcomes_sha256"):
            raise Stage21BIntegrityError("sealed canonical ordering hash changed")
        if fingerprint != manifest.get("result_set_fingerprint"):
            raise Stage21BIntegrityError("sealed result-set fingerprint changed")
        if manifest.get("score_bearing_outcomes") != successes:
            raise Stage21BIntegrityError("sealed success count changed")
        # Re-read both canonical exports through the independent offline
        # verifier before calling the seal valid.  This also binds the attempt
        # journal to each terminal outcome's provenance without trusting the
        # SQLite journal that produced the files.
        from fpbench.stage21b.integrity import verify_sealed_run_directory

        verified = verify_sealed_run_directory(
            self.run_dir, require_production_shape=False
        )
        if verified["result_set_fingerprint"] != fingerprint:
            raise Stage21BIntegrityError("offline seal verification disagrees")
        return manifest

    # ------------------------------------------------------------- supersede

    def supersede(self, *, reason: str, superseded_by_run_id: str) -> Path:
        text = str(reason).strip()
        if not text:
            raise ValueError("superseded_reason must not be empty")
        document = {
            "schema_version": "1",
            "stage": "21B",
            "status": "superseded",
            "run_id": self.spec.run_id,
            "run_spec_fingerprint": self.spec.run_spec_fingerprint,
            "superseded_reason": text,
            "superseded_by_run_id": str(superseded_by_run_id),
            "recorded_utc": _utc_now(),
        }
        if self.supersession_path.is_file():
            existing = _read_json(self.supersession_path)
            if existing.get("superseded_by_run_id") != superseded_by_run_id:
                raise Stage21BStoreConflict("run already has a different supersession record")
            return self.supersession_path
        publish_json(self.supersession_path, document)
        return self.supersession_path

    def _require_plan_shape(self) -> None:
        if len(self.planned_pairs) != self.spec.expected_attempts:
            raise Stage21BStoreConflict(
                f"run spec expects {self.spec.expected_attempts} pairs, got {len(self.planned_pairs)}"
            )
        if [pair.ordinal for pair in self.planned_pairs] != list(range(len(self.planned_pairs))):
            raise Stage21BStoreConflict("pair ordinals must be 0..n-1 in manifest order")
        ids = [pair.pair_id for pair in self.planned_pairs]
        if len(ids) != len(set(ids)):
            raise Stage21BStoreConflict("planned pair IDs must be unique")
        if stable_hash(ids, length=64) != self.spec.pair_ids_sha256:
            raise Stage21BStoreConflict("planned pair IDs/order differ from the run spec")
        if self._plan_hash != self.spec.planned_pair_input_fingerprint:
            raise Stage21BStoreConflict(
                "planned pair/image/preparation closure differs from the run spec"
            )
        for pair in self.planned_pairs:
            for reference in (pair.left_preparation, pair.right_preparation):
                if (
                    reference.preparation_set_id != self.spec.preparation_set_id
                    or reference.preparation_set_fingerprint
                    != self.spec.preparation_set_fingerprint
                    or reference.preparation_profile_id
                    != self.spec.preparation_profile_id
                    or reference.preparation_profile_fingerprint
                    != self.spec.preparation_profile_fingerprint
                ):
                    raise Stage21BStoreConflict(
                        f"{pair.pair_id}: preparation identity differs from the run spec"
                    )

    def _require_accepting_outcomes(self) -> None:
        if self.outcomes_path.exists() or self.attempts_path.exists():
            raise Stage21BSealedError(
                "canonical exports already exist; execution cannot continue over them"
            )

    def _freeze_checkpoint_database(self) -> None:
        """Merge the WAL and leave one stable database file for the seal."""
        with self._connect(write=True) as connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            mode = str(connection.execute("PRAGMA journal_mode=DELETE").fetchone()[0])
            if mode.lower() != "delete":
                raise Stage21BIntegrityError(
                    "cannot freeze checkpoint database out of WAL mode"
                )


def _outcomes_table(
    outcomes: tuple[TerminalOutcome, ...], *, metadata: Mapping[str, str]
) -> pa.Table:
    schema = pa.schema(
        [
            pa.field("ordinal", pa.int64(), nullable=False),
            pa.field("pair_id", pa.string(), nullable=False),
            pa.field("release", pa.string(), nullable=False),
            pa.field("left_image_id", pa.string(), nullable=False),
            pa.field("right_image_id", pa.string(), nullable=False),
            pa.field("preparation_set_id", pa.string(), nullable=False),
            pa.field("preparation_set_fingerprint", pa.string(), nullable=False),
            pa.field("preparation_profile_id", pa.string(), nullable=False),
            pa.field("left_preparation_entry_hash", pa.string(), nullable=False),
            pa.field("right_preparation_entry_hash", pa.string(), nullable=False),
            pa.field("ground_truth", pa.string(), nullable=False),
            pa.field("status", pa.string(), nullable=False),
            pa.field("raw_score", pa.float64(), nullable=True),
            pa.field("raw_score_hex", pa.string(), nullable=True),
            pa.field("failure_code", pa.string(), nullable=True),
            pa.field("failure_stage", pa.string(), nullable=True),
            pa.field("attempt", pa.int32(), nullable=False),
            pa.field("outcome_hash", pa.string(), nullable=False),
            pa.field("payload_json", pa.string(), nullable=False),
        ]
    )
    rows = [
        {
            "ordinal": item.pair.ordinal,
            "pair_id": item.pair.pair_id,
            "release": item.pair.release,
            "left_image_id": item.pair.left_image_id,
            "right_image_id": item.pair.right_image_id,
            "preparation_set_id": item.pair.left_preparation.preparation_set_id,
            "preparation_set_fingerprint": (
                item.pair.left_preparation.preparation_set_fingerprint
            ),
            "preparation_profile_id": (
                item.pair.left_preparation.preparation_profile_id
            ),
            "left_preparation_entry_hash": (
                item.pair.left_preparation.preparation_entry_hash
            ),
            "right_preparation_entry_hash": (
                item.pair.right_preparation.preparation_entry_hash
            ),
            "ground_truth": item.pair.ground_truth,
            "status": item.status.value,
            "raw_score": item.raw_score,
            "raw_score_hex": item.raw_score_hex,
            "failure_code": item.failure_code,
            "failure_stage": item.failure_stage,
            "attempt": item.attempt,
            "outcome_hash": item.outcome_hash,
            "payload_json": _canonical_json(item.to_dict()),
        }
        for item in outcomes
    ]
    table = pa.Table.from_pylist(rows, schema=schema)
    return table.replace_schema_metadata(
        {key.encode(): str(value).encode() for key, value in metadata.items()}
    )


def _attempts_table(rows: list[dict[str, Any]], *, metadata: Mapping[str, str]) -> pa.Table:
    schema = pa.schema(
        [
            pa.field("attempt_id", pa.int64(), nullable=False),
            pa.field("pair_id", pa.string(), nullable=False),
            pa.field("attempt_number", pa.int32(), nullable=False),
            pa.field("started_utc", pa.string(), nullable=False),
            pa.field("finished_utc", pa.string(), nullable=True),
            pa.field("classification", pa.string(), nullable=False),
            pa.field("failure_code", pa.string(), nullable=True),
            pa.field("failure_stage", pa.string(), nullable=True),
            pa.field("failure_message", pa.string(), nullable=True),
        ]
    )
    table = pa.Table.from_pylist(rows, schema=schema)
    return table.replace_schema_metadata(
        {key.encode(): str(value).encode() for key, value in metadata.items()}
    )


def _timing_document(
    outcomes: tuple[TerminalOutcome, ...], attempts: list[dict[str, Any]]
) -> dict[str, Any]:
    total_ms = sum(item.wall_time_ms for item in outcomes)
    component_totals: Counter[str] = Counter()
    for item in outcomes:
        component_totals.update(item.adapter_timing_ms)
    started_values = [str(row["started_utc"]) for row in attempts if row["started_utc"]]
    finished_values = [str(row["finished_utc"]) for row in attempts if row["finished_utc"]]
    first_started = min(started_values) if started_values else None
    last_finished = max(finished_values) if finished_values else None
    span_seconds: float | None = None
    if first_started is not None and last_finished is not None:
        span_seconds = max(
            0.0,
            (
                dt.datetime.fromisoformat(last_finished)
                - dt.datetime.fromisoformat(first_started)
            ).total_seconds(),
        )
    return {
        "definition": "wall time around one certified adapter.compare invocation",
        "terminal_attempts": len(outcomes),
        "adapter_wall_time_total_ms": total_ms,
        "adapter_component_totals_ms": dict(sorted(component_totals.items())),
        "first_attempt_started_utc": first_started,
        "last_attempt_finished_utc": last_finished,
        "run_wall_clock_span_seconds": span_seconds,
        "wall_clock_throughput_terminal_per_second": (
            len(outcomes) / span_seconds if span_seconds and span_seconds > 0 else None
        ),
    }


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _document_fingerprint(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Stage21BIntegrityError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise Stage21BIntegrityError(f"{path}: expected a JSON object")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _short(value: str, limit: int = 800) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()
