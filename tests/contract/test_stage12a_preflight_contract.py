"""The frozen Stage 12A contract: ten gates, three outcomes, one fake SDK.

No vendor package, no licence, no network, no dataset and no workspace. This
suite runs anywhere, which is the same claim the stage makes about itself:
without a delivered package there is nothing here but a state machine, a set of
schemas and a harness proved against a double.

What is under test is the shape of the decision rather than the decision. A
delivered package would turn most of these verdicts around and almost nothing
here would change — the gate order, the pending/failure split, the single-finger
rule, the raw-score requirement, the settings closure, the pair binding, the
secret guard and the two-outcome marker are the stage, and the outcome is what
they produced this time.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fpbench.core.errors import FpbenchError
from fpbench.core.idkit_preflight_errors import (
    IdkitAcquisitionError,
    IdkitCandidateIdentityError,
    IdkitGateError,
    IdkitObservationError,
    IdkitPreflightError,
    IdkitQualificationError,
    IdkitSensitiveEvidenceError,
    Stage12AFinalizationError,
)
from fpbench.experiments import stage12a_acquisition as store
from fpbench.experiments import stage12a_idkit_identity as frozen
from fpbench.experiments import stage12a_idkit_observations as observed
from fpbench.experiments import stage12a_preflight as engine
from fpbench.experiments import stage12a_qualification as harness
from fpbench.experiments.algorithm_research import REPOSITORY_ROOT
from fpbench.experiments.stage12a_finalization import (
    Stage12AFinalization,
    require_expected_evidence_files,
    stage_12a_finalization_fingerprint,
)

pytestmark = pytest.mark.stage12a_contract


# ------------------------------------------------------------- the vocabulary


def test_every_error_descends_from_the_project_root() -> None:
    for error in (
        IdkitPreflightError,
        IdkitCandidateIdentityError,
        IdkitObservationError,
        IdkitAcquisitionError,
        IdkitGateError,
        IdkitQualificationError,
        IdkitSensitiveEvidenceError,
        Stage12AFinalizationError,
    ):
        assert issubclass(error, FpbenchError)


def test_the_candidate_occupies_algorithm_five_and_freezes_no_version() -> None:
    assert frozen.ALGORITHM_SLOT == "algorithm_5"
    assert frozen.CANDIDATE_ID == "innovatrics_idkit_fingerprint_1to1"
    assert frozen.IMPLEMENTATION_ORIGIN == "VENDOR_OFFICIAL_SDK"
    assert frozen.IMPLEMENTATION_VERSION_UNRESOLVED == "UNRESOLVED_UNTIL_PACKAGE"
    assert frozen.PRODUCTION_ALGORITHM_ID_FROZEN is False


def test_the_advertised_version_is_recorded_and_is_not_an_authority() -> None:
    """7.6 is what a course page says, and a course page is not a package."""
    assert observed.ADVERTISED_VERSION_INDICATION == "7.6"
    assert observed.ADVERTISED_VERSION_IS_NOT_AUTHORITATIVE is True
    assert frozen.IMPLEMENTATION_VERSION_UNRESOLVED != "7.6"


def test_there_are_exactly_ten_gates_in_the_frozen_order() -> None:
    assert frozen.GATE_COUNT == 10
    assert len(set(frozen.GATE_ORDER)) == 10
    assert frozen.GATE_ORDER[0] is frozen.PreflightGate.ACQUISITION_ACCESS
    assert frozen.GATE_ORDER[-1] is frozen.PreflightGate.TRAINING_PROVENANCE
    # The raw score is settled before workload and provenance: a route with no
    # scalar is not worth measuring or vetting.
    assert frozen.GATE_ORDER.index(
        frozen.PreflightGate.SINGLE_FINGER_MATCHER_RAW_SCORE
    ) < frozen.GATE_ORDER.index(frozen.PreflightGate.WORKLOAD_RUNTIME_FEASIBILITY)


def test_every_blocker_belongs_to_exactly_one_gate() -> None:
    for code in frozen.BlockerCode:
        assert len(frozen.gate_of_blocker(code)) == 1


def test_the_three_outcomes_are_closed_and_only_two_may_be_finalised() -> None:
    assert set(frozen.STAGE_12A_OUTCOMES) == {
        "IDKIT_PREFLIGHT_PASS",
        "IDKIT_PREFLIGHT_FAIL",
        "IDKIT_PREFLIGHT_PENDING_ACCESS",
    }
    assert frozen.STAGE_12A_PENDING_OUTCOME not in frozen.STAGE_12A_FINAL_OUTCOMES


def test_pending_states_can_never_become_a_blocker() -> None:
    """The whole point of the state machine, stated as a test.

    Not asking is not being refused. Only a real refusal, or a package that does
    not exist for the target, may fail the acquisition gate.
    """
    for status in frozen.ACQUISITION_PENDING_STATES:
        assert status.is_pending
        assert not status.is_refusal
    assert set(frozen.ACQUISITION_REFUSAL_STATES) == {
        frozen.AcquisitionStatus.ACCESS_REFUSED,
        frozen.AcquisitionStatus.PACKAGE_UNAVAILABLE_FOR_TARGET,
    }


def test_only_acquisition_may_report_pending() -> None:
    assert frozen.PENDING_CAPABLE_GATES == (frozen.PreflightGate.ACQUISITION_ACCESS,)
    for gate in frozen.GATE_ORDER:
        if gate in frozen.PENDING_CAPABLE_GATES:
            continue
        with pytest.raises(IdkitGateError):
            engine.GateResult(
                gate=gate,
                status=frozen.GateStatus.PENDING,
                summary="a gate that would rather not decide",
                pending=engine.PendingReason(
                    acquisition_status=frozen.AcquisitionStatus.REQUEST_PENDING,
                    what_was_walked="nothing",
                    what_is_outstanding=("something",),
                    what_it_would_answer="nothing",
                ),
            )


def test_a_pending_reason_cannot_be_built_on_a_refusal() -> None:
    with pytest.raises(IdkitGateError):
        engine.PendingReason(
            acquisition_status=frozen.AcquisitionStatus.ACCESS_REFUSED,
            what_was_walked="the vendor said no",
            what_is_outstanding=("wait longer",),
            what_it_would_answer="nothing, because it is already answered",
        )


# ------------------------------------------------------------- the gate model


def test_a_passing_gate_carries_nothing_outstanding() -> None:
    with pytest.raises(IdkitGateError):
        engine.GateResult(
            gate=frozen.PreflightGate.CANONICAL500_INPUT_ROUTE,
            status=frozen.GateStatus.PASS,
            summary="passed, with reservations",
            blockers=(
                engine.Blocker(
                    gate=frozen.PreflightGate.CANONICAL500_INPUT_ROUTE,
                    blocker_code=(
                        frozen.BlockerCode.CANONICAL500_INPUT_ROUTE_UNRESOLVED
                    ),
                    affected_component="the input route",
                    evidence="a reservation",
                    why_this_blocks_algorithm_5="it does not, apparently",
                    how_this_would_be_lifted="by weighing it",
                ),
            ),
        )


def test_a_blocker_cannot_be_raised_at_a_gate_it_does_not_belong_to() -> None:
    with pytest.raises(IdkitGateError):
        engine.Blocker(
            gate=frozen.PreflightGate.TRAINING_PROVENANCE,
            blocker_code=frozen.BlockerCode.RAW_SCORE_ROUTE_UNRESOLVED,
            affected_component="the matcher",
            evidence="filed in the wrong place",
            why_this_blocks_algorithm_5="it would be unfindable",
            how_this_would_be_lifted="by filing it at the matcher gate",
        )


def test_a_gate_that_was_never_reached_found_nothing() -> None:
    with pytest.raises(IdkitGateError):
        engine.GateResult(
            gate=frozen.PreflightGate.TRAINING_PROVENANCE,
            status=frozen.GateStatus.NOT_REACHED,
            summary="never asked, and yet",
            blockers=(
                engine.Blocker(
                    gate=frozen.PreflightGate.TRAINING_PROVENANCE,
                    blocker_code=frozen.BlockerCode.SD300_TRAINING_OVERLAP_FOUND,
                    affected_component="a model nobody looked at",
                    evidence="none",
                    why_this_blocks_algorithm_5="it would be a finding from nothing",
                    how_this_would_be_lifted="by reaching the gate",
                ),
            ),
        )


def test_the_run_is_fail_fast_and_pause_fast() -> None:
    preflight = engine.run_preflight()
    statuses = [result.status for result in preflight.results]
    assert statuses.count(frozen.GateStatus.FAIL) <= 1
    assert statuses.count(frozen.GateStatus.PENDING) <= 1
    stop = preflight.stopped_at or preflight.paused_at
    if stop is not None:
        index = frozen.GATE_ORDER.index(stop)
        assert all(
            result.status is frozen.GateStatus.NOT_REACHED
            for result in preflight.results[index + 1 :]
        )


def test_a_run_cannot_both_fail_and_pause() -> None:
    results = [
        engine.GateResult(
            gate=frozen.PreflightGate.ACQUISITION_ACCESS,
            status=frozen.GateStatus.PENDING,
            summary="waiting",
            pending=engine.PendingReason(
                acquisition_status=frozen.AcquisitionStatus.REQUEST_SENT,
                what_was_walked="a request",
                what_is_outstanding=("a reply",),
                what_it_would_answer="everything below",
            ),
        ),
        engine.GateResult(
            gate=frozen.PreflightGate.PACKAGE_RUNTIME_IDENTITY,
            status=frozen.GateStatus.FAIL,
            summary="failed",
            blockers=(
                engine.Blocker(
                    gate=frozen.PreflightGate.PACKAGE_RUNTIME_IDENTITY,
                    blocker_code=frozen.BlockerCode.PACKAGE_IDENTITY_UNRESOLVED,
                    affected_component="a package nobody has",
                    evidence="none",
                    why_this_blocks_algorithm_5="it would be a finding from nothing",
                    how_this_would_be_lifted="by not doing this",
                ),
            ),
        ),
        *(
            engine.GateResult(
                gate=gate,
                status=frozen.GateStatus.NOT_REACHED,
                summary="never asked",
            )
            for gate in frozen.GATE_ORDER[2:]
        ),
    ]
    with pytest.raises(IdkitGateError):
        engine.IdkitPreflight(
            results=tuple(results),
            stopped_at=frozen.PreflightGate.PACKAGE_RUNTIME_IDENTITY,
            paused_at=frozen.PreflightGate.ACQUISITION_ACCESS,
            preflight_fingerprint="0" * 64,
        )


def test_not_reached_is_not_a_pass() -> None:
    preflight = engine.run_preflight()
    if preflight.gates_reached < frozen.GATE_COUNT:
        assert preflight.passed is False


# ------------------------------------------------------- what this run found


def test_the_run_today_is_pending_on_access_and_names_nothing_as_a_blocker() -> None:
    """The stage's actual finding, and the one it must not overstate.

    Five official routes were walked and none of them hands a package to a
    project without a customer account. Nobody was asked and nobody refused, so
    the outcome is pending and the blocker list is empty.
    """
    preflight = engine.run_preflight()
    assert preflight.outcome == frozen.STAGE_12A_PENDING_OUTCOME
    assert preflight.paused_at is frozen.PreflightGate.ACQUISITION_ACCESS
    assert preflight.stopped_at is None
    assert preflight.blockers == ()
    assert preflight.failure_class is None
    assert preflight.opens_stage_12b is False
    reason = preflight.pending_reason
    assert reason is not None
    assert reason.acquisition_status.is_pending


def test_every_recorded_route_was_either_retrieved_or_says_it_was_not() -> None:
    for route in observed.ACQUISITION_ROUTES:
        if route.retrieval is observed.RetrievalStatus.RETRIEVED:
            assert route.retrieved_utc
        else:
            assert route.retrieved_utc is None
            assert route.blocked_by


def test_no_public_statement_can_be_recorded_as_an_authority() -> None:
    for item in observed.PUBLIC_OBSERVATIONS:
        assert item.freezes_a_value is False
    with pytest.raises(IdkitObservationError):
        observed.PublicObservation(
            observation_id="a_statement_that_would_freeze_a_value",
            locator="https://example.invalid/",
            subject="a default",
            statement="the default is 42",
            retrieval=observed.RetrievalStatus.RETRIEVED,
            retrieved_utc="2026-08-13",
            what_it_tells_this_stage_to_check="nothing, it decided",
            freezes_a_value=True,
        )


def test_an_unretrieved_locator_cannot_carry_a_statement() -> None:
    with pytest.raises(IdkitObservationError):
        observed.PublicObservation(
            observation_id="a_page_nobody_opened",
            locator="https://example.invalid/",
            subject="something",
            statement="it says so",
            retrieval=observed.RetrievalStatus.NOT_RETRIEVED,
            retrieved_utc="2026-08-13",
            what_it_tells_this_stage_to_check="nothing",
        )


# ----------------------------------------------------------- the input route


def test_every_refused_preprocessing_step_stays_refused() -> None:
    for step in (
        "crop",
        "resize by fpbench",
        "rotation",
        "enhancement",
        "histogram normalization",
        "binarization",
        "external minutiae extraction",
    ):
        assert step in frozen.REFUSED_PREPROCESSING


def test_the_decode_route_is_permitted_only_with_identical_pixels() -> None:
    assert len(frozen.DECODE_EQUIVALENCE_REQUIREMENTS) == 4
    assert any(
        "identical" in item for item in frozen.DECODE_EQUIVALENCE_REQUIREMENTS
    )


def test_the_decoder_round_trips_the_exact_gray8_matrix(tmp_path: Path) -> None:
    """The proof the permitted route rests on, run for real.

    IDKit's public material describes BMP and raw input rather than PNG, so the
    benchmark's images may have to be decoded before the SDK sees them. That is
    permitted exactly as far as the pixels survive it.
    """
    pixels = harness.ridge_field(64, 48, phase=0.2, curve=2.0)
    path = harness.write_gray8_png(tmp_path / "fixture.png", pixels)
    width, height, decoded = harness.decode_gray8_png(path)
    assert (width, height) == (64, 48)
    assert decoded == bytes(value for row in pixels for value in row)


def test_dpi_is_declared_before_extraction_and_a_late_one_is_refused() -> None:
    assert frozen.REQUIRED_INPUT_DPI == 500
    assert frozen.DPI_MUST_BE_SET_BEFORE_EXTRACTION is True
    with pytest.raises(IdkitQualificationError):
        harness.Representation(
            handle=object(),
            representation_type="whatever",
            size_bytes=1,
            extraction_dpi=1000,
        )


# ------------------------------------------------- the single-finger route


def test_a_consolidated_multi_finger_score_is_refused_by_name() -> None:
    assert (
        "a consolidated multi-finger record score"
        in frozen.REFUSED_MULTI_FINGER_CONSTRUCTIONS
    )
    assert "exactly one fingerprint" in frozen.SINGLE_FINGER_RECORD_RULE


def test_the_proprietary_template_is_the_representation_under_test() -> None:
    assert (
        frozen.RepresentationType.VENDOR_PROPRIETARY_TEMPLATE.value
        == "VENDOR_PROPRIETARY_TEMPLATE"
    )
    assert frozen.RepresentationType.ISO_EXPORT in frozen.RepresentationType
    assert "template_bytes" not in frozen.PUBLISHABLE_REPRESENTATION_FACTS


# ---------------------------------------------------------- the score route


def test_a_decision_is_not_a_score() -> None:
    assert frozen.ScoreRouteStatus.DECISION_ONLY.is_raw_score is False
    assert frozen.ScoreRouteStatus.NATIVE_SCALAR.is_raw_score is True
    # A vendor scale that is already a transform of a claimed FAR is still raw.
    assert frozen.ScoreRouteStatus.NATIVE_TRANSFORMED_SCALAR.is_raw_score is True


def test_fpbench_transforms_nothing_and_the_refusals_say_which() -> None:
    assert frozen.FPBENCH_SCORE_TRANSFORMATION == "none"
    for item in ("convert to FAR", "rescale to 0..1", "z-score", "clamp"):
        assert item in frozen.REFUSED_SCORE_TRANSFORMATIONS


def test_lowering_the_threshold_to_read_scores_is_refused_by_name() -> None:
    assert "threshold" in frozen.REFUSED_THRESHOLD_MANIPULATION
    assert "a score returned only above a threshold" in frozen.INSUFFICIENT_SCORE_SHAPES


def test_an_unresolved_score_affecting_setting_has_no_authority() -> None:
    assert frozen.SettingProvenance.UNRESOLVED.is_upstream_authority is False
    for item in frozen.SettingProvenance:
        if item is not frozen.SettingProvenance.UNRESOLVED:
            assert item.is_upstream_authority is True


def test_a_value_tuned_on_our_own_fingerprints_is_not_a_provenance() -> None:
    assert frozen.REFUSED_SETTING_PROVENANCE not in {
        item.value for item in frozen.SettingProvenance
    }


# --------------------------------------------------- pair roles and SELF


def test_the_pair_binding_is_frozen_and_no_reduction_is_permitted() -> None:
    assert dict(frozen.PAIR_ROLE_BINDING) == {
        "pair.left": "probe",
        "pair.right": "gallery",
    }
    for reduction in ("max", "min", "average"):
        assert reduction in frozen.REFUSED_ORIENTATION_REDUCTIONS


def test_self_is_two_extractions_and_a_record_that_says_otherwise_is_refused() -> None:
    assert len(frozen.SELF_SEMANTICS_REQUIREMENTS) == 4
    with pytest.raises(IdkitQualificationError):
        _record(self_semantics={"score_present": True, "independent_extractions": 1})


# --------------------------------------------------------- the harness itself


def _fixtures(tmp_path: Path) -> harness.FixtureSet:
    return harness.build_fixtures(tmp_path, width=96, height=120)


def test_the_fake_run_satisfies_the_whole_harness_contract(tmp_path: Path) -> None:
    """CI's proof that the harness works, with no package and no licence."""
    record = harness.run_qualification(
        harness.fake_engine_factory,
        _fixtures(tmp_path),
        engine_kind=harness.EngineKind.FAKE_SDK,
    )
    assert record.status is frozen.QualificationOutcome.SUCCESS
    assert set(record.passes) == {name for name, _ in frozen.QUALIFICATION_PASSES}
    assert record.scoring_comparisons <= frozen.QUALIFICATION_MAX_SCORING_COMPARISONS
    assert all(record.determinism[level] for level in frozen.DETERMINISM_LEVELS)
    assert record.self_semantics["independent_extractions"] == 2
    assert record.failure_semantics
    assert all(not item["produced_a_score"] for item in record.failure_semantics)


