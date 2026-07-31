"""Turning decisions, eligibility verdicts and view rows into aggregate counts.

Six tables come out of here, one per :class:`~fpbench.core.metric_models.CountFamily`,
each at every release and once pooled. They are the only thing a metric is ever
computed from: the observation layer never touches a decision record, and the
verifier re-derives both from the same functions.

Three things this module refuses to do, and each has cost somebody a paper
somewhere.

**It does not read a raw score.** Not once. The decision set proved every
decision follows from the score it cites, and that proof is re-checked before
these functions are called. Reading the scores again here would create a second
path by which a threshold could enter the metric engine, which is exactly the
path that ends in a threshold chosen to make a number look good (spec section 32).

**It does not take a release from a directory name.** Releases come from the
frozen pair manifest, or from the eligibility record, which came from the pair
manifest. A file that has been moved is still the release it always was
(spec section 29).

**It does not let a pooled value be anything but a sum.** Pooled counts are
computed by adding the release counts, and the caller cannot supply them
(docs/adr/0028).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from fpbench.core.decision_models import DecisionRecord
from fpbench.core.eligibility_models import SelfEligibilityDecisionRecord
from fpbench.core.enums import (
    DecisionApplicationStatus,
    DecisionValue,
    MetricScopeKind,
    ProtocolStage,
    SelfEligibilityStatus,
)
from fpbench.core.errors import MetricDerivationError
from fpbench.core.evaluation_view_models import (
    MATED_CONDITIONAL_VIEW,
    MATED_UNCONDITIONAL_VIEW,
    NON_MATED_SANITY_VIEW,
    EvaluationViewEntry,
    EvaluationViewManifest,
    ExclusionReason,
)
from fpbench.core.identifiers import PairId
from fpbench.core.metric_models import (
    ConditionalOutcomeCounts,
    CountFamily,
    DecisionOutcomeCounts,
    EligibilityOutcomeCounts,
    EvaluationCountRecord,
    MetricScope,
    count_record_hash,
    scope_sort_key,
)
from fpbench.core.models import ComparisonPair
from fpbench.metrics.policy import (
    NEGATIVE_SANITY_METADATA as _POLICY_NEGATIVE_SANITY_METADATA,
)

__all__ = [
    "MetricSources",
    "aggregate_count_records",
    "self_decision_counts",
    "eligibility_counts",
    "unconditional_counts",
    "conditional_counts",
    "negative_sanity_counts",
    "pooled",
    "release_order_of",
    "NEGATIVE_SANITY_METADATA",
]

#: Re-exported from :mod:`fpbench.metrics.policy`, where it is defined once and
#: reaches the metric policy's fingerprint. Named here too because this is the
#: module that counts the set it describes (spec section 45, docs/adr/0025).
NEGATIVE_SANITY_METADATA: Mapping[str, str] = _POLICY_NEGATIVE_SANITY_METADATA


@dataclass(frozen=True, slots=True)
class MetricSources:
    """Everything the metric engine is allowed to read, already verified.

    Assembled by the experiment module from a ``DECISION_READY`` chain. The
    engine takes this and nothing else — in particular no result store, so
    "read a raw score" is not an option that exists here.
    """

    decisions: tuple[DecisionRecord, ...]
    decision_set_fingerprint: str

    eligibility_records: tuple[SelfEligibilityDecisionRecord, ...]
    eligibility_set_fingerprint: str

    view_manifests: Mapping[str, EvaluationViewManifest]
    view_entries: Mapping[str, tuple[EvaluationViewEntry, ...]]

    pairs: Mapping[PairId, ComparisonPair]

    def release_of(self, pair_id: str) -> str:
        pair = self.pairs.get(pair_id)  # type: ignore[arg-type]
        if pair is None:
            raise MetricDerivationError(
                f"pair {pair_id} is not in the frozen pair manifest; a release read "
                "from anywhere else is a guess"
            )
        release = str(pair.release).strip()
        if not release:
            raise MetricDerivationError(f"pair {pair_id} declares no release")
        return release

    def stage_of(self, pair_id: str) -> ProtocolStage:
        pair = self.pairs.get(pair_id)  # type: ignore[arg-type]
        if pair is None:
            raise MetricDerivationError(
                f"pair {pair_id} is not in the frozen pair manifest"
            )
        return pair.protocol_stage

    def entries(self, view_kind: str) -> tuple[EvaluationViewEntry, ...]:
        try:
            return self.view_entries[view_kind]
        except KeyError:
            raise MetricDerivationError(
                f"the evaluation view {view_kind!r} was not supplied"
            ) from None

    def view_fingerprint(self, view_kind: str) -> str:
        try:
            return self.view_manifests[view_kind].view_fingerprint
        except KeyError:
            raise MetricDerivationError(
                f"the evaluation view {view_kind!r} was not supplied"
            ) from None


# ------------------------------------------------------------------ releases


def release_order_of(
    sources: MetricSources, *, expected_releases: Sequence[str] | None = None
) -> tuple[str, ...]:
    """The releases this evaluation covers, in a stable order.

    Sorted rather than taken from a config, so that two people evaluating the
    same run get the same order without agreeing on one. When the experiment
    declares which releases it expects, the two must match exactly: an
    unexpected release means the source chain is not the chain the experiment
    was written for (spec section 73).
    """
    observed = sorted(
        {str(record.release).strip() for record in sources.eligibility_records}
    )
    if not observed:
        raise MetricDerivationError(
            "the eligibility set names no release; there is nothing to group by"
        )
    if expected_releases is not None:
        expected = list(expected_releases)
        if len(set(expected)) != len(expected):
            raise MetricDerivationError(
                f"the experiment declares a release twice: {expected}"
            )
        if observed != sorted(expected):
            missing = sorted(set(expected) - set(observed))
            unexpected = sorted(set(observed) - set(expected))
            raise MetricDerivationError(
                f"this evaluation covers releases {observed}, but the experiment "
                f"declares {sorted(expected)}"
                + (f"; missing {missing}" if missing else "")
                + (f"; unexpected {unexpected}" if unexpected else "")
            )
        return tuple(expected)
    return tuple(observed)


# ---------------------------------------------------------------------- SELF


def self_decision_counts(
    sources: MetricSources, *, stage: ProtocolStage, releases: Sequence[str]
) -> Mapping[str, DecisionOutcomeCounts]:
    """Count one SELF stage by release, straight from the decision set.

    Deliberately taken from the decisions rather than from the eligibility
    table, and then checked *against* the eligibility table. Reading only the
    eligibility table would make the SELF counts a restatement of a derived
    artefact; reading only the decisions would leave "one PLAIN SELF per unit"
    unverified. Doing both makes a disagreement between them visible
    (spec section 41).
    """
    if stage not in (ProtocolStage.PLAIN_SELF, ProtocolStage.ROLL_SELF):
        raise MetricDerivationError(f"{stage.value!r} is not a SELF stage")

    tallies: dict[str, list[int]] = {release: [0, 0, 0] for release in releases}
    seen_jobs: dict[str, DecisionRecord] = {}

    for decision in sources.decisions:
        if sources.stage_of(decision.pair_id) is not stage:
            continue
        release = sources.release_of(decision.pair_id)
        if release not in tallies:
            raise MetricDerivationError(
                f"a {stage.value} comparison belongs to release {release!r}, which "
                f"this evaluation does not cover ({sorted(tallies)})"
            )
        seen_jobs[decision.job_id] = decision
        tally = tallies[release]
        if decision.application_status is DecisionApplicationStatus.UNDECIDABLE:
            tally[2] += 1
        elif decision.decision is DecisionValue.MATCH:
            tally[0] += 1
        else:
            tally[1] += 1

    _require_self_agrees_with_eligibility(
        sources=sources, stage=stage, decisions_by_job=seen_jobs
    )

    return {
        release: DecisionOutcomeCounts(
            total_attempts=match + non_match + undecidable,
            decided_attempts=match + non_match,
            match_count=match,
            non_match_count=non_match,
            undecidable_count=undecidable,
        )
        for release, (match, non_match, undecidable) in tallies.items()
    }


def _require_self_agrees_with_eligibility(
    *,
    sources: MetricSources,
    stage: ProtocolStage,
    decisions_by_job: Mapping[str, DecisionRecord],
) -> None:
    """One SELF decision per unit, and the same verdict on both sides."""
    is_plain = stage is ProtocolStage.PLAIN_SELF
    expected: dict[str, DecisionValue | None] = {}
    for record in sources.eligibility_records:
        job_id = (
            record.plain_self_job_id if is_plain else record.roll_self_job_id
        )
        if job_id in expected:
            raise MetricDerivationError(
                f"two eligibility units name the same {stage.value} comparison; "
                "the SELF counts would double-count it"
            )
        expected[job_id] = (
            record.plain_self_decision if is_plain else record.roll_self_decision
        )

    missing = sorted(set(expected) - set(decisions_by_job))
    if missing:
        raise MetricDerivationError(
            f"{len(missing)} eligibility unit(s) cite a {stage.value} comparison "
            f"the decision set does not hold, e.g. {missing[:3]}"
        )
    extra = sorted(set(decisions_by_job) - set(expected))
    if extra:
        raise MetricDerivationError(
            f"the decision set holds {len(extra)} {stage.value} comparison(s) that "
            f"no eligibility unit accounts for, e.g. {extra[:3]}"
        )

    for job_id, verdict in expected.items():
        decision = decisions_by_job[job_id]
        if decision.decision is not verdict:
            raise MetricDerivationError(
                f"the eligibility set records {stage.value} {job_id} as "
                f"{verdict.value if verdict else 'undecidable'}, but the decision "
                f"set says "
                f"{decision.decision.value if decision.decision else 'undecidable'}"
            )


# --------------------------------------------------------------- eligibility


def eligibility_counts(
    sources: MetricSources, *, releases: Sequence[str]
) -> Mapping[str, EligibilityOutcomeCounts]:
    """Count SELF eligibility verdicts by release, three-valued throughout."""
    tallies: dict[str, list[int]] = {release: [0, 0, 0] for release in releases}
    for record in sources.eligibility_records:
        release = str(record.release).strip()
        if release not in tallies:
            raise MetricDerivationError(
                f"an eligibility unit belongs to release {release!r}, which this "
                f"evaluation does not cover ({sorted(tallies)})"
            )
        tally = tallies[release]
        if record.status is SelfEligibilityStatus.ELIGIBLE:
            tally[0] += 1
        elif record.status is SelfEligibilityStatus.INELIGIBLE:
            tally[1] += 1
        else:
            tally[2] += 1

    return {
        release: EligibilityOutcomeCounts(
            total_units=eligible + ineligible + undetermined,
            eligible_count=eligible,
            ineligible_count=ineligible,
            undetermined_count=undetermined,
        )
        for release, (eligible, ineligible, undetermined) in tallies.items()
    }


# ------------------------------------------------------------------- genuine


def unconditional_counts(
    sources: MetricSources, *, releases: Sequence[str]
) -> Mapping[str, DecisionOutcomeCounts]:
    """Count the unconditional mated view by release.

    Every row must be included. The unconditional view is *defined* as excluding
    nothing, so an excluded row there is not a filter to respect — it is a
    contradiction between the view and its own policy (docs/adr/0024).
    """
    tallies: dict[str, list[int]] = {release: [0, 0, 0] for release in releases}
    for entry in sources.entries(MATED_UNCONDITIONAL_VIEW):
        if not entry.included:
            raise MetricDerivationError(
                f"the unconditional mated view excludes {entry.pair_id}; that view "
                "excludes nothing by definition, and eligibility must not reach it"
            )
        release = sources.release_of(entry.pair_id)
        if release not in tallies:
            raise MetricDerivationError(
                f"an unconditional mated row belongs to release {release!r}, which "
                f"this evaluation does not cover ({sorted(tallies)})"
            )
        _tally_entry(tallies[release], entry)

    return {
        release: DecisionOutcomeCounts(
            total_attempts=match + non_match + undecidable,
            decided_attempts=match + non_match,
            match_count=match,
            non_match_count=non_match,
            undecidable_count=undecidable,
        )
        for release, (match, non_match, undecidable) in tallies.items()
    }


def conditional_counts(
    sources: MetricSources, *, releases: Sequence[str]
) -> Mapping[str, ConditionalOutcomeCounts]:
    """Count the SELF-conditional mated view by release, selection included.

    Excluded rows stay in ``total_rows`` and never enter an outcome count. That
    is the shape of the whole conditional result: the selection is a number the
    reader needs, not a step that happened before the numbers started
    (docs/adr/0029).
    """
    tallies: dict[str, dict[str, int]] = {
        release: {
            "total": 0,
            "included": 0,
            "excluded_ineligible": 0,
            "excluded_undetermined": 0,
            "included_match": 0,
            "included_non_match": 0,
            "included_undecidable": 0,
        }
        for release in releases
    }

    for entry in sources.entries(MATED_CONDITIONAL_VIEW):
        release = sources.release_of(entry.pair_id)
        if release not in tallies:
            raise MetricDerivationError(
                f"a conditional mated row belongs to release {release!r}, which "
                f"this evaluation does not cover ({sorted(tallies)})"
            )
        tally = tallies[release]
        tally["total"] += 1

        if not entry.included:
            if entry.exclusion_reason == ExclusionReason.SELF_INELIGIBLE:
                tally["excluded_ineligible"] += 1
            elif entry.exclusion_reason == ExclusionReason.SELF_UNDETERMINED:
                tally["excluded_undetermined"] += 1
            else:
                raise MetricDerivationError(
                    f"conditional row {entry.pair_id} is excluded for "
                    f"{entry.exclusion_reason!r}, which the conditional policy does "
                    "not produce; an unexplained exclusion is an unauditable "
                    "denominator"
                )
            continue

        tally["included"] += 1
        if entry.decision_status is DecisionApplicationStatus.UNDECIDABLE:
            tally["included_undecidable"] += 1
        elif entry.decision is DecisionValue.MATCH:
            tally["included_match"] += 1
        else:
            tally["included_non_match"] += 1

    return {
        release: ConditionalOutcomeCounts(
            total_rows=tally["total"],
            included_count=tally["included"],
            excluded_ineligible_count=tally["excluded_ineligible"],
            excluded_undetermined_count=tally["excluded_undetermined"],
            included_decided_count=(
                tally["included_match"] + tally["included_non_match"]
            ),
            included_match_count=tally["included_match"],
            included_non_match_count=tally["included_non_match"],
            included_undecidable_count=tally["included_undecidable"],
        )
        for release, tally in tallies.items()
    }


def negative_sanity_counts(
    sources: MetricSources, *, releases: Sequence[str]
) -> Mapping[str, DecisionOutcomeCounts]:
    """Count the closed-set impostor sanity check by release.

    Every row must be included and must carry no eligibility reference. An
    impostor pair spans two fingers, so "did its finger pass SELF?" has two
    answers and no agreed rule for combining them; a sanity row that had been
    conditioned on one of them would be a metric policy nobody approved
    (docs/adr/0025).
    """
    tallies: dict[str, list[int]] = {release: [0, 0, 0] for release in releases}
    for entry in sources.entries(NON_MATED_SANITY_VIEW):
        if not entry.included:
            raise MetricDerivationError(
                f"the negative sanity view excludes {entry.pair_id}; nothing "
                "conditions this view"
            )
        if (
            entry.eligibility_unit_id is not None
            or entry.eligibility_record_hash is not None
            or entry.eligibility_status is not None
        ):
            raise MetricDerivationError(
                f"negative sanity row {entry.pair_id} carries an eligibility "
                "reference; the impostor set is never conditioned on SELF "
                "(docs/adr/0025)"
            )
        release = sources.release_of(entry.pair_id)
        if release not in tallies:
            raise MetricDerivationError(
                f"a negative sanity row belongs to release {release!r}, which this "
                f"evaluation does not cover ({sorted(tallies)})"
            )
        _tally_entry(tallies[release], entry)

    return {
        release: DecisionOutcomeCounts(
            total_attempts=match + non_match + undecidable,
            decided_attempts=match + non_match,
            match_count=match,
            non_match_count=non_match,
            undecidable_count=undecidable,
        )
        for release, (match, non_match, undecidable) in tallies.items()
    }


def _tally_entry(tally: list[int], entry: EvaluationViewEntry) -> None:
    if entry.decision_status is DecisionApplicationStatus.UNDECIDABLE:
        tally[2] += 1
    elif entry.decision is DecisionValue.MATCH:
        tally[0] += 1
    else:
        tally[1] += 1


# -------------------------------------------------------------------- pooled


def pooled(counts: Mapping[str, object]) -> object:
    """Add the release counts together. There is no other way to get a pooled value.

    The count models define ``__add__``, so this is a fold rather than a
    re-derivation, and a pooled value that disagreed with the sum of its parts
    would be arithmetically impossible rather than merely detectable
    (docs/adr/0028).
    """
    values = list(counts.values())
    if not values:
        raise MetricDerivationError("there are no release counts to pool")
    total = values[0]
    for value in values[1:]:
        total = total + value  # type: ignore[operator]
    return total


# ------------------------------------------------------------- count records


def aggregate_count_records(
    sources: MetricSources, *, releases: Sequence[str]
) -> tuple[EvaluationCountRecord, ...]:
    """Build all six families, at every release and pooled, in canonical order.

    Order is family, then release in the declared order, then pooled — and it
    enters the ordered hash, so reordering these rows without changing one of
    them is detectable (spec section 40).
    """
    releases = tuple(releases)
    by_family: dict[str, tuple[str, Mapping[str, object]]] = {
        CountFamily.PLAIN_SELF: (
            sources.decision_set_fingerprint,
            self_decision_counts(
                sources, stage=ProtocolStage.PLAIN_SELF, releases=releases
            ),
        ),
        CountFamily.ROLL_SELF: (
            sources.decision_set_fingerprint,
            self_decision_counts(
                sources, stage=ProtocolStage.ROLL_SELF, releases=releases
            ),
        ),
        CountFamily.SELF_ELIGIBILITY: (
            sources.eligibility_set_fingerprint,
            eligibility_counts(sources, releases=releases),
        ),
        CountFamily.MATED_UNCONDITIONAL: (
            sources.view_fingerprint(MATED_UNCONDITIONAL_VIEW),
            unconditional_counts(sources, releases=releases),
        ),
        CountFamily.MATED_CONDITIONAL: (
            sources.view_fingerprint(MATED_CONDITIONAL_VIEW),
            conditional_counts(sources, releases=releases),
        ),
        CountFamily.NEGATIVE_SANITY: (
            sources.view_fingerprint(NON_MATED_SANITY_VIEW),
            negative_sanity_counts(sources, releases=releases),
        ),
    }

    records: list[EvaluationCountRecord] = []
    ordinal = 0
    for family in CountFamily.ORDER:
        source_fingerprint, per_release = by_family[family]
        scoped: list[tuple[MetricScope, object]] = [
            (MetricScope(MetricScopeKind.RELEASE, release), per_release[release])
            for release in releases
        ]
        scoped.append((MetricScope(MetricScopeKind.POOLED), pooled(per_release)))

        for scope, counts in scoped:
            records.append(
                _count_record(
                    ordinal=ordinal,
                    family=family,
                    scope=scope,
                    counts=counts,
                    source_fingerprint=source_fingerprint,
                )
            )
            ordinal += 1

    _require_canonical_order(records, releases)
    return tuple(records)


def _count_record(
    *,
    ordinal: int,
    family: str,
    scope: MetricScope,
    counts: object,
    source_fingerprint: str,
) -> EvaluationCountRecord:
    if isinstance(counts, EligibilityOutcomeCounts):
        total = counts.total_units
    elif isinstance(counts, ConditionalOutcomeCounts):
        total = counts.total_rows
    elif isinstance(counts, DecisionOutcomeCounts):
        total = counts.total_attempts
    else:  # pragma: no cover - guarded by the callers above
        raise MetricDerivationError(f"{type(counts).__name__} is not a count model")

    fields = {
        "ordinal": ordinal,
        "count_family": family,
        "scope": scope,
        "total_count": total,
        "counts": counts.as_mapping(),  # type: ignore[union-attr]
        "source_fingerprint": source_fingerprint,
    }
    probe = _CountProbe(**fields)
    return EvaluationCountRecord(
        count_record_hash=count_record_hash(probe),  # type: ignore[arg-type]
        **fields,
    )


def _require_canonical_order(
    records: Sequence[EvaluationCountRecord], releases: tuple[str, ...]
) -> None:
    expected = sorted(
        range(len(records)),
        key=lambda index: (
            CountFamily.index(records[index].count_family),
            scope_sort_key(records[index].scope, releases),
        ),
    )
    if expected != list(range(len(records))):
        raise MetricDerivationError(
            "count records were not produced in canonical order (family, release, "
            "pooled)"
        )


class _CountProbe:
    """The attributes ``count_record_hash`` reads, and nothing else."""

    __slots__ = (
        "ordinal",
        "count_family",
        "scope",
        "total_count",
        "counts",
        "source_fingerprint",
    )

    def __init__(self, **fields: object) -> None:
        for name in self.__slots__:
            setattr(self, name, fields.get(name))
        self.counts = dict(self.counts or {})  # type: ignore[arg-type]
