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

Everything below is also the strict reader. There is no lenient path, no
coercion and no default:

* an unknown key is refused, because a key nothing reads is a claim nothing
  checks;
* a missing key is refused, because the default somebody would have chosen is
  exactly the thing that should have been written down;
* a duplicate JSON key is refused, because ``json`` silently keeps the last one
  and the two documents would fingerprint identically;
* ``NaN`` and ``Infinity`` are refused;
* a JSON number with a fractional part is refused outright — a score and a
  threshold are written as *strings* and read as ``Decimal``, so that no value in
  this package ever passes through binary floating point;
* ``true`` is not ``1`` and ``1`` is not ``"1"``;
* an enum spelling this project does not know is refused rather than guessed at.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping, Sequence

from fpbench.core.calibration_errors import (
    CalibrationInputError,
    CalibrationProtocolError,
    CalibrationSourceError,
)
from fpbench.core.calibration_models import (
    CALIBRATION_OPERATING_POINT_SCHEMA_VERSION,
    CALIBRATION_PROTOCOL_SCHEMA_VERSION,
    CALIBRATION_SOURCE_BINDING_SCHEMA_VERSION,
    PROTECTED_REGISTRY_SCHEMA_VERSION,
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
    require_digest,
    require_exact_bool,
)
from fpbench.core.enums import (
    CalibrationPairTruth,
    ExecutionStatus,
    ScoreDirection,
    ThresholdComparator,
)
from fpbench.core.serialization import require_exact_int, stable_hash

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
    "labeled_results_hash",
]


# ------------------------------------------------------------ strict reading


class _DuplicateJsonKey(ValueError):
    """A JSON object carried the same key twice."""


def _reject_duplicate_keys(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    seen: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            raise _DuplicateJsonKey(
                f"duplicate JSON key {key!r}; the parser would keep the last one "
                "and the two documents would be indistinguishable afterwards"
            )
        seen[key] = value
    return seen


def _reject_constant(name: str) -> Any:
    raise ValueError(f"{name} is not a value a calibration document may carry")


def _reject_fractional_literal(literal: str) -> Any:
    raise ValueError(
        f"the JSON number {literal!r} has a fractional part; a score, a threshold "
        "and a rate are written as strings and integers in this package, so that "
        "nothing here is ever a binary floating-point value (docs/adr/0080)"
    )


def strict_json_document(text: str) -> Mapping[str, Any]:
    """Parse one calibration document, refusing everything ambiguous.

    Raises:
        ValueError: the text is not JSON, is not an object at the top level,
            carries a duplicate key, a fractional number, ``NaN`` or an infinity.
    """
    try:
        document = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_float=_reject_fractional_literal,
            parse_constant=_reject_constant,
        )
    except _DuplicateJsonKey:
        raise
    except json.JSONDecodeError as exc:
        raise ValueError(f"not a readable JSON document: {exc}") from None
    if not isinstance(document, dict):
        raise ValueError("a calibration document is a JSON object at the top level")
    return document


def require_exact_keys(
    document: Mapping[str, Any], expected: Iterable[str], *, what: str
) -> None:
    """Exactly these keys: no more, no fewer.

    Both halves matter. A missing key would be filled in with a default nobody
    wrote down; an unknown key is a claim the reader does not check and the writer
    believes was honoured.
    """
    wanted = set(expected)
    present = set(map(str, document))
    missing = sorted(wanted - present)
    if missing:
        raise ValueError(f"{what} is missing {missing}")
    unknown = sorted(present - wanted)
    if unknown:
        raise ValueError(
            f"{what} carries keys nothing reads: {unknown}; an unrecognised key is "
            "refused rather than ignored"
        )


def read_str(document: Mapping[str, Any], key: str) -> str:
    value = document[key]
    if type(value) is not str:
        raise ValueError(f"{key} must be a string, got {type(value).__name__}")
    text = value.strip()
    if not text:
        raise ValueError(f"{key} must not be empty")
    return text


def read_int(document: Mapping[str, Any], key: str) -> int:
    """An exact integer. ``true`` is not ``1`` and ``"1"`` is not ``1``."""
    return require_exact_int(document[key], key)


def read_bool(document: Mapping[str, Any], key: str) -> bool:
    return require_exact_bool(document[key], key)


def read_digest(document: Mapping[str, Any], key: str) -> str:
    value = document[key]
    if type(value) is not str:
        raise ValueError(f"{key} must be a string, got {type(value).__name__}")
    return require_digest(value, key)


