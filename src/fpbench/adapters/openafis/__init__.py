"""The MINDTCT -> OpenAFIS route: Algorithm 5.

Shares its extractor with Algorithm 2 and differs only in the matcher, which is
what makes the pair a controlled matcher comparison — and what has to be said out
loud rather than presented as two independent systems.
"""

from fpbench.adapters.openafis.adapter import (
    ADAPTER_ID,
    ADAPTER_VERSION,
    ALGORITHM_ID,
    IMPLEMENTATION_VERSION,
    OpenAfisAdapter,
)
from fpbench.adapters.openafis.config import OpenAfisConfig
from fpbench.adapters.openafis.translation import (
    MINUTIA_TYPE_POLICY,
    TranslationRefused,
    translate_xyt_to_openafis_csv,
)

__all__ = [
    "OpenAfisAdapter",
    "OpenAfisConfig",
    "ALGORITHM_ID",
    "ADAPTER_ID",
    "ADAPTER_VERSION",
    "IMPLEMENTATION_VERSION",
    "MINUTIA_TYPE_POLICY",
    "TranslationRefused",
    "translate_xyt_to_openafis_csv",
]
