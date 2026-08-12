"""The wire format, parsed strictly.

The bridge's output is the only thing standing between VeriFinger and a stored
research result, so nothing here is lenient. A response that is *almost* valid —
a score that is not an integer, an ``extraction_count`` of one, a ``request_id``
belonging to another job, a document carrying both a score and a failure code —
is refused outright rather than repaired.

Two refusals are specific to this route and worth naming.

**A score must be a JSON integer.** VeriFinger returns a Java ``int``; the stored
score is an IEEE double, and the two are the same number only because every
32-bit integer is exactly representable in float64. A response carrying ``2.5``
would mean the bridge had started transforming scores, and every claim this
stage makes about "no transformation by fpbench" would be false
(spec section 11).

**A response may never carry a decision.** ``match``, ``matched``, ``decision``
and ``threshold`` are refused as fields, not ignored. VeriFinger's own sample
sets a threshold of 48 and the bridge preserves that so the official route is
reproduced — but the answer fpbench reads is the integer, and a boolean arriving
alongside it would be an operating point nobody chose (docs/adr/0003,
spec section 10).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from fpbench.core.verifinger_errors import VeriFingerBridgeContractViolation
from fpbench.adapters.verifinger_java import identity

__all__ = [
    "SCHEMA_VERSION",
    "BridgeVersionInfo",
    "BridgeCompareResult",
    "build_compare_request",
    "parse_version_response",
    "parse_compare_response",
    "FORBIDDEN_RESPONSE_FIELDS",
]

SCHEMA_VERSION = "1"

#: Fields a response may never carry, whatever its status. Each of them would be
#: an answer to a question this layer does not ask.
FORBIDDEN_RESPONSE_FIELDS: tuple[str, ...] = (
    "decision",
    "far",
    "is_match",
    "match",
    "matched",
    "probability",
    "threshold",
)

_SUCCESS_FORBIDDEN_FIELDS = ("code", "stage", "side", "exception_type")
_FAILURE_FORBIDDEN_FIELDS = ("score", "extraction_count")


def build_compare_request(
    *,
    request_id: str,
    left_path: Path,
    left_effective_ppi: int,
    right_path: Path,
    right_effective_ppi: int,
) -> str:
    """Serialise a compare request.

    Six fields cross this boundary and there is no seventh. No pair id, no
    subject, no finger position, no release, no protocol stage, no ground truth,
    no threshold, and no other algorithm's score — the request is the narrowest
    thing that can still answer "how similar are these two images?"
    (docs/adr/0010, spec section 5).

    Raises:
        VeriFingerBridgeContractViolation: a path is relative, or a resolution
            is not the 500 ppi this route runs at.
    """
    for label, path in (("left", left_path), ("right", right_path)):
        if not Path(path).is_absolute():
            raise VeriFingerBridgeContractViolation(
                f"{label} path must be absolute, got {path}"
            )
    for label, ppi in (
        ("left", left_effective_ppi),
        ("right", right_effective_ppi),
    ):
        if type(ppi) is not int or ppi != identity.REQUIRED_EFFECTIVE_PPI:
            raise VeriFingerBridgeContractViolation(
                f"{label} effective_ppi must be the integer "
                f"{identity.REQUIRED_EFFECTIVE_PPI}; this route neither resamples "
                f"nor reinterprets a pixel (spec sections 6 and 7), got {ppi!r}"
            )
    return json.dumps(
        {
            "schema_version": SCHEMA_VERSION,
            "request_id": request_id,
            "left_image_path": str(left_path),
            "left_effective_ppi": left_effective_ppi,
            "right_image_path": str(right_path),
            "right_effective_ppi": right_effective_ppi,
        }
    )


@dataclass(frozen=True, slots=True)
class BridgeVersionInfo:
    """What ``VeriFingerBridge version`` reports.

    ``loaded_modules`` maps a module name to the version it declares. It is the
    engine's own inventory, which is what makes "the runtime reported its
    version" true rather than assumed.
    """

    schema_version: str
    bridge_protocol: str
    bridge_version: str
    licences_requested: str
    licences_obtained: bool
    licence_detail: str
    runtime_started: bool
    loaded_modules: Mapping[str, str]
    delivered_runtime_defaults: Mapping[str, str]
    configured_settings: Mapping[str, str]
    java_version: str
    java_vendor: str
    java_vm_name: str
    os_name: str
    os_arch: str
    required_ppi: int
    runtime_detail: str = ""

    @property
    def module_versions(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.loaded_modules.values())))


@dataclass(frozen=True, slots=True)
class BridgeCompareResult:
    """A validated compare response.

    Exactly one of ``score`` and ``code`` is set; that is checked here so no
    caller has to remember to.
    """

    request_id: str
    status: str
    score: int | None = None
    engine_status: str | None = None
    extraction_count: int | None = None
    left_image_ppi: str | None = None
    right_image_ppi: str | None = None
    code: str | None = None
    stage: str | None = None
    side: str | None = None
    message: str | None = None
    exception_type: str | None = None
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


def parse_version_response(payload: str) -> BridgeVersionInfo:
    document = _require_object(payload, "version response")
    _require_envelope(document, "version response")
    modules: dict[str, str] = {}
    for row in document.get("loaded_modules") or ():
        if not isinstance(row, Mapping):
            raise VeriFingerBridgeContractViolation(
                "version response: loaded_modules must hold objects"
            )
        modules[str(row.get("name"))] = str(row.get("version"))
    return BridgeVersionInfo(
        schema_version=str(document["schema_version"]),
        bridge_protocol=str(document["bridge_protocol"]),
        bridge_version=str(document["bridge_version"]),
        licences_requested=str(document.get("licences_requested") or ""),
        licences_obtained=bool(document.get("licences_obtained")),
        licence_detail=str(document.get("licence_detail") or ""),
        runtime_started=bool(document.get("runtime_started")),
        loaded_modules=modules,
        delivered_runtime_defaults=_string_mapping(
            document.get("delivered_runtime_defaults"), "delivered_runtime_defaults"
        ),
        configured_settings=_string_mapping(
            document.get("configured_settings"), "configured_settings"
        ),
        java_version=str(document.get("java_version") or ""),
        java_vendor=str(document.get("java_vendor") or ""),
        java_vm_name=str(document.get("java_vm_name") or ""),
        os_name=str(document.get("os_name") or ""),
        os_arch=str(document.get("os_arch") or ""),
        required_ppi=int(document.get("required_ppi") or 0),
        runtime_detail=str(document.get("runtime_detail") or ""),
    )


def parse_compare_response(
    payload: str, *, expected_request_id: str
) -> BridgeCompareResult:
    """Validate a compare response completely, or refuse it."""
    what = "compare response"
    document = _require_object(payload, what)
    _require_envelope(document, what)

    request_id = str(_require(document, "request_id", what))
    if request_id != expected_request_id:
        # A response from a different job would attach one comparison's score to
        # another's result record.
        raise VeriFingerBridgeContractViolation(
            f"{what}: request_id {request_id!r} does not match the request"
        )

    timings = _parse_timings(document.get("timings_ms"), what)
    status = str(_require(document, "status", what))

    if status == "success":
        _reject_present_fields(document, _SUCCESS_FORBIDDEN_FIELDS, what, status)
        score = _parse_score(_require(document, "score", what), what)
        extraction_count = _require(document, "extraction_count", what)
        if (
            type(extraction_count) is not int
            or extraction_count != identity.REQUIRED_EXTRACTION_COUNT
        ):
            raise VeriFingerBridgeContractViolation(
                f"{what}: extraction_count must be the JSON integer "
                f"{identity.REQUIRED_EXTRACTION_COUNT}, got {extraction_count!r}; "
                "both sides are extracted independently, SELF included"
            )
        engine_status = str(_require(document, "engine_status", what))
        if engine_status not in identity.SCORE_BEARING_STATUSES:
            raise VeriFingerBridgeContractViolation(
                f"{what}: a score was returned under engine status "
                f"{engine_status!r}, and only "
                f"{list(identity.SCORE_BEARING_STATUSES)} carry one"
            )
        direction = str(_require(document, "score_direction", what))
        if direction != identity.SCORE_DIRECTION.value.upper():
            raise VeriFingerBridgeContractViolation(
                f"{what}: score_direction is {direction!r}, expected "
                f"{identity.SCORE_DIRECTION.value.upper()!r}"
            )
        native_type = str(_require(document, "native_score_type", what))
        if native_type != identity.NATIVE_SCORE_TYPE:
            raise VeriFingerBridgeContractViolation(
                f"{what}: native_score_type is {native_type!r}, expected "
                f"{identity.NATIVE_SCORE_TYPE!r}"
            )
        return BridgeCompareResult(
            request_id=request_id,
            status=status,
            score=score,
            engine_status=engine_status,
            extraction_count=extraction_count,
            left_image_ppi=_optional(document, "left_image_ppi"),
            right_image_ppi=_optional(document, "right_image_ppi"),
            timings_ms=timings,
        )

    if status == "failure":
        _reject_present_fields(document, _FAILURE_FORBIDDEN_FIELDS, what, status)
        return BridgeCompareResult(
            request_id=request_id,
            status=status,
            code=str(_require(document, "code", what)),
            stage=str(document.get("stage") or ""),
            side=_optional(document, "side"),
            message=str(document.get("message") or "VeriFinger reported a failure"),
            exception_type=_optional(document, "exception_type"),
            engine_status=_optional(document, "engine_status"),
            timings_ms=timings,
        )

    raise VeriFingerBridgeContractViolation(f"{what}: unknown status {status!r}")


# ----------------------------------------------------------------- internals


def _require_object(payload: str, what: str) -> dict[str, Any]:
    """The last JSON object on stdout, and it must be the only one.

    A native SDK can print to stdout without asking, so the client hands over
    the line it isolated; anything that is not a single JSON object at that
    point is a contract violation rather than something to work around.
    """
    text = (payload or "").strip()
    if not text:
        raise VeriFingerBridgeContractViolation(f"{what}: the bridge produced no output")
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise VeriFingerBridgeContractViolation(
            f"{what}: output is not a single JSON document ({exc.msg})"
        ) from None
    if not isinstance(document, dict):
        raise VeriFingerBridgeContractViolation(f"{what}: expected a JSON object")
    forbidden = sorted(set(document) & set(FORBIDDEN_RESPONSE_FIELDS))
    if forbidden:
        raise VeriFingerBridgeContractViolation(
            f"{what}: the response carries {forbidden}, which this route may "
            "never return; fpbench reads the raw score and applies no operating "
            "point (docs/adr/0003)"
        )
    return document


def _require_envelope(document: Mapping[str, Any], what: str) -> None:
    schema = str(_require(document, "schema_version", what))
    if schema != SCHEMA_VERSION:
        raise VeriFingerBridgeContractViolation(
            f"{what}: unsupported schema_version {schema!r}"
        )
    protocol = str(_require(document, "bridge_protocol", what))
    if protocol != identity.BRIDGE_PROTOCOL:
        raise VeriFingerBridgeContractViolation(
            f"{what}: bridge protocol is {protocol!r}, expected "
            f"{identity.BRIDGE_PROTOCOL!r}"
        )
    version = str(_require(document, "bridge_version", what))
    if version != identity.BRIDGE_VERSION:
        raise VeriFingerBridgeContractViolation(
            f"{what}: bridge version is {version!r}, expected "
            f"{identity.BRIDGE_VERSION!r}"
        )


def _require(document: Mapping[str, Any], key: str, what: str) -> Any:
    if key not in document or document[key] is None:
        raise VeriFingerBridgeContractViolation(f"{what}: missing {key!r}")
    return document[key]


def _optional(document: Mapping[str, Any], key: str) -> str | None:
    value = document.get(key)
    return str(value) if value not in (None, "") else None


def _string_mapping(value: Any, what: str) -> Mapping[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise VeriFingerBridgeContractViolation(f"{what} must be an object")
    return {str(key): str(item) for key, item in value.items()}


def _parse_score(value: Any, what: str) -> int:
    """The score, and it has to be an integer.

    ``type(...) is not int`` rather than ``isinstance``: a JSON ``true`` is an
    ``int`` under ``isinstance`` and would arrive as a score of 1.
    """
    if type(value) is not int:
        raise VeriFingerBridgeContractViolation(
            f"{what}: score must be a JSON integer — VeriFinger returns a Java "
            f"int and fpbench transforms nothing — got {value!r}"
        )
    return value


def _parse_timings(value: Any, what: str) -> dict[str, float]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise VeriFingerBridgeContractViolation(f"{what}: timings_ms must be an object")
    timings: dict[str, float] = {}
    for key, raw in value.items():
        try:
            duration = float(raw)
        except (TypeError, ValueError):
            raise VeriFingerBridgeContractViolation(
                f"{what}: timing {key!r} is not a number"
            ) from None
        if duration != duration or duration in (float("inf"), float("-inf")):
            raise VeriFingerBridgeContractViolation(
                f"{what}: timing {key!r} must be finite"
            )
        if duration < 0:
            raise VeriFingerBridgeContractViolation(
                f"{what}: timing {key!r} must not be negative"
            )
        timings[str(key)] = duration
    return timings


def _reject_present_fields(
    document: Mapping[str, Any],
    forbidden_fields: tuple[str, ...],
    what: str,
    status: str,
) -> None:
    present = [name for name in forbidden_fields if name in document]
    if present:
        raise VeriFingerBridgeContractViolation(
            f"{what}: a {status} response must not contain fields {present!r}"
        )
