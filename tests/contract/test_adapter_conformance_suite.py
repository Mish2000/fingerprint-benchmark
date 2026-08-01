"""The conformance suite, run against the two adapters that can run anywhere.

``test_adapter_contract.py`` parametrises over the registry, which covers the
adapters that are registered and constructible from nothing. This file covers the
two cases it cannot: the reusable suite itself, and an adapter that is
deliberately unregistered because it is a fixture rather than an algorithm.

The point of running the same checks over the dummy matcher and over a
two-executable pipeline is that they are the same checks. If the two-stage route
needed a weakened version of any of them, the contract would not actually support
it (spec sections 51 to 53).
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

from fpbench.adapters.conformance import (
    AdapterConformanceCase,
    ConformanceFailure,
    ConformanceReport,
    run_adapter_conformance,
)
from fpbench.adapters.support.workspace import AdapterJobWorkspace
from fpbench.adapters.dummy.adapter import ALGORITHM_ID as DUMMY_ID
from fpbench.adapters.dummy.adapter import DummyShaAdapter
from fpbench.adapters.synthetic_two_stage import (
    ADAPTER_ID as TWO_STAGE_ID,
    SyntheticTwoStageCliAdapter,
)
from fpbench.core.enums import ChecksumStatus, ScoreDirection
from fpbench.core.execution_models import ArtifactReference, PreparedImage, RawMatchResult
from synthetic_ridges import whorl_png

pytestmark = pytest.mark.adapter_contract

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "two_stage_cli"

_SEEDS = {"left": 1, "right": 6}


@pytest.fixture
def sandbox(tmp_path: Path) -> dict[str, Path]:
    working = tmp_path / "work" / "run_abc123def456" / "job_0123456789abcdef"
    artifacts = tmp_path / "artifacts" / "run_abc123def456" / "job_0123456789abcdef"
    inputs = tmp_path / "inputs"
    for directory in (working, artifacts, inputs):
        directory.mkdir(parents=True)
    return {"root": tmp_path, "working": working, "artifacts": artifacts,
            "inputs": inputs}


def prepared(directory: Path, name: str) -> PreparedImage:
    """A real, decodable PNG, so an image-reading adapter is actually exercised.

    The synthetic ridges are not fingerprints; see
    ``tests/fixtures/sourceafis/README.md``.
    """
    payload = whorl_png(500, _SEEDS[name])
    path = directory / f"{name}.png"
    path.write_bytes(payload)
    return PreparedImage(
        image_id=f"sd300a_00001000_plain_{name}",
        local_path=path.resolve(),
        effective_ppi=500,
        media_type="image/png",
        expected_sha256=hashlib.sha256(payload).hexdigest(),
        checksum_status=ChecksumStatus.NOT_VERIFIED,
        preparation_profile_id="identity_png_v1",
        preparation_hash=hashlib.sha256(f"prep-{name}".encode()).hexdigest(),
    )


def run(case: AdapterConformanceCase, sandbox) -> ConformanceReport:
    return run_adapter_conformance(
        case,
        working_directory=sandbox["working"],
        artifact_directory=sandbox["artifacts"],
        sandbox_root=sandbox["root"],
    )


# ------------------------------------------------------------- dummy matcher


def dummy_case(sandbox) -> AdapterConformanceCase:
    return AdapterConformanceCase(
        adapter_id=DUMMY_ID,
        factory=lambda config: DummyShaAdapter.from_config(config),
        ready_config={},
        # The dummy matcher's only dependency is the standard library, so it can
        # never be unavailable. Its "unavailable" configuration is therefore the
        # same one, and the suite reports the check as not applicable rather than
        # pretending otherwise.
        unavailable_config={},
        left_image=prepared(sandbox["inputs"], "left"),
        right_image=prepared(sandbox["inputs"], "right"),
        expected_score_direction=ScoreDirection.HIGHER_IS_BETTER,
    )


def test_the_dummy_matcher_passes_everything_except_the_unavailable_case(sandbox):
    """It has no dependency to be missing, and that is the only finding."""
    report = run(dummy_case(sandbox), sandbox)
    failed = {finding.check for finding in report.failures}
    assert failed == {"environment_is_unavailable_when_a_dependency_is_missing"}


# ----------------------------------------------------------- two-stage route


def two_stage_case(sandbox, tmp_path: Path) -> AdapterConformanceCase:
    tools = tmp_path / "tools"
    tools.mkdir(parents=True, exist_ok=True)
    extractor = tools / "extractor.py"
    matcher = tools / "matcher.py"
    extractor.write_bytes((FIXTURES / "extractor.py").read_bytes())
    matcher.write_bytes((FIXTURES / "matcher.py").read_bytes())

    ready = {
        "extractor": str(extractor),
        "matcher": str(matcher),
        "interpreter": str(Path(sys.executable).resolve()),
    }
    return AdapterConformanceCase(
        adapter_id=TWO_STAGE_ID,
        factory=lambda config: SyntheticTwoStageCliAdapter.from_config(config),
        ready_config=ready,
        unavailable_config={**ready, "matcher": str(tools / "absent-matcher.py")},
        left_image=prepared(sandbox["inputs"], "left"),
        right_image=prepared(sandbox["inputs"], "right"),
        expected_score_direction=ScoreDirection.HIGHER_IS_BETTER,
        # A fixture, not an algorithm: it is deliberately absent from the public
        # registry, and the suite is told so rather than discovering it.
        registered=False,
    )


def test_a_two_stage_route_passes_the_same_suite(sandbox, tmp_path):
    """The whole of stage 7A, in one assertion (docs/adr/0043)."""
    report = run(two_stage_case(sandbox, tmp_path), sandbox)
    report.require_clean()


@pytest.mark.parametrize(
    "check",
    [
        "descriptor_identifiers_are_usable",
        "descriptor_declares_versions",
        "contract_version_is_supported",
        "descriptor_is_stable",
        "descriptor_declares_expected_score_direction",
        "probe_side_is_left",
        "environment_is_ready_when_dependencies_are_present",
        "missing_dependency_is_not_an_exception",
        "environment_is_unavailable_when_a_dependency_is_missing",
        "compare_does_not_raise",
        "compare_returns_a_raw_match_result",
        "result_score_direction_matches_the_descriptor",
        "outcome_shape_is_valid",
        "result_metadata_is_string_to_string",
        "result_metadata_carries_no_answer",
        "result_metadata_holds_no_absolute_path",
        "artifacts_are_verifiable",
        "compare_does_not_modify_its_inputs",
        "compare_writes_only_inside_its_directories",
        "deterministic_adapter_repeats_itself",
        "both_directions_are_separate_calls",
    ],
)
def test_every_mandatory_check_actually_ran(sandbox, tmp_path, check):
    """A suite that quietly skipped a check would prove nothing."""
    report = run(two_stage_case(sandbox, tmp_path), sandbox)
    finding = report.finding(check)
    assert finding is not None, f"{check} was never evaluated"
    assert finding.passed, finding.detail


# ------------------------------------------------- the suite can actually fail


class _StrayWriter(DummyShaAdapter):
    """Writes outside its allotted directories. Exists to fire the check."""

    def __init__(self, target: Path) -> None:
        super().__init__()
        self._target = Path(target)

    def compare(self, left, right, context):
        self._target.parent.mkdir(parents=True, exist_ok=True)
        self._target.write_text("I should not be here", encoding="utf-8")
        return super().compare(left, right, context)


def test_the_containment_check_can_fail(sandbox):
    """A check that never fires is not a check."""
    stray = sandbox["root"] / "elsewhere" / "leak.txt"
    case = AdapterConformanceCase(
        adapter_id=DUMMY_ID,
        factory=lambda config: _StrayWriter(stray),
        ready_config={},
        unavailable_config={},
        left_image=prepared(sandbox["inputs"], "left"),
        right_image=prepared(sandbox["inputs"], "right"),
        expected_score_direction=ScoreDirection.HIGHER_IS_BETTER,
    )
    report = run(case, sandbox)
    finding = report.finding("compare_writes_only_inside_its_directories")
    assert finding is not None and not finding.passed


class _Talkative(DummyShaAdapter):
    """Records a decision it was never entitled to make."""

    def compare(self, left, right, context):
        from fpbench.core.execution_models import RawMatchResult
        from fpbench.core.enums import ScoreDirection as Direction

        return RawMatchResult.success(
            raw_score=1.0,
            score_direction=Direction.HIGHER_IS_BETTER,
            metadata={"threshold": "40", "decision": "match"},
        )


def test_the_forbidden_metadata_check_can_fail(sandbox):
    case = AdapterConformanceCase(
        adapter_id=DUMMY_ID,
        factory=lambda config: _Talkative(),
        ready_config={},
        unavailable_config={},
        left_image=prepared(sandbox["inputs"], "left"),
        right_image=prepared(sandbox["inputs"], "right"),
        expected_score_direction=ScoreDirection.HIGHER_IS_BETTER,
    )
    report = run(case, sandbox)
    finding = report.finding("result_metadata_carries_no_answer")
    assert finding is not None and not finding.passed
    assert "threshold" in finding.detail


class _RaisingAdapter(DummyShaAdapter):
    def compare(self, left, right, context):
        raise RuntimeError("synthetic compare failure")


def test_a_compare_exception_is_reported_instead_of_escaping(sandbox):
    case = _dummy_variant_case(sandbox, lambda: _RaisingAdapter())
    report = run(case, sandbox)
    finding = report.finding("compare_does_not_raise")
    assert finding is not None and not finding.passed
    assert "RuntimeError" in finding.detail


class _FixedArtifactAdapter(DummyShaAdapter):
    def compare(self, left, right, context):
        workspace = AdapterJobWorkspace.from_context(context)
        source = workspace.work_path("fixed-output.txt")
        source.write_bytes(b"fixed")
        artifact = workspace.publish_artifact(
            artifact_id="fixed_output",
            kind="output",
            source=source,
            relative_name="fixed-output.txt",
        )
        result = super().compare(left, right, context)
        return RawMatchResult.success(
            raw_score=float(result.raw_score),
            score_direction=result.score_direction,
            artifacts=(artifact,),
        )


def test_each_compare_gets_fresh_directories_for_fixed_artifact_names(sandbox):
    report = run(_dummy_variant_case(sandbox, lambda: _FixedArtifactAdapter()), sandbox)
    assert report.finding("compare_does_not_raise").passed
    assert report.finding("artifacts_are_verifiable").passed
    assert len(list(sandbox["artifacts"].rglob("fixed-output.txt"))) == 3


class _SymlinkArtifactAdapter(DummyShaAdapter):
    def compare(self, left, right, context):
        directory = Path(context.artifact_directory)
        target = directory / "real-output.txt"
        target.write_bytes(b"payload")
        link = directory / "linked-output.txt"
        link.symlink_to(target)
        reference = ArtifactReference(
            artifact_id="linked_output",
            kind="output",
            relative_path=link.name,
            sha256=hashlib.sha256(b"payload").hexdigest(),
            size_bytes=len(b"payload"),
        )
        return RawMatchResult.success(
            raw_score=1.0,
            score_direction=ScoreDirection.HIGHER_IS_BETTER,
            artifacts=(reference,),
        )


def test_a_symlink_artifact_is_not_treated_as_a_regular_file(sandbox):
    probe = sandbox["root"] / "symlink-probe"
    target = sandbox["root"] / "symlink-target"
    target.write_bytes(b"x")
    try:
        probe.symlink_to(target)
        probe.unlink()
    except (OSError, NotImplementedError):  # pragma: no cover - platform policy
        pytest.skip("this platform will not create symlinks")
    report = run(_dummy_variant_case(sandbox, lambda: _SymlinkArtifactAdapter()), sandbox)
    finding = report.finding("artifacts_are_verifiable")
    assert finding is not None and not finding.passed


class _SecondCallMutator(DummyShaAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def compare(self, left, right, context):
        self.calls += 1
        result = super().compare(left, right, context)
        if self.calls == 2:
            Path(left.local_path).write_bytes(b"mutated-on-second-call")
        return result


def test_input_mutation_on_the_second_compare_is_detected(sandbox):
    report = run(_dummy_variant_case(sandbox, lambda: _SecondCallMutator()), sandbox)
    finding = report.finding("compare_does_not_modify_its_inputs")
    assert finding is not None and not finding.passed
    assert "forward-2" in finding.detail


def _dummy_variant_case(sandbox, build) -> AdapterConformanceCase:
    return AdapterConformanceCase(
        adapter_id=DUMMY_ID,
        factory=lambda config: build(),
        ready_config={},
        unavailable_config={},
        left_image=prepared(sandbox["inputs"], "left"),
        right_image=prepared(sandbox["inputs"], "right"),
        expected_score_direction=ScoreDirection.HIGHER_IS_BETTER,
    )


def test_require_clean_raises_with_every_failure_named(sandbox):
    report = run(dummy_case(sandbox), sandbox)
    with pytest.raises(ConformanceFailure, match="environment_is_unavailable"):
        report.require_clean()


# ------------------------------------------------------------ the real thing


@pytest.mark.sourceafis
def test_sourceafis_passes_the_same_suite(sandbox, tmp_path):
    """The suite is only worth having if the real adapter satisfies it too."""
    from sourceafis_support import require_bridge

    from fpbench.adapters.sourceafis_java.adapter import (
        ADAPTER_ID as SOURCEAFIS_ID,
        SourceAfisJavaAdapter,
    )

    require_bridge()
    case = AdapterConformanceCase(
        adapter_id=SOURCEAFIS_ID,
        factory=lambda config: SourceAfisJavaAdapter.from_config(config),
        ready_config={},
        unavailable_config={"bridge_jar": str(tmp_path / "absent-bridge.jar")},
        left_image=prepared(sandbox["inputs"], "left"),
        right_image=prepared(sandbox["inputs"], "right"),
        expected_score_direction=ScoreDirection.HIGHER_IS_BETTER,
        # SourceAFIS stores no template and no minutiae file, so a result
        # carrying either would mean the adapter changed underneath the results.
        additional_forbidden_metadata=("template", "minutiae"),
    )
    run(case, sandbox).require_clean()


def test_the_suite_imports_no_test_framework():
    """It is product code an adapter author can run, not a pytest file."""
    import ast

    from fpbench.adapters import conformance

    tree = ast.parse(Path(conformance.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not any(module.startswith("pytest") for module in imported)
