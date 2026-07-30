"""A research-ready world with scores chosen by hand.

The dummy matcher scores image digests, which is exactly right for testing the
harness and useless for testing a threshold: nobody can say in advance whether
a digest-derived score lands above or below 40. So this module builds the same
world with a *scripted* adapter, where every comparison's score is decided by
the test.

The default script is the one the stage's specification names:

    PLAIN SELF   50   above the threshold
    ROLL SELF    45   above the threshold
    mated        42   above the threshold
    non-mated    10   below it

which makes every unit eligible and every impostor pair a non-match. Individual
tests then move one score at a time to produce the interesting cases —
a finger that fails ROLL SELF, a comparison that produced no score at all — and
assert the exact verdict that should follow.

**No biometric claim is made or possible here.** The scores are literals in a
test file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping

from fpbench.adapters.base import ADAPTER_CONTRACT_VERSION, FingerprintAlgorithmAdapter
from fpbench.core.decision_models import (
    DecisionProfile,
    ThresholdComparator,
    ThresholdOrigin,
)
from fpbench.core.enums import (
    EnvironmentStatus,
    FailureCode,
    FailureStage,
    ProtocolStage,
    ScoreDirection,
)
from fpbench.core.execution_models import (
    AlgorithmDescriptor,
    EnvironmentReport,
    FailureInfo,
    RawMatchResult,
    runtime_description,
)
from fpbench.decisions.profiles import build_decision_profile
from fpbench.eligibility import build_self_eligibility_units
from fpbench.storage.manifest_store import ManifestStore
from runworld import RunWorld, build_world, finalise_research_world

__all__ = [
    "ScriptedAdapter",
    "DecisionWorld",
    "build_decision_world",
    "documented_profile_for",
    "SELF_INDEPENDENCE_METADATA",
    "DEFAULT_SCORES",
    "THRESHOLD",
]

THRESHOLD = "40"

#: The default script from the stage specification.
DEFAULT_SCORES: Mapping[ProtocolStage, float] = {
    ProtocolStage.PLAIN_SELF: 50.0,
    ProtocolStage.ROLL_SELF: 45.0,
    ProtocolStage.PLAIN_ROLL_MATED: 42.0,
    ProtocolStage.PLAIN_ROLL_NON_MATED: 10.0,
}

#: What a SELF result must carry before eligibility may rest on it. These are
#: adapter-contract terms; the scripted adapter emits them so that the
#: independence check exercises its real path rather than being bypassed.
SELF_INDEPENDENCE_METADATA: Mapping[str, str] = {
    "extraction_policy": "independent_both_sides",
    "extraction_count": "2",
    "template_cache": "disabled",
}


class ScriptedAdapter(FingerprintAlgorithmAdapter):
    """Returns whatever score the test says, keyed by the pair of image ids.

    A real adapter is told nothing about the comparison it is performing, and
    neither is this one: it looks the score up by image id, which is all it
    receives (docs/adr/0010). The *test* knows which pair those ids belong to.
    """

    def __init__(
        self,
        *,
        scores: Mapping[tuple[str, str], float],
        failures: Mapping[tuple[str, str], FailureInfo] | None = None,
        algorithm_id: str = "scripted_matcher",
    ) -> None:
        self._scores = dict(scores)
        self._failures = dict(failures or {})
        self._descriptor = AlgorithmDescriptor(
            algorithm_id=algorithm_id,
            display_name="Scripted test matcher",
            adapter_id=algorithm_id,
            adapter_version="1",
            adapter_contract_version=ADAPTER_CONTRACT_VERSION,
            implementation_version="test-1",
            score_direction=ScoreDirection.HIGHER_IS_BETTER,
            deterministic=True,
        )

    @property
    def descriptor(self) -> AlgorithmDescriptor:
        return self._descriptor

    def validate_environment(self) -> EnvironmentReport:
        return EnvironmentReport(
            status=EnvironmentStatus.READY,
            implementation_version="test-1",
            runtime=runtime_description(),
            dependencies={},
        )

    def compare(self, left, right, context) -> RawMatchResult:
        key = (str(left.image_id), str(right.image_id))
        failure = self._failures.get(key)
        if failure is not None:
            return RawMatchResult.failed(
                failure=failure,
                score_direction=ScoreDirection.HIGHER_IS_BETTER,
                metadata=dict(SELF_INDEPENDENCE_METADATA),
            )
        if key not in self._scores:
            raise AssertionError(f"no scripted score for {key}")
        return RawMatchResult.success(
            raw_score=float(self._scores[key]),
            score_direction=ScoreDirection.HIGHER_IS_BETTER,
            metadata=dict(SELF_INDEPENDENCE_METADATA),
        )


@dataclass
class DecisionWorld:
    """A finalised research run plus everything a derivation needs from it."""

    run_world: RunWorld
    profile: DecisionProfile
    units: tuple
    pair_manifest_hash: str
    result_set: object
    result_set_entries: tuple

    @property
    def run(self):
        return self.run_world.run

    @property
    def plan(self):
        return self.run_world.plan

    @property
    def pairs(self):
        return self.run_world.pair_index

    @property
    def workspace(self) -> Path:
        return self.run_world.workspace

    @property
    def result_store(self):
        return self.run_world.result_store

    def decisions_kwargs(self) -> dict:
        """The arguments ``apply_decision_profile`` takes, ready to splat."""
        return {
            "profile": self.profile,
            "run": self.run,
            "plan": self.plan,
            "result_set": self.result_set,
            "result_set_entries": self.result_set_entries,
            "result_store": self.result_store,
        }


def documented_profile_for(
    run,
    *,
    threshold: str = THRESHOLD,
    execution_profiles: tuple[str, ...] | None = None,
) -> DecisionProfile:
    """A documented-origin profile bound to this run's algorithm build."""
    return build_decision_profile(
        profile_id="test_documented_profile_v1",
        display_name="Test documented profile",
        profile_version="1",
        origin=ThresholdOrigin.DOCUMENTED_NATIVE,
        algorithm_id=run.algorithm.algorithm_id,
        implementation_version=run.algorithm.implementation_version,
        algorithm_fingerprint=run.algorithm_fingerprint,
        score_direction=run.algorithm.score_direction,
        comparator=ThresholdComparator.GREATER_THAN_OR_EQUAL,
        threshold=threshold,
        source_kind="upstream_documentation",
        source_reference="test_reference",
        source_version="1",
        allowed_execution_profiles=execution_profiles
        or (run.execution_profile.profile_id,),
        calibration_performed=False,
        calibration_manifest_fingerprint=None,
        metadata={},
    )


