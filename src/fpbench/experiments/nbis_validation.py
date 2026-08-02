"""Checking that stored results really are what an NBIS run promised.

The core audit answers a question about *bookkeeping*: is there one readable
result per planned job, and does each one claim the right run, plan, pair and
profile? It cannot answer the question this module exists for, because answering
it means knowing what this route is — which two executables, which extraction
policy, which resolution, which tool options were deliberately not passed.
Putting that knowledge in ``execution`` would be exactly the algorithm-specific
branching docs/adr/0007 forbids, so it lives here, beside the experiment that
needs it.

Two distinctions carry the module.

**An algorithm that declines a print is not a broken run.** MINDTCT looking at a
print and producing no template is a recorded outcome with a code, and a run full
of them is still a run (docs/adr/0013). So is a comparison that outran its budget:
MINDTCT's work is unbounded in the input, and a print it cannot finish is a
property of the print rather than of the harness (spec section 36).

**An algorithm that never got the chance is a broken run.** A crashed process, a
rejected input, a BOZORTH3 that printed something other than one integer — every
one of these says the pipeline failed, not the biometrics. The inputs were
validated and checksummed before the run started and the build passed NIST's own
tests, so these cannot be properties of the data.

The subtle case is between them. ``TEMPLATE_EXTRACTION_FAILED`` covers both
"MINDTCT declined this print" and "MINDTCT claimed success and wrote an XYT
nothing can read". They are the same failure code and they are not the same
event, so the *detail* decides: an ``output_kind`` of ``invalid_extractor_output``
is broken infrastructure and blocks a receipt (spec sections 30 and 36).

Nothing here looks at whether a score is high or low. There is no threshold in
this module, a score of 0 is an ordinary success, and an algorithmic failure is
never turned into a NON_MATCH — in a later decision stage it will be
``UNDECIDABLE`` (docs/adr/0003, docs/adr/0006).
"""

from __future__ import annotations

import datetime as _dt
import math
from dataclasses import dataclass
from typing import Iterable, Mapping

