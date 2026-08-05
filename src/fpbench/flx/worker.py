"""Drive the isolated worker: one process, deadlines, no retries.

The parent owns everything about the process and nothing about the model.  It
starts the worker inside the bundle's own interpreter, hands it one JSON
request at a time, enforces a deadline on each, captures stderr, and makes sure
the process is gone afterwards.

There is no automatic retry.  A timeout, a crash and a malformed response are
all comparison failures, and a retry would turn an intermittent runtime fault
into an intermittent number (spec section 12).
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any, Mapping

from fpbench.core.flx_errors import FlxWorkerError, FlxWorkerTimeout
from fpbench.flx.artifacts import FlxRuntimeBundle

__all__ = ["WORKER_SCRIPT", "FlxWorkerSession", "worker_environment"]

WORKER_SCRIPT = (
    Path(__file__).resolve().parents[3] / "integrations" / "flx" / "worker" / "flx_worker.py"
)

#: A named environment, not the developer's.  A worker that behaves differently
#: because someone exported OMP_NUM_THREADS produces representations that
#: cannot be reproduced from the manifest.
_BASE_ENVIRONMENT = {
    "LANG": "C",
    "LC_ALL": "C",
    "TZ": "UTC",
    "PYTHONHASHSEED": "0",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONNOUSERSITE": "1",
    "OMP_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
    "CUDA_VISIBLE_DEVICES": "",
}
#: The floor a process needs to start at all, per platform.
_PLATFORM_FLOOR = ("SystemRoot", "SystemDrive", "TEMP", "TMP", "PATH") if os.name == "nt" else ("PATH",)


def worker_environment(bundle: FlxRuntimeBundle) -> dict[str, str]:
    environment = dict(_BASE_ENVIRONMENT)
    environment["FPBENCH_FLX_BUNDLE"] = str(bundle.root)
    for name in _PLATFORM_FLOOR:
        value = os.environ.get(name)
        if value:
            environment[name] = value
    return environment


class FlxWorkerSession:
    """One worker process, for as long as the caller holds it.

    Loading the runtime once per worker is allowed and intended.  Caching
    anything derived from an *image* is not, and nothing in this class holds a
    tensor, a representation or a score between requests (spec section 13).
    """

    def __init__(
        self,
        bundle: FlxRuntimeBundle,
        *,
        startup_deadline_seconds: float,
        worker_script: Path | None = None,
    ) -> None:
        self.bundle = bundle
        self.startup_deadline_seconds = float(startup_deadline_seconds)
        self.worker_script = Path(worker_script or WORKER_SCRIPT)
        self._process: subprocess.Popen[str] | None = None
        self._responses: "queue.Queue[str | None]" = queue.Queue()
        self._reader: threading.Thread | None = None
        self._stderr_path: Path | None = None
        self._stderr_handle: Any = None

    # ------------------------------------------------------------- lifecycle

    def __enter__(self) -> "FlxWorkerSession":
        self.start()
        return self

    def __exit__(self, *exception: object) -> None:
        self.close()

    def start(self) -> None:
        if self._process is not None:
            raise FlxWorkerError("this worker session has already been started")
        interpreter = self.bundle.venv_python
        if not interpreter.exists():
            raise FlxWorkerError(f"the bundle has no interpreter at {interpreter}")
        if not self.worker_script.is_file():
            raise FlxWorkerError(f"worker script not found: {self.worker_script}")
        handle = tempfile.NamedTemporaryFile(
            mode="w+", encoding="utf-8", suffix=".stderr", delete=False
        )
        self._stderr_handle = handle
        self._stderr_path = Path(handle.name)
        try:
            self._process = subprocess.Popen(
                (str(interpreter), str(self.worker_script)),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=handle,
                text=True,
                encoding="utf-8",
                bufsize=1,
                env=worker_environment(self.bundle),
                cwd=str(self.bundle.root),
                **({"start_new_session": True} if os.name != "nt" else {}),
            )
        except OSError as exc:
            self._cleanup_stderr()
            raise FlxWorkerError(f"could not start the flx worker: {exc}") from exc
        self._reader = threading.Thread(target=self._pump, daemon=True)
        self._reader.start()

    def _pump(self) -> None:
        assert self._process is not None and self._process.stdout is not None
        try:
            for line in self._process.stdout:
                self._responses.put(line)
        except (OSError, ValueError):  # pragma: no cover - pipe closed under us
            pass
        finally:
            self._responses.put(None)

    def close(self) -> None:
        process = self._process
        if process is None:
            self._cleanup_stderr()
            return
        try:
            if process.poll() is None and process.stdin is not None:
                try:
                    process.stdin.write(json.dumps({"operation": "shutdown"}) + "\n")
                    process.stdin.flush()
                    process.stdin.close()
                except (OSError, ValueError):
                    pass
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._kill()
        finally:
            self._process = None
            if self._reader is not None:
                self._reader.join(timeout=5)
                self._reader = None
            self._cleanup_stderr()

    def _kill(self) -> None:
        process = self._process
        if process is None:
            return
        process.kill()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - the OS is stuck
            pass

    def _cleanup_stderr(self) -> None:
        if self._stderr_handle is not None:
            try:
                self._stderr_handle.close()
            except OSError:  # pragma: no cover
                pass
            self._stderr_handle = None
        if self._stderr_path is not None:
            self._stderr_path.unlink(missing_ok=True)
            self._stderr_path = None

    def stderr_tail(self, limit: int = 4000) -> str:
        if self._stderr_path is None or not self._stderr_path.exists():
            return ""
        try:
            return self._stderr_path.read_text(encoding="utf-8", errors="replace")[-limit:]
        except OSError:  # pragma: no cover
            return ""

    # --------------------------------------------------------------- requests

    def request(
        self, operation: str, *, deadline_seconds: float, **payload: Any
    ) -> Mapping[str, Any]:
        """Send one operation and return its structured result, or fail.

        Every failure path ends with the worker dead, because a worker that
        missed a deadline is a worker whose next answer cannot be trusted to
        belong to the next question.
        """
        process = self._process
        if process is None or process.poll() is not None:
            raise FlxWorkerError(f"{operation}: the worker is not running")
        assert process.stdin is not None
        request = {"operation": operation, **payload}
        try:
            process.stdin.write(json.dumps(request) + "\n")
            process.stdin.flush()
        except (OSError, ValueError) as exc:
            self._kill()
            raise FlxWorkerError(f"{operation}: could not reach the worker ({exc})") from exc
        try:
            line = self._responses.get(timeout=float(deadline_seconds))
        except queue.Empty:
            self._kill()
            raise FlxWorkerTimeout(
                f"{operation}: no response within {deadline_seconds}s; there is no retry"
            ) from None
        if line is None:
            code = process.poll()
            self._kill()
            raise FlxWorkerError(
                f"{operation}: the worker exited (status {code}) without responding; "
                f"stderr tail: {self.stderr_tail(600)!r}"
            )
        try:
            response = json.loads(line)
        except ValueError as exc:
            self._kill()
            raise FlxWorkerError(f"{operation}: malformed worker response ({exc})") from exc
        if not isinstance(response, dict):
            self._kill()
            raise FlxWorkerError(f"{operation}: worker response is not an object")
        if response.get("operation") != operation:
            self._kill()
            raise FlxWorkerError(
                f"{operation}: the worker answered {response.get('operation')!r}"
            )
        if not response.get("ok"):
            raise FlxWorkerError(
                f"{operation}: {response.get('code', 'UNKNOWN')}: {response.get('detail', '')}"
            )
        return response

    # ------------------------------------------------------------ operations

    def validate_runtime(self, *, deadline_seconds: float) -> Mapping[str, Any]:
        return self.request("validate_runtime", deadline_seconds=deadline_seconds)["result"]

    def load_runtime(self, *, deadline_seconds: float) -> Mapping[str, Any]:
        return self.request(
            "load_runtime",
            deadline_seconds=deadline_seconds,
            source_tree=str(self.bundle.source_tree),
            checkpoint=str(self.bundle.checkpoint),
        )["result"]
