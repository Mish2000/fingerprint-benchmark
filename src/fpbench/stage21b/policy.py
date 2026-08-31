"""Strict loading of the frozen, score-independent execution policy."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import yaml

from fpbench.core.identifiers import validate_id
from fpbench.stage21b.errors import Stage21BPreflightError

_TOP_KEYS = {
    "schema_version",
    "policy_id",
    "roster_ref",
    "preparation_set_id",
    "preparation_profile_id",
    "execution_strategy",
    "concurrency",
    "orchestrator_algorithm_retries",
    "infrastructure_resume_allowed",
    "optimizations_enabled",
    "routes",
}
_ROUTE_KEYS = {"timeout_seconds", "failure_classifier", "algorithm_config"}
_FROZEN_ROUTE_VALUES = {
    "sourceafis_java_subprocess": (
        60.0,
        "sourceafis_certified_v1",
        "configs/algorithms/sourceafis_java_3_18_1.yaml",
    ),
    "nbis_mindtct_bozorth3_subprocess": (
        60.0,
        "nbis_certified_v1",
        "configs/algorithms/nbis_mindtct_bozorth3_5_0_0_v1.yaml",
    ),
    "flx_pytorch_subprocess": (
        480.0,
        "flx_certified_v1",
        "configs/algorithms/flx_deepprint_texminu_512_without_localization_v1.yaml",
    ),
    "verifinger_java_subprocess": (
        180.0,
        "verifinger_certified_v1",
        "configs/algorithms/verifinger_2025_2_1to1_v1.yaml",
    ),
    "nbis_mindtct_mcc_sdk_v2_subprocess": (
        300.0,
        "mcc_stage20b_certified_v1",
        "evidence/stage20b-mindtct-mcc-canonical500-raw/algorithm-identity.json",
    ),
    "nbis_mindtct_openafis_capacity_extended_subprocess": (
        120.0,
        "openafis_stage19b_certified_v1",
        "evidence/stage19b-openafis-capacity-extended/variant-identity.json",
    ),
}


@dataclass(frozen=True, slots=True)
class RoutePolicy:
    adapter_id: str
    timeout_seconds: float
    failure_classifier: str
    algorithm_config: Path


@dataclass(frozen=True, slots=True)
class ExecutionPolicy:
    policy_id: str
    roster_ref: Path
    preparation_set_id: str
    preparation_profile_id: str
    execution_strategy: str
    concurrency: int
    orchestrator_algorithm_retries: int
    infrastructure_resume_allowed: bool
    optimizations_enabled: bool
    routes: Mapping[str, RoutePolicy]

    def __post_init__(self) -> None:
        object.__setattr__(self, "routes", MappingProxyType(dict(self.routes)))

    def require_roster_adapters(self, adapter_ids: tuple[str, ...]) -> None:
        expected = set(adapter_ids)
        actual = set(self.routes)
        if actual != expected:
            raise Stage21BPreflightError(
                "the Stage 21B route policy does not exactly cover the Stage 21A "
                f"roster adapters (missing={sorted(expected-actual)}, "
                f"extra={sorted(actual-expected)})"
            )


def load_execution_policy(path: Path) -> ExecutionPolicy:
    path = Path(path)
    if not path.is_file():
        raise Stage21BPreflightError(f"Stage 21B execution policy is missing: {path}")
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(document, Mapping):
        raise Stage21BPreflightError(f"{path}: expected a mapping")
    _keys(document, _TOP_KEYS, str(path))
    if type(document.get("schema_version")) is not int or document["schema_version"] != 1:
        raise Stage21BPreflightError(f"{path}: schema_version must be integer 1")

    routes_value = document.get("routes")
    if not isinstance(routes_value, Mapping) or not routes_value:
        raise Stage21BPreflightError(f"{path}: routes must be a non-empty mapping")
    routes: dict[str, RoutePolicy] = {}
    for adapter_id, value in routes_value.items():
        validate_id(str(adapter_id))
        if not isinstance(value, Mapping):
            raise Stage21BPreflightError(f"{path}: route {adapter_id!r} is malformed")
        _keys(value, _ROUTE_KEYS, f"{path}: routes.{adapter_id}")
        timeout = value.get("timeout_seconds")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
            raise Stage21BPreflightError(
                f"{path}: routes.{adapter_id}.timeout_seconds must be positive"
            )
        classifier = _required_text(value, "failure_classifier", path)
        validate_id(classifier)
        config = Path(_required_text(value, "algorithm_config", path))
        routes[str(adapter_id)] = RoutePolicy(
            adapter_id=str(adapter_id),
            timeout_seconds=float(timeout),
            failure_classifier=classifier,
            algorithm_config=config,
        )

    observed = {
        adapter_id: (
            route.timeout_seconds,
            route.failure_classifier,
            route.algorithm_config.as_posix(),
        )
        for adapter_id, route in routes.items()
    }
    if observed != _FROZEN_ROUTE_VALUES:
        raise Stage21BPreflightError(
            "Stage 21B route timeouts/classifiers/config bindings changed"
        )

    policy_id = _required_text(document, "policy_id", path)
    strategy = _required_text(document, "execution_strategy", path)
    for value in (policy_id, strategy):
        validate_id(value)
    concurrency = document.get("concurrency")
    retries = document.get("orchestrator_algorithm_retries")
    if type(concurrency) is not int or concurrency != 1:
        raise Stage21BPreflightError(f"{path}: concurrency must remain integer 1")
    if type(retries) is not int or retries != 0:
        raise Stage21BPreflightError(
            f"{path}: orchestrator_algorithm_retries must remain integer 0"
        )
    resume = document.get("infrastructure_resume_allowed")
    optimized = document.get("optimizations_enabled")
    if resume is not True or optimized is not False:
        raise Stage21BPreflightError(
            f"{path}: infrastructure resume must be true and optimizations false"
        )
    return ExecutionPolicy(
        policy_id=policy_id,
        roster_ref=Path(_required_text(document, "roster_ref", path)),
        preparation_set_id=_required_text(document, "preparation_set_id", path),
        preparation_profile_id=_required_text(
            document, "preparation_profile_id", path
        ),
        execution_strategy=strategy,
        concurrency=concurrency,
        orchestrator_algorithm_retries=retries,
        infrastructure_resume_allowed=resume,
        optimizations_enabled=optimized,
        routes=routes,
    )


def _keys(value: Mapping[str, Any], expected: set[str], where: str) -> None:
    actual = set(value)
    if actual != expected:
        raise Stage21BPreflightError(
            f"{where}: keys are {sorted(actual)}, expected {sorted(expected)}"
        )


def _required_text(value: Mapping[str, Any], key: str, path: Path) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise Stage21BPreflightError(f"{path}: {key} must be a non-empty string")
    return item.strip()
