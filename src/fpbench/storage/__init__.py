"""Persistence for manifests.

Scope note: raw match results, decisions and algorithm artifacts get their own
stores when the runner exists. Their schemas depend on what an adapter actually
returns, and guessing now would lock in the wrong columns.
"""

from fpbench.storage.manifest_store import ManifestStore
from fpbench.storage.schemas import IMAGE_SCHEMA, PAIR_SCHEMA, SUBJECT_SCHEMA

__all__ = ["IMAGE_SCHEMA", "ManifestStore", "PAIR_SCHEMA", "SUBJECT_SCHEMA"]
