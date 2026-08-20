"""The two files that close a comparison, and the evidence copies beside them.

The receipt binds both chains end to end — every run, result set, decision set,
eligibility set, metric set and decision profile on both sides, plus the shared
alignment, the shared eligibility policy, the shared metric policy, the
comparison policy and the frozen measurement protocol (spec section 68).

The marker comes after, and only after every other file has been written and read
back. Without it, a directory holding an audit, a comparison, a report and a
receipt is retryable work in progress rather than a finished comparison
(docs/adr/0020).

Evidence is written once. A second run either produces identical bytes or
refuses; there is no path here that overwrites a published comparison.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
from pathlib import Path
from typing import Any

from fpbench.core.cross_algorithm_models import (
    CROSS_ALGORITHM_SCHEMA_VERSION,
    NO_SUPERIORITY_STATEMENT,
    OPERATING_POINT_RELATION,
    CrossAlgorithmEvaluationDefinition,
    CrossAlgorithmEvaluationManifest,
    CrossAlgorithmEvaluationReceipt,
    CrossAlgorithmFinalization,
    FairComparabilityAudit,
    FairMeasurementProtocol,
    cross_algorithm_finalization_fingerprint,
    cross_algorithm_receipt_content_hash,
    cross_algorithm_receipt_fingerprint,
)
from fpbench.core.errors import ResultConflictError
from fpbench.core.provenance_models import (
    SoftwareProvenance,
    software_provenance_fingerprint,
)
from fpbench.core.serialization import to_plain
from fpbench.cross_algorithm.align import ComparisonSide, CrossAlgorithmError

__all__ = [
    "EVIDENCE_DIRECTORY",
    "build_cross_algorithm_receipt",
    "verify_cross_algorithm_receipt",
    "build_cross_algorithm_finalization",
    "verify_cross_algorithm_finalization",
    "write_evidence",
]

#: One directory per comparison family, and one file per artefact inside it.
EVIDENCE_DIRECTORY = Path("evidence") / "sourceafis-vs-nbis-canonical500"


def build_cross_algorithm_receipt(
    *,
    protocol: FairMeasurementProtocol,
    definition: CrossAlgorithmEvaluationDefinition,
    manifest: CrossAlgorithmEvaluationManifest,
    audit: FairComparabilityAudit,
    left: ComparisonSide,
    right: ComparisonSide,
    report_content_hash: str,
    comparison_software: SoftwareProvenance,
    created_utc: str | None = None,
) -> CrossAlgorithmEvaluationReceipt:
    """Derive the committable receipt for a complete, verified comparison."""
    if not comparison_software.is_research_grade:
        raise CrossAlgorithmError(
            "a comparison receipt needs a committed, clean source revision "
            "(docs/adr/0017)"
        )
    if not audit.is_clean:
        raise CrossAlgorithmError(
            "a comparison receipt cannot be built over an unclean fairness audit: "
            f"{list(audit.failures)}"
        )
    if right.stage_finalization_fingerprint is None:
        raise CrossAlgorithmError(
            "the right-hand run has no stage finalization marker; the alignment "
            "proof would not be bound to any evidence (docs/adr/0054)"
        )

    return CrossAlgorithmEvaluationReceipt(
        schema_version=CROSS_ALGORITHM_SCHEMA_VERSION,
        protocol_id=protocol.protocol_id,
        protocol_fingerprint=protocol.protocol_fingerprint,
        evaluation_id=manifest.evaluation_id,
        evaluation_fingerprint=manifest.evaluation_fingerprint,
        definition_fingerprint=definition.definition_fingerprint,
        audit_fingerprint=audit.audit_fingerprint,
        left_label=left.label,
        left_run_fingerprint=left.run.run_fingerprint,
        left_result_set_fingerprint=left.result_set.result_set_fingerprint,
        left_decision_set_fingerprint=(
            left.decision_manifest.decision_set_fingerprint
        ),
        left_eligibility_set_fingerprint=(
            left.eligibility_manifest.eligibility_set_fingerprint
        ),
        left_metric_set_fingerprint=left.metric_manifest.metric_set_fingerprint,
        left_decision_profile_fingerprint=left.decision_profile.profile_fingerprint,
        right_label=right.label,
        right_run_fingerprint=right.run.run_fingerprint,
        right_result_set_fingerprint=right.result_set.result_set_fingerprint,
        right_decision_set_fingerprint=(
            right.decision_manifest.decision_set_fingerprint
        ),
        right_eligibility_set_fingerprint=(
            right.eligibility_manifest.eligibility_set_fingerprint
        ),
        right_metric_set_fingerprint=right.metric_manifest.metric_set_fingerprint,
        right_decision_profile_fingerprint=(
            right.decision_profile.profile_fingerprint
        ),
        right_stage_finalization_fingerprint=right.stage_finalization_fingerprint,
        alignment_fingerprint=protocol.alignment_fingerprint,
        eligibility_policy_id=protocol.eligibility_policy_id,
        eligibility_policy_version=protocol.eligibility_policy_version,
        metric_policy_fingerprint=protocol.metric_policy_fingerprint,
        comparison_policy_fingerprint=protocol.comparison_policy_fingerprint,
        comparison_records_hash=manifest.comparison_records_hash,
        eligibility_transitions_hash=manifest.eligibility_transitions_hash,
        common_eligible_hash=manifest.common_eligible_hash,
        count_records_hash=manifest.count_records_hash,
        observations_hash=manifest.observations_hash,
        report_content_hash=report_content_hash,
        comparison_software_fingerprint=software_provenance_fingerprint(
            comparison_software
        ),
        comparison_source_commit=comparison_software.source_revision,
        comparison_source_tree_clean=comparison_software.source_tree_clean,
        total_records=manifest.total_records,
        total_transitions=manifest.total_transitions,
        total_common_eligible=manifest.total_common_eligible,
        total_observations=manifest.total_observations,
        operating_point_relation=OPERATING_POINT_RELATION,
        statement=NO_SUPERIORITY_STATEMENT,
        created_utc=created_utc or _utc_now(),
    )


def verify_cross_algorithm_receipt(
    *,
    receipt: CrossAlgorithmEvaluationReceipt,
    protocol: FairMeasurementProtocol,
    definition: CrossAlgorithmEvaluationDefinition,
    manifest: CrossAlgorithmEvaluationManifest,
    audit: FairComparabilityAudit,
    left: ComparisonSide,
    right: ComparisonSide,
    report_content_hash: str,
) -> None:
    """Re-derive every load-bearing receipt claim from the current artefacts."""
    expected = {
        "protocol_id": protocol.protocol_id,
        "protocol_fingerprint": protocol.protocol_fingerprint,
        "evaluation_id": manifest.evaluation_id,
        "evaluation_fingerprint": manifest.evaluation_fingerprint,
        "definition_fingerprint": definition.definition_fingerprint,
        "audit_fingerprint": audit.audit_fingerprint,
        "left_label": left.label,
        "left_run_fingerprint": left.run.run_fingerprint,
        "left_decision_set_fingerprint": (
            left.decision_manifest.decision_set_fingerprint
        ),
        "left_metric_set_fingerprint": left.metric_manifest.metric_set_fingerprint,
        "right_label": right.label,
        "right_run_fingerprint": right.run.run_fingerprint,
        "right_decision_set_fingerprint": (
            right.decision_manifest.decision_set_fingerprint
        ),
        "right_metric_set_fingerprint": right.metric_manifest.metric_set_fingerprint,
        "right_stage_finalization_fingerprint": right.stage_finalization_fingerprint,
        "alignment_fingerprint": protocol.alignment_fingerprint,
        "metric_policy_fingerprint": protocol.metric_policy_fingerprint,
        "comparison_policy_fingerprint": protocol.comparison_policy_fingerprint,
        "comparison_records_hash": manifest.comparison_records_hash,
        "eligibility_transitions_hash": manifest.eligibility_transitions_hash,
        "common_eligible_hash": manifest.common_eligible_hash,
        "count_records_hash": manifest.count_records_hash,
        "observations_hash": manifest.observations_hash,
        "report_content_hash": report_content_hash,
        "total_records": manifest.total_records,
        "total_transitions": manifest.total_transitions,
        "total_common_eligible": manifest.total_common_eligible,
        "total_observations": manifest.total_observations,
        "operating_point_relation": OPERATING_POINT_RELATION,
        "statement": NO_SUPERIORITY_STATEMENT,
    }
    for name, value in expected.items():
        actual = getattr(receipt, name)
        if actual != value:
            raise CrossAlgorithmError(
                f"comparison receipt field {name} is {actual!r}, expected {value!r}"
            )


def build_cross_algorithm_finalization(
    *,
    receipt: CrossAlgorithmEvaluationReceipt,
    manifest: CrossAlgorithmEvaluationManifest,
    protocol: FairMeasurementProtocol,
    audit: FairComparabilityAudit,
    report_content_hash: str,
    comparison_software: SoftwareProvenance,
    created_utc: str | None = None,
) -> CrossAlgorithmFinalization:
    """The last-written authority over a verified comparison chain."""
    if not comparison_software.is_research_grade:
        raise CrossAlgorithmError(
            "comparison finalization requires a committed, clean source revision"
        )
    claims = {
        "schema_version": CROSS_ALGORITHM_SCHEMA_VERSION,
        "evaluation_id": manifest.evaluation_id,
        "evaluation_fingerprint": manifest.evaluation_fingerprint,
        "protocol_fingerprint": protocol.protocol_fingerprint,
        "audit_fingerprint": audit.audit_fingerprint,
        "receipt_fingerprint": cross_algorithm_receipt_fingerprint(receipt),
        "receipt_content_hash": cross_algorithm_receipt_content_hash(receipt),
        "report_content_hash": report_content_hash,
        "comparison_source_commit": comparison_software.source_revision,
        "comparison_source_tree_clean": comparison_software.source_tree_clean,
    }
    fingerprint = cross_algorithm_finalization_fingerprint(claims)
    return CrossAlgorithmFinalization(
        **claims,
        finalization_id=f"algcomparefinal_{fingerprint[:12]}",
        finalization_fingerprint=fingerprint,
        created_utc=created_utc or _utc_now(),
    )


def verify_cross_algorithm_finalization(
    *,
    marker: CrossAlgorithmFinalization,
    receipt: CrossAlgorithmEvaluationReceipt,
    manifest: CrossAlgorithmEvaluationManifest,
    protocol: FairMeasurementProtocol,
    audit: FairComparabilityAudit,
    report_content_hash: str,
) -> None:
    expected = {
        "evaluation_id": manifest.evaluation_id,
        "evaluation_fingerprint": manifest.evaluation_fingerprint,
        "protocol_fingerprint": protocol.protocol_fingerprint,
        "audit_fingerprint": audit.audit_fingerprint,
        "receipt_fingerprint": cross_algorithm_receipt_fingerprint(receipt),
        "receipt_content_hash": cross_algorithm_receipt_content_hash(receipt),
        "report_content_hash": report_content_hash,
    }
    for name, value in expected.items():
        actual = getattr(marker, name)
        if actual != value:
            raise CrossAlgorithmError(
                f"comparison finalization field {name} is {actual!r}, expected "
                f"{value!r}"
            )
    if cross_algorithm_finalization_fingerprint(marker) != (
        marker.finalization_fingerprint
    ):
        raise CrossAlgorithmError(
            "the comparison finalization does not fingerprint to its own claims"
        )


# ------------------------------------------------------------------ evidence


def write_evidence(
    path: Path, value: Any, *, is_markdown: bool = False
) -> Path:
    """Write one committable file, byte-identically or not at all.

    Line endings are normalised to the platform's, matching ``write_json``, so
    that a copy checked out by git on another platform is recognised as the same
    evidence rather than as a conflicting one.
    """
    rendered = (
        str(value)
        if is_markdown
        else json.dumps(to_plain(value), indent=2, ensure_ascii=False, sort_keys=False)
        + "\n"
    )
    # LF on every platform. These bytes are compared against the committed
    # copy and, in several stages, hashed into a marker; translating them to
    # the writer's native line ending made one document into two, depending
    # on which machine happened to write it (docs/adr/0139).
    payload = rendered.replace("\r\n", "\n").encode("utf-8")
    path = Path(path)
    if path.is_file():
        if path.read_bytes() != payload:
            raise ResultConflictError(
                f"{path} already contains different comparison evidence; refusing "
                "to replace it"
            )
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(payload)
    except FileExistsError:  # pragma: no cover - lost race, same rule
        if path.read_bytes() != payload:
            raise ResultConflictError(
                f"{path} appeared with different comparison evidence; refusing to "
                "overwrite it"
            )
    return path


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()
