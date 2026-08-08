"""The frozen Stage 8E policy: the vocabulary, the decision table, the refusals.

Pure Python over notices that were never issued. No dataset, no runtime, no
checkpoint, no network and no workspace — a policy layer that needed any of them
in order to be qualified would be a policy nobody could re-qualify later.

What is under test is that the *decision follows from the facts*. The engine has
no parameter through which a caller could supply a verdict, so every test here
supplies an observation and some facts and asserts which of the four decisions
comes back.
"""

from __future__ import annotations

import pytest

from fpbench.core.third_party_errors import (
    LicenseObservationError,
    RedistributionError,
    ResearchUseDecisionError,
    ThirdPartyArtifactError,
    ThirdPartyPurposeError,
    ThirdPartyUsageError,
    UpstreamTransformationError,
)
from fpbench.core.third_party_models import (
    ArtifactStorageClass,
    IntendedUsePermissionStatus,
    LicenseEvidence,
    LicenseObservation,
    LicenseObservationStatus,
    NonBlockingRestriction,
    OwnerRiskAcceptance,
    ProjectPurpose,
    ProjectPurposeDeclaration,
    RedistributionDecision,
    RedistributionRecord,
    ResearchUseBlocker,
    ResearchUseDecision,
    ThirdPartyComponentKind,
    TransformationClassification,
    UpstreamIdentity,
    UpstreamModificationStrategy,
    read_license_observation,
    read_project_purpose_declaration,
    read_third_party_policy,
    read_third_party_usage_record,
    strict_json_document,
)
from fpbench.third_party import (
    PlausibleReading,
    assess_research_use,
    build_placement,
    build_usage_manifest,
    build_usage_record,
    choose_modification_strategy,
    intersection_permits_intended_use,
    needs_intersection,
    project_purpose,
    record_transformation,
    require_integration_only,
    require_manifest_opens_execution,
    resolve_third_party_root,
    storage_class_for,
    third_party_policy,
    transformation_over_bytes,
    verify_usage_record,
)
from fpbench.third_party.artifacts import THIRD_PARTY_ROOT_ENV, verify_placed_artifact

pytestmark = pytest.mark.stage8e_contract


def observation(
    status: LicenseObservationStatus,
    *,
    observation_id: str = "fixture",
    kind: ThirdPartyComponentKind = ThirdPartyComponentKind.SOURCE_CODE,
    names: tuple[str, ...] = (),
    restrictions: tuple[str, ...] = (),
    evidence_count: int = 1,
) -> LicenseObservation:
    return LicenseObservation(
        observation_id=observation_id,
        component_kind=kind,
        subject="a fixture describing no real upstream project",
        status=status,
        declared_license_names=names,
        stated_restrictions=restrictions,
        evidence=tuple(
            LicenseEvidence(
                locator=f"fixture://notice/{index}", description="an invented notice"
            )
            for index in range(evidence_count)
        ),
    )


def acceptance(**overrides) -> OwnerRiskAcceptance:
    fields = {
        "published_intentionally_by_official_authors": True,
        "publicly_obtainable_without_circumvention": True,
        "intended_operation_is_local_research_only": True,
        "no_located_term_expressly_prohibits_the_use": True,
        "no_bytes_will_be_redistributed": True,
        "accepted_by": "the project owner",
        "basis": "a local research operation despite an unresolved ambiguity",
    }
    fields.update(overrides)
    return OwnerRiskAcceptance(**fields)


def readings(*permitted: bool) -> tuple[PlausibleReading, ...]:
    return tuple(
        PlausibleReading(
            notice_locator=f"fixture://notice/{index}",
            permits_local_execution=True,
            permits_non_commercial_use=True,
            permits_educational_research=allowed,
        )
        for index, allowed in enumerate(permitted)
    )


# --------------------------------------------------------------- the purpose


def test_the_purpose_is_the_one_term_and_every_denial_is_false() -> None:
    declaration = project_purpose()
    assert declaration.purpose is ProjectPurpose.PERSONAL_EDUCATIONAL_RESEARCH
    assert declaration.purpose.value == "PERSONAL_EDUCATIONAL_RESEARCH"
    for name in ProjectPurposeDeclaration.DENIED_FLAGS:
        assert getattr(declaration, name) is False, name
    assert len(declaration.purpose_fingerprint) == 64


