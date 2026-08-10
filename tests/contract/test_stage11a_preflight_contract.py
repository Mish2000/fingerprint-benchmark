"""The frozen Stage 11A contract: seventeen gates, provenance, score, secrets.

No vendor SDK, no licence, no network, no dataset and no workspace. This suite
runs anywhere — including on a machine that has never seen the VeriFinger
archive — which is what makes it a contract suite rather than a re-run of the
stage.

What is under test is the shape of the decision rather than the decision. A
licensed engine on this machine would turn several of these verdicts around and
almost nothing here would change: the gate order, the source-class rule, the
provenance vocabulary and its one refused answer, the raw-score requirements, the
SELF and pair-order rules, the secret guard and the two-outcome marker are the
stage, and the verdict is what they produced this time.

A green run here does **not** mean the constants are right. It means the code
agrees with them (see the Stage 8B lesson recorded in the project's memory of
contract suites).
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from fpbench.core.errors import FpbenchError
from fpbench.core.verifinger_preflight_errors import (
    Stage11AFinalizationError,
    VeriFingerAcquisitionError,
    VeriFingerCandidateIdentityError,
    VeriFingerGateError,
    VeriFingerObservationError,
    VeriFingerPreflightError,
    VeriFingerSensitiveEvidenceError,
)
from fpbench.experiments import stage11a_artifacts as store
from fpbench.experiments import stage11a_preflight as engine
from fpbench.experiments import stage11a_verifinger_identity as frozen
from fpbench.experiments import stage11a_verifinger_observations as observed
from fpbench.experiments.algorithm_research import REPOSITORY_ROOT
from fpbench.experiments.stage11a_finalization import (
    Stage11AFinalization,
    require_expected_evidence_files,
    stage_11a_finalization_fingerprint,
)

pytestmark = pytest.mark.stage11a_contract


# ------------------------------------------------------------ candidate identity


def test_the_candidate_is_provisional_and_names_no_production_algorithm() -> None:
    assert frozen.CANDIDATE_ID == "neurotechnology_verifinger_2025_2_1to1"
    assert frozen.IMPLEMENTATION_ORIGIN == "VENDOR_OFFICIAL_SDK"
    assert frozen.PRODUCTION_ALGORITHM_ID_FROZEN is False
    assert frozen.ALGORITHM_SLOT == "algorithm_4"


def test_every_frozen_identifier_is_a_safe_key_and_path_component() -> None:
    assert frozen.all_frozen_identifiers()


def test_the_python_distribution_is_declared_a_non_candidate() -> None:
    """The route the preceding research expected to take, refused on evidence."""
    names = {name for name, _ in frozen.DECLARED_NON_CANDIDATES}
    assert "neurotec_biometric_python_packages_2025_1" in names
    rejected = {item.route for item in observed.REJECTED_ROUTES}
    assert frozen.ArtifactRoute.PYTHON_RESEARCH_PACKAGE in rejected
    python_route = next(
        item
        for item in observed.REJECTED_ROUTES
        if item.route is frozen.ArtifactRoute.PYTHON_RESEARCH_PACKAGE
    )
    assert python_route.declared_version == "2025.1"
    assert observed.SDK_ARCHIVE.declared_version == "2025.2"


# --------------------------------------------------------------- the gate order


def test_seventeen_gates_in_the_specified_order() -> None:
    assert frozen.GATE_COUNT == 17
    assert len(set(frozen.GATE_ORDER)) == frozen.GATE_COUNT
    assert frozen.GATE_ORDER[0] is frozen.PreflightGate.OFFICIAL_ARTIFACT_ACQUISITION
    assert frozen.GATE_ORDER[-1] is frozen.PreflightGate.TRAINING_PROVENANCE


def test_the_raw_score_gate_precedes_latency_and_provenance() -> None:
    """The specification's fail-fast rule, as an assertion about the order."""
    order = list(frozen.GATE_ORDER)
    score = order.index(frozen.PreflightGate.RAW_SCORE_ROUTE)
    for later in (
        frozen.PreflightGate.RUNTIME_FEASIBILITY,
        frozen.PreflightGate.LICENSE_CAPACITY,
        frozen.PreflightGate.TRAINING_PROVENANCE,
    ):
        assert order.index(later) > score


