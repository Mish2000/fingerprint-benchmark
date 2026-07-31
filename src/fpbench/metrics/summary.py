"""The machine-readable rendering of a verified metric set.

``summary.json`` exists so that something other than a Markdown parser can read
the results. It is not an authority and does not pretend to be one: it holds a
copy of the count records and observations that the metric set already holds, and
the verifier checks that the copy is exact rather than trusting it.

The identity fields on it — algorithm, implementation version, execution profile,
decision profile, threshold — are the answers to "of what?" that a bare table of
numbers cannot give. They come from the run and the decision profile, never from
the metric engine's own configuration, because the metric engine did not choose
any of them.
"""

from __future__ import annotations

import datetime as _dt
from typing import Sequence

from fpbench.core.decision_models import DecisionProfile
from fpbench.core.evaluation_models import EvaluationSummary
from fpbench.core.metric_models import (
    EvaluationCountRecord,
    MetricObservation,
    MetricSetManifest,
)
from fpbench.core.result_models import RunDefinition

__all__ = ["build_evaluation_summary"]


def build_evaluation_summary(
    *,
    manifest: MetricSetManifest,
    run: RunDefinition,
    decision_profile: DecisionProfile,
    releases: Sequence[str],
    counts: Sequence[EvaluationCountRecord],
    observations: Sequence[MetricObservation],
    generated_utc: str | None = None,
) -> EvaluationSummary:
    """Assemble the summary from artefacts that have already been verified."""
    return EvaluationSummary(
        metric_set_id=manifest.metric_set_id,
        algorithm_id=run.algorithm.algorithm_id,
        implementation_version=run.algorithm.implementation_version,
        execution_profile_id=run.execution_profile.profile_id,
        decision_profile_id=decision_profile.profile_id,
        threshold=decision_profile.threshold,
        releases=tuple(releases),
        count_records=tuple(counts),
        observations=tuple(observations),
        generated_utc=generated_utc or _utc_now(),
    )


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()
