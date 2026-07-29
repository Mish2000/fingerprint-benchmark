"""What a run is, and what makes two runs the same run.

A run pins down every input that could change a raw score: the exact pair
manifest, the exact cohort, the exact algorithm and adapter versions, the exact
environment, the exact execution profile and seed. ``run_fingerprint`` is a
digest of all of them, and ``run_id`` is its first twelve characters.

The consequence is the property the whole stage is built around: **the same
inputs always produce the same ``run_id``**. Re-running after a crash lands in
the same directory and skips the work already done. Changing anything that
matters lands somewhere else instead of quietly mixing incomparable results
into one place.

What the fingerprint excludes is just as deliberate: ``created_utc``, workspace
paths and dataset paths. A run repeated tomorrow, on another machine, with the
data unpacked elsewhere, is the same run.

The :class:`~fpbench.core.result_models.RunDefinition` dataclass itself lives in
``core`` so that the storage layer can persist it without depending on this
package; it is re-exported here, because the rules for deriving a run are this
module's business and callers should not have to know where the container is
declared.
"""

from __future__ import annotations

import datetime as _dt

from fpbench.core.execution_models import (
    FINGERPRINT_LENGTH,
    AlgorithmDescriptor,
    EnvironmentReport,
    ExecutionProfile,
)
from fpbench.core.execution_models import descriptor_fingerprint as _descriptor_hash
from fpbench.core.execution_models import environment_fingerprint as _environment_hash
from fpbench.core.execution_models import (
    execution_profile_fingerprint as _profile_hash,
)
from fpbench.core.identifiers import CohortId, validate_id
from fpbench.core.result_models import RunDefinition
from fpbench.core.serialization import stable_hash
from fpbench.imaging.identity import PREPARER_ID as IDENTITY_PREPARER_ID

__all__ = [
    "RunDefinition",
    "create_run_definition",
    "run_fingerprint_of",
    "DEFAULT_EXECUTION_PROFILE",
    "RUN_SCHEMA_VERSION",
    "RUN_ID_LENGTH",
]

#: Bumped when the meaning of a run changes. It is inside the fingerprint, so a
#: bump separates new runs from old ones rather than silently reusing their ids.
RUN_SCHEMA_VERSION = "1"

#: Twelve hex characters is 48 bits: ample for the number of runs a study will
#: ever contain, and short enough to type and to read in a directory listing.
RUN_ID_LENGTH = 12

#: The single execution profile stage 3A defines. Identity preparation, no
#: resampling, no conversion. Later stages add profiles; they never mutate this
#: one, because results already reference it by hash.
DEFAULT_EXECUTION_PROFILE = ExecutionProfile(
    profile_id="identity_png_v1",
    preparer_id=IDENTITY_PREPARER_ID,
    timeout_seconds=10.0,
    deterministic_seed=0,
    parameters={},
)


def run_fingerprint_of(
    *,
    protocol_id: str,
    cohort_id: CohortId | str,
    pair_manifest_hash: str,
    algorithm_fingerprint: str,
    environment_fingerprint: str,
    execution_profile_hash: str,
    replicate_index: int,
) -> str:
    """The digest behind ``run_id``, computed from fingerprints alone."""
    return stable_hash(
        {
            "schema": "run_fingerprint_v1",
            "run_schema_version": RUN_SCHEMA_VERSION,
            "protocol_id": protocol_id,
            "cohort_id": str(cohort_id),
            "pair_manifest_hash": pair_manifest_hash,
            "algorithm_fingerprint": algorithm_fingerprint,
            "environment_fingerprint": environment_fingerprint,
            "execution_profile_hash": execution_profile_hash,
            "replicate_index": int(replicate_index),
        },
        length=FINGERPRINT_LENGTH,
    )


def create_run_definition(
    *,
    protocol_id: str,
    cohort_id: CohortId,
    pair_manifest_hash: str,
    algorithm: AlgorithmDescriptor,
    environment: EnvironmentReport,
    execution_profile: ExecutionProfile,
    replicate_index: int = 0,
    created_utc: str | None = None,
) -> RunDefinition:
    """Derive a run from its inputs.

    Args:
        replicate_index: Distinguishes deliberate repeats of an otherwise
            identical run. It exists for non-deterministic algorithms, where
            running twice is a legitimate experiment rather than a mistake.
        created_utc: Overridable only so that tests can prove it does *not*
            reach the fingerprint.
    """
    validate_id(protocol_id)
    if int(replicate_index) < 0:
        raise ValueError("replicate_index must not be negative")

    algorithm_hash = _descriptor_hash(algorithm)
    environment_hash = _environment_hash(environment)
    profile_hash = _profile_hash(execution_profile)

    fingerprint = run_fingerprint_of(
        protocol_id=protocol_id,
        cohort_id=cohort_id,
        pair_manifest_hash=pair_manifest_hash,
        algorithm_fingerprint=algorithm_hash,
        environment_fingerprint=environment_hash,
        execution_profile_hash=profile_hash,
        replicate_index=replicate_index,
    )

    return RunDefinition(
        run_id=f"run_{fingerprint[:RUN_ID_LENGTH]}",
        run_fingerprint=fingerprint,
        protocol_id=protocol_id,
        cohort_id=cohort_id,
        pair_manifest_hash=pair_manifest_hash,
        algorithm=algorithm,
        algorithm_fingerprint=algorithm_hash,
        environment=environment,
        environment_fingerprint=environment_hash,
        execution_profile=execution_profile,
        execution_profile_hash=profile_hash,
        replicate_index=int(replicate_index),
        created_utc=created_utc or _utc_now(),
    )


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()
