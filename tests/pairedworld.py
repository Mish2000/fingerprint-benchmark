"""A synthetic pair of derivations, close enough to argue with.

Building two full chains — two runs, two result sets, two decision sets, two
eligibility sets — takes a workspace and a lot of ceremony. Doing it inline in
every test would bury the property each test is about, so it happens once here.

The world is deliberately small and structurally faithful: three releases, four
protocol stages, both SELF comparisons per finger, and a control release whose
two sides are identical by construction. Tests that want a *broken* world ask
for one — a changed score, a flipped decision, a missing pair — because the
interesting assertions are all about refusal.

Nothing here touches a store. The paired engine's inputs are two
:class:`~fpbench.paired.sources.PairedSide` objects, and this builds those
directly, which keeps the tests about the comparison rather than about parquet.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from types import SimpleNamespace
from typing import Mapping, Sequence

from fpbench.core.enums import (
    DecisionApplicationStatus,
    DecisionValue,
    ExecutionStatus,
    GroundTruth,
    ProtocolStage,
    ScoreDirection,
    SelfEligibilityReason,
    SelfEligibilityStatus,
)
from fpbench.core.identifiers import ImageId, PairId
from fpbench.core.models import ComparisonPair
from fpbench.core.serialization import stable_hash

__all__ = [
    "PairedWorld",
    "build_paired_world",
    "CONTROL_RELEASE",
    "RELEASES",
    "SUBJECTS",
    "FINGERS",
]

CONTROL_RELEASE = "SD300A"
RELEASES = ("SD300A", "SD300B", "SD300C")
SUBJECTS = 3
FINGERS = (1, 2)

_THRESHOLD = 40


def _digest(*parts: object) -> str:
    return stable_hash({"parts": [str(item) for item in parts]}, length=64)


@dataclass(frozen=True, slots=True)
class _Comparison:
    """One planned comparison, and both runs' scores for it."""

    pair_id: str
    release: str
    stage: ProtocolStage
    subject: str
    finger: int
    native_score: float | None
    canonical_score: float | None


@dataclass(frozen=True, slots=True)
class PairedWorld:
    native: object
    canonical: object
    comparisons: tuple[_Comparison, ...]

    @property
    def pair_ids(self) -> tuple[str, ...]:
        return tuple(item.pair_id for item in self.comparisons)


def _plan_comparisons(
    *,
    scores: Mapping[tuple[str, ProtocolStage], tuple[float | None, float | None]]
    | None = None,
) -> tuple[_Comparison, ...]:
    """The four stages over every release/subject/finger.

    Default scores are chosen so that the world has something to observe: the
    control release reproduces exactly, and the other two contain a handful of
    decisions that move in each direction.
    """
    chosen = dict(scores or {})
    built: list[_Comparison] = []
    for release in RELEASES:
        for subject_index in range(SUBJECTS):
            subject = f"s{subject_index + 1:04d}"
            for finger in FINGERS:
                slug = f"{release.lower()}_{subject}_f{finger:02d}"
                for stage, suffix, default in (
                    (ProtocolStage.PLAIN_SELF, "plainself", (90.0, 90.0)),
                    (ProtocolStage.ROLL_SELF, "rollself", (85.0, 85.0)),
                    (ProtocolStage.PLAIN_ROLL_MATED, "mated", (60.0, 60.0)),
                    (ProtocolStage.PLAIN_ROLL_NON_MATED, "nonmated", (5.0, 5.0)),
                ):
                    pair_id = f"{slug}_{suffix}"
                    native, canonical = chosen.get((pair_id, stage), default)
                    if release != CONTROL_RELEASE and stage in (
                        ProtocolStage.PLAIN_ROLL_MATED,
                        ProtocolStage.ROLL_SELF,
                    ):
                        # A little movement, so the transition matrices are not
                        # all diagonal and the exact-difference arithmetic is
                        # exercised on non-zero values.
                        if (pair_id, stage) not in chosen:
                            if finger == 1 and subject_index == 0:
                                native, canonical = 39.0, 41.0
                            elif finger == 2 and subject_index == 1:
                                native, canonical = 41.0, 39.0
                    built.append(
                        _Comparison(
                            pair_id=pair_id,
                            release=release,
                            stage=stage,
                            subject=subject,
                            finger=finger,
                            native_score=native,
                            canonical_score=canonical,
                        )
                    )
    return tuple(built)


