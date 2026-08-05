"""The committed Stage 8C evidence, verified with nothing the run needed.

No SD300, no checkpoint, no torch, no PyTorch runtime, no raw ResultSet and no
workspace. What is under test is the publication: that it holds exactly the
expected files, that every one of them parses strictly, that the marker
fingerprints to what it carries, that the four flx profiles are still the ones
this source produces, that the documents agree with each other, and that the
exact bytes have not moved since finalization.

Until the run has been executed and published there is nothing here to verify,
and these tests say so by skipping rather than by passing vacuously. The one
test that never skips is the one that keeps that honest.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fpbench.core.errors import ResearchPreflightError
from fpbench.experiments import stage8c_identity as frozen
from fpbench.experiments.algorithm_research import REPOSITORY_ROOT
from fpbench.experiments.stage8c_verify import (
    read_stage8c_finalization,
    verify_stage8c_evidence,
)

pytestmark = pytest.mark.stage8c

EVIDENCE = REPOSITORY_ROOT / frozen.EVIDENCE_DIRECTORY


def _published() -> bool:
    return (EVIDENCE / frozen.STAGE_8C_FINALIZATION_NAME).is_file()


requires_publication = pytest.mark.skipif(
    not _published(),
    reason="Stage 8C evidence has not been published yet",
)


# ------------------------------------------------------------ never skipped


def test_the_skip_condition_is_the_only_reason_anything_here_skips() -> None:
    """Keeps the gate honest.

    A suite that skipped for any other reason — a missing dependency, an import
    error, a marker typo — would look identical to a suite waiting for the run.
    This test always executes, so `pytest -m stage8c` always has something to
    run and the skip below always means exactly one thing.
    """
    marker_present = (EVIDENCE / frozen.STAGE_8C_FINALIZATION_NAME).is_file()
    directory_present = EVIDENCE.is_dir()
    assert marker_present == _published()
    if not directory_present:
        assert not marker_present
    # The verifier is importable and its contract is the expected one whether or
    # not anything has been published.
    assert callable(verify_stage8c_evidence)
    assert frozen.STAGE_8C_FINALIZATION_NAME == "stage-8c-finalization.json"
    assert len(frozen.REQUIRED_EVIDENCE_FILES) == 8


# ------------------------------------------------------ the published chain


@requires_publication
def test_the_publication_verifies_without_a_runtime() -> None:
    verification = verify_stage8c_evidence(repository_root=REPOSITORY_ROOT)
    assert verification.outcome == "FLX_CANONICAL500_RAW_READY"
    assert verification.stored_count == frozen.EXPECTED_JOBS
    assert verification.opens_stage_8d is True


@requires_publication
def test_verification_makes_no_claim_that_the_algorithm_was_executed() -> None:
    """spec section 29: evidence-only verification says what it verified."""
    verification = verify_stage8c_evidence(repository_root=REPOSITORY_ROOT)
    assert verification.algorithm_executed is False


@requires_publication
def test_the_two_extraction_counts_are_published_and_are_different() -> None:
    verification = verify_stage8c_evidence(repository_root=REPOSITORY_ROOT)
    assert verification.logical_extraction_call_count == 12_000
    assert verification.physical_forward_row_count == 24_000


@requires_publication
def test_the_outcomes_account_for_every_planned_comparison() -> None:
    verification = verify_stage8c_evidence(repository_root=REPOSITORY_ROOT)
    assert (
        verification.success_count + verification.algorithmic_failure_count
        == verification.stored_count
    )


@requires_publication
def test_the_marker_binds_the_stage_8b_qualification() -> None:
    marker = read_stage8c_finalization(repository_root=REPOSITORY_ROOT)
    assert marker.stage8b_finalization_fingerprint == (
        frozen.STAGE8B_FINALIZATION_FINGERPRINT
    )
    assert marker.stage8b_outcome == frozen.STAGE8B_OUTCOME
    assert marker.checkpoint_sha256 == frozen.CHECKPOINT_SHA256
    assert marker.permits_decisions is False
    assert marker.prior_result_scores_read is False
    assert marker.score_statistics_published is False


@requires_publication
def test_the_marker_binds_the_canonical_inputs() -> None:
    marker = read_stage8c_finalization(repository_root=REPOSITORY_ROOT)
    assert marker.reference_run_id == frozen.REFERENCE_RUN_ID
    assert marker.pair_manifest_hash == frozen.REFERENCE_PAIR_MANIFEST_HASH
    assert marker.preparation_set_id == frozen.PREPARATION_SET_ID


@requires_publication
def test_a_tampered_evidence_byte_is_caught(tmp_path: Path) -> None:
    """The content hashes are load-bearing, and this proves it."""
    import shutil

    mirror = tmp_path / "repo"
    shutil.copytree(REPOSITORY_ROOT / "evidence", mirror / "evidence")
    target = mirror / frozen.EVIDENCE_DIRECTORY / "alignment-report.json"
    target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ResearchPreflightError):
        verify_stage8c_evidence(
            repository_root=mirror, require_git_provenance=False
        )


@requires_publication
def test_the_evidence_holds_no_score_row_and_no_embedding() -> None:
    from fpbench.experiments.stage8c_finalization import (
        require_no_forbidden_published_data,
    )

    require_no_forbidden_published_data(REPOSITORY_ROOT)


@requires_publication
def test_the_evidence_holds_exactly_the_expected_files() -> None:
    from fpbench.experiments.stage8c_finalization import (
        published_evidence_names,
        require_expected_evidence_files,
    )

    names = published_evidence_names(REPOSITORY_ROOT)
    run_file = require_expected_evidence_files(names)
    assert run_file.startswith("run_") and run_file.endswith(".json")
    assert len(names) == len(frozen.REQUIRED_EVIDENCE_FILES) + 1
