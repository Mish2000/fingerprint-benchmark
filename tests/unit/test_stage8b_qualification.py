"""Fifteen conjunctive gates, and what each kind of failure is called."""

from __future__ import annotations

import pytest

from fpbench.core.flx_models import FlxGate, FlxGateState, FlxOutcome
from fpbench.flx import identity
from fpbench.flx.qualification import (
    build_qualification_report,
    evaluate_gates,
    outcome_for,
)
from flxworld import (
    make_artifact_binding,
    make_determinism,
    make_offline,
    make_operational,
    make_probe,
    make_runtime_manifest,
    make_self_independence,
)

pytestmark = pytest.mark.stage8b_contract

NOW = "2026-08-05T12:00:00+03:00"


def _gates(**probe_changes):
    return evaluate_gates(
        binding=make_artifact_binding(),
        manifest=make_runtime_manifest(),
        probe=make_probe(**probe_changes),
    )


def _states(gates):
    return {result.gate: result.state for result in gates}


def test_a_clean_probe_passes_every_gate() -> None:
    gates = _gates()

    assert len(gates) == len(FlxGate)
    assert tuple(result.gate for result in gates) == tuple(FlxGate)
    assert all(result.state is FlxGateState.PASSED for result in gates)
    assert outcome_for(gates) is FlxOutcome.RAW_SCORE_EXECUTION_READY


def test_the_report_over_a_clean_probe_opens_stage_8c() -> None:
    report = build_qualification_report(
        binding=make_artifact_binding(),
        manifest=make_runtime_manifest(),
        probe=make_probe(),
        qualified_utc=NOW,
    )

    assert report.outcome is FlxOutcome.RAW_SCORE_EXECUTION_READY
    assert report.opens_stage_8c is True
    assert report.permits_decisions is False
    assert report.weights_license_status == "unresolved"


def test_a_wrong_checkpoint_is_an_artifact_mismatch() -> None:
    gates = evaluate_gates(
        binding=make_artifact_binding(checkpoint_sha256="b" * 64),
        manifest=make_runtime_manifest(),
        probe=make_probe(),
    )

    assert _states(gates)[FlxGate.ARTIFACT_IDENTITY] is FlxGateState.FAILED
    assert outcome_for(gates) is FlxOutcome.ARTIFACT_MISMATCH


def test_a_multi_threaded_runtime_blocks_the_stage() -> None:
    gates = evaluate_gates(
        binding=make_artifact_binding(),
        manifest=make_runtime_manifest(torch_num_threads=8),
        probe=make_probe(),
    )

    assert _states(gates)[FlxGate.RUNTIME_IDENTITY] is FlxGateState.FAILED
    assert outcome_for(gates) is FlxOutcome.RUNTIME_BLOCKED


def test_an_unloadable_checkpoint_blocks_the_stage() -> None:
    gates = _gates(checkpoint_loaded=False, model_in_eval_mode=False, gradients_disabled=False)

    assert _states(gates)[FlxGate.CHECKPOINT_LOADED] is FlxGateState.FAILED
    assert outcome_for(gates) is FlxOutcome.RUNTIME_BLOCKED


def test_a_state_dict_key_mismatch_fails_the_contract() -> None:
    gates = _gates(unexpected_state_dict_keys=("scheduler.step",))

    assert _states(gates)[FlxGate.STRICT_KEY_VALIDATION] is FlxGateState.FAILED
    assert outcome_for(gates) is FlxOutcome.CONTRACT_FAILED


def test_nondeterminism_fails_the_contract() -> None:
    gates = _gates(determinism=make_determinism(repeated_extraction_bitwise_equal=False))

    assert _states(gates)[FlxGate.DETERMINISM] is FlxGateState.FAILED
    assert outcome_for(gates) is FlxOutcome.CONTRACT_FAILED


def test_an_asymmetric_comparison_fails_the_contract() -> None:
    gates = _gates(determinism=make_determinism(input_order_symmetric=False))

    assert _states(gates)[FlxGate.DETERMINISM] is FlxGateState.FAILED


def test_restart_drift_fails_the_contract() -> None:
    gates = _gates(determinism=make_determinism(process_restart_score_equal=False))

    assert _states(gates)[FlxGate.RESTART] is FlxGateState.FAILED
    assert outcome_for(gates) is FlxOutcome.CONTRACT_FAILED


