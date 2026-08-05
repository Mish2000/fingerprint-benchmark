"""The dynamic qualification, run for real and judged by the frozen gates."""

from __future__ import annotations

from pathlib import Path

import pytest

from fpbench.core.flx_errors import FlxArtifactError
from fpbench.core.flx_models import FlxGate, FlxGateState, FlxOutcome
from fpbench.flx import identity
from fpbench.flx.artifacts import (
    FlxRuntimeBundle,
    build_artifact_binding,
    verify_bundle_artifacts,
)
from fpbench.flx.lock import load_runtime_lock
from fpbench.flx.policy import load_runtime_policy
from fpbench.flx.probe import ProbeInputs, run_runtime_probe
from fpbench.flx.qualification import build_qualification_report
from fpbench.flx.runtime import build_runtime_manifest
from fpbench.flx.worker import FlxWorkerSession

pytestmark = pytest.mark.flx_runtime

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
NOW = "2026-08-05T12:00:00+00:00"
STAGE8A_MANIFEST_FINGERPRINT = (
    "46b36b0266a3173f22289ce9c2262cc0812cb148d8e1c7b6a3da909a1d6927f3"
)


@pytest.fixture(scope="module")
def probed():
    bundle = FlxRuntimeBundle.from_environment()
    try:
        verify_bundle_artifacts(bundle)
    except FlxArtifactError as exc:
        pytest.skip(f"no verified flx runtime bundle: {exc}")
    lock = load_runtime_lock(REPOSITORY_ROOT / "configs/flx/flx_runtime_lock_v1.txt")
    policy = load_runtime_policy(
        REPOSITORY_ROOT / "configs/flx/stage8b_flx_runtime_policy_v1.yaml"
    )
    binding = build_artifact_binding(
        bundle,
        stage8a_manifest_fingerprint=STAGE8A_MANIFEST_FINGERPRINT,
        inspected_utc=NOW,
    )
    with FlxWorkerSession(
        bundle, startup_deadline_seconds=float(policy.max_worker_startup_seconds)
    ) as session:
        report = session.validate_runtime(
            deadline_seconds=float(policy.max_worker_startup_seconds)
        )
    manifest = build_runtime_manifest(report, lock=lock, created_utc=NOW)
    probe = run_runtime_probe(
        ProbeInputs(
            bundle=bundle,
            policy=policy,
            artifact_binding_fingerprint=binding.fingerprint,
            runtime_manifest_fingerprint=manifest.fingerprint,
            created_utc=NOW,
        )
    )
    return binding, manifest, probe, policy


def test_the_probe_ran_every_fixture_and_published_only_hashes(probed) -> None:
    _, _, probe, _ = probed

    assert len(probe.fixture_ids) >= 4
    assert set(probe.representation_hashes) == set(probe.fixture_ids)
    for digest in probe.representation_hashes.values():
        assert len(digest) == 64
    for digest in probe.score_hashes.values():
        assert len(digest) == 64


def test_the_probe_read_no_biometric_input_or_prior_result(probed) -> None:
    _, _, probe, _ = probed

    assert probe.biometric_inputs_read is False
    assert probe.prior_results_read is False


def test_the_checkpoint_loaded_strictly_with_no_key_left_over(probed) -> None:
    _, _, probe, _ = probed

    assert probe.checkpoint_loaded is True
    assert probe.model_in_eval_mode is True
    assert probe.gradients_disabled is True
    assert probe.missing_state_dict_keys == ()
    assert probe.unexpected_state_dict_keys == ()


def test_self_ran_two_preprocess_and_two_independent_extractions(probed) -> None:
    _, _, probe, _ = probed
    independence = probe.self_independence

    assert independence.tested is True
    assert independence.preprocess_call_count == 2
    assert independence.extract_call_count == 2
    assert independence.distinct_representation_objects is True
    assert independence.cache_lookups_observed == 0
    # Equality between the two sides is expected, and is not the thing tested.
    assert independence.representations_equal is True


def test_the_route_is_bitwise_deterministic_at_the_frozen_tolerance(probed) -> None:
    _, _, probe, _ = probed
    determinism = probe.determinism

    assert determinism.numeric_tolerance == identity.NUMERIC_TOLERANCE == "0"
    assert determinism.repeated_extraction_bitwise_equal is True
    assert determinism.repeated_comparison_bitwise_equal is True
    assert determinism.input_order_symmetric is True


def test_a_fresh_process_reproduces_the_representation_score_and_metadata(probed) -> None:
    _, _, probe, _ = probed
    determinism = probe.determinism

    assert determinism.process_restart_representation_equal is True
    assert determinism.process_restart_score_equal is True
    assert determinism.process_restart_runtime_metadata_equal is True


def test_the_batch_comparison_is_not_applicable_rather_than_invented(probed) -> None:
    _, _, probe, _ = probed

    assert probe.determinism.single_vs_batch_state is FlxGateState.NOT_APPLICABLE
    assert probe.determinism.single_vs_batch_bitwise_equal is None


def test_nothing_attempted_to_reach_the_network(probed) -> None:
    _, _, probe, _ = probed

    assert probe.offline.tested is True
    assert probe.offline.network_attempts_observed == 0
    assert probe.offline.dns_blocked is True
    assert probe.offline.socket_creation_blocked is True


def test_the_projections_fit_inside_the_limits_frozen_beforehand(probed) -> None:
    from decimal import Decimal

    _, _, probe, policy = probed
    operational = probe.operational

    assert operational.measured is True
    assert operational.policy_fingerprint == policy.fingerprint
    assert Decimal(operational.projected_12000_extractions_seconds) <= Decimal(
        policy.max_projected_12000_extractions_seconds
    )
    assert Decimal(operational.projected_6000_comparisons_seconds) <= Decimal(
        policy.max_projected_6000_comparisons_seconds
    )
    assert operational.peak_ram_bytes <= policy.max_peak_ram_bytes
    assert operational.artifact_disk_bytes <= policy.max_artifact_disk_bytes
    assert operational.within_limits is True


def test_the_gates_over_the_real_probe_open_stage_8c(probed) -> None:
    binding, manifest, probe, _ = probed

    report = build_qualification_report(
        binding=binding, manifest=manifest, probe=probe, qualified_utc=NOW
    )

    failures = [
        result.gate.value for result in report.gates if result.state is not FlxGateState.PASSED
    ]
    assert failures == []
    assert report.outcome is FlxOutcome.RAW_SCORE_EXECUTION_READY
    assert report.opens_stage_8c is True
    assert report.permits_decisions is False
    assert len(report.gates) == len(FlxGate)


def test_readiness_still_does_not_resolve_the_licence(probed) -> None:
    binding, manifest, probe, _ = probed

    report = build_qualification_report(
        binding=binding, manifest=manifest, probe=probe, qualified_utc=NOW
    )

    assert report.weights_license_status == "unresolved"
    assert report.redistribution_allowed == "not_established"
    assert report.publication_permission == "not_established"
