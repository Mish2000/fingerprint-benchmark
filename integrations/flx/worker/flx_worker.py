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

import base64
import faulthandler
import hashlib
import json
import os
import platform
import struct
import sys
import time
import zlib
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


# ------------------------------------------------------------------- decode

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
#: A source carrying any of these is ambiguous: it asks a decoder to apply a
#: colour or transparency policy that this project never chose.
AMBIGUOUS_CHUNKS = frozenset({b"PLTE", b"tRNS", b"gAMA", b"sRGB", b"iCCP", b"cHRM"})
#: APNG.  A fingerprint is one image; a file that declares frames is refused
#: rather than silently reduced to its first one.
ANIMATION_CHUNKS = frozenset({b"acTL", b"fcTL", b"fdAT"})


def decode_gray8_png(payload: bytes) -> tuple[int, int, bytearray]:
    """Decode one non-interlaced 8-bit grayscale PNG, or refuse it.

    Written against the container rather than handed to a library, for the same
    reason ``fpbench.imaging.png_chunks`` is: Pillow would happily return an
    ``L`` raster for a paletted, gamma-tagged or 16-bit source, having applied
    a policy nobody chose, and that policy would silently become part of the
    algorithm.
    """
    if not payload.startswith(PNG_SIGNATURE):
        raise WorkerFailure("PNG_BAD_SIGNATURE", "not a PNG")
    offset = len(PNG_SIGNATURE)
    header: tuple[int, int] | None = None
    idat = bytearray()
    saw_end = False

    while offset < len(payload):
        if offset + 8 > len(payload):
            raise WorkerFailure("PNG_TRUNCATED", f"chunk header at byte {offset}")
        (length,) = struct.unpack(">I", payload[offset : offset + 4])
        kind = payload[offset + 4 : offset + 8]
        body_start = offset + 8
        body_end = body_start + length
        if body_end + 4 > len(payload):
            raise WorkerFailure(
                "PNG_TRUNCATED", f"{kind.decode('latin-1')} body at byte {body_start}"
            )
        body = payload[body_start:body_end]
        (declared_crc,) = struct.unpack(">I", payload[body_end : body_end + 4])
        if zlib.crc32(kind + body) & 0xFFFFFFFF != declared_crc:
            raise WorkerFailure("PNG_BAD_CRC", kind.decode("latin-1"))
        if saw_end:
            raise WorkerFailure("PNG_TRAILING_DATA", "a chunk follows IEND")

        if kind == b"IHDR":
            if header is not None:
                raise WorkerFailure("PNG_DUPLICATE_IHDR", "more than one header")
            if length != 13:
                raise WorkerFailure("PNG_BAD_IHDR", f"length {length}")
            width, height, depth, colour, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", body
            )
            if width == 0 or height == 0:
                raise WorkerFailure("PNG_EMPTY_IMAGE", f"{width}x{height}")
            if depth != 8:
                raise WorkerFailure("PNG_UNEXPECTED_BIT_DEPTH", f"bit depth {depth}, expected 8")
            if colour != 0:
                raise WorkerFailure(
                    "PNG_UNEXPECTED_COLOUR_TYPE", f"colour type {colour}, expected 0 (grayscale)"
                )
            if compression != 0 or filtering != 0:
                raise WorkerFailure("PNG_UNSUPPORTED_CODEC", f"{compression}/{filtering}")
            if interlace != 0:
                raise WorkerFailure("PNG_INTERLACED", "interlaced PNG is refused")
            header = (width, height)
        elif kind in ANIMATION_CHUNKS:
            raise WorkerFailure(
                "PNG_MULTI_FRAME", f"{kind.decode('latin-1')}: a fingerprint is one image"
            )
        elif kind in AMBIGUOUS_CHUNKS:
            raise WorkerFailure(
                "PNG_AMBIGUOUS_CHUNK",
                f"{kind.decode('latin-1')} would require a colour policy this project did not choose",
            )
        elif kind == b"IDAT":
            if header is None:
                raise WorkerFailure("PNG_IDAT_BEFORE_IHDR", "IDAT precedes IHDR")
            idat += body
        elif kind == b"IEND":
            saw_end = True
        offset = body_end + 4

    if header is None:
        raise WorkerFailure("PNG_NO_IHDR", "no header chunk")
    if not saw_end:
        raise WorkerFailure("PNG_NO_IEND", "the stream does not terminate")
    if not idat:
        raise WorkerFailure("PNG_NO_IDAT", "no image data")

    width, height = header
    try:
        raw = zlib.decompress(bytes(idat))
    except zlib.error as exc:
        raise WorkerFailure("PNG_BAD_DEFLATE", str(exc)) from exc
    expected = height * (width + 1)
    if len(raw) != expected:
        raise WorkerFailure(
            "PNG_BAD_RASTER_LENGTH", f"expected {expected} filtered bytes, got {len(raw)}"
        )
    return width, height, _unfilter(raw, width, height)


