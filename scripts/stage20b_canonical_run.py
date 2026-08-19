#!/usr/bin/env python3
"""The 6,000 canonical comparisons under MINDTCT + official MCC SDK v2.0.

This driver knows **nothing** about MINDTCT, about the XYT translation, about
.NET or about WSL interop. It builds the adapter through the registry, asks it
whether its environment is ready, and then calls ``compare(left, right, context)``
six thousand times. That is section 8's requirement: Stage 20B is a real algorithm
behind the standard three methods, not a stage-specific runner.

Everything that decides *what* is compared was decided in Stage 6A and is read
back unchanged: the same prepared image set, the same 6,000-row pair manifest,
the same row order. Nothing here selects a cohort, generates a pair or writes a
PNG.

Per pair it stores exactly what section 22 asks for:

.. code-block:: text

    pair_id, algorithm_id, raw_score, status,
    left_minutiae_count, right_minutiae_count,
    mindtct_left_ms, mindtct_right_ms,
    translation_left_ms, translation_right_ms,
    mcc_template_left_ms, mcc_template_right_ms, mcc_match_ms,
    total_adapter_ms

No threshold, no decision, no calibration, no metric. A score of 0.0 is a
success. Every attempt is stored, including the ones that failed.

.. code-block:: text

    MSYS_NO_PATHCONV=1 wsl.exe -d NBIS-BUILD-V1 -- bash -lc \\
      'cd /mnt/c/fingerprint-benchmark && ~/.venvs/fpbench-ci/bin/python scripts/stage20b_canonical_run.py'
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from fpbench.adapters.mcc.failure_mapping import STATUS_KEY  # noqa: E402
from fpbench.adapters.registry import create_adapter  # noqa: E402
from fpbench.core.enums import EnvironmentStatus, ExecutionStatus  # noqa: E402
from fpbench.core.execution_models import ComparisonContext  # noqa: E402
from fpbench.experiments.stage18a_inputs import load_stage18a_inputs  # noqa: E402
from fpbench.experiments.stage20b_identity import (  # noqa: E402
    ADAPTER_ID,
    ALGORITHM_ID,
    EXPECTED_OUTCOMES,
    NBIS_BUILD_ID,
    RUN_ID,
)
from fpbench.experiments.stage20b_run_support import (  # noqa: E402
    as_prepared,
    entry_hashes,
    to_local,
)

BUILD = to_local(REPO / "build" / "nbis-5.0.0" / NBIS_BUILD_ID)
BRIDGE = Path(
    os.environ.get(
        "FPBENCH_MCC_BRIDGE",
        "/mnt/c/Users/sirak/.cache/fpbench/third_party/unibo-mcc-sdk-v2/bridge/FpbenchMccBridge.exe",
    )
)
SDK_DLL = Path(
    os.environ.get(
        "FPBENCH_MCC_SDK_DLL",
        "/mnt/c/Users/sirak/.cache/fpbench/third_party/unibo-mcc-sdk-v2/bridge/MccSdk.dll",
    )
)
BRIDGE_MANIFEST = Path(
    os.environ.get(
        "FPBENCH_MCC_BRIDGE_MANIFEST",
        "/mnt/c/Users/sirak/.cache/fpbench/third_party/unibo-mcc-sdk-v2/bridge/bridge-manifest.json",
    )
)
OUTPUT_ROOT = Path(
    os.environ.get(
        "FPBENCH_STAGE20B_ROOT", "/mnt/c/Users/sirak/.cache/fpbench/private/stage20b"
    )
)

#: Generous, and deliberately so: a timeout is a fact about this host, and a
#: budget tight enough to fire under load would put infrastructure noise into a
#: result file that is meant to be about two fingers.
TIMEOUT_SECONDS = 300.0


def main() -> int:
    inputs = load_stage18a_inputs()
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    results_path = OUTPUT_ROOT / "pair-outcomes.jsonl"

    already: set[str] = set()
    if results_path.is_file():
        with results_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    already.add(json.loads(line)["pair_id"])
    if already:
        print(f"resuming: {len(already)} outcomes already stored")

    adapter = create_adapter(
        ADAPTER_ID,
        {
            "mindtct_executable": str(BUILD / "bin" / "mindtct"),
            "bozorth3_executable": str(BUILD / "bin" / "bozorth3"),
            "build_manifest": str(BUILD / "nbis-build-manifest.json"),
            "mcc_bridge": str(BRIDGE),
            "mcc_bridge_manifest": str(BRIDGE_MANIFEST),
            "mcc_sdk_dll": str(SDK_DLL),
            # Section 12: every comparison re-checks that the five runtime assets
            # are still the ones preflight approved, and a drift ends the run
            # rather than producing outcomes attributed to tools that changed
            # underneath them.
            "research_mode": True,
        },
    )
    report = adapter.validate_environment()
    print(f"environment: {report.status.value}")
    if report.status is not EnvironmentStatus.READY:
        print(f"  message: {report.message}")
        return 1
    for key, value in sorted(report.dependencies.items()):
        print(f"  {key} = {value}")

    # Recorded before the first image is opened, so the evidence binds the tools
    # the run actually loaded rather than the ones a config file named.
    (OUTPUT_ROOT / "environment.json").write_bytes(
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

    descriptor = adapter.descriptor
    if descriptor.algorithm_id != ALGORITHM_ID:
        print(f"unexpected algorithm id {descriptor.algorithm_id!r}")
        return 1

    by_id = inputs.images_by_id
    hashes = entry_hashes()
    work = OUTPUT_ROOT / "work"
    work.mkdir(parents=True, exist_ok=True)
    artifacts = OUTPUT_ROOT / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    written = 0
    with results_path.open("a", encoding="utf-8") as handle:
        for index, pair in enumerate(inputs.pairs, start=1):
            if pair.pair_id in already:
                continue
            left = as_prepared(by_id[pair.left_image_id], hashes[pair.left_image_id])
            right = as_prepared(by_id[pair.right_image_id], hashes[pair.right_image_id])
            # job_id is a hash so nothing about the pair can be read back out of
            # it, exactly as the contract requires.
            job_id = "job_" + hashlib.sha256(pair.pair_id.encode()).hexdigest()[:12]
            context = ComparisonContext(
                run_id=RUN_ID,
                job_id=job_id,
                attempt=1,
                working_directory=work,
                artifact_directory=artifacts,
                timeout_seconds=TIMEOUT_SECONDS,
                deterministic_seed=0,
            )
            call_started = time.perf_counter()
            result = adapter.compare(left, right, context)
            total_ms = (time.perf_counter() - call_started) * 1000.0

            timings = dict(result.timing_components_ms)
            metadata = dict(result.metadata)
            details = (result.failure.details or {}) if result.failure else {}
            status = (
                "OK"
                if result.status is ExecutionStatus.SUCCESS
                else str(details.get(STATUS_KEY, "INFRASTRUCTURE_FAILURE"))
            )
            row = {
                "ordinal": pair.ordinal,
                "pair_id": pair.pair_id,
                "algorithm_id": ALGORITHM_ID,
                "release": pair.release,
                "stage": pair.protocol_stage,
                "ground_truth": pair.ground_truth,
                "left_image_id": pair.left_image_id,
                "right_image_id": pair.right_image_id,
                "raw_score": result.raw_score,
                "status": status,
                "failure_code": result.failure.code.value if result.failure else None,
                "failure_reason": details.get("reason") or details.get("detail"),
                "observed_score": details.get("observed_score"),
                "left_minutiae_count": (
                    int(metadata["left_minutiae_count"])
                    if "left_minutiae_count" in metadata
                    else None
                ),
                "right_minutiae_count": (
                    int(metadata["right_minutiae_count"])
                    if "right_minutiae_count" in metadata
                    else None
                ),
                "mindtct_left_ms": timings.get("mindtct_left"),
                "mindtct_right_ms": timings.get("mindtct_right"),
                "translation_left_ms": timings.get("translation_left"),
                "translation_right_ms": timings.get("translation_right"),
                "mcc_template_left_ms": timings.get("mcc_template_left"),
                "mcc_template_right_ms": timings.get("mcc_template_right"),
                "mcc_match_ms": timings.get("mcc_match"),
                "total_adapter_ms": total_ms,
            }
            handle.write(json.dumps(row, sort_keys=True) + "\n")
            handle.flush()
            written += 1
            if index % 250 == 0:
                elapsed = time.perf_counter() - started
                rate = elapsed / max(written, 1)
                print(
                    f"  {index}/{len(inputs.pairs)}  {elapsed:.0f}s  "
                    f"{rate * 1000:.0f} ms/pair",
                    flush=True,
                )

    total = sum(1 for line in results_path.open("r", encoding="utf-8") if line.strip())
    print(
        f"\nstored {total} of {EXPECTED_OUTCOMES} outcomes "
        f"in {time.perf_counter() - started:.0f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
