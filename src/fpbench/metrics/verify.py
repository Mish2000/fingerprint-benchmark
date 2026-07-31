"""Re-deriving every number in a metric set, from the decisions upward.

A metric set is not evidence of itself. Stored counts, stored observations and a
stored manifest can be perfectly self-consistent and describe an evaluation that
never happened — the hashes would all check out, because a forger computes them
the same way the deriver did. So verification does not check the artefacts
against each other. It recomputes them from the decision set, the eligibility set
and the three views, and compares.

Twelve things are re-derived, in the order the specification fixes them (section
46). The one worth naming here is the seventh: **every denominator is re-resolved
from its enum**. A stored observation claiming ``3/487`` is not checked by
confirming that 3 ≤ 487. It is checked by looking up the count record its metric
reads, resolving ``DECIDED_ATTEMPTS`` against it, and seeing whether 487 is
what comes out. That is the difference between a checksum and a check.

What this module never does is read a raw score. The decision set already proved
every decision follows from the score it cites, and that proof is re-run by the
stage 5A verifier before any of this is called. A second path from the metric
engine to the scores would be a second path by which a threshold could be chosen
to suit a number (spec section 32).
"""

from __future__ import annotations

from typing import Mapping, Sequence

from fpbench.core.decision_models import DecisionProfile, DecisionSetManifest
from fpbench.core.eligibility_models import SelfEligibilityManifest
from fpbench.core.errors import MetricSetIntegrityError
from fpbench.core.evaluation_models import (
    EvaluationFinalizationMarker,
    EvaluationReceipt,
    EvaluationSummary,
    MetricDerivationDefinition,
    evaluation_receipt_content_hash,
    evaluation_receipt_fingerprint,
    evaluation_summary_content_hash,
    metric_derivation_definition_fingerprint,
    report_content_hash,
)
from fpbench.core.evaluation_view_models import (
    MATED_CONDITIONAL_VIEW,
    MATED_UNCONDITIONAL_VIEW,
    NON_MATED_SANITY_VIEW,
    EvaluationViewManifest,
)
from fpbench.core.metric_models import (
    EvaluationCountRecord,
    MetricObservation,
    MetricPolicy,
    MetricSetManifest,
    ReportProfile,
    count_record_hash,
    fraction_text,
    metric_observation_hash,
    metric_policy_fingerprint,
    metric_set_fingerprint,
    metric_set_id,
    ordered_count_records_hash,
    ordered_observations_hash,
    report_profile_fingerprint,
)
from fpbench.core.result_models import RunDefinition
from fpbench.core.result_set_models import ResultSetManifest
from fpbench.metrics.aggregate import MetricSources, aggregate_count_records
from fpbench.metrics.denominators import resolve
from fpbench.metrics.observations import build_observations, index_count_records
from fpbench.metrics.summary import build_evaluation_summary

__all__ = [
    "verify_metric_set",
    "verify_evaluation_summary",
    "verify_evaluation_report",
    "verify_evaluation_receipt",
    "verify_evaluation_finalization_marker",
]


