"""SourceAFIS for Java, 3.18.1, behind a stateless subprocess bridge.

The project's first real biometric integration. Everything Java-specific stops at
this package boundary: nothing above it knows that a JVM is involved
(docs/adr/0007, docs/adr/0015).
"""

from fpbench.adapters.sourceafis_java.adapter import (
    ADAPTER_ID,
    ALGORITHM_ID,
    PIPELINE_METADATA,
    SourceAfisJavaAdapter,
)
from fpbench.adapters.sourceafis_java.config import SourceAfisJavaConfig

__all__ = [
    "ADAPTER_ID",
    "ALGORITHM_ID",
    "PIPELINE_METADATA",
    "SourceAfisJavaAdapter",
    "SourceAfisJavaConfig",
]
