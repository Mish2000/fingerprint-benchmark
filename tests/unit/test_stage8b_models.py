"""What the Stage 8B record vocabulary refuses to say.

Each test changes one claim in an otherwise valid record and asserts the
refusal, so the invariants are pinned by counter-example rather than by
restating the constructor.
"""

from __future__ import annotations

import pytest

from fpbench.core.flx_models import (
    REQUIRED_PREPROCESSING_STEPS,
    FlxGate,
    FlxGateResult,
    FlxGateState,
    FlxOutcome,
    FlxPreprocessingStep,
    STAGE8B_SCHEMA_VERSION,
    semantic_fingerprint,
)
from fpbench.core.serialization import to_plain
from fpbench.flx import identity
from flxworld import (
    make_adapter_profile,
    make_artifact_binding,
    make_dependency_pin,
    make_determinism,
    make_finalization,
    make_gate_results,
    make_offline,
    make_operational,
    make_policy,
    make_preprocessing_profile,
    make_probe,
    make_qualification_report,
    make_representation_profile,
    make_runtime_manifest,
    make_score_profile,
    make_score_serialization,
    make_self_independence,
    rebuild,
)

pytestmark = pytest.mark.stage8b_contract


# ------------------------------------------------------------- fingerprints


def test_every_record_fingerprints_its_own_claims() -> None:
    for record in (
        make_policy(),
        make_artifact_binding(),
        make_runtime_manifest(),
        make_preprocessing_profile(),
        make_representation_profile(),
        make_score_profile(),
        make_adapter_profile(),
        make_probe(),
        make_qualification_report(),
        make_finalization(),
    ):
        assert len(record.fingerprint) == 64
        clone = rebuild(record)
        assert clone.fingerprint == record.fingerprint
        assert to_plain(clone) == to_plain(record)


def test_a_fingerprint_that_does_not_cover_the_claims_is_refused() -> None:
    binding = make_artifact_binding()
    fields = {
        name: getattr(binding, name)
        for name in binding.__dataclass_fields__
        if name != "fingerprint"
    }
    fields["source_tree_verified_files"] = 99
    with pytest.raises(ValueError, match="fingerprint does not cover"):
        type(binding)(**fields, fingerprint=binding.fingerprint)


def test_a_wall_clock_change_does_not_move_a_semantic_fingerprint() -> None:
    binding = make_artifact_binding()
    later = rebuild(binding, inspected_utc="2027-01-01T00:00:00+03:00")
    assert later.fingerprint == binding.fingerprint


# ---------------------------------------------------------------- artifacts


def test_the_checkpoint_may_never_be_recorded_as_committed_to_git() -> None:
    with pytest.raises(ValueError, match="never be committed"):
        make_artifact_binding(checkpoint_committed_to_git=True)


def test_an_artifact_downloaded_during_inference_is_refused() -> None:
    with pytest.raises(ValueError, match="downloaded during inference"):
        make_artifact_binding(downloaded_during_inference=True)


def test_the_weights_licence_cannot_be_recorded_as_resolved() -> None:
    # docs/adr/0068: local execution permission is not a licence finding.
    with pytest.raises(ValueError, match="may not record the weights licence as resolved"):
        make_artifact_binding(weights_license_status="resolved")


def test_a_truncated_checkpoint_size_is_still_a_size_but_a_different_identity() -> None:
    smaller = make_artifact_binding(checkpoint_size_bytes=identity.CHECKPOINT_SIZE_BYTES - 1)
    assert smaller.fingerprint != make_artifact_binding().fingerprint


def test_a_short_commit_is_not_a_source_identity() -> None:
    with pytest.raises(ValueError, match="40-character commit"):
        make_artifact_binding(source_commit="7accfca")


# ------------------------------------------------------------------ runtime


def test_a_runtime_manifest_without_pins_is_not_a_lock() -> None:
    with pytest.raises(ValueError, match="without dependency pins is not a lock"):
        make_runtime_manifest(dependencies=())


def test_a_distribution_may_be_pinned_only_once() -> None:
    with pytest.raises(ValueError, match="pinned only once"):
        make_runtime_manifest(
            dependencies=(make_dependency_pin("torch"), make_dependency_pin("torch"))
        )


