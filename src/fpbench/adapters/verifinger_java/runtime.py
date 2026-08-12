"""Everything executable or data that can affect this route, pinned.

Stage 11A pinned five native libraries, two model data files and three jars.
That was enough to identify the artifact and not enough to identify the *run*:
the engine reports **seven** loaded modules, and the qualification put every jar
in ``Bin/Java`` on the classpath. Two DLLs and several jars could therefore have
changed underneath a result without anything noticing. Stage 11B closes that
(spec section 16).

The closure is the whole of it:

.. code-block:: text

    7 native libraries   every module the engine reports as loaded
    2 model data files   Fingers.ndf and FingersMatching.ndf
    8 jars               exactly the classpath the bridge is launched with

and for each: a path relative to the installation, a size, a SHA-256 and — for
the native libraries — the version the binary itself declares.

**Provenance, not just integrity.** A digest proves a file has not changed; it
does not prove where the file came from. So every component is also read back
out of the pinned SDK archive and compared, which is what turns "these bytes are
stable" into "these bytes are the vendor's" (spec section 16).

**Three checks, at three costs.** The full digest pass runs before a run starts
and again after it stops. In between, every comparison does a ``stat``-cheap
identity check, exactly as the SourceAFIS adapter does for its one jar — because
hashing 32 MB of DLL before each of 6,000 comparisons would add an hour to a run
for no new information (docs/adr/0018, spec section 19).

**No vendor byte enters this repository.** What is committed is a manifest of
digests, sizes and archive-relative paths. The 4.7 GB it describes stays in the
local artifact store (spec section 38).

This module is part of the adapter and therefore imports only ``fpbench.core``
and its own package. The operator command that *derives* the committed manifest
needs the local artifact store, which is a layer above an adapter, so it lives in
:mod:`fpbench.experiments.verifinger_runtime_manifest` instead
(tests/unit/test_import_boundaries.py).
"""

from __future__ import annotations

import hashlib
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping

from fpbench.core.serialization import read_json, stable_hash
from fpbench.core.verifinger_errors import VeriFingerRuntimeClosureError
from fpbench.adapters.verifinger_java.identity import PLATFORM_NATIVE_DIRECTORY

__all__ = [
    "ARCHIVE_ROOT",
    "NATIVE_LIBRARY_NAMES",
    "MODEL_DATA_FILES",
    "CLASSPATH_JARS",
    "CLOSURE_PATHS",
    "MANIFEST_SCHEMA",
    "RuntimeComponent",
    "RuntimeManifest",
    "read_runtime_manifest",
    "build_runtime_manifest",
    "verify_installation",
    "verify_against_archive",
    "classpath_entries",
    "native_library_directory",
    "RuntimeIdentitySnapshot",
    "snapshot_runtime_identity",
    "require_runtime_unchanged",
]

#: The one directory prefix every path inside the pinned archive carries.
ARCHIVE_ROOT = "Neurotec_Biometric_2025_2_SDK/"

MANIFEST_SCHEMA = "verifinger_runtime_manifest_v1"

#: Every native module ``NModule.getLoadedModules()`` reports for this route.
#: Seven, not the five Stage 11A pinned: ``NMediaProc`` and ``NDevices`` are
#: loaded by the engine and were the last unpinned bytes on the route
#: (spec section 16).
NATIVE_LIBRARY_NAMES: tuple[str, ...] = (
    "NBiometricClient.dll",
    "NBiometrics.dll",
    "NCore.dll",
    "NDevices.dll",
    "NLicensing.dll",
    "NMedia.dll",
    "NMediaProc.dll",
)

#: The algorithm's own data. Withholding ``Fingers.ndf`` is what Stage 11A used
#: as the controlled cause for the missing-component failure class, so these are
#: unambiguously part of what produces a score.
MODEL_DATA_FILES: tuple[str, ...] = (
    "Bin/Data/Fingers.ndf",
    "Bin/Data/FingersMatching.ndf",
)

#: Exactly what goes on ``-cp``, in this order, and nothing else. The
#: qualification harness globbed the whole ``Bin/Java`` directory, which put a
#: MySQL driver and a Swing look-and-feel on the classpath of a fingerprint
#: comparison. A production route names its dependencies (spec section 16).
CLASSPATH_JARS: tuple[str, ...] = (
    "Bin/Java/neurotec-biometrics-client.jar",
    "Bin/Java/neurotec-biometrics.jar",
    "Bin/Java/neurotec-core.jar",
    "Bin/Java/neurotec-devices.jar",
    "Bin/Java/neurotec-licensing.jar",
    "Bin/Java/neurotec-media.jar",
    "Bin/Java/neurotec-media-processing.jar",
    "Bin/Java/jna.jar",
)


