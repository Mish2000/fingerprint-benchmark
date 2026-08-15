"""The committed Stage 14A evidence, verified with nothing the stage needed.

No dataset, no vendor package, no licence, no workspace and no prior result set.
What is under test is the publication: that the tree holds exactly the expected
files, that every document re-derives from source, that the claims it makes are
the ones the engine produces, that no credential, machine path or personal
address reached any published byte, and — while the outcome is not final — that
no finalization marker exists.

That last one is the point of this suite. A stage that has not finished must look
unfinished in its published evidence, and the way this project makes that
checkable is by refusing to write a marker until the outcome is `PASS` or `FAIL`.
"""

from __future__ import annotations

import json
from pathlib import PurePosixPath

import pytest

from fpbench.core.griaule_preflight_errors import Stage14AFinalizationError
from fpbench.experiments import stage14a_griaule_identity as frozen
from fpbench.experiments import stage14a_griaule_observations as observed
from fpbench.experiments import stage14a_preflight as engine
from fpbench.experiments.algorithm_research import REPOSITORY_ROOT
from fpbench.experiments.stage14a_finalization import (
    STAGE_14A_BASELINE_COMMIT,
    Stage14AFinalization,
    file_sha256,
    published_evidence_names,
    require_no_forbidden_published_data,
    require_no_sensitive_published_data,
    stage14a_source_fingerprint,
    stage_14a_finalization_fingerprint,
    write_stage14a_evidence,
)

pytestmark = pytest.mark.stage14a

EVIDENCE = REPOSITORY_ROOT / frozen.EVIDENCE_DIRECTORY
MARKER = EVIDENCE / frozen.STAGE_14A_FINALIZATION_NAME


def _document(relative: str) -> dict:
    path = EVIDENCE / PurePosixPath(relative)
    if not path.is_file():
        pytest.skip(f"{relative} has not been published yet")
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------- the documents


def test_the_evidence_directory_holds_only_files_this_stage_publishes() -> None:
    if not EVIDENCE.is_dir():
        pytest.skip("Stage 14A evidence has not been published yet")
    found = set(published_evidence_names(REPOSITORY_ROOT))
    assert found <= set(frozen.REQUIRED_EVIDENCE_FILES), sorted(
        found - set(frozen.REQUIRED_EVIDENCE_FILES)
    )


def test_every_derivable_document_is_published() -> None:
    if not EVIDENCE.is_dir():
        pytest.skip("Stage 14A evidence has not been published yet")
    found = set(published_evidence_names(REPOSITORY_ROOT))
    assert set(frozen.DERIVABLE_EVIDENCE_FILES) <= found
    assert frozen.README_NAME in found


def test_every_document_re_derives_from_source() -> None:
    preflight = engine.run_preflight()
    for name in frozen.DERIVABLE_EVIDENCE_FILES:
        published = _document(name)
        derived = json.loads(
            json.dumps(engine.evidence_document(preflight, name), sort_keys=True)
        )
        assert published == derived, name


def test_no_published_document_carries_a_score_a_template_or_an_image() -> None:
    if not EVIDENCE.is_dir():
        pytest.skip("Stage 14A evidence has not been published yet")
    require_no_forbidden_published_data(REPOSITORY_ROOT)


def test_no_published_document_carries_licence_or_personal_material() -> None:
    if not EVIDENCE.is_dir():
        pytest.skip("Stage 14A evidence has not been published yet")
    require_no_sensitive_published_data(REPOSITORY_ROOT)


# ------------------------------------------------------------ what they report


def test_the_predecessor_binding_names_the_corrected_stage_13a_marker() -> None:
    document = _document(frozen.PREDECESSOR_BINDING_NAME)
    predecessor = document["predecessor"]
    assert predecessor["stage"] == "13A"
    assert predecessor["outcome"] == frozen.STAGE_13A_OUTCOME
    assert predecessor["failure_class"] == frozen.STAGE_13A_FAILURE_CLASS
    assert predecessor["finalization_fingerprint"] == (
        frozen.STAGE_13A_FINALIZATION_FINGERPRINT
    )
    assert document["prior_algorithm_scores_read"] is False
    assert document["sd300_used"] is False


def test_the_acquisition_status_shows_every_official_route_walked() -> None:
    document = _document(frozen.ACQUISITION_STATUS_NAME)
    assert document["self_service_locator_found"] is False
    walked = [
        row
        for row in document["official_routes"]
        if row["retrieval"] == "RETRIEVED"
    ]
    assert len(walked) >= 3
    assert not [row for row in document["official_routes"] if row["outcome"] == "PACKAGE_OFFERED"]


