"""Driving the frozen runtime from fpbench's side of the pipe.

A long-lived worker rather than a process per comparison. That is safe here for a
reason that was checked rather than assumed: the upstream route holds no state
between calls — no template store, no memo, no lazily built model — so the second
comparison in a process sees exactly what the first one did. G3 proves it by
running the same pair in a fresh process and requiring the same bits.

The worker is not a cache. Every request re-enters
``FingerprintsMatching.fingerprints_matching``, which performs both extractions
itself, including when the two paths are the same file. SELF is two independent
extractions of one image, never one extraction compared with itself.

Three response shapes come back and this module keeps them apart:

* a score, which is the algorithm's own number;
* an algorithmic failure, which is the algorithm declining a print;
* an infrastructure failure, which is the machine being wrong and stops the run.

A dead worker, a timeout or a response that is not one of the three is an
infrastructure failure. None of them is ever a score.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fpbench.core.stage15a_errors import Stage15AAdapterError

__all__ = [
    "BridgeResponse",
    "BridgeWorker",
    "bridge_script_path",
]


def bridge_script_path(*, repository_root: Path | None = None) -> Path:
    root = Path(repository_root) if repository_root is not None else Path(".")
    return root / "integrations" / "fingerprints-matching" / "bridge.py"


@dataclass(frozen=True, slots=True)
class BridgeResponse:
    """One answer from the frozen runtime, already sorted into its kind."""

    status: str
    payload: dict[str, Any]

    @property
    def is_score(self) -> bool:
        return self.status == "score"

    @property
    def is_algorithmic_failure(self) -> bool:
        return self.status == "algorithmic_failure"

    @property
    def is_infrastructure_failure(self) -> bool:
        return self.status == "infrastructure_failure"

    @property
    def score(self) -> float:
        if not self.is_score:
            raise Stage15AAdapterError("this response carries no score")
        return float(self.payload["score"])

    @property
    def code(self) -> str:
        return str(self.payload.get("code", "UNKNOWN"))


class BridgeWorker:
    """A running frozen interpreter, and the pipe to it.

    Not thread-safe by construction — one comparison at a time, which is also
    what the execution profile asks for. The lock is there so that a caller who
    ignores that gets an error rather than two interleaved responses.
    """

    def __init__(
        self,
        *,
        interpreter: Path,
        script: Path,
        timeout_seconds: float,
    ) -> None:
        self._interpreter = Path(interpreter)
        self._script = Path(script)
        self._timeout = float(timeout_seconds)
        self._process: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- lifecycle

    def start(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return
        if not self._interpreter.exists():
            raise Stage15AAdapterError(
                f"the frozen runtime interpreter is missing: {self._interpreter}"
            )
        if not self._script.exists():
            raise Stage15AAdapterError(f"the bridge script is missing: {self._script}")
        # ``-I`` isolates the interpreter from PYTHONPATH and the user site
        # directory: the algorithm's imports come from the frozen environment or
        # from nowhere.
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("PYTHON")
        }
        env["PYTHONIOENCODING"] = "utf-8"
        try:
            self._process = subprocess.Popen(  # noqa: S603
                [str(self._interpreter), "-I", str(self._script)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                bufsize=1,
                env=env,
            )
        except OSError as exc:
            raise Stage15AAdapterError(f"the bridge would not start: {exc}") from exc

    def close(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        try:
            if process.stdin is not None:
                process.stdin.close()
            process.wait(timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            process.kill()

    def restart(self) -> None:
        """A fresh process, for the determinism case that requires one."""
        self.close()
        self.start()

    def __enter__(self) -> "BridgeWorker":
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ requests

    def _request(self, payload: dict[str, Any]) -> BridgeResponse:
        self.start()
        process = self._process
        if process is None or process.stdin is None or process.stdout is None:
            raise Stage15AAdapterError("the bridge is not running")

        timer: threading.Timer | None = None
        try:
            timer = threading.Timer(self._timeout, process.kill)
            timer.start()
            process.stdin.write(json.dumps(payload) + "\n")
            process.stdin.flush()
            line = process.stdout.readline()
        except (OSError, ValueError) as exc:
            self.close()
            return BridgeResponse(
                "infrastructure_failure",
                {"code": "BRIDGE_PIPE_BROKEN", "message": str(exc)[:200]},
            )
        finally:
            if timer is not None:
                timer.cancel()

        if not line:
            returncode = process.poll()
            self.close()
            return BridgeResponse(
                "infrastructure_failure",
                {
                    "code": "BRIDGE_DIED",
                    "message": f"no response; worker exit code {returncode}",
                },
            )
        try:
            decoded = json.loads(line)
        except json.JSONDecodeError as exc:
            self.close()
            return BridgeResponse(
                "infrastructure_failure",
                {"code": "BRIDGE_RESPONSE_NOT_JSON", "message": str(exc)[:200]},
            )
        status = decoded.get("status")
        if status not in {"score", "algorithmic_failure", "infrastructure_failure", "environment"}:
            return BridgeResponse(
                "infrastructure_failure",
                {"code": "BRIDGE_RESPONSE_UNKNOWN_STATUS", "message": repr(status)[:80]},
            )
        return BridgeResponse(str(status), decoded)

    def environment(self) -> BridgeResponse:
        with self._lock:
            return self._request({"op": "environment"})

    def compare(self, left: Path | str, right: Path | str) -> BridgeResponse:
        """One comparison. The two paths go straight to the upstream entry point."""
        with self._lock:
            return self._request(
                {"op": "compare", "left": str(left), "right": str(right)}
            )
