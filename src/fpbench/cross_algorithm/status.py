"""How far along a comparison is, recomputed from the artefacts every time.

Nothing here checks that a file exists and moves on. Every ``*_valid`` flag is
the result of re-deriving the thing it describes: the paired records from the two
decision sets, the transitions from the two eligibility sets, the counts from the
records, the observations from the counts, the report from the observations, and
each hash from the artefact it claims to cover.

``CROSS_ALGORITHM_READY`` additionally requires the fairness audit to be clean.
That is not a formality: if the two chains were not given the same pairs in the
same order from the same prepared images under the same policies, then the paired
rows are not paired and the tables above them are two experiments printed side by
side (spec sections 56 and 81).
"""

from __future__ import annotations

import datetime as _dt
from typing import Sequence

from fpbench.core.cross_algorithm_models import (
    CrossAlgorithmEvaluationDefinition,
    CrossAlgorithmEvaluationManifest,
    CrossAlgorithmEvaluationReceipt,
    CrossAlgorithmEvaluationState,
    CrossAlgorithmFinalization,
    FairComparabilityAudit,
    FairMeasurementProtocol,
)
from fpbench.core.enums import CrossAlgorithmStatus
from fpbench.core.errors import FpbenchError
from fpbench.cross_algorithm.derive import CrossAlgorithmDerivation
from fpbench.cross_algorithm.receipt import (
    verify_cross_algorithm_finalization,
    verify_cross_algorithm_receipt,
)
from fpbench.cross_algorithm.verify import (
    verify_audit,
    verify_definition,
    verify_derivation,
    verify_protocol,
)

__all__ = ["inspect_cross_algorithm_evaluation"]


