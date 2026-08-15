"""The frozen Stage 14A contract: four gates, five states, two markers.

No vendor package, no licence, no network, no dataset and no workspace. This
suite runs anywhere, which is the same claim the stage makes about itself:
without a delivered package there is nothing here but a state machine, a set of
schemas and a route table.

What is under test is the shape of the decision rather than the decision. The
gate order, the ``PENDING_ACCESS``/``ACTION_REQUIRED``/``FAIL`` split that keeps
"somebody has not answered" apart from "we have not asked" and both apart from
"it does not work", the acquisition state machine, the refused-source vocabulary,
the canonical500 input rule and its vendor-internal-crop exception, the raw-score
requirement, the settings closure, the secret guard and the two-outcome marker
are the stage; what they produced on any particular machine is not.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fpbench.core.errors import FpbenchError
from fpbench.core.griaule_preflight_errors import (
    GriauleAcquisitionError,
    GriauleCandidateIdentityError,
    GriauleGateError,
    GriauleObservationError,
    GriaulePreflightError,
    GriauleSensitiveEvidenceError,
    Stage14AFinalizationError,
)
from fpbench.experiments import stage14a_acquisition as store
from fpbench.experiments import stage14a_griaule_identity as frozen
from fpbench.experiments import stage14a_griaule_observations as observed
from fpbench.experiments import stage14a_preflight as engine
from fpbench.experiments.algorithm_research import REPOSITORY_ROOT
from fpbench.experiments.stage14a_finalization import (
    STAGE_14A_BASELINE_COMMIT,
    Stage14AFinalization,
    require_expected_evidence_files,
    stage_14a_finalization_fingerprint,
)

pytestmark = pytest.mark.stage14a_contract


# ------------------------------------------------------------- the vocabulary


def test_every_error_descends_from_the_project_root() -> None:
    for error in (
        GriaulePreflightError,
        GriauleCandidateIdentityError,
        GriauleObservationError,
        GriauleAcquisitionError,
        GriauleGateError,
        GriauleSensitiveEvidenceError,
        Stage14AFinalizationError,
    ):
        assert issubclass(error, FpbenchError)


def test_the_candidate_and_slot_are_frozen() -> None:
    assert frozen.CANDIDATE_ID == "griaule_gbs_fingerprint_sdk_1to1"
    assert frozen.ALGORITHM_SLOT == "algorithm_5"
    assert frozen.IMPLEMENTATION_ORIGIN == "VENDOR_OFFICIAL_SDK"
    assert frozen.PRODUCTION_ALGORITHM_ID_FROZEN is False


def test_the_version_is_a_sentinel_until_a_package_settles_it() -> None:
    assert frozen.IMPLEMENTATION_VERSION_SENTINEL == "UNRESOLVED_UNTIL_PACKAGE"
    assert frozen.VERSION_IS_NOT_TAKEN_FROM_THE_WEBSITE is True
    assert observed.ADVERTISED_VERSION is None


def test_exactly_four_gates_in_a_frozen_order() -> None:
    assert frozen.GATE_COUNT == 4
    assert frozen.GATE_ORDER == (
        frozen.PreflightGate.OFFICIAL_ARTIFACT_AND_TRIAL_ACCESS,
        frozen.PreflightGate.DIRECT_CANONICAL500_INPUT_ROUTE,
        frozen.PreflightGate.SINGLE_FINGER_RAW_1TO1_SCORE_ROUTE,
        frozen.PreflightGate.SCORE_AFFECTING_ROUTE_CLOSURE,
    )


def test_five_gate_states_and_only_two_are_final() -> None:
    assert {member.value for member in frozen.GateStatus} == {
        "PASS",
        "FAIL",
        "PENDING_ACCESS",
        "ACTION_REQUIRED",
        "NOT_REACHED",
    }
    final = {member for member in frozen.GateStatus if member.is_final}
    assert final == {frozen.GateStatus.PASS, frozen.GateStatus.FAIL}


def test_every_state_but_pass_stops_the_run() -> None:
    # Unlike Stage 13A: every gate after acquisition is a question about
    # delivered bytes, so there is nothing to ask around one that did not pass.
    for status in frozen.GateStatus:
        assert status.stops_the_run is (status is not frozen.GateStatus.PASS)


def test_the_four_outcomes_and_the_two_that_may_be_finalized() -> None:
    assert frozen.STAGE_14A_PASS_OUTCOME == "GRIAULE_ARTIFACT_ROUTE_PREFLIGHT_PASS"
    assert frozen.STAGE_14A_FAIL_OUTCOME == "GRIAULE_ARTIFACT_ROUTE_PREFLIGHT_FAIL"
    assert frozen.STAGE_14A_PENDING_OUTCOME == "GRIAULE_PREFLIGHT_PENDING_ACCESS"
    assert frozen.STAGE_14A_INCOMPLETE_OUTCOME == "GRIAULE_PREFLIGHT_INCOMPLETE"
    assert frozen.STAGE_14A_FINAL_OUTCOMES == (
        frozen.STAGE_14A_PASS_OUTCOME,
        frozen.STAGE_14A_FAIL_OUTCOME,
    )


def test_the_blocker_vocabulary_is_exactly_the_ten_named_codes() -> None:
    assert {member.value for member in frozen.BlockerCode} == {
        "VENDOR_ACCESS_REFUSED",
        "OFFICIAL_PACKAGE_UNAVAILABLE",
        "RESEARCH_USE_BLOCKED",
        "BUNDLED_TRIAL_ROUTE_UNAVAILABLE",
        "FPBENCH_PREPROCESSING_REQUIRED",
        "DIRECT_INPUT_ROUTE_UNRESOLVED",
        "RAW_SCORE_ROUTE_UNAVAILABLE",
        "RAW_SCORE_ROUTE_UNRESOLVED",
        "SCORE_AFFECTING_CHOICE_UNRESOLVED",
        "PACKAGE_ROUTE_IDENTITY_UNRESOLVED",
    }


def test_every_blocker_has_a_gate_and_a_failure_class() -> None:
    for code in frozen.BlockerCode:
        assert frozen.gate_of_blocker(code), code
        assert frozen.FailureClass(code.value)


def test_blockers_and_actions_are_disjoint_vocabularies() -> None:
    # The one distinction the stage carries from its first day: an action says
    # something about this project, a blocker about the candidate.
    blockers = {member.value for member in frozen.BlockerCode}
    actions = {member.value for member in frozen.RequiredAction}
    pending = {member.value for member in frozen.PendingKind}
    assert not blockers & actions
    assert not blockers & pending


def test_only_the_acquisition_gate_can_report_an_outstanding_action() -> None:
    # Every later gate is answered by reading bytes; a chore there would be a
    # chore nobody could do without the package.
    for gate, actions in frozen.GATE_ACTIONS:
        if gate is frozen.PreflightGate.OFFICIAL_ARTIFACT_AND_TRIAL_ACCESS:
            assert actions
        else:
            assert actions == ()


def test_the_frozen_identifier_set_is_pinned() -> None:
    identifiers = frozen.all_frozen_identifiers()
    assert len(identifiers) == len(set(identifiers))
    assert "GRIAULE_PREFLIGHT_PENDING_ACCESS" in identifiers
    assert "SEND_ONE_OFFICIAL_ACQUISITION_REQUEST" in identifiers


# ---------------------------------------------------------------- the evidence


def test_the_stage_publishes_eight_documents_a_readme_and_a_marker() -> None:
    assert len(frozen.REQUIRED_EVIDENCE_FILES) == 10
    assert len(frozen.DERIVABLE_EVIDENCE_FILES) == 8
    assert frozen.README_NAME not in frozen.DERIVABLE_EVIDENCE_FILES
    assert frozen.STAGE_14A_FINALIZATION_NAME not in frozen.DERIVABLE_EVIDENCE_FILES


def test_no_two_gates_share_a_document() -> None:
    names = [name for _, names in frozen.GATE_DOCUMENTS for name in names]
    assert len(names) == len(set(names))


def test_the_evidence_directory_must_hold_exactly_what_is_published() -> None:
    with pytest.raises(Stage14AFinalizationError):
        require_expected_evidence_files(("README.md",))
    with pytest.raises(Stage14AFinalizationError):
        require_expected_evidence_files(
            frozen.REQUIRED_EVIDENCE_FILES + ("notes.txt",)
        )


# -------------------------------------------------------------- the observations


def test_no_official_route_offers_the_package() -> None:
    assert observed.SELF_SERVICE_LOCATOR_FOUND is False
    offered = [
        route.route_id
        for route in observed.OFFICIAL_ROUTES
        if route.outcome is observed.RouteOutcome.PACKAGE_OFFERED
    ]
    assert offered == []


def test_the_exhaustion_covers_every_official_channel() -> None:
    walked = {
        route.category
        for route in observed.OFFICIAL_ROUTES
    }
    official = {member for member in frozen.LocatorCategory if member.is_official}
    assert official <= walked


def test_at_least_three_routes_were_actually_retrieved() -> None:
    walked = [
        route
        for route in observed.OFFICIAL_ROUTES
        if route.retrieval is observed.RetrievalStatus.RETRIEVED
    ]
    assert len(walked) >= 3
    for route in walked:
        assert route.retrieved_utc


def test_an_unwalked_route_cannot_report_what_it_found() -> None:
    with pytest.raises(GriauleObservationError):
        observed.OfficialRoute(
            route_id="invented",
            locator="https://example.invalid/",
            category=frozen.LocatorCategory.VENDOR_SUPPORT_DELIVERY,
            description="a route nobody fetched",
            retrieval=observed.RetrievalStatus.NOT_RETRIEVED,
            retrieved_utc=None,
            outcome=observed.RouteOutcome.NO_PACKAGE_OFFERED,
            what_was_found="nothing, because nobody looked",
            blocked_by="nothing",
        )


def test_a_mirror_cannot_be_recorded_as_an_official_route() -> None:
    with pytest.raises(GriauleObservationError):
        observed.OfficialRoute(
            route_id="mirror",
            locator="https://example.invalid/",
            category=frozen.LocatorCategory.THIRD_PARTY_MIRROR,
            description="a mirror",
            retrieval=observed.RetrievalStatus.RETRIEVED,
            retrieved_utc="2026-08-15",
            outcome=observed.RouteOutcome.PACKAGE_OFFERED,
            what_was_found="a package",
            blocked_by="nothing",
        )


def test_a_public_page_is_never_an_authority() -> None:
    for item in observed.PRODUCT_OBSERVATIONS:
        assert item.weight is observed.ObservationWeight.INDICATION_ONLY
    with pytest.raises(GriauleObservationError):
        observed.ProductObservation(
            observation_id="overreach",
            locator="https://docs.griaule.com/sdks/en/fingerprintsdk.md",
            statement="the default threshold is 20",
            retrieval=observed.RetrievalStatus.RETRIEVED,
            retrieved_utc="2026-08-15",
            what_it_indicates="what to look for",
            weight=observed.ObservationWeight.DELIVERED_AUTHORITY,
        )


def test_the_unlicensed_redistribution_route_is_recorded_and_refused() -> None:
    # Recorded rather than omitted: it is the first result a naive search
    # surfaces, and an evidence trail that left it out would not show it was
    # seen and declined.
    categories = {item.category for item in observed.REFUSED_ROUTE_CATEGORIES}
    assert frozen.LocatorCategory.UNLICENSED_REDISTRIBUTION in categories
    assert any(
        "bypass" in item.lower() or "crack" in item.lower()
        for item in frozen.REFUSED_ACQUISITION_SOURCES
    )


def test_the_observations_fingerprint_is_stable_and_covers_the_routes() -> None:
    assert observed.observations_fingerprint() == observed.observations_fingerprint()
    assert len(observed.observations_fingerprint()) == 64


# --------------------------------------------------------------- the acquisition


def test_an_unsent_request_is_a_local_action_and_not_a_vendor_wait() -> None:
    assert store.REQUEST_STATUS is store.RequestStatus.PREPARED_NOT_SENT
    assert store.REQUEST_STATUS.is_sent is False
    assert store.REQUEST_SENT_UTC is None
    assert store.AcquisitionStatus.REQUEST_NOT_SENT.is_a_local_action is True
    assert store.AcquisitionStatus.REQUEST_NOT_SENT.is_pending is False
    assert store.AcquisitionStatus.REQUEST_NOT_SENT.is_refusal is False


def test_only_a_vendor_answer_is_a_refusal() -> None:
    refusals = {
        status for status in store.AcquisitionStatus if status.is_refusal
    }
    assert refusals == {
        store.AcquisitionStatus.ACCESS_REFUSED,
        store.AcquisitionStatus.PACKAGE_UNAVAILABLE,
    }


def test_pending_and_local_action_are_disjoint() -> None:
    for status in store.AcquisitionStatus:
        assert not (status.is_pending and status.is_a_local_action)


def test_a_declaration_needs_a_digest_this_project_computed() -> None:
    with pytest.raises(GriauleAcquisitionError):
        store.PackageDeclaration(
            official_locator_category=(
                frozen.LocatorCategory.VENDOR_SUPPORT_DELIVERY
            ),
            official_locator="https://example.invalid/package",
            filename="package.zip",
            size_bytes=1,
            sha256="not-a-digest",
            obtained_utc="2026-08-15",
            product="GBS Fingerprint SDK",
            product_version="1.0",
            build_or_revision="1",
            platform="linux/x86_64",
            documentation_obtained=True,
            license_obtained=True,
            bundled_trial_present=True,
        )


def test_a_package_from_a_mirror_cannot_be_declared() -> None:
    with pytest.raises(GriauleAcquisitionError):
        store.PackageDeclaration(
            official_locator_category=frozen.LocatorCategory.SOFTWARE_CATALOGUE,
            official_locator="https://example.invalid/package",
            filename="package.zip",
            size_bytes=1,
            sha256="a" * 64,
            obtained_utc="2026-08-15",
            product="GBS Fingerprint SDK",
            product_version="1.0",
            build_or_revision="1",
            platform="linux/x86_64",
            documentation_obtained=True,
            license_obtained=True,
            bundled_trial_present=True,
        )


def test_a_tokenized_locator_is_refused() -> None:
    # A signed URL names one fetch rather than the artifact, and publishing one
    # would put a credential in the evidence.
    with pytest.raises(GriauleAcquisitionError):
        store.PackageDeclaration(
            official_locator_category=(
                frozen.LocatorCategory.VENDOR_SELF_SERVICE_DOWNLOAD
            ),
            official_locator="https://example.invalid/package?token=abc",
            filename="package.zip",
            size_bytes=1,
            sha256="a" * 64,
            obtained_utc="2026-08-15",
            product="GBS Fingerprint SDK",
            product_version="1.0",
            build_or_revision="1",
            platform="linux/x86_64",
            documentation_obtained=True,
            license_obtained=True,
            bundled_trial_present=True,
        )


# --------------------------------------------------------------------- the gates


def test_a_gate_that_passed_carries_nothing() -> None:
    gate = frozen.PreflightGate.DIRECT_CANONICAL500_INPUT_ROUTE
    with pytest.raises(GriauleGateError):
        engine.GateResult(
            gate=gate,
            status=frozen.GateStatus.PASS,
            summary="passed",
            outstanding=engine.OutstandingAction(
                gate=frozen.PreflightGate.OFFICIAL_ARTIFACT_AND_TRIAL_ACCESS,
                action=frozen.RequiredAction.SEND_ONE_OFFICIAL_ACQUISITION_REQUEST,
                what_has_been_done="the routes were walked",
                what_remains=("send it",),
                what_it_would_answer="acquisition",
            ),
        )


def test_a_gate_that_failed_names_why() -> None:
    with pytest.raises(GriauleGateError):
        engine.GateResult(
            gate=frozen.PreflightGate.SINGLE_FINGER_RAW_1TO1_SCORE_ROUTE,
            status=frozen.GateStatus.FAIL,
            summary="something went wrong",
        )


def test_a_waiting_gate_cannot_carry_a_blocker() -> None:
    gate = frozen.PreflightGate.OFFICIAL_ARTIFACT_AND_TRIAL_ACCESS
    blocker = engine.Blocker(
        gate=gate,
        blocker_code=frozen.BlockerCode.VENDOR_ACCESS_REFUSED,
        affected_component="the package",
        evidence="none",
        why_this_blocks_algorithm_5="it would",
        how_this_would_be_lifted="by the vendor",
    )
    for status in (frozen.GateStatus.PENDING_ACCESS, frozen.GateStatus.ACTION_REQUIRED):
        with pytest.raises(GriauleGateError):
            engine.GateResult(
                gate=gate, status=status, summary="waiting", blockers=(blocker,)
            )


def test_a_gate_cannot_wait_on_the_vendor_and_on_this_project_at_once() -> None:
    gate = frozen.PreflightGate.OFFICIAL_ARTIFACT_AND_TRIAL_ACCESS
    pending = engine.PendingReason(
        kind=frozen.PendingKind.VENDOR_REQUEST_SENT_AWAITING_REPLY,
        what_was_walked="the routes",
        what_is_outstanding=("a reply",),
        what_it_would_answer="acquisition",
    )
    action = engine.OutstandingAction(
        gate=gate,
        action=frozen.RequiredAction.SEND_ONE_OFFICIAL_ACQUISITION_REQUEST,
        what_has_been_done="the routes were walked",
        what_remains=("send it",),
        what_it_would_answer="acquisition",
    )
    with pytest.raises(GriauleGateError):
        engine.GateResult(
            gate=gate,
            status=frozen.GateStatus.PENDING_ACCESS,
            summary="both",
            pending=pending,
            outstanding=action,
        )


def test_a_blocker_cannot_be_raised_at_the_wrong_gate() -> None:
    with pytest.raises(GriauleGateError):
        engine.Blocker(
            gate=frozen.PreflightGate.DIRECT_CANONICAL500_INPUT_ROUTE,
            blocker_code=frozen.BlockerCode.RAW_SCORE_ROUTE_UNAVAILABLE,
            affected_component="the matcher",
            evidence="none",
            why_this_blocks_algorithm_5="it would",
            how_this_would_be_lifted="somehow",
        )


def test_a_blocker_names_how_it_would_be_lifted() -> None:
    with pytest.raises(GriauleGateError):
        engine.Blocker(
            gate=frozen.PreflightGate.OFFICIAL_ARTIFACT_AND_TRIAL_ACCESS,
            blocker_code=frozen.BlockerCode.VENDOR_ACCESS_REFUSED,
            affected_component="the package",
            evidence="the vendor declined",
            why_this_blocks_algorithm_5="nothing can be inspected",
            how_this_would_be_lifted="   ",
        )


# ------------------------------------------------------------------ the run


def test_the_live_run_reports_every_gate_in_order() -> None:
    preflight = engine.run_preflight()
    assert tuple(r.gate for r in preflight.results) == frozen.GATE_ORDER
    assert preflight.outcome in frozen.STAGE_14A_OUTCOMES


def test_without_a_package_the_run_stops_at_acquisition() -> None:
    preflight = engine.run_preflight()
    g1 = preflight.status(frozen.PreflightGate.OFFICIAL_ARTIFACT_AND_TRIAL_ACCESS)
    if g1 is frozen.GateStatus.PASS:
        pytest.skip("a package is present on this machine")
    for gate in frozen.GATE_ORDER[1:]:
        assert preflight.status(gate) is frozen.GateStatus.NOT_REACHED


def test_a_non_final_outcome_reopens_nothing() -> None:
    # Griaule is still the candidate under examination; only a FAIL returns the
    # slot to the next one.
    preflight = engine.run_preflight()
    if preflight.is_final:
        pytest.skip("this machine reached a final outcome")
    assert preflight.reopens_algorithm_5_search is False
    assert preflight.opens_stage_14b is False
    assert preflight.failure_class is None


def test_the_preflight_fingerprint_is_stable() -> None:
    assert (
        engine.run_preflight().preflight_fingerprint
        == engine.run_preflight().preflight_fingerprint
    )


def test_every_document_builds_and_is_guarded() -> None:
    preflight = engine.run_preflight()
    for name in frozen.DERIVABLE_EVIDENCE_FILES:
        document = engine.evidence_document(preflight, name)
        assert document["schema"].startswith("stage_14a_")
    with pytest.raises(Stage14AFinalizationError):
        engine.evidence_document(preflight, "not-a-document.json")


# ------------------------------------------------------------- the input rule


def test_fpbench_never_preprocesses_an_image_into_the_extractor() -> None:
    for refused in ("cropping", "resiz", "pad", "rotat", "region of interest"):
        assert any(
            refused in item.lower() for item in frozen.REFUSED_PREPROCESSING
        ), refused


def test_a_vendor_internal_crop_is_algorithm_behaviour() -> None:
    # The distinction the whole gate turns on.
    assert frozen.VENDOR_INTERNAL_CROP_IS_ALGORITHM_BEHAVIOUR is True
    assert frozen.UPSTREAM_EXTRACTION_PIXEL_LIMIT == (500, 500)


def test_a_container_change_must_preserve_pixels_and_geometry() -> None:
    assert len(frozen.DECODE_EQUIVALENCE_REQUIREMENTS) == 2
    joined = " ".join(frozen.DECODE_EQUIVALENCE_REQUIREMENTS).lower()
    assert "identical" in joined and "geometry" in joined


# ------------------------------------------------------------- the score rule


def test_the_score_shape_is_not_assumed_from_the_website() -> None:
    assert frozen.SCORE_SHAPE_IS_NOT_ASSUMED is True
    assert frozen.FPBENCH_SCORE_TRANSFORMATION == "NONE"
    assert frozen.CALIBRATION_PERFORMED is False
    assert frozen.THRESHOLD_PRODUCED is False


def test_the_upstream_defaults_are_recorded_as_observations_only() -> None:
    assert frozen.UPSTREAM_DEFAULT_THRESHOLD_INDICATION == 20
    assert frozen.UPSTREAM_DEFAULT_ROTATION_TOLERANCE_INDICATION == -1
    assert frozen.THRESHOLD_IS_NOT_A_DECISION_HERE is True
    preflight = engine.run_preflight()
    document = engine.evidence_document(preflight, frozen.SCORE_CONTRACT_NAME)
    assert document["threshold"]["used_as_a_decision_here"] is False
    assert document["threshold"]["calibration"] == "NONE"
    assert document["scores_produced_in_this_stage"] == 0


# ----------------------------------------------------------- the settings rule


def test_the_threshold_and_rotation_tolerance_can_never_be_missing() -> None:
    # The vendor's own public documentation proves both exist and are matcher
    # parameters, so an inventory that omitted them would be visibly incomplete.
    assert "verification threshold" in frozen.SETTINGS_TO_ACCOUNT_FOR
    assert "rotation tolerance" in frozen.SETTINGS_TO_ACCOUNT_FOR
    assert set(engine.missing_setting_categories()) == set(
        frozen.SETTINGS_TO_ACCOUNT_FOR
    )


def test_only_a_delivered_value_is_an_authority() -> None:
    upstream = {
        member
        for member in frozen.SettingProvenance
        if member.is_upstream_authority
    }
    assert upstream == {
        frozen.SettingProvenance.DELIVERED_DEFAULT,
        frozen.SettingProvenance.DELIVERED_DOCUMENTATION,
    }
    assert frozen.SettingProvenance.UPSTREAM_PUBLIC_PAGE not in upstream
    assert frozen.SettingProvenance.FPBENCH_CHOICE not in upstream


def test_an_uninspected_package_has_no_closed_settings_surface() -> None:
    # Never zero merely because nobody recorded an inventory.
    assert engine.unresolved_score_affecting_settings() == ()
    assert engine.missing_setting_categories() != ()


def test_no_setting_is_chosen_by_trying_values() -> None:
    assert frozen.NO_SETTING_IS_CHOSEN_BY_TRYING_VALUES is True
    assert frozen.DEFAULT_FPBENCH_CHANGED is False


# ------------------------------------------------------------- the secret guard


@pytest.mark.parametrize(
    "probe",
    [
        {"note": "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE"},
        {"machine_id": "whatever"},
        {"trial_token": "whatever"},
        {"email": "whatever"},
        {"note": "someone@example.com"},
        {"note": "/home/someone/packages"},
        {"note": "https://example.invalid/pkg?token=abc"},
    ],
)
def test_the_guard_bites_on_licence_and_personal_material(probe: dict) -> None:
    assert engine.find_sensitive_material(probe)
    with pytest.raises(GriauleSensitiveEvidenceError):
        engine.require_no_sensitive_material(probe, where="a probe")


def test_a_document_may_never_publish_a_score_or_a_template() -> None:
    for key in ("score", "template", "image_bytes", "decision"):
        assert key in frozen.FORBIDDEN_PUBLISHED_KEYS


# ------------------------------------------------------------------ the marker


def _pass_claims() -> dict:
    """A synthetic PASS marker, for the validation rules only."""
    return {
        "schema_version": frozen.STAGE_14A_SCHEMA_VERSION,
        "kind": frozen.STAGE_FINALIZATION_KIND,
        "outcome": frozen.STAGE_14A_PASS_OUTCOME,
        "algorithm_slot": frozen.ALGORITHM_SLOT,
        "candidate": frozen.CANDIDATE_ID,
        "stage13a_outcome": frozen.STAGE_13A_OUTCOME,
        "stage13a_failure_class": frozen.STAGE_13A_FAILURE_CLASS,
        "stage13a_finalization_fingerprint": (
            frozen.STAGE_13A_FINALIZATION_FINGERPRINT
        ),
        "stage11b_finalization_fingerprint": (
            frozen.STAGE_11B_FINALIZATION_FINGERPRINT
        ),
        "stage8e_policy_fingerprint": frozen.STAGE8E_FINALIZATION_FINGERPRINT,
        "stage14a_source_fingerprint": "a" * 64,
        "observations_fingerprint": "b" * 64,
        "preflight_fingerprint": "c" * 64,
        "gate_count_defined": 4,
        "gates_reached": 4,
        "gates_passed": 4,
        "gates_pending_access": 0,
        "gates_awaiting_action": 0,
        "product": frozen.PRODUCT_FAMILY,
        "implementation_version": "2024.1",
        "build_or_revision": "1234",
        "platform": "linux/x86_64",
        "binding": "CPP",
        "package_sha256": "d" * 64,
        "implementation_origin": frozen.IMPLEMENTATION_ORIGIN,
        "official_package_obtained": True,
        "acquisition_status": "OBTAINED",
        "vendor_refused": False,
        "research_use_opens_execution": True,
        "research_use_blocked": False,
        "bundled_trial_present": True,
        "trial_activated": False,
        "license_bypass_attempted": False,
        "trial_reset_attempted": False,
        "canonical500_route": True,
        "fpbench_preprocessing_required": False,
        "vendor_internal_crop": True,
        "single_finger_template": True,
        "raw_score_route": True,
        "score_native_type": "int",
        "score_direction": "HIGHER_IS_MORE_SIMILAR",
        "threshold_applied_inside_the_score": False,
        "fpbench_score_transformation": frozen.FPBENCH_SCORE_TRANSFORMATION,
        "route_closed": True,
        "unresolved_score_affecting_settings": 0,
        "failure_class": None,
        "scores_produced": 0,
        "sd300_image_bytes_read": False,
        "sd300_pair_manifest_read": False,
        "sd300_scores_read": False,
        "sd300_used": False,
        "prior_algorithm_scores_read": False,
        "production_adapter_created": False,
        "registry_integration_created": False,
        "canonical_experiment_config_created": False,
        "benchmark_run_performed": False,
        "result_set_produced": False,
        "threshold_produced": False,
        "calibration_performed": False,
        "metrics_produced": False,
        "production_algorithm_id_frozen": False,
        "third_party_bytes_added_to_git": False,
        "secrets_added_to_git": False,
        "trial_activated_in_ci": False,
        "credentials_stored_in_ci": False,
        "stage8e_evidence_changed": False,
        "stage11b_evidence_changed": False,
        "stage13a_evidence_changed": False,
        "opens_stage_14b": True,
        "reopens_algorithm_5_search": False,
        "blockers": (),
        "evidence_content_hashes": {"README.md": "e" * 64},
        "source_commit": "0" * 40,
        "source_tree_clean": True,
        "verifier_source_commit": "0" * 40,
        "verifier_source_tree_clean": True,
    }


def _marker(claims: dict) -> Stage14AFinalization:
    return Stage14AFinalization(
        **claims,
        stage_14a_finalization_fingerprint=stage_14a_finalization_fingerprint(claims),
        created_utc="2026-08-15T00:00:00Z",
    )


def test_a_pass_marker_constructs() -> None:
    marker = _marker(_pass_claims())
    assert marker.outcome == frozen.STAGE_14A_PASS_OUTCOME
    assert marker.opens_stage_14b is True


@pytest.mark.parametrize(
    "outcome",
    [frozen.STAGE_14A_PENDING_OUTCOME, frozen.STAGE_14A_INCOMPLETE_OUTCOME],
)
def test_neither_non_final_outcome_can_be_finalized(outcome: str) -> None:
    claims = _pass_claims()
    claims["outcome"] = outcome
    with pytest.raises(ValueError, match="never of a finalization"):
        _marker(claims)


def test_a_finalized_marker_has_no_gate_still_waiting() -> None:
    for name in ("gates_pending_access", "gates_awaiting_action"):
        claims = _pass_claims()
        claims[name] = 1
        with pytest.raises(ValueError, match="waiting"):
            _marker(claims)


def test_a_pass_marker_cannot_carry_the_version_sentinel() -> None:
    claims = _pass_claims()
    claims["implementation_version"] = frozen.IMPLEMENTATION_VERSION_SENTINEL
    with pytest.raises(ValueError, match="sentinel"):
        _marker(claims)


def test_a_pass_marker_cannot_leave_a_setting_unresolved() -> None:
    claims = _pass_claims()
    claims["unresolved_score_affecting_settings"] = 1
    with pytest.raises(ValueError, match="unresolved"):
        _marker(claims)


def test_a_pass_marker_cannot_require_fpbench_preprocessing() -> None:
    claims = _pass_claims()
    claims["fpbench_preprocessing_required"] = True
    with pytest.raises(ValueError, match="is false"):
        _marker(claims)


def test_a_fail_marker_without_a_package_publishes_nulls_not_defaults() -> None:
    claims = _pass_claims()
    claims.update(
        outcome=frozen.STAGE_14A_FAIL_OUTCOME,
        gates_reached=1,
        gates_passed=0,
        official_package_obtained=False,
        acquisition_status="ACCESS_REFUSED",
        vendor_refused=True,
        failure_class=frozen.FailureClass.VENDOR_ACCESS_REFUSED.value,
        opens_stage_14b=False,
        reopens_algorithm_5_search=True,
        blockers=(
            {
                "gate": (
                    frozen.PreflightGate.OFFICIAL_ARTIFACT_AND_TRIAL_ACCESS.value
                ),
                "blocker_code": frozen.BlockerCode.VENDOR_ACCESS_REFUSED.value,
                "affected_component": "the package",
                "evidence": "the vendor declined",
                "why_this_blocks_algorithm_5": "nothing can be inspected",
                "how_this_would_be_lifted": "only by the vendor",
            },
        ),
    )
    for name in (
        "implementation_version",
        "build_or_revision",
        "platform",
        "binding",
        "package_sha256",
        "score_native_type",
        "score_direction",
        "research_use_opens_execution",
        "research_use_blocked",
        "bundled_trial_present",
        "canonical500_route",
        "fpbench_preprocessing_required",
        "vendor_internal_crop",
        "single_finger_template",
        "raw_score_route",
        "threshold_applied_inside_the_score",
        "route_closed",
        "unresolved_score_affecting_settings",
    ):
        claims[name] = None
    marker = _marker(claims)
    assert marker.failure_class == "VENDOR_ACCESS_REFUSED"

    # And the same marker with a plausible default instead of a null is refused.
    for name, value in (
        ("package_sha256", "f" * 64),
        ("research_use_opens_execution", False),
        ("unresolved_score_affecting_settings", 0),
        ("canonical500_route", False),
    ):
        bad = dict(claims)
        bad[name] = value
        with pytest.raises(ValueError):
            _marker(bad)


def test_a_fail_marker_names_its_failure_class() -> None:
    claims = _pass_claims()
    claims.update(
        outcome=frozen.STAGE_14A_FAIL_OUTCOME,
        gates_passed=0,
        failure_class=None,
        opens_stage_14b=False,
        reopens_algorithm_5_search=True,
        blockers=(
            {
                "gate": (
                    frozen.PreflightGate.OFFICIAL_ARTIFACT_AND_TRIAL_ACCESS.value
                ),
                "blocker_code": frozen.BlockerCode.VENDOR_ACCESS_REFUSED.value,
                "affected_component": "the package",
                "evidence": "the vendor declined",
                "why_this_blocks_algorithm_5": "nothing can be inspected",
                "how_this_would_be_lifted": "only by the vendor",
            },
        ),
    )
    with pytest.raises(ValueError, match="what kind of failure"):
        _marker(claims)


def test_a_marker_can_never_report_a_score_or_an_activated_trial() -> None:
    for name in ("trial_activated", "benchmark_run_performed", "metrics_produced"):
        claims = _pass_claims()
        claims[name] = True
        with pytest.raises(ValueError):
            _marker(claims)
    claims = _pass_claims()
    claims["scores_produced"] = 1
    with pytest.raises(ValueError, match="no score"):
        _marker(claims)


def test_the_fingerprint_covers_the_claims() -> None:
    claims = _pass_claims()
    marker = _marker(claims)
    moved = dict(claims)
    moved["platform"] = "windows/x86_64"
    assert stage_14a_finalization_fingerprint(moved) != (
        marker.stage_14a_finalization_fingerprint
    )


# ---------------------------------------------------------------- the boundary


def test_the_baseline_is_the_stage_13a_republish_commit() -> None:
    assert len(STAGE_14A_BASELINE_COMMIT) == 40
    assert STAGE_14A_BASELINE_COMMIT == (
        "db9cfce269705b542681e38f12e41b93a1601ec0"
    )


def test_the_bound_predecessor_is_the_corrected_stage_13a_marker() -> None:
    assert frozen.STAGE_13A_FINALIZATION_FINGERPRINT == (
        "b24bdb672926abfb5dd5a9e03a4c3aab39f51488d9a5413092adef392d99871d"
    )
    assert frozen.STAGE_13A_OUTCOME == "FINGERCELL_PREFLIGHT_FAIL"
    assert frozen.STAGE_13A_FAILURE_CLASS == (
        "OPERATIONAL_TRIAL_ENTITLEMENT_NOT_ESTABLISHED"
    )


def test_the_predecessor_marker_on_disk_still_says_it() -> None:
    marker = json.loads(
        (
            Path(REPOSITORY_ROOT)
            / frozen.STAGE_13A_EVIDENCE_DIRECTORY
            / "stage-13a-finalization.json"
        ).read_text(encoding="utf-8")
    )
    assert marker["stage_13a_finalization_fingerprint"] == (
        frozen.STAGE_13A_FINALIZATION_FINGERPRINT
    )
    assert marker["reopens_algorithm_5_search"] is True
    assert marker["opens_stage_13b"] is False


def test_every_stage_14a_source_file_exists() -> None:
    for relative in frozen.STAGE_14A_SOURCE_FILES:
        assert (Path(REPOSITORY_ROOT) / relative).is_file(), relative
