"""Stage 8D failure vocabulary.

Stage 8A's :mod:`fpbench.core.errors` is pinned byte-for-byte by the published
Stage 8A finalization, so Stage 8D cannot extend it — the same reason
:mod:`fpbench.core.flx_errors` exists. These classes therefore live beside it and
descend from the same roots, which keeps ``except FpbenchError`` and ``except
StorageError`` honest for callers that do not care which stage failed.

Like every other error in this project, none of these is a biometric outcome. A
boundary that admits more impostors than hoped is a finding; a development
population too small to bound a rate over is one of these (docs/adr/0006).
"""

from __future__ import annotations

from fpbench.core.errors import FpbenchError, StorageError

__all__ = [
    "CalibrationError",
    "CalibrationProtocolError",
    "CalibrationSourceError",
    "CalibrationLeakageError",
    "CalibrationInputError",
    "CalibrationSelectionError",
    "CalibrationConflictError",
    "CalibrationVerificationError",
    "CalibrationBridgeError",
    "Stage8DFinalizationError",
]


class CalibrationError(FpbenchError):
    """A threshold could not be chosen, or a chosen one does not hold up."""


class CalibrationProtocolError(CalibrationError):
    """A calibration protocol is missing, malformed or internally inconsistent.

    A target rate written as a float, a denominator of zero, a selection rule
    that does not constrain the metric it claims to, a normalization this project
    does not perform, or a protocol that would accept an impostor population it
    may not (docs/adr/0079, docs/adr/0080).
    """


class CalibrationSourceError(CalibrationError):
    """A source binding does not identify one exact body of development scores.

    A path where a fingerprint was required, a result set that does not belong to
    the run it names, a pair manifest that belongs to a different cohort. A source
    identified loosely is a source nobody can re-derive a threshold from
    (spec section 7).
    """


class CalibrationLeakageError(CalibrationError):
    """The scores offered for calibration are evaluation data.

    Deliberately its own class rather than a kind of
    :class:`CalibrationSourceError`, so that a caller handling malformed input
    cannot swallow it by accident. Raised before a single score is read: on the
    declared cohort role, or on a binding whose identities resolve to registered
    protected evaluation material (docs/adr/0021, docs/adr/0079).
    """


class CalibrationInputError(CalibrationError):
    """The labelled results cannot support the protocol that was asked for.

    A non-finite score, a duplicated pair, a population the protocol requires and
    the data does not contain, two score directions in one body of results.
    """


class CalibrationSelectionError(CalibrationError):
    """No operating point can be selected under this protocol and these scores.

    Never raised because the answer was disappointing. Raised when there is no
    answer: an empty impostor population to bound a rate over, or a target so
    strict that not even "accept nothing" satisfies it.
    """


class CalibrationConflictError(StorageError):
    """A different calibration artifact is already stored under this identity.

    Protocols, source bindings and operating points are append-only and
    content-addressed, so this means one of the inputs changed while the identity
    did not — never something to resolve by overwriting (docs/adr/0005).
    """


class CalibrationVerificationError(CalibrationError):
    """A stored operating point does not survive re-derivation.

    An operating point is not evidence of itself: verification recomputes every
    candidate boundary, every count and the selection from the labelled scores it
    cites, and compares (spec section 29).
    """


class CalibrationBridgeError(CalibrationError):
    """An operating point could not become a decision profile.

    A calibrated profile has to name the operating point, the protocol and the
    development source it came from. One that could not would be a threshold with
    the word "calibrated" beside it (docs/adr/0021, spec section 21).
    """


class Stage8DFinalizationError(CalibrationError):
    """The Stage 8D evidence chain is incomplete or no longer verifies."""
