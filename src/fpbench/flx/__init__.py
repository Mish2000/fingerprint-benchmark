"""Stage 8B: the flx learned-representation route, and what qualifies it.

This package owns one third-party inference route end to end — pinned source,
pinned checkpoint, a fixed transform from a canonical gray8 PNG, a fixed-length
representation, and a raw similarity score — plus the qualification that
decides whether the route may be executed at benchmark scale at all.

It deliberately knows nothing about pairs, subjects, labels, thresholds,
decisions or the other two algorithms.  It takes image bytes and returns a
representation or a score.
"""

from fpbench.flx.identity import (
    ADAPTER_ID,
    ADAPTER_VERSION,
    ALGORITHM_ID,
    PREPROCESSING_PROFILE_ID,
    QUALIFICATION_PROTOCOL_ID,
    REPRESENTATION_PROFILE_ID,
    RUNTIME_POLICY_ID,
    RUNTIME_PROFILE_ID,
    SCORE_PROFILE_ID,
    SCORE_SERIALIZATION_PROFILE_ID,
    STAGE8B_SCHEMA_VERSION,
)
from fpbench.flx.policy import load_runtime_policy

__all__ = [
    "ADAPTER_ID",
    "ADAPTER_VERSION",
    "ALGORITHM_ID",
    "PREPROCESSING_PROFILE_ID",
    "QUALIFICATION_PROTOCOL_ID",
    "REPRESENTATION_PROFILE_ID",
    "RUNTIME_POLICY_ID",
    "RUNTIME_PROFILE_ID",
    "SCORE_PROFILE_ID",
    "SCORE_SERIALIZATION_PROFILE_ID",
    "STAGE8B_SCHEMA_VERSION",
    "load_runtime_policy",
]
