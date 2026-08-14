"""The frozen Stage 13A contract: ten gates, four states, one fake engine.

No vendor archive, no licence, no network, no dataset and no workspace. This
suite runs anywhere, which is the same claim the stage makes about itself:
without a delivered trial there is nothing here but a state machine, a set of
schemas and a harness proved against a double.

What is under test is the shape of the decision rather than the decision. The
gate order, the ``ACTION_REQUIRED``/``FAIL`` split, the sibling-product
contamination guard, the single-finger rule, the raw-score requirement, the
settings closure, the pair binding, the four mandatory failure probes, the secret
guard and the two-outcome marker are the stage; what they produced on any
particular machine is not.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fpbench.core.errors import FpbenchError
from fpbench.core.fingercell_preflight_errors import (
    FingerCellAcquisitionError,
    FingerCellCandidateIdentityError,
    FingerCellContaminationError,
    FingerCellGateError,
    FingerCellObservationError,
    FingerCellPreflightError,
    FingerCellQualificationError,
    FingerCellSensitiveEvidenceError,
    Stage13AFinalizationError,
)
from fpbench.experiments import stage13a_acquisition as store
from fpbench.experiments import stage13a_fingercell_identity as frozen
from fpbench.experiments import stage13a_fingercell_observations as observed
from fpbench.experiments import stage13a_preflight as engine
from fpbench.experiments import stage13a_qualification as harness
from fpbench.experiments.algorithm_research import REPOSITORY_ROOT
from fpbench.experiments.stage13a_finalization import (
    Stage13AFinalization,
    require_expected_evidence_files,
    stage_13a_finalization_fingerprint,
)

pytestmark = pytest.mark.stage13a_contract


# ------------------------------------------------------------- the vocabulary


def test_every_error_descends_from_the_project_root() -> None:
    for error in (
        FingerCellPreflightError,
        FingerCellCandidateIdentityError,
        FingerCellObservationError,
        FingerCellAcquisitionError,
        FingerCellGateError,
        FingerCellQualificationError,
        FingerCellContaminationError,
        FingerCellSensitiveEvidenceError,
        Stage13AFinalizationError,
    ):
        assert issubclass(error, FpbenchError)


def test_the_candidate_and_slot_are_frozen() -> None:
    assert frozen.CANDIDATE_ID == "neurotechnology_fingercell_3_3_1to1"
    assert frozen.ALGORITHM_SLOT == "algorithm_5"
    assert frozen.PRODUCT_FAMILY == "FingerCell"
    assert frozen.DECLARED_PRODUCT_VERSION == "3.3"
    assert frozen.PRODUCTION_ALGORITHM_ID_FROZEN is False


def test_there_are_exactly_ten_gates_in_the_frozen_order() -> None:
    assert frozen.GATE_COUNT == 10
    assert len(set(frozen.GATE_ORDER)) == 10
    assert frozen.GATE_ORDER[0] is frozen.PreflightGate.OFFICIAL_ARTIFACT_ACQUISITION
    assert frozen.GATE_ORDER[-1] is frozen.PreflightGate.TRAINING_PROVENANCE


def test_there_are_exactly_four_gate_states_and_no_vendor_pending() -> None:
    """Acquisition is self-service here, so there is nothing to wait on a vendor for."""
    assert {status.value for status in frozen.GateStatus} == {
        "PASS",
        "FAIL",
        "ACTION_REQUIRED",
        "NOT_REACHED",
    }
    assert "PENDING_VENDOR" not in {status.value for status in frozen.GateStatus}
    assert frozen.GateStatus.PASS.is_final and frozen.GateStatus.FAIL.is_final
    assert not frozen.GateStatus.ACTION_REQUIRED.is_final
    assert not frozen.GateStatus.NOT_REACHED.is_final


def test_blockers_and_outstanding_actions_are_disjoint_vocabularies() -> None:
    """The distinction this stage exists to keep, checked as a set operation."""
    blockers = {code.value for code in frozen.BlockerCode}
    actions = {action.value for action in frozen.RequiredAction}
    assert not blockers & actions


def test_every_blocker_and_action_belongs_to_exactly_one_gate() -> None:
    for code in frozen.BlockerCode:
        assert len(frozen.gate_of_blocker(code)) == 1
    for action in frozen.RequiredAction:
        assert len(frozen.gate_of_action(action)) == 1


def test_each_gate_reports_through_exactly_one_document() -> None:
    seen: list[str] = []
    for gate in frozen.GATE_ORDER:
        names = frozen.gate_documents(gate)
        assert len(names) == 1, gate
        seen.extend(names)
    assert len(seen) == len(set(seen))
    assert set(seen) <= set(frozen.REQUIRED_EVIDENCE_FILES)


def test_thirteen_documents_and_a_readme_are_published() -> None:
    assert frozen.README_NAME in frozen.REQUIRED_EVIDENCE_FILES
    json_documents = [
        name for name in frozen.REQUIRED_EVIDENCE_FILES if name.endswith(".json")
    ]
    assert len(json_documents) == 13
    assert frozen.STAGE_13A_FINALIZATION_NAME in json_documents
    assert len(frozen.DERIVABLE_EVIDENCE_FILES) == 12


# --------------------------------------------------------- the predecessor


def test_the_predecessor_is_the_exact_closed_stage_12a_marker() -> None:
    assert frozen.STAGE_12A_OUTCOME == "IDKIT_PREFLIGHT_FAIL"
    assert frozen.STAGE_12A_FAILURE_CLASS == "VENDOR_ACCESS_REFUSED"
    assert frozen.STAGE_12A_FINALIZATION_FINGERPRINT == (
        "d3ef1127be38c75b932bdb8d2400da2608fbbf543223f78621535c0f24df321b"
    )


def test_the_bound_predecessor_matches_the_published_stage_12a_marker() -> None:
    """No placeholder was ever written here: the value came from the closed marker."""
    found = engine.require_stage12a_is_the_closed_predecessor(REPOSITORY_ROOT)
    assert found == frozen.STAGE_12A_FINALIZATION_FINGERPRINT


def test_stage_11b_and_stage_8e_stay_bound_and_unedited() -> None:
    assert engine.require_stage11b_is_unchanged(REPOSITORY_ROOT) == (
        frozen.STAGE_11B_FINALIZATION_FINGERPRINT
    )
    engine.require_stage8e_is_the_policy_this_reuses(REPOSITORY_ROOT)


# ------------------------------------------------------ the vendor revision hash


def test_a_vendor_revision_hash_can_never_be_used_as_an_archive_digest() -> None:
    """Forty hex characters look enough like a digest to be pasted into one."""
    assert len(frozen.VENDOR_REVISION_HASH_INDICATION) == 40
    assert frozen.VENDOR_REVISION_HASH_IS_NOT_A_DIGEST is True
    with pytest.raises(FingerCellAcquisitionError, match="64-character"):
        store.ArchiveDeclaration(
            official_locator_category=frozen.LocatorCategory.VENDOR_DIRECT_DOWNLOAD,
            official_locator="https://download.example.invalid/x.zip",
            filename="x.zip",
            size_bytes=1,
            sha256=frozen.VENDOR_REVISION_HASH_INDICATION,
            downloaded_utc="2026-08-14T00:00:00Z",
            product="FingerCell",
            product_version="3.3",
            vendor_product_revision="20211013",
            vendor_revision_hash=frozen.VENDOR_REVISION_HASH_INDICATION,
            documentation_obtained=True,
        )


def test_a_signed_or_tokenized_locator_is_never_published() -> None:
    with pytest.raises(FingerCellAcquisitionError, match="signed URL"):
        store.ArchiveDeclaration(
            official_locator_category=frozen.LocatorCategory.VENDOR_DIRECT_DOWNLOAD,
            official_locator="https://example.invalid/x.zip?token=abcdef123456",
            filename="x.zip",
            size_bytes=1,
            sha256="a" * 64,
            downloaded_utc="2026-08-14T00:00:00Z",
            product="FingerCell",
            product_version="3.3",
            vendor_product_revision="20211013",
            vendor_revision_hash=frozen.VENDOR_REVISION_HASH_INDICATION,
            documentation_obtained=True,
        )


# ------------------------------------------------------------- the gate machine


def test_a_gate_that_passed_carries_nothing_outstanding() -> None:
    with pytest.raises(FingerCellGateError, match="no blockers"):
        engine.GateResult(
            gate=frozen.PreflightGate.TRAINING_PROVENANCE,
            status=frozen.GateStatus.PASS,
            summary="x",
            outstanding=engine.OutstandingAction(
                gate=frozen.PreflightGate.TRAINING_PROVENANCE,
                action=frozen.RequiredAction.PROVENANCE_NOT_SEARCHED,
                what_has_been_done="nothing",
                what_remains=("search",),
                what_it_would_answer="whether there is an overlap",
            ),
        )


def test_an_outstanding_action_can_never_carry_a_blocker() -> None:
    """The one confusion the four-state vocabulary exists to prevent."""
    with pytest.raises(FingerCellGateError, match="nothing has been found"):
        engine.GateResult(
            gate=frozen.PreflightGate.TRAINING_PROVENANCE,
            status=frozen.GateStatus.ACTION_REQUIRED,
            summary="x",
            blockers=(
                engine.Blocker(
                    gate=frozen.PreflightGate.TRAINING_PROVENANCE,
                    blocker_code=frozen.BlockerCode.SD300_OVERLAP_FOUND,
                    affected_component="c",
                    evidence="e",
                    why_this_blocks_algorithm_5="w",
                    how_this_would_be_lifted="h",
                ),
            ),
        )


def test_a_gate_awaiting_an_action_names_which_action() -> None:
    with pytest.raises(FingerCellGateError, match="says which action"):
        engine.GateResult(
            gate=frozen.PreflightGate.TRAINING_PROVENANCE,
            status=frozen.GateStatus.ACTION_REQUIRED,
            summary="x",
        )


def test_a_failing_gate_names_why() -> None:
    with pytest.raises(FingerCellGateError, match="names why"):
        engine.GateResult(
            gate=frozen.PreflightGate.TRAINING_PROVENANCE,
            status=frozen.GateStatus.FAIL,
            summary="x",
        )


def test_a_blocker_cannot_be_raised_at_a_gate_it_does_not_belong_to() -> None:
    with pytest.raises(FingerCellGateError, match="does not belong"):
        engine.Blocker(
            gate=frozen.PreflightGate.TRAINING_PROVENANCE,
            blocker_code=frozen.BlockerCode.OFFICIAL_TRIAL_UNAVAILABLE,
            affected_component="c",
            evidence="e",
            why_this_blocks_algorithm_5="w",
            how_this_would_be_lifted="h",
        )


def test_an_action_cannot_be_reported_at_a_gate_it_does_not_belong_to() -> None:
    with pytest.raises(FingerCellGateError, match="does not belong"):
        engine.OutstandingAction(
            gate=frozen.PreflightGate.TRAINING_PROVENANCE,
            action=frozen.RequiredAction.ARCHIVE_NOT_ACQUIRED,
            what_has_been_done="x",
            what_remains=("y",),
            what_it_would_answer="z",
        )


def test_an_outstanding_action_must_name_what_remains() -> None:
    with pytest.raises(FingerCellGateError, match="names what would move it"):
        engine.OutstandingAction(
            gate=frozen.PreflightGate.TRAINING_PROVENANCE,
            action=frozen.RequiredAction.PROVENANCE_NOT_SEARCHED,
            what_has_been_done="x",
            what_remains=(),
            what_it_would_answer="z",
        )


def test_the_run_reports_every_gate_in_the_frozen_order() -> None:
    preflight = engine.run_preflight()
    assert tuple(r.gate for r in preflight.results) == frozen.GATE_ORDER
    assert preflight.outcome in frozen.STAGE_13A_OUTCOMES


def test_only_a_failure_stops_the_run() -> None:
    """An unpaid chore must not hide nine later answers (docs/adr/0104)."""
    preflight = engine.run_preflight()
    failed = [r for r in preflight.results if r.status is frozen.GateStatus.FAIL]
    assert len(failed) <= 1
    if failed:
        index = preflight.results.index(failed[0])
        for later in preflight.results[index + 1 :]:
            assert later.status is frozen.GateStatus.NOT_REACHED
    else:
        assert not [
            r for r in preflight.results if r.status is frozen.GateStatus.NOT_REACHED
        ]


def test_an_outstanding_action_does_not_stop_the_run() -> None:
    preflight = engine.run_preflight()
    awaiting = [
        r for r in preflight.results if r.status is frozen.GateStatus.ACTION_REQUIRED
    ]
    if awaiting and preflight.stopped_at is None:
        assert len(preflight.outstanding_actions) == len(awaiting)
        assert preflight.gates_awaiting_action == len(awaiting)


def test_a_run_that_failed_reports_no_gate_as_never_reached_without_a_failure() -> None:
    preflight = engine.run_preflight()
    if preflight.stopped_at is None:
        for result in preflight.results:
            assert result.status is not frozen.GateStatus.NOT_REACHED


def test_an_incomplete_run_reopens_nothing_and_opens_nothing() -> None:
    """It is not a verdict, so it neither admits nor rejects the candidate."""
    preflight = engine.run_preflight()
    if preflight.is_incomplete:
        assert preflight.outcome == frozen.STAGE_13A_INCOMPLETE_OUTCOME
        assert preflight.opens_stage_13b is False
        assert preflight.reopens_algorithm_5_search is False
        assert preflight.failure_class is None
        assert not preflight.blockers


def test_not_searched_provenance_is_an_action_and_never_an_overlap() -> None:
    assert frozen.SD300OverlapStatus.NOT_SEARCHED.passes is False
    assert frozen.SD300OverlapStatus.NO_EVIDENCE_FOUND.passes
    assert frozen.SD300OverlapStatus.VENDOR_DENIAL_OBTAINED.passes
    assert frozen.SD300OverlapStatus.OVERLAP_FOUND.passes is False
    preflight = engine.run_preflight()
    if preflight.status(frozen.PreflightGate.TRAINING_PROVENANCE) is (
        frozen.GateStatus.ACTION_REQUIRED
    ):
        assert preflight.sd300_overlap_status is frozen.SD300OverlapStatus.NOT_SEARCHED


# ------------------------------------------------------ the same-vendor guard


def test_no_stage_13a_module_imports_the_sibling_algorithm() -> None:
    """Stage 13A's own hazard: both candidates come from the same vendor."""
    audited = engine.require_no_verifinger_contamination(REPOSITORY_ROOT)
    assert set(audited) == set(frozen.STAGE_13A_SOURCE_FILES)


