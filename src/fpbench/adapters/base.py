"""The contract every fingerprint algorithm is wrapped in.

Three methods, and only one of them does any matching:

    descriptor            what is this algorithm, and how do its scores run?
    validate_environment  can it run here at all?
    compare               given two prepared images, what is the raw score?

``compare`` is the entire mandatory surface. Extraction, templates, quality and
minutiae are optional capabilities an adapter may additionally offer, because a
great many real matchers do not decompose into extract-then-match and forcing
them to pretend produces wrappers that lie about their own structure
(docs/adr/0002).

What an adapter must never do:

* read the pair manifest, or receive a ``ComparisonPair``;
* learn the protocol stage, the ground truth, the subject or the finger;
* apply a threshold or return a decision;
* decide where results are stored, or store them itself;
* write anywhere outside ``context.working_directory`` and
  ``context.artifact_directory``.

Expected trouble is returned as ``RawMatchResult.failed()``. Exceptions are for
the unexpected — a bug, a broken install — and the runner records them without
letting them end the run.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from fpbench.core.execution_models import (
    AlgorithmDescriptor,
    ComparisonContext,
    EnvironmentReport,
    PreparedImage,
    RawMatchResult,
)

__all__ = [
    "FingerprintAlgorithmAdapter",
    "ADAPTER_CONTRACT_VERSION",
    "SUPPORTED_ADAPTER_CONTRACT_VERSIONS",
]

#: The version of this contract. An adapter declares which one it implements,
#: so a future breaking change is detectable rather than merely puzzling.
#:
#: Frozen at ``"1"`` for the second algorithm. A pipeline that extracts and then
#: matches fits inside ``compare`` — that is what stage 7A set out to establish
#: and what the synthetic two-stage adapter demonstrates — so there is nothing a
#: version 2 would buy that is not already available (docs/adr/0039). Raising it
#: needs its own ADR, a compatibility path for version 1, and proof that the
#: existing runs stay readable.
ADAPTER_CONTRACT_VERSION = "1"

#: Which declared contract versions this harness can actually drive. A set, not
#: a single value, so that the day version 2 exists the runner can keep executing
#: version 1 adapters instead of every stored run becoming unreadable at once.
SUPPORTED_ADAPTER_CONTRACT_VERSIONS: frozenset[str] = frozenset(
    {ADAPTER_CONTRACT_VERSION}
)


class FingerprintAlgorithmAdapter(ABC):
    """Runs one algorithm over two prepared images."""

    @property
    @abstractmethod
    def descriptor(self) -> AlgorithmDescriptor:
        """Identity and versions, stable for the lifetime of the adapter."""

    @abstractmethod
    def validate_environment(self) -> EnvironmentReport:
        """Report whether this adapter's dependencies are present and usable.

        Called once per run, before any comparison. Must not raise for an
        ordinary missing dependency — that is an ``UNAVAILABLE`` report.
        """

    @abstractmethod
    def compare(
        self,
        left: PreparedImage,
        right: PreparedImage,
        context: ComparisonContext,
    ) -> RawMatchResult:
        """Compare two prepared images and return a raw score, or a failure.

        Synchronous. The returned result's ``score_direction`` must equal the
        descriptor's; the runner rejects a result that disagrees.
        """
