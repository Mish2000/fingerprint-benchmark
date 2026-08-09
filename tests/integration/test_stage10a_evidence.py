"""The committed Stage 10A evidence, verified with nothing the stage needed.

No dataset, no torch, no checkpoint, no workspace and no prior result set —
which for this stage is not much of a claim, because it never needed any of
them. What is under test is the publication: that it holds exactly the expected
files, that the marker fingerprints to what it carries, that every document
re-derives from source, that the marker's denials are true, and that the exact
bytes have not moved since finalization.

Until the evidence has been published there is nothing here to verify, and these
tests say so by skipping rather than by passing vacuously. The tests that never
skip are the ones that keep that honest — and the ones that check the documents,
which are published one commit before the marker is.
"""

from __future__ import annotations

import json
from pathlib import PurePosixPath

import pytest

from fpbench.core.algorithm4_errors import Stage10AFinalizationError
from fpbench.experiments import stage10a_candidate_evidence as observed
from fpbench.experiments import stage10a_candidate_identity as frozen
from fpbench.experiments import stage10a_preflight as engine
from fpbench.experiments.algorithm_research import REPOSITORY_ROOT
from fpbench.experiments.stage10a_finalization import (
    STAGE_10A_BASELINE_COMMIT,
    Stage10AFinalization,
    file_sha256,
    published_evidence_names,
    require_expected_evidence_files,
    require_no_forbidden_published_data,
    stage10a_source_fingerprint,
    stage_10a_finalization_fingerprint,
    verify_stage10a_workspace_boundaries,
)

pytestmark = pytest.mark.stage10a

EVIDENCE = REPOSITORY_ROOT / frozen.EVIDENCE_DIRECTORY
MARKER = EVIDENCE / frozen.STAGE_10A_FINALIZATION_NAME


def _document(relative: str) -> dict:
    path = EVIDENCE / PurePosixPath(relative)
    if not path.is_file():
        pytest.skip(f"{relative} has not been published yet")
    return json.loads(path.read_text(encoding="utf-8"))


def _marker() -> dict:
    if not MARKER.is_file():
        pytest.skip("the Stage 10A marker has not been published yet")
    return json.loads(MARKER.read_text(encoding="utf-8"))


# --------------------------------------------------------------- the documents


def test_the_evidence_tree_holds_exactly_the_expected_files() -> None:
    if not EVIDENCE.is_dir():
        pytest.skip("Stage 10A evidence has not been published yet")
    names = published_evidence_names(REPOSITORY_ROOT)
    if frozen.STAGE_10A_FINALIZATION_NAME not in names:
        # The documents commit precedes the marker commit by design.
        expected = set(frozen.REQUIRED_EVIDENCE_FILES) - {
            frozen.STAGE_10A_FINALIZATION_NAME
        }
        assert set(names) == expected
        return
    require_expected_evidence_files(names)


def test_no_forbidden_data_reached_the_published_evidence() -> None:
    if not EVIDENCE.is_dir():
        pytest.skip("Stage 10A evidence has not been published yet")
    require_no_forbidden_published_data(REPOSITORY_ROOT)


def test_the_candidate_set_re_derives_and_states_its_non_goals() -> None:
    document = _document(frozen.CANDIDATE_SET_NAME)
    assert document["candidate_count"] == len(frozen.CANDIDATES)
    assert document["gate_order"] == [gate.value for gate in frozen.GATE_ORDER]
    assert document["gates_are_conjunctive_and_unweighted"] is True
    assert document["tie_break_uses_reported_performance"] is False
    assert document["reconnaissance_fingerprint"] == (
        observed.reconnaissance_fingerprint()
    )
    joined = " ".join(document["non_goals"]).lower()
    for absent in ("adapter", "sd300", "threshold", "calibration"):
        assert absent in joined


def test_the_usage_manifest_re_derives_from_the_stage8e_engine() -> None:
    document = _document(frozen.CANDIDATE_SET_NAME)["third_party_usage"]
    audit = engine.build_usage_audit()
    assert document["manifest_fingerprint"] == audit.manifest.manifest_fingerprint
    assert document["audit_fingerprint"] == audit.audit_fingerprint
    assert document["purpose_fingerprint"] == frozen.STAGE8E_PURPOSE_FINGERPRINT
    assert document["policy_fingerprint"] == frozen.STAGE8E_POLICY_FINGERPRINT
    assert document["checkpoints_acquired"] == 0
    for record in document["records"]:
        assert record["stored_in_git"] is False
        assert record["stored_in_ci_artifacts"] is False
        assert record["redistributed_by_fpbench"] is False


