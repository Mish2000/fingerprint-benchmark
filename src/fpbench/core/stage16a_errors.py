"""Stage 16A failure vocabulary.

A sibling module rather than an extension of
:mod:`fpbench.core.stage15a_errors`, for the reason that module is a sibling of
the five before it: each published marker pins its own error module
byte-for-byte through a source fingerprint, so a line added to any of them would
re-open a closed stage to make room for a new one. All of them descend from the
same root, so ``except FpbenchError`` still catches everything.

Stage 16A adds one distinction its predecessors did not need, and it is the
lesson Stage 15A paid for. An algorithm that *declares* it cannot process an
input has produced a result: a refusal. An algorithm that raises a tensor, index,
shape or OpenCV exception from inside its own implementation on valid input has
produced no result at all, and the difference between the two is the difference
between a candidate that is strict and a candidate that is broken.
:class:`Stage16AUnhandledImplementationError` exists so that the second can never
be filed as the first (docs/adr/0131).

Three outcomes close this stage and none of them is an error.
``FINGERFLOW_CANONICAL500_RAW_COMPLETE`` closes it with the fifth raw result set;
``FINGERFLOW_ROUTE_CLOSURE_FAIL`` closes it without one, because the upstream
inference route could not be closed without fpbench choosing something that
moves the score; ``FINGERFLOW_QUALIFICATION_FAIL`` closes it without one for any
other gate. A stage that ran to the end and found the candidate unusable has
succeeded at being a stage (docs/adr/0104).
"""

from __future__ import annotations

from fpbench.core.errors import FpbenchError

__all__ = [
    "Stage16AError",
    "Stage16AIdentityError",
    "Stage16ASelectionError",
    "Stage16AArtifactIdentityError",
    "Stage16ARouteClosureError",
    "Stage16AScoreContractError",
    "Stage16AQualificationError",
    "Stage16AUnhandledImplementationError",
    "Stage16AAdapterError",
    "Stage16AResultIntegrityError",
    "Stage16AFinalizationError",
]


class Stage16AError(FpbenchError):
    """The FingerFlow qualification cannot be carried out as described."""


class Stage16AIdentityError(Stage16AError):
    """A frozen Stage 16A identity is malformed or has drifted.

    The candidate id, the package name and version, the pinned repository
    commit, the checkpoint inventory and its digests, the seven gates and their
    order, the three outcome names and the bound Stage 15A, Stage 11B and Stage
    8E records are frozen constants. A change to any of them is a different
    stage, not a correction to this one.
    """


class Stage16ASelectionError(Stage16AError):
    """The predecessor record misstates why Stage 15A did not fill the slot.

    Raised in particular where the reason given is a score: low genuine values,
    poor separation, or a comparison against another matcher. Stage 15A produced
    a complete, valid result set and it stands. It was not selected because its
    image-to-features route fails structurally on valid input, and that finding
    is about a mechanism, never about accuracy (docs/adr/0130).
    """


class Stage16AArtifactIdentityError(Stage16AError):
    """The artifact or runtime closure is incomplete, unpinned or unverifiable.

    Raised where a checkpoint the route needs carries no digest or no
    self-service locator, where a downloaded byte sequence disagrees with the
    recorded one, where the interpreter, platform, TensorFlow, NumPy or OpenCV
    version is missing from the closure, or where the execution device was not
    stated.
    """


class Stage16ARouteClosureError(Stage16AError):
    """The upstream inference route could not be closed from upstream authority.

    This is the gate the stage exists to answer. Raised where a question that
    moves the score — which core, which minutiae, how many, in what order,
    whether inference rotates, what happens below the required count, which
    VerifyNet precision — has no official inference example, no single
    unambiguous upstream implementation and no upstream-declared default, so
    that answering it would make fpbench a co-author of the algorithm.
    """


class Stage16AScoreContractError(Stage16AError):
    """The score contract is not the one the artifact supports.

    Raised where ``verify`` does not return one scalar, where the direction was
    assumed rather than shown, or where an asymmetry was repaired by averaging
    or by taking a maximum instead of being frozen as an orientation.
    """


class Stage16AQualificationError(Stage16AError):
    """A qualification claim is unsupported by what was observed.

    Raised where the same frozen input produced two different scores, where a
    required probe did not run, where a failure was recorded as a score of zero,
    or where an SD300 image was opened before the canonical run.
    """


class Stage16AUnhandledImplementationError(Stage16AError):
    """Valid input reached an internal exception, and that is not a refusal.

    The distinction this class exists to keep: an upstream ``no core detected``
    or ``fewer minutiae than the model accepts`` is an explicit algorithmic
    non-result and belongs in the result set as one. A tensor, index, shape or
    OpenCV exception raised from inside the implementation on a valid
    fingerprint is a route failure — never a template-extraction failure, never
    a score, and never evidence about the fingerprint (docs/adr/0131).
    """


class Stage16AAdapterError(Stage16AError):
    """The production adapter is not driving the frozen route.

    Raised where the adapter would assemble a feature vector the route contract
    did not fix, cache a template across the two sides of a comparison, reach
    for a threshold, transform a score, or receive anything about the pair it is
    comparing.
    """


class Stage16AResultIntegrityError(Stage16AError):
    """The stored result set is not the 6,000 outcomes it claims to be.

    Raised on a missing or duplicated outcome, on a comparison that ended in
    neither a score nor a declared algorithmic failure, on an infrastructure or
    route failure reaching the stored set at all, and on any threshold,
    calibration, metric or prior-algorithm score appearing anywhere in it.
    """


class Stage16AFinalizationError(Stage16AError):
    """The Stage 16A evidence chain is incomplete or no longer verifies."""
