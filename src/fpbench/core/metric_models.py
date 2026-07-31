"""Counting decisions, and naming what each count was counted out of.

Stage 5A wrote down *which* comparisons belong to an evaluation and *what* a
threshold said about each one. It deliberately computed no rate, because a rate
is three claims wearing one number: which comparisons counted, what counted as
success, and what happened to the ones that produced no score. This module holds
the containers that make all three visible.

Four ideas carry it.

**A count comes before a rate.** Every :class:`MetricObservation` stores an
integer numerator and an integer denominator. The percentage is a rendering,
computed for display and never stored as the authority. ``0.6%`` cannot be
checked; ``3/500`` can (docs/adr/0026).

**A denominator has a name.** :class:`~fpbench.core.enums.MetricDenominator` is
a closed vocabulary, and every definition names one member of it. There is no
path by which an aggregation function can hand a verifier an integer and say
"trust me, that was the denominator": the verifier re-derives it from the enum
and the stored counts (docs/adr/0027).

**A failure is still not a non-match.** Two metrics, never one: a
decision-conditional rate over comparisons that produced a score, and an
attempt-level rate over every comparison attempted. When nothing failed the two
coincide numerically, which is exactly why they must stay separate — the day
something fails, a single blended number would move for reasons nobody could
name (docs/adr/0006, docs/adr/0027).

**Pooled is a sum, not an average.** A pooled observation's numerator is the sum
of the release numerators and its denominator the sum of the release
denominators. ``(rate_A + rate_B + rate_C) / 3`` is a different quantity that
happens to agree when the releases are the same size, and the releases being the
same size today is not a reason to compute it that way (docs/adr/0028).

The dataclasses live in ``core`` because the storage layer persists them and
``storage`` may only import ``core``. The rules for *deriving* them — which
outcome feeds which numerator, how a view becomes a count record — live in
:mod:`fpbench.metrics`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, Decimal
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from fpbench.core.enums import (
    MetricDenominator,
    MetricNumerator,
    MetricObservationStatus,
    MetricScopeKind,
)
from fpbench.core.errors import MetricPolicyError
from fpbench.core.identifiers import validate_id
from fpbench.core.serialization import freeze_str_mapping, require_exact_int, stable_hash

__all__ = [
    "MetricNumerator",
    "MetricDenominator",
    "MetricScopeKind",
    "MetricObservationStatus",
    "DecisionOutcomeCounts",
    "EligibilityOutcomeCounts",
    "ConditionalOutcomeCounts",
    "MetricScope",
    "MetricDefinition",
    "MetricPolicy",
    "ReportProfile",
    "MetricObservation",
    "EvaluationCountRecord",
    "MetricSetManifest",
    "CountFamily",
    "scope_sort_key",
    "metric_definition_hash",
    "metric_policy_fingerprint",
    "report_profile_fingerprint",
    "metric_observation_hash",
    "count_record_hash",
    "ordered_count_records_hash",
    "ordered_observations_hash",
    "metric_set_fingerprint",
    "metric_set_id",
    "fraction_text",
    "render_percentage",
    "require_honest_metric_id",
    "METRIC_POLICY_SCHEMA_VERSION",
    "METRIC_SET_SCHEMA_VERSION",
    "REPORT_PROFILE_SCHEMA_VERSION",
    "METRIC_SET_ID_LENGTH",
    "FORBIDDEN_METRIC_TOKENS",
    "UNIT_OF_ANALYSIS_COMPARISON",
    "POOLED_AGGREGATION_SUM_COUNTS",
    "ZERO_FORMAT_OBSERVED_ZERO",
    "UNDEFINED_DISPLAY",
]

#: Bumped when the meaning of a metric policy changes. Inside the fingerprint,
#: so a bump separates new policies from old.
METRIC_POLICY_SCHEMA_VERSION = "1"

#: Bumped when the meaning of a metric set changes.
METRIC_SET_SCHEMA_VERSION = "1"

#: Bumped when the meaning of a report profile changes.
REPORT_PROFILE_SCHEMA_VERSION = "1"

METRIC_SET_ID_LENGTH = 12

#: The only unit of analysis this stage supports. One comparison, one vote. No
#: per-subject averaging, no average of release percentages (docs/adr/0028).
UNIT_OF_ANALYSIS_COMPARISON = "comparison"

#: The only pooling rule this stage supports.
POOLED_AGGREGATION_SUM_COUNTS = "sum_counts_then_divide"

#: How an observed zero is written: ``0/500 (0.0000%)``, never "no false
#: matches occurred" and never a probability claim (docs/adr/0030).
ZERO_FORMAT_OBSERVED_ZERO = "observed_zero"

#: What a metric with nothing to divide by renders as.
UNDEFINED_DISPLAY = "undefined"

#: Phrases a metric id may not contain. Narrower than the view-name rule, which
#: forbids ``fnmr`` outright: a *mated* non-match fraction with a named
#: denominator is a legitimate thing to call an FNMR, and
#: ``plain_roll_mated_unconditional_fnmr_decided`` says exactly which one it is.
#: What may never appear is a claim to a population-level false-match rate,
#: because the only impostor set here is a closed-set sanity check
#: (docs/adr/0025, docs/adr/0030).
FORBIDDEN_METRIC_TOKENS: frozenset[str] = frozenset(
    {"general_fmr", "population_fmr", "impostor_fmr", "overall_fmr"}
)

_HEX = frozenset("0123456789abcdef")


def _require_digest(value: str, field_name: str) -> str:
    digest = str(value).strip().lower()
    if len(digest) != 64 or not set(digest) <= _HEX:
        raise ValueError(f"{field_name} must be a 64-character hexadecimal digest")
    return digest


def _require_count(value: Any, field_name: str) -> int:
    number = require_exact_int(value, field_name)
    if number < 0:
        raise ValueError(f"{field_name} must not be negative, got {number}")
    return number


def require_honest_metric_id(metric_id: str) -> str:
    """Refuse a metric id that would claim a measurement this design cannot make."""
    lowered = str(metric_id).lower()
    offending = sorted(token for token in FORBIDDEN_METRIC_TOKENS if token in lowered)
    if offending:
        raise MetricPolicyError(
            f"a metric may not be called {metric_id!r}: {offending} would claim a "
            "population-level false-match rate, and the only impostor set in this "
            "study is a closed-set same-subject sanity check (docs/adr/0030)"
        )
    return validate_id(metric_id)


# ------------------------------------------------------------------- counts


@dataclass(frozen=True, slots=True)
class DecisionOutcomeCounts:
    """How a population of comparisons came out, with failures kept separate.

    The two invariants are the whole point. ``total == decided + undecidable``
    means no comparison is lost, and ``decided == match + non_match`` means no
    failure is quietly counted as a non-match. Both are checked here rather than
    trusted, because every rate in the stage divides one of these numbers by
    another (docs/adr/0006, docs/adr/0027).
    """

    total_attempts: int
    decided_attempts: int

    match_count: int
    non_match_count: int
    undecidable_count: int

    def __post_init__(self) -> None:
        for name in (
            "total_attempts",
            "decided_attempts",
            "match_count",
            "non_match_count",
            "undecidable_count",
        ):
            object.__setattr__(self, name, _require_count(getattr(self, name), name))

        if self.total_attempts != self.decided_attempts + self.undecidable_count:
            raise ValueError(
                "every attempt is either decided or undecidable: "
                f"{self.decided_attempts} + {self.undecidable_count} != "
                f"{self.total_attempts}"
            )
        if self.decided_attempts != self.match_count + self.non_match_count:
            raise ValueError(
                "every decided attempt is a match or a non-match: "
                f"{self.match_count} + {self.non_match_count} != "
                f"{self.decided_attempts}"
            )

    @property
    def non_success_count(self) -> int:
        """``NON_MATCH + UNDECIDABLE``.

        Meaningful for genuine attempts, where both mean "this finger was not
        recognised". Deliberately not used as an impostor numerator.
        """
        return self.non_match_count + self.undecidable_count

    def as_mapping(self) -> Mapping[str, int]:
        return {
            "match": self.match_count,
            "non_match": self.non_match_count,
            "undecidable": self.undecidable_count,
            "decided": self.decided_attempts,
        }

    def __add__(self, other: "DecisionOutcomeCounts") -> "DecisionOutcomeCounts":
        return DecisionOutcomeCounts(
            total_attempts=self.total_attempts + other.total_attempts,
            decided_attempts=self.decided_attempts + other.decided_attempts,
            match_count=self.match_count + other.match_count,
            non_match_count=self.non_match_count + other.non_match_count,
            undecidable_count=self.undecidable_count + other.undecidable_count,
        )


@dataclass(frozen=True, slots=True)
class EligibilityOutcomeCounts:
    """How many SELF units passed, failed, or could not be told apart.

    Three-valued, and it stays three-valued all the way into the report. Folding
    ``UNDETERMINED`` into ``INELIGIBLE`` would assert that a finger failed when
    what actually happened is that a comparison crashed (docs/adr/0023).
    """

    total_units: int
    eligible_count: int
    ineligible_count: int
    undetermined_count: int

    def __post_init__(self) -> None:
        for name in (
            "total_units",
            "eligible_count",
            "ineligible_count",
            "undetermined_count",
        ):
            object.__setattr__(self, name, _require_count(getattr(self, name), name))
        expected = (
            self.eligible_count + self.ineligible_count + self.undetermined_count
        )
        if self.total_units != expected:
            raise ValueError(
                "every unit is eligible, ineligible or undetermined: "
                f"{self.eligible_count} + {self.ineligible_count} + "
                f"{self.undetermined_count} != {self.total_units}"
            )

    def as_mapping(self) -> Mapping[str, int]:
        return {
            "eligible": self.eligible_count,
            "ineligible": self.ineligible_count,
            "undetermined": self.undetermined_count,
        }

    def __add__(self, other: "EligibilityOutcomeCounts") -> "EligibilityOutcomeCounts":
        return EligibilityOutcomeCounts(
            total_units=self.total_units + other.total_units,
            eligible_count=self.eligible_count + other.eligible_count,
            ineligible_count=self.ineligible_count + other.ineligible_count,
            undetermined_count=self.undetermined_count + other.undetermined_count,
        )


@dataclass(frozen=True, slots=True)
class ConditionalOutcomeCounts:
    """A selection and its outcomes, counted in one place so neither can hide.

    A conditional result without its selection fraction is uninterpretable: "the
    fingers that passed both SELF tests matched 99% of the time" says nothing
    until you know whether that was 99% of 1,480 or of 12. So the excluded rows
    are counted here beside the included ones, and the exclusion reasons are kept
    apart (docs/adr/0024, docs/adr/0029).
    """

    total_rows: int

    included_count: int
    excluded_ineligible_count: int
    excluded_undetermined_count: int

    included_decided_count: int
    included_match_count: int
    included_non_match_count: int
    included_undecidable_count: int

    def __post_init__(self) -> None:
        for name in (
            "total_rows",
            "included_count",
            "excluded_ineligible_count",
            "excluded_undetermined_count",
            "included_decided_count",
            "included_match_count",
            "included_non_match_count",
            "included_undecidable_count",
        ):
            object.__setattr__(self, name, _require_count(getattr(self, name), name))

        selected = (
            self.included_count
            + self.excluded_ineligible_count
            + self.excluded_undetermined_count
        )
        if self.total_rows != selected:
            raise ValueError(
                "every conditional row is included or excluded for one stated "
                f"reason: {self.included_count} + {self.excluded_ineligible_count} + "
                f"{self.excluded_undetermined_count} != {self.total_rows}"
            )
        if self.included_count != (
            self.included_decided_count + self.included_undecidable_count
        ):
            raise ValueError(
                "every included row is decided or undecidable: "
                f"{self.included_decided_count} + {self.included_undecidable_count} "
                f"!= {self.included_count}"
            )
        if self.included_decided_count != (
            self.included_match_count + self.included_non_match_count
        ):
            raise ValueError(
                "every included decided row is a match or a non-match: "
                f"{self.included_match_count} + {self.included_non_match_count} != "
                f"{self.included_decided_count}"
            )

    @property
    def included_non_success_count(self) -> int:
        return self.included_non_match_count + self.included_undecidable_count

    def as_mapping(self) -> Mapping[str, int]:
        return {
            "included": self.included_count,
            "excluded_ineligible": self.excluded_ineligible_count,
            "excluded_undetermined": self.excluded_undetermined_count,
            "included_decided": self.included_decided_count,
            "included_match": self.included_match_count,
            "included_non_match": self.included_non_match_count,
            "included_undecidable": self.included_undecidable_count,
        }

    def __add__(self, other: "ConditionalOutcomeCounts") -> "ConditionalOutcomeCounts":
        return ConditionalOutcomeCounts(
            total_rows=self.total_rows + other.total_rows,
            included_count=self.included_count + other.included_count,
            excluded_ineligible_count=(
                self.excluded_ineligible_count + other.excluded_ineligible_count
            ),
            excluded_undetermined_count=(
                self.excluded_undetermined_count + other.excluded_undetermined_count
            ),
            included_decided_count=(
                self.included_decided_count + other.included_decided_count
            ),
            included_match_count=self.included_match_count + other.included_match_count,
            included_non_match_count=(
                self.included_non_match_count + other.included_non_match_count
            ),
            included_undecidable_count=(
                self.included_undecidable_count + other.included_undecidable_count
            ),
        )


class CountFamily:
    """The six aggregate tables an evaluation rests on.

    Named and closed, with the exact key set each one carries, so that a verifier
    can recompute a denominator from a stored record without knowing which
    function produced it. A family whose keys drifted would be a family whose
    denominators could not be re-derived (spec section 47).
    """

    PLAIN_SELF = "plain_self_outcomes"
    ROLL_SELF = "roll_self_outcomes"
    SELF_ELIGIBILITY = "self_eligibility_outcomes"
    MATED_UNCONDITIONAL = "mated_unconditional_outcomes"
    MATED_CONDITIONAL = "mated_conditional_outcomes"
    NEGATIVE_SANITY = "negative_sanity_outcomes"

    #: Report and storage order. Enters every ordered hash (spec section 40).
    ORDER: tuple[str, ...] = (
        PLAIN_SELF,
        ROLL_SELF,
        SELF_ELIGIBILITY,
        MATED_UNCONDITIONAL,
        MATED_CONDITIONAL,
        NEGATIVE_SANITY,
    )

    _DECISION_KEYS = ("match", "non_match", "undecidable", "decided")
    _ELIGIBILITY_KEYS = ("eligible", "ineligible", "undetermined")
    _CONDITIONAL_KEYS = (
        "included",
        "excluded_ineligible",
        "excluded_undetermined",
        "included_decided",
        "included_match",
        "included_non_match",
        "included_undecidable",
    )

    KEYS: Mapping[str, tuple[str, ...]] = MappingProxyType(
        {
            PLAIN_SELF: _DECISION_KEYS,
            ROLL_SELF: _DECISION_KEYS,
            SELF_ELIGIBILITY: _ELIGIBILITY_KEYS,
            MATED_UNCONDITIONAL: _DECISION_KEYS,
            MATED_CONDITIONAL: _CONDITIONAL_KEYS,
            NEGATIVE_SANITY: _DECISION_KEYS,
        }
    )

    ALL: frozenset[str] = frozenset(ORDER)

    @classmethod
    def index(cls, family: str) -> int:
        try:
            return cls.ORDER.index(family)
        except ValueError:
            raise MetricPolicyError(
                f"count family {family!r} is not one this project defines; expected "
                f"one of {list(cls.ORDER)}"
            ) from None


# -------------------------------------------------------------------- scope


@dataclass(frozen=True, slots=True)
class MetricScope:
    """One release, or all of them summed.

    ``POOLED`` carries no release, and ``RELEASE`` must carry one. A pooled
    observation tagged with a release would read as a fourth release; a release
    observation with none would read as a pooled value that happened to cover a
    third of the data.
    """

    scope_kind: MetricScopeKind
    release: str | None = None

    def __post_init__(self) -> None:
        kind = self.scope_kind
        if not isinstance(kind, MetricScopeKind):
            kind = MetricScopeKind(str(kind))
            object.__setattr__(self, "scope_kind", kind)

        release = self.release
        if kind is MetricScopeKind.RELEASE:
            release = str(release or "").strip()
            if not release:
                raise ValueError("a release-scoped metric must name its release")
            object.__setattr__(self, "release", release)
        else:
            if release is not None and str(release).strip():
                raise ValueError(
                    f"a pooled metric must not name a release, got {release!r}; "
                    "pooled is the sum of the releases, not another one"
                )
            object.__setattr__(self, "release", None)

    @property
    def is_pooled(self) -> bool:
        return self.scope_kind is MetricScopeKind.POOLED

    @property
    def label(self) -> str:
        """What a report row is called."""
        return "pooled" if self.is_pooled else str(self.release)

    def as_plain(self) -> Mapping[str, Any]:
        return {"scope_kind": self.scope_kind.value, "release": self.release}


def scope_sort_key(
    scope: MetricScope, release_order: tuple[str, ...] = ()
) -> tuple[int, int, str]:
    """Releases in declared order, pooled last (spec section 40).

    A release the profile does not name sorts after the ones it does, by name,
    rather than raising: ordering is not the place to reject an unexpected
    release, and the aggregation layer rejects it much earlier and much louder.
    """
    if scope.is_pooled:
        return (1, len(release_order), "")
    release = str(scope.release)
    try:
        index = release_order.index(release)
    except ValueError:
        index = len(release_order)
    return (0, index, release)


# --------------------------------------------------------------- definitions


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    """One metric, stated as a numerator over a named denominator.

    ``interpretation`` and ``prohibited_labels`` are not decoration. They travel
    with the metric into the policy fingerprint, so that "this is not a general
    false-match rate" is part of the metric's identity rather than a sentence in
    a document that may or may not be copied alongside the number
    (docs/adr/0030).
    """

    metric_id: str
    metric_family: str

    numerator: MetricNumerator
    denominator: MetricDenominator

    source_view_kind: str | None
    source_protocol_stage: str | None

    interpretation: str
    prohibited_labels: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "metric_id", require_honest_metric_id(self.metric_id))
        family = str(self.metric_family).strip()
        if family not in CountFamily.ALL:
            raise MetricPolicyError(
                f"metric {self.metric_id} names count family {family!r}, which is "
                f"not one of {list(CountFamily.ORDER)}"
            )
        object.__setattr__(self, "metric_family", family)

        if not isinstance(self.numerator, MetricNumerator):
            object.__setattr__(self, "numerator", MetricNumerator(str(self.numerator)))
        if not isinstance(self.denominator, MetricDenominator):
            object.__setattr__(
                self, "denominator", MetricDenominator(str(self.denominator))
            )

        for name in ("source_view_kind", "source_protocol_stage"):
            value = getattr(self, name)
            object.__setattr__(
                self, name, str(value).strip() if value is not None else None
            )

        interpretation = str(self.interpretation).strip()
        if not interpretation:
            raise MetricPolicyError(
                f"metric {self.metric_id} must say what it means; a rate whose "
                "reading is left to the reader will be read generously"
            )
        object.__setattr__(self, "interpretation", interpretation)
        object.__setattr__(
            self,
            "prohibited_labels",
            tuple(str(label).strip() for label in self.prohibited_labels if str(label).strip()),
        )


def metric_definition_hash(definition: MetricDefinition) -> str:
    """A digest of one definition's whole semantics.

    Numerator and denominator are in it, which is the load-bearing part:
    changing a denominator changes this hash, therefore the policy fingerprint,
    therefore the metric-set id (spec section 23).
    """
    return stable_hash(
        {
            "schema": "metric_definition_v1",
            "metric_id": definition.metric_id,
            "metric_family": definition.metric_family,
            "numerator": definition.numerator.value,
            "denominator": definition.denominator.value,
            "source_view_kind": definition.source_view_kind,
            "source_protocol_stage": definition.source_protocol_stage,
            "interpretation": definition.interpretation,
            "prohibited_labels": list(definition.prohibited_labels),
        },
        length=64,
    )


@dataclass(frozen=True, slots=True)
class MetricPolicy:
    """Every metric this evaluation may compute, fixed before it computes one.

    Immutable and externally defined, on the same terms as a decision profile:
    the thing being measured has never seen this object, and nothing in it can
    reach back into a stored decision (docs/adr/0021, applied to metrics).

    The display fields are carried here because they are parsed from the same
    file, but they are *not* in :func:`metric_policy_fingerprint`. Rounding a
    percentage to five places instead of four changes how a report reads and
    changes nothing about what was measured; letting it change the metric-set id
    would make every republication look like a new result (spec section 23).
    :class:`ReportProfile` is what those fields do reach.
    """

    policy_id: str
    policy_fingerprint: str
    policy_version: str

    unit_of_analysis: str
    pooled_aggregation: str

    metric_definitions: tuple[MetricDefinition, ...]

    percentage_decimal_places: int
    always_show_fraction: bool
    zero_format: str

    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        validate_id(self.policy_id)
        object.__setattr__(
            self,
            "policy_fingerprint",
            _require_digest(self.policy_fingerprint, "policy_fingerprint"),
        )
        version = str(self.policy_version).strip()
        if not version:
            raise MetricPolicyError("policy_version must not be empty")
        object.__setattr__(self, "policy_version", version)

        if str(self.unit_of_analysis).strip() != UNIT_OF_ANALYSIS_COMPARISON:
            raise MetricPolicyError(
                f"unit of analysis {self.unit_of_analysis!r} is not supported; this "
                f"stage counts one comparison as one unit ({UNIT_OF_ANALYSIS_COMPARISON}), "
                "and averaging per subject or per finger would be a weighting choice "
                "nobody has argued for (docs/adr/0028)"
            )
        object.__setattr__(self, "unit_of_analysis", UNIT_OF_ANALYSIS_COMPARISON)

        if str(self.pooled_aggregation).strip() != POOLED_AGGREGATION_SUM_COUNTS:
            raise MetricPolicyError(
                f"pooled aggregation {self.pooled_aggregation!r} is not supported; "
                f"pooled values sum counts and divide once ({POOLED_AGGREGATION_SUM_COUNTS}), "
                "never average release percentages (docs/adr/0028)"
            )
        object.__setattr__(self, "pooled_aggregation", POOLED_AGGREGATION_SUM_COUNTS)

        definitions = tuple(self.metric_definitions)
        if not definitions:
            raise MetricPolicyError("a metric policy with no metrics is not one")
        ids = [definition.metric_id for definition in definitions]
        if len(set(ids)) != len(ids):
            duplicates = sorted({name for name in ids if ids.count(name) > 1})
            raise MetricPolicyError(f"metric ids must be unique; repeated: {duplicates}")
        object.__setattr__(self, "metric_definitions", definitions)

        places = require_exact_int(
            self.percentage_decimal_places, "percentage_decimal_places"
        )
        if not 0 <= places <= 10:
            raise MetricPolicyError(
                f"percentage_decimal_places must be between 0 and 10, got {places}"
            )
        object.__setattr__(self, "percentage_decimal_places", places)
        object.__setattr__(self, "always_show_fraction", bool(self.always_show_fraction))

        if str(self.zero_format).strip() != ZERO_FORMAT_OBSERVED_ZERO:
            raise MetricPolicyError(
                f"zero_format {self.zero_format!r} is not supported; an observed zero "
                f"is written as {ZERO_FORMAT_OBSERVED_ZERO!r} — '0/500', never 'no "
                "false matches occurred' (docs/adr/0030)"
            )
        object.__setattr__(self, "zero_format", ZERO_FORMAT_OBSERVED_ZERO)
        object.__setattr__(self, "metadata", freeze_str_mapping(self.metadata))

        recomputed = metric_policy_fingerprint(self)
        if self.policy_fingerprint != recomputed:
            raise MetricPolicyError(
                "policy_fingerprint does not cover the policy it is attached to"
            )

    def definition(self, metric_id: str) -> MetricDefinition:
        for definition in self.metric_definitions:
            if definition.metric_id == metric_id:
                return definition
        raise MetricPolicyError(
            f"metric {metric_id!r} is not defined by policy {self.policy_id}"
        )

    @property
    def metric_ids(self) -> tuple[str, ...]:
        return tuple(
            definition.metric_id for definition in self.metric_definitions
        )

    def definition_index(self, metric_id: str) -> int:
        return self.metric_ids.index(metric_id)


def metric_policy_fingerprint(policy: MetricPolicy) -> str:
    """A 64-character digest of everything that could change a number.

    In it: the ordered metric definitions with their numerators and denominators,
    the unit of analysis, the pooling rule and the semantic metadata. Out of it:
    display precision, the report's title, any filename, any timestamp. A policy
    written in two repositories is the same policy.
    """
    return stable_hash(
        {
            "schema": "metric_policy_fingerprint_v1",
            "metric_policy_schema_version": METRIC_POLICY_SCHEMA_VERSION,
            "policy_id": policy.policy_id,
            "policy_version": policy.policy_version,
            "unit_of_analysis": policy.unit_of_analysis,
            "pooled_aggregation": policy.pooled_aggregation,
            "metric_definitions": [
                {
                    "metric_id": definition.metric_id,
                    "metric_family": definition.metric_family,
                    "numerator": definition.numerator.value,
                    "denominator": definition.denominator.value,
                    "source_view_kind": definition.source_view_kind,
                    "source_protocol_stage": definition.source_protocol_stage,
                    "interpretation": definition.interpretation,
                    "prohibited_labels": list(definition.prohibited_labels),
                    "definition_hash": metric_definition_hash(definition),
                }
                for definition in policy.metric_definitions
            ],
            "metadata": dict(policy.metadata),
        },
        length=64,
    )


@dataclass(frozen=True, slots=True)
class ReportProfile:
    """How the verified numbers are rendered, kept apart from what they are.

    Everything here is presentation: how many decimal places a percentage shows,
    which order the releases appear in, whether a pooled row is drawn, what
    language the prose is written in. Changing any of it produces different bytes
    and the same measurement, which is exactly why it has its own identity and
    stays out of the metric-set fingerprint (spec sections 23–24).
    """

    report_profile_id: str
    report_profile_fingerprint: str

    percentage_decimal_places: int
    always_show_fraction: bool
    include_pooled: bool
    release_order: tuple[str, ...]
    language: str

    def __post_init__(self) -> None:
        validate_id(self.report_profile_id)
        object.__setattr__(
            self,
            "report_profile_fingerprint",
            _require_digest(
                self.report_profile_fingerprint, "report_profile_fingerprint"
            ),
        )
        places = require_exact_int(
            self.percentage_decimal_places, "percentage_decimal_places"
        )
        if not 0 <= places <= 10:
            raise MetricPolicyError(
                f"percentage_decimal_places must be between 0 and 10, got {places}"
            )
        object.__setattr__(self, "percentage_decimal_places", places)
        object.__setattr__(self, "always_show_fraction", bool(self.always_show_fraction))
        object.__setattr__(self, "include_pooled", bool(self.include_pooled))

        releases = tuple(str(item).strip() for item in self.release_order)
        if not releases:
            raise MetricPolicyError(
                "a report profile must fix the order its releases appear in; an "
                "unordered report is a report whose bytes change between machines"
            )
        if len(set(releases)) != len(releases):
            raise MetricPolicyError(f"release_order repeats a release: {list(releases)}")
        object.__setattr__(self, "release_order", releases)

        language = str(self.language).strip().lower()
        if not language:
            raise MetricPolicyError("language must not be empty")
        object.__setattr__(self, "language", language)

        recomputed = report_profile_fingerprint(self)
        if self.report_profile_fingerprint != recomputed:
            raise MetricPolicyError(
                "report_profile_fingerprint does not cover the profile it is "
                "attached to"
            )


def report_profile_fingerprint(profile: ReportProfile) -> str:
    """A digest of how a report is rendered, and of nothing it says."""
    return stable_hash(
        {
            "schema": "report_profile_fingerprint_v1",
            "report_profile_schema_version": REPORT_PROFILE_SCHEMA_VERSION,
            "report_profile_id": profile.report_profile_id,
            "percentage_decimal_places": profile.percentage_decimal_places,
            "always_show_fraction": profile.always_show_fraction,
            "include_pooled": profile.include_pooled,
            "release_order": list(profile.release_order),
            "language": profile.language,
        },
        length=64,
    )


# ------------------------------------------------------------- observations


def fraction_text(numerator: int, denominator: int) -> str | None:
    """``"<numerator>/<denominator>"``, or ``None`` when there is nothing to divide.

    The authoritative value of every metric in this stage is the pair of
    integers. This string is a convenience for readers and is re-derived from
    the integers whenever it is verified, never trusted (spec section 25).
    """
    if int(denominator) <= 0:
        return None
    return f"{int(numerator)}/{int(denominator)}"


def render_percentage(
    numerator: int, denominator: int, *, decimal_places: int
) -> str | None:
    """The display percentage, or ``None`` when the denominator is zero.

    Exact decimal arithmetic, rounded once at the end for display. Never
    ``NaN``, never ``Infinity``, and never ``0%`` standing in for "undefined"
    (spec section 26).
    """
    if int(denominator) <= 0:
        return None
    value = (Decimal(int(numerator)) / Decimal(int(denominator))) * Decimal(100)
    quantum = Decimal(1).scaleb(-int(decimal_places))
    return str(value.quantize(quantum, rounding=ROUND_HALF_EVEN))


@dataclass(frozen=True, slots=True)
class MetricObservation:
    """One metric, at one scope, as two integers and their provenance.

    Note what is *not* here: no raw score, no subject, no finger, no image, no
    pair, no job, no filename, no path. An observation is a statement about a
    population, and a population is the only thing it is allowed to identify
    (spec section 27).
    """

    ordinal: int

    metric_id: str
    scope: MetricScope

    numerator_count: int
    denominator_count: int

    status: MetricObservationStatus
    fraction_text: str | None

    source_decision_set_fingerprint: str
    source_eligibility_set_fingerprint: str | None
    source_view_fingerprint: str | None

    metric_policy_fingerprint: str

    observation_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "ordinal", _require_count(self.ordinal, "ordinal"))
        object.__setattr__(self, "metric_id", require_honest_metric_id(self.metric_id))

        scope = self.scope
        if isinstance(scope, Mapping):
            scope = MetricScope(
                scope_kind=MetricScopeKind(str(scope["scope_kind"])),
                release=scope.get("release"),
            )
            object.__setattr__(self, "scope", scope)
        if not isinstance(scope, MetricScope):
            raise ValueError("scope must be a MetricScope")

        for name in ("numerator_count", "denominator_count"):
            object.__setattr__(self, name, _require_count(getattr(self, name), name))

        if not isinstance(self.status, MetricObservationStatus):
            object.__setattr__(
                self, "status", MetricObservationStatus(str(self.status))
            )

        for name in (
            "source_decision_set_fingerprint",
            "metric_policy_fingerprint",
        ):
            object.__setattr__(self, name, _require_digest(getattr(self, name), name))
        for name in (
            "source_eligibility_set_fingerprint",
            "source_view_fingerprint",
        ):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _require_digest(value, name))

        # The three shapes a metric may take, enforced rather than assumed.
        if self.status is MetricObservationStatus.DEFINED:
            if self.denominator_count == 0:
                raise ValueError(
                    "a defined observation needs something to divide by; a zero "
                    "denominator is undefined, not zero per cent"
                )
            if self.numerator_count > self.denominator_count:
                raise ValueError(
                    f"metric {self.metric_id} counts {self.numerator_count} of "
                    f"{self.denominator_count}; a numerator cannot exceed its own "
                    "denominator"
                )
        else:
            if self.denominator_count != 0:
                raise ValueError(
                    "an observation is undefined only when its denominator is zero"
                )
            if self.numerator_count != 0:
                raise ValueError(
                    "an undefined observation counts nothing; a numerator over an "
                    "empty population is not a measurement"
                )

        expected_fraction = fraction_text(self.numerator_count, self.denominator_count)
        text = self.fraction_text
        if text is not None:
            text = str(text).strip()
        if text != expected_fraction:
            raise ValueError(
                f"fraction_text is {self.fraction_text!r}, but the counts say "
                f"{expected_fraction!r}; the integers are the authority"
            )
        object.__setattr__(self, "fraction_text", expected_fraction)

        recomputed = metric_observation_hash(self)
        if self.observation_hash != recomputed:
            raise ValueError("observation_hash does not cover this observation")

    @property
    def is_defined(self) -> bool:
        return self.status is MetricObservationStatus.DEFINED

    def percentage(self, *, decimal_places: int) -> str | None:
        return render_percentage(
            self.numerator_count,
            self.denominator_count,
            decimal_places=decimal_places,
        )


def metric_observation_hash(observation: MetricObservation) -> str:
    """A digest of one observation, excluding its own hash field.

    Covers the scope, both counts, the policy and the source artefacts. Moving a
    release observation to another release, or swapping a numerator, or pointing
    at a different view, all change it (spec section 74).
    """
    scope = observation.scope
    return stable_hash(
        {
            "schema": "metric_observation_v1",
            "ordinal": observation.ordinal,
            "metric_id": observation.metric_id,
            "scope_kind": scope.scope_kind.value,
            "release": scope.release,
            "numerator_count": observation.numerator_count,
            "denominator_count": observation.denominator_count,
            "status": observation.status.value,
            "source_decision_set_fingerprint": (
                observation.source_decision_set_fingerprint
            ),
            "source_eligibility_set_fingerprint": (
                observation.source_eligibility_set_fingerprint
            ),
            "source_view_fingerprint": observation.source_view_fingerprint,
            "metric_policy_fingerprint": observation.metric_policy_fingerprint,
        },
        length=64,
    )


# ------------------------------------------------------------ count records


@dataclass(frozen=True, slots=True)
class EvaluationCountRecord:
    """The full aggregate table a set of metrics was computed from.

    Observations alone would leave a reader guessing how a denominator was
    assembled. These records remove the guess: every count that went into any
    rate is here, at every scope, and a verifier re-derives each rate from them
    rather than from the aggregation code that produced it (spec section 28).
    """

    ordinal: int

    count_family: str
    scope: MetricScope

    total_count: int
    counts: Mapping[str, int]

    source_fingerprint: str
    count_record_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "ordinal", _require_count(self.ordinal, "ordinal"))

        family = str(self.count_family).strip()
        if family not in CountFamily.ALL:
            raise ValueError(
                f"count family {family!r} is not one of {list(CountFamily.ORDER)}"
            )
        object.__setattr__(self, "count_family", family)

        scope = self.scope
        if isinstance(scope, Mapping):
            scope = MetricScope(
                scope_kind=MetricScopeKind(str(scope["scope_kind"])),
                release=scope.get("release"),
            )
            object.__setattr__(self, "scope", scope)
        if not isinstance(scope, MetricScope):
            raise ValueError("scope must be a MetricScope")

        object.__setattr__(
            self, "total_count", _require_count(self.total_count, "total_count")
        )
        object.__setattr__(
            self,
            "source_fingerprint",
            _require_digest(self.source_fingerprint, "source_fingerprint"),
        )

        expected_keys = CountFamily.KEYS[family]
        counts: dict[str, int] = {}
        for key, value in dict(self.counts).items():
            name = str(key)
            if name not in expected_keys:
                raise ValueError(
                    f"count family {family!r} does not define a count called "
                    f"{name!r}; expected {list(expected_keys)}"
                )
            counts[name] = _require_count(value, f"counts[{name}]")
        missing = [key for key in expected_keys if key not in counts]
        if missing:
            raise ValueError(
                f"count family {family!r} is missing counts {missing}; a partial "
                "aggregate cannot back a denominator"
            )
        # Frozen so that a caller holding the dict it passed in cannot mutate a
        # stored record afterwards.
        object.__setattr__(
            self, "counts", MappingProxyType(dict(sorted(counts.items())))
        )

        _require_family_invariants(family, self.total_count, counts)

        recomputed = count_record_hash(self)
        if self.count_record_hash != recomputed:
            raise ValueError("count_record_hash does not cover this record")

    def get(self, name: str) -> int:
        try:
            return self.counts[name]
        except KeyError:
            raise ValueError(
                f"count family {self.count_family!r} has no count called {name!r}"
            ) from None


def _require_family_invariants(
    family: str, total: int, counts: Mapping[str, int]
) -> None:
    """Re-run the count models' invariants over a flattened record.

    The same arithmetic as the dataclasses above, applied to what was actually
    stored. A record read back from parquet has not been through
    ``DecisionOutcomeCounts.__post_init__``, and the invariants are the reason
    those numbers can be divided at all.
    """
    if family in (
        CountFamily.PLAIN_SELF,
        CountFamily.ROLL_SELF,
        CountFamily.MATED_UNCONDITIONAL,
        CountFamily.NEGATIVE_SANITY,
    ):
        DecisionOutcomeCounts(
            total_attempts=total,
            decided_attempts=counts["decided"],
            match_count=counts["match"],
            non_match_count=counts["non_match"],
            undecidable_count=counts["undecidable"],
        )
        return
    if family == CountFamily.SELF_ELIGIBILITY:
        EligibilityOutcomeCounts(
            total_units=total,
            eligible_count=counts["eligible"],
            ineligible_count=counts["ineligible"],
            undetermined_count=counts["undetermined"],
        )
        return
    ConditionalOutcomeCounts(
        total_rows=total,
        included_count=counts["included"],
        excluded_ineligible_count=counts["excluded_ineligible"],
        excluded_undetermined_count=counts["excluded_undetermined"],
        included_decided_count=counts["included_decided"],
        included_match_count=counts["included_match"],
        included_non_match_count=counts["included_non_match"],
        included_undecidable_count=counts["included_undecidable"],
    )


def count_record_hash(record: EvaluationCountRecord) -> str:
    """A digest of one aggregate table, excluding its own hash field."""
    return stable_hash(
        {
            "schema": "evaluation_count_record_v1",
            "ordinal": record.ordinal,
            "count_family": record.count_family,
            "scope_kind": record.scope.scope_kind.value,
            "release": record.scope.release,
            "total_count": record.total_count,
            "counts": dict(record.counts),
            "source_fingerprint": record.source_fingerprint,
        },
        length=64,
    )


# ----------------------------------------------------------------- manifest


def ordered_count_records_hash(records: Iterable[EvaluationCountRecord]) -> str:
    """A digest of the count records *in canonical order*.

    Order is inside it deliberately: reordering the rows without changing one of
    them must be detectable, because a report reads them in the order it finds
    them (spec section 40).
    """
    return stable_hash(
        {
            "schema": "evaluation_counts_ordered_v1",
            "records": [
                {
                    "ordinal": record.ordinal,
                    "count_family": record.count_family,
                    "scope_kind": record.scope.scope_kind.value,
                    "release": record.scope.release,
                    "count_record_hash": record.count_record_hash,
                }
                for record in records
            ],
        },
        length=64,
    )


def ordered_observations_hash(observations: Iterable[MetricObservation]) -> str:
    """A digest of the observations *in canonical order*."""
    return stable_hash(
        {
            "schema": "metric_observations_ordered_v1",
            "observations": [
                {
                    "ordinal": observation.ordinal,
                    "metric_id": observation.metric_id,
                    "scope_kind": observation.scope.scope_kind.value,
                    "release": observation.scope.release,
                    "observation_hash": observation.observation_hash,
                }
                for observation in observations
            ],
        },
        length=64,
    )


def metric_set_fingerprint(
    *,
    run_fingerprint: str,
    decision_set_fingerprint: str,
    eligibility_set_fingerprint: str,
    unconditional_view_fingerprint: str,
    conditional_view_fingerprint: str,
    non_mated_view_fingerprint: str,
    metric_policy_fingerprint: str,
    metric_software_fingerprint: str,
    ordered_count_records_hash: str,
    ordered_observations_hash: str,
) -> str:
    """The digest behind ``metric_set_id``.

    Includes the metric software fingerprint, for the same reason a decision set
    includes its derivation software: the partitioning, the ordering and the
    hashing all live in that code, and the same counts produced by different
    code are a different artefact (docs/adr/0017).

    Excludes ``created_utc``, the rendered Markdown, JSON indentation and any
    display title. Two people computing the same metrics from the same
    decisions must arrive at the same id.
    """
    return stable_hash(
        {
            "schema": "metric_set_fingerprint_v1",
            "metric_set_schema_version": METRIC_SET_SCHEMA_VERSION,
            "run_fingerprint": run_fingerprint,
            "decision_set_fingerprint": decision_set_fingerprint,
            "eligibility_set_fingerprint": eligibility_set_fingerprint,
            "unconditional_view_fingerprint": unconditional_view_fingerprint,
            "conditional_view_fingerprint": conditional_view_fingerprint,
            "non_mated_view_fingerprint": non_mated_view_fingerprint,
            "metric_policy_fingerprint": metric_policy_fingerprint,
            "metric_software_fingerprint": metric_software_fingerprint,
            "ordered_count_records_hash": ordered_count_records_hash,
            "ordered_observations_hash": ordered_observations_hash,
        },
        length=64,
    )


def metric_set_id(fingerprint: str) -> str:
    """``metricset_<12 chars of the metric-set fingerprint>``."""
    digest = _require_digest(fingerprint, "metric_set_fingerprint")
    return f"metricset_{digest[:METRIC_SET_ID_LENGTH]}"


@dataclass(frozen=True, slots=True)
class MetricSetManifest:
    """The identity of one immutable collection of metrics.

    Carries counts of *structure* — how many count records, how many
    observations — and no outcome. Which comparisons matched is in the
    observations, where a reader has the denominators beside it.
    """

    metric_set_id: str
    metric_set_fingerprint: str

    run_id: str
    run_fingerprint: str

    decision_set_id: str
    decision_set_fingerprint: str

    eligibility_set_id: str
    eligibility_set_fingerprint: str

    unconditional_view_fingerprint: str
    conditional_view_fingerprint: str
    non_mated_view_fingerprint: str

    metric_policy_id: str
    metric_policy_fingerprint: str

    report_profile_fingerprint: str

    metric_software_fingerprint: str
    metric_source_revision: str

    total_count_records: int
    total_observations: int

    ordered_count_records_hash: str
    ordered_observations_hash: str

    created_utc: str

    def __post_init__(self) -> None:
        for name in (
            "metric_set_id",
            "run_id",
            "decision_set_id",
            "eligibility_set_id",
            "metric_policy_id",
        ):
            validate_id(str(getattr(self, name)))
        for name in (
            "metric_set_fingerprint",
            "run_fingerprint",
            "decision_set_fingerprint",
            "eligibility_set_fingerprint",
            "unconditional_view_fingerprint",
            "conditional_view_fingerprint",
            "non_mated_view_fingerprint",
            "metric_policy_fingerprint",
            "report_profile_fingerprint",
            "metric_software_fingerprint",
            "ordered_count_records_hash",
            "ordered_observations_hash",
        ):
            object.__setattr__(self, name, _require_digest(getattr(self, name), name))

        revision = str(self.metric_source_revision).strip().lower()
        if len(revision) != 40 or not set(revision) <= _HEX:
            raise ValueError(
                "metric_source_revision must be a full 40-character commit SHA"
            )
        object.__setattr__(self, "metric_source_revision", revision)

        for name in ("total_count_records", "total_observations"):
            object.__setattr__(self, name, _require_count(getattr(self, name), name))
        if self.total_count_records <= 0:
            raise ValueError("a metric set with no count records is not one")
        if self.total_observations <= 0:
            raise ValueError("a metric set with no observations is not one")

        created = str(self.created_utc).strip()
        if not created:
            raise ValueError("created_utc must not be empty")
        object.__setattr__(self, "created_utc", created)

        expected_fingerprint = metric_set_fingerprint(
            run_fingerprint=self.run_fingerprint,
            decision_set_fingerprint=self.decision_set_fingerprint,
            eligibility_set_fingerprint=self.eligibility_set_fingerprint,
            unconditional_view_fingerprint=self.unconditional_view_fingerprint,
            conditional_view_fingerprint=self.conditional_view_fingerprint,
            non_mated_view_fingerprint=self.non_mated_view_fingerprint,
            metric_policy_fingerprint=self.metric_policy_fingerprint,
            metric_software_fingerprint=self.metric_software_fingerprint,
            ordered_count_records_hash=self.ordered_count_records_hash,
            ordered_observations_hash=self.ordered_observations_hash,
        )
        if self.metric_set_fingerprint != expected_fingerprint:
            raise ValueError(
                "metric_set_fingerprint does not cover the manifest's claims"
            )
        expected_id = metric_set_id(self.metric_set_fingerprint)
        if self.metric_set_id != expected_id:
            raise ValueError(
                f"metric_set_id must be derived from the fingerprint: expected "
                f"{expected_id}, got {self.metric_set_id!r}"
            )
