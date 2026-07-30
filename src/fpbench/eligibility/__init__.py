"""Which fingers may take part in the conditional PLAIN–ROLL report.

Dependency rule: ``eligibility`` imports ``core``, ``decisions`` and
``storage``. It never imports an adapter and never names an algorithm — a
finger's eligibility is a statement about decisions, and decisions have already
forgotten which matcher made them (docs/adr/0023).
"""

from fpbench.core.eligibility_models import (
    ELIGIBILITY_POLICY_ID,
    ELIGIBILITY_POLICY_VERSION,
    SelfEligibilityDecisionRecord,
    SelfEligibilityManifest,
    SelfEligibilityReason,
    SelfEligibilityStatus,
    SelfEligibilityUnit,
    eligibility_status_of,
)
from fpbench.eligibility.derive import EligibilitySet, derive_self_eligibility
from fpbench.eligibility.self_mapping import (
    DEFAULT_SELF_INDEPENDENCE,
    SelfIndependenceRequirement,
    build_self_eligibility_units,
    require_self_independence_evidence,
)
from fpbench.eligibility.verify import verify_eligibility_set

__all__ = [
    "DEFAULT_SELF_INDEPENDENCE",
    "ELIGIBILITY_POLICY_ID",
    "ELIGIBILITY_POLICY_VERSION",
    "EligibilitySet",
    "SelfEligibilityDecisionRecord",
    "SelfEligibilityManifest",
    "SelfEligibilityReason",
    "SelfEligibilityStatus",
    "SelfEligibilityUnit",
    "SelfIndependenceRequirement",
    "build_self_eligibility_units",
    "derive_self_eligibility",
    "eligibility_status_of",
    "require_self_independence_evidence",
    "verify_eligibility_set",
]
