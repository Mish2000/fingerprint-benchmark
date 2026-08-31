"""Raw-contract integrity and score-blind cross-method alignment."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

import pyarrow.parquet as pq

from fpbench.core.serialization import stable_hash
from fpbench.stage21b.constants import (
    EXPECTED_METHODS,
    EXPECTED_PAIRS_PER_METHOD,
    EXPECTED_PAIRS_PER_RELEASE,
    EXPECTED_RELEASES,
    FUTURE_TEST_RELEASE,
)
from fpbench.stage21b.errors import Stage21BIntegrityError
from fpbench.stage21b.models import (
    FrozenRunSpec,
    Stage21BOutcomeStatus,
    TerminalOutcome,
)

_PAIR_COLUMNS = (
    "ordinal",
    "pair_id",
    "release",
    "left_image_id",
    "right_image_id",
    "preparation_set_id",
    "preparation_set_fingerprint",
    "preparation_profile_id",
    "left_preparation_entry_hash",
    "right_preparation_entry_hash",
    "ground_truth",
)


def discover_authoritative_run_directories(
    workspace: Path, algorithm_ids: Iterable[str]
) -> dict[str, Path]:
    """Find exactly one non-superseded sealed run for every roster method."""
    root = Path(workspace).resolve() / "stage21b"
    discovered: dict[str, Path] = {}
    for algorithm_id in algorithm_ids:
        directory = root / str(algorithm_id)
        active = sorted(
            path.parent
            for path in directory.glob("*/run-spec.json")
            if not (path.parent / "supersession.json").is_file()
        )
        if len(active) != 1 or not (active[0] / "result-set.json").is_file():
            raise Stage21BIntegrityError(
                f"{algorithm_id}: expected exactly one active authoritative sealed "
                f"run, found {len(active)} active run(s)"
            )
        discovered[str(algorithm_id)] = active[0]
    return discovered


def verify_sealed_run_directory(
    run_directory: Path,
    *,
    require_production_shape: bool,
) -> dict[str, Any]:
    """Recompute a sealed result identity without producing score summaries."""
    directory = Path(run_directory).resolve()
    spec = FrozenRunSpec.from_dict(_json(directory / "run-spec.json"))
    seal = _json(directory / "result-set.json")
    claimed_seal_fingerprint = seal.get("result_set_manifest_fingerprint")
    seal_body = dict(seal)
    seal_body.pop("result_set_manifest_fingerprint", None)
    if claimed_seal_fingerprint != _document_fingerprint(seal_body):
        raise Stage21BIntegrityError(f"{directory}: result-set seal fingerprint is invalid")
    outcomes_path = _sealed_child(directory, seal.get("outcomes_file"), "outcomes.parquet")
    attempts_path = _sealed_child(directory, seal.get("attempts_file"), "attempts.parquet")
    if _sha256(outcomes_path) != seal.get("outcomes_file_sha256"):
        raise Stage21BIntegrityError(f"{directory}: outcomes parquet changed")
    if _sha256(attempts_path) != seal.get("attempts_file_sha256"):
        raise Stage21BIntegrityError(f"{directory}: attempts parquet changed")
    if seal.get("run_spec_fingerprint") != spec.run_spec_fingerprint:
        raise Stage21BIntegrityError(f"{directory}: seal/run-spec mismatch")
    sealed_spec_fields = {
        "run_id": spec.run_id,
        "result_set_id": spec.result_set_id,
        "algorithm_id": spec.algorithm_id,
        "adapter_id": spec.adapter_id,
        "execution_source_fingerprint": spec.execution_source_fingerprint,
        "runtime_identity_fingerprint": spec.runtime_identity_fingerprint,
        "pair_manifest_hash": spec.pair_manifest_hash,
        "pair_ids_sha256": spec.pair_ids_sha256,
        "planned_pair_input_fingerprint": spec.planned_pair_input_fingerprint,
        "preparation_set_id": spec.preparation_set_id,
        "preparation_set_fingerprint": spec.preparation_set_fingerprint,
        "preparation_profile_id": spec.preparation_profile_id,
        "planned_attempts": spec.expected_attempts,
    }
    mismatched_seal_fields = [
        key for key, expected in sealed_spec_fields.items() if seal.get(key) != expected
    ]
    if mismatched_seal_fields:
        raise Stage21BIntegrityError(
            f"{directory}: seal fields differ from run spec: "
            + ", ".join(mismatched_seal_fields)
        )
    if _sha256(directory / "run-spec.json") != seal.get("run_spec_file_sha256"):
        raise Stage21BIntegrityError(f"{directory}: sealed run spec changed")
    if _sha256(directory / "checkpoint.sqlite3") != seal.get(
        "checkpoint_database_sha256"
    ):
        raise Stage21BIntegrityError(f"{directory}: sealed checkpoint changed")
    source_name = seal.get("execution_source_binding_file")
    if source_name is not None:
        source_path = _sealed_child(
            directory, source_name, "execution-source-binding.json"
        )
        if _sha256(source_path) != seal.get("execution_source_binding_file_sha256"):
            raise Stage21BIntegrityError(f"{directory}: execution-source binding changed")
    elif require_production_shape:
        raise Stage21BIntegrityError(f"{directory}: execution-source binding is missing")

    parquet = pq.ParquetFile(outcomes_path)
    required_columns = set(_PAIR_COLUMNS) | {
        "status",
        "raw_score",
        "raw_score_hex",
        "failure_code",
        "failure_stage",
        "attempt",
        "outcome_hash",
        "payload_json",
    }
    if not required_columns <= set(parquet.schema_arrow.names):
        raise Stage21BIntegrityError(f"{directory}: outcome schema is incomplete")
    metadata = {
        key.decode(): value.decode()
        for key, value in (parquet.schema_arrow.metadata or {}).items()
    }
    if metadata.get("run_spec_fingerprint") != spec.run_spec_fingerprint:
        raise Stage21BIntegrityError(f"{directory}: parquet metadata changed")
    for key, expected in {
        "run_id": spec.run_id,
        "result_set_id": spec.result_set_id,
    }.items():
        if metadata.get(key) != expected:
            raise Stage21BIntegrityError(f"{directory}: parquet {key} metadata changed")

    indexes: list[dict[str, Any]] = []
    pair_ids: list[str] = []
    release_counts: Counter[str] = Counter()
    failure_counts: Counter[str] = Counter()
    success_count = 0
    expected_ordinal = 0
    plan_digest = hashlib.sha256()
    plan_digest.update(b"stage21b_plan_v1\x00")
    for batch in parquet.iter_batches(batch_size=4096):
        for row in batch.to_pylist():
            try:
                outcome = TerminalOutcome.from_dict(json.loads(row["payload_json"]))
            except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
                raise Stage21BIntegrityError(
                    f"sealed terminal payload is invalid: {exc}"
                ) from exc
            if row["payload_json"] != json.dumps(
                outcome.to_dict(),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ):
                raise Stage21BIntegrityError("sealed terminal payload is not canonical")
            if outcome.outcome_hash != row["outcome_hash"]:
                raise Stage21BIntegrityError("terminal outcome hash changed")
            if (
                outcome.run_id != spec.run_id
                or outcome.run_spec_fingerprint != spec.run_spec_fingerprint
                or outcome.result_set_id != spec.result_set_id
                or outcome.algorithm_id != spec.algorithm_id
                or outcome.adapter_id != spec.adapter_id
                or outcome.adapter_descriptor_fingerprint
                != spec.adapter_descriptor_fingerprint
                or outcome.runtime_identity_fingerprint
                != spec.runtime_identity_fingerprint
            ):
                raise Stage21BIntegrityError("terminal outcome belongs to another run")
            if outcome.pair.ordinal != expected_ordinal or row["ordinal"] != expected_ordinal:
                raise Stage21BIntegrityError("canonical outcome ordering changed")
            expected_ordinal += 1
            _require_row_agrees(row, outcome)
            if outcome.status is Stage21BOutcomeStatus.SUCCESS:
                success_count += 1
                if row["raw_score"] is None or not math.isfinite(row["raw_score"]):
                    raise Stage21BIntegrityError("SUCCESS does not carry a finite raw score")
                if float(row["raw_score"]).hex() != outcome.raw_score_hex:
                    raise Stage21BIntegrityError("raw score changed in parquet serialization")
            else:
                if row["raw_score"] is not None or row["raw_score_hex"] is not None:
                    raise Stage21BIntegrityError("algorithm failure was encoded as a score")
                failure_counts[str(outcome.failure_code)] += 1
            pair_ids.append(outcome.pair.pair_id)
            plan_digest.update(
                json.dumps(
                    outcome.pair.to_dict(),
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")
            )
            plan_digest.update(b"\n")
            release_counts[outcome.pair.release] += 1
            indexes.append(
                {
                    "ordinal": outcome.pair.ordinal,
                    "pair_id": outcome.pair.pair_id,
                    "outcome_hash": outcome.outcome_hash,
                }
            )

    count = len(indexes)
    if count != spec.expected_attempts or len(set(pair_ids)) != count:
        raise Stage21BIntegrityError("sealed result does not cover each planned pair once")
    if stable_hash(pair_ids, length=64) != spec.pair_ids_sha256:
        raise Stage21BIntegrityError("sealed pair IDs/order differ from the run spec")
    if plan_digest.hexdigest() != spec.planned_pair_input_fingerprint:
        raise Stage21BIntegrityError(
            "sealed pair/image/preparation closure differs from the run spec"
        )
    ordered_hash = stable_hash(indexes, length=64)
    result_fingerprint = stable_hash(
        {
            "schema": "stage21b_result_set_v1",
            "run_spec_fingerprint": spec.run_spec_fingerprint,
            "result_set_id": spec.result_set_id,
            "ordered_outcomes": indexes,
            "success_count": success_count,
            "algorithm_failure_count": count - success_count,
        },
        length=64,
    )
    if ordered_hash != seal.get("ordered_outcomes_sha256"):
        raise Stage21BIntegrityError("ordered outcome identity changed")
    if result_fingerprint != seal.get("result_set_fingerprint"):
        raise Stage21BIntegrityError("result-set fingerprint changed")
    if seal.get("score_bearing_outcomes") != success_count:
        raise Stage21BIntegrityError("score-bearing count changed")
    if seal.get("algorithm_failures") != count - success_count:
        raise Stage21BIntegrityError("algorithm-failure count changed")
    if seal.get("failure_classifications") != dict(sorted(failure_counts.items())):
        raise Stage21BIntegrityError("algorithm-failure classifications changed")
    if seal.get("release_counts") != dict(release_counts):
        raise Stage21BIntegrityError("sealed release counts changed")
    for name in (
        "metrics_computed",
        "threshold_selected",
        "calibration_performed",
        "score_transform_performed",
    ):
        if seal.get(name) is not False:
            raise Stage21BIntegrityError(f"sealed result violates {name}=false")

    attempts_table = pq.read_table(attempts_path)
    attempts_metadata = {
        key.decode(): value.decode()
        for key, value in (attempts_table.schema.metadata or {}).items()
    }
    if attempts_metadata.get("run_id") != spec.run_id or attempts_metadata.get(
        "run_spec_fingerprint"
    ) != spec.run_spec_fingerprint:
        raise Stage21BIntegrityError("attempt parquet metadata changed")
    attempts = attempts_table.to_pylist()
    open_attempts = sum(row["classification"] == "IN_PROGRESS" for row in attempts)
    terminal_attempts = sum(
        row["classification"] in {"SUCCESS", "ALGORITHM_FAILURE"} for row in attempts
    )
    if open_attempts or terminal_attempts != count:
        raise Stage21BIntegrityError("attempt journal and terminal outcomes disagree")
    _verify_attempt_export(attempts, outcomes_path=outcomes_path)

    production_gates = {
        "planned_attempts_exact_73500": spec.expected_attempts
        == EXPECTED_PAIRS_PER_METHOD,
        "terminal_outcomes_exact_73500": count == EXPECTED_PAIRS_PER_METHOD,
        "release_counts_exact": dict(release_counts)
        == {release: EXPECTED_PAIRS_PER_RELEASE for release in EXPECTED_RELEASES},
    }
    if require_production_shape and not all(production_gates.values()):
        raise Stage21BIntegrityError("sealed run is not the production 73,500 shape")
    return {
        "algorithm_id": spec.algorithm_id,
        "run_id": spec.run_id,
        "result_set_id": spec.result_set_id,
        "run_spec_fingerprint": spec.run_spec_fingerprint,
        "result_set_fingerprint": result_fingerprint,
        "pair_manifest_hash": spec.pair_manifest_hash,
        "pair_ids_sha256": spec.pair_ids_sha256,
        "planned_pair_input_fingerprint": spec.planned_pair_input_fingerprint,
        "preparation_set_id": spec.preparation_set_id,
        "preparation_set_fingerprint": spec.preparation_set_fingerprint,
        "preparation_profile_id": spec.preparation_profile_id,
        "planned_attempts": spec.expected_attempts,
        "terminal_outcomes": count,
        "score_bearing_outcomes": success_count,
        "algorithm_failures": count - success_count,
        "failure_classifications": dict(sorted(failure_counts.items())),
        "release_counts": dict(release_counts),
        "attempt_records": len(attempts),
        "infrastructure_gaps": 0,
        "infrastructure_events_before_completion": seal.get(
            "infrastructure_events_before_completion", {}
        ),
        "timing": seal.get("timing", {}),
        "outcomes_file_sha256": seal.get("outcomes_file_sha256"),
        "attempts_file_sha256": seal.get("attempts_file_sha256"),
        "result_set_manifest_sha256": _sha256(directory / "result-set.json"),
        "result_set_manifest_fingerprint": claimed_seal_fingerprint,
        "production_gates": production_gates,
        "integrity_pass": True,
        "spec": spec,
        "seal": seal,
    }


def audit_cross_method_alignment(
    run_directories: Mapping[str, Path],
    *,
    expected_algorithm_ids: Iterable[str] | None = None,
    require_production_shape: bool,
    expected_pair_manifest_hash: str | None = None,
    expected_pair_ids_sha256: str | None = None,
    expected_manifest_pairs: Iterable[Any] | None = None,
    expected_preparation_set_id: str | None = None,
    expected_preparation_profile_id: str | None = None,
) -> dict[str, Any]:
    """Compare only pair/input identity columns; raw_score is never loaded."""
    if expected_algorithm_ids is not None:
        expected = tuple(expected_algorithm_ids)
        if set(run_directories) != set(expected) or len(run_directories) != len(expected):
            raise Stage21BIntegrityError("alignment input does not exactly match the roster")
    if require_production_shape and len(run_directories) != EXPECTED_METHODS:
        raise Stage21BIntegrityError("alignment requires all six Stage 21B methods")
    if require_production_shape and any(
        value is None
        for value in (
            expected_pair_manifest_hash,
            expected_pair_ids_sha256,
            expected_manifest_pairs,
            expected_preparation_set_id,
            expected_preparation_profile_id,
        )
    ):
        raise Stage21BIntegrityError(
            "production alignment requires the accepted Stage 21A manifest and canonical500 binding"
        )

    expected_identity_rows = (
        tuple(_manifest_pair_identity(pair) for pair in expected_manifest_pairs)
        if expected_manifest_pairs is not None
        else None
    )
    expected_future_ids_hash = (
        stable_hash(
            [
                row["pair_id"]
                for row in expected_identity_rows
                if row["release"] == FUTURE_TEST_RELEASE
            ],
            length=64,
        )
        if expected_identity_rows is not None
        else None
    )

    reference_pair_hash: str | None = None
    reference_ids_hash: str | None = None
    reference_alignment_hash: str | None = None
    reference_prep: tuple[str, str, str] | None = None
    reference_count: int | None = None
    future_ids_hash: str | None = None
    method_rows: list[dict[str, Any]] = []
    for algorithm_id, directory in sorted(run_directories.items()):
        spec = FrozenRunSpec.from_dict(_json(Path(directory) / "run-spec.json"))
        seal = _json(Path(directory) / "result-set.json")
        path = Path(directory) / str(seal["outcomes_file"])
        table = pq.read_table(path, columns=list(_PAIR_COLUMNS))
        rows = table.to_pylist()
        ids = [str(row["pair_id"]) for row in rows]
        ids_hash = stable_hash(ids, length=64)
        alignment_hash = _ordered_identity_hash(rows)
        release_counts = Counter(str(row["release"]) for row in rows)
        b_hash = stable_hash(
            [str(row["pair_id"]) for row in rows if row["release"] == FUTURE_TEST_RELEASE],
            length=64,
        )
        prep = (
            spec.preparation_set_id,
            spec.preparation_set_fingerprint,
            spec.preparation_profile_id,
        )
        if algorithm_id != spec.algorithm_id:
            raise Stage21BIntegrityError("run directory is filed under another algorithm")
        if (
            expected_pair_manifest_hash is not None
            and spec.pair_manifest_hash != expected_pair_manifest_hash
        ):
            raise Stage21BIntegrityError(
                f"{algorithm_id}: pair manifest is not the accepted Stage 21A manifest"
            )
        if expected_pair_ids_sha256 is not None and ids_hash != expected_pair_ids_sha256:
            raise Stage21BIntegrityError(
                f"{algorithm_id}: pair IDs/order are not the accepted Stage 21A sequence"
            )
        if (
            expected_preparation_set_id is not None
            and spec.preparation_set_id != expected_preparation_set_id
        ) or (
            expected_preparation_profile_id is not None
            and spec.preparation_profile_id != expected_preparation_profile_id
        ):
            raise Stage21BIntegrityError(
                f"{algorithm_id}: result set is not on the frozen canonical500 lane"
            )
        if len(rows) != spec.expected_attempts or ids_hash != spec.pair_ids_sha256:
            raise Stage21BIntegrityError(f"{algorithm_id}: pair coverage changed")
        if expected_identity_rows is not None:
            actual_identity_rows = tuple(
                {
                    "pair_id": str(row["pair_id"]),
                    "release": str(row["release"]),
                    "left_image_id": str(row["left_image_id"]),
                    "right_image_id": str(row["right_image_id"]),
                    "ground_truth": str(row["ground_truth"]),
                }
                for row in rows
            )
            if actual_identity_rows != expected_identity_rows:
                raise Stage21BIntegrityError(
                    f"{algorithm_id}: pair/image identities differ from the accepted Stage 21A manifest"
                )
        if any(row["ground_truth"] != "NON_MATED" for row in rows):
            raise Stage21BIntegrityError(f"{algorithm_id}: non-NON_MATED row found")
        if any(
            row["preparation_set_id"] != spec.preparation_set_id
            or row["preparation_set_fingerprint"] != spec.preparation_set_fingerprint
            or row["preparation_profile_id"] != spec.preparation_profile_id
            for row in rows
        ):
            raise Stage21BIntegrityError(f"{algorithm_id}: preparation binding changed")
        if require_production_shape and dict(release_counts) != {
            release: EXPECTED_PAIRS_PER_RELEASE for release in EXPECTED_RELEASES
        }:
            raise Stage21BIntegrityError(
                f"{algorithm_id}: release coverage is not 24,500/24,500/24,500"
            )
        if require_production_shape and (
            release_counts.get(FUTURE_TEST_RELEASE, 0) != EXPECTED_PAIRS_PER_RELEASE
            or (
                expected_future_ids_hash is not None
                and b_hash != expected_future_ids_hash
            )
        ):
            raise Stage21BIntegrityError(
                f"{algorithm_id}: SD300B future-challenger population changed"
            )

        current = (
            spec.pair_manifest_hash,
            ids_hash,
            alignment_hash,
            prep,
            len(rows),
            b_hash,
        )
        if reference_pair_hash is None:
            (
                reference_pair_hash,
                reference_ids_hash,
                reference_alignment_hash,
                reference_prep,
                reference_count,
                future_ids_hash,
            ) = current
        elif current != (
            reference_pair_hash,
            reference_ids_hash,
            reference_alignment_hash,
            reference_prep,
            reference_count,
            future_ids_hash,
        ):
            raise Stage21BIntegrityError(
                f"{algorithm_id}: pair/image/preparation identities are not aligned"
            )
        method_rows.append(
            {
                "algorithm_id": algorithm_id,
                "run_id": spec.run_id,
                "result_set_id": spec.result_set_id,
                "result_set_fingerprint": seal["result_set_fingerprint"],
            }
        )

    if reference_count is None:
        raise Stage21BIntegrityError("no result sets supplied for alignment")
    if require_production_shape and reference_count != EXPECTED_PAIRS_PER_METHOD:
        raise Stage21BIntegrityError("aligned population is not 73,500 pairs")
    return {
        "schema_version": "1",
        "stage": "21B",
        "kind": "stage_21b_cross_method_alignment",
        "method_count": len(method_rows),
        "pair_count_per_method": reference_count,
        "release_counts_per_method": (
            {release: EXPECTED_PAIRS_PER_RELEASE for release in EXPECTED_RELEASES}
            if require_production_shape
            else None
        ),
        "future_sd300b_pair_count": (
            EXPECTED_PAIRS_PER_RELEASE if require_production_shape else None
        ),
        "pair_manifest_hash": reference_pair_hash,
        "pair_ids_sha256": reference_ids_hash,
        "ordered_pair_input_identity_sha256": reference_alignment_hash,
        "preparation_set_id": reference_prep[0],
        "preparation_set_fingerprint": reference_prep[1],
        "preparation_profile_id": reference_prep[2],
        "future_sd300b_pair_ids_sha256": future_ids_hash,
        "methods": method_rows,
        "gates": {
            "all_pair_manifest_hashes_identical": True,
            "all_pair_sets_and_order_identical": True,
            "all_left_right_image_identities_identical": True,
            "all_preparation_entry_identities_identical": True,
            "no_method_specific_filtering": True,
        },
        "raw_score_column_loaded": False,
        "common_score_population_computed": False,
        "alignment_pass": True,
    }


def _manifest_pair_identity(pair: Any) -> dict[str, str]:
    truth = getattr(pair, "ground_truth", "")
    truth = getattr(truth, "name", getattr(truth, "value", truth))
    return {
        "pair_id": str(pair.pair_id),
        "release": str(pair.release),
        "left_image_id": str(pair.left_image_id),
        "right_image_id": str(pair.right_image_id),
        "ground_truth": str(truth).upper(),
    }


def _verify_attempt_export(
    attempts: list[dict[str, Any]], *, outcomes_path: Path
) -> None:
    outcome_rows = pq.read_table(
        outcomes_path,
        columns=[
            "pair_id",
            "attempt",
            "status",
            "failure_code",
            "failure_stage",
            "payload_json",
        ],
    ).to_pylist()
    outcomes = {
        str(row["pair_id"]): TerminalOutcome.from_dict(json.loads(row["payload_json"]))
        for row in outcome_rows
    }
    grouped: dict[str, list[dict[str, Any]]] = {}
    seen_attempt_ids: set[int] = set()
    allowed = {
        "INFRASTRUCTURE_FAILURE",
        "INFRASTRUCTURE_INTERRUPTED",
        "SUCCESS",
        "ALGORITHM_FAILURE",
    }
    for row in attempts:
        attempt_id = int(row["attempt_id"])
        if attempt_id in seen_attempt_ids:
            raise Stage21BIntegrityError("attempt export contains a duplicate attempt ID")
        seen_attempt_ids.add(attempt_id)
        pair_id = str(row["pair_id"])
        if pair_id not in outcomes:
            raise Stage21BIntegrityError("attempt export contains an unknown pair")
        state = str(row["classification"])
        if state not in allowed or row["finished_utc"] is None:
            raise Stage21BIntegrityError("attempt export contains an invalid closed state")
        if state.startswith("INFRASTRUCTURE_") and (
            not row["failure_code"] or not row["failure_stage"]
        ):
            raise Stage21BIntegrityError(
                "infrastructure attempt is missing its operational classification"
            )
        grouped.setdefault(pair_id, []).append(row)
    if set(grouped) != set(outcomes):
        raise Stage21BIntegrityError("attempt export does not cover every terminal pair")
    for pair_id, rows in grouped.items():
        rows.sort(key=lambda row: int(row["attempt_number"]))
        if [int(row["attempt_number"]) for row in rows] != list(
            range(1, len(rows) + 1)
        ):
            raise Stage21BIntegrityError(
                f"{pair_id}: exported attempt numbers are not the canonical 1..n sequence"
            )
        terminal = [
            row
            for row in rows
            if row["classification"] in {"SUCCESS", "ALGORITHM_FAILURE"}
        ]
        outcome = outcomes[pair_id]
        if len(terminal) != 1 or terminal[0] is not rows[-1]:
            raise Stage21BIntegrityError(
                f"{pair_id}: terminal attempt is not the unique final attempt"
            )
        row = terminal[0]
        if (
            int(row["attempt_number"]) != outcome.attempt
            or row["classification"] != outcome.status.value
            or row["started_utc"] != outcome.started_utc
            or row["finished_utc"] != outcome.finished_utc
            or row["failure_code"] != outcome.failure_code
            or row["failure_stage"] != outcome.failure_stage
        ):
            raise Stage21BIntegrityError(
                f"{pair_id}: exported attempt provenance disagrees with the outcome"
            )


def _sealed_child(directory: Path, value: Any, expected_name: str) -> Path:
    if value != expected_name:
        raise Stage21BIntegrityError(
            f"{directory}: sealed file name must be {expected_name!r}"
        )
    path = (directory / expected_name).resolve()
    if path.parent != directory.resolve() or not path.is_file():
        raise Stage21BIntegrityError(f"{directory}: sealed file is absent or escaped")
    return path


def _require_row_agrees(row: Mapping[str, Any], outcome: TerminalOutcome) -> None:
    expected = {
        "ordinal": outcome.pair.ordinal,
        "pair_id": outcome.pair.pair_id,
        "release": outcome.pair.release,
        "left_image_id": outcome.pair.left_image_id,
        "right_image_id": outcome.pair.right_image_id,
        "preparation_set_id": outcome.pair.left_preparation.preparation_set_id,
        "preparation_set_fingerprint": (
            outcome.pair.left_preparation.preparation_set_fingerprint
        ),
        "preparation_profile_id": outcome.pair.left_preparation.preparation_profile_id,
        "left_preparation_entry_hash": (
            outcome.pair.left_preparation.preparation_entry_hash
        ),
        "right_preparation_entry_hash": (
            outcome.pair.right_preparation.preparation_entry_hash
        ),
        "ground_truth": outcome.pair.ground_truth,
        "status": outcome.status.value,
        "raw_score_hex": outcome.raw_score_hex,
        "failure_code": outcome.failure_code,
        "failure_stage": outcome.failure_stage,
        "attempt": outcome.attempt,
    }
    different = [key for key, value in expected.items() if row[key] != value]
    if different:
        raise Stage21BIntegrityError(
            "outcome parquet and canonical payload disagree: " + ", ".join(different)
        )


def _ordered_identity_hash(rows: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    digest.update(b"stage21b_pair_input_alignment_v1\0")
    for row in rows:
        value = {key: row[key] for key in _PAIR_COLUMNS}
        digest.update(
            json.dumps(
                value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8")
        )
        digest.update(b"\n")
    return digest.hexdigest()


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Stage21BIntegrityError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise Stage21BIntegrityError(f"{path}: expected a JSON object")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as stream:
            for block in iter(lambda: stream.read(1 << 20), b""):
                digest.update(block)
    except OSError as exc:
        raise Stage21BIntegrityError(f"cannot hash {path}: {exc}") from exc
    return digest.hexdigest()


def _document_fingerprint(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()
