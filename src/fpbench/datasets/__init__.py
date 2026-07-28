"""Description of raw material on disk.

Dependency rule: ``datasets`` may import ``core``; it must not import
``protocols``.
"""

from fpbench.datasets.base import (
    DatasetProvider,
    DatasetSpec,
    DatasetValidationReport,
    Severity,
    ValidationIssue,
    summarise_subjects,
)
from fpbench.datasets.registry import create_provider, load_dataset_spec

__all__ = [
    "DatasetProvider",
    "DatasetSpec",
    "DatasetValidationReport",
    "Severity",
    "ValidationIssue",
    "create_provider",
    "load_dataset_spec",
    "summarise_subjects",
]
