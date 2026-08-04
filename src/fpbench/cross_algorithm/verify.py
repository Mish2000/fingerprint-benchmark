"""Re-deriving a comparison instead of believing it.

A comparison manifest is not evidence of itself. It says the paired records hash
to a value; it is a file, and a file can be edited. So verification does the only
thing that proves anything: it goes back to the two verified chains, derives the
whole comparison again, and checks that every hash it computes is the one the
manifest carries.

That makes verification cost what derivation cost, which is the correct trade —
and it is what makes the tampering cases in the specification fail rather than
pass quietly: a removed common-eligible row, a removed transition cell, a
reordered pair, an edited report (spec section 71).
"""

from __future__ import annotations

from typing import Sequence

from fpbench.core.cross_algorithm_models import (
    CrossAlgorithmEvaluationDefinition,
    CrossAlgorithmEvaluationManifest,
    FairComparabilityAudit,
    FairMeasurementProtocol,
    cross_algorithm_definition_fingerprint,
    cross_algorithm_evaluation_fingerprint,
    cross_algorithm_evaluation_id,
    fair_comparability_audit_fingerprint,
    fair_measurement_protocol_fingerprint,
    ordered_common_eligible_hash,
    ordered_comparison_records_hash,
    ordered_count_records_hash,
    ordered_eligibility_transitions_hash,
    ordered_observations_hash,
    require_no_score_comparison,
)
from fpbench.core.enums import CrossAlgorithmTransitionFamily, DecisionOutcome
from fpbench.cross_algorithm.align import ComparisonSide, CrossAlgorithmError
from fpbench.cross_algorithm.derive import (
    CrossAlgorithmDerivation,
    POOLED_SCOPE,
)

__all__ = [
    "verify_protocol",
    "verify_audit",
    "verify_definition",
    "verify_derivation",
    "require_complete_matrices",
]


def verify_protocol(protocol: FairMeasurementProtocol) -> None:
    """The frozen protocol still fingerprints to what it claims."""
    recomputed = fair_measurement_protocol_fingerprint(protocol)
    if recomputed != protocol.protocol_fingerprint:
        raise CrossAlgorithmError(
            "the measurement protocol does not fingerprint to its own content; it "
            "has been edited since it was committed"
        )


def verify_audit(audit: FairComparabilityAudit) -> None:
    if fair_comparability_audit_fingerprint(audit) != audit.audit_fingerprint:
        raise CrossAlgorithmError(
            "the fair-comparability audit does not fingerprint to its own content"
        )


def verify_definition(
    *,
    definition: CrossAlgorithmEvaluationDefinition,
    protocol: FairMeasurementProtocol,
    left: ComparisonSide,
    right: ComparisonSide,
) -> None:
    """Every identity the definition names is the one currently on disk.

    Field by field rather than by comparing fingerprints: a forged definition can
    be perfectly self-consistent while describing a comparison that is not the
    one being carried out.
    """
    if cross_algorithm_definition_fingerprint(definition) != (
        definition.definition_fingerprint
    ):
        raise CrossAlgorithmError(
            "the comparison definition does not fingerprint to its own claims"
        )
    if definition.protocol_fingerprint != protocol.protocol_fingerprint:
        raise CrossAlgorithmError(
            "the comparison definition names a different measurement protocol"
        )

    expected = {
        "left_label": left.label,
        "left_run_id": left.run.run_id,
        "left_run_fingerprint": left.run.run_fingerprint,
        "left_result_set_fingerprint": left.result_set.result_set_fingerprint,
        "left_decision_set_id": left.decision_manifest.decision_set_id,
        "left_decision_set_fingerprint": (
            left.decision_manifest.decision_set_fingerprint
        ),
        "left_eligibility_set_id": left.eligibility_manifest.eligibility_set_id,
        "left_eligibility_set_fingerprint": (
            left.eligibility_manifest.eligibility_set_fingerprint
        ),
        "left_metric_set_id": left.metric_manifest.metric_set_id,
        "left_metric_set_fingerprint": left.metric_manifest.metric_set_fingerprint,
        "left_decision_profile_fingerprint": left.decision_profile.profile_fingerprint,
        "right_label": right.label,
        "right_run_id": right.run.run_id,
        "right_run_fingerprint": right.run.run_fingerprint,
        "right_result_set_fingerprint": right.result_set.result_set_fingerprint,
        "right_decision_set_id": right.decision_manifest.decision_set_id,
        "right_decision_set_fingerprint": (
            right.decision_manifest.decision_set_fingerprint
        ),
        "right_eligibility_set_id": right.eligibility_manifest.eligibility_set_id,
        "right_eligibility_set_fingerprint": (
            right.eligibility_manifest.eligibility_set_fingerprint
        ),
        "right_metric_set_id": right.metric_manifest.metric_set_id,
        "right_metric_set_fingerprint": right.metric_manifest.metric_set_fingerprint,
        "right_decision_profile_fingerprint": (
            right.decision_profile.profile_fingerprint
        ),
        "alignment_fingerprint": protocol.alignment_fingerprint,
        "metric_policy_fingerprint": protocol.metric_policy_fingerprint,
        "comparison_policy_fingerprint": protocol.comparison_policy_fingerprint,
        "eligibility_policy_id": protocol.eligibility_policy_id,
        "eligibility_policy_version": protocol.eligibility_policy_version,
    }
    for name, value in expected.items():
        actual = getattr(definition, name)
        if actual != value:
            raise CrossAlgorithmError(
                f"comparison definition field {name} is {actual!r}, expected "
                f"{value!r}"
            )


