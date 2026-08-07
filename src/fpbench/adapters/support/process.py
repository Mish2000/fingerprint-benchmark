"""Running an external tool once, without the six mistakes everybody makes.

Every command-line matcher needs the same things: a timeout that actually kills
the process, output that cannot exhaust memory, an environment that does not vary
with whoever's shell started the run, and an exit code reported rather than
interpreted. Writing that again per adapter is how one adapter ends up leaking
zombie processes and another ends up hiding a crash.

The rules, and why each one:

**No shell.** ``argv`` is a tuple and it is passed as a tuple. There is no string
form and no ``shell=True`` — not as a convenience, not behind a flag. A shell
would make the command depend on quoting rules that differ between platforms,
and a file name is not a place to discover that.

**An absolute executable.** A bare ``mindtct`` means "whatever is first on this
machine's PATH", which is exactly the thing a pinned runtime bundle exists to
stop being true. Callers that need PATH resolution do it themselves, in the open,
before building the command.

**Bounded output.** stdout and stderr go to temporary files and only the first
``stdout_limit_bytes``/``stderr_limit_bytes`` are ever read into memory. A tool
that prints a hundred megabytes of debug produces a truncated string and a flag
that says so, not a crash and not a run whose result rows are each a megabyte.

**A timeout that ends the process.** Terminate, wait a short fixed grace, kill,
wait again. The result is returned only once the child is actually gone, because
a "timed out" result while the process is still holding a file open is not a
result, it is a race.

**A named environment.** ``LANG=C``, ``LC_ALL=C``, ``TZ=UTC`` and nothing else,
apart from a small, explicitly listed platform floor that Windows needs to start
a process at all. ``os.environ`` is never passed through: a tool that behaves
differently because a developer exports ``OMP_NUM_THREADS`` produces scores that
cannot be reproduced from the receipt.

What this module deliberately does **not** do is decide what an exit code means.
``exit_code=2`` might be "no minutiae found" for one tool and "bad arguments" for
another. Translating it is the adapter's job, in its own ``failure_mapping``
module, where the table can be read (spec section 75).
"""

from __future__ import annotations

import math
import os
import signal
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic, perf_counter_ns, sleep
from types import MappingProxyType
from typing import Mapping

from fpbench.core.errors import ConfigurationError, ProcessTreeTerminationError

__all__ = [
    "ExternalCommand",
    "ExternalCommandResult",
    "ProcessTreeTerminationError",
    "run_external_command",
    "DETERMINISTIC_ENVIRONMENT",
    "PLATFORM_ENVIRONMENT_FLOOR",
    "TERMINATE_GRACE_SECONDS",
]

_NS_PER_MS = 1_000_000

#: The locale and clock every external tool is run under, so that a tool which
#: formats a number differently in another locale cannot change a score.
DETERMINISTIC_ENVIRONMENT: Mapping[str, str] = MappingProxyType(
    {"LANG": "C", "LC_ALL": "C", "TZ": "UTC"}
)

#: Named, not inherited. Windows cannot start a process without ``SystemRoot``,
#: so these four are read from the ambient environment when they exist — and
#: they are listed here so that "which variables reach the tool" is answerable by
#: reading this file rather than by reading a developer's shell profile.
PLATFORM_ENVIRONMENT_FLOOR: tuple[str, ...] = (
    ("SystemRoot", "windir", "COMSPEC", "PATHEXT") if sys.platform == "win32" else ()
)

