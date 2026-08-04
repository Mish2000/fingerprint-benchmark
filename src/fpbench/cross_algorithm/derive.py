"""Turning two verified chains into transitions, counts and comparable rates.

The whole of this module is bookkeeping over outcomes. It counts how many pairs
each algorithm matched, how many each declined, and how the two answers moved
relative to each other — and it does that over populations it names explicitly,
because a rate whose population is implied is a rate nobody can check.

Two rules shape everything here.

**Every transition matrix has nine cells.** All of them, including the ones that
are zero. A matrix rendered from only its non-empty cells invites the reader to
assume the missing ones were impossible rather than merely unobserved
(spec section 50).

**A difference is stored only where subtraction is defined.** The full mated
attempt population is identical on both sides by construction, so its rates
subtract. The two conditional populations are each algorithm's own eligible set,
so theirs do not — and the model has nowhere to put the number, rather than a
convention for hiding it (docs/adr/0038, spec sections 45 and 61).
"""

from __future__ import annotations

import datetime as _dt
from typing import Mapping, Sequence

from fpbench.core.cross_algorithm_models import (
    CrossAlgorithmCommonEligibleEntry,
    CrossAlgorithmComparisonRecord,
    CrossAlgorithmCountRecord,
    CrossAlgorithmEligibilityTransition,
    CrossAlgorithmEvaluationManifest,
    CrossAlgorithmObservation,
    ExactRate,
    cross_algorithm_evaluation_fingerprint,
    cross_algorithm_evaluation_id,
    ordered_common_eligible_hash,
    ordered_comparison_records_hash,
    ordered_count_records_hash,
    ordered_eligibility_transitions_hash,
    ordered_observations_hash,
    rate_difference,
)
from fpbench.core.enums import (
    CrossAlgorithmPopulation,
    CrossAlgorithmTransitionFamily,
    DecisionOutcome,
    ProtocolStage,
    SelfEligibilityStatus,
)
from fpbench.cross_algorithm.align import ComparisonSide, CrossAlgorithmError

__all__ = [
    "POOLED_SCOPE",
    "CrossAlgorithmDerivation",
    "FAMILY_STAGES",
    "METRIC_IDS",
    "build_eligibility_transitions",
    "build_common_eligible",
    "build_count_records",
    "build_observations",
    "build_manifest",
    "derive_cross_algorithm_evaluation",
]

#: Not a fourth release. The sum of the release counts, divided once
#: (docs/adr/0028).
POOLED_SCOPE = "pooled"

#: Which protocol stage each transition family covers. ``MATED_COMMON_ELIGIBLE``
#: is the mated stage again, restricted to the intersection of the two eligible
#: sets, and is listed separately because a family is a population and not a
#: stage.
FAMILY_STAGES: Mapping[CrossAlgorithmTransitionFamily, ProtocolStage] = {
    CrossAlgorithmTransitionFamily.PLAIN_SELF: ProtocolStage.PLAIN_SELF,
    CrossAlgorithmTransitionFamily.ROLL_SELF: ProtocolStage.ROLL_SELF,
    CrossAlgorithmTransitionFamily.MATED_UNCONDITIONAL: ProtocolStage.PLAIN_ROLL_MATED,
    CrossAlgorithmTransitionFamily.MATED_COMMON_ELIGIBLE: (
        ProtocolStage.PLAIN_ROLL_MATED
    ),
    CrossAlgorithmTransitionFamily.NEGATIVE_SANITY: (
        ProtocolStage.PLAIN_ROLL_NON_MATED
    ),
}