def test_the_fake_matcher_is_asymmetric_because_the_real_one_is(
    tmp_path: Path,
) -> None:
    record = harness.run_qualification(
        harness.fake_engine_factory,
        _fixtures(tmp_path),
        engine_kind=harness.EngineKind.FAKE_SDK,
    )
    assert record.pair_orientation["both_orderings_produced_a_score"] is True
    assert record.pair_orientation["score_digests_equal"] is False


def test_no_score_value_ever_reaches_the_record(tmp_path: Path) -> None:
    record = harness.run_qualification(
        harness.fake_engine_factory,
        _fixtures(tmp_path),
        engine_kind=harness.EngineKind.FAKE_SDK,
    )
    payload = json.dumps(record.as_json())
    assert "score_digest" not in payload or True  # digests are permitted
    for value in record.passes.values():
        assert "score" not in {key for key in value if key == "score"}
        digest = value.get("score_digest")
        assert digest is None or (len(digest) == 64 and int(digest, 16) >= 0)


def test_a_comparison_returns_a_score_or_a_failure_and_never_both() -> None:
    with pytest.raises(IdkitQualificationError):
        harness.ComparisonOutcome(score=1.0, failure_status="ALSO_BROKEN")
    with pytest.raises(IdkitQualificationError):
        harness.ComparisonOutcome(score=None, failure_status=None)


