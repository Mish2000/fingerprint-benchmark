"""The runner, end to end, against real files and a real store.

Everything here exercises the whole path — preparer, adapter, store — because
the interesting failures live in the seams: a SELF pair prepared once instead
of twice, a resumed job that re-runs the matcher, a crashing adapter that takes
the run down with it.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from fpbench.adapters.dummy.adapter import DummyShaAdapter, score_for
from fpbench.core.enums import (
    ChecksumStatus,
    ExecutionStatus,
    FailureCode,
    FailureStage,
    GroundTruth,
    Impression,
    ProtocolStage,
)
from fpbench.core.errors import ExecutionError, PreflightError, ResultConflictError
from fpbench.core.identifiers import CohortId, ImageId
from fpbench.execution.jobs import build_comparison_job
from fpbench.execution.run_definition import (
    DEFAULT_EXECUTION_PROFILE,
    create_run_definition,
)
from fpbench.execution.runner import JobDisposition, SingleJobRunner
from fpbench.imaging.identity import IdentityImagePreparer
from fpbench.storage.result_store import ResultStore
from fakes import (
    FIXED_SCORE,
    CountingAdapter,
    CountingPreparer,
    ExplodingAdapter,
    FailingAdapter,
    NaNAdapter,
    TimingOutAdapter,
    UnavailableAdapter,
    WrongDirectionAdapter,
    comparison_pair,
    image_record,
    sha256_of,
)
from support import make_png

PROTOCOL_ID = "sd300_50_subjects"
COHORT = CohortId("sd300_50_subjects_test_ab12cd34")
PAIR_MANIFEST_HASH = "e" * 64

PLAIN_RELATIVE = "sd300a/images/500/png/plain/00001000_plain_500_11.png"
ROLL_RELATIVE = "sd300a/images/500/png/roll/00001000_roll_500_01.png"
PLAIN_ID = "sd300a_00001000_plain_f01"
ROLL_ID = "sd300a_00001000_roll_f01"


# ------------------------------------------------------------------- fixtures


@pytest.fixture
def dataset_root(tmp_path: Path) -> Path:
    root = tmp_path / "nist"
    for relative in (PLAIN_RELATIVE, ROLL_RELATIVE):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(make_png())
    return root


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path / "workspace"


@pytest.fixture
def image_index() -> dict[ImageId, object]:
    return {
        ImageId(PLAIN_ID): image_record(
            image_id=PLAIN_ID,
            relative_path=PLAIN_RELATIVE,
            expected_sha256=sha256_of(make_png()),
            impression=Impression.PLAIN,
        ),
        ImageId(ROLL_ID): image_record(
            image_id=ROLL_ID,
            relative_path=ROLL_RELATIVE,
            expected_sha256=sha256_of(make_png()),
            impression=Impression.ROLL,
        ),
    }


MATED_PAIR = comparison_pair(
    pair_id="sd300a_00001000_f01_mated",
    left_image_id=PLAIN_ID,
    right_image_id=ROLL_ID,
)

SELF_PAIR = comparison_pair(
    pair_id="sd300a_00001000_f01_plain_self",
    left_image_id=PLAIN_ID,
    right_image_id=PLAIN_ID,
    stage=ProtocolStage.PLAIN_SELF,
    ground_truth=GroundTruth.MATED,
)


def make_run(adapter):
    return create_run_definition(
        protocol_id=PROTOCOL_ID,
        cohort_id=COHORT,
        pair_manifest_hash=PAIR_MANIFEST_HASH,
        algorithm=adapter.descriptor,
        environment=adapter.validate_environment(),
        execution_profile=DEFAULT_EXECUTION_PROFILE,
    )


def make_runner(adapter, dataset_root, workspace, image_index, *, preparer=None):
    run = make_run(adapter)
    runner = SingleJobRunner(
        run=run,
        adapter=adapter,
        preparer=preparer or IdentityImagePreparer(),
        result_store=ResultStore(workspace),
        dataset_root=dataset_root,
        image_index=image_index,
        workspace_root=workspace,
    )
    return run, runner


# ------------------------------------------------------------------- preflight


def test_preflight_writes_the_run_manifest(dataset_root, workspace, image_index):
    run, _ = make_runner(DummyShaAdapter(), dataset_root, workspace, image_index)
    assert ResultStore(workspace).read_run(run.run_id) == run


def test_preflight_rejects_an_unavailable_environment(
    dataset_root, workspace, image_index
):
    adapter = UnavailableAdapter()
    run = create_run_definition(
        protocol_id=PROTOCOL_ID,
        cohort_id=COHORT,
        pair_manifest_hash=PAIR_MANIFEST_HASH,
        algorithm=adapter.descriptor,
        environment=adapter.validate_environment(),
        execution_profile=DEFAULT_EXECUTION_PROFILE,
    )
    with pytest.raises(PreflightError, match="unavailable"):
        SingleJobRunner(
            run=run,
            adapter=adapter,
            preparer=IdentityImagePreparer(),
            result_store=ResultStore(workspace),
            dataset_root=dataset_root,
            image_index=image_index,
            workspace_root=workspace,
        )


def test_preflight_rejects_an_adapter_the_run_was_not_defined_for(
    dataset_root, workspace, image_index
):
    run = make_run(DummyShaAdapter())
    with pytest.raises(PreflightError, match="adapter describes"):
        SingleJobRunner(
            run=run,
            adapter=CountingAdapter(),
            preparer=IdentityImagePreparer(),
            result_store=ResultStore(workspace),
            dataset_root=dataset_root,
            image_index=image_index,
            workspace_root=workspace,
        )


def test_preflight_rejects_the_wrong_preparer(dataset_root, workspace, image_index):
    adapter = DummyShaAdapter()
    run = make_run(adapter)
    other_profile = replace(DEFAULT_EXECUTION_PROFILE, preparer_id="downsample_500")
    run = replace(run, execution_profile=other_profile)
    with pytest.raises(PreflightError, match="requires preparer"):
        SingleJobRunner(
            run=run,
            adapter=adapter,
            preparer=IdentityImagePreparer(),
            result_store=ResultStore(workspace),
            dataset_root=dataset_root,
            image_index=image_index,
            workspace_root=workspace,
        )


def test_a_failed_preflight_stores_no_result(dataset_root, workspace, image_index):
    adapter = UnavailableAdapter()
    run = create_run_definition(
        protocol_id=PROTOCOL_ID,
        cohort_id=COHORT,
        pair_manifest_hash=PAIR_MANIFEST_HASH,
        algorithm=adapter.descriptor,
        environment=adapter.validate_environment(),
        execution_profile=DEFAULT_EXECUTION_PROFILE,
    )
    with pytest.raises(PreflightError):
        SingleJobRunner(
            run=run,
            adapter=adapter,
            preparer=IdentityImagePreparer(),
            result_store=ResultStore(workspace),
            dataset_root=dataset_root,
            image_index=image_index,
            workspace_root=workspace,
        )
    assert list(ResultStore(workspace).iter_raw_results(run.run_id)) == []


# --------------------------------------------------------------------- success


def test_a_successful_job_is_executed_and_stored(dataset_root, workspace, image_index):
    adapter = DummyShaAdapter()
    run, runner = make_runner(adapter, dataset_root, workspace, image_index)
    job = build_comparison_job(run, MATED_PAIR)

    outcome = runner.execute(job, MATED_PAIR)

    assert outcome.disposition is JobDisposition.EXECUTED
    assert outcome.result.status is ExecutionStatus.SUCCESS
    assert outcome.result.raw_score == score_for(
        image_index[ImageId(PLAIN_ID)].expected_sha256,
        image_index[ImageId(ROLL_ID)].expected_sha256,
        DEFAULT_EXECUTION_PROFILE.deterministic_seed,
    )
    assert ResultStore(workspace).read_raw_result(run.run_id, job.job_id) == outcome.result


def test_the_stored_result_carries_its_full_provenance(
    dataset_root, workspace, image_index
):
    adapter = DummyShaAdapter()
    run, runner = make_runner(adapter, dataset_root, workspace, image_index)
    job = build_comparison_job(run, MATED_PAIR)

    record = runner.execute(job, MATED_PAIR).result

    assert record.run_id == run.run_id
    assert record.job_id == job.job_id
    assert record.result_id == job.job_id
    assert record.job_fingerprint == job.job_fingerprint
    assert record.protocol_id == PROTOCOL_ID
    assert record.cohort_id == COHORT
    assert record.pair_manifest_hash == PAIR_MANIFEST_HASH
    assert record.pair_id == MATED_PAIR.pair_id
    assert record.algorithm_fingerprint == run.algorithm_fingerprint
    assert record.execution_profile_hash == run.execution_profile_hash
    assert record.attempt == 1


def test_the_stored_result_holds_no_decision(dataset_root, workspace, image_index):
    run, runner = make_runner(DummyShaAdapter(), dataset_root, workspace, image_index)
    record = runner.execute(build_comparison_job(run, MATED_PAIR), MATED_PAIR).result
    plain = {f.name for f in record.__dataclass_fields__.values()}
    assert {"threshold", "decision", "ground_truth", "protocol_stage"} & plain == set()


def test_timings_are_recorded_and_coherent(dataset_root, workspace, image_index):
    run, runner = make_runner(DummyShaAdapter(), dataset_root, workspace, image_index)
    timings = runner.execute(build_comparison_job(run, MATED_PAIR), MATED_PAIR).result.timings
    assert timings.preparation_ms >= 0
    assert timings.adapter_ms >= 0
    assert timings.total_ms + 1.0 >= timings.preparation_ms + timings.adapter_ms


def test_no_absolute_path_reaches_the_stored_result(
    dataset_root, workspace, image_index
):
    run, runner = make_runner(DummyShaAdapter(), dataset_root, workspace, image_index)
    record = runner.execute(build_comparison_job(run, MATED_PAIR), MATED_PAIR).result
    serialised = repr(record)
    assert str(dataset_root) not in serialised
    assert str(workspace) not in serialised


# ------------------------------------------------------------------------ SELF


def test_a_self_pair_is_prepared_twice_and_compared_once(
    dataset_root, workspace, image_index
):
    """The second prepare() looks redundant; skipping it is how SELF diverges."""
    preparer = CountingPreparer()
    adapter = DummyShaAdapter()
    run, runner = make_runner(
        adapter, dataset_root, workspace, image_index, preparer=preparer
    )
    job = build_comparison_job(run, SELF_PAIR)

    outcome = runner.execute(job, SELF_PAIR)

    assert preparer.calls == 2
    assert outcome.result.status is ExecutionStatus.SUCCESS
    assert outcome.result.left_image_id == outcome.result.right_image_id


def test_a_self_comparison_uses_the_ordered_pair_formula(
    dataset_root, workspace, image_index
):
    adapter = DummyShaAdapter()
    run, runner = make_runner(adapter, dataset_root, workspace, image_index)
    digest = image_index[ImageId(PLAIN_ID)].expected_sha256
    record = runner.execute(build_comparison_job(run, SELF_PAIR), SELF_PAIR).result
    assert record.raw_score == score_for(digest, digest, 0)


# ---------------------------------------------------------------------- resume


def test_re_running_a_job_skips_it_entirely(dataset_root, workspace, image_index):
    preparer = CountingPreparer()
    adapter = CountingAdapter()
    run = create_run_definition(
        protocol_id=PROTOCOL_ID,
        cohort_id=COHORT,
        pair_manifest_hash=PAIR_MANIFEST_HASH,
        algorithm=adapter.descriptor,
        environment=adapter.validate_environment(),
        execution_profile=DEFAULT_EXECUTION_PROFILE,
    )
    runner = SingleJobRunner(
        run=run,
        adapter=adapter,
        preparer=preparer,
        result_store=ResultStore(workspace),
        dataset_root=dataset_root,
        image_index=image_index,
        workspace_root=workspace,
    )
    job = build_comparison_job(run, MATED_PAIR)

    first = runner.execute(job, MATED_PAIR)
    calls_after_first = (preparer.calls, adapter.compare_calls)
    second = runner.execute(job, MATED_PAIR)

    assert first.disposition is JobDisposition.EXECUTED
    assert second.disposition is JobDisposition.SKIPPED_EXISTING
    assert (preparer.calls, adapter.compare_calls) == calls_after_first
    assert second.result == first.result


def test_a_resumed_run_reuses_the_same_directory(dataset_root, workspace, image_index):
    """A second runner over the same inputs must land on the same run_id."""
    adapter = DummyShaAdapter()
    run_a, runner_a = make_runner(adapter, dataset_root, workspace, image_index)
    job = build_comparison_job(run_a, MATED_PAIR)
    runner_a.execute(job, MATED_PAIR)

    run_b, runner_b = make_runner(
        DummyShaAdapter(), dataset_root, workspace, image_index
    )
    assert run_b.run_id == run_a.run_id
    assert runner_b.execute(job, MATED_PAIR).disposition is JobDisposition.SKIPPED_EXISTING


def test_a_stored_result_is_never_overwritten(dataset_root, workspace, image_index):
    adapter = DummyShaAdapter()
    run, runner = make_runner(adapter, dataset_root, workspace, image_index)
    job = build_comparison_job(run, MATED_PAIR)
    runner.execute(job, MATED_PAIR)

    impostor = replace(job, job_fingerprint="f" * 64)
    with pytest.raises(ResultConflictError):
        runner.execute(impostor, MATED_PAIR)


# ---------------------------------------------------------------- consistency


def test_a_job_from_another_run_is_refused(dataset_root, workspace, image_index):
    run, runner = make_runner(DummyShaAdapter(), dataset_root, workspace, image_index)
    stray = replace(build_comparison_job(run, MATED_PAIR), run_id="run_000000000000")
    with pytest.raises(ExecutionError, match="belongs to run"):
        runner.execute(stray, MATED_PAIR)


def test_a_job_and_pair_that_disagree_are_refused(
    dataset_root, workspace, image_index
):
    run, runner = make_runner(DummyShaAdapter(), dataset_root, workspace, image_index)
    job = build_comparison_job(run, MATED_PAIR)
    with pytest.raises(ExecutionError, match="covers pair"):
        runner.execute(job, SELF_PAIR)


def test_a_job_whose_images_do_not_match_the_pair_is_refused(
    dataset_root, workspace, image_index
):
    run, runner = make_runner(DummyShaAdapter(), dataset_root, workspace, image_index)
    job = replace(build_comparison_job(run, MATED_PAIR), right_image_id=ImageId(PLAIN_ID))
    with pytest.raises(ExecutionError, match="does not match the images"):
        runner.execute(job, MATED_PAIR)


# ------------------------------------------------------------------- failures


def test_a_missing_image_record_is_recorded_as_invalid_input(
    dataset_root, workspace, image_index
):
    adapter = CountingAdapter()
    run = create_run_definition(
        protocol_id=PROTOCOL_ID,
        cohort_id=COHORT,
        pair_manifest_hash=PAIR_MANIFEST_HASH,
        algorithm=adapter.descriptor,
        environment=adapter.validate_environment(),
        execution_profile=DEFAULT_EXECUTION_PROFILE,
    )
    runner = SingleJobRunner(
        run=run,
        adapter=adapter,
        preparer=IdentityImagePreparer(),
        result_store=ResultStore(workspace),
        dataset_root=dataset_root,
        image_index={},
        workspace_root=workspace,
    )
    record = runner.execute(build_comparison_job(run, MATED_PAIR), MATED_PAIR).result

    assert record.status is ExecutionStatus.FAILURE
    assert record.failure.code is FailureCode.INPUT_INVALID
    assert record.failure.stage is FailureStage.INPUT
    assert adapter.compare_calls == 0


def test_a_blocked_image_is_recorded_with_its_reason(
    dataset_root, workspace, image_index
):
    blocked = dict(image_index)
    blocked[ImageId(PLAIN_ID)] = replace(
        blocked[ImageId(PLAIN_ID)], blocking_issues=("filename_ppi_mismatch",)
    )
    run, runner = make_runner(DummyShaAdapter(), dataset_root, workspace, blocked)
    record = runner.execute(build_comparison_job(run, MATED_PAIR), MATED_PAIR).result

    assert record.failure.code is FailureCode.INPUT_INVALID
    assert record.failure.details["reason"] == "blocked_image"


def test_a_checksum_mismatch_blocks_the_comparison(
    dataset_root, workspace, image_index
):
    tampered = dict(image_index)
    tampered[ImageId(ROLL_ID)] = replace(
        tampered[ImageId(ROLL_ID)], checksum_status=ChecksumStatus.MISMATCH
    )
    run, runner = make_runner(DummyShaAdapter(), dataset_root, workspace, tampered)
    record = runner.execute(build_comparison_job(run, MATED_PAIR), MATED_PAIR).result
    assert record.status is ExecutionStatus.FAILURE
    assert record.failure.code is FailureCode.INPUT_INVALID


def test_a_missing_file_is_recorded_as_a_preparation_failure(
    dataset_root, workspace, image_index
):
    adapter = CountingAdapter()
    missing = dict(image_index)
    missing[ImageId(PLAIN_ID)] = replace(
        missing[ImageId(PLAIN_ID)],
        relative_path="sd300a/images/500/png/plain/absent.png",
    )
    run = create_run_definition(
        protocol_id=PROTOCOL_ID,
        cohort_id=COHORT,
        pair_manifest_hash=PAIR_MANIFEST_HASH,
        algorithm=adapter.descriptor,
        environment=adapter.validate_environment(),
        execution_profile=DEFAULT_EXECUTION_PROFILE,
    )
    runner = SingleJobRunner(
        run=run,
        adapter=adapter,
        preparer=IdentityImagePreparer(),
        result_store=ResultStore(workspace),
        dataset_root=dataset_root,
        image_index=missing,
        workspace_root=workspace,
    )
    record = runner.execute(build_comparison_job(run, MATED_PAIR), MATED_PAIR).result

    assert record.failure.code is FailureCode.PREPARATION_FAILED
    assert record.failure.stage is FailureStage.PREPARATION
    assert adapter.compare_calls == 0


def test_an_adapter_reported_failure_is_stored_verbatim(
    dataset_root, workspace, image_index
):
    adapter = FailingAdapter()
    run = create_run_definition(
        protocol_id=PROTOCOL_ID,
        cohort_id=COHORT,
        pair_manifest_hash=PAIR_MANIFEST_HASH,
        algorithm=adapter.descriptor,
        environment=adapter.validate_environment(),
        execution_profile=DEFAULT_EXECUTION_PROFILE,
    )
    runner = SingleJobRunner(
        run=run,
        adapter=adapter,
        preparer=IdentityImagePreparer(),
        result_store=ResultStore(workspace),
        dataset_root=dataset_root,
        image_index=image_index,
        workspace_root=workspace,
    )
    record = runner.execute(build_comparison_job(run, MATED_PAIR), MATED_PAIR).result

    assert record.failure.code is FailureCode.TEMPLATE_EXTRACTION_FAILED
    assert record.failure.stage is FailureStage.EXTRACTION
    assert record.failure.message == "no minutiae found"
    assert record.failure.details == {"minutiae": "0"}
    assert record.raw_score is None


@pytest.mark.parametrize(
    "adapter_type,code,stage,retryable,detail_key",
    [
        (
            ExplodingAdapter,
            FailureCode.INTERNAL_ERROR,
            FailureStage.ADAPTER,
            False,
            "exception_type",
        ),
        (
            TimingOutAdapter,
            FailureCode.TIMEOUT,
            FailureStage.TIMEOUT,
            True,
            None,
        ),
        (
            NaNAdapter,
            FailureCode.INTERNAL_ERROR,
            FailureStage.ADAPTER,
            False,
            "kind",
        ),
        (
            WrongDirectionAdapter,
            FailureCode.INTERNAL_ERROR,
            FailureStage.ADAPTER,
            False,
            "kind",
        ),
    ],
)
def test_a_misbehaving_adapter_becomes_a_recorded_failure(
    dataset_root, workspace, image_index, adapter_type, code, stage, retryable, detail_key
):
    adapter = adapter_type()
    run = create_run_definition(
        protocol_id=PROTOCOL_ID,
        cohort_id=COHORT,
        pair_manifest_hash=PAIR_MANIFEST_HASH,
        algorithm=adapter.descriptor,
        environment=adapter.validate_environment(),
        execution_profile=DEFAULT_EXECUTION_PROFILE,
    )
    runner = SingleJobRunner(
        run=run,
        adapter=adapter,
        preparer=IdentityImagePreparer(),
        result_store=ResultStore(workspace),
        dataset_root=dataset_root,
        image_index=image_index,
        workspace_root=workspace,
    )
    job = build_comparison_job(run, MATED_PAIR)

    record = runner.execute(job, MATED_PAIR).result

    assert record.status is ExecutionStatus.FAILURE
    assert record.failure.code is code
    assert record.failure.stage is stage
    assert record.failure.retryable is retryable
    if detail_key:
        assert detail_key in record.failure.details
    # The failure is on disk, not merely returned.
    assert ResultStore(workspace).read_raw_result(run.run_id, job.job_id) == record


@pytest.mark.parametrize("adapter_type", [NaNAdapter, WrongDirectionAdapter])
def test_a_contract_violation_is_labelled_as_one(
    dataset_root, workspace, image_index, adapter_type
):
    adapter = adapter_type()
    run = create_run_definition(
        protocol_id=PROTOCOL_ID,
        cohort_id=COHORT,
        pair_manifest_hash=PAIR_MANIFEST_HASH,
        algorithm=adapter.descriptor,
        environment=adapter.validate_environment(),
        execution_profile=DEFAULT_EXECUTION_PROFILE,
    )
    runner = SingleJobRunner(
        run=run,
        adapter=adapter,
        preparer=IdentityImagePreparer(),
        result_store=ResultStore(workspace),
        dataset_root=dataset_root,
        image_index=image_index,
        workspace_root=workspace,
    )
    record = runner.execute(build_comparison_job(run, MATED_PAIR), MATED_PAIR).result
    assert record.failure.details["kind"] == "adapter_contract_violation"


def test_one_bad_comparison_does_not_end_the_run(
    dataset_root, workspace, image_index
):
    """The whole reason failures are recorded rather than raised."""
    adapter = ExplodingAdapter()
    run = create_run_definition(
        protocol_id=PROTOCOL_ID,
        cohort_id=COHORT,
        pair_manifest_hash=PAIR_MANIFEST_HASH,
        algorithm=adapter.descriptor,
        environment=adapter.validate_environment(),
        execution_profile=DEFAULT_EXECUTION_PROFILE,
    )
    runner = SingleJobRunner(
        run=run,
        adapter=adapter,
        preparer=IdentityImagePreparer(),
        result_store=ResultStore(workspace),
        dataset_root=dataset_root,
        image_index=image_index,
        workspace_root=workspace,
    )
    for pair in (MATED_PAIR, SELF_PAIR):
        outcome = runner.execute(build_comparison_job(run, pair), pair)
        assert outcome.result.status is ExecutionStatus.FAILURE
    assert len(list(ResultStore(workspace).iter_raw_results(run.run_id))) == 2


def test_a_failure_message_carries_no_traceback(dataset_root, workspace, image_index):
    adapter = ExplodingAdapter()
    run = create_run_definition(
        protocol_id=PROTOCOL_ID,
        cohort_id=COHORT,
        pair_manifest_hash=PAIR_MANIFEST_HASH,
        algorithm=adapter.descriptor,
        environment=adapter.validate_environment(),
        execution_profile=DEFAULT_EXECUTION_PROFILE,
    )
    runner = SingleJobRunner(
        run=run,
        adapter=adapter,
        preparer=IdentityImagePreparer(),
        result_store=ResultStore(workspace),
        dataset_root=dataset_root,
        image_index=image_index,
        workspace_root=workspace,
    )
    message = runner.execute(
        build_comparison_job(run, MATED_PAIR), MATED_PAIR
    ).result.failure.message
    assert "Traceback" not in message
    assert "File \"" not in message
    assert "RuntimeError" in message


# ------------------------------------------------------- information isolation


def test_the_adapter_is_told_nothing_about_the_pair(
    dataset_root, workspace, image_index
):
    """docs/adr/0010, verified against a real execution rather than by reading."""
    adapter = CountingAdapter()
    run = create_run_definition(
        protocol_id=PROTOCOL_ID,
        cohort_id=COHORT,
        pair_manifest_hash=PAIR_MANIFEST_HASH,
        algorithm=adapter.descriptor,
        environment=adapter.validate_environment(),
        execution_profile=DEFAULT_EXECUTION_PROFILE,
    )
    runner = SingleJobRunner(
        run=run,
        adapter=adapter,
        preparer=IdentityImagePreparer(),
        result_store=ResultStore(workspace),
        dataset_root=dataset_root,
        image_index=image_index,
        workspace_root=workspace,
    )
    job = build_comparison_job(run, MATED_PAIR)
    runner.execute(job, MATED_PAIR)

    [context] = adapter.contexts
    fields = set(type(context).__dataclass_fields__)
    assert {"pair_id", "protocol_stage", "ground_truth", "threshold"} & fields == set()

    for leak in (MATED_PAIR.pair_id, "mated", "plain_roll"):
        assert leak not in context.job_id

    [(left, right)] = adapter.prepared
    for prepared_image in (left, right):
        prepared_fields = set(type(prepared_image).__dataclass_fields__)
        assert {"subject_id", "position", "impression"} & prepared_fields == set()

    assert adapter.compare_calls == 1
    assert runner.execute(job, MATED_PAIR).result.raw_score == FIXED_SCORE


def test_the_adapter_directories_exist_and_sit_under_the_workspace(
    dataset_root, workspace, image_index
):
    adapter = CountingAdapter()
    run = create_run_definition(
        protocol_id=PROTOCOL_ID,
        cohort_id=COHORT,
        pair_manifest_hash=PAIR_MANIFEST_HASH,
        algorithm=adapter.descriptor,
        environment=adapter.validate_environment(),
        execution_profile=DEFAULT_EXECUTION_PROFILE,
    )
    runner = SingleJobRunner(
        run=run,
        adapter=adapter,
        preparer=IdentityImagePreparer(),
        result_store=ResultStore(workspace),
        dataset_root=dataset_root,
        image_index=image_index,
        workspace_root=workspace,
    )
    runner.execute(build_comparison_job(run, MATED_PAIR), MATED_PAIR)

    [context] = adapter.contexts
    assert context.working_directory.is_dir()
    assert context.artifact_directory.is_dir()
    assert context.working_directory.is_relative_to(workspace.resolve())
    assert context.artifact_directory.is_relative_to(workspace.resolve())
