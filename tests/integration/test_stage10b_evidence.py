"""The committed Stage 10B evidence, verified with nothing the stage needed.

No dataset, no vendor SDK, no licence, no workspace and no prior result set —
which for this stage is not much of a claim, because it never needed any of
them. What is under test is the publication: that it holds exactly the expected
files, that the marker fingerprints to what it carries, that every document
re-derives from source, that the marker's denials are true, that no credential
reached any published byte, and that the exact bytes have not moved since
finalization.

Until the evidence has been published there is nothing here to verify, and these
tests say so by skipping rather than by passing vacuously. The tests that never
skip are the ones that keep that honest — and the ones that check the documents,
which are published one commit before the marker is.
"""

from __future__ import annotations

import json
from pathlib import PurePosixPath

import pytest

from fpbench.core.id3_preflight_errors import Stage10BFinalizationError
from fpbench.experiments import stage10b_id3_identity as frozen
from fpbench.experiments import stage10b_id3_observations as observed
from fpbench.experiments import stage10b_preflight as engine
from fpbench.experiments.algorithm_research import REPOSITORY_ROOT
from fpbench.experiments.stage10b_finalization import (
    STAGE_10B_BASELINE_COMMIT,
    Stage10BFinalization,
    file_sha256,
    published_evidence_names,
    require_expected_evidence_files,
    require_no_forbidden_published_data,
    require_no_sensitive_published_data,
    stage10b_source_fingerprint,
    stage_10b_finalization_fingerprint,
    verify_stage10b_workspace_boundaries,
)

pytestmark = pytest.mark.stage10b

EVIDENCE = REPOSITORY_ROOT / frozen.EVIDENCE_DIRECTORY
MARKER = EVIDENCE / frozen.STAGE_10B_FINALIZATION_NAME


def _document(relative: str) -> dict:
    path = EVIDENCE / PurePosixPath(relative)
    if not path.is_file():
        pytest.skip(f"{relative} has not been published yet")
    return json.loads(path.read_text(encoding="utf-8"))


def _marker() -> dict:
    if not MARKER.is_file():
        pytest.skip("the Stage 10B marker has not been published yet")
    return json.loads(MARKER.read_text(encoding="utf-8"))


# --------------------------------------------------------------- the documents


def test_the_evidence_directory_holds_exactly_the_expected_files() -> None:
    if not EVIDENCE.is_dir():
        pytest.skip("the Stage 10B evidence has not been published yet")
    names = published_evidence_names(REPOSITORY_ROOT)
    if frozen.STAGE_10B_FINALIZATION_NAME not in names:
        require_expected_evidence_files(names + (frozen.STAGE_10B_FINALIZATION_NAME,))
        return
    require_expected_evidence_files(names)


def test_every_derivable_document_re_derives_from_source() -> None:
    """The bytes on disk are what the engine produces from what it recorded."""
    preflight = engine.run_preflight()
    for name in frozen.REQUIRED_EVIDENCE_FILES:
        if name in (frozen.README_NAME, frozen.STAGE_10B_FINALIZATION_NAME):
            continue
        published = _document(name)
        derived = json.loads(
            json.dumps(
                _plain(engine.evidence_document(preflight, name)), ensure_ascii=False
            )
        )
        assert published == derived, name


def _plain(value: object) -> object:
    from fpbench.core.serialization import to_plain

    return to_plain(value)


def test_no_forbidden_data_is_published() -> None:
    if not EVIDENCE.is_dir():
        pytest.skip("the Stage 10B evidence has not been published yet")
    require_no_forbidden_published_data(REPOSITORY_ROOT)


def test_no_credential_is_published() -> None:
    """Never vacuous while the directory exists: it walks every published byte."""
    if not EVIDENCE.is_dir():
        pytest.skip("the Stage 10B evidence has not been published yet")
    require_no_sensitive_published_data(REPOSITORY_ROOT)


def test_the_candidate_identity_is_provisional_and_binds_stage_10a() -> None:
    document = _document(frozen.CANDIDATE_IDENTITY_NAME)
    assert document["candidate_id"] == frozen.CANDIDATE_ID
    assert document["candidate_id_is_provisional"] is True
    assert document["production_algorithm_id_frozen"] is False
    predecessor = document["predecessor"]
    assert predecessor["outcome"] == frozen.STAGE_10A_OUTCOME
    assert (
        predecessor["finalization_fingerprint"]
        == frozen.STAGE_10A_FINALIZATION_FINGERPRINT
    )
    assert predecessor["stage_10a_evidence_modified_by_stage_10b"] is False


def test_the_gate_documents_report_the_gate_they_belong_to() -> None:
    for gate, names in frozen.GATE_DOCUMENTS:
        for name in names:
            document = _document(name)
            assert document["gate"] == gate.value, name


