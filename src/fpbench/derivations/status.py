"""How far along a derivation is, recomputed from the files every time.

Nothing here checks that a file exists and moves on. Every ``*_valid`` flag is
the result of re-deriving the thing it describes: the decisions are recomputed
from the raw scores, the eligibility verdicts from the decisions, the view
memberships from the verdicts, and each fingerprint from the artefact it claims
to cover.

That is expensive — reading a status costs roughly what producing it did — and
it is the only reading that means anything. A cheap status would answer "does
the directory look right?", and the whole point of the chain is that a directory
can look right and be wrong (docs/adr/0012, docs/adr/0022).
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Mapping, Sequence

from fpbench.core.decision_models import DecisionProfile, DecisionRecord
from fpbench.core.derivation_models import (
    DecisionDerivationState,
    DerivationDefinition,
    SourceFinalizationIdentity,
)
from fpbench.core.eligibility_models import SelfEligibilityUnit
from fpbench.core.enums import DecisionDerivationStatus, ResearchRunStatus
from fpbench.core.errors import FpbenchError
from fpbench.core.evaluation_view_models import (
    MATED_CONDITIONAL_VIEW,
    MATED_UNCONDITIONAL_VIEW,
    NON_MATED_SANITY_VIEW,
)
from fpbench.core.execution_plan_models import ExecutionPlan
from fpbench.core.identifiers import PairId
from fpbench.core.models import ComparisonPair
from fpbench.core.provenance_models import software_provenance_fingerprint
from fpbench.core.result_models import RunDefinition
from fpbench.core.result_set_models import ResultSetEntry, ResultSetManifest
from fpbench.decisions.verify import verify_decision_set
from fpbench.derivations.receipt import (
    verify_derivation_finalization_marker,
    verify_derivation_receipt,
)
from fpbench.eligibility.verify import verify_eligibility_set
from fpbench.evaluation.verify import verify_evaluation_view
from fpbench.storage.decision_set_store import DecisionSetStore
from fpbench.storage.eligibility_set_store import EligibilitySetStore
from fpbench.storage.evaluation_view_store import EvaluationViewStore
from fpbench.storage.result_store import ResultStore

__all__ = ["inspect_decision_derivation", "VIEW_KINDS"]

VIEW_KINDS = (
    MATED_UNCONDITIONAL_VIEW,
    MATED_CONDITIONAL_VIEW,
    NON_MATED_SANITY_VIEW,
)


def inspect_decision_derivation(
    *,
    run: RunDefinition,
    plan: ExecutionPlan,
    pairs: Mapping[PairId, ComparisonPair],
    units: Sequence[SelfEligibilityUnit],
    result_set: ResultSetManifest,
    result_set_entries: tuple[ResultSetEntry, ...],
    result_store: ResultStore,
    research_status: ResearchRunStatus,
    decision_profile: DecisionProfile,
    definition: DerivationDefinition | None,
    decision_set_id: str | None,
    pair_manifest_hash: str,
    non_mated_finger_shift: int,
    workspace: Path | None = None,
    source_finalization: SourceFinalizationIdentity | None = None,
) -> DecisionDerivationState:
    """Recompute the whole chain and report where it stands.

    Never raises for a derivation that is merely unfinished or even broken; the
    state is the answer.
    """
    root = Path(workspace) if workspace is not None else result_store.root
    decisions_store = DecisionSetStore(root)
    eligibility_store = EligibilitySetStore(root)
    view_store = EvaluationViewStore(root)

    issues: list[str] = []
    source_ready = research_status is ResearchRunStatus.RESEARCH_READY
    if not source_ready:
        issues.append(
            f"the source run is {research_status.value}, not research_ready; no "
            "derivation over it can be authoritative"
        )

    profile_present = False
    profile_valid = False
    decision_set_present = False
    decision_set_valid = False
    eligibility_present = False
    eligibility_valid = False
    views_present = 0
    views_valid = 0
    receipt_present = False
    receipt_valid = False
    finalization_present = False
    finalization_valid = False

    totals = {"decisions": 0, "decided": 0, "undecidable": 0, "units": 0}

    decisions_by_job: Mapping[str, DecisionRecord] = {}
    decision_manifest = None
    eligibility_manifest = None
    eligibility_records: tuple = ()
    view_manifests: dict[str, object] = {}

    if definition is not None:
        for label, actual, expected in (
            ("run id", definition.run_id, run.run_id),
            ("run fingerprint", definition.run_fingerprint, run.run_fingerprint),
            ("result-set id", definition.result_set_id, result_set.result_set_id),
            (
                "result-set fingerprint",
                definition.result_set_fingerprint,
                result_set.result_set_fingerprint,
            ),
            (
                "decision-profile id",
                definition.decision_profile_id,
                decision_profile.profile_id,
            ),
            (
                "decision-profile fingerprint",
                definition.decision_profile_fingerprint,
                decision_profile.profile_fingerprint,
            ),
            (
                "software fingerprint",
                definition.derivation_software_fingerprint,
                software_provenance_fingerprint(definition.derivation_software),
            ),
            (
                "source commit",
                definition.derivation_source_commit,
                definition.derivation_software.source_revision,
            ),
        ):
            if actual != expected:
                issues.append(
                    f"derivation definition {label} is {actual!r}, expected "
                    f"{expected!r}"
                )

    if decision_set_id and decisions_store.has_decision_set(run.run_id, decision_set_id):
        decision_set_present = True
        profile_present = decisions_store.profile_path(
            run.run_id, decision_set_id
        ).is_file()
        try:
            profile, decision_manifest, records = decisions_store.read_decision_set(
                run.run_id, decision_set_id
            )
            profile_valid = (
                profile.profile_id == decision_profile.profile_id
                and profile.profile_fingerprint
                == decision_profile.profile_fingerprint
                and (
                    definition is None
                    or (
                        profile.profile_id == definition.decision_profile_id
                        and profile.profile_fingerprint
                        == definition.decision_profile_fingerprint
                    )
                )
            )
            if not profile_valid:
                issues.append(
                    "the stored profile is not the one this derivation was prepared "
                    "with"
                )
            verify_decision_set(
                profile=profile,
                manifest=decision_manifest,
                records=records,
                run=run,
                plan=plan,
                result_set=result_set,
                result_set_entries=result_set_entries,
                result_store=result_store,
            )
            if definition is not None:
                for label, actual, expected in (
                    (
                        "source commit",
                        decision_manifest.derivation_source_revision,
                        definition.derivation_source_commit,
                    ),
                    (
                        "software fingerprint",
                        decision_manifest.derivation_software_fingerprint,
                        definition.derivation_software_fingerprint,
                    ),
                ):
                    if actual != expected:
                        raise FpbenchError(
                            f"decision-set {label} is {actual!r}, expected "
                            f"definition value {expected!r}"
                        )
            decision_set_valid = True
            decisions_by_job = {record.job_id: record for record in records}
            totals["decisions"] = decision_manifest.total_decisions
            totals["decided"] = decision_manifest.decided_count
            totals["undecidable"] = decision_manifest.undecidable_count
        except FpbenchError as exc:
            issues.append(f"decision set: {exc}")

    if decision_set_id and decision_set_valid and eligibility_store.has_eligibility_set(
        run.run_id, decision_set_id
    ):
        eligibility_present = True
        try:
            eligibility_manifest, eligibility_records = (
                eligibility_store.read_eligibility_set(run.run_id, decision_set_id)
            )
            verify_eligibility_set(
                manifest=eligibility_manifest,
                records=eligibility_records,
                units=units,
                decisions=decisions_by_job,
                decision_set=decision_manifest,
                pair_manifest_hash=pair_manifest_hash,
            )
            eligibility_valid = True
            totals["units"] = eligibility_manifest.total_units
        except FpbenchError as exc:
            issues.append(f"eligibility set: {exc}")

    if decision_set_id and decision_set_valid:
        for kind in VIEW_KINDS:
            if not view_store.has_view(run.run_id, decision_set_id, kind):
                continue
            views_present += 1
            try:
                manifest, entries = view_store.read_view(
                    run.run_id, decision_set_id, kind
                )
                verify_evaluation_view(
                    manifest=manifest,
                    entries=entries,
                    run=run,
                    plan=plan,
                    pairs=pairs,
                    decisions=decisions_by_job,
                    decision_set=decision_manifest,
                    eligibility=(
                        eligibility_manifest
                        if kind == MATED_CONDITIONAL_VIEW
                        else None
                    ),
                    eligibility_records=eligibility_records,
                    pair_manifest_hash=pair_manifest_hash,
                    non_mated_finger_shift=non_mated_finger_shift,
                )
                view_manifests[kind] = manifest
                views_valid += 1
            except FpbenchError as exc:
                issues.append(f"view {kind}: {exc}")

    complete_views = views_valid == len(VIEW_KINDS)

    if decision_set_id and decisions_store.has_receipt(run.run_id, decision_set_id):
        receipt_present = True
        if complete_views and eligibility_valid and definition is not None:
            try:
                receipt = decisions_store.read_receipt(run.run_id, decision_set_id)
                verify_derivation_receipt(
                    receipt=receipt,
                    run=run,
                    result_set=result_set,
                    decision_set=decision_manifest,
                    eligibility=eligibility_manifest,
                    unconditional_view=view_manifests[MATED_UNCONDITIONAL_VIEW],
                    conditional_view=view_manifests[MATED_CONDITIONAL_VIEW],
                    non_mated_view=view_manifests[NON_MATED_SANITY_VIEW],
                    pair_manifest_hash=pair_manifest_hash,
                    definition=definition,
                    source_finalization=source_finalization,
                )
                receipt_valid = True
            except FpbenchError as exc:
                issues.append(f"derivation receipt: {exc}")
        else:
            issues.append(
                "a derivation receipt is stored over an incomplete, invalid or "
                "undefined chain"
            )

    if decision_set_id and decisions_store.has_finalization(
        run.run_id, decision_set_id
    ):
        finalization_present = True
        if receipt_valid:
            try:
                marker = decisions_store.read_finalization(
                    run.run_id, decision_set_id
                )
                verify_derivation_finalization_marker(
                    marker=marker,
                    run=run,
                    result_set=result_set,
                    decision_set=decision_manifest,
                    eligibility=eligibility_manifest,
                    unconditional_view=view_manifests[MATED_UNCONDITIONAL_VIEW],
                    conditional_view=view_manifests[MATED_CONDITIONAL_VIEW],
                    non_mated_view=view_manifests[NON_MATED_SANITY_VIEW],
                    receipt=decisions_store.read_receipt(run.run_id, decision_set_id),
                    definition=definition,
                    source_finalization=source_finalization,
                )
                finalization_valid = True
            except FpbenchError as exc:
                issues.append(f"finalization marker: {exc}")
        else:
            issues.append(
                "a finalization marker is stored over an unverified receipt"
            )

    status = _status(
        definition_present=definition is not None,
        source_ready=source_ready,
        decision_set_valid=decision_set_valid,
        eligibility_valid=eligibility_valid,
        views_valid=complete_views,
        receipt_valid=receipt_valid,
        finalization_valid=finalization_valid,
        decision_set_present=decision_set_present,
        issues=issues,
    )

    return DecisionDerivationState(
        run_id=run.run_id,
        decision_set_id=decision_set_id,
        status=status,
        definition_present=definition is not None,
        source_research_ready=source_ready,
        profile_present=profile_present,
        profile_valid=profile_valid,
        decision_set_present=decision_set_present,
        decision_set_valid=decision_set_valid,
        eligibility_present=eligibility_present,
        eligibility_valid=eligibility_valid,
        views_present=views_present,
        views_valid=views_valid,
        receipt_present=receipt_present,
        receipt_valid=receipt_valid,
        finalization_present=finalization_present,
        finalization_valid=finalization_valid,
        total_decisions=totals["decisions"],
        decided_count=totals["decided"],
        undecidable_count=totals["undecidable"],
        total_eligibility_units=totals["units"],
        issues=tuple(issues),
        inspected_utc=_dt.datetime.now(_dt.timezone.utc).isoformat(),
    )


def _status(
    *,
    definition_present: bool,
    source_ready: bool,
    decision_set_valid: bool,
    eligibility_valid: bool,
    views_valid: bool,
    receipt_valid: bool,
    finalization_valid: bool,
    decision_set_present: bool,
    issues: Sequence[str],
) -> DecisionDerivationStatus:
    if issues:
        return DecisionDerivationStatus.INVALID
    if not definition_present:
        return DecisionDerivationStatus.NOT_PREPARED
    if not source_ready:
        return DecisionDerivationStatus.INVALID
    if not decision_set_present:
        return DecisionDerivationStatus.PROFILE_READY
    if not decision_set_valid:
        return DecisionDerivationStatus.INVALID
    if not eligibility_valid:
        return DecisionDerivationStatus.DECISIONS_READY
    if not views_valid:
        return DecisionDerivationStatus.ELIGIBILITY_READY
    if not (receipt_valid and finalization_valid):
        return DecisionDerivationStatus.VIEWS_READY
    return DecisionDerivationStatus.DECISION_READY
