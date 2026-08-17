"""Stage 19B's diagnostic report — section 19, plus the audit section 12 withdrew.

Reuses Stage 19A's report builder unchanged (importing it does not alter its
bytes, which its marker pins) and adds the two comparisons this stage exists to
make:

* **against Stage 19A** — how many pairs the capacity extension newly admits;
* **against Algorithm 2** — the same MINDTCT minutiae into two different matchers.

THE OVERFLOW AUDIT, AND WHY IT IS HERE

Section 12 of the requirements withdrew a ``uint8_t`` overflow check, reasoning
that ``matched`` cannot exceed the minutiae count on either side and so the score
cannot exceed 100. Stage 19A observed a maximum of **109**, so the premise does
not hold: the formula

.. code-block:: text

    score = 100 * maxMatched^2 / (probe_count * candidate_count)

is an unclamped integer ratio cast to ``uint8_t``, and ``maxMatched`` counts
compatible minutia pairs drawn from triplets, which can exceed
``sqrt(n_probe * n_candidate)``.

The gate stays withdrawn — that is the instruction — but the risk is real once
templates carry 373 minutiae instead of 128, so it is *audited* rather than
assumed away. For every scored pair the implied ``maxMatched`` is recovered from
the stored score and minutiae counts, and the report says how close the run came
to 256 and whether any pair is consistent with having wrapped. This costs nothing
and needs no change to upstream or to the bridge.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from fpbench.experiments.stage19a_diagnostics import (
    PairOutcome,
    build_report,
    read_algorithm2_scores,
    read_outcomes,
)

__all__ = [
    "compare_to_stage19a",
    "audit_uint8_headroom",
    "build_stage19b_report",
    "main",
]


def compare_to_stage19a(
    current: Sequence[PairOutcome], previous: Sequence[PairOutcome]
) -> dict[str, object]:
    """What the capacity extension newly admits, and what it cost."""
    now = {o.pair_id: o for o in current}
    before = {o.pair_id: o for o in previous}

    was_ok = {p for p, o in before.items() if o.status == "OK"}
    is_ok = {p for p, o in now.items() if o.status == "OK"}

    newly = sorted(is_ok - was_ok)
    lost = sorted(was_ok - is_ok)
    retained = sorted(was_ok & is_ok)
    changed = [
        {"pair_id": p, "stage19a": before[p].raw_score, "stage19b": now[p].raw_score}
        for p in retained
        if before[p].raw_score != now[p].raw_score
    ]

    per_stage: dict[str, dict[str, int]] = {}
    for pair_id in newly:
        stage = now[pair_id].stage
        per_stage.setdefault(stage, {"newly_admitted": 0})["newly_admitted"] += 1

    return {
        "stage19a_score_bearing": len(was_ok),
        "stage19b_score_bearing": len(is_ok),
        "newly_admitted": len(newly),
        "newly_admitted_by_protocol_stage": per_stage,
        "lost": len(lost),
        "retained": len(retained),
        "retained_with_changed_score": len(changed),
        "first_changed": changed[:20],
        "first_lost": lost[:20],
        "inertness_holds_on_retained": not changed and not lost,
    }


def audit_uint8_headroom(outcomes: Sequence[PairOutcome]) -> dict[str, object]:
    """How close the unclamped ratio came to wrapping a ``uint8_t``.

    For a scored pair the reported value ``s`` implies
    ``maxMatched = sqrt(s * n_p * n_c / 100)``. If the true value had wrapped once,
    the real score would be ``s + 256`` and the implied ``maxMatched`` would have
    to exceed ``min(n_p, n_c)`` by a wide margin — which is reported here so the
    reader can see the margin rather than take a reassurance.
    """
    scored = [
        o for o in outcomes
        if o.status == "OK"
        and o.raw_score is not None
        and o.left_minutiae_count
        and o.right_minutiae_count
    ]
    if not scored:
        return {"scored_pairs": 0}

    observed_max = max(o.raw_score for o in scored)
    ratios = []
    wrap_candidates = 0
    for o in scored:
        product = o.left_minutiae_count * o.right_minutiae_count
        implied = math.sqrt(max(o.raw_score, 0) * product / 100.0)
        smaller = min(o.left_minutiae_count, o.right_minutiae_count)
        ratios.append(implied / smaller if smaller else 0.0)
        # Would a single wrap even be arithmetically reachable for this pair?
        implied_if_wrapped = math.sqrt((o.raw_score + 256) * product / 100.0)
        if implied_if_wrapped <= smaller:
            wrap_candidates += 1

    return {
        "scored_pairs": len(scored),
        "observed_max_score": observed_max,
        "uint8_wrap_threshold": 256,
        "headroom_to_wrap": 256 - observed_max,
        "scores_above_100": sum(1 for o in scored if o.raw_score > 100),
        "max_implied_matched_over_smaller_side": round(max(ratios), 4),
        "pairs_where_a_wrap_is_arithmetically_reachable": wrap_candidates,
        "note": (
            "section 12 withdrew this gate on the premise that the score cannot exceed 100; "
            "Stage 19A observed 109, so the premise is false and the headroom is reported "
            "rather than assumed. A pair is counted as wrap-reachable only if score+256 "
            "implies a matched count still within the smaller template"
        ),
    }


def build_stage19b_report(
    outcomes: Sequence[PairOutcome],
    *,
    stage19a: Sequence[PairOutcome] | None = None,
    algorithm2: Mapping[str, float] | None = None,
) -> dict[str, object]:
    document = build_report(outcomes, algorithm2=algorithm2).describe()
    document["kind"] = "stage_19b_diagnostic_report"
    document["stage"] = "19B"
    document["algorithm_id"] = "nbis_mindtct_openafis_capacity_extended"
    document["upstream_modified"] = True
    document["uint8_headroom_audit"] = audit_uint8_headroom(outcomes)
    if stage19a is not None:
        document["stage19a_comparison"] = compare_to_stage19a(outcomes, stage19a)
    return document


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Stage 19B diagnostic report")
    parser.add_argument("--outcomes", type=Path, required=True)
    parser.add_argument("--stage19a-outcomes", type=Path, default=None)
    parser.add_argument("--algorithm2-results", type=Path, default=None)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    outcomes = read_outcomes(args.outcomes)
    previous = read_outcomes(args.stage19a_outcomes) if args.stage19a_outcomes else None
    algorithm2 = read_algorithm2_scores(args.algorithm2_results) if args.algorithm2_results else None

    document = build_stage19b_report(outcomes, stage19a=previous, algorithm2=algorithm2)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"diagnostic report {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