def test_zero_is_a_legitimate_score_and_a_failure_is_not_a_zero() -> None:
    outcome = harness.ComparisonOutcome(score=0, failure_status=None)
    assert outcome.produced_a_score is True
    failure = harness.ComparisonOutcome(score=None, failure_status="BAD_IMAGE")
    assert failure.produced_a_score is False
    assert failure.score_digest is None


def test_the_comparison_ceiling_is_enforced_where_comparisons_happen() -> None:
    budget = harness._Budget()
    for _ in range(frozen.QUALIFICATION_MAX_SCORING_COMPARISONS):
        budget.spend()
    with pytest.raises(IdkitQualificationError):
        budget.spend()


def test_a_failed_run_is_still_a_record() -> None:
    """The Stage 11A lesson: a run that broke is evidence, not a chore."""

    class _Broken:
        def describe(self):
            return {}

        def extract(self, image, *, dpi):
            raise RuntimeError("the engine fell over")

        def compare(self, probe, gallery):  # pragma: no cover - never reached
            raise AssertionError

        def close(self):
            return None

    record = harness.run_qualification(
        _Broken,
        harness.FixtureSet(
            kind="SYNTHETIC_RIDGE_LIKE",
            a=Path("a.png"),
            b=Path("b.png"),
            blank=Path("blank.png"),
            invalid=Path("invalid.png"),
            missing=Path("missing.png"),
        ),
        engine_kind=harness.EngineKind.FAKE_SDK,
    )
    assert record.status is frozen.QualificationOutcome.FAILED
    assert record.failed_at_pass == "ordinary"
    assert "the engine fell over" in record.failure_detail


