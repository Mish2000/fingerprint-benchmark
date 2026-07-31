"""Turning a stored score into a claim, without ever touching the score.

This is the layer [ADR 0003](../../docs/adr/0003-decision-outside-adapter.md)
promised from the beginning: raw results are written once and never
reinterpreted, and a threshold is applied *to* them afterwards, possibly several
times, by something the adapter has never heard of.

Three ideas carry the whole module.

**A threshold is a decimal, not a float.** ``0.1 + 0.2`` is not ``0.3``, and a
threshold stored as binary floating point is a threshold whose exact value
depends on how it was parsed. It is kept as a canonical decimal *string* —
``"40"``, never ``40.0`` and never ``4e1`` — so that the same profile written by
two people produces the same fingerprint, and so that "is this score exactly at
the threshold?" has one answer.

**A failure is not a non-match.** A comparison that never produced a score
cannot be thresholded, and the vocabulary refuses to let it be: its application
status is ``UNDECIDABLE`` and its decision is ``None``. There is no
``NO_MATCH_DUE_TO_FAILURE``. Counting a crashed JVM as a non-match would corrupt
every denominator a later stage computes (docs/adr/0006).

**A decision set names one exact body of evidence.** Not "the latest scores for
this run" — one result-set fingerprint, one profile fingerprint, one derivation
source revision. Change any of the three and you have a different decision set,
with a different id, in a different directory (docs/adr/0022).

The dataclasses live in ``core`` because the storage layer persists them and
``storage`` may only import ``core``. The rules for deriving them live in
:mod:`fpbench.decisions`, which re-exports the containers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Iterable, Mapping

from fpbench.core.enums import (
    DecisionApplicationStatus,
    DecisionValue,
    ExecutionStatus,
    ScoreDirection,
    ThresholdComparator,
    ThresholdOrigin,
)
from fpbench.core.errors import DecisionProfileError
from fpbench.core.identifiers import validate_id
from fpbench.core.serialization import freeze_str_mapping, require_exact_int, stable_hash

__all__ = [
    "DecisionApplicationStatus",
    "DecisionValue",
    "ThresholdComparator",
    "ThresholdOrigin",
    "DecisionProfile",
    "DecisionRecord",
    "DecisionSetManifest",
    "canonical_threshold",
    "threshold_decimal",
    "decision_profile_fingerprint",
    "decision_record_hash",
    "ordered_decisions_hash",
    "decision_set_fingerprint",
    "decision_set_id",
    "DECISION_PROFILE_SCHEMA_VERSION",
    "DECISION_SET_SCHEMA_VERSION",
    "DECISION_SET_ID_LENGTH",
    "COMPARATOR_FOR_DIRECTION",
]

#: Bumped when the meaning of a decision profile changes. Inside the
#: fingerprint, so a bump separates new profiles from old.
DECISION_PROFILE_SCHEMA_VERSION = "1"

#: Bumped when the meaning of a decision set changes.
DECISION_SET_SCHEMA_VERSION = "1"

DECISION_SET_ID_LENGTH = 12

#: The only comparator that is coherent with each score direction. A matcher
#: whose scores rise with similarity matches *at or above* its threshold; one
#: whose scores are distances matches at or below. Allowing the other pairing
#: would invert every decision in a run while looking like a configuration
#: choice.
COMPARATOR_FOR_DIRECTION: Mapping[ScoreDirection, ThresholdComparator] = {
    ScoreDirection.HIGHER_IS_BETTER: ThresholdComparator.GREATER_THAN_OR_EQUAL,
    ScoreDirection.LOWER_IS_BETTER: ThresholdComparator.LESS_THAN_OR_EQUAL,
}

_HEX = frozenset("0123456789abcdef")


# ---------------------------------------------------------------- threshold


def canonical_threshold(text: str | int | Decimal) -> str:
    """The one true spelling of a threshold.

    ``"40"``, ``"40.0"``, ``"+40"``, ``"4e1"`` and ``Decimal(40)`` all
    canonicalise to ``"40"``; ``"40.50"`` to ``"40.5"``. ``NaN``, infinities and
    anything unparseable are refused outright.

    There is exactly one canonicaliser in the project, and it is this one. Two
    of them would eventually disagree about a trailing zero, and a threshold
    that fingerprints differently depending on how it was written is not a
    threshold anyone can cite.

    Raises:
        DecisionProfileError: the value is empty, unparseable or not finite.
    """
    raw = str(text).strip()
    if not raw:
        raise DecisionProfileError("a threshold must not be empty")
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError, ArithmeticError):
        raise DecisionProfileError(
            f"threshold {raw!r} is not a decimal number"
        ) from None
    if not value.is_finite():
        raise DecisionProfileError(
            f"threshold {raw!r} must be finite; NaN and infinities cannot divide "
            "anything into matches and non-matches"
        )

    normalised = value.normalize()
    # ``normalize`` turns 40.0 into 4E+1. Fixed-point formatting turns it back,
    # which is the form a person would write and a fingerprint should cover.
    if normalised == 0:
        return "0"
    return format(normalised, "f")


def threshold_decimal(profile: "DecisionProfile") -> Decimal:
    """The profile's threshold as an exact decimal, for comparison."""
    return Decimal(profile.threshold)


