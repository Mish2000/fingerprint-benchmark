"""Shared, experiment-wide image preparation.

Dependency rule: ``imaging`` may import ``core`` and ``storage``, and nothing
else from the project. In particular it must never import ``adapters`` —
algorithm-specific encoding stays inside the adapter that needs it, and a
canonical transformation must be identical for every algorithm evaluated under
it (docs/adr/0007, docs/adr/0031).

The ``storage`` dependency arrived with stage 6A and is deliberate: a
prepared-image set is persistent evidence, and a preparer that could not read
one would have to be handed a hydrated set by every caller.
"""

from fpbench.core.imaging_models import (
    ImageTransformProfile,
    PreparationDefinition,
    PreparationFinalizationMarker,
    PreparationReceipt,
    PreparedImageEntry,
    PreparedImageSetManifest,
    TransformRuntimeManifest,
    canonical_pixel_hash,
    scale_dimension,
)
from fpbench.imaging.base import ImagePreparer
from fpbench.imaging.canonical500 import Canonical500ImagePreparer
from fpbench.imaging.identity import IdentityImagePreparer
from fpbench.imaging.transform_profile import load_transform_profile

__all__ = [
    "Canonical500ImagePreparer",
    "IdentityImagePreparer",
    "ImagePreparer",
    "ImageTransformProfile",
    "PreparationDefinition",
    "PreparationFinalizationMarker",
    "PreparationReceipt",
    "PreparedImageEntry",
    "PreparedImageSetManifest",
    "TransformRuntimeManifest",
    "canonical_pixel_hash",
    "load_transform_profile",
    "scale_dimension",
]
