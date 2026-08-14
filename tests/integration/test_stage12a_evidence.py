"""The committed Stage 12A evidence, verified with nothing the stage needed.

No dataset, no vendor package, no licence, no workspace and no prior result set —
which for this stage is not much of a claim, because without a delivered package
it never needed any of them. What is under test is the publication: that it holds
exactly the expected files, that every document re-derives from source, that the
claims it makes are the ones the engine produces, that no credential or machine
path reached any published byte, and that the final marker binds the refusal to
the exact published bytes.

Until the evidence has been published there is nothing here to verify, and these
tests say so by skipping rather than by passing vacuously.
"""

from __future__ import annotations

import json
from pathlib import PurePosixPath

import pytest

from fpbench.experiments import stage12a_idkit_identity as frozen
from fpbench.experiments import stage12a_idkit_observations as observed
from fpbench.experiments import stage12a_preflight as engine
from fpbench.experiments.algorithm_research import REPOSITORY_ROOT
from fpbench.experiments.stage12a_finalization import (
    STAGE_12A_BASELINE_COMMIT,
    Stage12AFinalization,
    file_sha256,
    published_evidence_names,
    require_expected_evidence_files,
    require_no_forbidden_published_data,
    require_no_sensitive_published_data,
    stage12a_source_fingerprint,
    stage_12a_finalization_fingerprint,
)

pytestmark = pytest.mark.stage12a

EVIDENCE = REPOSITORY_ROOT / frozen.EVIDENCE_DIRECTORY
MARKER = EVIDENCE / frozen.STAGE_12A_FINALIZATION_NAME


def _document(relative: str) -> dict:
    path = EVIDENCE / PurePosixPath(relative)
    if not path.is_file():
        pytest.skip(f"{relative} has not been published yet")
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------- the documents


def test_the_evidence_directory_holds_exactly_the_expected_files() -> None:
    if not EVIDENCE.is_dir():
        pytest.skip("the Stage 12A evidence has not been published yet")
    names = published_evidence_names(REPOSITORY_ROOT)
    require_expected_evidence_files(
        names, marker_expected=frozen.STAGE_12A_FINALIZATION_NAME in names
    )


def test_every_derivable_document_re_derives_from_source() -> None:
    """The bytes on disk are what the engine produces from what it recorded."""
    preflight = engine.run_preflight()
    for name in frozen.DERIVABLE_EVIDENCE_FILES:
        published = _document(name)
        derived = json.loads(
            json.dumps(engine.evidence_document(preflight, name), ensure_ascii=False)
        )
        assert published == derived, f"{name} has drifted from what derives it"


def test_no_published_byte_carries_a_credential_or_a_machine_path() -> None:
    if not EVIDENCE.is_dir():
        pytest.skip("the Stage 12A evidence has not been published yet")
    require_no_sensitive_published_data(REPOSITORY_ROOT)


def test_no_published_byte_carries_upstream_material() -> None:
    if not EVIDENCE.is_dir():
        pytest.skip("the Stage 12A evidence has not been published yet")
    require_no_forbidden_published_data(REPOSITORY_ROOT)


def test_the_readme_exists_and_names_the_outcome() -> None:
    path = EVIDENCE / frozen.README_NAME
    if not path.is_file():
        pytest.skip("the Stage 12A README has not been published yet")
    text = path.read_text(encoding="utf-8")
    preflight = engine.run_preflight()
    assert preflight.outcome in text
    assert frozen.CANDIDATE_ID in text


# ------------------------------------------------------------- what it claims


def test_the_acquisition_document_publishes_the_vendor_refusal() -> None:
    document = _document(frozen.ACQUISITION_STATUS_NAME)
    status = frozen.AcquisitionStatus(document["acquisition_status"])
    assert document["is_pending"] is status.is_pending
    assert document["is_refusal"] is status.is_refusal
    assert document["pending_is_not_a_failure"] is True
    assert status is frozen.AcquisitionStatus.ACCESS_REFUSED
    assert document["gate_status"] == frozen.GateStatus.FAIL.value
    assert document["vendor_was_not_asked_and_did_not_refuse"] is False
    assert document["vendor_response_received"] is True
    assert document["vendor_response_date"] == "2026-08-14"
    assert document["vendor_channel"] == frozen.DeliveryChannel.VENDOR_SALES.value
    assert document["package_obtained"] is False
    assert document["license_offered"] is False
    assert document["what_would_change_the_status"] == []


