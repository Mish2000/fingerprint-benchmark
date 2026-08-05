"""The isolated flx inference worker.

This file runs inside the pinned runtime, in its own process, and is the only
place torch is ever imported.  It must not import ``fpbench``: its dependency
surface is exactly the locked distributions plus the standard library, so that
the runtime manifest describes everything that can influence a number.

It is also the process that touches the checkpoint.  A ``.pyt`` file is an
external serialization from a third party and is treated as untrusted input:
size and digest are checked before it is opened, it is loaded with
``weights_only=True`` so no pickled object can execute, the model is built from
the pinned source rather than from anything inside the file, and the state dict
is loaded strictly against a training-only allowlist frozen in advance.

The protocol is one JSON request per line on stdin, one JSON response per line
on stdout.  The parent owns deadlines, exit status and cleanup.
"""

from __future__ import annotations

import faulthandler
import hashlib
import json
import os
import platform
import sys
import time
from pathlib import Path
from typing import Any, Mapping

PROTOCOL_VERSION = 1

# Frozen upstream in fpbench.flx.identity.  Restated here rather than imported,
# because the worker may not import fpbench; the parent asserts they agree.
CHECKPOINT_SHA256 = "2683a04427bacd54adc00cfdc97474625b1e11e5a9e6672c5129f033018f8a28"
CHECKPOINT_SIZE_BYTES = 875770140
TRAINING_ONLY_CHECKPOINT_KEYS = ("loss_state_dict", "optimizer_state_dict")
MODEL_STATE_KEY = "model_state_dict"
NUM_TRAINING_CLASSES = 8000
TEXTURE_DIMENSIONS = 256
MINUTIA_DIMENSIONS = 256
MODEL_INPUT_SIDE = 299
INFERENCE_BATCH_ROWS = 2
REPRESENTED_ROW = 0

_STATE: dict[str, Any] = {"model": None, "loaded": False, "load_seconds": None}


class WorkerFailure(Exception):
    """A structured failure.  The parent sees the code, never a traceback."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


# ----------------------------------------------------------------- offline


def preimport_runtime() -> None:
    """Import the locked runtime before the network is sealed.

    ``torch.hub`` imports ``urllib.request``, which imports ``ssl``, which
    executes ``class SSLSocket(socket)`` at import time.  Sealing the socket
    layer first would break that class definition and the runtime would never
    load — so the imports happen first, and the seal goes on immediately after,
    before any request is read.  Importing a module is not a network access.
    """
    import numpy  # noqa: F401
    import torch
    import torchvision  # noqa: F401

    # Both pins have to happen here.  set_num_interop_threads is only honoured
    # before the interop pool starts, so deferring it to load_runtime would
    # silently leave the machine's core count inside the runtime identity.
    torch.set_num_threads(1)
    try:
        torch.set_num_interop_threads(1)
    except RuntimeError:  # pragma: no cover - only if a pool already started
        pass


def enforce_offline() -> dict[str, Any]:
    """Make a network call fail loudly here rather than quietly succeed.

    Spec section 15: an attempted access is a failure even when it would have
    failed anyway.  Connecting methods are replaced rather than the socket
    class itself, so subclasses that already exist keep working while every
    route that could actually reach the network raises and is counted.
    """
    import socket
    import urllib.request

    attempts = {"count": 0}

    def refuse(what: str):
        def guard(*args: Any, **kwargs: Any):
            attempts["count"] += 1
            raise OSError(
                f"network access is forbidden inside a Stage 8B operation ({what})"
            )

        return guard

    socket.socket.connect = refuse("socket.connect")  # type: ignore[method-assign]
    socket.socket.connect_ex = refuse("socket.connect_ex")  # type: ignore[method-assign]
    socket.socket.sendto = refuse("socket.sendto")  # type: ignore[method-assign]
    socket.create_connection = refuse("socket.create_connection")  # type: ignore[assignment]
    socket.getaddrinfo = refuse("socket.getaddrinfo")  # type: ignore[assignment]
    socket.gethostbyname = refuse("socket.gethostbyname")  # type: ignore[assignment]
    socket.gethostbyname_ex = refuse("socket.gethostbyname_ex")  # type: ignore[assignment]
    urllib.request.urlopen = refuse("urllib.request.urlopen")  # type: ignore[assignment]

    import torch.hub

    torch.hub.load_state_dict_from_url = refuse("torch.hub.load_state_dict_from_url")
    torch.hub.download_url_to_file = refuse("torch.hub.download_url_to_file")
    return attempts


def neutralize_environment(bundle_root: Path) -> dict[str, str]:
    """Point every model-hub and proxy variable at a local, controlled place."""
    removed = []
    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "NO_PROXY",
        "no_proxy",
    ):
        if os.environ.pop(name, None) is not None:
            removed.append(name)
    cache = bundle_root / "offline-cache"
    cache.mkdir(parents=True, exist_ok=True)
    redirected = {}
    for name in ("HF_HOME", "TORCH_HOME", "HUGGINGFACE_HUB_CACHE", "XDG_CACHE_HOME"):
        os.environ[name] = str(cache)
        redirected[name] = str(cache)
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    return {"removed": removed, "redirected": redirected}


def pin_threads() -> None:
    """One thread, so MKL's reduction order is not part of the answer."""
    for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[name] = "1"


