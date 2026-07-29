"""Exception hierarchy shared by the project.

These are *programming and configuration* errors — conditions under which the
harness cannot proceed. They are deliberately not the vocabulary for biometric
outcomes: an algorithm that fails to extract a template is a recorded result,
not an exception (see docs/adr/0006).
"""

from __future__ import annotations

__all__ = [
    "FpbenchError",
    "ConfigurationError",
    "DatasetError",
    "DatasetLayoutError",
    "ProtocolError",
    "InsufficientCohortError",
    "StorageError",
    "ManifestExistsError",
    "ResultConflictError",
    "ImagePreparationError",
    "ExecutionError",
    "PreflightError",
]


class FpbenchError(Exception):
    """Base class for every error raised by this project."""


class ConfigurationError(FpbenchError):
    """A configuration file is missing, malformed or internally inconsistent."""


class DatasetError(FpbenchError):
    """The dataset on disk does not match what the dataset provider expects."""


class DatasetLayoutError(DatasetError):
    """A required directory or index file is missing from the dataset root."""


class ProtocolError(FpbenchError):
    """The protocol cannot be constructed from the available images."""


class InsufficientCohortError(ProtocolError):
    """Fewer eligible subjects exist than the protocol requires."""


class StorageError(FpbenchError):
    """A manifest or result could not be read or written."""


class ManifestExistsError(StorageError):
    """Refused to overwrite an existing manifest (see docs/adr/0005)."""


class ResultConflictError(StorageError):
    """A stored artefact exists but describes something else.

    Raised when a run manifest or a job result is already on disk under an
    identifier that should have been unique, and its fingerprint disagrees with
    what is being written. Never resolved by overwriting: the correct response
    is a new run, not a lost result (docs/adr/0009).
    """


class ImagePreparationError(FpbenchError):
    """An image could not be made ready for an adapter.

    Raised by an :class:`~fpbench.imaging.base.ImagePreparer`. The runner turns
    it into a recorded ``PREPARATION_FAILED`` result rather than letting it
    abort the run.
    """


class ExecutionError(FpbenchError):
    """A run could not be carried out as defined."""


class PreflightError(ExecutionError):
    """The runner's inputs disagree with the run definition.

    A run-level fault — a mismatched adapter, an unavailable environment, the
    wrong preparer. It must stop the run before any job executes, rather than
    producing thousands of identical per-pair failures.
    """
