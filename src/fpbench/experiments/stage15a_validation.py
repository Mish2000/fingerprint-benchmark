"""Which recorded failures are this algorithm declining a print, and which are not.

The shared engine cannot answer that, and does not try: a template that would
not extract is data for SourceAFIS and would be data for NBIS, but an unfamiliar
tool's non-zero exit might be either, and guessing is how a broken run becomes a
published one (docs/adr/0013).

For this route the split is unusually clean, because the bridge already made it
at the point where the information exists. An exception raised *inside*
``FingerprintsMatching.fingerprints_matching`` is the algorithm declining the two
prints it was handed — a contour ``convexityDefects`` will not accept, an image
OpenCV will not decode, a first side with no features to divide by. Those reach
this module as ``TEMPLATE_EXTRACTION_FAILED``, ``IMAGE_DECODE_FAILED`` or
``MATCHING_FAILED``, and they are data.

Everything else never became a stored result at all: the adapter raises on an
infrastructure failure, which stops the run. So a blocking code appearing here
means something got past that, and the run is not publishable.

**A failure carries no score, and a score of zero is not a failure.** Zero is a
value this matcher genuinely returns, for two prints whose minutiae never fall
within tolerance. The result-model layer already refuses a failed result that
carries a number; this module refuses the inverse — a run in which the two were
ever conflated.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from fpbench.core.enums import (
    ExecutionStatus,
    FailureCode,
    IntegrityIssueCode,
    IntegritySeverity,
)
from fpbench.core.execution_plan_models import ExecutionPlan
from fpbench.core.identifiers import ImageId, PairId
from fpbench.core.models import ComparisonPair, ImageRecord
from fpbench.core.result_models import RunDefinition
from fpbench.core.run_state_models import IntegrityIssue
from fpbench.core.runtime_models import RunRuntimeReference
from fpbench.core.serialization import stable_hash
from fpbench.experiments import stage15a_identity as frozen
from fpbench.experiments.prepared_input_validation import PreparedInputExpectations
from fpbench.core.errors import StorageError
from fpbench.storage.result_store import ResultStore

__all__ = [
    "Stage15AValidationReport",
    "ExpectedInputSet",
    "SD300_CANONICAL500_INPUT_SET",
    "validate_fingerprints_matching_result_set",
    "ALGORITHMIC_FAILURE_CODES",
    "BLOCKING_FAILURE_CODES",
    "FORBIDDEN_METADATA_KEYS",
]

#: Upstream declined the prints. Data, counted, and never repaired.
ALGORITHMIC_FAILURE_CODES: frozenset[FailureCode] = frozenset(
    {
        FailureCode.TEMPLATE_EXTRACTION_FAILED,
        FailureCode.IMAGE_DECODE_FAILED,
        FailureCode.MATCHING_FAILED,
    }
)

#: The comparison never happened as designed. None of these can be a property of
#: a dataset that has already been validated and checksummed.
BLOCKING_FAILURE_CODES: frozenset[FailureCode] = frozenset(
    {
        FailureCode.INPUT_INVALID,
        FailureCode.UNSUPPORTED_RESOLUTION,
        FailureCode.QUALITY_REJECTED,
        FailureCode.NO_SCORE,
        FailureCode.DEPENDENCY_MISSING,
        FailureCode.INTERNAL_ERROR,
        FailureCode.PROCESS_CRASHED,
        FailureCode.TIMEOUT,
        FailureCode.PREPARATION_FAILED,
    }
)

#: This route publishes no feature set, no contour and no threshold. A result
#: carrying one means the adapter changed underneath the results.
FORBIDDEN_METADATA_KEYS: frozenset[str] = frozenset(
    {
        "calibration",
        "contours",
        "decision",
        "eligibility",
        "flx_score",
        "ground_truth",
        "minutiae",
        "minutiae1",
        "minutiae2",
        "nbis_score",
        "operating_point",
        "sourceafis_score",
        "threshold",
        "verifinger_score",
    }
)

_EXPECTED_LOGICAL_EXTRACTIONS = "2"


@dataclass(frozen=True, slots=True)
class ExpectedInputSet:
    """Which materialised input set a run is allowed to have been produced from."""

    preparation_set_id: str
    transform_profile_id: str
    target_ppi: int
    entry_count: int


SD300_CANONICAL500_INPUT_SET = ExpectedInputSet(
    preparation_set_id=frozen.PREPARATION_SET_ID,
    transform_profile_id=frozen.TRANSFORM_PROFILE_ID,
    target_ppi=500,
    entry_count=frozen.EXPECTED_PARTICIPATING_IMAGES,
)


@dataclass(frozen=True, slots=True)
class Stage15AValidationReport:
    """What a Stage 15A pass over a run's stored results found.

    Satisfies ``AlgorithmValidationReport`` structurally, without inheriting
    from or importing any other algorithm's report (docs/adr/0040).
    """

    run_id: str
    plan_id: str

    total_results: int
    successful_results: int
    algorithmic_failures: int
    blocking_failures: int

    #: Counted apart, because for this algorithm they are not the same fact. A
    #: SELF comparison extracts the same image twice, every minutia matches
    #: itself at distance zero and angle zero, and the score is exactly 1.0
    #: whenever extraction succeeds at all. Those scores say the extractor ran;
    #: they say nothing about whether this matcher can tell two prints apart.
    #: Reporting one combined total would let 367 constructed 1.0s stand in for
    #: discriminative coverage.
    self_scores: int
    genuine_scores: int

    failure_counts: Mapping[str, int]
    upstream_codes: Mapping[str, int]
    issues: tuple[IntegrityIssue, ...]

    logical_extraction_calls: int
    comparison_calls: int

    validation_fingerprint: str
    inspected_utc: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "failure_counts",
            MappingProxyType(
                {str(k): int(v) for k, v in sorted(dict(self.failure_counts).items())}
            ),
        )
        object.__setattr__(
            self,
            "upstream_codes",
            MappingProxyType(
                {str(k): int(v) for k, v in sorted(dict(self.upstream_codes).items())}
            ),
        )
        object.__setattr__(self, "issues", tuple(self.issues))

    @property
    def is_clean(self) -> bool:
        """True when nothing blocks a research receipt.

        A run with two thousand extraction failures and no issues is clean. A
        run with one failure that carried a score is not.
        """
        return not self.blocking_failures and not any(
            issue.severity is IntegritySeverity.ERROR for issue in self.issues
        )

    @property
    def errors(self) -> tuple[IntegrityIssue, ...]:
        return tuple(
            issue for issue in self.issues if issue.severity is IntegritySeverity.ERROR
        )

    @property
    def is_score_bearing(self) -> bool:
        """Whether this result set contains any score at all.

        The property that decides whether Stage 15A can establish a fifth raw
        matcher. Six thousand deterministic refusals are a complete, internally
        consistent result set — and not a raw score set.
        """
        return self.successful_results > 0

    @property
    def is_genuine_score_bearing(self) -> bool:
        """Whether any comparison of two *different* prints produced a score.

        Published beside :attr:`is_score_bearing` rather than replacing it. The
        stage's pass criterion is the one above, and this is the number a reader
        needs in order to judge what that pass is worth: a result set whose only
        scores are SELF comparisons has measured that the extractor sometimes
        runs, not that the matcher discriminates.
        """
        return self.genuine_scores > 0


def _issue(
    *,
    code: IntegrityIssueCode,
    message: str,
    reason: str,
    job_id: str | None = None,
    severity: IntegritySeverity = IntegritySeverity.ERROR,
) -> IntegrityIssue:
    """One finding, in the audit's own vocabulary.

    ``reason`` carries this route's more specific name for what happened. The
    shared ``IntegrityIssueCode`` is what the engine reasons about; keeping the
    narrower name in the details means a Stage 15A finding stays readable
    without widening an enum every published run depends on.
    """
    return IntegrityIssue(
        code=code,
        severity=severity,
        message=message,
        job_id=job_id,
        details={"stage15a_reason": reason},
    )


def validate_fingerprints_matching_result_set(
    *,
    run: RunDefinition,
    plan: ExecutionPlan,
    pairs: Mapping[PairId, ComparisonPair],
    images: Mapping[ImageId, ImageRecord],
    result_store: ResultStore,
    runtime_reference: RunRuntimeReference,
    preparation: PreparedInputExpectations | None = None,
    expected_input_set: ExpectedInputSet | None = None,
) -> Stage15AValidationReport:
    """Inspect every stored result of a Stage 15A run against this route's contract."""
    issues: list[IntegrityIssue] = []
    failure_counts: dict[str, int] = {}
    upstream_codes: dict[str, int] = {}

    total = 0
    successes = 0
    algorithmic = 0
    blocking = 0
    logical_extractions = 0
    comparisons = 0
    self_scores = 0
    genuine_scores = 0

    if run.algorithm.algorithm_id != frozen.PRODUCTION_ALGORITHM_ID:
        issues.append(
            _issue(
                code=IntegrityIssueCode.ALGORITHM_FINGERPRINT_MISMATCH,
                reason="algorithm_identity_mismatch",
                message=(
                    f"the run records algorithm {run.algorithm.algorithm_id!r}, "
                    f"not {frozen.PRODUCTION_ALGORITHM_ID!r}"
                ),
            )
        )

    if expected_input_set is not None and preparation is not None:
        observed_set = getattr(preparation, "preparation_set_id", None)
        if observed_set != expected_input_set.preparation_set_id:
            issues.append(
                _issue(
                    code=IntegrityIssueCode.RESULT_PIPELINE_MISMATCH,
                    reason="input_set_mismatch",
                    message=(
                        f"the run reads {observed_set!r}, not the canonical set "
                        f"{expected_input_set.preparation_set_id!r}"
                    ),
                )
            )

    seen_jobs: set[str] = set()
    for planned in plan.jobs:
        job_id = planned.job.job_id
        if job_id in seen_jobs:
            issues.append(
                _issue(
                    code=IntegrityIssueCode.DUPLICATE_JOB_ID,
                    reason="duplicate_planned_job",
                    message="the plan names this job twice",
                    job_id=job_id,
                )
            )
            continue
        seen_jobs.add(job_id)

        try:
            record = result_store.read_raw_result(run.run_id, job_id)
        except (StorageError, ValueError) as exc:
            issues.append(
                _issue(
                    code=IntegrityIssueCode.MISSING_RESULT,
                    reason="missing_result",
                    message=f"no readable stored result: {exc}"[:200],
                    job_id=job_id,
                )
            )
            continue

        total += 1
        # The adapter's own metadata, which is where the route's account of
        # itself lives. ``runner_metadata`` beside it belongs to the engine and
        # is not this route's to assert anything about.
        metadata = dict(getattr(record, "adapter_metadata", {}) or {})
        forbidden = sorted(set(metadata) & FORBIDDEN_METADATA_KEYS)
        if forbidden:
            issues.append(
                _issue(
                    code=IntegrityIssueCode.RESULT_SCHEMA_MISMATCH,
                    reason="forbidden_metadata",
                    message=f"result metadata carries {', '.join(forbidden)}",
                    job_id=job_id,
                )
            )

        extractions = metadata.get("logical_extractions")
        if extractions != _EXPECTED_LOGICAL_EXTRACTIONS:
            issues.append(
                _issue(
                    code=IntegrityIssueCode.RESULT_PIPELINE_MISMATCH,
                    reason="logical_extraction_count",
                    message=(
                        "every comparison performs two independent extractions; "
                        f"this one recorded {extractions!r}"
                    ),
                    job_id=job_id,
                )
            )
        else:
            logical_extractions += 2
        comparisons += 1

        if metadata.get("score_transformation") not in (None, "NONE"):
            issues.append(
                _issue(
                    code=IntegrityIssueCode.RESULT_PIPELINE_MISMATCH,
                    reason="score_transformed",
                    message="fpbench applied a score transformation",
                    job_id=job_id,
                )
            )

        status = getattr(record, "status", None)
        if status is ExecutionStatus.SUCCESS:
            successes += 1
            # SELF is decided from the record's own two image ids rather than
            # from the pair manifest, because the adapter never saw the pair and
            # the stored result is what has to be defensible on its own.
            if record.left_image_id == record.right_image_id:
                self_scores += 1
            else:
                genuine_scores += 1
            if getattr(record, "raw_score", None) is None:
                issues.append(
                    _issue(
                        code=IntegrityIssueCode.RESULT_SCORE_INVALID,
                        reason="success_without_score",
                        message="a successful outcome carries no score",
                        job_id=job_id,
                    )
                )
            continue

        failure = getattr(record, "failure", None)
        if failure is None:
            issues.append(
                _issue(
                    code=IntegrityIssueCode.RESULT_SCHEMA_MISMATCH,
                    reason="failure_without_reason",
                    message="a failed outcome explains nothing",
                    job_id=job_id,
                )
            )
            continue

        if getattr(record, "raw_score", None) is not None:
            issues.append(
                _issue(
                    code=IntegrityIssueCode.RESULT_SCORE_INVALID,
                    reason="failure_carries_a_score",
                    message=(
                        "a failed outcome carries a number. An exception is never "
                        "a score of zero"
                    ),
                    job_id=job_id,
                )
            )

        code = failure.code
        failure_counts[code.value] = failure_counts.get(code.value, 0) + 1
        upstream = dict(getattr(failure, "details", {}) or {}).get("upstream_code")
        if upstream:
            upstream_codes[str(upstream)] = upstream_codes.get(str(upstream), 0) + 1

        if code in BLOCKING_FAILURE_CODES:
            blocking += 1
            issues.append(
                _issue(
                    code=IntegrityIssueCode.RESULT_BLOCKING_FAILURE,
                    reason="infrastructure_failure_stored",
                    message=(
                        f"{code.value} is not something a fingerprint can be; it "
                        "means the harness or the environment was wrong"
                    ),
                    job_id=job_id,
                )
            )
        elif code in ALGORITHMIC_FAILURE_CODES:
            algorithmic += 1
        else:
            blocking += 1
            issues.append(
                _issue(
                    code=IntegrityIssueCode.RESULT_UNKNOWN_FAILURE_CODE,
                    reason="unclassified_failure",
                    message=f"{code.value} is not in this route's failure contract",
                    job_id=job_id,
                )
            )

    if total != len(plan.jobs):
        issues.append(
            _issue(
                code=IntegrityIssueCode.PLAN_CONFLICT,
                reason="result_count_mismatch",
                message=f"{total} stored results against {len(plan.jobs)} planned jobs",
            )
        )
    if successes + algorithmic + blocking != total:
        issues.append(
            _issue(
                code=IntegrityIssueCode.RESULT_SCHEMA_MISMATCH,
                reason="outcome_partition_mismatch",
                message=(
                    "every comparison must end in exactly one of a score or a "
                    f"failure; {successes}+{algorithmic}+{blocking} != {total}"
                ),
            )
        )

    inspected = _dt.datetime.now(_dt.timezone.utc).isoformat()
    fingerprint = stable_hash(
        {
            "schema": "stage_15a_validation_v1",
            "run_id": run.run_id,
            "plan_id": plan.plan_id,
            "total": total,
            "successes": successes,
            "self_scores": self_scores,
            "genuine_scores": genuine_scores,
            "algorithmic": algorithmic,
            "blocking": blocking,
            "failure_counts": dict(sorted(failure_counts.items())),
            "upstream_codes": dict(sorted(upstream_codes.items())),
        }
    )
    return Stage15AValidationReport(
        run_id=run.run_id,
        plan_id=plan.plan_id,
        total_results=total,
        successful_results=successes,
        algorithmic_failures=algorithmic,
        blocking_failures=blocking,
        failure_counts=failure_counts,
        upstream_codes=upstream_codes,
        issues=tuple(issues),
        logical_extraction_calls=logical_extractions,
        comparison_calls=comparisons,
        self_scores=self_scores,
        genuine_scores=genuine_scores,
        validation_fingerprint=fingerprint,
        inspected_utc=inspected,
    )
