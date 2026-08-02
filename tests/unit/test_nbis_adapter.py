"""The NBIS adapter's own contract, driven through real subprocesses.

The tools underneath are stand-ins (``tests/fixtures/nbis_cli/``) and nothing here
is a fingerprint or a score. What *is* real is everything the adapter is
responsible for: the exact command lines, one budget across three processes, two
independent extractions even when both sides are the same file, an empty working
directory afterwards on every path out, a stored result that names its options,
and a runtime that is noticed when it changes.

Claims about NBIS itself — PNG support, the PPI policy, determinism of the real
extractor, the meaning of a zero score — belong to
``tests/integration/test_nbis_upstream.py`` and run against a certified build.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from fpbench.adapters.nbis.adapter import (
    ADAPTER_ID,
    ALGORITHM_ID,
    LEFT_INPUT,
    LEFT_OUTPUT_ROOT,
    MINDTCT_OUTPUT_SUFFIXES,
    RESULT_METADATA,
    RIGHT_INPUT,
    RIGHT_OUTPUT_ROOT,
    NbisAdapter,
)
from fpbench.adapters.support.process import ExternalCommand
from fpbench.core.enums import (
    EnvironmentStatus,
    ExecutionStatus,
    FailureCode,
    FailureStage,
    ScoreDirection,
)
from fpbench.core.errors import ResearchPreflightError, RuntimeDriftError
from fpbench.core.execution_models import descriptor_fingerprint
from nbisworld import (
    build_stand_in,
    certify_host,
    files_in,
    gray8_png,
    host_is_certified,
    job_context,
    job_directories,
    png_with_case,
    prepared_image,
)

pytestmark = pytest.mark.nbis_contract


# ------------------------------------------------------------------ fixtures


@pytest.fixture
def build(tmp_path):
    return build_stand_in(tmp_path / "build")


@pytest.fixture
def adapter(build):
    return build.adapter()


@pytest.fixture
def directories(tmp_path):
    return job_directories(tmp_path)


@pytest.fixture
def commands(monkeypatch):
    """Record every command line the adapter builds, then run it for real."""
    from fpbench.adapters.nbis import adapter as adapter_module

    recorded: list[tuple[str, ...]] = []
    original = adapter_module.run_external_command

    def recording(command: ExternalCommand):
        recorded.append(tuple(command.argv))
        return original(command)

    monkeypatch.setattr(adapter_module, "run_external_command", recording)
    return recorded


def image(tmp_path, side: str, seed: int = 1, case: str | None = None):
    payload = gray8_png(seed)
    if case:
        payload = png_with_case(payload, case)
    return prepared_image(
        tmp_path / "inputs" / f"{side}.png",
        payload,
        image_id=f"sd300a_00001000_plain_{side}",
    )


def compare(adapter, directories, left, right, *, timeout_seconds: float = 60.0):
    working, artifacts = directories
    return adapter.compare(
        left, right, job_context(working, artifacts, timeout_seconds=timeout_seconds)
    )


# ---------------------------------------------------------------- descriptor


def test_the_identity_names_the_whole_route(adapter):
    descriptor = adapter.descriptor
    assert descriptor.algorithm_id == ALGORITHM_ID == "nbis_mindtct_bozorth3"
    assert descriptor.adapter_id == ADAPTER_ID
    assert descriptor.adapter_version == "1"
    assert descriptor.adapter_contract_version == "1"
    assert descriptor.implementation_version == "5.0.0"
    assert descriptor.score_direction is ScoreDirection.HIGHER_IS_BETTER
    assert descriptor.deterministic is True


def test_the_descriptor_declares_the_options_it_does_not_pass(adapter):
    metadata = dict(adapter.descriptor.metadata)
    assert metadata["extractor_id"] == "mindtct"
    assert metadata["matcher_id"] == "bozorth3"
    assert metadata["mindtct_contrast_boost"] == "disabled"
    assert metadata["mindtct_m1"] == "disabled"
    assert metadata["bozorth3_m1"] == "disabled"
    assert metadata["bozorth3_threshold"] == "none"
    assert metadata["bozorth3_max_minutiae"] == "default_150"
    assert metadata["bozorth3_min_minutiae"] == "default_10"
    assert metadata["score_type"] == "nonnegative_integer_similarity"
    assert metadata["input_effective_ppi"] == "500"
    assert metadata["probe_side"] == "left"
    assert metadata["template_cache"] == "disabled"
    assert metadata["template_persistence"] == "disabled"


def test_the_descriptor_is_stable(adapter):
    assert adapter.descriptor == adapter.descriptor
    assert descriptor_fingerprint(adapter.descriptor) == descriptor_fingerprint(
        adapter.descriptor
    )


# --------------------------------------------------------- command construction


def test_mindtct_runs_twice_and_bozorth3_once(adapter, directories, commands, tmp_path):
    compare(adapter, directories, image(tmp_path, "left", 1), image(tmp_path, "right", 6))
    assert len(commands) == 3
    assert Path(commands[0][0]).stem == "mindtct"
    assert Path(commands[1][0]).stem == "mindtct"
    assert Path(commands[2][0]).stem == "bozorth3"


def test_mindtct_is_given_exactly_an_image_and_an_output_root(
    adapter, directories, commands, tmp_path
):
    """``mindtct <input.png> <output-root>`` and nothing else (section 23)."""
    compare(adapter, directories, image(tmp_path, "left", 1), image(tmp_path, "right", 6))
    left, right = commands[0], commands[1]
    assert len(left) == len(right) == 3
    assert Path(left[1]).name == LEFT_INPUT
    assert Path(left[2]).name == LEFT_OUTPUT_ROOT
    assert Path(right[1]).name == RIGHT_INPUT
    assert Path(right[2]).name == RIGHT_OUTPUT_ROOT


def test_bozorth3_is_given_exactly_two_templates(
    adapter, directories, commands, tmp_path
):
    compare(adapter, directories, image(tmp_path, "left", 1), image(tmp_path, "right", 6))
    argv = commands[2]
    assert len(argv) == 3
    assert Path(argv[1]).name == f"{LEFT_OUTPUT_ROOT}.xyt"
    assert Path(argv[2]).name == f"{RIGHT_OUTPUT_ROOT}.xyt"


def test_left_is_the_probe_and_right_is_the_gallery(
    adapter, directories, commands, tmp_path
):
    """Section 24: the first argument is the probe, and there is no reverse run."""
    compare(adapter, directories, image(tmp_path, "left", 1), image(tmp_path, "right", 6))
    assert commands[2][1].endswith(f"{LEFT_OUTPUT_ROOT}.xyt")
    assert commands[2][2].endswith(f"{RIGHT_OUTPUT_ROOT}.xyt")
    assert len([argv for argv in commands if Path(argv[0]).stem == "bozorth3"]) == 1


@pytest.mark.parametrize(
    "flag", ["-b", "-m1", "-n", "-A", "-T", "-q", "-O", "-o", "-e", "-v", "-V"]
)
def test_no_forbidden_option_ever_reaches_a_command_line(
    adapter, directories, commands, tmp_path, flag
):
    """Sections 23 to 26: every one of these would be a different experiment."""
    compare(adapter, directories, image(tmp_path, "left", 1), image(tmp_path, "right", 6))
    for argv in commands:
        assert flag not in argv[1:], argv


def test_every_command_runs_from_inside_the_job_directory(
    adapter, directories, tmp_path, monkeypatch
):
    from fpbench.adapters.nbis import adapter as adapter_module

    working, _artifacts = directories
    seen: list[Path] = []
    original = adapter_module.run_external_command

    def recording(command: ExternalCommand):
        seen.append(command.working_directory)
        return original(command)

    monkeypatch.setattr(adapter_module, "run_external_command", recording)
    compare(adapter, directories, image(tmp_path, "left", 1), image(tmp_path, "right", 6))
    assert seen and all(path == working.resolve() for path in seen)


# ---------------------------------------------------------------- the result


def test_a_successful_comparison_carries_an_integer_score(adapter, directories, tmp_path):
    result = compare(
        adapter, directories, image(tmp_path, "left", 1), image(tmp_path, "right", 6)
    )
    assert result.status is ExecutionStatus.SUCCESS
    assert result.raw_score is not None
    assert float(result.raw_score) == int(result.raw_score)
    assert result.raw_score >= 0
    assert result.failure is None


def test_the_result_records_every_fixed_fact_about_the_route(
    adapter, directories, tmp_path
):
    result = compare(
        adapter, directories, image(tmp_path, "left", 1), image(tmp_path, "right", 6)
    )
    metadata = dict(result.metadata)
    for key, expected in RESULT_METADATA.items():
        assert metadata[key] == expected, key
    assert metadata["pipeline"] == "nbis_mindtct_bozorth3"
    assert metadata["nbis_version"] == "5.0.0"
    assert metadata["effective_ppi"] == "500"
    assert metadata["ppi_policy"] == "nbis_png_default_500"
    assert metadata["input_transport"] == "byte_for_byte_copy"
    assert metadata["extraction_count"] == "2"
    assert metadata["left_minutiae_count"].isdigit()
    assert metadata["right_minutiae_count"].isdigit()


def test_the_result_records_no_template_and_no_decision(adapter, directories, tmp_path):
    result = compare(
        adapter, directories, image(tmp_path, "left", 1), image(tmp_path, "right", 6)
    )
    forbidden = {
        "threshold",
        "decision",
        "is_match",
        "matched",
        "ground_truth",
        "protocol_stage",
        "subject_id",
        "template",
        "minutiae",
        "xyt",
        "score",
    }
    assert forbidden.isdisjoint(result.metadata)
    assert result.artifacts == ()


def test_no_metadata_value_carries_a_path(adapter, directories, tmp_path):
    result = compare(
        adapter, directories, image(tmp_path, "left", 1), image(tmp_path, "right", 6)
    )
    for key, value in result.metadata.items():
        assert "/" not in value and "\\" not in value, f"{key}={value}"


def test_the_timings_name_only_the_stages_that_ran(adapter, directories, tmp_path):
    result = compare(
        adapter, directories, image(tmp_path, "left", 1), image(tmp_path, "right", 6)
    )
    assert set(result.timing_components_ms) == {
        "input_staging",
        "left_extraction",
        "right_extraction",
        "matching",
        "cleanup",
    }
    assert all(value >= 0 for value in result.timing_components_ms.values())


def test_a_failed_left_extraction_records_no_later_stage(adapter, directories, tmp_path):
    result = compare(
        adapter,
        directories,
        image(tmp_path, "left", 1, case="mindtct-fail"),
        image(tmp_path, "right", 6),
    )
    assert result.status is ExecutionStatus.FAILURE
    assert "right_extraction" not in result.timing_components_ms
    assert "matching" not in result.timing_components_ms
    assert "cleanup" in result.timing_components_ms


# ------------------------------------------------------------- both sides


def test_a_self_comparison_extracts_both_sides_independently(
    adapter, directories, commands, tmp_path
):
    """Section 45: the same file twice is still two extractions, two roots."""
    left = image(tmp_path, "same", 1)
    result = compare(adapter, directories, left, left)
    assert result.status is ExecutionStatus.SUCCESS
    assert result.metadata["extraction_count"] == "2"
    assert result.metadata["template_cache"] == "disabled"
    assert result.metadata["template_persistence"] == "disabled"

    extractions = [argv for argv in commands if Path(argv[0]).stem == "mindtct"]
    assert len(extractions) == 2
    assert {Path(argv[2]).name for argv in extractions} == {
        LEFT_OUTPUT_ROOT,
        RIGHT_OUTPUT_ROOT,
    }
    assert Path(extractions[0][1]).name != Path(extractions[1][1]).name


def test_a_self_comparison_stages_the_source_twice(adapter, directories, tmp_path):
    """Both copies exist while the tools run, even though they are identical."""
    from fpbench.adapters.nbis import adapter as adapter_module

    left = image(tmp_path, "same", 1)
    seen: list[list[str]] = []
    original = adapter_module.run_external_command

    def recording(command: ExternalCommand):
        seen.append(files_in(command.working_directory))
        return original(command)

    import unittest.mock

    with unittest.mock.patch.object(
        adapter_module, "run_external_command", recording
    ):
        compare(adapter, directories, left, left)
    assert LEFT_INPUT in seen[0] and RIGHT_INPUT in seen[0]


# --------------------------------------------------------------- direction


def test_reversing_the_sides_is_a_different_call(adapter, directories, tmp_path):
    """Section 44: this route never runs the reverse direction on its own."""
    working, artifacts = directories
    left, right = image(tmp_path, "left", 1), image(tmp_path, "right", 6)
    forward = compare(adapter, directories, left, right)
    reverse = compare(adapter, directories, right, left)
    assert forward.status is reverse.status is ExecutionStatus.SUCCESS
    assert forward.raw_score != reverse.raw_score


# --------------------------------------------------------------- zero score


def test_fewer_than_ten_minutiae_scores_zero_rather_than_failing(
    adapter, directories, tmp_path
):
    """Section 43: 0 is a score, on both the empty and the nine-minutia case."""
    result = compare(
        adapter,
        directories,
        image(tmp_path, "left", 1, case="mindtct-few"),
        image(tmp_path, "right", 6, case="mindtct-few"),
    )
    assert result.status is ExecutionStatus.SUCCESS
    assert result.raw_score == 0.0
    assert result.metadata["left_minutiae_count"] == "9"


def test_an_empty_template_scores_zero_rather_than_failing(
    adapter, directories, tmp_path
):
    result = compare(
        adapter,
        directories,
        image(tmp_path, "left", 1, case="mindtct-empty"),
        image(tmp_path, "right", 6, case="mindtct-empty"),
    )
    assert result.status is ExecutionStatus.SUCCESS
    assert result.raw_score == 0.0
    assert result.metadata["left_minutiae_count"] == "0"


def test_one_short_side_is_enough_for_a_zero(adapter, directories, tmp_path):
    result = compare(
        adapter,
        directories,
        image(tmp_path, "left", 1, case="mindtct-few"),
        image(tmp_path, "right", 6),
    )
    assert result.status is ExecutionStatus.SUCCESS
    assert result.raw_score == 0.0


# ------------------------------------------------------------ failure paths


@pytest.mark.parametrize("side", ["left", "right"])
def test_a_declined_print_is_an_extraction_failure(adapter, directories, tmp_path, side):
    left = image(tmp_path, "left", 1, case="mindtct-fail" if side == "left" else None)
    right = image(tmp_path, "right", 6, case="mindtct-fail" if side == "right" else None)
    result = compare(adapter, directories, left, right)
    assert result.status is ExecutionStatus.FAILURE
    assert result.failure.code is FailureCode.TEMPLATE_EXTRACTION_FAILED
    assert result.failure.stage is FailureStage.EXTRACTION
    assert result.failure.details["output_kind"] == "nonzero_exit"
    assert result.failure.details["side"] == side


def test_a_missing_xyt_after_a_successful_exit_is_an_extraction_failure(
    adapter, directories, tmp_path
):
    result = compare(
        adapter,
        directories,
        image(tmp_path, "left", 1, case="mindtct-noxyt"),
        image(tmp_path, "right", 6),
    )
    assert result.failure.code is FailureCode.TEMPLATE_EXTRACTION_FAILED
    assert result.failure.details["output_kind"] == "invalid_extractor_output"
    assert result.failure.details["reason"] == "missing_extractor_output"


def test_an_unusable_xyt_after_a_successful_exit_is_an_extraction_failure(
    adapter, directories, tmp_path
):
    result = compare(
        adapter,
        directories,
        image(tmp_path, "left", 1, case="mindtct-garbage"),
        image(tmp_path, "right", 6),
    )
    assert result.failure.code is FailureCode.TEMPLATE_EXTRACTION_FAILED
    assert result.failure.details["output_kind"] == "invalid_extractor_output"
    assert result.failure.details["reason"] == "invalid_extractor_output"


def test_a_crashing_extractor_is_a_crash_not_a_declined_print(
    adapter, directories, tmp_path
):
    result = compare(
        adapter,
        directories,
        image(tmp_path, "left", 1, case="mindtct-crash"),
        image(tmp_path, "right", 6),
    )
    assert result.failure.code is FailureCode.PROCESS_CRASHED
    assert result.failure.stage is FailureStage.EXTRACTION


def test_a_failing_matcher_is_a_matching_failure(adapter, directories, tmp_path):
    result = compare(
        adapter,
        directories,
        image(tmp_path, "left", 1, case="bozorth3-fail"),
        image(tmp_path, "right", 6),
    )
    assert result.failure.code is FailureCode.MATCHING_FAILED
    assert result.failure.stage is FailureStage.MATCHING


def test_a_crashing_matcher_is_a_crash_during_matching(adapter, directories, tmp_path):
    result = compare(
        adapter,
        directories,
        image(tmp_path, "left", 1, case="bozorth3-crash"),
        image(tmp_path, "right", 6),
    )
    assert result.failure.code is FailureCode.PROCESS_CRASHED
    assert result.failure.stage is FailureStage.MATCHING


@pytest.mark.parametrize("case", ["bozorth3-noise", "bozorth3-silent"])
def test_a_matcher_that_prints_no_usable_score_is_no_score(
    adapter, directories, tmp_path, case
):
    result = compare(
        adapter,
        directories,
        image(tmp_path, "left", 1, case=case),
        image(tmp_path, "right", 6),
    )
    assert result.failure.code is FailureCode.NO_SCORE
    assert result.failure.stage is FailureStage.MATCHING
    assert result.raw_score is None


def test_an_input_of_the_wrong_shape_is_recorded_not_raised(
    adapter, directories, tmp_path
):
    left = prepared_image(
        tmp_path / "inputs" / "wrong.png", gray8_png(1), effective_ppi=1000
    )
    result = compare(adapter, directories, left, image(tmp_path, "right", 6))
    assert result.status is ExecutionStatus.FAILURE
    assert result.failure.code is FailureCode.INPUT_INVALID
    assert result.failure.stage is FailureStage.INPUT
    assert result.failure.details["reason"] == "unsupported_resolution"


def test_no_failure_ever_becomes_a_score(adapter, directories, tmp_path):
    for case in (
        "mindtct-fail",
        "mindtct-garbage",
        "mindtct-crash",
        "bozorth3-fail",
        "bozorth3-silent",
    ):
        result = compare(
            adapter,
            directories,
            image(tmp_path, "left", 1, case=case),
            image(tmp_path, "right", 6),
        )
        assert result.raw_score is None, case
        assert result.failure is not None, case


# ---------------------------------------------------------------- timeouts


def test_a_hanging_extractor_is_a_timeout(adapter, directories, tmp_path):
    result = compare(
        adapter,
        directories,
        image(tmp_path, "left", 1, case="mindtct-hang"),
        image(tmp_path, "right", 6),
        timeout_seconds=1.0,
    )
    assert result.failure.code is FailureCode.TIMEOUT
    assert result.failure.stage is FailureStage.TIMEOUT


def test_a_hanging_matcher_is_a_timeout(adapter, directories, tmp_path):
    result = compare(
        adapter,
        directories,
        image(tmp_path, "left", 1, case="bozorth3-hang"),
        image(tmp_path, "right", 6),
        timeout_seconds=3.0,
    )
    assert result.failure.code is FailureCode.TIMEOUT


def test_the_budget_is_shared_across_the_whole_comparison(
    adapter, directories, commands, tmp_path
):
    """Section 29: one total, not one per stage.

    The left extraction consumes the entire budget, so the right one never runs.
    Three independent timeouts would have let the comparison take three times what
    the contract allowed.
    """
    result = compare(
        adapter,
        directories,
        image(tmp_path, "left", 1, case="mindtct-hang"),
        image(tmp_path, "right", 6),
        timeout_seconds=1.0,
    )
    assert result.failure.code is FailureCode.TIMEOUT
    assert len(commands) == 1


# ----------------------------------------------------------------- cleanup


CLEANUP_CASES = [
    ("success", None, None),
    ("left extraction failure", "mindtct-fail", None),
    ("right extraction failure", None, "mindtct-fail"),
    ("missing xyt", "mindtct-noxyt", None),
    ("malformed xyt", "mindtct-garbage", None),
    ("extractor crash", "mindtct-crash", None),
    ("matching failure", "bozorth3-fail", None),
    ("no score", "bozorth3-silent", None),
]


@pytest.mark.parametrize(
    "label,left_case,right_case", CLEANUP_CASES, ids=[c[0] for c in CLEANUP_CASES]
)
def test_the_working_directory_is_empty_afterwards(
    adapter, directories, tmp_path, label, left_case, right_case
):
    """Section 32: the runner does not clear it, so the adapter must."""
    working, artifacts = directories
    compare(
        adapter,
        directories,
        image(tmp_path, "left", 1, case=left_case),
        image(tmp_path, "right", 6, case=right_case),
    )
    assert files_in(working) == [], label
    assert files_in(artifacts) == [], label


@pytest.mark.parametrize("case", ["mindtct-hang", "bozorth3-hang"])
def test_the_working_directory_is_empty_after_a_timeout(
    adapter, directories, tmp_path, case
):
    working, artifacts = directories
    compare(
        adapter,
        directories,
        image(tmp_path, "left", 1, case=case),
        image(tmp_path, "right", 6),
        timeout_seconds=2.0,
    )
    assert files_in(working) == []
    assert files_in(artifacts) == []


def test_every_map_file_the_extractor_writes_is_removed(adapter, directories, tmp_path):
    """All eight suffixes, not only the XYT the adapter happens to read."""
    working, _artifacts = directories
    compare(adapter, directories, image(tmp_path, "left", 1), image(tmp_path, "right", 6))
    for root in (LEFT_OUTPUT_ROOT, RIGHT_OUTPUT_ROOT):
        for suffix in MINDTCT_OUTPUT_SUFFIXES:
            assert not (working / f"{root}.{suffix}").exists()


def test_cleanup_leaves_a_neighbour_alone(adapter, directories, tmp_path):
    """Scoped to the two known roots: no wildcard sweep of the directory."""
    working, _artifacts = directories
    bystander = working / "something-else.txt"
    bystander.write_text("not mine", encoding="utf-8")
    compare(adapter, directories, image(tmp_path, "left", 1), image(tmp_path, "right", 6))
    assert bystander.read_text(encoding="utf-8") == "not mine"


def test_the_inputs_are_not_modified(adapter, directories, tmp_path):
    left, right = image(tmp_path, "left", 1), image(tmp_path, "right", 6)
    before = (
        Path(left.local_path).read_bytes(),
        Path(right.local_path).read_bytes(),
    )
    compare(adapter, directories, left, right)
    assert (
        Path(left.local_path).read_bytes(),
        Path(right.local_path).read_bytes(),
    ) == before


def test_the_staged_copy_is_byte_for_byte(adapter, directories, tmp_path, monkeypatch):
    """Section 21: no re-encoding, no conversion, no PGM and no WSQ."""
    from fpbench.adapters.nbis import adapter as adapter_module

    left = image(tmp_path, "left", 1)
    staged: list[bytes] = []
    original = adapter_module.run_external_command

    def recording(command: ExternalCommand):
        candidate = command.working_directory / LEFT_INPUT
        if candidate.is_file():
            staged.append(candidate.read_bytes())
        return original(command)

    monkeypatch.setattr(adapter_module, "run_external_command", recording)
    compare(adapter, directories, left, image(tmp_path, "right", 6))
    assert staged and staged[0] == Path(left.local_path).read_bytes()


# ------------------------------------------------------------- determinism


def test_the_same_pair_produces_the_same_result_twice(adapter, directories, tmp_path):
    left, right = image(tmp_path, "left", 1), image(tmp_path, "right", 6)
    first = compare(adapter, directories, left, right)
    second = compare(adapter, directories, left, right)
    assert first.status is second.status
    assert first.raw_score == second.raw_score
    assert dict(first.metadata) == dict(second.metadata)
    assert first.failure == second.failure


# ------------------------------------------------------------- environment


def test_an_uncertified_platform_is_unavailable_and_not_an_exception(adapter):
    """Section 18: v1 certifies Linux x86_64, and elsewhere it says so."""
    report = adapter.validate_environment()
    if host_is_certified():
        assert report.status is EnvironmentStatus.READY
    else:
        assert report.status is EnvironmentStatus.UNAVAILABLE
        assert "linux" in (report.message or "")


def test_a_certified_platform_reports_ready(build, monkeypatch):
    certify_host(monkeypatch)
    report = build.adapter().validate_environment()
    assert report.status is EnvironmentStatus.READY, report.message
    assert report.implementation_version == "5.0.0"
    assert report.dependencies["nbis.version"] == "5.0.0"
    assert report.dependencies["nbis.png_ppi_policy"] == "metadata_ignored_default_500"
    assert report.dependencies["nbis.build_manifest_fingerprint"]


def test_the_environment_report_carries_no_path(build, monkeypatch):
    certify_host(monkeypatch)
    report = build.adapter().validate_environment()
    rendered = " ".join(
        [*report.runtime.values(), *report.dependencies.values(), report.message or ""]
    )
    assert str(build.directory) not in rendered


def test_a_missing_executable_is_unavailable_not_an_exception(build, monkeypatch):
    certify_host(monkeypatch)
    build.mindtct.unlink()
    report = build.adapter().validate_environment()
    assert report.status is EnvironmentStatus.UNAVAILABLE
    assert "nbis_mindtct_executable" in (report.message or "")


def test_a_tampered_manifest_is_unavailable_in_development(build, monkeypatch, tmp_path):
    certify_host(monkeypatch)
    build.manifest_path.write_text("{}", encoding="utf-8")
    report = build.adapter().validate_environment()
    assert report.status is EnvironmentStatus.UNAVAILABLE


def test_a_tampered_manifest_is_fatal_in_research_mode(build, monkeypatch):
    """Section 12: there is no research reading of an uncertified build."""
    certify_host(monkeypatch)
    build.manifest_path.write_text("{}", encoding="utf-8")
    with pytest.raises(ResearchPreflightError, match="not certified"):
        build.adapter(research_mode=True).validate_environment()


def test_a_replaced_executable_is_refused_by_the_environment(build, monkeypatch):
    certify_host(monkeypatch)
    build.bozorth3.write_bytes(build.bozorth3.read_bytes() + b"\r\n")
    report = build.adapter().validate_environment()
    assert report.status is EnvironmentStatus.UNAVAILABLE
    assert "bozorth3" in (report.message or "")


# ------------------------------------------------------------ runtime drift


@pytest.mark.parametrize(
    "role", ["mindtct", "bozorth3", "manifest"]
)
def test_a_runtime_file_that_changes_after_preflight_is_fatal(
    build, directories, tmp_path, monkeypatch, role
):
    """Section 47: drift is a fact about the run, never a per-pair failure."""
    certify_host(monkeypatch)
    adapter = build.adapter(research_mode=True)
    assert adapter.validate_environment().status is EnvironmentStatus.READY

    target = {
        "mindtct": build.mindtct,
        "bozorth3": build.bozorth3,
        "manifest": build.manifest_path,
    }[role]
    target.write_bytes(target.read_bytes() + b"\n")

    with pytest.raises(RuntimeDriftError):
        compare(adapter, directories, image(tmp_path, "left", 1), image(tmp_path, "right", 6))


def test_a_research_adapter_that_never_validated_refuses_to_compare(
    build, directories, tmp_path
):
    adapter = build.adapter(research_mode=True)
    with pytest.raises(RuntimeDriftError, match="never validated"):
        compare(adapter, directories, image(tmp_path, "left", 1), image(tmp_path, "right", 6))


def test_a_development_adapter_does_not_re_check_its_runtime(
    build, directories, tmp_path
):
    """Outside research mode there is nothing pinned and nothing to check."""
    adapter = build.adapter()
    adapter.check_runtime_integrity()
    result = compare(
        adapter, directories, image(tmp_path, "left", 1), image(tmp_path, "right", 6)
    )
    assert result.status is ExecutionStatus.SUCCESS


# ------------------------------------------------------------------ surface


def test_compare_asks_for_nothing_but_two_images_and_a_context():
    import inspect

    assert list(inspect.signature(NbisAdapter.compare).parameters) == [
        "self",
        "left",
        "right",
        "context",
    ]