def test_the_purpose_vocabulary_offers_no_academic_term() -> None:
    """docs/adr/0081: a vocabulary that offered the word would see it claimed."""
    assert [member.value for member in ProjectPurpose] == [
        "PERSONAL_EDUCATIONAL_RESEARCH"
    ]


def test_a_declaration_that_permits_commercial_use_is_refused() -> None:
    with pytest.raises(ThirdPartyPurposeError, match="commercial_deployment"):
        ProjectPurposeDeclaration(
            purpose=ProjectPurpose.PERSONAL_EDUCATIONAL_RESEARCH,
            statement="a declaration describing a different project",
            commercial_use_by_project_owner=False,
            commercial_deployment=True,
            commercial_service=False,
            third_party_redistribution=False,
            third_party_sublicensing=False,
            benchmark_publication_as_academic_work=False,
        )


def test_the_purpose_round_trips_through_its_strict_reader() -> None:
    import json

    from fpbench.core.serialization import to_plain

    declaration = project_purpose()
    restored = read_project_purpose_declaration(
        strict_json_document(json.dumps(to_plain(declaration)))
    )
    assert restored == declaration


# ---------------------------------------------------------------- the policy


def test_the_policy_never_vendors_and_its_ci_claims_are_all_false() -> None:
    policy = third_party_policy()
    assert policy.vendoring_default == "DO_NOT_VENDOR"
    assert policy.ci_downloads_restricted_artifacts is False
    assert policy.ci_uploads_third_party_bytes is False
    assert policy.publishes_container_images_with_third_party_artifacts is False
    assert policy.dataset_rights_unchanged is True
    assert policy.purpose_fingerprint == project_purpose().purpose_fingerprint


def test_the_modification_ladder_keeps_its_order() -> None:
    policy = third_party_policy()
    assert [item.rung for item in policy.modification_strategy_order] == [1, 2, 3]
    assert (
        policy.modification_strategy_order[0]
        is UpstreamModificationStrategy.WRAPPER_WITHOUT_UPSTREAM_MODIFICATION
    )


def test_the_policy_round_trips_through_its_strict_reader() -> None:
    import json

    from fpbench.core.serialization import to_plain

    policy = third_party_policy()
    restored = read_third_party_policy(
        strict_json_document(json.dumps(to_plain(policy)))
    )
    assert restored == policy


def test_the_permitted_and_forbidden_repository_content_do_not_overlap() -> None:
    policy = third_party_policy()
    assert not (
        set(policy.repository_permitted_content)
        & set(policy.repository_forbidden_content)
    )


# ------------------------------------------------------------ the observation


def test_an_observation_carries_no_decision_field() -> None:
    """docs/adr/0082: an observation that could carry a conclusion will be read as one."""
    fields = {field for field in LicenseObservation.__dataclass_fields__}
    assert "decision" not in fields
    assert "research_use_decision" not in fields
    assert "allowed" not in fields


def test_no_license_found_may_not_name_a_licence() -> None:
    with pytest.raises(LicenseObservationError, match="NO_LICENSE_FOUND"):
        observation(
            LicenseObservationStatus.NO_LICENSE_FOUND,
            names=("Apache License 2.0",),
            evidence_count=0,
        )


def test_unknown_may_not_carry_an_observed_restriction() -> None:
    with pytest.raises(LicenseObservationError, match="UNKNOWN"):
        observation(
            LicenseObservationStatus.UNKNOWN,
            restrictions=("something somebody remembered",),
            evidence_count=0,
        )


def test_conflicting_notices_needs_two_notices() -> None:
    with pytest.raises(LicenseObservationError, match="at least two"):
        observation(LicenseObservationStatus.CONFLICTING_NOTICES, evidence_count=1)


def test_identified_terms_need_a_notice_somebody_read() -> None:
    with pytest.raises(LicenseObservationError, match="terms come from a notice"):
        observation(
            LicenseObservationStatus.OPEN_SOURCE_PERMISSIVE,
            names=("MIT License",),
            evidence_count=0,
        )


