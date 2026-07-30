"""A research adapter runs the bytes it was pinned to, or nothing at all.

Most of this needs no JVM, which is deliberate: the checks under test are meant
to fire *before* a Java process is started, so a wrong pin costs a hash rather
than a run. The one test that does need Java is marked ``sourceafis``.
"""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

import pytest

from fpbench.adapters.sourceafis_java.adapter import ADAPTER_ID, SourceAfisJavaAdapter
from fpbench.adapters.sourceafis_java.config import (
    BRIDGE_JAR_ROLE,
    SourceAfisJavaConfig,
)
from fpbench.core.enums import EnvironmentStatus
from fpbench.core.errors import ConfigurationError, RuntimeDriftError
from fpbench.storage.runtime_bundle_store import RuntimeBundleStore

REVISION = "0123456789abcdef0123456789abcdef01234567"
PAYLOAD = b"PK\x03\x04 a jar, for the purposes of this test" * 32


@pytest.fixture
def bundled(tmp_path: Path):
    """A materialised bundle holding a stand-in jar, and its store."""
    build = tmp_path / "build"
    build.mkdir()
    source = build / "fpbench-sourceafis-bridge.jar"
    source.write_bytes(PAYLOAD)

    store = RuntimeBundleStore(tmp_path / "workspace")
    bundle = store.materialize(
        adapter_id=ADAPTER_ID, assets={BRIDGE_JAR_ROLE: source}
    )
    return store, bundle


def _pinned(store, bundle, **overrides) -> SourceAfisJavaConfig:
    asset = bundle.asset(BRIDGE_JAR_ROLE)
    settings = {
        "bridge_jar": store.asset_path(bundle.bundle_id, BRIDGE_JAR_ROLE),
        "runtime_bundle_id": bundle.bundle_id,
        "runtime_bundle_fingerprint": bundle.bundle_fingerprint,
        "expected_bridge_jar_sha256": asset.sha256,
        "expected_bridge_jar_size": asset.size_bytes,
        "fpbench_source_revision": REVISION,
        "research_mode": True,
    }
    settings.update(overrides)
    return SourceAfisJavaConfig(**settings)


def _unlock(path: Path) -> Path:
    path.chmod(path.stat().st_mode | stat.S_IWUSR)
    return path


# --------------------------------------------------------- required pinning


@pytest.mark.parametrize(
    "omitted",
    [
        "runtime_bundle_id",
        "runtime_bundle_fingerprint",
        "expected_bridge_jar_sha256",
        "expected_bridge_jar_size",
        "fpbench_source_revision",
    ],
)
def test_research_mode_refuses_a_half_configured_pin(bundled, omitted):
    store, bundle = bundled
    with pytest.raises(ConfigurationError, match="pinned completely"):
        _pinned(store, bundle, **{omitted: None})


def test_research_mode_refuses_to_run_the_build_output(bundled, tmp_path):
    """The whole point: a rebuild can replace that file, so it is not evidence."""
    store, bundle = bundled
    with pytest.raises(ConfigurationError, match="runtime bundle"):
        _pinned(
            store,
            bundle,
            bridge_jar=tmp_path / "build" / "fpbench-sourceafis-bridge.jar",
        )


def test_research_mode_requires_a_full_commit_sha(bundled):
    store, bundle = bundled
    with pytest.raises(ConfigurationError, match="40-character"):
        _pinned(store, bundle, fpbench_source_revision="abc1234")


def test_a_malformed_digest_is_refused_even_outside_research_mode(bundled):
    store, bundle = bundled
    with pytest.raises(ConfigurationError, match="hexadecimal"):
        SourceAfisJavaConfig(expected_bridge_jar_sha256="not-a-digest")


def test_development_mode_needs_none_of_it(bundled):
    """The ordinary adapter is unchanged, and stays convenient."""
    config = SourceAfisJavaConfig()
    assert not config.research_mode
    assert config.runtime_bundle_id is None


def test_pinned_to_leaves_the_development_configuration_alone(bundled):
    store, bundle = bundled
    development = SourceAfisJavaConfig()
    asset = bundle.asset(BRIDGE_JAR_ROLE)
    research = development.pinned_to(
        bridge_jar=store.asset_path(bundle.bundle_id, BRIDGE_JAR_ROLE),
        runtime_bundle_id=bundle.bundle_id,
        runtime_bundle_fingerprint=bundle.bundle_fingerprint,
        expected_bridge_jar_sha256=asset.sha256,
        expected_bridge_jar_size=asset.size_bytes,
        fpbench_source_revision=REVISION,
    )
    assert research.research_mode and not development.research_mode
    assert research.bridge_jar != development.bridge_jar


# ------------------------------------------------------ environment checking


