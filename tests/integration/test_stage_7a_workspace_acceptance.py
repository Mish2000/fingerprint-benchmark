"""Stage 7A rearranged the code. It must not have moved a single artefact.

Everything in stage 7A is a refactor: the orchestration became generic, the
prepared-input checks moved to a module no algorithm owns, the pipeline metadata
became a typed model, and the runtime guard learned to watch several files. Every
one of those touches code that two finished runs, two derivations, two
evaluations and one paired comparison were produced by.

A refactor that changed any of their identities would not be a refactor. It would
be new evidence wearing an old id, cited by committed receipts that no longer
describe it — and the whole of stages 4B through 6B would need re-arguing rather
than re-running.

So this file re-verifies the whole chain, from the files, with the stage 7A code:

    run_7ac1cecc0bb3   resultset_2bf3cacfd806   native
    run_4c59fa02a6ab   resultset_087b084fb8a8   canonical
    decisionset_0122544e71b1   decisionset_df0d584bdede
    metricset_f6ffa71f3880     metricset_b4c70fbfd1d3
    pairedeval_ee2e0fe7ddb6

``RESEARCH_READY`` is the strongest of these assertions and the least obvious.
Reaching it requires the research receipt to verify, and verifying a receipt
re-runs the algorithm validator and compares the fingerprint it produces against
the one the receipt recorded. So a status of ``RESEARCH_READY`` here *is* the
statement that extracting the prepared-input checks changed no issue, no code, no
count and no ordering (spec sections 5 and 27).

Skip policy: no workspace, skip. A workspace whose chain is broken is a failure,
not a skip — that is the entire point of running this (spec section 86).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fpbench.core.enums import (
    DecisionDerivationStatus,
    EvaluationStatus,
    PairedEvaluationStatus,
    ResearchRunStatus,
)

pytestmark = [pytest.mark.dataset, pytest.mark.adapter_contract]

REPO = Path(__file__).resolve().parents[2]
WORKSPACE = REPO / "workspace"


@pytest.fixture(scope="module", autouse=True)
def require_results_workspace():
    """Skip only when this module's tests are selected, not during collection."""
    if not (WORKSPACE / "results").is_dir():
        pytest.skip("no persisted results workspace is available")

NATIVE_RUN = "run_7ac1cecc0bb3"
NATIVE_RESULT_SET = "resultset_2bf3cacfd806"
CANONICAL_RUN = "run_4c59fa02a6ab"
CANONICAL_RESULT_SET = "resultset_087b084fb8a8"

NATIVE_DECISION_SET = "decisionset_0122544e71b1"
CANONICAL_DECISION_SET = "decisionset_df0d584bdede"

NATIVE_METRIC_SET = "metricset_f6ffa71f3880"
CANONICAL_METRIC_SET = "metricset_b4c70fbfd1d3"

PAIRED_EVALUATION = "pairedeval_ee2e0fe7ddb6"


def require_run(run_id: str) -> None:
    assert (WORKSPACE / "results" / run_id).is_dir(), (
        f"persisted workspace is missing required run {run_id}"
    )


# ------------------------------------------------------------------ the runs


@pytest.fixture(scope="module")
def native_state():
    require_run(NATIVE_RUN)
    from fpbench.experiments.sourceafis_native_full import (
        inspect_sourceafis_native_run,
    )

    return inspect_sourceafis_native_run(workspace=WORKSPACE)


@pytest.fixture(scope="module")
def canonical_state():
    require_run(CANONICAL_RUN)
    from fpbench.experiments.sourceafis_canonical500_full import (
        inspect_sourceafis_canonical500_run,
    )

    return inspect_sourceafis_canonical500_run(workspace=WORKSPACE)


def test_the_native_run_is_still_research_ready(native_state):
    assert native_state.run_id == NATIVE_RUN
    assert native_state.status is ResearchRunStatus.RESEARCH_READY, list(
        native_state.issues
    )
    assert native_state.stored_results == 6000
    assert native_state.missing_results == 0
    assert native_state.runtime_bundle_valid
    assert native_state.result_set_valid
    assert native_state.receipt_valid
    assert native_state.finalization_marker_valid


def test_the_canonical_run_is_still_research_ready(canonical_state):
    """The one whose validation includes every prepared-input check."""
    assert canonical_state.run_id == CANONICAL_RUN
    assert canonical_state.status is ResearchRunStatus.RESEARCH_READY, list(
        canonical_state.issues
    )
    assert canonical_state.stored_results == 6000
    assert canonical_state.receipt_valid
    assert canonical_state.finalization_marker_valid


@pytest.mark.parametrize(
    "run_id,result_set_id",
    [(NATIVE_RUN, NATIVE_RESULT_SET), (CANONICAL_RUN, CANONICAL_RESULT_SET)],
)
def test_the_result_sets_keep_their_identities(run_id, result_set_id):
    require_run(run_id)
    from fpbench.storage.result_set_store import ResultSetStore

    manifest = ResultSetStore(WORKSPACE).verify_result_set(run_id)
    assert manifest.result_set_id == result_set_id
    assert manifest.total_results == 6000


