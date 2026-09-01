"""Compare pore-only vs SourceAFIS-only vs fused scores on the same pair list.

Inputs: the pore run's scores.csv (spatial score) and safis_scores.csv from
sourceafis_pairs.py, joined on (kind, left, right).

Reported EERs:
  1. pore spatial score alone
  2. SourceAFIS score alone
  3. min-max-sum fusion   — parameter-free demonstration (normalisation uses
     the pooled score range, i.e. test statistics; demonstrative only)
  4. logistic-regression fusion with leave-one-finger-out cross-validation —
     no pair's own finger contributes to the weights that score it.

log1p is applied to the pore spatial score before fusion (it is heavy-tailed:
medians 0.07 impostor vs 521 genuine).
"""
import argparse
import csv
import json

import numpy as np


def eer_from_scores(genuine, impostor):
    scores = np.concatenate([genuine, impostor])
    labels = np.concatenate([np.ones(len(genuine)), np.zeros(len(impostor))])
    order = np.argsort(-scores)
    labels = labels[order]
    n_gen, n_imp = len(genuine), len(impostor)
    best = (1.0, 1.0)
    fa, fr = 0, n_gen
    for lab in labels:
        if lab == 0:
            fa += 1
        else:
            fr -= 1
        fmr, fnmr = fa / n_imp, fr / n_gen
        if abs(fmr - fnmr) < best[0]:
            best = (abs(fmr - fnmr), (fmr + fnmr) / 2)
    return best[1]


def logistic_loo(x, y, finger_of_row):
    """Leave-one-finger-out logistic regression fusion scores."""
    from numpy.linalg import norm

    def fit(xtr, ytr, iters=500, lr=0.5):
        w = np.zeros(xtr.shape[1] + 1)
        xb = np.hstack([xtr, np.ones((len(xtr), 1))])
        for _ in range(iters):
            p = 1 / (1 + np.exp(-xb @ w))
            g = xb.T @ (p - ytr) / len(ytr)
            w -= lr * g
            if norm(g) < 1e-7:
                break
        return w

    fused = np.zeros(len(x))
    for f in sorted(set(finger_of_row)):
        test = np.array([fo == f for fo in finger_of_row])
        w = fit(x[~test], y[~test])
        xb = np.hstack([x[test], np.ones((test.sum(), 1))])
        fused[test] = xb @ w  # decision value, monotone in probability
    return fused


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pore", required=True)
    ap.add_argument("--safis", required=True)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    with open(args.pore) as f:
        pore = {(r["kind"], r["left"], r["right"]): float(r["spatial"])
                for r in csv.DictReader(f)}
    with open(args.safis) as f:
        safis = {(r["kind"], r["left"], r["right"]): float(r["safis"])
                 for r in csv.DictReader(f) if r["safis"] != ""}

    keys = [k for k in pore if k in safis]
    dropped = len(pore) - len(keys)
    y = np.array([1.0 if k[0] == "genuine" else 0.0 for k in keys])
    ps = np.log1p(np.array([pore[k] for k in keys]))
    ss = np.array([safis[k] for k in keys])
    # a pair's "finger" for LOO grouping: the left image's finger id
    finger = [k[1].split("_")[0] for k in keys]

    def split(v):
        return v[y == 1], v[y == 0]

    eer_pore = eer_from_scores(*split(ps))
    eer_safis = eer_from_scores(*split(ss))

    def mm(v):
        return (v - v.min()) / (v.max() - v.min() + 1e-12)

    fused_mm = mm(ps) + mm(ss)
    eer_mm = eer_from_scores(*split(fused_mm))

    x = np.stack([ps, ss], axis=1)
    x = (x - x.mean(0)) / (x.std(0) + 1e-12)
    fused_lr = logistic_loo(x, y, finger)
    eer_lr = eer_from_scores(*split(fused_lr))

    summary = dict(
        pairs=len(keys), dropped_missing_safis=dropped,
        genuine=int(y.sum()), impostor=int((1 - y).sum()),
        eer=dict(
            pore_spatial=eer_pore,
            sourceafis=eer_safis,
            fusion_minmax_sum=eer_mm,
            fusion_logistic_loo=eer_lr,
        ),
        sourceafis_score_stats=dict(
            genuine_median=float(np.median(ss[y == 1])),
            impostor_median=float(np.median(ss[y == 0])),
            genuine_at_or_above_40=int((ss[y == 1] >= 40).sum()),
        ),
    )
    print(json.dumps(summary, indent=1))
    if args.out:
        with open(args.out, "w") as f:
            json.dump(summary, f, indent=1)


if __name__ == "__main__":
    main()
