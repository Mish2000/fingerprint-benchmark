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

import hashlib
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
    FAILURE_SEMANTICS_CAUSES,
    FIXTURE_VERSION,
    PendingActionCode,
    QUALIFICATION_RUN_MAX_SCORES,
    QualificationOutcome,
)
from fpbench.experiments.stage11a_verifinger_observations import (
    FINGER_DATA_FILES,
    JAVA_BINDING_JARS,
    SDK_ARCHIVE,
    WINDOWS_X64_NATIVE_LIBRARIES,
)

__all__ = [
    "HARNESS_SOURCE",
    "DRIVER_SOURCE",
    "MINIMUM_JAVA_MAJOR",
    "PLATFORM_NATIVE_DIRECTORY",
    "PreconditionStatus",
    "Preconditions",
    "check_preconditions",
    "prepare_installation",
    "verify_installation_digests",
    "loaded_component_fingerprint",
    "inputs_fingerprint",
    "write_fixtures",
    "write_vendor_fallback_fixtures",
    "run_qualification",
    "main",
]

#: The harness this module compiles. One file, in the repository, reviewable.
HARNESS_SOURCE = Path("integrations") / "verifinger-qualification" / (
    "VeriFingerQualification.java"
)

#: This module's own source. Part of the run's identity, because the driver
#: decides which passes run, which fixtures they see and how their answers are
#: merged — all of which can change what a record says (spec correction 3).
DRIVER_SOURCE = Path("src") / "fpbench" / "experiments" / "stage11a_qualification.py"

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


