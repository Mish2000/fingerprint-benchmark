"""Closed vocabularies shared by every subsystem.

Nothing here is specific to a dataset, a protocol or an algorithm. Dataset
native codes (SD300 FRGP, impression codes, ...) are translated into these
values at the dataset boundary and never leak past it.
"""

from __future__ import annotations

from enum import Enum, IntEnum

__all__ = [
    "Hand",
    "Impression",
    "FingerprintPosition",
    "GroundTruth",
    "ProtocolStage",
    "CohortRole",
    "ChecksumStatus",
    "ScoreDirection",
    "ExecutionStatus",
    "EnvironmentStatus",
    "FailureStage",
    "FailureCode",
    "RunState",
    "ResearchRunStatus",
    "IntegritySeverity",
    "IntegrityIssueCode",
    "ThresholdOrigin",
    "ThresholdComparator",
    "DecisionApplicationStatus",
    "DecisionValue",
    "SelfEligibilityStatus",
    "SelfEligibilityReason",
    "DecisionDerivationStatus",
    "MetricNumerator",
    "MetricDenominator",
    "MetricScopeKind",
    "MetricObservationStatus",
    "EvaluationStatus",
]


class Hand(str, Enum):
    RIGHT = "right"
    LEFT = "left"


class Impression(str, Enum):
    """How the friction ridge was deposited on the card."""

    PLAIN = "plain"
    ROLL = "roll"


class FingerprintPosition(IntEnum):
    """Anatomical finger, numbered as in ANSI/NIST-ITL FRGP 1-10.

    This is the *anatomical* identity used for pairing. It is deliberately not
    the dataset's raw position code: SD300 stores a plain right thumb under
    FRGP 11, and the mapping back to finger 1 belongs to the dataset layer.
    """

    RIGHT_THUMB = 1
    RIGHT_INDEX = 2
    RIGHT_MIDDLE = 3
    RIGHT_RING = 4
    RIGHT_LITTLE = 5
    LEFT_THUMB = 6
    LEFT_INDEX = 7
    LEFT_MIDDLE = 8
    LEFT_RING = 9
    LEFT_LITTLE = 10

    @property
    def hand(self) -> Hand:
        return Hand.RIGHT if self.value <= 5 else Hand.LEFT

    @property
    def label(self) -> str:
        """Stable short label used inside identifiers, e.g. ``f01``."""
        return f"f{self.value:02d}"


ALL_POSITIONS: frozenset[FingerprintPosition] = frozenset(FingerprintPosition)


class GroundTruth(str, Enum):
    """Whether two images are known to originate from the same anatomical finger.

    A SELF comparison (an image against itself) is MATED; it is distinguished
    from a genuine cross-impression comparison by :class:`ProtocolStage`, not
    by its ground truth.
    """

    MATED = "mated"
    NON_MATED = "non_mated"


class ProtocolStage(str, Enum):
    """The experiment step a pair belongs to."""

    PLAIN_SELF = "plain_self"
    ROLL_SELF = "roll_self"
    PLAIN_ROLL_MATED = "plain_roll_mated"
    PLAIN_ROLL_NON_MATED = "plain_roll_non_mated"

    @property
    def is_self(self) -> bool:
        return self in (ProtocolStage.PLAIN_SELF, ProtocolStage.ROLL_SELF)


class CohortRole(str, Enum):
    """What a cohort may be used for.

    The distinction exists to make threshold-calibration leakage detectable in
    code rather than in review: calibration must refuse a TEST cohort.
    """

    TEST = "test"
    DEVELOPMENT = "development"


class ChecksumStatus(str, Enum):
    """Whether the bytes on disk were checked against the official digest."""

    NOT_VERIFIED = "not_verified"
    VERIFIED = "verified"
    MISMATCH = "mismatch"


class ScoreDirection(str, Enum):
    """Which way a matcher's score runs.

    Declared by the algorithm and carried on every result, because a threshold
    is meaningless without it and different matchers disagree.
    """

    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"


class ExecutionStatus(str, Enum):
    """Whether a comparison produced a usable score.

    There is deliberately no ``SKIPPED`` member. Skipping is something the
    runner does about a job; it is never an algorithm's answer about a pair of
    images, and conflating the two would corrupt every denominator.
    """

    SUCCESS = "success"
    FAILURE = "failure"


class EnvironmentStatus(str, Enum):
    """Whether an adapter's dependencies are present and usable."""

    READY = "ready"
    UNAVAILABLE = "unavailable"


