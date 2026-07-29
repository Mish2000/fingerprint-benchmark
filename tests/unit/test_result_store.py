"""Raw results are the only irreplaceable thing this project produces."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from fpbench.core.enums import (
    EnvironmentStatus,
    ExecutionStatus,
    FailureCode,
    FailureStage,
    ScoreDirection,
)
from fpbench.core.errors import ResultConflictError, StorageError
from fpbench.core.execution_models import (
    ArtifactReference,
    EnvironmentReport,
    FailureInfo,
    TimingBreakdown,
)
from fpbench.core.identifiers import CohortId, ImageId, PairId
from fpbench.core.result_models import RawResultRecord, raw_result_hash
from fpbench.execution.run_definition import (
    DEFAULT_EXECUTION_PROFILE,
    create_run_definition,
)
from fpbench.storage.result_store import ResultStore
from fakes import fake_descriptor, sha256_of

PAIR_MANIFEST_HASH = "c" * 64
COHORT = CohortId("sd300_50_subjects_test_ab12cd34")


def make_run(**overrides):
    defaults = dict(
        protocol_id="sd300_50_subjects",
        cohort_id=COHORT,
        pair_manifest_hash=PAIR_MANIFEST_HASH,
        algorithm=fake_descriptor("dummy_sha256"),
        environment=EnvironmentReport(
            status=EnvironmentStatus.READY,
            implementation_version="test-1",
            runtime={"python": "3.12.0"},
        ),
        execution_profile=DEFAULT_EXECUTION_PROFILE,
    )
    return create_run_definition(**{**defaults, **overrides})


def make_record(run, *, job_id="job_0123456789abcdef", **overrides) -> RawResultRecord:
    defaults = dict(
        result_id=job_id,
        run_id=run.run_id,
        job_id=job_id,
        job_fingerprint=sha256_of(job_id),
        protocol_id=run.protocol_id,
        cohort_id=run.cohort_id,
        pair_manifest_hash=run.pair_manifest_hash,
        pair_id=PairId("sd300a_00001000_f01_mated"),
        left_image_id=ImageId("sd300a_00001000_plain_f01"),
        right_image_id=ImageId("sd300a_00001000_roll_f01"),
        algorithm_id=run.algorithm.algorithm_id,
        algorithm_fingerprint=run.algorithm_fingerprint,
        execution_profile_id=run.execution_profile.profile_id,
        execution_profile_hash=run.execution_profile_hash,
        attempt=1,
        started_utc="2026-07-29T18:42:15.123456+00:00",
        finished_utc="2026-07-29T18:42:15.223456+00:00",
        status=ExecutionStatus.SUCCESS,
        raw_score=42.5,
        score_direction=ScoreDirection.HIGHER_IS_BETTER,
        failure=None,
        timings=TimingBreakdown(preparation_ms=1.5, adapter_ms=2.5, total_ms=5.0),
        artifacts=(),
        adapter_metadata={"generator": "test"},
        runner_metadata={"runner": "single_job_runner"},
    )
    return RawResultRecord(**{**defaults, **overrides})


@pytest.fixture
def store(tmp_path: Path) -> ResultStore:
    return ResultStore(tmp_path / "workspace")


# -------------------------------------------------------------- run manifests


def test_run_round_trips(store):
    run = make_run()
    store.ensure_run(run)
    assert store.read_run(run.run_id) == run


def test_run_manifest_lands_where_documented(store):
    run = make_run()
    store.ensure_run(run)
    assert store.run_manifest_path(run.run_id) == (
        store.root / "results" / run.run_id / "run.json"
    )
    assert store.run_manifest_path(run.run_id).is_file()


def test_ensuring_the_same_run_twice_is_a_no_op(store):
    run = make_run()
    store.ensure_run(run)
    before = store.run_manifest_path(run.run_id).read_bytes()
    store.ensure_run(run)
    assert store.run_manifest_path(run.run_id).read_bytes() == before


def test_a_different_run_under_the_same_id_is_a_conflict(store):
    run = make_run()
    store.ensure_run(run)
    impostor = replace(run, run_fingerprint="d" * 64)
    with pytest.raises(ResultConflictError):
        store.ensure_run(impostor)


def test_reading_an_unknown_run_fails_clearly(store):
    with pytest.raises(StorageError, match="run manifest not found"):
        store.read_run("run_000000000000")


def test_two_runs_coexist(store):
    first, second = make_run(), make_run(replicate_index=1)
    store.ensure_run(first)
    store.ensure_run(second)
    assert store.run_ids() == tuple(sorted((first.run_id, second.run_id)))


# -------------------------------------------------------------- raw results


def test_raw_result_record_rejects_nan():
    with pytest.raises(ValueError, match="raw_score must be finite"):
        make_record(make_run(), raw_score=float("nan"))


@pytest.mark.parametrize("raw_score", [float("inf"), float("-inf")])
def test_raw_result_record_rejects_infinity(raw_score):
    with pytest.raises(ValueError, match="raw_score must be finite"):
        make_record(make_run(), raw_score=raw_score)


def test_raw_result_record_rejects_result_id_that_differs_from_job_id():
    with pytest.raises(
        ValueError, match="result_id must equal job_id in result schema version 1"
    ):
        make_record(make_run(), result_id="job_different_result")


def test_raw_result_round_trips(store):
    run = make_run()
    store.ensure_run(run)
    record = make_record(run)
    store.write_raw_result(record)
    assert store.read_raw_result(run.run_id, record.job_id) == record


def test_a_failure_result_round_trips_with_its_structure_intact(store):
    run = make_run()
    store.ensure_run(run)
    record = make_record(
        run,
        status=ExecutionStatus.FAILURE,
        raw_score=None,
        failure=FailureInfo(
            code=FailureCode.TEMPLATE_EXTRACTION_FAILED,
            stage=FailureStage.EXTRACTION,
            message="no minutiae found",
            retryable=False,
            details={"minutiae": "0"},
        ),
    )
    store.write_raw_result(record)
    restored = store.read_raw_result(run.run_id, record.job_id)
    assert restored.failure.code is FailureCode.TEMPLATE_EXTRACTION_FAILED
    assert restored.failure.stage is FailureStage.EXTRACTION
    assert restored.failure.details == {"minutiae": "0"}
    assert restored.raw_score is None


def test_artifacts_and_component_timings_round_trip(store):
    run = make_run()
    store.ensure_run(run)
    record = make_record(
        run,
        artifacts=(
            ArtifactReference(
                artifact_id="template_left",
                kind="template",
                relative_path="artifacts/run_x/job_y/left.tpl",
                sha256=sha256_of("left"),
                size_bytes=256,
                media_type="application/octet-stream",
                metadata={"format": "ansi378"},
            ),
        ),
        timings=TimingBreakdown(
            preparation_ms=1.0,
            adapter_ms=2.0,
            total_ms=4.0,
            adapter_components_ms={"extract": 1.2, "match": 0.8},
        ),
    )
    store.write_raw_result(record)
    restored = store.read_raw_result(run.run_id, record.job_id)
    assert restored.artifacts == record.artifacts
    assert restored.timings.adapter_components_ms == {"extract": 1.2, "match": 0.8}


def test_one_row_per_job_file(store):
    import pyarrow.parquet as pq

    run = make_run()
    store.ensure_run(run)
    record = make_record(run)
    path = store.write_raw_result(record)
    assert pq.read_table(path).num_rows == 1


def test_the_write_is_atomic_and_leaves_no_temporary_file(store):
    run = make_run()
    store.ensure_run(run)
    path = store.write_raw_result(make_record(run))
    assert list(path.parent.glob("*.tmp")) == []


def test_a_stored_result_is_never_overwritten(store):
    run = make_run()
    store.ensure_run(run)
    record = make_record(run)
    store.write_raw_result(record)
    with pytest.raises(ResultConflictError):
        store.write_raw_result(record)


def test_the_store_offers_no_way_to_force_an_overwrite():
    """A deliberate absence, so it is worth asserting rather than assuming."""
    import inspect

    signature = inspect.signature(ResultStore.write_raw_result)
    assert "overwrite" not in signature.parameters
    assert "force" not in signature.parameters


def test_two_jobs_coexist_within_a_run(store):
    run = make_run()
    store.ensure_run(run)
    store.write_raw_result(make_record(run, job_id="job_00000000000000aa"))
    store.write_raw_result(make_record(run, job_id="job_00000000000000bb"))
    assert len(list(store.iter_raw_results(run.run_id))) == 2


def test_iteration_is_sorted_by_job_id(store):
    run = make_run()
    store.ensure_run(run)
    for job_id in ("job_0000000000000ccc", "job_0000000000000aaa", "job_0000000000000bbb"):
        store.write_raw_result(make_record(run, job_id=job_id))
    seen = [record.job_id for record in store.iter_raw_results(run.run_id)]
    assert seen == sorted(seen)


def test_iterating_a_run_with_no_results_yields_nothing(store):
    assert list(store.iter_raw_results("run_000000000000")) == []


# ------------------------------------------------------------------ metadata


def test_required_metadata_is_written_into_the_file(store):
    run = make_run()
    store.ensure_run(run)
    record = make_record(run)
    store.write_raw_result(record)
    metadata = store.raw_result_metadata(run.run_id, record.job_id)
    for key in (
        "schema_version",
        "result_hash",
        "run_id",
        "job_id",
        "job_fingerprint",
        "pair_manifest_hash",
        "algorithm_fingerprint",
        "execution_profile_hash",
        "fpbench_version",
        "created_utc",
        "row_count",
    ):
        assert metadata[key], f"missing metadata: {key}"
    assert metadata["row_count"] == "1"
    assert metadata["result_hash"] == raw_result_hash(record)


def test_the_result_hash_ignores_when_the_file_was_written(store, tmp_path):
    """Two stores, two write times, same record: the hash must not move."""
    run = make_run()
    record = make_record(run)
    hashes = []
    for name in ("first", "second"):
        other = ResultStore(tmp_path / name)
        other.ensure_run(run)
        other.write_raw_result(record)
        hashes.append(other.raw_result_metadata(run.run_id, record.job_id)["result_hash"])
    assert hashes[0] == hashes[1]


def test_the_result_hash_tracks_the_score(store):
    run = make_run()
    assert raw_result_hash(make_record(run, raw_score=1.0)) != raw_result_hash(
        make_record(run, raw_score=2.0)
    )


# ------------------------------------------------------------------ integrity


def test_a_corrupt_result_file_raises_a_storage_error(store):
    run = make_run()
    store.ensure_run(run)
    record = make_record(run)
    path = store.write_raw_result(record)
    path.write_bytes(b"this is not parquet")
    with pytest.raises(StorageError, match="unreadable parquet"):
        store.read_raw_result(run.run_id, record.job_id)


def test_a_corrupt_run_manifest_raises_a_storage_error(store):
    run = make_run()
    store.ensure_run(run)
    store.run_manifest_path(run.run_id).write_text("{}", encoding="utf-8")
    with pytest.raises(StorageError, match="unreadable run manifest"):
        store.read_run(run.run_id)


def test_reading_a_missing_result_raises_a_storage_error(store):
    run = make_run()
    store.ensure_run(run)
    with pytest.raises(StorageError, match="result not found"):
        store.read_raw_result(run.run_id, "job_00000000000000ff")


def test_a_record_stores_no_decision_and_no_ground_truth():
    forbidden = {
        "ground_truth",
        "protocol_stage",
        "threshold",
        "decision",
        "decision_profile",
        "local_path",
    }
    assert forbidden.isdisjoint(RawResultRecord.__dataclass_fields__)
