"""The real workspace, before and after the run that stage 7C is.

Two jobs, in one file because they are two readings of the same chain.

**Before.** Everything the run depends on is in place and is what the
configuration says it is: the canonical SourceAFIS run is ``RESEARCH_READY``, its
result set is ``resultset_087b084fb8a8``, the prepared set is
``PREPARATION_READY``, 6,000 pairs and 3,000 prepared entries line up, and the
one certified build the experiment pins is present and verifies. Running this
before starting is the difference between finding out in ten seconds and finding
out three hours in (spec section 44).

**After.** Once an NBIS run exists, the same file requires it to be finished and
aligned, and requires *nothing downstream of it to exist*: no decisions, no
eligibility, no metrics, no paired evaluation. Stage 7C publishes raw scores, and
a decision set over this run would mean somebody had chosen a threshold for
BOZORTH3 (spec section 45, docs/adr/0052).

Skip policy, matching stage 7A's: no workspace at all is a skip. A workspace
whose chain is broken is a failure, because that is the entire point of running
this (spec section 44).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from fpbench.core.enums import ResearchRunStatus

pytestmark = [pytest.mark.dataset, pytest.mark.nbis_full_run]

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = REPOSITORY_ROOT / "workspace"


@pytest.fixture(scope="module", autouse=True)
def require_results_workspace():
    """Skip only when this module's tests are selected, not during collection."""
    if not (WORKSPACE / "results").is_dir():
        pytest.skip("no persisted results workspace is available")

REFERENCE_RUN = "run_4c59fa02a6ab"
REFERENCE_PLAN = "plan_b4ae66e91923"
REFERENCE_RESULT_SET = "resultset_087b084fb8a8"
PREPARATION_SET = "prepset_be560e047991"


@pytest.fixture(scope="module")
def config():
    from fpbench.experiments.nbis_canonical500_full import (
        load_nbis_canonical500_config,
    )

    return load_nbis_canonical500_config(repository_root=REPOSITORY_ROOT)


@pytest.fixture(scope="module")
def dataset_root():
    root = os.environ.get("FPBENCH_SD300_ROOT")
    if not root:
        pytest.skip("FPBENCH_SD300_ROOT is not set")
    return Path(root)


def nbis_run_id() -> str | None:
    """Which NBIS run this workspace has prepared, if any."""
    from fpbench.core.errors import ResearchPreflightError
    from fpbench.experiments.algorithm_research import read_run_pointer
    from fpbench.experiments.nbis_canonical500_full import EXPERIMENT_ID

    try:
        return read_run_pointer(WORKSPACE, EXPERIMENT_ID)
    except ResearchPreflightError:
        return None


# ------------------------------------------------------------------- before


def test_the_reference_run_is_present(config):
    assert (WORKSPACE / "results" / REFERENCE_RUN).is_dir(), (
        "the canonical SourceAFIS run is the input to this stage"
    )
    assert config.reference.run_id == REFERENCE_RUN
    assert config.reference.plan_id == REFERENCE_PLAN
    assert config.reference.result_set_id == REFERENCE_RESULT_SET


def test_the_reference_run_is_research_ready(dataset_root):
    from fpbench.experiments.sourceafis_canonical500_full import (
        inspect_sourceafis_canonical500_run,
    )

    state = inspect_sourceafis_canonical500_run(
        workspace=WORKSPACE, dataset_root=dataset_root, repository_root=REPOSITORY_ROOT
    )
    assert state.run_id == REFERENCE_RUN
    assert state.status is ResearchRunStatus.RESEARCH_READY, list(state.issues)
    assert state.stored_results == 6000
    assert state.missing_results == 0


def test_the_reference_result_set_verifies(config):
    from fpbench.storage.result_set_store import ResultSetStore

    manifest = ResultSetStore(WORKSPACE).verify_result_set(REFERENCE_RUN)
    assert manifest.result_set_id == REFERENCE_RESULT_SET
    assert manifest.total_results == 6000