# ------------------------------------------------------------------ profile


@dataclass(frozen=True, slots=True)
class DecisionProfile:
    """A threshold, its provenance, and what it may be applied to.

    Immutable and externally defined: the adapter that produced the scores has
    never seen this object, and nothing in it can reach back into a stored
    result (docs/adr/0021).
    """

    profile_id: str
    profile_fingerprint: str

    display_name: str
    profile_version: str

    algorithm_id: str
    implementation_version: str
    algorithm_fingerprint: str

    score_direction: ScoreDirection
    comparator: ThresholdComparator
    threshold: str

    origin: ThresholdOrigin
    source_kind: str
    source_reference: str
    source_version: str

    allowed_execution_profiles: tuple[str, ...]

    calibration_performed: bool
    calibration_manifest_fingerprint: str | None = None

    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        validate_id(self.profile_id)
        validate_id(self.algorithm_id)
        for name in (
            "display_name",
            "profile_version",
            "implementation_version",
            "source_kind",
            "source_reference",
            "source_version",
        ):
            value = str(getattr(self, name)).strip()
            if not value:
                raise DecisionProfileError(f"{name} must not be empty")
            object.__setattr__(self, name, value)

        object.__setattr__(
            self,
            "algorithm_fingerprint",
            _require_digest(self.algorithm_fingerprint, "algorithm_fingerprint"),
        )
        object.__setattr__(
            self,
            "profile_fingerprint",
            _require_digest(self.profile_fingerprint, "profile_fingerprint"),
        )
        object.__setattr__(self, "threshold", canonical_threshold(self.threshold))

        profiles = tuple(str(item).strip() for item in self.allowed_execution_profiles)
        if not profiles:
            raise DecisionProfileError(
                "a decision profile must name at least one execution profile it "
                "applies to; a threshold that spans every way of preparing an "
                "image is a threshold nobody can attribute"
            )
        for profile_id in profiles:
            validate_id(profile_id)
        object.__setattr__(self, "allowed_execution_profiles", profiles)

        expected = COMPARATOR_FOR_DIRECTION[self.score_direction]
        if self.comparator is not expected:
            raise DecisionProfileError(
                f"score direction {self.score_direction.value!r} requires "
                f"comparator {expected.value!r}, not {self.comparator.value!r}; "
                "the other pairing inverts every decision"
            )

        object.__setattr__(
            self, "calibration_performed", bool(self.calibration_performed)
        )
        manifest = self.calibration_manifest_fingerprint
        if manifest is not None:
            manifest = _require_digest(manifest, "calibration_manifest_fingerprint")
            object.__setattr__(self, "calibration_manifest_fingerprint", manifest)

        if self.calibration_performed and manifest is None:
            raise DecisionProfileError(
                "a profile that claims calibration must name the calibration "
                "manifest that produced it"
            )
        if not self.calibration_performed and manifest is not None:
            raise DecisionProfileError(
                "a profile that performed no calibration must not cite a "
                "calibration manifest"
            )
        if self.origin is ThresholdOrigin.CALIBRATED_DEVELOPMENT and manifest is None:
            raise DecisionProfileError(
                "a calibrated threshold needs the development-cohort calibration "
                "manifest it was derived from; without one there is no evidence "
                "the calibration happened, or that it avoided the test cohort"
            )
        if self.origin is not ThresholdOrigin.CALIBRATED_DEVELOPMENT and manifest:
            raise DecisionProfileError(
                f"origin {self.origin.value!r} cannot carry a calibration manifest"
            )

        object.__setattr__(self, "metadata", freeze_str_mapping(self.metadata))

        recomputed = decision_profile_fingerprint(self)
        if self.profile_fingerprint != recomputed:
            raise DecisionProfileError(
                "profile_fingerprint does not cover the profile it is attached to"
            )

    @property
    def threshold_value(self) -> Decimal:
        return Decimal(self.threshold)

    def applies_to_execution_profile(self, profile_id: str) -> bool:
        return profile_id in self.allowed_execution_profiles


