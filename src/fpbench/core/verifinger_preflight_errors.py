"""Stage 11A failure vocabulary.

A sibling module rather than an extension of
:mod:`fpbench.core.id3_preflight_errors`, for the reason that module is itself a
sibling of :mod:`fpbench.core.algorithm4_errors`: Stage 10B's published marker
pins ``id3_preflight_errors.py`` byte-for-byte through its source fingerprint, so
a line added there would re-open a closed stage to make room for a new one. These
descend from the same root, so ``except FpbenchError`` still catches everything.

None of these is a statement about VeriFinger's quality, and none is a licence
finding. An error here means Stage 11A's own record is missing, malformed, or has
been allowed to stand in for something it is not: an artifact identified by a web
page rather than by its bytes, a runtime identity asserted without a runtime, an
inspection result published for an archive nobody opened, a gate conclusion
recorded for a gate that never ran.

A *blocked* candidate is not an error. ``VERIFINGER_PREFLIGHT_FAIL`` is a
published outcome with a blocker list, produced by the normal path, and it is a
complete and final result for the route as it stands (spec sections 45 and 46).
"""

from __future__ import annotations

from fpbench.core.errors import FpbenchError

__all__ = [
    "VeriFingerPreflightError",
    "VeriFingerCandidateIdentityError",
    "VeriFingerObservationError",
    "VeriFingerAcquisitionError",
    "VeriFingerArtifactInspectionError",
    "VeriFingerGateError",
    "VeriFingerSensitiveEvidenceError",
    "Stage11AFinalizationError",
]


class VeriFingerPreflightError(FpbenchError):
    """The VeriFinger preflight cannot be carried out as described."""


class VeriFingerCandidateIdentityError(VeriFingerPreflightError):
    """A frozen Stage 11A identity is malformed or has drifted.

    The provisional candidate id, the seventeen gates and their order, the
    blocker vocabulary, the outcome names, the setting-provenance vocabulary and
    the frozen workload are constants fixed before the artifact was opened. A
    change to any of them is a different preflight, not a correction to this one.
    """


class VeriFingerObservationError(VeriFingerPreflightError):
    """A recorded observation is malformed.

    Raised where an observation carries no locator, where a page reported as read
    answered something other than 200, or — the case this stage cares most about
    — where a statement read from a *web page* is filed as though it had been
    read from the pinned artifact. The two are different sources and this stage
    exists because they had been treated as one (spec section 5).
    """


class VeriFingerAcquisitionError(VeriFingerPreflightError):
    """An acquisition claim is unsupported by what is on disk.

    Raised where an artifact is reported obtained without a digest, where a
    recorded size disagrees with the file, or where a locator that requires a
    credential is about to be recorded as evidence (spec section 4).
    """


class VeriFingerArtifactInspectionError(VeriFingerPreflightError):
    """An inspection result does not match the artifact it claims to describe.

    Raised where an inspection is reported for an archive whose digest was never
    verified, where a member count is published for a listing nobody produced, or
    where an inspection would have had to extract vendor bytes into the working
    tree to reach its conclusion.
    """


class VeriFingerGateError(VeriFingerPreflightError):
    """A gate result contradicts the gate order or the evidence beneath it.

    Raised where a gate reports a conclusion although an earlier gate stopped the
    candidate, where the candidate passes with a blocker recorded against it, or
    where a blocker is raised against a gate it does not belong to.
    """


class VeriFingerSensitiveEvidenceError(VeriFingerPreflightError):
    """Published evidence carries, or is about to carry, licence material.

    The one refusal in this module that is not about correctness. A trial serial,
    an activation ID, a machine or hardware identifier, a signed URL, a token or
    a licence file's bytes must never reach a public repository, whatever the
    document around it was trying to say (spec section 43).
    """


class Stage11AFinalizationError(VeriFingerPreflightError):
    """The Stage 11A evidence chain is incomplete or no longer verifies."""
