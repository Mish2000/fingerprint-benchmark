#!/usr/bin/env python3
"""Obtain, verify, build and certify NIST NBIS 5.0.0, and nothing else.

Five commands, and each of them refuses to do the next one's job:

``seal``    record, once, the SHA-256 and size of the two archives NIST published.
``fetch``   download exactly those archives, verify them, and only then keep them.
``build``   compile the verified sources. Never touches the network.
``test``    run NIST's own Test 5.0.0 suite plus this project's PNG and PPI
            capability probes, and — only if all of it passes — write the build
            manifest that makes the build usable.
``inspect`` say where the lock, the cache and the build stand. Writes nothing.

Three rules the whole file exists to enforce.

**No silent download.** ``build`` cannot reach the network at all; there is no
code path in it that opens a socket. ``fetch`` will not run against an unsealed
lock, will not accept a byte that disagrees with the lock, and has no mirror,
no fallback URL and no retry against a different host. A third-party package, a
GitHub fork or somebody's Docker image is not this source, whatever it contains
(spec sections 3 and 5).

**No unsafe extraction.** Every archive entry is inspected before anything is
written: an absolute path, a ``..``, a symlink, a hard link, a device node or a
FIFO is refused outright, and the archive with it. Extraction happens in a fresh
temporary directory outside the repository, never into ``src/``, never into
``integrations/`` and never into the working tree (spec section 6).

**No behavioural patch.** ``patches/series.json`` is empty and the fingerprint of
that emptiness is in the manifest. Flags may move — install prefixes, ``-fcommon``,
``--without-X11`` — because they change where things go and how they link, not
what MINDTCT decides about a ridge. A change to NBIS's C sources stops this stage
rather than being labelled portability (spec section 7).

**The manifest is the output of ``test``, not of ``build``.** A compiled pair of
executables that has not been through NIST's own suite and the PNG/PPI probes is
not a certified build, and the adapter has no way to use one: it requires the
manifest, and the manifest carries the test summary and the two PNG verdicts. So
``build`` writes ``build-inputs.json`` and stops, and ``test`` is what completes
the directory. This deviates from a literal reading of the spec's section 8,
which describes the finished layout; it is the only ordering in which the
manifest cannot exist for an uncertified build.

Nothing here writes a path into anything durable. A build manifest that carried
somebody's home directory would put it in the runtime bundle and from there into
published evidence, so the manifest model refuses one and this script never
offers it (spec section 10).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import zipfile
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

HERE = Path(__file__).resolve().parent
REPOSITORY_ROOT = HERE.parents[1]

# The manifest model is product code and lives in the package, so that the thing
# that writes a manifest and the thing that verifies one cannot drift apart.
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from fpbench.adapters.nbis.adapter import VERSION_PROBES, version_probe  # noqa: E402
from fpbench.adapters.nbis.build_manifest import (  # noqa: E402
    BUILD_MANIFEST_FILENAME,
    BUILD_MANIFEST_SCHEMA_VERSION,
    EXPECTED_NBIS_VERSION,
    EXPECTED_PNG_PPI_POLICY,
    LOCK_FILENAME,
    PATCH_SERIES_RELATIVE_PATH,
    NbisBuildManifest,
    NbisBuildManifestError,
    NbisOfficialTestSummary,
    NbisSourceLock,
    build_script_fingerprint,
    file_digest,
    host_target,
    patchset_fingerprint,
    read_source_lock,
    verify_build_manifest,
)

LOCK_PATH = HERE / LOCK_FILENAME
SERIES_PATH = HERE / PATCH_SERIES_RELATIVE_PATH

#: Where verified archives and extracted sources live. Deliberately outside the
#: repository: an extracted upstream tree inside the working copy would make
#: every research command refuse to run for having a dirty tree, and would put
#: 100 MB of third-party C where a reviewer expects this project's code.
DEFAULT_CACHE = Path(
    os.environ.get("FPBENCH_NBIS_CACHE")
    or (Path.home() / ".cache" / "fpbench" / "nbis")
)

#: Where the finished executables go. Inside the repository but under ``build/``,
#: which ``.gitignore`` already excludes in full (spec sections 6 and 8).
BUILD_ROOT = Path(
    os.environ.get("FPBENCH_NBIS_BUILD") or (REPOSITORY_ROOT / "build")
) / f"nbis-{EXPECTED_NBIS_VERSION}"

#: The two tools this stage certifies. Nothing else is copied out of the build.
TOOLS = ("mindtct", "bozorth3")

#: Which of NIST's own test directories are relevant to MINDTCT, to BOZORTH3 and
#: to the image formats they depend on. Confirmed against the real Test 5.0.0
#: package on first run: discovery *fails loudly* when none of these exists,
#: rather than reporting zero tests and calling that a pass (spec section 40).
RELEVANT_TEST_TOOLS: tuple[str, ...] = (
    "mindtct",
    "bozorth3",
    "png",
    "jpegl",
    "jpegb",
    "wsq",
    "ihead",
    "an2k",
    "imgtools",
)

#: The compiler flags are **NBIS's own**, read back out of the ``rules.mak`` its
#: ``setup.sh`` generates, and recorded in the manifest as the build actually used
#: them (spec section 10).
#:
#: They are deliberately not supplied by this project. ``rules.mak`` defines
#:
#:     CFLAGS := -O2 -w -ansi -D_POSIX_SOURCE $(ENDIAN_FLAG) $(NBIS_JASPER_FLAG) \
#:               $(NBIS_OPENJP2_FLAG) $(NBIS_PNG_FLAG) $(ARCH_FLAG)
#:
#: so passing ``CFLAGS=`` on the make command line would *replace* the whole
#: line — silently dropping ``-D__NBIS_PNG__`` and building the one thing this
#: route cannot do without. The only variable this project overrides is ``CC``,
#: which ``rules.mak`` assigns with ``:=`` and no ``override``, so a command-line
#: value wins cleanly.
#:
#: ``-fcommon`` is the one flag that may be added, and only when the compiler
#: needs it: GCC 10 changed its default to ``-fno-common`` and NBIS 5.0.0 predates
#: that. Whether it is needed is *measured* on the compiler rather than assumed
#: from a version number, and it rides on ``CC`` so that ``CFLAGS`` stays NBIS's
#: (spec section 7).
FCOMMON_FLAG = "-fcommon"

#: Flags that would make the build depend on the machine it was built on, or on
#: a floating-point contraction nobody chose. Refused rather than merely omitted,
#: because an operator exporting one in their shell would otherwise change what a
#: certified build is (spec section 9).
FORBIDDEN_FLAG_FRAGMENTS = (
    "-march=native",
    "-mtune=native",
    "-ffast-math",
    "-flto",
    "-fprofile-use",
    "-fprofile-generate",
)

TIMEOUT_SECONDS = 3600.0

#: The probe raster. Half an inch square at 500 ppi, with roughly human ridge
#: spacing — enough structure for MINDTCT to find minutiae, and not a fingerprint.
PROBE_PPI = 500
PROBE_INCHES = 0.5
RIDGES_PER_INCH = 55.0


class BuildError(RuntimeError):
    """Something about the source, the build or the certification is wrong."""


# --------------------------------------------------------------------- shell


@dataclass(frozen=True, slots=True)
class CommandResult:
    argv: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str


def run(
    argv: Sequence[str],
    *,
    cwd: Path,
    extra_path: Path | None = None,
    check: bool = True,
    timeout: float = TIMEOUT_SECONDS,
) -> CommandResult:
    """Run one command with a named environment and a real timeout.

    ``extra_path`` goes in front of ``PATH``. That is how the chosen compiler
    reaches the parts of NBIS's build that resolve a bare name: ``setup.sh``
    compiles its endianness probe with a literal ``gcc``, and ``rules.mak``
    assigns ``CC := $(shell which gcc)``. A shim directory holding ``gcc`` and
    ``cc`` makes both of those the compiler this script probed and recorded.
    """
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", str(Path.home())),
        "LANG": "C",
        "LC_ALL": "C",
        "TZ": "UTC",
    }
    # Named, not inherited. Windows cannot start a process without these, so they
    # are listed here rather than picked up wholesale — which keeps "what reaches
    # the build" answerable by reading this file. The certified target is Linux;
    # this exists so the script's own tests can run anywhere.
    for name in ("SystemRoot", "windir", "COMSPEC", "PATHEXT"):
        value = os.environ.get(name)
        if value is not None:
            environment[name] = value
    if extra_path is not None:
        environment["PATH"] = f"{extra_path}{os.pathsep}{environment['PATH']}"
    try:
        completed = subprocess.run(  # noqa: S603 - argv list, shell=False
            [str(item) for item in argv],
            cwd=str(cwd),
            env=environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            errors="replace",
            shell=False,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise BuildError(f"{argv[0]!r} is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise BuildError(f"{argv[0]!r} did not finish within {timeout:.0f}s") from exc
    result = CommandResult(
        argv=tuple(str(item) for item in argv),
        exit_code=int(completed.returncode),
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )
    if check and result.exit_code != 0:
        raise BuildError(
            f"{argv[0]!r} exited {result.exit_code}\n"
            f"{result.stdout[-2000:]}\n{result.stderr[-2000:]}"
        )
    return result


# ------------------------------------------------------------------ archives


def sniff_archive(path: Path) -> str:
    """zip, tar.gz or tar — decided by the bytes, never by the file name."""
    with Path(path).open("rb") as handle:
        head = handle.read(262)
    if head[:4] == b"PK\x03\x04":
        return "zip"
    if head[:2] == b"\x1f\x8b":
        return "tar.gz"
    if head[257:262] == b"ustar":
        return "tar"
    raise BuildError(
        f"{Path(path).name} is neither a zip nor a tar archive; this is not the "
        "NIST distribution"
    )


def _reject_entry_name(name: str) -> None:
    if not name or name in (".", ".."):
        raise BuildError(f"archive entry {name!r} has no usable name")
    if name.startswith("/") or name.startswith("\\"):
        raise BuildError(f"archive entry {name!r} is an absolute path")
    if len(name) > 1 and name[1] == ":":
        raise BuildError(f"archive entry {name!r} carries a drive letter")
    parts = name.replace("\\", "/").split("/")
    if any(part == ".." for part in parts):
        raise BuildError(f"archive entry {name!r} escapes with '..'")


def _reject_escape(destination: Path, name: str) -> Path:
    target = (destination / name.replace("\\", "/")).resolve()
    if not target.is_relative_to(destination.resolve()):
        raise BuildError(f"archive entry {name!r} resolves outside the extraction root")
    return target


def safe_extract(archive: Path, destination: Path) -> Path:
    """Extract into a directory that did not exist a moment ago, or refuse.

    Every entry is inspected first and the whole archive is refused on the first
    unacceptable one. Partial extraction of a hostile archive is not a state this
    project is willing to be in (spec section 6).
    """
    destination = Path(destination)
    if destination.exists():
        raise BuildError(f"{destination.name} already exists; extract into a fresh one")
    destination.mkdir(parents=True)
    kind = sniff_archive(archive)

    if kind == "zip":
        with zipfile.ZipFile(archive) as bundle:
            members = bundle.infolist()
            for info in members:
                _reject_entry_name(info.filename.rstrip("/") or info.filename)
                mode = (info.external_attr >> 16) & 0o170000
                if mode == 0o120000:
                    raise BuildError(f"archive entry {info.filename!r} is a symlink")
                if mode not in (0, 0o100000, 0o040000):
                    raise BuildError(
                        f"archive entry {info.filename!r} is not a plain file or "
                        "directory"
                    )
                _reject_escape(destination, info.filename)
            bundle.extractall(destination)
    else:
        mode = "r:gz" if kind == "tar.gz" else "r:"
        with tarfile.open(archive, mode) as bundle:
            members = bundle.getmembers()
            for member in members:
                _reject_entry_name(member.name)
                if member.issym() or member.islnk():
                    raise BuildError(f"archive entry {member.name!r} is a link")
                if member.ischr() or member.isblk() or member.isfifo() or member.isdev():
                    raise BuildError(f"archive entry {member.name!r} is a device node")
                if not (member.isfile() or member.isdir()):
                    raise BuildError(
                        f"archive entry {member.name!r} is neither a file nor a "
                        "directory"
                    )
                _reject_escape(destination, member.name)
            bundle.extractall(destination)

    for path in destination.rglob("*"):
        if path.is_symlink():  # pragma: no cover - the checks above prevent it
            raise BuildError(f"{path.name} was extracted as a symlink")
    return destination


# ---------------------------------------------------------------------- lock


def require_sealed_lock() -> NbisSourceLock:
    lock = read_source_lock(LOCK_PATH)
    if not lock.is_sealed:
        raise BuildError(
            "the NBIS source lock has never been sealed. Obtain "
            "NBIS Release 5.0.0 and NBIS Test 5.0.0 from NIST, then run\n"
            "    python integrations/nbis/build.py seal \\\n"
            "        --release <nbis release archive> --release-url <url> \\\n"
            "        --tests <nbis test archive> --tests-url <url>\n"
            "and commit the resulting lock file (integrations/nbis/README.md)"
        )
    return lock


def cache_paths(cache: Path) -> dict[str, Path]:
    return {
        "release": Path(cache) / "archives" / "nbis-release-5.0.0.archive",
        "tests": Path(cache) / "archives" / "nbis-tests-5.0.0.archive",
    }


def verify_cached_archives(lock: NbisSourceLock, cache: Path) -> dict[str, Path]:
    """Every cached archive is exactly the bytes the lock names, or nothing is."""
    paths = cache_paths(cache)
    for name, locked in (("release", lock.release), ("tests", lock.tests)):
        path = paths[name]
        if not path.is_file():
            raise BuildError(
                f"the {name} archive is not in the cache; run 'build.py fetch' first"
            )
        digest, size = file_digest(path)
        if size != locked.size_bytes or digest != locked.sha256:
            raise BuildError(
                f"the cached {name} archive is not the locked one "
                f"({size} bytes, {digest[:16]}...); delete it and fetch again"
            )
    return paths


# --------------------------------------------------------------------- seal


def command_seal(arguments: argparse.Namespace) -> int:
    """Record the digest of an archive obtained from NIST. Once, per archive.

    The digest is computed here from the bytes on disk. It is never copied from a
    web page, a README, a package index or a mirror, and an entry that already
    carries one is never replaced: a change in the bytes needs its own review and
    must not be waved through by re-running a command (spec section 4).
    """
    lock = read_source_lock(LOCK_PATH)
    payload = lock.as_plain()
    changed: list[str] = []

    for name, archive, url in (
        ("release", arguments.release, arguments.release_url),
        ("tests", arguments.tests, arguments.tests_url),
    ):
        if archive is None:
            continue
        entry = payload[name]
        if entry["sha256"] is not None:
            raise BuildError(
                f"the {name} archive is already sealed. Its bytes are part of every "
                "manifest this project has issued; changing them is a reviewed "
                "update, not a re-run of 'seal'"
            )
        if not url:
            raise BuildError(f"--{name}-url is required when sealing the {name} archive")
        path = Path(archive).resolve()
        if not path.is_file():
            raise BuildError(f"{path.name} is not a regular file")
        sniff_archive(path)
        digest, size = file_digest(path)
        entry["url"] = url
        entry["sha256"] = digest
        entry["size_bytes"] = size
        changed.append(f"{name}: {digest} ({size} bytes)")

    if not changed:
        raise BuildError("nothing to seal; pass --release and/or --tests")

    # Round-tripped through the model so a malformed edit cannot be committed.
    read_source_lock(_write_json_atomically(LOCK_PATH, payload))
    print("sealed:")
    for line in changed:
        print(f"  {line}")
    print(f"\nCommit {_display(LOCK_PATH)}.")
    return 0


# -------------------------------------------------------------------- fetch


def command_fetch(arguments: argparse.Namespace) -> int:
    """Download exactly the locked archives, verify, and only then keep them."""
    lock = require_sealed_lock()
    cache = Path(arguments.cache)
    _require_outside_repository(cache)
    paths = cache_paths(cache)
    paths["release"].parent.mkdir(parents=True, exist_ok=True)

    from urllib.error import URLError
    from urllib.request import urlopen

    for name, locked in (("release", lock.release), ("tests", lock.tests)):
        target = paths[name]
        if target.is_file():
            digest, size = file_digest(target)
            if digest == locked.sha256 and size == locked.size_bytes:
                print(f"{name}: already cached and verified")
                continue
            raise BuildError(
                f"the cached {name} archive is not the locked one; delete "
                f"{target.name} deliberately before fetching again"
            )

        quarantine = target.with_suffix(".partial")
        print(f"{name}: downloading {locked.url}")
        try:
            with urlopen(locked.url, timeout=120) as response:  # noqa: S310 - locked URL
                with quarantine.open("wb") as handle:
                    shutil.copyfileobj(response, handle, 1 << 20)
        except (URLError, OSError, ValueError) as exc:
            quarantine.unlink(missing_ok=True)
            raise BuildError(
                f"could not download the {name} archive: {type(exc).__name__}. There "
                "is no mirror and no fallback; obtain it from NIST and seal it "
                "instead"
            ) from exc

        digest, size = file_digest(quarantine)
        if size != locked.size_bytes or digest != locked.sha256:
            quarantine.unlink(missing_ok=True)
            raise BuildError(
                f"the downloaded {name} archive is {size} bytes / {digest[:16]}..., "
                f"the lock says {locked.size_bytes} bytes / {str(locked.sha256)[:16]}"
                "... Nothing was kept"
            )
        sniff_archive(quarantine)
        quarantine.replace(target)
        print(f"{name}: verified and cached")
    return 0


# -------------------------------------------------------------------- build


@dataclass(frozen=True, slots=True)
class BuildInputs:
    """Everything that decides what a build *is*, before it has run.

    The compiler flags are absent on purpose. They are not an input: ``setup.sh``
    derives them from the archive, the setup options and the platform, all three
    of which are here. They are read back afterwards and recorded in the manifest
    as the build actually used them (spec section 10).
    """

    source_archive_sha256: str
    source_archive_size_bytes: int
    test_archive_sha256: str
    test_archive_size_bytes: int
    patchset_fingerprint: str
    build_script_fingerprint: str
    target_os: str
    target_architecture: str
    compiler_id: str
    compiler_version: str
    compiler_target: str
    compiler_extra_flags: str
    setup_options: str

    @property
    def build_id(self) -> str:
        canonical = json.dumps(
            {
                "schema": "nbis_build_id_v1",
                **{
                    name: getattr(self, name)
                    for name in sorted(self.__slots__)
                },
            },
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]

    def as_plain(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in self.__slots__}


@dataclass(frozen=True, slots=True)
class Compiler:
    """The one compiler that is probed, invoked and recorded.

    ``executable`` is an absolute path and is deliberately **never** written into
    the manifest: where a machine keeps its compiler is a fact about the machine
    (spec section 10). What is recorded is what the compiler *is* — its identity,
    its version banner and its own ``-dumpmachine`` target — and the whole point
    of resolving it to an absolute path here is that the thing recorded and the
    thing invoked cannot come apart.
    """

    executable: Path
    identity: str
    version: str
    target: str
    extra_flags: tuple[str, ...] = ()

    @property
    def command(self) -> str:
        """What ``CC`` is set to: the compiler, plus any flag it needs."""
        return " ".join([str(self.executable), *self.extra_flags])


def resolve_compiler() -> Compiler:
    """Decide which compiler builds, and prove it answers for itself.

    ``CC`` chooses; ``cc`` is the default. Either way the name is resolved to an
    absolute path *before* it is probed, so that the version banner recorded in
    the manifest came from the same file that will be handed to ``setup.sh`` and
    to ``make``. Resolving after probing, or probing a bare name while building
    with another, is the provenance gap this exists to close.
    """
    requested = (os.environ.get("CC") or "cc").strip()
    if not requested:
        raise BuildError("CC is set but empty; unset it or name a compiler")
    if os.sep in requested or (os.altsep and os.altsep in requested):
        executable = Path(requested).expanduser().resolve()
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise BuildError(f"CC names {requested!r}, which is not an executable file")
    else:
        found = shutil.which(requested)
        if found is None:
            raise BuildError(
                f"CC names {requested!r}, which is not on PATH. Name an absolute "
                "path, or install it"
            )
        executable = Path(found).resolve()

    banner = (
        run([executable, "--version"], cwd=HERE).stdout.strip().splitlines() or [""]
    )[0]
    target = run([executable, "-dumpmachine"], cwd=HERE).stdout.strip()
    if not target:
        raise BuildError(f"{executable.name} does not answer -dumpmachine")
    identity = "clang" if "clang" in banner.lower() else "gcc"
    extra = _tentative_definition_flags(executable)
    return Compiler(
        executable=executable,
        identity=identity,
        version=banner,
        target=target,
        extra_flags=extra,
    )


def _tentative_definition_flags(executable: Path) -> tuple[str, ...]:
    """Does this compiler need ``-fcommon``? Measured, not inferred from a version.

    NBIS 5.0.0 declares the same variable at file scope in more than one
    translation unit. GCC 9 and earlier merged those; GCC 10 changed the default
    to ``-fno-common`` and the link fails. Compiling the two-file case is a
    smaller and more reliable question than parsing a version string, and the
    answer is recorded rather than assumed (spec section 7).
    """
    probe = Path(tempfile.mkdtemp(prefix="fpbench-nbis-cc-"))
    try:
        (probe / "a.c").write_text("int fpbench_probe;\nint main(void){return 0;}\n")
        (probe / "b.c").write_text("int fpbench_probe;\n")
        without = run(
            [executable, "a.c", "b.c", "-o", "probe"],
            cwd=probe,
            check=False,
            timeout=120.0,
        )
        if without.exit_code == 0:
            return ()
        with_flag = run(
            [executable, FCOMMON_FLAG, "a.c", "b.c", "-o", "probe"],
            cwd=probe,
            check=False,
            timeout=120.0,
        )
        if with_flag.exit_code == 0:
            return (FCOMMON_FLAG,)
        raise BuildError(
            f"{executable.name} links neither with nor without {FCOMMON_FLAG}; "
            "this toolchain cannot build NBIS 5.0.0 unchanged, and changing its C "
            "is not something this stage does (spec section 7)"
        )
    finally:
        shutil.rmtree(probe, ignore_errors=True)


def compiler_shim(directory: Path, compiler: Compiler) -> Path:
    """A directory holding ``gcc`` and ``cc``, both this compiler.

    NBIS resolves a bare name in two places — ``setup.sh``'s endianness probe and
    ``rules.mak``'s ``CC := $(shell which gcc)`` — so overriding ``CC`` on the
    make command line alone would still leave part of the build using whatever is
    first on PATH. With this directory in front, every one of them is the
    compiler that was probed.
    """
    shim = _ensure(Path(directory))
    for name in ("gcc", "cc"):
        path = shim / name
        path.write_text(
            "#!/bin/sh\n"
            f'exec "{compiler.executable}" {" ".join(compiler.extra_flags)} "$@"\n',
            encoding="ascii",
        )
        path.chmod(0o755)
    return shim


def make_command(target: str, compiler: Compiler) -> list[str]:
    """``make <target> CC=<the compiler>`` and nothing else.

    ``CFLAGS`` and ``LDFLAGS`` are deliberately absent: ``rules.mak`` builds
    ``CFLAGS`` out of NBIS's own feature macros, and a command-line value would
    replace the whole line — taking ``-D__NBIS_PNG__`` with it.
    """
    return ["make", target, f"CC={compiler.command}"]


def read_build_flags(source_root: Path, compiler: Compiler) -> dict[str, str]:
    """The flags NBIS's generated ``rules.mak`` actually uses, expanded by make.

    Asked of make rather than parsed out of the file, because the values are
    composed from half a dozen variables ``setup.sh`` substitutes; a regex would
    record something that looks like the flags rather than the flags.
    """
    probe = Path(source_root) / "fpbench-print-flags.mak"
    probe.write_text(
        "include rules.mak\n"
        "fpbench-print-flags:\n"
        "\t@echo CFLAGS=$(CFLAGS)\n"
        "\t@echo CDEFS=$(CDEFS)\n"
        "\t@echo LDFLAGS=$(LDFLAGS)\n",
        encoding="ascii",
    )
    try:
        result = run(
            ["make", "-f", probe.name, "fpbench-print-flags", f"CC={compiler.command}"],
            cwd=Path(source_root),
            check=False,
            timeout=300.0,
        )
    finally:
        probe.unlink(missing_ok=True)
    if result.exit_code != 0:
        raise BuildError(
            "could not read the flags out of the generated rules.mak: "
            f"{result.stderr[-500:]}"
        )
    flags: dict[str, str] = {}
    for line in result.stdout.splitlines():
        name, _, value = line.partition("=")
        if name in ("CFLAGS", "CDEFS", "LDFLAGS"):
            flags[name] = " ".join(value.split())
    missing = sorted({"CFLAGS", "CDEFS", "LDFLAGS"} - set(flags))
    if missing:
        raise BuildError(f"rules.mak defines no {missing}")
    # The flags this project added ride on CC rather than on CFLAGS, so they are
    # folded in here: the manifest records what the compiler received.
    if compiler.extra_flags:
        flags["CFLAGS"] = " ".join([*compiler.extra_flags, flags["CFLAGS"]])
    return flags


def require_acceptable_flags(**flags: str) -> None:
    """Refuse a flag that ties the build to the machine that made it.

    Applied to the environment before the build, and to the flags NBIS's own
    ``rules.mak`` turns out to use afterwards. The environment check matters even
    though ``rules.mak`` assigns ``CFLAGS`` with ``:=`` and therefore ignores it:
    an operator who exported one of these meant it to take effect, and refusing is
    the only outcome that does not quietly disappoint them (spec section 9).
    """
    for label, value in flags.items():
        for fragment in FORBIDDEN_FLAG_FRAGMENTS:
            if fragment in (value or ""):
                raise BuildError(
                    f"{label} contains {fragment!r}, which makes the build depend on "
                    "the machine it was built on (spec section 9)"
                )


def _require_acceptable_environment_flags() -> None:
    require_acceptable_flags(
        **{
            "the environment's CFLAGS": os.environ.get("CFLAGS", ""),
            "the environment's CPPFLAGS": os.environ.get("CPPFLAGS", ""),
            "the environment's LDFLAGS": os.environ.get("LDFLAGS", ""),
        }
    )


def _require_no_patches_touch_behaviour() -> None:
    """The default is no patches at all, and that default is checked, not assumed."""
    payload = json.loads(SERIES_PATH.read_text(encoding="utf-8"))
    entries = payload.get("patches") or []
    if entries:
        raise BuildError(
            "patches/series.json is not empty. Stage 7B builds NBIS 5.0.0 unmodified; "
            "a patch is a reviewed change with its own argument, and this script will "
            "not apply one on its behalf (spec section 7)"
        )


def setup_options(target_architecture: str) -> list[str]:
    """NBIS's own configure switches. Part of what a build id covers.

    ``--without-X11`` because nothing this route uses needs it and it drags in a
    dependency that is a property of the machine. ``--64`` on x86_64 because
    NBIS's default is a 32-bit build on a cross-capable toolchain.
    """
    options = ["--without-X11"]
    if target_architecture == "x86_64":
        options.append("--64")
    return options


def collect_build_inputs(lock: NbisSourceLock, compiler: Compiler) -> BuildInputs:
    _require_acceptable_environment_flags()
    _require_no_patches_touch_behaviour()
    target_os, target_architecture = host_target()
    return BuildInputs(
        source_archive_sha256=str(lock.release.sha256),
        source_archive_size_bytes=lock.release.size_bytes,
        test_archive_sha256=str(lock.tests.sha256),
        test_archive_size_bytes=lock.tests.size_bytes,
        patchset_fingerprint=patchset_fingerprint(SERIES_PATH),
        build_script_fingerprint=build_script_fingerprint(HERE),
        target_os=target_os,
        target_architecture=target_architecture,
        compiler_id=compiler.identity,
        compiler_version=compiler.version,
        compiler_target=compiler.target,
        compiler_extra_flags=" ".join(compiler.extra_flags),
        setup_options=" ".join(setup_options(target_architecture)),
    )


def compile_nbis(
    *, source_root: Path, install_root: Path, compiler: Compiler, shim: Path
) -> dict[str, str]:
    """Run NBIS's own build, with one compiler reaching every part of it.

    Three places would otherwise choose their own: ``setup.sh`` compiles its
    endianness probe with a literal ``gcc``, ``rules.mak`` assigns
    ``CC := $(shell which gcc)``, and ``make`` would inherit whichever of those
    won. The shim directory settles the first two and the command-line ``CC=``
    settles the third, so the compiler this script probed is the compiler that
    builds — which is the whole of the provenance claim.

    Returns the flags the build actually used.
    """
    architecture = host_target()[1]
    run(
        ["./setup.sh", str(install_root), *setup_options(architecture)],
        cwd=source_root,
        extra_path=shim,
    )
    for target in ("config", "it", "install"):
        run(make_command(target, compiler), cwd=source_root, extra_path=shim)
    flags = read_build_flags(source_root, compiler)
    require_acceptable_flags(
        **{f"the build's {name}": value for name, value in flags.items()}
    )
    return flags


def _find_source_root(extracted: Path) -> Path:
    """The directory holding NBIS's own ``setup.sh``, wherever the archive put it."""
    candidates = sorted(extracted.rglob("setup.sh"))
    if not candidates:
        raise BuildError(
            "the extracted NBIS release has no setup.sh; this is not the NIST "
            "distribution layout"
        )
    return min(candidates, key=lambda path: len(path.parts)).parent


