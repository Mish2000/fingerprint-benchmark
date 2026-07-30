"""Launching the Java bridge, once per comparison.

One JVM per comparison is slow and deliberate. It buys three things that matter more
than throughput at this stage: an algorithm that cannot accumulate state between
comparisons, a crash that damages exactly one result, and a memory leak that cannot
exist. Whether to keep paying for it is a question for measurement, not for
guesswork (docs/adr/0015).

Everything about the invocation is pinned:

* ``argv`` is a list and ``shell`` is never used, so no path can be reinterpreted as
  a command;
* the environment is stripped of ``JAVA_TOOL_OPTIONS`` and friends, which would
  otherwise let an ambient variable silently change the JVM a result was produced on;
* the working directory is the job's own, so anything the JVM writes lands where the
  harness expects;
* ``subprocess.TimeoutExpired`` becomes a built-in ``TimeoutError``, which is what the
  runner already maps to ``FailureCode.TIMEOUT``.
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

from fpbench.adapters.sourceafis_java.bridge_models import (
    BridgeCompareResult,
    BridgeContractViolation,
    BridgeVersionInfo,
    build_compare_request,
    parse_compare_response,
    parse_version_response,
)
from fpbench.adapters.sourceafis_java.config import SourceAfisJavaConfig

__all__ = [
    "BridgeClient",
    "BridgeUnavailable",
    "BridgeProcessError",
    "JavaRuntime",
    "MINIMUM_JAVA_MAJOR",
]

#: Upstream SourceAFIS needs 11; this project's reference JVM is 17 and results are
#: only pinned there. Anything older is refused outright.
MINIMUM_JAVA_MAJOR = 17

#: Variables that inject JVM flags behind our back. Removed rather than trusted:
#: a run whose heap size came from an ambient variable is not reproducible.
_JVM_ENV_OVERRIDES = ("JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS")

_VERSION_TIMEOUT_SECONDS = 60.0
_JAVA_VERSION_PATTERN = re.compile(r'version "?(\d+)')


class BridgeUnavailable(Exception):
    """The bridge cannot be run here. Becomes an UNAVAILABLE environment report."""


class BridgeProcessError(Exception):
    """The bridge ran but exited non-zero: a broken request, or a bug in it."""

    def __init__(self, exit_code: int, stderr: str) -> None:
        super().__init__(f"the SourceAFIS bridge exited with {exit_code}")
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

    def __init__(self, config: SourceAfisJavaConfig) -> None:
        self._config = config

    @property
    def config(self) -> SourceAfisJavaConfig:
        return self._config

    # ----------------------------------------------------------- environment

    def resolve_java(self) -> JavaRuntime:
        """Find Java and check its major version.

        Raises:
            BridgeUnavailable: no usable Java. Not an exception the caller should
                treat as a crash — a missing dependency is a fault of the run, and
                ``validate_environment`` turns it into a report.
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
            raise BridgeUnavailable(f"java could not be started: {type(exc).__name__}")

        # `java -version` has written to stderr since forever; accept either.
        output = f"{completed.stderr}\n{completed.stdout}".strip()
        match = _JAVA_VERSION_PATTERN.search(output)
        if completed.returncode != 0 or match is None:
            raise BridgeUnavailable("java did not report a usable version")

        major = int(match.group(1))
        if major < MINIMUM_JAVA_MAJOR:
            raise BridgeUnavailable(
                f"java {major} is too old; {MINIMUM_JAVA_MAJOR} or newer is required"
            )
        return JavaRuntime(executable=executable, major=major, raw_version_output=output)

    def resolve_jar(self) -> Path:
        jar = self._config.bridge_jar
        if not jar.exists():
            raise BridgeUnavailable(
                "the SourceAFIS bridge jar has not been built; run "
                "'make sourceafis-build'"
            )
        if not jar.is_file():
            raise BridgeUnavailable("the configured bridge jar path is not a file")
        return jar

    def jar_digest(self, jar: Path) -> tuple[str, int]:
        """SHA-256 and size of the jar.

        The digest goes into the environment fingerprint, so a rebuilt or altered
        bridge produces a different run rather than quietly mixing with the old one.
        """
        digest = hashlib.sha256()
        size = 0
        with Path(jar).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
                size += len(chunk)
        return digest.hexdigest(), size

    def version(self, java: JavaRuntime, jar: Path) -> BridgeVersionInfo:
        """Ask the bridge what it is."""
        completed = self._run(
            java=java,
            jar=jar,
            command="version",
            stdin="",
            cwd=None,
            timeout=_VERSION_TIMEOUT_SECONDS,
        )
        if completed.returncode != 0:
            raise BridgeUnavailable(
                f"the bridge version command exited with {completed.returncode}"
            )
        return parse_version_response(completed.stdout)

    # -------------------------------------------------------------- compare

    def compare(
        self,
        *,
        java: JavaRuntime,
        jar: Path,
        request_id: str,
        left_path: Path,
        left_dpi: int,
        right_path: Path,
        right_dpi: int,
        working_directory: Path,
        timeout_seconds: float,
    ) -> BridgeCompareResult:
        """Run one comparison.

        Raises:
            TimeoutError: the JVM outlived its budget. Deliberately the built-in, so
                the runner records ``FailureCode.TIMEOUT`` without this module
                knowing anything about the runner.
            BridgeProcessError: non-zero exit.
            BridgeContractViolation: output the protocol forbids.
        """
        payload = build_compare_request(
            request_id=request_id,
            left_path=left_path,
            left_dpi=left_dpi,
            right_path=right_path,
            right_dpi=right_dpi,
        )
        completed = self._run(
            java=java,
            jar=jar,
            command="compare",
            stdin=payload,
            cwd=working_directory,
            timeout=timeout_seconds,
        )
        if completed.returncode != 0:
            raise BridgeProcessError(completed.returncode, completed.stderr or "")
        return parse_compare_response(
            completed.stdout,
            expected_request_id=request_id,
            expected_sourceafis_version=self._config.expected_sourceafis_version,
            expected_bridge_version=self._config.expected_bridge_version,
        )

    # -------------------------------------------------------------- internal

    def argv(self, java: JavaRuntime, jar: Path, command: str) -> list[str]:
        """The exact command line. A list, always — never a string for a shell."""
        return [str(java.executable), *self._config.jvm_args, "-jar", str(jar), command]

    def sanitised_env(self) -> dict[str, str]:
        """The child's environment, with JVM back doors closed."""
        env = dict(os.environ)
        for name in _JVM_ENV_OVERRIDES:
            env.pop(name, None)
        return env

    def _run(
        self,
        *,
        java: JavaRuntime,
        jar: Path,
        command: str,
        stdin: str,
        cwd: Path | None,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        argv: Sequence[str] = self.argv(java, jar, command)
        try:
            return subprocess.run(
                argv,
                input=stdin,
                text=True,
                capture_output=True,
                cwd=str(cwd) if cwd is not None else None,
                timeout=timeout,
                check=False,
                env=self.sanitised_env(),
                # No shell, ever: a path containing a space or a quote would
                # otherwise be reinterpreted as a command.
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError(
                f"the SourceAFIS bridge exceeded its {timeout:g}s budget"
            ) from exc

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


def is_contract_violation(exception: BaseException) -> bool:
    return isinstance(exception, BridgeContractViolation)
