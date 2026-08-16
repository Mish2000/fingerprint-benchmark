"""The frozen Stage 16A contract: seven gates, three outcomes, one decision rule.

No FingerFlow package, no TensorFlow, no checkpoint, no network and no dataset.
This suite runs anywhere, which is the claim the stage makes about the part of
itself that matters: the route-closure question is answered by reading upstream
source, and the *rule* for answering it is a state machine that needs nothing
installed.

What is under test is the shape of the decision rather than the decision. The
candidate identity and its pinned digests, the gate order and fail-fast, the four
authority levels and the one that fails, the refusal to break a tie by
experiment, the explicit-refusal/unhandled-exception split, the predecessor
record that may cite a mechanism and not a score, and a marker that cannot
establish Algorithm 5 over an unclosed route.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from fpbench.core.errors import FpbenchError
from fpbench.core.stage16a_errors import (
    Stage16AAdapterError,
    Stage16AArtifactIdentityError,
    Stage16AError,
    Stage16AFinalizationError,
    Stage16AIdentityError,
    Stage16AQualificationError,
    Stage16AResultIntegrityError,
    Stage16ARouteClosureError,
    Stage16AScoreContractError,
    Stage16ASelectionError,
    Stage16AUnhandledImplementationError,
)
from fpbench.experiments import stage16a_acquire as acquire
from fpbench.experiments import stage16a_artifacts as artifacts
from fpbench.experiments import stage16a_finalization as finalization
from fpbench.experiments import stage16a_identity as frozen
from fpbench.experiments import stage16a_route as route

pytestmark = pytest.mark.stage16a_contract

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


# ------------------------------------------------------------- the vocabulary


def test_every_error_descends_from_the_project_root() -> None:
    for error in (
        Stage16AError,
        Stage16AIdentityError,
        Stage16ASelectionError,
        Stage16AArtifactIdentityError,
        Stage16ARouteClosureError,
        Stage16AScoreContractError,
        Stage16AQualificationError,
        Stage16AUnhandledImplementationError,
        Stage16AAdapterError,
        Stage16AResultIntegrityError,
        Stage16AFinalizationError,
    ):
        assert issubclass(error, Stage16AError)
        assert issubclass(error, FpbenchError)


def test_the_error_module_is_a_sibling_and_not_an_edit_of_an_earlier_one() -> None:
    """Stage 15A's marker pins its own error module byte-for-byte."""
    source = (REPOSITORY_ROOT / "src/fpbench/core/stage16a_errors.py").read_text(
        encoding="utf-8"
    )
    assert "class Stage15A" not in source
    assert "from fpbench.core.errors import FpbenchError" in source


def test_an_unhandled_implementation_exception_has_its_own_class() -> None:
    """The Stage 15A lesson, as a type rather than as a comment."""
    assert not issubclass(Stage16AUnhandledImplementationError, Stage16AQualificationError)
    assert not issubclass(Stage16AQualificationError, Stage16AUnhandledImplementationError)


# --------------------------------------------------------------- the identity


def test_the_candidate_is_pinned_by_version_commit_and_digest() -> None:
    assert frozen.CANDIDATE_ID == "fingerflow_3_0_1"
    assert frozen.PACKAGE_REQUIREMENT == "fingerflow==3.0.1"
    assert frozen.LICENSE == "MIT"
    assert len(frozen.UPSTREAM_COMMIT) == 40
    assert frozen.UPSTREAM_TAG == "v3.0.1"
    for digest in (frozen.RUNTIME_ARTIFACT_SHA256, frozen.SOURCE_ARTIFACT_SHA256):
        assert len(digest) == 64 and int(digest, 16) >= 0


def test_every_checkpoint_carries_a_digest_a_size_and_a_locator() -> None:
    for record in frozen.CHECKPOINTS:
        assert len(str(record["sha256"])) == 64
        assert int(record["size_bytes"]) > 0
        assert str(record["locator"]).strip()
        assert record["role"] in frozen.REQUIRED_CHECKPOINT_ROLES
        assert str(record["needed_for"]).strip()


def test_every_required_role_has_at_least_one_checkpoint() -> None:
    covered = {str(record["role"]) for record in frozen.CHECKPOINTS}
    assert covered == set(frozen.REQUIRED_CHECKPOINT_ROLES)


