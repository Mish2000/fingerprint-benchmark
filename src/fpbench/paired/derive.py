"""Joining two chains pair by pair, and counting what changed.

Five steps, in this order, and the order matters because each rests on the one
before it.

**Align.** Every ``pair_id`` in the frozen manifest must appear exactly once on
each side, with the same release, the same protocol stage, the same left and
right *source* images and the same orientation. Job ids are expected to differ —
a job id is a hash over its own run — and that is the reason the join is on
``pair_id`` and never on a job id or an ordinal.

**Record.** One row per pair, carrying both outcomes, both result hashes, both
decision hashes and the exact score delta when both sides scored.

**Control.** SD300A must reproduce exactly. That check comes before any
aggregate, because if it fails the aggregates are measuring something nobody has
identified and printing them would be worse than printing nothing.

**Transition.** Six matrices, each at four scopes, every cell present.

**Observe.** Ten rates on each side, with their exact reduced differences where
the two sides are comparable and an explicit refusal where they are not.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Iterable, Mapping, Sequence

from fpbench.core.enums import (
    ComparabilityStatus,
    DecisionOutcome,
    ExecutionStatus,
    ProtocolStage,
)
from fpbench.core.errors import ControlAuditError, PairedAlignmentError
from fpbench.core.paired_models import (
    ALL_TRANSITION_KEYS,
    ELIGIBILITY_FAMILY,
    MATED_COMMON_ELIGIBLE_FAMILY,
    MATED_UNCONDITIONAL_FAMILY,
    NEGATIVE_SANITY_FAMILY,
    PLAIN_SELF_FAMILY,
    ROLL_SELF_FAMILY,
    CommonEligibleMatedEntry,
    MetricScopeRef,
    NativeCanonicalControlAudit,
    PairedComparisonRecord,
    PairedRateObservation,
    SelfEligibilityTransitionRecord,
    TransitionCountRecord,
    common_eligible_entry_hash,
    control_audit_fingerprint,
    decision_outcome_of,
    eligibility_transition_record_hash,
    exact_rate_difference,
    paired_comparison_record_hash,
    paired_rate_observation_hash,
    transition_count_record_hash,
    transition_key,
)
from fpbench.paired.sources import PairedSide

__all__ = [
    "CONTROL_RELEASE",
    "OBSERVATION_IDS",
    "align_pairs",
    "build_paired_records",
    "build_control_audit",
    "build_eligibility_transitions",
    "build_common_eligible_view",
    "build_transition_counts",
    "build_paired_observations",
    "release_order",
]

#: The release whose canonical artefacts preserve their source rasters byte for
#: byte, so its two runs must agree exactly (docs/adr/0034, spec section 32).
CONTROL_RELEASE = "SD300A"

#: Every rate the comparison reports, in storage order.
OBSERVATION_IDS: tuple[str, ...] = (
    "plain_self_attempt_match_fraction",
    "roll_self_attempt_match_fraction",
    "self_eligibility_fraction",
    "mated_unconditional_attempt_non_success_fraction",
    "mated_unconditional_decision_fnmr",
    "negative_sanity_attempt_match_fraction",
    "common_eligible_selection_fraction",
    "common_eligible_mated_attempt_non_success_fraction",
    "common_eligible_mated_decision_fnmr",
    "per_run_conditional_mated_decision_fnmr",
)

_STAGE_FAMILY = {
    ProtocolStage.PLAIN_SELF: PLAIN_SELF_FAMILY,
    ProtocolStage.ROLL_SELF: ROLL_SELF_FAMILY,
    ProtocolStage.PLAIN_ROLL_MATED: MATED_UNCONDITIONAL_FAMILY,
    ProtocolStage.PLAIN_ROLL_NON_MATED: NEGATIVE_SANITY_FAMILY,
}

#: The nine eligibility transitions, in a fixed order so the stored hash is
#: stable. Every cell is present even when zero (spec section 38).
_ELIGIBILITY_STATES = ("eligible", "ineligible", "undetermined")
ALL_ELIGIBILITY_KEYS: tuple[str, ...] = tuple(
    f"{native}_to_{canonical}"
    for native in _ELIGIBILITY_STATES
    for canonical in _ELIGIBILITY_STATES
)


def release_order(native: PairedSide) -> tuple[str, ...]:
    """The releases the pair manifest covers, in ascending order."""
    return tuple(sorted({pair.release for pair in native.pairs.values()}))


# ------------------------------------------------------------------- align


def align_pairs(*, native: PairedSide, canonical: PairedSide) -> tuple[str, ...]:
    """Return the pair ids both runs cover, in pair-manifest order.

    Raises:
        PairedAlignmentError: a pair is missing on one side, appears twice, has
            no job, has more than one job, or describes a different comparison
            on the two sides.
    """
    native_ids = [str(planned.job.pair_id) for planned in native.plan.jobs]
    canonical_ids = [str(planned.job.pair_id) for planned in canonical.plan.jobs]

    for label, ids in (("native", native_ids), ("canonical", canonical_ids)):
        duplicates = sorted({item for item in ids if ids.count(item) > 1})
        if duplicates:
            raise PairedAlignmentError(
                f"{label}: {len(duplicates)} pair id(s) are planned more than once, "
                f"starting with {duplicates[:3]}"
            )

    native_set = set(native_ids)
    canonical_set = set(canonical_ids)
    missing_canonical = sorted(native_set - canonical_set)
    missing_native = sorted(canonical_set - native_set)
    if missing_canonical:
        raise PairedAlignmentError(
            f"{len(missing_canonical)} pair(s) exist in the native run and not in "
            f"the canonical one, starting with {missing_canonical[:3]}"
        )
    if missing_native:
        raise PairedAlignmentError(
            f"{len(missing_native)} pair(s) exist in the canonical run and not in "
            f"the native one, starting with {missing_native[:3]}"
        )

    # Same order, not merely the same set. The pair manifest is frozen and both
    # plans are built from it, so a different order means one of them was not.
    if native_ids != canonical_ids:
        first = next(
            index
            for index, (left, right) in enumerate(zip(native_ids, canonical_ids))
            if left != right
        )
        raise PairedAlignmentError(
            f"the two plans order their pairs differently, first at ordinal "
            f"{first}: {native_ids[first]!r} versus {canonical_ids[first]!r}"
        )

    for pair_id in native_ids:
        _require_same_comparison(pair_id, native, canonical)
    return tuple(native_ids)


def _require_same_comparison(
    pair_id: str, native: PairedSide, canonical: PairedSide
) -> None:
    left = native.pairs.get(pair_id)
    right = canonical.pairs.get(pair_id)
    if left is None or right is None:
        raise PairedAlignmentError(
            f"{pair_id} is planned but absent from a pair manifest"
        )
    checks = (
        ("dataset", left.dataset_id, right.dataset_id),
        ("release", left.release, right.release),
        ("protocol stage", left.protocol_stage.value, right.protocol_stage.value),
        ("ground truth", left.ground_truth.value, right.ground_truth.value),
        ("left image", str(left.left_image_id), str(right.left_image_id)),
        ("right image", str(left.right_image_id), str(right.right_image_id)),
    )
    for label, a, b in checks:
        if a != b:
            raise PairedAlignmentError(
                f"{pair_id}: the two runs disagree about the {label} "
                f"({a!r} versus {b!r}). The probe/candidate orientation and the "
                "source images must be identical for a comparison to be paired"
            )


# ------------------------------------------------------------------ records


def build_paired_records(
    *,
    native: PairedSide,
    canonical: PairedSide,
    pair_ids: Sequence[str],
) -> tuple[PairedComparisonRecord, ...]:
    """One row per pair, with both outcomes and the exact score delta."""
    native_jobs = native.jobs_by_pair
    canonical_jobs = canonical.jobs_by_pair
    native_decisions = native.decisions_by_job
    canonical_decisions = canonical.decisions_by_job

    records: list[PairedComparisonRecord] = []
    for ordinal, pair_id in enumerate(pair_ids):
        pair = native.pairs[pair_id]
        native_job = native_jobs[pair_id]
        canonical_job = canonical_jobs[pair_id]

        native_decision = _require_decision(native_decisions, native_job, "native")
        canonical_decision = _require_decision(
            canonical_decisions, canonical_job, "canonical"
        )

        native_score = _score_of(native, native_job)
        canonical_score = _score_of(canonical, canonical_job)
        native_result = native.result_store.read_raw_result(native.run.run_id, native_job)
        canonical_result = canonical.result_store.read_raw_result(
            canonical.run.run_id, canonical_job
        )
        relation, delta = _relate(native_score, canonical_score)

        draft = dict(
            ordinal=ordinal,
            pair_id=pair_id,
            release=pair.release,
            protocol_stage=pair.protocol_stage,
            native_job_id=native_job,
            canonical_job_id=canonical_job,
            native_raw_result_hash=native_decision.source_result_hash,
            canonical_raw_result_hash=canonical_decision.source_result_hash,
            native_decision_hash=native_decision.decision_record_hash,
            canonical_decision_hash=canonical_decision.decision_record_hash,
            native_execution_status=native_result.status,
            canonical_execution_status=canonical_result.status,
            native_failure_code=(
                native_result.failure.code.value if native_result.failure else None
            ),
            canonical_failure_code=(
                canonical_result.failure.code.value if canonical_result.failure else None
            ),
            native_outcome=decision_outcome_of(
                application_status=native_decision.application_status,
                decision=native_decision.decision,
            ),
            canonical_outcome=decision_outcome_of(
                application_status=canonical_decision.application_status,
                decision=canonical_decision.decision,
            ),
            score_relation=relation,
            score_delta_decimal=delta,
        )
        records.append(
            PairedComparisonRecord(
                record_hash=paired_comparison_record_hash(_Draft(**draft)), **draft
            )
        )
    return tuple(records)


class _Draft:
    """A record-shaped stand-in used only to compute a hash.

    Every record in this project validates its own hash in ``__post_init__``, so
    none can be built before the hash exists. Feeding the hash rule a stand-in
    keeps the rule in one place rather than copying it here.
    """

    __slots__ = (
        "ordinal",
        "pair_id",
        "release",
        "protocol_stage",
        "native_job_id",
        "canonical_job_id",
        "native_raw_result_hash",
        "canonical_raw_result_hash",
        "native_decision_hash",
        "canonical_decision_hash",
        "native_execution_status",
        "canonical_execution_status",
        "native_failure_code",
        "canonical_failure_code",
        "native_outcome",
        "canonical_outcome",
        "score_relation",
        "score_delta_decimal",
    )

    def __init__(self, **fields: object) -> None:
        for name in self.__slots__:
            setattr(self, name, fields[name])


def _require_decision(decisions: Mapping[str, object], job_id: str, label: str):
    record = decisions.get(job_id)
    if record is None:
        raise PairedAlignmentError(
            f"{label}: job {job_id} has no decision; the decision set and the plan "
            "disagree"
        )
    return record


def _score_of(side: PairedSide, job_id: str) -> str | None:
    """The raw score as an exact decimal string, or ``None`` if there is none.

    Read from the stored result rather than from the decision, because a
    decision deliberately does not copy the score — that would create a second
    place the number lives (docs/adr/0022).
    """
    record = side.result_store.read_raw_result(side.run.run_id, job_id)
    if record.status is not ExecutionStatus.SUCCESS or record.raw_score is None:
        return None
    # A float round-trips exactly through repr, and Decimal(repr(x)) is the
    # shortest decimal that maps back to the same float. Two identical floats
    # therefore always yield identical strings, which is what the SD300A control
    # needs.
    return format(Decimal(repr(float(record.raw_score))), "f")


def _relate(native: str | None, canonical: str | None):
    from fpbench.core.enums import ScoreRelation

    if native is None or canonical is None:
        return ScoreRelation.UNAVAILABLE, None
    delta = Decimal(canonical) - Decimal(native)
    rendered = format(delta, "f")
    if delta == 0:
        return ScoreRelation.EQUAL, rendered
    if delta > 0:
        return ScoreRelation.CANONICAL_HIGHER, rendered
    return ScoreRelation.CANONICAL_LOWER, rendered


# ------------------------------------------------------------------ control


def build_control_audit(
    records: Iterable[PairedComparisonRecord],
    *,
    control_release: str = CONTROL_RELEASE,
) -> NativeCanonicalControlAudit:
    """Prove SD300A reproduced exactly, or say precisely how it did not.

    No rounding and no tolerance. The scores are compared as exact decimal
    strings, which for two identical floats are identical strings.
    """
    planned = 0
    compared = 0
    equal_scores = 0
    equal_statuses = 0
    equal_decisions = 0
    issues: list[str] = []

    for record in records:
        if record.release != control_release:
            continue
        planned += 1

        from fpbench.core.enums import ScoreRelation

        if record.score_relation is ScoreRelation.UNAVAILABLE:
            issues.append(
                f"{record.pair_id}: at least one side produced no score, so the "
                "control cannot be checked"
            )
        else:
            compared += 1
            if record.score_relation is ScoreRelation.EQUAL:
                equal_scores += 1
            else:
                issues.append(
                    f"{record.pair_id}: the canonical score differs from the native "
                    f"one by {record.score_delta_decimal}, but its pixels are "
                    "identical"
                )

        if record.native_execution_status is record.canonical_execution_status:
            equal_statuses += 1
        else:
            issues.append(
                f"{record.pair_id}: execution status changed from "
                f"{record.native_execution_status.value} to "
                f"{record.canonical_execution_status.value}"
            )
        if (
            record.native_execution_status is not ExecutionStatus.SUCCESS
            and record.canonical_execution_status is not ExecutionStatus.SUCCESS
            and record.native_failure_code != record.canonical_failure_code
        ):
            issues.append(
                f"{record.pair_id}: failure code changed from "
                f"{record.native_failure_code!r} to {record.canonical_failure_code!r}"
            )

        if record.native_outcome is record.canonical_outcome:
            equal_decisions += 1
        else:
            issues.append(
                f"{record.pair_id}: the decision changed from "
                f"{record.native_outcome.value} to {record.canonical_outcome.value} "
                "over identical pixels"
            )

    draft = dict(
        planned_sd300a_pairs=planned,
        compared_scores=compared,
        equal_scores=equal_scores,
        equal_result_statuses=equal_statuses,
        equal_decisions=equal_decisions,
        # Bounded so that a catastrophic mismatch produces a readable artefact
        # rather than a 2,000-line one. The counts above are the authority.
        issues=tuple(issues[:20]),
    )
    return NativeCanonicalControlAudit(
        audit_fingerprint=control_audit_fingerprint(_AuditDraft(**draft)), **draft
    )


class _AuditDraft:
    __slots__ = (
        "planned_sd300a_pairs",
        "compared_scores",
        "equal_scores",
        "equal_result_statuses",
        "equal_decisions",
        "issues",
    )

    def __init__(self, **fields: object) -> None:
        for name in self.__slots__:
            setattr(self, name, fields[name])


def require_clean_control(audit: NativeCanonicalControlAudit) -> None:
    """Stop the derivation if the control did not reproduce.

    Deliberately fatal rather than a recorded finding. Every other number in the
    comparison is interpreted as an effect of image preparation, and that
    interpretation is exactly what a failed control withdraws.
    """
    if not audit.is_clean:
        raise ControlAuditError(
            f"the {CONTROL_RELEASE} control did not reproduce: "
            f"{audit.equal_scores}/{audit.planned_sd300a_pairs} equal scores, "
            f"{audit.equal_decisions}/{audit.planned_sd300a_pairs} equal decisions. "
            f"{'; '.join(audit.issues[:3])}"
        )


# ------------------------------------------------------- eligibility transitions


def build_eligibility_transitions(
    *, native: PairedSide, canonical: PairedSide
) -> tuple[SelfEligibilityTransitionRecord, ...]:
    """One row per SELF unit, with both runs' verdicts."""
    native_by_unit = native.eligibility_by_unit
    canonical_by_unit = canonical.eligibility_by_unit

    missing = sorted(set(native_by_unit) ^ set(canonical_by_unit))
    if missing:
        raise PairedAlignmentError(
            f"{len(missing)} eligibility unit(s) exist on only one side, starting "
            f"with {missing[:3]}"
        )

    subjects = {unit.eligibility_unit_id: unit.subject_id for unit in native.units}

    records: list[SelfEligibilityTransitionRecord] = []
    for ordinal, unit_id in enumerate(sorted(native_by_unit)):
        left = native_by_unit[unit_id]
        right = canonical_by_unit[unit_id]
        if left.release != right.release or left.canonical_finger != right.canonical_finger:
            raise PairedAlignmentError(
                f"{unit_id}: the two runs describe different fingers"
            )
        draft = dict(
            ordinal=ordinal,
            eligibility_unit_id=unit_id,
            release=left.release,
            subject_id=str(subjects.get(unit_id, "")),
            finger_id=left.canonical_finger,
            native_record_hash=left.eligibility_record_hash,
            canonical_record_hash=right.eligibility_record_hash,
            native_status=left.status.value,
            canonical_status=right.status.value,
        )
        records.append(
            SelfEligibilityTransitionRecord(
                record_hash=eligibility_transition_record_hash(
                    _EligibilityDraft(**draft)
                ),
                **draft,
            )
        )
    return tuple(records)


