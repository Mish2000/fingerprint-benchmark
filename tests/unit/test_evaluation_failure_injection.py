"""An interrupted finalisation is retryable, and never authoritative.

The failure this guards against is the quiet one: a crash between writing the
report and writing the marker leaves a directory that contains numbers, a
summary and a receipt, and looks finished to anyone reading it with ``ls``. It is
not finished, and the marker is what says so.

Each test stops the chain after one write and asserts three things: no marker
exists, the status is not ``EVALUATION_READY``, and retrying succeeds while
reusing the intermediates rather than producing new ones (spec section 78).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fpbench.core.enums import EvaluationStatus
from fpbench.storage.metric_set_store import MetricSetStore
from metricworld import SPEC_EXAMPLE_SCRIPT, all_matching, build_metric_world

pytestmark = pytest.mark.metrics


@pytest.fixture
def world():
    return build_metric_world(
        {
            "SD300A": SPEC_EXAMPLE_SCRIPT,
            "SD300B": all_matching(10),
            "SD300C": all_matching(10),
        }
    )


def _partial(world, workspace: Path, stop_after: str) -> str:
    """Write the chain up to and including ``stop_after``, then stop.

    Mirrors :meth:`MetricWorld.finalize` step by step rather than calling it
    with a flag, because the point of the test is the order of the writes.
    """
    from fpbench.metrics import build_evaluation_receipt

    definition, policy, profile, manifest, counts, observations = world.metric_set()
    store = MetricSetStore(workspace)
    set_id = manifest.metric_set_id

    if stop_after == "definition":
        # Nothing beyond the definition exists yet: written by ``prepare``,
        # before a single count.
        from fpbench.core.serialization import write_json

        write_json(store.definition_path(world.run_id, set_id), definition)
        return set_id

    store.ensure_metric_set(
        definition=definition,
        policy=policy,
        report_profile=profile,
        manifest=manifest,
        counts=counts,
        observations=observations,
    )
    if stop_after in ("counts", "observations", "manifest"):
        return set_id

    summary = _summary(world, manifest, counts, observations)
    store.ensure_summary(run_id=world.run_id, metric_set_id=set_id, summary=summary)
    if stop_after == "summary":
        return set_id

    markdown = world.render(manifest, counts, observations)
    store.ensure_report(
        run_id=world.run_id, metric_set_id=set_id, markdown=markdown
    )
    if stop_after == "report":
        return set_id

    receipt = build_evaluation_receipt(
        manifest=manifest,
        definition=definition,
        policy=policy,
        observations=observations,
        releases=world.releases,
        structural_counts=world.structural_counts(),
        run_id=world.run_id,
        result_set_id=world.result_set_id,
        decision_profile_id=world.decision_profile_id,
        metric_software=world.software,
        created_utc="2026-01-01T00:00:00+00:00",
    )
    store.ensure_receipt(
        run_id=world.run_id, metric_set_id=set_id, receipt=receipt
    )
    return set_id


def _summary(world, manifest, counts, observations):
    from fpbench.metrics import build_evaluation_summary
    from metricworld import _FakeProfile, _FakeRun

    return build_evaluation_summary(
        manifest=manifest,
        run=_FakeRun(world),
        decision_profile=_FakeProfile(world),
        releases=world.releases,
        counts=counts,
        observations=observations,
        generated_utc="2026-01-01T00:00:00+00:00",
    )


@pytest.mark.parametrize(
    "stop_after,expected",
    [
        ("definition", EvaluationStatus.POLICY_READY),
        ("counts", EvaluationStatus.METRICS_READY),
        ("observations", EvaluationStatus.METRICS_READY),
        ("manifest", EvaluationStatus.METRICS_READY),
        ("summary", EvaluationStatus.METRICS_READY),
        ("report", EvaluationStatus.REPORT_READY),
        ("receipt", EvaluationStatus.REPORT_READY),
    ],
)
def test_a_crash_before_the_marker_leaves_a_retryable_state(
    world, tmp_path: Path, stop_after, expected
) -> None:
    set_id = _partial(world, tmp_path, stop_after)
    store = MetricSetStore(tmp_path)

    assert not store.has_finalization(world.run_id, set_id)
    state = world.inspect(tmp_path, set_id if stop_after != "definition" else None)
    assert state.status is expected
    assert state.status is not EvaluationStatus.EVALUATION_READY


@pytest.mark.parametrize(
    "stop_after",
    ["counts", "manifest", "summary", "report", "receipt"],
)
def test_retrying_succeeds_and_reuses_the_matching_intermediates(
    world, tmp_path: Path, stop_after
) -> None:
    set_id = _partial(world, tmp_path, stop_after)
    store = MetricSetStore(tmp_path)
    written = {
        path.name: path.read_bytes()
        for path in store.metric_set_dir(world.run_id, set_id).iterdir()
        if path.is_file()
    }

    retried = world.finalize(tmp_path)
    assert retried == set_id
    assert world.inspect(tmp_path, set_id).status is EvaluationStatus.EVALUATION_READY

    # Everything already on disk was reused byte for byte, not regenerated.
    for name, payload in written.items():
        assert (
            store.metric_set_dir(world.run_id, set_id) / name
        ).read_bytes() == payload


def test_finalising_twice_is_a_no_op(world, tmp_path: Path) -> None:
    first = world.finalize(tmp_path)
    store = MetricSetStore(tmp_path)
    marker = store.read_finalization(world.run_id, first)

    second = world.finalize(tmp_path)
    assert second == first
    assert (
        store.read_finalization(world.run_id, first).finalization_fingerprint
        == marker.finalization_fingerprint
    )
    assert store.read_finalization(world.run_id, first).created_utc == (
        marker.created_utc
    )


def test_a_marker_over_an_incomplete_chain_is_invalid(world, tmp_path: Path) -> None:
    set_id = _partial(world, tmp_path, "manifest")
    store = MetricSetStore(tmp_path)

    # Forge a marker without the summary, report or receipt beneath it.
    from fpbench.core.serialization import write_json

    write_json(
        store.finalization_path(world.run_id, set_id),
        {
            "schema_version": "1",
            "finalization_id": "evaluationfinal_000000000000",
            "finalization_fingerprint": "0" * 64,
            "source_decision_finalization_fingerprint": world.decision_finalization,
            "metric_definition_fingerprint": "1" * 64,
            "metric_set_fingerprint": "2" * 64,
            "summary_content_hash": "3" * 64,
            "report_content_hash": "4" * 64,
            "evaluation_receipt_fingerprint": "5" * 64,
            "evaluation_receipt_content_hash": "6" * 64,
            "metric_source_commit": world.software.source_revision,
            "metric_source_tree_clean": True,
            "created_utc": "2026-01-01T00:00:00+00:00",
        },
    )
    state = world.inspect(tmp_path, set_id)
    assert state.status is EvaluationStatus.INVALID
    assert state.finalization_present and not state.finalization_valid
