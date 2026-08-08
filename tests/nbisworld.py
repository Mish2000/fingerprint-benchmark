"""A complete, certified-looking NBIS build that is not NBIS.

The NBIS adapter's contract is mostly about things that have nothing to do with
fingerprints: the exact argument order, one budget across three subprocesses, an
empty working directory afterwards, a stored result that names its options, a
runtime that is noticed when it changes. Testing those against the real build
would mean nobody could run the suite without 100 MB of NIST source, a C
compiler and Linux — so they are tested against a stand-in whose *interface* is
faithful and whose numbers are arithmetic on digests.

**Nothing here is a fingerprint and nothing here is a result.** What the stand-in
proves is that the adapter drives its tools correctly. What the stand-in cannot
prove is anything about NBIS, which is why every claim about NBIS itself —
PNG support, the PPI policy, determinism, score 0, the official test suite — is
in ``tests/integration/test_nbis_upstream.py`` behind the ``nbis_upstream``
marker and runs against a real certified build (spec sections 53 and 54).

One deliberate concession: :func:`certify_host` adds the running machine to the
adapter's certified-target set. Stage 7B certifies Linux x86_64 only, and the
gate that enforces that is tested on its own in
``tests/unit/test_nbis_adapter.py``. Without the concession every test that needs
a READY environment would be unrunnable anywhere else, and the gate would be the
only thing anyone ever exercised.
"""

from __future__ import annotations

import hashlib
import os
import stat
import struct
import sys
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from fpbench.adapters.nbis import build_manifest as build_manifest_module
from fpbench.adapters.nbis.adapter import VERSION_PROBES, NbisAdapter, version_probe
from fpbench.adapters.nbis.build_manifest import (
    BUILD_MANIFEST_FILENAME,
    BUILD_MANIFEST_SCHEMA_VERSION,
    EXPECTED_NBIS_VERSION,
    EXPECTED_PNG_PPI_POLICY,
    SUPPORTED_TARGETS,
    NbisBuildManifest,
    NbisOfficialTestSummary,
    build_script_fingerprint,
    file_digest,
    host_target,
    patchset_fingerprint,
)
from fpbench.adapters.nbis.config import NbisConfig
from fpbench.core.enums import ChecksumStatus
from fpbench.core.execution_models import ComparisonContext, PreparedImage
from fpbench.core.serialization import write_json
from synthetic_ridges import whorl_png

__all__ = [
    "StandInBuild",
    "REPOSITORY_ROOT",
    "NBIS_INTEGRATION_DIRECTORY",
    "FIXTURES",
    "build_stand_in",
    "sealed_repository",
    "certify_host",
    "host_is_certified",
    "gray8_png",
    "png_with_phys",
    "png_with_case",
    "prepared_image",
    "job_context",
    "job_directories",
    "files_in",
    "certified_build_directory",
    "upstream_build_available",
    "directional_golden",
    "ridge_payload",
    "identity_preparer",
]

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
NBIS_INTEGRATION_DIRECTORY = REPOSITORY_ROOT / "integrations" / "nbis"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "nbis_cli"

#: How an operator points the upstream suite at a real certified build.
BUILD_DIRECTORY_ENV_VAR = "FPBENCH_NBIS_BUILD_DIR"


@dataclass(frozen=True, slots=True)
class StandInBuild:
    """The three files an NBIS adapter is given, and where they came from."""

    directory: Path
    mindtct: Path
    bozorth3: Path
    manifest_path: Path

    def config(self, *, research_mode: bool = False) -> NbisConfig:
        return NbisConfig(
            mindtct_executable=self.mindtct,
            bozorth3_executable=self.bozorth3,
            build_manifest=self.manifest_path,
            research_mode=research_mode,
        )

    def adapter(self, *, research_mode: bool = False) -> NbisAdapter:
        return NbisAdapter(self.config(research_mode=research_mode))

    def assets(self) -> Mapping[str, Path]:
        return self.config().runtime_assets()

    def manifest(self) -> NbisBuildManifest:
        return build_manifest_module.read_build_manifest(self.manifest_path)


# ------------------------------------------------------------------ the build


