"""Evaluate survey-repo pore detections against bundled L3-SF ground truth.

Criterion: mutual-nearest-neighbour correspondence, copied faithfully from
third_party/pore-survey/validate.py lines 133-191 (test()): a ground-truth
pore g counts as a true detection iff g's nearest prediction p has g as its
nearest ground-truth point. No distance threshold — exactly as upstream.

Because the survey FCN uses valid convolutions (architectures/net17nomax.py,
padding="valid"), prediction coordinates live in the prediction-map frame,
offset by half the receptive field from image coordinates. We report both
raw (upstream convention) and offset-corrected results.

Usage:
  python eval_pore_detection.py --survey-dir <path> --range 1-50 [--offset 8]
"""
import argparse
import json
import os

import numpy as np
from scipy.spatial import distance_matrix


def read_coords(path):
    pts = []
    with open(path) as f:
        for line in f:
            line = line.replace(",", " ").split()
            if len(line) < 2 or not line[0].lstrip("-").isdigit():
                continue
            pts.append([int(line[0]) - 1, int(line[1]) - 1])
    return np.array(pts, dtype=float)


def mutual_nn_stats(gt, pred):
    """validate.py's criterion: mutual nearest neighbours, no threshold."""
    if len(gt) == 0 or len(pred) == 0:
        return 0
    d = distance_matrix(pred, gt)          # [P, G]
    nearest_pred_for_gt = np.argmin(d, axis=0)   # for each gt: pred index
    nearest_gt_for_pred = np.argmin(d, axis=1)   # for each pred: gt index
    td = sum(
        1 for g in range(len(gt))
        if nearest_gt_for_pred[nearest_pred_for_gt[g]] == g
    )
    return td


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--survey-dir", required=True)
    ap.add_argument("--range", default="1-50")
    ap.add_argument("--offset", type=int, default=8,
                    help="map-to-image coordinate offset to test alongside raw")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    lo, hi = (int(x) for x in args.range.split("-"))
    gt_dir = os.path.join(args.survey_dir, "dataset", "PoreGroundTruthMarked")
    pred_dir = os.path.join(args.survey_dir, "out_of_the_box_detect",
                            "Prediction", "Coordinates")

    rows = []
    for i in range(lo, hi + 1):
        gt = read_coords(os.path.join(gt_dir, f"{i}.txt"))
        pred = read_coords(os.path.join(pred_dir, f"{i}.txt"))
        for name, shift in (("raw", 0), (f"+{args.offset}px", args.offset)):
            p = pred + shift if shift else pred
            td = mutual_nn_stats(gt, p)
            precision = td / len(p) if len(p) else 0.0
            recall = td / len(gt) if len(gt) else 0.0
            f = (2 * precision * recall / (precision + recall)
                 if precision + recall else 0.0)
            rows.append(dict(image=i, variant=name, gt=len(gt), pred=len(p),
                             td=td, precision=precision, recall=recall, f=f))

    for variant in ("raw", f"+{args.offset}px"):
        sel = [r for r in rows if r["variant"] == variant]
        mp = float(np.mean([r["precision"] for r in sel]))
        mr = float(np.mean([r["recall"] for r in sel]))
        mf = float(np.mean([r["f"] for r in sel]))
        print(f"[{variant}] images {lo}-{hi}: "
              f"mean P={mp:.4f} R={mr:.4f} F={mf:.4f}")

    if args.out:
        with open(args.out, "w") as f:
            json.dump(rows, f, indent=1)
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
