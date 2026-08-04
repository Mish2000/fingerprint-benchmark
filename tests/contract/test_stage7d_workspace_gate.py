"""The real-workspace gate may skip only when Stage 7D is not installed."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.stage7d_contract

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
GATE_PATH = REPOSITORY_ROOT / "tests/integration/test_stage7d_workspace.py"


@pytest.fixture(scope="module")
def gate() -> ModuleType:
    spec = importlib.util.spec_from_file_location("stage7d_workspace_gate", GATE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_machine_without_any_known_run_skips_the_module(
    gate: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    monkeypatch.setattr(gate, "WORKSPACE", tmp_path / "workspace")
    monkeypatch.delenv("FPBENCH_SD300_ROOT", raising=False)

    with pytest.raises(pytest.skip.Exception, match="none of the three"):
        gate._require_workspace()


def test_one_known_run_makes_a_missing_dataset_a_failure(
    gate: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    workspace = tmp_path / "workspace"
    (workspace / "results" / gate.NBIS_RUN).mkdir(parents=True)
    monkeypatch.setattr(gate, "WORKSPACE", workspace)
    monkeypatch.delenv("FPBENCH_SD300_ROOT", raising=False)

    with pytest.raises(pytest.fail.Exception, match="FPBENCH_SD300_ROOT is not set"):
        gate._require_workspace()


def test_one_known_run_makes_missing_run_manifests_fail(
    gate: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    workspace = tmp_path / "workspace"
    (workspace / "results" / gate.NBIS_RUN).mkdir(parents=True)
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    monkeypatch.setattr(gate, "WORKSPACE", workspace)
    monkeypatch.setenv("FPBENCH_SD300_ROOT", str(dataset))

    with pytest.raises(pytest.fail.Exception, match="research run .* is missing"):
        gate._require_workspace()


def test_raw_runs_without_stage7d_artefacts_fail_instead_of_skip(
    gate: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    workspace = tmp_path / "workspace"
    for run_id in (gate.SOURCEAFIS_RUN, gate.NBIS_RUN, gate.NATIVE_RUN):
        directory = workspace / "results" / run_id
        directory.mkdir(parents=True)
        (directory / "run.json").write_text("{}\n", encoding="utf-8")
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    monkeypatch.setattr(gate, "WORKSPACE", workspace)
    monkeypatch.setenv("FPBENCH_SD300_ROOT", str(dataset))

    with pytest.raises(pytest.fail.Exception, match="NBIS decision pointer"):
        gate._require_workspace()


def test_no_individual_workspace_check_can_skip():
    source = GATE_PATH.read_text(encoding="utf-8")
    assert source.count("pytest.skip(") == 1
    assert "_require_clean_tree" not in source
