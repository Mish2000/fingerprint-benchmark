"""Checking that 6,000 stored results really are what a SourceAFIS run promised.

The core audit answers a question about *bookkeeping*: is there one readable
result per planned job, and does each one claim the right run, plan, pair and
profile? It cannot answer the question this module exists for, because
answering it means knowing what SourceAFIS is — which executable, which
extraction policy, which resolution each release is entitled to. Putting that
knowledge in ``execution`` would be exactly the algorithm-specific branching
docs/adr/0007 forbids, so it lives here, in the application layer, beside the
experiment that needs it.

Two distinctions carry the whole module:

**An algorithm that declines a print is not a broken run.** SourceAFIS failing
to extract a template, or failing to match two templates it did extract, is a
recorded outcome with a code, and a run full of them is still a run
(docs/adr/0013). Those are counted and reported, never hidden and never turned
into a score.

**An algorithm that never got the chance is a broken run.** A crashed JVM, a
timeout, a rejected resolution, an image that would not decode — every one of
these says the pipeline failed, not the biometrics. The inputs were validated
and checksummed before the run started and all three resolutions passed a smoke
test, so these cannot be properties of the data; they are properties of the
harness, and they block a research receipt outright.

Nothing here looks at whether a score is high or low. There is no threshold in
this module and there will not be one until a decision profile exists
(docs/adr/0003).
"""

from __future__ import annotations

import datetime as _dt
import math
from dataclasses import dataclass
from typing import Iterable, Mapping

from fpbench.adapters.sourceafis_java.adapter import (
    ADAPTER_ID,
    ALGORITHM_ID,
    PIPELINE_METADATA,
)
from fpbench.adapters.sourceafis_java.config import (
    BRIDGE_JAR_ROLE,
    EXPECTED_BRIDGE_PROTOCOL,
    EXPECTED_BRIDGE_VERSION,
    EXPECTED_SOURCEAFIS_VERSION,
)
from fpbench.core.enums import (
    ExecutionStatus,
    FailureCode,
    IntegrityIssueCode,
    IntegritySeverity,
    ScoreDirection,
)
from fpbench.core.errors import ConfigurationError, StorageError
from fpbench.core.execution_plan_models import ExecutionPlan
from fpbench.core.identifiers import ImageId, PairId
from fpbench.core.models import ComparisonPair, ImageRecord
from fpbench.core.result_models import RawResultRecord, RunDefinition
from fpbench.core.run_state_models import IntegrityIssue
from fpbench.core.runtime_models import RunRuntimeReference
from fpbench.core.serialization import stable_hash
from fpbench.datasets.sd300 import ppi_policy
from fpbench.experiments.prepared_input_validation import (
    CanonicalPreparationExpectations,
    PreparedInputExpectations,
)
from fpbench.storage.result_store import ResultStore

__all__ = [
    "SourceAfisValidationReport",
    # Re-exported from fpbench.experiments.prepared_input_validation, where the
    # model now lives: what a result must claim about the input set it names is
    # the same question for every algorithm (spec section 25).
    "CanonicalPreparationExpectations",
    "PreparedInputExpectations",
    "validate_sourceafis_result_set",
    "ALGORITHMIC_FAILURE_CODES",
    "BLOCKING_FAILURE_CODES",
    "FORBIDDEN_METADATA_KEYS",
]

#: The algorithm looked at the print and could not produce a template, or could
#: not match two it did produce. A real property of real fingerprints; kept,
#: counted, and analysed in a later stage (docs/adr/0006).
ALGORITHMIC_FAILURE_CODES: frozenset[FailureCode] = frozenset(
    {FailureCode.TEMPLATE_EXTRACTION_FAILED, FailureCode.MATCHING_FAILED}
)

