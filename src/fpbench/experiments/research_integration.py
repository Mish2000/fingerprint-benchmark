"""The one seam between the shared research engine and a particular algorithm.

:mod:`fpbench.experiments.algorithm_research` orchestrates a research run:
materialise a runtime bundle, define a run, plan 6,000 comparisons, execute them
one at a time, audit, validate, give the results an identity, write a receipt and
a marker. None of that depends on which algorithm is being run — and stage 7A's
whole claim is that it must not start depending on one when the second algorithm
arrives.

So every difference is injected, through one immutable record:

``adapter_id`` / ``runtime_asset_roles``
    Which adapter this is, and which files it needs pinned. A route made of two
    executables and a support file declares three roles, and all three reach the
    bundle fingerprint (docs/adr/0042).

``create_development_runtime``
    Build the algorithm from whatever the developer has locally — a Maven target
    directory, a compiled build tree — and say where each runtime file is. This
    is the only place a build layout is known.

``create_research_delegate``
    Build the same algorithm again, pinned to the materialised bundle. The engine
    wraps the result in :class:`~fpbench.execution.research.ResearchModeAdapter`
    itself, so an adapter never has to know what research provenance looks like.

``validate_result_set``
    Decide, for this algorithm, which recorded failures are biometric outcomes
    and which mean the harness broke. The engine cannot know: a template that
    would not extract is data for SourceAFIS and would be data for NBIS, but a
    non-zero exit from an unfamiliar tool might be either, and guessing is how a
    broken run becomes a published one (docs/adr/0013).

What is deliberately absent is a registry. There is no ``latest``, no module
scanning and no entry point: the experiment wrapper names exactly one
integration, in code, and that is the whole selection mechanism (spec section 50).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Protocol, runtime_checkable

from fpbench.adapters.base import FingerprintAlgorithmAdapter
from fpbench.core.errors import ConfigurationError, ResearchPreflightError
from fpbench.core.execution_models import descriptor_fingerprint
from fpbench.core.execution_plan_models import ExecutionPlan
from fpbench.core.identifiers import ImageId, PairId, validate_id
from fpbench.core.models import ComparisonPair, ImageRecord
from fpbench.core.provenance_models import SoftwareProvenance
from fpbench.core.result_models import RunDefinition
from fpbench.core.run_state_models import IntegrityIssue
from fpbench.core.runtime_models import RunRuntimeReference, RuntimeBundleDefinition
from fpbench.experiments.prepared_input_validation import PreparedInputExpectations
from fpbench.storage.result_store import ResultStore

__all__ = [
    "DevelopmentAdapterRuntime",
    "ResearchAdapterIntegration",
    "ResearchValidationContext",
    "AlgorithmValidationReport",
    "DevelopmentRuntimeFactory",
    "ResearchDelegateFactory",
    "ResearchResultValidator",
]


# ------------------------------------------------------------ what an adapter
#                                                               looks like
#                                                               before pinning


@dataclass(frozen=True, slots=True)
class DevelopmentAdapterRuntime:
    """An algorithm as it exists on the developer's machine, before pinning.

    Two things, because the engine needs exactly two: something that can report
    an environment and a descriptor, and the files whose bytes will be copied
    into an immutable bundle. Where those files came from — a Maven target
    directory, a ``make`` output tree — is the integration's business and reaches
    nothing downstream (docs/adr/0018).
    """

    adapter: FingerprintAlgorithmAdapter
    assets: Mapping[str, Path]

    def __post_init__(self) -> None:
        from types import MappingProxyType

        assets = dict(self.assets)
        if not assets:
            raise ConfigurationError(
                "a development runtime must name at least one file to pin; an "
                "algorithm with nothing to materialise cannot be attributed"
            )

        resolved: dict[str, Path] = {}
        seen: dict[Path, str] = {}
        for role, source in assets.items():
            validate_id(str(role))
            path = Path(source)
            if not path.is_absolute():
                raise ConfigurationError(
                    f"runtime asset {role!r} must be an absolute path; a relative "
                    "one means whatever directory the caller happened to be in"
                )
            if path.is_symlink():
                raise ConfigurationError(
                    f"runtime asset {role!r} is a symlink; a bundle owns its bytes "
                    "rather than pointing at someone else's"
                )
            if not path.is_file():
                raise ConfigurationError(
                    f"runtime asset {role!r} is not a regular file: {path.name}"
                )
            previous = seen.get(path)
            if previous is not None:
                raise ConfigurationError(
                    f"runtime assets {previous!r} and {role!r} name the same file; "
                    "two roles cannot share one set of bytes"
                )
            seen[path] = str(role)
            resolved[str(role)] = path

        object.__setattr__(self, "assets", MappingProxyType(dict(sorted(resolved.items()))))

    @property
    def roles(self) -> frozenset[str]:
        return frozenset(self.assets)


#: Build the algorithm from a local build tree.
#:
#: ``(repository_root, algorithm_config, development_overrides)``. The overrides
#: are how an experiment says "materialise from this file instead of the build
#: output" without the engine growing a parameter that only one algorithm has.
DevelopmentRuntimeFactory = Callable[
    [Path, Path, Mapping[str, object]],
    DevelopmentAdapterRuntime,
]

#: Build the same algorithm pinned to a materialised bundle.
#:
#: ``(repository_root, algorithm_config, bundle, role -> bundled path, software)``.
#: Returns the algorithm's own adapter. The engine wraps it in
#: ``ResearchModeAdapter``; an adapter that wrapped itself would put the research
#: environment in two places and let them disagree.
ResearchDelegateFactory = Callable[
    [
        Path,
        Path,
        RuntimeBundleDefinition,
        Mapping[str, Path],
        SoftwareProvenance,
    ],
    FingerprintAlgorithmAdapter,
]


# ------------------------------------------------------------------ validation


@dataclass(frozen=True, slots=True)
class ResearchValidationContext:
    """Everything an algorithm's validator is given to check a finished run.

    Deliberately the stored artefacts and the manifests they claim to belong to,
    and nothing else. A validator reads results; it does not execute anything,
    does not repair anything, and has no threshold — the question "is this score
    high?" belongs to a decision profile and to a different stage entirely
    (docs/adr/0003).
    """

    run: RunDefinition
    plan: ExecutionPlan
    pairs: Mapping[PairId, ComparisonPair]
    images: Mapping[ImageId, ImageRecord]

    result_store: ResultStore
    runtime_reference: RunRuntimeReference

    #: What the results must claim about the input set they were produced from.
    #: ``None`` for a run over untouched source images: there is no set for the
    #: results to be checked against, and inventing one would fail results that
    #: were never subject to the check.
    preparation: PreparedInputExpectations | None = None


@runtime_checkable
class AlgorithmValidationReport(Protocol):
    """What every algorithm's validator must be able to report.

    The two failure counts are separate because they mean opposite things.
    ``algorithmic_failures`` is data — an algorithm declining a print is a real
    property of real fingerprints and a run full of them is still a run
    (docs/adr/0013). ``blocking_failures`` is a defect: the comparison never
    happened as designed, and no receipt may be issued over it.

    ``validation_fingerprint`` is what lets a receipt name the exact pass it
    rests on, so re-running validation later either reproduces the digest or
    proves something changed.
    """

    run_id: str
    plan_id: str

    total_results: int
    successful_results: int
    algorithmic_failures: int
    blocking_failures: int

    #: Failure code to how many results carried it. Part of the contract because
    #: the receipt records it: a run's receipt says *which* failures occurred,
    #: not merely how many, and a validator that reported only totals would make
    #: the receipt less informative than the results it summarises.
    failure_counts: Mapping[str, int]

    validation_fingerprint: str

    @property
    def is_clean(self) -> bool:
        """True when nothing blocks a research receipt."""

    @property
    def errors(self) -> tuple[IntegrityIssue, ...]:
        """The findings that made it unclean, in the order they were found."""


#: Inspect one finished run's stored results against one algorithm's contract.
ResearchResultValidator = Callable[
    [ResearchValidationContext],
    AlgorithmValidationReport,
]


# ----------------------------------------------------------------- the seam


@dataclass(frozen=True, slots=True)
class ResearchAdapterIntegration:
    """Everything the shared research engine needs to run *this* algorithm."""

    integration_id: str
    adapter_id: str

    runtime_asset_roles: tuple[str, ...]
    primary_runtime_asset_role: str

    create_development_runtime: DevelopmentRuntimeFactory
    create_research_delegate: ResearchDelegateFactory
    validate_result_set: ResearchResultValidator

    def __post_init__(self) -> None:
        validate_id(self.integration_id)
        validate_id(self.adapter_id)

        roles = tuple(str(role) for role in self.runtime_asset_roles)
        if not roles:
            raise ConfigurationError(
                f"integration {self.integration_id!r} declares no runtime assets; "
                "an algorithm whose executables are not pinned cannot produce "
                "citable results (docs/adr/0018)"
            )
        for role in roles:
            validate_id(role)
        if len(set(roles)) != len(roles):
            raise ConfigurationError(
                f"integration {self.integration_id!r} declares a duplicate runtime "
                f"asset role: {sorted({r for r in roles if roles.count(r) > 1})}"
            )
        object.__setattr__(self, "runtime_asset_roles", roles)

        validate_id(self.primary_runtime_asset_role)
        if self.primary_runtime_asset_role not in roles:
            raise ConfigurationError(
                f"integration {self.integration_id!r} names "
                f"{self.primary_runtime_asset_role!r} as its primary runtime asset, "
                f"but its roles are {list(roles)}"
            )

        for name in (
            "create_development_runtime",
            "create_research_delegate",
            "validate_result_set",
        ):
            if not callable(getattr(self, name)):
                raise ConfigurationError(f"{name} must be callable")

    @property
    def roles(self) -> frozenset[str]:
        return frozenset(self.runtime_asset_roles)

    # ------------------------------------------------------------- checking

    def require_development_runtime(
        self, development: DevelopmentAdapterRuntime
    ) -> None:
        """The local build is the algorithm this integration claims it is.

        Raises:
            ResearchPreflightError: the roles do not match the declaration, or
                the adapter describes a different algorithm.
        """
        if development.roles != self.roles:
            missing = sorted(self.roles - development.roles)
            extra = sorted(development.roles - self.roles)
            raise ResearchPreflightError(
                f"integration {self.integration_id!r} declares runtime roles "
                f"{list(self.runtime_asset_roles)}, but the development runtime "
                f"supplied missing={missing} extra={extra}"
            )
        actual = development.adapter.descriptor.adapter_id
        if actual != self.adapter_id:
            raise ResearchPreflightError(
                f"integration {self.integration_id!r} is for adapter "
                f"{self.adapter_id!r}, but the development runtime built "
                f"{actual!r}"
            )

    def require_bundle_matches(self, bundle: RuntimeBundleDefinition) -> None:
        """A materialised bundle holds exactly this integration's assets.

        Checked on the way in *and* every time a prepared run is reloaded: a
        bundle that acquired a role, lost one, or belongs to another adapter is
        not the runtime the run was defined against, whatever the surviving files
        hash to.

        Raises:
            ResearchPreflightError: it does not.
        """
        if bundle.adapter_id != self.adapter_id:
            raise ResearchPreflightError(
                f"runtime bundle {bundle.bundle_id} belongs to adapter "
                f"{bundle.adapter_id!r}, not {self.adapter_id!r}"
            )
        present = {asset.role for asset in bundle.assets}
        if present != self.roles:
            missing = sorted(self.roles - present)
            extra = sorted(present - self.roles)
            raise ResearchPreflightError(
                f"runtime bundle {bundle.bundle_id} holds roles {sorted(present)}; "
                f"integration {self.integration_id!r} needs "
                f"{list(self.runtime_asset_roles)} (missing={missing} extra={extra})"
            )

    def require_same_algorithm(
        self,
        *,
        development: FingerprintAlgorithmAdapter,
        research: FingerprintAlgorithmAdapter,
    ) -> None:
        """Pinning changed where the bytes live, not which algorithm they are.

        The development adapter is what preflight approved; the research adapter
        is what will actually run. If those two describe different algorithms then
        the environment check proved nothing about the thing that produced the
        scores.

        Raises:
            ResearchPreflightError: the two descriptors disagree in any field
                that reaches the fingerprint.
        """
        left = development.descriptor
        right = research.descriptor
        for label, first, second in (
            ("adapter_id", left.adapter_id, right.adapter_id),
            ("algorithm_id", left.algorithm_id, right.algorithm_id),
            (
                "score_direction",
                left.score_direction.value,
                right.score_direction.value,
            ),
            (
                "implementation_version",
                left.implementation_version,
                right.implementation_version,
            ),
            (
                "adapter_contract_version",
                left.adapter_contract_version,
                right.adapter_contract_version,
            ),
            ("adapter_version", left.adapter_version, right.adapter_version),
        ):
            if first != second:
                raise ResearchPreflightError(
                    f"the development adapter reports {label}={first!r} but the "
                    f"pinned research adapter reports {second!r}; materialising a "
                    "runtime bundle must not change what the algorithm is"
                )
        if descriptor_fingerprint(left) != descriptor_fingerprint(right):
            raise ResearchPreflightError(
                "the development and research adapters fingerprint differently, "
                "so the environment that was checked is not the one that would "
                "run"
            )
