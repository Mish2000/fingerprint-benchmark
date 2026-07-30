"""The wire format, parsed strictly.

The bridge's output is the only thing standing between SourceAFIS and a stored
research result, so nothing here is lenient. A response that is *almost* valid — a
score that is negative, an ``extraction_count`` of 1, a ``request_id`` belonging to
some other job — is refused outright rather than repaired, because every one of
those means something upstream is not doing what this adapter claims it does.

Accepting an almost-valid response is how a benchmark ends up reporting numbers
whose provenance nobody can reconstruct.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from fpbench.core.serialization import freeze_str_mapping

__all__ = [
    "BridgeContractViolation",
    "BridgeVersionInfo",
    "BridgeCompareResult",
    "SCHEMA_VERSION",
    "build_compare_request",
    "parse_version_response",
    "parse_compare_response",
]

SCHEMA_VERSION = "1"

#: The bridge always extracts both sides independently, so anything else means the
#: template-reuse prohibition has been broken somewhere (docs/adr/0016).
REQUIRED_EXTRACTION_COUNT = 2

_TIMING_KEYS_SUCCESS = ("bridge_total",)


class BridgeContractViolation(Exception):
    """The bridge said something the protocol does not allow.

    Mapped by the adapter to ``INTERNAL_ERROR`` with
    ``details.kind = bridge_contract_violation``. Never to a biometric failure code:
    a broken bridge is our bug, not an unmatched fingerprint.
    """


def build_compare_request(
    *, request_id: str, left_path: Path, left_dpi: int, right_path: Path, right_dpi: int
) -> str:
    """Serialise a compare request.

    Only paths and resolutions cross this boundary. No pair id, no subject, no
    finger, no stage, no ground truth, no threshold — the request is the narrowest
    thing that can still answer "how similar are these two images?"
    (docs/adr/0010).
    """
    for label, path in (("left", left_path), ("right", right_path)):
        if not Path(path).is_absolute():
            raise BridgeContractViolation(f"{label} path must be absolute, got {path}")
    for label, dpi in (("left", left_dpi), ("right", right_dpi)):
        if not isinstance(dpi, int) or dpi <= 0:
            raise BridgeContractViolation(
                f"{label} dpi must be a positive integer, got {dpi!r}"
            )

    return json.dumps(
        {
            "schema_version": SCHEMA_VERSION,
            "request_id": request_id,
            "left": {"path": str(left_path), "dpi": left_dpi},
            "right": {"path": str(right_path), "dpi": right_dpi},
        }
    )


@dataclass(frozen=True, slots=True)
class BridgeVersionInfo:
    """What ``java -jar bridge.jar version`` reports."""

    schema_version: str
    bridge_version: str
    bridge_protocol: str
    sourceafis_version: str
    java_version: str
    java_vendor: str
    java_vm_name: str
    os_name: str
    os_arch: str


@dataclass(frozen=True, slots=True)
class BridgeCompareResult:
    """A validated compare response.

    Exactly one of ``score`` and ``code`` is set. That is checked here so no caller
    has to remember to.
    """

    request_id: str
    status: str
    sourceafis_version: str
    bridge_version: str
    score: float | None = None
    code: str | None = None
    stage: str | None = None
    side: str | None = None
    message: str | None = None
    exception_type: str | None = None
    extraction_count: int | None = None
    timings_ms: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "timings_ms",
            {str(k): float(v) for k, v in dict(self.timings_ms).items()},
        )

    @property
    def succeeded(self) -> bool:
        return self.status == "success"


def _require_object(payload: str, what: str) -> dict[str, Any]:
    text = (payload or "").strip()
    if not text:
        raise BridgeContractViolation(f"{what}: the bridge produced no output")
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        # A second document, a stray print, truncated output — all land here.
        raise BridgeContractViolation(
            f"{what}: output is not a single JSON document ({exc.msg})"
        ) from None
    if not isinstance(document, dict):
        raise BridgeContractViolation(f"{what}: expected a JSON object")
    return document


def _require(document: Mapping[str, Any], key: str, what: str) -> Any:
    if key not in document or document[key] is None:
        raise BridgeContractViolation(f"{what}: missing {key!r}")
    return document[key]


def parse_version_response(payload: str) -> BridgeVersionInfo:
    document = _require_object(payload, "version response")
    schema = str(_require(document, "schema_version", "version response"))
    if schema != SCHEMA_VERSION:
        raise BridgeContractViolation(
            f"version response: unsupported schema_version {schema!r}"
        )
    return BridgeVersionInfo(
        schema_version=schema,
        bridge_version=str(_require(document, "bridge_version", "version response")),
        bridge_protocol=str(_require(document, "bridge_protocol", "version response")),
        sourceafis_version=str(
            _require(document, "sourceafis_version", "version response")
        ),
        java_version=str(document.get("java_version", "")),
        java_vendor=str(document.get("java_vendor", "")),
        java_vm_name=str(document.get("java_vm_name", "")),
        os_name=str(document.get("os_name", "")),
        os_arch=str(document.get("os_arch", "")),
    )


def parse_compare_response(
    payload: str,
    *,
    expected_request_id: str,
    expected_sourceafis_version: str,
    expected_bridge_version: str,
) -> BridgeCompareResult:
    """Validate a compare response completely, or refuse it."""
    what = "compare response"
    document = _require_object(payload, what)

    schema = str(_require(document, "schema_version", what))
    if schema != SCHEMA_VERSION:
        raise BridgeContractViolation(f"{what}: unsupported schema_version {schema!r}")

    request_id = str(_require(document, "request_id", what))
    if request_id != expected_request_id:
        # A response from a different job would attach one comparison's score to
        # another's result record.
        raise BridgeContractViolation(
            f"{what}: request_id {request_id!r} does not match the request"
        )

    sourceafis_version = str(_require(document, "sourceafis_version", what))
    if sourceafis_version != expected_sourceafis_version:
        raise BridgeContractViolation(
            f"{what}: SourceAFIS reported {sourceafis_version!r}, expected "
            f"{expected_sourceafis_version!r}"
        )
    bridge_version = str(_require(document, "bridge_version", what))
    if bridge_version != expected_bridge_version:
        raise BridgeContractViolation(
            f"{what}: bridge reported version {bridge_version!r}, expected "
            f"{expected_bridge_version!r}"
        )

    timings = _parse_timings(document.get("timings_ms"), what)
    status = str(_require(document, "status", what))

    if status == "success":
        score = _parse_score(_require(document, "score", what), what)
        extraction_count = int(_require(document, "extraction_count", what))
        if extraction_count != REQUIRED_EXTRACTION_COUNT:
            raise BridgeContractViolation(
                f"{what}: extraction_count is {extraction_count}, expected "
                f"{REQUIRED_EXTRACTION_COUNT}; both sides must be extracted "
                f"independently"
            )
        for key in _TIMING_KEYS_SUCCESS:
            if key not in timings:
                raise BridgeContractViolation(f"{what}: missing timing {key!r}")
        return BridgeCompareResult(
            request_id=request_id,
            status=status,
            score=score,
            sourceafis_version=sourceafis_version,
            bridge_version=bridge_version,
            extraction_count=extraction_count,
            timings_ms=timings,
        )

    if status == "failure":
        if document.get("score") is not None:
            raise BridgeContractViolation(f"{what}: a failure must not carry a score")
        return BridgeCompareResult(
            request_id=request_id,
            status=status,
            sourceafis_version=sourceafis_version,
            bridge_version=bridge_version,
            code=str(_require(document, "code", what)),
            stage=str(document.get("stage") or ""),
            side=(str(document["side"]) if document.get("side") else None),
            message=str(document.get("message") or "SourceAFIS reported a failure"),
            exception_type=(
                str(document["exception_type"]) if document.get("exception_type") else None
            ),
            timings_ms=timings,
        )

    raise BridgeContractViolation(f"{what}: unknown status {status!r}")


def _parse_score(value: Any, what: str) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        raise BridgeContractViolation(f"{what}: score is not a number") from None
    if not math.isfinite(score):
        raise BridgeContractViolation(f"{what}: score is not finite")
    if score < 0:
        # SourceAFIS documents a non-negative, higher-is-better similarity. A
        # negative number means that assumption no longer holds, and every stored
        # score direction would be wrong.
        raise BridgeContractViolation(f"{what}: score is negative ({score})")
    return score


def _parse_timings(value: Any, what: str) -> dict[str, float]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise BridgeContractViolation(f"{what}: timings_ms must be an object")
    timings: dict[str, float] = {}
    for key, raw in value.items():
        try:
            duration = float(raw)
        except (TypeError, ValueError):
            raise BridgeContractViolation(
                f"{what}: timing {key!r} is not a number"
            ) from None
        if not math.isfinite(duration) or duration < 0:
            raise BridgeContractViolation(
                f"{what}: timing {key!r} must be finite and non-negative"
            )
        timings[str(key)] = duration
    return timings


def frozen_metadata(values: Mapping[str, str]) -> Mapping[str, str]:
    return freeze_str_mapping(values)