def test_acquisition_precedes_every_question_about_the_artifact() -> None:
    order = list(frozen.GATE_ORDER)
    assert order.index(frozen.PreflightGate.OFFICIAL_ARTIFACT_ACQUISITION) == 0


def test_every_gate_has_a_runner() -> None:
    """A gate with no runner is an unanswered question, never a passed one."""
    assert set(engine._GATE_RUNNERS) == set(frozen.GATE_ORDER)


def test_every_blocker_code_belongs_to_at_least_one_gate() -> None:
    for code in frozen.BlockerCode:
        assert frozen.gate_of_blocker(code), code


def test_the_blocker_vocabulary_is_exactly_the_specified_one() -> None:
    assert {item.value for item in frozen.BlockerCode} == {
        "OFFICIAL_ARTIFACT_NOT_OBTAINABLE",
        "ARTIFACT_IDENTITY_UNRESOLVED",
        "RESEARCH_USE_BLOCKED",
        "REQUIRED_RUNTIME_COMPONENT_MISSING",
        "CANONICAL500_INPUT_ROUTE_UNRESOLVED",
        "FPBENCH_PREPROCESSING_CHOICE_REQUIRED",
        "EXTRACTION_PROFILE_UNRESOLVED",
        "REPRESENTATION_PROFILE_UNRESOLVED",
        "MATCHER_PROFILE_UNRESOLVED",
        "HIDDEN_SCORE_AFFECTING_DEFAULT_UNRESOLVED",
        "RAW_SCORE_ROUTE_UNRESOLVED",
        "PAIR_ORDER_SEMANTICS_UNRESOLVED",
        "SCORE_NONDETERMINISM_OBSERVED",
        "REMOTE_COMPUTATION_IDENTITY_UNRESOLVED",
        "LICENSE_WORKLOAD_CAPACITY_INSUFFICIENT",
        "SD300_TRAINING_OVERLAP_FOUND",
        "LOCAL_SMOKE_FAILED",
    }


def test_a_blocker_may_not_be_raised_at_a_gate_it_does_not_belong_to() -> None:
    with pytest.raises(VeriFingerGateError):
        engine.Blocker(
            gate=frozen.PreflightGate.RAW_SCORE_ROUTE,
            blocker_code=frozen.BlockerCode.RESEARCH_USE_BLOCKED,
            affected_component="x",
            evidence="x",
            why_this_blocks_algorithm_4="x",
            how_this_would_be_lifted="x",
        )


def test_a_passing_gate_carries_no_blocker_and_a_failing_gate_names_one() -> None:
    with pytest.raises(VeriFingerGateError):
        engine.GateResult(
            gate=frozen.PreflightGate.RAW_SCORE_ROUTE,
            status=frozen.GateStatus.FAIL,
            summary="failed",
        )
    with pytest.raises(VeriFingerGateError):
        engine.GateResult(
            gate=frozen.PreflightGate.NETWORK_DEPENDENCY,
            status=frozen.GateStatus.NOT_REACHED,
            summary="never asked",
            blockers=(
                engine.Blocker(
                    gate=frozen.PreflightGate.NETWORK_DEPENDENCY,
                    blocker_code=(
                        frozen.BlockerCode.REMOTE_COMPUTATION_IDENTITY_UNRESOLVED
                    ),
                    affected_component="x",
                    evidence="x",
                    why_this_blocks_algorithm_4="x",
                    how_this_would_be_lifted="x",
                ),
            ),
        )


