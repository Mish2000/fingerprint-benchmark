"""The frozen Stage 10A contract: gates, order, fail-fast, refusals, selection.

No torch, no checkpoint, no network, no dataset and no workspace. This suite
runs anywhere, which is the same claim the stage makes about itself: the whole
preflight is a reading exercise over descriptions of upstream.

What is under test is the shape of the decision rather than the decision. A
future upstream release could turn either candidate's verdict around, and almost
nothing here would change — the gate order, the origin vocabulary, the
NOT_REACHED semantics, the refusal to invent preprocessing and the refusal to
rank failures are the stage, and the verdicts are what they produced this time.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from fpbench.core.algorithm4_errors import (
    Algorithm4PreflightError,
    CandidateAuthenticityError,
    CandidateIdentityError,
    InputDomainError,
    PreflightGateError,
    Stage10AFinalizationError,
)
from fpbench.core.errors import FpbenchError
from fpbench.core.third_party_models import ResearchUseDecision
from fpbench.experiments import stage10a_candidate_evidence as observed
from fpbench.experiments import stage10a_candidate_identity as frozen
from fpbench.experiments import stage10a_preflight as engine
from fpbench.experiments.algorithm_research import REPOSITORY_ROOT
from fpbench.experiments.stage10a_finalization import (
    Stage10AFinalization,
    require_expected_evidence_files,
    stage_10a_finalization_fingerprint,
)

pytestmark = pytest.mark.stage10a_contract


# ------------------------------------------------------------- the vocabulary


def test_every_error_descends_from_the_project_root() -> None:
    for error in (
        Algorithm4PreflightError,
        CandidateIdentityError,
        CandidateAuthenticityError,
        InputDomainError,
        PreflightGateError,
        Stage10AFinalizationError,
    ):
        assert issubclass(error, FpbenchError)


def test_the_frozen_identifiers_are_well_formed() -> None:
    assert frozen.all_frozen_identifiers()


def test_there_are_exactly_two_candidates_and_two_spellings_of_each() -> None:
    assert len(frozen.CANDIDATES) == 2
    assert {item.candidate_id for item in frozen.CANDIDATES} == {"afrnet", "jipnet"}
    for item in frozen.CANDIDATES:
        assert item.marker_token == item.candidate_id.upper()
        assert item.pass_outcome == f"{item.marker_token}_PREFLIGHT_PASS"
        assert item.fail_outcome == f"{item.marker_token}_PREFLIGHT_FAIL"


def test_only_author_official_origins_are_admissible() -> None:
    admissible = {
        origin
        for origin in frozen.ImplementationOrigin
        if origin.is_admissible_for_algorithm_4
    }
    assert admissible == set(frozen.ACCEPTED_ORIGINS)
    assert frozen.ImplementationOrigin.THIRD_PARTY_REIMPLEMENTATION not in admissible
    assert (
        frozen.ImplementationOrigin.ADJUSTED_THIRD_PARTY_REIMPLEMENTATION
        not in admissible
    )
    assert frozen.ImplementationOrigin.PAPER_RECONSTRUCTION not in admissible


def test_the_gate_order_is_seven_gates_with_identity_and_input_domain_first() -> None:
    assert len(frozen.GATE_ORDER) == 7
    assert len(set(frozen.GATE_ORDER)) == 7
    assert set(frozen.GATE_ORDER) == set(frozen.PreflightGate)
    assert frozen.GATE_ORDER[0] is frozen.PreflightGate.IDENTITY
    assert frozen.GATE_ORDER[1] is frozen.PreflightGate.INPUT_DOMAIN


def test_every_blocker_code_belongs_to_exactly_one_gate() -> None:
    seen: dict[frozen.BlockerCode, frozen.PreflightGate] = {}
    for gate, codes in frozen.GATE_BLOCKERS:
        for code in codes:
            assert code not in seen, f"{code} is claimed by two gates"
            seen[code] = gate
    assert set(seen) == set(frozen.BlockerCode)


def test_the_blocker_vocabulary_has_no_vague_members() -> None:
    for code in frozen.BlockerCode:
        text = code.value.lower()
        for vague in ("probably", "some_issues", "not_ideal", "maybe", "unclear"):
            assert vague not in text


def test_no_evidence_found_is_not_an_automatic_rejection_and_proven_absent_exists() -> None:
    assert frozen.SD300OverlapStatus.POSITIVE_OVERLAP_FOUND.is_automatic_rejection
    for status in frozen.SD300OverlapStatus:
        if status is not frozen.SD300OverlapStatus.POSITIVE_OVERLAP_FOUND:
            assert not status.is_automatic_rejection


def test_only_two_input_domain_resolutions_admit_a_candidate() -> None:
    admitting = {
        resolution
        for resolution in frozen.InputDomainResolution
        if resolution.admits_candidate
    }
    assert admitting == {
        frozen.InputDomainResolution.NATIVE_INPUT_ACCEPTED,
        frozen.InputDomainResolution.UPSTREAM_AUTHORITATIVE_TRANSFORMATION,
    }
    assert not frozen.InputDomainResolution.FPBENCH_CONSTRUCTION_REQUIRED.admits_candidate


def test_the_score_requirements_state_the_self_and_pair_order_rules() -> None:
    """Requirements, not findings: neither candidate reached the score gate."""
    joined = " ".join(frozen.SCORE_CONTRACT_REQUIREMENTS).lower()
    assert "self(a, a)" in joined
    assert "shortcut" in joined
    assert "score(a, b) equals score(b, a)" in joined
    assert "never averages or maximises" in joined
    assert "no threshold" in joined
    assert "nan" in joined
    document = engine.candidate_document(
        engine.run_candidate_preflight("jipnet"),
        frozen.SCORE_CONTRACT_NAME,
        repository_root=REPOSITORY_ROOT,
    )
    assert document["gate_status"] == frozen.GateStatus.NOT_REACHED.value
    assert document["self_comparison_shortcut_permitted"] is False
    assert document["requirements_this_gate_would_have_applied"] == list(
        frozen.SCORE_CONTRACT_REQUIREMENTS
    )


def test_the_tie_break_is_ordered_and_excludes_reported_performance() -> None:
    orders = [item.order for item in frozen.TIE_BREAK_CRITERIA]
    assert orders == sorted(orders) == list(range(1, len(orders) + 1))
    assert frozen.TIE_BREAK_CRITERIA[0].criterion_id == "canonical500_fit"
    text = " ".join(item.description.lower() for item in frozen.TIE_BREAK_CRITERIA)
    for banned in ("eer", "accuracy", "reported", "tar @", "benchmark result"):
        assert banned not in text


# ------------------------------------------------------- the recorded evidence


def test_the_afrnet_search_covers_the_locations_the_stage_promised() -> None:
    required = {
        "arxiv_abstract_page",
        "paper_body_and_references",
        "msu_biometrics_publications",
        "first_author_github_account",
        "github_repository_search",
        "ieee_supplementary_material",
        "model_and_code_indexes",
    }
    found = {item.location_id for item in observed.AFRNET_SEARCH_LOCATIONS}
    assert required <= found
    for location in observed.AFRNET_SEARCH_LOCATIONS:
        assert location.locator.startswith("http")
        assert location.finding.strip()


def test_an_unreadable_location_is_not_recorded_as_an_empty_one() -> None:
    unread = [
        item
        for item in observed.AFRNET_SEARCH_LOCATIONS
        if item.outcome is observed.SearchOutcome.NOT_READABLE
    ]
    assert unread, "the IEEE page could not be read and the record must say so"
    for item in unread:
        assert "not established" in item.finding or "unread" in item.finding


def test_the_search_does_not_claim_proof_of_absence() -> None:
    document = observed.afrnet_source_discovery()
    assert document["official_source_found"] is False
    assert document["official_checkpoint_found"] is False
    assert document["official_inference_route_found"] is False
    assert document["not_found_is_not_proof_of_absence"] is True


def test_the_jipnet_reproduction_is_excluded_evidence_and_a_named_non_candidate() -> None:
    excluded = {name for name, _, _ in observed.AFRNET_EXCLUDED_EVIDENCE}
    assert "jipnet_afrnet_reproduction" in excluded
    names = {name for name, _ in frozen.DECLARED_NON_CANDIDATES}
    assert "jipnet_authors_adjusted_afrnet_reimplementation" in names
    assert "afr_net" not in names


def test_the_jipnet_repository_is_pinned_by_a_commit_and_by_bytes() -> None:
    repository = observed.JIPNET_REPOSITORY
    assert len(repository.commit) == 40
    assert repository.commit in repository.archive_locator
    assert repository.archive_size_bytes > 0
    assert len(repository.archive_sha256) == 64
    assert repository.acquired_twice_byte_identical is True
    for name in ("main", "master", "HEAD", "latest"):
        assert repository.commit != name


def test_every_cited_upstream_file_carries_a_digest_and_a_size() -> None:
    assert observed.JIPNET_PINNED_FILES
    for item in observed.JIPNET_PINNED_FILES:
        assert len(item.sha256) == 64
        assert item.size_bytes > 0
        assert not item.relative_path.startswith("/")


def test_an_official_origin_claim_without_a_locator_is_refused() -> None:
    with pytest.raises(CandidateAuthenticityError, match="no locator behind it"):
        observed.OriginClaim(
            candidate_id="jipnet",
            origin=frozen.ImplementationOrigin.AUTHOR_OFFICIAL_IMPLEMENTATION,
            subject="something",
            supporting_locators=(),
            upstream_self_description="",
            basis="",
        )


def test_a_non_official_origin_may_not_carry_partial_credit() -> None:
    with pytest.raises(CandidateAuthenticityError, match="partial credit"):
        observed.OriginClaim(
            candidate_id="afrnet",
            origin=frozen.ImplementationOrigin.THIRD_PARTY_REIMPLEMENTATION,
            subject="something",
            supporting_locators=("https://example.invalid",),
            upstream_self_description="",
            basis="",
        )


def test_an_admitting_input_domain_without_an_authority_is_refused() -> None:
    with pytest.raises(InputDomainError, match="without a named authority"):
        observed.InputDomainContract(
            candidate_id="jipnet",
            declared_input=observed.DeclaredModelInput(
                geometry_pixels=(160, 160),
                channels=1,
                dtype="float32",
                value_range="[0, 1]",
                normalization="none",
                normalization_locator="https://example.invalid",
                declared_ppi=None,
                ppi_statement="none",
                geometry_locators=(),
            ),
            resolution=(
                frozen.InputDomainResolution.UPSTREAM_AUTHORITATIVE_TRANSFORMATION
            ),
            transformation_authority=None,
            observations=(),
        )


def test_the_refused_constructions_name_what_somebody_might_propose() -> None:
    contract = observed.input_domain_contract("jipnet")
    refused = " ".join(contract.refused_constructions).lower()
    for shape in ("centre-crop", "resiz", "core", "highest-quality", "maximum", "sd300"):
        assert shape in refused


def test_the_jipnet_input_route_is_not_admitted_by_a_training_construction() -> None:
    contract = observed.input_domain_contract("jipnet")
    assert not contract.resolution.admits_candidate
    training_side = [
        item for item in contract.observations if not item.is_inference_time
    ]
    assert training_side, "the training-side construction has to be recorded"
    inference_side = [
        item for item in contract.observations if item.is_inference_time
    ]
    assert inference_side, "what the inference script actually does has to be recorded"


def test_neither_candidate_records_a_declared_ppi_as_an_assumption() -> None:
    for item in frozen.CANDIDATES:
        contract = observed.input_domain_contract(item.candidate_id)
        assert contract.declared_input.declared_ppi is None
        assert contract.declared_input.ppi_statement.strip()


def test_sd300_overlap_is_no_evidence_found_for_both_and_never_proven_absent() -> None:
    for item in frozen.CANDIDATES:
        provenance = observed.training_provenance(item.candidate_id)
        assert provenance.sd300_overlap_status is (
            frozen.SD300OverlapStatus.NO_EVIDENCE_FOUND
        )
        assert not provenance.sd300_overlap_status.is_automatic_rejection
        assert provenance.sd300_basis.strip()


def test_the_jipnet_future_exclusions_name_its_training_corpora() -> None:
    provenance = observed.training_provenance("jipnet")
    assert set(provenance.future_development_dataset_exclusions) == {
        "NIST SD14",
        "FVC2004 DB1_A",
        "FVC2004 DB2_A",
        "FVC2006 DB2_A",
    }
    training = {
        item.name
        for item in provenance.datasets
        if item.role is observed.DatasetRole.TRAINING
    }
    assert set(provenance.future_development_dataset_exclusions) == training


# ---------------------------------------------------------------- the engine


def test_a_blocker_raised_against_the_wrong_gate_is_refused() -> None:
    with pytest.raises(PreflightGateError, match="does not belong to"):
        engine.Blocker(
            candidate_id="jipnet",
            gate=frozen.PreflightGate.IDENTITY,
            blocker_code=frozen.BlockerCode.BENCHMARK_INPUT_ROUTE_UNRESOLVED,
            affected_component="x",
            evidence="y",
            why_this_blocks_algorithm_4="z",
        )


def test_a_blocker_with_an_empty_field_is_refused() -> None:
    with pytest.raises(PreflightGateError, match="empty"):
        engine.Blocker(
            candidate_id="jipnet",
            gate=frozen.PreflightGate.INPUT_DOMAIN,
            blocker_code=frozen.BlockerCode.BENCHMARK_INPUT_ROUTE_UNRESOLVED,
            affected_component="x",
            evidence="y",
            why_this_blocks_algorithm_4="   ",
        )


def test_a_passing_gate_carries_no_blockers_and_a_failing_one_names_why() -> None:
    blocker = engine.Blocker(
        candidate_id="jipnet",
        gate=frozen.PreflightGate.INPUT_DOMAIN,
        blocker_code=frozen.BlockerCode.BENCHMARK_INPUT_ROUTE_UNRESOLVED,
        affected_component="x",
        evidence="y",
        why_this_blocks_algorithm_4="z",
    )
    with pytest.raises(PreflightGateError, match="carries no blockers"):
        engine.GateResult(
            candidate_id="jipnet",
            gate=frozen.PreflightGate.INPUT_DOMAIN,
            status=frozen.GateStatus.PASS,
            summary="s",
            blockers=(blocker,),
        )
    with pytest.raises(PreflightGateError, match="names why"):
        engine.GateResult(
            candidate_id="jipnet",
            gate=frozen.PreflightGate.INPUT_DOMAIN,
            status=frozen.GateStatus.FAIL,
            summary="s",
        )


def test_a_gate_that_was_never_reached_cannot_have_found_anything() -> None:
    blocker = engine.Blocker(
        candidate_id="jipnet",
        gate=frozen.PreflightGate.ARTIFACTS,
        blocker_code=frozen.BlockerCode.REQUIRED_ARTIFACT_MISSING,
        affected_component="x",
        evidence="y",
        why_this_blocks_algorithm_4="z",
    )
    with pytest.raises(PreflightGateError, match="never reached"):
        engine.GateResult(
            candidate_id="jipnet",
            gate=frozen.PreflightGate.ARTIFACTS,
            status=frozen.GateStatus.NOT_REACHED,
            summary="s",
            blockers=(blocker,),
        )


def test_every_candidate_reports_all_seven_gates_in_the_frozen_order() -> None:
    for item in frozen.CANDIDATES:
        preflight = engine.run_candidate_preflight(item.candidate_id)
        assert tuple(r.gate for r in preflight.results) == frozen.GATE_ORDER


def test_fail_fast_stops_at_the_first_failure_and_marks_the_rest_not_reached() -> None:
    for item in frozen.CANDIDATES:
        preflight = engine.run_candidate_preflight(item.candidate_id)
        statuses = [result.status for result in preflight.results]
        assert statuses.count(frozen.GateStatus.FAIL) == 1
        index = statuses.index(frozen.GateStatus.FAIL)
        assert all(
            status is frozen.GateStatus.NOT_REACHED
            for status in statuses[index + 1 :]
        )
        assert preflight.stopped_at is preflight.results[index].gate


def test_a_not_reached_gate_is_never_a_pass() -> None:
    for item in frozen.CANDIDATES:
        preflight = engine.run_candidate_preflight(item.candidate_id)
        assert preflight.passed is all(
            result.status is frozen.GateStatus.PASS for result in preflight.results
        )
        assert preflight.passed is False


def test_afrnet_stops_at_identity_and_jipnet_at_input_domain() -> None:
    afrnet = engine.run_candidate_preflight("afrnet")
    jipnet = engine.run_candidate_preflight("jipnet")
    assert afrnet.stopped_at is frozen.PreflightGate.IDENTITY
    assert afrnet.verdict == "AFRNET_PREFLIGHT_FAIL"
    assert jipnet.status(frozen.PreflightGate.IDENTITY) is frozen.GateStatus.PASS
    assert jipnet.stopped_at is frozen.PreflightGate.INPUT_DOMAIN
    assert jipnet.verdict == "JIPNET_PREFLIGHT_FAIL"


def test_the_afrnet_blockers_are_the_three_identity_ones() -> None:
    preflight = engine.run_candidate_preflight("afrnet")
    assert {blocker.blocker_code for blocker in preflight.blockers} == {
        frozen.BlockerCode.OFFICIAL_IMPLEMENTATION_NOT_FOUND,
        frozen.BlockerCode.OFFICIAL_CHECKPOINT_NOT_FOUND,
        frozen.BlockerCode.THIRD_PARTY_REIMPLEMENTATION_ONLY,
    }


def test_the_jipnet_reproduction_never_closes_the_afrnet_identity_gate() -> None:
    """The contract test the stage was specified to carry (spec section 6)."""
    result = engine.run_gate_identity("afrnet")
    assert result.status is frozen.GateStatus.FAIL
    claim = observed.origin_claim("afrnet")
    assert claim.origin is frozen.ImplementationOrigin.UNKNOWN
    assert claim.supporting_locators == ()
    # The reproduction is recorded, and recording it is what produces a blocker
    # rather than what removes one.
    codes = {blocker.blocker_code for blocker in result.blockers}
    assert frozen.BlockerCode.THIRD_PARTY_REIMPLEMENTATION_ONLY in codes


def test_the_outcome_is_derived_and_takes_no_verdict_parameter() -> None:
    signature = inspect.signature(engine.run_preflight)
    assert not signature.parameters
    for name in ("run_gate_identity", "run_gate_input_domain"):
        parameters = inspect.signature(getattr(engine, name)).parameters
        assert list(parameters) == ["candidate_id"]


def test_no_survivor_selects_nothing_and_opens_a_candidate_search() -> None:
    outcome = engine.run_preflight()
    assert outcome.outcome == frozen.STAGE_10A_NO_SURVIVOR_OUTCOME
    assert outcome.selected_candidate is None
    assert outcome.survivors == ()
    assert outcome.tie_break_applied is False
    assert outcome.blockers


def test_the_comparison_refuses_to_rank_candidates_that_failed() -> None:
    document = engine.candidate_comparison_document(engine.run_preflight())
    assert document["ranking_performed"] is False
    assert document["selection_based_on_reported_performance"] is False
    assert document["reported_performance_read"] is False
    assert document["selected_candidate"] is None


def test_no_published_document_carries_a_reported_accuracy() -> None:
    """Reported performance is background, and background is not published here."""
    import json

    outcome = engine.run_preflight()
    payload = json.dumps(
        {
            "set": engine.candidate_set_document(),
            "comparison": engine.candidate_comparison_document(outcome),
            "candidates": [
                {
                    name: engine.candidate_document(
                        item, name, repository_root=REPOSITORY_ROOT
                    )
                    for name in frozen.candidate_document_names(item.identity)
                }
                for item in outcome.candidates
            ],
        },
        default=str,
    ).lower()
    for token in ("eer", "tar @", "@ far", "auc", "accuracy of", "outperform"):
        assert token not in payload, token


def test_the_preflight_fingerprint_covers_the_reconnaissance() -> None:
    outcome = engine.run_preflight()
    assert len(outcome.preflight_fingerprint) == 64
    assert len(observed.reconnaissance_fingerprint()) == 64


# ----------------------------------------------------------- Stage 8E reuse


def test_exactly_one_component_was_obtained_and_no_checkpoint() -> None:
    assert engine.acquired_components() == ("jipnet_source_archive",)
    audit = engine.build_usage_audit()
    assert audit.record.component_kind.value == "SOURCE_CODE"
    assert audit.assessment.decision is ResearchUseDecision.ALLOWED
    assert audit.opens_execution is True


def test_stage10a_adds_no_licence_vocabulary_of_its_own() -> None:
    audit = engine.build_usage_audit()
    assert audit.record.stored_in_git is False
    assert audit.record.stored_in_ci_artifacts is False
    assert audit.record.redistribution.redistributed_by_fpbench is False
    assert audit.manifest.purpose_fingerprint == frozen.STAGE8E_PURPOSE_FINGERPRINT
    assert audit.manifest.policy_fingerprint == frozen.STAGE8E_POLICY_FINGERPRINT


def test_the_stage8e_policy_is_the_one_this_stage_was_written_against() -> None:
    engine.require_stage8e_is_the_policy_this_reuses(REPOSITORY_ROOT)


def test_the_placement_names_no_machine() -> None:
    placement = engine.placement_for_source_archive()
    assert not placement.relative_location.startswith("/")
    assert ":" not in placement.relative_location
    assert ".." not in placement.relative_location.split("/")


def test_no_candidate_byte_is_tracked_in_this_repository() -> None:
    audit = engine.require_no_candidate_bytes_in_git(REPOSITORY_ROOT)
    assert audit.clean
    assert audit.known_digest_count >= 1 + len(observed.JIPNET_PINNED_FILES)


# ------------------------------------------------------------- the marker shape


def _claims(**overrides: object) -> dict:
    outcome = engine.run_preflight()
    base: dict = {
        "schema_version": frozen.STAGE_10A_SCHEMA_VERSION,
        "kind": frozen.STAGE_FINALIZATION_KIND,
        "outcome": frozen.STAGE_10A_NO_SURVIVOR_OUTCOME,
        "algorithm_slot": frozen.ALGORITHM_SLOT,
        "stage8e_policy_fingerprint": frozen.STAGE8E_FINALIZATION_FINGERPRINT,
        "stage10a_source_fingerprint": "a" * 64,
        "reconnaissance_fingerprint": "b" * 64,
        "preflight_fingerprint": "c" * 64,
        "third_party_usage_manifest_fingerprint": "d" * 64,
        "selected_candidate": None,
        "afrnet_preflight": "AFRNET_PREFLIGHT_FAIL",
        "jipnet_preflight": "JIPNET_PREFLIGHT_FAIL",
        "candidate_count": 2,
        "survivor_count": 0,
        "gates_evaluated_per_candidate": 7,
        "selection_based_on_reported_performance": False,
        "reported_performance_read": False,
        "sd300_image_bytes_read": False,
        "sd300_scores_read": False,
        "prior_algorithm_scores_read": False,
        "fpbench_score_affecting_preprocessing_invented": False,
        "candidate_checkpoint_bytes_downloaded": 0,
        "production_adapter_created": False,
        "calibration_performed": False,
        "threshold_produced": False,
        "decision_profile_produced": False,
        "benchmark_run_performed": False,
        "third_party_bytes_added_to_git": False,
        "stage8e_evidence_changed": False,
        "stage9a_evidence_changed": False,
        "upstream_behaviour_modified": False,
        "opens_algorithm4_artifact_qualification": False,
        "opens_candidate_search": True,
        "blockers": engine.marker_blocker_rows(outcome.blockers),
        "evidence_content_hashes": {},
        "source_commit": "0" * 40,
        "source_tree_clean": True,
        "verifier_source_commit": "0" * 40,
        "verifier_source_tree_clean": True,
    }
    base.update(overrides)
    return base


def _marker(**overrides: object) -> Stage10AFinalization:
    claims = _claims(**overrides)
    return Stage10AFinalization(
        **claims,
        stage_10a_finalization_fingerprint=stage_10a_finalization_fingerprint(claims),
        created_utc="2026-08-09T00:00:00Z",
    )


def test_the_marker_reconstructs_from_its_own_claims() -> None:
    marker = _marker()
    assert marker.outcome == frozen.STAGE_10A_NO_SURVIVOR_OUTCOME
    assert marker.selected_candidate is None


def test_a_no_survivor_marker_may_not_select_a_candidate() -> None:
    with pytest.raises(ValueError, match="selects nothing"):
        _marker(selected_candidate="JIPNET")


def test_a_no_survivor_marker_must_open_a_candidate_search() -> None:
    with pytest.raises(ValueError, match="opens a search"):
        _marker(opens_candidate_search=False)


def test_a_no_survivor_marker_may_not_open_the_artifact_qualification() -> None:
    with pytest.raises(ValueError, match="opens no artifact qualification"):
        _marker(opens_algorithm4_artifact_qualification=True)


def test_a_no_survivor_marker_names_its_blockers() -> None:
    with pytest.raises(ValueError, match="names which blockers"):
        _marker(blockers=())


def test_a_selected_marker_requires_the_candidate_to_have_passed() -> None:
    with pytest.raises(ValueError, match="its verdict is"):
        _marker(
            outcome=frozen.STAGE_10A_SELECTED_OUTCOME,
            selected_candidate="JIPNET",
            survivor_count=0,
            blockers=(),
            opens_algorithm4_artifact_qualification=True,
            opens_candidate_search=False,
        )


def test_a_selected_marker_is_reachable_when_a_candidate_passes() -> None:
    """The READY path is exercised even though no candidate took it."""
    marker = _marker(
        outcome=frozen.STAGE_10A_SELECTED_OUTCOME,
        selected_candidate="JIPNET",
        jipnet_preflight="JIPNET_PREFLIGHT_PASS",
        survivor_count=1,
        blockers=(),
        opens_algorithm4_artifact_qualification=True,
        opens_candidate_search=False,
    )
    assert marker.selected_candidate == "JIPNET"


def test_the_marker_denies_everything_this_stage_did_not_do() -> None:
    marker = _marker()
    for name in Stage10AFinalization.DENIED_FLAGS:
        assert getattr(marker, name) is False
        with pytest.raises(ValueError, match=name):
            _marker(**{name: True})


def test_a_downloaded_checkpoint_byte_contradicts_the_stage() -> None:
    with pytest.raises(ValueError, match="no checkpoint byte"):
        _marker(candidate_checkpoint_bytes_downloaded=1)


def test_a_preflight_over_fewer_gates_is_a_different_preflight() -> None:
    with pytest.raises(ValueError, match="seven hard gates"):
        _marker(gates_evaluated_per_candidate=6)


def test_the_survivor_count_must_agree_with_the_verdicts() -> None:
    with pytest.raises(ValueError, match="survivor_count"):
        _marker(survivor_count=1)


def test_a_third_outcome_cannot_be_expressed() -> None:
    with pytest.raises(ValueError, match="no third state"):
        _marker(outcome="ALGORITHM4_SELECTED_WITH_RESERVATIONS")


def test_the_marker_binds_the_exact_stage8e_policy() -> None:
    with pytest.raises(ValueError, match="closed stage"):
        _marker(stage8e_policy_fingerprint="e" * 64)


def test_the_evidence_file_list_is_a_contract() -> None:
    assert frozen.REQUIRED_EVIDENCE_FILES[0] == "README.md"
    assert frozen.REQUIRED_EVIDENCE_FILES[-1] == frozen.STAGE_10A_FINALIZATION_NAME
    assert "afrnet/source-discovery.json" in frozen.REQUIRED_EVIDENCE_FILES
    assert "jipnet/source-manifest.json" in frozen.REQUIRED_EVIDENCE_FILES
    assert "afrnet/source-manifest.json" not in frozen.REQUIRED_EVIDENCE_FILES
    with pytest.raises(Stage10AFinalizationError, match="nothing accounts for"):
        require_expected_evidence_files(
            frozen.REQUIRED_EVIDENCE_FILES + ("notes.json",)
        )
    with pytest.raises(Stage10AFinalizationError, match="missing"):
        require_expected_evidence_files(("README.md",))


def test_no_forbidden_key_is_also_a_published_vocabulary_value() -> None:
    values = {
        member.value.lower()
        for enum in (
            frozen.ImplementationOrigin,
            frozen.PreflightGate,
            frozen.GateStatus,
            frozen.InputDomainResolution,
            frozen.SD300OverlapStatus,
            frozen.BlockerCode,
        )
        for member in enum
    }
    assert not (values & frozen.FORBIDDEN_PUBLISHED_KEYS)


def test_stage10a_source_files_exist_and_are_the_ones_the_marker_pins() -> None:
    from fpbench.experiments.stage10a_finalization import _STAGE_10A_SOURCE_FILES

    assert set(_STAGE_10A_SOURCE_FILES) == set(frozen.STAGE_10A_SOURCE_FILES)
    for relative in frozen.STAGE_10A_SOURCE_FILES:
        assert (REPOSITORY_ROOT / Path(relative)).is_file(), relative
    for relative in frozen.STAGE_10A_ADRS + frozen.STAGE_10A_DOCUMENTS:
        assert (REPOSITORY_ROOT / Path(relative)).is_file(), relative
