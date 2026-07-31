"""The four files that make an evaluation authoritative, and safe to publish.

Stage 5A learned the shape of this: a directory can hold every intermediate a
finished derivation would hold and still be a crash halfway through, so a
last-written marker decides. Stage 5B applies the same discipline one layer up,
to numbers rather than to decisions (docs/adr/0020).

``MetricDerivationDefinition``
    What the evaluation is *going* to be, fixed before a single count exists.
    It pins the decision set, the eligibility set, all three views, the metric
    policy, the report profile and the exact metric code — by fingerprint, not by
    name. A different policy over the same decisions is a different evaluation
    and gets its own definition.

``EvaluationSummary``
    The machine-readable rendering of a verified metric set. Not an authority in
    itself: it is built *from* the metric set and can be rebuilt from it at any
    time.

``EvaluationReceipt``
    The committable statement of what was measured. Unlike stage 5A's derivation
    receipt, this one *may* carry outcome counts — that is the entire point of
    the stage. What it may not carry is anything below the aggregate: no score,
    no subject, no finger, no image, no pair, no job, no path. A release-level
    count is a statement about five hundred comparisons; a per-finger count is a
    statement about a person.

``EvaluationFinalizationMarker``
    Written last, after every other file has been read back and re-hashed.
    Without it there is no ``EVALUATION_READY``, however complete the directory
    looks.

One sentence appears verbatim in every receipt, and it is the sentence somebody
reading only this file needs: the threshold was documented rather than
calibrated, there are no confidence intervals, and the impostor set is a
closed-set sanity check rather than a false-match-rate experiment.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from fpbench.core.identifiers import validate_id
from fpbench.core.metric_models import EvaluationCountRecord, MetricObservation
from fpbench.core.provenance_models import (
    SoftwareProvenance,
    software_provenance_fingerprint,
)
from fpbench.core.serialization import stable_hash, to_plain

__all__ = [
    "MetricDerivationDefinition",
    "EvaluationSummary",
    "EvaluationReceipt",
    "EvaluationFinalizationMarker",
    "EvaluationState",
    "metric_derivation_definition_fingerprint",
    "evaluation_summary_content_hash",
    "report_content_hash",
    "evaluation_receipt_fingerprint",
    "evaluation_receipt_content_hash",
    "evaluation_finalization_fingerprint",
    "require_sanitised_evaluation",
    "EVALUATION_RECEIPT_SCHEMA_VERSION",
    "EVALUATION_FINALIZATION_SCHEMA_VERSION",
    "EVALUATION_SUMMARY_SCHEMA_VERSION",
    "EVALUATION_SCOPE_STATEMENT",
    "POOLED_SCOPE_LABEL",
    "STRUCTURAL_COUNT_KEYS",
]

EVALUATION_RECEIPT_SCHEMA_VERSION = "1"
EVALUATION_FINALIZATION_SCHEMA_VERSION = "1"
EVALUATION_SUMMARY_SCHEMA_VERSION = "1"

#: Printed verbatim into every evaluation receipt. Somebody will eventually read
#: only this file, and every clause here is a claim it must be impossible to
#: mistake this document for making (docs/adr/0030).
EVALUATION_SCOPE_STATEMENT = (
    "These are observed counts under one documented threshold, over one closed "
    "cohort. The threshold was not calibrated. No confidence interval, "
    "significance test or population-level false-match rate is claimed, and the "
    "same-subject different-finger set is a negative sanity check rather than an "
    "impostor experiment."
)

#: What a pooled row is called wherever a scope has to be a string key.
POOLED_SCOPE_LABEL = "pooled"

#: The structural shape the receipt records. Structure, not outcome: how many
#: comparisons there were, never how many matched.
STRUCTURAL_COUNT_KEYS: tuple[str, ...] = (
    "decisions",
    "eligibility_units",
    "unconditional_rows",
    "conditional_rows",
    "negative_sanity_rows",
)

_HEX = frozenset("0123456789abcdef")
_PATH_LIKE = re.compile(r"(^[A-Za-z]:[\\/])|(^\\\\)|(^/)|(\\)")

#: Keys that would take a receipt below the aggregate. Deliberately *not* the
#: stage 5A list: ``match_count`` and friends are the point of this document.
#: What must never appear is anything identifying a person, an image or a file
#: (spec section 58).
_FORBIDDEN_KEYS = frozenset(
    {
        "raw_score",
        "raw_scores",
        "score",
        "scores",
        "score_distribution",
        "min_score",
        "max_score",
        "mean_score",
        "subject_id",
        "subject_ids",
        "finger_id",
        "finger_ids",
        "canonical_finger",
        "image_id",
        "image_ids",
        "pair_id",
        "pair_ids",
        "job_id",
        "job_ids",
        "eligibility_unit_id",
        "filename",
        "filenames",
        "path",
        "paths",
        "dataset_root",
        "workspace",
        "template",
        "templates",
        "minutiae",
        "per_subject",
        "per_finger",
        "roc",
        "det",
        "eer",
    }
)


def _require_digest(value: str, field_name: str) -> str:
    digest = str(value).strip().lower()
    if len(digest) != 64 or not set(digest) <= _HEX:
        raise ValueError(f"{field_name} must be a 64-character hexadecimal digest")
    return digest


def _require_commit(value: str, field_name: str) -> str:
    commit = str(value).strip().lower()
    if len(commit) != 40 or not set(commit) <= _HEX:
        raise ValueError(f"{field_name} must be a full 40-character commit SHA")
    return commit


def _require_utc(value: str, field_name: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{field_name} must not be empty")
    return text


# ------------------------------------------------------------------ definition


@dataclass(frozen=True, slots=True)
class MetricDerivationDefinition:
    """What an evaluation is going to measure, pinned before it measures it.

    Every source is named by fingerprint. That is what makes ``prepare`` worth
    having as its own command: a decision set that is not decision-ready, a
    policy that does not parse, a dirty working tree — all of it fails here,
    before anything is written that would later have to be reconciled.

    The metric derivation commit is *not* required to be the decision derivation
    commit. Counting decisions written last month with code written today is
    normal and honest, as long as both commits are recorded — which is why there
    are two fields for them rather than one.
    """

    definition_id: str
    definition_fingerprint: str

    run_id: str
    result_set_fingerprint: str

    decision_set_id: str
    decision_set_fingerprint: str

    eligibility_set_id: str
    eligibility_set_fingerprint: str

    unconditional_view_fingerprint: str
    conditional_view_fingerprint: str
    non_mated_view_fingerprint: str

    metric_policy_id: str
    metric_policy_fingerprint: str

    report_profile_id: str
    report_profile_fingerprint: str

    metric_software: SoftwareProvenance
    metric_software_fingerprint: str

    created_utc: str

    def __post_init__(self) -> None:
        for name in (
            "definition_id",
            "run_id",
            "decision_set_id",
            "eligibility_set_id",
            "metric_policy_id",
            "report_profile_id",
        ):
            validate_id(str(getattr(self, name)))
        for name in (
            "definition_fingerprint",
            "result_set_fingerprint",
            "decision_set_fingerprint",
            "eligibility_set_fingerprint",
            "unconditional_view_fingerprint",
            "conditional_view_fingerprint",
            "non_mated_view_fingerprint",
            "metric_policy_fingerprint",
            "report_profile_fingerprint",
            "metric_software_fingerprint",
        ):
            object.__setattr__(self, name, _require_digest(getattr(self, name), name))

        software = self.metric_software
        if isinstance(software, Mapping):
            software = SoftwareProvenance(**software)
            object.__setattr__(self, "metric_software", software)
        if not isinstance(software, SoftwareProvenance):
            raise ValueError("metric_software must be SoftwareProvenance")
        if not software.is_research_grade:
            raise ValueError(
                "a metric derivation definition requires committed, clean software "
                "provenance; a dirty tree cannot produce an authoritative "
                "evaluation (docs/adr/0017)"
            )
        if self.metric_software_fingerprint != software_provenance_fingerprint(software):
            raise ValueError(
                "metric_software_fingerprint does not cover metric_software"
            )

        object.__setattr__(
            self, "created_utc", _require_utc(self.created_utc, "created_utc")
        )

        expected = metric_derivation_definition_fingerprint(self)
        if self.definition_fingerprint != expected:
            raise ValueError(
                "definition_fingerprint does not cover the definition's claims"
            )
        expected_id = f"metricderivation_{expected[:12]}"
        if self.definition_id != expected_id:
            raise ValueError(
                f"definition_id must be {expected_id!r}, got {self.definition_id!r}"
            )

    @property
    def metric_source_commit(self) -> str:
        return self.metric_software.source_revision


def metric_derivation_definition_fingerprint(
    definition: MetricDerivationDefinition | Mapping[str, Any],
) -> str:
    """A definition's identity, without its own identity and without its clock."""
    plain = dict(to_plain(definition))
    plain.pop("definition_id", None)
    plain.pop("definition_fingerprint", None)
    plain.pop("created_utc", None)
    return stable_hash(
        {"schema": "metric_derivation_definition_v1", "definition": plain}, length=64
    )