class _EligibilityDraft:
    __slots__ = (
        "ordinal",
        "eligibility_unit_id",
        "release",
        "subject_id",
        "finger_id",
        "native_record_hash",
        "canonical_record_hash",
        "native_status",
        "canonical_status",
    )

    def __init__(self, **fields: object) -> None:
        for name in self.__slots__:
            setattr(self, name, fields[name])


# --------------------------------------------------------- common-eligible view


def build_common_eligible_view(
    *,
    native: PairedSide,
    canonical: PairedSide,
    transitions: Sequence[SelfEligibilityTransitionRecord],
    records: Sequence[PairedComparisonRecord],
) -> tuple[CommonEligibleMatedEntry, ...]:
    """Every mated row, marked with whether both runs found its finger eligible.

    Excluded rows stay. A view that dropped them could not state its own
    selection fraction, and a conditional result published without one is a
    number with an invisible denominator (docs/adr/0029).
    """
    del canonical  # the two eligibility verdicts already travel in `transitions`
    by_unit = {record.eligibility_unit_id: record for record in transitions}
    mated_unit_of = {
        unit.mated_pair_id: unit.eligibility_unit_id for unit in native.units
    }

    entries: list[CommonEligibleMatedEntry] = []
    ordinal = 0
    for record in records:
        if record.protocol_stage is not ProtocolStage.PLAIN_ROLL_MATED:
            continue
        unit_id = mated_unit_of.get(str(record.pair_id))
        if unit_id is None:
            raise PairedAlignmentError(
                f"{record.pair_id}: a mated comparison with no eligibility unit"
            )
        transition = by_unit[unit_id]
        draft = dict(
            ordinal=ordinal,
            pair_id=str(record.pair_id),
            release=record.release,
            native_eligibility_status=transition.native_status,
            canonical_eligibility_status=transition.canonical_status,
            included=transition.common_eligible,
            native_job_id=record.native_job_id,
            canonical_job_id=record.canonical_job_id,
            native_decision_hash=record.native_decision_hash,
            canonical_decision_hash=record.canonical_decision_hash,
            native_outcome=record.native_outcome,
            canonical_outcome=record.canonical_outcome,
        )
        entries.append(
            CommonEligibleMatedEntry(
                entry_hash=common_eligible_entry_hash(_CommonDraft(**draft)), **draft
            )
        )
        ordinal += 1

    return tuple(entries)


