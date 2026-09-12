"""Small, dependency-free policy and attempt-level development readout rules."""

from __future__ import annotations

import math
from collections import Counter
from fractions import Fraction


def scale_policy(estimate, target, band):
    if not math.isfinite(target) or target <= 0 or not 0 < band[0] <= band[1]:
        raise ValueError("Invalid declared scale policy")
    period = estimate["period_px"]
    factor = target / period if period is not None else None
    reason = estimate["status"] if estimate["status"] != "OK" else None
    if reason is None and (
        factor is None or not math.isfinite(factor) or not band[0] <= factor <= band[1]
    ):
        reason = "SCALE_OUTSIDE_FROZEN_BAND"
    return {
        "target": target,
        "band": list(band),
        "factor": factor,
        "status": "PREPROCESSING_FAILURE" if reason else "OK",
        "reason": reason,
    }


def validate_pairs(pairs):
    if len(pairs) != 250 or len({p["pair_id"] for p in pairs}) != 250:
        raise ValueError("Expected the 250 unique predecessor pairs")
    if Counter(p["kind"] for p in pairs) != {"genuine": 50, "impostor": 200}:
        raise ValueError("Attempt denominators must remain 50/200")


def descriptive_points(rows, targets=("0.01", "0.05")):
    """Atomic >= ties; maximize TA, then minimize FA, then maximize cut.

    An explicit accept-none point represents cut=+infinity without emitting
    non-JSON infinity. Failures are operational nonacceptance, never scores.
    """
    validate_pairs(rows)
    counts = Counter((r["kind"], r["status"]) for r in rows)
    coverage = {
        kind: {
            status: counts[kind, status] for status in ("success", "failure", "blocked")
        }
        for kind in ("genuine", "impostor")
    }
    groups = {}
    for row in rows:
        if row["status"] not in ("success", "failure", "blocked"):
            raise ValueError("Unknown pair status")
        if row["status"] != "success":
            if row["score"] not in (None, ""):
                raise ValueError("Failure cannot carry a score")
            continue
        score = float(row["score"])
        if not math.isfinite(score):
            raise ValueError("Nonfinite score")
        groups.setdefault(score, Counter())[row["kind"]] += 1
    if not all(coverage[k]["success"] for k in coverage):
        return {
            "status": "unsupported",
            "reason": "NO_SCORED_GENUINE_OR_IMPOSTOR",
            "coverage": coverage,
            "points": [],
        }
    candidates = [{"cut": None, "accept_none": True, "TA": 0, "FA": 0}]
    ta = fa = 0
    for cut in sorted(groups, reverse=True):
        ta += groups[cut]["genuine"]
        fa += groups[cut]["impostor"]
        candidates.append({"cut": cut, "accept_none": False, "TA": ta, "FA": fa})
    points = []
    for target in targets:
        allowed = [p for p in candidates if Fraction(p["FA"], 200) <= Fraction(target)]
        best = max(
            allowed,
            key=lambda p: (
                p["TA"],
                -p["FA"],
                math.inf if p["accept_none"] else p["cut"],
            ),
        )
        points.append(
            {
                **best,
                "target_far": str(target),
                "TAR": best["TA"] / 50,
                "FAR": best["FA"] / 200,
                "FRR": (50 - best["TA"]) / 50,
                "genuine_denominator": 50,
                "impostor_denominator": 200,
                "FR": 50 - best["TA"],
                "matcher_rejected_genuine": coverage["genuine"]["success"] - best["TA"],
                "failed_genuine": coverage["genuine"]["failure"],
                "blocked_genuine": coverage["genuine"]["blocked"],
            }
        )
    return {
        "status": "supported_descriptive_only",
        "coverage": coverage,
        "points": points,
    }
