"""Which comparisons belong to which evaluation, and why.

A view is not a metric. It is a named, fingerprinted list of comparisons
together with the reason each one is in or out — the thing a metric will later
be computed *over*, written down separately so that the choice of denominator is
reviewable before any number depends on it.

That separation is the point. "SourceAFIS matched 94% of mated pairs" is three
decisions in a trench coat: which pairs counted, what counted as a match, and
what happened to the ones that failed. Stage 5A fixes the first two and writes
them down; the third and the arithmetic come later.

Three views exist, and the differences between them are all about inclusion:

``plain_roll_mated_unconditional_v1``
    Every mated PLAIN–ROLL comparison. Nothing is excluded, not even a failed
    one — a comparison that produced no score is still part of the experiment,
    and deciding how to count it is a metric question.

``plain_roll_mated_both_self_match_v1``
    The same 1,500 rows, with ``included`` set only where the finger passed both
    SELF tests. The excluded rows stay in the file: deleting them would make the
    inclusion rule unauditable, and "why is this pair missing?" is exactly the
    question a reviewer will ask (docs/adr/0024).

``plain_roll_non_mated_same_subject_cyclic_v1``
    The impostor sanity check. It records what it is — a closed set of
    same-subject, different-finger pairs at a fixed cyclic shift — and, more
    importantly, what it is not: a false-match-rate experiment
    (docs/adr/0025).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Mapping

from fpbench.core.enums import (
    DecisionApplicationStatus,
    DecisionValue,
    SelfEligibilityStatus,
)
from fpbench.core.errors import EvaluationViewIntegrityError
from fpbench.core.identifiers import validate_id
from fpbench.core.serialization import freeze_str_mapping, stable_hash

__all__ = [
    "EvaluationViewEntry",
    "EvaluationViewManifest",
    "ExclusionReason",
    "evaluation_entry_hash",
    "ordered_entries_hash",
    "evaluation_view_fingerprint",
    "evaluation_view_id",
    "EVALUATION_VIEW_SCHEMA_VERSION",
    "VIEW_ID_LENGTH",
    "MATED_UNCONDITIONAL_VIEW",
    "MATED_CONDITIONAL_VIEW",
    "NON_MATED_SANITY_VIEW",
    "FORBIDDEN_VIEW_TOKENS",
]

EVALUATION_VIEW_SCHEMA_VERSION = "1"
VIEW_ID_LENGTH = 12

MATED_UNCONDITIONAL_VIEW = "plain_roll_mated_unconditional_v1"
MATED_CONDITIONAL_VIEW = "plain_roll_mated_both_self_match_v1"
NON_MATED_SANITY_VIEW = "plain_roll_non_mated_same_subject_cyclic_v1"

#: Words a view may not call itself. The impostor set here is closed,
#: same-subject and cyclically paired; a name containing any of these would
#: claim a population estimate the design cannot support, and names travel
#: further than caveats (docs/adr/0025).
FORBIDDEN_VIEW_TOKENS: frozenset[str] = frozenset(
    {"fmr", "fnmr", "eer", "impostor_rate", "population", "general_fmr", "accuracy"}
)

_HEX = frozenset("0123456789abcdef")
_TOKEN = re.compile(r"[a-z0-9]+")


class ExclusionReason:
    """Why a row is present but not counted.

    A tiny closed vocabulary rather than free text, so that a reviewer can group
    exclusions and a typo cannot invent a new category.
    """

    SELF_INELIGIBLE = "self_ineligible"
    SELF_UNDETERMINED = "self_undetermined"
    NO_ELIGIBILITY_UNIT = "no_eligibility_unit"

    ALL: frozenset[str] = frozenset(
        {SELF_INELIGIBLE, SELF_UNDETERMINED, NO_ELIGIBILITY_UNIT}
    )


def _require_digest(value: str, field_name: str) -> str:
    digest = str(value).strip().lower()
    if len(digest) != 64 or not set(digest) <= _HEX:
        raise ValueError(f"{field_name} must be a 64-character hexadecimal digest")
    return digest


def require_honest_view_name(name: str) -> str:
    """Refuse a view name that claims more than the design supports."""
    tokens = set(_TOKEN.findall(name.lower()))
    offending = tokens & FORBIDDEN_VIEW_TOKENS
    if offending:
        raise EvaluationViewIntegrityError(
            f"a view may not be named {name!r}: {sorted(offending)} would claim a "
            "performance measure this stage does not compute (docs/adr/0025)"
        )
    return name


@dataclass(frozen=True, slots=True)
class EvaluationViewEntry:
    """One comparison's membership of one view."""

    ordinal: int

    pair_id: str
    job_id: str

    source_result_hash: str
    decision_record_hash: str

    decision_status: DecisionApplicationStatus
    decision: DecisionValue | None

    eligibility_unit_id: str | None
    eligibility_record_hash: str | None
    eligibility_status: SelfEligibilityStatus | None

    included: bool
    exclusion_reason: str | None

    evaluation_entry_hash: str

    def __post_init__(self) -> None:
        validate_id(self.job_id)
        if int(self.ordinal) < 0:
            raise ValueError("ordinal is 0-based and must not be negative")
        object.__setattr__(self, "ordinal", int(self.ordinal))
        pair_id = str(self.pair_id).strip()
        if not pair_id:
            raise ValueError("pair_id must not be empty")
        object.__setattr__(self, "pair_id", pair_id)

        for name in ("source_result_hash", "decision_record_hash"):
            object.__setattr__(self, name, _require_digest(getattr(self, name), name))
        if self.eligibility_record_hash is not None:
            object.__setattr__(
                self,
                "eligibility_record_hash",
                _require_digest(
                    self.eligibility_record_hash, "eligibility_record_hash"
                ),
            )
        if self.eligibility_unit_id is not None:
            validate_id(self.eligibility_unit_id)

        object.__setattr__(self, "included", bool(self.included))
        reason = self.exclusion_reason
        if self.included:
            if reason is not None:
                raise ValueError(
                    "an included entry has no exclusion reason to give"
                )
        else:
            if not reason:
                raise ValueError(
                    "an excluded entry must say why; an unexplained exclusion is an "
                    "unauditable denominator"
                )
            if reason not in ExclusionReason.ALL:
                raise ValueError(
                    f"exclusion reason {reason!r} is not one of "
                    f"{sorted(ExclusionReason.ALL)}"
                )

        # A decision that could not be made is still a row; it just carries no
        # decision. The invariant mirrors DecisionRecord one layer down.
        if self.decision_status is DecisionApplicationStatus.DECIDED:
            if self.decision is None:
                raise ValueError("a decided entry must carry its decision")
        elif self.decision is not None:
            raise ValueError(
                "an undecidable entry must not carry a decision (docs/adr/0006)"
            )

        recomputed = evaluation_entry_hash(self)
        if self.evaluation_entry_hash != recomputed:
            raise ValueError("evaluation_entry_hash does not cover this entry")


