"""The bounded qualification run, and the engine contract it drives.

Four of Stage 12A's ten gates are questions about a *running* engine: the pair
roles, SELF, determinism and failure semantics, and behind them the workload
feasibility that only a measurement can answer. This module is what would answer
them — and it exists now, before any package does, because of what it costs to
build it later.

**The engine is behind a protocol.** :class:`QualificationEngine` is four
methods: open, load-and-extract, compare, close. Nothing here knows whether the
thing behind it is a C++ binding, a .NET assembly or a JAR, because the binding
is chosen from the delivered package and nothing may be assumed about it in
advance. When the package arrives, one adapter implements this protocol and the
driver below is unchanged.

**A fake engine implements the same protocol**, so the harness's own contract —
the six passes, the twenty-comparison ceiling, two extractions for SELF, both
orientations, digests instead of scores, a record that survives failure — is
proved on every CI run with no package, no licence and no network. The fake can
never answer a gate: every record is stamped with its engine kind and the
preflight reads only ``DELIVERED_SDK``.

**No score value is written anywhere.** Each pass records a SHA-256 over the
score's canonical text and never the score. What reaches disk is a contract, not
a measurement.

**The record survives a failure.** A run that starts and breaks writes
``status: FAILED`` with the pass it broke at. Stage 11A learned that the
alternative — discarding it and reporting "not run yet" — turns a finding into a
chore, and the finding is the more useful of the two.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import struct
import subprocess
import sys
import time
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

from fpbench.core.idkit_preflight_errors import IdkitQualificationError
from fpbench.core.serialization import stable_hash
from fpbench.experiments.stage12a_idkit_identity import (
    DETERMINISM_LEVELS,
    FAILURE_SEMANTICS_CAUSES,
    PAIR_ROLE_BINDING,
    QUALIFICATION_MAX_SCORING_COMPARISONS,
    QUALIFICATION_PASSES,
    QUALIFICATION_RECORD_NAME,
    QUALIFICATION_RECORD_SCHEMA,
    REQUIRED_INPUT_DPI,
    QualificationOutcome,
)

__all__ = [
    "DRIVER_SOURCE",
    "EngineKind",
    "ComparisonOutcome",
    "Representation",
    "QualificationEngine",
    "EngineFactory",
    "FakeIdkitEngine",
    "fake_engine_factory",
    "FixtureSet",
    "build_fixtures",
    "write_gray8_png",
    "decode_gray8_png",
    "ridge_field",
    "QualificationRecord",
    "run_qualification",
    "read_record",
    "write_record",
    "record_path",
    "main",
]

#: This module's own source. Part of a run's identity, because the driver decides
#: which passes run, what they see and how their answers are merged — all of
#: which can change what a record says.
DRIVER_SOURCE = Path("src") / "fpbench" / "experiments" / "stage12a_qualification.py"


class EngineKind(str, Enum):
    """What produced a record, and therefore what it may be used for.

    The distinction is load-bearing. A fake engine proves the harness; it proves
    nothing about IDKit, and a gate that accepted its record would be a gate that
    passed on this project's own test double.
    """

    #: The binding selected from a delivered Innovatrics package.
    DELIVERED_SDK = "DELIVERED_SDK"

    #: This module's own double. Answers no gate, ever.
    FAKE_SDK = "FAKE_SDK"

    @property
    def answers_gates(self) -> bool:
        return self is EngineKind.DELIVERED_SDK


@dataclass(frozen=True, slots=True)
class Representation:
    """One extracted single-finger representation, as an opaque handle.

    ``handle`` is whatever the binding returns and never leaves this process.
    ``size_bytes`` and ``representation_type`` are the only facts about it that
    may be published, and the bytes themselves are not among them.
    """

    handle: Any
    representation_type: str
    size_bytes: int
    extraction_dpi: int

    def __post_init__(self) -> None:
        if self.extraction_dpi != REQUIRED_INPUT_DPI:
            raise IdkitQualificationError(
                f"a representation was extracted at {self.extraction_dpi} DPI and "
                f"this benchmark's input profile is {REQUIRED_INPUT_DPI}; the "
                "resolution is declared before extraction, not after"
            )


@dataclass(frozen=True, slots=True)
class ComparisonOutcome:
    """What one comparison returned: a score, or a structured failure.

    Never both, and never a score standing in for a failure. The whole point of
    the failure-semantics pass is that a refused comparison arrives here as
    ``failure_status`` and not as a zero.
    """

    score: float | int | None
    failure_status: str | None
    detail: str = ""

    def __post_init__(self) -> None:
        if (self.score is None) == (self.failure_status is None):
            raise IdkitQualificationError(
                "a comparison returns exactly one of a score and a failure "
                "status. Both would be ambiguous; neither would be silence"
            )

    @property
    def produced_a_score(self) -> bool:
        return self.score is not None

    @property
    def score_digest(self) -> str | None:
        """A digest over the score's canonical text, never the score.

        ``repr`` of the number rather than a rounded string, so that two runs
        that differ in the last bit of a float are two different digests. A
        digest is the only form in which a score is allowed to reach disk.
        """
        if self.score is None:
            return None
        return hashlib.sha256(repr(self.score).encode("utf-8")).hexdigest()


class QualificationEngine(Protocol):
    """What a binding has to offer for the four execution gates to be answerable.

    Four methods, chosen so that the harness never needs to know how the package
    is organised. ``extract`` takes a path and a DPI and returns a
    representation, which is what makes "two independent extractions" expressible
    without the caller managing any engine state.
    """

    def describe(self) -> Mapping[str, Any]:
        """Binding identity and the settings the engine reports for itself."""

    def extract(self, image: Path, *, dpi: int) -> Representation:
        """Load one image and extract exactly one single-finger representation.

        Raises:
            Exception: any structured refusal from the binding. The driver
                catches it and records it as a failure, which is the answer the
                failure-semantics pass is looking for.
        """

    def compare(
        self, probe: Representation, gallery: Representation
    ) -> ComparisonOutcome:
        """Compare one probe against one gallery, both single-finger."""

    def close(self) -> None:
        """Release whatever the binding holds."""


#: A callable that builds a fresh engine. Fresh objects and fresh processes are
#: two of the three determinism levels, and both are expressed by calling this
#: again rather than by reaching into an engine's internals.
EngineFactory = Callable[[], QualificationEngine]


# ------------------------------------------------------------------ fixtures


def write_gray8_png(path: Path, pixels: Sequence[Sequence[int]]) -> Path:
    """An 8-bit grayscale PNG at 500 PPI, written with the standard library only.

    ``fpbench.imaging`` owns this project's real image pipeline and Stage 12A may
    not import it: a qualification layer that reached into the benchmark's own
    preprocessing could produce a fixture the benchmark had already shaped.
    """
    height = len(pixels)
    width = len(pixels[0])
    raw = b"".join(b"\x00" + bytes(row) for row in pixels)

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    per_metre = int(round(REQUIRED_INPUT_DPI * 39.3701))
    physical = struct.pack(">IIB", per_metre, per_metre, 1)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"pHYs", physical)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )
    return path


def decode_gray8_png(path: Path) -> tuple[int, int, bytes]:
    """Decode one 8-bit grayscale PNG to its exact pixel matrix.

    This is the decode the permitted input route rests on. If the delivered
    package turns out not to read PNG, the benchmark's images reach it through
    this function and a raw-buffer API — and the gate's requirement is that the
    matrix is identical, so the decode has to be here, readable, and checkable
    rather than delegated to whatever image library happens to be installed.

    Only the narrow case is supported: 8-bit greyscale, no interlace, no palette.
    Anything else raises, because a decoder that quietly handled a wider case
    would be a decoder that quietly changed pixels.

    Returns:
        ``(width, height, pixels)`` with one byte per pixel, row-major.
    """
    data = Path(path).read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise IdkitQualificationError(f"{path.name} is not a PNG")
    offset = 8
    width = height = 0
    compressed = bytearray()
    while offset < len(data):
        (length,) = struct.unpack(">I", data[offset : offset + 4])
        kind = data[offset + 4 : offset + 8]
        payload = data[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if kind == b"IHDR":
            width, height, depth, colour, compression, filter_, interlace = (
                struct.unpack(">IIBBBBB", payload)
            )
            if (depth, colour, compression, filter_, interlace) != (8, 0, 0, 0, 0):
                raise IdkitQualificationError(
                    f"{path.name} is not 8-bit non-interlaced greyscale, and this "
                    "decoder handles nothing else on purpose"
                )
        elif kind == b"IDAT":
            compressed += payload
        elif kind == b"IEND":
            break
    raw = zlib.decompress(bytes(compressed))
    stride = width
    pixels = bytearray()
    previous = bytes(stride)
    position = 0
    for _ in range(height):
        filter_type = raw[position]
        line = bytearray(raw[position + 1 : position + 1 + stride])
        position += 1 + stride
        if filter_type == 0:
            pass
        elif filter_type == 1:
            for index in range(1, stride):
                line[index] = (line[index] + line[index - 1]) & 0xFF
        elif filter_type == 2:
            for index in range(stride):
                line[index] = (line[index] + previous[index]) & 0xFF
        elif filter_type == 3:
            for index in range(stride):
                left = line[index - 1] if index else 0
                line[index] = (line[index] + ((left + previous[index]) >> 1)) & 0xFF
        elif filter_type == 4:
            for index in range(stride):
                left = line[index - 1] if index else 0
                upper_left = previous[index - 1] if index else 0
                estimate = left + previous[index] - upper_left
                distances = (
                    abs(estimate - left),
                    abs(estimate - previous[index]),
                    abs(estimate - upper_left),
                )
                nearest = (left, previous[index], upper_left)[
                    distances.index(min(distances))
                ]
                line[index] = (line[index] + nearest) & 0xFF
        else:  # pragma: no cover - not produced by this project's writer
            raise IdkitQualificationError(
                f"{path.name} uses PNG filter {filter_type}, which this decoder "
                "does not handle"
            )
        pixels += line
        previous = bytes(line)
    return width, height, bytes(pixels)


def ridge_field(
    width: int, height: int, *, phase: float, curve: float
) -> list[list[int]]:
    """A synthetic ridge-like field. Not a fingerprint, and not from any person.

    Concentric-ish ridges with a slowly rotating orientation: enough structure
    for an extractor to find minutiae in, and none of it from a human being or
    from SD300.
    """
    rows: list[list[int]] = []
    centre_x, centre_y = width / 2.0, height / 2.0
    for y in range(height):
        row: list[int] = []
        for x in range(width):
            dx, dy = (x - centre_x) / width, (y - centre_y) / height
            radius = math.sqrt(dx * dx + dy * dy)
            angle = math.atan2(dy, dx)
            wave = math.sin(48.0 * radius + curve * angle + phase)
            row.append(max(0, min(255, int(128 + 110 * wave))))
        rows.append(row)
    return rows


@dataclass(frozen=True, slots=True)
class FixtureSet:
    """The non-SD300 inputs one qualification runs on.

    Four files, each with a job. Two ridge-like impressions carry the route
    itself. A uniform grey image decodes perfectly and holds no ridge at all,
    which is the controlled cause for an extraction that legitimately declines. A
    PNG signature over a broken body is the controlled cause for an invalid
    image.
    """

    kind: str
    a: Path
    b: Path
    blank: Path
    invalid: Path
    missing: Path

    @property
    def digests(self) -> Mapping[str, str]:
        """A digest per fixture, or ``ABSENT`` for one that is not there.

        Tolerant on purpose. This is computed while a record is being assembled,
        including the record of a run that broke — and a fingerprint that raised
        would take the failed run's evidence down with it, which is the one thing
        this harness is built not to do.
        """
        return {
            path.name: (
                hashlib.sha256(path.read_bytes()).hexdigest()
                if path.is_file()
                else "ABSENT"
            )
            for path in (self.a, self.b, self.blank, self.invalid)
        }


def build_fixtures(directory: Path, *, width: int = 320, height: int = 400) -> FixtureSet:
    """Write the fixtures. Nothing here reads SD300, and nothing can."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    a = write_gray8_png(
        directory / "fixture_a.png", ridge_field(width, height, phase=0.0, curve=3.0)
    )
    b = write_gray8_png(
        directory / "fixture_b.png", ridge_field(width, height, phase=0.6, curve=3.4)
    )
    blank = write_gray8_png(
        directory / "fixture_blank.png", [[128] * width for _ in range(height)]
    )
    invalid = directory / "fixture_invalid.png"
    invalid.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    return FixtureSet(
        kind="SYNTHETIC_RIDGE_LIKE",
        a=a,
        b=b,
        blank=blank,
        invalid=invalid,
        missing=directory / "fixture_absent.png",
    )


