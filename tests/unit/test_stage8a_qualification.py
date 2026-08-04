from __future__ import annotations

import pytest

from fpbench.core.errors import QualificationError
from fpbench.core.modern_matcher_models import (
    DecisionPathKind,
    LicenseConclusion,
    LicenseScope,
    ComponentKind,
    QualificationGate,
    QualificationStatus,
)
from fpbench.modern_matchers.qualification import (
    NEGATIVE_FAILURE_CODES,
    QualificationFacts,
    derive_gate_results,
)
from stage8aworld import (
    digest,
    make_candidate,
    make_component,
    make_decision_path,
    make_determinism,
    make_facts,
    make_license,
    make_manifest,
    make_operational,
    make_preprocessing,
    make_registry,
    make_report,
    make_representation,
    make_score,
    make_raw_only_report,
    rebuild,
)

pytestmark = pytest.mark.stage8a_contract


def _parts():
    candidate = make_candidate()
    registry = make_registry((candidate,))
    return {
        "candidate": candidate,
        "registry": registry,
        "manifest": make_manifest(candidate, registry),
        "facts": make_facts(),
        "preprocessing": make_preprocessing(),
        "representation": make_representation(),
        "score": make_score(),
        "determinism": make_determinism(),
        "operational": make_operational(),
        "decision_path": make_decision_path(),
    }


def _failures(parts) -> set[str]:
    gates = derive_gate_results(
        candidate=parts["candidate"],
        manifest=parts["manifest"],
        facts=parts["facts"],
        preprocessing=parts["preprocessing"],
        representation=parts["representation"],
        score=parts["score"],
        determinism=parts["determinism"],
        operational=parts["operational"],
        decision_path=parts["decision_path"],
    )
    return {
        code
        for result in gates
        if not result.passed
        for code in result.failures
    }


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("paper_only", "PAPER_WITHOUT_INFERENCE_CODE"),
        ("code_without_weights", "INFERENCE_CODE_WITHOUT_WEIGHTS"),
        ("architecture_unknown", "WEIGHTS_ARCHITECTURE_UNIDENTIFIABLE"),
        ("checkpoint_without_license", "CHECKPOINT_LICENSE_MISSING"),
        ("code_license_only", "WEIGHTS_LICENSE_NOT_ESTABLISHED"),
        ("missing_preprocessing", "PREPROCESSING_INCOMPLETE"),
        ("dataset_preprocessing", "PREPROCESSING_DATASET_DEPENDENT"),
        ("missing_matcher", "COMPARATOR_MISSING"),
        ("boolean_only_matcher", "RAW_SCORE_NOT_EXPOSED"),
        ("online_download", "ONLINE_RUNTIME_DEPENDENCY"),
        ("hidden_threshold", "HIDDEN_THRESHOLD"),
        ("excessive_drift", "NONDETERMINISM_EXCEEDS_TOLERANCE"),
        ("external_minutiae", "EXTERNAL_MINUTIAE_OUTSIDE_IDENTITY"),
        ("evaluation_reweighting", "EVALUATION_COHORT_REWEIGHTING"),
    ],
)
def test_every_mandated_negative_case_has_an_exact_failure_code(case, expected):
    parts = _parts()
    facts = parts["facts"]

    if case == "paper_only":
        facts = rebuild(facts, paper_only=True, inference_code_present=False)
    elif case == "code_without_weights":
        facts = rebuild(facts, weights_present=False)
    elif case == "architecture_unknown":
        facts = rebuild(facts, weights_architecture_identifiable=False)
    elif case == "checkpoint_without_license":
        source = make_license(LicenseScope.SOURCE_CODE)
        components = (
            make_component(
                "source_bundle",
                kind=ComponentKind.SOURCE_CODE,
                role="source_code",
                license_fingerprint=source.fingerprint,
                payload=b"source-bundle",
            ),
            make_component(
                "model_checkpoint",
                kind=ComponentKind.CHECKPOINT,
                role="checkpoint",
                license_fingerprint=None,
                payload=b"model-checkpoint",
            ),
        )
        parts["manifest"] = make_manifest(
            parts["candidate"],
            parts["registry"],
            license_records=(source,),
            components=components,
        )
    elif case == "code_license_only":
        parts["manifest"] = make_manifest(
            parts["candidate"],
            parts["registry"],
            license_records=(
                make_license(LicenseScope.SOURCE_CODE),
                make_license(
                    LicenseScope.WEIGHTS,
                    conclusion=LicenseConclusion.UNCLEAR,
                ),
            ),
        )
    elif case == "missing_preprocessing":
        facts = rebuild(facts, preprocessing_complete=False)
        parts["preprocessing"] = None
    elif case == "dataset_preprocessing":
        facts = rebuild(facts, preprocessing_dataset_independent=False)
        parts["preprocessing"] = make_preprocessing(dataset_independent=False)
    elif case == "missing_matcher":
        facts = rebuild(facts, comparator_present=False)
    elif case == "boolean_only_matcher":
        facts = rebuild(facts, raw_score_exposed=False)
    elif case == "online_download":
        facts = rebuild(facts, online_runtime_dependency=True)
    elif case == "hidden_threshold":
        facts = rebuild(facts, hidden_threshold=True)
        parts["score"] = make_score(hidden_threshold=True)
    elif case == "excessive_drift":
        facts = rebuild(facts, determinism_within_tolerance=False)
    elif case == "external_minutiae":
        facts = rebuild(facts, external_minutiae_in_candidate_identity=False)
    elif case == "evaluation_reweighting":
        facts = rebuild(facts, reweighting_uses_evaluation_cohort=True)
    else:  # pragma: no cover - the parameter list is exhaustive
        raise AssertionError(case)

    parts["facts"] = facts
    assert expected in _failures(parts)


