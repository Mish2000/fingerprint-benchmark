"""The committed Stage 16A evidence gate.

No artifact store, no TensorFlow, no checkpoint, no network and no dataset: this
suite reads the nine published files and re-derives what they can re-derive from
each other. That is what makes it a CI gate rather than a re-run, and it is the
only check that would notice the evidence being edited after the marker was
written.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fpbench.core.stage16a_errors import Stage16AFinalizationError
from fpbench.experiments import stage16a_finalization as finalization
from fpbench.experiments import stage16a_identity as frozen

pytestmark = pytest.mark.stage16a

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = REPOSITORY_ROOT / frozen.EVIDENCE_DIRECTORY


def _document(name: str) -> dict:
    return json.loads((EVIDENCE / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def marker() -> dict:
    return _document(frozen.STAGE_16A_FINALIZATION_NAME)


def test_every_expected_document_is_published() -> None:
    for name in frozen.EVIDENCE_DOCUMENTS:
        assert (EVIDENCE / name).is_file(), name
    published = {path.name for path in EVIDENCE.iterdir() if path.is_file()}
    assert published == set(frozen.EVIDENCE_DOCUMENTS)


def test_the_evidence_verifies_end_to_end() -> None:
    findings = finalization.verify_stage16a_evidence(repository_root=REPOSITORY_ROOT)
    assert findings["missing_documents"] == []
    assert findings["outcome"] in frozen.OUTCOMES


def test_the_stage_closed_at_the_route_gate(marker: dict) -> None:
    assert marker["outcome"] == frozen.OUTCOME_ROUTE_FAIL
    assert marker["blocker"] == "UPSTREAM_INFERENCE_ROUTE_NOT_CLOSED"
    assert marker["gate_reached_last"] == frozen.GATES["G2"]
    assert marker["gates"][frozen.GATES["G1"]] == "PASS"
    assert marker["gates"][frozen.GATES["G2"]] == "FAIL"
    for gate in ("G4", "G5", "G6", "G7"):
        assert marker["gates"][frozen.GATES[gate]] == "NOT_REACHED"


def test_algorithm_5_is_not_established_and_the_search_reopens(marker: dict) -> None:
    assert marker["algorithm_5_established"] is False
    assert marker["opens_common_calibration"] is False
    assert marker["reopens_algorithm_5_search"] is True
    assert marker["calibration_roster"] == []
    assert marker["fallback_candidate"] is None


def test_nothing_was_executed_and_no_sd300_image_was_opened(marker: dict) -> None:
    assert marker["adapter_frozen"] is False
    assert marker["canonical_run_executed"] is False
    assert marker["sd300_images_opened"] == 0
    assert marker["stored_outcomes"] == 0
    binding = _document("canonical-run-binding.json")
    assert binding["gate_state"] == "NOT_REACHED"
    assert binding["run_id"] is None
    assert binding["result_set_id"] is None


def test_the_route_document_settles_six_of_ten_questions() -> None:
    document = _document("upstream-inference-route.json")
    assert document["gate_state"] == "FAIL"
    assert len(document["questions"]) == len(frozen.ROUTE_QUESTIONS)
    assert len(document["settled_questions"]) == 6
    assert set(document["unsettled_questions"]) == {
        "how_many_minutiae_are_retained",
        "whether_rotation_augmentation_belongs_to_inference",
        "what_happens_below_the_required_minutiae_count",
        "which_verify_net_precision_and_checkpoint",
    }


def test_every_unsettled_question_names_more_than_one_upstream_alternative() -> None:
    document = _document("upstream-inference-route.json")
    unsettled = set(document["unsettled_questions"])
    for question in document["questions"]:
        if question["key"] in unsettled:
            assert question["authority"] == "FPBENCH_WOULD_HAVE_TO_CHOOSE"
            assert question["answer"] is None
            assert len(question["upstream_statements"]) >= 2, question["key"]
            assert question["why"].strip()


def test_every_settled_question_carries_an_authority_and_an_answer() -> None:
    document = _document("upstream-inference-route.json")
    settled = set(document["settled_questions"])
    for question in document["questions"]:
        if question["key"] in settled:
            assert question["authority"] in frozen.SETTLING_AUTHORITIES
            assert question["answer"]
            assert question["upstream_statements"]


def test_no_alternative_was_chosen_by_experiment() -> None:
    document = _document("upstream-inference-route.json")
    assert document["experiments_run_to_choose_between_alternatives"] == 0
    marker = _document(frozen.STAGE_16A_FINALIZATION_NAME)
    assert marker["experiments_run_to_choose_between_route_alternatives"] == 0
    assert marker["fpbench_chose_a_score_affecting_step"] is False


def test_the_artifact_gate_passed_on_nine_self_service_checkpoints() -> None:
    document = _document("artifact-runtime-identity.json")
    assert document["gate_state"] == "PASS"
    assert document["blocker"] is None
    assert document["self_service_acquisition"] is True
    assert document["vendor_or_author_request_required"] is False
    assert len(document["checkpoints"]) == len(frozen.CHECKPOINTS)
    assert set(document["roles_covered"]) == set(frozen.REQUIRED_CHECKPOINT_ROLES)


def test_the_dead_drive_locators_are_published_as_their_own_finding() -> None:
    document = _document("artifact-runtime-identity.json")
    dead = {entry["role"]: entry for entry in document["dead_upstream_locators"]}
    assert set(dead) == {"coarse_net", "fine_net"}
    for entry in dead.values():
        assert entry["status"] == "HTTP_404"
        assert len(entry["endpoints_tried"]) >= 3
        assert entry["served_instead_by"]


def test_the_closure_does_not_claim_to_be_contemporary_with_the_artifact() -> None:
    document = _document("artifact-runtime-identity.json")
    assert document["closure_is_contemporary_with_artifact"] is False
    assert document["why_not_contemporary"].strip()
    assert document["upstream_declared_pins"]["tensorflow"] == "2.5.1"


def test_stage_15a_is_cited_for_its_mechanism_and_never_for_its_scores() -> None:
    document = _document("predecessor-selection.json")
    assert document["reason"] == frozen.PREDECESSOR_REASON
    assert document["predecessor_scores_read"] is False
    assert document["prior_algorithm_scores_read"] is False
    assert document["stage15a_evidence_modified"] is False
    assert document["stage15a_rerun"] is False
    assert set(document["reason_is_not"]) == set(frozen.PREDECESSOR_REASON_IS_NOT)
    for statement in document["evidence"]:
        assert not any(character.isdigit() for character in statement), statement


def test_the_predecessor_marker_is_bound_by_fingerprint() -> None:
    document = _document("predecessor-selection.json")
    bound = {entry["stage"]: entry for entry in document["bound_markers"]}
    assert set(bound) == {"15A", "11B", "8E"}
    for entry in bound.values():
        assert len(entry["finalization_fingerprint"]) == 64


def test_the_bound_stage_15a_fingerprint_is_the_one_stage_15a_publishes() -> None:
    """A binding that names a marker nobody can find is not a binding."""
    predecessor = REPOSITORY_ROOT / "evidence/stage15a-fingerprints-matching"
    published = json.loads(
        (predecessor / "stage-15a-finalization.json").read_text(encoding="utf-8")
    )["stage_15a_finalization_fingerprint"]
    bound = {
        entry["stage"]: entry
        for entry in _document("predecessor-selection.json")["bound_markers"]
    }
    assert bound["15A"]["finalization_fingerprint"] == published


def test_the_marker_fingerprint_matches_its_own_contents(marker: dict) -> None:
    assert finalization.stage16a_finalization_fingerprint(marker) == marker[
        "stage_16a_finalization_fingerprint"
    ]


def test_the_marker_pins_the_published_documents_by_content(marker: dict) -> None:
    recorded = marker["evidence_content_hashes"]
    assert set(recorded) == set(frozen.EVIDENCE_DOCUMENTS) - {
        frozen.STAGE_16A_FINALIZATION_NAME
    }
    for name, digest in recorded.items():
        import hashlib

        observed = hashlib.sha256((EVIDENCE / name).read_bytes()).hexdigest()
        assert observed == digest, name


def test_no_published_document_carries_a_threshold_or_an_absolute_path() -> None:
    finalization._require_no_forbidden_published_data(EVIDENCE)


def test_the_evidence_refuses_a_marker_that_outran_its_route(tmp_path: Path) -> None:
    """Tamper: claim Algorithm 5 while the route document still has open questions."""
    staged = tmp_path / frozen.EVIDENCE_DIRECTORY
    staged.mkdir(parents=True)
    for name in frozen.EVIDENCE_DOCUMENTS:
        (staged / name).write_bytes((EVIDENCE / name).read_bytes())
    marker = json.loads(
        (staged / frozen.STAGE_16A_FINALIZATION_NAME).read_text(encoding="utf-8")
    )
    marker["algorithm_5_established"] = True
    marker["stage_16a_finalization_fingerprint"] = (
        finalization.stage16a_finalization_fingerprint(marker)
    )
    (staged / frozen.STAGE_16A_FINALIZATION_NAME).write_text(
        json.dumps(marker, indent=2, sort_keys=True), encoding="utf-8"
    )
    with pytest.raises(Stage16AFinalizationError):
        finalization.verify_stage16a_evidence(repository_root=tmp_path)