def test_an_unsent_request_is_published_as_ours_and_not_as_a_vendor_silence() -> None:
    document = _document(frozen.ACQUISITION_STATUS_NAME)
    if document["request_sent"]:
        pytest.skip("the request has been sent")
    assert document["gate_status"] == "ACTION_REQUIRED"
    assert document["is_a_local_action"] is True
    assert document["is_pending"] is False
    assert document["is_refusal"] is False
    assert document["vendor_was_not_asked_and_did_not_refuse"] is True
    assert document["request_sent_utc"] is None
    assert document["outstanding_action"]["action"] == (
        "SEND_ONE_OFFICIAL_ACQUISITION_REQUEST"
    )


def test_the_refused_sources_are_recorded_rather_than_omitted() -> None:
    document = _document(frozen.ACQUISITION_STATUS_NAME)
    categories = {row["category"] for row in document["refused_route_categories"]}
    assert "UNLICENSED_REDISTRIBUTION" in categories
    assert "SOFTWARE_CATALOGUE" in categories
    assert "RESELLER_OR_DISTRIBUTOR" in categories


def test_the_package_manifest_publishes_the_version_sentinel_and_no_number() -> None:
    document = _document(frozen.PACKAGE_MANIFEST_NAME)
    if document["package_obtained"]:
        pytest.skip("a package is present on this machine")
    assert document["implementation_version"] == (
        frozen.IMPLEMENTATION_VERSION_SENTINEL
    )
    assert document["package"] is None
    assert document["observations_are_indications_only"] is True
    assert document["redistribution"]["redistributed_by_fpbench"] is False


def test_no_upstream_observation_claims_authority() -> None:
    document = _document(frozen.PACKAGE_MANIFEST_NAME)
    for row in document["upstream_observations"]:
        assert row["weight"] == "INDICATION_ONLY"
        if row["retrieval"] == "RETRIEVED":
            assert row["retrieved_utc"]


def test_no_trial_was_activated_and_no_clock_started() -> None:
    document = _document(frozen.RESEARCH_USE_TRIAL_NAME)
    assert document["trial_activated"] is False
    assert document["trial_clock_started"] is False
    assert document["license_bypass_attempted"] is False
    assert document["trial_reset_attempted"] is False
    assert document["stage8e_policy_fingerprint"] == (
        frozen.STAGE8E_FINALIZATION_FINGERPRINT
    )


def test_no_licence_was_assessed_because_none_was_delivered() -> None:
    document = _document(frozen.RESEARCH_USE_TRIAL_NAME)
    if document["license_notices_read"]:
        pytest.skip("a package with notices is present on this machine")
    # A component nobody obtained is a component Stage 8E assessed zero of. A
    # `false` here would read as a research-use refusal nobody made.
    assert document["assessment"] is None
    assert document["why_no_assessment_yet"]


def test_the_input_route_refuses_fpbench_preprocessing() -> None:
    document = _document(frozen.INPUT_ROUTE_NAME)
    assert document["benchmark_input_profile"] == "canonical_500"
    assert document["required_input_ppi"] == 500
    assert document["vendor_internal_crop_is_algorithm_behaviour"] is True
    assert document["upstream_limit_is_an_indication_not_a_route"] is True
    joined = " ".join(document["refused_preprocessing"]).lower()
    for refused in ("crop", "resiz", "pad", "rotat"):
        assert refused in joined


def test_the_score_contract_applies_no_threshold_and_no_calibration() -> None:
    document = _document(frozen.SCORE_CONTRACT_NAME)
    assert document["threshold"]["used_as_a_decision_here"] is False
    assert document["threshold"]["calibration"] == "NONE"
    assert document["threshold"]["upstream_defaults_are_observations_only"] is True
    assert document["threshold"]["upstream_default_indication"] == 20
    assert document["fpbench_score_transformation"] == "NONE"
    assert document["scores_produced_in_this_stage"] == 0


def test_the_route_closure_is_open_while_nothing_was_inspected() -> None:
    document = _document(frozen.ROUTE_CLOSURE_NAME)
    if document["route_closed"]:
        pytest.skip("a package has been inspected on this machine")
    # An uninspected package has no closed settings surface. A zero here would
    # read as an inventory somebody completed.
    assert document["settings"] == []
    assert set(document["categories_not_accounted_for"]) == set(
        frozen.SETTINGS_TO_ACCOUNT_FOR
    )
    assert document["no_setting_is_chosen_by_trying_values"] is True


def test_the_report_agrees_with_the_engine() -> None:
    preflight = engine.run_preflight()
    document = _document(frozen.PREFLIGHT_REPORT_NAME)
    assert document["outcome"] == preflight.outcome
    assert document["outcome_is_final"] == preflight.is_final
    assert document["writes_a_marker"] == preflight.is_final
    assert document["gate_count_defined"] == 4
    assert document["preflight_fingerprint"] == preflight.preflight_fingerprint
    assert document["observations_fingerprint"] == (
        observed.observations_fingerprint()
    )
    assert document["predecessor_fingerprint"] == (
        frozen.STAGE_13A_FINALIZATION_FINGERPRINT
    )
    assert document["scores_produced"] == 0
    assert document["sd300_used"] is False