def test_the_contamination_guard_bites_on_a_sibling_import(tmp_path: Path) -> None:
    module = tmp_path / "src" / "fpbench" / "experiments"
    module.mkdir(parents=True)
    target = module / "stage13a_fingercell_identity.py"
    target.write_text(
        "from fpbench.adapters." + "verifinger_java import x\n", encoding="utf-8"
    )
    with pytest.raises(FingerCellContaminationError, match="sibling algorithm"):
        engine.require_no_verifinger_contamination(tmp_path)


def test_common_runtime_components_are_permitted_and_the_algorithm_ones_are_not() -> None:
    assert frozen.PERMITTED_COMMON_RUNTIME_COMPONENTS
    assert frozen.VERIFINGER_ALGORITHM_COMPONENTS
    assert frozen.RUNTIME_CLOSURE_IS_NOT_INHERITED_FROM_A_SIBLING is True
    assert "extractor" in " ".join(frozen.VERIFINGER_ALGORITHM_COMPONENTS)
    assert "matcher" in " ".join(frozen.VERIFINGER_ALGORITHM_COMPONENTS)


def test_a_running_licensing_service_is_not_evidence_about_this_product() -> None:
    assert "does not imply" in frozen.SAME_VENDOR_LICENSING_ISOLATION
    assert "reactivating an expired trial" in frozen.REFUSED_LICENSE_ACTIONS
    assert "resetting a trial clock" in frozen.REFUSED_LICENSE_ACTIONS


