"""Deciding which comparisons an evaluation is about, before it computes one.

Three views, and the difference between the first two is the entire substance of
the supervisor's conditional-reporting requirement.

The **unconditional** mated view is every mated PLAIN–ROLL comparison, full
stop. A comparison that failed is still in it and still included: whether a
failure belongs in a denominator is a question about metrics, and answering it
here would bake one answer into the data.

The **conditional** mated view is the same 1,500 comparisons, with inclusion
switched off wherever the finger did not pass both SELF tests. Crucially the
excluded rows stay in the file, carrying the reason they were excluded. A view
that simply dropped them would be smaller, tidier, and impossible to audit —
"which pairs did you leave out, and why?" is the first question anyone should
ask of a conditional result (docs/adr/0024).

The **non-mated** view is the impostor sanity check, and most of what it does is
say what it is not. Its pairs are same-subject, different-finger, at a fixed
cyclic shift, over a closed set of 50 people. That is a good check that the
matcher does not fire on obviously different fingers. It is not a false-match
rate, it cannot be turned into one by dividing, and the view records that
refusal in its own policy metadata rather than in a footnote somebody drops
(docs/adr/0025).
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Mapping, Sequence

from fpbench.core.decision_models import DecisionRecord, DecisionSetManifest
from fpbench.core.eligibility_models import (
    SelfEligibilityDecisionRecord,
    SelfEligibilityManifest,
)
from fpbench.core.enums import ProtocolStage, SelfEligibilityStatus
from fpbench.core.errors import EvaluationViewIntegrityError
from fpbench.core.evaluation_view_models import (
    MATED_CONDITIONAL_VIEW,
    MATED_UNCONDITIONAL_VIEW,
    NON_MATED_SANITY_VIEW,
    EvaluationViewEntry,
    EvaluationViewManifest,
    ExclusionReason,
    evaluation_entry_hash,
    evaluation_view_fingerprint,
    evaluation_view_id,
    ordered_entries_hash,
)
from fpbench.core.execution_plan_models import ExecutionPlan
from fpbench.core.identifiers import PairId
from fpbench.core.models import ComparisonPair
from fpbench.core.result_models import RunDefinition

__all__ = [
    "EvaluationView",
    "build_mated_unconditional_view",
    "build_mated_conditional_view",
    "build_non_mated_sanity_view",
    "MATED_UNCONDITIONAL_POLICY",
    "MATED_CONDITIONAL_POLICY",
    "NON_MATED_SANITY_POLICY",
    "POLICY_VERSION",
    "POLICY_FOR_VIEW",
    "expected_policy_metadata",
]

MATED_UNCONDITIONAL_POLICY = "mated_unconditional"
MATED_CONDITIONAL_POLICY = "mated_both_self_match"
NON_MATED_SANITY_POLICY = "non_mated_same_subject_cyclic"

POLICY_VERSION = "1"

POLICY_FOR_VIEW: Mapping[str, str] = {
    MATED_UNCONDITIONAL_VIEW: MATED_UNCONDITIONAL_POLICY,
    MATED_CONDITIONAL_VIEW: MATED_CONDITIONAL_POLICY,
    NON_MATED_SANITY_VIEW: NON_MATED_SANITY_POLICY,
}


def expected_policy_metadata(
    view_kind: str, *, finger_shift: int
) -> Mapping[str, str]:
    """Return the complete, mandatory policy metadata for one view kind."""
    if view_kind == MATED_UNCONDITIONAL_VIEW:
        return {
            "inclusion": "every_mated_pair",
            "self_conditioned": "false",
            "failed_comparisons_retained": "true",
            "purpose": "unconditional_genuine_view",
        }
    if view_kind == MATED_CONDITIONAL_VIEW:
        return {
            "inclusion": "plain_self_match_and_roll_self_match",
            "self_conditioned": "true",
            "excluded_rows_retained": "true",
            "purpose": "conditional_genuine_view",
        }
    if view_kind == NON_MATED_SANITY_VIEW:
        return {
            "negative_kind": "same_subject_different_finger",
            "pairing_strategy": "cyclic_finger_shift",
            "finger_shift": str(int(finger_shift)),
            "closed_set": "true",
            "primary_fmr_estimate": "false",
            "purpose": "negative_sanity_check",
            "self_conditioned": "false",
        }
    raise EvaluationViewIntegrityError(
        f"view kind {view_kind!r} is not one this project defines"
    )


@dataclass(frozen=True, slots=True)
class EvaluationView:
    """A manifest and its entries, as one in-memory unit."""

    manifest: EvaluationViewManifest
    entries: tuple[EvaluationViewEntry, ...]

    @property
    def view_id(self) -> str:
        return self.manifest.view_id

    @property
    def included_count(self) -> int:
        """How many rows a metric would actually cover.

        Derived on demand and deliberately never stored in the manifest or a
        receipt: in the conditional view this number *is* a result
        (docs/adr/0024).
        """
        return sum(1 for entry in self.entries if entry.included)


def build_mated_unconditional_view(
    *,
    run: RunDefinition,
    plan: ExecutionPlan,
    pairs: Mapping[PairId, ComparisonPair],
    decisions: Mapping[str, DecisionRecord],
    decision_set: DecisionSetManifest,
    pair_manifest_hash: str,
    created_utc: str | None = None,
) -> EvaluationView:
    """Every mated PLAIN–ROLL comparison, all included."""
    entries = _entries_for_stage(
        plan=plan,
        pairs=pairs,
        decisions=decisions,
        stage=ProtocolStage.PLAIN_ROLL_MATED,
        eligibility_by_mated_pair=None,
        conditional=False,
    )
    return _assemble(
        view_kind=MATED_UNCONDITIONAL_VIEW,
        policy_id=MATED_UNCONDITIONAL_POLICY,
        run=run,
        decision_set=decision_set,
        eligibility=None,
        pair_manifest_hash=pair_manifest_hash,
        policy_metadata=expected_policy_metadata(
            MATED_UNCONDITIONAL_VIEW, finger_shift=0
        ),
        entries=entries,
        created_utc=created_utc,
    )


def build_mated_conditional_view(
    *,
    run: RunDefinition,
    plan: ExecutionPlan,
    pairs: Mapping[PairId, ComparisonPair],
    decisions: Mapping[str, DecisionRecord],
    decision_set: DecisionSetManifest,
    eligibility: SelfEligibilityManifest,
    eligibility_records: Sequence[SelfEligibilityDecisionRecord],
    pair_manifest_hash: str,
    created_utc: str | None = None,
) -> EvaluationView:
    """The same comparisons, included only where both SELF tests matched."""
    by_mated_pair = {
        record.mated_pair_id: record for record in eligibility_records
    }
    entries = _entries_for_stage(
        plan=plan,
        pairs=pairs,
        decisions=decisions,
        stage=ProtocolStage.PLAIN_ROLL_MATED,
        eligibility_by_mated_pair=by_mated_pair,
        conditional=True,
    )
    return _assemble(
        view_kind=MATED_CONDITIONAL_VIEW,
        policy_id=MATED_CONDITIONAL_POLICY,
        run=run,
        decision_set=decision_set,
        eligibility=eligibility,
        pair_manifest_hash=pair_manifest_hash,
        policy_metadata=expected_policy_metadata(
            MATED_CONDITIONAL_VIEW, finger_shift=0
        ),
        entries=entries,
        created_utc=created_utc,
    )


def build_non_mated_sanity_view(
    *,
    run: RunDefinition,
    plan: ExecutionPlan,
    pairs: Mapping[PairId, ComparisonPair],
    decisions: Mapping[str, DecisionRecord],
    decision_set: DecisionSetManifest,
    pair_manifest_hash: str,
    finger_shift: int,
    created_utc: str | None = None,
) -> EvaluationView:
    """The closed-set impostor sanity check, labelled as exactly that.

    No SELF conditioning is applied, and none will be in this stage. An impostor
    pair spans two different fingers, so "did its finger pass SELF?" has two
    answers and no agreed rule for combining them; inventing one here would be a
    metric policy nobody approved (spec section 41).
    """
    entries = _entries_for_stage(
        plan=plan,
        pairs=pairs,
        decisions=decisions,
        stage=ProtocolStage.PLAIN_ROLL_NON_MATED,
        eligibility_by_mated_pair=None,
        conditional=False,
    )
    return _assemble(
        view_kind=NON_MATED_SANITY_VIEW,
        policy_id=NON_MATED_SANITY_POLICY,
        run=run,
        decision_set=decision_set,
        eligibility=None,
        pair_manifest_hash=pair_manifest_hash,
        policy_metadata=expected_policy_metadata(
            NON_MATED_SANITY_VIEW, finger_shift=finger_shift
        ),
        entries=entries,
        created_utc=created_utc,
    )


# ----------------------------------------------------------------- internals


def _entries_for_stage(
    *,
    plan: ExecutionPlan,
    pairs: Mapping[PairId, ComparisonPair],
    decisions: Mapping[str, DecisionRecord],
    stage: ProtocolStage,
    eligibility_by_mated_pair: Mapping[str, SelfEligibilityDecisionRecord] | None,
    conditional: bool,
) -> tuple[EvaluationViewEntry, ...]:
    """Walk the plan in order and build one entry per comparison of ``stage``."""
    entries: list[EvaluationViewEntry] = []
    ordinal = 0

    for planned in plan.jobs:
        job = planned.job
        pair = pairs.get(job.pair_id)
        if pair is None:
            raise EvaluationViewIntegrityError(
                f"planned pair {job.pair_id} is not in the supplied pair manifest"
            )
        if pair.protocol_stage is not stage:
            continue

        decision = decisions.get(job.job_id)
        if decision is None:
            raise EvaluationViewIntegrityError(
                f"comparison {job.job_id} belongs to this view but the decision set "
                "does not hold it"
            )

        unit_id = None
        unit_hash = None
        unit_status = None
        included = True
        exclusion: str | None = None

        if conditional:
            record = (eligibility_by_mated_pair or {}).get(str(pair.pair_id))
            if record is None:
                # Every mated pair governs exactly one unit. A missing one means
                # the mapping and the manifest disagree, which is not something
                # to paper over by including or excluding the row.
                raise EvaluationViewIntegrityError(
                    f"mated pair {pair.pair_id} has no eligibility unit; the "
                    "conditional view cannot decide whether to include it"
                )
            unit_id = record.eligibility_unit_id
            unit_hash = record.eligibility_record_hash
            unit_status = record.status
            if record.status is SelfEligibilityStatus.ELIGIBLE:
                included = True
            elif record.status is SelfEligibilityStatus.INELIGIBLE:
                included = False
                exclusion = ExclusionReason.SELF_INELIGIBLE
            else:
                included = False
                exclusion = ExclusionReason.SELF_UNDETERMINED

        fields = {
            "ordinal": ordinal,
            "pair_id": str(pair.pair_id),
            "job_id": job.job_id,
            "source_result_hash": decision.source_result_hash,
            "decision_record_hash": decision.decision_record_hash,
            "decision_status": decision.application_status,
            "decision": decision.decision,
            "eligibility_unit_id": unit_id,
            "eligibility_record_hash": unit_hash,
            "eligibility_status": unit_status,
            "included": included,
            "exclusion_reason": exclusion,
        }
        probe = _EntryProbe(**fields)
        entries.append(
            EvaluationViewEntry(
                evaluation_entry_hash=evaluation_entry_hash(probe),  # type: ignore[arg-type]
                **fields,
            )
        )
        ordinal += 1

    if not entries:
        raise EvaluationViewIntegrityError(
            f"no comparison in this plan belongs to stage {stage.value!r}"
        )
    return tuple(entries)


def _assemble(
    *,
    view_kind: str,
    policy_id: str,
    run: RunDefinition,
    decision_set: DecisionSetManifest,
    eligibility: SelfEligibilityManifest | None,
    pair_manifest_hash: str,
    policy_metadata: Mapping[str, str],
    entries: tuple[EvaluationViewEntry, ...],
    created_utc: str | None,
) -> EvaluationView:
    eligibility_fingerprint = (
        eligibility.eligibility_set_fingerprint if eligibility else None
    )
    fingerprint = evaluation_view_fingerprint(
        view_kind=view_kind,
        policy_id=policy_id,
        policy_version=POLICY_VERSION,
        run_fingerprint=run.run_fingerprint,
        result_set_fingerprint=decision_set.result_set_fingerprint,
        decision_set_fingerprint=decision_set.decision_set_fingerprint,
        eligibility_set_fingerprint=eligibility_fingerprint,
        pair_manifest_hash=pair_manifest_hash,
        policy_metadata=policy_metadata,
        entries=entries,
    )
    manifest = EvaluationViewManifest(
        view_id=evaluation_view_id(view_kind, fingerprint),
        view_fingerprint=fingerprint,
        view_kind=view_kind,
        policy_id=policy_id,
        policy_version=POLICY_VERSION,
        run_fingerprint=run.run_fingerprint,
        result_set_fingerprint=decision_set.result_set_fingerprint,
        decision_set_fingerprint=decision_set.decision_set_fingerprint,
        eligibility_set_fingerprint=eligibility_fingerprint,
        pair_manifest_hash=pair_manifest_hash,
        total_rows=len(entries),
        ordered_entries_hash=ordered_entries_hash(entries),
        policy_metadata=policy_metadata,
        created_utc=created_utc or _dt.datetime.now(_dt.timezone.utc).isoformat(),
    )
    return EvaluationView(manifest=manifest, entries=entries)


class _EntryProbe:
    """The attributes ``evaluation_entry_hash`` reads, and nothing else."""

    __slots__ = (
        "ordinal",
        "pair_id",
        "job_id",
        "source_result_hash",
        "decision_record_hash",
        "decision_status",
        "decision",
        "eligibility_unit_id",
        "eligibility_record_hash",
        "eligibility_status",
        "included",
        "exclusion_reason",
    )

    def __init__(self, **fields: object) -> None:
        for name in self.__slots__:
            setattr(self, name, fields.get(name))
