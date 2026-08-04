"""Generic fixture-only smoke, SELF, determinism, and operational probes."""

from __future__ import annotations

import hashlib
import json
import math
import os
import secrets
import sys
import time
import ctypes
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from unittest.mock import patch

from fpbench.core.errors import QualificationError
from fpbench.core.modern_matcher_models import (
    STAGE8A_SCHEMA_VERSION,
    CandidateArtifactManifest,
    CandidateDeterminismReport,
    CandidateOperationalReport,
    CandidateRepresentationProfile,
    CandidateScoreProfile,
    RuntimeProbeResult,
)
from fpbench.modern_matchers.artifacts import ModernMatcherArtifactStore
from fpbench.modern_matchers.base import LearnedFingerprintIntegration
from fpbench.modern_matchers.offline import (
    offline_network_guard,
    sanitised_runtime_environment,
)

__all__ = [
    "RestartProbeChallenge",
    "IsolatedRestartObservation",
    "RuntimeProbeResult",
    "run_smoke_qualification",
]

_OS_NETWORK_ISOLATION_METHODS = frozenset(
    {
        "container_network_none",
        "linux_network_namespace",
        "macos_sandbox_network_deny",
        "windows_firewall_block",
    }
)
_RUNTIME_METADATA_KEYS = frozenset(
    {"runtime_kind", "runtime_version", "driver_version", "device_class"}
)


def _seconds(value: float) -> str:
    return format(Decimal(str(value)), "f")


def _time_limit(value: Decimal | int, name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (Decimal, int)):
        raise QualificationError(f"{name} must be an exact Decimal or integer")
    limit = Decimal(value)
    if not limit.is_finite() or limit < 0:
        raise QualificationError(f"{name} must be finite and non-negative")
    return limit


def _byte_limit(value: int, name: str) -> int:
    if type(value) is not int or value < 0:
        raise QualificationError(f"{name} must be a non-negative exact integer")
    return value


def _peak_process_rss_bytes() -> int:
    """Return the process peak resident set, including native ML allocations."""
    if os.name == "nt":
        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = (
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            )

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        get_current_process = ctypes.windll.kernel32.GetCurrentProcess
        get_process_memory_info = ctypes.windll.psapi.GetProcessMemoryInfo
        get_current_process.argtypes = ()
        get_current_process.restype = ctypes.c_void_p
        get_process_memory_info.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(ProcessMemoryCounters),
            ctypes.c_ulong,
        )
        get_process_memory_info.restype = ctypes.c_int
        if not get_process_memory_info(
            get_current_process(), ctypes.byref(counters), counters.cb
        ):
            raise QualificationError("could not measure process peak RAM")
        return int(counters.PeakWorkingSetSize)
    try:
        import resource

        peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    except (ImportError, OSError, ValueError) as exc:
        raise QualificationError(f"could not measure process peak RAM: {exc}") from exc
    return peak if sys.platform == "darwin" else peak * 1024


