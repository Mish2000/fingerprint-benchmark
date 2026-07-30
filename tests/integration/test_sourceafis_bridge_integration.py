"""Python adapter → real JVM → real SourceAFIS 3.18.1 → score.

Nothing is stubbed here. These are the tests that would notice if the bridge, the
jar, the JVM or the wire format stopped agreeing with each other.

No threshold assertions anywhere. The fixtures are procedural textures, not fingers,
so "the SELF score should be high" would be a claim about the generator rather than
about SourceAFIS (see tests/fixtures/sourceafis/README.md).
"""

from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path

import pytest

from fpbench.core.enums import ExecutionStatus, FailureCode, FailureStage, ScoreDirection
from fpbench.execution.jobs import build_comparison_job
from fpbench.execution.run_definition import create_run_definition
from fpbench.execution.runner import JobDisposition, SingleJobRunner
from fpbench.imaging.identity import IdentityImagePreparer
from fpbench.storage.result_store import ResultStore
from fakes import comparison_pair, image_record, sha256_of
from sourceafis_support import comparison_context, prepared_image, require_bridge
from synthetic_ridges import whorl_png, corrupt_png, write_fixture

pytestmark = pytest.mark.sourceafis


@pytest.fixture(scope="module")
def bridge():
    """One READY adapter for the whole module; a JVM check per test would be waste."""
    adapter, report = require_bridge()
    return adapter, report


@pytest.fixture
def images(tmp_path) -> dict[str, Path]:
    return {
        "a": write_fixture(tmp_path, "a.png", whorl_png(500, 1)),
        "b": write_fixture(tmp_path, "b.png", whorl_png(500, 6)),
        "corrupt": write_fixture(tmp_path, "corrupt.png", corrupt_png()),
    }


# ------------------------------------------------------------------ environment


def test_the_environment_reports_the_real_versions(bridge):
    _, report = bridge
    assert report.dependencies["sourceafis"] == "3.18.1"
    assert report.dependencies["bridge.protocol"] == "fpbench.sourceafis.bridge.v1"
    assert report.dependencies["bridge.version"] == "1"
    assert len(report.dependencies["bridge.jar.sha256"]) == 64
    assert int(report.dependencies["bridge.jar.size"]) > 0
    assert report.runtime["java.version"].split(".")[0] >= "17"


# --------------------------------------------------------------- same image


def test_a_self_comparison_produces_a_finite_non_negative_score(bridge, images, tmp_path):
    adapter, _ = bridge
    left = prepared_image(images["a"], 500, "img_a")
    right = prepared_image(images["a"], 500, "img_a")

    result = adapter.compare(left, right, comparison_context(tmp_path))

    assert result.status is ExecutionStatus.SUCCESS, (
        result.failure.code.value if result.failure else ""
    )
    assert math.isfinite(result.raw_score)
    assert result.raw_score >= 0
    assert result.score_direction is ScoreDirection.HIGHER_IS_BETTER


def test_a_self_comparison_extracts_both_sides_independently(bridge, images, tmp_path):
    """The one property that a score alone can never demonstrate."""
    adapter, _ = bridge
    left = prepared_image(images["a"], 500, "img_a")
    right = prepared_image(images["a"], 500, "img_a")

    result = adapter.compare(left, right, comparison_context(tmp_path))

    assert result.metadata["extraction_count"] == "2"
    assert result.metadata["extraction_policy"] == "independent_both_sides"
    assert result.metadata["template_cache"] == "disabled"
    # Both sides were read and extracted, so both timings exist.
    for key in (
        "left_input_read",
        "left_template_extraction",
        "right_input_read",
        "right_template_extraction",
    ):
        assert key in result.timing_components_ms, key


def test_repeating_a_comparison_gives_the_same_score(bridge, images, tmp_path):
    adapter, _ = bridge
    left = prepared_image(images["a"], 500, "img_a")
    right = prepared_image(images["b"], 500, "img_b")

    first = adapter.compare(left, right, comparison_context(tmp_path))
    second = adapter.compare(left, right, comparison_context(tmp_path))

    assert first.raw_score == second.raw_score


