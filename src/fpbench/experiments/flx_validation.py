"""What a finished flx run's stored results have to say for themselves.

The engine cannot decide which recorded failures are the algorithm declining a
print and which mean the harness broke, so it asks the algorithm — and this is
the flx answer (docs/adr/0013).  It is also where the two claims that only make
sense for this route are checked over all 6,000 rows:

**Every success carries a Decimal, exactly.**  The stored ``raw_score`` is an
IEEE double and ``flx.raw_score_decimal`` is its canonical 17-significant-digit
text.  Seventeen digits always recovers a double exactly, so the two are the same
number — and this pass re-derives the text from the stored double rather than
trusting the adapter that wrote it.  A row where they disagree means something
rounded (docs/adr/0077, docs/adr/0073).

**Every comparison performed two independent extractions.**  Each result records
how many preprocess calls, logical extractions and comparison calls actually
produced it, measured from the integration's own counters.  A SELF row that
reported one extraction would mean a cache had been introduced, and it is a
finding here rather than an assumption in a docstring (spec sections 9 and 34).

There is no threshold in this module, no notion of a score being high or low,
and no comparison with any other algorithm.  A score of 0 is a perfectly good
success (docs/adr/0003, docs/adr/0076).
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Iterable, Mapping

from fpbench.experiments.flx_adapter import RAW_SCORE_DECIMAL_METADATA_KEY
from fpbench.experiments.flx_adapter import RUNTIME_ASSET_ROLES
from fpbench.experiments.flx_failure_mapping import ALGORITHMIC_FAILURE_CODES
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
from fpbench.flx import identity
from fpbench.flx.score import canonical_decimal_text
from fpbench.storage.result_store import ResultStore

__all__ = [
    "FlxValidationReport",
    "ExpectedInputSet",
    "SD300_CANONICAL500_INPUT_SET",
    "validate_flx_result_set",
    "ALGORITHMIC_FAILURE_CODES",
    "BLOCKING_FAILURE_CODES",
    "FLX_FORBIDDEN_METADATA_KEYS",
    "FORBIDDEN_METADATA_KEYS",
    "REQUIRED_RUNTIME_ASSET_ROLES",
]

#: The comparison never happened as designed. Every one of these means the
#: harness, the environment or the input set is wrong, and none of them can be a
#: property of a dataset that has already been validated and checksummed.
BLOCKING_FAILURE_CODES: frozenset[FailureCode] = frozenset(
    {
        FailureCode.INPUT_INVALID,
        FailureCode.UNSUPPORTED_RESOLUTION,
        FailureCode.QUALITY_REJECTED,
        FailureCode.NO_SCORE,
        FailureCode.DEPENDENCY_MISSING,
        FailureCode.INTERNAL_ERROR,
    }
)

#: This route's own additions to the universal list. It publishes no embedding,
#: no tensor and no representation, so a result carrying one means the adapter
#: changed underneath the results (spec section 15).
FLX_FORBIDDEN_METADATA_KEYS: frozenset[str] = frozenset(
    {
        "embedding",
        "representation",
        "texture",
        "texture_vector",
        "texture_embedding",
        "minutia_vector",
        "minutia_embedding",
        "tensor",
        "model_input",
        "score",
        "threshold",
        "decision",
        "eligibility",
        "ground_truth",
        "sourceafis_score",
        "nbis_score",
        "sourceafis_result",
        "nbis_result",
    }
)

FORBIDDEN_METADATA_KEYS: frozenset[str] = (
    UNIVERSAL_FORBIDDEN_METADATA_KEYS | FLX_FORBIDDEN_METADATA_KEYS
)

#: Every role the runtime reference must carry. A bundle holding two of the
#: three is not this route's runtime, whatever the surviving files hash to
#: (docs/adr/0042, docs/adr/0077).
REQUIRED_RUNTIME_ASSET_ROLES: tuple[str, ...] = tuple(sorted(RUNTIME_ASSET_ROLES))

#: Two preprocess calls, two logical extractions and one comparison per stored
#: result, whatever the pair kind (spec section 9).
_EXPECTED_PREPROCESS_CALLS = "2"
_EXPECTED_LOGICAL_EXTRACTIONS = "2"
_EXPECTED_COMPARISON_CALLS = "1"
_EXPECTED_PHYSICAL_FORWARD_ROWS = str(2 * identity.INFERENCE_BATCH_ROWS)


@dataclass(frozen=True, slots=True)
class ExpectedInputSet:
    """Which materialised input set a run is allowed to have been produced from."""

    preparation_set_id: str
    transform_profile_id: str
    target_ppi: int
    entry_count: int


#: The set Stage 6A materialised and Stage 8C reads. Written down so the check
#: exists independently of the experiment configuration that also names it.
SD300_CANONICAL500_INPUT_SET = ExpectedInputSet(
    preparation_set_id="prepset_be560e047991",
    transform_profile_id="canonical_gray8_500ppi_lanczos3_v1",
    target_ppi=500,
    entry_count=3000,
)


@dataclass(frozen=True, slots=True)
class FlxValidationReport:
    """What an flx-specific pass over a run's results found.

    ``algorithmic_failures`` and ``blocking_failures`` are counted separately on
    purpose: the first is data, the second is a defect. ``is_clean`` cares only
    about the second, plus anything that made a result unattributable.

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
    #: summary can publish both counts without recomputing them (docs/adr/0075).
    preprocess_calls: int
    logical_extraction_calls: int
    physical_forward_rows: int
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
        object.__setattr__(self, "issues", tuple(self.issues))

    @property
    def is_clean(self) -> bool:
        """True when nothing blocks a research receipt.

        A run with forty extraction failures and no issues is clean. A run with
        one result whose Decimal text does not match its stored double is not.
        """
        return not self.blocking_failures and not any(
            issue.severity is IntegritySeverity.ERROR for issue in self.issues
        )

    @property
    def errors(self) -> tuple[IntegrityIssue, ...]:
        return tuple(
            issue for issue in self.issues if issue.severity is IntegritySeverity.ERROR
        )