def test_the_afrnet_source_discovery_enumerates_where_it_looked() -> None:
    document = _document("afrnet/source-discovery.json")
    assert document["official_source_found"] is False
    assert document["official_checkpoint_found"] is False
    assert document["not_found_is_not_proof_of_absence"] is True
    assert document["locations_searched"] == len(document["locations"])
    assert document["locations_searched"] >= 7
    for location in document["locations"]:
        assert location["locator"].startswith("http")
        assert location["finding"].strip()
        assert location["outcome"] in {
            item.value for item in observed.SearchOutcome
        }


def test_the_jipnet_source_manifest_pins_a_commit_and_no_branch() -> None:
    document = _document("jipnet/source-manifest.json")
    assert len(document["upstream_commit"]) == 40
    assert document["upstream_commit"] in document["source_archive_locator"]
    assert document["source_archive_size_bytes"] > 0
    assert document["branch_names_are_not_identities"] is True
    assert document["acquired_twice_byte_identical"] is True
    assert document["official_checkpoint_locator_is_an_identity"] is False
    for entry in document["cited_files"]:
        assert len(entry["sha256"]) == 64
        assert entry["size_bytes"] > 0


def test_each_authenticity_report_classifies_the_origin() -> None:
    for item in frozen.CANDIDATES:
        document = _document(f"{item.candidate_id}/authenticity-report.json")
        origin = document["implementation_origin"]
        assert origin in {member.value for member in frozen.ImplementationOrigin}
        assert document["origin_is_admissible_for_algorithm_4"] == (
            frozen.ImplementationOrigin(origin).is_admissible_for_algorithm_4
        )
        assert document["accepted_origins"] == [
            member.value for member in frozen.ACCEPTED_ORIGINS
        ]


def test_the_afrnet_origin_is_not_satisfied_by_the_reproduction() -> None:
    document = _document("afrnet/authenticity-report.json")
    assert document["origin_is_admissible_for_algorithm_4"] is False
    assert document["supporting_locators"] == []
    names = {item["identity"] for item in document["declared_non_candidates"]}
    assert "jipnet_authors_adjusted_afrnet_reimplementation" in names
    assert "afr_net" not in names


def test_the_jipnet_input_domain_contract_refuses_invented_construction() -> None:
    document = _document("jipnet/input-domain-contract.json")
    assert document["gate_status"] == frozen.GateStatus.FAIL.value
    assert document["resolution_admits_candidate"] is False
    assert document["transformation_authority"] is None
    assert document["resize_is_assumed_physically_neutral"] is False
    assert document["declared_model_input"]["geometry_pixels"] == [160, 160]
    assert document["declared_model_input"]["declared_ppi"] is None
    assert document["benchmark_input_profile"] == frozen.BENCHMARK_INPUT_PROFILE
    assert len(document["constructions_fpbench_refuses_to_invent"]) >= 6
    assert any(
        item["is_inference_time"] is False for item in document["observations"]
    )


def test_the_afrnet_input_domain_contract_is_not_reached_and_claims_nothing() -> None:
    document = _document("afrnet/input-domain-contract.json")
    assert document["resolution"] == frozen.InputDomainResolution.NOT_REACHED.value
    assert document["observations"] == []
    assert document["transformation_authority"] is None


def test_every_unreached_gate_document_says_so_and_concludes_nothing() -> None:
    unreached = {
        frozen.PreflightGate.ARTIFACTS: frozen.ARTIFACT_MANIFEST_NAME,
        frozen.PreflightGate.INFERENCE_ROUTE: frozen.INFERENCE_ROUTE_AUDIT_NAME,
        frozen.PreflightGate.SCORE_CONTRACT: frozen.SCORE_CONTRACT_NAME,
        frozen.PreflightGate.TRAINING_PROVENANCE: frozen.TRAINING_PROVENANCE_NAME,
        frozen.PreflightGate.RUNTIME_SMOKE: frozen.RUNTIME_SMOKE_NAME,
    }
    for item in frozen.CANDIDATES:
        for gate, name in unreached.items():
            document = _document(f"{item.candidate_id}/{name}")
            assert document["gate"] == gate.value
            assert document["gate_status"] == frozen.GateStatus.NOT_REACHED.value
            assert document["why_not_reached"].strip()
            if "observations_recorded_before_the_stop" in document:
                assert (
                    document["these_observations_are_not_a_gate_conclusion"] is True
                )


def test_no_artifact_manifest_treats_a_drive_folder_as_an_identity() -> None:
    for item in frozen.CANDIDATES:
        document = _document(f"{item.candidate_id}/artifact-manifest.json")
        assert document["bytes_downloaded"] == 0
        assert document["manifests_hold_no_absolute_path"] is True
        for entry in document["would_have_had_to_close_over"]:
            assert entry["locator_is_an_identity"] is False


