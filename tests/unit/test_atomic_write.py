"""The publication primitive, and the race it exists to lose loudly.

The bug this replaces was not "a file got corrupted". It was that the *loser* of
a race returned normally: a caller was told its result was stored while the
bytes on disk belonged to another writer. Every test here is about which writer
is told what.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from fpbench.core.atomic_write import (
    PublishConflictError,
    PublishOutcome,
    publish_bytes,
    publish_file,
    replace_bytes,
    unique_temp_path,
)


def test_publishing_into_an_empty_directory_creates_the_file(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "result.bin"
    published = publish_bytes(target, b"one")
    assert published.outcome is PublishOutcome.PUBLISHED
    assert published.created
    assert target.read_bytes() == b"one"


def test_a_second_writer_of_identical_bytes_is_told_it_lost(tmp_path: Path) -> None:
    target = tmp_path / "result.bin"
    publish_bytes(target, b"same")
    second = publish_bytes(target, b"same")
    assert second.outcome is PublishOutcome.ALREADY_IDENTICAL
    assert not second.created
    assert target.read_bytes() == b"same"


def test_a_second_writer_of_different_bytes_is_refused(tmp_path: Path) -> None:
    target = tmp_path / "result.bin"
    publish_bytes(target, b"first")
    with pytest.raises(PublishConflictError):
        publish_bytes(target, b"second")
    assert target.read_bytes() == b"first", "the winner's bytes must survive"


def test_the_temp_file_is_removed_whether_or_not_the_write_won(
    tmp_path: Path,
) -> None:
    target = tmp_path / "result.bin"
    publish_bytes(target, b"first")
    with pytest.raises(PublishConflictError):
        publish_bytes(target, b"second")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["result.bin"]


def test_a_failing_producer_leaves_no_target_and_no_temp(tmp_path: Path) -> None:
    target = tmp_path / "result.bin"

    def explode(_: Path) -> None:
        raise RuntimeError("the producer failed")

    with pytest.raises(RuntimeError):
        publish_file(target, explode)
    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


def test_two_writers_do_not_share_a_temp_name(tmp_path: Path) -> None:
    """The fixed ``<name>.tmp`` is what let two writers corrupt one scratch file."""
    target = tmp_path / "result.bin"
    names = {unique_temp_path(target).name for _ in range(200)}
    assert len(names) == 200
    assert all(name != "result.bin.tmp" for name in names)


def test_the_temp_name_stays_short_enough_for_windows(tmp_path: Path) -> None:
    """A deep workspace path plus a long temp name is an unopenable file.

    Windows enforces 260 characters on these APIs, and the workspace layout
    reaches into the 230s on its own.
    """
    for name in ("manifest.json", "entries.parquet", "x.md", "a" * 80):
        assert len(unique_temp_path(tmp_path / name).name) == 17


def test_exactly_one_of_many_concurrent_writers_wins(tmp_path: Path) -> None:
    """The reproduction from the audit, run for real.

    Under the old write-temp-then-replace, several writers reported success and
    the file held whichever bytes landed last.
    """
    target = tmp_path / "contended.bin"
    writers = 16

    def attempt(index: int) -> str:
        try:
            published = publish_bytes(target, f"writer-{index}".encode())
        except PublishConflictError:
            return "refused"
        return published.outcome.value

    with ThreadPoolExecutor(max_workers=writers) as pool:
        outcomes = list(pool.map(attempt, range(writers)))

    assert outcomes.count(PublishOutcome.PUBLISHED.value) == 1, outcomes
    assert outcomes.count("refused") == writers - 1, outcomes

    winner = target.read_bytes().decode()
    assert winner.startswith("writer-")


def test_the_winners_bytes_are_the_bytes_on_disk(tmp_path: Path) -> None:
    """No writer may report success over content it did not store."""
    target = tmp_path / "contended.bin"
    reported: list[tuple[bool, bytes]] = []

    def attempt(index: int) -> None:
        payload = f"writer-{index}".encode()
        try:
            published = publish_bytes(target, payload)
        except PublishConflictError:
            return
        reported.append((published.created, payload))

    with ThreadPoolExecutor(max_workers=12) as pool:
        list(pool.map(attempt, range(12)))

    successes = [payload for created, payload in reported if created]
    assert len(successes) == 1
    assert target.read_bytes() == successes[0]


def test_replace_overwrites_and_is_still_atomic(tmp_path: Path) -> None:
    target = tmp_path / "regenerated.json"
    replace_bytes(target, b"first")
    replace_bytes(target, b"second")
    assert target.read_bytes() == b"second"
    assert list(tmp_path.iterdir()) == [target]


def test_publish_survives_a_filesystem_without_hard_links(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FAT, exFAT and some network mounts have no ``os.link``.

    The ``O_EXCL`` fallback is weaker — a reader can see a partial file — but it
    still lets exactly one writer claim the name, which is the property the
    existence check never had.
    """

    def no_links(*_: object, **__: object) -> None:
        raise OSError("hard links are not supported here")

    monkeypatch.setattr(os, "link", no_links)

    target = tmp_path / "result.bin"
    assert publish_bytes(target, b"first").created
    assert not publish_bytes(target, b"first").created
    with pytest.raises(PublishConflictError):
        publish_bytes(target, b"second")
    assert target.read_bytes() == b"first"


