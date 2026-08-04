"""Applying one threshold to one exact body of stored scores.

The interesting function in this module is four lines long, and the rest is
about making sure it is asked the right question.

:func:`decide_score` compares a score to a threshold. It does not round, it does
not use an epsilon, it does not normalise, and it does not know what a protocol
stage or a ground truth is. A score exactly equal to the threshold is a MATCH,
because ``>=`` is what the profile says and inventing a tolerance would move the
boundary by an amount nobody wrote down.

Everything else here exists so that the decisions it produces can be attributed.
The engine re-reads every raw result from disk and re-derives its hash before
deciding anything: the result set says what the evidence was, and a derivation
that trusted an index instead of the files would agree with the index even after
the files changed (docs/adr/0022).

Nothing in this module imports an adapter, and nothing in it knows that
SourceAFIS exists.
"""

from __future__ import annotations

import datetime as _dt
import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping

from fpbench.core.decision_models import (
    DecisionApplicationStatus,
    DecisionProfile,
    DecisionRecord,
    DecisionSetManifest,
    DecisionValue,
    ThresholdComparator,
    decision_record_hash,
    decision_set_fingerprint,
    decision_set_id,
    ordered_decisions_hash,
)
from fpbench.core.enums import ExecutionStatus, ScoreDirection
from fpbench.core.errors import DecisionDerivationError
from fpbench.core.execution_plan_models import ExecutionPlan
from fpbench.core.provenance_models import (
    SoftwareProvenance,
    software_provenance_fingerprint,
)
from fpbench.core.result_models import RunDefinition, raw_result_hash
from fpbench.core.result_set_models import ResultSetEntry, ResultSetManifest
from fpbench.decisions.profiles import require_profile_applies_to_run
from fpbench.storage.result_store import ResultStore

__all__ = ["DecisionSet", "decide_score", "apply_decision_profile"]


@dataclass(frozen=True, slots=True)
class DecisionSet:
    """A profile, its manifest and its records, as one in-memory unit."""

    profile: DecisionProfile
    manifest: DecisionSetManifest
    records: tuple[DecisionRecord, ...]

    @property
    def decision_set_id(self) -> str:
        return self.manifest.decision_set_id

    def by_job(self) -> Mapping[str, DecisionRecord]:
        return {record.job_id: record for record in self.records}


#: One predicate per comparator, and the whole of the decision layer's
#: arithmetic. Kept as a table rather than a chain of ``if``s so that adding a
#: comparator without deciding what it means at the boundary is impossible: the
#: table would simply have no entry for it.
_COMPARATORS: Mapping[ThresholdComparator, Any] = {
    ThresholdComparator.GREATER_THAN_OR_EQUAL: lambda value, threshold: value
    >= threshold,
    ThresholdComparator.GREATER_THAN: lambda value, threshold: value > threshold,
    ThresholdComparator.LESS_THAN_OR_EQUAL: lambda value, threshold: value <= threshold,
    ThresholdComparator.LESS_THAN: lambda value, threshold: value < threshold,
}


def decide_score(*, score: float, profile: DecisionProfile) -> DecisionValue:
    """Compare one score to one threshold. Nothing else.

    Args:
        score: The algorithm's own number, exactly as it was stored.

    Raises:
        DecisionDerivationError: the score is not finite. A NaN is not a low
            score — it is the absence of one, and it must never be silently
            classified.

    The comparison is done in :class:`~decimal.Decimal`. Converting the
    threshold to binary floating point instead would mean ``40`` is not exactly
    40, and a score that landed on the boundary would be decided by the parser.

    That mattered before four comparators existed and matters more now: under
    ``>=`` a boundary score is a MATCH and under ``>`` it is a NON_MATCH, so the
    two comparators disagree about exactly the scores where an epsilon or a
    binary rounding error would decide the answer. There is no epsilon here
    (docs/adr/0055, spec sections 17 and 18).
    """
    number = float(score)
    if not math.isfinite(number):
        raise DecisionDerivationError(
            f"score {score!r} is not finite and cannot be compared to a threshold"
        )

    value = Decimal(str(number))
    threshold = profile.threshold_value

    predicate = _COMPARATORS.get(profile.comparator)
    if predicate is None:  # pragma: no cover - unreachable while the table is total
        raise DecisionDerivationError(
            f"comparator {profile.comparator.value!r} has no decision rule"
        )
    return DecisionValue.MATCH if predicate(value, threshold) else DecisionValue.NON_MATCH


