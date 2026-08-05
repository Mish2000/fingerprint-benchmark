"""Builders for complete, valid Stage 8B records.

Every helper returns something that *passes*, so a test can express what it is
testing by changing one field and asserting the refusal.  Nothing here needs
torch, a checkpoint, a network or a dataset: these are the frozen claims, not
the runtime.
"""

from __future__ import annotations

from typing import Any, Mapping

from fpbench.core.flx_models import (
    REQUIRED_PREPROCESSING_STEPS,
    STAGE8B_SCHEMA_VERSION,
    FlxAdapterProfile,
    FlxArtifactBinding,
    FlxDependencyPin,
    FlxDeterminismReport,
    FlxGate,
    FlxGateResult,
    FlxGateState,
    FlxOfflineReport,
    FlxOperationalReport,
    FlxOutcome,
    FlxPreprocessingProfile,
    FlxPreprocessingStep,
    FlxQualificationReport,
    FlxRepresentationBranchSpec,
    FlxRepresentationProfile,
    FlxRuntimeManifest,
    FlxRuntimePolicy,
    FlxRuntimeProbe,
    FlxScoreProfile,
    FlxScoreSerializationProfile,
    Stage8BFinalization,
)
from fpbench.flx import identity

NOW = "2026-08-05T12:00:00+03:00"
COMMIT = "1" * 40
DIGEST = "a" * 64
STAGE8A_SELECTION_POLICY_FINGERPRINT = (
    "b61d85f8539d06df9984fa6ad95f21e40977edfda17225c53fdbfb2428b6f396"
)


def rebuild(record: Any, **changes: Any) -> Any:
    """Rebuild a frozen record with different claims and a matching fingerprint."""
    fields = {
        name: getattr(record, name)
        for name in record.__dataclass_fields__
        if name != "fingerprint"
    }
    fields.update(changes)
    return type(record).create(**fields)


def make_policy(**changes: Any) -> FlxRuntimePolicy:
    claims: dict[str, Any] = dict(
        schema_version=STAGE8B_SCHEMA_VERSION,
        policy_id=identity.RUNTIME_POLICY_ID,
        inherits_selection_policy_fingerprint=STAGE8A_SELECTION_POLICY_FINGERPRINT,
        max_projected_12000_extractions_seconds="86400",
        max_projected_6000_comparisons_seconds="21600",
        max_peak_ram_bytes=34359738368,
        max_artifact_disk_bytes=10737418240,
        max_worker_startup_seconds="60",
        max_model_load_seconds="300",
        preprocess_deadline_seconds="60",
        extract_deadline_seconds="120",
        compare_deadline_seconds="60",
        numeric_tolerance=identity.NUMERIC_TOLERANCE,
    )
    claims.update(changes)
    return FlxRuntimePolicy.create(**claims)


def make_artifact_binding(**changes: Any) -> FlxArtifactBinding:
    claims: dict[str, Any] = dict(
        schema_version=STAGE8B_SCHEMA_VERSION,
        binding_id="flx_artifact_binding_v1",
        algorithm_id=identity.ALGORITHM_ID,
        source_commit=identity.SOURCE_COMMIT,
        source_archive_sha256=identity.SOURCE_ARCHIVE_SHA256,
        source_tree_verified_files=4,
        checkpoint_filename=identity.CHECKPOINT_FILENAME,
        checkpoint_sha256=identity.CHECKPOINT_SHA256,
        checkpoint_size_bytes=identity.CHECKPOINT_SIZE_BYTES,
        checkpoint_variant=identity.CHECKPOINT_VARIANT,
        implementation_origin=identity.IMPLEMENTATION_ORIGIN,
        upstream_study=identity.UPSTREAM_STUDY,
        upstream_relationship=identity.UPSTREAM_RELATIONSHIP,
        stage8a_manifest_fingerprint=DIGEST,
        weights_license_status=identity.WEIGHTS_LICENSE_STATUS,
        redistribution_allowed=identity.REDISTRIBUTION_ALLOWED,
        publication_permission=identity.PUBLICATION_PERMISSION,
        checkpoint_committed_to_git=False,
        downloaded_during_inference=False,
        inspected_utc=NOW,
    )
    claims.update(changes)
    return FlxArtifactBinding.create(**claims)