def build_stand_in(
    directory: Path,
    *,
    real_names: bool = False,
    target: tuple[str, str] | None = None,
    png_ppi_policy: str = EXPECTED_PNG_PPI_POLICY,
    png_support_compiled: bool = True,
    direct_gray8_png_verified: bool = True,
    png_formats_refused_by_build: str = "corrupt,rgb8",
    failed_tests: int = 0,
    discovered_tests: int = 12,
    executed_tests: int | None = None,
) -> StandInBuild:
    """Two launchers and a signed manifest that really describes them.

    The manifest is built the way ``build.py test`` builds one — digest the two
    executables, ask them their version probes, sign the whole thing — so a test
    that tampers with any of it fails for the same reason a tampered real build
    would.

    Args:
        real_names: Put the launchers at ``bin/mindtct`` and ``bin/bozorth3``,
            which is the layout a real build produces and the layout the research
            integration looks for. On POSIX that is already the default; on
            Windows a file has to be called ``.bat`` before the operating system
            will start it, so a stand-in cannot be both runnable and
            correctly named. Tests that only *construct* an adapter ask for the
            real names; tests that actually run the tools take the default.
    """
    root = Path(directory)
    binaries = root / "bin"
    binaries.mkdir(parents=True, exist_ok=True)

    mindtct = _launcher(binaries, "mindtct", FIXTURES / "mindtct_tool.py", real_names)
    bozorth3 = _launcher(binaries, "bozorth3", FIXTURES / "bozorth3_tool.py", real_names)

    mindtct_digest, mindtct_size = file_digest(mindtct)
    bozorth3_digest, bozorth3_size = file_digest(bozorth3)
    executed = discovered_tests if executed_tests is None else executed_tests

    manifest = NbisBuildManifest.create(
        schema_version=BUILD_MANIFEST_SCHEMA_VERSION,
        nbis_version=EXPECTED_NBIS_VERSION,
        source_archive_sha256=_fake_digest("release archive"),
        source_archive_size_bytes=104857600,
        test_archive_sha256=_fake_digest("test archive"),
        test_archive_size_bytes=20971520,
        patchset_fingerprint=patchset_fingerprint(
            NBIS_INTEGRATION_DIRECTORY / "patches" / "series.json"
        ),
        build_script_fingerprint=build_script_fingerprint(NBIS_INTEGRATION_DIRECTORY),
        target_os=(target or host_target())[0],
        target_architecture=(target or host_target())[1],
        compiler_id="gcc",
        compiler_version="stand-in",
        compiler_target="stand-in",
        cflags="-O2 -fcommon",
        cppflags="",
        ldflags="",
        mindtct_version_output=version_probe(mindtct, VERSION_PROBES["mindtct"]) or "",
        bozorth3_version_output=version_probe(bozorth3, VERSION_PROBES["bozorth3"]) or "",
        png_support_compiled=png_support_compiled,
        direct_gray8_png_verified=direct_gray8_png_verified,
        # What the real certified build was measured to refuse: libpng
        # down-converts 16-bit and indexed, so only these two are refused.
        png_formats_refused_by_build=png_formats_refused_by_build,
        png_ppi_policy=png_ppi_policy,
        mindtct_sha256=mindtct_digest,
        mindtct_size_bytes=mindtct_size,
        bozorth3_sha256=bozorth3_digest,
        bozorth3_size_bytes=bozorth3_size,
        dynamic_dependencies={"mindtct": [], "bozorth3": []},
        official_test_summary=NbisOfficialTestSummary(
            test_suite_version=EXPECTED_NBIS_VERSION,
            discovered_tests=discovered_tests,
            executed_tests=executed,
            passed_tests=executed - failed_tests,
            failed_tests=failed_tests,
            ordered_output_hash=_fake_digest("official tests"),
        ),
        created_utc=datetime.now(timezone.utc).isoformat(),
    )
    manifest_path = root / BUILD_MANIFEST_FILENAME
    write_json(manifest_path, manifest.as_plain())
    return StandInBuild(
        directory=root,
        mindtct=mindtct,
        bozorth3=bozorth3,
        manifest_path=manifest_path,
    )