class FailureStage(str, Enum):
    """Where in the pipeline a failure happened.

    The stage answers "whose problem is this?"; :class:`FailureCode` answers
    "what exactly went wrong?".
    """

    INPUT = "input"
    PREPARATION = "preparation"
    ENVIRONMENT = "environment"
    QUALITY = "quality"
    EXTRACTION = "extraction"
    MATCHING = "matching"
    ADAPTER = "adapter"
    TIMEOUT = "timeout"


class FailureCode(str, Enum):
    """The taxonomy locked in docs/adr/0006.

    None of these is a biometric decision. A comparison that ran correctly and
    scored below threshold is a ``SUCCESS`` with a low score, never a failure.
    """

    INPUT_INVALID = "input_invalid"
    IMAGE_DECODE_FAILED = "image_decode_failed"
    PREPARATION_FAILED = "preparation_failed"
    QUALITY_REJECTED = "quality_rejected"
    TEMPLATE_EXTRACTION_FAILED = "template_extraction_failed"
    MATCHING_FAILED = "matching_failed"
    NO_SCORE = "no_score"
    TIMEOUT = "timeout"
    PROCESS_CRASHED = "process_crashed"
    DEPENDENCY_MISSING = "dependency_missing"
    UNSUPPORTED_RESOLUTION = "unsupported_resolution"
    INTERNAL_ERROR = "internal_error"


class RunState(str, Enum):
    """How far a run has got, and whether it can be believed.

    There is deliberately no ``RUNNING``. State is derived from files on disk,
    and after a crash nothing on disk can tell you whether a process is still
    alive — a persisted ``RUNNING`` would be a lie the moment the machine
    rebooted (docs/adr/0012).
    """

    #: The plan exists; no results have been stored yet.
    PLANNED = "planned"
    #: Some planned jobs have results, some do not.
    PARTIAL = "partial"
    #: Every planned job has a readable result, but no completion manifest has
    #: been written — nothing has yet verified the run as a whole.
    COMPLETE = "complete"
    #: A clean audit ran and its completion manifest is on disk.
    VERIFIED = "verified"
    #: An integrity problem was found: corruption, a conflict, a result that
    #: belongs to no planned job, mismatched provenance.
    INVALID = "invalid"


class ResearchRunStatus(str, Enum):
    """How much of a research run's evidence chain is in place.

    A superset of :class:`RunState`, not a replacement for it. ``VERIFIED``
    answers "were these results audited against their plan?"; it says nothing
    about *which executable* produced them, *which source revision* drove it, or
    whether the exact ordered collection of scores has been given an identity
    that a later analysis can cite. Those are the three questions that separate
    a sound run from a run something may be published from (docs/adr/0020).
    """

    #: No run manifest, or no plan beside it.
    NOT_PREPARED = "not_prepared"
    #: Run, plan and runtime reference are written; no comparison has been made.
    PREPARED = "prepared"
    #: Some planned jobs have results, some do not.
    PARTIAL = "partial"
    #: Every planned job has a result; nothing has verified them as a whole.
    RESULTS_COMPLETE = "results_complete"
    #: The core audit passed and ``completion.json`` is on disk, but the
    #: result-set manifest or the research receipt is missing.
    CORE_VERIFIED = "core_verified"
    #: Every link is present and revalidated: audit, runtime bundle, source
    #: revision, result-set identity and sanitised receipt.
    RESEARCH_READY = "research_ready"
    #: Something in the chain contradicts something else.
    INVALID = "invalid"


class IntegritySeverity(str, Enum):
    """Whether an audit finding blocks a run from being called verified."""

    WARNING = "warning"
    ERROR = "error"


