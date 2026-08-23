"""The one count Stage 19A/19B may publish for a canonical raw run.

The resumable Stage 19 runners store one JSON object per comparison in
``pair-outcomes.jsonl``.  Diagnostics are derived from that file, but they are a
report rather than the store itself.  Finalization therefore reads both and
requires every independent description of the run's cardinality to agree.

In particular, no caller supplies ``stored`` or ``missing``.  A command-line
number is a claim about the result store, not evidence from it.

**Counting is not enough, and this module used to stop at counting.** Six
thousand rows with unique ``pair_id`` values, ordinals 0..5,999 and matching
diagnostics satisfied every check here — whatever those pair ids actually were.
A store of rows reading ``fabricated_0000`` upward published
``CANONICAL_RAW_COMPLETE`` and ``algorithm_5_established: true``.  The
cardinality was real; the run it described was not.

So a store is now checked against the *authoritative pair manifest*: the
``pairs.parquet`` the cohort published, which is the same artifact the other
four algorithms' runs consumed.  Row *n* must be the manifest's row *n*, on
every field that says which comparison it is — pair id, release, protocol
stage, ground truth, and both image ids — and must name the algorithm the
stage is publishing.  The manifest hash the binding declares is derived from
that artifact rather than written down beside it.

The manifest itself is loaded by
:mod:`fpbench.experiments.stage19_pair_manifest`, which keeps parquet out of
this module: everything here is standard library, so the rules can be read
without knowing how a manifest is stored.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Collection, Mapping, Sequence

__all__ = [
    "OutcomeShape",
    "ReasonRule",
    "ScoreContract",
    "failure_reason_from_details",
    "Stage19ResultIntegrityError",
    "CanonicalPair",
    "OutcomeStoreIntegrity",
    "bound_manifest_digest",
    "canonical_source_sha256",
    "verify_outcome_store_integrity",
]

#: The statuses a Stage 19 row may carry that mean "this comparison produced a
#: score". Everything else is a failure and must carry no score at all — the
#: distinction ADR 0006 exists to keep, checked here against the stored bytes
#: rather than trusted from the diagnostics.
#: Kept for readers of published documents: every route's scoring status is
#: ``OK``. The *authority* is each route's own ``OUTCOME_CONTRACT``, which says
#: so and says what the score must be; this is a name, not a second answer.
SCORE_BEARING_STATUSES: frozenset[str] = frozenset({"OK"})


class Stage19ResultIntegrityError(RuntimeError):
    """The outcome store and the diagnostic report do not describe one run."""


@dataclass(frozen=True, slots=True)
class CanonicalPair:
    """One row of the authoritative pair manifest, in protocol order.

    Deliberately not the protocol's own ``ComparisonPair``: this is the subset a
    stored outcome can be checked against, spelled the way the outcome spells
    it, so the comparison below is a field-for-field equality and not a
    translation nobody re-reads.
    """

    ordinal: int
    pair_id: str
    release: str
    protocol_stage: str
    ground_truth: str
    left_image_id: str
    right_image_id: str

    def as_claims(self) -> dict[str, Any]:
        return {
            "ordinal": self.ordinal,
            "pair_id": self.pair_id,
            "release": self.release,
            "protocol_stage": self.protocol_stage,
            "ground_truth": self.ground_truth,
            "left_image_id": self.left_image_id,
            "right_image_id": self.right_image_id,
        }


@dataclass(frozen=True, slots=True)
class OutcomeStoreIntegrity:
    """Counts derived from the outcome store, after equality was proved."""

    expected_outcomes: int
    stored_outcomes: int
    unique_pair_ids: int
    unique_ordinals: int
    diagnostic_comparisons: int
    missing: int
    outcome_store_sha256: str

    #: The hash the pair manifest artifact carries, re-derived from its own rows
    #: by the loader rather than taken from a constant.
    pair_manifest_hash: str
    #: A digest over the exact manifest rows this store was checked against. Two
    #: runs that agree on this were bound to the same comparisons in the same
    #: order, whatever else differs.
    bound_manifest_digest: str
    #: How many rows carried a score, counted from the store.
    score_bearing: int

    #: ``status -> count``, counted from the store.
    outcome_counts: Mapping[str, int]
    #: ``failure_reason -> count`` over the rows that did not produce a score,
    #: counted from the store. This is the field Stage 19B's fourth condition
    #: reads, and the one a diagnostics document was previously free to invent.
    #: Every failing row contributes: a row with no reason is refused outright,
    #: so this total always equals ``stored_outcomes - score_bearing``.
    failure_reasons: Mapping[str, int]
    #: The subset of the above the route does not recognise. A free-text bridge
    #: detail lands here, and so does anything a stage has never classified.
    #: The rows are real and the store is honest; what may not happen is a
    #: stage publishing itself complete over failures nobody has named.
    unclassified_failure_reasons: Mapping[str, int]
    #: One row per protocol stage: how many comparisons it holds and how many
    #: of them scored. The score statistics stay with the diagnostics — a
    #: histogram is a description — but the populations a conclusion divides by
    #: are counted here.
    by_protocol_stage: tuple[Mapping[str, Any], ...]

    @property
    def score_bearing_fraction(self) -> float:
        """Score coverage, from the store's own counts."""
        return self.score_bearing / self.expected_outcomes if self.expected_outcomes else 0.0

    @property
    def unclassified_failures(self) -> int:
        """How many failing rows carry a reason the route does not recognise."""
        return sum(self.unclassified_failure_reasons.values())

    def capacity_failures(self, reason: str) -> int:
        """How many rows failed for ``reason``. Zero is an answer, not a default."""
        return int(self.failure_reasons.get(reason, 0))

    def describe(self) -> dict[str, int | str]:
        return {
            "expected_outcomes": self.expected_outcomes,
            "stored_outcomes": self.stored_outcomes,
            "unique_pair_ids": self.unique_pair_ids,
            "unique_ordinals": self.unique_ordinals,
            "diagnostic_comparisons": self.diagnostic_comparisons,
            "missing": self.missing,
            "outcome_store_sha256": self.outcome_store_sha256,
            "pair_manifest_hash": self.pair_manifest_hash,
            "bound_manifest_digest": self.bound_manifest_digest,
            "score_bearing_in_store": self.score_bearing,
        }