def command_build(arguments: argparse.Namespace) -> int:
    """Compile the verified sources. No network, no substitute archive."""
    lock = require_sealed_lock()
    cache = Path(arguments.cache)
    _require_outside_repository(cache)
    archives = verify_cached_archives(lock, cache)
    compiler = resolve_compiler()
    inputs = collect_build_inputs(lock, compiler)

    output = BUILD_ROOT / inputs.build_id
    if output.exists() and not arguments.force:
        raise BuildError(
            f"{output.name} already exists. A build id covers the sources, the patch "
            "series, the build script, the compiler and the setup options, so an "
            "existing one is the same build; pass --force to replace it deliberately"
        )
    if output.exists():
        shutil.rmtree(output)

    workspace = Path(
        tempfile.mkdtemp(
            prefix=f"nbis-{inputs.build_id}-", dir=str(_ensure(cache / "work"))
        )
    )
    try:
        source_root = _find_source_root(
            safe_extract(archives["release"], workspace / "release")
        )
        install_root = _ensure(workspace / "install")
        shim = compiler_shim(workspace / "compiler", compiler)

        print(
            f"building NBIS {EXPECTED_NBIS_VERSION} ({inputs.build_id}) "
            f"with {compiler.identity} {compiler.target}"
        )
        flags = compile_nbis(
            source_root=source_root,
            install_root=install_root,
            compiler=compiler,
            shim=shim,
        )

        binaries = _ensure(output / "bin")
        for tool in TOOLS:
            built = _locate_tool(install_root, tool)
            target = binaries / tool
            shutil.copyfile(built, target)
            target.chmod(0o755)

        _write_json_atomically(
            output / "build-inputs.json",
            {
                "schema_version": BUILD_MANIFEST_SCHEMA_VERSION,
                "nbis_version": EXPECTED_NBIS_VERSION,
                "build_id": inputs.build_id,
                **inputs.as_plain(),
                # What the build actually used, read back out of the generated
                # rules.mak rather than declared in advance (spec section 10).
                "cflags": flags["CFLAGS"],
                "cppflags": flags["CDEFS"],
                "ldflags": flags["LDFLAGS"],
            },
        )
    finally:
        if not arguments.keep_sources:
            shutil.rmtree(workspace, ignore_errors=True)

    print(f"built into {output}")
    print("run 'build.py test' to certify it; until then it has no build manifest")
    return 0