def verify_metric_set(
    *,
    definition: MetricDerivationDefinition,
    policy: MetricPolicy,
    report_profile: ReportProfile,
    manifest: MetricSetManifest,
    counts: Sequence[EvaluationCountRecord],
    observations: Sequence[MetricObservation],
    sources: MetricSources,
    run: RunDefinition,
    result_set: ResultSetManifest,
    decision_profile: DecisionProfile,
    decision_manifest: DecisionSetManifest,
    eligibility_manifest: SelfEligibilityManifest,
    view_manifests: Mapping[str, EvaluationViewManifest],
    releases: Sequence[str],
) -> None:
    """Recompute a stored metric set from its sources and refuse any difference.

    Raises:
        MetricSetIntegrityError: anything at all does not survive re-derivation.
    """
    releases = tuple(releases)

    # 1. The definition and manifest must point to the actual, already verified
    # source chain. Recomputing their own fingerprints is not enough: a forged
    # definition and manifest can agree perfectly with one another while naming
    # a run, set or view that was never supplied to this evaluation.
    _verify_source_chain(
        definition=definition,
        policy=policy,
        report_profile=report_profile,
        manifest=manifest,
        sources=sources,
        run=run,
        result_set=result_set,
        decision_profile=decision_profile,
        decision_manifest=decision_manifest,
        eligibility_manifest=eligibility_manifest,
        view_manifests=view_manifests,
    )

    # 2-4. The three immutable inputs still fingerprint to what they claim, and
    # the definition still names the artefacts actually in front of us.
    _require(
        definition.definition_fingerprint
        == metric_derivation_definition_fingerprint(definition),
        "the metric derivation definition's fingerprint does not cover its claims",
    )
    _require(
        policy.policy_fingerprint == metric_policy_fingerprint(policy),
        "the metric policy's fingerprint does not cover its definitions",
    )
    _require(
        report_profile.report_profile_fingerprint
        == report_profile_fingerprint(report_profile),
        "the report profile's fingerprint does not cover its settings",
    )
    for label, actual, expected in (
        ("metric policy", definition.metric_policy_fingerprint, policy.policy_fingerprint),
        (
            "report profile",
            definition.report_profile_fingerprint,
            report_profile.report_profile_fingerprint,
        ),
        (
            "decision set",
            definition.decision_set_fingerprint,
            sources.decision_set_fingerprint,
        ),
        (
            "eligibility set",
            definition.eligibility_set_fingerprint,
            sources.eligibility_set_fingerprint,
        ),
        (
            "unconditional view",
            definition.unconditional_view_fingerprint,
            sources.view_fingerprint(MATED_UNCONDITIONAL_VIEW),
        ),
        (
            "conditional view",
            definition.conditional_view_fingerprint,
            sources.view_fingerprint(MATED_CONDITIONAL_VIEW),
        ),
        (
            "non-mated view",
            definition.non_mated_view_fingerprint,
            sources.view_fingerprint(NON_MATED_SANITY_VIEW),
        ),
    ):
        _require(
            actual == expected,
            f"the definition pins a different {label} than the one supplied: "
            f"{actual[:12]}... != {expected[:12]}...",
        )
    _require(
        tuple(report_profile.release_order) == releases,
        f"the report profile orders releases {list(report_profile.release_order)}, "
        f"but this evaluation covers {list(releases)}",
    )

    # 5-6. Every release partition and every count record, recomputed from the
    # decisions and views rather than compared with itself.
    recomputed_counts = aggregate_count_records(sources, releases=releases)
    _require(
        len(recomputed_counts) == len(counts),
        f"the metric set stores {len(counts)} count records, but re-deriving them "
        f"from the decisions produces {len(recomputed_counts)}",
    )
    for stored, recomputed in zip(counts, recomputed_counts):
        _require(
            stored.count_record_hash == count_record_hash(stored),
            f"count record {stored.count_family} at {stored.scope.label} does not "
            "hash to its own contents",
        )
        _require(
            stored.count_record_hash == recomputed.count_record_hash,
            f"count record {stored.count_family} at {stored.scope.label} does not "
            f"survive re-derivation: stored {dict(stored.counts)} "
            f"total {stored.total_count}, re-derived {dict(recomputed.counts)} "
            f"total {recomputed.total_count}",
        )

    # 7-8. Every numerator, every denominator and every fraction, re-resolved
    # from the enum rather than trusted as an integer (spec section 47).
    index = index_count_records(counts)
    for observation in observations:
        definition_for = _definition_or_fail(policy, observation.metric_id)
        key = (
            definition_for.metric_family,
            observation.scope.scope_kind.value,
            observation.scope.release,
        )
        record = index.get(key)
        _require(
            record is not None,
            f"observation {observation.metric_id} at {observation.scope.label} "
            f"cites {definition_for.metric_family} counts that are not stored",
        )
        numerator, denominator = resolve(definition=definition_for, record=record)
        _require(
            observation.denominator_count == denominator,
            f"observation {observation.metric_id} at {observation.scope.label} "
            f"reports denominator {observation.denominator_count}, but "
            f"{definition_for.denominator.value} over the stored counts is "
            f"{denominator}",
        )
        expected_numerator = numerator if denominator > 0 else 0
        _require(
            observation.numerator_count == expected_numerator,
            f"observation {observation.metric_id} at {observation.scope.label} "
            f"reports numerator {observation.numerator_count}, but "
            f"{definition_for.numerator.value} over the stored counts is "
            f"{expected_numerator}",
        )
        _require(
            observation.fraction_text
            == fraction_text(observation.numerator_count, observation.denominator_count),
            f"observation {observation.metric_id} at {observation.scope.label} "
            f"carries fraction text {observation.fraction_text!r} that its counts "
            "do not produce",
        )
        # 10. And the hash covers all of it, including the scope.
        _require(
            observation.observation_hash == metric_observation_hash(observation),
            f"observation {observation.metric_id} at {observation.scope.label} does "
            "not hash to its own contents",
        )

    # 9. Pooled values are the sums of their releases. Re-deriving the whole
    # observation list also re-checks the ordering and the pooled arithmetic.
    recomputed_observations = build_observations(
        policy=policy,
        records=recomputed_counts,
        releases=releases,
        decision_set_fingerprint=sources.decision_set_fingerprint,
        eligibility_set_fingerprint=sources.eligibility_set_fingerprint,
        view_fingerprints={
            kind: sources.view_fingerprint(kind)
            for kind in (
                MATED_UNCONDITIONAL_VIEW,
                MATED_CONDITIONAL_VIEW,
                NON_MATED_SANITY_VIEW,
            )
        },
    )
    _require(
        len(recomputed_observations) == len(observations),
        f"the metric set stores {len(observations)} observations, but the policy "
        f"and the counts produce {len(recomputed_observations)}",
    )
    for stored, recomputed in zip(observations, recomputed_observations):
        _require(
            stored.observation_hash == recomputed.observation_hash,
            f"observation {stored.metric_id} at {stored.scope.label} does not "
            f"survive re-derivation: stored "
            f"{stored.numerator_count}/{stored.denominator_count}, re-derived "
            f"{recomputed.numerator_count}/{recomputed.denominator_count}",
        )

    # 11-12. The ordered hashes and the identity they roll up into.
    _require(
        ordered_count_records_hash(counts) == manifest.ordered_count_records_hash,
        "the manifest's ordered count-records hash does not cover these rows",
    )
    _require(
        ordered_observations_hash(observations) == manifest.ordered_observations_hash,
        "the manifest's ordered observations hash does not cover these rows",
    )
    _require(
        manifest.total_count_records == len(counts)
        and manifest.total_observations == len(observations),
        f"the manifest declares {manifest.total_count_records} count records and "
        f"{manifest.total_observations} observations, but carries "
        f"{len(counts)} and {len(observations)}",
    )

    expected_fingerprint = metric_set_fingerprint(
        run_fingerprint=manifest.run_fingerprint,
        decision_set_fingerprint=sources.decision_set_fingerprint,
        eligibility_set_fingerprint=sources.eligibility_set_fingerprint,
        unconditional_view_fingerprint=sources.view_fingerprint(
            MATED_UNCONDITIONAL_VIEW
        ),
        conditional_view_fingerprint=sources.view_fingerprint(MATED_CONDITIONAL_VIEW),
        non_mated_view_fingerprint=sources.view_fingerprint(NON_MATED_SANITY_VIEW),
        metric_policy_fingerprint=policy.policy_fingerprint,
        metric_software_fingerprint=definition.metric_software_fingerprint,
        ordered_count_records_hash=manifest.ordered_count_records_hash,
        ordered_observations_hash=manifest.ordered_observations_hash,
    )
    _require(
        manifest.metric_set_fingerprint == expected_fingerprint,
        "the metric-set fingerprint does not cover the artefacts it was computed "
        "over",
    )
    _require(
        manifest.metric_set_id == metric_set_id(expected_fingerprint),
        "the metric-set id is not derived from its fingerprint",
    )


