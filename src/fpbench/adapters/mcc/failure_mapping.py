"""What each way this route can fail is recorded as, in one table.

Stage 20B's requirement lists its outcome vocabulary directly:

.. code-block:: text

    OK

    MINDTCT_FAILED_LEFT / _RIGHT / _BOTH
    INVALID_XYT_LEFT / _RIGHT / _BOTH

    MCC_TEMPLATE_REFUSAL_LEFT / _RIGHT / _BOTH
    MCC_MATCH_REFUSAL
    MCC_INVALID_SCORE

    MCC_RUNTIME_FAILURE
    BRIDGE_FAILURE
    INFRASTRUCTURE_FAILURE

Those names live in ``details["stage20b_status"]`` on every failure, so a stored
result carries the requirement's own word for what happened as well as the
project's ``FailureCode``. The two are not redundant: ``FailureCode`` is what the
rest of the benchmark already understands, and the Stage 20B word is what the
requirement asked to be able to count.

**A score of 0 never reaches this module.** Stage 20A established that the MCC
SDK's documented range is an inclusive ``[0,1]`` and that zero is never used as
an exception sentinel — it throws instead. Zero is an answer about two fingers.

**Four kinds of "the SDK said no" are kept apart** because they mean different
things. A template refusal is the SDK declining a minutiae set; a match refusal
is the SDK declining two templates it built itself; an invalid score is a number
outside the contract, recorded verbatim and never clamped; a runtime failure is
the CLR or the assembly, and says nothing about any finger. ``BRIDGE_FAILURE``
is the fifth: our own payload or our own reading of the bridge's answer.

There is no path from an exception to a score here, in either direction.

Nothing in this module carries a path, a subject, a finger or a pair id.
"""

from __future__ import annotations

from fpbench.core.enums import FailureCode, FailureStage
from fpbench.core.execution_models import FailureInfo

__all__ = [
    "MCC_TOOL",
    "MINDTCT_TOOL",
    "STAGE20B_STATUSES",
    "STATUS_KEY",
    "mindtct_failure",
    "invalid_xyt_failure",
    "template_refused_failure",
    "match_refused_failure",
    "invalid_score_failure",
    "mcc_runtime_failure",
    "bridge_failure",
    "infrastructure_failure",
]

MCC_TOOL = "mcc_sdk_v2"
MINDTCT_TOOL = "mindtct"

#: The key every failure writes its Stage 20B word under.
STATUS_KEY = "stage20b_status"

#: The closed vocabulary from section 20. ``OK`` is here so the list is the whole
#: set rather than the failures only.
STAGE20B_STATUSES: tuple[str, ...] = (
    "OK",
    "MINDTCT_FAILED_LEFT",
    "MINDTCT_FAILED_RIGHT",
    "MINDTCT_FAILED_BOTH",
    "INVALID_XYT_LEFT",
    "INVALID_XYT_RIGHT",
    "INVALID_XYT_BOTH",
    "MCC_TEMPLATE_REFUSAL_LEFT",
    "MCC_TEMPLATE_REFUSAL_RIGHT",
    "MCC_TEMPLATE_REFUSAL_BOTH",
    "MCC_MATCH_REFUSAL",
    "MCC_INVALID_SCORE",
    "MCC_RUNTIME_FAILURE",
    "BRIDGE_FAILURE",
    "INFRASTRUCTURE_FAILURE",
)

_SIDE_SUFFIX = {"left": "LEFT", "right": "RIGHT", "both": "BOTH"}


def _side(side: str) -> str:
    suffix = _SIDE_SUFFIX.get(side)
    if suffix is None:
        raise ValueError(f"unknown side {side!r}")
    return suffix


def mindtct_failure(*, side: str, exit_code: int) -> FailureInfo:
    """MINDTCT ran and declined the print, or ended non-zero."""
    return FailureInfo(
        code=FailureCode.TEMPLATE_EXTRACTION_FAILED,
        stage=FailureStage.EXTRACTION,
        message="mindtct exited non-zero",
        details={
            "tool": MINDTCT_TOOL,
            "side": side,
            "exit_code": str(exit_code),
            STATUS_KEY: f"MINDTCT_FAILED_{_side(side)}",
        },
    )


