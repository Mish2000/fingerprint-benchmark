"""Stage 12A failure vocabulary.

A sibling module rather than an extension of
:mod:`fpbench.core.id3_preflight_errors` or
:mod:`fpbench.core.verifinger_preflight_errors`, for the reason those two are
siblings of each other: Stage 10B's and Stage 11A's published markers pin their
error modules byte-for-byte through their source fingerprints, so a line added to
either would re-open a closed stage to make room for a new one. All three descend
from the same root, so ``except FpbenchError`` still catches everything.

None of these is a statement about Innovatrics IDKit's quality, and none is a
licence-terms finding. An error here means Stage 12A's own record is missing,
malformed, or has been allowed to stand in for something it is not: a package
identified by a learning-portal version rather than by its own bytes, a score
route asserted from a support article rather than from the delivered API, a
qualification conclusion published for a pass that never ran.

Three outcomes are ordinary published results and none of them is an error.
``IDKIT_PREFLIGHT_PASS`` and ``IDKIT_PREFLIGHT_FAIL`` are produced by the normal
path, and so is ``IDKIT_PREFLIGHT_PENDING_ACCESS`` — waiting on a vendor is not
a defect in the candidate and is not a verdict about it (docs/adr/0108).
"""

from __future__ import annotations

from fpbench.core.errors import FpbenchError

__all__ = [
    "IdkitPreflightError",
    "IdkitCandidateIdentityError",
    "IdkitObservationError",
    "IdkitAcquisitionError",
    "IdkitGateError",
    "IdkitQualificationError",
    "IdkitSensitiveEvidenceError",
    "Stage12AFinalizationError",
]


class IdkitPreflightError(FpbenchError):
    """The Innovatrics IDKit preflight cannot be carried out as described."""


class IdkitCandidateIdentityError(IdkitPreflightError):
    """A frozen Stage 12A identity is malformed or has drifted.

    The provisional candidate id, the ten gates and their order, the acquisition
    state machine, the blocker vocabulary, the three outcome names and the bound
    Stage 11B and Stage 8E markers are frozen constants. A change to any of them
    is a different preflight, not a correction to this one.
    """


class IdkitObservationError(IdkitPreflightError):
    """A recorded public observation is malformed, or is claiming authority.

    Raised where an observation carries no locator, where a locator was never
    retrieved yet the observation reports what it said, or where a statement read
    from a public support article is recorded as something Stage 12A may freeze a
    value from. A vendor's undated support page is evidence about a product; only
    the delivered package is evidence about *this* package (docs/adr/0110).
    """


class IdkitAcquisitionError(IdkitPreflightError):
    """An acquisition or licence claim is unsupported by what was recorded.

    Raised where the package is reported obtained with no identity behind it,
    where a delivery channel outside the official set is recorded as one, where
    activation is reported without the package having been obtained, or where a
    workload capacity is called sufficient without an arithmetic that covers the
    frozen workload.
    """


class IdkitGateError(IdkitPreflightError):
    """A gate result contradicts the gate order or the evidence beneath it.

    Raised where a gate reports a conclusion although an earlier gate stopped the
    run, where a gate passes with a blocker recorded against it, where a blocker
    is raised against a gate it does not belong to, or where ``PENDING`` appears
    at any gate but acquisition — the one gate whose answer can be "nobody has
    replied yet" (docs/adr/0108).
    """


class IdkitQualificationError(IdkitPreflightError):
    """The bounded qualification run was asked to do something it may not.

    Raised where more than the permitted number of score-producing comparisons is
    requested, where a required pass is missing from a record that claims
    success, where a score value would reach disk, or where SELF was assembled
    from one extraction instead of two (docs/adr/0109).
    """


class IdkitSensitiveEvidenceError(IdkitPreflightError):
    """Published evidence carries, or is about to carry, licence material.

    The one refusal in this module that is not about correctness. A licence file's
    bytes, a portal login, a hardware ID, a serial, a signed download URL, a
    machine path or anything shaped like a credential must never reach a public
    repository, whatever the document around it was trying to say.
    """


class Stage12AFinalizationError(IdkitPreflightError):
    """The Stage 12A evidence chain is incomplete or no longer verifies."""