def native_library_directory() -> str:
    """``Bin/Win64_x64``, as a path relative to the installation root."""
    return PLATFORM_NATIVE_DIRECTORY


#: Every component of the closure, as a path relative to the installation root,
#: sorted. Sorted rather than grouped because this tuple is what the manifest is
#: keyed by, and a stable order makes the fingerprint stable.
CLOSURE_PATHS: tuple[str, ...] = tuple(
    sorted(
        [
            *(f"{PLATFORM_NATIVE_DIRECTORY}/{name}" for name in NATIVE_LIBRARY_NAMES),
            *MODEL_DATA_FILES,
            *CLASSPATH_JARS,
        ]
    )
)


# ------------------------------------------------------------------ the model


@dataclass(frozen=True, slots=True)
class RuntimeComponent:
    """One file the route loads, and how it is recognised.

    ``relative_path`` is relative to the installation root and therefore to the
    archive root as well, which is what lets the same string identify the file
    on disk and the member inside the pinned archive. It is never an absolute
    path: a published component that named ``C:\\Users\\...`` would be
    describing one computer rather than one runtime (spec section 39).
    """

    role: str
    relative_path: str
    size_bytes: int
    sha256: str
    declared_version: str | None = None

    def __post_init__(self) -> None:
        path = str(self.relative_path).replace("\\", "/").strip()
        if not path or PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts:
            raise VeriFingerRuntimeClosureError(
                f"{self.role}: a runtime component is named by a relative path "
                f"inside the installation, not {path!r}"
            )
        object.__setattr__(self, "relative_path", path)
        digest = str(self.sha256).strip().lower()
        if len(digest) != 64 or set(digest) - set("0123456789abcdef"):
            raise VeriFingerRuntimeClosureError(
                f"{self.role}: sha256 must be a 64-character hexadecimal digest"
            )
        object.__setattr__(self, "sha256", digest)
        if int(self.size_bytes) <= 0:
            raise VeriFingerRuntimeClosureError(f"{self.role}: size must be positive")
        object.__setattr__(self, "size_bytes", int(self.size_bytes))

    @property
    def archive_member(self) -> str:
        """Where the same bytes live inside the pinned SDK archive."""
        return f"{ARCHIVE_ROOT}{self.relative_path}"

    def as_document(self) -> dict[str, Any]:
        document: dict[str, Any] = {
            "role": self.role,
            "relative_path": self.relative_path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }
        if self.declared_version is not None:
            document["declared_version"] = self.declared_version
        return document


@dataclass(frozen=True, slots=True)
class RuntimeManifest:
    """The whole closure, and one digest over it.

    The digest is what an experiment configuration pins and what a stored result
    carries, so a run whose DLLs were swapped between two machines cannot share
    an identity with one whose were not.
    """

    components: tuple[RuntimeComponent, ...]
    sdk_archive_sha256: str
    platform: str

    def __post_init__(self) -> None:
        components = tuple(
            sorted(self.components, key=lambda item: item.relative_path)
        )
        paths = [item.relative_path for item in components]
        if len(set(paths)) != len(paths):
            raise VeriFingerRuntimeClosureError(
                "the runtime manifest names the same file twice"
            )
        if tuple(paths) != CLOSURE_PATHS:
            missing = sorted(set(CLOSURE_PATHS) - set(paths))
            extra = sorted(set(paths) - set(CLOSURE_PATHS))
            raise VeriFingerRuntimeClosureError(
                "the runtime manifest is not this route's closure: "
                f"missing={missing} unexpected={extra}"
            )
        object.__setattr__(self, "components", components)

    @property
    def by_path(self) -> Mapping[str, RuntimeComponent]:
        return MappingProxyType({item.relative_path: item for item in self.components})

    @property
    def fingerprint(self) -> str:
        return stable_hash(self.as_document(), length=64)

    def as_document(self) -> dict[str, Any]:
        return {
            "schema": MANIFEST_SCHEMA,
            "platform": self.platform,
            "sdk_archive_sha256": self.sdk_archive_sha256,
            "native_library_directory": native_library_directory(),
            "classpath": list(CLASSPATH_JARS),
            "components": [item.as_document() for item in self.components],
        }


