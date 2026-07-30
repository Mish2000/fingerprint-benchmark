"""Which build of *this* project produced a result.

A run already pins the pair manifest, the algorithm, the machine and the
execution profile. None of that says which Python code serialised the request,
mapped the failure, wrote the row or decided a job could be skipped — and all
four can change a stored result without changing anything a run currently
identifies. So a research run identifies its own source revision too
(docs/adr/0017).

The rule that follows is uncomfortable and deliberate: a research run may only
be created from a **clean** working tree. ``dirty = true`` is not an acceptable
record, because a receipt read a year later cannot recover code that was never
committed. The fix for an uncommitted change is to commit it.

Ordinary development is not held to this. :func:`capture_software_provenance`
with ``require_clean=False`` reports what it finds, including a repository that
has no git metadata at all — the test suite has to run inside a source
distribution, and a unit test is not evidence.

The dataclass lives here rather than in ``fpbench.provenance`` because the
storage layer persists it inside a run's environment report, and ``storage``
may only import ``core``. The rules for *capturing* it stay in
:mod:`fpbench.provenance.software`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from fpbench.core.serialization import freeze_str_mapping, stable_hash

__all__ = [
    "SoftwareProvenance",
    "software_provenance_fingerprint",
    "PROVENANCE_SCHEMA_VERSION",
    "PROVENANCE_KIND_GIT",
    "PROVENANCE_KIND_UNAVAILABLE",
    "TRACKED_DEPENDENCIES",
]

#: Bumped when the meaning of software provenance changes. Inside the
#: fingerprint, so a bump separates new environments from old.
PROVENANCE_SCHEMA_VERSION = "1"

#: The repository was read through git and reported a commit.
PROVENANCE_KIND_GIT = "git"

#: There is no git metadata here — an exported tarball, an installed wheel. A
#: research run refuses this; development does not have to.
PROVENANCE_KIND_UNAVAILABLE = "unavailable"

#: The third-party packages whose versions can change a stored result. Both
#: touch persistence directly: pyarrow writes every result file, PyYAML parses
#: every config that defines what runs. The interpreter itself is recorded
#: separately.
TRACKED_DEPENDENCIES: tuple[str, ...] = ("pyarrow", "pyyaml")

_HEX = frozenset("0123456789abcdef")


def _require_non_empty(value: str, field_name: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{field_name} must not be empty")
    return text


@dataclass(frozen=True, slots=True)
class SoftwareProvenance:
    """The exact fpbench build a run was carried out by.

    Carries no path. Where the repository happens to sit on one machine says
    nothing about the experiment, and a value that differs between two
    reproductions of the same run has no business inside a fingerprint.
    """

    provenance_kind: str
    source_revision: str
    source_tree_clean: bool

    package_version: str
    python_version: str
    python_implementation: str

    dependency_versions: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "provenance_kind",
            "source_revision",
            "package_version",
            "python_version",
            "python_implementation",
        ):
            object.__setattr__(
                self, name, _require_non_empty(getattr(self, name), name)
            )
        object.__setattr__(self, "source_tree_clean", bool(self.source_tree_clean))
        object.__setattr__(
            self, "dependency_versions", freeze_str_mapping(self.dependency_versions)
        )

        if self.provenance_kind == PROVENANCE_KIND_GIT:
            revision = self.source_revision.lower()
            if len(revision) != 40 or not set(revision) <= _HEX:
                raise ValueError(
                    "source_revision must be a full 40-character commit SHA when "
                    f"provenance_kind is {PROVENANCE_KIND_GIT!r}, got "
                    f"{self.source_revision!r}"
                )
            object.__setattr__(self, "source_revision", revision)
        elif self.source_tree_clean:
            # "Clean" is a claim about a tracked tree. Without git metadata
            # there is nothing to be clean with respect to, and letting the
            # claim stand would let a research preflight pass on no evidence.
            raise ValueError(
                f"provenance_kind {self.provenance_kind!r} cannot report a clean "
                "source tree; there is no revision to compare against"
            )

    @property
    def is_research_grade(self) -> bool:
        """Whether this provenance may back a research run.

        A committed revision *and* nothing uncommitted beside it. Both halves
        are needed: a commit alone does not describe a tree with edits in it.
        """
        return self.provenance_kind == PROVENANCE_KIND_GIT and self.source_tree_clean


def software_provenance_fingerprint(provenance: SoftwareProvenance) -> str:
    """A 64-character digest of the build, with no timestamp and no path.

    Changing the commit changes it. Upgrading pyarrow changes it. Capturing the
    same repository twice a day apart does not.
    """
    return stable_hash(
        {
            "schema": "software_provenance_fingerprint_v1",
            "provenance_schema_version": PROVENANCE_SCHEMA_VERSION,
            "provenance_kind": provenance.provenance_kind,
            "source_revision": provenance.source_revision,
            "source_tree_clean": provenance.source_tree_clean,
            "package_version": provenance.package_version,
            "python_version": provenance.python_version,
            "python_implementation": provenance.python_implementation,
            "dependency_versions": dict(provenance.dependency_versions),
        },
        length=64,
    )
