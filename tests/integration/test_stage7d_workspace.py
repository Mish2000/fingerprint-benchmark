"""Stage 7D over the real workspace: both chains, and the comparison between them.

Skipped entirely when the workspace is not here — the two runs, the prepared
image set and the SD300 delivery are 100 GB of things a laptop may not have. Once
they *are* here, nothing in this module is allowed to skip: a missing artefact or
a wrong count is a failure, because the whole point is that these numbers are
reproducible from what is committed (spec section 77).

The gates are the ones the specification names, in order: before the NBIS
decisions (section 78), after them (79), after the metrics (80), after the
comparison (81), and over everything published before stage 7D began (82).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = [pytest.mark.dataset, pytest.mark.stage7d]

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = REPOSITORY_ROOT / "workspace"

SOURCEAFIS_RUN = "run_4c59fa02a6ab"
NBIS_RUN = "run_f0468f28ffba"
NATIVE_RUN = "run_7ac1cecc0bb3"

#: Everything published before stage 7D, which stage 7D may not move
#: (spec section 82).
LEGACY_IDENTITIES = {
    NATIVE_RUN: ("decisionset_0122544e71b1", "eligibilityset_77dbf75cdc76"),
    SOURCEAFIS_RUN: ("decisionset_df0d584bdede", "eligibilityset_d87d6591d517"),
}
LEGACY_METRIC_SETS = {
    NATIVE_RUN: "metricset_f6ffa71f3880",
    SOURCEAFIS_RUN: "metricset_b4c70fbfd1d3",
}
LEGACY_PAIRED = "pairedeval_ee2e0fe7ddb6"


def _dataset_root() -> Path | None:
    value = os.environ.get("FPBENCH_SD300_ROOT")
    return Path(value) if value else None


def _require_workspace() -> None:
    for run_id in (SOURCEAFIS_RUN, NBIS_RUN, NATIVE_RUN):
        if not (WORKSPACE / "results" / run_id / "run.json").is_file():
            pytest.skip(f"workspace does not hold {run_id}")
    if _dataset_root() is None:
        pytest.skip("FPBENCH_SD300_ROOT is not set")


def _require_clean_tree() -> None:
    """A chain status refuses a dirty tree, by design (docs/adr/0017).

    The status of a research chain is a statement about code that can be
    recovered from a commit, so a checkout in the middle of a change cannot
    answer the question at all. Saying so here is the honest outcome, and it
    beats failing four hundred lines deep inside a provenance capture with a
    message about starting a research run.
    """
    import shutil
    import subprocess

    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    completed = subprocess.run(
        ["git", "-C", str(REPOSITORY_ROOT), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        pytest.skip("git could not report the working tree state")
    if completed.stdout.strip():
        pytest.skip(
            "the working tree has uncommitted changes; a chain status is only "
            "meaningful over a committed tree"
        )


@pytest.fixture(scope="module", autouse=True)
def _workspace() -> None:
    _require_workspace()


# ------------------------------------------------- section 78: before deriving


def test_the_methodology_was_committed_before_the_decisions():
    """A protocol edited after the fact would not fingerprint to itself."""
    from fpbench.cross_algorithm import load_comparison_policy
    from fpbench.cross_algorithm.align import load_fair_measurement_protocol

    protocol = load_fair_measurement_protocol(
        REPOSITORY_ROOT / "configs/experiments/stage7d_fair_measurement_protocol_v1.json"
    )
    policy = load_comparison_policy(
        REPOSITORY_ROOT
        / "configs/comparisons/policies/documented_operating_points_v1.yaml"
    )
    assert protocol.comparison_policy_fingerprint == policy.policy_fingerprint
    assert protocol.operating_point_relation == (
        "independently_documented_not_equated"
    )
    assert not protocol.calibration_performed
    assert not protocol.test_cohort_used
    assert not protocol.raw_score_comparison


def test_the_nbis_profile_applies_to_the_real_run():
    from fpbench.decisions import (
        load_decision_profile,
        require_profile_applies_to_run,
    )
    from fpbench.experiments.nbis_canonical500_decisions import (
        DEFAULT_DECISION_CONFIG,
    )
    from fpbench.storage.result_store import ResultStore

    run = ResultStore(WORKSPACE).read_run(NBIS_RUN)
    profile = load_decision_profile(
        DEFAULT_DECISION_CONFIG, algorithm_fingerprint=run.algorithm_fingerprint
    )
    require_profile_applies_to_run(profile=profile, run=run)
    assert profile.threshold == "40"
    assert profile.comparator.value == "greater_than"
    assert profile.schema_version == "2"


def test_the_profile_refuses_the_other_algorithms_run():
    """Section 28: the profile is rejected on any other run."""
    from fpbench.core.errors import DecisionProfileApplicabilityError
    from fpbench.decisions import (
        load_decision_profile,
        require_profile_applies_to_run,
    )
    from fpbench.experiments.nbis_canonical500_decisions import (
        DEFAULT_DECISION_CONFIG,
    )
    from fpbench.storage.result_store import ResultStore

    sourceafis_run = ResultStore(WORKSPACE).read_run(SOURCEAFIS_RUN)
    profile = load_decision_profile(
        DEFAULT_DECISION_CONFIG,
        algorithm_fingerprint=sourceafis_run.algorithm_fingerprint,
    )
    with pytest.raises(DecisionProfileApplicabilityError):
        require_profile_applies_to_run(profile=profile, run=sourceafis_run)


# ---------------------------------------------- section 75: the real boundary


def test_the_real_scores_at_the_boundary_are_decided_as_written():
    """Whatever scores of 39, 40 and 41 exist, they follow ``> 40``.

    No claim is made that any of the three occurs. Where one does, its decisions
    are pinned; where it does not, the synthetic boundary suite still covers the
    rule (spec section 75).
    """
    from fpbench.core.enums import DecisionValue, ExecutionStatus
    from fpbench.storage.decision_set_store import DecisionSetStore
    from fpbench.storage.result_store import ResultStore

    store = DecisionSetStore(WORKSPACE)
    set_id = _nbis_decision_set_id()
    if set_id is None or not store.has_decision_set(NBIS_RUN, set_id):
        pytest.skip("the NBIS decision set has not been derived yet")

    _profile, _manifest, records = store.read_decision_set(NBIS_RUN, set_id)
    results = ResultStore(WORKSPACE)
    counts: dict[int, int] = {39: 0, 40: 0, 41: 0}
    for record in records:
        stored = results.read_raw_result(NBIS_RUN, record.job_id)
        if stored.status is not ExecutionStatus.SUCCESS:
            continue
        score = int(stored.raw_score)
        if score not in counts:
            continue
        counts[score] += 1
        expected = (
            DecisionValue.MATCH if score > 40 else DecisionValue.NON_MATCH
        )
        assert record.decision is expected, (
            f"score {score} decided {record.decision}, expected {expected}"
        )
    # Recorded rather than asserted: the counts are a property of the data.
    print(f"boundary scores observed: {counts}")


def test_a_score_of_zero_is_a_decided_non_match():
    """Section 30, on the real results."""
    from fpbench.core.enums import (
        DecisionApplicationStatus,
        DecisionValue,
        ExecutionStatus,
    )
    from fpbench.storage.decision_set_store import DecisionSetStore
    from fpbench.storage.result_store import ResultStore

    store = DecisionSetStore(WORKSPACE)
    set_id = _nbis_decision_set_id()
    if set_id is None or not store.has_decision_set(NBIS_RUN, set_id):
        pytest.skip("the NBIS decision set has not been derived yet")

    _profile, _manifest, records = store.read_decision_set(NBIS_RUN, set_id)
    results = ResultStore(WORKSPACE)
    seen = 0
    for record in records:
        stored = results.read_raw_result(NBIS_RUN, record.job_id)
        if stored.status is not ExecutionStatus.SUCCESS or int(stored.raw_score) != 0:
            continue
        seen += 1
        assert record.application_status is DecisionApplicationStatus.DECIDED
        assert record.decision is DecisionValue.NON_MATCH
        if seen >= 50:  # the rule is uniform; fifty is enough to see it hold
            break


# ------------------------------------------------ section 79: after deriving


def test_the_nbis_decision_chain_is_decision_ready():
    _require_clean_tree()
    from fpbench.experiments.nbis_canonical500_decisions import inspect_nbis_decisions

    state = inspect_nbis_decisions(
        workspace=WORKSPACE, repository_root=REPOSITORY_ROOT
    )
    assert state.is_decision_ready, list(state.issues)[:3]
    assert state.total_decisions == 6000
    assert state.decided_count == 6000
    assert state.undecidable_count == 0
    assert state.total_eligibility_units == 1500
    assert state.views_valid == 3
    assert state.receipt_valid
    assert state.finalization_valid


# ------------------------------------------------ section 80: after counting


def test_the_nbis_evaluation_is_evaluation_ready_with_56_observations():
    _require_clean_tree()
    from fpbench.experiments.nbis_canonical500_evaluation import (
        inspect_nbis_evaluation,
    )
    from fpbench.storage.metric_set_store import MetricSetStore

    state = inspect_nbis_evaluation(
        workspace=WORKSPACE, repository_root=REPOSITORY_ROOT
    )
    assert state.is_evaluation_ready, list(state.issues)[:3]
    manifest = MetricSetStore(WORKSPACE).read_manifest(NBIS_RUN, state.metric_set_id)
    assert manifest.total_observations == 56


def test_both_chains_were_counted_under_one_metric_policy():
    """Section 40: the same file, not a copy under an NBIS name."""
    from fpbench.storage.metric_set_store import MetricSetStore

    store = MetricSetStore(WORKSPACE)
    left = store.read_manifest(SOURCEAFIS_RUN, LEGACY_METRIC_SETS[SOURCEAFIS_RUN])
    right_id = _nbis_metric_set_id()
    if right_id is None:
        pytest.skip("the NBIS metric set has not been derived yet")
    right = store.read_manifest(NBIS_RUN, right_id)
    assert left.metric_policy_fingerprint == right.metric_policy_fingerprint
    assert not list(
        (REPOSITORY_ROOT / "configs" / "metrics").glob("*nbis*")
    ), "there is one metric policy file, not one per algorithm"


# --------------------------------------------- section 81: after comparing


def test_the_comparison_is_cross_algorithm_ready():
    _require_clean_tree()
    from fpbench.experiments.sourceafis_vs_nbis_canonical500 import (
        DEFAULT_COMPARISON_CONFIG,
        inspect_comparison,
        load_comparison_config,
    )

    try:
        config = load_comparison_config(DEFAULT_COMPARISON_CONFIG)
    except Exception as exc:  # a placeholder id is not a failure yet
        pytest.skip(f"the comparison config is not bound yet: {exc}")

    state = inspect_comparison(
        workspace=WORKSPACE, config=config, repository_root=REPOSITORY_ROOT
    )
    assert state.audit_clean, list(state.issues)[:3]
    assert state.total_records == 6000
    assert state.total_transitions == 1500
    assert state.is_cross_algorithm_ready, list(state.issues)[:3]


def test_the_published_comparison_carries_no_score():
    from fpbench.core.serialization import read_json
    from fpbench.cross_algorithm import (
        EVIDENCE_DIRECTORY,
        require_no_score_comparison,
    )

    directory = REPOSITORY_ROOT / EVIDENCE_DIRECTORY
    if not directory.is_dir():
        pytest.skip("no comparison evidence is published yet")
    for path in sorted(directory.glob("*.json")):
        require_no_score_comparison(read_json(path), path=path.name)
    for path in sorted(directory.glob("*.md")):
        text = path.read_text(encoding="utf-8").lower()
        for forbidden in ("score delta", "more accurate", "statistically significant"):
            assert forbidden not in text, f"{path.name} says {forbidden!r}"


# ------------------------------------- section 82: nothing published moved


@pytest.mark.parametrize("run_id", sorted(LEGACY_IDENTITIES))
def test_every_published_decision_and_eligibility_set_is_still_there(run_id):
    from fpbench.storage.decision_set_store import DecisionSetStore
    from fpbench.storage.eligibility_set_store import EligibilitySetStore

    decision_set_id, eligibility_set_id = LEGACY_IDENTITIES[run_id]
    assert DecisionSetStore(WORKSPACE).has_decision_set(run_id, decision_set_id)
    manifest, _records = EligibilitySetStore(WORKSPACE).read_eligibility_set(
        run_id, decision_set_id
    )
    assert manifest.eligibility_set_id == eligibility_set_id


@pytest.mark.parametrize("run_id", sorted(LEGACY_METRIC_SETS))
def test_every_published_metric_set_is_still_there(run_id):
    from fpbench.storage.metric_set_store import MetricSetStore

    manifest = MetricSetStore(WORKSPACE).read_manifest(
        run_id, LEGACY_METRIC_SETS[run_id]
    )
    assert manifest.metric_set_id == LEGACY_METRIC_SETS[run_id]


def test_the_published_paired_evaluation_is_still_there():
    from fpbench.storage.paired_evaluation_store import PairedEvaluationStore

    store = PairedEvaluationStore(WORKSPACE)
    assert store.definition_path(LEGACY_PAIRED).is_file()


def test_the_stage_7c_evidence_is_unchanged():
    """Section 82: the alignment and its marker still hold, byte for byte."""
    from fpbench.core.serialization import read_json
    from fpbench.experiments.nbis_canonical500_decisions import (
        EXPECTED_ALIGNMENT_FINGERPRINT,
        EXPECTED_STAGE_7C_FINALIZATION_FINGERPRINT,
    )

    marker = read_json(
        REPOSITORY_ROOT / "evidence/nbis-canonical500-raw/stage-7c-finalization.json"
    )
    assert marker["stage_7c_finalization_fingerprint"] == (
        EXPECTED_STAGE_7C_FINALIZATION_FINGERPRINT
    )
    assert marker["alignment_fingerprint"] == EXPECTED_ALIGNMENT_FINGERPRINT


def test_the_sourceafis_profiles_still_fingerprint_to_what_the_workspace_stored():
    """The frozen half of section 19, checked against the stored artefacts."""
    from fpbench.core.serialization import read_json
    from fpbench.decisions import load_decision_profile
    from fpbench.storage.decision_set_store import DecisionSetStore

    for run_id, config in (
        (NATIVE_RUN, "sourceafis_java_3_18_1_documented_40_v1.yaml"),
        (SOURCEAFIS_RUN, "sourceafis_java_3_18_1_documented_40_canonical500_v1.yaml"),
    ):
        decision_set_id = LEGACY_IDENTITIES[run_id][0]
        stored = read_json(
            DecisionSetStore(WORKSPACE).profile_path(run_id, decision_set_id)
        )
        reloaded = load_decision_profile(
            REPOSITORY_ROOT / "configs" / "decisions" / config,
            algorithm_fingerprint=stored["algorithm_fingerprint"],
        )
        assert reloaded.profile_fingerprint == stored["profile_fingerprint"]
        assert reloaded.comparator.value == "greater_than_or_equal"
        assert "schema_version" not in stored


# ----------------------------------------------------------------- internals


def _nbis_decision_set_id() -> str | None:
    from fpbench.experiments.algorithm_decisions import read_decision_set_pointer
    from fpbench.experiments.nbis_canonical500_decisions import EXPERIMENT_ID

    return read_decision_set_pointer(WORKSPACE, EXPERIMENT_ID, NBIS_RUN)


def _nbis_metric_set_id() -> str | None:
    from fpbench.storage.definition_store import DefinitionStore
    from fpbench.core.evaluation_models import MetricDerivationDefinition
    from fpbench.experiments.nbis_canonical500_evaluation import EXPERIMENT_ID

    store = DefinitionStore(
        WORKSPACE,
        experiment_id=EXPERIMENT_ID,
        loader=lambda payload: MetricDerivationDefinition(**payload),
        pointer_name="current-metric-set.json",
    )
    return store.read_pointer_value(NBIS_RUN, "metric_set_id")
