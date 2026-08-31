"""Consume the accepted Stage 21A marker without importing evaluation code."""

from __future__ import annotations

import ast
import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from fpbench.core.enums import BaselineProtocolStage, GroundTruth
from fpbench.core.models import ComparisonPair
from fpbench.core.serialization import stable_hash
from fpbench.stage21b.constants import (
    EXPECTED_METHODS,
    EXPECTED_PAIRS_PER_METHOD,
    EXPECTED_PAIRS_PER_RELEASE,
    EXPECTED_RELEASES,
    FUTURE_TEST_RELEASE,
    LEGACY_PAIR_COUNT,
    LEGACY_PAIR_MANIFEST_HASH,
    POPULATION,
    PROTOCOL_ID,
    ROSTER_ID,
    STAGE21A_EVIDENCE,
    STAGE21A_MARKER,
)
from fpbench.stage21b.errors import Stage21BPreflightError
from fpbench.storage.manifest_store import ManifestStore

_STAGE21A_OUTCOME = "FINAL_BASELINE_EVALUATION_PROTOCOL_READY"


@dataclass(frozen=True, slots=True)
class AlgorithmBinding:
    algorithm_id: str
    role: str
    display_name: str
    adapter_id: str
    integration_id: str | None
    implementation_version: str
    score_direction: str
    predecessor_finalization_fingerprint: str
    raw_result_identity: Mapping[str, Any]
    upstream_artifact: str | None
    upstream_commit: str | None


@dataclass(frozen=True, slots=True)
class Stage21ABinding:
    finalization_fingerprint: str
    source_fingerprint: str
    roster_id: str
    roster_fingerprint: str
    protocol_config_sha256: str
    pair_manifest_hash: str
    pair_ids_sha256: str
    pair_count: int
    high_resolution_reservation_fingerprint: str
    future_test_release: str
    legacy_pair_manifest_hash: str
    cohort_id: str
    algorithms: tuple[AlgorithmBinding, ...]
    marker: Mapping[str, Any]
    pair_binding: Mapping[str, Any]
    legacy_binding: Mapping[str, Any]

    @property
    def algorithm_ids(self) -> tuple[str, ...]:
        return tuple(item.algorithm_id for item in self.algorithms)

    @property
    def adapter_ids(self) -> tuple[str, ...]:
        return tuple(item.adapter_id for item in self.algorithms)

    @property
    def accepted_legacy_result_identities(self) -> dict[str, dict[str, Any]]:
        """Return the six legacy result identities sealed into Stage 21A.

        These are evidence identities, not a claim that Stage 21B opened the
        legacy raw stores.  The Stage 21A marker binds the roster document that
        carries them, while Stage 21B writes into its own disjoint result-store
        namespace.
        """
        return {
            item.algorithm_id: {
                "predecessor_finalization_fingerprint": (
                    item.predecessor_finalization_fingerprint
                ),
                "raw_result_identity": dict(item.raw_result_identity),
            }
            for item in self.algorithms
        }

    @property
    def accepted_legacy_result_identities_fingerprint(self) -> str:
        return stable_hash(self.accepted_legacy_result_identities, length=64)

    def algorithm(self, algorithm_id: str) -> AlgorithmBinding:
        for item in self.algorithms:
            if item.algorithm_id == algorithm_id:
                return item
        raise Stage21BPreflightError(
            f"algorithm {algorithm_id!r} is not in the accepted Stage 21A roster"
        )


@dataclass(frozen=True, slots=True)
class PairManifestSnapshot:
    pairs: tuple[ComparisonPair, ...]
    pair_manifest_hash: str
    pair_ids_sha256: str
    protocol_id: str
    cohort_id: str


