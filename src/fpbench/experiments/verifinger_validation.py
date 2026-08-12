"""What a finished VeriFinger run's stored results have to say for themselves.

The engine cannot decide which recorded failures are the algorithm declining a
print and which mean the harness broke, so it asks the algorithm — and this is
the VeriFinger answer (docs/adr/0013). It is also where the claims that only make
sense for this route are checked over all 6,000 rows.

**Every success carries an integer.** VeriFinger returns a Java ``int``; the
stored score is an IEEE double. Seventeen digits do not enter into it — what is
checked is that the stored double is integer-valued, so a row that had been
normalised, scaled or calibrated between the bridge and the store would be
visible as a fraction (spec sections 11 and 31).

**Every comparison performed two independent extractions.** Each successful
result records ``extraction_count`` from the bridge's own count, so the SELF
stage's independence is a recorded fact for every one of the 500 SELF rows per
release rather than a claim in a docstring (spec section 14).

**Every result names the same runtime closure.** A run whose DLLs were swapped
halfway would show two manifest fingerprints across its rows.

**No result carries a decision.** Not a threshold, not a MATCH, not a FAR, not
another algorithm's score. The metadata prefix is namespaced, so
``verifinger.threshold`` is refused for the same reason ``threshold`` is
(spec sections 30 and 31).

There is no threshold in this module, no notion of a score being high or low,
and no comparison with any other algorithm. A score of 0 is a perfectly good
success (docs/adr/0003, spec section 33).
"""

from __future__ import annotations

import datetime as _dt
import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterable, Mapping

from fpbench.adapters.verifinger_java.failure_mapping import (
    ALGORITHMIC_FAILURE_CODES,
    BLOCKING_FAILURE_CODES,
)
from fpbench.core.enums import (
    ExecutionStatus,
    FailureCode,
    IntegrityIssueCode,
    IntegritySeverity,
    ScoreDirection,
)
from fpbench.core.errors import StorageError
from fpbench.core.execution_plan_models import ExecutionPlan
from fpbench.core.identifiers import ImageId, PairId
from fpbench.core.models import ComparisonPair, ImageRecord
from fpbench.core.result_models import RawResultRecord, RunDefinition
from fpbench.core.run_state_models import IntegrityIssue
from fpbench.core.runtime_models import RunRuntimeReference
from fpbench.core.serialization import stable_hash
from fpbench.execution.adapter_result_validation import (
    FORBIDDEN_METADATA_KEYS as UNIVERSAL_FORBIDDEN_METADATA_KEYS,
)
from fpbench.execution.adapter_result_validation import forbidden_metadata_present
from fpbench.experiments.prepared_input_validation import (
    PreparedInputExpectations,
    check_prepared_inputs,
    check_release_source_resolutions,
)
from fpbench.storage.result_store import ResultStore
from fpbench.adapters.verifinger_java import identity

__all__ = [
    "VeriFingerValidationReport",
    "ExpectedInputSet",
    "SD300_CANONICAL500_INPUT_SET",
    "validate_verifinger_result_set",
    "ALGORITHMIC_FAILURE_CODES",
    "BLOCKING_FAILURE_CODES",
    "VERIFINGER_FORBIDDEN_METADATA_KEYS",
    "FORBIDDEN_METADATA_KEYS",
    "REQUIRED_RUNTIME_ASSET_ROLES",
]

#: This route's own additions to the universal list. It publishes no template,
#: no minutia set and no decision, so a result carrying one means the adapter
#: changed underneath the results (spec section 31).
VERIFINGER_FORBIDDEN_METADATA_KEYS: frozenset[str] = frozenset(
    {
        "calibration",
        "decision",
        "eligibility",
        "far",
        "flx_result",
        "flx_score",
        "ground_truth",
        "is_match",
        "match",
        "matched",
        "minutiae",
        "nbis_result",
        "nbis_score",
        "operating_point",
        "score",
        "sourceafis_result",
        "sourceafis_score",
        "template",
        "threshold",
    }
)

FORBIDDEN_METADATA_KEYS: frozenset[str] = (
    UNIVERSAL_FORBIDDEN_METADATA_KEYS | VERIFINGER_FORBIDDEN_METADATA_KEYS
)