# ------------------------------------------------------------------ reading


def read_runtime_manifest(path: Path) -> RuntimeManifest:
    """Load the committed manifest.

    Raises:
        VeriFingerRuntimeClosureError: the document is absent, is not this
            schema, or does not describe this route's closure.
    """
    location = Path(path)
    if not location.is_file():
        raise VeriFingerRuntimeClosureError(
            f"the VeriFinger runtime manifest is missing: {location.name}"
        )
    document = read_json(location)
    if str(document.get("schema")) != MANIFEST_SCHEMA:
        raise VeriFingerRuntimeClosureError(
            f"{location.name} is not a {MANIFEST_SCHEMA} document"
        )
    declared_classpath = tuple(str(item) for item in document.get("classpath") or ())
    if declared_classpath != CLASSPATH_JARS:
        raise VeriFingerRuntimeClosureError(
            f"{location.name} declares a classpath this source does not build: "
            f"{list(declared_classpath)}"
        )
    components = tuple(
        RuntimeComponent(
            role=str(row["role"]),
            relative_path=str(row["relative_path"]),
            size_bytes=int(row["size_bytes"]),
            sha256=str(row["sha256"]),
            declared_version=(
                str(row["declared_version"]) if row.get("declared_version") else None
            ),
        )
        for row in document.get("components") or ()
    )
    return RuntimeManifest(
        components=components,
        sdk_archive_sha256=str(document["sdk_archive_sha256"]),
        platform=str(document["platform"]),
    )


# ------------------------------------------------------------------ building


def build_runtime_manifest(
    installation: Path, *, sdk_archive_sha256: str, platform: str
) -> RuntimeManifest:
    """Hash every component of the closure as it exists on disk.

    Used once, by ``python -m fpbench.experiments.verifinger_runtime_manifest``, to produce the
    document that is then committed and never regenerated silently. Everything
    afterwards *verifies* against it.
    """
    root = Path(installation)
    components: list[RuntimeComponent] = []
    for relative in CLOSURE_PATHS:
        target = root / Path(relative)
        if not target.is_file():
            raise VeriFingerRuntimeClosureError(
                f"the installation is missing {relative}, which this route loads"
            )
        digest, size = _digest_of(target)
        components.append(
            RuntimeComponent(
                role=_role_of(relative),
                relative_path=relative,
                size_bytes=size,
                sha256=digest,
                declared_version=None,
            )
        )
    return RuntimeManifest(
        components=tuple(components),
        sdk_archive_sha256=str(sdk_archive_sha256).strip().lower(),
        platform=platform,
    )


def _role_of(relative: str) -> str:
    if relative.endswith(".dll"):
        return "native_library"
    if relative.endswith(".ndf"):
        return "model_data_file"
    if relative.endswith(".jar"):
        return "classpath_jar"
    raise VeriFingerRuntimeClosureError(  # pragma: no cover - the closure is fixed
        f"{relative} has no role on this route"
    )


# ------------------------------------------------------------- verification


def verify_installation(
    installation: Path, manifest: RuntimeManifest
) -> Mapping[str, str]:
    """Re-hash every component and compare it with the manifest.

    The expensive pass. Run before a run starts and again after it stops.

    Returns:
        Every verified component's digest, keyed by relative path.

    Raises:
        VeriFingerRuntimeClosureError: a component is absent, is the wrong size,
            or hashes to something else.
    """
    root = Path(installation)
    verified: dict[str, str] = {}
    for component in manifest.components:
        target = root / Path(component.relative_path)
        if not target.is_file():
            raise VeriFingerRuntimeClosureError(
                f"{component.relative_path} is not present in the installation; "
                "this route loads it"
            )
        if target.is_symlink():
            raise VeriFingerRuntimeClosureError(
                f"{component.relative_path} is a symlink; a pinned runtime owns "
                "its bytes rather than pointing at someone else's"
            )
        digest, size = _digest_of(target)
        if size != component.size_bytes or digest != component.sha256:
            raise VeriFingerRuntimeClosureError(
                f"{component.relative_path} is not the bytes this run is pinned "
                f"to: found {digest[:12]}... ({size} bytes), expected "
                f"{component.sha256[:12]}... ({component.size_bytes} bytes)"
            )
        verified[component.relative_path] = digest
    return MappingProxyType(verified)


