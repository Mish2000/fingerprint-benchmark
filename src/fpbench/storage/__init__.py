"""Persistence for manifests, run manifests and raw results.

Dependency rule: ``storage`` imports ``core`` and nothing else from the
project. It knows how to write a result; it knows nothing about how one is
produced, and never about a specific adapter (docs/adr/0007).

Decision records and artifact storage arrive with the decision layer and the
first adapter that produces artefacts. The raw-result schema already reserves
the ``artifacts`` column so those references have somewhere to land.
"""

from fpbench.storage.decision_set_store import DecisionSetStore
from fpbench.storage.derivation_schemas import (
    DECISION_RECORD_SCHEMA,
    ELIGIBILITY_RECORD_SCHEMA,
    EVALUATION_VIEW_ENTRY_SCHEMA,
)
from fpbench.storage.eligibility_set_store import EligibilitySetStore
from fpbench.storage.evaluation_view_store import EvaluationViewStore
from fpbench.storage.manifest_store import ManifestStore
from fpbench.storage.plan_schemas import PLANNED_JOB_SCHEMA
from fpbench.storage.plan_store import PlanStore
from fpbench.storage.result_schemas import RAW_RESULT_SCHEMA
from fpbench.storage.result_set_schemas import RESULT_SET_ENTRY_SCHEMA
from fpbench.storage.result_set_store import ResultSetStore
from fpbench.storage.result_store import ResultStore
from fpbench.storage.runtime_bundle_store import RuntimeBundleStore
from fpbench.storage.schemas import (
    IMAGE_SCHEMA,
    PAIR_SCHEMA,
    SELF_ELIGIBILITY_SCHEMA,
    SUBJECT_SCHEMA,
)

__all__ = [
    "DECISION_RECORD_SCHEMA",
    "DecisionSetStore",
    "ELIGIBILITY_RECORD_SCHEMA",
    "EVALUATION_VIEW_ENTRY_SCHEMA",
    "EligibilitySetStore",
    "EvaluationViewStore",
    "IMAGE_SCHEMA",
    "ManifestStore",
    "PAIR_SCHEMA",
    "PLANNED_JOB_SCHEMA",
    "PlanStore",
    "RAW_RESULT_SCHEMA",
    "RESULT_SET_ENTRY_SCHEMA",
    "ResultSetStore",
    "ResultStore",
    "RuntimeBundleStore",
    "SELF_ELIGIBILITY_SCHEMA",
    "SUBJECT_SCHEMA",
]
