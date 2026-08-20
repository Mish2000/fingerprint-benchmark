"""Calibration provenance starts at verified raw-result bytes."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from fpbench.calibration import (
    LabeledResults,
    VerifiedCalibrationResults,
    build_calibration_source_binding,
    select_operating_point,
    verify_operating_point,
    verify_result_set_for_calibration,
)
from fpbench.calibration.protocol import (
    build_protected_evaluation_registry,
    impostor_ceiling_protocol,
)
from fpbench.core.calibration_errors import (
    CalibrationSourceError,
    CalibrationVerificationError,
)
from fpbench.core.calibration_models import ProtectedEvaluationIdentity
from fpbench.core.enums import (
    CalibrationPairTruth,
    CohortRole,
    GroundTruth,
    ProtectedIdentityKind,
    ProtocolStage,
)
from fpbench.core.identifiers import PairId
from fpbench.core.models import ComparisonPair
from fpbench.execution.result_set import build_result_set
from runworld import build_world

MATED = CalibrationPairTruth.MATED
IMPOSTOR = CalibrationPairTruth.CROSS_SUBJECT_IMPOSTOR


@pytest.fixture
def verified_world(tmp_path: Path):
    # Reuse the fixture's real image ids, but make the impostor comparison
    # genuinely cross-subject; the default runworld non-mated pairs are the
    # same-subject sanity population and are intentionally not calibration data.
    seed = build_world(tmp_path / "seed", research=True)
    mated = [
        pair
        for pair in seed.pairs
        if pair.protocol_stage is ProtocolStage.PLAIN_ROLL_MATED
    ]
    genuine = mated[0]
    other_subject = mated[2]
    impostor = ComparisonPair(
        pair_id=PairId("calibration_cross_subject_000"),
        dataset_id=genuine.dataset_id,
        release=genuine.release,
        left_image_id=genuine.left_image_id,
        right_image_id=other_subject.right_image_id,
        ground_truth=GroundTruth.NON_MATED,
        protocol_stage=ProtocolStage.PLAIN_ROLL_NON_MATED,
    )

    world = build_world(
        tmp_path / "calibration",
        research=True,
        pairs=(genuine, impostor),
    )
    world.executor().execute(finalize=False)
    manifest, entries = build_result_set(
        run=world.run,
        plan=world.plan,
        result_store=world.result_store,
        runtime_reference=world.runtime_reference,
    )
    records = tuple(
        world.result_store.read_raw_result(world.run.run_id, entry.job_id)
        for entry in entries
    )
    truth = {
        str(genuine.pair_id): MATED,
        str(impostor.pair_id): IMPOSTOR,
    }
    verified = verify_result_set_for_calibration(
        result_set=manifest,
        result_set_entries=entries,
        raw_results=records,
        ground_truth_by_pair_id=truth,
    )
    return world, manifest, entries, records, verified


def _binding(verified: VerifiedCalibrationResults):
    return build_calibration_source_binding(
        binding_id="verified_development_binding_v1",
        verified_results=verified,
        integration_id="synthetic_integration",
        integration_fingerprint="a" * 64,
        dataset_id="synthetic_dataset",
        dataset_fingerprint="b" * 64,
        cohort_fingerprint="c" * 64,
        cohort_role=CohortRole.DEVELOPMENT,
        pair_manifest_id="synthetic_pair_manifest",
    )


def _registry():
    return build_protected_evaluation_registry(
        registry_id="unrelated_protected_registry",
        registry_version="1",
        entries=(
            ProtectedEvaluationIdentity(
                kind=ProtectedIdentityKind.RESULT_SET,
                identity="resultset_unrelated",
                fingerprint="f" * 64,
                label="unrelated protected evaluation set",
            ),
        ),
    )


def _protocol():
    return impostor_ceiling_protocol(
        protocol_id="synthetic_allows_one_v1", numerator=1, denominator=1
    )


def _select(binding, results):
    return select_operating_point(
        _protocol(),
        binding,
        results,
        protected_registry=_registry(),
        created_source_commit="0" * 40,
        created_source_tree_clean=True,
        created_utc="2026-08-20T00:00:00Z",
    )


def test_binding_and_operating_point_carry_the_exact_verified_body(
    verified_world,
) -> None:
    _world, manifest, _entries, _records, verified = verified_world
    binding = _binding(verified)
    point = _select(binding, verified.labeled_results)

    assert binding.result_set_id == manifest.result_set_id
    assert binding.result_set_fingerprint == manifest.result_set_fingerprint
    assert binding.labeled_results_hash == verified.labeled_results.content_hash()
    assert binding.pair_ids == verified.labeled_results.pair_ids
    assert binding.ground_truth == verified.labeled_results.ground_truth
    assert point.labeled_results_hash == binding.labeled_results_hash
    assert point.pair_ids == binding.pair_ids
    assert point.ground_truth == binding.ground_truth


def test_a_raw_score_changed_under_the_same_result_set_is_refused(
    verified_world,
) -> None:
    _world, manifest, entries, records, _verified = verified_world
    changed = replace(records[0], raw_score=records[0].raw_score + 1.0)

    with pytest.raises(CalibrationSourceError, match="hashes to"):
        verify_result_set_for_calibration(
            result_set=manifest,
            result_set_entries=entries,
            raw_results=(changed, *records[1:]),
            ground_truth_by_pair_id={
                str(records[0].pair_id): MATED,
                str(records[1].pair_id): IMPOSTOR,
            },
        )


def test_the_trusted_source_type_cannot_wrap_an_arbitrary_score_body(
    verified_world,
) -> None:
    _world, _manifest, _entries, _records, verified = verified_world
    with pytest.raises(CalibrationSourceError, match="can only be produced"):
        VerifiedCalibrationResults(labeled_results=verified.labeled_results)
    with pytest.raises(CalibrationSourceError, match="requires the output"):
        build_calibration_source_binding(
            binding_id="forged_binding",
            verified_results=verified.labeled_results,
            integration_id="synthetic_integration",
            integration_fingerprint="a" * 64,
            dataset_id="synthetic_dataset",
            dataset_fingerprint="b" * 64,
            cohort_fingerprint="c" * 64,
            cohort_role=CohortRole.DEVELOPMENT,
            pair_manifest_id="synthetic_pair_manifest",
        )


def test_one_binding_cannot_verify_a_second_body_of_scores(verified_world) -> None:
    """Regression: the old implementation verified both scale 3 and scale 30."""
    _world, _manifest, _entries, _records, verified = verified_world
    original = verified.labeled_results
    binding = _binding(verified)
    point = _select(binding, original)
    scaled = LabeledResults(
        score_direction=original.score_direction,
        rows=tuple(
            replace(row, score=row.score * Decimal("10"))
            for row in original.rows
        ),
    )
    assert scaled.content_hash() != binding.labeled_results_hash

    with pytest.raises(CalibrationSourceError, match="another result set"):
        _select(binding, scaled)
    with pytest.raises(CalibrationVerificationError, match="binds labelled results"):
        verify_operating_point(
            point,
            _protocol(),
            binding,
            scaled,
            protected_registry=_registry(),
        )


@pytest.mark.parametrize("change", ["pair_id", "ground_truth"])
def test_pair_ids_and_ground_truth_are_part_of_the_bound_body(
    verified_world, change: str
) -> None:
    _world, _manifest, _entries, _records, verified = verified_world
    binding = _binding(verified)
    rows = list(verified.labeled_results.rows)
    if change == "pair_id":
        rows[0] = replace(rows[0], pair_id="different_pair")
    else:
        replacement = MATED if rows[0].truth is IMPOSTOR else IMPOSTOR
        rows[0] = replace(rows[0], truth=replacement)
    changed = LabeledResults(
        score_direction=verified.labeled_results.score_direction,
        rows=tuple(rows),
    )

    with pytest.raises(CalibrationSourceError, match="binds labelled results"):
        _select(binding, changed)