def test_every_not_reached_document_says_so_and_concludes_nothing() -> None:
    preflight = engine.run_preflight()
    for gate in frozen.GATE_ORDER:
        if preflight.status(gate) is not frozen.GateStatus.NOT_REACHED:
            continue
        for name in frozen.gate_documents(gate):
            document = _document(name)
            assert document["gate_status"] == "NOT_REACHED", name
            assert document["why_not_reached"], name
            if "observations_recorded_before_the_stop" in document:
                assert (
                    document["these_observations_are_not_a_gate_conclusion"] is True
                ), name


def test_the_preflight_report_names_every_blocker_with_a_lift() -> None:
    document = _document(frozen.PREFLIGHT_REPORT_NAME)
    assert document["verdict"] == frozen.CANDIDATE_FAIL_VERDICT
    assert document["stopped_at_gate"] == "ACQUISITION_ACCESS"
    assert document["gate_count_defined"] == 10
    assert document["gates_reached"] == 2
    assert document["blockers"]
    for blocker in document["blockers"]:
        assert blocker["how_this_would_be_lifted"].strip()
    assert document["acceptance_conditions_met"] is False
    assert len(document["acceptance_conditions"]) == 13


def test_the_report_names_the_workarounds_that_were_not_considered() -> None:
    document = _document(frozen.PREFLIGHT_REPORT_NAME)
    joined = " ".join(document["no_workaround_was_considered"]).lower()
    assert "bypass" in joined
    assert "reset" in joined


def test_the_stage_cost_nothing_it_said_it_cost_nothing() -> None:
    document = _document(frozen.PREFLIGHT_REPORT_NAME)
    assert document["what_this_candidate_cost"] == {
        "package_bytes_downloaded": 0,
        "model_bytes_downloaded": 0,
        "licences_activated": 0,
        "runtime_environments_built": 0,
        "sd300_images_read": 0,
        "scores_produced": 0,
    }


def test_the_unresolved_locators_are_published_with_their_status_codes() -> None:
    document = _document(frozen.PUBLIC_PRODUCT_OBSERVATIONS_NAME)
    rows = document["locators_that_did_not_resolve"]
    assert len(rows) == len(observed.UNRESOLVED_LOCATORS)
    assert all(row["http_status"] == 404 for row in rows)


def test_the_licence_report_publishes_the_cost_under_each_metering() -> None:
    document = _document(frozen.LICENSE_CAPABILITY_REPORT_NAME)
    assert document["capacity_status"] == "UNRESOLVED"
    assert document["capacity_admits_candidate"] is False
    assert document["logical_workload"] == {
        "comparison_attempts": 6_000,
        "extraction_invocations": 12_000,
        "matcher_invocations": 6_000,
        "qualification_high_level_operations_upper_bound": 200,
    }
    assert document["high_level_biometric_operations"] == 18_200
    assert document["sdk_metered_call_count"] == "UNRESOLVED"
    assert document["a_biometric_operation_count_is_not_an_api_call_count"] is True
    assert "cost_under_each_metering_semantics" not in document
    assert document["frozen_workload"]["comparison_attempts"] == 6_000
    assert document["frozen_workload"]["extraction_invocations"] == 12_000
    assert document["every_publishable_fact_is_null_because_no_licence_exists"] is True


def test_the_access_document_keeps_access_and_research_use_apart() -> None:
    document = _document(frozen.ACCESS_QUALIFICATION_NAME)
    assert document["operational_access_is_not_research_use"] is True
    assert document["research_use_decision_owner"] == "stage_8e"
    assert document["research_use_blocked_by_this_stage"] is False
    assert document["third_party_components"]["components_obtained"] == 0
    assert document["third_party_components"]["stage_8e_usage_manifest_written"] is False
    assert document["secrets_recorded_here"] == 0
    assert document["runtime_target"]["locked"] is False
    assert document["runtime_target"]["chosen_target"] is None


# ------------------------------------------------------------------ the marker


def test_the_marker_fingerprints_to_what_it_carries() -> None:
    document = _marker()
    expected = stage_10b_finalization_fingerprint(
        {
            key: value
            for key, value in document.items()
            if key not in ("stage_10b_finalization_fingerprint", "created_utc")
        }
    )
    assert document["stage_10b_finalization_fingerprint"] == expected


def test_the_marker_reconstructs_as_the_model_that_wrote_it() -> None:
    document = _marker()
    marker = Stage10BFinalization(
        **{
            key: value
            for key, value in document.items()
            if key not in ("stage_10b_finalization_fingerprint", "created_utc")
        },
        stage_10b_finalization_fingerprint=document[
            "stage_10b_finalization_fingerprint"
        ],
        created_utc=document["created_utc"],
    )
    assert marker.outcome == document["outcome"]


def test_the_marker_binds_the_source_that_decided_the_preflight() -> None:
    document = _marker()
    assert document["stage10b_source_fingerprint"] == stage10b_source_fingerprint(
        REPOSITORY_ROOT
    )
    assert document["observations_fingerprint"] == observed.observations_fingerprint()
    assert document["preflight_fingerprint"] == engine.run_preflight().preflight_fingerprint