def load_stage21a_binding(
    repository_root: Path, *, require_predecessor_files: bool = False
) -> Stage21ABinding:
    root = Path(repository_root).resolve()
    directory = root / STAGE21A_EVIDENCE
    marker = _json(directory / STAGE21A_MARKER)
    _verify_marker(root, directory, marker)

    roster_document = _json(directory / "baseline-roster.json")
    pair = _json(directory / "cross-subject-pair-binding.json")
    reservation = _json(directory / "high-resolution-test-reservation.json")
    predecessors = _json(directory / "predecessor-bindings.json")
    predecessor_values: set[str] = set()
    if require_predecessor_files:
        predecessor_values = _verify_predecessor_documents(root, predecessors)

    methods = roster_document.get("methods")
    if not isinstance(methods, list) or len(methods) != EXPECTED_METHODS:
        raise Stage21BPreflightError("Stage 21A roster does not contain exactly six methods")
    config_path = root / str(roster_document.get("roster_config", ""))
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    configured = tuple(
        (row.get("algorithm_id"), row.get("role")) for row in config.get("methods", [])
    )
    evidenced = tuple((row.get("algorithm_id"), row.get("role")) for row in methods)
    if configured != evidenced:
        raise Stage21BPreflightError(
            "the accepted roster evidence and frozen roster config disagree"
        )
    if config.get("roster_id") != ROSTER_ID or roster_document.get("roster_id") != ROSTER_ID:
        raise Stage21BPreflightError("the Stage 21A roster identity changed")
    if len({row[0] for row in evidenced}) != EXPECTED_METHODS:
        raise Stage21BPreflightError("the Stage 21A roster contains a duplicate algorithm")

    algorithms: list[AlgorithmBinding] = []
    for row in methods:
        for key in (
            "algorithm_id",
            "role",
            "display_name",
            "adapter_id",
            "implementation_version",
            "score_direction",
            "finalization_fingerprint",
        ):
            if row.get(key) in (None, ""):
                raise Stage21BPreflightError(
                    f"Stage 21A roster method is missing {key!r}"
                )
        if row.get("canonical_preparation_set_id") != "prepset_be560e047991":
            raise Stage21BPreflightError("a roster method is not bound to canonical500")
        if row.get("pair_manifest_hash") != LEGACY_PAIR_MANIFEST_HASH:
            raise Stage21BPreflightError("a roster predecessor is not bound to legacy 6,000")
        raw_result_identity = row.get("raw_result_identity")
        if not isinstance(raw_result_identity, Mapping) or not raw_result_identity:
            raise Stage21BPreflightError(
                "a Stage 21A roster method has no accepted raw-result identity"
            )
        if any(value in (None, "") for value in raw_result_identity.values()):
            raise Stage21BPreflightError(
                "a Stage 21A roster method has an incomplete raw-result identity"
            )
        algorithms.append(
            AlgorithmBinding(
                algorithm_id=str(row["algorithm_id"]),
                role=str(row["role"]),
                display_name=str(row["display_name"]),
                adapter_id=str(row["adapter_id"]),
                integration_id=(
                    str(row["integration_id"]) if row.get("integration_id") else None
                ),
                implementation_version=str(row["implementation_version"]),
                score_direction=str(row["score_direction"]),
                predecessor_finalization_fingerprint=str(row["finalization_fingerprint"]),
                raw_result_identity={
                    str(key): value for key, value in raw_result_identity.items()
                },
                upstream_artifact=(
                    str(row["upstream_artifact"]) if row.get("upstream_artifact") else None
                ),
                upstream_commit=(
                    str(row["upstream_commit"]) if row.get("upstream_commit") else None
                ),
            )
        )
    if require_predecessor_files:
        missing_finalizations = sorted(
            item.predecessor_finalization_fingerprint
            for item in algorithms
            if item.predecessor_finalization_fingerprint not in predecessor_values
        )
        if missing_finalizations:
            raise Stage21BPreflightError(
                "predecessor evidence does not carry every roster finalization: "
                + ", ".join(missing_finalizations)
            )

    if pair.get("protocol_id") != PROTOCOL_ID or pair.get("population") != POPULATION:
        raise Stage21BPreflightError("Stage 21A cross-subject population identity changed")
    if pair.get("pair_count") != EXPECTED_PAIRS_PER_METHOD:
        raise Stage21BPreflightError("Stage 21A cross-subject count is not 73,500")
    if pair.get("pair_manifest_hash") != marker.get("cross_subject_pair_manifest_hash"):
        raise Stage21BPreflightError("Stage 21A marker and pair binding disagree")
    if pair.get("legacy_pair_manifest_hash") != LEGACY_PAIR_MANIFEST_HASH:
        raise Stage21BPreflightError("the legacy pair manifest changed")
    reserved_release = reservation.get("reservation", {}).get("primary_release")
    if reserved_release != FUTURE_TEST_RELEASE:
        raise Stage21BPreflightError("the future challenger is no longer bound to SD300B")

    legacy = _json(directory / "legacy-protocol-invariance.json")
    if (
        legacy.get("pass") is not True
        or legacy.get("count") != LEGACY_PAIR_COUNT
        or legacy.get("pair_manifest_hash") != LEGACY_PAIR_MANIFEST_HASH
        or not str(legacy.get("protocol_id", "")).strip()
        or not str(legacy.get("cohort_id", "")).strip()
        or not str(legacy.get("pair_ids_sha256", "")).strip()
    ):
        raise Stage21BPreflightError("Stage 21A legacy-protocol invariance is not intact")

    hashes = marker["evidence_content_hashes"]
    return Stage21ABinding(
        finalization_fingerprint=str(marker["stage_21a_finalization_fingerprint"]),
        source_fingerprint=str(marker["stage21a_source_fingerprint"]),
        roster_id=ROSTER_ID,
        roster_fingerprint=str(hashes["baseline-roster.json"]),
        protocol_config_sha256=str(pair["generation_config_sha256"]),
        pair_manifest_hash=str(pair["pair_manifest_hash"]),
        pair_ids_sha256=str(pair["pair_ids_sha256"]),
        pair_count=int(pair["pair_count"]),
        high_resolution_reservation_fingerprint=str(
            hashes["high-resolution-test-reservation.json"]
        ),
        future_test_release=str(reserved_release),
        legacy_pair_manifest_hash=LEGACY_PAIR_MANIFEST_HASH,
        cohort_id=str(pair["cohort_id"]),
        algorithms=tuple(algorithms),
        marker=marker,
        pair_binding=pair,
        legacy_binding=legacy,
    )


