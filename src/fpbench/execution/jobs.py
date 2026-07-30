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

The :class:`~fpbench.core.execution_plan_models.ComparisonJob` container lives
in ``core`` so that the storage layer can persist plans without depending on
this package; it is re-exported here because the rules for *deriving* a job are
this module's business and callers should not have to know where the container
is declared. Data there, policy here — the same split as ``RunDefinition``.
"""

from __future__ import annotations

from fpbench.core.execution_models import FINGERPRINT_LENGTH
from fpbench.core.execution_plan_models import ComparisonJob
from fpbench.core.models import ComparisonPair
from fpbench.core.result_models import RunDefinition
from fpbench.core.serialization import stable_hash

__all__ = ["ComparisonJob", "build_comparison_job", "JOB_SCHEMA_VERSION", "JOB_ID_LENGTH"]

JOB_SCHEMA_VERSION = "1"

#: Sixteen hex characters is 64 bits. A run holds thousands of jobs, not
#: billions, but the ids also name files, and a collision there would silently
#: drop a result.
JOB_ID_LENGTH = 16


def build_comparison_job(
    run: RunDefinition, pair: ComparisonPair, *, attempt: int = 1
) -> ComparisonJob:
    """Derive the job that covers ``pair`` within ``run``.

    ``attempt`` is always 1 through stage 3B — there are no automatic retries
    yet — but it is part of the fingerprint so that a future retry produces a
    distinct job rather than colliding with the attempt it is replacing.

    This is the only place job identity is minted. The planner calls it rather
    than deriving ids of its own, so there is exactly one answer to "which job
    covers this pair in this run?".
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