def sealed_repository(root: Path, manifest: NbisBuildManifest) -> Path:
    """A repository whose NBIS lock is sealed to ``manifest``'s archives.

    The real ``integrations/nbis/nbis-5.0.0.lock.json`` is deliberately unsealed
    until somebody obtains the archives from NIST and records their digests, so a
    research run cannot be prepared against it — which is itself worth a test.
    This builds the *other* case: a checkout where the sealing has happened, so
    that everything downstream of it can be exercised.

    The patch series and both build scripts are copied byte for byte, because
    their fingerprints are in the manifest and a paraphrase would fail for the
    wrong reason.
    """
    integration = Path(root) / "integrations" / "nbis"
    (integration / "patches").mkdir(parents=True, exist_ok=True)
    for name in ("build.py", "verify_build.py"):
        (integration / name).write_bytes((NBIS_INTEGRATION_DIRECTORY / name).read_bytes())
    (integration / "patches" / "series.json").write_bytes(
        (NBIS_INTEGRATION_DIRECTORY / "patches" / "series.json").read_bytes()
    )

    write_json(
        integration / "nbis-5.0.0.lock.json",
        {
            "schema_version": "1",
            "release": {
                "version": EXPECTED_NBIS_VERSION,
                "source": "official_nist_nigos",
                "url": "https://example.invalid/nbis-release-5.0.0.zip",
                "sha256": manifest.source_archive_sha256,
                "size_bytes": manifest.source_archive_size_bytes,
            },
            "tests": {
                "version": EXPECTED_NBIS_VERSION,
                "source": "official_nist_nigos",
                "url": "https://example.invalid/nbis-tests-5.0.0.zip",
                "sha256": manifest.test_archive_sha256,
                "size_bytes": manifest.test_archive_size_bytes,
            },
        },
    )
    return Path(root)