def _pairs(comparisons: Sequence[_Comparison]) -> dict[PairId, ComparisonPair]:
    built: dict[PairId, ComparisonPair] = {}
    for item in comparisons:
        left = ImageId(f"{item.release.lower()}_{item.subject}_plain_f{item.finger:02d}")
        right = ImageId(f"{item.release.lower()}_{item.subject}_roll_f{item.finger:02d}")
        if item.stage is ProtocolStage.PLAIN_SELF:
            right = left
        elif item.stage is ProtocolStage.ROLL_SELF:
            left = right
        elif item.stage is ProtocolStage.PLAIN_ROLL_NON_MATED:
            other = FINGERS[(FINGERS.index(item.finger) + 1) % len(FINGERS)]
            right = ImageId(
                f"{item.release.lower()}_{item.subject}_roll_f{other:02d}"
            )
        built[PairId(item.pair_id)] = ComparisonPair(
            pair_id=PairId(item.pair_id),
            dataset_id="sd300",
            release=item.release,
            left_image_id=left,
            right_image_id=right,
            ground_truth=(
                GroundTruth.NON_MATED
                if item.stage is ProtocolStage.PLAIN_ROLL_NON_MATED
                else GroundTruth.MATED
            ),
            protocol_stage=item.stage,
        )
    return built


def _side(
    *,
    label: str,
    comparisons: Sequence[_Comparison],
    score_of,
    run_id: str,
    profile_id: str,
    decision_profile_id: str,
    job_salt: str,
):
    """One synthetic chain, shaped like what ``load_paired_side`` returns."""
    pairs = _pairs(comparisons)
    jobs = {
        item.pair_id: f"job_{_digest(job_salt, item.pair_id)[:16]}"
        for item in comparisons
    }

    results: dict[str, object] = {}
    decisions: list[object] = []
    for ordinal, item in enumerate(comparisons):
        job_id = jobs[item.pair_id]
        score = score_of(item)
        status = (
            ExecutionStatus.SUCCESS if score is not None else ExecutionStatus.FAILURE
        )
        result_hash = _digest(job_salt, item.pair_id, "result", score)
        results[job_id] = SimpleNamespace(
            status=status, raw_score=score, job_id=job_id
        )
        if score is None:
            application = DecisionApplicationStatus.UNDECIDABLE
            decision = None
        else:
            application = DecisionApplicationStatus.DECIDED
            decision = (
                DecisionValue.MATCH if score >= _THRESHOLD else DecisionValue.NON_MATCH
            )
        decisions.append(
            SimpleNamespace(
                ordinal=ordinal,
                job_id=job_id,
                pair_id=item.pair_id,
                source_result_hash=result_hash,
                application_status=application,
                decision=decision,
                decision_record_hash=_digest(
                    job_salt, item.pair_id, "decision", application, decision
                ),
            )
        )

    units, eligibility = _eligibility(
        comparisons=comparisons,
        jobs=jobs,
        decisions={record.job_id: record for record in decisions},
        job_salt=job_salt,
    )

    plan = SimpleNamespace(
        jobs=tuple(
            SimpleNamespace(
                job=SimpleNamespace(pair_id=item.pair_id, job_id=jobs[item.pair_id])
            )
            for item in comparisons
        ),
        total_jobs=len(comparisons),
    )
    run = SimpleNamespace(
        run_id=run_id,
        run_fingerprint=_digest("run", run_id),
        protocol_id="sd300_50_subjects",
        cohort_id="sd300_50_subjects_test_22f8d52a7478",
        pair_manifest_hash=_digest("pairs"),
        algorithm_fingerprint=_digest("algorithm"),
        algorithm=SimpleNamespace(
            algorithm_id="sourceafis_java",
            adapter_id="sourceafis_java_subprocess",
            adapter_version="1",
            implementation_version="3.18.1",
            score_direction=ScoreDirection.HIGHER_IS_BETTER,
        ),
        execution_profile=SimpleNamespace(profile_id=profile_id),
        environment=SimpleNamespace(
            dependencies={
                "bridge.jar.sha256": _digest("jar"),
                "runtime.bundle.fingerprint": _digest("bundle"),
            }
        ),
    )

    return SimpleNamespace(
        label=label,
        run=run,
        plan=plan,
        result_set=SimpleNamespace(
            result_set_id=f"resultset_{_digest('rs', run_id)[:12]}",
            result_set_fingerprint=_digest("resultset", run_id),
        ),
        pairs=pairs,
        pair_manifest_hash=_digest("pairs"),
        units=units,
        decision_profile=SimpleNamespace(
            profile_id=decision_profile_id,
            threshold="40",
            comparator=SimpleNamespace(value="greater_than_or_equal"),
            origin=SimpleNamespace(value="documented_native"),
            score_direction=SimpleNamespace(value="higher_is_better"),
            algorithm_fingerprint=_digest("algorithm"),
            calibration_performed=False,
        ),
        decision_manifest=SimpleNamespace(
            decision_set_id=f"decisionset_{_digest('ds', run_id)[:12]}",
            decision_set_fingerprint=_digest("decisionset", run_id),
            decision_profile_id=decision_profile_id,
        ),
        decision_records=tuple(decisions),
        eligibility_manifest=SimpleNamespace(
            eligibility_set_id=f"eligibilityset_{_digest('es', run_id)[:12]}",
            eligibility_set_fingerprint=_digest("eligibilityset", run_id),
        ),
        eligibility_records=tuple(eligibility),
        metric_manifest=SimpleNamespace(
            metric_set_id=f"metricset_{_digest('ms', run_id)[:12]}",
            metric_set_fingerprint=_digest("metricset", run_id),
            decision_set_id=f"decisionset_{_digest('ds', run_id)[:12]}",
        ),
        decision_status=None,
        research_status=None,
        result_store=SimpleNamespace(
            read_raw_result=lambda _run, job_id, _results=results: _results[job_id],
            run_id=run_id,
            has_research_receipt=lambda _run: False,
        ),
        jobs_by_pair=jobs,
        decisions_by_job={record.job_id: record for record in decisions},
        eligibility_by_unit={
            record.eligibility_unit_id: record for record in eligibility
        },
    )