def test_a_dependency_pin_must_name_the_wheel_that_was_installed() -> None:
    with pytest.raises(ValueError, match="exact wheel"):
        make_dependency_pin(artifact_filename="torch-2.13.0.tar.gz")


def test_a_cpu_profile_refuses_to_describe_a_gpu_runtime() -> None:
    with pytest.raises(ValueError, match="CPU profile"):
        make_runtime_manifest(cuda_available=True)
    with pytest.raises(ValueError, match="CPU profile"):
        make_runtime_manifest(device="cuda:0")


def test_changing_any_pinned_dependency_changes_the_runtime_identity() -> None:
    baseline = make_runtime_manifest()
    for change in (
        {"torch_version": "2.12.1+cpu"},
        {"torchvision_version": "0.27.1+cpu"},
        {"numpy_version": "2.5.0"},
        {"python_version": "3.12.4"},
        {"torch_num_threads": 4},
        {"mkldnn_version": "v3.11.0"},
        {"deterministic_environment": {"OMP_NUM_THREADS": "4"}},
    ):
        assert make_runtime_manifest(**change).fingerprint != baseline.fingerprint


# ------------------------------------------------------------ preprocessing


def test_a_profile_must_document_every_step_in_order() -> None:
    steps = make_preprocessing_profile().steps
    with pytest.raises(ValueError, match="every required step"):
        make_preprocessing_profile(steps=steps[:-1])
    with pytest.raises(ValueError, match="every required step"):
        make_preprocessing_profile(steps=tuple(reversed(steps)))


