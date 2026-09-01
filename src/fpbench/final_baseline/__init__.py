"""The frozen final-baseline TAR/FAR/FRR reporting component.

Stage 21A predeclared the comparison; Stage 21B executed the cross-subject
raw runs. This component is the reporting boundary that may finally read
score values — through re-verified stores only — and publish the predeclared
tables. It creates no threshold, calibrates nothing, normalizes nothing and
compares no raw score across algorithms.
"""

from fpbench.final_baseline.errors import FinalBaselineError
from fpbench.final_baseline.evaluate import (
    FinalBaselineEvaluation,
    FinalBaselineInputs,
    collect_final_baseline_inputs,
    evaluate_final_baseline,
)
from fpbench.final_baseline.evidence import (
    publish_final_baseline_evidence,
    final_baseline_source_fingerprint,
    verify_final_baseline_evidence,
)
from fpbench.final_baseline.report import render_final_baseline_report
from fpbench.final_baseline.reporting import (
    FinalBaselineReporting,
    NativeDocumentedRule,
    load_final_baseline_reporting,
)

__all__ = [
    "FinalBaselineError",
    "FinalBaselineEvaluation",
    "FinalBaselineInputs",
    "FinalBaselineReporting",
    "NativeDocumentedRule",
    "collect_final_baseline_inputs",
    "evaluate_final_baseline",
    "load_final_baseline_reporting",
    "publish_final_baseline_evidence",
    "render_final_baseline_report",
    "final_baseline_source_fingerprint",
    "verify_final_baseline_evidence",
]