def verify_against_archive(
    archive: Path, manifest: RuntimeManifest
) -> Mapping[str, str]:
    """Prove every component came out of the pinned SDK archive.

    The other half of the closure claim. ``verify_installation`` says the files
    have not changed; this says they are the vendor's, by reading the same
    member out of the archive whose own digest Stage 11A froze.

    Raises:
        VeriFingerRuntimeClosureError: the archive is absent, is missing a
            member, or holds different bytes under that name.
    """
    location = Path(archive)
    if not location.is_file():
        raise VeriFingerRuntimeClosureError(
            "the pinned SDK archive is not in the local store, so no component "
            "can be shown to have come from it"
        )
    proved: dict[str, str] = {}
    with zipfile.ZipFile(location) as handle:
        names = set(handle.namelist())
        for component in manifest.components:
            member = component.archive_member
            if member not in names:
                raise VeriFingerRuntimeClosureError(
                    f"the pinned archive holds no {component.relative_path}"
                )
            digest = hashlib.sha256()
            size = 0
            with handle.open(member) as stream:
                for block in iter(lambda: stream.read(1 << 20), b""):
                    digest.update(block)
                    size += len(block)
            found = digest.hexdigest()
            if found != component.sha256 or size != component.size_bytes:
                raise VeriFingerRuntimeClosureError(
                    f"{component.relative_path} in the pinned archive hashes to "
                    f"{found[:12]}..., and this run is pinned to "
                    f"{component.sha256[:12]}..."
                )
            proved[component.relative_path] = found
    return MappingProxyType(proved)


def classpath_entries(installation: Path) -> tuple[Path, ...]:
    """The ``-cp`` entries, in the declared order, as absolute paths.

    Order is part of the runtime's identity: two classpaths holding the same
    jars in different orders can resolve a duplicated class differently, and a
    route that produced results under one must not silently run under the other.
    """
    root = Path(installation)
    return tuple((root / Path(relative)).resolve() for relative in CLASSPATH_JARS)


# ---------------------------------------------------------------- the guard


@dataclass(frozen=True, slots=True)
class RuntimeIdentitySnapshot:
    """What ``stat`` says about every component, taken once at preflight.

    Compared before every comparison. One ``stat`` per file against 32 MB of
    hashing is the difference between a guard that runs and a guard somebody
    turns off (docs/adr/0018).
    """

    identities: Mapping[str, tuple[int, int, int, int]]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "identities", MappingProxyType(dict(sorted(self.identities.items())))
        )


def snapshot_runtime_identity(
    installation: Path, manifest: RuntimeManifest
) -> RuntimeIdentitySnapshot:
    """Record what each component is now, so a later call can tell it changed."""
    root = Path(installation)
    return RuntimeIdentitySnapshot(
        identities={
            component.relative_path: _identity_of(root / Path(component.relative_path))
            for component in manifest.components
        }
    )


def require_runtime_unchanged(
    installation: Path, snapshot: RuntimeIdentitySnapshot
) -> None:
    """Confirm no component has been replaced since preflight.

    Raises:
        RuntimeDriftError: one has. Fatal to the run, never a stored comparison
            failure: a result written after a DLL changed would claim provenance
            it does not have (spec section 19).
    """
    from fpbench.core.errors import RuntimeDriftError

    root = Path(installation)
    for relative, expected in snapshot.identities.items():
        try:
            current = _identity_of(root / Path(relative))
        except VeriFingerRuntimeClosureError as exc:
            raise RuntimeDriftError(
                f"the pinned VeriFinger runtime lost {relative} while the run was "
                f"using it: {exc}"
            ) from exc
        if current != expected:
            raise RuntimeDriftError(
                f"the pinned VeriFinger runtime component {relative} changed while "
                "the run was using it; no further comparison may be attributed to "
                "this run (docs/adr/0018)"
            )


def _identity_of(path: Path) -> tuple[int, int, int, int]:
    target = Path(path)
    if target.is_symlink():
        raise VeriFingerRuntimeClosureError(
            f"{target.name} is now a symlink; a pinned runtime owns its bytes"
        )
    if not target.is_file():
        raise VeriFingerRuntimeClosureError(f"{target.name} is no longer a regular file")
    status = target.stat()
    return (
        int(getattr(status, "st_dev", 0) or 0),
        int(getattr(status, "st_ino", 0) or 0),
        int(status.st_size),
        int(status.st_mtime_ns),
    )


def _digest_of(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size
