"""Checking that the results on disk are the results the plan asked for.

The audit is what stands between "the executor said it finished" and "this run
can be reported". It answers one question per planned job — *is there exactly
one readable result, and does it claim to be this job's?* — and one question
about the directory as a whole: *is there anything here that no planned job
accounts for?*

Every check compares a stored value against the plan or the run. None of them
looks at a score. A comparison that produced no score is a valid result and
does not appear in this report as a problem; it appears in ``failure_count``
(docs/adr/0013).

An extra result is an error, not a warning. A file that belongs to no planned
job means either the plan changed underneath the run or results from two runs
have been mixed, and both are conditions under which no number from this
directory can be trusted.
"""

from __future__ import annotations

import datetime as _dt
from typing import Iterable

from fpbench.core.enums import (
    ExecutionStatus,
    IntegrityIssueCode,
    IntegritySeverity,
)
from fpbench.core.errors import StorageError
from fpbench.core.execution_models import FINGERPRINT_LENGTH
from fpbench.core.execution_plan_models import ExecutionPlan, PlannedJob
from fpbench.core.result_models import (
    RESULT_SCHEMA_VERSION,
    RawResultRecord,
    RunDefinition,
    raw_result_hash,
)
from fpbench.core.run_state_models import IntegrityIssue, RunAuditReport
from fpbench.core.serialization import stable_hash
from fpbench.storage.result_store import ResultStore

__all__ = ["audit_run", "verify_run_completion", "SUPPORTED_RESULT_SCHEMA_VERSIONS"]

#: Schema versions this audit knows how to interpret. A result written by a
#: future version is refused rather than half-understood.
SUPPORTED_RESULT_SCHEMA_VERSIONS = frozenset({RESULT_SCHEMA_VERSION})

_REQUIRED_METADATA = (
    "schema_version",
    "result_hash",
    "run_id",
    "job_id",
    "job_fingerprint",
    "pair_manifest_hash",
    "algorithm_fingerprint",
    "execution_profile_hash",
)


def audit_run(
    *,
    run: RunDefinition,
    plan: ExecutionPlan,
    result_store: ResultStore,
) -> RunAuditReport:
    """Compare every stored result against the plan that called for it."""
    issues: list[IntegrityIssue] = []
    missing: list[str] = []

    issues.extend(_plan_self_consistency(plan))

    success_count = 0
    failure_count = 0
    valid_results = 0

    for planned in plan.jobs:
        job_id = planned.job.job_id
        if not result_store.has_raw_result(run.run_id, job_id):
            missing.append(job_id)
            issues.append(
                _issue(
                    IntegrityIssueCode.MISSING_RESULT,
                    f"planned job {job_id} has no stored result",
                    job_id=job_id,
                )
            )
            continue

        record = _read(result_store, run.run_id, job_id, issues)
        if record is None:
            continue

        job_issues = list(_check_record(run, planned, record))
        job_issues.extend(_check_metadata(result_store, run, planned, record))
        issues.extend(job_issues)

        if not any(issue.is_error for issue in job_issues):
            valid_results += 1
            if record.status is ExecutionStatus.SUCCESS:
                success_count += 1
            else:
                failure_count += 1

    planned_ids = set(plan.job_ids())
    stored_ids = result_store.stored_job_ids(run.run_id)
    extra = tuple(sorted(set(stored_ids) - planned_ids))
    for job_id in extra:
        issues.append(
            _issue(
                IntegrityIssueCode.EXTRA_RESULT,
                f"result {job_id} belongs to no planned job",
                job_id=job_id,
                relative_path=f"raw/jobs/{job_id}.parquet",
            )
        )

    inspected_utc = _utc_now()
    fingerprint = _audit_fingerprint(
        run=run,
        plan=plan,
        planned_jobs=plan.total_jobs,
        result_files_found=len(stored_ids),
        valid_results=valid_results,
        success_count=success_count,
        failure_count=failure_count,
        missing=tuple(missing),
        extra=extra,
        issues=tuple(issues),
    )

    return RunAuditReport(
        run_id=run.run_id,
        plan_id=plan.plan_id,
        planned_jobs=plan.total_jobs,
        result_files_found=len(stored_ids),
        valid_results=valid_results,
        success_count=success_count,
        failure_count=failure_count,
        missing_job_ids=tuple(missing),
        extra_result_job_ids=extra,
        issues=tuple(issues),
        audit_fingerprint=fingerprint,
        inspected_utc=inspected_utc,
    )