def test_the_job_id_does_not_change_the_score(bridge, images, tmp_path):
    """request_id is for correlation; a score that depended on it would be a bug."""
    adapter, _ = bridge
    left = prepared_image(images["a"], 500, "img_a")
    right = prepared_image(images["b"], 500, "img_b")

    first = adapter.compare(
        left, right, comparison_context(tmp_path, job_id="job_0000000000000001")
    )
    second = adapter.compare(
        left, right, comparison_context(tmp_path, job_id="job_ffffffffffffffff")
    )
    assert first.raw_score == second.raw_score


# ------------------------------------------------------------- different input


def test_two_different_images_produce_a_finite_non_negative_score(bridge, images, tmp_path):
    adapter, _ = bridge
    result = adapter.compare(
        prepared_image(images["a"], 500, "img_a"),
        prepared_image(images["b"], 500, "img_b"),
        comparison_context(tmp_path),
    )
    assert result.status is ExecutionStatus.SUCCESS
    assert math.isfinite(result.raw_score)
    assert result.raw_score >= 0


def test_swapping_the_sides_is_recorded_in_the_metadata(bridge, images, tmp_path):
    """left stays the probe; the two resolutions are reported as sent."""
    adapter, _ = bridge
    result = adapter.compare(
        prepared_image(images["a"], 500, "img_a"),
        prepared_image(images["b"], 500, "img_b"),
        comparison_context(tmp_path),
    )
    assert result.metadata["probe_side"] == "left"
    assert result.metadata["left_dpi"] == "500"
    assert result.metadata["right_dpi"] == "500"


# ------------------------------------------------------------------------ DPI


@pytest.mark.parametrize("dpi", [500, 1000, 2000])
def test_every_sd300_resolution_reaches_sourceafis(bridge, tmp_path, dpi):
    """500, 1000 and 2000 must all be accepted: no clamp, no fallback, no silent
    downsampling. If 2000 were rejected the stage stops and the profile is
    reconsidered explicitly (docs/adr/0016)."""
    adapter, _ = bridge
    left = write_fixture(tmp_path, f"a_{dpi}.png", whorl_png(dpi, 1))
    right = write_fixture(tmp_path, f"b_{dpi}.png", whorl_png(dpi, 6))

    result = adapter.compare(
        prepared_image(left, dpi, "img_a"),
        prepared_image(right, dpi, "img_b"),
        comparison_context(tmp_path),
    )

    assert result.status is ExecutionStatus.SUCCESS, (
        f"{dpi} dpi rejected: "
        f"{result.failure.code.value if result.failure else ''} "
        f"{result.failure.message if result.failure else ''}"
    )
    assert result.metadata["left_dpi"] == str(dpi)
    assert result.metadata["dpi_policy"] == "explicit_effective_ppi"


def test_no_resolution_is_ever_reported_as_unsupported(bridge, tmp_path):
    adapter, _ = bridge
    for dpi in (500, 1000, 2000):
        left = write_fixture(tmp_path, f"a_{dpi}.png", whorl_png(dpi, 1))
        result = adapter.compare(
            prepared_image(left, dpi, "img_a"),
            prepared_image(left, dpi, "img_a"),
            comparison_context(tmp_path),
        )
        if result.failure is not None:
            assert result.failure.code is not FailureCode.UNSUPPORTED_RESOLUTION


def test_the_two_sides_may_carry_different_resolutions(bridge, tmp_path):
    adapter, _ = bridge
    left = write_fixture(tmp_path, "a_500.png", whorl_png(500, 1))
    right = write_fixture(tmp_path, "b_1000.png", whorl_png(1000, 6))

    result = adapter.compare(
        prepared_image(left, 500, "img_a"),
        prepared_image(right, 1000, "img_b"),
        comparison_context(tmp_path),
    )
    assert result.status is ExecutionStatus.SUCCESS
    assert result.metadata["left_dpi"] == "500"
    assert result.metadata["right_dpi"] == "1000"


# --------------------------------------------------------------------- failures


