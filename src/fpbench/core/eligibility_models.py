"""Which fingers survived both SELF comparisons, under one exact threshold.

The supervisor's protocol reports the PLAIN–ROLL stage twice: over all 500 pairs
per release, and over only those whose finger passed both SELF tests. This
module holds the record that decides the second question.

Three things it is easy to get wrong, and which the models make impossible.

**Eligibility is release-specific.** The same anatomical finger of the same
subject appears in SD300A, SD300B and SD300C, and each is scanned separately at
a different resolution. Finger 3 of subject 12 may pass both SELF tests at
2000 ppi and fail one at 500. Those are three units, not one, and a unit id that
did not include the release would silently merge them (docs/adr/0023).

**Eligibility is profile-specific.** It is derived from *decisions*, and a
decision is only meaningful under a threshold. There is no such thing as a
finger that is eligible in general — every eligibility set names the decision
set, decision profile and result set it came from, and changing the threshold
produces a different eligibility set with a different id.

**"We could not tell" is not "it failed."** A SELF comparison that crashed makes
a unit ``UNDETERMINED``, not ``INELIGIBLE``. Only an actual ``NON_MATCH``
disqualifies a finger. Collapsing the two would be the same mistake as counting
a failure as a non-match, one level up (docs/adr/0006).

The unit id is opaque on purpose: it is a digest, so a subject cannot be read
back out of an artefact that gets shared.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping

from fpbench.core.enums import (
    DecisionValue,
    SelfEligibilityReason,
    SelfEligibilityStatus,
)
from fpbench.core.identifiers import validate_id
from fpbench.core.serialization import stable_hash

__all__ = [
    "SelfEligibilityStatus",
    "SelfEligibilityReason",
    "SelfEligibilityUnit",
    "SelfEligibilityDecisionRecord",
    "SelfEligibilityManifest",
    "eligibility_unit_id",
    "eligibility_record_hash",
    "ordered_units_hash",
    "eligibility_set_fingerprint",
    "eligibility_set_id",
    "ELIGIBILITY_SCHEMA_VERSION",
    "ELIGIBILITY_POLICY_ID",
    "ELIGIBILITY_POLICY_VERSION",
    "ELIGIBILITY_UNIT_ID_LENGTH",
    "ELIGIBILITY_SET_ID_LENGTH",
]

ELIGIBILITY_SCHEMA_VERSION = "1"

#: The rule this project's protocol fixes: a finger is usable for conditional
#: reporting only when *both* of its SELF comparisons matched. Named and
#: versioned, so that a future protocol with a different rule produces a
#: different eligibility fingerprint rather than quietly different answers.
ELIGIBILITY_POLICY_ID = "plain_and_roll_self_must_match"
ELIGIBILITY_POLICY_VERSION = "1"

#: Sixteen characters here rather than twelve: there are 1,500 units per
#: derivation and they are joined against, so the extra collision margin is
#: cheap and the id is never typed by a person.
ELIGIBILITY_UNIT_ID_LENGTH = 16
ELIGIBILITY_SET_ID_LENGTH = 12

_HEX = frozenset("0123456789abcdef")


def _require_digest(value: str, field_name: str) -> str:
    digest = str(value).strip().lower()
    if len(digest) != 64 or not set(digest) <= _HEX:
        raise ValueError(f"{field_name} must be a 64-character hexadecimal digest")
    return digest


def eligibility_unit_id(
    *,
    protocol_id: str,
    cohort_id: str,
    release: str,
    subject_id: str,
    canonical_finger: int,
) -> str:
    """``selfunit_<16 chars>``, derived and opaque.

    The subject reaches the digest but never the id's text. Eligibility tables
    are the most join-friendly artefact this stage produces, which makes them
    the most likely to be copied somewhere less careful.
    """
    digest = stable_hash(
        {
            "schema": "self_eligibility_unit_v1",
            "protocol_id": protocol_id,
            "cohort_id": str(cohort_id),
            "release": release,
            "subject_id": str(subject_id),
            "canonical_finger": int(canonical_finger),
        },
        length=64,
    )
    return f"selfunit_{digest[:ELIGIBILITY_UNIT_ID_LENGTH]}"


@dataclass(frozen=True, slots=True)
class SelfEligibilityUnit:
    """One release/subject/finger, and the three comparisons that concern it.

    Built from the frozen pair manifest, never from filenames. The mated pair is
    carried because it is what the conditional view will include or exclude —
    the unit is the thing that decides, and the mated pair is what it decides
    about.
    """

    eligibility_unit_id: str

    release: str
    subject_id: str
    canonical_finger: int

    plain_self_pair_id: str
    plain_self_job_id: str

    roll_self_pair_id: str
    roll_self_job_id: str

    mated_pair_id: str
    mated_job_id: str

    def __post_init__(self) -> None:
        validate_id(self.eligibility_unit_id)
        for name in ("plain_self_job_id", "roll_self_job_id", "mated_job_id"):
            validate_id(str(getattr(self, name)))
        for name in (
            "release",
            "subject_id",
            "plain_self_pair_id",
            "roll_self_pair_id",
            "mated_pair_id",
        ):
            value = str(getattr(self, name)).strip()
            if not value:
                raise ValueError(f"{name} must not be empty")
            object.__setattr__(self, name, value)
        finger = int(self.canonical_finger)
        if not 1 <= finger <= 10:
            raise ValueError(
                f"canonical_finger must be an ANSI/NIST FRGP 1-10 position, got "
                f"{finger}"
            )
        object.__setattr__(self, "canonical_finger", finger)

        pair_ids = {
            self.plain_self_pair_id,
            self.roll_self_pair_id,
            self.mated_pair_id,
        }
        if len(pair_ids) != 3:
            raise ValueError(
                "a unit's PLAIN SELF, ROLL SELF and mated comparisons must be three "
                "distinct pairs"
            )


@dataclass(frozen=True, slots=True)
class SelfEligibilityDecisionRecord:
    """The eligibility verdict for one unit, under one decision set."""

    ordinal: int
    eligibility_unit_id: str

    release: str
    canonical_finger: int

    plain_self_pair_id: str
    plain_self_job_id: str
    plain_self_decision_hash: str
    plain_self_decision: DecisionValue | None

    roll_self_pair_id: str
    roll_self_job_id: str
    roll_self_decision_hash: str
    roll_self_decision: DecisionValue | None

    mated_pair_id: str
    mated_job_id: str

    status: SelfEligibilityStatus
    reasons: tuple[SelfEligibilityReason, ...]

    eligibility_record_hash: str

    def __post_init__(self) -> None:
        validate_id(self.eligibility_unit_id)
        for name in ("plain_self_job_id", "roll_self_job_id", "mated_job_id"):
            validate_id(str(getattr(self, name)))
        if int(self.ordinal) < 0:
            raise ValueError("ordinal is 0-based and must not be negative")
        object.__setattr__(self, "ordinal", int(self.ordinal))
        object.__setattr__(self, "canonical_finger", int(self.canonical_finger))
        for name in ("plain_self_decision_hash", "roll_self_decision_hash"):
            object.__setattr__(self, name, _require_digest(getattr(self, name), name))
        object.__setattr__(
            self, "eligibility_record_hash",
            _require_digest(self.eligibility_record_hash, "eligibility_record_hash"),
        )

        reasons = tuple(dict.fromkeys(self.reasons))
        if not reasons:
            raise ValueError("an eligibility verdict must say why it reached itself")
        object.__setattr__(self, "reasons", reasons)

        # The verdict has to follow from the two decisions it cites. This is the
        # one invariant that would let a bug quietly change which comparisons a
        # conditional report covers.
        expected = eligibility_status_of(
            plain=self.plain_self_decision, roll=self.roll_self_decision
        )
        if self.status is not expected[0]:
            raise ValueError(
                f"status {self.status.value!r} does not follow from PLAIN "
                f"{_render(self.plain_self_decision)} and ROLL "
                f"{_render(self.roll_self_decision)}; expected "
                f"{expected[0].value!r}"
            )
        if set(reasons) != set(expected[1]):
            raise ValueError(
                f"reasons {sorted(r.value for r in reasons)} do not follow from the "
                f"decisions; expected {sorted(r.value for r in expected[1])}"
            )

        recomputed = eligibility_record_hash(self)
        if self.eligibility_record_hash != recomputed:
            raise ValueError("eligibility_record_hash does not cover this record")

    @property
    def is_eligible(self) -> bool:
        return self.status is SelfEligibilityStatus.ELIGIBLE


def _render(decision: DecisionValue | None) -> str:
    return decision.value if decision is not None else "undecidable"


def eligibility_status_of(
    *,
    plain: DecisionValue | None,
    roll: DecisionValue | None,
) -> tuple[SelfEligibilityStatus, tuple[SelfEligibilityReason, ...]]:
    """The rule, in one place, as a pure function of two decisions.

    ``None`` means the SELF comparison could not be decided at all.

    The asymmetry between the two failure kinds is the substance of the rule.
    A ``NON_MATCH`` is *knowledge*: this finger did not match itself, so it can
    never satisfy "both SELF tests matched", whatever the other side did — even
    if the other side is unknown. An undecidable is *absence of knowledge*: the
    unit might have qualified, and recording it as ineligible would assert
    something nobody measured (docs/adr/0023).
    """
    reasons: list[SelfEligibilityReason] = []

    if plain is DecisionValue.NON_MATCH:
        reasons.append(SelfEligibilityReason.PLAIN_SELF_NON_MATCH)
    if roll is DecisionValue.NON_MATCH:
        reasons.append(SelfEligibilityReason.ROLL_SELF_NON_MATCH)
    if plain is None:
        reasons.append(SelfEligibilityReason.PLAIN_SELF_UNDECIDABLE)
    if roll is None:
        reasons.append(SelfEligibilityReason.ROLL_SELF_UNDECIDABLE)

    if reasons and any(
        reason
        in (
            SelfEligibilityReason.PLAIN_SELF_NON_MATCH,
            SelfEligibilityReason.ROLL_SELF_NON_MATCH,
        )
        for reason in reasons
    ):
        return SelfEligibilityStatus.INELIGIBLE, tuple(reasons)
    if reasons:
        return SelfEligibilityStatus.UNDETERMINED, tuple(reasons)
    return (
        SelfEligibilityStatus.ELIGIBLE,
        (SelfEligibilityReason.BOTH_SELF_MATCH,),
    )


def eligibility_record_hash(record: SelfEligibilityDecisionRecord) -> str:
    """A digest of one verdict, excluding its own hash field."""
    return stable_hash(
        {
            "schema": "self_eligibility_record_v1",
            "policy_id": ELIGIBILITY_POLICY_ID,
            "policy_version": ELIGIBILITY_POLICY_VERSION,
            "eligibility_unit_id": record.eligibility_unit_id,
            "release": record.release,
            "canonical_finger": record.canonical_finger,
            "plain_self_pair_id": record.plain_self_pair_id,
            "plain_self_job_id": record.plain_self_job_id,
            "plain_self_decision_hash": record.plain_self_decision_hash,
            "plain_self_decision": _plain(record.plain_self_decision),
            "roll_self_pair_id": record.roll_self_pair_id,
            "roll_self_job_id": record.roll_self_job_id,
            "roll_self_decision_hash": record.roll_self_decision_hash,
            "roll_self_decision": _plain(record.roll_self_decision),
            "mated_pair_id": record.mated_pair_id,
            "mated_job_id": record.mated_job_id,
            "status": record.status.value,
            "reasons": sorted(reason.value for reason in record.reasons),
        },
        length=64,
    )


def _plain(decision: DecisionValue | None) -> str | None:
    return decision.value if decision is not None else None


def ordered_units_hash(
    records: Iterable[SelfEligibilityDecisionRecord],
) -> str:
    return stable_hash(
        {
            "schema": "self_eligibility_ordered_v1",
            "units": [
                {
                    "ordinal": record.ordinal,
                    "eligibility_unit_id": record.eligibility_unit_id,
                    "eligibility_record_hash": record.eligibility_record_hash,
                }
                for record in records
            ],
        },
        length=64,
    )


def eligibility_set_fingerprint(
    *,
    result_set_fingerprint: str,
    decision_set_fingerprint: str,
    decision_profile_fingerprint: str,
    pair_manifest_hash: str,
    records: Iterable[SelfEligibilityDecisionRecord],
    policy_id: str = ELIGIBILITY_POLICY_ID,
    policy_version: str = ELIGIBILITY_POLICY_VERSION,
) -> str:
    """The digest behind ``eligibility_set_id``."""
    return stable_hash(
        {
            "schema": "self_eligibility_set_fingerprint_v1",
            "eligibility_schema_version": ELIGIBILITY_SCHEMA_VERSION,
            "policy_id": policy_id,
            "policy_version": policy_version,
            "result_set_fingerprint": result_set_fingerprint,
            "decision_set_fingerprint": decision_set_fingerprint,
            "decision_profile_fingerprint": decision_profile_fingerprint,
            "pair_manifest_hash": pair_manifest_hash,
            "records": [record.eligibility_record_hash for record in records],
        },
        length=64,
    )


def eligibility_set_id(fingerprint: str) -> str:
    digest = _require_digest(fingerprint, "eligibility_set_fingerprint")
    return f"eligibilityset_{digest[:ELIGIBILITY_SET_ID_LENGTH]}"


@dataclass(frozen=True, slots=True)
class SelfEligibilityManifest:
    """The identity of one immutable eligibility set.

    Carries ``total_units`` and no breakdown. How many fingers were eligible is
    a result; how many units exist is a property of the protocol. Only the
    second belongs here, and the first is derived when somebody actually
    evaluates something (docs/adr/0023).
    """

    eligibility_set_id: str
    eligibility_set_fingerprint: str

    run_id: str
    result_set_fingerprint: str
    decision_set_fingerprint: str
    decision_profile_fingerprint: str
    pair_manifest_hash: str

    policy_id: str
    policy_version: str

    total_units: int
    ordered_units_hash: str

    created_utc: str

    def __post_init__(self) -> None:
        validate_id(self.eligibility_set_id)
        validate_id(self.run_id)
        validate_id(self.policy_id)
        for name in (
            "eligibility_set_fingerprint",
            "result_set_fingerprint",
            "decision_set_fingerprint",
            "decision_profile_fingerprint",
            "pair_manifest_hash",
            "ordered_units_hash",
        ):
            object.__setattr__(self, name, _require_digest(getattr(self, name), name))

        total = int(self.total_units)
        if total <= 0:
            raise ValueError("an eligibility set with no units is not one")
        object.__setattr__(self, "total_units", total)

        version = str(self.policy_version).strip()
        if not version:
            raise ValueError("policy_version must not be empty")
        object.__setattr__(self, "policy_version", version)

        created = str(self.created_utc).strip()
        if not created:
            raise ValueError("created_utc must not be empty")
        object.__setattr__(self, "created_utc", created)

        expected = eligibility_set_id(self.eligibility_set_fingerprint)
        if self.eligibility_set_id != expected:
            raise ValueError(
                f"eligibility_set_id must be derived from the fingerprint: expected "
                f"{expected}, got {self.eligibility_set_id!r}"
            )
