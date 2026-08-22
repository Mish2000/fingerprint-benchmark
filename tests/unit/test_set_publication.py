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
        body_paths=(tmp_path / "entries.parquet",),
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
        body_paths=(tmp_path / "entries.parquet",),
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


# ------------------------------------------ a set is every file it is made of


def _multi(tmp_path: Path, manifest: _Manifest, names: tuple[str, ...]) -> SetClaim:
    manifest_path = tmp_path / "manifest.json"

    def stored() -> str:
        return str(json.loads(manifest_path.read_text(encoding="utf-8"))["fingerprint"])

    return publish_set(
        manifest_path=manifest_path,
        manifest=manifest,
        body_paths=tuple(tmp_path / name for name in names),
        stored_fingerprint=stored,
        fingerprint=manifest.fingerprint,
    )


#: A metric set: a definition, a policy, a report profile, the counts and the
#: observations. Six files with the manifest, and the crash below lands between
#: the fourth and the fifth.
_METRIC_SET = (
    "definition.json",
    "policy.json",
    "report-profile.json",
    "counts.parquet",
    "observations.parquet",
)


def test_a_crash_between_two_body_files_is_still_an_unfinished_set(
    tmp_path: Path,
) -> None:
    """The reviewer's case, and the reason ``body_paths`` is plural.

    ``counts.parquet`` used to stand in for the whole body. A crash after it and
    before ``observations.parquet`` left a set whose retry reported success over
    a set that cannot be read: the manifest is there, the counts are there, and
    the observations the manifest describes never arrived.
    """
    manifest = _Manifest("ms_1", "a" * 64)
    assert _multi(tmp_path, manifest, _METRIC_SET).write_body is True
    for name in _METRIC_SET[:-1]:
        (tmp_path / name).write_bytes(b"written")
    # ...and then the process died.

    resumed = _multi(tmp_path, manifest, _METRIC_SET)
    assert resumed.write_body is True, (
        "the set is missing observations.parquet and the retry called it finished"
    )


def test_a_set_whose_every_file_arrived_is_not_written_again(tmp_path: Path) -> None:
    manifest = _Manifest("ms_1", "a" * 64)
    assert _multi(tmp_path, manifest, _METRIC_SET).write_body is True
    for name in _METRIC_SET:
        (tmp_path / name).write_bytes(b"written")

    resumed = _multi(tmp_path, manifest, _METRIC_SET)
    assert resumed.write_body is False


@pytest.mark.parametrize("missing", _METRIC_SET)
def test_any_missing_file_makes_the_set_unfinished(tmp_path: Path, missing: str) -> None:
    """Not just the last one: each file is the manifest's claim as much as the rest."""
    manifest = _Manifest("ms_1", "a" * 64)
    assert _multi(tmp_path, manifest, _METRIC_SET).write_body is True
    for name in _METRIC_SET:
        if name != missing:
            (tmp_path / name).write_bytes(b"written")

    assert _multi(tmp_path, manifest, _METRIC_SET).write_body is True