def inspect_cross_algorithm_evaluation(
    *,
    protocol: FairMeasurementProtocol,
    definition: CrossAlgorithmEvaluationDefinition,
    audit: FairComparabilityAudit,
    derivation: CrossAlgorithmDerivation,
    left: object,
    right: object,
    left_evaluation_ready: bool,
    right_evaluation_ready: bool,
    stored_manifest: CrossAlgorithmEvaluationManifest | None,
    stored_receipt: CrossAlgorithmEvaluationReceipt | None,
    stored_marker: CrossAlgorithmFinalization | None,
    stored_report: str | None,
    report_content_hash: str,
    expected_records: int,
    expected_transitions: int,
) -> CrossAlgorithmEvaluationState:
    """Recompute the whole comparison and report where it stands. Never writes."""
    issues: list[str] = []

    if not left_evaluation_ready:
        issues.append(
            "the left chain is not EVALUATION_READY; a comparison cannot outrank "
            "the metrics beneath it"
        )
    if not right_evaluation_ready:
        issues.append(
            "the right chain is not EVALUATION_READY; a comparison cannot outrank "
            "the metrics beneath it"
        )

    try:
        verify_protocol(protocol)
    except FpbenchError as exc:
        issues.append(f"measurement protocol: {exc}")

    audit_present = True
    audit_clean = False
    try:
        verify_audit(audit)
        audit_clean = audit.is_clean
        if not audit_clean:
            issues.append(
                f"fair-comparability audit: {list(audit.failures)} "
                f"{[issue.message for issue in audit.issues][:2]}"
            )
    except FpbenchError as exc:
        audit_present = False
        issues.append(f"fair-comparability audit: {exc}")

    definition_present = True
    try:
        verify_definition(
            definition=definition, protocol=protocol, left=left, right=right
        )
    except FpbenchError as exc:
        definition_present = False
        issues.append(f"comparison definition: {exc}")

    records_present = stored_manifest is not None
    records_valid = False
    aggregates_present = records_present
    aggregates_valid = False
    if stored_manifest is not None:
        try:
            verify_derivation(derivation=derivation, manifest=stored_manifest)
            records_valid = True
            aggregates_valid = True
        except FpbenchError as exc:
            issues.append(f"comparison: {exc}")
    if len(derivation.records) != expected_records:
        records_valid = False
        issues.append(
            f"the comparison holds {len(derivation.records)} paired records, "
            f"expected {expected_records}"
        )
    if len(derivation.transitions) != expected_transitions:
        aggregates_valid = False
        issues.append(
            f"the comparison holds {len(derivation.transitions)} eligibility "
            f"transitions, expected {expected_transitions}"
        )

    report_present = stored_report is not None
    report_valid = False
    if stored_report is not None:
        from fpbench.cross_algorithm.report import report_content_hash as _hash

        if _hash(stored_report) == report_content_hash:
            report_valid = True
        else:
            issues.append(
                "the published report is not the one this comparison renders"
            )

    receipt_present = stored_receipt is not None
    receipt_valid = False
    if stored_receipt is not None and stored_manifest is not None:
        try:
            verify_cross_algorithm_receipt(
                receipt=stored_receipt,
                protocol=protocol,
                definition=definition,
                manifest=stored_manifest,
                audit=audit,
                left=left,
                right=right,
                report_content_hash=report_content_hash,
            )
            receipt_valid = True
        except FpbenchError as exc:
            issues.append(f"comparison receipt: {exc}")

    finalization_present = stored_marker is not None
    finalization_valid = False
    if stored_marker is not None and stored_receipt is not None and stored_manifest:
        if not receipt_valid:
            issues.append("a finalization marker is stored over an unverified receipt")
        else:
            try:
                verify_cross_algorithm_finalization(
                    marker=stored_marker,
                    receipt=stored_receipt,
                    manifest=stored_manifest,
                    protocol=protocol,
                    audit=audit,
                    report_content_hash=report_content_hash,
                )
                finalization_valid = True
            except FpbenchError as exc:
                issues.append(f"comparison finalization: {exc}")

    status = _status(
        issues=issues,
        definition_present=definition_present,
        sources_ready=left_evaluation_ready and right_evaluation_ready,
        audit_clean=audit_clean,
        records_valid=records_valid,
        aggregates_valid=aggregates_valid,
        report_valid=report_valid,
        receipt_valid=receipt_valid,
        finalization_valid=finalization_valid,
        records_present=records_present,
    )
    return CrossAlgorithmEvaluationState(
        evaluation_id=(
            stored_manifest.evaluation_id if stored_manifest is not None else None
        ),
        status=status,
        definition_present=definition_present,
        left_evaluation_ready=left_evaluation_ready,
        right_evaluation_ready=right_evaluation_ready,
        audit_present=audit_present,
        audit_clean=audit_clean,
        records_present=records_present,
        records_valid=records_valid,
        aggregates_present=aggregates_present,
        aggregates_valid=aggregates_valid,
        report_present=report_present,
        report_valid=report_valid,
        receipt_present=receipt_present,
        receipt_valid=receipt_valid,
        finalization_present=finalization_present,
        finalization_valid=finalization_valid,
        total_records=len(derivation.records),
        total_transitions=len(derivation.transitions),
        total_common_eligible=len(derivation.common_eligible),
        total_observations=len(derivation.observations),
        issues=tuple(issues),
        inspected_utc=_dt.datetime.now(_dt.timezone.utc).isoformat(),
    )


def _status(
    *,
    issues: Sequence[str],
    definition_present: bool,
    sources_ready: bool,
    audit_clean: bool,
    records_valid: bool,
    aggregates_valid: bool,
    report_valid: bool,
    receipt_valid: bool,
    finalization_valid: bool,
    records_present: bool,
) -> CrossAlgorithmStatus:
    if issues:
        return CrossAlgorithmStatus.INVALID
    if not definition_present:
        return CrossAlgorithmStatus.NOT_PREPARED
    if not sources_ready:
        return CrossAlgorithmStatus.INVALID
    if not audit_clean:
        return CrossAlgorithmStatus.SOURCES_READY
    if not records_present:
        return CrossAlgorithmStatus.AUDIT_READY
    if not records_valid:
        return CrossAlgorithmStatus.INVALID
    if not aggregates_valid:
        return CrossAlgorithmStatus.RECORDS_READY
    if not report_valid:
        return CrossAlgorithmStatus.AGGREGATES_READY
    if not (receipt_valid and finalization_valid):
        return CrossAlgorithmStatus.REPORT_READY
    return CrossAlgorithmStatus.CROSS_ALGORITHM_READY