class _CommonDraft:
    __slots__ = (
        "ordinal",
        "pair_id",
        "release",
        "native_eligibility_status",
        "canonical_eligibility_status",
        "included",
        "native_job_id",
        "canonical_job_id",
        "native_decision_hash",
        "canonical_decision_hash",
        "native_outcome",
        "canonical_outcome",
    )

    def __init__(self, **fields: object) -> None:
        for name in self.__slots__:
            setattr(self, name, fields[name])


# --------------------------------------------------------------- transitions


def build_transition_counts(
    *,
    records: Sequence[PairedComparisonRecord],
    transitions: Sequence[SelfEligibilityTransitionRecord],
    common_eligible: Sequence[CommonEligibleMatedEntry],
    releases: Sequence[str],
    source_fingerprints: Mapping[str, str],
) -> tuple[TransitionCountRecord, ...]:
    """Six matrices at four scopes each, with every cell present.

    Pooled counts are the sum of the release counts and nothing else. Averaging
    percentages across releases would weight a release by nothing in particular
    (docs/adr/0028).
    """
    scopes = [MetricScopeRef(scope_kind="release", release=name) for name in releases]
    scopes.append(MetricScopeRef(scope_kind="pooled"))

    families: list[tuple[str, object]] = [
        (PLAIN_SELF_FAMILY, ProtocolStage.PLAIN_SELF),
        (ROLL_SELF_FAMILY, ProtocolStage.ROLL_SELF),
        (MATED_UNCONDITIONAL_FAMILY, ProtocolStage.PLAIN_ROLL_MATED),
        (MATED_COMMON_ELIGIBLE_FAMILY, None),
        (NEGATIVE_SANITY_FAMILY, ProtocolStage.PLAIN_ROLL_NON_MATED),
        (ELIGIBILITY_FAMILY, None),
    ]

    built: list[TransitionCountRecord] = []
    ordinal = 0
    for family, stage in families:
        for scope in scopes:
            if family == ELIGIBILITY_FAMILY:
                counts, total = _eligibility_counts(transitions, scope)
            elif family == MATED_COMMON_ELIGIBLE_FAMILY:
                counts, total = _common_eligible_counts(common_eligible, scope)
            else:
                counts, total = _decision_counts(records, stage, scope)
            draft = dict(
                ordinal=ordinal,
                family=family,
                scope=scope,
                total=total,
                counts=counts,
                source_fingerprints=dict(source_fingerprints),
            )
            built.append(
                TransitionCountRecord(
                    record_hash=transition_count_record_hash(_CountDraft(**draft)),
                    **draft,
                )
            )
            ordinal += 1
    return tuple(built)


