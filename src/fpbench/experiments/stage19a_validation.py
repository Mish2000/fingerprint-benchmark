"""Stage 19A's own reading of a finished run's stored results.

The engine does not decide which recorded failures are the algorithm declining a
print and which mean a broken machine — it asks the route, because the answer is
route-specific (docs/adr/0013). This module is Stage 19A's answer, and it is
deliberately its own file rather than a parameter on the NBIS validator: that one
is bound to ``nbis_mindtct_bozorth3`` and is pinned by Stage 7C's published
evidence.

**The one classification that matters here, and is not obvious.** A template
OpenAFIS refuses because it carries more than 128 minutiae is an
``ALGORITHMIC`` failure, not a blocking one. It is a real limit of a real matcher
meeting a real property of real rolled fingerprints: MINDTCT finds a median of
205 minutiae in a rolled 500 ppi impression and OpenAFIS declares a ceiling of
128. Nothing about the harness is wrong when that happens, and recording it as a
defect would say the bridge is broken when the composition simply does not reach.

The same is true in the other direction: ``MATCHING_FAILED`` *is* blocking. Both
templates loaded, so the matcher owed an answer, and not getting one means
something is wrong with this machine rather than with these fingers.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Mapping

from fpbench.adapters.openafis.adapter import ADAPTER_ID, ALGORITHM_ID
from fpbench.core.enums import (
    ExecutionStatus,
    FailureCode,
    IntegrityIssueCode,
    IntegritySeverity,
)
from fpbench.core.run_state_models import IntegrityIssue

__all__ = [
    "ExpectedInputSet",
    "SD300_CANONICAL500_INPUT_SET",
    "ALGORITHMIC_FAILURE_CODES",
    "BLOCKING_FAILURE_CODES",
    "Stage19AValidationReport",
    "validate_stage19a_result_set",
]


@dataclass(frozen=True, slots=True)
class ExpectedInputSet:
    """Which materialised input set a run is allowed to have been produced from."""

    preparation_set_id: str
    transform_profile_id: str
    target_ppi: int
    entry_count: int


SD300_CANONICAL500_INPUT_SET = ExpectedInputSet(
    preparation_set_id="prepset_be560e047991",
    transform_profile_id="canonical_gray8_500ppi_lanczos3_v1",
    target_ppi=500,
    entry_count=3000,
)

#: The route looked at the print and could not produce a usable template, or ran
#: out of the comparison's budget doing so. Real properties of real fingerprints.
#: ``TEMPLATE_EXTRACTION_FAILED`` covers both MINDTCT declining a print and
#: OpenAFIS refusing a minutiae count outside its own 2..128 bounds.
ALGORITHMIC_FAILURE_CODES: frozenset[FailureCode] = frozenset(
    {FailureCode.TEMPLATE_EXTRACTION_FAILED, FailureCode.TIMEOUT}
)

#: The comparison never happened as designed. None of these can be a property of
#: a dataset that has already been validated and checksummed.
BLOCKING_FAILURE_CODES: frozenset[FailureCode] = frozenset(
    {
        FailureCode.INPUT_INVALID,
        FailureCode.IMAGE_DECODE_FAILED,
        FailureCode.PREPARATION_FAILED,
        FailureCode.UNSUPPORTED_RESOLUTION,
        FailureCode.QUALITY_REJECTED,
        FailureCode.MATCHING_FAILED,
        FailureCode.NO_SCORE,
        FailureCode.PROCESS_CRASHED,
        FailureCode.DEPENDENCY_MISSING,
        FailureCode.INTERNAL_ERROR,
    }
)


@dataclass(frozen=True, slots=True)
class Stage19AValidationReport:
    """What a Stage 19A pass over a run's results found.

    ``algorithmic_failures`` and ``blocking_failures`` are counted separately on
    purpose: the first is data, the second is a defect. ``is_clean`` cares only
    about the second, plus anything that made a result unattributable.
    """

    run_id: str
    plan_id: str

    total_results: int
    successful_results: int
    algorithmic_failures: int
    blocking_failures: int

    failure_counts: Mapping[str, int]
    stage19_status_counts: Mapping[str, int]
    issues: tuple[IntegrityIssue, ...]

    validation_fingerprint: str
    inspected_utc: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "failure_counts",
            MappingProxyType({str(k): int(v) for k, v in sorted(dict(self.failure_counts).items())}),
        )
        object.__setattr__(
            self,
            "stage19_status_counts",
            MappingProxyType({str(k): int(v) for k, v in sorted(dict(self.stage19_status_counts).items())}),
        )
        object.__setattr__(self, "issues", tuple(self.issues))

    @property
    def is_clean(self) -> bool:
        """True when nothing blocks a research receipt.

        A run with four thousand template refusals and no issues is clean: the
        refusals are what this composition does. A run with one result that
        cannot be attributed is not.
        """
        return not self.blocking_failures and not self.issues


def _issue(
    code: IntegrityIssueCode,
    message: str,
    job_id: str = "",
    *,
    severity: IntegritySeverity = IntegritySeverity.ERROR,
) -> IntegrityIssue:
    return IntegrityIssue(code=code, severity=severity, message=message, job_id=job_id or None)


def validate_stage19a_result_set(
    *,
    run,
    plan,
    pairs,
    images,
    result_store,
    runtime_reference,
    preparation=None,
    expected_input_set: ExpectedInputSet | None = None,
) -> Stage19AValidationReport:
    """Inspect every stored result of a Stage 19A run against this route's contract."""
    issues: list[IntegrityIssue] = []
    failure_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}

    total = successes = algorithmic = blocking = 0

    if run.algorithm.algorithm_id != ALGORITHM_ID:
        issues.append(
            _issue(
                IntegrityIssueCode.ALGORITHM_FINGERPRINT_MISMATCH,
                f"the run's algorithm is {run.algorithm.algorithm_id!r}, not {ALGORITHM_ID!r}; "
                "this validator does not apply to it",
            )
        )
    if run.algorithm.adapter_id != ADAPTER_ID:
        issues.append(
            _issue(
                IntegrityIssueCode.ALGORITHM_FINGERPRINT_MISMATCH,
                f"the run's adapter is {run.algorithm.adapter_id!r}, not {ADAPTER_ID!r}",
            )
        )

    if preparation is not None and expected_input_set is not None:
        if preparation.preparation_set_id != expected_input_set.preparation_set_id:
            issues.append(
                _issue(
                    IntegrityIssueCode.PAIR_MANIFEST_HASH_MISMATCH,
                    f"the run used preparation set {preparation.preparation_set_id!r}, "
                    f"not {expected_input_set.preparation_set_id!r}",
                )
            )

    for planned in plan.jobs:
        job_id = planned.job.job_id
        try:
            record = result_store.read(run.run_id, job_id)
        except FileNotFoundError:
            issues.append(_issue(IntegrityIssueCode.MISSING_RESULT, "no result was stored", job_id))
            continue
        except Exception:  # noqa: BLE001
            issues.append(_issue(IntegrityIssueCode.RESULT_UNREADABLE, "the result could not be read", job_id))
            continue

        total += 1
        if getattr(record, "algorithm_id", ALGORITHM_ID) != ALGORITHM_ID:
            issues.append(
                _issue(
                    IntegrityIssueCode.ALGORITHM_FINGERPRINT_MISMATCH,
                    f"the result claims algorithm {record.algorithm_id!r}",
                    job_id,
                )
            )

        metadata = dict(getattr(record, "metadata", {}) or {})
        stage19 = metadata.get("stage19_status")
        if stage19:
            status_counts[str(stage19)] = status_counts.get(str(stage19), 0) + 1

        if record.status is ExecutionStatus.SUCCESS:
            successes += 1
            score = record.raw_score
            if score is None:
                issues.append(
                    _issue(IntegrityIssueCode.RESULT_HASH_MISMATCH, "a success carries no score", job_id)
                )
            elif float(score) != int(float(score)) or float(score) < 0:
                # OpenAFIS returns a uint8_t. A non-integer or negative value did
                # not come from it.
                issues.append(
                    _issue(
                        IntegrityIssueCode.RESULT_HASH_MISMATCH,
                        f"a success carries {score!r}, which is not a non-negative integer",
                        job_id,
                    )
                )
            continue

        failure = record.failure
        if failure is None:
            issues.append(
                _issue(IntegrityIssueCode.RESULT_UNREADABLE, "a non-success carries no failure", job_id)
            )
            continue
        if record.raw_score is not None:
            # The property the whole benchmark rests on: a failure is never a zero.
            issues.append(
                _issue(
                    IntegrityIssueCode.RESULT_HASH_MISMATCH,
                    "a failed comparison carries a score",
                    job_id,
                )
            )

        code = failure.code
        failure_counts[code.value] = failure_counts.get(code.value, 0) + 1
        if code in ALGORITHMIC_FAILURE_CODES:
            algorithmic += 1
        elif code in BLOCKING_FAILURE_CODES:
            blocking += 1
            issues.append(
                _issue(
                    IntegrityIssueCode.RESULT_BLOCKING_FAILURE,
                    f"result records {code.value}, which means the comparison never happened as designed",
                    job_id,
                )
            )
        else:  # pragma: no cover - the two sets are exhaustive over FailureCode
            blocking += 1
            issues.append(
                _issue(
                    IntegrityIssueCode.RESULT_BLOCKING_FAILURE,
                    f"result records the unclassified failure code {code.value}",
                    job_id,
                )
            )

    payload = {
        "schema": "stage_19a_validation_v1",
        "run_id": run.run_id,
        "plan_id": plan.plan_id,
        "total": total,
        "successes": successes,
        "algorithmic": algorithmic,
        "blocking": blocking,
        "failure_counts": dict(sorted(failure_counts.items())),
        "stage19_status_counts": dict(sorted(status_counts.items())),
        "issues": [issue.code.value for issue in issues],
    }
    fingerprint = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    return Stage19AValidationReport(
        run_id=run.run_id,
        plan_id=plan.plan_id,
        total_results=total,
        successful_results=successes,
        algorithmic_failures=algorithmic,
        blocking_failures=blocking,
        failure_counts=failure_counts,
        stage19_status_counts=status_counts,
        issues=tuple(issues),
        validation_fingerprint=fingerprint,
        inspected_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
