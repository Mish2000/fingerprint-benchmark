"""A runtime bundle is the bytes, not the path they were copied from.

The property under test throughout: the same file produces the same bundle from
anywhere, at any time, and a bundle that has been touched since is detectable.
Everything else here — symlinks, hardlinks, permissions, write order — exists to
make that property survive contact with a filesystem.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from fpbench.core.errors import RuntimeBundleConflictError, StorageError
from fpbench.core.runtime_models import (
    CONTENT_ADDRESSED_COPY_V1,
    runtime_bundle_fingerprint,
)
from fpbench.storage.runtime_bundle_store import RuntimeBundleStore

ADAPTER = "sourceafis_java_subprocess"
ROLE = "sourceafis_bridge_jar"

PAYLOAD = b"PK\x03\x04 pretend this is a shaded jar" * 64


def _write(path: Path, payload: bytes = PAYLOAD) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _unlock(path: Path) -> Path:
    """Undo the store's read-only bit so a test can forge damage."""
    path.chmod(path.stat().st_mode | stat.S_IWUSR)
    return path


@pytest.fixture
def store(tmp_path: Path) -> RuntimeBundleStore:
    return RuntimeBundleStore(tmp_path / "workspace")


@pytest.fixture
def source(tmp_path: Path) -> Path:
    return _write(tmp_path / "build" / "fpbench-sourceafis-bridge.jar")


# ------------------------------------------------------------------ identity


def test_the_same_bytes_at_the_same_path_produce_the_same_bundle(store, source):
    first = store.materialize(adapter_id=ADAPTER, assets={ROLE: source})
    second = store.materialize(adapter_id=ADAPTER, assets={ROLE: source})
    assert first.bundle_id == second.bundle_id
    assert first.bundle_fingerprint == second.bundle_fingerprint


def test_the_same_bytes_at_a_different_path_produce_the_same_bundle(
    store, source, tmp_path
):
    """The point of the whole exercise: a build directory is not an identity."""
    elsewhere = _write(tmp_path / "somewhere" / "else" / source.name)
    first = store.materialize(adapter_id=ADAPTER, assets={ROLE: source})
    second = store.materialize(adapter_id=ADAPTER, assets={ROLE: elsewhere})
    assert first.bundle_id == second.bundle_id


def test_different_bytes_produce_a_different_bundle(store, source, tmp_path):
    other = _write(tmp_path / "rebuild" / source.name, PAYLOAD + b"!")
    first = store.materialize(adapter_id=ADAPTER, assets={ROLE: source})
    second = store.materialize(adapter_id=ADAPTER, assets={ROLE: other})
    assert first.bundle_id != second.bundle_id
    assert store.has_bundle(first.bundle_id) and store.has_bundle(second.bundle_id)


def test_a_new_timestamp_alone_does_not_change_the_bundle(store, source):
    first = store.materialize(adapter_id=ADAPTER, assets={ROLE: source})
    os.utime(source, (0, 0))
    second = store.materialize(adapter_id=ADAPTER, assets={ROLE: source})
    assert first.bundle_id == second.bundle_id


def test_two_adapters_do_not_share_one_bundle(store, source):
    """Same jar, different adapter, different runtime. Ids must not collide."""
    first = store.materialize(adapter_id=ADAPTER, assets={ROLE: source})
    second = store.materialize(adapter_id="another_adapter", assets={ROLE: source})
    assert first.bundle_id != second.bundle_id


def test_the_bundle_id_is_derived_from_the_fingerprint(store, source):
    bundle = store.materialize(adapter_id=ADAPTER, assets={ROLE: source})
    assert bundle.bundle_id == f"runtime_{bundle.bundle_fingerprint[:12]}"
    assert bundle.bundle_fingerprint == runtime_bundle_fingerprint(
        adapter_id=ADAPTER,
        materialization_policy=CONTENT_ADDRESSED_COPY_V1,
        assets=bundle.assets,
    )