def decision_profile_fingerprint(profile: DecisionProfile) -> str:
    """A 64-character digest of everything that could change a decision.

    ``display_name`` is excluded: renaming a profile in a report must not
    invalidate decisions derived under it. So are timestamps and file paths —
    the same profile, written in two repositories, is the same profile.
    """
    return stable_hash(
        {
            "schema": "decision_profile_fingerprint_v1",
            "decision_profile_schema_version": DECISION_PROFILE_SCHEMA_VERSION,
            "profile_id": profile.profile_id,
            "profile_version": profile.profile_version,
            "algorithm_id": profile.algorithm_id,
            "implementation_version": profile.implementation_version,
            "algorithm_fingerprint": profile.algorithm_fingerprint,
            "score_direction": profile.score_direction.value,
            "comparator": profile.comparator.value,
            "threshold": profile.threshold,
            "origin": profile.origin.value,
            "source_kind": profile.source_kind,
            "source_reference": profile.source_reference,
            "source_version": profile.source_version,
            "allowed_execution_profiles": list(profile.allowed_execution_profiles),
            "calibration_performed": profile.calibration_performed,
            "calibration_manifest_fingerprint": (
                profile.calibration_manifest_fingerprint
            ),
            "metadata": dict(profile.metadata),
        },
        length=64,
    )