def test_an_observation_round_trips_through_its_strict_reader() -> None:
    import json

    from fpbench.core.serialization import to_plain

    original = observation(
        LicenseObservationStatus.OPEN_SOURCE_COPYLEFT,
        names=("GNU Lesser General Public License v3.0",),
        restrictions=("Source obligations apply on conveying.",),
    )
    restored = read_license_observation(
        strict_json_document(json.dumps(to_plain(original)))
    )
    assert restored == original


# ---------------------------------------------------------- the decision table


def test_a_permissive_licence_is_allowed_outright() -> None:
    assessment = assess_research_use(
        observation(
            LicenseObservationStatus.OPEN_SOURCE_PERMISSIVE,
            names=("Apache License 2.0",),
        ),
        assessment_id="fixture_permissive",
        basis="conditions attach to distribution and there is none",
        non_blocking_restrictions=(
            NonBlockingRestriction.ATTRIBUTION_AND_NOTICE_RETENTION,
        ),
    )
    assert assessment.decision is ResearchUseDecision.ALLOWED
    assert (
        assessment.intended_use_permission_status
        is IntendedUsePermissionStatus.ESTABLISHED
    )


def test_copyleft_is_not_a_field_of_use_restriction() -> None:
    """The FSF's own position: running and copying is not conveying."""
    assert not needs_intersection(
        LicenseObservationStatus.OPEN_SOURCE_COPYLEFT,
        (NonBlockingRestriction.STRONG_COPYLEFT, NonBlockingRestriction.COPYLEFT),
    )
    assessment = assess_research_use(
        observation(
            LicenseObservationStatus.OPEN_SOURCE_COPYLEFT,
            names=("GNU General Public License v3.0",),
        ),
        assessment_id="fixture_copyleft",
        basis="nothing is conveyed",
        non_blocking_restrictions=(NonBlockingRestriction.STRONG_COPYLEFT,),
    )
    assert assessment.decision is ResearchUseDecision.ALLOWED


@pytest.mark.parametrize(
    "status,restriction",
    [
        (LicenseObservationStatus.NON_COMMERCIAL, NonBlockingRestriction.NON_COMMERCIAL_ONLY),
        (
            LicenseObservationStatus.ACADEMIC_ONLY,
            NonBlockingRestriction.ACADEMIC_OR_RESEARCH_ONLY,
        ),
        (
            LicenseObservationStatus.RESEARCH_ONLY,
            NonBlockingRestriction.ACADEMIC_OR_RESEARCH_ONLY,
        ),
        (
            LicenseObservationStatus.SOURCE_AVAILABLE,
            NonBlockingRestriction.EDUCATIONAL_ONLY,
        ),
    ],
)
def test_a_field_limited_licence_passes_on_the_intersection(
    status: LicenseObservationStatus, restriction: NonBlockingRestriction
) -> None:
    """The whole point of the stage: these restrict nothing this project does."""
    assessment = assess_research_use(
        observation(status, names=("a restricted licence",)),
        assessment_id="fixture_field_limited",
        basis="the declared purpose forecloses every use this restricts",
        non_blocking_restrictions=(restriction,),
        intersection_readings=readings(True, True),
    )
    assert (
        assessment.decision
        is ResearchUseDecision.ALLOWED_UNDER_RESTRICTIVE_INTERSECTION
    )
    assert assessment.intersection_permits_intended_use is True


def test_conflicting_notices_stay_conflicting_while_the_use_is_allowed() -> None:
    source = observation(
        LicenseObservationStatus.CONFLICTING_NOTICES,
        names=("Apache License 2.0", "academic use only"),
        evidence_count=2,
    )
    assessment = assess_research_use(
        source,
        assessment_id="fixture_conflicting",
        basis="every plausible reading permits local educational research",
        non_blocking_restrictions=(
            NonBlockingRestriction.NOTICE_CONFLICT_WITH_PERMISSIVE_INTERSECTION,
        ),
        intersection_readings=readings(True, True),
    )
    assert source.status is LicenseObservationStatus.CONFLICTING_NOTICES
    assert (
        assessment.decision
        is ResearchUseDecision.ALLOWED_UNDER_RESTRICTIVE_INTERSECTION
    )