#: Every role the runtime reference must carry. A bundle holding two of the
#: three is not this route's runtime, whatever the surviving files hash to.
REQUIRED_RUNTIME_ASSET_ROLES: tuple[str, ...] = (
    "verifinger_bridge_jar",
    "verifinger_runtime_manifest",
    "verifinger_runtime_policy",
)

_PREFIX = identity.METADATA_PREFIX


@dataclass(frozen=True, slots=True)
class ExpectedInputSet:
    """Which materialised input set a run is allowed to have been produced from."""

    preparation_set_id: str
    transform_profile_id: str
    target_ppi: int
    entry_count: int


#: The set Stage 6A materialised and every canonical run since has read. Written
#: down so the check exists independently of the experiment configuration that
#: also names it.
SD300_CANONICAL500_INPUT_SET = ExpectedInputSet(
    preparation_set_id="prepset_be560e047991",
    transform_profile_id="canonical_gray8_500ppi_lanczos3_v1",
    target_ppi=500,
    entry_count=3000,
)


@dataclass(frozen=True, slots=True)
class VeriFingerValidationReport:
    """What a VeriFinger-specific pass over a run's results found.

    ``algorithmic_failures`` and ``blocking_failures`` are counted separately on
    purpose: the first is data — VeriFinger declining a print is a real property
    of real fingerprints — and the second is a defect. ``is_clean`` cares only
    about the second, plus anything that made a result unattributable
    (spec sections 31 and 32).

    Satisfies ``AlgorithmValidationReport`` structurally, without inheriting from
    or importing any other algorithm's report (docs/adr/0040).
    """

    run_id: str
    plan_id: str

    total_results: int
    successful_results: int
    algorithmic_failures: int
    blocking_failures: int

    failure_counts: Mapping[str, int]
    issues: tuple[IntegrityIssue, ...]

    #: Measured over the stored results, not planned. Reported so the operational
    #: summary can publish them without recomputing.
    logical_extraction_calls: int
    verify_invocations: int
    engine_status_counts: Mapping[str, int]

    validation_fingerprint: str
    inspected_utc: str

    def __post_init__(self) -> None:
        for name in ("failure_counts", "engine_status_counts"):
            object.__setattr__(
                self,
                name,
                MappingProxyType(
                    {
                        str(k): int(v)
                        for k, v in sorted(dict(getattr(self, name)).items())
                    }
                ),
            )
        object.__setattr__(self, "issues", tuple(self.issues))

    @property
    def is_clean(self) -> bool:
        """True when nothing blocks a research receipt.

        A run with forty extraction failures and no issues is clean. A run with
        one licence failure is not (spec sections 31 and 32).
        """
        return not self.blocking_failures and not any(
            issue.severity is IntegritySeverity.ERROR for issue in self.issues
        )

    @property
    def errors(self) -> tuple[IntegrityIssue, ...]:
        return tuple(
            issue for issue in self.issues if issue.severity is IntegritySeverity.ERROR
        )