# -------------------------------------------------------------------- summary


@dataclass(frozen=True, slots=True)
class EvaluationSummary:
    """Every verified count and every verified rate, in one machine-readable file.

    Derived, and it says so: ``summary.json`` is not an authority. It is built
    from a metric set that has already been verified, and if the two ever
    disagree the metric set wins. Nothing downstream may compute a metric from
    the summary that the metric set does not already contain (spec section 48).
    """

    metric_set_id: str

    algorithm_id: str
    implementation_version: str
    execution_profile_id: str

    decision_profile_id: str
    threshold: str

    releases: tuple[str, ...]

    count_records: tuple[EvaluationCountRecord, ...]
    observations: tuple[MetricObservation, ...]

    generated_utc: str

    def __post_init__(self) -> None:
        for name in (
            "metric_set_id",
            "algorithm_id",
            "execution_profile_id",
            "decision_profile_id",
        ):
            validate_id(str(getattr(self, name)))
        for name in ("implementation_version", "threshold"):
            value = str(getattr(self, name)).strip()
            if not value:
                raise ValueError(f"{name} must not be empty")
            object.__setattr__(self, name, value)

        releases = tuple(str(item).strip() for item in self.releases)
        if not releases:
            raise ValueError("an evaluation summary must name the releases it covers")
        object.__setattr__(self, "releases", releases)

        object.__setattr__(self, "count_records", tuple(self.count_records))
        object.__setattr__(self, "observations", tuple(self.observations))
        if not self.count_records:
            raise ValueError("a summary with no count records is not one")
        if not self.observations:
            raise ValueError("a summary with no observations is not one")

        object.__setattr__(
            self, "generated_utc", _require_utc(self.generated_utc, "generated_utc")
        )