def test_the_prepared_set_is_preparation_ready(config):
    from fpbench.imaging.verify import verify_prepared_artifacts
    from fpbench.storage.prepared_image_set_store import PreparedImageSetStore

    store = PreparedImageSetStore(WORKSPACE)
    manifest = store.read_manifest(PREPARATION_SET)
    assert manifest.preparation_set_id == config.preparation_set_id
    assert manifest.preparation_set_fingerprint == config.preparation_set_fingerprint
    verification = verify_prepared_artifacts(
        store=store,
        preparation_set_id_value=PREPARATION_SET,
        require_receipt=True,
        require_finalization=True,
    )
    assert verification.is_valid, list(verification.issues[:3])


def test_the_execution_controls_of_the_reference_run_are_reproducible(config):
    """The committed YAML against the recorded run, not against another file."""
    from fpbench.experiments.canonical_run_alignment import (
        require_execution_controls_equal,
    )
    from fpbench.experiments.nbis_canonical500_full import (
        build_nbis_canonical500_spec,
    )
    from fpbench.storage.result_store import ResultStore
    from fpbench.storage.runtime_bundle_store import RuntimeBundleStore

    result_store = ResultStore(WORKSPACE)
    reference = result_store.read_run(REFERENCE_RUN)
    bundle = RuntimeBundleStore(WORKSPACE).read_bundle(
        result_store.read_runtime_reference(REFERENCE_RUN).bundle_id
    )
    require_execution_controls_equal(
        reference,
        build_nbis_canonical500_spec(config),
        reference_materialization_policy=bundle.materialization_policy,
    )


def test_the_alignment_is_derivable_and_clean(config, dataset_root):
    """6,000 pairs and 3,000 prepared entries, matched row by row."""
    from fpbench.experiments.nbis_canonical500_full import (
        verify_nbis_canonical500_alignment,
    )

    report = verify_nbis_canonical500_alignment(
        workspace=WORKSPACE,
        dataset_root=dataset_root,
        config=config,
        repository_root=REPOSITORY_ROOT,
        run_id=nbis_run_id(),
        require_clean=False,
    )
    assert report.reference_pair_count == 6000
    assert report.candidate_pair_count == 6000
    assert report.equal_pair_ids == 6000
    assert report.equal_pair_semantics == 6000
    assert report.reference_prepared_entries == 3000
    assert report.candidate_prepared_entries == 3000
    assert report.equal_prepared_entries == 3000
    assert report.is_clean, [issue.message for issue in report.issues]


def test_the_pinned_runtime_is_present_and_certified(config):
    """Before a run the external build is mandatory; afterwards its bundle is."""
    from fpbench.adapters.nbis.build_manifest import read_build_manifest
    from fpbench.experiments.nbis_canonical500_full import require_pinned_build
    from fpbench.storage.result_store import ResultStore
    from fpbench.storage.runtime_bundle_store import RuntimeBundleStore

    run_id = nbis_run_id()
    if run_id is None:
        directory = REPOSITORY_ROOT / config.build_root / config.nbis_build_id
        if not directory.is_dir():
            pytest.fail(
                f"preflight requires pinned NBIS build {config.nbis_build_id}; "
                "a missing build is a failure before any run is prepared"
            )
        resolved = require_pinned_build(
            directory, config=config, repository_root=REPOSITORY_ROOT
        )
        assert resolved.name == config.nbis_build_id
        return

    result_store = ResultStore(WORKSPACE)
    run = result_store.read_run(run_id)
    reference = result_store.read_runtime_reference(run_id)
    bundle_store = RuntimeBundleStore(WORKSPACE)
    verification = bundle_store.require_valid(reference.bundle_id)
    bundle = bundle_store.read_bundle(reference.bundle_id)
    assert verification.bundle_fingerprint == reference.bundle_fingerprint
    assert bundle.bundle_fingerprint == reference.bundle_fingerprint
    assert {asset.role for asset in bundle.assets} == {
        "nbis_mindtct_executable",
        "nbis_bozorth3_executable",
        "nbis_build_manifest",
    }
    manifest = read_build_manifest(
        bundle_store.asset_path(reference.bundle_id, "nbis_build_manifest")
    )
    assert manifest.manifest_fingerprint == run.environment.dependencies[
        "nbis.build_manifest_fingerprint"
    ]