def _eligibility(*, comparisons, jobs, decisions, job_salt):
    """One SELF unit per release/subject/finger, with the both-must-match rule."""
    units = []
    records = []
    keys = sorted(
        {(item.release, item.subject, item.finger) for item in comparisons}
    )
    for ordinal, (release, subject, finger) in enumerate(keys):
        slug = f"{release.lower()}_{subject}_f{finger:02d}"
        unit_id = f"unit_{_digest('unit', slug)[:16]}"
        plain_job = jobs[f"{slug}_plainself"]
        roll_job = jobs[f"{slug}_rollself"]
        mated_pair = f"{slug}_mated"

        plain = decisions[plain_job]
        roll = decisions[roll_job]
        status, reasons = _status_of(plain.decision, roll.decision)

        units.append(
            SimpleNamespace(
                eligibility_unit_id=unit_id,
                release=release,
                subject_id=subject,
                canonical_finger=finger,
                plain_self_job_id=plain_job,
                roll_self_job_id=roll_job,
                mated_pair_id=mated_pair,
            )
        )
        records.append(
            SimpleNamespace(
                ordinal=ordinal,
                eligibility_unit_id=unit_id,
                release=release,
                canonical_finger=finger,
                status=status,
                reasons=reasons,
                eligibility_record_hash=_digest(
                    job_salt, unit_id, status.value
                ),
            )
        )
    return tuple(units), tuple(records)


def _status_of(plain, roll):
    if plain is None or roll is None:
        return SelfEligibilityStatus.UNDETERMINED, (
            SelfEligibilityReason.PLAIN_SELF_UNDECIDABLE,
        )
    if plain is DecisionValue.MATCH and roll is DecisionValue.MATCH:
        return SelfEligibilityStatus.ELIGIBLE, (
            SelfEligibilityReason.BOTH_SELF_MATCH,
        )
    return SelfEligibilityStatus.INELIGIBLE, (
        SelfEligibilityReason.PLAIN_SELF_NON_MATCH,
    )


def build_paired_world(
    *,
    scores: Mapping[tuple[str, ProtocolStage], tuple[float | None, float | None]]
    | None = None,
    drop_canonical_pair: str | None = None,
    duplicate_canonical_pair: str | None = None,
    swap_canonical_sides: str | None = None,
) -> PairedWorld:
    """Two synthetic chains over the same comparisons.

    Args:
        scores: Override ``(native, canonical)`` for one ``(pair_id, stage)``.
            ``None`` on a side means that side produced no score.
        drop_canonical_pair: Remove a pair from the canonical plan, to exercise
            the alignment refusal.
        duplicate_canonical_pair: Plan a pair twice on the canonical side.
        swap_canonical_sides: Reverse left and right for one canonical pair.
    """
    comparisons = _plan_comparisons(scores=scores)

    native = _side(
        label="native",
        comparisons=comparisons,
        score_of=lambda item: item.native_score,
        run_id="run_nativesynth1",
        profile_id="native_identity_60s_v1",
        decision_profile_id="sourceafis_java_3_18_1_documented_40_v1",
        job_salt="native",
    )

    canonical_comparisons = comparisons
    if drop_canonical_pair is not None:
        canonical_comparisons = tuple(
            item for item in comparisons if item.pair_id != drop_canonical_pair
        )
    if duplicate_canonical_pair is not None:
        extra = next(
            item
            for item in comparisons
            if item.pair_id == duplicate_canonical_pair
        )
        canonical_comparisons = (*canonical_comparisons, extra)

    canonical = _side(
        label="canonical",
        comparisons=canonical_comparisons,
        score_of=lambda item: item.canonical_score,
        run_id="run_canonsynth1",
        profile_id="canonical_500_lanczos3_60s_v1",
        decision_profile_id="sourceafis_java_3_18_1_documented_40_canonical500_v1",
        job_salt="canonical",
    )

    if swap_canonical_sides is not None:
        pair = canonical.pairs[PairId(swap_canonical_sides)]
        canonical.pairs[PairId(swap_canonical_sides)] = replace(
            pair,
            left_image_id=pair.right_image_id,
            right_image_id=pair.left_image_id,
        )

    return PairedWorld(
        native=native, canonical=canonical, comparisons=comparisons
    )
