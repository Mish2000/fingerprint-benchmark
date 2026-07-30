"""Every kind of damage the audit claims to detect, produced deliberately.

Each test forges one specific defect and asserts the *exact* issue code. An
audit that merely returns ``is_clean == False`` for everything would pass a
looser suite while telling nobody what is actually wrong.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from fpbench.core.enums import IntegrityIssueCode, IntegritySeverity
from fpbench.core.identifiers import ImageId, PairId
from fpbench.execution.audit import audit_run, verify_run_completion
from fakes import SometimesFailingAdapter
from runworld import build_world, write_result_file


@pytest.fixture
def world(tmp_path):
    return build_world(tmp_path, subjects=2, fingers=2)


@pytest.fixture
def executed(world):
    """A world with every planned job executed cleanly."""
    runner = world.job_runner()
    for planned in world.plan.jobs:
        runner.execute(planned.job, world.pair_index[planned.job.pair_id])
    return world


def audit(world):
    return audit_run(run=world.run, plan=world.plan, result_store=world.result_store)


def codes(report) -> set[IntegrityIssueCode]:
    return {issue.code for issue in report.issues}


def first_job(world):
    return world.plan.jobs[0].job


def replace_result(world, job, **changes):
    """Forge a damaged result in place of a stored one."""
    store = world.result_store
    record = store.read_raw_result(world.run.run_id, job.job_id)
    path = store.raw_result_path(world.run.run_id, job.job_id)
    path.unlink()
    return write_result_file(path, replace(record, **changes))


# ----------------------------------------------------------------- clean runs


def test_a_fully_executed_run_audits_clean(executed):
    report = audit(executed)
    assert report.is_clean
    assert report.issues == ()
    assert report.planned_jobs == executed.plan.total_jobs
    assert report.valid_results == executed.plan.total_jobs
    assert report.missing_job_ids == ()
    assert report.extra_result_job_ids == ()


def test_success_and_failure_counts_add_up(tmp_path):
    world = build_world(
        tmp_path, subjects=2, fingers=2, adapter=SometimesFailingAdapter(fail_every=3)
    )
    runner = world.job_runner()
    for planned in world.plan.jobs:
        runner.execute(planned.job, world.pair_index[planned.job.pair_id])

    report = audit(world)
    assert report.is_clean
    assert report.failure_count > 0
    assert report.success_count + report.failure_count == world.plan.total_jobs


def test_comparison_failures_are_not_integrity_issues(tmp_path):
    """docs/adr/0013, stated as an assertion."""
    world = build_world(
        tmp_path, subjects=1, fingers=2, adapter=SometimesFailingAdapter(fail_every=1)
    )
    runner = world.job_runner()
    for planned in world.plan.jobs:
        runner.execute(planned.job, world.pair_index[planned.job.pair_id])
    report = audit(world)
    assert report.is_clean
    assert report.failure_count == world.plan.total_jobs


def test_the_fingerprint_is_stable_for_an_unchanged_filesystem(executed):
    assert audit(executed).audit_fingerprint == audit(executed).audit_fingerprint


def test_the_fingerprint_moves_when_the_results_do(executed):
    before = audit(executed).audit_fingerprint
    executed.result_store.raw_result_path(
        executed.run.run_id, first_job(executed).job_id
    ).unlink()
    assert audit(executed).audit_fingerprint != before


def test_verify_run_completion_is_the_full_audit(executed):
    direct = audit(executed)
    aliased = verify_run_completion(
        run=executed.run, plan=executed.plan, result_store=executed.result_store
    )
    assert aliased.audit_fingerprint == direct.audit_fingerprint


# -------------------------------------------------------------- missing/extra


def test_a_missing_result_is_reported(executed):
    job = first_job(executed)
    executed.result_store.raw_result_path(executed.run.run_id, job.job_id).unlink()

    report = audit(executed)
    assert IntegrityIssueCode.MISSING_RESULT in codes(report)
    assert report.missing_job_ids == (job.job_id,)
    assert not report.is_clean


def test_an_extra_result_is_an_error_not_a_warning(executed):
    store = executed.result_store
    source = store.raw_result_path(executed.run.run_id, first_job(executed).job_id)
    stray_id = "job_00000000000000ff"
    (store.raw_jobs_dir(executed.run.run_id) / f"{stray_id}.parquet").write_bytes(
        source.read_bytes()
    )

    report = audit(executed)
    assert IntegrityIssueCode.EXTRA_RESULT in codes(report)
    assert report.extra_result_job_ids == (stray_id,)
    assert all(
        issue.severity is IntegritySeverity.ERROR
        for issue in report.issues
        if issue.code is IntegrityIssueCode.EXTRA_RESULT
    )


def test_a_corrupt_result_is_reported_as_unreadable(executed):
    job = first_job(executed)
    executed.result_store.raw_result_path(
        executed.run.run_id, job.job_id
    ).write_bytes(b"not parquet at all")

    report = audit(executed)
    assert IntegrityIssueCode.RESULT_UNREADABLE in codes(report)
    assert not report.is_clean


# ------------------------------------------------------------ record contents


def test_a_wrong_job_fingerprint_is_reported(executed):
    job = first_job(executed)
    replace_result(executed, job, job_fingerprint="f" * 64)
    assert IntegrityIssueCode.JOB_FINGERPRINT_MISMATCH in codes(audit(executed))


def test_a_wrong_pair_id_is_reported(executed):
    job = first_job(executed)
    replace_result(executed, job, pair_id=PairId("sd300a_00009999_f09_mated"))
    assert IntegrityIssueCode.PAIR_ID_MISMATCH in codes(audit(executed))


def test_wrong_image_ids_are_reported(executed):
    job = first_job(executed)
    replace_result(executed, job, right_image_id=ImageId("sd300a_00009999_roll_f09"))
    assert IntegrityIssueCode.IMAGE_IDS_MISMATCH in codes(audit(executed))


def test_a_wrong_run_id_is_reported(executed):
    job = first_job(executed)
    replace_result(executed, job, run_id="run_000000000000")
    assert IntegrityIssueCode.RUN_ID_MISMATCH in codes(audit(executed))


def test_a_wrong_algorithm_fingerprint_is_reported(executed):
    job = first_job(executed)
    replace_result(executed, job, algorithm_fingerprint="b" * 64)
    assert IntegrityIssueCode.ALGORITHM_FINGERPRINT_MISMATCH in codes(audit(executed))


def test_a_wrong_execution_profile_hash_is_reported(executed):
    job = first_job(executed)
    replace_result(executed, job, execution_profile_hash="c" * 64)
    assert IntegrityIssueCode.EXECUTION_PROFILE_HASH_MISMATCH in codes(audit(executed))


def test_a_wrong_pair_manifest_hash_is_reported(executed):
    job = first_job(executed)
    replace_result(executed, job, pair_manifest_hash="d" * 64)
    assert IntegrityIssueCode.PAIR_MANIFEST_HASH_MISMATCH in codes(audit(executed))


def test_a_result_stored_under_the_wrong_name_is_reported(executed):
    """The row says one job, the filename says another."""
    store = executed.result_store
    first, second = executed.plan.jobs[0].job, executed.plan.jobs[1].job
    source = store.raw_result_path(executed.run.run_id, first.job_id)
    target = store.raw_result_path(executed.run.run_id, second.job_id)
    target.unlink()
    target.write_bytes(source.read_bytes())

    assert IntegrityIssueCode.PATH_JOB_ID_MISMATCH in codes(audit(executed))


# ------------------------------------------------------------------ metadata


def test_a_stale_metadata_result_hash_is_reported(executed):
    job = first_job(executed)
    store = executed.result_store
    record = store.read_raw_result(executed.run.run_id, job.job_id)
    path = store.raw_result_path(executed.run.run_id, job.job_id)
    path.unlink()
    write_result_file(path, record, metadata={"result_hash": "0" * 64})

    assert IntegrityIssueCode.RESULT_HASH_MISMATCH in codes(audit(executed))


@pytest.mark.parametrize(
    "key",
    [
        "schema_version",
        "result_hash",
        "run_id",
        "job_id",
        "job_fingerprint",
        "pair_manifest_hash",
        "algorithm_fingerprint",
        "execution_profile_hash",
    ],
)
def test_missing_metadata_is_reported(executed, key):
    job = first_job(executed)
    store = executed.result_store
    record = store.read_raw_result(executed.run.run_id, job.job_id)
    path = store.raw_result_path(executed.run.run_id, job.job_id)
    path.unlink()
    write_result_file(path, record, drop_metadata=(key,))

    report = audit(executed)
    assert IntegrityIssueCode.RESULT_METADATA_MISSING in codes(report)
    assert key in "".join(issue.details.get("missing", "") for issue in report.issues)


def test_an_unsupported_schema_version_is_reported(executed):
    job = first_job(executed)
    store = executed.result_store
    record = store.read_raw_result(executed.run.run_id, job.job_id)
    path = store.raw_result_path(executed.run.run_id, job.job_id)
    path.unlink()
    write_result_file(path, record, metadata={"schema_version": "99"})

    report = audit(executed)
    assert IntegrityIssueCode.RESULT_SCHEMA_MISMATCH in codes(report)
    assert not report.is_clean


def test_metadata_that_disagrees_with_the_row_is_reported(executed):
    """A self-describing file whose header contradicts its body describes nothing."""
    job = first_job(executed)
    store = executed.result_store
    record = store.read_raw_result(executed.run.run_id, job.job_id)
    path = store.raw_result_path(executed.run.run_id, job.job_id)
    path.unlink()
    write_result_file(path, record, metadata={"algorithm_fingerprint": "e" * 64})

    assert IntegrityIssueCode.ALGORITHM_FINGERPRINT_MISMATCH in codes(audit(executed))


# ----------------------------------------------------------------- plan shape


def test_a_plan_with_a_repeated_job_is_reported(executed):
    plan = executed.plan
    forged = replace(plan, jobs=plan.jobs)
    object.__setattr__(forged, "jobs", plan.jobs[:-1] + (plan.jobs[-2],))

    report = audit_run(
        run=executed.run, plan=forged, result_store=executed.result_store
    )
    assert IntegrityIssueCode.DUPLICATE_JOB_ID in codes(report)


def test_a_damaged_result_does_not_count_as_valid(executed):
    job = first_job(executed)
    replace_result(executed, job, job_fingerprint="f" * 64)
    report = audit(executed)
    assert report.valid_results == executed.plan.total_jobs - 1