def test_every_published_route_carries_a_locator_and_an_outcome() -> None:
    document = _document(frozen.ACQUISITION_STATUS_NAME)
    routes = document["official_routes"]
    assert len(routes) == len(observed.ACQUISITION_ROUTES)
    for route in routes:
        assert route["locator"]
        assert route["outcome"]
        assert route["what_was_found"]


def test_the_package_manifest_publishes_no_identity_it_does_not_have() -> None:
    document = _document(frozen.PACKAGE_MANIFEST_NAME)
    if document["identity"] is None:
        assert document["documentation_obtained"] is False
        assert document["selected_binding"] is None
    else:
        assert set(document["identity"]) == set(frozen.PACKAGE_IDENTITY_FIELDS)
    assert document["advertised_version_is_authoritative"] is False
    assert document["vendor_bytes_in_repository"] is False


def test_the_license_document_publishes_no_decision_nobody_made() -> None:
    """A component nobody obtained is a component Stage 8E assessed none of."""
    document = _document(frozen.RESEARCH_USE_LICENSE_NAME)
    if not document["package_obtainable"]:
        assert document["research_use_decision"] is None
        assert document["research_use_opens_execution"] is None
        assert document["third_party_components_assessed"] == 0
        assert document["why_no_assessment_exists"]
    assert document["research_use_blocked"] is False
    assert document["license_bypass_attempted"] is False
    assert document["redistributed_by_fpbench"] is False


def test_the_input_route_document_keeps_every_refusal() -> None:
    document = _document(frozen.INPUT_ROUTE_NAME)
    assert document["benchmark_input"]["pixels_per_inch"] == 500
    assert document["benchmark_input"]["pixel_format"] == "gray8"
    assert set(document["refused_preprocessing"]) == set(frozen.REFUSED_PREPROCESSING)
    assert document["fpbench_preprocessing_required"] is False
    assert document["dpi_must_be_set_before_extraction"] is True


def test_the_route_profile_publishes_no_template_bytes() -> None:
    document = _document(frozen.FINGERPRINT_ROUTE_PROFILE_NAME)
    assert document["template_bytes_published"] is False
    assert "a consolidated multi-finger record score" in (
        document["refused_multi_finger_constructions"]
    )
    assert document["refused_setting_provenance"] == frozen.REFUSED_SETTING_PROVENANCE


def test_the_score_contract_publishes_no_transformation() -> None:
    document = _document(frozen.SCORE_CONTRACT_NAME)
    assert document["fpbench_score_transformation"] == "none"
    assert document["threshold_belongs_to_a_later_stage"] is True
    assert document["refused_threshold_manipulation"]


def test_the_qualification_document_never_claims_a_fake_run_answered_a_gate() -> None:
    document = _document(frozen.QUALIFICATION_RUN_NAME)
    assert document["sd300_fixtures_used"] is False
    assert document["max_scoring_comparisons"] == 20
    if not document["run_by_delivered_sdk"]:
        assert document["run"] is None
    else:
        assert document["run"]["engine_kind"] == "DELIVERED_SDK"
    assert document["pair_role_binding"] == {
        "pair.left": "probe",
        "pair.right": "gallery",
    }


def test_the_provenance_document_separates_not_reached_from_no_evidence() -> None:
    document = _document(frozen.TRAINING_PROVENANCE_NAME)
    status = document["sd300_overlap_status"]
    if status == frozen.SD300OverlapStatus.NOT_REACHED.value:
        assert document["sd300_training_overlap_found"] is None
    else:
        assert document["sd300_training_overlap_found"] is not None


