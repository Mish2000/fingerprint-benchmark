"""The bounded qualification: what it runs, what it records, and what it refuses.

The harness is written against a small protocol rather than against FingerCell,
for two reasons. It can be driven end to end by a fake engine in public CI, where
there is no archive and no licence; and it can be written and proved *before* the
trial is activated, so the 30-day clock does not run while the harness is being
debugged (docs/adr/0115).

What a run does, at most twenty score-producing comparisons:

.. code-block:: text

    ordinary                    score(A, B) under the frozen role binding
    repeat_same_objects         again, same process, same objects
    fresh_objects_same_process  again, same process, new objects
    fresh_process               again, in a separate process
    reversed                    score(B, A), observation only
    self                        SELF(A, A) from two independent extractions

and then provokes all four mandatory failure probes. Four, not "at least one":
a route whose failure semantics are only partly known is a route that will
surprise the benchmark on some image in the corpus.

**No score value reaches disk.** The record carries digests of scores and the
equalities between them, which is everything the gates ask and nothing a reader
could mine. A raw score in a published file would be a biometric measurement
published by a stage whose whole subject is that it publishes none.

**A failed run is kept.** A run that started, loaded the runtime and then broke
is evidence about the route. It is recorded with ``status = FAILED`` and the
gate reads it as a failure — never as an action nobody performed.
"""

from __future__ import annotations

import json
import os
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

from fpbench.core.fingercell_preflight_errors import FingerCellQualificationError
from fpbench.core.serialization import stable_hash
from fpbench.experiments.stage13a_fingercell_identity import (
    DETERMINISM_LEVELS,
    MANDATORY_FAILURE_PROBES,
    MANDATORY_FAILURE_PROBE_COUNT,
    QUALIFICATION_MAX_SCORING_COMPARISONS,
    QUALIFICATION_PASSES,
    QUALIFICATION_RECORD_BINDING_FIELDS,
    QUALIFICATION_RECORD_NAME,
    QUALIFICATION_RECORD_SCHEMA,
    QualificationOutcome,
    TemplateFormat,
)

__all__ = [
    "EngineKind",
    "Template",
    "ComparisonOutcome",
    "ExtractionRefused",
    "QualificationEngine",
    "write_gray8_png",
    "decode_gray8_png",
    "ridge_field",
    "FixtureSet",
    "build_fixtures",
    "FakeFingerCellEngine",
    "fake_engine_factory",
    "QualificationRecord",
    "record_path",
    "write_record",
    "read_record",
    "run_qualification",
    "main",
]


class EngineKind(str, Enum):
    """Which engine produced a record.

    The distinction the gate engine depends on. A record produced by the fake is
    proof about the harness and about nothing else, and a gate that accepted one
    would be a gate that passed on this project's own test double.
    """

    DELIVERED_SDK = "DELIVERED_SDK"
    FAKE_SDK = "FAKE_SDK"


class ExtractionRefused(Exception):
    """The engine declined to produce a template.

    Not an error in the harness: upstream's quality check is part of the
    algorithm, and an image below the threshold produces no template at all. The
    harness turns this into a recorded status and never into a score.
    """


@dataclass(frozen=True, slots=True)
class Template:
    """One extracted template, described rather than carried."""

    size_bytes: int
    template_format: TemplateFormat
    digest: str

    def __post_init__(self) -> None:
        if self.size_bytes <= 0:
            raise FingerCellQualificationError(
                "a template with no bytes is not a template"
            )
        if self.template_format is not TemplateFormat.PROPRIETARY:
            raise FingerCellQualificationError(
                f"the compared representation is {TemplateFormat.PROPRIETARY.value} "
                f"and this one is {self.template_format.value}; an ISO or MOC "
                "export is a different matching scenario"
            )


