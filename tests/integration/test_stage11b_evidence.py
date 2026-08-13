"""The committed Stage 11B evidence, checked without anything that produced it.

No dataset, no SDK, no licence, no JVM, no workspace and no prior result. What is
under test is whether the published documents still say what they said, whether
they are the documents this source produces, and whether the marker's verdict is
one the counts beside it support (spec section 41).

The gate is mandatory and may never skip. An evidence directory that has gone
missing is a failure here, not a skipped test: the whole point of publishing is
that a later reader finds it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fpbench.adapters.verifinger_java import identity, runtime as runtime_closure
from fpbench.experiments import stage11b_identity as frozen
from fpbench.experiments.stage11b_finalization import (
    stage11b_finalization_fingerprint,
    verify_stage11b_evidence,
)

pytestmark = pytest.mark.stage11b

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = REPOSITORY_ROOT / frozen.EVIDENCE_DIRECTORY


def document(name: str) -> dict:
    return json.loads((EVIDENCE / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def marker() -> dict:
    return document(frozen.STAGE_11B_FINALIZATION_NAME)


def test_the_evidence_verifies_against_itself_and_against_this_source() -> None:
    found = verify_stage11b_evidence(repository_root=REPOSITORY_ROOT)
    assert found["outcome"] == frozen.OUTCOME
    assert found["documents"] == len(frozen.EVIDENCE_DOCUMENTS)


def test_the_marker_fingerprints_to_the_identity_it_carries(marker) -> None:
    assert stage11b_finalization_fingerprint(marker) == (
        marker["stage_11b_finalization_fingerprint"]
    )


def test_the_stage_closed_on_six_thousand_stored_outcomes(marker) -> None:
    assert marker["expected_comparisons"] == frozen.EXPECTED_JOBS
    assert marker["stored_outcomes"] == frozen.EXPECTED_JOBS
    assert marker["missing_jobs"] == 0
    assert marker["duplicate_jobs"] == 0
    assert marker["result_set_validation_clean"] is True


def test_six_thousand_outcomes_were_required_and_not_six_thousand_scores(
    marker,
) -> None:
    """A print the extractor declines is the algorithm's behaviour, not a defect.

    The arithmetic has to close: every stored outcome is either a score or a
    counted failure, and no third category exists (spec sections 12 and 32).
    """
    assert (
        marker["successful_scores"]
        + marker["algorithm_failures"]
        + marker["infrastructure_failures"]
        == marker["stored_outcomes"]
    )
    assert marker["successful_scores"] < marker["stored_outcomes"], (
        "this run recorded algorithm failures; if that ever becomes false the "
        "claim below stops being exercised"
    )
    assert marker["algorithm_failures"] > 0


def test_no_infrastructure_failure_was_recorded(marker) -> None:
    assert marker["infrastructure_failures"] == 0


def test_the_operations_are_the_frozen_ones(marker) -> None:
    assert marker["logical_extractions"] == frozen.EXPECTED_LOGICAL_EXTRACTIONS
    assert marker["verify_invocations"] == frozen.EXPECTED_VERIFY_INVOCATIONS


def test_the_stage_is_bound_to_the_published_stage_11a_qualification(marker) -> None:
    assert marker["stage11a_fingerprint"] == (
        identity.STAGE_11A_FINALIZATION_FINGERPRINT
    )
    assert marker["stage11a_outcome"] == identity.STAGE_11A_OUTCOME


def test_the_run_is_the_canonical_one(marker) -> None:
    assert marker["reference_run_id"] == frozen.REFERENCE_RUN_ID
    assert marker["reference_pair_manifest_hash"] == (
        frozen.REFERENCE_PAIR_MANIFEST_HASH
    )
    assert marker["preparation_set_id"] == frozen.PREPARATION_SET_ID
    assert marker["canonical_prepared_set_exact"] is True
    assert marker["pair_manifest_exact"] is True


def test_the_marker_denies_everything_this_stage_may_not_do(marker) -> None:
    for field in (
        "threshold_produced",
        "decision_profile_produced",
        "calibration_performed",
        "metrics_produced",
        "score_statistics_published",
        "algorithm_ranking_published",
        "prior_algorithm_scores_consulted",
        "third_party_bytes_added_to_git",
        "secrets_added_to_git",
        "absolute_paths_in_evidence",
        "opens_common_calibration",
    ):
        assert marker[field] is False, field


def test_a_finished_algorithm_4_opens_the_next_search_and_no_calibration(
    marker,
) -> None:
    """Four raw result sets is not a ranking (spec sections 35 and 36)."""
    assert marker["opens_algorithm_5_search"] is True
    assert marker["opens_common_calibration"] is False


def test_the_production_smoke_passed_on_fixtures_that_are_not_sd300(marker) -> None:
    smoke = marker["production_adapter_smoke"]
    assert smoke["outcome"] == "PASS"
    assert smoke["sd300_used"] is False
    assert smoke["scores_produced"] <= frozen.SMOKE_MAX_SCORES

    published = document(frozen.SMOKE_REPORT_NAME)
    assert published["benchmark_scores_produced"] == 0
    assert all(published["claims"].values())


def test_the_runtime_closure_is_complete_and_pinned(marker) -> None:
    binding = document("runtime-binding.json")
    assert marker["runtime_manifest_fingerprint"] == (
        binding["runtime_manifest_fingerprint"]
    )
    assert binding["closure"]["components"] == len(runtime_closure.CLOSURE_PATHS) == 17
    assert binding["closure"]["native_libraries"] == 7
    assert binding["closure"]["model_data_files"] == 2
    assert binding["closure"]["classpath_jars"] == 8
    assert len(binding["components"]) == 17
    assert marker["all_loaded_components_verified"] is True


def test_no_published_component_names_a_machine(marker) -> None:
    binding = document("runtime-binding.json")
    for component in binding["components"]:
        relative = component["relative_path"]
        assert not relative.startswith("/")
        assert ":" not in relative
        assert len(component["sha256"]) == 64
        assert component["size_bytes"] > 0


def test_the_published_operational_summary_carries_no_score_statistic() -> None:
    """Checked by key, at any depth, rather than by scanning for substrings.

    A substring scan reads ``jvm_processes`` as an ROC curve and the timing
    ``median`` as a score median. The distinction that matters is what a *key*
    means: this document may carry a median latency and may not carry a median
    score (spec section 33).
    """
    from fpbench.experiments.stage11b_finalization import _forbidden_keys

    summary = document(frozen.OPERATIONAL_SUMMARY_NAME)
    assert summary["score_statistics_published"] is False
    assert summary["biometric_metrics_published"] is False
    assert summary["threshold_produced"] is False
    assert summary["calibration_performed"] is False
    assert _forbidden_keys(summary) == set()
    # The one median it does carry is a duration, in milliseconds.
    assert summary["timings"]["adapter_ms"]["median"] > 0


def test_the_engine_statuses_include_scores_read_below_the_vendor_threshold() -> None:
    """MATCH_NOT_FOUND carries a score, and that is the whole score route.

    A run where every score came back under ``OK`` would not have exercised the
    one thing Stage 11A established: that the number is separate from the
    sample's own threshold of 48 (spec section 10).
    """
    summary = document(frozen.OPERATIONAL_SUMMARY_NAME)
    statuses = summary["outcomes"]["engine_statuses"]
    assert set(statuses) <= {"OK", "MATCH_NOT_FOUND", "BAD_OBJECT"}
    assert statuses.get("MATCH_NOT_FOUND", 0) > 0
    scored = statuses.get("OK", 0) + statuses.get("MATCH_NOT_FOUND", 0)
    assert scored == summary["outcomes"]["score_successes"]


def test_the_published_identity_is_the_one_this_source_freezes() -> None:
    profile = document("algorithm-profile.json")
    assert profile["algorithm_id"] == identity.ALGORITHM_ID
    assert profile["adapter_id"] == identity.ADAPTER_ID
    assert profile["implementation_version"] == identity.IMPLEMENTATION_VERSION
    assert profile["algorithm_profile_fingerprint"] == (
        identity.algorithm_profile_fingerprint()
    )
    assert profile["runtime"]["decision_threshold_produced_by_fpbench"] is False
    assert profile["runtime"]["official_sample_matching_threshold"] == 48


def test_the_readme_is_beside_the_documents_it_describes() -> None:
    readme = (EVIDENCE / "README.md").read_text(encoding="utf-8")
    assert frozen.OUTCOME in readme
    assert "C:\\Users" not in readme and "/home/" not in readme
