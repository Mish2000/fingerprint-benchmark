"""Failures with distinct operational meanings in Stage 21B."""


class Stage21BError(RuntimeError):
    """Base class for a Stage 21B refusal."""


class Stage21BPreflightError(Stage21BError):
    """No matcher invocation may begin under the observed inputs/runtime."""


class Stage21BIntegrityError(Stage21BError):
    """Stored or frozen material contradicts its own identity."""


class Stage21BStoreConflict(Stage21BIntegrityError):
    """An existing logical run may not be silently replaced."""


class Stage21BInfrastructureInterruption(Stage21BError):
    """The pair remains pending because no biometric terminal outcome exists."""


class Stage21BSealedError(Stage21BStoreConflict):
    """A sealed result set is immutable."""