def verify_evaluation_summary(
    *,
    summary: EvaluationSummary,
    manifest: MetricSetManifest,
    counts: Sequence[EvaluationCountRecord],
    observations: Sequence[MetricObservation],
    releases: Sequence[str],
    run: RunDefinition,
    decision_profile: DecisionProfile,
) -> None:
    """Confirm the summary is a rendering of *this* metric set and nothing else.

    Field by field rather than by comparing one hash, because a forged summary
    can be internally consistent while describing a different evaluation.
    """
    expected = build_evaluation_summary(
        manifest=manifest,
        run=run,
        decision_profile=decision_profile,
        releases=releases,
        counts=counts,
        observations=observations,
        # The clock is intentionally non-semantic. Reusing the stored value lets
        # ordinary dataclass equality compare every other field exactly.
        generated_utc=summary.generated_utc,
    )
    for name in (
        "metric_set_id",
        "algorithm_id",
        "implementation_version",
        "execution_profile_id",
        "decision_profile_id",
        "threshold",
        "releases",
        "count_records",
        "observations",
    ):
        _require(
            getattr(summary, name) == getattr(expected, name),
            f"the summary field {name} is not the canonical value derived from "
            "the verified run, decision profile and metric set",
        )


def verify_evaluation_report(*, markdown: str, expected_markdown: str) -> None:
    """Confirm stored report text equals a fresh canonical rendering."""
    _require(
        markdown == expected_markdown,
        "the stored report is not the canonical rendering of the verified "
        "sources and metric set",
    )