def _score(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise QualificationError("compare() must return a Decimal or exact int, never bool or float")
    number = Decimal(value)
    if not number.is_finite():
        raise QualificationError("compare() returned a non-finite raw score")
    return number


def _score_hash(value: Any) -> str:
    """Hash the exact public raw-score representation, including its type."""
    _score(value)
    if type(value) is int:
        payload: Any = {"type": "int", "value": str(value)}
    else:
        decimal_value = value
        payload = {
            "type": "Decimal",
            "sign": decimal_value.as_tuple().sign,
            "digits": list(decimal_value.as_tuple().digits),
            "exponent": decimal_value.as_tuple().exponent,
        }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _plain_representation(value: Any) -> Any:
    if isinstance(value, bool):
        raise QualificationError("a boolean is not a numeric representation")
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise QualificationError("representation contains a non-finite Decimal")
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise QualificationError("representation contains NaN or infinity")
        return value.hex()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"bytes_sha256": hashlib.sha256(bytes(value)).hexdigest(), "size": len(value)}
    if isinstance(value, Mapping):
        return {str(key): _plain_representation(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_plain_representation(item) for item in value]
    if hasattr(value, "tobytes") and hasattr(value, "shape"):
        if hasattr(value, "tolist"):
            # Hashing bytes alone would accept a NaN/Inf representation.  Walk
            # the fixture-sized values as well, without importing an ML stack.
            _plain_representation(value.tolist())
        raw = value.tobytes()
        return {
            "shape": [int(item) for item in value.shape],
            "dtype": str(getattr(value, "dtype", "unknown")),
            "bytes_sha256": hashlib.sha256(raw).hexdigest(),
        }
    raise QualificationError(f"unsupported representation type {type(value).__name__}")


def _representation_hash(value: Any) -> str:
    payload = json.dumps(_plain_representation(value), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _representation_shape_and_dtype(value: Any) -> tuple[tuple[int, ...], str]:
    if hasattr(value, "shape") and hasattr(value, "dtype"):
        try:
            shape = tuple(int(item) for item in value.shape)
        except (TypeError, ValueError) as exc:
            raise QualificationError(
                "representation shape must contain exact integer dimensions"
            ) from exc
        return shape, str(value.dtype)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return (len(value),), "uint8"
    if isinstance(value, (list, tuple)):
        return (len(value),), "python_sequence"
    raise QualificationError(
        "representation must expose shape and dtype for contract qualification"
    )


def _validate_representation_profile(
    value: Any, profile: CandidateRepresentationProfile
) -> None:
    shape, dtype = _representation_shape_and_dtype(value)
    if shape != profile.representation_shape:
        raise QualificationError(
            "observed representation shape contradicts the frozen profile"
        )
    if dtype.lower() != profile.representation_dtype.lower():
        raise QualificationError(
            "observed representation dtype contradicts the frozen profile"
        )
    if len(profile.branches) == 1:
        branch = profile.branches[0]
        if branch.shape != shape:
            raise QualificationError(
                "observed representation shape contradicts its scored branch"
            )
    elif isinstance(value, Mapping):
        for branch in profile.branches:
            if branch.branch_id not in value:
                raise QualificationError(
                    f"representation is missing documented branch {branch.branch_id}"
                )
            branch_shape, _branch_dtype = _representation_shape_and_dtype(
                value[branch.branch_id]
            )
            if branch_shape != branch.shape:
                raise QualificationError(
                    f"observed branch {branch.branch_id} shape contradicts the profile"
                )
    else:
        raise QualificationError(
            "a multi-branch representation must expose branches by documented id"
        )


_FORBIDDEN_OPERATION_KEYS = frozenset(
    {
        "threshold",
        "dataset_name",
        "subject_id",
        "label",
        "ground_truth",
        "template_cache",
        "persistent_embedding_store",
    }
)


def _require_context_free_metadata(value: Any, *, location: str) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).strip().lower()
            if normalized in _FORBIDDEN_OPERATION_KEYS:
                raise QualificationError(
                    f"{location}.{key} exposes forbidden threshold, label, "
                    "dataset, or persistence state"
                )
            _require_context_free_metadata(
                nested, location=f"{location}.{key}"
            )
        return
    if isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _require_context_free_metadata(
                nested, location=f"{location}[{index}]"
            )


def _validated_runtime_metadata(
    value: Any,
    *,
    runtime_kind: str,
    runtime_version: str,
    driver_version: str | None,
    device_class: str | None,
) -> Mapping[str, str | None]:
    """Bind the predeclared runtime to what the loaded integration reports."""
    if runtime_kind not in {"CPU", "CUDA"}:
        raise QualificationError("runtime_kind must be exactly CPU or CUDA")
    if not isinstance(runtime_version, str) or not runtime_version.strip():
        raise QualificationError("runtime_version must be non-empty text")
    for name, item in (
        ("driver_version", driver_version),
        ("device_class", device_class),
    ):
        if item is not None and (
            not isinstance(item, str) or not item.strip()
        ):
            raise QualificationError(f"{name} must be non-empty text or null")
    if runtime_kind == "CUDA" and (
        driver_version is None or device_class is None
    ):
        raise QualificationError(
            "CUDA qualification requires exact driver_version and device_class"
        )
    if not isinstance(value, Mapping):
        raise QualificationError("validate_runtime() must return a mapping")
    actual = dict(value)
    if set(actual) != _RUNTIME_METADATA_KEYS:
        raise QualificationError(
            "validate_runtime() must report exactly runtime_kind, runtime_version, "
            "driver_version, and device_class"
        )
    expected: dict[str, str | None] = {
        "runtime_kind": runtime_kind,
        "runtime_version": runtime_version,
        "driver_version": driver_version,
        "device_class": device_class,
    }
    for name, expected_value in expected.items():
        if actual[name] != expected_value or type(actual[name]) is not type(
            expected_value
        ):
            raise QualificationError(
                f"validate_runtime() {name} contradicts the predeclared runtime"
            )
    return expected


def _tree_snapshot(roots: Sequence[Path]) -> tuple[tuple[str, int, int, str], ...]:
    rows: list[tuple[str, int, int, str]] = []
    for root in roots:
        root = Path(root)
        if not root.exists():
            continue
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            info = path.stat()
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1 << 20), b""):
                    digest.update(block)
            rows.append(
                (str(path.resolve()), info.st_size, info.st_mtime_ns, digest.hexdigest())
            )
    return tuple(rows)