class _CountDraft:
    __slots__ = ("ordinal", "family", "scope", "total", "counts", "source_fingerprints")

    def __init__(self, **fields: object) -> None:
        for name in self.__slots__:
            setattr(self, name, fields[name])


def _in_scope(release: str, scope: MetricScopeRef) -> bool:
    return scope.scope_kind == "pooled" or release == scope.release


def _decision_counts(
    records: Sequence[PairedComparisonRecord],
    stage: ProtocolStage,
    scope: MetricScopeRef,
) -> tuple[dict[str, int], int]:
    counts = {key: 0 for key in ALL_TRANSITION_KEYS}
    total = 0
    for record in records:
        if record.protocol_stage is not stage or not _in_scope(record.release, scope):
            continue
        counts[record.transition] += 1
        total += 1
    return counts, total


def _common_eligible_counts(
    entries: Sequence[CommonEligibleMatedEntry], scope: MetricScopeRef
) -> tuple[dict[str, int], int]:
    counts = {key: 0 for key in ALL_TRANSITION_KEYS}
    total = 0
    for entry in entries:
        if not entry.included or not _in_scope(entry.release, scope):
            continue
        counts[transition_key(entry.native_outcome, entry.canonical_outcome)] += 1
        total += 1
    return counts, total


def _eligibility_counts(
    transitions: Sequence[SelfEligibilityTransitionRecord], scope: MetricScopeRef
) -> tuple[dict[str, int], int]:
    counts = {key: 0 for key in ALL_ELIGIBILITY_KEYS}
    total = 0
    for record in transitions:
        if not _in_scope(record.release, scope):
            continue
        counts[record.transition] += 1
        total += 1
    return counts, total