# ---------------------------------------------------------------- the route


def test_the_pair_binding_uses_the_words_the_api_under_test_uses() -> None:
    assert frozen.PAIR_ROLE_BINDING == (
        ("pair.left", "reference"),
        ("pair.right", "candidate"),
    )
    assert frozen.PAIR_LABELS_ARE_NOT_COPIED_FROM_ANOTHER_CANDIDATE is True
    roles = {right for _, right in frozen.PAIR_ROLE_BINDING}
    assert "probe" not in roles and "gallery" not in roles


def test_no_orientation_reduction_is_permitted() -> None:
    for reduction in ("max", "min", "average"):
        assert reduction in frozen.REFUSED_ORIENTATION_REDUCTIONS


def test_the_score_contract_is_a_native_integer_higher_is_more_similar() -> None:
    assert frozen.SCORE_NATIVE_TYPE == "signed_integer"
    assert frozen.SCORE_DIRECTION == "HIGHER_IS_MORE_SIMILAR"
    assert frozen.FPBENCH_SCORE_TRANSFORMATION == "NONE"
    assert frozen.SCORE_RANGE_IS_NOT_ASSUMED is True
    assert frozen.ScoreRouteStatus.NATIVE_SCALAR.is_raw_score
    assert not frozen.ScoreRouteStatus.DECISION_ONLY.is_raw_score
    assert not frozen.ScoreRouteStatus.UNRESOLVED.is_raw_score


