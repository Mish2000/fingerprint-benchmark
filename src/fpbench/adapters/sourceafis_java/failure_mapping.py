"""Translating the bridge's failure codes into fpbench's taxonomy.

The mapping is a table, not logic, because it is the point at which two vocabularies
meet and every entry is a decision someone may need to look up. An unrecognised
bridge code is a contract violation rather than a guess: silently folding it into
``INTERNAL_ERROR`` would hide the fact that the two sides have drifted apart.

Nothing here is retryable. Every failure SourceAFIS reports is a property of the
image or the template, and running the same comparison again would produce the same
answer. Timeouts are the exception, and they never reach this module — the client
raises ``TimeoutError`` so the runner's own taxonomy handles them
(docs/adr/0006).
"""

from __future__ import annotations

from typing import Mapping

from fpbench.core.enums import FailureCode, FailureStage
from fpbench.core.execution_models import FailureInfo

__all__ = [
    "BRIDGE_FAILURE_MAP",
    "map_bridge_failure",
    "contract_violation",
    "process_crash",
    "MAX_STDERR_CHARS",
]

#: How much stderr is worth keeping. Enough to identify a crash, not enough for a
#: Java stack trace to end up in every row of a run.
MAX_STDERR_CHARS = 400

#: bridge code -> (fpbench code, stage)
BRIDGE_FAILURE_MAP: Mapping[str, tuple[FailureCode, FailureStage]] = {
    "input_read_failed": (FailureCode.INPUT_INVALID, FailureStage.INPUT),
    "image_decode_failed": (FailureCode.IMAGE_DECODE_FAILED, FailureStage.EXTRACTION),
    "unsupported_resolution": (
        FailureCode.UNSUPPORTED_RESOLUTION,
        FailureStage.EXTRACTION,
    ),
    "template_extraction_failed": (
        FailureCode.TEMPLATE_EXTRACTION_FAILED,
        FailureStage.EXTRACTION,
    ),
    "matching_failed": (FailureCode.MATCHING_FAILED, FailureStage.MATCHING),
}


def map_bridge_failure(
    *,
    code: str,
    message: str,
    side: str | None = None,
    stage: str | None = None,
    exception_type: str | None = None,
) -> FailureInfo:
    """Turn a bridge failure document into a recorded ``FailureInfo``.

    Raises:
        KeyError: never. An unknown code becomes a contract violation instead, so
            that a bridge and adapter which have drifted apart say so.
    """
    mapped = BRIDGE_FAILURE_MAP.get(code)
    if mapped is None:
        return contract_violation(
            f"bridge reported unknown failure code {code!r}",
            details={"bridge_code": code},
        )

    failure_code, failure_stage = mapped
    details: dict[str, str] = {"bridge_code": code}
    if side:
        details["side"] = side
    if stage:
        details["bridge_stage"] = stage
    if exception_type:
        details["exception_type"] = exception_type

    return FailureInfo(
        code=failure_code,
        stage=failure_stage,
        message=message or f"SourceAFIS reported {code}",
        retryable=False,
        details=details,
    )


def contract_violation(
    message: str, *, details: Mapping[str, str] | None = None
) -> FailureInfo:
    """The bridge said something the protocol forbids."""
    return FailureInfo(
        code=FailureCode.INTERNAL_ERROR,
        stage=FailureStage.ADAPTER,
        message=message,
        retryable=False,
        details={"kind": "bridge_contract_violation", **dict(details or {})},
    )


def process_crash(*, exit_code: int, stderr: str) -> FailureInfo:
    """The JVM exited non-zero: a bug in the bridge, or a broken request."""
    excerpt = " ".join((stderr or "").split())[:MAX_STDERR_CHARS]
    details = {"exit_code": str(exit_code)}
    if excerpt:
        details["stderr_excerpt"] = excerpt
    return FailureInfo(
        code=FailureCode.PROCESS_CRASHED,
        stage=FailureStage.ADAPTER,
        message=f"the SourceAFIS bridge exited with code {exit_code}",
        retryable=False,
        details=details,
    )
