"""Comparing two algorithms over one body of inputs, without comparing scores.

Stage 6B already has a paired-comparison vocabulary, and none of it applies
here. That one compares two runs of *the same algorithm* under two image
preparations: a score delta is a meaningful quantity, an exactly-equal control
set is the argument, and "the canonical side scored lower" is a sentence with a
referent. Stage 7D compares SourceAFIS with NBIS. A BOZORTH3 score of 41 and a
SourceAFIS score of 41 are two numbers on two scales produced by two matchers,
and subtracting them would produce a quantity with no unit (docs/adr/0060,
spec section 53).

So this module has no field for a score, and it is designed so that adding one
is awkward rather than merely discouraged: :func:`require_no_score_comparison`
walks the rendered document and refuses any of the names a score comparison
would have to be called, and a structural test refuses the module the imports it
would need.

Four ideas carry the rest.

**Left and right, never native and canonical.** The two sides are labelled by
their algorithms, the labels are inside every fingerprint, and every difference
is defined once and in one direction: ``right_minus_left`` (spec section 55).

**A difference is an exact fraction.** ``a/b - c/d`` is stored as an integer
numerator and an integer denominator, reduced, and a decimal is derived from it
for display only. Two rates that differ in the fourth decimal place differ; a
report that rounded first would say they did not (spec section 60).

**A difference is stored only when the populations permit one.** Two conditional
rates over two different eligible sets are two measurements, and their
subtraction is not defined — so the model has nowhere to put it
(docs/adr/0038, spec section 61).

**Nothing here concludes anything.** Every receipt and every report carries
:data:`NO_SUPERIORITY_STATEMENT` verbatim, and the statement is inside the
comparison policy fingerprint, so a document that dropped it would not
fingerprint to the policy it claims to follow (docs/adr/0058, spec section 63).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from math import gcd
from typing import Any, Iterable, Mapping

from fpbench.core.enums import (
    CrossAlgorithmPopulation,
    CrossAlgorithmStatus,
    CrossAlgorithmTransitionFamily,
    DecisionOutcome,
    SelfEligibilityStatus,
)
from fpbench.core.identifiers import validate_id
from fpbench.core.run_state_models import IntegrityIssue
from fpbench.core.serialization import require_exact_int, stable_hash, to_plain

__all__ = [
    "CROSS_ALGORITHM_SCHEMA_VERSION",
    "CROSS_ALGORITHM_ID_LENGTH",
    "NO_SUPERIORITY_STATEMENT",
    "OPERATING_POINT_RELATION",
    "FORBIDDEN_SCORE_FIELDS",
    "ExactRate",
    "RateDifference",
    "FairMeasurementProtocol",
    "FairComparabilityAudit",
    "CrossAlgorithmEvaluationDefinition",
    "CrossAlgorithmComparisonRecord",
    "CrossAlgorithmEligibilityTransition",
    "CrossAlgorithmCommonEligibleEntry",
    "CrossAlgorithmCountRecord",
    "CrossAlgorithmObservation",
    "CrossAlgorithmEvaluationManifest",
    "CrossAlgorithmEvaluationReceipt",
    "CrossAlgorithmFinalization",
    "CrossAlgorithmEvaluationState",
    "exact_rate",
    "rate_difference",
    "fair_measurement_protocol_fingerprint",
    "fair_comparability_audit_fingerprint",
    "cross_algorithm_definition_fingerprint",
    "comparison_record_hash",
    "ordered_comparison_records_hash",
    "ordered_eligibility_transitions_hash",
    "ordered_common_eligible_hash",
    "ordered_count_records_hash",
    "ordered_observations_hash",
    "cross_algorithm_evaluation_fingerprint",
    "cross_algorithm_evaluation_id",
    "cross_algorithm_receipt_fingerprint",
    "cross_algorithm_receipt_content_hash",
    "cross_algorithm_finalization_fingerprint",
    "require_no_score_comparison",
]

CROSS_ALGORITHM_SCHEMA_VERSION = "1"
CROSS_ALGORITHM_ID_LENGTH = 12

#: Printed verbatim into the comparison receipt and the report, and inside the
#: comparison policy fingerprint. Somebody will eventually read only one of those
#: files, and every sentence they could reasonably infer from a table of paired
#: outcomes has to be refused in advance (spec section 63).
NO_SUPERIORITY_STATEMENT = (
    "This comparison uses independently documented, uncalibrated operating "
    "points on identical inputs. It records paired observed outcomes. It does "
    "not establish equal FMR, general algorithm superiority, causality, or "
    "statistical significance."
)

#: The only relation this project asserts between the two operating points. Both
#: thresholds are written "40"; they came from two documents about two score
#: scales, and the digits agreeing is a coincidence of notation
#: (docs/adr/0058, spec section 6).
OPERATING_POINT_RELATION = "independently_documented_not_equated"

#: Names a raw-score comparison would have to use. Checked over the rendered
#: document rather than field by field, so a field added later is covered
#: without anyone remembering to extend a list (spec section 52).
FORBIDDEN_SCORE_FIELDS: frozenset[str] = frozenset(
    {
        "left_score",
        "right_score",
        "sourceafis_score",
        "nbis_score",
        "raw_score",
        "raw_scores",
        "score",
        "scores",
        "score_delta",
        "score_relation",
        "score_ratio",
        "score_difference",
        "normalised_score",
        "normalized_score",
        "rank_correlation",
        "correlation",
        "score_distribution",
        "mean_score",
        "median_score",
    }
)

_HEX = frozenset("0123456789abcdef")
_PATH_LIKE = re.compile(r"(^[A-Za-z]:[\\/])|(^\\\\)|(^/)|(\\)")


def _require_digest(value: str, field_name: str) -> str:
    digest = str(value).strip().lower()
    if len(digest) != 64 or not set(digest) <= _HEX:
        raise ValueError(f"{field_name} must be a 64-character hexadecimal digest")
    return digest


def _require_commit(value: str, field_name: str) -> str:
    commit = str(value).strip().lower()
    if len(commit) != 40 or not set(commit) <= _HEX:
        raise ValueError(f"{field_name} must be a full 40-character commit SHA")
    return commit


def require_no_score_comparison(document: Any, *, path: str = "document") -> None:
    """Refuse a document carrying anything a score comparison would need.

    Mechanical, and therefore only as good as :data:`FORBIDDEN_SCORE_FIELDS` —
    but the mistake it catches is exactly the one that is easy to make and hard
    to notice. Somebody adds ``score_delta`` "just for diagnostics", it reaches a
    report, and a reader subtracts two numbers on two different scales.

    Raises:
        ValueError: a forbidden key appears, or a value looks like a filesystem
            path.
    """
    _walk(to_plain(document), path=path)


def _walk(value: Any, *, path: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).lower() in FORBIDDEN_SCORE_FIELDS:
                raise ValueError(
                    f"{path}.{key} must not appear in a cross-algorithm document: "
                    "the two algorithms' scores are not on a common scale, so no "
                    "arithmetic over them is defined (docs/adr/0060)"
                )
            _walk(item, path=f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _walk(item, path=f"{path}[{index}]")
        return
    if isinstance(value, str) and _PATH_LIKE.search(value):
        raise ValueError(f"{path} looks like a filesystem path: {value!r}")


# ------------------------------------------------------------------- rates


@dataclass(frozen=True, slots=True)
class ExactRate:
    """A count over a count, kept as two integers.

    ``value`` is derived for display and is never what anything is compared on.
    A rate whose stored form was a float would be a rate that could not be added
    to another one exactly, and pooling is defined as summing counts and
    dividing once (docs/adr/0028).
    """

    numerator: int
    denominator: int

    def __post_init__(self) -> None:
        numerator = require_exact_int(self.numerator, "numerator")
        denominator = require_exact_int(self.denominator, "denominator")
        if numerator < 0:
            raise ValueError("a count numerator must not be negative")
        if denominator < 0:
            raise ValueError("a count denominator must not be negative")
        if denominator and numerator > denominator:
            raise ValueError(
                f"{numerator} of {denominator} is not a rate; a numerator counts a "
                "subset of its denominator"
            )
        object.__setattr__(self, "numerator", numerator)
        object.__setattr__(self, "denominator", denominator)

    @property
    def is_defined(self) -> bool:
        """A zero denominator is not zero. It is "nothing was covered"."""
        return self.denominator > 0

    @property
    def value(self) -> Decimal | None:
        if not self.is_defined:
            return None
        return Decimal(self.numerator) / Decimal(self.denominator)


def exact_rate(numerator: int, denominator: int) -> ExactRate:
    return ExactRate(numerator=numerator, denominator=denominator)


@dataclass(frozen=True, slots=True)
class RateDifference:
    """``right - left``, as one reduced fraction, or nothing at all.

    ``None`` numerator and denominator mean the difference is *undefined* — the
    populations did not permit one, or a side had nothing to divide by. That is
    a third state and not a zero: rendering an undefined difference as ``0.0000``
    would state an agreement nobody measured (spec sections 44, 60 and 61).
    """

    population: CrossAlgorithmPopulation
    difference_numerator: int | None = None
    difference_denominator: int | None = None

    def __post_init__(self) -> None:
        numerator = self.difference_numerator
        denominator = self.difference_denominator
        if (numerator is None) != (denominator is None):
            raise ValueError(
                "a rate difference is a numerator and a denominator together"
            )
        if numerator is None:
            return
        numerator = require_exact_int(numerator, "difference_numerator")
        denominator = require_exact_int(denominator, "difference_denominator")
        if denominator <= 0:
            raise ValueError("difference_denominator must be positive")
        if not self.population.permits_difference:
            raise ValueError(
                f"population {self.population.value!r} does not permit a rate "
                "difference; two rates over different populations differ by the "
                "sum of the effect and the change in who was counted "
                "(docs/adr/0038)"
            )
        object.__setattr__(self, "difference_numerator", numerator)
        object.__setattr__(self, "difference_denominator", denominator)

    @property
    def is_defined(self) -> bool:
        return self.difference_numerator is not None

    @property
    def value(self) -> Decimal | None:
        """Display only. The fraction above is what is stored and compared."""
        if not self.is_defined:
            return None
        return Decimal(int(self.difference_numerator)) / Decimal(
            int(self.difference_denominator)
        )


def rate_difference(
    *,
    left: ExactRate,
    right: ExactRate,
    population: CrossAlgorithmPopulation,
) -> RateDifference:
    """``right - left`` as an exact reduced fraction, when that is defined.

    Undefined — and stored as such — when either side has a zero denominator or
    when the population does not permit subtraction. There is no fallback to
    zero and no fallback to the defined side (spec sections 60 and 61).
    """
    if not population.permits_difference or not (left.is_defined and right.is_defined):
        return RateDifference(population=population)
    numerator = (
        right.numerator * left.denominator - left.numerator * right.denominator
    )
    denominator = right.denominator * left.denominator
    divisor = gcd(abs(numerator), denominator) or 1
    return RateDifference(
        population=population,
        difference_numerator=numerator // divisor,
        difference_denominator=denominator // divisor,
    )


# ------------------------------------------------------- the frozen protocol


@dataclass(frozen=True, slots=True)
class FairMeasurementProtocol:
    """The methodology, fixed and committed before a single decision is derived.

    This is the artefact that makes stage 7D a measurement rather than a search.
    Everything that could be chosen — which runs, which profiles, which
    eligibility rule, which metric policy, what relation the two operating points
    stand in — is written down and fingerprinted *first*, so that no later result
    can have influenced any of it (spec section 12).

    Four of the identity fields are empty at the moment of committing, because
    they cannot be known: a decision set's id is derived from the decisions. They
    are the only fields the protocol allows to be bound afterwards, and binding
    one does not change the protocol fingerprint — that is what
    :meth:`bind` exists to enforce (spec section 13).
    """

    schema_version: str
    protocol_id: str

    sourceafis_run_id: str
    sourceafis_result_set_id: str
    sourceafis_decision_set_id: str
    sourceafis_eligibility_set_id: str
    sourceafis_metric_set_id: str

    nbis_run_id: str
    nbis_result_set_id: str
    stage_7c_finalization_fingerprint: str

    alignment_fingerprint: str
    preparation_set_id: str
    preparation_set_fingerprint: str

    sourceafis_decision_profile_fingerprint: str
    nbis_decision_profile_fingerprint: str

    eligibility_policy_id: str
    eligibility_policy_version: str
    metric_policy_id: str
    metric_policy_fingerprint: str
    comparison_policy_fingerprint: str

    operating_point_relation: str
    raw_score_comparison: bool
    calibration_performed: bool
    test_cohort_used: bool

    protocol_fingerprint: str

    #: Bound after the derivations exist. Outside the protocol fingerprint by
    #: construction: an id that could not be known when the methodology was
    #: frozen cannot be part of what was frozen (spec section 13).
    nbis_decision_set_id: str | None = None
    nbis_eligibility_set_id: str | None = None
    nbis_metric_set_id: str | None = None
    cross_algorithm_evaluation_id: str | None = None

    def __post_init__(self) -> None:
        version = str(self.schema_version).strip()
        if version != CROSS_ALGORITHM_SCHEMA_VERSION:
            raise ValueError(f"unsupported protocol schema version {version!r}")
        object.__setattr__(self, "schema_version", version)

        for name in (
            "protocol_id",
            "sourceafis_run_id",
            "sourceafis_result_set_id",
            "sourceafis_decision_set_id",
            "sourceafis_eligibility_set_id",
            "sourceafis_metric_set_id",
            "nbis_run_id",
            "nbis_result_set_id",
            "preparation_set_id",
            "eligibility_policy_id",
            "metric_policy_id",
        ):
            validate_id(str(getattr(self, name)))
        for name in (
            "nbis_decision_set_id",
            "nbis_eligibility_set_id",
            "nbis_metric_set_id",
            "cross_algorithm_evaluation_id",
        ):
            value = getattr(self, name)
            if value is not None:
                validate_id(str(value))
        for name in (
            "stage_7c_finalization_fingerprint",
            "alignment_fingerprint",
            "preparation_set_fingerprint",
            "sourceafis_decision_profile_fingerprint",
            "nbis_decision_profile_fingerprint",
            "metric_policy_fingerprint",
            "comparison_policy_fingerprint",
            "protocol_fingerprint",
        ):
            object.__setattr__(self, name, _require_digest(getattr(self, name), name))

        if (
            self.sourceafis_decision_profile_fingerprint
            == self.nbis_decision_profile_fingerprint
        ):
            raise ValueError(
                "the two decision profiles fingerprint identically; they describe "
                "different algorithms and different comparators and cannot"
            )

        if self.operating_point_relation != OPERATING_POINT_RELATION:
            raise ValueError(
                f"operating_point_relation must be {OPERATING_POINT_RELATION!r}, "
                f"got {self.operating_point_relation!r}. The two thresholds are "
                "both written '40' and are not the same operating point "
                "(docs/adr/0058)"
            )
        for name in ("raw_score_comparison", "calibration_performed", "test_cohort_used"):
            value = getattr(self, name)
            if type(value) is not bool:
                raise ValueError(f"{name} must be a boolean")
            if value:
                raise ValueError(
                    f"{name} is true, but nothing in stage 7D does it. A protocol "
                    "that declared it would be describing a study this one is not"
                )

        recomputed = fair_measurement_protocol_fingerprint(self)
        if self.protocol_fingerprint != recomputed:
            raise ValueError(
                "protocol_fingerprint does not cover the protocol it is attached "
                "to"
            )

    @property
    def is_bound(self) -> bool:
        """Whether every id that could only be known afterwards has been."""
        return all(
            getattr(self, name) is not None
            for name in (
                "nbis_decision_set_id",
                "nbis_eligibility_set_id",
                "nbis_metric_set_id",
            )
        )

    def bind(self, **identities: str) -> "FairMeasurementProtocol":
        """Fill in ids that could not exist when the methodology was frozen.

        Only the four late-binding fields may be named. Anything else — a
        threshold, a comparator, a policy, the operating-point relation — needs a
        new ``protocol_id``, a new fingerprint and a new derivation, because
        changing it after seeing a result is the definition of the thing this
        artefact exists to prevent (spec section 13).

        Raises:
            ValueError: a field outside the late-binding set was named, or a
                field already bound to a different value was rebound.
        """
        import dataclasses

        allowed = {
            "nbis_decision_set_id",
            "nbis_eligibility_set_id",
            "nbis_metric_set_id",
            "cross_algorithm_evaluation_id",
        }
        unknown = sorted(set(identities) - allowed)
        if unknown:
            raise ValueError(
                f"a committed measurement protocol may not change {unknown}; only "
                f"{sorted(allowed)} may be bound afterwards, and everything else "
                "needs a new protocol_id and a new derivation"
            )
        for name, value in identities.items():
            current = getattr(self, name)
            if current is not None and current != value:
                raise ValueError(
                    f"{name} is already bound to {current!r}; rebinding it would "
                    "silently repoint a committed protocol at a different artefact"
                )
        return dataclasses.replace(self, **identities)


def fair_measurement_protocol_fingerprint(
    protocol: FairMeasurementProtocol | Mapping[str, Any],
) -> str:
    """The protocol's identity, excluding its own digest and the late bindings.

    The four late-bound ids are outside it by construction rather than by
    omission: they did not exist when the methodology was frozen, so a
    fingerprint that covered them could not have been computed then, and a
    protocol whose digest changed when a derivation completed would not be a
    frozen protocol at all (spec section 13).
    """
    plain = dict(to_plain(protocol))
    for name in (
        "protocol_fingerprint",
        "nbis_decision_set_id",
        "nbis_eligibility_set_id",
        "nbis_metric_set_id",
        "cross_algorithm_evaluation_id",
    ):
        plain.pop(name, None)
    return stable_hash(
        {"schema": "fair_measurement_protocol_v1", "protocol": plain}, length=64
    )


# ------------------------------------------------------- the fairness audit


@dataclass(frozen=True, slots=True)
class FairComparabilityAudit:
    """Whether the two chains were measuring the same thing at all.

    Built before a single paired record exists, and every flag is the outcome of
    an equality between two loaded artefacts rather than a declaration. A clean
    gate needs all six equalities true, all three calibration flags false, and
    both "did we cheat" flags false (spec section 56).

    The two negative flags read oddly and are deliberate. ``operating_points_equated``
    and ``raw_scores_compared`` must be *false*: they record that the comparison
    did not do the two things that would have made it easy and wrong.
    """

    protocol_fingerprint: str

    pair_alignment_fingerprint: str
    pair_ids_equal: bool
    pair_semantics_equal: bool
    prepared_entries_equal: bool

    eligibility_policy_equal: bool
    metric_policy_equal: bool
    execution_profile_equal: bool

    left_profile_origin: str
    right_profile_origin: str
    left_calibrated: bool
    right_calibrated: bool
    test_cohort_used: bool

    operating_points_equated: bool
    raw_scores_compared: bool

    issues: tuple[IntegrityIssue, ...]
    audit_fingerprint: str

    def __post_init__(self) -> None:
        for name in ("protocol_fingerprint", "pair_alignment_fingerprint"):
            object.__setattr__(self, name, _require_digest(getattr(self, name), name))
        for name in (
            "pair_ids_equal",
            "pair_semantics_equal",
            "prepared_entries_equal",
            "eligibility_policy_equal",
            "metric_policy_equal",
            "execution_profile_equal",
            "left_calibrated",
            "right_calibrated",
            "test_cohort_used",
            "operating_points_equated",
            "raw_scores_compared",
        ):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be a boolean")
        for name in ("left_profile_origin", "right_profile_origin"):
            value = str(getattr(self, name)).strip()
            if not value:
                raise ValueError(f"{name} must not be empty")
            object.__setattr__(self, name, value)
        object.__setattr__(self, "issues", tuple(self.issues))
        recomputed = fair_comparability_audit_fingerprint(self)
        if self.audit_fingerprint != recomputed:
            raise ValueError("audit_fingerprint does not cover this audit")

    @property
    def required_true(self) -> tuple[str, ...]:
        return (
            "pair_ids_equal",
            "pair_semantics_equal",
            "prepared_entries_equal",
            "eligibility_policy_equal",
            "metric_policy_equal",
            "execution_profile_equal",
        )

    @property
    def required_false(self) -> tuple[str, ...]:
        return (
            "left_calibrated",
            "right_calibrated",
            "test_cohort_used",
            "operating_points_equated",
            "raw_scores_compared",
        )

    @property
    def is_clean(self) -> bool:
        return (
            all(getattr(self, name) for name in self.required_true)
            and not any(getattr(self, name) for name in self.required_false)
            and not self.issues
        )

    @property
    def failures(self) -> tuple[str, ...]:
        """Which named conditions are not met, in a stable order."""
        failed = [name for name in self.required_true if not getattr(self, name)]
        failed.extend(name for name in self.required_false if getattr(self, name))
        return tuple(failed)


def fair_comparability_audit_fingerprint(
    audit: FairComparabilityAudit | Mapping[str, Any],
) -> str:
    plain = dict(to_plain(audit))
    plain.pop("audit_fingerprint", None)
    return stable_hash(
        {"schema": "fair_comparability_audit_v1", "audit": plain}, length=64
    )


# ------------------------------------------------------------- the definition


@dataclass(frozen=True, slots=True)
class CrossAlgorithmEvaluationDefinition:
    """What a comparison is going to be, fixed before it is carried out.

    Both sides are named by every identity that could change a number, in one
    direction: ``left`` is the algorithm whose decisions are the reference point
    for a difference, ``right`` is the one subtracted *from* it. The labels are
    inside the fingerprint, so swapping the sides is a different comparison
    rather than the same one read backwards (spec section 55).
    """

    definition_id: str
    definition_fingerprint: str

    protocol_id: str
    protocol_fingerprint: str

    left_label: str
    left_run_id: str
    left_run_fingerprint: str
    left_result_set_fingerprint: str
    left_decision_set_id: str
    left_decision_set_fingerprint: str
    left_eligibility_set_id: str
    left_eligibility_set_fingerprint: str
    left_metric_set_id: str
    left_metric_set_fingerprint: str
    left_decision_profile_fingerprint: str

    right_label: str
    right_run_id: str
    right_run_fingerprint: str
    right_result_set_fingerprint: str
    right_decision_set_id: str
    right_decision_set_fingerprint: str
    right_eligibility_set_id: str
    right_eligibility_set_fingerprint: str
    right_metric_set_id: str
    right_metric_set_fingerprint: str
    right_decision_profile_fingerprint: str

    alignment_fingerprint: str
    pair_manifest_hash: str
    preparation_set_fingerprint: str

    eligibility_policy_id: str
    eligibility_policy_version: str
    metric_policy_fingerprint: str
    comparison_policy_fingerprint: str

    comparison_software_fingerprint: str
    comparison_source_commit: str

    created_utc: str

    def __post_init__(self) -> None:
        for name in (
            "definition_id",
            "protocol_id",
            "left_run_id",
            "left_decision_set_id",
            "left_eligibility_set_id",
            "left_metric_set_id",
            "right_run_id",
            "right_decision_set_id",
            "right_eligibility_set_id",
            "right_metric_set_id",
            "eligibility_policy_id",
        ):
            validate_id(str(getattr(self, name)))
        for name in (
            "definition_fingerprint",
            "protocol_fingerprint",
            "left_run_fingerprint",
            "left_result_set_fingerprint",
            "left_decision_set_fingerprint",
            "left_eligibility_set_fingerprint",
            "left_metric_set_fingerprint",
            "left_decision_profile_fingerprint",
            "right_run_fingerprint",
            "right_result_set_fingerprint",
            "right_decision_set_fingerprint",
            "right_eligibility_set_fingerprint",
            "right_metric_set_fingerprint",
            "right_decision_profile_fingerprint",
            "alignment_fingerprint",
            "pair_manifest_hash",
            "preparation_set_fingerprint",
            "metric_policy_fingerprint",
            "comparison_policy_fingerprint",
            "comparison_software_fingerprint",
        ):
            object.__setattr__(self, name, _require_digest(getattr(self, name), name))
        object.__setattr__(
            self,
            "comparison_source_commit",
            _require_commit(self.comparison_source_commit, "comparison_source_commit"),
        )
        for name in ("left_label", "right_label"):
            value = str(getattr(self, name)).strip()
            if not value:
                raise ValueError(f"{name} must not be empty")
            object.__setattr__(self, name, value)
        if self.left_label == self.right_label:
            raise ValueError(
                "the two sides carry the same label; a comparison of an algorithm "
                "with itself is not what this artefact is for"
            )
        if self.left_run_id == self.right_run_id:
            raise ValueError(
                "both sides name run "
                f"{self.left_run_id}; two algorithms produce two runs"
            )
        created = str(self.created_utc).strip()
        if not created:
            raise ValueError("created_utc must not be empty")
        object.__setattr__(self, "created_utc", created)

        expected = cross_algorithm_definition_fingerprint(self)
        if self.definition_fingerprint != expected:
            raise ValueError(
                "definition_fingerprint does not cover the definition's claims"
            )
        expected_id = f"algcomparedef_{expected[:CROSS_ALGORITHM_ID_LENGTH]}"
        if self.definition_id != expected_id:
            raise ValueError(
                f"definition_id must be {expected_id!r}, got {self.definition_id!r}"
            )


def cross_algorithm_definition_fingerprint(
    definition: CrossAlgorithmEvaluationDefinition | Mapping[str, Any],
) -> str:
    plain = dict(to_plain(definition))
    for name in ("definition_id", "definition_fingerprint", "created_utc"):
        plain.pop(name, None)
    return stable_hash(
        {"schema": "cross_algorithm_definition_v1", "definition": plain}, length=64
    )


# ----------------------------------------------------------------- records


@dataclass(frozen=True, slots=True)
class CrossAlgorithmComparisonRecord:
    """One pair, and what each algorithm decided about it.

    Five hashes and two outcomes. No score, no delta, and no field either could
    hide in: what is recorded is *which stored artefacts* the two outcomes came
    from, so a reader can go back to them, and the outcomes themselves
    (spec sections 51 and 52).
    """

    ordinal: int
    pair_id: str
    release: str
    protocol_stage: str

    left_decision_hash: str
    right_decision_hash: str
    left_raw_result_hash: str
    right_raw_result_hash: str

    left_outcome: DecisionOutcome
    right_outcome: DecisionOutcome

    record_hash: str

    def __post_init__(self) -> None:
        ordinal = require_exact_int(self.ordinal, "ordinal")
        if ordinal < 0:
            raise ValueError("ordinal is 0-based and must not be negative")
        object.__setattr__(self, "ordinal", ordinal)
        for name in ("pair_id", "release", "protocol_stage"):
            value = str(getattr(self, name)).strip()
            if not value:
                raise ValueError(f"{name} must not be empty")
            object.__setattr__(self, name, value)
        for name in (
            "left_decision_hash",
            "right_decision_hash",
            "left_raw_result_hash",
            "right_raw_result_hash",
            "record_hash",
        ):
            object.__setattr__(self, name, _require_digest(getattr(self, name), name))
        recomputed = comparison_record_hash(self)
        if self.record_hash != recomputed:
            raise ValueError("record_hash does not cover this comparison record")

    @property
    def changed(self) -> bool:
        return self.left_outcome is not self.right_outcome


def comparison_record_hash(record: CrossAlgorithmComparisonRecord) -> str:
    return stable_hash(
        {
            "schema": "cross_algorithm_comparison_record_v1",
            "ordinal": record.ordinal,
            "pair_id": record.pair_id,
            "release": record.release,
            "protocol_stage": record.protocol_stage,
            "left_decision_hash": record.left_decision_hash,
            "right_decision_hash": record.right_decision_hash,
            "left_raw_result_hash": record.left_raw_result_hash,
            "right_raw_result_hash": record.right_raw_result_hash,
            "left_outcome": record.left_outcome.value,
            "right_outcome": record.right_outcome.value,
        },
        length=64,
    )


@dataclass(frozen=True, slots=True)
class CrossAlgorithmEligibilityTransition:
    """One eligibility unit, and what each side made of it.

    Keyed by ``eligibility_unit_id`` rather than by ordinal, because an ordinal
    is a property of an ordering and a unit is a property of a finger. The two
    agree today and the check that they do is what makes it safe to say so
    (spec section 46).
    """

    ordinal: int
    eligibility_unit_id: str
    release: str

    #: The mated PLAIN-ROLL comparison this unit governs. Carried so that "which
    #: rows did each side's conditional view keep?" is answerable from the
    #: transitions alone — one selection rule applied twice, rather than two
    #: stored views that happen to agree (docs/adr/0024).
    mated_pair_id: str

    left_status: SelfEligibilityStatus
    right_status: SelfEligibilityStatus

    left_record_hash: str
    right_record_hash: str

    def __post_init__(self) -> None:
        ordinal = require_exact_int(self.ordinal, "ordinal")
        if ordinal < 0:
            raise ValueError("ordinal is 0-based and must not be negative")
        object.__setattr__(self, "ordinal", ordinal)
        validate_id(str(self.eligibility_unit_id))
        for name in ("release", "mated_pair_id"):
            value = str(getattr(self, name)).strip()
            if not value:
                raise ValueError(f"{name} must not be empty")
            object.__setattr__(self, name, value)
        for name in ("left_record_hash", "right_record_hash"):
            object.__setattr__(self, name, _require_digest(getattr(self, name), name))

    @property
    def is_common_eligible(self) -> bool:
        return (
            self.left_status is SelfEligibilityStatus.ELIGIBLE
            and self.right_status is SelfEligibilityStatus.ELIGIBLE
        )


@dataclass(frozen=True, slots=True)
class CrossAlgorithmCommonEligibleEntry:
    """A unit both algorithms proved usable, and the mated pair it governs.

    The intersection is a *controlled secondary* analysis and the model says so
    by keeping it in its own record type. It filters out exactly the units that
    were hard for either algorithm, which is informative and is not the headline
    (spec sections 46 and 47).
    """

    ordinal: int
    eligibility_unit_id: str
    release: str
    mated_pair_id: str

    left_outcome: DecisionOutcome
    right_outcome: DecisionOutcome

    def __post_init__(self) -> None:
        ordinal = require_exact_int(self.ordinal, "ordinal")
        if ordinal < 0:
            raise ValueError("ordinal is 0-based and must not be negative")
        object.__setattr__(self, "ordinal", ordinal)
        validate_id(str(self.eligibility_unit_id))
        for name in ("release", "mated_pair_id"):
            value = str(getattr(self, name)).strip()
            if not value:
                raise ValueError(f"{name} must not be empty")
            object.__setattr__(self, name, value)


@dataclass(frozen=True, slots=True)
class CrossAlgorithmCountRecord:
    """One counted cell: a family, a scope, a side, an outcome, a number.

    Everything the report shows is derived from these and nothing else, so a
    number in the report can always be traced to a row here, and a row here can
    always be traced to the records it counted.
    """

    family: CrossAlgorithmTransitionFamily
    scope: str
    left_outcome: DecisionOutcome | None
    right_outcome: DecisionOutcome | None
    count: int

    def __post_init__(self) -> None:
        scope = str(self.scope).strip()
        if not scope:
            raise ValueError("scope must not be empty")
        object.__setattr__(self, "scope", scope)
        count = require_exact_int(self.count, "count")
        if count < 0:
            raise ValueError("count must not be negative")
        object.__setattr__(self, "count", count)


@dataclass(frozen=True, slots=True)
class CrossAlgorithmObservation:
    """One comparable quantity, with both sides' fractions and their difference.

    ``population`` is not decoration. It decides whether ``difference`` is
    allowed to carry anything at all, and the model refuses to construct an
    observation whose difference contradicts it (spec section 61).
    """

    observation_id: str
    metric_id: str
    scope: str

    population: CrossAlgorithmPopulation

    left_numerator: int
    left_denominator: int
    right_numerator: int
    right_denominator: int

    difference_numerator: int | None
    difference_denominator: int | None

    def __post_init__(self) -> None:
        validate_id(str(self.observation_id))
        for name in ("metric_id", "scope"):
            value = str(getattr(self, name)).strip()
            if not value:
                raise ValueError(f"{name} must not be empty")
            object.__setattr__(self, name, value)
        left = ExactRate(
            numerator=self.left_numerator, denominator=self.left_denominator
        )
        right = ExactRate(
            numerator=self.right_numerator, denominator=self.right_denominator
        )
        expected = rate_difference(
            left=left, right=right, population=self.population
        )
        if (
            expected.difference_numerator != self.difference_numerator
            or expected.difference_denominator != self.difference_denominator
        ):
            raise ValueError(
                f"observation {self.observation_id} stores difference "
                f"{self.difference_numerator}/{self.difference_denominator}, but "
                f"{right.numerator}/{right.denominator} - "
                f"{left.numerator}/{left.denominator} under population "
                f"{self.population.value!r} is "
                f"{expected.difference_numerator}/{expected.difference_denominator}"
            )

    @property
    def left(self) -> ExactRate:
        return ExactRate(
            numerator=self.left_numerator, denominator=self.left_denominator
        )

    @property
    def right(self) -> ExactRate:
        return ExactRate(
            numerator=self.right_numerator, denominator=self.right_denominator
        )

    @property
    def difference(self) -> RateDifference:
        return RateDifference(
            population=self.population,
            difference_numerator=self.difference_numerator,
            difference_denominator=self.difference_denominator,
        )


# ---------------------------------------------------------------- manifest


def _ordered_hash(schema: str, rows: Iterable[Any]) -> str:
    return stable_hash({"schema": schema, "rows": [to_plain(r) for r in rows]}, length=64)


def ordered_comparison_records_hash(
    records: Iterable[CrossAlgorithmComparisonRecord],
) -> str:
    return stable_hash(
        {
            "schema": "cross_algorithm_ordered_records_v1",
            "rows": [
                {
                    "ordinal": record.ordinal,
                    "pair_id": record.pair_id,
                    "record_hash": record.record_hash,
                }
                for record in records
            ],
        },
        length=64,
    )


def ordered_eligibility_transitions_hash(
    transitions: Iterable[CrossAlgorithmEligibilityTransition],
) -> str:
    return _ordered_hash("cross_algorithm_ordered_transitions_v1", transitions)


def ordered_common_eligible_hash(
    entries: Iterable[CrossAlgorithmCommonEligibleEntry],
) -> str:
    return _ordered_hash("cross_algorithm_ordered_common_eligible_v1", entries)


def ordered_count_records_hash(records: Iterable[CrossAlgorithmCountRecord]) -> str:
    return _ordered_hash("cross_algorithm_ordered_counts_v1", records)


def ordered_observations_hash(
    observations: Iterable[CrossAlgorithmObservation],
) -> str:
    return _ordered_hash("cross_algorithm_ordered_observations_v1", observations)


def cross_algorithm_evaluation_fingerprint(
    *,
    definition_fingerprint: str,
    audit_fingerprint: str,
    comparison_records_hash: str,
    eligibility_transitions_hash: str,
    common_eligible_hash: str,
    count_records_hash: str,
    observations_hash: str,
    total_records: int,
    total_transitions: int,
    total_common_eligible: int,
    total_observations: int,
) -> str:
    return stable_hash(
        {
            "schema": "cross_algorithm_evaluation_v1",
            "cross_algorithm_schema_version": CROSS_ALGORITHM_SCHEMA_VERSION,
            "definition_fingerprint": definition_fingerprint,
            "audit_fingerprint": audit_fingerprint,
            "comparison_records_hash": comparison_records_hash,
            "eligibility_transitions_hash": eligibility_transitions_hash,
            "common_eligible_hash": common_eligible_hash,
            "count_records_hash": count_records_hash,
            "observations_hash": observations_hash,
            "total_records": int(total_records),
            "total_transitions": int(total_transitions),
            "total_common_eligible": int(total_common_eligible),
            "total_observations": int(total_observations),
        },
        length=64,
    )


def cross_algorithm_evaluation_id(fingerprint: str) -> str:
    """``algcompare_<12 chars of the evaluation fingerprint>``."""
    digest = _require_digest(fingerprint, "cross_algorithm_evaluation_fingerprint")
    return f"algcompare_{digest[:CROSS_ALGORITHM_ID_LENGTH]}"


@dataclass(frozen=True, slots=True)
class CrossAlgorithmEvaluationManifest:
    """The identity of one immutable comparison."""

    evaluation_id: str
    evaluation_fingerprint: str

    definition_id: str
    definition_fingerprint: str
    audit_fingerprint: str

    comparison_records_hash: str
    eligibility_transitions_hash: str
    common_eligible_hash: str
    count_records_hash: str
    observations_hash: str

    total_records: int
    total_transitions: int
    total_common_eligible: int
    total_observations: int

    created_utc: str

    def __post_init__(self) -> None:
        for name in ("evaluation_id", "definition_id"):
            validate_id(str(getattr(self, name)))
        for name in (
            "evaluation_fingerprint",
            "definition_fingerprint",
            "audit_fingerprint",
            "comparison_records_hash",
            "eligibility_transitions_hash",
            "common_eligible_hash",
            "count_records_hash",
            "observations_hash",
        ):
            object.__setattr__(self, name, _require_digest(getattr(self, name), name))
        for name in (
            "total_records",
            "total_transitions",
            "total_common_eligible",
            "total_observations",
        ):
            number = require_exact_int(getattr(self, name), name)
            if number < 0:
                raise ValueError(f"{name} must not be negative")
            object.__setattr__(self, name, number)
        created = str(self.created_utc).strip()
        if not created:
            raise ValueError("created_utc must not be empty")
        object.__setattr__(self, "created_utc", created)

        expected = cross_algorithm_evaluation_fingerprint(
            definition_fingerprint=self.definition_fingerprint,
            audit_fingerprint=self.audit_fingerprint,
            comparison_records_hash=self.comparison_records_hash,
            eligibility_transitions_hash=self.eligibility_transitions_hash,
            common_eligible_hash=self.common_eligible_hash,
            count_records_hash=self.count_records_hash,
            observations_hash=self.observations_hash,
            total_records=self.total_records,
            total_transitions=self.total_transitions,
            total_common_eligible=self.total_common_eligible,
            total_observations=self.total_observations,
        )
        if self.evaluation_fingerprint != expected:
            raise ValueError(
                "evaluation_fingerprint does not cover this comparison"
            )
        expected_id = cross_algorithm_evaluation_id(expected)
        if self.evaluation_id != expected_id:
            raise ValueError(
                f"evaluation_id must be {expected_id!r}, got {self.evaluation_id!r}"
            )


# ------------------------------------------------------- receipt and marker


@dataclass(frozen=True, slots=True)
class CrossAlgorithmEvaluationReceipt:
    """The committable proof that one comparison was derived deterministically.

    It binds both chains end to end, the shared inputs, the three policies and
    the frozen protocol — and it carries the refusal to conclude anything,
    verbatim, because a receipt is the file somebody reads on its own
    (spec sections 63 and 68).
    """

    schema_version: str

    protocol_id: str
    protocol_fingerprint: str

    evaluation_id: str
    evaluation_fingerprint: str
    definition_fingerprint: str
    audit_fingerprint: str

    left_label: str
    left_run_fingerprint: str
    left_result_set_fingerprint: str
    left_decision_set_fingerprint: str
    left_eligibility_set_fingerprint: str
    left_metric_set_fingerprint: str
    left_decision_profile_fingerprint: str

    right_label: str
    right_run_fingerprint: str
    right_result_set_fingerprint: str
    right_decision_set_fingerprint: str
    right_eligibility_set_fingerprint: str
    right_metric_set_fingerprint: str
    right_decision_profile_fingerprint: str
    right_stage_finalization_fingerprint: str

    alignment_fingerprint: str
    eligibility_policy_id: str
    eligibility_policy_version: str
    metric_policy_fingerprint: str
    comparison_policy_fingerprint: str

    comparison_records_hash: str
    eligibility_transitions_hash: str
    common_eligible_hash: str
    count_records_hash: str
    observations_hash: str
    report_content_hash: str

    comparison_software_fingerprint: str
    comparison_source_commit: str
    comparison_source_tree_clean: bool

    total_records: int
    total_transitions: int
    total_common_eligible: int
    total_observations: int

    operating_point_relation: str = OPERATING_POINT_RELATION
    statement: str = NO_SUPERIORITY_STATEMENT
    created_utc: str = ""

    def __post_init__(self) -> None:
        version = str(self.schema_version).strip()
        if version != CROSS_ALGORITHM_SCHEMA_VERSION:
            raise ValueError(f"unsupported comparison receipt version {version!r}")
        object.__setattr__(self, "schema_version", version)

        for name in ("protocol_id", "evaluation_id", "eligibility_policy_id"):
            validate_id(str(getattr(self, name)))
        for name in (
            "protocol_fingerprint",
            "evaluation_fingerprint",
            "definition_fingerprint",
            "audit_fingerprint",
            "left_run_fingerprint",
            "left_result_set_fingerprint",
            "left_decision_set_fingerprint",
            "left_eligibility_set_fingerprint",
            "left_metric_set_fingerprint",
            "left_decision_profile_fingerprint",
            "right_run_fingerprint",
            "right_result_set_fingerprint",
            "right_decision_set_fingerprint",
            "right_eligibility_set_fingerprint",
            "right_metric_set_fingerprint",
            "right_decision_profile_fingerprint",
            "right_stage_finalization_fingerprint",
            "alignment_fingerprint",
            "metric_policy_fingerprint",
            "comparison_policy_fingerprint",
            "comparison_records_hash",
            "eligibility_transitions_hash",
            "common_eligible_hash",
            "count_records_hash",
            "observations_hash",
            "report_content_hash",
            "comparison_software_fingerprint",
        ):
            object.__setattr__(self, name, _require_digest(getattr(self, name), name))
        object.__setattr__(
            self,
            "comparison_source_commit",
            _require_commit(self.comparison_source_commit, "comparison_source_commit"),
        )
        if not self.comparison_source_tree_clean:
            raise ValueError(
                "a comparison receipt cannot describe an uncommitted working tree "
                "(docs/adr/0017)"
            )
        if self.operating_point_relation != OPERATING_POINT_RELATION:
            raise ValueError(
                f"operating_point_relation must be {OPERATING_POINT_RELATION!r}"
            )
        if str(self.statement).strip() != NO_SUPERIORITY_STATEMENT:
            raise ValueError(
                "a comparison receipt states, verbatim, what it does not establish"
            )
        created = str(self.created_utc).strip()
        if not created:
            raise ValueError("created_utc must not be empty")
        object.__setattr__(self, "created_utc", created)
        require_no_score_comparison(self, path="receipt")


def cross_algorithm_receipt_fingerprint(
    receipt: CrossAlgorithmEvaluationReceipt,
) -> str:
    plain = dict(to_plain(receipt))
    plain.pop("created_utc", None)
    return stable_hash(
        {"schema": "cross_algorithm_receipt_v1", "receipt": plain}, length=64
    )


def cross_algorithm_receipt_content_hash(
    receipt: CrossAlgorithmEvaluationReceipt,
) -> str:
    return stable_hash(
        {"schema": "cross_algorithm_receipt_content_v1", "receipt": to_plain(receipt)},
        length=64,
    )


@dataclass(frozen=True, slots=True)
class CrossAlgorithmFinalization:
    """The last-written authority over a verified comparison chain."""

    schema_version: str
    finalization_id: str
    finalization_fingerprint: str

    evaluation_id: str
    evaluation_fingerprint: str
    protocol_fingerprint: str
    audit_fingerprint: str

    receipt_fingerprint: str
    receipt_content_hash: str
    report_content_hash: str

    comparison_source_commit: str
    comparison_source_tree_clean: bool

    created_utc: str

    def __post_init__(self) -> None:
        version = str(self.schema_version).strip()
        if version != CROSS_ALGORITHM_SCHEMA_VERSION:
            raise ValueError(f"unsupported comparison finalization version {version!r}")
        object.__setattr__(self, "schema_version", version)
        validate_id(self.finalization_id)
        validate_id(self.evaluation_id)
        for name in (
            "finalization_fingerprint",
            "evaluation_fingerprint",
            "protocol_fingerprint",
            "audit_fingerprint",
            "receipt_fingerprint",
            "receipt_content_hash",
            "report_content_hash",
        ):
            object.__setattr__(self, name, _require_digest(getattr(self, name), name))
        object.__setattr__(
            self,
            "comparison_source_commit",
            _require_commit(self.comparison_source_commit, "comparison_source_commit"),
        )
        if not self.comparison_source_tree_clean:
            raise ValueError(
                "comparison finalization requires a clean comparison tree"
            )
        created = str(self.created_utc).strip()
        if not created:
            raise ValueError("created_utc must not be empty")
        object.__setattr__(self, "created_utc", created)

        expected = cross_algorithm_finalization_fingerprint(self)
        if self.finalization_fingerprint != expected:
            raise ValueError(
                "finalization_fingerprint does not cover the marker's claims"
            )
        expected_id = f"algcomparefinal_{expected[:CROSS_ALGORITHM_ID_LENGTH]}"
        if self.finalization_id != expected_id:
            raise ValueError(
                f"finalization_id must be {expected_id!r}, got "
                f"{self.finalization_id!r}"
            )


def cross_algorithm_finalization_fingerprint(
    marker: CrossAlgorithmFinalization | Mapping[str, Any],
) -> str:
    plain = dict(to_plain(marker))
    for name in ("finalization_id", "finalization_fingerprint", "created_utc"):
        plain.pop(name, None)
    return stable_hash(
        {"schema": "cross_algorithm_finalization_v1", "marker": plain}, length=64
    )


# -------------------------------------------------------------------- state


@dataclass(frozen=True, slots=True)
class CrossAlgorithmEvaluationState:
    """How much of a comparison's evidence chain is currently in place.

    Derived, never stored as authority. Every ``*_valid`` flag means "re-derived
    and agreed", not "the file exists" (docs/adr/0012).
    """

    evaluation_id: str | None
    status: CrossAlgorithmStatus

    definition_present: bool
    left_evaluation_ready: bool
    right_evaluation_ready: bool

    audit_present: bool
    audit_clean: bool

    records_present: bool
    records_valid: bool

    aggregates_present: bool
    aggregates_valid: bool

    report_present: bool
    report_valid: bool

    receipt_present: bool
    receipt_valid: bool

    finalization_present: bool
    finalization_valid: bool

    total_records: int = 0
    total_transitions: int = 0
    total_common_eligible: int = 0
    total_observations: int = 0

    issues: tuple[str, ...] = ()
    inspected_utc: str = ""

    def __post_init__(self) -> None:
        if self.evaluation_id is not None:
            validate_id(self.evaluation_id)
        object.__setattr__(self, "issues", tuple(str(item) for item in self.issues))

    @property
    def is_cross_algorithm_ready(self) -> bool:
        return self.status is CrossAlgorithmStatus.CROSS_ALGORITHM_READY
