"""The committed Stage 20B evidence gate.

Reads what was published and checks it says what Stage 20B is required to say.
No dataset, no runtime, no vendor byte and no prior-result workspace.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from fpbench.experiments.stage18a_inputs import REPOSITORY_ROOT
from fpbench.experiments.stage20b_finalization import stage20b_source_fingerprint
from fpbench.experiments.stage20b_identity import (
    EVIDENCE_DIRECTORY,
    EVIDENCE_DOCUMENTS,
    EXPECTED_OUTCOMES,
    PREFERENCE_REASON,
    STAGE_20B_FINALIZATION_NAME,
    SUPERVISOR_DISCLOSURE,
)

pytestmark = pytest.mark.stage20b

DIRECTORY = REPOSITORY_ROOT / EVIDENCE_DIRECTORY


def _read(name: str) -> dict:
    return json.loads((DIRECTORY / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def marker() -> dict:
    return _read(STAGE_20B_FINALIZATION_NAME)


# ------------------------------------------------------------------ integrity


def test_the_evidence_is_exactly_the_declared_documents() -> None:
    present = sorted(path.name for path in DIRECTORY.iterdir() if path.is_file())
    assert present == sorted([*EVIDENCE_DOCUMENTS, STAGE_20B_FINALIZATION_NAME])


def test_every_evidence_byte_matches_the_digest_the_marker_published(marker) -> None:
    for name, digest in marker["evidence_content_hashes"].items():
        assert hashlib.sha256((DIRECTORY / name).read_bytes()).hexdigest() == digest, name


def test_the_marker_fingerprint_covers_the_marker(marker) -> None:
    payload = {
        key: value
        for key, value in marker.items()
        if key != "stage_20b_finalization_fingerprint"
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    assert (
        hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        == marker["stage_20b_finalization_fingerprint"]
    )


def test_the_source_fingerprint_still_describes_this_tree(marker) -> None:
    assert marker["stage20b_source_fingerprint"] == stage20b_source_fingerprint(
        REPOSITORY_ROOT
    )


def test_no_vendor_byte_reached_the_repository(marker) -> None:
    assert marker["third_party_bytes_added_to_git"] is False
    for path in DIRECTORY.iterdir():
        assert path.suffix in {".json", ".md"}
        assert path.stat().st_size < 4_000_000


# --------------------------------------------------------------------- gates


def test_gate_a_reproduced_stage20a_exactly(marker) -> None:
    gate = _read("gate-a-bridge-reproduction.json")
    assert marker["gate_a_bridge_reproduction"] == "PASS"
    assert gate["outcome"] == "MCC_PRODUCTION_BRIDGE_REPRODUCTION_PASS"
    assert gate["mismatches"] == 0
    assert gate["exact_matches"] == gate["expected_comparisons"] == 5
    assert gate["tolerance"] is None
    assert all(row["exact"] for row in gate["comparisons"])
    assert all(gate["symmetry_preserved"].values())
    # The gate says nothing about the extractor, and says so.
    assert "MINDTCT" in gate["what_this_does_not_prove"]
    assert gate["sd300_images_used"] == 0


def test_gate_a_scores_are_stage20as_own_numbers() -> None:
    gate = _read("gate-a-bridge-reproduction.json")
    published = {row["comparison"]: row["production_score"] for row in gate["comparisons"]}
    assert published == {
        "self": 0.6463866269440767,
        "related_forward": 0.18989714373119645,
        "related_reverse": 0.18989714373119645,
        "unrelated_forward": 0.10158917843359545,
        "unrelated_reverse": 0.10158917843359545,
    }


def test_gate_b_proved_the_extractor_is_algorithm_twos(marker) -> None:
    gate = _read("gate-b-mindtct-parity.json")
    assert marker["gate_b_mindtct_parity"] == "PASS"
    assert gate["outcome"] == "MINDTCT_ROUTE_PARITY_PASS"
    assert gate["expected_images"] == 12
    assert gate["identical_xyt"] == 12
    assert gate["mismatches"] == 0
    assert gate["same_mindtct_executable"] is True
    assert gate["flags"] == []
    assert gate["scores_read"] == 0
    assert gate["sd300_used_for_selection"] is False
    assert gate["subset_frozen_before_extraction"] is True
    for row in gate["images"]:
        assert row["identical"] is True
        assert row["algorithm2_xyt_sha256"] == row["stage20b_xyt_sha256"]


def test_gate_b_covered_two_impressions_of_every_release() -> None:
    gate = _read("gate-b-mindtct-parity.json")
    for release in ("SD300A", "SD300B", "SD300C"):
        of_release = [row for row in gate["images"] if row["release"] == release]
        assert len(of_release) == 4
        assert sum(1 for row in of_release if row["impression_type"] == "plain") == 2
        assert sum(1 for row in of_release if row["impression_type"] == "roll") == 2


# ---------------------------------------------------------------- the raw run


def test_every_attempt_is_stored_and_none_is_missing(marker) -> None:
    binding = _read("canonical-run-binding.json")
    assert marker["expected_outcomes"] == EXPECTED_OUTCOMES
    assert marker["stored_outcomes"] == EXPECTED_OUTCOMES
    assert marker["missing"] == 0
    assert binding["stored_outcomes"] == EXPECTED_OUTCOMES
    assert binding["missing"] == 0


def test_the_run_used_the_same_manifest_as_every_other_algorithm() -> None:
    binding = _read("canonical-run-binding.json")
    assert binding["preparation_set_id"] == "prepset_be560e047991"
    assert binding["pair_manifest_hash"] == (
        "ee4d942e23cdc112e17ed69e0abc603d5f26e17cc5839edc9aa412edc57dfe3b"
    )
    assert binding["pairs_regenerated"] is False
    assert binding["pair_order_changed"] is False
    assert binding["dataset_changed"] is False
    assert binding["protocol_stages"] == {
        "plain_self": 1500,
        "roll_self": 1500,
        "plain_roll_mated": 1500,
        "plain_roll_non_mated": 1500,
    }


def test_the_result_file_holds_each_pair_once_in_manifest_order() -> None:
    integrity = _read("result-integrity.json")
    assert integrity["duplicate_pair_ids"] == 0
    assert integrity["ordinals_are_the_manifest_order"] is True
    assert integrity["ordinals_are_complete"] is True
    assert integrity["every_attempt_stored"] is True
    assert integrity["algorithm_ids_present"] == ["nbis_mindtct_mcc_sdk_v2"]


def test_no_score_lies_outside_the_frozen_contract() -> None:
    integrity = _read("result-integrity.json")
    assert integrity["scores_outside_contract"] == 0
    assert integrity["invalid_scores_clamped"] is False


def test_no_failure_became_a_zero_and_no_zero_became_a_failure(marker) -> None:
    integrity = _read("result-integrity.json")
    assert integrity["failures_recorded_as_zero"] == 0
    assert integrity["successes_recorded_without_a_score"] == 0
    assert integrity["zero_is_a_valid_similarity"] is True
    assert marker["failures_recorded_as_zero"] is False


# -------------------------------------------------------------- what is absent


def test_the_stage_produced_no_decision_threshold_or_metric(marker) -> None:
    binding = _read("canonical-run-binding.json")
    diagnostics = _read("diagnostic-report.json")
    for document in (marker, binding, diagnostics):
        assert document.get("threshold", document.get("threshold_applied")) is None
        assert document.get("calibration_performed") is False
    assert binding["decisions_produced"] == 0
    assert binding["metrics_produced"] == []
    assert marker["metrics_produced"] is False
    assert marker["decision_profile_produced"] is False
    assert marker["algorithm_ranking_published"] is False

    text = json.dumps(diagnostics).lower()
    for absent in ('"tar"', '"far"', '"frr"', '"fmr"', '"fnmr"', '"eer"', '"non_match"'):
        assert absent not in text


def test_the_diagnostics_changed_nothing() -> None:
    diagnostics = _read("diagnostic-report.json")
    assert diagnostics["used_to_change_route_or_configuration"] is False
    assert diagnostics["score_transform"] == "NONE"


def test_the_matcher_comparison_names_no_winner() -> None:
    diagnostics = _read("diagnostic-report.json")
    comparison = diagnostics.get("algorithm2_comparison")
    if comparison is None:
        pytest.skip("the run was published without the Algorithm 2 comparison")
    assert comparison["threshold_applied"] is None
    assert comparison["decisions_produced"] == 0
    assert "calibration" in comparison["why_no_better_or_worse"]
    text = json.dumps(comparison).lower()
    assert "better" not in text.replace("why_no_better_or_worse", "")


# ---------------------------------------------------------------- the identity


def test_the_algorithm_names_its_extractor(marker) -> None:
    identity = _read("algorithm-identity.json")
    assert marker["algorithm_id"] == "nbis_mindtct_mcc_sdk_v2"
    assert marker["display_name"] == "NBIS MINDTCT + MCC SDK v2.0"
    assert marker["extractor"] == "NBIS_MINDTCT_5_0_0"
    assert marker["matcher"] == "MCC_SDK_V2_BASELINE"
    assert marker["shares_extractor_with"] == "nbis_mindtct_bozorth3"
    assert marker["is_an_independent_fifth_system"] is False
    assert "no image extractor" in identity["why_the_extractor_is_in_the_name"]


def test_nothing_of_the_vendors_was_modified(marker) -> None:
    identity = _read("algorithm-identity.json")
    assert marker["upstream_modified"] is False
    assert marker["official_mcc_artifact"] is True
    assert identity["parameter_setters_called"] is False
    assert identity["parameters"] == "SDK_OPTIMAL_DEFAULTS"
    assert identity["mcc_sdk_dll_sha256"] == (
        "7267ea9f2ea4c32bdeef30a49e648a516381941b531c59960517a87e5cd2eb01"
    )


def test_the_runtime_binding_records_the_two_hosts_and_one_process_per_pair() -> None:
    binding = _read("runtime-binding.json")
    assert binding["nbis_build_id"] == "658f9f54a8f2"
    assert binding["same_certified_build_as_algorithm_2"] is True
    assert binding["mindtct_compiled_for_this_stage"] is False
    assert binding["bridge_process_model"] == "one_process_per_comparison"
    assert binding["template_cache"] == "disabled"
    assert binding["template_persistence"] == "disabled"
    assert binding["vendor_bytes_in_git"] is False
    assert binding["dependencies"]["mcc.parameter_setters_called"] == "false"
    assert binding["dependencies"]["mcc.threshold"] == "NONE"


def test_the_score_contract_is_stage20as(marker) -> None:
    assert marker["score_type"] == "System.Double"
    assert marker["score_range"] == [0.0, 1.0]
    assert marker["score_direction"] == "HIGHER_MORE_SIMILAR"
    assert marker["score_transform"] == "NONE"
    assert marker["threshold"] is None


# --------------------------------------------------------------- the decision


def test_the_preference_reason_is_the_implementation_and_never_the_scores(marker) -> None:
    assert marker["preference_reason"] == PREFERENCE_REASON == (
        "OFFICIAL_UNMODIFIED_MATCHER_ROUTE"
    )
    assert marker["selection_based_on_sd300_accuracy"] is False
    assert marker["sd300_parameter_selection"] is False
    assert marker["sd300_performance_selection"] is False


def test_the_completion_conditions_are_all_recorded(marker) -> None:
    conditions = marker["completion_conditions"]
    assert set(conditions) == {
        "gate_a_bridge_reproduction",
        "gate_b_mindtct_parity",
        "canonical_run_complete",
        "route_unchanged",
        "no_systemic_bridge_defect",
        "no_systemic_translation_defect",
        "no_parameter_selection",
        "no_calibration",
        "no_threshold_selection",
    }
    assert all(conditions.values())


def test_openafis_is_not_deleted_by_this_stage(marker) -> None:
    assert marker["openafis_capacity_extended_retained_as"] in {
        "additional experimentally evaluated method",
        "algorithm_5",
    }


def test_the_marker_binds_its_predecessors(marker) -> None:
    stages = {row["stage"]: row for row in marker["bound_markers"]}
    assert set(stages) == {"20A", "19B", "8E"}
    assert stages["20A"]["outcome"] == "MINDTCT_MCC_SDK_V2_ROUTE_PASS"
    for row in stages.values():
        assert len(row["finalization_fingerprint"]) == 64
        assert row["why"]


def test_the_disclosure_travels_with_the_number(marker) -> None:
    assert marker["supervisor_disclosure"] == SUPERVISOR_DISCLOSURE
    for phrase in ("shares the MINDTCT extractor", "no image extractor", "no threshold"):
        assert phrase in SUPERVISOR_DISCLOSURE


def test_the_readme_states_what_the_stage_did_not_do() -> None:
    readme = (DIRECTORY / "README.md").read_text(encoding="utf-8")
    for phrase in ("Gate A", "Gate B", "6,000", "MINDTCT", "MCC SDK v2.0"):
        assert phrase in readme