def test_no_threshold_decision_or_calibration_happens_in_this_stage() -> None:
    assert frozen.THRESHOLD_PRODUCED is False
    assert frozen.DECISION_PRODUCED is False
    assert frozen.CALIBRATION_PERFORMED is False


def test_the_canonical_image_is_never_resized_to_an_embedded_sample_size() -> None:
    assert frozen.EMBEDDED_BENCHMARK_SAMPLE_DIMENSIONS == (234, 332)
    assert frozen.SAMPLE_DIMENSIONS_ARE_NOT_A_PREPROCESSING_RULE is True
    for refused in ("crop", "resize", "pad", "rotate"):
        assert refused in frozen.REFUSED_PREPROCESSING


def test_the_ppi_must_be_effective_at_extraction_not_set_afterwards() -> None:
    assert frozen.REQUIRED_INPUT_PPI == 500
    assert frozen.PPI_MUST_BE_EFFECTIVE_AT_EXTRACTION is True


def test_template_merging_and_caching_are_refused() -> None:
    assert "MergeTemplates" in frozen.REFUSED_TEMPLATE_CONSTRUCTIONS
    assert frozen.TEMPLATE_CACHE_PERMITTED is False
    assert frozen.REQUIRED_TEMPLATE_FORMAT is frozen.TemplateFormat.PROPRIETARY


def test_quality_rejection_is_a_failure_and_the_threshold_is_not_tuned() -> None:
    assert frozen.QUALITY_REJECTION_IS_PART_OF_THE_ALGORITHM is True
    assert "increase the number of images" in (
        frozen.REFUSED_QUALITY_THRESHOLD_TUNING
    )


# ------------------------------------------------------------- the settings


def test_an_unresolved_score_affecting_setting_has_no_authority() -> None:
    assert not frozen.SettingProvenance.UNRESOLVED.is_upstream_authority
    for provenance in frozen.SettingProvenance:
        if provenance is not frozen.SettingProvenance.UNRESOLVED:
            assert provenance.is_upstream_authority


def test_the_refused_provenance_is_not_selectable() -> None:
    assert frozen.REFUSED_SETTING_PROVENANCE not in {
        item.value for item in frozen.SettingProvenance
    }


def test_the_settings_list_is_explicitly_not_exhaustive() -> None:
    """The archive is entitled to have knobs nobody wrote down in advance."""
    assert frozen.SETTINGS_LIST_IS_NOT_EXHAUSTIVE is True
    assert frozen.SETTINGS_ARE_READ_BEFORE_THEY_ARE_SET is True
    assert len(frozen.SETTING_DISCOVERY_SURFACES) >= 4


