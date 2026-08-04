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
from fpbench.core.provenance_models import (
    SoftwareProvenance,
    software_provenance_fingerprint,
)
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
    "SourceFinalizationIdentity",
    "DERIVATION_RECEIPT_SCHEMA_VERSION",
    "DERIVATION_RECEIPT_SCHEMA_VERSIONS",
    "DERIVATION_FINALIZATION_SCHEMA_VERSION",
    "DERIVATION_FINALIZATION_SCHEMA_VERSIONS",
    "OPTIONAL_RECEIPT_FIELDS",
    "OPTIONAL_FINALIZATION_FIELDS",
    "NO_METRIC_STATEMENT",
]

#: What a receipt is when it does not say otherwise, and what the four published
#: SourceAFIS receipts are.
DERIVATION_RECEIPT_SCHEMA_VERSION = "1"
DERIVATION_FINALIZATION_SCHEMA_VERSION = "1"

#: **1** — the shape stage 5A published and stage 6B republished. Frozen.
#: **2** — additionally binds the derivation definition, the derivation software
#: identity and the source run's stage finalization marker. A schema-2 receipt
#: must carry all three; a schema-1 receipt must carry none of them, so that
#: neither can be mistaken for the other and neither can drift into the other
#: (spec sections 15, 25 and 36).
DERIVATION_RECEIPT_SCHEMA_VERSIONS: tuple[str, ...] = ("1", "2")
DERIVATION_FINALIZATION_SCHEMA_VERSIONS: tuple[str, ...] = ("1", "2")

#: Fields added to the receipt after four SourceAFIS receipts had already been
#: published, finalised and committed.
#:
#: They are hashed when a derivation has them and *removed* when it does not,
#: rather than hashed as ``null``. Hashing a null would move the digest of every
#: receipt written before the field existed, which would in turn invalidate the
#: finalization markers that cite those digests — four decision sets, four
#: eligibility sets and four metric sets, none of which changed in any way that
#: matters (spec sections 19, 25 and 82).
#:
#: The rule is deliberately narrow: it applies to this fixed list and not to
#: "any null", so a future required field cannot slip past it by being optional
#: for one caller.
OPTIONAL_RECEIPT_FIELDS: tuple[str, ...] = (
    "source_stage_finalization_kind",
    "source_stage_finalization_fingerprint",
    "derivation_definition_fingerprint",
    "derivation_software_fingerprint",
)

#: The same, for the finalization marker.
OPTIONAL_FINALIZATION_FIELDS: tuple[str, ...] = (
    "source_stage_finalization_kind",
    "source_stage_finalization_fingerprint",
)

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

    #: What made the *source run's* raw scores authoritative, when the run has a
    #: stage marker of its own beyond the general research finalization. Stage 7C
    #: wrote one for the NBIS run: it binds the alignment proof to the receipt,
    #: and a decision receipt that did not cite it would be resting on a run
    #: whose defining property — that it was given the reference run's own
    #: inputs — appears nowhere above it (spec section 36).
    source_stage_finalization_kind: str | None = None
    source_stage_finalization_fingerprint: str | None = None

    #: The derivation definition and the code that carried it out, by digest.
    #: ``derivation_source_commit`` above answers "which commit"; these answer
    #: "which pinned derivation" and "which exact software identity", which are
    #: not recoverable from a commit alone (docs/adr/0017).
    derivation_definition_fingerprint: str | None = None
    derivation_software_fingerprint: str | None = None

    def __post_init__(self) -> None:
        _normalise_stage_finalization(self)
        for name in (
            "derivation_definition_fingerprint",
            "derivation_software_fingerprint",
        ):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _require_digest(value, name))
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
        if version not in DERIVATION_RECEIPT_SCHEMA_VERSIONS:
            raise ValueError(
                f"unsupported derivation receipt schema version {version!r}"
            )
        object.__setattr__(self, "schema_version", version)
        _require_optional_fields_match_schema(
            self,
            version=version,
            names=OPTIONAL_RECEIPT_FIELDS,
            label="derivation receipt",
        )

        if str(self.statement).strip() != NO_METRIC_STATEMENT:
            raise ValueError(
                "a derivation receipt states, verbatim, that it carries no metric"
            )
        created = str(self.created_utc).strip()
        if not created:
            raise ValueError("created_utc must not be empty")
        object.__setattr__(self, "created_utc", created)

        require_sanitised_derivation(self)


def _drop_absent_optionals(
    plain: dict[str, Any], names: tuple[str, ...]
) -> dict[str, Any]:
    """Remove the post-hoc optional keys a document does not carry.

    See :data:`OPTIONAL_RECEIPT_FIELDS` for why absence is removal rather than
    ``null``: it is what keeps every artefact published before stage 7D
    fingerprinting to the identity it was published under.
    """
    for name in names:
        if plain.get(name) is None:
            plain.pop(name, None)
    return plain


