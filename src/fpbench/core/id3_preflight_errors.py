"""Stage 10B failure vocabulary.

A sibling module rather than an extension of
:mod:`fpbench.core.algorithm4_errors`, for the reason that module is itself a
sibling of :mod:`fpbench.core.errors`: Stage 10A's published marker pins
``algorithm4_errors.py`` byte-for-byte through its source fingerprint, so a line
added there would re-open a closed stage to make room for a new one. These
descend from the same root, so ``except FpbenchError`` still catches everything.

None of these is a statement about the id3 Finger SDK's quality, and none is a
licence finding. An error here means Stage 10B's own record is missing,
malformed, or has been allowed to stand in for something it is not: a package
identified by a documentation version rather than by its bytes, an activation
described without the credentials being kept out of the evidence, a gate
conclusion asserted for a gate that never ran.

A *blocked* candidate is not an error. ``ID3_FINGER_SDK_PREFLIGHT_FAIL`` is a
published outcome with a blocker list, produced by the normal path, and a
failure on access or quota is a complete and final result for the route as it
stands (docs/adr/0095, docs/adr/0096).
"""

from __future__ import annotations

from fpbench.core.errors import FpbenchError

__all__ = [
    "Id3PreflightError",
    "Id3CandidateIdentityError",
    "Id3ObservationError",
    "Id3AccessQualificationError",
    "Id3GateError",
    "SensitiveEvidenceError",
    "Stage10BFinalizationError",
]


class Id3PreflightError(FpbenchError):
    """The id3 Finger SDK preflight cannot be carried out as described."""


class Id3CandidateIdentityError(Id3PreflightError):
    """A frozen Stage 10B identity is malformed or has drifted.

    The provisional candidate id, the ten gates and their order, the blocker
    vocabulary, the outcome names and the predecessor Stage 10A marker are
    frozen constants. A change to any of them is a different preflight, not a
    correction to this one.
    """


class Id3ObservationError(Id3PreflightError):
    """A recorded public observation is malformed.

    Raised where an observation carries no locator, where a locator was never
    retrieved yet the observation reports what it said, or where a statement
    read from one documentation version is filed under another (docs/adr/0097).
    """


class Id3AccessQualificationError(Id3PreflightError):
    """An acquisition or licence claim is unsupported by what was recorded.

    Raised where the package is reported obtained with no identity behind it,
    where activation is reported verified without the licence having been
    obtained, or where a workload capacity is called sufficient without an
    arithmetic that covers the frozen workload (docs/adr/0096).
    """


class Id3GateError(Id3PreflightError):
    """A gate result contradicts the gate order or the evidence beneath it.

    Raised where a gate reports a conclusion although an earlier gate stopped
    the candidate, where the candidate passes with a blocker recorded against
    it, or where a blocker is raised against a gate it does not belong to.
    """


class SensitiveEvidenceError(Id3PreflightError):
    """Published evidence carries, or is about to carry, licence material.

    The one refusal in this module that is not about correctness. An activation
    key, a hardware code, a customer login, a licence file's bytes or anything
    shaped like a credential must never reach a public repository, whatever the
    document around it was trying to say (docs/adr/0098).
    """


class Stage10BFinalizationError(Id3PreflightError):
    """The Stage 10B evidence chain is incomplete or no longer verifies."""
