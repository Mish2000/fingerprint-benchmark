"""The frozen Stage 10B contract: ten gates, access, capacity, profiles, secrets.

No vendor SDK, no licence, no network, no dataset and no workspace. This suite
runs anywhere, which is the same claim the stage makes about itself: everything
before the tenth gate is a reading exercise over descriptions of a product.

What is under test is the shape of the decision rather than the decision. A
delivered package would turn most of these verdicts around and almost nothing
here would change — the gate order, the access/research-use split, the capacity
rule, the profile closure, the SELF and pair-order requirements, the secret
guard and the two-outcome marker are the stage, and the verdict is what they
produced this time.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from fpbench.core.errors import FpbenchError
from fpbench.core.id3_preflight_errors import (
    Id3AccessQualificationError,
    Id3CandidateIdentityError,
    Id3GateError,
    Id3ObservationError,
    Id3PreflightError,
    SensitiveEvidenceError,
    Stage10BFinalizationError,
)
from fpbench.experiments import stage10b_id3_identity as frozen
from fpbench.experiments import stage10b_id3_observations as observed
from fpbench.experiments import stage10b_preflight as engine
from fpbench.experiments.algorithm_research import REPOSITORY_ROOT
from fpbench.experiments.stage10b_finalization import (
    Stage10BFinalization,
    require_expected_evidence_files,
    stage_10b_finalization_fingerprint,
)

pytestmark = pytest.mark.stage10b_contract


# ------------------------------------------------------------- the vocabulary


def test_every_error_descends_from_the_project_root() -> None:
    for error in (
        Id3PreflightError,
        Id3CandidateIdentityError,
        Id3ObservationError,
        Id3AccessQualificationError,
        Id3GateError,
        SensitiveEvidenceError,
        Stage10BFinalizationError,
    ):
        assert issubclass(error, FpbenchError)


def test_stage_10b_does_not_import_stage_10a_error_types() -> None:
    """Stage 10A's error module is pinned by its published source fingerprint.

    The docstrings say why, so the check is over the imports rather than over
    the text: naming the module in prose is the explanation, importing it is
    the coupling.
    """
    import ast

    import fpbench.core.id3_preflight_errors as module

    tree = ast.parse(inspect.getsource(module))
    imported = [
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    ] + [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    ]
    assert sorted(imported) == ["__future__", "fpbench.core.errors"]


def test_the_frozen_identifiers_are_well_formed() -> None:
    assert frozen.all_frozen_identifiers()
    assert frozen.CANDIDATE_ID == "id3_finger_sdk_1to1"
    assert frozen.IMPLEMENTATION_ORIGIN == "VENDOR_OFFICIAL_SDK"


def test_no_production_algorithm_id_is_frozen_here() -> None:
    assert frozen.PRODUCTION_ALGORITHM_ID_FROZEN is False
    assert len(frozen.FINAL_IDENTITY_COMPONENTS) >= 5


def test_the_gate_order_is_ten_gates_with_acquisition_second() -> None:
    assert len(frozen.GATE_ORDER) == frozen.GATE_COUNT == 10
    assert frozen.GATE_ORDER[0] is frozen.PreflightGate.PRODUCT_IDENTITY
    assert frozen.GATE_ORDER[1] is frozen.PreflightGate.ACQUISITION_ACCESS
    assert len(set(frozen.GATE_ORDER)) == len(frozen.GATE_ORDER)


def test_every_gate_is_covered_by_the_blocker_table() -> None:
    covered = tuple(gate for gate, _ in frozen.GATE_BLOCKERS)
    assert covered == frozen.GATE_ORDER


def test_every_blocker_code_belongs_to_at_least_one_gate() -> None:
    attached = {
        code for _, codes in frozen.GATE_BLOCKERS for code in codes
    }
    assert attached == set(frozen.BlockerCode)


def test_the_blocker_vocabulary_is_the_one_the_specification_fixed() -> None:
    assert {code.value for code in frozen.BlockerCode} == {
        "ID3_PACKAGE_NOT_OBTAINABLE",
        "ID3_LICENSE_NOT_OBTAINABLE",
        "ID3_LICENSE_ACTIVATION_FAILED",
        "ID3_REQUIRED_MODULE_NOT_LICENSED",
        "LICENSE_WORKLOAD_CAPACITY_UNRESOLVED",
        "LICENSE_WORKLOAD_CAPACITY_INSUFFICIENT",
        "SDK_VERSION_IDENTITY_UNRESOLVED",
        "REQUIRED_MODEL_MISSING",
        "MODEL_IDENTITY_UNRESOLVED",
        "CANONICAL500_INPUT_ROUTE_UNRESOLVED",
        "SINGLE_FINGER_INPUT_ROUTE_UNRESOLVED",
        "FPBENCH_PREPROCESSING_CHOICE_REQUIRED",
        "EXTRACTION_PROFILE_UNRESOLVED",
        "MATCHER_PROFILE_UNRESOLVED",
        "HIDDEN_DEFAULT_UNRESOLVED",
        "RAW_SCORE_ROUTE_UNRESOLVED",
        "PAIR_ORDER_SEMANTICS_UNRESOLVED",
        "SCORE_NONDETERMINISM_OBSERVED",
        "RESEARCH_USE_BLOCKED",
        "SD300_TRAINING_OVERLAP_FOUND",
        "LOCAL_SMOKE_FAILED",
    }


def test_a_blocker_cannot_be_raised_at_a_gate_it_does_not_belong_to() -> None:
    with pytest.raises(Id3GateError, match="does not belong to"):
        engine.Blocker(
            gate=frozen.PreflightGate.PRODUCT_IDENTITY,
            blocker_code=frozen.BlockerCode.LOCAL_SMOKE_FAILED,
            affected_component="x",
            evidence="y",
            why_this_blocks_algorithm_4="z",
            how_this_would_be_lifted="w",
        )


def test_a_blocker_must_say_how_it_would_be_lifted() -> None:
    with pytest.raises(Id3GateError, match="how_this_would_be_lifted"):
        engine.Blocker(
            gate=frozen.PreflightGate.ACQUISITION_ACCESS,
            blocker_code=frozen.BlockerCode.ID3_PACKAGE_NOT_OBTAINABLE,
            affected_component="x",
            evidence="y",
            why_this_blocks_algorithm_4="z",
            how_this_would_be_lifted="   ",
        )


# ----------------------------------------------------------------- the gates


def test_a_passing_gate_carries_no_blockers() -> None:
    with pytest.raises(Id3GateError, match="carries no blockers"):
        engine.GateResult(
            gate=frozen.PreflightGate.ACQUISITION_ACCESS,
            status=frozen.GateStatus.PASS,
            summary="s",
            blockers=(_blocker(),),
        )


def test_a_failing_gate_names_why() -> None:
    with pytest.raises(Id3GateError, match="names why"):
        engine.GateResult(
            gate=frozen.PreflightGate.ACQUISITION_ACCESS,
            status=frozen.GateStatus.FAIL,
            summary="s",
        )


def test_a_gate_that_was_never_reached_found_nothing() -> None:
    with pytest.raises(Id3GateError, match="never reached"):
        engine.GateResult(
            gate=frozen.PreflightGate.ACQUISITION_ACCESS,
            status=frozen.GateStatus.NOT_REACHED,
            summary="s",
            blockers=(_blocker(),),
        )


def _blocker() -> engine.Blocker:
    return engine.Blocker(
        gate=frozen.PreflightGate.ACQUISITION_ACCESS,
        blocker_code=frozen.BlockerCode.ID3_PACKAGE_NOT_OBTAINABLE,
        affected_component="the delivered package",
        evidence="nothing was delivered",
        why_this_blocks_algorithm_4="there is nothing to qualify",
        how_this_would_be_lifted="request one from the vendor",
    )


def test_the_preflight_stops_at_the_first_failing_gate() -> None:
    preflight = engine.run_preflight()
    statuses = [result.status for result in preflight.results]
    assert statuses[0] is frozen.GateStatus.PASS
    assert statuses[1] is frozen.GateStatus.FAIL
    assert all(status is frozen.GateStatus.NOT_REACHED for status in statuses[2:])
    assert preflight.stopped_at is frozen.PreflightGate.ACQUISITION_ACCESS
    assert preflight.gates_reached == 2


def test_not_reached_is_not_a_pass() -> None:
    preflight = engine.run_preflight()
    assert preflight.passed is False
    assert preflight.verdict == frozen.CANDIDATE_FAIL_VERDICT
    assert preflight.outcome == frozen.STAGE_10B_BLOCKED_OUTCOME
    assert preflight.selected_candidate is None


def test_two_failing_gates_are_refused() -> None:
    results = []
    for gate in frozen.GATE_ORDER:
        if gate in (
            frozen.PreflightGate.ACQUISITION_ACCESS,
            frozen.PreflightGate.LOCAL_SMOKE,
        ):
            results.append(
                engine.GateResult(
                    gate=gate,
                    status=frozen.GateStatus.FAIL,
                    summary="s",
                    blockers=(
                        engine.Blocker(
                            gate=gate,
                            blocker_code=dict(frozen.GATE_BLOCKERS)[gate][0],
                            affected_component="a",
                            evidence="b",
                            why_this_blocks_algorithm_4="c",
                            how_this_would_be_lifted="d",
                        ),
                    ),
                )
            )
        else:
            results.append(
                engine.GateResult(
                    gate=gate, status=frozen.GateStatus.NOT_REACHED, summary="s"
                )
            )
    with pytest.raises(Id3GateError, match="fail-fast"):
        engine.Id3Preflight(
            results=tuple(results),
            stopped_at=frozen.PreflightGate.ACQUISITION_ACCESS,
            preflight_fingerprint="0" * 64,
        )


def test_a_gate_reported_out_of_order_is_refused() -> None:
    results = tuple(
        engine.GateResult(gate=gate, status=frozen.GateStatus.NOT_REACHED, summary="s")
        for gate in reversed(frozen.GATE_ORDER)
    )
    with pytest.raises(Id3GateError, match="frozen order"):
        engine.Id3Preflight(
            results=results, stopped_at=None, preflight_fingerprint="0" * 64
        )


def test_the_engine_has_no_verdict_parameter() -> None:
    assert list(inspect.signature(engine.run_preflight).parameters) == []


def test_only_the_two_reached_gates_have_runners() -> None:
    """A gate reached with no runner is an unanswered question, not a pass."""
    assert set(engine._GATE_RUNNERS) == {
        frozen.PreflightGate.PRODUCT_IDENTITY,
        frozen.PreflightGate.ACQUISITION_ACCESS,
    }


# ------------------------------------------------------- access and capacity


def test_operational_access_is_not_a_research_use_decision() -> None:
    from fpbench.core.third_party_models import ResearchUseDecision

    access = {item.value for item in frozen.OperationalAccessDecision}
    research = {item.value for item in ResearchUseDecision}
    assert access.isdisjoint(research)
    assert frozen.OperationalAccessDecision.OPERABLE.opens_execution is True
    assert frozen.OperationalAccessDecision.NO_PACKAGE.opens_execution is False


def test_no_package_is_present_and_none_is_claimed() -> None:
    state = engine.package_acquisition_state()
    assert state.obtained is False
    assert state.frozen_identity_available is False
    assert state.findings


def test_a_capacity_cannot_be_called_sufficient_without_an_activation() -> None:
    with pytest.raises(Id3AccessQualificationError, match="activated licence"):
        engine.LicenseCapability(
            license_present=True,
            activation_attempted=True,
            activation_verified=False,
            capacity=frozen.LicenseCapacityStatus.SUFFICIENT,
            license_type="evaluation",
            enabled_module_names=(),
            expiry_category="under_30_days",
            remaining_days_category="under_30_days",
            sufficient_for_declared_workload=None,
            basis="b",
        )


def test_activation_cannot_be_verified_without_a_licence() -> None:
    with pytest.raises(Id3AccessQualificationError, match="without a licence"):
        engine.LicenseCapability(
            license_present=False,
            activation_attempted=True,
            activation_verified=True,
            capacity=frozen.LicenseCapacityStatus.UNRESOLVED,
            license_type=None,
            enabled_module_names=(),
            expiry_category=None,
            remaining_days_category=None,
            sufficient_for_declared_workload=None,
            basis="b",
        )


def test_an_unresolved_capacity_does_not_admit_the_candidate() -> None:
    licence = engine.license_capability_state()
    assert licence.capacity is frozen.LicenseCapacityStatus.UNRESOLVED
    assert licence.capacity.admits_candidate is False
    assert licence.sufficient_for_declared_workload is None
    assert licence.basis


def test_the_workload_is_frozen_before_the_capacity_is_asked_about() -> None:
    load = frozen.FROZEN_WORKLOAD
    assert (load.participating_images, load.extractions, load.comparisons) == (
        3_000,
        3_000,
        6_000,
    )
    assert load.total_metered_operations_upper_bound == 9_200


def test_a_workload_with_mismatched_extractions_is_refused() -> None:
    with pytest.raises(Id3CandidateIdentityError, match="one extraction per"):
        frozen.FrozenWorkload(
            participating_images=3_000,
            extractions=6_000,
            comparisons=6_000,
            qualification_operations_upper_bound=10,
        )


def test_the_budget_publishes_a_cost_under_every_metering_semantics() -> None:
    budget = engine.workload_budget()
    assert budget.resolved is False
    assert budget.costs_by_metering_semantics == {
        "every_api_call_upper_bound": 9_200,
        "extraction_and_matching": 9_000,
        "extraction_only": 3_000,
        "matching_only": 6_000,
    }


# --------------------------------------------------------------- the profiles


def test_every_published_matcher_option_is_score_affecting_and_undocumented() -> None:
    options = observed.PUBLISHED_MATCHER_OPTIONS
    assert {item.name for item in options} == {
        "maximumRotation",
        "minexOnly",
        "minutiaPatchOnly",
        "multiscaleMatch",
        "normalizedScores",
    }
    assert all(item.is_score_affecting for item in options)
    assert all(item.documented_default is None for item in options)


def test_the_count_of_unresolved_score_affecting_defaults_is_published() -> None:
    unresolved = [
        item
        for item in (
            *observed.PUBLISHED_MATCHER_OPTIONS,
            *observed.PUBLISHED_EXTRACTOR_OPTIONS,
        )
        if item.is_score_affecting and item.documented_default is None
    ]
    assert len(unresolved) == 7


def test_the_extraction_profile_refuses_selection_on_reported_accuracy() -> None:
    document = engine.extraction_profile_document(engine.run_preflight())
    assert document["fusion_selection_from_vendor_reported_accuracy"] is False
    assert document["profile_frozen"] is False
    assert len(document["fields_that_must_be_frozen"]) == 7


def test_minex_only_is_not_the_research_default() -> None:
    document = engine.matcher_profile_document(engine.run_preflight())
    assert document["minex_only_is_not_the_research_default"] is True
    assert document["minex_only_would_be_a_separate_algorithm_profile"] is True
    assert document["undocumented_runtime_default_label"] == "DELIVERED_SDK_DEFAULT"


# ------------------------------------------------------------ the score rules


def test_the_score_contract_forbids_a_threshold_in_the_raw_route() -> None:
    document = engine.score_contract_document(engine.run_preflight())
    assert document["threshold_in_raw_route"] is False
    assert document["vendor_threshold_constants_are_not_part_of_the_raw_route"] is True
    assert document["zero_is_a_valid_score_and_never_a_failure_sentinel"] is True
    assert document["extraction_failure_may_become_a_score"] is False


def test_self_requires_two_independent_extractions() -> None:
    document = engine.score_contract_document(engine.run_preflight())
    assert document["self_independent_extraction_required"] is True
    assert len(document["self_semantics_requirements"]) == 4
    joined = " ".join(frozen.SELF_SEMANTICS_REQUIREMENTS).lower()
    assert "two independent extractions" in joined
    assert "shortcut" in joined


def test_pair_order_is_never_symmetrised_by_fpbench() -> None:
    document = engine.score_contract_document(engine.run_preflight())
    assert document["pair_order_symmetry_established"] is False
    assert document["fpbench_may_symmetrise_a_pairwise_score"] is False


def test_the_only_apis_offered_are_the_two_published_ones_and_never_both() -> None:
    admissible = [
        item for item in frozen.RawScoreRouteStatus if item.admits_candidate
    ]
    assert {item.value for item in admissible} == {
        "COMPARE_TEMPLATES",
        "COMPARE_TEMPLATE_RECORDS",
    }
    document = engine.score_contract_document(engine.run_preflight())
    assert document["apis_may_not_be_mixed"] is True
    assert document["chosen_comparison_api"] is None


def test_the_documented_range_is_recorded_as_an_observation_not_a_contract() -> None:
    document = engine.score_contract_document(engine.run_preflight())
    published = document["publicly_documented_score"]
    assert published["range_min"] == 0
    assert published["range_max"] == 65535
    assert published["direction"] == "HIGHER_IS_MORE_SIMILAR"
    assert published["this_is_an_observation_not_a_contract"] is True


# ------------------------------------------------------------- the input rules


def test_the_input_domain_refuses_an_fpbench_transformation() -> None:
    document = engine.input_domain_contract_document(engine.run_preflight())
    assert document["fpbench_crop_resize_or_rotation"] is False
    assert document["benchmark_input"] == {
        "profile": "canonical_500",
        "ppi": 500,
        "pixel_format": "gray8",
    }
    assert document["refused_constructions"]


def test_no_other_sd300_profile_is_offered_to_this_candidate() -> None:
    document = engine.input_domain_contract_document(engine.run_preflight())
    assert document["sd300b_1000_ppi_offered_to_this_candidate"] is False
    assert document["sd300c_2000_ppi_offered_to_this_candidate"] is False
    assert document["sd300_bytes_read"] is False


def test_an_undefined_single_finger_route_is_a_named_failure() -> None:
    document = engine.input_domain_contract_document(engine.run_preflight())
    assert (
        document["if_the_single_finger_route_were_undefined"]
        == "SINGLE_FINGER_INPUT_ROUTE_UNRESOLVED"
    )
    assert frozen.SingleFingerRouteStatus.UNRESOLVED.admits_candidate is False


# --------------------------------------------------------------- the provenance


def test_no_evidence_found_is_never_proven_absent() -> None:
    document = engine.training_provenance_document(engine.run_preflight())
    assert document["no_evidence_found_is_not_proven_absent"] is True
    assert document["expected_sd300_overlap_status"] == "NO_EVIDENCE_FOUND"
    assert document["an_evaluation_dataset_is_not_a_training_dataset"] is True


def test_a_proprietary_product_is_not_required_to_disclose_its_corpus() -> None:
    document = engine.training_provenance_document(engine.run_preflight())
    assert document["full_training_corpus_disclosure_is_not_required"] is True
    assert document["expected_status_for_a_proprietary_product"] == (
        "PROPRIETARY_UNDISCLOSED"
    )


# ------------------------------------------------------------- the secret guard


@pytest.mark.parametrize(
    "payload",
    [
        {"activation_key": "redacted"},
        {"license": {"hardware_code": "x"}},
        {"notes": ["customer_login was here"], "customer_login": "a"},
        {"nested": [{"deep": {"access_token": "t"}}]},
    ],
)
def test_a_credential_key_is_refused_at_any_depth(payload: dict) -> None:
    assert engine.find_sensitive_material(payload)
    with pytest.raises(SensitiveEvidenceError):
        engine.require_no_sensitive_material(payload, where="probe")


@pytest.mark.parametrize(
    "value",
    [
        "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE",
        "Authorization: Bearer abcdefghijklmnopqrstuvwxyz012345",
        "-----BEGIN RSA PRIVATE KEY-----",
        "https://user:hunter2@vendor.example/portal",
    ],
)
def test_a_credential_shaped_value_is_refused_whatever_the_key_is_called(
    value: str,
) -> None:
    assert engine.find_sensitive_material({"harmless_note": value})


def test_an_ordinary_document_passes_the_guard() -> None:
    preflight = engine.run_preflight()
    for name in frozen.REQUIRED_EVIDENCE_FILES:
        if name in (frozen.README_NAME, frozen.STAGE_10B_FINALIZATION_NAME):
            continue
        assert engine.evidence_document(preflight, name)


def test_the_publishable_licence_facts_are_a_closed_list() -> None:
    assert frozen.PUBLISHABLE_LICENSE_FACTS == (
        "license_type",
        "enabled_module_names",
        "expiry_category",
        "remaining_days_category",
        "sufficient_for_declared_workload",
    )
    assert frozen.SENSITIVE_EVIDENCE_KEYS <= frozen.FORBIDDEN_PUBLISHED_KEYS


def test_no_publishable_licence_fact_is_also_a_refused_key() -> None:
    assert set(frozen.PUBLISHABLE_LICENSE_FACTS).isdisjoint(
        frozen.SENSITIVE_EVIDENCE_KEYS
    )


# ---------------------------------------------------------------- observations


def test_every_observation_carries_a_locator_and_a_retrieval_outcome() -> None:
    items = observed.all_observations()
    assert items
    assert len({item.observation_id for item in items}) == len(items)
    for item in items:
        assert item.locator.startswith("https://")
        assert item.observed_utc == observed.OBSERVED_UTC


def test_a_locator_that_did_not_resolve_is_published_as_not_resolving() -> None:
    unresolved = observed.UNRESOLVED_LOCATORS
    assert len(unresolved) >= 5
    assert all(item.http_status == 404 for item in unresolved)
    assert all(
        item.retrieval is observed.RetrievalOutcome.NOT_FOUND for item in unresolved
    )


def test_an_observation_reported_as_read_cannot_carry_a_404() -> None:
    with pytest.raises(Id3ObservationError, match="answered 404"):
        observed.PublicObservation(
            observation_id="probe",
            subject="s",
            statement="t",
            locator="https://example.invalid/",
            retrieval=observed.RetrievalOutcome.READ,
            http_status=404,
        )


def test_the_samples_repository_is_pinned_by_commit_not_by_branch() -> None:
    repository = observed.SAMPLES_REPOSITORY
    assert len(repository.commit) == 40
    with pytest.raises(Id3ObservationError, match="full commit SHA"):
        observed.UpstreamRepository(
            upstream_name="x",
            html_locator="https://example.invalid/x",
            commit="main",
            commit_date_utc="2026-01-01T00:00:00Z",
            release_label="r",
        )


def test_every_cited_file_is_named_by_digest_and_size() -> None:
    for item in observed.SAMPLES_PINNED_FILES:
        assert len(item.sha256) == 64
        assert item.size_bytes > 0


def test_the_observations_fingerprint_moves_with_a_recorded_fact() -> None:
    before = observed.observations_fingerprint()
    original = observed.EVALUATION_TERMS.duration_days
    replacement = observed.EvaluationTerms(
        offered=True,
        duration_days=original + 1,
        api_call_limit_statement=observed.EVALUATION_TERMS.api_call_limit_statement,
        api_call_limit_is_numeric=False,
        platform_limit_statement=observed.EVALUATION_TERMS.platform_limit_statement,
        metering_semantics_published=False,
        locator=observed.EVALUATION_TERMS.locator,
    )
    saved = observed.EVALUATION_TERMS
    observed.EVALUATION_TERMS = replacement  # type: ignore[misc]
    try:
        assert observed.observations_fingerprint() != before
    finally:
        observed.EVALUATION_TERMS = saved  # type: ignore[misc]
    assert observed.observations_fingerprint() == before


# -------------------------------------------------------------- the publication


def test_the_required_files_are_the_fifteen_the_specification_fixed() -> None:
    assert frozen.REQUIRED_EVIDENCE_FILES == (
        "README.md",
        "candidate-identity.json",
        "public-product-observations.json",
        "access-qualification.json",
        "sdk-package-manifest.json",
        "license-capability-report.json",
        "model-artifact-manifest.json",
        "input-domain-contract.json",
        "extraction-profile.json",
        "matcher-profile.json",
        "score-contract.json",
        "training-provenance.json",
        "runtime-smoke.json",
        "preflight-report.json",
        "stage-10b-finalization.json",
    )


def test_an_extra_published_file_is_a_finding() -> None:
    with pytest.raises(Stage10BFinalizationError, match="nothing accounts for"):
        require_expected_evidence_files(
            frozen.REQUIRED_EVIDENCE_FILES + ("notes.json",)
        )


def test_a_missing_published_file_is_a_finding() -> None:
    with pytest.raises(Stage10BFinalizationError, match="missing"):
        require_expected_evidence_files(frozen.REQUIRED_EVIDENCE_FILES[:-2])


# ------------------------------------------------------------------ the marker


def _marker(**overrides: object) -> dict:
    preflight = engine.run_preflight()
    claims: dict = {
        "schema_version": "1",
        "kind": "stage_10b_finalization",
        "outcome": frozen.STAGE_10B_BLOCKED_OUTCOME,
        "algorithm_slot": "algorithm_4",
        "predecessor_stage_10a_fingerprint": (
            frozen.STAGE_10A_FINALIZATION_FINGERPRINT
        ),
        "stage8e_policy_fingerprint": frozen.STAGE8E_FINALIZATION_FINGERPRINT,
        "stage10b_source_fingerprint": "a" * 64,
        "observations_fingerprint": "b" * 64,
        "preflight_fingerprint": "c" * 64,
        "candidate_verdict": frozen.CANDIDATE_FAIL_VERDICT,
        "selected_candidate": None,
        "gate_count_defined": 10,
        "gates_reached": 2,
        "official_sdk_obtained": False,
        "exact_sdk_identity_established": False,
        "research_use_opens_execution": None,
        "research_use_blocked": False,
        "third_party_components_assessed": 0,
        "license_activation_verified": False,
        "license_workload_capacity_sufficient": None,
        "required_models_identity_established": False,
        "canonical500_input_route_resolved": False,
        "single_finger_route_resolved": False,
        "extraction_profile_resolved": False,
        "matcher_profile_resolved": False,
        "hidden_score_affecting_defaults": 7,
        "raw_score_route_resolved": False,
        "score_type": None,
        "score_range_min": None,
        "score_range_max": None,
        "score_direction": None,
        "threshold_in_raw_route": False,
        "self_independent_extraction_required": True,
        "pair_order_semantics_resolved": False,
        "restart_determinism_verified": False,
        "training_provenance_status": "NOT_REACHED",
        "sd300_training_overlap_found": False,
        "sd300_image_bytes_read": False,
        "sd300_scores_read": False,
        "sd300_pair_manifest_read": False,
        "prior_algorithm_scores_read": False,
        "production_adapter_created": False,
        "benchmark_run_performed": False,
        "threshold_produced": False,
        "decision_profile_produced": False,
        "calibration_performed": False,
        "metrics_produced": False,
        "third_party_bytes_added_to_git": False,
        "secrets_added_to_git": False,
        "license_activation_attempted_in_ci": False,
        "credentials_stored_in_ci": False,
        "license_bypass_attempted": False,
        "stage8e_evidence_changed": False,
        "stage9a_evidence_changed": False,
        "stage10a_evidence_changed": False,
        "opens_stage_10c": False,
        "opens_candidate_search": True,
        "blockers": engine.marker_blocker_rows(preflight.blockers),
        "evidence_content_hashes": {"README.md": "d" * 64},
        "source_commit": "e" * 40,
        "source_tree_clean": True,
        "verifier_source_commit": "e" * 40,
        "verifier_source_tree_clean": True,
    }
    claims.update(overrides)
    marker = Stage10BFinalization(
        **claims,
        stage_10b_finalization_fingerprint=stage_10b_finalization_fingerprint(claims),
        created_utc="2026-08-10T00:00:00Z",
    )
    from fpbench.core.serialization import to_plain

    return dict(to_plain(marker))


def test_the_blocked_marker_validates() -> None:
    document = _marker()
    assert document["outcome"] == "ID3_FINGER_SDK_PREFLIGHT_FAIL"
    assert document["selected_candidate"] is None
    assert len(document["blockers"]) == 3


def test_a_third_outcome_cannot_be_expressed() -> None:
    with pytest.raises(ValueError, match="no third state"):
        _marker(outcome="ID3_FINGER_SDK_PREFLIGHT_PASS_WITH_RESERVATIONS")


def test_a_blocked_marker_cannot_name_a_candidate() -> None:
    with pytest.raises(ValueError, match="selects nothing"):
        _marker(selected_candidate=frozen.CANDIDATE_ID)


def test_a_blocked_marker_cannot_claim_an_unestablished_fact() -> None:
    with pytest.raises(ValueError, match="not established"):
        _marker(raw_score_route_resolved=True)


def test_a_blocked_marker_publishes_no_research_use_refusal_nobody_made() -> None:
    with pytest.raises(ValueError, match="research-use refusal"):
        _marker(research_use_opens_execution=False)


def test_a_blocked_marker_does_not_claim_the_quota_was_measured() -> None:
    with pytest.raises(ValueError, match="published as unresolved"):
        _marker(license_workload_capacity_sufficient=False)


def test_a_blocked_marker_publishes_no_score_facts() -> None:
    with pytest.raises(ValueError, match="raw-score gate settled it"):
        _marker(score_range_max=65535)


def test_the_self_rule_holds_under_either_outcome() -> None:
    with pytest.raises(ValueError, match="frozen requirement"):
        _marker(self_independent_extraction_required=False)


def test_a_blocked_marker_opens_a_candidate_search_and_not_stage_10c() -> None:
    with pytest.raises(ValueError, match="opens no artifact integration"):
        _marker(opens_stage_10c=True)
    with pytest.raises(ValueError, match="search for another candidate"):
        _marker(opens_candidate_search=False)


def test_a_marker_without_blockers_cannot_be_blocked() -> None:
    with pytest.raises(ValueError, match="names which blockers apply"):
        _marker(blockers=())


def test_a_blocker_missing_its_lift_is_refused_by_the_marker() -> None:
    rows = [
        {
            key: value
            for key, value in dict(row).items()
            if key != "how_this_would_be_lifted"
        }
        for row in engine.marker_blocker_rows(engine.run_preflight().blockers)
    ]
    with pytest.raises(ValueError, match="how_this_would_be_lifted"):
        _marker(blockers=tuple(rows))


def test_the_marker_must_bind_the_stage_10a_predecessor() -> None:
    with pytest.raises(ValueError, match="Stage 10A"):
        _marker(predecessor_stage_10a_fingerprint="f" * 64)


def test_the_marker_must_bind_the_stage_8e_policy() -> None:
    with pytest.raises(ValueError, match="Stage 8E"):
        _marker(stage8e_policy_fingerprint="f" * 64)


def test_a_preflight_over_fewer_gates_is_a_different_preflight() -> None:
    with pytest.raises(ValueError, match="hard gates are defined"):
        _marker(gate_count_defined=9)


def test_the_marker_denies_everything_this_stage_did_not_do() -> None:
    document = _marker()
    for name in Stage10BFinalization.DENIED_FLAGS:
        assert document[name] is False, name


@pytest.mark.parametrize("name", list(Stage10BFinalization.DENIED_FLAGS))
def test_each_denial_is_enforced_rather_than_written(name: str) -> None:
    with pytest.raises(ValueError, match=name):
        _marker(**{name: True})


def test_a_tampered_fingerprint_is_refused() -> None:
    preflight = engine.run_preflight()
    claims = {"outcome": frozen.STAGE_10B_BLOCKED_OUTCOME}
    document = _marker()
    document["gates_reached"] = 3
    with pytest.raises(ValueError, match="does not cover"):
        Stage10BFinalization(
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
    assert claims and preflight


def test_a_selected_marker_requires_every_score_fact() -> None:
    selected = {
        "outcome": frozen.STAGE_10B_SELECTED_OUTCOME,
        "candidate_verdict": frozen.CANDIDATE_PASS_VERDICT,
        "selected_candidate": frozen.CANDIDATE_ID,
        "gates_reached": 10,
        "official_sdk_obtained": True,
        "exact_sdk_identity_established": True,
        "research_use_opens_execution": True,
        "third_party_components_assessed": 3,
        "license_activation_verified": True,
        "license_workload_capacity_sufficient": True,
        "required_models_identity_established": True,
        "canonical500_input_route_resolved": True,
        "single_finger_route_resolved": True,
        "extraction_profile_resolved": True,
        "matcher_profile_resolved": True,
        "hidden_score_affecting_defaults": 0,
        "raw_score_route_resolved": True,
        "score_type": "integer",
        "score_range_min": 0,
        "score_range_max": 65535,
        "score_direction": "HIGHER_IS_MORE_SIMILAR",
        "pair_order_semantics_resolved": True,
        "restart_determinism_verified": True,
        "training_provenance_status": "PROPRIETARY_UNDISCLOSED",
        "blockers": (),
        "opens_stage_10c": True,
        "opens_candidate_search": False,
    }
    assert _marker(**selected)["outcome"] == "ALGORITHM4_CANDIDATE_SELECTED"

    with pytest.raises(ValueError, match="score-affecting default"):
        _marker(**{**selected, "hidden_score_affecting_defaults": 1})
    with pytest.raises(ValueError, match="licence capacity"):
        _marker(**{**selected, "license_workload_capacity_sufficient": None})
    with pytest.raises(ValueError, match="establishes"):
        _marker(**{**selected, "single_finger_route_resolved": False})
    with pytest.raises(ValueError, match="every gate"):
        _marker(**{**selected, "gates_reached": 9})


# ------------------------------------------------------------ the byte guard


def test_no_id3_material_is_tracked_in_this_repository() -> None:
    audit = engine.require_no_id3_bytes_in_git(REPOSITORY_ROOT)
    assert audit.clean
    assert audit.tracked_file_count > 0
    assert audit.known_digest_count == len(observed.SAMPLES_PINNED_FILES)


def test_the_byte_guard_knows_the_vendor_artifact_shapes() -> None:
    source = inspect.getsource(engine)
    assert ".id3nn" in source
    assert ".lic" in source


# ------------------------------------------------------------- the closed stages


def test_stage_10a_is_the_bound_predecessor_and_still_opens_a_search() -> None:
    fingerprint = engine.require_stage10a_is_the_closed_predecessor(REPOSITORY_ROOT)
    assert fingerprint == frozen.STAGE_10A_FINALIZATION_FINGERPRINT


def test_stage_8e_is_the_policy_this_stage_reuses() -> None:
    engine.require_stage8e_is_the_policy_this_reuses(REPOSITORY_ROOT)


def test_stage_10b_adds_no_licensing_subsystem() -> None:
    """Stage 8E's package and models are read, never extended."""
    for module in (frozen, observed, engine):
        source = inspect.getsource(module)
        assert "build_usage_manifest" not in source
        assert "assess_research_use" not in source


def test_the_stage_declares_its_own_source_set() -> None:
    for relative in frozen.STAGE_10B_SOURCE_FILES:
        assert (Path(REPOSITORY_ROOT) / relative).is_file(), relative
    for relative in frozen.STAGE_10B_ADRS + frozen.STAGE_10B_DOCUMENTS:
        assert (Path(REPOSITORY_ROOT) / relative).is_file(), relative
