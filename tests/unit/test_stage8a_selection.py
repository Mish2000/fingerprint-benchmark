from __future__ import annotations

import pytest

from fpbench.core.errors import ModernMatcherSelectionError
from fpbench.core.modern_matcher_models import (
    CandidateTier,
    DecisionPathKind,
    ImplementationOrigin,
    Stage8AOutcome,
)
from fpbench.modern_matchers.selection import select_modern_matcher
from stage8aworld import (
    COMMIT,
    NOW,
    make_blocked_report,
    make_candidate,
    make_facts,
    make_decision_path,
    make_policy,
    make_operational,
    make_raw_only_report,
    make_registry,
    make_report,
    rebuild,
)

pytestmark = pytest.mark.stage8a_contract


def _select(registry, reports):
    return select_modern_matcher(
        registry=registry,
        reports=reports,
        policy=make_policy(),
        verifier_source_commit=COMMIT,
        decided_utc=NOW,
    )


def test_gate_failure_beats_tier_and_a_complete_tier_c_candidate_is_selected() -> None:
    candidates = (
        make_candidate("candidate_a", tier=CandidateTier.A),
        make_candidate("candidate_b", tier=CandidateTier.B),
        make_candidate("candidate_c", tier=CandidateTier.C),
    )
    registry = make_registry(candidates)
    reports = (
        make_blocked_report(candidates[0], registry),
        make_raw_only_report(candidates[1], registry),
        make_report(candidates[2], registry),
    )

    decision = _select(registry, reports)
    assert decision.outcome is Stage8AOutcome.MODERN_MATCHER_SELECTED
    assert decision.selected_candidate_id == "candidate_c"
    assert decision.raw_score_candidate_id == "candidate_c"


def test_tier_precedes_every_tie_breaker_once_gates_pass() -> None:
    high = make_candidate(
        "candidate_high", tier=CandidateTier.A,
        origin=ImplementationOrigin.INDEPENDENT_REIMPLEMENTATION,
    )
    low = make_candidate("candidate_low", tier=CandidateTier.C)
    registry = make_registry((high, low))
    high_report = make_report(
        high,
        registry,
        facts=make_facts(
            algorithm_completeness_rank=1,
            external_components_required=99,
            runtime_complexity_rank=99,
            estimated_adapter_lines=9999,
            diversity_rank=0,
            paper_year=2000,
        ),
    )
    low_report = make_report(low, registry)

    assert _select(registry, (high_report, low_report)).selected_candidate_id == (
        high.candidate_id
    )


def test_official_origin_is_the_first_same_tier_tie_breaker() -> None:
    official = make_candidate("candidate_official", tier=CandidateTier.A)
    independent = make_candidate(
        "candidate_independent",
        tier=CandidateTier.A,
        origin=ImplementationOrigin.INDEPENDENT_REIMPLEMENTATION,
    )
    registry = make_registry((official, independent))

    decision = _select(
        registry,
        (
            make_report(official, registry),
            make_report(independent, registry),
        ),
    )
    assert decision.selected_candidate_id == official.candidate_id


def test_an_exact_same_tier_tie_fails_closed() -> None:
    left = make_candidate("candidate_left", tier=CandidateTier.A)
    right = make_candidate("candidate_right", tier=CandidateTier.A)
    registry = make_registry((left, right))

    with pytest.raises(ModernMatcherSelectionError, match="nine tie breakers"):
        _select(
            registry,
            (make_report(left, registry), make_report(right, registry)),
        )


def test_raw_score_only_is_a_distinct_outcome_with_no_selected_integration() -> None:
    candidate = make_candidate()
    registry = make_registry((candidate,))
    decision = _select(registry, (make_raw_only_report(candidate, registry),))

    assert decision.outcome is Stage8AOutcome.QUALIFIED_FOR_RAW_SCORES_ONLY
    assert decision.selected_candidate_id is None
    assert decision.selected_artifact_fingerprint is None
    assert decision.selected_score_profile_fingerprint is None
    assert decision.raw_score_candidate_id == candidate.candidate_id
    assert decision.rejected_candidates == ()