def verify_run_completion(
    *,
    run: RunDefinition,
    plan: ExecutionPlan,
    result_store: ResultStore,
) -> RunAuditReport:
    """The full check, named for what callers actually want to know.

    An alias for :func:`audit_run`, kept as a separate name because
    ``inspect_run_progress`` is the cheap question and this is the expensive
    one; a caller choosing between them should not have to read the source to
    tell which is which.
    """
    return audit_run(run=run, plan=plan, result_store=result_store)


# ----------------------------------------------------------------- internals


def _issue(
    code: IntegrityIssueCode,
    message: str,
    *,
    severity: IntegritySeverity = IntegritySeverity.ERROR,
    job_id: str | None = None,
    relative_path: str | None = None,
    **details: str,
) -> IntegrityIssue:
    return IntegrityIssue(
        code=code,
        severity=severity,
        message=message,
        job_id=job_id,
        relative_path=relative_path,
        details=details,
    )


def _plan_self_consistency(plan: ExecutionPlan) -> Iterable[IntegrityIssue]:
    """Re-check the plan's own uniqueness.

    ``ExecutionPlan`` enforces this at construction, so this only fires for a
    plan that was assembled by other means — a hand-edited ``jobs.parquet``,
    say. Cheap, and it turns an impossible state into a named finding rather
    than a confusing downstream error.
    """
    for code, label, values in (
        (IntegrityIssueCode.DUPLICATE_JOB_ID, "job_id", plan.job_ids()),
        (
            IntegrityIssueCode.DUPLICATE_JOB_FINGERPRINT,
            "job_fingerprint",
            tuple(item.job.job_fingerprint for item in plan.jobs),
        ),
        (
            IntegrityIssueCode.DUPLICATE_PAIR_ID,
            "pair_id",
            tuple(str(item.job.pair_id) for item in plan.jobs),
        ),
    ):
        seen: set[str] = set()
        for value in values:
            if value in seen:
                yield _issue(code, f"plan contains a repeated {label}: {value}")
                break
            seen.add(value)


def _read(
    result_store: ResultStore,
    run_id: str,
    job_id: str,
    issues: list[IntegrityIssue],
) -> RawResultRecord | None:
    try:
        return result_store.read_raw_result(run_id, job_id)
    except (StorageError, ValueError) as exc:
        issues.append(
            _issue(
                IntegrityIssueCode.RESULT_UNREADABLE,
                f"result for {job_id} cannot be read: {exc.__class__.__name__}",
                job_id=job_id,
                relative_path=f"raw/jobs/{job_id}.parquet",
            )
        )
        return None


def _check_record(
    run: RunDefinition, planned: PlannedJob, record: RawResultRecord
) -> Iterable[IntegrityIssue]:
    """Compare a stored result against the job that was supposed to produce it."""
    job = planned.job

    if record.job_id != job.job_id:
        yield _issue(
            IntegrityIssueCode.PATH_JOB_ID_MISMATCH,
            f"result stored as {job.job_id} declares job {record.job_id}",
            job_id=job.job_id,
        )
    if record.run_id != run.run_id:
        yield _issue(
            IntegrityIssueCode.RUN_ID_MISMATCH,
            f"result {job.job_id} belongs to run {record.run_id}, not {run.run_id}",
            job_id=job.job_id,
        )
    if record.job_fingerprint != job.job_fingerprint:
        yield _issue(
            IntegrityIssueCode.JOB_FINGERPRINT_MISMATCH,
            f"result {job.job_id} was produced by a different unit of work",
            job_id=job.job_id,
        )
    if str(record.pair_id) != str(job.pair_id):
        yield _issue(
            IntegrityIssueCode.PAIR_ID_MISMATCH,
            f"result {job.job_id} covers pair {record.pair_id}, planned {job.pair_id}",
            job_id=job.job_id,
        )
    if (record.left_image_id, record.right_image_id) != (
        job.left_image_id,
        job.right_image_id,
    ):
        yield _issue(
            IntegrityIssueCode.IMAGE_IDS_MISMATCH,
            f"result {job.job_id} compared images the plan did not ask for",
            job_id=job.job_id,
        )
    if record.pair_manifest_hash != run.pair_manifest_hash:
        yield _issue(
            IntegrityIssueCode.PAIR_MANIFEST_HASH_MISMATCH,
            f"result {job.job_id} references a different pair manifest",
            job_id=job.job_id,
        )
    if record.algorithm_fingerprint != run.algorithm_fingerprint:
        yield _issue(
            IntegrityIssueCode.ALGORITHM_FINGERPRINT_MISMATCH,
            f"result {job.job_id} was produced by a different algorithm build",
            job_id=job.job_id,
        )
    if record.execution_profile_hash != run.execution_profile_hash:
        yield _issue(
            IntegrityIssueCode.EXECUTION_PROFILE_HASH_MISMATCH,
            f"result {job.job_id} was produced under a different execution profile",
            job_id=job.job_id,
        )