# ---------------------------------------------------------------- the fake SDK


class FakeIdkitEngine:
    """A double with the behaviours that matter, and none that flatter the route.

    It is asymmetric, because Innovatrics states its matcher is; it is
    deterministic, because a candidate that is not fails; it refuses a blank
    image and an unreadable one with a status rather than a score; and it returns
    a scalar independent of any threshold.

    It is deliberately *not* generous. It refuses to compare a representation it
    did not produce, and it counts its own extractions, so a driver that
    shortcuts SELF to one extraction is caught here rather than in six months.
    """

    representation_type = "FAKE_PROPRIETARY_TEMPLATE"

    def __init__(self) -> None:
        self._closed = False
        self.extractions = 0
        self._issued: list[int] = []

    def describe(self) -> Mapping[str, Any]:
        return {
            "binding": "fake",
            "engine_kind": EngineKind.FAKE_SDK.value,
            "delivered_runtime_defaults": {
                "fake_quality_threshold": 0,
                "fake_max_template_size": 4096,
                "fake_matching_speed": "MEDIUM",
            },
        }

    def _require_open(self) -> None:
        if self._closed:
            raise IdkitQualificationError("the engine has been closed")

    def extract(self, image: Path, *, dpi: int) -> Representation:
        self._require_open()
        path = Path(image)
        if not path.is_file():
            raise FileNotFoundError(f"no such image: {path.name}")
        width, height, pixels = decode_gray8_png(path)
        if len(set(pixels)) <= 1:
            raise ValueError(
                "no ridge structure was found in this image; the extractor "
                "declines it"
            )
        self.extractions += 1
        digest = hashlib.sha256(pixels).digest()
        handle = int.from_bytes(digest[:8], "big")
        self._issued.append(handle)
        return Representation(
            handle=handle,
            representation_type=self.representation_type,
            size_bytes=512 + (handle % 1024),
            extraction_dpi=dpi,
        )

    def compare(
        self, probe: Representation, gallery: Representation
    ) -> ComparisonOutcome:
        self._require_open()
        for side, item in (("probe", probe), ("gallery", gallery)):
            if item.handle not in self._issued:
                return ComparisonOutcome(
                    score=None,
                    failure_status="FOREIGN_REPRESENTATION",
                    detail=f"the {side} was not extracted by this engine",
                )
        # Asymmetric on purpose: the low bits of the probe are weighted more
        # than the gallery's, so score(A, B) and score(B, A) differ, exactly as
        # the vendor documents for the real matcher.
        blend = (probe.handle * 3 + gallery.handle) % 100_000
        return ComparisonOutcome(score=blend / 1000.0, failure_status=None)

    def close(self) -> None:
        self._closed = True