#: How long a terminated process is given to exit before it is killed. Fixed,
#: because a configurable grace period is a knob nobody would ever tune.
TERMINATE_GRACE_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class ExternalCommand:
    """One invocation of one external tool."""

    argv: tuple[str, ...]
    working_directory: Path
    timeout_seconds: float

    environment: Mapping[str, str] = field(default_factory=dict)

    stdout_limit_bytes: int = 1_048_576
    stderr_limit_bytes: int = 1_048_576

    #: When set, ``working_directory`` must be inside it. Adapters pass the job's
    #: working directory, so a command cannot be launched from somewhere the job
    #: was never given (spec section 38).
    containment_root: Path | None = None

    def __post_init__(self) -> None:
        argv = tuple(str(item) for item in self.argv)
        if not argv:
            raise ConfigurationError("an external command needs an argv")
        if any(not item for item in argv):
            raise ConfigurationError("an external command argument must not be empty")
        executable = Path(argv[0])
        if not executable.is_absolute():
            raise ConfigurationError(
                f"the executable must be an absolute path, got {argv[0]!r}; a bare "
                "command name means whatever this machine's PATH happens to say"
            )
        object.__setattr__(self, "argv", argv)

        working = Path(self.working_directory)
        if not working.is_absolute():
            raise ConfigurationError(
                f"working_directory must be absolute, got {working}"
            )
        working = working.resolve()
        object.__setattr__(self, "working_directory", working)

        if self.containment_root is not None:
            root = Path(self.containment_root).resolve()
            object.__setattr__(self, "containment_root", root)
            if not working.is_relative_to(root):
                raise ConfigurationError(
                    "working_directory must be inside the directory this job was "
                    "given; a tool may not be launched from elsewhere"
                )

        if type(self.timeout_seconds) not in (int, float):
            raise ConfigurationError(
                "timeout_seconds must be a number, got "
                f"{type(self.timeout_seconds).__name__}"
            )
        timeout = float(self.timeout_seconds)
        if not math.isfinite(timeout) or timeout <= 0:
            raise ConfigurationError(
                f"timeout_seconds must be finite and positive, got {timeout!r}"
            )
        object.__setattr__(self, "timeout_seconds", timeout)

        for name in ("stdout_limit_bytes", "stderr_limit_bytes"):
            value = getattr(self, name)
            if type(value) is not int:
                raise ConfigurationError(
                    f"{name} must be an exact integer, got {type(value).__name__}"
                )
            if value <= 0:
                raise ConfigurationError(f"{name} must be positive, got {value}")

        environment: dict[str, str] = {}
        for key, value in dict(self.environment).items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise ConfigurationError(
                    "environment names and values must both be strings, got "
                    f"{type(key).__name__} -> {type(value).__name__}"
                )
            if not key.strip():
                raise ConfigurationError("an environment variable needs a name")
            environment[key] = value
        object.__setattr__(self, "environment", MappingProxyType(environment))

    @property
    def executable(self) -> Path:
        return Path(self.argv[0])

    def resolved_environment(self) -> Mapping[str, str]:
        """Exactly what the child process will see.

        Deterministic base, then the platform floor, then whatever the adapter
        declared. An adapter may override ``TZ`` if it has a reason; it cannot
        pull in the whole ambient environment by accident, because there is no
        code path here that reads it.
        """
        resolved = dict(DETERMINISTIC_ENVIRONMENT)
        for name in PLATFORM_ENVIRONMENT_FLOOR:
            value = os.environ.get(name)
            if value is not None:
                resolved[name] = value
        resolved.update(self.environment)
        return MappingProxyType(resolved)


@dataclass(frozen=True, slots=True)
class ExternalCommandResult:
    """What the tool did. Not what it meant.

    ``exit_code`` is ``None`` when there was no exit code to have: the process
    could not be started, or it was killed after a timeout on a platform that
    reports no status for it. The three flags are separate rather than folded
    into one enum because an adapter maps them to different failure codes and
    different stages (spec section 58).
    """

    exit_code: int | None
    timed_out: bool
    launch_failed: bool

    stdout: str
    stderr: str

    stdout_truncated: bool
    stderr_truncated: bool

    duration_ms: float

    @property
    def succeeded(self) -> bool:
        """Exit status zero, started, and not killed. Says nothing about output."""
        return (
            not self.launch_failed and not self.timed_out and self.exit_code == 0
        )