def validate_flx_result_set(
    *,
    run: RunDefinition,
    plan: ExecutionPlan,
    pairs: Mapping[PairId, ComparisonPair],
    images: Mapping[ImageId, ImageRecord],
    result_store: ResultStore,
    runtime_reference: RunRuntimeReference,
    preparation: PreparedInputExpectations | None = None,
    expected_input_set: ExpectedInputSet | None = None,
) -> FlxValidationReport:
    """Inspect every stored result of an flx run against this route's contract."""
    issues: list[IntegrityIssue] = []
    failure_counts: dict[str, int] = {}

    total = 0
    successes = 0
    algorithmic = 0
    blocking = 0
    preprocess_calls = 0
    logical_extractions = 0
    comparison_calls = 0

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
                    f"result {job_id} covers pair {record.pair_id}, which is not in "
                    "the supplied pair manifest",
                    job_id=job_id,
                )
            )
        issues.extend(_check_identity(record))
        if preparation is not None:
            issues.extend(check_prepared_inputs(record, preparation))

        if record.status is ExecutionStatus.SUCCESS:
            successes += 1
            issues.extend(_check_success(record))
            counted = _operation_counts(record)
            preprocess_calls += counted[0]
            logical_extractions += counted[1]
            comparison_calls += counted[2]
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

    inspected_utc = _utc_now()
    physical_rows = logical_extractions * identity.INFERENCE_BATCH_ROWS
    fingerprint = _validation_fingerprint(
        run=run,
        plan=plan,
        runtime_reference=runtime_reference,
        total=total,
        successes=successes,
        algorithmic=algorithmic,
        blocking=blocking,
        failure_counts=failure_counts,
        issues=tuple(issues),
        preprocess_calls=preprocess_calls,
        logical_extractions=logical_extractions,
        comparison_calls=comparison_calls,
    )
    return FlxValidationReport(
        run_id=run.run_id,
        plan_id=plan.plan_id,
        total_results=total,
        successful_results=successes,
        algorithmic_failures=algorithmic,
        blocking_failures=blocking,
        failure_counts=failure_counts,
        issues=tuple(issues),
        preprocess_calls=preprocess_calls,
        logical_extraction_calls=logical_extractions,
        physical_forward_rows=physical_rows,
        comparison_calls=comparison_calls,
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
    if run.algorithm.score_direction is not ScoreDirection.HIGHER_IS_BETTER:
        yield _issue(
            IntegrityIssueCode.ALGORITHM_FINGERPRINT_MISMATCH,
            "the flx score is higher_is_more_similar, which is "
            f"higher_is_better here, not {run.algorithm.score_direction.value!r}",
        )
    present = tuple(sorted(dict(runtime_reference.asset_sha256s)))
    if present != REQUIRED_RUNTIME_ASSET_ROLES:
        yield _issue(
            IntegrityIssueCode.RESULT_RUNTIME_MISMATCH,
            f"run {run.run_id} is bound to runtime roles {list(present)}; this "
            f"route needs {list(REQUIRED_RUNTIME_ASSET_ROLES)}",
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
    # Which resolution each release was scaled *from*, joined back through the
    # pair manifest rather than read off adapter metadata — which by
    # construction says one value for every release after canonicalisation
    # (docs/adr/0032). Skipped when the run declares no expectation, exactly as
    # the NBIS validator does.
    if preparation.expected_source_ppi:
        yield from check_release_source_resolutions(
            pairs=pairs,
            preparation=preparation,
            expected_source_ppi=preparation.expected_source_ppi,
        )


def _check_identity(record: RawResultRecord) -> Iterable[IntegrityIssue]:
    """Does this result name the route, the profiles and the batch rule it should?"""
    job_id = record.job_id
    metadata = record.adapter_metadata

    expected = {
        "flx.algorithm_id": identity.ALGORITHM_ID,
        "flx.adapter_id": identity.ADAPTER_ID,
        "flx.adapter_version": str(identity.ADAPTER_VERSION),
        "flx.runtime_profile_id": identity.RUNTIME_PROFILE_ID,
        "flx.preprocessing_profile_id": identity.PREPROCESSING_PROFILE_ID,
        "flx.representation_profile_id": identity.REPRESENTATION_PROFILE_ID,
        "flx.score_profile_id": identity.SCORE_PROFILE_ID,
        "flx.score_serialization_profile_id": identity.SCORE_SERIALIZATION_PROFILE_ID,
        "flx.inference_batch_rows": str(identity.INFERENCE_BATCH_ROWS),
        "flx.inference_batch_rule": identity.INFERENCE_BATCH_RULE,
        "flx.represented_row": str(identity.REPRESENTED_ROW),
        "flx.side_independence": "separate_preprocess_and_extract_per_side",
    }
    for key, wanted in sorted(expected.items()):
        actual = metadata.get(key)
        if actual != wanted:
            yield _issue(
                IntegrityIssueCode.RESULT_METADATA_MISSING,
                f"result {job_id} records {key}={actual!r}, expected {wanted!r}",
                job_id=job_id,
            )

    # The profile fingerprints must be what this source produces. A result whose
    # transform or comparator fingerprint moved means something else entirely
    # (docs/adr/0077).
    from fpbench.flx.preprocessing import build_preprocessing_profile
    from fpbench.flx.representation import build_representation_profile
    from fpbench.flx.score import build_score_profile

    for key, profile in (
        ("flx.preprocessing_profile_fingerprint", build_preprocessing_profile()),
        ("flx.representation_profile_fingerprint", build_representation_profile()),
        ("flx.score_profile_fingerprint", build_score_profile()),
    ):
        actual = metadata.get(key)
        if actual != profile.fingerprint:
            yield _issue(
                IntegrityIssueCode.RESULT_METADATA_MISSING,
                f"result {job_id} records {key}={str(actual)[:12]}..., but this "
                f"source produces {profile.fingerprint[:12]}...",
                job_id=job_id,
            )

    forbidden = set(
        forbidden_metadata_present(metadata, additional=FLX_FORBIDDEN_METADATA_KEYS)
    ) | set(_forbidden_namespaced_keys(metadata))
    if forbidden:
        yield _issue(
            IntegrityIssueCode.RESULT_PIPELINE_MISMATCH,
            f"result {job_id} carries metadata a raw flx result may never hold: "
            f"{sorted(forbidden)}",
            job_id=job_id,
        )


def _forbidden_namespaced_keys(metadata: Mapping[str, str]) -> tuple[str, ...]:
    """Catch a forbidden name hiding behind this route's own ``flx.`` prefix.

    The universal check matches keys exactly, which is right for it. This route
    namespaces everything it writes, so ``flx.embedding`` has to be refused for
    the same reason ``embedding`` is (spec section 15).
    """
    found = []
    for key in metadata:
        name = str(key)
        bare = name[4:] if name.startswith("flx.") else name
        if bare in FLX_FORBIDDEN_METADATA_KEYS:
            found.append(name)
    return tuple(sorted(found))


def _check_success(record: RawResultRecord) -> Iterable[IntegrityIssue]:
    """Is a successful result well formed?

    Well formed, not *good*. There is no threshold here and no claim that a SELF
    comparison ought to score highly. A score of 0 passes every check below, and
    so does a negative one (docs/adr/0003, docs/adr/0076).
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

    text = record.adapter_metadata.get(RAW_SCORE_DECIMAL_METADATA_KEY)
    if not text:
        yield _issue(
            IntegrityIssueCode.RESULT_SCORE_INVALID,
            f"result {job_id} carries no canonical decimal score; the general "
            "schema stores the IEEE double and this key stores the exact text "
            "it serialises to (docs/adr/0077)",
            job_id=job_id,
        )
        return
    try:
        stored = Decimal(str(text))
    except (InvalidOperation, TypeError, ValueError):
        yield _issue(
            IntegrityIssueCode.RESULT_SCORE_INVALID,
            f"result {job_id} carries {text!r}, which is not a decimal",
            job_id=job_id,
        )
        return
    if not stored.is_finite():
        yield _issue(
            IntegrityIssueCode.RESULT_SCORE_INVALID,
            f"result {job_id} carries a non-finite score {text!r}",
            job_id=job_id,
        )
        return

    # The heart of it: the text is re-derived from the stored double rather than
    # compared with itself. Seventeen significant digits always recovers a
    # double exactly, so any disagreement means something rounded.
    rederived = canonical_decimal_text(float(score))
    if rederived != str(text):
        yield _issue(
            IntegrityIssueCode.RESULT_SCORE_INVALID,
            f"result {job_id} stores {score!r}, which serialises to {rederived}, "
            f"but records {text}; the two are not the same number",
            job_id=job_id,
        )
    if float(stored) != float(score):
        yield _issue(
            IntegrityIssueCode.RESULT_SCORE_INVALID,
            f"result {job_id}: the recorded decimal does not round-trip to the "
            "stored double",
            job_id=job_id,
        )

    tolerance = Decimal(identity.SCORE_RANGE_VALIDATION_TOLERANCE)
    minimum = Decimal(identity.SCORE_MINIMUM) - tolerance
    maximum = Decimal(identity.SCORE_MAXIMUM) + tolerance
    if not minimum <= stored <= maximum:
        yield _issue(
            IntegrityIssueCode.RESULT_SCORE_INVALID,
            f"result {job_id} scores {text}, outside "
            f"[{identity.SCORE_MINIMUM}, {identity.SCORE_MAXIMUM}] by more than "
            f"the {identity.SCORE_RANGE_VALIDATION_TOLERANCE} float32 "
            f"normalization allowance under "
            f"{identity.SCORE_RANGE_VALIDATION_POLICY}",
            job_id=job_id,
        )

    yield from _check_operation_counts(record)


def _check_failure(record: RawResultRecord) -> Iterable[IntegrityIssue]:
    """A failure carries a code, a stage and no score of any kind."""
    job_id = record.job_id
    if record.raw_score is not None:  # pragma: no cover - the model forbids it
        yield _issue(
            IntegrityIssueCode.RESULT_SCORE_INVALID,
            f"result {job_id} failed and still carries a score",
            job_id=job_id,
        )
    if RAW_SCORE_DECIMAL_METADATA_KEY in record.adapter_metadata:
        yield _issue(
            IntegrityIssueCode.RESULT_SCORE_INVALID,
            f"result {job_id} failed and still carries a canonical decimal score",
            job_id=job_id,
        )


def _check_operation_counts(record: RawResultRecord) -> Iterable[IntegrityIssue]:
    """Two preprocess calls, two logical extractions, one comparison.

    Recorded per result from the integration's own counters, so SELF
    independence is proved by observation for every one of the 6,000 rows rather
    than asserted once in a test (spec sections 9 and 34).
    """
    job_id = record.job_id
    metadata = record.adapter_metadata
    for key, wanted in (
        ("flx.preprocess_calls", _EXPECTED_PREPROCESS_CALLS),
        ("flx.logical_extraction_calls", _EXPECTED_LOGICAL_EXTRACTIONS),
        ("flx.physical_forward_rows", _EXPECTED_PHYSICAL_FORWARD_ROWS),
        ("flx.comparison_calls", _EXPECTED_COMPARISON_CALLS),
    ):
        actual = metadata.get(key)
        if actual != wanted:
            yield _issue(
                IntegrityIssueCode.RESULT_METADATA_MISSING,
                f"result {job_id} records {key}={actual!r}, expected {wanted!r}. "
                "Both sides of every comparison are preprocessed and extracted "
                "independently, SELF included (spec section 9)",
                job_id=job_id,
            )


def _operation_counts(record: RawResultRecord) -> tuple[int, int, int]:
    metadata = record.adapter_metadata

    def count(key: str) -> int:
        try:
            return int(metadata.get(key, 0))
        except (TypeError, ValueError):
            return 0

    return (
        count("flx.preprocess_calls"),
        count("flx.logical_extraction_calls"),
        count("flx.comparison_calls"),
    )


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
    issues: tuple[IntegrityIssue, ...],
    preprocess_calls: int,
    logical_extractions: int,
    comparison_calls: int,
) -> str:
    """A digest of what this pass found, with no timestamp in it.

    The same files validated twice produce the same fingerprint, so a receipt can
    name the exact validation it rests on.
    """
    return stable_hash(
        {
            "schema": "flx_validation_fingerprint_v1",
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
            "preprocess_calls": preprocess_calls,
            "logical_extraction_calls": logical_extractions,
            "physical_forward_rows": logical_extractions
            * identity.INFERENCE_BATCH_ROWS,
            "comparison_calls": comparison_calls,
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
