from __future__ import annotations

import json
from pathlib import Path

import pytest

import fpbench.stage21b.evidence as stage21b_evidence
from fpbench.stage21b.bindings import load_stage21a_binding
from fpbench.stage21b.constants import (
    EXPECTED_PAIRS_PER_METHOD,
    EXPECTED_TOTAL_ATTEMPTS,
    OUTCOME,
    STAGE21B_EVIDENCE,
    STAGE21B_MARKER,
)
from fpbench.stage21b.evidence import (
    _method_receipt,
    _no_evaluation_document,
    _verify_no_evaluation_document,
    publish_stage21b_evidence,
    verify_stage21b_evidence,
)
from fpbench.stage21b.errors import Stage21BIntegrityError
from .helpers import ScriptedAdapter, make_pairs, make_spec

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.stage21b_contract


def test_no_evaluation_schema_has_the_required_closed_false_attestations() -> None:
    document = _no_evaluation_document(ROOT)
    _verify_no_evaluation_document(document)
    assert document["new_raw_scores_generated"] is True
    required_false = {
        "tar_computed",
        "far_computed",
        "frr_computed",
        "score_sweep_performed",
        "far_target_selected_from_results",
        "threshold_selected",
        "calibration_performed",
        "score_normalization_performed",
        "cross_algorithm_raw_scores_compared",
        "algorithm_ranking_performed",
        "pair_selection_used_scores",
        "algorithm_parameters_changed_from_results",
        "future_method_development_started",
    }
    assert all(document[name] is False for name in required_false)


def test_method_receipt_contains_counts_and_hashes_but_no_raw_score() -> None:
    pairs = make_pairs(3)
    adapter = ScriptedAdapter("receipt_method")
    spec = make_spec(adapter, pairs)
    result = {
        "result_set_fingerprint": "a" * 64,
        "result_set_manifest_sha256": "d" * 64,
        "result_set_manifest_fingerprint": "e" * 64,
        "planned_attempts": 3,
        "terminal_outcomes": 3,
        "score_bearing_outcomes": 2,
        "algorithm_failures": 1,
        "failure_classifications": {"template_extraction_failed": 1},
        "attempt_records": 3,
        "infrastructure_gaps": 0,
        "infrastructure_events_before_completion": {},
        "release_counts": {"SD300A": 1, "SD300B": 1, "SD300C": 1},
        "timing": {"adapter_wall_time_total_ms": 1.0},
    }
    source = {
        "execution_source_fingerprint": spec.execution_source_fingerprint,
        "execution_source_revision": "revision",
        "file_sha256s": {"src/example.py": "b" * 64},
        "private_adapter_config_sha256": "c" * 64,
        "runtime_identity_fingerprint": spec.runtime_identity_fingerprint,
    }
    receipt = _method_receipt(result, spec, source)
    rendered = json.dumps(receipt)
    assert "raw_score" not in rendered
    assert receipt["score_bearing_outcomes"] == 2
    assert receipt["algorithm_failures"] == 1
    assert receipt["score_summary_computed"] is False


def test_publisher_refuses_to_create_final_marker_before_six_sealed_runs(
    tmp_path, monkeypatch
) -> None:
    binding = load_stage21a_binding(ROOT)
    assert len(binding.algorithms) == 6
    marker = ROOT / STAGE21B_EVIDENCE / STAGE21B_MARKER
    if marker.exists():
        pytest.skip("Stage 21B is published; refusal is only testable before it is")
    monkeypatch.setattr(
        stage21b_evidence,
        "run_contract_suite",
        lambda _root: {
            "contract_tests_pass": True,
            "regression_tests_pass": True,
            "sd300_matcher_attempts": 0,
        },
    )
    monkeypatch.setattr(
        stage21b_evidence,
        "load_stage21a_binding",
        lambda *_args, **_kwargs: binding,
    )
    with pytest.raises(Stage21BIntegrityError, match="authoritative sealed run"):
        publish_stage21b_evidence(
            repository_root=ROOT,
            workspace=tmp_path,
        )
    assert not marker.exists()


def test_evidence_directory_contains_no_raw_result_store() -> None:
    directory = ROOT / STAGE21B_EVIDENCE
    assert not list(directory.rglob("*.parquet"))
    assert not list(directory.rglob("*.sqlite3"))


def test_the_evidence_directory_is_either_unpublished_or_fully_verifiable() -> None:
    """There is no third state, and CI is where that has to be true.

    Publication writes every receipt and only then the marker, so a directory
    holding documents without a marker is a publisher that stopped halfway —
    the shape this test exists to make loud. Once the marker is there the whole
    gate is re-derived here without a dataset, an SDK, a licence or the raw
    result workspace, which is what spec section 41 asks public CI to run.
    """
    directory = ROOT / STAGE21B_EVIDENCE
    marker = directory / STAGE21B_MARKER
    published = sorted(
        path.relative_to(directory).as_posix()
        for path in directory.rglob("*")
        if path.is_file() and path.name != STAGE21B_MARKER
    )
    if not marker.is_file():
        assert published == ["README.md"], (
            "Stage 21B is unpublished, so the evidence directory may hold nothing "
            f"but its README; found {published}"
        )
        return

    document = verify_stage21b_evidence(ROOT)
    assert document["outcome"] == OUTCOME
    assert document["roster_size"] == 6
    assert document["planned_pairs_per_method"] == EXPECTED_PAIRS_PER_METHOD
    assert document["planned_total_attempts"] == EXPECTED_TOTAL_ATTEMPTS
    assert document["methods_completed"] == 6
    assert all(document["conditions"].values())
    for forbidden in (
        "metrics_computed",
        "tar_computed",
        "far_computed",
        "frr_computed",
        "score_sweep_performed",
        "threshold_selected",
        "calibration_performed",
        "score_normalization_performed",
        "ranking_performed",
    ):
        assert document[forbidden] is False
