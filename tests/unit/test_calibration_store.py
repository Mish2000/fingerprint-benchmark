"""The append-only calibration store.

Three behaviours and one of them is the point: writing a different document under
an id that already exists fails, because every id here is derived from a digest
of its own contents and a collision therefore means something that should have
been determined by its inputs was not.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from fpbench.calibration.models import LabeledResults, LabeledScore
from fpbench.calibration.protocol import (
    _seal_calibration_source_binding,
    build_calibration_operating_point,
    impostor_ceiling_protocol,
)
from fpbench.core.calibration_errors import CalibrationConflictError
from fpbench.core.enums import (
    CalibrationPairTruth,
    CalibrationTiePolicy,
    CohortRole,
    ExecutionStatus,
    ScoreDirection,
    ThresholdComparator,
    ThresholdSelectionRule,
)
from fpbench.core.errors import StorageError
from fpbench.storage.calibration_store import CalibrationStore, canonical_bytes

pytestmark = pytest.mark.stage8d_contract

HIGHER = ScoreDirection.HIGHER_IS_BETTER


def a_protocol(numerator: int = 1, denominator: int = 1000):
    return impostor_ceiling_protocol(
        protocol_id="stored_ceiling_v1", numerator=numerator, denominator=denominator
    )


def a_binding(**overrides):
    labeled_results = LabeledResults(
        score_direction=HIGHER,
        rows=(
            LabeledScore(
                pair_id="i000",
                truth=CalibrationPairTruth.CROSS_SUBJECT_IMPOSTOR,
                execution_status=ExecutionStatus.SUCCESS,
                score=Decimal("0"),
            ),
            LabeledScore(
                pair_id="m000",
                truth=CalibrationPairTruth.MATED,
                execution_status=ExecutionStatus.SUCCESS,
                score=Decimal("1"),
            ),
        ),
    )
    fields = dict(
        binding_id="stored_binding_v1",
        algorithm_id="synthetic_matcher",
        algorithm_fingerprint="a" * 64,
        integration_id="synthetic_integration",
        integration_fingerprint="b" * 64,
        run_id="run_stored01",
        run_fingerprint="c" * 64,
        result_set_id="resultset_stored01",
        result_set_fingerprint="d" * 64,
        dataset_id="stored_dataset",
        dataset_fingerprint="e" * 64,
        cohort_id="stored_dev_cohort",
        cohort_fingerprint="f" * 64,
        cohort_role=CohortRole.DEVELOPMENT,
        pair_manifest_id="stored_pairs",
        pair_manifest_fingerprint="1" * 64,
        score_direction=HIGHER,
        labeled_results=labeled_results,
    )
    fields.update(overrides)
    return _seal_calibration_source_binding(**fields)


def an_operating_point(threshold: str = "0.5"):
    return build_calibration_operating_point(
        calibration_protocol_fingerprint_value=a_protocol().protocol_fingerprint,
        source_binding_fingerprint=a_binding().source_binding_fingerprint,
        labeled_results_hash="2" * 64,
        pair_ids=("i000", "m000"),
        ground_truth=(
            CalibrationPairTruth.CROSS_SUBJECT_IMPOSTOR,
            CalibrationPairTruth.MATED,
        ),
        algorithm_id="synthetic_matcher",
        algorithm_fingerprint="a" * 64,
        threshold=Decimal(threshold),
        comparator=ThresholdComparator.GREATER_THAN_OR_EQUAL,
        score_direction=HIGHER,
        target_rate_numerator=1,
        target_rate_denominator=1000,
        observed_impostor_matches=0,
        observed_impostor_scored=1,
        observed_impostor_attempts=1,
        impostor_failures=0,
        observed_mated_matches=1,
        observed_mated_non_matches=0,
        observed_mated_scored=1,
        observed_mated_attempts=1,
        mated_failures=0,
        selection_rule=ThresholdSelectionRule.MOST_PERMISSIVE_WITHIN_IMPOSTOR_CEILING,
        tie_policy=CalibrationTiePolicy.ATOMIC_TIES_PREFER_INCLUSIVE,
        created_source_commit="0" * 40,
        created_source_tree_clean=True,
        created_utc="2026-08-07T12:00:00Z",
    )


def test_the_four_artifact_families_land_under_calibration(tmp_path: Path) -> None:
    store = CalibrationStore(root=tmp_path)
    store.write_protocol(a_protocol())
    store.write_source_binding(a_binding())
    point = an_operating_point()
    store.write_operating_point(point)
    store.write_receipt(point.operating_point_id, {"verified": True})

    root = tmp_path / "calibration"
    assert (root / "protocols" / "stored_ceiling_v1.json").is_file()
    assert (root / "source-bindings" / "stored_binding_v1.json").is_file()
    assert (
        root / "operating-points" / f"{point.operating_point_id}.json"
    ).is_file()
    assert (root / "receipts" / f"{point.operating_point_id}.json").is_file()


def test_rewriting_identical_bytes_is_an_idempotent_success(tmp_path: Path) -> None:
    """Re-running a finished calibration is how it gets verified."""
    store = CalibrationStore(root=tmp_path)
    first = store.write_operating_point(an_operating_point())
    before = first.read_bytes()
    second = store.write_operating_point(an_operating_point())
    assert first == second
    assert second.read_bytes() == before


def test_writing_different_bytes_under_one_id_is_refused(tmp_path: Path) -> None:
    store = CalibrationStore(root=tmp_path)
    point = an_operating_point()
    store.write_operating_point(point)
    # Same id on disk, different contents: forced by writing the receipt path's
    # neighbour by hand, because two different operating points cannot share an
    # id honestly — the id is derived from the contents.
    path = store.operating_point_path(point.operating_point_id)
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(CalibrationConflictError, match="never something to resolve"):
        store.write_operating_point(point)


def test_a_conflicting_protocol_is_refused(tmp_path: Path) -> None:
    store = CalibrationStore(root=tmp_path)
    store.write_protocol(a_protocol(1, 1000))
    with pytest.raises(CalibrationConflictError):
        store.write_protocol(a_protocol(1, 2000))


def test_stored_artifacts_read_back_identically(tmp_path: Path) -> None:
    store = CalibrationStore(root=tmp_path)
    protocol, binding, point = a_protocol(), a_binding(), an_operating_point()
    store.write_protocol(protocol)
    store.write_source_binding(binding)
    store.write_operating_point(point)

    assert store.read_protocol(protocol.protocol_id) == protocol
    assert store.read_source_binding(binding.binding_id) == binding
    assert store.read_operating_point(point.operating_point_id) == point


def test_reading_something_that_was_never_stored_says_so(tmp_path: Path) -> None:
    store = CalibrationStore(root=tmp_path)
    with pytest.raises(StorageError, match="not found"):
        store.read_protocol("stored_ceiling_v1")


def test_the_stored_bytes_are_the_bytes_the_conflict_check_compares(tmp_path):
    """One definition of "the same document", used by the writer and the check."""
    store = CalibrationStore(root=tmp_path)
    point = an_operating_point()
    path = store.write_operating_point(point)
    assert path.read_bytes() == canonical_bytes(point)


def test_the_inventory_lists_what_was_stored(tmp_path: Path) -> None:
    store = CalibrationStore(root=tmp_path)
    assert store.stored_operating_point_ids() == ()
    first = an_operating_point("0.5")
    second = an_operating_point("0.6")
    store.write_operating_point(first)
    store.write_operating_point(second)
    assert store.stored_operating_point_ids() == tuple(
        sorted((first.operating_point_id, second.operating_point_id))
    )


def test_the_store_has_no_method_for_the_protected_registry() -> None:
    """docs/adr/0079: the registry is a constraint on inputs, not an output.

    A per-workspace copy could drift from another workspace's, and the whole
    value of the artifact is that there is one.
    """
    assert not [
        name for name in dir(CalibrationStore) if "registry" in name.lower()
    ]
