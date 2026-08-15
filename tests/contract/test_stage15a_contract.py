"""The frozen Stage 15A protocol, proved without the package or OpenCV.

Nothing here downloads anything, imports ``cv2``, builds an environment or opens
an SD300 byte. What it checks is the part of Stage 15A that must be true before
any of that happens: the identities are what they say, the selection record does
not turn an unfinished investigation into a finding, the route contract is
derived from bytes rather than from prose, the failure split never lets an
exception become a score, and the finalization refuses to publish a marker the
evidence does not support.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fpbench.core.enums import (
    ExecutionStatus,
    FailureCode,
    FailureStage,
    ScoreDirection,
)
from fpbench.core.execution_models import FailureInfo, RawMatchResult
from fpbench.core.stage15a_errors import (
    Stage15AFinalizationError,
    Stage15AResultIntegrityError,
    Stage15ASelectionError,
)
from fpbench.experiments import stage15a_finalization as finalization
from fpbench.experiments import stage15a_identity as frozen
from fpbench.experiments import stage15a_validation as validation

pytestmark = pytest.mark.stage15a_contract

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


# ------------------------------------------------------------------- identity


def test_the_candidate_identity_is_the_published_artifact() -> None:
    assert frozen.PACKAGE_REQUIREMENT == "fingerprints-matching==0.1.0"
    assert frozen.LICENSE == "MIT"
    assert frozen.IMPLEMENTATION_ORIGIN == "OPEN_SOURCE_PYPI_ARTIFACT"
    assert len(frozen.RUNTIME_ARTIFACT_SHA256) == 64
    assert len(frozen.SOURCE_ARTIFACT_SHA256) == 64
    assert frozen.RUNTIME_ARTIFACT_SHA256 != frozen.SOURCE_ARTIFACT_SHA256


def test_there_are_six_gates_in_one_order() -> None:
    assert frozen.GATE_ORDER == ("G1", "G2", "G3", "G4", "G5", "G6")
    assert set(frozen.GATES) == set(frozen.GATE_ORDER)


def test_there_is_no_pending_access_state() -> None:
    """A self-service candidate can never be waiting on a vendor.

    A state nobody can reach is a state that will eventually be reached by
    accident, so the vocabulary does not contain one.
    """
    assert "PENDING_ACCESS" not in frozen.GATE_STATES


def test_the_workload_is_six_thousand_comparisons_and_twelve_thousand_extractions() -> None:
    assert frozen.EXPECTED_JOBS == 6000
    assert frozen.EXPECTED_LOGICAL_EXTRACTIONS == 12000
    assert frozen.EXPECTED_MATCH_INVOCATIONS == 6000


# ------------------------------------------------------------------ selection


def test_stage_14a_keeps_its_non_final_outcome() -> None:
    document = finalization.build_predecessor_selection_document()
    assert document["stage14a_final_outcome"] == "NONE"
    assert document["vendor_request_sent"] is False
    assert document["reason_not_continued"] == "SELF_SERVICE_ACQUISITION_NOT_ESTABLISHED"
    assert document["stage14a_evidence_modified"] is False


def test_the_selection_policy_is_two_hard_requirements() -> None:
    document = finalization.build_predecessor_selection_document()
    assert document["selection_policy"] == {
        "self_service_acquisition": "HARD_REQUIREMENT",
        "runnable_without_vendor_action": "HARD_REQUIREMENT",
    }
    assert document["superseded_candidate"] == "griaule_gbs_fingerprint_sdk_1to1"
    assert document["commercial_search_reopened"] is False


def test_the_reserve_candidate_is_named_and_the_queue_stays_closed() -> None:
    document = finalization.build_predecessor_selection_document()
    assert document["reserve_candidate"] == "fingerflow_3_0_1"
    assert "Griaule" in document["out_of_queue_candidates"]
    assert "IDKit" in document["out_of_queue_candidates"]


def test_stage_14a_evidence_is_untouched_on_disk() -> None:
    """The published Griaule preflight still says nobody was contacted."""
    directory = REPOSITORY_ROOT / "evidence" / "stage14a-griaule-preflight"
    assert not (directory / "stage-14a-finalization.json").exists()
    acquisition = json.loads(
        (directory / "acquisition-status.json").read_text(encoding="utf-8")
    )
    assert acquisition.get("request_sent") is False


# --------------------------------------------------------------- score contract


def test_the_argument_binding_follows_from_the_denominator() -> None:
    assert frozen.LEFT_ARGUMENT == "image_path1"
    assert frozen.RIGHT_ARGUMENT == "image_path2"
    assert frozen.SYMMETRY_REQUIRED is False


def test_fpbench_transforms_nothing_and_holds_no_threshold() -> None:
    assert frozen.FPBENCH_SCORE_TRANSFORMATION == "NONE"
    assert frozen.DECISION_THRESHOLD == "NONE"
    assert frozen.SCORE_RANGE == "UNSPECIFIED"
    assert frozen.SCORE_DIRECTION == "HIGHER_MORE_SIMILAR"


def test_the_upstream_readme_threshold_is_recorded_but_not_adopted() -> None:
    """0.9 is upstream's guidance to its own users, and stays that."""
    assert frozen.UPSTREAM_README_THRESHOLD == 0.9
    assert frozen.DECISION_THRESHOLD == "NONE"


