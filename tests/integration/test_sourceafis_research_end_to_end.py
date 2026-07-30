"""The whole stage 4B chain, with a real SourceAFIS and no real dataset.

Twenty-four comparisons through an actual JVM, an actual SourceAFIS 3.18.1, an
actual subprocess per comparison and actual parquet result files — then the
whole provenance sequence: runtime revalidation, core audit, SourceAFIS evidence
validation, result set, completion, receipt, ``RESEARCH_READY``.

Nothing is mocked. The one thing that is synthetic is the imagery, because
SD300 is redistribution-restricted and cannot live in a public CI runner; the
fixtures are procedurally generated ridge patterns with roughly human ridge
spacing (``tests/synthetic_ridges.py``). **They are not fingerprints and no
biometric claim follows from any score here** — what this proves is that the
6,000-comparison pipeline works end to end when SourceAFIS is genuinely running
underneath it.

The real 6,000-comparison run is executed locally against the NIST delivery, and
its sanitised receipt is committed under ``evidence/``.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from fpbench.adapters.sourceafis_java.adapter import ADAPTER_ID, SourceAfisJavaAdapter
from fpbench.adapters.sourceafis_java.config import (
    BRIDGE_JAR_ROLE,
    SourceAfisJavaConfig,
)
from fpbench.core.enums import (
    ChecksumStatus,
    EnvironmentStatus,
    GroundTruth,
    Impression,
    ProtocolStage,
    ResearchRunStatus,
    RunState,
)
from fpbench.core.errors import RuntimeDriftError
from fpbench.core.execution_models import ExecutionProfile
from fpbench.core.identifiers import CohortId, ImageId, PairId, SubjectId
from fpbench.core.models import ComparisonPair, ImageRecord
from fpbench.core.runtime_models import RunRuntimeReference
from fpbench.core.serialization import stable_hash
from fpbench.execution.batch_runner import SequentialRunExecutor
from fpbench.execution.completion import RunCompletionService, build_run_completion
from fpbench.execution.planner import build_execution_plan
from fpbench.execution.progress import inspect_run_progress
from fpbench.execution.research import ResearchModeAdapter, inspect_research_run
from fpbench.execution.result_set import build_result_set
from fpbench.execution.run_definition import create_run_definition
from fpbench.execution.runner import SingleJobRunner
from fpbench.experiments.operational_summary import build_operational_summary
from fpbench.experiments.research_receipt import (
    build_research_finalization_marker,
    build_research_receipt,
)
from fpbench.experiments.sourceafis_validation import validate_sourceafis_result_set
from fpbench.imaging.identity import IdentityImagePreparer
from fpbench.storage.plan_store import PlanStore
from fpbench.storage.result_set_store import ResultSetStore
from fpbench.storage.result_store import ResultStore
from fpbench.storage.runtime_bundle_store import RuntimeBundleStore
from runworld import research_provenance, TEST_REVISION
from sourceafis_support import require_bridge
from synthetic_ridges import whorl_png

pytestmark = pytest.mark.sourceafis

PROTOCOL_ID = "sd300_50_subjects"
COHORT_ID = CohortId("synthetic_research_cohort")
RELEASE = "SD300A"
DPI = 500

SUBJECTS = 3
FINGERS = 2
EXPECTED_JOBS = SUBJECTS * FINGERS * len(ProtocolStage)  # 24

NATIVE_PROFILE = ExecutionProfile(
    profile_id="native_identity_60s_v1",
    preparer_id="identity",
    timeout_seconds=60.0,
    deterministic_seed=0,
    parameters={"resolution_mode": "native", "shared_resampling": "none"},
)


# ------------------------------------------------------------------ fixtures


def _image_id(subject: str, impression: Impression, finger: int) -> str:
    return f"{RELEASE.lower()}_{subject}_{impression.value}_f{finger:02d}"


def _build_images(dataset_root: Path) -> dict[ImageId, ImageRecord]:
    """One distinct synthetic ridge image per (subject, impression, finger).

    Distinct seeds, so no two records point at the same bytes: a SELF pair is
    an image against itself, and every other pair is genuinely two images.
    """
    records: dict[ImageId, ImageRecord] = {}
    seed = 0
    for index in range(SUBJECTS):
        subject = f"{1000 + index:08d}"
        for finger in range(1, FINGERS + 1):
            for impression in (Impression.PLAIN, Impression.ROLL):
                seed += 1
                image_id = _image_id(subject, impression, finger)
                relative = f"{RELEASE.lower()}/{impression.value}/{image_id}.png"
                path = dataset_root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                payload = whorl_png(DPI, seed)
                path.write_bytes(payload)

                records[ImageId(image_id)] = ImageRecord(
                    image_id=ImageId(image_id),
                    dataset_id="sd300",
                    release=RELEASE,
                    subject_id=SubjectId(subject),
                    impression=impression,
                    position=None,
                    is_multi_finger=False,
                    relative_path=relative,
                    effective_ppi=DPI,
                    expected_sha256=hashlib.sha256(payload).hexdigest(),
                    checksum_status=ChecksumStatus.VERIFIED,
                )
    return records


def _build_pairs() -> tuple[ComparisonPair, ...]:
    """The protocol's four stages, at 24-comparison scale."""
    pairs: list[ComparisonPair] = []
    for index in range(SUBJECTS):
        subject = f"{1000 + index:08d}"
        for finger in range(1, FINGERS + 1):
            plain = _image_id(subject, Impression.PLAIN, finger)
            roll = _image_id(subject, Impression.ROLL, finger)
            other = (finger % FINGERS) + 1
            impostor = _image_id(subject, Impression.ROLL, other)

            for pair_id, left, right, stage, truth in (
                (f"{subject}_f{finger:02d}_plain_self", plain, plain,
                 ProtocolStage.PLAIN_SELF, GroundTruth.MATED),
                (f"{subject}_f{finger:02d}_roll_self", roll, roll,
                 ProtocolStage.ROLL_SELF, GroundTruth.MATED),
                (f"{subject}_f{finger:02d}_mated", plain, roll,
                 ProtocolStage.PLAIN_ROLL_MATED, GroundTruth.MATED),
                (f"{subject}_f{finger:02d}_nonmated", plain, impostor,
                 ProtocolStage.PLAIN_ROLL_NON_MATED, GroundTruth.NON_MATED),
            ):
                pairs.append(
                    ComparisonPair(
                        pair_id=PairId(pair_id),
                        dataset_id="sd300",
                        release=RELEASE,
                        left_image_id=ImageId(left),
                        right_image_id=ImageId(right),
                        ground_truth=truth,
                        protocol_stage=stage,
                    )
                )
    return tuple(pairs)