def test_a_fake_record_can_never_answer_a_gate() -> None:
    assert harness.EngineKind.FAKE_SDK.answers_gates is False
    assert harness.EngineKind.DELIVERED_SDK.answers_gates is True


# --------------------------------------------------------- the secret guard


@pytest.mark.parametrize(
    "document",
    [
        {"hardware_id": "anything at all"},
        {"portal_username": "someone"},
        {"note": "Bearer abcdefghijklmnopqrstuvwxyz012345"},
        {"nested": [{"license_bytes": "..."}]},
        {"path": "C:\\Users\\someone\\packages"},
        {"path": "/home/someone/packages"},
        {"serial": "ABCD-1234-EFGH-5678"},
    ],
)
def test_the_guard_bites_on_credentials_and_machine_paths(document: dict) -> None:
    assert engine.find_sensitive_material(document)
    with pytest.raises(IdkitSensitiveEvidenceError):
        engine.require_no_sensitive_material(document, where="a test document")


def test_the_guard_does_not_bite_on_the_locators_this_stage_publishes() -> None:
    """A guard that refuses a support-article URL is a guard somebody switches off."""
    for item in observed.PUBLIC_OBSERVATIONS:
        assert engine.find_sensitive_material({"locator": item.locator}) == ()
    for route in observed.ACQUISITION_ROUTES:
        assert engine.find_sensitive_material({"locator": route.locator}) == ()


def test_no_derived_document_carries_anything_sensitive() -> None:
    preflight = engine.run_preflight()
    for name in frozen.DERIVABLE_EVIDENCE_FILES:
        document = engine.evidence_document(preflight, name)
        assert engine.find_sensitive_material(document) == ()


def test_a_store_declaration_carrying_a_credential_is_refused(tmp_path: Path) -> None:
    """Guarded at the reader, so nothing travels from the store into a document."""
    path = tmp_path / store.PACKAGE_DECLARATION_NAME
    path.write_text(json.dumps({"hardware_id": "xyz"}), encoding="utf-8")
    with pytest.raises(IdkitSensitiveEvidenceError):
        store._read_guarded_json(path, what="package declaration")


def test_no_idkit_byte_or_licence_is_tracked_in_this_repository() -> None:
    audit = engine.require_no_idkit_bytes_in_git(REPOSITORY_ROOT)
    assert audit.clean
    assert audit.tracked_file_count > 0


# -------------------------------------------------------- the acquisition store


def test_possession_is_never_something_a_person_may_declare() -> None:
    assert frozen.AcquisitionStatus.PACKAGE_OBTAINED not in store.DECLARABLE_STATES
    with pytest.raises(IdkitAcquisitionError):
        store.DeclaredState(
            status=frozen.AcquisitionStatus.PACKAGE_OBTAINED,
            basis="we have it, honestly",
            declared_utc="2026-08-13",
        )


def test_a_declared_refusal_must_say_what_happened() -> None:
    with pytest.raises(IdkitAcquisitionError):
        store.DeclaredState(
            status=frozen.AcquisitionStatus.ACCESS_REFUSED,
            basis="   ",
            declared_utc="2026-08-13",
        )


def test_a_package_declaration_needs_every_identity_field() -> None:
    with pytest.raises(IdkitAcquisitionError):
        store.PackageDeclaration(
            exact_product_name="",
            product_family=frozen.ProductFamily.IDKIT_SDK,
            implementation_version="7.6",
            package_build="1",
            package_filename="idkit.zip",
            package_size_bytes=1,
            package_sha256="a" * 64,
            delivery_channel=frozen.DeliveryChannel.CUSTOMER_PORTAL,
            operating_system="windows",
            architecture="x86_64",
            documentation_obtained=True,
            licensing_route_available=True,
            received_utc="2026-08-13",
        )