# -------------------------------------------------------------- observations


def build_paired_observations(
    *,
    records: Sequence[PairedComparisonRecord],
    transitions: Sequence[SelfEligibilityTransitionRecord],
    common_eligible: Sequence[CommonEligibleMatedEntry],
    releases: Sequence[str],
    policy_fingerprint: str,
) -> tuple[PairedRateObservation, ...]:
    """Ten rates per scope, each with the four integers it was computed from."""
    scopes = [MetricScopeRef(scope_kind="release", release=name) for name in releases]
    scopes.append(MetricScopeRef(scope_kind="pooled"))

    built: list[PairedRateObservation] = []
    ordinal = 0
    for observation_id in OBSERVATION_IDS:
        for scope in scopes:
            counts, comparability = _observation_counts(
                observation_id=observation_id,
                scope=scope,
                records=records,
                transitions=transitions,
                common_eligible=common_eligible,
            )
            native_numerator, native_denominator, canonical_numerator, canonical_denominator = counts

            if native_denominator == 0 or canonical_denominator == 0:
                comparability = ComparabilityStatus.UNDEFINED

            difference = None
            if comparability is ComparabilityStatus.DIRECTLY_COMPARABLE:
                difference = exact_rate_difference(
                    native_numerator=native_numerator,
                    native_denominator=native_denominator,
                    canonical_numerator=canonical_numerator,
                    canonical_denominator=canonical_denominator,
                )

            draft = dict(
                ordinal=ordinal,
                observation_id=observation_id,
                scope=scope,
                native_numerator=native_numerator,
                native_denominator=native_denominator,
                canonical_numerator=canonical_numerator,
                canonical_denominator=canonical_denominator,
                difference_numerator=difference[0] if difference else None,
                difference_denominator=difference[1] if difference else None,
                comparability=comparability,
                policy_fingerprint=policy_fingerprint,
            )
            built.append(
                PairedRateObservation(
                    observation_hash=paired_rate_observation_hash(
                        _ObservationDraft(**draft)
                    ),
                    **draft,
                )
            )
            ordinal += 1
    return tuple(built)


