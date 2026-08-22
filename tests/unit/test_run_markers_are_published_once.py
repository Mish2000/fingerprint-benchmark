"""A run marker is written by the filesystem's decision, not by a check.

Four ``ResultStore.ensure_*`` methods guarded an immutable marker the same way::

    if path.is_file():
        <compare what is stored against what I hold>
        return path
    return write_json(path, mine)          # <- replaces

The guard is correct and the write is not. Two publishers that both find the
path absent both pass the check and both write; ``write_json`` replaces, so the
second silently overwrites the first, and the run ends up declaring whichever
one happened to finish last. The completion marker is the record that a run was
audited and found sound — it is the last thing that may be decided by timing.

The claim is now the publication itself: create-if-absent, and a caller that
loses re-reads and compares. These tests drive it from several threads, because
the defect only exists between two operations.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from fpbench.core.errors import ResultConflictError
from fpbench.core.run_state_models import RunCompletion
from fpbench.storage.result_store import ResultStore

RUN_ID = "run_abc123abc123"


def _completion(fingerprint: str, *, success: int = 10) -> RunCompletion:
    return RunCompletion(
        completion_id="completion_abc123abc123",
        completion_fingerprint=fingerprint,
        run_id=RUN_ID,
        run_fingerprint="b" * 64,
        plan_id="plan_abc123abc123",
        plan_fingerprint="c" * 64,
        pair_manifest_hash="d" * 64,
        audit_fingerprint="e" * 64,
        planned_jobs=10,
        success_count=success,
        failure_count=10 - success,
        completed_utc="2026-07-30T00:00:00+00:00",
    )


def _store(tmp_path: Path) -> ResultStore:
    store = ResultStore(tmp_path)
    store.run_dir(RUN_ID).mkdir(parents=True, exist_ok=True)
    return store


def test_the_first_completion_is_the_one_that_stands(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.ensure_completion(_completion("a" * 64))
    with pytest.raises(ResultConflictError, match="already declares completion"):
        store.ensure_completion(_completion("f" * 64, success=7))
    assert store.read_completion(RUN_ID).completion_fingerprint == "a" * 64


def test_re_declaring_the_same_completion_is_a_no_op(tmp_path: Path) -> None:
    """Idempotence, which every resumable finaliser relies on."""
    store = _store(tmp_path)
    first = store.ensure_completion(_completion("a" * 64))
    again = store.ensure_completion(_completion("a" * 64))
    assert first == again
    assert store.read_completion(RUN_ID).completion_fingerprint == "a" * 64


def test_two_threads_declaring_different_completions_cannot_both_win(
    tmp_path: Path,
) -> None:
    """The race, run for real.

    Both threads reach a directory with no completion marker. Exactly one may
    store its own; the other must be told, not silently replaced. The assertion
    that matters is the last one: whatever is on disk is what the winner wrote,
    in full — not one writer's marker with another writer's counts.
    """
    store = _store(tmp_path)
    start = threading.Barrier(2)
    outcomes: dict[str, object] = {}

    def publish(name: str, fingerprint: str, success: int) -> None:
        start.wait()
        try:
            store.ensure_completion(_completion(fingerprint, success=success))
            outcomes[name] = "stored"
        except ResultConflictError:
            outcomes[name] = "refused"

    threads = [
        threading.Thread(target=publish, args=("a", "a" * 64, 10)),
        threading.Thread(target=publish, args=("b", "f" * 64, 7)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(outcomes.values()) == ["refused", "stored"], outcomes
    stored = store.read_completion(RUN_ID)
    winner = "a" if outcomes["a"] == "stored" else "b"
    assert stored.completion_fingerprint == ("a" * 64 if winner == "a" else "f" * 64)
    assert stored.success_count == (10 if winner == "a" else 7)


def test_the_stored_marker_is_never_a_blend_of_two_writers(tmp_path: Path) -> None:
    """Ten writers, one marker, and it is one writer's marker.

    ``success_count`` and ``completion_fingerprint`` come from the same object,
    so a document carrying one writer's fingerprint over another's counts is
    detectable — and was exactly what a replacing write could produce.
    """
    store = _store(tmp_path)
    start = threading.Barrier(10)
    refused = 0
    lock = threading.Lock()

    def publish(index: int) -> None:
        nonlocal refused
        start.wait()
        try:
            store.ensure_completion(
                _completion(str(index) * 64, success=index)
            )
        except ResultConflictError:
            with lock:
                refused += 1

    threads = [threading.Thread(target=publish, args=(i,)) for i in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert refused == 9
    stored = store.read_completion(RUN_ID)
    assert stored.completion_fingerprint == str(stored.success_count) * 64