def test_one_forbidding_reading_blocks_the_intersection() -> None:
    assessment = assess_research_use(
        observation(
            LicenseObservationStatus.CONFLICTING_NOTICES,
            names=("a permissive notice", "an evaluation-only notice"),
            evidence_count=2,
        ),
        assessment_id="fixture_conflict_blocked",
        basis="one reading forbids the exact operation",
        non_blocking_restrictions=(
            NonBlockingRestriction.NOTICE_CONFLICT_WITH_PERMISSIVE_INTERSECTION,
        ),
        intersection_readings=readings(True, False),
    )
    assert assessment.decision is ResearchUseDecision.BLOCKED
    assert (
        ResearchUseBlocker.INTENDED_RESEARCH_USE_EXPRESSLY_PROHIBITED
        in assessment.blockers
    )


def test_an_intersection_needs_two_readings() -> None:
    with pytest.raises(LicenseObservationError, match="at least two"):
        intersection_permits_intended_use(readings(True))


def test_a_field_limited_status_may_not_skip_the_intersection() -> None:
    with pytest.raises(ResearchUseDecisionError, match="has to be computed"):
        assess_research_use(
            observation(
                LicenseObservationStatus.ACADEMIC_ONLY, names=("academic only",)
            ),
            assessment_id="fixture_uncomputed",
            basis="assumed to be fine",
            non_blocking_restrictions=(
                NonBlockingRestriction.ACADEMIC_OR_RESEARCH_ONLY,
            ),
        )


def test_permissive_and_field_limited_cannot_both_hold() -> None:
    """An OSI-conforming licence cannot restrict the field of endeavour."""
    with pytest.raises(ResearchUseDecisionError, match="source-available"):
        assess_research_use(
            observation(
                LicenseObservationStatus.OPEN_SOURCE_PERMISSIVE, names=("MIT License",)
            ),
            assessment_id="fixture_contradictory",
            basis="a record that misread one of its notices",
            non_blocking_restrictions=(NonBlockingRestriction.NON_COMMERCIAL_ONLY,),
        )


def test_a_field_limited_status_must_name_its_restriction() -> None:
    with pytest.raises(ResearchUseDecisionError, match="lost what the notice said"):
        assess_research_use(
            observation(
                LicenseObservationStatus.ACADEMIC_ONLY, names=("academic only",)
            ),
            assessment_id="fixture_lost",
            basis="a record that dropped the restriction it read",
            intersection_readings=readings(True, True),
        )


def test_an_intersection_offered_where_nothing_restricts_is_refused() -> None:
    with pytest.raises(ResearchUseDecisionError, match="ordinary ALLOWED"):
        assess_research_use(
            observation(
                LicenseObservationStatus.OPEN_SOURCE_PERMISSIVE,
                names=("MIT License",),
            ),
            assessment_id="fixture_overstated",
            basis="care that was not needed",
            intersection_readings=readings(True, True),
        )


# ---------------------------------------------------------- the unresolved case


def test_an_absent_licence_may_be_risk_accepted_and_stays_unresolved() -> None:
    assessment = assess_research_use(
        observation(
            LicenseObservationStatus.NO_LICENSE_FOUND,
            kind=ThirdPartyComponentKind.MODEL_WEIGHTS,
            evidence_count=0,
        ),
        assessment_id="fixture_risk",
        basis="the owner accepted the risk of a local research operation",
        owner_risk_acceptance=acceptance(),
    )
    assert assessment.decision is ResearchUseDecision.OWNER_RISK_ACCEPTED
    assert (
        assessment.intended_use_permission_status
        is IntendedUsePermissionStatus.UNRESOLVED
    )


def test_an_absent_licence_without_acceptance_is_blocked() -> None:
    """docs/adr/0084: silence is not a grant."""
    assessment = assess_research_use(
        observation(
            LicenseObservationStatus.UNKNOWN,
            kind=ThirdPartyComponentKind.RUNTIME_BINARY,
            evidence_count=0,
        ),
        assessment_id="fixture_unaccepted",
        basis="nobody accepted the risk",
    )
    assert assessment.decision is ResearchUseDecision.BLOCKED
    assert assessment.blockers == (
        ResearchUseBlocker.PERMISSION_UNRESOLVED_AND_NOT_RISK_ACCEPTED,
    )


@pytest.mark.parametrize("condition", OwnerRiskAcceptance.CONDITIONS)
def test_a_partial_risk_acceptance_is_refused(condition: str) -> None:
    with pytest.raises(ResearchUseDecisionError, match="every condition"):
        acceptance(**{condition: False})