def _read_build_inputs(output: Path, inputs: BuildInputs) -> dict[str, str]:
    """What ``build`` wrote down about itself, and that it is still this build.

    The build id already covers the sources, the patch series, the build script,
    the compiler and the setup options, so a directory found under that id was
    produced from these inputs. This re-reads it anyway and compares, because the
    manifest about to be signed says so and a signature over an assumption is not
    a signature.
    """
    path = Path(output) / "build-inputs.json"
    if not path.is_file():
        raise BuildError(
            f"{output.name} holds no build-inputs.json; rebuild it with "
            "'build.py build'"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BuildError(f"{path.name} is unreadable: {type(exc).__name__}") from exc

    for name, expected in inputs.as_plain().items():
        if payload.get(name) != expected:
            raise BuildError(
                f"{path.name} records {name}={payload.get(name)!r}, but this "
                f"invocation resolves {expected!r}. Rebuild before certifying"
            )
    flags = {name: payload.get(name) for name in ("cflags", "cppflags", "ldflags")}
    if any(value is None for value in flags.values()):
        raise BuildError(f"{path.name} records no build flags; rebuild it")
    require_acceptable_flags(
        **{f"the recorded {name}": str(value) for name, value in flags.items()}
    )
    return {name: str(value) for name, value in flags.items()}


def _locate_tool(install_root: Path, tool: str) -> Path:
    candidates = [
        path
        for path in install_root.rglob(tool)
        if path.is_file() and not path.is_symlink() and os.access(path, os.X_OK)
    ]
    if not candidates:
        raise BuildError(f"the build produced no {tool} executable")
    return min(candidates, key=lambda path: len(path.parts))


# --------------------------------------------------------------------- test


def command_test(arguments: argparse.Namespace) -> int:
    """Run NIST's own suite and this project's probes; write the manifest last."""
    lock = require_sealed_lock()
    cache = Path(arguments.cache)
    archives = verify_cached_archives(lock, cache)
    compiler = resolve_compiler()
    inputs = collect_build_inputs(lock, compiler)
    output = BUILD_ROOT / inputs.build_id
    binaries = output / "bin"
    if not (binaries / "mindtct").is_file():
        raise BuildError(f"there is no build at {output.name}; run 'build.py build'")
    # The flags are read from what ``build`` recorded rather than re-derived: the
    # manifest has to describe the build that happened, not the one this
    # invocation would produce (spec section 10).
    recorded = _read_build_inputs(output, inputs)

    workspace = Path(tempfile.mkdtemp(prefix="nbis-test-", dir=_ensure(cache / "work")))
    try:
        tests_root = safe_extract(archives["tests"], workspace / "tests")
        summary = run_official_tests(tests_root, binaries)
        if not summary.is_accepted:
            raise BuildError(
                "the official NIST tests did not all pass "
                f"(discovered={summary.discovered_tests} "
                f"executed={summary.executed_tests} failed={summary.failed_tests}). "
                "Golden output is never edited to make a test pass"
            )

        png_supported, gray8_verified = probe_png_capability(
            binaries, _ensure(workspace / "png")
        )
        if not (png_supported and gray8_verified):
            raise BuildError(
                "this build does not accept a direct 8-bit greyscale PNG. PNG "
                "support is an acceptance condition and there is no WSQ fallback "
                "(spec section 41)"
            )
        ppi_policy = probe_ppi_policy(binaries, _ensure(workspace / "ppi"))
        if ppi_policy != EXPECTED_PNG_PPI_POLICY:
            raise BuildError(
                f"the PPI probe concluded {ppi_policy!r}. Stage 7B stops here: the "
                "500-ppi-only route is designed around metadata being ignored, and "
                "the policy is never written from memory (spec section 22)"
            )

        # The same function the adapter uses to re-ask the question later, so the
        # recorded answer and the checked answer cannot be normalised differently.
        versions = {
            tool: version_probe(binaries / tool, VERSION_PROBES[tool]) or ""
            for tool in TOOLS
        }
        dependencies = {
            tool: dynamic_dependencies(binaries / tool) for tool in TOOLS
        }
        digests = {tool: file_digest(binaries / tool) for tool in TOOLS}

        manifest = NbisBuildManifest.create(
            schema_version=BUILD_MANIFEST_SCHEMA_VERSION,
            nbis_version=EXPECTED_NBIS_VERSION,
            source_archive_sha256=inputs.source_archive_sha256,
            source_archive_size_bytes=inputs.source_archive_size_bytes,
            test_archive_sha256=inputs.test_archive_sha256,
            test_archive_size_bytes=inputs.test_archive_size_bytes,
            patchset_fingerprint=inputs.patchset_fingerprint,
            build_script_fingerprint=inputs.build_script_fingerprint,
            target_os=inputs.target_os,
            target_architecture=inputs.target_architecture,
            compiler_id=inputs.compiler_id,
            compiler_version=inputs.compiler_version,
            compiler_target=inputs.compiler_target,
            cflags=recorded["cflags"],
            cppflags=recorded["cppflags"],
            ldflags=recorded["ldflags"],
            mindtct_version_output=versions["mindtct"],
            bozorth3_version_output=versions["bozorth3"],
            png_support_compiled=png_supported,
            direct_gray8_png_verified=gray8_verified,
            png_ppi_policy=ppi_policy,
            mindtct_sha256=digests["mindtct"][0],
            mindtct_size_bytes=digests["mindtct"][1],
            bozorth3_sha256=digests["bozorth3"][0],
            bozorth3_size_bytes=digests["bozorth3"][1],
            dynamic_dependencies=dependencies,
            official_test_summary=summary,
            created_utc=datetime.now(timezone.utc).isoformat(),
        )
        # Written only after it has been checked against the very files it
        # describes, so a manifest on disk is always one the adapter will accept.
        verify_build_manifest(
            manifest, mindtct=binaries / "mindtct", bozorth3=binaries / "bozorth3"
        )
        _write_json_atomically(output / BUILD_MANIFEST_FILENAME, manifest.as_plain())
    finally:
        if not arguments.keep_sources:
            shutil.rmtree(workspace, ignore_errors=True)

    print(f"certified {output / BUILD_MANIFEST_FILENAME}")
    return 0


def run_official_tests(tests_root: Path, binaries: Path) -> NbisOfficialTestSummary:
    """Every relevant test NIST published for these tools, run unmodified.

    Discovery is by directory name and then by executable script. A layout this
    does not recognise raises rather than returning an empty suite: a summary
    saying "0 discovered, 0 failed" would satisfy a careless reading of the
    acceptance condition while proving nothing at all (spec section 40).
    """
    directories = sorted(
        path
        for path in tests_root.rglob("*")
        if path.is_dir() and path.name.lower() in RELEVANT_TEST_TOOLS
    )
    if not directories:
        listing = sorted({path.name for path in tests_root.rglob("*") if path.is_dir()})
        raise BuildError(
            "no relevant NIST test directory was found. Expected one of "
            f"{list(RELEVANT_TEST_TOOLS)}; the package holds {listing[:40]}. Confirm "
            "the layout and update RELEVANT_TEST_TOOLS in this script"
        )

    scripts: list[Path] = []
    for directory in directories:
        found = sorted(
            path
            for path in directory.rglob("*.sh")
            if path.is_file() and not path.is_symlink()
        )
        if not found:
            raise BuildError(
                f"the {directory.name!r} test directory holds no runnable script; "
                "refusing to report it as passing"
            )
        scripts.extend(found)

    records: list[dict[str, object]] = []
    passed = 0
    failed = 0
    for script in scripts:
        script.chmod(0o755)
        result = run(
            ["sh", script.name],
            cwd=script.parent,
            extra_path=binaries,
            check=False,
            timeout=1800.0,
        )
        ok = result.exit_code == 0
        passed += int(ok)
        failed += int(not ok)
        records.append(
            {
                "name": script.relative_to(tests_root).as_posix(),
                "exit_code": result.exit_code,
                "stdout_sha256": hashlib.sha256(
                    result.stdout.encode("utf-8")
                ).hexdigest(),
                "stderr_sha256": hashlib.sha256(
                    result.stderr.encode("utf-8")
                ).hexdigest(),
            }
        )
        if not ok:
            print(f"FAILED {records[-1]['name']}\n{result.stdout[-1500:]}")

    ordered = hashlib.sha256(
        json.dumps(records, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return NbisOfficialTestSummary(
        test_suite_version=EXPECTED_NBIS_VERSION,
        discovered_tests=len(scripts),
        executed_tests=len(records),
        passed_tests=passed,
        failed_tests=failed,
        ordered_output_hash=ordered,
    )


# --------------------------------------------------------------- PNG probes


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def _ridge_rows(size: int) -> tuple[bytearray, list[int]]:
    """Half an inch of synthetic warped ridges. Not a fingerprint."""
    import math

    period = PROBE_PPI / RIDGES_PER_INCH
    centre = size / 2.0
    rows = bytearray()
    flat: list[int] = []
    for y in range(size):
        rows.append(0)
        for x in range(size):
            dx, dy = x - centre, y - centre
            radius = math.hypot(dx, dy)
            angle = math.atan2(dy, dx)
            warp = 0.35 * period * math.sin(3 * angle) + 0.20 * period * math.sin(
                (x + 1.3 * y) / (2.5 * period)
            )
            value = 128 + 110 * math.sin(2 * math.pi * (radius + warp) / period)
            falloff = max(0.0, 1.0 - radius / (0.52 * size))
            level = min(255, max(0, int(round(255 - (255 - value) * falloff))))
            rows.append(level)
            flat.append(level)
    return rows, flat


def probe_pngs(directory: Path) -> dict[str, Path]:
    """The seven probe images, written from one raster.

    The three PPI probes share *identical pixels* on purpose: if MINDTCT's output
    differs between them, the only thing that can have caused it is the ``pHYs``
    chunk (spec section 22).
    """
    size = int(round(PROBE_INCHES * PROBE_PPI))
    rows, flat = _ridge_rows(size)
    compressed = zlib.compress(bytes(rows), 6)
    header = struct.pack(">IIBBBBB", size, size, 8, 0, 0, 0, 0)

    def phys(ppi: int) -> bytes:
        per_metre = round(ppi / 0.0254)
        return _chunk(b"pHYs", struct.pack(">IIB", per_metre, per_metre, 1))

    def assemble(*parts: bytes) -> bytes:
        return b"\x89PNG\r\n\x1a\n" + b"".join(parts)

    gray_idat = _chunk(b"IDAT", compressed)
    written: dict[str, Path] = {}

    payloads = {
        "gray8_500ppi": assemble(
            _chunk(b"IHDR", header), phys(500), gray_idat, _chunk(b"IEND", b"")
        ),
        "gray8_1000ppi": assemble(
            _chunk(b"IHDR", header), phys(1000), gray_idat, _chunk(b"IEND", b"")
        ),
        "gray8_no_phys": assemble(
            _chunk(b"IHDR", header), gray_idat, _chunk(b"IEND", b"")
        ),
    }

    sixteen = bytearray()
    for y in range(size):
        sixteen.append(0)
        for x in range(size):
            sixteen += struct.pack(">H", flat[y * size + x] * 257)
    payloads["gray16"] = assemble(
        _chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 16, 0, 0, 0, 0)),
        phys(500),
        _chunk(b"IDAT", zlib.compress(bytes(sixteen), 6)),
        _chunk(b"IEND", b""),
    )

    rgb = bytearray()
    for y in range(size):
        rgb.append(0)
        for x in range(size):
            level = flat[y * size + x]
            rgb += bytes((level, level, level))
    payloads["rgb8"] = assemble(
        _chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)),
        phys(500),
        _chunk(b"IDAT", zlib.compress(bytes(rgb), 6)),
        _chunk(b"IEND", b""),
    )

    palette = b"".join(bytes((value, value, value)) for value in range(256))
    indexed = bytearray()
    for y in range(size):
        indexed.append(0)
        for x in range(size):
            indexed.append(flat[y * size + x])
    payloads["indexed8"] = assemble(
        _chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 3, 0, 0, 0)),
        _chunk(b"PLTE", palette),
        phys(500),
        _chunk(b"IDAT", zlib.compress(bytes(indexed), 6)),
        _chunk(b"IEND", b""),
    )
    payloads["corrupt"] = b"\x89PNG\r\n\x1a\ndeliberately not a valid PNG body"

    for name, payload in payloads.items():
        path = Path(directory) / f"{name}.png"
        path.write_bytes(payload)
        written[name] = path
    return written