#: The comparison never happened as designed. Every one of these means the
#: harness, the environment or the provenance is wrong, and none of them can be
#: a property of a dataset that has already been validated and checksummed.
BLOCKING_FAILURE_CODES: frozenset[FailureCode] = frozenset(
    {
        FailureCode.INPUT_INVALID,
        FailureCode.IMAGE_DECODE_FAILED,
        FailureCode.PREPARATION_FAILED,
        FailureCode.UNSUPPORTED_RESOLUTION,
        FailureCode.PROCESS_CRASHED,
        FailureCode.TIMEOUT,
        FailureCode.DEPENDENCY_MISSING,
        FailureCode.INTERNAL_ERROR,
        FailureCode.NO_SCORE,
        FailureCode.QUALITY_REJECTED,
    }
)

#: Keys that would mean an adapter had made a decision. Their absence is
#: checked rather than assumed, because the one thing a raw result may never
#: contain is an answer (docs/adr/0003, docs/adr/0010).
FORBIDDEN_METADATA_KEYS: frozenset[str] = frozenset(
    {
        "threshold",
        "decision",
        "is_match",
        "matched",
        "ground_truth",
        "protocol_stage",
        "subject_id",
        "template",
        "minutiae",
    }
)

_EXPECTED_METADATA = {
    "sourceafis_version": EXPECTED_SOURCEAFIS_VERSION,
    "bridge_version": EXPECTED_BRIDGE_VERSION,
    "bridge_protocol": EXPECTED_BRIDGE_PROTOCOL,
    "integration_mode": PIPELINE_METADATA["integration_mode"],
    "dpi_policy": PIPELINE_METADATA["dpi_policy"],
    "probe_side": PIPELINE_METADATA["probe_side"],
    "template_cache": "disabled",
    "extraction_policy": "independent_both_sides",
}

_EXPECTED_EXTRACTION_COUNT = "2"


@dataclass(frozen=True, slots=True)
class SourceAfisValidationReport:
    """What a SourceAFIS-specific pass over a run's results found.

    ``algorithmic_failures`` and ``blocking_failures`` are counted separately
    on purpose: the first is data, the second is a defect. ``is_clean`` cares
    only about the second, plus anything that made a result unattributable.
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

        A run with 40 template-extraction failures and no issues is clean. A
        run with one timeout is not.
        """
        return not self.blocking_failures and not any(
            issue.severity is IntegritySeverity.ERROR for issue in self.issues
        )

    @property
    def errors(self) -> tuple[IntegrityIssue, ...]:
        return tuple(
            issue for issue in self.issues if issue.severity is IntegritySeverity.ERROR
        )


