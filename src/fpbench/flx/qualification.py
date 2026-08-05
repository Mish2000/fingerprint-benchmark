"""Fifteen gates, applied to one probe, producing one outcome.

Every gate is conjunctive: `FLX_RAW_SCORE_EXECUTION_READY` holds exactly when
all fifteen passed, and the record type refuses any other combination.

The distinction Stage 8A insisted on is kept.  A check that did not run is
`not_executed`, not `failed`; a comparison that has no meaning on this artifact
is `not_applicable`, not `passed`.  Neither of them opens Stage 8C, and neither
of them is written down as a fault the artifact does not have.
"""

from __future__ import annotations

from typing import Mapping

from fpbench.core.flx_models import (
    STAGE8B_SCHEMA_VERSION,
    FlxArtifactBinding,
    FlxGate,
    FlxGateResult,
    FlxGateState,
    FlxOutcome,
    FlxQualificationReport,
    FlxRuntimeManifest,
    FlxRuntimeProbe,
)
from fpbench.flx import identity

__all__ = ["evaluate_gates", "build_qualification_report", "outcome_for"]


def _result(
    gate: FlxGate, state: FlxGateState, detail: str, *codes: str
) -> FlxGateResult:
    return FlxGateResult.create(
        schema_version=STAGE8B_SCHEMA_VERSION,
        gate=gate,
        state=state,
        detail=detail,
        failure_codes=tuple(codes) if state is FlxGateState.FAILED else (),
    )


def _pass_or_fail(condition: bool, gate: FlxGate, passed: str, failed: str, code: str):
    if condition:
        return _result(gate, FlxGateState.PASSED, passed)
    return _result(gate, FlxGateState.FAILED, failed, code)