@pytest.fixture(scope="module")
def prepared(tmp_path_factory):
    """Materialise a real bundle, pin a real adapter to it, plan 24 jobs."""
    require_bridge()  # skips (or fails, under FPBENCH_REQUIRE_SOURCEAFIS) early

    root = tmp_path_factory.mktemp("sourceafis_research")
    workspace = root / "workspace"
    dataset_root = root / "nist"

    software = research_provenance()
    bundle_store = RuntimeBundleStore(workspace)
    bundle = bundle_store.materialize(
        adapter_id=ADAPTER_ID,
        assets={BRIDGE_JAR_ROLE: SourceAfisJavaConfig().bridge_jar},
    )
    asset = bundle.asset(BRIDGE_JAR_ROLE)

    pinned = SourceAfisJavaConfig().pinned_to(
        bridge_jar=bundle_store.asset_path(bundle.bundle_id, BRIDGE_JAR_ROLE),
        runtime_bundle_id=bundle.bundle_id,
        runtime_bundle_fingerprint=bundle.bundle_fingerprint,
        expected_bridge_jar_sha256=asset.sha256,
        expected_bridge_jar_size=asset.size_bytes,
        fpbench_source_revision=software.source_revision,
    )
    adapter = ResearchModeAdapter(
        delegate=SourceAfisJavaAdapter(pinned),
        software=software,
        runtime_bundle=bundle,
    )
    environment = adapter.validate_environment()
    assert environment.status is EnvironmentStatus.READY, environment.message

    images = _build_images(dataset_root)
    pairs = _build_pairs()
    manifest_hash = stable_hash(
        {"schema": "synthetic_pair_manifest_v1",
         "pairs": sorted(str(pair.pair_id) for pair in pairs)},
        length=64,
    )
    metadata = {
        "protocol_id": PROTOCOL_ID,
        "cohort_id": str(COHORT_ID),
        "pair_manifest_hash": manifest_hash,
    }

    run = create_run_definition(
        protocol_id=PROTOCOL_ID,
        cohort_id=COHORT_ID,
        pair_manifest_hash=manifest_hash,
        algorithm=adapter.descriptor,
        environment=environment,
        execution_profile=NATIVE_PROFILE,
    )
    plan = build_execution_plan(
        run=run, pairs=pairs, pair_manifest_metadata=metadata
    )

    result_store = ResultStore(workspace)
    result_store.ensure_run(run)
    PlanStore(workspace).ensure_plan(plan)
    reference = RunRuntimeReference.create(
        run_id=run.run_id,
        run_fingerprint=run.run_fingerprint,
        environment_fingerprint=run.environment_fingerprint,
        bundle=bundle,
        created_utc="2026-07-30T00:00:00+00:00",
    )
    result_store.ensure_runtime_reference(reference)

    return {
        "workspace": workspace,
        "dataset_root": dataset_root,
        "software": software,
        "bundle": bundle,
        "bundle_store": bundle_store,
        "adapter": adapter,
        "images": images,
        "pairs": {pair.pair_id: pair for pair in pairs},
        "run": run,
        "plan": plan,
        "runtime_reference": reference,
    }


