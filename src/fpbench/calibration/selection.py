"""Choosing one boundary, deterministically, from labelled development scores.

The rule, in full, and it is the whole of the objective:

    of the boundaries whose observed impostor match rate does not exceed the
    target, take the one that accepts the most.

There is no second objective. Genuine performance at the chosen boundary is
measured and recorded afterwards; it is never searched over. A selector that
tried many rules and kept the one with the best FNMR would be fitting the
development set rather than applying a policy to it (docs/adr/0080).

Three properties make the result citable.

**The candidates come from the impostor data, and only from it.** For each
distinct score ``s`` that a *scored cross-subject impostor* comparison produced,
and for a higher-is-better matcher, ``score >= s`` and ``score > s``. That family
is closed over the quantity being constrained — ``>= min`` admits every impostor,
``> max`` admits none — so no epsilon is ever invented, and none of the
arithmetic depends on the scale the matcher happens to use.

Mated scores generate no candidate, contribute nothing to permissiveness, and
break no tie. They are counted once, at the end, at whichever boundary was
chosen.

**Ties are atomic.** A boundary is a predicate over a score's *value*, so two
comparisons that scored the same are always decided the same way. That is why a
target rate is usually undershot rather than reached exactly: reaching it would
mean splitting a group of identical scores, and there is nothing to split them
on. Not a pair id, and certainly not a random seed.

**The answer does not depend on the order the rows arrived in.** Counting runs
over a set of distinct values, and the tie-break between two boundaries that
produce literally the same decisions is a fixed canonical rule. Shuffle the
input, restart the process, round-trip through JSON: the same threshold, the same
comparator, the same counts and the same fingerprint.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from fpbench.calibration.models import (
    CalibrationOperatingPoint,
    CalibrationProtocol,
    CalibrationSourceBinding,
    CandidateBoundary,
    LabeledResults,
)
from fpbench.calibration.protocol import build_calibration_operating_point
from fpbench.calibration.validation import validate_calibration_inputs
from fpbench.core.calibration_errors import (
    CalibrationInputError,
    CalibrationSelectionError,
)
from fpbench.core.calibration_models import ProtectedEvaluationRegistry
from fpbench.core.enums import (
    CalibrationPairTruth,
    ScoreDirection,
    ThresholdComparator,
)

__all__ = [
    "COMPARATORS_FOR_DIRECTION",
    "BoundaryOutcome",
    "candidate_boundaries",
    "evaluate_boundary",
    "require_ties_are_atomic",
    "select_boundary",
    "select_operating_point",
]

MATED = CalibrationPairTruth.MATED
IMPOSTOR = CalibrationPairTruth.CROSS_SUBJECT_IMPOSTOR

#: The two comparators each score direction admits, inclusive first.
#:
#: Both are first-class. Unlike a legacy decision profile, no calibrated
#: operating point predates the strict comparators, so there is no schema here in
#: which ``>`` is unavailable (docs/adr/0055).
COMPARATORS_FOR_DIRECTION = {
    ScoreDirection.HIGHER_IS_BETTER: (
        ThresholdComparator.GREATER_THAN_OR_EQUAL,
        ThresholdComparator.GREATER_THAN,
    ),
    ScoreDirection.LOWER_IS_BETTER: (
        ThresholdComparator.LESS_THAN_OR_EQUAL,
        ThresholdComparator.LESS_THAN,
    ),
}


@dataclass(frozen=True, slots=True)
class BoundaryOutcome:
    """What one candidate boundary would do to one body of labelled results.

    ``accepted_impostor_scores`` is the boundary's identity as far as the
    selection is concerned: two boundaries that admit the same impostor evidence
    are one threshold with two names, and choosing between them is a naming
    question rather than a threshold question.

    The mated counts are here too, and they are output. Nothing in the selection
    reads them — permissiveness, admissibility and the tie-break are all defined
    over impostor evidence alone, so the genuine population cannot move the
    boundary even by a tie (docs/adr/0080).
    """

    boundary: CandidateBoundary
    accepted_impostor_scores: frozenset[Decimal]
    impostor_matches: int
    impostor_scored: int
    mated_matches: int
    mated_scored: int

    @property
    def permissiveness(self) -> int:
        """How many distinct *impostor* scores this boundary calls a match.

        A faithful ordering, not an approximation. For one score direction the
        accepted sets are all upward-closed (or all downward-closed), and those
        form a chain under inclusion — so a larger accepted set is always a
        superset, and two of equal size are always equal.
        """
        return len(self.accepted_impostor_scores)


def candidate_boundaries(results: LabeledResults) -> tuple[CandidateBoundary, ...]:
    """Every boundary the observed *impostor* scores can express, in a fixed order.

    Impostor-only, and that is the whole of it. A candidate drawn from a value
    only a mated comparison produced is a threshold the genuine population chose,
    which is the optimisation the selection rule exists to refuse.

    The family is still closed over the quantity being constrained: ``>= min``
    admits every impostor and ``> max`` admits none, so both extremes of the
    impostor rate are reachable without inventing a number. A boundary *below*
    the lowest impostor score is deliberately not representable — the only reason
    to move there would be to admit more mated comparisons (docs/adr/0080).

    Ordered by threshold then by inclusiveness so the tuple itself is
    deterministic. The selection does not depend on this order, but a published
    count of candidates should not wobble.
    """
    comparators = COMPARATORS_FOR_DIRECTION[results.score_direction]
    return tuple(
        CandidateBoundary(threshold=score, comparator=comparator)
        for score in results.distinct_scores_of(IMPOSTOR)
        for comparator in comparators
    )


def evaluate_boundary(
    boundary: CandidateBoundary, results: LabeledResults
) -> BoundaryOutcome:
    """Count what this boundary would do, over scored comparisons only.

    A comparison that produced no score is not counted as a non-match and not
    counted as a match. It is absent from every number here and present in the
    operating point's failure counts, which is the only honest place for it
    (docs/adr/0006).
    """
    impostor_rows = results.scored_of(IMPOSTOR)
    mated_rows = results.scored_of(MATED)
    return BoundaryOutcome(
        boundary=boundary,
        accepted_impostor_scores=frozenset(
            score
            for score in results.distinct_scores_of(IMPOSTOR)
            if boundary.decides(score)
        ),
        impostor_matches=sum(1 for row in impostor_rows if boundary.decides(row.score)),
        impostor_scored=len(impostor_rows),
        mated_matches=sum(1 for row in mated_rows if boundary.decides(row.score)),
        mated_scored=len(mated_rows),
    )


def require_ties_are_atomic(
    boundary: CandidateBoundary, results: LabeledResults
) -> None:
    """Prove that equal scores received equal decisions.

    A property of comparing by value rather than a rule that has to be enforced —
    which is exactly why it is asserted. If ``decides`` ever grew a second input,
    this is what would notice, and it would notice before an operating point was
    published rather than after somebody asked why two identical comparisons
    disagreed (docs/adr/0080).
    """
    by_score: dict[Decimal, set[bool]] = {}
    for row in results.rows:
        if row.is_scored:
            by_score.setdefault(row.score, set()).add(boundary.decides(row.score))
    split = sorted(str(score) for score, calls in by_score.items() if len(calls) > 1)
    if split:
        raise CalibrationSelectionError(
            f"boundary {boundary.canonical_threshold} "
            f"{boundary.comparator.value} split identical scores {split}; a "
            "threshold that can accept one of three identical comparisons is not "
            "a threshold (docs/adr/0080)"
        )


def select_boundary(
    protocol: CalibrationProtocol, results: LabeledResults
) -> BoundaryOutcome:
    """The most permissive boundary inside the target ceiling.

    Raises:
        CalibrationSelectionError: there is no impostor comparison that produced
            a score, so there is no denominator to bound a rate over. An empty
            impostor population is not a low false-match rate (docs/adr/0027).
    """
    impostor_scored = len(results.scored_of(IMPOSTOR))
    if impostor_scored == 0:
        raise CalibrationSelectionError(
            "every impostor comparison in the development set failed, so there is "
            "nothing to bound an impostor match rate over. A rate over an empty "
            "population is not a small rate; it is not a rate"
        )

    outcomes = [
        evaluate_boundary(boundary, results)
        for boundary in candidate_boundaries(results)
    ]
    admissible = [
        outcome
        for outcome in outcomes
        if protocol.permits(outcome.impostor_matches, outcome.impostor_scored)
    ]
    if not admissible:
        # Unreachable while the target is non-negative: "accept nothing" admits
        # zero impostors and 0/n is inside every ceiling. Kept because the
        # alternative to an explicit refusal is an IndexError three lines down.
        raise CalibrationSelectionError(
            f"no boundary satisfies a target of {protocol.target_rate}; not even "
            "the one that accepts nothing"
        )

    best = max(outcome.permissiveness for outcome in admissible)
    tied = [outcome for outcome in admissible if outcome.permissiveness == best]

    # Two boundaries can admit the same impostor evidence — ``>= 0.7`` and
    # ``> 0.4`` over impostor scores {0.4, 0.7} both accept exactly {0.7}. The
    # canonical one is chosen so the identity is stable; no impostor decision
    # moves either way. Inclusive first, then Decimal ordering of the threshold;
    # the second key is defensive, because exactly one inclusive boundary
    # represents each accepted impostor set.
    #
    # The mated population is not consulted, not even here. A tie-break that
    # preferred whichever spelling happened to admit more genuine comparisons
    # would be a second objective wearing a naming rule's clothes.
    chosen = sorted(
        tied,
        key=lambda outcome: (
            outcome.boundary.comparator.is_strict,
            outcome.boundary.threshold,
        ),
    )[0]
    require_ties_are_atomic(chosen.boundary, results)
    return chosen


def select_operating_point(
    protocol: CalibrationProtocol,
    source_binding: CalibrationSourceBinding,
    labeled_results: LabeledResults,
    *,
    protected_registry: ProtectedEvaluationRegistry,
    created_source_commit: str,
    created_source_tree_clean: bool,
    created_utc: str,
) -> CalibrationOperatingPoint:
    """Choose a boundary and seal it, with the counts it was chosen from.

    The public entry point of the whole package. The first thing it does is
    refuse: the cohort role and the protected identities are checked before
    ``labeled_results`` is touched at all, so a caller who hands over evaluation
    scores gets a :class:`CalibrationLeakageError` and not a threshold
    (docs/adr/0079).
    """
    validate_calibration_inputs(
        protocol=protocol,
        source_binding=source_binding,
        labeled_results=labeled_results,
        protected_registry=protected_registry,
    )
    if not isinstance(labeled_results, LabeledResults):
        raise CalibrationInputError(
            "a selection runs over a validated body of labelled results"
        )

    outcome = select_boundary(protocol, labeled_results)
    boundary = outcome.boundary

    impostor_attempts = labeled_results.attempts(IMPOSTOR)
    mated_attempts = labeled_results.attempts(MATED)
    return build_calibration_operating_point(
        calibration_protocol_fingerprint_value=protocol.protocol_fingerprint,
        source_binding_fingerprint=source_binding.source_binding_fingerprint,
        algorithm_id=source_binding.algorithm_id,
        algorithm_fingerprint=source_binding.algorithm_fingerprint,
        threshold=boundary.threshold,
        comparator=boundary.comparator,
        score_direction=labeled_results.score_direction,
        target_rate_numerator=protocol.target_rate_numerator,
        target_rate_denominator=protocol.target_rate_denominator,
        observed_impostor_matches=outcome.impostor_matches,
        observed_impostor_scored=outcome.impostor_scored,
        observed_impostor_attempts=impostor_attempts,
        impostor_failures=labeled_results.failures(IMPOSTOR),
        observed_mated_matches=outcome.mated_matches,
        observed_mated_non_matches=outcome.mated_scored - outcome.mated_matches,
        observed_mated_scored=outcome.mated_scored,
        observed_mated_attempts=mated_attempts,
        mated_failures=labeled_results.failures(MATED),
        selection_rule=protocol.threshold_selection_rule,
        tie_policy=protocol.tie_policy,
        created_source_commit=created_source_commit,
        created_source_tree_clean=created_source_tree_clean,
        created_utc=created_utc,
    )
