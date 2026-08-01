"""Comparing two finished derivations of the same 6,000 pairs.

Everything here is about *one variable*. The native and canonical runs share a
protocol, a cohort, a pair manifest, an algorithm build, a bridge jar, a runtime
bundle and a threshold. They differ in which file the adapter opened. A paired
record exists to make that difference visible per comparison, and to make it
impossible to accidentally attribute a second difference to it.

Four ideas carry the module.

**Pairs are joined by ``pair_id``, never by ``job_id``.** A job id is a hash over
the run, so the same comparison has two different ones. Joining on it would
produce zero matches; joining on an ordinal alone would silently succeed while
comparing the wrong rows.

**Failure is preserved, never converted.** ``UNDECIDABLE`` is its own outcome on
both axes of every transition matrix. A comparison that produced no score did
not become a non-match by being compared with one (docs/adr/0006).

**Differences between rates are exact fractions.** ``a/b`` minus ``c/d`` is
``(cb - ad)/(bd)``, reduced. A decimal is a rendering, and a rendering that got
rounded twice is a number nobody can check (docs/adr/0026).

**Two rates over different populations are not subtracted.** The conditional
FNMRs of the two runs are computed over whichever fingers each run found
eligible, and those sets differ. Their difference is not an effect; it is an
effect plus a change in who was counted, and :class:`ComparabilityStatus` exists
so that the distinction survives into the stored record.

The dataclasses live in ``core`` because ``storage`` persists them and may only
import ``core``. Deriving them is :mod:`fpbench.paired`'s job.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from math import gcd
from types import MappingProxyType
from typing import Iterable, Mapping

from fpbench.core.enums import (
    ComparabilityStatus,
    DecisionApplicationStatus,
    DecisionOutcome,
    DecisionValue,
    ExecutionStatus,
    ProtocolStage,
    ScoreRelation,
)
from fpbench.core.identifiers import PairId, validate_id
from fpbench.core.provenance_models import (
    SoftwareProvenance,
    software_provenance_fingerprint,
)
from fpbench.core.serialization import require_exact_int, stable_hash, to_plain

__all__ = [
    "PAIRED_SCHEMA_VERSION",
    "PAIRED_EVALUATION_ID_LENGTH",
    "TRANSITION_FAMILIES",
    "PLAIN_SELF_FAMILY",
    "ROLL_SELF_FAMILY",
    "MATED_UNCONDITIONAL_FAMILY",
    "NEGATIVE_SANITY_FAMILY",
    "MATED_COMMON_ELIGIBLE_FAMILY",
    "ELIGIBILITY_FAMILY",
    "decision_outcome_of",
    "transition_key",
    "exact_rate_difference",
    "PairedComparisonRecord",
    "paired_comparison_record_hash",
    "ordered_paired_records_hash",
    "SelfEligibilityTransitionRecord",
    "eligibility_transition_record_hash",
    "ordered_eligibility_transitions_hash",
    "CommonEligibleMatedEntry",
    "common_eligible_entry_hash",
    "common_eligible_view_hash",
    "TransitionCountRecord",
    "transition_count_record_hash",
    "ordered_transition_counts_hash",
    "PairedRateObservation",
    "paired_rate_observation_hash",
    "ordered_paired_observations_hash",
    "NativeCanonicalControlAudit",
    "control_audit_fingerprint",
    "PairedEvaluationDefinition",
    "paired_evaluation_definition_fingerprint",
    "PairedEvaluationManifest",
    "paired_evaluation_fingerprint",
    "paired_evaluation_id",
    "PairedEvaluationReceipt",
    "paired_receipt_fingerprint",
    "paired_receipt_content_hash",
    "PairedFinalizationMarker",
    "paired_finalization_fingerprint",
    "NO_SUPERIORITY_STATEMENT",
]

#: Bumped when the meaning of any paired record changes. Inside every
#: fingerprint below, so a bump separates new artefacts from old.
PAIRED_SCHEMA_VERSION = "2"

#: Twelve hex characters, matching every other id in the project.
PAIRED_EVALUATION_ID_LENGTH = 12

PLAIN_SELF_FAMILY = "plain_self"
ROLL_SELF_FAMILY = "roll_self"
MATED_UNCONDITIONAL_FAMILY = "mated_unconditional"
NEGATIVE_SANITY_FAMILY = "negative_sanity"
MATED_COMMON_ELIGIBLE_FAMILY = "mated_common_eligible"
ELIGIBILITY_FAMILY = "eligibility"

#: The order transition families are stored and reported in. Fixed, because the
#: ordered hash over the count records depends on it.
TRANSITION_FAMILIES: tuple[str, ...] = (
    PLAIN_SELF_FAMILY,
    ROLL_SELF_FAMILY,
    MATED_UNCONDITIONAL_FAMILY,
    MATED_COMMON_ELIGIBLE_FAMILY,
    NEGATIVE_SANITY_FAMILY,
    ELIGIBILITY_FAMILY,
)

#: Printed on the paired receipt and at the head of the paired report.
NO_SUPERIORITY_STATEMENT = (
    "This comparison records what changed between two runs that differed in one "
    "thing: the image preparation path. It establishes no resolution "
    "superiority, no causal claim, no general false-match rate, and no "
    "statistical significance."
)

_HEX = frozenset("0123456789abcdef")


# ---------------------------------------------------------------- validation


def _require_digest(value: str, field_name: str) -> str:
    digest = str(value).strip().lower()
    if len(digest) != 64 or not set(digest) <= _HEX:
        raise ValueError(f"{field_name} must be a 64-character hexadecimal digest")
    return digest


def _require_non_empty(value: str, field_name: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{field_name} must not be empty")
    return text


def _require_non_negative(value: object, field_name: str) -> int:
    number = require_exact_int(value, field_name)
    if number < 0:
        raise ValueError(f"{field_name} must not be negative, got {number}")
    return number


def _freeze_counts(value: Mapping[str, int], field_name: str) -> Mapping[str, int]:
    return MappingProxyType(
        {
            str(key): _require_non_negative(item, f"{field_name}[{key}]")
            for key, item in sorted(dict(value).items())
        }
    )


def _freeze_strings(value: Mapping[str, str]) -> Mapping[str, str]:
    return MappingProxyType({str(k): str(v) for k, v in sorted(dict(value).items())})


# ------------------------------------------------------------------ outcomes


def decision_outcome_of(
    *, application_status: DecisionApplicationStatus, decision: DecisionValue | None
) -> DecisionOutcome:
    """Flatten a decision record's two fields into one three-valued outcome.

    Raises:
        ValueError: the two fields contradict each other. A decided record with
            no value, or an undecidable one carrying a verdict, is a record no
            transition matrix should be asked to place.
    """
    if application_status is DecisionApplicationStatus.UNDECIDABLE:
        if decision is not None:
            raise ValueError(
                "an undecidable decision carries no value; this record carries "
                f"{decision.value!r}"
            )
        return DecisionOutcome.UNDECIDABLE
    if decision is None:
        raise ValueError("a decided record must carry a value")
    return (
        DecisionOutcome.MATCH
        if decision is DecisionValue.MATCH
        else DecisionOutcome.NON_MATCH
    )


def transition_key(native: DecisionOutcome, canonical: DecisionOutcome) -> str:
    """``native_to_canonical``, the key a transition matrix counts under.

    Both states are kept, rather than a single "changed"/"unchanged" label,
    because ``MATCH -> NON_MATCH`` and ``NON_MATCH -> MATCH`` are opposite
    findings and a compound label would hide which happened (spec section 34).
    """
    return f"{native.value}_to_{canonical.value}"


def _all_transition_keys() -> tuple[str, ...]:
    return tuple(
        transition_key(native, canonical)
        for native in DecisionOutcome
        for canonical in DecisionOutcome
    )


#: All nine cells, always present even when zero. A matrix that omitted its
#: empty cells would let a reader mistake "none of these happened" for "this
#: was not measured" (spec section 38).
ALL_TRANSITION_KEYS: tuple[str, ...] = _all_transition_keys()


# ------------------------------------------------------------ exact fractions


def exact_rate_difference(
    *,
    native_numerator: int,
    native_denominator: int,
    canonical_numerator: int,
    canonical_denominator: int,
) -> tuple[int, int] | None:
    """``canonical - native``, as a reduced fraction.

    ``c/d - a/b`` is ``(cb - ad)/(bd)``. Reduced by the greatest common divisor,
    with the sign kept on the numerator, so the same difference always stores the
    same pair of integers.

    Returns ``None`` when either side has nothing to divide by. A difference
    against an undefined rate is undefined, not zero (docs/adr/0026).
    """
    b = _require_non_negative(native_denominator, "native_denominator")
    d = _require_non_negative(canonical_denominator, "canonical_denominator")
    a = _require_non_negative(native_numerator, "native_numerator")
    c = _require_non_negative(canonical_numerator, "canonical_numerator")
    if a > b:
        raise ValueError("a numerator may not exceed its denominator")
    if c > d:
        raise ValueError("a numerator may not exceed its denominator")
    if b == 0 or d == 0:
        return None

    numerator = c * b - a * d
    denominator = b * d
    divisor = gcd(abs(numerator), denominator) or 1
    return numerator // divisor, denominator // divisor


def _decimal_delta(native: str | None, canonical: str | None) -> str | None:
    """``canonical - native`` as an exact decimal string, or ``None``.

    Scores are stored as decimal strings so that no float ever enters the
    comparison. ``Decimal`` subtraction of two exact decimals is exact.
    """
    if native is None or canonical is None:
        return None
    try:
        difference = Decimal(canonical) - Decimal(native)
    except InvalidOperation as exc:  # pragma: no cover - the store validates first
        raise ValueError(f"unusable score decimal ({exc})") from exc
    return format(difference, "f")


# ------------------------------------------------------------- paired record


@dataclass(frozen=True, slots=True)
class PairedComparisonRecord:
    """One comparison, as both runs performed it.

    Carries the two job ids because they legitimately differ — a job id is a
    hash over the run — and the two raw-result hashes so that a verifier can go
    back to the stored results rather than trusting this row.

    Carries no float. ``score_delta_decimal`` is an exact decimal string, and it
    is ``None`` whenever either side produced no score.
    """

    ordinal: int
    pair_id: PairId

    release: str
    protocol_stage: ProtocolStage

    native_job_id: str
    canonical_job_id: str

    native_raw_result_hash: str
    canonical_raw_result_hash: str

    native_decision_hash: str
    canonical_decision_hash: str

    native_execution_status: ExecutionStatus
    canonical_execution_status: ExecutionStatus
    native_failure_code: str | None
    canonical_failure_code: str | None

    native_outcome: DecisionOutcome
    canonical_outcome: DecisionOutcome

    score_relation: ScoreRelation
    score_delta_decimal: str | None

    record_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "ordinal", _require_non_negative(self.ordinal, "ordinal")
        )
        object.__setattr__(self, "pair_id", PairId(validate_id(str(self.pair_id))))
        object.__setattr__(self, "release", _require_non_empty(self.release, "release"))
        for name in ("native_job_id", "canonical_job_id"):
            validate_id(str(getattr(self, name)))
        for name in (
            "native_raw_result_hash",
            "canonical_raw_result_hash",
            "native_decision_hash",
            "canonical_decision_hash",
            "record_hash",
        ):
            object.__setattr__(self, name, _require_digest(getattr(self, name), name))
        for prefix in ("native", "canonical"):
            status = getattr(self, f"{prefix}_execution_status")
            outcome = getattr(self, f"{prefix}_outcome")
            failure_code = getattr(self, f"{prefix}_failure_code")
            if status is ExecutionStatus.SUCCESS:
                if failure_code is not None:
                    raise ValueError(
                        f"{prefix}: a successful result must not carry a failure code"
                    )
                if outcome is DecisionOutcome.UNDECIDABLE:
                    raise ValueError(
                        f"{prefix}: a successful result must carry a decided outcome"
                    )
            else:
                code = _require_non_empty(failure_code or "", f"{prefix}_failure_code")
                object.__setattr__(self, f"{prefix}_failure_code", code)
                if outcome is not DecisionOutcome.UNDECIDABLE:
                    raise ValueError(
                        f"{prefix}: a failed result must carry an undecidable outcome"
                    )
        if self.score_delta_decimal is not None:
            object.__setattr__(
                self,
                "score_delta_decimal",
                _require_non_empty(self.score_delta_decimal, "score_delta_decimal"),
            )

        # A relation and a delta have to agree about whether a comparison was
        # possible. Either both sides scored, or neither claim is made.
        unavailable = self.score_relation is ScoreRelation.UNAVAILABLE
        if unavailable and self.score_delta_decimal is not None:
            raise ValueError(
                "an unavailable score relation carries no delta; at least one "
                "side produced no score"
            )
        if not unavailable and self.score_delta_decimal is None:
            raise ValueError(
                f"score relation {self.score_relation.value!r} claims both sides "
                "scored, but no delta is recorded"
            )
        if not unavailable:
            delta = Decimal(self.score_delta_decimal)
            expected = (
                ScoreRelation.EQUAL
                if delta == 0
                else ScoreRelation.CANONICAL_HIGHER
                if delta > 0
                else ScoreRelation.CANONICAL_LOWER
            )
            if self.score_relation is not expected:
                raise ValueError(
                    f"a delta of {self.score_delta_decimal} is "
                    f"{expected.value!r}, not {self.score_relation.value!r}"
                )
        if unavailable and DecisionOutcome.UNDECIDABLE not in (
            self.native_outcome,
            self.canonical_outcome,
        ):
            raise ValueError(
                "no score was available, yet both sides recorded a decided "
                "outcome; the decisions and the results disagree"
            )

        expected_hash = paired_comparison_record_hash(self)
        if self.record_hash != expected_hash:
            raise ValueError(
                f"{self.pair_id}: record_hash does not cover this record"
            )

    @property
    def transition(self) -> str:
        return transition_key(self.native_outcome, self.canonical_outcome)

    @property
    def changed(self) -> bool:
        return self.native_outcome is not self.canonical_outcome


def paired_comparison_record_hash(record: PairedComparisonRecord) -> str:
    """A digest of what this pair did, excluding its position in the list."""
    return stable_hash(
        {
            "schema": "paired_comparison_record_hash_v1",
            "paired_schema_version": PAIRED_SCHEMA_VERSION,
            "pair_id": str(record.pair_id),
            "release": record.release,
            "protocol_stage": record.protocol_stage.value,
            "native": {
                "job_id": record.native_job_id,
                "raw_result_hash": record.native_raw_result_hash,
                "decision_hash": record.native_decision_hash,
                "outcome": record.native_outcome.value,
                "execution_status": record.native_execution_status.value,
                "failure_code": record.native_failure_code,
            },
            "canonical": {
                "job_id": record.canonical_job_id,
                "raw_result_hash": record.canonical_raw_result_hash,
                "decision_hash": record.canonical_decision_hash,
                "outcome": record.canonical_outcome.value,
                "execution_status": record.canonical_execution_status.value,
                "failure_code": record.canonical_failure_code,
            },
            "score_relation": record.score_relation.value,
            "score_delta_decimal": record.score_delta_decimal,
        },
        length=64,
    )


def ordered_paired_records_hash(records: Iterable[PairedComparisonRecord]) -> str:
    """A digest of the records in pair-manifest order. Order is identity."""
    return stable_hash(
        {
            "schema": "paired_ordered_records_v1",
            "records": [
                {
                    "ordinal": record.ordinal,
                    "pair_id": str(record.pair_id),
                    "record_hash": record.record_hash,
                }
                for record in records
            ],
        },
        length=64,
    )


# ------------------------------------------------------ eligibility transition


@dataclass(frozen=True, slots=True)
class SelfEligibilityTransitionRecord:
    """One SELF unit's eligibility verdict, as both runs reached it.

    ``subject_id`` and ``finger_id`` are here because a transition has to be
    traceable to the finger it describes. They are internal: the public receipt
    carries counts and never these fields (spec section 37).
    """

    ordinal: int

    eligibility_unit_id: str
    release: str
    subject_id: str
    finger_id: int

    native_record_hash: str
    canonical_record_hash: str

    native_status: str
    canonical_status: str

    record_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "ordinal", _require_non_negative(self.ordinal, "ordinal")
        )
        validate_id(str(self.eligibility_unit_id))
        for name in ("release", "subject_id", "native_status", "canonical_status"):
            object.__setattr__(
                self, name, _require_non_empty(getattr(self, name), name)
            )
        finger = require_exact_int(self.finger_id, "finger_id")
        if not 1 <= finger <= 10:
            raise ValueError(
                f"finger_id must be an ANSI/NIST FRGP 1-10 position, got {finger}"
            )
        object.__setattr__(self, "finger_id", finger)
        for name in (
            "native_record_hash",
            "canonical_record_hash",
            "record_hash",
        ):
            object.__setattr__(self, name, _require_digest(getattr(self, name), name))

        expected = eligibility_transition_record_hash(self)
        if self.record_hash != expected:
            raise ValueError(
                f"{self.eligibility_unit_id}: record_hash does not cover this record"
            )

    @property
    def transition(self) -> str:
        return f"{self.native_status}_to_{self.canonical_status}"

    @property
    def common_eligible(self) -> bool:
        """Both runs found this finger eligible.

        The only combination that enters the fair conditional comparison. One
        run's ``ELIGIBLE`` against the other's ``INELIGIBLE`` is a *difference*,
        not a shared population (spec section 39).
        """
        return self.native_status == "eligible" and self.canonical_status == "eligible"


def eligibility_transition_record_hash(
    record: SelfEligibilityTransitionRecord,
) -> str:
    return stable_hash(
        {
            "schema": "paired_eligibility_transition_hash_v1",
            "paired_schema_version": PAIRED_SCHEMA_VERSION,
            "eligibility_unit_id": record.eligibility_unit_id,
            "release": record.release,
            "subject_id": record.subject_id,
            "finger_id": record.finger_id,
            "native": {
                "record_hash": record.native_record_hash,
                "status": record.native_status,
            },
            "canonical": {
                "record_hash": record.canonical_record_hash,
                "status": record.canonical_status,
            },
        },
        length=64,
    )


def ordered_eligibility_transitions_hash(
    records: Iterable[SelfEligibilityTransitionRecord],
) -> str:
    return stable_hash(
        {
            "schema": "paired_ordered_eligibility_transitions_v1",
            "records": [
                {
                    "ordinal": record.ordinal,
                    "eligibility_unit_id": record.eligibility_unit_id,
                    "record_hash": record.record_hash,
                }
                for record in records
            ],
        },
        length=64,
    )


# -------------------------------------------------------- common-eligible view


@dataclass(frozen=True, slots=True)
class CommonEligibleMatedEntry:
    """One mated comparison, and whether both runs found its finger eligible.

    Excluded rows stay in the view. A view that dropped them would be unable to
    say *why* its denominator is what it is, and the selection fraction is the
    one number a conditional result may never be published without
    (docs/adr/0029).
    """

    ordinal: int
    pair_id: PairId

    release: str

    native_eligibility_status: str
    canonical_eligibility_status: str

    included: bool

    native_job_id: str
    canonical_job_id: str

    native_decision_hash: str
    canonical_decision_hash: str

    native_outcome: DecisionOutcome
    canonical_outcome: DecisionOutcome

    entry_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "ordinal", _require_non_negative(self.ordinal, "ordinal")
        )
        object.__setattr__(self, "pair_id", PairId(validate_id(str(self.pair_id))))
        for name in (
            "release",
            "native_eligibility_status",
            "canonical_eligibility_status",
        ):
            object.__setattr__(
                self, name, _require_non_empty(getattr(self, name), name)
            )
        for name in ("native_job_id", "canonical_job_id"):
            validate_id(str(getattr(self, name)))
        for name in ("native_decision_hash", "canonical_decision_hash", "entry_hash"):
            object.__setattr__(self, name, _require_digest(getattr(self, name), name))
        if type(self.included) is not bool:
            raise ValueError("included must be a bool")

        expected_inclusion = (
            self.native_eligibility_status == "eligible"
            and self.canonical_eligibility_status == "eligible"
        )
        if self.included is not expected_inclusion:
            raise ValueError(
                f"{self.pair_id}: included is {self.included} but the two "
                f"eligibility statuses are {self.native_eligibility_status!r} and "
                f"{self.canonical_eligibility_status!r}; membership is derived, "
                "never asserted"
            )

        expected = common_eligible_entry_hash(self)
        if self.entry_hash != expected:
            raise ValueError(f"{self.pair_id}: entry_hash does not cover this entry")


def common_eligible_entry_hash(entry: CommonEligibleMatedEntry) -> str:
    return stable_hash(
        {
            "schema": "paired_common_eligible_entry_hash_v1",
            "paired_schema_version": PAIRED_SCHEMA_VERSION,
            "pair_id": str(entry.pair_id),
            "release": entry.release,
            "native": {
                "eligibility_status": entry.native_eligibility_status,
                "job_id": entry.native_job_id,
                "decision_hash": entry.native_decision_hash,
                "outcome": entry.native_outcome.value,
            },
            "canonical": {
                "eligibility_status": entry.canonical_eligibility_status,
                "job_id": entry.canonical_job_id,
                "decision_hash": entry.canonical_decision_hash,
                "outcome": entry.canonical_outcome.value,
            },
            "included": entry.included,
        },
        length=64,
    )


def common_eligible_view_hash(entries: Iterable[CommonEligibleMatedEntry]) -> str:
    return stable_hash(
        {
            "schema": "paired_common_eligible_view_v1",
            "entries": [
                {
                    "ordinal": entry.ordinal,
                    "pair_id": str(entry.pair_id),
                    "entry_hash": entry.entry_hash,
                }
                for entry in entries
            ],
        },
        length=64,
    )


# ---------------------------------------------------------------- aggregates


@dataclass(frozen=True, slots=True)
class MetricScopeRef:
    """Release, or pooled. A local stand-in for the metric layer's scope.

    Deliberately not imported from :mod:`fpbench.core.metric_models`: a paired
    scope is a property of a comparison rather than of a metric set, and reusing
    the type would suggest the two are interchangeable.
    """

    scope_kind: str
    release: str | None = None

    def __post_init__(self) -> None:
        kind = _require_non_empty(self.scope_kind, "scope_kind")
        if kind not in {"release", "pooled"}:
            raise ValueError(f"scope_kind must be release or pooled, got {kind!r}")
        object.__setattr__(self, "scope_kind", kind)
        if kind == "release":
            object.__setattr__(
                self, "release", _require_non_empty(str(self.release), "release")
            )
        elif self.release is not None:
            raise ValueError("a pooled scope names no release")

    @property
    def label(self) -> str:
        return self.release if self.scope_kind == "release" else "pooled"


@dataclass(frozen=True, slots=True)
class TransitionCountRecord:
    """One transition matrix, at one scope.

    ``counts`` holds every cell the family can produce, zeros included, so that
    a reader never has to decide whether a missing key means zero or means
    unmeasured.
    """

    ordinal: int
    family: str
    scope: MetricScopeRef

    total: int
    counts: Mapping[str, int]

    source_fingerprints: Mapping[str, str]
    record_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "ordinal", _require_non_negative(self.ordinal, "ordinal")
        )
        object.__setattr__(self, "family", _require_non_empty(self.family, "family"))
        if self.family not in TRANSITION_FAMILIES:
            raise ValueError(
                f"unknown transition family {self.family!r}; known: "
                f"{list(TRANSITION_FAMILIES)}"
            )
        object.__setattr__(
            self, "total", _require_non_negative(self.total, "total")
        )
        object.__setattr__(self, "counts", _freeze_counts(self.counts, "counts"))
        object.__setattr__(
            self, "source_fingerprints", _freeze_strings(self.source_fingerprints)
        )
        object.__setattr__(
            self, "record_hash", _require_digest(self.record_hash, "record_hash")
        )

        if sum(self.counts.values()) != self.total:
            raise ValueError(
                f"{self.family} at {self.scope.label}: the cells sum to "
                f"{sum(self.counts.values())} but the total is {self.total}; every "
                "row has to land somewhere"
            )

        expected = transition_count_record_hash(self)
        if self.record_hash != expected:
            raise ValueError(
                f"{self.family} at {self.scope.label}: record_hash does not cover "
                "this record"
            )


def transition_count_record_hash(record: TransitionCountRecord) -> str:
    return stable_hash(
        {
            "schema": "paired_transition_count_hash_v1",
            "paired_schema_version": PAIRED_SCHEMA_VERSION,
            "family": record.family,
            "scope": {
                "scope_kind": record.scope.scope_kind,
                "release": record.scope.release,
            },
            "total": record.total,
            "counts": dict(record.counts),
            "source_fingerprints": dict(record.source_fingerprints),
        },
        length=64,
    )


def ordered_transition_counts_hash(records: Iterable[TransitionCountRecord]) -> str:
    return stable_hash(
        {
            "schema": "paired_ordered_transition_counts_v1",
            "records": [
                {
                    "ordinal": record.ordinal,
                    "family": record.family,
                    "scope": record.scope.label,
                    "record_hash": record.record_hash,
                }
                for record in records
            ],
        },
        length=64,
    )


@dataclass(frozen=True, slots=True)
class PairedRateObservation:
    """One rate, on both sides, and their exact difference if there is one.

    Four integers and a comparability verdict. No percentage is stored: a
    percentage is a rendering, and the moment one is stored somebody subtracts
    two of them (docs/adr/0026).
    """

    ordinal: int
    observation_id: str
    scope: MetricScopeRef

    native_numerator: int
    native_denominator: int

    canonical_numerator: int
    canonical_denominator: int

    difference_numerator: int | None
    difference_denominator: int | None

    comparability: ComparabilityStatus

    policy_fingerprint: str
    observation_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "ordinal", _require_non_negative(self.ordinal, "ordinal")
        )
        validate_id(str(self.observation_id))
        for name in (
            "native_numerator",
            "native_denominator",
            "canonical_numerator",
            "canonical_denominator",
        ):
            object.__setattr__(
                self, name, _require_non_negative(getattr(self, name), name)
            )
        object.__setattr__(
            self,
            "policy_fingerprint",
            _require_digest(self.policy_fingerprint, "policy_fingerprint"),
        )
        object.__setattr__(
            self,
            "observation_hash",
            _require_digest(self.observation_hash, "observation_hash"),
        )

        if self.native_numerator > self.native_denominator:
            raise ValueError("a numerator may not exceed its denominator")
        if self.canonical_numerator > self.canonical_denominator:
            raise ValueError("a numerator may not exceed its denominator")

        has_difference = self.difference_numerator is not None
        if has_difference != (self.difference_denominator is not None):
            raise ValueError(
                "a difference is a fraction: both parts, or neither"
            )
        if has_difference:
            object.__setattr__(
                self,
                "difference_numerator",
                require_exact_int(self.difference_numerator, "difference_numerator"),
            )
            denominator = require_exact_int(
                self.difference_denominator, "difference_denominator"
            )
            if denominator <= 0:
                raise ValueError("difference_denominator must be positive")
            object.__setattr__(self, "difference_denominator", denominator)

            expected = exact_rate_difference(
                native_numerator=self.native_numerator,
                native_denominator=self.native_denominator,
                canonical_numerator=self.canonical_numerator,
                canonical_denominator=self.canonical_denominator,
            )
            if expected != (self.difference_numerator, self.difference_denominator):
                raise ValueError(
                    f"{self.observation_id}: the stored difference is not the exact "
                    f"reduced difference of the four counts"
                )

        # A difference may only exist where the two sides are comparable at all.
        if self.comparability in {
            ComparabilityStatus.DIFFERENT_SELECTION,
            ComparabilityStatus.SAME_ATTEMPTS_DIFFERENT_DECIDED_SUBSETS,
            ComparabilityStatus.UNDEFINED,
        } and has_difference:
            raise ValueError(
                f"{self.observation_id}: comparability is "
                f"{self.comparability.value!r}, so no difference may be recorded. "
                "Two rates over different populations do not subtract"
            )

        expected_hash = paired_rate_observation_hash(self)
        if self.observation_hash != expected_hash:
            raise ValueError(
                f"{self.observation_id}: observation_hash does not cover this "
                "observation"
            )

    @property
    def has_difference(self) -> bool:
        return self.difference_numerator is not None


def paired_rate_observation_hash(observation: PairedRateObservation) -> str:
    return stable_hash(
        {
            "schema": "paired_rate_observation_hash_v1",
            "paired_schema_version": PAIRED_SCHEMA_VERSION,
            "observation_id": observation.observation_id,
            "scope": {
                "scope_kind": observation.scope.scope_kind,
                "release": observation.scope.release,
            },
            "native": {
                "numerator": observation.native_numerator,
                "denominator": observation.native_denominator,
            },
            "canonical": {
                "numerator": observation.canonical_numerator,
                "denominator": observation.canonical_denominator,
            },
            "difference": {
                "numerator": observation.difference_numerator,
                "denominator": observation.difference_denominator,
            },
            "comparability": observation.comparability.value,
            "policy_fingerprint": observation.policy_fingerprint,
        },
        length=64,
    )


def ordered_paired_observations_hash(
    observations: Iterable[PairedRateObservation],
) -> str:
    return stable_hash(
        {
            "schema": "paired_ordered_observations_v1",
            "observations": [
                {
                    "ordinal": observation.ordinal,
                    "observation_id": observation.observation_id,
                    "scope": observation.scope.label,
                    "observation_hash": observation.observation_hash,
                }
                for observation in observations
            ],
        },
        length=64,
    )


# --------------------------------------------------------------- control audit


@dataclass(frozen=True, slots=True)
class NativeCanonicalControlAudit:
    """The SD300A control: identical pixels must produce identical everything.

    SD300A's canonical artefacts preserve their source rasters byte for byte —
    stage 6A proved that for all 1,000 images. The two runs used the same
    SourceAFIS build, the same bridge, the same pair orientation and a
    deterministic algorithm. So every one of the 2,000 SD300A comparisons must
    have produced the same score, the same execution status and the same
    decision.

    One mismatch means something other than image preparation differs between the
    runs, and every number in the comparison is then measuring an unknown sum.
    There is no tolerance and no rounding (spec section 32).
    """

    planned_sd300a_pairs: int
    compared_scores: int
    equal_scores: int
    equal_result_statuses: int
    equal_decisions: int
    issues: tuple[str, ...]

    audit_fingerprint: str

    def __post_init__(self) -> None:
        for name in (
            "planned_sd300a_pairs",
            "compared_scores",
            "equal_scores",
            "equal_result_statuses",
            "equal_decisions",
        ):
            object.__setattr__(
                self, name, _require_non_negative(getattr(self, name), name)
            )
        object.__setattr__(self, "issues", tuple(str(item) for item in self.issues))
        object.__setattr__(
            self,
            "audit_fingerprint",
            _require_digest(self.audit_fingerprint, "audit_fingerprint"),
        )
        expected = control_audit_fingerprint(self)
        if self.audit_fingerprint != expected:
            raise ValueError("audit_fingerprint does not cover this audit")

    @property
    def is_clean(self) -> bool:
        """Every SD300A pair compared, and every one of them identical."""
        expected = self.planned_sd300a_pairs
        return bool(expected) and not self.issues and all(
            value == expected
            for value in (
                self.compared_scores,
                self.equal_scores,
                self.equal_result_statuses,
                self.equal_decisions,
            )
        )


def control_audit_fingerprint(audit: NativeCanonicalControlAudit) -> str:
    return stable_hash(
        {
            "schema": "paired_control_audit_fingerprint_v1",
            "paired_schema_version": PAIRED_SCHEMA_VERSION,
            "planned_sd300a_pairs": audit.planned_sd300a_pairs,
            "compared_scores": audit.compared_scores,
            "equal_scores": audit.equal_scores,
            "equal_result_statuses": audit.equal_result_statuses,
            "equal_decisions": audit.equal_decisions,
            "issues": list(audit.issues),
        },
        length=64,
    )


# ----------------------------------------------------------------- definition


@dataclass(frozen=True, slots=True)
class PairedEvaluationDefinition:
    """What a paired comparison pinned, before it compared anything."""

    definition_id: str
    definition_fingerprint: str

    native_run_fingerprint: str
    canonical_run_fingerprint: str

    native_result_set_fingerprint: str
    canonical_result_set_fingerprint: str

    native_decision_set_fingerprint: str
    canonical_decision_set_fingerprint: str

    native_eligibility_set_fingerprint: str
    canonical_eligibility_set_fingerprint: str

    native_metric_set_fingerprint: str
    canonical_metric_set_fingerprint: str

    pair_manifest_hash: str
    policy_fingerprint: str

    derivation_software: SoftwareProvenance
    derivation_software_fingerprint: str

    created_utc: str

    def __post_init__(self) -> None:
        validate_id(str(self.definition_id))
        for name in (
            "definition_fingerprint",
            "native_run_fingerprint",
            "canonical_run_fingerprint",
            "native_result_set_fingerprint",
            "canonical_result_set_fingerprint",
            "native_decision_set_fingerprint",
            "canonical_decision_set_fingerprint",
            "native_eligibility_set_fingerprint",
            "canonical_eligibility_set_fingerprint",
            "native_metric_set_fingerprint",
            "canonical_metric_set_fingerprint",
            "pair_manifest_hash",
            "policy_fingerprint",
            "derivation_software_fingerprint",
        ):
            object.__setattr__(self, name, _require_digest(getattr(self, name), name))
        object.__setattr__(
            self, "created_utc", _require_non_empty(self.created_utc, "created_utc")
        )

        # Two runs of the same thing would make the comparison vacuous.
        if self.native_run_fingerprint == self.canonical_run_fingerprint:
            raise ValueError(
                "the two runs have the same fingerprint; a paired comparison "
                "needs two different runs"
            )

        expected = paired_evaluation_definition_fingerprint(self.claims())
        if self.definition_fingerprint != expected:
            raise ValueError("definition_fingerprint does not cover these claims")
        if self.definition_id != f"paireddef_{expected[:PAIRED_EVALUATION_ID_LENGTH]}":
            raise ValueError("definition_id must be derived from the fingerprint")
        actual_software_fingerprint = software_provenance_fingerprint(
            self.derivation_software
        )
        if self.derivation_software_fingerprint != actual_software_fingerprint:
            raise ValueError(
                "derivation_software_fingerprint does not cover derivation_software"
            )

    def claims(self) -> Mapping[str, object]:
        return {
            "paired_schema_version": PAIRED_SCHEMA_VERSION,
            "native_run_fingerprint": self.native_run_fingerprint,
            "canonical_run_fingerprint": self.canonical_run_fingerprint,
            "native_result_set_fingerprint": self.native_result_set_fingerprint,
            "canonical_result_set_fingerprint": self.canonical_result_set_fingerprint,
            "native_decision_set_fingerprint": self.native_decision_set_fingerprint,
            "canonical_decision_set_fingerprint": (
                self.canonical_decision_set_fingerprint
            ),
            "native_eligibility_set_fingerprint": (
                self.native_eligibility_set_fingerprint
            ),
            "canonical_eligibility_set_fingerprint": (
                self.canonical_eligibility_set_fingerprint
            ),
            "native_metric_set_fingerprint": self.native_metric_set_fingerprint,
            "canonical_metric_set_fingerprint": self.canonical_metric_set_fingerprint,
            "pair_manifest_hash": self.pair_manifest_hash,
            "policy_fingerprint": self.policy_fingerprint,
            "derivation_software_fingerprint": self.derivation_software_fingerprint,
        }


def paired_evaluation_definition_fingerprint(claims: Mapping[str, object]) -> str:
    return stable_hash(
        {"schema": "paired_evaluation_definition_fingerprint_v1", "claims": dict(claims)},
        length=64,
    )


# ------------------------------------------------------------------- manifest


@dataclass(frozen=True, slots=True)
class PairedEvaluationManifest:
    """The identity of one immutable paired comparison."""

    paired_evaluation_id: str
    paired_evaluation_fingerprint: str

    definition_fingerprint: str

    total_paired_comparisons: int
    total_eligibility_units: int
    total_common_eligible_rows: int

    ordered_paired_records_hash: str
    ordered_eligibility_transitions_hash: str
    common_eligible_view_hash: str
    ordered_count_records_hash: str
    ordered_observations_hash: str

    control_audit_fingerprint: str

    created_utc: str

    def __post_init__(self) -> None:
        validate_id(str(self.paired_evaluation_id))
        for name in (
            "paired_evaluation_fingerprint",
            "definition_fingerprint",
            "ordered_paired_records_hash",
            "ordered_eligibility_transitions_hash",
            "common_eligible_view_hash",
            "ordered_count_records_hash",
            "ordered_observations_hash",
            "control_audit_fingerprint",
        ):
            object.__setattr__(self, name, _require_digest(getattr(self, name), name))
        for name in (
            "total_paired_comparisons",
            "total_eligibility_units",
            "total_common_eligible_rows",
        ):
            object.__setattr__(
                self, name, _require_non_negative(getattr(self, name), name)
            )
        object.__setattr__(
            self, "created_utc", _require_non_empty(self.created_utc, "created_utc")
        )
        if self.total_paired_comparisons <= 0:
            raise ValueError("a paired comparison with no pairs is not one")

        expected_id = paired_evaluation_id(self.paired_evaluation_fingerprint)
        if self.paired_evaluation_id != expected_id:
            raise ValueError(
                f"paired_evaluation_id must be derived from the fingerprint: "
                f"expected {expected_id}, got {self.paired_evaluation_id!r}"
            )
        expected_fingerprint = paired_evaluation_fingerprint(
            definition_fingerprint=self.definition_fingerprint,
            ordered_records_hash=self.ordered_paired_records_hash,
            ordered_eligibility_hash=self.ordered_eligibility_transitions_hash,
            common_eligible_hash=self.common_eligible_view_hash,
            ordered_counts_hash=self.ordered_count_records_hash,
            ordered_observations_hash=self.ordered_observations_hash,
            control_fingerprint=self.control_audit_fingerprint,
            total_paired_comparisons=self.total_paired_comparisons,
            total_eligibility_units=self.total_eligibility_units,
            total_common_eligible_rows=self.total_common_eligible_rows,
        )
        if self.paired_evaluation_fingerprint != expected_fingerprint:
            raise ValueError(
                "paired_evaluation_fingerprint does not cover the manifest fields"
            )


def paired_evaluation_fingerprint(
    *,
    definition_fingerprint: str,
    ordered_records_hash: str,
    ordered_eligibility_hash: str,
    common_eligible_hash: str,
    ordered_counts_hash: str,
    ordered_observations_hash: str,
    control_fingerprint: str,
    total_paired_comparisons: int,
    total_eligibility_units: int,
    total_common_eligible_rows: int,
) -> str:
    """The digest behind ``paired_evaluation_id``.

    Carries no timestamp and no file path. The same two chains compared again
    tomorrow, in a different workspace, are the same comparison.
    """
    return stable_hash(
        {
            "schema": "paired_evaluation_fingerprint_v1",
            "paired_schema_version": PAIRED_SCHEMA_VERSION,
            "definition_fingerprint": definition_fingerprint,
            "ordered_paired_records_hash": ordered_records_hash,
            "ordered_eligibility_transitions_hash": ordered_eligibility_hash,
            "common_eligible_view_hash": common_eligible_hash,
            "ordered_count_records_hash": ordered_counts_hash,
            "ordered_observations_hash": ordered_observations_hash,
            "control_audit_fingerprint": control_fingerprint,
            "total_paired_comparisons": int(total_paired_comparisons),
            "total_eligibility_units": int(total_eligibility_units),
            "total_common_eligible_rows": int(total_common_eligible_rows),
        },
        length=64,
    )


def paired_evaluation_id(fingerprint: str) -> str:
    """``pairedeval_<12 chars of the paired fingerprint>``."""
    digest = _require_digest(fingerprint, "paired_evaluation_fingerprint")
    return f"pairedeval_{digest[:PAIRED_EVALUATION_ID_LENGTH]}"


# -------------------------------------------------------------------- receipt


@dataclass(frozen=True, slots=True)
class PairedEvaluationReceipt:
    """The committable statement of a paired comparison.

    It may carry identities, the control audit's counts, the aggregate
    transition counts and the paired rate observations. It may not carry a pair
    id, a job id, a subject, a finger, an image, a filename, a path, a raw score,
    a per-pair delta or a template (spec section 65).
    """

    schema_version: str

    paired_evaluation_id: str
    paired_evaluation_fingerprint: str
    definition_fingerprint: str

    policy_id: str
    policy_fingerprint: str

    native_run_id: str
    native_result_set_id: str
    native_decision_set_id: str
    native_eligibility_set_id: str
    native_metric_set_id: str

    canonical_run_id: str
    canonical_result_set_id: str
    canonical_decision_set_id: str
    canonical_eligibility_set_id: str
    canonical_metric_set_id: str
    canonical_preparation_set_id: str

    pair_manifest_hash: str

    source_commit: str
    source_tree_clean: bool

    total_paired_comparisons: int
    total_eligibility_units: int
    total_common_eligible_rows: int

    control_audit: Mapping[str, int]
    transition_counts: Mapping[str, Mapping[str, int]]
    rate_observations: Mapping[str, Mapping[str, str]]

    statement: str
    created_utc: str

    def __post_init__(self) -> None:
        for name in (
            "paired_evaluation_id",
            "policy_id",
            "native_run_id",
            "native_result_set_id",
            "native_decision_set_id",
            "native_eligibility_set_id",
            "native_metric_set_id",
            "canonical_run_id",
            "canonical_result_set_id",
            "canonical_decision_set_id",
            "canonical_eligibility_set_id",
            "canonical_metric_set_id",
            "canonical_preparation_set_id",
        ):
            validate_id(str(getattr(self, name)))
        for name in (
            "paired_evaluation_fingerprint",
            "definition_fingerprint",
            "policy_fingerprint",
            "pair_manifest_hash",
        ):
            object.__setattr__(self, name, _require_digest(getattr(self, name), name))
        for name in ("schema_version", "source_commit", "statement", "created_utc"):
            object.__setattr__(
                self, name, _require_non_empty(getattr(self, name), name)
            )
        if type(self.source_tree_clean) is not bool:
            raise ValueError("source_tree_clean must be a bool")
        for name in (
            "total_paired_comparisons",
            "total_eligibility_units",
            "total_common_eligible_rows",
        ):
            object.__setattr__(
                self, name, _require_non_negative(getattr(self, name), name)
            )
        object.__setattr__(
            self, "control_audit", _freeze_counts(self.control_audit, "control_audit")
        )
        object.__setattr__(
            self,
            "transition_counts",
            MappingProxyType(
                {
                    str(key): _freeze_counts(value, f"transition_counts[{key}]")
                    for key, value in sorted(dict(self.transition_counts).items())
                }
            ),
        )
        object.__setattr__(
            self,
            "rate_observations",
            MappingProxyType(
                {
                    str(key): _freeze_strings(value)
                    for key, value in sorted(dict(self.rate_observations).items())
                }
            ),
        )


def paired_receipt_fingerprint(receipt: PairedEvaluationReceipt) -> str:
    """A digest of the receipt's claims, with ``created_utc`` excluded."""
    payload = dict(to_plain(receipt))
    payload.pop("created_utc", None)
    return stable_hash(
        {"schema": "paired_receipt_fingerprint_v1", "receipt": payload}, length=64
    )


