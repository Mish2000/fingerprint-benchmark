"""Verified score sources for the final-baseline report.

Two bodies of scores enter the frozen comparison: the six legacy plain↔roll
mated result sets whose identities Stage 21A sealed into the roster, and the
six sealed Stage 21B cross-subject result sets.  Both are re-verified from
bytes here — every hash is re-derived from the artifact it describes, never
read back and repeated, because a repeated fingerprint is a claim and this
stage publishes measurements.
"""

from __future__ import annotations

import hashlib
import json
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
    "load_stage21b_impostor_attempts",
]


@dataclass(frozen=True, slots=True)
class LegacyGenuineSource:
    """The 1,500 plain↔roll mated attempts of one accepted legacy result set."""

    algorithm_id: str
    run_id: str
    result_set_id: str
    result_set_fingerprint: str
    run_fingerprint: str
    record_algorithm_id: str
    record_algorithm_fingerprint: str
    attempts: tuple[EvaluationAttempt, ...]
    planned_attempts: int
    score_bearing_attempts: int
    algorithm_failures: int


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
        run_id=run_id,
        result_set_id=manifest.result_set_id,
        result_set_fingerprint=manifest.result_set_fingerprint,
        run_fingerprint=manifest.run_fingerprint,
        record_algorithm_id=next(iter(record_algorithm_ids)),
        record_algorithm_fingerprint=next(iter(record_algorithm_fingerprints)),
        attempts=tuple(attempts),
        planned_attempts=len(attempts),
        score_bearing_attempts=len(attempts) - failures,
        algorithm_failures=failures,
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
