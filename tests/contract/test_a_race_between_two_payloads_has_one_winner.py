"""Two writers, one name, different content: one winner and an explicit refusal.

The static scans next door prove the *shape* — that no store checks for a
document and then replaces it, and that no body is written before the manifest
claims the set. Shape is not behaviour, and the defect these replaced was
invisible precisely because every test ran one writer at a time. So this runs
two, and pins the three outcomes that must hold:

* exactly one writer's bytes are on disk;
* the loser is *told* — a refusal, never a return that reads as success;
* nothing on disk mixes the two, and that is true of a *set* as well as a file.

**How the race is made deterministic.** ``publish_*`` writes a scratch file and
then reserves the final name, and the window between those two steps is what a
real collision falls into. Each thread is held at the top of its *first*
reservation until the others arrive, so both are inside that window together —
every run, rather than on the runs where the scheduler happened to oblige. Only
the first reservation per thread waits: a set publishes its manifest and then
several body documents, and holding every one of them would deadlock the writer
that owns the claim.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Callable

import pytest

from fpbench.core import atomic_write
from fpbench.core.enums import CohortRole
from fpbench.core.errors import ManifestExistsError, MetricSetConflictError
from fpbench.core.identifiers import CohortId, SubjectId
from fpbench.core.models import Cohort, CohortSelection
from fpbench.storage.manifest_store import ManifestStore
from fpbench.storage.metric_set_store import MetricSetStore
from fpbench.storage.set_publication import publish_set

_TIMEOUT_SECONDS = 30.0


@contextmanager
def _writers_collide(monkeypatch, parties: int = 2):
    """Hold every thread at its first name reservation until all have arrived."""
    barrier = threading.Barrier(parties, timeout=_TIMEOUT_SECONDS)
    local = threading.local()
    original = atomic_write._reserve

    def synchronised(source, target):
        if not getattr(local, "arrived", False):
            local.arrived = True
            barrier.wait()
        return original(source, target)

    monkeypatch.setattr(atomic_write, "_reserve", synchronised)
    try:
        yield
    finally:
        barrier.abort()


def _run_together(*writers: Callable[[], object]) -> list[object | BaseException]:
    """Run each writer in its own thread; return its value or the error it raised."""
    outcomes: list[object | BaseException] = [None] * len(writers)

    def attempt(index: int, writer: Callable[[], object]) -> None:
        try:
            outcomes[index] = writer()
        except BaseException as exc:  # noqa: BLE001 - the outcome under test
            outcomes[index] = exc

    threads = [
        threading.Thread(target=attempt, args=(index, writer), daemon=True)
        for index, writer in enumerate(writers)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=_TIMEOUT_SECONDS)
    assert not any(thread.is_alive() for thread in threads), "a writer never finished"
    return outcomes


def _cohort(seed: int) -> Cohort:
    """Two cohorts under one name, differing only in the seed that selected them."""
    return Cohort(
        cohort_id=CohortId("c0001"),
        protocol_id="p",
        dataset_id="sd300",
        role=CohortRole.EVALUATION,
        releases=("sd300a",),
        subject_ids=(SubjectId("s0001"),),
        selection=CohortSelection(
            seed=seed,
            size=1,
            candidate_ids=(SubjectId("s0001"),),
            criteria={"kind": "synthetic"},
            image_manifest_hashes={"sd300a": "0" * 64},
        ),
    )


# ------------------------------------------------------------------ the primitive


def test_two_different_sets_racing_for_one_manifest_leave_one_owner(
    tmp_path, monkeypatch
):
    """``publish_set`` is where a set's ownership is decided, so it is tested first."""
    manifest_path = tmp_path / "manifest.json"
    body = tmp_path / "body.parquet"

    def claim(fingerprint: str):
        return publish_set(
            manifest_path=manifest_path,
            manifest={"fingerprint": fingerprint},
            body_paths=(body,),
            stored_fingerprint=lambda: _read_fingerprint(manifest_path),
            fingerprint=fingerprint,
        )

    with _writers_collide(monkeypatch):
        outcomes = _run_together(lambda: claim("a" * 64), lambda: claim("b" * 64))

    assert not any(isinstance(outcome, BaseException) for outcome in outcomes), outcomes
    owners = [outcome for outcome in outcomes if outcome.owned]
    assert len(owners) == 1, "exactly one writer may own a set"

    loser = next(outcome for outcome in outcomes if not outcome.owned)
    assert loser.already_published
    assert not loser.write_body, (
        "the writer that lost the manifest must not write the body: that is the "
        "mixed set the claim exists to prevent"
    )


def _read_fingerprint(path) -> str:
    import json

    return json.loads(path.read_text(encoding="utf-8"))["fingerprint"]


# --------------------------------------------------------------- ManifestStore