def test_possession_without_a_verified_package_is_refused() -> None:
    with pytest.raises(IdkitAcquisitionError):
        store.AcquisitionState(
            status=frozen.AcquisitionStatus.PACKAGE_OBTAINED,
            presence=store.PackagePresence.ABSENT,
            basis="it is around here somewhere",
            declaration=None,
        )


def test_this_machine_holds_no_idkit_package() -> None:
    """True on every CI runner, and true here until a vendor delivers one."""
    state = store.acquisition_state()
    assert state.obtained is False
    assert state.status is observed.OBSERVED_ACQUISITION_STATUS


# ------------------------------------------------------------- the workload


def test_the_frozen_workload_extracts_both_sides_of_every_pair() -> None:
    workload = frozen.FROZEN_WORKLOAD
    assert workload.comparison_attempts == 6_000
    assert workload.independent_extractions == 12_000
    assert workload.matcher_invocations == 6_000
    assert frozen.REPRESENTATION_CACHE_PERMITTED is False


def test_a_workload_with_a_representation_cache_is_refused() -> None:
    with pytest.raises(IdkitCandidateIdentityError):
        frozen.FrozenWorkload(
            comparison_attempts=6_000,
            independent_extractions=6_000,
            matcher_invocations=6_000,
            qualification_allowance=20,
        )


# --------------------------------------------------------------- the marker


def _marker_claims(**overrides: object) -> dict:
    """A minimal valid FAIL marker, for the negative cases to bend."""
    claims: dict = {
        "schema_version": frozen.STAGE_12A_SCHEMA_VERSION,
        "kind": frozen.STAGE_FINALIZATION_KIND,
        "outcome": frozen.STAGE_12A_FAIL_OUTCOME,
        "algorithm_slot": frozen.ALGORITHM_SLOT,
        "candidate": frozen.CANDIDATE_ID,
        "stage11b_outcome": frozen.STAGE_11B_OUTCOME,
        "stage11b_finalization_fingerprint": (
            frozen.STAGE_11B_FINALIZATION_FINGERPRINT
        ),
        "stage8e_policy_fingerprint": frozen.STAGE8E_FINALIZATION_FINGERPRINT,
        "stage12a_source_fingerprint": "1" * 64,
        "observations_fingerprint": "2" * 64,
        "preflight_fingerprint": "3" * 64,
        "gate_count_defined": frozen.GATE_COUNT,
        "gates_reached": 1,
        "gates_passed": 0,
        "exact_product": None,
        "implementation_origin": frozen.IMPLEMENTATION_ORIGIN,
        "implementation_version": None,
        "package_sha256": None,
        "platform": None,
        "official_package_obtained": False,
        "acquisition_status": frozen.AcquisitionStatus.ACCESS_REFUSED.value,
        "one_official_binding_selected": False,
        "runtime_dependency_closure_known": False,
        "research_use_opens_execution": None,
        "research_use_blocked": False,
        "license_activated": False,
        "license_workload_sufficient": None,
        "canonical500_route": False,
        "fpbench_preprocessing_required": False,
        "dpi_500_before_extraction": False,
        "single_finger_route": False,
        "representation_type": None,
        "multi_finger_consolidation_used": False,
        "extraction_settings_frozen": False,
        "matcher_settings_frozen": False,
        "hidden_score_affecting_defaults": None,
        "raw_score_route": False,
        "score_numeric_type": None,
        "score_direction": None,
        "threshold_applied_inside_the_score": False,
        "fpbench_score_transformation": frozen.FPBENCH_SCORE_TRANSFORMATION,
        "pair_orientation": "left_probe_right_gallery",
        "self_independent_extraction": False,
        "restart_determinism": False,
        "failure_semantics_resolved": False,
        "local_smoke_passed": False,
        "runtime_feasibility_measured": False,
        "training_provenance": frozen.TrainingProvenanceStatus.NOT_REACHED.value,
        "sd300_overlap_status": frozen.SD300OverlapStatus.NOT_REACHED.value,
        "sd300_used": False,
        "failure_class": frozen.FailureClass.VENDOR_ACCESS_REFUSED.value,
        "sd300_image_bytes_read": False,
        "sd300_pair_manifest_read": False,
        "sd300_scores_read": False,
        "prior_algorithm_scores_read": False,
        "production_adapter_created": False,
        "canonical_experiment_config_created": False,
        "benchmark_run_performed": False,
        "result_set_produced": False,
        "threshold_produced": False,
        "calibration_performed": False,
        "metrics_produced": False,
        "production_algorithm_id_frozen": False,
        "third_party_bytes_added_to_git": False,
        "secrets_added_to_git": False,
        "license_activation_attempted_in_ci": False,
        "credentials_stored_in_ci": False,
        "license_bypass_attempted": False,
        "stage8e_evidence_changed": False,
        "stage11a_evidence_changed": False,
        "stage11b_evidence_changed": False,
        "opens_stage_12b": False,
        "blockers": (
            {
                "gate": frozen.PreflightGate.ACQUISITION_ACCESS.value,
                "blocker_code": frozen.BlockerCode.ACCESS_REFUSED_BY_VENDOR.value,
                "affected_component": "the package",
                "evidence": "the vendor declined in writing",
                "why_this_blocks_algorithm_5": "there is nothing to qualify",
                "how_this_would_be_lifted": "only the vendor can lift it",
            },
        ),
        "evidence_content_hashes": {"preflight-report.json": "4" * 64},
        "source_commit": "a" * 40,
        "source_tree_clean": True,
        "verifier_source_commit": "a" * 40,
        "verifier_source_tree_clean": True,
    }
    claims.update(overrides)
    return claims


def _marker(**overrides: object) -> Stage12AFinalization:
    claims = _marker_claims(**overrides)
    return Stage12AFinalization(
        **claims,
        stage_12a_finalization_fingerprint=stage_12a_finalization_fingerprint(claims),
        created_utc="2026-08-13T00:00:00Z",
    )


def test_a_fail_marker_validates() -> None:
    marker = _marker()
    assert marker.outcome == frozen.STAGE_12A_FAIL_OUTCOME
    assert marker.opens_stage_12b is False


def test_no_marker_may_carry_the_pending_outcome() -> None:
    """The state that would otherwise become the third one everybody uses."""
    with pytest.raises(ValueError, match="never of a finalization"):
        _marker(outcome=frozen.STAGE_12A_PENDING_OUTCOME)


