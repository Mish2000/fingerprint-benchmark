"""Stage 14A failure vocabulary.

A sibling module rather than an extension of
:mod:`fpbench.core.fingercell_preflight_errors`,
:mod:`fpbench.core.idkit_preflight_errors`,
:mod:`fpbench.core.id3_preflight_errors` or
:mod:`fpbench.core.verifinger_preflight_errors`, for the reason those four are
siblings of each other: Stage 10B's, Stage 11A's, Stage 12A's and Stage 13A's
published markers pin their error modules byte-for-byte through their source
fingerprints, so a line added to any of them would re-open a closed stage to make
room for a new one. All five descend from the same root, so ``except
FpbenchError`` still catches everything.

None of these is a statement about Griaule's quality. An error here means Stage
14A's own record is missing, malformed, or has been allowed to stand in for
something it is not: a package identity taken from a product page instead of from
delivered bytes, an API contract asserted from documentation rather than read out
of a delivered header, an unsent request published as a vendor dependency, or a
gate reported as failed when nothing was ever inspected.

Four outcomes are ordinary published results and none of them is an error.
``GRIAULE_ARTIFACT_ROUTE_PREFLIGHT_PASS`` and
``GRIAULE_ARTIFACT_ROUTE_PREFLIGHT_FAIL`` are produced by the normal path, and so
are ``GRIAULE_PREFLIGHT_PENDING_ACCESS`` — somebody else has to move next — and
``GRIAULE_PREFLIGHT_INCOMPLETE`` — this project has a step left to take. Neither
of the last two says anything about the candidate (docs/adr/0121, docs/adr/0122).
"""

from __future__ import annotations

from fpbench.core.errors import FpbenchError

__all__ = [
    "GriaulePreflightError",
    "GriauleCandidateIdentityError",
    "GriauleObservationError",
    "GriauleAcquisitionError",
    "GriauleGateError",
    "GriauleSensitiveEvidenceError",
    "Stage14AFinalizationError",
]


class GriaulePreflightError(FpbenchError):
    """The Griaule GBS Fingerprint SDK preflight cannot be carried out as described."""


class GriauleCandidateIdentityError(GriaulePreflightError):
    """A frozen Stage 14A identity is malformed or has drifted.

    The candidate id, the four gates and their order, the five gate states, the
    blocker vocabulary, the four outcome names and the bound Stage 13A, Stage 11B
    and Stage 8E markers are frozen constants. A change to any of them is a
    different preflight, not a correction to this one.

    Raised in particular where an implementation version is asserted before a
    package exists. Griaule publishes three build names and no version number,
    and a preflight that froze one from a documentation page would be pinning a
    string rather than an artifact (docs/adr/0110).
    """


class GriauleObservationError(GriaulePreflightError):
    """A recorded public observation is malformed, or is claiming authority.

    Raised where an observation carries no locator, where a locator was never
    retrieved yet the observation reports what it said, or where a statement read
    from the vendor's documentation site is recorded as something Stage 14A may
    settle a gate from. Upstream's published page is evidence about the product
    line; only a delivered package is evidence about *this* package.
    """


class GriauleAcquisitionError(GriaulePreflightError):
    """An acquisition claim is unsupported by what was recorded.

    Raised where the package is reported obtained with no digest behind it, where
    a locator category outside the official set is recorded as one, where a
    request nobody sent is published as a vendor dependency, or where a route
    reports an outcome it never retrieved anything to support.
    """


class GriauleGateError(GriaulePreflightError):
    """A gate result contradicts the gate order or the evidence beneath it.

    Raised where a gate reports a conclusion although an earlier gate stopped the
    run, where a gate passes with a blocker recorded against it, where a blocker
    is raised against a gate it does not belong to, or where ``PENDING_ACCESS``
    and ``ACTION_REQUIRED`` are confused for each other — the one distinction
    this stage carries from its first day, because one of them is somebody else's
    move and the other is ours (docs/adr/0121).
    """


class GriauleSensitiveEvidenceError(GriaulePreflightError):
    """Published evidence carries, or is about to carry, licence material.

    The one refusal in this module that is not about correctness. A licence
    file's bytes, a machine identifier, a trial token, a signed download URL, a
    machine path, a personal e-mail address or anything shaped like a credential
    must never reach a public repository, whatever the document around it was
    trying to say.
    """


class Stage14AFinalizationError(GriaulePreflightError):
    """The Stage 14A evidence chain is incomplete or no longer verifies."""
