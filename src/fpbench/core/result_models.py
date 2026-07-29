"""What gets written to disk about a run and its comparisons.

Distinct from :mod:`fpbench.core.execution_models`, which describes what flows
*between* components while a job runs. These are the durable artefacts: written
once, kept forever, joined against later.

Why they live in ``core`` rather than in ``fpbench.execution``: the storage
layer has to read and write them, and ``storage`` is only allowed to depend on
``core``. The *rules* for deriving a run — what goes into its fingerprint, how
its id is formed — do belong to execution, and stay in
:mod:`fpbench.execution.run_definition`, which re-exports
:class:`RunDefinition` so that callers can import model and factory from one
place. Data here, policy there.

Both records are deliberately self-describing. A result carries the protocol,
cohort, pair manifest hash, algorithm fingerprint and execution profile hash it
was produced under, so a file found on its own years later can still be
attributed without trusting the directory it happens to sit in.

Equally deliberate is what a result does *not* carry:

* no ``ground_truth`` and no ``protocol_stage`` — evaluation joins those in
  from the pair manifest via ``pair_id``. Storing them here would let a result
  and its manifest drift apart, and would put the answer next to the score;
* no threshold and no decision — those are a separate record produced later,
  possibly several times, against this unchanged score (docs/adr/0003);
* no absolute path — results must stay portable between machines.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from fpbench.core.enums import ExecutionStatus, ScoreDirection
from fpbench.core.execution_models import (
    FINGERPRINT_LENGTH,
    AlgorithmDescriptor,
    ArtifactReference,
    EnvironmentReport,
    ExecutionProfile,
    FailureInfo,
    TimingBreakdown,
)
from fpbench.core.identifiers import CohortId, ImageId, PairId, validate_id
from fpbench.core.serialization import freeze_str_mapping, stable_hash, to_plain

__all__ = [
    "RunDefinition",
    "RawResultRecord",
    "raw_result_hash",
    "RESULT_SCHEMA_VERSION",
]

RESULT_SCHEMA_VERSION = "1"


@dataclass(frozen=True, slots=True)
class RunDefinition:
    """Everything a run's results can be attributed to.

    Each fingerprint is stored beside the object it summarises. That is
    redundant on purpose: a result read years later can be checked against the
    manifest it claims to come from without re-deriving anything.

    Built through
    :func:`fpbench.execution.run_definition.create_run_definition`, which is
    where the fingerprint rules live.
    """

    run_id: str
    run_fingerprint: str

    protocol_id: str
    cohort_id: CohortId
    pair_manifest_hash: str

    algorithm: AlgorithmDescriptor
    algorithm_fingerprint: str

    environment: EnvironmentReport
    environment_fingerprint: str

    execution_profile: ExecutionProfile
    execution_profile_hash: str

    replicate_index: int
    created_utc: str

    def __post_init__(self) -> None:
        validate_id(self.run_id)
        validate_id(self.protocol_id)
        if int(self.replicate_index) < 0:
            raise ValueError("replicate_index must not be negative")
        object.__setattr__(self, "replicate_index", int(self.replicate_index))


@dataclass(frozen=True, slots=True)
class RawResultRecord:
    """One comparison, carried out and recorded.

    ``result_id`` equals ``job_id`` for now. They are separate fields because
    they answer different questions — "which stored row is this?" versus "which
    planned unit of work produced it?" — and a future retry policy will make
    them diverge.
    """

    result_id: str
    run_id: str
    job_id: str
    job_fingerprint: str

    protocol_id: str
    cohort_id: CohortId
    pair_manifest_hash: str
    pair_id: PairId

    left_image_id: ImageId
    right_image_id: ImageId

    algorithm_id: str
    algorithm_fingerprint: str

    execution_profile_id: str
    execution_profile_hash: str

    attempt: int
    started_utc: str
    finished_utc: str

    status: ExecutionStatus
    raw_score: float | None
    score_direction: ScoreDirection
    failure: FailureInfo | None

    timings: TimingBreakdown
    artifacts: tuple[ArtifactReference, ...] = ()
    adapter_metadata: Mapping[str, str] = field(default_factory=dict)
    runner_metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "result_id",
            "run_id",
            "job_id",
            "protocol_id",
            "algorithm_id",
            "execution_profile_id",
        ):
            validate_id(getattr(self, name))
        if int(self.attempt) < 1:
            raise ValueError("attempt is 1-based")
        object.__setattr__(self, "attempt", int(self.attempt))
        object.__setattr__(self, "artifacts", tuple(self.artifacts))
        object.__setattr__(
            self, "adapter_metadata", freeze_str_mapping(self.adapter_metadata)
        )
        object.__setattr__(
            self, "runner_metadata", freeze_str_mapping(self.runner_metadata)
        )

        # The same invariants RawMatchResult enforces. They are repeated rather
        # than assumed, because this record outlives the object it came from and
        # is the thing analysis will actually read.
        if self.status is ExecutionStatus.SUCCESS:
            if self.raw_score is None:
                raise ValueError("a successful result must carry a score")
            if self.failure is not None:
                raise ValueError("a successful result must not carry a failure")
        else:
            if self.raw_score is not None:
                raise ValueError("a failed result must not carry a score")
            if self.failure is None:
                raise ValueError("a failed result must explain itself")

        identifiers = [artifact.artifact_id for artifact in self.artifacts]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("artifact_id must be unique within a result")


def raw_result_hash(record: RawResultRecord) -> str:
    """A digest of the record's own content.

    Covers the whole record, timings and timestamps included: it answers "are
    these two stored rows the same row?", not "were they produced by the same
    job?". The latter is what ``job_fingerprint`` is for, and it is what resume
    compares. File-level parquet metadata is excluded, since that says when the
    file was written rather than what it says.
    """
    return stable_hash(
        {"schema": f"raw_result_v{RESULT_SCHEMA_VERSION}", "record": to_plain(record)},
        length=FINGERPRINT_LENGTH,
    )