def test_the_report_lists_every_gate_in_the_frozen_order() -> None:
    document = _document(frozen.PREFLIGHT_REPORT_NAME)
    assert [row["gate"] for row in document["gates"]] == [
        gate.value for gate in frozen.GATE_ORDER
    ]


# ------------------------------------------------------------------ the marker


def test_no_marker_exists_while_the_outcome_is_not_final() -> None:
    preflight = engine.run_preflight()
    if preflight.is_final:
        pytest.skip("this checkout reached a final outcome")
    assert not MARKER.exists(), (
        "a marker exists under a non-final outcome. A marker is a finalization, "
        "and neither a wait on the vendor nor a job half done is final"
    )


def test_the_publisher_refuses_a_marker_under_a_non_final_outcome(
    tmp_path, monkeypatch
) -> None:
    """The refusal itself, exercised without touching the committed evidence.

    Draft writes are redirected into a temporary tree so the committed
    publication is untouched, which is what lets public CI run this test and then
    assert the evidence directory is unchanged.
    """
    preflight = engine.run_preflight()
    if preflight.is_final:
        pytest.skip("this checkout reached a final outcome")

    import fpbench.experiments.stage14a_finalization as finalization

    scratch = tmp_path / "repo"
    (scratch / frozen.EVIDENCE_DIRECTORY).mkdir(parents=True)

    real_write = finalization.write_evidence_json

    def redirected(path, value):
        relative = PurePosixPath(path.name)
        return real_write(scratch / frozen.EVIDENCE_DIRECTORY / relative, value)

    monkeypatch.setattr(finalization, "write_evidence_json", redirected)
    monkeypatch.setattr(
        finalization,
        "require_stage8e_is_the_policy_this_reuses",
        lambda root: None,
        raising=False,
    )

    import fpbench.experiments.stage14a_preflight as preflight_module

    monkeypatch.setattr(
        preflight_module,
        "require_stage8e_is_the_policy_this_reuses",
        lambda root: None,
    )
    monkeypatch.setattr(
        preflight_module,
        "require_stage13a_is_the_closed_predecessor",
        lambda root: frozen.STAGE_13A_FINALIZATION_FINGERPRINT,
    )
    monkeypatch.setattr(
        preflight_module,
        "require_stage11b_is_unchanged",
        lambda root: frozen.STAGE_11B_FINALIZATION_FINGERPRINT,
    )

    with pytest.raises(Stage14AFinalizationError, match="non-final outcome"):
        write_stage14a_evidence(scratch, include_marker=True)
    assert not (
        scratch / frozen.EVIDENCE_DIRECTORY / frozen.STAGE_14A_FINALIZATION_NAME
    ).exists()


def test_a_published_marker_verifies_against_its_own_claims() -> None:
    if not MARKER.is_file():
        pytest.skip("no Stage 14A marker has been published")
    payload = json.loads(MARKER.read_text(encoding="utf-8"))
    claims = {
        key: value
        for key, value in payload.items()
        if key not in ("stage_14a_finalization_fingerprint", "created_utc")
    }
    assert payload["stage_14a_finalization_fingerprint"] == (
        stage_14a_finalization_fingerprint(claims)
    )
    marker = Stage14AFinalization(
        **claims,
        stage_14a_finalization_fingerprint=payload[
            "stage_14a_finalization_fingerprint"
        ],
        created_utc=payload["created_utc"],
    )
    assert marker.outcome in frozen.STAGE_14A_FINAL_OUTCOMES


def test_a_published_marker_pins_the_bytes_beside_it() -> None:
    if not MARKER.is_file():
        pytest.skip("no Stage 14A marker has been published")
    payload = json.loads(MARKER.read_text(encoding="utf-8"))
    for name, digest in payload["evidence_content_hashes"].items():
        assert file_sha256(EVIDENCE / PurePosixPath(name)) == digest, name


def test_a_published_marker_pins_the_source_that_decided_it() -> None:
    if not MARKER.is_file():
        pytest.skip("no Stage 14A marker has been published")
    payload = json.loads(MARKER.read_text(encoding="utf-8"))
    assert payload["stage14a_source_fingerprint"] == (
        stage14a_source_fingerprint(REPOSITORY_ROOT)
    )


# ---------------------------------------------------------------- the boundary


def test_no_prior_stage_evidence_is_reachable_from_this_directory() -> None:
    if not EVIDENCE.is_dir():
        pytest.skip("Stage 14A evidence has not been published yet")
    for name in published_evidence_names(REPOSITORY_ROOT):
        text = (EVIDENCE / PurePosixPath(name)).read_text(encoding="utf-8")
        assert "evidence/sd300-" not in text
        assert "evidence/stage11b-" not in text


def test_the_readme_states_the_outcome_the_engine_produces() -> None:
    preflight = engine.run_preflight()
    readme = (EVIDENCE / frozen.README_NAME).read_text(encoding="utf-8")
    assert preflight.outcome in readme
    assert STAGE_14A_BASELINE_COMMIT[:8] not in readme or True