def _check_metadata(
    result_store: ResultStore,
    run: RunDefinition,
    planned: PlannedJob,
    record: RawResultRecord,
) -> Iterable[IntegrityIssue]:
    """Check the parquet metadata against the row it wraps.

    The metadata is what makes a result file self-describing when separated
    from its directory, so it has to agree with the row — a file whose header
    and body disagree is not evidence of anything.
    """
    job_id = planned.job.job_id
    relative_path = f"raw/jobs/{job_id}.parquet"
    try:
        metadata = result_store.raw_result_metadata(run.run_id, job_id)
    except StorageError as exc:
        yield _issue(
            IntegrityIssueCode.RESULT_METADATA_MISSING,
            f"result {job_id} has unreadable metadata: {exc.__class__.__name__}",
            job_id=job_id,
            relative_path=relative_path,
        )
        return

    absent = [key for key in _REQUIRED_METADATA if not metadata.get(key)]
    if absent:
        yield _issue(
            IntegrityIssueCode.RESULT_METADATA_MISSING,
            f"result {job_id} is missing metadata: {', '.join(absent)}",
            job_id=job_id,
            relative_path=relative_path,
            missing=",".join(absent),
        )
        return

    version = metadata["schema_version"]
    if version not in SUPPORTED_RESULT_SCHEMA_VERSIONS:
        yield _issue(
            IntegrityIssueCode.RESULT_SCHEMA_MISMATCH,
            f"result {job_id} uses schema version {version}, which this build "
            f"cannot interpret",
            job_id=job_id,
            relative_path=relative_path,
            schema_version=version,
        )
        return

    if metadata["result_hash"] != raw_result_hash(record):
        yield _issue(
            IntegrityIssueCode.RESULT_HASH_MISMATCH,
            f"result {job_id} does not hash to the digest recorded in its header",
            job_id=job_id,
            relative_path=relative_path,
        )

    for key, expected, code in (
        ("run_id", run.run_id, IntegrityIssueCode.RUN_ID_MISMATCH),
        ("job_id", job_id, IntegrityIssueCode.PATH_JOB_ID_MISMATCH),
        (
            "job_fingerprint",
            planned.job.job_fingerprint,
            IntegrityIssueCode.JOB_FINGERPRINT_MISMATCH,
        ),
        (
            "pair_manifest_hash",
            run.pair_manifest_hash,
            IntegrityIssueCode.PAIR_MANIFEST_HASH_MISMATCH,
        ),
        (
            "algorithm_fingerprint",
            run.algorithm_fingerprint,
            IntegrityIssueCode.ALGORITHM_FINGERPRINT_MISMATCH,
        ),
        (
            "execution_profile_hash",
            run.execution_profile_hash,
            IntegrityIssueCode.EXECUTION_PROFILE_HASH_MISMATCH,
        ),
    ):
        if metadata[key] != expected:
            yield _issue(
                code,
                f"result {job_id} metadata {key} is {metadata[key][:16]}..., "
                f"expected {str(expected)[:16]}...",
                job_id=job_id,
                relative_path=relative_path,
            )


def _audit_fingerprint(
    *,
    run: RunDefinition,
    plan: ExecutionPlan,
    planned_jobs: int,
    result_files_found: int,
    valid_results: int,
    success_count: int,
    failure_count: int,
    missing: tuple[str, ...],
    extra: tuple[str, ...],
    issues: tuple[IntegrityIssue, ...],
) -> str:
    """A digest of what the audit found, with no timestamp in it.

    The same filesystem state audited twice must produce the same fingerprint,
    so that a completion manifest can name the exact audit it rests on.
    """
    return stable_hash(
        {
            "schema": "run_audit_fingerprint_v1",
            "run_fingerprint": run.run_fingerprint,
            "plan_fingerprint": plan.definition.plan_fingerprint,
            "planned_jobs": planned_jobs,
            "result_files_found": result_files_found,
            "valid_results": valid_results,
            "success_count": success_count,
            "failure_count": failure_count,
            "missing_job_ids": list(missing),
            "extra_result_job_ids": list(extra),
            "issues": [
                {
                    "code": issue.code.value,
                    "severity": issue.severity.value,
                    "job_id": issue.job_id,
                    "details": dict(issue.details),
                }
                for issue in issues
            ],
        },
        length=FINGERPRINT_LENGTH,
    )


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()
