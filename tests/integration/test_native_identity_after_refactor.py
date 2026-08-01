"""Extracting the shared engines changed no native identity.

Stage 6B moved the derivation and evaluation logic into engines both SourceAFIS
paths call. That refactor is only safe if the native chain comes out *bit for
bit* the same — same decision set, same eligibility set, same three views, same
metric set, same report bytes, same receipt fingerprints.

A refactor that changed any of them would not be a refactor. It would be a new
derivation wearing an old id, cited by committed evidence that no longer
describes it, and it would need a research argument rather than a green test
(spec section 4).

These are the exact ids stage 5A and 5B produced and committed:

    run_7ac1cecc0bb3
    resultset_2bf3cacfd806
    decisionset_0122544e71b1
    eligibilityset_77dbf75cdc76
    metricset_f6ffa71f3880

Skip policy: no workspace, skip. A workspace whose native chain is broken is a
failure, not a skip — that is the whole point of running this (spec section 77).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fpbench.core.enums import DecisionDerivationStatus, EvaluationStatus

pytestmark = [pytest.mark.dataset, pytest.mark.decisions, pytest.mark.metrics]

REPO = Path(__file__).resolve().parents[2]
WORKSPACE = REPO / "workspace"

RUN_ID = "run_7ac1cecc0bb3"
RESULT_SET_ID = "resultset_2bf3cacfd806"
DECISION_SET_ID = "decisionset_0122544e71b1"
ELIGIBILITY_SET_ID = "eligibilityset_77dbf75cdc76"
METRIC_SET_ID = "metricset_f6ffa71f3880"

DECISION_EVIDENCE = (
    REPO / "evidence" / "sourceafis-native-decisions" / f"{DECISION_SET_ID}.json"
)
EVALUATION_EVIDENCE = (
    REPO / "evidence" / "sourceafis-native-evaluation" / f"{METRIC_SET_ID}.json"
)
REPORT_EVIDENCE = (
    REPO / "evidence" / "sourceafis-native-evaluation" / f"{METRIC_SET_ID}.md"
)


def _require_workspace() -> None:
    if not (WORKSPACE / "results" / RUN_ID).is_dir():
        pytest.skip(f"no native run {RUN_ID} in this workspace")


@pytest.fixture(scope="module")
def decision_state():
    _require_workspace()
    from fpbench.experiments.sourceafis_native_decisions import (
        inspect_sourceafis_native_decisions,
    )

    return inspect_sourceafis_native_decisions(workspace=WORKSPACE)


@pytest.fixture(scope="module")
def evaluation_state():
    _require_workspace()
    from fpbench.experiments.sourceafis_native_evaluation import (
        inspect_sourceafis_native_evaluation,
    )

    return inspect_sourceafis_native_evaluation(workspace=WORKSPACE)


# ------------------------------------------------------------------ identities


def test_the_native_decision_chain_still_has_its_original_identities(decision_state):
    assert decision_state.run_id == RUN_ID
    assert decision_state.decision_set_id == DECISION_SET_ID
    assert decision_state.status is DecisionDerivationStatus.DECISION_READY
    assert decision_state.total_decisions == 6000
    assert decision_state.decided_count == 6000
    assert decision_state.undecidable_count == 0
    assert decision_state.total_eligibility_units == 1500
    assert decision_state.views_valid == 3
    assert decision_state.receipt_valid
    assert decision_state.finalization_valid


def test_the_native_evaluation_still_has_its_original_identity(evaluation_state):
    assert evaluation_state.run_id == RUN_ID
    assert evaluation_state.metric_set_id == METRIC_SET_ID
    assert evaluation_state.status is EvaluationStatus.EVALUATION_READY
    assert evaluation_state.counts_valid
    assert evaluation_state.observations_valid
    assert evaluation_state.summary_valid
    assert evaluation_state.report_valid
    assert evaluation_state.receipt_valid
    assert evaluation_state.finalization_valid


def test_the_committed_decision_receipt_still_describes_the_stored_chain():
    _require_workspace()
    from fpbench.storage.decision_set_store import DecisionSetStore

    committed = json.loads(DECISION_EVIDENCE.read_text("utf-8"))
    stored = DecisionSetStore(WORKSPACE).read_receipt(RUN_ID, DECISION_SET_ID)

    assert committed["run_id"] == stored.run_id == RUN_ID
    assert committed["result_set_id"] == stored.result_set_id == RESULT_SET_ID
    assert committed["decision_set_id"] == stored.decision_set_id == DECISION_SET_ID
    assert (
        committed["eligibility_set_id"]
        == stored.eligibility_set_id
        == ELIGIBILITY_SET_ID
    )
    assert (
        committed["decision_set_fingerprint"] == stored.decision_set_fingerprint
    )
    assert (
        committed["eligibility_set_fingerprint"]
        == stored.eligibility_set_fingerprint
    )
    for name in (
        "unconditional_view_fingerprint",
        "conditional_view_fingerprint",
        "non_mated_view_fingerprint",
        "decision_profile_fingerprint",
        "run_fingerprint",
        "result_set_fingerprint",
    ):
        assert committed[name] == getattr(stored, name), name
    assert committed["view_total_rows"] == dict(stored.view_total_rows)


def test_the_committed_evaluation_receipt_still_describes_the_stored_metric_set():
    _require_workspace()
    from fpbench.storage.metric_set_store import MetricSetStore

    committed = json.loads(EVALUATION_EVIDENCE.read_text("utf-8"))
    stored = MetricSetStore(WORKSPACE).read_receipt(RUN_ID, METRIC_SET_ID)

    assert committed["metric_set_id"] == stored.metric_set_id == METRIC_SET_ID
    assert committed["metric_set_fingerprint"] == stored.metric_set_fingerprint
    assert committed["decision_set_id"] == stored.decision_set_id == DECISION_SET_ID
    assert committed["metric_policy_fingerprint"] == stored.metric_policy_fingerprint
    assert committed["metrics"] == dict(stored.metrics)
    assert committed["structural_counts"] == dict(stored.structural_counts)


def test_the_committed_report_is_still_byte_identical_to_the_stored_one():
    """The strongest of these checks, and the cheapest to break.

    A report is rendered from the counts, so any change to how a number is
    formatted, ordered or labelled shows up here as a byte difference — including
    changes that leave every fingerprint intact.
    """
    _require_workspace()
    from fpbench.storage.metric_set_store import MetricSetStore

    stored = MetricSetStore(WORKSPACE).read_report(RUN_ID, METRIC_SET_ID)
    assert REPORT_EVIDENCE.read_text("utf-8") == stored


def test_the_verified_report_is_readable_through_the_wrapper():
    _require_workspace()
    from fpbench.experiments.sourceafis_native_evaluation import (
        read_native_verified_report,
    )

    report = read_native_verified_report(workspace=WORKSPACE)
    assert METRIC_SET_ID in report
    assert "threshold" in report.lower()
