"""The two files that make a derivation authoritative, and safe to publish.

Stage 4B learned this the hard way: intermediate artefacts can be written
correctly and still not amount to a finished thing, because a crash halfway
leaves a directory that looks complete. The answer there was a last-written
marker, and the answer here is the same one, applied to decisions
(docs/adr/0020).

``DecisionDerivationReceipt``
    The sanitised statement that a derivation happened, meant to be committed.
    It names every link by fingerprint and carries counts of *structure* — how
    many decisions, how many units, how many rows per view.

    It carries no counts of *outcome*. Not how many comparisons matched, not how
    many fingers were eligible, not how many rows the conditional view included.
    Those are results, and a result derived from a threshold nobody has
    justified, over denominators nobody has defined, is not a number this
    project is entitled to publish yet (docs/adr/0003, docs/adr/0021).

``DecisionDerivationFinalizationMarker``
    Written last, after every other file has been re-read and re-verified.
    Without it there is no ``DECISION_READY``, however complete the directory
    looks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from fpbench.core.identifiers import validate_id
from fpbench.core.serialization import stable_hash, to_plain

__all__ = [
    "DecisionDerivationReceipt",
    "DecisionDerivationFinalizationMarker",
    "DecisionDerivationState",
    "DerivationDefinition",
    "derivation_definition_fingerprint",
    "derivation_receipt_fingerprint",
    "derivation_receipt_content_hash",
    "derivation_finalization_fingerprint",
    "require_sanitised_derivation",
    "DERIVATION_RECEIPT_SCHEMA_VERSION",
    "DERIVATION_FINALIZATION_SCHEMA_VERSION",
    "NO_METRIC_STATEMENT",
]

DERIVATION_RECEIPT_SCHEMA_VERSION = "1"
DERIVATION_FINALIZATION_SCHEMA_VERSION = "1"

#: Printed verbatim into every derivation receipt. Somebody will eventually read
#: only this file, and it has to be impossible to mistake for a measurement.
NO_METRIC_STATEMENT = (
    "This receipt proves deterministic decision and eligibility derivation. "
    "It contains no biometric performance metric or conclusion."
)

_HEX = frozenset("0123456789abcdef")
_PATH_LIKE = re.compile(r"(^[A-Za-z]:[\\/])|(^\\\\)|(^/)|(\\)")

#: Keys that would turn a provenance record into a results table. Checked over
#: the rendered document rather than field by field, so a field added later is
#: covered without anyone remembering to extend a list.
_FORBIDDEN_KEYS = frozenset(
    {
        "raw_score",
        "raw_scores",
        "score",
        "scores",
        "threshold",
        "match_count",
        "matched",
        "non_match_count",
        "eligible_count",
        "ineligible_count",
        "undetermined_count",
        "included_count",
        "excluded_count",
        "subject_id",
        "subject_ids",
        "image_id",
        "image_ids",
        "filename",
        "filenames",
        "dataset_root",
        "workspace",
        "fmr",
        "fnmr",
        "eer",
        "accuracy",
        "roc",
        "det",
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


def _freeze_counts(value: Mapping[str, int], field_name: str) -> Mapping[str, int]:
    from types import MappingProxyType

    counts: dict[str, int] = {}
    for key, count in dict(value).items():
        number = int(count)
        if number < 0:
            raise ValueError(f"{field_name}[{key}] must not be negative")
        counts[str(key)] = number
    return MappingProxyType(dict(sorted(counts.items())))


def require_sanitised_derivation(receipt: "DecisionDerivationReceipt") -> None:
    """Refuse a receipt carrying anything a public derivation record must not.

    Mechanical, and therefore only as good as the list — but the mistakes it
    catches are exactly the ones that are easy to make and hard to notice: a
    path, a subject id, an outcome count that crept in as "just context".
    """
    _walk(to_plain(receipt), path="receipt")


def _walk(value: Any, *, path: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).lower() in _FORBIDDEN_KEYS:
                raise ValueError(
                    f"{path}.{key} must not appear in a derivation receipt"
                )
            _walk(item, path=f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _walk(item, path=f"{path}[{index}]")
        return
    if isinstance(value, str) and _PATH_LIKE.search(value):
        raise ValueError(f"{path} looks like a filesystem path: {value!r}")


# ------------------------------------------------------------------ receipt


@dataclass(frozen=True, slots=True)
class DecisionDerivationReceipt:
    """The committable proof that decisions were derived deterministically."""

    schema_version: str

    run_id: str
    run_fingerprint: str

    result_set_id: str
    result_set_fingerprint: str
    pair_manifest_hash: str

    decision_profile_id: str
    decision_profile_fingerprint: str

    decision_set_id: str
    decision_set_fingerprint: str

    eligibility_set_id: str
    eligibility_set_fingerprint: str

    unconditional_view_id: str
    unconditional_view_fingerprint: str
    conditional_view_id: str
    conditional_view_fingerprint: str
    non_mated_view_id: str
    non_mated_view_fingerprint: str

    derivation_source_commit: str
    derivation_source_tree_clean: bool

    total_decisions: int
    decided_count: int
    undecidable_count: int
    total_eligibility_units: int

    view_total_rows: Mapping[str, int] = field(default_factory=dict)

    statement: str = NO_METRIC_STATEMENT
    created_utc: str = ""

    def __post_init__(self) -> None:
        for name in (
            "run_id",
            "result_set_id",
            "decision_profile_id",
            "decision_set_id",
            "eligibility_set_id",
            "unconditional_view_id",
            "conditional_view_id",
            "non_mated_view_id",
        ):
            validate_id(str(getattr(self, name)))
        for name in (
            "run_fingerprint",
            "result_set_fingerprint",
            "pair_manifest_hash",
            "decision_profile_fingerprint",
            "decision_set_fingerprint",
            "eligibility_set_fingerprint",
            "unconditional_view_fingerprint",
            "conditional_view_fingerprint",
            "non_mated_view_fingerprint",
        ):
            object.__setattr__(self, name, _require_digest(getattr(self, name), name))

        object.__setattr__(
            self,
            "derivation_source_commit",
            _require_commit(self.derivation_source_commit, "derivation_source_commit"),
        )
        if not self.derivation_source_tree_clean:
            raise ValueError(
                "a derivation receipt cannot describe an uncommitted working tree "
                "(docs/adr/0017)"
            )

        for name in (
            "total_decisions",
            "decided_count",
            "undecidable_count",
            "total_eligibility_units",
        ):
            number = int(getattr(self, name))
            if number < 0:
                raise ValueError(f"{name} must not be negative")
            object.__setattr__(self, name, number)
        if self.decided_count + self.undecidable_count != self.total_decisions:
            raise ValueError(
                "every decision is either decided or undecidable: "
                f"{self.decided_count} + {self.undecidable_count} != "
                f"{self.total_decisions}"
            )

        object.__setattr__(
            self, "view_total_rows", _freeze_counts(self.view_total_rows, "view_total_rows")
        )
        if len(self.view_total_rows) != 3:
            raise ValueError(
                "a derivation covers exactly three evaluation views; got "
                f"{sorted(self.view_total_rows)}"
            )

        version = str(self.schema_version).strip()
        if not version:
            raise ValueError("schema_version must not be empty")
        object.__setattr__(self, "schema_version", version)

        if str(self.statement).strip() != NO_METRIC_STATEMENT:
            raise ValueError(
                "a derivation receipt states, verbatim, that it carries no metric"
            )
        created = str(self.created_utc).strip()
        if not created:
            raise ValueError("created_utc must not be empty")
        object.__setattr__(self, "created_utc", created)

        require_sanitised_derivation(self)


def derivation_receipt_fingerprint(receipt: DecisionDerivationReceipt) -> str:
    """A digest of the receipt's durable claims, excluding when it was written."""
    plain = dict(to_plain(receipt))
    plain.pop("created_utc", None)
    return stable_hash(
        {
            "schema": f"derivation_receipt_v{DERIVATION_RECEIPT_SCHEMA_VERSION}",
            "receipt": plain,
        },
        length=64,
    )


