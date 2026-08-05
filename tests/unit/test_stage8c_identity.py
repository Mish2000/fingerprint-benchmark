"""The Stage 8C identities are frozen, and the freeze is what is tested.

Every constant here is restated in a committed configuration file and
republished in the Stage 8C finalization. A test that read the constant and
asserted it equals itself would be worthless, so these assert the literal frozen
values, the relationships between them, and the properties that make them usable
as identities.
"""

from __future__ import annotations

import pytest

from fpbench.core.identifiers import validate_id
from fpbench.experiments import stage8c_identity as frozen
from fpbench.experiments.algorithm_research import REPOSITORY_ROOT
from fpbench.flx import identity as flx_identity

pytestmark = pytest.mark.stage8c_contract


def test_the_stage_identifiers_are_exactly_the_declared_ones() -> None:
    assert frozen.EXPERIMENT_ID == "flx_canonical500_full_v1"
    assert frozen.INTEGRATION_ID == "flx_deepprint_texminu_research_v1"
    assert frozen.EXECUTION_PROFILE_ID == "flx_canonical500_sequential_no_retry_v1"
    assert frozen.ALIGNMENT_PROFILE_ID == "flx_canonical500_alignment_v1"
    assert frozen.STAGE_FINALIZATION_KIND == "stage_8c_finalization"
    assert frozen.EVIDENCE_DIRECTORY.as_posix() == "evidence/flx-canonical500-raw"


def test_every_identifier_is_a_safe_path_and_key_component() -> None:
    for identifier in frozen.all_frozen_identifiers():
        assert validate_id(identifier) == identifier


def test_the_stage_8b_binding_is_the_published_qualification() -> None:
    assert frozen.STAGE8B_FINALIZATION_FINGERPRINT == (
        "aa6897bf25c7b6565647da3566e6ab6446ae6104b2511034fed0fdb08cb13373"
    )
    assert frozen.STAGE8B_OUTCOME == "FLX_RAW_SCORE_EXECUTION_READY"


def test_the_route_identities_are_stage_8bs_own_and_not_a_second_copy() -> None:
    # Restated in this module so a reviewer sees them, but they must equal the
    # authority. A drift here would mean Stage 8C ran something Stage 8B never
    # qualified (spec section 3).
    assert frozen.ALGORITHM_ID == flx_identity.ALGORITHM_ID
    assert frozen.ADAPTER_ID == flx_identity.ADAPTER_ID
    assert frozen.ADAPTER_VERSION == flx_identity.ADAPTER_VERSION
    assert frozen.RUNTIME_PROFILE_ID == flx_identity.RUNTIME_PROFILE_ID
    assert frozen.PREPROCESSING_PROFILE_ID == flx_identity.PREPROCESSING_PROFILE_ID
    assert frozen.REPRESENTATION_PROFILE_ID == flx_identity.REPRESENTATION_PROFILE_ID
    assert frozen.SCORE_PROFILE_ID == flx_identity.SCORE_PROFILE_ID
    assert frozen.SOURCE_COMMIT == flx_identity.SOURCE_COMMIT
    assert frozen.SOURCE_ARCHIVE_SHA256 == flx_identity.SOURCE_ARCHIVE_SHA256
    assert frozen.CHECKPOINT_FILENAME == flx_identity.CHECKPOINT_FILENAME
    assert frozen.CHECKPOINT_SHA256 == flx_identity.CHECKPOINT_SHA256
    assert frozen.CHECKPOINT_SIZE_BYTES == flx_identity.CHECKPOINT_SIZE_BYTES


def test_the_published_profile_fingerprints_are_what_this_source_produces() -> None:
    from fpbench.flx.integration import build_adapter_profile
    from fpbench.flx.preprocessing import build_preprocessing_profile
    from fpbench.flx.representation import build_representation_profile
    from fpbench.flx.score import build_score_profile

    assert build_preprocessing_profile().fingerprint == (
        frozen.PREPROCESSING_PROFILE_FINGERPRINT
    )
    assert build_representation_profile().fingerprint == (
        frozen.REPRESENTATION_PROFILE_FINGERPRINT
    )
    assert build_score_profile().fingerprint == frozen.SCORE_PROFILE_FINGERPRINT
    assert build_adapter_profile().fingerprint == frozen.ADAPTER_PROFILE_FINGERPRINT


def test_the_canonical_experiment_is_the_one_sourceafis_ran() -> None:
    assert frozen.REFERENCE_RUN_ID == "run_4c59fa02a6ab"
    assert frozen.REFERENCE_PLAN_ID == "plan_b4ae66e91923"
    assert frozen.REFERENCE_RESULT_SET_ID == "resultset_087b084fb8a8"
    assert frozen.REFERENCE_COHORT_ID == "sd300_50_subjects_test_22f8d52a7478"
    assert frozen.REFERENCE_PAIR_MANIFEST_HASH == (
        "ee4d942e23cdc112e17ed69e0abc603d5f26e17cc5839edc9aa412edc57dfe3b"
    )
    assert frozen.PREPARATION_SET_ID == "prepset_be560e047991"
    assert frozen.PREPARATION_SET_FINGERPRINT == (
        "be560e047991a0d58af8f86a4576f8b78dc350e643af82f0e2405350d9e2fd3f"
    )
    assert frozen.TRANSFORM_PROFILE_ID == "canonical_gray8_500ppi_lanczos3_v1"
    assert frozen.TRANSFORM_PROFILE_FINGERPRINT == (
        "28abd453d86918132c03a57a2ace1a59024b5fb9c2e02eb5339e2a61e4597373"
    )
    assert frozen.TRANSFORM_RUNTIME_FINGERPRINT == (
        "31a0a4346a3dd07843513cc1de5b167d8f2795b230a82bac709913032b74579c"
    )