@pytest.fixture(scope="module")
def executed(prepared):
    """Twenty-four real SourceAFIS comparisons, with no completion written."""
    workspace = prepared["workspace"]
    result_store = ResultStore(workspace)

    prepared["bundle_store"].require_valid(prepared["bundle"].bundle_id)

    executor = SequentialRunExecutor(
        plan=prepared["plan"],
        pair_index=prepared["pairs"],
        job_runner=SingleJobRunner(
            run=prepared["run"],
            adapter=prepared["adapter"],
            preparer=IdentityImagePreparer(),
            result_store=result_store,
            dataset_root=prepared["dataset_root"],
            image_index=prepared["images"],
            workspace_root=workspace,
        ),
        result_store=result_store,
        completion_service=RunCompletionService(result_store=result_store),
        plan_store=PlanStore(workspace),
    )
    summary = executor.execute(finalize=False)

    prepared["bundle_store"].require_valid(prepared["bundle"].bundle_id)
    return summary


# ------------------------------------------------------------------ execution


def test_all_twenty_four_comparisons_ran(executed):
    assert executed.newly_executed_jobs == EXPECTED_JOBS
    assert executed.remaining_jobs == 0
    assert executed.completed


def test_the_executor_did_not_declare_the_run_verified(executed, prepared):
    """``finalize=False``: provenance is revalidated by somebody else first."""
    assert not executed.verified
    assert not ResultStore(prepared["workspace"]).has_completion(
        prepared["run"].run_id
    )
    assert inspect_run_progress(
        run=prepared["run"],
        plan=prepared["plan"],
        result_store=ResultStore(prepared["workspace"]),
    ).state is RunState.COMPLETE


def test_every_result_names_the_runtime_bundle_and_the_source_revision(
    executed, prepared
):
    store = ResultStore(prepared["workspace"])
    bundle = prepared["bundle"]
    asset = bundle.asset(BRIDGE_JAR_ROLE)

    for record in store.iter_raw_results(prepared["run"].run_id):
        metadata = record.adapter_metadata
        assert metadata["runtime_bundle_id"] == bundle.bundle_id
        assert metadata["runtime_bundle_fingerprint"] == bundle.bundle_fingerprint
        assert metadata["bridge_jar_sha256"] == asset.sha256
        assert metadata["fpbench_source_revision"] == TEST_REVISION
        assert metadata["sourceafis_version"] == "3.18.1"


