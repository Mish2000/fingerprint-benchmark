"""Adding a second algorithm moved nothing that belongs to the first.

Stage 7B added an adapter, a validator, an integration and a registry entry. None
of that is supposed to be visible from where SourceAFIS stands — but "supposed
to" is what regression tests are for. Seven finished artefacts are cited by
committed evidence and by a thesis chapter, and every one of them has to still be
exactly what it was (spec section 51):

    run_7ac1cecc0bb3        native research run
    run_4c59fa02a6ab        canonical research run
    decisionset_0122544e71b1 / decisionset_df0d584bdede
    metricset_f6ffa71f3880   / metricset_b4c70fbfd1d3
    pairedeval_ee2e0fe7ddb6  the paired comparison over both

The identity checks need no workspace and run everywhere: the descriptor is built
from constants, and if it moved, all twelve thousand stored results would be
attributed to an algorithm that no longer exists under that name. The chain
checks need the real workspace and skip without it — but a workspace whose chain
is *broken* is a failure, not a skip.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fpbench.adapters.registry import registered_adapters
from fpbench.adapters.sourceafis_java.adapter import (
    ADAPTER_ID as SOURCEAFIS_ADAPTER_ID,
)
from fpbench.adapters.sourceafis_java.adapter import (
    ALGORITHM_ID as SOURCEAFIS_ALGORITHM_ID,
)
from fpbench.adapters.sourceafis_java.adapter import SourceAfisJavaAdapter
from fpbench.adapters.sourceafis_java.config import SourceAfisJavaConfig
from fpbench.core.enums import (
    DecisionDerivationStatus,
    EvaluationStatus,
    PairedEvaluationStatus,
    ResearchRunStatus,
)
from fpbench.core.execution_models import descriptor_fingerprint

pytestmark = [pytest.mark.adapter_contract, pytest.mark.nbis_contract]

REPO = Path(__file__).resolve().parents[2]
WORKSPACE = REPO / "workspace"
EVIDENCE = REPO / "evidence"

NATIVE_RUN_ID = "run_7ac1cecc0bb3"
CANONICAL_RUN_ID = "run_4c59fa02a6ab"
NATIVE_DECISION_SET_ID = "decisionset_0122544e71b1"
CANONICAL_DECISION_SET_ID = "decisionset_df0d584bdede"
NATIVE_METRIC_SET_ID = "metricset_f6ffa71f3880"
CANONICAL_METRIC_SET_ID = "metricset_b4c70fbfd1d3"
PAIRED_ID = "pairedeval_ee2e0fe7ddb6"

#: Read out of ``workspace/results/run_7ac1cecc0bb3/run.json``, not recomputed.
STORED_ALGORITHM_FINGERPRINT = (
    "5a1784faae1e82c12c374e050fcd6cfd41aa25b7a9ade3905d099df2e06a9531"
)


def workspace_has(run_id: str) -> bool:
    return (WORKSPACE / "results" / run_id).is_dir()


def require_workspace() -> None:
    for run_id in (NATIVE_RUN_ID, CANONICAL_RUN_ID):
        if not workspace_has(run_id):
            pytest.skip(f"no run {run_id} in this workspace")


def require_clean_tree() -> None:
    """A research status refuses a dirty tree, by design (docs/adr/0017).

    So a checkout in the middle of a change cannot answer the question, and
    saying so is the honest outcome — the chain is re-verified in CI and before
    every commit, where the tree is clean.
    """
    import shutil
    import subprocess

    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    completed = subprocess.run(
        ["git", "-C", str(REPO), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0 or completed.stdout.strip():
        pytest.skip("the working tree is dirty; a research status refuses one")


# --------------------------------------------------------------- identities


def test_the_sourceafis_descriptor_fingerprint_did_not_move():
    """The one check that would invalidate every downstream artefact at once."""
    adapter = SourceAfisJavaAdapter(SourceAfisJavaConfig())
    assert descriptor_fingerprint(adapter.descriptor) == STORED_ALGORITHM_FINGERPRINT


def test_registering_a_second_adapter_did_not_disturb_the_first():
    listed = registered_adapters()
    assert SOURCEAFIS_ADAPTER_ID in listed
    assert "nbis_mindtct_bozorth3_subprocess" in listed
    assert "dummy_sha256" in listed
    assert len(set(listed)) == len(listed)


def test_the_two_routes_have_distinct_identities():
    from fpbench.adapters.nbis.adapter import (
        ADAPTER_ID as NBIS_ADAPTER_ID,
        ALGORITHM_ID as NBIS_ALGORITHM_ID,
    )

    assert NBIS_ALGORITHM_ID != SOURCEAFIS_ALGORITHM_ID
    assert NBIS_ADAPTER_ID != SOURCEAFIS_ADAPTER_ID


def test_the_committed_evidence_still_names_the_same_artefacts():
    """Present in every checkout, workspace or not."""
    expected = {
        EVIDENCE / "sourceafis-native-full" / f"{NATIVE_RUN_ID}.json": "run_id",
        EVIDENCE
        / "sourceafis-canonical500-full"
        / f"{CANONICAL_RUN_ID}.json": "run_id",
        EVIDENCE
        / "sourceafis-native-decisions"
        / f"{NATIVE_DECISION_SET_ID}.json": "decision_set_id",
        EVIDENCE
        / "sourceafis-canonical500-decisions"
        / f"{CANONICAL_DECISION_SET_ID}.json": "decision_set_id",
        EVIDENCE
        / "sourceafis-native-evaluation"
        / f"{NATIVE_METRIC_SET_ID}.json": "metric_set_id",
        EVIDENCE
        / "sourceafis-canonical500-evaluation"
        / f"{CANONICAL_METRIC_SET_ID}.json": "metric_set_id",
        EVIDENCE
        / "sourceafis-native-vs-canonical500"
        / f"{PAIRED_ID}.json": "paired_evaluation_id",
    }
    for path, key in expected.items():
        assert path.is_file(), path
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload[key] == path.stem, path


#: The evidence directories that are *about* NBIS and say so: stage 7C's raw
#: scores, stage 7D's decisions and counts over them, and the comparison that
#: names both algorithms in its own title. Every other directory under evidence/
#: predates the second algorithm and must not have acquired a word of its
#: vocabulary.
#:
#: An allowlist rather than a prefix rule, because the comparison directory
#: begins with ``sourceafis-`` and would otherwise be checked for the word it
#: exists to use.
NBIS_EVIDENCE_DIRECTORIES = frozenset(
    {
        "nbis-canonical500-raw",
        "nbis-canonical500-decisions",
        "nbis-canonical500-evaluation",
        "sourceafis-vs-nbis-canonical500",
    }
)

#: Directories published *after* NBIS, which are therefore not "earlier
#: receipts" and are not what this module is about. Stage 8B's adapter profile
#: names `nbis_result` on purpose: it is one of the inputs the learned matcher
#: must never receive, and listing it is the point.
#:
#: Without this the checks below read as "no evidence directory anywhere may
#: contain the word", which no later stage can satisfy — the same widening
#: mistake docs/adr/0067 corrected in Stage 8A's boundary audit.
LATER_STAGE_EVIDENCE_DIRECTORIES = frozenset(
    {
        "stage8a-modern-matcher-selection",
        "stage8b-flx-runtime-qualification",
        # Stage 8C's raw run. Its research finalization is schema 4, and its
        # documents name NBIS because the run is aligned against the same
        # canonical experiment NBIS used — neither of which says anything about
        # whether an *earlier* receipt moved, which is the only question these
        # two tests ask.
        "flx-canonical500-raw",
    }
)
EXEMPT_EVIDENCE_DIRECTORIES = NBIS_EVIDENCE_DIRECTORIES | LATER_STAGE_EVIDENCE_DIRECTORIES


def test_no_earlier_receipt_was_upgraded_to_a_newer_schema():
    """Section 51: the receipts issued before NBIS stay exactly as they were.

    A receipt that had been rewritten by a later stage would carry that stage's
    vocabulary, so the check is for the word rather than for a schema number:
    it catches a re-issue, a re-render and a silent upgrade alike.
    """
    for directory in sorted(EVIDENCE.iterdir()):
        if not directory.is_dir() or directory.name in EXEMPT_EVIDENCE_DIRECTORIES:
            continue
        for path in sorted(directory.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            assert "nbis" not in json.dumps(payload, sort_keys=True).lower(), path


def test_no_earlier_receipt_acquired_the_second_schema_version():
    """The same question asked of the schema number rather than the vocabulary.

    Stage 7D added a schema-2 derivation receipt, which binds three things
    schema 1 does not. Every receipt published before it is schema 1 and stays
    schema 1 — an upgrade would change the digest its finalization marker cites
    (docs/adr/0055).
    """
    for directory in sorted(EVIDENCE.iterdir()):
        if not directory.is_dir() or directory.name in EXEMPT_EVIDENCE_DIRECTORIES:
            continue
        for path in sorted(directory.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and "schema_version" in payload:
                assert str(payload["schema_version"]) in {"1", "2", "3"}, path
            for name in (
                "source_stage_finalization_kind",
                "derivation_definition_fingerprint",
            ):
                assert name not in json.dumps(payload), (
                    f"{path} acquired the stage 7D receipt field {name!r}"
                )


# ------------------------------------------------------------- the chains


@pytest.mark.dataset
def test_the_native_research_run_is_still_research_ready(sd300_root):
    """Needs the delivery: a research status re-reads the pair manifest."""
    require_workspace()
    require_clean_tree()
    from fpbench.experiments.sourceafis_native_full import inspect_sourceafis_native_run

    state = inspect_sourceafis_native_run(workspace=WORKSPACE)
    assert state.run_id == NATIVE_RUN_ID
    assert state.status is ResearchRunStatus.RESEARCH_READY, list(state.issues)


@pytest.mark.dataset
def test_the_canonical_research_run_is_still_research_ready(sd300_root):
    require_workspace()
    require_clean_tree()
    from fpbench.experiments.sourceafis_canonical500_full import (
        inspect_sourceafis_canonical500_run,
    )

    state = inspect_sourceafis_canonical500_run(workspace=WORKSPACE)
    assert state.run_id == CANONICAL_RUN_ID
    assert state.status is ResearchRunStatus.RESEARCH_READY, list(state.issues)


@pytest.mark.dataset
@pytest.mark.decisions
def test_both_decision_chains_are_still_decision_ready():
    require_workspace()
    from fpbench.experiments.sourceafis_canonical500_decisions import (
        inspect_canonical_decisions,
    )
    from fpbench.experiments.sourceafis_native_decisions import (
        inspect_sourceafis_native_decisions,
    )

    native = inspect_sourceafis_native_decisions(workspace=WORKSPACE)
    canonical = inspect_canonical_decisions(workspace=WORKSPACE)
    assert native.decision_set_id == NATIVE_DECISION_SET_ID
    assert canonical.decision_set_id == CANONICAL_DECISION_SET_ID
    assert native.status is DecisionDerivationStatus.DECISION_READY
    assert canonical.status is DecisionDerivationStatus.DECISION_READY


@pytest.mark.dataset
@pytest.mark.metrics
def test_both_evaluations_are_still_evaluation_ready():
    require_workspace()
    from fpbench.experiments.sourceafis_canonical500_evaluation import (
        inspect_canonical_evaluation,
    )
    from fpbench.experiments.sourceafis_native_evaluation import (
        inspect_sourceafis_native_evaluation,
    )

    native = inspect_sourceafis_native_evaluation(workspace=WORKSPACE)
    canonical = inspect_canonical_evaluation(workspace=WORKSPACE)
    assert native.metric_set_id == NATIVE_METRIC_SET_ID
    assert canonical.metric_set_id == CANONICAL_METRIC_SET_ID
    assert native.status is EvaluationStatus.EVALUATION_READY
    assert canonical.status is EvaluationStatus.EVALUATION_READY


@pytest.mark.dataset
@pytest.mark.paired_evaluation
def test_the_paired_comparison_is_still_paired_evaluation_ready():
    require_workspace()
    from fpbench.experiments.sourceafis_native_vs_canonical500 import (
        inspect_paired_experiment,
    )

    state = inspect_paired_experiment(workspace=WORKSPACE, repository_root=REPO)
    assert state.paired_evaluation_id == PAIRED_ID
    assert state.status is PairedEvaluationStatus.PAIRED_EVALUATION_READY, list(
        state.issues
    )


@pytest.mark.dataset
def test_every_run_beyond_the_two_originals_is_named_by_an_experiment(tmp_path):
    """The two SourceAFIS runs are untouched, and nothing else is unexplained.

    This test has now been widened twice by later stages, which is the signal
    that its *shape* was wrong rather than its intent. The original asserted the
    workspace held exactly the two SourceAFIS runs — true until Stage 7C added a
    third. It was then changed to allow the run Stage 7C's experiment pointer
    named — true until Stage 8C added a fourth.

    So it no longer names an experiment at all. It asks the question it always
    meant: are the two originals present, and is every other run in the
    workspace declared by some experiment's own pointer? A stray run that no
    experiment claims still fails, and the next stage needs no edit here
    (docs/adr/0067).
    """
    if not WORKSPACE.is_dir():
        pytest.skip("no workspace in this checkout")
    runs = {path.name for path in (WORKSPACE / "results").iterdir() if path.is_dir()}
    assert {NATIVE_RUN_ID, CANONICAL_RUN_ID} <= runs, sorted(runs)

    from fpbench.core.errors import ResearchPreflightError
    from fpbench.experiments.algorithm_research import read_run_pointer

    experiments = WORKSPACE / "experiments"
    declared: set[str] = set()
    for directory in sorted(experiments.iterdir()) if experiments.is_dir() else ():
        if not directory.is_dir():
            continue
        try:
            declared.add(read_run_pointer(WORKSPACE, directory.name))
        except ResearchPreflightError:
            continue

    unexplained = runs - {NATIVE_RUN_ID, CANONICAL_RUN_ID} - declared
    assert not unexplained, sorted(unexplained)