def evaluation_entry_hash(entry: EvaluationViewEntry) -> str:
    """A digest of one membership decision, excluding its own hash field."""
    return stable_hash(
        {
            "schema": "evaluation_view_entry_v1",
            "ordinal": entry.ordinal,
            "pair_id": entry.pair_id,
            "job_id": entry.job_id,
            "source_result_hash": entry.source_result_hash,
            "decision_record_hash": entry.decision_record_hash,
            "decision_status": entry.decision_status.value,
            "decision": entry.decision.value if entry.decision else None,
            "eligibility_unit_id": entry.eligibility_unit_id,
            "eligibility_record_hash": entry.eligibility_record_hash,
            "eligibility_status": (
                entry.eligibility_status.value if entry.eligibility_status else None
            ),
            "included": entry.included,
            "exclusion_reason": entry.exclusion_reason,
        },
        length=64,
    )


def ordered_entries_hash(entries: Iterable[EvaluationViewEntry]) -> str:
    return stable_hash(
        {
            "schema": "evaluation_view_ordered_v1",
            "entries": [
                {
                    "ordinal": entry.ordinal,
                    "pair_id": entry.pair_id,
                    "evaluation_entry_hash": entry.evaluation_entry_hash,
                }
                for entry in entries
            ],
        },
        length=64,
    )