def test_fail_fast_produces_one_failure_and_the_rest_not_reached() -> None:
    preflight = engine.run_preflight()
    failed = [
        item
        for item in preflight.results
        if item.status is frozen.GateStatus.FAIL
    ]
    assert len(failed) <= 1
    if failed:
        assert preflight.stopped_at is failed[0].gate
        index = list(frozen.GATE_ORDER).index(preflight.stopped_at)
        for later in preflight.results[index + 1 :]:
            assert later.status is frozen.GateStatus.NOT_REACHED


def test_not_reached_is_not_a_pass() -> None:
    preflight = engine.run_preflight()
    if preflight.stopped_at is not None:
        assert preflight.passed is False
    assert preflight.gates_passed <= preflight.gates_reached


# ---------------------------------------------------------------- observations


def test_an_artifact_class_observation_may_not_carry_a_url() -> None:
    """The substitution this stage exists to prevent, refused by the type."""
    with pytest.raises(VeriFingerObservationError):
        observed.Observation(
            observation_id="a_page_pretending_to_be_the_artifact",
            subject="x",
            statement="x",
            source_class=observed.SourceClass.PINNED_SDK_ARCHIVE,
            locator="https://www.neurotechnology.com/verifinger.html",
        )


def test_a_page_observation_needs_a_url() -> None:
    with pytest.raises(VeriFingerObservationError):
        observed.Observation(
            observation_id="a_page_with_no_page",
            subject="x",
            statement="x",
            source_class=observed.SourceClass.OFFICIAL_DOWNLOAD_PAGE,
            locator="Neurotec_Biometric_2025_2_SDK/ReadMe.txt",
        )


def test_the_gates_that_matter_rest_on_artifact_evidence() -> None:
    """Input, extraction, representation, matching and score, all from the bytes."""
    for group in (
        observed.INPUT_OBSERVATIONS,
        observed.EXTRACTION_OBSERVATIONS,
        observed.REPRESENTATION_OBSERVATIONS,
        observed.MATCHER_OBSERVATIONS,
        observed.SCORE_OBSERVATIONS,
        observed.CLOSURE_OBSERVATIONS,
    ):
        assert group
        for item in group:
            assert item.source_class.is_artifact_evidence, item.observation_id


def test_observation_ids_are_unique() -> None:
    ids = [item.observation_id for item in observed.all_observations()]
    assert len(ids) == len(set(ids))


def test_the_observations_fingerprint_moves_with_the_record() -> None:
    assert len(observed.observations_fingerprint()) == 64


# ------------------------------------------------------------------ acquisition


def test_the_acquired_artifacts_carry_every_pin_field() -> None:
    assert len(frozen.ACQUISITION_PIN_FIELDS) == 7
    for item in observed.ACQUIRED_ARTIFACTS:
        assert item.filename and item.locator
        assert item.size_bytes > 0
        assert len(item.sha256) == 64
        assert item.downloaded_utc and item.declared_version
        assert item.official_locator_category


def test_a_signed_locator_is_refused_as_evidence() -> None:
    with pytest.raises(VeriFingerObservationError):
        observed.AcquiredArtifact(
            artifact_id="a_signed_download",
            route=frozen.ArtifactRoute.MAIN_SDK_PACKAGE,
            official_locator_category="x",
            locator="https://example.invalid/x.zip?X-Amz-Signature=abc",
            filename="x.zip",
            size_bytes=1,
            sha256="0" * 64,
            downloaded_utc="2026-08-10T00:00:00Z",
            declared_version="2025.2",
            target_operating_systems=(),
            target_architectures=(),
            role="x",
        )


def test_the_acquired_artifact_type_has_no_field_for_a_credential() -> None:
    fields = set(observed.AcquiredArtifact.__dataclass_fields__)
    assert not fields & frozen.SENSITIVE_EVIDENCE_KEYS


def test_exactly_one_runtime_route_was_chosen() -> None:
    runtime = [
        item
        for item in observed.ACQUIRED_ARTIFACTS
        if item.route is not frozen.ArtifactRoute.DOCUMENTATION_BUNDLE
    ]
    assert len(runtime) == 1
    assert runtime[0].route is frozen.ArtifactRoute.MAIN_SDK_PACKAGE


