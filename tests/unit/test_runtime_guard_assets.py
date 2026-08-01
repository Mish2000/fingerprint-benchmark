"""One tool changing is enough, and one tool is not all of them.

A two-executable pipeline can be broken by either half. The guard therefore
watches the whole role-to-path mapping: a rebuilt matcher with an untouched
extractor is drift, and so is a role that appeared or vanished since preflight
(spec section 44).
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from fpbench.adapters.support.runtime_guard import (
    require_runtime_assets_unchanged,
    require_unchanged,
    snapshot_file_identity,
    snapshot_runtime_assets,
)
from fpbench.core.errors import RuntimeDriftError

pytestmark = pytest.mark.adapter_contract


@pytest.fixture
def assets(tmp_path: Path) -> dict[str, Path]:
    extractor = tmp_path / "extractor.bin"
    matcher = tmp_path / "matcher.bin"
    support = tmp_path / "support.dat"
    extractor.write_bytes(b"extractor-v1")
    matcher.write_bytes(b"matcher-v1")
    support.write_bytes(b"support-v1")
    return {
        "tool_extractor": extractor,
        "tool_matcher": matcher,
        "tool_support_data": support,
    }


def replace(path: Path, payload: bytes) -> None:
    """Rewrite a file the way a rebuild would: new bytes, new mtime."""
    path.write_bytes(payload)
    # Some filesystems have coarse mtime granularity; make the change visible
    # through size as well so the test is not timing-dependent.
    os.utime(path, (time.time() + 1, time.time() + 1))


def test_an_unchanged_runtime_passes(assets):
    expected = snapshot_runtime_assets(assets)
    require_runtime_assets_unchanged(assets, expected)


@pytest.mark.parametrize(
    "role", ["tool_extractor", "tool_matcher", "tool_support_data"]
)
def test_changing_any_single_asset_is_drift(assets, role):
    expected = snapshot_runtime_assets(assets)
    replace(assets[role], b"rebuilt-with-different-bytes")
    with pytest.raises(RuntimeDriftError, match="changed while the run"):
        require_runtime_assets_unchanged(assets, expected)


def test_a_role_that_appeared_is_drift(assets, tmp_path):
    expected = snapshot_runtime_assets(assets)
    extra = tmp_path / "extra.bin"
    extra.write_bytes(b"extra")
    with pytest.raises(RuntimeDriftError, match="appeared"):
        require_runtime_assets_unchanged({**assets, "tool_extra": extra}, expected)


def test_a_role_that_vanished_is_drift(assets):
    expected = snapshot_runtime_assets(assets)
    remaining = dict(assets)
    remaining.pop("tool_matcher")
    with pytest.raises(RuntimeDriftError, match="vanished"):
        require_runtime_assets_unchanged(remaining, expected)


def test_a_deleted_asset_is_drift_rather_than_an_os_error(assets):
    expected = snapshot_runtime_assets(assets)
    assets["tool_matcher"].unlink()
    with pytest.raises(RuntimeDriftError, match="no longer present"):
        require_runtime_assets_unchanged(assets, expected)


def test_an_asset_replaced_by_a_symlink_is_drift(assets, tmp_path):
    expected = snapshot_runtime_assets(assets)
    original = assets["tool_matcher"]
    elsewhere = tmp_path / "other-matcher.bin"
    elsewhere.write_bytes(b"matcher-v1")
    original.unlink()
    try:
        original.symlink_to(elsewhere)
    except (OSError, NotImplementedError):  # pragma: no cover - needs privilege
        pytest.skip("this platform will not create symlinks without privileges")
    with pytest.raises(RuntimeDriftError, match="symlink"):
        require_runtime_assets_unchanged(assets, expected)


def test_snapshotting_nothing_is_a_programming_error(tmp_path):
    with pytest.raises(ValueError, match="at least one asset"):
        snapshot_runtime_assets({})


def test_the_single_file_form_still_works(assets):
    """The SourceAFIS adapter uses it, and it is the same code underneath."""
    jar = assets["tool_extractor"]
    identity = snapshot_file_identity(jar)
    require_unchanged(jar, identity, label="bridge jar")
    replace(jar, b"rebuilt")
    with pytest.raises(RuntimeDriftError, match="bridge jar"):
        require_unchanged(jar, identity, label="bridge jar")


def test_the_old_import_path_is_the_same_object():
    """Moving the guard must not break an import that already works."""
    from fpbench.adapters.sourceafis_java import runtime_guard as legacy
    from fpbench.adapters.support import runtime_guard as shared

    assert legacy.snapshot_file_identity is shared.snapshot_file_identity
    assert legacy.require_unchanged is shared.require_unchanged
    assert legacy.FileIdentity is shared.FileIdentity


def test_an_error_message_carries_no_directory(assets):
    """A drift report is read by people and may outlive the machine."""
    expected = snapshot_runtime_assets(assets)
    replace(assets["tool_matcher"], b"rebuilt-with-different-bytes")
    with pytest.raises(RuntimeDriftError) as caught:
        require_runtime_assets_unchanged(assets, expected)
    assert str(assets["tool_matcher"].parent) not in str(caught.value)
