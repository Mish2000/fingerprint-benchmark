"""``VERIFIED`` is not ``RESEARCH_READY``, and the difference is the point.

A run can pass every check stage 3B knows how to make and still be unusable as
evidence: nothing in an audit says which executable produced the results, which
commit drove it, or that the collection of scores has an identity a later
chapter can cite. This module walks a run through the whole chain and asserts
that each state is reported only once its own link is actually in place
(docs/adr/0020).
"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from fpbench.core.enums import ResearchRunStatus, RunState
from fpbench.execution.research import inspect_research_run
from runworld import build_world, finalise_research_world


def _state(world):
    return inspect_research_run(
        run=world.run, plan=world.plan, result_store=world.result_store
    )


def _unlock(path: Path) -> Path:
    path.chmod(path.stat().st_mode | stat.S_IWUSR)
    return path


# ---------------------------------------------------------------- progression


def test_a_prepared_run_with_no_results_is_prepared(tmp_path):
    world = build_world(tmp_path, research=True)
    world.result_store.ensure_run(world.run)
    world.plan_store.ensure_plan(world.plan)

    state = _state(world)
    assert state.status is ResearchRunStatus.PREPARED
    assert state.runtime_reference_present and state.runtime_bundle_valid
    assert state.stored_results == 0


def test_a_run_with_no_runtime_binding_is_not_prepared(tmp_path):
    """The ordinary dummy world has no pinned runtime, and must not pretend."""
    world = build_world(tmp_path)
    world.executor().execute()

    state = _state(world)
    assert state.status is ResearchRunStatus.NOT_PREPARED
    assert not state.runtime_reference_present
    assert state.core_state is RunState.VERIFIED


def test_a_half_executed_run_is_partial(tmp_path):
    world = build_world(tmp_path, research=True)
    world.executor().execute(max_new_jobs=3, finalize=False)

    state = _state(world)
    assert state.status is ResearchRunStatus.PARTIAL
    assert state.stored_results == 3
    assert state.missing_results == world.plan.total_jobs - 3


def test_all_results_without_a_completion_is_results_complete(tmp_path):
    world = build_world(tmp_path, research=True)
    world.executor().execute(finalize=False)

    state = _state(world)
    assert state.status is ResearchRunStatus.RESULTS_COMPLETE
    assert state.core_state is RunState.COMPLETE
    assert state.missing_results == 0


def test_a_completion_alone_is_only_core_verified(tmp_path):
    """The claim a thesis needs is not the claim an audit makes."""
    world = build_world(tmp_path, research=True)
    world.executor().execute(finalize=False)
    world.completion_service.finalise(run=world.run, plan=world.plan)

    state = _state(world)
    assert state.core_state is RunState.VERIFIED
    assert state.status is ResearchRunStatus.CORE_VERIFIED
    assert not state.result_set_present
    assert not state.receipt_present


def test_the_full_chain_reaches_research_ready(tmp_path):
    world = build_world(tmp_path, research=True)
    world.executor().execute(finalize=False)
    finalise_research_world(world)

    state = _state(world)
    assert state.status is ResearchRunStatus.RESEARCH_READY
    assert state.is_research_ready
    assert state.runtime_bundle_valid
    assert state.result_set_valid
    assert state.receipt_valid
    assert state.issues == ()


# ------------------------------------------------------------------- invalid


def test_a_damaged_runtime_bundle_invalidates_a_finished_run(tmp_path):
    """The results are all there and audited; the executable is not."""
    world = build_world(tmp_path, research=True)
    world.executor().execute(finalize=False)
    finalise_research_world(world)

    role = list(world.runtime_reference.asset_sha256s)[0]
    _unlock(world.bundle_store.asset_path(world.bundle.bundle_id, role)).write_bytes(
        b"replaced"
    )

    state = _state(world)
    assert state.status is ResearchRunStatus.INVALID
    assert not state.runtime_bundle_valid
    assert state.issues


def test_a_missing_runtime_asset_invalidates_the_run(tmp_path):
    world = build_world(tmp_path, research=True)
    world.executor().execute(finalize=False)
    finalise_research_world(world)

    role = list(world.runtime_reference.asset_sha256s)[0]
    _unlock(world.bundle_store.asset_path(world.bundle.bundle_id, role)).unlink()

    assert _state(world).status is ResearchRunStatus.INVALID


def test_a_deleted_result_invalidates_a_finalised_run(tmp_path):
    world = build_world(tmp_path, research=True)
    world.executor().execute(finalize=False)
    finalise_research_world(world)

    job_id = world.plan.job_ids()[0]
    world.result_store.raw_result_path(world.run.run_id, job_id).unlink()

    state = _state(world)
    assert state.status is ResearchRunStatus.INVALID
    assert not state.result_set_valid


def test_a_receipt_for_another_run_is_rejected(tmp_path):
    world = build_world(tmp_path, research=True)
    world.executor().execute(finalize=False)
    receipt = finalise_research_world(world)

    other = build_world(tmp_path / "second", research=True, replicate_index=1)
    other.executor().execute(finalize=False)
    finalise_research_world(other)

    # Point the first run's receipt file at the second run's fingerprints.
    from dataclasses import replace

    from fpbench.core.serialization import write_json

    forged = replace(receipt, run_fingerprint=other.run.run_fingerprint)
    write_json(world.result_store.research_receipt_path(world.run.run_id), forged)

    state = _state(world)
    assert state.status is ResearchRunStatus.INVALID
    assert not state.receipt_valid


# ------------------------------------------------------------------ receipt


def test_the_receipt_names_every_link_in_the_chain(tmp_path):
    world = build_world(tmp_path, research=True)
    world.executor().execute(finalize=False)
    receipt = finalise_research_world(world)

    assert receipt.run_fingerprint == world.run.run_fingerprint
    assert receipt.plan_fingerprint == world.plan.definition.plan_fingerprint
    assert receipt.runtime_bundle_id == world.bundle.bundle_id
    assert receipt.source_commit == world.software.source_revision
    assert receipt.planned_jobs == world.plan.total_jobs
    assert receipt.stored_results == world.plan.total_jobs
    assert receipt.blocking_failure_count == 0


def test_the_receipt_carries_no_path_and_no_score(tmp_path):
    world = build_world(tmp_path, research=True)
    world.executor().execute(finalize=False)
    finalise_research_world(world)

    text = world.result_store.research_receipt_path(world.run.run_id).read_text(
        encoding="utf-8"
    )
    assert str(world.workspace) not in text
    assert str(world.dataset_root) not in text
    for forbidden in ("raw_score", "subject_id", "image_id", "threshold", "fmr"):
        assert forbidden not in text.lower()


def test_the_receipt_says_it_proves_nothing_about_accuracy(tmp_path):
    world = build_world(tmp_path, research=True)
    world.executor().execute(finalize=False)
    receipt = finalise_research_world(world)
    assert "no biometric performance conclusion" in receipt.statement


def test_a_receipt_cannot_be_built_for_a_dirty_tree(tmp_path):
    from dataclasses import replace

    world = build_world(tmp_path, research=True)
    world.executor().execute(finalize=False)
    receipt = finalise_research_world(world)

    with pytest.raises(ValueError, match="uncommitted"):
        replace(receipt, source_tree_clean=False)