def test_the_matching_algorithm_is_never_forced_back_silently() -> None:
    assert frozen.MATCHING_ALGORITHM_EXPECTED_VALUE == 0
    assert frozen.MATCHING_ALGORITHM_IS_NOT_FORCED_SILENTLY is True


def test_settings_with_no_authority_are_reported_as_unresolved() -> None:
    rows = [
        {"name": "A", "provenance": "DELIVERED_RUNTIME_DEFAULT",
         "can_affect_template_or_score": True},
        {"name": "B", "provenance": "UNRESOLVED", "can_affect_template_or_score": True},
        {"name": "C", "provenance": "nonsense", "can_affect_template_or_score": True},
        {"name": "D", "provenance": "UNRESOLVED",
         "can_affect_template_or_score": False},
    ]
    engine._RUN_CACHE["inspection"] = {"settings": rows}
    try:
        assert engine.unresolved_score_affecting_settings() == ("B", "C")
    finally:
        engine._RUN_CACHE.clear()


# ------------------------------------------------------------ the qualification


def test_the_harness_reaches_a_passing_record_against_the_fake(tmp_path: Path) -> None:
    """A double that could never pass would prove only that the harness can fail."""
    fixtures = harness.build_fixtures(tmp_path, width=96, height=120)
    record = harness.run_qualification(
        harness.fake_engine_factory,
        fixtures,
        engine_kind=harness.EngineKind.FAKE_SDK,
    )
    assert record.status is frozen.QualificationOutcome.SUCCESS, record.failure_detail
    assert record.scoring_comparisons <= frozen.QUALIFICATION_MAX_SCORING_COMPARISONS
    assert all(record.determinism[level] for level in frozen.DETERMINISM_LEVELS)


def test_the_harness_provokes_all_four_mandatory_failure_probes(tmp_path: Path) -> None:
    fixtures = harness.build_fixtures(tmp_path, width=96, height=120)
    record = harness.run_qualification(
        harness.fake_engine_factory,
        fixtures,
        engine_kind=harness.EngineKind.FAKE_SDK,
    )
    provoked = {
        item["cause"] for item in record.failure_probes if item["behaved_correctly"]
    }
    assert provoked == {cause for cause, _ in frozen.MANDATORY_FAILURE_PROBES}
    assert len(provoked) == frozen.MANDATORY_FAILURE_PROBE_COUNT == 4
    assert not any(item["produced_a_score"] for item in record.failure_probes)


def test_a_record_missing_one_mandatory_probe_is_refused(tmp_path: Path) -> None:
    """'At least one' is how a route's failure semantics stay half known."""
    fixtures = harness.build_fixtures(tmp_path, width=96, height=120)
    record = harness.run_qualification(
        harness.fake_engine_factory,
        fixtures,
        engine_kind=harness.EngineKind.FAKE_SDK,
    )
    short = [
        item
        for item in record.failure_probes
        if item["cause"] != "missing_or_invalid_input"
    ]
    with pytest.raises(FingerCellQualificationError, match="mandatory failure probes"):
        harness.QualificationRecord(
            schema=record.schema,
            engine_kind=record.engine_kind,
            status=record.status,
            scoring_comparisons=record.scoring_comparisons,
            comparisons=record.comparisons,
            determinism=record.determinism,
            pair_orientation=record.pair_orientation,
            self_semantics=record.self_semantics,
            failure_probes=tuple(short),
            timings=record.timings,
            binding=record.binding,
            started_utc=record.started_utc,
        )


def test_self_comes_from_two_independent_extractions(tmp_path: Path) -> None:
    fixtures = harness.build_fixtures(tmp_path, width=96, height=120)
    record = harness.run_qualification(
        harness.fake_engine_factory,
        fixtures,
        engine_kind=harness.EngineKind.FAKE_SDK,
    )
    assert record.self_semantics["independent_extractions"] == 2
    assert record.self_semantics["templates_shared"] is False
    assert record.self_semantics["template_cache_used"] is False


def test_no_score_value_reaches_the_record(tmp_path: Path) -> None:
    fixtures = harness.build_fixtures(tmp_path, width=96, height=120)
    record = harness.run_qualification(
        harness.fake_engine_factory,
        fixtures,
        engine_kind=harness.EngineKind.FAKE_SDK,
    )
    payload = json.dumps(record.payload)
    for item in record.comparisons:
        assert len(item.score_digest) == 64
    assert '"score"' not in payload and '"raw_score"' not in payload


def test_the_comparison_ceiling_is_enforced_where_comparisons_happen() -> None:
    budget = harness._Budget(remaining=1)
    budget.spend()
    with pytest.raises(FingerCellQualificationError, match="budget is exhausted"):
        budget.spend()


def test_a_non_proprietary_template_is_refused() -> None:
    with pytest.raises(FingerCellQualificationError, match="PROPRIETARY"):
        harness.Template(
            size_bytes=10, template_format=frozen.TemplateFormat.ISO, digest="d"
        )


def test_a_fake_record_never_answers_a_gate() -> None:
    """It proves the harness and nothing else."""
    assert harness.EngineKind.FAKE_SDK.value != harness.EngineKind.DELIVERED_SDK.value