def _launcher(directory: Path, name: str, script: Path, real_names: bool = False) -> Path:
    """An executable that runs ``script``, on whichever platform this is.

    A ``.bat`` on Windows and a shell stub on POSIX. The adapter is given an
    absolute path to it, exactly as it is given an absolute path to a real
    ``mindtct``; the launcher exists because a ``.py`` file is not something the
    operating system will start on its own.
    """
    interpreter = Path(sys.executable).resolve()
    if os.name == "nt":
        path = directory / (name if real_names else f"{name}.bat")
        path.write_text(
            '@echo off\r\n"%s" "%s" %%*\r\n' % (interpreter, script), encoding="ascii"
        )
        return path
    path = directory / name
    path.write_text(
        f'#!/bin/sh\nexec "{interpreter}" "{script}" "$@"\n', encoding="ascii"
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _fake_digest(label: str) -> str:
    return hashlib.sha256(f"fpbench stand-in {label}".encode()).hexdigest()


# ------------------------------------------------------------ platform gate


def host_is_certified() -> bool:
    return host_target() in SUPPORTED_TARGETS


def certify_host(monkeypatch) -> None:
    """Let this machine's platform through the certified-target gate.

    A no-op on Linux x86_64, where the gate already passes. Everywhere else it
    widens the set for the duration of one test, so that everything *except* the
    gate can be exercised. The gate itself has its own test, without this
    (spec section 18).
    """
    if host_is_certified():
        return
    widened = frozenset(SUPPORTED_TARGETS | {host_target()})
    monkeypatch.setattr(build_manifest_module, "SUPPORTED_TARGETS", widened)
    from fpbench.adapters.nbis import adapter as adapter_module

    monkeypatch.setattr(adapter_module, "SUPPORTED_TARGETS", widened)


# ------------------------------------------------------------------- images


def gray8_png(seed: int = 1) -> bytes:
    """A deterministic 8-bit greyscale PNG at fingertip scale, with no pHYs.

    The synthetic ridges are not fingerprints; see
    ``tests/fixtures/sourceafis/README.md``. What matters here is only that the
    file is a real, structurally valid greyscale PNG of a size MINDTCT would
    accept.
    """
    return whorl_png(500, seed)


def png_with_phys(payload: bytes, ppi: int) -> bytes:
    """The same PNG, with a ``pHYs`` chunk declaring ``ppi``.

    Inserted immediately after IHDR so the pixels are byte-identical to the
    original's. That identity is the whole point of the PPI probe: if MINDTCT's
    output differs, the chunk is the only thing that can have caused it
    (docs/adr/0047).
    """
    per_metre = round(ppi / 0.0254)
    return _insert_chunk(payload, b"pHYs", struct.pack(">IIB", per_metre, per_metre, 1))


def png_with_case(payload: bytes, case: str) -> bytes:
    """The same PNG, carrying a ``tEXt`` chunk that tells the stand-in what to do.

    The adapter names every staged input ``left-input.png`` or
    ``right-input.png``, so a fixture cannot be steered by a file name. It is
    steered by the image instead — which also means the two sides of one
    comparison can be given different behaviour, which is how the
    left-fails-but-right-does-not cases are written.
    """
    return _insert_chunk(payload, b"tEXt", b"fpbench-case\x00" + case.encode("ascii"))


def _insert_chunk(payload: bytes, kind: bytes, body: bytes) -> bytes:
    """Put one chunk immediately after IHDR, leaving the pixels untouched."""
    signature, rest = payload[:8], payload[8:]
    length = struct.unpack(">I", rest[:4])[0]
    ihdr_end = 4 + 4 + length + 4
    chunk = (
        struct.pack(">I", len(body))
        + kind
        + body
        + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
    )
    return signature + rest[:ihdr_end] + chunk + rest[ihdr_end:]


def prepared_image(
    path: Path,
    payload: bytes,
    *,
    image_id: str = "sd300a_00001000_plain_left",
    effective_ppi: int = 500,
    media_type: str = "image/png",
    prepared_sha256: str | None = None,
) -> PreparedImage:
    """Write ``payload`` and describe it as the preparer would have."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    return PreparedImage(
        image_id=image_id,
        local_path=target.resolve(),
        effective_ppi=effective_ppi,
        media_type=media_type,
        expected_sha256=digest,
        checksum_status=ChecksumStatus.VERIFIED,
        preparation_profile_id="identity_png_v1",
        preparation_hash=hashlib.sha256(f"prep-{image_id}".encode()).hexdigest(),
        prepared_sha256=prepared_sha256 or digest,
        prepared_size_bytes=len(payload),
    )


# ------------------------------------------------------------------- context


def job_directories(root: Path) -> tuple[Path, Path]:
    """The runner's own layout, so workspace-relative artefact paths resolve."""
    working = Path(root) / "workspace" / "work" / "run_abc123def456" / "job_0123456789abcdef"
    artifacts = (
        Path(root) / "workspace" / "artifacts" / "run_abc123def456" / "job_0123456789abcdef"
    )
    working.mkdir(parents=True, exist_ok=True)
    artifacts.mkdir(parents=True, exist_ok=True)
    return working, artifacts


def job_context(
    working: Path, artifacts: Path, *, timeout_seconds: float = 60.0
) -> ComparisonContext:
    return ComparisonContext(
        run_id="run_abc123def456",
        job_id="job_0123456789abcdef",
        attempt=1,
        working_directory=Path(working),
        artifact_directory=Path(artifacts),
        timeout_seconds=timeout_seconds,
        deterministic_seed=0,
    )


def files_in(directory: Path) -> list[str]:
    return sorted(path.name for path in Path(directory).rglob("*") if path.is_file())


# ------------------------------------------------------------------ upstream


def directional_golden(forward, reverse) -> bool:
    """The sides' minutiae counts swap, or the two calls were not two calls.

    The conformance suite's generic direction check cannot detect silent input
    sorting, because a symmetric matcher may legitimately return the same score
    both ways. This route can prove it another way: no amount of internal
    reordering makes the two sides' recorded counts exchange places.

    Only discriminating when the two images yield different counts, which the
    tests that use it assert separately — a golden that held for identical inputs
    would be no golden at all (spec section 44).
    """
    from fpbench.core.enums import ExecutionStatus

    if not (
        forward.status is ExecutionStatus.SUCCESS
        and reverse.status is ExecutionStatus.SUCCESS
    ):
        return False
    forward_left = forward.metadata.get("left_minutiae_count")
    forward_right = forward.metadata.get("right_minutiae_count")
    return (
        forward_left is not None
        and forward_right is not None
        and reverse.metadata.get("left_minutiae_count") == forward_right
        and reverse.metadata.get("right_minutiae_count") == forward_left
    )


def ridge_payload(subject: str, impression: str, frgp: int) -> bytes:
    """One deterministic 500 ppi greyscale raster per image. Not a fingerprint."""
    seed = (int(subject) + frgp * 7 + (3 if impression == "roll" else 0)) % 11 + 1
    return gray8_png(seed)


def identity_preparer(workspace: Path, spec):
    """The preparer factory the engine takes, for a run over delivered bytes."""
    from fpbench.imaging.identity import IdentityImagePreparer

    return IdentityImagePreparer()


def certified_build_directory() -> Path | None:
    """A real certified NBIS build, if this machine has one."""
    value = os.environ.get(BUILD_DIRECTORY_ENV_VAR)
    if value and (Path(value) / BUILD_MANIFEST_FILENAME).is_file():
        return Path(value).resolve()
    root = REPOSITORY_ROOT / "build" / f"nbis-{EXPECTED_NBIS_VERSION}"
    if not root.is_dir():
        return None
    candidates = sorted(
        path
        for path in root.iterdir()
        if path.is_dir() and (path / BUILD_MANIFEST_FILENAME).is_file()
    )
    return candidates[0].resolve() if len(candidates) == 1 else None


def upstream_build_available() -> bool:
    """Whether this machine has a certified build *it can run*.

    Two questions that look like one. ``certified_build_directory`` answers
    "where is a build?", which is what a diagnostic message needs. This answers
    "can the upstream suite execute here?", and those come apart in exactly one
    situation that this repository actually produces: a Linux build materialised
    into a Windows checkout under the gitignored ``build/`` directory, where the
    fallback scan finds it and every test then fails on
    ``EnvironmentStatus.READY`` rather than skipping.

    The platform comparison uses ``host_target`` for the reason that function
    exists — so the build script, the adapter and the tests cannot disagree
    about whether ``AMD64`` and ``x86_64`` are the same machine.
    """
    return upstream_build_unavailable_reason() is None


#: Set in CI, where a build is supposed to be present. It turns "no runnable
#: build" from a skip into a failure, so an absent or mis-targeted build cannot
#: make a job quietly green.
REQUIRE_UPSTREAM_ENV_VAR = "FPBENCH_REQUIRE_NBIS"


def upstream_build_unavailable_reason() -> str | None:
    """Why the upstream suite cannot run here, or ``None`` if it can.

    A sentence rather than a boolean, because the two ways this fails are not
    the same event and a reader of a skip line needs to know which one they got.
    """
    directory = certified_build_directory()
    if directory is None:
        return f"no certified NBIS build; set {BUILD_DIRECTORY_ENV_VAR}"
    try:
        manifest = build_manifest_module.read_build_manifest(
            directory / BUILD_MANIFEST_FILENAME
        )
    except Exception as exc:
        return f"the build manifest at {directory.name} is not readable: {exc}"
    host = host_target()
    if manifest.target != host:
        return (
            f"the build at {directory.name} targets "
            f"{manifest.target[0]}/{manifest.target[1]} and this machine is "
            f"{host[0]}/{host[1]}"
        )
    return None


def require_runnable_upstream_build() -> None:
    """Skip the upstream suite, or fail it where a build was promised.

    Called from a module-scoped autouse fixture rather than expressed as a
    ``skipif``, because ``skipif`` cannot distinguish "not applicable here" from
    "CI said a build would be here and it is not".
    """
    import pytest

    reason = upstream_build_unavailable_reason()
    if reason is None:
        return
    if os.environ.get(REQUIRE_UPSTREAM_ENV_VAR):
        pytest.fail(f"{REQUIRE_UPSTREAM_ENV_VAR} is set and {reason}")
    pytest.skip(reason)
