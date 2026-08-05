"""The Stage 8C configuration is strict, and strictness is what is tested.

The committed document is loaded once and asserted against the frozen protocol.
Everything else here is a mutation of that document, written to a temporary file
and expected to be refused: an unknown key, a threshold at any depth, a reporting
switch in the wrong position, an identity that does not match the freeze, a
parallel run, a retry, or two files disagreeing about the budget.

None of this needs SD300, torch, a checkpoint or a workspace.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from fpbench.core.errors import ConfigurationError
from fpbench.experiments import stage8c_identity as frozen
from fpbench.experiments.algorithm_research import REPOSITORY_ROOT
from fpbench.experiments.flx_canonical500_full import (
    DEFAULT_EXPERIMENT_CONFIG,
    build_flx_canonical500_spec,
    load_flx_canonical500_config,
)

pytestmark = pytest.mark.stage8c_contract


# ------------------------------------------------------------------- helpers


def _document() -> dict[str, Any]:
    return yaml.safe_load(DEFAULT_EXPERIMENT_CONFIG.read_text(encoding="utf-8"))


def _write(tmp_path: Path, document: Any, name: str = "experiment.yaml") -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


def _load_mutated(tmp_path: Path, mutate) -> None:
    document = _document()
    mutate(document)
    load_flx_canonical500_config(
        _write(tmp_path, document), repository_root=REPOSITORY_ROOT
    )


def _refuses(tmp_path: Path, mutate, *, because: str) -> None:
    with pytest.raises(ConfigurationError) as caught:
        _load_mutated(tmp_path, mutate)
    assert caught.value.args, because


# ------------------------------------------------------- the committed config


def test_the_committed_config_loads_and_is_the_frozen_experiment() -> None:
    config = load_flx_canonical500_config()
    assert config.experiment_id == frozen.EXPERIMENT_ID
    assert config.kind == "research"
    assert config.replicate_index == 0
    assert config.require_verified_checksums is True
    assert config.research_mode is True


def test_the_committed_config_names_the_qualified_stage_8b_route() -> None:
    binding = load_flx_canonical500_config().stage8b
    assert binding.finalization_fingerprint == frozen.STAGE8B_FINALIZATION_FINGERPRINT
    assert binding.outcome == frozen.STAGE8B_OUTCOME
    assert binding.algorithm_id == frozen.ALGORITHM_ID
    assert binding.adapter_id == frozen.ADAPTER_ID
    assert binding.adapter_version == frozen.ADAPTER_VERSION
    assert binding.profile_fingerprints["score"] == frozen.SCORE_PROFILE_FINGERPRINT


def test_the_committed_config_names_the_canonical_reference_chain() -> None:
    config = load_flx_canonical500_config()
    assert config.reference.run_id == frozen.REFERENCE_RUN_ID
    assert config.reference.plan_id == frozen.REFERENCE_PLAN_ID
    assert config.reference.result_set_id == frozen.REFERENCE_RESULT_SET_ID
    assert config.reference_cohort_id == frozen.REFERENCE_COHORT_ID
    assert config.reference_pair_manifest_hash == frozen.REFERENCE_PAIR_MANIFEST_HASH
    assert config.preparation_set_id == frozen.PREPARATION_SET_ID
    assert config.transform_runtime_fingerprint == frozen.TRANSFORM_RUNTIME_FINGERPRINT


def test_the_committed_config_is_the_six_thousand_pair_shape() -> None:
    config = load_flx_canonical500_config()
    assert config.expected_jobs == 6000
    assert config.expected_participating_images == 3000
    assert config.expected_subjects == 50
    assert config.expected_releases == ("SD300A", "SD300B", "SD300C")
    assert config.expected_per_release_stage == 500
    assert config.expected_per_release == 2000
    assert config.expected_per_stage == 1500
    assert config.expected_source_ppi == {"SD300A": 500, "SD300B": 1000, "SD300C": 2000}
    expectations = config.alignment_expectations
    assert expectations.pair_count == 6000
    assert expectations.prepared_entry_count == 3000
    assert expectations.prepared_entries_per_release == 1000


def test_the_committed_config_plans_the_exact_operation_counts() -> None:
    operations = load_flx_canonical500_config().operations
    assert operations.planned_preprocess_calls == 12_000
    assert operations.planned_logical_extractions == 12_000
    assert operations.planned_physical_forward_rows == 24_000
    assert operations.planned_comparison_calls == 6_000
    assert operations.inference_batch_rule == "duplicate_pair_take_first_row"
    assert operations.represented_row == 0


def test_the_execution_profile_is_stage_8cs_own_with_the_reference_parameters() -> None:
    profile = load_flx_canonical500_config().execution_profile
    assert profile.profile_id == frozen.EXECUTION_PROFILE_ID
    assert profile.timeout_seconds == float(frozen.JOB_DEADLINE_SECONDS)
    assert profile.deterministic_seed == 0
    # The preparer and every input-set parameter are the reference run's, which
    # is what makes the two runs read the same pixels (docs/adr/0074).
    assert profile.preparer_id == "canonical_500_png"
    assert profile.parameters["preparation_set_id"] == frozen.PREPARATION_SET_ID
    assert profile.parameters["target_ppi"] == "500"
    assert profile.parameters["resolution_mode"] == "canonical_500"


def test_the_execution_profile_carries_the_reference_runs_input_parameters() -> None:
    reference_profile = yaml.safe_load(
        (
            REPOSITORY_ROOT / "configs" / "execution" / "canonical_500_lanczos3_60s_v1.yaml"
        ).read_text(encoding="utf-8")
    )
    stage8c_profile = yaml.safe_load(
        (
            REPOSITORY_ROOT
            / "configs"
            / "execution"
            / "flx_canonical500_sequential_no_retry_v1.yaml"
        ).read_text(encoding="utf-8")
    )
    # Identical inputs, different budget. Anything else would be a second
    # difference between the two runs (docs/adr/0074).
    assert stage8c_profile["parameters"] == reference_profile["parameters"]
    assert stage8c_profile["profile"]["preparer_id"] == (
        reference_profile["profile"]["preparer_id"]
    )
    assert stage8c_profile["profile"]["deterministic_seed"] == (
        reference_profile["profile"]["deterministic_seed"]
    )
    assert stage8c_profile["profile"]["timeout_seconds"] == 480
    assert reference_profile["profile"]["timeout_seconds"] == 60


def test_the_spec_handed_to_the_engine_is_the_configured_experiment() -> None:
    spec = build_flx_canonical500_spec(load_flx_canonical500_config())
    assert spec.experiment_id == frozen.EXPERIMENT_ID
    assert spec.expected_jobs == 6000
    assert spec.expected_participating_images == 3000
    assert spec.is_canonical is True
    assert spec.preparation_set_id == frozen.PREPARATION_SET_ID
    assert spec.evidence_directory == frozen.EVIDENCE_DIRECTORY
    assert spec.research_mode is True


def test_the_committed_config_publishes_no_statistic_and_exports_no_score() -> None:
    document = _document()
    assert document["reporting"] == {
        "operational_summary": True,
        "biometric_metrics": False,
        "score_statistics": False,
        "score_export": False,
    }


# ----------------------------------------------------------- what is refused


def test_an_unknown_top_level_key_is_refused(tmp_path: Path) -> None:
    _refuses(
        tmp_path,
        lambda document: document.update({"notes": "harmless"}),
        because="an unknown key means the document says something nobody reads",
    )


def test_an_unknown_nested_key_is_refused(tmp_path: Path) -> None:
    _refuses(
        tmp_path,
        lambda document: document["expected"].update({"pairs_per_finger": 12}),
        because="an unknown nested key is the same defect one level down",
    )


@pytest.mark.parametrize(
    "key",
    sorted(frozen.FORBIDDEN_CONFIG_KEYS - {"score_statistics"}),
)
def test_a_threshold_shaped_key_is_refused_at_the_top_level(
    tmp_path: Path, key: str
) -> None:
    _refuses(
        tmp_path,
        lambda document, key=key: document.update({key: 0.5}),
        because=f"{key} would make Stage 8C a decision stage",
    )


@pytest.mark.parametrize(
    "key",
    sorted(frozen.FORBIDDEN_CONFIG_KEYS - {"score_statistics"}),
)
def test_a_threshold_shaped_key_is_refused_at_any_depth(
    tmp_path: Path, key: str
) -> None:
    _refuses(
        tmp_path,
        lambda document, key=key: document["expected"].update({key: 0.5}),
        because=f"{key} nested three levels down is still a threshold",
    )


def test_a_threshold_shaped_key_is_refused_inside_a_list(tmp_path: Path) -> None:
    def mutate(document: dict[str, Any]) -> None:
        document["expected"]["releases"] = [
            "SD300A",
            {"threshold": 40},
            "SD300B",
            "SD300C",
        ]

    _refuses(tmp_path, mutate, because="a list is not a hiding place")


def test_score_statistics_is_refused_anywhere_but_its_own_switch(
    tmp_path: Path,
) -> None:
    _refuses(
        tmp_path,
        lambda document: document["expected"].update({"score_statistics": False}),
        because="the one exception is reporting.score_statistics and nowhere else",
    )


@pytest.mark.parametrize(
    "key, wrong",
    [
        ("operational_summary", False),
        ("biometric_metrics", True),
        ("score_statistics", True),
        ("score_export", True),
    ],
)
def test_each_reporting_switch_has_exactly_one_permitted_value(
    tmp_path: Path, key: str, wrong: bool
) -> None:
    _refuses(
        tmp_path,
        lambda document, key=key, wrong=wrong: document["reporting"].update({key: wrong}),
        because=f"reporting.{key} may not be {wrong}",
    )


def test_a_missing_reporting_switch_is_refused(tmp_path: Path) -> None:
    _refuses(
        tmp_path,
        lambda document: document["reporting"].pop("score_export"),
        because="a switch that is absent is a switch nobody set",
    )


def test_parallel_execution_is_refused(tmp_path: Path) -> None:
    _refuses(
        tmp_path,
        lambda document: document["execution"].update({"sequential": False}),
        because="two workers would double peak RAM and reorder results",
    )


def test_more_than_one_worker_is_refused(tmp_path: Path) -> None:
    _refuses(
        tmp_path,
        lambda document: document["execution"].update({"max_workers": 2}),
        because="spec section 11 pins max_workers to 1",
    )


def test_a_retry_count_above_zero_is_refused(tmp_path: Path) -> None:
    _refuses(
        tmp_path,
        lambda document: document["execution"].update({"retries": 1}),
        because="a failed comparison is a recorded outcome, not a retry",
    )


def test_a_job_deadline_the_profile_disagrees_with_is_refused(tmp_path: Path) -> None:
    _refuses(
        tmp_path,
        lambda document: document["execution"].update({"job_deadline_seconds": 600}),
        because="two files may not disagree about the budget a comparison ran under",
    )


def test_another_execution_profile_is_refused(tmp_path: Path) -> None:
    def mutate(document: dict[str, Any]) -> None:
        document["execution"]["profile_config"] = (
            "configs/execution/canonical_500_lanczos3_60s_v1.yaml"
        )
        document["execution"]["profile_id"] = "canonical_500_lanczos3_60s_v1"

    _refuses(
        tmp_path,
        mutate,
        because="Stage 8C runs under its own profile, and only under that one",
    )


def test_creating_a_prepared_image_set_is_refused(tmp_path: Path) -> None:
    _refuses(
        tmp_path,
        lambda document: document["runtime"].update(
            {"image_materialization_policy": "materialize_new_prepared_images"}
        ),
        because="Stage 8C creates no PreparedImageSet",
    )


@pytest.mark.parametrize(
    "section, key, wrong",
    [
        ("stage8b", "finalization_fingerprint", "0" * 64),
        ("stage8b", "outcome", "FLX_CONTRACT_FAILED"),
        ("stage8b", "adapter_id", "flx_pytorch_inprocess"),
        ("stage8b", "adapter_version", 2),
        ("stage8b", "runtime_manifest_fingerprint", "1" * 64),
        ("stage8b", "score_profile_fingerprint", "2" * 64),
        ("stage8b", "adapter_profile_fingerprint", "3" * 64),
        ("artifact", "checkpoint_sha256", "4" * 64),
        ("artifact", "source_archive_sha256", "5" * 64),
        ("artifact", "checkpoint_size_bytes", 875770139),
        ("reference", "run_id", "run_000000000000"),
        ("reference", "pair_manifest_hash", "6" * 64),
        ("preparation", "set_fingerprint", "7" * 64),
        ("preparation", "transform_profile_fingerprint", "8" * 64),
        ("preparation", "transform_runtime_fingerprint", "9" * 64),
    ],
)
def test_a_wrong_frozen_identity_is_refused(
    tmp_path: Path, section: str, key: str, wrong: Any
) -> None:
    _refuses(
        tmp_path,
        lambda document, section=section, key=key, wrong=wrong: document[section].update(
            {key: wrong}
        ),
        because=f"{section}.{key} is frozen and may not be edited",
    )


def test_a_wrong_pair_count_is_refused(tmp_path: Path) -> None:
    _refuses(
        tmp_path,
        lambda document: document["expected"].update({"jobs": 5999}),
        because="Stage 8C is exactly 6,000 pairs",
    )


def test_a_wrong_prepared_entry_count_is_refused(tmp_path: Path) -> None:
    _refuses(
        tmp_path,
        lambda document: document["expected"].update({"participating_images": 2999}),
        because="Stage 8C is exactly 3,000 prepared entries",
    )


def test_a_wrong_release_list_is_refused(tmp_path: Path) -> None:
    _refuses(
        tmp_path,
        lambda document: document["expected"].update({"releases": ["SD300A", "SD300B"]}),
        because="Stage 8C covers all three releases",
    )


def test_one_extraction_per_comparison_is_refused(tmp_path: Path) -> None:
    # spec section 35: SELF must not take a shortcut, and neither must anything
    # else. Two independent sides, always.
    _refuses(
        tmp_path,
        lambda document: document["operations"].update(
            {"logical_extractions_per_comparison": 1}
        ),
        because="both sides of every comparison are extracted independently",
    )


def test_a_batch_rule_the_qualified_route_does_not_use_is_refused(
    tmp_path: Path,
) -> None:
    _refuses(
        tmp_path,
        lambda document: document["operations"].update(
            {"inference_batch_rule": "single_row"}
        ),
        because="the batch rule is Stage 8B's, not Stage 8C's to choose",
    )


def test_a_truncated_digest_is_refused(tmp_path: Path) -> None:
    _refuses(
        tmp_path,
        lambda document: document["stage8b"].update(
            {"finalization_fingerprint": frozen.STAGE8B_FINALIZATION_FINGERPRINT[:32]}
        ),
        because="a fingerprint is 64 hexadecimal characters or it is not one",
    )


def test_a_missing_config_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError):
        load_flx_canonical500_config(tmp_path / "absent.yaml")


def test_a_config_that_is_not_a_mapping_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "list.yaml"
    path.write_text("- one\n- two\n", encoding="utf-8")
    with pytest.raises(ConfigurationError):
        load_flx_canonical500_config(path)


def test_the_loader_does_not_mutate_the_document_it_read() -> None:
    before = _document()
    load_flx_canonical500_config()
    assert _document() == before
    assert copy.deepcopy(before) == before