def validate_sourceafis_result_set(
    *,
    run: RunDefinition,
    plan: ExecutionPlan,
    pairs: Mapping[PairId, ComparisonPair],
    images: Mapping[ImageId, ImageRecord],
    result_store: ResultStore,
    runtime_reference: RunRuntimeReference,
    preparation: CanonicalPreparationExpectations | None = None,
) -> SourceAfisValidationReport:
    """Inspect every stored result of a SourceAFIS run against its contract.

    Args:
        preparation: What the results must claim about the input set they were
            produced from. ``None`` for a run whose images were passed through
            untouched; supplying it turns on the whole of spec section 75.
    """
    issues: list[IntegrityIssue] = []
    failure_counts: dict[str, int] = {}

    total = 0
    successes = 0
    algorithmic = 0
    blocking = 0

    expected_revision = run.environment.runtime.get("fpbench.source.revision")
    expected_jar_sha = dict(runtime_reference.asset_sha256s).get(BRIDGE_JAR_ROLE)

    if run.algorithm.algorithm_id != ALGORITHM_ID:
        issues.append(
            _issue(
                IntegrityIssueCode.ALGORITHM_FINGERPRINT_MISMATCH,
                f"run {run.run_id} was defined for {run.algorithm.algorithm_id!r}, "
                f"not {ALGORITHM_ID!r}; this validator does not apply to it",
            )
        )
    if run.algorithm.adapter_id != ADAPTER_ID:
        issues.append(
            _issue(
                IntegrityIssueCode.ALGORITHM_FINGERPRINT_MISMATCH,
                f"run {run.run_id} used adapter {run.algorithm.adapter_id!r}, not "
                f"{ADAPTER_ID!r}",
            )
        )
    if expected_jar_sha is None:
        issues.append(
            _issue(
                IntegrityIssueCode.RESULT_RUNTIME_MISMATCH,
                f"the runtime reference holds no {BRIDGE_JAR_ROLE!r} asset, so no "
                "result can be checked against the executable that produced it",
            )
        )
    if not expected_revision:
        issues.append(
            _issue(
                IntegrityIssueCode.RESULT_RUNTIME_MISMATCH,
                "the run environment records no fpbench source revision "
                "(docs/adr/0017)",
            )
        )
    if preparation is not None:
        if run.execution_profile.profile_id != preparation.execution_profile_id:
            issues.append(
                _issue(
                    IntegrityIssueCode.EXECUTION_PROFILE_HASH_MISMATCH,
                    f"run {run.run_id} used execution profile "
                    f"{run.execution_profile.profile_id!r}, not "
                    f"{preparation.execution_profile_id!r}",
                )
            )
        if not preparation.entries:
            issues.append(
                _issue(
                    IntegrityIssueCode.RESULT_METADATA_MISSING,
                    "the prepared-image set holds no entries, so no result can be "
                    "checked against the artefacts it claims to have used",
                )
            )
        elif preparation.expected_source_ppi:
            issues.extend(
                _check_release_source_resolutions(
                    pairs=pairs,
                    preparation=preparation,
                    expected_source_ppi=preparation.expected_source_ppi,
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
        pair = pairs.get(planned.job.pair_id)
        issues.extend(
            _check_identity(
                record,
                expected_revision=expected_revision,
                expected_jar_sha=expected_jar_sha,
                runtime_reference=runtime_reference,
            )
        )
        issues.extend(_check_resolution(record, pair, images, preparation))
        if preparation is not None:
            issues.extend(_check_preparation(record, preparation))

        if record.status is ExecutionStatus.SUCCESS:
            successes += 1
            issues.extend(_check_success(record))
            continue

        code = record.failure.code if record.failure is not None else None
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

    return SourceAfisValidationReport(
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


def _check_identity(
    record: RawResultRecord,
    *,
    expected_revision: str | None,
    expected_jar_sha: str | None,
    runtime_reference: RunRuntimeReference,
) -> Iterable[IntegrityIssue]:
    """Does this result name the pipeline and the executable it should?"""
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

    for key, expected in (
        ("runtime_bundle_id", runtime_reference.bundle_id),
        ("runtime_bundle_fingerprint", runtime_reference.bundle_fingerprint),
        ("bridge_jar_sha256", expected_jar_sha),
        ("fpbench_source_revision", expected_revision),
    ):
        if expected is None:
            continue  # already reported once, at run level
        actual = metadata.get(key)
        if actual is None:
            yield _issue(
                IntegrityIssueCode.RESULT_RUNTIME_MISMATCH,
                f"result {job_id} does not record {key}; it cannot be attributed "
                "to the executable that produced it",
                job_id=job_id,
            )
        elif actual != expected:
            yield _issue(
                IntegrityIssueCode.RESULT_RUNTIME_MISMATCH,
                f"result {job_id} records {key}={actual[:16]}..., expected "
                f"{str(expected)[:16]}...",
                job_id=job_id,
            )

    # Extraction count is only meaningful when extraction happened. A result
    # whose failure *is* an extraction failure cannot report two of them, and
    # demanding it would force the adapter to invent a number.
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

    if record.artifacts:
        yield _issue(
            IntegrityIssueCode.RESULT_UNEXPECTED_ARTIFACT,
            f"result {job_id} carries {len(record.artifacts)} artefact(s); this "
            "stage stores no template and no transparency output",
            job_id=job_id,
        )

    present = FORBIDDEN_METADATA_KEYS & set(metadata)
    if present:
        yield _issue(
            IntegrityIssueCode.RESULT_PIPELINE_MISMATCH,
            f"result {job_id} carries metadata a raw result may never hold: "
            f"{sorted(present)}",
            job_id=job_id,
        )


def _check_resolution(
    record: RawResultRecord,
    pair: ComparisonPair | None,
    images: Mapping[ImageId, ImageRecord],
    preparation: CanonicalPreparationExpectations | None = None,
) -> Iterable[IntegrityIssue]:
    """Was each side compared at the resolution it was entitled to?

    Which resolution that is depends on what prepared the images, and the answer
    is completely different for the two runs. Natively, SD300C is the reason this
    is checked rather than assumed: 10,115 of its files declare 5080 ppi in a
    header that is simply wrong, and a run that quietly believed them would
    produce results nobody could compare against SD300A or SD300B
    (docs/adr/0004, docs/adr/0016).

    Canonically, every side is 500 ppi regardless of release, because that is
    what canonicalisation *did*. Checking the release's native value here would
    fail every canonical result, and inferring the source resolution from adapter
    metadata is impossible — by the time the adapter saw the file it was already
    500 (spec section 76). The source side is checked against the preparation
    entries instead, in :func:`_check_preparation`.
    """
    job_id = record.job_id
    if pair is None:
        yield _issue(
            IntegrityIssueCode.PAIR_ID_MISMATCH,
            f"result {job_id} covers pair {record.pair_id}, which is not in the "
            "supplied pair manifest",
            job_id=job_id,
        )
        return

    if preparation is not None:
        expected: int | None = preparation.target_ppi
    else:
        try:
            expected = ppi_policy.effective_ppi(pair.release)
        except ConfigurationError:
            # Not an SD300 release. Fall back to what the manifest says each
            # image is, which is the value the preparer would have used.
            left_record = images.get(record.left_image_id)
            expected = left_record.effective_ppi if left_record else None
            if expected is None:
                return

    for side, key in (("left", "left_dpi"), ("right", "right_dpi")):
        actual = record.adapter_metadata.get(key)
        if actual is None:
            yield _issue(
                IntegrityIssueCode.RESULT_METADATA_MISSING,
                f"result {job_id} does not record {key}",
                job_id=job_id,
            )
            continue
        if actual != str(expected):
            yield _issue(
                IntegrityIssueCode.RESULT_RESOLUTION_MISMATCH,
                f"result {job_id} compared its {side} side at {actual} ppi; "
                f"{pair.release} is used at {expected}",
                job_id=job_id,
            )


def _check_preparation(
    record: RawResultRecord, preparation: CanonicalPreparationExpectations
) -> Iterable[IntegrityIssue]:
    """Does this result name an artefact that actually exists in the set?

    Every check here is against the *entries*, not against another copy of the
    same claim. A result that recorded a preparation-set fingerprint and nothing
    else would prove only that somebody typed the fingerprint; a result whose
    recorded entry hash, file digest, raster digest and dimensions all match the
    entry for its own image id could not have been produced from anything else
    (spec section 75).
    """
    job_id = record.job_id
    metadata = record.runner_metadata

    for key, expected in preparation.run_level_metadata().items():
        actual = metadata.get(key)
        if actual is None:
            yield _issue(
                IntegrityIssueCode.RESULT_METADATA_MISSING,
                f"result {job_id} does not record {key}; it cannot be attributed "
                "to the input set that produced it",
                job_id=job_id,
            )
        elif actual != expected:
            yield _issue(
                IntegrityIssueCode.RESULT_PIPELINE_MISMATCH,
                f"result {job_id} records {key}={str(actual)[:16]}..., expected "
                f"{str(expected)[:16]}...",
                job_id=job_id,
            )

    for side, image_id in (
        ("left", record.left_image_id),
        ("right", record.right_image_id),
    ):
        entry = preparation.entries.get(image_id)
        if entry is None:
            yield _issue(
                IntegrityIssueCode.RESULT_PIPELINE_MISMATCH,
                f"result {job_id}'s {side} image has no entry in prepared-image set "
                f"{preparation.preparation_set_id}",
                job_id=job_id,
            )
            continue

        for suffix, expected in (
            ("preparation_entry_hash", entry.entry_hash),
            ("prepared_sha256", entry.output_encoded_sha256),
            ("pixel_sha256", entry.output_pixel_sha256),
            ("source_ppi", str(entry.source_effective_ppi)),
            ("output_ppi", str(entry.output_effective_ppi)),
            ("output_width", str(entry.output_width)),
            ("output_height", str(entry.output_height)),
        ):
            key = f"{side}_{suffix}"
            actual = metadata.get(key)
            if actual is None:
                yield _issue(
                    IntegrityIssueCode.RESULT_METADATA_MISSING,
                    f"result {job_id} does not record {key}",
                    job_id=job_id,
                )
            elif actual != str(expected):
                yield _issue(
                    IntegrityIssueCode.RESULT_PIPELINE_MISMATCH,
                    f"result {job_id} records {key}={str(actual)[:16]}..., but the "
                    f"prepared-image set says {str(expected)[:16]}...",
                    job_id=job_id,
                )

        if entry.output_effective_ppi != preparation.target_ppi:
            yield _issue(
                IntegrityIssueCode.RESULT_RESOLUTION_MISMATCH,
                f"result {job_id}'s {side} artefact is "
                f"{entry.output_effective_ppi} ppi; this profile targets "
                f"{preparation.target_ppi}",
                job_id=job_id,
            )
        if entry.source_effective_ppi < entry.output_effective_ppi:
            yield _issue(  # pragma: no cover - the entry model forbids it
                IntegrityIssueCode.RESULT_RESOLUTION_MISMATCH,
                f"result {job_id}'s {side} artefact was upsampled",
                job_id=job_id,
            )

def _check_release_source_resolutions(
    *,
    pairs: Mapping[PairId, ComparisonPair],
    preparation: CanonicalPreparationExpectations,
    expected_source_ppi: Mapping[str, int],
) -> Iterable[IntegrityIssue]:
    """Every SD300A entry came from 500 ppi, every B from 1000, every C from 2000.

    Joined back through the pair manifest rather than read off adapter metadata,
    which by construction says 500 for all three after canonicalisation
    (spec section 76).
    """
    for pair in pairs.values():
        expected = expected_source_ppi.get(pair.release)
        if expected is None:
            continue
        for side, image_id in (
            ("left", pair.left_image_id),
            ("right", pair.right_image_id),
        ):
            entry = preparation.entries.get(image_id)
            if entry is None:
                yield _issue(
                    IntegrityIssueCode.RESULT_PIPELINE_MISMATCH,
                    f"pair {pair.pair_id}'s {side} image has no prepared entry",
                )
                continue
            if entry.source_effective_ppi != expected:
                yield _issue(
                    IntegrityIssueCode.RESULT_RESOLUTION_MISMATCH,
                    f"pair {pair.pair_id}'s {side} artefact was scaled from "
                    f"{entry.source_effective_ppi} ppi; {pair.release} is used at "
                    f"{expected}",
                )


def _check_success(record: RawResultRecord) -> Iterable[IntegrityIssue]:
    """Is a successful result well formed?

    Well formed, not *good*. There is no threshold here, no claim that a SELF
    comparison ought to score highly, and no comparison of genuine against
    impostor. Those are the next stage's questions and asking them here would
    smuggle a decision into an integrity check (docs/adr/0003).
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
    if float(score) < 0:
        yield _issue(
            IntegrityIssueCode.RESULT_SCORE_INVALID,
            f"result {job_id} scored below zero; SourceAFIS similarity is "
            "non-negative",
            job_id=job_id,
        )
    if record.failure is not None:
        yield _issue(
            IntegrityIssueCode.RESULT_SCORE_INVALID,
            f"result {job_id} carries both a score and a failure",
            job_id=job_id,
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
) -> str:
    """A digest of what this pass found, with no timestamp in it.

    The same files validated twice produce the same fingerprint, so a receipt
    can name the exact validation it rests on.
    """
    return stable_hash(
        {
            "schema": "sourceafis_validation_fingerprint_v1",
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
