#!/usr/bin/env python3
"""The 6,000 canonical comparisons under Algorithm 5, through the adapter contract.

This driver knows **nothing** about MINDTCT, about the CSV translation or about
OpenAFIS. It builds the adapter through the registry, asks it whether its
environment is ready, and then calls ``compare(left, right, context)`` six
thousand times. That is section 14's requirement: Stage 19A is a real algorithm
behind the standard three methods, not a stage-specific runner like 18A's.

Everything that decides *what* is compared was decided in Stage 6A and is read
back unchanged: the same prepared image set, the same 6,000-row pair manifest,
the same row order. Nothing here selects a cohort, generates a pair or writes a
PNG.

Per pair it stores exactly what section 19 asks for:

.. code-block:: text

    pair_id, algorithm_id, raw_score, status,
    mindtct_left_ms, mindtct_right_ms,
    openafis_template_left_ms, openafis_template_right_ms, openafis_match_ms,
    left_minutiae_count, right_minutiae_count

No threshold, no decision, no calibration. A score of 0 is a success.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from fpbench.adapters.registry import create_adapter  # noqa: E402
from fpbench.core.enums import ChecksumStatus, EnvironmentStatus, ExecutionStatus  # noqa: E402
from fpbench.core.execution_models import ComparisonContext, PreparedImage  # noqa: E402
from fpbench.experiments.stage18a_inputs import load_stage18a_inputs  # noqa: E402

ADAPTER_ID = "nbis_mindtct_openafis_subprocess"
ALGORITHM_ID = "nbis_mindtct_openafis"

BUILD = REPO / "build" / "nbis-5.0.0" / "658f9f54a8f2"
BRIDGE = Path(
    os.environ.get(
        "FPBENCH_OPENAFIS_BRIDGE",
        "/home/nbisbuild/stage18a-openafis/bridge/build/fpbench_openafis_bridge",
    )
)
OUTPUT_ROOT = Path(
    os.environ.get("FPBENCH_STAGE19A_ROOT", "/mnt/c/Users/sirak/.cache/fpbench/private/stage19a")
)

RUN_ID = "run_stage19a_canonical500"


def to_local(path: Path) -> Path:
    """Windows path -> the path this process can open."""
    text = str(path)
    if len(text) > 2 and text[1] == ":":
        return Path("/mnt/" + text[0].lower() + text[2:].replace("\\", "/"))
    return Path(text)


def entry_hashes() -> dict[str, str]:
    """image_id -> the preparation set's own per-entry hash.

    Read straight from the published parquet rather than through Stage 18A's
    input reader: that module's bytes are pinned by Stage 18A's finalization
    marker, and widening its dataclass for a Stage 19A need would invalidate a
    published fingerprint.
    """
    import pyarrow.parquet as pq

    table = pq.read_table(
        REPO / "workspace" / "prepared-images" / "prepset_be560e047991" / "entries.parquet",
        columns=["image_id", "entry_hash"],
    )
    return {row["image_id"]: row["entry_hash"] for row in table.to_pylist()}


def as_prepared(entry, entry_hash: str) -> PreparedImage:
    """One preparation entry as the adapter contract's PreparedImage."""
    return PreparedImage(
        image_id=entry.image_id,
        local_path=to_local(entry.path),
        effective_ppi=500,
        media_type="image/png",
        expected_sha256=entry.output_encoded_sha256,
        checksum_status=ChecksumStatus.VERIFIED,
        preparation_profile_id="canonical_gray8_500ppi_lanczos3_v1",
        preparation_hash=entry_hash,
        prepared_sha256=entry.output_encoded_sha256,
        pixel_sha256=entry.output_pixel_sha256,
        pixel_width=entry.output_width,
        pixel_height=entry.output_height,
    )


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
            "openafis_bridge": str(BRIDGE),
            "research_mode": False,
        },
    )
    report = adapter.validate_environment()
    print(f"environment: {report.status.value}")
    if report.status is not EnvironmentStatus.READY:
        print(f"  message: {report.message}")
        return 1
    for key, value in sorted(report.dependencies.items()):
        print(f"  {key} = {value}")

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
            import hashlib

            job_id = "job_" + hashlib.sha256(pair.pair_id.encode()).hexdigest()[:12]
            context = ComparisonContext(
                run_id=RUN_ID,
                job_id=job_id,
                attempt=1,
                working_directory=work,
                artifact_directory=artifacts,
                timeout_seconds=120.0,
                deterministic_seed=0,
            )
            result = adapter.compare(left, right, context)

            timings = dict(result.timing_components_ms)
            metadata = dict(result.metadata)
            status = (
                "OK"
                if result.status is ExecutionStatus.SUCCESS
                else str((result.failure.details or {}).get("stage19_status", "INFRASTRUCTURE_FAILURE"))
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
                "raw_score": int(result.raw_score) if result.raw_score is not None else None,
                "status": status,
                "failure_code": result.failure.code.value if result.failure else None,
                "failure_reason": (result.failure.details or {}).get("reason") if result.failure else None,
                "mindtct_left_ms": timings.get("mindtct_left"),
                "mindtct_right_ms": timings.get("mindtct_right"),
                "openafis_template_left_ms": timings.get("openafis_template_left"),
                "openafis_template_right_ms": timings.get("openafis_template_right"),
                "openafis_match_ms": timings.get("openafis_match"),
                "left_minutiae_count": (
                    int(metadata["left_minutiae_count"]) if "left_minutiae_count" in metadata else None
                ),
                "right_minutiae_count": (
                    int(metadata["right_minutiae_count"]) if "right_minutiae_count" in metadata else None
                ),
            }
            handle.write(json.dumps(row, sort_keys=True) + "\n")
            handle.flush()
            written += 1
            if index % 250 == 0:
                rate = (time.perf_counter() - started) / max(written, 1)
                print(f"  {index}/{len(inputs.pairs)}  {time.perf_counter()-started:.0f}s  {rate*1000:.0f} ms/pair", flush=True)

    total = sum(1 for _ in results_path.open("r", encoding="utf-8"))
    print(f"\nstored {total} of {len(inputs.pairs)} outcomes in {time.perf_counter()-started:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
