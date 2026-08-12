"""What can go wrong on the VeriFinger route, named.

Two families, and the split is the whole point of the module (docs/adr/0013).

``VeriFingerRuntimeError`` and its siblings mean *the runtime is not the one this
run was defined against*: a missing DLL, a licence that will not be granted, a
model data file that moved, a bridge speaking a protocol this adapter does not
know. None of them is a biometric outcome, none of them may be stored as a
comparison failure, and every one of them ends the run.

``VeriFingerComparisonError`` means *VeriFinger looked at these two images and
produced no score*. A print the extractor rejects for quality, a template with
too few minutiae, an image the media layer cannot decode: those are properties of
fingerprints, they are recorded per pair, and a run full of them is still a run
(spec section 13).

Nothing here is raised across a subprocess boundary. The bridge answers in JSON
and :mod:`fpbench.adapters.verifinger_java.bridge_models` turns that answer into
one of these, so that the classification happens once, in Python, where it can be
tested without a licence.
"""

from __future__ import annotations

from fpbench.core.errors import FpbenchError

__all__ = [
    "VeriFingerError",
    "VeriFingerRuntimeError",
    "VeriFingerRuntimeClosureError",
    "VeriFingerLicenceError",
    "VeriFingerBridgeContractViolation",
    "VeriFingerComparisonError",
    "Stage11BError",
    "Stage11BBindingError",
    "Stage11BSmokeError",
    "Stage11BFinalizationError",
]


class VeriFingerError(FpbenchError):
    """Anything the VeriFinger route can raise."""


# ------------------------------------------------------------- infrastructure


class VeriFingerRuntimeError(VeriFingerError):
    """The runtime is missing, incomplete or not the one that was pinned.

    Never stored as a comparison failure. A run that recorded this per pair
    would publish 6,000 rows that look like biometric findings and are not.
    """


class VeriFingerRuntimeClosureError(VeriFingerRuntimeError):
    """A component of the runtime closure is absent, altered, or unpinned.

    Raised by :mod:`fpbench.experiments.verifinger_runtime_manifest` when a DLL, a jar, a model data
    file or the bridge jar is not the bytes the pinned SDK archive holds.
    """


class VeriFingerLicenceError(VeriFingerRuntimeError):
    """The finger licences were refused.

    A fault of the machine, not of the fingerprint. The adapter reports it as an
    ``UNAVAILABLE`` environment rather than letting a run start and produce
    6,000 identical failures (spec section 18).
    """


class VeriFingerBridgeContractViolation(VeriFingerError):
    """The bridge said something the protocol forbids.

    Deliberately not a runtime error: an unparseable response is this project's
    bug, and the adapter records it as ``INTERNAL_ERROR`` so a single malformed
    answer does not masquerade as an unmatched fingerprint. The result-set
    validator counts it as blocking, so a run containing one cannot be
    published.
    """


# ----------------------------------------------------------------- biometric


class VeriFingerComparisonError(VeriFingerError):
    """VeriFinger produced no score for these two images.

    An algorithm outcome. Recorded, counted and carried into the result set
    without a score beside it — never converted into a zero (spec section 12).
    """


# --------------------------------------------------------------- the stage


class Stage11BError(VeriFingerError):
    """Something is wrong with the Stage 11B evidence chain itself."""


class Stage11BBindingError(Stage11BError):
    """This stage is not bound to the Stage 11A qualification it claims."""


class Stage11BSmokeError(Stage11BError):
    """The production adapter smoke did not establish what it must."""


class Stage11BFinalizationError(Stage11BError):
    """The stage cannot be closed as complete."""
