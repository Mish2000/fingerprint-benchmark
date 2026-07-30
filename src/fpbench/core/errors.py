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
    "RuntimeBundleConflictError",
    "ResultSetConflictError",
    "ImagePreparationError",
    "ExecutionError",
    "PreflightError",
    "ResearchPreflightError",
    "PlanningError",
    "PlanConflictError",
    "RunIntegrityError",
    "IncompleteRunError",
    "RuntimeDriftError",
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


class RuntimeBundleConflictError(StorageError):
    """A different runtime bundle is already stored under this bundle id.

    A bundle id is the first twelve characters of a digest over its assets'
    contents, so this normally means the stored bundle was tampered with or a
    fingerprint rule changed. Never resolved by overwriting: the executable a
    finished run was produced with must stay exactly as it was
    (docs/adr/0018).
    """


class ResultSetConflictError(StorageError):
    """A different result set is already stored under this run.

    Raised when the ordered collection of raw result hashes on disk disagrees
    with the one being written. Two different sets of scores are two different
    result sets, and the second must never be able to overwrite the first
    (docs/adr/0019).
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


class ResearchPreflightError(PreflightError):
    """A research run's provenance preconditions are not met.

    Distinct from an ordinary :class:`PreflightError` because it is never about
    the machine being wrong — it is about the *evidence* being insufficient: an
    uncommitted working tree, a different commit than the run was defined under,
    a dataset whose checksums were never verified. There is no override. Code
    that is not committed cannot be recovered from a receipt written a year
    later, so the fix is to commit it, not to record that it was dirty
    (docs/adr/0017).
    """


class RuntimeDriftError(FpbenchError):
    """The pinned executable changed while a run was using it.

    Deliberately *not* an :class:`ExecutionError` subclass that a runner might
    reasonably record: this is never a comparison failure. A result written
    after the bytes underneath the adapter changed would claim provenance it
    does not have, so this exception is fatal to the whole invocation and must
    reach the caller unrecorded (docs/adr/0018).
    """


class PlanningError(ExecutionError):
    """An execution plan cannot be built from the given inputs.

    Duplicated pairs, or a pair manifest that does not belong to the run.
    Building a plan anyway would produce a run whose results cannot be
    attributed to any particular set of comparisons (docs/adr/0011).
    """


class PlanConflictError(ExecutionError):
    """A different plan is already stored under this run.

    Plans are immutable. Since a run's identity already covers its pair
    manifest, this normally means the stored plan was edited or a fingerprint
    rule changed — never something to resolve by overwriting.
    """


class RunIntegrityError(ExecutionError):
    """Stored results contradict the plan or each other.

    Distinct from a comparison that failed: that is a valid recorded result and
    a run full of them can still be complete (docs/adr/0013). This is a missing
    result, an extra one, a corrupt file, or provenance that does not match —
    conditions under which continuing would mix incomparable results together.
    """


class IncompleteRunError(ExecutionError):
    """An operation needed every planned job to have a result, and some do not."""