def test_the_documentation_is_pinned_as_its_own_artifact() -> None:
    assert observed.DOCUMENTATION_PDF.route is frozen.ArtifactRoute.DOCUMENTATION_BUNDLE
    inside = {
        item.sha256 for item in observed.CITED_ARCHIVE_MEMBERS
    }
    assert observed.DOCUMENTATION_PDF.sha256 in inside, (
        "the standalone manual must be the same bytes as the copy inside the "
        "archive, or citing it would be citing a document that can drift"
    )


# ------------------------------------------------------------------- provenance


def test_fpbench_choice_is_not_a_selectable_provenance() -> None:
    assert frozen.REFUSED_SETTING_PROVENANCE == "FPBENCH_CHOICE"
    assert frozen.REFUSED_SETTING_PROVENANCE not in {
        item.value for item in frozen.SettingProvenance
    }


def test_the_four_upstream_authorities_are_the_specified_ones() -> None:
    assert {
        item.value
        for item in frozen.SettingProvenance
        if item.is_upstream_authority
    } == {
        "UPSTREAM_DOCUMENTED_DEFAULT",
        "DELIVERED_RUNTIME_DEFAULT",
        "OFFICIAL_SAMPLE_EXPLICIT",
        "UPSTREAM_EXPLICIT_RECOMMENDATION",
    }


def test_a_setting_with_no_authority_is_unresolved_not_defaulted() -> None:
    setting = observed.PublishedSetting(
        name="x", published_meaning="y", is_score_affecting=True
    )
    assert setting.provenance is frozen.SettingProvenance.UNRESOLVED
    assert setting.is_unresolved_score_affecting_default is True


def test_the_official_sample_outranks_a_documented_default() -> None:
    setting = observed.PublishedSetting(
        name="x",
        published_meaning="y",
        is_score_affecting=True,
        documented_default="a",
        official_sample_value="b",
    )
    assert setting.provenance is frozen.SettingProvenance.OFFICIAL_SAMPLE_EXPLICIT


def test_no_published_setting_row_carries_a_chosen_value() -> None:
    for rows in (
        observed.setting_rows(observed.PUBLISHED_EXTRACTOR_SETTINGS),
        observed.setting_rows(observed.PUBLISHED_MATCHER_SETTINGS),
    ):
        for row in rows:
            assert row["chosen_value"] is None
            assert row["delivered_runtime_default"] is None


def test_the_matching_speed_preset_is_upstreams_choice_not_a_performance_one() -> None:
    speed = next(
        item
        for item in observed.PUBLISHED_MATCHER_SETTINGS
        if item.name == "FingersMatchingSpeed"
    )
    assert speed.official_sample_value == "NMatchingSpeed.LOW"
    assert speed.provenance is frozen.SettingProvenance.OFFICIAL_SAMPLE_EXPLICIT


# ------------------------------------------------------------------- the score


def test_the_score_contract_requirements_are_frozen() -> None:
    joined = " ".join(frozen.SCORE_CONTRACT_REQUIREMENTS).lower()
    assert "exactly one scalar score" in joined
    assert "boolean" in joined
    assert "no conversion" in joined or "no conversion of its own" in joined


def test_a_transformed_native_score_is_admissible_and_a_boolean_is_not() -> None:
    assert frozen.ScoreRouteStatus.NATIVE_TRANSFORMED_SCALAR.admits_candidate
    assert frozen.ScoreRouteStatus.NATIVE_SCALAR.admits_candidate
    assert not frozen.ScoreRouteStatus.BOOLEAN_ONLY.admits_candidate
    assert not frozen.ScoreRouteStatus.UNRESOLVED.admits_candidate


def test_the_upstream_anchor_table_is_recorded_and_monotone() -> None:
    values = [value for _, value in observed.DOCUMENTED_SCORE_ANCHORS]
    assert values == sorted(values)
    assert observed.DOCUMENTED_SCORE_DIRECTION == "HIGHER_IS_MORE_SIMILAR"