def _unfilter(raw: bytes, width: int, height: int) -> bytearray:
    """Undo the per-scanline filters.  One byte per pixel, so bpp is 1."""
    pixels = bytearray(width * height)
    previous = bytearray(width)
    position = 0
    for row in range(height):
        filter_type = raw[position]
        position += 1
        line = bytearray(raw[position : position + width])
        position += width
        if filter_type == 0:
            pass
        elif filter_type == 1:
            for index in range(1, width):
                line[index] = (line[index] + line[index - 1]) & 0xFF
        elif filter_type == 2:
            for index in range(width):
                line[index] = (line[index] + previous[index]) & 0xFF
        elif filter_type == 3:
            for index in range(width):
                left = line[index - 1] if index else 0
                line[index] = (line[index] + ((left + previous[index]) >> 1)) & 0xFF
        elif filter_type == 4:
            for index in range(width):
                left = line[index - 1] if index else 0
                upper_left = previous[index - 1] if index else 0
                above = previous[index]
                estimate = left + above - upper_left
                distance_left = abs(estimate - left)
                distance_above = abs(estimate - above)
                distance_upper_left = abs(estimate - upper_left)
                if distance_left <= distance_above and distance_left <= distance_upper_left:
                    predictor = left
                elif distance_above <= distance_upper_left:
                    predictor = above
                else:
                    predictor = upper_left
                line[index] = (line[index] + predictor) & 0xFF
        else:
            raise WorkerFailure("PNG_BAD_FILTER", f"filter type {filter_type} on row {row}")
        pixels[row * width : (row + 1) * width] = line
        previous = line
    return pixels


# -------------------------------------------------------------- preprocess


