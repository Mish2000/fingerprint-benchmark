"""Where a paired comparison stands, re-derived rather than remembered.

The same shape as every other status ladder in this project. Nothing writes a
status; it is read off the files that exist and re-verified every time it is
asked for.

One rung is unusual: ``PAIRED_EVALUATION_READY`` requires a *clean control
audit* on top of everything else. A comparison whose SD300A control failed can
be complete, internally consistent, and fully written — and still mean nothing,
because the difference it reports is then a difference of unknown origin
(spec section 56).
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from pathlib import Path

from fpbench.core.enums import PairedEvaluationStatus
from fpbench.core.errors import StorageError
from fpbench.core.paired_models import (
    paired_receipt_content_hash,
    paired_receipt_fingerprint,
)
from fpbench.storage.paired_evaluation_store import (
    PairedEvaluationStore,
    paired_summary_content_hash,
    report_content_hash,
)

__all__ = ["PairedEvaluationState", "inspect_paired_evaluation"]


@dataclass(frozen=True, slots=True)
class PairedEvaluationState:
    """How far along the chain a comparison is, and why it is not further."""

    paired_evaluation_id: str | None

    status: PairedEvaluationStatus

    total_paired_comparisons: int
    total_eligibility_units: int
    total_common_eligible_rows: int

    control_audit_clean: bool
    manifest_valid: bool
    summary_valid: bool
    report_valid: bool
    receipt_valid: bool
    finalization_valid: bool

    issues: tuple[str, ...]
    inspected_utc: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "issues", tuple(self.issues))

    @property
    def is_paired_evaluation_ready(self) -> bool:
        return self.status is PairedEvaluationStatus.PAIRED_EVALUATION_READY


def inspect_paired_evaluation(
    *, store: PairedEvaluationStore, paired_evaluation_id: str | None
) -> PairedEvaluationState:
    """Report the state of one comparison. Never writes."""
    inspected = _utc_now()
    if not paired_evaluation_id or not store.has_manifest(paired_evaluation_id):
        return PairedEvaluationState(
            paired_evaluation_id=paired_evaluation_id,
            status=PairedEvaluationStatus.NOT_PREPARED,
            total_paired_comparisons=0,
            total_eligibility_units=0,
            total_common_eligible_rows=0,
            control_audit_clean=False,
            manifest_valid=False,
            summary_valid=False,
            report_valid=False,
            receipt_valid=False,
            finalization_valid=False,
            issues=("no paired comparison has been derived",),
            inspected_utc=inspected,
        )

    issues: list[str] = []
    manifest_valid = False
    try:
        manifest = store.verify_paired_evaluation(paired_evaluation_id)
        manifest_valid = True
    except StorageError as exc:
        return PairedEvaluationState(
            paired_evaluation_id=paired_evaluation_id,
            status=PairedEvaluationStatus.INVALID,
            total_paired_comparisons=0,
            total_eligibility_units=0,
            total_common_eligible_rows=0,
            control_audit_clean=False,
            manifest_valid=False,
            summary_valid=False,
            report_valid=False,
            receipt_valid=False,
            finalization_valid=False,
            issues=(str(exc),),
            inspected_utc=inspected,
        )

    control = store.read_control_audit(paired_evaluation_id)
    if not control.is_clean:
        issues.append(
            f"the SD300A control did not reproduce "
            f"({control.equal_scores}/{control.planned_sd300a_pairs} equal scores)"
        )

    summary_valid = store.has_summary(paired_evaluation_id)
    report_valid = store.has_report(paired_evaluation_id)
    receipt_valid = False
    finalization_valid = False

    if store.has_receipt(paired_evaluation_id):
        try:
            store.read_receipt(paired_evaluation_id)
            receipt_valid = True
        except StorageError as exc:
            issues.append(str(exc))

    if store.has_finalization(paired_evaluation_id):
        try:
            marker = store.read_finalization(paired_evaluation_id)
        except StorageError as exc:
            issues.append(str(exc))
        else:
            finalization_valid = _check_marker(
                store=store,
                paired_evaluation_id=paired_evaluation_id,
                marker=marker,
                manifest=manifest,
                control=control,
                issues=issues,
            )

    if issues:
        status = PairedEvaluationStatus.INVALID
    elif finalization_valid and receipt_valid and report_valid and summary_valid:
        status = PairedEvaluationStatus.PAIRED_EVALUATION_READY
    elif report_valid:
        status = PairedEvaluationStatus.REPORT_READY
    elif manifest_valid:
        status = PairedEvaluationStatus.AGGREGATES_READY
    else:  # pragma: no cover - manifest_valid is True by here
        status = PairedEvaluationStatus.RECORDS_READY

    return PairedEvaluationState(
        paired_evaluation_id=paired_evaluation_id,
        status=status,
        total_paired_comparisons=manifest.total_paired_comparisons,
        total_eligibility_units=manifest.total_eligibility_units,
        total_common_eligible_rows=manifest.total_common_eligible_rows,
        control_audit_clean=control.is_clean,
        manifest_valid=manifest_valid,
        summary_valid=summary_valid,
        report_valid=report_valid,
        receipt_valid=receipt_valid,
        finalization_valid=finalization_valid,
        issues=tuple(issues),
        inspected_utc=inspected,
    )


def _check_marker(
    *,
    store: PairedEvaluationStore,
    paired_evaluation_id: str,
    marker,
    manifest,
    control,
    issues: list[str],
) -> bool:
    """Does the marker still name every current durable artefact?"""
    try:
        receipt = store.read_receipt(paired_evaluation_id)
        summary = store.read_summary(paired_evaluation_id)
        markdown = store.read_report(paired_evaluation_id)
    except StorageError as exc:
        issues.append(str(exc))
        return False

    expected = {
        "paired_evaluation_id": manifest.paired_evaluation_id,
        "paired_evaluation_fingerprint": manifest.paired_evaluation_fingerprint,
        "definition_fingerprint": manifest.definition_fingerprint,
        "control_audit_fingerprint": control.audit_fingerprint,
        "summary_content_hash": paired_summary_content_hash(summary),
        "report_content_hash": report_content_hash(markdown),
        "receipt_fingerprint": paired_receipt_fingerprint(receipt),
        "receipt_content_hash": paired_receipt_content_hash(receipt),
    }
    ok = True
    for name, value in expected.items():
        actual = getattr(marker, name)
        if actual != value:
            issues.append(
                f"the finalization marker's {name} is {str(actual)[:16]}..., "
                f"expected {str(value)[:16]}..."
            )
            ok = False
    return ok


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()
