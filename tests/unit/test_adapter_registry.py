"""The lookup that keeps algorithm names out of the rest of the codebase."""

from __future__ import annotations

import pytest

from fpbench.adapters import registry
from fpbench.adapters.base import (
    SUPPORTED_ADAPTER_CONTRACT_VERSIONS,
    FingerprintAlgorithmAdapter,
)
from fpbench.adapters.errors import AdapterContractViolation
from fpbench.core.errors import ConfigurationError
from fpbench.core.identifiers import InvalidIdentifierError
from fakes import CountingAdapter, fake_descriptor, registry_configuration


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


# ---------------------------------------------------- what create_adapter checks
#
# Three faults a factory can have, each of which would otherwise surface much
# later as something that looks like corrupt evidence (spec section 49).


@pytest.mark.adapter_contract
def test_a_factory_that_returns_a_different_adapter_id_is_refused(isolated_registry):
    """A run built from this registry would record an algorithm it did not use."""
    isolated_registry.register_adapter(
        "declared_adapter", lambda config: CountingAdapter()
    )
    with pytest.raises(ConfigurationError, match="describes itself as"):
        isolated_registry.create_adapter("declared_adapter")


@pytest.mark.adapter_contract
def test_an_unsupported_contract_version_is_refused(isolated_registry):
    class FutureContractAdapter(CountingAdapter):
        @property
        def descriptor(self):
            base = fake_descriptor("future_adapter")
            from dataclasses import replace

            return replace(base, adapter_contract_version="99")

    isolated_registry.register_adapter(
        "future_adapter", lambda config: FutureContractAdapter()
    )
    with pytest.raises(AdapterContractViolation, match="contract version"):
        isolated_registry.create_adapter("future_adapter")


@pytest.mark.adapter_contract
def test_an_unstable_descriptor_is_refused(isolated_registry):
    """A descriptor rebuilt per access would change the fingerprint mid-run."""

    class DriftingAdapter(CountingAdapter):
        def __init__(self) -> None:
            super().__init__()
            self._reads = 0

        @property
        def descriptor(self):
            self._reads += 1
            from dataclasses import replace

            return replace(
                fake_descriptor("drifting_adapter"),
                implementation_version=f"test-{self._reads}",
            )

    isolated_registry.register_adapter(
        "drifting_adapter", lambda config: DriftingAdapter()
    )
    with pytest.raises(AdapterContractViolation, match="different descriptor"):
        isolated_registry.create_adapter("drifting_adapter")


@pytest.mark.adapter_contract
def test_something_that_is_not_an_adapter_at_all_is_refused(isolated_registry):
    isolated_registry.register_adapter("not_an_adapter", lambda config: object())
    with pytest.raises(AdapterContractViolation, match="not a Fingerprint"):
        isolated_registry.create_adapter("not_an_adapter")


@pytest.mark.adapter_contract
def test_every_registered_adapter_declares_a_supported_contract_version():
    for adapter_id in registry.registered_adapters():
        adapter = registry.create_adapter(adapter_id, registry_configuration(adapter_id))
        assert (
            adapter.descriptor.adapter_contract_version
            in SUPPORTED_ADAPTER_CONTRACT_VERSIONS
        )


@pytest.mark.adapter_contract
def test_the_registry_is_still_a_plain_dict():
    """No entry points, no scanning: the lookup stays readable (spec section 49)."""
    assert isinstance(registry.ADAPTERS, dict)


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
