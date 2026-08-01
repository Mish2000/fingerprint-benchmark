"""The stage 6B acceptance conditions, against the real workspace.

Every other paired test runs over a synthetic world, which is the right place to
prove the arithmetic. None of them can prove the thing this stage was actually
for: that two real runs over 6,000 real SD300 comparisons were joined, that
SD300A's provably identical pixels produced provably identical scores, and that
what got committed is what the workspace holds.

These are the exact ids stage 6B produced and committed:

    pairedeval_ee2e0fe7ddb6   over run_7ac1cecc0bb3 and run_4c59fa02a6ab

Skip policy: no workspace, skip. A workspace holding a *broken* comparison is a
failure, not a skip — reporting it as absent is exactly the outcome this suite
exists to prevent (spec section 77).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fpbench.core.enums import PairedEvaluationStatus

pytestmark = [pytest.mark.dataset, pytest.mark.paired_evaluation]

REPO = Path(__file__).resolve().parents[2]
WORKSPACE = REPO / "workspace"

NATIVE_RUN_ID = "run_7ac1cecc0bb3"
CANONICAL_RUN_ID = "run_4c59fa02a6ab"
PAIRED_ID = "pairedeval_ee2e0fe7ddb6"

EVIDENCE = REPO / "evidence" / "sourceafis-native-vs-canonical500"

#: SD300A: 500 subjects' worth of comparisons across all four protocol stages.
CONTROL_PAIRS = 2000


def _require_workspace() -> None:
    for run_id in (NATIVE_RUN_ID, CANONICAL_RUN_ID):
        if not (WORKSPACE / "results" / run_id).is_dir():
            pytest.skip(f"no run {run_id} in this workspace")


@pytest.fixture(scope="module")
def state():
    _require_workspace()
    from fpbench.experiments.sourceafis_native_vs_canonical500 import (
        inspect_paired_experiment,
    )

    return inspect_paired_experiment(workspace=WORKSPACE, repository_root=REPO)


@pytest.fixture(scope="module")
def store():
    from fpbench.storage.paired_evaluation_store import PairedEvaluationStore

    return PairedEvaluationStore(WORKSPACE)


# ------------------------------------------------------------------- readiness


def test_the_real_comparison_is_paired_evaluation_ready(state):
    assert state.paired_evaluation_id == PAIRED_ID
    assert state.status is PairedEvaluationStatus.PAIRED_EVALUATION_READY, list(
        state.issues
    )
    assert state.issues == ()
    assert state.manifest_valid and state.summary_valid
    assert state.report_valid and state.receipt_valid
    assert state.finalization_valid


def test_the_real_comparison_has_the_expected_structure(state):
    assert state.total_paired_comparisons == 6000
    assert state.total_eligibility_units == 1500
    assert 0 < state.total_common_eligible_rows <= state.total_eligibility_units


# --------------------------------------------------------------- the control


def test_sd300a_reproduced_exactly(state, store):
    """The acceptance condition the whole stage turns on.

    SD300A is delivered at 500 ppi, so its canonical preparation is an identity:
    the same pixels through the same build at the same threshold. Anything other
    than complete agreement here would mean the preparation pipeline is not
    doing what the previous stage proved it does, and every number downstream
    would be describing something else.
    """
    assert state.control_audit_clean
    control = store.read_control_audit(PAIRED_ID)
    assert control.planned_sd300a_pairs == CONTROL_PAIRS
    assert control.compared_scores == CONTROL_PAIRS
    assert control.equal_scores == CONTROL_PAIRS
    assert control.equal_result_statuses == CONTROL_PAIRS
    assert control.equal_decisions == CONTROL_PAIRS
    assert control.issues == ()


# ------------------------------------------------------------- the evidence


@pytest.mark.parametrize("suffix", [".json", ".md"])
def test_the_committed_evidence_matches_the_workspace_byte_for_byte(
    state, store, suffix
):
    committed = EVIDENCE / f"{PAIRED_ID}{suffix}"
    assert committed.is_file(), f"{committed} has not been committed"

    workspace_path = (
        store.receipt_path(PAIRED_ID)
        if suffix == ".json"
        else store.report_path(PAIRED_ID)
    )
    assert committed.read_bytes() == workspace_path.read_bytes()


def test_the_committed_receipt_cites_the_frozen_native_identities(state):
    """A comparison against a moved native chain would be a different claim."""
    receipt = json.loads((EVIDENCE / f"{PAIRED_ID}.json").read_text("utf-8"))
    assert receipt["native_run_id"] == NATIVE_RUN_ID
    assert receipt["native_result_set_id"] == "resultset_2bf3cacfd806"
    assert receipt["native_decision_set_id"] == "decisionset_0122544e71b1"
    assert receipt["native_eligibility_set_id"] == "eligibilityset_77dbf75cdc76"
    assert receipt["native_metric_set_id"] == "metricset_f6ffa71f3880"
    assert receipt["canonical_run_id"] == CANONICAL_RUN_ID


def test_the_committed_receipt_publishes_no_per_pair_detail(state, store):
    """The sanitiser ran at build time; this checks the bytes that shipped."""
    from fpbench.paired import require_sanitised_paired_receipt

    require_sanitised_paired_receipt(store.read_receipt(PAIRED_ID))

    rendered = (EVIDENCE / f"{PAIRED_ID}.json").read_text("utf-8").lower()
    for marker in ("job_", "_plainself", "_rollself", "_nonmated", "raw_score"):
        assert marker not in rendered, f"the receipt names {marker!r}"


# ---------------------------------------------------------- forbidden claims


def test_the_real_report_makes_no_claim_this_stage_may_not_make(state, store):
    """Spec sections 63 and 80, checked against the published words.

    Only the numbered body between section 1 and the closing Limitations is
    searched. The disclaimers bracket it on both sides — the opening statement
    and sections 13 and 14 name every forbidden quantity on purpose, to say it
    is absent. A check that could not tell "no confidence interval is reported"
    from "confidence interval: ±2 pp" would be satisfied by deleting the
    disclaimer, which is the wrong direction entirely.

    The policy refuses to permit these and the builder never computes them, so
    this is the third line of defence rather than the first. It is here because
    the report is the artefact somebody will quote, and a phrase can arrive
    through prose long after the machinery to compute it was refused.
    """
    report = store.read_report(PAIRED_ID).lower()
    start = report.find("## 1. evaluation identity")
    end = report.find("## 13. limitations")
    assert 0 < start < end, "the report no longer opens and closes as expected"
    body = report[start:end]

    for phrase in (
        "roc",
        "equal error rate",
        "eer",
        "confidence interval",
        "statistically significant",
        "significance",
        "p-value",
        "mcnemar",
        "bootstrap",
        "more accurate",
        "outperform",
    ):
        assert phrase not in body, f"the report body says {phrase!r}"


def test_the_real_report_states_what_it_does_not_establish(state, store):
    report = store.read_report(PAIRED_ID).lower()
    assert "does not establish" in report
    assert "better or worse" in report
    assert "caused" in report or "causal" in report


def test_an_incomparable_rate_is_printed_as_incomparable(state, store):
    """The per-run conditional FNMR is over two different eligible sets.

    Its two numbers are both true and their difference is meaningless, so the
    report has to say so rather than quietly omitting the row — an omitted row
    is one a reader recomputes for themselves (docs/adr/0038).
    """
    report = store.read_report(PAIRED_ID)
    assert "not comparable" in report

    observations = store.read_observations(PAIRED_ID)
    incomparable = [item for item in observations if not item.has_difference]
    assert incomparable, "no observation was reported as incomparable"
    for item in incomparable:
        assert item.difference_numerator is None
        assert item.difference_denominator is None