def test_the_negative_catalogue_is_exercised_in_full() -> None:
    expected = {
        "PAPER_WITHOUT_INFERENCE_CODE",
        "INFERENCE_CODE_WITHOUT_WEIGHTS",
        "WEIGHTS_ARCHITECTURE_UNIDENTIFIABLE",
        "CHECKPOINT_LICENSE_MISSING",
        "WEIGHTS_LICENSE_NOT_ESTABLISHED",
        "PREPROCESSING_INCOMPLETE",
        "PREPROCESSING_DATASET_DEPENDENT",
        "COMPARATOR_MISSING",
        "RAW_SCORE_NOT_EXPOSED",
        "ONLINE_RUNTIME_DEPENDENCY",
        "HIDDEN_THRESHOLD",
        "NONDETERMINISM_EXCEEDS_TOLERANCE",
        "EXTERNAL_MINUTIAE_OUTSIDE_IDENTITY",
        "EVALUATION_COHORT_REWEIGHTING",
    }
    assert NEGATIVE_FAILURE_CODES == expected


def test_static_inspection_failure_prevents_any_execution() -> None:
    candidate = make_candidate()
    registry = make_registry((candidate,))
    facts = make_facts(
        paper_only=True,
        inference_code_present=False,
        execution_attempted=True,
    )

    with pytest.raises(QualificationError, match="execution is forbidden"):
        make_report(candidate, registry, facts=facts)


def test_raw_score_readiness_does_not_imply_decision_path_readiness() -> None:
    candidate = make_candidate()
    registry = make_registry((candidate,))
    report = make_raw_only_report(candidate, registry)

    assert report.raw_score_ready
    assert not report.decision_path_ready
    assert report.qualification_status is QualificationStatus.RAW_SCORE_READY
    assert report.exact_gate_failures == ("DECISION_PATH_NOT_ESTABLISHED",)


def test_a_complete_report_passes_every_gate() -> None:
    candidate = make_candidate()
    registry = make_registry((candidate,))
    report = make_report(candidate, registry)

    assert all(result.passed for result in report.gate_results)
    assert report.raw_score_ready and report.decision_path_ready
    assert report.qualification_status is QualificationStatus.DECISION_PATH_READY


def test_offline_and_process_restart_require_explicit_isolation_evidence() -> None:
    parts = _parts()
    parts["facts"] = rebuild(
        parts["facts"],
        offline_execution_proven=False,
        process_restart_isolated=False,
    )

    assert {
        "OFFLINE_EXECUTION_NOT_PROVEN",
        "PROCESS_RESTART_NOT_ISOLATED",
    } <= _failures(parts)