def _mindtct(binaries: Path, image: Path, root: Path) -> CommandResult:
    return run(
        [str(binaries / "mindtct"), str(image), str(root)],
        cwd=root.parent,
        check=False,
        timeout=300.0,
    )


def probe_png_capability(binaries: Path, directory: Path) -> tuple[bool, bool]:
    """gray8 in, everything else out — measured on the build, not assumed.

    Returns ``(png_support_compiled, direct_gray8_png_verified)``.
    """
    images = probe_pngs(directory)
    accepted = _mindtct(binaries, images["gray8_500ppi"], directory / "accept")
    gray8_ok = accepted.exit_code == 0 and (directory / "accept.xyt").is_file()

    rejected: list[str] = []
    for name in ("gray16", "rgb8", "indexed8", "corrupt"):
        result = _mindtct(binaries, images[name], directory / f"reject-{name}")
        if result.exit_code == 0 and (directory / f"reject-{name}.xyt").is_file():
            rejected.append(name)
    if rejected:
        raise BuildError(
            f"this build accepted {rejected}, which the input contract forbids. The "
            "adapter rejects them before the subprocess, but a build that quietly "
            "converts them is not the build this stage certified (spec section 41)"
        )

    no_phys = _mindtct(binaries, images["gray8_no_phys"], directory / "nophys")
    no_phys_ok = no_phys.exit_code == 0 and (directory / "nophys.xyt").is_file()
    return (gray8_ok and no_phys_ok, gray8_ok)


