"""Orchestration: what to run, and running it.

Dependency rule: ``execution`` is the one package allowed to import ``core``,
``imaging``, ``adapters`` and ``storage`` together. It receives its adapter and
its preparer by injection and never names a specific algorithm
(docs/adr/0007).
"""

from fpbench.execution.jobs import ComparisonJob, build_comparison_job
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
    "RunDefinition",
    "SingleJobRunner",
    "build_comparison_job",
    "create_run_definition",
    "run_fingerprint_of",
]