def test_unexecuted_runtime_reports_only_unknown_runtime_conclusions() -> None:
    parts = _parts()
    parts["facts"] = rebuild(
        parts["facts"],
        raw_score_finite=False,
        self_independent=False,
        determinism_within_tolerance=False,
        process_restart_isolated=False,
        operationally_feasible=False,
        execution_attempted=False,
        smoke_passed=False,
        contract_passed=False,
    )
    parts["determinism"] = make_determinism(tested=False)
    parts["operational"] = make_operational(measured=False)

    failures = _failures(parts)
    assert {
        "RAW_SCORE_RUNTIME_NOT_EXECUTED",
        "SELF_CONTRACT_NOT_EXECUTED",
        "DETERMINISM_NOT_TESTED",
        "OPERATIONAL_MEASUREMENTS_MISSING",
    } <= failures
    assert {
        "RAW_SCORE_NOT_FINITE",
        "SELF_EXTRACTION_NOT_INDEPENDENT",
        "PROCESS_RESTART_NOT_ISOLATED",
        "NONDETERMINISM_EXCEEDS_TOLERANCE",
        "FULL_RUN_NOT_OPERATIONALLY_FEASIBLE",
    }.isdisjoint(failures)


def test_executed_runtime_preserves_observed_negative_conclusions() -> None:
    parts = _parts()
    parts["facts"] = rebuild(
        parts["facts"],
        raw_score_finite=False,
        self_independent=False,
        determinism_within_tolerance=False,
        process_restart_isolated=False,
        operationally_feasible=False,
        smoke_passed=False,
        contract_passed=False,
    )

    failures = _failures(parts)
    assert {
        "RAW_SCORE_NOT_FINITE",
        "SELF_EXTRACTION_NOT_INDEPENDENT",
        "PROCESS_RESTART_NOT_ISOLATED",
        "NONDETERMINISM_EXCEEDS_TOLERANCE",
        "FULL_RUN_NOT_OPERATIONALLY_FEASIBLE",
    } <= failures
    assert {
        "RAW_SCORE_RUNTIME_NOT_EXECUTED",
        "SELF_CONTRACT_NOT_EXECUTED",
        "DETERMINISM_NOT_TESTED",
        "OPERATIONAL_MEASUREMENTS_MISSING",
    }.isdisjoint(failures)


def test_every_licensing_scope_must_be_reviewed_separately() -> None:
    parts = _parts()
    source = make_license(LicenseScope.SOURCE_CODE)
    weights = make_license(LicenseScope.WEIGHTS)
    parts["manifest"] = make_manifest(
        parts["candidate"],
        parts["registry"],
        license_records=(source, weights),
    )

    assert {
        "THIRD_PARTY_LICENSE_REVIEW_MISSING",
        "TRAINING_RESTRICTIONS_REVIEW_MISSING",
    } <= _failures(parts)


def test_checkpoint_must_bind_to_its_own_weights_licence() -> None:
    parts = _parts()
    source = make_license(LicenseScope.SOURCE_CODE)
    weights = make_license(LicenseScope.WEIGHTS)
    third_party = make_license(LicenseScope.THIRD_PARTY)
    training = make_license(LicenseScope.TRAINING_RESTRICTIONS)
    components = (
        make_component(
            "source_bundle",
            kind=ComponentKind.SOURCE_CODE,
            role="source_code",
            license_fingerprint=source.fingerprint,
            payload=b"source-bundle",
        ),
        make_component(
            "model_checkpoint",
            kind=ComponentKind.CHECKPOINT,
            role="checkpoint",
            license_fingerprint=source.fingerprint,
            payload=b"model-checkpoint",
        ),
    )
    parts["manifest"] = make_manifest(
        parts["candidate"],
        parts["registry"],
        components=components,
        license_records=(source, weights, third_party, training),
    )

    assert "CHECKPOINT_LICENSE_MISSING" in _failures(parts)


@pytest.mark.parametrize(
    "role",
    ("source_code", "checkpoint", "upstream_documentation"),
)
def test_an_expected_component_cannot_be_present_but_optional(role: str) -> None:
    parts = _parts()
    components = tuple(
        rebuild(component, required=False)
        if component.role == role
        else component
        for component in parts["manifest"].components
    )
    parts["manifest"] = rebuild(parts["manifest"], components=components)

    code = "EXPECTED_COMPONENT_NOT_REQUIRED_" + role.upper()
    assert code in _failures(parts)


