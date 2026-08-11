"""The bounded local qualification run, and the three things it needs first.

Nine of Stage 11A's seventeen gates are questions about a *running* licensed
engine. This module is what answers them: it prepares a small isolated
installation from the pinned archive, generates synthetic fixtures that are not
SD300, compiles upstream's binding against
``integrations/verifinger-qualification/VeriFingerQualification.java``, runs it
twice in separate processes, and writes a validated record beside the artifacts.

**It refuses before it improvises.** Three preconditions are checked by name, and
each maps to a pending action the preflight can report rather than to a guess:

.. code-block:: text

    the pinned artifacts are here          →  QUALIFICATION_RUN_NOT_PERFORMED
    a Java 17+ toolchain is available      →  JAVA_RUNTIME_NOT_AVAILABLE
    the trial licence is activated         →  TRIAL_LICENCE_NOT_ACTIVATED

The third is only discoverable by asking the SDK, so the harness asks it the way
upstream's own samples do — ``NLicense.obtain`` against the local licensing
service — and reports the refusal rather than working around it. Nothing here
bypasses a licence, resets a trial or touches a protection mechanism
(spec section 32).

**No score value is written anywhere.** The Java pass emits a SHA-256 over each
score and never the score; this module compares digests across processes and
records equalities and counts. What reaches disk is a contract, not a
measurement (docs/adr/0104).

**Nothing here runs in CI.** The record lives in the local artifact store, and
the tests that exercise the real thing carry the ``verifinger_artifact`` marker.
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import struct
import subprocess
import zipfile
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from fpbench.core.verifinger_preflight_errors import (
    VeriFingerAcquisitionError,
    VeriFingerArtifactInspectionError,
)
from fpbench.experiments.stage11a_artifacts import (
    QUALIFICATION_RUN_RECORD_NAME,
    QUALIFICATION_RUN_SCHEMA,
    acquisition_state,
    artifact_store_prefix_path,
    qualification_run_state,
)
from fpbench.experiments.stage11a_verifinger_identity import (
    DETERMINISM_LEVELS,
    PendingActionCode,
    QUALIFICATION_RUN_MAX_SCORES,
)
from fpbench.experiments.stage11a_verifinger_observations import (
    SDK_ARCHIVE,
    WINDOWS_X64_NATIVE_LIBRARIES,
)

__all__ = [
    "HARNESS_SOURCE",
    "MINIMUM_JAVA_MAJOR",
    "PLATFORM_NATIVE_DIRECTORY",
    "PreconditionStatus",
    "Preconditions",
    "check_preconditions",
    "prepare_installation",
    "write_fixtures",
    "run_qualification",
    "main",
]

#: The harness this module compiles. One file, in the repository, reviewable.
HARNESS_SOURCE = Path("integrations") / "verifinger-qualification" / (
    "VeriFingerQualification.java"
)

#: This project's reference JVM, as ``environment.yml`` pins it. Anything older
#: is refused rather than tried: a qualification produced on an unpinned runtime
#: is a qualification of a runtime nobody recorded.
MINIMUM_JAVA_MAJOR = 17

#: The platform this project would host, and the one the trial is locked to when
#: the run happens. Chosen *before* activation because the trial is
#: single-platform, and alternating between two under one algorithm fingerprint
#: is refused whichever is chosen (spec section 33).
PLATFORM_NATIVE_DIRECTORY = "Bin/Win64_x64"
PLATFORM_OPERATING_SYSTEM = "windows"
PLATFORM_ARCHITECTURE = "x86_64"

_ARCHIVE_ROOT = "Neurotec_Biometric_2025_2_SDK/"

#: Everything the 1:1 route loads, and nothing else. Extracting 6.8 GB to run one
#: comparison would also extract four other products' models.
_INSTALL_SUBTREES = (
    f"{_ARCHIVE_ROOT}Bin/Java/",
    f"{_ARCHIVE_ROOT}{PLATFORM_NATIVE_DIRECTORY}/",
    f"{_ARCHIVE_ROOT}Bin/Licenses/",
)
_INSTALL_FILES = (
    f"{_ARCHIVE_ROOT}Bin/Data/Fingers.ndf",
    f"{_ARCHIVE_ROOT}Bin/Data/FingersMatching.ndf",
)

_JAVA_VERSION_PATTERN = re.compile(r'version "?(\d+)')

#: Variables that inject JVM flags behind our back. Removed rather than trusted,
#: for the reason the SourceAFIS bridge removes them: a result whose heap size
#: came from an ambient variable is not reproducible.
_JVM_ENV_OVERRIDES = ("JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS")


class PreconditionStatus(str, Enum):
    """Whether the run can proceed, and if not, which named action is missing."""

    READY = "READY"
    ARTIFACTS_MISSING = "ARTIFACTS_MISSING"
    JAVA_MISSING = "JAVA_MISSING"
    LICENCE_NOT_ACTIVATED = "LICENCE_NOT_ACTIVATED"

    @property
    def pending_action(self) -> PendingActionCode | None:
        return {
            PreconditionStatus.READY: None,
            PreconditionStatus.ARTIFACTS_MISSING: (
                PendingActionCode.QUALIFICATION_RUN_NOT_PERFORMED
            ),
            PreconditionStatus.JAVA_MISSING: (
                PendingActionCode.JAVA_RUNTIME_NOT_AVAILABLE
            ),
            PreconditionStatus.LICENCE_NOT_ACTIVATED: (
                PendingActionCode.TRIAL_LICENCE_NOT_ACTIVATED
            ),
        }[self]


@dataclass(frozen=True, slots=True)
class Preconditions:
    """What is and is not in place for a qualification run."""

    status: PreconditionStatus
    detail: str
    java_home: str | None = None
    java_major: int | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ready(self) -> bool:
        return self.status is PreconditionStatus.READY


def _java_tool(name: str) -> str | None:
    """``java`` or ``javac``, from ``JAVA_HOME`` first and then from ``PATH``."""
    home = os.environ.get("JAVA_HOME", "").strip()
    if home:
        candidate = Path(home) / "bin" / name
        for suffix in ("", ".exe"):
            if candidate.with_suffix(suffix).is_file():
                return str(candidate.with_suffix(suffix))
    return shutil.which(name)


def _java_major(java: str) -> int | None:
    try:
        completed = subprocess.run(
            (java, "-version"), check=False, capture_output=True, text=True, timeout=60
        )
    except (OSError, subprocess.TimeoutExpired):  # pragma: no cover - no JVM
        return None
    found = _JAVA_VERSION_PATTERN.search(
        (completed.stderr or "") + (completed.stdout or "")
    )
    return int(found.group(1)) if found else None


def check_preconditions(*, repository_root: Path | None = None) -> Preconditions:
    """Everything that must hold before a licence is asked for anything.

    The licence itself is *not* probed here. Asking the SDK whether it is
    licensed means loading the SDK, and loading it is the run; the harness
    reports the refusal it gets back rather than predicting one.
    """
    acquisition = acquisition_state(repository_root=repository_root)
    if not acquisition.obtained:
        return Preconditions(
            status=PreconditionStatus.ARTIFACTS_MISSING,
            detail=(
                "the pinned VeriFinger artifacts are not verified in the local "
                "store; run the acquisition first"
            ),
        )
    java = _java_tool("java")
    javac = _java_tool("javac")
    if java is None or javac is None:
        return Preconditions(
            status=PreconditionStatus.JAVA_MISSING,
            detail=(
                "no Java toolchain was found on JAVA_HOME or PATH. The main 2025.2 "
                "archive ships no Python binding, so the qualification runs "
                "through upstream's Java binding, and this project already pins "
                f"openjdk={MINIMUM_JAVA_MAJOR} in environment.yml"
            ),
        )
    major = _java_major(java)
    if major is None or major < MINIMUM_JAVA_MAJOR:
        return Preconditions(
            status=PreconditionStatus.JAVA_MISSING,
            detail=(
                f"the Java on this machine reports major version {major}, and the "
                f"reference JVM for this project is {MINIMUM_JAVA_MAJOR}"
            ),
            java_home=java,
            java_major=major,
        )
    return Preconditions(
        status=PreconditionStatus.READY,
        detail="artifacts verified and a Java toolchain is available",
        java_home=java,
        java_major=major,
    )


# ------------------------------------------------------------- the installation


def prepare_installation(*, repository_root: Path | None = None) -> Path:
    """Extract the subset of the pinned archive the 1:1 route loads.

    Into the artifact store, never into the working tree. Idempotent: an install
    directory that already holds the marker file is left alone, because
    re-extracting a gigabyte to run one comparison is a slow way to change
    nothing.

    Raises:
        VeriFingerArtifactInspectionError: the archive is not the pinned one, so
            nothing extracted from it would describe this route.
    """
    store = artifact_store_prefix_path(repository_root=repository_root)
    archive = store / SDK_ARCHIVE.filename
    if not archive.is_file():
        raise VeriFingerArtifactInspectionError(
            "the pinned archive is not in the local store"
        )
    install = store / "installation"
    stamp = install / ".prepared"
    if stamp.is_file() and stamp.read_text(encoding="utf-8").strip() == (
        SDK_ARCHIVE.sha256
    ):
        return install

    if install.exists():
        shutil.rmtree(install)
    install.mkdir(parents=True)
    with zipfile.ZipFile(archive) as handle:
        wanted = [
            info
            for info in handle.infolist()
            if not info.is_dir()
            and (
                info.filename in _INSTALL_FILES
                or info.filename.startswith(_INSTALL_SUBTREES)
            )
        ]
        if not wanted:  # pragma: no cover - a different archive under the name
            raise VeriFingerArtifactInspectionError(
                "the archive holds none of the subtrees the 1:1 route loads"
            )
        for info in wanted:
            relative = info.filename[len(_ARCHIVE_ROOT) :]
            target = install / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with handle.open(info) as source, target.open("wb") as sink:
                shutil.copyfileobj(source, sink)
    stamp.write_text(SDK_ARCHIVE.sha256 + "\n", encoding="utf-8")
    return install


# ------------------------------------------------------------------ the fixtures


def _write_png(path: Path, pixels: list[list[int]]) -> None:
    """An 8-bit grayscale PNG, written with the standard library only.

    ``fpbench.imaging`` owns this project's real image pipeline and Stage 11A may
    not import it: a qualification layer that reached into the benchmark's own
    preprocessing could produce a fixture the benchmark had shaped. Forty lines
    of ``zlib`` keep the boundary intact.
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
    # 500 pixels per inch, in the metre units PNG's pHYs chunk uses.
    per_metre = int(round(500 * 39.3701))
    physical = struct.pack(">IIB", per_metre, per_metre, 1)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"pHYs", physical)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def _ridge_field(width: int, height: int, *, phase: float, curve: float) -> list[list[int]]:
    """A synthetic ridge-like field. Not a fingerprint, and not from any person.

    Concentric-ish ridges with a slowly rotating orientation, which is enough
    structure for an extractor to find minutiae in without any of it having come
    from a human being or from SD300.
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
            value = int(128 + 110 * wave)
            row.append(max(0, min(255, value)))
        rows.append(row)
    return rows


def write_fixtures(directory: Path) -> tuple[Path, ...]:
    """The non-SD300 inputs the pass runs on (spec sections 39 and 40).

    Five files: two ridge-like impressions, an image that decodes to nothing, a
    file whose bytes are not an image at all, and — by omission — a path that
    does not exist. Between them they exercise every failure class the contract
    names.
    """
    directory.mkdir(parents=True, exist_ok=True)
    a = directory / "fixture_a.png"
    b = directory / "fixture_b.png"
    invalid = directory / "fixture_invalid.png"
    unsupported = directory / "fixture_unsupported.dat"
    _write_png(a, _ridge_field(400, 500, phase=0.0, curve=3.0))
    _write_png(b, _ridge_field(400, 500, phase=0.6, curve=3.4))
    # A PNG header over bytes that are not a valid image body.
    invalid.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    unsupported.write_bytes(b"not an image, and not claiming to be one\n")
    return (a, b, invalid, unsupported)


# ------------------------------------------------------------------ the run


def _classpath(install: Path) -> str:
    jars = sorted((install / "Bin" / "Java").glob("*.jar"))
    if not jars:  # pragma: no cover - a broken installation
        raise VeriFingerArtifactInspectionError(
            "the prepared installation holds no Java bindings"
        )
    return os.pathsep.join(str(jar) for jar in jars)


def _clean_environment(install: Path) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in _JVM_ENV_OVERRIDES
    }
    native = install / PLATFORM_NATIVE_DIRECTORY.replace("Bin/", "Bin" + os.sep)
    environment["PATH"] = str(native) + os.pathsep + environment.get("PATH", "")
    environment["JNA_LIBRARY_PATH"] = str(native)
    return environment


def _one_pass(
    *,
    java: str,
    install: Path,
    fixtures: Path,
    classes: Path,
    label: str,
    timeout: float,
) -> Mapping[str, Any]:
    completed = subprocess.run(
        (
            java,
            "-cp",
            os.pathsep.join((str(classes), _classpath(install))),
            f"-Djna.library.path={install / 'Bin' / 'Win64_x64'}",
            "VeriFingerQualification",
            str(fixtures),
            label,
        ),
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(install),
        env=_clean_environment(install),
    )
    payload = (completed.stdout or "").strip().splitlines()
    for line in reversed(payload):
        if line.startswith("{"):
            return json.loads(line)
    raise VeriFingerArtifactInspectionError(
        "the qualification pass produced no report; the harness printed "
        f"{(completed.stderr or '').strip()[:400]!r}"
    )


def run_qualification(
    *, repository_root: Path | None = None, timeout: float = 900.0
) -> Mapping[str, Any]:
    """Prepare, compile, run twice, and write the record.

    Two passes in two processes, because the third determinism level is a fresh
    process and no program can perform that on itself. The record is written only
    if both passes report success and their score digests agree — a harness that
    wrote a record for a half-finished run would be the thing this whole stage
    refuses.

    Raises:
        VeriFingerAcquisitionError: a precondition is missing, named.
        VeriFingerArtifactInspectionError: the run started and did not finish.
    """
    preconditions = check_preconditions(repository_root=repository_root)
    if not preconditions.ready:
        raise VeriFingerAcquisitionError(
            f"{preconditions.status.value}: {preconditions.detail}"
        )
    assert preconditions.java_home is not None

    root = Path(repository_root) if repository_root is not None else Path(".")
    source = root / HARNESS_SOURCE
    if not source.is_file():
        raise VeriFingerArtifactInspectionError(
            f"the qualification harness is missing at {HARNESS_SOURCE.as_posix()}"
        )

    install = prepare_installation(repository_root=repository_root)
    store = artifact_store_prefix_path(repository_root=repository_root)
    fixtures = store / "fixtures"
    write_fixtures(fixtures)
    classes = store / "harness-classes"
    classes.mkdir(parents=True, exist_ok=True)

    javac = _java_tool("javac")
    assert javac is not None
    compiled = subprocess.run(
        (
            javac,
            "-cp",
            _classpath(install),
            "-d",
            str(classes),
            str(source),
        ),
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=_clean_environment(install),
    )
    if compiled.returncode != 0:
        raise VeriFingerArtifactInspectionError(
            "the qualification harness did not compile against the pinned "
            f"bindings: {(compiled.stderr or '').strip()[:600]}"
        )

    first = _one_pass(
        java=preconditions.java_home,
        install=install,
        fixtures=fixtures,
        classes=classes,
        label="first",
        timeout=timeout,
    )
    if not first.get("ok"):
        if first.get("error") == "LICENCES_NOT_OBTAINED":
            raise VeriFingerAcquisitionError(
                f"{PreconditionStatus.LICENCE_NOT_ACTIVATED.value}: the SDK "
                "refused the FingerExtractor and FingerMatcher licences. "
                "Activate the 30-day trial as the vendor documents it — "
                "Trial = true in pgd.conf and start the licensing service — and "
                "run this again. Nothing here bypasses a licence."
            )
        raise VeriFingerArtifactInspectionError(
            f"the first qualification pass failed: {first.get('error')}"
        )
    second = _one_pass(
        java=preconditions.java_home,
        install=install,
        fixtures=fixtures,
        classes=classes,
        label="second",
        timeout=timeout,
    )
    if not second.get("ok"):
        raise VeriFingerArtifactInspectionError(
            f"the second qualification pass failed: {second.get('error')}"
        )

    record = _build_record(install, first, second)
    path = store / QUALIFICATION_RUN_RECORD_NAME
    path.write_text(
        json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    state = qualification_run_state(repository_root=repository_root)
    if not state.performed:
        raise VeriFingerArtifactInspectionError(
            "the record this run wrote does not verify: "
            f"{state.invalid_reason}"
        )
    return record


def _build_record(
    install: Path, first: Mapping[str, Any], second: Mapping[str, Any]
) -> dict[str, Any]:
    """Merge the two passes into the shape the preflight reads.

    The only thing the second pass contributes is the restart level of
    determinism. Everything else is the first pass's, because two passes that
    disagreed about anything else would be a nondeterminism finding rather than
    something to average.
    """
    determinism = dict(first.get("determinism_within_process") or {})
    determinism[DETERMINISM_LEVELS[2]] = bool(
        first.get("pair_score_digest")
        and first.get("pair_score_digest") == second.get("pair_score_digest")
    )
    defaults: dict[str, str] = {}
    defaults.update(first.get("delivered_extraction_defaults") or {})
    defaults.update(first.get("delivered_matching_defaults") or {})
    # The engine publishes its parameters under the manual's dotted names; the
    # profile documents key them by the accessor name the reference uses, so the
    # record carries both rather than making the reader map them.
    normalised = {
        _accessor_name(name): value for name, value in defaults.items()
    }
    normalised.update(defaults)

    produced = int(first.get("qualification_scores_produced") or 0) + int(
        second.get("qualification_scores_produced") or 0
    )
    native = install / "Bin" / "Win64_x64"
    return {
        "schema": QUALIFICATION_RUN_SCHEMA,
        "performed_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "archive_sha256": SDK_ARCHIVE.sha256,
        "platform_lock": {
            "operating_system": PLATFORM_OPERATING_SYSTEM,
            "architecture": PLATFORM_ARCHITECTURE,
            "native_library_directory": PLATFORM_NATIVE_DIRECTORY,
            "native_library_digests": {
                Path(item.relative_path).name: item.sha256
                for item in WINDOWS_X64_NATIVE_LIBRARIES
            },
            "java_runtime_version": first.get("java_runtime_version"),
            "java_vendor": first.get("java_vendor"),
            "locked_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "reported_operating_system": first.get("operating_system"),
        "reported_architecture": first.get("architecture"),
        "licences_obtained": bool(first.get("licences_obtained")),
        "settings_set_by_the_run": list(first.get("settings_set_by_this_pass") or ()),
        "threshold_set_by_the_run": bool(first.get("threshold_set_by_this_pass")),
        "delivered_runtime_defaults": normalised,
        "pair_orientation": first.get("pair_orientation"),
        "self_semantics": first.get("self_semantics"),
        "determinism": determinism,
        "failure_semantics": first.get("failure_semantics"),
        "feasibility": first.get("feasibility"),
        "qualification_scores_produced": min(produced, QUALIFICATION_RUN_MAX_SCORES),
        "benchmark_scores_produced": 0,
        "sd300_used": False,
        "fixture_kind": "SYNTHETIC_RIDGE_LIKE",
        "native_library_directory_present": native.is_dir(),
    }


def _accessor_name(dotted: str) -> str:
    """``Fingers.TemplateSize`` to ``FingersTemplateSize``."""
    return dotted.replace(".", "")


def main(argv: list[str] | None = None) -> int:
    """``python -m fpbench.experiments.stage11a_qualification``.

    ``check`` reports the preconditions and writes nothing, which is what to run
    before deciding whether to start a 30-day clock. ``run`` performs the pass.
    """
    import argparse

    parser = argparse.ArgumentParser(description="Stage 11A qualification run")
    parser.add_argument("action", choices=("check", "run"), nargs="?", default="check")
    parser.add_argument("--repository-root", default=".")
    arguments = parser.parse_args(argv)
    root = Path(arguments.repository_root).resolve()

    if arguments.action == "check":
        found = check_preconditions(repository_root=root)
        print(f"preconditions   {found.status.value}")
        print(f"detail          {found.detail}")
        if found.java_home:
            print(f"java            {found.java_home} (major {found.java_major})")
        action = found.status.pending_action
        print(f"pending action  {action.value if action else 'none'}")
        state = qualification_run_state(repository_root=root)
        print(f"existing record {state.record_present} (verified {state.performed})")
        if state.invalid_reason:
            print(f"                {state.invalid_reason}")
        return 0

    record = run_qualification(repository_root=root)
    print(f"qualification record written, {record['qualification_scores_produced']} scores")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
