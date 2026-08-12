"""The committed runtime policy, read rather than restated.

The policy file exists so a reviewer sees this route's choices in a diff. That
is only worth anything if the file and the code cannot disagree quietly, so this
module loads the file and checks it against
:mod:`fpbench.adapters.verifinger_java.identity` and :mod:`fpbench.experiments.verifinger_runtime_manifest`.

The direction of authority is deliberate and one-way. The **code** decides what
runs; the **file** is a statement about it. A policy that disagreed could never
change a comparison — it can only fail this check, which is what a contract test
asserts on every CI run, with no SDK, no licence and no JVM in sight
(spec section 37).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from fpbench.core.serialization import stable_hash
from fpbench.core.verifinger_errors import VeriFingerError
from fpbench.adapters.verifinger_java import identity, runtime

__all__ = [
    "POLICY_ID",
    "POLICY_SCHEMA",
    "DEFAULT_POLICY_PATH",
    "VeriFingerRuntimePolicy",
    "read_runtime_policy",
    "require_policy_matches_source",
]

POLICY_ID = "stage11b_verifinger_runtime_policy_v1"
POLICY_SCHEMA = "verifinger_runtime_policy_v1"

DEFAULT_POLICY_PATH = Path("configs/verifinger/stage11b_verifinger_runtime_policy_v1.yaml")


@dataclass(frozen=True, slots=True)
class VeriFingerRuntimePolicy:
    """The committed policy document, loaded."""

    policy_id: str
    document: Mapping[str, Any]

    @property
    def fingerprint(self) -> str:
        return stable_hash(dict(self.document), length=64)

    def section(self, name: str) -> Mapping[str, Any]:
        value = self.document.get(name)
        if not isinstance(value, Mapping):
            raise VeriFingerError(f"the runtime policy has no {name!r} section")
        return value


def read_runtime_policy(path: Path) -> VeriFingerRuntimePolicy:
    """Load the policy, refusing anything that is not this document.

    Raises:
        VeriFingerError: the file is missing, is not a mapping, or is not this
            schema and id.
    """
    location = Path(path)
    if not location.is_file():
        raise VeriFingerError(f"the VeriFinger runtime policy is missing: {location.name}")
    document = yaml.safe_load(location.read_text(encoding="utf-8")) or {}
    if not isinstance(document, Mapping):
        raise VeriFingerError(f"{location.name}: expected a mapping at the top level")
    if str(document.get("schema")) != POLICY_SCHEMA:
        raise VeriFingerError(f"{location.name} is not a {POLICY_SCHEMA} document")
    if str(document.get("policy_id")) != POLICY_ID:
        raise VeriFingerError(
            f"{location.name} declares policy {document.get('policy_id')!r}, "
            f"expected {POLICY_ID!r}"
        )
    return VeriFingerRuntimePolicy(policy_id=POLICY_ID, document=dict(document))


def require_policy_matches_source(policy: VeriFingerRuntimePolicy) -> None:
    """Every claim the policy makes is one this source actually enforces.

    Raises:
        VeriFingerError: any of them is not, listing each difference. A single
            wrong value fails the whole check: a policy that is right about nine
            things and wrong about the tenth is a policy nobody should trust.
    """
    differences: list[str] = []

    algorithm = policy.section("algorithm")
    for key, expected in (
        ("id", identity.ALGORITHM_ID),
        ("adapter_id", identity.ADAPTER_ID),
        ("implementation_version", identity.IMPLEMENTATION_VERSION),
        ("vendor", identity.VENDOR),
        ("slot", identity.ALGORITHM_SLOT),
    ):
        if str(algorithm.get(key)) != expected:
            differences.append(f"algorithm.{key}={algorithm.get(key)!r} != {expected!r}")

    stage11a = policy.section("stage11a")
    for key, expected in (
        ("finalization_fingerprint", identity.STAGE_11A_FINALIZATION_FINGERPRINT),
        ("outcome", identity.STAGE_11A_OUTCOME),
        ("selected_candidate", identity.STAGE_11A_SELECTED_CANDIDATE),
    ):
        if str(stage11a.get(key)) != expected:
            differences.append(f"stage11a.{key}={stage11a.get(key)!r} != {expected!r}")

    execution = policy.section("execution")
    if str(execution.get("integration_mode")) != identity.INTEGRATION_MODE:
        differences.append(
            f"execution.integration_mode={execution.get('integration_mode')!r} "
            f"!= {identity.INTEGRATION_MODE!r}"
        )
    if int(execution.get("logical_extractions_per_comparison") or 0) != (
        identity.REQUIRED_EXTRACTION_COUNT
    ):
        differences.append(
            "execution.logical_extractions_per_comparison != "
            f"{identity.REQUIRED_EXTRACTION_COUNT}"
        )

    route = policy.section("route")
    configured = route.get("configured")
    if not isinstance(configured, Mapping) or str(
        configured.get("Fingers.MatchingSpeed")
    ) != identity.MATCHING_SPEED:
        differences.append(
            f"route.configured.Fingers.MatchingSpeed != {identity.MATCHING_SPEED!r}"
        )
    if int(route.get("official_sample_matching_threshold") or 0) != (
        identity.OFFICIAL_SAMPLE_MATCHING_THRESHOLD
    ):
        differences.append(
            "route.official_sample_matching_threshold != "
            f"{identity.OFFICIAL_SAMPLE_MATCHING_THRESHOLD}"
        )
    for key in ("decision_threshold_produced_by_fpbench", "decision_returned_to_fpbench"):
        if route.get(key) is not False:
            differences.append(f"route.{key} must be false")
    declared_defaults = route.get("expected_delivered_defaults")
    if not isinstance(declared_defaults, Mapping):
        differences.append("route.expected_delivered_defaults is missing")
    else:
        rendered = {str(k): str(v) for k, v in declared_defaults.items()}
        if rendered != dict(identity.EXPECTED_RUNTIME_DEFAULTS):
            differences.append(
                "route.expected_delivered_defaults is not the frozen profile"
            )

    inputs = policy.section("inputs")
    if int(inputs.get("required_effective_ppi") or 0) != (
        identity.REQUIRED_EFFECTIVE_PPI
    ):
        differences.append(
            f"inputs.required_effective_ppi != {identity.REQUIRED_EFFECTIVE_PPI}"
        )

    pairs = policy.section("pairs")
    for key, expected in (
        ("left", "reference"),
        ("right", "candidate"),
    ):
        if str(pairs.get(key)) != expected:
            differences.append(f"pairs.{key}={pairs.get(key)!r} != {expected!r}")
    for key in (
        "reversal_permitted",
        "maximum_of_both_orderings_permitted",
        "average_of_both_orderings_permitted",
        "path_sorting_permitted",
    ):
        if pairs.get(key) is not False:
            differences.append(f"pairs.{key} must be false")
    if pairs.get("self_independent_sides") is not True:
        differences.append("pairs.self_independent_sides must be true")

    score = policy.section("score")
    for key, expected in (
        ("direction", identity.SCORE_DIRECTION.value),
        ("native_score_type", identity.NATIVE_SCORE_TYPE),
        ("score_scale", identity.SCORE_SCALE),
        ("score_transformation_by_fpbench", identity.SCORE_TRANSFORMATION_BY_FPBENCH),
        ("serialization", identity.SCORE_SERIALIZATION),
    ):
        if str(score.get(key)) != expected:
            differences.append(f"score.{key}={score.get(key)!r} != {expected!r}")
    if tuple(str(item) for item in score.get("score_bearing_statuses") or ()) != (
        identity.SCORE_BEARING_STATUSES
    ):
        differences.append("score.score_bearing_statuses is not the frozen pair")
    for key in (
        "far_computed_by_fpbench",
        "normalized",
        "clamped",
        "calibrated",
        "failure_scored_as_zero",
    ):
        if score.get(key) is not False:
            differences.append(f"score.{key} must be false")

    closure = policy.section("runtime_closure")
    for key, expected in (
        ("native_libraries", len(runtime.NATIVE_LIBRARY_NAMES)),
        ("model_data_files", len(runtime.MODEL_DATA_FILES)),
        ("classpath_jars", len(runtime.CLASSPATH_JARS)),
        ("components", len(runtime.CLOSURE_PATHS)),
    ):
        if int(closure.get(key) or 0) != expected:
            differences.append(f"runtime_closure.{key}={closure.get(key)!r} != {expected}")

    declared_forbidden = tuple(
        str(item) for item in policy.document.get("forbidden_inputs") or ()
    )
    if declared_forbidden != identity.FORBIDDEN_INPUTS:
        differences.append("forbidden_inputs is not the frozen list")

    reporting = policy.section("reporting")
    for key in (
        "biometric_metrics",
        "score_statistics",
        "score_export",
        "threshold_produced",
        "calibration_performed",
        "algorithm_ranking",
    ):
        if reporting.get(key) is not False:
            differences.append(f"reporting.{key} must be false")
    if reporting.get("operational_summary") is not True:
        differences.append("reporting.operational_summary must be true")

    if differences:
        raise VeriFingerError(
            "the committed VeriFinger runtime policy does not describe what this "
            "source does: " + "; ".join(differences)
        )