def test_the_report_agrees_with_the_engine() -> None:
    document = _document(frozen.PREFLIGHT_REPORT_NAME)
    preflight = engine.run_preflight()
    assert document["outcome"] == preflight.outcome
    assert document["gate_count_defined"] == frozen.GATE_COUNT
    assert document["gates_reached"] == preflight.gates_reached
    assert document["gates_passed"] == preflight.gates_passed
    assert document["preflight_fingerprint"] == preflight.preflight_fingerprint
    assert len(document["gates"]) == frozen.GATE_COUNT
    assert document["opens_stage_12b"] == preflight.opens_stage_12b
    assert document["reopens_algorithm_5_search"] is True


def test_the_predecessor_binding_names_the_stage_it_follows() -> None:
    document = _document(frozen.PREDECESSOR_BINDING_NAME)
    assert document["predecessor"]["outcome"] == frozen.STAGE_11B_OUTCOME
    assert (
        document["predecessor"]["finalization_fingerprint"]
        == frozen.STAGE_11B_FINALIZATION_FINGERPRINT
    )
    assert document["stage_11a_evidence_changed"] is False
    assert document["stage_11b_evidence_changed"] is False
    assert document["stage_8e_evidence_changed"] is False
    assert document["production_algorithm_id_frozen"] is False


# ------------------------------------------------------------------ the marker


def test_the_marker_is_absent_for_exactly_as_long_as_the_run_is_pending() -> None:
    """The claim that keeps 'pending' from becoming a third finalisation."""
    if not EVIDENCE.is_dir():
        pytest.skip("the Stage 12A evidence has not been published yet")
    preflight = engine.run_preflight()
    if preflight.outcome == frozen.STAGE_12A_PENDING_OUTCOME:
        assert not MARKER.is_file(), (
            "a marker is published and the preflight is pending; one of the two "
            "is wrong, and it is not the preflight"
        )
    else:
        assert MARKER.is_file(), (
            "the run reached a final outcome and no marker was published"
        )


def test_the_publisher_has_a_final_outcome_to_publish() -> None:
    preflight = engine.run_preflight()
    assert preflight.outcome == frozen.STAGE_12A_FAIL_OUTCOME
    assert MARKER.is_file()


def test_the_marker_verifies_against_the_bytes_it_was_derived_from() -> None:
    if not MARKER.is_file():
        pytest.skip("the Stage 12A marker has not been published yet")
    marker = json.loads(MARKER.read_text(encoding="utf-8"))
    for name, expected in marker["evidence_content_hashes"].items():
        assert file_sha256(EVIDENCE / PurePosixPath(name)) == expected
    assert stage_12a_finalization_fingerprint(
        {
            key: value
            for key, value in marker.items()
            if key
            not in ("stage_12a_finalization_fingerprint", "created_utc")
        }
    ) == marker["stage_12a_finalization_fingerprint"]


def test_the_marker_reconstructs_as_the_model_that_validates_it() -> None:
    if not MARKER.is_file():
        pytest.skip("the Stage 12A marker has not been published yet")
    marker = json.loads(MARKER.read_text(encoding="utf-8"))
    marker["blockers"] = tuple(marker["blockers"])
    finalization = Stage12AFinalization(**marker)
    assert finalization.opens_stage_12b is False
    assert finalization.reopens_algorithm_5_search is True


def test_the_source_fingerprint_matches_this_checkout() -> None:
    if not MARKER.is_file():
        pytest.skip("the Stage 12A marker has not been published yet")
    marker = json.loads(MARKER.read_text(encoding="utf-8"))
    assert marker["stage12a_source_fingerprint"] == stage12a_source_fingerprint(
        REPOSITORY_ROOT
    )


def test_the_baseline_commit_is_an_ancestor_of_this_checkout() -> None:
    import subprocess

    completed = subprocess.run(
        (
            "git",
            "-C",
            str(REPOSITORY_ROOT),
            "merge-base",
            "--is-ancestor",
            STAGE_12A_BASELINE_COMMIT,
            "HEAD",
        ),
        check=False,
        capture_output=True,
    )
    assert completed.returncode == 0, (
        "Stage 12A's baseline commit is not an ancestor of this checkout, so the "
        "boundary audit would be measuring a span that does not exist"
    )