def _digest_of(path: Path) -> str:
    """A digest over the bytes on disk, for binaries."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _source_digest_of(path: Path) -> str:
    """A digest over one *source* file, with newlines normalised.

    ``core.autocrlf`` is on for this repository, so the same committed blob is
    LF in one checkout and CRLF in another. A raw digest over the harness and
    the driver would therefore move on a fresh checkout with no code change at
    all, and the record's identity check would demand a re-run every time —
    which is how a check that should be trusted becomes one that gets switched
    off. This is the same normalisation the stage finalization already applies
    to its own source set.

    Binaries stay raw under :func:`_digest_of`: normalising bytes inside a jar
    or a ``.ndf`` would corrupt the thing being identified.
    """
    content = Path(path).read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(content).hexdigest()


def verify_installation_digests(install: Path) -> dict[str, str]:
    """Re-hash what was extracted, before anything loads it.

    Extraction is not verification: a truncated write, a partially replaced
    directory or a stale tree from an earlier archive would all produce files
    that exist. Every component this stage pinned by digest is re-read from the
    installation and compared, and the CRC-32 the archive recorded is checked for
    everything else (spec correction 4).

    Returns:
        The digest of every verified component, keyed by its path inside the
        installation — which is also what the run's identity is computed over.

    Raises:
        VeriFingerArtifactInspectionError: a file is missing or is not the bytes
            the archive said it was.
    """
    pinned = {
        item.relative_path.split("/", 1)[1]: item.sha256
        for item in (
            *WINDOWS_X64_NATIVE_LIBRARIES,
            *FINGER_DATA_FILES,
            *JAVA_BINDING_JARS,
        )
    }
    verified: dict[str, str] = {}
    for relative, expected in sorted(pinned.items()):
        target = install / Path(relative)
        if not target.is_file():
            raise VeriFingerArtifactInspectionError(
                f"the prepared installation is missing {relative}, which this "
                "stage pinned by digest"
            )
        found = _digest_of(target)
        if found != expected:
            raise VeriFingerArtifactInspectionError(
                f"{relative} in the prepared installation is not the bytes the "
                "pinned archive holds; nothing loaded from this tree would "
                "describe the qualified route"
            )
        verified[relative] = found
    return verified


def loaded_component_fingerprint(install: Path) -> str:
    """One digest over every component the route loads."""
    return _stable_digest(verify_installation_digests(install))


def _stable_digest(value: Mapping[str, str]) -> str:
    payload = "\n".join(f"{key}={value[key]}" for key in sorted(value))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def inputs_fingerprint(install: Path, *, repository_root: Path | None = None) -> str:
    """What produced this record, in one digest (spec correction 3).

    The archive, every component actually loaded, the Java harness, this driver
    and the fixture version. A record that cannot say which bytes produced it is
    a record about nothing in particular — and each of these five can change a
    score or change which questions were asked.
    """
    root = Path(repository_root) if repository_root is not None else Path(".")
    return _stable_digest(
        {
            "sdk_archive": SDK_ARCHIVE.sha256,
            "loaded_components": loaded_component_fingerprint(install),
            "java_harness": _source_digest_of(root / HARNESS_SOURCE),
            "python_driver": _source_digest_of(root / DRIVER_SOURCE),
            "fixture_version": FIXTURE_VERSION,
        }
    )


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
    """The non-SD300 inputs the passes run on (spec sections 39 and 40).

    Five files, each with a job. Two ridge-like impressions carry the route
    itself. A uniform grey image decodes perfectly and contains no ridge at all,
    which is the controlled cause for an extraction failure — and, used as a
    reference side, for a matcher failure. A PNG signature over a broken body is
    the controlled cause for an invalid image. A file that is not an image in any
    container is the controlled cause for an unsupported one.

    The two remaining failure classes are about a runtime that is missing
    something, so their causes are whole processes rather than files.
    """
    directory.mkdir(parents=True, exist_ok=True)
    a = directory / "fixture_a.png"
    b = directory / "fixture_b.png"
    blank = directory / "fixture_blank.png"
    invalid = directory / "fixture_invalid.png"
    unsupported = directory / "fixture_unsupported.dat"
    _write_png(a, _ridge_field(400, 500, phase=0.0, curve=3.0))
    _write_png(b, _ridge_field(400, 500, phase=0.6, curve=3.4))
    _write_png(blank, [[128] * 400 for _ in range(500)])
    # A PNG signature over bytes that are not a valid image body.
    invalid.write_bytes(bytes((0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A)) + b"\x00" * 64)
    unsupported.write_bytes(b"not an image, and not claiming to be one\n")
    return (a, b, blank, invalid, unsupported)


#: Upstream's own tutorial inputs, inside the pinned archive. The named fallback
#: for a synthetic fixture the extractor will not accept (spec section 39).
#:
#: They stay in the local artifact store like every other vendor byte, and the
#: repository's byte guard refuses them by digest and by the archive-tree path
#: they carry.
_VENDOR_SAMPLE_MEMBERS = (
    (
        "vendor_a.png",
        f"{_ARCHIVE_ROOT}Tutorials/Biometrics/Android/"
        "biometrics-tutorials-android/src/main/assets/input/finger1.png",
    ),
    (
        "vendor_b.png",
        f"{_ARCHIVE_ROOT}Tutorials/Biometrics/Android/"
        "biometrics-tutorials-android/src/main/assets/input/finger2.png",
    ),
)


def write_vendor_fallback_fixtures(
    directory: Path, *, repository_root: Path | None = None
) -> dict[str, str]:
    """Place upstream's own sample fingerprints beside the synthetic ones.

    Extracted from the pinned archive rather than downloaded, so they are covered
    by the archive digest the record already binds. The harness uses them only
    when the synthetic pair will not extract, and records which kind it used.

    Returns:
        The digest of each sample, for the record to carry.
    """
    store = artifact_store_prefix_path(repository_root=repository_root)
    archive = store / SDK_ARCHIVE.filename
    digests: dict[str, str] = {}
    directory.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as handle:
        for name, member in _VENDOR_SAMPLE_MEMBERS:
            target = directory / name
            with handle.open(member) as source, target.open("wb") as sink:
                shutil.copyfileobj(source, sink)
            digests[name] = _digest_of(target)
    return digests


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


def _write_record(store_path: Path, record: dict[str, Any]) -> Path:
    path = store_path / QUALIFICATION_RUN_RECORD_NAME
    path.write_text(
        json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


def _failed_record(
    install: Path,
    *,
    repository_root: Path | None,
    stage: str,
    detail: str,
    passes: Mapping[str, Any],
) -> dict[str, Any]:
    """A run that started and did not finish, written down as a finding.

    The single most important record this module can produce, and the one an
    earlier version could not: a harness whose failure looked the same as its
    absence could never move this stage off ``INCOMPLETE``. A ``FAILED`` record
    says the runtime started, names the step it died at, and turns into a real
    blocker rather than an outstanding chore (spec correction 5).
    """
    return {
        "schema": QUALIFICATION_RUN_SCHEMA,
        "outcome": QualificationOutcome.FAILED.value,
        "performed_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "archive_sha256": SDK_ARCHIVE.sha256,
        "inputs_fingerprint": inputs_fingerprint(
            install, repository_root=repository_root
        ),
        "fixture_version": FIXTURE_VERSION,
        "runtime_started": True,
        "failed_at_stage": stage,
        "failure_detail": detail,
        "passes_attempted": dict(passes),
        "sd300_used": False,
        "benchmark_scores_produced": 0,
        "qualification_scores_produced": 0,
    }


def run_qualification(
    *, repository_root: Path | None = None, timeout: float = 1800.0
) -> Mapping[str, Any]:
    """Prepare, verify, compile, run four passes, and write the record.

    Four passes because the questions need different runtimes. ``full`` and
    ``restart`` are the same route in two processes, which is the only way to
    settle the third determinism level. ``no-models`` runs against an
    installation with the fingerprint data file withheld, and ``no-licence``
    against a complete one with no licence obtained — the controlled causes for
    the two failure classes that are about a runtime missing something.

    If the runtime starts and something then goes wrong, a ``FAILED`` record is
    written rather than none, so the preflight reports a real blocker instead of
    returning to "nobody has run it".

    Raises:
        VeriFingerAcquisitionError: a precondition is missing, named. Nothing has
            started, so nothing is recorded.
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
    verify_installation_digests(install)

    store_path = artifact_store_prefix_path(repository_root=repository_root)
    fixtures = store_path / "fixtures"
    write_fixtures(fixtures)
    vendor_digests = write_vendor_fallback_fixtures(
        fixtures, repository_root=repository_root
    )
    classes = store_path / "harness-classes"
    classes.mkdir(parents=True, exist_ok=True)

    javac = _java_tool("javac")
    assert javac is not None
    compiled = subprocess.run(
        (javac, "-cp", _classpath(install), "-d", str(classes), str(source)),
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=_clean_environment(install),
    )
    if compiled.returncode != 0:
        raise VeriFingerArtifactInspectionError(
            "the qualification harness did not compile against the pinned "
            f"bindings: {(compiled.stderr or '').strip()[:800]}"
        )

    attempted: dict[str, Any] = {}

    def one(mode: str, tree: Path) -> Mapping[str, Any]:
        report = _one_pass(
            java=preconditions.java_home,
            install=tree,
            fixtures=fixtures,
            classes=classes,
            label=mode,
            timeout=timeout,
        )
        attempted[mode] = {
            "ok": bool(report.get("ok")),
            "stage": report.get("stage"),
            "runtime_started": bool(report.get("runtime_started")),
            "error": report.get("error"),
        }
        return report

    first = one("full", install)
    if not first.get("ok"):
        if first.get("error") == "LICENCES_NOT_OBTAINED":
            # Nothing ran: the engine was never constructed. This is the third
            # precondition failing, not a finding about VeriFinger.
            raise VeriFingerAcquisitionError(
                f"{PreconditionStatus.LICENCE_NOT_ACTIVATED.value}: the SDK "
                "refused the FingerExtractor and FingerMatcher licences. "
                "Activate the 30-day trial as the vendor documents it — "
                "Trial = true in pgd.conf and start the licensing service — and "
                "run this again. Nothing here bypasses a licence."
            )
        _write_record(
            store_path,
            _failed_record(
                install,
                repository_root=repository_root,
                stage=str(first.get("stage")),
                detail=str(first.get("error")),
                passes=attempted,
            ),
        )
        raise VeriFingerArtifactInspectionError(
            "the qualification run started and failed at "
            f"{first.get('stage')}: {first.get('error')}. A FAILED record has "
            "been written, so the preflight will report a real blocker rather "
            "than an outstanding action"
        )

    second = one("restart", install)
    if not second.get("ok"):
        _write_record(
            store_path,
            _failed_record(
                install,
                repository_root=repository_root,
                stage=str(second.get("stage")),
                detail=str(second.get("error")),
                passes=attempted,
            ),
        )
        raise VeriFingerArtifactInspectionError(
            "the restart pass failed after the runtime had started: "
            f"{second.get('error')}"
        )

    # The two probes that need a deliberately incomplete runtime.
    without_models = _prepare_installation_without_models(install)
    third = one("no-models", without_models)
    fourth = one("no-licence", install)

    record = _build_record(
        install,
        first,
        second,
        third,
        fourth,
        repository_root=repository_root,
    )
    record["vendor_sample_digests"] = vendor_digests
    missing = sorted(
        {name for name, _ in FAILURE_SEMANTICS_CAUSES}
        - {
            row.get("failure_class")
            for row in record["failure_semantics"]
            if isinstance(row, dict)
        }
    )
    if missing:
        _write_record(
            store_path,
            _failed_record(
                install,
                repository_root=repository_root,
                stage="failure-semantics",
                detail=f"these failure classes were never provoked: {missing}",
                passes=attempted,
            ),
        )
        raise VeriFingerArtifactInspectionError(
            f"the run did not provoke {missing}; a FAILED record has been written"
        )

    _write_record(store_path, record)
    state = qualification_run_state(repository_root=repository_root)
    if not state.performed:
        raise VeriFingerArtifactInspectionError(
            f"the record this run wrote does not verify: {state.invalid_reason}"
        )
    return record