# ------------------------------------------------------------------ digest


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


# ------------------------------------------------------------------- model


def _import_upstream(source_tree: Path):
    if str(source_tree) not in sys.path:
        sys.path.insert(0, str(source_tree))
    try:
        from flx.models.deep_print_arch import DeepPrint_TexMinu
    except Exception as exc:  # noqa: BLE001 - reported, never raised onward
        raise WorkerFailure("UPSTREAM_IMPORT_FAILED", f"{type(exc).__name__}: {exc}") from exc
    return DeepPrint_TexMinu


def _load_checkpoint(path: Path):
    import torch

    size = path.stat().st_size
    if size != CHECKPOINT_SIZE_BYTES:
        raise WorkerFailure(
            "CHECKPOINT_SIZE_MISMATCH",
            f"expected {CHECKPOINT_SIZE_BYTES} bytes, found {size}",
        )
    digest = file_sha256(path)
    if digest != CHECKPOINT_SHA256:
        raise WorkerFailure(
            "CHECKPOINT_DIGEST_MISMATCH", f"expected {CHECKPOINT_SHA256}, found {digest}"
        )
    try:
        payload = torch.load(path, map_location="cpu", weights_only=True)
    except Exception as exc:  # noqa: BLE001
        raise WorkerFailure(
            "CHECKPOINT_NOT_WEIGHTS_ONLY",
            f"the checkpoint did not load as pure tensors: {type(exc).__name__}: {exc}",
        ) from exc
    if not isinstance(payload, dict):
        raise WorkerFailure("CHECKPOINT_NOT_A_MAPPING", f"top level is {type(payload).__name__}")
    allowed = {MODEL_STATE_KEY, *TRAINING_ONLY_CHECKPOINT_KEYS}
    unexpected = sorted(set(payload) - allowed)
    if unexpected:
        raise WorkerFailure(
            "CHECKPOINT_UNEXPECTED_TOP_LEVEL_KEYS",
            f"the frozen allowlist does not cover {unexpected}",
        )
    if MODEL_STATE_KEY not in payload:
        raise WorkerFailure("CHECKPOINT_MISSING_MODEL_STATE", f"no {MODEL_STATE_KEY}")
    return payload[MODEL_STATE_KEY]


def load_runtime(request: Mapping[str, Any]) -> Mapping[str, Any]:
    source_tree = Path(request["source_tree"])
    checkpoint = Path(request["checkpoint"])
    started = time.perf_counter()

    constructor = _import_upstream(source_tree)
    state_dict = _load_checkpoint(checkpoint)
    model = constructor(
        NUM_TRAINING_CLASSES,
        TEXTURE_DIMENSIONS,
        MINUTIA_DIMENSIONS,
    )
    incompatible = model.load_state_dict(state_dict, strict=True)
    missing = tuple(getattr(incompatible, "missing_keys", ()) or ())
    unexpected = tuple(getattr(incompatible, "unexpected_keys", ()) or ())
    if missing or unexpected:
        raise WorkerFailure(
            "STATE_DICT_KEY_MISMATCH",
            f"missing={list(missing)} unexpected={list(unexpected)}",
        )
    model.eval()
    for parameter in model.parameters():
        parameter.requires_grad_(False)

    _STATE["model"] = model
    _STATE["loaded"] = True
    _STATE["load_seconds"] = time.perf_counter() - started
    return {
        "loaded": True,
        "load_seconds": _STATE["load_seconds"],
        "training_mode": bool(model.training),
        "gradients_enabled": any(p.requires_grad for p in model.parameters()),
        "parameter_count": sum(p.numel() for p in model.parameters()),
        "state_dict_entries": len(state_dict),
        "missing_state_dict_keys": list(missing),
        "unexpected_state_dict_keys": list(unexpected),
    }