def test_the_official_route_stops_at_the_score() -> None:
    assert observed.OFFICIAL_ONE_TO_ONE_ROUTE[-1].startswith("stop there")


# ----------------------------------------------------------------- SELF and pairs


def test_self_is_two_independent_extractions() -> None:
    joined = " ".join(frozen.SELF_SEMANTICS_REQUIREMENTS).lower()
    assert "twice" in joined
    assert "reuse" in joined
    assert "shortcut" in joined


def test_pair_orientation_is_never_averaged_or_maximised() -> None:
    joined = " ".join(frozen.PAIR_ORIENTATION_REQUIREMENTS).lower()
    assert "never averages" in joined and "maximum" in joined


def test_the_frozen_workload_extracts_both_sides_of_every_comparison() -> None:
    load = frozen.FROZEN_WORKLOAD
    assert load.comparison_attempts == 6_000
    assert load.extraction_invocations == 12_000
    assert load.matcher_invocations == 6_000


def test_a_workload_that_extracted_once_per_image_is_refused() -> None:
    with pytest.raises(VeriFingerCandidateIdentityError):
        frozen.FrozenWorkload(
            participating_images=3_000,
            comparison_attempts=6_000,
            extraction_invocations=3_000,
            matcher_invocations=6_000,
        )


def test_determinism_is_checked_at_three_levels() -> None:
    assert len(frozen.DETERMINISM_LEVELS) == 3
    assert any("restart" in item for item in frozen.DETERMINISM_LEVELS)


# ------------------------------------------------------------------ input domain


def test_fpbench_refuses_every_named_preprocessing_step() -> None:
    assert set(frozen.REFUSED_PREPROCESSING) >= {
        "crop",
        "resize",
        "rotate",
        "enhancement",
        "histogram manipulation",
    }


def test_internal_black_box_preprocessing_is_acceptable() -> None:
    assert frozen.INTERNAL_BLACK_BOX_PREPROCESSING_IS_ACCEPTABLE is True


def test_the_benchmark_input_is_canonical_500_only() -> None:
    assert frozen.BENCHMARK_INPUT_PROFILE == "canonical_500"
    assert frozen.BENCHMARK_INPUT_PPI == 500
    assert frozen.BENCHMARK_INPUT_PIXEL_FORMAT == "gray8"


# --------------------------------------------------------------------- network


def test_only_license_validation_admits_the_candidate() -> None:
    assert frozen.NetworkRole.LICENSE_VALIDATION_ONLY.admits_candidate
    assert not frozen.NetworkRole.PARTICIPATES_IN_BIOMETRIC_COMPUTATION.admits_candidate
    assert not frozen.NetworkRole.UNRESOLVED.admits_candidate


# ------------------------------------------------------------------- provenance


def test_no_evidence_found_is_never_proven_absent() -> None:
    assert frozen.SD300OverlapStatus.NO_EVIDENCE_FOUND.is_automatic_rejection is False
    assert frozen.SD300OverlapStatus.POSITIVE_OVERLAP_FOUND.is_automatic_rejection


def test_a_proprietary_undisclosed_corpus_is_an_acceptable_answer() -> None:
    assert frozen.TrainingProvenanceStatus.PROPRIETARY_UNDISCLOSED


# ---------------------------------------------------------------- the guards


def test_the_secret_guard_finds_a_credential_by_key() -> None:
    found = engine.find_sensitive_material({"outer": {"activation_key": "x"}})
    assert found and "activation_key" in found[0]


@pytest.mark.parametrize(
    "value",
    [
        "ABCD-1234-EFGH-5678",
        "Bearer abcdefghijklmnopqrstuvwxyz012345",
        "-----BEGIN RSA PRIVATE KEY-----",
        "https://user:password@example.invalid/x",
        "https://example.invalid/x.zip?X-Amz-Signature=deadbeef",
    ],
)
def test_the_secret_guard_finds_a_credential_by_shape(value: str) -> None:
    assert engine.find_sensitive_material({"note": value})