def test_risk_may_not_be_accepted_over_terms_that_were_found() -> None:
    with pytest.raises(ResearchUseDecisionError, match="Terms were identified"):
        assess_research_use(
            observation(
                LicenseObservationStatus.OPEN_SOURCE_PERMISSIVE,
                names=("Apache License 2.0",),
            ),
            assessment_id="fixture_overrule",
            basis="an attempt to overrule a licence that was found",
            owner_risk_acceptance=acceptance(),
        )


def test_an_unestablished_identity_blocks_whatever_the_licence_says() -> None:
    assessment = assess_research_use(
        observation(
            LicenseObservationStatus.OPEN_SOURCE_PERMISSIVE, names=("MIT License",)
        ),
        assessment_id="fixture_no_identity",
        basis="permissively licensed and impossible to name",
        identity_established=False,
    )
    assert assessment.decision is ResearchUseDecision.BLOCKED
    assert (
        ResearchUseBlocker.ARTIFACT_IDENTITY_NOT_ESTABLISHED in assessment.blockers
    )


# -------------------------------------------------------------- the dataset


def test_a_dataset_must_answer_the_dataset_question() -> None:
    with pytest.raises(ResearchUseDecisionError, match="access terms are satisfied"):
        assess_research_use(
            observation(
                LicenseObservationStatus.OPEN_SOURCE_PERMISSIVE,
                kind=ThirdPartyComponentKind.DATASET,
                names=("a permissive data licence",),
            ),
            assessment_id="fixture_dataset_unanswered",
            basis="a dataset assessed as though it were software",
        )


def test_a_dataset_may_never_be_risk_accepted() -> None:
    """spec section 11: Stage 8E did not make dataset restrictions non-blocking."""
    with pytest.raises(ResearchUseDecisionError, match="not risk-accepted"):
        assess_research_use(
            observation(
                LicenseObservationStatus.NO_LICENSE_FOUND,
                kind=ThirdPartyComponentKind.DATASET,
                evidence_count=0,
            ),
            assessment_id="fixture_dataset_risk",
            basis="an attempt to wave a dataset through",
            owner_risk_acceptance=acceptance(),
            dataset_access_terms_satisfied=False,
        )


def test_an_unsatisfied_dataset_is_blocked() -> None:
    assessment = assess_research_use(
        observation(
            LicenseObservationStatus.OPEN_SOURCE_PERMISSIVE,
            kind=ThirdPartyComponentKind.DATASET,
            names=("a permissive data licence",),
        ),
        assessment_id="fixture_dataset_unsatisfied",
        basis="the delivery terms were never agreed",
        dataset_access_terms_satisfied=False,
    )
    assert assessment.decision is ResearchUseDecision.BLOCKED
    assert (
        ResearchUseBlocker.DATASET_ACCESS_TERMS_NOT_SATISFIED in assessment.blockers
    )


def test_a_non_dataset_may_not_answer_the_dataset_question() -> None:
    with pytest.raises(ResearchUseDecisionError, match="belongs to a"):
        assess_research_use(
            observation(
                LicenseObservationStatus.OPEN_SOURCE_PERMISSIVE, names=("MIT License",)
            ),
            assessment_id="fixture_wrong_kind",
            basis="a source record answering a dataset question",
            dataset_access_terms_satisfied=True,
        )


# ---------------------------------------------------------- the usage record


def permissive_pair() -> tuple[LicenseObservation, "object"]:
    source = observation(
        LicenseObservationStatus.OPEN_SOURCE_PERMISSIVE, names=("MIT License",)
    )
    assessment = assess_research_use(
        source,
        assessment_id="fixture_record",
        basis="conditions attach to distribution and there is none",
        non_blocking_restrictions=(
            NonBlockingRestriction.ATTRIBUTION_AND_NOTICE_RETENTION,
        ),
    )
    return source, assessment


def identity() -> UpstreamIdentity:
    return UpstreamIdentity(
        upstream_name="a fixture",
        upstream_locator="https://example.invalid/fixture",
        exact_version="1.0.0",
    )