@dataclass(frozen=True, slots=True)
class RestartProbeChallenge:
    """Fresh identity-bound challenge that an isolated runner must attest."""

    candidate_fingerprint: str
    artifact_manifest_fingerprint: str
    left_fixture_hash: str
    right_fixture_hash: str
    runtime_kind: str
    runtime_version: str
    driver_version: str | None
    device_class: str | None
    nonce: str

    def __post_init__(self) -> None:
        for name in (
            "candidate_fingerprint",
            "artifact_manifest_fingerprint",
            "left_fixture_hash",
            "right_fixture_hash",
            "nonce",
        ):
            value = str(getattr(self, name)).lower()
            if len(value) != 64 or any(
                character not in "0123456789abcdef" for character in value
            ):
                raise ValueError(f"{name} must be a SHA-256-sized lowercase hex value")
            object.__setattr__(self, name, value)

    @property
    def fingerprint(self) -> str:
        payload = {
            name: getattr(self, name)
            for name in (
                "candidate_fingerprint",
                "artifact_manifest_fingerprint",
                "left_fixture_hash",
                "right_fixture_hash",
                "runtime_kind",
                "runtime_version",
                "driver_version",
                "device_class",
                "nonce",
            )
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class IsolatedRestartObservation:
    """Identity-bound output from a real child process under an OS network block."""

    challenge_fingerprint: str
    raw_score: Decimal | int
    left_representation_hash: str
    right_representation_hash: str
    process_id: int
    parent_process_id: int
    network_isolation_method: str
    isolation_attestation_bytes: bytes

    def __post_init__(self) -> None:
        _score(self.raw_score)
        for name in (
            "challenge_fingerprint",
            "left_representation_hash",
            "right_representation_hash",
        ):
            value = str(getattr(self, name)).lower()
            if len(value) != 64 or any(
                character not in "0123456789abcdef" for character in value
            ):
                raise ValueError(f"{name} must be a SHA-256")
            object.__setattr__(self, name, value)
        for name in ("process_id", "parent_process_id"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive exact integer")
        if self.process_id == self.parent_process_id:
            raise ValueError("restart observation must name a distinct child process")
        method = str(self.network_isolation_method).strip()
        if method not in _OS_NETWORK_ISOLATION_METHODS:
            raise ValueError("network isolation method is not an approved OS boundary")
        object.__setattr__(self, "network_isolation_method", method)
        if not isinstance(self.isolation_attestation_bytes, bytes):
            raise ValueError("isolation_attestation_bytes must be immutable bytes")
        if not self.isolation_attestation_bytes:
            raise ValueError("an OS isolation attestation must not be empty")

    @property
    def isolation_evidence_fingerprint(self) -> str:
        claims = json.dumps(
            {
                "challenge_fingerprint": self.challenge_fingerprint,
                "left_representation_hash": self.left_representation_hash,
                "right_representation_hash": self.right_representation_hash,
                "score_hash": _score_hash(self.raw_score),
                "process_id": self.process_id,
                "parent_process_id": self.parent_process_id,
                "network_isolation_method": self.network_isolation_method,
                "attestation_sha256": hashlib.sha256(
                    self.isolation_attestation_bytes
                ).hexdigest(),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(claims).hexdigest()


def run_smoke_qualification(
    *,
    integration_factory: Callable[[], LearnedFingerprintIntegration],
    artifact_manifest: CandidateArtifactManifest,
    artifact_root: Path,
    representation_profile: CandidateRepresentationProfile,
    score_profile: CandidateScoreProfile,
    left_image_bytes: bytes,
    right_image_bytes: bytes,
    runtime_kind: str,
    runtime_version: str,
    driver_version: str | None,
    device_class: str | None,
    max_projected_12000_extractions_seconds: Decimal | int,
    max_projected_6000_comparisons_seconds: Decimal | int,
    max_peak_ram_bytes: int,
    max_peak_vram_bytes: int,
    max_artifact_disk_bytes: int,
    inspected_utc: str,
    restart_probe: Callable[
        [RestartProbeChallenge, bytes, bytes], IsolatedRestartObservation
    ],
    batch_probe: Callable[
        [LearnedFingerprintIntegration, Sequence[Any]], Sequence[Any]
    ],
    watched_roots: Sequence[Path] = (),
    numeric_tolerance: Decimal = Decimal("0"),
) -> RuntimeProbeResult:
    """Exercise only non-SD300 fixture bytes, with network access refused."""
    if not isinstance(left_image_bytes, bytes) or not isinstance(right_image_bytes, bytes):
        raise QualificationError("smoke fixtures must be byte strings")
    if not left_image_bytes or not right_image_bytes:
        raise QualificationError("smoke fixtures must not be empty")
    if not representation_profile.complete:
        raise QualificationError(
            "smoke qualification requires a complete representation profile"
        )
    if not score_profile.complete:
        raise QualificationError(
            "smoke qualification requires a complete raw-score profile"
        )
    if numeric_tolerance < 0 or not numeric_tolerance.is_finite():
        raise QualificationError("numeric_tolerance must be finite and non-negative")
    extraction_limit = _time_limit(
        max_projected_12000_extractions_seconds,
        "max_projected_12000_extractions_seconds",
    )
    comparison_limit = _time_limit(
        max_projected_6000_comparisons_seconds,
        "max_projected_6000_comparisons_seconds",
    )
    ram_limit = _byte_limit(max_peak_ram_bytes, "max_peak_ram_bytes")
    vram_limit = _byte_limit(max_peak_vram_bytes, "max_peak_vram_bytes")
    disk_limit = _byte_limit(max_artifact_disk_bytes, "max_artifact_disk_bytes")
    artifact_store = ModernMatcherArtifactStore(Path(artifact_root))
    verified_artifacts = artifact_store.verify_manifest(artifact_manifest)
    artifact_disk_bytes = sum(
        path.stat().st_size for path in set(verified_artifacts.values())
    )
    if not watched_roots:
        raise QualificationError(
            "at least one isolated persistence root must be watched during qualification"
        )
    observation_roots = tuple(
        dict.fromkeys((Path(artifact_root), *(Path(root) for root in watched_roots)))
    )
    for root in observation_roots:
        if not Path(root).is_dir():
            raise QualificationError(
                f"watched persistence root is not a directory: {root}"
            )

    left_fixture_hash = hashlib.sha256(left_image_bytes).hexdigest()
    right_fixture_hash = hashlib.sha256(right_image_bytes).hexdigest()
    before = _tree_snapshot(observation_roots)
    extraction_calls = 0
    comparison_calls = 0
    with patch.dict(
        os.environ, sanitised_runtime_environment(), clear=True
    ), offline_network_guard():
            start = time.perf_counter()
            integration = integration_factory()
            startup_seconds = time.perf_counter() - start
            start = time.perf_counter()
            integration.load_runtime()
            model_load_seconds = time.perf_counter() - start
            runtime_description = _validated_runtime_metadata(
                integration.validate_runtime(),
                runtime_kind=runtime_kind,
                runtime_version=runtime_version,
                driver_version=driver_version,
                device_class=device_class,
            )
            description = dict(integration.describe_operation())
            _require_context_free_metadata(
                runtime_description, location="runtime"
            )
            _require_context_free_metadata(description, location="operation")
            if (
                description.get("representation_profile_fingerprint")
                != representation_profile.fingerprint
            ):
                raise QualificationError(
                    "runtime operation does not bind the frozen representation profile"
                )
            if (
                description.get("score_profile_fingerprint")
                != score_profile.fingerprint
            ):
                raise QualificationError(
                    "runtime operation does not bind the frozen score profile"
                )

            left_input = integration.preprocess(left_image_bytes)
            right_input = integration.preprocess(right_image_bytes)
            self_input = integration.preprocess(left_image_bytes)
            start = time.perf_counter()
            left_representation = integration.extract(left_input)
            extraction_seconds = time.perf_counter() - start
            extraction_calls += 1
            right_representation = integration.extract(right_input)
            extraction_calls += 1
            repeated_self = integration.extract(self_input)
            extraction_calls += 1
            repeated_left = integration.extract(
                integration.preprocess(left_image_bytes)
            )
            extraction_calls += 1

            for observed in (
                left_representation,
                right_representation,
                repeated_self,
                repeated_left,
            ):
                _validate_representation_profile(
                    observed, representation_profile
                )

            left_hash = _representation_hash(left_representation)
            right_hash = _representation_hash(right_representation)
            self_hash = _representation_hash(repeated_self)
            repeated_hash = _representation_hash(repeated_left)

            start = time.perf_counter()
            raw_score = integration.compare(
                left_representation, right_representation
            )
            score = _score(raw_score)
            score_hash = _score_hash(raw_score)
            comparison_seconds = time.perf_counter() - start
            comparison_calls += 1
            raw_reverse = integration.compare(
                right_representation, left_representation
            )
            reverse = _score(raw_reverse)
            reverse_hash = _score_hash(raw_reverse)
            comparison_calls += 1
            raw_repeated = integration.compare(
                left_representation, right_representation
            )
            repeated = _score(raw_repeated)
            repeated_score_hash = _score_hash(raw_repeated)
            comparison_calls += 1
            if score_profile.score_minimum is not None:
                lower = Decimal(score_profile.score_minimum)
                upper = Decimal(score_profile.score_maximum)
                if any(
                    observed < lower or observed > upper
                    for observed in (score, reverse, repeated)
                ):
                    raise QualificationError(
                        "observed raw score falls outside the frozen score profile"
                    )

            batch_values = tuple(
                batch_probe(integration, (left_input, right_input))
            )
            if len(batch_values) != 2:
                raise QualificationError(
                    "batch probe must return one representation per image"
                )
            batch_hashes = tuple(
                _representation_hash(value) for value in batch_values
            )
            for observed in batch_values:
                _validate_representation_profile(
                    observed, representation_profile
                )
            challenge = RestartProbeChallenge(
                candidate_fingerprint=artifact_manifest.candidate_fingerprint,
                artifact_manifest_fingerprint=artifact_manifest.fingerprint,
                left_fixture_hash=left_fixture_hash,
                right_fixture_hash=right_fixture_hash,
                runtime_kind=runtime_kind,
                runtime_version=runtime_version,
                driver_version=driver_version,
                device_class=device_class,
                nonce=secrets.token_hex(32),
            )
            restart_observation = restart_probe(
                challenge, left_image_bytes, right_image_bytes
            )
            if not isinstance(
                restart_observation, IsolatedRestartObservation
            ):
                raise QualificationError(
                    "restart probe must return an isolated child-process observation"
                )
            if (
                restart_observation.parent_process_id != os.getpid()
                or restart_observation.process_id == os.getpid()
            ):
                raise QualificationError(
                    "restart attestation does not identify this parent and a distinct child"
                )
            if restart_observation.challenge_fingerprint != challenge.fingerprint:
                raise QualificationError(
                    "restart attestation does not answer the fresh identity-bound challenge"
                )
            restarted = _score(restart_observation.raw_score)
            restarted_score_hash = _score_hash(
                restart_observation.raw_score
            )
            if score_profile.score_minimum is not None and not (
                Decimal(score_profile.score_minimum)
                <= restarted
                <= Decimal(score_profile.score_maximum)
            ):
                raise QualificationError(
                    "restarted raw score falls outside the frozen score profile"
                )
            process_restart_isolated = True
            offline_execution_proven = True
            isolation_evidence_fingerprint = (
                restart_observation.isolation_evidence_fingerprint
            )

    peak_ram = _peak_process_rss_bytes()
    after = _tree_snapshot(observation_roots)
    no_persistence = before == after
    if not no_persistence:
        raise QualificationError("smoke qualification created or changed a persistent representation file")

    drifts = (
        abs(score - reverse),
        abs(score - repeated),
        abs(score - restarted),
    )
    maximum_drift = max(drifts)
    representation_observations_equal = (
        left_hash == self_hash == repeated_hash
        and batch_hashes == (left_hash, right_hash)
        and restart_observation.left_representation_hash == left_hash
        and restart_observation.right_representation_hash == right_hash
    )
    score_observations_equal = (
        score_hash
        == reverse_hash
        == repeated_score_hash
        == restarted_score_hash
    )
    bitwise = (
        representation_observations_equal and score_observations_equal
    )
    within_tolerance = (
        representation_observations_equal
        and maximum_drift <= numeric_tolerance
    )
    determinism = CandidateDeterminismReport.create(
        schema_version=STAGE8A_SCHEMA_VERSION,
        report_id="stage8a_fixture_determinism",
        tested=True,
        runtime_kind=runtime_kind,
        runtime_version=runtime_version,
        driver_version=driver_version,
        device_class=device_class,
        repeated_extraction_equal=left_hash == self_hash == repeated_hash,
        repeated_comparison_equal=score_hash == repeated_score_hash,
        single_image_vs_batch_equal=batch_hashes == (left_hash, right_hash),
        process_restart_equal=(
            score_hash == restarted_score_hash
        ),
        process_restart_representation_equal=(
            restart_observation.left_representation_hash == left_hash
            and restart_observation.right_representation_hash == right_hash
        ),
        input_order_equal=score_hash == reverse_hash,
        bitwise_equal=bitwise,
        numeric_tolerance=None if bitwise else str(numeric_tolerance),
        maximum_observed_score_drift=None if bitwise else str(maximum_drift),
        within_predeclared_tolerance=within_tolerance,
        nondeterminism_reason=None if bitwise else "candidate runtime produced numeric drift under a mandatory probe",
        runtime_restrictions=(
            ()
            if bitwise
            else (
                "raw-score qualification only; no threshold decision is safe "
                "without a separately proven guard protocol",
            )
        ),
        decision_safe=bitwise,
        inspected_utc=inspected_utc,
    )
    projected_extractions = _seconds(extraction_seconds * 12000)
    projected_comparisons = _seconds(comparison_seconds * 6000)
    if runtime_kind == "CPU":
        peak_vram = 0
    else:
        peak_vram = description.get("peak_vram_bytes")
        if type(peak_vram) is not int or peak_vram < 0:
            raise QualificationError(
                "a non-CPU runtime must report peak_vram_bytes as a "
                "non-negative exact integer"
            )
    operationally_feasible = (
        Decimal(projected_extractions) <= extraction_limit
        and Decimal(projected_comparisons) <= comparison_limit
        and peak_ram <= ram_limit
        and peak_vram <= vram_limit
        and artifact_disk_bytes <= disk_limit
    )
    operational = CandidateOperationalReport.create(
        schema_version=STAGE8A_SCHEMA_VERSION,
        report_id="stage8a_fixture_operational",
        measured=True,
        startup_seconds=_seconds(startup_seconds),
        model_load_seconds=_seconds(model_load_seconds),
        extraction_seconds=_seconds(extraction_seconds),
        comparison_seconds=_seconds(comparison_seconds),
        peak_ram_bytes=peak_ram,
        peak_vram_bytes=peak_vram,
        artifact_disk_bytes=artifact_disk_bytes,
        projected_12000_extractions_seconds=projected_extractions,
        projected_6000_comparisons_seconds=projected_comparisons,
        max_projected_12000_extractions_seconds=str(extraction_limit),
        max_projected_6000_comparisons_seconds=str(comparison_limit),
        max_peak_ram_bytes=ram_limit,
        max_peak_vram_bytes=vram_limit,
        max_artifact_disk_bytes=disk_limit,
        operationally_feasible=operationally_feasible,
        measurement_scope="fixture-only capacity estimate; no biometric performance claim",
        inspected_utc=inspected_utc,
    )
    return RuntimeProbeResult.create(
        schema_version=STAGE8A_SCHEMA_VERSION,
        candidate_fingerprint=artifact_manifest.candidate_fingerprint,
        artifact_manifest_fingerprint=artifact_manifest.fingerprint,
        left_fixture_hash=left_fixture_hash,
        right_fixture_hash=right_fixture_hash,
        left_representation_hash=left_hash,
        right_representation_hash=right_hash,
        repeated_self_representation_hash=self_hash,
        repeated_left_representation_hash=repeated_hash,
        batch_left_representation_hash=batch_hashes[0],
        batch_right_representation_hash=batch_hashes[1],
        restarted_left_representation_hash=(
            restart_observation.left_representation_hash
        ),
        restarted_right_representation_hash=(
            restart_observation.right_representation_hash
        ),
        left_score_hash=score_hash,
        reverse_score_hash=reverse_hash,
        repeated_score_hash=repeated_score_hash,
        restarted_score_hash=restarted_score_hash,
        extraction_calls=extraction_calls,
        comparison_calls=comparison_calls,
        no_representation_persistence=no_persistence,
        process_restart_isolated=process_restart_isolated,
        offline_execution_proven=offline_execution_proven,
        isolation_evidence_fingerprint=isolation_evidence_fingerprint,
        determinism_report=determinism,
        operational_report=operational,
    )