def fake_engine_factory() -> QualificationEngine:
    """A fresh fake engine. The factory the CI qualification runs against."""
    return FakeIdkitEngine()


# ------------------------------------------------------------------ the record


@dataclass(frozen=True, slots=True)
class QualificationRecord:
    """One bounded run, in the form that reaches disk.

    Validated on construction under ``SUCCESS`` and left deliberately loose under
    ``FAILED``: a run that broke halfway is allowed to have holes, and the record
    of it is more useful than no record.
    """

    schema: str
    status: QualificationOutcome
    engine_kind: EngineKind
    started_utc: str
    finished_utc: str
    scoring_comparisons: int
    passes: Mapping[str, Mapping[str, Any]]
    pair_orientation: Mapping[str, Any]
    self_semantics: Mapping[str, Any]
    determinism: Mapping[str, bool]
    failure_semantics: tuple[Mapping[str, Any], ...]
    runtime: Mapping[str, Any]
    delivered_runtime_defaults: Mapping[str, Any]
    fixture_kind: str
    inputs_fingerprint: str
    driver_fingerprint: str
    failed_at_pass: str | None = None
    failure_detail: str = ""

    def __post_init__(self) -> None:
        if self.schema != QUALIFICATION_RECORD_SCHEMA:
            raise IdkitQualificationError(
                f"unsupported qualification record schema {self.schema!r}"
            )
        if self.scoring_comparisons > QUALIFICATION_MAX_SCORING_COMPARISONS:
            raise IdkitQualificationError(
                f"{self.scoring_comparisons} score-producing comparisons were run "
                f"and the ceiling is {QUALIFICATION_MAX_SCORING_COMPARISONS}. A "
                "route check that grew into a measurement would be spending a "
                "licence clock on numbers nobody may publish"
            )
        if self.status is QualificationOutcome.FAILED:
            if not self.failed_at_pass:
                raise IdkitQualificationError(
                    "a failed run names the pass it failed at; a failure nobody "
                    "can locate is a failure nobody can diagnose"
                )
            return
        if self.failed_at_pass:
            raise IdkitQualificationError(
                "a successful run failed at nothing"
            )
        missing = sorted(
            {name for name, _ in QUALIFICATION_PASSES} - set(self.passes)
        )
        if missing:
            raise IdkitQualificationError(
                f"a successful run carries every pass; {missing} is missing"
            )
        levels = sorted(set(DETERMINISM_LEVELS) - set(self.determinism))
        if levels:
            raise IdkitQualificationError(
                f"a successful run answers every determinism level; {levels} is "
                "missing"
            )
        causes = {name for name, _ in FAILURE_SEMANTICS_CAUSES}
        attempted = {str(item.get("cause")) for item in self.failure_semantics}
        if not causes & attempted:
            raise IdkitQualificationError(
                "a successful run tried at least one failure cause; a route whose "
                "failures nobody provoked is a route whose failures arrive during "
                "the 6,000"
            )
        for item in self.failure_semantics:
            if item.get("produced_a_score"):
                raise IdkitQualificationError(
                    f"the {item.get('cause')!r} cause produced a score. A failure "
                    "that arrives as a number enters the benchmark as a very poor "
                    "match and no metric can tell the two apart"
                )
        if int(self.self_semantics.get("independent_extractions", 0)) != 2:
            raise IdkitQualificationError(
                "SELF is two independent extractions of the same image, and a "
                "record that says otherwise describes a different rule"
            )
        if self.self_semantics.get("representation_reused"):
            raise IdkitQualificationError(
                "SELF reused a representation between its two sides"
            )

    def as_json(self) -> Mapping[str, Any]:
        return {
            "schema": self.schema,
            "status": self.status.value,
            "engine_kind": self.engine_kind.value,
            "started_utc": self.started_utc,
            "finished_utc": self.finished_utc,
            "failed_at_pass": self.failed_at_pass,
            "failure_detail": self.failure_detail,
            "scoring_comparisons": self.scoring_comparisons,
            "pair_role_binding": {left: right for left, right in PAIR_ROLE_BINDING},
            "passes": {name: dict(value) for name, value in self.passes.items()},
            "pair_orientation": dict(self.pair_orientation),
            "self_semantics": dict(self.self_semantics),
            "determinism": dict(self.determinism),
            "failure_semantics": [dict(item) for item in self.failure_semantics],
            "runtime": dict(self.runtime),
            "delivered_runtime_defaults": dict(self.delivered_runtime_defaults),
            "fixture_kind": self.fixture_kind,
            "inputs_fingerprint": self.inputs_fingerprint,
            "driver_fingerprint": self.driver_fingerprint,
        }