def test_a_usage_record_binds_its_observation_and_its_assessment() -> None:
    source, assessment = permissive_pair()
    record = build_usage_record(
        record_id="fixture_record",
        observation=source,
        assessment=assessment,
        upstream_identity=identity(),
        redistribution_decision=RedistributionDecision.CONDITIONAL,
        redistribution_basis="permitted with notices retained; not exercised",
    )
    assert record.license_observation_fingerprint == source.observation_fingerprint
    assert record.research_use_assessment_fingerprint == (
        assessment.assessment_fingerprint
    )
    assert record.stored_in_git is False
    assert record.stored_in_ci_artifacts is False
    assert record.redistribution.redistributed_by_fpbench is False
    assert verify_usage_record(record, source, assessment).verified


def test_a_record_over_a_different_observation_is_refused() -> None:
    source, assessment = permissive_pair()
    other = observation(
        LicenseObservationStatus.OPEN_SOURCE_PERMISSIVE,
        observation_id="other",
        names=("BSD 3-Clause License",),
    )
    with pytest.raises(ThirdPartyUsageError, match="assessment was taken over"):
        build_usage_record(
            record_id="fixture_mismatch",
            observation=other,
            assessment=assessment,
            upstream_identity=identity(),
            redistribution_decision=RedistributionDecision.ALLOWED,
            redistribution_basis="permitted and not exercised",
        )


def test_nothing_can_claim_this_project_redistributes() -> None:
    with pytest.raises(RedistributionError, match="redistributes no third-party"):
        RedistributionRecord(
            decision=RedistributionDecision.ALLOWED,
            basis="an attempt to record a redistribution",
            redistributed_by_fpbench=True,
        )


def test_weights_may_not_be_declared_repository_metadata() -> None:
    source = observation(
        LicenseObservationStatus.NO_LICENSE_FOUND,
        kind=ThirdPartyComponentKind.MODEL_WEIGHTS,
        evidence_count=0,
    )
    assessment = assess_research_use(
        source,
        assessment_id="fixture_weights",
        basis="the owner accepted the risk",
        owner_risk_acceptance=acceptance(),
    )
    with pytest.raises(ThirdPartyUsageError, match="bytes live in the local"):
        build_usage_record(
            record_id="fixture_weights_in_repo",
            observation=source,
            assessment=assessment,
            upstream_identity=identity(),
            redistribution_decision=RedistributionDecision.NOT_ESTABLISHED,
            redistribution_basis="not established and not exercised",
            storage_class=ArtifactStorageClass.REPOSITORY_METADATA,
        )


@pytest.mark.parametrize(
    "kind,expected",
    [
        (ThirdPartyComponentKind.SOURCE_CODE, ArtifactStorageClass.LOCAL_ARTIFACT_STORE),
        (
            ThirdPartyComponentKind.MODEL_WEIGHTS,
            ArtifactStorageClass.LOCAL_ARTIFACT_STORE,
        ),
        (
            ThirdPartyComponentKind.RUNTIME_BINARY,
            ArtifactStorageClass.LOCAL_ARTIFACT_STORE,
        ),
        (ThirdPartyComponentKind.DATASET, ArtifactStorageClass.LOCAL_ARTIFACT_STORE),
        (
            ThirdPartyComponentKind.OTHER_ARTIFACT,
            ArtifactStorageClass.LOCAL_ARTIFACT_STORE,
        ),
        (
            ThirdPartyComponentKind.PACKAGE_DEPENDENCY,
            ArtifactStorageClass.REPOSITORY_METADATA,
        ),
        (
            ThirdPartyComponentKind.DOCUMENTATION,
            ArtifactStorageClass.REPOSITORY_METADATA,
        ),
    ],
)
def test_upstream_source_is_a_runtime_artifact_like_any_other(
    kind: ThirdPartyComponentKind, expected: ArtifactStorageClass
) -> None:
    """spec section 7: an upstream repository is not vendored either."""
    assert storage_class_for(kind) is expected


