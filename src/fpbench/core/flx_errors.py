"""Stage 8B failure vocabulary.

Stage 8A's :mod:`fpbench.core.errors` is pinned byte-for-byte by the published
Stage 8A finalization, so Stage 8B cannot extend it.  These classes therefore
live beside it and descend from the same root, which keeps ``except
FpbenchError`` honest for callers that do not care which stage failed.

Like every other error in this project these are *harness* failures, never
biometric outcomes: a comparison that times out is a recorded comparison
failure, not an exception that escapes to the caller (docs/adr/0006).
"""

from __future__ import annotations

from fpbench.core.errors import FpbenchError

__all__ = [
    "FlxError",
    "FlxIdentityError",
    "FlxArtifactError",
    "FlxRuntimeLockError",
    "FlxRuntimeError",
    "FlxCheckpointError",
    "FlxPreprocessingError",
    "FlxRepresentationError",
    "FlxScoreError",
    "FlxWorkerError",
    "FlxWorkerTimeout",
    "FlxOfflineViolation",
    "FlxPolicyError",
    "FlxQualificationError",
    "Stage8BFinalizationError",
]


class FlxError(FpbenchError):
    """The flx learned-matcher route could not be operated honestly."""


class FlxIdentityError(FlxError):
    """A frozen Stage 8B identifier or profile identity does not hold."""


class FlxArtifactError(FlxError):
    """The pinned source archive or checkpoint lost its filename, size or digest."""


class FlxRuntimeLockError(FlxError):
    """The dependency lock is incomplete, unpinned, or does not match what is installed."""


class FlxRuntimeError(FlxError):
    """The pinned runtime is absent, altered, or reports a different environment."""


class FlxCheckpointError(FlxError):
    """A checkpoint could not be loaded safely into the identified model variant."""


class FlxPreprocessingError(FlxError):
    """An input is not a canonical gray8 PNG, or the frozen transform did not hold."""


class FlxRepresentationError(FlxError):
    """A representation is the wrong shape, dtype, normalization or is not finite."""


class FlxScoreError(FlxError):
    """A raw score is non-finite, out of nominal range, or not canonically serialized."""


class FlxWorkerError(FlxError):
    """The isolated worker crashed, exited non-zero, or returned a malformed response."""


class FlxWorkerTimeout(FlxWorkerError):
    """A worker operation passed its deadline.  There is no automatic retry."""


class FlxOfflineViolation(FlxError):
    """Something attempted to reach the network inside a qualification operation."""


class FlxPolicyError(FlxError):
    """The frozen Stage 8B operational policy is missing, malformed, or was moved."""


class FlxQualificationError(FlxError):
    """Stage 8B qualification evidence is incomplete or internally contradictory."""


class Stage8BFinalizationError(FlxError):
    """The Stage 8B evidence chain is incomplete or no longer verifies."""
