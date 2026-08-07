"""The containers, and the only way plain data is allowed to become one.

Two kinds of thing live here.

**The persisted artifacts** — protocol, source binding, protected registry,
operating point — are re-exported from :mod:`fpbench.core.calibration_models`.
They live in ``core`` because the storage layer persists them and ``storage`` may
only import ``core``; the rules for deriving them live here, which is the same
split :mod:`fpbench.decisions` uses.

**The inputs** — a labelled score, a body of labelled scores, a candidate
boundary — are defined here and are never persisted. They are what a selection
consumes and what a verification re-reads; giving them a stored form would create
a second place a development score could live, and the first thing a reader would
have to stop trusting.

**The strict reader** is re-exported too, from the same place. It lives in
``core`` because the storage layer has to reconstruct a stored artifact and
``storage`` may import only ``core``; a store that reached into this package for
its parser would invert the dependency graph. A caller working with the engine
still imports model, reader and factory from one place — here.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from fpbench.core.calibration_errors import CalibrationInputError
from fpbench.core.calibration_models import (
    CalibrationOperatingPoint,
    CalibrationProtocol,
    CalibrationSourceBinding,
    ExactRate,
    ProtectedEvaluationIdentity,
    ProtectedEvaluationRegistry,
    calibration_operating_point_fingerprint,
    calibration_protocol_fingerprint,
    calibration_source_binding_fingerprint,
    operating_point_id,
    protected_evaluation_registry_fingerprint,
    rate_at_most,
    read_bool,
    read_calibration_operating_point,
    read_calibration_protocol,
    read_calibration_source_binding,
    read_decimal_text,
    read_digest,
    read_enum,
    read_int,
    read_protected_evaluation_registry,
    read_str,
    require_digest,
    require_exact_bool,
    require_exact_keys,
    require_finite_decimal,
    strict_json_document,
)
from fpbench.core.enums import (
    CalibrationPairTruth,
    ExecutionStatus,
    ScoreDirection,
    ThresholdComparator,
)
from fpbench.core.serialization import stable_hash

__all__ = [
    "CalibrationProtocol",
    "CalibrationSourceBinding",
    "CalibrationOperatingPoint",
    "ProtectedEvaluationIdentity",
    "ProtectedEvaluationRegistry",
    "ExactRate",
    "LabeledScore",
    "LabeledResults",
    "CandidateBoundary",
    "calibration_protocol_fingerprint",
    "calibration_source_binding_fingerprint",
    "calibration_operating_point_fingerprint",
    "protected_evaluation_registry_fingerprint",
    "operating_point_id",
    "rate_at_most",
    "require_digest",
    "require_exact_bool",
    "require_finite_decimal",
    "strict_json_document",
    "require_exact_keys",
    "read_str",
    "read_int",
    "read_bool",
    "read_digest",
    "read_enum",
    "read_decimal_text",
    "read_calibration_protocol",
    "read_calibration_source_binding",
    "read_calibration_operating_point",
    "read_protected_evaluation_registry",
    "labeled_results_hash",
]


# ---------------------------------------------------------------- the inputs


@dataclass(frozen=True, slots=True)
class LabeledScore:
    """One development comparison, its ground truth, and what it produced.

    The one place in this project where ground truth travels beside a score. An
    adapter may never know whether a pair is mated; a calibration must, or it has
    nothing to count (docs/adr/0010).

    The two shapes are enforced rather than assumed, exactly as they are for a
    stored decision: a success carries a finite score and no failure code, a
    failure carries a code and no score. There is no third shape, and in
    particular no way to represent "failed, therefore non-match" — a comparison
    that produced no score did not fail to match (docs/adr/0006).
    """

    pair_id: str
    truth: CalibrationPairTruth
    execution_status: ExecutionStatus
    score: Decimal | None = None
    failure_code: str | None = None

    def __post_init__(self) -> None:
        pair_id = str(self.pair_id).strip()
        if not pair_id:
            raise CalibrationInputError("pair_id must not be empty")
        object.__setattr__(self, "pair_id", pair_id)

        if not isinstance(self.truth, CalibrationPairTruth):
            raise CalibrationInputError(
                "truth must be a CalibrationPairTruth; a labelled comparison whose "
                "label is a bare string is a label nothing validated"
            )
        if not isinstance(self.execution_status, ExecutionStatus):
            raise CalibrationInputError("execution_status must be an ExecutionStatus")

        if self.execution_status is ExecutionStatus.SUCCESS:
            if self.score is None:
                raise CalibrationInputError(
                    f"{pair_id}: a successful comparison carries a score"
                )
            try:
                score = require_finite_decimal(self.score, f"{pair_id}.score")
            except ValueError as exc:
                raise CalibrationInputError(str(exc)) from None
            object.__setattr__(self, "score", score)
            if self.failure_code is not None:
                raise CalibrationInputError(
                    f"{pair_id}: a successful comparison carries no failure code"
                )
        else:
            if self.score is not None:
                raise CalibrationInputError(
                    f"{pair_id}: a failed comparison has no score to threshold"
                )
            code = str(self.failure_code or "").strip()
            if not code:
                raise CalibrationInputError(
                    f"{pair_id}: a failed comparison records why there was no score"
                )
            object.__setattr__(self, "failure_code", code)

    @property
    def is_scored(self) -> bool:
        return self.execution_status is ExecutionStatus.SUCCESS


@dataclass(frozen=True, slots=True)
class LabeledResults:
    """One body of labelled development comparisons, on one score scale.

    Holds the score direction because a boundary is meaningless without it, and
    holds it *once* because two directions in one body of results would mean two
    algorithms' scores had been mixed — the one thing docs/adr/0058 says can never
    be undone afterwards.

    Rows are sorted on construction by ``pair_id``. That is not the order they
    are counted in — counting is over a set of unique scores and is
    order-independent by construction — it is so that the content hash of a body
    of results does not depend on how it was assembled.
    """

    score_direction: ScoreDirection
    rows: tuple[LabeledScore, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.score_direction, ScoreDirection):
            raise CalibrationInputError("score_direction must be a ScoreDirection")
        rows = tuple(self.rows)
        for row in rows:
            if not isinstance(row, LabeledScore):
                raise CalibrationInputError("every labelled result must be a LabeledScore")
        seen: set[str] = set()
        duplicates: set[str] = set()
        for row in rows:
            if row.pair_id in seen:
                duplicates.add(row.pair_id)
            seen.add(row.pair_id)
        if duplicates:
            raise CalibrationInputError(
                f"the same comparison appears more than once: {sorted(duplicates)}. "
                "A duplicated pair would be counted twice in a rate whose "
                "denominator claims to be the number of comparisons"
            )
        object.__setattr__(
            self, "rows", tuple(sorted(rows, key=lambda item: item.pair_id))
        )

    # -- populations ------------------------------------------------------

    def of(self, truth: CalibrationPairTruth) -> tuple[LabeledScore, ...]:
        return tuple(row for row in self.rows if row.truth is truth)

    def scored_of(self, truth: CalibrationPairTruth) -> tuple[LabeledScore, ...]:
        return tuple(row for row in self.of(truth) if row.is_scored)

    def attempts(self, truth: CalibrationPairTruth) -> int:
        return len(self.of(truth))

    def failures(self, truth: CalibrationPairTruth) -> int:
        return sum(1 for row in self.of(truth) if not row.is_scored)

    @property
    def distinct_scores(self) -> tuple[Decimal, ...]:
        """Every distinct score, ascending.

        Grouped by *value*, so ``0.40`` and ``0.4`` are one score. That is what
        makes ties atomic: a boundary is a predicate over the value, and two
        comparisons with the same value cannot be separated by one
        (docs/adr/0080).
        """
        return tuple(sorted({row.score for row in self.rows if row.is_scored}))

    def content_hash(self) -> str:
        """A digest of the labelled results, independent of the order given.

        Used by verification to prove that a stored operating point was derived
        from *these* comparisons. It covers the canonical text of each score, so
        two bodies that differ only in how a score was spelled hash the same and
        two that differ in a digit do not.
        """
        from fpbench.core.decision_models import canonical_threshold

        return stable_hash(
            {
                "schema": "calibration_labeled_results_v1",
                "score_direction": self.score_direction.value,
                "rows": [
                    {
                        "pair_id": row.pair_id,
                        "truth": row.truth.value,
                        "execution_status": row.execution_status.value,
                        "score": (
                            canonical_threshold(row.score) if row.is_scored else None
                        ),
                        "failure_code": row.failure_code,
                    }
                    for row in self.rows
                ],
            },
            length=64,
        )


@dataclass(frozen=True, slots=True)
class CandidateBoundary:
    """A threshold and the comparator that says which side of it matches.

    Never persisted. It is the unit a selection considers and discards; only the
    one that survives becomes a :class:`CalibrationOperatingPoint`.

    ``decides`` is the whole of the class. Everything else in the selection —
    permissiveness, tie handling, the target check — is expressed in terms of
    what this returns, so there is exactly one definition of "is this score a
    match?" and no second one to drift from it.
    """

    threshold: Decimal
    comparator: ThresholdComparator

    def __post_init__(self) -> None:
        threshold = require_finite_decimal(self.threshold, "threshold")
        object.__setattr__(self, "threshold", threshold)
        if not isinstance(self.comparator, ThresholdComparator):
            raise CalibrationInputError("comparator must be a ThresholdComparator")

    def decides(self, score: Decimal) -> bool:
        """Whether this boundary calls ``score`` a match."""
        if self.comparator is ThresholdComparator.GREATER_THAN_OR_EQUAL:
            return score >= self.threshold
        if self.comparator is ThresholdComparator.GREATER_THAN:
            return score > self.threshold
        if self.comparator is ThresholdComparator.LESS_THAN_OR_EQUAL:
            return score <= self.threshold
        return score < self.threshold

    @property
    def canonical_threshold(self) -> str:
        """The one true spelling, as an operating point would store it."""
        from fpbench.core.decision_models import canonical_threshold

        return canonical_threshold(self.threshold)

    @property
    def is_inclusive(self) -> bool:
        return not self.comparator.is_strict


def labeled_results_hash(results: LabeledResults) -> str:
    return results.content_hash()


