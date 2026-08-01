"""A two-stage route through the existing contract, and every way it fails.

This is stage 7A's proof rather than its promise. The adapter runs three
subprocesses, writes four intermediate files and can fail at four stages, and it
reaches the harness through the same three methods the dummy matcher uses. If any
of the scenarios below needed a change to ``SingleJobRunner``, the result schema
or a store, stage 7A would have failed (docs/adr/0043, spec sections 56 to 59).

**Nothing here is biometric.** The extractor hashes bytes; the matcher hashes two
hashes; the images are not fingerprints.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

from fpbench.adapters.support.workspace import WorkspaceContainmentError
from fpbench.adapters.synthetic_two_stage import (
    ADAPTER_ID,
    EXTRACTOR_ROLE,
    MATCHER_ROLE,
    SyntheticTwoStageCliAdapter,
    SyntheticTwoStageConfig,
)
from fpbench.core.enums import (
    ChecksumStatus,
    EnvironmentStatus,
    ExecutionStatus,
    FailureCode,
    FailureStage,
    ScoreDirection,
)
from fpbench.core.errors import ConfigurationError, RuntimeDriftError
from fpbench.core.execution_models import ComparisonContext, PreparedImage

pytestmark = pytest.mark.adapter_contract

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "two_stage_cli"
EXTRACTOR = FIXTURES / "extractor.py"
MATCHER = FIXTURES / "matcher.py"

RUN_ID = "run_abc123def456"
JOB_ID = "job_0123456789abcdef"


@pytest.fixture
def sandbox(tmp_path: Path) -> dict[str, Path]:
    working = tmp_path / "work" / RUN_ID / JOB_ID
    artifacts = tmp_path / "artifacts" / RUN_ID / JOB_ID
    inputs = tmp_path / "inputs"
    for directory in (working, artifacts, inputs):
        directory.mkdir(parents=True)
    return {
        "root": tmp_path,
        "working": working,
        "artifacts": artifacts,
        "inputs": inputs,
    }


@pytest.fixture
def context(sandbox) -> ComparisonContext:
    return ComparisonContext(
        run_id=RUN_ID,
        job_id=JOB_ID,
        attempt=1,
        working_directory=sandbox["working"],
        artifact_directory=sandbox["artifacts"],
        timeout_seconds=60.0,
        deterministic_seed=0,
    )


def tools(tmp_path: Path) -> tuple[Path, Path]:
    """Copies of the two fixture tools, so a test may replace one."""
    target = tmp_path / "tools"
    target.mkdir(parents=True, exist_ok=True)
    extractor = target / "extractor.py"
    matcher = target / "matcher.py"
    extractor.write_bytes(EXTRACTOR.read_bytes())
    matcher.write_bytes(MATCHER.read_bytes())
    return extractor, matcher


def adapter(tmp_path: Path, *, research_mode: bool = False, **overrides):
    extractor, matcher = tools(tmp_path)
    settings = {
        "extractor": extractor,
        "matcher": matcher,
        "interpreter": Path(sys.executable).resolve(),
        "research_mode": research_mode,
    }
    settings.update(overrides)
    instance = SyntheticTwoStageCliAdapter(SyntheticTwoStageConfig(**settings))
    instance.validate_environment()
    return instance


def image(directory: Path, name: str, payload: bytes) -> PreparedImage:
    path = directory / f"{name}.bin"
    path.write_bytes(payload)
    return PreparedImage(
        image_id=f"sd300a_00001000_plain_{name}",
        local_path=path.resolve(),
        effective_ppi=500,
        media_type="application/octet-stream",
        expected_sha256=hashlib.sha256(payload).hexdigest(),
        checksum_status=ChecksumStatus.NOT_VERIFIED,
        preparation_profile_id="identity_png_v1",
        preparation_hash=hashlib.sha256(f"prep-{name}".encode()).hexdigest(),
    )


def pair(sandbox, left_payload=b"left ridges", right_payload=b"right ridges"):
    return (
        image(sandbox["inputs"], "left", left_payload),
        image(sandbox["inputs"], "right", right_payload),
    )


# ------------------------------------------------------------------ success


def test_two_extractions_and_a_match_produce_a_score(tmp_path, sandbox, context):
    left, right = pair(sandbox)
    result = adapter(tmp_path).compare(left, right, context)

    assert result.status is ExecutionStatus.SUCCESS
    assert result.raw_score is not None
    assert 0.0 <= result.raw_score <= 100.0
    assert result.score_direction is ScoreDirection.HIGHER_IS_BETTER
    assert result.failure is None


def test_the_intermediate_files_are_written_and_stay_in_the_working_directory(
    tmp_path, sandbox, context
):
    left, right = pair(sandbox)
    adapter(tmp_path).compare(left, right, context)

    names = {path.name for path in sandbox["working"].rglob("*") if path.is_file()}
    assert {"left-input.bin", "right-input.bin", "left-template.xyt",
            "right-template.xyt"} <= names
    assert not any(path.is_file() for path in sandbox["artifacts"].rglob("*"))


def test_no_intermediate_file_name_carries_research_meaning(tmp_path, sandbox, context):
    left, right = pair(sandbox)
    adapter(tmp_path).compare(left, right, context)
    for path in sandbox["working"].rglob("*"):
        lowered = path.name.lower()
        for token in ("subject", "finger", "pair", "genuine", "mated"):
            assert token not in lowered, path.name


def test_the_route_records_its_timing_by_stage(tmp_path, sandbox, context):
    left, right = pair(sandbox)
    result = adapter(tmp_path).compare(left, right, context)
    assert set(result.timing_components_ms) == {
        "input_conversion",
        "left_extraction",
        "right_extraction",
        "matching",
    }


def test_the_result_proves_both_sides_were_extracted_independently(
    tmp_path, sandbox, context
):
    left, right = pair(sandbox)
    metadata = adapter(tmp_path).compare(left, right, context).metadata
    assert metadata["extraction_policy"] == "independent_both_sides"
    assert metadata["extraction_count"] == "2"
    assert metadata["template_cache"] == "disabled"
    assert metadata["template_persistence"] == "disabled"


def test_a_self_comparison_still_extracts_twice(tmp_path, sandbox, context):
    """Both sides are the same file, and both are extracted (docs/adr/0035)."""
    left, _ = pair(sandbox)
    result = adapter(tmp_path).compare(left, left, context)

    assert result.status is ExecutionStatus.SUCCESS
    assert result.metadata["extraction_count"] == "2"
    templates = {
        path.name
        for path in sandbox["working"].rglob("*")
        if path.name.endswith(".xyt")
    }
    assert templates == {"left-template.xyt", "right-template.xyt"}


def test_the_route_is_deterministic(tmp_path, sandbox, context):
    left, right = pair(sandbox)
    instance = adapter(tmp_path)
    first = instance.compare(left, right, context)
    second = instance.compare(left, right, context)
    assert first.raw_score == second.raw_score


def test_the_descriptor_names_both_halves_of_the_route(tmp_path):
    descriptor = adapter(tmp_path).descriptor
    metadata = dict(descriptor.metadata)
    assert metadata["pipeline_kind"] == "extract_then_match"
    assert metadata["extractor_id"] != metadata["matcher_id"]
    assert descriptor.adapter_id == ADAPTER_ID


# ------------------------------------------------------------------ failures


@pytest.mark.parametrize("side", ["left", "right"])
def test_an_extraction_failure_maps_to_the_extraction_stage(
    tmp_path, sandbox, context, side
):
    marker = b"FPBENCH-FIXTURE:EXTRACT-FAIL"
    payloads = {"left": b"left ridges", "right": b"right ridges"}
    payloads[side] = marker
    left, right = pair(sandbox, payloads["left"], payloads["right"])

    result = adapter(tmp_path).compare(left, right, context)

    assert result.status is ExecutionStatus.FAILURE
    assert result.raw_score is None
    assert result.failure.code is FailureCode.TEMPLATE_EXTRACTION_FAILED
    assert result.failure.stage is FailureStage.EXTRACTION
    assert result.failure.details["side"] == side


def test_a_matching_failure_maps_to_the_matching_stage(tmp_path, sandbox, context):
    left, right = pair(sandbox, b"FPBENCH-FIXTURE:MATCH-FAIL", b"right ridges")
    result = adapter(tmp_path).compare(left, right, context)

    assert result.failure.code is FailureCode.MATCHING_FAILED
    assert result.failure.stage is FailureStage.MATCHING


def test_a_matcher_that_prints_no_number_is_no_score_and_never_zero(
    tmp_path, sandbox, context
):
    """A comparison that produced no number did not score badly; it did not score."""
    left, right = pair(sandbox, b"FPBENCH-FIXTURE:MATCH-NOSCORE", b"right ridges")
    result = adapter(tmp_path).compare(left, right, context)

    assert result.failure.code is FailureCode.NO_SCORE
    assert result.failure.stage is FailureStage.MATCHING
    assert result.raw_score is None


def test_a_crashing_extractor_is_a_process_crash(tmp_path, sandbox, context):
    left, right = pair(sandbox, b"FPBENCH-FIXTURE:EXTRACT-CRASH", b"right ridges")
    result = adapter(tmp_path).compare(left, right, context)

    assert result.failure.code is FailureCode.PROCESS_CRASHED
    assert result.failure.stage is FailureStage.ADAPTER


def test_a_crashing_matcher_is_a_process_crash_in_matching(tmp_path, sandbox, context):
    left, right = pair(sandbox, b"FPBENCH-FIXTURE:MATCH-CRASH", b"right ridges")
    result = adapter(tmp_path).compare(left, right, context)

    assert result.failure.code is FailureCode.PROCESS_CRASHED
    assert result.failure.stage is FailureStage.MATCHING


def test_a_hanging_extractor_is_a_timeout(tmp_path, sandbox):
    left, right = pair(
        {"inputs": sandbox["inputs"]}, b"FPBENCH-FIXTURE:EXTRACT-HANG", b"right"
    )
    context = ComparisonContext(
        run_id=RUN_ID,
        job_id=JOB_ID,
        attempt=1,
        working_directory=sandbox["working"],
        artifact_directory=sandbox["artifacts"],
        timeout_seconds=2.0,
        deterministic_seed=0,
    )
    result = adapter(tmp_path).compare(left, right, context)

    assert result.failure.code is FailureCode.TIMEOUT
    assert result.failure.stage is FailureStage.TIMEOUT
    assert result.failure.retryable


def test_a_hanging_matcher_is_a_timeout(tmp_path, sandbox):
    left, right = pair(
        {"inputs": sandbox["inputs"]}, b"FPBENCH-FIXTURE:MATCH-HANG", b"right"
    )
    context = ComparisonContext(
        run_id=RUN_ID,
        job_id=JOB_ID,
        attempt=1,
        working_directory=sandbox["working"],
        artifact_directory=sandbox["artifacts"],
        timeout_seconds=3.0,
        deterministic_seed=0,
    )
    result = adapter(tmp_path).compare(left, right, context)
    assert result.failure.code is FailureCode.TIMEOUT


def test_a_missing_template_is_an_extraction_failure(tmp_path, sandbox, context):
    """The tool claimed success and produced nothing; the file decides."""
    left, right = pair(sandbox, b"FPBENCH-FIXTURE:EXTRACT-MISSING", b"right ridges")
    result = adapter(tmp_path).compare(left, right, context)

    assert result.failure.code is FailureCode.TEMPLATE_EXTRACTION_FAILED
    assert result.failure.details["reason"] == "template_missing_or_empty"


def test_an_empty_template_is_an_extraction_failure(tmp_path, sandbox, context):
    left, right = pair(sandbox, b"FPBENCH-FIXTURE:EXTRACT-EMPTY", b"right ridges")
    result = adapter(tmp_path).compare(left, right, context)
    assert result.failure.code is FailureCode.TEMPLATE_EXTRACTION_FAILED


def test_a_very_noisy_tool_does_not_bloat_the_result(tmp_path, sandbox, context):
    left, right = pair(sandbox, b"FPBENCH-FIXTURE:EXTRACT-NOISY", b"right ridges")
    result = adapter(tmp_path).compare(left, right, context)

    assert result.status is ExecutionStatus.SUCCESS
    for value in result.metadata.values():
        assert len(value) < 200


def test_a_very_noisy_failure_keeps_its_excerpt_short(tmp_path, sandbox, context):
    left, right = pair(
        sandbox, b"FPBENCH-FIXTURE:MATCH-NOISY FPBENCH-FIXTURE:MATCH-FAIL", b"right"
    )
    result = adapter(tmp_path).compare(left, right, context)

    assert result.failure.code is FailureCode.MATCHING_FAILED
    assert len(result.failure.details.get("stderr_excerpt", "")) <= 400


def test_no_failure_ever_carries_a_score(tmp_path, sandbox, context):
    """Section 59: not 0, not -1, not NaN — no score at all."""
    for marker in (
        b"FPBENCH-FIXTURE:EXTRACT-FAIL",
        b"FPBENCH-FIXTURE:MATCH-FAIL",
        b"FPBENCH-FIXTURE:MATCH-NOSCORE",
        b"FPBENCH-FIXTURE:EXTRACT-CRASH",
    ):
        left, right = pair(sandbox, marker, b"right ridges")
        result = adapter(tmp_path).compare(left, right, context)
        assert result.status is ExecutionStatus.FAILURE
        assert result.raw_score is None


# --------------------------------------------------------------- environment


def test_a_missing_tool_is_unavailable_and_not_an_exception(tmp_path):
    extractor, matcher = tools(tmp_path)
    matcher.unlink()
    instance = SyntheticTwoStageCliAdapter(
        SyntheticTwoStageConfig(
            extractor=extractor, matcher=matcher,
            interpreter=Path(sys.executable).resolve(),
        )
    )
    report = instance.validate_environment()
    assert report.status is EnvironmentStatus.UNAVAILABLE
    assert "matcher" in report.message


def test_a_ready_environment_names_its_version(tmp_path):
    report = adapter(tmp_path).validate_environment()
    assert report.status is EnvironmentStatus.READY
    assert report.implementation_version


def test_the_environment_message_carries_no_directory(tmp_path):
    extractor, matcher = tools(tmp_path)
    matcher.unlink()
    instance = SyntheticTwoStageCliAdapter(
        SyntheticTwoStageConfig(
            extractor=extractor, matcher=matcher,
            interpreter=Path(sys.executable).resolve(),
        )
    )
    assert str(tmp_path) not in (instance.validate_environment().message or "")


# ------------------------------------------------------------- runtime drift


def test_a_changed_tool_during_a_research_run_is_drift_not_a_failed_pair(
    tmp_path, sandbox, context
):
    """Section 65: it invalidates the run, so it is raised rather than recorded."""
    instance = adapter(tmp_path, research_mode=True)
    left, right = pair(sandbox)
    assert instance.compare(left, right, context).status is ExecutionStatus.SUCCESS

    matcher = instance.config.matcher
    matcher.write_bytes(matcher.read_bytes() + b"\n# rebuilt\n")

    with pytest.raises(RuntimeDriftError):
        instance.compare(left, right, context)


def test_changing_either_tool_is_noticed(tmp_path, sandbox, context):
    for role in (EXTRACTOR_ROLE, MATCHER_ROLE):
        instance = adapter(tmp_path / role, research_mode=True)
        target = instance.config.runtime_assets()[role]
        target.write_bytes(target.read_bytes() + b"\n# rebuilt\n")
        left, right = pair(sandbox)
        with pytest.raises(RuntimeDriftError):
            instance.compare(left, right, context)


def test_outside_research_mode_nothing_is_pinned(tmp_path, sandbox, context):
    instance = adapter(tmp_path)
    matcher = instance.config.matcher
    matcher.write_bytes(matcher.read_bytes() + b"\n# rebuilt\n")
    left, right = pair(sandbox)
    assert instance.compare(left, right, context).status is ExecutionStatus.SUCCESS


# ------------------------------------------------------------------- config


def test_a_relative_tool_path_is_refused():
    with pytest.raises(ConfigurationError, match="absolute path"):
        SyntheticTwoStageConfig(
            extractor=Path("extractor.py"), matcher=MATCHER.resolve()
        )


def test_one_file_cannot_be_both_stages():
    with pytest.raises(ConfigurationError, match="two different files"):
        SyntheticTwoStageConfig(extractor=EXTRACTOR.resolve(), matcher=EXTRACTOR.resolve())


def test_a_quoted_boolean_is_refused():
    with pytest.raises(ConfigurationError, match="YAML boolean"):
        SyntheticTwoStageConfig.from_mapping(
            {
                "extractor": str(EXTRACTOR.resolve()),
                "matcher": str(MATCHER.resolve()),
                "research_mode": "false",
            }
        )


def test_an_unknown_configuration_key_is_refused():
    with pytest.raises(ConfigurationError, match="unknown"):
        SyntheticTwoStageConfig.from_mapping(
            {
                "extractor": str(EXTRACTOR.resolve()),
                "matcher": str(MATCHER.resolve()),
                "threshold": 40,
            }
        )


# ---------------------------------------------------------------- isolation


def test_the_adapter_cannot_name_a_file_outside_its_workspace(sandbox, context):
    """The workspace helper is what stops it, and it does stop it."""
    from fpbench.adapters.support.workspace import AdapterJobWorkspace

    workspace = AdapterJobWorkspace.from_context(context)
    with pytest.raises(WorkspaceContainmentError):
        workspace.work_path("../escaped-template.xyt")


def test_the_source_images_are_not_modified(tmp_path, sandbox, context):
    left, right = pair(sandbox)
    before = {
        path: path.read_bytes() for path in sandbox["inputs"].iterdir() if path.is_file()
    }
    adapter(tmp_path).compare(left, right, context)
    after = {
        path: path.read_bytes() for path in sandbox["inputs"].iterdir() if path.is_file()
    }
    assert after == before


def test_nothing_is_written_outside_the_two_job_directories(tmp_path, sandbox, context):
    left, right = pair(sandbox)
    instance = adapter(tmp_path)
    # Snapshot after construction: copying the tools into place is the test's
    # doing, not the adapter's.
    before = {p for p in sandbox["root"].rglob("*") if p.is_file()}
    instance.compare(left, right, context)
    created = {p for p in sandbox["root"].rglob("*") if p.is_file()} - before
    for path in created:
        assert path.is_relative_to(sandbox["working"]) or path.is_relative_to(
            sandbox["artifacts"]
        ), path


def test_the_adapter_is_not_in_the_public_registry():
    """A fixture is not an algorithm; it must not appear where one would."""
    from fpbench.adapters.registry import registered_adapters

    assert ADAPTER_ID not in registered_adapters()
