"""One table, one place: what each way the tools can fail is recorded as.

Every real adapter gets a file like this, because a failure mapping spread over
three modules is a mapping nobody can review. Everything a reader needs in order
to answer "why was this comparison recorded as ``matching_failed``?" is below
(spec section 75).

**Order of precedence** (spec section 76):

1. the tool's own structured code — here, its exit status;
2. the stage that was running when it happened;
3. a missing or unusable output file;
4. a pattern in stderr, and only as a last resort.

This mapping never reaches step 4. Both fixture tools report a distinct exit code
for their one biometric outcome, so a change to their English cannot silently
reclassify anything — which is precisely the property step 4 puts at risk.

**No failure ever becomes a score.** Every path here returns a ``FailureInfo``
and the adapter returns ``RawMatchResult.failed()``; none of them invents 0, -1
or NaN to stand in for "did not work" (docs/adr/0006, spec section 59).
"""

from __future__ import annotations

from typing import Mapping

from fpbench.core.enums import FailureCode, FailureStage
from fpbench.core.execution_models import FailureInfo

__all__ = [
    "EXTRACTOR_EXIT_CODES",
    "MATCHER_EXIT_CODES",
    "MAX_STDERR_CHARS",
    "extraction_failure",
    "matching_failure",
    "timeout_failure",
    "launch_failure",
    "no_score_failure",
    "missing_template_failure",
]

#: How much stderr is worth keeping: enough to identify what happened, not
#: enough for a tool's debug output to end up in every row of a run.
MAX_STDERR_CHARS = 400

#: The extractor's exit status -> what it means. ``3`` is the tool's own way of
#: saying "I looked at this print and produced no template", which is a
#: biometric outcome and not a defect (docs/adr/0013).
EXTRACTOR_EXIT_CODES: Mapping[int, tuple[FailureCode, FailureStage]] = {
    3: (FailureCode.TEMPLATE_EXTRACTION_FAILED, FailureStage.EXTRACTION),
    2: (FailureCode.INPUT_INVALID, FailureStage.INPUT),
}

#: The matcher's exit status -> what it means. ``4`` is "these two templates
#: share no comparable structure", which is also an outcome.
MATCHER_EXIT_CODES: Mapping[int, tuple[FailureCode, FailureStage]] = {
    4: (FailureCode.MATCHING_FAILED, FailureStage.MATCHING),
    2: (FailureCode.INPUT_INVALID, FailureStage.INPUT),
}


def extraction_failure(*, side: str, exit_code: int, stderr: str) -> FailureInfo:
    """The extractor exited non-zero.

    A code the table knows is that outcome; any other code is a crash, and a
    crash during extraction is a fault of the harness rather than of the print.
    """
    mapped = EXTRACTOR_EXIT_CODES.get(exit_code)
    if mapped is None:
        return FailureInfo(
            code=FailureCode.PROCESS_CRASHED,
            stage=FailureStage.ADAPTER,
            message=f"the extractor exited with code {exit_code}",
            retryable=False,
            details=_details(side=side, exit_code=exit_code, stderr=stderr),
        )
    code, stage = mapped
    return FailureInfo(
        code=code,
        stage=stage,
        message=f"the extractor produced no template for the {side} side",
        retryable=False,
        details=_details(side=side, exit_code=exit_code, stderr=stderr),
    )


def missing_template_failure(*, side: str) -> FailureInfo:
    """The extractor exited zero and produced nothing usable.

    Step 3 of the precedence order: the tool claimed success, so its exit code
    says nothing, but there is no template to match. Recorded as an extraction
    failure because that is what happened, not as an internal error.
    """
    return FailureInfo(
        code=FailureCode.TEMPLATE_EXTRACTION_FAILED,
        stage=FailureStage.EXTRACTION,
        message=f"the extractor wrote no usable template for the {side} side",
        retryable=False,
        details={"side": side, "reason": "template_missing_or_empty"},
    )


def matching_failure(*, exit_code: int, stderr: str) -> FailureInfo:
    """The matcher exited non-zero."""
    mapped = MATCHER_EXIT_CODES.get(exit_code)
    if mapped is None:
        return FailureInfo(
            code=FailureCode.PROCESS_CRASHED,
            stage=FailureStage.MATCHING,
            message=f"the matcher exited with code {exit_code}",
            retryable=False,
            details=_details(exit_code=exit_code, stderr=stderr),
        )
    code, stage = mapped
    return FailureInfo(
        code=code,
        stage=stage,
        message="the matcher produced no comparison",
        retryable=False,
        details=_details(exit_code=exit_code, stderr=stderr),
    )


def no_score_failure(*, stdout_excerpt: str) -> FailureInfo:
    """The matcher exited zero without printing a usable number.

    Never a zero score. A comparison that produced no number did not score
    badly; it did not score (docs/adr/0006).
    """
    return FailureInfo(
        code=FailureCode.NO_SCORE,
        stage=FailureStage.MATCHING,
        message="the matcher exited successfully without printing a score",
        retryable=False,
        details={"stdout_excerpt": _excerpt(stdout_excerpt)},
    )


def timeout_failure(*, stage: str) -> FailureInfo:
    """A tool overran its budget and was ended."""
    return FailureInfo(
        code=FailureCode.TIMEOUT,
        stage=FailureStage.TIMEOUT,
        message=f"the {stage} stage exceeded the configured budget",
        retryable=True,
        details={"stage": stage},
    )


def launch_failure(*, stage: str, detail: str) -> FailureInfo:
    """A tool could not be started at all.

    Distinct from a crash: nothing ran, so this is the environment rather than
    the comparison. Preflight normally catches it; this is the case where a tool
    disappeared after preflight approved it.
    """
    return FailureInfo(
        code=FailureCode.DEPENDENCY_MISSING,
        stage=FailureStage.ENVIRONMENT,
        message=f"the {stage} tool could not be started",
        retryable=False,
        details={"stage": stage, "detail": _excerpt(detail)},
    )


def _details(*, exit_code: int, stderr: str, side: str | None = None) -> dict[str, str]:
    details = {"exit_code": str(exit_code)}
    if side is not None:
        details["side"] = side
    excerpt = _excerpt(stderr)
    if excerpt:
        details["stderr_excerpt"] = excerpt
    return details


def _excerpt(text: str) -> str:
    """Short, single-line, and safe to publish: no paths and no traceback."""
    return " ".join((text or "").split())[:MAX_STDERR_CHARS]
