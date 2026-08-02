"""The NBIS adapter against the same suite every adapter has to pass.

``fpbench.adapters.conformance`` is the checklist stage 7A wrote for exactly this
moment: an adapter that needs two executables and a build manifest materialised
before it can run cannot be exercised by the registry-driven suite, so it is
handed to the reusable one instead (spec section 48).

The suite is run twice. Here, against stand-in tools, so it runs on any machine
with no NBIS and no network. And in ``tests/integration/test_nbis_upstream.py``,
against a real certified build — because a suite the real adapter has never
satisfied proves nothing about the real adapter.

The directional golden is the one adapter-specific check the suite asks for. The
generic half cannot detect silent input sorting, because a symmetric matcher may
legitimately return the same score both ways. This route can prove it another
way: the two sides' minutiae counts have to *swap* when the sides swap, and no
amount of internal reordering produces that unless the two calls really were
different calls (spec section 44).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fpbench.adapters.conformance import (
    AdapterConformanceCase,
    ConformanceReport,
    run_adapter_conformance,
)
from fpbench.adapters.nbis.adapter import ADAPTER_ID, NbisAdapter
from fpbench.core.enums import ExecutionStatus, ScoreDirection
from nbisworld import (
    build_stand_in,
    certify_host,
    directional_golden,
    gray8_png,
    job_directories,
    prepared_image,
)

pytestmark = [pytest.mark.nbis_contract, pytest.mark.adapter_contract]

#: Two different synthetic rasters, so the two sides are genuinely two sides.
SEEDS = {"left": 1, "right": 6}


def prepared(directory: Path, name: str):
    """A real, decodable 500 ppi greyscale PNG. Not a fingerprint."""
    return prepared_image(
        Path(directory) / f"{name}.png",
        gray8_png(SEEDS[name]),
        image_id=f"sd300a_00001000_plain_{name}",
    )


@pytest.fixture
def sandbox(tmp_path: Path) -> dict[str, Path]:
    working, artifacts = job_directories(tmp_path)
    inputs = tmp_path / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    return {
        "root": tmp_path,
        "working": working,
        "artifacts": artifacts,
        "inputs": inputs,
    }


def nbis_case(build, sandbox, tmp_path) -> AdapterConformanceCase:
    ready = {
        "mindtct_executable": str(build.mindtct),
        "bozorth3_executable": str(build.bozorth3),
        "build_manifest": str(build.manifest_path),
    }
    return AdapterConformanceCase(
        adapter_id=ADAPTER_ID,
        factory=lambda config: NbisAdapter.from_config(config),
        ready_config=ready,
        unavailable_config={
            **ready,
            "mindtct_executable": str(tmp_path / "absent" / "mindtct"),
        },
        left_image=prepared(sandbox["inputs"], "left"),
        right_image=prepared(sandbox["inputs"], "right"),
        expected_score_direction=ScoreDirection.HIGHER_IS_BETTER,
        # This route publishes no template, no minutiae file and no XYT, so a
        # result carrying one would mean the adapter changed underneath the
        # results (docs/adr/0050).
        additional_forbidden_metadata=("template", "minutiae", "xyt", "score"),
        directional_golden=directional_golden,
    )


def run(case, sandbox) -> ConformanceReport:
    return run_adapter_conformance(
        case,
        working_directory=sandbox["working"],
        artifact_directory=sandbox["artifacts"],
        sandbox_root=sandbox["root"],
    )


@pytest.fixture
def build(tmp_path, monkeypatch):
    certify_host(monkeypatch)
    return build_stand_in(tmp_path / "build")


# ------------------------------------------------------------------- the suite


def test_the_nbis_adapter_passes_the_whole_suite(build, sandbox, tmp_path):
    run(nbis_case(build, sandbox, tmp_path), sandbox).require_clean()


@pytest.mark.parametrize(
    "check",
    [
        "factory_returns_an_adapter",
        "descriptor_identifiers_are_usable",
        "descriptor_declares_versions",
        "contract_version_is_supported",
        "descriptor_is_stable",
        "registry_id_matches_descriptor",
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
def test_every_mandatory_check_actually_ran(build, sandbox, tmp_path, check):
    """A suite that quietly skipped a check would prove nothing."""
    report = run(nbis_case(build, sandbox, tmp_path), sandbox)
    finding = report.finding(check)
    assert finding is not None, f"{check} was never evaluated"
    assert finding.passed, finding.detail


def test_the_adapter_is_resolvable_through_the_registry():
    from fpbench.adapters.registry import registered_adapters

    assert ADAPTER_ID in registered_adapters()


def test_the_two_probe_images_are_actually_different(build, sandbox, tmp_path):
    """Otherwise the directional golden would hold vacuously."""
    from nbisworld import job_context

    adapter = build.adapter()
    result = adapter.compare(
        prepared(sandbox["inputs"], "left"),
        prepared(sandbox["inputs"], "right"),
        job_context(sandbox["working"], sandbox["artifacts"]),
    )
    assert result.status is ExecutionStatus.SUCCESS
    assert (
        result.metadata["left_minutiae_count"]
        != result.metadata["right_minutiae_count"]
    )


def test_each_comparison_gets_fresh_directories(build, sandbox, tmp_path):
    """Three invocations, the same intermediate names, and no collision."""
    report = run(nbis_case(build, sandbox, tmp_path), sandbox)
    assert report.finding("compare_does_not_raise").passed
    assert report.finding("artifacts_are_verifiable").passed
    assert list(sandbox["artifacts"].rglob("*.xyt")) == []


def test_the_suite_leaves_nothing_behind(build, sandbox, tmp_path):
    """Section 32, checked through the suite rather than through one call."""
    run(nbis_case(build, sandbox, tmp_path), sandbox)
    leftovers = [
        path
        for path in sandbox["working"].rglob("*")
        if path.is_file()
    ]
    assert leftovers == []
    assert [path for path in sandbox["artifacts"].rglob("*") if path.is_file()] == []


def test_a_directional_golden_that_cannot_hold_fails(build, sandbox, tmp_path):
    """The golden is only worth having if it can say no."""
    from dataclasses import replace

    case = replace(
        nbis_case(build, sandbox, tmp_path),
        directional_golden=lambda forward, reverse: False,
    )
    report = run(case, sandbox)
    finding = report.finding("both_directions_are_separate_calls")
    assert finding is not None and not finding.passed
