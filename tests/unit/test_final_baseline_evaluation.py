"""final-baseline reporting evaluation, ranking, context and rendering contracts."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import pytest

from fpbench.baseline_evaluation import (
    BaselinePopulation,
    EvaluationAttempt,
    evaluate_comparison_roster,
)
from fpbench.baseline_evaluation.policy import load_baseline_evaluation_policy
from fpbench.core.enums import ExecutionStatus, GroundTruth, ScoreDirection
from fpbench.final_baseline.constants import (
    EXPECTED_RELEASES,
    POLICY_PATH,
    POOLED_SCOPE,
    REPORTING_PATH,
)
from fpbench.final_baseline.evaluate import (
    far_target_cell,
    rank_algorithms,
    roster_view_documents,
)
from fpbench.final_baseline.report import render_final_baseline_report
from fpbench.final_baseline.reporting import load_final_baseline_reporting

pytestmark = pytest.mark.final_baseline_contract

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
RELEASES = EXPECTED_RELEASES
TARGETS = (Fraction(1, 100), Fraction(1, 1000), Fraction(1, 10000))


def _attempt(
    pair_id: str,
    release: str,
    population: BaselinePopulation,
    score: float | None,
) -> EvaluationAttempt:
    mated = population is BaselinePopulation.GENUINE
    return EvaluationAttempt(
        pair_id=pair_id,
        release=release,
        population=population,
        ground_truth=GroundTruth.MATED if mated else GroundTruth.NON_MATED,
        status=ExecutionStatus.SUCCESS if score is not None else ExecutionStatus.FAILURE,
        score=score,
    )


def _population(
    prefix: str, genuine_scores: dict[str, list[float | None]], impostor_scores: dict[str, list[float | None]]
) -> list[EvaluationAttempt]:
    attempts: list[EvaluationAttempt] = []
    for release, scores in genuine_scores.items():
        for index, score in enumerate(scores):
            attempts.append(
                _attempt(
                    f"{prefix}-gen-{release}-{index}",
                    release,
                    BaselinePopulation.GENUINE,
                    score,
                )
            )
    for release, scores in impostor_scores.items():
        for index, score in enumerate(scores):
            attempts.append(
                _attempt(
                    f"{prefix}-imp-{release}-{index}",
                    release,
                    BaselinePopulation.IMPOSTOR,
                    score,
                )
            )
    return attempts


def _shared_pair_scores(
    per_algorithm_scores: dict[str, tuple[dict, dict]]
) -> dict[str, list[EvaluationAttempt]]:
    """Build populations over the identical planned pair ids for every method."""
    result: dict[str, list[EvaluationAttempt]] = {}
    for algorithm_id, (genuine, impostor) in per_algorithm_scores.items():
        result[algorithm_id] = _population("shared", genuine, impostor)
    return result


def _small_roster() -> tuple[dict[str, list[EvaluationAttempt]], dict[str, ScoreDirection]]:
    genuine_a = {
        "SD300A": [50.0, 45.0, 12.0, None],
        "SD300B": [48.0, 40.0, 40.0, 7.0],
        "SD300C": [60.0, 55.0, 30.0, 20.0],
    }
    impostor_a = {
        "SD300A": [1.0, 2.0, 3.0, 41.0, 5.0, 6.0, 0.5, 0.25],
        "SD300B": [2.0, 2.0, 2.0, 4.0, 4.0, 9.0, 1.5, 0.75],
        "SD300C": [0.0, 1.0, 1.0, 2.0, 3.0, 5.0, 8.0, 39.0],
    }
    genuine_b = {
        "SD300A": [0.90, 0.80, 0.70, 0.10],
        "SD300B": [0.95, 0.85, 0.20, None],
        "SD300C": [0.99, 0.60, 0.55, 0.50],
    }
    impostor_b = {
        "SD300A": [0.05, 0.10, 0.10, 0.15, 0.20, 0.75, 0.02, 0.01],
        "SD300B": [0.03, 0.06, 0.09, 0.12, 0.18, 0.21, 0.24, 0.27],
        "SD300C": [0.02, 0.04, 0.06, 0.08, 0.30, 0.32, 0.34, 0.36],
    }
    attempts = _shared_pair_scores(
        {
            "alpha": (genuine_a, impostor_a),
            "beta": (genuine_b, impostor_b),
        }
    )
    directions = {
        "alpha": ScoreDirection.HIGHER_IS_BETTER,
        "beta": ScoreDirection.HIGHER_IS_BETTER,
    }
    return attempts, directions


def test_view_documents_agree_with_reference_composition() -> None:
    """The bounded-memory composition equals ``evaluate_comparison_roster``."""
    attempts, directions = _small_roster()
    reference = evaluate_comparison_roster(
        attempts,
        score_directions=directions,
        far_targets=TARGETS,
        releases=RELEASES,
    )
    views = roster_view_documents(
        attempts,
        score_directions=directions,
        far_targets=TARGETS,
        roster_order=("alpha", "beta"),
        membership_definition="pairs_scored_by_every_roster_method",
    )
    for view_name in ("primary_all_attempt", "secondary_common_score"):
        for algorithm_id in ("alpha", "beta"):
            for scope in (*RELEASES, POOLED_SCOPE):
                reference_points = reference[view_name][algorithm_id][
                    "far_targets"
                ][scope]
                document = views[view_name][algorithm_id]["scopes"][scope]
                assert document["far_targets"] == [
                    far_target_cell(point) for point in reference_points
                ]


def test_far_semantics_failures_and_ties() -> None:
    """Failures stay in denominators; a tie moves both impostor scores together."""
    attempts, directions = _small_roster()
    views = roster_view_documents(
        attempts,
        score_directions=directions,
        far_targets=TARGETS,
        roster_order=("alpha", "beta"),
        membership_definition="pairs_scored_by_every_roster_method",
    )
    pooled = views["primary_all_attempt"]["alpha"]["scopes"][POOLED_SCOPE]
    assert pooled["operational"]["genuine"]["planned_attempts"] == 12
    assert pooled["operational"]["genuine"]["algorithm_failures"] == 1
    assert pooled["operational"]["impostor"]["planned_attempts"] == 24
    # FAR <= 1/100 over 24 impostors means zero accepted impostors.
    strict = pooled["far_targets"][2]
    assert strict["requested_far"] == "1/10000"
    assert strict["far"]["numerator"] == 0
    # TAR denominators are planned attempts, so the failure is a permanent miss.
    assert strict["tar"]["denominator"] == 12


def test_rankings_order_by_tar_with_roster_tie_break() -> None:
    attempts, directions = _small_roster()
    views = roster_view_documents(
        attempts,
        score_directions=directions,
        far_targets=TARGETS,
        roster_order=("alpha", "beta"),
        membership_definition="pairs_scored_by_every_roster_method",
    )
    rankings = rank_algorithms(
        views, roster_order=("alpha", "beta"), far_targets=TARGETS
    )
    for scope in (*RELEASES, POOLED_SCOPE):
        for target in ("1/100", "1/1000", "1/10000"):
            ranked = rankings[scope][target]
            assert sorted(ranked) == ["alpha", "beta"]
            tars = []
            for algorithm_id in ranked:
                index = ("1/100", "1/1000", "1/10000").index(target)
                cell = views["primary_all_attempt"][algorithm_id]["scopes"][scope][
                    "far_targets"
                ][index]["tar"]
                tars.append(Fraction(cell["numerator"], cell["denominator"]))
            assert tars == sorted(tars, reverse=True)


def test_frozen_configs_load_and_carry_the_native_rules() -> None:
    policy = load_baseline_evaluation_policy(REPOSITORY_ROOT / POLICY_PATH)
    reporting = load_final_baseline_reporting(
        REPOSITORY_ROOT / REPORTING_PATH,
        roster_method_ids=policy.roster.method_ids,
    )
    assert reporting.primary_far_target == Fraction(1, 1000)
    assert reporting.scopes == (*RELEASES, POOLED_SCOPE)
    sourceafis = reporting.native_rule("sourceafis_java")
    assert sourceafis.exists
    assert sourceafis.accepts(40.0) and not sourceafis.accepts(39.999)
    nbis = reporting.native_rule("nbis_mindtct_bozorth3")
    assert nbis.exists
    assert nbis.accepts(40.001) and not nbis.accepts(40.0)
    for score_only in (
        "flx_deepprint_texminu_512_without_localization",
        "verifinger_1to1",
        "nbis_mindtct_mcc_sdk_v2",
        "nbis_mindtct_openafis_capacity_extended",
    ):
        assert not reporting.native_rule(score_only).exists


def test_report_renders_deterministically_with_disclosures() -> None:
    attempts, directions = _small_roster()
    policy = load_baseline_evaluation_policy(REPOSITORY_ROOT / POLICY_PATH)
    reporting = load_final_baseline_reporting(
        REPOSITORY_ROOT / REPORTING_PATH,
        roster_method_ids=policy.roster.method_ids,
    )
    views = roster_view_documents(
        attempts,
        score_directions=directions,
        far_targets=TARGETS,
        roster_order=("alpha", "beta"),
        membership_definition=reporting.secondary_view_membership,
    )
    rankings = rank_algorithms(
        views, roster_order=("alpha", "beta"), far_targets=TARGETS
    )
    results_document = {
        "comparison_id": "final_baseline_tar_far_frr_v1",
        "roster_id": "final_baseline_roster_v1",
        "report_id": reporting.report_id,
        "scopes": [*RELEASES, POOLED_SCOPE],
        "far_targets": ["1/100", "1/1000", "1/10000"],
        "primary_far_target": "1/1000",
        "ranking_rule": "highest TAR at or below the requested FAR",
        "views": views,
        "rankings": rankings,
    }
    inputs_document = {
        "stage21a_finalization_fingerprint": "a" * 64,
        "stage21b_finalization_fingerprint": "b" * 64,
        "genuine_population": "plain_roll_mated",
        "impostor_population": "plain_roll_cross_subject_non_mated",
        "methods": [
            {
                "algorithm_id": "alpha",
                "display_name": "Alpha Matcher",
                "role": "primary_baseline",
            },
            {
                "algorithm_id": "beta",
                "display_name": "Beta Matcher",
                "role": "additional_experimentally_evaluated_method",
            },
        ],
    }
    context_document = {
        "methods": {
            "alpha": {"rule": "score_greater_than_or_equal_to_40", "scopes": None},
            "beta": {"rule": "none", "scopes": None},
        }
    }
    first = render_final_baseline_report(
        inputs_document=inputs_document,
        results_document=results_document,
        context_document=context_document,
        reporting=reporting,
    )
    second = render_final_baseline_report(
        inputs_document=inputs_document,
        results_document=results_document,
        context_document=context_document,
        reporting=reporting,
    )
    assert first == second
    assert reporting.release_dependence_disclosure.splitlines()[0][:20] in first
    assert "Beta Matcher †" in first
    assert "no operational threshold" in first
    assert "not an average of release rates" in first
