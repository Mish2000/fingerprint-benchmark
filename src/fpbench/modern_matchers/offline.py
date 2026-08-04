"""Process-local network refusal and a scrubbed environment for smoke probes."""

from __future__ import annotations

import contextlib
import os
import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from fpbench.core.errors import QualificationError

__all__ = ["NetworkAccessBlocked", "offline_network_guard", "sanitised_runtime_environment"]


class NetworkAccessBlocked(QualificationError):
    pass


@contextlib.contextmanager
def offline_network_guard() -> Iterator[None]:
    """Refuse Python socket connections during qualification.

    Candidate subprocesses additionally receive the scrubbed environment below;
    a real candidate qualification must also record its OS-level isolation in
    the determinism/runtime evidence.  This guard makes import-time and lazy
    Python downloads fail loudly instead of reaching a hub.
    """

    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_create_connection = socket.create_connection

    def blocked(*args: Any, **kwargs: Any) -> Any:
        raise NetworkAccessBlocked("network access is forbidden during Stage 8A qualification")

    socket.socket.connect = blocked  # type: ignore[method-assign]
    socket.socket.connect_ex = blocked  # type: ignore[method-assign]
    socket.create_connection = blocked  # type: ignore[assignment]
    try:
        yield
    finally:
        socket.socket.connect = original_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = original_connect_ex  # type: ignore[method-assign]
        socket.create_connection = original_create_connection  # type: ignore[assignment]


def sanitised_runtime_environment() -> dict[str, str]:
    """An allowlisted child environment with every common model hub offline."""
    allowed = (
        "PATH",
        "SystemRoot",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "TEMP",
        "TMP",
        "LANG",
        "LC_ALL",
        "PYTHONPATH",
    )
    environment = {name: os.environ[name] for name in allowed if name in os.environ}
    environment.update(
        {
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_DATASETS_OFFLINE": "1",
            "TORCH_HOME": str(Path(os.environ.get("TEMP", ".")) / "fpbench-stage8a-no-download"),
            "NO_PROXY": "*",
            "no_proxy": "*",
        }
    )
    return environment