# ------------------------------------------------------------------- record


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    """One stored result, and what one threshold says about it.

    Note what is *not* here: the raw score. A decision cites the result it was
    derived from by hash and leaves the number where it was written. Copying it
    would create a second place a score lives, and the first thing a reader
    would have to stop trusting.

    Also absent: subject, finger, protocol stage and ground truth. A decision is
    a statement about a comparison, not about an experiment
    (docs/adr/0010).
    """

    ordinal: int

    job_id: str
    job_fingerprint: str
    pair_id: str

    source_result_hash: str
    result_set_id: str
    result_set_fingerprint: str

    decision_profile_id: str
    decision_profile_fingerprint: str

    application_status: DecisionApplicationStatus
    decision: DecisionValue | None

    source_execution_status: ExecutionStatus
    source_failure_code: str | None

    decision_record_hash: str

    def __post_init__(self) -> None:
        validate_id(self.job_id)
        validate_id(self.result_set_id)
        validate_id(self.decision_profile_id)
        ordinal = require_exact_int(self.ordinal, "ordinal")
        if ordinal < 0:
            raise ValueError("ordinal is 0-based and must not be negative")
        object.__setattr__(self, "ordinal", ordinal)

        for name in (
            "job_fingerprint",
            "source_result_hash",
            "result_set_fingerprint",
            "decision_profile_fingerprint",
            "decision_record_hash",
        ):
            object.__setattr__(self, name, _require_digest(getattr(self, name), name))

        pair_id = str(self.pair_id).strip()
        if not pair_id:
            raise ValueError("pair_id must not be empty")
        object.__setattr__(self, "pair_id", pair_id)

        # The two shapes, enforced rather than assumed. An adapter cannot
        # produce these; a buggy derivation could, and this is what stops it.
        if self.application_status is DecisionApplicationStatus.DECIDED:
            if self.source_execution_status is not ExecutionStatus.SUCCESS:
                raise ValueError(
                    "a decided result must come from a successful comparison; a "
                    "failure has no score to threshold"
                )
            if self.decision is None:
                raise ValueError("a decided result must carry a decision")
            if self.source_failure_code is not None:
                raise ValueError("a decided result must not carry a failure code")
        else:
            if self.source_execution_status is not ExecutionStatus.FAILURE:
                raise ValueError(
                    "a successful comparison produced a score and must be decided; "
                    "marking it undecidable would discard a usable measurement"
                )
            if self.decision is not None:
                raise ValueError(
                    "an undecidable result must not carry a decision; a failure is "
                    "not a non-match (docs/adr/0006)"
                )
            code = str(self.source_failure_code or "").strip()
            if not code:
                raise ValueError(
                    "an undecidable result must record why there was no score"
                )
            object.__setattr__(self, "source_failure_code", code)

        recomputed = decision_record_hash(self)
        if self.decision_record_hash != recomputed:
            raise ValueError("decision_record_hash does not cover this record")


def decision_record_hash(record: DecisionRecord) -> str:
    """A digest of one decision, excluding its own hash field."""
    return stable_hash(
        {
            "schema": "decision_record_v1",
            "ordinal": record.ordinal,
            "job_id": record.job_id,
            "job_fingerprint": record.job_fingerprint,
            "pair_id": record.pair_id,
            "source_result_hash": record.source_result_hash,
            "result_set_id": record.result_set_id,
            "result_set_fingerprint": record.result_set_fingerprint,
            "decision_profile_id": record.decision_profile_id,
            "decision_profile_fingerprint": record.decision_profile_fingerprint,
            "application_status": record.application_status.value,
            "decision": record.decision.value if record.decision else None,
            "source_execution_status": record.source_execution_status.value,
            "source_failure_code": record.source_failure_code,
        },
        length=64,
    )


# ----------------------------------------------------------------- manifest


def ordered_decisions_hash(records: Iterable[DecisionRecord]) -> str:
    """A digest of the decisions *in plan order*."""
    return stable_hash(
        {
            "schema": "decision_set_ordered_v1",
            "records": [
                {
                    "ordinal": record.ordinal,
                    "job_id": record.job_id,
                    "source_result_hash": record.source_result_hash,
                    "decision_record_hash": record.decision_record_hash,
                }
                for record in records
            ],
        },
        length=64,
    )


def decision_set_fingerprint(
    *,
    run_fingerprint: str,
    plan_fingerprint: str,
    result_set_fingerprint: str,
    decision_profile_fingerprint: str,
    derivation_software_fingerprint: str,
    derivation_source_revision: str,
    records: Iterable[DecisionRecord],
    decided_count: int,
    undecidable_count: int,
) -> str:
    """The digest behind ``decision_set_id``.

    Includes the derivation software fingerprint, so a change to the code that
    applies thresholds produces a different decision set even over identical
    scores under an identical profile. That is not paranoia: failure mapping,
    ordering and hashing all live in that code (docs/adr/0017).

    The commit is covered separately as well as inside that fingerprint. A
    verifier reading only a stored manifest cannot recompute the software
    fingerprint — it has no ``SoftwareProvenance`` to hash — so without this the
    recorded revision would be the one field nothing checked.
    """
    ordered = list(records)
    return stable_hash(
        {
            "schema": "decision_set_fingerprint_v1",
            "decision_set_schema_version": DECISION_SET_SCHEMA_VERSION,
            "run_fingerprint": run_fingerprint,
            "plan_fingerprint": plan_fingerprint,
            "result_set_fingerprint": result_set_fingerprint,
            "decision_profile_fingerprint": decision_profile_fingerprint,
            "derivation_software_fingerprint": derivation_software_fingerprint,
            "derivation_source_revision": str(derivation_source_revision).lower(),
            "records": [
                {
                    "ordinal": record.ordinal,
                    "job_id": record.job_id,
                    "source_result_hash": record.source_result_hash,
                    "decision_record_hash": record.decision_record_hash,
                }
                for record in ordered
            ],
            "total_decisions": len(ordered),
            "decided_count": int(decided_count),
            "undecidable_count": int(undecidable_count),
        },
        length=64,
    )


