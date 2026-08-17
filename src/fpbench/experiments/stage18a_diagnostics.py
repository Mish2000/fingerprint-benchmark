"""The private diagnostic report — section 16, and nothing past it.

This module describes a completed Stage 18A run. It does not evaluate it. The
distinction is the whole point: the negative pairs in this manifest are
same-subject different-finger comparisons chosen for a sanity check, not a true
impostor population drawn for estimation, so every rate computed over them would
be a number with no population behind it.

So the permitted statistics are descriptive and the forbidden ones are absent
**structurally** — there is no ``tar`` field to fill in, no ``threshold``
parameter to pass, and :func:`build_diagnostic_report` takes no cutoff. A future
edit that wanted an EER would have to add the concept, which is a visible change
rather than a silent one.

.. code-block:: text

    permitted                                forbidden
    ---------------------------------------  -------------
    template extraction coverage             TAR
    score-bearing comparisons                FAR
    score histogram 0..100                   FMR
    SELF distribution                        EER
    PLAIN-ROLL mated distribution            best threshold
    same-subject/different-finger sanity
    score uniqueness / quantization
    median / p95 extraction time
    median / p95 OpenAFIS match time
    A->B versus B->A differences

The report is written into the private root beside the results it describes, and
never into the repository: Stage 18A's evidence carries bindings, not scores.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from fpbench.experiments import stage18a_identity as frozen
from fpbench.experiments.stage18a_reference_run import (
    PairOutcome,
    Stage18AConfig,
    TemplateRecord,
    read_pair_outcomes,
    read_template_index,
)

__all__ = [
    "Distribution",
    "DiagnosticReport",
    "build_diagnostic_report",
    "write_diagnostic_report",
]


def _percentile(values: Sequence[float], fraction: float) -> float | None:
    """Nearest-rank percentile. No interpolation, so the answer is an observed value."""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(float(ordered[0]), 4)
    rank = max(1, min(len(ordered), int(-(-fraction * len(ordered) // 1))))
    return round(float(ordered[rank - 1]), 4)


def _median(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return round(float(ordered[middle]), 4)
    return round((float(ordered[middle - 1]) + float(ordered[middle])) / 2.0, 4)


@dataclass(frozen=True, slots=True)
class Distribution:
    """One population of raw scores, described and not judged."""

    label: str
    count: int
    scored: int
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
            "comparisons": self.count,
            "score_bearing": self.scored,
            "min": self.minimum,
            "max": self.maximum,
            "median": self.median,
            "p95": self.p95,
            "zeros": self.zeros,
            "distinct_values": self.distinct_values,
            "histogram": {str(k): v for k, v in sorted(self.histogram.items())},
        }


def _distribution(label: str, outcomes: Sequence[PairOutcome]) -> Distribution:
    scores = [o.openafis_score for o in outcomes if o.status == frozen.OK_STATUS and o.openafis_score is not None]
    histogram: dict[int, int] = {}
    for score in scores:
        histogram[score] = histogram.get(score, 0) + 1
    return Distribution(
        label=label,
        count=len(outcomes),
        scored=len(scores),
        minimum=min(scores) if scores else None,
        maximum=max(scores) if scores else None,
        median=_median(scores),
        p95=_percentile(scores, 0.95),
        zeros=sum(1 for score in scores if score == 0),
        distinct_values=len(set(scores)),
        histogram=histogram,
    )


@dataclass(frozen=True, slots=True)
class DiagnosticReport:
    """Everything section 16 permits, and no field for anything it forbids."""

    created_utc: str
    extraction_coverage: Mapping[str, object]
    outcome_counts: Mapping[str, int]
    overall: Distribution
    by_protocol_stage: Sequence[Distribution]
    by_release: Sequence[Distribution]
    extraction_timing_ms: Mapping[str, float | None]
    match_timing_ms: Mapping[str, float | None]
    orientation_probe: Mapping[str, object] | None

    def describe(self) -> dict[str, object]:
        return {
            "kind": "stage_18a_private_diagnostic_report",
            "stage": frozen.STAGE,
            "purpose": frozen.PURPOSE,
            "created_utc": self.created_utc,
            "publication_eligible": frozen.PUBLICATION_ELIGIBLE,
            "why_no_rates": (
                "the negative pairs are a same-subject different-finger sanity set, not an "
                "impostor population drawn for estimation, so TAR/FAR/FMR/EER and any chosen "
                "threshold would be numbers with no population behind them"
            ),
            "permitted_statistics": list(frozen.DIAGNOSTICS_PERMITTED),
            "forbidden_statistics": list(frozen.DIAGNOSTICS_FORBIDDEN),
            "extraction_coverage": dict(self.extraction_coverage),
            "outcome_counts": dict(sorted(self.outcome_counts.items())),
            "overall": self.overall.describe(),
            "by_protocol_stage": [d.describe() for d in self.by_protocol_stage],
            "by_release": [d.describe() for d in self.by_release],
            "extraction_timing_ms": dict(self.extraction_timing_ms),
            "match_timing_ms": dict(self.match_timing_ms),
            "orientation_probe": dict(self.orientation_probe) if self.orientation_probe else None,
        }


def build_diagnostic_report(
    outcomes: Sequence[PairOutcome],
    templates: Mapping[str, TemplateRecord],
    *,
    orientation_probe: Mapping[str, object] | None = None,
) -> DiagnosticReport:
    """Describe a run. Takes no threshold, and there is nowhere to pass one."""
    ok_templates = [record for record in templates.values() if record.ok]
    extraction_coverage = {
        "images_recorded": len(templates),
        "templates_produced": len(ok_templates),
        "extraction_failures": len(templates) - len(ok_templates),
        "coverage": round(len(ok_templates) / len(templates), 6) if templates else None,
        "template_bytes_min": min((r.template_bytes for r in ok_templates), default=None),
        "template_bytes_max": max((r.template_bytes for r in ok_templates), default=None),
        "template_bytes_median": _median([r.template_bytes for r in ok_templates]),
    }

    counts: dict[str, int] = {}
    for outcome in outcomes:
        counts[outcome.status] = counts.get(outcome.status, 0) + 1

    stages = sorted({outcome.stage for outcome in outcomes})
    releases = sorted({outcome.release for outcome in outcomes})

    extraction_times = [record.extract_ms for record in ok_templates]
    match_times = [o.match_ms for o in outcomes if o.match_ms is not None]

    return DiagnosticReport(
        created_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        extraction_coverage=extraction_coverage,
        outcome_counts=counts,
        overall=_distribution("all", outcomes),
        by_protocol_stage=[_distribution(stage, [o for o in outcomes if o.stage == stage]) for stage in stages],
        by_release=[_distribution(release, [o for o in outcomes if o.release == release]) for release in releases],
        extraction_timing_ms={"median": _median(extraction_times), "p95": _percentile(extraction_times, 0.95)},
        match_timing_ms={"median": _median(match_times), "p95": _percentile(match_times, 0.95)},
        orientation_probe=orientation_probe,
    )


def write_diagnostic_report(config: Stage18AConfig, report: DiagnosticReport) -> Path:
    """Write the report into the private root. Never into the repository."""
    path = config.stage_root / "diagnostic-report.json"
    path.write_text(json.dumps(report.describe(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def run_orientation_probe(config: Stage18AConfig, outcomes: Sequence[PairOutcome]) -> dict[str, object]:
    """Section 16's A->B versus B->A check, over every pair whose sides differ.

    SELF pairs are excluded because they are symmetric by construction and would
    dilute the answer with guaranteed agreement. Nothing here changes a stored
    score: the run keeps ``left -> probe`` throughout, and this only asks what the
    other orientation would have produced.
    """
    import subprocess

    from fpbench.experiments.stage18a_reference_run import _to_matcher_path

    cross = [o for o in outcomes if o.status == frozen.OK_STATUS and o.left_image_id != o.right_image_id]
    if not cross:
        return {"reversed_pairs": 0}

    jobs = "".join(
        f"{o.pair_id}\t{_to_matcher_path(config.templates_dir / (o.right_image_id + '.iso'), config)}"
        f"\t{_to_matcher_path(config.templates_dir / (o.left_image_id + '.iso'), config)}\n"
        for o in cross
    )
    completed = subprocess.run([*config.matcher_command, "batch"], input=jobs, text=True, capture_output=True)

    reversed_scores: dict[str, int] = {}
    for line in completed.stdout.splitlines():
        fields = line.split("\t")
        if len(fields) >= 6 and fields[1] == frozen.OK_STATUS:
            reversed_scores[fields[0]] = int(fields[2])

    forward = {o.pair_id: o.openafis_score for o in cross if o.openafis_score is not None}
    common = [pair_id for pair_id in forward if pair_id in reversed_scores]
    differences = [abs(forward[pair_id] - reversed_scores[pair_id]) for pair_id in common]
    if not differences:
        return {"reversed_pairs": 0}

    identical = sum(1 for difference in differences if difference == 0)
    return {
        "reversed_pairs": len(common),
        "identical": identical,
        "identical_fraction": round(identical / len(common), 6),
        "max_abs_difference": max(differences),
        "mean_abs_difference": round(sum(differences) / len(differences), 6),
        "self_pairs_excluded": True,
        "is_a_blocker": False,
        "note": "section 7C records symmetry and section 19 excludes it from the stage's requirements",
    }


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    from fpbench.experiments.stage18a_reference_run import load_stage18a_config

    parser = argparse.ArgumentParser(description="Stage 18A private diagnostic report")
    parser.add_argument(
        "--orientation-probe",
        action="store_true",
        help="also run every non-SELF pair in reverse and compare (section 16's A->B versus B->A)",
    )
    args = parser.parse_args(argv)

    config = load_stage18a_config()
    outcomes = read_pair_outcomes(config)
    templates = read_template_index(config)
    if not outcomes:
        print("no stored pair outcomes; run the matching phase first")
        return 1

    probe = run_orientation_probe(config, outcomes) if args.orientation_probe else None
    report = build_diagnostic_report(outcomes, templates, orientation_probe=probe)
    path = write_diagnostic_report(config, report)
    print(f"diagnostic report {path}")
    print(json.dumps(report.overall.describe(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
