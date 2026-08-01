"""Compatibility import path for the shared runtime guard.

The guard was never SourceAFIS-specific — it watches a file, not a jar — and
stage 7A moved it to :mod:`fpbench.adapters.support.runtime_guard` so a
two-executable adapter can watch both of its tools with the same code
(docs/adr/0042).

This module stays because imports elsewhere name it, and because breaking an
import path is a change to code that already works. Everything here is the same
object as its counterpart in ``support``; there is no second implementation.
"""

from __future__ import annotations

from fpbench.adapters.support.runtime_guard import (
    FileIdentity,
    require_runtime_assets_unchanged,
    require_unchanged,
    snapshot_file_identity,
    snapshot_runtime_assets,
)

__all__ = [
    "FileIdentity",
    "snapshot_file_identity",
    "require_unchanged",
    "snapshot_runtime_assets",
    "require_runtime_assets_unchanged",
]