class _ObservationDraft:
    __slots__ = (
        "ordinal",
        "observation_id",
        "scope",
        "native_numerator",
        "native_denominator",
        "canonical_numerator",
        "canonical_denominator",
        "difference_numerator",
        "difference_denominator",
        "comparability",
        "policy_fingerprint",
    )

    def __init__(self, **fields: object) -> None:
        for name in self.__slots__:
            setattr(self, name, fields[name])


def _observation_counts(
    *,
    observation_id: str,
    scope: MetricScopeRef,
    records: Sequence[PairedComparisonRecord],
    transitions: Sequence[SelfEligibilityTransitionRecord],
    common_eligible: Sequence[CommonEligibleMatedEntry],
) -> tuple[tuple[int, int, int, int], ComparabilityStatus]:
    """``(native_n, native_d, canonical_n, canonical_d)`` and whether they subtract."""
    if observation_id == "plain_self_attempt_match_fraction":
        return (
            _attempt_match(records, ProtocolStage.PLAIN_SELF, scope),
            ComparabilityStatus.DIRECTLY_COMPARABLE,
        )
    if observation_id == "roll_self_attempt_match_fraction":
        return (
            _attempt_match(records, ProtocolStage.ROLL_SELF, scope),
            ComparabilityStatus.DIRECTLY_COMPARABLE,
        )
    if observation_id == "negative_sanity_attempt_match_fraction":
        return (
            _attempt_match(records, ProtocolStage.PLAIN_ROLL_NON_MATED, scope),
            ComparabilityStatus.DIRECTLY_COMPARABLE,
        )
    if observation_id == "self_eligibility_fraction":
        total = sum(1 for item in transitions if _in_scope(item.release, scope))
        native = sum(
            1
            for item in transitions
            if _in_scope(item.release, scope) and item.native_status == "eligible"
        )
        canonical = sum(
            1
            for item in transitions
            if _in_scope(item.release, scope) and item.canonical_status == "eligible"
        )
        return (native, total, canonical, total), ComparabilityStatus.DIRECTLY_COMPARABLE
    if observation_id == "mated_unconditional_attempt_non_success_fraction":
        return (
            _attempt_non_success(records, ProtocolStage.PLAIN_ROLL_MATED, scope),
            ComparabilityStatus.DIRECTLY_COMPARABLE,
        )
    if observation_id == "mated_unconditional_decision_fnmr":
        counts, comparability = _decided_fnmr(
            records, ProtocolStage.PLAIN_ROLL_MATED, scope
        )
        return counts, comparability
    if observation_id == "common_eligible_selection_fraction":
        total = sum(1 for item in common_eligible if _in_scope(item.release, scope))
        included = sum(
            1
            for item in common_eligible
            if _in_scope(item.release, scope) and item.included
        )
        # The same numerator on both sides by construction: this rate describes
        # the *shared* population, and both runs contributed to defining it.
        return (
            included,
            total,
            included,
            total,
        ), ComparabilityStatus.DIRECTLY_COMPARABLE
    if observation_id == "common_eligible_mated_attempt_non_success_fraction":
        rows = [
            item
            for item in common_eligible
            if item.included and _in_scope(item.release, scope)
        ]
        total = len(rows)
        native = sum(
            1 for item in rows if item.native_outcome is not DecisionOutcome.MATCH
        )
        canonical = sum(
            1 for item in rows if item.canonical_outcome is not DecisionOutcome.MATCH
        )
        return (
            native,
            total,
            canonical,
            total,
        ), ComparabilityStatus.DIRECTLY_COMPARABLE
    if observation_id == "common_eligible_mated_decision_fnmr":
        rows = [
            item
            for item in common_eligible
            if item.included and _in_scope(item.release, scope)
        ]
        native_decided = [
            item
            for item in rows
            if item.native_outcome is not DecisionOutcome.UNDECIDABLE
        ]
        canonical_decided = [
            item
            for item in rows
            if item.canonical_outcome is not DecisionOutcome.UNDECIDABLE
        ]
        native_decided_ids = {str(item.pair_id) for item in native_decided}
        canonical_decided_ids = {str(item.pair_id) for item in canonical_decided}
        comparability = (
            ComparabilityStatus.DIRECTLY_COMPARABLE
            if native_decided_ids == canonical_decided_ids
            else ComparabilityStatus.SAME_ATTEMPTS_DIFFERENT_DECIDED_SUBSETS
        )
        return (
            sum(
                1
                for item in native_decided
                if item.native_outcome is DecisionOutcome.NON_MATCH
            ),
            len(native_decided),
            sum(
                1
                for item in canonical_decided
                if item.canonical_outcome is DecisionOutcome.NON_MATCH
            ),
            len(canonical_decided),
        ), comparability
    if observation_id == "per_run_conditional_mated_decision_fnmr":
        # Each run's own conditional FNMR, over *its own* eligible fingers. The
        # two denominators differ, so this is reported side by side and never as
        # a difference (spec section 41).
        native_rows = [
            item
            for item in common_eligible
            if _in_scope(item.release, scope)
            and item.native_eligibility_status == "eligible"
        ]
        canonical_rows = [
            item
            for item in common_eligible
            if _in_scope(item.release, scope)
            and item.canonical_eligibility_status == "eligible"
        ]
        native_decided = [
            item
            for item in native_rows
            if item.native_outcome is not DecisionOutcome.UNDECIDABLE
        ]
        canonical_decided = [
            item
            for item in canonical_rows
            if item.canonical_outcome is not DecisionOutcome.UNDECIDABLE
        ]
        return (
            sum(
                1
                for item in native_decided
                if item.native_outcome is DecisionOutcome.NON_MATCH
            ),
            len(native_decided),
            sum(
                1
                for item in canonical_decided
                if item.canonical_outcome is DecisionOutcome.NON_MATCH
            ),
            len(canonical_decided),
        ), ComparabilityStatus.DIFFERENT_SELECTION

    raise ValueError(f"unknown paired observation {observation_id!r}")


