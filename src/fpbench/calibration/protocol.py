"""Constructing a frozen calibration artifact from its parts.

Every artifact in this package validates its own fingerprint in
``__post_init__``, which means none of them can be built by constructing it and
then hashing it. The fingerprint has to be computed from the *parts*, before the
object exists — and the parts have to be normalised exactly as the object will
normalise them, or the object will refuse the fingerprint that was just computed
for it.

That refusal is the design, not an obstacle. It means these builders cannot
drift from the models they build: a normalisation added on one side and forgotten
on the other fails immediately and loudly, at construction, rather than producing
an artifact whose identity quietly means something else.

The alternative — a mutable escape hatch on the models — would remove the check
that makes a stored fingerprint worth reading.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Iterable, Mapping

from fpbench.core.calibration_errors import CalibrationProtocolError
from fpbench.core.calibration_models import (
    CALIBRATION_OPERATING_POINT_SCHEMA_VERSION,
    CALIBRATION_PROTOCOL_SCHEMA_VERSION,
    CALIBRATION_SOURCE_BINDING_SCHEMA_VERSION,
    PROTECTED_REGISTRY_SCHEMA_VERSION,
    CalibrationOperatingPoint,
    CalibrationProtocol,
    CalibrationSourceBinding,
    ExactRate,
    ProtectedEvaluationIdentity,
    ProtectedEvaluationRegistry,
    calibration_operating_point_fingerprint,
    calibration_protocol_fingerprint,
    calibration_source_binding_fingerprint,
    operating_point_id,
    protected_evaluation_registry_fingerprint,
)
from fpbench.core.decision_models import canonical_threshold
from fpbench.core.enums import (
    CalibrationFailurePolicy,
    CalibrationTargetMetric,
    CalibrationTargetPopulation,
    CalibrationTiePolicy,
    CandidateBoundaryPolicy,
    CohortRole,
    ScoreDirection,
    ScoreNormalizationPolicy,
    ScorePopulationPolicy,
    ThresholdComparator,
    ThresholdSelectionRule,
)
from fpbench.calibration.models import LabeledResults

__all__ = [
    "build_calibration_protocol",
    "build_calibration_source_binding",
    "build_protected_evaluation_registry",
    "build_calibration_operating_point",
    "impostor_ceiling_protocol",
    "V1_POLICY",
]

#: The one set of policy values a v1 protocol may hold. Stated once, here, so
#: that a caller building a protocol cannot accidentally assemble a policy this
#: project does not implement — and so that the *fixed* parts of a protocol are
#: visibly separate from the two a study actually chooses: the target rate and
#: the protocol's own name (docs/adr/0080).
V1_POLICY: Mapping[str, Any] = {
    "target_metric": CalibrationTargetMetric.IMPOSTOR_MATCH_RATE,
    "target_population": CalibrationTargetPopulation.SCORED_COMPARISONS,
    "threshold_selection_rule": (
        ThresholdSelectionRule.MOST_PERMISSIVE_WITHIN_IMPOSTOR_CEILING
    ),
    "candidate_boundary_policy": CandidateBoundaryPolicy.OBSERVED_SCORE_BOUNDARIES,
    "tie_policy": CalibrationTiePolicy.ATOMIC_TIES_PREFER_INCLUSIVE,
    "score_population_policy": ScorePopulationPolicy.SUCCESSFUL_FINITE_SCORES_ONLY,
    "failure_policy": CalibrationFailurePolicy.FAILURES_EXCLUDED_AND_COUNTED,
    "requires_cross_subject_impostors": True,
    "requires_development_role": True,
    "quality_filtering": False,
    "normalization": ScoreNormalizationPolicy.NONE,
}


def _normalised_metadata(metadata: Mapping[str, str] | None) -> dict[str, str]:
    return {str(key): str(value) for key, value in dict(metadata or {}).items()}


def _digest(value: str) -> str:
    return str(value).strip().lower()


# -------------------------------------------------------------------- protocol


def build_calibration_protocol(
    *,
    protocol_id: str,
    protocol_version: str,
    target_rate_numerator: int,
    target_rate_denominator: int,
    metadata: Mapping[str, str] | None = None,
    **policy: Any,
) -> CalibrationProtocol:
    """Seal a protocol around a target rate and the v1 policy.

    ``policy`` overrides exist so a test can build a protocol this project would
    refuse and prove that it is refused. Nothing else should pass them: a
    protocol assembled out of a policy the selector does not implement would
    describe a study nobody could run.
    """
    fields: dict[str, Any] = dict(V1_POLICY)
    unknown = sorted(set(policy) - set(V1_POLICY))
    if unknown:
        raise CalibrationProtocolError(
            f"a calibration protocol has no {unknown} to set; the policy is fixed "
            "and a new knob is a new protocol version"
        )
    fields.update(policy)

    rate = ExactRate(
        numerator=target_rate_numerator, denominator=target_rate_denominator
    )
    fields.update(
        schema_version=CALIBRATION_PROTOCOL_SCHEMA_VERSION,
        protocol_id=str(protocol_id).strip(),
        protocol_version=str(protocol_version).strip(),
        target_rate_numerator=rate.numerator,
        target_rate_denominator=rate.denominator,
        metadata=_normalised_metadata(metadata),
    )
    fingerprint = calibration_protocol_fingerprint(fields)
    return CalibrationProtocol(protocol_fingerprint=fingerprint, **fields)


def impostor_ceiling_protocol(
    *,
    protocol_id: str,
    protocol_version: str = "1",
    numerator: int,
    denominator: int,
    metadata: Mapping[str, str] | None = None,
) -> CalibrationProtocol:
    """The v1 protocol, named by the ceiling it puts on impostor matches.

    Reads at the call site the way the policy reads in prose: *find the most
    permissive boundary whose observed impostor match rate does not exceed
    ``numerator/denominator``*. The number itself is a study's choice, and Stage
    8D makes it only for synthetic fixtures (docs/adr/0078).
    """
    return build_calibration_protocol(
        protocol_id=protocol_id,
        protocol_version=protocol_version,
        target_rate_numerator=numerator,
        target_rate_denominator=denominator,
        metadata=metadata,
    )


# -------------------------------------------------------------- source binding


def _seal_calibration_source_binding(
    *,
    binding_id: str,
    algorithm_id: str,
    algorithm_fingerprint: str,
    integration_id: str,
    integration_fingerprint: str,
    run_id: str,
    run_fingerprint: str,
    result_set_id: str,
    result_set_fingerprint: str,
    dataset_id: str,
    dataset_fingerprint: str,
    cohort_id: str,
    cohort_fingerprint: str,
    cohort_role: CohortRole,
    pair_manifest_id: str,
    pair_manifest_fingerprint: str,
    score_direction: ScoreDirection,
    labeled_results: LabeledResults,
    metadata: Mapping[str, str] | None = None,
) -> CalibrationSourceBinding:
    """Seal a binding around the identities it pins.

    Takes no path, no root and no filename, and there is nowhere to put one. A
    caller that knows where the scores are on disk is welcome to that knowledge;
    the artifact that a threshold cites must not depend on it (spec section 7).
    """
    if not isinstance(labeled_results, LabeledResults):
        raise CalibrationProtocolError(
            "a source binding must be sealed around validated labelled results"
        )
    if labeled_results.score_direction is not score_direction:
        raise CalibrationProtocolError(
            "a source binding and its labelled results must use one score direction"
        )

    fields: dict[str, Any] = {
        "schema_version": CALIBRATION_SOURCE_BINDING_SCHEMA_VERSION,
        "binding_id": str(binding_id).strip(),
        "algorithm_id": str(algorithm_id).strip(),
        "algorithm_fingerprint": _digest(algorithm_fingerprint),
        "integration_id": str(integration_id).strip(),
        "integration_fingerprint": _digest(integration_fingerprint),
        "run_id": str(run_id).strip(),
        "run_fingerprint": _digest(run_fingerprint),
        "result_set_id": str(result_set_id).strip(),
        "result_set_fingerprint": _digest(result_set_fingerprint),
        "labeled_results_hash": labeled_results.content_hash(),
        "pair_ids": labeled_results.pair_ids,
        "ground_truth": labeled_results.ground_truth,
        "dataset_id": str(dataset_id).strip(),
        "dataset_fingerprint": _digest(dataset_fingerprint),
        "cohort_id": str(cohort_id).strip(),
        "cohort_fingerprint": _digest(cohort_fingerprint),
        "cohort_role": cohort_role,
        "pair_manifest_id": str(pair_manifest_id).strip(),
        "pair_manifest_fingerprint": _digest(pair_manifest_fingerprint),
        "score_direction": score_direction,
        "metadata": _normalised_metadata(metadata),
    }
    fingerprint = calibration_source_binding_fingerprint(fields)
    return CalibrationSourceBinding(source_binding_fingerprint=fingerprint, **fields)


def build_calibration_source_binding(
    *,
    binding_id: str,
    verified_results: Any,
    integration_id: str,
    integration_fingerprint: str,
    dataset_id: str,
    dataset_fingerprint: str,
    cohort_fingerprint: str,
    cohort_role: CohortRole,
    pair_manifest_id: str,
    metadata: Mapping[str, str] | None = None,
) -> CalibrationSourceBinding:
    """Build a binding only from a result set whose raw records were verified.

    The verifier lives in :mod:`fpbench.calibration.source`.  Importing it here
    lazily keeps artifact sealing independent of source verification while
    retaining the public factory's historical import path.
    """
    from fpbench.calibration.source import (
        build_calibration_source_binding as build_from_verified_results,
    )

    return build_from_verified_results(
        binding_id=binding_id,
        verified_results=verified_results,
        integration_id=integration_id,
        integration_fingerprint=integration_fingerprint,
        dataset_id=dataset_id,
        dataset_fingerprint=dataset_fingerprint,
        cohort_fingerprint=cohort_fingerprint,
        cohort_role=cohort_role,
        pair_manifest_id=pair_manifest_id,
        metadata=metadata,
    )


# -------------------------------------------------------- protected registry


def build_protected_evaluation_registry(
    *,
    registry_id: str,
    registry_version: str,
    entries: Iterable[ProtectedEvaluationIdentity],
) -> ProtectedEvaluationRegistry:
    """Seal the registry, ordered and de-duplicated as the model will order it."""
    from fpbench.core.serialization import to_plain

    seen: dict[str, ProtectedEvaluationIdentity] = {}
    for entry in entries:
        previous = seen.get(entry.fingerprint)
        if previous is not None and previous != entry:
            raise ValueError(
                f"fingerprint {entry.fingerprint[:12]}... is registered twice with "
                f"different claims: {previous.label!r} and {entry.label!r}"
            )
        seen[entry.fingerprint] = entry
    ordered = tuple(
        sorted(seen.values(), key=lambda item: (item.kind.value, item.identity))
    )
    fields: dict[str, Any] = {
        "schema_version": PROTECTED_REGISTRY_SCHEMA_VERSION,
        "registry_id": str(registry_id).strip(),
        "registry_version": str(registry_version).strip(),
        "entries": [to_plain(entry) for entry in ordered],
    }
    fingerprint = protected_evaluation_registry_fingerprint(fields)
    return ProtectedEvaluationRegistry(
        registry_id=fields["registry_id"],
        registry_version=fields["registry_version"],
        entries=ordered,
        registry_fingerprint=fingerprint,
        schema_version=fields["schema_version"],
    )


# ------------------------------------------------------------- operating point


def build_calibration_operating_point(
    *,
    calibration_protocol_fingerprint_value: str,
    source_binding_fingerprint: str,
    labeled_results_hash: str,
    pair_ids: Iterable[str],
    ground_truth: Iterable[Any],
    algorithm_id: str,
    algorithm_fingerprint: str,
    threshold: Decimal | str,
    comparator: ThresholdComparator,
    score_direction: ScoreDirection,
    target_rate_numerator: int,
    target_rate_denominator: int,
    observed_impostor_matches: int,
    observed_impostor_scored: int,
    observed_impostor_attempts: int,
    impostor_failures: int,
    observed_mated_matches: int,
    observed_mated_non_matches: int,
    observed_mated_scored: int,
    observed_mated_attempts: int,
    mated_failures: int,
    selection_rule: ThresholdSelectionRule,
    tie_policy: CalibrationTiePolicy,
    created_source_commit: str,
    created_source_tree_clean: bool,
    created_utc: str,
) -> CalibrationOperatingPoint:
    """Seal an operating point around a chosen boundary and its observed counts.

    Only :mod:`fpbench.calibration.selection` should call this. An operating
    point assembled by hand would be a threshold with counts beside it rather
    than a threshold the counts produced — and nothing downstream could tell the
    difference, which is exactly why re-derivation is what verification does.
    """
    rate = ExactRate(
        numerator=target_rate_numerator, denominator=target_rate_denominator
    )
    fields: dict[str, Any] = {
        "schema_version": CALIBRATION_OPERATING_POINT_SCHEMA_VERSION,
        "calibration_protocol_fingerprint": _digest(
            calibration_protocol_fingerprint_value
        ),
        "source_binding_fingerprint": _digest(source_binding_fingerprint),
        "labeled_results_hash": _digest(labeled_results_hash),
        "pair_ids": tuple(str(pair_id).strip() for pair_id in pair_ids),
        "ground_truth": tuple(ground_truth),
        "algorithm_id": str(algorithm_id).strip(),
        "algorithm_fingerprint": _digest(algorithm_fingerprint),
        "threshold": canonical_threshold(threshold),
        "comparator": comparator,
        "score_direction": score_direction,
        "target_rate_numerator": rate.numerator,
        "target_rate_denominator": rate.denominator,
        "observed_impostor_matches": observed_impostor_matches,
        "observed_impostor_scored": observed_impostor_scored,
        "observed_impostor_attempts": observed_impostor_attempts,
        "impostor_failures": impostor_failures,
        "observed_mated_matches": observed_mated_matches,
        "observed_mated_non_matches": observed_mated_non_matches,
        "observed_mated_scored": observed_mated_scored,
        "observed_mated_attempts": observed_mated_attempts,
        "mated_failures": mated_failures,
        "selection_rule": selection_rule,
        "tie_policy": tie_policy,
        "created_source_commit": str(created_source_commit).strip().lower(),
        "created_source_tree_clean": created_source_tree_clean,
    }
    # The id and the wall clock are outside the fingerprint, so the identity is
    # computed first and the id is derived from it (spec section 20).
    fingerprint = calibration_operating_point_fingerprint(fields)
    return CalibrationOperatingPoint(
        operating_point_id=operating_point_id(fingerprint),
        operating_point_fingerprint=fingerprint,
        created_utc=str(created_utc).strip(),
        **fields,
    )
