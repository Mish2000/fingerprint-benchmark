"""Comparing two finished derivations of the same 6,000 pairs.

Dependency rule: ``paired`` imports ``core``, ``storage``, ``derivations``,
``metrics`` and the shared SourceAFIS decision engine. It never runs Java, never
opens a raw result except to read one score, and never modifies anything the two
source chains own.

The layer exists because a comparison is a third artefact with its own identity,
not a section of either evaluation's report. Filing it inside one of them would
suggest that run is the subject and the other merely a reference; neither is
(docs/adr/0036).
"""

from fpbench.core.paired_models import (
    NativeCanonicalControlAudit,
    PairedComparisonRecord,
    PairedEvaluationDefinition,
    PairedEvaluationManifest,
    PairedRateObservation,
    SelfEligibilityTransitionRecord,
    TransitionCountRecord,
    exact_rate_difference,
)
from fpbench.paired.derive import (
    CONTROL_RELEASE,
    OBSERVATION_IDS,
    align_pairs,
    build_common_eligible_view,
    build_control_audit,
    build_eligibility_transitions,
    build_paired_observations,
    build_paired_records,
    build_transition_counts,
    release_order,
    require_clean_control,
)
from fpbench.paired.policy import PairedComparisonPolicy, load_paired_policy
from fpbench.paired.receipt import (
    build_paired_finalization_marker,
    build_paired_receipt,
    require_sanitised_paired_receipt,
    verify_paired_receipt,
    write_paired_evidence_copies,
)
from fpbench.paired.report import build_paired_summary, render_paired_report
from fpbench.paired.sources import PairedSide, load_paired_side, require_comparable_runs
from fpbench.paired.status import PairedEvaluationState, inspect_paired_evaluation

__all__ = [
    "CONTROL_RELEASE",
    "OBSERVATION_IDS",
    "NativeCanonicalControlAudit",
    "PairedComparisonPolicy",
    "PairedComparisonRecord",
    "PairedEvaluationDefinition",
    "PairedEvaluationManifest",
    "PairedEvaluationState",
    "PairedRateObservation",
    "PairedSide",
    "SelfEligibilityTransitionRecord",
    "TransitionCountRecord",
    "align_pairs",
    "build_common_eligible_view",
    "build_control_audit",
    "build_eligibility_transitions",
    "build_paired_finalization_marker",
    "build_paired_observations",
    "build_paired_receipt",
    "build_paired_records",
    "build_paired_summary",
    "build_transition_counts",
    "exact_rate_difference",
    "inspect_paired_evaluation",
    "load_paired_policy",
    "load_paired_side",
    "release_order",
    "render_paired_report",
    "require_clean_control",
    "require_comparable_runs",
    "require_sanitised_paired_receipt",
    "verify_paired_receipt",
    "write_paired_evidence_copies",
]