def paired_receipt_content_hash(receipt: PairedEvaluationReceipt) -> str:
    """A digest of the exact receipt, ``created_utc`` included."""
    return stable_hash(
        {"schema": "paired_receipt_content_hash_v1", "receipt": to_plain(receipt)},
        length=64,
    )


# --------------------------------------------------------------------- marker


@dataclass(frozen=True, slots=True)
class PairedFinalizationMarker:
    """The last file written, and the only one that makes the rest authoritative."""

    schema_version: str

    finalization_id: str
    finalization_fingerprint: str

    paired_evaluation_id: str
    paired_evaluation_fingerprint: str
    definition_fingerprint: str

    control_audit_fingerprint: str
    summary_content_hash: str
    report_content_hash: str

    receipt_fingerprint: str
    receipt_content_hash: str

    source_commit: str
    source_tree_clean: bool

    created_utc: str

    def __post_init__(self) -> None:
        validate_id(str(self.finalization_id))
        validate_id(str(self.paired_evaluation_id))
        for name in (
            "finalization_fingerprint",
            "paired_evaluation_fingerprint",
            "definition_fingerprint",
            "control_audit_fingerprint",
            "summary_content_hash",
            "report_content_hash",
            "receipt_fingerprint",
            "receipt_content_hash",
        ):
            object.__setattr__(self, name, _require_digest(getattr(self, name), name))
        for name in ("schema_version", "source_commit", "created_utc"):
            object.__setattr__(
                self, name, _require_non_empty(getattr(self, name), name)
            )
        if type(self.source_tree_clean) is not bool:
            raise ValueError("source_tree_clean must be a bool")

        expected = paired_finalization_fingerprint(self.claims())
        if self.finalization_fingerprint != expected:
            raise ValueError("finalization_fingerprint does not cover these claims")
        if (
            self.finalization_id
            != f"pairedfinal_{expected[:PAIRED_EVALUATION_ID_LENGTH]}"
        ):
            raise ValueError("finalization_id must be derived from the fingerprint")

    def claims(self) -> Mapping[str, object]:
        return {
            "schema_version": self.schema_version,
            "paired_evaluation_id": self.paired_evaluation_id,
            "paired_evaluation_fingerprint": self.paired_evaluation_fingerprint,
            "definition_fingerprint": self.definition_fingerprint,
            "control_audit_fingerprint": self.control_audit_fingerprint,
            "summary_content_hash": self.summary_content_hash,
            "report_content_hash": self.report_content_hash,
            "receipt_fingerprint": self.receipt_fingerprint,
            "receipt_content_hash": self.receipt_content_hash,
            "source_commit": self.source_commit,
            "source_tree_clean": self.source_tree_clean,
        }


def paired_finalization_fingerprint(claims: Mapping[str, object]) -> str:
    return stable_hash(
        {"schema": "paired_finalization_fingerprint_v1", "claims": dict(claims)},
        length=64,
    )
