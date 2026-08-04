from __future__ import annotations

import dataclasses

import pytest

from fpbench.core.errors import QualificationError
from fpbench.core.modern_matcher_models import (
    CandidatePreprocessingProfile,
    DecisionPathKind,
    DevelopmentCohortKind,
    LicenseScope,
    QualificationStatus,
    RepresentationBranch,
    ThresholdSourceKind,
)
from fpbench.core.serialization import to_plain
from fpbench.modern_matchers.loading import candidate_from_plain
from stage8aworld import (
    build_evidence_world,
    digest,
    make_candidate,
    make_decision_path,
    make_determinism,
    make_license,
    make_manifest,
    make_operational,
    make_policy,
    make_preprocessing,
    make_registry,
    make_report,
    rebuild,
)

pytestmark = pytest.mark.stage8a_contract


def test_every_fixture_model_has_a_full_self_verifying_fingerprint() -> None:
    candidate = make_candidate()
    registry = make_registry((candidate,))
    report = make_report(candidate, registry)

    records = (
        candidate,
        registry,
        report.artifact_manifest,
        *report.artifact_manifest.components,
        *report.artifact_manifest.license_records,
        report.preprocessing_profile,
        report.representation_profile,
        report.score_profile,
        report.determinism_report,
        report.operational_report,
        report.decision_path,
        *report.gate_results,
        report,
        make_policy(),
    )
    for record in records:
        assert record is not None
        assert len(record.fingerprint) == 64
        assert set(record.fingerprint) <= set("0123456789abcdef")


def test_frozen_models_detach_nested_collections_from_the_caller() -> None:
    candidate = make_candidate()
    candidates = [candidate]
    registry = make_registry(candidates)
    candidates.clear()

    assert registry.candidates == (candidate,)
    with pytest.raises(dataclasses.FrozenInstanceError):
        registry.reserve_activation = "silently activate reserve"  # type: ignore[misc]


