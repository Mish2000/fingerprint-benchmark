"""Persistence for manifests, run manifests and raw results.

Dependency rule: ``storage`` imports ``core`` and nothing else from the
project. It knows how to write a result; it knows nothing about how one is
produced, and never about a specific adapter (docs/adr/0007).

Decision records and artifact storage arrive with the decision layer and the
first adapter that produces artefacts. The raw-result schema already reserves
the ``artifacts`` column so those references have somewhere to land.
"""

from fpbench.storage.manifest_store import ManifestStore
from fpbench.storage.result_schemas import RAW_RESULT_SCHEMA
from fpbench.storage.result_store import ResultStore
from fpbench.storage.schemas import (
    IMAGE_SCHEMA,
    PAIR_SCHEMA,
    SELF_ELIGIBILITY_SCHEMA,
    SUBJECT_SCHEMA,
)

__all__ = [
    "IMAGE_SCHEMA",
    "ManifestStore",
    "PAIR_SCHEMA",
    "RAW_RESULT_SCHEMA",
    "ResultStore",
    "SELF_ELIGIBILITY_SCHEMA",
    "SUBJECT_SCHEMA",
]