def test_the_required_steps_name_every_question_the_transform_answers() -> None:
    assert REQUIRED_PREPROCESSING_STEPS == (
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


def test_a_dataset_dependent_transform_is_refused() -> None:
    with pytest.raises(ValueError, match="may not branch on dataset or subject"):
        make_preprocessing_profile(dataset_independent=False)
    with pytest.raises(ValueError, match="may not branch on dataset or subject"):
        make_preprocessing_profile(subject_independent=False)


def test_the_output_shape_must_be_one_channel_at_the_declared_side() -> None:
    with pytest.raises(ValueError, match="one channel at the declared resize side"):
        make_preprocessing_profile(output_shape=(3, 299, 299))
    with pytest.raises(ValueError, match="one channel at the declared resize side"):
        make_preprocessing_profile(output_shape=(1, 224, 224))


def test_a_padding_fill_outside_eight_bits_is_refused() -> None:
    with pytest.raises(ValueError, match="8-bit sample"):
        make_preprocessing_profile(padding_fill_value=256)


@pytest.mark.parametrize(
    "change",
    [
        {"padding_fill_value": 0},
        {"padding_parity_rule": "left_top_remainder_right_bottom_floor"},
        {"interpolation": "torchvision.transforms.InterpolationMode.NEAREST"},
        {"antialias": False},
        {"output_dtype": "float64"},
        {"value_maximum": "255"},
    ],
)
def test_tampering_with_the_transform_changes_its_identity(change) -> None:
    assert make_preprocessing_profile(**change).fingerprint != make_preprocessing_profile().fingerprint


def test_a_step_without_a_rationale_is_not_a_declaration() -> None:
    with pytest.raises(ValueError, match="rationale"):
        FlxPreprocessingStep.create(
            schema_version=STAGE8B_SCHEMA_VERSION,
            step_id="decode",
            action="decode as gray8",
            rationale="",
        )


# ----------------------------------------------------------- representation


def test_the_representation_is_exactly_two_branches() -> None:
    branches = make_representation_profile().branches
    with pytest.raises(ValueError, match="exactly two branches"):
        make_representation_profile(
            branches=branches[:1], concatenation_order=("texture",), concatenated_dimensions=256
        )


def test_swapping_the_branch_order_changes_the_representation_identity() -> None:
    baseline = make_representation_profile()
    swapped_branches = (
        rebuild(baseline.branches[1], position=0),
        rebuild(baseline.branches[0], position=1),
    )
    swapped = make_representation_profile(
        branches=swapped_branches, concatenation_order=("minutia", "texture")
    )
    assert swapped.fingerprint != baseline.fingerprint


def test_the_concatenation_order_must_match_the_stored_branches() -> None:
    with pytest.raises(ValueError, match="concatenation order must match"):
        make_representation_profile(concatenation_order=("minutia", "texture"))


def test_the_concatenated_width_must_be_the_sum_of_the_branches() -> None:
    with pytest.raises(ValueError, match="sum of the branch dimensions"):
        make_representation_profile(concatenated_dimensions=384)


def test_a_duplicated_batch_must_assert_its_rows_are_equal() -> None:
    # docs/adr/0070: the duplication is a checked invariant, not an assumption.
    with pytest.raises(ValueError, match="bitwise equal"):
        make_representation_profile(duplicate_rows_must_be_bitwise_equal=False)


def test_the_represented_row_must_index_the_batch() -> None:
    with pytest.raises(ValueError, match="represented_row must index"):
        make_representation_profile(represented_row=2)


def test_this_variant_has_no_localization_pose_or_reweighting() -> None:
    for change, match in (
        ({"localization_used": True}, "no localization branch"),
        ({"pose_input_required": True}, "no localization branch"),
        ({"reweighting_applied": True}, "no branch reweighting"),
    ):
        with pytest.raises(ValueError, match=match):
            make_representation_profile(**change)


def test_a_representation_profile_may_not_declare_persistence() -> None:
    with pytest.raises(ValueError, match="never written to disk"):
        make_representation_profile(persisted=True)


# -------------------------------------------------------------------- score


def test_the_public_api_must_return_decimal() -> None:
    with pytest.raises(ValueError, match="returns Decimal, never a Python float"):
        make_score_profile(returns_decimal=False)


def test_a_raw_score_is_never_rounded_before_storage() -> None:
    with pytest.raises(ValueError, match="never rounded"):
        make_score_serialization(rounding_before_storage=True)


@pytest.mark.parametrize(
    "field",
    ["calibration", "normalization", "threshold", "fallback_matcher", "quality_adjustment", "realignment"],
)
def test_a_raw_score_profile_carries_no_hidden_machinery(field: str) -> None:
    with pytest.raises(ValueError, match=f"{field} must be 'none'"):
        make_score_profile(**{field: "documented_at_40"})


def test_branch_weights_are_exactly_one_each() -> None:
    with pytest.raises(ValueError, match="both branches carry weight exactly one"):
        make_score_profile(branch_weights=("0.6", "0.4"))


def test_the_nominal_range_is_minus_two_to_two() -> None:
    profile = make_score_profile()
    assert (profile.nominal_minimum, profile.nominal_maximum) == ("-2", "2")
    with pytest.raises(ValueError, match="lower than"):
        make_score_profile(nominal_minimum="2", nominal_maximum="-2")


def test_the_range_validation_contract_is_exact_and_fingerprinted() -> None:
    profile = make_score_profile()
    assert profile.range_validation_tolerance == "0.000000476837158203125"
    assert profile.range_validation_policy == (
        "nominal_bounds_plus_symmetric_tolerance_no_clamp"
    )
    assert make_score_profile(
        range_validation_tolerance="0.00000095367431640625"
    ).fingerprint != profile.fingerprint
    with pytest.raises(ValueError, match="must be positive"):
        make_score_profile(range_validation_tolerance="0")
    with pytest.raises(ValueError, match="range_validation_policy must be"):
        make_score_profile(range_validation_policy="nominal_bounds_then_clamp")


def test_the_score_direction_cannot_be_inverted() -> None:
    with pytest.raises(ValueError, match="higher_is_more_similar"):
        make_score_profile(score_direction="lower_is_more_similar")


def test_changing_the_serialization_rule_changes_the_score_identity() -> None:
    baseline = make_score_profile()
    changed = make_score_profile(serialization=make_score_serialization(significant_digits=15))
    assert changed.fingerprint != baseline.fingerprint


# ------------------------------------------------------------------ adapter


def test_the_adapter_exposes_exactly_the_six_contracted_operations() -> None:
    with pytest.raises(ValueError, match="exactly the six contracted operations"):
        make_adapter_profile(operations=("load_runtime", "preprocess", "extract", "compare"))
    with pytest.raises(ValueError, match="exactly the six contracted operations"):
        make_adapter_profile(
            operations=(
                "preprocess",
                "load_runtime",
                "extract",
                "compare",
                "validate_runtime",
                "describe_operation",
            )
        )


@pytest.mark.parametrize(
    "field",
    [
        "caches_representations",
        "persists_representations",
        "retries_failed_operations",
        "loads_torch_in_parent",
    ],
)
def test_the_adapter_may_not_declare_a_forbidden_behaviour(field: str) -> None:
    with pytest.raises(ValueError, match=f"{field} must be false"):
        make_adapter_profile(**{field: True})


def test_the_adapter_names_the_inputs_it_must_never_see() -> None:
    profile = make_adapter_profile()
    assert {"subject_id", "finger_position", "pair_kind", "mated", "threshold"} <= set(
        profile.forbidden_inputs
    )


def test_the_adapter_version_is_part_of_its_identity() -> None:
    assert make_adapter_profile(adapter_version=2).fingerprint != make_adapter_profile().fingerprint


def test_the_training_only_allowlist_is_part_of_the_adapter_identity() -> None:
    widened = make_adapter_profile(
        training_only_checkpoint_keys=identity.TRAINING_ONLY_CHECKPOINT_KEYS + ("scheduler_state_dict",)
    )
    assert widened.fingerprint != make_adapter_profile().fingerprint


# -------------------------------------------------------------------- probe


def test_an_untested_probe_reports_nothing_rather_than_a_failure() -> None:
    # Stage 8A's rule, kept: not executed is not the same as observed to fail.
    for factory, kwargs in (
        (make_self_independence, {"preprocess_call_count": 2}),
        (make_determinism, {"repeated_extraction_bitwise_equal": True}),
        (make_offline, {"dns_blocked": True}),
        (make_operational, {"extract_seconds": "0.5"}),
    ):
        with pytest.raises(ValueError, match="reports nothing|missing measurements"):
            factory(tested=False, **kwargs) if factory is not make_operational else factory(
                measured=False, **kwargs
            )


def test_a_tested_report_must_carry_every_observation() -> None:
    with pytest.raises(ValueError, match="must carry every observation"):
        make_self_independence(extract_call_count=None)
    with pytest.raises(ValueError, match="must carry every observation"):
        make_determinism(input_order_symmetric=None)
    with pytest.raises(ValueError, match="must name every batch context"):
        make_determinism(batch_contexts=())


def test_a_not_applicable_batch_comparison_carries_no_observation() -> None:
    # Spec section 17.6: no batch-of-one API exists, so nothing is invented.
    with pytest.raises(ValueError, match="not-applicable batch comparison"):
        make_determinism(
            single_vs_batch_state=FlxGateState.NOT_APPLICABLE,
            single_vs_batch_bitwise_equal=True,
        )


def test_a_probe_may_not_admit_reading_biometric_input_or_prior_results() -> None:
    with pytest.raises(ValueError, match="no SD300 image"):
        make_probe(biometric_inputs_read=True)
    with pytest.raises(ValueError, match="no SD300 image"):
        make_probe(prior_results_read=True)


def test_a_loaded_model_must_be_in_eval_mode_with_gradients_disabled() -> None:
    with pytest.raises(ValueError, match="eval mode with gradients disabled"):
        make_probe(model_in_eval_mode=False)
    with pytest.raises(ValueError, match="eval mode with gradients disabled"):
        make_probe(gradients_disabled=False)


def test_every_fixture_must_be_content_addressed() -> None:
    with pytest.raises(ValueError, match="content-addressed exactly once"):
        make_probe(fixture_content_hashes={"fixture_white": "a" * 64})


def test_a_probe_must_name_the_fixtures_it_ran_on() -> None:
    with pytest.raises(ValueError, match="name the fixtures"):
        make_probe(fixture_ids=(), fixture_content_hashes={})


# ------------------------------------------------------------ qualification


def test_a_report_states_every_gate_exactly_once_in_order() -> None:
    gates = make_gate_results()
    with pytest.raises(ValueError, match="every gate exactly once"):
        make_qualification_report(gates=gates[:-1])
    with pytest.raises(ValueError, match="every gate exactly once"):
        make_qualification_report(gates=tuple(reversed(gates)))


def test_ready_holds_exactly_when_every_gate_passed() -> None:
    ready = make_qualification_report()
    assert ready.outcome is FlxOutcome.RAW_SCORE_EXECUTION_READY
    assert ready.opens_stage_8c is True

    blocked = make_qualification_report(
        gates=make_gate_results({FlxGate.DETERMINISM: FlxGateState.FAILED})
    )
    assert blocked.outcome is FlxOutcome.CONTRACT_FAILED
    assert blocked.opens_stage_8c is False


def test_a_ready_outcome_over_a_failed_gate_is_refused() -> None:
    with pytest.raises(ValueError, match="ready outcome holds exactly when"):
        make_qualification_report(
            gates=make_gate_results({FlxGate.OFFLINE_ISOLATION: FlxGateState.FAILED}),
            outcome=FlxOutcome.RAW_SCORE_EXECUTION_READY,
            opens_stage_8c=True,
        )


def test_an_unrun_gate_does_not_produce_a_ready_outcome() -> None:
    report = make_qualification_report(
        gates=make_gate_results({FlxGate.RESTART: FlxGateState.NOT_EXECUTED})
    )
    assert report.outcome is not FlxOutcome.RAW_SCORE_EXECUTION_READY
    assert report.opens_stage_8c is False


def test_raw_score_readiness_never_permits_decisions() -> None:
    # docs/adr/0065.
    with pytest.raises(ValueError, match="never permits MATCH"):
        make_qualification_report(permits_decisions=True)


def test_a_failed_gate_must_name_a_failure_code() -> None:
    with pytest.raises(ValueError, match="must name at least one failure code"):
        FlxGateResult.create(
            schema_version=STAGE8B_SCHEMA_VERSION,
            gate=FlxGate.DETERMINISM,
            state=FlxGateState.FAILED,
            detail="drifted",
            failure_codes=(),
        )


def test_only_a_failed_gate_carries_failure_codes() -> None:
    with pytest.raises(ValueError, match="only a failed gate"):
        FlxGateResult.create(
            schema_version=STAGE8B_SCHEMA_VERSION,
            gate=FlxGate.DETERMINISM,
            state=FlxGateState.PASSED,
            detail="fine",
            failure_codes=("SOMETHING",),
        )


# ------------------------------------------------------------ finalization


def test_finalization_requires_a_clean_verifier_tree() -> None:
    with pytest.raises(ValueError, match="clean verifier source tree"):
        make_finalization(verifier_source_tree_clean=False)


def test_finalization_refuses_to_claim_a_biometric_input_was_read() -> None:
    with pytest.raises(ValueError, match="read no biometric input"):
        make_finalization(biometric_inputs_read=True)


def test_finalization_requires_prior_stages_unchanged() -> None:
    with pytest.raises(ValueError, match="prior stages to be unchanged"):
        make_finalization(prior_stages_unchanged=False)


def test_finalization_binds_every_evidence_file_by_content() -> None:
    marker = make_finalization()
    assert set(marker.evidence_content_hashes) == set(identity.REQUIRED_EVIDENCE_FILES)


def test_an_evidence_hash_that_is_not_a_digest_is_refused() -> None:
    hashes = dict.fromkeys(identity.REQUIRED_EVIDENCE_FILES, "a" * 64)
    hashes["README.md"] = "not-a-digest"
    with pytest.raises(ValueError, match="evidence_content_hashes"):
        make_finalization(evidence_content_hashes=hashes)


def test_the_finalization_kind_is_fixed() -> None:
    with pytest.raises(ValueError, match="kind must be stage_8b_finalization"):
        make_finalization(kind="stage_8a_finalization")


def test_semantic_fingerprints_are_stable_across_equal_documents() -> None:
    first = make_finalization()
    second = make_finalization()
    assert semantic_fingerprint("stage_8b_finalization_v1", first) == semantic_fingerprint(
        "stage_8b_finalization_v1", second
    )
