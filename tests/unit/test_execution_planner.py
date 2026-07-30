"""A plan must be a pure function of the run and its pair manifest.

The two halves of that: the same inputs always give the same plan no matter how
they arrive, and any input that could change which comparisons happen changes
the plan's identity.
"""

from __future__ import annotations

import random
from dataclasses import replace

import pytest

from fpbench.core.enums import ProtocolStage
from fpbench.core.errors import PlanningError
from fpbench.execution.planner import STAGE_ORDER, build_execution_plan
from runworld import COHORT_ID, PROTOCOL_ID, build_world


@pytest.fixture
def world(tmp_path):
    return build_world(tmp_path, subjects=2, fingers=2)


def plan_from(world, *, pairs=None, metadata=None, run=None):
    return build_execution_plan(
        run=run or world.run,
        pairs=pairs if pairs is not None else world.pairs,
        pair_manifest_metadata=metadata or world.pair_manifest_metadata,
    )


# ---------------------------------------------------------------- determinism


def test_the_same_pairs_give_the_same_plan(world):
    assert plan_from(world) == plan_from(world) or (
        plan_from(world).definition.plan_fingerprint
        == plan_from(world).definition.plan_fingerprint
    )


def test_shuffling_the_input_does_not_change_the_plan(world):
    ordered = plan_from(world)
    for seed in range(5):
        shuffled = list(world.pairs)
        random.Random(seed).shuffle(shuffled)
        candidate = plan_from(world, pairs=shuffled)
        assert candidate.definition.plan_fingerprint == ordered.definition.plan_fingerprint
        assert candidate.job_ids() == ordered.job_ids()


def test_the_creation_timestamp_is_not_part_of_the_identity(world):
    first = plan_from(world)
    second = plan_from(world)
    assert first.definition.created_utc != "" and second.definition.created_utc != ""
    assert first.definition.plan_fingerprint == second.definition.plan_fingerprint


def test_plan_id_is_derived_from_the_fingerprint(world):
    plan = plan_from(world)
    assert plan.plan_id == f"plan_{plan.definition.plan_fingerprint[:12]}"
    assert len(plan.definition.plan_fingerprint) == 64
    assert len(plan.definition.job_manifest_hash) == 64


# ------------------------------------------------------------------- ordering


def test_jobs_follow_stage_then_release_then_pair_id(world):
    plan = plan_from(world)
    by_pair = {pair.pair_id: pair for pair in world.pairs}
    keys = [
        (
            STAGE_ORDER[by_pair[item.job.pair_id].protocol_stage],
            by_pair[item.job.pair_id].release,
            str(item.job.pair_id),
        )
        for item in plan.jobs
    ]
    assert keys == sorted(keys)


def test_every_self_comparison_is_planned_before_any_cross_impression_one(tmp_path):
    world = build_world(tmp_path, subjects=2, fingers=2, releases=("SD300A", "SD300B"))
    plan = plan_from(world)
    by_pair = {pair.pair_id: pair for pair in world.pairs}
    stages = [by_pair[item.job.pair_id].protocol_stage for item in plan.jobs]
    last_self = max(i for i, stage in enumerate(stages) if stage.is_self)
    first_cross = min(i for i, stage in enumerate(stages) if not stage.is_self)
    assert last_self < first_cross


def test_release_order_is_stable_within_a_stage(tmp_path):
    world = build_world(tmp_path, subjects=1, fingers=2, releases=("SD300C", "SD300A"))
    plan = plan_from(world)
    by_pair = {pair.pair_id: pair for pair in world.pairs}
    releases = [
        by_pair[item.job.pair_id].release
        for item in plan.jobs
        if by_pair[item.job.pair_id].protocol_stage is ProtocolStage.PLAIN_SELF
    ]
    assert releases == ["SD300A", "SD300A", "SD300C", "SD300C"]


# ---------------------------------------------------------------- plan shape


def test_one_job_per_pair(world):
    plan = plan_from(world)
    assert plan.total_jobs == len(world.pairs)
    assert len(plan.jobs) == len(world.pairs)


def test_ordinals_are_contiguous_from_zero(world):
    plan = plan_from(world)
    assert [item.ordinal for item in plan.jobs] == list(range(plan.total_jobs))


def test_every_job_is_a_first_attempt(world):
    assert all(item.job.attempt == 1 for item in plan_from(world).jobs)


def test_every_job_belongs_to_the_run(world):
    plan = plan_from(world)
    assert {item.job.run_id for item in plan.jobs} == {world.run.run_id}


def test_ids_and_fingerprints_are_unique(world):
    plan = plan_from(world)
    assert len(set(plan.job_ids())) == plan.total_jobs
    assert len({item.job.job_fingerprint for item in plan.jobs}) == plan.total_jobs
    assert len(set(plan.pair_ids())) == plan.total_jobs