def test_a_failed_run_is_kept_rather_than_discarded(tmp_path: Path) -> None:
    class Broken:
        def extract(self, image_path):  # noqa: ANN001, ANN202
            raise RuntimeError("the runtime went away")

        def match(self, reference, candidate):  # noqa: ANN001, ANN202
            raise AssertionError("unreachable")

        def describe(self):  # noqa: ANN202
            return {}

    fixtures = harness.build_fixtures(tmp_path, width=96, height=120)
    record = harness.run_qualification(
        Broken, fixtures, engine_kind=harness.EngineKind.FAKE_SDK
    )
    assert record.status is frozen.QualificationOutcome.FAILED
    assert record.failed_at
    assert frozen.FAILED_QUALIFICATION_IS_KEPT is True


def test_a_gray8_png_round_trips_to_the_same_pixels(tmp_path: Path) -> None:
    pixels = harness.ridge_field(48, 32, seed=3)
    path = harness.write_gray8_png(tmp_path / "x.png", pixels)
    width, height, raw = harness.decode_gray8_png(path)
    assert (width, height) == (48, 32)
    assert list(raw) == [value for row in pixels for value in row]


# --------------------------------------------------------------- the guards


def test_the_secret_guard_bites_on_keys_and_on_value_shapes() -> None:
    for probe in (
        {"machine_id": "whatever"},
        {"trial_token": "whatever"},
        {"licensing_server": "whatever"},
        {"note": "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE"},
        {"path": "/home/someone/archives"},
        {"locator": "https://example.invalid/a?X-Amz-Signature=abc"},
    ):
        assert engine.find_sensitive_material(probe), probe
        with pytest.raises(FingerCellSensitiveEvidenceError):
            engine.require_no_sensitive_material(probe, where="a probe")


def test_the_secret_guard_does_not_refuse_an_ordinary_vendor_locator() -> None:
    """A guard that refused the official URL is a guard somebody switches off."""
    assert not engine.find_sensitive_material(
        {"official_locator": observed.OFFICIAL_LOCATOR}
    )


def test_no_forbidden_key_is_also_a_published_vocabulary_value() -> None:
    vocabulary = {value.lower() for value in frozen.all_frozen_identifiers()}
    assert not (frozen.FORBIDDEN_PUBLISHED_KEYS & vocabulary)


def test_every_derived_document_is_free_of_licence_material() -> None:
    preflight = engine.run_preflight()
    for name in frozen.DERIVABLE_EVIDENCE_FILES:
        document = engine.evidence_document(preflight, name)
        assert not engine.find_sensitive_material(document), name


def test_published_runtime_paths_are_relative_to_the_store() -> None:
    assert frozen.PUBLISHED_PATHS_ARE_RELATIVE is True
    with pytest.raises(FingerCellAcquisitionError, match="never name a machine"):
        store.RuntimeComponent(
            relative_path="C:/Users/someone/x.dll",
            component_role=frozen.ComponentRole.FINGERCELL_ALGORITHM,
            size_bytes=1,
            sha256="a" * 64,
            version_or_revision=None,
            source_archive_member="x.dll",
        )


def test_the_sd300_and_prior_score_firewall_is_declared() -> None:
    for forbidden in (
        "sd300_image_bytes",
        "sd300_pair_manifest",
        "sd300_scores",
        "sourceafis_scores",
        "nbis_scores",
        "flx_scores",
        "verifinger_scores",
    ):
        assert forbidden in frozen.FORBIDDEN_READS


def test_public_ci_never_touches_a_vendor_runtime() -> None:
    for refused in ("download FingerCell", "activate a trial", "produce a biometric score"):
        assert refused in frozen.CI_MUST_NOT


# ---------------------------------------------------------------- the marker


