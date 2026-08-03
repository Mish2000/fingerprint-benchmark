"""How long the run took and what went wrong — never what the scores mean.

Everything in here is about the *machine*: seconds, counts, failure codes, the
span between the first comparison starting and the last one finishing. It is
the artefact that answers "should the next run use a persistent JVM?" and "did
2000 ppi cost four times as much as 500?", which are engineering questions with
engineering answers.

What it deliberately does not contain: any statistic over the scores. No mean,
no histogram, no split by ground truth, no threshold, no rate. Those are not
omitted because they are hard — a mean is one line — but because publishing a
number derived from 6,000 scores *is* a biometric claim, and the definitions
that would make such a claim honest (decision profiles, SELF eligibility,
failure denominators) do not exist yet (docs/adr/0003).

The file is derived and disposable: delete it, regenerate it, nothing is lost.
That is the difference between this and the receipt beside it.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Iterable, Mapping, Sequence

from fpbench.core.enums import ExecutionStatus
from fpbench.core.execution_plan_models import ExecutionPlan
from fpbench.core.identifiers import PairId
from fpbench.core.models import ComparisonPair
from fpbench.core.research_models import NO_CONCLUSION_STATEMENT
from fpbench.core.result_models import RunDefinition
from fpbench.core.result_set_models import ResultSetManifest
from fpbench.storage.result_store import ResultStore

__all__ = [
    "OPERATIONAL_SUMMARY_NAME",
    "OPERATIONAL_SUMMARY_SCHEMA_VERSION",
    "TIMING_COMPONENTS",
    "build_operational_summary",
    "write_operational_summary",
]

#: Kept under its historical name. It is the file name of a regenerable derived
#: artefact, and renaming it would move — or worse, duplicate — the summary of
#: five runs that already exist and whose directories may not be written to
#: (spec section 46). The contents have never been algorithm-specific.
OPERATIONAL_SUMMARY_NAME = "sourceafis-native-operational-summary.json"
OPERATIONAL_SUMMARY_SCHEMA_VERSION = "2"

#: The first algorithm's own segments, in the order a reader thinks about them.
#: Named explicitly so that a timing the bridge stops reporting shows up as an
#: empty series rather than silently disappearing from the summary.
#:
#: They are no longer the *only* series reported. Every component name a stored
#: result actually carries is summarised as well, so a two-stage route's input
#: staging, its two extractions, its matching and its cleanup appear without
#: this module knowing that such a route exists (docs/adr/0040, docs/adr/0007).
TIMING_COMPONENTS: tuple[str, ...] = (
    "bridge_total",
    "left_input_read",
    "left_template_extraction",
    "right_input_read",
    "right_template_extraction",
    "matcher_initialization",
    "matching",
)


def build_operational_summary(
    *,
    run: RunDefinition,
    plan: ExecutionPlan,
    pairs: Mapping[PairId, ComparisonPair],
    result_store: ResultStore,
    result_set: ResultSetManifest | None = None,
    runtime_bundle_id: str | None = None,
) -> dict[str, Any]:
    """Summarise a run's cost and its failures, and nothing else."""
    adapter_ms: list[float] = []
    total_ms: list[float] = []
    components: dict[str, list[float]] = {name: [] for name in TIMING_COMPONENTS}

    failure_counts: dict[str, int] = {}
    failure_stage_counts: dict[str, int] = {}
    failure_detail_counts: dict[str, int] = {}
    failure_release_counts: dict[str, int] = {}
    failure_protocol_stage_counts: dict[str, int] = {}
    release_counts: dict[str, int] = {}
    stage_counts: dict[str, int] = {}

    stored = 0
    successes = 0
    failures = 0
    started: list[str] = []
    finished: list[str] = []

    for planned in plan.jobs:
        job_id = planned.job.job_id
        if not result_store.has_raw_result(run.run_id, job_id):
            continue
        record = result_store.read_raw_result(run.run_id, job_id)
        stored += 1
        pair = pairs.get(planned.job.pair_id)

        if record.status is ExecutionStatus.SUCCESS:
            successes += 1
        else:
            failures += 1
            failure = record.failure
            if failure is not None:
                code = failure.code.value
                failure_counts[code] = failure_counts.get(code, 0) + 1
                failure_stage_counts[failure.stage.value] = (
                    failure_stage_counts.get(failure.stage.value, 0) + 1
                )
                # Every detail the adapter attached, as ``key=value``. Generic on
                # purpose: which detail keys exist is the algorithm's business,
                # and a summary that only understood one route's vocabulary would
                # be silent about the next one (docs/adr/0040).
                for key, value in sorted(dict(failure.details).items()):
                    label = f"{key}={value}"
                    failure_detail_counts[label] = (
                        failure_detail_counts.get(label, 0) + 1
                    )
                if pair is not None:
                    failure_release_counts[pair.release] = (
                        failure_release_counts.get(pair.release, 0) + 1
                    )
                    failed_stage = pair.protocol_stage.value
                    failure_protocol_stage_counts[failed_stage] = (
                        failure_protocol_stage_counts.get(failed_stage, 0) + 1
                    )

        if pair is not None:
            release_counts[pair.release] = release_counts.get(pair.release, 0) + 1
            stage = pair.protocol_stage.value
            stage_counts[stage] = stage_counts.get(stage, 0) + 1

        adapter_ms.append(record.timings.adapter_ms)
        total_ms.append(record.timings.total_ms)
        for name, value in record.timings.adapter_components_ms.items():
            components.setdefault(str(name), []).append(float(value))

        started.append(record.started_utc)
        finished.append(record.finished_utc)

    summary: dict[str, Any] = {
        "schema_version": OPERATIONAL_SUMMARY_SCHEMA_VERSION,
        "kind": "operational_summary",
        "statement": NO_CONCLUSION_STATEMENT,
        "run_id": run.run_id,
        "plan_id": plan.plan_id,
        "result_set_id": result_set.result_set_id if result_set else None,
        "runtime_bundle_id": (
            runtime_bundle_id
            or run.environment.dependencies.get("runtime.bundle.id")
        ),
        "counts": {
            "planned_jobs": plan.total_jobs,
            "stored_results": stored,
            "missing_results": plan.total_jobs - stored,
            "success_count": successes,
            "failure_count": failures,
        },
        "failure_counts": dict(sorted(failure_counts.items())),
        "failure_counts_by_failure_stage": dict(sorted(failure_stage_counts.items())),
        "failure_counts_by_detail": dict(sorted(failure_detail_counts.items())),
        "failure_counts_by_release": dict(sorted(failure_release_counts.items())),
        "failure_counts_by_protocol_stage": dict(
            sorted(failure_protocol_stage_counts.items())
        ),
        "release_counts": dict(sorted(release_counts.items())),
        "stage_counts": dict(sorted(stage_counts.items())),
        "timings_ms": {
            "adapter": _distribution(adapter_ms),
            "job_total": _distribution(total_ms),
            **{
                name: _distribution(values)
                for name, values in sorted(components.items())
            },
        },
        "first_started_utc": min(started) if started else None,
        "last_finished_utc": max(finished) if finished else None,
        "wall_clock_span_seconds": _span_seconds(started, finished),
        "generated_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    }
    return summary


def write_operational_summary(
    *,
    result_store: ResultStore,
    run_id: str,
    summary: Mapping[str, Any],
) -> Any:
    """Persist the summary under the run's regenerable ``derived/`` directory."""
    return result_store.write_derived(run_id, OPERATIONAL_SUMMARY_NAME, summary)


# ----------------------------------------------------------------- internals


def _distribution(values: Sequence[float]) -> dict[str, Any]:
    """Count and order statistics, or an empty series stated as such.

    Percentiles are nearest-rank, computed on the sorted sample: no
    interpolation, no assumption about the shape of the distribution, and the
    same answer on every machine. For run timings that is what is wanted — the
    p95 should be a comparison that actually happened.
    """
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return {"count": 0}
    return {
        "count": len(ordered),
        "min": round(ordered[0], 3),
        "median": round(_nearest_rank(ordered, 50), 3),
        "p95": round(_nearest_rank(ordered, 95), 3),
        "p99": round(_nearest_rank(ordered, 99), 3),
        "max": round(ordered[-1], 3),
        "sum": round(sum(ordered), 3),
    }


def _nearest_rank(ordered: Sequence[float], percentile: int) -> float:
    import math

    index = max(1, math.ceil(percentile / 100 * len(ordered))) - 1
    return ordered[min(index, len(ordered) - 1)]


def _span_seconds(started: Iterable[str], finished: Iterable[str]) -> float | None:
    first = min(started, default=None)
    last = max(finished, default=None)
    if not first or not last:
        return None
    try:
        begin = _dt.datetime.fromisoformat(first)
        end = _dt.datetime.fromisoformat(last)
    except ValueError:  # pragma: no cover - the runner writes ISO timestamps
        return None
    return round((end - begin).total_seconds(), 3)
