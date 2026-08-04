"""Select only after every mandatory gate, then tier, then fixed tie breakers."""

from __future__ import annotations

from decimal import Decimal
from typing import Callable, Iterable, Sequence

from fpbench.core.errors import ModernMatcherSelectionError
from fpbench.core.modern_matcher_models import (
    STAGE8A_SCHEMA_VERSION,
    CandidateQualificationReport,
    DecisionPathKind,
    ModernMatcherCandidate,
    ModernMatcherCandidateRegistry,
    ModernMatcherSelectionDecision,
    RejectedCandidate,
    SelectionPolicy,
    SelectionState,
    Stage8AOutcome,
)
from fpbench.modern_matchers.policy import TIE_BREAKERS

__all__ = ["select_modern_matcher"]


def _uses_frozen_operational_limits(
    report: CandidateQualificationReport, policy: SelectionPolicy
) -> bool:
    operational = report.operational_report
    if not operational.measured:
        return False
    claimed_limits = (
        operational.max_projected_12000_extractions_seconds,
        operational.max_projected_6000_comparisons_seconds,
        operational.max_peak_ram_bytes,
        operational.max_peak_vram_bytes,
        operational.max_artifact_disk_bytes,
    )
    policy_limits = (
        policy.max_projected_12000_extractions_seconds,
        policy.max_projected_6000_comparisons_seconds,
        policy.max_peak_ram_bytes,
        policy.max_peak_vram_bytes,
        policy.max_artifact_disk_bytes,
    )
    if claimed_limits != policy_limits:
        return False
    return (
        Decimal(operational.projected_12000_extractions_seconds)
        <= Decimal(policy.max_projected_12000_extractions_seconds)
        and Decimal(operational.projected_6000_comparisons_seconds)
        <= Decimal(policy.max_projected_6000_comparisons_seconds)
        and operational.peak_ram_bytes <= policy.max_peak_ram_bytes
        and operational.peak_vram_bytes <= policy.max_peak_vram_bytes
        and operational.artifact_disk_bytes <= policy.max_artifact_disk_bytes
    )


def _tie_values(report: CandidateQualificationReport) -> tuple[object, ...]:
    preprocessing_is_general = bool(
        report.preprocessing_profile is not None
        and report.preprocessing_profile.dataset_independent
    )
    return (
        report.official_or_author_supplied,
        report.algorithm_completeness_rank,
        -report.external_components_required,
        report.decision_path.kind is DecisionPathKind.DOCUMENTED_CHECKPOINT_THRESHOLD,
        preprocessing_is_general,
        -report.runtime_complexity_rank,
        -report.estimated_adapter_lines,
        report.diversity_rank,
        report.paper_year,
    )


def _choose_one(
    reports: Sequence[CandidateQualificationReport],
    candidates: dict[str, ModernMatcherCandidate],
) -> CandidateQualificationReport:
    if not reports:
        raise ModernMatcherSelectionError("cannot choose from an empty candidate set")
    highest_tier = max(candidates[item.candidate_id].tier.priority for item in reports)
    finalists = [item for item in reports if candidates[item.candidate_id].tier.priority == highest_tier]
    if len(finalists) == 1:
        return finalists[0]
    remaining = list(finalists)
    for index in range(9):
        best = max(_tie_values(item)[index] for item in remaining)
        remaining = [item for item in remaining if _tie_values(item)[index] == best]
        if len(remaining) == 1:
            return remaining[0]
    raise ModernMatcherSelectionError(
        "the fixed nine tie breakers leave candidates tied; Stage 8A fails closed "
        "until a new selection policy fingerprint and ADR define another rule"
    )


def _rejection(
    report: CandidateQualificationReport,
    *,
    state: SelectionState,
    reason: str,
) -> RejectedCandidate:
    return RejectedCandidate.create(
        schema_version=STAGE8A_SCHEMA_VERSION,
        candidate_id=report.candidate_id,
        qualification_fingerprint=report.fingerprint,
        selection_state=state,
        gate_failures=report.exact_gate_failures,
        reason=reason,
    )