def validate_verifinger_result_set(
    *,
    run: RunDefinition,
    plan: ExecutionPlan,
    pairs: Mapping[PairId, ComparisonPair],
    images: Mapping[ImageId, ImageRecord],
    result_store: ResultStore,
    runtime_reference: RunRuntimeReference,
    preparation: PreparedInputExpectations | None = None,
    expected_input_set: ExpectedInputSet | None = None,
    expected_runtime_manifest_fingerprint: str | None = None,
) -> VeriFingerValidationReport:
    """Inspect every stored result of a VeriFinger run against this route's contract."""
    issues: list[IntegrityIssue] = []
    failure_counts: dict[str, int] = {}
    engine_statuses: dict[str, int] = {}

    total = 0
    successes = 0
    algorithmic = 0
    blocking = 0
    extractions = 0
    verifications = 0
    seen_jobs: set[str] = set()
    manifest_fingerprints: set[str] = set()

    issues.extend(_check_run(run, runtime_reference))
    if preparation is not None:
        issues.extend(
            _check_input_set(
                run=run,
                pairs=pairs,
                preparation=preparation,
                expected_input_set=expected_input_set,
            )
        )

    for planned in plan.jobs:
        job_id = planned.job.job_id
        if job_id in seen_jobs:
            # The plan itself is the authority on which jobs exist, so a repeat
            # here is a defect in the plan rather than in the results — and one
            # that would silently double-count a comparison (spec section 31).
            issues.append(
                _issue(
                    IntegrityIssueCode.DUPLICATE_JOB_ID,
                    f"job {job_id} appears twice in the plan",
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
                    IntegrityIssueCode.RESULT_UNREADABLE,
                    f"result for {job_id} cannot be read: {type(exc).__name__}",
                    job_id=job_id,
                )
            )
            continue

        total += 1
        if pairs.get(planned.job.pair_id) is None:
            issues.append(
                _issue(
                    IntegrityIssueCode.PAIR_ID_MISMATCH,
                    f"result {job_id} covers pair {record.pair_id}, which is not "
                    "in the supplied pair manifest",
                    job_id=job_id,
                )
            )
        issues.extend(_check_identity(record))
        if preparation is not None:
            issues.extend(check_prepared_inputs(record, preparation))

        fingerprint = record.adapter_metadata.get(f"{_PREFIX}runtime_manifest_fingerprint")
        if fingerprint:
            manifest_fingerprints.add(str(fingerprint))

        status = record.adapter_metadata.get(f"{_PREFIX}engine_status")
        if status:
            engine_statuses[str(status)] = engine_statuses.get(str(status), 0) + 1

        if record.status is ExecutionStatus.SUCCESS:
            successes += 1
            verifications += 1
            issues.extend(_check_success(record))
            extractions += _extraction_count(record)
            continue

        failure = record.failure
        code = failure.code if failure is not None else None
        if code is None:  # pragma: no cover - the model forbids it
            issues.append(
                _issue(
                    IntegrityIssueCode.RESULT_UNKNOWN_FAILURE_CODE,
                    f"result {job_id} failed without saying why",
                    job_id=job_id,
                )
            )
            continue

        issues.extend(_check_failure(record))
        failure_counts[code.value] = failure_counts.get(code.value, 0) + 1
        if code in ALGORITHMIC_FAILURE_CODES:
            algorithmic += 1
            # An algorithm outcome still consumed the route: both sides were
            # extracted before the engine declined (spec section 27).
            verifications += 1
            extractions += identity.REQUIRED_EXTRACTION_COUNT
        elif code in BLOCKING_FAILURE_CODES:
            blocking += 1
            issues.append(
                _issue(
                    IntegrityIssueCode.RESULT_BLOCKING_FAILURE,
                    f"result {job_id} failed with {code.value}, which indicates "
                    "broken infrastructure rather than a biometric outcome",
                    job_id=job_id,
                    failure_code=code.value,
                )
            )
        else:
            blocking += 1
            issues.append(
                _issue(
                    IntegrityIssueCode.RESULT_UNKNOWN_FAILURE_CODE,
                    f"result {job_id} failed with {code.value}, which no policy "
                    "classifies as either algorithmic or blocking; classify it "
                    "deliberately rather than guessing",
                    job_id=job_id,
                    failure_code=code.value,
                )
            )

    if len(manifest_fingerprints) > 1:
        issues.append(
            _issue(
                IntegrityIssueCode.RESULT_RUNTIME_MISMATCH,
                "the stored results name more than one runtime closure: "
                f"{sorted(item[:12] for item in manifest_fingerprints)}; a run "
                "whose engine changed halfway is not one run",
            )
        )
    if (
        expected_runtime_manifest_fingerprint is not None
        and manifest_fingerprints
        and manifest_fingerprints != {expected_runtime_manifest_fingerprint}
    ):
        issues.append(
            _issue(
                IntegrityIssueCode.RESULT_RUNTIME_MISMATCH,
                "the stored results were produced under runtime closure "
                f"{sorted(item[:12] for item in manifest_fingerprints)}, and this "
                f"experiment is pinned to "
                f"{expected_runtime_manifest_fingerprint[:12]}...",
            )
        )

    inspected_utc = _utc_now()
    fingerprint = _validation_fingerprint(
        run=run,
        plan=plan,
        runtime_reference=runtime_reference,
        total=total,
        successes=successes,
        algorithmic=algorithmic,
        blocking=blocking,
        failure_counts=failure_counts,
        engine_statuses=engine_statuses,
        issues=tuple(issues),
        extractions=extractions,
        verifications=verifications,
    )
    return VeriFingerValidationReport(
        run_id=run.run_id,
        plan_id=plan.plan_id,
        total_results=total,
        successful_results=successes,
        algorithmic_failures=algorithmic,
        blocking_failures=blocking,
        failure_counts=failure_counts,
        issues=tuple(issues),
        logical_extraction_calls=extractions,
        verify_invocations=verifications,
        engine_status_counts=engine_statuses,
        validation_fingerprint=fingerprint,
        inspected_utc=inspected_utc,
    )


