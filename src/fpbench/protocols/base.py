"""The contract a protocol implements.

A protocol answers two questions and nothing else:

    build_cohort(subjects)        which subjects take part?
    build_pairs(cohort, images)   which comparisons does that imply?

It never runs an algorithm, applies a threshold or reads a result. Its output —
the cohort and the pair manifest — is produced once and consumed by every
algorithm (docs/adr/0001).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable, Sequence

from fpbench.core.models import Cohort, ComparisonPair, ImageRecord, SubjectRecord

__all__ = ["Protocol"]


class Protocol(ABC):
    """Selects participants and enumerates the comparisons between them."""

    protocol_id: str
    dataset_id: str

    @property
    @abstractmethod
    def releases(self) -> tuple[str, ...]:
        """Dataset releases this protocol runs over."""

    @abstractmethod
    def build_cohort(self, subjects: Iterable[SubjectRecord]) -> Cohort:
        """Choose the participating subjects from the dataset's subject manifest."""

    @abstractmethod
    def build_pairs(
        self, cohort: Cohort, images: Sequence[ImageRecord]
    ) -> tuple[ComparisonPair, ...]:
        """Enumerate every comparison the protocol defines for ``cohort``."""