def run_external_command(command: ExternalCommand) -> ExternalCommandResult:
    """Run ``command`` to completion, a timeout, or a failure to start.

    Never raises for an ordinary tool failure — a non-zero exit, a crash, a
    timeout and a missing executable are all returned as results, because each of
    them is something the adapter has to map into the failure taxonomy rather
    than something that should end a 6,000-comparison run.
    """
    started = perf_counter_ns()
    directory = command.working_directory
    environment = dict(command.resolved_environment())

    # Temporary files rather than pipes: the output is bounded when it is read,
    # not after a pipe has already buffered it all into this process, and there
    # is no reader thread to deadlock. Both are deleted when closed.
    with tempfile.TemporaryFile(dir=directory) as out_file, tempfile.TemporaryFile(
        dir=directory
    ) as err_file:
        windows_job = _create_windows_job() if sys.platform == "win32" else None
        try:
            process = subprocess.Popen(  # noqa: S603 - argv list, shell=False
                list(command.argv),
                cwd=str(directory),
                stdin=subprocess.DEVNULL,
                stdout=out_file,
                stderr=err_file,
                env=environment,
                shell=False,
                close_fds=True,
                start_new_session=sys.platform != "win32",
            )
        except (OSError, ValueError) as exc:
            _close_windows_job(windows_job)
            return ExternalCommandResult(
                exit_code=None,
                timed_out=False,
                launch_failed=True,
                stdout="",
                # Safe to publish: the exception type and the executable's bare
                # name, never the path and never a traceback.
                stderr=(
                    f"{type(exc).__name__}: could not start "
                    f"{command.executable.name}"
                ),
                stdout_truncated=False,
                stderr_truncated=False,
                duration_ms=(perf_counter_ns() - started) / _NS_PER_MS,
            )

        # A tiny tool can finish between CreateProcess and job assignment. Avoid
        # asking Windows to assign a process that is already known to be done;
        # _assign_windows_job repeats this check if the process exits during the
        # assignment call itself.
        if windows_job is not None and process.poll() is None:
            _assign_windows_job(windows_job, process)

        timed_out = False
        try:
            exit_code: int | None = process.wait(timeout=command.timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            exit_code = _end_process_tree(process, windows_job)
        finally:
            _close_windows_job(windows_job)

        stdout, stdout_truncated = _read_capped(out_file, command.stdout_limit_bytes)
        stderr, stderr_truncated = _read_capped(err_file, command.stderr_limit_bytes)

    return ExternalCommandResult(
        exit_code=exit_code,
        timed_out=timed_out,
        launch_failed=False,
        stdout=stdout,
        stderr=stderr,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
        duration_ms=(perf_counter_ns() - started) / _NS_PER_MS,
    )


def _end_process_tree(
    process: "subprocess.Popen[bytes]", windows_job: int | None
) -> int | None:
    """End the complete process tree and return only after proving it is gone."""
    if sys.platform == "win32":
        tree_terminated = _terminate_windows_process_tree(process.pid)
        job_terminated = (
            windows_job is not None and _terminate_windows_job(windows_job)
        )
        if not tree_terminated or not job_terminated:
            raise ProcessTreeTerminationError(
                "could not prove termination of the timed-out Windows process tree"
            )
        try:
            return process.wait(timeout=TERMINATE_GRACE_SECONDS)
        except subprocess.TimeoutExpired as exc:  # pragma: no cover - OS failure
            raise ProcessTreeTerminationError(
                "the Windows job was terminated but its root process stayed alive"
            ) from exc

    process_group = process.pid
    _signal_process_group(process_group, signal.SIGTERM)
    deadline = monotonic() + TERMINATE_GRACE_SECONDS
    while monotonic() < deadline and _process_group_exists(process_group):
        process.poll()
        sleep(0.02)
    if _process_group_exists(process_group):
        _signal_process_group(process_group, signal.SIGKILL)
        deadline = monotonic() + TERMINATE_GRACE_SECONDS
        while monotonic() < deadline and _process_group_exists(process_group):
            process.poll()
            sleep(0.02)
    try:
        exit_code = process.wait(timeout=TERMINATE_GRACE_SECONDS)
    except subprocess.TimeoutExpired as exc:  # pragma: no cover - OS failure
        raise ProcessTreeTerminationError(
            "the process group was killed but its root process stayed alive"
        ) from exc
    if _process_group_exists(process_group):  # pragma: no cover - OS failure
        raise ProcessTreeTerminationError(
            "the timed-out process group still exists after forced termination"
        )
    return exit_code


def _signal_process_group(process_group: int, requested_signal: int) -> None:
    try:
        os.killpg(process_group, requested_signal)
    except ProcessLookupError:
        return
    except OSError as exc:  # pragma: no cover - OS failure
        raise ProcessTreeTerminationError(
            f"could not signal timed-out process group {process_group}"
        ) from exc


def _process_group_exists(process_group: int) -> bool:
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    except PermissionError as exc:  # pragma: no cover - OS failure
        raise ProcessTreeTerminationError(
            f"cannot verify timed-out process group {process_group}"
        ) from exc
    return True


def _create_windows_job() -> int | None:
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    class _BasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
        )]

    class _ExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BasicLimitInformation),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.CreateJobObjectW(None, None)
    if not handle:
        raise ProcessTreeTerminationError("could not create a Windows process job")
    information = _ExtendedLimitInformation()
    information.BasicLimitInformation.LimitFlags = 0x00002000
    if not kernel32.SetInformationJobObject(
        handle, 9, ctypes.byref(information), ctypes.sizeof(information)
    ):
        kernel32.CloseHandle(handle)
        raise ProcessTreeTerminationError(
            "could not configure a Windows process job for tree termination"
        )
    return int(handle)