def test_two_different_cohorts_racing_leave_one_and_a_refusal(tmp_path, monkeypatch):
    store = ManifestStore(tmp_path / "workspace")
    store.cohort_path("p", "c0001").parent.mkdir(parents=True, exist_ok=True)

    with _writers_collide(monkeypatch):
        outcomes = _run_together(
            lambda: store.write_cohort(_cohort(seed=1)),
            lambda: store.write_cohort(_cohort(seed=2)),
        )

    refusals = [o for o in outcomes if isinstance(o, ManifestExistsError)]
    assert len(refusals) == 1, f"exactly one writer is refused, got {outcomes}"
    assert len(outcomes) - len(refusals) == 1

    stored = store.read_cohort("p", "c0001")
    assert stored.selection.seed in (1, 2)
    assert stored == _cohort(seed=stored.selection.seed), (
        "the stored cohort is one writer's, whole"
    )


def test_two_identical_manifests_racing_still_leave_exactly_one_success(
    tmp_path, monkeypatch
):
    """The same bytes are still two writers, and ``overwrite=False`` refuses both but one.

    This is the case a digest comparison cannot catch. A manifest is stamped with
    ``created_utc`` at one-second resolution, so two writers of the same rows
    inside one second produce *identical* files; the publisher then reports
    ALREADY_IDENTICAL rather than raising, and a store that only translated the
    conflict would have told both writers they had stored the manifest.
    """
    store = ManifestStore(tmp_path / "workspace")
    store.cohort_path("p", "c0001").parent.mkdir(parents=True, exist_ok=True)

    with _writers_collide(monkeypatch):
        outcomes = _run_together(
            lambda: store.write_cohort(_cohort(seed=7)),
            lambda: store.write_cohort(_cohort(seed=7)),
        )

    refusals = [o for o in outcomes if isinstance(o, ManifestExistsError)]
    assert len(refusals) == 1, (
        f"one writer created the manifest and one did not, got {outcomes}"
    )
    assert store.read_cohort("p", "c0001") == _cohort(seed=7)


def test_an_overwrite_is_still_a_deliberate_replacement(tmp_path):
    """``overwrite=True`` is the separate, intended path and keeps replacing."""
    store = ManifestStore(tmp_path / "workspace")
    store.write_cohort(_cohort(seed=1))
    store.write_cohort(_cohort(seed=2), overwrite=True)
    assert store.read_cohort("p", "c0001").selection.seed == 2


# -------------------------------------------------------------------- a report


def test_two_different_reports_racing_leave_one_and_a_conflict(tmp_path, monkeypatch):
    store = MetricSetStore(tmp_path / "workspace")
    path = store.report_path("run_000000000001", "metricset_000000000001")
    path.parent.mkdir(parents=True, exist_ok=True)

    def write(markdown: str):
        return store.ensure_report(
            run_id="run_000000000001",
            metric_set_id="metricset_000000000001",
            markdown=markdown,
        )

    with _writers_collide(monkeypatch):
        outcomes = _run_together(lambda: write("# one\n"), lambda: write("# two\n"))

    conflicts = [o for o in outcomes if isinstance(o, MetricSetConflictError)]
    assert len(conflicts) == 1, f"exactly one writer is refused, got {outcomes}"
    assert path.read_text(encoding="utf-8") in ("# one\n", "# two\n"), (
        "the stored report is one writer's, whole"
    )


def test_two_identical_reports_racing_are_both_a_no_op(tmp_path, monkeypatch):
    """Losing the race is not an error when the winner stored the same report."""
    store = MetricSetStore(tmp_path / "workspace")
    path = store.report_path("run_000000000001", "metricset_000000000001")
    path.parent.mkdir(parents=True, exist_ok=True)

    def write():
        return store.ensure_report(
            run_id="run_000000000001",
            metric_set_id="metricset_000000000001",
            markdown="# the same report\n",
        )

    with _writers_collide(monkeypatch):
        outcomes = _run_together(write, write)

    assert not any(isinstance(o, BaseException) for o in outcomes), outcomes
    assert path.read_text(encoding="utf-8") == "# the same report\n"


# ------------------------------------------------------- a whole prepared set


@pytest.mark.imaging
@pytest.mark.canonical500
def test_one_prepared_set_published_twice_at_once_is_never_mixed(
    tmp_path, monkeypatch
):
    """Two writers of the *same* set: the body is written by its owner alone."""
    from canonicalworld import build_canonical_world

    world = build_canonical_world(tmp_path, subjects=1, fingers=(1,), finalise=False)
    store = world.store

    def publish():
        return store.ensure_manifest(
            manifest=world.manifest,
            entries=world.entries,
            profile=world.profile,
            runtime=world.runtime,
            definition=world.definition,
        )

    with _writers_collide(monkeypatch):
        outcomes = _run_together(publish, publish)

    assert not any(isinstance(o, BaseException) for o in outcomes), outcomes
    assert store.verify_set(world.preparation_set_id)
