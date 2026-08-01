"""The committed evaluation of the real SD300 run, re-verified from its workspace.

Marked ``dataset`` and excluded from public CI: it needs the workspace holding
the 6,000-comparison run, which is 113 GB of NIST delivery away from a runner.
When that workspace is present, this is the test that proves the published
numbers are still the numbers on disk.

The skip logic is the part worth reading. A missing workspace is a legitimate
absence and skips. An evaluation that has not been run yet is a legitimate
absence and skips. A workspace that exists and whose chain does not verify is a
**failure** — the whole point of the stage is that a broken chain is loud, and
``except Exception: pytest.skip(...)`` would turn every regression into a green
run (spec section 88).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from fpbench.core.enums import EvaluationStatus
from fpbench.experiments.sourceafis_native_evaluation import (
    DEFAULT_WORKSPACE,
    inspect_sourceafis_native_evaluation,
    load_evaluation_config,
    read_native_verified_report,
)
from fpbench.metrics.receipt import EVIDENCE_DIRECTORY
from fpbench.storage.metric_set_store import MetricSetStore

pytestmark = [pytest.mark.dataset, pytest.mark.metrics]

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def workspace() -> Path:
    """The workspace holding the finished run, or skip."""
    root = Path(os.environ.get("FPBENCH_WORKSPACE", DEFAULT_WORKSPACE))
    if not (root / "results").is_dir():
        pytest.skip(f"no fpbench workspace at {root}")
    return root


@pytest.fixture(scope="module")
def evaluation(workspace: Path):
    """The verified state of the committed evaluation, or skip if absent."""
    config = load_evaluation_config(repository_root=REPOSITORY_ROOT)
    run_directory = workspace / "results" / config.run_id
    if not run_directory.is_dir():
        pytest.skip(f"this workspace does not hold run {config.run_id}")

    evaluations = run_directory / "evaluations"
    if not evaluations.is_dir() or not any(evaluations.iterdir()):
        pytest.skip(
            f"run {config.run_id} has no evaluation yet; run "
            "'python -m fpbench.experiments.sourceafis_native_evaluation derive'"
        )

    # Past this point every failure is a real one. The chain either verifies or
    # it does not, and a broken chain must not be reported as an absent one.
    state = inspect_sourceafis_native_evaluation(
        workspace=workspace, config=config, repository_root=REPOSITORY_ROOT
    )
    return config, state


def test_the_real_evaluation_is_evaluation_ready(workspace, evaluation) -> None:
    _, state = evaluation
    assert state.status is EvaluationStatus.EVALUATION_READY, list(state.issues)
    assert state.source_decision_ready
    assert state.counts_valid and state.observations_valid
    assert state.metric_set_valid and state.summary_valid
    assert state.report_valid and state.receipt_valid
    assert state.finalization_valid


def test_the_real_evaluation_has_the_expected_structure(workspace, evaluation) -> None:
    config, state = evaluation
    store = MetricSetStore(workspace)
    set_id = str(state.metric_set_id)

    receipt = store.read_receipt(config.run_id, set_id)
    assert dict(receipt.structural_counts) == {
        "decisions": config.expected_decisions,
        "eligibility_units": config.expected_eligibility_units,
        "unconditional_rows": config.expected_rows_per_view,
        "conditional_rows": config.expected_rows_per_view,
        "negative_sanity_rows": config.expected_rows_per_view,
    }
    assert tuple(receipt.releases) == config.expected_releases


def test_every_pooled_value_is_the_sum_of_its_releases(workspace, evaluation) -> None:
    config, state = evaluation
    observations = MetricSetStore(workspace).read_observations(
        config.run_id, str(state.metric_set_id)
    )
    by_metric: dict[str, dict[str, tuple[int, int]]] = {}
    for observation in observations:
        by_metric.setdefault(observation.metric_id, {})[observation.scope.label] = (
            observation.numerator_count,
            observation.denominator_count,
        )
    for metric_id, by_scope in by_metric.items():
        releases = [by_scope[release] for release in config.expected_releases]
        assert by_scope["pooled"] == (
            sum(pair[0] for pair in releases),
            sum(pair[1] for pair in releases),
        ), metric_id


def test_the_committed_evidence_matches_the_workspace_byte_for_byte(
    workspace, evaluation
) -> None:
    config, state = evaluation
    set_id = str(state.metric_set_id)
    store = MetricSetStore(workspace)

    for suffix, workspace_path in (
        (".json", store.receipt_path(config.run_id, set_id)),
        (".md", store.report_path(config.run_id, set_id)),
    ):
        committed = REPOSITORY_ROOT / EVIDENCE_DIRECTORY / f"{set_id}{suffix}"
        assert committed.is_file(), f"{committed} has not been committed"
        assert committed.read_bytes() == workspace_path.read_bytes()


def test_the_verified_report_is_the_stored_one(workspace, evaluation) -> None:
    config, state = evaluation
    shown = read_native_verified_report(
        workspace=workspace, repository_root=REPOSITORY_ROOT
    )
    assert shown == MetricSetStore(workspace).read_report(
        config.run_id, str(state.metric_set_id)
    )


def test_the_real_evaluation_makes_no_false_match_rate_claim(
    workspace, evaluation
) -> None:
    import re

    config, state = evaluation
    report = MetricSetStore(workspace).read_report(
        config.run_id, str(state.metric_set_id)
    )
    assert re.search(r"\bFMR\s*[=:]", report, re.IGNORECASE) is None
    assert "not a general" in report
    assert "Same-subject different-finger negative sanity check" in report