def derivation_receipt_content_hash(receipt: DecisionDerivationReceipt) -> str:
    """Digest every byte-significant field, timestamp included.

    The semantic fingerprint deliberately ignores ``created_utc`` so that the
    same derivation recognises itself across reruns. Finalization needs the
    stronger identity: once the marker is published, even the timestamp is
    frozen.
    """
    return stable_hash(
        {"schema": "derivation_receipt_content_v1", "receipt": to_plain(receipt)},
        length=64,
    )


# ------------------------------------------------------------------- marker


@dataclass(frozen=True, slots=True)
class DecisionDerivationFinalizationMarker:
    """The last-written authority over a verified derivation chain."""

    schema_version: str
    finalization_id: str
    finalization_fingerprint: str

    run_id: str
    source_result_set_fingerprint: str
    decision_profile_fingerprint: str
    decision_set_fingerprint: str
    eligibility_set_fingerprint: str

    unconditional_view_fingerprint: str
    conditional_view_fingerprint: str
    non_mated_view_fingerprint: str

    derivation_receipt_fingerprint: str
    derivation_receipt_content_hash: str

    derivation_source_commit: str
    derivation_source_tree_clean: bool

    created_utc: str

    def __post_init__(self) -> None:
        validate_id(self.finalization_id)
        validate_id(self.run_id)
        for name in (
            "finalization_fingerprint",
            "source_result_set_fingerprint",
            "decision_profile_fingerprint",
            "decision_set_fingerprint",
            "eligibility_set_fingerprint",
            "unconditional_view_fingerprint",
            "conditional_view_fingerprint",
            "non_mated_view_fingerprint",
            "derivation_receipt_fingerprint",
            "derivation_receipt_content_hash",
        ):
            object.__setattr__(self, name, _require_digest(getattr(self, name), name))

        object.__setattr__(
            self,
            "derivation_source_commit",
            _require_commit(self.derivation_source_commit, "derivation_source_commit"),
        )
        if not self.derivation_source_tree_clean:
            raise ValueError(
                "derivation finalization requires a clean derivation tree"
            )

        version = str(self.schema_version).strip()
        if version != DERIVATION_FINALIZATION_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported derivation finalization schema version {version!r}"
            )
        object.__setattr__(self, "schema_version", version)
        created = str(self.created_utc).strip()
        if not created:
            raise ValueError("created_utc must not be empty")
        object.__setattr__(self, "created_utc", created)

        expected = derivation_finalization_fingerprint(self)
        if self.finalization_fingerprint != expected:
            raise ValueError(
                "finalization_fingerprint does not cover the marker's claims"
            )
        expected_id = f"derivationfinal_{expected[:12]}"
        if self.finalization_id != expected_id:
            raise ValueError(
                f"finalization_id must be {expected_id!r}, got "
                f"{self.finalization_id!r}"
            )