def record_path(*, repository_root: Path | None = None) -> Path:
    """Where the local record lives: beside the package, outside Git."""
    from fpbench.experiments.stage12a_acquisition import artifact_store_prefix_path

    return (
        artifact_store_prefix_path(repository_root=repository_root)
        / QUALIFICATION_RECORD_NAME
    )


def write_record(record: QualificationRecord, path: Path) -> Path:
    """Write one record as bytes, with ``\\n`` line endings."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(record.as_json(), indent=2, ensure_ascii=False)
    path.write_bytes((payload + "\n").encode("utf-8"))
    return path


def read_record(path: Path) -> Mapping[str, Any] | None:
    """Read a record, or ``None`` where there is not one."""
    path = Path(path)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


# ------------------------------------------------------------------- the run


def _driver_fingerprint() -> str:
    """A digest over this driver's source, with newlines normalised.

    ``core.autocrlf`` is on for this repository, so a raw digest would name the
    checkout rather than the code — and a check that demands a re-run after every
    fresh clone is a check somebody switches off.
    """
    from fpbench.experiments.algorithm_research import REPOSITORY_ROOT

    path = Path(REPOSITORY_ROOT) / DRIVER_SOURCE
    try:
        content = path.read_bytes().replace(b"\r\n", b"\n")
    except OSError:  # pragma: no cover - a driver that cannot read itself
        return "unavailable"
    return hashlib.sha256(content).hexdigest()


@dataclass
class _Budget:
    """The twenty-comparison ceiling, enforced where the comparisons happen."""

    used: int = 0

    def spend(self) -> None:
        self.used += 1
        if self.used > QUALIFICATION_MAX_SCORING_COMPARISONS:
            raise IdkitQualificationError(
                f"the qualification asked for comparison {self.used} and the "
                f"ceiling is {QUALIFICATION_MAX_SCORING_COMPARISONS}"
            )


@dataclass
class _Run:
    """Mutable state while the passes run. Never published as itself."""

    passes: dict[str, dict[str, Any]] = field(default_factory=dict)
    failure_semantics: list[dict[str, Any]] = field(default_factory=list)
    budget: _Budget = field(default_factory=_Budget)


def _score_pass(
    run: _Run,
    engine: QualificationEngine,
    name: str,
    probe: Representation,
    gallery: Representation,
) -> ComparisonOutcome:
    run.budget.spend()
    outcome = engine.compare(probe, gallery)
    run.passes[name] = {
        "produced_a_score": outcome.produced_a_score,
        "score_digest": outcome.score_digest,
        "failure_status": outcome.failure_status,
    }
    return outcome


def _fresh_process_digest(fixtures: FixtureSet, *, engine_module: str) -> str | None:
    """Run the ordinary pass again in a separate process, and return its digest.

    A real restart, not a simulated one. The determinism level that catches a
    lazily-initialised cache is exactly the one that cannot be checked from
    inside the process that would hold the cache.
    """
    command = (
        sys.executable,
        "-m",
        "fpbench.experiments.stage12a_qualification",
        "fresh-process",
        "--engine",
        engine_module,
        "--probe",
        str(fixtures.a),
        "--gallery",
        str(fixtures.b),
    )
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in ("PYTHONHASHSEED",)
    }
    environment["PYTHONHASHSEED"] = "0"
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=300,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired):  # pragma: no cover - a broken host
        return None
    if completed.returncode != 0:
        return None
    for line in reversed(completed.stdout.splitlines()):
        item = line.strip()
        if len(item) == 64 and all(character in "0123456789abcdef" for character in item):
            return item
    return None


def run_qualification(
    factory: EngineFactory,
    fixtures: FixtureSet,
    *,
    engine_kind: EngineKind,
    engine_module: str = "fake",
) -> QualificationRecord:
    """Drive the six passes and return the record, whatever happened.

    Raises nothing for an engine failure: a broken route is the finding, and the
    record carries it. It does raise for a driver mistake — a comparison over the
    ceiling, a SELF built from one extraction — because those are this project's
    faults and must not be recorded as the candidate's.
    """
    started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    run = _Run()
    determinism: dict[str, bool] = {level: False for level in DETERMINISM_LEVELS}
    orientation: dict[str, Any] = {
        "both_orderings_produced_a_score": False,
        "score_digests_equal": None,
    }
    self_semantics: dict[str, Any] = {
        "score_present": False,
        "independent_extractions": 0,
        "representation_reused": False,
    }
    runtime: dict[str, Any] = {}
    delivered: Mapping[str, Any] = {}
    failed_at: str | None = None
    detail = ""

    engine: QualificationEngine | None = None
    try:
        startup_began = time.perf_counter()
        engine = factory()
        described = engine.describe()
        runtime["startup_seconds"] = round(time.perf_counter() - startup_began, 4)
        raw_defaults = described.get("delivered_runtime_defaults")
        delivered = dict(raw_defaults) if isinstance(raw_defaults, Mapping) else {}

        end_to_end_began = time.perf_counter()
        probe = engine.extract(fixtures.a, dpi=REQUIRED_INPUT_DPI)
        gallery = engine.extract(fixtures.b, dpi=REQUIRED_INPUT_DPI)
        ordinary = _score_pass(run, engine, "ordinary", probe, gallery)
        runtime["end_to_end_seconds"] = round(
            time.perf_counter() - end_to_end_began, 4
        )
        if not ordinary.produced_a_score:
            raise IdkitQualificationError(
                "the ordinary pass produced no score: "
                f"{ordinary.failure_status} {ordinary.detail}".strip()
            )

        repeated = _score_pass(run, engine, "repeat_same_process", probe, gallery)
        determinism["repeat_in_the_same_process"] = (
            repeated.score_digest == ordinary.score_digest
        )

        fresh_probe = engine.extract(fixtures.a, dpi=REQUIRED_INPUT_DPI)
        fresh_gallery = engine.extract(fixtures.b, dpi=REQUIRED_INPUT_DPI)
        fresh_objects = _score_pass(
            run, engine, "fresh_objects_same_process", fresh_probe, fresh_gallery
        )
        determinism["fresh_objects_in_the_same_process"] = (
            fresh_objects.score_digest == ordinary.score_digest
        )

        reversed_outcome = _score_pass(run, engine, "reversed", gallery, probe)
        orientation["both_orderings_produced_a_score"] = (
            ordinary.produced_a_score and reversed_outcome.produced_a_score
        )
        if orientation["both_orderings_produced_a_score"]:
            orientation["score_digests_equal"] = (
                reversed_outcome.score_digest == ordinary.score_digest
            )

        # SELF: two loads, two extractions, nothing shared between the sides.
        self_probe = engine.extract(fixtures.a, dpi=REQUIRED_INPUT_DPI)
        self_gallery = engine.extract(fixtures.a, dpi=REQUIRED_INPUT_DPI)
        if self_probe is self_gallery:  # pragma: no cover - a broken engine
            raise IdkitQualificationError(
                "the engine returned the same representation object for two "
                "extractions, so SELF would compare a template with itself"
            )
        self_outcome = _score_pass(run, engine, "self", self_probe, self_gallery)
        self_semantics = {
            "score_present": self_outcome.produced_a_score,
            "independent_extractions": 2,
            "representation_reused": False,
        }

        run.passes["fresh_process"] = {
            "produced_a_score": False,
            "score_digest": None,
            "failure_status": None,
        }
        restart_digest = _fresh_process_digest(fixtures, engine_module=engine_module)
        run.passes["fresh_process"] = {
            "produced_a_score": restart_digest is not None,
            "score_digest": restart_digest,
            "failure_status": None if restart_digest else "RESTART_PASS_DID_NOT_SCORE",
        }
        determinism["fresh_process"] = restart_digest == ordinary.score_digest

        for cause, expectation in FAILURE_SEMANTICS_CAUSES:
            attempt = _failure_probe(engine, fixtures, cause)
            if attempt is not None:
                attempt["expectation"] = expectation
                run.failure_semantics.append(attempt)

        runtime.update(_runtime_measurements())
    except IdkitQualificationError:
        raise
    except Exception as exc:  # the candidate's failure, not the driver's
        failed_at = _current_pass(run)
        detail = f"{type(exc).__name__}: {exc}"
    finally:
        if engine is not None:
            try:
                engine.close()
            except Exception:  # pragma: no cover - a binding that will not close
                pass

    status = (
        QualificationOutcome.FAILED if failed_at else QualificationOutcome.SUCCESS
    )
    return QualificationRecord(
        schema=QUALIFICATION_RECORD_SCHEMA,
        status=status,
        engine_kind=engine_kind,
        started_utc=started,
        finished_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        scoring_comparisons=run.budget.used,
        passes=run.passes,
        pair_orientation=orientation,
        self_semantics=self_semantics,
        determinism=determinism,
        failure_semantics=tuple(run.failure_semantics),
        runtime=runtime,
        delivered_runtime_defaults=delivered,
        fixture_kind=fixtures.kind,
        inputs_fingerprint=stable_hash(
            {
                "schema": "stage_12a_qualification_inputs_v1",
                "fixtures": dict(fixtures.digests),
                "dpi": REQUIRED_INPUT_DPI,
            },
            length=64,
        ),
        driver_fingerprint=_driver_fingerprint(),
        failed_at_pass=failed_at,
        failure_detail=detail,
    )


def _current_pass(run: _Run) -> str:
    """The pass that was in flight when something broke."""
    for name, _ in QUALIFICATION_PASSES:
        if name not in run.passes:
            return name
    return "failure_semantics"  # pragma: no cover - every pass completed


def _failure_probe(
    engine: QualificationEngine, fixtures: FixtureSet, cause: str
) -> dict[str, Any] | None:
    """Provoke one failure cause safely, and record what came back.

    Returns ``None`` for a cause this harness cannot provoke without doing
    something it must not — deleting a licence, for instance. A cause nobody
    could try is recorded as untried by its absence rather than as passed.
    """
    target = {
        "malformed_or_invalid_image": fixtures.invalid,
        "valid_but_unextractable_fingerprint": fixtures.blank,
        "missing_or_invalid_input": fixtures.missing,
    }.get(cause)
    if target is None:
        return None
    try:
        representation = engine.extract(target, dpi=REQUIRED_INPUT_DPI)
    except Exception as exc:
        return {
            "cause": cause,
            "produced_a_score": False,
            "classified_as": type(exc).__name__,
            "arrived_as": "EXCEPTION",
        }
    outcome = engine.compare(representation, representation)
    return {
        "cause": cause,
        "produced_a_score": outcome.produced_a_score,
        "classified_as": outcome.failure_status or "SCORE",
        "arrived_as": "SCORE" if outcome.produced_a_score else "STATUS",
    }


def _runtime_measurements() -> Mapping[str, Any]:
    """What the host can say about itself, without naming itself.

    A CPU count and a peak memory figure. No hostname, no user, no path — a
    runtime measurement is not a reason to publish a machine.
    """
    measurements: dict[str, Any] = {
        "cpu_count": os.cpu_count(),
        "python_implementation": platform.python_implementation(),
    }
    try:  # pragma: no cover - absent on Windows
        import resource

        measurements["approximate_peak_memory_kb"] = (
            resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        )
    except Exception:
        measurements["approximate_peak_memory_kb"] = None
    return measurements


def main(argv: list[str] | None = None) -> int:
    """``python -m fpbench.experiments.stage12a_qualification``.

    ``fake`` runs the whole harness against the fake engine and writes the record
    where it is told, which is what CI exercises. ``fresh-process`` is the
    restart pass calling back into itself: it prints one digest and nothing else.
    """
    import argparse
    import tempfile

    parser = argparse.ArgumentParser(description="Stage 12A qualification")
    parser.add_argument(
        "action", choices=("fake", "check", "fresh-process"), nargs="?", default="fake"
    )
    parser.add_argument("--engine", default="fake")
    parser.add_argument("--probe")
    parser.add_argument("--gallery")
    parser.add_argument("--output")
    arguments = parser.parse_args(argv)

    if arguments.action == "check":
        from fpbench.experiments.stage12a_acquisition import acquisition_state

        state = acquisition_state()
        print(f"acquisition            {state.status.value}")
        print(f"package                {state.presence.value}")
        if not state.obtained:
            print(
                "\nA qualification runs against a binding selected from a "
                "delivered package,\nand there is none here. Nothing is missing "
                "from this project: the vendor\nhas not delivered one. Run "
                "`make stage12a-qualify-fake` to exercise the whole\nharness "
                "against the fake SDK — it proves every pass, needs no licence, "
                "and\nanswers no gate."
            )
            return 1
        print(
            "\nA delivered package is present. The binding adapter that drives "
            "this harness\nagainst it is the first thing Stage 12A adds once a "
            "package exists; it is not\nwritten in advance, because nothing may "
            "be assumed about which binding the\npackage ships."
        )
        return 0

    if arguments.action == "fresh-process":
        if arguments.engine != "fake":
            raise SystemExit(
                f"no restart engine is registered for {arguments.engine!r}"
            )
        engine = fake_engine_factory()
        try:
            probe = engine.extract(Path(arguments.probe), dpi=REQUIRED_INPUT_DPI)
            gallery = engine.extract(Path(arguments.gallery), dpi=REQUIRED_INPUT_DPI)
            outcome = engine.compare(probe, gallery)
        finally:
            engine.close()
        if not outcome.produced_a_score:
            raise SystemExit(f"the restart pass produced no score: {outcome.failure_status}")
        print(outcome.score_digest)
        return 0

    with tempfile.TemporaryDirectory(prefix="stage12a-qualification-") as scratch:
        fixtures = build_fixtures(Path(scratch))
        record = run_qualification(
            fake_engine_factory,
            fixtures,
            engine_kind=EngineKind.FAKE_SDK,
            engine_module="fake",
        )
        destination = Path(arguments.output) if arguments.output else (
            Path(scratch) / QUALIFICATION_RECORD_NAME
        )
        write_record(record, destination)
        print(f"status                 {record.status.value}")
        print(f"engine kind            {record.engine_kind.value}")
        print(f"scoring comparisons    {record.scoring_comparisons}")
        print(f"passes                 {len(record.passes)}")
        for level in DETERMINISM_LEVELS:
            print(f"  {level:<34s} {record.determinism.get(level)}")
        print(
            "orientation digests    "
            + (
                "equal"
                if record.pair_orientation.get("score_digests_equal")
                else "different"
            )
        )
        print(f"failure causes tried   {len(record.failure_semantics)}")
        if arguments.output:
            print(f"record                 {destination}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