def test_no_result_stores_a_path(executed, prepared):
    store = ResultStore(prepared["workspace"])
    for record in store.iter_raw_results(prepared["run"].run_id):
        rendered = repr(record)
        assert str(prepared["workspace"]) not in rendered
        assert str(prepared["dataset_root"]) not in rendered


# ----------------------------------------------------------------- validation


@pytest.fixture(scope="module")
def validation(executed, prepared):
    return validate_sourceafis_result_set(
        run=prepared["run"],
        plan=prepared["plan"],
        pairs=prepared["pairs"],
        images=prepared["images"],
        result_store=ResultStore(prepared["workspace"]),
        runtime_reference=prepared["runtime_reference"],
    )


def test_the_evidence_validates_cleanly(validation):
    assert validation.is_clean, [issue.message for issue in validation.errors]
    assert validation.total_results == EXPECTED_JOBS
    assert validation.blocking_failures == 0


def test_no_infrastructure_failure_occurred(validation):
    """A crash, a timeout or a rejected resolution would block the receipt."""
    forbidden = {
        "process_crashed",
        "timeout",
        "internal_error",
        "unsupported_resolution",
        "input_invalid",
        "image_decode_failed",
        "preparation_failed",
    }
    assert forbidden.isdisjoint(validation.failure_counts)


# --------------------------------------------------------------- finalisation


@pytest.fixture(scope="module")
def finalised(executed, validation, prepared):
    """The external finalisation sequence, in the order docs/adr/0020 fixes."""
    workspace = prepared["workspace"]
    result_store = ResultStore(workspace)

    prepared["bundle_store"].require_valid(prepared["bundle"].bundle_id)

    audit = RunCompletionService(result_store=result_store).audit(
        run=prepared["run"], plan=prepared["plan"]
    )
    assert audit.is_clean

    manifest, entries = build_result_set(
        run=prepared["run"],
        plan=prepared["plan"],
        result_store=result_store,
        runtime_reference=prepared["runtime_reference"],
    )
    ResultSetStore(workspace).ensure_result_set(manifest, entries)

    completion = build_run_completion(
        run=prepared["run"], plan=prepared["plan"], audit=audit
    )
    result_store.ensure_completion(completion)

    summary = build_operational_summary(
        run=prepared["run"],
        plan=prepared["plan"],
        pairs=prepared["pairs"],
        result_store=result_store,
        result_set=manifest,
        runtime_bundle_id=prepared["bundle"].bundle_id,
    )
    receipt = build_research_receipt(
        run=prepared["run"],
        plan=prepared["plan"],
        pairs=prepared["pairs"],
        software=prepared["software"],
        runtime_reference=prepared["runtime_reference"],
        result_set=manifest,
        audit=audit,
        validation=validation,
        completion=completion,
        dataset_id="sd300",
    )
    result_store.ensure_research_receipt(receipt)
    stored_receipt = result_store.read_research_receipt(prepared["run"].run_id)
    marker = build_research_finalization_marker(
        run=prepared["run"],
        plan=prepared["plan"],
        runtime_reference=prepared["runtime_reference"],
        result_set=manifest,
        audit=audit,
        validation=validation,
        completion=completion,
        receipt=stored_receipt,
        verifier_software=prepared["software"],
        created_utc="2026-07-30T00:00:00+00:00",
    )
    result_store.ensure_research_finalization(marker)
    return {"receipt": stored_receipt, "result_set": manifest, "summary": summary}


def test_the_result_set_holds_one_entry_per_planned_job(finalised, prepared):
    manifest, entries = ResultSetStore(prepared["workspace"]).read_result_set(
        prepared["run"].run_id
    )
    assert manifest.total_results == EXPECTED_JOBS
    assert [entry.job_id for entry in entries] == list(prepared["plan"].job_ids())


