"""Orchestration: what to run, and running it.

Dependency rule: ``execution`` is the one package allowed to import ``core``,
``imaging``, ``adapters`` and ``storage`` together. It receives its adapter and
its preparer by injection and never names a specific algorithm
(docs/adr/0007).
"""

from fpbench.execution.audit import (
    audit_run,
    validate_existing_results,
    verify_run_completion,
)
from fpbench.execution.batch_runner import RunExecutionSummary, SequentialRunExecutor
from fpbench.execution.completion import RunCompletionService, build_run_completion
from fpbench.execution.jobs import ComparisonJob, build_comparison_job
from fpbench.execution.planner import STAGE_ORDER, build_execution_plan
from fpbench.execution.progress import inspect_run_progress
from fpbench.execution.run_definition import (
    DEFAULT_EXECUTION_PROFILE,
    RunDefinition,
    create_run_definition,
    run_fingerprint_of,
)
from fpbench.execution.runner import (
    JobDisposition,
    JobExecutionOutcome,
    SingleJobRunner,
)

__all__ = [
    "ComparisonJob",
    "DEFAULT_EXECUTION_PROFILE",
    "JobDisposition",
    "JobExecutionOutcome",
    "RunCompletionService",
    "RunDefinition",
    "RunExecutionSummary",
    "STAGE_ORDER",
    "SequentialRunExecutor",
    "SingleJobRunner",
    "audit_run",
    "build_comparison_job",
    "build_execution_plan",
    "build_run_completion",
    "create_run_definition",
    "inspect_run_progress",
    "run_fingerprint_of",
    "validate_existing_results",
    "verify_run_completion",
]
