#!/usr/bin/env python3
"""How many minutiae MINDTCT finds in each of the 3,000 canonical images.

This is a measurement, not a pilot. It runs the extractor half of the frozen
route and records a count per image; it produces no score, compares nothing, and
**cannot change the route** — section 10 forbids the only thing a bad answer
would tempt anyone into (keeping a best-128), and section 13 forbids choosing
anything here by how the numbers look.

It exists because OpenAFIS declares a hard ceiling of 128 minutiae per template
and refuses anything above it. Whether that ceiling bites on rolled impressions
decides how much of Stage 19A's 6,000 can carry a score at all, and section 21
asks for the minutiae-count distribution regardless.

Writes one JSON document. Run inside WSL, where MINDTCT lives.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from fpbench.adapters.nbis.xyt import XytFormatError, read_xyt  # noqa: E402
from fpbench.adapters.openafis.translation import (  # noqa: E402
    OPENAFIS_MAXIMUM_MINUTIAE,
    OPENAFIS_MINIMUM_MINUTIAE,
)
from fpbench.experiments.stage18a_inputs import load_stage18a_inputs  # noqa: E402

MINDTCT = Path("/mnt/c/fingerprint-benchmark/build/nbis-5.0.0/658f9f54a8f2/bin/mindtct")
OUTPUT = Path("/mnt/c/Users/sirak/.cache/fpbench/private/stage19a/minutiae-survey.json")


def to_wsl(path: Path) -> Path:
    text = str(path)
    if len(text) > 2 and text[1] == ":":
        return Path("/mnt/" + text[0].lower() + text[2:].replace("\\", "/"))
    return Path(text)


def main() -> int:
    inputs = load_stage18a_inputs()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, object]] = []
    started = time.perf_counter()
    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        root = work / "survey"
        for index, image in enumerate(inputs.images, start=1):
            began = time.perf_counter_ns()
            completed = subprocess.run(
                [str(MINDTCT), str(to_wsl(image.path)), str(root)],
                capture_output=True, text=True,
            )
            elapsed_ms = (time.perf_counter_ns() - began) / 1_000_000
            if completed.returncode != 0:
                records.append({
                    "image_id": image.image_id, "status": "MINDTCT_FAILED",
                    "minutiae": None, "ms": round(elapsed_ms, 3),
                    "exit_code": completed.returncode,
                })
                continue
            try:
                minutiae = read_xyt(
                    root.with_suffix(".xyt"),
                    image_width=image.output_width, image_height=image.output_height,
                )
            except XytFormatError as exc:
                records.append({
                    "image_id": image.image_id, "status": "INVALID_XYT",
                    "minutiae": None, "ms": round(elapsed_ms, 3), "kind": exc.kind,
                })
                continue
            count = len(minutiae)
            if count < OPENAFIS_MINIMUM_MINUTIAE:
                status = "BELOW_OPENAFIS_MINIMUM"
            elif count > OPENAFIS_MAXIMUM_MINUTIAE:
                status = "ABOVE_OPENAFIS_MAXIMUM"
            else:
                status = "LOADABLE"
            records.append({
                "image_id": image.image_id, "status": status,
                "minutiae": count, "ms": round(elapsed_ms, 3),
                "width": image.output_width, "height": image.output_height,
            })
            if index % 250 == 0:
                print(f"  {index}/{len(inputs.images)}  {time.perf_counter() - started:.0f}s", flush=True)

    def kind(image_id: str) -> str:
        return "roll" if "_roll_" in image_id else "plain"

    summary: dict[str, object] = {
        "kind": "stage_19a_minutiae_survey",
        "images": len(records),
        "openafis_bounds": f"{OPENAFIS_MINIMUM_MINUTIAE}..{OPENAFIS_MAXIMUM_MINUTIAE}",
        "wall_seconds": round(time.perf_counter() - started, 1),
        "status_counts": dict(sorted(Counter(str(r["status"]) for r in records).items())),
    }
    for impression in ("plain", "roll"):
        subset = [r for r in records if kind(str(r["image_id"])) == impression]
        counts = sorted(int(r["minutiae"]) for r in subset if r["minutiae"] is not None)
        summary[impression] = {
            "images": len(subset),
            "status_counts": dict(sorted(Counter(str(r["status"]) for r in subset).items())),
            "min": counts[0] if counts else None,
            "median": counts[len(counts) // 2] if counts else None,
            "p95": counts[int(0.95 * len(counts)) - 1] if counts else None,
            "max": counts[-1] if counts else None,
            "above_128": sum(1 for c in counts if c > OPENAFIS_MAXIMUM_MINUTIAE),
        }
    summary["records"] = records
    OUTPUT.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")

    print(json.dumps({k: v for k, v in summary.items() if k != "records"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
