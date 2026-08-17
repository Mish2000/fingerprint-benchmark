"""Stage 19A's diagnostic report — section 21, and the comparison it enables.

Written only after the route is frozen and the run is finished. Nothing here can
reach back into the algorithm: the translation contract is fixed in
:mod:`fpbench.adapters.openafis.translation`, and this module only describes what
came out.

WHAT IT MAY SAY AND WHAT IT MAY NOT

Section 21 permits coverage, failure breakdowns, per-population score
distributions, minutiae-count distributions and timings. It also permits the one
comparison this stage was worth building for:

.. code-block:: text

    MINDTCT -> BOZORTH3      (Algorithm 2)
    MINDTCT -> OpenAFIS      (Algorithm 5)

— the same extractor feeding two different matchers over the same 6,000 pairs.
That is a controlled matcher comparison and it is unusual to be able to make one.

What it may **not** say is that either matcher is better. There is no common
operating point, no threshold and no calibration; BOZORTH3's scale and OpenAFIS's
scale are unrelated. So the comparison reports coverage and agreement in
*ranking*, never a winner — and there is no field for one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

__all__ = [
    "PairOutcome",
    "Distribution",
    "Stage19ADiagnosticReport",
    "read_outcomes",
    "read_algorithm2_scores",
    "build_report",
]


@dataclass(frozen=True, slots=True)
class PairOutcome:
    ordinal: int
    pair_id: str
    release: str
    stage: str
    ground_truth: str
    raw_score: int | None
    status: str
    failure_reason: str | None
    left_minutiae_count: int | None
    right_minutiae_count: int | None
    mindtct_left_ms: float | None
    mindtct_right_ms: float | None
    openafis_template_left_ms: float | None
    openafis_template_right_ms: float | None
    openafis_match_ms: float | None

    @property
    def total_ms(self) -> float:
        return sum(
            value or 0.0
            for value in (
                self.mindtct_left_ms,
                self.mindtct_right_ms,
                self.openafis_template_left_ms,
                self.openafis_template_right_ms,
                self.openafis_match_ms,
            )
        )


def _median(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return round(float(ordered[middle]), 4)
    return round((float(ordered[middle - 1]) + float(ordered[middle])) / 2.0, 4)


def _p95(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, min(len(ordered), int(-(-0.95 * len(ordered) // 1))))
    return round(float(ordered[rank - 1]), 4)


@dataclass(frozen=True, slots=True)
class Distribution:
    label: str
    comparisons: int
    score_bearing: int
    minimum: int | None
    maximum: int | None
    median: float | None
    p95: float | None
    zeros: int
    distinct_values: int
    histogram: Mapping[int, int]

    def describe(self) -> dict[str, object]:
        return {
            "label": self.label,
            "comparisons": self.comparisons,
            "score_bearing": self.score_bearing,
            "score_bearing_fraction": (
                round(self.score_bearing / self.comparisons, 6) if self.comparisons else None
            ),
            "min": self.minimum,
            "max": self.maximum,
            "median": self.median,
            "p95": self.p95,
            "zeros": self.zeros,
            "distinct_values": self.distinct_values,
            "histogram": {str(k): v for k, v in sorted(self.histogram.items())},
        }


def _distribution(label: str, outcomes: Sequence[PairOutcome]) -> Distribution:
    scores = [o.raw_score for o in outcomes if o.status == "OK" and o.raw_score is not None]
    histogram: dict[int, int] = {}
    for score in scores:
        histogram[score] = histogram.get(score, 0) + 1
    return Distribution(
        label=label,
        comparisons=len(outcomes),
        score_bearing=len(scores),
        minimum=min(scores) if scores else None,
        maximum=max(scores) if scores else None,
        median=_median(scores),
        p95=_p95(scores),
        zeros=sum(1 for s in scores if s == 0),
        distinct_values=len(set(scores)),
        histogram=histogram,
    )


def read_outcomes(path: Path) -> list[PairOutcome]:
    outcomes: list[PairOutcome] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            outcomes.append(
                PairOutcome(
                    ordinal=int(row["ordinal"]),
                    pair_id=row["pair_id"],
                    release=row["release"],
                    stage=row["stage"],
                    ground_truth=row["ground_truth"],
                    raw_score=row["raw_score"],
                    status=row["status"],
                    failure_reason=row.get("failure_reason"),
                    left_minutiae_count=row.get("left_minutiae_count"),
                    right_minutiae_count=row.get("right_minutiae_count"),
                    mindtct_left_ms=row.get("mindtct_left_ms"),
                    mindtct_right_ms=row.get("mindtct_right_ms"),
                    openafis_template_left_ms=row.get("openafis_template_left_ms"),
                    openafis_template_right_ms=row.get("openafis_template_right_ms"),
                    openafis_match_ms=row.get("openafis_match_ms"),
                )
            )
    outcomes.sort(key=lambda outcome: outcome.ordinal)
    return outcomes


def read_algorithm2_scores(results_root: Path) -> dict[str, float]:
    """Algorithm 2's stored raw scores, keyed by pair id.

    Read for the matcher comparison only. No threshold is applied, no decision is
    read, and the two scales are never mixed into one number.
    """
    import pyarrow.parquet as pq

    scores: dict[str, float] = {}
    for path in sorted(Path(results_root).rglob("*.parquet")):
        table = pq.read_table(path, columns=["pair_id", "status", "raw_score", "algorithm_id"])
        for row in table.to_pylist():
            if row["algorithm_id"] != "nbis_mindtct_bozorth3":
                continue
            if row["status"] != "success" or row["raw_score"] is None:
                continue
            scores[row["pair_id"]] = float(row["raw_score"])
    return scores


@dataclass(frozen=True, slots=True)
class Stage19ADiagnosticReport:
    created_utc: str
    outcome_counts: Mapping[str, int]
    failure_reasons: Mapping[str, int]
    template_coverage: Mapping[str, object]
    minutiae_counts: Mapping[str, object]
    overall: Distribution
    by_protocol_stage: Sequence[Distribution]
    by_release: Sequence[Distribution]
    timings_ms: Mapping[str, Mapping[str, float | None]]
    algorithm2_comparison: Mapping[str, object] | None

    def describe(self) -> dict[str, object]:
        return {
            "kind": "stage_19a_diagnostic_report",
            "stage": "19A",
            "algorithm_id": "nbis_mindtct_openafis",
            "created_utc": self.created_utc,
            "threshold_applied": None,
            "why_no_rates": (
                "no common operating point exists across the algorithms and the negative pairs "
                "are a same-subject different-finger sanity set, not an impostor population "
                "drawn for estimation"
            ),
            "outcome_counts": dict(sorted(self.outcome_counts.items())),
            "failure_reasons": dict(sorted(self.failure_reasons.items())),
            "template_coverage": dict(self.template_coverage),
            "minutiae_counts": dict(self.minutiae_counts),
            "overall": self.overall.describe(),
            "by_protocol_stage": [d.describe() for d in self.by_protocol_stage],
            "by_release": [d.describe() for d in self.by_release],
            "timings_ms": {k: dict(v) for k, v in self.timings_ms.items()},
            "algorithm2_comparison": dict(self.algorithm2_comparison) if self.algorithm2_comparison else None,
        }


def _compare_to_algorithm2(
    outcomes: Sequence[PairOutcome], algorithm2: Mapping[str, float]
) -> dict[str, object]:
    """Coverage and rank agreement between the two matchers. Never a winner.

    Spearman is computed on the pairs *both* matchers scored, which is a small and
    self-selected subset — every pair Algorithm 5 could not template is absent.
    That is stated in the output rather than left for the reader to infer.
    """
    ours = {o.pair_id: float(o.raw_score) for o in outcomes if o.status == "OK" and o.raw_score is not None}
    common = sorted(set(ours) & set(algorithm2))

    def _rank(values: Sequence[float]) -> list[float]:
        order = sorted(range(len(values)), key=lambda i: values[i])
        ranks = [0.0] * len(values)
        index = 0
        while index < len(order):
            stop = index
            while stop + 1 < len(order) and values[order[stop + 1]] == values[order[index]]:
                stop += 1
            average = (index + stop) / 2.0 + 1.0
            for position in range(index, stop + 1):
                ranks[order[position]] = average
            index = stop + 1
        return ranks

    spearman = None
    if len(common) > 2:
        a = _rank([ours[p] for p in common])
        b = _rank([algorithm2[p] for p in common])
        mean_a = sum(a) / len(a)
        mean_b = sum(b) / len(b)
        num = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b))
        den = (sum((x - mean_a) ** 2 for x in a) * sum((y - mean_b) ** 2 for y in b)) ** 0.5
        spearman = round(num / den, 6) if den else None

    return {
        "algorithm_2": "nbis_mindtct_bozorth3",
        "algorithm_5": "nbis_mindtct_openafis",
        "shared_extractor": "mindtct 5.0.0, same certified build",
        "differs_only_in": "the matcher",
        "algorithm_2_score_bearing": len(algorithm2),
        "algorithm_5_score_bearing": len(ours),
        "both_score_bearing": len(common),
        "spearman_rank_correlation_on_common": spearman,
        "spearman_is_over_a_self_selected_subset": True,
        "why_no_better_or_worse": (
            "the two scales are unrelated and no common operating point has been chosen; "
            "a comparison of accuracy needs calibration, which is a later stage"
        ),
    }


def build_report(
    outcomes: Sequence[PairOutcome], *, algorithm2: Mapping[str, float] | None = None
) -> Stage19ADiagnosticReport:
    counts: dict[str, int] = {}
    reasons: dict[str, int] = {}
    for outcome in outcomes:
        counts[outcome.status] = counts.get(outcome.status, 0) + 1
        if outcome.failure_reason:
            reasons[outcome.failure_reason] = reasons.get(outcome.failure_reason, 0) + 1

    extracted = [
        count
        for outcome in outcomes
        for count in (outcome.left_minutiae_count, outcome.right_minutiae_count)
        if count is not None
    ]
    over = sum(1 for count in extracted if count > 128)
    under = sum(1 for count in extracted if count < 2)

    stages = sorted({o.stage for o in outcomes})
    releases = sorted({o.release for o in outcomes})

    def _times(attribute: str) -> dict[str, float | None]:
        values = [getattr(o, attribute) for o in outcomes if getattr(o, attribute) is not None]
        return {"median": _median(values), "p95": _p95(values)}

    totals = [o.total_ms for o in outcomes if o.status == "OK"]

    return Stage19ADiagnosticReport(
        created_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        outcome_counts=counts,
        failure_reasons=reasons,
        template_coverage={
            "pairs": len(outcomes),
            "score_bearing": counts.get("OK", 0),
            "score_bearing_fraction": round(counts.get("OK", 0) / len(outcomes), 6) if outcomes else None,
        },
        minutiae_counts={
            "observations": len(extracted),
            "min": min(extracted) if extracted else None,
            "median": _median(extracted),
            "p95": _p95(extracted),
            "max": max(extracted) if extracted else None,
            "above_openafis_maximum_128": over,
            "below_openafis_minimum_2": under,
            "note": "counted per side of a pair, so an image participating in several pairs is counted several times",
        },
        overall=_distribution("all", outcomes),
        by_protocol_stage=[_distribution(s, [o for o in outcomes if o.stage == s]) for s in stages],
        by_release=[_distribution(r, [o for o in outcomes if o.release == r]) for r in releases],
        timings_ms={
            "mindtct_left": _times("mindtct_left_ms"),
            "mindtct_right": _times("mindtct_right_ms"),
            "openafis_template_left": _times("openafis_template_left_ms"),
            "openafis_template_right": _times("openafis_template_right_ms"),
            "openafis_match": _times("openafis_match_ms"),
            "total_comparison": {"median": _median(totals), "p95": _p95(totals)},
        },
        algorithm2_comparison=_compare_to_algorithm2(outcomes, algorithm2) if algorithm2 else None,
    )


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Stage 19A diagnostic report")
    parser.add_argument("--outcomes", type=Path, required=True)
    parser.add_argument("--algorithm2-results", type=Path, default=None)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    outcomes = read_outcomes(args.outcomes)
    algorithm2 = read_algorithm2_scores(args.algorithm2_results) if args.algorithm2_results else None
    report = build_report(outcomes, algorithm2=algorithm2)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report.describe(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"diagnostic report {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