def require_model():
    if not _STATE["loaded"]:
        raise WorkerFailure("RUNTIME_NOT_LOADED", "load_runtime must succeed first")
    return _STATE["model"]


# -------------------------------------------------------------- describe


def validate_runtime(request: Mapping[str, Any]) -> Mapping[str, Any]:
    import numpy
    import torch
    import torchvision

    distributions: dict[str, str] = {}
    from importlib.metadata import distributions as installed

    for distribution in installed():
        name = distribution.metadata["Name"]
        if name:
            distributions[name] = distribution.version

    parallel = torch.__config__.parallel_info()
    blas = next(
        (line.strip() for line in parallel.splitlines() if "Math Kernel Library" in line),
        "unknown",
    )
    mkldnn = next(
        (line.strip() for line in parallel.splitlines() if "MKL-DNN" in line), "unknown"
    )
    backend = next(
        (
            line.split(":", 1)[1].strip()
            for line in parallel.splitlines()
            if line.startswith("ATen parallel backend")
        ),
        "unknown",
    )
    return {
        "protocol_version": PROTOCOL_VERSION,
        "os_name": platform.system(),
        "os_version": _os_release(),
        "kernel_release": platform.release(),
        "cpu_architecture": platform.machine(),
        "cpu_model": _cpu_model(),
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "python_executable": Path(sys.executable).name,
        "torch_version": torch.__version__,
        "torchvision_version": torchvision.__version__,
        "numpy_version": numpy.__version__,
        "blas_implementation": blas,
        "mkldnn_version": mkldnn,
        "parallel_backend": backend,
        "torch_num_threads": torch.get_num_threads(),
        "torch_num_interop_threads": torch.get_num_interop_threads(),
        "device": "cpu",
        "cuda_available": bool(torch.cuda.is_available()),
        "distributions": distributions,
        "environment": {
            name: os.environ.get(name, "")
            for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "HF_HOME", "TORCH_HOME")
        },
    }


def _os_release() -> str:
    try:
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            if line.startswith("PRETTY_NAME="):
                return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return platform.version()


def _cpu_model() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "unknown"


# ------------------------------------------------------------------- loop

HANDLERS = {
    "load_runtime": load_runtime,
    "validate_runtime": validate_runtime,
}


def handle(request: Mapping[str, Any]) -> Mapping[str, Any]:
    operation = request.get("operation")
    handler = HANDLERS.get(str(operation))
    if handler is None:
        raise WorkerFailure("UNKNOWN_OPERATION", f"{operation!r}")
    return handler(request)


def main() -> int:
    faulthandler.enable(file=sys.stderr)
    pin_threads()
    bundle_root = Path(os.environ.get("FPBENCH_FLX_BUNDLE", "."))
    environment = neutralize_environment(bundle_root)
    preimport_runtime()
    attempts = enforce_offline()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except ValueError as exc:
            _respond({"ok": False, "code": "MALFORMED_REQUEST", "detail": str(exc)})
            continue
        started = time.perf_counter()
        try:
            payload = handle(request)
            response = {
                "ok": True,
                "operation": request.get("operation"),
                "seconds": time.perf_counter() - started,
                "network_attempts": attempts["count"],
                "result": payload,
            }
        except WorkerFailure as failure:
            response = {
                "ok": False,
                "operation": request.get("operation"),
                "seconds": time.perf_counter() - started,
                "network_attempts": attempts["count"],
                "code": failure.code,
                "detail": failure.detail,
            }
        except Exception as exc:  # noqa: BLE001 - never leak a traceback upward
            response = {
                "ok": False,
                "operation": request.get("operation"),
                "seconds": time.perf_counter() - started,
                "network_attempts": attempts["count"],
                "code": "UNHANDLED_WORKER_ERROR",
                "detail": f"{type(exc).__name__}: {exc}",
            }
        if request.get("operation") == "shutdown":
            break
        _respond(response)
    _ = environment
    return 0


def _respond(payload: Mapping[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, sort_keys=True) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    raise SystemExit(main())
