from __future__ import annotations

import dataclasses
import json
import shutil
import sqlite3

import pytest

from fpbench.stage21b.errors import (
    Stage21BInfrastructureInterruption,
    Stage21BIntegrityError,
    Stage21BSealedError,
    Stage21BStoreConflict,
)
from fpbench.stage21b.integrity import verify_sealed_run_directory
from fpbench.stage21b.models import Stage21BOutcomeStatus
from fpbench.stage21b.models import FrozenRunSpec
from fpbench.stage21b.preflight import _require_no_active_collision
from fpbench.stage21b.runner import Stage21BRunner
from fpbench.stage21b.store import Stage21BResultStore
from .helpers import (
    ScriptedAdapter,
    SyntheticPreparedInputs,
    algorithm_failure_classifier,
    make_pairs,
    make_spec,
    split_classifier,
)

pytestmark = pytest.mark.stage21b_contract


def _runner(tmp_path, outcomes):
    pairs = make_pairs(len(outcomes))
    adapter = ScriptedAdapter("synthetic_method", outcomes=outcomes)
    spec = make_spec(adapter, pairs)
    store = Stage21BResultStore(
        workspace=tmp_path / "workspace", spec=spec, planned_pairs=pairs
    )
    prepared = SyntheticPreparedInputs(tmp_path / "inputs", pairs)
    runner = Stage21BRunner(
        spec=spec,
        adapter=adapter,
        prepared_inputs=prepared,
        store=store,
        failure_classifier=algorithm_failure_classifier,
    )
    return pairs, adapter, spec, store, runner


def test_raw_zero_negative_and_failure_are_preserved_without_transform(tmp_path) -> None:
    pairs, adapter, _spec, store, runner = _runner(
        tmp_path, [0.0, -7.25, "failure", 12.5]
    )
    report = runner.run()
    outcomes = store.outcomes()

    assert [item.pair for item in outcomes] == list(pairs)
    assert outcomes[0].raw_score == 0.0
    assert outcomes[0].raw_score_hex == "0x0.0p+0"
    assert outcomes[1].raw_score == -7.25
    assert outcomes[1].raw_score_hex == (-7.25).hex()
    assert outcomes[2].status is Stage21BOutcomeStatus.ALGORITHM_FAILURE
    assert outcomes[2].raw_score is None
    assert outcomes[2].raw_score_hex is None
    assert outcomes[3].raw_score == 12.5
    assert adapter.calls == 4  # algorithm failure was not selectively retried
    assert all(
        seen_left != pair.left_image_id and seen_right != pair.right_image_id
        for pair, (seen_left, seen_right) in zip(pairs, adapter.seen_image_ids, strict=True)
    )
    assert report["completed_count"] == 4
    assert report["algorithm_failure_count"] == 1
    assert "raw_score" not in json.dumps(report)
    assert store.is_sealed


def test_signed_zero_has_a_distinct_lossless_serialization(tmp_path) -> None:
    _pairs, _adapter, _spec, store, runner = _runner(tmp_path, [-0.0])
    runner.run()
    assert store.outcomes()[0].raw_score_hex == "-0x0.0p+0"


def test_infrastructure_failure_stops_and_resume_runs_only_pending_pair(tmp_path) -> None:
    pairs = make_pairs(5)
    adapter = ScriptedAdapter(
        "resume_method", outcomes=[1.0, "infrastructure", 2.0, 3.0, 4.0, 5.0]
    )
    spec = make_spec(adapter, pairs)
    store = Stage21BResultStore(
        workspace=tmp_path / "workspace", spec=spec, planned_pairs=pairs
    )
    prepared = SyntheticPreparedInputs(tmp_path / "inputs", pairs)
    runner = Stage21BRunner(
        spec=spec,
        adapter=adapter,
        prepared_inputs=prepared,
        store=store,
        failure_classifier=split_classifier,
    )
    with pytest.raises(Stage21BInfrastructureInterruption):
        runner.run()
    assert store.terminal_count() == 1
    assert [pair.pair_id for pair in store.pending_pairs()] == [
        pair.pair_id for pair in pairs[1:]
    ]

    # Resume is a new preflight/batch lifecycle; the interrupted runner has
    # already closed its adapter during cleanup.
    resumed = Stage21BRunner(
        spec=spec,
        adapter=adapter,
        prepared_inputs=prepared,
        store=store,
        failure_classifier=split_classifier,
    )
    report = resumed.run()
    assert report["completed_count"] == 5
    assert report["infrastructure_events"] == 1
    assert store.is_sealed
    assert adapter.calls == 6  # one infrastructure invocation, then one valid retry


