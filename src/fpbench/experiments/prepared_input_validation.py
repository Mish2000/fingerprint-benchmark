"""What every result of a run over a materialised input set must claim.

None of this is about an algorithm. "The stored result names an artefact that
exists in this exact prepared-image set, with this width, this height, this file
digest and this raster digest" is the same question whether the comparison was
carried out by SourceAFIS, by a two-executable pipeline, or by something that has
not been written yet — and answering it twice, once per algorithm, is how the two
answers eventually diverge.

So the expectations live here, in a module no algorithm owns.

The model was called ``CanonicalPreparationExpectations`` while there was exactly
one canonical profile to expect. The name is kept as an alias — imports that use
it keep working, and the stage 6A code reads the same — but the honest name is
:class:`PreparedInputExpectations`: it describes any materialised input set, and
the canonical-500 profile is one instance of one (spec section 25).

Present for a run over a prepared set and ``None`` for a run over the delivered
bytes. That asymmetry is deliberate rather than a gap: the identity preparer
materialises nothing, so there is no set for its results to be checked against,
and inventing one would make thousands of already-stored results fail a check
they were never subject to (spec section 61).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from fpbench.core.identifiers import ImageId
from fpbench.core.imaging_models import PreparedImageEntry

__all__ = [
    "PreparedInputExpectations",
    "CanonicalPreparationExpectations",
]


@dataclass(frozen=True, slots=True)
class PreparedInputExpectations:
    """The input-set identity every result of one run has to agree with.

    Holding the entry index here is what turns "the result says it used prepared
    pixels" into "the result names an artefact that exists in this exact set,
    with this width, this height, this file digest and this raster digest"
    (spec section 75).
    """

    execution_profile_id: str
    preparer_id: str
    preparer_version: str
    runner_metadata_schema: str

    preparation_set_id: str
    preparation_set_fingerprint: str

    transform_profile_id: str
    transform_profile_fingerprint: str
    transform_runtime_fingerprint: str

    target_ppi: int

    entries: Mapping[ImageId, PreparedImageEntry]

    #: Which source resolution each release is entitled to have been scaled
    #: from. Empty disables the release-aware check, which is what a synthetic
    #: world with invented release names wants.
    expected_source_ppi: Mapping[str, int] = field(default_factory=dict)

    def run_level_metadata(self) -> Mapping[str, str]:
        """The runner-metadata keys that are the same for every comparison."""
        return {
            "preparer_id": self.preparer_id,
            "preparer_version": self.preparer_version,
            "runner_metadata_schema": self.runner_metadata_schema,
            "preparation_set_id": self.preparation_set_id,
            "preparation_set_fingerprint": self.preparation_set_fingerprint,
            "transform_profile_id": self.transform_profile_id,
            "transform_profile_fingerprint": self.transform_profile_fingerprint,
            "transform_runtime_fingerprint": self.transform_runtime_fingerprint,
        }


#: The name this model had while only one profile used it. Same class, so
#: ``isinstance`` and equality behave as they always did.
CanonicalPreparationExpectations = PreparedInputExpectations
