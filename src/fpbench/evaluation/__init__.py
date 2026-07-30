"""What an evaluation is *about* — the comparisons, not the arithmetic.

Stage 5A fills this package with views: named, fingerprinted lists of
comparisons together with the reason each one is in or out. The metrics that
consume them — FMR, FNMR, EER, and the failure denominators they need — are the
next stage, and nothing here computes one.

Dependency rule: ``evaluation`` imports ``core``, ``decisions``, ``eligibility``
and ``storage``. It never imports an adapter.
"""

from fpbench.core.evaluation_view_models import (
    MATED_CONDITIONAL_VIEW,
    MATED_UNCONDITIONAL_VIEW,
    NON_MATED_SANITY_VIEW,
    EvaluationViewEntry,
    EvaluationViewManifest,
    ExclusionReason,
)
from fpbench.evaluation.verify import STAGE_FOR_VIEW, verify_evaluation_view
from fpbench.evaluation.views import (
    EvaluationView,
    build_mated_conditional_view,
    build_mated_unconditional_view,
    build_non_mated_sanity_view,
)

__all__ = [
    "EvaluationView",
    "EvaluationViewEntry",
    "EvaluationViewManifest",
    "ExclusionReason",
    "MATED_CONDITIONAL_VIEW",
    "MATED_UNCONDITIONAL_VIEW",
    "NON_MATED_SANITY_VIEW",
    "STAGE_FOR_VIEW",
    "build_mated_conditional_view",
    "build_mated_unconditional_view",
    "build_non_mated_sanity_view",
    "verify_evaluation_view",
]