def failure_reason_from_details(
    details: Mapping[str, Any] | None, *, status: str
) -> str:
    """One reason string for any failure this project can record.

    The run scripts used to store ``details["reason"]`` and nothing else, and
    only ``template_refused_failure`` sets that key — so a mindtct exit code, an
    invalid xyt, a bridge crash and a timeout were all written as
    ``failure_reason: null``. The validator then counted them as no failure at
    all, and a run in which every comparison failed could publish "no failure of
    this kind remains".

    The keys are tried in the order a reader would: the classified reason first,
    then the kind of thing that went wrong, then the free-text detail. A failure
    that carries none of them still gets a reason naming its status, because a
    failure with no reason is the hole this closes.
    """
    payload = dict(details or {})
    for key in ("reason", "kind", "detail"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    exit_code = payload.get("exit_code")
    if exit_code is not None:
        return f"exit_code_{exit_code}"
    if payload.get("observed_score") is not None:
        return "invalid_score"
    text = str(status or "").strip().lower()
    return f"unclassified_{text}" if text else "unclassified"


@dataclass(frozen=True, slots=True)
class ScoreContract:
    """What a score has to be for this route, not merely that it is a number.

    The validator asked only for a finite number, so a stored ``OK`` row could
    carry ``-1`` — which the OpenAFIS bridge documents as its failure marker,
    never a similarity. Six thousand of them verified and published.
    """

    minimum: float
    maximum: float
    #: The bridge prints ``score_native_type\tuint8_t``, so a fraction is not a
    #: rounding artefact; it is a value that route cannot emit.
    integral: bool = False

    def refusal(self, score: object) -> str | None:
        """Why this score is impossible for this route, or ``None``."""
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            return f"raw_score is {score!r}, which is not a number"
        value = float(score)
        if not math.isfinite(value):
            return f"raw_score {score!r} is not finite"
        if self.integral and value != int(value):
            return (
                f"raw_score {score!r} is not a whole number, and this route's "
                "score is an integer"
            )
        if not self.minimum <= value <= self.maximum:
            return (
                f"raw_score {score!r} is outside this route's contract "
                f"[{self.minimum}, {self.maximum}]"
            )
        return None


@dataclass(frozen=True, slots=True)
class ReasonRule:
    """Which reasons one ``status + failure_code`` may carry.

    The pair is the unit, not the status. ``INFRASTRUCTURE_FAILURE`` is the one
    outcome whose code is chosen by the caller rather than fixed by its factory,
    so the eleven PNG rejections belong to it *under* ``input_invalid`` and
    nowhere else — a timeout never read a malformed file.
    """

    #: The reasons this pair owns. Ownership is global: a reason owned here may
    #: not appear under any other pair, whatever that pair allows.
    reasons: frozenset[str] = frozenset()
    #: A shape, for reasons the route generates rather than names —
    #: ``exit_code_2``, ``mindtct_crash_139``. Matched in full, and owned in the
    #: same way as a literal.
    pattern: str | None = None
    #: Whether a reason **nobody** owns may appear here. Closed by default: a
    #: status whose reasons are all enumerable says so by leaving this alone,
    #: and one that carries a vendor's free text — a .NET exception name, a
    #: bridge's own message — opts in explicitly. Being open is orthogonal to
    #: owning: ``MCC_TEMPLATE_REFUSAL_*`` does both.
    allow_unowned: bool = False

    def owns(self, reason: str) -> bool:
        if reason in self.reasons:
            return True
        return bool(self.pattern and re.fullmatch(self.pattern, reason))


@dataclass(frozen=True, slots=True)
class OutcomeShape:
    """What one status requires of the rest of the row it appears in.

    The four fields of an outcome were each checked on their own and never
    against each other, so a row could say ``MINDTCT_FAILED_LEFT`` — the
    extractor failed — and give ``invalid_raster_dimensions`` as the reason,
    which is a refusal only the *translation* raises. Every field individually
    legal; the row describing no event that can happen.
    """

    #: Does this status mean a score was produced? Exactly one status per route
    #: does, and it is the one that must carry no failure detail at all.
    scored: bool = False
    #: What that score has to be. Required on the scoring status.
    score: ScoreContract | None = None
    #: ``failure_code -> the reasons that pair may carry``. Empty on the scoring
    #: status, which has nothing to explain.
    codes: Mapping[str, ReasonRule] = field(default_factory=dict)


def _owners(
    contract: Mapping[str, OutcomeShape],
) -> list[tuple[str, str, ReasonRule]]:
    return [
        (status, code, rule)
        for status, shape in sorted(contract.items())
        for code, rule in sorted(shape.codes.items())
    ]


def _require_coherent_row(
    row: Mapping[str, Any],
    status: str,
    *,
    where: str,
    contract: Mapping[str, OutcomeShape],
    owners: list[tuple[str, str, "ReasonRule"]],
) -> bool:
    """The four fields must describe one event, not four legal values.

    Returns whether the row is score-bearing, so the caller counts from the
    store rather than from a report about it.
    """
    shape = contract[status]

    score = row.get("raw_score")
    code = row.get("failure_code")
    reason = row.get("failure_reason")

    if shape.scored:
        assert shape.score is not None  # the contract is checked on entry
        refusal = shape.score.refusal(score)
        if refusal is not None:
            raise Stage19ResultIntegrityError(
                f"{where}: status {status!r} means a score was produced and "
                f"{refusal}"
            )
        for field_name, value in (("failure_code", code), ("failure_reason", reason)):
            if value is not None and str(value).strip():
                raise Stage19ResultIntegrityError(
                    f"{where}: status {status!r} succeeded and the row carries "
                    f"{field_name}={value!r}. A comparison that produced a score "
                    "has nothing to explain"
                )
        return True

    if score is not None:
        raise Stage19ResultIntegrityError(
            f"{where}: status {status!r} is a failure and it carries raw_score "
            f"{score!r}. A failure recorded with a score is a non-match nobody "
            "measured (docs/adr/0006)"
        )
    if not isinstance(code, str) or not code.strip():
        raise Stage19ResultIntegrityError(
            f"{where}: status {status!r} is a failure and gives failure_code "
            f"{code!r}. Every failure names what kind of failure it was"
        )
    code = code.strip()
    rule = shape.codes.get(code)
    if rule is None:
        raise Stage19ResultIntegrityError(
            f"{where}: status {status!r} cannot carry failure_code {code!r}; "
            f"this route records it as {sorted(shape.codes)}"
        )
    if not isinstance(reason, str) or not reason.strip():
        raise Stage19ResultIntegrityError(
            f"{where}: status {status!r} produced no score and the row gives "
            f"failure_reason {reason!r}. Every failure states its cause; an "
            "unstated one is counted as no failure at all, which is how a run "
            "that scored nothing was published as having nothing left to fix"
        )
    text = reason.strip()

    if rule.owns(text):
        return False

    elsewhere = sorted(
        f"{other_status}+{other_code}"
        for other_status, other_code, other_rule in owners
        if (other_status, other_code) != (status, code) and other_rule.owns(text)
    )
    if elsewhere:
        raise Stage19ResultIntegrityError(
            f"{where}: status {status!r} with failure_code {code!r} carries "
            f"reason {text!r}, which belongs to {elsewhere}. The status and the "
            "reason describe different events, and no comparison produced both"
        )
    if not rule.allow_unowned:
        raise Stage19ResultIntegrityError(
            f"{where}: status {status!r} with failure_code {code!r} accepts only "
            f"the reasons it owns, and {text!r} is not one of "
            f"{sorted(rule.reasons) or [rule.pattern]}"
        )
    return False


def failure_reason_from_details(
    details: Mapping[str, Any] | None, *, status: str
) -> str:
    """One reason string for any failure this project can record.

    The run scripts used to store ``details["reason"]`` and nothing else, and
    only ``template_refused_failure`` sets that key — so a mindtct exit code, an
    invalid xyt, a bridge crash and a timeout were all written as
    ``failure_reason: null``. The validator then counted them as no failure at
    all, and a run in which every comparison failed could publish "no failure of
    this kind remains".

    The keys are tried in the order a reader would: the classified reason first,
    then the kind of thing that went wrong, then the free-text detail. A failure
    that carries none of them still gets a reason naming its status, because a
    failure with no reason is the hole this closes.
    """
    payload = dict(details or {})
    for key in ("reason", "kind", "detail"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    exit_code = payload.get("exit_code")
    if exit_code is not None:
        return f"exit_code_{exit_code}"
    if payload.get("observed_score") is not None:
        return "invalid_score"
    text = str(status or "").strip().lower()
    return f"unclassified_{text}" if text else "unclassified"


@dataclass(frozen=True, slots=True)
class ScoreContract:
    """What a score has to be for this route, not merely that it is a number.

    The validator asked only for a finite number, so a stored ``OK`` row could
    carry ``-1`` — which the OpenAFIS bridge documents as its failure marker,
    never a similarity. Six thousand of them verified and published.
    """

    minimum: float
    maximum: float
    #: The bridge prints ``score_native_type\tuint8_t``, so a fraction is not a
    #: rounding artefact; it is a value that route cannot emit.
    integral: bool = False

    def refusal(self, score: object) -> str | None:
        """Why this score is impossible for this route, or ``None``."""
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            return f"raw_score is {score!r}, which is not a number"
        value = float(score)
        if not math.isfinite(value):
            return f"raw_score {score!r} is not finite"
        if self.integral and value != int(value):
            return (
                f"raw_score {score!r} is not a whole number, and this route's "
                "score is an integer"
            )
        if not self.minimum <= value <= self.maximum:
            return (
                f"raw_score {score!r} is outside this route's contract "
                f"[{self.minimum}, {self.maximum}]"
            )
        return None


@dataclass(frozen=True, slots=True)
class ReasonRule:
    """Which reasons one ``status + failure_code`` may carry.

    The pair is the unit, not the status. ``INFRASTRUCTURE_FAILURE`` is the one
    outcome whose code is chosen by the caller rather than fixed by its factory,
    so the eleven PNG rejections belong to it *under* ``input_invalid`` and
    nowhere else — a timeout never read a malformed file.
    """

    #: The reasons this pair owns. Ownership is global: a reason owned here may
    #: not appear under any other pair, whatever that pair allows.
    reasons: frozenset[str] = frozenset()
    #: A shape, for reasons the route generates rather than names —
    #: ``exit_code_2``, ``mindtct_crash_139``. Matched in full, and owned in the
    #: same way as a literal.
    pattern: str | None = None
    #: Whether a reason **nobody** owns may appear here. Closed by default: a
    #: status whose reasons are all enumerable says so by leaving this alone,
    #: and one that carries a vendor's free text — a .NET exception name, a
    #: bridge's own message — opts in explicitly. Being open is orthogonal to
    #: owning: ``MCC_TEMPLATE_REFUSAL_*`` does both.
    allow_unowned: bool = False

    def owns(self, reason: str) -> bool:
        if reason in self.reasons:
            return True
        return bool(self.pattern and re.fullmatch(self.pattern, reason))


@dataclass(frozen=True, slots=True)
class OutcomeShape:
    """What one status requires of the rest of the row it appears in.

    The four fields of an outcome were each checked on their own and never
    against each other, so a row could say ``MINDTCT_FAILED_LEFT`` — the
    extractor failed — and give ``invalid_raster_dimensions`` as the reason,
    which is a refusal only the *translation* raises. Every field individually
    legal; the row describing no event that can happen.
    """

    #: Does this status mean a score was produced? Exactly one status per route
    #: does, and it is the one that must carry no failure detail at all.
    scored: bool = False
    #: What that score has to be. Required on the scoring status.
    score: ScoreContract | None = None
    #: ``failure_code -> the reasons that pair may carry``. Empty on the scoring
    #: status, which has nothing to explain.
    codes: Mapping[str, ReasonRule] = field(default_factory=dict)


def _owners(
    contract: Mapping[str, OutcomeShape],
) -> list[tuple[str, str, ReasonRule]]:
    return [
        (status, code, rule)
        for status, shape in sorted(contract.items())
        for code, rule in sorted(shape.codes.items())
    ]



def canonical_source_sha256(path: Path) -> str:
    """Hash a text source identically on LF and CRLF checkouts.

    Stage source fingerprints describe repository content, not the checkout's
    platform-specific newline materialization.  Outcome-store hashes remain
    byte-exact and deliberately do not use this helper.
    """
    payload = Path(path).read_bytes()
    canonical = payload.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(canonical).hexdigest()


def bound_manifest_digest(manifest: Sequence[CanonicalPair]) -> str:
    """A digest over the comparisons a run was bound to, in their order.

    Independent of how the manifest is stored, so a store validated here and a
    store validated somewhere else can be compared without both sides agreeing
    about parquet.
    """
    return hashlib.sha256(
        json.dumps(
            {
                "schema": "stage_19_bound_pair_manifest_v1",
                "pairs": [pair.as_claims() for pair in manifest],
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def _exact_non_negative_int(value: object, field: str) -> int:
    if type(value) is not int or value < 0:
        raise Stage19ResultIntegrityError(
            f"{field} must be a non-negative JSON integer"
        )
    return value


def _require_text(row: Mapping[str, Any], key: str, where: str) -> str:
    value = row.get(key)
    if type(value) is not str or not value.strip():
        raise Stage19ResultIntegrityError(
            f"{where}: {key} must be a non-empty string, got {value!r}"
        )
    return value.strip()


def _require_manifest(
    manifest: Sequence[CanonicalPair], expected: int
) -> tuple[CanonicalPair, ...]:
    rows = tuple(manifest)
    if not rows:
        raise Stage19ResultIntegrityError(
            "a Stage 19 store can only be verified against a pair manifest, and "
            "none was supplied. Counting rows proves cardinality, not identity"
        )
    if len(rows) != expected:
        raise Stage19ResultIntegrityError(
            f"the pair manifest holds {len(rows)} comparisons and this stage "
            f"expects {expected}"
        )
    for position, pair in enumerate(rows):
        if not isinstance(pair, CanonicalPair):
            raise Stage19ResultIntegrityError(
                "every manifest entry must be a CanonicalPair"
            )
        if pair.ordinal != position:
            raise Stage19ResultIntegrityError(
                f"the pair manifest is not in protocol order: entry {position} "
                f"carries ordinal {pair.ordinal}"
            )
    identifiers = {pair.pair_id for pair in rows}
    if len(identifiers) != len(rows):
        raise Stage19ResultIntegrityError(
            "the pair manifest names the same pair twice; it cannot be an "
            "authority for a one-result-per-pair run"
        )
    return rows


def _check_against_manifest(
    row: Mapping[str, Any],
    pair: CanonicalPair,
    *,
    where: str,
    algorithm_id: str,
) -> None:
    """Every field that says *which comparison this is*, checked one by one.

    Reported field by field rather than as a whole-row equality, because "row
    3,214 does not match the manifest" sends a reader to the wrong place when
    the real answer is "its ground truth says mated and the manifest says not".
    """
    for key, expected in (
        ("pair_id", pair.pair_id),
        ("release", pair.release),
        ("stage", pair.protocol_stage),
        ("ground_truth", pair.ground_truth),
        ("left_image_id", pair.left_image_id),
        ("right_image_id", pair.right_image_id),
    ):
        actual = _require_text(row, key, where)
        if actual != expected:
            raise Stage19ResultIntegrityError(
                f"{where}: {key} is {actual!r} and the pair manifest's "
                f"comparison {pair.ordinal} says {expected!r}. The store does "
                "not describe the canonical run"
            )

    stored_algorithm = _require_text(row, "algorithm_id", where)
    if stored_algorithm != algorithm_id:
        raise Stage19ResultIntegrityError(
            f"{where}: algorithm_id is {stored_algorithm!r} and this stage "
            f"publishes {algorithm_id!r}"
        )



def verify_outcome_store_integrity(
    outcomes_path: Path,
    diagnostics: Mapping[str, Any],
    *,
    expected_outcomes: int,
    manifest: Sequence[CanonicalPair],
    algorithm_id: str,
    pair_manifest_hash: str,
    classified_failure_reasons: Collection[str],
    outcome_contract: Mapping[str, OutcomeShape],
) -> OutcomeStoreIntegrity:
    """Prove the store *is* the canonical run, not merely the right size.

    ``manifest`` and ``algorithm_id`` are required, with no default. An optional
    manifest would be a manifest a publisher could omit, and the failure this
    function exists to stop is precisely a publisher whose rows were never
    compared to anything.

    The stronger ordinal check matters even after the counts agree: 6,000
    distinct ordinals numbered 1..6,000 are not the canonical 0..5,999 run.
    """
    expected = _exact_non_negative_int(expected_outcomes, "expected_outcomes")
    pairs = _require_manifest(manifest, expected)
    classified = frozenset(
        text.strip()
        for text in classified_failure_reasons
        if isinstance(text, str) and text.strip()
    )
    # One table, not two. Its keys are the route's whole status vocabulary —
    # the status used to decide only whether a row was score-bearing, so 6,000
    # rows of ``THIS_STATUS_DOES_NOT_EXIST`` with an agreeing diagnostics
    # document verified — and its values say what each status requires of the
    # rest of its row.
    contract = {
        str(status).strip(): shape
        for status, shape in dict(outcome_contract).items()
        if str(status).strip()
    }
    if not contract:
        raise Stage19ResultIntegrityError(
            "a store can only be verified against the outcomes its route "
            "declares; an empty contract admits every string"
        )
    scoring = sorted(status for status, shape in contract.items() if shape.scored)
    if len(scoring) != 1:
        raise Stage19ResultIntegrityError(
            "a route has exactly one status that means a score was produced; "
            f"this contract names {scoring}"
        )
    if contract[scoring[0]].score is None:
        raise Stage19ResultIntegrityError(
            f"the scoring status {scoring[0]!r} declares no score contract, so "
            "any number at all would verify — which is how -1 was published as "
            "a similarity"
        )
    owners = _owners(contract)
    allowed = frozenset(contract)
    if type(pair_manifest_hash) is not str or len(pair_manifest_hash.strip()) != 64:
        raise Stage19ResultIntegrityError(
            "pair_manifest_hash must be the manifest artifact's own 64-character "
            "digest, re-derived from its rows"
        )

    path = Path(outcomes_path)
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise Stage19ResultIntegrityError(
            f"cannot read the Stage 19 outcome store {path}: {exc}"
        ) from exc

    pair_ids: list[str] = []
    ordinals: list[int] = []
    status_counts: dict[str, int] = {}
    failure_reasons: dict[str, int] = {}
    unclassified: dict[str, int] = {}
    stage_totals: dict[str, int] = {}
    stage_scored: dict[str, int] = {}
    seen_ordinals: dict[int, int] = {}
    score_bearing = 0

    for line_number, raw_line in enumerate(payload.splitlines(), start=1):
        if not raw_line.strip():
            continue
        where = f"{path}:{line_number}"
        try:
            row = json.loads(raw_line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise Stage19ResultIntegrityError(
                f"{where}: unreadable JSON outcome ({exc})"
            ) from exc
        if not isinstance(row, dict):
            raise Stage19ResultIntegrityError(
                f"{where}: an outcome must be a JSON object"
            )

        ordinal = _exact_non_negative_int(row.get("ordinal"), f"{where}: ordinal")
        if ordinal >= expected:
            raise Stage19ResultIntegrityError(
                f"{where}: ordinal {ordinal} is outside the manifest's "
                f"0..{expected - 1}"
            )
        first_seen = seen_ordinals.get(ordinal)
        if first_seen is not None:
            raise Stage19ResultIntegrityError(
                f"{where}: ordinal {ordinal} was already stored at line "
                f"{first_seen}; a comparison has one result (docs/adr/0009)"
            )
        seen_ordinals[ordinal] = line_number

        status = _require_text(row, "status", where)
        if status not in allowed:
            raise Stage19ResultIntegrityError(
                f"{where}: status {status!r} is not one this route can produce. "
                f"The vocabulary is {sorted(allowed)}; a store using a status "
                "nobody defined is a store this stage never wrote"
            )
        _check_against_manifest(
            row, pairs[ordinal], where=where, algorithm_id=algorithm_id
        )
        scored = _require_coherent_row(
            row, status, where=where, contract=contract, owners=owners
        )
        if scored:
            score_bearing += 1

        pair_ids.append(pairs[ordinal].pair_id)
        ordinals.append(ordinal)
        status_counts[status] = status_counts.get(status, 0) + 1

        stage = pairs[ordinal].protocol_stage
        stage_totals[stage] = stage_totals.get(stage, 0) + 1
        if scored:
            stage_scored[stage] = stage_scored.get(stage, 0) + 1
        else:
            # A failure's reason is part of why the stage concluded what it
            # concluded, so it is counted here rather than read from a report.
            #
            # A row with no reason at all used to be skipped silently, which
            # made "no failure of this kind remains" true of a store in which
            # every single comparison failed and none of them said why. A
            # failure that does not state its cause is an incomplete record,
            # failure that does not state its cause is an incomplete record,
            # in the same way a failure carrying a score is — and the row
            # contract above has already refused one, so this only counts.
            reason = str(row["failure_reason"]).strip()
            failure_reasons[reason] = failure_reasons.get(reason, 0) + 1
            if reason not in classified:
                unclassified[reason] = unclassified.get(reason, 0) + 1

    stored = len(pair_ids)
    unique_pairs = len(set(pair_ids))
    unique_ordinals = len(set(ordinals))

    overall = diagnostics.get("overall")
    if not isinstance(overall, Mapping):
        raise Stage19ResultIntegrityError(
            "the diagnostic report has no overall comparison population"
        )
    diagnostic_comparisons = _exact_non_negative_int(
        overall.get("comparisons"), "diagnostics.overall.comparisons"
    )

    observed = {
        "unique pair_ids": unique_pairs,
        "unique ordinals": unique_ordinals,
        "diagnostic comparisons": diagnostic_comparisons,
        "stored outcomes": stored,
        "expected outcomes": expected,
    }
    if len(set(observed.values())) != 1:
        detail = ", ".join(f"{name}={value}" for name, value in observed.items())
        raise Stage19ResultIntegrityError(
            "Stage 19 finalization requires unique pair_ids == unique ordinals == "
            "diagnostic comparisons == stored outcomes == expected outcomes; "
            + detail
        )

    expected_ordinals = set(range(expected))
    if set(ordinals) != expected_ordinals:
        missing_ordinals = sorted(expected_ordinals - set(ordinals))
        unexpected_ordinals = sorted(set(ordinals) - expected_ordinals)
        raise Stage19ResultIntegrityError(
            "the outcome-store ordinals are not the canonical 0.."
            f"{expected - 1}: missing={missing_ordinals[:3]}, "
            f"unexpected={unexpected_ordinals[:3]}"
        )

    reported_counts = diagnostics.get("outcome_counts")
    if not isinstance(reported_counts, Mapping):
        raise Stage19ResultIntegrityError(
            "the diagnostic report has no outcome_counts mapping"
        )
    normalized_counts = {
        str(status): _exact_non_negative_int(
            count, f"diagnostics.outcome_counts[{status!r}]"
        )
        for status, count in reported_counts.items()
    }
    if normalized_counts != status_counts:
        raise Stage19ResultIntegrityError(
            "diagnostics.outcome_counts does not describe the outcome store: "
            f"diagnostics={normalized_counts}, store={status_counts}"
        )

    reported_score_bearing = overall.get("score_bearing")
    if reported_score_bearing is not None:
        reported = _exact_non_negative_int(
            reported_score_bearing, "diagnostics.overall.score_bearing"
        )
        if reported != score_bearing:
            raise Stage19ResultIntegrityError(
                f"the diagnostics report {reported} score-bearing comparisons "
                f"and the store holds {score_bearing}"
            )

    _require_diagnostics_agree(
        diagnostics,
        failure_reasons=failure_reasons,
        stage_totals=stage_totals,
        stage_scored=stage_scored,
    )

    stages = tuple(
        {
            "label": label,
            "comparisons": stage_totals[label],
            "score_bearing": stage_scored.get(label, 0),
            "score_bearing_fraction": (
                stage_scored.get(label, 0) / stage_totals[label]
                if stage_totals[label]
                else 0.0
            ),
        }
        for label in sorted(stage_totals)
    )

    return OutcomeStoreIntegrity(
        expected_outcomes=expected,
        stored_outcomes=stored,
        unique_pair_ids=unique_pairs,
        unique_ordinals=unique_ordinals,
        diagnostic_comparisons=diagnostic_comparisons,
        missing=expected - stored,
        outcome_store_sha256=hashlib.sha256(payload).hexdigest(),
        pair_manifest_hash=pair_manifest_hash.strip(),
        bound_manifest_digest=bound_manifest_digest(pairs),
        score_bearing=score_bearing,
        outcome_counts=dict(status_counts),
        failure_reasons=dict(failure_reasons),
        unclassified_failure_reasons=dict(unclassified),
        by_protocol_stage=stages,
    )


def _require_diagnostics_agree(
    diagnostics: Mapping[str, Any],
    *,
    failure_reasons: Mapping[str, int],
    stage_totals: Mapping[str, int],
    stage_scored: Mapping[str, int],
) -> None:
    """A diagnostics document may describe the store; it may not contradict it.

    Checked rather than ignored, because a publisher reads *both*: the store for
    the counts and the report for everything the counts do not carry. A report
    that disagreed about the failure reasons was believed, and the disagreement
    was the whole exploit.
    """
    reported_reasons = diagnostics.get("failure_reasons")
    if reported_reasons is not None:
        normalized = {
            str(reason): _exact_non_negative_int(
                count, f"diagnostics.failure_reasons[{reason!r}]"
            )
            for reason, count in dict(reported_reasons).items()
            if count
        }
        derived = {reason: count for reason, count in failure_reasons.items() if count}
        if normalized != derived:
            raise Stage19ResultIntegrityError(
                "diagnostics.failure_reasons does not describe the outcome store: "
                f"diagnostics={normalized}, store={derived}"
            )

    reported_stages = diagnostics.get("by_protocol_stage")
    if not reported_stages:
        return
    for row in reported_stages:
        if not isinstance(row, Mapping):
            raise Stage19ResultIntegrityError(
                "every by_protocol_stage entry must be a mapping"
            )
        label = str(row.get("label", "")).strip()
        if not label:
            raise Stage19ResultIntegrityError(
                "a by_protocol_stage entry names no protocol stage"
            )
        if label not in stage_totals:
            raise Stage19ResultIntegrityError(
                f"the diagnostics report protocol stage {label!r}, which the "
                "pair manifest does not contain"
            )
        for key, derived in (
            ("comparisons", stage_totals[label]),
            ("score_bearing", stage_scored.get(label, 0)),
        ):
            if key not in row:
                continue
            reported = _exact_non_negative_int(
                row[key], f"by_protocol_stage[{label!r}].{key}"
            )
            if reported != derived:
                raise Stage19ResultIntegrityError(
                    f"the diagnostics say protocol stage {label!r} has {key}="
                    f"{reported} and the store holds {derived}"
                )