def test_the_receipt_names_the_real_jar_that_ran(finalised, prepared):
    receipt = finalised["receipt"]
    assert receipt.bridge_jar_sha256 == prepared["bundle"].asset(
        BRIDGE_JAR_ROLE
    ).sha256
    assert receipt.runtime_bundle_id == prepared["bundle"].bundle_id
    assert receipt.source_commit == TEST_REVISION
    assert receipt.blocking_failure_count == 0


def test_the_operational_summary_reports_cost_and_not_scores(finalised):
    summary = finalised["summary"]
    assert summary["counts"]["stored_results"] == EXPECTED_JOBS
    assert summary["timings_ms"]["adapter"]["count"] == EXPECTED_JOBS
    assert summary["timings_ms"]["bridge_total"]["count"] >= 1
    for forbidden in ("mean_score", "score_histogram", "threshold", "fmr", "fnmr"):
        assert forbidden not in summary


def test_the_run_reaches_research_ready(finalised, prepared):
    state = inspect_research_run(
        run=prepared["run"],
        plan=prepared["plan"],
        result_store=ResultStore(prepared["workspace"]),
        pairs=prepared["pairs"],
        algorithm_validation=validate_sourceafis_result_set(
            run=prepared["run"],
            plan=prepared["plan"],
            pairs=prepared["pairs"],
            images=prepared["images"],
            result_store=ResultStore(prepared["workspace"]),
            runtime_reference=prepared["runtime_reference"],
        ),
        primary_asset_role=BRIDGE_JAR_ROLE,
        verifier_software=prepared["software"],
    )
    assert state.status is ResearchRunStatus.RESEARCH_READY, list(state.issues)
    assert state.core_state is RunState.VERIFIED


# ---------------------------------------------------------------- drift, live


def test_replacing_the_pinned_jar_stops_the_adapter(finalised, prepared, tmp_path):
    """The real adapter, the real bundle, a real replacement mid-run.

    The replacement here is byte-identical, and it is still refused. That is
    deliberate: the cheap per-comparison check cannot tell a harmless copy from
    a harmful one without re-hashing 27 MB, and the only safe reading of "the
    file under me was rewritten while I was using it" is that the run stops
    (docs/adr/0018). The full digest, run before and after the executor, is what
    would have said the bytes were fine.
    """
    import shutil
    import stat

    workspace = tmp_path / "drift"
    store = RuntimeBundleStore(workspace)
    bundle = store.materialize(
        adapter_id=ADAPTER_ID,
        assets={BRIDGE_JAR_ROLE: SourceAfisJavaConfig().bridge_jar},
    )
    asset = bundle.asset(BRIDGE_JAR_ROLE)
    adapter = SourceAfisJavaAdapter(
        SourceAfisJavaConfig().pinned_to(
            bridge_jar=store.asset_path(bundle.bundle_id, BRIDGE_JAR_ROLE),
            runtime_bundle_id=bundle.bundle_id,
            runtime_bundle_fingerprint=bundle.bundle_fingerprint,
            expected_bridge_jar_sha256=asset.sha256,
            expected_bridge_jar_size=asset.size_bytes,
            fpbench_source_revision=TEST_REVISION,
        )
    )
    assert adapter.validate_environment().status is EnvironmentStatus.READY

    jar = store.asset_path(bundle.bundle_id, BRIDGE_JAR_ROLE)
    jar.chmod(jar.stat().st_mode | stat.S_IWUSR)
    shutil.copyfile(SourceAfisJavaConfig().bridge_jar, jar)

    with pytest.raises(RuntimeDriftError):
        adapter.check_runtime_integrity()

    # And the digest still matches — which is exactly why the cheap check has to
    # exist. A verification that only hashed would have seen nothing here.
    assert store.verify_bundle(bundle.bundle_id).is_valid
