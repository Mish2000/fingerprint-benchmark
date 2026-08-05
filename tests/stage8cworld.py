"""A Stage 8C world with no torch, no checkpoint and no 2 GB bundle in it.

The flx route is a persistent worker holding an 875 MB checkpoint. Almost
nothing about Stage 8C needs that: the adapter contract, the failure taxonomy,
the Decimal rule, the independence of the two sides and the shape of a stored
result are all properties of the wiring, and the wiring is what these fakes
exercise.

``FakeFlxIntegration`` mimics exactly the surface
:class:`~fpbench.flx.integration.FlxLearnedFingerprintIntegration` presents to
the adapter — six operations and three counters — and nothing else. It counts
its own calls and records the identity of every object it returned, so a test
can assert that no representation was ever reused rather than trusting a
docstring.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Mapping

from fpbench.core.enums import ChecksumStatus
from fpbench.core.execution_models import ComparisonContext, PreparedImage
from fpbench.core.identifiers import ImageId
from fpbench.flx import identity
from fpbench.flx.fixtures import gray8_png

__all__ = [
    "FakeModelInput",
    "FakeRepresentation",
    "FakeFlxIntegration",
    "READY_RUNTIME_REPORT",
    "make_prepared_image",
    "make_context",
    "write_fixture_png",
]


#: What a healthy ``validate_runtime()`` says. Every key the adapter reads is
#: present; nothing here varies between two calls on one machine, which is what
#: makes the engine's environment fingerprint stable across prepare and execute.
READY_RUNTIME_REPORT: Mapping[str, Any] = {
    "runtime_profile_id": identity.RUNTIME_PROFILE_ID,
    "runtime_manifest_fingerprint": "a" * 64,
    "os_version": "6.6.87.2-microsoft-standard-WSL2",
    "cpu_architecture": "x86_64",
    "python_version": "3.12.3",
    "torch_version": "2.13.0+cpu",
    "torchvision_version": "0.28.0+cpu",
    "numpy_version": "2.1.3",
    "blas_implementation": "openblas",
    "mkldnn_version": "v3.5.3",
    "torch_num_threads": 1,
    "torch_num_interop_threads": 1,
    "device": "cpu",
    "cuda_available": False,
    "dependency_lock_sha256": "b" * 64,
    "checkpoint_loaded": True,
    "model_in_eval_mode": True,
    "gradients_disabled": True,
    "missing_state_dict_keys": (),
    "unexpected_state_dict_keys": (),
    "network_attempts": 0,
}


@dataclass(frozen=True, slots=True)
class FakeModelInput:
    """Stands in for one 299x299 tensor. Distinct per preprocess call."""

    digest: str
    serial: int


@dataclass(frozen=True, slots=True)
class FakeRepresentation:
    """Stands in for 256 texture and 256 minutia dimensions.

    ``digest`` is the content: two representations of the same image are equal.
    ``serial`` is the call that produced it: two representations of the same
    image are never the *same object*, and the difference between those two
    sentences is the whole of spec section 9.
    """

    digest: str
    serial: int


class FakeFlxIntegration:
    """The six operations, the three counters, and a ledger of what it returned."""

    def __init__(
        self,
        bundle: Any = None,
        *,
        lock_path: Path | None = None,
        policy_path: Path | None = None,
        runtime_report: Mapping[str, Any] | None = None,
        score: Callable[[FakeRepresentation, FakeRepresentation], Decimal] | None = None,
        fail_on: Mapping[str, BaseException] | None = None,
        load_error: BaseException | None = None,
        close_error: BaseException | None = None,
    ) -> None:
        self.bundle = bundle
        self.lock_path = lock_path
        self.policy_path = policy_path
        self._runtime_report = dict(runtime_report or READY_RUNTIME_REPORT)
        self._score = score or _default_score
        self._fail_on = dict(fail_on or {})
        self._load_error = load_error
        self._close_error = close_error

        self.preprocess_calls = 0
        self.extract_calls = 0
        self.compare_calls = 0

        self.loaded = False
        self.closed = 0
        self.model_inputs: list[FakeModelInput] = []
        self.representations: list[FakeRepresentation] = []
        self.compared: list[tuple[int, int]] = []

    # ------------------------------------------------------------- lifecycle

    def load_runtime(self) -> None:
        if self._load_error is not None:
            raise self._load_error
        self.loaded = True

    def close(self) -> None:
        self.closed += 1
        self.loaded = False
        if self._close_error is not None:
            raise self._close_error

    # ------------------------------------------------------------ operations

    def preprocess(self, image_bytes: bytes) -> FakeModelInput:
        self._maybe_fail("preprocess")
        self.preprocess_calls += 1
        import hashlib

        model_input = FakeModelInput(
            digest=hashlib.sha256(image_bytes).hexdigest(),
            serial=self.preprocess_calls,
        )
        self.model_inputs.append(model_input)
        return model_input

    def extract(self, model_input: FakeModelInput) -> FakeRepresentation:
        self._maybe_fail("extract")
        self.extract_calls += 1
        representation = FakeRepresentation(
            digest=model_input.digest, serial=self.extract_calls
        )
        self.representations.append(representation)
        return representation

    def compare(
        self, left: FakeRepresentation, right: FakeRepresentation
    ) -> Decimal:
        self._maybe_fail("compare")
        self.compare_calls += 1
        self.compared.append((left.serial, right.serial))
        return self._score(left, right)

    def validate_runtime(self) -> Mapping[str, Any]:
        self._maybe_fail("validate_runtime")
        return dict(self._runtime_report)

    def _maybe_fail(self, operation: str) -> None:
        error = self._fail_on.get(operation)
        if error is not None:
            raise error


def _default_score(left: FakeRepresentation, right: FakeRepresentation) -> Decimal:
    """A SELF pair lands just above 2, exactly as the pinned runtime does."""
    if left.digest == right.digest:
        return Decimal("2.0000001192092896")
    return Decimal("0.42314159265358979")


# ------------------------------------------------------------------ fixtures


def write_fixture_png(directory: Path, name: str, *, side: int = 40) -> Path:
    """One small synthetic gray8 PNG. Generated, never biometric."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.png"
    payload = gray8_png(side, side, lambda x, y: (x * 7 + y * 13 + len(name)) % 256)
    path.write_bytes(payload)
    return path


