"""The contract every dataset provider implements.

A provider answers exactly two questions about raw material on disk:

    scan()      what images exist, and what is each one?
    validate()  does what is on disk match what the release claims?

It never decides which images take part in an experiment. That is the
protocol's job, and keeping the two apart is what lets one pair manifest serve
every algorithm (docs/adr/0001).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from fpbench.core.models import ImageRecord, SubjectRecord

__all__ = [
    "Severity",
    "ValidationIssue",
    "DatasetValidationReport",
    "DatasetSpec",
    "DatasetProvider",
]


class Severity(str, Enum):
    """How a validation finding should be treated.

    ERROR   the file cannot be described faithfully; it must not be used.
    WARNING the file is usable, but something about it is not as declared.
    INFO    worth recording, no action implied.
    """

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    severity: Severity
    detail: str
    relative_path: str | None = None


@dataclass(frozen=True, slots=True)
class DatasetValidationReport:
    dataset_id: str
    release: str
    checked_files: int
    issues: tuple[ValidationIssue, ...] = ()

    @property
    def counts_by_code(self) -> Mapping[str, int]:
        return dict(Counter(issue.code for issue in self.issues))

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        return tuple(i for i in self.issues if i.severity is Severity.ERROR)

    @property
    def is_clean(self) -> bool:
        """True when nothing blocks use of the release.

        Warnings do not make a release unusable — SD300C is expected to carry
        thousands of PPI-metadata warnings and is still the primary 2000 ppi
        source (docs/adr/0004).
        """
        return not self.errors


@dataclass(frozen=True, slots=True)
class DatasetSpec:
    """A dataset configuration after YAML loading, before provider-specific parsing.

    ``options`` stays untyped here on purpose: only the provider knows what a
    valid option set for its own layout looks like, and the registry must not
    grow knowledge of individual datasets.
    """

    dataset_id: str
    provider: str
    root: Path
    options: Mapping[str, Any] = field(default_factory=dict)


class DatasetProvider(ABC):
    """Describes the raw material of one dataset."""

    dataset_id: str

    @property
    @abstractmethod
    def releases(self) -> tuple[str, ...]:
        """Release identifiers this provider can serve, in declaration order."""

    @abstractmethod
    def scan(self, release: str) -> Iterator[ImageRecord]:
        """Yield one record per image file present in ``release``."""

    @abstractmethod
    def validate(self, release: str) -> DatasetValidationReport:
        """Check the release on disk against what it declares."""

    def scan_all(self) -> Iterator[ImageRecord]:
        for release in self.releases:
            yield from self.scan(release)


def summarise_subjects(images: Iterable[ImageRecord]) -> list[SubjectRecord]:
    """Aggregate image records into one :class:`SubjectRecord` per subject/release.

    Dataset-agnostic, so it lives beside the contract rather than inside any
    one provider.
    """
    from fpbench.core.enums import Impression

    buckets: dict[tuple[str, str], list[ImageRecord]] = {}
    for image in images:
        if not image.is_usable:
            continue
        buckets.setdefault((image.release, image.subject_id), []).append(image)

    records: list[SubjectRecord] = []
    for (release, subject_id), group in sorted(buckets.items()):
        plain = sorted(
            {
                i.position
                for i in group
                if i.impression is Impression.PLAIN and i.is_single_finger
            }
        )
        roll = sorted(
            {
                i.position
                for i in group
                if i.impression is Impression.ROLL and i.is_single_finger
            }
        )
        records.append(
            SubjectRecord(
                subject_id=subject_id,
                dataset_id=group[0].dataset_id,
                release=release,
                image_count=len(group),
                plain_positions=tuple(plain),
                roll_positions=tuple(roll),
                multi_finger_count=sum(1 for i in group if i.is_multi_finger),
            )
        )
    return records


def require_releases(provider: DatasetProvider, releases: Sequence[str]) -> None:
    """Raise if any requested release is unknown to ``provider``."""
    from fpbench.core.errors import ConfigurationError

    unknown = [r for r in releases if r not in provider.releases]
    if unknown:
        raise ConfigurationError(
            f"dataset {provider.dataset_id!r} has no release(s) {unknown}; "
            f"known releases: {list(provider.releases)}"
        )
