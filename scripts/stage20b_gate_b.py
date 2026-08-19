#!/usr/bin/env python3
"""Gate B: this route's MINDTCT is Algorithm 2's MINDTCT, byte for byte.

Runs in WSL on the certified Linux target, because that is where Algorithm 2's
extractor runs and the whole point of the gate is that Stage 20B did not compile
a second MINDTCT for a more convenient host.

Twelve canonical images, frozen in source before any extraction, are put through
*both adapters' own extraction paths* — Algorithm 2's and Stage 20B's — and the
XYT outputs compared. Two runs of one script would only show that MINDTCT is
deterministic; this shows the two routes agree. File names differ and are not
compared; content may not differ.

No score is read anywhere in this script.

.. code-block:: text

    MSYS_NO_PATHCONV=1 wsl.exe -d NBIS-BUILD-V1 -- bash -lc \\
      'cd /mnt/c/fingerprint-benchmark && ~/.venvs/fpbench-ci/bin/python scripts/stage20b_gate_b.py'
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
from fpbench.experiments.stage18a_inputs import load_stage18a_inputs  # noqa: E402
from fpbench.experiments.stage20b_gates import GATE_B_PASS, run_gate_b  # noqa: E402
from fpbench.experiments.stage20b_identity import (  # noqa: E402
    ADAPTER_ID,
    GATE_B_SUBSET,
    NBIS_BUILD_ID,
)
from fpbench.experiments.stage20b_run_support import (  # noqa: E402
    as_prepared,
    entry_hashes,
    to_local,
)

ALGORITHM2_ADAPTER_ID = "nbis_mindtct_bozorth3_subprocess"

DEFAULT_BUILD = REPO / "build" / "nbis-5.0.0" / NBIS_BUILD_ID
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
    parser = argparse.ArgumentParser(description="Stage 20B Gate B")
    parser.add_argument("--build", type=Path, default=DEFAULT_BUILD)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--bridge", type=Path, default=DEFAULT_BRIDGE)
    parser.add_argument("--sdk-dll", type=Path, default=DEFAULT_SDK_DLL)
    parser.add_argument("--bridge-manifest", type=Path, default=DEFAULT_BRIDGE_MANIFEST)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    build = to_local(Path(args.build))
    mindtct = build / "bin" / "mindtct"
    if not mindtct.is_file():
        print(f"the certified mindtct is absent: {mindtct}", file=sys.stderr)
        return 2

    nbis_configuration = {
        "mindtct_executable": str(mindtct),
        "bozorth3_executable": str(build / "bin" / "bozorth3"),
        "build_manifest": str(build / "nbis-build-manifest.json"),
    }
    algorithm2 = create_adapter(ALGORITHM2_ADAPTER_ID, dict(nbis_configuration))
    stage20b = create_adapter(
        ADAPTER_ID,
        {
            **nbis_configuration,
            "mcc_bridge": str(args.bridge),
            "mcc_bridge_manifest": str(args.bridge_manifest),
            "mcc_sdk_dll": str(args.sdk_dll),
        },
    )

    inputs = load_stage18a_inputs()
    by_id = inputs.images_by_id
    hashes = entry_hashes()
    missing = [image_id for image_id in GATE_B_SUBSET if image_id not in by_id]
    if missing:
        print(
            f"the frozen Gate B subset names images the set does not hold: {missing}",
            file=sys.stderr,
        )
        return 2

    images = []
    for image_id in GATE_B_SUBSET:
        entry = by_id[image_id]
        release, _subject, impression, _finger = image_id.split("_")
        images.append(
            {
                "image_id": image_id,
                "release": release.upper(),
                "impression_type": impression,
                "prepared": as_prepared(entry, hashes[image_id]),
            }
        )

    workspace = Path(args.root) / "gate-b"
    record = run_gate_b(
        algorithm2=algorithm2, stage20b=stage20b, images=images, workspace=workspace
    )
    for row in record["images"]:
        mark = "identical" if row["identical"] else "DIFFERENT"
        print(f"  {row['image_id']:<28} {row['minutiae_count']:>4} minutiae  {mark}")
    print(
        f"\n{record['outcome']}  "
        f"({record['identical_xyt']}/{record['expected_images']} identical)"
    )

    output = args.output or (workspace / "gate-b-mindtct-parity.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(
        (json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode(
            "utf-8"
        )
    )
    print(f"written: {output}")
    return 0 if record["outcome"] == GATE_B_PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