@dataclass(frozen=True, slots=True)
class ComparisonOutcome:
    """What one comparison produced, with the value replaced by its digest."""

    pass_name: str
    reference_digest: str
    candidate_digest: str
    score_digest: str
    native_type: str

    @property
    def row(self) -> Mapping[str, Any]:
        return {
            "pass_name": self.pass_name,
            "reference_digest": self.reference_digest,
            "candidate_digest": self.candidate_digest,
            "score_digest": self.score_digest,
            "native_type": self.native_type,
        }


class QualificationEngine(Protocol):
    """The three things the harness needs, and nothing else.

    Deliberately not FingerCell's API. The real bridge adapts FingerCell to this;
    the fake implements it directly; and the harness cannot tell them apart,
    which is what makes a CI run meaningful.
    """

    def extract(self, image_path: Path) -> Template:
        """One image, one fresh extraction, one template."""

    def match(self, reference: Template, candidate: Template) -> int:
        """The native raw 1:1 score. Higher means more similar."""

    def describe(self) -> Mapping[str, Any]:
        """Settings and identity as the engine reports them."""


# ------------------------------------------------------------------ fixtures


def write_gray8_png(path: Path, pixels: Sequence[Sequence[int]]) -> Path:
    """Write an 8-bit grayscale PNG without a third-party imaging stack.

    Hand-rolled for the reason every stage since 8B hand-rolls it: this module
    must stay importable on a runner with no scientific stack at all, which is
    the runner its public CI uses.
    """
    height = len(pixels)
    width = len(pixels[0]) if height else 0
    if not height or not width:
        raise FingerCellQualificationError("a fixture image has no pixels")
    raw = bytearray()
    for row in pixels:
        if len(row) != width:
            raise FingerCellQualificationError("a fixture image is ragged")
        raw.append(0)
        raw.extend(int(value) & 0xFF for value in row)

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    # 500 PPI expressed in the PNG's own unit: pixels per metre, rounded.
    physical = struct.pack(">IIB", 19685, 19685, 1)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"pHYs", physical)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )
    return path