def build_decision_world(
    tmp_path: Path,
    *,
    subjects: int = 2,
    fingers: int = 2,
    releases: tuple[str, ...] = ("SD300A",),
    score_for: Callable[[object], float] | None = None,
    failure_for: Callable[[object], FailureInfo | None] | None = None,
    threshold: str = THRESHOLD,
) -> DecisionWorld:
    """A finalised research run whose scores the caller chose.

    Args:
        score_for: ``pair -> score``. Defaults to the stage's script.
        failure_for: ``pair -> FailureInfo | None``, for testing undecidables.
    """
    # The pairs have to exist before the adapter can be scripted over them, and
    # the world builder needs the adapter. Build a throwaway world first purely
    # to learn the pair shapes, then build the real one.
    shape = build_world(
        tmp_path / "shape", subjects=subjects, fingers=fingers, releases=releases
    )

    scores: dict[tuple[str, str], float] = {}
    failures: dict[tuple[str, str], FailureInfo] = {}
    for pair in shape.pairs:
        key = (str(pair.left_image_id), str(pair.right_image_id))
        failure = failure_for(pair) if failure_for else None
        if failure is not None:
            failures[key] = failure
            continue
        scores[key] = (
            score_for(pair) if score_for else DEFAULT_SCORES[pair.protocol_stage]
        )

    adapter = ScriptedAdapter(scores=scores, failures=failures)
    world = build_world(
        tmp_path / "world",
        subjects=subjects,
        fingers=fingers,
        releases=releases,
        adapter=adapter,
        research=True,
    )
    world.executor().execute(finalize=False)
    finalise_research_world(world)

    result_set, entries = world.result_set_store.read_result_set(world.run.run_id)

    jobs_by_pair = {
        str(planned.job.pair_id): planned.job.job_id for planned in world.plan.jobs
    }
    units = build_self_eligibility_units(
        pairs=world.pairs,
        images=world.images,
        jobs_by_pair=jobs_by_pair,
        protocol_id=world.run.protocol_id,
        cohort_id=str(world.run.cohort_id),
    )

    return DecisionWorld(
        run_world=world,
        profile=documented_profile_for(world.run, threshold=threshold),
        units=units,
        pair_manifest_hash=world.run.pair_manifest_hash,
        result_set=result_set,
        result_set_entries=entries,
    )


@dataclass
class DerivedChain:
    """Everything ``derive`` produces, stored and ready to inspect."""

    world: DecisionWorld
    decision_set: object
    eligibility: object
    views: dict
    receipt: object | None = None
    marker: object | None = None

    @property
    def decision_set_id(self) -> str:
        return self.decision_set.manifest.decision_set_id


