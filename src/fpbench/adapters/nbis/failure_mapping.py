"""One table, one place: what each way this route can fail is recorded as.

Everything a reader needs in order to answer "why was this comparison recorded as
``template_extraction_failed``?" is below. A mapping spread over three modules is
a mapping nobody can review (spec section 30).

**Order of precedence.** Checked in this order, and the first one that applies
wins:

1. the comparison ran out of its budget      -> ``TIMEOUT``
2. the tool could not be started at all      -> ``DEPENDENCY_MISSING``
3. the process died on a signal or crashed   -> ``PROCESS_CRASHED``
4. it exited non-zero, ordinarily            -> per tool, below
5. it exited zero and wrote no output        -> ``TEMPLATE_EXTRACTION_FAILED``
6. it exited zero and wrote unusable output  -> ``TEMPLATE_EXTRACTION_FAILED``
7. it exited zero and printed no score       -> ``NO_SCORE``

The order matters because the cases overlap. A tool killed at its deadline also
has a non-zero exit status; recording that as a matching failure would turn a
harness problem into a biometric-looking one.

**A crash is not an exit code.** MINDTCT exiting 1 because it declined a print is
an outcome; MINDTCT dying on SIGSEGV is a defect, and the two must not share a
code. On POSIX a signal is reported as a negative status, and on Windows an
unhandled exception surfaces as a status far outside the 0..255 an ordinary
program returns; both are treated as crashes.

**No failure ever becomes a score.** Every path here returns a ``FailureInfo`` and
the adapter returns ``RawMatchResult.failed()``; none of them invents 0, -1 or NaN
to stand in for "did not work". In particular BOZORTH3 printing ``0`` is a
*success* and never reaches this module (docs/adr/0006, spec sections 25 and 26).

**Nothing here carries a path.** Not the input, not the build, not the workspace,
and certainly not a subject, a finger or a pair — the adapter has none of those
and a message that named one would mean it had been given something the contract
withholds. What is kept is the tool, the stage, the exit code and a short kind:
four safe strings (spec section 30).
"""

from __future__ import annotations

from typing import Mapping

from fpbench.core.enums import FailureCode, FailureStage
from fpbench.core.execution_models import FailureInfo

__all__ = [
    "MINDTCT_TOOL",
    "BOZORTH3_TOOL",
    "EXTRACTION_STAGE",
    "MATCHING_STAGE",
    "is_process_crash",
    "timeout_failure",
    "launch_failure",
    "crash_failure",
    "extraction_exit_failure",
    "invalid_extractor_output_failure",
    "matching_exit_failure",
    "no_score_failure",
    "input_rejected_failure",
]

MINDTCT_TOOL = "mindtct"
BOZORTH3_TOOL = "bozorth3"

#: Stage labels used in ``details``. Deliberately not the side — "left" and
#: "right" are safe, but they belong in the side field of the extraction
#: failures, not in a stage name.
EXTRACTION_STAGE = "extraction"
MATCHING_STAGE = "matching"

#: The largest status an ordinary program returns. Anything above it on Windows
#: is an unhandled structured exception rather than a considered exit.
_MAX_ORDINARY_EXIT = 255


def is_process_crash(exit_code: int | None) -> bool:
    """Did the process die, as opposed to deciding to stop?"""
    if exit_code is None:
        return False
    return exit_code < 0 or exit_code > _MAX_ORDINARY_EXIT


def timeout_failure(*, tool: str, stage: str) -> FailureInfo:
    """The comparison's shared budget ran out while this tool held it.

    One budget covers staging, both extractions and the match, so a timeout is a
    fact about the comparison rather than about the stage that happened to be
    running — which is why the code and the stage are both ``TIMEOUT``
    (spec sections 29 and 30).
    """
    return FailureInfo(
        code=FailureCode.TIMEOUT,
        stage=FailureStage.TIMEOUT,
        message=f"the comparison exceeded its budget during {stage}",
        retryable=True,
        details=_details(tool=tool, stage=stage, output_kind="timed_out"),
    )


def launch_failure(*, tool: str, stage: str, detail: str = "") -> FailureInfo:
    """The tool could not be started at all.

    Distinct from a crash: nothing ran, so this is the environment rather than
    the comparison. Preflight normally catches it; this is the case where an
    executable disappeared after preflight approved it.
    """
    return FailureInfo(
        code=FailureCode.DEPENDENCY_MISSING,
        stage=FailureStage.ENVIRONMENT,
        message=f"{tool} could not be started",
        retryable=False,
        details=_details(
            tool=tool, stage=stage, output_kind="launch_failed", detail=detail
        ),
    )