def invalid_xyt_failure(*, side: str, kind: str) -> FailureInfo:
    """MINDTCT exited zero and wrote something that is not an XYT file."""
    return FailureInfo(
        code=FailureCode.TEMPLATE_EXTRACTION_FAILED,
        stage=FailureStage.EXTRACTION,
        message="the extractor output is not a usable XYT file",
        details={
            "tool": MINDTCT_TOOL,
            "side": side,
            "kind": kind,
            STATUS_KEY: f"INVALID_XYT_{_side(side)}",
        },
    )


def template_refused_failure(*, side: str, reason: str) -> FailureInfo:
    """The SDK, or this route's translation, would not make a template.

    ``side`` may be ``both`` when neither side could become one. A translation
    refusal lands here rather than under ``BRIDGE_FAILURE`` because it is a
    statement about one side's minutiae, which is what a template refusal is.
    """
    return FailureInfo(
        code=FailureCode.TEMPLATE_EXTRACTION_FAILED,
        stage=FailureStage.EXTRACTION,
        message="the mcc sdk refused to build a template from these minutiae",
        details={
            "tool": MCC_TOOL,
            "side": side,
            "reason": reason,
            STATUS_KEY: f"MCC_TEMPLATE_REFUSAL_{_side(side)}",
        },
    )


def match_refused_failure(*, detail: str) -> FailureInfo:
    """Both templates were built and the matcher still produced no number."""
    return FailureInfo(
        code=FailureCode.MATCHING_FAILED,
        stage=FailureStage.MATCHING,
        message="the mcc sdk produced no similarity for two templates it built",
        details={"tool": MCC_TOOL, "detail": detail, STATUS_KEY: "MCC_MATCH_REFUSAL"},
    )


def invalid_score_failure(*, observed: str) -> FailureInfo:
    """A number outside the frozen contract: NaN, an infinity, or off ``[0,1]``.

    Recorded exactly as the SDK produced it. Not clamped, not rounded, not
    normalised — a similarity the matcher never returned must not appear in a
    result file, and a score that breaks the contract is worth seeing.
    """
    return FailureInfo(
        code=FailureCode.NO_SCORE,
        stage=FailureStage.MATCHING,
        message="the mcc sdk returned a value outside its documented score contract",
        details={
            "tool": MCC_TOOL,
            "observed_score": observed,
            "clamped": "false",
            STATUS_KEY: "MCC_INVALID_SCORE",
        },
    )


def mcc_runtime_failure(*, detail: str) -> FailureInfo:
    """The CLR, the assembly load, or the process. Not the biometrics."""
    return FailureInfo(
        code=FailureCode.DEPENDENCY_MISSING,
        stage=FailureStage.ENVIRONMENT,
        message="the mcc sdk runtime could not be used for this comparison",
        details={"tool": MCC_TOOL, "detail": detail, STATUS_KEY: "MCC_RUNTIME_FAILURE"},
    )


def bridge_failure(*, detail: str) -> FailureInfo:
    """Our payload, or our reading of the bridge's answer. Ours, either way."""
    return FailureInfo(
        code=FailureCode.INTERNAL_ERROR,
        stage=FailureStage.ADAPTER,
        message="the mcc bridge could not carry this comparison",
        details={"detail": detail, STATUS_KEY: "BRIDGE_FAILURE"},
    )


def infrastructure_failure(
    *, stage: FailureStage, code: FailureCode, detail: str
) -> FailureInfo:
    """The machine broke, rather than the biometrics.

    Kept distinct on purpose: a timeout, a tool that would not start and a crashed
    process all say something about this host and nothing about these fingers.
    """
    return FailureInfo(
        code=code,
        stage=stage,
        message="the comparison could not be carried out",
        details={"detail": detail, STATUS_KEY: "INFRASTRUCTURE_FAILURE"},
    )
