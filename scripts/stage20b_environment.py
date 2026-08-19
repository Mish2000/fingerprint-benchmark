#!/usr/bin/env python3
"""Record the runtime this route resolves to, without running a comparison.

``validate_environment()`` is what checks the certified build, the pinned
assembly and the SDK's untouched defaults; this writes down what it found so the
evidence can bind the tools rather than the configuration that named them.

Runs where the route runs — WSL on the certified Linux target.

.. code-block:: text

    MSYS_NO_PATHCONV=1 wsl.exe -d NBIS-BUILD-V1 -- bash -lc \\
      'cd /mnt/c/fingerprint-benchmark && ~/.venvs/fpbench-ci/bin/python scripts/stage20b_environment.py'
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from fpbench.adapters.registry import create_adapter  # noqa: E402
from fpbench.core.enums import EnvironmentStatus  # noqa: E402
from fpbench.experiments.stage20b_identity import ADAPTER_ID, NBIS_BUILD_ID  # noqa: E402
from fpbench.experiments.stage20b_run_support import to_local  # noqa: E402

DEFAULT_ROOT = Path(
    os.environ.get(
        "FPBENCH_STAGE20B_ROOT", "/mnt/c/Users/sirak/.cache/fpbench/private/stage20b"
    )
)
DEFAULT_BRIDGE = Path(
    os.environ.get(
        "FPBENCH_MCC_BRIDGE",
        "/mnt/c/Users/sirak/.cache/fpbench/third_party/unibo-mcc-sdk-v2/bridge/FpbenchMccBridge.exe",
    )
)
DEFAULT_SDK_DLL = Path(
    os.environ.get(
        "FPBENCH_MCC_SDK_DLL",
        "/mnt/c/Users/sirak/.cache/fpbench/third_party/unibo-mcc-sdk-v2/bridge/MccSdk.dll",
    )
)
DEFAULT_BRIDGE_MANIFEST = Path(
    os.environ.get(
        "FPBENCH_MCC_BRIDGE_MANIFEST",
        "/mnt/c/Users/sirak/.cache/fpbench/third_party/unibo-mcc-sdk-v2/bridge/bridge-manifest.json",
    )
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage 20B runtime record")
    parser.add_argument("--build", type=Path, default=REPO / "build" / "nbis-5.0.0" / NBIS_BUILD_ID)
    parser.add_argument("--bridge", type=Path, default=DEFAULT_BRIDGE)
    parser.add_argument("--sdk-dll", type=Path, default=DEFAULT_SDK_DLL)
    parser.add_argument("--bridge-manifest", type=Path, default=DEFAULT_BRIDGE_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_ROOT / "environment.json")
    args = parser.parse_args()

    build = to_local(Path(args.build))
    adapter = create_adapter(
        ADAPTER_ID,
        {
            "mindtct_executable": str(build / "bin" / "mindtct"),
            "bozorth3_executable": str(build / "bin" / "bozorth3"),
            "build_manifest": str(build / "nbis-build-manifest.json"),
            "mcc_bridge": str(args.bridge),
            "mcc_bridge_manifest": str(args.bridge_manifest),
            "mcc_sdk_dll": str(args.sdk_dll),
        },
    )
    report = adapter.validate_environment()
    print(f"environment: {report.status.value}")
    if report.status is not EnvironmentStatus.READY:
        print(f"  message: {report.message}", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(
        (
            json.dumps(
                {
                    "schema": "stage_20b_environment_v1",
                    "status": report.status.value,
                    "implementation_version": report.implementation_version,
                    "runtime": dict(report.runtime),
                    "dependencies": dict(report.dependencies),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    )
    for key, value in sorted(report.dependencies.items()):
        print(f"  {key} = {value}")
    print(f"written: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
