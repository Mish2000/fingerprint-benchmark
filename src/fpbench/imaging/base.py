"""The contract for turning a catalogued image into adapter input.

A preparer answers one question: *given this record and this execution profile,
what exactly does the adapter receive?* It never chooses which images to
compare, never applies a threshold and never knows which algorithm will consume
its output.

Preparation is where the shared, experiment-wide transformations belong —
resolution changes, colour depth, format conversion — as opposed to the
algorithm-specific encoding an adapter does for itself. That split is the whole
of docs/adr/0031: two matchers compared under ``canonical_500`` are handed
artefacts from one immutable set, so a matcher cannot advantage itself with a
better downsampler and a comparison between matchers stays a comparison between
matchers.

**Preparers describe their own provenance.** ``run_metadata`` and
``side_metadata`` are how a canonical run's results come to carry a preparation
set id, two entry hashes and two pixel digests without the runner knowing what a
preparation set is. The runner prefixes the per-side keys with ``left_`` and
``right_`` and stores the lot; it does not interpret any of it, and there is no
``if resolution_mode == ...`` anywhere downstream of here (docs/adr/0007).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Mapping

from fpbench.core.execution_models import ExecutionProfile, PreparedImage
from fpbench.core.models import ImageRecord

__all__ = ["ImagePreparer"]


class ImagePreparer(ABC):
    """Produces the concrete input an adapter will be handed."""

    @property
    @abstractmethod
    def preparer_id(self) -> str:
        """Stable identifier, referenced by ``ExecutionProfile.preparer_id``."""

    @property
    def preparer_version(self) -> str:
        """Bumped when the meaning of this preparer's output changes.

        Recorded on every result, so a bump makes results produced before and
        after visibly different rather than silently incomparable.
        """
        return "1"

    @property
    def runner_metadata_schema(self) -> str:
        """Which set of keys :meth:`run_metadata` and :meth:`side_metadata` fill.

        Versioned so a validator can require *every* field of a known schema
        instead of accepting whatever happens to be present (spec section 63).
        """
        return "identity_preparation_v1"

    def run_metadata(self) -> Mapping[str, str]:
        """Provenance that is the same for every comparison in a run.

        The transform profile, the runtime, the preparation set — facts about
        the input set rather than about either side of one pair.
        """
        return {}

    def side_metadata(self, prepared: PreparedImage) -> Mapping[str, str]:
        """Provenance about one prepared image.

        The runner stores these twice, prefixed ``left_`` and ``right_``. Keys
        must therefore be free of any such prefix themselves.
        """
        return {}

    def preflight(self) -> None:
        """Prove this preparer can serve a whole run, before any job starts.

        The default does nothing. A preparer backed by an immutable set uses it
        to verify that set once, so that a missing artefact is one fault of the
        run rather than six thousand identical per-pair failures
        (spec section 56).

        Raises:
            PreflightError: the preparer cannot serve this run.
        """

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
            PreparedImageDriftError: when an artefact this preparer already
                verified has changed underneath it. Fatal to the invocation and
                deliberately *not* recorded as a pair failure (docs/adr/0033).
        """