def read_enum(document: Mapping[str, Any], key: str, enum: Any) -> Any:
    """One of this project's spellings, or a refusal naming the ones it knows."""
    value = document[key]
    if type(value) is not str:
        raise ValueError(f"{key} must be a string, got {type(value).__name__}")
    try:
        return enum(value)
    except ValueError:
        known = ", ".join(sorted(member.value for member in enum))
        raise ValueError(
            f"{key} is {value!r}, which is not one of: {known}. An unknown "
            "vocabulary member is refused rather than guessed at"
        ) from None


def read_decimal_text(document: Mapping[str, Any], key: str) -> Decimal:
    """A decimal written as a string, read exactly.

    A JSON number would already have been refused by the parser. This is the
    positive half: the value is a string, and it becomes a ``Decimal`` built from
    that string's own digits rather than from a double.
    """
    value = document[key]
    if type(value) is not str:
        raise ValueError(
            f"{key} must be a decimal written as a string, got "
            f"{type(value).__name__}"
        )
    return require_finite_decimal(value, key)


def require_finite_decimal(value: object, field_name: str) -> Decimal:
    """An exact, finite ``Decimal``, refusing a ``float`` outright.

    A ``float`` is refused even though it would convert: the conversion is where
    ``0.1`` stops being one tenth, and a development score that arrived as a
    double has already lost whatever the algorithm actually produced
    (docs/adr/0073).
    """
    if isinstance(value, bool) or type(value) is float:
        raise ValueError(
            f"{field_name} must be a Decimal or a decimal string, never a "
            f"{type(value).__name__}"
        )
    if isinstance(value, Decimal):
        number = value
    else:
        try:
            number = Decimal(str(value).strip())
        except (InvalidOperation, ValueError, ArithmeticError):
            raise ValueError(f"{field_name} is not a decimal number: {value!r}") from None
    if not number.is_finite():
        raise ValueError(
            f"{field_name} must be finite; NaN and infinities divide nothing into "
            "matches and non-matches"
        )
    return number


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


# ------------------------------------------------- documents into artifacts


_PROTOCOL_KEYS = (
    "schema_version",
    "protocol_id",
    "protocol_version",
    "target_metric",
    "target_rate_numerator",
    "target_rate_denominator",
    "target_population",
    "threshold_selection_rule",
    "candidate_boundary_policy",
    "tie_policy",
    "score_population_policy",
    "failure_policy",
    "requires_cross_subject_impostors",
    "requires_development_role",
    "quality_filtering",
    "normalization",
    "metadata",
    "protocol_fingerprint",
)

_BINDING_KEYS = (
    "schema_version",
    "binding_id",
    "algorithm_id",
    "algorithm_fingerprint",
    "integration_id",
    "integration_fingerprint",
    "run_id",
    "run_fingerprint",
    "result_set_id",
    "result_set_fingerprint",
    "dataset_id",
    "dataset_fingerprint",
    "cohort_id",
    "cohort_fingerprint",
    "cohort_role",
    "pair_manifest_id",
    "pair_manifest_fingerprint",
    "score_direction",
    "metadata",
    "source_binding_fingerprint",
)

_REGISTRY_KEYS = (
    "schema_version",
    "registry_id",
    "registry_version",
    "entries",
    "registry_fingerprint",
)
_REGISTRY_ENTRY_KEYS = ("kind", "identity", "fingerprint", "label")

_OPERATING_POINT_KEYS = (
    "schema_version",
    "operating_point_id",
    "operating_point_fingerprint",
    "calibration_protocol_fingerprint",
    "source_binding_fingerprint",
    "algorithm_id",
    "algorithm_fingerprint",
    "threshold",
    "comparator",
    "score_direction",
    "target_rate_numerator",
    "target_rate_denominator",
    "observed_impostor_matches",
    "observed_impostor_scored",
    "observed_impostor_attempts",
    "impostor_failures",
    "observed_mated_matches",
    "observed_mated_non_matches",
    "observed_mated_scored",
    "observed_mated_attempts",
    "mated_failures",
    "selection_rule",
    "tie_policy",
    "created_source_commit",
    "created_source_tree_clean",
    "created_utc",
)


def _read_metadata(document: Mapping[str, Any], what: str) -> Mapping[str, str]:
    value = document["metadata"]
    if not isinstance(value, dict):
        raise ValueError(f"{what}: metadata must be a JSON object")
    for key, item in value.items():
        if type(item) is not str:
            raise ValueError(
                f"{what}: metadata[{key!r}] must be a string; a structured value "
                "there would be a claim outside the schema"
            )
    return {str(key): str(item) for key, item in value.items()}