#: Every rate this comparison reports, in the order the report shows them. The
#: primary one is fifth: it is the full mated attempt population, which is the
#: only mated population identical on both sides by construction
#: (docs/adr/0059, spec section 43).
METRIC_IDS: tuple[str, ...] = (
    "plain_self_match_rate_attempt",
    "plain_self_match_rate_decided",
    "roll_self_match_rate_attempt",
    "roll_self_match_rate_decided",
    "plain_roll_mated_unconditional_non_success_rate_attempt",
    "plain_roll_mated_unconditional_fnmr_decided",
    "plain_roll_mated_conditional_selection_rate",
    "plain_roll_mated_conditional_fnmr_decided",
    "plain_roll_mated_conditional_non_success_rate_attempt",
    "plain_roll_mated_common_eligible_non_success_rate_attempt",
    "plain_roll_mated_common_eligible_fnmr_decided",
    "plain_roll_non_mated_sanity_match_rate_attempt",
    "plain_roll_non_mated_sanity_match_rate_decided",
)

#: The primary operational number. Same 1,500 attempts, same denominator, both
#: NON_MATCH and UNDECIDABLE counted as non-successes, no eligibility filter. It
#: is deliberately *not* called an FNMR (docs/adr/0059, spec section 43).
PRIMARY_METRIC_ID = "plain_roll_mated_unconditional_non_success_rate_attempt"


class CrossAlgorithmDerivation:
    """Everything one comparison produced, as one in-memory unit."""

    __slots__ = (
        "manifest",
        "records",
        "transitions",
        "common_eligible",
        "counts",
        "observations",
        "releases",
    )

    def __init__(
        self,
        *,
        manifest: CrossAlgorithmEvaluationManifest,
        records: tuple[CrossAlgorithmComparisonRecord, ...],
        transitions: tuple[CrossAlgorithmEligibilityTransition, ...],
        common_eligible: tuple[CrossAlgorithmCommonEligibleEntry, ...],
        counts: tuple[CrossAlgorithmCountRecord, ...],
        observations: tuple[CrossAlgorithmObservation, ...],
        releases: tuple[str, ...],
    ) -> None:
        self.manifest = manifest
        self.records = records
        self.transitions = transitions
        self.common_eligible = common_eligible
        self.counts = counts
        self.observations = observations
        self.releases = releases

    @property
    def evaluation_id(self) -> str:
        return self.manifest.evaluation_id


# ------------------------------------------------------------- transitions


def build_eligibility_transitions(
    *, left: ComparisonSide, right: ComparisonSide
) -> tuple[CrossAlgorithmEligibilityTransition, ...]:
    """One row per eligibility unit, joined by unit id rather than by position.

    An ordinal is a property of an ordering; a unit is a property of a finger in
    a release. They agree here, and joining on the id is what makes it safe to
    say so (spec section 46).

    Raises:
        CrossAlgorithmError: the two sides do not cover the same units.
    """
    left_by_unit = {record.eligibility_unit_id: record for record in left.eligibility_records}
    right_by_unit = {
        record.eligibility_unit_id: record for record in right.eligibility_records
    }
    if set(left_by_unit) != set(right_by_unit):
        missing = sorted(set(left_by_unit) - set(right_by_unit))[:3]
        extra = sorted(set(right_by_unit) - set(left_by_unit))[:3]
        raise CrossAlgorithmError(
            "the two eligibility sets cover different units "
            f"(missing on the {right.label} side: {missing}; extra: {extra})"
        )

    transitions: list[CrossAlgorithmEligibilityTransition] = []
    for ordinal, record in enumerate(left.eligibility_records):
        counterpart = right_by_unit[record.eligibility_unit_id]
        if record.mated_pair_id != counterpart.mated_pair_id:
            raise CrossAlgorithmError(
                f"unit {record.eligibility_unit_id} governs pair "
                f"{record.mated_pair_id} on the {left.label} side and "
                f"{counterpart.mated_pair_id} on the {right.label} side"
            )
        transitions.append(
            CrossAlgorithmEligibilityTransition(
                ordinal=ordinal,
                eligibility_unit_id=record.eligibility_unit_id,
                release=record.release,
                mated_pair_id=record.mated_pair_id,
                left_status=record.status,
                right_status=counterpart.status,
                left_record_hash=record.eligibility_record_hash,
                right_record_hash=counterpart.eligibility_record_hash,
            )
        )
    return tuple(transitions)