def make_dependency_pin(name: str = "torch", **changes: Any) -> FlxDependencyPin:
    claims: dict[str, Any] = dict(
        schema_version=STAGE8B_SCHEMA_VERSION,
        name=name,
        version="2.13.0+cpu",
        artifact_filename=f"{name}-2.13.0+cpu-cp312-cp312-manylinux_2_28_x86_64.whl",
        artifact_sha256=DIGEST,
        source_index="https://download.pytorch.org/whl/cpu",
    )
    claims.update(changes)
    return FlxDependencyPin.create(**claims)


def make_runtime_manifest(**changes: Any) -> FlxRuntimeManifest:
    claims: dict[str, Any] = dict(
        schema_version=STAGE8B_SCHEMA_VERSION,
        runtime_profile_id=identity.RUNTIME_PROFILE_ID,
        os_name="Linux",
        os_version="Ubuntu 24.04.4 LTS",
        kernel_release="6.6.0-microsoft-standard",
        cpu_architecture="x86_64",
        cpu_model="synthetic test cpu",
        python_version="3.12.3",
        python_implementation="CPython",
        torch_version="2.13.0+cpu",
        torchvision_version="0.28.0+cpu",
        numpy_version="2.5.1",
        blas_implementation="Intel(R) oneAPI Math Kernel Library Version 2024.2",
        mkldnn_version="v3.12.0",
        parallel_backend="OpenMP",
        torch_num_threads=1,
        torch_num_interop_threads=1,
        device="cpu",
        cuda_available=False,
        dependency_lock_sha256=DIGEST,
        dependencies=(make_dependency_pin("torch"), make_dependency_pin("torchvision")),
        deterministic_environment={"OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"},
        created_utc=NOW,
    )
    claims.update(changes)
    return FlxRuntimeManifest.create(**claims)


def make_preprocessing_profile(**changes: Any) -> FlxPreprocessingProfile:
    steps = tuple(
        FlxPreprocessingStep.create(
            schema_version=STAGE8B_SCHEMA_VERSION,
            step_id=step_id,
            action=f"declared action for {step_id}",
            rationale=f"declared rationale for {step_id}",
        )
        for step_id in REQUIRED_PREPROCESSING_STEPS
    )
    claims: dict[str, Any] = dict(
        schema_version=STAGE8B_SCHEMA_VERSION,
        profile_id=identity.PREPROCESSING_PROFILE_ID,
        input_contract="canonical 500 ppi 8-bit grayscale PNG",
        output_shape=(1, identity.MODEL_INPUT_SIDE, identity.MODEL_INPUT_SIDE),
        output_dtype="float32",
        value_minimum="0",
        value_maximum="1",
        padding_fill_value=identity.PAD_FILL_VALUE,
        padding_parity_rule="left_top_floor_right_bottom_remainder",
        resize_side=identity.MODEL_INPUT_SIDE,
        interpolation="torchvision.transforms.InterpolationMode.BILINEAR",
        antialias=True,
        dataset_independent=True,
        subject_independent=True,
        steps=steps,
    )
    claims.update(changes)
    return FlxPreprocessingProfile.create(**claims)