def test_cleanup_failure_prevents_seal_and_resume_does_not_rerun_outcome(
    tmp_path,
) -> None:
    class CloseFailsOnceAdapter(ScriptedAdapter):
        def __init__(self) -> None:
            super().__init__("cleanup_guard", outcomes=[17.0])
            self.close_calls = 0

        def close(self) -> None:
            self.close_calls += 1
            if self.close_calls == 1:
                raise RuntimeError("synthetic worker would not stop")

    pairs = make_pairs(1)
    adapter = CloseFailsOnceAdapter()
    spec = make_spec(adapter, pairs)
    store = Stage21BResultStore(
        workspace=tmp_path / "workspace", spec=spec, planned_pairs=pairs
    )
    prepared = SyntheticPreparedInputs(tmp_path / "inputs", pairs)
    runner = Stage21BRunner(
        spec=spec,
        adapter=adapter,
        prepared_inputs=prepared,
        store=store,
        failure_classifier=algorithm_failure_classifier,
    )

    with pytest.raises(Stage21BInfrastructureInterruption, match="cleanup failed"):
        runner.run()
    assert store.terminal_count() == 1
    assert not store.is_sealed

    resumed = Stage21BRunner(
        spec=spec,
        adapter=adapter,
        prepared_inputs=prepared,
        store=store,
        failure_classifier=algorithm_failure_classifier,
    )
    report = resumed.run()
    assert report["completed_count"] == 1
    assert store.is_sealed
    assert adapter.calls == 1
    assert adapter.close_calls == 2


def test_rejected_batch_argument_still_closes_the_preflighted_adapter(
    tmp_path,
) -> None:
    class ClosingAdapter(ScriptedAdapter):
        def __init__(self) -> None:
            super().__init__("invalid_limit_guard")
            self.close_calls = 0

        def close(self) -> None:
            self.close_calls += 1

    pairs = make_pairs(1)
    adapter = ClosingAdapter()
    spec = make_spec(adapter, pairs)
    store = Stage21BResultStore(
        workspace=tmp_path / "workspace", spec=spec, planned_pairs=pairs
    )
    runner = Stage21BRunner(
        spec=spec,
        adapter=adapter,
        prepared_inputs=SyntheticPreparedInputs(tmp_path / "inputs", pairs),
        store=store,
        failure_classifier=algorithm_failure_classifier,
    )

    with pytest.raises(ValueError, match="max_pairs"):
        runner.run(max_pairs=0)
    assert adapter.close_calls == 1
    assert adapter.calls == 0
    assert not store.is_sealed


def test_missing_pair_duplicate_and_unknown_pair_are_rejected(tmp_path) -> None:
    pairs, _adapter, _spec, store, runner = _runner(tmp_path, [1.0, 2.0])
    runner.run(max_pairs=1)
    with pytest.raises(Stage21BIntegrityError):
        store.integrity_report(require_complete=True)
    with pytest.raises(Stage21BStoreConflict):
        store.begin_attempt(pairs[0].pair_id, started_utc="2026-01-01T00:00:00+00:00")
    with pytest.raises(Stage21BStoreConflict):
        store.begin_attempt("unknown_pair", started_utc="2026-01-01T00:00:00+00:00")


def test_sealed_result_is_read_only_and_reopens_with_original_created_time(tmp_path) -> None:
    pairs, adapter, spec, store, runner = _runner(tmp_path, [4.0, 5.0])
    first = runner.run()
    fingerprint = store.verify_seal()["result_set_fingerprint"]
    later_spec = dataclasses.replace(spec, created_utc="2030-01-01T00:00:00+00:00")
    reopened = Stage21BResultStore(
        workspace=tmp_path / "workspace", spec=later_spec, planned_pairs=pairs
    )
    assert reopened.spec.created_utc == spec.created_utc
    assert reopened.verify_seal()["result_set_fingerprint"] == fingerprint
    assert reopened.seal()["result_set_fingerprint"] == fingerprint
    with pytest.raises(Stage21BSealedError):
        reopened.begin_attempt(pairs[0].pair_id, started_utc=spec.created_utc)
    verified = verify_sealed_run_directory(
        store.run_dir, require_production_shape=False
    )
    assert verified["result_set_fingerprint"] == fingerprint
    assert first["seal_status"] == "SEALED"