def test_the_two_dead_drive_links_are_served_from_the_readmes_own_mirror() -> None:
    """docs/adr/0129 — obtainability belongs to the artifact, not to a URL."""
    by_role = {str(r["role"]): r for r in frozen.CHECKPOINTS if r["role"] in
               {"coarse_net", "fine_net"}}
    assert set(by_role) == {"coarse_net", "fine_net"}
    for record in by_role.values():
        assert record["source"] == "dropbox"
        assert str(record["locator"]).startswith("https://www.dropbox.com/")


def test_every_upstream_source_the_route_reads_is_pinned_by_digest() -> None:
    for relative, digest in frozen.UPSTREAM_SOURCE_DIGESTS.items():
        assert len(digest) == 64
        assert not relative.startswith("/")
    for named in (
        route.ENCODINGS_SCRIPT,
        route.VISUALISE_SCRIPT,
        route.EVALUATE_SCRIPT,
        route.RECOUNT_SCRIPT,
        route.TRAINING_PAIR_UTILS,
        route.MATCHER_CONSTANTS,
        route.MATCHER_UTILS,
        route.CLASSIFY_UTILS,
        route.CORE_UTILS,
    ):
        assert named in frozen.UPSTREAM_SOURCE_DIGESTS, named


def test_the_matcher_input_arithmetic_is_the_one_upstream_publishes() -> None:
    """Nine features minus two dropped columns plus five neighbours = six in."""
    assert frozen.VERIFY_NET_FEATURE_COUNT == 9
    assert frozen.VERIFY_NET_NEIGHBOURS == 5
    implied = (
        frozen.VERIFY_NET_FEATURE_COUNT - frozen.VERIFY_NET_NEIGHBOURS + 2
    )
    assert implied == len(frozen.MINUTIAE_COLUMNS) + 1


# ------------------------------------------------------------------ the gates


def test_seven_gates_in_a_fixed_order_and_three_states() -> None:
    assert frozen.GATE_ORDER == ("G1", "G2", "G3", "G4", "G5", "G6", "G7")
    assert set(frozen.GATES) == set(frozen.GATE_ORDER)
    assert frozen.GATE_STATES == ("PASS", "FAIL", "NOT_REACHED")


def test_there_is_no_pending_state_for_a_self_service_candidate() -> None:
    assert not any("PEND" in state for state in frozen.GATE_STATES)


def test_three_outcomes_and_route_failure_is_named_apart() -> None:
    assert set(frozen.OUTCOMES) == {
        frozen.OUTCOME_COMPLETE,
        frozen.OUTCOME_ROUTE_FAIL,
        frozen.OUTCOME_QUALIFICATION_FAIL,
    }
    assert frozen.OUTCOME_ROUTE_FAIL != frozen.OUTCOME_QUALIFICATION_FAIL


# ------------------------------------------------------- the decision rule


def test_only_the_last_authority_fails_and_it_is_the_one_that_names_fpbench() -> None:
    assert frozen.ROUTE_AUTHORITIES[-1] == "FPBENCH_WOULD_HAVE_TO_CHOOSE"
    assert frozen.SETTLING_AUTHORITIES == frozenset(frozen.ROUTE_AUTHORITIES[:3])
    assert "FPBENCH_WOULD_HAVE_TO_CHOOSE" not in frozen.SETTLING_AUTHORITIES


def test_a_question_settled_by_fpbench_is_not_settled() -> None:
    unsettled = route.RouteQuestion(
        key="k",
        question="q",
        authority="FPBENCH_WOULD_HAVE_TO_CHOOSE",
        answer=None,
        statements=(),
        why="",
    )
    settled = route.RouteQuestion(
        key="k",
        question="q",
        authority="SINGLE_UNAMBIGUOUS_UPSTREAM_IMPLEMENTATION",
        answer="a",
        statements=(),
        why="",
    )
    assert not unsettled.settled
    assert settled.settled


def test_one_unsettled_question_fails_the_whole_gate() -> None:
    settled = route.RouteQuestion(
        key="a",
        question="q",
        authority="OFFICIAL_INFERENCE_EXAMPLE",
        answer="a",
        statements=(),
        why="",
    )
    unsettled = route.RouteQuestion(
        key="b",
        question="q",
        authority="FPBENCH_WOULD_HAVE_TO_CHOOSE",
        answer=None,
        statements=(),
        why="",
    )
    digests = dict.fromkeys(frozen.UPSTREAM_SOURCE_DIGESTS, "x")
    assert (
        route.RouteClosure(
            questions=(settled,), source_digests={}, sources_present=True
        ).gate_state
        == "PASS"
    )
    closure = route.RouteClosure(
        questions=(settled, unsettled), source_digests={}, sources_present=True
    )
    assert closure.gate_state == "FAIL"
    assert closure.blocker == "UPSTREAM_INFERENCE_ROUTE_NOT_CLOSED"
    assert closure.unsettled == ("b",)
    del digests