def _pass_claims() -> dict:
    """A minimal set of claims a PASS marker would have to carry."""
    orientation = "_".join(
        f"{left.split('.')[-1]}_{right}" for left, right in frozen.PAIR_ROLE_BINDING
    )
    return {
        "schema_version": frozen.STAGE_13A_SCHEMA_VERSION,
        "kind": frozen.STAGE_FINALIZATION_KIND,
        "outcome": frozen.STAGE_13A_PASS_OUTCOME,
        "algorithm_slot": frozen.ALGORITHM_SLOT,
        "candidate": frozen.CANDIDATE_ID,
        "stage12a_outcome": frozen.STAGE_12A_OUTCOME,
        "stage12a_failure_class": frozen.STAGE_12A_FAILURE_CLASS,
        "stage12a_finalization_fingerprint": (
            frozen.STAGE_12A_FINALIZATION_FINGERPRINT
        ),
        "stage11b_finalization_fingerprint": (
            frozen.STAGE_11B_FINALIZATION_FINGERPRINT
        ),
        "stage8e_policy_fingerprint": frozen.STAGE8E_FINALIZATION_FINGERPRINT,
        "stage13a_source_fingerprint": "b" * 64,
        "observations_fingerprint": "c" * 64,
        "preflight_fingerprint": "d" * 64,
        "gate_count_defined": frozen.GATE_COUNT,
        "gates_reached": frozen.GATE_COUNT,
        "gates_passed": frozen.GATE_COUNT,
        "gates_awaiting_action": 0,
        "product": "FingerCell",
        "product_version": "3.3",
        "product_revision": "20211013",
        "package_sha256": "e" * 64,
        "platform": "windows/x86_64",
        "binding": "CPP",
        "implementation_origin": frozen.IMPLEMENTATION_ORIGIN,
        "official_trial_obtained": True,
        "runtime_closure_pinned": True,
        "verifinger_component_in_route": False,
        "research_use_opens_execution": True,
        "research_use_blocked": False,
        "trial_activated": True,
        "trial_workload_sufficient": True,
        "license_bypass_attempted": False,
        "trial_reset_attempted": False,
        "canonical500_route": True,
        "fpbench_preprocessing_required": False,
        "ppi_500_effective_at_extraction": True,
        "single_finger_template": True,
        "template_format": "PROPRIETARY",
        "template_merging": False,
        "template_cache_used": False,
        "extractor_settings_frozen": True,
        "hidden_score_affecting_settings": 0,
        "raw_score_route": True,
        "score_native_type": "signed_integer",
        "score_direction": frozen.SCORE_DIRECTION,
        "threshold_applied_inside_the_score": False,
        "fpbench_score_transformation": frozen.FPBENCH_SCORE_TRANSFORMATION,
        "pair_orientation": orientation,
        "self_independent_extraction": True,
        "repeat_determinism": True,
        "restart_determinism": True,
        "mandatory_failure_probes_passed": frozen.MANDATORY_FAILURE_PROBE_COUNT,
        "local_smoke_passed": True,
        "runtime_timing_measured": True,
        "training_provenance": "PROPRIETARY_UNDISCLOSED",
        "sd300_overlap_status": "NO_EVIDENCE_FOUND",
        "sd300_used": False,
        "failure_class": None,
        "sd300_image_bytes_read": False,
        "sd300_pair_manifest_read": False,
        "sd300_scores_read": False,
        "prior_algorithm_scores_read": False,
        "production_adapter_created": False,
        "registry_integration_created": False,
        "canonical_experiment_config_created": False,
        "benchmark_run_performed": False,
        "result_set_produced": False,
        "decision_profile_produced": False,
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
        "stage12a_evidence_changed": False,
        "opens_stage_13b": True,
        "reopens_algorithm_5_search": False,
        "blockers": (),
        "evidence_content_hashes": {"README.md": "f" * 64},
        "source_commit": "0" * 40,
        "source_tree_clean": True,
        "verifier_source_commit": "0" * 40,
        "verifier_source_tree_clean": True,
    }


def _marker(**overrides) -> Stage13AFinalization:
    claims = {**_pass_claims(), **overrides}
    return Stage13AFinalization(
        **claims,
        stage_13a_finalization_fingerprint=stage_13a_finalization_fingerprint(claims),
        created_utc="2026-08-14T00:00:00Z",
    )


def test_a_pass_marker_validates_and_opens_stage_13b() -> None:
    marker = _marker()
    assert marker.outcome == frozen.STAGE_13A_PASS_OUTCOME
    assert marker.opens_stage_13b is True


def test_no_marker_can_ever_carry_the_incomplete_outcome() -> None:
    """The shape that would otherwise be used."""
    with pytest.raises(ValueError, match="never of a finalization"):
        _marker(outcome=frozen.STAGE_13A_INCOMPLETE_OUTCOME)


def test_a_marker_cannot_be_written_with_a_gate_awaiting_an_action() -> None:
    with pytest.raises(ValueError, match="no gate awaiting a local action"):
        _marker(gates_awaiting_action=1)


def test_a_pass_marker_cannot_leave_a_setting_unresolved() -> None:
    with pytest.raises(ValueError, match="no score-affecting setting unresolved"):
        _marker(hidden_score_affecting_settings=1)


def test_a_pass_marker_needs_all_four_failure_probes() -> None:
    with pytest.raises(ValueError, match="mandatory failure probes"):
        _marker(mandatory_failure_probes_passed=3)


def test_a_pass_marker_cannot_carry_a_sibling_component_in_the_route() -> None:
    with pytest.raises(ValueError, match="verifinger_component_in_route"):
        _marker(verifinger_component_in_route=True)


def test_a_marker_cannot_claim_a_score_transformation() -> None:
    with pytest.raises(ValueError, match="no score transformation"):
        _marker(fpbench_score_transformation="rescaled")


def test_a_marker_cannot_relabel_the_pair_orientation() -> None:
    with pytest.raises(ValueError, match="pair_orientation must be"):
        _marker(pair_orientation="left_probe_right_gallery")


def test_a_marker_must_bind_the_exact_stage_12a_fingerprint() -> None:
    with pytest.raises(ValueError, match="exact Stage 12A marker"):
        _marker(stage12a_finalization_fingerprint="9" * 64)


def test_a_fail_marker_needs_a_blocker_and_a_failure_class() -> None:
    with pytest.raises(ValueError, match="names which blockers"):
        _marker(
            outcome=frozen.STAGE_13A_FAIL_OUTCOME,
            gates_passed=1,
            opens_stage_13b=False,
            reopens_algorithm_5_search=True,
            failure_class="LOCAL_SMOKE_FAILED",
            blockers=(),
        )