def decision_set_id(fingerprint: str) -> str:
    """``decisionset_<12 chars of the decision-set fingerprint>``."""
    digest = _require_digest(fingerprint, "decision_set_fingerprint")
    return f"decisionset_{digest[:DECISION_SET_ID_LENGTH]}"


@dataclass(frozen=True, slots=True)
class DecisionSetManifest:
    """The identity of one immutable collection of decisions.

    Carries counts of *decidability*, never counts of outcome. How many
    comparisons matched is a performance statement; how many could be decided at
    all is a property of the derivation, and only the second belongs to an
    identity (docs/adr/0021).
    """

    decision_set_id: str
    decision_set_fingerprint: str

    run_id: str
    run_fingerprint: str

    plan_id: str
    plan_fingerprint: str

    result_set_id: str
    result_set_fingerprint: str

    decision_profile_id: str
    decision_profile_fingerprint: str

    derivation_software_fingerprint: str
    derivation_source_revision: str

    total_decisions: int
    decided_count: int
    undecidable_count: int

    ordered_decisions_hash: str
    created_utc: str

    def __post_init__(self) -> None:
        for name in (
            "decision_set_id",
            "run_id",
            "plan_id",
            "result_set_id",
            "decision_profile_id",
        ):
            validate_id(str(getattr(self, name)))
        for name in (
            "decision_set_fingerprint",
            "run_fingerprint",
            "plan_fingerprint",
            "result_set_fingerprint",
            "decision_profile_fingerprint",
            "derivation_software_fingerprint",
            "ordered_decisions_hash",
        ):
            object.__setattr__(self, name, _require_digest(getattr(self, name), name))

        revision = str(self.derivation_source_revision).strip().lower()
        if len(revision) != 40 or not set(revision) <= _HEX:
            raise ValueError(
                "derivation_source_revision must be a full 40-character commit SHA"
            )
        object.__setattr__(self, "derivation_source_revision", revision)

        for name in ("total_decisions", "decided_count", "undecidable_count"):
            number = require_exact_int(getattr(self, name), name)
            if number < 0:
                raise ValueError(f"{name} must not be negative")
            object.__setattr__(self, name, number)
        if self.total_decisions <= 0:
            raise ValueError("a decision set with no decisions is not a decision set")
        if self.decided_count + self.undecidable_count != self.total_decisions:
            raise ValueError(
                "every decision is either decided or undecidable: "
                f"{self.decided_count} + {self.undecidable_count} != "
                f"{self.total_decisions}"
            )

        created = str(self.created_utc).strip()
        if not created:
            raise ValueError("created_utc must not be empty")
        object.__setattr__(self, "created_utc", created)

        expected = decision_set_id(self.decision_set_fingerprint)
        if self.decision_set_id != expected:
            raise ValueError(
                f"decision_set_id must be derived from the fingerprint: expected "
                f"{expected}, got {self.decision_set_id!r}"
            )


def _require_digest(value: str, field_name: str) -> str:
    digest = str(value).strip().lower()
    if len(digest) != 64 or not set(digest) <= _HEX:
        raise ValueError(f"{field_name} must be a 64-character hexadecimal digest")
    return digest
