"""One unit of work: compare these two images, once, inside this run.

A job's identity is a digest of the run it belongs to plus the pair and images
it covers. That gives two things at once:

* **idempotence** — the same pair in the same run always maps to the same
  ``job_id``, so a result file already on disk is recognisable as *this* job's
  result and can be skipped rather than recomputed;
* **opacity** — ``job_id`` is a hash, so nothing about the pair leaks through
  it. An adapter receives the job id and still cannot tell whether it is
  looking at a genuine comparison or an impostor one (docs/adr/0010).

That second property is why the id is not something readable like
``sourceafis_sd300b_plain_roll_00001000_f01``.
"""

from __future__ import annotations

from dataclasses import dataclass

from fpbench.core.execution_models import FINGERPRINT_LENGTH
from fpbench.core.identifiers import ImageId, PairId
from fpbench.core.models import ComparisonPair
from fpbench.core.serialization import stable_hash
from fpbench.execution.run_definition import RunDefinition

__all__ = ["ComparisonJob", "build_comparison_job", "JOB_SCHEMA_VERSION", "JOB_ID_LENGTH"]

JOB_SCHEMA_VERSION = "1"

#: Sixteen hex characters is 64 bits. A run holds thousands of jobs, not
#: billions, but the ids also name files, and a collision there would silently
#: drop a result.
JOB_ID_LENGTH = 16


@dataclass(frozen=True, slots=True)
class ComparisonJob:
    """A single planned comparison.

    Carries ``pair_id`` because the runner and the result store need to join
    back to the pair manifest. The adapter never sees this object — it receives
    a :class:`~fpbench.core.execution_models.ComparisonContext`, which does not
    include the pair.
    """

    job_id: str
    job_fingerprint: str
    run_id: str
    pair_id: PairId
    left_image_id: ImageId
    right_image_id: ImageId
    attempt: int = 1

    def __post_init__(self) -> None:
        if int(self.attempt) < 1:
            raise ValueError("attempt is 1-based")
        object.__setattr__(self, "attempt", int(self.attempt))


def build_comparison_job(
    run: RunDefinition, pair: ComparisonPair, *, attempt: int = 1
) -> ComparisonJob:
    """Derive the job that covers ``pair`` within ``run``.

    ``attempt`` is always 1 in stage 3A — there are no automatic retries yet —
    but it is part of the fingerprint so that a future retry produces a
    distinct job rather than colliding with the attempt it is replacing.
    """
    fingerprint = stable_hash(
        {
            "schema": "job_fingerprint_v1",
            "job_schema_version": JOB_SCHEMA_VERSION,
            "run_fingerprint": run.run_fingerprint,
            "pair_id": str(pair.pair_id),
            "left_image_id": str(pair.left_image_id),
            "right_image_id": str(pair.right_image_id),
            "attempt": int(attempt),
        },
        length=FINGERPRINT_LENGTH,
    )
    return ComparisonJob(
        job_id=f"job_{fingerprint[:JOB_ID_LENGTH]}",
        job_fingerprint=fingerprint,
        run_id=run.run_id,
        pair_id=pair.pair_id,
        left_image_id=pair.left_image_id,
        right_image_id=pair.right_image_id,
        attempt=int(attempt),
    )
