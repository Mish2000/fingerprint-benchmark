"""Stage 15A failure vocabulary.

A sibling module rather than an extension of
:mod:`fpbench.core.griaule_preflight_errors`,
:mod:`fpbench.core.fingercell_preflight_errors`,
:mod:`fpbench.core.idkit_preflight_errors`,
:mod:`fpbench.core.id3_preflight_errors` or
:mod:`fpbench.core.verifinger_preflight_errors`, for the reason those five are
siblings of each other: each published marker pins its own error module
byte-for-byte through a source fingerprint, so a line added to any of them would
re-open a closed stage to make room for a new one. All six descend from the same
root, so ``except FpbenchError`` still catches everything.

None of these is a statement about the candidate's quality. An error here means
Stage 15A's own record is missing, malformed, or has been allowed to stand in for
something it is not: a runtime pinned from a resolver's answer rather than from a
stated rule, a route asserted from the package's README rather than read out of
the installed module, a comparison that ended in neither a score nor a declared
algorithmic failure, or an exception quietly recorded as a score of zero.

Two outcomes are ordinary published results and neither is an error.
``FINGERPRINTS_MATCHING_CANONICAL500_RAW_COMPLETE`` closes the stage with the
fifth raw result set; ``FINGERPRINTS_MATCHING_QUALIFICATION_FAIL`` closes it
without one and hands Algorithm 5 to the reserve candidate. A stage that ran to
the end and found the candidate cannot produce scores has succeeded at being a
stage (docs/adr/0104).
"""

from __future__ import annotations

from fpbench.core.errors import FpbenchError

__all__ = [
    "Stage15AError",
    "Stage15AIdentityError",
    "Stage15ASelectionError",
    "Stage15ARuntimeIdentityError",
    "Stage15ARouteContractError",
    "Stage15AQualificationError",
    "Stage15AAdapterError",
    "Stage15AResultIntegrityError",
    "Stage15AFinalizationError",
]


class Stage15AError(FpbenchError):
    """The ``fingerprints-matching`` qualification cannot be carried out as described."""


class Stage15AIdentityError(Stage15AError):
    """A frozen Stage 15A identity is malformed or has drifted.

    The candidate id, the package name and version, the two published artifact
    digests, the six gates and their order, the two outcome names and the bound
    Stage 14A, Stage 11B and Stage 8E records are frozen constants. A change to
    any of them is a different stage, not a correction to this one.
    """


class Stage15ASelectionError(Stage15AError):
    """The predecessor-selection record misstates what it supersedes.

    Raised in particular where Stage 14A is recorded as having failed. Griaule
    was never refused and never answered: no request was sent, so there is no
    vendor position to report. Rewriting an unfinished investigation as a
    finding about the candidate would manufacture evidence that does not exist
    (docs/adr/0104, docs/adr/0121).
    """


class Stage15ARuntimeIdentityError(Stage15AError):
    """The frozen runtime closure is incomplete, unpinned or unverifiable.

    OpenCV is not an incidental dependency here: the contours it returns are the
    direct input to feature extraction, so its exact version is part of the
    algorithm's identity (docs/adr/0125). Raised where a component carries no
    digest, where the interpreter, platform or a wheel is missing from the
    closure, where a resolved version disagrees with the pinned one, or where a
    version was chosen by any rule other than the stated one.
    """


class Stage15ARouteContractError(Stage15AError):
    """The upstream route does not match what the contract froze.

    Raised where the installed module's bytes differ from the published
    artifact, where the top-level entry point is missing or has a different
    signature, where the route is claimed from the package's README rather than
    read out of the installed source, or where fpbench would have to insert a
    crop, resize, ROI, segmentation, enhancement, threshold, alignment or score
    transform for a canonical image to reach it.
    """


class Stage15AQualificationError(Stage15AError):
    """A qualification claim is unsupported by what was observed.

    Raised where the same frozen input produced two different scores, where a
    probe that was required did not run, where a failure was recorded as a score
    of zero, or where an SD300 image was opened before the canonical run. Score
    asymmetry is not raised here: it is an observation that binds the argument
    order into the algorithm's identity, never a defect (docs/adr/0109).
    """


class Stage15AAdapterError(Stage15AError):
    """The production adapter is not driving the frozen route.

    Raised where the adapter would reimplement the matching formula, cache a
    feature set across the two sides of a comparison, reach for a threshold, or
    receive anything about the pair it is comparing.
    """


class Stage15AResultIntegrityError(Stage15AError):
    """The stored result set is not the 6,000 outcomes it claims to be.

    Raised on a missing or duplicated outcome, on a comparison that ended in
    neither a score nor an algorithmic failure, on an infrastructure failure
    reaching the stored set at all, and on any threshold, calibration, metric or
    prior-algorithm score appearing anywhere in it.
    """


class Stage15AFinalizationError(Stage15AError):
    """The Stage 15A evidence chain is incomplete or no longer verifies."""