# ------------------------------------------------- the no-hard-link fallback


def _without_hard_links(monkeypatch: pytest.MonkeyPatch) -> None:
    """Emulate FAT, exFAT and the network mounts that have no ``os.link``."""

    def refuse(*_: object, **__: object) -> None:
        raise OSError("hard links are not supported here")

    monkeypatch.setattr(os, "link", refuse)


def test_the_fallback_never_leaves_a_partial_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reviewer's reproduction: a failed copy left a target holding ``com``.

    The old fallback created the *final* path with ``O_EXCL`` and copied into
    it, so an interrupted copy published a prefix. Content now arrives by
    ``os.replace``, which is atomic: the target is absent or complete.
    """
    _without_hard_links(monkeypatch)
    target = tmp_path / "result.bin"

    def fails_halfway(temporary: Path) -> None:
        temporary.write_bytes(b"com")
        raise OSError("the copy was interrupted")

    with pytest.raises(OSError, match="interrupted"):
        publish_file(target, fails_halfway)

    assert not target.exists(), "a failed publication must leave no target"
    assert list(tmp_path.iterdir()) == [], "and no scratch or claim behind"


def test_the_fallback_refuses_to_overwrite_a_published_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``os.replace`` clobbers; the claim is what stops it doing so."""
    _without_hard_links(monkeypatch)
    target = tmp_path / "result.bin"

    assert publish_bytes(target, b"first").created
    with pytest.raises(PublishConflictError):
        publish_bytes(target, b"second")
    assert target.read_bytes() == b"first"


def test_exactly_one_fallback_writer_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _without_hard_links(monkeypatch)
    target = tmp_path / "contended.bin"

    def attempt(index: int) -> str:
        try:
            return publish_bytes(target, f"writer-{index}".encode()).outcome.value
        except PublishConflictError:
            return "refused"

    with ThreadPoolExecutor(max_workers=12) as pool:
        outcomes = list(pool.map(attempt, range(12)))

    assert outcomes.count(PublishOutcome.PUBLISHED.value) == 1, outcomes
    assert target.read_bytes().decode().startswith("writer-")
    assert not list(tmp_path.glob("*.publishing")), "no claim may survive"


def test_a_stale_claim_is_reported_rather_than_resolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A writer that died mid-publication is a stuck store, not a free name.

    Guessing — deleting somebody else's claim — is how two writers end up
    publishing at once on the one filesystem that cannot serialise them.
    """
    import fpbench.core.atomic_write as atomic

    _without_hard_links(monkeypatch)
    monkeypatch.setattr(atomic, "_CLAIM_TIMEOUT_SECONDS", 0.05)
    target = tmp_path / "result.bin"
    atomic._claim_path(target).write_bytes(b"")

    with pytest.raises(PublishConflictError, match="did not finish"):
        publish_bytes(target, b"payload")
    assert not target.exists()


def test_a_claim_handed_back_by_a_failed_writer_is_reusable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other half: a claim released without a target frees the name."""
    _without_hard_links(monkeypatch)
    target = tmp_path / "result.bin"

    def fails(temporary: Path) -> None:
        temporary.write_bytes(b"partial")
        raise OSError("interrupted")

    with pytest.raises(OSError):
        publish_file(target, fails)

    assert publish_bytes(target, b"complete").created
    assert target.read_bytes() == b"complete"
