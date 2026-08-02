"""What was built, from which bytes, with which compiler — as one signed record.

An NBIS build is not a package version. Two machines running ``5.0.0`` can have
compiled different sources with different flags against different libpng copies,
and the scores would differ without anything in the run saying so. So the build
writes down everything that could move a score and signs it, and every later step
— the adapter, the research integration, CI after a cache restore — re-checks the
record against the files it claims to describe.

Three separate questions, deliberately not conflated:

``verify_build_manifest``
    Is this manifest internally sound, and are the two executables beside it the
    exact bytes it names? Answerable from the bundle alone, which is what the
    research adapter has after pinning.

``verify_against_source_lock``
    Were those executables built from the archives this repository locked? Needs
    ``integrations/nbis/nbis-5.0.0.lock.json``, so it is asked by the integration
    rather than by the adapter (spec section 12).

``verify_against_repository``
    Was it built by *this* build script with *this* patch series? Same reasoning.

Nothing here reads a path out of a manifest, because no manifest carries one. A
build directory, a cache directory, a home directory and a user name are all
facts about a machine rather than about an experiment, and a manifest that
carried one would leak it into the runtime bundle and from there into published
evidence (spec section 10).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from fpbench.core.serialization import stable_hash

__all__ = [
    "BUILD_MANIFEST_SCHEMA_VERSION",
    "BUILD_MANIFEST_FILENAME",
    "EXPECTED_NBIS_VERSION",
    "EXPECTED_PNG_PPI_POLICY",
    "REQUIRED_PNG_REFUSALS",
    "SUPPORTED_TARGETS",
    "FORBIDDEN_DYNAMIC_DEPENDENCIES",
    "BUILD_SCRIPT_FILES",
    "LOCK_FILENAME",
    "PATCH_SERIES_RELATIVE_PATH",
    "NbisBuildManifestError",
    "NbisOfficialTestSummary",
    "NbisBuildManifest",
    "NbisArchiveLock",
    "NbisSourceLock",
    "read_build_manifest",
    "read_source_lock",
    "patchset_fingerprint",
    "build_script_fingerprint",
    "verify_build_manifest",
    "verify_against_source_lock",
    "verify_against_repository",
    "file_digest",
    "host_target",
]

#: Bumped when the meaning of a field changes, never when a value does.
BUILD_MANIFEST_SCHEMA_VERSION = "1"

#: The file the build writes next to ``bin/``.
BUILD_MANIFEST_FILENAME = "nbis-build-manifest.json"

#: The one release stage 7B certifies. Not configurable: a different NBIS is a
#: different algorithm identity and needs its own stage (docs/adr/0046).
EXPECTED_NBIS_VERSION = "5.0.0"

#: The probe images the build itself must refuse. 16-bit and indexed-colour are
#: deliberately *not* here: NBIS 5.0.0 passes PNG to libpng, which down-converts
#: both, and that was measured rather than assumed. Neither can reach MINDTCT on
#: this route, because the adapter refuses them before a subprocess exists. A
#: truecolour or unreadable PNG is different in kind — silently flattening one
#: would change the pixels being compared — so those two stay acceptance
#: conditions (docs/adr/0048, spec section 41).
REQUIRED_PNG_REFUSALS: frozenset[str] = frozenset({"rgb8", "corrupt"})

#: What the PPI capability probe must have concluded. Written by the build after
#: running MINDTCT over three PNGs with identical pixels and different ``pHYs``
#: chunks; the adapter refuses a manifest claiming anything else, because the
#: whole 500-ppi-only argument rests on this being measured rather than assumed
#: (docs/adr/0047, spec section 22).
EXPECTED_PNG_PPI_POLICY = "metadata_ignored_default_500"

#: The platforms this stage certified a build for. A tuple of
#: ``(target_os, target_architecture)`` exactly as the manifest spells them.
SUPPORTED_TARGETS: frozenset[tuple[str, str]] = frozenset({("linux", "x86_64")})

#: Library names that must never appear among a tool's dynamic dependencies. Any
#: of them means the score depends on whatever the machine happens to have
#: installed rather than on the pinned bundle (spec section 9).
FORBIDDEN_DYNAMIC_DEPENDENCIES: tuple[str, ...] = (
    "libpng",
    "libz",
    "libfing",
    "libmindtct",
    "libbozorth",
    "liban2k",
    "libihead",
    "libjpegb",
    "libjpegl",
    "libwsq",
    "libnbis",
)

#: The scripts whose bytes decide how the build ran. Relative to
#: ``integrations/nbis/``.
BUILD_SCRIPT_FILES: tuple[str, ...] = ("build.py", "verify_build.py")

LOCK_FILENAME = "nbis-5.0.0.lock.json"
PATCH_SERIES_RELATIVE_PATH = "patches/series.json"

_HEX = frozenset("0123456789abcdef")

#: Everything the fingerprint covers, in declaration order. ``manifest_fingerprint``
#: and ``created_utc`` are absent by construction: a digest cannot cover itself,
#: and a timestamp would make two identical builds fingerprint differently.
_FINGERPRINTED_FIELDS: tuple[str, ...] = (
    "schema_version",
    "nbis_version",
    "source_archive_sha256",
    "source_archive_size_bytes",
    "test_archive_sha256",
    "test_archive_size_bytes",
    "patchset_fingerprint",
    "build_script_fingerprint",
    "target_os",
    "target_architecture",
    "compiler_id",
    "compiler_version",
    "compiler_target",
    "cflags",
    "cppflags",
    "ldflags",
    "mindtct_version_output",
    "bozorth3_version_output",
    "png_support_compiled",
    "direct_gray8_png_verified",
    "png_formats_refused_by_build",
    "png_ppi_policy",
    "mindtct_sha256",
    "mindtct_size_bytes",
    "bozorth3_sha256",
    "bozorth3_size_bytes",
    "dynamic_dependencies",
    "official_test_summary",
)

#: A crude but effective guard against a manifest that picked up somebody's home
#: directory. Applied to every string value before the manifest is accepted.
_PATH_SHAPED = re.compile(
    r"(/home/|/Users/|/root/|/tmp/|/var/tmp/|[A-Za-z]:\\|\\Users\\)"
)


class NbisBuildManifestError(Exception):
    """A build manifest is missing, malformed, or does not describe the files.

    Deliberately a plain exception rather than an ``AdapterError``: it is raised
    by the build scripts as well as by the adapter, and ``integrations/`` is not
    part of the ``fpbench`` package.
    """


# ---------------------------------------------------------------- validation


def _require_sha256(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise NbisBuildManifestError(
            f"{field_name} must be a string, got {type(value).__name__}"
        )
    digest = value.strip().lower()
    if len(digest) != 64 or not set(digest) <= _HEX:
        raise NbisBuildManifestError(
            f"{field_name} must be a 64-character hexadecimal digest"
        )
    return digest


def _require_text(value: Any, field_name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise NbisBuildManifestError(
            f"{field_name} must be a string, got {type(value).__name__}"
        )
    text = value.strip()
    if not text and not allow_empty:
        raise NbisBuildManifestError(f"{field_name} must not be empty")
    if _PATH_SHAPED.search(value):
        raise NbisBuildManifestError(
            f"{field_name} looks like it carries a local path; a build manifest "
            "records what was built, never where (spec section 10)"
        )
    return text


def _require_exact_int(value: Any, field_name: str, *, minimum: int = 0) -> int:
    if type(value) is not int:
        raise NbisBuildManifestError(
            f"{field_name} must be an exact integer, got {type(value).__name__}"
        )
    if value < minimum:
        raise NbisBuildManifestError(f"{field_name} must be at least {minimum}")
    return value


def _require_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise NbisBuildManifestError(
            f"{field_name} must be a JSON boolean, got {type(value).__name__}"
        )
    return value


# --------------------------------------------------------------- test summary


@dataclass(frozen=True, slots=True)
class NbisOfficialTestSummary:
    """What NIST's own Test 5.0.0 package said about this build.

    ``discovered_tests`` and ``executed_tests`` are separate so that a run which
    silently skipped half the suite is visible as a number rather than as an
    absence. Acceptance needs both ``failed_tests == 0`` and
    ``executed_tests == discovered_tests`` (spec section 40).
    """

    test_suite_version: str
    discovered_tests: int
    executed_tests: int
    passed_tests: int
    failed_tests: int
    ordered_output_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "test_suite_version",
            _require_text(self.test_suite_version, "test_suite_version"),
        )
        for name in (
            "discovered_tests",
            "executed_tests",
            "passed_tests",
            "failed_tests",
        ):
            object.__setattr__(
                self, name, _require_exact_int(getattr(self, name), name)
            )
        object.__setattr__(
            self,
            "ordered_output_hash",
            _require_sha256(self.ordered_output_hash, "ordered_output_hash"),
        )
        if self.passed_tests + self.failed_tests != self.executed_tests:
            raise NbisBuildManifestError(
                "official_test_summary: passed + failed must equal executed, got "
                f"{self.passed_tests} + {self.failed_tests} != {self.executed_tests}"
            )
        if self.executed_tests > self.discovered_tests:
            raise NbisBuildManifestError(
                "official_test_summary: more tests were executed than discovered"
            )

    @property
    def is_accepted(self) -> bool:
        """Every relevant discovered test ran, and none of them failed."""
        return (
            self.failed_tests == 0
            and self.discovered_tests > 0
            and self.executed_tests == self.discovered_tests
        )

    def as_plain(self) -> dict[str, Any]:
        return {
            "test_suite_version": self.test_suite_version,
            "discovered_tests": self.discovered_tests,
            "executed_tests": self.executed_tests,
            "passed_tests": self.passed_tests,
            "failed_tests": self.failed_tests,
            "ordered_output_hash": self.ordered_output_hash,
        }

    @classmethod
    def from_plain(cls, payload: Any) -> "NbisOfficialTestSummary":
        if not isinstance(payload, Mapping):
            raise NbisBuildManifestError(
                "official_test_summary must be a JSON object"
            )
        known = set(cls.__slots__)
        unknown = sorted(set(payload) - known)
        if unknown:
            raise NbisBuildManifestError(
                f"official_test_summary has unknown keys: {unknown}"
            )
        missing = sorted(known - set(payload))
        if missing:
            raise NbisBuildManifestError(
                f"official_test_summary is missing: {missing}"
            )
        return cls(**{name: payload[name] for name in known})


# ------------------------------------------------------------------ manifest


@dataclass(frozen=True, slots=True)
class NbisBuildManifest:
    """The canonical content of ``nbis-build-manifest.json``."""

    schema_version: str
    nbis_version: str

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

    cflags: str
    cppflags: str
    ldflags: str

    mindtct_version_output: str
    bozorth3_version_output: str

    png_support_compiled: bool
    direct_gray8_png_verified: bool

    #: Which of the probe images the build itself refused, sorted and comma
    #: separated. Measured, and recorded because the answer surprised this
    #: project: NBIS 5.0.0 hands PNG to libpng, which happily down-converts a
    #: 16-bit raster and expands a palette, so the build *accepts* those two.
    #: The route is unaffected — the adapter refuses anything that is not 8-bit
    #: greyscale before a subprocess exists (docs/adr/0048) — but a build that
    #: silently converted a *truecolour* image would be changing pixels, so
    #: ``rgb8`` and ``corrupt`` remain acceptance conditions.
    png_formats_refused_by_build: str

    png_ppi_policy: str

    mindtct_sha256: str
    mindtct_size_bytes: int

    bozorth3_sha256: str
    bozorth3_size_bytes: int

    #: Tool name -> the shared objects it actually loads, sorted. Empty tuples
    #: are legal and are what a fully static build produces on some toolchains.
    dynamic_dependencies: Mapping[str, tuple[str, ...]]

    official_test_summary: NbisOfficialTestSummary

    manifest_fingerprint: str
    created_utc: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "schema_version", _require_text(self.schema_version, "schema_version")
        )
        if self.schema_version != BUILD_MANIFEST_SCHEMA_VERSION:
            raise NbisBuildManifestError(
                f"build manifest schema_version is {self.schema_version!r}; this "
                f"code reads {BUILD_MANIFEST_SCHEMA_VERSION!r}"
            )
        object.__setattr__(
            self, "nbis_version", _require_text(self.nbis_version, "nbis_version")
        )
        for name in (
            "source_archive_sha256",
            "test_archive_sha256",
            "patchset_fingerprint",
            "build_script_fingerprint",
            "mindtct_sha256",
            "bozorth3_sha256",
            "manifest_fingerprint",
        ):
            object.__setattr__(
                self, name, _require_sha256(getattr(self, name), name)
            )
        for name in (
            "source_archive_size_bytes",
            "test_archive_size_bytes",
            "mindtct_size_bytes",
            "bozorth3_size_bytes",
        ):
            object.__setattr__(
                self, name, _require_exact_int(getattr(self, name), name, minimum=1)
            )
        for name in (
            "target_os",
            "target_architecture",
            "compiler_id",
            "compiler_version",
            "compiler_target",
            "png_ppi_policy",
            "created_utc",
        ):
            object.__setattr__(self, name, _require_text(getattr(self, name), name))
        # Flags and version banners may legitimately be empty, and a tool that
        # prints nothing for its version probe is a fact worth recording rather
        # than a reason to refuse the build.
        for name in (
            "cflags",
            "cppflags",
            "ldflags",
            "mindtct_version_output",
            "bozorth3_version_output",
        ):
            object.__setattr__(
                self, name, _require_text(getattr(self, name), name, allow_empty=True)
            )
        for name in ("png_support_compiled", "direct_gray8_png_verified"):
            object.__setattr__(self, name, _require_bool(getattr(self, name), name))
        object.__setattr__(
            self,
            "png_formats_refused_by_build",
            _require_text(
                self.png_formats_refused_by_build,
                "png_formats_refused_by_build",
                allow_empty=True,
            ),
        )

        dependencies: dict[str, tuple[str, ...]] = {}
        for tool, libraries in dict(self.dynamic_dependencies).items():
            name = _require_text(tool, "dynamic_dependencies key")
            if isinstance(libraries, (str, bytes)):
                raise NbisBuildManifestError(
                    f"dynamic_dependencies[{name!r}] must be a list of names"
                )
            dependencies[name] = tuple(
                sorted(
                    _require_text(item, f"dynamic_dependencies[{name!r}] entry")
                    for item in libraries
                )
            )
        object.__setattr__(
            self,
            "dynamic_dependencies",
            MappingProxyType(dict(sorted(dependencies.items()))),
        )

        if not isinstance(self.official_test_summary, NbisOfficialTestSummary):
            raise NbisBuildManifestError(
                "official_test_summary must be an NbisOfficialTestSummary"
            )

    # ------------------------------------------------------------ rendering

    def fingerprinted_content(self) -> dict[str, Any]:
        """Exactly what ``manifest_fingerprint`` is taken over."""
        payload: dict[str, Any] = {"schema": "nbis_build_manifest_fingerprint_v1"}
        for name in _FINGERPRINTED_FIELDS:
            value = getattr(self, name)
            if name == "dynamic_dependencies":
                payload[name] = {
                    tool: list(libraries) for tool, libraries in value.items()
                }
            elif name == "official_test_summary":
                payload[name] = value.as_plain()
            else:
                payload[name] = value
        return payload

    def computed_fingerprint(self) -> str:
        return stable_hash(self.fingerprinted_content(), length=64)

    def as_plain(self) -> dict[str, Any]:
        """The JSON document, in the order the spec lists the fields."""
        payload: dict[str, Any] = {}
        for name in _FINGERPRINTED_FIELDS:
            value = getattr(self, name)
            if name == "dynamic_dependencies":
                payload[name] = {
                    tool: list(libraries) for tool, libraries in value.items()
                }
            elif name == "official_test_summary":
                payload[name] = value.as_plain()
            else:
                payload[name] = value
        payload["manifest_fingerprint"] = self.manifest_fingerprint
        payload["created_utc"] = self.created_utc
        return payload

    @property
    def target(self) -> tuple[str, str]:
        return (self.target_os, self.target_architecture)

    # ---------------------------------------------------------- construction

    @classmethod
    def create(cls, **fields: Any) -> "NbisBuildManifest":
        """Build a manifest and compute its own fingerprint.

        The only supported way for the build script to produce one: passing a
        fingerprint in by hand would let a manifest be signed for content it does
        not have.
        """
        if "manifest_fingerprint" in fields:
            raise NbisBuildManifestError(
                "manifest_fingerprint is computed, never supplied"
            )
        placeholder = cls(manifest_fingerprint="0" * 64, **fields)
        digest = placeholder.computed_fingerprint()
        return cls(manifest_fingerprint=digest, **fields)

    @classmethod
    def from_plain(cls, payload: Any) -> "NbisBuildManifest":
        """Read a manifest document, refusing anything unexpected in it.

        Unknown keys are refused rather than ignored. A manifest that grew a key
        this code does not fingerprint would be a manifest whose signature covers
        less than it says.
        """
        if not isinstance(payload, Mapping):
            raise NbisBuildManifestError("a build manifest must be a JSON object")
        expected = set(_FINGERPRINTED_FIELDS) | {
            "manifest_fingerprint",
            "created_utc",
        }
        unknown = sorted(set(payload) - expected)
        if unknown:
            raise NbisBuildManifestError(f"build manifest has unknown keys: {unknown}")
        missing = sorted(expected - set(payload))
        if missing:
            raise NbisBuildManifestError(f"build manifest is missing: {missing}")

        fields = {name: payload[name] for name in expected}
        fields["official_test_summary"] = NbisOfficialTestSummary.from_plain(
            payload["official_test_summary"]
        )
        dependencies = payload["dynamic_dependencies"]
        if not isinstance(dependencies, Mapping):
            raise NbisBuildManifestError("dynamic_dependencies must be a JSON object")
        fields["dynamic_dependencies"] = {
            str(tool): tuple(libraries) for tool, libraries in dependencies.items()
        }
        return cls(**fields)


# --------------------------------------------------------------- source lock


@dataclass(frozen=True, slots=True)
class NbisArchiveLock:
    """One locked archive: where it came from and exactly which bytes it is.

    ``sha256`` and ``url`` are ``None`` until the archive has been obtained once
    and its digest recorded from the bytes themselves. Until then the lock is
    *unsealed* and nothing may be fetched or built from it — an unsealed lock is
    a promise to check, not a check (spec section 4).
    """

    version: str
    source: str
    url: str | None
    sha256: str | None
    size_bytes: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "version", _require_text(self.version, "version"))
        object.__setattr__(self, "source", _require_text(self.source, "source"))
        if self.url is not None:
            if not isinstance(self.url, str) or not self.url.strip():
                raise NbisBuildManifestError("a locked url must be a non-empty string")
            object.__setattr__(self, "url", self.url.strip())
        if self.sha256 is not None:
            object.__setattr__(self, "sha256", _require_sha256(self.sha256, "sha256"))
        object.__setattr__(
            self, "size_bytes", _require_exact_int(self.size_bytes, "size_bytes")
        )
        if self.is_sealed and self.size_bytes <= 0:
            raise NbisBuildManifestError(
                "a sealed archive lock must record a positive size"
            )

    @property
    def is_sealed(self) -> bool:
        return self.sha256 is not None and self.url is not None

    def as_plain(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "source": self.source,
            "url": self.url,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True, slots=True)
class NbisSourceLock:
    """``integrations/nbis/nbis-5.0.0.lock.json``, read strictly."""

    schema_version: str
    release: NbisArchiveLock
    tests: NbisArchiveLock

    def __post_init__(self) -> None:
        if self.schema_version != "1":
            raise NbisBuildManifestError(
                f"source lock schema_version is {self.schema_version!r}; this code "
                "reads '1'"
            )
        for name in ("release", "tests"):
            entry = getattr(self, name)
            if not isinstance(entry, NbisArchiveLock):
                raise NbisBuildManifestError(f"{name} must be an archive lock")
            if entry.version != EXPECTED_NBIS_VERSION:
                raise NbisBuildManifestError(
                    f"{name} locks version {entry.version!r}; stage 7B certifies "
                    f"{EXPECTED_NBIS_VERSION!r} only"
                )

    @property
    def is_sealed(self) -> bool:
        return self.release.is_sealed and self.tests.is_sealed

    def as_plain(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "release": self.release.as_plain(),
            "tests": self.tests.as_plain(),
        }


def read_source_lock(path: Path) -> NbisSourceLock:
    """Read the lock file, refusing unknown keys and a wrong version."""
    payload = _read_json_object(Path(path), label="source lock")
    known = {"schema_version", "release", "tests"}
    unknown = sorted(set(payload) - known)
    if unknown:
        raise NbisBuildManifestError(f"source lock has unknown keys: {unknown}")
    missing = sorted(known - set(payload))
    if missing:
        raise NbisBuildManifestError(f"source lock is missing: {missing}")

    def archive(name: str) -> NbisArchiveLock:
        entry = payload[name]
        if not isinstance(entry, Mapping):
            raise NbisBuildManifestError(f"source lock {name!r} must be an object")
        fields = {"version", "source", "url", "sha256", "size_bytes"}
        extra = sorted(set(entry) - fields)
        if extra:
            raise NbisBuildManifestError(
                f"source lock {name!r} has unknown keys: {extra}"
            )
        absent = sorted(fields - set(entry))
        if absent:
            raise NbisBuildManifestError(f"source lock {name!r} is missing: {absent}")
        return NbisArchiveLock(**{key: entry[key] for key in fields})

    return NbisSourceLock(
        schema_version=str(payload["schema_version"]),
        release=archive("release"),
        tests=archive("tests"),
    )


# ------------------------------------------------------------- fingerprints


def patchset_fingerprint(series_path: Path) -> str:
    """A digest over the patch series and the bytes of every patch it names.

    An empty series is the expected state and has a perfectly ordinary digest;
    "no patches" is a decision this project made and records, not an absence
    (spec section 7).
    """
    path = Path(series_path)
    payload = _read_json_object(path, label="patch series")
    known = {"schema_version", "patches"}
    unknown = sorted(set(payload) - known)
    if unknown:
        raise NbisBuildManifestError(f"patch series has unknown keys: {unknown}")
    if str(payload.get("schema_version")) != "1":
        raise NbisBuildManifestError(
            f"patch series schema_version is {payload.get('schema_version')!r}; "
            "this code reads '1'"
        )
    entries = payload.get("patches")
    if not isinstance(entries, list):
        raise NbisBuildManifestError("patch series 'patches' must be a list")

    rendered: list[dict[str, str]] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            raise NbisBuildManifestError(f"patch {index} must be an object")
        name = entry.get("file")
        if not isinstance(name, str) or not name.strip():
            raise NbisBuildManifestError(f"patch {index} must name a file")
        if "/" in name or "\\" in name or name in (".", ".."):
            raise NbisBuildManifestError(
                f"patch {index} must name a plain file inside patches/, got {name!r}"
            )
        patch_path = path.parent / name
        if not patch_path.is_file():
            raise NbisBuildManifestError(f"patch file {name!r} does not exist")
        digest, _size = file_digest(patch_path)
        rendered.append({"file": name, "sha256": digest})

    return stable_hash(
        {"schema": "nbis_patchset_fingerprint_v1", "patches": rendered}, length=64
    )


def build_script_fingerprint(integration_directory: Path) -> str:
    """A digest over the scripts that decide how NBIS is fetched and built.

    Changing either of them changes what a build *is*, so it changes the digest,
    so every manifest produced by the previous version stops verifying. That is
    the intended cost: a build recipe nobody can pin is a build nobody can cite.
    """
    directory = Path(integration_directory)
    rendered = []
    for name in BUILD_SCRIPT_FILES:
        path = directory / name
        if not path.is_file():
            raise NbisBuildManifestError(f"build script {name!r} is missing")
        digest, _size = file_digest(path)
        rendered.append({"file": name, "sha256": digest})
    return stable_hash(
        {"schema": "nbis_build_script_fingerprint_v1", "scripts": rendered},
        length=64,
    )


def host_target() -> tuple[str, str]:
    """This machine, spelled the way a manifest's target fields are.

    One function so that the build script, the adapter and the tests cannot
    disagree about whether ``AMD64`` and ``x86_64`` are the same machine.
    """
    import platform

    system = platform.system().lower()
    machine = platform.machine().lower()
    return (system, "x86_64" if machine in ("x86_64", "amd64") else machine)


def file_digest(path: Path) -> tuple[str, int]:
    """SHA-256 and size of a file, read in chunks."""
    digest = hashlib.sha256()
    size = 0
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


# ------------------------------------------------------------ verification


def read_build_manifest(path: Path) -> NbisBuildManifest:
    """Read and structurally validate a manifest. Does not touch the binaries."""
    return NbisBuildManifest.from_plain(
        _read_json_object(Path(path), label="build manifest")
    )


def verify_build_manifest(
    manifest: NbisBuildManifest,
    *,
    mindtct: Path,
    bozorth3: Path,
) -> None:
    """Is this manifest sound, and are these two files the ones it names?

    Everything answerable without the repository: the version, the signature,
    both executables' digests and sizes, the PNG capability claims, the official
    test result and the target platform (spec section 12).

    Raises:
        NbisBuildManifestError: any of it does not hold.
    """
    problems = list(_manifest_problems(manifest, mindtct=mindtct, bozorth3=bozorth3))
    if problems:
        raise NbisBuildManifestError(
            "the NBIS build manifest does not describe this build: "
            + "; ".join(problems)
        )


def _manifest_problems(
    manifest: NbisBuildManifest, *, mindtct: Path, bozorth3: Path
) -> Iterable[str]:
    if manifest.nbis_version != EXPECTED_NBIS_VERSION:
        yield (
            f"nbis_version is {manifest.nbis_version!r}, expected "
            f"{EXPECTED_NBIS_VERSION!r}"
        )
    if manifest.manifest_fingerprint != manifest.computed_fingerprint():
        yield "manifest_fingerprint does not cover the manifest's own content"
    if manifest.target not in SUPPORTED_TARGETS:
        yield (
            f"target {manifest.target_os}/{manifest.target_architecture} is not one "
            f"stage 7B certified ({sorted(SUPPORTED_TARGETS)})"
        )
    if not manifest.png_support_compiled:
        yield "the build reports no PNG support; there is no WSQ fallback"
    if not manifest.direct_gray8_png_verified:
        yield "direct 8-bit greyscale PNG input was never verified on this build"
    refused = {
        item.strip()
        for item in manifest.png_formats_refused_by_build.split(",")
        if item.strip()
    }
    tolerated = sorted(REQUIRED_PNG_REFUSALS - refused)
    if tolerated:
        yield (
            f"the build accepts {tolerated}; a truecolour or unreadable PNG that "
            "produced a template would mean the pixels compared were not the "
            "pixels prepared (spec section 41)"
        )
    if manifest.png_ppi_policy != EXPECTED_PNG_PPI_POLICY:
        yield (
            f"png_ppi_policy is {manifest.png_ppi_policy!r}, expected "
            f"{EXPECTED_PNG_PPI_POLICY!r}"
        )
    if not manifest.official_test_summary.is_accepted:
        summary = manifest.official_test_summary
        yield (
            "the official NIST tests were not fully passed "
            f"(discovered={summary.discovered_tests} executed={summary.executed_tests} "
            f"failed={summary.failed_tests})"
        )

    for tool, libraries in manifest.dynamic_dependencies.items():
        offenders = sorted(
            library
            for library in libraries
            if any(
                library.startswith(name) or f"/{name}" in library
                for name in FORBIDDEN_DYNAMIC_DEPENDENCIES
            )
        )
        if offenders:
            yield (
                f"{tool} loads {offenders} dynamically; the pinned bundle would not "
                "own the code that produced the score (spec section 9)"
            )

    for label, path, expected_digest, expected_size in (
        ("mindtct", mindtct, manifest.mindtct_sha256, manifest.mindtct_size_bytes),
        ("bozorth3", bozorth3, manifest.bozorth3_sha256, manifest.bozorth3_size_bytes),
    ):
        candidate = Path(path)
        if candidate.is_symlink():
            yield f"{label} is a symlink; a bundle owns its bytes"
            continue
        if not candidate.is_file():
            yield f"{label} is not a regular file"
            continue
        digest, size = file_digest(candidate)
        if size != expected_size:
            yield f"{label} is {size} bytes, the manifest says {expected_size}"
        if digest != expected_digest:
            yield f"{label} does not hash to what the manifest records"


def verify_against_source_lock(
    manifest: NbisBuildManifest, lock: NbisSourceLock
) -> None:
    """Were these binaries built from the archives this repository locked?

    Raises:
        NbisBuildManifestError: the lock is unsealed, or a digest disagrees.
    """
    if not lock.is_sealed:
        raise NbisBuildManifestError(
            "the NBIS source lock has never been sealed, so nothing can be checked "
            "against it; record the digests of the archives obtained from NIST first "
            "(integrations/nbis/README.md)"
        )
    problems: list[str] = []
    for label, locked, manifest_digest, manifest_size in (
        (
            "release",
            lock.release,
            manifest.source_archive_sha256,
            manifest.source_archive_size_bytes,
        ),
        (
            "tests",
            lock.tests,
            manifest.test_archive_sha256,
            manifest.test_archive_size_bytes,
        ),
    ):
        if locked.sha256 != manifest_digest:
            problems.append(
                f"the {label} archive digest in the manifest is not the locked one"
            )
        if locked.size_bytes != manifest_size:
            problems.append(
                f"the {label} archive size in the manifest is {manifest_size}, the "
                f"lock says {locked.size_bytes}"
            )
    if problems:
        raise NbisBuildManifestError(
            "this build did not come from the locked NBIS sources: "
            + "; ".join(problems)
        )


def verify_against_repository(
    manifest: NbisBuildManifest, *, integration_directory: Path
) -> None:
    """Was it built by this build script, with this patch series, from this lock?

    Raises:
        NbisBuildManifestError: any of the three disagrees.
    """
    directory = Path(integration_directory)
    verify_against_source_lock(manifest, read_source_lock(directory / LOCK_FILENAME))

    expected_patches = patchset_fingerprint(directory / PATCH_SERIES_RELATIVE_PATH)
    if manifest.patchset_fingerprint != expected_patches:
        raise NbisBuildManifestError(
            "the build applied a different patch series than this repository holds; "
            "a behavioural change to NBIS's C sources is never accepted silently "
            "(spec section 7)"
        )
    expected_scripts = build_script_fingerprint(directory)
    if manifest.build_script_fingerprint != expected_scripts:
        raise NbisBuildManifestError(
            "the build was produced by a different build script than this "
            "repository holds; rebuild before attributing results to it"
        )


def _read_json_object(path: Path, *, label: str) -> Mapping[str, Any]:
    candidate = Path(path)
    if candidate.is_symlink():
        raise NbisBuildManifestError(f"the {label} is a symlink; it must own its bytes")
    if not candidate.is_file():
        raise NbisBuildManifestError(f"the {label} is not a regular file")
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NbisBuildManifestError(
            f"the {label} could not be read: {type(exc).__name__}"
        ) from exc
    if not isinstance(payload, Mapping):
        raise NbisBuildManifestError(f"the {label} must be a JSON object")
    return payload