def test_the_runtime_smoke_documents_record_that_nothing_ran() -> None:
    for item in frozen.CANDIDATES:
        document = _document(f"{item.candidate_id}/runtime-smoke.json")
        assert document["synthetic_fixtures_written"] == 0
        assert document["checkpoint_loaded"] is False
        assert document["forward_pass_executed"] is False
        assert document["sd300_images_used"] is False


def test_the_training_provenance_does_not_claim_proof_of_absence() -> None:
    for item in frozen.CANDIDATES:
        document = _document(f"{item.candidate_id}/training-provenance.json")
        assert document["sd300_overlap_status"] == "NO_EVIDENCE_FOUND"
        assert document["sd300_overlap_found"] is False
        assert document["no_evidence_found_is_not_proven_absent"] is True
        assert document["sd300_data_read_by_this_stage"] is False


def test_the_jipnet_exclusions_are_published_for_a_later_stage() -> None:
    document = _document("jipnet/training-provenance.json")
    assert set(document["future_development_dataset_exclusions"]) == {
        "NIST SD14",
        "FVC2004 DB1_A",
        "FVC2004 DB2_A",
        "FVC2006 DB2_A",
    }


def test_each_preflight_report_carries_its_decisive_question_and_a_one_word_answer() -> None:
    for item in frozen.CANDIDATES:
        document = _document(f"{item.candidate_id}/preflight-report.json")
        assert document["decisive_question"].strip().endswith("?")
        assert document["decisive_answer"] in ("YES", "NO")
        assert document["decisive_answer_basis"].strip()
        assert document["verdict"] in (item.pass_outcome, item.fail_outcome)
        assert len(document["gates"]) == 7
        assert document["what_this_candidate_cost"]["checkpoint_bytes_downloaded"] == 0
        for blocker in document["blockers"]:
            assert blocker["blocker_code"] in {
                member.value for member in frozen.BlockerCode
            }
            assert blocker["why_this_blocks_algorithm_4"].strip()


def test_the_preflight_reports_re_derive_from_source() -> None:
    outcome = engine.run_preflight()
    for preflight in outcome.candidates:
        document = _document(f"{preflight.candidate_id}/preflight-report.json")
        assert document["verdict"] == preflight.verdict
        assert document["stopped_at_gate"] == (
            preflight.stopped_at.value if preflight.stopped_at else None
        )
        assert [entry["status"] for entry in document["gates"]] == [
            result.status.value for result in preflight.results
        ]


def test_the_comparison_re_derives_and_ranks_nothing() -> None:
    document = _document(frozen.CANDIDATE_COMPARISON_NAME)
    outcome = engine.run_preflight()
    assert document["outcome"] == outcome.outcome
    assert document["survivor_count"] == len(outcome.survivors)
    assert document["ranking_performed"] is False
    assert document["selection_based_on_reported_performance"] is False
    assert document["reported_performance_read"] is False
    assert len(document["gate_matrix"]) == 7


# ------------------------------------------------------------------ the marker


def test_the_marker_reconstructs_and_fingerprints_to_what_it_carries() -> None:
    document = _marker()
    claims = {
        key: value
        for key, value in document.items()
        if key not in ("stage_10a_finalization_fingerprint", "created_utc")
    }
    claims["blockers"] = tuple(claims["blockers"])
    assert stage_10a_finalization_fingerprint(claims) == (
        document["stage_10a_finalization_fingerprint"]
    )
    marker = Stage10AFinalization(
        **claims,
        stage_10a_finalization_fingerprint=document[
            "stage_10a_finalization_fingerprint"
        ],
        created_utc=document["created_utc"],
    )
    assert marker.outcome in frozen.STAGE_10A_OUTCOMES


def test_the_marker_binds_the_stage8e_policy_it_reused() -> None:
    document = _marker()
    assert document["stage8e_policy_fingerprint"] == (
        frozen.STAGE8E_FINALIZATION_FINGERPRINT
    )
    engine.require_stage8e_is_the_policy_this_reuses(REPOSITORY_ROOT)


def test_the_marker_pins_the_source_and_the_reconnaissance_that_decided_this() -> None:
    document = _marker()
    assert document["stage10a_source_fingerprint"] == stage10a_source_fingerprint(
        REPOSITORY_ROOT
    )
    assert document["reconnaissance_fingerprint"] == (
        observed.reconnaissance_fingerprint()
    )
    assert document["preflight_fingerprint"] == (
        engine.run_preflight().preflight_fingerprint
    )