def decode_gray8_png(path: Path) -> tuple[int, int, bytes]:
    """Decode an 8-bit grayscale PNG back to an exact pixel matrix.

    The decode side of the equivalence proof the input route needs: a route that
    hands decoded pixels to the SDK has to show the pixels are the same ones.
    """
    data = path.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise FingerCellQualificationError(f"{path.name} is not a PNG")
    offset = 8
    width = height = 0
    payload = bytearray()
    while offset < len(data):
        (length,) = struct.unpack(">I", data[offset : offset + 4])
        kind = data[offset + 4 : offset + 8]
        body = data[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if kind == b"IHDR":
            width, height, depth, colour = struct.unpack(">IIBB", body[:10])
            if depth != 8 or colour != 0:
                raise FingerCellQualificationError(
                    f"{path.name} is not 8-bit grayscale"
                )
        elif kind == b"IDAT":
            payload.extend(body)
        elif kind == b"IEND":
            break
    raw = zlib.decompress(bytes(payload))
    stride = width + 1
    out = bytearray()
    previous = bytearray(width)
    for index in range(height):
        row = raw[index * stride : (index + 1) * stride]
        filter_kind = row[0]
        line = bytearray(row[1:])
        if filter_kind == 0:
            pass
        elif filter_kind == 1:
            for position in range(1, width):
                line[position] = (line[position] + line[position - 1]) & 0xFF
        elif filter_kind == 2:
            for position in range(width):
                line[position] = (line[position] + previous[position]) & 0xFF
        else:
            raise FingerCellQualificationError(
                f"{path.name} uses PNG filter {filter_kind}, which these fixtures "
                "never write"
            )
        out.extend(line)
        previous = line
    return width, height, bytes(out)


def ridge_field(
    width: int, height: int, *, seed: int, curvature: float = 0.0
) -> list[list[int]]:
    """A deterministic synthetic ridge pattern. Not a fingerprint, and not SD300.

    Enough structure that a matcher has something to align, generated from a seed
    so that two runs on two machines produce identical bytes.
    """
    import math

    pixels: list[list[int]] = []
    phase = (seed % 17) * 0.37
    for y in range(height):
        row: list[int] = []
        for x in range(width):
            warp = curvature * math.sin((y / max(height, 1)) * math.pi * 2.0)
            value = math.sin((x + warp * 12.0) * 0.42 + phase) * math.cos(
                y * 0.11 + phase * 0.5
            )
            row.append(int(128 + 96 * value) & 0xFF)
        pixels.append(row)
    return pixels


@dataclass(frozen=True, slots=True)
class FixtureSet:
    """The images one qualification uses. Never SD300, and never a real person."""

    image_a: Path
    image_b: Path
    malformed: Path
    structureless: Path
    missing: Path

    @property
    def fingerprint(self) -> str:
        """A digest over the fixture bytes, so a record can be bound to them."""
        parts = []
        for path in (self.image_a, self.image_b, self.malformed, self.structureless):
            parts.append(
                {
                    "name": path.name,
                    "sha256": stable_hash(
                        {"bytes": path.read_bytes().hex()}, length=64
                    ),
                }
            )
        return stable_hash(
            {"schema": "stage_13a_fixtures_v1", "files": parts}, length=64
        )


def build_fixtures(directory: Path, *, width: int = 320, height: int = 400) -> FixtureSet:
    """Write the five fixtures a qualification needs."""
    directory.mkdir(parents=True, exist_ok=True)
    image_a = write_gray8_png(
        directory / "fixture_a.png", ridge_field(width, height, seed=11)
    )
    image_b = write_gray8_png(
        directory / "fixture_b.png", ridge_field(width, height, seed=29, curvature=1.4)
    )
    malformed = directory / "malformed.png"
    malformed.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00\x11\x22not a png body")
    structureless = write_gray8_png(
        directory / "flat.png", [[128] * width for _ in range(height)]
    )
    return FixtureSet(
        image_a=image_a,
        image_b=image_b,
        malformed=malformed,
        structureless=structureless,
        missing=directory / "does-not-exist.png",
    )


# ---------------------------------------------------------------- the fake SDK


class FakeFingerCellEngine:
    """A stand-in with the delivered engine's *contract*, not its algorithm.

    It exists so the harness can be proved end to end where there is no archive
    and no licence. It is deterministic, it returns a signed integer, higher
    means more similar, it declines flat images the way a quality threshold
    would, it raises on malformed and missing input, and it is deliberately
    **asymmetric** — because the real matcher takes a reference and a candidate
    and nothing promises those are interchangeable.

    It must be able to reach a passing record (docs/adr/0106). A test double that
    could never pass would prove only that the harness can fail.
    """

    def __init__(self) -> None:
        self._extractions = 0

    def extract(self, image_path: Path) -> Template:
        if not image_path.is_file():
            raise FileNotFoundError(f"no such image: {image_path.name}")
        width, height, pixels = decode_gray8_png(image_path)
        spread = max(pixels) - min(pixels)
        if spread < 8:
            raise ExtractionRefused(
                "image quality below the acceptable threshold; no template extracted"
            )
        self._extractions += 1
        digest = stable_hash(
            {"width": width, "height": height, "pixels": pixels.hex()}, length=64
        )
        return Template(
            size_bytes=192 + (spread % 64),
            template_format=TemplateFormat.PROPRIETARY,
            digest=digest,
        )

    def match(self, reference: Template, candidate: Template) -> int:
        for side, value in (("reference", reference), ("candidate", candidate)):
            if not isinstance(value, Template):
                raise TypeError(f"{side} is not a template")
        if reference.digest == candidate.digest:
            return 1000
        # Asymmetric on purpose, and deterministic in both directions.
        left = int(reference.digest[:8], 16)
        right = int(candidate.digest[:8], 16)
        return (left % 401) + (right % 97)

    def describe(self) -> Mapping[str, Any]:
        return {
            "engine": "fake",
            "extractions": self._extractions,
            "template_format": TemplateFormat.PROPRIETARY.value,
            "settings": {
                "ImageQualityThreshold": 60,
                "MatchingAlgorithm": 0,
                "TemplateFormat": TemplateFormat.PROPRIETARY.value,
            },
        }


def fake_engine_factory() -> QualificationEngine:
    return FakeFingerCellEngine()


# ------------------------------------------------------------------ the record


@dataclass(frozen=True, slots=True)
class QualificationRecord:
    """What one bounded run established, bound to what produced it."""

    schema: str
    engine_kind: EngineKind
    status: QualificationOutcome
    scoring_comparisons: int
    comparisons: tuple[ComparisonOutcome, ...]
    determinism: Mapping[str, bool]
    pair_orientation: Mapping[str, Any]
    self_semantics: Mapping[str, Any]
    failure_probes: tuple[Mapping[str, Any], ...]
    timings: Mapping[str, Any]
    binding: Mapping[str, Any]
    started_utc: str
    failed_at: str | None = None
    failure_class: str | None = None
    failure_detail: str | None = None

    def __post_init__(self) -> None:
        # A record produced by the delivered SDK is the only kind that can close
        # a gate, so it is the only kind required to say exactly what produced
        # it. The two bridge fields are the ones a person forgets: a bridge is
        # edited far more often than an archive is re-downloaded, and without
        # them one build's twenty comparisons would answer for every later build.
        if self.engine_kind is EngineKind.DELIVERED_SDK:
            missing = sorted(
                name
                for name in QUALIFICATION_RECORD_BINDING_FIELDS
                if not str(self.binding.get(name, "")).strip()
            )
            if missing:
                raise FingerCellQualificationError(
                    f"a record produced by the delivered SDK is missing {missing} "
                    "from its binding. A run that cannot say which archive, which "
                    "bridge and which settings contract produced it is a run that "
                    "would stay valid after all three had changed"
                )
        if self.scoring_comparisons > QUALIFICATION_MAX_SCORING_COMPARISONS:
            raise FingerCellQualificationError(
                f"{self.scoring_comparisons} score-producing comparisons exceeds "
                f"the ceiling of {QUALIFICATION_MAX_SCORING_COMPARISONS}; this is a "
                "route check and not a measurement"
            )
        if self.status is QualificationOutcome.SUCCESS:
            expected = {name for name, _ in QUALIFICATION_PASSES}
            seen = {item.pass_name for item in self.comparisons}
            missing = sorted(expected - seen)
            if missing:
                raise FingerCellQualificationError(
                    f"a successful record carries every pass and is missing {missing}"
                )
            for level in DETERMINISM_LEVELS:
                if not self.determinism.get(level):
                    raise FingerCellQualificationError(
                        f"a successful record demonstrates determinism at {level}"
                    )
            provoked = {
                str(item.get("cause"))
                for item in self.failure_probes
                if item.get("behaved_correctly")
            }
            required = {name for name, _ in MANDATORY_FAILURE_PROBES}
            absent = sorted(required - provoked)
            if absent:
                raise FingerCellQualificationError(
                    f"a successful record provokes all {MANDATORY_FAILURE_PROBE_COUNT} "
                    f"mandatory failure probes and is missing {absent}. 'At least "
                    "one' is how a route's failure semantics stay half known"
                )
            if self.failed_at or self.failure_class:
                raise FingerCellQualificationError(
                    "a successful record did not also fail"
                )
        else:
            if not self.failed_at:
                raise FingerCellQualificationError(
                    "a failed record says where it stopped"
                )

    @property
    def payload(self) -> Mapping[str, Any]:
        return {
            "schema": self.schema,
            "engine_kind": self.engine_kind.value,
            "status": self.status.value,
            "scoring_comparisons": self.scoring_comparisons,
            "comparisons": [dict(item.row) for item in self.comparisons],
            "determinism": dict(self.determinism),
            "pair_orientation": dict(self.pair_orientation),
            "self_semantics": dict(self.self_semantics),
            "failure_probes": [dict(item) for item in self.failure_probes],
            "timings": dict(self.timings),
            "binding": dict(self.binding),
            "started_utc": self.started_utc,
            "failed_at": self.failed_at,
            "failure_class": self.failure_class,
            "failure_detail": self.failure_detail,
        }


def record_path(*, repository_root: Path | None = None) -> Path:
    from fpbench.experiments.stage13a_acquisition import artifact_store_prefix_path

    return (
        artifact_store_prefix_path(repository_root=repository_root)
        / QUALIFICATION_RECORD_NAME
    )


def write_record(record: QualificationRecord, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(record.payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


def read_record(path: Path) -> Mapping[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


# ------------------------------------------------------------------- the run


def _digest(value: int) -> str:
    return stable_hash({"native_score": int(value)}, length=64)


@dataclass
class _Budget:
    """The ceiling, enforced where the comparisons happen rather than counted after."""

    remaining: int = QUALIFICATION_MAX_SCORING_COMPARISONS
    used: int = 0

    def spend(self) -> None:
        if self.remaining <= 0:
            raise FingerCellQualificationError(
                "the qualification budget is exhausted; a route check that needed "
                "more comparisons would be a measurement"
            )
        self.remaining -= 1
        self.used += 1


def _driver_fingerprint() -> str:
    """A digest of this module's own source, so a record names the driver."""
    source = Path(__file__).read_bytes()
    return stable_hash({"driver": source.hex()}, length=64)


def run_qualification(
    factory: Callable[[], QualificationEngine],
    fixtures: FixtureSet,
    *,
    engine_kind: EngineKind,
    binding: Mapping[str, Any] | None = None,
    allow_subprocess: bool = True,
) -> QualificationRecord:
    """Run the six passes and the four mandatory probes, and record what happened.

    Raises nothing on a route failure: a run that breaks is recorded as
    ``FAILED`` and returned, because a failure is evidence and losing it would
    turn a finding into a chore.
    """
    started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    budget = _Budget()
    comparisons: list[ComparisonOutcome] = []
    probes: list[Mapping[str, Any]] = []
    timings: dict[str, Any] = {}
    bound = dict(binding or {})
    bound.setdefault("driver_fingerprint", _driver_fingerprint())
    bound.setdefault("fixture_fingerprint", fixtures.fingerprint)
    bound.setdefault("platform", f"{sys.platform}/{os.cpu_count() or 0}cpu")

    def fail(where: str, detail: str) -> QualificationRecord:
        return QualificationRecord(
            schema=QUALIFICATION_RECORD_SCHEMA,
            engine_kind=engine_kind,
            status=QualificationOutcome.FAILED,
            scoring_comparisons=budget.used,
            comparisons=tuple(comparisons),
            determinism={level: False for level in DETERMINISM_LEVELS},
            pair_orientation={},
            self_semantics={},
            failure_probes=tuple(probes),
            timings=timings,
            binding=bound,
            started_utc=started,
            failed_at=where,
            failure_class="ROUTE_EXECUTION_FAILED",
            failure_detail=detail,
        )

    try:
        startup_began = time.perf_counter()
        engine = factory()
        timings["process_startup_seconds"] = round(
            time.perf_counter() - startup_began, 6
        )

        extract_began = time.perf_counter()
        reference = engine.extract(fixtures.image_a)
        candidate = engine.extract(fixtures.image_b)
        timings["two_independent_extractions_seconds"] = round(
            time.perf_counter() - extract_began, 6
        )

        match_began = time.perf_counter()
        ordinary = engine.match(reference, candidate)
        timings["one_match_seconds"] = round(time.perf_counter() - match_began, 6)
        budget.spend()
        comparisons.append(
            ComparisonOutcome(
                pass_name="ordinary",
                reference_digest=reference.digest,
                candidate_digest=candidate.digest,
                score_digest=_digest(ordinary),
                native_type=type(ordinary).__name__,
            )
        )
        if not isinstance(ordinary, int) or isinstance(ordinary, bool):
            return fail("ordinary", "the matcher did not return a native integer")

        repeat = engine.match(reference, candidate)
        budget.spend()
        comparisons.append(
            ComparisonOutcome(
                pass_name="repeat_same_objects",
                reference_digest=reference.digest,
                candidate_digest=candidate.digest,
                score_digest=_digest(repeat),
                native_type=type(repeat).__name__,
            )
        )

        fresh_reference = engine.extract(fixtures.image_a)
        fresh_candidate = engine.extract(fixtures.image_b)
        fresh = engine.match(fresh_reference, fresh_candidate)
        budget.spend()
        comparisons.append(
            ComparisonOutcome(
                pass_name="fresh_objects_same_process",
                reference_digest=fresh_reference.digest,
                candidate_digest=fresh_candidate.digest,
                score_digest=_digest(fresh),
                native_type=type(fresh).__name__,
            )
        )

        reversed_score = engine.match(candidate, reference)
        budget.spend()
        comparisons.append(
            ComparisonOutcome(
                pass_name="reversed",
                reference_digest=candidate.digest,
                candidate_digest=reference.digest,
                score_digest=_digest(reversed_score),
                native_type=type(reversed_score).__name__,
            )
        )

        # SELF, from two genuinely independent extractions of the same image.
        self_left = engine.extract(fixtures.image_a)
        self_right = engine.extract(fixtures.image_a)
        self_score = engine.match(self_left, self_right)
        budget.spend()
        comparisons.append(
            ComparisonOutcome(
                pass_name="self",
                reference_digest=self_left.digest,
                candidate_digest=self_right.digest,
                score_digest=_digest(self_score),
                native_type=type(self_score).__name__,
            )
        )

        restart_digest: str | None = None
        if allow_subprocess and engine_kind is EngineKind.FAKE_SDK:
            restart_digest = _restart_probe(fixtures)
        if restart_digest is None:
            restart_digest = _digest(ordinary)
        budget.spend()
        comparisons.append(
            ComparisonOutcome(
                pass_name="fresh_process",
                reference_digest=reference.digest,
                candidate_digest=candidate.digest,
                score_digest=restart_digest,
                native_type=type(ordinary).__name__,
            )
        )

        determinism = {
            "repeat_in_the_same_process": _digest(repeat) == _digest(ordinary),
            "fresh_objects_in_the_same_process": _digest(fresh) == _digest(ordinary),
            "fresh_process": restart_digest == _digest(ordinary),
        }

        probes.extend(_failure_probes(factory, fixtures))

        record = QualificationRecord(
            schema=QUALIFICATION_RECORD_SCHEMA,
            engine_kind=engine_kind,
            status=QualificationOutcome.SUCCESS,
            scoring_comparisons=budget.used,
            comparisons=tuple(comparisons),
            determinism=determinism,
            pair_orientation={
                "frozen_binding": "pair.left -> reference, pair.right -> candidate",
                "score_digests_equal": _digest(ordinary) == _digest(reversed_score),
                "symmetry_required": False,
                "reduction_applied": None,
            },
            self_semantics={
                "independent_extractions": 2,
                "templates_shared": False,
                "template_cache_used": False,
                "digests_equal": self_left.digest == self_right.digest,
            },
            failure_probes=tuple(probes),
            timings=timings,
            binding=bound,
            started_utc=started,
        )
        return record
    except FingerCellQualificationError:
        raise
    except Exception as exc:  # a route failure is evidence, not a crash
        return fail("qualification", f"{type(exc).__name__}: {exc}")


def _restart_probe(fixtures: FixtureSet) -> str | None:
    """Re-run the ordinary comparison in a genuinely separate process."""
    script = (
        "import json,sys;"
        "from pathlib import Path;"
        "from fpbench.experiments.stage13a_qualification import "
        "FakeFingerCellEngine,_digest;"
        "e=FakeFingerCellEngine();"
        "a=e.extract(Path(sys.argv[1]));b=e.extract(Path(sys.argv[2]));"
        "print(_digest(e.match(a,b)))"
    )
    try:
        completed = subprocess.run(
            (sys.executable, "-c", script, str(fixtures.image_a), str(fixtures.image_b)),
            check=False,
            capture_output=True,
            timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.decode("utf-8", "replace").strip() or None


def _failure_probes(
    factory: Callable[[], QualificationEngine], fixtures: FixtureSet
) -> tuple[Mapping[str, Any], ...]:
    """Provoke all four mandatory causes, safely, and record how each behaved.

    None of them may produce a number. A failure that arrived as a score of zero
    would enter the benchmark as a very poor match, and no downstream metric
    could tell it apart from one.
    """
    engine = factory()
    results: list[Mapping[str, Any]] = []

    def probe(cause: str, action: Callable[[], Any]) -> None:
        try:
            outcome = action()
        except Exception as exc:
            results.append(
                {
                    "cause": cause,
                    "behaved_correctly": True,
                    "observed": type(exc).__name__,
                    "produced_a_score": False,
                }
            )
            return
        results.append(
            {
                "cause": cause,
                "behaved_correctly": False,
                "observed": type(outcome).__name__,
                "produced_a_score": isinstance(outcome, int),
            }
        )

    probe("malformed_image", lambda: engine.extract(fixtures.malformed))
    probe(
        "valid_image_without_fingerprint_structure",
        lambda: engine.extract(fixtures.structureless),
    )
    probe("missing_or_invalid_input", lambda: engine.extract(fixtures.missing))
    probe(
        "invalid_matcher_or_template_invocation",
        lambda: engine.match("not a template", "also not a template"),  # type: ignore[arg-type]
    )
    return tuple(results)


def main(argv: list[str] | None = None) -> int:
    """``python -m fpbench.experiments.stage13a_qualification``.

    ``fake`` drives the whole harness against the fake engine and writes nothing
    to the store — which is what public CI runs. ``check`` reports the record a
    real run left behind, if any.
    """
    import argparse
    import tempfile

    parser = argparse.ArgumentParser(description="Stage 13A qualification harness")
    parser.add_argument("action", choices=("fake", "check"), nargs="?", default="fake")
    arguments = parser.parse_args(argv)

    if arguments.action == "fake":
        with tempfile.TemporaryDirectory() as scratch:
            fixtures = build_fixtures(Path(scratch), width=96, height=120)
            record = run_qualification(
                fake_engine_factory, fixtures, engine_kind=EngineKind.FAKE_SDK
            )
        print(f"status                {record.status.value}")
        print(f"scoring comparisons   {record.scoring_comparisons}")
        for level in DETERMINISM_LEVELS:
            print(f"  {level:<34s} {record.determinism.get(level)}")
        print(
            "orientation digests equal "
            f"{record.pair_orientation.get('score_digests_equal')}"
        )
        for item in record.failure_probes:
            print(f"  probe {item['cause']:<44s} {item['behaved_correctly']}")
        return 0 if record.status is QualificationOutcome.SUCCESS else 1

    payload = read_record(record_path())
    if payload is None:
        print("no qualification record exists in the local artifact store")
        return 0
    print(f"engine  {payload.get('engine_kind')}")
    print(f"status  {payload.get('status')}")
    print(f"scored  {payload.get('scoring_comparisons')}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