def probe_ppi_policy(binaries: Path, directory: Path) -> str:
    """Does a ``pHYs`` chunk change what MINDTCT extracts? Answered by running it.

    Three PNGs, identical pixels, three different resolution declarations. If the
    XYT bytes are identical the metadata is ignored and the default applies; if
    they are not, the route as designed does not exist and the stage stops
    (docs/adr/0047).
    """
    images = probe_pngs(directory)
    outputs: dict[str, bytes] = {}
    for name in ("gray8_500ppi", "gray8_1000ppi", "gray8_no_phys"):
        root = directory / f"ppi-{name}"
        result = _mindtct(binaries, images[name], root)
        xyt = root.with_suffix(".xyt")
        if result.exit_code != 0 or not xyt.is_file():
            raise BuildError(f"the PPI probe could not extract from {name}")
        outputs[name] = xyt.read_bytes()

    distinct = {digest for digest in (hashlib.sha256(v).hexdigest() for v in outputs.values())}
    if len(distinct) == 1:
        return EXPECTED_PNG_PPI_POLICY
    return "metadata_changes_extraction"


def dynamic_dependencies(tool: Path) -> list[str]:
    """The shared objects a tool actually loads, by soname.

    ``ldd`` on a fully static binary says so and reports nothing, which is the
    expected answer here. Paths are deliberately dropped: a manifest records what
    is linked, never where this machine keeps it.
    """
    result = run(["ldd", str(tool)], cwd=tool.parent, check=False, timeout=120.0)
    if result.exit_code != 0 or "not a dynamic executable" in result.stdout:
        return []
    sonames: set[str] = set()
    for line in result.stdout.splitlines():
        text = line.strip()
        if not text or text.startswith("statically linked"):
            continue
        soname = text.split("=>")[0].strip().split()[0]
        if soname.startswith("/"):
            soname = soname.rsplit("/", 1)[-1]
        if soname:
            sonames.add(soname)
    return sorted(sonames)


