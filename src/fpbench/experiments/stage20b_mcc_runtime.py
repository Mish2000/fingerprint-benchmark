"""Building the production MCC bridge, and locating what it runs against.

Stage 20A settled *which* bytes this route is defined over: one archive, one
``MccSdk.dll``, both pinned by SHA-256. This module compiles the production
bridge against that assembly, outside the working tree, and hands back the paths
the adapter needs.

**Nothing here is committed.** ``MccSdk.dll``, the official archive, the sample
minutiae and the compiled bridge all live in the local third-party store —
Stage 20A recorded ``official_artifact_cannot_be_redistributed_by_this_repository``
and that has not changed. What *is* committed is the bridge's source, the hashes,
and the tests.

The compiler is the .NET Framework 4.x ``csc`` that ships with Windows, chosen
the same way Stage 20A's probe chose it: by absolute path under ``SystemRoot``,
never off PATH. The bridge targets AnyCPU because the vendor assembly is
``ILOnly`` with no 32-bit requirement, which Stage 20A established by reading its
PE header rather than by trying it.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from fpbench.adapters.mcc.identity import MCC_SDK_DLL_SHA256
from fpbench.third_party.artifacts import resolve_third_party_root

__all__ = [
    "Stage20BRuntimeError",
    "BRIDGE_SOURCE",
    "BRIDGE_EXECUTABLE_NAME",
    "SDK_DLL_NAME",
    "SAMPLE_MINUTIAE_DIRECTORY",
    "OFFICIAL_SAMPLES",
    "Stage20BRuntime",
    "resolve_runtime",
    "build_bridge",
]

ARTIFACT_STORE_PREFIX = "unibo-mcc-sdk-v2"
PACKAGE_DIRECTORY = "MccSdk v2.0"
SDK_DLL_RELATIVE = Path("Sdk/MccSdk.dll")
SDK_DLL_NAME = "MccSdk.dll"

BRIDGE_SOURCE = Path("integrations/mcc-sdk-v2-bridge/Program.cs")
BRIDGE_DIRECTORY_NAME = "bridge"
BRIDGE_EXECUTABLE_NAME = "FpbenchMccBridge.exe"
BRIDGE_MANIFEST_NAME = "bridge-manifest.json"

SAMPLE_MINUTIAE_DIRECTORY = "SampleMinutiae"

#: The three official minutiae files Stage 20A's smoke used, in the roles it used
#: them in. Gate A drives the production bridge over exactly these.
OFFICIAL_SAMPLES: tuple[str, str, str] = ("1_1.txt", "1_2.txt", "2_1.txt")


class Stage20BRuntimeError(RuntimeError):
    """The runtime this route is defined over is absent or is not the pinned one."""


@dataclass(frozen=True, slots=True)
class Stage20BRuntime:
    """Where the vendor bytes and the compiled bridge are on this machine."""

    store: Path
    package: Path
    sdk_dll: Path
    bridge_directory: Path
    bridge: Path
    bridge_manifest: Path

    @property
    def samples(self) -> Path:
        return self.package / SAMPLE_MINUTIAE_DIRECTORY


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_runtime(*, repository_root: Path) -> Stage20BRuntime:
    """The local artifact store's MCC paths, without requiring them to exist."""
    store = Path(resolve_third_party_root(repository_root=repository_root)) / ARTIFACT_STORE_PREFIX
    package = store / "extracted" / PACKAGE_DIRECTORY
    bridge_directory = store / BRIDGE_DIRECTORY_NAME
    return Stage20BRuntime(
        store=store,
        package=package,
        sdk_dll=bridge_directory / SDK_DLL_NAME,
        bridge_directory=bridge_directory,
        bridge=bridge_directory / BRIDGE_EXECUTABLE_NAME,
        bridge_manifest=bridge_directory / BRIDGE_MANIFEST_NAME,
    )


def _framework_compiler() -> Path:
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    candidates = (
        system_root / "Microsoft.NET/Framework64/v4.0.30319/csc.exe",
        system_root / "Microsoft.NET/Framework/v4.0.30319/csc.exe",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise Stage20BRuntimeError(".NET Framework 4.x C# compiler is not installed")


def build_bridge(*, repository_root: Path) -> Stage20BRuntime:
    """Compile the production bridge beside a verified copy of the SDK.

    The assembly is copied next to the executable rather than referenced where it
    lies, because .NET resolves a dependency from the application's own directory
    and this route must never load a ``MccSdk.dll`` that happens to be somewhere
    else on the machine. Its SHA-256 is checked before the compile and the copy is
    checked after it.
    """
    runtime = resolve_runtime(repository_root=repository_root)
    source = Path(repository_root) / BRIDGE_SOURCE
    if not source.is_file():
        raise Stage20BRuntimeError(f"bridge source is absent: {BRIDGE_SOURCE.as_posix()}")

    original = runtime.package / SDK_DLL_RELATIVE
    if not original.is_file():
        raise Stage20BRuntimeError(
            "the official MCC SDK package is not extracted in the local artifact "
            "store; run the Stage 20A acquisition first"
        )
    if _sha256(original) != MCC_SDK_DLL_SHA256:
        raise Stage20BRuntimeError(
            "the extracted MccSdk.dll is not the assembly Stage 20A qualified"
        )

    runtime.bridge_directory.mkdir(parents=True, exist_ok=True)
    shutil.copy2(original, runtime.sdk_dll)
    if _sha256(runtime.sdk_dll) != MCC_SDK_DLL_SHA256:  # pragma: no cover
        raise Stage20BRuntimeError("the copied MccSdk.dll does not match Stage 20A")

    compile_run = subprocess.run(
        [
            str(_framework_compiler()),
            "/nologo",
            "/target:exe",
            "/platform:anycpu",
            "/optimize+",
            f"/reference:{runtime.sdk_dll}",
            "/reference:System.Core.dll",
            f"/out:{runtime.bridge}",
            str(source),
        ],
        cwd=str(runtime.bridge_directory),
        capture_output=True,
        text=True,
        check=False,
    )
    if compile_run.returncode != 0:
        raise Stage20BRuntimeError(f"bridge compilation failed: {compile_run.stderr.strip()}")

    # The compiled binary's digest is machine-specific — a different .NET
    # Framework servicing level produces different bytes from the same source —
    # so it cannot be pinned in the repository the way ``MccSdk.dll``'s is. It is
    # recorded here instead, beside the executable and against the *committed*
    # source it was built from, which is what lets ``validate_environment`` check
    # a digest rather than merely report one. Same shape as the NBIS build
    # manifest Algorithm 2 already relies on.
    manifest = {
        "schema": "stage_20b_mcc_bridge_manifest_v1",
        "built_utc": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "bridge_filename": BRIDGE_EXECUTABLE_NAME,
        "bridge_sha256": _sha256(runtime.bridge),
        "bridge_size_bytes": runtime.bridge.stat().st_size,
        "bridge_source": BRIDGE_SOURCE.as_posix(),
        "bridge_source_sha256": _sha256(source),
        "sdk_dll_sha256": _sha256(runtime.sdk_dll),
        "compiler": str(_framework_compiler()),
        "platform_target": "anycpu",
        "vendor_bytes_in_git": False,
    }
    runtime.bridge_manifest.write_bytes(
        (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    )
    return runtime
