"""The Stage 8A learned-matcher qualification contract (not an adapter)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping, Protocol, runtime_checkable

__all__ = ["LearnedFingerprintIntegration"]


@runtime_checkable
class LearnedFingerprintIntegration(Protocol):
    """Six operations an artefact must expose before an adapter can be built."""

    def load_runtime(self) -> None: ...

    def preprocess(self, image_bytes: bytes) -> Any: ...

    def extract(self, model_input: Any) -> Any: ...

    def compare(self, left: Any, right: Any) -> Decimal | int: ...

    def validate_runtime(self) -> Mapping[str, Any]: ...

    def describe_operation(self) -> Mapping[str, Any]: ...