def test_crash_between_canonical_exports_and_seal_is_recovered_without_rerun(tmp_path) -> None:
    pairs, adapter, spec, store, runner = _runner(tmp_path, [2.0, 3.0])
    runner.run()
    fingerprint = store.verify_seal()["result_set_fingerprint"]
    store.seal_path.unlink()  # simulate power loss immediately before marker publication
    reopened = Stage21BResultStore(
        workspace=tmp_path / "workspace", spec=spec, planned_pairs=pairs
    )
    assert reopened.is_sealed
    assert reopened.verify_seal()["result_set_fingerprint"] == fingerprint
    assert adapter.calls == 2


def test_abandoned_in_progress_attempt_is_recovered_then_resumed(tmp_path) -> None:
    pairs, adapter, spec, store, runner = _runner(tmp_path, [8.0])
    _attempt_id, number = store.begin_attempt(
        pairs[0].pair_id, started_utc="2026-01-01T00:00:00+00:00"
    )
    assert number == 1
    report = runner.run()
    assert report["completed_count"] == 1
    assert report["infrastructure_events"] == 1
    assert store.outcomes()[0].attempt == 2


def test_plan_binding_rejects_changed_preparation_reference_before_execution(tmp_path) -> None:
    pairs = make_pairs(2)
    adapter = ScriptedAdapter("plan_guard")
    spec = make_spec(adapter, pairs)
    changed_reference = dataclasses.replace(
        pairs[0].left_preparation, preparation_entry_hash="f" * 64
    )
    changed_pairs = (
        dataclasses.replace(pairs[0], left_preparation=changed_reference),
        pairs[1],
    )
    with pytest.raises(Stage21BStoreConflict, match="closure differs"):
        Stage21BResultStore(
            workspace=tmp_path / "workspace", spec=spec, planned_pairs=changed_pairs
        )


def test_wrong_preparation_reference_becomes_infrastructure_gap_not_failure(tmp_path) -> None:
    pairs = make_pairs(1)
    adapter = ScriptedAdapter("prep_guard", outcomes=[1.0])
    spec = make_spec(adapter, pairs)
    store = Stage21BResultStore(
        workspace=tmp_path / "workspace", spec=spec, planned_pairs=pairs
    )
    prepared = SyntheticPreparedInputs(tmp_path / "inputs", pairs)
    prepared.images[pairs[0].left_image_id] = dataclasses.replace(
        prepared.images[pairs[0].left_image_id],
        preparation_entry_hash="0" * 64,
    )
    runner = Stage21BRunner(
        spec=spec,
        adapter=adapter,
        prepared_inputs=prepared,
        store=store,
        failure_classifier=algorithm_failure_classifier,
    )
    with pytest.raises(Stage21BInfrastructureInterruption):
        runner.run()
    assert store.terminal_count() == 0
    assert store.status_report()["algorithm_failure_count"] == 0


def test_run_spec_refuses_any_evaluation_permission() -> None:
    pairs = make_pairs(1)
    adapter = ScriptedAdapter("flags_guard")
    spec = make_spec(adapter, pairs)
    with pytest.raises(ValueError, match="metrics_allowed"):
        dataclasses.replace(spec, metrics_allowed=True)


def test_resume_refuses_a_tampered_existing_terminal_record(tmp_path) -> None:
    pairs, _adapter, spec, store, runner = _runner(tmp_path, [3.5, 4.5])
    runner.run(max_pairs=1)
    with sqlite3.connect(store.database_path) as connection:
        connection.execute(
            "UPDATE terminal_outcomes SET outcome_hash=? WHERE pair_id=?",
            ("0" * 64, pairs[0].pair_id),
        )
        connection.commit()

    with pytest.raises(Stage21BIntegrityError, match="outcome hash"):
        Stage21BResultStore(
            workspace=tmp_path / "workspace", spec=spec, planned_pairs=pairs
        )


