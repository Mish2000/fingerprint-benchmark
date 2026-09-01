"""End-to-end pore-based verification on L3-SF: detector -> descriptors -> score.

Pipeline under test (all existing components, no new models, no blocked weights):
  1. Pore detection  — survey repo's pretrained FCN (out_of_the_box_detect
     flow: model forward + entireImage.apply_nms, identical parameters).
  2. Descriptors     — Dahia & Segundo utils.sift_descriptors (OpenCV SIFT at
     detected pore locations, their default scale=4, CLAHE normalisation).
  3. Match score     — Dahia & Segundo matching.spatial (Pamplona Segundo &
     Lemes 2015 spatial-consistency score over bidirectional correspondences,
     distance-ratio thr as in their recognize.py, 0.7).

Protocol (PolyU-style, shrunk): first N fingers of L3-SF R1.
  genuine  : all 25 cross-"session" pairs  f_1_i vs f_2_j  per finger
  impostor : f_1_1 of finger a vs f_2_1 of finger b, for all a<b

Outputs: scores CSV + summary JSON (EER for spatial score and for the plain
bidirectional-correspondence count) into --out-dir.

Third-party code is imported in place from V2/third_party (no edits):
  - tensorflow is stubbed in sys.modules — dahia utils.py imports it at module
    level, but none of the functions used here touch it.
  - cv2.xfeatures2d.SIFT_create is aliased to cv2.SIFT_create (SIFT moved into
    OpenCV main after the patent expired; dahia pins OpenCV 3.4-contrib).
"""
import argparse
import csv
import json
import os
import sys
import time
import types

import numpy as np