def test_a_corrupt_image_becomes_a_decode_failure(bridge, images, tmp_path):
    adapter, _ = bridge
    result = adapter.compare(
        prepared_image(images["a"], 500, "img_a"),
        prepared_image(images["corrupt"], 500, "img_corrupt"),
        comparison_context(tmp_path),
    )

    assert result.status is ExecutionStatus.FAILURE
    assert result.failure.code is FailureCode.IMAGE_DECODE_FAILED
    assert result.failure.stage is FailureStage.EXTRACTION
    assert result.failure.details["side"] == "right"
    assert result.raw_score is None


def test_a_missing_file_becomes_invalid_input(bridge, images, tmp_path):
    adapter, _ = bridge
    absent = tmp_path / "absent.png"
    # A prepared image over a file that has since gone away.
    left = prepared_image(images["a"], 500, "img_a")
    right = replace(left, image_id="img_gone", local_path=absent.resolve())

    result = adapter.compare(left, right, comparison_context(tmp_path))

    assert result.status is ExecutionStatus.FAILURE
    assert result.failure.code is FailureCode.INPUT_INVALID
    assert result.failure.stage is FailureStage.INPUT


def test_a_failure_message_names_no_path(bridge, images, tmp_path):
    adapter, _ = bridge
    named = write_fixture(tmp_path, "subject-00001000-finger-01.png", corrupt_png())

    result = adapter.compare(
        prepared_image(images["a"], 500, "img_a"),
        prepared_image(named, 500, "img_named"),
        comparison_context(tmp_path),
    )

    message = result.failure.message
    assert "subject-00001000" not in message
    assert str(tmp_path) not in message


def test_a_timeout_is_reported_as_a_timeout(bridge, images, tmp_path):
    """An impossible budget: the JVM cannot even start in a millisecond."""
    adapter, _ = bridge
    with pytest.raises(TimeoutError):
        adapter.compare(
            prepared_image(images["a"], 500, "img_a"),
            prepared_image(images["b"], 500, "img_b"),
            comparison_context(tmp_path, timeout_seconds=0.001),
        )


# ------------------------------------------------------------ no side effects


def test_the_bridge_writes_nothing_outside_its_context(bridge, images, tmp_path):
    adapter, _ = bridge
    context = comparison_context(tmp_path)
    before = {p for p in tmp_path.rglob("*") if p.is_file()}

    adapter.compare(
        prepared_image(images["a"], 500, "img_a"),
        prepared_image(images["b"], 500, "img_b"),
        context,
    )

    created = {p for p in tmp_path.rglob("*") if p.is_file()} - before
    for path in created:
        assert path.is_relative_to(context.working_directory) or path.is_relative_to(
            context.artifact_directory
        ), f"wrote outside its context: {path}"


def test_no_artifacts_are_produced(bridge, images, tmp_path):
    """Templates are neither serialised nor stored in stage 4A (docs/adr/0016)."""
    adapter, _ = bridge
    result = adapter.compare(
        prepared_image(images["a"], 500, "img_a"),
        prepared_image(images["b"], 500, "img_b"),
        comparison_context(tmp_path),
    )
    assert result.artifacts == ()


def test_the_input_files_are_not_modified(bridge, images, tmp_path):
    adapter, _ = bridge
    before = {name: path.read_bytes() for name, path in images.items() if name != "corrupt"}

    adapter.compare(
        prepared_image(images["a"], 500, "img_a"),
        prepared_image(images["b"], 500, "img_b"),
        comparison_context(tmp_path),
    )

    for name, payload in before.items():
        assert images[name].read_bytes() == payload, name


def test_the_result_carries_no_threshold_or_decision(bridge, images, tmp_path):
    adapter, _ = bridge
    result = adapter.compare(
        prepared_image(images["a"], 500, "img_a"),
        prepared_image(images["b"], 500, "img_b"),
        comparison_context(tmp_path),
    )
    forbidden = {"threshold", "decision", "is_match", "ground_truth", "protocol_stage"}
    assert forbidden.isdisjoint(result.metadata)


# ------------------------------------------------------------- through the runner