def derivation_receipt_fingerprint(receipt: DecisionDerivationReceipt) -> str:
    """A digest of the receipt's durable claims, excluding when it was written."""
    plain = dict(to_plain(receipt))
    plain.pop("created_utc", None)
    return stable_hash(
        {
            # The receipt's own version, not the module's idea of the current
            # one. A schema-1 receipt hashes under the v1 tag for ever, whatever
            # this module later learns to write.
            "schema": f"derivation_receipt_v{receipt.schema_version}",
            "receipt": _drop_absent_optionals(plain, OPTIONAL_RECEIPT_FIELDS),
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
        {
            "schema": "derivation_receipt_content_v1",
            "receipt": _drop_absent_optionals(
                dict(to_plain(receipt)), OPTIONAL_RECEIPT_FIELDS
            ),
        },
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

    #: The source run's own stage marker, when it has one. See the receipt field
    #: of the same name.
    source_stage_finalization_kind: str | None = None
    source_stage_finalization_fingerprint: str | None = None

    def __post_init__(self) -> None:
        _normalise_stage_finalization(self)
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
        if version not in DERIVATION_FINALIZATION_SCHEMA_VERSIONS:
            raise ValueError(
                f"unsupported derivation finalization schema version {version!r}"
            )
        object.__setattr__(self, "schema_version", version)
        _require_optional_fields_match_schema(
            self,
            version=version,
            names=OPTIONAL_FINALIZATION_FIELDS,
            label="derivation finalization",
        )
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
        {
            "schema": "derivation_finalization_v1",
            "marker": _drop_absent_optionals(plain, OPTIONAL_FINALIZATION_FIELDS),
        },
        length=64,
    )


# ------------------------------------------------- the source's stage marker


@dataclass(frozen=True, slots=True)
class SourceFinalizationIdentity:
    """What makes one run's raw scores authoritative, named without naming it.

    Every research run has a general research finalization marker. Some runs
    additionally have a *stage* marker that binds something the general chain
    knows nothing about: the NBIS run has one, because being aligned row by row
    with the SourceAFIS run is the property that makes the two comparable at all,
    and the general chain has no field for it.

    The decision engine treats this as opaque — a kind and a digest — so that the
    next algorithm's stage marker needs no change to any engine (docs/adr/0056).
    """

    research_finalization_fingerprint: str
    stage_finalization_kind: str | None = None
    stage_finalization_fingerprint: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "research_finalization_fingerprint",
            _require_digest(
                self.research_finalization_fingerprint,
                "research_finalization_fingerprint",
            ),
        )
        kind = self.stage_finalization_kind
        fingerprint = self.stage_finalization_fingerprint
        if (kind is None) != (fingerprint is None):
            raise ValueError(
                "a stage finalization is a kind and a digest together; one without "
                "the other names a marker nobody can look up"
            )
        if kind is not None:
            kind = str(kind).strip()
            if not kind:
                raise ValueError("stage_finalization_kind must not be empty")
            object.__setattr__(self, "stage_finalization_kind", kind)
            object.__setattr__(
                self,
                "stage_finalization_fingerprint",
                _require_digest(fingerprint, "stage_finalization_fingerprint"),
            )


def _require_optional_fields_match_schema(
    document: Any, *, version: str, names: tuple[str, ...], label: str
) -> None:
    """Schema 1 carries none of the later fields; schema 2 carries all of them.

    Stated as an equality rather than a minimum so that neither shape can drift
    into the other. A schema-1 document that acquired one field would fingerprint
    like a schema-1 document and mean something else; a schema-2 document missing
    one would claim a binding it does not have.
    """
    absent = [name for name in names if getattr(document, name) is None]
    if version == "1" and absent != list(names):
        present = sorted(set(names) - set(absent))
        raise ValueError(
            f"a schema-1 {label} carries none of {list(names)}; this one carries "
            f"{present}. Those fields are what schema 2 is for"
        )
    if version != "1" and absent:
        raise ValueError(
            f"a schema-{version} {label} must bind {absent}; a receipt that names "
            "only some of what it rests on is a receipt whose reader has to guess "
            "the rest"
        )


def _normalise_stage_finalization(document: Any) -> None:
    """Validate the ``source_stage_finalization_*`` pair on a frozen document."""
    kind = document.source_stage_finalization_kind
    fingerprint = document.source_stage_finalization_fingerprint
    if (kind is None) != (fingerprint is None):
        raise ValueError(
            "source_stage_finalization_kind and "
            "source_stage_finalization_fingerprint are written together or not at "
            "all"
        )
    if kind is None:
        return
    text = str(kind).strip()
    if not text:
        raise ValueError("source_stage_finalization_kind must not be empty")
    object.__setattr__(document, "source_stage_finalization_kind", text)
    object.__setattr__(
        document,
        "source_stage_finalization_fingerprint",
        _require_digest(fingerprint, "source_stage_finalization_fingerprint"),
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

    derivation_software: SoftwareProvenance
    derivation_software_fingerprint: str
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
            "derivation_software_fingerprint",
        ):
            object.__setattr__(self, name, _require_digest(getattr(self, name), name))
        software = self.derivation_software
        if isinstance(software, Mapping):
            software = SoftwareProvenance(**software)
            object.__setattr__(self, "derivation_software", software)
        if not isinstance(software, SoftwareProvenance):
            raise ValueError("derivation_software must be SoftwareProvenance")
        if not software.is_research_grade:
            raise ValueError(
                "a derivation definition requires committed, clean software provenance"
            )
        software_fingerprint = software_provenance_fingerprint(software)
        if self.derivation_software_fingerprint != software_fingerprint:
            raise ValueError(
                "derivation_software_fingerprint does not cover derivation_software"
            )
        object.__setattr__(
            self,
            "derivation_source_commit",
            _require_commit(self.derivation_source_commit, "derivation_source_commit"),
        )
        if self.derivation_source_commit != software.source_revision:
            raise ValueError(
                "derivation_source_commit must equal the software source revision"
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