def evaluation_view_fingerprint(
    *,
    view_kind: str,
    policy_id: str,
    policy_version: str,
    run_fingerprint: str,
    result_set_fingerprint: str,
    decision_set_fingerprint: str,
    eligibility_set_fingerprint: str | None,
    pair_manifest_hash: str,
    policy_metadata: Mapping[str, str],
    entries: Iterable[EvaluationViewEntry],
) -> str:
    """The digest behind ``view_id``.

    Covers the inclusion state and the exclusion reasons, not just the rows: two
    views over the same pairs that include different subsets are different
    views, and that is the whole distinction between the unconditional and
    conditional mated views.
    """
    ordered = list(entries)
    return stable_hash(
        {
            "schema": "evaluation_view_fingerprint_v1",
            "evaluation_view_schema_version": EVALUATION_VIEW_SCHEMA_VERSION,
            "view_kind": view_kind,
            "policy_id": policy_id,
            "policy_version": policy_version,
            "run_fingerprint": run_fingerprint,
            "result_set_fingerprint": result_set_fingerprint,
            "decision_set_fingerprint": decision_set_fingerprint,
            "eligibility_set_fingerprint": eligibility_set_fingerprint,
            "pair_manifest_hash": pair_manifest_hash,
            "policy_metadata": dict(sorted(dict(policy_metadata).items())),
            "entries": [
                {
                    "ordinal": entry.ordinal,
                    "pair_id": entry.pair_id,
                    "included": entry.included,
                    "exclusion_reason": entry.exclusion_reason,
                    "evaluation_entry_hash": entry.evaluation_entry_hash,
                }
                for entry in ordered
            ],
            "total_rows": len(ordered),
        },
        length=64,
    )


def evaluation_view_id(view_kind: str, fingerprint: str) -> str:
    """``view_<kind>_<12 chars>``, honest name enforced."""
    require_honest_view_name(view_kind)
    digest = _require_digest(fingerprint, "view_fingerprint")
    return validate_id(f"view_{view_kind}_{digest[:VIEW_ID_LENGTH]}")


@dataclass(frozen=True, slots=True)
class EvaluationViewManifest:
    """The identity of one immutable evaluation view.

    ``total_rows`` and nothing else about the contents. The number of *included*
    rows is a result — in the conditional view it is precisely the interesting
    result — and it stays in the workspace rather than in any identity or public
    artefact (docs/adr/0024).
    """

    view_id: str
    view_fingerprint: str

    view_kind: str
    policy_id: str
    policy_version: str

    run_fingerprint: str
    result_set_fingerprint: str
    decision_set_fingerprint: str
    eligibility_set_fingerprint: str | None
    pair_manifest_hash: str

    total_rows: int
    ordered_entries_hash: str

    policy_metadata: Mapping[str, str] = field(default_factory=dict)
    created_utc: str = ""

    def __post_init__(self) -> None:
        validate_id(self.view_id)
        validate_id(self.view_kind)
        validate_id(self.policy_id)
        require_honest_view_name(self.view_kind)
        require_honest_view_name(self.policy_id)

        for name in (
            "view_fingerprint",
            "run_fingerprint",
            "result_set_fingerprint",
            "decision_set_fingerprint",
            "pair_manifest_hash",
            "ordered_entries_hash",
        ):
            object.__setattr__(self, name, _require_digest(getattr(self, name), name))
        if self.eligibility_set_fingerprint is not None:
            object.__setattr__(
                self,
                "eligibility_set_fingerprint",
                _require_digest(
                    self.eligibility_set_fingerprint, "eligibility_set_fingerprint"
                ),
            )

        total = int(self.total_rows)
        if total <= 0:
            raise ValueError("an evaluation view with no rows is not a view")
        object.__setattr__(self, "total_rows", total)

        version = str(self.policy_version).strip()
        if not version:
            raise ValueError("policy_version must not be empty")
        object.__setattr__(self, "policy_version", version)

        object.__setattr__(
            self, "policy_metadata", freeze_str_mapping(self.policy_metadata)
        )
        created = str(self.created_utc).strip()
        if not created:
            raise ValueError("created_utc must not be empty")
        object.__setattr__(self, "created_utc", created)

        expected = evaluation_view_id(self.view_kind, self.view_fingerprint)
        if self.view_id != expected:
            raise ValueError(
                f"view_id must be derived from the fingerprint: expected {expected}, "
                f"got {self.view_id!r}"
            )