def apply_decision_profile(
    *,
    profile: DecisionProfile,
    run: RunDefinition,
    plan: ExecutionPlan,
    result_set: ResultSetManifest,
    result_set_entries: tuple[ResultSetEntry, ...],
    result_store: ResultStore,
    derivation_software: SoftwareProvenance,
    created_utc: str | None = None,
) -> DecisionSet:
    """Derive one decision per planned job, in plan order.

    The caller is responsible for having established that the source run is
    ``RESEARCH_READY``; this function establishes everything else, and refuses
    rather than repairs.

    Raises:
        DecisionDerivationError: the result set does not describe this run, a
            stored result no longer hashes to what the set records, or a planned
            job has no result to decide.
        DecisionProfileApplicabilityError: the profile does not describe this run.
    """
    require_profile_applies_to_run(profile=profile, run=run)

    if not derivation_software.is_research_grade:
        raise DecisionDerivationError(
            "a research derivation needs a committed, clean source revision; "
            f"got kind={derivation_software.provenance_kind!r}, "
            f"clean={derivation_software.source_tree_clean}"
        )
    if result_set.run_fingerprint != run.run_fingerprint:
        raise DecisionDerivationError(
            "the result set describes a different run than the one supplied"
        )
    if result_set.plan_fingerprint != plan.definition.plan_fingerprint:
        raise DecisionDerivationError(
            "the result set describes a different plan than the one supplied"
        )
    if len(result_set_entries) != plan.total_jobs:
        raise DecisionDerivationError(
            f"the result set holds {len(result_set_entries)} results for "
            f"{plan.total_jobs} planned jobs"
        )

    entries_by_job = {entry.job_id: entry for entry in result_set_entries}
    records: list[DecisionRecord] = []
    decided = 0
    undecidable = 0

    for planned in plan.jobs:
        job = planned.job
        entry = entries_by_job.get(job.job_id)
        if entry is None:
            raise DecisionDerivationError(
                f"planned job {job.job_id} is absent from the result set; there is "
                "nothing to decide"
            )
        if entry.ordinal != planned.ordinal:
            raise DecisionDerivationError(
                f"job {job.job_id} sits at ordinal {planned.ordinal} in the plan "
                f"and {entry.ordinal} in the result set"
            )

        record = result_store.read_raw_result(run.run_id, job.job_id)
        actual_hash = raw_result_hash(record)
        if actual_hash != entry.result_hash:
            raise DecisionDerivationError(
                f"result {job.job_id} hashes to {actual_hash[:12]}... but the "
                f"result set records {entry.result_hash[:12]}...; the scores have "
                "changed since they were indexed"
            )
        if record.job_fingerprint != job.job_fingerprint:
            raise DecisionDerivationError(
                f"result {job.job_id} was produced by a different unit of work "
                "than the plan asked for"
            )
        if record.score_direction is not profile.score_direction:
            raise DecisionDerivationError(
                f"result {job.job_id} declares score direction "
                f"{record.score_direction.value!r} but the profile assumes "
                f"{profile.score_direction.value!r}"
            )

        if record.status is ExecutionStatus.SUCCESS:
            decision = decide_score(score=float(record.raw_score), profile=profile)
            status = DecisionApplicationStatus.DECIDED
            failure_code = None
            decided += 1
        else:
            # No score, no decision. The failure code travels so that a later
            # stage can decide how to account for it — which is a question about
            # denominators, not about this comparison (docs/adr/0006).
            decision = None
            status = DecisionApplicationStatus.UNDECIDABLE
            failure_code = record.failure.code.value if record.failure else None
            undecidable += 1

        records.append(
            _build_record(
                ordinal=planned.ordinal,
                job_id=job.job_id,
                job_fingerprint=job.job_fingerprint,
                pair_id=str(job.pair_id),
                source_result_hash=actual_hash,
                result_set=result_set,
                profile=profile,
                status=status,
                decision=decision,
                execution_status=record.status,
                failure_code=failure_code,
            )
        )

    ordered = tuple(records)
    software_fingerprint = software_provenance_fingerprint(derivation_software)
    fingerprint = decision_set_fingerprint(
        run_fingerprint=run.run_fingerprint,
        plan_fingerprint=plan.definition.plan_fingerprint,
        result_set_fingerprint=result_set.result_set_fingerprint,
        decision_profile_fingerprint=profile.profile_fingerprint,
        derivation_software_fingerprint=software_fingerprint,
        derivation_source_revision=derivation_software.source_revision,
        records=ordered,
        decided_count=decided,
        undecidable_count=undecidable,
    )

    manifest = DecisionSetManifest(
        decision_set_id=decision_set_id(fingerprint),
        decision_set_fingerprint=fingerprint,
        run_id=run.run_id,
        run_fingerprint=run.run_fingerprint,
        plan_id=plan.plan_id,
        plan_fingerprint=plan.definition.plan_fingerprint,
        result_set_id=result_set.result_set_id,
        result_set_fingerprint=result_set.result_set_fingerprint,
        decision_profile_id=profile.profile_id,
        decision_profile_fingerprint=profile.profile_fingerprint,
        derivation_software_fingerprint=software_fingerprint,
        derivation_source_revision=derivation_software.source_revision,
        total_decisions=len(ordered),
        decided_count=decided,
        undecidable_count=undecidable,
        ordered_decisions_hash=ordered_decisions_hash(ordered),
        created_utc=created_utc or _dt.datetime.now(_dt.timezone.utc).isoformat(),
    )
    return DecisionSet(profile=profile, manifest=manifest, records=ordered)


