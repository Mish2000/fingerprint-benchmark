"""Launching the bridge, once per comparison.

One JVM per comparison is slow and deliberate. It buys, almost for free, four
things this stage would otherwise have to argue for: no cross-comparison state,
no representation cache, no score cache, and restart determinism as the ordinary
behaviour of every job rather than a property somebody has to test for. At the
2.29 s per verify Stage 11A measured, the cost is hours against a thirty-day
licence window (spec section 3).

Everything about the invocation is pinned:

* ``argv`` is a list and ``shell`` is never used, so no path can be reinterpreted
  as a command;
* the classpath is the eight jars :mod:`fpbench.experiments.verifinger_runtime_manifest` declares, in
  its order, and not whatever ``Bin/Java`` happens to hold;
* the environment is stripped of ``JAVA_TOOL_OPTIONS`` and friends, which would
  otherwise let an ambient variable change the JVM a result was produced on;
* ``PATH`` and ``jna.library.path`` point at the pinned native directory, so the
  DLLs that load are the DLLs that were verified;
* the working directory is the job's own;
* ``subprocess.TimeoutExpired`` becomes a built-in ``TimeoutError``, which the
  runner already maps to ``FailureCode.TIMEOUT``.

**stdout is treated as shared.** A native SDK can print to it without asking, so
the response is the last line that starts with ``{`` rather than the whole
stream. Everything after that isolation is strict: the parser refuses anything
that is not exactly one valid document.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from fpbench.adapters.verifinger_java.bridge_models import (
    BridgeCompareResult,
    BridgeVersionInfo,
    build_compare_request,
    parse_compare_response,
    parse_version_response,
)
from fpbench.adapters.verifinger_java.config import VeriFingerJavaConfig
from fpbench.core.verifinger_errors import (
    VeriFingerBridgeContractViolation,
    VeriFingerRuntimeError,
)
from fpbench.adapters.verifinger_java import identity
from fpbench.adapters.verifinger_java.runtime import classpath_entries

__all__ = [
    "BridgeClient",
    "BridgeUnavailable",
    "BridgeProcessError",
    "JavaRuntime",
    "MAIN_CLASS",
]

MAIN_CLASS = "org.fpbench.verifingerbridge.VeriFingerBridge"

#: Variables that inject JVM flags behind our back. Removed rather than trusted:
#: a run whose heap size came from an ambient variable is not reproducible.
_JVM_ENV_OVERRIDES = ("JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS")

_VERSION_TIMEOUT_SECONDS = 180.0

_JAVA_VERSION_PATTERN = re.compile(r'version "?(\d+)')


class BridgeUnavailable(VeriFingerRuntimeError):
    """The bridge cannot be run here. Becomes an UNAVAILABLE environment report."""


class BridgeProcessError(VeriFingerRuntimeError):
    """The bridge ran and exited non-zero: a broken installation, or our bug."""

    def __init__(self, exit_code: int, stderr: str) -> None:
        super().__init__(f"the VeriFinger bridge exited with {exit_code}")
        self.exit_code = exit_code
        self.stderr = stderr


@dataclass(frozen=True, slots=True)
class JavaRuntime:
    """A located, version-checked Java executable."""

    executable: Path
    major: int
    raw_version_output: str


class BridgeClient:
    """Runs the two bridge commands and validates what comes back."""

    def __init__(self, config: VeriFingerJavaConfig) -> None:
        self._config = config

    @property
    def config(self) -> VeriFingerJavaConfig:
        return self._config

    # ----------------------------------------------------------- environment

    def resolve_java(self) -> JavaRuntime:
        """Find Java and check its major version.

        Raises:
            BridgeUnavailable: no usable Java. A missing dependency is a fault of
                the run, and ``validate_environment`` turns it into a report
                rather than 6,000 identical failures.
        """
        candidate = self._config.java_executable
        located = shutil.which(str(candidate))
        if located is None and Path(candidate).is_file():
            located = str(Path(candidate).resolve())
        if located is None:
            raise BridgeUnavailable(f"java executable not found: {candidate}")

        executable = Path(located)
        try:
            completed = subprocess.run(
                [str(executable), "-version"],
                capture_output=True,
                text=True,
                timeout=_VERSION_TIMEOUT_SECONDS,
                check=False,
                env=self.sanitised_env(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise BridgeUnavailable(
                f"java could not be started: {type(exc).__name__}"
            ) from exc

        output = f"{completed.stderr}\n{completed.stdout}".strip()
        match = _JAVA_VERSION_PATTERN.search(output)
        if completed.returncode != 0 or match is None:
            raise BridgeUnavailable("java did not report a usable version")
        major = int(match.group(1))
        if major < identity.MINIMUM_JAVA_MAJOR:
            raise BridgeUnavailable(
                f"java {major} is too old; {identity.MINIMUM_JAVA_MAJOR} or newer "
                "is required"
            )
        return JavaRuntime(
            executable=executable, major=major, raw_version_output=output
        )

    def resolve_jar(self) -> Path:
        jar = Path(self._config.bridge_jar)
        if not jar.exists():
            raise BridgeUnavailable(
                "the VeriFinger bridge jar has not been built; run "
                "'make verifinger-build'"
            )
        if not jar.is_file():
            raise BridgeUnavailable("the configured bridge jar path is not a file")
        if jar.is_symlink():
            raise BridgeUnavailable(
                "the bridge jar is a symlink; a runtime bundle owns its bytes "
                "rather than pointing at someone else's"
            )
        return jar

    def resolve_installation(self) -> Path:
        from fpbench.adapters.verifinger_java.config import (
            INSTALLATION_ENV_VAR,
            UNRESOLVED_INSTALLATION,
        )

        installation = Path(str(self._config.installation))
        if installation == UNRESOLVED_INSTALLATION:
            raise BridgeUnavailable(
                "no VeriFinger installation was named; pass one to the adapter "
                f"or set {INSTALLATION_ENV_VAR}. This adapter does not go "
                "looking for one"
            )
        if not installation.is_dir():
            raise BridgeUnavailable(
                "the pinned VeriFinger installation is not on this machine; "
                "acquire the SDK archive and prepare it first. Nothing in this "
                "repository downloads it"
            )
        return installation

    def file_digest(self, path: Path) -> tuple[str, int]:
        """SHA-256 and size, for the environment fingerprint."""
        digest = hashlib.sha256()
        size = 0
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
                size += len(chunk)
        return digest.hexdigest(), size

    def version(self, java: JavaRuntime, jar: Path, installation: Path) -> BridgeVersionInfo:
        """Ask the bridge what it is, and what the engine reports about itself."""
        completed = self._run(
            java=java,
            jar=jar,
            installation=installation,
            command="version",
            stdin="",
            cwd=None,
            timeout=_VERSION_TIMEOUT_SECONDS,
        )
        if completed.returncode != 0:
            raise BridgeUnavailable(
                f"the bridge version command exited with {completed.returncode}: "
                f"{(completed.stderr or '').strip()[:300]}"
            )
        return parse_version_response(self._document(completed.stdout, "version"))

    # -------------------------------------------------------------- compare

    def compare(
        self,
        *,
        java: JavaRuntime,
        jar: Path,
        installation: Path,
        request_id: str,
        left_path: Path,
        left_effective_ppi: int,
        right_path: Path,
        right_effective_ppi: int,
        working_directory: Path,
        timeout_seconds: float,
    ) -> BridgeCompareResult:
        """Run one comparison in its own JVM.

        Raises:
            TimeoutError: the JVM outlived its budget. Deliberately the built-in,
                so the runner records ``FailureCode.TIMEOUT`` without this module
                knowing anything about the runner.
            BridgeProcessError: non-zero exit.
            VeriFingerBridgeContractViolation: output the protocol forbids.
        """
        payload = build_compare_request(
            request_id=request_id,
            left_path=left_path,
            left_effective_ppi=left_effective_ppi,
            right_path=right_path,
            right_effective_ppi=right_effective_ppi,
        )
        completed = self._run(
            java=java,
            jar=jar,
            installation=installation,
            command="compare",
            stdin=payload,
            cwd=working_directory,
            timeout=timeout_seconds,
        )
        if completed.returncode != 0:
            raise BridgeProcessError(completed.returncode, completed.stderr or "")
        return parse_compare_response(
            self._document(completed.stdout, "compare"),
            expected_request_id=request_id,
        )

    # -------------------------------------------------------------- internal

    def argv(
        self, java: JavaRuntime, jar: Path, installation: Path, command: str
    ) -> list[str]:
        """The exact command line. A list, always — never a string for a shell."""
        native = Path(installation) / identity.PLATFORM_NATIVE_DIRECTORY
        classpath = os.pathsep.join(
            [str(jar), *(str(entry) for entry in classpath_entries(installation))]
        )
        return [
            str(java.executable),
            *self._config.jvm_args,
            f"-Djna.library.path={native}",
            "-cp",
            classpath,
            MAIN_CLASS,
            command,
        ]

    def sanitised_env(self, installation: Path | None = None) -> dict[str, str]:
        """The child's environment, with JVM back doors closed.

        When an installation is given, its native directory goes on the front of
        ``PATH`` so that the DLLs the engine loads are the ones this run pinned
        and verified, rather than any copy that happens to be installed
        system-wide.
        """
        env = {
            key: value
            for key, value in os.environ.items()
            if key not in _JVM_ENV_OVERRIDES
        }
        if installation is not None:
            native = Path(installation) / identity.PLATFORM_NATIVE_DIRECTORY
            env["PATH"] = str(native) + os.pathsep + env.get("PATH", "")
            env["JNA_LIBRARY_PATH"] = str(native)
        return env

    def _run(
        self,
        *,
        java: JavaRuntime,
        jar: Path,
        installation: Path,
        command: str,
        stdin: str,
        cwd: Path | None,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        argv: Sequence[str] = self.argv(java, jar, installation, command)
        try:
            return subprocess.run(
                argv,
                input=stdin,
                text=True,
                capture_output=True,
                cwd=str(cwd) if cwd is not None else str(installation),
                timeout=timeout,
                check=False,
                env=self.sanitised_env(installation),
                # No shell, ever: a path containing a space or a quote would
                # otherwise be reinterpreted as a command.
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError(
                f"the VeriFinger bridge exceeded its {timeout:g}s budget"
            ) from exc

    @staticmethod
    def _document(stdout: str, what: str) -> str:
        """Isolate the one JSON object the bridge printed.

        The native libraries share this process's stdout and may write to it. The
        response is the last line starting with ``{``; if there is none, that is
        a contract violation rather than something to recover from.
        """
        for line in reversed((stdout or "").splitlines()):
            if line.startswith("{"):
                return line
        raise VeriFingerBridgeContractViolation(
            f"{what}: the bridge printed no JSON document"
        )

    def runtime_description(
        self, java: JavaRuntime, version: BridgeVersionInfo
    ) -> Mapping[str, str]:
        """The runtime facts that belong in the environment fingerprint."""
        return {
            "java.version": version.java_version or str(java.major),
            "java.vendor": version.java_vendor,
            "java.vm.name": version.java_vm_name,
            "os.name": version.os_name,
            "os.arch": version.os_arch,
        }
