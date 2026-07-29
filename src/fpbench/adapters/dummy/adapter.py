"""A matcher that does no matching.

It derives a score by hashing the two images' official digests. The number is
meaningless as biometrics and must never appear in a research claim. What it is
good for is proving the harness works: 6,000 comparisons can be planned, run,
stored, resumed and audited before SourceAFIS or NBIS is installed, so that any
bug found at that point is unambiguously the harness's fault.

Determinism is the whole value here, so the score is built to be reproducible
across machines, runs and Python versions:

* ``hashlib.sha256``, not ``hash()`` — the latter is randomised per process;
* the images' ``expected_sha256`` values, not their paths, sizes or mtimes;
* concatenation in left-then-right order, so swapping the sides changes the
  score and an accidentally symmetric matcher is detectable;
* the run's ``deterministic_seed``, so two runs can be deliberately different;
* a version tag in the payload, so changing this formula is visible rather
  than silently reinterpreting old results.

Note what is *not* used: ``pair_id`` is unavailable by construction, and the
adapter never inspects an ``image_id`` to guess whether a pair is genuine. An
adapter that could tell would be able to cheat, and this one is the reference
example of an adapter that cannot (docs/adr/0010).
"""

from __future__ import annotations

import hashlib
from typing import Mapping

from fpbench.adapters.base import ADAPTER_CONTRACT_VERSION, FingerprintAlgorithmAdapter
from fpbench.core.enums import EnvironmentStatus, ScoreDirection
from fpbench.core.execution_models import (
    AlgorithmDescriptor,
    ComparisonContext,
    EnvironmentReport,
    PreparedImage,
    RawMatchResult,
    runtime_description,
)

__all__ = ["DummyShaAdapter", "ALGORITHM_ID", "IMPLEMENTATION_VERSION", "SCORE_SCALE"]

ALGORITHM_ID = "dummy_sha256"
IMPLEMENTATION_VERSION = "dummy-sha256-v1"
GENERATOR = "sha256_ordered_pair_v1"

#: Scores span [0, SCORE_SCALE]. The range is arbitrary but fixed, so that a
#: threshold written against this adapter keeps meaning the same thing.
SCORE_SCALE = 100.0

_PAYLOAD_PREFIX = b"fpbench-dummy-sha256-v1\0"
_UINT64_MAX = (1 << 64) - 1


class DummyShaAdapter(FingerprintAlgorithmAdapter):
    """Deterministic SHA-256 pseudo-matcher."""

    def __init__(self) -> None:
        self._descriptor = AlgorithmDescriptor(
            algorithm_id=ALGORITHM_ID,
            display_name="Deterministic SHA-256 Dummy Matcher",
            adapter_id=ALGORITHM_ID,
            adapter_version="1",
            adapter_contract_version=ADAPTER_CONTRACT_VERSION,
            implementation_version=IMPLEMENTATION_VERSION,
            score_direction=ScoreDirection.HIGHER_IS_BETTER,
            deterministic=True,
            capabilities=(),
        )

    @classmethod
    def from_config(cls, config: Mapping[str, object]) -> "DummyShaAdapter":
        """Build from registry configuration.

        Takes no options. Rejecting unknown keys rather than ignoring them
        means a typo in a config file is caught instead of silently changing
        nothing.
        """
        if config:
            raise ValueError(
                f"{ALGORITHM_ID} takes no configuration, got {sorted(config)}"
            )
        return cls()

    @property
    def descriptor(self) -> AlgorithmDescriptor:
        return self._descriptor

    def validate_environment(self) -> EnvironmentReport:
        """Always ready: the only dependency is the standard library."""
        return EnvironmentReport(
            status=EnvironmentStatus.READY,
            implementation_version=IMPLEMENTATION_VERSION,
            runtime=runtime_description(),
            dependencies={},
        )

    def compare(
        self,
        left: PreparedImage,
        right: PreparedImage,
        context: ComparisonContext,
    ) -> RawMatchResult:
        return RawMatchResult.success(
            raw_score=score_for(
                left.expected_sha256, right.expected_sha256, context.deterministic_seed
            ),
            score_direction=ScoreDirection.HIGHER_IS_BETTER,
            artifacts=(),
            metadata={"generator": GENERATOR},
        )


def score_for(left_sha256: str, right_sha256: str, deterministic_seed: int) -> float:
    """The scoring function, exposed so tests can pin it without a full run."""
    payload = (
        _PAYLOAD_PREFIX
        + left_sha256.encode("ascii")
        + b"\0"
        + right_sha256.encode("ascii")
        + b"\0"
        + str(deterministic_seed).encode("ascii")
    )
    digest = hashlib.sha256(payload).digest()
    integer = int.from_bytes(digest[:8], "big")
    return integer / _UINT64_MAX * SCORE_SCALE
