"""Pinned identities, so that changing a fingerprint rule is a deliberate act.

Everything a run or plan fingerprint depends on is fixed by hand here — the
descriptor, the environment (which normally carries this machine's platform),
the execution profile and the pairs. That makes the expected digests
machine-independent, which is the only way this test can mean anything.

If one of these numbers changes, a formula changed. That may well be correct —
but it invalidates every result already on disk, since ``run_id`` and
``plan_id`` are derived from these digests, and it has to be acknowledged rather
than discovered later while wondering why a resumed run started from zero.
"""

from __future__ import annotations

import random

import pytest

from fpbench.core.enums import (
    EnvironmentStatus,
    GroundTruth,
    ProtocolStage,
    ScoreDirection,
)
from fpbench.core.execution_models import (
    AlgorithmDescriptor,
    EnvironmentReport,
    ExecutionProfile,
    descriptor_fingerprint,
    environment_fingerprint,
    execution_profile_fingerprint,
)
from fpbench.core.identifiers import CohortId, ImageId, PairId
from fpbench.core.models import ComparisonPair
from fpbench.execution.jobs import build_comparison_job
from fpbench.execution.planner import build_execution_plan
from fpbench.execution.run_definition import create_run_definition

PROTOCOL_ID = "sd300_50_subjects"
COHORT_ID = CohortId("sd300_50_subjects_test_ab12cd34")
PAIR_MANIFEST_HASH = "a1" * 32

DESCRIPTOR = AlgorithmDescriptor(
    algorithm_id="dummy_sha256",
    display_name="Deterministic SHA-256 Dummy Matcher",
    adapter_id="dummy_sha256",
    adapter_version="1",
    adapter_contract_version="1",
    implementation_version="dummy-sha256-v1",
    score_direction=ScoreDirection.HIGHER_IS_BETTER,
    deterministic=True,
    capabilities=(),
)

ENVIRONMENT = EnvironmentReport(
    status=EnvironmentStatus.READY,
    implementation_version="dummy-sha256-v1",
    runtime={"python": "3.12.0", "platform": "PinnedForTests"},
    dependencies={},
)

PROFILE = ExecutionProfile(
    profile_id="identity_png_v1",
    preparer_id="identity",
    timeout_seconds=10.0,
    deterministic_seed=0,
    parameters={},
)


def _pair(pair_id: str, left: str, right: str, stage: ProtocolStage) -> ComparisonPair:
    return ComparisonPair(
        pair_id=PairId(pair_id),
        dataset_id="sd300",
        release="SD300A",
        left_image_id=ImageId(left),
        right_image_id=ImageId(right),
        ground_truth=(
            GroundTruth.NON_MATED
            if stage is ProtocolStage.PLAIN_ROLL_NON_MATED
            else GroundTruth.MATED
        ),
        protocol_stage=stage,
    )


PAIRS = (
    _pair(
        "sd300a_00001000_f01_plain_self",
        "sd300a_00001000_plain_f01",
        "sd300a_00001000_plain_f01",
        ProtocolStage.PLAIN_SELF,
    ),
    _pair(
        "sd300a_00001000_f01_roll_self",
        "sd300a_00001000_roll_f01",
        "sd300a_00001000_roll_f01",
        ProtocolStage.ROLL_SELF,
    ),
    _pair(
        "sd300a_00001000_f01_mated",
        "sd300a_00001000_plain_f01",
        "sd300a_00001000_roll_f01",
        ProtocolStage.PLAIN_ROLL_MATED,
    ),
    _pair(
        "sd300a_00001000_f01_vs_f02_nonmated",
        "sd300a_00001000_plain_f01",
        "sd300a_00001000_roll_f02",
        ProtocolStage.PLAIN_ROLL_NON_MATED,
    ),
)

METADATA = {
    "protocol_id": PROTOCOL_ID,
    "cohort_id": str(COHORT_ID),
    "pair_manifest_hash": PAIR_MANIFEST_HASH,
}

