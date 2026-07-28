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