def build_common_eligible(
    *,
    transitions: Sequence[CrossAlgorithmEligibilityTransition],
    left: ComparisonSide,
    right: ComparisonSide,
    records_by_pair: Mapping[str, CrossAlgorithmComparisonRecord],
) -> tuple[CrossAlgorithmCommonEligibleEntry, ...]:
    """The intersection: units both algorithms proved usable.

    A controlled secondary analysis, and never the headline. It filters out
    exactly the units that were hard for either algorithm, so a difference over
    it answers a narrower question than the primary number does: *when both
    algorithms have shown that a finger's plain and rolled impressions match
    themselves, how did the plain-to-rolled decisions differ?* (spec section 47).
    """
    _ = left, right  # both sides are already joined into ``transitions``
    entries: list[CrossAlgorithmCommonEligibleEntry] = []
    ordinal = 0
    for transition in transitions:
        if not transition.is_common_eligible:
            continue
        record = records_by_pair.get(transition.mated_pair_id)
        if record is None:
            raise CrossAlgorithmError(
                f"unit {transition.eligibility_unit_id} governs mated pair "
                f"{transition.mated_pair_id}, which no comparison record covers"
            )
        entries.append(
            CrossAlgorithmCommonEligibleEntry(
                ordinal=ordinal,
                eligibility_unit_id=transition.eligibility_unit_id,
                release=transition.release,
                mated_pair_id=transition.mated_pair_id,
                left_outcome=record.left_outcome,
                right_outcome=record.right_outcome,
            )
        )
        ordinal += 1
    return tuple(entries)


# ------------------------------------------------------------------ counts


def build_count_records(
    *,
    records: Sequence[CrossAlgorithmComparisonRecord],
    transitions: Sequence[CrossAlgorithmEligibilityTransition],
    common_eligible: Sequence[CrossAlgorithmCommonEligibleEntry],
    releases: Sequence[str],
) -> tuple[CrossAlgorithmCountRecord, ...]:
    """Every cell of every matrix, per release and pooled, zeros included.

    The zeros are the point. Nine cells per family per scope, always, so that a
    cell nobody observed is visibly zero rather than absent (spec section 50).
    """
    scopes = tuple(releases) + (POOLED_SCOPE,)
    counts: list[CrossAlgorithmCountRecord] = []

    by_family: dict[CrossAlgorithmTransitionFamily, list] = {}
    for family, stage in FAMILY_STAGES.items():
        if family is CrossAlgorithmTransitionFamily.MATED_COMMON_ELIGIBLE:
            by_family[family] = list(common_eligible)
            continue
        by_family[family] = [
            record for record in records if record.protocol_stage == stage.value
        ]

    for family, rows in by_family.items():
        for scope in scopes:
            selected = [
                row for row in rows if scope == POOLED_SCOPE or row.release == scope
            ]
            for left_outcome in DecisionOutcome:
                for right_outcome in DecisionOutcome:
                    counts.append(
                        CrossAlgorithmCountRecord(
                            family=family,
                            scope=scope,
                            left_outcome=left_outcome,
                            right_outcome=right_outcome,
                            count=sum(
                                1
                                for row in selected
                                if row.left_outcome is left_outcome
                                and row.right_outcome is right_outcome
                            ),
                        )
                    )

    # The eligibility transition matrix, in the same shape and for the same
    # reason. Recorded with ``left_outcome``/``right_outcome`` left empty because
    # an eligibility status is not a decision outcome, and giving the two the
    # same column would let them be summed by accident.
    for scope in scopes:
        selected = [
            transition
            for transition in transitions
            if scope == POOLED_SCOPE or transition.release == scope
        ]
        for left_status in SelfEligibilityStatus:
            for right_status in SelfEligibilityStatus:
                counts.append(
                    CrossAlgorithmCountRecord(
                        family=CrossAlgorithmTransitionFamily.MATED_UNCONDITIONAL,
                        scope=f"eligibility:{scope}:{left_status.value}:{right_status.value}",
                        left_outcome=None,
                        right_outcome=None,
                        count=sum(
                            1
                            for transition in selected
                            if transition.left_status is left_status
                            and transition.right_status is right_status
                        ),
                    )
                )
    return tuple(counts)


