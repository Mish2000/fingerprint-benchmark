"""Stage 10A failure vocabulary.

A sibling module rather than an extension of :mod:`fpbench.core.errors` or of
:mod:`fpbench.core.flare_errors`, for the reason :mod:`fpbench.core.flx_errors`,
:mod:`fpbench.core.calibration_errors` and :mod:`fpbench.core.third_party_errors`
are: each of those is pinned byte-for-byte by a published finalization, and
Stage 8E and Stage 9A are both closed stages Stage 10A may not touch. These
descend from the same root, so ``except FpbenchError`` still catches everything.

None of these is a statement about a candidate's quality, and none is a licence
finding. An error here means Stage 10A's own record of what upstream publishes
is missing, malformed, or has been allowed to stand in for something it is not:
a reproduction offered as the algorithm it reproduces, an artifact described by
a Drive folder instead of by its bytes, a gate conclusion asserted for a gate
that never ran.

A *failed* candidate is not an error. ``AFRNET_PREFLIGHT_FAIL`` and
``JIPNET_PREFLIGHT_FAIL`` are published outcomes with blocker lists, produced by
the normal path, and ``ALGORITHM4_PREFLIGHT_NO_SURVIVOR`` is a complete result
(docs/adr/0089).
"""

from __future__ import annotations

from fpbench.core.errors import FpbenchError

__all__ = [
    "Algorithm4PreflightError",
    "CandidateIdentityError",
    "CandidateAuthenticityError",
    "InputDomainError",
    "PreflightGateError",
    "Stage10AFinalizationError",
]


class Algorithm4PreflightError(FpbenchError):
    """The Algorithm 4 candidate preflight cannot be carried out as described."""


class CandidateIdentityError(Algorithm4PreflightError):
    """A frozen Stage 10A identity is malformed or has drifted.

    The candidate ids, the gate order, the outcome names and the pinned upstream
    commit are frozen constants. A change to any of them is a different
    preflight, not a correction to this one.
    """


class CandidateAuthenticityError(Algorithm4PreflightError):
    """An implementation origin claim is unsupported by what was recorded.

    Raised where an origin of ``AUTHOR_OFFICIAL_IMPLEMENTATION`` is claimed with
    no author-supplied locator behind it, or where a reproduction is filed under
    the name of the algorithm it reproduces (docs/adr/0090).
    """


class InputDomainError(Algorithm4PreflightError):
    """A benchmark input-domain contract is malformed.

    Raised where a transformation from ``canonical_500`` to a model's declared
    input claims an upstream authority it does not cite, or where a contract
    declares a model input without declaring how the model's own code obtains
    it (docs/adr/0091).
    """


class PreflightGateError(Algorithm4PreflightError):
    """A gate result contradicts the gate order or the evidence beneath it.

    Raised where a gate reports a conclusion although an earlier gate stopped
    the candidate, where a candidate passes with a blocker recorded against it,
    or where a selection is made among candidates that did not all survive the
    hard gates (docs/adr/0093).
    """


class Stage10AFinalizationError(Algorithm4PreflightError):
    """The Stage 10A evidence chain is incomplete or no longer verifies."""
