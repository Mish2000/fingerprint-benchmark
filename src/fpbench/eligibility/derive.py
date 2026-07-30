"""Turning two SELF decisions into one verdict about a finger.

The rule itself is one line of the supervisor's protocol: a finger counts for
the conditional PLAIN–ROLL report only if it matched itself in *both* the plain
and the rolled impression. Failing either is enough to disqualify it, and it
does not matter which.

The work in this module is everything around that line. Which two decisions?
(The ones the frozen pair manifest assigns to this release, subject and finger —
never the ones that happen to score well.) Under which threshold? (Exactly one,
named in the set's identity.) And what if a SELF comparison never produced a
score at all?

That last case is where a plausible shortcut would do real damage. Treating an
undecidable SELF as a failure would silently shrink the conditional denominator
using an assumption nobody stated. The unit becomes ``UNDETERMINED`` instead: it
is excluded from the conditional view, and it is excluded *for a different,
recorded reason* than a finger that genuinely failed (docs/adr/0023).
"""

from __future__ import annotations

import datetime as _dt
from typing import Mapping, Sequence

from fpbench.core.decision_models import DecisionRecord, DecisionSetManifest
from fpbench.core.eligibility_models import (
    ELIGIBILITY_POLICY_ID,
    ELIGIBILITY_POLICY_VERSION,
    SelfEligibilityDecisionRecord,
    SelfEligibilityManifest,
    SelfEligibilityUnit,
    eligibility_record_hash,
    eligibility_set_fingerprint,
    eligibility_set_id,
    eligibility_status_of,
    ordered_units_hash,
)
from fpbench.core.enums import DecisionApplicationStatus, DecisionValue
from fpbench.core.errors import EligibilityIntegrityError
from fpbench.core.result_models import RunDefinition

__all__ = ["EligibilitySet", "derive_self_eligibility"]


class EligibilitySet:
    """A manifest and its records, as one in-memory unit."""

    __slots__ = ("manifest", "records")

    def __init__(
        self,
        manifest: SelfEligibilityManifest,
        records: tuple[SelfEligibilityDecisionRecord, ...],
    ) -> None:
        self.manifest = manifest
        self.records = records

    @property
    def eligibility_set_id(self) -> str:
        return self.manifest.eligibility_set_id

    def by_unit(self) -> Mapping[str, SelfEligibilityDecisionRecord]:
        return {record.eligibility_unit_id: record for record in self.records}

    def by_mated_pair(self) -> Mapping[str, SelfEligibilityDecisionRecord]:
        return {record.mated_pair_id: record for record in self.records}