# ------------------------------------------------------------- materialisation


def test_the_copy_holds_the_source_bytes(store, source):
    bundle = store.materialize(adapter_id=ADAPTER, assets={ROLE: source})
    copy = store.asset_path(bundle.bundle_id, ROLE)
    assert copy.read_bytes() == source.read_bytes()
    assert bundle.asset(ROLE).size_bytes == len(PAYLOAD)


def test_no_hardlink_is_created(store, source):
    """A hardlink would let a rebuild rewrite the 'immutable' asset in place."""
    bundle = store.materialize(adapter_id=ADAPTER, assets={ROLE: source})
    copy = store.asset_path(bundle.bundle_id, ROLE)
    assert not os.path.samefile(source, copy)


def test_the_asset_is_made_read_only_where_the_filesystem_allows_it(store, source):
    bundle = store.materialize(adapter_id=ADAPTER, assets={ROLE: source})
    copy = store.asset_path(bundle.bundle_id, ROLE)
    assert not os.access(copy, os.W_OK)


@pytest.mark.skipif(os.name == "nt", reason="Windows has no executable mode bits")
def test_an_executable_asset_remains_executable_after_it_is_pinned(store, source):
    executable = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    source.chmod(source.stat().st_mode | executable)

    bundle = store.materialize(adapter_id=ADAPTER, assets={ROLE: source})
    copy = store.asset_path(bundle.bundle_id, ROLE)

    assert copy.stat().st_mode & executable == executable


def test_no_temporary_file_is_left_behind(store, source):
    bundle = store.materialize(adapter_id=ADAPTER, assets={ROLE: source})
    assert list(store.assets_dir(bundle.bundle_id).glob("*.tmp")) == []


def test_the_manifest_is_written_only_after_the_assets(store, source, monkeypatch):
    """A crash mid-copy leaves a visibly unfinished directory, not a lie."""
    from fpbench.storage import runtime_bundle_store as module

    def explode(*args, **kwargs):
        raise OSError("the disk went away")

    monkeypatch.setattr(module.RuntimeBundleStore, "_copy_verified", explode)
    with pytest.raises(OSError):
        store.materialize(adapter_id=ADAPTER, assets={ROLE: source})

    written = list(store.bundles_root.glob("*")) if store.bundles_root.is_dir() else []
    assert all(not (path / "bundle.json").is_file() for path in written)
    assert store.bundle_ids() == ()


def test_a_source_symlink_is_refused(store, source, tmp_path):
    link = tmp_path / "link.jar"
    try:
        link.symlink_to(source)
    except (OSError, NotImplementedError):
        pytest.skip("this platform will not create symlinks for this user")
    with pytest.raises(StorageError, match="symlink"):
        store.materialize(adapter_id=ADAPTER, assets={ROLE: link})


def test_a_source_directory_is_refused(store, tmp_path):
    directory = tmp_path / "target"
    directory.mkdir()
    with pytest.raises(StorageError, match="not a regular file"):
        store.materialize(adapter_id=ADAPTER, assets={ROLE: directory})


def test_a_missing_source_is_refused(store, tmp_path):
    with pytest.raises(StorageError, match="does not exist"):
        store.materialize(adapter_id=ADAPTER, assets={ROLE: tmp_path / "absent.jar"})


def test_a_bundle_with_no_assets_is_refused(store):
    with pytest.raises(StorageError, match="at least one asset"):
        store.materialize(adapter_id=ADAPTER, assets={})


# -------------------------------------------------------------- round trip


def test_a_bundle_round_trips_through_json(store, source):
    written = store.materialize(adapter_id=ADAPTER, assets={ROLE: source})
    read = store.read_bundle(written.bundle_id)
    assert read == written


