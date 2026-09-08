"""Assemble verified attempts and compute the frozen TAR/FAR/FRR report body.

The numeric semantics live in :mod:`fpbench.baseline_evaluation` — this module
only composes them, exactly the way ``evaluate_comparison_roster`` does, but one
algorithm and one view at a time so that a 441,000-attempt roster never holds
twelve full sweeps in memory at once.  A structural test asserts the two
compositions agree on the same inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Mapping, Sequence

from fpbench.baseline_evaluation.models import (
    BaselineEvaluationError,
    BaselinePopulation,
    EvaluationAttempt,
    FarTargetPoint,
    ScoreSweep,
)
from fpbench.baseline_evaluation.policy import (
    BaselineEvaluationPolicy,
    load_baseline_evaluation_policy,
)
from fpbench.baseline_evaluation.sweep import (
    build_scope_sweeps,
    common_score_population,
    select_far_target_point,
)
from fpbench.core.enums import ExecutionStatus, ScoreDirection
from fpbench.experiments.stage21a_finalization import verify_stage21a_evidence
from fpbench.stage21b.bindings import (
    Stage21ABinding,
    load_frozen_pairs,
    load_stage21a_binding,
    verify_legacy_manifest_unchanged,
)
from fpbench.stage21b.evidence import verify_stage21b_evidence
from fpbench.stage21b.integrity import discover_authoritative_run_directories
from fpbench.final_baseline.constants import (
    EXPECTED_METHODS,
    EXPECTED_RELEASES,
    POLICY_PATH,
    POOLED_SCOPE,
    REPORTING_PATH,
    COMPONENT,
    STAGE21A_MARKER_FINGERPRINT_KEY,
    STAGE21B_MARKER_FINGERPRINT_KEY,
)
from fpbench.final_baseline.errors import FinalBaselineError
from fpbench.final_baseline.hashing import normalized_text_sha256
from fpbench.final_baseline.reporting import (
    FinalBaselineReporting,
    load_final_baseline_reporting,
)
from fpbench.final_baseline.sources import (
    Stage21BImpostorSource,
    VerifiedMethodAttempts,
    load_legacy_genuine_attempts,
    load_legacy_mated_pairs,
    load_stage21b_impostor_attempts,
)

__all__ = [
    "FinalBaselineInputs",
    "FinalBaselineEvaluation",
    "collect_final_baseline_inputs",
    "evaluate_final_baseline",
    "far_target_cell",
    "rank_algorithms",
    "roster_view_documents",
]

_SCOPES = (*EXPECTED_RELEASES, POOLED_SCOPE)


@dataclass(frozen=True, slots=True)
class FinalBaselineInputs:
    repository_root: Path
    workspace: Path
    binding: Stage21ABinding
    policy: BaselineEvaluationPolicy
    reporting: FinalBaselineReporting
    stage21a_marker_fingerprint: str
    stage21b_marker_fingerprint: str
    cross_subject_pair_manifest_hash: str
    cross_subject_pair_ids_sha256: str
    legacy_invariance: Mapping[str, Any]
    methods: tuple[VerifiedMethodAttempts, ...]


@dataclass(frozen=True, slots=True)
class FinalBaselineEvaluation:
    inputs_document: dict[str, Any]
    results_document: dict[str, Any]
    context_document: dict[str, Any]
    summary: dict[str, Any]


def _sha256(path: Path) -> str:
    """Digest one frozen config with line endings normalised (see hashing.py)."""
    return normalized_text_sha256(path)


def _fraction_str(value: Fraction) -> str:
    return f"{value.numerator}/{value.denominator}"


def _rate(numerator: int, denominator: int) -> dict[str, int]:
    return {"numerator": int(numerator), "denominator": int(denominator)}


def far_target_cell(point: FarTargetPoint) -> dict[str, Any]:
    """Serialize one selected operating point, exactly and reproducibly."""
    observed = point.observed
    cut = observed.score_cut
    return {
        "requested_far": _fraction_str(point.requested_far),
        "boundary_kind": observed.boundary_kind.value,
        "score_cut": cut,
        "score_cut_hex": None if cut is None else float(cut).hex(),
        "comparator": observed.comparator,
        "tar": _rate(observed.tar.numerator, observed.tar.denominator),
        "far": _rate(observed.far.numerator, observed.far.denominator),
        "frr": _rate(observed.frr.numerator, observed.frr.denominator),
        "genuine_accepted": observed.genuine.accepted,
        "impostor_accepted": observed.impostor.accepted,
        "accepts_all_score_bearing": observed.accepts_all_score_bearing,
        "interpolation_performed": point.interpolation_performed,
    }


def collect_final_baseline_inputs(
    *, repository_root: Path, workspace: Path
) -> FinalBaselineInputs:
    """Verify both predecessor stages and load every score this report reads."""
    root = Path(repository_root).resolve()
    workspace = Path(workspace).resolve()

    stage21a_marker = verify_stage21a_evidence(root)
    stage21a_fingerprint = str(
        stage21a_marker.get(STAGE21A_MARKER_FINGERPRINT_KEY, "")
    )
    if not stage21a_fingerprint:
        raise FinalBaselineError("Stage 21A marker carries no finalization fingerprint")

    stage21b_marker = verify_stage21b_evidence(root)
    stage21b_fingerprint = str(
        stage21b_marker.get(STAGE21B_MARKER_FINGERPRINT_KEY, "")
    )
    if not stage21b_fingerprint:
        raise FinalBaselineError("Stage 21B marker carries no finalization fingerprint")

    policy = load_baseline_evaluation_policy(root / POLICY_PATH)
    reporting = load_final_baseline_reporting(
        root / REPORTING_PATH, roster_method_ids=policy.roster.method_ids
    )
    binding = load_stage21a_binding(root)
    if tuple(binding.algorithm_ids) != tuple(policy.roster.method_ids):
        raise FinalBaselineError(
            "the accepted Stage 21A roster and the frozen roster config disagree: "
            f"{binding.algorithm_ids} versus {policy.roster.method_ids}"
        )
    if len(binding.algorithms) != EXPECTED_METHODS:
        raise FinalBaselineError(
            f"roster carries {len(binding.algorithms)} methods, expected "
            f"{EXPECTED_METHODS}"
        )

    published_21b = _published_stage21b_methods(
        stage21b_marker, expected_algorithm_ids=binding.algorithm_ids
    )
    frozen = load_frozen_pairs(workspace=workspace, binding=binding)
    legacy_invariance = verify_legacy_manifest_unchanged(
        workspace=workspace, binding=binding
    )
    mated_pairs = load_legacy_mated_pairs(workspace)
    run_directories = discover_authoritative_run_directories(
        workspace, binding.algorithm_ids
    )

    methods: list[VerifiedMethodAttempts] = []
    for algorithm in binding.algorithms:
        genuine = load_legacy_genuine_attempts(workspace, algorithm, mated_pairs)
        impostor = load_stage21b_impostor_attempts(
            run_directories[algorithm.algorithm_id], algorithm, frozen
        )
        _require_published_stage21b_identity(
            impostor, published_21b[algorithm.algorithm_id]
        )
        methods.append(
            VerifiedMethodAttempts(
                algorithm_id=algorithm.algorithm_id,
                display_name=algorithm.display_name,
                role=algorithm.role,
                score_direction=ScoreDirection(algorithm.score_direction),
                genuine=genuine,
                impostor=impostor,
            )
        )

    return FinalBaselineInputs(
        repository_root=root,
        workspace=workspace,
        binding=binding,
        policy=policy,
        reporting=reporting,
        stage21a_marker_fingerprint=stage21a_fingerprint,
        stage21b_marker_fingerprint=stage21b_fingerprint,
        cross_subject_pair_manifest_hash=frozen.pair_manifest_hash,
        cross_subject_pair_ids_sha256=frozen.pair_ids_sha256,
        legacy_invariance=legacy_invariance,
        methods=tuple(methods),
    )


def _published_stage21b_methods(
    marker: Mapping[str, Any], *, expected_algorithm_ids: Sequence[str]
) -> dict[str, Mapping[str, Any]]:
    """Index the verified marker by algorithm, requiring the exact frozen roster."""
    methods = marker.get("methods")
    if not isinstance(methods, list):
        raise FinalBaselineError("Stage 21B publication methods must be a list")
    expected = set(expected_algorithm_ids)
    published: dict[str, Mapping[str, Any]] = {}
    for index, method in enumerate(methods):
        if not isinstance(method, Mapping):
            raise FinalBaselineError(
                f"Stage 21B publication method entry {index} must be a mapping"
            )
        algorithm_id = method.get("algorithm_id")
        if not isinstance(algorithm_id, str) or not algorithm_id.strip():
            raise FinalBaselineError(
                f"Stage 21B publication method entry {index}: "
                "algorithm_id must be a non-empty string"
            )
        if algorithm_id not in expected:
            raise FinalBaselineError(
                f"{algorithm_id}: unexpected algorithm_id in Stage 21B publication"
            )
        if algorithm_id in published:
            raise FinalBaselineError(
                f"{algorithm_id}: duplicate algorithm_id in Stage 21B publication"
            )
        for key in ("run_id", "result_set_id", "result_set_fingerprint"):
            value = method.get(key)
            if not isinstance(value, str) or not value.strip():
                raise FinalBaselineError(
                    f"{algorithm_id}: Stage 21B publication {key} "
                    "must be a non-empty string"
                )
        published[algorithm_id] = method
    missing = sorted(expected - set(published))
    if missing:
        raise FinalBaselineError(
            f"{', '.join(missing)}: missing algorithm_id entry in Stage 21B publication"
        )
    return published


def _require_published_stage21b_identity(
    source: Stage21BImpostorSource, published: Mapping[str, Any]
) -> None:
    """Bind all four sealed identity fields to the same published method entry."""
    for key in ("algorithm_id", "run_id", "result_set_id", "result_set_fingerprint"):
        if getattr(source, key) != published[key]:
            raise FinalBaselineError(
                f"{published['algorithm_id']}: sealed Stage 21B {key} does not "
                "match the verified Stage 21B publication"
            )


def _view_for_algorithm(
    attempts: Sequence[EvaluationAttempt],
    *,
    score_direction: ScoreDirection,
    far_targets: Sequence[Fraction],
) -> dict[str, Any]:
    sweeps = build_scope_sweeps(
        attempts, score_direction=score_direction, releases=EXPECTED_RELEASES
    )
    scopes: dict[str, Any] = {}
    for scope in _SCOPES:
        sweep: ScoreSweep = sweeps[scope]
        first = sweep.points[0]
        scopes[scope] = {
            "operational": {
                "genuine": {
                    "planned_attempts": first.genuine.operational.planned_attempts,
                    "score_bearing_attempts": (
                        first.genuine.operational.score_bearing_attempts
                    ),
                    "algorithm_failures": (
                        first.genuine.operational.algorithm_failures
                    ),
                },
                "impostor": {
                    "planned_attempts": first.impostor.operational.planned_attempts,
                    "score_bearing_attempts": (
                        first.impostor.operational.score_bearing_attempts
                    ),
                    "algorithm_failures": (
                        first.impostor.operational.algorithm_failures
                    ),
                },
            },
            "unique_score_cuts": len(sweep.points) - 1,
            "far_targets": [
                far_target_cell(select_far_target_point(sweep, target))
                for target in far_targets
            ],
        }
    return {"scopes": scopes}


def _counts(attempts: Sequence[EvaluationAttempt]) -> dict[str, int]:
    genuine = [a for a in attempts if a.population is BaselinePopulation.GENUINE]
    impostor = [a for a in attempts if a.population is BaselinePopulation.IMPOSTOR]
    return {
        "genuine_pairs": len(genuine),
        "impostor_pairs": len(impostor),
    }


def _native_rule_counts(
    attempts: Sequence[EvaluationAttempt], accepts: Any
) -> dict[str, Any]:
    scopes: dict[str, Any] = {}
    for scope in _SCOPES:
        rows = [
            attempt
            for attempt in attempts
            if scope == POOLED_SCOPE or attempt.release == scope
        ]
        genuine = [a for a in rows if a.population is BaselinePopulation.GENUINE]
        impostor = [a for a in rows if a.population is BaselinePopulation.IMPOSTOR]
        genuine_accepted = sum(
            a.status is ExecutionStatus.SUCCESS and accepts(a.score)
            for a in genuine
        )
        impostor_accepted = sum(
            a.status is ExecutionStatus.SUCCESS and accepts(a.score)
            for a in impostor
        )
        scopes[scope] = {
            "tar": _rate(genuine_accepted, len(genuine)),
            "frr": _rate(len(genuine) - genuine_accepted, len(genuine)),
            "far": _rate(impostor_accepted, len(impostor)),
        }
    return scopes


def roster_view_documents(
    attempts_by_algorithm: Mapping[str, Sequence[EvaluationAttempt]],
    *,
    score_directions: Mapping[str, ScoreDirection],
    far_targets: Sequence[Fraction],
    roster_order: Sequence[str],
    membership_definition: str,
) -> dict[str, Any]:
    """Compute both frozen views, one algorithm and one view at a time.

    This is ``evaluate_comparison_roster``'s composition with bounded memory;
    a unit test asserts the two agree on identical inputs.  A refusal in the
    primary view is fatal; in the secondary view it is recorded, because a
    release every method failed is a fact about the data, not a reason to
    withhold the primary result.
    """
    # ``common_score_population`` also validates that every method covers the
    # identical planned pair population — the same alignment gate
    # ``evaluate_comparison_roster`` runs first.
    common = common_score_population(attempts_by_algorithm)

    views: dict[str, Any] = {}
    for view_name, populations in (
        ("primary_all_attempt", attempts_by_algorithm),
        ("secondary_common_score", common),
    ):
        per_algorithm: dict[str, Any] = {}
        for algorithm_id in roster_order:
            attempts = populations[algorithm_id]
            try:
                per_algorithm[algorithm_id] = _view_for_algorithm(
                    attempts,
                    score_direction=score_directions[algorithm_id],
                    far_targets=far_targets,
                )
            except BaselineEvaluationError as error:
                if view_name == "primary_all_attempt":
                    raise FinalBaselineError(
                        f"{algorithm_id}: the primary view cannot be evaluated: "
                        f"{error}"
                    ) from error
                per_algorithm[algorithm_id] = {"unavailable": str(error)}
        views[view_name] = per_algorithm
    views["secondary_common_score_membership"] = {
        "definition": membership_definition,
        **_counts(next(iter(common.values()))),
    }
    return views


def rank_algorithms(
    views: Mapping[str, Any],
    *,
    roster_order: Sequence[str],
    far_targets: Sequence[Fraction],
) -> dict[str, Any]:
    """Order methods by observed TAR at each target; ties keep roster order."""
    order = list(roster_order)
    rankings: dict[str, Any] = {}
    for scope in _SCOPES:
        rankings[scope] = {}
        for index, target in enumerate(far_targets):
            def tar_of(algorithm_id: str, index: int = index, scope: str = scope) -> Fraction:
                cell = views["primary_all_attempt"][algorithm_id]["scopes"][scope][
                    "far_targets"
                ][index]["tar"]
                return Fraction(cell["numerator"], cell["denominator"])

            ordered = sorted(
                order,
                key=lambda algorithm_id: (
                    -tar_of(algorithm_id),
                    order.index(algorithm_id),
                ),
            )
            rankings[scope][_fraction_str(target)] = list(ordered)
    return rankings


def evaluate_final_baseline(inputs: FinalBaselineInputs) -> FinalBaselineEvaluation:
    """Compute both frozen views, the rankings and the contextual rule table."""
    policy = inputs.policy
    reporting = inputs.reporting
    roster_order = tuple(method.algorithm_id for method in inputs.methods)

    attempts_by_algorithm = {
        method.algorithm_id: method.attempts for method in inputs.methods
    }
    directions = {
        method.algorithm_id: method.score_direction for method in inputs.methods
    }

    views = roster_view_documents(
        attempts_by_algorithm,
        score_directions=directions,
        far_targets=policy.far_targets,
        roster_order=roster_order,
        membership_definition=reporting.secondary_view_membership,
    )
    rankings = rank_algorithms(
        views, roster_order=roster_order, far_targets=policy.far_targets
    )

    results_document = {
        "kind": "final_baseline_tar_far_frr_results",
        "component": COMPONENT,
        "comparison_id": policy.comparison_id,
        "roster_id": policy.roster.roster_id,
        "report_id": reporting.report_id,
        "releases": list(EXPECTED_RELEASES),
        "scopes": list(_SCOPES),
        "far_targets": [_fraction_str(target) for target in policy.far_targets],
        "primary_far_target": _fraction_str(policy.primary_far_target),
        "ranking_rule": (
            "highest TAR at or below the requested FAR, ties resolved by frozen "
            "roster order; primary view, all planned attempts"
        ),
        "views": views,
        "rankings": rankings,
    }

    context_document = {
        "kind": "final_baseline_native_documented_rules_context",
        "component": COMPONENT,
        "purpose": "separate_context_table_only",
        "direct_cross_algorithm_ranking": "forbidden",
        "methods": {
            method.algorithm_id: (
                {
                    "rule": inputs.reporting.native_rule(method.algorithm_id).rule,
                    "scopes": _native_rule_counts(
                        method.attempts,
                        inputs.reporting.native_rule(method.algorithm_id).accepts,
                    ),
                }
                if inputs.reporting.native_rule(method.algorithm_id).exists
                else {
                    "rule": inputs.reporting.native_rule(method.algorithm_id).rule,
                    "scopes": None,
                }
            )
            for method in inputs.methods
        },
    }

    inputs_document = _inputs_document(inputs)

    primary_key = _fraction_str(policy.primary_far_target)
    summary = {
        "component": COMPONENT,
        "primary_far_target": primary_key,
        "pooled_primary_ranking": [
            {
                "algorithm_id": algorithm_id,
                "tar": views["primary_all_attempt"][algorithm_id]["scopes"][
                    POOLED_SCOPE
                ]["far_targets"][_target_index(policy, policy.primary_far_target)][
                    "tar"
                ],
            }
            for algorithm_id in rankings[POOLED_SCOPE][primary_key]
        ],
    }

    return FinalBaselineEvaluation(
        inputs_document=inputs_document,
        results_document=results_document,
        context_document=context_document,
        summary=summary,
    )


def _target_index(policy: BaselineEvaluationPolicy, target: Fraction) -> int:
    for index, candidate in enumerate(policy.far_targets):
        if candidate == target:
            return index
    raise FinalBaselineError(f"FAR target {target} is not in the frozen policy")


def _inputs_document(inputs: FinalBaselineInputs) -> dict[str, Any]:
    root = inputs.repository_root
    return {
        "kind": "final_baseline_evaluation_inputs",
        "component": COMPONENT,
        "comparison_id": inputs.policy.comparison_id,
        "roster_id": inputs.policy.roster.roster_id,
        "report_id": inputs.reporting.report_id,
        "stage21a_finalization_fingerprint": inputs.stage21a_marker_fingerprint,
        "stage21b_finalization_fingerprint": inputs.stage21b_marker_fingerprint,
        "legacy_pair_manifest_hash": str(
            inputs.binding.legacy_pair_manifest_hash
        ),
        "legacy_manifest_invariance": dict(inputs.legacy_invariance),
        "cross_subject_pair_manifest_hash": inputs.cross_subject_pair_manifest_hash,
        "cross_subject_pair_ids_sha256": inputs.cross_subject_pair_ids_sha256,
        "genuine_population": inputs.policy.genuine_population,
        "impostor_population": inputs.policy.impostor_population,
        "config_digests": {
            "policy": _sha256(root / POLICY_PATH),
            "roster": _sha256(inputs.policy.roster_config),
            "reporting": _sha256(root / REPORTING_PATH),
        },
        "methods": [
            {
                "algorithm_id": method.algorithm_id,
                "display_name": method.display_name,
                "role": method.role,
                "score_direction": method.score_direction.value,
                "legacy_genuine": {
                    "run_id": method.genuine.run_id,
                    "run_fingerprint": method.genuine.run_fingerprint,
                    "result_set_id": method.genuine.result_set_id,
                    "result_set_fingerprint": (
                        method.genuine.result_set_fingerprint
                    ),
                    "record_algorithm_id": method.genuine.record_algorithm_id,
                    "record_algorithm_fingerprint": (
                        method.genuine.record_algorithm_fingerprint
                    ),
                    "planned_attempts": method.genuine.planned_attempts,
                    "score_bearing_attempts": (
                        method.genuine.score_bearing_attempts
                    ),
                    "algorithm_failures": method.genuine.algorithm_failures,
                },
                "stage21b_impostor": {
                    "run_id": method.impostor.run_id,
                    "result_set_id": method.impostor.result_set_id,
                    "result_set_fingerprint": (
                        method.impostor.result_set_fingerprint
                    ),
                    "seal_fingerprint": method.impostor.seal_fingerprint,
                    "planned_attempts": method.impostor.planned_attempts,
                    "score_bearing_attempts": (
                        method.impostor.score_bearing_attempts
                    ),
                    "algorithm_failures": method.impostor.algorithm_failures,
                },
            }
            for method in inputs.methods
        ],
    }