def test_no_ready_candidate_does_not_activate_the_reserve() -> None:
    candidate = make_candidate()
    registry = make_registry((candidate,))
    decision = _select(registry, (make_blocked_report(candidate, registry),))

    assert decision.outcome is Stage8AOutcome.NO_MODERN_MATCHER_READY
    assert decision.selected_candidate_id is None
    assert decision.raw_score_candidate_id is None
    assert "id3" not in str(decision).lower()


def test_selection_requires_one_report_for_every_registry_candidate() -> None:
    candidates = (
        make_candidate("candidate_a", tier=CandidateTier.A),
        make_candidate("candidate_b", tier=CandidateTier.B),
    )
    registry = make_registry(candidates)

    with pytest.raises(ModernMatcherSelectionError, match="cover.*exactly"):
        _select(registry, (make_report(candidates[0], registry),))


def test_selection_rejects_duplicate_candidate_reports() -> None:
    candidate = make_candidate()
    registry = make_registry((candidate,))
    report = make_report(candidate, registry)

    with pytest.raises(ModernMatcherSelectionError, match="exactly one"):
        _select(registry, (report, report))


@pytest.mark.parametrize(
    ("field", "preferred", "other"),
    [
        ("algorithm_completeness_rank", 101, 100),
        ("external_components_required", 0, 1),
        ("runtime_complexity_rank", 0, 1),
        ("estimated_adapter_lines", 9, 10),
        ("diversity_rank", 6, 5),
        ("paper_year", 2026, 2025),
    ],
)
def test_each_numeric_tie_breaker_is_applied_in_the_frozen_direction(
    field: str,
    preferred: int,
    other: int,
) -> None:
    candidates = (
        make_candidate("candidate_preferred", tier=CandidateTier.A),
        make_candidate("candidate_other", tier=CandidateTier.A),
    )
    registry = make_registry(candidates)
    preferred_report = make_report(
        candidates[0],
        registry,
        facts=make_facts(**{field: preferred}),
    )
    other_report = make_report(
        candidates[1],
        registry,
        facts=make_facts(**{field: other}),
    )

    assert _select(
        registry,
        (preferred_report, other_report),
    ).selected_candidate_id == candidates[0].candidate_id


def test_checkpoint_bound_threshold_precedes_external_calibration() -> None:
    candidates = (
        make_candidate("candidate_checkpoint", tier=CandidateTier.A),
        make_candidate("candidate_calibrated", tier=CandidateTier.A),
    )
    registry = make_registry(candidates)
    checkpoint = make_report(candidates[0], registry)
    calibrated = make_report(
        candidates[1],
        registry,
        decision_path=make_decision_path(
            DecisionPathKind.EXTERNAL_DEVELOPMENT_CALIBRATION
        ),
    )

    assert _select(
        registry,
        (checkpoint, calibrated),
    ).selected_candidate_id == candidates[0].candidate_id


def test_selector_rejects_a_policy_that_does_not_name_its_actual_order() -> None:
    candidate = make_candidate()
    registry = make_registry((candidate,))
    report = make_report(candidate, registry)
    policy = make_policy()
    altered = rebuild(
        policy,
        tie_breakers=(
            policy.tie_breakers[1],
            policy.tie_breakers[0],
            *policy.tie_breakers[2:],
        ),
    )

    with pytest.raises(ModernMatcherSelectionError, match="fixed nine"):
        select_modern_matcher(
            registry=registry,
            reports=(report,),
            policy=altered,
            verifier_source_commit=COMMIT,
            decided_utc=NOW,
        )


def test_selector_rejects_ready_claims_measured_against_looser_limits() -> None:
    candidate = make_candidate()
    registry = make_registry((candidate,))
    operational = rebuild(
        make_operational(),
        max_projected_12000_extractions_seconds="999999",
        max_projected_6000_comparisons_seconds="999999",
        max_peak_ram_bytes=999_999_999_999,
        max_peak_vram_bytes=999_999_999_999,
        max_artifact_disk_bytes=999_999_999_999,
    )
    report = make_report(candidate, registry, operational=operational)

    with pytest.raises(ModernMatcherSelectionError, match="frozen operational"):
        _select(registry, (report,))
