"""Evidence-only verification for the Stage 21A protocol freeze."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from fpbench.experiments.stage21a_finalization import (
    EVIDENCE_DIRECTORY,
    EVIDENCE_DOCUMENTS,
    FINALIZATION_NAME,
    LEGACY_PAIR_MANIFEST_HASH,
    OUTCOME,
    stage21a_source_fingerprint,
    verify_stage21a_evidence,
)

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / EVIDENCE_DIRECTORY
pytestmark = pytest.mark.stage21a


def _read(name: str) -> dict:
    return json.loads((DIRECTORY / name).read_text(encoding="utf-8"))


def test_the_complete_evidence_gate_verifies_without_a_workspace() -> None:
    marker = verify_stage21a_evidence(ROOT)
    assert marker["outcome"] == OUTCOME


def test_the_evidence_directory_contains_exactly_the_frozen_documents() -> None:
    present = sorted(path.name for path in DIRECTORY.iterdir() if path.is_file())
    assert present == sorted((*EVIDENCE_DOCUMENTS, FINALIZATION_NAME))


def test_the_marker_covers_every_evidence_byte_and_its_own_fields() -> None:
    marker = _read(FINALIZATION_NAME)
    for name, digest in marker["evidence_content_hashes"].items():
        assert hashlib.sha256((DIRECTORY / name).read_bytes()).hexdigest() == digest
    fingerprint = marker.pop("stage_21a_finalization_fingerprint")
    encoded = json.dumps(
        marker, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    assert hashlib.sha256(encoded).hexdigest() == fingerprint


def test_the_marker_covers_the_stage21a_source_tree() -> None:
    marker = _read(FINALIZATION_NAME)
    assert marker["stage21a_source_fingerprint"] == stage21a_source_fingerprint(ROOT)
    assert marker["source_tree_clean"] is True
    assert marker["failed_conditions"] == []
    assert all(marker["conditions"].values())


def test_the_roster_contains_five_primary_methods_plus_openafis() -> None:
    roster = _read("baseline-roster.json")
    assert roster["method_count"] == 6
    assert roster["more_than_five_allowed_by_user_correction"] is True
    assert roster["score_values_read_for_roster"] is False
    methods = roster["methods"]
    assert [method["algorithm_id"] for method in methods] == [
        "sourceafis_java",
        "nbis_mindtct_bozorth3",
        "flx_deepprint_texminu_512_without_localization",
        "verifinger_1to1",
        "nbis_mindtct_mcc_sdk_v2",
        "nbis_mindtct_openafis_capacity_extended",
    ]
    assert sum(method["role"] == "primary_baseline" for method in methods) == 5
    assert methods[-1]["role"] == "additional_experimentally_evaluated_method"
    for method in methods:
        assert method["attempts"] == 6_000
        assert method["score_bearing_results"] + method["algorithm_failures"] == 6_000
        assert method["pair_manifest_hash"] == LEGACY_PAIR_MANIFEST_HASH
        assert method["canonical_preparation_set_id"] == "prepset_be560e047991"
        assert method["score_direction"] == "higher_is_better"
        assert len(method["finalization_fingerprint"]) == 64
        assert method["raw_result_identity"]


def test_the_low_coverage_stage15_route_is_explicitly_accounted_for() -> None:
    excluded = _read("baseline-roster.json")["excluded_completed_routes"]
    assert len(excluded) == 1
    assert excluded[0]["algorithm_id"] == "fingerprints_matching_0_1_0"
    assert excluded[0]["score_values_read_for_exclusion"] is False
    assert excluded[0]["attempts"] == 6_000
    assert excluded[0]["score_bearing_results"] == 389


def test_the_legacy_manifest_is_exactly_invariant() -> None:
    legacy = _read("legacy-protocol-invariance.json")
    assert legacy["pass"] is True
    assert legacy["count"] == 6_000
    assert legacy["pair_manifest_hash"] == LEGACY_PAIR_MANIFEST_HASH
    assert legacy["manifest_self_hash_recomputed"] == LEGACY_PAIR_MANIFEST_HASH
    assert legacy["all_pair_ids_unchanged"] is True
    assert legacy["ordering_unchanged"] is True
    assert legacy["generator_regeneration_exact"] is True


def test_the_cross_subject_manifest_has_exact_shape_and_no_violation() -> None:
    audit = _read("cross-subject-pair-audit.json")
    assert audit["clean"] is True
    assert audit["total_pairs"] == 73_500
    assert audit["release_counts"] == {
        "SD300A": 24_500,
        "SD300B": 24_500,
        "SD300C": 24_500,
    }
    assert all(
        set(per_release.values()) == {2_450}
        for per_release in audit["pairs_per_finger_per_release"].values()
    )
    for key in (
        "pairs_with_same_subject",
        "pairs_with_different_finger_position",
        "cross_release_pairs",
        "duplicate_pair_ids",
        "legacy_pair_id_collisions",
        "unknown_subjects",
        "unknown_images",
        "left_appearance_violations",
        "right_appearance_violations",
    ):
        assert audit[key] == 0
    assert audit["expected_appearances_per_side_per_subject_per_release"] == 490


def test_the_evaluation_policy_is_reporting_and_never_calibration() -> None:
    policy = _read("evaluation-policy.json")
    assert policy["allowed_biometric_metrics"] == ["TAR", "FAR", "FRR"]
    assert policy["primary_view"] == "all_planned_attempts"
    assert policy["self_eligibility_filtering"] is False
    assert policy["primary_far_target"] == "1/1000"
    assert set(policy["far_targets"]) == {"1/100", "1/1000", "1/10000"}
    for field in (
        "score_normalization",
        "cross_algorithm_raw_score_comparison",
        "interpolation",
        "calibration_performed",
        "operational_threshold_created",
        "threshold_profile_created",
        "algorithm_parameters_changed",
    ):
        assert policy[field] is False
    assert policy["ties_move_together"] is True
    assert policy["common_score_secondary"] is True


def test_no_leakage_or_algorithm_run_entered_the_freeze() -> None:
    audit = _read("no-leakage-audit.json")
    assert audit["pass"] is True
    false_fields = [
        key
        for key in audit
        if key not in {"kind", "algorithm_runs_performed", "new_results_computed", "pass"}
    ]
    assert all(audit[key] is False for key in false_fields)
    assert audit["algorithm_runs_performed"] == 0
    assert audit["new_results_computed"] == 0


def test_the_future_1000ppi_test_lane_is_protected() -> None:
    artifact = _read("high-resolution-test-reservation.json")
    reservation = artifact["reservation"]
    assert artifact["frozen"] is True
    assert reservation["primary_release"] == "SD300B"
    assert reservation["native_ppi"] == 1000
    assert reservation["cohort_role"] == "future_test"
    assert reservation["training_allowed"] is False
    assert reservation["parameter_tuning_allowed"] is False
    assert reservation["threshold_tuning_allowed"] is False
    assert reservation["supplementary_release"]["independent_development_set"] is False
    assert reservation["legacy_lane"]["changed_by_this_reservation"] is False
