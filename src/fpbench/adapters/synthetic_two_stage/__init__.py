"""A two-stage command-line adapter, built only from the shared tools.

This is not a biometric algorithm and it is deliberately **not registered**. It
exists to answer one question before a real second algorithm is attempted: does
the adapter contract already support a route that extracts a template per side,
writes intermediate files, runs a separate matcher, and fails in each of the ways
a two-process pipeline fails — without changing ``SingleJobRunner``, the result
schema, the stores or the evidence chain?

It uses nothing an NBIS adapter could not use: :class:`AdapterJobWorkspace` for
its files, :class:`ExternalCommand` for its processes, the shared runtime guard
for its executables, ``RuntimeBundleStore`` for pinning them, and the same three
methods every other adapter implements (docs/adr/0043).

**No score it produces means anything.** The extractor hashes bytes and the
matcher hashes two hashes.
"""

from __future__ import annotations

from fpbench.adapters.synthetic_two_stage.adapter import (
    ADAPTER_ID,
    ALGORITHM_ID,
    EXTRACTOR_ROLE,
    MATCHER_ROLE,
    SyntheticTwoStageCliAdapter,
)
from fpbench.adapters.synthetic_two_stage.config import SyntheticTwoStageConfig

__all__ = [
    "SyntheticTwoStageCliAdapter",
    "SyntheticTwoStageConfig",
    "ADAPTER_ID",
    "ALGORITHM_ID",
    "EXTRACTOR_ROLE",
    "MATCHER_ROLE",
]
