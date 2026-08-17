#!/usr/bin/env python3
"""Gate A — the inertness test. Section 6 of the Stage 19B requirements.

Takes exactly the pairs that carried a score in Stage 19A and reruns them against
the capacity-extended build. The requirement is byte-exact equality:

.. code-block:: text

    baseline scored pairs = 1583
    patched OK            = 1583
    score mismatches      = 0
    status regressions    = 0

No tolerance, no correlation, no "close enough".

HOW THE MATCHER IS ISOLATED

The templates are extracted **once** and both bridges are run over the *same*
CSV files. That removes MINDTCT from the comparison entirely: if the two binaries
disagree, the only thing that differs between them is the patch. Rerunning the
whole adapter twice would also work, but a spurious difference from the extractor
would be indistinguishable from a real one from the patch — and this gate exists
precisely to attribute a difference.

Three comparisons are made, and all three must hold:

1. reproduced-unpatched == stored Stage 19A  — the pipeline reproduces at all,
   which also demonstrates MINDTCT determinism over these images;
2. reproduced-patched == reproduced-unpatched — the inertness claim itself;
3. every pair that was OK is still OK — no status regression.

WHAT PASSING DOES NOT PROVE

That behaviour *above* 128 minutiae is upstream-validated. It is not, and cannot
be: upstream refuses that region, so there is no upstream behaviour to agree with.
Gate A shows only that the change is inert where upstream already worked.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from fpbench.adapters.nbis.xyt import read_xyt  # noqa: E402
from fpbench.adapters.openafis.translation import translate_xyt_to_openafis_csv  # noqa: E402
from fpbench.experiments.stage18a_inputs import load_stage18a_inputs  # noqa: E402

MINDTCT = Path("/mnt/c/fingerprint-benchmark/build/nbis-5.0.0/658f9f54a8f2/bin/mindtct")
BRIDGE_UNPATCHED = Path("/home/nbisbuild/stage18a-openafis/bridge/build/fpbench_openafis_bridge")
BRIDGE_PATCHED = Path("/home/nbisbuild/stage19b-openafis/bridge/build/fpbench_openafis_bridge")

STAGE19A_OUTCOMES = Path("/mnt/c/Users/sirak/.cache/fpbench/private/stage19a/pair-outcomes.jsonl")
OUTPUT = Path("/mnt/c/Users/sirak/.cache/fpbench/private/stage19b/gate-a.json")


def to_local(path: Path) -> Path:
    text = str(path)
    if len(text) > 2 and text[1] == ":":
        return Path("/mnt/" + text[0].lower() + text[2:].replace("\\", "/"))
    return Path(text)


def run_bridge(binary: Path, jobs: str) -> dict[str, tuple[str, int]]:
    completed = subprocess.run(
        [str(binary), "batch", "--format", "csv"], input=jobs, text=True, capture_output=True
    )
    results: dict[str, tuple[str, int]] = {}
    for line in completed.stdout.splitlines():
        fields = line.split("\t")
        if len(fields) >= 3:
            results[fields[0]] = (fields[1], int(fields[2]))
    return results


def main() -> int:
    inputs = load_stage18a_inputs()
    by_id = inputs.images_by_id
    pairs_by_id = {pair.pair_id: pair for pair in inputs.pairs}

    baseline = {}
    with STAGE19A_OUTCOMES.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if row["status"] == "OK":
                baseline[row["pair_id"]] = int(row["raw_score"])
    print(f"Stage 19A scored pairs: {len(baseline)}")

    needed = sorted({
        side
        for pair_id in baseline
        for side in (pairs_by_id[pair_id].left_image_id, pairs_by_id[pair_id].right_image_id)
    })
    print(f"distinct images to extract: {len(needed)}")

    started = time.perf_counter()
    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        templates: dict[str, Path] = {}
        for index, image_id in enumerate(needed, start=1):
            image = by_id[image_id]
            root = work / f"x{index}"
            completed = subprocess.run(
                [str(MINDTCT), str(to_local(image.path)), str(root)], capture_output=True, text=True
            )
            if completed.returncode != 0:
                print(f"mindtct failed on {image_id}: {completed.returncode}")
                return 1
            minutiae = read_xyt(
                root.with_suffix(".xyt"),
                image_width=image.output_width, image_height=image.output_height,
            )
            csv = translate_xyt_to_openafis_csv(
                minutiae, width=image.output_width, height=image.output_height
            )
            path = work / f"{image_id}.csv"
            path.write_text(csv.text)
            templates[image_id] = path
            if index % 200 == 0:
                print(f"  extracted {index}/{len(needed)}  {time.perf_counter()-started:.0f}s", flush=True)

        jobs = "".join(
            f"{pair_id}\t{templates[pairs_by_id[pair_id].left_image_id]}"
            f"\t{templates[pairs_by_id[pair_id].right_image_id]}\n"
            for pair_id in sorted(baseline)
        )
        print("running the unpatched bridge ...", flush=True)
        unpatched = run_bridge(BRIDGE_UNPATCHED, jobs)
        print("running the patched bridge ...", flush=True)
        patched = run_bridge(BRIDGE_PATCHED, jobs)

    # 1. does the pipeline reproduce Stage 19A at all?
    reproduction_mismatches = [
        {"pair_id": p, "stored": baseline[p], "reproduced": unpatched.get(p, ("MISSING", -1))[1]}
        for p in sorted(baseline)
        if unpatched.get(p, ("MISSING", -1))[1] != baseline[p]
    ]
    # 2. the inertness claim: same templates, two binaries
    inertness_mismatches = [
        {"pair_id": p, "unpatched": unpatched[p], "patched": patched.get(p, ("MISSING", -1))}
        for p in sorted(unpatched)
        if patched.get(p) != unpatched[p]
    ]
    # 3. status regressions
    regressions = [p for p in sorted(baseline) if patched.get(p, ("MISSING", -1))[0] != "OK"]

    passed = not reproduction_mismatches and not inertness_mismatches and not regressions
    report = {
        "kind": "stage_19b_gate_a",
        "gate": "CAPACITY_EXTENSION_INERTNESS",
        "baseline_scored_pairs": len(baseline),
        "patched_ok": sum(1 for p in baseline if patched.get(p, ("", -1))[0] == "OK"),
        "reproduction_mismatches": len(reproduction_mismatches),
        "score_mismatches": len(inertness_mismatches),
        "status_regressions": len(regressions),
        "exact_score_matches": sum(
            1 for p in baseline if patched.get(p, ("", -1))[1] == baseline[p]
        ),
        "outcome": "CAPACITY_EXTENSION_INERTNESS_PASS" if passed else "CAPACITY_EXTENSION_INERTNESS_FAIL",
        "what_this_does_not_prove": (
            "that behaviour above 128 minutiae is upstream-validated; upstream refuses that "
            "region, so there is no upstream behaviour to agree with"
        ),
        "first_reproduction_mismatches": reproduction_mismatches[:20],
        "first_inertness_mismatches": inertness_mismatches[:20],
        "first_status_regressions": regressions[:20],
        "wall_seconds": round(time.perf_counter() - started, 1),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    print()
    print(f"baseline scored pairs  : {report['baseline_scored_pairs']}")
    print(f"patched OK             : {report['patched_ok']}")
    print(f"exact score matches    : {report['exact_score_matches']}")
    print(f"reproduction mismatches: {report['reproduction_mismatches']}")
    print(f"score mismatches       : {report['score_mismatches']}")
    print(f"status regressions     : {report['status_regressions']}")
    print()
    print(report["outcome"])
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
