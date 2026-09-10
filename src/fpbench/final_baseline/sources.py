"""Verified score sources for the final-baseline report.

Two bodies of scores enter the frozen comparison: the six legacy plain↔roll
mated sources whose identities Stage 21A sealed into the roster, and the
six sealed Stage 21B cross-subject result sets.  Both are re-verified from
bytes here — every hash is re-derived from the artifact it describes, never
read back and repeated, because a repeated fingerprint is a claim and this
stage publishes measurements.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import pyarrow.parquet as pq

from fpbench.baseline_evaluation.models import BaselinePopulation, EvaluationAttempt
from fpbench.core.enums import ExecutionStatus, GroundTruth, ProtocolStage, ScoreDirection
from fpbench.core.result_models import raw_result_hash
from fpbench.core.serialization import stable_hash
from fpbench.experiments.stage19_pair_manifest import (
    CanonicalPair,
    load_canonical_pair_manifest,
)
from fpbench.experiments.stage21a_finalization import (
    LEGACY_COHORT_ID,
    LEGACY_PROTOCOL_ID,
)
from fpbench.stage21b.bindings import AlgorithmBinding, PairManifestSnapshot
from fpbench.stage21b.models import Stage21BOutcomeStatus
from fpbench.final_baseline.constants import (
    EXPECTED_GENUINE_PER_METHOD,
    EXPECTED_GENUINE_PER_RELEASE,
    EXPECTED_PAIRS_PER_METHOD,
    EXPECTED_PAIRS_PER_RELEASE,
    EXPECTED_RELEASES,
    LEGACY_PAIR_COUNT,
    LEGACY_PAIR_MANIFEST_HASH,
    PREPARATION_SET_ID,
)
from fpbench.final_baseline.errors import FinalBaselineError
from fpbench.storage.manifest_store import ManifestStore
from fpbench.storage.result_schemas import table_to_raw_results
from fpbench.storage.result_set_store import ResultSetStore
from fpbench.storage.result_store import ResultStore

__all__ = [
    "LegacyGenuineSource",
    "Stage21BImpostorSource",
    "VerifiedMethodAttempts",
    "load_legacy_mated_pairs",
    "load_legacy_genuine_attempts",
    "legacy_source_format",
    "load_stage21b_impostor_attempts",
]


@dataclass(frozen=True, slots=True)
class LegacyGenuineSource:
    """Mated attempts, with predecessor claims separate from observed identity."""

    algorithm_id: str
    predecessor_raw_result_identity: Mapping[str, Any]
    source_format: str
    source_locator: Mapping[str, str]
    stage21c_observed_source_identity: Mapping[str, Any]
    verification: Mapping[str, Any]
    record_algorithm_identity: Mapping[str, str]
    attempts: tuple[EvaluationAttempt, ...]
    planned_attempts: int
    score_bearing_attempts: int
    algorithm_failures: int

    def provenance(self) -> dict[str, Any]:
        """Public source evidence, without scores or machine-local paths."""
        return {
            "predecessor_raw_result_identity": dict(self.predecessor_raw_result_identity),
            "source_format": self.source_format,
            "source_locator": dict(self.source_locator),
            "stage21c_observed_source_identity": dict(
                self.stage21c_observed_source_identity
            ),
            "verification": dict(self.verification),
            "record_algorithm_identity": dict(self.record_algorithm_identity),
            "planned_attempts": self.planned_attempts,
            "score_bearing_attempts": self.score_bearing_attempts,
            "algorithm_failures": self.algorithm_failures,
        }


@dataclass(frozen=True, slots=True)
class Stage21BImpostorSource:
    """The 73,500 sealed cross-subject attempts of one Stage 21B run."""

    algorithm_id: str
    run_id: str
    result_set_id: str
    result_set_fingerprint: str
    seal_fingerprint: str
    run_directory_name: str
    attempts: tuple[EvaluationAttempt, ...]
    planned_attempts: int
    score_bearing_attempts: int
    algorithm_failures: int


@dataclass(frozen=True, slots=True)
class VerifiedMethodAttempts:
    """Everything one roster method contributes to the report, verified."""

    algorithm_id: str
    display_name: str
    role: str
    score_direction: ScoreDirection
    genuine: LegacyGenuineSource
    impostor: Stage21BImpostorSource

    @property
    def attempts(self) -> tuple[EvaluationAttempt, ...]:
        return (*self.genuine.attempts, *self.impostor.attempts)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _document_fingerprint(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_legacy_mated_pairs(workspace: Path) -> tuple[CanonicalPair, ...]:
    """Load the frozen 6,000-pair manifest and select its mated family."""
    store = ManifestStore(Path(workspace))
    manifest = load_canonical_pair_manifest(
        store.pairs_path(LEGACY_PROTOCOL_ID, LEGACY_COHORT_ID),
        expected_pair_manifest_hash=LEGACY_PAIR_MANIFEST_HASH,
    )
    if len(manifest.pairs) != LEGACY_PAIR_COUNT:
        raise FinalBaselineError(
            f"legacy manifest carries {len(manifest.pairs)} pairs, expected "
            f"{LEGACY_PAIR_COUNT}"
        )
    mated = tuple(
        pair
        for pair in manifest.pairs
        if pair.protocol_stage == ProtocolStage.PLAIN_ROLL_MATED.value
    )
    if len(mated) != EXPECTED_GENUINE_PER_METHOD:
        raise FinalBaselineError(
            f"legacy mated family has {len(mated)} pairs, expected "
            f"{EXPECTED_GENUINE_PER_METHOD}"
        )
    for pair in mated:
        if pair.ground_truth != GroundTruth.MATED.value:
            raise FinalBaselineError(
                f"mated pair {pair.pair_id} carries truth {pair.ground_truth!r}"
            )
        if pair.release not in EXPECTED_RELEASES:
            raise FinalBaselineError(
                f"mated pair {pair.pair_id} names unknown release {pair.release!r}"
            )
    for release in EXPECTED_RELEASES:
        count = sum(pair.release == release for pair in mated)
        if count != EXPECTED_GENUINE_PER_RELEASE:
            raise FinalBaselineError(
                f"release {release} has {count} mated pairs, expected "
                f"{EXPECTED_GENUINE_PER_RELEASE}"
            )
    return mated


def load_legacy_genuine_attempts(
    workspace: Path,
    algorithm: AlgorithmBinding,
    mated_pairs: tuple[CanonicalPair, ...],
    *,
    repository_root: Path,
) -> LegacyGenuineSource:
    """Dispatch using exactly the identity schema the predecessor froze."""
    source_format = legacy_source_format(
        algorithm.algorithm_id, algorithm.raw_result_identity
    )
    if source_format == "result_set_store":
        return _load_result_set_genuine_attempts(workspace, algorithm, mated_pairs)
    return _load_jsonl_genuine_attempts(
        workspace, algorithm, mated_pairs,
        repository_root=repository_root, source_format=source_format,
    )


def legacy_source_format(
    algorithm_id: str, identity: Mapping[str, Any]
) -> str:
    """Recognize frozen metadata only; never open a result store to dispatch."""
    if isinstance(identity, Mapping):
        if (
            algorithm_id not in {
                "nbis_mindtct_mcc_sdk_v2",
                "nbis_mindtct_openafis_capacity_extended",
            }
            and set(identity) == {
                "run_id", "run_fingerprint", "result_set_id", "result_set_fingerprint"
            }
            and all(isinstance(value, str) and value.strip() for value in identity.values())
        ):
            return "result_set_store"
        if algorithm_id == "nbis_mindtct_mcc_sdk_v2" and identity == {
            "run_id": "run_stage20b_canonical500"
        }:
            return "stage20b_pair_outcomes_jsonl"
        if (
            algorithm_id == "nbis_mindtct_openafis_capacity_extended"
            and set(identity) == {"kind", "sha256"}
            and identity["kind"] == "immutable_outcome_store_sha256"
            and isinstance(identity["sha256"], str)
            and re.fullmatch(r"[0-9a-f]{64}", identity["sha256"])
        ):
            return "stage19b_pair_outcomes_jsonl"
    raise FinalBaselineError(
        f"{algorithm_id}: unsupported Stage 21A raw_result_identity; expected "
        "four ResultSetStore fields, the MCC Stage 20B run_id, or the "
        "OpenAFIS immutable_outcome_store_sha256 identity"
    )


def _load_result_set_genuine_attempts(
    workspace: Path,
    algorithm: AlgorithmBinding,
    mated_pairs: tuple[CanonicalPair, ...],
) -> LegacyGenuineSource:
    """Re-verify one accepted legacy result set and extract its mated attempts.

    The chain is: the Stage 21A roster names the four identity fields; the
    result-set store re-derives the ordered-results hash and the result-set
    fingerprint from the stored entries; every raw record is then re-hashed
    against its entry.  Only after all of that does a score become an attempt.
    """
    workspace = Path(workspace)
    identity = dict(algorithm.raw_result_identity)
    for key in ("run_id", "run_fingerprint", "result_set_id", "result_set_fingerprint"):
        if not str(identity.get(key, "")).strip():
            raise FinalBaselineError(
                f"{algorithm.algorithm_id}: roster raw_result_identity lacks {key!r}"
            )
    run_id = str(identity["run_id"])

    manifest, entries = ResultSetStore(workspace).read_result_set(run_id)
    checks = (
        ("result_set_id", manifest.result_set_id),
        ("result_set_fingerprint", manifest.result_set_fingerprint),
        ("run_id", manifest.run_id),
        ("run_fingerprint", manifest.run_fingerprint),
    )
    for key, stored in checks:
        if stored != str(identity[key]):
            raise FinalBaselineError(
                f"{algorithm.algorithm_id}: stored result set {key} is {stored}, "
                f"the accepted Stage 21A roster names {identity[key]}"
            )
    if manifest.total_results != LEGACY_PAIR_COUNT:
        raise FinalBaselineError(
            f"{algorithm.algorithm_id}: legacy result set holds "
            f"{manifest.total_results} results, expected {LEGACY_PAIR_COUNT}"
        )

    result_store = ResultStore(workspace)
    records: dict[str, Any] = {}
    record_algorithm_ids: set[str] = set()
    record_algorithm_fingerprints: set[str] = set()
    declared_direction = ScoreDirection(algorithm.score_direction)
    for entry in entries:
        path = result_store.raw_result_path(run_id, entry.job_id)
        loaded = table_to_raw_results(pq.read_table(path))
        if len(loaded) != 1:
            raise FinalBaselineError(f"{path}: expected exactly one raw record")
        record = loaded[0]
        if raw_result_hash(record) != entry.result_hash:
            raise FinalBaselineError(
                f"{path}: raw record does not hash to its result-set entry"
            )
        if record.pair_manifest_hash != LEGACY_PAIR_MANIFEST_HASH:
            raise FinalBaselineError(
                f"{path}: record was produced over pair manifest "
                f"{record.pair_manifest_hash[:12]}…, not the frozen legacy manifest"
            )
        if record.score_direction is not declared_direction:
            raise FinalBaselineError(
                f"{path}: record declares score direction "
                f"{record.score_direction.value}, the roster froze "
                f"{declared_direction.value}"
            )
        pair_id = str(record.pair_id)
        if pair_id in records:
            raise FinalBaselineError(f"{path}: duplicate pair {pair_id}")
        records[pair_id] = record
        record_algorithm_ids.add(record.algorithm_id)
        record_algorithm_fingerprints.add(record.algorithm_fingerprint)
    if len(records) != LEGACY_PAIR_COUNT:
        raise FinalBaselineError(
            f"{algorithm.algorithm_id}: read {len(records)} distinct pairs, "
            f"expected {LEGACY_PAIR_COUNT}"
        )
    if len(record_algorithm_ids) != 1 or len(record_algorithm_fingerprints) != 1:
        raise FinalBaselineError(
            f"{algorithm.algorithm_id}: the legacy records disagree about their "
            f"own algorithm identity: {sorted(record_algorithm_ids)}"
        )

    attempts: list[EvaluationAttempt] = []
    failures = 0
    for pair in mated_pairs:
        record = records.get(pair.pair_id)
        if record is None:
            raise FinalBaselineError(
                f"{algorithm.algorithm_id}: mated pair {pair.pair_id} has no "
                "stored result"
            )
        if record.status is ExecutionStatus.SUCCESS:
            score: float | None = float(record.raw_score)
        else:
            score = None
            failures += 1
        attempts.append(
            EvaluationAttempt(
                pair_id=pair.pair_id,
                release=pair.release,
                population=BaselinePopulation.GENUINE,
                ground_truth=GroundTruth.MATED,
                status=record.status,
                score=score,
            )
        )

    return LegacyGenuineSource(
        algorithm_id=algorithm.algorithm_id,
        predecessor_raw_result_identity=identity,
        source_format="result_set_store",
        source_locator={"root": "workspace", "relative_path": f"results/{run_id}"},
        stage21c_observed_source_identity={
            "kind": "result_set_store_content_identity",
            **dict(checks),
        },
        verification={
            "predecessor_exact_byte_hash_bound": False,
            "predecessor_content_identity_verified": True,
            "raw_record_hashes_verified": len(records),
            "pair_manifest_hash": LEGACY_PAIR_MANIFEST_HASH,
            "stored_outcomes": len(records),
        },
        record_algorithm_identity={
            "algorithm_id": next(iter(record_algorithm_ids)),
            "algorithm_fingerprint": next(iter(record_algorithm_fingerprints)),
        },
        attempts=tuple(attempts),
        planned_attempts=len(attempts),
        score_bearing_attempts=len(attempts) - failures,
        algorithm_failures=failures,
    )


def _read_source_document(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise FinalBaselineError(f"{path}: unreadable source evidence") from exc
    if not isinstance(value, dict):
        raise FinalBaselineError(f"{path}: source evidence must be a JSON object")
    return value


def _require_source_fields(
    document: Mapping[str, Any], expected: Mapping[str, Any], *, where: str
) -> None:
    for field, value in expected.items():
        if document.get(field) != value:
            raise FinalBaselineError(f"{where}: {field} disagrees with the frozen source")


def _load_jsonl_genuine_attempts(
    workspace: Path,
    algorithm: AlgorithmBinding,
    mated_pairs: tuple[CanonicalPair, ...],
    *,
    repository_root: Path,
    source_format: str,
) -> LegacyGenuineSource:
    # Import the existing route contracts, never a runner or diagnostic builder.
    from fpbench.experiments import stage19b_finalization, stage20b_finalization
    from fpbench.experiments.stage19_result_integrity import (
        Stage19ResultIntegrityError,
        verify_outcome_store_integrity,
    )

    immutable = source_format == "stage19b_pair_outcomes_jsonl"
    stage = "19b" if immutable else "20b"
    contract = stage19b_finalization if immutable else stage20b_finalization
    variable = f"FPBENCH_STAGE{stage.upper()}_ROOT"
    location = os.environ.get(variable, "").strip()
    if not location or not (Path(location) / "pair-outcomes.jsonl").is_file():
        raise FinalBaselineError(
            f"{algorithm.algorithm_id}: set {variable} to the retained Stage "
            f"{stage.upper()} directory containing pair-outcomes.jsonl"
        )
    path = Path(location) / "pair-outcomes.jsonl"
    directory = Path(repository_root) / "evidence" / (
        "stage19b-openafis-capacity-extended" if immutable
        else "stage20b-mindtct-mcc-canonical500-raw"
    )
    marker = _read_source_document(directory / f"stage-{stage}-finalization.json")
    fingerprint_key = f"stage_{stage}_finalization_fingerprint"
    body = dict(marker)
    claimed = body.pop(fingerprint_key, None)
    if (
        claimed != algorithm.predecessor_finalization_fingerprint
        or claimed != _document_fingerprint(body)
    ):
        raise FinalBaselineError(f"Stage {stage.upper()}: predecessor fingerprint mismatch")

    checked_documents: dict[str, str] = {}

    def evidence(name: str) -> dict[str, Any]:
        document_path = directory / name
        # Parse the very bytes whose hash the predecessor marker binds.
        try:
            payload = document_path.read_bytes()
            digest = hashlib.sha256(payload).hexdigest()
            if digest != marker.get("evidence_content_hashes", {}).get(name):
                raise FinalBaselineError(f"{document_path}: predecessor evidence hash mismatch")
            value = json.loads(payload)
            if not isinstance(value, dict):
                raise ValueError("expected a JSON object")
        except (OSError, ValueError) as exc:
            raise FinalBaselineError(f"{document_path}: unreadable source evidence") from exc
        checked_documents[name] = digest
        return value

    binding = evidence("canonical-run-binding.json")
    common = {
        "algorithm_id": algorithm.algorithm_id,
        "pair_manifest_hash": LEGACY_PAIR_MANIFEST_HASH,
        "preparation_set_id": PREPARATION_SET_ID,
        "expected_outcomes": LEGACY_PAIR_COUNT,
        "stored_outcomes": LEGACY_PAIR_COUNT,
        "missing": 0,
    }
    _require_source_fields(
        marker,
        {**common, "publication_eligible": True,
         "score_direction": "HIGHER_MORE_SIMILAR", "score_transform": "NONE"},
        where="predecessor marker",
    )
    _require_source_fields(binding, common, where="canonical-run-binding.json")
    if algorithm.score_direction != ScoreDirection.HIGHER_IS_BETTER.value:
        raise FinalBaselineError(f"{algorithm.algorithm_id}: unexpected frozen score direction")

    if immutable:
        expected_sha = algorithm.raw_result_identity["sha256"]
        for document, label in ((marker, "Stage 19B marker"), (binding, "Stage 19B binding")):
            _require_source_fields(
                document, {"outcome_store_sha256": expected_sha}, where=label
            )
        diagnostics = {
            "overall": {
                "comparisons": binding["diagnostic_comparisons"],
                "score_bearing": binding["score_bearing"],
            },
            "outcome_counts": binding["outcome_counts"],
            "failure_reasons": binding["failure_reasons"],
            "by_protocol_stage": [
                {key: row[key] for key in ("label", "comparisons", "score_bearing")}
                for row in binding["by_protocol_stage"]
            ],
        }
        if _sha256(path) != expected_sha:
            raise FinalBaselineError("Stage 19B outcome-store bytes differ from the frozen SHA-256")
    else:
        _require_source_fields(binding, algorithm.raw_result_identity, where="Stage 20B binding")
        historical = evidence("diagnostic-report.json")
        _require_source_fields(
            historical,
            {key: common[key] for key in (
                "algorithm_id", "expected_outcomes", "stored_outcomes", "missing"
            )},
            where="Stage 20B diagnostics",
        )
        # Historical structural names only. Score summaries are not inputs to
        # this compatibility boundary and the frozen document is never rewritten.
        diagnostics = {
            "overall": {
                "comparisons": historical["stored_outcomes"],
                "score_bearing": historical["overall"]["score_bearing"],
            },
            "outcome_counts": historical["outcome_counts"],
            "failure_reasons": historical["failure_reasons"],
            "by_protocol_stage": [
                {"label": row["protocol_stage"], "comparisons": row["attempted"],
                 "score_bearing": row["score_bearing"]}
                for row in historical["by_protocol_stage"]
            ],
        }

    manifest = load_canonical_pair_manifest(
        ManifestStore(Path(workspace)).pairs_path(LEGACY_PROTOCOL_ID, LEGACY_COHORT_ID),
        expected_pair_manifest_hash=LEGACY_PAIR_MANIFEST_HASH,
    )
    frozen_mated = tuple(
        pair for pair in manifest.pairs if pair.protocol_stage == "plain_roll_mated"
    )
    if frozen_mated != mated_pairs or len(mated_pairs) != EXPECTED_GENUINE_PER_METHOD:
        raise FinalBaselineError(
            "legacy genuine selection differs from the frozen mated population"
        )
    try:
        integrity = verify_outcome_store_integrity(
            path, diagnostics, expected_outcomes=LEGACY_PAIR_COUNT,
            manifest=manifest.pairs, algorithm_id=algorithm.algorithm_id,
            pair_manifest_hash=manifest.pair_manifest_hash,
            classified_failure_reasons=contract.CLASSIFIED_FAILURE_REASONS,
            outcome_contract=contract.OUTCOME_CONTRACT,
        )
    except Stage19ResultIntegrityError as exc:
        raise FinalBaselineError(str(exc)) from exc
    if immutable and integrity.outcome_store_sha256 != expected_sha:
        raise FinalBaselineError("Stage 19B outcome-store bytes differ from the frozen SHA-256")
    _require_source_fields(
        marker, {"score_bearing": integrity.score_bearing}, where="predecessor marker"
    )
    _require_source_fields(binding, {
        "score_bearing": integrity.score_bearing,
        "outcome_counts": dict(integrity.outcome_counts),
        "failure_reasons": dict(integrity.failure_reasons),
    }, where="canonical-run-binding.json")
    if not immutable:
        _require_source_fields(binding, {
            "protocol_stages": {
                row["label"]: row["comparisons"] for row in integrity.by_protocol_stage
            },
        }, where="Stage 20B binding")
        _require_source_fields(evidence("result-integrity.json"), {
            "algorithm_id": algorithm.algorithm_id,
            "algorithm_ids_present": [algorithm.algorithm_id],
            "expected_outcomes": LEGACY_PAIR_COUNT,
            "stored_outcomes": integrity.stored_outcomes,
            "score_bearing": integrity.score_bearing,
            "missing": 0, "duplicate_pair_ids": 0,
            "ordinals_are_complete": True, "ordinals_are_the_manifest_order": True,
            "scores_outside_contract": 0, "failures_recorded_as_zero": 0,
            "successes_recorded_without_a_score": 0,
        }, where="Stage 20B result integrity")

    # Re-reading for extraction must reproduce the verifier's exact bytes.
    # Parse this in-memory payload so a later on-disk mutation cannot change an attempt.
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != integrity.outcome_store_sha256:
        raise FinalBaselineError("legacy outcome store changed during verification")
    rows = [json.loads(line) for line in payload.splitlines() if line.strip()]
    by_pair = {row["pair_id"].strip(): row for row in rows}
    attempts = tuple(
        EvaluationAttempt(
            pair_id=pair.pair_id, release=pair.release,
            population=BaselinePopulation.GENUINE, ground_truth=GroundTruth.MATED,
            status=(ExecutionStatus.SUCCESS if by_pair[pair.pair_id]["status"].strip() == "OK"
                    else ExecutionStatus.FAILURE),
            score=(float(by_pair[pair.pair_id]["raw_score"])
                   if by_pair[pair.pair_id]["status"].strip() == "OK" else None),
        )
        for pair in mated_pairs
    )
    scored = sum(attempt.status is ExecutionStatus.SUCCESS for attempt in attempts)
    return LegacyGenuineSource(
        algorithm_id=algorithm.algorithm_id,
        predecessor_raw_result_identity=dict(algorithm.raw_result_identity),
        source_format=source_format,
        source_locator={
            "root_environment_variable": variable, "relative_path": "pair-outcomes.jsonl"
        },
        stage21c_observed_source_identity={
            "kind": "outcome_store_sha256", "sha256": integrity.outcome_store_sha256,
        },
        verification={
            "predecessor_exact_byte_hash_bound": immutable,
            "predecessor_content_identity_verified": immutable,
            "predecessor_finalization_fingerprint": claimed,
            "predecessor_evidence_content_hashes": checked_documents,
            "pair_manifest_hash": integrity.pair_manifest_hash,
            "bound_manifest_digest": integrity.bound_manifest_digest,
            "stored_outcomes": integrity.stored_outcomes,
            "score_bearing_outcomes": integrity.score_bearing,
            "algorithm_failures": integrity.stored_outcomes - integrity.score_bearing,
            "row_manifest_and_outcome_contract_verified": True,
        },
        record_algorithm_identity={"algorithm_id": algorithm.algorithm_id},
        attempts=attempts, planned_attempts=len(attempts),
        score_bearing_attempts=scored, algorithm_failures=len(attempts) - scored,
    )


def load_stage21b_impostor_attempts(
    run_directory: Path,
    algorithm: AlgorithmBinding,
    frozen: PairManifestSnapshot,
) -> Stage21BImpostorSource:
    """Re-verify one sealed Stage 21B run and extract its 73,500 attempts.

    The seal is checked the way Stage 21B's own verifier checks it: the seal
    document must fingerprint to itself, the outcomes file must hash to the
    seal's digest, the ordered-outcomes hash and the result-set fingerprint are
    re-derived from the rows as read, and every row is checked against the
    frozen Stage 21A pair manifest — position, pair id, release and truth.
    """
    directory = Path(run_directory).resolve()
    seal_path = directory / "result-set.json"
    if not seal_path.is_file():
        raise FinalBaselineError(
            f"{algorithm.algorithm_id}: {directory.name} is not sealed; run "
            "Stage 21B to completion first"
        )
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    claimed = seal.get("result_set_manifest_fingerprint")
    body = dict(seal)
    body.pop("result_set_manifest_fingerprint", None)
    if claimed != _document_fingerprint(body):
        raise FinalBaselineError(f"{seal_path}: seal fingerprint does not cover the seal")
    if seal.get("algorithm_id") != algorithm.algorithm_id:
        raise FinalBaselineError(
            f"{seal_path}: seal names algorithm {seal.get('algorithm_id')!r}"
        )
    if seal.get("pair_manifest_hash") != frozen.pair_manifest_hash:
        raise FinalBaselineError(
            f"{seal_path}: sealed over pair manifest "
            f"{str(seal.get('pair_manifest_hash'))[:12]}…, the frozen protocol is "
            f"{frozen.pair_manifest_hash[:12]}…"
        )
    if seal.get("pair_ids_sha256") != frozen.pair_ids_sha256:
        raise FinalBaselineError(f"{seal_path}: sealed pair ids differ from Stage 21A")
    if int(seal.get("planned_attempts", -1)) != EXPECTED_PAIRS_PER_METHOD:
        raise FinalBaselineError(
            f"{seal_path}: planned attempts are {seal.get('planned_attempts')}, "
            f"expected {EXPECTED_PAIRS_PER_METHOD}"
        )

    outcomes_path = directory / str(seal.get("outcomes_file", "outcomes.parquet"))
    if _sha256(outcomes_path) != seal.get("outcomes_file_sha256"):
        raise FinalBaselineError(
            f"{outcomes_path}: bytes do not hash to the seal's digest"
        )
    table = pq.read_table(outcomes_path)
    metadata = {
        (key.decode() if isinstance(key, bytes) else key): (
            value.decode() if isinstance(value, bytes) else value
        )
        for key, value in (table.schema.metadata or {}).items()
    }
    for key in ("run_id", "result_set_id", "result_set_fingerprint"):
        if metadata.get(key) != str(seal.get(key)):
            raise FinalBaselineError(
                f"{outcomes_path}: parquet metadata {key} disagrees with the seal"
            )
    rows = table.to_pylist()
    if len(rows) != EXPECTED_PAIRS_PER_METHOD:
        raise FinalBaselineError(
            f"{outcomes_path}: {len(rows)} rows, expected {EXPECTED_PAIRS_PER_METHOD}"
        )

    index = [
        {
            "ordinal": row["ordinal"],
            "pair_id": row["pair_id"],
            "outcome_hash": row["outcome_hash"],
        }
        for row in rows
    ]
    if stable_hash(index, length=64) != seal.get("ordered_outcomes_sha256"):
        raise FinalBaselineError(
            f"{outcomes_path}: rows do not reproduce ordered_outcomes_sha256"
        )
    scored = sum(row["status"] == Stage21BOutcomeStatus.SUCCESS.value for row in rows)
    failures = len(rows) - scored
    recomputed_fingerprint = stable_hash(
        {
            "schema": "stage21b_result_set_v1",
            "run_spec_fingerprint": seal.get("run_spec_fingerprint"),
            "result_set_id": seal.get("result_set_id"),
            "ordered_outcomes": index,
            "success_count": scored,
            "algorithm_failure_count": failures,
        },
        length=64,
    )
    if recomputed_fingerprint != seal.get("result_set_fingerprint"):
        raise FinalBaselineError(
            f"{outcomes_path}: rows do not reproduce the sealed result-set "
            "fingerprint"
        )
    if scored != int(seal.get("score_bearing_outcomes", -1)) or failures != int(
        seal.get("algorithm_failures", -1)
    ):
        raise FinalBaselineError(f"{seal_path}: sealed counts disagree with the rows")

    attempts: list[EvaluationAttempt] = []
    release_counts = {release: 0 for release in EXPECTED_RELEASES}
    for position, (row, pair) in enumerate(zip(rows, frozen.pairs)):
        if int(row["ordinal"]) != position:
            raise FinalBaselineError(
                f"{outcomes_path}: row {position} is out of manifest order"
            )
        if row["pair_id"] != str(pair.pair_id):
            raise FinalBaselineError(
                f"{outcomes_path}: row {position} is pair {row['pair_id']}, the "
                f"manifest plans {pair.pair_id}"
            )
        if row["release"] != pair.release:
            raise FinalBaselineError(
                f"{outcomes_path}: pair {row['pair_id']} release disagrees with "
                "the manifest"
            )
        if row["ground_truth"] != GroundTruth.NON_MATED.value.upper():
            raise FinalBaselineError(
                f"{outcomes_path}: pair {row['pair_id']} carries truth "
                f"{row['ground_truth']!r}"
            )
        status_raw = row["status"]
        if status_raw == Stage21BOutcomeStatus.SUCCESS.value:
            status = ExecutionStatus.SUCCESS
            if row["raw_score"] is None:
                raise FinalBaselineError(
                    f"{outcomes_path}: successful pair {row['pair_id']} has no score"
                )
            score: float | None = float(row["raw_score"])
        elif status_raw == Stage21BOutcomeStatus.ALGORITHM_FAILURE.value:
            status = ExecutionStatus.FAILURE
            if row["raw_score"] is not None:
                raise FinalBaselineError(
                    f"{outcomes_path}: failed pair {row['pair_id']} carries a score"
                )
            score = None
        else:
            raise FinalBaselineError(
                f"{outcomes_path}: pair {row['pair_id']} has unknown status "
                f"{status_raw!r}"
            )
        release_counts[row["release"]] += 1
        attempts.append(
            EvaluationAttempt(
                pair_id=row["pair_id"],
                release=row["release"],
                population=BaselinePopulation.IMPOSTOR,
                ground_truth=GroundTruth.NON_MATED,
                status=status,
                score=score,
            )
        )
    for release, count in release_counts.items():
        if count != EXPECTED_PAIRS_PER_RELEASE:
            raise FinalBaselineError(
                f"{outcomes_path}: release {release} holds {count} pairs, expected "
                f"{EXPECTED_PAIRS_PER_RELEASE}"
            )

    return Stage21BImpostorSource(
        algorithm_id=algorithm.algorithm_id,
        run_id=str(seal["run_id"]),
        result_set_id=str(seal["result_set_id"]),
        result_set_fingerprint=str(seal["result_set_fingerprint"]),
        seal_fingerprint=str(claimed),
        run_directory_name=directory.name,
        attempts=tuple(attempts),
        planned_attempts=len(attempts),
        score_bearing_attempts=scored,
        algorithm_failures=failures,
    )