# ----------------------------------------------------------------- internals


def _issue(
    code: IntegrityIssueCode,
    message: str,
    *,
    severity: IntegritySeverity = IntegritySeverity.ERROR,
    job_id: str | None = None,
    **details: str,
) -> IntegrityIssue:
    return IntegrityIssue(
        code=code,
        severity=severity,
        message=message,
        job_id=job_id,
        details={str(k): str(v) for k, v in details.items()},
    )


def _check_run(
    run: RunDefinition, runtime_reference: RunRuntimeReference
) -> Iterable[IntegrityIssue]:
    """Was this run defined for this route, against a complete runtime?"""
    if run.algorithm.algorithm_id != identity.ALGORITHM_ID:
        yield _issue(
            IntegrityIssueCode.ALGORITHM_FINGERPRINT_MISMATCH,
            f"run {run.run_id} was defined for algorithm "
            f"{run.algorithm.algorithm_id!r}, not {identity.ALGORITHM_ID!r}",
        )
    if run.algorithm.adapter_id != identity.ADAPTER_ID:
        yield _issue(
            IntegrityIssueCode.ALGORITHM_FINGERPRINT_MISMATCH,
            f"run {run.run_id} was defined for adapter "
            f"{run.algorithm.adapter_id!r}, not {identity.ADAPTER_ID!r}",
        )
    if run.algorithm.implementation_version != identity.IMPLEMENTATION_VERSION:
        yield _issue(
            IntegrityIssueCode.ALGORITHM_FINGERPRINT_MISMATCH,
            f"run {run.run_id} names implementation version "
            f"{run.algorithm.implementation_version!r}, not "
            f"{identity.IMPLEMENTATION_VERSION!r}",
        )
    if run.algorithm.score_direction is not ScoreDirection.HIGHER_IS_BETTER:
        yield _issue(
            IntegrityIssueCode.ALGORITHM_FINGERPRINT_MISMATCH,
            "the VeriFinger score is higher_is_more_similar, which is "
            f"higher_is_better here, not {run.algorithm.score_direction.value!r}",
        )
    present = tuple(sorted(dict(runtime_reference.asset_sha256s)))
    if present != tuple(sorted(REQUIRED_RUNTIME_ASSET_ROLES)):
        yield _issue(
            IntegrityIssueCode.RESULT_RUNTIME_MISMATCH,
            f"run {run.run_id} is bound to runtime roles {list(present)}; this "
            f"route needs {sorted(REQUIRED_RUNTIME_ASSET_ROLES)}",
        )


