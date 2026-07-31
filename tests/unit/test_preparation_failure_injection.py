"""A crash at any write leaves work that can be resumed, and never a marker.

The property is the same one stage 4B established for a research run, applied one
layer down: everything before the finalization marker is idempotent and
retryable, and only a marker matching the freshly revalidated chain makes any of
it authoritative (docs/adr/0020).

Each test injects a failure immediately after one write, then asserts three
things: no marker exists, the status is not ``PREPARATION_READY``, and running
the same command again under the same runtime finishes the job. The last is the
one that matters operationally — a 3,000-image materialisation that had to start
over after every interruption would be unusable.
"""

from __future__ import annotations

import pytest

from fpbench.core.enums import PreparationStatus
from fpbench.imaging.status import inspect_preparation
from fpbench.storage.prepared_image_set_store import PreparedImageSetStore
from canonicalworld import build_canonical_world, publish_receipt_and_marker

pytestmark = [pytest.mark.imaging, pytest.mark.canonical500]


class _Boom(RuntimeError):
    """An injected failure, distinguishable from a real one."""


def _fail_after(original, when=1):
    calls = {"count": 0}

    def wrapped(*args, **kwargs):
        result = original(*args, **kwargs)
        calls["count"] += 1
        if calls["count"] == when:
            raise _Boom("injected failure")
        return result

    return wrapped


def _status(world):
    return inspect_preparation(
        store=world.store,
        definition=world.definition,
        images=world.images,
        dataset_root=world.dataset_root,
    )


# ------------------------------------------------- interruption during writing


@pytest.mark.parametrize("write_step", ["profile", "runtime", "definition"])
def test_a_failure_before_any_image_leaves_nothing_authoritative(
    tmp_path, monkeypatch, write_step
):
    """The three files ``prepare`` writes, each interrupted in turn."""
    store = PreparedImageSetStore(tmp_path / "workspace")
    method = {
        "profile": "ensure_transform_profile",
        "runtime": "ensure_runtime",
        "definition": "ensure_definition",
    }[write_step]
    monkeypatch.setattr(
        PreparedImageSetStore, method, _fail_after(getattr(store, method).__func__)
    )
    with pytest.raises(_Boom):
        build_canonical_world(tmp_path, subjects=1, fingers=(1,))

    assert not list((tmp_path / "workspace" / "prepared-images").glob("prepset_*"))


def test_a_failure_after_the_first_image_is_resumable(tmp_path, monkeypatch):
    original = PreparedImageSetStore.ensure_image
    monkeypatch.setattr(PreparedImageSetStore, "ensure_image", _fail_after(original))
    with pytest.raises(_Boom):
        build_canonical_world(tmp_path, subjects=1, fingers=(1,))
    monkeypatch.undo()

    # The same world again, this time uninterrupted. The already-written image is
    # a verified no-op rather than a rewrite.
    world = build_canonical_world(tmp_path, subjects=1, fingers=(1,))
    assert world.store.verify_set(world.preparation_set_id)


def test_a_failure_after_an_entry_write_is_resumable(tmp_path, monkeypatch):
    original = PreparedImageSetStore.ensure_entry
    monkeypatch.setattr(PreparedImageSetStore, "ensure_entry", _fail_after(original, 2))
    with pytest.raises(_Boom):
        build_canonical_world(tmp_path, subjects=1, fingers=(1,))
    monkeypatch.undo()

    world = build_canonical_world(tmp_path, subjects=1, fingers=(1,))
    assert world.store.verify_set(world.preparation_set_id)


def test_a_failure_after_the_entries_table_leaves_no_manifest(tmp_path, monkeypatch):
    original = PreparedImageSetStore.ensure_entries_table
    monkeypatch.setattr(
        PreparedImageSetStore, "ensure_entries_table", _fail_after(original)
    )
    with pytest.raises(_Boom):
        build_canonical_world(tmp_path, subjects=1, fingers=(1,))
    monkeypatch.undo()

    world = build_canonical_world(tmp_path, subjects=1, fingers=(1,), finalise=False)
    assert not world.store.has_manifest(world.preparation_set_id)
    assert _status(world).status is PreparationStatus.IMAGES_COMPLETE


def test_a_failure_after_the_manifest_leaves_no_receipt(tmp_path, monkeypatch):
    world = build_canonical_world(tmp_path, subjects=1, fingers=(1,))
    assert world.store.has_manifest(world.preparation_set_id)
    assert not world.store.has_receipt(world.preparation_set_id)

    state = _status(world)
    assert state.status is PreparationStatus.VERIFIED
    assert any("receipt" in issue for issue in state.issues)


def test_a_failure_after_the_summary_leaves_no_marker(tmp_path, monkeypatch):
    world = build_canonical_world(tmp_path, subjects=1, fingers=(1,))
    original = PreparedImageSetStore.ensure_summary
    monkeypatch.setattr(PreparedImageSetStore, "ensure_summary", _fail_after(original))
    with pytest.raises(_Boom):
        publish_receipt_and_marker(world)
    monkeypatch.undo()

    assert not world.store.has_finalization(world.preparation_set_id)
    assert _status(world).status is not PreparationStatus.PREPARATION_READY

    publish_receipt_and_marker(world)
    assert _status(world).status is PreparationStatus.PREPARATION_READY


def test_a_failure_after_the_receipt_leaves_no_marker(tmp_path, monkeypatch):
    world = build_canonical_world(tmp_path, subjects=1, fingers=(1,))
    original = PreparedImageSetStore.ensure_receipt
    monkeypatch.setattr(PreparedImageSetStore, "ensure_receipt", _fail_after(original))
    with pytest.raises(_Boom):
        publish_receipt_and_marker(world)
    monkeypatch.undo()

    assert world.store.has_receipt(world.preparation_set_id)
    assert not world.store.has_finalization(world.preparation_set_id)
    assert _status(world).status is PreparationStatus.VERIFIED

    publish_receipt_and_marker(world)
    assert _status(world).status is PreparationStatus.PREPARATION_READY


def test_re_publishing_an_identical_chain_is_a_no_op(tmp_path):
    world = build_canonical_world(tmp_path, subjects=1, fingers=(1,))
    publish_receipt_and_marker(world)
    first = world.store.read_finalization(world.preparation_set_id)

    publish_receipt_and_marker(world)
    second = world.store.read_finalization(world.preparation_set_id)
    assert second.finalization_fingerprint == first.finalization_fingerprint


# ---------------------------------------------------------------- resumability


def test_an_existing_entry_is_verified_before_it_is_reused(tmp_path):
    """A damaged entry stops a resume; it is never quietly overwritten."""
    import stat

    from fpbench.core.errors import PreparedImageSetConflictError

    world = build_canonical_world(tmp_path, subjects=1, fingers=(1,))
    entry = world.entries[0]
    path = world.artifact_path(entry)
    path.chmod(path.stat().st_mode | stat.S_IWUSR)
    path.write_bytes(path.read_bytes()[:-3] + b"XXX")

    with pytest.raises(PreparedImageSetConflictError):
        world.store.verify_entry(entry, profile=world.profile)


def test_a_partial_materialisation_reports_partial(tmp_path):
    world = build_canonical_world(tmp_path, subjects=2, fingers=(1, 2), finalise=False)
    # Remove one entry file, as an interrupted run would have left it.
    victim = world.definition.ordered_image_ids[-1]
    world.store.entry_path(world.definition.definition_id, str(victim)).unlink()

    state = _status(world)
    assert state.status is PreparationStatus.PARTIAL
    assert state.missing_images == 1
