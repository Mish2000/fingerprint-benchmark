"""Comparing two algorithms over one body of inputs, at two documented points.

The layer above ``decisions``, ``eligibility``, ``evaluation`` and ``metrics``,
and beside ``paired`` rather than on top of it. The two are deliberately
separate: ``paired`` compares two runs of *the same* algorithm under two image
preparations, where a score delta is meaningful and an exactly-equal control set
is the argument. Neither holds between two different matchers, so the paired
schema's assumptions are wrong here rather than merely unused
(docs/adr/0060, spec section 53).

Dependency rule: ``cross_algorithm`` imports ``core``. It does not import an
adapter, a result store, a score parser or a threshold, and it has no field or
function through which a raw score could reach it — which the structural suite
checks by walking these files' syntax trees (spec section 76).
"""

from fpbench.core.cross_algorithm_models import (
    NO_SUPERIORITY_STATEMENT,
    OPERATING_POINT_RELATION,
    CrossAlgorithmCommonEligibleEntry,
    CrossAlgorithmComparisonRecord,
    CrossAlgorithmCountRecord,
    CrossAlgorithmEligibilityTransition,
    CrossAlgorithmEvaluationDefinition,
    CrossAlgorithmEvaluationManifest,
    CrossAlgorithmEvaluationReceipt,
    CrossAlgorithmEvaluationState,
    CrossAlgorithmFinalization,
    CrossAlgorithmObservation,
    FairComparabilityAudit,
    FairMeasurementProtocol,
    cross_algorithm_definition_fingerprint,
    cross_algorithm_evaluation_id,
    fair_comparability_audit_fingerprint,
    fair_measurement_protocol_fingerprint,
    rate_difference,
    require_no_score_comparison,
)
from fpbench.cross_algorithm.align import (
    ComparisonPolicy,
    ComparisonSide,
    CrossAlgorithmError,
    build_comparison_records,
    build_fair_comparability_audit,
    load_comparison_policy,
    outcome_of,
    require_clean_audit,
)
from fpbench.cross_algorithm.derive import (
    METRIC_IDS,
    POOLED_SCOPE,
    PRIMARY_METRIC_ID,
    CrossAlgorithmDerivation,
    derive_cross_algorithm_evaluation,
)
from fpbench.cross_algorithm.receipt import (
    EVIDENCE_DIRECTORY,
    build_cross_algorithm_finalization,
    build_cross_algorithm_receipt,
    verify_cross_algorithm_finalization,
    verify_cross_algorithm_receipt,
    write_evidence,
)
from fpbench.cross_algorithm.report import render_report, report_content_hash
from fpbench.cross_algorithm.status import inspect_cross_algorithm_evaluation
from fpbench.cross_algorithm.verify import (
    require_complete_matrices,
    verify_audit,
    verify_definition,
    verify_derivation,
    verify_protocol,
)

__all__ = [
    "NO_SUPERIORITY_STATEMENT",
    "OPERATING_POINT_RELATION",
    "EVIDENCE_DIRECTORY",
    "METRIC_IDS",
    "POOLED_SCOPE",
    "PRIMARY_METRIC_ID",
    "ComparisonPolicy",
    "ComparisonSide",
    "CrossAlgorithmCommonEligibleEntry",
    "CrossAlgorithmComparisonRecord",
    "CrossAlgorithmCountRecord",
    "CrossAlgorithmDerivation",
    "CrossAlgorithmEligibilityTransition",
    "CrossAlgorithmError",
    "CrossAlgorithmEvaluationDefinition",
    "CrossAlgorithmEvaluationManifest",
    "CrossAlgorithmEvaluationReceipt",
    "CrossAlgorithmEvaluationState",
    "CrossAlgorithmFinalization",
    "CrossAlgorithmObservation",
    "FairComparabilityAudit",
    "FairMeasurementProtocol",
    "build_comparison_records",
    "build_cross_algorithm_finalization",
    "build_cross_algorithm_receipt",
    "build_fair_comparability_audit",
    "cross_algorithm_definition_fingerprint",
    "cross_algorithm_evaluation_id",
    "derive_cross_algorithm_evaluation",
    "fair_comparability_audit_fingerprint",
    "fair_measurement_protocol_fingerprint",
    "inspect_cross_algorithm_evaluation",
    "load_comparison_policy",
    "outcome_of",
    "rate_difference",
    "render_report",
    "report_content_hash",
    "require_clean_audit",
    "require_complete_matrices",
    "require_no_score_comparison",
    "verify_audit",
    "verify_cross_algorithm_finalization",
    "verify_cross_algorithm_receipt",
    "verify_definition",
    "verify_derivation",
    "verify_protocol",
    "write_evidence",
]