# --- pinned values -----------------------------------------------------------
EXPECTED_DESCRIPTOR_FINGERPRINT = (
    "8d1de81b8353200485fc6c445221ee3afcb270460fe4427c13684ff8de69738a"
)
EXPECTED_ENVIRONMENT_FINGERPRINT = (
    "c99b1fde58c6671f6f109012a5c7ab0d6bdce87693f9bd7bb9084e770ad9204c"
)
EXPECTED_PROFILE_FINGERPRINT = (
    "f3507a6cbde6170790b7481aed7142bb44df48cec79b0158404d1dfc602b1470"
)
EXPECTED_JOB_MANIFEST_HASH = (
    "9bb9d7a0eed2350f97492ee0101012a6e9d56a7dbe6d8ec54e588b841a5b4483"
)
EXPECTED_PLAN_FINGERPRINT = (
    "72f1566fc92764dcc980ea4f1201a8ea3e9358f2c1a7d2888c69c8e7ce8a3a9b"
)
EXPECTED_RUN_ID = "run_9afea2f30132"
EXPECTED_PLAN_ID = "plan_72f1566fc927"


@pytest.fixture(scope="module")
def run():
    return create_run_definition(
        protocol_id=PROTOCOL_ID,
        cohort_id=COHORT_ID,
        pair_manifest_hash=PAIR_MANIFEST_HASH,
        algorithm=DESCRIPTOR,
        environment=ENVIRONMENT,
        execution_profile=PROFILE,
        created_utc="2020-01-01T00:00:00+00:00",
    )


@pytest.fixture(scope="module")
def plan(run):
    return build_execution_plan(
        run=run, pairs=PAIRS, pair_manifest_metadata=METADATA
    )


# ------------------------------------------------------------------- pinned


def test_descriptor_fingerprint_is_pinned():
    assert descriptor_fingerprint(DESCRIPTOR) == EXPECTED_DESCRIPTOR_FINGERPRINT


def test_environment_fingerprint_is_pinned():
    assert environment_fingerprint(ENVIRONMENT) == EXPECTED_ENVIRONMENT_FINGERPRINT


def test_execution_profile_fingerprint_is_pinned():
    assert execution_profile_fingerprint(PROFILE) == EXPECTED_PROFILE_FINGERPRINT


def test_run_id_is_pinned(run):
    assert run.run_id == EXPECTED_RUN_ID


def test_job_manifest_hash_is_pinned(plan):
    assert plan.definition.job_manifest_hash == EXPECTED_JOB_MANIFEST_HASH


def test_plan_fingerprint_is_pinned(plan):
    assert plan.definition.plan_fingerprint == EXPECTED_PLAN_FINGERPRINT
    assert plan.plan_id == EXPECTED_PLAN_ID


# -------------------------------------------------------------- independence


def test_the_plan_is_independent_of_input_order(run):
    baseline = build_execution_plan(
        run=run, pairs=PAIRS, pair_manifest_metadata=METADATA
    ).definition.plan_fingerprint
    for seed in range(10):
        shuffled = list(PAIRS)
        random.Random(seed).shuffle(shuffled)
        candidate = build_execution_plan(
            run=run, pairs=shuffled, pair_manifest_metadata=METADATA
        )
        assert candidate.definition.plan_fingerprint == baseline


#: (ordinal, job_id, pair_id) for the fixed pairs above, in canonical order.
EXPECTED_JOBS = (
    (0, "job_8b03aa766e048790", "sd300a_00001000_f01_plain_self"),
    (1, "job_108f211f07618a24", "sd300a_00001000_f01_roll_self"),
    (2, "job_47ee3749df46ea12", "sd300a_00001000_f01_mated"),
    (3, "job_2fc8ba39313c62d6", "sd300a_00001000_f01_vs_f02_nonmated"),
)


def test_the_planned_jobs_are_pinned(plan):
    """Job ids name result files; changing them orphans every stored result."""
    assert tuple(
        (item.ordinal, item.job.job_id, str(item.job.pair_id)) for item in plan.jobs
    ) == EXPECTED_JOBS


def test_job_identity_comes_only_from_build_comparison_job(run, plan):
    """The planner mints no ids of its own (spec 9.4)."""
    for item in plan.jobs:
        pair = next(p for p in PAIRS if str(p.pair_id) == str(item.job.pair_id))
        assert build_comparison_job(run, pair) == item.job


def test_the_plan_puts_self_stages_first(plan):
    """The canonical order is part of the identity, so pin the shape too."""
    by_pair = {str(pair.pair_id): pair for pair in PAIRS}
    stages = [by_pair[str(item.job.pair_id)].protocol_stage for item in plan.jobs]
    assert stages == [
        ProtocolStage.PLAIN_SELF,
        ProtocolStage.ROLL_SELF,
        ProtocolStage.PLAIN_ROLL_MATED,
        ProtocolStage.PLAIN_ROLL_NON_MATED,
    ]