def test_changed_stage21a_identity_needs_explicit_supersession(tmp_path) -> None:
    pairs = make_pairs(1)
    adapter = ScriptedAdapter("stage21a_guard")
    first_spec = make_spec(adapter, pairs)
    store = Stage21BResultStore(
        workspace=tmp_path / "workspace", spec=first_spec, planned_pairs=pairs
    )
    changed = first_spec.semantic_payload()
    changed.pop("schema_version")
    changed.pop("stage")
    changed["stage21a_finalization_fingerprint"] = "f" * 64
    second_spec = FrozenRunSpec.create(
        created_utc="2026-02-01T00:00:00+00:00", **changed
    )

    with pytest.raises(Stage21BStoreConflict, match="explicit supersession"):
        _require_no_active_collision(
            tmp_path / "workspace", adapter.descriptor.algorithm_id, second_spec.run_id
        )
    store.supersede(
        reason="accepted Stage 21A identity changed before matcher execution",
        superseded_by_run_id=second_spec.run_id,
    )
    _require_no_active_collision(
        tmp_path / "workspace", adapter.descriptor.algorithm_id, second_spec.run_id
    )


def test_resume_refuses_a_run_directory_holding_a_different_run_spec(tmp_path) -> None:
    """The directory is addressed by the spec's own fingerprint, so a mismatch
    can only arise from a hand-edited or half-copied workspace — and that is
    exactly the resume that must not silently continue."""
    pairs = make_pairs(2)
    adapter = ScriptedAdapter("spec_guard")
    first_spec = make_spec(adapter, pairs)
    workspace = tmp_path / "workspace"
    first = Stage21BResultStore(
        workspace=workspace, spec=first_spec, planned_pairs=pairs
    )

    changed = first_spec.semantic_payload()
    changed.pop("schema_version")
    changed.pop("stage")
    changed["stage21a_source_fingerprint"] = "e" * 64
    second_spec = FrozenRunSpec.create(
        created_utc="2026-03-01T00:00:00+00:00", **changed
    )
    intruder = workspace / "stage21b" / second_spec.algorithm_id / second_spec.run_id
    intruder.mkdir(parents=True)
    shutil.copyfile(first.spec_path, intruder / "run-spec.json")

    with pytest.raises(Stage21BStoreConflict, match="different frozen run spec"):
        Stage21BResultStore(
            workspace=workspace, spec=second_spec, planned_pairs=pairs
        )


def test_resume_recovers_a_schema_only_interrupted_checkpoint(tmp_path) -> None:
    pairs = make_pairs(3)
    adapter = ScriptedAdapter("initialisation_resume")
    spec = make_spec(adapter, pairs)
    workspace = tmp_path / "workspace"
    first = Stage21BResultStore(
        workspace=workspace, spec=spec, planned_pairs=pairs
    )
    with sqlite3.connect(first.database_path) as connection:
        connection.execute("DELETE FROM planned_pairs")
        connection.execute("DELETE FROM metadata")

    reopened = Stage21BResultStore(
        workspace=workspace, spec=spec, planned_pairs=pairs
    )
    assert reopened.terminal_count() == 0
    assert [pair.pair_id for pair in reopened.pending_pairs()] == [
        pair.pair_id for pair in pairs
    ]
    with sqlite3.connect(reopened.database_path) as connection:
        metadata = dict(connection.execute("SELECT key,value FROM metadata"))
        assert metadata["run_id"] == spec.run_id
        assert connection.execute("SELECT COUNT(*) FROM planned_pairs").fetchone()[
            0
        ] == len(pairs)


def test_resume_refuses_a_partially_empty_checkpoint(tmp_path) -> None:
    pairs = make_pairs(2)
    adapter = ScriptedAdapter("partial_initialisation_guard")
    spec = make_spec(adapter, pairs)
    workspace = tmp_path / "workspace"
    first = Stage21BResultStore(
        workspace=workspace, spec=spec, planned_pairs=pairs
    )
    with sqlite3.connect(first.database_path) as connection:
        connection.execute("DELETE FROM metadata")

    with pytest.raises(Stage21BStoreConflict, match="different frozen run"):
        Stage21BResultStore(
            workspace=workspace, spec=spec, planned_pairs=pairs
        )