def test_documented_threshold_source_must_resolve_to_locked_upstream_evidence() -> None:
    parts = _parts()
    forged = digest("unresolved-threshold-source")
    parts["decision_path"] = rebuild(
        parts["decision_path"], threshold_source_fingerprint=forged
    )
    evidence = {
        gate: tuple(references)
        for gate, references in parts["facts"].gate_evidence.items()
    }
    evidence[QualificationGate.DECISION_PATH.value] += (f"sha256:{forged}",)
    parts["facts"] = rebuild(parts["facts"], gate_evidence=evidence)

    assert "THRESHOLD_SOURCE_ARTIFACT_NOT_IDENTIFIED" in _failures(parts)


@pytest.mark.parametrize(
    "facts",
    [
        make_facts(smoke_passed=False, contract_passed=False),
        make_facts(contract_passed=False),
    ],
    ids=("smoke-failed", "contract-failed"),
)
def test_ready_status_requires_executed_smoke_and_contract_qualification(
    facts: QualificationFacts,
) -> None:
    candidate = make_candidate()
    registry = make_registry((candidate,))

    with pytest.raises(ValueError, match="readiness requires executed smoke"):
        make_report(candidate, registry, facts=facts)


def test_unexecuted_report_is_recorded_as_not_established_not_ready() -> None:
    candidate = make_candidate()
    registry = make_registry((candidate,))
    report = make_report(
        candidate,
        registry,
        facts=make_facts(
            execution_attempted=False,
            smoke_passed=False,
            contract_passed=False,
        ),
        determinism=make_determinism(tested=False),
        operational=make_operational(measured=False),
    )

    assert not report.raw_score_ready
    assert not report.decision_path_ready
    assert {
        "RAW_SCORE_RUNTIME_NOT_EXECUTED",
        "SELF_CONTRACT_NOT_EXECUTED",
        "DETERMINISM_NOT_TESTED",
        "OPERATIONAL_MEASUREMENTS_MISSING",
    } <= set(report.exact_gate_failures)


def test_candidate_specific_failures_are_preserved_verbatim() -> None:
    parts = _parts()
    parts["facts"] = rebuild(
        parts["facts"],
        extra_gate_failures={
            QualificationGate.COMPLETE_INFERENCE.value: (
                "AFR_REALIGNMENT_IMPLEMENTATION_MISSING",
            )
        },
    )
    assert "AFR_REALIGNMENT_IMPLEMENTATION_MISSING" in _failures(parts)


def test_runtime_probe_cannot_be_reused_for_another_candidate() -> None:
    first = make_candidate("candidate_first")
    first_registry = make_registry((first,))
    first_report = make_report(first, first_registry)
    assert first_report.runtime_probe is not None

    second = make_candidate("candidate_second")
    second_registry = make_registry((second,))
    with pytest.raises(QualificationError, match="another candidate identity"):
        make_report(
            second,
            second_registry,
            runtime_probe_override=first_report.runtime_probe,
        )


def test_tolerated_score_drift_can_be_raw_ready_but_not_decision_ready() -> None:
    candidate = make_candidate()
    registry = make_registry((candidate,))
    determinism = rebuild(
        make_determinism(),
        process_restart_equal=False,
        bitwise_equal=False,
        numeric_tolerance="0.02",
        maximum_observed_score_drift="0.01",
        within_predeclared_tolerance=True,
        nondeterminism_reason="synthetic score drift",
        runtime_restrictions=("fixed CPU runtime only",),
        decision_safe=False,
    )

    report = make_report(candidate, registry, determinism=determinism)

    assert report.raw_score_ready
    assert not report.decision_path_ready
    assert report.qualification_status is QualificationStatus.RAW_SCORE_READY
    assert "DRIFT_CAN_CHANGE_THRESHOLD_DECISION" in report.exact_gate_failures


def test_qualification_fact_maps_are_deeply_immutable() -> None:
    failures = {QualificationGate.COMPLETE_INFERENCE.value: ("MISSING",)}
    facts = make_facts(extra_gate_failures=failures)
    failures[QualificationGate.COMPLETE_INFERENCE.value] = ("CHANGED",)
    assert facts.extra_gate_failures[QualificationGate.COMPLETE_INFERENCE.value] == (
        "MISSING",
    )
    with pytest.raises(TypeError):
        facts.extra_gate_failures[QualificationGate.COMPLETE_INFERENCE.value] = (  # type: ignore[index]
            "CHANGED",
        )
