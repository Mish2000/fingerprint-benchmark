"""Frozen, candidate-specific Stage 8A inspection conclusions.

The generic qualification engine lives in :mod:`qualification`.  This module
contains the deliberately small amount of candidate-specific knowledge that
turns the three acquisition manifests into commit-4 reports.  It never imports
an ML framework, executes third-party serialization, downloads an artefact, or
opens any benchmark workspace/evidence from earlier stages.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from fpbench.core.errors import QualificationError
from fpbench.core.modern_matcher_models import (
    STAGE8A_SCHEMA_VERSION,
    CandidateArtifactManifest,
    CandidateDeterminismReport,
    CandidateOperationalReport,
    CandidatePreprocessingProfile,
    CandidateQualificationReport,
    CandidateRepresentationProfile,
    CandidateScoreProfile,
    DecisionPath,
    DecisionPathKind,
    DevelopmentCohortKind,
    ModernMatcherCandidate,
    ModernMatcherCandidateRegistry,
    PreprocessingOperation,
    QualificationGate,
    RepresentationBranch,
    ThresholdSourceKind,
)
from fpbench.modern_matchers.qualification import (
    QualificationFacts,
    build_qualification_report,
)

__all__ = ["QUALIFIED_UTC", "build_frozen_qualification_reports"]

QUALIFIED_UTC = "2026-08-04T18:00:00+03:00"


def _not_tested(candidate_id: str) -> CandidateDeterminismReport:
    return CandidateDeterminismReport.create(
        schema_version=STAGE8A_SCHEMA_VERSION,
        report_id=f"determinism_{candidate_id}",
        tested=False,
        runtime_kind=None,
        runtime_version=None,
        driver_version=None,
        device_class=None,
        repeated_extraction_equal=None,
        repeated_comparison_equal=None,
        single_image_vs_batch_equal=None,
        process_restart_equal=None,
        process_restart_representation_equal=None,
        input_order_equal=None,
        bitwise_equal=None,
        numeric_tolerance=None,
        maximum_observed_score_drift=None,
        within_predeclared_tolerance=None,
        nondeterminism_reason="static inspection failed before execution was permitted",
        runtime_restrictions=("no runtime was certified",),
        decision_safe=None,
        inspected_utc=QUALIFIED_UTC,
    )


def _not_measured(candidate_id: str) -> CandidateOperationalReport:
    return CandidateOperationalReport.create(
        schema_version=STAGE8A_SCHEMA_VERSION,
        report_id=f"operational_{candidate_id}",
        measured=False,
        startup_seconds=None,
        model_load_seconds=None,
        extraction_seconds=None,
        comparison_seconds=None,
        peak_ram_bytes=None,
        peak_vram_bytes=None,
        artifact_disk_bytes=None,
        projected_12000_extractions_seconds=None,
        projected_6000_comparisons_seconds=None,
        max_projected_12000_extractions_seconds=None,
        max_projected_6000_comparisons_seconds=None,
        max_peak_ram_bytes=None,
        max_peak_vram_bytes=None,
        max_artifact_disk_bytes=None,
        operationally_feasible=None,
        measurement_scope=(
            "not measured: failed static inspection forbade fixture execution; "
            "no biometric performance claim"
        ),
        inspected_utc=QUALIFIED_UTC,
    )


def _no_decision_path() -> DecisionPath:
    return DecisionPath.create(
        schema_version=STAGE8A_SCHEMA_VERSION,
        kind=DecisionPathKind.NONE,
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


def _evidence(reference: str) -> Mapping[str, tuple[str, ...]]:
    return {gate.value: (reference,) for gate in QualificationGate}


def _paper_only_facts(
    *,
    paper_year: int,
    evidence_reference: str,
    extra_failures: Mapping[str, tuple[str, ...]],
    external_minutiae_in_identity: bool,
) -> QualificationFacts:
    return QualificationFacts.create(
        schema_version=STAGE8A_SCHEMA_VERSION,
        paper_only=True,
        inference_code_present=False,
        imports_resolvable=False,
        model_constructor_present=False,
        weights_present=False,
        weights_identity_complete=False,
        weights_architecture_identifiable=False,
        preprocessing_complete=False,
        preprocessing_dataset_independent=False,
        representation_complete=False,
        comparator_present=False,
        raw_score_exposed=False,
        raw_score_finite=False,
        hidden_threshold=False,
        decision_path_valid=False,
        self_independent=False,
        determinism_within_tolerance=False,
        online_runtime_dependency=False,
        offline_bundle_complete=False,
        offline_execution_proven=False,
        process_restart_isolated=False,
        architecture_fit=False,
        operationally_feasible=False,
        external_minutiae_in_candidate_identity=external_minutiae_in_identity,
        reweighting_uses_evaluation_cohort=False,
        execution_attempted=False,
        smoke_passed=False,
        contract_passed=False,
        extra_gate_failures=extra_failures,
        gate_evidence=_evidence(evidence_reference),
        algorithm_completeness_rank=0,
        external_components_required=1,
        runtime_complexity_rank=0,
        estimated_adapter_lines=0,
        diversity_rank=0,
        paper_year=paper_year,
    )


def _component(manifest: CandidateArtifactManifest, role: str):
    matches = tuple(item for item in manifest.components if item.role == role)
    if len(matches) != 1:
        raise QualificationError(
            f"{manifest.candidate_id}: expected exactly one {role!r} component"
        )
    return matches[0]


def _operation(
    *,
    operation_id: str,
    action: str,
    component,
) -> PreprocessingOperation:
    if component.sha256 is None or component.source_locator is None:
        raise QualificationError(
            f"{component.component_id}: preprocessing source lacks a public identity"
        )
    return PreprocessingOperation.create(
        schema_version=STAGE8A_SCHEMA_VERSION,
        operation_id=operation_id,
        action=action,
        upstream_source_kind="pinned upstream source code",
        upstream_source_reference=component.source_locator,
        source_fingerprint=component.sha256,
    )


def _flx_preprocessing(
    manifest: CandidateArtifactManifest,
) -> CandidatePreprocessingProfile:
    loader = _component(manifest, "image_loader")
    helpers = _component(manifest, "preprocessing")
    architecture = _component(manifest, "model_constructor")
    operations = (
        _operation(
            operation_id="grayscale_conversion",
            action="OpenCV IMREAD_GRAYSCALE in each named dataset loader",
            component=loader,
        ),
        _operation(
            operation_id="polarity",
            action="no explicit polarity transform in the inspected loaders",
            component=loader,
        ),
        _operation(
            operation_id="crop",
            action="dataset-specific: SFinGe removes 32 rows; MCYT optical center-crops a fixed ROI; other loaders do not crop",
            component=loader,
        ),
        _operation(
            operation_id="padding",
            action="symmetric square padding; the inspected benchmark loaders pass white fill 1.0",
            component=helpers,
        ),
        _operation(
            operation_id="resize",
            action="torchvision functional resize to 299 by 299 with antialias enabled",
            component=helpers,
        ),
        _operation(
            operation_id="interpolation",
            action="torchvision resize default interpolation; exact behavior is not locked because dependency versions are unpinned",
            component=helpers,
        ),
        _operation(
            operation_id="alignment",
            action="no generic inference alignment operation is selected",
            component=loader,
        ),
        _operation(
            operation_id="localization",
            action="absent from the identified checkpoint variant and its constructor",
            component=architecture,
        ),
        _operation(
            operation_id="contrast_transformation",
            action="no inference-time contrast transform in the inspected loaders",
            component=loader,
        ),
        _operation(
            operation_id="normalization",
            action="torchvision to_tensor conversion only; no further mean or variance normalization",
            component=helpers,
        ),
        _operation(
            operation_id="channel_replication",
            action="none; the model stem expects one grayscale channel",
            component=architecture,
        ),
        _operation(
            operation_id="tensor_layout",
            action="torchvision to_tensor produces channel-height-width layout",
            component=helpers,
        ),
        _operation(
            operation_id="numeric_dtype",
            action="torchvision to_tensor floating output; exact library version and resulting runtime are not locked",
            component=helpers,
        ),
        _operation(
            operation_id="value_range",
            action="uint8 inputs are scaled by torchvision to_tensor to the nominal zero-to-one range",
            component=helpers,
        ),
    )
    return CandidatePreprocessingProfile.create(
        schema_version=STAGE8A_SCHEMA_VERSION,
        profile_id="flx_checkpoint_preprocessing_inspection_v1",
        operations=operations,
        dataset_independent=False,
        subject_independent=True,
        label_independent=True,
        canonical_png_to_tensor_complete=False,
    )


def _flx_representation() -> CandidateRepresentationProfile:
    texture = RepresentationBranch.create(
        schema_version=STAGE8A_SCHEMA_VERSION,
        branch_id="texture",
        kind="texture embedding",
        shape=(256,),
        included_in_final_score=True,
        combination_rule="concatenated before the one-to-one dot-product comparator",
    )
    minutia = RepresentationBranch.create(
        schema_version=STAGE8A_SCHEMA_VERSION,
        branch_id="minutia",
        kind="learned minutia embedding; no external minutiae detector at inference",
        shape=(256,),
        included_in_final_score=True,
        combination_rule="concatenated before the one-to-one dot-product comparator",
    )
    return CandidateRepresentationProfile.create(
        schema_version=STAGE8A_SCHEMA_VERSION,
        profile_id="flx_deepprint_texminu_512_representation_v1",
        representation_kind="two-branch fixed-length learned embedding",
        representation_shape=(512,),
        representation_dtype="PyTorch floating tensor; exact runtime dtype not dynamically qualified",
        representation_normalization="independent L2 normalization of each 256-dimensional branch",
        fixed_length=True,
        branches=(texture, minutia),
        fusion_rule="concatenate texture then minutia; dot product sums the two branch similarities",
        pose_information_required=False,
        pose_handling=(
            "no pose input is required by the identified no-localization variant "
            "or its direct one-to-one comparator"
        ),
        complete=True,
    )


def _flx_score() -> CandidateScoreProfile:
    return CandidateScoreProfile.create(
        schema_version=STAGE8A_SCHEMA_VERSION,
        profile_id="flx_direct_pair_dot_product_v1",
        compare_api="CosineSimilarityMatcher.similarity(sample1, sample2)",
        similarity_function="NumPy dot product over the concatenated, independently L2-normalized branches",
        score_direction="higher_is_more_similar",
        score_range="nominal [-2, 2], the sum of two branch cosine similarities",
        score_minimum="-2",
        score_maximum="2",
        normalization="each 256-dimensional branch is L2-normalized before concatenation",
        symmetric=True,
        fusion="sum of texture and minutia branch dot products",
        reweighting=(
            "none; both independently normalized branches retain equal unit "
            "contribution and no evaluation-cohort weights are introduced"
        ),
        realignment_trigger="none; no localization branch and no comparator realignment",
        fallback_behavior="none in the direct one-to-one API; its vectorized sibling is not the selected pair API",
        returns_finite_numeric_raw_score=False,
        hidden_threshold=False,
        complete=False,
    )


def _flx_facts(manifest: CandidateArtifactManifest) -> QualificationFacts:
    reference = _component(manifest, "source_code").source_locator
    if reference is None:
        raise QualificationError("flx source component has no public locator")
    return QualificationFacts.create(
        schema_version=STAGE8A_SCHEMA_VERSION,
        paper_only=False,
        inference_code_present=True,
        imports_resolvable=False,
        model_constructor_present=True,
        weights_present=True,
        weights_identity_complete=False,
        weights_architecture_identifiable=True,
        preprocessing_complete=False,
        preprocessing_dataset_independent=False,
        representation_complete=True,
        comparator_present=True,
        raw_score_exposed=True,
        raw_score_finite=False,
        hidden_threshold=False,
        decision_path_valid=False,
        self_independent=False,
        determinism_within_tolerance=False,
        online_runtime_dependency=False,
        offline_bundle_complete=False,
        offline_execution_proven=False,
        process_restart_isolated=False,
        architecture_fit=True,
        operationally_feasible=False,
        external_minutiae_in_candidate_identity=True,
        reweighting_uses_evaluation_cohort=False,
        execution_attempted=False,
        smoke_passed=False,
        contract_passed=False,
        extra_gate_failures={
            QualificationGate.COMPLETE_INFERENCE.value: (
                "DEPENDENCY_VERSIONS_NOT_LOCKED",
            ),
            QualificationGate.EXACT_WEIGHTS.value: (
                "CHECKPOINT_TRAINING_PROVENANCE_CONFLICT",
            ),
            QualificationGate.COMPLETE_PREPROCESSING.value: (
                "GENERIC_CANONICAL_PNG_ROUTE_NOT_DEFINED",
            ),
            QualificationGate.FINITE_RAW_SCORE.value: (
                "RAW_SCORE_RUNTIME_NOT_EXECUTED",
            ),
            QualificationGate.DECISION_PATH.value: (
                "CHECKPOINT_BOUND_THRESHOLD_NOT_DOCUMENTED",
            ),
            QualificationGate.INDEPENDENT_SELF.value: (
                "SELF_CONTRACT_NOT_EXECUTED",
            ),
            QualificationGate.OFFLINE_OPERATION.value: (
                "DEPENDENCY_LOCK_MISSING",
            ),
            QualificationGate.LICENSE_AND_PUBLICATION.value: (
                "WEIGHTS_HOLD_AND_EXECUTE_PERMISSION_UNESTABLISHED",
            ),
        },
        gate_evidence=_evidence(reference),
        algorithm_completeness_rank=6,
        external_components_required=2,
        runtime_complexity_rank=3,
        estimated_adapter_lines=0,
        diversity_rank=0,
        paper_year=2023,
    )


def _build_one(
    *,
    candidate: ModernMatcherCandidate,
    registry: ModernMatcherCandidateRegistry,
    manifest: CandidateArtifactManifest,
) -> CandidateQualificationReport:
    common = {
        "candidate": candidate,
        "registry_fingerprint": registry.fingerprint,
        "manifest": manifest,
        "determinism": _not_tested(candidate.candidate_id),
        "operational": _not_measured(candidate.candidate_id),
        "decision_path": _no_decision_path(),
        "runtime_probe": None,
        "qualified_utc": QUALIFIED_UTC,
    }
    if candidate.candidate_id == "afr_net_official_artifact":
        facts = _paper_only_facts(
            paper_year=2023,
            evidence_reference=candidate.paper_url,
            external_minutiae_in_identity=True,
            extra_failures={
                QualificationGate.COMPLETE_INFERENCE.value: (
                    "AFR_NET_OFFICIAL_ARTIFACT_NOT_ACQUIRED",
                    "AFR_NET_LOCAL_REALIGNMENT_IMPLEMENTATION_MISSING",
                ),
                QualificationGate.EXACT_WEIGHTS.value: (
                    "AFR_NET_GLOBAL_AND_ATTENTION_CHECKPOINTS_MISSING",
                ),
                QualificationGate.FINITE_RAW_SCORE.value: (
                    "AFR_NET_FINAL_FUSION_AND_SCORE_FORMULA_ARTIFACT_MISSING",
                ),
            },
        )
        return build_qualification_report(
            **common,
            facts=facts,
            preprocessing=None,
            representation=None,
            score=None,
        )
    if candidate.candidate_id == "mgvit_official_artifact":
        facts = _paper_only_facts(
            paper_year=2022,
            evidence_reference=candidate.paper_url,
            external_minutiae_in_identity=False,
            extra_failures={
                QualificationGate.COMPLETE_INFERENCE.value: (
                    "MGVIT_PAPER_CODE_LINK_IS_PLACEHOLDER",
                    "MGVIT_MINUTIAE_MAP_COMPONENT_MISSING",
                ),
                QualificationGate.EXACT_WEIGHTS.value: (
                    "MGVIT_EXACT_CHECKPOINT_MISSING",
                ),
                QualificationGate.ARCHITECTURE_FIT.value: (
                    "MINDTCT_SUBSTITUTION_NOT_AUTHORIZED",
                ),
            },
        )
        return build_qualification_report(
            **common,
            facts=facts,
            preprocessing=None,
            representation=None,
            score=None,
        )
    if candidate.candidate_id == "flx_fixed_length_extractor":
        return build_qualification_report(
            **common,
            facts=_flx_facts(manifest),
            preprocessing=_flx_preprocessing(manifest),
            representation=_flx_representation(),
            score=_flx_score(),
        )
    raise QualificationError(
        f"{candidate.candidate_id}: no frozen Stage 8A inspector exists"
    )


def build_frozen_qualification_reports(
    *,
    registry: ModernMatcherCandidateRegistry,
    manifests: Sequence[CandidateArtifactManifest],
) -> tuple[CandidateQualificationReport, ...]:
    """Re-derive one report for each candidate in registry order."""
    by_id = {manifest.candidate_id: manifest for manifest in manifests}
    if len(by_id) != len(tuple(manifests)):
        raise QualificationError("each candidate must have exactly one acquisition manifest")
    candidate_ids = {candidate.candidate_id for candidate in registry.candidates}
    if set(by_id) != candidate_ids:
        raise QualificationError(
            "acquisition manifests must cover the frozen registry exactly; "
            f"missing={sorted(candidate_ids - set(by_id))}, "
            f"extra={sorted(set(by_id) - candidate_ids)}"
        )
    reports = []
    for candidate in registry.candidates:
        manifest = by_id[candidate.candidate_id]
        if manifest.registry_fingerprint != registry.fingerprint:
            raise QualificationError(
                f"{candidate.candidate_id}: manifest names another registry"
            )
        if manifest.candidate_fingerprint != candidate.fingerprint:
            raise QualificationError(
                f"{candidate.candidate_id}: manifest names another candidate identity"
            )
        reports.append(
            _build_one(candidate=candidate, registry=registry, manifest=manifest)
        )
    return tuple(reports)
