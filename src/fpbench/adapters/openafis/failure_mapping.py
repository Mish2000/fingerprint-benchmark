"""What each way this route can fail is recorded as, in one table.

Stage 19A's requirement lists its outcome vocabulary directly:

.. code-block:: text

    OK
    MINDTCT_FAILED_LEFT / _RIGHT / _BOTH
    INVALID_XYT_LEFT / _RIGHT
    OPENAFIS_TEMPLATE_FAILED_LEFT / _RIGHT / _BOTH
    OPENAFIS_MATCH_FAILED
    INFRASTRUCTURE_FAILURE

Those names live in ``details["stage19_status"]`` on every failure, so a stored
result carries the requirement's own word for what happened as well as the
project's ``FailureCode``. The two are not redundant: ``FailureCode`` is what the
rest of the benchmark already understands, and the Stage 19A word is what the
requirement asked to be able to count.

**A score of 0 never reaches this module.** OpenAFIS returns 0 when two templates
share too little structure, which is an answer about two fingers and not a
failure of anything (docs/adr/0006).

**A template OpenAFIS refuses is not a bridge defect.** Fewer than 2 or more than
128 minutiae are OpenAFIS's own declared limits, so they are recorded as template
failures on the side that broke them, and the bridge does not "fix" either by
padding or by keeping a best-128.

Nothing here carries a path, a subject, a finger or a pair id.
"""

from __future__ import annotations

from fpbench.core.enums import FailureCode, FailureStage
from fpbench.core.execution_models import FailureInfo

__all__ = [
    "OPENAFIS_TOOL",
    "TRANSLATION_STAGE",
    "STAGE19_STATUSES",
    "mindtct_failure",
    "invalid_xyt_failure",
    "template_refused_failure",
    "openafis_match_failure",
    "infrastructure_failure",
]

OPENAFIS_TOOL = "openafis"
TRANSLATION_STAGE = "translation"

#: The closed vocabulary from section 17. ``OK`` is here so the list is the whole
#: set rather than the failures only.
STAGE19_STATUSES: tuple[str, ...] = (
    "OK",
    "MINDTCT_FAILED_LEFT",
    "MINDTCT_FAILED_RIGHT",
    "MINDTCT_FAILED_BOTH",
    "INVALID_XYT_LEFT",
    "INVALID_XYT_RIGHT",
    "OPENAFIS_TEMPLATE_FAILED_LEFT",
    "OPENAFIS_TEMPLATE_FAILED_RIGHT",
    "OPENAFIS_TEMPLATE_FAILED_BOTH",
    "OPENAFIS_MATCH_FAILED",
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
            "tool": "mindtct",
            "side": side,
            "exit_code": str(exit_code),
            "stage19_status": f"MINDTCT_FAILED_{_side(side)}",
        },
    )


def invalid_xyt_failure(*, side: str, kind: str) -> FailureInfo:
    """MINDTCT exited zero and wrote something that is not an XYT file."""
    return FailureInfo(
        code=FailureCode.TEMPLATE_EXTRACTION_FAILED,
        stage=FailureStage.EXTRACTION,
        message="the extractor output is not a usable XYT file",
        details={
            "tool": "mindtct",
            "side": side,
            "kind": kind,
            "stage19_status": f"INVALID_XYT_{_side(side)}",
        },
    )


def template_refused_failure(*, side: str, reason: str) -> FailureInfo:
    """The minutiae are outside OpenAFIS's own 2..128 bounds, or the raster is not.

    ``side`` may be ``both`` when neither side could become a template.
    """
    return FailureInfo(
        code=FailureCode.TEMPLATE_EXTRACTION_FAILED,
        stage=FailureStage.EXTRACTION,
        message="openafis refuses a template with this minutiae count",
        details={
            "tool": OPENAFIS_TOOL,
            "side": side,
            "reason": reason,
            "stage19_status": f"OPENAFIS_TEMPLATE_FAILED_{_side(side)}",
        },
    )


def openafis_match_failure(*, detail: str) -> FailureInfo:
    """Both templates loaded and the matcher still produced no number."""
    return FailureInfo(
        code=FailureCode.MATCHING_FAILED,
        stage=FailureStage.MATCHING,
        message="openafis produced no similarity score",
        details={
            "tool": OPENAFIS_TOOL,
            "detail": detail,
            "stage19_status": "OPENAFIS_MATCH_FAILED",
        },
    )


def infrastructure_failure(*, stage: FailureStage, code: FailureCode, detail: str) -> FailureInfo:
    """The machine broke, rather than the biometrics.

    Kept distinct on purpose: a timeout, a tool that would not start and a crashed
    process all say something about this host and nothing about these fingers.
    """
    return FailureInfo(
        code=code,
        stage=stage,
        message="the comparison could not be carried out",
        details={"detail": detail, "stage19_status": "INFRASTRUCTURE_FAILURE"},
    )