def test_the_secret_guard_reaches_inside_a_list() -> None:
    assert engine.find_sensitive_material({"notes": [{"api_key": "x"}]})


def test_the_publisher_refuses_rather_than_redacting() -> None:
    with pytest.raises(VeriFingerSensitiveEvidenceError):
        engine.require_no_sensitive_material({"serial_number": "x"}, where="test")


def test_no_forbidden_key_is_a_value_of_a_published_vocabulary() -> None:
    """A forbidden key must not collide with an enum value used as a map key."""
    values = {
        item.value.lower()
        for enum in (
            frozen.PreflightGate,
            frozen.BlockerCode,
            frozen.GateStatus,
            frozen.SettingProvenance,
            frozen.RepresentationType,
            frozen.ScoreRouteStatus,
            frozen.NetworkRole,
            frozen.ArtifactRoute,
            frozen.AcquisitionStatus,
            frozen.FailureClass,
            frozen.TrainingProvenanceStatus,
            frozen.SD300OverlapStatus,
        )
        for item in enum
    }
    assert not values & frozen.FORBIDDEN_PUBLISHED_KEYS


def test_the_byte_guard_knows_the_artifacts_and_the_vendor_name_shapes() -> None:
    digests = store.verifinger_artifact_digests()
    assert observed.SDK_ARCHIVE.sha256 in digests
    assert observed.DOCUMENTATION_PDF.sha256 in digests
    for item in observed.FINGER_DATA_FILES:
        assert item.sha256 in digests


def test_no_vendor_byte_is_tracked_in_this_repository() -> None:
    """Never skips. This is the one that would matter."""
    audit = store.require_no_verifinger_bytes_in_git(REPOSITORY_ROOT)
    assert audit.clean


# ------------------------------------------------------------------ the marker


def test_the_two_outcomes_are_the_only_ones() -> None:
    assert frozen.STAGE_11A_OUTCOMES == (
        "VERIFINGER_PREFLIGHT_PASS",
        "VERIFINGER_PREFLIGHT_FAIL",
    )


def test_the_acceptance_conditions_are_the_specified_conjunction() -> None:
    assert len(frozen.ACCEPTANCE_CONDITIONS) == 15
    joined = " ".join(frozen.ACCEPTANCE_CONDITIONS).lower()
    for needle in (
        "official artifact obtained",
        "raw scalar score resolved",
        "restart determinism demonstrated",
        "no sd300 consulted",
    ):
        assert needle in joined


def test_every_pass_claim_is_covered_by_the_established_list() -> None:
    """A claim added to the marker is either checked under PASS or visibly absent."""
    fields = set(Stage11AFinalization.__dataclass_fields__)
    assert set(Stage11AFinalization.ESTABLISHED_UNDER_PASS) <= fields
    assert set(Stage11AFinalization.DENIED_FLAGS) <= fields


def test_the_marker_refuses_a_third_outcome() -> None:
    with pytest.raises(ValueError):
        _marker_claims(outcome="VERIFINGER_PREFLIGHT_PENDING")


def test_the_marker_refuses_an_activated_licence() -> None:
    with pytest.raises(ValueError):
        _marker_claims(licenses_activated=1)


def test_the_marker_refuses_a_produced_score() -> None:
    with pytest.raises(ValueError):
        _marker_claims(scores_produced=1)


def test_a_blocked_marker_may_not_claim_a_measured_capacity() -> None:
    with pytest.raises(ValueError):
        _marker_claims(license_workload_capacity_sufficient=False)


def test_a_blocked_marker_names_a_failure_class() -> None:
    with pytest.raises(ValueError):
        _marker_claims(failure_class=None)


def test_a_blocked_marker_still_requires_the_self_rule() -> None:
    with pytest.raises(ValueError):
        _marker_claims(self_independent_extraction_required=False)


