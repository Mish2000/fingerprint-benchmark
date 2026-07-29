"""The lookup that keeps algorithm names out of the rest of the codebase."""

from __future__ import annotations

import pytest

from fpbench.adapters import registry
from fpbench.adapters.base import FingerprintAlgorithmAdapter
from fpbench.core.errors import ConfigurationError
from fpbench.core.identifiers import InvalidIdentifierError
from fakes import CountingAdapter


@pytest.fixture
def isolated_registry(monkeypatch):
    """A copy of the real registry, so tests cannot leak into each other."""
    monkeypatch.setattr(registry, "ADAPTERS", dict(registry.ADAPTERS))
    return registry


def test_the_builtin_adapter_is_registered_lazily():
    assert "dummy_sha256" in registry.registered_adapters()


def test_creating_a_registered_adapter_returns_an_adapter():
    assert isinstance(
        registry.create_adapter("dummy_sha256"), FingerprintAlgorithmAdapter
    )


def test_an_unknown_adapter_is_a_configuration_error():
    with pytest.raises(ConfigurationError, match="unknown adapter"):
        registry.create_adapter("sourceafis")


def test_registering_twice_is_refused(isolated_registry):
    """Silent replacement would let import order pick the matcher."""
    isolated_registry.register_adapter("probe_adapter", lambda config: CountingAdapter())
    with pytest.raises(ConfigurationError, match="already registered"):
        isolated_registry.register_adapter(
            "probe_adapter", lambda config: CountingAdapter()
        )


def test_an_unusable_adapter_id_is_refused(isolated_registry):
    with pytest.raises(InvalidIdentifierError):
        isolated_registry.register_adapter("Not An Id", lambda config: CountingAdapter())


def test_registered_adapters_is_sorted():
    listed = registry.registered_adapters()
    assert list(listed) == sorted(listed)


def test_the_registry_is_the_only_place_that_names_an_algorithm():
    """docs/adr/0007, checked mechanically rather than by review."""
    from pathlib import Path

    source_root = Path(registry.__file__).resolve().parents[2]
    offenders = []
    for path in source_root.rglob("*.py"):
        relative = path.relative_to(source_root)
        if relative.parts[:2] == ("fpbench", "adapters"):
            continue
        if "dummy_sha256" in path.read_text(encoding="utf-8"):
            offenders.append(str(relative))
    assert offenders == [], f"algorithm id leaked outside adapters/: {offenders}"