def make_representation_profile(**changes: Any) -> FlxRepresentationProfile:
    branches = (
        FlxRepresentationBranchSpec.create(
            schema_version=STAGE8B_SCHEMA_VERSION,
            branch_id="texture",
            position=0,
            dimensions=identity.TEXTURE_DIMENSIONS,
            dtype="float32",
            normalization="l2_per_branch",
            upstream_module="flx.models.deep_print_arch._Branch_TextureEmbedding",
        ),
        FlxRepresentationBranchSpec.create(
            schema_version=STAGE8B_SCHEMA_VERSION,
            branch_id="minutia",
            position=1,
            dimensions=identity.MINUTIA_DIMENSIONS,
            dtype="float32",
            normalization="l2_per_branch",
            upstream_module="flx.models.deep_print_arch._Branch_MinutiaEmbedding",
        ),
    )
    claims: dict[str, Any] = dict(
        schema_version=STAGE8B_SCHEMA_VERSION,
        profile_id=identity.REPRESENTATION_PROFILE_ID,
        branches=branches,
        concatenated_dimensions=identity.CONCATENATED_DIMENSIONS,
        concatenation_order=("texture", "minutia"),
        inference_batch_rows=identity.INFERENCE_BATCH_ROWS,
        inference_batch_rule=identity.INFERENCE_BATCH_RULE,
        represented_row=identity.REPRESENTED_ROW,
        duplicate_rows_must_be_bitwise_equal=True,
        localization_used=False,
        pose_input_required=False,
        reweighting_applied=False,
        persisted=False,
    )
    claims.update(changes)
    return FlxRepresentationProfile.create(**claims)


def make_score_serialization(**changes: Any) -> FlxScoreSerializationProfile:
    claims: dict[str, Any] = dict(
        schema_version=STAGE8B_SCHEMA_VERSION,
        profile_id=identity.SCORE_SERIALIZATION_PROFILE_ID,
        significant_digits=identity.DECIMAL_SIGNIFICANT_DIGITS,
        intermediate_form="canonical 17-significant-digit decimal string",
        constructed_from="the scalar returned by the pinned comparator",
        rounding_before_storage=False,
    )
    claims.update(changes)
    return FlxScoreSerializationProfile.create(**claims)


def make_score_profile(**changes: Any) -> FlxScoreProfile:
    claims: dict[str, Any] = dict(
        schema_version=STAGE8B_SCHEMA_VERSION,
        profile_id=identity.SCORE_PROFILE_ID,
        formula="dot(texture_left, texture_right) + dot(minutia_left, minutia_right)",
        score_direction=identity.SCORE_DIRECTION,
        nominal_minimum=identity.SCORE_MINIMUM,
        nominal_maximum=identity.SCORE_MAXIMUM,
        range_validation_tolerance=identity.SCORE_RANGE_VALIDATION_TOLERANCE,
        range_validation_policy=identity.SCORE_RANGE_VALIDATION_POLICY,
        branch_weights=("1", "1"),
        serialization=make_score_serialization(),
        returns_decimal=True,
        symmetric=True,
        calibration="none",
        normalization="none",
        threshold="none",
        fallback_matcher="none",
        quality_adjustment="none",
        realignment="none",
    )
    claims.update(changes)
    return FlxScoreProfile.create(**claims)


def make_adapter_profile(**changes: Any) -> FlxAdapterProfile:
    claims: dict[str, Any] = dict(
        schema_version=STAGE8B_SCHEMA_VERSION,
        adapter_id=identity.ADAPTER_ID,
        adapter_version=identity.ADAPTER_VERSION,
        algorithm_id=identity.ALGORITHM_ID,
        process_model="isolated subprocess worker with per-operation deadlines",
        protocol="length-prefixed JSON over pipes",
        operations=(
            "load_runtime",
            "preprocess",
            "extract",
            "compare",
            "validate_runtime",
            "describe_operation",
        ),
        forbidden_inputs=(
            "subject_id",
            "finger_position",
            "release",
            "pair_kind",
            "mated",
            "expected_decision",
            "threshold",
            "sourceafis_result",
            "nbis_result",
        ),
        caches_representations=False,
        persists_representations=False,
        retries_failed_operations=False,
        loads_torch_in_parent=False,
        training_only_checkpoint_keys=identity.TRAINING_ONLY_CHECKPOINT_KEYS,
        runtime_profile_id=identity.RUNTIME_PROFILE_ID,
        preprocessing_profile_id=identity.PREPROCESSING_PROFILE_ID,
        representation_profile_id=identity.REPRESENTATION_PROFILE_ID,
        score_profile_id=identity.SCORE_PROFILE_ID,
        score_serialization_profile_id=identity.SCORE_SERIALIZATION_PROFILE_ID,
    )
    claims.update(changes)
    return FlxAdapterProfile.create(**claims)


