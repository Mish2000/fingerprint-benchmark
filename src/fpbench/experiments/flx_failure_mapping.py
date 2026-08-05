"""Which flx errors are the algorithm declining, and which mean the run is void.

The distinction is the whole point and it is not a matter of taste. A recorded
failure says "this comparison did not produce a score, and the run is otherwise
sound". A blocking failure says "nothing after this point can be attributed".
Recording the second kind as the first would let an invalid run be published
with 6,000 rows that look complete (docs/adr/0006, docs/adr/0013).

Every code used here already exists in the general taxonomy. Stage 8C adds
none: a new code would have to be algorithm-neutral and covered by tests for the
whole engine, and each of the five outcomes the flx route can produce already
has a name (spec section 16.1).

    INPUT_DECODE_FAILED   -> IMAGE_DECODE_FAILED
    PREPROCESSING_FAILED  -> PREPARATION_FAILED
    EXTRACTION_FAILED     -> TEMPLATE_EXTRACTION_FAILED
    COMPARISON_FAILED     -> MATCHING_FAILED
    OPERATION_TIMEOUT     -> TIMEOUT
"""

from __future__ import annotations

from fpbench.core.enums import FailureCode, FailureStage
from fpbench.core.errors import RuntimeDriftError
from fpbench.core.flx_errors import (
    FlxArtifactError,
    FlxCheckpointError,
    FlxError,
    FlxIdentityError,
    FlxOfflineViolation,
    FlxPreprocessingError,
    FlxRepresentationError,
    FlxRuntimeError,
    FlxRuntimeLockError,
    FlxScoreError,
    FlxWorkerError,
    FlxWorkerTimeout,
)

__all__ = [
    "BLOCKING_ERRORS",
    "ALGORITHMIC_FAILURE_CODES",
    "classify",
    "raise_if_blocking",
]

#: Errors that mean the pinned runtime is not the one the run was defined
#: against. Re-raised as ``RuntimeDriftError`` and never stored: a stored
#: failure would imply the run is otherwise sound, when what actually happened
#: is that the artifact, the lock, the identity or the offline guarantee moved
#: underneath it (docs/adr/0018, spec section 16.2).
BLOCKING_ERRORS: tuple[type[FlxError], ...] = (
    FlxArtifactError,
    FlxCheckpointError,
    FlxIdentityError,
    FlxOfflineViolation,
    FlxRuntimeError,
    FlxRuntimeLockError,
)

#: Every code a stored flx failure may carry. Nothing outside this set is a
#: biometric outcome, and the validator refuses a result that carries one.
ALGORITHMIC_FAILURE_CODES: frozenset[FailureCode] = frozenset(
    {
        FailureCode.IMAGE_DECODE_FAILED,
        FailureCode.PREPARATION_FAILED,
        FailureCode.TEMPLATE_EXTRACTION_FAILED,
        FailureCode.MATCHING_FAILED,
        FailureCode.TIMEOUT,
        FailureCode.PROCESS_CRASHED,
    }
)


def raise_if_blocking(error: BaseException) -> None:
    """Convert a runtime-integrity error into the engine's own drift signal.

    Ordered before every other classification, and deliberately so: ``FlxWorkerError``
    is a recorded failure and ``FlxRuntimeError`` is not, and both can surface
    from the same call.
    """
    if isinstance(error, BLOCKING_ERRORS):
        raise RuntimeDriftError(
            f"the pinned flx runtime is not the one this run was defined "
            f"against: {type(error).__name__}: {error}"
        ) from error


def classify(error: BaseException, *, stage: FailureStage) -> tuple[FailureCode, FailureStage]:
    """Name a recorded failure. ``stage`` is where the adapter actually was.

    The stage is passed in rather than inferred from the exception type, because
    the same ``FlxWorkerTimeout`` means a slow preprocess in one call and a slow
    comparison in another, and a reader of a stored failure needs to know which.
    """
    if isinstance(error, FlxWorkerTimeout):
        return FailureCode.TIMEOUT, FailureStage.TIMEOUT
    if isinstance(error, FlxPreprocessingError):
        return FailureCode.PREPARATION_FAILED, FailureStage.PREPARATION
    if isinstance(error, FlxRepresentationError):
        return FailureCode.TEMPLATE_EXTRACTION_FAILED, FailureStage.EXTRACTION
    if isinstance(error, FlxScoreError):
        return FailureCode.MATCHING_FAILED, FailureStage.MATCHING
    if isinstance(error, FlxWorkerError):
        return FailureCode.PROCESS_CRASHED, stage
    if isinstance(error, OSError):
        return FailureCode.IMAGE_DECODE_FAILED, FailureStage.INPUT
    return FailureCode.INTERNAL_ERROR, stage
