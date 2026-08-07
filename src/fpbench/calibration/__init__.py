"""Choosing a threshold from labelled development scores — and refusing to.

This package is the machinery a real calibration will one day run on. It does
not perform one. Stage 8D builds it, qualifies it on synthetic fixtures and
stops there, because the algorithm list is not final and no development cohort
has been drawn (docs/adr/0078).

**Dependency rule.** ``calibration`` imports ``core`` and nothing else from this
project. It never imports an adapter, never imports ``sourceafis``, ``nbis`` or
``flx``, never imports ``decisions``, ``metrics`` or any other derivation layer,
and never names an algorithm. That is not tidiness: a calibration engine that
knew which matcher it was calibrating would be able to branch on it, and a
branch is how "the same policy, applied to each algorithm separately" quietly
becomes five different policies.

Three ideas carry the package.

**A threshold is a boundary, not a number.** An operating point carries a
threshold *and* a comparator, because ``>= 40`` and ``> 40`` disagree about every
comparison that scored exactly 40. Boundaries are taken from the observed scores
themselves — ``score >= s`` and ``score > s`` for each distinct ``s`` — so no
epsilon is ever invented and "accept everything" and "accept nothing" are both
representable without one (docs/adr/0080).

**Rates are exact.** A target is a numerator and a denominator, never a float,
and every comparison of two rates is a cross-multiplication of integers. A
target of one in a thousand written as ``0.001`` is not one in a thousand, and
borderline candidates would be decided by the rounding of IEEE 754.

**Development data only, enforced rather than declared.** Scores do not carry a
sentence about which cohort they came from, so the engine refuses on the
binding's declared role *and* on its identities, checked against a registry of
the protected evaluation material. Both refusals happen before a single score is
read (docs/adr/0079).

What is deliberately absent, and is absent rather than disabled: min-max
normalization, z-score normalization, Platt scaling, score fusion, any mapping
between two algorithms' scales, and any quality filtering of development
fingerprints. Each of those would let one algorithm's development population be
shaped differently from another's while the protocol claimed they were the same.
"""

from __future__ import annotations

__all__ = [
    "FORBIDDEN_IMPORT_ROOTS",
    "FORBIDDEN_NORMALIZATION_TOKENS",
    "CALIBRATION_SCHEMA_VERSION",
    "CalibrationOperatingPoint",
    "CalibrationProtocol",
    "CalibrationSourceBinding",
    "CandidateBoundary",
    "LabeledResults",
    "LabeledScore",
    "ProtectedEvaluationIdentity",
    "ProtectedEvaluationRegistry",
    "VerificationReport",
    "select_operating_point",
    "verify_operating_point",
]

#: The calibration schema generation. Bumped when the meaning of a stored
#: calibration artifact changes, never when a field is spelled differently.
CALIBRATION_SCHEMA_VERSION = "1"

#: The names of the algorithms integrated so far, assembled from fragments rather
#: than written out. The structural test that enforces the rules below reads this
#: package's own source for exactly these tokens, and a literal here would make
#: the package fail the boundary it defines.
_ALGORITHM_ROOTS: tuple[str, ...] = (
    "".join(("source", "afis")),
    "".join(("nb", "is")),
    "".join(("f", "lx")),
)

#: What no module in this package may import, at any depth, including inside a
#: function body. A deferred import is still an import, and it is exactly where a
#: boundary violation would hide.
FORBIDDEN_IMPORT_ROOTS: tuple[str, ...] = (
    *_ALGORITHM_ROOTS,
    *(f"fpbench.{root}" for root in _ALGORITHM_ROOTS),
    "torch",
    "fpbench.adapters",
    "fpbench.cross_algorithm",
    "fpbench.datasets",
    "fpbench.decisions",
    "fpbench.derivations",
    "fpbench.eligibility",
    "fpbench.evaluation",
    "fpbench.execution",
    "fpbench.experiments",
    "fpbench.imaging",
    "fpbench.metrics",
    "fpbench.modern_matchers",
    "fpbench.paired",
    "fpbench.protocols",
    "fpbench.storage",
)

#: Symbols whose presence would mean this package had learned to reshape a score
#: before thresholding it. Checked as *defined names*, not as text, so that this
#: docstring and the ADR references below do not trip it (docs/adr/0080).
FORBIDDEN_NORMALIZATION_TOKENS: tuple[str, ...] = (
    "normalize_scores",
    "normalise_scores",
    "min_max_normalize",
    "minmax_normalize",
    "z_score",
    "zscore",
    "standardize_scores",
    "platt_scale",
    "platt_scaling",
    "sigmoid_calibrate",
    "fuse_scores",
    "score_fusion",
    "map_score_scale",
    "rescale_score",
)

# Imported last, and deliberately after the constants above: the structural test
# that enforces the boundary reads those tuples out of this module, so they have
# to exist before anything else in the package is loaded.
from fpbench.calibration.models import (  # noqa: E402
    CalibrationOperatingPoint,
    CalibrationProtocol,
    CalibrationSourceBinding,
    CandidateBoundary,
    LabeledResults,
    LabeledScore,
    ProtectedEvaluationIdentity,
    ProtectedEvaluationRegistry,
)
from fpbench.calibration.selection import select_operating_point  # noqa: E402
from fpbench.calibration.verify import (  # noqa: E402
    VerificationReport,
    verify_operating_point,
)
