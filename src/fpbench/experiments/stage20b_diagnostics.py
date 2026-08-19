"""Stage 20B's diagnostic report — section 28, and the one comparison section 29 allows.

Read **after** the 6,000 outcomes are frozen, and used to change nothing. Section
28 is explicit that no number in this report may alter the route, and there is
nothing here that could: it counts, sorts and describes, and every field it emits
is a property of a run that has already happened.

WHAT IS DELIBERATELY ABSENT

.. code-block:: text

    MATCH / NON_MATCH        threshold        TAR / FAR / FRR
    FMR / FNMR / EER         calibration      ranking

The MCC SDK gave Stage 20A no native decision threshold, so Stage 20B does not
invent one. The supervisor's "processing matched/non-matched results" question is
a separate stage with its own requirements.

THE ONE COMPARISON THAT IS ALLOWED

Section 29: ``MINDTCT → BOZORTH3`` against ``MINDTCT → MCC``, because the
extractor is genuinely the same one — Gate B proves it byte for byte — so rank
agreement between the two matchers means something. What it is *not* allowed to
say is which is better. The scales are unrelated, no common operating point
exists, and "better" needs a calibration that has not happened.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from fpbench.experiments.stage20b_identity import (
    ALGORITHM_ID,
    EXPECTED_OUTCOMES,
    PROTOCOL_STAGES,
)

__all__ = [
    "PairOutcome",
    "read_outcomes",
    "read_algorithm2_scores",
    "build_stage20b_report",
    "main",
]

_TIMING_FIELDS: tuple[str, ...] = (
    "mindtct_left_ms",
    "mindtct_right_ms",
    "translation_left_ms",
    "translation_right_ms",
    "mcc_template_left_ms",
    "mcc_template_right_ms",
    "mcc_match_ms",
    "total_adapter_ms",
)


@dataclass(frozen=True, slots=True)
class PairOutcome:
    """One stored comparison, exactly as the run wrote it down."""

    ordinal: int
    pair_id: str
    release: str
    stage: str
    ground_truth: str
    raw_score: float | None
    status: str
    failure_code: str | None
    failure_reason: str | None
    observed_score: str | None
    left_minutiae_count: int | None
    right_minutiae_count: int | None
    timings: Mapping[str, float | None]

    @property
    def score_bearing(self) -> bool:
        return self.status == "OK" and self.raw_score is not None


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
                    failure_code=row.get("failure_code"),
                    failure_reason=row.get("failure_reason"),
                    observed_score=row.get("observed_score"),
                    left_minutiae_count=row.get("left_minutiae_count"),
                    right_minutiae_count=row.get("right_minutiae_count"),
                    timings={field: row.get(field) for field in _TIMING_FIELDS},
                )
            )
    outcomes.sort(key=lambda outcome: outcome.ordinal)
    return outcomes


def read_algorithm2_scores(results_root: Path) -> dict[str, float]:
    """Algorithm 2's stored raw scores, keyed by pair id.

    Read for the section 29 comparison only. No threshold is applied, no decision
    is read, and the two scales are never mixed into one number.
    """
    import pyarrow.parquet as pq

    wanted = ["pair_id", "status", "raw_score", "algorithm_id"]
    scores: dict[str, float] = {}
    for path in sorted(Path(results_root).rglob("*.parquet")):
        # A results tree holds more than raw scores — decision records, for one —
        # and those carry different columns. Skipped rather than guessed at:
        # anything that is not a raw result set has nothing to say here.
        if not set(wanted).issubset(set(pq.read_schema(path).names)):
            continue
        table = pq.read_table(path, columns=wanted)
        for row in table.to_pylist():
            if row["algorithm_id"] != "nbis_mindtct_bozorth3":
                continue
            if row["status"] != "success" or row["raw_score"] is None:
                continue
            scores[row["pair_id"]] = float(row["raw_score"])
    return scores


def _describe(scores: Sequence[float]) -> dict[str, Any]:
    if not scores:
        return {
            "count": 0, "minimum": None, "median": None, "maximum": None,
            "mean": None, "unique_scores": 0, "zeros": 0,
        }
    ordered = sorted(scores)
    return {
        "count": len(ordered),
        "minimum": ordered[0],
        "p05": ordered[max(0, int(round(0.05 * (len(ordered) - 1))))],
        "median": statistics.median(ordered),
        "p95": ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))],
        "maximum": ordered[-1],
        "mean": statistics.fmean(ordered),
        "unique_scores": len(set(ordered)),
        "zeros": sum(1 for value in ordered if value == 0.0),
    }


def _timings(outcomes: Sequence[PairOutcome]) -> dict[str, dict[str, float | None]]:
    report: dict[str, dict[str, float | None]] = {}
    for field in _TIMING_FIELDS:
        values = sorted(
            value
            for outcome in outcomes
            if (value := outcome.timings.get(field)) is not None
        )
        report[field] = {
            "median": statistics.median(values) if values else None,
            "p95": (
                values[min(len(values) - 1, int(round(0.95 * (len(values) - 1))))]
                if values
                else None
            ),
        }
    return report


def _minutiae(outcomes: Sequence[PairOutcome]) -> dict[str, Any]:
    counts = [
        count
        for outcome in outcomes
        for count in (outcome.left_minutiae_count, outcome.right_minutiae_count)
        if count is not None
    ]
    if not counts:
        return {"sides_counted": 0}
    ordered = sorted(counts)
    return {
        "sides_counted": len(ordered),
        "minimum": ordered[0],
        "median": statistics.median(ordered),
        "p95": ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))],
        "maximum": ordered[-1],
        "sides_with_zero_minutiae": sum(1 for value in ordered if value == 0),
        "sides_above_128": sum(1 for value in ordered if value > 128),
    }


def _rank(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: values[index])
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


def compare_to_algorithm2(
    outcomes: Sequence[PairOutcome], algorithm2: Mapping[str, float]
) -> dict[str, Any]:
    """Rank agreement between two matchers over one extractor. Never a winner."""
    ours = {
        outcome.pair_id: float(outcome.raw_score)
        for outcome in outcomes
        if outcome.score_bearing
    }
    common = sorted(set(ours) & set(algorithm2))

    spearman = None
    if len(common) > 2:
        left = _rank([ours[pair] for pair in common])
        right = _rank([algorithm2[pair] for pair in common])
        mean_left = sum(left) / len(left)
        mean_right = sum(right) / len(right)
        numerator = sum(
            (a - mean_left) * (b - mean_right) for a, b in zip(left, right)
        )
        denominator = (
            sum((a - mean_left) ** 2 for a in left)
            * sum((b - mean_right) ** 2 for b in right)
        ) ** 0.5
        spearman = round(numerator / denominator, 6) if denominator else None

    return {
        "algorithm_2": "nbis_mindtct_bozorth3",
        "stage_20b": ALGORITHM_ID,
        "shared_extractor": "mindtct 5.0.0, the same certified build, proved by Gate B",
        "differs_only_in": "the matcher",
        "algorithm_2_score_bearing": len(algorithm2),
        "stage_20b_score_bearing": len(ours),
        "both_score_bearing": len(common),
        "spearman_rank_correlation_on_common": spearman,
        "why_no_better_or_worse": (
            "the two scales are unrelated and no common operating point has been "
            "chosen; a comparison of accuracy needs calibration, which is a later stage"
        ),
        "threshold_applied": None,
        "decisions_produced": 0,
    }


def build_stage20b_report(
    outcomes: Sequence[PairOutcome],
    *,
    algorithm2: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Section 28's report, and nothing that could change a route."""
    counts: dict[str, int] = {}
    reasons: dict[str, int] = {}
    for outcome in outcomes:
        counts[outcome.status] = counts.get(outcome.status, 0) + 1
        if outcome.failure_reason:
            reasons[outcome.failure_reason] = reasons.get(outcome.failure_reason, 0) + 1

    scored = [outcome for outcome in outcomes if outcome.score_bearing]
    all_scores = [float(outcome.raw_score) for outcome in scored]

    by_stage = []
    for stage in PROTOCOL_STAGES:
        cell = [outcome for outcome in scored if outcome.stage == stage]
        by_stage.append(
            {
                "protocol_stage": stage,
                "attempted": sum(1 for o in outcomes if o.stage == stage),
                "score_bearing": len(cell),
                **_describe([float(o.raw_score) for o in cell]),
            }
        )

    by_release = []
    for release in sorted({outcome.release for outcome in outcomes}):
        cell = [outcome for outcome in scored if outcome.release == release]
        by_release.append(
            {
                "release": release,
                "attempted": sum(1 for o in outcomes if o.release == release),
                "score_bearing": len(cell),
                **_describe([float(o.raw_score) for o in cell]),
            }
        )

    document: dict[str, Any] = {
        "kind": "stage_20b_diagnostic_report",
        "stage": "20B",
        "schema": "stage_20b_diagnostic_report_v1",
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "algorithm_id": ALGORITHM_ID,
        "expected_outcomes": EXPECTED_OUTCOMES,
        "stored_outcomes": len(outcomes),
        "missing": EXPECTED_OUTCOMES - len(outcomes),
        "outcome_counts": dict(sorted(counts.items())),
        "failure_count": len(outcomes) - len(scored),
        "failure_reasons": dict(sorted(reasons.items())),
        "invalid_scores_observed": [
            outcome.observed_score
            for outcome in outcomes
            if outcome.status == "MCC_INVALID_SCORE"
        ],
        "overall": {
            "score_bearing": len(scored),
            "score_bearing_fraction": (
                round(len(scored) / len(outcomes), 6) if outcomes else None
            ),
            **_describe(all_scores),
        },
        "by_protocol_stage": by_stage,
        "by_release": by_release,
        "minutiae_counts": _minutiae(outcomes),
        "timings_ms": _timings(outcomes),
        # Named, so that the absence is a statement rather than an omission.
        "threshold": None,
        "score_transform": "NONE",
        "decisions_produced": 0,
        "calibration_performed": False,
        "metrics_produced": [],
        "used_to_change_route_or_configuration": False,
    }
    if algorithm2 is not None:
        document["algorithm2_comparison"] = compare_to_algorithm2(outcomes, algorithm2)
    return document


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Stage 20B diagnostic report")
    parser.add_argument("--outcomes", type=Path, required=True)
    parser.add_argument("--algorithm2-results", type=Path, default=None)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    outcomes = read_outcomes(args.outcomes)
    algorithm2 = (
        read_algorithm2_scores(args.algorithm2_results)
        if args.algorithm2_results
        else None
    )
    document = build_stage20b_report(outcomes, algorithm2=algorithm2)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(
        (json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode(
            "utf-8"
        )
    )
    print(f"diagnostic report {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