def preprocess(request: Mapping[str, Any]) -> Mapping[str, Any]:
    """canonical gray8 PNG -> [1, 299, 299] float32 in [0, 1].

    Order matters and is deliberate: the exact ``uint8 / 255`` conversion
    happens *before* padding and resizing, as upstream does, so the fill value
    255 enters as exactly 1.0 and the resize runs in float instead of
    quantizing through 8-bit intermediates (docs/adr/0071).
    """
    import torch
    import torchvision.transforms.functional as VTF
    from torchvision.transforms import InterpolationMode

    payload = base64.b64decode(request["image_bytes"], validate=True)
    width, height, pixels = decode_gray8_png(payload)

    tensor = torch.frombuffer(bytearray(pixels), dtype=torch.uint8).reshape(1, height, width)
    tensor = tensor.to(torch.float32).div(255.0)

    side = max(width, height)
    horizontal, vertical = side - width, side - height
    left, top = horizontal // 2, vertical // 2
    right, bottom = horizontal - left, vertical - top
    if left or top or right or bottom:
        tensor = VTF.pad(tensor, padding=[left, top, right, bottom], fill=1.0)
    if tensor.shape[1] != tensor.shape[2]:
        raise WorkerFailure(
            "PREPROCESS_NOT_SQUARE", f"padded to {tuple(tensor.shape)}"
        )

    tensor = VTF.resize(
        tensor,
        [MODEL_INPUT_SIDE, MODEL_INPUT_SIDE],
        interpolation=InterpolationMode.BILINEAR,
        antialias=True,
    )
    tensor = tensor.contiguous()

    if tuple(tensor.shape) != (1, MODEL_INPUT_SIDE, MODEL_INPUT_SIDE):
        raise WorkerFailure("PREPROCESS_WRONG_SHAPE", str(tuple(tensor.shape)))
    if tensor.dtype is not torch.float32:
        raise WorkerFailure("PREPROCESS_WRONG_DTYPE", str(tensor.dtype))
    if not bool(torch.isfinite(tensor).all()):
        raise WorkerFailure("PREPROCESS_NOT_FINITE", "the transform produced a non-finite sample")

    values = tensor.numpy().tobytes()
    return {
        "shape": [1, MODEL_INPUT_SIDE, MODEL_INPUT_SIDE],
        "dtype": "float32",
        "source_width": width,
        "source_height": height,
        "padded_side": side,
        "pad_left": left,
        "pad_top": top,
        "pad_right": right,
        "pad_bottom": bottom,
        "minimum": float(tensor.min()),
        "maximum": float(tensor.max()),
        "values": base64.b64encode(values).decode("ascii"),
        "content_sha256": hashlib.sha256(values).hexdigest(),
    }


# ----------------------------------------------------------------- extract


def _model_input_tensor(request: Mapping[str, Any]):
    import torch

    expected = [1, MODEL_INPUT_SIDE, MODEL_INPUT_SIDE]
    if list(request.get("shape", [])) != expected:
        raise WorkerFailure("EXTRACT_WRONG_INPUT_SHAPE", str(request.get("shape")))
    if str(request.get("dtype")) != "float32":
        raise WorkerFailure("EXTRACT_WRONG_INPUT_DTYPE", str(request.get("dtype")))
    values = base64.b64decode(request["values"], validate=True)
    if len(values) != 4 * MODEL_INPUT_SIDE * MODEL_INPUT_SIDE:
        raise WorkerFailure("EXTRACT_WRONG_INPUT_LENGTH", str(len(values)))

    return torch.frombuffer(bytearray(values), dtype=torch.float32).reshape(*expected)


def _representation_result(output: Any, *, batch_rows: int, row: int) -> Mapping[str, Any]:
    import torch

    texture = output.texture_embeddings
    minutia = output.minutia_embeddings
    if texture is None or minutia is None:
        raise WorkerFailure("EXTRACT_MISSING_BRANCH", "the model returned an empty branch")
    for name, branch, width in (
        ("texture", texture, TEXTURE_DIMENSIONS),
        ("minutia", minutia, MINUTIA_DIMENSIONS),
    ):
        if tuple(branch.shape) != (batch_rows, width):
            raise WorkerFailure("EXTRACT_WRONG_BRANCH_SHAPE", f"{name} {tuple(branch.shape)}")
        if branch.dtype is not torch.float32:
            raise WorkerFailure("EXTRACT_WRONG_BRANCH_DTYPE", f"{name} {branch.dtype}")

    result = {}
    for name, branch in (("texture", texture), ("minutia", minutia)):
        vector = branch[row].detach().clone().contiguous()
        if not bool(torch.isfinite(vector).all()):
            raise WorkerFailure("REPRESENTATION_NOT_FINITE", name)
        raw = vector.numpy().tobytes()
        result[name] = base64.b64encode(raw).decode("ascii")
        result[f"{name}_norm"] = float(torch.linalg.vector_norm(vector.to(torch.float64)))
    return result


