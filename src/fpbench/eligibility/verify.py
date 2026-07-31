"""Re-deriving eligibility instead of believing a stored table.

Same discipline as the decision verifier one layer down: the mapping is rebuilt
from the frozen pair manifest, every verdict is recomputed from the two SELF
decisions it cites, and the set's fingerprint is recomputed from the result.
A stored eligibility table proves nothing about itself.
"""

from __future__ import annotations

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

__all__ = ["verify_eligibility_set"]


def verify_eligibility_set(
    *,
    manifest: SelfEligibilityManifest,
    records: Sequence[SelfEligibilityDecisionRecord],
    units: Sequence[SelfEligibilityUnit],
    decisions: Mapping[str, DecisionRecord],
    decision_set: DecisionSetManifest,
    pair_manifest_hash: str,
) -> None:
    """Prove the stored verdicts still follow from the stored decisions.

    Raises:
        EligibilityIntegrityError: anything disagrees with anything.
    """
    for label, actual, expected in (
        ("run id", manifest.run_id, decision_set.run_id),
        (
            "decision-set fingerprint",
            manifest.decision_set_fingerprint,
            decision_set.decision_set_fingerprint,
        ),
        (
            "decision-profile fingerprint",
            manifest.decision_profile_fingerprint,
            decision_set.decision_profile_fingerprint,
        ),
        (
            "result-set fingerprint",
            manifest.result_set_fingerprint,
            decision_set.result_set_fingerprint,
        ),
        ("pair-manifest hash", manifest.pair_manifest_hash, pair_manifest_hash),
        ("policy id", manifest.policy_id, ELIGIBILITY_POLICY_ID),
        ("policy version", manifest.policy_version, ELIGIBILITY_POLICY_VERSION),
    ):
        if actual != expected:
            raise EligibilityIntegrityError(
                f"eligibility set {label} is {actual!r}, expected {expected!r}"
            )

    if len(records) != len(units):
        raise EligibilityIntegrityError(
            f"the eligibility set holds {len(records)} verdicts for {len(units)} "
            "units derived from the pair manifest"
        )
    if manifest.total_units != len(records):
        raise EligibilityIntegrityError(
            f"manifest declares {manifest.total_units} units but the set carries "
            f"{len(records)}"
        )
    if [record.ordinal for record in records] != list(range(len(records))):
        raise EligibilityIntegrityError(
            "eligibility ordinals must be 0..n-1 with no gaps and no repeats"
        )

    unit_ids = [record.eligibility_unit_id for record in records]
    if len(set(unit_ids)) != len(unit_ids):
        raise EligibilityIntegrityError("a unit may appear at most once in a set")

    for unit, record in zip(units, records, strict=True):
        where = record.eligibility_unit_id
        if record.eligibility_unit_id != unit.eligibility_unit_id:
            raise EligibilityIntegrityError(
                f"verdict at ordinal {record.ordinal} covers {where}, but the "
                f"mapping places {unit.eligibility_unit_id} there"
            )
        for label, actual, expected in (
            ("release", record.release, unit.release),
            ("finger", record.canonical_finger, unit.canonical_finger),
            (
                "PLAIN SELF pair",
                record.plain_self_pair_id,
                unit.plain_self_pair_id,
            ),
            ("PLAIN SELF job", record.plain_self_job_id, unit.plain_self_job_id),
            ("ROLL SELF pair", record.roll_self_pair_id, unit.roll_self_pair_id),
            ("ROLL SELF job", record.roll_self_job_id, unit.roll_self_job_id),
            ("mated pair", record.mated_pair_id, unit.mated_pair_id),
            ("mated job", record.mated_job_id, unit.mated_job_id),
        ):
            if actual != expected:
                raise EligibilityIntegrityError(
                    f"unit {where} records {label} {actual!r}, but the mapping "
                    f"derives {expected!r}"
                )

        plain = _require_decision(decisions, unit.plain_self_job_id, where)
        roll = _require_decision(decisions, unit.roll_self_job_id, where)
        if record.plain_self_decision_hash != plain.decision_record_hash:
            raise EligibilityIntegrityError(
                f"unit {where} cites a PLAIN SELF decision that is not the stored one"
            )
        if record.roll_self_decision_hash != roll.decision_record_hash:
            raise EligibilityIntegrityError(
                f"unit {where} cites a ROLL SELF decision that is not the stored one"
            )

        plain_value = _value_of(plain)
        roll_value = _value_of(roll)
        if record.plain_self_decision is not plain_value:
            raise EligibilityIntegrityError(
                f"unit {where} records a different PLAIN SELF outcome than the "
                "decision set"
            )
        if record.roll_self_decision is not roll_value:
            raise EligibilityIntegrityError(
                f"unit {where} records a different ROLL SELF outcome than the "
                "decision set"
            )

        status, reasons = eligibility_status_of(plain=plain_value, roll=roll_value)
        if record.status is not status:
            raise EligibilityIntegrityError(
                f"unit {where} is {record.status.value}, but its decisions imply "
                f"{status.value}"
            )
        if set(record.reasons) != set(reasons):
            raise EligibilityIntegrityError(
                f"unit {where} gives reasons "
                f"{sorted(r.value for r in record.reasons)}, expected "
                f"{sorted(r.value for r in reasons)}"
            )
        if record.eligibility_record_hash != eligibility_record_hash(record):
            raise EligibilityIntegrityError(
                f"unit {where} does not hash to its own content"
            )

    if ordered_units_hash(records) != manifest.ordered_units_hash:
        raise EligibilityIntegrityError(
            "the ordered units hash does not cover these verdicts in this order"
        )
    recomputed = eligibility_set_fingerprint(
        result_set_fingerprint=manifest.result_set_fingerprint,
        decision_set_fingerprint=manifest.decision_set_fingerprint,
        decision_profile_fingerprint=manifest.decision_profile_fingerprint,
        pair_manifest_hash=manifest.pair_manifest_hash,
        records=records,
        policy_id=manifest.policy_id,
        policy_version=manifest.policy_version,
    )
    if recomputed != manifest.eligibility_set_fingerprint:
        raise EligibilityIntegrityError(
            "the eligibility set does not fingerprint to its own identity"
        )
    if eligibility_set_id(recomputed) != manifest.eligibility_set_id:
        raise EligibilityIntegrityError(
            "the eligibility set is stored under a foreign id"
        )


def _require_decision(
    decisions: Mapping[str, DecisionRecord], job_id: str, where: str
) -> DecisionRecord:
    record = decisions.get(job_id)
    if record is None:
        raise EligibilityIntegrityError(
            f"unit {where} cites job {job_id}, which the decision set does not hold"
        )
    return record


def _value_of(record: DecisionRecord) -> DecisionValue | None:
    if record.application_status is DecisionApplicationStatus.UNDECIDABLE:
        return None
    return record.decision