# ------------------------------------------------------------ observations


def _rate(rows: Sequence, *, numerator, denominator) -> ExactRate:
    return ExactRate(
        numerator=sum(1 for row in rows if numerator(row)),
        denominator=sum(1 for row in rows if denominator(row)),
    )


def _decided(outcome: DecisionOutcome) -> bool:
    return outcome is not DecisionOutcome.UNDECIDABLE


def _observation(
    *,
    metric_id: str,
    scope: str,
    population: CrossAlgorithmPopulation,
    left: ExactRate,
    right: ExactRate,
) -> CrossAlgorithmObservation:
    difference = rate_difference(left=left, right=right, population=population)
    return CrossAlgorithmObservation(
        # Metric and scope together, as one well-formed identifier: the pair is
        # what makes an observation unique, and an id that dropped either would
        # collide across releases.
        observation_id=f"{metric_id}_{scope.lower()}",
        metric_id=metric_id,
        scope=scope,
        population=population,
        left_numerator=left.numerator,
        left_denominator=left.denominator,
        right_numerator=right.numerator,
        right_denominator=right.denominator,
        difference_numerator=difference.difference_numerator,
        difference_denominator=difference.difference_denominator,
    )


def _decided_population(rows: Sequence) -> CrossAlgorithmPopulation:
    """Whether the two sides could decide the same subset of the same attempts.

    Same attempts always — the pair manifest is frozen. Same *decided* attempts
    only when neither side failed anywhere the other did not, and a rate over
    decided attempts is comparable only then (docs/adr/0027, spec section 44).
    """
    for row in rows:
        if _decided(row.left_outcome) != _decided(row.right_outcome):
            return CrossAlgorithmPopulation.DIFFERENT_DECIDED_POPULATIONS
    return CrossAlgorithmPopulation.SAME_POPULATION


def _eligible_population(
    transitions: Sequence[CrossAlgorithmEligibilityTransition],
) -> CrossAlgorithmPopulation:
    for transition in transitions:
        if transition.left_status is not transition.right_status:
            return CrossAlgorithmPopulation.DIFFERENT_ELIGIBLE_POPULATIONS
    return CrossAlgorithmPopulation.SAME_POPULATION


