"""The failure table, entry by entry (spec section 30).

Two properties are worth more than the individual rows.

The first is that **a crash and an exit code are different events**. MINDTCT
exiting 1 because it declined a print is data; MINDTCT dying on SIGSEGV is a
defect, and a mapping that gave them the same code would let a broken machine
look like a difficult dataset.

The second is that **no detail is free text**. Every value in a stored failure is
a fixed vocabulary word or a number: no path, no stderr excerpt, no subject and
no pair. A tool's English changes between builds, and a detail nobody controls is
a detail that ends up in six thousand rows.
"""

from __future__ import annotations

import pytest

from fpbench.adapters.nbis.failure_mapping import (
    BOZORTH3_TOOL,
    EXTRACTION_STAGE,
    MATCHING_STAGE,
    MINDTCT_TOOL,
    crash_failure,
    extraction_exit_failure,
    input_rejected_failure,
    invalid_extractor_output_failure,
    is_process_crash,
    launch_failure,
    matching_exit_failure,
    no_score_failure,
    timeout_failure,
)
from fpbench.core.enums import FailureCode, FailureStage

pytestmark = pytest.mark.nbis_contract

SAFE_DETAIL_KEYS = {"tool", "stage", "exit_code", "output_kind", "side", "reason", "detail"}


# ---------------------------------------------------------------- the table


@pytest.mark.parametrize("tool", [MINDTCT_TOOL, BOZORTH3_TOOL])
def test_a_timeout_is_a_timeout_whichever_tool_held_the_budget(tool):
    info = timeout_failure(tool=tool, stage=EXTRACTION_STAGE)
    assert info.code is FailureCode.TIMEOUT
    assert info.stage is FailureStage.TIMEOUT


def test_mindtct_crashing_is_a_crash_during_extraction():
    info = crash_failure(tool=MINDTCT_TOOL, stage=EXTRACTION_STAGE, exit_code=-11)
    assert info.code is FailureCode.PROCESS_CRASHED
    assert info.stage is FailureStage.EXTRACTION


def test_bozorth3_crashing_is_a_crash_during_matching():
    info = crash_failure(tool=BOZORTH3_TOOL, stage=MATCHING_STAGE, exit_code=-11)
    assert info.code is FailureCode.PROCESS_CRASHED
    assert info.stage is FailureStage.MATCHING


def test_an_ordinary_non_zero_mindtct_exit_is_an_extraction_failure():
    info = extraction_exit_failure(side="left", exit_code=1)
    assert info.code is FailureCode.TEMPLATE_EXTRACTION_FAILED
    assert info.stage is FailureStage.EXTRACTION
    assert info.details["output_kind"] == "nonzero_exit"


def test_a_successful_exit_with_unusable_output_is_also_an_extraction_failure():
    """Same code, different cause — and the cause is what the validator reads."""
    info = invalid_extractor_output_failure(side="right", kind="invalid_extractor_output")
    assert info.code is FailureCode.TEMPLATE_EXTRACTION_FAILED
    assert info.stage is FailureStage.EXTRACTION
    assert info.details["output_kind"] == "invalid_extractor_output"


def test_an_ordinary_non_zero_bozorth3_exit_is_a_matching_failure():
    info = matching_exit_failure(exit_code=1)
    assert info.code is FailureCode.MATCHING_FAILED
    assert info.stage is FailureStage.MATCHING


def test_a_successful_bozorth3_without_one_integer_is_no_score():
    info = no_score_failure(detail="printed 2 lines, expected one")
    assert info.code is FailureCode.NO_SCORE
    assert info.stage is FailureStage.MATCHING


def test_a_tool_that_could_not_start_is_a_missing_dependency():
    info = launch_failure(tool=MINDTCT_TOOL, stage=EXTRACTION_STAGE)
    assert info.code is FailureCode.DEPENDENCY_MISSING
    assert info.stage is FailureStage.ENVIRONMENT


def test_a_rejected_input_is_input_invalid():
    info = input_rejected_failure(side="left", reason="unsupported_colour_type")
    assert info.code is FailureCode.INPUT_INVALID
    assert info.stage is FailureStage.INPUT


# ------------------------------------------------------------------ crashes


@pytest.mark.parametrize("exit_code", [-11, -9, -6, 300, 3221225477])
def test_a_signal_or_an_out_of_range_status_is_a_crash(exit_code):
    assert is_process_crash(exit_code)


@pytest.mark.parametrize("exit_code", [0, 1, 2, 3, 127, 255, None])
def test_an_ordinary_status_is_not_a_crash(exit_code):
    assert not is_process_crash(exit_code)


# -------------------------------------------------------------- safe detail


@pytest.mark.parametrize(
    "info",
    [
        timeout_failure(tool=MINDTCT_TOOL, stage=EXTRACTION_STAGE),
        launch_failure(tool=BOZORTH3_TOOL, stage=MATCHING_STAGE, detail="OSError"),
        crash_failure(tool=MINDTCT_TOOL, stage=EXTRACTION_STAGE, exit_code=-11),
        extraction_exit_failure(side="left", exit_code=1),
        invalid_extractor_output_failure(side="left", kind="missing_extractor_output"),
        matching_exit_failure(exit_code=1),
        no_score_failure(detail="printed nothing"),
        input_rejected_failure(side="right", reason="unsupported_bit_depth"),
    ],
)
def test_every_failure_keeps_only_safe_keys(info):
    assert set(info.details) <= SAFE_DETAIL_KEYS


@pytest.mark.parametrize(
    "info",
    [
        timeout_failure(tool=MINDTCT_TOOL, stage=EXTRACTION_STAGE),
        crash_failure(tool=BOZORTH3_TOOL, stage=MATCHING_STAGE, exit_code=-11),
        extraction_exit_failure(side="left", exit_code=1),
        matching_exit_failure(exit_code=1),
        no_score_failure(detail="printed nothing"),
    ],
)
def test_no_failure_names_a_path_or_a_pair(info):
    rendered = " ".join([info.message, *info.details.values()]).lower()
    for forbidden in ("/", "\\", "subject", "finger", "pair", "sd300", "genuine"):
        assert forbidden not in rendered, rendered


def test_a_long_reason_is_truncated():
    info = no_score_failure(detail="x" * 5000)
    assert len(info.details["reason"]) <= 120


def test_no_failure_carries_a_score():
    """Section 30: a failure is never dressed up as a number."""
    for info in (
        matching_exit_failure(exit_code=1),
        no_score_failure(detail="printed nothing"),
        extraction_exit_failure(side="left", exit_code=1),
    ):
        assert "score" not in info.details
        assert "0" not in info.details.get("output_kind", "")
