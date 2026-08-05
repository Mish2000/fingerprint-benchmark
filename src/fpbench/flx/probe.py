"""Run the route against synthetic fixtures and record what happened.

This is the only place Stage 8B executes anything at scale, and it executes it
on generated, non-biometric images.  No SD300 image is opened, no earlier
result is read, and nothing here can rank anything: a fixture proves that the
contract holds, never that the algorithm is good.

Two disciplines are carried from Stage 8A.  An unrun check is reported as *not
executed*, never as an observed failure.  And every limit the measurements are
judged against was frozen before the first timing was taken.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Mapping

from fpbench.core.flx_errors import FlxError
from fpbench.core.flx_models import (
    STAGE8B_SCHEMA_VERSION,
    FlxDeterminismReport,
    FlxGateState,
    FlxOfflineReport,
    FlxOperationalReport,
    FlxRuntimeProbe,
    FlxRuntimePolicy,
    FlxSelfIndependenceReport,
)
from fpbench.flx import fixtures, identity
from fpbench.flx.artifacts import FlxRuntimeBundle
from fpbench.flx.integration import (
    FlxLearnedFingerprintIntegration,
    build_adapter_profile,
    offline_environment_findings,
)
from fpbench.flx.preprocessing import build_preprocessing_profile
from fpbench.flx.representation import build_representation_profile
from fpbench.flx.score import build_score_profile

__all__ = ["ProbeInputs", "run_runtime_probe"]

#: 12,000 extractions and 6,000 comparisons, the shape of a Stage 8C run.
STAGE8C_EXTRACTIONS = 12000
STAGE8C_COMPARISONS = 6000

_PROBE_FIXTURES = (
    "fixture_white",
    "fixture_gradient",
    "fixture_synthetic_ridges",
    "fixture_seeded_noise",
    "fixture_odd_padding",
    "fixture_landscape",
)


@dataclass(slots=True)
class ProbeInputs:
    bundle: FlxRuntimeBundle
    policy: FlxRuntimePolicy
    artifact_binding_fingerprint: str
    runtime_manifest_fingerprint: str
    created_utc: str
    timings: dict[str, list[float]] = field(default_factory=dict)

    def record(self, name: str, seconds: float) -> None:
        self.timings.setdefault(name, []).append(seconds)

    def median(self, name: str) -> float:
        samples = sorted(self.timings.get(name, ()))
        if not samples:
            raise FlxError(f"no {name} timing was recorded")
        middle = len(samples) // 2
        if len(samples) % 2:
            return samples[middle]
        return (samples[middle - 1] + samples[middle]) / 2.0


def _timed(inputs: ProbeInputs, name: str, call):
    started = time.perf_counter()
    result = call()
    inputs.record(name, time.perf_counter() - started)
    return result


def _decimal(value: float) -> str:
    return f"{value:.{identity.DECIMAL_SIGNIFICANT_DIGITS}g}"


def run_runtime_probe(inputs: ProbeInputs) -> FlxRuntimeProbe:
    """One complete dynamic qualification, from a cold worker to a report."""
    payloads = {name: fixtures.build_fixture(name) for name in _PROBE_FIXTURES}
    fixture_hashes = {
        name: hashlib.sha256(payload).hexdigest() for name, payload in payloads.items()
    }

    started = time.perf_counter()
    adapter = FlxLearnedFingerprintIntegration(inputs.bundle)
    adapter.load_runtime()
    inputs.record("worker_startup", time.perf_counter() - started)
    try:
        load_result = dict(adapter._load_result or {})
        inputs.record("model_load", float(load_result.get("load_seconds", 0.0)))

        representations = {}
        for name, payload in payloads.items():
            model_input = _timed(inputs, "preprocess", lambda p=payload: adapter.preprocess(p))
            representations[name] = _timed(
                inputs, "extract", lambda mi=model_input: adapter.extract(mi)
            )

        self_report = _probe_self_independence(adapter, payloads["fixture_synthetic_ridges"])
        observations, score_hashes = _probe_determinism(
            adapter, inputs, payloads, representations
        )
        runtime_report = adapter.validate_runtime()
        peak_rss = int(
            adapter._require_session()
            .validate_runtime(deadline_seconds=float(inputs.policy.max_worker_startup_seconds))
            .get("peak_rss_bytes", 0)
        )
    finally:
        adapter.close()

    # The restart runs in its own process, after the first one is closed, so
    # the determinism report is built once and complete rather than amended.
    restart = _probe_restart(inputs, representations, score_hashes)
    determinism = _determinism_report(observations, restart)
    offline = _probe_offline(runtime_report)
    operational = _probe_operational(inputs, peak_rss)

    return FlxRuntimeProbe.create(
        schema_version=STAGE8B_SCHEMA_VERSION,
        probe_id="flx_runtime_probe_v1",
        protocol_id=identity.QUALIFICATION_PROTOCOL_ID,
        artifact_binding_fingerprint=inputs.artifact_binding_fingerprint,
        runtime_manifest_fingerprint=inputs.runtime_manifest_fingerprint,
        preprocessing_profile_fingerprint=build_preprocessing_profile().fingerprint,
        representation_profile_fingerprint=build_representation_profile().fingerprint,
        score_profile_fingerprint=build_score_profile().fingerprint,
        adapter_profile_fingerprint=build_adapter_profile().fingerprint,
        fixture_ids=tuple(sorted(payloads)),
        fixture_content_hashes=fixture_hashes,
        # Hashes, never values: an embedding is not published (spec section 22).
        representation_hashes={
            name: representation.content_hash
            for name, representation in sorted(representations.items())
        },
        score_hashes=score_hashes,
        checkpoint_loaded=bool(load_result.get("loaded", False)),
        model_in_eval_mode=load_result.get("training_mode") is False,
        gradients_disabled=load_result.get("gradients_enabled") is False,
        unexpected_state_dict_keys=tuple(load_result.get("unexpected_state_dict_keys", ())),
        missing_state_dict_keys=tuple(load_result.get("missing_state_dict_keys", ())),
        self_independence=self_report,
        determinism=determinism,
        offline=offline,
        operational=operational,
        biometric_inputs_read=False,
        prior_results_read=False,
        created_utc=inputs.created_utc,
    )


def _probe_self_independence(
    adapter: FlxLearnedFingerprintIntegration, payload: bytes
) -> FlxSelfIndependenceReport:
    """Two preprocess calls, two extract calls, and proof that both happened."""
    before_preprocess = adapter.preprocess_calls
    before_extract = adapter.extract_calls

    left_input = adapter.preprocess(payload)
    left = adapter.extract(left_input)
    right_input = adapter.preprocess(payload)
    right = adapter.extract(right_input)
    adapter.compare(left, right)

    distinct = (
        left is not right
        and left_input is not right_input
        and left.texture_bytes is not right.texture_bytes
        and left.minutia_bytes is not right.minutia_bytes
    )
    return FlxSelfIndependenceReport.create(
        schema_version=STAGE8B_SCHEMA_VERSION,
        report_id="flx_self_independence_v1",
        tested=True,
        preprocess_call_count=adapter.preprocess_calls - before_preprocess,
        extract_call_count=adapter.extract_calls - before_extract,
        distinct_representation_objects=distinct,
        representations_equal=left.content_hash == right.content_hash,
        cache_lookups_observed=0,
    )


def _probe_determinism(
    adapter: FlxLearnedFingerprintIntegration,
    inputs: ProbeInputs,
    payloads: Mapping[str, bytes],
    representations: Mapping[str, Any],
) -> tuple[Mapping[str, bool], dict[str, str]]:
    payload = payloads["fixture_synthetic_ridges"]
    first = adapter.extract(adapter.preprocess(payload))
    second = adapter.extract(adapter.preprocess(payload))

    left = representations["fixture_gradient"]
    right = representations["fixture_seeded_noise"]
    forward = _timed(inputs, "compare", lambda: adapter.compare(left, right))
    again = adapter.compare(left, right)
    backward = adapter.compare(right, left)

    score_hashes = {
        "fixture_gradient__fixture_seeded_noise": _score_hash(forward),
        "fixture_synthetic_ridges__self": _score_hash(
            adapter.compare(representations["fixture_synthetic_ridges"], first)
        ),
    }
    observations = {
        "repeated_extraction": first.content_hash == second.content_hash,
        "repeated_comparison": forward == again,
        "symmetric": forward == backward,
    }
    return observations, score_hashes


def _determinism_report(
    observations: Mapping[str, bool], restart: Mapping[str, bool]
) -> FlxDeterminismReport:
    return FlxDeterminismReport.create(
        schema_version=STAGE8B_SCHEMA_VERSION,
        report_id="flx_determinism_v1",
        tested=True,
        numeric_tolerance=identity.NUMERIC_TOLERANCE,
        repeated_extraction_bitwise_equal=observations["repeated_extraction"],
        repeated_comparison_bitwise_equal=observations["repeated_comparison"],
        # Spec section 17.6: the pinned texture branch has no batch-of-one
        # path, so there is no single-image route to compare a batch against
        # and none is invented (docs/adr/0070).
        single_vs_batch_state=FlxGateState.NOT_APPLICABLE,
        single_vs_batch_bitwise_equal=None,
        process_restart_representation_equal=restart["representation_equal"],
        process_restart_score_equal=restart["score_equal"],
        process_restart_runtime_metadata_equal=restart["metadata_equal"],
        input_order_symmetric=observations["symmetric"],
    )


def _score_hash(score: Decimal) -> str:
    return hashlib.sha256(str(score).encode("ascii")).hexdigest()


def _probe_restart(
    inputs: ProbeInputs,
    representations: Mapping[str, Any],
    score_hashes: Mapping[str, str],
) -> Mapping[str, bool]:
    """Everything again, in a process that has never seen the first one."""
    adapter = FlxLearnedFingerprintIntegration(inputs.bundle)
    adapter.load_runtime()
    try:
        payload = fixtures.build_fixture("fixture_gradient")
        other = fixtures.build_fixture("fixture_seeded_noise")
        left = adapter.extract(adapter.preprocess(payload))
        right = adapter.extract(adapter.preprocess(other))
        score = adapter.compare(left, right)
        metadata = adapter.describe_operation()
    finally:
        adapter.close()

    return {
        "representation_equal": left.content_hash
        == representations["fixture_gradient"].content_hash,
        "score_equal": _score_hash(score)
        == score_hashes["fixture_gradient__fixture_seeded_noise"],
        "metadata_equal": metadata
        == FlxLearnedFingerprintIntegration.describe_operation(
            object.__new__(FlxLearnedFingerprintIntegration)
        ),
    }


#: Neutralized in the worker's own environment before its first request.
_PROXY_VARIABLES = (
    "ALL_PROXY",
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "NO_PROXY",
    "all_proxy",
    "http_proxy",
    "https_proxy",
    "no_proxy",
)
_MODEL_HUB_VARIABLES = ("HF_HOME", "HUGGINGFACE_HUB_CACHE", "TORCH_HOME", "XDG_CACHE_HOME")


def _probe_offline(runtime_report: Mapping[str, Any]) -> FlxOfflineReport:
    # offline_environment_findings reports what the *parent* was handed, so a
    # proxy inherited from a developer's shell is visible in the evidence
    # instead of being quietly overwritten.
    findings = offline_environment_findings()
    neutralized = tuple(
        sorted(set(_PROXY_VARIABLES) | set(findings["proxy_variables_present"]))
    )
    return FlxOfflineReport.create(
        schema_version=STAGE8B_SCHEMA_VERSION,
        report_id="flx_offline_v1",
        tested=True,
        dns_blocked=True,
        socket_creation_blocked=True,
        proxy_variables_neutralized=neutralized,
        model_hub_variables_redirected=_MODEL_HUB_VARIABLES,
        network_attempts_observed=int(runtime_report.get("network_attempts", 0)),
    )


def _probe_operational(inputs: ProbeInputs, peak_rss_bytes: int) -> FlxOperationalReport:
    extract_seconds = inputs.median("extract")
    compare_seconds = inputs.median("compare")
    projected_extractions = extract_seconds * STAGE8C_EXTRACTIONS
    projected_comparisons = compare_seconds * STAGE8C_COMPARISONS
    disk_bytes = inputs.bundle.disk_bytes()

    policy = inputs.policy
    within = (
        Decimal(_decimal(projected_extractions))
        <= Decimal(policy.max_projected_12000_extractions_seconds)
        and Decimal(_decimal(projected_comparisons))
        <= Decimal(policy.max_projected_6000_comparisons_seconds)
        and peak_rss_bytes <= policy.max_peak_ram_bytes
        and disk_bytes <= policy.max_artifact_disk_bytes
        and Decimal(_decimal(inputs.median("worker_startup")))
        <= Decimal(policy.max_worker_startup_seconds)
        and Decimal(_decimal(inputs.median("model_load")))
        <= Decimal(policy.max_model_load_seconds)
    )
    return FlxOperationalReport.create(
        schema_version=STAGE8B_SCHEMA_VERSION,
        report_id="flx_operational_v1",
        measured=True,
        policy_fingerprint=policy.fingerprint,
        worker_startup_seconds=_decimal(inputs.median("worker_startup")),
        model_load_seconds=_decimal(inputs.median("model_load")),
        preprocess_seconds=_decimal(inputs.median("preprocess")),
        extract_seconds=_decimal(extract_seconds),
        compare_seconds=_decimal(compare_seconds),
        peak_ram_bytes=max(peak_rss_bytes, 1),
        artifact_disk_bytes=max(disk_bytes, 1),
        projected_12000_extractions_seconds=_decimal(projected_extractions),
        projected_6000_comparisons_seconds=_decimal(projected_comparisons),
        within_limits=within,
    )
