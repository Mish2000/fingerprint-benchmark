"""Durable, evaluation-blind records for Stage 21B.

The raw score is stored as a binary64 number and beside its exact hexadecimal
representation.  The latter is not a transformed score: it is the lossless
serialization identity of the former, including ``-0.0``.
"""

from __future__ import annotations

import math
import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from fpbench.core.identifiers import validate_id
from fpbench.core.serialization import stable_hash
from fpbench.stage21b.constants import GROUND_TRUTH, STAGE

_HEX = frozenset("0123456789abcdef")


def _digest(value: object, name: str) -> str:
    text = str(value).strip().lower()
    if len(text) != 64 or not set(text) <= _HEX:
        raise ValueError(f"{name} must be a 64-character hexadecimal digest")
    return text


def _text(value: object, name: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{name} must not be empty")
    return text


def _exact_int(value: object, name: str, *, minimum: int = 0) -> int:
    if type(value) is not int:
        raise ValueError(f"{name} must be an exact integer")
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


def _float(value: object, name: str, *, non_negative: bool = False) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    if non_negative and number < 0:
        raise ValueError(f"{name} must not be negative")
    return number


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    return value


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(
        {str(k): _deep_freeze(v) for k, v in sorted(value.items())}
    )


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _deep_freeze(item) for key, item in sorted(value.items())}
        )
    if isinstance(value, (tuple, list)):
        return tuple(_deep_freeze(item) for item in value)
    if isinstance(value, Enum):
        return value.value
    return value