def derivation_finalization_fingerprint(
    marker: DecisionDerivationFinalizationMarker | Mapping[str, Any],
) -> str:
    """Derive a marker's identity from its claims, without its own identity."""
    plain = dict(to_plain(marker))
    plain.pop("finalization_id", None)
    plain.pop("finalization_fingerprint", None)
    plain.pop("created_utc", None)
    return stable_hash(
        {"schema": "derivation_finalization_v1", "marker": plain}, length=64
    )


# --------------------------------------------------------------- definition


@dataclass(frozen=True, slots=True)
class DerivationDefinition:
    """What a derivation is *going* to be, fixed before it is carried out.

    Written by ``prepare``, before a single decision exists. It cannot name the
    decision set — that identity depends on the decisions themselves — but it
    can and does pin everything the decisions will be derived *from*: one run,
    one result set, one profile.

    That separation is what makes ``prepare`` worth having as its own command.
    A profile that does not apply to this run, a run that is not research-ready,
    a dirty working tree: all of it fails here, before any work is done and
    before anything is written that would have to be reconciled later.
    """

    definition_id: str
    definition_fingerprint: str

    run_id: str
    run_fingerprint: str

    result_set_id: str
    result_set_fingerprint: str

    decision_profile_id: str
    decision_profile_fingerprint: str

    derivation_source_commit: str
    created_utc: str

    def __post_init__(self) -> None:
        for name in (
            "definition_id",
            "run_id",
            "result_set_id",
            "decision_profile_id",
        ):
            validate_id(str(getattr(self, name)))
        for name in (
            "definition_fingerprint",
            "run_fingerprint",
            "result_set_fingerprint",
            "decision_profile_fingerprint",
        ):
            object.__setattr__(self, name, _require_digest(getattr(self, name), name))
        object.__setattr__(
            self,
            "derivation_source_commit",
            _require_commit(self.derivation_source_commit, "derivation_source_commit"),
        )
        created = str(self.created_utc).strip()
        if not created:
            raise ValueError("created_utc must not be empty")
        object.__setattr__(self, "created_utc", created)

        expected = derivation_definition_fingerprint(self)
        if self.definition_fingerprint != expected:
            raise ValueError(
                "definition_fingerprint does not cover the definition's claims"
            )
        expected_id = f"derivation_{expected[:12]}"
        if self.definition_id != expected_id:
            raise ValueError(
                f"definition_id must be {expected_id!r}, got {self.definition_id!r}"
            )


