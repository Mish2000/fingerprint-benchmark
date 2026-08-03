"""The Stage 7C marker makes alignment part of the completion authority."""

from __future__ import annotations

import dataclasses

import pytest

from fpbench.core.serialization import stable_hash
from fpbench.experiments.stage7c_finalization import (
    STAGE_7C_FINALIZATION_KIND,
    STAGE_7C_FINALIZATION_SCHEMA_VERSION,
    Stage7CFinalization,
    alignment_report_content_hash,
    stage_7c_finalization_fingerprint,
)


def digest(label: str) -> str:
    return stable_hash({"test": label}, length=64)


def marker(**overrides) -> Stage7CFinalization:
    claims = {
        "schema_version": STAGE_7C_FINALIZATION_SCHEMA_VERSION,
        "kind": STAGE_7C_FINALIZATION_KIND,
        "run_id": "run_111111111111",
        "run_fingerprint": digest("run"),
        "result_set_id": "resultset_111111111111",
        "result_set_fingerprint": digest("result-set"),
        "research_receipt_fingerprint": digest("research-receipt"),
        "research_receipt_content_hash": digest("research-receipt-content"),
        "research_finalization_fingerprint": digest("research-finalization"),
        "reference_run_id": "run_222222222222",
        "reference_plan_id": "plan_222222222222",
        "reference_result_set_id": "resultset_222222222222",
        "alignment_fingerprint": digest("alignment"),
        "alignment_report_content_hash": digest("alignment-content"),
        "verifier_source_commit": "a" * 40,
        "verifier_source_tree_clean": True,
    }
    claims.update(overrides)
    fingerprint = stage_7c_finalization_fingerprint(claims)
    return Stage7CFinalization(
        **claims,
        stage_7c_finalization_fingerprint=fingerprint,
        created_utc="2026-08-03T00:00:00+00:00",
    )


def test_the_complete_chain_builds_one_valid_marker():
    built = marker()
    assert built.stage_7c_finalization_fingerprint == (
        stage_7c_finalization_fingerprint(built)
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("alignment_fingerprint", digest("other-alignment")),
        ("alignment_report_content_hash", digest("other-alignment-content")),
        ("reference_run_id", "run_333333333333"),
        ("reference_plan_id", "plan_333333333333"),
        ("reference_result_set_id", "resultset_333333333333"),
        ("research_receipt_content_hash", digest("other-receipt-content")),
        ("research_finalization_fingerprint", digest("other-finalization")),
    ],
)
def test_every_alignment_and_research_link_changes_the_marker(field, value):
    first = marker()
    second = marker(**{field: value})
    assert second.stage_7c_finalization_fingerprint != (
        first.stage_7c_finalization_fingerprint
    )


def test_an_edited_marker_is_rejected_even_if_its_identity_is_left_in_place():
    built = marker()
    with pytest.raises(ValueError, match="does not cover"):
        dataclasses.replace(
            built, alignment_report_content_hash=digest("edited-content")
        )


def test_the_alignment_content_hash_covers_expectations_and_timestamp():
    report = {
        "alignment_fingerprint": digest("alignment"),
        "inspected_utc": "2026-08-03T00:00:00+00:00",
        "expectations": {"pair_count": 6000},
    }
    changed_expectations = {
        **report,
        "expectations": {"pair_count": 5999},
    }
    changed_timestamp = {
        **report,
        "inspected_utc": "2026-08-03T00:00:01+00:00",
    }
    assert alignment_report_content_hash(report) != alignment_report_content_hash(
        changed_expectations
    )
    assert alignment_report_content_hash(report) != alignment_report_content_hash(
        changed_timestamp
    )


def test_the_wall_clock_is_not_part_of_the_marker_identity():
    built = marker()
    later = dataclasses.replace(built, created_utc="2026-08-04T00:00:00+00:00")
    assert later.stage_7c_finalization_fingerprint == (
        built.stage_7c_finalization_fingerprint
    )