def _build_record(
    *,
    ordinal: int,
    job_id: str,
    job_fingerprint: str,
    pair_id: str,
    source_result_hash: str,
    result_set: ResultSetManifest,
    profile: DecisionProfile,
    status: DecisionApplicationStatus,
    decision: DecisionValue | None,
    execution_status: ExecutionStatus,
    failure_code: str | None,
) -> DecisionRecord:
    """Build one record, deriving its own hash from its own content."""
    fields = {
        "ordinal": ordinal,
        "job_id": job_id,
        "job_fingerprint": job_fingerprint,
        "pair_id": pair_id,
        "source_result_hash": source_result_hash,
        "result_set_id": result_set.result_set_id,
        "result_set_fingerprint": result_set.result_set_fingerprint,
        "decision_profile_id": profile.profile_id,
        "decision_profile_fingerprint": profile.profile_fingerprint,
        "application_status": status,
        "decision": decision,
        "source_execution_status": execution_status,
        "source_failure_code": failure_code,
    }
    probe = _RecordProbe(**fields)
    return DecisionRecord(
        decision_record_hash=decision_record_hash(probe),  # type: ignore[arg-type]
        **fields,
    )


class _RecordProbe:
    """The attributes ``decision_record_hash`` reads, and nothing else."""

    __slots__ = (
        "ordinal",
        "job_id",
        "job_fingerprint",
        "pair_id",
        "source_result_hash",
        "result_set_id",
        "result_set_fingerprint",
        "decision_profile_id",
        "decision_profile_fingerprint",
        "application_status",
        "decision",
        "source_execution_status",
        "source_failure_code",
    )

    def __init__(self, **fields: object) -> None:
        for name in self.__slots__:
            setattr(self, name, fields.get(name))
