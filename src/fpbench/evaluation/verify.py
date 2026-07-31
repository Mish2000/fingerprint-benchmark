"""Re-deriving a view's membership instead of trusting the stored flags.

The flag that matters is ``included``. Everything a conditional result says
rests on it, and it is one boolean per row — the easiest thing in the whole
chain to change without anyone noticing. So verification rebuilds it from the
eligibility verdict the row cites, and rebuilds the eligibility verdict's own
identity from the decision set beneath it.
"""

from __future__ import annotations

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
from fpbench.evaluation.views import (
    POLICY_FOR_VIEW,
    POLICY_VERSION,
    expected_policy_metadata,
)

__all__ = ["verify_evaluation_view", "STAGE_FOR_VIEW"]

#: Which protocol stage each view is allowed to contain. A view that drew from
#: the wrong stage would be a different experiment wearing the right name.
STAGE_FOR_VIEW: Mapping[str, ProtocolStage] = {
    MATED_UNCONDITIONAL_VIEW: ProtocolStage.PLAIN_ROLL_MATED,
    MATED_CONDITIONAL_VIEW: ProtocolStage.PLAIN_ROLL_MATED,
    NON_MATED_SANITY_VIEW: ProtocolStage.PLAIN_ROLL_NON_MATED,
}


def verify_evaluation_view(
    *,
    manifest: EvaluationViewManifest,
    entries: Sequence[EvaluationViewEntry],
    run: RunDefinition,
    plan: ExecutionPlan,
    pairs: Mapping[PairId, ComparisonPair],
    decisions: Mapping[str, DecisionRecord],
    decision_set: DecisionSetManifest,
    eligibility: SelfEligibilityManifest | None,
    eligibility_records: Sequence[SelfEligibilityDecisionRecord] = (),
    pair_manifest_hash: str,
    non_mated_finger_shift: int,
) -> None:
    """Prove a stored view still follows from the decisions and verdicts it cites.

    Raises:
        EvaluationViewIntegrityError: anything disagrees with anything.
    """
    expected_stage = STAGE_FOR_VIEW.get(manifest.view_kind)
    if expected_stage is None:
        raise EvaluationViewIntegrityError(
            f"view kind {manifest.view_kind!r} is not one this project defines"
        )

    conditional = manifest.view_kind == MATED_CONDITIONAL_VIEW
    if conditional and eligibility is None:
        raise EvaluationViewIntegrityError(
            "the conditional view must cite the eligibility set that filtered it"
        )
    if not conditional and manifest.eligibility_set_fingerprint is not None:
        raise EvaluationViewIntegrityError(
            f"view {manifest.view_id} is not conditional but cites an eligibility "
            "set; an unconditional view that quietly filtered would be the exact "
            "confusion this stage exists to prevent"
        )

    for label, actual, expected in (
        ("run fingerprint", manifest.run_fingerprint, run.run_fingerprint),
        (
            "decision-set fingerprint",
            manifest.decision_set_fingerprint,
            decision_set.decision_set_fingerprint,
        ),
        (
            "result-set fingerprint",
            manifest.result_set_fingerprint,
            decision_set.result_set_fingerprint,
        ),
        ("pair-manifest hash", manifest.pair_manifest_hash, pair_manifest_hash),
        ("policy version", manifest.policy_version, POLICY_VERSION),
        ("policy id", manifest.policy_id, POLICY_FOR_VIEW[manifest.view_kind]),
    ):
        if actual != expected:
            raise EvaluationViewIntegrityError(
                f"view {label} is {actual!r}, expected {expected!r}"
            )

    expected_metadata = expected_policy_metadata(
        manifest.view_kind, finger_shift=non_mated_finger_shift
    )
    if dict(manifest.policy_metadata) != dict(expected_metadata):
        raise EvaluationViewIntegrityError(
            f"view policy metadata is {dict(manifest.policy_metadata)!r}, expected "
            f"{dict(expected_metadata)!r}"
        )
    if conditional and eligibility is not None:
        if manifest.eligibility_set_fingerprint != eligibility.eligibility_set_fingerprint:
            raise EvaluationViewIntegrityError(
                "the conditional view cites a different eligibility set than the "
                "one supplied"
            )

    if manifest.total_rows != len(entries):
        raise EvaluationViewIntegrityError(
            f"manifest declares {manifest.total_rows} rows but the view carries "
            f"{len(entries)}"
        )
    if [entry.ordinal for entry in entries] != list(range(len(entries))):
        raise EvaluationViewIntegrityError(
            "view ordinals must be 0..n-1 with no gaps and no repeats"
        )
    pair_ids = [entry.pair_id for entry in entries]
    if len(set(pair_ids)) != len(pair_ids):
        raise EvaluationViewIntegrityError("a pair may appear at most once in a view")
    job_ids = [entry.job_id for entry in entries]
    if len(set(job_ids)) != len(job_ids):
        raise EvaluationViewIntegrityError("a job may appear at most once in a view")

    expected_rows: list[tuple[str, str]] = []
    for planned in plan.jobs:
        pair = pairs.get(planned.job.pair_id)
        if pair is None:
            raise EvaluationViewIntegrityError(
                f"planned pair {planned.job.pair_id} is not in the pair manifest"
            )
        if pair.protocol_stage is expected_stage:
            expected_rows.append((str(pair.pair_id), planned.job.job_id))
    actual_rows = [(entry.pair_id, entry.job_id) for entry in entries]
    if actual_rows != expected_rows:
        raise EvaluationViewIntegrityError(
            "view rows are not exactly the jobs for its protocol stage in plan order"
        )

    by_mated_pair = {
        record.mated_pair_id: record for record in eligibility_records
    }

    for entry in entries:
        pair = pairs.get(PairId(entry.pair_id))
        if pair is None:
            raise EvaluationViewIntegrityError(
                f"view row {entry.pair_id} is not in the pair manifest"
            )
        if pair.protocol_stage is not expected_stage:
            raise EvaluationViewIntegrityError(
                f"view {manifest.view_id} contains a {pair.protocol_stage.value} "
                f"comparison; it is defined over {expected_stage.value}"
            )

        decision = decisions.get(entry.job_id)
        if decision is None:
            raise EvaluationViewIntegrityError(
                f"view row {entry.job_id} cites a decision the set does not hold"
            )
        if entry.decision_record_hash != decision.decision_record_hash:
            raise EvaluationViewIntegrityError(
                f"view row {entry.job_id} cites a decision that is not the stored one"
            )
        if entry.pair_id != decision.pair_id:
            raise EvaluationViewIntegrityError(
                f"view row {entry.job_id} names pair {entry.pair_id}, but its "
                f"decision names {decision.pair_id}"
            )
        if entry.source_result_hash != decision.source_result_hash:
            raise EvaluationViewIntegrityError(
                f"view row {entry.job_id} cites a different raw result than its "
                "decision does"
            )
        if entry.decision_status is not decision.application_status:
            raise EvaluationViewIntegrityError(
                f"view row {entry.job_id} records application status "
                f"{entry.decision_status.value}, decision says "
                f"{decision.application_status.value}"
            )
        if entry.decision is not decision.decision:
            raise EvaluationViewIntegrityError(
                f"view row {entry.job_id} records a different decision than the "
                "decision set"
            )

        expected_included, expected_reason, expected_unit = _expected_membership(
            conditional=conditional,
            pair_id=entry.pair_id,
            by_mated_pair=by_mated_pair,
            view_id=manifest.view_id,
        )
        if entry.included is not expected_included:
            raise EvaluationViewIntegrityError(
                f"view row {entry.pair_id} is "
                f"{'included' if entry.included else 'excluded'}, but its "
                "eligibility implies otherwise"
            )
        if entry.exclusion_reason != expected_reason:
            raise EvaluationViewIntegrityError(
                f"view row {entry.pair_id} gives exclusion reason "
                f"{entry.exclusion_reason!r}, expected {expected_reason!r}"
            )
        if expected_unit is not None:
            if entry.eligibility_unit_id != expected_unit.eligibility_unit_id:
                raise EvaluationViewIntegrityError(
                    f"view row {entry.pair_id} cites a different eligibility unit"
                )
            if entry.eligibility_record_hash != expected_unit.eligibility_record_hash:
                raise EvaluationViewIntegrityError(
                    f"view row {entry.pair_id} cites an eligibility verdict that is "
                    "not the stored one"
                )
            if entry.eligibility_status is not expected_unit.status:
                raise EvaluationViewIntegrityError(
                    f"view row {entry.pair_id} records eligibility status "
                    f"{entry.eligibility_status}, stored verdict says "
                    f"{expected_unit.status.value}"
                )
        elif entry.eligibility_unit_id is not None:
            raise EvaluationViewIntegrityError(
                f"view row {entry.pair_id} cites an eligibility unit in a view that "
                "applies no SELF filter"
            )

        if entry.evaluation_entry_hash != evaluation_entry_hash(entry):
            raise EvaluationViewIntegrityError(
                f"view row {entry.pair_id} does not hash to its own content"
            )

    if ordered_entries_hash(entries) != manifest.ordered_entries_hash:
        raise EvaluationViewIntegrityError(
            "the ordered entries hash does not cover these rows in this order"
        )
    recomputed = evaluation_view_fingerprint(
        view_kind=manifest.view_kind,
        policy_id=manifest.policy_id,
        policy_version=manifest.policy_version,
        run_fingerprint=manifest.run_fingerprint,
        result_set_fingerprint=manifest.result_set_fingerprint,
        decision_set_fingerprint=manifest.decision_set_fingerprint,
        eligibility_set_fingerprint=manifest.eligibility_set_fingerprint,
        pair_manifest_hash=manifest.pair_manifest_hash,
        policy_metadata=manifest.policy_metadata,
        entries=entries,
    )
    if recomputed != manifest.view_fingerprint:
        raise EvaluationViewIntegrityError(
            "the view does not fingerprint to its own identity"
        )
    if evaluation_view_id(manifest.view_kind, recomputed) != manifest.view_id:
        raise EvaluationViewIntegrityError("the view is stored under a foreign id")

    if manifest.view_kind == NON_MATED_SANITY_VIEW:
        _require_sanity_labelling(manifest)