def verify_evaluation_receipt(
    *,
    receipt: EvaluationReceipt,
    definition: MetricDerivationDefinition,
    manifest: MetricSetManifest,
    policy: MetricPolicy,
    observations: Sequence[MetricObservation],
    releases: Sequence[str],
    structural_counts: Mapping[str, int],
    run_id: str,
    result_set_id: str,
    decision_profile_id: str,
) -> None:
    """Re-derive every load-bearing receipt claim from the current artefacts."""
    expected: Mapping[str, object] = {
        "run_id": run_id,
        "result_set_id": result_set_id,
        "decision_profile_id": decision_profile_id,
        "decision_set_id": manifest.decision_set_id,
        "eligibility_set_id": manifest.eligibility_set_id,
        "metric_policy_id": policy.policy_id,
        "metric_policy_fingerprint": policy.policy_fingerprint,
        "metric_set_id": manifest.metric_set_id,
        "metric_set_fingerprint": manifest.metric_set_fingerprint,
        "metric_source_commit": definition.metric_source_commit,
        "metric_source_tree_clean": True,
    }
    for name, value in expected.items():
        actual = getattr(receipt, name)
        _require(
            actual == value,
            f"evaluation receipt field {name} is {actual!r}, expected {value!r}",
        )
    _require(
        tuple(receipt.releases) == tuple(releases),
        f"the receipt covers releases {list(receipt.releases)}, expected "
        f"{list(releases)}",
    )
    _require(
        dict(receipt.structural_counts) == dict(structural_counts),
        f"the receipt's structural counts are {dict(receipt.structural_counts)}, "
        f"expected {dict(structural_counts)}",
    )

    # Every published pair of integers must be one the metric set actually holds.
    stored = {
        (observation.metric_id, observation.scope.label): (
            observation.numerator_count,
            observation.denominator_count,
        )
        for observation in observations
    }
    published = {
        (metric_id, label): (
            pair["numerator"],
            pair["denominator"],
        )
        for metric_id, by_scope in receipt.metrics.items()
        for label, pair in by_scope.items()
    }
    _require(
        published == stored,
        "the receipt publishes numbers the metric set does not hold, or omits "
        "numbers it does",
    )