# ------------------------------------------------------------------ inspect


def command_inspect(arguments: argparse.Namespace) -> int:
    """Say where everything stands. Writes nothing, downloads nothing."""
    lock = read_source_lock(LOCK_PATH)
    print(f"lock:   {_display(LOCK_PATH)}")
    for name, entry in (("release", lock.release), ("tests", lock.tests)):
        state = "sealed" if entry.is_sealed else "UNSEALED"
        print(f"  {name}: {state} {entry.sha256 or ''} {entry.size_bytes or ''}".rstrip())

    cache = Path(arguments.cache)
    print(f"cache:  {cache}")
    for name, path in cache_paths(cache).items():
        if not path.is_file():
            print(f"  {name}: absent")
            continue
        digest, size = file_digest(path)
        locked = getattr(lock, name)
        verdict = "verified" if (digest == locked.sha256 and size == locked.size_bytes) else "DOES NOT MATCH THE LOCK"
        print(f"  {name}: {verdict} ({size} bytes)")

    print(f"builds: {BUILD_ROOT}")
    if BUILD_ROOT.is_dir():
        for directory in sorted(p for p in BUILD_ROOT.iterdir() if p.is_dir()):
            manifest = directory / BUILD_MANIFEST_FILENAME
            if not manifest.is_file():
                print(f"  {directory.name}: built, NOT certified (no build manifest)")
                continue
            try:
                from fpbench.adapters.nbis.build_manifest import read_build_manifest

                loaded = read_build_manifest(manifest)
                verify_build_manifest(
                    loaded,
                    mindtct=directory / "bin" / "mindtct",
                    bozorth3=directory / "bin" / "bozorth3",
                )
            except NbisBuildManifestError as exc:
                print(f"  {directory.name}: INVALID — {exc}")
                continue
            print(
                f"  {directory.name}: certified, NBIS {loaded.nbis_version}, "
                f"{loaded.official_test_summary.passed_tests} NIST tests passed"
            )
    else:
        print("  (none)")
    return 0


