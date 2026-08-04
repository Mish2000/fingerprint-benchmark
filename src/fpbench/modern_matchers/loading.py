"""Strict reconstruction of Stage 8A JSON/YAML records.

The dataclasses validate values and fingerprints.  This module adds the other
half of a durable format: unknown and missing keys are errors, and every nested
record is reconstructed rather than left as a mutable dictionary.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Mapping

from fpbench.core.modern_matcher_models import (
    CandidateArtifactManifest,
    CandidateComponent,
    CandidateDeterminismReport,
    CandidateLicenseRecord,
    CandidateOperationalReport,
    CandidatePreprocessingProfile,
    CandidateQualificationReport,
    CandidateRepresentationProfile,
    CandidateScoreProfile,
    DecisionPath,
    ModernMatcherCandidate,
    ModernMatcherCandidateRegistry,
    ModernMatcherSelectionDecision,
    PreprocessingOperation,
    QualificationGateResult,
    RejectedCandidate,
    RepresentationBranch,
    RuntimeProbeResult,
    SelectionPolicy,
    Stage8AFinalization,
)

__all__ = [
    "candidate_from_plain",
    "registry_from_plain",
    "component_from_plain",
    "license_record_from_plain",
    "artifact_manifest_from_plain",
    "preprocessing_operation_from_plain",
    "preprocessing_profile_from_plain",
    "representation_branch_from_plain",
    "representation_profile_from_plain",
    "score_profile_from_plain",
    "determinism_report_from_plain",
    "operational_report_from_plain",
    "runtime_probe_from_plain",
    "gate_result_from_plain",
    "decision_path_from_plain",
    "qualification_report_from_plain",
    "selection_policy_from_plain",
    "rejected_candidate_from_plain",
    "selection_decision_from_plain",
    "finalization_from_plain",
]


def _document(value: Any, what: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{what} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise ValueError(f"{what} keys must be strings")
    return dict(value)


def _claims(cls: type[Any], value: Any, what: str) -> dict[str, Any]:
    document = _document(value, what)
    expected = {item.name for item in dataclasses.fields(cls)}
    missing = sorted(expected - set(document))
    unknown = sorted(set(document) - expected)
    if missing:
        raise ValueError(f"{what} is missing required keys: {missing}")
    if unknown:
        raise ValueError(f"{what} contains unknown keys: {unknown}")
    return document


def _sequence(value: Any, what: str) -> tuple[Any, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{what} must be a JSON/YAML sequence")
    return tuple(value)


def candidate_from_plain(value: Any) -> ModernMatcherCandidate:
    claims = _claims(ModernMatcherCandidate, value, "modern matcher candidate")
    for name in ("implementation_authors", "expected_components", "known_missing_components"):
        claims[name] = _sequence(claims[name], f"candidate.{name}")
    return ModernMatcherCandidate(**claims)


def registry_from_plain(value: Any) -> ModernMatcherCandidateRegistry:
    claims = _claims(ModernMatcherCandidateRegistry, value, "candidate registry")
    claims["candidates"] = tuple(candidate_from_plain(item) for item in _sequence(claims["candidates"], "registry.candidates"))
    return ModernMatcherCandidateRegistry(**claims)


def component_from_plain(value: Any) -> CandidateComponent:
    claims = _claims(CandidateComponent, value, "candidate component")
    claims["notes"] = _sequence(claims["notes"], "component.notes")
    return CandidateComponent(**claims)


def license_record_from_plain(value: Any) -> CandidateLicenseRecord:
    claims = _claims(CandidateLicenseRecord, value, "candidate licence record")
    claims["restrictions"] = _sequence(claims["restrictions"], "licence.restrictions")
    claims["evidence"] = _sequence(claims["evidence"], "licence.evidence")
    return CandidateLicenseRecord(**claims)


def artifact_manifest_from_plain(value: Any) -> CandidateArtifactManifest:
    claims = _claims(CandidateArtifactManifest, value, "candidate artefact manifest")
    claims["components"] = tuple(component_from_plain(item) for item in _sequence(claims["components"], "manifest.components"))
    claims["license_records"] = tuple(license_record_from_plain(item) for item in _sequence(claims["license_records"], "manifest.license_records"))
    return CandidateArtifactManifest(**claims)


def preprocessing_operation_from_plain(value: Any) -> PreprocessingOperation:
    return PreprocessingOperation(**_claims(PreprocessingOperation, value, "preprocessing operation"))


def preprocessing_profile_from_plain(value: Any) -> CandidatePreprocessingProfile:
    claims = _claims(CandidatePreprocessingProfile, value, "preprocessing profile")
    claims["operations"] = tuple(preprocessing_operation_from_plain(item) for item in _sequence(claims["operations"], "preprocessing.operations"))
    return CandidatePreprocessingProfile(**claims)


def representation_branch_from_plain(value: Any) -> RepresentationBranch:
    claims = _claims(RepresentationBranch, value, "representation branch")
    claims["shape"] = _sequence(claims["shape"], "branch.shape")
    return RepresentationBranch(**claims)


def representation_profile_from_plain(value: Any) -> CandidateRepresentationProfile:
    claims = _claims(CandidateRepresentationProfile, value, "representation profile")
    claims["representation_shape"] = _sequence(claims["representation_shape"], "representation.shape")
    claims["branches"] = tuple(representation_branch_from_plain(item) for item in _sequence(claims["branches"], "representation.branches"))
    return CandidateRepresentationProfile(**claims)


def score_profile_from_plain(value: Any) -> CandidateScoreProfile:
    return CandidateScoreProfile(**_claims(CandidateScoreProfile, value, "score profile"))


def determinism_report_from_plain(value: Any) -> CandidateDeterminismReport:
    claims = _claims(CandidateDeterminismReport, value, "determinism report")
    claims["runtime_restrictions"] = _sequence(claims["runtime_restrictions"], "determinism.runtime_restrictions")
    return CandidateDeterminismReport(**claims)


def operational_report_from_plain(value: Any) -> CandidateOperationalReport:
    return CandidateOperationalReport(**_claims(CandidateOperationalReport, value, "operational report"))


def runtime_probe_from_plain(value: Any) -> RuntimeProbeResult:
    claims = _claims(RuntimeProbeResult, value, "runtime probe")
    claims["determinism_report"] = determinism_report_from_plain(
        claims["determinism_report"]
    )
    claims["operational_report"] = operational_report_from_plain(
        claims["operational_report"]
    )
    return RuntimeProbeResult(**claims)


def gate_result_from_plain(value: Any) -> QualificationGateResult:
    claims = _claims(QualificationGateResult, value, "qualification gate result")
    claims["failures"] = _sequence(claims["failures"], "gate.failures")
    claims["evidence"] = _sequence(claims["evidence"], "gate.evidence")
    return QualificationGateResult(**claims)


def decision_path_from_plain(value: Any) -> DecisionPath:
    return DecisionPath(**_claims(DecisionPath, value, "decision path"))


def qualification_report_from_plain(value: Any) -> CandidateQualificationReport:
    claims = _claims(CandidateQualificationReport, value, "candidate qualification report")
    claims["artifact_manifest"] = artifact_manifest_from_plain(claims["artifact_manifest"])
    if claims["preprocessing_profile"] is not None:
        claims["preprocessing_profile"] = preprocessing_profile_from_plain(claims["preprocessing_profile"])
    if claims["representation_profile"] is not None:
        claims["representation_profile"] = representation_profile_from_plain(claims["representation_profile"])
    if claims["score_profile"] is not None:
        claims["score_profile"] = score_profile_from_plain(claims["score_profile"])
    claims["determinism_report"] = determinism_report_from_plain(claims["determinism_report"])
    claims["operational_report"] = operational_report_from_plain(claims["operational_report"])
    if claims["runtime_probe"] is not None:
        claims["runtime_probe"] = runtime_probe_from_plain(
            claims["runtime_probe"]
        )
    claims["decision_path"] = decision_path_from_plain(claims["decision_path"])
    claims["gate_results"] = tuple(gate_result_from_plain(item) for item in _sequence(claims["gate_results"], "qualification.gate_results"))
    return CandidateQualificationReport(**claims)


def selection_policy_from_plain(value: Any) -> SelectionPolicy:
    claims = _claims(SelectionPolicy, value, "selection policy")
    for name in ("mandatory_gates", "tier_order", "tie_breakers"):
        claims[name] = _sequence(claims[name], f"selection_policy.{name}")
    return SelectionPolicy(**claims)


def rejected_candidate_from_plain(value: Any) -> RejectedCandidate:
    claims = _claims(RejectedCandidate, value, "rejected candidate")
    claims["gate_failures"] = _sequence(claims["gate_failures"], "rejected_candidate.gate_failures")
    return RejectedCandidate(**claims)


def selection_decision_from_plain(value: Any) -> ModernMatcherSelectionDecision:
    claims = _claims(ModernMatcherSelectionDecision, value, "modern matcher selection decision")
    claims["candidate_qualification_fingerprints"] = _document(claims["candidate_qualification_fingerprints"], "candidate qualification fingerprints")
    claims["rejected_candidates"] = tuple(rejected_candidate_from_plain(item) for item in _sequence(claims["rejected_candidates"], "selection.rejected_candidates"))
    return ModernMatcherSelectionDecision(**claims)


def finalization_from_plain(value: Any) -> Stage8AFinalization:
    claims = _claims(Stage8AFinalization, value, "Stage 8A finalization")
    for name in ("qualification_fingerprints", "qualification_content_hashes", "required_local_artifact_fingerprints"):
        claims[name] = _document(claims[name], f"finalization.{name}")
    return Stage8AFinalization(**claims)