def test_the_manifest_holds_no_absolute_path(store, source):
    bundle = store.materialize(adapter_id=ADAPTER, assets={ROLE: source})
    text = store.bundle_manifest_path(bundle.bundle_id).read_text(encoding="utf-8")
    assert str(source) not in text
    assert str(source.parent) not in text
    assert bundle.asset(ROLE).relative_path == "assets/fpbench-sourceafis-bridge.jar"


def test_the_media_type_is_recorded_for_a_jar(store, source):
    bundle = store.materialize(adapter_id=ADAPTER, assets={ROLE: source})
    assert bundle.asset(ROLE).media_type == "application/java-archive"


# ---------------------------------------------------------------- conflict


def test_a_conflicting_bundle_is_refused(store, source):
    """Forge a bundle whose stored bytes are not the ones it names."""
    bundle = store.materialize(adapter_id=ADAPTER, assets={ROLE: source})
    _unlock(store.asset_path(bundle.bundle_id, ROLE)).write_bytes(b"different")
    with pytest.raises(RuntimeBundleConflictError, match="no longer intact"):
        store.materialize(adapter_id=ADAPTER, assets={ROLE: source})


def test_ensuring_an_intact_bundle_again_is_a_no_op(store, source):
    first = store.materialize(adapter_id=ADAPTER, assets={ROLE: source})
    manifest = store.bundle_manifest_path(first.bundle_id)
    before = manifest.read_bytes()
    store.materialize(adapter_id=ADAPTER, assets={ROLE: source})
    assert manifest.read_bytes() == before


# ------------------------------------------------------------------ verify


def test_an_intact_bundle_verifies(store, source):
    bundle = store.materialize(adapter_id=ADAPTER, assets={ROLE: source})
    verification = store.verify_bundle(bundle.bundle_id)
    assert verification.is_valid
    assert verification.verified_assets == 1
    assert verification.issues == ()


def test_a_modified_asset_is_detected(store, source):
    bundle = store.materialize(adapter_id=ADAPTER, assets={ROLE: source})
    copy = _unlock(store.asset_path(bundle.bundle_id, ROLE))
    payload = bytearray(copy.read_bytes())
    payload[0] ^= 0xFF
    copy.write_bytes(bytes(payload))

    verification = store.verify_bundle(bundle.bundle_id)
    assert not verification.is_valid
    assert "hashes to" in verification.issues[0]


def test_a_truncated_asset_is_detected(store, source):
    bundle = store.materialize(adapter_id=ADAPTER, assets={ROLE: source})
    copy = _unlock(store.asset_path(bundle.bundle_id, ROLE))
    copy.write_bytes(copy.read_bytes()[:-16])

    verification = store.verify_bundle(bundle.bundle_id)
    assert not verification.is_valid
    assert "bytes, expected" in verification.issues[0]


def test_a_replaced_asset_of_the_same_size_is_detected(store, source):
    bundle = store.materialize(adapter_id=ADAPTER, assets={ROLE: source})
    copy = _unlock(store.asset_path(bundle.bundle_id, ROLE))
    copy.write_bytes(b"X" * copy.stat().st_size)

    verification = store.verify_bundle(bundle.bundle_id)
    assert not verification.is_valid


def test_a_missing_asset_is_detected(store, source):
    bundle = store.materialize(adapter_id=ADAPTER, assets={ROLE: source})
    _unlock(store.asset_path(bundle.bundle_id, ROLE)).unlink()

    verification = store.verify_bundle(bundle.bundle_id)
    assert not verification.is_valid
    assert "missing" in verification.issues[0]


def test_require_valid_raises_on_a_damaged_bundle(store, source):
    bundle = store.materialize(adapter_id=ADAPTER, assets={ROLE: source})
    _unlock(store.asset_path(bundle.bundle_id, ROLE)).unlink()
    with pytest.raises(RuntimeBundleConflictError):
        store.require_valid(bundle.bundle_id)


def test_reading_an_unknown_bundle_raises(store):
    with pytest.raises(StorageError, match="not found"):
        store.read_bundle("runtime_000000000000")
