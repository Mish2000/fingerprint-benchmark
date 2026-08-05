"""What one extraction produces, and what the parent is allowed to assume.

``FlxRepresentation`` holds the exact IEEE bytes the worker produced.  It does
not hold torch tensors — the parent has no torch — and it does not hold a view
into anything the worker might reuse: every extraction copies, so two
representations can be equal without being the same object (spec section 14).

It is hashable for qualification and it is never written to disk (spec
section 13).
"""

from __future__ import annotations

import base64
import hashlib
import math
import struct
from dataclasses import dataclass
from typing import Any, Mapping

from fpbench.core.flx_errors import FlxRepresentationError
from fpbench.core.flx_models import (
    STAGE8B_SCHEMA_VERSION,
    FlxRepresentationBranchSpec,
    FlxRepresentationProfile,
)
from fpbench.flx import identity

__all__ = ["ModelInput", "FlxRepresentation", "build_representation_profile"]

_BRANCH_WIDTHS = {
    "texture": identity.TEXTURE_DIMENSIONS,
    "minutia": identity.MINUTIA_DIMENSIONS,
}


def _floats(raw: bytes, width: int, what: str) -> tuple[float, ...]:
    if len(raw) != 4 * width:
        raise FlxRepresentationError(
            f"{what}: expected {4 * width} bytes of float32, got {len(raw)}"
        )
    values = struct.unpack(f"<{width}f", raw)
    for value in values:
        if not math.isfinite(value):
            raise FlxRepresentationError(f"{what}: contains a non-finite value")
    return values


@dataclass(frozen=True, slots=True)
class ModelInput:
    """One preprocessed tensor, self-contained and immutable.

    The whole tensor crosses the process boundary rather than staying behind a
    worker-side handle.  That costs about 350 KiB per operation and buys two
    things worth more than that: the parent can check the transform contract
    itself, and there is no worker-side state that could survive between
    operations and become a cache.
    """

    shape: tuple[int, ...]
    dtype: str
    values: bytes
    source_width: int
    source_height: int
    padded_side: int
    pad_left: int
    pad_top: int
    pad_right: int
    pad_bottom: int
    minimum: float
    maximum: float

    def __post_init__(self) -> None:
        side = identity.MODEL_INPUT_SIDE
        if tuple(self.shape) != (1, side, side):
            raise FlxRepresentationError(f"model input shape is {self.shape}, expected (1, {side}, {side})")
        if self.dtype != "float32":
            raise FlxRepresentationError(f"model input dtype is {self.dtype}, expected float32")
        if len(self.values) != 4 * side * side:
            raise FlxRepresentationError(
                f"model input carries {len(self.values)} bytes, expected {4 * side * side}"
            )
        tolerance = identity.VALUE_RANGE_TOLERANCE
        if not (-tolerance <= self.minimum <= self.maximum <= 1.0 + tolerance):
            raise FlxRepresentationError(
                f"model input range [{self.minimum}, {self.maximum}] escapes [0, 1] "
                f"by more than the {tolerance} float32 resampling allowance"
            )

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.values).hexdigest()

    def sample(self, row: int, column: int) -> float:
        side = identity.MODEL_INPUT_SIDE
        offset = 4 * (row * side + column)
        return struct.unpack_from("<f", self.values, offset)[0]

    @classmethod
    def from_worker(cls, payload: Mapping[str, Any]) -> "ModelInput":
        values = base64.b64decode(payload["values"], validate=True)
        declared = str(payload.get("content_sha256", ""))
        if declared and hashlib.sha256(values).hexdigest() != declared:
            raise FlxRepresentationError("the worker's model input does not match its own digest")
        return cls(
            shape=tuple(int(value) for value in payload["shape"]),
            dtype=str(payload["dtype"]),
            values=values,
            source_width=int(payload["source_width"]),
            source_height=int(payload["source_height"]),
            padded_side=int(payload["padded_side"]),
            pad_left=int(payload["pad_left"]),
            pad_top=int(payload["pad_top"]),
            pad_right=int(payload["pad_right"]),
            pad_bottom=int(payload["pad_bottom"]),
            minimum=float(payload["minimum"]),
            maximum=float(payload["maximum"]),
        )

    def as_request(self) -> dict[str, Any]:
        return {
            "shape": list(self.shape),
            "dtype": self.dtype,
            "values": base64.b64encode(self.values).decode("ascii"),
        }