def eer_from_scores(genuine, impostor):
    """EER via threshold sweep over the pooled score set (higher = more similar)."""
    scores = np.concatenate([genuine, impostor])
    labels = np.concatenate([np.ones(len(genuine)), np.zeros(len(impostor))])
    order = np.argsort(-scores)
    scores, labels = scores[order], labels[order]
    n_gen, n_imp = len(genuine), len(impostor)
    best = (1.0, None)
    fa = 0  # impostors accepted so far (score above threshold)
    fr = n_gen  # genuines rejected so far
    # sweep thresholds just below each score
    for i in range(len(scores)):
        if labels[i] == 0:
            fa += 1
        else:
            fr -= 1
        fmr = fa / n_imp
        fnmr = fr / n_gen
        if abs(fmr - fnmr) < best[0]:
            best = (abs(fmr - fnmr), (fmr + fnmr) / 2)
    return best[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--survey-dir", required=True)
    ap.add_argument("--dahia-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--fingers", type=int, default=12)
    ap.add_argument("--features", type=int, default=40)
    ap.add_argument("--ratio-thr", type=float, default=0.7)
    ap.add_argument("--device", default="cpu")
    args = ap.parse_args()

    survey_dir = os.path.abspath(args.survey_dir)
    dahia_dir = os.path.abspath(args.dahia_dir)
    out_dir = os.path.abspath(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)
    tmp_pore = os.path.join(out_dir, "tmp_pore")
    tmp_coord = os.path.join(out_dir, "tmp_coord")
    os.makedirs(tmp_pore, exist_ok=True)
    os.makedirs(tmp_coord, exist_ok=True)

    # --- third-party imports, in place, unmodified -------------------------
    sys.modules.setdefault("tensorflow", types.ModuleType("tensorflow"))
    sys.path.insert(0, dahia_dir)    # utils (dahia), matching
    sys.path.insert(0, survey_dir)   # util package, entireImage, architectures

    import cv2
    if not hasattr(cv2, "xfeatures2d"):
        cv2.xfeatures2d = types.SimpleNamespace(SIFT_create=cv2.SIFT_create)

    import torch
    import torchvision
    import entireImage                      # survey
    from util.utils import loadModel        # survey
    import utils as dahia_utils             # dahia (tf stubbed)
    import matching                         # dahia

    # --- survey model, exactly as out_of_the_box_detect.py ----------------
    model = loadModel(
        modelPath=os.path.join(survey_dir, "out_of_the_box_detect", "models",
                               str(args.features)),
        device=torch.device(args.device),
        NUMBERLAYERS=8, NUMBERFEATURES=args.features, MAXPOOLING=False,
        WINDOWSIZE=17, residual=False, gabriel=False, su=False)
    model.eval()
    model.to(args.device)
    to_tensor = torchvision.transforms.Compose(
        [torchvision.transforms.ToTensor()])

    def read_coords(path, h, w, window=17):
        pts, half = [], window // 2
        with open(path) as f:
            for line in f:
                line = line.replace(",", " ").split()
                if len(line) < 2 or not line[0].isdigit():
                    continue
                x, y = int(line[0]) - 1, int(line[1]) - 1
                if half < x < h - half and half < y < w - half:
                    pts.append([x, y])
        return np.array(pts, dtype=int)

    counter = {"i": 0}

    def detect(img):
        """Survey flow: forward pass + apply_nms with upstream's parameters."""
        counter["i"] += 1
        idx = counter["i"]
        with torch.no_grad():
            pred = model(to_tensor(img).unsqueeze(0).float()
                         .to(args.device)).cpu()
        entireImage.apply_nms(pred, 0.65, 17, 0.2, tmp_pore + "/", idx,
                              tmp_coord + "/", 17)
        return read_coords(os.path.join(tmp_coord, f"{idx}.txt"),
                           img.shape[0], img.shape[1])

    # --- data: first N fingers of R1 --------------------------------------
    r1 = os.path.join(survey_dir, "L3SF_V2", "L3-SF", "R1")
    finger_ids = sorted(
        {f.split("_")[0] for f in os.listdir(r1)}, key=int)[:args.fingers]
    print(f"fingers: {finger_ids}")

    cache = {}  # (finger, session, imp) -> (pts, descs)
    t0 = time.time()
    for fid in finger_ids:
        for ses in (1, 2):
            for imp in range(1, 6):
                path = os.path.join(r1, f"{fid}_{ses}_{imp}.png")
                img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
                pts = detect(img).astype(np.float32)
                # float32: cv2 3.4.18's KeyPoint.convert rejects int arrays
                descs = dahia_utils.sift_descriptors(img, pts)
                cache[(fid, ses, imp)] = (pts, descs)
    n_imgs = len(cache)
    t_prep = time.time() - t0
    pores = [len(p) for p, _ in cache.values()]
    print(f"prepared {n_imgs} images in {t_prep:.1f}s "
          f"({t_prep/n_imgs:.2f}s/img); pores/img min={min(pores)} "
          f"median={int(np.median(pores))} max={max(pores)}")

    def score(a, b):
        pts1, d1 = cache[a]
        pts2, d2 = cache[b]
        if len(d1) == 0 or len(d2) == 0:
            return 0.0, 0
        sp = matching.spatial(d1, d2, pts1, pts2, thr=args.ratio_thr)
        nc = matching.basic(d1, d2, thr=args.ratio_thr)
        return float(sp), int(nc)

    rows = []
    t0 = time.time()
    for fid in finger_ids:                      # genuine: 25 per finger
        for i in range(1, 6):
            for j in range(1, 6):
                sp, nc = score((fid, 1, i), (fid, 2, j))
                rows.append(dict(kind="genuine", left=f"{fid}_1_{i}",
                                 right=f"{fid}_2_{j}", spatial=sp, count=nc))
    for a in range(len(finger_ids)):            # impostor: a<b, first images
        for b in range(a + 1, len(finger_ids)):
            sp, nc = score((finger_ids[a], 1, 1), (finger_ids[b], 2, 1))
            rows.append(dict(kind="impostor",
                             left=f"{finger_ids[a]}_1_1",
                             right=f"{finger_ids[b]}_2_1",
                             spatial=sp, count=nc))
    t_match = time.time() - t0

    gen_sp = np.array([r["spatial"] for r in rows if r["kind"] == "genuine"])
    imp_sp = np.array([r["spatial"] for r in rows if r["kind"] == "impostor"])
    gen_nc = np.array([r["count"] for r in rows if r["kind"] == "genuine"])
    imp_nc = np.array([r["count"] for r in rows if r["kind"] == "impostor"])

    summary = dict(
        fingers=finger_ids, images=n_imgs,
        genuine_pairs=len(gen_sp), impostor_pairs=len(imp_sp),
        prep_seconds=round(t_prep, 1), match_seconds=round(t_match, 1),
        pores_per_image=dict(min=int(min(pores)),
                             median=int(np.median(pores)),
                             max=int(max(pores))),
        spatial=dict(
            eer=eer_from_scores(gen_sp, imp_sp),
            genuine=dict(median=float(np.median(gen_sp)),
                         p10=float(np.percentile(gen_sp, 10))),
            impostor=dict(median=float(np.median(imp_sp)),
                          p90=float(np.percentile(imp_sp, 90)))),
        count=dict(
            eer=eer_from_scores(gen_nc.astype(float), imp_nc.astype(float)),
            genuine_median=float(np.median(gen_nc)),
            impostor_median=float(np.median(imp_nc))),
        parameters=dict(features=args.features, window=17, nms_prob=0.65,
                        nms_inter=0.2, sift_scale=4, ratio_thr=args.ratio_thr),
    )

    with open(os.path.join(out_dir, "scores.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    with open(os.path.join(out_dir, "summary.json"), "w") as f:
        json.dump(summary, f, indent=1)

    print(json.dumps(summary["spatial"], indent=1))
    print(json.dumps(summary["count"], indent=1))
    print(f"EER (spatial) = {summary['spatial']['eer']:.4f}  "
          f"EER (count) = {summary['count']['eer']:.4f}")
    print(f"wrote {out_dir}/scores.csv and summary.json")


if __name__ == "__main__":
    main()