def test_the_experiment_shape_is_six_thousand_pairs_over_three_thousand_images() -> None:
    assert frozen.EXPECTED_JOBS == 6000
    assert frozen.EXPECTED_PARTICIPATING_IMAGES == 3000
    assert frozen.EXPECTED_SUBJECTS == 50
    assert frozen.EXPECTED_RELEASES == ("SD300A", "SD300B", "SD300C")
    assert frozen.EXPECTED_PER_RELEASE_STAGE == 500
    # 500 in each of three releases and four stages.
    assert frozen.EXPECTED_PER_RELEASE_STAGE * 3 * 4 == frozen.EXPECTED_JOBS


def test_logical_extractions_and_physical_rows_are_different_counts() -> None:
    # docs/adr/0075. Both numbers are true; they measure different things, and
    # the relationship between them is Stage 8B's batch rule, not a Stage 8C
    # choice.
    assert frozen.PLANNED_PREPROCESS_CALLS == 12_000
    assert frozen.PLANNED_LOGICAL_EXTRACTIONS == 12_000
    assert frozen.PLANNED_PHYSICAL_FORWARD_ROWS == 24_000
    assert frozen.PLANNED_COMPARISON_CALLS == 6_000
    assert frozen.PLANNED_PHYSICAL_FORWARD_ROWS == (
        frozen.PLANNED_LOGICAL_EXTRACTIONS * frozen.INFERENCE_BATCH_ROWS
    )


def test_the_batch_doubling_is_stage_8bs_rule_and_not_restated_here() -> None:
    assert frozen.INFERENCE_BATCH_ROWS == flx_identity.INFERENCE_BATCH_ROWS


def test_both_sides_of_every_comparison_are_independent() -> None:
    # spec section 9: SELF is not a special case. Two preprocess calls and two
    # logical extractions per comparison, whatever the pair kind.
    assert frozen.PREPROCESS_CALLS_PER_COMPARISON == 2
    assert frozen.LOGICAL_EXTRACTIONS_PER_COMPARISON == 2
    assert frozen.COMPARISONS_PER_JOB == 1


def test_the_pinned_runtime_roles_are_three_committed_repository_files() -> None:
    assert frozen.RUNTIME_ASSET_ROLES == (
        "flx_worker_script",
        "flx_runtime_lock",
        "flx_runtime_policy",
    )
    assert frozen.PRIMARY_RUNTIME_ASSET_ROLE == "flx_worker_script"
    assert set(frozen.RUNTIME_ASSET_SOURCES) == set(frozen.RUNTIME_ASSET_ROLES)


def test_no_role_pins_the_checkpoint_or_the_source_archive() -> None:
    # docs/adr/0077: the weights are pinned by frozen digest and re-hashed
    # before every model load. A copy in the workspace would be a second copy of
    # licence-unresolved weights (docs/adr/0068).
    for source in frozen.RUNTIME_ASSET_SOURCES.values():
        assert "checkpoint" not in source
        assert not source.endswith(".pyt")
        assert not source.endswith(".tar.gz")


def test_the_pinned_runtime_files_exist_and_are_committed() -> None:
    for role, relative in sorted(frozen.RUNTIME_ASSET_SOURCES.items()):
        path = REPOSITORY_ROOT / relative
        assert path.is_file(), f"{role} names a missing file: {relative}"
        assert not path.is_symlink(), f"{role} may not be a link"


def test_the_job_deadline_covers_every_stage_8b_operation_deadline() -> None:
    # spec section 11: 2 preprocess + 2 extract + 1 compare + 60 s margin. The
    # whole-job deadline does not replace the per-operation ones.
    from fpbench.flx.policy import load_runtime_policy

    policy = load_runtime_policy(
        REPOSITORY_ROOT / "configs" / "flx" / "stage8b_flx_runtime_policy_v1.yaml"
    )
    operations = (
        2 * float(policy.preprocess_deadline_seconds)
        + 2 * float(policy.extract_deadline_seconds)
        + 1 * float(policy.compare_deadline_seconds)
    )
    assert operations == 420.0
    assert frozen.JOB_DEADLINE_SECONDS == 480
    assert frozen.JOB_DEADLINE_SECONDS - operations == 60.0


def test_nothing_may_derive_from_this_run_yet() -> None:
    # docs/adr/0076: a decision set over these scores would mean somebody chose
    # a threshold for the flx scale, and there is none to choose.
    assert frozen.PERMITTED_DOWNSTREAM_EXPERIMENTS == frozenset()


def test_the_forbidden_config_keys_cover_every_route_to_a_threshold() -> None:
    assert frozen.FORBIDDEN_CONFIG_KEYS >= {
        "threshold",
        "decision_profile",
        "match_threshold",
        "acceptance_threshold",
        "calibration",
        "eer",
        "far",
        "fmr",
        "fnmr",
        "roc",
        "det",
        "score_bins",
        "score_statistics",
    }


def test_the_reporting_switches_permit_operations_and_nothing_else() -> None:
    assert frozen.REQUIRED_REPORTING_SWITCHES == {
        "operational_summary": True,
        "biometric_metrics": False,
        "score_statistics": False,
        "score_export": False,
    }


def test_the_score_is_stored_beside_its_canonical_decimal_text() -> None:
    assert frozen.RAW_SCORE_DECIMAL_METADATA_KEY == "flx.raw_score_decimal"