def test_a_wrong_digest_makes_the_environment_unavailable(bundled):
    """Checked before Java is even located, so this holds with no JVM present."""
    store, bundle = bundled
    adapter = SourceAfisJavaAdapter(
        _pinned(store, bundle, expected_bridge_jar_sha256="a" * 64)
    )
    report = adapter.validate_environment()
    assert report.status is EnvironmentStatus.UNAVAILABLE
    assert "pinned to" in (report.message or "")


def test_a_wrong_size_makes_the_environment_unavailable(bundled):
    store, bundle = bundled
    adapter = SourceAfisJavaAdapter(
        _pinned(store, bundle, expected_bridge_jar_size=1)
    )
    report = adapter.validate_environment()
    assert report.status is EnvironmentStatus.UNAVAILABLE
    assert "bytes" in (report.message or "")


def test_a_replaced_jar_makes_the_environment_unavailable(bundled):
    store, bundle = bundled
    jar = _unlock(store.asset_path(bundle.bundle_id, BRIDGE_JAR_ROLE))
    adapter = SourceAfisJavaAdapter(_pinned(store, bundle))
    jar.write_bytes(PAYLOAD + b"rebuilt")

    report = adapter.validate_environment()
    assert report.status is EnvironmentStatus.UNAVAILABLE


def test_an_unavailable_report_carries_no_absolute_path(bundled):
    store, bundle = bundled
    adapter = SourceAfisJavaAdapter(
        _pinned(store, bundle, expected_bridge_jar_sha256="a" * 64)
    )
    report = adapter.validate_environment()
    assert str(store.root) not in (report.message or "")


# ---------------------------------------------------------- runtime drift


def test_an_untouched_jar_passes_the_cheap_check(bundled):
    store, bundle = bundled
    adapter = SourceAfisJavaAdapter(_pinned(store, bundle))
    adapter.validate_environment()
    adapter.check_runtime_integrity()  # must not raise


def test_a_replaced_jar_is_drift_rather_than_a_comparison_failure(bundled):
    store, bundle = bundled
    adapter = SourceAfisJavaAdapter(_pinned(store, bundle))
    adapter.validate_environment()

    jar = _unlock(store.asset_path(bundle.bundle_id, BRIDGE_JAR_ROLE))
    os.utime(jar, (0, 0))

    with pytest.raises(RuntimeDriftError, match="changed while the run"):
        adapter.check_runtime_integrity()


def test_a_deleted_jar_is_drift(bundled):
    store, bundle = bundled
    adapter = SourceAfisJavaAdapter(_pinned(store, bundle))
    adapter.validate_environment()
    _unlock(store.asset_path(bundle.bundle_id, BRIDGE_JAR_ROLE)).unlink()

    with pytest.raises(RuntimeDriftError, match="no longer present"):
        adapter.check_runtime_integrity()


def test_an_unvalidated_research_adapter_refuses_to_compare(bundled):
    store, bundle = bundled
    adapter = SourceAfisJavaAdapter(_pinned(store, bundle))
    with pytest.raises(RuntimeDriftError, match="never validated"):
        adapter.check_runtime_integrity()


def test_a_development_adapter_has_nothing_to_drift(tmp_path):
    """Nothing is pinned outside research mode, so the check is a no-op."""
    SourceAfisJavaAdapter().check_runtime_integrity()


def test_the_drift_message_names_no_path(bundled):
    store, bundle = bundled
    adapter = SourceAfisJavaAdapter(_pinned(store, bundle))
    adapter.validate_environment()
    _unlock(store.asset_path(bundle.bundle_id, BRIDGE_JAR_ROLE)).unlink()

    with pytest.raises(RuntimeDriftError) as caught:
        adapter.check_runtime_integrity()
    assert str(store.root) not in str(caught.value)


# ------------------------------------------------------------ with real Java


@pytest.mark.sourceafis
def test_a_correctly_pinned_bundle_is_ready(tmp_path):
    from sourceafis_support import require_bridge

    _, report = require_bridge()
    build_jar = SourceAfisJavaConfig().bridge_jar

    store = RuntimeBundleStore(tmp_path / "workspace")
    bundle = store.materialize(
        adapter_id=ADAPTER_ID, assets={BRIDGE_JAR_ROLE: build_jar}
    )
    asset = bundle.asset(BRIDGE_JAR_ROLE)
    assert asset.sha256 == hashlib.sha256(build_jar.read_bytes()).hexdigest()

    adapter = SourceAfisJavaAdapter(_pinned(store, bundle))
    pinned_report = adapter.validate_environment()

    assert pinned_report.status is EnvironmentStatus.READY
    assert pinned_report.dependencies["runtime.bundle.id"] == bundle.bundle_id
    assert pinned_report.dependencies["bridge.jar.sha256"] == asset.sha256
    assert pinned_report.implementation_version == report.implementation_version
    assert str(store.root) not in repr(pinned_report)
