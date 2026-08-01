"""A bundle of several tools, and what changes its identity.

``RuntimeBundleDefinition`` was always a mapping of roles to assets, but with one
algorithm shipping one jar every test supplied exactly one role — so the plural
behaviour was designed and never exercised. A two-tool pipeline makes it
load-bearing: if replacing the matcher alone left the bundle id unchanged, a run
would go on claiming a runtime it no longer had (docs/adr/0042, spec section 63).

Every property below is about *identity*, which is the thing a receipt cites and
a later reader re-checks.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fpbench.core.errors import RuntimeBundleConflictError, StorageError
from fpbench.core.runtime_models import (
    RuntimeAssetDefinition,
    RuntimeBundleDefinition,
    runtime_bundle_fingerprint,
)
from fpbench.storage.runtime_bundle_store import RuntimeBundleStore

pytestmark = pytest.mark.adapter_contract

ADAPTER_ID = "two_tool_adapter"

ROLES = {
    "tool_extractor": b"extractor bytes",
    "tool_matcher": b"matcher bytes",
    "tool_support_data": b"support bytes",
}


@pytest.fixture
def store(tmp_path: Path) -> RuntimeBundleStore:
    return RuntimeBundleStore(tmp_path / "workspace")


@pytest.fixture
def sources(tmp_path: Path) -> dict[str, Path]:
    build = tmp_path / "build"
    build.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for role, payload in ROLES.items():
        path = build / f"{role}.bin"
        path.write_bytes(payload)
        paths[role] = path
    return paths


def materialize(store: RuntimeBundleStore, assets: dict[str, Path]):
    return store.materialize(adapter_id=ADAPTER_ID, assets=assets)


# ------------------------------------------------------------- what it covers


def test_all_three_files_are_in_the_bundle(store, sources):
    bundle = materialize(store, sources)
    assert {asset.role for asset in bundle.assets} == set(ROLES)
    assert len(bundle.asset_sha256s()) == 3


def test_every_asset_is_copied_and_verifiable(store, sources):
    bundle = materialize(store, sources)
    for role, payload in ROLES.items():
        path = store.asset_path(bundle.bundle_id, role)
        assert path.read_bytes() == payload
    assert store.verify_bundle(bundle.bundle_id).verified_assets == 3


@pytest.mark.parametrize("role", sorted(ROLES))
def test_changing_any_one_file_changes_the_bundle_id(store, sources, role, tmp_path):
    """The failure this whole ADR exists for: a rebuilt matcher must be noticed."""
    before = materialize(store, sources).bundle_id

    rebuilt = tmp_path / "build2"
    rebuilt.mkdir()
    changed = dict(sources)
    replacement = rebuilt / f"{role}.bin"
    replacement.write_bytes(ROLES[role] + b" rebuilt")
    changed[role] = replacement

    assert materialize(store, changed).bundle_id != before


def test_changing_a_role_name_changes_the_bundle_id(store, sources):
    before = materialize(store, sources).bundle_id
    renamed = dict(sources)
    renamed["tool_second_matcher"] = renamed.pop("tool_matcher")
    assert materialize(store, renamed).bundle_id != before


def test_changing_a_filename_changes_the_bundle_id(store, sources, tmp_path):
    """The name is part of the identity: a tool invoked by name is a dependency."""
    before = materialize(store, sources).bundle_id
    renamed_directory = tmp_path / "build3"
    renamed_directory.mkdir()
    renamed = dict(sources)
    target = renamed_directory / "matcher-v2.bin"
    target.write_bytes(ROLES["tool_matcher"])
    renamed["tool_matcher"] = target
    assert materialize(store, renamed).bundle_id != before


def test_the_order_of_the_mapping_does_not_change_the_bundle_id(store, sources):
    """A dict is ordered in Python; a runtime is not."""
    forward = materialize(store, dict(sorted(sources.items())))
    backward = materialize(store, dict(sorted(sources.items(), reverse=True)))
    assert forward.bundle_id == backward.bundle_id
    assert forward.bundle_fingerprint == backward.bundle_fingerprint


def test_the_fingerprint_covers_every_asset(store, sources):
    bundle = materialize(store, sources)
    recomputed = runtime_bundle_fingerprint(
        adapter_id=ADAPTER_ID,
        materialization_policy=bundle.materialization_policy,
        assets=bundle.assets,
    )
    assert recomputed == bundle.bundle_fingerprint

    without_one = [a for a in bundle.assets if a.role != "tool_support_data"]
    assert (
        runtime_bundle_fingerprint(
            adapter_id=ADAPTER_ID,
            materialization_policy=bundle.materialization_policy,
            assets=without_one,
        )
        != bundle.bundle_fingerprint
    )


# ------------------------------------------------------------- what it refuses


def test_a_duplicate_role_cannot_exist_in_a_bundle():
    """A mapping cannot express it; the model refuses it anyway."""
    import hashlib

    asset = RuntimeAssetDefinition.create(
        role="tool_matcher",
        filename="matcher.bin",
        sha256=hashlib.sha256(b"a").hexdigest(),
        size_bytes=1,
        media_type="application/octet-stream",
    )
    with pytest.raises(ValueError, match="each role appears at most once"):
        RuntimeBundleDefinition.create(
            adapter_id=ADAPTER_ID,
            materialization_policy="content_addressed_copy_v1",
            assets=(asset, asset),
            created_utc="2026-08-01T00:00:00+00:00",
        )


def test_two_roles_cannot_occupy_one_path():
    import hashlib

    first = RuntimeAssetDefinition.create(
        role="tool_extractor",
        filename="shared.bin",
        sha256=hashlib.sha256(b"a").hexdigest(),
        size_bytes=1,
        media_type="application/octet-stream",
    )
    second = RuntimeAssetDefinition.create(
        role="tool_matcher",
        filename="shared.bin",
        sha256=hashlib.sha256(b"b").hexdigest(),
        size_bytes=1,
        media_type="application/octet-stream",
    )
    with pytest.raises(ValueError, match="two assets cannot occupy one path"):
        RuntimeBundleDefinition.create(
            adapter_id=ADAPTER_ID,
            materialization_policy="content_addressed_copy_v1",
            assets=(first, second),
            created_utc="2026-08-01T00:00:00+00:00",
        )


def test_one_missing_file_refuses_the_whole_bundle(store, sources, tmp_path):
    """Two of three tools pinned is not a pinned runtime."""
    incomplete = dict(sources)
    incomplete["tool_support_data"] = tmp_path / "build" / "absent.bin"
    with pytest.raises(StorageError, match="does not exist"):
        materialize(store, incomplete)


def test_one_symlinked_file_refuses_the_whole_bundle(store, sources, tmp_path):
    elsewhere = tmp_path / "elsewhere.bin"
    elsewhere.write_bytes(b"matcher bytes")
    link = tmp_path / "build" / "linked-matcher.bin"
    try:
        link.symlink_to(elsewhere)
    except (OSError, NotImplementedError):  # pragma: no cover - needs privilege
        pytest.skip("this platform will not create symlinks without privileges")
    linked = dict(sources)
    linked["tool_matcher"] = link
    with pytest.raises(StorageError, match="symlink"):
        materialize(store, linked)


def test_no_asset_is_hardlinked_to_its_source(store, sources):
    """A hardlink would let a rebuild rewrite the "immutable" copy in place."""
    bundle = materialize(store, sources)
    for role, source in sources.items():
        copied = store.asset_path(bundle.bundle_id, role)
        assert copied.stat().st_ino != source.stat().st_ino or (
            copied.stat().st_ino == 0  # filesystems that report no inode
        )


def test_a_tampered_bundle_is_reported_rather_than_repaired(store, sources):
    import stat as stat_module

    bundle = materialize(store, sources)
    victim = store.asset_path(bundle.bundle_id, "tool_matcher")
    victim.chmod(victim.stat().st_mode | stat_module.S_IWUSR)
    victim.write_bytes(b"tampered bytes")

    verification = store.verify_bundle(bundle.bundle_id)
    assert not verification.is_valid
    assert verification.verified_assets == 2
    with pytest.raises(RuntimeBundleConflictError):
        store.require_valid(bundle.bundle_id)
