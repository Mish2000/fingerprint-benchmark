"""Derive mandatory Stage 8A gates from inspection facts and artefact records."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from fpbench.core.errors import QualificationError
from fpbench.core.modern_matcher_models import (
    STAGE8A_SCHEMA_VERSION,
    CandidateArtifactManifest,
    CandidateDeterminismReport,
    CandidateLicenseRecord,
    CandidateOperationalReport,
    CandidatePreprocessingProfile,
    CandidateQualificationReport,
    CandidateRepresentationProfile,
    CandidateScoreProfile,
    ComponentKind,
    DecisionPath,
    DecisionPathKind,
    ImplementationOrigin,
    LicenseConclusion,
    LicenseScope,
    ModernMatcherCandidate,
    QualificationGate,
    QualificationGateResult,
    QualificationStatus,
    semantic_fingerprint,
)
from fpbench.modern_matchers.probe import RuntimeProbeResult

__all__ = [
    "QualificationFacts",
    "NEGATIVE_FAILURE_CODES",
    "derive_gate_results",
    "build_qualification_report",
]

NEGATIVE_FAILURE_CODES = frozenset(
    {
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
)


@dataclass(frozen=True, slots=True)
class QualificationFacts:
    """Static/dynamic observations supplied by a candidate-specific inspector.

    This is input to a pure gate derivation.  It carries no score, embedding,
    image, subject, dataset name, or label.  Candidate-specific facts are
    stable failure codes keyed by a mandatory gate, never a weighted score.
    """

    schema_version: str
    paper_only: bool
    inference_code_present: bool
    imports_resolvable: bool
    model_constructor_present: bool
    weights_present: bool
    weights_identity_complete: bool
    weights_architecture_identifiable: bool
    preprocessing_complete: bool
    preprocessing_dataset_independent: bool
    representation_complete: bool
    comparator_present: bool
    raw_score_exposed: bool
    raw_score_finite: bool
    hidden_threshold: bool
    decision_path_valid: bool
    self_independent: bool
    determinism_within_tolerance: bool
    online_runtime_dependency: bool
    offline_bundle_complete: bool
    offline_execution_proven: bool
    process_restart_isolated: bool
    architecture_fit: bool
    operationally_feasible: bool
    external_minutiae_in_candidate_identity: bool
    reweighting_uses_evaluation_cohort: bool
    execution_attempted: bool
    smoke_passed: bool
    contract_passed: bool
    extra_gate_failures: Mapping[str, tuple[str, ...]]
    gate_evidence: Mapping[str, tuple[str, ...]]
    algorithm_completeness_rank: int
    external_components_required: int
    runtime_complexity_rank: int
    estimated_adapter_lines: int
    diversity_rank: int
    paper_year: int
    fingerprint: str

    def __post_init__(self) -> None:
        if str(self.schema_version) != STAGE8A_SCHEMA_VERSION:
            raise ValueError("unsupported qualification facts schema version")
        for name in (
            "paper_only",
            "inference_code_present",
            "imports_resolvable",
            "model_constructor_present",
            "weights_present",
            "weights_identity_complete",
            "weights_architecture_identifiable",
            "preprocessing_complete",
            "preprocessing_dataset_independent",
            "representation_complete",
            "comparator_present",
            "raw_score_exposed",
            "raw_score_finite",
            "hidden_threshold",
            "decision_path_valid",
            "self_independent",
            "determinism_within_tolerance",
            "online_runtime_dependency",
            "offline_bundle_complete",
            "offline_execution_proven",
            "process_restart_isolated",
            "architecture_fit",
            "operationally_feasible",
            "external_minutiae_in_candidate_identity",
            "reweighting_uses_evaluation_cohort",
            "execution_attempted",
            "smoke_passed",
            "contract_passed",
        ):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be a boolean")
        if (self.smoke_passed or self.contract_passed) and not self.execution_attempted:
            raise ValueError(
                "smoke and contract conclusions require an execution attempt"
            )
        if self.contract_passed and not self.smoke_passed:
            raise ValueError("contract qualification cannot pass before smoke qualification")
        for name in (
            "algorithm_completeness_rank",
            "external_components_required",
            "runtime_complexity_rank",
            "estimated_adapter_lines",
            "diversity_rank",
            "paper_year",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative exact integer")
        failures: dict[str, tuple[str, ...]] = {}
        for gate, codes in dict(self.extra_gate_failures).items():
            gate_value = gate.value if isinstance(gate, QualificationGate) else str(gate)
            QualificationGate(gate_value)
            values = tuple(str(code).strip() for code in codes)
            if not values or any(not code for code in values):
                raise ValueError(f"extra failures for {gate!r} must be non-empty codes")
            failures[gate_value] = values
        evidence: dict[str, tuple[str, ...]] = {}
        for gate, references in dict(self.gate_evidence).items():
            gate_value = gate.value if isinstance(gate, QualificationGate) else str(gate)
            QualificationGate(gate_value)
            values = tuple(str(item).strip() for item in references)
            if any(not item for item in values):
                raise ValueError(f"evidence for {gate!r} contains an empty reference")
            evidence[gate_value] = values
        object.__setattr__(self, "extra_gate_failures", MappingProxyType(failures))
        object.__setattr__(self, "gate_evidence", MappingProxyType(evidence))
        expected = semantic_fingerprint("qualification_facts_v1", self)
        if self.fingerprint != expected:
            raise ValueError("fingerprint does not cover qualification facts")

    @classmethod
    def create(cls, **claims: Any) -> "QualificationFacts":
        return cls(**claims, fingerprint=semantic_fingerprint("qualification_facts_v1", claims))


def _append(failures: dict[QualificationGate, list[str]], gate: QualificationGate, condition: bool, code: str) -> None:
    if condition:
        failures[gate].append(code)


def _clear_licences(records: Sequence[CandidateLicenseRecord]) -> bool:
    grouped: dict[LicenseScope, list[CandidateLicenseRecord]] = {}
    for record in records:
        grouped.setdefault(record.scope, []).append(record)
    required_scopes = (
        LicenseScope.SOURCE_CODE,
        LicenseScope.WEIGHTS,
        LicenseScope.THIRD_PARTY,
        LicenseScope.TRAINING_RESTRICTIONS,
    )
    if any(not grouped.get(scope) for scope in required_scopes):
        return False
    return all(
        record.conclusion is LicenseConclusion.CLEAR
        for record in records
    )


def _gate_for_expected_role(role: str) -> QualificationGate:
    """Place a missing registry component at its substantive hard gate."""
    normalized = role.lower()
    if "license" in normalized:
        return QualificationGate.LICENSE_AND_PUBLICATION
    if "dependency_lock" in normalized or "runtime_manifest" in normalized:
        return QualificationGate.OFFLINE_OPERATION
    if "checkpoint" in normalized or normalized == "weights":
        return QualificationGate.EXACT_WEIGHTS
    if "preprocess" in normalized or "image_loader" in normalized:
        return QualificationGate.COMPLETE_PREPROCESSING
    if any(
        token in normalized
        for token in ("representation", "embedding_fusion", "image_map_concatenation")
    ):
        return QualificationGate.COMPLETE_REPRESENTATION
    if any(
        token in normalized
        for token in ("comparator", "score", "similarity_function")
    ):
        return QualificationGate.FINITE_RAW_SCORE
    return QualificationGate.COMPLETE_INFERENCE


def derive_gate_results(
    *,
    candidate: ModernMatcherCandidate,
    manifest: CandidateArtifactManifest,
    facts: QualificationFacts,
    preprocessing: CandidatePreprocessingProfile | None,
    representation: CandidateRepresentationProfile | None,
    score: CandidateScoreProfile | None,
    determinism: CandidateDeterminismReport,
    operational: CandidateOperationalReport,
    decision_path: DecisionPath,
) -> tuple[QualificationGateResult, ...]:
    """Apply hard gates.  No failure can be averaged away by another success."""
    failures = {gate: [] for gate in QualificationGate}

    scientific_complete = (
        candidate.actual_implementation_name is not None
        and candidate.relationship_to_original_paper is not None
        and bool(candidate.implementation_authors)
        and candidate.implementation_origin is not ImplementationOrigin.NOT_ESTABLISHED
    )
    _append(failures, QualificationGate.SCIENTIFIC_IDENTITY, not scientific_complete, "SCIENTIFIC_IDENTITY_INCOMPLETE")
    _append(
        failures,
        QualificationGate.SCIENTIFIC_IDENTITY,
        candidate.implementation_origin is ImplementationOrigin.INDEPENDENT_REIMPLEMENTATION
        and candidate.actual_implementation_name == candidate.claimed_algorithm_name,
        "INDEPENDENT_REIMPLEMENTATION_USES_ORIGINAL_IDENTITY",
    )

    _append(failures, QualificationGate.COMPLETE_INFERENCE, facts.paper_only, "PAPER_WITHOUT_INFERENCE_CODE")
    _append(failures, QualificationGate.COMPLETE_INFERENCE, not facts.inference_code_present and not facts.paper_only, "INFERENCE_CODE_MISSING")
    _append(failures, QualificationGate.COMPLETE_INFERENCE, not facts.imports_resolvable, "IMPORTS_UNRESOLVABLE")
    _append(failures, QualificationGate.COMPLETE_INFERENCE, not facts.model_constructor_present, "MODEL_CONSTRUCTOR_MISSING")

    checkpoints = manifest.checkpoint_components
    _append(
        failures,
        QualificationGate.EXACT_WEIGHTS,
        not facts.weights_present,
        "INFERENCE_CODE_WITHOUT_WEIGHTS" if facts.inference_code_present else "WEIGHTS_MISSING",
    )
    _append(failures, QualificationGate.EXACT_WEIGHTS, facts.weights_present and not facts.weights_identity_complete, "CHECKPOINT_IDENTITY_INCOMPLETE")
    _append(failures, QualificationGate.EXACT_WEIGHTS, facts.weights_present and not facts.weights_architecture_identifiable, "WEIGHTS_ARCHITECTURE_UNIDENTIFIABLE")
    _append(failures, QualificationGate.EXACT_WEIGHTS, facts.weights_present and not checkpoints, "CHECKPOINT_COMPONENT_MISSING")
    if facts.weights_present:
        _append(
            failures,
            QualificationGate.EXACT_WEIGHTS,
            any(not item.identity_established for item in checkpoints),
            "CHECKPOINT_IDENTITY_INCOMPLETE",
        )

    _append(failures, QualificationGate.COMPLETE_PREPROCESSING, not facts.preprocessing_complete or preprocessing is None or not preprocessing.canonical_png_to_tensor_complete, "PREPROCESSING_INCOMPLETE")
    _append(failures, QualificationGate.COMPLETE_PREPROCESSING, not facts.preprocessing_dataset_independent or (preprocessing is not None and not preprocessing.dataset_independent), "PREPROCESSING_DATASET_DEPENDENT")
    _append(
        failures,
        QualificationGate.COMPLETE_PREPROCESSING,
        preprocessing is not None and not preprocessing.subject_independent,
        "PREPROCESSING_SUBJECT_DEPENDENT",
    )
    _append(
        failures,
        QualificationGate.COMPLETE_PREPROCESSING,
        preprocessing is not None and not preprocessing.label_independent,
        "PREPROCESSING_LABEL_DEPENDENT",
    )

    _append(failures, QualificationGate.COMPLETE_REPRESENTATION, not facts.representation_complete or representation is None or not representation.complete, "REPRESENTATION_INCOMPLETE")

    _append(failures, QualificationGate.FINITE_RAW_SCORE, not facts.comparator_present, "COMPARATOR_MISSING")
    _append(failures, QualificationGate.FINITE_RAW_SCORE, not facts.raw_score_exposed, "RAW_SCORE_NOT_EXPOSED")
    if facts.execution_attempted:
        _append(
            failures,
            QualificationGate.FINITE_RAW_SCORE,
            facts.raw_score_exposed and not facts.raw_score_finite,
            "RAW_SCORE_NOT_FINITE",
        )
    else:
        failures[QualificationGate.FINITE_RAW_SCORE].append(
            "RAW_SCORE_RUNTIME_NOT_EXECUTED"
        )
    _append(failures, QualificationGate.FINITE_RAW_SCORE, facts.hidden_threshold or (score is not None and score.hidden_threshold), "HIDDEN_THRESHOLD")
    _append(failures, QualificationGate.FINITE_RAW_SCORE, score is None or not score.complete, "SCORE_PROFILE_INCOMPLETE")

    _append(failures, QualificationGate.DECISION_PATH, not facts.decision_path_valid or decision_path.kind is DecisionPathKind.NONE, "DECISION_PATH_NOT_ESTABLISHED")
    if decision_path.kind is DecisionPathKind.DOCUMENTED_CHECKPOINT_THRESHOLD:
        checkpoint_identities = {
            identity
            for checkpoint in checkpoints
            for identity in (checkpoint.fingerprint, checkpoint.sha256)
            if identity is not None
        }
        _append(
            failures,
            QualificationGate.DECISION_PATH,
            decision_path.checkpoint_fingerprint not in checkpoint_identities,
            "THRESHOLD_CHECKPOINT_MISMATCH",
        )
        threshold_source_reference = (
            f"sha256:{decision_path.threshold_source_fingerprint}"
        )
        threshold_documents = tuple(
            component
            for component in manifest.components
            if component.kind is ComponentKind.UPSTREAM_DOCUMENTATION
            and component.present
            and component.identity_established
            and component.required
            and component.locked_for_offline_use
        )
        threshold_document_identities = {
            identity
            for component in threshold_documents
            for identity in (
                component.fingerprint,
                component.sha256,
                component.source_archive_sha256,
            )
            if identity is not None
        }
        _append(
            failures,
            QualificationGate.DECISION_PATH,
            decision_path.threshold_source_fingerprint
            not in threshold_document_identities,
            "THRESHOLD_SOURCE_ARTIFACT_NOT_IDENTIFIED",
        )
        _append(
            failures,
            QualificationGate.DECISION_PATH,
            threshold_source_reference
            not in facts.gate_evidence.get(
                QualificationGate.DECISION_PATH.value, ()
            ),
            "THRESHOLD_SOURCE_EVIDENCE_NOT_BOUND",
        )
        numeric_bounds_missing = (
            score is None
            or score.score_minimum is None
            or score.score_maximum is None
        )
        _append(
            failures,
            QualificationGate.DECISION_PATH,
            numeric_bounds_missing,
            "SCORE_RANGE_NOT_NUMERICALLY_BOUNDED_FOR_THRESHOLD",
        )
        if not numeric_bounds_missing:
            threshold = Decimal(decision_path.documented_threshold)
            _append(
                failures,
                QualificationGate.DECISION_PATH,
                not (
                    Decimal(score.score_minimum)
                    <= threshold
                    <= Decimal(score.score_maximum)
                ),
                "THRESHOLD_OUTSIDE_SCORE_RANGE",
            )
    elif decision_path.kind is DecisionPathKind.EXTERNAL_DEVELOPMENT_CALIBRATION:
        calibration_reference = (
            f"sha256:{decision_path.calibration_protocol_fingerprint}"
        )
        _append(
            failures,
            QualificationGate.DECISION_PATH,
            calibration_reference
            not in facts.gate_evidence.get(
                QualificationGate.DECISION_PATH.value, ()
            ),
            "CALIBRATION_PROTOCOL_EVIDENCE_NOT_BOUND",
        )

    if facts.execution_attempted:
        _append(
            failures,
            QualificationGate.INDEPENDENT_SELF,
            not facts.self_independent,
            "SELF_EXTRACTION_NOT_INDEPENDENT",
        )
    else:
        failures[QualificationGate.INDEPENDENT_SELF].append(
            "SELF_CONTRACT_NOT_EXECUTED"
        )

    if not determinism.tested:
        failures[QualificationGate.DETERMINISM].append(
            "DETERMINISM_NOT_TESTED"
        )
    else:
        _append(
            failures,
            QualificationGate.DETERMINISM,
            not facts.process_restart_isolated,
            "PROCESS_RESTART_NOT_ISOLATED",
        )
        _append(
            failures,
            QualificationGate.DETERMINISM,
            not facts.determinism_within_tolerance
            or determinism.within_predeclared_tolerance is not True,
            "NONDETERMINISM_EXCEEDS_TOLERANCE",
        )
    _append(
        failures,
        QualificationGate.DECISION_PATH,
        decision_path.kind is not DecisionPathKind.NONE
        and determinism.decision_safe is not True,
        "DRIFT_CAN_CHANGE_THRESHOLD_DECISION",
    )

    _append(failures, QualificationGate.OFFLINE_OPERATION, facts.online_runtime_dependency, "ONLINE_RUNTIME_DEPENDENCY")
    _append(failures, QualificationGate.OFFLINE_OPERATION, not facts.offline_bundle_complete or not manifest.required_components_available_offline, "OFFLINE_BUNDLE_INCOMPLETE")
    _append(
        failures,
        QualificationGate.OFFLINE_OPERATION,
        not facts.offline_execution_proven,
        "OFFLINE_EXECUTION_NOT_PROVEN",
    )

    scopes = {record.scope for record in manifest.license_records}
    _append(failures, QualificationGate.LICENSE_AND_PUBLICATION, LicenseScope.SOURCE_CODE not in scopes, "SOURCE_CODE_LICENSE_MISSING")
    _append(failures, QualificationGate.LICENSE_AND_PUBLICATION, LicenseScope.WEIGHTS not in scopes, "CHECKPOINT_LICENSE_MISSING")
    _append(
        failures,
        QualificationGate.LICENSE_AND_PUBLICATION,
        LicenseScope.THIRD_PARTY not in scopes,
        "THIRD_PARTY_LICENSE_REVIEW_MISSING",
    )
    _append(
        failures,
        QualificationGate.LICENSE_AND_PUBLICATION,
        LicenseScope.TRAINING_RESTRICTIONS not in scopes,
        "TRAINING_RESTRICTIONS_REVIEW_MISSING",
    )
    licences_by_fingerprint = {
        record.fingerprint: record for record in manifest.license_records
    }
    source_components = tuple(
        component
        for component in manifest.components
        if component.present and component.kind is ComponentKind.SOURCE_CODE
    )
    linked_source_licences = tuple(
        licences_by_fingerprint.get(component.license_record_fingerprint)
        for component in source_components
    )
    linked_checkpoint_licences = tuple(
        licences_by_fingerprint.get(component.license_record_fingerprint)
        for component in checkpoints
        if component.present
    )
    _append(
        failures,
        QualificationGate.LICENSE_AND_PUBLICATION,
        bool(source_components)
        and any(
            record is None or record.scope is not LicenseScope.SOURCE_CODE
            for record in linked_source_licences
        ),
        "SOURCE_COMPONENT_LICENSE_MISMATCH",
    )
    _append(
        failures,
        QualificationGate.LICENSE_AND_PUBLICATION,
        bool(checkpoints)
        and any(
            record is None or record.scope is not LicenseScope.WEIGHTS
            for record in linked_checkpoint_licences
        ),
        "CHECKPOINT_LICENSE_MISSING",
    )
    weights_records = tuple(record for record in manifest.license_records if record.scope is LicenseScope.WEIGHTS)
    _append(failures, QualificationGate.LICENSE_AND_PUBLICATION, bool(weights_records) and any(record.conclusion is not LicenseConclusion.CLEAR for record in weights_records), "WEIGHTS_LICENSE_NOT_ESTABLISHED")
    _append(failures, QualificationGate.LICENSE_AND_PUBLICATION, not _clear_licences(manifest.license_records), "BENCHMARK_PUBLICATION_PERMISSIONS_NOT_CLEAR")

    _append(failures, QualificationGate.ARCHITECTURE_FIT, not facts.architecture_fit, "ARCHITECTURE_CONTRACT_NOT_MET")
    _append(failures, QualificationGate.ARCHITECTURE_FIT, not facts.external_minutiae_in_candidate_identity, "EXTERNAL_MINUTIAE_OUTSIDE_IDENTITY")
    _append(failures, QualificationGate.ARCHITECTURE_FIT, facts.reweighting_uses_evaluation_cohort, "EVALUATION_COHORT_REWEIGHTING")

    if not operational.measured:
        failures[QualificationGate.OPERATIONAL_FEASIBILITY].append(
            "OPERATIONAL_MEASUREMENTS_MISSING"
        )
    else:
        _append(
            failures,
            QualificationGate.OPERATIONAL_FEASIBILITY,
            not facts.operationally_feasible
            or operational.operationally_feasible is not True,
            "FULL_RUN_NOT_OPERATIONALLY_FEASIBLE",
        )

    expected_roles = set(candidate.expected_components)
    present_roles = {component.role for component in manifest.components if component.present}
    for role in sorted(expected_roles - present_roles):
        code = "EXPECTED_COMPONENT_MISSING_" + "".join(character if character.isalnum() else "_" for character in role.upper()).strip("_")
        failures[_gate_for_expected_role(role)].append(code)
    for role in sorted(expected_roles & present_roles):
        matching = tuple(
            component
            for component in manifest.components
            if component.present and component.role == role
        )
        if not any(component.required for component in matching):
            code = "EXPECTED_COMPONENT_NOT_REQUIRED_" + "".join(
                character if character.isalnum() else "_"
                for character in role.upper()
            ).strip("_")
            failures[_gate_for_expected_role(role)].append(code)

    for gate_name, codes in facts.extra_gate_failures.items():
        failures[QualificationGate(gate_name)].extend(codes)

    results: list[QualificationGateResult] = []
    for gate in QualificationGate:
        codes = tuple(dict.fromkeys(failures[gate]))
        results.append(
            QualificationGateResult.create(
                schema_version=STAGE8A_SCHEMA_VERSION,
                gate=gate,
                passed=not codes,
                failures=codes,
                evidence=tuple(facts.gate_evidence.get(gate.value, ())),
            )
        )
    return tuple(results)


def build_qualification_report(
    *,
    candidate: ModernMatcherCandidate,
    registry_fingerprint: str,
    manifest: CandidateArtifactManifest,
    facts: QualificationFacts,
    preprocessing: CandidatePreprocessingProfile | None,
    representation: CandidateRepresentationProfile | None,
    score: CandidateScoreProfile | None,
    determinism: CandidateDeterminismReport,
    operational: CandidateOperationalReport,
    decision_path: DecisionPath,
    runtime_probe: RuntimeProbeResult | None,
    qualified_utc: str,
) -> CandidateQualificationReport:
    if manifest.candidate_fingerprint != candidate.fingerprint:
        raise QualificationError("artefact manifest does not belong to the registry candidate")
    if facts.smoke_passed and runtime_probe is None:
        raise QualificationError(
            "a passing smoke qualification requires its content-addressed runtime probe"
        )
    if runtime_probe is not None:
        if not facts.execution_attempted:
            raise QualificationError(
                "a runtime probe cannot exist when execution was not attempted"
            )
        if runtime_probe.candidate_fingerprint != candidate.fingerprint:
            raise QualificationError(
                "runtime probe belongs to another candidate identity"
            )
        if runtime_probe.artifact_manifest_fingerprint != manifest.fingerprint:
            raise QualificationError(
                "runtime probe belongs to another artifact manifest"
            )
        if runtime_probe.determinism_report.fingerprint != determinism.fingerprint:
            raise QualificationError(
                "determinism report is not the bound runtime probe observation"
            )
        if runtime_probe.operational_report.fingerprint != operational.fingerprint:
            raise QualificationError(
                "operational report is not the bound runtime probe observation"
            )
        observations = (
            (
                facts.determinism_within_tolerance,
                determinism.within_predeclared_tolerance is True,
                "determinism tolerance",
            ),
            (
                facts.operationally_feasible,
                operational.operationally_feasible is True,
                "operational feasibility",
            ),
            (
                facts.process_restart_isolated,
                runtime_probe.process_restart_isolated,
                "process restart isolation",
            ),
            (
                facts.offline_execution_proven,
                runtime_probe.offline_execution_proven,
                "offline execution isolation",
            ),
        )
        for claimed, observed, what in observations:
            if claimed is not observed:
                raise QualificationError(
                    f"qualification facts contradict the runtime probe {what}"
                )
        if facts.raw_score_finite is not True:
            raise QualificationError(
                "a successful runtime probe observed a finite raw score"
            )
        probe_reference = f"sha256:{runtime_probe.fingerprint}"
        for gate in (
            QualificationGate.FINITE_RAW_SCORE,
            QualificationGate.INDEPENDENT_SELF,
            QualificationGate.DETERMINISM,
            QualificationGate.OPERATIONAL_FEASIBILITY,
        ):
            if probe_reference not in facts.gate_evidence.get(gate.value, ()):
                raise QualificationError(
                    f"{gate.value} does not bind the runtime probe fingerprint"
                )
        if runtime_probe.offline_execution_proven:
            isolation_reference = (
                f"sha256:{runtime_probe.isolation_evidence_fingerprint}"
            )
            if isolation_reference not in facts.gate_evidence.get(
                QualificationGate.OFFLINE_OPERATION.value, ()
            ):
                raise QualificationError(
                    "offline operation does not bind the isolation attestation"
                )
    gates = derive_gate_results(
        candidate=candidate,
        manifest=manifest,
        facts=facts,
        preprocessing=preprocessing,
        representation=representation,
        score=score,
        determinism=determinism,
        operational=operational,
        decision_path=decision_path,
    )
    passed = {item.gate: item.passed for item in gates}
    raw_ready = all(passed[gate] for gate in QualificationGate if gate is not QualificationGate.DECISION_PATH)
    decision_ready = raw_ready and passed[QualificationGate.DECISION_PATH]
    static_gates = (
        QualificationGate.SCIENTIFIC_IDENTITY,
        QualificationGate.COMPLETE_INFERENCE,
        QualificationGate.EXACT_WEIGHTS,
        QualificationGate.COMPLETE_PREPROCESSING,
        QualificationGate.COMPLETE_REPRESENTATION,
        QualificationGate.LICENSE_AND_PUBLICATION,
    )
    score_gate = next(item for item in gates if item.gate is QualificationGate.FINITE_RAW_SCORE)
    # Finiteness itself is a smoke observation.  Static inspection must establish
    # the comparator, raw-score API, profile, and absence of a hidden threshold,
    # but cannot require the very execution it is deciding whether to permit.
    finite_score_is_the_only_dynamic_unknown = set(score_gate.failures) <= {
        "RAW_SCORE_NOT_FINITE",
        "RAW_SCORE_RUNTIME_NOT_EXECUTED",
    }
    static_passed = all(passed[gate] for gate in static_gates) and (
        score_gate.passed or finite_score_is_the_only_dynamic_unknown
    )
    if not static_passed and facts.execution_attempted:
        raise QualificationError("static inspection failed; execution is forbidden")
    if decision_ready:
        status = QualificationStatus.DECISION_PATH_READY
    elif raw_ready:
        status = QualificationStatus.RAW_SCORE_READY
    elif (
        not passed[QualificationGate.LICENSE_AND_PUBLICATION]
        and (facts.inference_code_present or facts.weights_present)
    ):
        status = QualificationStatus.LICENSE_BLOCKED
    elif static_passed and facts.execution_attempted:
        status = QualificationStatus.RUNTIME_BLOCKED
    elif any(component.present for component in manifest.components):
        status = QualificationStatus.ARTIFACT_INCOMPLETE
    else:
        status = QualificationStatus.ARTIFACT_INCOMPLETE
    checkpoint_variants = tuple(
        component.model_variant
        for component in manifest.checkpoint_components
        if component.present and component.model_variant is not None
    )
    qualified_implementation_name = candidate.actual_implementation_name
    if checkpoint_variants:
        identity_prefix = (
            qualified_implementation_name
            or f"{candidate.claimed_algorithm_name} acquired artifact"
        )
        qualified_implementation_name = (
            f"{identity_prefix}: " + ", ".join(checkpoint_variants)
        )
    return CandidateQualificationReport.create(
        schema_version=STAGE8A_SCHEMA_VERSION,
        report_id=f"qualification_{candidate.candidate_id}",
        candidate_id=candidate.candidate_id,
        candidate_fingerprint=candidate.fingerprint,
        qualified_implementation_name=qualified_implementation_name,
        registry_fingerprint=registry_fingerprint,
        artifact_manifest=manifest,
        preprocessing_profile=preprocessing,
        representation_profile=representation,
        score_profile=score,
        determinism_report=determinism,
        operational_report=operational,
        decision_path=decision_path,
        gate_results=gates,
        qualification_status=status,
        static_inspection_passed=static_passed,
        execution_attempted=facts.execution_attempted,
        smoke_qualification_passed=facts.smoke_passed,
        contract_qualification_passed=facts.contract_passed,
        runtime_probe=runtime_probe,
        runtime_probe_fingerprint=(
            runtime_probe.fingerprint if runtime_probe is not None else None
        ),
        raw_score_ready=raw_ready,
        decision_path_ready=decision_ready,
        license_clear=passed[QualificationGate.LICENSE_AND_PUBLICATION],
        architecture_fit=passed[QualificationGate.ARCHITECTURE_FIT],
        official_or_author_supplied=candidate.implementation_origin in (ImplementationOrigin.OFFICIAL, ImplementationOrigin.AUTHOR_SUPPLIED),
        algorithm_completeness_rank=facts.algorithm_completeness_rank,
        external_components_required=facts.external_components_required,
        runtime_complexity_rank=facts.runtime_complexity_rank,
        estimated_adapter_lines=facts.estimated_adapter_lines,
        diversity_rank=facts.diversity_rank,
        paper_year=facts.paper_year,
        qualified_utc=qualified_utc,
    )
