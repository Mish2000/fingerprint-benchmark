"""Small deterministic Stage 8A worlds for unit and contract tests.

The objects in this module are deliberately synthetic.  They describe tiny
content-addressed byte files and generated facts, not a real matcher and not a
biometric result.  Keeping the builders here makes the tests state the one
claim they are changing instead of repeating the entire Stage 8A evidence
schema in every test.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from fpbench.core.modern_matcher_models import (
    STAGE8A_SCHEMA_VERSION,
    CandidateArtifactManifest,
    CandidateComponent,
    CandidateDeterminismReport,
    CandidateLicenseRecord,
    CandidateOperationalReport,
    CandidatePreprocessingProfile,
    CandidateQualificationReport,
    CandidateRepresentationProfile,
    CandidateScoreProfile,
    CandidateTier,
    ComponentKind,
    DecisionPath,
    DecisionPathKind,
    DevelopmentCohortKind,
    ImplementationOrigin,
    LicenseConclusion,
    LicenseScope,
    ModernMatcherCandidate,
    ModernMatcherCandidateRegistry,
    ModernMatcherSelectionDecision,
    PreprocessingOperation,
    QualificationGate,
    RepresentationBranch,
    SelectionPolicy,
    Stage8AFinalization,
    ThresholdSourceKind,
)
from fpbench.core.serialization import stable_hash, write_json
from fpbench.modern_matchers.acquisition import load_acquisition_manifests
from fpbench.modern_matchers.finalization import build_stage8a_finalization
from fpbench.modern_matchers.policy import TIE_BREAKERS, load_selection_policy
from fpbench.modern_matchers.probe import RuntimeProbeResult
from fpbench.modern_matchers.qualification import (
    QualificationFacts,
    build_qualification_report,
)
from fpbench.modern_matchers.selection import select_modern_matcher
from fpbench.modern_matchers.registry import load_candidate_registry
from fpbench.storage.modern_matcher_store import Stage8AEvidenceStore

NOW = "2026-08-04T12:00:00+00:00"
COMMIT = "a" * 40
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def digest(label: str) -> str:
    return stable_hash({"stage8a-test": label}, length=64)


def rebuild(value: Any, /, **changes: Any) -> Any:
    """Recreate a fingerprinted record after changing semantic claims."""
    claims = {
        item.name: getattr(value, item.name)
        for item in dataclasses.fields(value)
        if item.name != "fingerprint"
    }
    claims.update(changes)
    return type(value).create(**claims)


def make_candidate(
    candidate_id: str = "candidate_alpha",
    *,
    tier: CandidateTier = CandidateTier.A,
    origin: ImplementationOrigin = ImplementationOrigin.OFFICIAL,
    expected_components: Sequence[str] = (
        "source_code",
        "checkpoint",
        "upstream_documentation",
    ),
) -> ModernMatcherCandidate:
    claimed = f"Claimed {candidate_id}"
    actual = (
        f"Independent {candidate_id} implementation"
        if origin is ImplementationOrigin.INDEPENDENT_REIMPLEMENTATION
        else f"Official {candidate_id} implementation"
    )
    return ModernMatcherCandidate.create(
        schema_version=STAGE8A_SCHEMA_VERSION,
        candidate_id=candidate_id,
        tier=tier,
        claimed_algorithm_name=claimed,
        actual_implementation_name=actual,
        paper_citation=f"Synthetic citation for {candidate_id}",
        paper_url=f"https://example.invalid/papers/{candidate_id}",
        implementation_authors=("Fixture Author",),
        relationship_to_original_paper=(
            "independent reimplementation"
            if origin is ImplementationOrigin.INDEPENDENT_REIMPLEMENTATION
            else "official implementation"
        ),
        implementation_origin=origin,
        expected_components=tuple(expected_components),
        known_missing_components=(),
        acquisition_method="fixture-only local acquisition",
    )


def make_registry(
    candidates: Sequence[ModernMatcherCandidate] | None = None,
) -> ModernMatcherCandidateRegistry:
    if candidates is None:
        candidates = (
            make_candidate("afr_net_official_artifact", tier=CandidateTier.A),
            make_candidate("mgvit_official_artifact", tier=CandidateTier.B),
            make_candidate(
                "flx_fixed_length_extractor",
                tier=CandidateTier.C,
                origin=ImplementationOrigin.INDEPENDENT_REIMPLEMENTATION,
            ),
        )
    return ModernMatcherCandidateRegistry.create(
        schema_version=STAGE8A_SCHEMA_VERSION,
        candidate_registry_version="stage8a_candidates_v1",
        frozen_before_qualification=True,
        candidates=tuple(candidates),
        reserve_candidate_id="id3_finger_sdk",
        reserve_activation="outside Stage 8A; explicit new stage required",
    )


def make_license(
    scope: LicenseScope,
    *,
    conclusion: LicenseConclusion = LicenseConclusion.CLEAR,
    suffix: str = "fixture",
) -> CandidateLicenseRecord:
    clear = conclusion is LicenseConclusion.CLEAR
    return CandidateLicenseRecord.create(
        schema_version=STAGE8A_SCHEMA_VERSION,
        record_id=f"{scope.value}_{suffix}",
        scope=scope,
        subject=f"{scope.value} bytes",
        license_name="Fixture permissive licence" if clear else None,
        spdx_identifier="MIT" if clear else None,
        license_document_sha256=digest(f"licence-{scope.value}-{suffix}"),
        license_document_url="https://example.invalid/LICENSE",
        conclusion=conclusion,
        academic_benchmark_allowed=True if clear else None,
        nist_image_processing_allowed=True if clear else None,
        cross_algorithm_comparison_allowed=True if clear else None,
        publish_counts_and_rates_allowed=True if clear else None,
        publish_metadata_and_hashes_allowed=True if clear else None,
        hold_and_execute_allowed=True if clear else None,
        redistribution_allowed=False,
        restrictions=(),
        evidence=("fixture licence text",),
    )


def make_component(
    component_id: str,
    *,
    kind: ComponentKind,
    role: str,
    license_fingerprint: str | None,
    filename: str | None = None,
    payload: bytes | None = None,
) -> CandidateComponent:
    payload = payload if payload is not None else f"{component_id}-bytes".encode()
    filename = filename or f"{component_id}.bin"
    checkpoint = kind is ComponentKind.CHECKPOINT
    return CandidateComponent.create(
        schema_version=STAGE8A_SCHEMA_VERSION,
        component_id=component_id,
        kind=kind,
        role=role,
        required=True,
        present=True,
        identity_established=True,
        locked_for_offline_use=True,
        filename=filename,
        sha256=__import__("hashlib").sha256(payload).hexdigest(),
        size_bytes=len(payload),
        format="fixture-checkpoint" if checkpoint else "fixture-archive",
        source_locator=f"fixture/{filename}",
        source_commit=COMMIT if not checkpoint else None,
        source_archive_sha256=None,
        model_variant="FixtureNet_512" if checkpoint else None,
        embedding_dimension=512 if checkpoint else None,
        training_provenance="synthetic fixture; no training" if checkpoint else None,
        license_record_fingerprint=license_fingerprint,
        notes=(),
    )


def make_manifest(
    candidate: ModernMatcherCandidate,
    registry: ModernMatcherCandidateRegistry,
    *,
    components: Sequence[CandidateComponent] | None = None,
    license_records: Sequence[CandidateLicenseRecord] | None = None,
    storage_reference: str | None = None,
) -> CandidateArtifactManifest:
    code_license = make_license(LicenseScope.SOURCE_CODE)
    weights_license = make_license(LicenseScope.WEIGHTS)
    third_party_license = make_license(LicenseScope.THIRD_PARTY)
    training_review = make_license(LicenseScope.TRAINING_RESTRICTIONS)
    if license_records is None:
        license_records = (
            code_license,
            weights_license,
            third_party_license,
            training_review,
        )
    else:
        by_scope = {record.scope: record for record in license_records}
        code_license = by_scope.get(LicenseScope.SOURCE_CODE, code_license)
        weights_license = by_scope.get(LicenseScope.WEIGHTS, weights_license)
    if components is None:
        components = (
            make_component(
                "source_bundle",
                kind=ComponentKind.SOURCE_CODE,
                role="source_code",
                license_fingerprint=code_license.fingerprint,
                payload=b"source-bundle",
            ),
            make_component(
                "model_checkpoint",
                kind=ComponentKind.CHECKPOINT,
                role="checkpoint",
                license_fingerprint=weights_license.fingerprint,
                payload=b"model-checkpoint",
            ),
            make_component(
                "threshold_documentation",
                kind=ComponentKind.UPSTREAM_DOCUMENTATION,
                role="upstream_documentation",
                license_fingerprint=None,
                payload=b"threshold-document",
            ),
        )
    return CandidateArtifactManifest.create(
        schema_version=STAGE8A_SCHEMA_VERSION,
        manifest_id=f"artifact_{candidate.candidate_id}",
        candidate_id=candidate.candidate_id,
        registry_fingerprint=registry.fingerprint,
        candidate_fingerprint=candidate.fingerprint,
        source_commit=COMMIT,
        source_archive_sha256=digest(f"source-archive-{candidate.candidate_id}"),
        components=tuple(components),
        license_records=tuple(license_records),
        storage_reference=storage_reference or candidate.candidate_id,
        acquisition_method="fixture-only local acquisition",
        acquired_utc=NOW,
    )


def make_preprocessing(
    *, dataset_independent: bool = True, complete: bool = True
) -> CandidatePreprocessingProfile:
    operation_ids = (
        "grayscale_conversion",
        "polarity",
        "crop",
        "padding",
        "resize",
        "interpolation",
        "alignment",
        "localization",
        "contrast_transformation",
        "normalization",
        "channel_replication",
        "tensor_layout",
        "numeric_dtype",
        "value_range",
    )
    operations = tuple(
        PreprocessingOperation.create(
            schema_version=STAGE8A_SCHEMA_VERSION,
            operation_id=operation_id,
            action=f"documented fixture action for {operation_id}",
            upstream_source_kind="upstream_code",
            upstream_source_reference=f"preprocess.py:{index + 1}",
            source_fingerprint=digest(f"preprocess-source-{operation_id}"),
        )
        for index, operation_id in enumerate(operation_ids)
    )
    if not complete:
        operations = operations[:-1]
    return CandidatePreprocessingProfile.create(
        schema_version=STAGE8A_SCHEMA_VERSION,
        profile_id="fixture_preprocessing_v1",
        operations=operations,
        dataset_independent=dataset_independent,
        subject_independent=True,
        label_independent=True,
        canonical_png_to_tensor_complete=complete,
    )


def make_representation(*, complete: bool = True) -> CandidateRepresentationProfile:
    branch = RepresentationBranch.create(
        schema_version=STAGE8A_SCHEMA_VERSION,
        branch_id="texture",
        kind="texture embedding",
        shape=(512,),
        included_in_final_score=True,
        combination_rule="the sole branch is compared directly",
    )
    return CandidateRepresentationProfile.create(
        schema_version=STAGE8A_SCHEMA_VERSION,
        profile_id="fixture_representation_v1",
        representation_kind="fixed-length embedding",
        representation_shape=(512,),
        representation_dtype="float32",
        representation_normalization="upstream L2 normalization",
        fixed_length=True,
        branches=(branch,),
        fusion_rule="single scored texture branch",
        pose_information_required=False,
        pose_handling="no pose input or pose-conditioned comparator",
        complete=complete,
    )


def make_score(*, hidden_threshold: bool = False) -> CandidateScoreProfile:
    return CandidateScoreProfile.create(
        schema_version=STAGE8A_SCHEMA_VERSION,
        profile_id="fixture_score_v1",
        compare_api="compare(left_representation, right_representation) -> Decimal",
        similarity_function="upstream dot product",
        score_direction="higher_is_better",
        score_range="fixture range [-1, 1]",
        score_minimum="-1",
        score_maximum="1",
        normalization="representations normalized upstream; score unchanged",
        symmetric=True,
        fusion="single branch",
        reweighting="none; the upstream score is used unchanged",
        realignment_trigger="not applicable in this fixture",
        fallback_behavior="raise; never synthesize a score",
        returns_finite_numeric_raw_score=True,
        hidden_threshold=hidden_threshold,
        complete=not hidden_threshold,
    )


def make_determinism(*, tested: bool = True) -> CandidateDeterminismReport:
    return CandidateDeterminismReport.create(
        schema_version=STAGE8A_SCHEMA_VERSION,
        report_id="fixture_determinism_v1",
        tested=tested,
        runtime_kind="CPU" if tested else None,
        runtime_version="fixture-runtime-1" if tested else None,
        driver_version=None,
        device_class=None,
        repeated_extraction_equal=True if tested else None,
        repeated_comparison_equal=True if tested else None,
        single_image_vs_batch_equal=True if tested else None,
        process_restart_equal=True if tested else None,
        process_restart_representation_equal=True if tested else None,
        input_order_equal=True if tested else None,
        bitwise_equal=True if tested else None,
        numeric_tolerance=None,
        maximum_observed_score_drift=None,
        within_predeclared_tolerance=True if tested else None,
        nondeterminism_reason=None,
        runtime_restrictions=(),
        decision_safe=True if tested else None,
        inspected_utc=NOW,
    )


def make_operational(*, measured: bool = True) -> CandidateOperationalReport:
    return CandidateOperationalReport.create(
        schema_version=STAGE8A_SCHEMA_VERSION,
        report_id="fixture_operational_v1",
        measured=measured,
        startup_seconds="0.01" if measured else None,
        model_load_seconds="0.02" if measured else None,
        extraction_seconds="0.03" if measured else None,
        comparison_seconds="0.001" if measured else None,
        peak_ram_bytes=1024 if measured else None,
        peak_vram_bytes=0 if measured else None,
        artifact_disk_bytes=256 if measured else None,
        projected_12000_extractions_seconds="360" if measured else None,
        projected_6000_comparisons_seconds="6" if measured else None,
        max_projected_12000_extractions_seconds="86400" if measured else None,
        max_projected_6000_comparisons_seconds="21600" if measured else None,
        max_peak_ram_bytes=34_359_738_368 if measured else None,
        max_peak_vram_bytes=25_769_803_776 if measured else None,
        max_artifact_disk_bytes=10_737_418_240 if measured else None,
        operationally_feasible=True if measured else None,
        measurement_scope="synthetic fixtures only; no biometric performance claim",
        inspected_utc=NOW,
    )


def make_runtime_probe(
    determinism: CandidateDeterminismReport,
    operational: CandidateOperationalReport,
    *,
    candidate_fingerprint: str,
    artifact_manifest_fingerprint: str,
    process_restart_isolated: bool = True,
    offline_execution_proven: bool = True,
) -> RuntimeProbeResult:
    isolated = process_restart_isolated and offline_execution_proven
    left_representation_hash = digest("left-representation")
    right_representation_hash = digest("right-representation")
    left_score_hash = digest("left-score")
    return RuntimeProbeResult.create(
        schema_version=STAGE8A_SCHEMA_VERSION,
        candidate_fingerprint=candidate_fingerprint,
        artifact_manifest_fingerprint=artifact_manifest_fingerprint,
        left_fixture_hash=digest("left-fixture"),
        right_fixture_hash=digest("right-fixture"),
        left_representation_hash=left_representation_hash,
        right_representation_hash=right_representation_hash,
        repeated_self_representation_hash=(
            left_representation_hash
            if determinism.repeated_extraction_equal
            else digest("repeated-extraction-drift")
        ),
        repeated_left_representation_hash=(
            left_representation_hash
            if determinism.repeated_extraction_equal
            else digest("repeated-left-drift")
        ),
        batch_left_representation_hash=(
            left_representation_hash
            if determinism.single_image_vs_batch_equal
            else digest("batch-left-drift")
        ),
        batch_right_representation_hash=(
            right_representation_hash
            if determinism.single_image_vs_batch_equal
            else digest("batch-right-drift")
        ),
        restarted_left_representation_hash=(
            left_representation_hash
            if determinism.process_restart_representation_equal
            else digest("restart-left-drift")
        ),
        restarted_right_representation_hash=(
            right_representation_hash
            if determinism.process_restart_representation_equal
            else digest("restart-right-drift")
        ),
        left_score_hash=left_score_hash,
        reverse_score_hash=(
            left_score_hash
            if determinism.input_order_equal
            else digest("reverse-score-drift")
        ),
        repeated_score_hash=(
            left_score_hash
            if determinism.repeated_comparison_equal
            else digest("repeated-score-drift")
        ),
        restarted_score_hash=(
            left_score_hash
            if determinism.process_restart_equal
            else digest("restart-score-drift")
        ),
        extraction_calls=4,
        comparison_calls=3,
        no_representation_persistence=True,
        process_restart_isolated=process_restart_isolated,
        offline_execution_proven=offline_execution_proven,
        isolation_evidence_fingerprint=(
            digest("os-isolation-attestation") if isolated else None
        ),
        determinism_report=determinism,
        operational_report=operational,
    )


def make_decision_path(
    kind: DecisionPathKind = DecisionPathKind.DOCUMENTED_CHECKPOINT_THRESHOLD,
    *,
    checkpoint_fingerprint: str | None = None,
) -> DecisionPath:
    if kind is DecisionPathKind.NONE:
        return DecisionPath.create(
            schema_version=STAGE8A_SCHEMA_VERSION,
            kind=kind,
            documented_threshold=None,
            threshold_source=None,
            threshold_source_fingerprint=None,
            threshold_source_kind=ThresholdSourceKind.NONE,
            checkpoint_fingerprint=None,
            development_cohort=None,
            development_cohort_kind=DevelopmentCohortKind.NONE,
            calibration_protocol_fingerprint=None,
            cohort_is_independent_of_evaluation=False,
            legally_and_practically_available=False,
        )
    if kind is DecisionPathKind.EXTERNAL_DEVELOPMENT_CALIBRATION:
        return DecisionPath.create(
            schema_version=STAGE8A_SCHEMA_VERSION,
            kind=kind,
            documented_threshold=None,
            threshold_source=None,
            threshold_source_fingerprint=None,
            threshold_source_kind=ThresholdSourceKind.NONE,
            checkpoint_fingerprint=None,
            development_cohort="independent_fixture_development_cohort",
            development_cohort_kind=DevelopmentCohortKind.INDEPENDENT_EXTERNAL,
            calibration_protocol_fingerprint=digest("calibration-protocol"),
            cohort_is_independent_of_evaluation=True,
            legally_and_practically_available=True,
        )
    return DecisionPath.create(
        schema_version=STAGE8A_SCHEMA_VERSION,
        kind=kind,
        documented_threshold="0.5",
        threshold_source="upstream checkpoint documentation",
        threshold_source_fingerprint=__import__("hashlib").sha256(
            b"threshold-document"
        ).hexdigest(),
        threshold_source_kind=(
            ThresholdSourceKind.UPSTREAM_DOCUMENTED_CHECKPOINT_THRESHOLD
        ),
        checkpoint_fingerprint=(
            checkpoint_fingerprint or digest("checkpoint-threshold-binding")
        ),
        development_cohort=None,
        development_cohort_kind=DevelopmentCohortKind.NONE,
        calibration_protocol_fingerprint=None,
        cohort_is_independent_of_evaluation=False,
        legally_and_practically_available=False,
    )


def make_facts(**overrides: Any) -> QualificationFacts:
    claims: dict[str, Any] = {
        "schema_version": STAGE8A_SCHEMA_VERSION,
        "paper_only": False,
        "inference_code_present": True,
        "imports_resolvable": True,
        "model_constructor_present": True,
        "weights_present": True,
        "weights_identity_complete": True,
        "weights_architecture_identifiable": True,
        "preprocessing_complete": True,
        "preprocessing_dataset_independent": True,
        "representation_complete": True,
        "comparator_present": True,
        "raw_score_exposed": True,
        "raw_score_finite": True,
        "hidden_threshold": False,
        "decision_path_valid": True,
        "self_independent": True,
        "determinism_within_tolerance": True,
        "online_runtime_dependency": False,
        "offline_bundle_complete": True,
        "offline_execution_proven": True,
        "process_restart_isolated": True,
        "architecture_fit": True,
        "operationally_feasible": True,
        "external_minutiae_in_candidate_identity": True,
        "reweighting_uses_evaluation_cohort": False,
        "execution_attempted": True,
        "smoke_passed": True,
        "contract_passed": True,
        "extra_gate_failures": {},
        "gate_evidence": {
            gate.value: (f"sha256:{digest('gate-evidence-' + gate.value)}",)
            for gate in QualificationGate
        },
        "algorithm_completeness_rank": 100,
        "external_components_required": 0,
        "runtime_complexity_rank": 1,
        "estimated_adapter_lines": 10,
        "diversity_rank": 5,
        "paper_year": 2025,
    }
    claims.update(overrides)
    return QualificationFacts.create(**claims)


_DEFAULT = object()


def make_report(
    candidate: ModernMatcherCandidate,
    registry: ModernMatcherCandidateRegistry,
    *,
    facts: QualificationFacts | None = None,
    manifest: CandidateArtifactManifest | None = None,
    preprocessing: CandidatePreprocessingProfile | None | object = _DEFAULT,
    representation: CandidateRepresentationProfile | None | object = _DEFAULT,
    score: CandidateScoreProfile | None | object = _DEFAULT,
    determinism: CandidateDeterminismReport | None = None,
    operational: CandidateOperationalReport | None = None,
    decision_path: DecisionPath | None = None,
    runtime_probe_override: RuntimeProbeResult | object = _DEFAULT,
) -> CandidateQualificationReport:
    facts = facts or make_facts()
    manifest = manifest or make_manifest(candidate, registry)
    preprocessing = make_preprocessing() if preprocessing is _DEFAULT else preprocessing
    representation = make_representation() if representation is _DEFAULT else representation
    score = make_score() if score is _DEFAULT else score
    if decision_path is None:
        checkpoint = next(
            component
            for component in manifest.components
            if component.kind is ComponentKind.CHECKPOINT
        )
        decision_path = make_decision_path(
            checkpoint_fingerprint=checkpoint.fingerprint,
        )
    if decision_path.kind is DecisionPathKind.DOCUMENTED_CHECKPOINT_THRESHOLD:
        evidence = {
            gate: tuple(references)
            for gate, references in facts.gate_evidence.items()
        }
        evidence[QualificationGate.DECISION_PATH.value] = evidence.get(
            QualificationGate.DECISION_PATH.value, ()
        ) + (f"sha256:{decision_path.threshold_source_fingerprint}",)
        facts = rebuild(facts, gate_evidence=evidence)
    elif decision_path.kind is DecisionPathKind.EXTERNAL_DEVELOPMENT_CALIBRATION:
        evidence = {
            gate: tuple(references)
            for gate, references in facts.gate_evidence.items()
        }
        evidence[QualificationGate.DECISION_PATH.value] = evidence.get(
            QualificationGate.DECISION_PATH.value, ()
        ) + (f"sha256:{decision_path.calibration_protocol_fingerprint}",)
        facts = rebuild(facts, gate_evidence=evidence)
    determinism = determinism or make_determinism()
    operational = operational or make_operational()
    runtime_probe = None
    if facts.execution_attempted and facts.smoke_passed:
        runtime_probe = make_runtime_probe(
            determinism,
            operational,
            candidate_fingerprint=candidate.fingerprint,
            artifact_manifest_fingerprint=manifest.fingerprint,
            process_restart_isolated=facts.process_restart_isolated,
            offline_execution_proven=facts.offline_execution_proven,
        )
        if runtime_probe_override is not _DEFAULT:
            runtime_probe = runtime_probe_override  # type: ignore[assignment]
        evidence = {
            gate: tuple(references)
            for gate, references in facts.gate_evidence.items()
        }
        probe_reference = f"sha256:{runtime_probe.fingerprint}"
        for gate in (
            QualificationGate.FINITE_RAW_SCORE,
            QualificationGate.INDEPENDENT_SELF,
            QualificationGate.DETERMINISM,
            QualificationGate.OPERATIONAL_FEASIBILITY,
        ):
            evidence[gate.value] = evidence.get(gate.value, ()) + (
                probe_reference,
            )
        if runtime_probe.isolation_evidence_fingerprint is not None:
            evidence[QualificationGate.OFFLINE_OPERATION.value] = evidence.get(
                QualificationGate.OFFLINE_OPERATION.value, ()
            ) + (
                f"sha256:{runtime_probe.isolation_evidence_fingerprint}",
            )
        facts = rebuild(facts, gate_evidence=evidence)
    return build_qualification_report(
        candidate=candidate,
        registry_fingerprint=registry.fingerprint,
        manifest=manifest,
        facts=facts,
        preprocessing=preprocessing,  # type: ignore[arg-type]
        representation=representation,  # type: ignore[arg-type]
        score=score,  # type: ignore[arg-type]
        determinism=determinism,
        operational=operational,
        decision_path=decision_path,
        runtime_probe=runtime_probe,
        qualified_utc=NOW,
    )


def make_raw_only_report(
    candidate: ModernMatcherCandidate,
    registry: ModernMatcherCandidateRegistry,
) -> CandidateQualificationReport:
    return make_report(
        candidate,
        registry,
        facts=make_facts(decision_path_valid=False),
        decision_path=make_decision_path(DecisionPathKind.NONE),
    )


def make_blocked_report(
    candidate: ModernMatcherCandidate,
    registry: ModernMatcherCandidateRegistry,
) -> CandidateQualificationReport:
    return make_report(
        candidate,
        registry,
        facts=make_facts(architecture_fit=False),
    )


def make_policy() -> SelectionPolicy:
    return SelectionPolicy.create(
        schema_version=STAGE8A_SCHEMA_VERSION,
        policy_id="stage8a_gate_first_selection_v1",
        mandatory_gates=tuple(QualificationGate),
        tier_order=(CandidateTier.A, CandidateTier.B, CandidateTier.C),
        tie_breakers=TIE_BREAKERS,
        weighted_score_forbidden=True,
        unresolved_tie_action="fail_closed",
        max_projected_12000_extractions_seconds="86400",
        max_projected_6000_comparisons_seconds="21600",
        max_peak_ram_bytes=34_359_738_368,
        max_peak_vram_bytes=25_769_803_776,
        max_artifact_disk_bytes=10_737_418_240,
    )


@dataclass(frozen=True, slots=True)
class EvidenceWorld:
    repository_root: Path
    registry_config: Path
    policy_config: Path
    store: Stage8AEvidenceStore
    registry: ModernMatcherCandidateRegistry
    policy: SelectionPolicy
    manifests: tuple[CandidateArtifactManifest, ...]
    reports: tuple[CandidateQualificationReport, ...]
    decision: ModernMatcherSelectionDecision
    finalization: Stage8AFinalization


def build_evidence_world(root: Path, *, ready: bool = False) -> EvidenceWorld:
    root = Path(root)
    if ready:
        registry = make_registry()
        policy = make_policy()
        manifests = tuple(
            make_manifest(candidate, registry) for candidate in registry.candidates
        )
        reports = tuple(
            make_report(candidate, registry, manifest=manifest)
            for candidate, manifest in zip(registry.candidates, manifests, strict=True)
        )
    else:
        from fpbench.modern_matchers.assessments import (
            build_frozen_qualification_reports,
        )

        frozen_registry_config = (
            REPOSITORY_ROOT
            / "configs"
            / "modern-matchers"
            / "stage8a_candidates_v1.yaml"
        )
        frozen_policy_config = (
            REPOSITORY_ROOT
            / "configs"
            / "modern-matchers"
            / "stage8a_selection_policy_v1.yaml"
        )
        registry = load_candidate_registry(frozen_registry_config)
        policy = load_selection_policy(frozen_policy_config)
        manifests = load_acquisition_manifests(
            REPOSITORY_ROOT / "integrations" / "modern-matchers" / "manifests",
            registry=registry,
        )
        reports = build_frozen_qualification_reports(
            registry=registry,
            manifests=manifests,
        )

    configs = root / "configs" / "modern-matchers"
    registry_config = configs / "stage8a_candidates_v1.yaml"
    policy_config = configs / "stage8a_selection_policy_v1.yaml"
    write_json(registry_config, registry)
    write_json(policy_config, policy)
    manifest_dir = root / "integrations" / "modern-matchers" / "manifests"
    for manifest in manifests:
        write_json(manifest_dir / f"{manifest.candidate_id}.json", manifest)

    decision = select_modern_matcher(
        registry=registry,
        reports=reports,
        policy=policy,
        verifier_source_commit=COMMIT,
        decided_utc=NOW,
    )
    store = Stage8AEvidenceStore(root)
    store.ensure_registry(registry)
    for report in reports:
        store.ensure_qualification(report.candidate_id, report)
    store.ensure_selection(
        decision, tuple(candidate.candidate_id for candidate in registry.candidates)
    )
    store.readme_path.write_text(
        "# Synthetic Stage 8A evidence\n\nNo biometric performance claim.\n",
        encoding="utf-8",
    )
    finalization = build_stage8a_finalization(
        store=store,
        registry=registry,
        reports=reports,
        decision=decision,
        policy=policy,
        verifier_source_commit=COMMIT,
        verifier_source_tree_clean=True,
        created_utc=NOW,
        require_git_provenance=False,
    )
    store.ensure_finalization(
        finalization,
        tuple(candidate.candidate_id for candidate in registry.candidates),
    )
    return EvidenceWorld(
        repository_root=root,
        registry_config=registry_config,
        policy_config=policy_config,
        store=store,
        registry=registry,
        policy=policy,
        manifests=manifests,
        reports=reports,
        decision=decision,
        finalization=finalization,
    )


def write_artifact_files(
    root: Path,
    manifest: CandidateArtifactManifest,
    payloads: Mapping[str, bytes],
) -> None:
    assert manifest.storage_reference is not None
    base = Path(root) / manifest.storage_reference
    base.mkdir(parents=True, exist_ok=True)
    for component in manifest.components:
        if component.required:
            assert component.filename is not None
            (base / component.filename).write_bytes(payloads[component.component_id])
