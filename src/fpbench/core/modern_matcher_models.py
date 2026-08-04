"""Immutable, content-addressed vocabulary for Stage 8A.

Stage 8A is deliberately a qualification layer, not an adapter and not an
experiment over SD300.  These records describe third-party artefacts, the
evidence collected about them, and the gate-first selection decision.  This
module is stdlib-only so the qualification layer can be imported without an
ML runtime, a dataset provider, or either existing matcher.

Every record validates a 64-character fingerprint over its semantic claims.
Wall-clock fields are retained in the stored document but excluded from the
semantic identity; finalization separately hashes the exact stored bytes.
Nested sequences are tuples and nested mappings are read-only copies, so a
``frozen=True`` record cannot be changed through an alias held by its caller.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from fpbench.core.identifiers import validate_id
from fpbench.core.serialization import require_exact_int, stable_hash, to_plain

__all__ = [
    "STAGE8A_SCHEMA_VERSION",
    "CandidateTier",
    "ImplementationOrigin",
    "ComponentKind",
    "LicenseScope",
    "LicenseConclusion",
    "QualificationStatus",
    "QualificationGate",
    "DecisionPathKind",
    "ThresholdSourceKind",
    "DevelopmentCohortKind",
    "Stage8AOutcome",
    "SelectionState",
    "ModernMatcherCandidate",
    "ModernMatcherCandidateRegistry",
    "CandidateComponent",
    "CandidateArtifactManifest",
    "CandidateLicenseRecord",
    "PreprocessingOperation",
    "CandidatePreprocessingProfile",
    "RepresentationBranch",
    "CandidateRepresentationProfile",
    "CandidateScoreProfile",
    "CandidateDeterminismReport",
    "CandidateOperationalReport",
    "RuntimeProbeResult",
    "QualificationGateResult",
    "DecisionPath",
    "CandidateQualificationReport",
    "SelectionPolicy",
    "RejectedCandidate",
    "ModernMatcherSelectionDecision",
    "Stage8AFinalization",
    "semantic_fingerprint",
    "document_content_hash",
]

STAGE8A_SCHEMA_VERSION = "1"
_HEX = frozenset("0123456789abcdef")
_NON_SEMANTIC_FIELDS = frozenset(
    {
        "acquired_utc",
        "inspected_utc",
        "qualified_utc",
        "decided_utc",
        "created_utc",
    }
)
_FACTORY_FINGERPRINTING: ContextVar[bool] = ContextVar(
    "stage8a_factory_fingerprinting", default=False
)


class CandidateTier(str, Enum):
    A = "A"
    B = "B"
    C = "C"

    @property
    def priority(self) -> int:
        return {CandidateTier.A: 3, CandidateTier.B: 2, CandidateTier.C: 1}[self]


class ImplementationOrigin(str, Enum):
    OFFICIAL = "official"
    AUTHOR_SUPPLIED = "author_supplied"
    INDEPENDENT_REIMPLEMENTATION = "independent_reimplementation"
    COMMERCIAL = "commercial"
    NOT_ESTABLISHED = "not_established"


class ComponentKind(str, Enum):
    SOURCE_CODE = "source_code"
    CHECKPOINT = "checkpoint"
    MODEL_CONFIGURATION = "model_configuration"
    RUNTIME_MANIFEST = "runtime_manifest"
    DEPENDENCY_LOCK = "dependency_lock"
    LICENSE_DOCUMENT = "license_document"
    UPSTREAM_DOCUMENTATION = "upstream_documentation"
    INFERENCE = "inference"
    PREPROCESSING = "preprocessing"
    REPRESENTATION = "representation"
    COMPARATOR = "comparator"
    LOCALIZATION = "localization"
    MINUTIAE = "minutiae"
    REALIGNMENT = "realignment"
    FUSION = "fusion"


class LicenseScope(str, Enum):
    SOURCE_CODE = "source_code"
    WEIGHTS = "weights"
    THIRD_PARTY = "third_party"
    TRAINING_RESTRICTIONS = "training_restrictions"


class LicenseConclusion(str, Enum):
    CLEAR = "clear"
    UNCLEAR = "unclear"
    BLOCKED = "blocked"


class QualificationStatus(str, Enum):
    DISCOVERED = "DISCOVERED"
    ACQUIRED = "ACQUIRED"
    ARTIFACT_INCOMPLETE = "ARTIFACT_INCOMPLETE"
    LICENSE_BLOCKED = "LICENSE_BLOCKED"
    RUNTIME_BLOCKED = "RUNTIME_BLOCKED"
    RAW_SCORE_READY = "RAW_SCORE_READY"
    DECISION_PATH_READY = "DECISION_PATH_READY"
    SELECTED = "SELECTED"
    REJECTED = "REJECTED"


class QualificationGate(str, Enum):
    SCIENTIFIC_IDENTITY = "scientific_identity"
    COMPLETE_INFERENCE = "complete_inference"
    EXACT_WEIGHTS = "exact_weights"
    COMPLETE_PREPROCESSING = "complete_preprocessing"
    COMPLETE_REPRESENTATION = "complete_representation"
    FINITE_RAW_SCORE = "finite_raw_score"
    DECISION_PATH = "decision_path"
    INDEPENDENT_SELF = "independent_self"
    DETERMINISM = "determinism"
    OFFLINE_OPERATION = "offline_operation"
    LICENSE_AND_PUBLICATION = "license_and_publication"
    ARCHITECTURE_FIT = "architecture_fit"
    OPERATIONAL_FEASIBILITY = "operational_feasibility"


class DecisionPathKind(str, Enum):
    NONE = "none"
    DOCUMENTED_CHECKPOINT_THRESHOLD = "documented_checkpoint_threshold"
    EXTERNAL_DEVELOPMENT_CALIBRATION = "external_development_calibration"


class ThresholdSourceKind(str, Enum):
    NONE = "none"
    UPSTREAM_DOCUMENTED_CHECKPOINT_THRESHOLD = (
        "upstream_documented_checkpoint_threshold"
    )
    PAPER_EER = "paper_eer"
    REPORTED_FAR_WITHOUT_RAW_CALIBRATION = (
        "reported_far_without_raw_calibration"
    )
    ASSUMED_COSINE_ZERO = "assumed_cosine_zero"


class DevelopmentCohortKind(str, Enum):
    NONE = "none"
    INDEPENDENT_EXTERNAL = "independent_external"
    SD300_EVALUATION = "sd300_evaluation"
    OTHER_EVALUATION = "other_evaluation"


class Stage8AOutcome(str, Enum):
    MODERN_MATCHER_SELECTED = "MODERN_MATCHER_SELECTED"
    NO_MODERN_MATCHER_READY = "NO_MODERN_MATCHER_READY"
    QUALIFIED_FOR_RAW_SCORES_ONLY = "QUALIFIED_FOR_RAW_SCORES_ONLY"


class SelectionState(str, Enum):
    SELECTED = "SELECTED"
    REJECTED = "REJECTED"
    QUALIFIED_RAW_SCORE_ONLY = "QUALIFIED_RAW_SCORE_ONLY"


def _require_text(value: Any, name: str, *, allow_empty: bool = False) -> str:
    text = str(value).strip()
    if not text and not allow_empty:
        raise ValueError(f"{name} must not be empty")
    return text


def _require_optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _require_text(value, name)


def _require_sha256(value: str, name: str) -> str:
    digest = str(value).strip().lower()
    if len(digest) != 64 or not set(digest) <= _HEX:
        raise ValueError(f"{name} must be a 64-character hexadecimal SHA-256")
    return digest


def _require_optional_sha256(value: str | None, name: str) -> str | None:
    return None if value is None else _require_sha256(value, name)


def _require_commit(value: str | None, name: str) -> str | None:
    if value is None:
        return None
    commit = str(value).strip().lower()
    if len(commit) != 40 or not set(commit) <= _HEX:
        raise ValueError(f"{name} must be a full 40-character commit SHA")
    return commit


def _enum(value: Any, enum_type: type[Enum], name: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(repr(item.value) for item in enum_type)
        raise ValueError(f"{name} must be one of {allowed}") from exc


def _text_tuple(values: Sequence[Any], name: str, *, unique: bool = True) -> tuple[str, ...]:
    result = tuple(_require_text(value, f"{name} entry") for value in values)
    if unique and len(set(result)) != len(result):
        raise ValueError(f"{name} must not contain duplicates")
    return result


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    def freeze(item: Any) -> Any:
        if isinstance(item, Mapping):
            return MappingProxyType({str(k): freeze(v) for k, v in item.items()})
        if isinstance(item, (list, tuple)):
            return tuple(freeze(v) for v in item)
        if isinstance(item, (set, frozenset)):
            return tuple(sorted((freeze(v) for v in item), key=repr))
        return item

    return freeze(dict(value))


def _decimal_text(value: str | None, name: str, *, non_negative: bool = False) -> str | None:
    if value is None:
        return None
    text = _require_text(value, name)
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"{name} must be a finite decimal string") from exc
    if not number.is_finite():
        raise ValueError(f"{name} must be finite")
    if non_negative and number < 0:
        raise ValueError(f"{name} must not be negative")
    return text


def semantic_fingerprint(schema: str, value: Any) -> str:
    """Fingerprint semantic claims, excluding self identity and wall clocks."""
    plain = dict(to_plain(value)) if not isinstance(value, Mapping) else dict(to_plain(value))
    plain.pop("fingerprint", None)

    def without_clocks(item: Any) -> Any:
        if isinstance(item, Mapping):
            return {
                key: without_clocks(nested)
                for key, nested in item.items()
                if key not in _NON_SEMANTIC_FIELDS
            }
        if isinstance(item, list):
            return [without_clocks(nested) for nested in item]
        if isinstance(item, tuple):
            return tuple(without_clocks(nested) for nested in item)
        return item

    plain = without_clocks(plain)
    return stable_hash({"schema": schema, "claims": plain}, length=64)


def document_content_hash(schema: str, value: Any) -> str:
    """Hash an entire persisted document, including timestamps and fingerprint."""
    return stable_hash({"schema": schema, "document": to_plain(value)}, length=64)


def _finish(model: Any, schema: str) -> None:
    if _FACTORY_FINGERPRINTING.get():
        object.__setattr__(model, "fingerprint", semantic_fingerprint(schema, model))
        return
    fingerprint = _require_sha256(model.fingerprint, "fingerprint")
    object.__setattr__(model, "fingerprint", fingerprint)
    expected = semantic_fingerprint(schema, model)
    if fingerprint != expected:
        raise ValueError(f"fingerprint does not cover the {schema} claims")


def _with_fingerprint(cls: type[Any], schema: str, claims: Mapping[str, Any]) -> Any:
    plain = dict(claims)
    token = _FACTORY_FINGERPRINTING.set(True)
    try:
        # The constructor first canonicalizes text, enums, digests, tuples, and
        # mappings.  _finish then fingerprints that canonical form.  Direct
        # construction remains strict and cannot use this sentinel path.
        return cls(**plain, fingerprint="0" * 64)
    finally:
        _FACTORY_FINGERPRINTING.reset(token)


@dataclass(frozen=True, slots=True)
class ModernMatcherCandidate:
    schema_version: str
    candidate_id: str
    tier: CandidateTier
    claimed_algorithm_name: str
    actual_implementation_name: str | None
    paper_citation: str
    paper_url: str
    implementation_authors: tuple[str, ...]
    relationship_to_original_paper: str | None
    implementation_origin: ImplementationOrigin
    expected_components: tuple[str, ...]
    known_missing_components: tuple[str, ...]
    acquisition_method: str
    fingerprint: str

    def __post_init__(self) -> None:
        if str(self.schema_version) != STAGE8A_SCHEMA_VERSION:
            raise ValueError("unsupported modern matcher candidate schema version")
        validate_id(self.candidate_id)
        object.__setattr__(self, "tier", _enum(self.tier, CandidateTier, "tier"))
        for name in ("claimed_algorithm_name", "paper_citation", "paper_url", "acquisition_method"):
            object.__setattr__(self, name, _require_text(getattr(self, name), name))
        object.__setattr__(self, "actual_implementation_name", _require_optional_text(self.actual_implementation_name, "actual_implementation_name"))
        object.__setattr__(self, "relationship_to_original_paper", _require_optional_text(self.relationship_to_original_paper, "relationship_to_original_paper"))
        object.__setattr__(self, "implementation_origin", _enum(self.implementation_origin, ImplementationOrigin, "implementation_origin"))
        object.__setattr__(self, "implementation_authors", _text_tuple(self.implementation_authors, "implementation_authors"))
        object.__setattr__(self, "expected_components", _text_tuple(self.expected_components, "expected_components"))
        object.__setattr__(self, "known_missing_components", _text_tuple(self.known_missing_components, "known_missing_components"))
        _finish(self, "modern_matcher_candidate_v1")

    @classmethod
    def create(cls, **claims: Any) -> "ModernMatcherCandidate":
        return _with_fingerprint(cls, "modern_matcher_candidate_v1", claims)


@dataclass(frozen=True, slots=True)
class ModernMatcherCandidateRegistry:
    schema_version: str
    candidate_registry_version: str
    frozen_before_qualification: bool
    candidates: tuple[ModernMatcherCandidate, ...]
    reserve_candidate_id: str
    reserve_activation: str
    fingerprint: str

    def __post_init__(self) -> None:
        if str(self.schema_version) != STAGE8A_SCHEMA_VERSION:
            raise ValueError("unsupported candidate registry schema version")
        validate_id(self.candidate_registry_version)
        if self.frozen_before_qualification is not True:
            raise ValueError("the Stage 8A registry must be frozen before qualification")
        object.__setattr__(self, "candidates", tuple(self.candidates))
        ids = tuple(candidate.candidate_id for candidate in self.candidates)
        if len(ids) != len(set(ids)):
            raise ValueError("candidate ids must be unique")
        validate_id(self.reserve_candidate_id)
        if self.reserve_candidate_id in ids:
            raise ValueError("the reserve candidate is outside Stage 8A")
        object.__setattr__(self, "reserve_activation", _require_text(self.reserve_activation, "reserve_activation"))
        _finish(self, "modern_matcher_candidate_registry_v1")

    @classmethod
    def create(cls, **claims: Any) -> "ModernMatcherCandidateRegistry":
        return _with_fingerprint(cls, "modern_matcher_candidate_registry_v1", claims)


@dataclass(frozen=True, slots=True)
class CandidateComponent:
    schema_version: str
    component_id: str
    kind: ComponentKind
    role: str
    required: bool
    present: bool
    identity_established: bool
    locked_for_offline_use: bool
    filename: str | None
    sha256: str | None
    size_bytes: int | None
    format: str | None
    source_locator: str | None
    source_commit: str | None
    source_archive_sha256: str | None
    model_variant: str | None
    embedding_dimension: int | None
    training_provenance: str | None
    license_record_fingerprint: str | None
    notes: tuple[str, ...]
    fingerprint: str

    def __post_init__(self) -> None:
        if str(self.schema_version) != STAGE8A_SCHEMA_VERSION:
            raise ValueError("unsupported candidate component schema version")
        validate_id(self.component_id)
        object.__setattr__(self, "kind", _enum(self.kind, ComponentKind, "kind"))
        object.__setattr__(self, "role", _require_text(self.role, "role"))
        for name in ("required", "present", "identity_established", "locked_for_offline_use"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be a boolean")
        if self.filename is not None and self.filename != self.filename.strip():
            raise ValueError(
                "component filename must not contain surrounding whitespace"
            )
        for name in ("filename", "format", "source_locator", "model_variant", "training_provenance"):
            object.__setattr__(self, name, _require_optional_text(getattr(self, name), name))
        object.__setattr__(self, "sha256", _require_optional_sha256(self.sha256, "sha256"))
        object.__setattr__(self, "source_archive_sha256", _require_optional_sha256(self.source_archive_sha256, "source_archive_sha256"))
        object.__setattr__(self, "source_commit", _require_commit(self.source_commit, "source_commit"))
        object.__setattr__(self, "license_record_fingerprint", _require_optional_sha256(self.license_record_fingerprint, "license_record_fingerprint"))
        if self.size_bytes is not None:
            size = require_exact_int(self.size_bytes, "size_bytes")
            if size < 0:
                raise ValueError("size_bytes must not be negative")
            object.__setattr__(self, "size_bytes", size)
        if self.embedding_dimension is not None:
            dimension = require_exact_int(self.embedding_dimension, "embedding_dimension")
            if dimension <= 0:
                raise ValueError("embedding_dimension must be positive")
            object.__setattr__(self, "embedding_dimension", dimension)
        object.__setattr__(self, "notes", _text_tuple(self.notes, "notes", unique=False))
        if self.kind is ComponentKind.CHECKPOINT and self.present and self.identity_established:
            for name in ("filename", "sha256", "size_bytes", "format", "model_variant", "embedding_dimension", "training_provenance"):
                if getattr(self, name) is None:
                    raise ValueError(f"an identified checkpoint requires {name}")
        if self.locked_for_offline_use and not (self.present and self.identity_established):
            raise ValueError("only a present identified component can be locked offline")
        _finish(self, "candidate_component_v1")

    @classmethod
    def create(cls, **claims: Any) -> "CandidateComponent":
        return _with_fingerprint(cls, "candidate_component_v1", claims)


@dataclass(frozen=True, slots=True)
class CandidateLicenseRecord:
    schema_version: str
    record_id: str
    scope: LicenseScope
    subject: str
    license_name: str | None
    spdx_identifier: str | None
    license_document_sha256: str | None
    license_document_url: str | None
    conclusion: LicenseConclusion
    academic_benchmark_allowed: bool | None
    nist_image_processing_allowed: bool | None
    cross_algorithm_comparison_allowed: bool | None
    publish_counts_and_rates_allowed: bool | None
    publish_metadata_and_hashes_allowed: bool | None
    hold_and_execute_allowed: bool | None
    redistribution_allowed: bool | None
    restrictions: tuple[str, ...]
    evidence: tuple[str, ...]
    fingerprint: str

    def __post_init__(self) -> None:
        if str(self.schema_version) != STAGE8A_SCHEMA_VERSION:
            raise ValueError("unsupported candidate licence schema version")
        validate_id(self.record_id)
        object.__setattr__(self, "scope", _enum(self.scope, LicenseScope, "scope"))
        object.__setattr__(self, "conclusion", _enum(self.conclusion, LicenseConclusion, "conclusion"))
        object.__setattr__(self, "subject", _require_text(self.subject, "subject"))
        for name in ("license_name", "spdx_identifier", "license_document_url"):
            object.__setattr__(self, name, _require_optional_text(getattr(self, name), name))
        object.__setattr__(self, "license_document_sha256", _require_optional_sha256(self.license_document_sha256, "license_document_sha256"))
        for name in (
            "academic_benchmark_allowed",
            "nist_image_processing_allowed",
            "cross_algorithm_comparison_allowed",
            "publish_counts_and_rates_allowed",
            "publish_metadata_and_hashes_allowed",
            "hold_and_execute_allowed",
            "redistribution_allowed",
        ):
            if getattr(self, name) is not None and type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be true, false, or null")
        object.__setattr__(self, "restrictions", _text_tuple(self.restrictions, "restrictions", unique=False))
        object.__setattr__(self, "evidence", _text_tuple(self.evidence, "evidence", unique=False))
        if not self.evidence:
            raise ValueError("every licence conclusion requires inspection evidence")
        if self.conclusion is LicenseConclusion.CLEAR:
            if self.license_name is None or self.license_document_sha256 is None:
                raise ValueError(
                    "a clear licence conclusion requires an identified, hashed "
                    "licence or upstream rights document"
                )
            required = (
                self.academic_benchmark_allowed,
                self.nist_image_processing_allowed,
                self.cross_algorithm_comparison_allowed,
                self.publish_counts_and_rates_allowed,
                self.publish_metadata_and_hashes_allowed,
                self.hold_and_execute_allowed,
            )
            if not all(value is True for value in required):
                raise ValueError("a clear licence conclusion requires every Stage 8A permission")
        _finish(self, "candidate_license_record_v1")

    @classmethod
    def create(cls, **claims: Any) -> "CandidateLicenseRecord":
        return _with_fingerprint(cls, "candidate_license_record_v1", claims)


@dataclass(frozen=True, slots=True)
class CandidateArtifactManifest:
    schema_version: str
    manifest_id: str
    candidate_id: str
    registry_fingerprint: str
    candidate_fingerprint: str
    source_commit: str | None
    source_archive_sha256: str | None
    components: tuple[CandidateComponent, ...]
    license_records: tuple[CandidateLicenseRecord, ...]
    storage_reference: str | None
    acquisition_method: str
    acquired_utc: str
    fingerprint: str

    def __post_init__(self) -> None:
        if str(self.schema_version) != STAGE8A_SCHEMA_VERSION:
            raise ValueError("unsupported candidate artefact manifest schema version")
        validate_id(self.manifest_id)
        validate_id(self.candidate_id)
        object.__setattr__(self, "registry_fingerprint", _require_sha256(self.registry_fingerprint, "registry_fingerprint"))
        object.__setattr__(self, "candidate_fingerprint", _require_sha256(self.candidate_fingerprint, "candidate_fingerprint"))
        object.__setattr__(self, "source_commit", _require_commit(self.source_commit, "source_commit"))
        object.__setattr__(self, "source_archive_sha256", _require_optional_sha256(self.source_archive_sha256, "source_archive_sha256"))
        object.__setattr__(self, "components", tuple(self.components))
        object.__setattr__(self, "license_records", tuple(self.license_records))
        component_ids = tuple(item.component_id for item in self.components)
        record_ids = tuple(item.record_id for item in self.license_records)
        if len(component_ids) != len(set(component_ids)):
            raise ValueError("component ids must be unique within a manifest")
        if len(record_ids) != len(set(record_ids)):
            raise ValueError("licence record ids must be unique within a manifest")
        licence_fingerprints = {item.fingerprint for item in self.license_records}
        unknown_licences = {
            item.license_record_fingerprint
            for item in self.components
            if item.license_record_fingerprint is not None
            and item.license_record_fingerprint not in licence_fingerprints
        }
        if unknown_licences:
            raise ValueError(
                "component licence references must resolve inside the manifest"
            )
        if (
            self.storage_reference is not None
            and self.storage_reference != self.storage_reference.strip()
        ):
            raise ValueError(
                "storage_reference must not contain surrounding whitespace"
            )
        object.__setattr__(self, "storage_reference", _require_optional_text(self.storage_reference, "storage_reference"))
        object.__setattr__(self, "acquisition_method", _require_text(self.acquisition_method, "acquisition_method"))
        object.__setattr__(self, "acquired_utc", _require_text(self.acquired_utc, "acquired_utc"))
        _finish(self, "candidate_artifact_manifest_v1")

    @property
    def checkpoint_components(self) -> tuple[CandidateComponent, ...]:
        return tuple(item for item in self.components if item.kind is ComponentKind.CHECKPOINT)

    @property
    def required_components_available_offline(self) -> bool:
        required = tuple(item for item in self.components if item.required)
        return bool(required) and all(item.locked_for_offline_use for item in required)

    @classmethod
    def create(cls, **claims: Any) -> "CandidateArtifactManifest":
        return _with_fingerprint(cls, "candidate_artifact_manifest_v1", claims)


@dataclass(frozen=True, slots=True)
class PreprocessingOperation:
    schema_version: str
    operation_id: str
    action: str | None
    upstream_source_kind: str | None
    upstream_source_reference: str | None
    source_fingerprint: str | None
    fingerprint: str

    def __post_init__(self) -> None:
        if str(self.schema_version) != STAGE8A_SCHEMA_VERSION:
            raise ValueError("unsupported preprocessing operation schema version")
        validate_id(self.operation_id)
        for name in ("action", "upstream_source_kind", "upstream_source_reference"):
            object.__setattr__(self, name, _require_optional_text(getattr(self, name), name))
        object.__setattr__(self, "source_fingerprint", _require_optional_sha256(self.source_fingerprint, "source_fingerprint"))
        supplied = (self.upstream_source_kind, self.upstream_source_reference, self.source_fingerprint)
        if self.action is not None and not all(value is not None for value in supplied):
            raise ValueError("a documented preprocessing action requires an upstream source and fingerprint")
        _finish(self, "preprocessing_operation_v1")

    @classmethod
    def create(cls, **claims: Any) -> "PreprocessingOperation":
        return _with_fingerprint(cls, "preprocessing_operation_v1", claims)


REQUIRED_PREPROCESSING_OPERATIONS = (
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


@dataclass(frozen=True, slots=True)
class CandidatePreprocessingProfile:
    schema_version: str
    profile_id: str
    operations: tuple[PreprocessingOperation, ...]
    dataset_independent: bool
    subject_independent: bool
    label_independent: bool
    canonical_png_to_tensor_complete: bool
    fingerprint: str

    def __post_init__(self) -> None:
        if str(self.schema_version) != STAGE8A_SCHEMA_VERSION:
            raise ValueError("unsupported preprocessing profile schema version")
        validate_id(self.profile_id)
        object.__setattr__(self, "operations", tuple(self.operations))
        ids = tuple(item.operation_id for item in self.operations)
        if len(ids) != len(set(ids)):
            raise ValueError("preprocessing operation ids must be unique")
        for name in ("dataset_independent", "subject_independent", "label_independent", "canonical_png_to_tensor_complete"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be a boolean")
        if self.canonical_png_to_tensor_complete:
            if set(ids) != set(REQUIRED_PREPROCESSING_OPERATIONS):
                raise ValueError("a complete preprocessing profile must document every required operation exactly once")
            if any(item.action is None for item in self.operations):
                raise ValueError("a complete preprocessing profile cannot contain an undocumented action")
        _finish(self, "candidate_preprocessing_profile_v1")

    @classmethod
    def create(cls, **claims: Any) -> "CandidatePreprocessingProfile":
        return _with_fingerprint(cls, "candidate_preprocessing_profile_v1", claims)


@dataclass(frozen=True, slots=True)
class RepresentationBranch:
    schema_version: str
    branch_id: str
    kind: str
    shape: tuple[int, ...]
    included_in_final_score: bool
    combination_rule: str | None
    fingerprint: str

    def __post_init__(self) -> None:
        if str(self.schema_version) != STAGE8A_SCHEMA_VERSION:
            raise ValueError("unsupported representation branch schema version")
        validate_id(self.branch_id)
        object.__setattr__(self, "kind", _require_text(self.kind, "kind"))
        shape = tuple(require_exact_int(value, "shape dimension") for value in self.shape)
        if not shape or any(value <= 0 for value in shape):
            raise ValueError("representation branch dimensions must be positive")
        object.__setattr__(self, "shape", shape)
        if type(self.included_in_final_score) is not bool:
            raise ValueError("included_in_final_score must be a boolean")
        object.__setattr__(self, "combination_rule", _require_optional_text(self.combination_rule, "combination_rule"))
        if self.included_in_final_score and self.combination_rule is None:
            raise ValueError("a scored representation branch requires a combination rule")
        _finish(self, "representation_branch_v1")

    @classmethod
    def create(cls, **claims: Any) -> "RepresentationBranch":
        return _with_fingerprint(cls, "representation_branch_v1", claims)


@dataclass(frozen=True, slots=True)
class CandidateRepresentationProfile:
    schema_version: str
    profile_id: str
    representation_kind: str
    representation_shape: tuple[int, ...]
    representation_dtype: str
    representation_normalization: str
    fixed_length: bool
    branches: tuple[RepresentationBranch, ...]
    fusion_rule: str
    pose_information_required: bool
    pose_handling: str
    complete: bool
    fingerprint: str

    def __post_init__(self) -> None:
        if str(self.schema_version) != STAGE8A_SCHEMA_VERSION:
            raise ValueError("unsupported representation profile schema version")
        validate_id(self.profile_id)
        for name in (
            "representation_kind",
            "representation_dtype",
            "representation_normalization",
            "fusion_rule",
            "pose_handling",
        ):
            object.__setattr__(self, name, _require_text(getattr(self, name), name))
        shape = tuple(require_exact_int(value, "representation_shape dimension") for value in self.representation_shape)
        if not shape or any(value <= 0 for value in shape):
            raise ValueError("representation dimensions must be positive")
        object.__setattr__(self, "representation_shape", shape)
        object.__setattr__(self, "branches", tuple(self.branches))
        if len({item.branch_id for item in self.branches}) != len(self.branches):
            raise ValueError("representation branch ids must be unique")
        for name in ("fixed_length", "pose_information_required", "complete"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be a boolean")
        if self.complete and not any(item.included_in_final_score for item in self.branches):
            raise ValueError("a complete representation must identify a scored branch")
        _finish(self, "candidate_representation_profile_v1")

    @classmethod
    def create(cls, **claims: Any) -> "CandidateRepresentationProfile":
        return _with_fingerprint(cls, "candidate_representation_profile_v1", claims)


@dataclass(frozen=True, slots=True)
class CandidateScoreProfile:
    schema_version: str
    profile_id: str
    compare_api: str
    similarity_function: str
    score_direction: str
    score_range: str | None
    score_minimum: str | None
    score_maximum: str | None
    normalization: str
    symmetric: bool
    fusion: str
    reweighting: str
    realignment_trigger: str
    fallback_behavior: str
    returns_finite_numeric_raw_score: bool
    hidden_threshold: bool
    complete: bool
    fingerprint: str

    def __post_init__(self) -> None:
        if str(self.schema_version) != STAGE8A_SCHEMA_VERSION:
            raise ValueError("unsupported score profile schema version")
        validate_id(self.profile_id)
        for name in (
            "compare_api",
            "similarity_function",
            "score_direction",
            "normalization",
            "fusion",
            "reweighting",
            "realignment_trigger",
            "fallback_behavior",
        ):
            object.__setattr__(self, name, _require_text(getattr(self, name), name))
        object.__setattr__(self, "score_range", _require_optional_text(self.score_range, "score_range"))
        object.__setattr__(
            self,
            "score_minimum",
            _decimal_text(self.score_minimum, "score_minimum"),
        )
        object.__setattr__(
            self,
            "score_maximum",
            _decimal_text(self.score_maximum, "score_maximum"),
        )
        if (self.score_minimum is None) is not (self.score_maximum is None):
            raise ValueError("numeric score bounds must be supplied together")
        if (
            self.score_minimum is not None
            and Decimal(self.score_minimum) >= Decimal(self.score_maximum)
        ):
            raise ValueError("score_minimum must be lower than score_maximum")
        for name in ("symmetric", "returns_finite_numeric_raw_score", "hidden_threshold", "complete"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be a boolean")
        if self.complete and (not self.returns_finite_numeric_raw_score or self.hidden_threshold):
            raise ValueError("a complete score profile requires a finite raw score and no hidden threshold")
        _finish(self, "candidate_score_profile_v1")

    @classmethod
    def create(cls, **claims: Any) -> "CandidateScoreProfile":
        return _with_fingerprint(cls, "candidate_score_profile_v1", claims)


@dataclass(frozen=True, slots=True)
class CandidateDeterminismReport:
    schema_version: str
    report_id: str
    tested: bool
    runtime_kind: str | None
    runtime_version: str | None
    driver_version: str | None
    device_class: str | None
    repeated_extraction_equal: bool | None
    repeated_comparison_equal: bool | None
    single_image_vs_batch_equal: bool | None
    process_restart_equal: bool | None
    process_restart_representation_equal: bool | None
    input_order_equal: bool | None
    bitwise_equal: bool | None
    numeric_tolerance: str | None
    maximum_observed_score_drift: str | None
    within_predeclared_tolerance: bool | None
    nondeterminism_reason: str | None
    runtime_restrictions: tuple[str, ...]
    decision_safe: bool | None
    inspected_utc: str
    fingerprint: str

    def __post_init__(self) -> None:
        if str(self.schema_version) != STAGE8A_SCHEMA_VERSION:
            raise ValueError("unsupported determinism report schema version")
        validate_id(self.report_id)
        if type(self.tested) is not bool:
            raise ValueError("tested must be a boolean")
        for name in ("runtime_kind", "runtime_version", "driver_version", "device_class", "nondeterminism_reason"):
            object.__setattr__(self, name, _require_optional_text(getattr(self, name), name))
        for name in (
            "repeated_extraction_equal",
            "repeated_comparison_equal",
            "single_image_vs_batch_equal",
            "process_restart_equal",
            "process_restart_representation_equal",
            "input_order_equal",
            "bitwise_equal",
            "within_predeclared_tolerance",
            "decision_safe",
        ):
            value = getattr(self, name)
            if value is not None and type(value) is not bool:
                raise ValueError(f"{name} must be true, false, or null")
        object.__setattr__(self, "numeric_tolerance", _decimal_text(self.numeric_tolerance, "numeric_tolerance", non_negative=True))
        object.__setattr__(self, "maximum_observed_score_drift", _decimal_text(self.maximum_observed_score_drift, "maximum_observed_score_drift", non_negative=True))
        object.__setattr__(self, "runtime_restrictions", _text_tuple(self.runtime_restrictions, "runtime_restrictions", unique=False))
        object.__setattr__(self, "inspected_utc", _require_text(self.inspected_utc, "inspected_utc"))
        if self.tested:
            if self.runtime_kind not in {"CPU", "CUDA"}:
                raise ValueError("tested runtime_kind must be CPU or CUDA")
            for name in (
                "runtime_kind",
                "runtime_version",
                "repeated_extraction_equal",
                "repeated_comparison_equal",
                "single_image_vs_batch_equal",
                "process_restart_equal",
                "process_restart_representation_equal",
                "input_order_equal",
                "bitwise_equal",
                "within_predeclared_tolerance",
            ):
                if getattr(self, name) is None:
                    raise ValueError(f"a tested determinism report requires {name}")
            if self.runtime_kind == "CUDA" and (self.driver_version is None or self.device_class is None):
                raise ValueError("a CUDA qualification requires exact driver and device class")
            if self.bitwise_equal is False and (self.numeric_tolerance is None or self.maximum_observed_score_drift is None or self.nondeterminism_reason is None):
                raise ValueError("non-bitwise determinism requires tolerance, drift, and reason")
            if self.bitwise_equal is False and not self.runtime_restrictions:
                raise ValueError(
                    "non-bitwise determinism requires explicit runtime restrictions"
                )
            equality_observations = (
                self.repeated_extraction_equal,
                self.repeated_comparison_equal,
                self.single_image_vs_batch_equal,
                self.process_restart_equal,
                self.process_restart_representation_equal,
                self.input_order_equal,
            )
            if self.bitwise_equal is not all(equality_observations):
                raise ValueError(
                    "bitwise_equal must be derived from every mandatory "
                    "determinism observation"
                )
            representation_observations_equal = (
                self.repeated_extraction_equal
                and self.single_image_vs_batch_equal
                and self.process_restart_representation_equal
            )
            expected_within_tolerance = (
                representation_observations_equal
                and (
                    self.bitwise_equal
                    or Decimal(self.maximum_observed_score_drift)
                    <= Decimal(self.numeric_tolerance)
                )
            )
            if self.within_predeclared_tolerance is not expected_within_tolerance:
                raise ValueError(
                    "within_predeclared_tolerance must be derived from maximum "
                    "drift and the predeclared tolerance"
                )
            if self.decision_safe is not self.bitwise_equal:
                raise ValueError(
                    "without a separate threshold guard model, only bitwise "
                    "determinism is decision-safe"
                )
        _finish(self, "candidate_determinism_report_v1")

    @classmethod
    def create(cls, **claims: Any) -> "CandidateDeterminismReport":
        return _with_fingerprint(cls, "candidate_determinism_report_v1", claims)


@dataclass(frozen=True, slots=True)
class CandidateOperationalReport:
    schema_version: str
    report_id: str
    measured: bool
    startup_seconds: str | None
    model_load_seconds: str | None
    extraction_seconds: str | None
    comparison_seconds: str | None
    peak_ram_bytes: int | None
    peak_vram_bytes: int | None
    artifact_disk_bytes: int | None
    projected_12000_extractions_seconds: str | None
    projected_6000_comparisons_seconds: str | None
    max_projected_12000_extractions_seconds: str | None
    max_projected_6000_comparisons_seconds: str | None
    max_peak_ram_bytes: int | None
    max_peak_vram_bytes: int | None
    max_artifact_disk_bytes: int | None
    operationally_feasible: bool | None
    measurement_scope: str
    inspected_utc: str
    fingerprint: str

    def __post_init__(self) -> None:
        if str(self.schema_version) != STAGE8A_SCHEMA_VERSION:
            raise ValueError("unsupported operational report schema version")
        validate_id(self.report_id)
        if type(self.measured) is not bool:
            raise ValueError("measured must be a boolean")
        for name in (
            "startup_seconds",
            "model_load_seconds",
            "extraction_seconds",
            "comparison_seconds",
            "projected_12000_extractions_seconds",
            "projected_6000_comparisons_seconds",
            "max_projected_12000_extractions_seconds",
            "max_projected_6000_comparisons_seconds",
        ):
            object.__setattr__(self, name, _decimal_text(getattr(self, name), name, non_negative=True))
        for name in (
            "peak_ram_bytes",
            "peak_vram_bytes",
            "artifact_disk_bytes",
            "max_peak_ram_bytes",
            "max_peak_vram_bytes",
            "max_artifact_disk_bytes",
        ):
            value = getattr(self, name)
            if value is not None:
                value = require_exact_int(value, name)
                if value < 0:
                    raise ValueError(f"{name} must not be negative")
                object.__setattr__(self, name, value)
        if self.operationally_feasible is not None and type(self.operationally_feasible) is not bool:
            raise ValueError("operationally_feasible must be true, false, or null")
        object.__setattr__(self, "measurement_scope", _require_text(self.measurement_scope, "measurement_scope"))
        object.__setattr__(self, "inspected_utc", _require_text(self.inspected_utc, "inspected_utc"))
        if self.measured:
            required = (
                self.startup_seconds,
                self.model_load_seconds,
                self.extraction_seconds,
                self.comparison_seconds,
                self.peak_ram_bytes,
                self.peak_vram_bytes,
                self.artifact_disk_bytes,
                self.projected_12000_extractions_seconds,
                self.projected_6000_comparisons_seconds,
                self.max_projected_12000_extractions_seconds,
                self.max_projected_6000_comparisons_seconds,
                self.max_peak_ram_bytes,
                self.max_peak_vram_bytes,
                self.max_artifact_disk_bytes,
                self.operationally_feasible,
            )
            if any(value is None for value in required):
                raise ValueError(
                    "a measured operational report requires every CPU/RAM/disk/time "
                    "measurement, predeclared limit, and feasibility conclusion"
                )
            expected_feasible = (
                Decimal(self.projected_12000_extractions_seconds)
                <= Decimal(self.max_projected_12000_extractions_seconds)
                and Decimal(self.projected_6000_comparisons_seconds)
                <= Decimal(self.max_projected_6000_comparisons_seconds)
                and self.peak_ram_bytes <= self.max_peak_ram_bytes
                and self.peak_vram_bytes <= self.max_peak_vram_bytes
                and self.artifact_disk_bytes <= self.max_artifact_disk_bytes
            )
            if self.operationally_feasible is not expected_feasible:
                raise ValueError(
                    "operationally_feasible must be derived from every recorded "
                    "time, RAM, VRAM, and disk limit"
                )
        _finish(self, "candidate_operational_report_v1")

    @classmethod
    def create(cls, **claims: Any) -> "CandidateOperationalReport":
        return _with_fingerprint(cls, "candidate_operational_report_v1", claims)


@dataclass(frozen=True, slots=True)
class RuntimeProbeResult:
    """Content-addressed, publication-safe evidence from one smoke execution."""

    schema_version: str
    candidate_fingerprint: str
    artifact_manifest_fingerprint: str
    left_fixture_hash: str
    right_fixture_hash: str
    left_representation_hash: str
    right_representation_hash: str
    repeated_self_representation_hash: str
    repeated_left_representation_hash: str
    batch_left_representation_hash: str
    batch_right_representation_hash: str
    restarted_left_representation_hash: str
    restarted_right_representation_hash: str
    left_score_hash: str
    reverse_score_hash: str
    repeated_score_hash: str
    restarted_score_hash: str
    extraction_calls: int
    comparison_calls: int
    no_representation_persistence: bool
    process_restart_isolated: bool
    offline_execution_proven: bool
    isolation_evidence_fingerprint: str | None
    determinism_report: CandidateDeterminismReport
    operational_report: CandidateOperationalReport
    fingerprint: str

    def __post_init__(self) -> None:
        if str(self.schema_version) != STAGE8A_SCHEMA_VERSION:
            raise ValueError("unsupported runtime probe schema version")
        for name in (
            "candidate_fingerprint",
            "artifact_manifest_fingerprint",
            "left_fixture_hash",
            "right_fixture_hash",
            "left_representation_hash",
            "right_representation_hash",
            "repeated_self_representation_hash",
            "repeated_left_representation_hash",
            "batch_left_representation_hash",
            "batch_right_representation_hash",
            "restarted_left_representation_hash",
            "restarted_right_representation_hash",
            "left_score_hash",
            "reverse_score_hash",
            "repeated_score_hash",
            "restarted_score_hash",
        ):
            object.__setattr__(
                self, name, _require_sha256(getattr(self, name), name)
            )
        for name, minimum in (("extraction_calls", 4), ("comparison_calls", 3)):
            value = require_exact_int(getattr(self, name), name)
            if value < minimum:
                raise ValueError(
                    f"the smoke probe requires at least {minimum} {name}"
                )
            object.__setattr__(self, name, value)
        if self.no_representation_persistence is not True:
            raise ValueError("Stage 8A may not persist representations")
        for name in ("process_restart_isolated", "offline_execution_proven"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be a boolean")
        object.__setattr__(
            self,
            "isolation_evidence_fingerprint",
            _require_optional_sha256(
                self.isolation_evidence_fingerprint,
                "isolation_evidence_fingerprint",
            ),
        )
        if not (
            self.process_restart_isolated
            and self.offline_execution_proven
            and self.isolation_evidence_fingerprint is not None
        ):
            raise ValueError(
                "a completed smoke probe requires an isolated process restart "
                "and content-addressed offline attestation"
            )
        expected_observations = {
            "repeated_extraction_equal": self.left_representation_hash
            == self.repeated_self_representation_hash
            == self.repeated_left_representation_hash,
            "repeated_comparison_equal": self.left_score_hash
            == self.repeated_score_hash,
            "single_image_vs_batch_equal": (
                self.batch_left_representation_hash
                == self.left_representation_hash
                and self.batch_right_representation_hash
                == self.right_representation_hash
            ),
            "process_restart_equal": self.left_score_hash
            == self.restarted_score_hash,
            "process_restart_representation_equal": (
                self.left_representation_hash
                == self.restarted_left_representation_hash
                and self.right_representation_hash
                == self.restarted_right_representation_hash
            ),
            "input_order_equal": self.left_score_hash
            == self.reverse_score_hash,
        }
        for name, expected in expected_observations.items():
            if getattr(self.determinism_report, name) is not expected:
                raise ValueError(
                    f"determinism {name} contradicts the stored observation hashes"
                )
        if self.determinism_report.bitwise_equal is not all(
            expected_observations.values()
        ):
            raise ValueError(
                "determinism bitwise_equal contradicts the stored observation hashes"
            )
        if not self.determinism_report.tested:
            raise ValueError("a runtime probe requires a tested determinism report")
        if not self.operational_report.measured:
            raise ValueError("a runtime probe requires a measured operational report")
        _finish(self, "runtime_probe_result_v1")

    @classmethod
    def create(cls, **claims: Any) -> "RuntimeProbeResult":
        return _with_fingerprint(cls, "runtime_probe_result_v1", claims)


@dataclass(frozen=True, slots=True)
class QualificationGateResult:
    schema_version: str
    gate: QualificationGate
    passed: bool
    failures: tuple[str, ...]
    evidence: tuple[str, ...]
    fingerprint: str

    def __post_init__(self) -> None:
        if str(self.schema_version) != STAGE8A_SCHEMA_VERSION:
            raise ValueError("unsupported qualification gate result schema version")
        object.__setattr__(self, "gate", _enum(self.gate, QualificationGate, "gate"))
        if type(self.passed) is not bool:
            raise ValueError("passed must be a boolean")
        object.__setattr__(self, "failures", _text_tuple(self.failures, "failures", unique=False))
        object.__setattr__(self, "evidence", _text_tuple(self.evidence, "evidence", unique=False))
        if self.passed and self.failures:
            raise ValueError("a passing gate cannot carry failures")
        if not self.passed and not self.failures:
            raise ValueError("a failing gate must state exact failures")
        if not self.evidence:
            raise ValueError("every gate conclusion requires evidence")
        runtime_evidence_gates = {
            QualificationGate.FINITE_RAW_SCORE,
            QualificationGate.INDEPENDENT_SELF,
            QualificationGate.DETERMINISM,
            QualificationGate.OFFLINE_OPERATION,
            QualificationGate.OPERATIONAL_FEASIBILITY,
        }
        if self.passed and self.gate in runtime_evidence_gates:
            fingerprints = tuple(
                item.removeprefix("sha256:").lower()
                for item in self.evidence
                if item.lower().startswith("sha256:")
            )
            if not any(
                len(digest) == 64 and set(digest) <= _HEX
                for digest in fingerprints
            ):
                raise ValueError(
                    "a passing runtime gate requires content-addressed probe "
                    "or isolation evidence"
                )
        _finish(self, "qualification_gate_result_v1")

    @classmethod
    def create(cls, **claims: Any) -> "QualificationGateResult":
        return _with_fingerprint(cls, "qualification_gate_result_v1", claims)


@dataclass(frozen=True, slots=True)
class DecisionPath:
    schema_version: str
    kind: DecisionPathKind
    documented_threshold: str | None
    threshold_source: str | None
    threshold_source_fingerprint: str | None
    threshold_source_kind: ThresholdSourceKind
    checkpoint_fingerprint: str | None
    development_cohort: str | None
    development_cohort_kind: DevelopmentCohortKind
    calibration_protocol_fingerprint: str | None
    cohort_is_independent_of_evaluation: bool
    legally_and_practically_available: bool
    fingerprint: str

    def __post_init__(self) -> None:
        if str(self.schema_version) != STAGE8A_SCHEMA_VERSION:
            raise ValueError("unsupported decision path schema version")
        object.__setattr__(self, "kind", _enum(self.kind, DecisionPathKind, "kind"))
        object.__setattr__(
            self,
            "threshold_source_kind",
            _enum(
                self.threshold_source_kind,
                ThresholdSourceKind,
                "threshold_source_kind",
            ),
        )
        object.__setattr__(
            self,
            "development_cohort_kind",
            _enum(
                self.development_cohort_kind,
                DevelopmentCohortKind,
                "development_cohort_kind",
            ),
        )
        object.__setattr__(
            self,
            "documented_threshold",
            _decimal_text(self.documented_threshold, "documented_threshold"),
        )
        for name in ("threshold_source", "development_cohort"):
            object.__setattr__(self, name, _require_optional_text(getattr(self, name), name))
        object.__setattr__(
            self,
            "threshold_source_fingerprint",
            _require_optional_sha256(
                self.threshold_source_fingerprint,
                "threshold_source_fingerprint",
            ),
        )
        object.__setattr__(self, "checkpoint_fingerprint", _require_optional_sha256(self.checkpoint_fingerprint, "checkpoint_fingerprint"))
        object.__setattr__(self, "calibration_protocol_fingerprint", _require_optional_sha256(self.calibration_protocol_fingerprint, "calibration_protocol_fingerprint"))
        for name in ("cohort_is_independent_of_evaluation", "legally_and_practically_available"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be a boolean")
        if self.kind is DecisionPathKind.NONE:
            if any(value is not None for value in (self.documented_threshold, self.threshold_source, self.threshold_source_fingerprint, self.checkpoint_fingerprint, self.development_cohort, self.calibration_protocol_fingerprint)):
                raise ValueError("a missing decision path cannot carry threshold or calibration claims")
            if (
                self.threshold_source_kind is not ThresholdSourceKind.NONE
                or self.development_cohort_kind is not DevelopmentCohortKind.NONE
            ):
                raise ValueError(
                    "a missing decision path cannot claim a threshold source or cohort"
                )
        elif self.kind is DecisionPathKind.DOCUMENTED_CHECKPOINT_THRESHOLD:
            if any(value is None for value in (self.documented_threshold, self.threshold_source, self.threshold_source_fingerprint, self.checkpoint_fingerprint)):
                raise ValueError(
                    "a documented threshold must name and hash its source and "
                    "bind the exact checkpoint"
                )
            if (
                self.threshold_source_kind
                is not ThresholdSourceKind.UPSTREAM_DOCUMENTED_CHECKPOINT_THRESHOLD
            ):
                raise ValueError(
                    "paper EER, inferred FAR, and assumed cosine zero are not "
                    "documented checkpoint thresholds"
                )
            if self.development_cohort_kind is not DevelopmentCohortKind.NONE:
                raise ValueError(
                    "a documented threshold cannot claim a development cohort"
                )
            if any(
                value is not None
                for value in (
                    self.development_cohort,
                    self.calibration_protocol_fingerprint,
                )
            ):
                raise ValueError(
                    "a documented threshold cannot also carry calibration claims"
                )
        elif self.kind is DecisionPathKind.EXTERNAL_DEVELOPMENT_CALIBRATION:
            if any(value is None for value in (self.development_cohort, self.calibration_protocol_fingerprint)):
                raise ValueError("a calibration path requires a cohort and predeclared protocol")
            if not (self.cohort_is_independent_of_evaluation and self.legally_and_practically_available):
                raise ValueError("the calibration cohort must be independent, legal, and available")
            if self.development_cohort_kind is not DevelopmentCohortKind.INDEPENDENT_EXTERNAL:
                raise ValueError(
                    "SD300 or another evaluation cohort cannot be used for calibration"
                )
            if self.threshold_source_kind is not ThresholdSourceKind.NONE:
                raise ValueError(
                    "an external calibration path cannot claim a documented threshold"
                )
            if any(
                value is not None
                for value in (
                    self.documented_threshold,
                    self.threshold_source,
                    self.threshold_source_fingerprint,
                    self.checkpoint_fingerprint,
                )
            ):
                raise ValueError(
                    "an external calibration path cannot carry a checkpoint threshold"
                )
        _finish(self, "decision_path_v1")

    @classmethod
    def create(cls, **claims: Any) -> "DecisionPath":
        return _with_fingerprint(cls, "decision_path_v1", claims)


@dataclass(frozen=True, slots=True)
class CandidateQualificationReport:
    schema_version: str
    report_id: str
    candidate_id: str
    candidate_fingerprint: str
    qualified_implementation_name: str | None
    registry_fingerprint: str
    artifact_manifest: CandidateArtifactManifest
    preprocessing_profile: CandidatePreprocessingProfile | None
    representation_profile: CandidateRepresentationProfile | None
    score_profile: CandidateScoreProfile | None
    determinism_report: CandidateDeterminismReport
    operational_report: CandidateOperationalReport
    decision_path: DecisionPath
    gate_results: tuple[QualificationGateResult, ...]
    qualification_status: QualificationStatus
    static_inspection_passed: bool
    execution_attempted: bool
    smoke_qualification_passed: bool
    contract_qualification_passed: bool
    runtime_probe: RuntimeProbeResult | None
    runtime_probe_fingerprint: str | None
    raw_score_ready: bool
    decision_path_ready: bool
    license_clear: bool
    architecture_fit: bool
    official_or_author_supplied: bool
    algorithm_completeness_rank: int
    external_components_required: int
    runtime_complexity_rank: int
    estimated_adapter_lines: int
    diversity_rank: int
    paper_year: int
    qualified_utc: str
    fingerprint: str

    def __post_init__(self) -> None:
        if str(self.schema_version) != STAGE8A_SCHEMA_VERSION:
            raise ValueError("unsupported candidate qualification report schema version")
        validate_id(self.report_id)
        validate_id(self.candidate_id)
        object.__setattr__(self, "candidate_fingerprint", _require_sha256(self.candidate_fingerprint, "candidate_fingerprint"))
        object.__setattr__(
            self,
            "qualified_implementation_name",
            _require_optional_text(
                self.qualified_implementation_name,
                "qualified_implementation_name",
            ),
        )
        object.__setattr__(self, "registry_fingerprint", _require_sha256(self.registry_fingerprint, "registry_fingerprint"))
        if self.artifact_manifest.candidate_id != self.candidate_id:
            raise ValueError("qualification report and artefact manifest name different candidates")
        if self.artifact_manifest.registry_fingerprint != self.registry_fingerprint:
            raise ValueError("qualification report and artefact manifest name different registries")
        if self.artifact_manifest.candidate_fingerprint != self.candidate_fingerprint:
            raise ValueError(
                "qualification report and artefact manifest name different candidate identities"
            )
        checkpoint_variants = tuple(
            component.model_variant
            for component in self.artifact_manifest.checkpoint_components
            if component.present and component.model_variant is not None
        )
        if self.qualified_implementation_name is not None and any(
            variant not in self.qualified_implementation_name
            for variant in checkpoint_variants
        ):
            raise ValueError(
                "qualified implementation identity must name every identified "
                "checkpoint variant"
            )
        object.__setattr__(self, "gate_results", tuple(self.gate_results))
        gates = tuple(item.gate for item in self.gate_results)
        if set(gates) != set(QualificationGate) or len(gates) != len(QualificationGate):
            raise ValueError("a qualification report must contain every mandatory gate exactly once")
        object.__setattr__(self, "qualification_status", _enum(self.qualification_status, QualificationStatus, "qualification_status"))
        for name in ("static_inspection_passed", "execution_attempted", "smoke_qualification_passed", "contract_qualification_passed", "raw_score_ready", "decision_path_ready", "license_clear", "architecture_fit", "official_or_author_supplied"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be a boolean")
        object.__setattr__(
            self,
            "runtime_probe_fingerprint",
            _require_optional_sha256(
                self.runtime_probe_fingerprint, "runtime_probe_fingerprint"
            ),
        )
        if self.runtime_probe is None:
            if self.runtime_probe_fingerprint is not None:
                raise ValueError(
                    "runtime_probe_fingerprint must resolve to embedded probe evidence"
                )
        else:
            if self.runtime_probe_fingerprint != self.runtime_probe.fingerprint:
                raise ValueError(
                    "runtime_probe_fingerprint does not identify embedded probe evidence"
                )
            if self.runtime_probe.candidate_fingerprint != self.candidate_fingerprint:
                raise ValueError("runtime probe belongs to another candidate")
            if (
                self.runtime_probe.artifact_manifest_fingerprint
                != self.artifact_manifest.fingerprint
            ):
                raise ValueError("runtime probe belongs to another artifact manifest")
            if (
                self.runtime_probe.determinism_report.fingerprint
                != self.determinism_report.fingerprint
                or self.runtime_probe.operational_report.fingerprint
                != self.operational_report.fingerprint
            ):
                raise ValueError(
                    "runtime probe reports differ from the qualification report"
                )
        for name in ("algorithm_completeness_rank", "external_components_required", "runtime_complexity_rank", "estimated_adapter_lines", "diversity_rank", "paper_year"):
            value = require_exact_int(getattr(self, name), name)
            if value < 0:
                raise ValueError(f"{name} must not be negative")
            object.__setattr__(self, name, value)
        object.__setattr__(self, "qualified_utc", _require_text(self.qualified_utc, "qualified_utc"))
        passed = {item.gate: item.passed for item in self.gate_results}
        raw_gates = set(QualificationGate) - {QualificationGate.DECISION_PATH}
        expected_raw = all(passed[gate] for gate in raw_gates)
        expected_decision = expected_raw and passed[QualificationGate.DECISION_PATH]
        if self.raw_score_ready != expected_raw:
            raise ValueError("raw_score_ready must be derived from all non-decision mandatory gates")
        if self.decision_path_ready != expected_decision:
            raise ValueError("decision_path_ready must add the decision-path gate to raw readiness")
        if self.license_clear != passed[QualificationGate.LICENSE_AND_PUBLICATION]:
            raise ValueError("license_clear contradicts the licence gate")
        if self.architecture_fit != passed[QualificationGate.ARCHITECTURE_FIT]:
            raise ValueError("architecture_fit contradicts the architecture gate")
        static_gates = {
            QualificationGate.SCIENTIFIC_IDENTITY,
            QualificationGate.COMPLETE_INFERENCE,
            QualificationGate.EXACT_WEIGHTS,
            QualificationGate.COMPLETE_PREPROCESSING,
            QualificationGate.COMPLETE_REPRESENTATION,
            QualificationGate.LICENSE_AND_PUBLICATION,
        }
        score_gate = next(
            item
            for item in self.gate_results
            if item.gate is QualificationGate.FINITE_RAW_SCORE
        )
        finite_score_is_the_only_dynamic_unknown = set(score_gate.failures) <= {
            "RAW_SCORE_NOT_FINITE"
        }
        expected_static = all(passed[gate] for gate in static_gates) and (
            score_gate.passed or finite_score_is_the_only_dynamic_unknown
        )
        if self.static_inspection_passed != expected_static:
            raise ValueError("static_inspection_passed contradicts the static gates")
        if not self.static_inspection_passed and self.execution_attempted:
            raise ValueError("failed static inspection must prevent execution")
        if self.smoke_qualification_passed and not self.execution_attempted:
            raise ValueError("smoke qualification cannot pass without execution")
        if self.smoke_qualification_passed and self.runtime_probe is None:
            raise ValueError(
                "a passing smoke qualification requires a bound runtime probe"
            )
        if not self.smoke_qualification_passed and self.runtime_probe is not None:
            raise ValueError(
                "runtime probe evidence cannot be embedded when smoke did not pass"
            )
        if self.contract_qualification_passed and not (
            self.execution_attempted and self.smoke_qualification_passed
        ):
            raise ValueError(
                "contract qualification requires an executed, passing smoke qualification"
            )
        if passed[QualificationGate.COMPLETE_PREPROCESSING] and (
            self.preprocessing_profile is None
            or not self.preprocessing_profile.canonical_png_to_tensor_complete
            or not self.preprocessing_profile.dataset_independent
            or not self.preprocessing_profile.subject_independent
            or not self.preprocessing_profile.label_independent
        ):
            raise ValueError(
                "a passing preprocessing gate requires a complete independent profile"
            )
        if passed[QualificationGate.COMPLETE_REPRESENTATION] and (
            self.representation_profile is None
            or not self.representation_profile.complete
        ):
            raise ValueError(
                "a passing representation gate requires a complete profile"
            )
        if passed[QualificationGate.EXACT_WEIGHTS] and (
            self.qualified_implementation_name is None
        ):
            raise ValueError(
                "passing exact weights requires a checkpoint-derived "
                "implementation identity"
            )
        if passed[QualificationGate.FINITE_RAW_SCORE] and (
            self.score_profile is None or not self.score_profile.complete
        ):
            raise ValueError("a passing score gate requires a complete score profile")
        if passed[QualificationGate.DECISION_PATH] and (
            self.decision_path.kind is DecisionPathKind.NONE
            or self.determinism_report.decision_safe is not True
        ):
            raise ValueError(
                "a passing decision gate requires a decision-safe decision path"
            )
        if passed[QualificationGate.DETERMINISM] and (
            not self.determinism_report.tested
        ):
            raise ValueError(
                "a passing determinism gate requires tested output within its "
                "predeclared tolerance"
            )
        if passed[QualificationGate.OPERATIONAL_FEASIBILITY] and (
            not self.operational_report.measured
            or self.operational_report.operationally_feasible is not True
        ):
            raise ValueError(
                "a passing operational gate requires feasible fixture measurements"
            )
        if self.raw_score_ready and not (
            self.execution_attempted
            and self.smoke_qualification_passed
            and self.contract_qualification_passed
        ):
            raise ValueError(
                "raw-score readiness requires executed smoke and contract qualification"
            )
        if self.qualification_status is QualificationStatus.RAW_SCORE_READY and not self.raw_score_ready:
            raise ValueError("RAW_SCORE_READY requires all raw-score gates")
        if self.qualification_status is QualificationStatus.DECISION_PATH_READY and not self.decision_path_ready:
            raise ValueError("DECISION_PATH_READY requires both readiness levels")
        if self.qualification_status in (QualificationStatus.SELECTED, QualificationStatus.REJECTED):
            raise ValueError("selection state belongs in the selection decision, not a commit-4 qualification report")
        _finish(self, "candidate_qualification_report_v1")

    @property
    def exact_gate_failures(self) -> tuple[str, ...]:
        return tuple(failure for gate in self.gate_results if not gate.passed for failure in gate.failures)

    @classmethod
    def create(cls, **claims: Any) -> "CandidateQualificationReport":
        return _with_fingerprint(cls, "candidate_qualification_report_v1", claims)


@dataclass(frozen=True, slots=True)
class SelectionPolicy:
    schema_version: str
    policy_id: str
    mandatory_gates: tuple[QualificationGate, ...]
    tier_order: tuple[CandidateTier, ...]
    tie_breakers: tuple[str, ...]
    weighted_score_forbidden: bool
    unresolved_tie_action: str
    max_projected_12000_extractions_seconds: str
    max_projected_6000_comparisons_seconds: str
    max_peak_ram_bytes: int
    max_peak_vram_bytes: int
    max_artifact_disk_bytes: int
    fingerprint: str

    def __post_init__(self) -> None:
        if str(self.schema_version) != STAGE8A_SCHEMA_VERSION:
            raise ValueError("unsupported selection policy schema version")
        validate_id(self.policy_id)
        object.__setattr__(self, "mandatory_gates", tuple(_enum(item, QualificationGate, "mandatory_gates entry") for item in self.mandatory_gates))
        object.__setattr__(self, "tier_order", tuple(_enum(item, CandidateTier, "tier_order entry") for item in self.tier_order))
        object.__setattr__(self, "tie_breakers", _text_tuple(self.tie_breakers, "tie_breakers"))
        if (
            set(self.mandatory_gates) != set(QualificationGate)
            or len(self.mandatory_gates) != len(QualificationGate)
        ):
            raise ValueError(
                "selection policy must retain every mandatory gate exactly once"
            )
        if self.tier_order != (CandidateTier.A, CandidateTier.B, CandidateTier.C):
            raise ValueError("the frozen tier order is A, B, C")
        if self.weighted_score_forbidden is not True:
            raise ValueError("Stage 8A forbids weighted gate averages")
        if self.unresolved_tie_action != "fail_closed":
            raise ValueError("an unresolved tie must fail closed")
        for name in (
            "max_projected_12000_extractions_seconds",
            "max_projected_6000_comparisons_seconds",
        ):
            value = _decimal_text(getattr(self, name), name, non_negative=True)
            if value is None:
                raise ValueError(f"{name} is required")
            object.__setattr__(self, name, value)
        for name in (
            "max_peak_ram_bytes",
            "max_peak_vram_bytes",
            "max_artifact_disk_bytes",
        ):
            value = require_exact_int(getattr(self, name), name)
            if value < 0:
                raise ValueError(f"{name} must not be negative")
            object.__setattr__(self, name, value)
        _finish(self, "modern_matcher_selection_policy_v1")

    @classmethod
    def create(cls, **claims: Any) -> "SelectionPolicy":
        return _with_fingerprint(cls, "modern_matcher_selection_policy_v1", claims)


@dataclass(frozen=True, slots=True)
class RejectedCandidate:
    schema_version: str
    candidate_id: str
    qualification_fingerprint: str
    selection_state: SelectionState
    gate_failures: tuple[str, ...]
    reason: str
    fingerprint: str

    def __post_init__(self) -> None:
        if str(self.schema_version) != STAGE8A_SCHEMA_VERSION:
            raise ValueError("unsupported rejected-candidate schema version")
        validate_id(self.candidate_id)
        object.__setattr__(self, "qualification_fingerprint", _require_sha256(self.qualification_fingerprint, "qualification_fingerprint"))
        object.__setattr__(self, "selection_state", _enum(self.selection_state, SelectionState, "selection_state"))
        object.__setattr__(self, "gate_failures", _text_tuple(self.gate_failures, "gate_failures", unique=False))
        object.__setattr__(self, "reason", _require_text(self.reason, "reason"))
        if self.selection_state is not SelectionState.REJECTED:
            raise ValueError("a rejected-candidate record must be REJECTED")
        _finish(self, "rejected_candidate_v1")

    @classmethod
    def create(cls, **claims: Any) -> "RejectedCandidate":
        return _with_fingerprint(cls, "rejected_candidate_v1", claims)


@dataclass(frozen=True, slots=True)
class ModernMatcherSelectionDecision:
    schema_version: str
    decision_id: str
    outcome: Stage8AOutcome
    registry_fingerprint: str
    candidate_qualification_fingerprints: Mapping[str, str]
    selected_candidate_id: str | None
    selected_artifact_fingerprint: str | None
    selected_score_profile_fingerprint: str | None
    raw_score_candidate_id: str | None
    decision_path_kind: DecisionPathKind
    rejected_candidates: tuple[RejectedCandidate, ...]
    selection_policy_fingerprint: str
    verifier_source_commit: str
    decided_utc: str
    fingerprint: str

    def __post_init__(self) -> None:
        if str(self.schema_version) != STAGE8A_SCHEMA_VERSION:
            raise ValueError("unsupported modern matcher selection decision schema version")
        validate_id(self.decision_id)
        object.__setattr__(self, "outcome", _enum(self.outcome, Stage8AOutcome, "outcome"))
        object.__setattr__(self, "registry_fingerprint", _require_sha256(self.registry_fingerprint, "registry_fingerprint"))
        qualifications = {str(candidate_id): _require_sha256(value, f"candidate_qualification_fingerprints[{candidate_id}]") for candidate_id, value in dict(self.candidate_qualification_fingerprints).items()}
        for candidate_id in qualifications:
            validate_id(candidate_id)
        object.__setattr__(self, "candidate_qualification_fingerprints", MappingProxyType(qualifications))
        for name in ("selected_candidate_id", "raw_score_candidate_id"):
            value = getattr(self, name)
            if value is not None:
                validate_id(value)
        for name in ("selected_artifact_fingerprint", "selected_score_profile_fingerprint"):
            object.__setattr__(self, name, _require_optional_sha256(getattr(self, name), name))
        object.__setattr__(self, "decision_path_kind", _enum(self.decision_path_kind, DecisionPathKind, "decision_path_kind"))
        object.__setattr__(self, "rejected_candidates", tuple(self.rejected_candidates))
        object.__setattr__(self, "selection_policy_fingerprint", _require_sha256(self.selection_policy_fingerprint, "selection_policy_fingerprint"))
        verifier_commit = _require_commit(
            self.verifier_source_commit, "verifier_source_commit"
        )
        if verifier_commit is None:
            raise ValueError("verifier_source_commit is required")
        object.__setattr__(self, "verifier_source_commit", verifier_commit)
        object.__setattr__(self, "decided_utc", _require_text(self.decided_utc, "decided_utc"))
        selected_fields = (self.selected_candidate_id, self.selected_artifact_fingerprint, self.selected_score_profile_fingerprint)
        if self.outcome is Stage8AOutcome.MODERN_MATCHER_SELECTED:
            if any(value is None for value in selected_fields) or self.decision_path_kind is DecisionPathKind.NONE:
                raise ValueError("MODERN_MATCHER_SELECTED requires candidate, artefact, score profile, and decision path")
            if self.raw_score_candidate_id not in (None, self.selected_candidate_id):
                raise ValueError("the selected candidate is also the raw-score candidate")
        elif self.outcome is Stage8AOutcome.QUALIFIED_FOR_RAW_SCORES_ONLY:
            if any(value is not None for value in selected_fields) or self.raw_score_candidate_id is None or self.decision_path_kind is not DecisionPathKind.NONE:
                raise ValueError("raw-score-only outcome names no selected integration and no decision path")
        else:
            if any(value is not None for value in selected_fields) or self.raw_score_candidate_id is not None or self.decision_path_kind is not DecisionPathKind.NONE:
                raise ValueError("NO_MODERN_MATCHER_READY cannot name a candidate or decision path")
        qualification_ids = set(qualifications)
        for name in ("selected_candidate_id", "raw_score_candidate_id"):
            candidate_id = getattr(self, name)
            if candidate_id is not None and candidate_id not in qualification_ids:
                raise ValueError(f"{name} has no bound qualification report")
        rejected_ids = tuple(item.candidate_id for item in self.rejected_candidates)
        if len(rejected_ids) != len(set(rejected_ids)):
            raise ValueError("rejected candidate ids must be unique")
        for rejected in self.rejected_candidates:
            if rejected.candidate_id not in qualifications:
                raise ValueError("a rejected candidate has no bound qualification report")
            if rejected.qualification_fingerprint != qualifications[rejected.candidate_id]:
                raise ValueError("a rejected candidate names another qualification report")
        non_rejected = {
            candidate_id
            for candidate_id in (
                self.selected_candidate_id,
                self.raw_score_candidate_id,
            )
            if candidate_id is not None
        }
        expected_rejected = qualification_ids - non_rejected
        if set(rejected_ids) != expected_rejected:
            raise ValueError(
                "rejected candidates must cover every qualification that was "
                "neither selected nor qualified for raw scores"
            )
        _finish(self, "modern_matcher_selection_decision_v1")

    @classmethod
    def create(cls, **claims: Any) -> "ModernMatcherSelectionDecision":
        return _with_fingerprint(cls, "modern_matcher_selection_decision_v1", claims)


@dataclass(frozen=True, slots=True)
class Stage8AFinalization:
    schema_version: str
    kind: str
    outcome: Stage8AOutcome
    registry_fingerprint: str
    registry_content_hash: str
    qualification_fingerprints: Mapping[str, str]
    qualification_content_hashes: Mapping[str, str]
    selection_decision_fingerprint: str
    selection_decision_content_hash: str
    readme_content_hash: str
    selection_policy_fingerprint: str
    required_local_artifact_fingerprints: Mapping[str, str]
    forbidden_inputs_read: bool
    prior_stages_unchanged: bool
    verifier_source_commit: str
    verifier_source_tree_clean: bool
    created_utc: str
    fingerprint: str

    def __post_init__(self) -> None:
        if str(self.schema_version) != STAGE8A_SCHEMA_VERSION:
            raise ValueError("unsupported Stage 8A finalization schema version")
        if self.kind != "stage_8a_finalization":
            raise ValueError("kind must be 'stage_8a_finalization'")
        object.__setattr__(self, "outcome", _enum(self.outcome, Stage8AOutcome, "outcome"))
        for name in ("registry_fingerprint", "registry_content_hash", "selection_decision_fingerprint", "selection_decision_content_hash", "readme_content_hash", "selection_policy_fingerprint"):
            object.__setattr__(self, name, _require_sha256(getattr(self, name), name))
        for name in ("qualification_fingerprints", "qualification_content_hashes", "required_local_artifact_fingerprints"):
            values = {str(key): _require_sha256(value, f"{name}[{key}]") for key, value in dict(getattr(self, name)).items()}
            for key in values:
                validate_id(key)
            object.__setattr__(self, name, MappingProxyType(values))
        if set(self.qualification_fingerprints) != set(self.qualification_content_hashes):
            raise ValueError("finalization must bind the same qualification reports by identity and exact bytes")
        if self.forbidden_inputs_read is not False:
            raise ValueError("Stage 8A finalization requires that no forbidden input was read")
        if self.prior_stages_unchanged is not True:
            raise ValueError("Stage 8A may not alter stages 1 through 7D")
        verifier_commit = _require_commit(
            self.verifier_source_commit, "verifier_source_commit"
        )
        if verifier_commit is None:
            raise ValueError("verifier_source_commit is required")
        object.__setattr__(self, "verifier_source_commit", verifier_commit)
        if self.verifier_source_tree_clean is not True:
            raise ValueError("Stage 8A finalization requires a clean verifier source tree")
        object.__setattr__(self, "created_utc", _require_text(self.created_utc, "created_utc"))
        _finish(self, "stage_8a_finalization_v1")

    @classmethod
    def create(cls, **claims: Any) -> "Stage8AFinalization":
        return _with_fingerprint(cls, "stage_8a_finalization_v1", claims)
