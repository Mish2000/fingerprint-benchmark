"""The committed Stage 15A evidence, verified with nothing the stage needed.

No package, no OpenCV, no frozen runtime, no dataset, no workspace and no prior
result set. What is under test is the publication: that the tree holds exactly
the expected files, that the marker's fingerprint covers its own contents, that
the counts inside it add up, that the outcome follows from whether the result set
carries a score, and that no machine path reached any published byte.

The suite skips cleanly before the stage has published, so it can be committed
alongside the code that produces the evidence rather than after it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fpbench.experiments import stage15a_finalization as finalization
from fpbench.experiments import stage15a_identity as frozen
from fpbench.experiments.algorithm_research import REPOSITORY_ROOT

pytestmark = pytest.mark.stage15a

EVIDENCE = REPOSITORY_ROOT / frozen.EVIDENCE_DIRECTORY
MARKER = EVIDENCE / frozen.STAGE_15A_FINALIZATION_NAME


def _document(name: str) -> dict:
    path = EVIDENCE / name
    if not path.is_file():
        pytest.skip(f"{name} has not been published yet")
    return json.loads(path.read_text(encoding="utf-8"))


def _marker() -> dict:
    return _document(frozen.STAGE_15A_FINALIZATION_NAME)


# --------------------------------------------------------------- the documents


def test_the_evidence_directory_holds_only_what_this_stage_publishes() -> None:
    """Eight documents, plus the shared engine's own run receipt.

    ``run_<id>.json`` is written by the research engine rather than by this
    stage, exactly as it is for Stage 11B. It is allowed here by shape and not
    by name, because the name carries a run id that changes with the run.
    """
    if not EVIDENCE.is_dir():
        pytest.skip("Stage 15A evidence has not been published yet")
    found = {
        p.name
        for p in EVIDENCE.iterdir()
        if p.is_file() and not (p.name.startswith("run_") and p.suffix == ".json")
    }
    assert found <= set(frozen.EVIDENCE_DOCUMENTS), sorted(
        found - set(frozen.EVIDENCE_DOCUMENTS)
    )


def test_every_expected_document_is_present() -> None:
    if not MARKER.is_file():
        pytest.skip("Stage 15A has not been finalized yet")
    missing = [n for n in frozen.EVIDENCE_DOCUMENTS if not (EVIDENCE / n).is_file()]
    assert missing == []


def test_the_whole_chain_reverifies() -> None:
    if not MARKER.is_file():
        pytest.skip("Stage 15A has not been finalized yet")
    findings = finalization.verify_stage15a_evidence(repository_root=REPOSITORY_ROOT)
    assert findings["outcome"] in frozen.OUTCOMES
    assert findings["missing_documents"] == []


# ------------------------------------------------------------------- the marker


def test_the_marker_fingerprint_covers_its_own_contents() -> None:
    marker = _marker()
    assert (
        finalization.stage15a_finalization_fingerprint(marker)
        == marker["stage_15a_finalization_fingerprint"]
    )


def test_the_counts_add_up_to_six_thousand() -> None:
    marker = _marker()
    assert marker["stored_outcomes"] == frozen.EXPECTED_JOBS
    assert marker["missing_jobs"] == 0
    assert marker["duplicate_jobs"] == 0
    assert marker["infrastructure_failures"] == 0
    assert (
        marker["successful_scores"] + marker["algorithm_failures"]
        == frozen.EXPECTED_JOBS
    )
    assert marker["logical_extractions"] == frozen.EXPECTED_LOGICAL_EXTRACTIONS
    assert marker["match_invocations"] == frozen.EXPECTED_MATCH_INVOCATIONS


def test_the_outcome_follows_from_whether_a_score_exists() -> None:
    """The one property that decides whether Algorithm 5 exists."""
    marker = _marker()
    score_bearing = marker["result_set_is_score_bearing"]
    assert score_bearing == (marker["successful_scores"] > 0)
    if score_bearing:
        assert marker["outcome"] == frozen.OUTCOME_COMPLETE
        assert marker["algorithm_5_established"] is True
        assert marker["opens_common_calibration"] is True
        assert len(marker["calibration_roster"]) == 5
    else:
        assert marker["outcome"] == frozen.OUTCOME_FAIL
        assert marker["algorithm_5_established"] is False
        assert marker["opens_common_calibration"] is False
        assert marker["reopens_algorithm_5_search"] is True
        assert marker["fallback_candidate"] == frozen.RESERVE_CANDIDATE
        assert marker["calibration_roster"] == []
        assert "why_not_complete" in marker


def test_every_gate_that_was_reached_passed() -> None:
    marker = _marker()
    for gate, state in marker["gates"].items():
        assert state == "PASS", f"{gate} is {state}"


def test_the_marker_denies_every_later_layer() -> None:
    marker = _marker()
    for key in (
        "threshold_produced",
        "decision_profile_produced",
        "calibration_performed",
        "metrics_produced",
        "score_statistics_published",
        "failure_rates_published",
        "algorithm_ranking_published",
        "prior_algorithm_scores_consulted",
        "failures_recorded_as_zero",
        "score_formula_reimplemented",
        "denominator_fallback_added",
        "invented_score_for_empty_features",
        "fpbench_preprocessing_added",
        "sd300_pilot_before_the_run",
        "third_party_bytes_added_to_git",
        "secrets_added_to_git",
        "absolute_paths_in_evidence",
    ):
        assert marker[key] is False, key


def test_the_run_is_bound_to_the_reference_run() -> None:
    marker = _marker()
    assert marker["reference_run_id"] == frozen.REFERENCE_RUN_ID
    assert marker["reference_pair_manifest_hash"] == frozen.REFERENCE_PAIR_MANIFEST_HASH
    assert marker["preparation_set_id"] == frozen.PREPARATION_SET_ID
    assert marker["canonical_prepared_set_exact"] is True
    assert marker["pair_manifest_exact"] is True


# ---------------------------------------------------------------- the selection


def test_stage_14a_is_still_non_final_and_uncontacted() -> None:
    selection = _document("predecessor-selection.json")
    assert selection["stage14a_final_outcome"] == "NONE"
    assert selection["vendor_request_sent"] is False
    assert selection["stage14a_evidence_modified"] is False
    assert selection["superseded_candidate"] == frozen.SUPERSEDED_CANDIDATE


def test_the_griaule_evidence_on_disk_is_unchanged() -> None:
    """Stage 14A still publishes its request as unsent, and still has no marker."""
    directory = REPOSITORY_ROOT / "evidence" / "stage14a-griaule-preflight"
    if not directory.is_dir():
        pytest.skip("Stage 14A evidence is not present")
    assert not (directory / "stage-14a-finalization.json").exists()
    acquisition = json.loads(
        (directory / "acquisition-status.json").read_text(encoding="utf-8")
    )
    assert acquisition["request_sent"] is False


# ----------------------------------------------------------------- the identity


def test_the_runtime_closure_names_opencv_as_algorithm_identity() -> None:
    document = _document("artifact-runtime-identity.json")
    assert document["opencv_is_part_of_algorithm_identity"] is True
    assert document["pinned_environment"]["opencv_python"] == frozen.PINNED_OPENCV
    assert document["pinned_environment"]["numpy"] == frozen.PINNED_NUMPY
    assert document["opencv_generation_rule"] == frozen.OPENCV_GENERATION_RULE
    assert document["network_after_environment_creation"] == "NONE"


def test_the_published_artifacts_are_the_pinned_digests() -> None:
    document = _document("artifact-runtime-identity.json")
    digests = {a["name"]: a["expected_sha256"] for a in document["published_artifacts"]}
    assert digests[frozen.RUNTIME_ARTIFACT_NAME] == frozen.RUNTIME_ARTIFACT_SHA256
    assert digests[frozen.SOURCE_ARTIFACT_NAME] == frozen.SOURCE_ARTIFACT_SHA256


def test_the_route_contract_was_read_from_bytes_not_from_prose() -> None:
    document = _document("upstream-route-contract.json")
    assert document["read_from"] == "the installed module source, parsed"
    assert document["fpbench_adds"] == []
    assert document["argument_binding"]["denominator_argument"] == "minutiae1"
    assert document["score_contract"]["fpbench_score_transformation"] == "NONE"
    assert document["score_contract"]["decision_threshold"] == "NONE"
    assert (
        document["score_contract"]["upstream_readme_threshold_is_fpbench_threshold"]
        is False
    )


def test_the_qualification_required_determinism_and_not_symmetry() -> None:
    document = _document("qualification.json")
    assert document["determinism_required"] is True
    assert document["symmetry_required"] is False
    assert document["sd300_used"] is False
    assert document["comparisons_used"] <= frozen.QUALIFICATION_MAX_COMPARISONS
    assert document["zero_feature_policy"]["never"] == "exception → score 0"
    assert all(document["claims"].values())


def test_the_failure_breakdown_publishes_counts_and_not_rates() -> None:
    document = _document("result-integrity.json")
    breakdown = document["failure_breakdown"]
    assert breakdown["rates_published"] is False
    assert isinstance(breakdown["by_failure_code"], dict)
    assert isinstance(breakdown["by_upstream_code"], dict)


# ------------------------------------------------------------------- hygiene


def test_no_published_byte_carries_a_machine_path() -> None:
    if not EVIDENCE.is_dir():
        pytest.skip("Stage 15A evidence has not been published yet")
    for path in sorted(EVIDENCE.glob("*.json")):
        text = path.read_text(encoding="utf-8")
        for marker in ("C:\\\\", "C:/", "/home/", "/Users/"):
            assert marker not in text, f"{path.name} carries {marker}"


def test_no_published_byte_carries_a_threshold(tmp_path: Path) -> None:
    if not EVIDENCE.is_dir():
        pytest.skip("Stage 15A evidence has not been published yet")
    finalization._require_no_forbidden_published_data(EVIDENCE)