def test_the_runner_stores_a_sourceafis_result_and_resumes_without_java(
    bridge, tmp_path
):
    """The second execution must not start a JVM at all."""
    adapter, report = bridge
    dataset_root = tmp_path / "nist"
    workspace = tmp_path / "workspace"

    plain = write_fixture(dataset_root, "plain.png", whorl_png(500, 1))
    roll = write_fixture(dataset_root, "roll.png", whorl_png(500, 6))

    records = {
        "sd300a_00001000_plain_f01": image_record(
            image_id="sd300a_00001000_plain_f01",
            relative_path="plain.png",
            expected_sha256=sha256_of(plain.read_bytes()),
        ),
        "sd300a_00001000_roll_f01": image_record(
            image_id="sd300a_00001000_roll_f01",
            relative_path="roll.png",
            expected_sha256=sha256_of(roll.read_bytes()),
        ),
    }
    pair = comparison_pair(
        pair_id="sd300a_00001000_f01_mated",
        left_image_id="sd300a_00001000_plain_f01",
        right_image_id="sd300a_00001000_roll_f01",
    )

    run = create_run_definition(
        protocol_id="sd300_50_subjects",
        cohort_id="sd300_50_subjects_test_ab12cd34",
        pair_manifest_hash="a1" * 32,
        algorithm=adapter.descriptor,
        environment=report,
        execution_profile=_native_profile(),
    )
    store = ResultStore(workspace)

    class CountingAdapter:
        """Wraps the real adapter so JVM launches can be counted."""

        def __init__(self, delegate):
            self._delegate = delegate
            self.compare_calls = 0

        @property
        def descriptor(self):
            return self._delegate.descriptor

        def validate_environment(self):
            return self._delegate.validate_environment()

        def compare(self, left, right, context):
            self.compare_calls += 1
            return self._delegate.compare(left, right, context)

    counting = CountingAdapter(adapter)
    runner = SingleJobRunner(
        run=run,
        adapter=counting,
        preparer=IdentityImagePreparer(),
        result_store=store,
        dataset_root=dataset_root,
        image_index=records,
        workspace_root=workspace,
    )
    job = build_comparison_job(run, pair)

    first = runner.execute(job, pair)
    assert first.disposition is JobDisposition.EXECUTED
    assert first.result.status is ExecutionStatus.SUCCESS
    assert first.result.algorithm_id == "sourceafis_java"
    assert counting.compare_calls == 1

    second = runner.execute(job, pair)
    assert second.disposition is JobDisposition.SKIPPED_EXISTING
    assert counting.compare_calls == 1, "resume must not start a JVM"
    assert second.result == first.result


def test_a_stored_sourceafis_result_holds_no_absolute_path(bridge, tmp_path):
    adapter, report = bridge
    dataset_root = tmp_path / "nist"
    workspace = tmp_path / "workspace"
    image = write_fixture(dataset_root, "a.png", whorl_png(500, 1))
    record = image_record(
        image_id="sd300a_00001000_plain_f01",
        relative_path="a.png",
        expected_sha256=sha256_of(image.read_bytes()),
    )
    pair = comparison_pair(
        pair_id="sd300a_00001000_f01_plain_self",
        left_image_id=record.image_id,
        right_image_id=record.image_id,
    )
    run = create_run_definition(
        protocol_id="sd300_50_subjects",
        cohort_id="sd300_50_subjects_test_ab12cd34",
        pair_manifest_hash="a2" * 32,
        algorithm=adapter.descriptor,
        environment=report,
        execution_profile=_native_profile(),
    )
    runner = SingleJobRunner(
        run=run,
        adapter=adapter,
        preparer=IdentityImagePreparer(),
        result_store=ResultStore(workspace),
        dataset_root=dataset_root,
        image_index={record.image_id: record},
        workspace_root=workspace,
    )
    result = runner.execute(build_comparison_job(run, pair), pair).result

    rendered = repr(result)
    assert str(dataset_root) not in rendered
    assert str(workspace) not in rendered


def _native_profile():
    from fpbench.core.execution_models import ExecutionProfile

    return ExecutionProfile(
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
