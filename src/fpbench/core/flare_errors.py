"""Stage 9A failure vocabulary.

A sibling module rather than an extension of :mod:`fpbench.core.errors` or of
:mod:`fpbench.core.third_party_errors`, for the reason
:mod:`fpbench.core.flx_errors` and :mod:`fpbench.core.calibration_errors` are:
each of those is pinned byte-for-byte by a published finalization, and Stage 8E
in particular is a closed stage that Stage 9A may not touch. These descend from
the same root, so ``except FpbenchError`` still catches everything.

None of these is a statement about FLARE's quality, and none is a licence
finding. An error here means Stage 9A's own record of what upstream says is
missing, malformed, or has been allowed to stand in for something it is not: an
artifact described by a path instead of by its bytes, a route operation with no
authority behind it, a checkpoint bound to a model nobody checked it against.

A *blocked* qualification is not an error. ``FLARE_FULL_ROUTE_BLOCKED`` is a
published outcome with a blocker list, and it is produced by the normal path
(docs/adr/0085).
"""

from __future__ import annotations

from fpbench.core.errors import FpbenchError

__all__ = [
    "FlareQualificationError",
    "FlareIdentityError",
    "FlareArtifactError",
    "FlareRouteError",
    "FlareCheckpointError",
    "Stage9AFinalizationError",
]


class FlareQualificationError(FpbenchError):
    """The FLARE qualification cannot be carried out as described."""


class FlareIdentityError(FlareQualificationError):
    """A frozen Stage 9A identity is malformed or has drifted.

    The candidate algorithm id, the four branch names, the two pinned upstream
    commits and the artifact roles are frozen constants. A change to any of them
    is a different qualification, not a correction to this one (docs/adr/0086).
    """


class FlareArtifactError(FlareQualificationError):
    """An upstream artifact is not pinned by the bytes it must be.

    Raised where a Drive file id is offered as an identity, where a placement
    names a machine, or where the bytes that arrived are not the bytes the
    manifest expects. A Drive id is a locator; the identity is the SHA-256 and
    the exact size (docs/adr/0083).
    """


class FlareRouteError(FlareQualificationError):
    """A route operation is malformed, or claims an authority it does not have.

    Never raised because an operation turned out to be unresolved — that is a
    finding the audit reports and a blocker the marker carries. Raised when an
    operation claims ``PAPER_EXPLICIT`` with no paper locator, when a
    resolution is asserted rather than derived, or when the graph does not run
    from the canonical input to the FDRN tensor (docs/adr/0088).
    """


class FlareCheckpointError(FlareQualificationError):
    """A checkpoint's binding to a model class cannot be established.

    Raised when the inspection itself cannot be performed or is self-
    contradictory. A checkpoint whose parameters do not cover the model is a
    reported incompatibility, not an exception (docs/adr/0087).
    """


class Stage9AFinalizationError(FlareQualificationError):
    """The Stage 9A evidence chain is incomplete or no longer verifies."""
