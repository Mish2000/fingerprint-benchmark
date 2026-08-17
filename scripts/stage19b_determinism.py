#!/usr/bin/env python3
"""Section 15 — the small determinism check, on a subset frozen before it runs.

Not a second full run. Thirty pairs, chosen by a rule rather than by looking at
results:

.. code-block:: text

    10 SELF
    10 mated
    10 non-mated sanity

taking the first of each kind in manifest order, and — as the requirement asks —
the selection is biased on purpose toward pairs where at least one side carries
more than 128 minutiae. Those are the comparisons the capacity extension admits,
so they are the ones whose repeatability is actually in question; a subset of only
small templates would be testing the part that Gate A already covered.

Each pair runs twice through the whole route, extraction included. The requirement
is the same status and the same raw score both times.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from fpbench.adapters.nbis.xyt import read_xyt  # noqa: E402
from fpbench.adapters.openafis.capacity_extended import (  # noqa: E402
    translate_xyt_to_openafis_csv_uncapped as translate_xyt_to_openafis_csv,
)
from fpbench.experiments.stage18a_inputs import load_stage18a_inputs  # noqa: E402

MINDTCT = Path("/mnt/c/fingerprint-benchmark/build/nbis-5.0.0/658f9f54a8f2/bin/mindtct")
BRIDGE = Path("/home/nbisbuild/stage19b-openafis/bridge/build/fpbench_openafis_bridge")
SURVEY = Path("/mnt/c/Users/sirak/.cache/fpbench/private/stage19a/minutiae-survey.json")
OUTPUT = Path("/mnt/c/Users/sirak/.cache/fpbench/private/stage19b/determinism.json")

PER_KIND = 10
KINDS = {
    "self": ("plain_self", "roll_self"),
    "mated": ("plain_roll_mated",),
    "non_mated": ("plain_roll_non_mated",),
}


def to_local(path: Path) -> Path:
    text = str(path)
    if len(text) > 2 and text[1] == ":":
        return Path("/mnt/" + text[0].lower() + text[2:].replace("\\", "/"))
    return Path(text)


def compare_once(pair, by_id, work: Path, tag: str):
    """One full pass: extract both sides, translate both, match once."""
    templates = []
    counts = []
    for side, image_id in (("l", pair.left_image_id), ("r", pair.right_image_id)):
        image = by_id[image_id]
        root = work / f"{tag}-{side}"
        completed = subprocess.run(
            [str(MINDTCT), str(to_local(image.path)), str(root)], capture_output=True, text=True
        )
        if completed.returncode != 0:
            return ("MINDTCT_FAILED", -1, counts)
        minutiae = read_xyt(
            root.with_suffix(".xyt"), image_width=image.output_width, image_height=image.output_height
        )
        counts.append(len(minutiae))
        csv = translate_xyt_to_openafis_csv(
            minutiae, width=image.output_width, height=image.output_height
        )
        path = work / f"{tag}-{side}.csv"
        path.write_text(csv.text)
        templates.append(path)

    completed = subprocess.run(
        [str(BRIDGE), "match", str(templates[0]), str(templates[1]), "--format", "csv"],
        capture_output=True, text=True,
    )
    fields = completed.stdout.strip().split("\t")
    if len(fields) < 3:
        return ("BRIDGE_UNREADABLE", -1, counts)
    return (fields[1], int(fields[2]), counts)


def main() -> int:
    inputs = load_stage18a_inputs()
    by_id = inputs.images_by_id

    loadable_above = set()
    if SURVEY.is_file():
        survey = json.loads(SURVEY.read_text())
        loadable_above = {
            r["image_id"] for r in survey["records"]
            if r.get("minutiae") is not None and r["minutiae"] > 128
        }

    def big(pair) -> bool:
        return pair.left_image_id in loadable_above or pair.right_image_id in loadable_above

    selected = []
    for label, stages in KINDS.items():
        candidates = [p for p in inputs.pairs if p.protocol_stage in stages]
        # Prefer pairs the extension actually admits; fall back in manifest order.
        chosen = [p for p in candidates if big(p)][:PER_KIND]
        if len(chosen) < PER_KIND:
            chosen += [p for p in candidates if not big(p)][: PER_KIND - len(chosen)]
        selected.extend((label, p) for p in chosen)

    fingerprint = hashlib.sha256(
        json.dumps([p.pair_id for _, p in selected], sort_keys=True).encode()
    ).hexdigest()
    print(f"subset of {len(selected)} pairs, fingerprint {fingerprint[:16]}...")
    print(f"pairs with a >128 side: {sum(1 for _, p in selected if big(p))}")

    rows = []
    disagreements = []
    started = time.perf_counter()
    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        for index, (label, pair) in enumerate(selected, start=1):
            first = compare_once(pair, by_id, work, f"a{index}")
            second = compare_once(pair, by_id, work, f"b{index}")
            agrees = first[0] == second[0] and first[1] == second[1]
            rows.append({
                "pair_id": pair.pair_id, "kind": label, "stage": pair.protocol_stage,
                "minutiae": first[2], "has_side_above_128": big(pair),
                "first": {"status": first[0], "score": first[1]},
                "second": {"status": second[0], "score": second[1]},
                "agrees": agrees,
            })
            if not agrees:
                disagreements.append(rows[-1])

    report = {
        "kind": "stage_19b_determinism",
        "subset_size": len(selected),
        "subset_fingerprint": fingerprint,
        "subset_selection_rule": "first PER_KIND of each pair kind in manifest order, preferring pairs with a >128-minutiae side",
        "pairs_with_side_above_128": sum(1 for r in rows if r["has_side_above_128"]),
        "agreements": sum(1 for r in rows if r["agrees"]),
        "disagreements": len(disagreements),
        "deterministic": not disagreements,
        "wall_seconds": round(time.perf_counter() - started, 1),
        "rows": rows,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    print(f"agreements   : {report['agreements']}/{report['subset_size']}")
    print(f"disagreements: {report['disagreements']}")
    print("deterministic" if report["deterministic"] else "NOT DETERMINISTIC")
    for row in disagreements[:5]:
        print("  ", row["pair_id"], row["first"], row["second"])
    return 0 if report["deterministic"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