def select_modern_matcher(
    *,
    registry: ModernMatcherCandidateRegistry,
    reports: Sequence[CandidateQualificationReport],
    policy: SelectionPolicy,
    verifier_source_commit: str,
    decided_utc: str,
) -> ModernMatcherSelectionDecision:
    """Return one of the three Stage 8A outcomes without reading benchmark data."""
    if policy.tie_breakers != TIE_BREAKERS:
        raise ModernMatcherSelectionError(
            "the supplied policy does not name the fixed nine tie breakers used by the selector"
        )
    candidates = {item.candidate_id: item for item in registry.candidates}
    reports_by_id = {item.candidate_id: item for item in reports}
    if len(reports_by_id) != len(tuple(reports)):
        raise ModernMatcherSelectionError("each candidate must have exactly one qualification report")
    if set(reports_by_id) != set(candidates):
        raise ModernMatcherSelectionError(
            f"qualification reports must cover the frozen registry exactly; "
            f"missing={sorted(set(candidates) - set(reports_by_id))}, "
            f"extra={sorted(set(reports_by_id) - set(candidates))}"
        )
    for candidate_id, report in reports_by_id.items():
        candidate = candidates[candidate_id]
        if report.registry_fingerprint != registry.fingerprint:
            raise ModernMatcherSelectionError(f"{candidate_id}: qualification report names another registry")
        if report.candidate_fingerprint != candidate.fingerprint:
            raise ModernMatcherSelectionError(f"{candidate_id}: qualification report names another candidate identity")
        if report.raw_score_ready and not _uses_frozen_operational_limits(
            report, policy
        ):
            raise ModernMatcherSelectionError(
                f"{candidate_id}: raw readiness was not measured against the "
                "frozen operational limits"
            )

    decision_ready = [
        report
        for report in reports_by_id.values()
        if report.raw_score_ready
        and report.decision_path_ready
        and report.license_clear
        and report.architecture_fit
    ]
    raw_ready = [report for report in reports_by_id.values() if report.raw_score_ready]

    selected: CandidateQualificationReport | None = None
    raw_candidate: CandidateQualificationReport | None = None
    if decision_ready:
        selected = _choose_one(decision_ready, candidates)
        outcome = Stage8AOutcome.MODERN_MATCHER_SELECTED
    elif raw_ready:
        raw_candidate = _choose_one(raw_ready, candidates)
        outcome = Stage8AOutcome.QUALIFIED_FOR_RAW_SCORES_ONLY
    else:
        outcome = Stage8AOutcome.NO_MODERN_MATCHER_READY

    rejected: list[RejectedCandidate] = []
    for candidate_id in sorted(reports_by_id):
        report = reports_by_id[candidate_id]
        if selected is not None and report.candidate_id == selected.candidate_id:
            continue
        if raw_candidate is not None and report.candidate_id == raw_candidate.candidate_id:
            continue
        if report.exact_gate_failures:
            rejected.append(
                _rejection(
                    report,
                    state=SelectionState.REJECTED,
                    reason="one or more mandatory qualification gates failed",
                )
            )
        else:
            rejected.append(
                _rejection(
                    report,
                    state=SelectionState.REJECTED,
                    reason="all gates passed, but a higher-tier candidate passed the same gates",
                )
            )

    return ModernMatcherSelectionDecision.create(
        schema_version=STAGE8A_SCHEMA_VERSION,
        decision_id="stage8a_modern_matcher_selection_v1",
        outcome=outcome,
        registry_fingerprint=registry.fingerprint,
        candidate_qualification_fingerprints={
            candidate_id: reports_by_id[candidate_id].fingerprint
            for candidate_id in sorted(reports_by_id)
        },
        selected_candidate_id=selected.candidate_id if selected is not None else None,
        selected_artifact_fingerprint=(
            selected.artifact_manifest.fingerprint if selected is not None else None
        ),
        selected_score_profile_fingerprint=(
            selected.score_profile.fingerprint
            if selected is not None and selected.score_profile is not None
            else None
        ),
        raw_score_candidate_id=(
            selected.candidate_id
            if selected is not None
            else raw_candidate.candidate_id if raw_candidate is not None else None
        ),
        decision_path_kind=(
            selected.decision_path.kind if selected is not None else DecisionPathKind.NONE
        ),
        rejected_candidates=tuple(rejected),
        selection_policy_fingerprint=policy.fingerprint,
        verifier_source_commit=verifier_source_commit,
        decided_utc=decided_utc,
    )
