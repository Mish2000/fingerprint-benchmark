from __future__ import annotations

import pytest

from fpbench.stage21b.errors import (
    Stage21BInfrastructureInterruption,
    Stage21BIntegrityError,
)
from fpbench.stage21b.integrity import (
    audit_cross_method_alignment,
    verify_sealed_run_directory,
)
from fpbench.stage21b.runner import Stage21BRunner
from fpbench.stage21b.store import Stage21BResultStore
from .helpers import (
    ScriptedAdapter,
    SyntheticPreparedInputs,
    algorithm_failure_classifier,
    make_pairs,
    make_spec,
)

pytestmark = pytest.mark.stage21b_contract


def test_73_pairs_times_six_fake_methods_with_interruption_and_resume(tmp_path) -> None:
    pairs = make_pairs(73)
    prepared = SyntheticPreparedInputs(tmp_path / "inputs", pairs)
    directories = {}
    algorithm_ids = tuple(f"fake_method_{index}" for index in range(6))
    for index, algorithm_id in enumerate(algorithm_ids):
        adapter = ScriptedAdapter(
            algorithm_id,
            failure_every=(11 if index in {1, 4} else None),
            interrupt_at=(19 if index == 3 else None),
        )
        spec = make_spec(adapter, pairs)
        store = Stage21BResultStore(
            workspace=tmp_path / "workspace", spec=spec, planned_pairs=pairs
        )
        runner = Stage21BRunner(
            spec=spec,
            adapter=adapter,
            prepared_inputs=prepared,
            store=store,
            failure_classifier=algorithm_failure_classifier,
        )
        if index == 3:
            with pytest.raises(Stage21BInfrastructureInterruption):
                runner.run()
            runner = Stage21BRunner(
                spec=spec,
                adapter=adapter,
                prepared_inputs=prepared,
                store=store,
                failure_classifier=algorithm_failure_classifier,
            )
        report = runner.run()
        assert report["completed_count"] == 73
        assert report["pending_count"] == 0
        assert store.is_sealed
        assert [item.pair.pair_id for item in store.outcomes()] == [
            pair.pair_id for pair in pairs
        ]
        verify_sealed_run_directory(store.run_dir, require_production_shape=False)
        directories[algorithm_id] = store.run_dir

    alignment = audit_cross_method_alignment(
        directories,
        expected_algorithm_ids=algorithm_ids,
        require_production_shape=False,
    )
    assert alignment["method_count"] == 6
    assert alignment["pair_count_per_method"] == 73
    assert alignment["raw_score_column_loaded"] is False
    assert alignment["common_score_population_computed"] is False
    assert all(alignment["gates"].values())


def test_alignment_rejects_one_method_with_a_different_pair_manifest(tmp_path) -> None:
    pairs = make_pairs(7)
    algorithm_ids = ("aligned_a", "aligned_b")
    directories = {}
    for algorithm_id in algorithm_ids:
        adapter = ScriptedAdapter(algorithm_id)
        spec = make_spec(adapter, pairs)
        store = Stage21BResultStore(
            workspace=tmp_path / algorithm_id, spec=spec, planned_pairs=pairs
        )
        Stage21BRunner(
            spec=spec,
            adapter=adapter,
            prepared_inputs=SyntheticPreparedInputs(tmp_path / f"inputs_{algorithm_id}", pairs),
            store=store,
            failure_classifier=algorithm_failure_classifier,
        ).run()
        directories[algorithm_id] = store.run_dir

    variant_pairs = make_pairs(7, variant_at=3)
    adapter = ScriptedAdapter("aligned_b")
    spec = make_spec(adapter, variant_pairs, pair_manifest_hash="f" * 64)
    variant_store = Stage21BResultStore(
        workspace=tmp_path / "variant", spec=spec, planned_pairs=variant_pairs
    )
    Stage21BRunner(
        spec=spec,
        adapter=adapter,
        prepared_inputs=SyntheticPreparedInputs(tmp_path / "variant_inputs", variant_pairs),
        store=variant_store,
        failure_classifier=algorithm_failure_classifier,
    ).run()
    directories["aligned_b"] = variant_store.run_dir

    with pytest.raises(Stage21BIntegrityError, match="not aligned"):
        audit_cross_method_alignment(
            directories,
            expected_algorithm_ids=algorithm_ids,
            require_production_shape=False,
        )