def derive_full_chain(
    world: DecisionWorld,
    *,
    software=None,
    store: bool = True,
    finalize: bool = False,
) -> DerivedChain:
    """Run the whole 5A derivation over a scripted world.

    Mirrors what the experiment module does, without its clean-tree
    requirement — a test cannot commit, and the provenance gate is exercised by
    the real derivation instead.
    """
    from fpbench.core.evaluation_view_models import (
        MATED_CONDITIONAL_VIEW,
        MATED_UNCONDITIONAL_VIEW,
        NON_MATED_SANITY_VIEW,
    )
    from fpbench.decisions import apply_decision_profile
    from fpbench.derivations import (
        build_derivation_finalization_marker,
        build_derivation_receipt,
    )
    from fpbench.eligibility import derive_self_eligibility
    from fpbench.evaluation import (
        build_mated_conditional_view,
        build_mated_unconditional_view,
        build_non_mated_sanity_view,
    )
    from fpbench.storage.decision_set_store import DecisionSetStore
    from fpbench.storage.eligibility_set_store import EligibilitySetStore
    from fpbench.storage.evaluation_view_store import EvaluationViewStore
    from runworld import research_provenance

    software = software or research_provenance()

    decision_set = apply_decision_profile(
        **world.decisions_kwargs(), derivation_software=software
    )
    eligibility = derive_self_eligibility(
        run=world.run,
        units=world.units,
        decisions=decision_set.by_job(),
        decision_set=decision_set.manifest,
        pair_manifest_hash=world.pair_manifest_hash,
    )
    common = {
        "run": world.run,
        "plan": world.plan,
        "pairs": world.pairs,
        "decisions": decision_set.by_job(),
        "decision_set": decision_set.manifest,
        "pair_manifest_hash": world.pair_manifest_hash,
    }
    views = {
        MATED_UNCONDITIONAL_VIEW: build_mated_unconditional_view(**common),
        MATED_CONDITIONAL_VIEW: build_mated_conditional_view(
            **common,
            eligibility=eligibility.manifest,
            eligibility_records=eligibility.records,
        ),
        NON_MATED_SANITY_VIEW: build_non_mated_sanity_view(**common, finger_shift=1),
    }

    chain = DerivedChain(
        world=world, decision_set=decision_set, eligibility=eligibility, views=views
    )
    if not store:
        return chain

    workspace = world.workspace
    set_id = decision_set.manifest.decision_set_id
    DecisionSetStore(workspace).ensure_decision_set(
        profile=decision_set.profile,
        manifest=decision_set.manifest,
        records=decision_set.records,
    )
    EligibilitySetStore(workspace).ensure_eligibility_set(
        decision_set_id=set_id,
        manifest=eligibility.manifest,
        records=eligibility.records,
    )
    for view in views.values():
        EvaluationViewStore(workspace).ensure_view(
            run_id=world.run.run_id,
            decision_set_id=set_id,
            manifest=view.manifest,
            entries=view.entries,
        )

    if finalize:
        store_ = DecisionSetStore(workspace)
        receipt = build_derivation_receipt(
            run=world.run,
            result_set=world.result_set,
            decision_set=decision_set.manifest,
            eligibility=eligibility.manifest,
            unconditional_view=views[MATED_UNCONDITIONAL_VIEW].manifest,
            conditional_view=views[MATED_CONDITIONAL_VIEW].manifest,
            non_mated_view=views[NON_MATED_SANITY_VIEW].manifest,
            derivation_software=software,
            pair_manifest_hash=world.pair_manifest_hash,
        )
        store_.ensure_receipt(decision_set_id=set_id, receipt=receipt)
        stored_receipt = store_.read_receipt(world.run.run_id, set_id)
        marker = build_derivation_finalization_marker(
            run=world.run,
            result_set=world.result_set,
            decision_set=decision_set.manifest,
            eligibility=eligibility.manifest,
            unconditional_view=views[MATED_UNCONDITIONAL_VIEW].manifest,
            conditional_view=views[MATED_CONDITIONAL_VIEW].manifest,
            non_mated_view=views[NON_MATED_SANITY_VIEW].manifest,
            receipt=stored_receipt,
            derivation_software=software,
        )
        store_.ensure_finalization(
            run_id=world.run.run_id, decision_set_id=set_id, marker=marker
        )
        chain.receipt = stored_receipt
        chain.marker = marker

    return chain


def inspect_chain(world: DecisionWorld, decision_set_id: str | None):
    """Run the real status inspector over a scripted world."""
    from fpbench.core.enums import ResearchRunStatus
    from fpbench.derivations import inspect_decision_derivation

    definition = None
    if decision_set_id is not None:
        from types import SimpleNamespace

        definition = SimpleNamespace(
            decision_profile_fingerprint=world.profile.profile_fingerprint
        )

    return inspect_decision_derivation(
        run=world.run,
        plan=world.plan,
        pairs=world.pairs,
        units=world.units,
        result_set=world.result_set,
        result_set_entries=world.result_set_entries,
        result_store=world.result_store,
        research_status=ResearchRunStatus.RESEARCH_READY,
        definition=definition,
        decision_set_id=decision_set_id,
        pair_manifest_hash=world.pair_manifest_hash,
        workspace=world.workspace,
    )


def extraction_failure() -> FailureInfo:
    """The one failure a matcher may legitimately produce for a real print."""
    return FailureInfo(
        code=FailureCode.TEMPLATE_EXTRACTION_FAILED,
        stage=FailureStage.EXTRACTION,
        message="no minutiae found",
    )
