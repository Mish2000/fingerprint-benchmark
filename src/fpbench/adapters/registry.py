"""Looking up an adapter by identifier.

The point of the registry is that nothing else in the codebase needs to know
which algorithms exist. The runner asks for an adapter by id and gets one; it
contains no ``if algorithm_id == ...`` anywhere, and neither does anything else
outside this module (docs/adr/0007).

Deliberately a plain dict rather than pip entry points. Dynamic discovery buys
nothing while the answer is a handful of adapters in this repository, and it
can replace this lookup later without a single adapter changing.
"""

from __future__ import annotations

from typing import Callable, Mapping

from fpbench.adapters.base import FingerprintAlgorithmAdapter
from fpbench.core.errors import ConfigurationError
from fpbench.core.identifiers import validate_id

__all__ = [
    "AdapterFactory",
    "ADAPTERS",
    "register_adapter",
    "create_adapter",
    "registered_adapters",
]

AdapterFactory = Callable[[Mapping[str, object]], FingerprintAlgorithmAdapter]

ADAPTERS: dict[str, AdapterFactory] = {}


def register_adapter(adapter_id: str, factory: AdapterFactory) -> None:
    """Make ``adapter_id`` resolvable.

    Raises:
        ConfigurationError: if the id is already taken. Silently replacing a
            registration would let an import order decide which matcher a run
            actually used.
    """
    validate_id(adapter_id)
    if adapter_id in ADAPTERS:
        raise ConfigurationError(f"adapter {adapter_id!r} is already registered")
    ADAPTERS[adapter_id] = factory


def create_adapter(
    adapter_id: str, config: Mapping[str, object] | None = None
) -> FingerprintAlgorithmAdapter:
    """Build the adapter registered under ``adapter_id``."""
    _ensure_builtin_adapters()
    try:
        factory = ADAPTERS[adapter_id]
    except KeyError:
        raise ConfigurationError(
            f"unknown adapter {adapter_id!r}; available: {sorted(ADAPTERS)}"
        ) from None
    return factory(dict(config or {}))


def registered_adapters() -> tuple[str, ...]:
    """Every adapter id currently resolvable, sorted."""
    _ensure_builtin_adapters()
    return tuple(sorted(ADAPTERS))


def _ensure_builtin_adapters() -> None:
    """Register the adapters shipped with the project, on first use.

    Imported lazily so that an adapter with heavy or platform-specific
    dependencies never makes ``import fpbench.adapters`` expensive — or
    impossible — for someone running a different algorithm.
    """
    if "dummy_sha256" not in ADAPTERS:
        from fpbench.adapters.dummy.adapter import DummyShaAdapter

        register_adapter("dummy_sha256", DummyShaAdapter.from_config)
