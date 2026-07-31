"""The final marker is the only authoritative finalization commit point."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from fpbench.adapters.sourceafis_java.config import BRIDGE_JAR_ROLE
from fpbench.core.enums import ResearchRunStatus
from fpbench.execution.research import inspect_research_run
from fpbench.experiments import sourceafis_native_full as experiment
from fpbench.experiments import sourceafis_research
from fpbench.experiments.research_receipt import EVIDENCE_DIRECTORY
from runworld import build_world, structural_validation_report


@pytest.mark.parametrize(
    "write_step",
    ("result_set", "completion", "summary", "receipt"),
)
def test_failure_after_each_intermediate_write_is_retryable_and_not_ready(
    tmp_path, monkeypatch, write_step
):
    """The chain is patched where it now lives: the shared orchestration.

    Since stage 6A the native and canonical experiments are two thin wrappers
    over one implementation, so the injection points moved from
    ``sourceafis_native_full`` to ``sourceafis_research``. The property under
    test is unchanged: a failure at any intermediate write leaves no
    finalization marker, and the next attempt succeeds.
    """
    world = build_world(tmp_path, research=True, asset_role=BRIDGE_JAR_ROLE)
    world.executor().execute(finalize=False)

    prepared = SimpleNamespace(
        spec=SimpleNamespace(
            evidence_directory=EVIDENCE_DIRECTORY,
            is_canonical=False,
            preparation_set_id=None,
        ),
        software=world.software,
        verifier_software=world.software,
        dataset_root=world.dataset_root,
        workspace=world.workspace,
        protocol=SimpleNamespace(dataset_id="sd300"),
        images=world.images,
        pairs=world.pair_index,
        bundle=world.bundle,
        adapter=world.adapter,
        preparer=None,
        run=world.run,
        plan=world.plan,
        runtime_reference=world.runtime_reference,
        result_store=world.result_store,
        result_set_store=world.result_set_store,
        bundle_store=world.bundle_store,
    )
    monkeypatch.setattr(sourceafis_research, "_load_prepared", lambda **_: prepared)
    monkeypatch.setattr(
        sourceafis_research,
        "validate_sourceafis_result_set",
        lambda **_: structural_validation_report(world),
    )
    monkeypatch.setattr(
        sourceafis_research, "write_evidence_copy", lambda *_, **__: None
    )

    calls = 0

    def fail_once_after(original):
        def wrapped(*args, **kwargs):
            nonlocal calls
            result = original(*args, **kwargs)
            calls += 1
            if calls == 1:
                raise RuntimeError(f"injected failure after {write_step}")
            return result

        return wrapped

    if write_step == "result_set":
        monkeypatch.setattr(
            prepared.result_set_store,
            "ensure_result_set",
            fail_once_after(prepared.result_set_store.ensure_result_set),
        )
    elif write_step == "completion":
        monkeypatch.setattr(
            prepared.result_store,
            "ensure_completion",
            fail_once_after(prepared.result_store.ensure_completion),
        )
    elif write_step == "summary":
        monkeypatch.setattr(
            sourceafis_research,
            "write_operational_summary",
            fail_once_after(sourceafis_research.write_operational_summary),
        )
    else:
        monkeypatch.setattr(
            prepared.result_store,
            "ensure_research_receipt",
            fail_once_after(prepared.result_store.ensure_research_receipt),
        )

    with pytest.raises(RuntimeError, match="injected failure"):
        experiment.finalize_sourceafis_native_run(
            workspace=world.workspace,
            repository_root=tmp_path,
        )

    assert not world.result_store.has_research_finalization(world.run.run_id)
    interrupted = _state(world)
    assert interrupted.status is not ResearchRunStatus.RESEARCH_READY

    receipt = experiment.finalize_sourceafis_native_run(
        workspace=world.workspace,
        repository_root=tmp_path,
    )
    assert receipt.run_id == world.run.run_id
    assert world.result_store.has_research_finalization(world.run.run_id)
    assert _state(world).status is ResearchRunStatus.RESEARCH_READY


def _state(world):
    return inspect_research_run(
        run=world.run,
        plan=world.plan,
        result_store=world.result_store,
        pairs=world.pair_index,
        algorithm_validation=structural_validation_report(world),
        primary_asset_role=BRIDGE_JAR_ROLE,
        verifier_software=world.software,
    )