def build_observations(
    *,
    records: Sequence[CrossAlgorithmComparisonRecord],
    transitions: Sequence[CrossAlgorithmEligibilityTransition],
    common_eligible: Sequence[CrossAlgorithmCommonEligibleEntry],
    releases: Sequence[str],
) -> tuple[CrossAlgorithmObservation, ...]:
    """One observation per metric per scope, each carrying its own population."""
    scopes = tuple(releases) + (POOLED_SCOPE,)
    by_stage: dict[str, list[CrossAlgorithmComparisonRecord]] = {}
    for record in records:
        by_stage.setdefault(record.protocol_stage, []).append(record)

    observations: list[CrossAlgorithmObservation] = []
    for scope in scopes:

        def _in_scope(row) -> bool:
            return scope == POOLED_SCOPE or row.release == scope

        for stage, prefix in (
            (ProtocolStage.PLAIN_SELF.value, "plain_self"),
            (ProtocolStage.ROLL_SELF.value, "roll_self"),
        ):
            rows = [row for row in by_stage.get(stage, ()) if _in_scope(row)]
            observations.append(
                _observation(
                    metric_id=f"{prefix}_match_rate_attempt",
                    scope=scope,
                    population=CrossAlgorithmPopulation.SAME_POPULATION,
                    left=_rate(
                        rows,
                        numerator=lambda r: r.left_outcome is DecisionOutcome.MATCH,
                        denominator=lambda r: True,
                    ),
                    right=_rate(
                        rows,
                        numerator=lambda r: r.right_outcome is DecisionOutcome.MATCH,
                        denominator=lambda r: True,
                    ),
                )
            )
            observations.append(
                _observation(
                    metric_id=f"{prefix}_match_rate_decided",
                    scope=scope,
                    population=_decided_population(rows),
                    left=_rate(
                        rows,
                        numerator=lambda r: r.left_outcome is DecisionOutcome.MATCH,
                        denominator=lambda r: _decided(r.left_outcome),
                    ),
                    right=_rate(
                        rows,
                        numerator=lambda r: r.right_outcome is DecisionOutcome.MATCH,
                        denominator=lambda r: _decided(r.right_outcome),
                    ),
                )
            )

        mated = [
            row
            for row in by_stage.get(ProtocolStage.PLAIN_ROLL_MATED.value, ())
            if _in_scope(row)
        ]
        observations.append(
            _observation(
                metric_id=PRIMARY_METRIC_ID,
                scope=scope,
                population=CrossAlgorithmPopulation.SAME_POPULATION,
                left=_rate(
                    mated,
                    numerator=lambda r: r.left_outcome is not DecisionOutcome.MATCH,
                    denominator=lambda r: True,
                ),
                right=_rate(
                    mated,
                    numerator=lambda r: r.right_outcome is not DecisionOutcome.MATCH,
                    denominator=lambda r: True,
                ),
            )
        )
        observations.append(
            _observation(
                metric_id="plain_roll_mated_unconditional_fnmr_decided",
                scope=scope,
                population=_decided_population(mated),
                left=_rate(
                    mated,
                    numerator=lambda r: r.left_outcome is DecisionOutcome.NON_MATCH,
                    denominator=lambda r: _decided(r.left_outcome),
                ),
                right=_rate(
                    mated,
                    numerator=lambda r: r.right_outcome is DecisionOutcome.NON_MATCH,
                    denominator=lambda r: _decided(r.right_outcome),
                ),
            )
        )

        scoped_transitions = [
            transition
            for transition in transitions
            if scope == POOLED_SCOPE or transition.release == scope
        ]
        eligible_population = _eligible_population(scoped_transitions)
        observations.append(
            _observation(
                metric_id="plain_roll_mated_conditional_selection_rate",
                scope=scope,
                # Both sides divide by every eligibility unit in scope, so the
                # denominators are identical whatever each side selected. That is
                # what makes *this* conditional number comparable while the two
                # below are not (docs/adr/0029).
                population=CrossAlgorithmPopulation.SAME_POPULATION,
                left=_rate(
                    scoped_transitions,
                    numerator=lambda t: t.left_status is SelfEligibilityStatus.ELIGIBLE,
                    denominator=lambda t: True,
                ),
                right=_rate(
                    scoped_transitions,
                    numerator=lambda t: t.right_status
                    is SelfEligibilityStatus.ELIGIBLE,
                    denominator=lambda t: True,
                ),
            )
        )

        left_included = _included_pairs(scoped_transitions, side="left")
        right_included = _included_pairs(scoped_transitions, side="right")
        left_rows = [row for row in mated if row.pair_id in left_included]
        right_rows = [row for row in mated if row.pair_id in right_included]
        observations.append(
            _observation(
                metric_id="plain_roll_mated_conditional_non_success_rate_attempt",
                scope=scope,
                population=eligible_population,
                left=_rate(
                    left_rows,
                    numerator=lambda r: r.left_outcome is not DecisionOutcome.MATCH,
                    denominator=lambda r: True,
                ),
                right=_rate(
                    right_rows,
                    numerator=lambda r: r.right_outcome is not DecisionOutcome.MATCH,
                    denominator=lambda r: True,
                ),
            )
        )
        observations.append(
            _observation(
                metric_id="plain_roll_mated_conditional_fnmr_decided",
                scope=scope,
                population=(
                    _decided_population(left_rows)
                    if eligible_population is CrossAlgorithmPopulation.SAME_POPULATION
                    else eligible_population
                ),
                left=_rate(
                    left_rows,
                    numerator=lambda r: r.left_outcome is DecisionOutcome.NON_MATCH,
                    denominator=lambda r: _decided(r.left_outcome),
                ),
                right=_rate(
                    right_rows,
                    numerator=lambda r: r.right_outcome is DecisionOutcome.NON_MATCH,
                    denominator=lambda r: _decided(r.right_outcome),
                ),
            )
        )

        common = [entry for entry in common_eligible if _in_scope(entry)]
        observations.append(
            _observation(
                metric_id=(
                    "plain_roll_mated_common_eligible_non_success_rate_attempt"
                ),
                scope=scope,
                population=CrossAlgorithmPopulation.COMMON_ELIGIBLE_POPULATION,
                left=_rate(
                    common,
                    numerator=lambda e: e.left_outcome is not DecisionOutcome.MATCH,
                    denominator=lambda e: True,
                ),
                right=_rate(
                    common,
                    numerator=lambda e: e.right_outcome is not DecisionOutcome.MATCH,
                    denominator=lambda e: True,
                ),
            )
        )
        observations.append(
            _observation(
                metric_id="plain_roll_mated_common_eligible_fnmr_decided",
                scope=scope,
                population=(
                    CrossAlgorithmPopulation.COMMON_ELIGIBLE_POPULATION
                    if _decided_population(common)
                    is CrossAlgorithmPopulation.SAME_POPULATION
                    else CrossAlgorithmPopulation.DIFFERENT_DECIDED_POPULATIONS
                ),
                left=_rate(
                    common,
                    numerator=lambda e: e.left_outcome is DecisionOutcome.NON_MATCH,
                    denominator=lambda e: _decided(e.left_outcome),
                ),
                right=_rate(
                    common,
                    numerator=lambda e: e.right_outcome is DecisionOutcome.NON_MATCH,
                    denominator=lambda e: _decided(e.right_outcome),
                ),
            )
        )

        sanity = [
            row
            for row in by_stage.get(ProtocolStage.PLAIN_ROLL_NON_MATED.value, ())
            if _in_scope(row)
        ]
        observations.append(
            _observation(
                metric_id="plain_roll_non_mated_sanity_match_rate_attempt",
                scope=scope,
                population=CrossAlgorithmPopulation.SAME_POPULATION,
                left=_rate(
                    sanity,
                    numerator=lambda r: r.left_outcome is DecisionOutcome.MATCH,
                    denominator=lambda r: True,
                ),
                right=_rate(
                    sanity,
                    numerator=lambda r: r.right_outcome is DecisionOutcome.MATCH,
                    denominator=lambda r: True,
                ),
            )
        )
        observations.append(
            _observation(
                metric_id="plain_roll_non_mated_sanity_match_rate_decided",
                scope=scope,
                population=_decided_population(sanity),
                left=_rate(
                    sanity,
                    numerator=lambda r: r.left_outcome is DecisionOutcome.MATCH,
                    denominator=lambda r: _decided(r.left_outcome),
                ),
                right=_rate(
                    sanity,
                    numerator=lambda r: r.right_outcome is DecisionOutcome.MATCH,
                    denominator=lambda r: _decided(r.right_outcome),
                ),
            )
        )

    ordered = {metric: index for index, metric in enumerate(METRIC_IDS)}
    return tuple(
        sorted(
            observations,
            key=lambda observation: (
                ordered.get(observation.metric_id, len(ordered)),
                observation.scope,
            ),
        )
    )


