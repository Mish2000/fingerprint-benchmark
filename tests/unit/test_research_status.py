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
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from fpbench.core.enums import ResearchRunStatus, RunState
from fpbench.core.errors import ResultConflictError
from fpbench.execution.research import inspect_research_run
from fpbench.experiments.research_receipt import (
    build_research_finalization_marker,
    write_evidence_copy,
)
from fpbench.core.result_set_models import (
    ResultSetEntry,
    ordered_results_hash,
    result_set_fingerprint,
    result_set_id,
)
from fpbench.core.serialization import read_json, to_plain
from fpbench.core.json_io import write_json
from runworld import (
    build_world,
    finalise_research_world,
    research_provenance,
    structural_validation_report,
)


def _state(world):
    validation = None
    if world.result_store.has_research_receipt(world.run.run_id):
        try:
            validation = structural_validation_report(world)
        except Exception:
            # Corruption tests deliberately make a full validation impossible;
            # the inspector must report INVALID rather than the fixture failing.
            validation = None
    return inspect_research_run(
        run=world.run,
        plan=world.plan,
        result_store=world.result_store,
        pairs=world.pair_index,
        algorithm_validation=validation,
        primary_asset_role=(
            next(iter(world.runtime_reference.asset_sha256s))
            if world.runtime_reference
            else "test_runtime_asset"
        ),
        verifier_software=world.software,
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
    assert state.finalization_marker_present
    assert state.finalization_marker_valid
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


def test_broken_prepared_input_set_is_reported_as_invalid_not_raised(
    tmp_path, monkeypatch
):
    from fpbench.experiments import algorithm_research, sourceafis_research

    world = build_world(tmp_path, research=True)
    world.result_store.ensure_run(world.run)
    world.plan_store.ensure_plan(world.plan)
    prepared = SimpleNamespace(
        preparation_preflight_issue=(
            "preparation-set preflight failed: prepared-image set is broken"
        ),
        run=world.run,
        plan=world.plan,
        result_store=world.result_store,
        pairs=world.pair_index,
        verifier_software=world.software,
    )
    load_arguments = {}

    def load_prepared(**kwargs):
        load_arguments.update(kwargs)
        return prepared

    monkeypatch.setattr(algorithm_research, "_load_prepared", load_prepared)

    def must_not_validate(*_, **__):  # pragma: no cover - the assertion is no call
        raise AssertionError("broken preparation must not request prepared entries")

    monkeypatch.setattr(algorithm_research, "_validate", must_not_validate)
    state = sourceafis_research.inspect_research_experiment(
        spec=None,
        preparer_factory=None,
        workspace=tmp_path,
        repository_root=tmp_path,
    )
    assert state.status is ResearchRunStatus.INVALID
    assert any("preparation-set preflight failed" in issue for issue in state.issues)
    assert load_arguments["require_clean_verifier"] is False


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
    forged = replace(receipt, run_fingerprint=other.run.run_fingerprint)
    write_json(world.result_store.research_receipt_path(world.run.run_id), forged)

    state = _state(world)
    assert state.status is ResearchRunStatus.INVALID
    assert not state.receipt_valid


@pytest.mark.parametrize(
    ("field_name", "forged_value"),
    [
        ("schema_version", "999"),
        ("source_commit", "f" * 40),
        ("source_tree_clean", False),
        ("dataset_id", "other_dataset"),
        ("cohort_id", "other_cohort"),
        ("pair_manifest_hash", "f" * 64),
        ("run_id", "run_other"),
        ("run_fingerprint", "f" * 64),
        ("plan_id", "plan_other"),
        ("plan_fingerprint", "f" * 64),
        ("environment_fingerprint", "f" * 64),
        ("runtime_bundle_id", "runtime_other"),
        ("runtime_bundle_fingerprint", "f" * 64),
        ("bridge_jar_sha256", "f" * 64),
        ("result_set_id", "resultset_other"),
        ("result_set_fingerprint", "f" * 64),
        ("audit_fingerprint", "f" * 64),
        ("sourceafis_validation_fingerprint", "f" * 64),
        ("completion_id", "completion_other"),
        ("completion_fingerprint", "f" * 64),
        ("planned_jobs", 999),
        ("stored_results", 999),
        ("success_count", 999),
        ("algorithmic_failure_count", 1),
        ("blocking_failure_count", 1),
        ("preparation_set_id", "prepset_000000000000"),
        ("preparation_set_fingerprint", "a" * 64),
        ("transform_profile_id", "canonical_profile"),
        ("transform_profile_fingerprint", "b" * 64),
        ("transform_runtime_fingerprint", "c" * 64),
        ("failure_counts", {"timeout": 1}),
        ("release_counts", {"SD300A": 1}),
        ("stage_counts", {"plain_self": 1}),
    ],
)
def test_every_load_bearing_receipt_claim_is_revalidated(
    tmp_path, field_name, forged_value
):
    world = build_world(tmp_path, research=True)
    world.executor().execute(finalize=False)
    finalise_research_world(world)

    path = world.result_store.research_receipt_path(world.run.run_id)
    payload = read_json(path)
    payload[field_name] = forged_value
    write_json(path, payload)

    state = _state(world)
    assert state.status is ResearchRunStatus.INVALID
    assert not state.receipt_valid


def test_a_coherent_result_set_in_the_wrong_plan_order_is_invalid(tmp_path):
    world = build_world(tmp_path, research=True)
    world.executor().execute(finalize=False)
    finalise_research_world(world)

    store = world.result_set_store
    manifest, entries = store.read_result_set(world.run.run_id)
    shuffled = (
        ResultSetEntry(0, entries[1].job_id, entries[1].result_hash),
        ResultSetEntry(1, entries[0].job_id, entries[0].result_hash),
        *entries[2:],
    )
    fingerprint = result_set_fingerprint(
        run_fingerprint=manifest.run_fingerprint,
        plan_fingerprint=manifest.plan_fingerprint,
        runtime_bundle_fingerprint=manifest.runtime_bundle_fingerprint,
        entries=shuffled,
        success_count=manifest.success_count,
        failure_count=manifest.failure_count,
    )
    forged = replace(
        manifest,
        result_set_id=result_set_id(fingerprint),
        result_set_fingerprint=fingerprint,
        ordered_results_hash=ordered_results_hash(shuffled),
    )
    store.entries_path(world.run.run_id).unlink()
    store.manifest_path(world.run.run_id).unlink()
    store.ensure_result_set(forged, shuffled)

    state = _state(world)
    assert state.status is ResearchRunStatus.INVALID
    assert not state.result_set_valid
    assert any("order does not match" in issue for issue in state.issues)


def test_intermediate_finalization_without_marker_is_not_authoritative(tmp_path):
    world = build_world(tmp_path, research=True)
    world.executor().execute(finalize=False)
    finalise_research_world(world)

    world.result_store.research_finalization_path(world.run.run_id).unlink()
    state = _state(world)
    assert state.status is ResearchRunStatus.CORE_VERIFIED
    assert state.receipt_valid
    assert not state.finalization_marker_present


def test_a_tampered_finalization_marker_is_invalid(tmp_path):
    world = build_world(tmp_path, research=True)
    world.executor().execute(finalize=False)
    finalise_research_world(world)

    path = world.result_store.research_finalization_path(world.run.run_id)
    payload = read_json(path)
    payload["receipt_content_hash"] = "f" * 64
    write_json(path, payload)

    state = _state(world)
    assert state.status is ResearchRunStatus.INVALID
    assert not state.finalization_marker_valid


def test_a_published_finalization_marker_cannot_be_replaced(tmp_path):
    world = build_world(tmp_path, research=True)
    world.executor().execute(finalize=False)
    receipt = finalise_research_world(world)
    audit = world.completion_service.audit(run=world.run, plan=world.plan)
    validation = structural_validation_report(world)
    result_set = world.result_set_store.read_manifest(world.run.run_id)
    completion = world.result_store.read_completion(world.run.run_id)

    different = build_research_finalization_marker(
        run=world.run,
        plan=world.plan,
        runtime_reference=world.runtime_reference,
        result_set=result_set,
        audit=audit,
        validation=validation,
        completion=completion,
        receipt=receipt,
        verifier_software=research_provenance(revision="f" * 40),
    )
    with pytest.raises(ResultConflictError, match="different research finalization"):
        world.result_store.ensure_research_finalization(different)


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
    assert receipt.preparation_set_id is None
    assert receipt.preparation_set_fingerprint is None
    assert receipt.transform_profile_id is None
    assert receipt.transform_profile_fingerprint is None
    assert receipt.transform_runtime_fingerprint is None


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


def test_evidence_copy_is_idempotent_only_for_identical_bytes(tmp_path):
    world = build_world(tmp_path / "world", research=True)
    world.executor().execute(finalize=False)
    receipt = finalise_research_world(world)
    repository = tmp_path / "repository"

    path = (
        repository
        / "evidence"
        / "sourceafis-native-full"
        / f"{receipt.run_id}.json"
    )
    write_json(path, receipt)
    original = path.read_bytes()
    assert write_evidence_copy(receipt, repository_root=repository) == path
    assert path.read_bytes() == original

    created = write_evidence_copy(
        receipt, repository_root=tmp_path / "empty_repository"
    )
    assert created.is_file()

    changed = replace(receipt, timing_summary={"adapter_ms.count": "999"})
    with pytest.raises(ResultConflictError, match="refusing to overwrite"):
        write_evidence_copy(changed, repository_root=repository)
    assert path.read_bytes() == original


def test_evidence_copy_allows_only_an_exact_v1_to_v2_claim_upgrade(tmp_path):
    world = build_world(tmp_path / "world", research=True)
    world.executor().execute(finalize=False)
    receipt = finalise_research_world(world)
    repository = tmp_path / "repository"
    path = (
        repository
        / "evidence"
        / "sourceafis-native-full"
        / f"{receipt.run_id}.json"
    )
    payload = dict(to_plain(receipt))
    payload["schema_version"] = "1"
    for name in (
        "preparation_set_id",
        "preparation_set_fingerprint",
        "transform_profile_id",
        "transform_profile_fingerprint",
        "transform_runtime_fingerprint",
    ):
        payload.pop(name)
    write_json(path, payload)

    assert write_evidence_copy(receipt, repository_root=repository) == path
    assert read_json(path)["schema_version"] == "2"

    payload["planned_jobs"] = receipt.planned_jobs + 1
    write_json(path, payload)
    with pytest.raises(ResultConflictError, match="refusing to overwrite"):
        write_evidence_copy(receipt, repository_root=repository)