def make_prepared_image(path: Path, *, image_id: str = "SD300A_00001_plain_01") -> PreparedImage:
    """A prepared image whose declared digest is the file's own."""
    import hashlib

    raw = Path(path).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    return PreparedImage(
        image_id=ImageId(image_id),
        local_path=Path(path).resolve(),
        effective_ppi=500,
        media_type="image/png",
        expected_sha256=digest,
        checksum_status=ChecksumStatus.VERIFIED,
        preparation_profile_id="canonical_gray8_500ppi_lanczos3_v1",
        preparation_hash="c" * 64,
        source_effective_ppi=500,
        prepared_sha256=digest,
        prepared_size_bytes=len(raw),
        preparation_set_id="prepset_be560e047991",
        preparation_set_fingerprint="d" * 64,
        preparation_entry_hash="e" * 64,
        pixel_sha256="f" * 64,
        pixel_width=40,
        pixel_height=40,
    )


def make_context(tmp_path: Path, *, job_id: str = "job_0000000000000001") -> ComparisonContext:
    working = tmp_path / "work"
    artifacts = tmp_path / "artifacts"
    working.mkdir(parents=True, exist_ok=True)
    artifacts.mkdir(parents=True, exist_ok=True)
    return ComparisonContext(
        run_id="run_000000000001",
        job_id=job_id,
        attempt=1,
        working_directory=working.resolve(),
        artifact_directory=artifacts.resolve(),
        timeout_seconds=480.0,
        deterministic_seed=0,
    )