def test_a_manifest_with_a_blocked_component_does_not_open_execution() -> None:
    source, assessment = permissive_pair()
    good = build_usage_record(
        record_id="fixture_good",
        observation=source,
        assessment=assessment,
        upstream_identity=identity(),
        redistribution_decision=RedistributionDecision.ALLOWED,
        redistribution_basis="permitted and not exercised",
    )
    blocked_source = observation(
        LicenseObservationStatus.UNKNOWN,
        observation_id="fixture_blocked",
        kind=ThirdPartyComponentKind.MODEL_WEIGHTS,
        evidence_count=0,
    )
    blocked_assessment = assess_research_use(
        blocked_source,
        assessment_id="fixture_blocked",
        basis="nobody accepted the risk",
    )
    blocked = build_usage_record(
        record_id="fixture_blocked",
        observation=blocked_source,
        assessment=blocked_assessment,
        upstream_identity=identity(),
        redistribution_decision=RedistributionDecision.NOT_ESTABLISHED,
        redistribution_basis="not established",
    )
    manifest = build_usage_manifest(
        manifest_id="fixture_manifest",
        subject="a fixture integration",
        records=(good, blocked),
    )
    assert manifest.opens_execution is False
    with pytest.raises(ThirdPartyUsageError, match="may not be executed"):
        require_manifest_opens_execution(manifest)


def test_a_usage_record_round_trips_through_its_strict_reader() -> None:
    import json

    from fpbench.core.serialization import to_plain

    source, assessment = permissive_pair()
    record = build_usage_record(
        record_id="fixture_record",
        observation=source,
        assessment=assessment,
        upstream_identity=identity(),
        redistribution_decision=RedistributionDecision.CONDITIONAL,
        redistribution_basis="permitted with notices retained; not exercised",
    )
    restored = read_third_party_usage_record(
        strict_json_document(json.dumps(to_plain(record)))
    )
    assert restored == record


# -------------------------------------------------------- the artifact store


def test_the_store_root_comes_from_the_environment_or_the_home_default(
    tmp_path,
) -> None:
    chosen = tmp_path / "artifacts"
    assert (
        resolve_third_party_root({THIRD_PARTY_ROOT_ENV: str(chosen)}) == chosen
    )
    default = resolve_third_party_root({})
    assert default.parts[-3:] == (".cache", "fpbench", "third_party")


def test_a_relative_store_root_is_refused() -> None:
    with pytest.raises(ThirdPartyArtifactError, match="absolute path"):
        resolve_third_party_root({THIRD_PARTY_ROOT_ENV: "artifacts"})


def test_a_store_inside_the_repository_is_refused(tmp_path) -> None:
    repository = tmp_path / "repo"
    (repository / "third_party").mkdir(parents=True)
    with pytest.raises(ThirdPartyArtifactError, match="inside the"):
        resolve_third_party_root(
            {THIRD_PARTY_ROOT_ENV: str(repository / "third_party")},
            repository_root=repository,
        )


def test_a_placement_names_no_machine(tmp_path) -> None:
    placement = build_placement(
        placement_id="fixture_placement",
        component_role="checkpoint",
        component_kind=ThirdPartyComponentKind.MODEL_WEIGHTS,
        relative_location="fixture/best_model.pyt",
        expected_sha256="a" * 64,
        expected_size_bytes=1024,
        upstream_identity=identity(),
    )
    plain = {field: getattr(placement, field) for field in ("relative_location",)}
    assert not plain["relative_location"].startswith(("/", "\\", "~"))
    with pytest.raises(ThirdPartyArtifactError, match="names a machine"):
        build_placement(
            placement_id="fixture_absolute",
            component_role="checkpoint",
            component_kind=ThirdPartyComponentKind.MODEL_WEIGHTS,
            relative_location="/var/lib/fpbench/best_model.pyt",
            expected_sha256="a" * 64,
            expected_size_bytes=1024,
            upstream_identity=identity(),
        )


def test_an_absent_artifact_is_reported_rather_than_raised(tmp_path) -> None:
    """Every CI runner is in this state by design."""
    placement = build_placement(
        placement_id="fixture_absent",
        component_role="checkpoint",
        component_kind=ThirdPartyComponentKind.MODEL_WEIGHTS,
        relative_location="fixture/best_model.pyt",
        expected_sha256="a" * 64,
        expected_size_bytes=1024,
        upstream_identity=identity(),
    )
    result = verify_placed_artifact(placement, root=tmp_path)
    assert result.present is False
    assert result.verified is False