def evaluation_summary_content_hash(summary: EvaluationSummary) -> str:
    """A digest of the summary's numbers, excluding when it was rendered.

    The timestamp is out so that the same verified metric set, summarised twice,
    hashes the same. Everything else is in, down to the ordering: a summary that
    listed the same observations in a different order would read differently to a
    person, and reading is what it is for.
    """
    plain = dict(to_plain(summary))
    plain.pop("generated_utc", None)
    return stable_hash(
        {
            "schema": f"evaluation_summary_v{EVALUATION_SUMMARY_SCHEMA_VERSION}",
            "summary": plain,
        },
        length=64,
    )


def report_content_hash(markdown: str) -> str:
    """A digest of a rendered report's exact text.

    Line endings are normalised first. The same report checked out by git on
    Windows and on Linux is the same report, and a finalization marker that
    disagreed with itself across platforms would be worse than useless.
    """
    normalised = str(markdown).replace("\r\n", "\n").replace("\r", "\n")
    return stable_hash(
        {"schema": "evaluation_report_content_v1", "markdown": normalised}, length=64
    )


# -------------------------------------------------------------------- receipt


def require_sanitised_evaluation(receipt: "EvaluationReceipt") -> None:
    """Refuse a receipt carrying anything below the aggregate.

    Mechanical, and therefore only as good as its list — but the mistakes it
    catches are the ones that are easy to make and hard to see: a workspace path
    that came along with a count, a subject id added "for traceability", a score
    that leaked in through a debugging field nobody removed.
    """
    _walk(to_plain(receipt), path="receipt")