def load_frozen_pairs(
    *, workspace: Path, binding: Stage21ABinding
) -> PairManifestSnapshot:
    store = ManifestStore(Path(workspace))
    metadata = store.pair_manifest_metadata(PROTOCOL_ID, binding.cohort_id)
    if metadata["pair_manifest_hash"] != binding.pair_manifest_hash:
        raise Stage21BPreflightError("local pair manifest does not match Stage 21A")
    pairs = tuple(store.read_pairs(PROTOCOL_ID, binding.cohort_id))
    if len(pairs) != EXPECTED_PAIRS_PER_METHOD:
        raise Stage21BPreflightError("local Stage 21B pair manifest is not 73,500 rows")
    ids_hash = stable_hash([str(pair.pair_id) for pair in pairs], length=64)
    if ids_hash != binding.pair_ids_sha256:
        raise Stage21BPreflightError("local pair IDs/order do not match Stage 21A")
    counts = Counter(pair.release for pair in pairs)
    expected = {release: EXPECTED_PAIRS_PER_RELEASE for release in EXPECTED_RELEASES}
    if dict(counts) != expected:
        raise Stage21BPreflightError(
            f"release counts are {dict(counts)}, expected {expected}"
        )
    if len({str(pair.pair_id) for pair in pairs}) != len(pairs):
        raise Stage21BPreflightError("the frozen pair manifest has duplicate pair IDs")
    for pair in pairs:
        if pair.ground_truth is not GroundTruth.NON_MATED:
            raise Stage21BPreflightError(f"pair {pair.pair_id} is not NON_MATED")
        if pair.protocol_stage is not BaselineProtocolStage.PLAIN_ROLL_CROSS_SUBJECT_NON_MATED:
            raise Stage21BPreflightError(
                f"pair {pair.pair_id} is outside the frozen Stage 21B population"
            )
    return PairManifestSnapshot(
        pairs=pairs,
        pair_manifest_hash=binding.pair_manifest_hash,
        pair_ids_sha256=ids_hash,
        protocol_id=PROTOCOL_ID,
        cohort_id=binding.cohort_id,
    )


