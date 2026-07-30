"""Every bridge failure code lands on exactly one fpbench code and stage.

This is where two vocabularies meet, so each entry is asserted individually rather
than by iterating the table it is meant to be checking.
"""

from __future__ import annotations

import pytest

from fpbench.adapters.sourceafis_java.failure_mapping import (
    BRIDGE_FAILURE_MAP,
    MAX_STDERR_CHARS,
    contract_violation,
    map_bridge_failure,
    process_crash,
)
from fpbench.core.enums import FailureCode, FailureStage

pytestmark = pytest.mark.sourceafis


@pytest.mark.parametrize(
    "bridge_code,expected_code,expected_stage",
    [
        ("input_read_failed", FailureCode.INPUT_INVALID, FailureStage.INPUT),
        ("image_decode_failed", FailureCode.IMAGE_DECODE_FAILED, FailureStage.EXTRACTION),
        (
            "unsupported_resolution",
            FailureCode.UNSUPPORTED_RESOLUTION,
            FailureStage.EXTRACTION,
        ),
        (
            "template_extraction_failed",
            FailureCode.TEMPLATE_EXTRACTION_FAILED,
            FailureStage.EXTRACTION,
        ),
        ("matching_failed", FailureCode.MATCHING_FAILED, FailureStage.MATCHING),
    ],
)
def test_each_bridge_code_maps_exactly(bridge_code, expected_code, expected_stage):
    failure = map_bridge_failure(code=bridge_code, message="something went wrong")
    assert failure.code is expected_code
    assert failure.stage is expected_stage
    assert failure.details["bridge_code"] == bridge_code


def test_no_sourceafis_failure_is_retryable():
    """Re-running the same comparison would produce the same answer."""
    for code in BRIDGE_FAILURE_MAP:
        assert not map_bridge_failure(code=code, message="x").retryable


def test_the_side_is_recorded_when_the_bridge_names_one():
    failure = map_bridge_failure(
        code="image_decode_failed", message="undecodable", side="right"
    )
    assert failure.details["side"] == "right"


def test_the_bridge_stage_is_kept_for_triage():
    failure = map_bridge_failure(
        code="template_extraction_failed",
        message="no template",
        stage="left_extraction",
        exception_type="IllegalArgumentException",
    )
    assert failure.details["bridge_stage"] == "left_extraction"
    assert failure.details["exception_type"] == "IllegalArgumentException"


def test_an_unknown_bridge_code_is_a_contract_violation():
    """A code this adapter does not know means the two sides have drifted apart."""
    failure = map_bridge_failure(code="brand_new_code", message="?")
    assert failure.code is FailureCode.INTERNAL_ERROR
    assert failure.stage is FailureStage.ADAPTER
    assert failure.details["kind"] == "bridge_contract_violation"
    assert failure.details["bridge_code"] == "brand_new_code"


def test_a_contract_violation_is_labelled_as_one():
    failure = contract_violation("score was negative")
    assert failure.code is FailureCode.INTERNAL_ERROR
    assert failure.stage is FailureStage.ADAPTER
    assert failure.details["kind"] == "bridge_contract_violation"


def test_a_non_zero_exit_becomes_a_process_crash():
    failure = process_crash(exit_code=70, stderr="internal bridge error: boom")
    assert failure.code is FailureCode.PROCESS_CRASHED
    assert failure.stage is FailureStage.ADAPTER
    assert failure.details["exit_code"] == "70"
    assert "boom" in failure.details["stderr_excerpt"]


def test_a_stderr_excerpt_is_bounded():
    """A Java stack trace must not end up in every row of a run."""
    failure = process_crash(exit_code=70, stderr="x" * 5000)
    assert len(failure.details["stderr_excerpt"]) <= MAX_STDERR_CHARS


def test_a_stderr_excerpt_is_collapsed_to_one_line():
    failure = process_crash(exit_code=70, stderr="line one\n\tat Foo.bar(Foo.java:1)\n")
    excerpt = failure.details["stderr_excerpt"]
    assert "\n" not in excerpt and "\t" not in excerpt


def test_an_empty_stderr_is_omitted_rather_than_stored_blank():
    failure = process_crash(exit_code=64, stderr="   ")
    assert "stderr_excerpt" not in failure.details


def test_no_failure_carries_a_threshold_or_a_decision():
    failure = map_bridge_failure(code="matching_failed", message="x")
    forbidden = {"threshold", "decision", "is_match", "ground_truth"}
    assert forbidden.isdisjoint(failure.details)