def test_a_clear_weight_licence_may_forbid_redistribution() -> None:
    record = make_license(LicenseScope.WEIGHTS)
    assert record.redistribution_allowed is False
    assert record.hold_and_execute_allowed is True


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"license_document_sha256": None}, "identified, hashed"),
        ({"evidence": ()}, "inspection evidence"),
    ),
)
def test_a_clear_licence_requires_a_hashed_rights_document_and_evidence(
    changes,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        rebuild(make_license(LicenseScope.WEIGHTS), **changes)


def test_a_complete_preprocessing_profile_requires_every_documented_operation() -> None:
    complete = make_preprocessing()
    claims = {
        item.name: getattr(complete, item.name)
        for item in dataclasses.fields(complete)
        if item.name != "fingerprint"
    }
    claims["operations"] = complete.operations[:-1]

    with pytest.raises(ValueError, match="every required operation"):
        CandidatePreprocessingProfile.create(**claims)


def test_strict_loading_rejects_unknown_and_missing_candidate_fields() -> None:
    payload = to_plain(make_candidate())
    with pytest.raises(ValueError, match="unknown"):
        candidate_from_plain({**payload, "threshold": 40})

    payload.pop("paper_citation")
    with pytest.raises(ValueError, match="missing"):
        candidate_from_plain(payload)


@pytest.mark.parametrize(
    "status",
    (QualificationStatus.SELECTED, QualificationStatus.REJECTED),
)
def test_selection_states_do_not_leak_back_into_qualification_reports(
    status: QualificationStatus,
) -> None:
    candidate = make_candidate()
    registry = make_registry((candidate,))
    report = make_report(candidate, registry)

    with pytest.raises(ValueError, match="selection state belongs"):
        rebuild(report, qualification_status=status)


def test_empty_representation_shapes_are_not_valid_shapes() -> None:
    with pytest.raises(ValueError, match="dimensions"):
        RepresentationBranch.create(
            schema_version="1",
            branch_id="empty",
            kind="embedding",
            shape=(),
            included_in_final_score=True,
            combination_rule="direct",
        )


def test_selection_policy_rejects_duplicate_mandatory_gates() -> None:
    policy = make_policy()
    with pytest.raises(ValueError, match="exactly once"):
        rebuild(
            policy,
            mandatory_gates=policy.mandatory_gates + (policy.mandatory_gates[0],),
        )


def test_nested_wall_clocks_do_not_change_a_parent_semantic_identity() -> None:
    candidate = make_candidate()
    registry = make_registry((candidate,))
    report = make_report(candidate, registry)
    later_manifest = rebuild(
        report.artifact_manifest,
        acquired_utc="2027-01-01T00:00:00+00:00",
    )
    later_report = rebuild(report, artifact_manifest=later_manifest)

    assert later_manifest.fingerprint == report.artifact_manifest.fingerprint
    assert later_report.fingerprint == report.fingerprint


def test_required_verifier_commits_cannot_be_null(tmp_path) -> None:
    world = build_evidence_world(tmp_path, ready=True)
    with pytest.raises(ValueError, match="commit"):
        rebuild(world.decision, verifier_source_commit=None)
    with pytest.raises(ValueError, match="commit"):
        rebuild(world.finalization, verifier_source_commit=None)


def test_top_level_wall_clock_is_outside_semantic_identity() -> None:
    candidate = make_candidate()
    registry = make_registry((candidate,))
    manifest = make_manifest(candidate, registry)
    later = rebuild(manifest, acquired_utc="2028-01-01T00:00:00+00:00")
    assert later.fingerprint == manifest.fingerprint


def test_create_hashes_canonical_claims_not_unnormalized_input() -> None:
    candidate = make_candidate()
    registry = make_registry((candidate,))
    component = make_manifest(candidate, registry).components[0]
    assert component.sha256 is not None
    assert component.source_commit is not None

    normalized = rebuild(
        component,
        sha256=component.sha256.upper(),
        source_commit=component.source_commit.upper(),
    )

    assert normalized.sha256 == component.sha256
    assert normalized.source_commit == component.source_commit
    assert normalized.fingerprint == component.fingerprint


def test_report_identity_binds_the_embedded_manifest_to_the_candidate() -> None:
    candidate = make_candidate()
    registry = make_registry((candidate,))
    manifest = make_manifest(candidate, registry)
    forged = rebuild(manifest, candidate_fingerprint=digest("another-candidate"))

    with pytest.raises(QualificationError, match="does not belong"):
        make_report(candidate, registry, manifest=forged)


@pytest.mark.parametrize(
    "source_kind",
    (
        ThresholdSourceKind.PAPER_EER,
        ThresholdSourceKind.REPORTED_FAR_WITHOUT_RAW_CALIBRATION,
        ThresholdSourceKind.ASSUMED_COSINE_ZERO,
    ),
)
def test_paper_metrics_and_assumed_zero_are_not_checkpoint_thresholds(
    source_kind: ThresholdSourceKind,
) -> None:
    path = make_decision_path()
    with pytest.raises(ValueError, match="paper EER"):
        rebuild(path, threshold_source_kind=source_kind)


def test_a_documented_threshold_must_be_a_finite_number() -> None:
    with pytest.raises(ValueError, match="finite decimal"):
        rebuild(make_decision_path(), documented_threshold="paper EER")


def test_a_documented_threshold_requires_a_content_addressed_source() -> None:
    with pytest.raises(ValueError, match="name and hash its source"):
        rebuild(make_decision_path(), threshold_source_fingerprint=None)


def test_sd300_cannot_be_declared_an_independent_calibration_cohort() -> None:
    path = make_decision_path(
        kind=DecisionPathKind.EXTERNAL_DEVELOPMENT_CALIBRATION
    )
    with pytest.raises(ValueError, match="SD300"):
        rebuild(
            path,
            development_cohort="NIST SD300",
            development_cohort_kind=DevelopmentCohortKind.SD300_EVALUATION,
        )


def test_artifact_logical_paths_reject_surrounding_whitespace() -> None:
    candidate = make_candidate()
    registry = make_registry((candidate,))
    manifest = make_manifest(candidate, registry)
    with pytest.raises(ValueError, match="storage_reference"):
        rebuild(manifest, storage_reference="candidate/trailing ")
    with pytest.raises(ValueError, match="filename"):
        rebuild(manifest.components[0], filename="source_bundle.bin ")


def test_operational_feasibility_cannot_ignore_a_failed_limit() -> None:
    report = make_operational()
    with pytest.raises(ValueError, match="derived from every recorded"):
        rebuild(report, max_artifact_disk_bytes=report.artifact_disk_bytes - 1)


def test_non_bitwise_determinism_requires_runtime_restrictions() -> None:
    with pytest.raises(ValueError, match="runtime restrictions"):
        rebuild(
            make_determinism(),
            process_restart_equal=False,
            bitwise_equal=False,
            numeric_tolerance="0.02",
            maximum_observed_score_drift="0.01",
            within_predeclared_tolerance=True,
            nondeterminism_reason="synthetic score drift",
            runtime_restrictions=(),
            decision_safe=False,
        )
