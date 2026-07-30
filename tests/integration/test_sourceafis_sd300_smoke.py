"""24 real SD300 comparisons through SourceAFIS.

A **compatibility smoke test**, not an experiment. It answers one question: can
SourceAFIS 3.18.1 actually process this delivery — every release, every resolution,
every protocol stage — without crashing, timing out, or rejecting a DPI?

Two fingers of one subject, four stages, three releases. The jobs are taken from the
real execution plan rather than assembled here, so what runs is exactly what the
protocol asked for.

**No biometric conclusion may be drawn from these 24 scores.** They are a handful of
comparisons from one subject, with no threshold applied and none available. The run is
left deliberately PARTIAL and no completion manifest is written, because a run that
covered 24 of 6,000 comparisons must not be able to look finished
(docs/adr/0012, docs/adr/0013).
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from fpbench.core.enums import (
    ExecutionStatus,
    FailureCode,
    FingerprintPosition,
    ProtocolStage,
    RunState,
)
from fpbench.core.execution_models import ExecutionProfile
from fpbench.datasets import create_provider, load_dataset_spec, summarise_subjects
from fpbench.execution.audit import validate_existing_results
from fpbench.execution.planner import build_execution_plan
from fpbench.execution.progress import inspect_run_progress
from fpbench.execution.run_definition import create_run_definition
from fpbench.execution.runner import JobDisposition, SingleJobRunner
from fpbench.imaging.identity import IdentityImagePreparer
from fpbench.protocols.sd300_protocol import SD300Protocol
from fpbench.storage.manifest_store import ManifestStore
from fpbench.storage.plan_store import PlanStore
from fpbench.storage.result_store import ResultStore
from sourceafis_support import require_bridge

pytestmark = [pytest.mark.dataset, pytest.mark.sourceafis]

REPO = Path(__file__).resolve().parents[2]
PROTOCOL_CONFIG = REPO / "configs" / "protocols" / "sd300_50_subjects.yaml"
DATASET_CONFIG = REPO / "configs" / "datasets" / "sd300.yaml"

#: The first two fingers in canonical order. Deterministic, and enough to cover both
#: thumb remapping (FRGP 11 -> finger 1) and an ordinary segmented finger.
SMOKE_POSITIONS = (FingerprintPosition.RIGHT_THUMB, FingerprintPosition.RIGHT_INDEX)

RELEASES = ("SD300A", "SD300B", "SD300C")
EXPECTED_PPI = {"SD300A": 500, "SD300B": 1000, "SD300C": 2000}
EXPECTED_JOBS = len(SMOKE_POSITIONS) * len(ProtocolStage) * len(RELEASES)  # 24


NATIVE_PROFILE = ExecutionProfile(
    profile_id="native_identity_60s_v1",
    preparer_id="identity",
    timeout_seconds=60.0,
    deterministic_seed=0,
    parameters={
        "resolution_mode": "native",
        "input_format": "png",
        "shared_resampling": "none",
    },
)


@pytest.fixture(scope="module")
def pilot(tmp_path_factory, sd300_root):
    """The real protocol, planned, with a 24-job slice selected from the plan."""
    adapter, report = require_bridge()

    workspace = tmp_path_factory.mktemp("sourceafis_smoke") / "workspace"
    spec = load_dataset_spec(DATASET_CONFIG, root_override=sd300_root)
    provider = create_provider(spec)
    protocol = SD300Protocol.from_config_file(PROTOCOL_CONFIG)
    manifests = ManifestStore(workspace)

    images, subjects, manifest_hashes = [], [], {}
    for release in protocol.releases:
        release_images = list(provider.scan(release))
        release_subjects = summarise_subjects(release_images)
        manifests.write_images(
            release_images, dataset_id=protocol.dataset_id, release=release
        )
        manifests.write_subjects(
            release_subjects, dataset_id=protocol.dataset_id, release=release
        )
        manifest_hashes[release] = manifests.image_manifest_hash(
            protocol.dataset_id, release
        )
        images += release_images
        subjects += release_subjects

    cohort = protocol.build_cohort(subjects, manifest_hashes)
    pairs = protocol.build_pairs(cohort, images)
    manifests.write_cohort(cohort)
    manifests.write_pairs(pairs, cohort=cohort)
    pair_metadata = manifests.pair_manifest_metadata(
        protocol.protocol_id, cohort.cohort_id
    )

    run = create_run_definition(
        protocol_id=protocol.protocol_id,
        cohort_id=cohort.cohort_id,
        pair_manifest_hash=pair_metadata["pair_manifest_hash"],
        algorithm=adapter.descriptor,
        environment=report,
        execution_profile=NATIVE_PROFILE,
    )
    plan = build_execution_plan(
        run=run, pairs=pairs, pair_manifest_metadata=pair_metadata
    )
    PlanStore(workspace).ensure_plan(plan)

    # The first cohort subject, in the cohort's own order. Nothing is sampled.
    subject_id = cohort.subject_ids[0]
    by_image = {image.image_id: image for image in images}
    by_pair = {pair.pair_id: pair for pair in pairs}

    selected = [
        planned
        for planned in plan.jobs
        if _matches(by_pair[planned.job.pair_id], by_image, subject_id)
    ]

    return {
        "adapter": adapter,
        "environment": report,
        "workspace": workspace,
        "dataset_root": spec.root,
        "images": by_image,
        "pairs": by_pair,
        "run": run,
        "plan": plan,
        "subject_id": subject_id,
        "selected": selected,
    }


def _matches(pair, by_image, subject_id: str) -> bool:
    """Whether a pair belongs to the chosen subject and one of the chosen fingers.

    Decided from the *left* image's record rather than by reading the pair id. In
    all four stages the left side is the pair's own finger, and matching on the id
    would over-select: an impostor pair named ``..._f10_vs_f01_nonmated`` contains
    ``_f01_`` without being a finger-1 comparison.
    """
    left = by_image[pair.left_image_id]
    return left.subject_id == subject_id and left.position in SMOKE_POSITIONS


@pytest.fixture(scope="module")
def executed(pilot):
    """Run the 24 jobs once, through the ordinary single-job runner."""
    runner = SingleJobRunner(
        run=pilot["run"],
        adapter=pilot["adapter"],
        preparer=IdentityImagePreparer(),
        result_store=ResultStore(pilot["workspace"]),
        dataset_root=pilot["dataset_root"],
        image_index=pilot["images"],
        workspace_root=pilot["workspace"],
    )
    outcomes = [
        runner.execute(planned.job, pilot["pairs"][planned.job.pair_id])
        for planned in pilot["selected"]
    ]
    return outcomes


# ------------------------------------------------------------------- selection


def test_the_slice_is_exactly_twenty_four_jobs(pilot):
    assert len(pilot["selected"]) == EXPECTED_JOBS


def test_the_slice_covers_every_release_and_every_stage(pilot):
    pairs = [pilot["pairs"][planned.job.pair_id] for planned in pilot["selected"]]
    assert Counter(pair.release for pair in pairs) == {
        release: len(SMOKE_POSITIONS) * len(ProtocolStage) for release in RELEASES
    }
    assert Counter(pair.protocol_stage for pair in pairs) == {
        stage: len(SMOKE_POSITIONS) * len(RELEASES) for stage in ProtocolStage
    }


def test_the_slice_comes_from_the_real_plan(pilot):
    planned_ids = set(pilot["plan"].job_ids())
    assert {planned.job.job_id for planned in pilot["selected"]} <= planned_ids


# -------------------------------------------------------------------- results


def test_every_comparison_produced_a_raw_score(executed, pilot):
    """A compatibility smoke test: all 24 must score, or the stage does not close."""
    failures = [
        (outcome.result.pair_id, outcome.result.failure.code.value)
        for outcome in executed
        if outcome.result.status is not ExecutionStatus.SUCCESS
    ]
    assert failures == [], f"SourceAFIS failed on {len(failures)} of {EXPECTED_JOBS}: {failures}"
    assert len(executed) == EXPECTED_JOBS


def test_no_comparison_crashed_timed_out_or_violated_the_contract(executed):
    forbidden = {
        FailureCode.PROCESS_CRASHED,
        FailureCode.TIMEOUT,
        FailureCode.INTERNAL_ERROR,
        FailureCode.UNSUPPORTED_RESOLUTION,
    }
    seen = {
        outcome.result.failure.code
        for outcome in executed
        if outcome.result.failure is not None
    }
    assert seen & forbidden == set()


def test_every_score_is_finite_and_non_negative(executed):
    import math

    for outcome in executed:
        score = outcome.result.raw_score
        assert score is not None and math.isfinite(score) and score >= 0


def test_each_release_was_compared_at_its_own_resolution(executed, pilot):
    """SD300C is used at 2000 ppi even though its PNG headers claim 5080."""
    for outcome in executed:
        pair = pilot["pairs"][outcome.result.pair_id]
        expected = str(EXPECTED_PPI[pair.release])
        assert outcome.result.adapter_metadata["left_dpi"] == expected
        assert outcome.result.adapter_metadata["right_dpi"] == expected


def test_both_sides_were_extracted_independently(executed):
    for outcome in executed:
        assert outcome.result.adapter_metadata["extraction_count"] == "2"
        assert (
            outcome.result.adapter_metadata["extraction_policy"]
            == "independent_both_sides"
        )


def test_no_result_carries_a_template_artifact(executed):
    for outcome in executed:
        assert outcome.result.artifacts == ()


def test_no_result_carries_a_threshold_or_decision(executed):
    forbidden = {"threshold", "decision", "is_match", "ground_truth", "protocol_stage"}
    for outcome in executed:
        assert forbidden.isdisjoint(outcome.result.adapter_metadata)


def test_no_result_stores_an_absolute_path(executed, pilot):
    for outcome in executed:
        rendered = repr(outcome.result)
        assert str(pilot["dataset_root"]) not in rendered
        assert str(pilot["workspace"]) not in rendered


def test_every_result_names_the_sourceafis_pipeline(executed):
    for outcome in executed:
        assert outcome.result.algorithm_id == "sourceafis_java"
        assert outcome.result.adapter_metadata["sourceafis_version"] == "3.18.1"


def test_re_running_the_slice_starts_no_jvm(pilot, executed):
    runner = SingleJobRunner(
        run=pilot["run"],
        adapter=_refusing_adapter(pilot["adapter"]),
        preparer=IdentityImagePreparer(),
        result_store=ResultStore(pilot["workspace"]),
        dataset_root=pilot["dataset_root"],
        image_index=pilot["images"],
        workspace_root=pilot["workspace"],
    )
    for planned in pilot["selected"]:
        outcome = runner.execute(planned.job, pilot["pairs"][planned.job.pair_id])
        assert outcome.disposition is JobDisposition.SKIPPED_EXISTING


def _refusing_adapter(delegate):
    """Wraps the real adapter and fails loudly if a comparison is attempted."""

    class Refusing:
        @property
        def descriptor(self):
            return delegate.descriptor

        def validate_environment(self):
            return delegate.validate_environment()

        def compare(self, left, right, context):  # pragma: no cover - must not run
            raise AssertionError("resume must not invoke the adapter")

    return Refusing()


# ---------------------------------------------------------------- run state


def test_the_existing_results_validate_cleanly(pilot, executed):
    report = validate_existing_results(
        run=pilot["run"],
        plan=pilot["plan"],
        result_store=ResultStore(pilot["workspace"]),
    )
    assert report.is_clean
    assert report.valid_results == EXPECTED_JOBS


def test_the_run_stays_partial_and_unverified(pilot, executed):
    """24 of 6,000 comparisons must never be able to look like a finished run."""
    store = ResultStore(pilot["workspace"])
    progress = inspect_run_progress(
        run=pilot["run"], plan=pilot["plan"], result_store=store
    )
    assert progress.state is RunState.PARTIAL
    assert progress.stored_results == EXPECTED_JOBS
    assert progress.missing_results == pilot["plan"].total_jobs - EXPECTED_JOBS
    assert not progress.completion_manifest_present
    assert not store.has_completion(pilot["run"].run_id)