from fpbench.adapters.nbis.adapter import (
    ADAPTER_ID,
    ALGORITHM_ID,
    IMPLEMENTATION_VERSION,
    RESULT_METADATA,
)
from fpbench.adapters.nbis.config import (
    BOZORTH3_ROLE,
    BUILD_MANIFEST_ROLE,
    MINDTCT_ROLE,
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

__all__ = [
    "NbisValidationReport",
    "ExpectedInputSet",
    "SD300_CANONICAL500_INPUT_SET",
    "validate_nbis_result_set",
    "ALGORITHMIC_FAILURE_CODES",
    "BLOCKING_FAILURE_CODES",
    "INVALID_EXTRACTOR_OUTPUT_KIND",
    "NBIS_FORBIDDEN_METADATA_KEYS",
    "FORBIDDEN_METADATA_KEYS",
    "REQUIRED_RUNTIME_ASSET_ROLES",
]

#: NBIS looked at the print and could not produce a template, or ran out of the
#: comparison's budget doing so. Real properties of real fingerprints; kept,
#: counted, and analysed in a later stage (docs/adr/0006, docs/adr/0013).
ALGORITHMIC_FAILURE_CODES: frozenset[FailureCode] = frozenset(
    {FailureCode.TEMPLATE_EXTRACTION_FAILED, FailureCode.TIMEOUT}
)

#: The comparison never happened as designed. Every one of these means the
#: harness, the environment or the input set is wrong, and none of them can be a
#: property of a dataset that has already been validated and checksummed.
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

#: The ``output_kind`` that turns an extraction failure from a biometric outcome
#: into a defect: MINDTCT exited zero and wrote something no XYT parser accepts.
INVALID_EXTRACTOR_OUTPUT_KIND = "invalid_extractor_output"

#: This route's own additions to the universal list. It publishes no template,
#: no minutiae and no XYT, so a result carrying one means the adapter changed
#: underneath the results (docs/adr/0050, spec section 33).
NBIS_FORBIDDEN_METADATA_KEYS: frozenset[str] = frozenset(
    {"template", "minutiae", "xyt", "template_path", "xyt_path", "score"}
)

FORBIDDEN_METADATA_KEYS: frozenset[str] = (
    UNIVERSAL_FORBIDDEN_METADATA_KEYS | NBIS_FORBIDDEN_METADATA_KEYS
)

#: Every role the runtime reference must carry. A bundle holding two of the three
#: is not this route's runtime, whatever the surviving files hash to
#: (docs/adr/0042).
REQUIRED_RUNTIME_ASSET_ROLES: tuple[str, ...] = (
    BOZORTH3_ROLE,
    BUILD_MANIFEST_ROLE,
    MINDTCT_ROLE,
)

#: The metadata every result must carry, and what it must say. Taken from the
#: adapter's own constant so the two cannot drift; the per-comparison keys
#: (minutiae counts, extraction count) are checked separately.
_EXPECTED_METADATA: Mapping[str, str] = dict(RESULT_METADATA)

_EXPECTED_EXTRACTION_COUNT = "2"


@dataclass(frozen=True, slots=True)
class ExpectedInputSet:
    """Which materialised input set a run is allowed to have been produced from.

    Supplied by the experiment, not assumed here: stage 7B produces no SD300 run
    at all, and a validator that hard-coded one set would have to be edited
    before it could ever be used on another (spec section 37).
    """

    preparation_set_id: str
    transform_profile_id: str
    target_ppi: int
    entry_count: int


#: The set the canonical SD300 route will use when stage 7C runs it. Written down
#: here so the check exists before the run does, and so 7C names a constant
#: rather than retyping four values (spec section 37).
SD300_CANONICAL500_INPUT_SET = ExpectedInputSet(
    preparation_set_id="prepset_be560e047991",
    transform_profile_id="canonical_gray8_500ppi_lanczos3_v1",
    target_ppi=500,
    entry_count=3000,
)


@dataclass(frozen=True, slots=True)
class NbisValidationReport:
    """What an NBIS-specific pass over a run's results found.

    ``algorithmic_failures`` and ``blocking_failures`` are counted separately on
    purpose: the first is data, the second is a defect. ``is_clean`` cares only
    about the second, plus anything that made a result unattributable.

    Satisfies ``AlgorithmValidationReport`` structurally, without inheriting from
    or importing any other algorithm's report — which is the point of the
    protocol (docs/adr/0040).
    """

    run_id: str
    plan_id: str

    total_results: int
    successful_results: int
    algorithmic_failures: int
    blocking_failures: int

    failure_counts: Mapping[str, int]
    issues: tuple[IntegrityIssue, ...]

    validation_fingerprint: str
    inspected_utc: str

    def __post_init__(self) -> None:
        from types import MappingProxyType

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
        one unreadable XYT is not.
        """
        return not self.blocking_failures and not any(
            issue.severity is IntegritySeverity.ERROR for issue in self.issues
        )

    @property
    def errors(self) -> tuple[IntegrityIssue, ...]:
        return tuple(
            issue for issue in self.issues if issue.severity is IntegritySeverity.ERROR
        )


def validate_nbis_result_set(
    *,
    run: RunDefinition,
    plan: ExecutionPlan,
    pairs: Mapping[PairId, ComparisonPair],
    images: Mapping[ImageId, ImageRecord],
    result_store: ResultStore,
    runtime_reference: RunRuntimeReference,
    preparation: PreparedInputExpectations | None = None,
    expected_input_set: ExpectedInputSet | None = None,
) -> NbisValidationReport:
    """Inspect every stored result of an NBIS run against this route's contract.

    Args:
        preparation: What the results must claim about the input set they were
            produced from. ``None`` for a run over untouched source images.
        expected_input_set: Which input set this experiment is entitled to have
            used. Checked against ``preparation`` when both are given.
    """
    issues: list[IntegrityIssue] = []
    failure_counts: dict[str, int] = {}

    total = 0
    successes = 0
    algorithmic = 0
    blocking = 0

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
            # Shared with every other algorithm: "this result names an artefact
            # that exists in this exact set" is not an NBIS question.
            issues.extend(check_prepared_inputs(record, preparation))

        if record.status is ExecutionStatus.SUCCESS:
            successes += 1
            issues.extend(_check_success(record))
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

        failure_counts[code.value] = failure_counts.get(code.value, 0) + 1
        if _is_corrupt_extractor_output(record):
            blocking += 1
            issues.append(
                _issue(
                    IntegrityIssueCode.RESULT_BLOCKING_FAILURE,
                    f"result {job_id} records an extraction failure whose cause is "
                    "unusable extractor output; mindtct exited successfully and "
                    "wrote an XYT nothing can read, which is broken infrastructure "
                    "rather than a biometric outcome",
                    job_id=job_id,
                    failure_code=code.value,
                )
            )
        elif code in ALGORITHMIC_FAILURE_CODES:
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
    )
    return NbisValidationReport(
        run_id=run.run_id,
        plan_id=plan.plan_id,
        total_results=total,
        successful_results=successes,
        algorithmic_failures=algorithmic,
        blocking_failures=blocking,
        failure_counts=failure_counts,
        issues=tuple(issues),
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
        details=details,
    )


def _check_run(
    run: RunDefinition, runtime_reference: RunRuntimeReference
) -> Iterable[IntegrityIssue]:
    """Was this run defined for this route, against a complete runtime?"""
    if run.algorithm.algorithm_id != ALGORITHM_ID:
        yield _issue(
            IntegrityIssueCode.ALGORITHM_FINGERPRINT_MISMATCH,
            f"run {run.run_id} was defined for {run.algorithm.algorithm_id!r}, not "
            f"{ALGORITHM_ID!r}; this validator does not apply to it",
        )
    if run.algorithm.adapter_id != ADAPTER_ID:
        yield _issue(
            IntegrityIssueCode.ALGORITHM_FINGERPRINT_MISMATCH,
            f"run {run.run_id} used adapter {run.algorithm.adapter_id!r}, not "
            f"{ADAPTER_ID!r}",
        )
    if run.algorithm.implementation_version != IMPLEMENTATION_VERSION:
        yield _issue(
            IntegrityIssueCode.ALGORITHM_FINGERPRINT_MISMATCH,
            f"run {run.run_id} names NBIS "
            f"{run.algorithm.implementation_version!r}, not "
            f"{IMPLEMENTATION_VERSION!r}",
        )

    present = set(dict(runtime_reference.asset_sha256s))
    missing = sorted(set(REQUIRED_RUNTIME_ASSET_ROLES) - present)
    if missing:
        yield _issue(
            IntegrityIssueCode.RESULT_RUNTIME_MISMATCH,
            f"the runtime reference holds no {missing}; this route's identity is "
            "both executables and the build manifest together",
        )

    dependencies = run.environment.dependencies
    for key, expected in (
        ("nbis.version", IMPLEMENTATION_VERSION),
        ("nbis.png_ppi_policy", "metadata_ignored_default_500"),
    ):
        actual = dependencies.get(key)
        if actual is None:
            yield _issue(
                IntegrityIssueCode.RESULT_METADATA_MISSING,
                f"the run environment records no {key}",
            )
        elif actual != expected:
            yield _issue(
                IntegrityIssueCode.RESULT_PIPELINE_MISMATCH,
                f"the run environment records {key}={actual!r}, expected "
                f"{expected!r}",
            )
    if not dependencies.get("nbis.build_manifest_fingerprint"):
        yield _issue(
            IntegrityIssueCode.RESULT_RUNTIME_MISMATCH,
            "the run environment records no NBIS build manifest fingerprint, so no "
            "result can be attributed to a certified build",
        )
    if not run.environment.runtime.get("fpbench.source.revision"):
        yield _issue(
            IntegrityIssueCode.RESULT_RUNTIME_MISMATCH,
            "the run environment records no fpbench source revision "
            "(docs/adr/0017)",
        )


def _check_input_set(
    *,
    run: RunDefinition,
    pairs: Mapping[PairId, ComparisonPair],
    preparation: PreparedInputExpectations,
    expected_input_set: ExpectedInputSet | None,
) -> Iterable[IntegrityIssue]:
    if run.execution_profile.profile_id != preparation.execution_profile_id:
        yield _issue(
            IntegrityIssueCode.EXECUTION_PROFILE_HASH_MISMATCH,
            f"run {run.run_id} used execution profile "
            f"{run.execution_profile.profile_id!r}, not "
            f"{preparation.execution_profile_id!r}",
        )
    if not preparation.entries:
        yield _issue(
            IntegrityIssueCode.RESULT_METADATA_MISSING,
            "the prepared-image set holds no entries, so no result can be checked "
            "against the artefacts it claims to have used",
        )
    elif preparation.expected_source_ppi:
        yield from check_release_source_resolutions(
            pairs=pairs,
            preparation=preparation,
            expected_source_ppi=preparation.expected_source_ppi,
        )

    if expected_input_set is None:
        return
    for label, actual, expected in (
        (
            "preparation_set_id",
            preparation.preparation_set_id,
            expected_input_set.preparation_set_id,
        ),
        (
            "transform_profile_id",
            preparation.transform_profile_id,
            expected_input_set.transform_profile_id,
        ),
        ("target_ppi", str(preparation.target_ppi), str(expected_input_set.target_ppi)),
        (
            "entry_count",
            str(len(preparation.entries)),
            str(expected_input_set.entry_count),
        ),
    ):
        if actual != expected:
            yield _issue(
                IntegrityIssueCode.RESULT_PIPELINE_MISMATCH,
                f"the run used {label}={actual!r}; this experiment is defined over "
                f"{expected!r}",
            )


def _check_identity(record: RawResultRecord) -> Iterable[IntegrityIssue]:
    """Does this result name the route and the options it should?"""
    job_id = record.job_id
    metadata = record.adapter_metadata

    if record.algorithm_id != ALGORITHM_ID:
        yield _issue(
            IntegrityIssueCode.ALGORITHM_FINGERPRINT_MISMATCH,
            f"result {job_id} names algorithm {record.algorithm_id!r}",
            job_id=job_id,
        )
    if record.score_direction is not ScoreDirection.HIGHER_IS_BETTER:
        yield _issue(
            IntegrityIssueCode.RESULT_PIPELINE_MISMATCH,
            f"result {job_id} declares score direction "
            f"{record.score_direction.value!r}",
            job_id=job_id,
        )

    for key, expected in _EXPECTED_METADATA.items():
        actual = metadata.get(key)
        if actual is None:
            yield _issue(
                IntegrityIssueCode.RESULT_METADATA_MISSING,
                f"result {job_id} does not record {key}",
                job_id=job_id,
            )
        elif actual != expected:
            yield _issue(
                IntegrityIssueCode.RESULT_PIPELINE_MISMATCH,
                f"result {job_id} records {key}={actual!r}, expected {expected!r}",
                job_id=job_id,
            )

    # Extraction count is only meaningful when both extractions happened. A
    # result whose failure *is* an extraction failure cannot report two of them,
    # and demanding it would force the adapter to invent a number.
    extraction_count = metadata.get("extraction_count")
    if record.status is ExecutionStatus.SUCCESS and extraction_count is None:
        yield _issue(
            IntegrityIssueCode.RESULT_METADATA_MISSING,
            f"result {job_id} does not record extraction_count",
            job_id=job_id,
        )
    elif extraction_count is not None and extraction_count != _EXPECTED_EXTRACTION_COUNT:
        yield _issue(
            IntegrityIssueCode.RESULT_PIPELINE_MISMATCH,
            f"result {job_id} records extraction_count={extraction_count!r}; both "
            "sides must be extracted independently, even for a SELF comparison",
            job_id=job_id,
        )

    for side in ("left", "right"):
        key = f"{side}_minutiae_count"
        value = metadata.get(key)
        if record.status is ExecutionStatus.SUCCESS and value is None:
            yield _issue(
                IntegrityIssueCode.RESULT_METADATA_MISSING,
                f"result {job_id} does not record {key}",
                job_id=job_id,
            )
        elif value is not None and not (value.isdigit() and value.isascii()):
            yield _issue(
                IntegrityIssueCode.RESULT_PIPELINE_MISMATCH,
                f"result {job_id} records {key}={value!r}, which is not a count",
                job_id=job_id,
            )

    if record.artifacts:
        yield _issue(
            IntegrityIssueCode.RESULT_UNEXPECTED_ARTIFACT,
            f"result {job_id} carries {len(record.artifacts)} artefact(s); this "
            "route publishes no template, no XYT and no map file",
            job_id=job_id,
        )

    present = forbidden_metadata_present(
        metadata, additional=NBIS_FORBIDDEN_METADATA_KEYS
    )
    if present:
        yield _issue(
            IntegrityIssueCode.RESULT_PIPELINE_MISMATCH,
            f"result {job_id} carries metadata a raw result may never hold: "
            f"{sorted(present)}",
            job_id=job_id,
        )


def _check_success(record: RawResultRecord) -> Iterable[IntegrityIssue]:
    """Is a successful result well formed?

    Well formed, not *good*. There is no threshold here and no claim that a SELF
    comparison ought to score highly. In particular a score of 0 passes every
    check below: BOZORTH3 returns 0 when a side has fewer than ten minutiae, and
    that is an outcome rather than a defect (docs/adr/0006, spec section 26).
    """
    job_id = record.job_id
    score = record.raw_score
    if score is None or not math.isfinite(float(score)):
        yield _issue(
            IntegrityIssueCode.RESULT_SCORE_INVALID,
            f"result {job_id} is a success with no usable score",
            job_id=job_id,
        )
        return
    value = float(score)
    if value < 0:
        yield _issue(
            IntegrityIssueCode.RESULT_SCORE_INVALID,
            f"result {job_id} scored below zero; a BOZORTH3 score is a "
            "non-negative integer",
            job_id=job_id,
        )
    if value != int(value):
        yield _issue(
            IntegrityIssueCode.RESULT_SCORE_INVALID,
            f"result {job_id} stored a fractional score; BOZORTH3 prints integers",
            job_id=job_id,
        )
    if record.failure is not None:
        yield _issue(
            IntegrityIssueCode.RESULT_SCORE_INVALID,
            f"result {job_id} carries both a score and a failure",
            job_id=job_id,
        )


def _is_corrupt_extractor_output(record: RawResultRecord) -> bool:
    failure = record.failure
    if failure is None or failure.code is not FailureCode.TEMPLATE_EXTRACTION_FAILED:
        return False
    return dict(failure.details).get("output_kind") == INVALID_EXTRACTOR_OUTPUT_KIND


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
) -> str:
    """A digest of what this pass found, with no timestamp in it.

    The same files validated twice produce the same fingerprint, so a receipt can
    name the exact validation it rests on.
    """
    return stable_hash(
        {
            "schema": "nbis_validation_fingerprint_v1",
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