def _walk(value: Any, *, path: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).lower() in _FORBIDDEN_KEYS:
                raise ValueError(
                    f"{path}.{key} must not appear in an evaluation receipt; "
                    "aggregate counts are publishable, the things they were "
                    "aggregated over are not"
                )
            _walk(item, path=f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _walk(item, path=f"{path}[{index}]")
        return
    if isinstance(value, str) and _PATH_LIKE.search(value):
        raise ValueError(f"{path} looks like a filesystem path: {value!r}")


def _freeze_counts(value: Mapping[str, int], field_name: str) -> Mapping[str, int]:
    counts: dict[str, int] = {}
    for key, count in dict(value).items():
        number = int(count)
        if number < 0:
            raise ValueError(f"{field_name}[{key}] must not be negative")
        counts[str(key)] = number
    return MappingProxyType(dict(sorted(counts.items())))


@dataclass(frozen=True, slots=True)
class EvaluationReceipt:
    """The committable proof of what was measured, and out of what.

    Every rate in ``metrics`` is stored as its two integers, never as a
    percentage. A reader with this file and nothing else can recompute every
    number in the report and check that the pooled values are the sums they claim
    to be (docs/adr/0026, docs/adr/0028).
    """

    schema_version: str

    run_id: str
    result_set_id: str

    decision_profile_id: str
    decision_set_id: str
    eligibility_set_id: str

    metric_policy_id: str
    metric_policy_fingerprint: str

    metric_set_id: str
    metric_set_fingerprint: str

    metric_source_commit: str
    metric_source_tree_clean: bool

    releases: tuple[str, ...]

    structural_counts: Mapping[str, int]

    #: ``metric_id -> scope label -> {"numerator": n, "denominator": d}``. A
    #: scope label is a release name or ``"pooled"``, and nothing finer than a
    #: release may ever appear as a key here (spec section 58).
    metrics: Mapping[str, Mapping[str, Mapping[str, int]]]

    statement: str = EVALUATION_SCOPE_STATEMENT
    created_utc: str = ""

    def __post_init__(self) -> None:
        for name in (
            "run_id",
            "result_set_id",
            "decision_profile_id",
            "decision_set_id",
            "eligibility_set_id",
            "metric_policy_id",
            "metric_set_id",
        ):
            validate_id(str(getattr(self, name)))
        for name in ("metric_policy_fingerprint", "metric_set_fingerprint"):
            object.__setattr__(self, name, _require_digest(getattr(self, name), name))

        object.__setattr__(
            self,
            "metric_source_commit",
            _require_commit(self.metric_source_commit, "metric_source_commit"),
        )
        if not self.metric_source_tree_clean:
            raise ValueError(
                "an evaluation receipt cannot describe an uncommitted working tree "
                "(docs/adr/0017)"
            )

        releases = tuple(str(item).strip() for item in self.releases)
        if not releases:
            raise ValueError("an evaluation receipt must name the releases it covers")
        if len(set(releases)) != len(releases):
            raise ValueError(f"releases repeat: {list(releases)}")
        object.__setattr__(self, "releases", releases)

        object.__setattr__(
            self,
            "structural_counts",
            _freeze_counts(self.structural_counts, "structural_counts"),
        )
        missing = [
            key for key in STRUCTURAL_COUNT_KEYS if key not in self.structural_counts
        ]
        if missing:
            raise ValueError(f"structural_counts is missing {missing}")
        unexpected = sorted(set(self.structural_counts) - set(STRUCTURAL_COUNT_KEYS))
        if unexpected:
            raise ValueError(f"structural_counts carries unexpected keys {unexpected}")

        allowed_scopes = set(releases) | {POOLED_SCOPE_LABEL}
        metrics: dict[str, Mapping[str, Mapping[str, int]]] = {}
        for metric_id, by_scope in dict(self.metrics).items():
            validate_id(str(metric_id))
            scopes: dict[str, Mapping[str, int]] = {}
            for scope_label, counts in dict(by_scope).items():
                label = str(scope_label)
                if label not in allowed_scopes:
                    raise ValueError(
                        f"metric {metric_id} reports a scope {label!r} that is "
                        f"neither a release nor {POOLED_SCOPE_LABEL!r}; an "
                        "evaluation receipt is never broken down finer than a "
                        "release"
                    )
                pair = dict(counts)
                if set(pair) != {"numerator", "denominator"}:
                    raise ValueError(
                        f"metric {metric_id} at {label} must report exactly a "
                        f"numerator and a denominator, got {sorted(pair)}; a "
                        "percentage on its own is not checkable (docs/adr/0026)"
                    )
                scopes[label] = _freeze_counts(pair, f"metrics[{metric_id}][{label}]")
            if not scopes:
                raise ValueError(f"metric {metric_id} reports no scope at all")
            metrics[str(metric_id)] = MappingProxyType(dict(sorted(scopes.items())))
        if not metrics:
            raise ValueError("an evaluation receipt with no metrics is not one")
        object.__setattr__(self, "metrics", MappingProxyType(dict(sorted(metrics.items()))))

        version = str(self.schema_version).strip()
        if version != EVALUATION_RECEIPT_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported evaluation receipt schema version {version!r}"
            )
        object.__setattr__(self, "schema_version", version)

        if str(self.statement).strip() != EVALUATION_SCOPE_STATEMENT:
            raise ValueError(
                "an evaluation receipt states, verbatim, what it does not claim"
            )
        object.__setattr__(
            self, "created_utc", _require_utc(self.created_utc, "created_utc")
        )

        require_sanitised_evaluation(self)


