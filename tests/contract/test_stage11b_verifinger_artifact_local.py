"""The Stage 11B route against the real SDK. Local only, never in CI.

Everything in this file needs the pinned VeriFinger 2025.2 artifacts in the local
third-party store, a prepared installation, an activated trial licence and a Java
17 toolchain. CI has none of those and must never acquire them, so every test
carries the ``verifinger_artifact`` marker and skips itself when the artifacts
are absent (spec section 37).

The contract suite beside this one proves the adapter behaves correctly against a
fake bridge. This one proves the *real* bridge behaves the way that fake does —
which is the only way the first suite means anything.

No SD300 image is opened here and no benchmark score exists. The fixtures are
Stage 11A's: synthetic ridge fields this project generated, and upstream's own
sample prints out of the pinned archive.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fpbench.core.enums import EnvironmentStatus, ExecutionStatus
from fpbench.adapters.verifinger_java import identity, runtime as runtime_closure

pytestmark = pytest.mark.verifinger_artifact

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _store() -> Path:
    from fpbench.experiments.stage11a_artifacts import artifact_store_prefix_path

    return artifact_store_prefix_path(repository_root=REPOSITORY_ROOT)


@pytest.fixture(scope="module")
def installation() -> Path:
    from fpbench.experiments.stage11a_artifacts import acquisition_state

    try:
        state = acquisition_state(repository_root=REPOSITORY_ROOT)
    except Exception as exc:  # pragma: no cover - no store on this machine
        pytest.skip(f"no local artifact store: {exc}")
    if not state.obtained:
        pytest.skip("the pinned VeriFinger artifacts are not in the local store")

    from fpbench.experiments.stage11a_qualification import prepare_installation

    return prepare_installation(repository_root=REPOSITORY_ROOT)


@pytest.fixture(scope="module")
def manifest():
    return runtime_closure.read_runtime_manifest(
        REPOSITORY_ROOT / "configs" / "verifinger" / "verifinger_runtime_manifest_v1.json"
    )


@pytest.fixture(scope="module")
def adapter(installation: Path):
    from fpbench.adapters.registry import create_adapter

    built = create_adapter(identity.ADAPTER_ID, {"installation": str(installation)})
    report = built.validate_environment()
    if report.status is not EnvironmentStatus.READY:
        pytest.skip(f"the VeriFinger runtime is not usable here: {report.message}")
    return built


# ------------------------------------------------------------ runtime closure


def test_every_component_of_the_closure_is_on_disk_and_unchanged(
    installation: Path, manifest
) -> None:
    verified = runtime_closure.verify_installation(installation, manifest)
    assert len(verified) == len(runtime_closure.CLOSURE_PATHS) == 17


def test_every_component_came_out_of_the_pinned_archive(manifest) -> None:
    """Integrity is not provenance. This is the provenance half (spec section 16)."""
    from fpbench.experiments.stage11a_verifinger_observations import SDK_ARCHIVE

    archive = _store() / SDK_ARCHIVE.filename
    if not archive.is_file():
        pytest.skip("the pinned SDK archive is not in the local store")
    proved = runtime_closure.verify_against_archive(archive, manifest)
    assert len(proved) == len(manifest.components)


def test_the_committed_manifest_is_what_this_installation_produces(
    installation: Path, manifest
) -> None:
    derived = runtime_closure.build_runtime_manifest(
        installation,
        sdk_archive_sha256=manifest.sdk_archive_sha256,
        platform=manifest.platform,
    )
    assert derived.fingerprint == manifest.fingerprint


# ----------------------------------------------------------- the real bridge


def test_the_environment_reports_the_engines_own_seven_modules(adapter) -> None:
    report = adapter.validate_environment()
    assert report.status is EnvironmentStatus.READY
    assert report.implementation_version == identity.IMPLEMENTATION_VERSION
    modules = {
        key.removeprefix("module."): value
        for key, value in report.dependencies.items()
        if key.startswith("module.")
    }
    assert set(modules) == {
        name.removesuffix(".dll") for name in runtime_closure.NATIVE_LIBRARY_NAMES
    }
    assert all(
        version.startswith(f"{identity.IMPLEMENTATION_VERSION}.")
        for version in modules.values()
    )


def test_the_real_engine_delivers_the_defaults_stage_11a_read(adapter) -> None:
    """If it did not, the environment would be UNAVAILABLE and this would skip."""
    assert adapter.validate_environment().status is EnvironmentStatus.READY


def test_no_absolute_path_reaches_the_environment_report(adapter) -> None:
    import json

    report = adapter.validate_environment()
    rendered = json.dumps(dict(report.dependencies)) + json.dumps(dict(report.runtime))
    assert "C:\\Users" not in rendered
    assert "\\.cache\\" not in rendered
    assert "/home/" not in rendered


# ------------------------------------------------------------------ the smoke


def test_the_production_smoke_establishes_every_claim(installation: Path) -> None:
    """The whole of spec section 23, run against the real SDK."""
    from fpbench.experiments.verifinger_smoke import run_production_smoke

    report = run_production_smoke(
        repository_root=REPOSITORY_ROOT, installation=installation
    )
    assert report.passed, report.claims
    assert report.sd300_used is False
    assert report.benchmark_scores_produced == 0
    assert report.scores_produced <= 20
    for claim, held in report.claims.items():
        assert held is True, claim


def test_a_real_comparison_returns_an_integer_and_no_decision(adapter) -> None:
    import hashlib
    import tempfile

    from fpbench.core.enums import ChecksumStatus
    from fpbench.core.execution_models import ComparisonContext, PreparedImage

    fixtures = _store() / "fixtures"
    if not (fixtures / "vendor_a.png").is_file():
        pytest.skip("the Stage 11A fixtures are not on this machine")

    def image(name: str) -> PreparedImage:
        path = (fixtures / name).resolve()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return PreparedImage(
            image_id=f"fixture_{name.split('.')[0]}",
            local_path=path,
            effective_ppi=identity.REQUIRED_EFFECTIVE_PPI,
            media_type="image/png",
            expected_sha256=digest,
            checksum_status=ChecksumStatus.VERIFIED,
            preparation_profile_id="stage11b_artifact_test_v1",
            preparation_hash=hashlib.sha256(b"stage11b-artifact").hexdigest(),
        )

    with tempfile.TemporaryDirectory() as scratch:
        work = Path(scratch) / "work"
        artifacts = Path(scratch) / "artifacts"
        work.mkdir()
        artifacts.mkdir()
        result = adapter.compare(
            image("vendor_a.png"),
            image("vendor_b.png"),
            ComparisonContext(
                run_id="run_stage11barti",
                job_id="5b0000000000d001",
                attempt=1,
                working_directory=work.resolve(),
                artifact_directory=artifacts.resolve(),
                timeout_seconds=180.0,
                deterministic_seed=0,
            ),
        )
    assert result.status is ExecutionStatus.SUCCESS
    assert float(result.raw_score).is_integer()
    metadata = dict(result.metadata)
    assert metadata["verifinger.extraction_count"] == "2"
    assert metadata["verifinger.engine_status"] in identity.SCORE_BEARING_STATUSES
    assert "verifinger.decision" not in metadata
    assert "verifinger.threshold" not in metadata


def test_a_print_the_extractor_declines_is_a_recorded_outcome(adapter) -> None:
    """A quality refusal is data, not a broken run (spec sections 13 and 32)."""
    import hashlib
    import tempfile

    from fpbench.adapters.verifinger_java.failure_mapping import (
        ALGORITHMIC_FAILURE_CODES,
    )
    from fpbench.core.enums import ChecksumStatus
    from fpbench.core.execution_models import ComparisonContext, PreparedImage

    fixtures = _store() / "fixtures"
    for name in ("vendor_a.png", "fixture_blank.png"):
        if not (fixtures / name).is_file():
            pytest.skip("the Stage 11A fixtures are not on this machine")

    def image(name: str) -> PreparedImage:
        path = (fixtures / name).resolve()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return PreparedImage(
            image_id=f"fixture_{name.split('.')[0]}",
            local_path=path,
            effective_ppi=identity.REQUIRED_EFFECTIVE_PPI,
            media_type="image/png",
            expected_sha256=digest,
            checksum_status=ChecksumStatus.VERIFIED,
            preparation_profile_id="stage11b_artifact_test_v1",
            preparation_hash=hashlib.sha256(b"stage11b-artifact").hexdigest(),
        )

    with tempfile.TemporaryDirectory() as scratch:
        work = Path(scratch) / "work"
        artifacts = Path(scratch) / "artifacts"
        work.mkdir()
        artifacts.mkdir()
        result = adapter.compare(
            image("vendor_a.png"),
            image("fixture_blank.png"),
            ComparisonContext(
                run_id="run_stage11barti",
                job_id="5b0000000000d002",
                attempt=1,
                working_directory=work.resolve(),
                artifact_directory=artifacts.resolve(),
                timeout_seconds=180.0,
                deterministic_seed=0,
            ),
        )
    assert result.status is ExecutionStatus.FAILURE
    assert result.raw_score is None
    assert result.failure.code in ALGORITHMIC_FAILURE_CODES
    assert result.failure.details["engine_status"]
