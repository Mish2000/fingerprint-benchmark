"""Stage 8C against the real workspace, before a single comparison is run.

Everything here needs the SD300 dataset, the materialised 500 ppi input set and
the finished SourceAFIS canonical chain. The flx runtime bundle is needed only
by the artifact check, which is marked separately, so the alignment half can be
run on a machine that has the dataset and not the 2 GB bundle.

Nothing here executes a comparison, and nothing here writes to the workspace.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from fpbench.core.errors import ResearchPreflightError
from fpbench.experiments import stage8c_identity as frozen
from fpbench.experiments.algorithm_research import REPOSITORY_ROOT
from fpbench.experiments.flx_canonical500_full import (
    DEFAULT_WORKSPACE,
    load_flx_canonical500_config,
    verify_flx_canonical500_alignment,
)

pytestmark = [pytest.mark.stage8c_full_run, pytest.mark.dataset]


@pytest.fixture(scope="module")
def workspace() -> Path:
    path = Path(os.environ.get("FPBENCH_WORKSPACE", DEFAULT_WORKSPACE))
    if not (path / "results" / frozen.REFERENCE_RUN_ID).is_dir():
        pytest.skip(f"no canonical reference run in {path}")
    return path


@pytest.fixture(scope="module")
def config():
    return load_flx_canonical500_config()


@pytest.fixture(scope="module")
def alignment(workspace: Path, config):
    return verify_flx_canonical500_alignment(
        workspace=workspace, config=config, require_clean=False
    )


def test_the_alignment_is_clean_before_a_run_exists(alignment) -> None:
    assert alignment.is_clean, [issue.message for issue in alignment.issues]


def test_every_pair_matches_record_by_record(alignment) -> None:
    # Not counts against counts: six fields of every one of the 6,000 pairs,
    # compared positionally in the plan's order (spec section 6).
    assert alignment.reference_pair_count == 6000
    assert alignment.candidate_pair_count == 6000
    assert alignment.equal_pair_ids == 6000
    assert alignment.equal_pair_semantics == 6000


def test_every_prepared_entry_matches_record_by_record(alignment) -> None:
    assert alignment.reference_prepared_entries == 3000
    assert alignment.candidate_prepared_entries == 3000
    assert alignment.equal_prepared_entries == 3000


def test_the_alignment_names_the_reference_chain(alignment) -> None:
    assert alignment.reference_run_id == frozen.REFERENCE_RUN_ID
    assert alignment.reference_plan_id == frozen.REFERENCE_PLAN_ID
    assert alignment.reference_result_set_id == frozen.REFERENCE_RESULT_SET_ID
    assert alignment.pair_manifest_hash == frozen.REFERENCE_PAIR_MANIFEST_HASH
    assert alignment.preparation_set_id == frozen.PREPARATION_SET_ID


def test_no_run_exists_yet_so_the_candidate_side_is_the_manifest(alignment) -> None:
    assert alignment.candidate_run_id is None
    assert alignment.candidate_plan_id is None


def test_the_alignment_is_the_same_digest_twice(workspace: Path, config) -> None:
    first = verify_flx_canonical500_alignment(
        workspace=workspace, config=config, require_clean=True
    )
    second = verify_flx_canonical500_alignment(
        workspace=workspace, config=config, require_clean=True
    )
    assert first.alignment_fingerprint == second.alignment_fingerprint


def test_a_pair_manifest_hash_the_experiment_does_not_name_stops_everything(
    workspace: Path, config
) -> None:
    from dataclasses import replace

    hijacked = replace(config, reference_pair_manifest_hash="0" * 64)
    with pytest.raises(ResearchPreflightError, match="pair manifest"):
        verify_flx_canonical500_alignment(
            workspace=workspace, config=hijacked, require_clean=False
        )


def test_a_cohort_the_experiment_does_not_name_stops_everything(
    workspace: Path, config
) -> None:
    from dataclasses import replace

    hijacked = replace(config, reference_cohort_id="sd300_50_subjects_test_000000000000")
    with pytest.raises(ResearchPreflightError, match="cohort"):
        verify_flx_canonical500_alignment(
            workspace=workspace, config=hijacked, require_clean=False
        )


def test_a_transform_runtime_the_experiment_does_not_name_stops_everything(
    workspace: Path, config
) -> None:
    from dataclasses import replace

    hijacked = replace(config, transform_runtime_fingerprint="1" * 64)
    with pytest.raises(ResearchPreflightError, match="transform runtime"):
        verify_flx_canonical500_alignment(
            workspace=workspace, config=hijacked, require_clean=False
        )


def test_a_workspace_with_no_pair_manifest_is_an_error_not_an_invitation(
    tmp_path: Path, config
) -> None:
    """``allow_creation=False``: nothing here builds a manifest (spec section 21)."""
    with pytest.raises(Exception) as caught:
        verify_flx_canonical500_alignment(
            workspace=tmp_path, config=config, require_clean=False
        )
    assert "create" not in str(caught.value).lower() or "not" in str(caught.value).lower()


@pytest.mark.flx_runtime
def test_the_pinned_runtime_bundle_verifies_in_full(workspace: Path, config) -> None:
    """The archive, the six source files and all 875,770,140 checkpoint bytes.

    Skipped where the bundle is *absent*, and only there. The module guards on
    the reference run, but ``stage8c_full_run`` promises three things — the
    dataset, the pinned flx bundle and the finished SourceAFIS chain — and a
    machine can easily have the run without the 2.06 GB bundle, which is the
    case on the Windows side of this project where the bundle lives in WSL.

    A bundle that is present and *wrong* still fails, which is the whole point
    of the test: absence is not applicability, a mismatch is a finding.
    """
    from fpbench.flx.artifacts import FlxRuntimeBundle

    bundle = FlxRuntimeBundle.from_environment()
    if not bundle.root.is_dir():
        pytest.skip(
            "the pinned flx runtime bundle is not on this machine; set "
            "FPBENCH_FLX_BUNDLE"
        )

    from fpbench.experiments.flx_canonical500_full import preflight_flx_canonical500_run

    findings = preflight_flx_canonical500_run(
        workspace=workspace, config=config, require_clean_tree=False
    )
    assert findings["stage8b_outcome"] == frozen.STAGE8B_OUTCOME
    assert findings["artifacts"]["checkpoint_sha256"] == frozen.CHECKPOINT_SHA256
    assert findings["artifacts"]["checkpoint_size_bytes"] == frozen.CHECKPOINT_SIZE_BYTES
    assert findings["artifacts"]["source_files_verified"] == 6
    assert findings["pairs"] == 6000
    assert findings["prepared_entries"] == 3000
    assert findings["planned_operations"] == {
        "preprocess_calls": 12_000,
        "logical_extraction_calls": 12_000,
        "physical_forward_rows": 24_000,
        "comparison_calls": 6_000,
    }


def test_the_repository_root_is_where_this_test_thinks_it_is() -> None:
    assert (REPOSITORY_ROOT / "configs" / "experiments").is_dir()