@dataclass(frozen=True, slots=True)
class FlxRepresentation:
    """256 texture dimensions and 256 minutia dimensions, each L2-normalized."""

    texture_bytes: bytes
    minutia_bytes: bytes
    texture_norm: float
    minutia_norm: float

    def __post_init__(self) -> None:
        for name, raw in (("texture", self.texture_bytes), ("minutia", self.minutia_bytes)):
            _floats(raw, _BRANCH_WIDTHS[name], name)
        for name, norm in (("texture", self.texture_norm), ("minutia", self.minutia_norm)):
            if not math.isfinite(norm):
                raise FlxRepresentationError(f"{name}: branch norm is not finite")
            if norm == 0.0:
                raise FlxRepresentationError(
                    f"{name}: a zero-norm branch carries no direction and is refused"
                )

    @property
    def texture(self) -> tuple[float, ...]:
        return _floats(self.texture_bytes, identity.TEXTURE_DIMENSIONS, "texture")

    @property
    def minutia(self) -> tuple[float, ...]:
        return _floats(self.minutia_bytes, identity.MINUTIA_DIMENSIONS, "minutia")

    @property
    def concatenated(self) -> tuple[float, ...]:
        return self.texture + self.minutia

    @property
    def shape(self) -> tuple[int, ...]:
        return (identity.CONCATENATED_DIMENSIONS,)

    @property
    def dtype(self) -> str:
        return "float32"

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.texture_bytes + self.minutia_bytes).hexdigest()

    def is_l2_normalized(self, tolerance: float = 1e-5) -> bool:
        return abs(self.texture_norm - 1.0) <= tolerance and abs(self.minutia_norm - 1.0) <= tolerance

    @classmethod
    def from_worker(cls, payload: Mapping[str, Any]) -> "FlxRepresentation":
        # bytes() copies, so nothing here can alias a buffer the next call reuses.
        return cls(
            texture_bytes=bytes(base64.b64decode(payload["texture"], validate=True)),
            minutia_bytes=bytes(base64.b64decode(payload["minutia"], validate=True)),
            texture_norm=float(payload["texture_norm"]),
            minutia_norm=float(payload["minutia_norm"]),
        )

    def as_request(self) -> dict[str, str]:
        return {
            "texture": base64.b64encode(self.texture_bytes).decode("ascii"),
            "minutia": base64.b64encode(self.minutia_bytes).decode("ascii"),
        }


def build_representation_profile() -> FlxRepresentationProfile:
    branches = (
        FlxRepresentationBranchSpec.create(
            schema_version=STAGE8B_SCHEMA_VERSION,
            branch_id="texture",
            position=0,
            dimensions=identity.TEXTURE_DIMENSIONS,
            dtype="float32",
            normalization="l2_per_branch",
            upstream_module="flx.models.deep_print_arch._Branch_TextureEmbedding",
        ),
        FlxRepresentationBranchSpec.create(
            schema_version=STAGE8B_SCHEMA_VERSION,
            branch_id="minutia",
            position=1,
            dimensions=identity.MINUTIA_DIMENSIONS,
            dtype="float32",
            normalization="l2_per_branch",
            upstream_module="flx.models.deep_print_arch._Branch_MinutiaEmbedding",
        ),
    )
    return FlxRepresentationProfile.create(
        schema_version=STAGE8B_SCHEMA_VERSION,
        profile_id=identity.REPRESENTATION_PROFILE_ID,
        branches=branches,
        concatenated_dimensions=identity.CONCATENATED_DIMENSIONS,
        concatenation_order=("texture", "minutia"),
        inference_batch_rows=identity.INFERENCE_BATCH_ROWS,
        inference_batch_rule=identity.INFERENCE_BATCH_RULE,
        represented_row=identity.REPRESENTED_ROW,
        duplicate_rows_must_be_bitwise_equal=True,
        localization_used=False,
        pose_input_required=False,
        reweighting_applied=False,
        persisted=False,
    )