def derive_self_eligibility(
    *,
    run: RunDefinition,
    units: Sequence[SelfEligibilityUnit],
    decisions: Mapping[str, DecisionRecord],
    decision_set: DecisionSetManifest,
    pair_manifest_hash: str,
    created_utc: str | None = None,
) -> EligibilitySet:
    """Derive one verdict per unit, from that unit's own two SELF decisions.

    Args:
        decisions: ``job_id -> DecisionRecord``, from one decision set.

    Every unit in ``units`` produces a record. None is skipped, including units
    whose SELF comparisons failed — an eligibility set that only described the
    fingers that worked would be a biased description of the protocol.

    Raises:
        EligibilityIntegrityError: a unit's SELF comparisons are not in the
            decision set, or the decision set describes a different run.
    """
    if decision_set.run_id != run.run_id:
        raise EligibilityIntegrityError(
            f"the decision set belongs to run {decision_set.run_id}, not "
            f"{run.run_id}"
        )
    if not units:
        raise EligibilityIntegrityError(
            "the protocol produced no eligibility units; there is nothing to decide"
        )

    records: list[SelfEligibilityDecisionRecord] = []
    for ordinal, unit in enumerate(units):
        plain = _decision_for(decisions, unit.plain_self_job_id, "PLAIN SELF", unit)
        roll = _decision_for(decisions, unit.roll_self_job_id, "ROLL SELF", unit)
        if unit.mated_job_id not in decisions:
            raise EligibilityIntegrityError(
                f"unit {unit.eligibility_unit_id} names mated job "
                f"{unit.mated_job_id}, which the decision set does not hold"
            )

        plain_value = _value_of(plain)
        roll_value = _value_of(roll)
        status, reasons = eligibility_status_of(plain=plain_value, roll=roll_value)

        fields = {
            "ordinal": ordinal,
            "eligibility_unit_id": unit.eligibility_unit_id,
            "release": unit.release,
            "canonical_finger": unit.canonical_finger,
            "plain_self_pair_id": unit.plain_self_pair_id,
            "plain_self_job_id": unit.plain_self_job_id,
            "plain_self_decision_hash": plain.decision_record_hash,
            "plain_self_decision": plain_value,
            "roll_self_pair_id": unit.roll_self_pair_id,
            "roll_self_job_id": unit.roll_self_job_id,
            "roll_self_decision_hash": roll.decision_record_hash,
            "roll_self_decision": roll_value,
            "mated_pair_id": unit.mated_pair_id,
            "mated_job_id": unit.mated_job_id,
            "status": status,
            "reasons": reasons,
        }
        probe = _RecordProbe(**fields)
        records.append(
            SelfEligibilityDecisionRecord(
                eligibility_record_hash=eligibility_record_hash(probe),  # type: ignore[arg-type]
                **fields,
            )
        )

    ordered = tuple(records)
    fingerprint = eligibility_set_fingerprint(
        result_set_fingerprint=decision_set.result_set_fingerprint,
        decision_set_fingerprint=decision_set.decision_set_fingerprint,
        decision_profile_fingerprint=decision_set.decision_profile_fingerprint,
        pair_manifest_hash=pair_manifest_hash,
        records=ordered,
    )
    manifest = SelfEligibilityManifest(
        eligibility_set_id=eligibility_set_id(fingerprint),
        eligibility_set_fingerprint=fingerprint,
        run_id=run.run_id,
        result_set_fingerprint=decision_set.result_set_fingerprint,
        decision_set_fingerprint=decision_set.decision_set_fingerprint,
        decision_profile_fingerprint=decision_set.decision_profile_fingerprint,
        pair_manifest_hash=pair_manifest_hash,
        policy_id=ELIGIBILITY_POLICY_ID,
        policy_version=ELIGIBILITY_POLICY_VERSION,
        total_units=len(ordered),
        ordered_units_hash=ordered_units_hash(ordered),
        created_utc=created_utc or _dt.datetime.now(_dt.timezone.utc).isoformat(),
    )
    return EligibilitySet(manifest, ordered)


def _decision_for(
    decisions: Mapping[str, DecisionRecord],
    job_id: str,
    label: str,
    unit: SelfEligibilityUnit,
) -> DecisionRecord:
    record = decisions.get(job_id)
    if record is None:
        raise EligibilityIntegrityError(
            f"unit {unit.eligibility_unit_id} names {label} job {job_id}, which the "
            "decision set does not hold; eligibility cannot be derived from a "
            "comparison nobody decided"
        )
    return record


def _value_of(record: DecisionRecord) -> DecisionValue | None:
    """``None`` when the comparison could not be decided at all.

    Deliberately not ``NON_MATCH``. The two are different facts and the rule
    treats them differently.
    """
    if record.application_status is DecisionApplicationStatus.UNDECIDABLE:
        return None
    return record.decision


class _RecordProbe:
    """The attributes ``eligibility_record_hash`` reads, and nothing else."""

    __slots__ = (
        "ordinal",
        "eligibility_unit_id",
        "release",
        "canonical_finger",
        "plain_self_pair_id",
        "plain_self_job_id",
        "plain_self_decision_hash",
        "plain_self_decision",
        "roll_self_pair_id",
        "roll_self_job_id",
        "roll_self_decision_hash",
        "roll_self_decision",
        "mated_pair_id",
        "mated_job_id",
        "status",
        "reasons",
    )

    def __init__(self, **fields: object) -> None:
        for name in self.__slots__:
            setattr(self, name, fields.get(name))