def crash_failure(*, tool: str, stage: str, exit_code: int) -> FailureInfo:
    """The process died on a signal or an unhandled fault."""
    return FailureInfo(
        code=FailureCode.PROCESS_CRASHED,
        stage=(
            FailureStage.EXTRACTION if stage == EXTRACTION_STAGE else FailureStage.MATCHING
        ),
        message=f"{tool} did not exit normally",
        retryable=False,
        details=_details(
            tool=tool, stage=stage, exit_code=exit_code, output_kind="process_crashed"
        ),
    )


def extraction_exit_failure(*, side: str, exit_code: int) -> FailureInfo:
    """MINDTCT exited non-zero, ordinarily.

    Recorded as an extraction failure because that is what it is: NBIS looked at
    the print and produced no template. A real property of real fingerprints, kept
    and counted rather than hidden (docs/adr/0013).
    """
    return FailureInfo(
        code=FailureCode.TEMPLATE_EXTRACTION_FAILED,
        stage=FailureStage.EXTRACTION,
        message=f"mindtct produced no template for the {side} side",
        retryable=False,
        details=_details(
            tool=MINDTCT_TOOL,
            stage=EXTRACTION_STAGE,
            exit_code=exit_code,
            output_kind="nonzero_exit",
            side=side,
        ),
    )


def invalid_extractor_output_failure(*, side: str, kind: str) -> FailureInfo:
    """MINDTCT claimed success and wrote no usable XYT.

    Step 5 and 6 of the precedence order. The exit code says nothing here, so the
    output decides. ``output_kind`` is ``invalid_extractor_output``, and the
    validator treats *that* as broken infrastructure rather than as NBIS
    declining a print — the two are the same failure code and they are not the
    same event (spec sections 30 and 36).
    """
    return FailureInfo(
        code=FailureCode.TEMPLATE_EXTRACTION_FAILED,
        stage=FailureStage.EXTRACTION,
        message=f"mindtct wrote no usable template for the {side} side",
        retryable=False,
        details=_details(
            tool=MINDTCT_TOOL,
            stage=EXTRACTION_STAGE,
            output_kind="invalid_extractor_output",
            side=side,
            reason=kind,
        ),
    )


def matching_exit_failure(*, exit_code: int) -> FailureInfo:
    """BOZORTH3 exited non-zero, ordinarily."""
    return FailureInfo(
        code=FailureCode.MATCHING_FAILED,
        stage=FailureStage.MATCHING,
        message="bozorth3 produced no comparison",
        retryable=False,
        details=_details(
            tool=BOZORTH3_TOOL,
            stage=MATCHING_STAGE,
            exit_code=exit_code,
            output_kind="nonzero_exit",
        ),
    )


def no_score_failure(*, detail: str) -> FailureInfo:
    """BOZORTH3 exited zero without printing exactly one non-negative integer.

    Never a zero score. A comparison that produced no number did not score badly;
    it did not score, and 0 is a number BOZORTH3 prints deliberately
    (docs/adr/0006, spec sections 26 and 28).
    """
    return FailureInfo(
        code=FailureCode.NO_SCORE,
        stage=FailureStage.MATCHING,
        message="bozorth3 exited successfully without printing one score",
        retryable=False,
        details=_details(
            tool=BOZORTH3_TOOL,
            stage=MATCHING_STAGE,
            output_kind="unparsable_score",
            reason=detail,
        ),
    )


def input_rejected_failure(*, side: str, reason: str) -> FailureInfo:
    """The prepared image is not this route's input, refused before any process.

    Recorded rather than raised: an image of the wrong shape is a fact about the
    input set and the run carries on. The one thing that is *not* recorded here is
    a file whose bytes changed after preflight, which the input check raises as
    drift instead (spec section 20).
    """
    return FailureInfo(
        code=FailureCode.INPUT_INVALID,
        stage=FailureStage.INPUT,
        message=f"the {side} input is not an 8-bit greyscale 500 ppi PNG",
        retryable=False,
        details=_details(
            tool="adapter",
            stage="input",
            output_kind="input_rejected",
            side=side,
            reason=reason,
        ),
    )


def _details(
    *,
    tool: str,
    stage: str,
    output_kind: str,
    exit_code: int | None = None,
    side: str | None = None,
    reason: str = "",
    detail: str = "",
) -> Mapping[str, str]:
    """Four safe strings, plus at most two more that are also safe.

    Every value here is either a fixed vocabulary word or a number. There is no
    path, no stderr excerpt and no free text from a tool: a tool's English can
    change between builds, and a detail nobody controls is a detail that ends up
    in six thousand stored rows.
    """
    payload = {"tool": tool, "stage": stage, "output_kind": output_kind}
    if exit_code is not None:
        payload["exit_code"] = str(exit_code)
    if side is not None:
        payload["side"] = side
    if reason:
        payload["reason"] = reason[:120]
    if detail:
        payload["detail"] = detail[:120]
    return payload