def evaluation_receipt_fingerprint(receipt: EvaluationReceipt) -> str:
    """A digest of the receipt's durable claims, excluding when it was written."""
    plain = dict(to_plain(receipt))
    plain.pop("created_utc", None)
    return stable_hash(
        {
            "schema": f"evaluation_receipt_v{EVALUATION_RECEIPT_SCHEMA_VERSION}",
            "receipt": plain,
        },
        length=64,
    )


def evaluation_receipt_content_hash(receipt: EvaluationReceipt) -> str:
    """Digest every byte-significant field, timestamp included.

    The semantic fingerprint ignores ``created_utc`` so that the same evaluation
    recognises itself across reruns. Finalization binds the stronger identity:
    once the marker is published, even the timestamp is frozen.
    """
    return stable_hash(
        {"schema": "evaluation_receipt_content_v1", "receipt": to_plain(receipt)},
        length=64,
    )


# --------------------------------------------------------------------- marker


@dataclass(frozen=True, slots=True)
class EvaluationFinalizationMarker:
    """The last-written authority over a verified evaluation.

    It names the *decision* finalization marker it rests on as well as its own
    artefacts. That link is what stops an evaluation from outliving the
    derivation beneath it: re-derive the decisions differently and this marker
    stops matching, however intact the metric files are.
    """

    schema_version: str
    finalization_id: str
    finalization_fingerprint: str

    source_decision_finalization_fingerprint: str

    metric_definition_fingerprint: str
    metric_set_fingerprint: str

    summary_content_hash: str
    report_content_hash: str

    evaluation_receipt_fingerprint: str
    evaluation_receipt_content_hash: str

    metric_source_commit: str
    metric_source_tree_clean: bool

    created_utc: str

    def __post_init__(self) -> None:
        validate_id(self.finalization_id)
        for name in (
            "finalization_fingerprint",
            "source_decision_finalization_fingerprint",
            "metric_definition_fingerprint",
            "metric_set_fingerprint",
            "summary_content_hash",
            "report_content_hash",
            "evaluation_receipt_fingerprint",
            "evaluation_receipt_content_hash",
        ):
            object.__setattr__(self, name, _require_digest(getattr(self, name), name))

        object.__setattr__(
            self,
            "metric_source_commit",
            _require_commit(self.metric_source_commit, "metric_source_commit"),
        )
        if not self.metric_source_tree_clean:
            raise ValueError(
                "evaluation finalization requires a clean metric-engine tree"
            )

        version = str(self.schema_version).strip()
        if version != EVALUATION_FINALIZATION_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported evaluation finalization schema version {version!r}"
            )
        object.__setattr__(self, "schema_version", version)
        object.__setattr__(
            self, "created_utc", _require_utc(self.created_utc, "created_utc")
        )

        expected = evaluation_finalization_fingerprint(self)
        if self.finalization_fingerprint != expected:
            raise ValueError(
                "finalization_fingerprint does not cover the marker's claims"
            )
        expected_id = f"evaluationfinal_{expected[:12]}"
        if self.finalization_id != expected_id:
            raise ValueError(
                f"finalization_id must be {expected_id!r}, got "
                f"{self.finalization_id!r}"
            )


