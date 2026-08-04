"""The stage 5B/6B names for the shared evaluation engine.

Everything this module used to implement now lives in
:mod:`fpbench.experiments.algorithm_evaluation`, unchanged in behaviour and free
of any algorithm's vocabulary. What remains here is the import surface stage 5B
and stage 6B callers were written against, so that moving the code did not
require touching a wrapper, a test or a committed identity (docs/adr/0056).

``SourceAfisEvaluationExperimentSpec`` is now an alias. There was never anything
SourceAFIS-shaped about it — three fields, all data — and once NBIS is counted by
the same engine, keeping a second name for the same record would be keeping a
distinction that does not exist.
"""

from __future__ import annotations

from fpbench.experiments.algorithm_evaluation import (
    REPOSITORY_ROOT,
    AlgorithmEvaluationExperimentSpec,
    EvaluationExperimentConfig,
    PreparedEvaluation,
    derive_metrics,
    finalize_evaluation,
    inspect_evaluation_experiment,
    load_evaluation_config,
    prepare_evaluation,
    read_verified_report,
)

#: Historical name, kept for stage 5B and 6B callers and annotations.
SourceAfisEvaluationExperimentSpec = AlgorithmEvaluationExperimentSpec

__all__ = [
    "SourceAfisEvaluationExperimentSpec",
    "AlgorithmEvaluationExperimentSpec",
    "EvaluationExperimentConfig",
    "PreparedEvaluation",
    "REPOSITORY_ROOT",
    "load_evaluation_config",
    "prepare_evaluation",
    "derive_metrics",
    "inspect_evaluation_experiment",
    "finalize_evaluation",
    "read_verified_report",
]
