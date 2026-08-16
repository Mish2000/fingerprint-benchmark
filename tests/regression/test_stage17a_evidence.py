"""The committed Stage 17A evidence gate.

No artifact store, no package, no network and no dataset: this suite reads the
five published files and re-derives what they can re-derive from each other.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from fpbench.core.stage17a_errors import Stage17AFinalizationError
from fpbench.experiments import stage17a_finalization as finalization
from fpbench.experiments import stage17a_identity as frozen

pytestmark = pytest.mark.stage17a

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = REPOSITORY_ROOT / frozen.EVIDENCE_DIRECTORY


def _document(name: str) -> dict:
    return json.loads((EVIDENCE / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def marker() -> dict:
    return _document(frozen.STAGE_17A_FINALIZATION_NAME)


def test_every_expected_document_is_published() -> None:
    published = {path.name for path in EVIDENCE.iterdir() if path.is_file()}
    assert published == set(frozen.EVIDENCE_DOCUMENTS)


def test_the_evidence_verifies_end_to_end() -> None:
    findings = finalization.verify_stage17a_evidence(repository_root=REPOSITORY_ROOT)
    assert findings["missing_documents"] == []
    assert findings["outcome"] in frozen.OUTCOMES


def test_the_stage_closed_at_the_score_contract(marker: dict) -> None:
    assert marker["outcome"] == frozen.OUTCOME_SCORE_CONTRACT_FAIL
    assert marker["blocker"] == "BOOLEAN_OR_THRESHOLD_ONLY_OUTPUT"
    assert marker["gate_reached_last"] == frozen.GATES["G2"]
    assert marker["gates"][frozen.GATES["G1"]] == "PASS"
    assert marker["gates"][frozen.GATES["G2"]] == "FAIL"
    for key in ("G3", "G4", "G5", "G6", "G7"):
        assert marker["gates"][frozen.GATES[key]] == "NOT_REACHED"


def test_the_artifact_gate_passed_on_both_distributions() -> None:
    document = _document("artifact-identity.json")
    assert document["gate_state"] == "PASS"
    assert document["self_service_acquisition"] is True
    assert document["vendor_or_author_request_required"] is False
    assert document["module"]["sdist_and_wheel_are_identical"] is True
    assert document["module"]["expected_sha256"] == frozen.MODULE_SHA256
    for entry in document["published_distributions"]:
        assert entry["present"] is True
        assert entry["matches"] is True


def test_the_repository_is_recorded_as_a_locator_and_not_an_authority() -> None:
    document = _document("artifact-identity.json")
    assert document["authority_is_the_distribution"] is True
    assert document["why_not_the_repository"].strip()


def test_the_entry_point_returns_nothing_and_that_is_the_reason() -> None:
    document = _document("score-contract.json")
    assert document["gate_state"] == "FAIL"
    assert document["returns_native_scalar_before_decision"] is False
    assert document["score_direction_provable_from_source"] is False
    findings = document["findings"]
    assert findings["return_statements_carrying_a_value"] == 0
    assert findings["docstring_declares_returns"] == "None"
    assert findings["ratio_is_returned"] is False
    assert findings["internal_decision_thresholds"] == ["match_ratio > 0.95"]
    assert findings["printed_observables"] > 0


def test_no_score_direction_is_published_anywhere(marker: dict) -> None:
    assert _document("score-contract.json")["score_direction"] is None
    assert marker["score_direction"] is None


def test_the_score_was_not_reconstructed_by_any_route(marker: dict) -> None:
    for denial in (
        "score_reconstructed_by_fpbench",
        "stdout_parsed_for_a_score",
        "upstream_function_reimplemented",
    ):
        assert marker[denial] is False, denial
    document = _document("score-contract.json")
    assert len(document["what_recovering_a_score_would_require"]) == 2
    assert document["why_that_is_refused"].strip()


def test_nothing_was_installed_executed_or_opened(marker: dict) -> None:
    assert marker["package_installed"] is False
    assert marker["package_executed"] is False
    assert marker["adapter_frozen"] is False
    assert marker["canonical_run_executed"] is False
    assert marker["sd300_images_opened"] == 0


def test_the_route_gate_explains_why_it_is_not_a_gap() -> None:
    document = _document("upstream-route.json")
    assert document["gate_state"] == "NOT_REACHED"
    assert document["why_not_reached"].strip()
    assert set(document["fpbench_refuses_to_add"]) == set(frozen.REFUSED_FPBENCH_STEPS)


def test_algorithm_5_is_open_and_no_fallback_is_invented(marker: dict) -> None:
    assert marker["algorithm_5_established"] is False
    assert marker["reopens_algorithm_5_search"] is True
    assert marker["opens_common_calibration"] is False
    assert marker["calibration_roster"] == []
    assert marker["fallback_candidate"] is None


def test_the_bound_predecessor_fingerprints_are_the_published_ones(marker: dict) -> None:
    bound = {record["stage"]: record for record in marker["bound_markers"]}
    published = {
        "16A": (
            "evidence/stage16a-fingerflow/stage-16a-finalization.json",
            "stage_16a_finalization_fingerprint",
        ),
        "15A": (
            "evidence/stage15a-fingerprints-matching/stage-15a-finalization.json",
            "stage_15a_finalization_fingerprint",
        ),
    }
    for stage, (relative, key) in published.items():
        document = json.loads(
            (REPOSITORY_ROOT / relative).read_text(encoding="utf-8")
        )
        assert bound[stage]["finalization_fingerprint"] == document[key], stage


def test_the_marker_fingerprint_matches_its_own_contents(marker: dict) -> None:
    assert finalization.stage17a_finalization_fingerprint(marker) == marker[
        "stage_17a_finalization_fingerprint"
    ]


def test_the_marker_pins_the_published_documents_by_content(marker: dict) -> None:
    recorded = marker["evidence_content_hashes"]
    assert set(recorded) == set(frozen.EVIDENCE_DOCUMENTS) - {
        frozen.STAGE_17A_FINALIZATION_NAME
    }
    for name, digest in recorded.items():
        assert hashlib.sha256((EVIDENCE / name).read_bytes()).hexdigest() == digest


def test_no_published_document_carries_a_threshold_or_an_absolute_path() -> None:
    finalization._require_no_forbidden_published_data(EVIDENCE)


def test_evidence_claiming_a_direction_for_a_failed_contract_is_refused(
    tmp_path: Path,
) -> None:
    staged = tmp_path / frozen.EVIDENCE_DIRECTORY
    staged.mkdir(parents=True)
    for name in frozen.EVIDENCE_DOCUMENTS:
        (staged / name).write_bytes((EVIDENCE / name).read_bytes())
    document = json.loads((staged / "score-contract.json").read_text(encoding="utf-8"))
    document["score_direction"] = "HIGHER_MORE_SIMILAR"
    (staged / "score-contract.json").write_text(
        json.dumps(document, indent=2, sort_keys=True), encoding="utf-8"
    )
    with pytest.raises(Stage17AFinalizationError):
        finalization.verify_stage17a_evidence(repository_root=tmp_path)