class IntegrityIssueCode(str, Enum):
    """What an audit found wrong.

    None of these describes a biometric outcome. A comparison that failed to
    produce a score is a perfectly valid stored result (docs/adr/0013); these
    codes are about results that are missing, duplicated, unreadable, or
    claiming to belong to something they do not.
    """

    MISSING_RESULT = "missing_result"
    EXTRA_RESULT = "extra_result"
    RESULT_UNREADABLE = "result_unreadable"
    PATH_JOB_ID_MISMATCH = "path_job_id_mismatch"
    RUN_ID_MISMATCH = "run_id_mismatch"
    JOB_FINGERPRINT_MISMATCH = "job_fingerprint_mismatch"
    PAIR_ID_MISMATCH = "pair_id_mismatch"
    IMAGE_IDS_MISMATCH = "image_ids_mismatch"
    PAIR_MANIFEST_HASH_MISMATCH = "pair_manifest_hash_mismatch"
    ALGORITHM_FINGERPRINT_MISMATCH = "algorithm_fingerprint_mismatch"
    EXECUTION_PROFILE_HASH_MISMATCH = "execution_profile_hash_mismatch"
    RESULT_HASH_MISMATCH = "result_hash_mismatch"
    RESULT_METADATA_MISSING = "result_metadata_missing"
    RESULT_SCHEMA_MISMATCH = "result_schema_mismatch"
    #: The stored result names a different executable, bundle or source
    #: revision than the run it belongs to (docs/adr/0017, docs/adr/0018).
    RESULT_RUNTIME_MISMATCH = "result_runtime_mismatch"
    #: The result's own account of how it was produced — integration mode,
    #: extraction policy, template caching — contradicts the algorithm's
    #: contract. Still not a biometric finding: it says the pipeline was not
    #: the pipeline that was agreed, not that a comparison went badly.
    RESULT_PIPELINE_MISMATCH = "result_pipeline_mismatch"
    #: The comparison ran at a different resolution than the pair's release
    #: declares (docs/adr/0004, docs/adr/0016).
    RESULT_RESOLUTION_MISMATCH = "result_resolution_mismatch"
    #: The result carries an artefact reference the run forbids.
    RESULT_UNEXPECTED_ARTIFACT = "result_unexpected_artifact"
    #: The comparison produced no score for a reason that indicates broken
    #: infrastructure rather than an algorithm declining a print.
    RESULT_BLOCKING_FAILURE = "result_blocking_failure"
    #: A failure code no policy has classified. Never guessed at.
    RESULT_UNKNOWN_FAILURE_CODE = "result_unknown_failure_code"
    #: A stored score is absent, non-finite or outside the algorithm's declared
    #: range. Not a threshold check — a well-formedness check.
    RESULT_SCORE_INVALID = "result_score_invalid"
    DUPLICATE_PAIR_ID = "duplicate_pair_id"
    DUPLICATE_JOB_ID = "duplicate_job_id"
    DUPLICATE_JOB_FINGERPRINT = "duplicate_job_fingerprint"
    PLAN_CONFLICT = "plan_conflict"


# ------------------------------------------------------------------ decisions
#
# The vocabulary of the layer that turns a stored score into a claim about two
# fingerprints. It is kept rigorously apart from the execution vocabulary above:
# `ExecutionStatus` answers "did the comparison happen?", and nothing here
# answers that question (docs/adr/0003, docs/adr/0021).


class ThresholdOrigin(str, Enum):
    """Where a threshold came from, which is not the same as whether it is good.

    The distinction exists to make one specific mistake impossible to commit
    quietly: presenting a number an upstream project documented as though this
    project had measured it. SourceAFIS documents 40; that is
    ``DOCUMENTED_NATIVE`` and stays so no matter how many comparisons are run
    under it.
    """

    #: Published by the algorithm's own authors, for their own reasons.
    DOCUMENTED_NATIVE = "documented_native"
    #: Chosen by this project on a development cohort. Requires a calibration
    #: manifest, and may never be derived from a TEST cohort.
    CALIBRATED_DEVELOPMENT = "calibrated_development"
    #: Fixed by an external requirement — a standard, a procurement spec.
    EXTERNAL_FIXED = "external_fixed"


class ThresholdComparator(str, Enum):
    """Which side of the threshold counts as a match.

    Paired with the algorithm's score direction and checked against it, because
    a comparator that disagrees with the direction silently inverts every
    decision in a run.
    """

    GREATER_THAN_OR_EQUAL = "greater_than_or_equal"
    LESS_THAN_OR_EQUAL = "less_than_or_equal"


class DecisionApplicationStatus(str, Enum):
    """Whether a threshold could be applied to a stored result at all.

    ``UNDECIDABLE`` is not a third biometric outcome. It records that there was
    no score to compare — the comparison failed — and it exists precisely so
    that such a result never has to be squeezed into MATCH or NON_MATCH
    (docs/adr/0006).
    """

    DECIDED = "decided"
    UNDECIDABLE = "undecidable"


class DecisionValue(str, Enum):
    """What a threshold said about a score.

    There are deliberately only two members, and no member means "failed". A
    comparison that produced no score has no ``DecisionValue`` at all.
    """

    MATCH = "match"
    NON_MATCH = "non_match"


class SelfEligibilityStatus(str, Enum):
    """Whether one finger, in one release, is usable for conditional reporting.

    Three-valued on purpose. Collapsing ``UNDETERMINED`` into ``INELIGIBLE``
    would silently treat "we could not tell" as "it failed", which is the same
    error as counting a crashed comparison as a non-match.
    """

    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    UNDETERMINED = "undetermined"


