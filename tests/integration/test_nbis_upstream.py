"""Everything that is a claim about NBIS itself, checked against NBIS itself.

The rest of the NBIS suite runs against stand-ins, which is right for testing the
adapter's own contract and useless for testing NBIS's. These are the claims stage
7B rests on that only the real, certified build can settle:

* MINDTCT accepts an 8-bit greyscale PNG directly, and refuses everything else;
* a ``pHYs`` chunk changes nothing, so the 500 ppi default is what applies;
* the same image extracts to the same XYT, every time;
* the same pair of templates scores the same, every time;
* fewer than ten minutiae is a score of 0 and not a failure;
* the XYT the official build writes lies inside the ranges the parser enforces;
* NIST's own Test 5.0.0 suite passed on this build.

Every one of them is a **precondition of the stage**, not an observation about
it. If the PPI probe comes out differently, the route as designed does not exist
and the stage stops rather than the policy being written from memory
(docs/adr/0047, spec section 22).

**Nothing here is a fingerprint and no biometric conclusion follows.** The images
are procedurally generated warped ridges; what they establish is that a build
behaves the way this project assumed when it built a pipeline around it.

Run with a certified build present::

    python integrations/nbis/build.py fetch && ... build && ... test
    FPBENCH_NBIS_BUILD_DIR=build/nbis-5.0.0/<build-id> \\
        pytest -m nbis_upstream -q
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from fpbench.adapters.conformance import AdapterConformanceCase, run_adapter_conformance
from fpbench.adapters.nbis.adapter import (
    ADAPTER_ID,
    ALGORITHM_ID,
    VERSION_PROBES,
    NbisAdapter,
    version_probe,
)
from fpbench.adapters.nbis.build_manifest import (
    BUILD_MANIFEST_FILENAME,
    EXPECTED_PNG_PPI_POLICY,
    SUPPORTED_TARGETS,
    host_target,
    read_build_manifest,
    verify_build_manifest,
)
from fpbench.adapters.nbis.config import NbisConfig
from fpbench.adapters.nbis.xyt import (
    QUALITY_MAX,
    QUALITY_MIN,
    THETA_MAX,
    THETA_MIN,
    parse_xyt,
)
from fpbench.adapters.nbis.score import parse_bozorth3_score
from fpbench.adapters.support.process import ExternalCommand, run_external_command
from fpbench.core.enums import EnvironmentStatus, ExecutionStatus, ScoreDirection
from fpbench.core.serialization import to_plain
from nbisworld import (
    certified_build_directory,
    directional_golden,
    gray8_png,
    identity_preparer,
    job_context,
    job_directories,
    png_with_phys,
    prepared_image,
    ridge_payload,
    sealed_repository,
    upstream_build_available,
)

pytestmark = [
    pytest.mark.nbis_upstream,
    pytest.mark.upstream,
    pytest.mark.skipif(
        not upstream_build_available(),
        reason="no certified NBIS build; set FPBENCH_NBIS_BUILD_DIR",
    ),
]

#: How many repetitions the spec fixes for each determinism claim (section 19).
XYT_REPEATS = 20
SCORE_REPEATS = 50
COMPARISON_REPEATS = 20


# ------------------------------------------------------------------ fixtures


@pytest.fixture(scope="module")
def build() -> Path:
    directory = certified_build_directory()
    assert directory is not None
    return directory


@pytest.fixture(scope="module")
def mindtct(build) -> Path:
    return build / "bin" / "mindtct"


@pytest.fixture(scope="module")
def bozorth3(build) -> Path:
    return build / "bin" / "bozorth3"


@pytest.fixture(scope="module")
def manifest(build):
    return read_build_manifest(build / BUILD_MANIFEST_FILENAME)


@pytest.fixture
def adapter(build) -> NbisAdapter:
    return NbisAdapter(
        NbisConfig(
            mindtct_executable=build / "bin" / "mindtct",
            bozorth3_executable=build / "bin" / "bozorth3",
            build_manifest=build / BUILD_MANIFEST_FILENAME,
        )
    )


def run_tool(argv, directory: Path, timeout: float = 300.0):
    return run_external_command(
        ExternalCommand(
            argv=tuple(str(item) for item in argv),
            working_directory=Path(directory),
            containment_root=Path(directory),
            timeout_seconds=timeout,
        )
    )


def extract(mindtct: Path, image: Path, root: Path) -> Path:
    result = run_tool([mindtct, image, root], root.parent)
    assert result.exit_code == 0, result.stderr[-500:]
    template = root.with_name(f"{root.name}.xyt")
    assert template.is_file()
    return template


def write_xyt(path: Path, count: int) -> Path:
    """A synthetic template with exactly ``count`` well-formed minutiae."""
    lines = [f"{40 + index} {60 + index * 2} {(index * 17) % 360} 50" for index in range(count)]
    path.write_text(("\n".join(lines) + "\n") if lines else "", encoding="ascii")
    return path


# ------------------------------------------------------- the build itself


def test_the_build_is_certified_for_a_supported_platform(build, manifest):
    verify_build_manifest(
        manifest, mindtct=build / "bin" / "mindtct", bozorth3=build / "bin" / "bozorth3"
    )
    assert manifest.nbis_version == "5.0.0"
    assert manifest.target in SUPPORTED_TARGETS
    assert manifest.target == host_target()


def test_the_official_nist_tests_all_passed(manifest):
    """Section 40: every discovered relevant test ran, and none failed."""
    summary = manifest.official_test_summary
    assert summary.test_suite_version == "5.0.0"
    assert summary.discovered_tests > 0
    assert summary.executed_tests == summary.discovered_tests
    assert summary.failed_tests == 0
    assert summary.passed_tests == summary.executed_tests
    assert summary.is_accepted


def test_neither_tool_loads_a_forbidden_library(manifest):
    """Section 9: the bundle owns the code that produced the score."""
    for tool, libraries in manifest.dynamic_dependencies.items():
        for library in libraries:
            for forbidden in ("libpng", "libz.", "libfing", "libnbis"):
                assert forbidden not in library, f"{tool} loads {library}"


def test_the_standalone_verifier_agrees(build):
    import importlib.util
    import sys

    from nbisworld import NBIS_INTEGRATION_DIRECTORY

    spec = importlib.util.spec_from_file_location(
        "fpbench_nbis_verify_under_test", NBIS_INTEGRATION_DIRECTORY / "verify_build.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.verify(build)


def test_each_tool_answers_its_version_probe_as_the_manifest_recorded(
    mindtct, bozorth3, manifest
):
    assert version_probe(mindtct, VERSION_PROBES["mindtct"]) == (
        manifest.mindtct_version_output
    )
    assert version_probe(bozorth3, VERSION_PROBES["bozorth3"]) == (
        manifest.bozorth3_version_output
    )


def test_the_environment_is_ready(adapter):
    report = adapter.validate_environment()
    assert report.status is EnvironmentStatus.READY, report.message
    assert report.dependencies["nbis.version"] == "5.0.0"
    assert report.dependencies["nbis.png_ppi_policy"] == EXPECTED_PNG_PPI_POLICY


# ---------------------------------------------------------- PNG capability


def png(width: int, height: int, depth: int, colour: int, *, plte: bool = False) -> bytes:
    import struct
    import zlib

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body))
            + kind
            + body
            + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
        )

    raw = bytearray()
    per_pixel = {0: depth // 8, 2: 3 * (depth // 8), 3: 1}[colour]
    for _ in range(height):
        raw.append(0)
        raw += bytes(width * max(per_pixel, 1))
    parts = [
        b"\x89PNG\r\n\x1a\n",
        chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, depth, colour, 0, 0, 0)),
    ]
    if plte:
        parts.append(chunk(b"PLTE", b"".join(bytes((v, v, v)) for v in range(256))))
    parts.append(chunk(b"IDAT", zlib.compress(bytes(raw), 6)))
    parts.append(chunk(b"IEND", b""))
    return b"".join(parts)


def test_a_direct_gray8_png_is_accepted(mindtct, tmp_path):
    """Section 41: PNG support is an acceptance condition, with no WSQ fallback."""
    image = tmp_path / "gray8.png"
    image.write_bytes(gray8_png(1))
    template = extract(mindtct, image, tmp_path / "out")
    assert template.read_text("ascii") is not None


def test_a_png_without_a_phys_chunk_is_accepted(mindtct, tmp_path):
    payload = gray8_png(2)
    assert b"pHYs" not in payload
    image = tmp_path / "nophys.png"
    image.write_bytes(payload)
    extract(mindtct, image, tmp_path / "out")


@pytest.mark.parametrize(
    "name,payload_factory",
    [
        ("gray16", lambda: png(256, 256, 16, 0)),
        ("rgb8", lambda: png(256, 256, 8, 2)),
        ("indexed8", lambda: png(256, 256, 8, 3, plte=True)),
        ("corrupt", lambda: b"\x89PNG\r\n\x1a\nnot a valid PNG body"),
    ],
)
def test_a_png_this_route_forbids_is_refused_by_the_build(
    mindtct, tmp_path, name, payload_factory
):
    """The adapter refuses these before the subprocess; so does the build."""
    image = tmp_path / f"{name}.png"
    image.write_bytes(payload_factory())
    root = tmp_path / f"out-{name}"
    result = run_tool([mindtct, image, root], tmp_path)
    produced = root.with_name(f"{root.name}.xyt").is_file()
    assert not (result.exit_code == 0 and produced), (
        f"the build accepted a {name} PNG, which the input contract forbids"
    )


def test_the_extractor_does_not_modify_its_input(mindtct, tmp_path):
    payload = gray8_png(3)
    image = tmp_path / "input.png"
    image.write_bytes(payload)
    extract(mindtct, image, tmp_path / "out")
    assert image.read_bytes() == payload


def test_the_adapter_stages_its_input_byte_for_byte(adapter, tmp_path, monkeypatch):
    """Section 21: no re-encoding, no PGM, no WSQ, no conversion tool."""
    from fpbench.adapters.nbis import adapter as adapter_module
    from fpbench.adapters.nbis.adapter import LEFT_INPUT

    working, artifacts = job_directories(tmp_path)
    left = prepared_image(tmp_path / "inputs" / "left.png", gray8_png(1))
    right = prepared_image(
        tmp_path / "inputs" / "right.png",
        gray8_png(6),
        image_id="sd300a_00001000_plain_right",
    )
    staged: list[bytes] = []
    original = adapter_module.run_external_command

    def recording(command: ExternalCommand):
        candidate = command.working_directory / LEFT_INPUT
        if candidate.is_file():
            staged.append(candidate.read_bytes())
        return original(command)

    monkeypatch.setattr(adapter_module, "run_external_command", recording)
    adapter.compare(left, right, job_context(working, artifacts))
    assert staged and staged[0] == Path(left.local_path).read_bytes()


def test_no_wsq_or_pgm_is_ever_written(adapter, tmp_path):
    working, artifacts = job_directories(tmp_path)
    left = prepared_image(tmp_path / "inputs" / "left.png", gray8_png(1))
    right = prepared_image(
        tmp_path / "inputs" / "right.png",
        gray8_png(6),
        image_id="sd300a_00001000_plain_right",
    )
    adapter.compare(left, right, job_context(working, artifacts))
    for suffix in (".wsq", ".pgm", ".jpg", ".jpeg", ".an2"):
        assert list(tmp_path.rglob(f"*{suffix}")) == []


# --------------------------------------------------------------- PPI policy


def test_the_declared_resolution_changes_nothing(mindtct, tmp_path, manifest):
    """Section 22: measured on the build, never written from memory.

    Three PNGs with byte-identical pixel data and three different ``pHYs``
    declarations. If the extracted XYT differs, the 500-ppi-only route as
    designed does not exist and this stage stops here.
    """
    base = gray8_png(4)
    variants = {
        "phys500": png_with_phys(base, 500),
        "phys1000": png_with_phys(base, 1000),
        "nophys": base,
    }
    digests: dict[str, str] = {}
    for name, payload in variants.items():
        image = tmp_path / f"{name}.png"
        image.write_bytes(payload)
        template = extract(mindtct, image, tmp_path / f"out-{name}")
        digests[name] = hashlib.sha256(template.read_bytes()).hexdigest()

    assert len(set(digests.values())) == 1, (
        "MINDTCT's output depends on the declared resolution; the canonical-500 "
        "route is not what stage 7B assumed and the stage must stop (docs/adr/0047)"
    )
    assert manifest.png_ppi_policy == EXPECTED_PNG_PPI_POLICY


def test_the_three_probe_images_really_do_share_their_pixels(tmp_path):
    """Otherwise the probe above would prove nothing at all."""
    base = gray8_png(4)
    for payload in (png_with_phys(base, 500), png_with_phys(base, 1000), base):
        index = payload.find(b"IDAT")
        assert payload[index:] == base[base.find(b"IDAT") :]


# -------------------------------------------------------------- determinism


def test_the_same_image_extracts_to_the_same_xyt_every_time(mindtct, tmp_path):
    """Section 19: twenty times, byte for byte."""
    image = tmp_path / "input.png"
    image.write_bytes(gray8_png(5))
    digests = set()
    counts = set()
    for index in range(XYT_REPEATS):
        template = extract(mindtct, image, tmp_path / f"out-{index}")
        payload = template.read_bytes()
        digests.add(hashlib.sha256(payload).hexdigest())
        counts.add(len(parse_xyt(payload.decode("ascii"))))
    assert len(digests) == 1, "MINDTCT is not deterministic on this build"
    assert len(counts) == 1


def test_the_same_pair_of_templates_scores_the_same_every_time(
    mindtct, bozorth3, tmp_path
):
    """Section 19: fifty times, exactly."""
    left_image, right_image = tmp_path / "l.png", tmp_path / "r.png"
    left_image.write_bytes(gray8_png(1))
    right_image.write_bytes(gray8_png(6))
    left = extract(mindtct, left_image, tmp_path / "left")
    right = extract(mindtct, right_image, tmp_path / "right")

    scores = set()
    for _ in range(SCORE_REPEATS):
        result = run_tool([bozorth3, left, right], tmp_path)
        assert result.exit_code == 0, result.stderr[-500:]
        scores.add(parse_bozorth3_score(result.stdout))
    assert len(scores) == 1, "BOZORTH3 is not deterministic on this build"


def test_the_same_comparison_produces_the_same_result_every_time(adapter, tmp_path):
    """Section 19: twenty whole comparisons, compared field by field."""
    working, artifacts = job_directories(tmp_path)
    left = prepared_image(tmp_path / "inputs" / "left.png", gray8_png(1))
    right = prepared_image(
        tmp_path / "inputs" / "right.png",
        gray8_png(6),
        image_id="sd300a_00001000_plain_right",
    )
    observed = set()
    for _ in range(COMPARISON_REPEATS):
        result = adapter.compare(left, right, job_context(working, artifacts))
        observed.add(
            json.dumps(
                {
                    "status": result.status.value,
                    "score": result.raw_score,
                    "failure": to_plain(result.failure),
                    "metadata": dict(result.metadata),
                },
                sort_keys=True,
            )
        )
    assert len(observed) == 1, "the route is not deterministic on this build"


# --------------------------------------------------------- the XYT contract


def test_the_official_output_lies_inside_the_ranges_the_parser_enforces(
    mindtct, tmp_path
):
    """Section 27: the bounds are checked against the build, not remembered."""
    seen = 0
    for seed in range(1, 6):
        image = tmp_path / f"input-{seed}.png"
        image.write_bytes(gray8_png(seed))
        template = extract(mindtct, image, tmp_path / f"out-{seed}")
        payload = template.read_text("ascii")
        for line in payload.splitlines():
            if not line.strip():
                continue
            fields = line.split()
            assert len(fields) == 4, line
            x, y, theta, quality = (int(item) for item in fields)
            assert x >= 0 and y >= 0
            assert THETA_MIN <= theta <= THETA_MAX, line
            assert QUALITY_MIN <= quality <= QUALITY_MAX, line
            seen += 1
        # Parsed by the real parser too, with the raster bounds applied.
        parse_xyt(payload, image_width=250, image_height=250)
    assert seen > 0, "no minutiae were extracted from any probe image"


# ------------------------------------------------------------- score of zero


@pytest.mark.parametrize(
    "left_count,right_count",
    [(0, 0), (9, 9), (0, 20), (9, 20), (20, 9)],
    ids=["empty-empty", "nine-nine", "empty-full", "short-full", "full-short"],
)
def test_too_few_minutiae_scores_zero_rather_than_failing(
    bozorth3, tmp_path, left_count, right_count
):
    """Section 43: never NO_SCORE, never MATCHING_FAILED, never NON_MATCH."""
    left = write_xyt(tmp_path / f"left-{left_count}-{right_count}.xyt", left_count)
    right = write_xyt(tmp_path / f"right-{left_count}-{right_count}.xyt", right_count)
    result = run_tool([bozorth3, left, right], tmp_path)
    assert result.exit_code == 0, result.stderr[-500:]
    assert parse_bozorth3_score(result.stdout) == 0


def test_an_empty_template_reaches_the_adapter_as_a_score(adapter, tmp_path):
    """The whole path, not only the matcher: 0 is stored as a success."""
    working, artifacts = job_directories(tmp_path)
    blank = tmp_path / "inputs" / "blank.png"
    blank.parent.mkdir(parents=True, exist_ok=True)
    blank.write_bytes(png(256, 256, 8, 0))
    left = prepared_image(blank, blank.read_bytes())
    right = prepared_image(
        tmp_path / "inputs" / "right.png",
        gray8_png(6),
        image_id="sd300a_00001000_plain_right",
    )
    result = adapter.compare(left, right, job_context(working, artifacts))
    if result.status is ExecutionStatus.SUCCESS:
        assert result.raw_score == 0.0
    else:
        # A flat raster MINDTCT declines outright is also acceptable — what is
        # not acceptable is a score invented for it.
        assert result.raw_score is None


# ---------------------------------------------------------------- direction


def test_the_probe_and_the_gallery_are_not_interchangeable(
    mindtct, bozorth3, tmp_path, adapter
):
    """Section 44: prove the reverse order is a different call.

    BOZORTH3's scores are not necessarily symmetric, so a pair whose two
    directions differ is the strongest available proof. Where the two happen to
    agree, the sides' minutiae counts still have to swap — which no amount of
    internal reordering produces.
    """
    working, artifacts = job_directories(tmp_path)
    left = prepared_image(tmp_path / "inputs" / "left.png", gray8_png(1))
    right = prepared_image(
        tmp_path / "inputs" / "right.png",
        gray8_png(6),
        image_id="sd300a_00001000_plain_right",
    )
    forward = adapter.compare(left, right, job_context(working, artifacts))
    reverse = adapter.compare(right, left, job_context(working, artifacts))
    assert forward.status is reverse.status is ExecutionStatus.SUCCESS

    swapped = (
        forward.metadata["left_minutiae_count"]
        == reverse.metadata["right_minutiae_count"]
        and forward.metadata["right_minutiae_count"]
        == reverse.metadata["left_minutiae_count"]
    )
    assert swapped
    assert (
        forward.raw_score != reverse.raw_score
        or forward.metadata["left_minutiae_count"]
        != forward.metadata["right_minutiae_count"]
    ), "neither the score nor the counts distinguish the two directions"


def test_only_one_direction_is_ever_run(adapter, tmp_path, monkeypatch):
    from fpbench.adapters.nbis import adapter as adapter_module

    working, artifacts = job_directories(tmp_path)
    left = prepared_image(tmp_path / "inputs" / "left.png", gray8_png(1))
    right = prepared_image(
        tmp_path / "inputs" / "right.png",
        gray8_png(6),
        image_id="sd300a_00001000_plain_right",
    )
    seen: list[tuple[str, ...]] = []
    original = adapter_module.run_external_command

    def recording(command: ExternalCommand):
        seen.append(tuple(command.argv))
        return original(command)

    monkeypatch.setattr(adapter_module, "run_external_command", recording)
    adapter.compare(left, right, job_context(working, artifacts))
    matches = [argv for argv in seen if Path(argv[0]).stem == "bozorth3"]
    assert len(matches) == 1
    assert matches[0][1].endswith("left-nbis.xyt")
    assert matches[0][2].endswith("right-nbis.xyt")


# ---------------------------------------------------------- SELF, for real


def test_a_self_comparison_extracts_twice_on_the_real_build(
    adapter, tmp_path, monkeypatch
):
    """Section 45: the XYTs may be byte-identical; the work still happens twice."""
    from fpbench.adapters.nbis import adapter as adapter_module

    working, artifacts = job_directories(tmp_path)
    same = prepared_image(tmp_path / "inputs" / "same.png", gray8_png(1))
    seen: list[tuple[str, ...]] = []
    original = adapter_module.run_external_command

    def recording(command: ExternalCommand):
        seen.append(tuple(command.argv))
        return original(command)

    monkeypatch.setattr(adapter_module, "run_external_command", recording)
    result = adapter.compare(same, same, job_context(working, artifacts))
    extractions = [argv for argv in seen if Path(argv[0]).stem == "mindtct"]
    assert len(extractions) == 2
    assert {Path(argv[2]).name for argv in extractions} == {"left-nbis", "right-nbis"}
    assert result.metadata["extraction_count"] == "2"
    assert result.metadata["template_cache"] == "disabled"
    assert result.metadata["template_persistence"] == "disabled"


# ----------------------------------------------------------- the whole suite


def test_the_real_adapter_is_conformant(build, tmp_path):
    """Section 48, against NBIS rather than against a stand-in."""
    working, artifacts = job_directories(tmp_path)
    inputs = tmp_path / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    ready = {
        "mindtct_executable": str(build / "bin" / "mindtct"),
        "bozorth3_executable": str(build / "bin" / "bozorth3"),
        "build_manifest": str(build / BUILD_MANIFEST_FILENAME),
    }
    case = AdapterConformanceCase(
        adapter_id=ADAPTER_ID,
        factory=lambda config: NbisAdapter.from_config(config),
        ready_config=ready,
        unavailable_config={
            **ready,
            "mindtct_executable": str(tmp_path / "absent" / "mindtct"),
        },
        left_image=prepared_image(inputs / "left.png", gray8_png(1)),
        right_image=prepared_image(
            inputs / "right.png",
            gray8_png(6),
            image_id="sd300a_00001000_plain_right",
        ),
        expected_score_direction=ScoreDirection.HIGHER_IS_BETTER,
        additional_forbidden_metadata=("template", "minutiae", "xyt", "score"),
        directional_golden=directional_golden,
    )
    run_adapter_conformance(
        case,
        working_directory=working,
        artifact_directory=artifacts,
        sandbox_root=tmp_path,
    ).require_clean()


def test_the_real_build_reaches_research_ready_through_the_shared_engine(
    build, tmp_path
):
    """Section 49: the same four commands, the same stores, the same receipt."""
    from engineworld import build_engine_world, git_available
    from fpbench.core.enums import ResearchRunStatus
    from fpbench.experiments.algorithm_research import (
        execute_algorithm_research_run,
        finalize_algorithm_research_run,
        inspect_algorithm_research_experiment,
        prepare_algorithm_research_run,
    )
    from fpbench.experiments.nbis_research import nbis_research_integration

    if not git_available():
        pytest.skip("git is not installed")

    manifest = read_build_manifest(build / BUILD_MANIFEST_FILENAME)
    engine = build_engine_world(
        tmp_path,
        subject_count=1,
        experiment_id="nbis_upstream_smoke_v1",
        payload_factory=ridge_payload,
        prepare_repository=lambda root: sealed_repository(root, manifest),
    )
    shared = {
        "spec": engine.spec,
        "integration": nbis_research_integration(),
        "preparer_factory": identity_preparer,
        "workspace": engine.workspace,
        "dataset_root": engine.dataset_root,
        "repository_root": engine.repository_root,
    }
    prepare_algorithm_research_run(
        **shared, development_overrides={"build_directory": build}
    )
    summary = execute_algorithm_research_run(**shared)
    finalize_algorithm_research_run(**shared)
    state = inspect_algorithm_research_experiment(**shared)

    assert summary.newly_executed_jobs == engine.expected_jobs
    assert state.status is ResearchRunStatus.RESEARCH_READY, list(state.issues)