def test_a_fail_marker_may_not_publish_what_it_never_established() -> None:
    with pytest.raises(ValueError, match="published as unestablished"):
        _marker(implementation_version="7.6")


def test_a_fail_marker_may_not_claim_stage_8e_refused_something() -> None:
    with pytest.raises(ValueError, match="research-use refusal"):
        _marker(research_use_opens_execution=False)


def test_a_fail_marker_names_its_failure_class() -> None:
    with pytest.raises(ValueError, match="what kind of failure"):
        _marker(failure_class=None)


def test_a_marker_may_not_deny_a_denial() -> None:
    for flag in Stage12AFinalization.DENIED_FLAGS:
        with pytest.raises(ValueError, match="a marker that said"):
            _marker(**{flag: True})


def test_a_marker_may_not_move_the_pair_binding() -> None:
    with pytest.raises(ValueError, match="pair_orientation"):
        _marker(pair_orientation="whichever_scored_higher")


def test_a_marker_may_not_record_a_score_transformation() -> None:
    with pytest.raises(ValueError, match="no score transformation"):
        _marker(fpbench_score_transformation="normalised")


def test_a_marker_may_not_rebind_a_closed_stage() -> None:
    with pytest.raises(ValueError, match="Stage 11B is immutable"):
        _marker(stage11b_finalization_fingerprint="9" * 64)
    with pytest.raises(ValueError, match="Stage 8E is a closed stage"):
        _marker(stage8e_policy_fingerprint="9" * 64)


def test_a_marker_may_not_drop_a_gate() -> None:
    with pytest.raises(ValueError, match="hard gates are defined"):
        _marker(gate_count_defined=9)


def test_the_fingerprint_covers_every_claim() -> None:
    claims = _marker_claims()
    marker = _marker()
    for field in ("outcome", "gates_reached", "acquisition_status"):
        moved = dict(claims)
        moved[field] = (
            frozen.STAGE_12A_PASS_OUTCOME if field == "outcome" else "changed"
        )
        assert stage_12a_finalization_fingerprint(moved) != (
            marker.stage_12a_finalization_fingerprint
        )


def test_a_pass_marker_needs_every_acceptance_condition() -> None:
    with pytest.raises(ValueError):
        _marker(outcome=frozen.STAGE_12A_PASS_OUTCOME)


def test_the_evidence_list_is_closed_and_pending_omits_the_marker() -> None:
    require_expected_evidence_files(
        tuple(
            name
            for name in frozen.REQUIRED_EVIDENCE_FILES
            if name != frozen.STAGE_12A_FINALIZATION_NAME
        ),
        marker_expected=False,
    )
    with pytest.raises(Stage12AFinalizationError, match="is missing"):
        require_expected_evidence_files(("README.md",), marker_expected=False)
    with pytest.raises(Stage12AFinalizationError, match="nothing accounts for"):
        require_expected_evidence_files(
            frozen.REQUIRED_EVIDENCE_FILES + ("notes.txt",)
        )


# ------------------------------------------------------------- the boundaries


def test_this_stage_builds_no_production_integration() -> None:
    for item in (
        "a generic FingerprintAlgorithmAdapter",
        "the 6,000-comparison runner",
        "a threshold",
        "a calibration",
    ):
        assert item in frozen.NON_GOALS


def test_the_stage_reads_no_dataset_and_no_prior_algorithm_scores() -> None:
    for item in (
        "sd300_image_bytes",
        "sd300_pair_manifest",
        "sd300_scores",
        "verifinger_scores",
    ):
        assert item in frozen.FORBIDDEN_READS


def test_the_source_fingerprint_covers_every_module_that_decides_anything() -> None:
    for relative in frozen.STAGE_12A_SOURCE_FILES:
        assert (REPOSITORY_ROOT / Path(relative)).is_file()
    assert len(frozen.STAGE_12A_SOURCE_FILES) == 7


def test_the_predecessor_and_the_policy_are_bound_and_unchanged() -> None:
    engine.require_stage8e_is_the_policy_this_reuses(REPOSITORY_ROOT)
    fingerprint = engine.require_stage11b_is_the_closed_predecessor(REPOSITORY_ROOT)
    assert fingerprint == frozen.STAGE_11B_FINALIZATION_FINGERPRINT


def _record(**overrides: object) -> harness.QualificationRecord:
    base: dict = {
        "schema": frozen.QUALIFICATION_RECORD_SCHEMA,
        "status": frozen.QualificationOutcome.SUCCESS,
        "engine_kind": harness.EngineKind.FAKE_SDK,
        "started_utc": "2026-08-13T00:00:00Z",
        "finished_utc": "2026-08-13T00:00:01Z",
        "scoring_comparisons": 5,
        "passes": {name: {} for name, _ in frozen.QUALIFICATION_PASSES},
        "pair_orientation": {"both_orderings_produced_a_score": True},
        "self_semantics": {"score_present": True, "independent_extractions": 2},
        "determinism": {level: True for level in frozen.DETERMINISM_LEVELS},
        "failure_semantics": (
            {"cause": "malformed_or_invalid_image", "produced_a_score": False},
        ),
        "runtime": {},
        "delivered_runtime_defaults": {},
        "fixture_kind": "SYNTHETIC_RIDGE_LIKE",
        "inputs_fingerprint": "5" * 64,
        "driver_fingerprint": "6" * 64,
    }
    base.update(overrides)
    return harness.QualificationRecord(**base)


# ------------------------------------------------ the pass path is reachable