def _expected_membership(
    *,
    conditional: bool,
    pair_id: str,
    by_mated_pair: Mapping[str, SelfEligibilityDecisionRecord],
    view_id: str,
) -> tuple[bool, str | None, SelfEligibilityDecisionRecord | None]:
    if not conditional:
        return True, None, None
    record = by_mated_pair.get(pair_id)
    if record is None:
        raise EvaluationViewIntegrityError(
            f"conditional view {view_id} holds pair {pair_id}, which has no "
            "eligibility verdict"
        )
    if record.status is SelfEligibilityStatus.ELIGIBLE:
        return True, None, record
    if record.status is SelfEligibilityStatus.INELIGIBLE:
        return False, ExclusionReason.SELF_INELIGIBLE, record
    return False, ExclusionReason.SELF_UNDETERMINED, record


def _require_sanity_labelling(manifest: EvaluationViewManifest) -> None:
    """The negative view must keep saying what it is not.

    The metadata is part of the fingerprint, so this cannot be edited away
    quietly — but it can be omitted at build time, and a view that stopped
    declaring ``primary_fmr_estimate: false`` would be one careless paragraph
    away from becoming a rate (docs/adr/0025).
    """
    required = {
        "negative_kind": "same_subject_different_finger",
        "pairing_strategy": "cyclic_finger_shift",
        "closed_set": "true",
        "primary_fmr_estimate": "false",
        "purpose": "negative_sanity_check",
    }
    for key, expected in required.items():
        actual = manifest.policy_metadata.get(key)
        if actual != expected:
            raise EvaluationViewIntegrityError(
                f"the non-mated sanity view must record {key}={expected!r}, got "
                f"{actual!r}; this set is a closed-set sanity check and may not be "
                "presented as a population estimate (docs/adr/0025)"
            )
    if "finger_shift" not in manifest.policy_metadata:
        raise EvaluationViewIntegrityError(
            "the non-mated sanity view must record the cyclic shift it was built "
            "with"
        )