@dataclass(frozen=True, slots=True)
class PreparationReference:
    """The exact canonical500 entry used for one side of one pair."""

    preparation_set_id: str
    preparation_set_fingerprint: str
    preparation_profile_id: str
    preparation_profile_fingerprint: str
    preparation_entry_hash: str
    encoded_sha256: str
    pixel_sha256: str
    width: int
    height: int
    effective_ppi: int

    def __post_init__(self) -> None:
        validate_id(self.preparation_set_id)
        validate_id(self.preparation_profile_id)
        for name in (
            "preparation_set_fingerprint",
            "preparation_profile_fingerprint",
            "preparation_entry_hash",
            "encoded_sha256",
            "pixel_sha256",
        ):
            object.__setattr__(self, name, _digest(getattr(self, name), name))
        for name in ("width", "height", "effective_ppi"):
            object.__setattr__(
                self, name, _exact_int(getattr(self, name), name, minimum=1)
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "preparation_set_id": self.preparation_set_id,
            "preparation_set_fingerprint": self.preparation_set_fingerprint,
            "preparation_profile_id": self.preparation_profile_id,
            "preparation_profile_fingerprint": self.preparation_profile_fingerprint,
            "preparation_entry_hash": self.preparation_entry_hash,
            "encoded_sha256": self.encoded_sha256,
            "pixel_sha256": self.pixel_sha256,
            "width": self.width,
            "height": self.height,
            "effective_ppi": self.effective_ppi,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PreparationReference":
        return cls(**dict(value))


@dataclass(frozen=True, slots=True)
class PlannedPair:
    """One immutable manifest row plus both prepared-input bindings."""

    ordinal: int
    pair_id: str
    release: str
    left_image_id: str
    right_image_id: str
    ground_truth: str
    left_preparation: PreparationReference
    right_preparation: PreparationReference

    def __post_init__(self) -> None:
        object.__setattr__(self, "ordinal", _exact_int(self.ordinal, "ordinal"))
        validate_id(self.pair_id)
        validate_id(self.left_image_id)
        validate_id(self.right_image_id)
        object.__setattr__(self, "release", _text(self.release, "release"))
        truth = _text(self.ground_truth, "ground_truth").upper()
        if truth != GROUND_TRUTH:
            raise ValueError(
                f"Stage 21B ground truth must be {GROUND_TRUTH}, got {truth!r}"
            )
        object.__setattr__(self, "ground_truth", truth)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ordinal": self.ordinal,
            "pair_id": self.pair_id,
            "release": self.release,
            "left_image_id": self.left_image_id,
            "right_image_id": self.right_image_id,
            "ground_truth": self.ground_truth,
            "left_preparation": self.left_preparation.to_dict(),
            "right_preparation": self.right_preparation.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PlannedPair":
        data = dict(value)
        data["left_preparation"] = PreparationReference.from_dict(
            data["left_preparation"]
        )
        data["right_preparation"] = PreparationReference.from_dict(
            data["right_preparation"]
        )
        return cls(**data)


class Stage21BOutcomeStatus(str, Enum):
    SUCCESS = "SUCCESS"
    ALGORITHM_FAILURE = "ALGORITHM_FAILURE"


def ordered_pair_plan_fingerprint(pairs: Iterable[PlannedPair]) -> str:
    """Hash manifest order, image identities and both preparation references."""
    digest = hashlib.sha256()
    digest.update(b"stage21b_plan_v1\x00")
    for pair in pairs:
        digest.update(
            json.dumps(
                pair.to_dict(),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        )
        digest.update(b"\n")
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class FrozenRunSpec:
    """Everything that must agree before a run can start or resume."""

    schema_version: str
    stage: str
    run_id: str
    run_spec_fingerprint: str
    result_set_id: str

    stage21a_finalization_fingerprint: str
    stage21a_source_fingerprint: str
    high_resolution_reservation_fingerprint: str
    roster_id: str
    roster_fingerprint: str

    algorithm_id: str
    adapter_id: str
    integration_id: str | None
    implementation_version: str
    adapter_descriptor_fingerprint: str
    runtime_identity_fingerprint: str
    runtime_binding: Mapping[str, Any]
    predecessor_finalization_fingerprint: str
    score_direction: str

    protocol_id: str
    protocol_config_sha256: str
    pair_manifest_hash: str
    pair_ids_sha256: str
    planned_pair_input_fingerprint: str
    pair_count: int

    preparation_set_id: str
    preparation_set_fingerprint: str
    preparation_profile_id: str
    preparation_profile_fingerprint: str

    execution_source_fingerprint: str
    execution_source_revision: str
    algorithm_execution_config_sha256: str
    private_adapter_config_sha256: str
    expected_attempts: int
    timeout_seconds: float
    concurrency: int
    execution_strategy: str

    metrics_allowed: bool
    calibration_allowed: bool
    threshold_allowed: bool
    score_transform_allowed: bool
    orchestrator_algorithm_retries: int
    infrastructure_resume_allowed: bool
    created_utc: str

    def __post_init__(self) -> None:
        if self.schema_version != "1":
            raise ValueError("Stage 21B run-spec schema_version must be '1'")
        if self.stage != STAGE:
            raise ValueError(f"stage must be {STAGE}")
        for name in (
            "run_id",
            "result_set_id",
            "roster_id",
            "algorithm_id",
            "adapter_id",
            "protocol_id",
            "preparation_set_id",
            "preparation_profile_id",
            "execution_strategy",
        ):
            validate_id(getattr(self, name))
        if self.integration_id is not None:
            validate_id(self.integration_id)
        for name in (
            "run_spec_fingerprint",
            "stage21a_finalization_fingerprint",
            "stage21a_source_fingerprint",
            "high_resolution_reservation_fingerprint",
            "roster_fingerprint",
            "adapter_descriptor_fingerprint",
            "runtime_identity_fingerprint",
            "predecessor_finalization_fingerprint",
            "protocol_config_sha256",
            "pair_manifest_hash",
            "pair_ids_sha256",
            "planned_pair_input_fingerprint",
            "preparation_set_fingerprint",
            "preparation_profile_fingerprint",
            "execution_source_fingerprint",
            "algorithm_execution_config_sha256",
            "private_adapter_config_sha256",
        ):
            object.__setattr__(self, name, _digest(getattr(self, name), name))
        for name in ("pair_count", "expected_attempts"):
            object.__setattr__(
                self, name, _exact_int(getattr(self, name), name, minimum=1)
            )
        object.__setattr__(
            self, "concurrency", _exact_int(self.concurrency, "concurrency", minimum=1)
        )
        object.__setattr__(
            self,
            "orchestrator_algorithm_retries",
            _exact_int(
                self.orchestrator_algorithm_retries,
                "orchestrator_algorithm_retries",
            ),
        )
        object.__setattr__(
            self,
            "timeout_seconds",
            _float(self.timeout_seconds, "timeout_seconds", non_negative=True),
        )
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.pair_count != self.expected_attempts:
            raise ValueError("pair_count and expected_attempts must be identical")
        for name in (
            "metrics_allowed",
            "calibration_allowed",
            "threshold_allowed",
            "score_transform_allowed",
        ):
            if getattr(self, name) is not False:
                raise ValueError(f"{name} must remain false in Stage 21B")
        if self.orchestrator_algorithm_retries != 0:
            raise ValueError("Stage 21B does not retry algorithm failures")
        if self.infrastructure_resume_allowed is not True:
            raise ValueError("infrastructure resume must remain allowed")
        if self.concurrency != 1:
            raise ValueError("Stage 21B v1 is frozen to one sequential worker")
        object.__setattr__(self, "runtime_binding", _freeze_mapping(self.runtime_binding))
        object.__setattr__(
            self, "implementation_version", _text(self.implementation_version, "implementation_version")
        )
        object.__setattr__(self, "score_direction", _text(self.score_direction, "score_direction"))
        object.__setattr__(
            self, "execution_source_revision", _text(self.execution_source_revision, "execution_source_revision")
        )
        object.__setattr__(self, "created_utc", _text(self.created_utc, "created_utc"))

        expected = self.derive_fingerprint(self.semantic_payload())
        if self.run_spec_fingerprint != expected:
            raise ValueError("run_spec_fingerprint does not cover the run specification")
        if self.run_id != f"run_stage21b_{expected[:12]}":
            raise ValueError("run_id must be derived from run_spec_fingerprint")
        if self.result_set_id != f"resultset21b_{expected[:12]}":
            raise ValueError("result_set_id must be fixed before execution")

    @staticmethod
    def derive_fingerprint(payload: Mapping[str, Any]) -> str:
        return stable_hash(
            {"schema": "stage21b_frozen_run_spec_v1", "spec": _plain(payload)},
            length=64,
        )

    def semantic_payload(self) -> dict[str, Any]:
        value = self.to_dict()
        for key in ("run_id", "run_spec_fingerprint", "result_set_id", "created_utc"):
            value.pop(key)
        return value

    def to_dict(self) -> dict[str, Any]:
        return {
            name: _plain(getattr(self, name))
            for name in self.__dataclass_fields__
        }

    @classmethod
    def create(cls, *, created_utc: str, **values: Any) -> "FrozenRunSpec":
        semantic = {
            "schema_version": "1",
            "stage": STAGE,
            **values,
        }
        fingerprint = cls.derive_fingerprint(semantic)
        return cls(
            **semantic,
            run_id=f"run_stage21b_{fingerprint[:12]}",
            run_spec_fingerprint=fingerprint,
            result_set_id=f"resultset21b_{fingerprint[:12]}",
            created_utc=created_utc,
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FrozenRunSpec":
        return cls(**dict(value))


@dataclass(frozen=True, slots=True)
class TerminalOutcome:
    """Exactly one terminal biometric outcome for one planned pair."""

    schema_version: str
    run_id: str
    run_spec_fingerprint: str
    result_set_id: str
    algorithm_id: str
    adapter_id: str
    adapter_descriptor_fingerprint: str
    runtime_identity_fingerprint: str
    job_id: str
    attempt: int

    pair: PlannedPair
    status: Stage21BOutcomeStatus
    raw_score: float | None
    raw_score_hex: str | None

    failure_classification: str | None
    failure_code: str | None
    failure_stage: str | None
    failure_message: str | None
    failure_details: Mapping[str, str] = field(default_factory=dict)

    started_utc: str = ""
    finished_utc: str = ""
    wall_time_ms: float = 0.0
    adapter_timing_ms: Mapping[str, float] = field(default_factory=dict)
    adapter_metadata: Mapping[str, str] = field(default_factory=dict)
    artifacts: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if self.schema_version != "1":
            raise ValueError("terminal outcome schema_version must be '1'")
        for name in ("run_id", "result_set_id", "algorithm_id", "adapter_id", "job_id"):
            validate_id(getattr(self, name))
        for name in (
            "run_spec_fingerprint",
            "adapter_descriptor_fingerprint",
            "runtime_identity_fingerprint",
        ):
            object.__setattr__(self, name, _digest(getattr(self, name), name))
        object.__setattr__(self, "attempt", _exact_int(self.attempt, "attempt", minimum=1))
        object.__setattr__(
            self, "wall_time_ms", _float(self.wall_time_ms, "wall_time_ms", non_negative=True)
        )
        object.__setattr__(self, "started_utc", _text(self.started_utc, "started_utc"))
        object.__setattr__(self, "finished_utc", _text(self.finished_utc, "finished_utc"))
        object.__setattr__(self, "failure_details", MappingProxyType(dict(self.failure_details)))
        object.__setattr__(
            self,
            "adapter_timing_ms",
            MappingProxyType(
                {
                    str(key): _float(value, f"adapter_timing_ms[{key}]", non_negative=True)
                    for key, value in sorted(self.adapter_timing_ms.items())
                }
            ),
        )
        object.__setattr__(self, "adapter_metadata", MappingProxyType(dict(self.adapter_metadata)))
        object.__setattr__(
            self, "artifacts", tuple(_deep_freeze(item) for item in self.artifacts)
        )

        if self.status is Stage21BOutcomeStatus.SUCCESS:
            if self.raw_score is None or self.raw_score_hex is None:
                raise ValueError("SUCCESS requires one raw score")
            score = _float(self.raw_score, "raw_score")
            try:
                encoded_score = float.fromhex(str(self.raw_score_hex))
            except ValueError as exc:
                raise ValueError("raw_score_hex is not a hexadecimal float") from exc
            # Numeric equality is not enough here: -0.0 == 0.0.  The hexadecimal
            # spelling is the lossless identity that proves even signed zero was
            # not transformed while the record was serialised.
            if encoded_score.hex() != score.hex():
                raise ValueError("raw_score_hex is not the exact raw score")
            object.__setattr__(self, "raw_score", score)
            object.__setattr__(self, "raw_score_hex", score.hex())
            if any(
                value is not None
                for value in (
                    self.failure_classification,
                    self.failure_code,
                    self.failure_stage,
                    self.failure_message,
                )
            ) or self.failure_details:
                raise ValueError("SUCCESS must not carry failure information")
        else:
            if self.raw_score is not None or self.raw_score_hex is not None:
                raise ValueError("algorithm failure is not a score")
            if self.failure_classification != "algorithm_failure":
                raise ValueError("only classified algorithm failures are terminal")
            for name in ("failure_code", "failure_stage", "failure_message"):
                _text(getattr(self, name), name)

    @property
    def outcome_hash(self) -> str:
        return stable_hash(
            {"schema": "stage21b_terminal_outcome_v1", "outcome": self.to_dict()},
            length=64,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "run_spec_fingerprint": self.run_spec_fingerprint,
            "result_set_id": self.result_set_id,
            "algorithm_id": self.algorithm_id,
            "adapter_id": self.adapter_id,
            "adapter_descriptor_fingerprint": self.adapter_descriptor_fingerprint,
            "runtime_identity_fingerprint": self.runtime_identity_fingerprint,
            "job_id": self.job_id,
            "attempt": self.attempt,
            "pair": self.pair.to_dict(),
            "status": self.status.value,
            "raw_score": self.raw_score,
            "raw_score_hex": self.raw_score_hex,
            "failure_classification": self.failure_classification,
            "failure_code": self.failure_code,
            "failure_stage": self.failure_stage,
            "failure_message": self.failure_message,
            "failure_details": dict(self.failure_details),
            "started_utc": self.started_utc,
            "finished_utc": self.finished_utc,
            "wall_time_ms": self.wall_time_ms,
            "adapter_timing_ms": dict(self.adapter_timing_ms),
            "adapter_metadata": dict(self.adapter_metadata),
            "artifacts": [_plain(item) for item in self.artifacts],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TerminalOutcome":
        data = dict(value)
        data["pair"] = PlannedPair.from_dict(data["pair"])
        data["status"] = Stage21BOutcomeStatus(data["status"])
        data["artifacts"] = tuple(data.get("artifacts") or ())
        return cls(**data)
