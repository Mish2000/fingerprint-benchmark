"""Turn what the worker reports about itself into a checked runtime manifest.

The worker is the only process that can see torch, so it is the only process
that can answer these questions — but it is not the process that decides
whether the answers are acceptable.  It reports; this module judges, against
the lock and against the frozen profile.

A manifest is only written when every check passes, so a stored manifest is
never a description of a runtime that was allowed to be wrong.
"""

from __future__ import annotations

from typing import Any, Mapping

from fpbench.core.flx_errors import FlxRuntimeError
from fpbench.core.flx_models import STAGE8B_SCHEMA_VERSION, FlxRuntimeManifest
from fpbench.flx import identity
from fpbench.flx.lock import RuntimeLock

__all__ = [
    "REQUIRED_ENVIRONMENT_KEYS",
    "verify_runtime_report",
    "build_runtime_manifest",
]

#: Environment the worker must have pinned before anything numeric happened.
REQUIRED_ENVIRONMENT_KEYS = ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "HF_HOME", "TORCH_HOME")

#: Variables whose *value* is a machine-local path.  What matters for the
#: evidence is that they were redirected into a controlled local directory, not
#: where that directory happens to live on one machine — and a private absolute
#: path may not be published at all (spec section 22).
_PATH_VALUED_KEYS = ("HF_HOME", "TORCH_HOME")
_REDIRECTED = "bundle_local_offline_cache"

_REQUIRED_FIELDS = (
    "os_name",
    "os_version",
    "kernel_release",
    "cpu_architecture",
    "cpu_model",
    "python_version",
    "python_implementation",
    "torch_version",
    "torchvision_version",
    "numpy_version",
    "blas_implementation",
    "mkldnn_version",
    "parallel_backend",
    "torch_num_threads",
    "torch_num_interop_threads",
    "device",
    "cuda_available",
    "distributions",
    "environment",
)


def verify_runtime_report(report: Mapping[str, Any], *, lock: RuntimeLock) -> None:
    """Refuse a runtime that is not the locked one, for any reason."""
    missing = [name for name in _REQUIRED_FIELDS if name not in report]
    if missing:
        raise FlxRuntimeError(f"the worker did not report {missing}")

    distributions = report["distributions"]
    if not isinstance(distributions, Mapping) or not distributions:
        raise FlxRuntimeError("the worker reported no installed distributions")
    lock.verify_installed(distributions)

    for name, field in (
        ("torch", "torch_version"),
        ("torchvision", "torchvision_version"),
        ("numpy", "numpy_version"),
    ):
        expected = lock.require_version(name)
        actual = str(report[field])
        if actual != expected:
            raise FlxRuntimeError(
                f"{name} is {actual} but the lock pins {expected}"
            )

    if report["cuda_available"] or str(report["device"]) != "cpu":
        raise FlxRuntimeError(
            f"{identity.RUNTIME_PROFILE_ID} is a CPU profile; a GPU runtime is a "
            "different profile and a different identity"
        )
    if str(report["cpu_architecture"]) != "x86_64":
        raise FlxRuntimeError(
            f"{identity.RUNTIME_PROFILE_ID} pins x86_64, got {report['cpu_architecture']}"
        )
    if str(report["os_name"]) != "Linux":
        raise FlxRuntimeError(
            f"{identity.RUNTIME_PROFILE_ID} pins Linux, got {report['os_name']}"
        )
    for field in ("torch_num_threads", "torch_num_interop_threads"):
        if int(report[field]) != 1:
            raise FlxRuntimeError(
                f"{field} is {report[field]}; the profile pins one thread so that "
                "reduction order is not part of the answer"
            )
    environment = report["environment"]
    if not isinstance(environment, Mapping):
        raise FlxRuntimeError("the worker did not report its deterministic environment")
    absent = [key for key in REQUIRED_ENVIRONMENT_KEYS if not str(environment.get(key, ""))]
    if absent:
        raise FlxRuntimeError(f"the worker left {absent} unset")
    for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        if str(environment[key]) != "1":
            raise FlxRuntimeError(f"{key} is {environment[key]!r}, expected '1'")
    for key in _PATH_VALUED_KEYS:
        if not str(environment[key]).endswith("offline-cache"):
            raise FlxRuntimeError(
                f"{key} is not the worker's bundle-local offline cache"
            )


def _publishable_environment(report: Mapping[str, Any]) -> dict[str, str]:
    """Record what was redirected, never a machine-local path."""
    environment = report["environment"]
    return {
        key: _REDIRECTED if key in _PATH_VALUED_KEYS else str(environment[key])
        for key in REQUIRED_ENVIRONMENT_KEYS
    }


def build_runtime_manifest(
    report: Mapping[str, Any],
    *,
    lock: RuntimeLock,
    created_utc: str,
) -> FlxRuntimeManifest:
    verify_runtime_report(report, lock=lock)
    return FlxRuntimeManifest.create(
        schema_version=STAGE8B_SCHEMA_VERSION,
        runtime_profile_id=identity.RUNTIME_PROFILE_ID,
        os_name=str(report["os_name"]),
        os_version=str(report["os_version"]),
        kernel_release=str(report["kernel_release"]),
        cpu_architecture=str(report["cpu_architecture"]),
        cpu_model=str(report["cpu_model"]),
        python_version=str(report["python_version"]),
        python_implementation=str(report["python_implementation"]),
        torch_version=str(report["torch_version"]),
        torchvision_version=str(report["torchvision_version"]),
        numpy_version=str(report["numpy_version"]),
        blas_implementation=str(report["blas_implementation"]),
        mkldnn_version=str(report["mkldnn_version"]),
        parallel_backend=str(report["parallel_backend"]),
        torch_num_threads=int(report["torch_num_threads"]),
        torch_num_interop_threads=int(report["torch_num_interop_threads"]),
        device=str(report["device"]),
        cuda_available=bool(report["cuda_available"]),
        dependency_lock_sha256=lock.sha256,
        dependencies=lock.pins(),
        deterministic_environment=_publishable_environment(report),
        created_utc=created_utc,
    )
