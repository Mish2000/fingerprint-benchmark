"""Shared, experiment-wide image preparation.

Dependency rule: ``imaging`` may import ``core`` and nothing else from the
project. In particular it must never import ``adapters`` — algorithm-specific
encoding stays inside the adapter that needs it (docs/adr/0007).
"""

from fpbench.imaging.base import ImagePreparer
from fpbench.imaging.identity import IdentityImagePreparer

__all__ = ["IdentityImagePreparer", "ImagePreparer"]
