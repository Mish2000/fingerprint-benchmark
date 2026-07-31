"""Counting decisions, and publishing the counts with their denominators.

Stage 5A said which comparisons belonged to an evaluation and what a threshold
said about each. This package turns that into numbers, and the whole design is
arranged around one refusal: **no rate is ever published without the two integers
it was computed from.**

The pieces, in the order they run:

``policy``
    The fixed catalogue of metric definitions, and the parser that reads which of
    them a policy file switches on. Definitions live in code; a config file
    selects, it does not define.

``aggregate``
    Six count families, per release and pooled, built from the decision set, the
    eligibility set and the three views. Never from a raw score, never from a
    directory name.

``denominators``
    The single function that turns a numerator enum and a denominator enum into
    two integers. Both the deriver and the verifier call it, so they cannot
    disagree about what a denominator was.

``observations``
    One observation per metric per scope, in canonical order, with the pooled
    value checked to be the sum of its releases.

``verify``
    Re-derives all of it from the sources and refuses any difference.

``summary`` / ``report``
    The machine-readable and human-readable renderings, computed from verified
    numbers and never from the underlying rows.

``receipt`` / ``status``
    The committable evidence, the last-written marker, and the recomputed answer
    to "how far along is this?".
"""

from fpbench.metrics.aggregate import (
    MetricSources,
    aggregate_count_records,
    release_order_of,
)
from fpbench.metrics.denominators import resolve
from fpbench.metrics.observations import build_observations
from fpbench.metrics.policy import (
    METRIC_CATALOGUE,
    METRIC_CATALOGUE_ORDER,
    build_metric_policy,
    build_report_profile,
    load_metric_policy,
)
from fpbench.metrics.receipt import (
    build_evaluation_finalization_marker,
    build_evaluation_receipt,
    structural_counts_of,
    write_evaluation_evidence_copies,
)
from fpbench.metrics.report import ReportContext, render_report
from fpbench.metrics.status import inspect_evaluation
from fpbench.metrics.summary import build_evaluation_summary
from fpbench.metrics.verify import (
    verify_evaluation_finalization_marker,
    verify_evaluation_receipt,
    verify_evaluation_report,
    verify_evaluation_summary,
    verify_metric_set,
)

__all__ = [
    "MetricSources",
    "aggregate_count_records",
    "release_order_of",
    "resolve",
    "build_observations",
    "METRIC_CATALOGUE",
    "METRIC_CATALOGUE_ORDER",
    "build_metric_policy",
    "build_report_profile",
    "load_metric_policy",
    "build_evaluation_finalization_marker",
    "build_evaluation_receipt",
    "structural_counts_of",
    "write_evaluation_evidence_copies",
    "ReportContext",
    "render_report",
    "inspect_evaluation",
    "build_evaluation_summary",
    "verify_metric_set",
    "verify_evaluation_summary",
    "verify_evaluation_report",
    "verify_evaluation_receipt",
    "verify_evaluation_finalization_marker",
]
