"""A set that is more than one file is claimed before any of it is written.

The five manifest+body stores all published in the same order: check whether
the manifest is there, write the body, then publish the manifest
create-if-absent. Two writers with different content both passed the check, both
*replaced* the body, and then one published the manifest and the other was
refused. What survived was one writer's manifest standing over the other
writer's rows — and the manifest's own fingerprint said nothing was wrong,
because it described rows that were no longer on disk.

:mod:`fpbench.storage.set_publication` inverts it: the manifest is the claim, it
goes first, and only its owner writes the body. These are the cases that
inversion has to get right, including the one it creates — a crash between the
manifest and the body.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from fpbench.storage.set_publication import SetClaim, publish_set


@dataclass(frozen=True, slots=True)
class _Manifest:
    """The smallest thing a store publishes: an id and a fingerprint."""

    set_id: str
    fingerprint: str


def _claim(tmp_path: Path, manifest: _Manifest) -> SetClaim:
    manifest_path = tmp_path / "manifest.json"

    def stored() -> str:
        return str(json.loads(manifest_path.read_text(encoding="utf-8"))["fingerprint"])

    return publish_set(
        manifest_path=manifest_path,
        manifest=manifest,
        body_path=tmp_path / "entries.parquet",
        stored_fingerprint=stored,
        fingerprint=manifest.fingerprint,
    )


def _write_body(tmp_path: Path, payload: bytes) -> None:
    (tmp_path / "entries.parquet").write_bytes(payload)


def test_the_first_writer_owns_the_set_and_writes_the_body(tmp_path: Path) -> None:
    claim = _claim(tmp_path, _Manifest("set_a", "a" * 64))
    assert claim == SetClaim(owned=True, write_body=True, already_published=False)
    assert (tmp_path / "manifest.json").is_file()


def test_a_second_writer_of_the_same_set_does_not_rewrite_the_body(
    tmp_path: Path,
) -> None:
    """Idempotent re-publication, which every store's caller relies on."""
    manifest = _Manifest("set_a", "a" * 64)
    assert _claim(tmp_path, manifest).write_body is True
    _write_body(tmp_path, b"rows")

    again = _claim(tmp_path, manifest)
    assert again == SetClaim(owned=False, write_body=False, already_published=True)
    assert (tmp_path / "entries.parquet").read_bytes() == b"rows"


def test_a_publication_that_stopped_half_way_is_finished_not_refused(
    tmp_path: Path,
) -> None:
    """The failure mode the inversion creates, handled rather than inherited.

    Manifest first means a crash before the body leaves a set whose manifest is
    present and whose rows are missing. That is recoverable precisely because
    the fingerprint determines the rows: writing them is finishing the
    publication, not guessing at it.
    """
    manifest = _Manifest("set_a", "a" * 64)
    assert _claim(tmp_path, manifest).write_body is True
    # ...and then the process died, before entries.parquet existed.

    resumed = _claim(tmp_path, manifest)
    assert resumed == SetClaim(owned=False, write_body=True, already_published=True)


def test_a_different_set_never_writes_the_body(tmp_path: Path) -> None:
    """The refusal the whole module exists for.

    The second writer disagrees about the content. It does not own the set, and
    — the part that used to be wrong — it does not touch the body either. The
    caller raises its own conflict from the comparison this returns.
    """
    assert _claim(tmp_path, _Manifest("set_a", "a" * 64)).write_body is True
    _write_body(tmp_path, b"rows from A")

    intruder = _claim(tmp_path, _Manifest("set_b", "b" * 64))
    assert intruder == SetClaim(owned=False, write_body=False, already_published=True)
    assert (tmp_path / "entries.parquet").read_bytes() == b"rows from A"

    stored = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert stored["set_id"] == "set_a"


def test_a_different_set_is_refused_even_before_its_body_exists(
    tmp_path: Path,
) -> None:
    """The half-published set is not an opening for somebody else's rows.

    ``write_body`` is true for a resumed publication only when the fingerprints
    match. A second writer arriving at the same gap with different content must
    not be handed the empty body slot.
    """
    assert _claim(tmp_path, _Manifest("set_a", "a" * 64)).write_body is True

    intruder = _claim(tmp_path, _Manifest("set_b", "b" * 64))
    assert intruder.write_body is False
    assert not (tmp_path / "entries.parquet").exists()


def test_an_already_published_manifest_is_never_re_rendered(tmp_path: Path) -> None:
    """The stored manifest decides, so the caller's object is not serialised.

    A store reaching this path holds whatever it was handed — including, in one
    of the conflict tests, an object built field by field to reach a state the
    real model refuses. Rendering it to compare would fail on the encoder
    instead of on the fingerprint, which is the wrong error for the wrong
    reason.
    """

    class _Unserialisable:
        fingerprint = "b" * 64

    assert _claim(tmp_path, _Manifest("set_a", "a" * 64)).owned is True

    manifest_path = tmp_path / "manifest.json"
    claim = publish_set(
        manifest_path=manifest_path,
        manifest=_Unserialisable(),
        body_path=tmp_path / "entries.parquet",
        stored_fingerprint=lambda: "a" * 64,
        fingerprint="b" * 64,
    )
    assert claim == SetClaim(owned=False, write_body=False, already_published=True)


def test_an_unreadable_stored_manifest_is_the_callers_error(tmp_path: Path) -> None:
    """Not swallowed into "somebody else has it".

    ``stored_fingerprint`` is the caller's reader. If the published manifest
    cannot be read, that is a corrupt set and the caller's exception is the
    right one to see.
    """
    (tmp_path / "manifest.json").write_text("not json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        _claim(tmp_path, _Manifest("set_a", "a" * 64))
