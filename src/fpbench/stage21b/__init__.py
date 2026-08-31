"""Stage 21B: frozen, raw-only cross-subject execution.

This package is intentionally upstream of every evaluation package.  It can
produce and prove raw terminal outcomes; it cannot decide what a score means.
"""

from fpbench.stage21b.errors import (
    Stage21BError,
    Stage21BInfrastructureInterruption,
    Stage21BIntegrityError,
    Stage21BPreflightError,
    Stage21BStoreConflict,
)
from fpbench.stage21b.models import (
    FrozenRunSpec,
    PlannedPair,
    PreparationReference,
    Stage21BOutcomeStatus,
    TerminalOutcome,
)

__all__ = [
    "FrozenRunSpec",
    "PlannedPair",
    "PreparationReference",
    "Stage21BError",
    "Stage21BInfrastructureInterruption",
    "Stage21BIntegrityError",
    "Stage21BOutcomeStatus",
    "Stage21BPreflightError",
    "Stage21BStoreConflict",
    "TerminalOutcome",
]
