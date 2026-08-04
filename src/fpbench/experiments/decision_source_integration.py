"""The one seam between the shared decision engine and a particular algorithm.

:mod:`fpbench.experiments.algorithm_decisions` applies a threshold to a finished
run, derives SELF eligibility, builds three evaluation views, writes a receipt
and a marker, and reports where the chain stands. None of that depends on which
algorithm produced the scores — and stage 7D's whole claim rests on it not
starting to depend on one now that a second algorithm has scores to decide.

What *is* algorithm-specific is a single question, asked once at the start:

    **is this run's evidence chain sound enough to decide?**

The answer is different for each algorithm, and not in a way the engine could
guess. SourceAFIS's answer is its own result-set validator plus the general
research chain. NBIS's answer is its own validator, the general research chain,
*and* the Stage 7C alignment marker — because being aligned row by row with the
SourceAFIS run is what makes the two sets of decisions comparable at all, and
the general chain has no field for it (docs/adr/0054, docs/adr/0056).

So the engine is handed one immutable record with two callables, and it never
learns which algorithm it is orchestrating. It cannot: nothing in this module or
in the engine names one.

There is deliberately no registry. An experiment wrapper names exactly one
integration, in code, and that is the whole selection mechanism — the same
choice stage 7A made for :class:`~fpbench.experiments.research_integration.
ResearchAdapterIntegration`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from fpbench.core.derivation_models import SourceFinalizationIdentity
from fpbench.core.enums import ResearchRunStatus
from fpbench.core.errors import ConfigurationError
from fpbench.core.execution_plan_models import ExecutionPlan
from fpbench.core.identifiers import ImageId, PairId, validate_id
from fpbench.core.models import ComparisonPair, ImageRecord
from fpbench.core.result_models import RunDefinition
from fpbench.core.result_set_models import ResultSetEntry, ResultSetManifest
from fpbench.core.serialization import stable_hash

__all__ = [
    "PreparationBinding",
    "PreparationBindingFactory",
    "VerifiedDecisionSource",
    "VerifiedSourceLoader",
    "DecisionSourceIntegration",
]


@dataclass(frozen=True, slots=True)
class PreparationBinding:
    """The verified prepared-image set a derivation rests on.

    Two facts, produced together because producing them separately would verify
    3,000 artefacts twice: what every stored result must claim about the set, and
    the set's own manifest, which the research-state check re-binds the run
    receipt to.

    Both halves are opaque here. The engine passes them straight to whatever the
    integration's loader does with them and never interprets either — the shape
    of ``expectations`` is one algorithm's validator's business.
    """

    expectations: Any
    manifest: Any


#: Build a :class:`PreparationBinding` from a workspace, or return ``None``.
#:
#: ``None`` is the honest answer for a run whose images were passed through
#: untouched: there is no input set to check against, and inventing one would
#: fail results that were never subject to the check.
PreparationBindingFactory = Callable[..., "PreparationBinding | None"]


@dataclass(frozen=True, slots=True)
class VerifiedDecisionSource:
    """One finished run, re-verified, and everything a derivation needs from it.

    Every field here has already been *checked* by the integration's loader, not
    merely read. ``research_status`` is the outcome of re-running the general
    research inspection over the current files; ``algorithm_validation_fingerprint``
    is the digest of the algorithm's own pass over the same files; and
    ``source_finalization`` names the last-written markers that make the raw
    scores authoritative.

    Note what is absent: a score, a threshold, a metric, and any statement about
    which algorithm this is. The engine gets manifests, pairs, images and
    identities. It does not get a way to ask "was this NBIS?", because there is
    no correct use for the answer (docs/adr/0056).
    """

    research_status: ResearchRunStatus

    run: RunDefinition
    plan: ExecutionPlan

    pairs: Mapping[PairId, ComparisonPair]
    images: Mapping[ImageId, ImageRecord]
    pair_manifest_hash: str

    result_set: ResultSetManifest
    result_set_entries: tuple[ResultSetEntry, ...]

    #: The digest of the algorithm-specific validation pass. Recorded so a later
    #: reader can tell that *some* algorithm-specific check ran, and which one,
    #: without this module knowing what it checked.
    algorithm_validation_fingerprint: str

    preparation_binding: PreparationBinding | None

    source_finalization: SourceFinalizationIdentity

    def __post_init__(self) -> None:
        object.__setattr__(self, "result_set_entries", tuple(self.result_set_entries))

    @property
    def is_research_ready(self) -> bool:
        return self.research_status is ResearchRunStatus.RESEARCH_READY


#: Load and re-verify one run's whole evidence chain.
#:
#: Called with keywords: ``workspace``, ``repository_root``, ``run_id``,
#: ``software``, ``require_ready`` and ``preparation_binding``. It returns a
#: :class:`VerifiedDecisionSource` or raises; it never returns a half-checked one
#: with a flag saying so.
VerifiedSourceLoader = Callable[..., VerifiedDecisionSource]


@dataclass(frozen=True, slots=True)
class DecisionSourceIntegration:
    """Everything the shared decision engine needs to decide *this* algorithm.

    ``algorithm_id`` is here to be checked, not to be branched on. The engine
    asserts that the run it loaded declares this algorithm and then forgets the
    string; there is no ``if`` anywhere downstream that reads it, and a
    structural test proves as much by walking the syntax tree.
    """

    integration_id: str
    algorithm_id: str

    load_verified_source: VerifiedSourceLoader
    preparation_binding_factory: PreparationBindingFactory | None = None

    def __post_init__(self) -> None:
        validate_id(self.integration_id)
        validate_id(self.algorithm_id)
        if not callable(self.load_verified_source):
            raise ConfigurationError("load_verified_source must be callable")
        if self.preparation_binding_factory is not None and not callable(
            self.preparation_binding_factory
        ):
            raise ConfigurationError(
                "preparation_binding_factory must be callable or None; None means "
                "this route has no materialised input set to bind"
            )

    @property
    def integration_fingerprint(self) -> str:
        """Identity of the seam, independent of its callables.

        The callables are already pinned by the fpbench source commit that every
        derivation records. What this covers is the declaration: which
        integration, for which algorithm, and whether it binds an input set.
        """
        return stable_hash(
            {
                "schema": "decision_source_integration_v1",
                "integration_id": self.integration_id,
                "algorithm_id": self.algorithm_id,
                "binds_preparation_set": self.preparation_binding_factory is not None,
            },
            length=64,
        )

    def require_source_algorithm(self, source: VerifiedDecisionSource) -> None:
        """The run this integration loaded is the algorithm it is for.

        Cheap, and the only thing standing between a mis-wired wrapper and a
        derivation attributed to the wrong matcher. The profile applicability
        check downstream would also catch it — but it would catch it as "this
        threshold does not apply", which is a confusing way to report a wiring
        mistake.

        Raises:
            ConfigurationError: the run was produced by a different algorithm.
        """
        actual = source.run.algorithm.algorithm_id
        if actual != self.algorithm_id:
            raise ConfigurationError(
                f"decision source integration {self.integration_id!r} is for "
                f"algorithm {self.algorithm_id!r}, but run {source.run.run_id} was "
                f"produced by {actual!r}"
            )