def read_calibration_protocol(document: Mapping[str, Any]) -> CalibrationProtocol:
    """Build a protocol from a strictly parsed document, or refuse it."""
    from fpbench.core.enums import (
        CalibrationFailurePolicy,
        CalibrationTargetMetric,
        CalibrationTargetPopulation,
        CalibrationTiePolicy,
        CandidateBoundaryPolicy,
        ScoreNormalizationPolicy,
        ScorePopulationPolicy,
        ThresholdSelectionRule,
    )

    try:
        require_exact_keys(document, _PROTOCOL_KEYS, what="a calibration protocol")
        version = read_str(document, "schema_version")
        if version != CALIBRATION_PROTOCOL_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported calibration-protocol schema version {version!r}"
            )
        return CalibrationProtocol(
            schema_version=version,
            protocol_id=read_str(document, "protocol_id"),
            protocol_version=read_str(document, "protocol_version"),
            target_metric=read_enum(document, "target_metric", CalibrationTargetMetric),
            target_rate_numerator=read_int(document, "target_rate_numerator"),
            target_rate_denominator=read_int(document, "target_rate_denominator"),
            target_population=read_enum(
                document, "target_population", CalibrationTargetPopulation
            ),
            threshold_selection_rule=read_enum(
                document, "threshold_selection_rule", ThresholdSelectionRule
            ),
            candidate_boundary_policy=read_enum(
                document, "candidate_boundary_policy", CandidateBoundaryPolicy
            ),
            tie_policy=read_enum(document, "tie_policy", CalibrationTiePolicy),
            score_population_policy=read_enum(
                document, "score_population_policy", ScorePopulationPolicy
            ),
            failure_policy=read_enum(
                document, "failure_policy", CalibrationFailurePolicy
            ),
            requires_cross_subject_impostors=read_bool(
                document, "requires_cross_subject_impostors"
            ),
            requires_development_role=read_bool(document, "requires_development_role"),
            quality_filtering=read_bool(document, "quality_filtering"),
            normalization=read_enum(document, "normalization", ScoreNormalizationPolicy),
            metadata=_read_metadata(document, "a calibration protocol"),
            protocol_fingerprint=read_digest(document, "protocol_fingerprint"),
        )
    except CalibrationProtocolError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise CalibrationProtocolError(f"malformed calibration protocol: {exc}") from None


def read_calibration_source_binding(
    document: Mapping[str, Any],
) -> CalibrationSourceBinding:
    """Build a source binding from a strictly parsed document, or refuse it."""
    from fpbench.core.enums import CohortRole

    try:
        require_exact_keys(document, _BINDING_KEYS, what="a calibration source binding")
        version = read_str(document, "schema_version")
        if version != CALIBRATION_SOURCE_BINDING_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported calibration source-binding schema version {version!r}"
            )
        return CalibrationSourceBinding(
            schema_version=version,
            binding_id=read_str(document, "binding_id"),
            algorithm_id=read_str(document, "algorithm_id"),
            algorithm_fingerprint=read_digest(document, "algorithm_fingerprint"),
            integration_id=read_str(document, "integration_id"),
            integration_fingerprint=read_digest(document, "integration_fingerprint"),
            run_id=read_str(document, "run_id"),
            run_fingerprint=read_digest(document, "run_fingerprint"),
            result_set_id=read_str(document, "result_set_id"),
            result_set_fingerprint=read_digest(document, "result_set_fingerprint"),
            dataset_id=read_str(document, "dataset_id"),
            dataset_fingerprint=read_digest(document, "dataset_fingerprint"),
            cohort_id=read_str(document, "cohort_id"),
            cohort_fingerprint=read_digest(document, "cohort_fingerprint"),
            cohort_role=read_enum(document, "cohort_role", CohortRole),
            pair_manifest_id=read_str(document, "pair_manifest_id"),
            pair_manifest_fingerprint=read_digest(document, "pair_manifest_fingerprint"),
            score_direction=read_enum(document, "score_direction", ScoreDirection),
            metadata=_read_metadata(document, "a calibration source binding"),
            source_binding_fingerprint=read_digest(
                document, "source_binding_fingerprint"
            ),
        )
    except CalibrationSourceError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise CalibrationSourceError(
            f"malformed calibration source binding: {exc}"
        ) from None