def make_probe(**changes: Any) -> FlxRuntimeProbe:
    fixtures = ("fixture_white", "fixture_gradient", "fixture_synthetic_ridges", "fixture_seeded_noise")
    claims: dict[str, Any] = dict(
        schema_version=STAGE8B_SCHEMA_VERSION,
        probe_id="flx_runtime_probe_v1",
        protocol_id=identity.QUALIFICATION_PROTOCOL_ID,
        artifact_binding_fingerprint=make_artifact_binding().fingerprint,
        runtime_manifest_fingerprint=make_runtime_manifest().fingerprint,
        preprocessing_profile_fingerprint=make_preprocessing_profile().fingerprint,
        representation_profile_fingerprint=make_representation_profile().fingerprint,
        score_profile_fingerprint=make_score_profile().fingerprint,
        adapter_profile_fingerprint=make_adapter_profile().fingerprint,
        fixture_ids=fixtures,
        fixture_content_hashes={name: DIGEST for name in fixtures},
        representation_hashes={name: DIGEST for name in fixtures},
        score_hashes={"fixture_white__fixture_white": DIGEST},
        checkpoint_loaded=True,
        model_in_eval_mode=True,
        gradients_disabled=True,
        unexpected_state_dict_keys=(),
        missing_state_dict_keys=(),
        self_independence=make_self_independence(),
        determinism=make_determinism(),
        offline=make_offline(),
        operational=make_operational(),
        biometric_inputs_read=False,
        prior_results_read=False,
        created_utc=NOW,
    )
    claims.update(changes)
    return FlxRuntimeProbe.create(**claims)


def make_self_independence(**changes: Any):
    from fpbench.core.flx_models import FlxSelfIndependenceReport

    claims: dict[str, Any] = dict(
        schema_version=STAGE8B_SCHEMA_VERSION,
        report_id="flx_self_independence_v1",
        tested=True,
        preprocess_call_count=2,
        extract_call_count=2,
        distinct_representation_objects=True,
        representations_equal=True,
        representation_cache_capability_present=False,
    )
    claims.update(changes)
    return FlxSelfIndependenceReport.create(**claims)


def make_determinism(**changes: Any) -> FlxDeterminismReport:
    claims: dict[str, Any] = dict(
        schema_version=STAGE8B_SCHEMA_VERSION,
        report_id="flx_determinism_v1",
        tested=True,
        numeric_tolerance=identity.NUMERIC_TOLERANCE,
        repeated_extraction_bitwise_equal=True,
        repeated_comparison_bitwise_equal=True,
        single_vs_batch_state=FlxGateState.NOT_APPLICABLE,
        single_vs_batch_bitwise_equal=None,
        batch_contexts=(
            "A from [A, A] at row 0",
            "A from [A, B] at row 0",
            "A from [B, A] at row 1",
            "A from [A, C] at row 0",
            "A from [C, A] at row 1",
        ),
        batch_context_texture_bitwise_equal=True,
        batch_context_minutia_bitwise_equal=True,
        process_restart_representation_equal=True,
        process_restart_score_equal=True,
        process_restart_runtime_metadata_equal=True,
        input_order_symmetric=True,
    )
    claims.update(changes)
    return FlxDeterminismReport.create(**claims)


def make_offline(**changes: Any) -> FlxOfflineReport:
    claims: dict[str, Any] = dict(
        schema_version=STAGE8B_SCHEMA_VERSION,
        report_id="flx_offline_v1",
        tested=True,
        dns_blocked=True,
        socket_creation_blocked=True,
        proxy_variables_neutralized=("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"),
        model_hub_variables_redirected=("HF_HOME", "TORCH_HOME"),
        network_attempts_observed=0,
    )
    claims.update(changes)
    return FlxOfflineReport.create(**claims)


