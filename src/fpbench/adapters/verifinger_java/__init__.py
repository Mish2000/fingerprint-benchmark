"""VeriFinger 2025.2 behind the ordinary adapter contract.

Nothing in this package knows what a pair is, what a protocol stage is, or that
three other algorithms have already run over the same images. It receives two
prepared images and returns a raw score or a structured failure — the same three
methods SourceAFIS and NBIS enter through (docs/adr/0007).
"""

from __future__ import annotations

from fpbench.adapters.verifinger_java.adapter import VeriFingerJavaAdapter
from fpbench.adapters.verifinger_java.config import (
    BRIDGE_JAR_ROLE,
    RUNTIME_ASSET_ROLES,
    RUNTIME_MANIFEST_ROLE,
    RUNTIME_POLICY_ROLE,
    VeriFingerJavaConfig,
)

__all__ = [
    "VeriFingerJavaAdapter",
    "VeriFingerJavaConfig",
    "BRIDGE_JAR_ROLE",
    "RUNTIME_MANIFEST_ROLE",
    "RUNTIME_POLICY_ROLE",
    "RUNTIME_ASSET_ROLES",
]