def _assign_windows_job(
    job: int, process: "subprocess.Popen[bytes]"
) -> None:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    if not kernel32.AssignProcessToJobObject(
        wintypes.HANDLE(job), wintypes.HANDLE(int(process._handle))  # type: ignore[attr-defined]
    ):
        # AssignProcessToJobObject fails once a very short-lived process has
        # already exited. That is a successful command result, not a process-tree
        # containment failure, and killing/raising here would discard it.
        if process.poll() is not None:
            return
        process.kill()
        process.wait(timeout=TERMINATE_GRACE_SECONDS)
        _close_windows_job(job)
        raise ProcessTreeTerminationError(
            "could not place the external tool in its Windows process job"
        )


def _terminate_windows_job(job: int) -> bool:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateJobObject.restype = wintypes.BOOL
    return bool(kernel32.TerminateJobObject(wintypes.HANDLE(job), 1))


def _terminate_windows_process_tree(process_id: int) -> bool:
    """Use Windows' own descendant walk in addition to the assigned Job Object.

    Assignment happens immediately after process creation, but Windows can
    schedule the child in that narrow interval. ``taskkill /T`` covers any
    descendant created before assignment; the Job Object covers everything
    created afterwards.
    """
    system_root = os.environ.get("SystemRoot") or os.environ.get("windir")
    if not system_root:
        return False
    executable = Path(system_root) / "System32" / "taskkill.exe"
    if not executable.is_file():
        return False
    try:
        completed = subprocess.run(  # noqa: S603 - absolute Windows system tool
            [str(executable), "/PID", str(process_id), "/T", "/F"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            timeout=TERMINATE_GRACE_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def _close_windows_job(job: int | None) -> None:
    if job is None or sys.platform != "win32":
        return
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CloseHandle(wintypes.HANDLE(job))


def _read_capped(handle, limit: int) -> tuple[str, bool]:
    """The first ``limit`` bytes of a stream, and whether there were more."""
    handle.flush()
    handle.seek(0)
    payload = handle.read(limit + 1)
    truncated = len(payload) > limit
    if truncated:
        payload = payload[:limit]
    return payload.decode("utf-8", errors="replace"), truncated