# ------------------------------------------------------------------ helpers


def _ensure(path: Path) -> Path:
    Path(path).mkdir(parents=True, exist_ok=True)
    return Path(path)


def _display(path: Path) -> str:
    """Repository-relative when it can be, absolute when it cannot."""
    try:
        return Path(path).relative_to(REPOSITORY_ROOT).as_posix()
    except ValueError:
        return str(path)


def _require_outside_repository(path: Path) -> None:
    resolved = Path(path).resolve()
    if resolved.is_relative_to(REPOSITORY_ROOT.resolve()) and not resolved.is_relative_to(
        (REPOSITORY_ROOT / "build").resolve()
    ):
        raise BuildError(
            f"{resolved} is inside the repository. Upstream sources are never "
            "extracted into the working tree (spec section 6)"
        )


def _write_json_atomically(path: Path, payload: object) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    temporary.replace(target)
    return target


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--cache",
        type=Path,
        default=DEFAULT_CACHE,
        help="where verified archives and scratch trees live (never the repository)",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    seal = commands.add_parser("seal", help="record the digest of an archive, once")
    seal.add_argument("--release", type=Path)
    seal.add_argument("--release-url")
    seal.add_argument("--tests", type=Path)
    seal.add_argument("--tests-url")
    seal.set_defaults(handler=command_seal)

    fetch = commands.add_parser("fetch", help="download and verify the locked archives")
    fetch.set_defaults(handler=command_fetch)

    build = commands.add_parser("build", help="compile the verified sources")
    build.add_argument("--force", action="store_true")
    build.add_argument("--keep-sources", action="store_true")
    build.set_defaults(handler=command_build)

    test = commands.add_parser(
        "test", help="run NIST's suite and the probes, then write the manifest"
    )
    test.add_argument("--keep-sources", action="store_true")
    test.set_defaults(handler=command_test)

    inspect = commands.add_parser("inspect", help="report where everything stands")
    inspect.set_defaults(handler=command_inspect)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    arguments = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        return int(arguments.handler(arguments))
    except (BuildError, NbisBuildManifestError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