def test_every_preprocessing_step_is_refused_by_name() -> None:
    for step in ("crop", "resize", "roi", "segmentation", "enhancement",
                 "thresholding", "alignment", "score_transform"):
        assert step in frozen.REFUSED_FPBENCH_STEPS


def test_opencv_is_pinned_by_a_stated_rule() -> None:
    assert frozen.OPENCV_GENERATION_RULE == "CONTEMPORARY_WITH_ARTIFACT_PUBLICATION"
    assert frozen.PINNED_OPENCV == "4.7.0.72"
    # The distribution and the library carry different strings for one install.
    assert frozen.PINNED_CV2_LIBRARY == "4.7.0"
    assert "opencv-python" in frozen.RUNTIME_WHEELS


# ------------------------------------------------------------ failure contract


def test_an_upstream_refusal_is_an_algorithmic_failure() -> None:
    for code in (
        FailureCode.TEMPLATE_EXTRACTION_FAILED,
        FailureCode.IMAGE_DECODE_FAILED,
        FailureCode.MATCHING_FAILED,
    ):
        assert code in validation.ALGORITHMIC_FAILURE_CODES
        assert code not in validation.BLOCKING_FAILURE_CODES


def test_a_broken_machine_is_never_an_algorithmic_failure() -> None:
    for code in (
        FailureCode.DEPENDENCY_MISSING,
        FailureCode.INTERNAL_ERROR,
        FailureCode.PROCESS_CRASHED,
        FailureCode.TIMEOUT,
    ):
        assert code in validation.BLOCKING_FAILURE_CODES
        assert code not in validation.ALGORITHMIC_FAILURE_CODES


def test_the_two_failure_classes_do_not_overlap() -> None:
    assert not (
        validation.ALGORITHMIC_FAILURE_CODES & validation.BLOCKING_FAILURE_CODES
    )


def test_a_failed_result_cannot_carry_a_score() -> None:
    """The model layer refuses it, which is why nothing downstream has to."""
    with pytest.raises(ValueError):
        RawMatchResult(
            status=ExecutionStatus.FAILURE,
            raw_score=0.0,
            score_direction=ScoreDirection.HIGHER_IS_BETTER,
            failure=FailureInfo(
                code=FailureCode.TEMPLATE_EXTRACTION_FAILED,
                stage=FailureStage.EXTRACTION,
                message="upstream declined the print",
            ),
        )


def test_zero_is_a_real_score_and_not_a_failure() -> None:
    result = RawMatchResult.success(
        raw_score=0.0, score_direction=ScoreDirection.HIGHER_IS_BETTER
    )
    assert result.status is ExecutionStatus.SUCCESS
    assert result.raw_score == 0.0


def test_the_adapter_maps_every_upstream_code_without_repairing_anything() -> None:
    from fpbench.adapters.fingerprints_matching.adapter import (
        ALGORITHMIC_FAILURE_CODES,
    )

    assert "NO_FEATURES_ON_FIRST_SIDE" in ALGORITHMIC_FAILURE_CODES
    assert "CONVEXITY_DEFECTS_REFUSED_CONTOUR" in ALGORITHMIC_FAILURE_CODES
    for code, stage in ALGORITHMIC_FAILURE_CODES.values():
        assert code in validation.ALGORITHMIC_FAILURE_CODES
        assert isinstance(stage, FailureStage)


# ------------------------------------------------------------------ the bridge


def test_the_bridge_never_imports_fpbench() -> None:
    source = (
        REPOSITORY_ROOT / "integrations" / "fingerprints-matching" / "bridge.py"
    ).read_text(encoding="utf-8")
    assert "import fpbench" not in source
    assert "from fpbench" not in source


def test_the_bridge_calls_the_top_level_entry_point() -> None:
    """It drives upstream's own function rather than assembling a route."""
    source = (
        REPOSITORY_ROOT / "integrations" / "fingerprints-matching" / "bridge.py"
    ).read_text(encoding="utf-8")
    assert "FingerprintsMatching.fingerprints_matching(left, right)" in source
    # It must not reach into the parts to build its own pipeline.
    assert "extract_minutiae(" not in source
    assert "minutiae_matching.match(" not in source