def derivation_definition_fingerprint(
    definition: DerivationDefinition | Mapping[str, Any],
) -> str:
    """A definition's identity, excluding its own identity and its timestamp.

    The source commit is *inside* it: two derivations of the same scores under
    the same threshold by different code are different derivations, and that has
    to be true from the first command rather than only at the end
    (docs/adr/0017).
    """
    plain = dict(to_plain(definition))
    plain.pop("definition_id", None)
    plain.pop("definition_fingerprint", None)
    plain.pop("created_utc", None)
    return stable_hash({"schema": "derivation_definition_v1", "definition": plain}, length=64)


# -------------------------------------------------------------------- state


@dataclass(frozen=True, slots=True)
class DecisionDerivationState:
    """How much of a derivation's evidence chain is currently in place.

    Derived, never stored as authority. Every field is recomputed from the files
    each time it is asked for, and every ``*_valid`` flag means "re-derived and
    agreed", not "the file exists" (docs/adr/0012).
    """

    run_id: str
    decision_set_id: str | None

    status: "Any"  # DecisionDerivationStatus; avoids an enums import cycle

    definition_present: bool
    source_research_ready: bool

    profile_present: bool
    profile_valid: bool

    decision_set_present: bool
    decision_set_valid: bool

    eligibility_present: bool
    eligibility_valid: bool

    views_present: int
    views_valid: int

    receipt_present: bool
    receipt_valid: bool

    finalization_present: bool
    finalization_valid: bool

    total_decisions: int = 0
    decided_count: int = 0
    undecidable_count: int = 0
    total_eligibility_units: int = 0

    issues: tuple[str, ...] = ()
    inspected_utc: str = ""

    def __post_init__(self) -> None:
        validate_id(self.run_id)
        if self.decision_set_id is not None:
            validate_id(self.decision_set_id)
        object.__setattr__(self, "issues", tuple(str(item) for item in self.issues))

    @property
    def is_decision_ready(self) -> bool:
        from fpbench.core.enums import DecisionDerivationStatus

        return self.status is DecisionDerivationStatus.DECISION_READY
