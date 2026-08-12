"""Which VeriFinger failures are the algorithm declining, and which void the run.

This is the table Stage 11B's whole failure discipline rests on, and it is a
table rather than logic because every row is a decision somebody may need to
look up (docs/adr/0013, spec sections 12 and 13).

The split is not a matter of taste:

``ALGORITHMIC``
    VeriFinger looked at two prints and would not produce a score. A quality
    threshold it set itself, a template it could not build, too few minutiae.
    These are properties of real fingerprints; a run full of them is still a
    run, and "fixing" them to reach 100 % coverage would be falsifying the
    algorithm's own behaviour (spec section 32).

``BLOCKING``
    The comparison never happened as designed. A licence that was refused, a
    model file that is not there, an engine fault, an image the media layer
    could not read *on an input set that was checksummed before the run
    started*, a bridge that spoke nonsense, a JVM that died. Every one of these
    means something about the harness or the machine is wrong, and a result set
    containing one may not be published (spec section 31).

Two classifications are worth defending because they differ from the flx route's.

**A crashed process is blocking here.** For flx a worker crash was a recorded
failure; for VeriFinger a JVM that dies is named in the specification as an
infrastructure failure, and one JVM is one comparison, so a crash means this
machine broke rather than this fingerprint being difficult (spec section 13).

**A decode failure is blocking here.** Every input to the canonical run is a PNG
that was resampled, hashed and verified by Stage 6A, and re-verified by the
preparer before the run. VeriFinger being unable to read one would say something
about the harness, not about the finger.
"""

from __future__ import annotations

from typing import Mapping

from fpbench.core.enums import FailureCode, FailureStage
from fpbench.core.execution_models import FailureInfo

__all__ = [
    "BRIDGE_FAILURE_MAP",
    "ALGORITHMIC_FAILURE_CODES",
    "BLOCKING_FAILURE_CODES",
    "map_bridge_failure",
    "contract_violation",
    "process_crash",
    "MAX_STDERR_CHARS",
]

#: How much stderr is worth keeping. Enough to identify a crash, not enough for
#: a Java stack trace to end up in every row of a run.
MAX_STDERR_CHARS = 400

#: bridge code -> (fpbench code, stage)
BRIDGE_FAILURE_MAP: Mapping[str, tuple[FailureCode, FailureStage]] = {
    # --- the algorithm's own opinion of a fingerprint ---------------------
    "extraction_failed": (
        FailureCode.TEMPLATE_EXTRACTION_FAILED,
        FailureStage.EXTRACTION,
    ),
    # --- the harness, the machine or the request -------------------------
    "invalid_request": (FailureCode.INTERNAL_ERROR, FailureStage.ADAPTER),
    "unsupported_resolution": (
        FailureCode.UNSUPPORTED_RESOLUTION,
        FailureStage.INPUT,
    ),
    "input_unreadable": (FailureCode.INPUT_INVALID, FailureStage.INPUT),
    "image_decode_failed": (FailureCode.IMAGE_DECODE_FAILED, FailureStage.INPUT),
    "licence_not_obtained": (FailureCode.DEPENDENCY_MISSING, FailureStage.ADAPTER),
    "runtime_unavailable": (FailureCode.DEPENDENCY_MISSING, FailureStage.ADAPTER),
    "runtime_defaults_mismatch": (FailureCode.INTERNAL_ERROR, FailureStage.ADAPTER),
    "engine_timeout": (FailureCode.TIMEOUT, FailureStage.TIMEOUT),
    "engine_error": (FailureCode.INTERNAL_ERROR, FailureStage.MATCHING),
    "unclassified_engine_status": (FailureCode.NO_SCORE, FailureStage.MATCHING),
    "bridge_failure": (FailureCode.INTERNAL_ERROR, FailureStage.ADAPTER),
}

#: The only codes a stored VeriFinger failure may carry and still leave the run
#: publishable. Exactly one, because ``verify`` answers with one status for a
#: call that both extracts and matches, and the vendor's own word for it travels
#: beside the code in ``engine_status``.
ALGORITHMIC_FAILURE_CODES: frozenset[FailureCode] = frozenset(
    {FailureCode.TEMPLATE_EXTRACTION_FAILED}
)

#: Everything that means the comparison did not happen as designed. A run
#: carrying any of these fails result-set validation (spec section 31).
BLOCKING_FAILURE_CODES: frozenset[FailureCode] = frozenset(
    {
        FailureCode.INPUT_INVALID,
        FailureCode.IMAGE_DECODE_FAILED,
        FailureCode.UNSUPPORTED_RESOLUTION,
        FailureCode.QUALITY_REJECTED,
        FailureCode.MATCHING_FAILED,
        FailureCode.NO_SCORE,
        FailureCode.DEPENDENCY_MISSING,
        FailureCode.TIMEOUT,
        FailureCode.PROCESS_CRASHED,
        FailureCode.INTERNAL_ERROR,
    }
)


def map_bridge_failure(
    *,
    code: str,
    message: str,
    stage: str | None = None,
    side: str | None = None,
    exception_type: str | None = None,
    engine_status: str | None = None,
) -> FailureInfo:
    """Turn a bridge failure document into a recorded ``FailureInfo``.

    An unrecognised bridge code becomes a contract violation rather than a
    guess: silently folding it into ``INTERNAL_ERROR`` would hide the fact that
    the two sides have drifted apart, and folding it into a biometric code would
    invent a finding.
    """
    mapped = BRIDGE_FAILURE_MAP.get(code)
    if mapped is None:
        return contract_violation(
            f"the bridge reported unknown failure code {code!r}",
            details={"bridge_code": code},
        )
    failure_code, failure_stage = mapped
    details: dict[str, str] = {"bridge_code": code}
    if stage:
        details["bridge_stage"] = stage
    if side:
        details["side"] = side
    if exception_type:
        details["exception_type"] = exception_type
    if engine_status:
        # The vendor's own word for what happened. Recorded on every failure so
        # a reader never has to infer it from an fpbench code.
        details["engine_status"] = engine_status
    return FailureInfo(
        code=failure_code,
        stage=failure_stage,
        message=message or f"VeriFinger reported {code}",
        # Nothing on this route is retryable. Every failure is a property of the
        # images, the installation or the machine, and running the same
        # comparison again would produce the same answer (docs/adr/0006).
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
    """The JVM exited non-zero: a broken installation, or a bug in the bridge."""
    excerpt = " ".join((stderr or "").split())[:MAX_STDERR_CHARS]
    details = {"exit_code": str(exit_code)}
    if excerpt:
        details["stderr_excerpt"] = excerpt
    return FailureInfo(
        code=FailureCode.PROCESS_CRASHED,
        stage=FailureStage.ADAPTER,
        message=f"the VeriFinger bridge exited with code {exit_code}",
        retryable=False,
        details=details,
    )