class SelfEligibilityReason(str, Enum):
    """Why a unit reached the status it did.

    More than one may apply — both SELF stages can fail independently — so
    these are recorded as a set rather than a single cause.
    """

    BOTH_SELF_MATCH = "both_self_match"

    PLAIN_SELF_NON_MATCH = "plain_self_non_match"
    ROLL_SELF_NON_MATCH = "roll_self_non_match"

    PLAIN_SELF_UNDECIDABLE = "plain_self_undecidable"
    ROLL_SELF_UNDECIDABLE = "roll_self_undecidable"


class DecisionDerivationStatus(str, Enum):
    """How much of a derivation's evidence chain is in place.

    The same shape as :class:`ResearchRunStatus`, one layer up, and for the same
    reason: intermediates are retryable, and only the last-written marker makes
    any of it authoritative (docs/adr/0020).
    """

    NOT_PREPARED = "not_prepared"
    PROFILE_READY = "profile_ready"
    DECISIONS_READY = "decisions_ready"
    ELIGIBILITY_READY = "eligibility_ready"
    VIEWS_READY = "views_ready"
    DECISION_READY = "decision_ready"
    INVALID = "invalid"


# -------------------------------------------------------------------- metrics
#
# The vocabulary of the layer that counts decisions. It names *what is counted*
# and *what it is counted out of*, separately and explicitly, because a rate
# whose denominator is implied is a rate nobody can check (docs/adr/0026).


class MetricNumerator(str, Enum):
    """What a metric counts on top of the line.

    Each member names an outcome that already exists one layer down — a decision
    value, an eligibility status, a conditional inclusion state — rather than
    inventing a new one. ``NON_SUCCESS`` is the single exception and is defined
    below as exactly ``NON_MATCH + UNDECIDABLE`` over genuine attempts; it exists
    because that sum is the honest attempt-level answer and computing it inline
    would let two call sites disagree about whether failures are in it.
    """

    MATCH = "match"
    NON_MATCH = "non_match"
    UNDECIDABLE = "undecidable"

    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    UNDETERMINED = "undetermined"

    INCLUDED = "included"
    EXCLUDED_INELIGIBLE = "excluded_ineligible"
    EXCLUDED_UNDETERMINED = "excluded_undetermined"

    #: ``NON_MATCH + UNDECIDABLE``, and only over genuine attempts. Never used
    #: as an impostor numerator: a failed impostor comparison is not a "success"
    #: whose absence means anything.
    NON_SUCCESS = "non_success"


class MetricDenominator(str, Enum):
    """What a metric divides by, named rather than implied.

    The distinction between ``ALL_ATTEMPTS`` and ``DECIDED_ATTEMPTS`` is the
    whole of docs/adr/0027: the first includes comparisons that produced no
    score, the second does not, and reporting one under the other's name silently
    changes what the number means.
    """

    #: Every comparison in the population, decided or not.
    ALL_ATTEMPTS = "all_attempts"
    #: Only the comparisons a threshold could actually be applied to.
    DECIDED_ATTEMPTS = "decided_attempts"
    #: Every SELF eligibility unit, whatever its status.
    ALL_ELIGIBILITY_UNITS = "all_eligibility_units"
    #: Conditional rows the selection rule kept, decided or not.
    INCLUDED_CONDITIONAL_ATTEMPTS = "included_conditional_attempts"
    #: Conditional rows the selection rule kept *and* that could be decided.
    DECIDED_CONDITIONAL_ATTEMPTS = "decided_conditional_attempts"


class MetricScopeKind(str, Enum):
    """Whether an observation covers one release or all of them.

    ``POOLED`` is not a fourth release. It is the sum of the release counts,
    divided once (docs/adr/0028).
    """

    RELEASE = "release"
    POOLED = "pooled"


class MetricObservationStatus(str, Enum):
    """Whether a metric had anything to divide by.

    ``UNDEFINED_ZERO_DENOMINATOR`` is not zero. A conditional FNMR over an empty
    included set is not "0% of comparisons failed"; it is "no comparison was
    covered", and rendering it as ``0.0000%`` would state a result nobody
    measured.
    """

    DEFINED = "defined"
    UNDEFINED_ZERO_DENOMINATOR = "undefined_zero_denominator"


class EvaluationStatus(str, Enum):
    """How much of an evaluation's evidence chain is in place.

    The same shape as :class:`DecisionDerivationStatus` one layer down, for the
    same reason: everything before the finalization marker is retryable work,
    and ``EVALUATION_READY`` means the defined metrics are reproducible — never
    that the threshold was calibrated or the benchmark estimates population-wide
    performance.
    """

    NOT_PREPARED = "not_prepared"
    POLICY_READY = "policy_ready"
    COUNTS_READY = "counts_ready"
    METRICS_READY = "metrics_ready"
    REPORT_READY = "report_ready"
    EVALUATION_READY = "evaluation_ready"
    INVALID = "invalid"
