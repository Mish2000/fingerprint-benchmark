"""The subprocess that runs ``fingerprints-matching`` 0.1.0, and nothing else.

This file executes inside the frozen runtime environment — the pinned
interpreter, the pinned numpy, the pinned OpenCV — and it never imports fpbench.
That separation is the whole point: the algorithm's numpy is not the benchmark's
numpy, and neither one can move the other.

**It calls the top-level upstream entry point and it does not reimplement it.**
``FingerprintsMatching.fingerprints_matching(image_path1, image_path2)`` performs
its own decode, its own greyscale conversion, its own Otsu threshold, its own two
feature extractions and its own match. Nothing here crops, resizes, segments,
enhances, aligns, thresholds or transforms a score, and nothing here reaches into
``minutiae_matching`` to assemble a route of its own.

Protocol: one JSON request per line on stdin, one JSON response per line on
stdout. Three response shapes and no fourth:

.. code-block:: text

    {"status": "score", "score": <float>, "score_hex": "0x..."}
        upstream returned a finite number

    {"status": "algorithmic_failure", "code": ..., "exception_type": ...}
        upstream raised while processing the prints it was handed

    {"status": "infrastructure_failure", "code": ..., ...}
        something that is not a statement about a fingerprint

The split between the last two is the one thing this file exists to get right. An
exception raised *inside* the upstream call is the algorithm declining the print
it was given: a contour it cannot take convexity defects from, an image it cannot
decode, a feature set with nothing in it to divide by. Those are properties of
real fingerprints, they are deterministic, and they are counted. Everything else
— a broken import, a request that is not a request, a response that is not a
number — is the machine being wrong, and it stops the run.

**An exception is never a score of zero.** Zero is a real value this matcher can
return, for two prints whose minutiae never fall within tolerance of each other,
and conflating it with "did not run" would put a fabricated similarity into the
benchmark.
"""

from __future__ import annotations

import json
import math
import sys
import time
import traceback
from typing import Any

PROTOCOL_VERSION = "stage15a_fingerprints_matching_bridge_v1"

#: Filled in at import. An import failure here is an infrastructure failure for
#: every subsequent request rather than a crash without an explanation.
_IMPORT_ERROR: str | None = None

try:
    import cv2
    import numpy
    from fingerprints_matching.fingerprints_matching import FingerprintsMatching
except Exception as exc:  # noqa: BLE001 - reported, not raised
    _IMPORT_ERROR = f"{type(exc).__name__}: {exc}"
    cv2 = None  # type: ignore[assignment]
    numpy = None  # type: ignore[assignment]
    FingerprintsMatching = None  # type: ignore[assignment]


def _describe(exc: BaseException) -> dict[str, Any]:
    """A publication-safe description of an exception: no traceback, no paths."""
    module = type(exc).__module__
    name = type(exc).__name__
    message = str(exc).strip()
    if message:
        # OpenCV messages embed the build machine's source paths. Keep the last
        # line, which carries the reason, and drop the rest.
        message = message.splitlines()[-1].strip()
    return {
        "exception_type": f"{module}.{name}" if module != "builtins" else name,
        "message": message[:400] or "(no message)",
    }


def _failure_code(exc: BaseException) -> str:
    """Name the upstream refusal without interpreting it as a similarity."""
    module = type(exc).__module__
    name = type(exc).__name__
    if name == "ZeroDivisionError":
        # ``match`` divides by len(minutiae1). No features on the first side.
        return "NO_FEATURES_ON_FIRST_SIDE"
    if module.startswith("cv2"):
        text = str(exc)
        if "monotonous" in text or "convexityDefects" in text:
            return "CONVEXITY_DEFECTS_REFUSED_CONTOUR"
        if "cvtColor" in text or "!_src.empty()" in text:
            return "IMAGE_NOT_DECODABLE"
        return "OPENCV_REFUSED_INPUT"
    return "UPSTREAM_RAISED"


