"""Derive labelled calibration input from one verified raw result set.

This is the only public construction path for a
:class:`CalibrationSourceBinding`.  It re-derives the result-set identity from
its entries, re-hashes every raw record, and only then joins ground truth by
``pair_id``.  Consequently a binding that names development result set R cannot
be paired with scores copied from evaluation result set E.

The module imports only :mod:`fpbench.core` from outside the calibration
package.  Callers remain responsible for reading the artifacts from storage;
verification here deliberately does not trust the fact that a store returned
them.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Mapping

from fpbench.calibration.models import LabeledResults, LabeledScore
from fpbench.core.calibration_errors import CalibrationSourceError
from fpbench.core.calibration_models import CalibrationSourceBinding
from fpbench.core.enums import (
    CalibrationPairTruth,
    CohortRole,
    ExecutionStatus,
    ScoreDirection,
)
from fpbench.core.result_models import RawResultRecord, raw_result_hash
from fpbench.core.result_set_models import (
    ResultSetEntry,
    ResultSetManifest,
    ordered_results_hash,
    result_set_fingerprint,
    result_set_id,
)

__all__ = [
    "VerifiedCalibrationResults",
    "verify_result_set_for_calibration",
    "build_calibration_source_binding",
]


@dataclass(frozen=True, slots=True, init=False)
class VerifiedCalibrationResults:
    """A labelled view whose scores were re-hashed against a result set.

    Instances have no public constructor.  This prevents a caller from wrapping
    arbitrary :class:`LabeledResults` in the trusted type (including through
    ``dataclasses.replace``) and bypassing raw-result verification.
    """

    result_set: ResultSetManifest
    result_set_entries: tuple[ResultSetEntry, ...]
    labeled_results: LabeledResults
    algorithm_id: str
    algorithm_fingerprint: str
    cohort_id: str
    pair_manifest_fingerprint: str

    def __init__(self, **_fields: object) -> None:
        _refuse(
            "VerifiedCalibrationResults can only be produced by "
            "verify_result_set_for_calibration"
        )


def _verified_results(
    *,
    result_set: ResultSetManifest,
    result_set_entries: tuple[ResultSetEntry, ...],
    labeled_results: LabeledResults,
    algorithm_id: str,
    algorithm_fingerprint: str,
    cohort_id: str,
    pair_manifest_fingerprint: str,
) -> VerifiedCalibrationResults:
    verified = object.__new__(VerifiedCalibrationResults)
    object.__setattr__(verified, "result_set", result_set)
    object.__setattr__(verified, "result_set_entries", result_set_entries)
    object.__setattr__(verified, "labeled_results", labeled_results)
    object.__setattr__(verified, "algorithm_id", algorithm_id)
    object.__setattr__(verified, "algorithm_fingerprint", algorithm_fingerprint)
    object.__setattr__(verified, "cohort_id", cohort_id)
    object.__setattr__(
        verified, "pair_manifest_fingerprint", pair_manifest_fingerprint
    )
    return verified


def _refuse(message: str) -> None:
    raise CalibrationSourceError(message)


def verify_result_set_for_calibration(
    *,
    result_set: ResultSetManifest,
    result_set_entries: Iterable[ResultSetEntry],
    raw_results: Iterable[RawResultRecord],
    ground_truth_by_pair_id: Mapping[str, CalibrationPairTruth],
) -> VerifiedCalibrationResults:
    """Re-verify raw records and produce the only labelled body selectors accept.

    ``ground_truth_by_pair_id`` is an exact join, not a partial annotation: it
    must name every pair in the result set and no other pair.  Its ordered values
    enter both the labelled-results hash and every downstream artifact.
    """
    if not isinstance(result_set, ResultSetManifest):
        _refuse("calibration requires a ResultSetManifest")
    entries = tuple(result_set_entries)
    if any(not isinstance(entry, ResultSetEntry) for entry in entries):
        _refuse("every result-set entry must be a ResultSetEntry")
    if len(entries) != result_set.total_results:
        _refuse(
            f"result set declares {result_set.total_results} results but carries "
            f"{len(entries)} entries"
        )
    if tuple(entry.ordinal for entry in entries) != tuple(range(len(entries))):
        _refuse("result-set ordinals must be 0..n-1 with no gaps or repeats")
    entry_job_ids = tuple(entry.job_id for entry in entries)
    if len(set(entry_job_ids)) != len(entry_job_ids):
        _refuse("a result-set job may appear only once")
    if ordered_results_hash(entries) != result_set.ordered_results_hash:
        _refuse("the result-set entries do not reproduce ordered_results_hash")
    recomputed_set = result_set_fingerprint(
        run_fingerprint=result_set.run_fingerprint,
        plan_fingerprint=result_set.plan_fingerprint,
        runtime_bundle_fingerprint=result_set.runtime_bundle_fingerprint,
        entries=entries,
        success_count=result_set.success_count,
        failure_count=result_set.failure_count,
    )
    if recomputed_set != result_set.result_set_fingerprint:
        _refuse("the result-set entries do not reproduce result_set_fingerprint")
    if result_set_id(recomputed_set) != result_set.result_set_id:
        _refuse("the result-set id is not derived from its verified fingerprint")

    records = tuple(raw_results)
    if any(not isinstance(record, RawResultRecord) for record in records):
        _refuse("every calibration score source must be a RawResultRecord")
    records_by_job: dict[str, RawResultRecord] = {}
    for record in records:
        if record.job_id in records_by_job:
            _refuse(f"raw result {record.job_id} appears more than once")
        records_by_job[record.job_id] = record
    if set(records_by_job) != set(entry_job_ids):
        missing = sorted(set(entry_job_ids) - set(records_by_job))
        extra = sorted(set(records_by_job) - set(entry_job_ids))
        _refuse(
            "the raw records do not exactly cover the result set: "
            f"missing={missing[:3]}, extra={extra[:3]}"
        )

    if not isinstance(ground_truth_by_pair_id, Mapping):
        _refuse("ground truth must be an exact mapping keyed by pair_id")
    truths = dict(ground_truth_by_pair_id)
    for pair_id, truth in truths.items():
        if type(pair_id) is not str or not pair_id.strip():
            _refuse("ground-truth pair ids must be non-empty strings")
        if not isinstance(truth, CalibrationPairTruth):
            _refuse(
                f"ground truth for {pair_id!r} must be a CalibrationPairTruth"
            )

    labeled_rows: list[LabeledScore] = []
    pair_ids: list[str] = []
    algorithms: set[tuple[str, str]] = set()
    cohorts: set[str] = set()
    pair_manifests: set[str] = set()
    directions: set[ScoreDirection] = set()
    successes = 0
    failures = 0
    for entry in entries:
        record = records_by_job[entry.job_id]
        if record.run_id != result_set.run_id:
            _refuse(
                f"raw result {record.job_id} belongs to run {record.run_id}, not "
                f"{result_set.run_id}"
            )
        actual_hash = raw_result_hash(record)
        if actual_hash != entry.result_hash:
            _refuse(
                f"raw result {record.job_id} hashes to {actual_hash[:12]}... but "
                f"the result set records {entry.result_hash[:12]}..."
            )

        pair_id = str(record.pair_id)
        pair_ids.append(pair_id)
        algorithms.add((record.algorithm_id, record.algorithm_fingerprint))
        cohorts.add(str(record.cohort_id))
        pair_manifests.add(record.pair_manifest_hash)
        if not isinstance(record.score_direction, ScoreDirection):
            _refuse(
                f"raw result {record.job_id} has no validated score direction"
            )
        directions.add(record.score_direction)
        truth = truths.get(pair_id)
        if truth is None:
            _refuse(f"result-set pair {pair_id!r} has no ground-truth label")

        if record.status is ExecutionStatus.SUCCESS:
            successes += 1
            labeled_rows.append(
                LabeledScore(
                    pair_id=pair_id,
                    truth=truth,
                    execution_status=record.status,
                    score=Decimal(str(record.raw_score)),
                )
            )
        else:
            failures += 1
            labeled_rows.append(
                LabeledScore(
                    pair_id=pair_id,
                    truth=truth,
                    execution_status=record.status,
                    failure_code=(record.failure.code.value if record.failure else None),
                )
            )

    if len(set(pair_ids)) != len(pair_ids):
        _refuse("a pair_id may appear only once in a calibration result set")
    if set(truths) != set(pair_ids):
        extra = sorted(set(truths) - set(pair_ids))
        _refuse(f"ground truth names pairs outside the result set: {extra[:3]}")
    if (successes, failures) != (result_set.success_count, result_set.failure_count):
        _refuse(
            "verified raw-result status counts do not match the result-set manifest"
        )
    if len(algorithms) != 1:
        _refuse("one calibration result set must contain one algorithm identity")
    if len(cohorts) != 1:
        _refuse("one calibration result set must contain one cohort identity")
    if len(pair_manifests) != 1:
        _refuse("one calibration result set must contain one pair-manifest identity")
    if len(directions) != 1:
        _refuse("one calibration result set must contain one score direction")

    algorithm_id, algorithm_fingerprint = algorithms.pop()
    labeled = LabeledResults(score_direction=directions.pop(), rows=tuple(labeled_rows))
    return _verified_results(
        result_set=result_set,
        result_set_entries=entries,
        labeled_results=labeled,
        algorithm_id=algorithm_id,
        algorithm_fingerprint=algorithm_fingerprint,
        cohort_id=cohorts.pop(),
        pair_manifest_fingerprint=pair_manifests.pop(),
    )


def build_calibration_source_binding(
    *,
    binding_id: str,
    verified_results: VerifiedCalibrationResults,
    integration_id: str,
    integration_fingerprint: str,
    dataset_id: str,
    dataset_fingerprint: str,
    cohort_fingerprint: str,
    cohort_role: CohortRole,
    pair_manifest_id: str,
    metadata: Mapping[str, str] | None = None,
) -> CalibrationSourceBinding:
    """Seal a source binding from identities proved by raw result bytes."""
    if not isinstance(verified_results, VerifiedCalibrationResults):
        _refuse(
            "build_calibration_source_binding requires the output of "
            "verify_result_set_for_calibration"
        )
    from fpbench.calibration.protocol import _seal_calibration_source_binding

    result_set = verified_results.result_set
    return _seal_calibration_source_binding(
        binding_id=binding_id,
        algorithm_id=verified_results.algorithm_id,
        algorithm_fingerprint=verified_results.algorithm_fingerprint,
        integration_id=integration_id,
        integration_fingerprint=integration_fingerprint,
        run_id=result_set.run_id,
        run_fingerprint=result_set.run_fingerprint,
        result_set_id=result_set.result_set_id,
        result_set_fingerprint=result_set.result_set_fingerprint,
        dataset_id=dataset_id,
        dataset_fingerprint=dataset_fingerprint,
        cohort_id=verified_results.cohort_id,
        cohort_fingerprint=cohort_fingerprint,
        cohort_role=cohort_role,
        pair_manifest_id=pair_manifest_id,
        pair_manifest_fingerprint=verified_results.pair_manifest_fingerprint,
        score_direction=verified_results.labeled_results.score_direction,
        labeled_results=verified_results.labeled_results,
        metadata=metadata,
    )