def test_a_fail_marker_publishes_the_unestablished_as_unestablished() -> None:
    blocker = {
        "gate": "OFFICIAL_ARTIFACT_ACQUISITION",
        "blocker_code": "OFFICIAL_TRIAL_UNAVAILABLE",
        "affected_component": "c",
        "evidence": "e",
        "why_this_blocks_algorithm_5": "w",
        "how_this_would_be_lifted": "h",
    }
    with pytest.raises(ValueError, match="published as unestablished"):
        _marker(
            outcome=frozen.STAGE_13A_FAIL_OUTCOME,
            gates_reached=1,
            gates_passed=0,
            official_trial_obtained=False,
            opens_stage_13b=False,
            reopens_algorithm_5_search=True,
            failure_class="OFFICIAL_TRIAL_UNAVAILABLE",
            blockers=(blocker,),
        )


def test_the_fingerprint_covers_the_claims() -> None:
    claims = _pass_claims()
    marker = _marker()
    tampered = dict(claims)
    tampered["opens_stage_13b"] = False
    assert stage_13a_finalization_fingerprint(tampered) != (
        marker.stage_13a_finalization_fingerprint
    )


def test_the_evidence_file_set_is_exact() -> None:
    with pytest.raises(Stage13AFinalizationError, match="missing"):
        require_expected_evidence_files(("README.md",))
    with pytest.raises(Stage13AFinalizationError, match="holds"):
        require_expected_evidence_files(
            frozen.REQUIRED_EVIDENCE_FILES + ("stray.json",)
        )


# ------------------------------------------------------------- the observations


def test_a_public_page_never_settles_a_gate() -> None:
    for item in observed.PUBLIC_OBSERVATIONS:
        assert item.weight is observed.ObservationWeight.INDICATION_ONLY


def test_a_delivered_fact_from_compiled_metadata_settles_nothing() -> None:
    """Binary metadata asks a question; the runtime answers it (docs/adr/0120)."""
    method = observed.DeliveredEvidenceMethod.COMPILED_MODULE_METADATA
    assert method.may_settle_a_gate is False
    from_metadata = [
        item for item in observed.DELIVERED_OBSERVATIONS if item.method is method
    ]
    assert from_metadata
    for item in from_metadata:
        assert item.weight is observed.ObservationWeight.INDICATION_ONLY


def test_delivered_text_and_headers_are_authorities() -> None:
    for method in (
        observed.DeliveredEvidenceMethod.DELIVERED_TEXT_FILE,
        observed.DeliveredEvidenceMethod.DELIVERED_HEADER,
        observed.DeliveredEvidenceMethod.DELIVERED_SAMPLE_SOURCE,
    ):
        assert method.may_settle_a_gate is True


def test_a_delivered_observation_never_names_a_machine() -> None:
    for item in observed.DELIVERED_OBSERVATIONS:
        assert not item.member.startswith("/")
        assert ":" not in item.member
    with pytest.raises(FingerCellObservationError, match="never name a machine"):
        observed.DeliveredObservation(
            observation_id="x",
            member="C:/Users/someone/x",
            statement="s",
            method=observed.DeliveredEvidenceMethod.DELIVERED_TEXT_FILE,
            what_it_settles="w",
        )


def test_the_observations_fingerprint_is_stable() -> None:
    assert observed.observations_fingerprint() == observed.observations_fingerprint()
    assert len(observed.observations_fingerprint()) == 64


# ------------------------------------------------------------- the workload


def test_the_frozen_workload_extracts_both_sides_of_every_comparison() -> None:
    workload = frozen.FROZEN_WORKLOAD
    assert workload.comparison_attempts == 6_000
    assert workload.independent_extractions == 12_000
    assert workload.matcher_invocations == 6_000
    assert workload.total_logical_operations > 18_000


def test_a_workload_with_a_template_cache_is_refused() -> None:
    with pytest.raises(FingerCellCandidateIdentityError, match="template cache"):
        frozen.FrozenWorkload(
            comparison_attempts=6_000,
            independent_extractions=6_000,
            matcher_invocations=6_000,
            qualification_allowance=20,
        )


def test_an_unresolved_quota_cannot_pass() -> None:
    assert frozen.UNRESOLVED_QUOTA_BLOCKS_PASS is True
    assert frozen.QuotaSchema.UNRESOLVED.value == "UNRESOLVED"
    assert frozen.VENDOR_EMBEDDED_FIGURES_ARE_NOT_A_PC_ESTIMATE is True


# ------------------------------------------------------------ what is not built


def test_this_stage_builds_no_production_integration() -> None:
    for goal in (
        "a FingerprintAlgorithmAdapter",
        "registry integration",
        "the 6,000-comparison run",
        "a ResultSet",
        "a calibration",
        "a metric",
    ):
        assert goal in frozen.NON_GOALS


def test_the_repository_holds_no_vendor_bytes() -> None:
    audit = store.require_no_fingercell_bytes_in_git(REPOSITORY_ROOT)
    assert audit.clean
    assert audit.tracked_file_count > 0