def test_the_marker_denies_everything_this_stage_did_not_do() -> None:
    document = _marker()
    for name in Stage10AFinalization.DENIED_FLAGS:
        assert document[name] is False, name
    assert document["candidate_checkpoint_bytes_downloaded"] == 0
    assert document["gates_evaluated_per_candidate"] == 7


def test_a_no_survivor_marker_names_its_blockers_and_opens_a_search() -> None:
    document = _marker()
    if document["outcome"] == frozen.STAGE_10A_SELECTED_OUTCOME:
        assert document["selected_candidate"] in ("AFRNET", "JIPNET")
        assert document["opens_algorithm4_artifact_qualification"] is True
        assert document["opens_candidate_search"] is False
        return
    assert document["outcome"] == frozen.STAGE_10A_NO_SURVIVOR_OUTCOME
    assert document["selected_candidate"] is None
    assert document["survivor_count"] == 0
    assert document["blockers"]
    assert document["opens_algorithm4_artifact_qualification"] is False
    assert document["opens_candidate_search"] is True
    for blocker in document["blockers"]:
        assert blocker["candidate"] in {
            item.candidate_id for item in frozen.CANDIDATES
        }
        assert blocker["gate"] in {gate.value for gate in frozen.GATE_ORDER}
        assert blocker["blocker_code"] in {
            member.value for member in frozen.BlockerCode
        }
        assert blocker["affected_component"].strip()
        assert blocker["evidence"].strip()
        assert blocker["why_this_blocks_algorithm_4"].strip()


def test_the_published_bytes_have_not_moved_since_finalization() -> None:
    document = _marker()
    for name, digest in document["evidence_content_hashes"].items():
        assert file_sha256(EVIDENCE / PurePosixPath(name)) == digest, name
    hashed = set(document["evidence_content_hashes"])
    expected = set(frozen.REQUIRED_EVIDENCE_FILES) - {
        frozen.STAGE_10A_FINALIZATION_NAME
    }
    assert hashed == expected


def test_stage10a_stayed_inside_its_own_span() -> None:
    document = _marker()
    verify_stage10a_workspace_boundaries(
        REPOSITORY_ROOT, span_end_commit=document["verifier_source_commit"]
    )


def test_no_candidate_byte_and_no_third_party_byte_is_tracked() -> None:
    from fpbench.third_party import require_no_third_party_bytes_in_git

    assert engine.require_no_candidate_bytes_in_git(REPOSITORY_ROOT).clean
    assert require_no_third_party_bytes_in_git(REPOSITORY_ROOT).clean


def test_the_closed_stages_are_byte_for_byte_what_they_published() -> None:
    """Stage 10A reads Stage 8E, reads nothing of Stage 9A, and writes to neither.

    Measured across Stage 10A's own span rather than from an arbitrary point,
    for the reason docs/adr/0067 gives: a comparison against something outside
    the span attributes somebody else's commits to this stage.
    """
    import subprocess

    completed = subprocess.run(
        (
            "git",
            "-C",
            str(REPOSITORY_ROOT),
            "diff",
            "--name-only",
            STAGE_10A_BASELINE_COMMIT,
            "HEAD",
            "--",
            "evidence/stage8e-research-only-policy",
            "evidence/stage9a-flare-artifact-qualification",
            "src/fpbench/third_party",
            "src/fpbench/core/third_party_models.py",
            "src/fpbench/core/third_party_errors.py",
            "src/fpbench/core/flare_errors.py",
        ),
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    changed = [line for line in completed.stdout.splitlines() if line]
    assert changed == [], changed


def test_the_evidence_gate_refuses_an_unexpected_published_file() -> None:
    """Never skips: the refusal is what makes the file list a contract."""
    with pytest.raises(Stage10AFinalizationError, match="nothing accounts for"):
        require_expected_evidence_files(
            frozen.REQUIRED_EVIDENCE_FILES + ("afrnet/notes.json",)
        )


def test_the_evidence_gate_refuses_a_missing_document() -> None:
    with pytest.raises(Stage10AFinalizationError, match="missing"):
        require_expected_evidence_files(("README.md",))


def test_the_readme_names_the_outcome_and_both_decisive_answers() -> None:
    path = EVIDENCE / frozen.README_NAME
    if not path.is_file():
        pytest.skip("Stage 10A evidence has not been published yet")
    text = path.read_text(encoding="utf-8")
    assert frozen.STAGE_10A_NO_SURVIVOR_OUTCOME in text
    for item in frozen.CANDIDATES:
        assert item.marker_token in text
    assert "NO_EVIDENCE_FOUND" in text
    # Both decisive questions are answered, in one word each.
    assert text.count("```text\nNO\n```") == 2