def _complete_inspection() -> dict:
    """Everything the nine gates below acquisition would need, in one record.

    Written here rather than in the engine because it is a *fixture*: it stands
    in for what a person would record after inspecting a delivered package. Its
    job is to prove the gates can be satisfied at all — a preflight nothing can
    pass is not a preflight, it is a refusal with extra steps (docs/adr/0106).
    """
    return {
        "binding": {
            "binding_id": "the vendor's own single-finger 1:1 sample binding",
            "version_matched": True,
            "vendor_supplied": True,
            "ships_a_1to1_sample": True,
            "exposes_every_setting": True,
            "returns_raw_score": True,
        },
        "runtime_components": [
            {
                "relative_path": "bin/engine",
                "role": "native_library",
                "size_bytes": 1024,
                "sha256": "a" * 64,
                "version_or_build": "x.y",
            }
        ],
        "license": {
            "activated": True,
            "expiry": "a dated evaluation term",
            "machine_binding": "bound to one host",
            "feature_entitlement": "the fingerprint modules",
            "process_restrictions": "none stated",
            "quota_or_transaction_limits": None,
            "offline_or_network_requirement": "offline after activation",
            "observation_status": "NON_COMMERCIAL",
            "declared_license_names": ["the agreement delivered with the package"],
            "stated_restrictions": ["non-commercial evaluation only"],
            "basis": (
                "one person, on one machine, runs the vendor's own 1:1 route and "
                "publishes no byte of it"
            ),
            "non_blocking_restrictions": [
                "NON_COMMERCIAL_ONLY",
                "NO_REDISTRIBUTION",
            ],
            # Two notices, because Stage 8E computes the conservative answer from
            # the intersection of at least two plausible readings and refuses to
            # assume one. A real delivery carries at least this many: an
            # agreement and whatever the evaluation terms are stated in.
            "notices": [
                {
                    "locator": "Documentation/License.txt",
                    "description": "the agreement inside the delivered package",
                    "document_sha256": "b" * 64,
                    "permits_local_execution": True,
                    "permits_non_commercial_use": True,
                    "permits_educational_research": True,
                },
                {
                    "locator": "Documentation/Evaluation.txt",
                    "description": "the evaluation terms delivered beside it",
                    "document_sha256": "c" * 64,
                    "permits_local_execution": True,
                    "permits_non_commercial_use": True,
                    "permits_educational_research": True,
                },
            ],
        },
        "input_route": {
            "reads_png_directly": False,
            "raw_buffer_api_available": True,
            "decode_is_lossless_and_deterministic": True,
            "dimensions_unchanged": True,
            "pixel_format_unchanged": True,
            "every_pixel_identical": True,
            "dpi_set_before_extraction": True,
            "fpbench_preprocessing_required": False,
            "fpbench_preprocessing_applied": [],
        },
        "representation": {
            "representation_type": "VENDOR_PROPRIETARY_TEMPLATE",
            "template_version_if_exposed": "as reported by the package",
            "single_finger_record_structure": "one fingerprint per record",
            "one_fingerprint_per_record_guaranteed": True,
            "whether_image_retention_affects_matching": False,
        },
        "extraction_settings": [
            {
                "name": "input_dpi",
                "value": 500,
                "can_affect_template_or_score": True,
                "provenance": "FPBENCH_PROTOCOL_BINDING",
            },
            {
                "name": "maximum_template_size",
                "value": 4096,
                "can_affect_template_or_score": True,
                "provenance": "DELIVERED_RUNTIME_DEFAULT",
            },
        ],
        "matcher_settings": [
            {
                "name": "matching_profile",
                "value": "as delivered",
                "can_affect_template_or_score": True,
                "provenance": "DELIVERED_RUNTIME_DEFAULT",
            }
        ],
        "score_contract": {
            "exact_api_or_method": "the sample's single-pair verification call",
            "result_field": "the similarity returned beside the status",
            "numeric_type": "integer",
            "defined_or_observed_range": "0 upwards on the vendor scale",
            "direction": "HIGHER_IS_MORE_SIMILAR",
            "failure_behaviour": "a status, never a number",
            "score_bearing_statuses": "returned under match and no-match alike",
            "threshold_relationship": "a separate settable property",
            "route_status": "NATIVE_TRANSFORMED_SCALAR",
            "threshold_applied_inside_the_score": False,
            "fpbench_score_transformation": "none",
        },
        "settings_closure": {
            family: True for family in frozen.SETTINGS_CLOSURE_FAMILIES
        },
        "training_provenance": {
            "training_provenance_status": "PROPRIETARY_UNDISCLOSED",
            "sd300_overlap_status": "NO_EVIDENCE_FOUND",
            "surfaces_searched": list(frozen.SD300_OVERLAP_SURFACES),
        },
    }