def evaluate_gates(
    *,
    binding: FlxArtifactBinding,
    manifest: FlxRuntimeManifest,
    probe: FlxRuntimeProbe,
) -> tuple[FlxGateResult, ...]:
    determinism = probe.determinism
    operational = probe.operational
    offline = probe.offline
    independence = probe.self_independence

    results = [
        _pass_or_fail(
            binding.source_archive_sha256 == identity.SOURCE_ARCHIVE_SHA256
            and binding.checkpoint_sha256 == identity.CHECKPOINT_SHA256
            and binding.checkpoint_size_bytes == identity.CHECKPOINT_SIZE_BYTES
            and binding.source_commit == identity.SOURCE_COMMIT,
            FlxGate.ARTIFACT_IDENTITY,
            "source archive, commit and checkpoint rehashed to the Stage 8A identities",
            "the artifacts on disk are not the ones Stage 8A identified",
            "FLX_ARTIFACT_MISMATCH",
        ),
        _pass_or_fail(
            manifest.runtime_profile_id == identity.RUNTIME_PROFILE_ID
            and manifest.device == "cpu"
            and not manifest.cuda_available
            and manifest.torch_num_threads == 1
            and manifest.torch_num_interop_threads == 1,
            FlxGate.RUNTIME_IDENTITY,
            "the installed runtime is the locked one, single-threaded, CPU only",
            "the runtime is not the pinned CPU profile",
            "FLX_RUNTIME_BLOCKED",
        ),
        _pass_or_fail(
            probe.checkpoint_loaded,
            FlxGate.CHECKPOINT_LOADED,
            "the checkpoint loaded as pure tensors under weights_only",
            "the checkpoint did not load safely",
            "FLX_CHECKPOINT_NOT_LOADED",
        ),
        _pass_or_fail(
            binding.checkpoint_variant == identity.CHECKPOINT_VARIANT,
            FlxGate.MODEL_VARIANT,
            f"the checkpoint identifies {identity.CHECKPOINT_VARIANT}",
            "the checkpoint is a different variant",
            "FLX_CHECKPOINT_VARIANT_MISMATCH",
        ),
        _pass_or_fail(
            not probe.missing_state_dict_keys and not probe.unexpected_state_dict_keys,
            FlxGate.STRICT_KEY_VALIDATION,
            "strict state-dict loading accepted every key with none left over",
            f"state dict mismatch: missing={list(probe.missing_state_dict_keys)} "
            f"unexpected={list(probe.unexpected_state_dict_keys)}",
            "FLX_STATE_DICT_KEY_MISMATCH",
        ),
        _pass_or_fail(
            bool(probe.fixture_ids) and len(probe.fixture_content_hashes) == len(probe.fixture_ids),
            FlxGate.PREPROCESSING_CONTRACT,
            f"the declared transform held on {len(probe.fixture_ids)} synthetic fixtures",
            "the transform contract was not established on every fixture",
            "FLX_PREPROCESSING_CONTRACT_FAILED",
        ),
        _pass_or_fail(
            len(probe.representation_hashes) == len(probe.fixture_ids)
            and probe.model_in_eval_mode
            and probe.gradients_disabled,
            FlxGate.REPRESENTATION_CONTRACT,
            "every fixture produced a finite, normalized 256+256 representation "
            "from a model in eval mode with gradients disabled",
            "the representation contract did not hold",
            "FLX_REPRESENTATION_CONTRACT_FAILED",
        ),
        _pass_or_fail(
            bool(probe.score_hashes),
            FlxGate.SCORE_CONTRACT,
            "raw scores are finite Decimals inside the nominal bounds plus the "
            "fingerprinted symmetric tolerance, with no clamp or threshold",
            "the score contract did not hold",
            "FLX_SCORE_CONTRACT_FAILED",
        ),
    ]

    if not independence.tested:
        results.append(
            _result(
                FlxGate.SELF_INDEPENDENCE,
                FlxGateState.NOT_EXECUTED,
                "the SELF contract was not exercised",
            )
        )
    else:
        results.append(
            _pass_or_fail(
                independence.preprocess_call_count == 2
                and independence.extract_call_count == 2
                and bool(independence.distinct_representation_objects)
                and independence.representation_cache_capability_present is False,
                FlxGate.SELF_INDEPENDENCE,
                "SELF ran two preprocess calls and two independent extractions, "
                "returning distinct objects through an adapter with no "
                "representation-cache capability",
                f"SELF made {independence.preprocess_call_count} preprocess and "
                f"{independence.extract_call_count} extract calls",
                "FLX_SELF_NOT_INDEPENDENT",
            )
        )

    if not determinism.tested:
        results.append(
            _result(FlxGate.DETERMINISM, FlxGateState.NOT_EXECUTED, "no determinism probe ran")
        )
        results.append(
            _result(FlxGate.RESTART, FlxGateState.NOT_EXECUTED, "no restart probe ran")
        )
    else:
        results.append(
            _pass_or_fail(
                determinism.numeric_tolerance == identity.NUMERIC_TOLERANCE
                and bool(determinism.repeated_extraction_bitwise_equal)
                and bool(determinism.repeated_comparison_bitwise_equal)
                and bool(determinism.batch_context_texture_bitwise_equal)
                and bool(determinism.batch_context_minutia_bitwise_equal)
                and bool(determinism.input_order_symmetric),
                FlxGate.DETERMINISM,
                "repeated extraction, repeated comparison, input order, and all "
                "five legal ADR 0070 batch contexts in both branches are bitwise equal "
                f"at tolerance {identity.NUMERIC_TOLERANCE}",
                "the route is not bitwise deterministic at the frozen tolerance",
                "FLX_NONDETERMINISTIC",
            )
        )
        results.append(
            _pass_or_fail(
                bool(determinism.process_restart_representation_equal)
                and bool(determinism.process_restart_score_equal)
                and bool(determinism.process_restart_runtime_metadata_equal),
                FlxGate.RESTART,
                "a fresh process reproduced the representation, the score and the metadata",
                "a restarted process produced different results",
                "FLX_RESTART_DRIFT",
            )
        )

    if not offline.tested:
        results.append(
            _result(
                FlxGate.OFFLINE_ISOLATION,
                FlxGateState.NOT_EXECUTED,
                "offline operation was not proven",
            )
        )
    else:
        results.append(
            _pass_or_fail(
                bool(offline.dns_blocked)
                and bool(offline.socket_creation_blocked)
                and offline.network_attempts_observed == 0,
                FlxGate.OFFLINE_ISOLATION,
                "the network was sealed and nothing attempted to reach it",
                f"{offline.network_attempts_observed} network attempts were observed",
                "FLX_NETWORK_ACCESS_ATTEMPTED",
            )
        )

    if not operational.measured:
        results.append(
            _result(
                FlxGate.OPERATIONAL,
                FlxGateState.NOT_EXECUTED,
                "no operational measurement was taken",
            )
        )
    else:
        results.append(
            _pass_or_fail(
                bool(operational.within_limits)
                and operational.policy_fingerprint != "",
                FlxGate.OPERATIONAL,
                f"projections fit inside the limits frozen as "
                f"{identity.RUNTIME_POLICY_ID}",
                "the projected full run does not fit the frozen limits",
                "FLX_OPERATIONALLY_INFEASIBLE",
            )
        )

    results.append(
        _pass_or_fail(
            not probe.biometric_inputs_read and not probe.prior_results_read,
            FlxGate.ARCHITECTURE_FIT,
            "the route runs behind the existing adapter contract and read no "
            "benchmark input or prior result",
            "the route read a forbidden input",
            "FLX_FORBIDDEN_INPUT_READ",
        )
    )
    results.append(
        _result(
            FlxGate.LICENSE_STATUS,
            FlxGateState.PASSED,
            "source licence clear; weights licence unresolved and recorded as such, "
            "with local execution instructed by the project owner and never presented "
            "as a licence finding (docs/adr/0068)",
        )
    )
    order = {gate: index for index, gate in enumerate(FlxGate)}
    return tuple(sorted(results, key=lambda item: order[item.gate]))


