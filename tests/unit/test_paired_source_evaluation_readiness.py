"""A paired comparison may rest only on two fully ready evaluations.

The paired tables can be rebuilt from decisions even when a source evaluation's
publication chain is incomplete.  That is not enough: both named evaluations
must independently remain ``EVALUATION_READY`` before the comparison may be
prepared, inspected, shown or finalised.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

import fpbench.paired.sources as paired_sources
from fpbench.core.enums import EvaluationStatus
from fpbench.core.errors import PairedSourceMismatchError
from fpbench.core.serialization import to_plain, write_json
from fpbench.experiments.sourceafis_evaluation import (
    SourceAfisEvaluationExperimentSpec,
)
from fpbench.metrics import build_evaluation_finalization_marker
from fpbench.storage.metric_set_store import MetricSetStore
from metricworld import SPEC_EXAMPLE_SCRIPT, build_metric_world

pytestmark = [pytest.mark.metrics, pytest.mark.paired_evaluation]


@pytest.fixture
def source_evaluation(tmp_path: Path):
    world = build_metric_world({"SD300A": SPEC_EXAMPLE_SCRIPT})
    metric_set_id = world.finalize(tmp_path)
    state = world.inspect(tmp_path, metric_set_id)
    assert state.status is EvaluationStatus.EVALUATION_READY
    return world, tmp_path, metric_set_id, MetricSetStore(tmp_path)


def _evaluation_spec() -> SourceAfisEvaluationExperimentSpec:
    return SourceAfisEvaluationExperimentSpec(
        evaluation_config=Path("synthetic-evaluation.yaml"),
        decision_spec=object(),  # type: ignore[arg-type]
        evidence_directory=Path("evidence") / "synthetic-evaluation",
    )


def _require_ready(world, workspace, metric_set_id, monkeypatch) -> None:
    spec = _evaluation_spec()
    repository_root = Path("synthetic-repository-root")
    calls = []

    def inspect(**arguments):
        calls.append(arguments)
        return world.inspect(workspace, arguments["metric_set_id_override"])

    monkeypatch.setattr(paired_sources, "inspect_evaluation_experiment", inspect)
    paired_sources._require_evaluation_ready(
        label="native",
        spec=spec,
        workspace=workspace,
        repository_root=repository_root,
        run_id=world.run_id,
        metric_set_id=metric_set_id,
    )
    assert calls == [
        {
            "spec": spec,
            "workspace": workspace,
            "repository_root": repository_root,
            "metric_set_id_override": metric_set_id,
        }
    ]


def test_a_ready_source_evaluation_is_accepted(source_evaluation, monkeypatch):
    world, workspace, metric_set_id, _ = source_evaluation
    _require_ready(world, workspace, metric_set_id, monkeypatch)


@pytest.mark.parametrize("artifact", ["summary", "report", "receipt"])
def test_a_missing_source_publication_artefact_invalidates_the_paired_source(
    source_evaluation, monkeypatch, artifact
):
    world, workspace, metric_set_id, store = source_evaluation
    path = getattr(store, f"{artifact}_path")(world.run_id, metric_set_id)
    path.unlink()

    with pytest.raises(PairedSourceMismatchError, match="not evaluation_ready"):
        _require_ready(world, workspace, metric_set_id, monkeypatch)

def test_a_coordinated_source_report_receipt_and_marker_forgery_is_rejected(
    source_evaluation, monkeypatch
):
    world, workspace, metric_set_id, store = source_evaluation

    report = store.read_report(world.run_id, metric_set_id)
    forged_report = report + "\nThis evaluation now claims superiority.\n"
    store.report_path(world.run_id, metric_set_id).write_text(
        forged_report, encoding="utf-8"
    )

    receipt = store.read_receipt(world.run_id, metric_set_id)
    receipt_fields = dict(to_plain(receipt))
    metrics = receipt_fields["metrics"]
    changed = False
    for scopes in metrics.values():
        for counts in scopes.values():
            if counts["numerator"] > 0:
                counts["numerator"] -= 1
                changed = True
                break
        if changed:
            break
    assert changed
    forged_receipt = replace(receipt, metrics=metrics)
    write_json(store.receipt_path(world.run_id, metric_set_id), forged_receipt)

    original_marker = store.read_finalization(world.run_id, metric_set_id)
    forged_marker = build_evaluation_finalization_marker(
        definition=store.read_definition(world.run_id, metric_set_id),
        manifest=store.read_manifest(world.run_id, metric_set_id),
        summary=store.read_summary(world.run_id, metric_set_id),
        markdown=forged_report,
        receipt=forged_receipt,
        decision_finalization_fingerprint=world.decision_finalization,
        metric_software=world.software,
        created_utc=original_marker.created_utc,
    )
    write_json(store.finalization_path(world.run_id, metric_set_id), forged_marker)
    assert store.read_finalization(
        world.run_id, metric_set_id
    ).finalization_fingerprint == forged_marker.finalization_fingerprint

    with pytest.raises(PairedSourceMismatchError, match="not evaluation_ready"):
        _require_ready(world, workspace, metric_set_id, monkeypatch)