def verify_derivation(
    *,
    derivation: CrossAlgorithmDerivation,
    manifest: CrossAlgorithmEvaluationManifest,
) -> None:
    """The stored manifest describes exactly the artefacts just re-derived."""
    checks = (
        (
            "comparison records",
            ordered_comparison_records_hash(derivation.records),
            manifest.comparison_records_hash,
        ),
        (
            "eligibility transitions",
            ordered_eligibility_transitions_hash(derivation.transitions),
            manifest.eligibility_transitions_hash,
        ),
        (
            "common eligible",
            ordered_common_eligible_hash(derivation.common_eligible),
            manifest.common_eligible_hash,
        ),
        (
            "count records",
            ordered_count_records_hash(derivation.counts),
            manifest.count_records_hash,
        ),
        (
            "observations",
            ordered_observations_hash(derivation.observations),
            manifest.observations_hash,
        ),
    )
    for label, recomputed, stored in checks:
        if recomputed != stored:
            raise CrossAlgorithmError(
                f"the {label} hash is {recomputed[:12]}..., but the manifest "
                f"records {stored[:12]}...; the comparison has changed since it "
                "was written"
            )

    totals = (
        ("total_records", len(derivation.records), manifest.total_records),
        ("total_transitions", len(derivation.transitions), manifest.total_transitions),
        (
            "total_common_eligible",
            len(derivation.common_eligible),
            manifest.total_common_eligible,
        ),
        (
            "total_observations",
            len(derivation.observations),
            manifest.total_observations,
        ),
    )
    for label, recomputed_count, stored_count in totals:
        if recomputed_count != stored_count:
            raise CrossAlgorithmError(
                f"{label} is {recomputed_count}, the manifest records {stored_count}"
            )

    recomputed_fingerprint = cross_algorithm_evaluation_fingerprint(
        definition_fingerprint=manifest.definition_fingerprint,
        audit_fingerprint=manifest.audit_fingerprint,
        comparison_records_hash=manifest.comparison_records_hash,
        eligibility_transitions_hash=manifest.eligibility_transitions_hash,
        common_eligible_hash=manifest.common_eligible_hash,
        count_records_hash=manifest.count_records_hash,
        observations_hash=manifest.observations_hash,
        total_records=manifest.total_records,
        total_transitions=manifest.total_transitions,
        total_common_eligible=manifest.total_common_eligible,
        total_observations=manifest.total_observations,
    )
    if recomputed_fingerprint != manifest.evaluation_fingerprint:
        raise CrossAlgorithmError(
            "the comparison does not fingerprint to its own identity"
        )
    if cross_algorithm_evaluation_id(recomputed_fingerprint) != manifest.evaluation_id:
        raise CrossAlgorithmError("the comparison is stored under a foreign id")

    require_complete_matrices(derivation.counts, releases=derivation.releases)
    require_no_score_comparison(derivation.observations, path="observations")
    require_no_score_comparison(derivation.records, path="records")


def require_complete_matrices(counts: Sequence, *, releases: Sequence[str]) -> None:
    """Nine cells per family per scope, present even where they are zero.

    A matrix rendered from only its non-empty cells invites the reader to assume
    the missing ones were impossible rather than merely unobserved, and a matrix
    that lost a cell to an editor would look exactly the same (spec section 50).
    """
    scopes = tuple(releases) + (POOLED_SCOPE,)
    present = {
        (record.family, record.scope, record.left_outcome, record.right_outcome)
        for record in counts
        if record.left_outcome is not None
    }
    missing: list[str] = []
    for family in CrossAlgorithmTransitionFamily:
        for scope in scopes:
            for left_outcome in DecisionOutcome:
                for right_outcome in DecisionOutcome:
                    key = (family, scope, left_outcome, right_outcome)
                    if key not in present:
                        missing.append(
                            f"{family.value}/{scope}/{left_outcome.value}->"
                            f"{right_outcome.value}"
                        )
    if missing:
        raise CrossAlgorithmError(
            f"{len(missing)} transition cell(s) are absent, starting with "
            f"{missing[:3]}; every matrix carries all nine cells"
        )