def read_protected_evaluation_registry(
    document: Mapping[str, Any],
) -> ProtectedEvaluationRegistry:
    """Build the protected registry from a strictly parsed document."""
    from fpbench.core.enums import ProtectedIdentityKind

    try:
        require_exact_keys(
            document, _REGISTRY_KEYS, what="a protected evaluation registry"
        )
        version = read_str(document, "schema_version")
        if version != PROTECTED_REGISTRY_SCHEMA_VERSION:
            raise ValueError(f"unsupported protected-registry schema version {version!r}")
        raw_entries = document["entries"]
        if not isinstance(raw_entries, list):
            raise ValueError("entries must be a JSON array")
        entries = []
        for index, item in enumerate(raw_entries):
            if not isinstance(item, dict):
                raise ValueError(f"entries[{index}] must be a JSON object")
            require_exact_keys(
                item, _REGISTRY_ENTRY_KEYS, what=f"protected identity {index}"
            )
            entries.append(
                ProtectedEvaluationIdentity(
                    kind=read_enum(item, "kind", ProtectedIdentityKind),
                    identity=read_str(item, "identity"),
                    fingerprint=read_digest(item, "fingerprint"),
                    label=read_str(item, "label"),
                )
            )
        return ProtectedEvaluationRegistry(
            schema_version=version,
            registry_id=read_str(document, "registry_id"),
            registry_version=read_str(document, "registry_version"),
            entries=tuple(entries),
            registry_fingerprint=read_digest(document, "registry_fingerprint"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise CalibrationSourceError(
            f"malformed protected evaluation registry: {exc}"
        ) from None


def read_calibration_operating_point(
    document: Mapping[str, Any],
) -> CalibrationOperatingPoint:
    """Build an operating point from a strictly parsed document, or refuse it."""
    from fpbench.core.enums import CalibrationTiePolicy, ThresholdSelectionRule

    try:
        require_exact_keys(
            document, _OPERATING_POINT_KEYS, what="a calibration operating point"
        )
        version = read_str(document, "schema_version")
        if version != CALIBRATION_OPERATING_POINT_SCHEMA_VERSION:
            raise ValueError(f"unsupported operating-point schema version {version!r}")
        # Read as text and hand the text on: the model canonicalises it, and a
        # Decimal built from the document's own digits is the only kind that
        # cannot have been rounded on the way in.
        threshold = read_decimal_text(document, "threshold")
        return CalibrationOperatingPoint(
            schema_version=version,
            operating_point_id=read_str(document, "operating_point_id"),
            operating_point_fingerprint=read_digest(
                document, "operating_point_fingerprint"
            ),
            calibration_protocol_fingerprint=read_digest(
                document, "calibration_protocol_fingerprint"
            ),
            source_binding_fingerprint=read_digest(
                document, "source_binding_fingerprint"
            ),
            algorithm_id=read_str(document, "algorithm_id"),
            algorithm_fingerprint=read_digest(document, "algorithm_fingerprint"),
            threshold=threshold,
            comparator=read_enum(document, "comparator", ThresholdComparator),
            score_direction=read_enum(document, "score_direction", ScoreDirection),
            target_rate_numerator=read_int(document, "target_rate_numerator"),
            target_rate_denominator=read_int(document, "target_rate_denominator"),
            observed_impostor_matches=read_int(document, "observed_impostor_matches"),
            observed_impostor_scored=read_int(document, "observed_impostor_scored"),
            observed_impostor_attempts=read_int(document, "observed_impostor_attempts"),
            impostor_failures=read_int(document, "impostor_failures"),
            observed_mated_matches=read_int(document, "observed_mated_matches"),
            observed_mated_non_matches=read_int(document, "observed_mated_non_matches"),
            observed_mated_scored=read_int(document, "observed_mated_scored"),
            observed_mated_attempts=read_int(document, "observed_mated_attempts"),
            mated_failures=read_int(document, "mated_failures"),
            selection_rule=read_enum(document, "selection_rule", ThresholdSelectionRule),
            tie_policy=read_enum(document, "tie_policy", CalibrationTiePolicy),
            created_source_commit=read_str(document, "created_source_commit"),
            created_source_tree_clean=read_bool(document, "created_source_tree_clean"),
            created_utc=read_str(document, "created_utc"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise CalibrationInputError(
            f"malformed calibration operating point: {exc}"
        ) from None
