"""Build the certified adapters and preserve their predecessor failure split."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping

import yaml

from fpbench.adapters.base import FingerprintAlgorithmAdapter
from fpbench.adapters.registry import create_adapter
from fpbench.core.enums import EnvironmentStatus, FailureCode
from fpbench.core.execution_models import (
    EnvironmentReport,
    FailureInfo,
    descriptor_fingerprint,
    environment_fingerprint,
)
from fpbench.core.serialization import stable_hash
from fpbench.stage21b.bindings import AlgorithmBinding
from fpbench.stage21b.errors import Stage21BPreflightError


class FailureDisposition(str, Enum):
    ALGORITHM = "algorithm_failure"
    INFRASTRUCTURE = "infrastructure_failure"


FailureClassifier = Callable[[FailureInfo], FailureDisposition]

_EXPECTED_RUNTIME_ASSET_ROLES = {
    "sourceafis_java_subprocess": {"sourceafis_bridge_jar"},
    "nbis_mindtct_bozorth3_subprocess": {
        "nbis_mindtct_executable",
        "nbis_bozorth3_executable",
        "nbis_build_manifest",
    },
    "flx_pytorch_subprocess": {
        "flx_worker_script",
        "flx_runtime_lock",
        "flx_runtime_policy",
    },
    "verifinger_java_subprocess": {
        "verifinger_bridge_jar",
        "verifinger_runtime_manifest",
        "verifinger_runtime_policy",
    },
    "nbis_mindtct_mcc_sdk_v2_subprocess": {
        "nbis_mindtct_executable",
        "nbis_build_manifest",
        "mcc_match_bridge",
        "mcc_bridge_manifest",
        "mcc_sdk_dll",
    },
    "nbis_mindtct_openafis_capacity_extended_subprocess": {
        "nbis_mindtct_executable",
        "nbis_build_manifest",
        "openafis_match_bridge",
    },
}


@dataclass(frozen=True, slots=True)
class RuntimeAssetIdentity:
    role: str
    sha256: str
    size_bytes: int

    def to_dict(self) -> dict[str, Any]:
        return {"role": self.role, "sha256": self.sha256, "size_bytes": self.size_bytes}


@dataclass(frozen=True, slots=True)
class CertifiedAdapterRuntime:
    adapter: FingerprintAlgorithmAdapter
    environment: EnvironmentReport
    descriptor_fingerprint: str
    environment_fingerprint: str
    runtime_identity_fingerprint: str
    assets: tuple[RuntimeAssetIdentity, ...]
    adapter_config_sha256: str
    environment_validation_ms: float

    def binding_document(self) -> dict[str, Any]:
        return {
            "adapter_id": self.adapter.descriptor.adapter_id,
            "algorithm_id": self.adapter.descriptor.algorithm_id,
            "implementation_version": self.adapter.descriptor.implementation_version,
            "descriptor_fingerprint": self.descriptor_fingerprint,
            "environment_fingerprint": self.environment_fingerprint,
            "runtime_identity_fingerprint": self.runtime_identity_fingerprint,
            "runtime": dict(self.environment.runtime),
            "dependencies": dict(self.environment.dependencies),
            "assets": [asset.to_dict() for asset in self.assets],
            "adapter_config_sha256": self.adapter_config_sha256,
        }


def load_certified_adapter(
    *,
    config_path: Path,
    binding: AlgorithmBinding,
    accepted_predecessor_digests: frozenset[str] | None = None,
) -> CertifiedAdapterRuntime:
    """Build one adapter from a private path-only config and verify its identity."""
    path = Path(config_path).resolve()
    document = _mapping_file(path)
    expected_keys = {"schema_version", "algorithm_id", "adapter_id", "adapter_config"}
    if set(document) != expected_keys:
        raise Stage21BPreflightError(
            f"{path}: keys are {sorted(document)}, expected {sorted(expected_keys)}"
        )
    if document.get("schema_version") != 1:
        raise Stage21BPreflightError(f"{path}: schema_version must be integer 1")
    if document.get("algorithm_id") != binding.algorithm_id:
        raise Stage21BPreflightError(f"{path}: algorithm_id does not match Stage 21A")
    if document.get("adapter_id") != binding.adapter_id:
        raise Stage21BPreflightError(f"{path}: adapter_id does not match Stage 21A")
    config = document.get("adapter_config")
    if not isinstance(config, Mapping):
        raise Stage21BPreflightError(f"{path}: adapter_config must be a mapping")

    if binding.adapter_id == "flx_pytorch_subprocess":
        from fpbench.experiments.flx_adapter import FlxAdapter, FlxConfig

        allowed = {
            "bundle_root",
            "worker_script",
            "runtime_lock",
            "runtime_policy",
            "research_mode",
        }
        if set(config) != allowed:
            raise Stage21BPreflightError(
                f"{path}: flx adapter_config keys must be {sorted(allowed)}"
            )
        if config.get("research_mode") is not True:
            raise Stage21BPreflightError("the FLX Stage 21B adapter must be in research mode")
        adapter: FingerprintAlgorithmAdapter = FlxAdapter(
            FlxConfig(
                bundle_root=Path(str(config["bundle_root"])).resolve(),
                worker_script=Path(str(config["worker_script"])).resolve(),
                runtime_lock=Path(str(config["runtime_lock"])).resolve(),
                runtime_policy=Path(str(config["runtime_policy"])).resolve(),
                research_mode=True,
            )
        )
    else:
        adapter = create_adapter(binding.adapter_id, config)

    adapter_config = getattr(adapter, "config", None)
    research_mode = getattr(adapter, "research_mode", None)
    if research_mode is None:
        research_mode = getattr(adapter_config, "research_mode", None)
    if research_mode is not True:
        raise Stage21BPreflightError(
            "Stage 21B requires the certified adapter's pinned research mode"
        )

    descriptor = adapter.descriptor
    if descriptor.algorithm_id != binding.algorithm_id:
        raise Stage21BPreflightError("adapter algorithm identity differs from Stage 21A")
    if descriptor.adapter_id != binding.adapter_id:
        raise Stage21BPreflightError("adapter route identity differs from Stage 21A")
    if descriptor.implementation_version != binding.implementation_version:
        raise Stage21BPreflightError(
            "adapter implementation version differs from the Stage 21A roster"
        )
    if descriptor.score_direction.value != binding.score_direction:
        raise Stage21BPreflightError("adapter score direction differs from Stage 21A")

    environment_started = time.perf_counter_ns()
    environment = adapter.validate_environment()
    environment_validation_ms = (
        time.perf_counter_ns() - environment_started
    ) / 1_000_000.0
    if environment.status is not EnvironmentStatus.READY:
        raise Stage21BPreflightError(
            "adapter/runtime is unavailable: " + (environment.message or "no detail")
        )
    if environment.implementation_version != binding.implementation_version:
        raise Stage21BPreflightError(
            "runtime implementation version differs from the Stage 21A roster"
        )
    assets = _runtime_assets(adapter)
    if not assets:
        raise Stage21BPreflightError("the certified adapter exposes no runtime assets")
    expected_roles = _EXPECTED_RUNTIME_ASSET_ROLES[binding.adapter_id]
    actual_roles = {asset.role for asset in assets}
    if actual_roles != expected_roles:
        raise Stage21BPreflightError(
            "runtime asset roles differ from the frozen route "
            f"(missing={sorted(expected_roles-actual_roles)}, "
            f"extra={sorted(actual_roles-expected_roles)})"
        )
    if accepted_predecessor_digests is not None:
        exempt = {"mcc_bridge_manifest"}
        mismatched = [
            asset.role
            for asset in assets
            if asset.role not in exempt and asset.sha256 not in accepted_predecessor_digests
        ]
        if mismatched:
            raise Stage21BPreflightError(
                "runtime assets are not present in accepted predecessor evidence: "
                + ", ".join(mismatched)
            )

    descriptor_hash = descriptor_fingerprint(descriptor)
    environment_hash = environment_fingerprint(environment)
    config_hash = _sha256(path)
    runtime_hash = stable_hash(
        {
            "schema": "stage21b_runtime_identity_v1",
            "descriptor_fingerprint": descriptor_hash,
            "environment_fingerprint": environment_hash,
            "assets": [asset.to_dict() for asset in assets],
            "adapter_config_sha256": config_hash,
        },
        length=64,
    )
    return CertifiedAdapterRuntime(
        adapter=adapter,
        environment=environment,
        descriptor_fingerprint=descriptor_hash,
        environment_fingerprint=environment_hash,
        runtime_identity_fingerprint=runtime_hash,
        assets=assets,
        adapter_config_sha256=config_hash,
        environment_validation_ms=environment_validation_ms,
    )


def accepted_predecessor_digests(
    repository_root: Path, *, binding: AlgorithmBinding | None = None
) -> frozenset[str]:
    """SHA-256 values carried by the relevant hash-bound predecessor docs.

    With a binding, a runtime asset must occur in that method's predecessor
    closure rather than merely somewhere in the six-method evidence union.
    """
    root = Path(repository_root).resolve()
    predecessor_document = json.loads(
        (
            root
            / "evidence/stage21a-final-baseline-evaluation-protocol/predecessor-bindings.json"
        ).read_text(encoding="utf-8")
    )
    found: set[str] = set()
    for row in predecessor_document.get("documents", []):
        relative = str(row.get("path", ""))
        if binding is not None and not _document_belongs_to_route(
            relative, binding.adapter_id
        ):
            continue
        path = root / relative
        if not path.is_file() or path.suffix.lower() != ".json":
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        _collect_digests(value, found)
        found.add(str(row.get("sha256", "")))
    return frozenset(item for item in found if _is_digest(item))


def _document_belongs_to_route(relative: str, adapter_id: str) -> bool:
    normalized = relative.replace("\\", "/").lower()
    route_fragments = {
        "sourceafis_java_subprocess": (
            "sourceafis_java_3_18_1",
            "sourceafis-canonical500-full",
            "run_4c59fa02a6ab",
        ),
        "nbis_mindtct_bozorth3_subprocess": (
            "nbis_mindtct_bozorth3_5_0_0",
            "nbis-canonical500-raw",
        ),
        "flx_pytorch_subprocess": (
            "flx_deepprint_texminu",
            "flx-canonical500-raw",
        ),
        "verifinger_java_subprocess": (
            "verifinger_2025_2",
            "stage11b-verifinger-canonical500-raw",
        ),
        "nbis_mindtct_mcc_sdk_v2_subprocess": (
            "stage20b-mindtct-mcc-canonical500-raw",
        ),
        "nbis_mindtct_openafis_capacity_extended_subprocess": (
            "stage19b-openafis-capacity-extended",
        ),
    }
    try:
        fragments = route_fragments[adapter_id]
    except KeyError:
        raise Stage21BPreflightError(
            f"no predecessor-document route is frozen for {adapter_id!r}"
        ) from None
    return any(fragment in normalized for fragment in fragments)


def classifier_for(policy_id: str) -> FailureClassifier:
    policies: dict[str, FailureClassifier] = {
        "sourceafis_certified_v1": _code_classifier(
            {FailureCode.TEMPLATE_EXTRACTION_FAILED, FailureCode.MATCHING_FAILED}
        ),
        "nbis_certified_v1": _code_classifier(
            {FailureCode.TEMPLATE_EXTRACTION_FAILED, FailureCode.TIMEOUT}
        ),
        "flx_certified_v1": _code_classifier(
            {
                FailureCode.IMAGE_DECODE_FAILED,
                FailureCode.PREPARATION_FAILED,
                FailureCode.TEMPLATE_EXTRACTION_FAILED,
                FailureCode.MATCHING_FAILED,
                FailureCode.TIMEOUT,
                FailureCode.PROCESS_CRASHED,
            }
        ),
        "verifinger_certified_v1": _code_classifier(
            {FailureCode.TEMPLATE_EXTRACTION_FAILED}
        ),
        "mcc_stage20b_certified_v1": _classify_mcc,
        "openafis_stage19b_certified_v1": _classify_openafis,
    }
    try:
        return policies[policy_id]
    except KeyError:
        raise Stage21BPreflightError(
            f"unknown frozen failure classifier {policy_id!r}"
        ) from None


def _code_classifier(codes: set[FailureCode]) -> FailureClassifier:
    frozen = frozenset(codes)

    def classify(failure: FailureInfo) -> FailureDisposition:
        return (
            FailureDisposition.ALGORITHM
            if failure.code in frozen
            else FailureDisposition.INFRASTRUCTURE
        )

    return classify


def _classify_openafis(failure: FailureInfo) -> FailureDisposition:
    status = str(failure.details.get("stage19_status", ""))
    algorithm_prefixes = (
        "MINDTCT_FAILED_",
        "INVALID_XYT_",
        "OPENAFIS_TEMPLATE_FAILED_",
    )
    return (
        FailureDisposition.ALGORITHM
        if status.startswith(algorithm_prefixes)
        else FailureDisposition.INFRASTRUCTURE
    )


def _classify_mcc(failure: FailureInfo) -> FailureDisposition:
    status = str(failure.details.get("stage20b_status", ""))
    if status.startswith(("MINDTCT_FAILED_", "INVALID_XYT_")):
        return FailureDisposition.ALGORITHM
    if status.startswith("MCC_TEMPLATE_REFUSAL_"):
        # Stage 20B explicitly classified these three as translation defects,
        # not an SDK declining a real minutiae set.
        route_defects = {
            "invalid_raster_dimensions",
            "minutia_outside_mindtct_raster",
            "invalid_mindtct_direction",
        }
        return (
            FailureDisposition.INFRASTRUCTURE
            if failure.details.get("reason") in route_defects
            else FailureDisposition.ALGORITHM
        )
    if status == "MCC_MATCH_REFUSAL":
        return FailureDisposition.ALGORITHM
    if status == "MCC_INVALID_SCORE":
        # The certified Stage 20B adapter already turns an out-of-contract
        # vendor value into a no-score matcher outcome and preserves the
        # observed spelling in failure details.  Stage 21B must not reclassify
        # that frozen outcome as a host outage or manufacture a numeric score.
        return FailureDisposition.ALGORITHM
    return FailureDisposition.INFRASTRUCTURE


def _runtime_assets(
    adapter: FingerprintAlgorithmAdapter,
) -> tuple[RuntimeAssetIdentity, ...]:
    config = getattr(adapter, "config", None)
    paths: Mapping[str, Path] = {}
    provider = getattr(config, "runtime_assets", None)
    if callable(provider):
        paths = provider()
    elif getattr(config, "bridge_jar", None) is not None:
        paths = {"sourceafis_bridge_jar": Path(config.bridge_jar)}
    assets: list[RuntimeAssetIdentity] = []
    for role, value in sorted(paths.items()):
        path = Path(value)
        if not path.is_file():
            raise Stage21BPreflightError(f"runtime asset {role!r} is missing")
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1 << 20), b""):
                digest.update(block)
                size += len(block)
        assets.append(
            RuntimeAssetIdentity(role=str(role), sha256=digest.hexdigest(), size_bytes=size)
        )
    return tuple(assets)


def _mapping_file(path: Path) -> Mapping[str, Any]:
    try:
        if path.suffix.lower() == ".json":
            value = json.loads(path.read_text(encoding="utf-8"))
        else:
            value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise Stage21BPreflightError(f"cannot read adapter config {path}: {exc}") from exc
    if not isinstance(value, Mapping):
        raise Stage21BPreflightError(f"{path}: expected a mapping")
    return value


def _collect_digests(value: Any, found: set[str]) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if isinstance(item, str) and ("sha256" in str(key).lower() or _is_digest(item)):
                if _is_digest(item):
                    found.add(item.lower())
            _collect_digests(item, found)
    elif isinstance(value, list):
        for item in value:
            _collect_digests(item, found)
    elif isinstance(value, str) and _is_digest(value):
        found.add(value.lower())


def _is_digest(value: object) -> bool:
    text = str(value).strip().lower()
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text)


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