def evaluation_finalization_fingerprint(
    marker: EvaluationFinalizationMarker | Mapping[str, Any],
) -> str:
    """Derive a marker's identity from its claims, without its own identity."""
    plain = dict(to_plain(marker))
    plain.pop("finalization_id", None)
    plain.pop("finalization_fingerprint", None)
    plain.pop("created_utc", None)
    return stable_hash(
        {"schema": "evaluation_finalization_v1", "marker": plain}, length=64
    )


# ---------------------------------------------------------------------- state


@dataclass(frozen=True, slots=True)
class EvaluationState:
    """How much of an evaluation's evidence chain is currently in place.

    Derived, never stored as authority. Every ``*_valid`` flag means "recomputed
    from the decisions and views, and agreed" — not "the file is there"
    (docs/adr/0012).
    """

    run_id: str
    metric_set_id: str | None

    status: Any  # EvaluationStatus; avoids an enums import cycle

    definition_present: bool
    source_decision_ready: bool

    policy_present: bool
    policy_valid: bool

    counts_present: bool
    counts_valid: bool

    observations_present: bool
    observations_valid: bool

    metric_set_present: bool
    metric_set_valid: bool

    summary_present: bool
    summary_valid: bool

    report_present: bool
    report_valid: bool

    receipt_present: bool
    receipt_valid: bool

    finalization_present: bool
    finalization_valid: bool

    total_count_records: int = 0
    total_observations: int = 0

    issues: tuple[str, ...] = ()
    inspected_utc: str = ""

    def __post_init__(self) -> None:
        validate_id(self.run_id)
        if self.metric_set_id is not None:
            validate_id(self.metric_set_id)
        object.__setattr__(self, "issues", tuple(str(item) for item in self.issues))

    @property
    def is_evaluation_ready(self) -> bool:
        from fpbench.core.enums import EvaluationStatus

        return self.status is EvaluationStatus.EVALUATION_READY