def test_the_wrong_bytes_are_caught_by_size_before_digest(tmp_path) -> None:
    import hashlib

    payload = b"not the expected artifact"
    target = tmp_path / "fixture" / "best_model.pyt"
    target.parent.mkdir(parents=True)
    target.write_bytes(payload)
    placement = build_placement(
        placement_id="fixture_present",
        component_role="checkpoint",
        component_kind=ThirdPartyComponentKind.MODEL_WEIGHTS,
        relative_location="fixture/best_model.pyt",
        expected_sha256=hashlib.sha256(payload).hexdigest(),
        expected_size_bytes=len(payload) + 1,
        upstream_identity=identity(),
    )
    result = verify_placed_artifact(placement, root=tmp_path)
    assert result.present is True
    assert result.size_matches is False
    assert result.digest_matches is True
    assert result.verified is False


def test_an_upstream_locator_may_not_be_a_local_path() -> None:
    with pytest.raises(ThirdPartyArtifactError, match="local path"):
        UpstreamIdentity(
            upstream_name="a fixture",
            upstream_locator="C:\\artifacts\\fixture",
            exact_version="1.0.0",
        )


# ------------------------------------------------------ upstream modification


def test_the_ladder_prefers_a_wrapper_then_a_recipe_then_a_patch() -> None:
    assert (
        choose_modification_strategy(
            wrapper_is_sufficient=True, transformation_recipe_is_sufficient=True
        )
        is UpstreamModificationStrategy.WRAPPER_WITHOUT_UPSTREAM_MODIFICATION
    )
    assert (
        choose_modification_strategy(
            wrapper_is_sufficient=False, transformation_recipe_is_sufficient=True
        )
        is UpstreamModificationStrategy.PROJECT_OWNED_TRANSFORMATION_RECIPE
    )
    assert (
        choose_modification_strategy(
            wrapper_is_sufficient=False, transformation_recipe_is_sufficient=False
        )
        is UpstreamModificationStrategy.LOCAL_PATCH
    )


def test_a_transformation_records_two_digests_and_no_source() -> None:
    transformation = transformation_over_bytes(
        b"import torch\n",
        b"import torch  # patched\n",
        transformation_id="fixture_transformation",
        strategy=UpstreamModificationStrategy.PROJECT_OWNED_TRANSFORMATION_RECIPE,
        subject="a fixture module",
        transformation_rule="append a marker comment to the import line",
        reason="a fixture, so that the recipe shape is exercised",
    )
    plain = {
        field: getattr(transformation, field)
        for field in transformation.__dataclass_fields__
    }
    assert "torch" not in str(plain["transformation_rule"])
    assert plain["preimage_sha256"] != plain["postimage_sha256"]
    assert (
        plain["classification"] is TransformationClassification.INTEGRATION_ONLY
    )


def test_a_wrapper_has_no_transformation_to_record() -> None:
    with pytest.raises(UpstreamTransformationError, match="no preimage"):
        record_transformation(
            transformation_id="fixture_wrapper",
            strategy=(
                UpstreamModificationStrategy.WRAPPER_WITHOUT_UPSTREAM_MODIFICATION
            ),
            subject="a fixture module",
            preimage_sha256="a" * 64,
            postimage_sha256="b" * 64,
            transformation_rule="none",
            reason="a wrapper recorded as a transformation",
        )


def test_a_transformation_that_changed_nothing_is_refused() -> None:
    with pytest.raises(UpstreamTransformationError, match="nothing was transformed"):
        record_transformation(
            transformation_id="fixture_identity",
            strategy=UpstreamModificationStrategy.LOCAL_PATCH,
            subject="a fixture module",
            preimage_sha256="a" * 64,
            postimage_sha256="a" * 64,
            transformation_rule="do nothing",
            reason="a patch that patched nothing",
        )


def test_a_behaviour_affecting_transformation_is_refused() -> None:
    behaviour = record_transformation(
        transformation_id="fixture_behaviour",
        strategy=UpstreamModificationStrategy.LOCAL_PATCH,
        subject="a fixture module",
        preimage_sha256="a" * 64,
        postimage_sha256="b" * 64,
        transformation_rule="change the interpolation used when resizing",
        reason="a change that would move a score",
        classification=TransformationClassification.BEHAVIOUR_AFFECTING,
    )
    with pytest.raises(UpstreamTransformationError, match="ADR before it is a commit"):
        require_integration_only((behaviour,))