def _environment() -> dict[str, Any]:
    import platform

    try:
        from importlib.metadata import version

        opencv_distribution = version("opencv-python")
    except Exception:  # noqa: BLE001
        opencv_distribution = None

    # ``opencv-python`` the distribution and ``cv2`` the library carry different
    # version strings for the same install. Both are reported so neither can be
    # quietly substituted for the other.
    return {
        "protocol": PROTOCOL_VERSION,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "numpy": getattr(numpy, "__version__", None),
        "opencv": opencv_distribution,
        "cv2_library": getattr(cv2, "__version__", None),
        "import_error": _IMPORT_ERROR,
    }


def _compare(left: str, right: str) -> dict[str, Any]:
    """One comparison, through the top-level upstream entry point."""
    started = time.perf_counter()
    try:
        value = FingerprintsMatching.fingerprints_matching(left, right)
    except Exception as exc:  # noqa: BLE001 - this is the algorithmic path
        elapsed = (time.perf_counter() - started) * 1000.0
        return {
            "status": "algorithmic_failure",
            "code": _failure_code(exc),
            "elapsed_ms": elapsed,
            **_describe(exc),
        }
    elapsed = (time.perf_counter() - started) * 1000.0

    # The value upstream builds is a numpy scalar, because every arithmetic step
    # in ``match_score`` runs through numpy. ``numpy.float64`` is a subclass of
    # ``float`` and holds the same IEEE double, so widening it to a Python float
    # is a type normalisation and not a score transformation — the bits do not
    # move. ``score_hex`` carries them exactly, so the determinism checks compare
    # values rather than decimal renderings.
    if not isinstance(value, (float, int)) or isinstance(value, bool):
        return {
            "status": "infrastructure_failure",
            "code": "SCORE_IS_NOT_A_NUMBER",
            "observed_type": type(value).__name__,
        }
    score = float(value)
    if not math.isfinite(score):
        return {
            "status": "infrastructure_failure",
            "code": "SCORE_IS_NOT_FINITE",
            "observed_repr": repr(value)[:80],
        }
    return {
        "status": "score",
        "score": score,
        "score_hex": score.hex(),
        "native_type": type(value).__name__,
        "elapsed_ms": elapsed,
    }


def _handle(request: Any) -> dict[str, Any]:
    if _IMPORT_ERROR is not None:
        return {
            "status": "infrastructure_failure",
            "code": "RUNTIME_IMPORT_FAILED",
            "message": _IMPORT_ERROR,
        }
    if not isinstance(request, dict):
        return {
            "status": "infrastructure_failure",
            "code": "MALFORMED_REQUEST",
            "message": "a request must be a JSON object",
        }
    op = request.get("op")
    if op == "environment":
        return {"status": "environment", **_environment()}
    if op != "compare":
        return {
            "status": "infrastructure_failure",
            "code": "UNKNOWN_OPERATION",
            "message": f"unknown op {op!r}",
        }
    left, right = request.get("left"), request.get("right")
    if not isinstance(left, str) or not isinstance(right, str):
        return {
            "status": "infrastructure_failure",
            "code": "MALFORMED_REQUEST",
            "message": "compare needs string 'left' and 'right' paths",
        }
    return _compare(left, right)


def main() -> int:
    for line in sys.stdin:
        # A byte-order mark ahead of the first request is a property of whoever
        # wrote the pipe, not of the request. Strip it rather than reporting the
        # first comparison of a run as malformed.
        line = line.lstrip("﻿").strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            response: dict[str, Any] = {
                "status": "infrastructure_failure",
                "code": "MALFORMED_REQUEST",
                "message": f"not JSON: {exc}",
            }
        else:
            try:
                response = _handle(request)
            except Exception:  # noqa: BLE001 - a bug in this file, not in upstream
                response = {
                    "status": "infrastructure_failure",
                    "code": "BRIDGE_INTERNAL_ERROR",
                    "message": traceback.format_exc(limit=1).splitlines()[-1][:200],
                }
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
