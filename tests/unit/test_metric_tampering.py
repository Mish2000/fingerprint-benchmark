"""Every edit to a finalised evaluation turns its status INVALID.

Fifteen tampering cases, one per artefact the specification names. Several of
them are *good* forgeries — the count record's own hash is recomputed, so the
model accepts it on read — because the interesting question is not whether a
self-hash works but whether a self-consistent lie survives re-derivation from
the decisions. It does not: the verifier recomputes the counts from the views
rather than checking them against themselves (spec sections 46, 77).

Note what is deliberately *not* asserted: which message comes back. A tampering
test that pinned the wording would break every time an error string improved,
and the property that matters is binary.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fpbench.core.enums import EvaluationStatus, MetricScopeKind
from fpbench.core.metric_models import CountFamily, MetricScope
from fpbench.storage.metric_set_store import MetricSetStore
from metricworld import (
    SPEC_EXAMPLE_SCRIPT,
    all_matching,
    build_metric_world,
    rebuild_count_record,
    rebuild_observation,
    rewrite_counts,
    rewrite_observations,
)

pytestmark = pytest.mark.metrics


@pytest.fixture
def finalised(tmp_path: Path):
    """A world whose evaluation is complete and verified before tampering."""
    world = build_metric_world(
        {
            "SD300A": SPEC_EXAMPLE_SCRIPT,
            "SD300B": all_matching(10),
            "SD300C": all_matching(10),
        }
    )
    set_id = world.finalize(tmp_path)
    assert world.inspect(tmp_path, set_id).status is EvaluationStatus.EVALUATION_READY
    return world, tmp_path, set_id, MetricSetStore(tmp_path)


def _assert_invalid(world, workspace, set_id) -> None:
    state = world.inspect(workspace, set_id)
    assert state.status is EvaluationStatus.INVALID, (
        f"tampering went unnoticed: {state.status.value}"
    )
    assert state.issues


def _edit_json(path: Path, mutate) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


# ------------------------------------------------------------- count records


def test_a_tampered_count_record_is_caught(finalised) -> None:
    world, workspace, set_id, store = finalised
    counts = list(store.read_counts(world.run_id, set_id))
    index = next(
        position
        for position, record in enumerate(counts)
        if record.count_family == CountFamily.PLAIN_SELF
        and record.scope.label == "SD300A"
    )
    counts[index] = rebuild_count_record(
        counts[index],
        counts={"match": 9, "non_match": 0, "undecidable": 1, "decided": 9},
    )
    rewrite_counts(store, world.run_id, set_id, counts)
    _assert_invalid(world, workspace, set_id)


def test_a_tampered_count_source_fingerprint_is_caught(finalised) -> None:
    world, workspace, set_id, store = finalised
    counts = list(store.read_counts(world.run_id, set_id))
    counts[0] = rebuild_count_record(counts[0], source_fingerprint="9" * 64)
    rewrite_counts(store, world.run_id, set_id, counts)
    _assert_invalid(world, workspace, set_id)


# -------------------------------------------------------------- observations


def test_a_tampered_numerator_is_caught(finalised) -> None:
    world, workspace, set_id, store = finalised
    observations = list(store.read_observations(world.run_id, set_id))
    observations[0] = rebuild_observation(observations[0], numerator_count=0)
    rewrite_observations(store, world.run_id, set_id, observations)
    _assert_invalid(world, workspace, set_id)


def test_a_tampered_denominator_is_caught(finalised) -> None:
    world, workspace, set_id, store = finalised
    observations = list(store.read_observations(world.run_id, set_id))
    # 8/9 quietly restated as 8/10 — the exact substitution the denominator
    # enum exists to prevent.
    observations[0] = rebuild_observation(observations[0], denominator_count=10)
    rewrite_observations(store, world.run_id, set_id, observations)
    _assert_invalid(world, workspace, set_id)


def test_a_tampered_scope_release_is_caught(finalised) -> None:
    world, workspace, set_id, store = finalised
    observations = list(store.read_observations(world.run_id, set_id))
    observations[0] = rebuild_observation(
        observations[0], scope=MetricScope(MetricScopeKind.RELEASE, "SD300C")
    )
    rewrite_observations(store, world.run_id, set_id, observations)
    _assert_invalid(world, workspace, set_id)


def test_a_tampered_metric_id_is_caught(finalised) -> None:
    world, workspace, set_id, store = finalised
    observations = list(store.read_observations(world.run_id, set_id))
    observations[0] = rebuild_observation(
        observations[0], metric_id="plain_self_match_rate_attempt"
    )
    rewrite_observations(store, world.run_id, set_id, observations)
    _assert_invalid(world, workspace, set_id)


def test_a_tampered_source_view_fingerprint_is_caught(finalised) -> None:
    world, workspace, set_id, store = finalised
    observations = list(store.read_observations(world.run_id, set_id))
    index = next(
        position
        for position, observation in enumerate(observations)
        if observation.source_view_fingerprint is not None
    )
    observations[index] = rebuild_observation(
        observations[index], source_view_fingerprint="7" * 64
    )
    rewrite_observations(store, world.run_id, set_id, observations)
    _assert_invalid(world, workspace, set_id)


def test_a_tampered_policy_fingerprint_on_an_observation_is_caught(
    finalised,
) -> None:
    world, workspace, set_id, store = finalised
    observations = list(store.read_observations(world.run_id, set_id))
    observations[0] = rebuild_observation(
        observations[0], metric_policy_fingerprint="6" * 64
    )
    rewrite_observations(store, world.run_id, set_id, observations)
    _assert_invalid(world, workspace, set_id)


def test_a_tampered_pooled_observation_is_caught(finalised) -> None:
    world, workspace, set_id, store = finalised
    observations = list(store.read_observations(world.run_id, set_id))
    index = next(
        position
        for position, observation in enumerate(observations)
        if observation.scope.is_pooled and observation.numerator_count > 0
    )
    observations[index] = rebuild_observation(
        observations[index],
        numerator_count=observations[index].numerator_count - 1,
    )
    rewrite_observations(store, world.run_id, set_id, observations)
    _assert_invalid(world, workspace, set_id)


def test_reordering_observations_without_changing_one_is_caught(finalised) -> None:
    world, workspace, set_id, store = finalised
    observations = list(store.read_observations(world.run_id, set_id))
    first, second = observations[0], observations[1]
    observations[0] = rebuild_observation(second, ordinal=0)
    observations[1] = rebuild_observation(first, ordinal=1)
    rewrite_observations(store, world.run_id, set_id, observations)
    _assert_invalid(world, workspace, set_id)


# ------------------------------------------------------------------ manifest


def test_a_tampered_manifest_count_is_caught(finalised) -> None:
    world, workspace, set_id, store = finalised
    _edit_json(
        store.manifest_path(world.run_id, set_id),
        lambda payload: payload.__setitem__("total_observations", 1),
    )
    _assert_invalid(world, workspace, set_id)


def test_a_tampered_metric_set_fingerprint_is_caught(finalised) -> None:
    world, workspace, set_id, store = finalised
    _edit_json(
        store.manifest_path(world.run_id, set_id),
        lambda payload: payload.__setitem__("metric_set_fingerprint", "5" * 64),
    )
    _assert_invalid(world, workspace, set_id)


def test_a_tampered_stored_policy_is_caught(finalised) -> None:
    world, workspace, set_id, store = finalised
    _edit_json(
        store.policy_path(world.run_id, set_id),
        lambda payload: payload.__setitem__("percentage_decimal_places", 9),
    )
    _assert_invalid(world, workspace, set_id)


# --------------------------------------------------- summary, report, receipt


def test_a_tampered_summary_value_is_caught(finalised) -> None:
    world, workspace, set_id, store = finalised

    def mutate(payload):
        payload["observations"][0]["numerator_count"] = 0

    _edit_json(store.summary_path(world.run_id, set_id), mutate)
    _assert_invalid(world, workspace, set_id)


def test_tampered_report_bytes_are_caught(finalised) -> None:
    world, workspace, set_id, store = finalised
    path = store.report_path(world.run_id, set_id)
    path.write_text(
        path.read_text(encoding="utf-8") + "\nFMR = 0.0000%\n", encoding="utf-8"
    )
    _assert_invalid(world, workspace, set_id)


def test_a_tampered_receipt_value_is_caught(finalised) -> None:
    world, workspace, set_id, store = finalised

    def mutate(payload):
        metric = next(iter(payload["metrics"]))
        scope = next(iter(payload["metrics"][metric]))
        payload["metrics"][metric][scope]["denominator"] += 1

    _edit_json(store.receipt_path(world.run_id, set_id), mutate)
    _assert_invalid(world, workspace, set_id)


def test_a_tampered_structural_count_in_the_receipt_is_caught(finalised) -> None:
    world, workspace, set_id, store = finalised
    _edit_json(
        store.receipt_path(world.run_id, set_id),
        lambda payload: payload["structural_counts"].__setitem__("decisions", 1),
    )
    _assert_invalid(world, workspace, set_id)


# ---------------------------------------------------------- finalization marker


def test_a_tampered_finalization_marker_is_caught(finalised) -> None:
    world, workspace, set_id, store = finalised
    _edit_json(
        store.finalization_path(world.run_id, set_id),
        lambda payload: payload.__setitem__("report_content_hash", "4" * 64),
    )
    _assert_invalid(world, workspace, set_id)


def test_a_marker_naming_a_different_decision_derivation_is_caught(
    finalised,
) -> None:
    world, workspace, set_id, _ = finalised
    state = world.inspect(
        workspace, set_id, decision_finalization_fingerprint="3" * 64
    )
    assert state.status is EvaluationStatus.INVALID


def test_a_source_derivation_that_is_no_longer_ready_invalidates_everything(
    finalised,
) -> None:
    from fpbench.core.enums import DecisionDerivationStatus

    world, workspace, set_id, _ = finalised
    state = world.inspect(
        workspace, set_id, decision_status=DecisionDerivationStatus.INVALID
    )
    assert state.status is EvaluationStatus.INVALID
    assert not state.source_decision_ready
