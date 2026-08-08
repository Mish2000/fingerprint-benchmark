"""Stage 8E failure vocabulary.

A sibling module rather than an extension of :mod:`fpbench.core.errors`, for the
reason :mod:`fpbench.core.flx_errors` and :mod:`fpbench.core.calibration_errors`
are: Stage 8A's published finalization pins ``core/errors.py`` byte-for-byte
against its verifier commit, so a later stage that added a class to it would turn
a committed evidence gate red. These descend from the same roots, so
``except FpbenchError`` still catches everything.

None of these is a legal conclusion. This project records what upstream terms
*say* and, separately, what it has decided to *do* on one machine; an error here
means one of those two records is missing, malformed, or has been allowed to
stand in for the other (docs/adr/0082).
"""

from __future__ import annotations

from fpbench.core.errors import FpbenchError

__all__ = [
    "ThirdPartyError",
    "ThirdPartyPurposeError",
    "LicenseObservationError",
    "ResearchUseDecisionError",
    "RedistributionError",
    "ThirdPartyUsageError",
    "ThirdPartyArtifactError",
    "UpstreamTransformationError",
    "RepositoryArtifactError",
    "Stage8EFinalizationError",
]


class ThirdPartyError(FpbenchError):
    """A third-party component cannot be used under this project's own policy."""


class ThirdPartyPurposeError(ThirdPartyError):
    """The declared project purpose is missing, altered, or self-contradictory.

    The purpose is the premise every research-use decision is taken under. A
    record that cited a purpose this project has not frozen would be a record
    whose conclusion nobody could reproduce (docs/adr/0081).
    """


class LicenseObservationError(ThirdPartyError):
    """An observation of upstream terms is malformed, or is not an observation.

    Raised when a description of what upstream says carries a conclusion about
    what this project may do, when a status claims a document that was never
    identified, or when conflicting notices are asserted without at least two
    notices to conflict (docs/adr/0082).
    """


class ResearchUseDecisionError(ThirdPartyError):
    """A research-use decision does not follow from the observation it cites.

    Never raised because the answer was inconvenient. Raised when the decision
    and its basis disagree: ``BLOCKED`` with no blocker named, ``OWNER_RISK_``
    ``ACCEPTED`` without every condition met, or a dataset waved through by a
    policy that was written for software (docs/adr/0084).
    """


class RedistributionError(ThirdPartyError):
    """A redistribution record claims something this project does not do.

    ``redistributed_by_fpbench`` is ``False`` everywhere and there is no code
    path that can set it otherwise, so this is what a caller gets for trying
    (docs/adr/0083).
    """


class ThirdPartyUsageError(ThirdPartyError):
    """A usage record does not bind one component to one observation and one decision."""


class ThirdPartyArtifactError(ThirdPartyError):
    """A third-party artifact is described by a path instead of by an identity.

    The repository names roles, digests, sizes and upstream identities. An
    absolute path names one machine, and a manifest that carried one would be a
    manifest that only worked there (docs/adr/0083).
    """


class UpstreamTransformationError(ThirdPartyError):
    """A change to upstream source is not expressed as a reproducible recipe."""


class RepositoryArtifactError(ThirdPartyError):
    """Third-party bytes are tracked in Git, or would be.

    The repository is public. ``.gitignore`` is a convenience and this is the
    enforcement: the guard reads what Git actually tracks (docs/adr/0083).
    """


class Stage8EFinalizationError(ThirdPartyError):
    """The Stage 8E evidence chain is incomplete or no longer verifies."""