def test_stage_and_release_counts_account_for_every_job(tmp_path):
    world = build_world(tmp_path, subjects=3, fingers=2, releases=("SD300A", "SD300B"))
    plan = plan_from(world)
    definition = plan.definition
    assert sum(definition.stage_counts.values()) == definition.total_jobs
    assert sum(definition.release_counts.values()) == definition.total_jobs
    assert definition.release_counts == {"SD300A": 24, "SD300B": 24}
    assert set(definition.stage_counts) == {stage.value for stage in ProtocolStage}


def test_a_plan_carries_no_stage_on_individual_jobs(world):
    """Stage counts are an aggregate; a job stays blind (docs/adr/0010)."""
    fields = set(type(plan_from(world).jobs[0].job).__dataclass_fields__)
    assert {"protocol_stage", "ground_truth", "threshold"} & fields == set()


# ---------------------------------------------------------------- provenance


@pytest.mark.parametrize(
    "change",
    [
        {"protocol_id": "other_protocol"},
        {"cohort_id": "other_cohort_1"},
        {"pair_manifest_hash": "b" * 64},
    ],
)
def test_a_manifest_from_another_run_is_refused(world, change):
    metadata = {**world.pair_manifest_metadata, **change}
    with pytest.raises(PlanningError):
        plan_from(world, metadata=metadata)


@pytest.mark.parametrize(
    "missing", ["protocol_id", "cohort_id", "pair_manifest_hash"]
)
def test_missing_provenance_metadata_is_refused(world, missing):
    metadata = dict(world.pair_manifest_metadata)
    metadata.pop(missing)
    with pytest.raises(PlanningError, match=missing):
        plan_from(world, metadata=metadata)


def test_provenance_is_checked_before_any_job_is_built(world):
    """A plan built from the wrong manifest would run perfectly and mean nothing."""
    metadata = {
        "protocol_id": PROTOCOL_ID,
        "cohort_id": str(COHORT_ID),
        "pair_manifest_hash": "c" * 64,
    }
    with pytest.raises(PlanningError, match="pair_manifest_hash"):
        plan_from(world, metadata=metadata)


# ---------------------------------------------------------------- duplicates


def test_a_repeated_pair_is_refused(world):
    duplicated = list(world.pairs) + [world.pairs[0]]
    with pytest.raises(PlanningError, match="more than once"):
        plan_from(world, pairs=duplicated)


def test_a_repeated_pair_is_refused_even_when_identical(world):
    """Keeping the first would make the plan depend on input order."""
    duplicated = [world.pairs[0], world.pairs[0]]
    with pytest.raises(PlanningError):
        plan_from(world, pairs=duplicated)


def test_two_pairs_over_the_same_images_are_not_a_duplicate(world):
    """Distinct pair ids over the same images are a legitimate protocol shape."""
    original = world.pairs[0]
    twin = replace(original, pair_id=f"{original.pair_id}_again")
    plan = plan_from(world, pairs=[original, twin])
    assert plan.total_jobs == 2
    assert len(set(plan.job_ids())) == 2


def test_an_empty_manifest_is_refused(world):
    with pytest.raises(PlanningError, match="no pairs"):
        plan_from(world, pairs=[])


# ------------------------------------------------------- what changes a plan


def test_changing_one_pair_changes_the_plan(world):
    baseline = plan_from(world)
    altered = list(world.pairs)
    altered[0] = replace(altered[0], right_image_id=altered[1].right_image_id)
    assert (
        plan_from(world, pairs=altered).definition.plan_fingerprint
        != baseline.definition.plan_fingerprint
    )


def test_removing_a_pair_changes_the_plan(world):
    baseline = plan_from(world)
    assert (
        plan_from(world, pairs=world.pairs[:-1]).definition.plan_fingerprint
        != baseline.definition.plan_fingerprint
    )


def test_changing_the_run_changes_the_plan(world, tmp_path):
    baseline = plan_from(world)
    other_run = replace(world.run, run_fingerprint="d" * 64, run_id="run_ddddddddddd1")
    other = build_execution_plan(
        run=other_run,
        pairs=world.pairs,
        pair_manifest_metadata=world.pair_manifest_metadata,
    )
    assert other.definition.plan_fingerprint != baseline.definition.plan_fingerprint
    assert other.definition.run_id == other_run.run_id


def test_the_planner_hardcodes_no_job_count(world):
    """Nothing in the planner knows the protocol is 6,000 comparisons."""
    from pathlib import Path

    import fpbench.execution.planner as planner_module

    source = Path(planner_module.__file__).read_text(encoding="utf-8")
    assert "6000" not in source and "6_000" not in source
