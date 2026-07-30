"""What a run's files say about it.

Three records, in increasing order of authority:

``RunProgress``
    A cheap snapshot: how many planned jobs have results, how many are missing,
    how the run looks right now. Always recomputed from the plan and the files
    on disk, never from a counter someone incremented (docs/adr/0012).

``RunAuditReport``
    The full check. Every planned job, every stored result, every field of
    provenance compared against the plan and the run. This is what decides
    whether a run may be called verified.

``RunCompletion``
    The immutable statement that an audit passed. Written once, never
    overwritten, and the only thing that turns a run's state into ``VERIFIED``.

The distinction that runs through all three: a *comparison* that failed is a
perfectly valid result, and a run made entirely of them can still be complete
and verified. A *run* is broken only when results are missing, duplicated,
unreadable, or claim provenance they do not have (docs/adr/0013).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from fpbench.core.enums import IntegrityIssueCode, IntegritySeverity, RunState
from fpbench.core.identifiers import validate_id
from fpbench.core.serialization import freeze_str_mapping

__all__ = [
    "RunProgress",
    "IntegrityIssue",
    "RunAuditReport",
    "RunCompletion",
    "COMPLETION_SCHEMA_VERSION",
    "COMPLETION_ID_LENGTH",
]

COMPLETION_SCHEMA_VERSION = "1"
COMPLETION_ID_LENGTH = 12

_HEX = frozenset("0123456789abcdef")


def _require_digest(value: str, field_name: str) -> str:
    digest = str(value).strip().lower()
    if len(digest) != 64 or not set(digest) <= _HEX:
        raise ValueError(f"{field_name} must be a 64-character hexadecimal digest")
    return digest


def _require_non_negative(value: int, field_name: str) -> int:
    number = int(value)
    if number < 0:
        raise ValueError(f"{field_name} must not be negative")
    return number


@dataclass(frozen=True, slots=True)
class RunProgress:
    """A recomputed snapshot of how far a run has got.

    Derived, never authoritative. It may be cached to
    ``derived/progress.json`` and that cache may be overwritten freely, because
    throwing it away costs nothing but a directory listing.

    Two invariants hold whenever nothing is wrong::

        stored_results == successful_results + failed_results   (no unreadable files)
        planned_jobs   == stored_results + missing_results

    The first breaks when a result file cannot be read; that is exactly the
    situation the ``unreadable_results`` count exists to surface, and it forces
    the state to ``INVALID``.
    """

    run_id: str
    plan_id: str
    state: RunState

    planned_jobs: int
    stored_results: int
    successful_results: int
    failed_results: int
    missing_results: int

    extra_results: int
    unreadable_results: int

    completion_manifest_present: bool
    inspected_utc: str

    def __post_init__(self) -> None:
        validate_id(self.run_id)
        validate_id(self.plan_id)
        for name in (
            "planned_jobs",
            "stored_results",
            "successful_results",
            "failed_results",
            "missing_results",
            "extra_results",
            "unreadable_results",
        ):
            object.__setattr__(
                self, name, _require_non_negative(getattr(self, name), name)
            )
        if self.stored_results + self.missing_results != self.planned_jobs:
            raise ValueError(
                "every planned job is either stored or missing: "
                f"{self.stored_results} + {self.missing_results} != {self.planned_jobs}"
            )

    @property
    def is_finished(self) -> bool:
        """True when no planned job is still waiting for a result."""
        return self.missing_results == 0 and self.planned_jobs > 0


@dataclass(frozen=True, slots=True)
class IntegrityIssue:
    """One thing an audit found wrong.

    ``message`` is meant to be shown; keep it short and free of absolute paths.
    """

    code: IntegrityIssueCode
    severity: IntegritySeverity
    message: str
    job_id: str | None = None
    relative_path: str | None = None
    details: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        message = str(self.message).strip()
        if not message:
            raise ValueError("an integrity issue must say what is wrong")
        object.__setattr__(self, "message", message)
        object.__setattr__(self, "details", freeze_str_mapping(self.details))

    @property
    def is_error(self) -> bool:
        return self.severity is IntegritySeverity.ERROR


@dataclass(frozen=True, slots=True)
class RunAuditReport:
    """The full comparison of stored results against the plan.

    ``success_count`` and ``failure_count`` describe *comparisons*;
    ``is_clean`` describes the *run*. A report with 30 failures and no issues is
    a clean report.
    """

    run_id: str
    plan_id: str

    planned_jobs: int
    result_files_found: int
    valid_results: int
    success_count: int
    failure_count: int

    missing_job_ids: tuple[str, ...]
    extra_result_job_ids: tuple[str, ...]
    issues: tuple[IntegrityIssue, ...]

    audit_fingerprint: str
    inspected_utc: str

    def __post_init__(self) -> None:
        validate_id(self.run_id)
        validate_id(self.plan_id)
        for name in (
            "planned_jobs",
            "result_files_found",
            "valid_results",
            "success_count",
            "failure_count",
        ):
            object.__setattr__(
                self, name, _require_non_negative(getattr(self, name), name)
            )
        object.__setattr__(self, "missing_job_ids", tuple(self.missing_job_ids))
        object.__setattr__(
            self, "extra_result_job_ids", tuple(self.extra_result_job_ids)
        )
        object.__setattr__(self, "issues", tuple(self.issues))
        object.__setattr__(
            self, "audit_fingerprint", _require_digest(self.audit_fingerprint, "audit_fingerprint")
        )

    @property
    def is_clean(self) -> bool:
        """True when nothing blocks the run from being verified.

        Warnings do not block. Failed comparisons are not issues at all.
        """
        return not any(issue.is_error for issue in self.issues)

    @property
    def errors(self) -> tuple[IntegrityIssue, ...]:
        return tuple(issue for issue in self.issues if issue.is_error)

    def codes(self) -> tuple[IntegrityIssueCode, ...]:
        return tuple(issue.code for issue in self.issues)


@dataclass(frozen=True, slots=True)
class RunCompletion:
    """The immutable record that a run was audited and found sound.

    Written only once, and only after a clean audit over a plan with no missing
    and no extra results. Its presence is what distinguishes ``COMPLETE`` — all
    the results are there — from ``VERIFIED`` — all the results are there *and*
    somebody checked them.

    ``failure_count`` may be greater than zero. A run in which 30 comparisons
    produced no score is still a finished, trustworthy run; it just has 30
    failures to analyse (docs/adr/0013).
    """

    completion_id: str
    completion_fingerprint: str

    run_id: str
    run_fingerprint: str
    plan_id: str
    plan_fingerprint: str

    pair_manifest_hash: str
    audit_fingerprint: str

    planned_jobs: int
    success_count: int
    failure_count: int

    completed_utc: str

    def __post_init__(self) -> None:
        validate_id(self.completion_id)
        validate_id(self.run_id)
        validate_id(self.plan_id)
        for name in (
            "completion_fingerprint",
            "run_fingerprint",
            "plan_fingerprint",
            "pair_manifest_hash",
            "audit_fingerprint",
        ):
            object.__setattr__(self, name, _require_digest(getattr(self, name), name))
        for name in ("planned_jobs", "success_count", "failure_count"):
            object.__setattr__(
                self, name, _require_non_negative(getattr(self, name), name)
            )
        if self.success_count + self.failure_count != self.planned_jobs:
            raise ValueError(
                "a completed run accounts for every planned job: "
                f"{self.success_count} + {self.failure_count} != {self.planned_jobs}"
            )