def verify_evaluation_finalization_marker(
    *,
    marker: EvaluationFinalizationMarker,
    definition: MetricDerivationDefinition,
    manifest: MetricSetManifest,
    receipt: EvaluationReceipt,
    summary: EvaluationSummary,
    canonical_markdown: str,
    decision_finalization_fingerprint: str,
) -> None:
    """Confirm the marker still names every current durable artefact."""
    expected = {
        "source_decision_finalization_fingerprint": decision_finalization_fingerprint,
        "metric_definition_fingerprint": definition.definition_fingerprint,
        "metric_set_fingerprint": manifest.metric_set_fingerprint,
        "summary_content_hash": evaluation_summary_content_hash(summary),
        "report_content_hash": report_content_hash(canonical_markdown),
        "evaluation_receipt_fingerprint": evaluation_receipt_fingerprint(receipt),
        "evaluation_receipt_content_hash": evaluation_receipt_content_hash(receipt),
        "metric_source_commit": definition.metric_source_commit,
        "metric_source_tree_clean": True,
    }
    for name, value in expected.items():
        actual = getattr(marker, name)
        _require(
            actual == value,
            f"evaluation finalization field {name} is {actual!r}, expected "
            f"{value!r}",
        )


# ----------------------------------------------------------------- internals


def _verify_source_chain(
    *,
    definition: MetricDerivationDefinition,
    policy: MetricPolicy,
    report_profile: ReportProfile,
    manifest: MetricSetManifest,
    sources: MetricSources,
    run: RunDefinition,
    result_set: ResultSetManifest,
    decision_profile: DecisionProfile,
    decision_manifest: DecisionSetManifest,
    eligibility_manifest: SelfEligibilityManifest,
    view_manifests: Mapping[str, EvaluationViewManifest],
) -> None:
    required_views = (
        MATED_UNCONDITIONAL_VIEW,
        MATED_CONDITIONAL_VIEW,
        NON_MATED_SANITY_VIEW,
    )
    _require(
        set(view_manifests) == set(required_views),
        f"the source chain supplies views {sorted(view_manifests)}, expected "
        f"{sorted(required_views)}",
    )
    _require(
        set(sources.view_manifests) == set(required_views),
        "the aggregation inputs do not carry exactly the source view manifests",
    )

    _require_fields(
        "definition",
        definition,
        {
            "run_id": run.run_id,
            "result_set_fingerprint": result_set.result_set_fingerprint,
            "decision_set_id": decision_manifest.decision_set_id,
            "decision_set_fingerprint": decision_manifest.decision_set_fingerprint,
            "eligibility_set_id": eligibility_manifest.eligibility_set_id,
            "eligibility_set_fingerprint": (
                eligibility_manifest.eligibility_set_fingerprint
            ),
            "unconditional_view_fingerprint": view_manifests[
                MATED_UNCONDITIONAL_VIEW
            ].view_fingerprint,
            "conditional_view_fingerprint": view_manifests[
                MATED_CONDITIONAL_VIEW
            ].view_fingerprint,
            "non_mated_view_fingerprint": view_manifests[
                NON_MATED_SANITY_VIEW
            ].view_fingerprint,
            "metric_policy_id": policy.policy_id,
            "metric_policy_fingerprint": policy.policy_fingerprint,
            "report_profile_id": report_profile.report_profile_id,
            "report_profile_fingerprint": report_profile.report_profile_fingerprint,
        },
    )
    _require_fields(
        "metric-set manifest",
        manifest,
        {
            "run_id": run.run_id,
            "run_fingerprint": run.run_fingerprint,
            "decision_set_id": decision_manifest.decision_set_id,
            "decision_set_fingerprint": decision_manifest.decision_set_fingerprint,
            "eligibility_set_id": eligibility_manifest.eligibility_set_id,
            "eligibility_set_fingerprint": (
                eligibility_manifest.eligibility_set_fingerprint
            ),
            "unconditional_view_fingerprint": view_manifests[
                MATED_UNCONDITIONAL_VIEW
            ].view_fingerprint,
            "conditional_view_fingerprint": view_manifests[
                MATED_CONDITIONAL_VIEW
            ].view_fingerprint,
            "non_mated_view_fingerprint": view_manifests[
                NON_MATED_SANITY_VIEW
            ].view_fingerprint,
            "metric_policy_id": policy.policy_id,
            "metric_policy_fingerprint": policy.policy_fingerprint,
            "report_profile_fingerprint": report_profile.report_profile_fingerprint,
            "metric_software_fingerprint": definition.metric_software_fingerprint,
            "metric_source_revision": definition.metric_source_commit,
        },
    )

    # Prove that the objects supplied as the source chain agree with each other,
    # rather than merely agreeing with the new metric artefacts.
    _require_fields(
        "result-set manifest",
        result_set,
        {"run_id": run.run_id, "run_fingerprint": run.run_fingerprint},
    )
    _require_fields(
        "decision-set manifest",
        decision_manifest,
        {
            "run_id": run.run_id,
            "run_fingerprint": run.run_fingerprint,
            "result_set_id": result_set.result_set_id,
            "result_set_fingerprint": result_set.result_set_fingerprint,
            "decision_profile_id": decision_profile.profile_id,
            "decision_profile_fingerprint": decision_profile.profile_fingerprint,
        },
    )
    _require_fields(
        "eligibility-set manifest",
        eligibility_manifest,
        {
            "run_id": run.run_id,
            "result_set_fingerprint": result_set.result_set_fingerprint,
            "decision_set_fingerprint": decision_manifest.decision_set_fingerprint,
            "decision_profile_fingerprint": decision_profile.profile_fingerprint,
        },
    )
    _require(
        sources.decision_set_fingerprint
        == decision_manifest.decision_set_fingerprint,
        "the aggregation inputs do not come from the supplied decision-set manifest",
    )
    _require(
        sources.eligibility_set_fingerprint
        == eligibility_manifest.eligibility_set_fingerprint,
        "the aggregation inputs do not come from the supplied eligibility-set manifest",
    )

    for kind in required_views:
        source_view = sources.view_manifests[kind]
        view = view_manifests[kind]
        _require(
            source_view.view_fingerprint == view.view_fingerprint,
            f"the aggregation inputs carry a different {kind} view manifest",
        )
        _require_fields(
            f"{kind} view manifest",
            view,
            {
                "view_kind": kind,
                "run_fingerprint": run.run_fingerprint,
                "result_set_fingerprint": result_set.result_set_fingerprint,
                "decision_set_fingerprint": decision_manifest.decision_set_fingerprint,
                "eligibility_set_fingerprint": (
                    eligibility_manifest.eligibility_set_fingerprint
                    if kind == MATED_CONDITIONAL_VIEW
                    else None
                ),
            },
        )


def _require_fields(label: str, actual: object, expected: Mapping[str, object]) -> None:
    for name, expected_value in expected.items():
        actual_value = getattr(actual, name)
        _require(
            actual_value == expected_value,
            f"{label}.{name} is {actual_value!r}, expected {expected_value!r} "
            "from the verified source chain",
        )


def _definition_or_fail(policy: MetricPolicy, metric_id: str):
    try:
        return policy.definition(metric_id)
    except Exception as exc:  # MetricPolicyError, deliberately re-typed
        raise MetricSetIntegrityError(
            f"the metric set holds an observation for {metric_id!r}, which policy "
            f"{policy.policy_id} does not define"
        ) from exc


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise MetricSetIntegrityError(message)
