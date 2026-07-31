"""Turning aggregate counts into the metrics a policy asked for.

Nothing is computed here. Every number an observation carries was already in a
count record; this module selects two of them per metric, per scope, using
:mod:`fpbench.metrics.denominators`, and attaches the provenance that says which
artefact the counts came from.

That is a deliberately small job. The temptation in a metrics layer is to let
each metric have its own little function that knows how to find its numbers —
and then one of those functions divides by the wrong total, and the resulting
percentage is indistinguishable from a correct one. Here there is one path, and
the verifier walks it again from the stored records (spec section 47).

The zero-denominator rule lives here too. A metric over an empty population is
``UNDEFINED_ZERO_DENOMINATOR`` with no fraction and no percentage. It is not
zero, it is not ``NaN``, and it does not raise: an evaluation in which no finger
passed both SELF tests is a real, reportable outcome, and it must survive all the
way into the report as "undefined (0 eligible decided attempts)" rather than as a
stack trace (spec sections 26, 70).
"""

from __future__ import annotations

from typing import Mapping, Sequence

from fpbench.core.enums import MetricObservationStatus, MetricScopeKind
from fpbench.core.errors import MetricDerivationError
from fpbench.core.evaluation_view_models import (
    MATED_CONDITIONAL_VIEW,
    MATED_UNCONDITIONAL_VIEW,
    NON_MATED_SANITY_VIEW,
)
from fpbench.core.metric_models import (
    CountFamily,
    EvaluationCountRecord,
    MetricObservation,
    MetricPolicy,
    MetricScope,
    fraction_text,
    metric_observation_hash,
    scope_sort_key,
)
from fpbench.metrics.denominators import resolve

__all__ = [
    "build_observations",
    "index_count_records",
    "FAMILIES_USING_ELIGIBILITY",
    "VIEW_FOR_FAMILY",
]

#: Families whose counts could not have been produced without the eligibility
#: set. Their observations cite it; the others must not, because citing an
#: artefact a number does not depend on makes the citation meaningless.
FAMILIES_USING_ELIGIBILITY: frozenset[str] = frozenset(
    {CountFamily.SELF_ELIGIBILITY, CountFamily.MATED_CONDITIONAL}
)

#: Which evaluation view each family was counted from. ``None`` for the two
#: families derived from the decision set and the eligibility set directly.
VIEW_FOR_FAMILY: Mapping[str, str | None] = {
    CountFamily.PLAIN_SELF: None,
    CountFamily.ROLL_SELF: None,
    CountFamily.SELF_ELIGIBILITY: None,
    CountFamily.MATED_UNCONDITIONAL: MATED_UNCONDITIONAL_VIEW,
    CountFamily.MATED_CONDITIONAL: MATED_CONDITIONAL_VIEW,
    CountFamily.NEGATIVE_SANITY: NON_MATED_SANITY_VIEW,
}


def index_count_records(
    records: Sequence[EvaluationCountRecord],
) -> Mapping[tuple[str, str, str | None], EvaluationCountRecord]:
    """Key the records by ``(family, scope kind, release)`` for lookup."""
    index: dict[tuple[str, str, str | None], EvaluationCountRecord] = {}
    for record in records:
        key = (
            record.count_family,
            record.scope.scope_kind.value,
            record.scope.release,
        )
        if key in index:
            raise MetricDerivationError(
                f"two count records cover {record.count_family} at "
                f"{record.scope.label}"
            )
        index[key] = record
    return index


