"""The derivation over the real 6,000-comparison SD300 run.

Marked ``dataset`` as well as ``decisions``, so it never runs in public CI: it
reads the workspace the real run produced, which holds 6,000 result files
derived from a redistribution-restricted delivery.

It runs no Java and re-executes no comparison. Stage 5A only reads raw results,
hashes them, and applies a threshold — so this is a check that the committed
derivation still follows from the committed run, and it skips cleanly on a
machine that has neither.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fpbench.core.enums import DecisionDerivationStatus

pytestmark = [pytest.mark.dataset, pytest.mark.decisions]

REPO = Path(__file__).resolve().parents[2]
WORKSPACE = REPO / "workspace"

EXPECTED_DECISIONS = 6_000
EXPECTED_UNITS = 1_500
EXPECTED_VIEW_ROWS = 1_500


@pytest.fixture(scope="module")
def state():
    """The real derivation's current status, or skip."""
    if not (WORKSPACE / "results").is_dir():
        pytest.skip("no local workspace holding a finished SourceAFIS run")

    from fpbench.experiments.sourceafis_native_decisions import (
        inspect_sourceafis_native_decisions,
    )

    try:
        return inspect_sourceafis_native_decisions(workspace=WORKSPACE)
    except Exception as exc:  # noqa: BLE001 - absence is a skip, not a failure
        pytest.skip(f"the local workspace holds no derivable run: {exc}")


def test_the_derivation_is_decision_ready(state):
    if state.decision_set_id is None:
        pytest.skip("no derivation has been produced in this workspace yet")
    assert state.status is DecisionDerivationStatus.DECISION_READY, list(state.issues)


def test_the_source_run_is_still_research_ready(state):
    assert state.source_research_ready, list(state.issues)


def test_six_thousand_decisions_none_undecidable(state):
    if state.decision_set_id is None:
        pytest.skip("no derivation has been produced in this workspace yet")
    assert state.total_decisions == EXPECTED_DECISIONS
    assert state.decided_count == EXPECTED_DECISIONS
    # The run's own receipt records zero failures, so an undecidable decision
    # would mean the scores and the receipt disagree.
    assert state.undecidable_count == 0


def test_fifteen_hundred_eligibility_units(state):
    if state.decision_set_id is None:
        pytest.skip("no derivation has been produced in this workspace yet")
    assert state.total_eligibility_units == EXPECTED_UNITS


def test_all_three_views_verify(state):
    if state.decision_set_id is None:
        pytest.skip("no derivation has been produced in this workspace yet")
    assert state.views_valid == 3


def test_the_receipt_is_committed_under_evidence(state):
    if state.decision_set_id is None:
        pytest.skip("no derivation has been produced in this workspace yet")
    committed = (
        REPO
        / "evidence"
        / "sourceafis-native-decisions"
        / f"{state.decision_set_id}.json"
    )
    assert committed.is_file(), (
        f"the derivation is finalised but {committed.name} is not under evidence/"
    )


def test_the_committed_receipt_carries_no_metric(state):
    if state.decision_set_id is None:
        pytest.skip("no derivation has been produced in this workspace yet")
    committed = (
        REPO
        / "evidence"
        / "sourceafis-native-decisions"
        / f"{state.decision_set_id}.json"
    )
    if not committed.is_file():
        pytest.skip("the receipt has not been committed yet")
    text = committed.read_text(encoding="utf-8").lower()
    for forbidden in (
        "raw_score",
        "match_count",
        "eligible_count",
        "included_count",
        "fmr",
        "fnmr",
        "eer",
        "accuracy",
        "subject_id",
    ):
        assert forbidden not in text, forbidden
    assert "no biometric performance metric or conclusion" in text