@pytest.mark.parametrize("run_id", [NATIVE_RUN, CANONICAL_RUN])
def test_the_committed_receipt_still_describes_the_stored_run(run_id):
    """The receipt is evidence that left the workspace; it has to still fit."""
    import json

    from fpbench.storage.result_store import ResultStore

    require_run(run_id)
    stored = ResultStore(WORKSPACE).read_research_receipt(run_id)
    directory = (
        "sourceafis-native-full"
        if run_id == NATIVE_RUN
        else "sourceafis-canonical500-full"
    )
    committed = json.loads(
        (REPO / "evidence" / directory / f"{run_id}.json").read_text("utf-8")
    )
    assert committed["run_fingerprint"] == stored.run_fingerprint
    assert committed["result_set_fingerprint"] == stored.result_set_fingerprint
    assert (
        committed["sourceafis_validation_fingerprint"]
        == stored.sourceafis_validation_fingerprint
    ), "the algorithm validation fingerprint moved"
    assert committed["runtime_bundle_fingerprint"] == stored.runtime_bundle_fingerprint
    assert committed["bridge_jar_sha256"] == stored.bridge_jar_sha256


# ----------------------------------------------------------- the derivations


def test_the_native_decision_set_is_still_decision_ready():
    require_run(NATIVE_RUN)
    from fpbench.experiments.sourceafis_native_decisions import (
        inspect_sourceafis_native_decisions,
    )

    state = inspect_sourceafis_native_decisions(workspace=WORKSPACE)
    assert state.decision_set_id == NATIVE_DECISION_SET
    assert state.status is DecisionDerivationStatus.DECISION_READY


def test_the_canonical_decision_set_is_still_decision_ready():
    require_run(CANONICAL_RUN)
    from fpbench.experiments.sourceafis_canonical500_decisions import (
        inspect_canonical_decisions,
    )

    state = inspect_canonical_decisions(workspace=WORKSPACE)
    assert state.decision_set_id == CANONICAL_DECISION_SET
    assert state.status is DecisionDerivationStatus.DECISION_READY


# ---------------------------------------------------------- the evaluations


def test_the_native_evaluation_is_still_evaluation_ready():
    require_run(NATIVE_RUN)
    from fpbench.experiments.sourceafis_native_evaluation import (
        inspect_sourceafis_native_evaluation,
    )

    state = inspect_sourceafis_native_evaluation(workspace=WORKSPACE)
    assert state.metric_set_id == NATIVE_METRIC_SET
    assert state.status is EvaluationStatus.EVALUATION_READY


def test_the_canonical_evaluation_is_still_evaluation_ready():
    require_run(CANONICAL_RUN)
    from fpbench.experiments.sourceafis_canonical500_evaluation import (
        inspect_canonical_evaluation,
    )

    state = inspect_canonical_evaluation(workspace=WORKSPACE)
    assert state.metric_set_id == CANONICAL_METRIC_SET
    assert state.status is EvaluationStatus.EVALUATION_READY


# ------------------------------------------------------- the paired evidence


def test_the_paired_comparison_is_still_paired_evaluation_ready():
    require_run(NATIVE_RUN)
    require_run(CANONICAL_RUN)
    from fpbench.experiments.sourceafis_native_vs_canonical500 import (
        inspect_paired_experiment,
    )

    state = inspect_paired_experiment(workspace=WORKSPACE)
    assert state.paired_evaluation_id == PAIRED_EVALUATION
    assert state.status is PairedEvaluationStatus.PAIRED_EVALUATION_READY, list(
        state.issues
    )


# ------------------------------------------------------------ nothing new


def test_stage_7a_produced_no_run_of_its_own():
    """Section 87: stage 7A's deliverables are code, tests, ADRs and docs.

    Written originally as "the workspace holds exactly these two runs", which is
    what that claim looked like when stage 7A was the newest thing here. Stage 7C
    then ran NBIS over the same 6,000 comparisons, so the claim is now the one it
    always meant: the two SourceAFIS runs are present and untouched, and every
    other run in the workspace was produced by a later stage that says which run
    is its own. An unexplained run in a workspace that publishes receipts is
    still a failure.
    """
    stored = {
        path.name
        for path in (WORKSPACE / "results").iterdir()
        if path.is_dir() and path.name.startswith("run_")
    }
    assert {NATIVE_RUN, CANONICAL_RUN} <= stored, sorted(stored)

    from fpbench.core.errors import ResearchPreflightError
    from fpbench.experiments.algorithm_research import read_run_pointer

    accounted: set[str] = set()
    experiments = WORKSPACE / "experiments"
    for pointer in experiments.glob("*/current-run.json"):
        try:
            accounted.add(read_run_pointer(WORKSPACE, pointer.parent.name))
        except ResearchPreflightError:
            # A malformed pointer cannot account for a stored run. The inventory
            # assertion below still rejects that run as unexplained.
            continue
    unexplained = stored - {NATIVE_RUN, CANONICAL_RUN} - accounted
    assert unexplained == set(), sorted(unexplained)