def test_a_self_contract_with_one_extraction_fails() -> None:
    # Spec section 26: SELF extraction call count of one is a failure, not a
    # cheaper way to get the same answer.
    gates = _gates(self_independence=make_self_independence(extract_call_count=1))

    assert _states(gates)[FlxGate.SELF_INDEPENDENCE] is FlxGateState.FAILED


def test_an_observed_cache_lookup_fails_the_self_gate() -> None:
    gates = _gates(self_independence=make_self_independence(cache_lookups_observed=1))

    assert _states(gates)[FlxGate.SELF_INDEPENDENCE] is FlxGateState.FAILED


def test_a_network_attempt_fails_offline_isolation() -> None:
    gates = _gates(offline=make_offline(network_attempts_observed=1))

    assert _states(gates)[FlxGate.OFFLINE_ISOLATION] is FlxGateState.FAILED


def test_exceeding_the_frozen_limits_is_operationally_infeasible() -> None:
    gates = _gates(operational=make_operational(within_limits=False))

    assert _states(gates)[FlxGate.OPERATIONAL] is FlxGateState.FAILED
    assert outcome_for(gates) is FlxOutcome.OPERATIONALLY_INFEASIBLE


def test_an_unrun_check_is_not_executed_rather_than_failed() -> None:
    # Stage 8A's rule, kept: an unexecuted probe is not an observed fault.
    gates = _gates(
        self_independence=make_self_independence(
            tested=False,
            preprocess_call_count=None,
            extract_call_count=None,
            distinct_representation_objects=None,
            representations_equal=None,
            cache_lookups_observed=None,
        ),
        determinism=make_determinism(
            tested=False,
            repeated_extraction_bitwise_equal=None,
            repeated_comparison_bitwise_equal=None,
            process_restart_representation_equal=None,
            process_restart_score_equal=None,
            process_restart_runtime_metadata_equal=None,
            input_order_symmetric=None,
        ),
        offline=make_offline(
            tested=False,
            dns_blocked=None,
            socket_creation_blocked=None,
            network_attempts_observed=None,
        ),
        operational=make_operational(
            measured=False,
            worker_startup_seconds=None,
            model_load_seconds=None,
            preprocess_seconds=None,
            extract_seconds=None,
            compare_seconds=None,
            peak_ram_bytes=None,
            artifact_disk_bytes=None,
            projected_12000_extractions_seconds=None,
            projected_6000_comparisons_seconds=None,
            within_limits=None,
        ),
    )
    states = _states(gates)

    for gate in (
        FlxGate.SELF_INDEPENDENCE,
        FlxGate.DETERMINISM,
        FlxGate.RESTART,
        FlxGate.OFFLINE_ISOLATION,
        FlxGate.OPERATIONAL,
    ):
        assert states[gate] is FlxGateState.NOT_EXECUTED, gate
        result = next(item for item in gates if item.gate is gate)
        assert result.failure_codes == ()
    assert outcome_for(gates) is not FlxOutcome.RAW_SCORE_EXECUTION_READY


def test_an_unrun_check_does_not_open_stage_8c() -> None:
    report = build_qualification_report(
        binding=make_artifact_binding(),
        manifest=make_runtime_manifest(),
        probe=make_probe(
            offline=make_offline(
                tested=False,
                dns_blocked=None,
                socket_creation_blocked=None,
                network_attempts_observed=None,
            )
        ),
        qualified_utc=NOW,
    )

    assert report.opens_stage_8c is False
    assert report.outcome is FlxOutcome.CONTRACT_FAILED


def test_the_licence_gate_passes_without_claiming_the_licence_is_resolved() -> None:
    licence = next(result for result in _gates() if result.gate is FlxGate.LICENSE_STATUS)

    assert licence.state is FlxGateState.PASSED
    assert "unresolved" in licence.detail
    assert "0068" in licence.detail


def test_the_batch_comparison_is_recorded_as_not_applicable() -> None:
    # Spec section 17.6: no batch-of-one API exists on this artifact, and none
    # is invented (docs/adr/0070).
    probe = make_probe()

    assert probe.determinism.single_vs_batch_state is FlxGateState.NOT_APPLICABLE
    assert probe.determinism.single_vs_batch_bitwise_equal is None


def test_every_gate_result_explains_itself() -> None:
    for result in _gates():
        assert result.detail
        assert len(result.detail) > 20, result.gate
