"""24 real SD300 comparisons through SourceAFIS, over canonical 500 ppi inputs.

The canonical sibling of the stage 4A pilot, and it asks the same question: can
SourceAFIS 3.18.1 actually process what this pipeline hands it — every release,
every protocol stage — without crashing, timing out or rejecting a resolution?

The difference from the native pilot is the input. Every image here comes from
the immutable prepared-image set, at 500 ppi, whatever release it belongs to, and
every stored result carries the set's fingerprint and both entry hashes.

Two fingers of one subject, four stages, three releases. The jobs are taken from
the real execution plan rather than assembled here, so what runs is exactly what
the protocol asked for.

**No biometric conclusion may be drawn from these 24 scores.** They are a handful
of comparisons from one subject, with no threshold applied and none available.
The run is left deliberately partial and no completion manifest is written,
because a run covering 24 of 6,000 comparisons must not be able to look finished
(docs/adr/0012, docs/adr/0013).
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from fpbench.core.enums import (
    ExecutionStatus,
    FailureCode,
    FingerprintPosition,
    ProtocolStage,
)
from fpbench.execution.planner import build_execution_plan
from fpbench.execution.run_definition import create_run_definition
from fpbench.execution.runner import SingleJobRunner
from fpbench.imaging.canonical500 import Canonical500ImagePreparer
from fpbench.storage.prepared_image_set_store import PreparedImageSetStore
from fpbench.storage.result_store import ResultStore
from sourceafis_support import require_bridge

pytestmark = [
    pytest.mark.dataset,
    pytest.mark.sourceafis,
    pytest.mark.canonical500,
]

REPO = Path(__file__).resolve().parents[2]
WORKSPACE = REPO / "workspace"

SMOKE_POSITIONS = (FingerprintPosition.RIGHT_THUMB, FingerprintPosition.RIGHT_INDEX)
RELEASES = ("SD300A", "SD300B", "SD300C")
EXPECTED_JOBS = len(SMOKE_POSITIONS) * len(ProtocolStage) * len(RELEASES)  # 24

#: The algorithm looked at the print and declined. A recorded outcome, not a
#: broken run (docs/adr/0006).
ALGORITHMIC = {FailureCode.TEMPLATE_EXTRACTION_FAILED, FailureCode.MATCHING_FAILED}


@pytest.fixture(scope="module")
def canonical_run(tmp_path_factory):
    """A tiny run over the committed prepared-image set."""
    from fpbench.experiments.sd300_inputs import load_sd300_inputs
    from fpbench.experiments.sourceafis_canonical500_full import (
        load_canonical_experiment_config,
    )

    try:
        config = load_canonical_experiment_config()
    except Exception as exc:  # noqa: BLE001 - an unfilled config is "not set up here"
        pytest.skip(f"the canonical experiment is not configured yet: {exc}")

    store = PreparedImageSetStore(WORKSPACE)
    if not store.has_finalization(config.preparation_set_id):
        pytest.skip(
            f"prepared-image set {config.preparation_set_id} is not finalised in "
            "this workspace"
        )

    inputs = load_sd300_inputs(
        workspace=WORKSPACE,
        dataset_root=None,
        dataset_config=config.dataset_config,
        protocol_config=config.protocol_config,
    )

    adapter, _ = require_bridge()
    preparer = Canonical500ImagePreparer(
        store=store,
        preparation_set_id=config.preparation_set_id,
        preparation_set_fingerprint=config.preparation_set_fingerprint,
    )

    # Selected through the image manifest rather than by matching substrings of
    # a pair id. The cyclic impostor stage pairs plain finger i with rolled
    # finger i+1, so a substring match on "f01" also catches the pair whose
    # *right* side is finger 1 — three extra comparisons, and a smoke test that
    # quietly stopped being 24 jobs.
    subject = sorted(inputs.cohort.subject_ids)[0]
    selected = [
        pair
        for pair in inputs.pairs.values()
        if inputs.images[pair.left_image_id].subject_id == subject
        and inputs.images[pair.left_image_id].position in SMOKE_POSITIONS
    ]
    selected.sort(key=lambda pair: str(pair.pair_id))
    assert len(selected) == EXPECTED_JOBS, (
        f"the smoke selection picked {len(selected)} pairs, expected {EXPECTED_JOBS}"
    )

    run = create_run_definition(
        protocol_id=inputs.protocol.protocol_id,
        cohort_id=inputs.cohort.cohort_id,
        pair_manifest_hash=inputs.pair_manifest_hash,
        algorithm=adapter.descriptor,
        environment=adapter.validate_environment(),
        execution_profile=config.execution_profile,
        replicate_index=0,
    )
    plan = build_execution_plan(
        run=run,
        pairs=selected,
        pair_manifest_metadata=dict(inputs.pair_metadata),
    )

    workspace = tmp_path_factory.mktemp("canonical-smoke")
    runner = SingleJobRunner(
        run=run,
        adapter=adapter,
        preparer=preparer,
        result_store=ResultStore(workspace),
        dataset_root=inputs.dataset_root,
        image_index=inputs.images,
        workspace_root=workspace,
    )

    results = []
    for planned in plan.jobs:
        outcome = runner.execute(planned.job, inputs.pairs[planned.job.pair_id])
        results.append((inputs.pairs[planned.job.pair_id], outcome.result))
    return config, plan, results


def test_all_twenty_four_comparisons_are_stored(canonical_run):
    _, plan, results = canonical_run
    assert plan.total_jobs == EXPECTED_JOBS
    assert len(results) == EXPECTED_JOBS


def test_every_release_and_every_stage_is_covered(canonical_run):
    _, _, results = canonical_run
    releases = Counter(pair.release for pair, _ in results)
    stages = Counter(pair.protocol_stage for pair, _ in results)
    assert set(releases) == set(RELEASES)
    assert set(stages) == set(ProtocolStage)
    assert set(releases.values()) == {len(SMOKE_POSITIONS) * len(ProtocolStage)}


def test_no_preparation_and_no_infrastructure_failure(canonical_run):
    """The point of the smoke test.

    An algorithm declining a print is data. Anything else means the canonical
    file never reached the matcher in usable form, and that is a defect
    (spec section 100).
    """
    _, _, results = canonical_run
    blocking = [
        (pair.pair_id, record.failure.code.value)
        for pair, record in results
        if record.status is not ExecutionStatus.SUCCESS
        and record.failure.code not in ALGORITHMIC
    ]
    assert blocking == [], blocking


def test_every_comparison_ran_at_500_ppi_on_both_sides(canonical_run):
    _, _, results = canonical_run
    for pair, record in results:
        assert record.adapter_metadata["left_dpi"] == "500"
        assert record.adapter_metadata["right_dpi"] == "500"
        assert record.runner_metadata["left_output_ppi"] == "500"
        assert record.runner_metadata["right_output_ppi"] == "500"


def test_every_result_names_the_prepared_image_set(canonical_run):
    config, _, results = canonical_run
    for _, record in results:
        metadata = record.runner_metadata
        assert metadata["preparer_id"] == "canonical_500_png"
        assert metadata["runner_metadata_schema"] == "canonical_preparation_v1"
        assert metadata["preparation_set_id"] == config.preparation_set_id
        assert (
            metadata["preparation_set_fingerprint"]
            == config.preparation_set_fingerprint
        )
        assert metadata["transform_profile_id"] == config.transform_profile_id


def test_the_source_resolution_of_each_release_is_recorded(canonical_run):
    """500 goes in for every release; where it came from is still recorded."""
    config, _, results = canonical_run
    expected = {"SD300A": "500", "SD300B": "1000", "SD300C": "2000"}
    for pair, record in results:
        assert record.runner_metadata["left_source_ppi"] == expected[pair.release]
        assert record.runner_metadata["right_source_ppi"] == expected[pair.release]


def test_a_self_comparison_reuses_one_artefact_and_extracts_twice(canonical_run):
    _, _, results = canonical_run
    self_results = [
        (pair, record)
        for pair, record in results
        if pair.protocol_stage.is_self
    ]
    assert self_results
    for _, record in self_results:
        metadata = record.runner_metadata
        assert (
            metadata["left_preparation_entry_hash"]
            == metadata["right_preparation_entry_hash"]
        )
        if record.status is ExecutionStatus.SUCCESS:
            assert record.adapter_metadata["extraction_count"] == "2"


def test_no_threshold_and_no_decision_anywhere(canonical_run):
    _, _, results = canonical_run
    for _, record in results:
        assert record.artifacts == ()
        for forbidden in ("threshold", "decision", "is_match", "ground_truth"):
            assert forbidden not in record.adapter_metadata
            assert forbidden not in record.runner_metadata