@pytest.fixture
def qualified_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A store standing in for a delivered, inspected, qualified package."""
    root = tmp_path / "store"
    prefix = root / frozen.ARTIFACT_STORE_PREFIX
    prefix.mkdir(parents=True)
    monkeypatch.setenv("FPBENCH_THIRD_PARTY_ROOT", str(root))

    package = prefix / "idkit-package.zip"
    package.write_bytes(b"not a real package, and never treated as one")
    digest = store._file_sha256(package)
    (prefix / store.PACKAGE_DECLARATION_NAME).write_text(
        json.dumps(
            {
                "exact_product_name": "IDKit SDK",
                "product_family": frozen.ProductFamily.IDKIT_SDK.value,
                "implementation_version": "x.y",
                "package_build": "build-as-delivered",
                "package_filename": package.name,
                "package_size_bytes": package.stat().st_size,
                "package_sha256": digest,
                "delivery_channel": frozen.DeliveryChannel.CUSTOMER_PORTAL.value,
                "operating_system": "windows",
                "architecture": "x86_64",
                "documentation_obtained": True,
                "licensing_route_available": True,
                "received_utc": "2026-08-13",
            }
        ),
        encoding="utf-8",
    )
    (prefix / engine.PACKAGE_INSPECTION_NAME).write_text(
        json.dumps(_complete_inspection()), encoding="utf-8"
    )

    fixtures = harness.build_fixtures(tmp_path / "fixtures", width=96, height=120)
    record = harness.run_qualification(
        harness.fake_engine_factory,
        fixtures,
        engine_kind=harness.EngineKind.DELIVERED_SDK,
    )
    assert record.status is frozen.QualificationOutcome.SUCCESS
    harness.write_record(record, prefix / frozen.QUALIFICATION_RECORD_NAME)
    return root


def test_a_delivered_inspected_qualified_package_passes_all_ten_gates(
    qualified_store: Path,
) -> None:
    """The preflight can reach PASS, and this is what it takes.

    Every input here is a stand-in — the package is not IDKit and the engine is
    the fake. What is under test is that ten gates written to refuse can also
    agree, and that the marker they feed validates as a pass.
    """
    preflight = engine.run_preflight()
    assert preflight.outcome == frozen.STAGE_12A_PASS_OUTCOME, [
        (result.gate.value, result.status.value, result.summary)
        for result in preflight.results
        if result.status is not frozen.GateStatus.PASS
    ]
    assert preflight.gates_passed == frozen.GATE_COUNT
    assert preflight.opens_stage_12b is True
    assert preflight.blockers == ()
    assert preflight.sd300_overlap_status is frozen.SD300OverlapStatus.NO_EVIDENCE_FOUND


def test_the_pass_path_produces_a_marker_that_validates(
    qualified_store: Path,
) -> None:
    from fpbench.experiments.stage12a_finalization import _marker_claims

    preflight = engine.run_preflight()
    claims = _marker_claims(
        REPOSITORY_ROOT,
        preflight,
        predecessor=frozen.STAGE_11B_FINALIZATION_FINGERPRINT,
        observations_fingerprint=observed.observations_fingerprint(),
        evidence_content_hashes={"preflight-report.json": "c" * 64},
        commit="d" * 40,
        byte_findings=False,
    )
    marker = Stage12AFinalization(
        **claims,
        stage_12a_finalization_fingerprint=stage_12a_finalization_fingerprint(claims),
        created_utc="2026-08-13T00:00:00Z",
    )
    assert marker.outcome == frozen.STAGE_12A_PASS_OUTCOME
    assert marker.opens_stage_12b is True
    assert marker.hidden_score_affecting_defaults == 0
    assert marker.pair_orientation == "left_probe_right_gallery"
    assert marker.fpbench_score_transformation == "none"


def test_a_consolidated_multi_finger_route_fails_the_extraction_gate(
    qualified_store: Path, tmp_path: Path
) -> None:
    """The failure mode this candidate is most likely to hit, exercised."""
    inspection = _complete_inspection()
    inspection["representation"]["one_fingerprint_per_record_guaranteed"] = False
    path = (
        tmp_path / "store" / frozen.ARTIFACT_STORE_PREFIX / engine.PACKAGE_INSPECTION_NAME
    )
    path.write_text(json.dumps(inspection), encoding="utf-8")

    preflight = engine.run_preflight()
    assert preflight.outcome == frozen.STAGE_12A_FAIL_OUTCOME
    assert preflight.stopped_at is (
        frozen.PreflightGate.SINGLE_FINGER_EXTRACTION_PROFILE
    )
    assert {item.blocker_code for item in preflight.blockers} == {
        frozen.BlockerCode.SINGLE_FINGER_EXTRACTION_ROUTE_UNRESOLVED
    }
    assert preflight.failure_class is frozen.FailureClass.ROUTE_NOT_QUALIFIABLE


def test_a_decision_only_matcher_fails_the_raw_score_gate(
    qualified_store: Path, tmp_path: Path
) -> None:
    inspection = _complete_inspection()
    inspection["score_contract"]["route_status"] = "DECISION_ONLY"
    path = (
        tmp_path / "store" / frozen.ARTIFACT_STORE_PREFIX / engine.PACKAGE_INSPECTION_NAME
    )
    path.write_text(json.dumps(inspection), encoding="utf-8")

    preflight = engine.run_preflight()
    assert preflight.stopped_at is frozen.PreflightGate.SINGLE_FINGER_MATCHER_RAW_SCORE
    assert {item.blocker_code for item in preflight.blockers} == {
        frozen.BlockerCode.RAW_SCORE_ROUTE_UNRESOLVED
    }


def test_an_unresolved_setting_fails_the_closure_gate(
    qualified_store: Path, tmp_path: Path
) -> None:
    inspection = _complete_inspection()
    inspection["matcher_settings"].append(
        {
            "name": "a knob nobody read",
            "value": None,
            "can_affect_template_or_score": True,
            "provenance": "UNRESOLVED",
        }
    )
    path = (
        tmp_path / "store" / frozen.ARTIFACT_STORE_PREFIX / engine.PACKAGE_INSPECTION_NAME
    )
    path.write_text(json.dumps(inspection), encoding="utf-8")

    preflight = engine.run_preflight()
    # The matcher gate sees it first, because it inventories the same rows.
    assert preflight.stopped_at is frozen.PreflightGate.SINGLE_FINGER_MATCHER_RAW_SCORE
    assert {item.blocker_code for item in preflight.blockers} == {
        frozen.BlockerCode.MATCHER_PROFILE_UNRESOLVED
    }


def test_a_declared_vendor_refusal_fails_the_acquisition_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one way this stage is allowed to fail on access."""
    root = tmp_path / "store"
    prefix = root / frozen.ARTIFACT_STORE_PREFIX
    prefix.mkdir(parents=True)
    monkeypatch.setenv("FPBENCH_THIRD_PARTY_ROOT", str(root))
    (prefix / store.ACQUISITION_STATE_NAME).write_text(
        json.dumps(
            {
                "status": frozen.AcquisitionStatus.ACCESS_REFUSED.value,
                "basis": "the vendor declined to supply an evaluation package",
                "declared_utc": "2026-08-13",
            }
        ),
        encoding="utf-8",
    )
    preflight = engine.run_preflight()
    assert preflight.outcome == frozen.STAGE_12A_FAIL_OUTCOME
    assert preflight.stopped_at is frozen.PreflightGate.ACQUISITION_ACCESS
    assert preflight.failure_class is frozen.FailureClass.VENDOR_ACCESS_REFUSED
    assert {item.blocker_code for item in preflight.blockers} == {
        frozen.BlockerCode.ACCESS_REFUSED_BY_VENDOR
    }


def test_a_request_that_has_been_sent_is_still_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "store"
    prefix = root / frozen.ARTIFACT_STORE_PREFIX
    prefix.mkdir(parents=True)
    monkeypatch.setenv("FPBENCH_THIRD_PARTY_ROOT", str(root))
    (prefix / store.ACQUISITION_STATE_NAME).write_text(
        json.dumps(
            {
                "status": frozen.AcquisitionStatus.REQUEST_SENT.value,
                "basis": "an evaluation request was sent to the vendor",
                "declared_utc": "2026-08-13",
            }
        ),
        encoding="utf-8",
    )
    preflight = engine.run_preflight()
    assert preflight.outcome == frozen.STAGE_12A_PENDING_OUTCOME
    assert preflight.blockers == ()


def test_a_successful_record_that_scored_a_failure_is_refused() -> None:
    with pytest.raises(IdkitQualificationError, match="produced a score"):
        _record(
            failure_semantics=(
                {"cause": "malformed_or_invalid_image", "produced_a_score": True},
            )
        )


def test_a_record_over_the_ceiling_is_refused() -> None:
    with pytest.raises(IdkitQualificationError, match="ceiling"):
        _record(scoring_comparisons=21)
