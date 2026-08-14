"""Stage 13A failure vocabulary.

A sibling module rather than an extension of
:mod:`fpbench.core.idkit_preflight_errors`,
:mod:`fpbench.core.id3_preflight_errors` or
:mod:`fpbench.core.verifinger_preflight_errors`, for the reason those three are
siblings of each other: Stage 10B's, Stage 11A's and Stage 12A's published
markers pin their error modules byte-for-byte through their source fingerprints,
so a line added to any of them would re-open a closed stage to make room for a
new one. All four descend from the same root, so ``except FpbenchError`` still
catches everything.

None of these is a statement about FingerCell's quality. An error here means
Stage 13A's own record is missing, malformed, or has been allowed to stand in for
something it is not: an archive identified by a vendor's revision hash rather
than by a digest this project computed, an extractor default asserted from a PDF
rather than read off a constructed engine, a gate reported as failed when the
action behind it was never performed.

Three outcomes are ordinary published results and none of them is an error.
``FINGERCELL_PREFLIGHT_PASS`` and ``FINGERCELL_PREFLIGHT_FAIL`` are produced by
the normal path, and so is ``FINGERCELL_PREFLIGHT_INCOMPLETE`` — an action this
project has not performed yet is not a finding about FingerCell
(docs/adr/0112, docs/adr/0113).
"""

from __future__ import annotations

from fpbench.core.errors import FpbenchError

__all__ = [
    "FingerCellPreflightError",
    "FingerCellCandidateIdentityError",
    "FingerCellObservationError",
    "FingerCellAcquisitionError",
    "FingerCellGateError",
    "FingerCellQualificationError",
    "FingerCellContaminationError",
    "FingerCellSensitiveEvidenceError",
    "Stage13AFinalizationError",
]


class FingerCellPreflightError(FpbenchError):
    """The Neurotechnology FingerCell preflight cannot be carried out as described."""


class FingerCellCandidateIdentityError(FingerCellPreflightError):
    """A frozen Stage 13A identity is malformed or has drifted.

    The candidate id, the ten gates and their order, the four gate states, the
    blocker vocabulary, the three outcome names, the bound Stage 12A, Stage 11B
    and Stage 8E markers and the refused sibling-product families are frozen
    constants. A change to any of them is a different preflight, not a correction
    to this one.
    """


class FingerCellObservationError(FingerCellPreflightError):
    """A recorded public observation is malformed, or is claiming authority.

    Raised where an observation carries no locator, where a locator was never
    retrieved yet the observation reports what it said, or where a statement read
    from the vendor's documentation PDF is recorded as something Stage 13A may
    freeze a value from. Upstream's published API contract is evidence about
    FingerCell; only the delivered archive is evidence about *this* archive
    (docs/adr/0113).
    """


class FingerCellAcquisitionError(FingerCellPreflightError):
    """An acquisition or trial claim is unsupported by what was recorded.

    Raised where the archive is reported obtained with no digest behind it, where
    a locator category outside the official set is recorded as one, where a
    signed or tokenized URL is offered as the official locator, where trial
    operation is reported without the archive having been obtained, or where a
    workload capacity is called sufficient without an arithmetic that covers the
    frozen workload.
    """


class FingerCellGateError(FingerCellPreflightError):
    """A gate result contradicts the gate order or the evidence beneath it.

    Raised where a gate reports a conclusion although an earlier gate stopped the
    run, where a gate passes with a blocker recorded against it, where a blocker
    is raised against a gate it does not belong to, or where ``ACTION_REQUIRED``
    is used to report an action that *was* performed and went wrong — the one
    distinction Stage 13A carries from its first day (docs/adr/0112).
    """


class FingerCellQualificationError(FingerCellPreflightError):
    """The bounded qualification run was asked to do something it may not.

    Raised where more than the permitted number of score-producing comparisons is
    requested, where a required pass is missing from a record that claims
    success, where fewer than the four mandatory failure probes were provoked,
    where a score value would reach disk, or where SELF was assembled from one
    extraction instead of two.
    """


class FingerCellContaminationError(FingerCellPreflightError):
    """A VeriFinger component was about to answer for FingerCell.

    Stage 13A's own hazard, and the reason it has an error class Stage 12A did
    not need. Both candidates are Neurotechnology products and the delivered
    FingerCell package ships common Neurotechnology runtime components; a route
    that reached a VeriFinger extractor or matcher would still produce numbers,
    and they would be Algorithm 4's numbers published under Algorithm 5's name
    (docs/adr/0114).
    """


class FingerCellSensitiveEvidenceError(FingerCellPreflightError):
    """Published evidence carries, or is about to carry, licence material.

    The one refusal in this module that is not about correctness. A licence
    file's bytes, a machine ID, a trial token, a licensing server identifier, a
    signed download URL, a machine path or anything shaped like a credential must
    never reach a public repository, whatever the document around it was trying
    to say.
    """


class Stage13AFinalizationError(FingerCellPreflightError):
    """The Stage 13A evidence chain is incomplete or no longer verifies."""