def _included_pairs(
    transitions: Sequence[CrossAlgorithmEligibilityTransition], *, side: str
) -> frozenset[str]:
    """Which mated pairs one side's conditional view kept.

    Derived from the eligibility transitions rather than read out of the stored
    conditional views, so that both sides are selected by *one* rule applied
    twice rather than by two stored artefacts that happen to agree. If they ever
    stopped agreeing, that would be a finding, and it would be invisible if this
    function read them (docs/adr/0024).
    """
    attribute = "left_status" if side == "left" else "right_status"
    return frozenset(
        transition.mated_pair_id
        for transition in transitions
        if getattr(transition, attribute) is SelfEligibilityStatus.ELIGIBLE
    )


# ------------------------------------------------------------------ manifest


def build_manifest(
    *,
    definition_fingerprint: str,
    audit_fingerprint: str,
    records: Sequence[CrossAlgorithmComparisonRecord],
    transitions: Sequence[CrossAlgorithmEligibilityTransition],
    common_eligible: Sequence[CrossAlgorithmCommonEligibleEntry],
    counts: Sequence[CrossAlgorithmCountRecord],
    observations: Sequence[CrossAlgorithmObservation],
    created_utc: str | None = None,
) -> CrossAlgorithmEvaluationManifest:
    records_hash = ordered_comparison_records_hash(records)
    transitions_hash = ordered_eligibility_transitions_hash(transitions)
    common_hash = ordered_common_eligible_hash(common_eligible)
    counts_hash = ordered_count_records_hash(counts)
    observations_hash = ordered_observations_hash(observations)
    fingerprint = cross_algorithm_evaluation_fingerprint(
        definition_fingerprint=definition_fingerprint,
        audit_fingerprint=audit_fingerprint,
        comparison_records_hash=records_hash,
        eligibility_transitions_hash=transitions_hash,
        common_eligible_hash=common_hash,
        count_records_hash=counts_hash,
        observations_hash=observations_hash,
        total_records=len(records),
        total_transitions=len(transitions),
        total_common_eligible=len(common_eligible),
        total_observations=len(observations),
    )
    return CrossAlgorithmEvaluationManifest(
        evaluation_id=cross_algorithm_evaluation_id(fingerprint),
        evaluation_fingerprint=fingerprint,
        definition_id=f"algcomparedef_{definition_fingerprint[:12]}",
        definition_fingerprint=definition_fingerprint,
        audit_fingerprint=audit_fingerprint,
        comparison_records_hash=records_hash,
        eligibility_transitions_hash=transitions_hash,
        common_eligible_hash=common_hash,
        count_records_hash=counts_hash,
        observations_hash=observations_hash,
        total_records=len(records),
        total_transitions=len(transitions),
        total_common_eligible=len(common_eligible),
        total_observations=len(observations),
        created_utc=created_utc or _dt.datetime.now(_dt.timezone.utc).isoformat(),
    )


