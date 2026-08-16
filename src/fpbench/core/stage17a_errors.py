"""Stage 17A failure vocabulary.

A sibling module rather than an extension of
:mod:`fpbench.core.stage16a_errors` or :mod:`fpbench.core.stage15a_errors`, for
the reason those are siblings of each other: each published marker pins its own
error module byte-for-byte through a source fingerprint, so a line added to any
of them would re-open a closed stage to make room for a new one. All of them
descend from the same root, so ``except FpbenchError`` still catches everything.

Stage 17A is the smallest candidate stage this project has run. It asks one
question before it builds anything, because the previous three stages each spent
their effort on machinery for a candidate that turned out not to reach it:
**does the entry point return a raw scalar at all, and can its direction be
proved from the source?** If the answer is no, there is nothing to integrate and
no amount of harness would change that.

Two outcomes close this stage and neither is an error.
``FINGERPRINTMATCHER_CANONICAL500_RAW_COMPLETE`` closes it with the fifth raw
result set; ``FINGERPRINTMATCHER_SCORE_CONTRACT_FAIL`` closes it without one,
because the package publishes a decision rather than a score. A stage that read
one file and correctly declined to build on it has succeeded at being a stage
(docs/adr/0104).
"""

from __future__ import annotations

from fpbench.core.errors import FpbenchError

__all__ = [
    "Stage17AError",
    "Stage17AIdentityError",
    "Stage17AArtifactIdentityError",
    "Stage17AScoreContractError",
    "Stage17ARouteClosureError",
    "Stage17AFinalizationError",
]


class Stage17AError(FpbenchError):
    """The ``fingerprintMatcher`` qualification cannot be carried out as described."""


class Stage17AIdentityError(Stage17AError):
    """A frozen Stage 17A identity is malformed or has drifted.

    The candidate id, the package name and version, the two published digests,
    the seven gates and their order, and the two outcome names are frozen
    constants. A change to any of them is a different stage.
    """


class Stage17AArtifactIdentityError(Stage17AError):
    """The acquired bytes are not the ones PyPI publishes for 1.0.6.

    Raised where a downloaded distribution's digest or size disagrees with the
    record, or where the sdist and the wheel do not ship the same module. Both
    are read, because a package whose two distributions differ has no single
    answer to "what does it do".
    """


class Stage17AScoreContractError(Stage17AError):
    """The entry point does not expose a raw score, and cannot be made to.

    This is the gate the stage exists to answer, and it is answered from the
    module's own source before anything is installed or run. Raised where the
    entry point returns no value, where the only observable is printed text,
    where a decision threshold is applied inside the function, or where the
    direction of a score could not be established from the implementation.
    """


class Stage17ARouteClosureError(Stage17AError):
    """The image-to-score route is not upstream-defined.

    Never reached when the score contract already failed: a route to a number
    that does not exist is not a route with a gap in it.
    """


class Stage17AFinalizationError(Stage17AError):
    """The Stage 17A evidence chain is incomplete or no longer verifies."""
