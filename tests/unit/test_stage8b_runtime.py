"""The worker reports; this is the code that decides whether to believe it."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from fpbench.core.flx_errors import FlxRuntimeError
from fpbench.flx import identity
from fpbench.flx.lock import load_runtime_lock
from fpbench.flx.runtime import build_runtime_manifest, verify_runtime_report

pytestmark = pytest.mark.stage8b_contract

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
LOCK = load_runtime_lock(REPOSITORY_ROOT / "configs" / "flx" / "flx_runtime_lock_v1.txt")
NOW = "2026-08-05T12:00:00+03:00"


def _report(**changes: Any) -> dict[str, Any]:
    """The report the real worker produced, so the checks face real shapes."""
    report: dict[str, Any] = {
        "os_name": "Linux",
        "os_version": "Ubuntu 24.04.4 LTS",
        "kernel_release": "6.18.33.2-microsoft-standard-WSL2",
        "cpu_architecture": "x86_64",
        "cpu_model": "Intel(R) Core(TM) Ultra 9 275HX",
        "python_version": "3.12.3",
        "python_implementation": "CPython",
        "torch_version": "2.13.0+cpu",
        "torchvision_version": "0.28.0+cpu",
        "numpy_version": "2.5.1",
        "blas_implementation": "Intel(R) oneAPI Math Kernel Library Version 2024.2",
        "mkldnn_version": "Intel(R) MKL-DNN v3.12.0",
        "parallel_backend": "OpenMP",
        "torch_num_threads": 1,
        "torch_num_interop_threads": 1,
        "device": "cpu",
        "cuda_available": False,
        "distributions": {item.name: item.version for item in LOCK.distributions},
        "environment": {
            "OMP_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "HF_HOME": "/bundle/offline-cache",
            "TORCH_HOME": "/bundle/offline-cache",
        },
    }
    report.update(changes)
    return report


def test_the_observed_runtime_is_accepted_and_becomes_a_manifest() -> None:
    manifest = build_runtime_manifest(_report(), lock=LOCK, created_utc=NOW)

    assert manifest.runtime_profile_id == identity.RUNTIME_PROFILE_ID
    assert manifest.torch_version == "2.13.0+cpu"
    assert manifest.dependency_lock_sha256 == LOCK.sha256
    assert len(manifest.dependencies) == len(LOCK.distributions)
    assert manifest.torch_num_threads == manifest.torch_num_interop_threads == 1
    assert manifest.cuda_available is False


def test_a_report_missing_a_field_is_refused() -> None:
    report = _report()
    del report["mkldnn_version"]

    with pytest.raises(FlxRuntimeError, match="did not report \\['mkldnn_version'\\]"):
        verify_runtime_report(report, lock=LOCK)


def test_a_gpu_runtime_is_a_different_profile() -> None:
    with pytest.raises(FlxRuntimeError, match="CPU profile"):
        verify_runtime_report(_report(cuda_available=True), lock=LOCK)
    with pytest.raises(FlxRuntimeError, match="CPU profile"):
        verify_runtime_report(_report(device="cuda:0"), lock=LOCK)


def test_a_different_architecture_or_os_is_refused() -> None:
    with pytest.raises(FlxRuntimeError, match="pins x86_64"):
        verify_runtime_report(_report(cpu_architecture="aarch64"), lock=LOCK)
    with pytest.raises(FlxRuntimeError, match="pins Linux"):
        verify_runtime_report(_report(os_name="Windows"), lock=LOCK)


@pytest.mark.parametrize("field", ["torch_num_threads", "torch_num_interop_threads"])
def test_more_than_one_thread_is_refused(field: str) -> None:
    # Spec section 6: the thread configuration is pinned, because MKL's
    # reduction order otherwise becomes part of the answer.
    with pytest.raises(FlxRuntimeError, match="pins one thread"):
        verify_runtime_report(_report(**{field: 24}), lock=LOCK)


def test_a_drifted_torch_is_refused_even_if_the_distribution_list_agrees() -> None:
    report = _report(torch_version="2.12.1+cpu")

    with pytest.raises(FlxRuntimeError, match="torch is 2.12.1\\+cpu but the lock pins"):
        verify_runtime_report(report, lock=LOCK)


def test_an_unpinned_distribution_in_the_runtime_is_refused() -> None:
    report = _report()
    report["distributions"] = {**report["distributions"], "opencv-python": "4.10.0"}

    with pytest.raises(Exception, match="unpinned"):
        verify_runtime_report(report, lock=LOCK)


def test_an_unset_offline_variable_is_refused() -> None:
    report = _report()
    report["environment"] = {**report["environment"], "TORCH_HOME": ""}

    with pytest.raises(FlxRuntimeError, match="left \\['TORCH_HOME'\\] unset"):
        verify_runtime_report(report, lock=LOCK)


def test_an_unpinned_thread_environment_is_refused() -> None:
    report = _report()
    report["environment"] = {**report["environment"], "OMP_NUM_THREADS": "8"}

    with pytest.raises(FlxRuntimeError, match="OMP_NUM_THREADS is '8'"):
        verify_runtime_report(report, lock=LOCK)


def test_an_empty_distribution_list_is_refused() -> None:
    with pytest.raises(FlxRuntimeError, match="no installed distributions"):
        verify_runtime_report(_report(distributions={}), lock=LOCK)


def test_the_manifest_identity_moves_with_any_runtime_change() -> None:
    baseline = build_runtime_manifest(_report(), lock=LOCK, created_utc=NOW)
    for change in (
        {"cpu_model": "some other cpu"},
        {"kernel_release": "6.0.0"},
        {"os_version": "Ubuntu 22.04"},
        {"mkldnn_version": "Intel(R) MKL-DNN v3.11.0"},
        {"blas_implementation": "OpenBLAS"},
    ):
        moved = build_runtime_manifest(_report(**change), lock=LOCK, created_utc=NOW)
        assert moved.fingerprint != baseline.fingerprint, change


def test_a_wall_clock_change_does_not_move_the_manifest_identity() -> None:
    first = build_runtime_manifest(_report(), lock=LOCK, created_utc=NOW)
    second = build_runtime_manifest(
        _report(), lock=LOCK, created_utc="2027-02-02T02:02:02+03:00"
    )

    assert first.fingerprint == second.fingerprint