def make_operational(**changes: Any) -> FlxOperationalReport:
    claims: dict[str, Any] = dict(
        schema_version=STAGE8B_SCHEMA_VERSION,
        report_id="flx_operational_v1",
        measured=True,
        policy_fingerprint=make_policy().fingerprint,
        worker_startup_seconds="1.5",
        model_load_seconds="12.0",
        preprocess_seconds="0.01",
        extract_seconds="0.773",
        compare_seconds="0.0001",
        peak_ram_bytes=2147483648,
        artifact_disk_bytes=1147483648,
        projected_12000_extractions_seconds="9276",
        projected_6000_comparisons_seconds="1",
        within_limits=True,
    )
    claims.update(changes)
    return FlxOperationalReport.create(**claims)


def make_gate_results(
    overrides: Mapping[FlxGate, FlxGateState] | None = None,
) -> tuple[FlxGateResult, ...]:
    overrides = dict(overrides or {})
    results = []
    for gate in FlxGate:
        state = overrides.get(gate, FlxGateState.PASSED)
        results.append(
            FlxGateResult.create(
                schema_version=STAGE8B_SCHEMA_VERSION,
                gate=gate,
                state=state,
                detail=f"{gate.value} is {state.value}",
                failure_codes=("SYNTHETIC_FAILURE",) if state is FlxGateState.FAILED else (),
            )
        )
    return tuple(results)


def make_qualification_report(**changes: Any) -> FlxQualificationReport:
    gates = changes.pop("gates", make_gate_results())
    ready = all(result.state is FlxGateState.PASSED for result in gates)
    claims: dict[str, Any] = dict(
        schema_version=STAGE8B_SCHEMA_VERSION,
        report_id="flx_qualification_report_v1",
        protocol_id=identity.QUALIFICATION_PROTOCOL_ID,
        algorithm_id=identity.ALGORITHM_ID,
        outcome=FlxOutcome.RAW_SCORE_EXECUTION_READY if ready else FlxOutcome.CONTRACT_FAILED,
        gates=gates,
        probe_fingerprint=make_probe().fingerprint,
        weights_license_status=identity.WEIGHTS_LICENSE_STATUS,
        redistribution_allowed=identity.REDISTRIBUTION_ALLOWED,
        publication_permission=identity.PUBLICATION_PERMISSION,
        opens_stage_8c=ready,
        permits_decisions=False,
        qualified_utc=NOW,
    )
    claims.update(changes)
    return FlxQualificationReport.create(**claims)


def make_finalization(**changes: Any) -> Stage8BFinalization:
    claims: dict[str, Any] = dict(
        schema_version=STAGE8B_SCHEMA_VERSION,
        kind="stage_8b_finalization",
        outcome=FlxOutcome.RAW_SCORE_EXECUTION_READY,
        stage8a_finalization_fingerprint=DIGEST,
        source_archive_sha256=identity.SOURCE_ARCHIVE_SHA256,
        checkpoint_sha256=identity.CHECKPOINT_SHA256,
        artifact_binding_fingerprint=make_artifact_binding().fingerprint,
        runtime_manifest_fingerprint=make_runtime_manifest().fingerprint,
        preprocessing_profile_fingerprint=make_preprocessing_profile().fingerprint,
        representation_profile_fingerprint=make_representation_profile().fingerprint,
        score_profile_fingerprint=make_score_profile().fingerprint,
        adapter_profile_fingerprint=make_adapter_profile().fingerprint,
        runtime_probe_fingerprint=make_probe().fingerprint,
        qualification_report_fingerprint=make_qualification_report().fingerprint,
        runtime_policy_fingerprint=make_policy().fingerprint,
        evidence_content_hashes={name: DIGEST for name in identity.REQUIRED_EVIDENCE_FILES},
        verifier_source_commit=COMMIT,
        verifier_source_tree_clean=True,
        biometric_inputs_read=False,
        prior_stages_unchanged=True,
        created_utc=NOW,
    )
    claims.update(changes)
    return Stage8BFinalization.create(**claims)
