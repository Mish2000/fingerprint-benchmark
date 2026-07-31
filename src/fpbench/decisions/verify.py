"""Re-deriving a stored decision set instead of believing it.

A decision set is not evidence of itself. Its manifest says the decisions hash
to a value; the manifest is a file, and a file can be edited. So verification
does the only thing that actually proves anything: it goes back to the raw
scores, applies the profile again, and checks that it gets the same answers —
byte for byte, hash for hash, in the same order (docs/adr/0022).

That makes verification about as expensive as derivation, which is the correct
trade. It runs when a derivation is finalised and whenever its status is asked
for, and the alternative — trusting a fingerprint that covers only the fields
somebody remembered to include — is how a tampered artefact passes review.
"""

from __future__ import annotations

from typing import Mapping

from fpbench.core.decision_models import (
    DecisionApplicationStatus,
    DecisionProfile,
    DecisionRecord,
    DecisionSetManifest,
    decision_record_hash,
    decision_set_fingerprint,
    decision_set_id,
    ordered_decisions_hash,
)
from fpbench.core.enums import ExecutionStatus
from fpbench.core.errors import DecisionSetIntegrityError
from fpbench.core.execution_plan_models import ExecutionPlan
from fpbench.core.result_models import RunDefinition, raw_result_hash
from fpbench.core.result_set_models import ResultSetEntry, ResultSetManifest
from fpbench.decisions.apply import decide_score
from fpbench.decisions.profiles import require_profile_applies_to_run
from fpbench.core.errors import DecisionProfileApplicabilityError
from fpbench.storage.result_store import ResultStore

__all__ = ["verify_decision_set"]