def outcome_for(gates: Mapping[FlxGate, FlxGateState] | tuple[FlxGateResult, ...]) -> FlxOutcome:
    """The first failing gate decides which kind of failure this was."""
    states = (
        gates
        if isinstance(gates, Mapping)
        else {result.gate: result.state for result in gates}
    )
    if all(state is FlxGateState.PASSED for state in states.values()):
        return FlxOutcome.RAW_SCORE_EXECUTION_READY
    if states.get(FlxGate.ARTIFACT_IDENTITY) is FlxGateState.FAILED:
        return FlxOutcome.ARTIFACT_MISMATCH
    if states.get(FlxGate.RUNTIME_IDENTITY) is FlxGateState.FAILED or (
        states.get(FlxGate.CHECKPOINT_LOADED) is FlxGateState.FAILED
    ):
        return FlxOutcome.RUNTIME_BLOCKED
    if states.get(FlxGate.OPERATIONAL) is FlxGateState.FAILED:
        return FlxOutcome.OPERATIONALLY_INFEASIBLE
    return FlxOutcome.CONTRACT_FAILED


def build_qualification_report(
    *,
    binding: FlxArtifactBinding,
    manifest: FlxRuntimeManifest,
    probe: FlxRuntimeProbe,
    qualified_utc: str,
) -> FlxQualificationReport:
    gates = evaluate_gates(binding=binding, manifest=manifest, probe=probe)
    outcome = outcome_for(gates)
    return FlxQualificationReport.create(
        schema_version=STAGE8B_SCHEMA_VERSION,
        report_id="flx_qualification_report_v1",
        protocol_id=identity.QUALIFICATION_PROTOCOL_ID,
        algorithm_id=identity.ALGORITHM_ID,
        outcome=outcome,
        gates=gates,
        probe_fingerprint=probe.fingerprint,
        weights_license_status=identity.WEIGHTS_LICENSE_STATUS,
        redistribution_allowed=identity.REDISTRIBUTION_ALLOWED,
        publication_permission=identity.PUBLICATION_PERMISSION,
        opens_stage_8c=outcome is FlxOutcome.RAW_SCORE_EXECUTION_READY,
        # Raw-score readiness never permits a decision (docs/adr/0065).
        permits_decisions=False,
        qualified_utc=qualified_utc,
    )
