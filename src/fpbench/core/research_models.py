"""What a finished research run says about itself, and what it may not say.

Two records:

``ResearchRunState``
    Derived, never authoritative — how much of the evidence chain is currently
    in place. Recomputed from the files every time, like
    :class:`~fpbench.core.run_state_models.RunProgress` and for the same reason
    (docs/adr/0012).

``ResearchRunReceipt``
    The sanitised statement that the chain was complete. It is the one artefact
    of a run that is meant to leave the workspace and enter version control, so
    it is defined by what it must **not** contain: no score, no subject, no
    image id, no filename, no dataset path, no workspace path, no template, no
    minutiae, no absolute path to anything.

    And no conclusion. A receipt proves that 6,000 comparisons were carried out
    by an identified build of an identified matcher over an identified set of
    pairs, and stops there. FMR, FNMR, EER, "SourceAFIS is accurate to..." — none
    of that is missing because the scores are missing. It is missing because the
    decision profiles, the SELF eligibility rule, the metric definitions and the
    failure denominators that would make such a sentence mean anything have not
    been built yet (docs/adr/0003).

:func:`require_sanitised` enforces the first list mechanically, because "we were
careful" is not a property a reviewer can check and a path leaking into a
committed file is not the kind of mistake that gets noticed by reading.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from fpbench.core.enums import ResearchRunStatus, RunState
from fpbench.core.identifiers import validate_id
from fpbench.core.serialization import stable_hash, to_plain

__all__ = [
    "ResearchRunState",
    "ResearchRunReceipt",
    "require_sanitised",
    "research_receipt_fingerprint",
    "RESEARCH_RECEIPT_SCHEMA_VERSION",
    "NO_CONCLUSION_STATEMENT",
]

RESEARCH_RECEIPT_SCHEMA_VERSION = "1"

#: Printed verbatim into every receipt. A reader who sees only this file must
#: not be able to mistake it for a result.
NO_CONCLUSION_STATEMENT = (
    "This receipt proves execution completeness and provenance. "
    "It contains no biometric performance conclusion."
)

_HEX = frozenset("0123456789abcdef")

#: Anything that looks like a filesystem location. Windows drive letters,
#: UNC and POSIX roots, and backslash-separated paths.
_PATH_LIKE = re.compile(r"(^[A-Za-z]:[\\/])|(^\\\\)|(^/)|(\\)")


def _require_digest(value: str, field_name: str) -> str:
    digest = str(value).strip().lower()
    if len(digest) != 64 or not set(digest) <= _HEX:
        raise ValueError(f"{field_name} must be a 64-character hexadecimal digest")
    return digest


def _require_non_negative(value: int, field_name: str) -> int:
    number = int(value)
    if number < 0:
        raise ValueError(f"{field_name} must not be negative")
    return number


def _freeze_counts(value: Mapping[str, int], field_name: str) -> Mapping[str, int]:
    from types import MappingProxyType

    counts: dict[str, int] = {}
    for key, count in dict(value).items():
        number = int(count)
        if number < 0:
            raise ValueError(f"{field_name}[{key}] must not be negative")
        counts[str(key)] = number
    return MappingProxyType(dict(sorted(counts.items())))


# ------------------------------------------------------------------- state


@dataclass(frozen=True, slots=True)
class ResearchRunState:
    """How far along the evidence chain a run currently is.

    ``core_state`` is the ordinary run state; ``status`` is the research one.
    Both are reported because they answer different questions and a run can be
    ``VERIFIED`` while being nowhere near ``RESEARCH_READY``.
    """

    run_id: str
    plan_id: str

    status: ResearchRunStatus
    core_state: RunState

    planned_jobs: int
    stored_results: int
    missing_results: int

    runtime_reference_present: bool
    runtime_bundle_valid: bool
    result_set_present: bool
    result_set_valid: bool
    receipt_present: bool
    receipt_valid: bool

    issues: tuple[str, ...] = ()
    inspected_utc: str = ""

    def __post_init__(self) -> None:
        validate_id(self.run_id)
        for name in ("planned_jobs", "stored_results", "missing_results"):
            object.__setattr__(
                self, name, _require_non_negative(getattr(self, name), name)
            )
        object.__setattr__(self, "issues", tuple(str(item) for item in self.issues))

    @property
    def is_research_ready(self) -> bool:
        return self.status is ResearchRunStatus.RESEARCH_READY


# ----------------------------------------------------------------- receipt


@dataclass(frozen=True, slots=True)
class ResearchRunReceipt:
    """The committable proof that a research run completed with its provenance.

    Every field is either an identifier, a fingerprint or a count. There is
    deliberately no score, no distribution, no threshold and no metric.

    ``sourceafis_validation_fingerprint`` names the algorithm because stage 4B
    has exactly one research validator and the field is part of the agreed
    receipt shape. When a second algorithm gains one, this becomes
    ``algorithm_validation_fingerprint`` and the schema version moves with it.
    """

    schema_version: str

    source_commit: str
    source_tree_clean: bool

    dataset_id: str
    cohort_id: str
    pair_manifest_hash: str

    run_id: str
    run_fingerprint: str

    plan_id: str
    plan_fingerprint: str

    environment_fingerprint: str

    runtime_bundle_id: str
    runtime_bundle_fingerprint: str
    bridge_jar_sha256: str

    result_set_id: str
    result_set_fingerprint: str

    audit_fingerprint: str
    sourceafis_validation_fingerprint: str
    completion_id: str
    completion_fingerprint: str

    planned_jobs: int
    stored_results: int
    success_count: int
    algorithmic_failure_count: int
    blocking_failure_count: int

    failure_counts: Mapping[str, int] = field(default_factory=dict)
    release_counts: Mapping[str, int] = field(default_factory=dict)
    stage_counts: Mapping[str, int] = field(default_factory=dict)
    timing_summary: Mapping[str, str] = field(default_factory=dict)

    statement: str = NO_CONCLUSION_STATEMENT
    created_utc: str = ""

    def __post_init__(self) -> None:
        for name in (
            "run_id",
            "plan_id",
            "cohort_id",
            "result_set_id",
            "runtime_bundle_id",
            "completion_id",
            "dataset_id",
        ):
            validate_id(str(getattr(self, name)))
        for name in (
            "run_fingerprint",
            "plan_fingerprint",
            "environment_fingerprint",
            "runtime_bundle_fingerprint",
            "bridge_jar_sha256",
            "result_set_fingerprint",
            "audit_fingerprint",
            "sourceafis_validation_fingerprint",
            "completion_fingerprint",
            "pair_manifest_hash",
        ):
            object.__setattr__(self, name, _require_digest(getattr(self, name), name))

        commit = str(self.source_commit).strip().lower()
        if len(commit) != 40 or not set(commit) <= _HEX:
            raise ValueError("source_commit must be a full 40-character commit SHA")
        object.__setattr__(self, "source_commit", commit)
        if not self.source_tree_clean:
            raise ValueError(
                "a research receipt cannot describe an uncommitted working tree "
                "(docs/adr/0017)"
            )

        for name in (
            "planned_jobs",
            "stored_results",
            "success_count",
            "algorithmic_failure_count",
            "blocking_failure_count",
        ):
            object.__setattr__(
                self, name, _require_non_negative(getattr(self, name), name)
            )
        if self.blocking_failure_count:
            raise ValueError(
                "a research receipt cannot be issued for a run with infrastructure "
                "failures; those indicate a broken pipeline, not a biometric outcome"
            )
        if self.stored_results != self.planned_jobs:
            raise ValueError(
                "a research receipt accounts for every planned job: "
                f"{self.stored_results} stored for {self.planned_jobs} planned"
            )
        if (
            self.success_count
            + self.algorithmic_failure_count
            + self.blocking_failure_count
            != self.stored_results
        ):
            raise ValueError(
                "success and failure counts must add up to the stored results"
            )

        for name in ("failure_counts", "release_counts", "stage_counts"):
            object.__setattr__(
                self, name, _freeze_counts(getattr(self, name), name)
            )
        from fpbench.core.serialization import freeze_str_mapping

        object.__setattr__(
            self, "timing_summary", freeze_str_mapping(self.timing_summary)
        )

        if str(self.statement).strip() != NO_CONCLUSION_STATEMENT:
            raise ValueError(
                "a research receipt states, verbatim, that it carries no "
                "performance conclusion"
            )
        object.__setattr__(self, "schema_version", str(self.schema_version).strip())
        if not self.schema_version:
            raise ValueError("schema_version must not be empty")
        object.__setattr__(self, "created_utc", str(self.created_utc).strip())
        if not self.created_utc:
            raise ValueError("created_utc must not be empty")

        require_sanitised(self)


def require_sanitised(receipt: "ResearchRunReceipt") -> None:
    """Refuse a receipt that carries anything a receipt must not carry.

    Checks the rendered form rather than the fields one by one, so a field
    added later is covered without anyone remembering to extend a list. It can
    only catch what is mechanically recognisable — a path, a forbidden key — and
    that is the point: it makes the cheap mistakes impossible, and leaves the
    expensive ones to review.
    """
    forbidden_keys = {
        "raw_score",
        "raw_scores",
        "scores",
        "score",
        "subject_id",
        "subject_ids",
        "image_id",
        "image_ids",
        "filename",
        "filenames",
        "dataset_root",
        "workspace",
        "template",
        "templates",
        "minutiae",
        "threshold",
        "decision",
        "fmr",
        "fnmr",
        "eer",
    }
    plain = to_plain(receipt)
    _walk_sanitised(plain, forbidden_keys, path="receipt")


def _walk_sanitised(value: Any, forbidden_keys: set[str], *, path: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).lower() in forbidden_keys:
                raise ValueError(
                    f"{path}.{key} must not appear in a research receipt"
                )
            _walk_sanitised(item, forbidden_keys, path=f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _walk_sanitised(item, forbidden_keys, path=f"{path}[{index}]")
        return
    if isinstance(value, str) and _PATH_LIKE.search(value):
        raise ValueError(f"{path} looks like a filesystem path: {value!r}")


def research_receipt_fingerprint(receipt: ResearchRunReceipt) -> str:
    """A digest of the receipt's durable content, excluding when it was written."""
    plain = dict(to_plain(receipt))
    plain.pop("created_utc", None)
    plain.pop("timing_summary", None)
    return stable_hash(
        {"schema": f"research_receipt_v{RESEARCH_RECEIPT_SCHEMA_VERSION}", "receipt": plain},
        length=64,
    )