def build_observations(
    *,
    policy: MetricPolicy,
    records: Sequence[EvaluationCountRecord],
    releases: Sequence[str],
    decision_set_fingerprint: str,
    eligibility_set_fingerprint: str,
    view_fingerprints: Mapping[str, str],
) -> tuple[MetricObservation, ...]:
    """One observation per metric per scope, in canonical order.

    Order is metric-definition order, then release in the declared order, then
    pooled. It enters the ordered hash, so a reordering that changes no number is
    still a different metric set (spec section 40).
    """
    releases = tuple(releases)
    index = index_count_records(records)

    observations: list[MetricObservation] = []
    ordinal = 0
    for definition in policy.metric_definitions:
        scopes = [
            MetricScope(MetricScopeKind.RELEASE, release) for release in releases
        ]
        scopes.append(MetricScope(MetricScopeKind.POOLED))

        for scope in scopes:
            key = (
                definition.metric_family,
                scope.scope_kind.value,
                scope.release,
            )
            record = index.get(key)
            if record is None:
                raise MetricDerivationError(
                    f"metric {definition.metric_id} needs "
                    f"{definition.metric_family} counts at {scope.label}, which "
                    "were not aggregated"
                )

            numerator, denominator = resolve(definition=definition, record=record)
            defined = denominator > 0
            status = (
                MetricObservationStatus.DEFINED
                if defined
                else MetricObservationStatus.UNDEFINED_ZERO_DENOMINATOR
            )
            # A numerator over an empty population is not a measurement. It
            # cannot be non-zero given the count invariants, but saying so here
            # keeps the observation model's contract local and readable.
            numerator = numerator if defined else 0

            view_kind = VIEW_FOR_FAMILY[definition.metric_family]
            fields = {
                "ordinal": ordinal,
                "metric_id": definition.metric_id,
                "scope": scope,
                "numerator_count": numerator,
                "denominator_count": denominator,
                "status": status,
                "fraction_text": fraction_text(numerator, denominator),
                "source_decision_set_fingerprint": decision_set_fingerprint,
                "source_eligibility_set_fingerprint": (
                    eligibility_set_fingerprint
                    if definition.metric_family in FAMILIES_USING_ELIGIBILITY
                    else None
                ),
                "source_view_fingerprint": (
                    view_fingerprints[view_kind] if view_kind else None
                ),
                "metric_policy_fingerprint": policy.policy_fingerprint,
            }
            probe = _ObservationProbe(**fields)
            observations.append(
                MetricObservation(
                    observation_hash=metric_observation_hash(probe),  # type: ignore[arg-type]
                    **fields,
                )
            )
            ordinal += 1

    _require_canonical_order(observations, policy=policy, releases=releases)
    _require_pooled_is_the_sum(observations, releases=releases)
    return tuple(observations)


def _require_canonical_order(
    observations: Sequence[MetricObservation],
    *,
    policy: MetricPolicy,
    releases: tuple[str, ...],
) -> None:
    expected = sorted(
        range(len(observations)),
        key=lambda index: (
            policy.definition_index(observations[index].metric_id),
            scope_sort_key(observations[index].scope, releases),
        ),
    )
    if expected != list(range(len(observations))):
        raise MetricDerivationError(
            "observations were not produced in canonical order (metric, release, "
            "pooled)"
        )


def _require_pooled_is_the_sum(
    observations: Sequence[MetricObservation], *, releases: tuple[str, ...]
) -> None:
    """Refuse a pooled observation that is not the sum of its releases.

    The pooled counts came from adding the release counts, so this cannot fail
    by arithmetic. It can fail if a metric's denominator resolves differently at
    pooled scope than at release scope — which would be a real bug, silently
    producing a pooled rate over a population that is not the union of the
    release populations (docs/adr/0028).
    """
    by_metric: dict[str, dict[str, MetricObservation]] = {}
    for observation in observations:
        by_metric.setdefault(observation.metric_id, {})[
            observation.scope.label
        ] = observation

    for metric_id, by_scope in by_metric.items():
        pooled = by_scope.get("pooled")
        if pooled is None:
            raise MetricDerivationError(
                f"metric {metric_id} has release observations but no pooled one"
            )
        missing = [release for release in releases if release not in by_scope]
        if missing:
            raise MetricDerivationError(
                f"metric {metric_id} is missing observations for {missing}"
            )

        numerator = sum(by_scope[release].numerator_count for release in releases)
        denominator = sum(by_scope[release].denominator_count for release in releases)
        if (pooled.numerator_count, pooled.denominator_count) != (
            numerator,
            denominator,
        ):
            raise MetricDerivationError(
                f"pooled {metric_id} is {pooled.numerator_count}/"
                f"{pooled.denominator_count}, but its releases sum to "
                f"{numerator}/{denominator}. A pooled value is the sum of the "
                "release counts divided once, never an average of their "
                "percentages (docs/adr/0028)"
            )


class _ObservationProbe:
    """The attributes ``metric_observation_hash`` reads, and nothing else."""

    __slots__ = (
        "ordinal",
        "metric_id",
        "scope",
        "numerator_count",
        "denominator_count",
        "status",
        "fraction_text",
        "source_decision_set_fingerprint",
        "source_eligibility_set_fingerprint",
        "source_view_fingerprint",
        "metric_policy_fingerprint",
    )

    def __init__(self, **fields: object) -> None:
        for name in self.__slots__:
            setattr(self, name, fields.get(name))
