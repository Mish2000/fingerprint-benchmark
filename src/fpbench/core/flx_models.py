"""Immutable, content-addressed vocabulary for Stage 8B.

Stage 8B turns one public artifact into a local inference route and asks
whether that route could be executed by the general engine without changing
it.  These records describe the route: what was pinned, what was installed,
what the transform does, what a representation is, how a raw score is formed
and serialized, and what a probe actually observed.

Like Stage 8A's vocabulary this module is stdlib-only.  It is imported by the
evidence store, by the qualification layer and by tests that have no ML
runtime, so nothing here may import torch, and nothing here holds pixels,
embeddings or scores.

Fingerprinting is shared with Stage 8A rather than reimplemented: a second
hash function over the same kind of claim is a second thing to keep correct.
Wall-clock fields are excluded from semantic identity by that shared helper,
which is why every timestamp here reuses one of the five names it already
knows.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from fpbench.core.identifiers import validate_id
from fpbench.core.modern_matcher_models import (
    document_content_hash,
    semantic_fingerprint,
)
from fpbench.core.serialization import require_exact_int

__all__ = [
    "STAGE8B_SCHEMA_VERSION",
    "FlxGate",
    "FlxGateState",
    "FlxOutcome",
    "FlxRuntimePolicy",
    "FlxArtifactBinding",
    "FlxDependencyPin",
    "FlxRuntimeManifest",
    "FlxPreprocessingStep",
    "FlxPreprocessingProfile",
    "FlxRepresentationBranchSpec",
    "FlxRepresentationProfile",
    "FlxScoreSerializationProfile",
    "FlxScoreProfile",
    "FlxAdapterProfile",
    "FlxSelfIndependenceReport",
    "FlxDeterminismReport",
    "FlxOfflineReport",
    "FlxOperationalReport",
    "FlxRuntimeProbe",
    "FlxGateResult",
    "FlxQualificationReport",
    "Stage8BFinalization",
    "REQUIRED_PREPROCESSING_STEPS",
    "document_content_hash",
    "semantic_fingerprint",
]

STAGE8B_SCHEMA_VERSION = "1"
_HEX = frozenset("0123456789abcdef")
_FACTORY_FINGERPRINTING: ContextVar[bool] = ContextVar(
    "stage8b_factory_fingerprinting", default=False
)


class FlxOutcome(str, Enum):
    """The five ways Stage 8B can end.  Only the first opens Stage 8C."""

    RAW_SCORE_EXECUTION_READY = "FLX_RAW_SCORE_EXECUTION_READY"
    RUNTIME_BLOCKED = "FLX_RUNTIME_BLOCKED"
    ARTIFACT_MISMATCH = "FLX_ARTIFACT_MISMATCH"
    CONTRACT_FAILED = "FLX_CONTRACT_FAILED"
    OPERATIONALLY_INFEASIBLE = "FLX_OPERATIONALLY_INFEASIBLE"


class FlxGate(str, Enum):
    ARTIFACT_IDENTITY = "artifact_identity_verified"
    RUNTIME_IDENTITY = "runtime_identity_verified"
    CHECKPOINT_LOADED = "checkpoint_loaded"
    MODEL_VARIANT = "model_variant_verified"
    STRICT_KEY_VALIDATION = "strict_key_validation"
    PREPROCESSING_CONTRACT = "preprocessing_contract"
    REPRESENTATION_CONTRACT = "representation_contract"
    SCORE_CONTRACT = "score_contract"
    SELF_INDEPENDENCE = "self_independence"
    DETERMINISM = "determinism"
    RESTART = "restart"
    OFFLINE_ISOLATION = "offline_isolation"
    OPERATIONAL = "operational"
    ARCHITECTURE_FIT = "architecture_fit"
    LICENSE_STATUS = "license_status"


class FlxGateState(str, Enum):
    """An unrun gate is never reported as an observed failure (Stage 8A's rule)."""

    PASSED = "passed"
    FAILED = "failed"
    NOT_EXECUTED = "not_executed"
    NOT_APPLICABLE = "not_applicable"


# --------------------------------------------------------------- validation


def _require_text(value: Any, name: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{name} must be non-empty text")
    return text


def _optional_text(value: Any, name: str) -> str | None:
    return None if value is None else _require_text(value, name)


def _require_sha256(value: Any, name: str) -> str:
    text = str(value).strip().lower()
    if len(text) != 64 or not set(text) <= _HEX:
        raise ValueError(f"{name} must be a 64-character lowercase SHA-256")
    return text


def _optional_sha256(value: Any, name: str) -> str | None:
    return None if value is None else _require_sha256(value, name)


def _require_commit(value: Any, name: str) -> str:
    text = str(value).strip().lower()
    if len(text) != 40 or not set(text) <= _HEX:
        raise ValueError(f"{name} must be a full 40-character commit SHA")
    return text


def _require_bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{name} must be a boolean")
    return value


def _optional_bool(value: Any, name: str) -> bool | None:
    return None if value is None else _require_bool(value, name)


def _enum(value: Any, enum_type: type[Enum], name: str) -> Any:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be one of {[item.value for item in enum_type]}") from exc


def _text_tuple(values: Sequence[Any], name: str, *, unique: bool = True) -> tuple[str, ...]:
    items = tuple(_require_text(value, name) for value in values)
    if unique and len(set(items)) != len(items):
        raise ValueError(f"{name} must not repeat a value")
    return items


def _int_tuple(values: Sequence[Any], name: str) -> tuple[int, ...]:
    shape = tuple(require_exact_int(value, name) for value in values)
    if not shape or any(value <= 0 for value in shape):
        raise ValueError(f"{name} must be positive dimensions")
    return shape


def _decimal_text(value: Any, name: str, *, non_negative: bool = False) -> str:
    text = _require_text(value, name)
    try:
        parsed = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"{name} must be an exact decimal string") from exc
    if not parsed.is_finite():
        raise ValueError(f"{name} must be finite")
    if non_negative and parsed < 0:
        raise ValueError(f"{name} must not be negative")
    return text


def _freeze(value: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("expected a mapping")
    frozen: dict[str, Any] = {}
    for key, item in value.items():
        frozen[_require_text(key, "mapping key")] = item
    return MappingProxyType(dict(sorted(frozen.items())))


def _finish(model: Any, schema: str) -> None:
    if _FACTORY_FINGERPRINTING.get():
        object.__setattr__(model, "fingerprint", semantic_fingerprint(schema, model))
        return
    fingerprint = _require_sha256(model.fingerprint, "fingerprint")
    object.__setattr__(model, "fingerprint", fingerprint)
    if fingerprint != semantic_fingerprint(schema, model):
        raise ValueError(f"fingerprint does not cover the {schema} claims")


def _with_fingerprint(cls: type[Any], schema: str, claims: Mapping[str, Any]) -> Any:
    token = _FACTORY_FINGERPRINTING.set(True)
    try:
        return cls(**dict(claims), fingerprint="0" * 64)
    finally:
        _FACTORY_FINGERPRINTING.reset(token)


def _check_version(value: Any, what: str) -> None:
    if str(value) != STAGE8B_SCHEMA_VERSION:
        raise ValueError(f"unsupported {what} schema version")


# ------------------------------------------------------------------- policy


@dataclass(frozen=True, slots=True)
class FlxRuntimePolicy:
    """Operational limits, frozen before a single measurement is taken.

    The three projection limits are inherited from Stage 8A's selection policy
    by fingerprint rather than restated, so the two documents cannot drift into
    different budgets for the same run (spec section 19).
    """

    schema_version: str
    policy_id: str
    inherits_selection_policy_fingerprint: str
    max_projected_12000_extractions_seconds: str
    max_projected_6000_comparisons_seconds: str
    max_peak_ram_bytes: int
    max_artifact_disk_bytes: int
    max_worker_startup_seconds: str
    max_model_load_seconds: str
    preprocess_deadline_seconds: str
    extract_deadline_seconds: str
    compare_deadline_seconds: str
    numeric_tolerance: str
    fingerprint: str

    def __post_init__(self) -> None:
        _check_version(self.schema_version, "flx runtime policy")
        validate_id(self.policy_id)
        object.__setattr__(
            self,
            "inherits_selection_policy_fingerprint",
            _require_sha256(
                self.inherits_selection_policy_fingerprint,
                "inherits_selection_policy_fingerprint",
            ),
        )
        for name in (
            "max_projected_12000_extractions_seconds",
            "max_projected_6000_comparisons_seconds",
            "max_worker_startup_seconds",
            "max_model_load_seconds",
            "preprocess_deadline_seconds",
            "extract_deadline_seconds",
            "compare_deadline_seconds",
            "numeric_tolerance",
        ):
            object.__setattr__(
                self, name, _decimal_text(getattr(self, name), name, non_negative=True)
            )
        for name in ("max_peak_ram_bytes", "max_artifact_disk_bytes"):
            value = require_exact_int(getattr(self, name), name)
            if value <= 0:
                raise ValueError(f"{name} must be positive")
            object.__setattr__(self, name, value)
        _finish(self, "flx_runtime_policy_v1")

    @classmethod
    def create(cls, **claims: Any) -> "FlxRuntimePolicy":
        return _with_fingerprint(cls, "flx_runtime_policy_v1", claims)


# ---------------------------------------------------------------- artifacts


@dataclass(frozen=True, slots=True)
class FlxArtifactBinding:
    """What was on disk, rehashed, at the moment the runtime was loaded.

    ``licence`` fields travel with the binding on purpose.  Executing the
    checkpoint locally is something the project owner instructed; it is not a
    licence conclusion, and nothing here is allowed to imply one.
    """

    schema_version: str
    binding_id: str
    algorithm_id: str
    source_commit: str
    source_archive_sha256: str
    source_tree_verified_files: int
    checkpoint_filename: str
    checkpoint_sha256: str
    checkpoint_size_bytes: int
    checkpoint_variant: str
    implementation_origin: str
    upstream_study: str
    upstream_relationship: str
    stage8a_manifest_fingerprint: str
    weights_license_status: str
    redistribution_allowed: str
    publication_permission: str
    checkpoint_committed_to_git: bool
    downloaded_during_inference: bool
    inspected_utc: str
    fingerprint: str

    def __post_init__(self) -> None:
        _check_version(self.schema_version, "flx artifact binding")
        validate_id(self.binding_id)
        validate_id(self.algorithm_id)
        object.__setattr__(self, "source_commit", _require_commit(self.source_commit, "source_commit"))
        for name in ("source_archive_sha256", "checkpoint_sha256", "stage8a_manifest_fingerprint"):
            object.__setattr__(self, name, _require_sha256(getattr(self, name), name))
        for name in (
            "checkpoint_filename",
            "checkpoint_variant",
            "implementation_origin",
            "upstream_study",
            "upstream_relationship",
            "weights_license_status",
            "redistribution_allowed",
            "publication_permission",
            "inspected_utc",
        ):
            object.__setattr__(self, name, _require_text(getattr(self, name), name))
        for name in ("checkpoint_size_bytes", "source_tree_verified_files"):
            value = require_exact_int(getattr(self, name), name)
            if value <= 0:
                raise ValueError(f"{name} must be positive")
            object.__setattr__(self, name, value)
        object.__setattr__(
            self,
            "checkpoint_committed_to_git",
            _require_bool(self.checkpoint_committed_to_git, "checkpoint_committed_to_git"),
        )
        object.__setattr__(
            self,
            "downloaded_during_inference",
            _require_bool(self.downloaded_during_inference, "downloaded_during_inference"),
        )
        if self.checkpoint_committed_to_git:
            raise ValueError("the checkpoint may never be committed to this repository")
        if self.downloaded_during_inference:
            raise ValueError("no artifact may be downloaded during inference")
        if self.weights_license_status != "unresolved":
            raise ValueError(
                "Stage 8B may not record the weights licence as resolved; local "
                "execution permission is not a licence finding"
            )
        _finish(self, "flx_artifact_binding_v1")

    @classmethod
    def create(cls, **claims: Any) -> "FlxArtifactBinding":
        return _with_fingerprint(cls, "flx_artifact_binding_v1", claims)


# ------------------------------------------------------------------ runtime


@dataclass(frozen=True, slots=True)
class FlxDependencyPin:
    """One installed distribution, pinned by version and by the bytes installed."""

    schema_version: str
    name: str
    version: str
    artifact_filename: str
    artifact_sha256: str
    source_index: str
    fingerprint: str

    def __post_init__(self) -> None:
        _check_version(self.schema_version, "flx dependency pin")
        for name in ("name", "version", "artifact_filename", "source_index"):
            object.__setattr__(self, name, _require_text(getattr(self, name), name))
        object.__setattr__(
            self, "artifact_sha256", _require_sha256(self.artifact_sha256, "artifact_sha256")
        )
        if not self.artifact_filename.endswith(".whl"):
            raise ValueError("a pinned dependency must name the exact wheel that was installed")
        _finish(self, "flx_dependency_pin_v1")

    @classmethod
    def create(cls, **claims: Any) -> "FlxDependencyPin":
        return _with_fingerprint(cls, "flx_dependency_pin_v1", claims)


@dataclass(frozen=True, slots=True)
class FlxRuntimeManifest:
    """The environment that produced a representation, described exactly."""

    schema_version: str
    runtime_profile_id: str
    os_name: str
    os_version: str
    kernel_release: str
    cpu_architecture: str
    cpu_model: str
    python_version: str
    python_implementation: str
    torch_version: str
    torchvision_version: str
    numpy_version: str
    blas_implementation: str
    mkldnn_version: str
    parallel_backend: str
    torch_num_threads: int
    torch_num_interop_threads: int
    device: str
    cuda_available: bool
    dependency_lock_sha256: str
    dependencies: tuple[FlxDependencyPin, ...]
    deterministic_environment: Mapping[str, Any]
    created_utc: str
    fingerprint: str

    def __post_init__(self) -> None:
        _check_version(self.schema_version, "flx runtime manifest")
        validate_id(self.runtime_profile_id)
        for name in (
            "os_name",
            "os_version",
            "kernel_release",
            "cpu_architecture",
            "cpu_model",
            "python_version",
            "python_implementation",
            "torch_version",
            "torchvision_version",
            "numpy_version",
            "blas_implementation",
            "mkldnn_version",
            "parallel_backend",
            "device",
            "created_utc",
        ):
            object.__setattr__(self, name, _require_text(getattr(self, name), name))
        object.__setattr__(
            self,
            "dependency_lock_sha256",
            _require_sha256(self.dependency_lock_sha256, "dependency_lock_sha256"),
        )
        for name in ("torch_num_threads", "torch_num_interop_threads"):
            value = require_exact_int(getattr(self, name), name)
            if value <= 0:
                raise ValueError(f"{name} must be positive")
            object.__setattr__(self, name, value)
        object.__setattr__(self, "cuda_available", _require_bool(self.cuda_available, "cuda_available"))
        object.__setattr__(self, "dependencies", tuple(self.dependencies))
        names = [pin.name.lower() for pin in self.dependencies]
        if len(set(names)) != len(names):
            raise ValueError("a distribution may be pinned only once")
        if not self.dependencies:
            raise ValueError("a runtime manifest without dependency pins is not a lock")
        object.__setattr__(self, "deterministic_environment", _freeze(self.deterministic_environment))
        if self.cuda_available or self.device != "cpu":
            raise ValueError(
                f"{self.runtime_profile_id} is a CPU profile; a GPU is a different "
                "runtime profile and a different identity"
            )
        _finish(self, "flx_runtime_manifest_v1")

    @classmethod
    def create(cls, **claims: Any) -> "FlxRuntimeManifest":
        return _with_fingerprint(cls, "flx_runtime_manifest_v1", claims)


# ------------------------------------------------------------ preprocessing


#: Every question the transform must answer out loud.  A profile that omits one
#: is not "using the default"; it is undocumented, and it is refused.
REQUIRED_PREPROCESSING_STEPS = (
    "decode",
    "channel_count",
    "bit_depth",
    "polarity",
    "crop",
    "localization",
    "alignment",
    "padding",
    "padding_fill",
    "padding_parity",
    "resize",
    "interpolation",
    "antialias",
    "tensor_shape",
    "numeric_dtype",
    "value_range",
    "normalization",
    "channel_replication",
    "re_encoding",
)


@dataclass(frozen=True, slots=True)
class FlxPreprocessingStep:
    schema_version: str
    step_id: str
    action: str
    rationale: str
    fingerprint: str

    def __post_init__(self) -> None:
        _check_version(self.schema_version, "flx preprocessing step")
        validate_id(self.step_id)
        for name in ("action", "rationale"):
            object.__setattr__(self, name, _require_text(getattr(self, name), name))
        _finish(self, "flx_preprocessing_step_v1")

    @classmethod
    def create(cls, **claims: Any) -> "FlxPreprocessingStep":
        return _with_fingerprint(cls, "flx_preprocessing_step_v1", claims)


@dataclass(frozen=True, slots=True)
class FlxPreprocessingProfile:
    schema_version: str
    profile_id: str
    input_contract: str
    output_shape: tuple[int, ...]
    output_dtype: str
    value_minimum: str
    value_maximum: str
    padding_fill_value: int
    padding_parity_rule: str
    resize_side: int
    interpolation: str
    antialias: bool
    dataset_independent: bool
    subject_independent: bool
    steps: tuple[FlxPreprocessingStep, ...]
    fingerprint: str

    def __post_init__(self) -> None:
        _check_version(self.schema_version, "flx preprocessing profile")
        validate_id(self.profile_id)
        for name in ("input_contract", "output_dtype", "padding_parity_rule", "interpolation"):
            object.__setattr__(self, name, _require_text(getattr(self, name), name))
        object.__setattr__(self, "output_shape", _int_tuple(self.output_shape, "output_shape"))
        for name in ("value_minimum", "value_maximum"):
            object.__setattr__(self, name, _decimal_text(getattr(self, name), name))
        if Decimal(self.value_minimum) >= Decimal(self.value_maximum):
            raise ValueError("value_minimum must be lower than value_maximum")
        fill = require_exact_int(self.padding_fill_value, "padding_fill_value")
        if not 0 <= fill <= 255:
            raise ValueError("padding_fill_value must be an 8-bit sample")
        object.__setattr__(self, "padding_fill_value", fill)
        side = require_exact_int(self.resize_side, "resize_side")
        if side <= 0:
            raise ValueError("resize_side must be positive")
        object.__setattr__(self, "resize_side", side)
        for name in ("antialias", "dataset_independent", "subject_independent"):
            object.__setattr__(self, name, _require_bool(getattr(self, name), name))
        object.__setattr__(self, "steps", tuple(self.steps))
        step_ids = tuple(step.step_id for step in self.steps)
        if step_ids != REQUIRED_PREPROCESSING_STEPS:
            raise ValueError(
                "a preprocessing profile must document every required step exactly "
                f"once and in order: {REQUIRED_PREPROCESSING_STEPS}"
            )
        if not self.dataset_independent or not self.subject_independent:
            raise ValueError(
                "Stage 8B preprocessing may not branch on dataset or subject"
            )
        if self.output_shape != (1, side, side):
            raise ValueError("output_shape must be one channel at the declared resize side")
        _finish(self, "flx_preprocessing_profile_v1")

    @classmethod
    def create(cls, **claims: Any) -> "FlxPreprocessingProfile":
        return _with_fingerprint(cls, "flx_preprocessing_profile_v1", claims)


# ----------------------------------------------------------- representation


@dataclass(frozen=True, slots=True)
class FlxRepresentationBranchSpec:
    schema_version: str
    branch_id: str
    position: int
    dimensions: int
    dtype: str
    normalization: str
    upstream_module: str
    fingerprint: str

    def __post_init__(self) -> None:
        _check_version(self.schema_version, "flx representation branch")
        validate_id(self.branch_id)
        position = require_exact_int(self.position, "position")
        if position < 0:
            raise ValueError("position must not be negative")
        object.__setattr__(self, "position", position)
        dimensions = require_exact_int(self.dimensions, "dimensions")
        if dimensions <= 0:
            raise ValueError("dimensions must be positive")
        object.__setattr__(self, "dimensions", dimensions)
        for name in ("dtype", "normalization", "upstream_module"):
            object.__setattr__(self, name, _require_text(getattr(self, name), name))
        _finish(self, "flx_representation_branch_v1")

    @classmethod
    def create(cls, **claims: Any) -> "FlxRepresentationBranchSpec":
        return _with_fingerprint(cls, "flx_representation_branch_v1", claims)


@dataclass(frozen=True, slots=True)
class FlxRepresentationProfile:
    """Two branches, each normalized on its own, concatenated in a fixed order.

    ``inference_batch_rows`` is part of the identity because the pinned texture
    branch has no batch-of-one path: it squeezes the batch dimension away and
    then normalizes along ``dim=1``.  What "one extraction" means is therefore
    a property of this profile, not an implementation detail (docs/adr/0070).
    """

    schema_version: str
    profile_id: str
    branches: tuple[FlxRepresentationBranchSpec, ...]
    concatenated_dimensions: int
    concatenation_order: tuple[str, ...]
    inference_batch_rows: int
    inference_batch_rule: str
    represented_row: int
    duplicate_rows_must_be_bitwise_equal: bool
    localization_used: bool
    pose_input_required: bool
    reweighting_applied: bool
    persisted: bool
    fingerprint: str

    def __post_init__(self) -> None:
        _check_version(self.schema_version, "flx representation profile")
        validate_id(self.profile_id)
        object.__setattr__(self, "branches", tuple(self.branches))
        if len(self.branches) != 2:
            raise ValueError("this variant has exactly two branches")
        positions = tuple(branch.position for branch in self.branches)
        if positions != tuple(range(len(self.branches))):
            raise ValueError("branch positions must be 0..n-1 in stored order")
        object.__setattr__(
            self, "concatenation_order", _text_tuple(self.concatenation_order, "concatenation_order")
        )
        if self.concatenation_order != tuple(branch.branch_id for branch in self.branches):
            raise ValueError("concatenation order must match the stored branch order")
        total = require_exact_int(self.concatenated_dimensions, "concatenated_dimensions")
        if total != sum(branch.dimensions for branch in self.branches):
            raise ValueError("concatenated_dimensions must be the sum of the branch dimensions")
        object.__setattr__(self, "concatenated_dimensions", total)
        rows = require_exact_int(self.inference_batch_rows, "inference_batch_rows")
        if rows < 1:
            raise ValueError("inference_batch_rows must be at least one")
        object.__setattr__(self, "inference_batch_rows", rows)
        represented = require_exact_int(self.represented_row, "represented_row")
        if not 0 <= represented < rows:
            raise ValueError("represented_row must index the inference batch")
        object.__setattr__(self, "represented_row", represented)
        object.__setattr__(
            self, "inference_batch_rule", _require_text(self.inference_batch_rule, "inference_batch_rule")
        )
        for name in (
            "duplicate_rows_must_be_bitwise_equal",
            "localization_used",
            "pose_input_required",
            "reweighting_applied",
            "persisted",
        ):
            object.__setattr__(self, name, _require_bool(getattr(self, name), name))
        if rows > 1 and not self.duplicate_rows_must_be_bitwise_equal:
            raise ValueError(
                "a duplicated inference batch must assert its rows are bitwise equal"
            )
        if self.localization_used or self.pose_input_required:
            raise ValueError(
                "the without_localization variant has no localization branch and no pose input"
            )
        if self.reweighting_applied:
            raise ValueError("Stage 8B applies no branch reweighting")
        if self.persisted:
            raise ValueError("representations are never written to disk in Stage 8B")
        _finish(self, "flx_representation_profile_v1")

    @classmethod
    def create(cls, **claims: Any) -> "FlxRepresentationProfile":
        return _with_fingerprint(cls, "flx_representation_profile_v1", claims)


# -------------------------------------------------------------------- score


@dataclass(frozen=True, slots=True)
class FlxScoreSerializationProfile:
    """How an IEEE scalar becomes a Decimal, decided before any score existed."""

    schema_version: str
    profile_id: str
    significant_digits: int
    intermediate_form: str
    constructed_from: str
    rounding_before_storage: bool
    fingerprint: str

    def __post_init__(self) -> None:
        _check_version(self.schema_version, "flx score serialization profile")
        validate_id(self.profile_id)
        digits = require_exact_int(self.significant_digits, "significant_digits")
        if digits <= 0:
            raise ValueError("significant_digits must be positive")
        object.__setattr__(self, "significant_digits", digits)
        for name in ("intermediate_form", "constructed_from"):
            object.__setattr__(self, name, _require_text(getattr(self, name), name))
        object.__setattr__(
            self,
            "rounding_before_storage",
            _require_bool(self.rounding_before_storage, "rounding_before_storage"),
        )
        if self.rounding_before_storage:
            raise ValueError("a raw score is never rounded for decisions or display")
        _finish(self, "flx_score_serialization_profile_v1")

    @classmethod
    def create(cls, **claims: Any) -> "FlxScoreSerializationProfile":
        return _with_fingerprint(cls, "flx_score_serialization_profile_v1", claims)


@dataclass(frozen=True, slots=True)
class FlxScoreProfile:
    schema_version: str
    profile_id: str
    formula: str
    score_direction: str
    nominal_minimum: str
    nominal_maximum: str
    branch_weights: tuple[str, ...]
    serialization: FlxScoreSerializationProfile
    returns_decimal: bool
    symmetric: bool
    calibration: str
    normalization: str
    threshold: str
    fallback_matcher: str
    quality_adjustment: str
    realignment: str
    fingerprint: str

    def __post_init__(self) -> None:
        _check_version(self.schema_version, "flx score profile")
        validate_id(self.profile_id)
        for name in (
            "formula",
            "score_direction",
            "calibration",
            "normalization",
            "threshold",
            "fallback_matcher",
            "quality_adjustment",
            "realignment",
        ):
            object.__setattr__(self, name, _require_text(getattr(self, name), name))
        for name in ("nominal_minimum", "nominal_maximum"):
            object.__setattr__(self, name, _decimal_text(getattr(self, name), name))
        if Decimal(self.nominal_minimum) >= Decimal(self.nominal_maximum):
            raise ValueError("nominal_minimum must be lower than nominal_maximum")
        weights = tuple(_decimal_text(value, "branch_weights") for value in self.branch_weights)
        if len(weights) != 2 or any(Decimal(weight) != Decimal("1") for weight in weights):
            raise ValueError("both branches carry weight exactly one; this profile adds no weighting")
        object.__setattr__(self, "branch_weights", weights)
        for name in ("returns_decimal", "symmetric"):
            object.__setattr__(self, name, _require_bool(getattr(self, name), name))
        if not self.returns_decimal:
            raise ValueError("the public compare API returns Decimal, never a Python float")
        for name in ("calibration", "normalization", "threshold", "fallback_matcher",
                     "quality_adjustment", "realignment"):
            if getattr(self, name) != "none":
                raise ValueError(f"{name} must be 'none' in a Stage 8B raw-score profile")
        if self.score_direction != "higher_is_more_similar":
            raise ValueError("score_direction must be higher_is_more_similar")
        _finish(self, "flx_score_profile_v1")

    @classmethod
    def create(cls, **claims: Any) -> "FlxScoreProfile":
        return _with_fingerprint(cls, "flx_score_profile_v1", claims)


# ------------------------------------------------------------------ adapter


@dataclass(frozen=True, slots=True)
class FlxAdapterProfile:
    """What the adapter is, and what it is structurally unable to see."""

    schema_version: str
    adapter_id: str
    adapter_version: int
    algorithm_id: str
    process_model: str
    protocol: str
    operations: tuple[str, ...]
    forbidden_inputs: tuple[str, ...]
    caches_representations: bool
    persists_representations: bool
    retries_failed_operations: bool
    loads_torch_in_parent: bool
    training_only_checkpoint_keys: tuple[str, ...]
    runtime_profile_id: str
    preprocessing_profile_id: str
    representation_profile_id: str
    score_profile_id: str
    score_serialization_profile_id: str
    fingerprint: str

    def __post_init__(self) -> None:
        _check_version(self.schema_version, "flx adapter profile")
        for name in (
            "adapter_id",
            "algorithm_id",
            "runtime_profile_id",
            "preprocessing_profile_id",
            "representation_profile_id",
            "score_profile_id",
            "score_serialization_profile_id",
        ):
            validate_id(getattr(self, name))
        version = require_exact_int(self.adapter_version, "adapter_version")
        if version <= 0:
            raise ValueError("adapter_version must be positive")
        object.__setattr__(self, "adapter_version", version)
        for name in ("process_model", "protocol"):
            object.__setattr__(self, name, _require_text(getattr(self, name), name))
        object.__setattr__(self, "operations", _text_tuple(self.operations, "operations"))
        object.__setattr__(
            self, "forbidden_inputs", _text_tuple(self.forbidden_inputs, "forbidden_inputs")
        )
        object.__setattr__(
            self,
            "training_only_checkpoint_keys",
            _text_tuple(self.training_only_checkpoint_keys, "training_only_checkpoint_keys"),
        )
        for name in (
            "caches_representations",
            "persists_representations",
            "retries_failed_operations",
            "loads_torch_in_parent",
        ):
            object.__setattr__(self, name, _require_bool(getattr(self, name), name))
            if getattr(self, name):
                raise ValueError(f"{name} must be false in Stage 8B")
        if self.operations != (
            "load_runtime",
            "preprocess",
            "extract",
            "compare",
            "validate_runtime",
            "describe_operation",
        ):
            raise ValueError("the adapter exposes exactly the six contracted operations, in order")
        _finish(self, "flx_adapter_profile_v1")

    @classmethod
    def create(cls, **claims: Any) -> "FlxAdapterProfile":
        return _with_fingerprint(cls, "flx_adapter_profile_v1", claims)


# -------------------------------------------------------------------- probe


@dataclass(frozen=True, slots=True)
class FlxSelfIndependenceReport:
    """Proof that SELF ran two extractions and did not reuse one.

    Equal representations are expected and fine.  Reusing the same extraction
    is what would make a SELF comparison meaningless, so the counters and the
    object identities are what is recorded, not the equality.
    """

    schema_version: str
    report_id: str
    tested: bool
    preprocess_call_count: int | None
    extract_call_count: int | None
    distinct_representation_objects: bool | None
    representations_equal: bool | None
    cache_lookups_observed: int | None
    fingerprint: str

    def __post_init__(self) -> None:
        _check_version(self.schema_version, "flx self independence report")
        validate_id(self.report_id)
        object.__setattr__(self, "tested", _require_bool(self.tested, "tested"))
        for name in ("preprocess_call_count", "extract_call_count", "cache_lookups_observed"):
            value = getattr(self, name)
            if value is not None:
                value = require_exact_int(value, name)
                if value < 0:
                    raise ValueError(f"{name} must not be negative")
            object.__setattr__(self, name, value)
        for name in ("distinct_representation_objects", "representations_equal"):
            object.__setattr__(self, name, _optional_bool(getattr(self, name), name))
        observed = (
            self.preprocess_call_count,
            self.extract_call_count,
            self.distinct_representation_objects,
            self.cache_lookups_observed,
        )
        if self.tested and any(value is None for value in observed):
            raise ValueError("a tested SELF report must carry every observation")
        if not self.tested and any(value is not None for value in observed):
            raise ValueError("an untested SELF contract reports nothing, not a failure")
        _finish(self, "flx_self_independence_report_v1")

    @classmethod
    def create(cls, **claims: Any) -> "FlxSelfIndependenceReport":
        return _with_fingerprint(cls, "flx_self_independence_report_v1", claims)


@dataclass(frozen=True, slots=True)
class FlxDeterminismReport:
    schema_version: str
    report_id: str
    tested: bool
    numeric_tolerance: str
    repeated_extraction_bitwise_equal: bool | None
    repeated_comparison_bitwise_equal: bool | None
    single_vs_batch_state: str
    single_vs_batch_bitwise_equal: bool | None
    process_restart_representation_equal: bool | None
    process_restart_score_equal: bool | None
    process_restart_runtime_metadata_equal: bool | None
    input_order_symmetric: bool | None
    fingerprint: str

    def __post_init__(self) -> None:
        _check_version(self.schema_version, "flx determinism report")
        validate_id(self.report_id)
        object.__setattr__(self, "tested", _require_bool(self.tested, "tested"))
        object.__setattr__(
            self,
            "numeric_tolerance",
            _decimal_text(self.numeric_tolerance, "numeric_tolerance", non_negative=True),
        )
        object.__setattr__(
            self, "single_vs_batch_state", _enum(self.single_vs_batch_state, FlxGateState, "single_vs_batch_state")
        )
        for name in (
            "repeated_extraction_bitwise_equal",
            "repeated_comparison_bitwise_equal",
            "single_vs_batch_bitwise_equal",
            "process_restart_representation_equal",
            "process_restart_score_equal",
            "process_restart_runtime_metadata_equal",
            "input_order_symmetric",
        ):
            object.__setattr__(self, name, _optional_bool(getattr(self, name), name))
        required = (
            self.repeated_extraction_bitwise_equal,
            self.repeated_comparison_bitwise_equal,
            self.process_restart_representation_equal,
            self.process_restart_score_equal,
            self.process_restart_runtime_metadata_equal,
            self.input_order_symmetric,
        )
        if self.tested and any(value is None for value in required):
            raise ValueError("a tested determinism report must carry every observation")
        if not self.tested and any(value is not None for value in required):
            raise ValueError("an untested determinism probe reports nothing, not nondeterminism")
        if (
            self.single_vs_batch_state is FlxGateState.NOT_APPLICABLE
            and self.single_vs_batch_bitwise_equal is not None
        ):
            raise ValueError("a not-applicable batch comparison carries no observation")
        _finish(self, "flx_determinism_report_v1")

    @classmethod
    def create(cls, **claims: Any) -> "FlxDeterminismReport":
        return _with_fingerprint(cls, "flx_determinism_report_v1", claims)


@dataclass(frozen=True, slots=True)
class FlxOfflineReport:
    schema_version: str
    report_id: str
    tested: bool
    dns_blocked: bool | None
    socket_creation_blocked: bool | None
    proxy_variables_neutralized: tuple[str, ...]
    model_hub_variables_redirected: tuple[str, ...]
    network_attempts_observed: int | None
    fingerprint: str

    def __post_init__(self) -> None:
        _check_version(self.schema_version, "flx offline report")
        validate_id(self.report_id)
        object.__setattr__(self, "tested", _require_bool(self.tested, "tested"))
        for name in ("dns_blocked", "socket_creation_blocked"):
            object.__setattr__(self, name, _optional_bool(getattr(self, name), name))
        for name in ("proxy_variables_neutralized", "model_hub_variables_redirected"):
            object.__setattr__(self, name, _text_tuple(getattr(self, name), name))
        attempts = self.network_attempts_observed
        if attempts is not None:
            attempts = require_exact_int(attempts, "network_attempts_observed")
            if attempts < 0:
                raise ValueError("network_attempts_observed must not be negative")
        object.__setattr__(self, "network_attempts_observed", attempts)
        if self.tested and (
            self.dns_blocked is None
            or self.socket_creation_blocked is None
            or attempts is None
        ):
            raise ValueError("a tested offline report must carry every observation")
        if not self.tested and (
            self.dns_blocked is not None
            or self.socket_creation_blocked is not None
            or attempts is not None
        ):
            raise ValueError("an untested offline probe reports nothing, not a violation")
        _finish(self, "flx_offline_report_v1")

    @classmethod
    def create(cls, **claims: Any) -> "FlxOfflineReport":
        return _with_fingerprint(cls, "flx_offline_report_v1", claims)


@dataclass(frozen=True, slots=True)
class FlxOperationalReport:
    """Measurements, and the pre-frozen limits they are measured against.

    A projection is a gate, not a promise and not a quality claim: it says only
    that a full Stage 8C run would fit inside limits chosen before any timing
    was seen (spec section 19).
    """

    schema_version: str
    report_id: str
    measured: bool
    policy_fingerprint: str
    worker_startup_seconds: str | None
    model_load_seconds: str | None
    preprocess_seconds: str | None
    extract_seconds: str | None
    compare_seconds: str | None
    peak_ram_bytes: int | None
    artifact_disk_bytes: int | None
    projected_12000_extractions_seconds: str | None
    projected_6000_comparisons_seconds: str | None
    within_limits: bool | None
    fingerprint: str

    def __post_init__(self) -> None:
        _check_version(self.schema_version, "flx operational report")
        validate_id(self.report_id)
        object.__setattr__(self, "measured", _require_bool(self.measured, "measured"))
        object.__setattr__(
            self, "policy_fingerprint", _require_sha256(self.policy_fingerprint, "policy_fingerprint")
        )
        decimals = (
            "worker_startup_seconds",
            "model_load_seconds",
            "preprocess_seconds",
            "extract_seconds",
            "compare_seconds",
            "projected_12000_extractions_seconds",
            "projected_6000_comparisons_seconds",
        )
        for name in decimals:
            value = getattr(self, name)
            if value is not None:
                value = _decimal_text(value, name, non_negative=True)
            object.__setattr__(self, name, value)
        for name in ("peak_ram_bytes", "artifact_disk_bytes"):
            value = getattr(self, name)
            if value is not None:
                value = require_exact_int(value, name)
                if value <= 0:
                    raise ValueError(f"{name} must be positive")
            object.__setattr__(self, name, value)
        object.__setattr__(self, "within_limits", _optional_bool(self.within_limits, "within_limits"))
        observations = tuple(getattr(self, name) for name in decimals) + (
            self.peak_ram_bytes,
            self.artifact_disk_bytes,
            self.within_limits,
        )
        if self.measured and any(value is None for value in observations):
            raise ValueError("a measured operational report must carry every measurement")
        if not self.measured and any(value is not None for value in observations):
            raise ValueError("an unmeasured runtime is missing measurements, not infeasible")
        _finish(self, "flx_operational_report_v1")

    @classmethod
    def create(cls, **claims: Any) -> "FlxOperationalReport":
        return _with_fingerprint(cls, "flx_operational_report_v1", claims)


@dataclass(frozen=True, slots=True)
class FlxRuntimeProbe:
    """One dynamic qualification run over synthetic, non-biometric fixtures."""

    schema_version: str
    probe_id: str
    protocol_id: str
    artifact_binding_fingerprint: str
    runtime_manifest_fingerprint: str
    preprocessing_profile_fingerprint: str
    representation_profile_fingerprint: str
    score_profile_fingerprint: str
    adapter_profile_fingerprint: str
    fixture_ids: tuple[str, ...]
    fixture_content_hashes: Mapping[str, Any]
    representation_hashes: Mapping[str, Any]
    score_hashes: Mapping[str, Any]
    checkpoint_loaded: bool
    model_in_eval_mode: bool
    gradients_disabled: bool
    unexpected_state_dict_keys: tuple[str, ...]
    missing_state_dict_keys: tuple[str, ...]
    self_independence: FlxSelfIndependenceReport
    determinism: FlxDeterminismReport
    offline: FlxOfflineReport
    operational: FlxOperationalReport
    biometric_inputs_read: bool
    prior_results_read: bool
    created_utc: str
    fingerprint: str

    def __post_init__(self) -> None:
        _check_version(self.schema_version, "flx runtime probe")
        validate_id(self.probe_id)
        validate_id(self.protocol_id)
        for name in (
            "artifact_binding_fingerprint",
            "runtime_manifest_fingerprint",
            "preprocessing_profile_fingerprint",
            "representation_profile_fingerprint",
            "score_profile_fingerprint",
            "adapter_profile_fingerprint",
        ):
            object.__setattr__(self, name, _require_sha256(getattr(self, name), name))
        object.__setattr__(self, "fixture_ids", _text_tuple(self.fixture_ids, "fixture_ids"))
        if not self.fixture_ids:
            raise ValueError("a probe must name the fixtures it ran on")
        for name in ("fixture_content_hashes", "representation_hashes", "score_hashes"):
            object.__setattr__(self, name, _freeze(getattr(self, name)))
        if set(self.fixture_content_hashes) != set(self.fixture_ids):
            raise ValueError("every fixture must be content-addressed exactly once")
        for name in ("checkpoint_loaded", "model_in_eval_mode", "gradients_disabled",
                     "biometric_inputs_read", "prior_results_read"):
            object.__setattr__(self, name, _require_bool(getattr(self, name), name))
        for name in ("unexpected_state_dict_keys", "missing_state_dict_keys"):
            object.__setattr__(self, name, _text_tuple(getattr(self, name), name))
        object.__setattr__(self, "created_utc", _require_text(self.created_utc, "created_utc"))
        if self.biometric_inputs_read or self.prior_results_read:
            raise ValueError(
                "Stage 8B reads no SD300 image and no SourceAFIS or NBIS result"
            )
        if self.checkpoint_loaded and not (self.model_in_eval_mode and self.gradients_disabled):
            raise ValueError("a loaded model must be in eval mode with gradients disabled")
        _finish(self, "flx_runtime_probe_v1")

    @classmethod
    def create(cls, **claims: Any) -> "FlxRuntimeProbe":
        return _with_fingerprint(cls, "flx_runtime_probe_v1", claims)


# ------------------------------------------------------------ qualification


@dataclass(frozen=True, slots=True)
class FlxGateResult:
    schema_version: str
    gate: FlxGate
    state: FlxGateState
    detail: str
    failure_codes: tuple[str, ...]
    fingerprint: str

    def __post_init__(self) -> None:
        _check_version(self.schema_version, "flx gate result")
        object.__setattr__(self, "gate", _enum(self.gate, FlxGate, "gate"))
        object.__setattr__(self, "state", _enum(self.state, FlxGateState, "state"))
        object.__setattr__(self, "detail", _require_text(self.detail, "detail"))
        object.__setattr__(self, "failure_codes", _text_tuple(self.failure_codes, "failure_codes"))
        if self.state is FlxGateState.FAILED and not self.failure_codes:
            raise ValueError("a failed gate must name at least one failure code")
        if self.state is not FlxGateState.FAILED and self.failure_codes:
            raise ValueError("only a failed gate carries failure codes")
        _finish(self, "flx_gate_result_v1")

    @classmethod
    def create(cls, **claims: Any) -> "FlxGateResult":
        return _with_fingerprint(cls, "flx_gate_result_v1", claims)


@dataclass(frozen=True, slots=True)
class FlxQualificationReport:
    schema_version: str
    report_id: str
    protocol_id: str
    algorithm_id: str
    outcome: FlxOutcome
    gates: tuple[FlxGateResult, ...]
    probe_fingerprint: str
    weights_license_status: str
    redistribution_allowed: str
    publication_permission: str
    opens_stage_8c: bool
    permits_decisions: bool
    qualified_utc: str
    fingerprint: str

    def __post_init__(self) -> None:
        _check_version(self.schema_version, "flx qualification report")
        validate_id(self.report_id)
        validate_id(self.protocol_id)
        validate_id(self.algorithm_id)
        object.__setattr__(self, "outcome", _enum(self.outcome, FlxOutcome, "outcome"))
        object.__setattr__(self, "gates", tuple(self.gates))
        gate_names = tuple(result.gate for result in self.gates)
        if gate_names != tuple(FlxGate):
            raise ValueError("a qualification report states every gate exactly once, in order")
        object.__setattr__(self, "probe_fingerprint", _require_sha256(self.probe_fingerprint, "probe_fingerprint"))
        for name in (
            "weights_license_status",
            "redistribution_allowed",
            "publication_permission",
            "qualified_utc",
        ):
            object.__setattr__(self, name, _require_text(getattr(self, name), name))
        for name in ("opens_stage_8c", "permits_decisions"):
            object.__setattr__(self, name, _require_bool(getattr(self, name), name))
        ready = self.outcome is FlxOutcome.RAW_SCORE_EXECUTION_READY
        if ready != all(result.state is FlxGateState.PASSED for result in self.gates):
            raise ValueError(
                "the ready outcome holds exactly when every gate passed"
            )
        if self.opens_stage_8c is not ready:
            raise ValueError("only FLX_RAW_SCORE_EXECUTION_READY opens Stage 8C")
        if self.permits_decisions:
            raise ValueError(
                "raw-score readiness never permits MATCH or NON_MATCH decisions "
                "(docs/adr/0065)"
            )
        if self.weights_license_status != "unresolved":
            raise ValueError("Stage 8B does not resolve the weights licence")
        _finish(self, "flx_qualification_report_v1")

    @classmethod
    def create(cls, **claims: Any) -> "FlxQualificationReport":
        return _with_fingerprint(cls, "flx_qualification_report_v1", claims)


@dataclass(frozen=True, slots=True)
class Stage8BFinalization:
    """The last-written authority over the exact Stage 8B evidence bytes."""

    schema_version: str
    kind: str
    outcome: FlxOutcome
    stage8a_finalization_fingerprint: str
    source_archive_sha256: str
    checkpoint_sha256: str
    artifact_binding_fingerprint: str
    runtime_manifest_fingerprint: str
    preprocessing_profile_fingerprint: str
    representation_profile_fingerprint: str
    score_profile_fingerprint: str
    adapter_profile_fingerprint: str
    runtime_probe_fingerprint: str
    qualification_report_fingerprint: str
    runtime_policy_fingerprint: str
    evidence_content_hashes: Mapping[str, Any]
    verifier_source_commit: str
    verifier_source_tree_clean: bool
    biometric_inputs_read: bool
    prior_stages_unchanged: bool
    created_utc: str
    fingerprint: str

    def __post_init__(self) -> None:
        _check_version(self.schema_version, "stage 8B finalization")
        object.__setattr__(self, "kind", _require_text(self.kind, "kind"))
        if self.kind != "stage_8b_finalization":
            raise ValueError("kind must be stage_8b_finalization")
        object.__setattr__(self, "outcome", _enum(self.outcome, FlxOutcome, "outcome"))
        for name in (
            "stage8a_finalization_fingerprint",
            "source_archive_sha256",
            "checkpoint_sha256",
            "artifact_binding_fingerprint",
            "runtime_manifest_fingerprint",
            "preprocessing_profile_fingerprint",
            "representation_profile_fingerprint",
            "score_profile_fingerprint",
            "adapter_profile_fingerprint",
            "runtime_probe_fingerprint",
            "qualification_report_fingerprint",
            "runtime_policy_fingerprint",
        ):
            object.__setattr__(self, name, _require_sha256(getattr(self, name), name))
        object.__setattr__(
            self, "verifier_source_commit", _require_commit(self.verifier_source_commit, "verifier_source_commit")
        )
        object.__setattr__(self, "created_utc", _require_text(self.created_utc, "created_utc"))
        object.__setattr__(self, "evidence_content_hashes", _freeze(self.evidence_content_hashes))
        for filename, digest in self.evidence_content_hashes.items():
            _require_sha256(digest, f"evidence_content_hashes[{filename}]")
        for name in (
            "verifier_source_tree_clean",
            "biometric_inputs_read",
            "prior_stages_unchanged",
        ):
            object.__setattr__(self, name, _require_bool(getattr(self, name), name))
        if not self.verifier_source_tree_clean:
            raise ValueError("finalization requires a clean verifier source tree")
        if self.biometric_inputs_read:
            raise ValueError("Stage 8B read no biometric input")
        if not self.prior_stages_unchanged:
            raise ValueError("finalization requires prior stages to be unchanged")
        _finish(self, "stage_8b_finalization_v1")

    @classmethod
    def create(cls, **claims: Any) -> "Stage8BFinalization":
        return _with_fingerprint(cls, "stage_8b_finalization_v1", claims)