def extract(request: Mapping[str, Any]) -> Mapping[str, Any]:
    """One model input -> one representation through the frozen duplicate rule."""
    import torch

    model = require_model()
    tensor = _model_input_tensor(request)
    batch = tensor.unsqueeze(0).repeat(INFERENCE_BATCH_ROWS, 1, 1, 1).contiguous()

    with torch.inference_mode():
        output = model(batch)

    for name, branch in (
        ("texture", output.texture_embeddings),
        ("minutia", output.minutia_embeddings),
    ):
        if branch is None:
            raise WorkerFailure("EXTRACT_MISSING_BRANCH", name)
        if not torch.equal(branch[0], branch[1]):
            raise WorkerFailure(
                "EXTRACT_DUPLICATE_ROWS_DIFFER",
                f"{name}: the duplicated inference batch produced different rows",
            )

    return _representation_result(
        output, batch_rows=INFERENCE_BATCH_ROWS, row=REPRESENTED_ROW
    )


def probe_batch_context(request: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return one row from the frozen two-image diagnostic batch."""
    import torch

    inputs = request.get("inputs")
    if not isinstance(inputs, list) or len(inputs) != INFERENCE_BATCH_ROWS:
        raise WorkerFailure("BATCH_CONTEXT_WRONG_SIZE", "expected exactly two inputs")
    represented_row = request.get("represented_row")
    if type(represented_row) is not int or not 0 <= represented_row < len(inputs):
        raise WorkerFailure("BATCH_CONTEXT_WRONG_ROW", repr(represented_row))
    tensors = [_model_input_tensor(item) for item in inputs]
    batch = torch.stack(tensors, dim=0).contiguous()
    with torch.inference_mode():
        output = require_model()(batch)
    return _representation_result(
        output, batch_rows=len(inputs), row=represented_row
    )


# -------------------------------------------------------------- comparator


def compare(request: Mapping[str, Any]) -> Mapping[str, Any]:
    """raw_score = dot(texture) + dot(minutia), through upstream's own function.

    ``numpy.dot`` is the comparator the pinned repository uses for a one-to-one
    similarity.  Summing two 256-wide dot products in Python instead would be
    mathematically equal and not bitwise equal, so the identified function is
    the one that runs (spec section 10).
    """
    import numpy

    scores = {}
    for name, width in (("texture", TEXTURE_DIMENSIONS), ("minutia", MINUTIA_DIMENSIONS)):
        left = _vector(request["left"][name], width, f"left {name}")
        right = _vector(request["right"][name], width, f"right {name}")
        scores[name] = float(numpy.dot(left, right))
    raw = scores["texture"] + scores["minutia"]
    if not _finite(raw):
        raise WorkerFailure("SCORE_NOT_FINITE", repr(raw))
    return {
        "texture_score": _repr17(scores["texture"]),
        "minutia_score": _repr17(scores["minutia"]),
        "raw_score": _repr17(raw),
    }


def _vector(encoded: str, width: int, what: str):
    import numpy

    raw = base64.b64decode(encoded, validate=True)
    if len(raw) != 4 * width:
        raise WorkerFailure("COMPARE_WRONG_VECTOR_LENGTH", f"{what}: {len(raw)} bytes")
    vector = numpy.frombuffer(raw, dtype=numpy.float32)
    if not bool(numpy.isfinite(vector).all()):
        raise WorkerFailure("COMPARE_VECTOR_NOT_FINITE", what)
    return vector


def _finite(value: float) -> bool:
    return value == value and value not in (float("inf"), float("-inf"))


def _repr17(value: float) -> str:
    """The canonical 17-significant-digit decimal string (spec section 10)."""
    return f"{value:.17g}"


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
        "peak_rss_bytes": _peak_rss_bytes(),
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


def _peak_rss_bytes() -> int:
    """The high-water mark of *this* process, which is where the model lives."""
    try:
        for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("VmHWM:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    try:
        import resource

        return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024
    except Exception:  # pragma: no cover - not a Linux target
        return 0


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
    "preprocess": preprocess,
    "extract": extract,
    "probe_batch_context": probe_batch_context,
    "compare": compare,
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
