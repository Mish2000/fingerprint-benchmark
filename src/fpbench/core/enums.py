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
    "IntegritySeverity",
    "IntegrityIssueCode",
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
    DUPLICATE_PAIR_ID = "duplicate_pair_id"
    DUPLICATE_JOB_ID = "duplicate_job_id"
    DUPLICATE_JOB_FINGERPRINT = "duplicate_job_fingerprint"
    PLAN_CONFLICT = "plan_conflict"
