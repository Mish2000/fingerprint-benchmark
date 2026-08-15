"""The ``fingerprints-matching`` 0.1.0 adapter.

Importing this package needs neither the frozen runtime nor OpenCV. The adapter
reports its own environment as ``UNAVAILABLE`` when the pinned environment is not
built, so listing the registry stays cheap on a machine that will never run this
algorithm.
"""

from fpbench.adapters.fingerprints_matching.adapter import (
    FingerprintsMatchingAdapter,
)

__all__ = ["FingerprintsMatchingAdapter"]