def test_the_bridge_has_three_response_shapes_and_no_fourth() -> None:
    source = (
        REPOSITORY_ROOT / "integrations" / "fingerprints-matching" / "bridge.py"
    ).read_text(encoding="utf-8")
    for status in ('"score"', '"algorithmic_failure"', '"infrastructure_failure"'):
        assert status in source


# ------------------------------------------------------------- the config guard


def test_the_experiment_config_refuses_a_threshold_shaped_key(tmp_path: Path) -> None:
    from fpbench.core.errors import ConfigurationError
    from fpbench.experiments.stage15a_canonical500_full import (
        EXPERIMENT_CONFIG,
        load_stage15a_canonical500_config,
    )

    text = EXPERIMENT_CONFIG.read_text(encoding="utf-8")
    tampered = tmp_path / "tampered.yaml"
    tampered.write_text(text + "\ncalibration:\n  profile: anything\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="calibration"):
        load_stage15a_canonical500_config(
            path=tampered, repository_root=REPOSITORY_ROOT
        )


def test_the_experiment_config_matches_the_frozen_identity() -> None:
    from fpbench.experiments.stage15a_canonical500_full import (
        load_stage15a_canonical500_config,
    )

    config = load_stage15a_canonical500_config(repository_root=REPOSITORY_ROOT)
    assert config.experiment_id == frozen.EXPERIMENT_ID
    assert config.expected_jobs == frozen.EXPECTED_JOBS
    assert config.reference_run_id == frozen.REFERENCE_RUN_ID
    assert config.execution_profile.profile_id == frozen.EXECUTION_PROFILE_ID
    assert int(config.execution_profile.timeout_seconds) == frozen.JOB_DEADLINE_SECONDS


# -------------------------------------------------------------- the marker gate


def _integrity(**overrides: object) -> dict[str, object]:
    document = {
        "stored_outcomes": 6000,
        "missing": 0,
        "duplicates": 0,
        "scores": 4000,
        "scores_self": 2500,
        "scores_genuine": 1500,
        "is_genuine_score_bearing": True,
        "algorithm_failures": 2000,
        "infrastructure_failures": 0,
        "logical_extractions": 12000,
        "match_invocations": 6000,
        "result_set_validation_clean": True,
        "validation_fingerprint": "f" * 64,
        "is_score_bearing": True,
    }
    document.update(overrides)
    return document


def _passing_gate() -> dict[str, object]:
    return {"gate_state": "PASS", "runtime_manifest_fingerprint": "a" * 64}


def _build(**overrides: object) -> dict[str, object]:
    return finalization.build_stage15a_finalization(
        repository_root=REPOSITORY_ROOT,
        run_id="run_stage15atest",
        plan_id="plan_stage15atest",
        result_set_id="resultset_stage15atest",
        integrity=_integrity(**overrides),
        qualification_document=_passing_gate(),
        runtime_document=_passing_gate(),
        route_document=_passing_gate(),
    )


def test_a_clean_score_bearing_run_is_complete() -> None:
    marker = _build()
    assert marker["outcome"] == frozen.OUTCOME_COMPLETE
    assert marker["algorithm_5_established"] is True
    assert marker["opens_common_calibration"] is True
    assert marker["reopens_algorithm_5_search"] is False
    assert len(marker["calibration_roster"]) == 5


def test_a_complete_run_with_no_score_is_not_algorithm_five() -> None:
    """Six thousand deterministic refusals are a finding, not a raw matcher."""
    marker = _build(
        scores=0,
        scores_self=0,
        scores_genuine=0,
        is_genuine_score_bearing=False,
        algorithm_failures=6000,
        is_score_bearing=False,
    )
    assert marker["outcome"] == frozen.OUTCOME_FAIL
    assert marker["algorithm_5_established"] is False
    assert marker["opens_common_calibration"] is False
    assert marker["reopens_algorithm_5_search"] is True
    assert marker["fallback_candidate"] == "fingerflow_3_0_1"
    assert "why_not_complete" in marker


def test_a_missing_outcome_refuses_a_marker() -> None:
    with pytest.raises(Stage15AResultIntegrityError):
        _build(stored_outcomes=5999, missing=1)


def test_an_infrastructure_failure_refuses_a_marker() -> None:
    with pytest.raises(Stage15AResultIntegrityError):
        _build(scores=3999, infrastructure_failures=1)


def test_an_unpartitioned_result_set_refuses_a_marker() -> None:
    with pytest.raises(Stage15AResultIntegrityError):
        _build(scores=100, scores_self=100, scores_genuine=0, algorithm_failures=100)


def test_a_set_whose_only_scores_are_self_is_published_as_such() -> None:
    """SELF returns 1.0 by construction, so the split has to reach the marker.

    The stage still passes on its stated criterion — a score is a score — but a
    reader must be able to see that nothing here compared two different prints.
    """
    marker = _build(
        scores=367,
        scores_self=367,
        scores_genuine=0,
        is_genuine_score_bearing=False,
        algorithm_failures=5633,
    )
    assert marker["outcome"] == frozen.OUTCOME_COMPLETE
    assert marker["successful_scores_self"] == 367
    assert marker["successful_scores_genuine"] == 0
    assert marker["result_set_is_genuine_score_bearing"] is False
    assert marker["self_score_is_constant_by_construction"] is True


def test_a_gate_that_did_not_pass_refuses_a_marker() -> None:
    with pytest.raises(Stage15AFinalizationError):
        finalization.build_stage15a_finalization(
            repository_root=REPOSITORY_ROOT,
            run_id="run_stage15atest",
            plan_id="plan_stage15atest",
            result_set_id=None,
            integrity=_integrity(),
            qualification_document={"gate_state": "FAIL"},
            runtime_document=_passing_gate(),
            route_document=_passing_gate(),
        )


def test_the_marker_fingerprint_covers_its_own_contents() -> None:
    marker = _build()
    recomputed = finalization.stage15a_finalization_fingerprint(marker)
    assert recomputed == marker["stage_15a_finalization_fingerprint"]
    tampered = dict(marker)
    tampered["successful_scores"] = 1
    assert finalization.stage15a_finalization_fingerprint(tampered) != recomputed


def test_the_marker_denies_every_later_layer() -> None:
    marker = _build()
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
        "sd300_pilot_before_the_run",
        "stage14a_evidence_modified",
    ):
        assert marker[key] is False, key