def verify_decision_set(
    *,
    profile: DecisionProfile,
    manifest: DecisionSetManifest,
    records: tuple[DecisionRecord, ...],
    run: RunDefinition,
    plan: ExecutionPlan,
    result_set: ResultSetManifest,
    result_set_entries: tuple[ResultSetEntry, ...],
    result_store: ResultStore,
) -> None:
    """Prove the stored decisions still follow from the stored scores.

    Raises:
        DecisionSetIntegrityError: anything disagrees with anything.
    """
    try:
        require_profile_applies_to_run(profile=profile, run=run)
    except DecisionProfileApplicabilityError as exc:
        raise DecisionSetIntegrityError(
            f"the stored profile no longer applies to this run: {exc}"
        ) from exc

    if profile.profile_fingerprint != manifest.decision_profile_fingerprint:
        raise DecisionSetIntegrityError(
            "the stored profile is not the profile the manifest names"
        )
    if profile.profile_id != manifest.decision_profile_id:
        raise DecisionSetIntegrityError(
            "the stored profile id is not the one the manifest names"
        )

    for label, actual, expected in (
        ("run id", manifest.run_id, run.run_id),
        ("run fingerprint", manifest.run_fingerprint, run.run_fingerprint),
        ("plan id", manifest.plan_id, plan.definition.plan_id),
        (
            "plan fingerprint",
            manifest.plan_fingerprint,
            plan.definition.plan_fingerprint,
        ),
        (
            "result-set fingerprint",
            manifest.result_set_fingerprint,
            result_set.result_set_fingerprint,
        ),
        ("result-set id", manifest.result_set_id, result_set.result_set_id),
    ):
        if actual != expected:
            raise DecisionSetIntegrityError(
                f"decision set {label} is {actual!r}, expected {expected!r}"
            )

    if len(records) != plan.total_jobs:
        raise DecisionSetIntegrityError(
            f"decision set holds {len(records)} decisions for {plan.total_jobs} "
            "planned jobs"
        )
    if manifest.total_decisions != len(records):
        raise DecisionSetIntegrityError(
            f"manifest declares {manifest.total_decisions} decisions but the set "
            f"carries {len(records)}"
        )
    if [record.ordinal for record in records] != list(range(len(records))):
        raise DecisionSetIntegrityError(
            "decision ordinals must be 0..n-1 with no gaps and no repeats"
        )

    job_ids = [record.job_id for record in records]
    if len(set(job_ids)) != len(job_ids):
        raise DecisionSetIntegrityError("a job may appear at most once in a set")
    hashes = [record.decision_record_hash for record in records]
    if len(set(hashes)) != len(hashes):
        raise DecisionSetIntegrityError(
            "two decisions hash identically; they cannot be distinguished"
        )

    entries_by_job: Mapping[str, ResultSetEntry] = {
        entry.job_id: entry for entry in result_set_entries
    }
    decided = 0
    undecidable = 0

    for planned, record in zip(plan.jobs, records, strict=True):
        job = planned.job
        if record.job_id != job.job_id:
            raise DecisionSetIntegrityError(
                f"decision at ordinal {record.ordinal} covers {record.job_id}, but "
                f"the plan places {job.job_id} there"
            )
        if record.job_fingerprint != job.job_fingerprint:
            raise DecisionSetIntegrityError(
                f"decision {record.job_id} cites a different unit of work than the "
                "plan"
            )
        if record.pair_id != str(job.pair_id):
            raise DecisionSetIntegrityError(
                f"decision {record.job_id} covers pair {record.pair_id}, planned "
                f"{job.pair_id}"
            )
        if record.decision_profile_fingerprint != profile.profile_fingerprint:
            raise DecisionSetIntegrityError(
                f"decision {record.job_id} was made under a different profile"
            )
        if record.decision_profile_id != profile.profile_id:
            raise DecisionSetIntegrityError(
                f"decision {record.job_id} names a different decision profile"
            )
        if record.result_set_id != result_set.result_set_id:
            raise DecisionSetIntegrityError(
                f"decision {record.job_id} names a different result set"
            )
        if record.result_set_fingerprint != result_set.result_set_fingerprint:
            raise DecisionSetIntegrityError(
                f"decision {record.job_id} cites a different result-set fingerprint"
            )

        entry = entries_by_job.get(record.job_id)
        if entry is None:
            raise DecisionSetIntegrityError(
                f"decision {record.job_id} cites a result the result set does not "
                "hold"
            )
        if record.source_result_hash != entry.result_hash:
            raise DecisionSetIntegrityError(
                f"decision {record.job_id} cites result hash "
                f"{record.source_result_hash[:12]}..., but the result set records "
                f"{entry.result_hash[:12]}..."
            )

        # The expensive half, and the only half that proves anything: go back to
        # the file and decide it again.
        stored = result_store.read_raw_result(run.run_id, record.job_id)
        actual_hash = raw_result_hash(stored)
        if actual_hash != record.source_result_hash:
            raise DecisionSetIntegrityError(
                f"the raw result for {record.job_id} has changed since it was "
                "decided"
            )

        if stored.status is ExecutionStatus.SUCCESS:
            expected_decision = decide_score(
                score=float(stored.raw_score), profile=profile
            )
            if record.application_status is not DecisionApplicationStatus.DECIDED:
                raise DecisionSetIntegrityError(
                    f"decision {record.job_id} is {record.application_status.value} "
                    "for a comparison that produced a score"
                )
            if record.decision is not expected_decision:
                raise DecisionSetIntegrityError(
                    f"decision {record.job_id} says "
                    f"{record.decision.value if record.decision else None!r}, but "
                    f"the stored score decides {expected_decision.value!r} under "
                    f"this profile"
                )
            decided += 1
        else:
            if record.application_status is not DecisionApplicationStatus.UNDECIDABLE:
                raise DecisionSetIntegrityError(
                    f"decision {record.job_id} claims to be decided, but the "
                    "comparison produced no score"
                )
            expected_code = stored.failure.code.value if stored.failure else None
            if record.source_failure_code != expected_code:
                raise DecisionSetIntegrityError(
                    f"decision {record.job_id} records failure "
                    f"{record.source_failure_code!r}, stored result says "
                    f"{expected_code!r}"
                )
            undecidable += 1

        if record.decision_record_hash != decision_record_hash(record):
            raise DecisionSetIntegrityError(
                f"decision {record.job_id} does not hash to its own content"
            )

    if (decided, undecidable) != (manifest.decided_count, manifest.undecidable_count):
        raise DecisionSetIntegrityError(
            f"manifest claims {manifest.decided_count} decided and "
            f"{manifest.undecidable_count} undecidable; the records hold {decided} "
            f"and {undecidable}"
        )
    if ordered_decisions_hash(records) != manifest.ordered_decisions_hash:
        raise DecisionSetIntegrityError(
            "the ordered decisions hash does not cover these records in this order"
        )

    recomputed = decision_set_fingerprint(
        run_fingerprint=manifest.run_fingerprint,
        plan_fingerprint=manifest.plan_fingerprint,
        result_set_fingerprint=manifest.result_set_fingerprint,
        decision_profile_fingerprint=manifest.decision_profile_fingerprint,
        derivation_software_fingerprint=manifest.derivation_software_fingerprint,
        derivation_source_revision=manifest.derivation_source_revision,
        records=records,
        decided_count=manifest.decided_count,
        undecidable_count=manifest.undecidable_count,
    )
    if recomputed != manifest.decision_set_fingerprint:
        raise DecisionSetIntegrityError(
            "the decision set does not fingerprint to its own identity"
        )
    if decision_set_id(recomputed) != manifest.decision_set_id:
        raise DecisionSetIntegrityError(
            "the decision set is stored under a foreign id"
        )
