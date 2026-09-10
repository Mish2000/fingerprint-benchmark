"""Legacy compatibility over synthetic stores only; no matcher is invoked."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from fpbench.core.enums import ExecutionStatus, FailureCode, FailureStage, ScoreDirection
from fpbench.core.errors import StorageError
from fpbench.core.execution_models import FailureInfo, TimingBreakdown
from fpbench.core.identifiers import CohortId, ImageId, PairId
from fpbench.core.result_models import RawResultRecord, raw_result_hash
from fpbench.core.result_set_models import (
    ResultSetEntry, ResultSetManifest, ordered_results_hash,
    result_set_fingerprint, result_set_id,
)
from fpbench.core.serialization import stable_hash
from fpbench.final_baseline import sources
from fpbench.final_baseline.errors import FinalBaselineError
from fpbench.final_baseline.evaluate import _inputs_document
from fpbench.stage21b.bindings import AlgorithmBinding
from fpbench.storage.manifest_store import ManifestStore
from fpbench.storage.result_set_store import ResultSetStore
from fpbench.storage.result_store import ResultStore

pytestmark = pytest.mark.final_baseline_contract
ROOT = Path(__file__).resolve().parents[2]
OPENAFIS = "nbis_mindtct_openafis_capacity_extended"
MCC = "nbis_mindtct_mcc_sdk_v2"
STAGES = ("plain_self", "roll_self", "plain_roll_mated", "plain_roll_non_mated")


def _bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _hash(payload):
    return hashlib.sha256(payload).hexdigest()


def _algorithm(algorithm_id, identity, fingerprint="a" * 64):
    return AlgorithmBinding(
        algorithm_id=algorithm_id, role="primary_baseline", display_name=algorithm_id,
        adapter_id="synthetic", integration_id=None, implementation_version="synthetic",
        score_direction="higher_is_better", predecessor_finalization_fingerprint=fingerprint,
        raw_result_identity=identity, upstream_artifact=None, upstream_commit=None,
    )


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """A synthetic, hash-verified 6,000-pair authority with 1,500 genuine pairs."""
    root = tmp_path_factory.mktemp("legacy-source-compatibility")
    workspace = root / "workspace"
    rows = [
        {
            "pair_id": f"pair_{release.lower()}_{finger:04d}_{stage}",
            "release": release, "protocol_stage": stage,
            "ground_truth": "non_mated" if stage == "plain_roll_non_mated" else "mated",
            "left_image_id": f"image_{release.lower()}_{finger:04d}_left",
            "right_image_id": f"image_{release.lower()}_{finger:04d}_right",
        }
        for release in sources.EXPECTED_RELEASES
        for finger in range(500)
        for stage in STAGES
    ]
    provenance = {
        "protocol_id": sources.LEGACY_PROTOCOL_ID, "cohort_id": sources.LEGACY_COHORT_ID,
        "image_manifest_hash": "b" * 64, "schema_version": "1",
    }
    digest = stable_hash({"provenance": provenance, "pairs": rows}, length=64)
    path = ManifestStore(workspace).pairs_path(sources.LEGACY_PROTOCOL_ID, sources.LEGACY_COHORT_ID)
    path.parent.mkdir(parents=True)
    pq.write_table(pa.Table.from_pylist(rows).replace_schema_metadata({
        **provenance, "pair_manifest_hash": digest,
    }), path)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(sources, "LEGACY_PAIR_MANIFEST_HASH", digest)
        mated = sources.load_legacy_mated_pairs(workspace)
        yield SimpleNamespace(root=root, workspace=workspace, rows=rows, digest=digest, mated=mated)


@pytest.fixture(scope="module")
def modern(world):
    """Real ResultSetStore serialization, with directly constructed synthetic records."""
    run_id, run_fingerprint = "run_synthetic", "1" * 64
    store = ResultStore(world.workspace)
    entries = []
    for ordinal, pair in enumerate(world.rows):
        job_id = f"job_{ordinal:06d}"
        failed = ordinal == world.mated[0].ordinal
        record = RawResultRecord(
            result_id=job_id, job_id=job_id, job_fingerprint="2" * 64, run_id=run_id,
            protocol_id=sources.LEGACY_PROTOCOL_ID, cohort_id=CohortId(sources.LEGACY_COHORT_ID),
            pair_manifest_hash=world.digest, pair_id=PairId(pair["pair_id"]),
            left_image_id=ImageId(pair["left_image_id"]), right_image_id=ImageId(pair["right_image_id"]),
            algorithm_id="synthetic_modern", algorithm_fingerprint="3" * 64,
            execution_profile_id="synthetic", execution_profile_hash="4" * 64, attempt=1,
            started_utc="2000-01-01T00:00:00Z", finished_utc="2000-01-01T00:00:01Z",
            status=ExecutionStatus.FAILURE if failed else ExecutionStatus.SUCCESS,
            raw_score=None if failed else 0.5, score_direction=ScoreDirection.HIGHER_IS_BETTER,
            failure=(FailureInfo(code=FailureCode.INTERNAL_ERROR, stage=FailureStage.ADAPTER,
                                 message="synthetic failure") if failed else None),
            timings=TimingBreakdown(preparation_ms=0, adapter_ms=0, total_ms=0),
        )
        store.write_raw_result(record)
        entries.append(ResultSetEntry(ordinal, job_id, raw_result_hash(record)))
    entries = tuple(entries)
    fingerprint = result_set_fingerprint(
        run_fingerprint=run_fingerprint, plan_fingerprint="5" * 64,
        runtime_bundle_fingerprint="6" * 64, entries=entries,
        success_count=5999, failure_count=1,
    )
    manifest = ResultSetManifest(
        result_set_id=result_set_id(fingerprint), result_set_fingerprint=fingerprint,
        run_id=run_id, run_fingerprint=run_fingerprint, plan_id="plan_synthetic",
        plan_fingerprint="5" * 64, runtime_bundle_id="bundle_synthetic",
        runtime_bundle_fingerprint="6" * 64, total_results=6000, success_count=5999,
        failure_count=1, ordered_results_hash=ordered_results_hash(entries),
        created_utc="2000-01-01T00:00:00Z",
    )
    ResultSetStore(world.workspace).ensure_result_set(manifest, entries)
    identity = {key: getattr(manifest, key) for key in (
        "run_id", "run_fingerprint", "result_set_id", "result_set_fingerprint",
    )}
    algorithm = _algorithm("synthetic_modern", identity)
    return algorithm


def _load(world, algorithm, root=None, mated=None):
    return sources.load_legacy_genuine_attempts(
        world.workspace, algorithm, world.mated if mated is None else mated,
        repository_root=world.root if root is None else root,
    )


@pytest.fixture
def jsonl_store(world, tmp_path, monkeypatch):
    def build(algorithm_id, *, mutation=None, evidence_mutation=None):
        immutable = algorithm_id == OPENAFIS
        stage = "19b" if immutable else "20b"
        directory = tmp_path / "evidence" / (
            "stage19b-openafis-capacity-extended" if immutable
            else "stage20b-mindtct-mcc-canonical500-raw"
        )
        directory.mkdir(parents=True, exist_ok=True)
        output = tmp_path / stage
        output.mkdir(exist_ok=True)
        path = output / "pair-outcomes.jsonl"
        rows = []
        for ordinal, pair in enumerate(world.rows):
            row = {**pair, "ordinal": ordinal, "algorithm_id": algorithm_id,
                   "stage": pair["protocol_stage"], "status": "OK",
                   "raw_score": 42 if immutable else 0.375,
                   "failure_code": None, "failure_reason": None}
            del row["protocol_stage"]
            if ordinal == world.mated[0].ordinal:
                row.update({
                    "status": "OPENAFIS_TEMPLATE_FAILED_LEFT" if immutable else "MCC_TEMPLATE_REFUSAL_LEFT",
                    "raw_score": None, "failure_code": "template_extraction_failed",
                    "failure_reason": "minutiae_below_upstream_minimum" if immutable else "invalid_raster_dimensions",
                })
            rows.append(row)
        # Diagnostics describe the intended canonical store. A structural
        # corruption can then have a correctly bound byte hash and still fail.
        counts = dict(Counter(row["status"] for row in rows))
        reasons = dict(Counter(row["failure_reason"] for row in rows if row["failure_reason"]))
        stages = [
            {"label": label, "comparisons": 1500,
             "score_bearing": sum(row["stage"] == label and row["status"] == "OK" for row in rows)}
            for label in STAGES
        ]
        if mutation:
            mutation(rows)
        path.write_bytes(b"\n".join(_bytes(row) for row in rows) + b"\n")
        digest = _hash(path.read_bytes())
        common = {
            "algorithm_id": algorithm_id, "pair_manifest_hash": world.digest,
            "preparation_set_id": sources.PREPARATION_SET_ID,
            "expected_outcomes": 6000, "stored_outcomes": 6000, "missing": 0,
        }
        binding = {**common, "score_bearing": 5999, "outcome_counts": counts,
                   "failure_reasons": reasons}
        documents = {"canonical-run-binding.json": binding}
        if immutable:
            identity = {"kind": "immutable_outcome_store_sha256", "sha256": digest}
            binding.update({"diagnostic_comparisons": 6000, "outcome_store_sha256": digest,
                            "by_protocol_stage": stages})
        else:
            identity = {"run_id": "run_stage20b_canonical500"}
            binding.update({**identity, "protocol_stages": {stage: 1500 for stage in STAGES}})
            documents["diagnostic-report.json"] = {
                **common, "overall": {"score_bearing": 5999},
                "outcome_counts": counts, "failure_reasons": reasons,
                "by_protocol_stage": [
                    {"protocol_stage": row["label"], "attempted": row["comparisons"],
                     "score_bearing": row["score_bearing"]} for row in stages
                ],
            }
            documents["result-integrity.json"] = {
                "algorithm_id": algorithm_id, "algorithm_ids_present": [algorithm_id],
                "expected_outcomes": 6000, "stored_outcomes": 6000, "score_bearing": 5999,
                "missing": 0, "duplicate_pair_ids": 0, "ordinals_are_complete": True,
                "ordinals_are_the_manifest_order": True, "scores_outside_contract": 0,
                "failures_recorded_as_zero": 0, "successes_recorded_without_a_score": 0,
            }
        if evidence_mutation:
            evidence_mutation(documents)
        hashes = {}
        for name, doc in documents.items():
            payload = _bytes(doc)
            (directory / name).write_bytes(payload)
            hashes[name] = _hash(payload)
        marker = {**common, "publication_eligible": True, "score_bearing": 5999,
                  "score_direction": "HIGHER_MORE_SIMILAR", "score_transform": "NONE",
                  "evidence_content_hashes": hashes}
        if immutable:
            marker["outcome_store_sha256"] = digest
        fingerprint = _hash(_bytes(marker))
        marker[f"stage_{stage}_finalization_fingerprint"] = fingerprint
        (directory / f"stage-{stage}-finalization.json").write_bytes(_bytes(marker))
        monkeypatch.setenv(f"FPBENCH_STAGE{stage.upper()}_ROOT", str(output))
        return SimpleNamespace(
            algorithm=_algorithm(algorithm_id, identity, fingerprint), path=path,
            root=tmp_path, evidence=directory, sha256=digest,
        )
    return build


def test_modern_exact_identity_still_verifies(world, modern):
    source = _load(world, modern)
    assert source.predecessor_raw_result_identity == modern.raw_result_identity
    assert all(source.stage21c_observed_source_identity[key] == value
               for key, value in modern.raw_result_identity.items())
    assert source.verification["raw_record_hashes_verified"] == 6000
    assert source.record_algorithm_identity == {
        "algorithm_id": "synthetic_modern", "algorithm_fingerprint": "3" * 64,
    }
    assert source.algorithm_failures == 1
    assert source.attempts[0].score is None


@pytest.mark.parametrize("field", ("run_id", "run_fingerprint", "result_set_id", "result_set_fingerprint"))
def test_modern_each_mismatched_identity_field_fails(world, modern, field):
    algorithm = replace(modern, raw_result_identity={**modern.raw_result_identity, field: "wrong_identity"})
    with pytest.raises((FinalBaselineError, StorageError)):
        _load(world, algorithm)


def test_modern_rederives_the_result_set_identity(world, modern, monkeypatch):
    original = ResultSetStore._read_entries
    def changed(store, run_id):
        entries = list(original(store, run_id))
        entries[0] = replace(entries[0], result_hash="f" * 64)
        return entries
    monkeypatch.setattr(ResultSetStore, "_read_entries", changed)
    with pytest.raises(StorageError, match="ordered results hash"):
        _load(world, modern)


def test_modern_rehashes_every_raw_record(world, modern, monkeypatch):
    original = pq.read_table
    def changed(path, *args, **kwargs):
        table = original(path, *args, **kwargs)
        if Path(path).name == "job_000000.parquet":
            rows = table.to_pylist()
            rows[0]["raw_score"] = 0.75
            return pa.Table.from_pylist(rows, schema=table.schema)
        return table
    monkeypatch.setattr(pq, "read_table", changed)
    with pytest.raises(FinalBaselineError, match="raw record does not hash"):
        _load(world, modern)


@pytest.mark.parametrize("algorithm_id", (OPENAFIS, MCC))
def test_jsonl_identity_counts_failures_and_observed_sha(world, jsonl_store, algorithm_id):
    store = jsonl_store(algorithm_id)
    source = _load(world, store.algorithm, store.root)
    assert source.predecessor_raw_result_identity == store.algorithm.raw_result_identity
    assert source.stage21c_observed_source_identity == {"kind": "outcome_store_sha256", "sha256": store.sha256}
    assert source.verification["predecessor_exact_byte_hash_bound"] is (algorithm_id == OPENAFIS)
    assert source.planned_attempts == 1500
    assert source.score_bearing_attempts == 1499
    assert source.algorithm_failures == 1
    assert source.attempts[0].status is ExecutionStatus.FAILURE
    assert source.attempts[0].score is None
    assert source.record_algorithm_identity == {"algorithm_id": algorithm_id}
    assert all(pair.pair_id == attempt.pair_id for pair, attempt in zip(world.mated, source.attempts))


def test_openafis_one_byte_mutation_refused_before_structural_loading(world, jsonl_store, monkeypatch):
    store = jsonl_store(OPENAFIS)
    store.path.write_bytes(store.path.read_bytes() + b" ")
    def forbidden(*args, **kwargs):
        pytest.fail("a changed frozen SHA must fail before reading the manifest")
    monkeypatch.setattr(sources, "load_canonical_pair_manifest", forbidden)
    with pytest.raises(FinalBaselineError, match="frozen SHA-256"):
        _load(world, store.algorithm, store.root)


@pytest.mark.parametrize("algorithm_id", (OPENAFIS, MCC))
@pytest.mark.parametrize("field,value", (
    ("algorithm_id", "wrong_algorithm"), ("pair_id", "wrong_pair"), ("ordinal", 6000),
    ("release", "SD300Z"), ("stage", "plain_roll_mated"), ("ground_truth", "non_mated"),
    ("left_image_id", "wrong_left"), ("right_image_id", "wrong_right"),
))
def test_correct_hash_cannot_hide_wrong_canonical_row(world, jsonl_store, algorithm_id, field, value):
    store = jsonl_store(algorithm_id, mutation=lambda rows: rows[0].update({field: value}))
    assert _hash(store.path.read_bytes()) == store.sha256
    with pytest.raises(FinalBaselineError, match=field):
        _load(world, store.algorithm, store.root)


@pytest.mark.parametrize("algorithm_id", (OPENAFIS, MCC))
@pytest.mark.parametrize("change", (
    {"raw_score": -1}, {"raw_score": None}, {"raw_score": True},
    {"status": "UNKNOWN"}, {"failure_code": "internal_error"},
))
def test_jsonl_uses_existing_score_and_status_contract(world, jsonl_store, algorithm_id, change):
    store = jsonl_store(algorithm_id, mutation=lambda rows: rows[0].update(change))
    with pytest.raises(FinalBaselineError):
        _load(world, store.algorithm, store.root)


@pytest.mark.parametrize("algorithm_id", (OPENAFIS, MCC))
@pytest.mark.parametrize("change", ({"raw_score": 0}, {"failure_code": None}, {"failure_reason": None}))
def test_failure_cannot_become_a_score_or_lose_its_cause(world, jsonl_store, algorithm_id, change):
    store = jsonl_store(algorithm_id, mutation=lambda rows: rows[world.mated[0].ordinal].update(change))
    with pytest.raises(FinalBaselineError):
        _load(world, store.algorithm, store.root)


@pytest.mark.parametrize("name,field,value", (
    ("canonical-run-binding.json", "run_id", "another_run"),
    ("canonical-run-binding.json", "score_bearing", 6000),
    ("canonical-run-binding.json", "protocol_stages", {}),
    ("diagnostic-report.json", "stored_outcomes", 5999),
    ("diagnostic-report.json", "outcome_counts", {"OK": 6000}),
    ("result-integrity.json", "algorithm_ids_present", ["wrong_algorithm"]),
))
def test_mcc_frozen_evidence_is_an_independent_boundary(world, jsonl_store, name, field, value):
    store = jsonl_store(MCC, evidence_mutation=lambda docs: docs[name].update({field: value}))
    with pytest.raises(FinalBaselineError):
        _load(world, store.algorithm, store.root)


def test_mcc_historical_stage_count_names_are_actually_checked(world, jsonl_store):
    def corrupt(documents):
        documents["diagnostic-report.json"]["by_protocol_stage"][0]["attempted"] = 1499
    store = jsonl_store(MCC, evidence_mutation=corrupt)
    with pytest.raises(FinalBaselineError, match="comparisons"):
        _load(world, store.algorithm, store.root)


@pytest.mark.parametrize("algorithm_id", (OPENAFIS, MCC))
def test_predecessor_document_bytes_cannot_change(world, jsonl_store, algorithm_id):
    store = jsonl_store(algorithm_id)
    path = store.evidence / "canonical-run-binding.json"
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(FinalBaselineError, match="evidence hash mismatch"):
        _load(world, store.algorithm, store.root)


@pytest.mark.parametrize("algorithm_id", (OPENAFIS, MCC))
def test_wrong_predecessor_finalization_fingerprint_fails(world, jsonl_store, algorithm_id):
    store = jsonl_store(algorithm_id)
    with pytest.raises(FinalBaselineError, match="predecessor fingerprint mismatch"):
        _load(world, replace(store.algorithm, predecessor_finalization_fingerprint="f" * 64), store.root)


@pytest.mark.parametrize("algorithm_id", (OPENAFIS, MCC))
def test_missing_legacy_source_names_required_environment_variable(world, jsonl_store, monkeypatch, algorithm_id):
    store = jsonl_store(algorithm_id)
    variable = "FPBENCH_STAGE19B_ROOT" if algorithm_id == OPENAFIS else "FPBENCH_STAGE20B_ROOT"
    monkeypatch.delenv(variable)
    with pytest.raises(FinalBaselineError, match=variable):
        _load(world, store.algorithm, store.root)
    monkeypatch.setenv(variable, str(store.root / "missing"))
    with pytest.raises(FinalBaselineError, match=variable):
        _load(world, store.algorithm, store.root)


def test_mcc_wrong_frozen_run_id_fails_without_opening_a_source(world, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("dispatch must refuse the run_id before opening files")
    monkeypatch.setattr(Path, "open", forbidden)
    with pytest.raises(FinalBaselineError, match="raw_result_identity"):
        _load(world, _algorithm(MCC, {"run_id": "wrong_run"}))


@pytest.mark.parametrize("identity", (
    {}, {"run_id": "other"}, {"sha256": "a" * 64},
    {"kind": "other", "sha256": "a" * 64},
    {"kind": "immutable_outcome_store_sha256", "sha256": "not_a_hash"},
    {"kind": "immutable_outcome_store_sha256", "sha256": "a" * 64, "extra": True},
    {"run_id": "run_stage20b_canonical500", "result_set_id": "invented"},
    {"run_id": "r", "run_fingerprint": "f", "result_set_id": "s", "result_set_fingerprint": " "},
    None,
))
def test_unknown_identity_shapes_fail_closed(identity):
    with pytest.raises(FinalBaselineError, match="raw_result_identity"):
        sources.legacy_source_format(OPENAFIS, identity)


@pytest.mark.parametrize("algorithm_id", (OPENAFIS, MCC))
def test_jsonl_method_cannot_acquire_an_invented_modern_identity(algorithm_id, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("a JSONL identity mismatch must fail without reading files")
    monkeypatch.setattr(Path, "open", forbidden)
    with pytest.raises(FinalBaselineError, match="raw_result_identity"):
        sources.legacy_source_format(algorithm_id, {
            "run_id": "run_stage20b_canonical500",
            "run_fingerprint": "a" * 64,
            "result_set_id": "resultset_synthetic",
            "result_set_fingerprint": "b" * 64,
        })


def test_all_three_routes_select_identical_1500_pairs_in_manifest_order(world, modern, jsonl_store):
    genuine = [_load(world, modern)]
    for algorithm_id in (OPENAFIS, MCC):
        store = jsonl_store(algorithm_id)
        genuine.append(_load(world, store.algorithm, store.root))
    expected = tuple(pair.pair_id for pair in world.mated)
    assert len(expected) == 1500
    assert all(tuple(attempt.pair_id for attempt in source.attempts) == expected for source in genuine)


def test_reordered_genuine_population_is_refused(world, jsonl_store):
    store = jsonl_store(MCC)
    with pytest.raises(FinalBaselineError, match="frozen mated population"):
        _load(world, store.algorithm, store.root, mated=tuple(reversed(world.mated)))


def test_bytes_extracted_are_the_bytes_the_validator_verified(world, jsonl_store, monkeypatch):
    store = jsonl_store(MCC)
    original = Path.read_bytes
    reads = 0
    def changed(path):
        nonlocal reads
        payload = original(path)
        if path == store.path:
            reads += 1
            if reads == 2:
                return payload + b" "
        return payload
    monkeypatch.setattr(Path, "read_bytes", changed)
    with pytest.raises(FinalBaselineError, match="changed during verification"):
        _load(world, store.algorithm, store.root)


def test_evaluation_input_provenance_distinguishes_mcc_observation(world, jsonl_store):
    from fpbench.baseline_evaluation.policy import load_baseline_evaluation_policy
    from fpbench.final_baseline.constants import POLICY_PATH, REPORTING_PATH
    from fpbench.final_baseline.reporting import load_final_baseline_reporting
    store = jsonl_store(MCC)
    genuine = _load(world, store.algorithm, store.root)
    policy = load_baseline_evaluation_policy(ROOT / POLICY_PATH)
    inputs = SimpleNamespace(
        repository_root=ROOT, policy=policy,
        reporting=load_final_baseline_reporting(ROOT / REPORTING_PATH, roster_method_ids=policy.roster.method_ids),
        stage21a_marker_fingerprint="a" * 64, stage21b_marker_fingerprint="b" * 64,
        binding=SimpleNamespace(legacy_pair_manifest_hash=world.digest), legacy_invariance={},
        cross_subject_pair_manifest_hash="c" * 64, cross_subject_pair_ids_sha256="d" * 64,
        methods=(SimpleNamespace(
            algorithm_id=MCC, display_name="Synthetic MCC", role="primary_baseline",
            score_direction=ScoreDirection.HIGHER_IS_BETTER, genuine=genuine,
            impostor=SimpleNamespace(run_id="synthetic", result_set_id="synthetic",
                result_set_fingerprint="e" * 64, seal_fingerprint="f" * 64,
                planned_attempts=1, score_bearing_attempts=1, algorithm_failures=0),
        ),),
    )
    # Serialize actual evaluation-input generation, without executing an evaluation.
    published = json.loads(json.dumps(_inputs_document(inputs)))["methods"][0]["legacy_genuine"]
    assert published["predecessor_raw_result_identity"] == {"run_id": "run_stage20b_canonical500"}
    assert published["stage21c_observed_source_identity"]["sha256"] == store.sha256
    assert published["verification"]["predecessor_exact_byte_hash_bound"] is False
    assert published["verification"]["predecessor_content_identity_verified"] is False
    assert published["source_locator"] == {
        "root_environment_variable": "FPBENCH_STAGE20B_ROOT", "relative_path": "pair-outcomes.jsonl",
    }
    encoded = json.dumps(published)
    assert str(store.root) not in encoded
    for field in ("run_fingerprint", "result_set_id", "result_set_fingerprint"):
        assert field not in encoded