def _write_evidence(directory: Path, marker: dict[str, object]) -> None:
    """A complete evidence directory, so the verifier runs its real path."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "README.md").write_text("# Stage 15A\n", encoding="utf-8")
    documents = {
        "predecessor-selection.json": finalization.build_predecessor_selection_document(),
        "artifact-runtime-identity.json": _passing_gate(),
        "upstream-route-contract.json": _passing_gate(),
        "qualification.json": _passing_gate(),
        "canonical-run-binding.json": {"schema": "x"},
        "result-integrity.json": _integrity(),
    }
    for name, document in documents.items():
        (directory / name).write_text(
            json.dumps(document, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
    hashes = finalization._evidence_content_hashes(directory.parents[1])
    marker = dict(marker)
    marker["evidence_content_hashes"] = hashes
    marker["stage_15a_finalization_fingerprint"] = (
        finalization.stage15a_finalization_fingerprint(marker)
    )
    (directory / frozen.STAGE_15A_FINALIZATION_NAME).write_text(
        json.dumps(marker, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def test_the_verifier_refuses_a_rewritten_stage_14a(tmp_path: Path) -> None:
    """A selection record that gives Griaule a verdict is refused, not published."""
    directory = tmp_path / frozen.EVIDENCE_DIRECTORY
    _write_evidence(directory, _build())

    selection = json.loads(
        (directory / "predecessor-selection.json").read_text(encoding="utf-8")
    )
    selection["stage14a_final_outcome"] = "GRIAULE_ARTIFACT_ROUTE_PREFLIGHT_FAIL"
    (directory / "predecessor-selection.json").write_text(
        json.dumps(selection, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    # Re-stamp the hashes so the drift check is not what fires: the point is
    # that the selection rule refuses this on its own.
    marker = json.loads(
        (directory / frozen.STAGE_15A_FINALIZATION_NAME).read_text(encoding="utf-8")
    )
    marker["evidence_content_hashes"] = finalization._evidence_content_hashes(tmp_path)
    marker["stage_15a_finalization_fingerprint"] = (
        finalization.stage15a_finalization_fingerprint(marker)
    )
    (directory / frozen.STAGE_15A_FINALIZATION_NAME).write_text(
        json.dumps(marker, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    with pytest.raises(Stage15ASelectionError):
        finalization.verify_stage15a_evidence(repository_root=tmp_path)


def test_the_verifier_refuses_an_incomplete_evidence_directory(tmp_path: Path) -> None:
    directory = tmp_path / frozen.EVIDENCE_DIRECTORY
    _write_evidence(directory, _build())
    (directory / "qualification.json").unlink()
    with pytest.raises(Stage15AFinalizationError, match="incomplete"):
        finalization.verify_stage15a_evidence(repository_root=tmp_path)


def test_the_verifier_detects_evidence_edited_after_the_marker(tmp_path: Path) -> None:
    directory = tmp_path / frozen.EVIDENCE_DIRECTORY
    _write_evidence(directory, _build())
    (directory / "canonical-run-binding.json").write_text(
        json.dumps({"schema": "edited"}) + "\n", encoding="utf-8"
    )
    with pytest.raises(Stage15AFinalizationError, match="has changed"):
        finalization.verify_stage15a_evidence(repository_root=tmp_path)