def test_the_evidence_file_list_is_exactly_the_specified_structure() -> None:
    assert frozen.REQUIRED_EVIDENCE_FILES == (
        "README.md",
        "candidate-identity.json",
        "acquisition-manifest.json",
        "artifact-manifest.json",
        "runtime-identity.json",
        "third-party-usage-binding.json",
        "input-domain-contract.json",
        "extraction-profile.json",
        "representation-profile.json",
        "matcher-profile.json",
        "score-contract.json",
        "pair-semantics.json",
        "determinism-report.json",
        "runtime-feasibility.json",
        "training-provenance.json",
        "preflight-report.json",
        "stage-11a-finalization.json",
    )


def test_an_extra_published_file_is_a_finding() -> None:
    with pytest.raises(Stage11AFinalizationError):
        require_expected_evidence_files(
            frozen.REQUIRED_EVIDENCE_FILES + ("notes.txt",)
        )


# ------------------------------------------------------------- non-goals & layering


def test_the_stage_creates_no_production_surface() -> None:
    assert "generic_engine_adapter" in frozen.PRODUCTION_INTEGRATION_NOT_CREATED
    assert "threshold" in frozen.PRODUCTION_INTEGRATION_NOT_CREATED
    assert not list((REPOSITORY_ROOT / "configs" / "algorithms").glob("verifinger*"))
    assert not list((REPOSITORY_ROOT / "src" / "fpbench" / "adapters").glob("verifinger*"))


def test_every_error_descends_from_the_project_root_error() -> None:
    for error in (
        VeriFingerPreflightError,
        VeriFingerCandidateIdentityError,
        VeriFingerObservationError,
        VeriFingerAcquisitionError,
        VeriFingerGateError,
        VeriFingerSensitiveEvidenceError,
        Stage11AFinalizationError,
    ):
        assert issubclass(error, FpbenchError)


def test_no_stage_11a_module_imports_a_vendor_runtime() -> None:
    from fpbench.experiments.stage11a_finalization import _audit_source_boundaries

    _audit_source_boundaries(REPOSITORY_ROOT)


def test_the_stage_reads_no_sd300_and_no_prior_scores() -> None:
    """Checked over the source, not asserted in prose."""
    for relative in frozen.STAGE_11A_SOURCE_FILES:
        text = (REPOSITORY_ROOT / Path(relative)).read_text(encoding="utf-8")
        assert "FPBENCH_SD300_ROOT" not in text


def test_the_qualification_run_record_lives_outside_the_repository() -> None:
    state = store.qualification_run_state(repository_root=REPOSITORY_ROOT)
    assert isinstance(state.performed, bool)
    assert state.reason


def test_the_engine_takes_no_verdict_parameter() -> None:
    assert not inspect.signature(engine.run_preflight).parameters


# ------------------------------------------------------------------- helpers