def derive_cross_algorithm_evaluation(
    *,
    definition_fingerprint: str,
    audit_fingerprint: str,
    left: ComparisonSide,
    right: ComparisonSide,
    records: Sequence[CrossAlgorithmComparisonRecord],
    releases: Sequence[str],
    created_utc: str | None = None,
) -> CrossAlgorithmDerivation:
    """Build every derived artefact of one comparison, in dependency order."""
    records = tuple(records)
    records_by_pair = {record.pair_id: record for record in records}
    transitions = build_eligibility_transitions(left=left, right=right)
    common_eligible = build_common_eligible(
        transitions=transitions,
        left=left,
        right=right,
        records_by_pair=records_by_pair,
    )
    counts = build_count_records(
        records=records,
        transitions=transitions,
        common_eligible=common_eligible,
        releases=releases,
    )
    observations = build_observations(
        records=records,
        transitions=transitions,
        common_eligible=common_eligible,
        releases=releases,
    )
    manifest = build_manifest(
        definition_fingerprint=definition_fingerprint,
        audit_fingerprint=audit_fingerprint,
        records=records,
        transitions=transitions,
        common_eligible=common_eligible,
        counts=counts,
        observations=observations,
        created_utc=created_utc,
    )
    return CrossAlgorithmDerivation(
        manifest=manifest,
        records=records,
        transitions=transitions,
        common_eligible=common_eligible,
        counts=counts,
        observations=observations,
        releases=tuple(releases),
    )