# -------------------------------------------------------------------- after


def prepared_run_or_skip() -> str:
    run_id = nbis_run_id()
    if run_id is None:
        pytest.skip("no NBIS canonical run has been prepared in this workspace yet")
    return run_id


def test_the_nbis_run_is_ready(config, dataset_root):
    from fpbench.experiments.nbis_canonical500_full import (
        inspect_nbis_canonical500_experiment,
    )

    run_id = prepared_run_or_skip()
    state = inspect_nbis_canonical500_experiment(
        workspace=WORKSPACE,
        dataset_root=dataset_root,
        config=config,
        repository_root=REPOSITORY_ROOT,
        run_id=run_id,
    )
    assert state.research_state.status is ResearchRunStatus.RESEARCH_READY, list(
        state.research_state.issues
    )
    assert state.research_state.stored_results == 6000
    assert state.research_state.missing_results == 0
    assert state.alignment_report.is_clean, [
        issue.message for issue in state.alignment_report.issues
    ]
    assert state.issues == (), [issue.message for issue in state.issues]
    assert state.is_ready


def test_the_nbis_result_set_holds_exactly_six_thousand_rows():
    from fpbench.storage.result_set_store import ResultSetStore

    run_id = prepared_run_or_skip()
    manifest = ResultSetStore(WORKSPACE).verify_result_set(run_id)
    assert manifest.total_results == 6000


def test_stage_7c_produced_no_decision_no_metric_and_no_paired_evaluation():
    """Spec section 45: raw results, and nothing downstream of them.

    This originally asserted that ``decisions/``, ``metrics/`` and
    ``eligibility/`` did not exist under the run, and that no derivation was
    filed against it. Both were true when Stage 7C closed and both stopped being
    true the next day, when Stage 7D derived NBIS decisions and metrics from this
    exact run — which is Stage 7D's published deliverable, not a violation of
    Stage 7C's.

    A directory's current contents were the wrong proxy for the claim. The claim
    is about what *Stage 7C* produced, and the place that records it is Stage
    7C's own finalization: a raw-run marker, which carries a result set and no
    derivation identity of any kind. That is checked here instead, and it stays
    true however many later stages derive from the run.

    What this deliberately does **not** do is police what else is under the run.
    No test in this repository forbids an unaccounted-for derivation set, and
    adding that rule here would be inventing a policy under the name of fixing a
    test.
    """
    import json

    run_id = prepared_run_or_skip()
    finalization = (
        WORKSPACE / "results" / run_id / "research-finalization.json"
    )
    assert finalization.is_file(), finalization
    marker = json.loads(finalization.read_text(encoding="utf-8"))

    derivation_terms = ("decision", "metric", "eligib", "paired", "derivation")
    carried = sorted(
        key
        for key in marker
        if any(term in key.lower() for term in derivation_terms)
    )
    assert carried == [], (
        f"the Stage 7C finalization carries derivation identities {carried}; "
        "it is a raw-run marker and names a result set and nothing downstream"
    )
    assert "result_set_fingerprint" in marker, sorted(marker)


def test_the_two_finished_result_sets_are_unmoved():
    """Spec section 46: stage 7C writes nothing into an earlier stage's directory.

    The rest of the chain — both decision sets, both metric sets and the paired
    comparison — is re-verified in
    ``tests/regression/test_sourceafis_unmoved_after_nbis.py``, which is where
    that list already lives.
    """
    from fpbench.storage.result_set_store import ResultSetStore

    for run_id, result_set_id in (
        ("run_7ac1cecc0bb3", "resultset_2bf3cacfd806"),
        ("run_4c59fa02a6ab", "resultset_087b084fb8a8"),
    ):
        manifest = ResultSetStore(WORKSPACE).verify_result_set(run_id)
        assert manifest.result_set_id == result_set_id
        assert manifest.total_results == 6000