def _attempt_match(
    records: Sequence[PairedComparisonRecord],
    stage: ProtocolStage,
    scope: MetricScopeRef,
) -> tuple[int, int, int, int]:
    rows = [
        record
        for record in records
        if record.protocol_stage is stage and _in_scope(record.release, scope)
    ]
    total = len(rows)
    return (
        sum(1 for row in rows if row.native_outcome is DecisionOutcome.MATCH),
        total,
        sum(1 for row in rows if row.canonical_outcome is DecisionOutcome.MATCH),
        total,
    )


def _attempt_non_success(
    records: Sequence[PairedComparisonRecord],
    stage: ProtocolStage,
    scope: MetricScopeRef,
) -> tuple[int, int, int, int]:
    rows = [
        record
        for record in records
        if record.protocol_stage is stage and _in_scope(record.release, scope)
    ]
    total = len(rows)
    return (
        sum(1 for row in rows if row.native_outcome is not DecisionOutcome.MATCH),
        total,
        sum(1 for row in rows if row.canonical_outcome is not DecisionOutcome.MATCH),
        total,
    )


def _decided_fnmr(
    records: Sequence[PairedComparisonRecord],
    stage: ProtocolStage,
    scope: MetricScopeRef,
) -> tuple[tuple[int, int, int, int], ComparabilityStatus]:
    rows = [
        record
        for record in records
        if record.protocol_stage is stage and _in_scope(record.release, scope)
    ]
    native_decided = [
        row for row in rows if row.native_outcome is not DecisionOutcome.UNDECIDABLE
    ]
    canonical_decided = [
        row for row in rows if row.canonical_outcome is not DecisionOutcome.UNDECIDABLE
    ]
    native_decided_ids = {str(row.pair_id) for row in native_decided}
    canonical_decided_ids = {str(row.pair_id) for row in canonical_decided}
    comparability = (
        ComparabilityStatus.DIRECTLY_COMPARABLE
        if native_decided_ids == canonical_decided_ids
        else ComparabilityStatus.SAME_ATTEMPTS_DIFFERENT_DECIDED_SUBSETS
    )
    return (
        sum(
            1
            for row in native_decided
            if row.native_outcome is DecisionOutcome.NON_MATCH
        ),
        len(native_decided),
        sum(
            1
            for row in canonical_decided
            if row.canonical_outcome is DecisionOutcome.NON_MATCH
        ),
        len(canonical_decided),
    ), comparability