def test_altered_upstream_bytes_fail_the_gate_before_any_question_is_read() -> None:
    settled = route.RouteQuestion(
        key="a",
        question="q",
        authority="OFFICIAL_INFERENCE_EXAMPLE",
        answer="a",
        statements=(),
        why="",
    )
    name = next(iter(frozen.UPSTREAM_SOURCE_DIGESTS))
    closure = route.RouteClosure(
        questions=(settled,),
        source_digests={name: "0" * 64},
        sources_present=True,
    )
    assert closure.gate_state == "FAIL"
    assert closure.blocker == "UPSTREAM_SOURCE_BYTES_DO_NOT_MATCH_THE_PIN"


def test_no_question_is_answered_by_running_the_alternatives() -> None:
    """docs/adr/0132 — a tie broken by score is a route chosen from the data."""
    source = (
        REPOSITORY_ROOT / "src/fpbench/experiments/stage16a_route.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    for forbidden in ("verify", "predict", "extract_minutiae"):
        assert forbidden not in called
    assert "experiments_run_to_choose_between_alternatives" in source


def test_all_ten_route_questions_are_named_in_the_frozen_identity() -> None:
    assert len(frozen.ROUTE_QUESTIONS) == 10
    assert len(set(frozen.ROUTE_QUESTIONS)) == 10
    for required in (
        "which_core_is_selected",
        "how_minutiae_are_ordered",
        "how_many_minutiae_are_retained",
        "how_nearest_minutiae_selection_works",
        "how_coordinates_are_made_core_relative",
        "whether_angles_are_transformed",
        "whether_rotation_augmentation_belongs_to_inference",
        "what_happens_if_no_core_is_detected",
        "what_happens_below_the_required_minutiae_count",
        "which_verify_net_precision_and_checkpoint",
    ):
        assert required in frozen.ROUTE_QUESTIONS


# --------------------------------------------------------- the score contract


def test_the_score_contract_is_frozen_with_no_threshold_and_no_transform() -> None:
    assert frozen.SCORE_DIRECTION == "HIGHER_MORE_SIMILAR"
    assert frozen.FPBENCH_SCORE_TRANSFORMATION == "NONE"
    assert frozen.DECISION_THRESHOLD == "NONE"
    assert frozen.CALIBRATION == "NONE"
    assert frozen.LEFT_ARGUMENT == "anchor"
    assert frozen.RIGHT_ARGUMENT == "sample"


def test_asymmetry_is_frozen_rather_than_repaired() -> None:
    assert frozen.SYMMETRY_REQUIRED is False
    assert set(frozen.SYMMETRY_REPAIRS_REFUSED) == {
        "averaging",
        "maximum_of_both_orderings",
    }
    document = finalization.build_score_contract_document(reached=False)
    assert document["argument_binding"]["averaged"] is False
    assert document["argument_binding"]["maximum_of_both_orderings"] is False
    assert document["argument_binding"]["reversed"] is False


def test_the_upstream_range_is_recorded_without_becoming_a_contract() -> None:
    document = finalization.build_score_contract_document(reached=False)
    assert frozen.SCORE_RANGE == "UNSPECIFIED"
    assert document["upstream_readme_range_is_fpbench_contract"] is False


# ----------------------------------------------------------- the failure split


def test_the_two_non_result_classes_are_disjoint_and_both_documented() -> None:
    assert set(frozen.NON_RESULT_CLASSES) == {
        frozen.EXPLICIT_ALGORITHMIC_NON_RESULT,
        frozen.UNHANDLED_IMPLEMENTATION_EXCEPTION,
    }
    for description in frozen.NON_RESULT_CLASSES.values():
        assert description.strip()


def test_the_qualification_probes_exercise_the_case_that_separates_them() -> None:
    assert "no_core_or_insufficient_minutiae" in frozen.FAILURE_PROBES
    assert "invalid_matcher_feature_input" in frozen.FAILURE_PROBES
    assert set(frozen.QUALIFICATION_CASES) == {
        "A_B_repeated",
        "A_B_fresh_object",
        "A_B_fresh_process",
        "B_A",
        "A_A",
    }
    assert frozen.QUALIFICATION_MAX_COMPARISONS == 20


# ------------------------------------------------------------ the predecessor


def test_stage_15a_is_not_replaced_for_anything_a_score_could_say() -> None:
    """docs/adr/0130 — mechanism, and the denials published beside it."""
    document = finalization.build_predecessor_selection_document()
    assert document["reason"] == "STRUCTURAL_EXTRACTION_ROUTE_FAILURE"
    assert document["stage15a_outcome"] == (
        "FINGERPRINTS_MATCHING_CANONICAL500_RAW_COMPLETE"
    )
    assert document["stage15a_selected_for_algorithm_5"] is False
    assert set(document["reason_is_not"]) == {
        "low genuine scores",
        "poor discrimination",
        "worse than another matcher",
    }
    assert document["predecessor_scores_read"] is False
    assert document["stage15a_evidence_modified"] is False
    assert document["stage15a_rerun"] is False


def test_no_predecessor_evidence_statement_carries_a_number() -> None:
    for statement in frozen.PREDECESSOR_EVIDENCE:
        assert not any(character.isdigit() for character in statement), statement


def test_the_forbidden_reads_include_every_algorithm_already_run() -> None:
    for algorithm in ("sourceafis", "nbis", "flx", "verifinger", "fingerprints_matching"):
        assert any(algorithm in read for read in frozen.FORBIDDEN_READS)


# --------------------------------------------------- accepting Algorithm 5

def test_at_least_one_score_is_no_longer_sufficient() -> None:
    document = finalization.build_result_integrity_document(reached=False)
    assert document["at_least_one_score_is_not_sufficient"] is True
    assert len(frozen.ALGORITHM_5_ACCEPTANCE_CONDITIONS) == 4


def test_the_fourth_acceptance_condition_names_no_number() -> None:
    fourth = frozen.ALGORITHM_5_ACCEPTANCE_CONDITIONS[3]
    assert not any(character.isdigit() for character in fourth)
    assert "score-bearing" in fourth


# ---------------------------------------------------------------- the marker


def _documents(*, route_state: str, artifact_state: str = "PASS") -> dict:
    return {
        "artifact_document": {"gate_state": artifact_state, "blocker": None},
        "route_document": {
            "gate_state": route_state,
            "blocker": None if route_state == "PASS" else
            "UPSTREAM_INFERENCE_ROUTE_NOT_CLOSED",
            "questions": [],
            "settled_questions": [],
            "unsettled_questions": [] if route_state == "PASS" else ["x"],
        },
        "score_document": {"gate_state": "NOT_REACHED"},
        "qualification_document": {"gate_state": "NOT_REACHED"},
        "integrity_document": {"gate_state": "NOT_REACHED", "stored_outcomes": 0},
    }


def test_the_outcome_follows_the_first_gate_that_failed() -> None:
    assert finalization.decide_outcome(
        artifact_document={"gate_state": "FAIL", "blocker": "SELF_SERVICE_ARTIFACT_INCOMPLETE"},
        route_document={"gate_state": "NOT_REACHED"},
    ) == (frozen.OUTCOME_QUALIFICATION_FAIL, "SELF_SERVICE_ARTIFACT_INCOMPLETE")
    assert finalization.decide_outcome(
        artifact_document={"gate_state": "PASS"},
        route_document={"gate_state": "FAIL", "blocker": "UPSTREAM_INFERENCE_ROUTE_NOT_CLOSED"},
    ) == (frozen.OUTCOME_ROUTE_FAIL, "UPSTREAM_INFERENCE_ROUTE_NOT_CLOSED")
    assert finalization.decide_outcome(
        artifact_document={"gate_state": "PASS"},
        route_document={"gate_state": "PASS"},
    ) == (frozen.OUTCOME_COMPLETE, None)


def test_a_marker_over_an_unclosed_route_cannot_establish_algorithm_5() -> None:
    marker = finalization.build_stage16a_finalization(
        repository_root=REPOSITORY_ROOT, **_documents(route_state="FAIL")
    )
    assert marker["outcome"] == frozen.OUTCOME_ROUTE_FAIL
    assert marker["algorithm_5_established"] is False
    assert marker["opens_common_calibration"] is False
    assert marker["reopens_algorithm_5_search"] is True
    assert marker["calibration_roster"] == []
    assert marker["adapter_frozen"] is False
    assert marker["canonical_run_executed"] is False
    assert marker["sd300_images_opened"] == 0


def test_a_complete_marker_is_refused_over_a_gate_that_did_not_pass() -> None:
    with pytest.raises(Stage16AFinalizationError):
        finalization.build_stage16a_finalization(
            repository_root=REPOSITORY_ROOT, **_documents(route_state="PASS")
        )


def test_the_marker_fingerprint_covers_everything_but_itself() -> None:
    marker = finalization.build_stage16a_finalization(
        repository_root=REPOSITORY_ROOT, **_documents(route_state="FAIL")
    )
    recomputed = finalization.stage16a_finalization_fingerprint(marker)
    assert recomputed == marker["stage_16a_finalization_fingerprint"]
    assert len(recomputed) == 64
    moved = dict(marker)
    moved["outcome"] = frozen.OUTCOME_QUALIFICATION_FAIL
    assert finalization.stage16a_finalization_fingerprint(moved) != recomputed


def test_the_source_fingerprint_covers_every_file_that_decides_the_outcome() -> None:
    for relative in finalization._SOURCE_FILES:
        assert (REPOSITORY_ROOT / relative).is_file(), relative
    assert len(finalization.stage16a_source_fingerprint(REPOSITORY_ROOT)) == 64


def test_no_fallback_candidate_is_invented() -> None:
    marker = finalization.build_stage16a_finalization(
        repository_root=REPOSITORY_ROOT, **_documents(route_state="FAIL")
    )
    assert marker["fallback_candidate"] is None
    assert marker["why_no_fallback_named"].strip()


# ------------------------------------------------------------- the boundaries


def test_nothing_in_this_stage_produces_a_threshold_or_a_metric() -> None:
    marker = finalization.build_stage16a_finalization(
        repository_root=REPOSITORY_ROOT, **_documents(route_state="FAIL")
    )
    for denial in (
        "threshold_produced",
        "decision_profile_produced",
        "calibration_performed",
        "metrics_produced",
        "score_statistics_published",
        "failure_rates_published",
        "algorithm_ranking_published",
        "prior_algorithm_scores_consulted",
        "fpbench_chose_a_score_affecting_step",
        "third_party_bytes_added_to_git",
    ):
        assert marker[denial] is False, denial
    assert marker["experiments_run_to_choose_between_route_alternatives"] == 0


def test_the_artifact_store_is_outside_the_working_tree() -> None:
    root = artifacts.store_root(repository_root=REPOSITORY_ROOT)
    assert REPOSITORY_ROOT not in Path(root).resolve().parents
    assert Path(root).name == "fingerflow"


def test_acquisition_names_a_locator_for_every_pinned_source_and_artifact() -> None:
    assert set(acquire.PYPI_FILES) == {
        frozen.RUNTIME_ARTIFACT_NAME,
        frozen.SOURCE_ARTIFACT_NAME,
    }
    for url in acquire.PYPI_FILES.values():
        assert url.startswith("https://files.pythonhosted.org/")


def test_evidence_is_exactly_nine_documents() -> None:
    assert len(frozen.EVIDENCE_DOCUMENTS) == 9
    assert frozen.EVIDENCE_DOCUMENTS[0] == "README.md"
    assert frozen.EVIDENCE_DOCUMENTS[-1] == frozen.STAGE_16A_FINALIZATION_NAME
    assert frozen.EVIDENCE_DIRECTORY.as_posix() == "evidence/stage16a-fingerflow"


def test_a_document_carrying_a_real_threshold_is_refused(tmp_path: Path) -> None:
    directory = tmp_path / frozen.EVIDENCE_DIRECTORY
    directory.mkdir(parents=True)
    (directory / "x.json").write_text(json.dumps({"threshold": 40}), encoding="utf-8")
    with pytest.raises(Stage16AFinalizationError):
        finalization._require_no_forbidden_published_data(directory)


def test_a_document_denying_a_threshold_is_allowed(tmp_path: Path) -> None:
    directory = tmp_path / frozen.EVIDENCE_DIRECTORY
    directory.mkdir(parents=True)
    (directory / "x.json").write_text(
        json.dumps({"threshold": "NONE", "calibration": "NONE"}), encoding="utf-8"
    )
    finalization._require_no_forbidden_published_data(directory)


def test_a_document_carrying_an_absolute_machine_path_is_refused(tmp_path: Path) -> None:
    directory = tmp_path / frozen.EVIDENCE_DIRECTORY
    directory.mkdir(parents=True)
    (directory / "x.json").write_text(
        json.dumps({"where": "/home/someone/models"}), encoding="utf-8"
    )
    with pytest.raises(Stage16AFinalizationError):
        finalization._require_no_forbidden_published_data(directory)