def verify_legacy_manifest_unchanged(
    *, workspace: Path, binding: Stage21ABinding
) -> dict[str, Any]:
    """Re-read the legacy 6,000 manifest and prove Stage 21B did not touch it.

    ``legacy_manifest_unchanged`` is a claim the finalization marker makes, and
    a claim decided by a constant is not evidence — the recurring finding in
    this repository's own audits.  The accepted Stage 21A invariance document
    supplies the expected protocol, cohort, count and both digests; this
    re-derives all four from the local store, so the marker's claim is grounded
    in the manifest that is actually on disk after the six runs.

    Stage 21B never reads a legacy *outcome*: the legacy result sets are outside
    this stage entirely.  Their accepted identities are carried forward from
    the hash-bound Stage 21A roster instead of fabricating a claim that the raw
    stores themselves were reopened here.
    """
    legacy = binding.legacy_binding
    protocol_id = str(legacy["protocol_id"])
    cohort_id = str(legacy["cohort_id"])
    store = ManifestStore(Path(workspace))
    try:
        metadata = store.pair_manifest_metadata(protocol_id, cohort_id)
        pairs = tuple(store.read_pairs(protocol_id, cohort_id))
    except Exception as exc:
        raise Stage21BPreflightError(
            f"cannot re-read the legacy {LEGACY_PAIR_COUNT} pair manifest: {exc}"
        ) from exc
    ids_hash = stable_hash([str(pair.pair_id) for pair in pairs], length=64)
    observed = {
        "protocol_id": metadata["protocol_id"],
        "cohort_id": metadata["cohort_id"],
        "pair_count": len(pairs),
        "pair_manifest_hash": metadata["pair_manifest_hash"],
        "pair_ids_sha256": ids_hash,
    }
    expected = {
        "protocol_id": protocol_id,
        "cohort_id": cohort_id,
        "pair_count": LEGACY_PAIR_COUNT,
        "pair_manifest_hash": LEGACY_PAIR_MANIFEST_HASH,
        "pair_ids_sha256": str(legacy["pair_ids_sha256"]),
    }
    different = sorted(key for key, value in expected.items() if observed[key] != value)
    if different:
        raise Stage21BPreflightError(
            "the legacy 6,000 pair manifest changed: " + ", ".join(different)
        )
    return {
        **expected,
        "reread_from_local_store": True,
        "accepted_legacy_result_identities": (
            binding.accepted_legacy_result_identities
        ),
        "accepted_legacy_result_identities_fingerprint": (
            binding.accepted_legacy_result_identities_fingerprint
        ),
    }


def _verify_marker(root: Path, directory: Path, marker: Mapping[str, Any]) -> None:
    fingerprint = marker.get("stage_21a_finalization_fingerprint")
    body = dict(marker)
    body.pop("stage_21a_finalization_fingerprint", None)
    if fingerprint != _canonical_json_hash(body):
        raise Stage21BPreflightError("Stage 21A finalization fingerprint is invalid")
    if marker.get("outcome") != _STAGE21A_OUTCOME:
        raise Stage21BPreflightError("Stage 21A is not PASS")
    conditions = marker.get("conditions")
    if not isinstance(conditions, Mapping) or not conditions or not all(conditions.values()):
        raise Stage21BPreflightError("Stage 21A carries a failed condition")
    for name, expected in marker.get("evidence_content_hashes", {}).items():
        path = directory / str(name)
        if _sha256(path) != expected:
            raise Stage21BPreflightError(f"Stage 21A evidence changed: {name}")
    paths = _stage21a_source_paths(root)
    current = stable_hash({path: _sha256(root / path) for path in paths}, length=64)
    if current != marker.get("stage21a_source_fingerprint"):
        raise Stage21BPreflightError("Stage 21A source fingerprint no longer holds")
    audit = _json(directory / "cross-subject-pair-audit.json")
    if audit.get("clean") is not True or audit.get("total_pairs") != EXPECTED_PAIRS_PER_METHOD:
        raise Stage21BPreflightError("Stage 21A cross-subject audit is not clean")
    leakage = _json(directory / "no-leakage-audit.json")
    if leakage.get("pass") is not True or leakage.get("algorithm_runs_performed") != 0:
        raise Stage21BPreflightError("Stage 21A no-leakage gate failed")


def _stage21a_source_paths(root: Path) -> tuple[str, ...]:
    source = root / "src/fpbench/experiments/stage21a_finalization.py"
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "_SOURCE_PATHS"
            for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            return tuple(str(item) for item in value)
    raise Stage21BPreflightError("cannot discover Stage 21A source closure")


def _verify_predecessor_documents(
    root: Path, document: Mapping[str, Any]
) -> set[str]:
    rows = document.get("documents")
    if not isinstance(rows, list) or not rows:
        raise Stage21BPreflightError("Stage 21A predecessor binding is malformed")
    values: set[str] = set()
    for row in rows:
        path = root / str(row.get("path", ""))
        if not path.is_file():
            raise Stage21BPreflightError(f"predecessor evidence is missing: {path}")
        if _sha256(path) != row.get("sha256"):
            raise Stage21BPreflightError(
                f"predecessor evidence changed: {row.get('path')}"
            )
        if path.suffix.lower() == ".json":
            _collect_strings(_json(path), values)
    return values


def _collect_strings(value: Any, found: set[str]) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            found.add(str(key))
            _collect_strings(item, found)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _collect_strings(item, found)
    elif isinstance(value, str):
        found.add(value)


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Stage21BPreflightError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise Stage21BPreflightError(f"{path}: expected a JSON object")
    return value


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError as exc:
        raise Stage21BPreflightError(f"cannot hash {path}: {exc}") from exc


def _canonical_json_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
