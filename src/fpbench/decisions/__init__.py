"""Turning stored scores into decisions, one exact threshold at a time.

Dependency rule: ``decisions`` imports ``core`` and ``storage`` and nothing else
from the project. It never imports an adapter, never names an algorithm, and
never reaches back into how a score was produced — which is the whole reason a
threshold can be re-applied to unchanged results as often as a study needs
(docs/adr/0003, docs/adr/0021).
"""

from fpbench.core.decision_models import (
    DecisionApplicationStatus,
    DecisionProfile,
    DecisionRecord,
    DecisionSetManifest,
    DecisionValue,
    ThresholdComparator,
    ThresholdOrigin,
    canonical_threshold,
)
from fpbench.decisions.apply import DecisionSet, apply_decision_profile, decide_score
from fpbench.decisions.profiles import (
    build_decision_profile,
    load_decision_profile,
    require_profile_applies_to_run,
)
from fpbench.decisions.verify import verify_decision_set

__all__ = [
    "DecisionApplicationStatus",
    "DecisionProfile",
    "DecisionRecord",
    "DecisionSet",
    "DecisionSetManifest",
    "DecisionValue",
    "ThresholdComparator",
    "ThresholdOrigin",
    "apply_decision_profile",
    "build_decision_profile",
    "canonical_threshold",
    "decide_score",
    "load_decision_profile",
    "require_profile_applies_to_run",
    "verify_decision_set",
]