def _check_input_set(
    *,
    run: RunDefinition,
    pairs: Mapping[PairId, ComparisonPair],
    preparation: PreparedInputExpectations,
    expected_input_set: ExpectedInputSet | None,
) -> Iterable[IntegrityIssue]:
    if expected_input_set is not None:
        if preparation.preparation_set_id != expected_input_set.preparation_set_id:
            yield _issue(
                IntegrityIssueCode.RESULT_PIPELINE_MISMATCH,
                f"run {run.run_id} was produced from input set "
                f"{preparation.preparation_set_id!r}, but this experiment is "
                f"defined against {expected_input_set.preparation_set_id!r}",
            )
        if preparation.transform_profile_id != expected_input_set.transform_profile_id:
            yield _issue(
                IntegrityIssueCode.RESULT_PIPELINE_MISMATCH,
                f"run {run.run_id} names transform profile "
                f"{preparation.transform_profile_id!r}, not "
                f"{expected_input_set.transform_profile_id!r}",
            )
        if int(preparation.target_ppi) != int(expected_input_set.target_ppi):
            yield _issue(
                IntegrityIssueCode.RESULT_PIPELINE_MISMATCH,
                f"run {run.run_id} targets {preparation.target_ppi} ppi, not "
                f"{expected_input_set.target_ppi}",
            )
        if len(preparation.entries) != int(expected_input_set.entry_count):
            yield _issue(
                IntegrityIssueCode.RESULT_PIPELINE_MISMATCH,
                f"the input set holds {len(preparation.entries)} entries, not "
                f"{expected_input_set.entry_count}",
            )
    if preparation.expected_source_ppi:
        yield from check_release_source_resolutions(
            pairs=pairs,
            preparation=preparation,
            expected_source_ppi=preparation.expected_source_ppi,
        )


def _check_identity(record: RawResultRecord) -> Iterable[IntegrityIssue]:
    """Does this result name the route, the version and the policy it should?"""
    job_id = record.job_id
    metadata = record.adapter_metadata

    expected = {
        f"{_PREFIX}algorithm_id": identity.ALGORITHM_ID,
        f"{_PREFIX}adapter_id": identity.ADAPTER_ID,
        f"{_PREFIX}adapter_version": identity.ADAPTER_VERSION,
        f"{_PREFIX}implementation_version": identity.IMPLEMENTATION_VERSION,
        f"{_PREFIX}vendor": identity.VENDOR,
        f"{_PREFIX}bridge_protocol": identity.BRIDGE_PROTOCOL,
        f"{_PREFIX}bridge_version": identity.BRIDGE_VERSION,
        f"{_PREFIX}integration_mode": identity.INTEGRATION_MODE,
        f"{_PREFIX}probe_side": "left",
        f"{_PREFIX}extraction_policy": "independent_both_sides",
        f"{_PREFIX}template_cache": "disabled",
        f"{_PREFIX}score_cache": "disabled",
        f"{_PREFIX}matching_speed": identity.MATCHING_SPEED,
        f"{_PREFIX}native_score_type": identity.NATIVE_SCORE_TYPE,
        f"{_PREFIX}score_transformation_by_fpbench": (
            identity.SCORE_TRANSFORMATION_BY_FPBENCH
        ),
        f"{_PREFIX}left_ppi": str(identity.REQUIRED_EFFECTIVE_PPI),
        f"{_PREFIX}right_ppi": str(identity.REQUIRED_EFFECTIVE_PPI),
    }
    for key, wanted in sorted(expected.items()):
        actual = metadata.get(key)
        if actual != wanted:
            yield _issue(
                IntegrityIssueCode.RESULT_METADATA_MISSING,
                f"result {job_id} records {key}={actual!r}, expected {wanted!r}",
                job_id=job_id,
            )

    forbidden = set(
        forbidden_metadata_present(
            metadata, additional=VERIFINGER_FORBIDDEN_METADATA_KEYS
        )
    ) | set(_forbidden_namespaced_keys(metadata))
    if forbidden:
        yield _issue(
            IntegrityIssueCode.RESULT_PIPELINE_MISMATCH,
            f"result {job_id} carries metadata a raw VeriFinger result may never "
            f"hold: {sorted(forbidden)}",
            job_id=job_id,
        )


def _forbidden_namespaced_keys(metadata: Mapping[str, str]) -> tuple[str, ...]:
    """Catch a forbidden name hiding behind this route's own prefix.

    The universal check matches keys exactly, which is right for it. This route
    namespaces everything it writes, so ``verifinger.threshold`` has to be
    refused for the same reason ``threshold`` is (spec section 31).
    """
    found = []
    for key in metadata:
        name = str(key)
        bare = name[len(_PREFIX) :] if name.startswith(_PREFIX) else name
        if bare in VERIFINGER_FORBIDDEN_METADATA_KEYS:
            found.append(name)
    return tuple(sorted(found))


