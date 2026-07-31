"""How far along an evaluation is, recomputed from the artefacts every time.

Nothing here checks that a file exists and moves on. ``counts_valid`` means the
counts were re-derived from the decisions and the views and agreed;
``observations_valid`` means every numerator and denominator was re-resolved from
its enum; ``summary_valid`` and ``report_valid`` mean both renderings were rebuilt
from the verified source chain and agree exactly with the stored copies. The
finalization marker is then checked against those canonical renderings.

That is expensive — reading a status costs roughly what producing it did — and it
is the only reading that means anything. A cheap status would answer "does the
directory look right?", and the whole point of the chain is that a directory can
look right and be wrong (docs/adr/0012).
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Mapping, Sequence

from fpbench.core.decision_models import DecisionProfile, DecisionSetManifest
from fpbench.core.eligibility_models import SelfEligibilityManifest
from fpbench.core.enums import DecisionDerivationStatus, EvaluationStatus
from fpbench.core.errors import FpbenchError
from fpbench.core.evaluation_models import (
    EvaluationState,
    MetricDerivationDefinition,
)
from fpbench.core.result_models import RunDefinition
from fpbench.core.result_set_models import ResultSetManifest
from fpbench.metrics.aggregate import MetricSources
from fpbench.metrics.report import build_report_context, render_report
from fpbench.metrics.verify import (
    verify_evaluation_finalization_marker,
    verify_evaluation_receipt,
    verify_evaluation_report,
    verify_evaluation_summary,
    verify_metric_set,
)
from fpbench.storage.metric_set_store import MetricSetStore

__all__ = ["inspect_evaluation"]


def inspect_evaluation(
    *,
    run: RunDefinition,
    result_set: ResultSetManifest,
    decision_profile: DecisionProfile,
    decision_manifest: DecisionSetManifest,
    eligibility_manifest: SelfEligibilityManifest,
    run_source_commit: str,
    sources: MetricSources,
    decision_status: DecisionDerivationStatus,
    decision_finalization_fingerprint: str | None,
    definition: MetricDerivationDefinition | None,
    metric_set_id: str | None,
    releases: Sequence[str],
    structural_counts: Mapping[str, int],
    workspace: Path,
) -> EvaluationState:
    """Recompute the whole chain and report where it stands. Never writes.

    Never raises for an evaluation that is merely unfinished or even broken; the
    state is the answer.
    """
    run_id = run.run_id
    store = MetricSetStore(Path(workspace))
    releases = tuple(releases)

    issues: list[str] = []
    source_ready = decision_status is DecisionDerivationStatus.DECISION_READY
    if not source_ready:
        issues.append(
            f"the source derivation is {decision_status.value}, not decision_ready; "
            "no evaluation over it can be authoritative"
        )

    policy_present = False
    policy_valid = False
    counts_present = False
    counts_valid = False
    observations_present = False
    observations_valid = False
    metric_set_present = False
    metric_set_valid = False
    summary_present = False
    summary_valid = False
    report_present = False
    report_valid = False
    receipt_present = False
    receipt_valid = False
    finalization_present = False
    finalization_valid = False

    total_counts = 0
    total_observations = 0

    manifest = None
    policy = None
    counts: tuple = ()
    observations: tuple = ()
    summary = None
    markdown = None
    canonical_markdown = None
    receipt = None

    if metric_set_id and store.has_metric_set(run_id, metric_set_id):
        metric_set_present = True
        policy_present = store.policy_path(run_id, metric_set_id).is_file()
        counts_present = store.counts_path(run_id, metric_set_id).is_file()
        observations_present = store.observations_path(
            run_id, metric_set_id
        ).is_file()
        try:
            (
                stored_definition,
                policy,
                report_profile,
                manifest,
                counts,
                observations,
            ) = store.read_metric_set(run_id, metric_set_id)
            total_counts = len(counts)
            total_observations = len(observations)

            if definition is not None and (
                stored_definition.definition_fingerprint
                != definition.definition_fingerprint
            ):
                raise FpbenchError(
                    f"the stored metric set was produced under definition "
                    f"{stored_definition.definition_id}, but this run pins "
                    f"{definition.definition_id}"
                )

            verify_metric_set(
                definition=stored_definition,
                policy=policy,
                report_profile=report_profile,
                manifest=manifest,
                counts=counts,
                observations=observations,
                sources=sources,
                run=run,
                result_set=result_set,
                decision_profile=decision_profile,
                decision_manifest=decision_manifest,
                eligibility_manifest=eligibility_manifest,
                view_manifests=sources.view_manifests,
                releases=releases,
            )
            policy_valid = True
            counts_valid = True
            observations_valid = True
            metric_set_valid = True
            definition = definition or stored_definition
        except FpbenchError as exc:
            issues.append(f"metric set: {exc}")

    if metric_set_id and metric_set_valid and store.has_summary(run_id, metric_set_id):
        summary_present = True
        try:
            summary = store.read_summary(run_id, metric_set_id)
            verify_evaluation_summary(
                summary=summary,
                manifest=manifest,
                counts=counts,
                observations=observations,
                releases=releases,
                run=run,
                decision_profile=decision_profile,
            )
            summary_valid = True
        except FpbenchError as exc:
            issues.append(f"evaluation summary: {exc}")

    if metric_set_id and metric_set_valid and store.has_report(run_id, metric_set_id):
        report_present = True
        try:
            markdown = store.read_report(run_id, metric_set_id)
            canonical_markdown = render_report(
                context=build_report_context(
                    run=run,
                    result_set=result_set,
                    decision_profile=decision_profile,
                    decision_manifest=decision_manifest,
                    eligibility_manifest=eligibility_manifest,
                    metric_manifest=manifest,
                    run_source_commit=run_source_commit,
                ),
                manifest=manifest,
                policy=policy,
                report_profile=report_profile,
                counts=counts,
                observations=observations,
            )
            verify_evaluation_report(
                markdown=markdown, expected_markdown=canonical_markdown
            )
            report_valid = True
        except FpbenchError as exc:
            issues.append(f"evaluation report: {exc}")

    if (
        metric_set_id
        and metric_set_valid
        and definition is not None
        and store.has_receipt(run_id, metric_set_id)
    ):
        receipt_present = True
        try:
            receipt = store.read_receipt(run_id, metric_set_id)
            verify_evaluation_receipt(
                receipt=receipt,
                definition=definition,
                manifest=manifest,
                policy=policy,
                observations=observations,
                releases=releases,
                structural_counts=structural_counts,
                run_id=run_id,
                result_set_id=result_set.result_set_id,
                decision_profile_id=decision_profile.profile_id,
            )
            receipt_valid = True
        except FpbenchError as exc:
            issues.append(f"evaluation receipt: {exc}")
    elif metric_set_id and store.has_receipt(run_id, metric_set_id):
        receipt_present = True
        issues.append(
            "an evaluation receipt is stored over an incomplete, invalid or "
            "undefined metric set"
        )

    if metric_set_id and store.has_finalization(run_id, metric_set_id):
        finalization_present = True
        if (
            receipt_valid
            and summary_valid
            and report_valid
            and definition is not None
            and decision_finalization_fingerprint is not None
        ):
            try:
                marker = store.read_finalization(run_id, metric_set_id)
                verify_evaluation_finalization_marker(
                    marker=marker,
                    definition=definition,
                    manifest=manifest,
                    receipt=receipt,
                    summary=summary,
                    canonical_markdown=canonical_markdown,
                    decision_finalization_fingerprint=(
                        decision_finalization_fingerprint
                    ),
                )
                finalization_valid = True
            except FpbenchError as exc:
                issues.append(f"finalization marker: {exc}")
        else:
            issues.append(
                "a finalization marker is stored over an unverified evaluation"
            )

    status = _status(
        definition_present=definition is not None,
        source_ready=source_ready,
        metric_set_present=metric_set_present,
        counts_valid=counts_valid,
        observations_valid=observations_valid,
        metric_set_valid=metric_set_valid,
        summary_valid=summary_valid,
        report_valid=report_valid,
        receipt_valid=receipt_valid,
        finalization_valid=finalization_valid,
        issues=issues,
    )

    return EvaluationState(
        run_id=run_id,
        metric_set_id=metric_set_id,
        status=status,
        definition_present=definition is not None,
        source_decision_ready=source_ready,
        policy_present=policy_present,
        policy_valid=policy_valid,
        counts_present=counts_present,
        counts_valid=counts_valid,
        observations_present=observations_present,
        observations_valid=observations_valid,
        metric_set_present=metric_set_present,
        metric_set_valid=metric_set_valid,
        summary_present=summary_present,
        summary_valid=summary_valid,
        report_present=report_present,
        report_valid=report_valid,
        receipt_present=receipt_present,
        receipt_valid=receipt_valid,
        finalization_present=finalization_present,
        finalization_valid=finalization_valid,
        total_count_records=total_counts,
        total_observations=total_observations,
        issues=tuple(issues),
        inspected_utc=_dt.datetime.now(_dt.timezone.utc).isoformat(),
    )


def _status(
    *,
    definition_present: bool,
    source_ready: bool,
    metric_set_present: bool,
    counts_valid: bool,
    observations_valid: bool,
    metric_set_valid: bool,
    summary_valid: bool,
    report_valid: bool,
    receipt_valid: bool,
    finalization_valid: bool,
    issues: Sequence[str],
) -> EvaluationStatus:
    if issues:
        return EvaluationStatus.INVALID
    if not definition_present:
        return EvaluationStatus.NOT_PREPARED
    if not source_ready:
        return EvaluationStatus.INVALID
    if not metric_set_present:
        return EvaluationStatus.POLICY_READY
    if not counts_valid:
        return EvaluationStatus.INVALID
    if not observations_valid:
        return EvaluationStatus.COUNTS_READY
    if not metric_set_valid:
        return EvaluationStatus.INVALID
    if not (summary_valid and report_valid):
        return EvaluationStatus.METRICS_READY
    if not (receipt_valid and finalization_valid):
        return EvaluationStatus.REPORT_READY
    return EvaluationStatus.EVALUATION_READY
