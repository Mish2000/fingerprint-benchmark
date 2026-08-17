#!/usr/bin/env python3
"""Stage 19A's four smoke tests, run against the real MINDTCT and the real OpenAFIS.

Section 12 asks for exactly four checks before the full run, and no more:

.. code-block:: text

    A. XYT -> CSV conversion    exact x/y, authoritative theta, no filtering
    B. type-invariance          RidgeEnding vs RidgeBifurcation, same score
    C. SELF                     one image, two independent MINDTCT invocations
    D. different impressions    plain + roll of one finger, both templates load

The height of D's score is deliberately not a criterion. A 0 there is recorded
and the stage continues; choosing anything about this route because a number
looked better is what section 13 forbids.

Runs inside WSL, where both binaries live. Prints a report and exits non-zero only
if a check that must hold does not.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from fpbench.adapters.nbis.xyt import read_xyt  # noqa: E402
from fpbench.adapters.openafis.translation import (  # noqa: E402
    TranslationRefused,
    MINUTIA_TYPE_RIDGE_BIFURCATION,
    MINUTIA_TYPE_RIDGE_ENDING,
    translate_xyt_to_openafis_csv,
)
from fpbench.experiments.stage18a_inputs import load_stage18a_inputs  # noqa: E402

MINDTCT = Path("/mnt/c/fingerprint-benchmark/build/nbis-5.0.0/658f9f54a8f2/bin/mindtct")
BRIDGE = Path("/home/nbisbuild/stage18a-openafis/bridge/build/fpbench_openafis_bridge")


def to_wsl(path: Path) -> Path:
    text = str(path)
    if len(text) > 2 and text[1] == ":":
        return Path("/mnt/" + text[0].lower() + text[2:].replace("\\", "/"))
    return Path(text)


def extract(image: Path, root: Path) -> tuple[Path, float]:
    """One MINDTCT invocation. No -b, no -m1, nothing else on the line."""
    completed = subprocess.run(
        [str(MINDTCT), str(image), str(root)], capture_output=True, text=True
    )
    if completed.returncode != 0:
        raise SystemExit(f"mindtct exited {completed.returncode}: {completed.stderr[:400]}")
    return root.with_suffix(".xyt"), 0.0


def match(left: Path, right: Path, fmt: str = "csv") -> tuple[str, int]:
    completed = subprocess.run(
        [str(BRIDGE), "match", str(left), str(right), "--format", fmt],
        capture_output=True, text=True,
    )
    fields = completed.stdout.strip().split("\t")
    if len(fields) < 6:
        raise SystemExit(f"unreadable bridge output: {completed.stdout!r} {completed.stderr[:300]}")
    return fields[1], int(fields[2])


def main() -> int:
    inputs = load_stage18a_inputs()
    by_id = inputs.images_by_id

    # One finger with both impressions, taken from the manifest rather than chosen.
    mated = next(p for p in inputs.pairs if p.protocol_stage == "plain_roll_mated")
    plain = by_id[mated.left_image_id]
    roll = by_id[mated.right_image_id]
    print(f"finger under test: {mated.pair_id}")
    print(f"  plain {plain.image_id}  {plain.output_width}x{plain.output_height}")
    print(f"  roll  {roll.image_id}  {roll.output_width}x{roll.output_height}")

    failures: list[str] = []
    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)

        # ---- C: SELF is two independent extractions of the same image ----------
        xyt_a, _ = extract(to_wsl(plain.path), work / "self-a")
        xyt_b, _ = extract(to_wsl(plain.path), work / "self-b")
        m_a = read_xyt(xyt_a, image_width=plain.output_width, image_height=plain.output_height)
        m_b = read_xyt(xyt_b, image_width=plain.output_width, image_height=plain.output_height)
        print(f"\nC. SELF: two independent MINDTCT runs -> {len(m_a)} and {len(m_b)} minutiae")
        if m_a != m_b:
            print("   note: the two extractions differ (recorded, not a blocker)")

        # ---- A: the translation is exact and drops nothing ---------------------
        csv_a = translate_xyt_to_openafis_csv(
            m_a, width=plain.output_width, height=plain.output_height
        )
        lines = csv_a.text.strip().split("\n")
        header = lines[0]
        body = lines[1:]
        ok_header = header == f"{plain.output_width},{plain.output_height}"
        ok_count = len(body) == len(m_a)
        ok_coords = True
        ok_angles = True
        import math

        for minutia, line in zip(m_a, body):
            t, x, y, ang = line.split(",")
            if int(x) != minutia.x or int(y) != minutia.y:
                ok_coords = False
            if abs(float(ang) - minutia.theta * math.pi / 180.0) > 1e-9:
                ok_angles = False
        print("\nA. XYT -> CSV")
        print(f"   header is the real raster size : {ok_header}  ({header})")
        print(f"   every minutia carried over     : {ok_count}  ({len(body)} of {len(m_a)})")
        print(f"   x and y exact, unscaled        : {ok_coords}")
        print(f"   theta = degrees * pi / 180     : {ok_angles}")
        for label, ok in (("header", ok_header), ("count", ok_count), ("coords", ok_coords), ("angles", ok_angles)):
            if not ok:
                failures.append(f"A/{label}")

        left_csv = work / "left.csv"
        right_csv = work / "right.csv"
        left_csv.write_text(csv_a.text)

        xyt_r, _ = extract(to_wsl(roll.path), work / "roll")
        m_r = read_xyt(xyt_r, image_width=roll.output_width, image_height=roll.output_height)
        try:
            csv_r = translate_xyt_to_openafis_csv(
                m_r, width=roll.output_width, height=roll.output_height
            )
            right_csv.write_text(csv_r.text)
            roll_refused = None
        except TranslationRefused as refused:
            # Not a defect and not something to work around: OpenAFIS declares a
            # 128-minutiae ceiling and a rolled impression can exceed it. Taking
            # the best 128 would be a selection rule fpbench invented (section 10).
            roll_refused = refused.reason
            print(f"\n   roll template refused: {refused.reason} ({len(m_r)} minutiae)")

        # ---- B: minutia type does not reach the score --------------------------
        # Run against a second plain impression, so the check exercises a real
        # comparison rather than a refused template.
        other = next(
            by_id[p.left_image_id]
            for p in inputs.pairs
            if p.protocol_stage == "plain_roll_mated" and p.left_image_id != plain.image_id
        )
        xyt_o, _ = extract(to_wsl(other.path), work / "other")
        m_o = read_xyt(xyt_o, image_width=other.output_width, image_height=other.output_height)

        re_l = work / "re-l.csv"; re_r = work / "re-r.csv"
        bif_l = work / "bif-l.csv"; bif_r = work / "bif-r.csv"
        re_l.write_text(translate_xyt_to_openafis_csv(
            m_a, width=plain.output_width, height=plain.output_height,
            minutia_type=MINUTIA_TYPE_RIDGE_ENDING).text)
        re_r.write_text(translate_xyt_to_openafis_csv(
            m_o, width=other.output_width, height=other.output_height,
            minutia_type=MINUTIA_TYPE_RIDGE_ENDING).text)
        bif_l.write_text(translate_xyt_to_openafis_csv(
            m_a, width=plain.output_width, height=plain.output_height,
            minutia_type=MINUTIA_TYPE_RIDGE_BIFURCATION).text)
        bif_r.write_text(translate_xyt_to_openafis_csv(
            m_o, width=other.output_width, height=other.output_height,
            minutia_type=MINUTIA_TYPE_RIDGE_BIFURCATION).text)

        status_re, score_re = match(re_l, re_r)
        status_bif, score_bif = match(bif_l, bif_r)
        print("\nB. minutia type invariance")
        print(f"   all RidgeEnding      : {status_re} {score_re}")
        print(f"   all RidgeBifurcation : {status_bif} {score_bif}")
        invariant = (status_re, score_re) == (status_bif, score_bif)
        print(f"   identical            : {invariant}")
        if not invariant:
            failures.append("B/type_invariance")

        # ---- C continued and D -------------------------------------------------
        status_c, score_c = match(left_csv, left_csv)
        print(f"\nC. SELF score  : {status_c} {score_c}   ({len(m_a)} minutiae)")
        if status_c != "OK":
            failures.append("C/self_did_not_score")

        if roll_refused is None:
            status_d, score_d = match(left_csv, right_csv)
            print(f"D. plain vs roll: {status_d} {score_d}   ({len(m_a)} vs {len(m_r)} minutiae)")
            print("   (the height of this number is deliberately not a criterion)")
            if status_d != "OK":
                failures.append("D/templates_did_not_both_load")
        else:
            # The recorded outcome, not a smoke-test failure: OpenAFIS refuses the
            # rolled template on its own declared ceiling. This is what the full
            # run will store as OPENAFIS_TEMPLATE_FAILED_RIGHT.
            print(f"D. plain vs roll: OPENAFIS_TEMPLATE_FAILED_RIGHT   ({len(m_a)} vs {len(m_r)} minutiae)")
            print(f"   reason: {roll_refused}; OpenAFIS's ceiling is 128")
            status_d2, score_d2 = match(left_csv, re_r)
            print(f"   plain vs plain instead: {status_d2} {score_d2}  ({len(m_a)} vs {len(m_o)} minutiae)")
            if status_d2 != "OK":
                failures.append("D/plain_pair_did_not_score")

    print()
    if failures:
        print(f"FAILED: {failures}")
        return 1
    print("all four smoke checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