def _check_success(record: RawResultRecord) -> Iterable[IntegrityIssue]:
    """Is a successful result well formed?

    Well formed, not *good*. There is no threshold here and no claim that a SELF
    comparison ought to score highly. A score of 0 passes every check below
    (docs/adr/0003, spec section 33).
    """
    job_id = record.job_id
    score = record.raw_score
    if score is None:  # pragma: no cover - the model forbids it
        yield _issue(
            IntegrityIssueCode.RESULT_SCORE_INVALID,
            f"result {job_id} succeeded without a score",
            job_id=job_id,
        )
        return
    if not math.isfinite(float(score)):
        yield _issue(
            IntegrityIssueCode.RESULT_SCORE_INVALID,
            f"result {job_id} carries a non-finite score",
            job_id=job_id,
        )
        return
    if float(score) != float(int(score)):
        # The heart of it. VeriFinger returns a Java int and fpbench transforms
        # nothing, so a stored score with a fractional part means something
        # normalised, scaled or calibrated it on the way in (spec section 11).
        yield _issue(
            IntegrityIssueCode.RESULT_SCORE_INVALID,
            f"result {job_id} stores {score!r}, which is not integer-valued; the "
            "native score is a Java int and fpbench applies no transformation",
            job_id=job_id,
        )

    metadata = record.adapter_metadata
    engine_status = metadata.get(f"{_PREFIX}engine_status")
    if engine_status not in identity.SCORE_BEARING_STATUSES:
        yield _issue(
            IntegrityIssueCode.RESULT_METADATA_MISSING,
            f"result {job_id} carries a score under engine status "
            f"{engine_status!r}, and only "
            f"{list(identity.SCORE_BEARING_STATUSES)} carry one",
            job_id=job_id,
        )
    count = metadata.get(f"{_PREFIX}extraction_count")
    if count != str(identity.REQUIRED_EXTRACTION_COUNT):
        yield _issue(
            IntegrityIssueCode.RESULT_METADATA_MISSING,
            f"result {job_id} records extraction_count={count!r}, expected "
            f"{identity.REQUIRED_EXTRACTION_COUNT}. Both sides of every "
            "comparison are extracted independently, SELF included "
            "(spec section 14)",
            job_id=job_id,
        )


def _check_failure(record: RawResultRecord) -> Iterable[IntegrityIssue]:
    """A failure carries a code and no score of any kind."""
    job_id = record.job_id
    if record.raw_score is not None:  # pragma: no cover - the model forbids it
        yield _issue(
            IntegrityIssueCode.RESULT_SCORE_INVALID,
            f"result {job_id} failed and still carries a score",
            job_id=job_id,
        )


def _extraction_count(record: RawResultRecord) -> int:
    try:
        return int(record.adapter_metadata.get(f"{_PREFIX}extraction_count", 0))
    except (TypeError, ValueError):
        return 0


def _validation_fingerprint(
    *,
    run: RunDefinition,
    plan: ExecutionPlan,
    runtime_reference: RunRuntimeReference,
    total: int,
    successes: int,
    algorithmic: int,
    blocking: int,
    failure_counts: Mapping[str, int],
    engine_statuses: Mapping[str, int],
    issues: tuple[IntegrityIssue, ...],
    extractions: int,
    verifications: int,
) -> str:
    """A digest of what this pass found, with no timestamp in it.

    The same files validated twice produce the same fingerprint, so a receipt can
    name the exact validation it rests on.
    """
    return stable_hash(
        {
            "schema": "verifinger_validation_fingerprint_v1",
            "run_fingerprint": run.run_fingerprint,
            "plan_fingerprint": plan.definition.plan_fingerprint,
            "runtime_reference_fingerprint": (
                runtime_reference.runtime_reference_fingerprint
            ),
            "total_results": total,
            "successful_results": successes,
            "algorithmic_failures": algorithmic,
            "blocking_failures": blocking,
            "failure_counts": dict(sorted(failure_counts.items())),
            "engine_status_counts": dict(sorted(engine_statuses.items())),
            "logical_extraction_calls": extractions,
            "verify_invocations": verifications,
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
        length=64,
    )


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()
