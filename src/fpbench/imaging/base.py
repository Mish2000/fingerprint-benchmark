"""The contract for turning a catalogued image into adapter input.

A preparer answers one question: *given this record and this execution profile,
what exactly does the adapter receive?* It never chooses which images to
compare, never applies a threshold and never knows which algorithm will consume
its output.

Preparation is where the shared, experiment-wide transformations belong —
resolution changes, colour depth, format conversion — as opposed to the
algorithm-specific encoding an adapter does for itself. In stage 3A only the
identity preparer exists, which does nothing at all; the split matters anyway,
because the moment a real transform arrives it must land on this side of the
line rather than being reimplemented inside each adapter (docs/adr/0004).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from fpbench.core.execution_models import ExecutionProfile, PreparedImage
from fpbench.core.models import ImageRecord

__all__ = ["ImagePreparer"]


class ImagePreparer(ABC):
    """Produces the concrete input an adapter will be handed."""

    @property
    @abstractmethod
    def preparer_id(self) -> str:
        """Stable identifier, referenced by ``ExecutionProfile.preparer_id``."""

    @abstractmethod
    def prepare(
        self,
        image: ImageRecord,
        dataset_root: Path,
        profile: ExecutionProfile,
    ) -> PreparedImage:
        """Make ``image`` ready for comparison under ``profile``.

        Raises:
            ImagePreparationError: when the image cannot be prepared. The
                runner records that as a ``PREPARATION_FAILED`` result rather
                than letting it abort the run.
        """
