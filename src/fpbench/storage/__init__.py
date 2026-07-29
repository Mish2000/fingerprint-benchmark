"""Persistence for manifests and phase-2 SELF eligibility.

Scope note: raw match results, decisions and algorithm artifacts get their own
stores when the runner exists. Their schemas depend on what an adapter actually
returns, and guessing now would lock in the wrong columns. SELF eligibility is
the exception because phase 2 already fixes its per-finger contract and scope.
"""

from fpbench.storage.manifest_store import ManifestStore
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
    "SELF_ELIGIBILITY_SCHEMA",
    "SUBJECT_SCHEMA",
]
