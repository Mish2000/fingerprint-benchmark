"""The ordered collection of results has an identity, and it is checkable.

Two things are being defended. First, that the index is derived from the files
rather than from anything handed to it — an index that agreed with its own
inputs would prove nothing. Second, that one changed score produces a different
identity, because that is the only property that makes citing a result set
worth anything (docs/adr/0019).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fpbench.core.errors import (
    IncompleteRunError,
    ResultSetConflictError,
    StorageError,
)
from fpbench.core.result_set_models import (
    ResultSetEntry,
    ordered_results_hash,
    result_set_fingerprint,
)
from fpbench.execution.result_set import build_result_set
from runworld import build_world


@pytest.fixture
def executed(tmp_path: Path):
    """A small research world with every planned job stored."""
    world = build_world(tmp_path, research=True)
    world.executor().execute(finalize=False)
    return world


def _built(world):
    return build_result_set(
        run=world.run,
        plan=world.plan,
        result_store=world.result_store,
        runtime_reference=world.runtime_reference,
    )


# -------------------------------------------------------------- derivation


def test_every_planned_job_appears_once_in_plan_order(executed):
    manifest, entries = _built(executed)
    assert manifest.total_results == executed.plan.total_jobs
    assert [entry.ordinal for entry in entries] == list(range(len(entries)))
    assert [entry.job_id for entry in entries] == list(executed.plan.job_ids())


def test_the_entry_hashes_are_the_hashes_of_the_stored_files(executed):
    from fpbench.core.result_models import raw_result_hash

    _, entries = _built(executed)
    store = executed.result_store
    for entry in entries:
        record = store.read_raw_result(executed.run.run_id, entry.job_id)
        assert entry.result_hash == raw_result_hash(record)


def test_a_run_with_a_missing_result_has_no_result_set(tmp_path):
    world = build_world(tmp_path, research=True)
    world.executor().execute(max_new_jobs=2, finalize=False)
    with pytest.raises(IncompleteRunError, match="no result"):
        _built(world)


def test_the_created_timestamp_does_not_reach_the_fingerprint(executed):
    first, entries = _built(executed)
    second, _ = build_result_set(
        run=executed.run,
        plan=executed.plan,
        result_store=executed.result_store,
        runtime_reference=executed.runtime_reference,
        created_utc="1999-01-01T00:00:00+00:00",
    )
    assert first.result_set_fingerprint == second.result_set_fingerprint
    assert first.created_utc != second.created_utc


def test_one_changed_score_changes_the_fingerprint(executed):
    manifest, entries = _built(executed)
    mutated = tuple(
        ResultSetEntry(
            ordinal=entry.ordinal,
            job_id=entry.job_id,
            result_hash=("f" * 64 if entry.ordinal == 0 else entry.result_hash),
        )
        for entry in entries
    )
    assert ordered_results_hash(mutated) != manifest.ordered_results_hash
    assert result_set_fingerprint(
        run_fingerprint=manifest.run_fingerprint,
        plan_fingerprint=manifest.plan_fingerprint,
        runtime_bundle_fingerprint=manifest.runtime_bundle_fingerprint,
        entries=mutated,
        success_count=manifest.success_count,
        failure_count=manifest.failure_count,
    ) != manifest.result_set_fingerprint


def test_reordering_the_same_results_changes_the_fingerprint(executed):
    """Order is part of the identity, not a presentation detail."""
    manifest, entries = _built(executed)
    swapped = list(entries)
    swapped[0], swapped[1] = (
        ResultSetEntry(0, swapped[1].job_id, swapped[1].result_hash),
        ResultSetEntry(1, swapped[0].job_id, swapped[0].result_hash),
    )
    assert ordered_results_hash(tuple(swapped)) != manifest.ordered_results_hash


def test_a_different_runtime_bundle_changes_the_fingerprint(executed):
    manifest, entries = _built(executed)
    other = result_set_fingerprint(
        run_fingerprint=manifest.run_fingerprint,
        plan_fingerprint=manifest.plan_fingerprint,
        runtime_bundle_fingerprint="a" * 64,
        entries=entries,
        success_count=manifest.success_count,
        failure_count=manifest.failure_count,
    )
    assert other != manifest.result_set_fingerprint


# ------------------------------------------------------------------- store


def test_a_result_set_round_trips(executed):
    manifest, entries = _built(executed)
    store = executed.result_set_store
    store.ensure_result_set(manifest, entries)

    read_manifest, read_entries = store.read_result_set(executed.run.run_id)
    assert read_manifest == manifest
    assert read_entries == entries


def test_storing_the_same_set_again_is_a_no_op(executed):
    manifest, entries = _built(executed)
    store = executed.result_set_store
    store.ensure_result_set(manifest, entries)
    before = store.manifest_path(executed.run.run_id).read_bytes()
    store.ensure_result_set(manifest, entries)
    assert store.manifest_path(executed.run.run_id).read_bytes() == before


def test_a_different_set_under_the_same_run_is_a_conflict(executed):
    manifest, entries = _built(executed)
    store = executed.result_set_store
    store.ensure_result_set(manifest, entries)

    # A set that claims one fewer success is a different body of evidence.
    from dataclasses import replace

    from fpbench.core.result_set_models import result_set_id

    fingerprint = result_set_fingerprint(
        run_fingerprint=manifest.run_fingerprint,
        plan_fingerprint=manifest.plan_fingerprint,
        runtime_bundle_fingerprint=manifest.runtime_bundle_fingerprint,
        entries=entries,
        success_count=manifest.success_count - 1,
        failure_count=manifest.failure_count + 1,
    )
    other = replace(
        manifest,
        result_set_id=result_set_id(fingerprint),
        result_set_fingerprint=fingerprint,
        success_count=manifest.success_count - 1,
        failure_count=manifest.failure_count + 1,
    )
    with pytest.raises((ResultSetConflictError, StorageError)):
        store.ensure_result_set(other, entries)


def test_an_entry_whose_hash_does_not_match_the_file_is_refused(executed):
    manifest, entries = _built(executed)
    forged = (
        ResultSetEntry(entries[0].ordinal, entries[0].job_id, "a" * 64),
        *entries[1:],
    )
    from dataclasses import replace

    from fpbench.core.result_set_models import result_set_id

    fingerprint = result_set_fingerprint(
        run_fingerprint=manifest.run_fingerprint,
        plan_fingerprint=manifest.plan_fingerprint,
        runtime_bundle_fingerprint=manifest.runtime_bundle_fingerprint,
        entries=forged,
        success_count=manifest.success_count,
        failure_count=manifest.failure_count,
    )
    other = replace(
        manifest,
        result_set_id=result_set_id(fingerprint),
        result_set_fingerprint=fingerprint,
        ordered_results_hash=ordered_results_hash(forged),
    )
    with pytest.raises(StorageError, match="hashes to"):
        executed.result_set_store.ensure_result_set(other, forged)


def test_a_result_the_set_does_not_account_for_is_refused(executed):
    """A coherent index that simply omits a stored result is still refused."""
    from dataclasses import replace

    from fpbench.core.result_set_models import result_set_id

    manifest, entries = _built(executed)
    shorter = entries[:-1]
    fingerprint = result_set_fingerprint(
        run_fingerprint=manifest.run_fingerprint,
        plan_fingerprint=manifest.plan_fingerprint,
        runtime_bundle_fingerprint=manifest.runtime_bundle_fingerprint,
        entries=shorter,
        success_count=manifest.success_count - 1,
        failure_count=manifest.failure_count,
    )
    partial = replace(
        manifest,
        result_set_id=result_set_id(fingerprint),
        result_set_fingerprint=fingerprint,
        total_results=len(shorter),
        success_count=manifest.success_count - 1,
        ordered_results_hash=ordered_results_hash(shorter),
    )
    with pytest.raises(StorageError, match="does not account for"):
        executed.result_set_store.ensure_result_set(partial, shorter)


def test_a_declared_count_that_disagrees_with_the_entries_is_refused(executed):
    manifest, entries = _built(executed)
    with pytest.raises(StorageError, match="declares"):
        executed.result_set_store.ensure_result_set(manifest, entries[:-1])


def test_a_duplicate_job_is_refused(executed):
    manifest, entries = _built(executed)
    duplicated = (*entries[:-1], ResultSetEntry(entries[-1].ordinal, entries[0].job_id,
                                                entries[0].result_hash))
    with pytest.raises(StorageError):
        executed.result_set_store.ensure_result_set(manifest, duplicated)


def test_an_edited_index_fails_to_read_back(executed):
    manifest, entries = _built(executed)
    store = executed.result_set_store
    store.ensure_result_set(manifest, entries)

    import pyarrow.parquet as pq

    from fpbench.storage.result_set_schemas import (
        result_set_entries_to_table,
        table_to_result_set_entries,
    )

    path = store.entries_path(executed.run.run_id)
    rows = table_to_result_set_entries(pq.read_table(path))
    rows[0] = ResultSetEntry(rows[0].ordinal, rows[0].job_id, "b" * 64)
    pq.write_table(result_set_entries_to_table(rows), path, compression="zstd")

    with pytest.raises(StorageError, match="ordered results hash"):
        store.read_result_set(executed.run.run_id)


def test_verification_re_reads_the_result_files(executed):
    manifest, entries = _built(executed)
    store = executed.result_set_store
    store.ensure_result_set(manifest, entries)
    assert store.verify_result_set(executed.run.run_id) == manifest

    # Remove one raw result: the index still parses, but it no longer describes
    # anything on disk.
    executed.result_store.raw_result_path(
        executed.run.run_id, entries[0].job_id
    ).unlink()
    with pytest.raises(StorageError):
        store.verify_result_set(executed.run.run_id)