def test_the_marker_binds_the_two_closed_stages() -> None:
    document = _marker()
    assert (
        document["predecessor_stage_10a_fingerprint"]
        == frozen.STAGE_10A_FINALIZATION_FINGERPRINT
    )
    assert (
        document["stage8e_policy_fingerprint"]
        == frozen.STAGE8E_FINALIZATION_FINGERPRINT
    )
    engine.require_stage10a_is_the_closed_predecessor(REPOSITORY_ROOT)
    engine.require_stage8e_is_the_policy_this_reuses(REPOSITORY_ROOT)


def test_the_published_bytes_have_not_moved_since_finalization() -> None:
    document = _marker()
    for name, digest in document["evidence_content_hashes"].items():
        assert file_sha256(EVIDENCE / PurePosixPath(name)) == digest, name


def test_the_marker_covers_every_file_but_itself() -> None:
    document = _marker()
    assert set(document["evidence_content_hashes"]) == set(
        name
        for name in frozen.REQUIRED_EVIDENCE_FILES
        if name != frozen.STAGE_10B_FINALIZATION_NAME
    )


def test_the_marker_denies_everything_this_stage_did_not_do() -> None:
    document = _marker()
    for name in Stage10BFinalization.DENIED_FLAGS:
        assert document[name] is False, name


def test_the_marker_publishes_the_unestablished_as_unestablished() -> None:
    document = _marker()
    assert document["outcome"] == frozen.STAGE_10B_BLOCKED_OUTCOME
    assert document["selected_candidate"] is None
    assert document["research_use_opens_execution"] is None
    assert document["license_workload_capacity_sufficient"] is None
    for name in ("score_type", "score_range_min", "score_range_max", "score_direction"):
        assert document[name] is None, name
    assert document["training_provenance_status"] == "NOT_REACHED"
    assert document["sd300_overlap_status"] == "NOT_REACHED"
    assert document["sd300_training_overlap_found"] is None
    assert document["hidden_score_affecting_defaults"] == 7


def test_the_marker_says_the_failure_is_access_and_not_impossibility() -> None:
    document = _marker()
    assert document["failure_class"] == "OPERATIONAL_ACCESS_NOT_ESTABLISHED"
    assert document["id3_proven_unobtainable"] is False


def test_the_access_document_separates_possession_from_obtainability() -> None:
    document = _document(frozen.ACCESS_QUALIFICATION_NAME)
    state = document["acquisition_state"]
    assert state["package_possession_status"] == "NOT_OBTAINED"
    assert state["package_obtainability_status"] == "NOT_TESTED"
    assert state["obtainability_is_a_negative_finding"] is False
    assert state["package_proven_unobtainable"] is False
    assert document["license_state"]["license_obtainability_status"] == "NOT_TESTED"
    assert document["license_state"]["license_refused_by_vendor"] is False


def test_the_report_says_what_the_outcome_does_not_say() -> None:
    document = _document(frozen.PREFLIGHT_REPORT_NAME)
    assert document["failure_class"] == "OPERATIONAL_ACCESS_NOT_ESTABLISHED"
    assert document["id3_proven_unobtainable"] is False
    joined = " ".join(document["what_this_outcome_does_not_say"]).lower()
    assert "cannot be obtained" in joined
    assert "refused" in joined


def test_the_marker_opens_a_candidate_search_and_not_stage_10c() -> None:
    document = _marker()
    assert document["opens_stage_10c"] is False
    assert document["opens_candidate_search"] is True


def test_the_self_rule_is_published_even_though_nothing_ran() -> None:
    document = _marker()
    assert document["self_independent_extraction_required"] is True


# --------------------------------------------------------------- the boundary


def test_the_stage_changed_only_its_own_surface() -> None:
    document = _marker()
    verify_stage10b_workspace_boundaries(
        REPOSITORY_ROOT, span_end_commit=document["verifier_source_commit"]
    )


def test_the_baseline_is_the_commit_that_re_closed_stage_10a() -> None:
    assert len(STAGE_10B_BASELINE_COMMIT) == 40


def test_no_id3_material_is_tracked_here() -> None:
    """Never skips: it is true before the evidence exists and after."""
    audit = engine.require_no_id3_bytes_in_git(REPOSITORY_ROOT)
    assert audit.clean


def test_nothing_of_the_vendor_sdk_is_present_on_this_machine_by_accident() -> None:
    """Never skips. Absence is the stage's result, not an accident of the runner."""
    state = engine.package_acquisition_state(repository_root=REPOSITORY_ROOT)
    assert state.obtained is False


def test_an_absent_evidence_directory_is_a_refusal_and_not_an_empty_pass() -> None:
    with pytest.raises(Stage10BFinalizationError, match="no published"):
        published_evidence_names(REPOSITORY_ROOT / "does-not-exist")
