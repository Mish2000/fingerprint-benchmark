"""The Stage 8C marker refuses to describe a run that did not happen.

Every invariant here is enforced at construction, so a marker that claims 5,999
stored outcomes for 6,000 planned jobs, or one blocking failure, or a decision
this stage is not allowed to permit, cannot be built at all — let alone
published.

Beside it: the boundary audit's allow and deny lists, the walker that refuses a
score row or an embedding anywhere in a published document, and the rules about
which files the evidence directory may hold.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fpbench.core.errors import ResearchPreflightError
from fpbench.experiments import stage8c_identity as frozen
from fpbench.experiments.stage8c_finalization import (
    STAGE_8C_BASELINE_COMMIT,
    Stage8CFinalization,
    alignment_report_content_hash,
    operational_summary_content_hash,
    published_evidence_names,
    require_expected_evidence_files,
    require_no_forbidden_published_data,
    stage_8c_finalization_fingerprint,
)

pytestmark = pytest.mark.stage8c_contract

_DIGEST = "a" * 64
_COMMIT = "b" * 40


def _claims(**changes) -> dict:
    claims = {
        "schema_version": "1",
        "kind": "stage_8c_finalization",
        "outcome": "FLX_CANONICAL500_RAW_READY",
        "stage8b_finalization_fingerprint": frozen.STAGE8B_FINALIZATION_FINGERPRINT,
        "stage8b_outcome": frozen.STAGE8B_OUTCOME,
        "algorithm_id": frozen.ALGORITHM_ID,
        "integration_id": frozen.INTEGRATION_ID,
        "integration_fingerprint": _DIGEST,
        "source_archive_sha256": frozen.SOURCE_ARCHIVE_SHA256,
        "checkpoint_sha256": frozen.CHECKPOINT_SHA256,
        "runtime_bundle_id": "runtime_000000000001",
        "runtime_bundle_fingerprint": _DIGEST,
        "runtime_manifest_fingerprint": frozen.RUNTIME_MANIFEST_FINGERPRINT,
        "preprocessing_profile_fingerprint": frozen.PREPROCESSING_PROFILE_FINGERPRINT,
        "representation_profile_fingerprint": frozen.REPRESENTATION_PROFILE_FINGERPRINT,
        "score_profile_fingerprint": frozen.SCORE_PROFILE_FINGERPRINT,
        "adapter_profile_fingerprint": frozen.ADAPTER_PROFILE_FINGERPRINT,
        "run_id": "run_000000000001",
        "run_fingerprint": _DIGEST,
        "plan_id": "plan_000000000001",
        "plan_fingerprint": _DIGEST,
        "result_set_id": "resultset_000000001",
        "result_set_fingerprint": _DIGEST,
        "completion_id": "completion_00000001",
        "completion_fingerprint": _DIGEST,
        "run_source_commit": _COMMIT,
        "run_source_tree_clean": True,
        "reference_run_id": frozen.REFERENCE_RUN_ID,
        "reference_plan_id": frozen.REFERENCE_PLAN_ID,
        "reference_result_set_id": frozen.REFERENCE_RESULT_SET_ID,
        "pair_manifest_hash": frozen.REFERENCE_PAIR_MANIFEST_HASH,
        "preparation_set_id": frozen.PREPARATION_SET_ID,
        "preparation_set_fingerprint": frozen.PREPARATION_SET_FINGERPRINT,
        "transform_profile_fingerprint": frozen.TRANSFORM_PROFILE_FINGERPRINT,
        "transform_runtime_fingerprint": frozen.TRANSFORM_RUNTIME_FINGERPRINT,
        "audit_fingerprint": _DIGEST,
        "algorithm_validation_fingerprint": _DIGEST,
        "research_receipt_fingerprint": _DIGEST,
        "research_receipt_content_hash": _DIGEST,
        "research_finalization_fingerprint": _DIGEST,
        "alignment_fingerprint": _DIGEST,
        "alignment_report_content_hash": _DIGEST,
        "operational_summary_fingerprint": _DIGEST,
        "operational_summary_content_hash": _DIGEST,
        "planned_count": 6000,
        "stored_count": 6000,
        "success_count": 5990,
        "algorithmic_failure_count": 10,
        "blocking_failure_count": 0,
        "preprocess_call_count": 11980,
        "logical_extraction_call_count": 11980,
        "physical_forward_row_count": 23960,
        "comparison_call_count": 5990,
        "permits_decisions": False,
        "opens_stage_8d": True,
        "prior_result_scores_read": False,
        "score_statistics_published": False,
        "evidence_content_hashes": {"README.md": _DIGEST},
        "verifier_source_commit": _COMMIT,
        "verifier_source_tree_clean": True,
    }
    claims.update(changes)
    return claims


def _marker(**changes) -> Stage8CFinalization:
    claims = _claims(**changes)
    return Stage8CFinalization(
        **claims,
        stage_8c_finalization_fingerprint=stage_8c_finalization_fingerprint(claims),
        created_utc="2026-08-05T00:00:00+00:00",
    )


# ------------------------------------------------------------- the marker


def test_a_complete_marker_can_be_built() -> None:
    marker = _marker()
    assert marker.outcome == "FLX_CANONICAL500_RAW_READY"
    assert marker.stored_count == 6000
    assert marker.opens_stage_8d is True
    assert marker.permits_decisions is False


def test_the_fingerprint_excludes_its_own_identity_and_the_wall_clock() -> None:
    first = _marker()
    second = Stage8CFinalization(
        **_claims(),
        stage_8c_finalization_fingerprint=first.stage_8c_finalization_fingerprint,
        created_utc="2027-01-01T12:00:00+00:00",
    )
    assert first.stage_8c_finalization_fingerprint == (
        second.stage_8c_finalization_fingerprint
    )


def test_an_edited_count_no_longer_fingerprints_to_what_it_carries() -> None:
    claims = _claims()
    honest = stage_8c_finalization_fingerprint(claims)
    with pytest.raises(ValueError, match="does not cover"):
        Stage8CFinalization(
            **_claims(success_count=5991, algorithmic_failure_count=9),
            stage_8c_finalization_fingerprint=honest,
            created_utc="2026-08-05T00:00:00+00:00",
        )


def test_an_incomplete_run_cannot_be_finalised() -> None:
    with pytest.raises(ValueError, match="stored outcomes"):
        _marker(stored_count=5999)


def test_outcomes_that_do_not_add_up_are_refused() -> None:
    with pytest.raises(ValueError, match="do not add up"):
        _marker(success_count=5990, algorithmic_failure_count=9)


def test_a_blocking_failure_cannot_be_finalised() -> None:
    with pytest.raises(ValueError, match="zero blocking failures"):
        _marker(
            blocking_failure_count=1,
            success_count=5989,
            algorithmic_failure_count=11,
        )


def test_the_two_extraction_counts_must_stay_different_numbers() -> None:
    # docs/adr/0075: conflating them is the error this check exists for.
    with pytest.raises(ValueError, match="twice the logical extractions"):
        _marker(physical_forward_row_count=11980)


@pytest.mark.parametrize(
    "field, wrong, message",
    [
        ("permits_decisions", True, "permits no decision"),
        ("opens_stage_8d", False, "opens Stage 8D"),
        ("prior_result_scores_read", True, "no prior algorithm"),
        ("score_statistics_published", True, "no score statistic"),
        ("run_source_tree_clean", False, "clean tree"),
        ("verifier_source_tree_clean", False, "clean verifier tree"),
    ],
)
def test_a_limit_the_stage_may_not_relax_is_refused(field, wrong, message) -> None:
    with pytest.raises(ValueError, match=message):
        _marker(**{field: wrong})


def test_another_outcome_is_refused() -> None:
    with pytest.raises(ValueError, match="FLX_CANONICAL500_RAW_READY"):
        _marker(outcome="FLX_CANONICAL500_RAW_PARTIAL")


def test_a_truncated_commit_is_refused() -> None:
    with pytest.raises(ValueError, match="40-character commit"):
        _marker(verifier_source_commit="abc123")


def test_a_truncated_digest_is_refused() -> None:
    with pytest.raises(ValueError, match="64-character"):
        _marker(run_fingerprint="abc123")


def test_the_baseline_is_the_approved_head_that_closed_stage_8b() -> None:
    assert STAGE_8C_BASELINE_COMMIT == "755d13f929c280d4079b50374c6974e44468e174"


# ------------------------------------------------------ the content hashes


def test_a_content_hash_covers_the_whole_stored_document() -> None:
    report = {"alignment_fingerprint": _DIGEST, "inspected_utc": "2026-08-05T00:00:00Z"}
    same = dict(report)
    edited = dict(report, inspected_utc="2026-08-06T00:00:00Z")
    assert alignment_report_content_hash(report) == alignment_report_content_hash(same)
    assert alignment_report_content_hash(report) != alignment_report_content_hash(edited)


def test_the_summary_hash_and_the_alignment_hash_are_different_schemas() -> None:
    document = {"a": 1}
    assert alignment_report_content_hash(document) != (
        operational_summary_content_hash(document)
    )


# --------------------------------------------------- the published evidence


def _publish(directory: Path, *, extra: dict | None = None, run_id: str = "run_000000000001"):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "README.md").write_text("# Stage 8C\n", encoding="utf-8")
    for name in frozen.REQUIRED_EVIDENCE_FILES:
        if name.endswith(".json"):
            (directory / name).write_text("{}", encoding="utf-8")
    (directory / f"{run_id}.json").write_text("{}", encoding="utf-8")
    for name, payload in (extra or {}).items():
        (directory / name).write_text(json.dumps(payload), encoding="utf-8")


def test_the_expected_file_set_is_accepted(tmp_path: Path) -> None:
    directory = tmp_path / "evidence" / "flx-canonical500-raw"
    _publish(directory)
    names = published_evidence_names(tmp_path)
    assert require_expected_evidence_files(names) == "run_000000000001.json"


def test_an_extra_published_file_is_refused(tmp_path: Path) -> None:
    directory = tmp_path / "evidence" / "flx-canonical500-raw"
    _publish(directory)
    (directory / "scratch-notes.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ResearchPreflightError, match="nothing accounts for"):
        require_expected_evidence_files(published_evidence_names(tmp_path))


def test_a_missing_published_file_is_refused(tmp_path: Path) -> None:
    directory = tmp_path / "evidence" / "flx-canonical500-raw"
    _publish(directory)
    (directory / "alignment-report.json").unlink()
    with pytest.raises(ResearchPreflightError, match="missing"):
        require_expected_evidence_files(published_evidence_names(tmp_path))


def test_two_run_documents_are_refused(tmp_path: Path) -> None:
    directory = tmp_path / "evidence" / "flx-canonical500-raw"
    _publish(directory)
    (directory / "run_000000000002.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ResearchPreflightError, match="exactly one"):
        require_expected_evidence_files(published_evidence_names(tmp_path))


def test_no_run_document_is_refused(tmp_path: Path) -> None:
    directory = tmp_path / "evidence" / "flx-canonical500-raw"
    _publish(directory)
    (directory / "run_000000000001.json").unlink()
    with pytest.raises(ResearchPreflightError, match="exactly one"):
        require_expected_evidence_files(published_evidence_names(tmp_path))


def test_a_symlink_in_the_evidence_directory_is_refused(tmp_path: Path) -> None:
    directory = tmp_path / "evidence" / "flx-canonical500-raw"
    _publish(directory)
    target = tmp_path / "elsewhere.json"
    target.write_text("{}", encoding="utf-8")
    try:
        (directory / "linked.json").symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("this platform will not create a symlink without privileges")
    with pytest.raises(ResearchPreflightError, match="may not be a link"):
        published_evidence_names(tmp_path)


def test_a_missing_evidence_directory_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ResearchPreflightError, match="no published"):
        published_evidence_names(tmp_path)


# ------------------------------------------------- forbidden published data


@pytest.mark.parametrize(
    "payload",
    [
        {"raw_score": 1.5},
        {"scores": [1.0, 2.0]},
        {"results": {"embedding": [0.1]}},
        {"a": {"b": {"c": {"representation_sha256": _DIGEST}}}},
        {"rows": [{"threshold": 40}]},
        {"summary": {"score_statistics": {"mean": 1.0}}},
        {"decision": "MATCH"},
        {"eligibility": True},
        {"flx.raw_score": 1.0},
        {"histogram": [1, 2, 3]},
        {"mean_score": 0.5},
    ],
)
def test_a_forbidden_key_at_any_depth_is_refused(tmp_path: Path, payload: dict) -> None:
    directory = tmp_path / "evidence" / "flx-canonical500-raw"
    _publish(directory, extra={"alignment-report.json": payload})
    with pytest.raises(ResearchPreflightError, match="forbidden data"):
        require_no_forbidden_published_data(tmp_path)


def test_ordinary_published_content_is_accepted(tmp_path: Path) -> None:
    directory = tmp_path / "evidence" / "flx-canonical500-raw"
    _publish(
        directory,
        extra={
            "operational-summary.json": {
                "stored_results": 6000,
                "success_count": 5990,
                "failure_counts": {"template_extraction_failed": 10},
                "algorithm_operations": {
                    "measured": {
                        "logical_extraction_calls": 11980,
                        "physical_forward_rows": 23960,
                    }
                },
            }
        },
    )
    require_no_forbidden_published_data(tmp_path)


def test_the_word_score_in_prose_is_not_a_forbidden_key(tmp_path: Path) -> None:
    """The walker reads keys, not text. A README sentence is not a score row."""
    directory = tmp_path / "evidence" / "flx-canonical500-raw"
    _publish(
        directory,
        extra={
            "runtime-provenance.json": {
                "statement": "this document carries no raw score and no threshold"
            }
        },
    )
    require_no_forbidden_published_data(tmp_path)