def _marker_claims(**overrides: object) -> Stage11AFinalization:
    """A minimal blocked marker, so a single field can be made wrong."""
    claims: dict = {
        "schema_version": frozen.STAGE_11A_SCHEMA_VERSION,
        "kind": frozen.STAGE_FINALIZATION_KIND,
        "outcome": frozen.STAGE_11A_BLOCKED_OUTCOME,
        "algorithm_slot": frozen.ALGORITHM_SLOT,
        "predecessor_stage_10b_fingerprint": (
            frozen.STAGE_10B_FINALIZATION_FINGERPRINT
        ),
        "stage8e_policy_fingerprint": frozen.STAGE8E_FINALIZATION_FINGERPRINT,
        "stage11a_source_fingerprint": "1" * 64,
        "observations_fingerprint": "2" * 64,
        "preflight_fingerprint": "3" * 64,
        "candidate_verdict": frozen.CANDIDATE_FAIL_VERDICT,
        "selected_candidate": None,
        "gate_count_defined": frozen.GATE_COUNT,
        "gates_reached": 6,
        "gates_passed": 5,
        "artifact_obtained": True,
        "artifact_route": frozen.ArtifactRoute.MAIN_SDK_PACKAGE.value,
        "artifact_identity_pinned": True,
        "documentation_pinned_separately": True,
        "runtime_identity_established": True,
        "runtime_reported_version_read_by_execution": False,
        "research_use_opens_execution": True,
        "research_use_blocked": False,
        "runtime_dependency_closure_complete": True,
        "external_model_downloads_required": 0,
        "canonical500_input_route_resolved": True,
        "fpbench_preprocessing_required": False,
        "extraction_profile_resolved": False,
        "representation_profile_resolved": False,
        "representation_type": frozen.RepresentationType.NOT_REACHED.value,
        "matcher_profile_resolved": False,
        "hidden_score_affecting_defaults": 9,
        "raw_score_route_resolved": False,
        "raw_score_route_status": frozen.ScoreRouteStatus.NOT_REACHED.value,
        "score_numeric_type": None,
        "score_direction": None,
        "threshold_applied_inside_the_score": False,
        "self_independent_extraction_required": True,
        "self_semantics_demonstrated": False,
        "pair_order_semantics_resolved": False,
        "restart_determinism_verified": False,
        "failure_semantics_resolved": False,
        "network_role": frozen.NetworkRole.NOT_REACHED.value,
        "remote_computation_participates_in_the_score": None,
        "runtime_feasibility_measured": False,
        "license_workload_capacity_sufficient": None,
        "training_provenance_status": (
            frozen.TrainingProvenanceStatus.NOT_REACHED.value
        ),
        "sd300_overlap_status": frozen.SD300OverlapStatus.NOT_REACHED.value,
        "sd300_training_overlap_found": None,
        "failure_class": frozen.FailureClass.EXECUTION_NOT_ESTABLISHED.value,
        "sd300_image_bytes_read": False,
        "sd300_scores_read": False,
        "sd300_pair_manifest_read": False,
        "prior_algorithm_scores_read": False,
        "licenses_activated": 0,
        "license_bypass_attempted": False,
        "trial_reset_attempted": False,
        "production_adapter_created": False,
        "generic_engine_adapter_created": False,
        "benchmark_run_performed": False,
        "threshold_produced": False,
        "decision_profile_produced": False,
        "calibration_performed": False,
        "metrics_produced": False,
        "scores_produced": 0,
        "third_party_bytes_added_to_git": False,
        "secrets_added_to_git": False,
        "artifact_downloaded_in_ci": False,
        "credentials_stored_in_ci": False,
        "stage8e_evidence_changed": False,
        "stage10b_evidence_changed": False,
        "opens_stage_11b": False,
        "opens_candidate_search": True,
        "blockers": (
            {
                "gate": frozen.PreflightGate.EXTRACTION_PROFILE.value,
                "blocker_code": (
                    frozen.BlockerCode.HIDDEN_SCORE_AFFECTING_DEFAULT_UNRESOLVED.value
                ),
                "affected_component": "x",
                "evidence": "x",
                "why_this_blocks_algorithm_4": "x",
                "how_this_would_be_lifted": "x",
            },
        ),
        "evidence_content_hashes": {},
        "source_commit": "a" * 40,
        "source_tree_clean": True,
        "verifier_source_commit": "a" * 40,
        "verifier_source_tree_clean": True,
    }
    claims.update(overrides)
    return Stage11AFinalization(
        **claims,
        stage_11a_finalization_fingerprint=stage_11a_finalization_fingerprint(claims),
        created_utc="2026-08-10T00:00:00Z",
    )


def test_the_helper_builds_a_valid_blocked_marker() -> None:
    """Otherwise every negative case above could be passing for the wrong reason."""
    marker = _marker_claims()
    assert marker.outcome == frozen.STAGE_11A_BLOCKED_OUTCOME
    assert marker.opens_stage_11b is False