def _prepare_installation_without_models(install: Path) -> Path:
    """A copy of the installation with the fingerprint data file withheld.

    The controlled cause for the missing-runtime-component class. A copy rather
    than a deletion, because a probe that damaged the real installation would
    make the next pass measure something else.
    """
    incomplete = install.parent / "installation-without-models"
    if incomplete.exists():
        shutil.rmtree(incomplete)
    shutil.copytree(install, incomplete)
    for item in FINGER_DATA_FILES:
        target = incomplete / Path(item.relative_path.split("/", 1)[1])
        if target.is_file():
            target.unlink()
    return incomplete


def _build_record(
    install: Path,
    first: Mapping[str, Any],
    second: Mapping[str, Any],
    third: Mapping[str, Any],
    fourth: Mapping[str, Any],
    *,
    repository_root: Path | None = None,
) -> dict[str, Any]:
    """Merge the four passes into the shape the preflight reads.

    The restart pass contributes exactly one thing — the third determinism level
    — because two passes that disagreed about anything else would be a
    nondeterminism finding rather than something to average. The two probe passes
    contribute one failure class each.
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
    normalised = {_accessor_name(name): value for name, value in defaults.items()}
    normalised.update(defaults)

    failures: list[Any] = list(first.get("failure_semantics") or ())
    for probe in (third, fourth):
        failures.extend(probe.get("failure_semantics") or ())

    produced = sum(
        int(item.get("qualification_scores_produced") or 0)
        for item in (first, second, third, fourth)
    )
    return {
        "schema": QUALIFICATION_RUN_SCHEMA,
        "outcome": QualificationOutcome.COMPLETED.value,
        "performed_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "archive_sha256": SDK_ARCHIVE.sha256,
        "inputs_fingerprint": inputs_fingerprint(
            install, repository_root=repository_root
        ),
        "fixture_version": FIXTURE_VERSION,
        "runtime_started": True,
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
        # The native modules the process actually loaded, each with its own
        # version. This — not the Java version beside it — is what "the version
        # the running library reports" means (spec correction 6).
        "loaded_modules": first.get("loaded_modules") or [],
        "licences_obtained": bool(first.get("licences_obtained")),
        "settings_set_by_the_run": list(first.get("settings_set_by_this_pass") or ()),
        "threshold_set_by_the_run": bool(first.get("threshold_set_by_this_pass")),
        "delivered_runtime_defaults": normalised,
        "pair_orientation": first.get("pair_orientation"),
        "self_semantics": first.get("self_semantics"),
        "determinism": determinism,
        "failure_semantics": failures,
        "failure_semantics_causes": [
            {"failure_class": name, "controlled_cause": cause}
            for name, cause in FAILURE_SEMANTICS_CAUSES
        ],
        "feasibility": first.get("feasibility"),
        "qualification_scores_produced": min(produced, QUALIFICATION_RUN_MAX_SCORES),
        "benchmark_scores_produced": 0,
        "sd300_used": False,
        "fixture_kind": first.get("fixture_kind") or "SYNTHETIC_RIDGE_LIKE",
        "synthetic_pair_status": first.get("synthetic_pair_status"),
        "vendor_pair_status": first.get("vendor_pair_status"),
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
