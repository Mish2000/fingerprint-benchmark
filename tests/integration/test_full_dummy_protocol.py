"""The whole protocol, end to end, at full scale.

50 subjects x 10 fingers x 4 stages x 3 releases = 6,000 comparisons, planned
and executed through the real pipeline: the real ``SD300Protocol``, the real
manifest store, the real planner, the real executor, the real audit. Only the
imagery is synthetic.

Since stage 4B it also carries the full provenance chain at scale: a
content-addressed runtime bundle, a run whose environment names its source
revision, external finalisation, a 6,000-entry result-set manifest and a
sanitised receipt. Those need to be exercised at six thousand rows rather than
sixteen, and running six thousand real SourceAFIS comparisons in CI to do it
would take hours to prove something about bookkeeping.

Marked ``full_run`` and excluded from the ordinary suite, because it takes
minutes rather than seconds. It has its own CI workflow.

**No biometric claim is made or possible here.** Every ``ImageRecord`` points at
the same handful of tiny PNGs; only the ids and digests differ. The dummy
matcher scores those digests. What this test proves is that the harness can
plan, execute, resume, audit, verify and *attribute* six thousand comparisons
without losing or duplicating one — nothing whatsoever about fingerprints.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fpbench.adapters.dummy.adapter import DummyShaAdapter
from fpbench.core.enums import (
    ChecksumStatus,
    FingerprintPosition,
    Impression,
    ProtocolStage,
    ResearchRunStatus,
    RunState,
)
from fpbench.core.identifiers import ImageId, SubjectId
from fpbench.core.models import ImageRecord, SubjectRecord
from fpbench.core.runtime_models import RunRuntimeReference
from fpbench.execution.batch_runner import SequentialRunExecutor
from fpbench.execution.completion import RunCompletionService
from fpbench.execution.planner import build_execution_plan
from fpbench.execution.progress import inspect_run_progress
from fpbench.execution.research import ResearchModeAdapter, inspect_research_run
from fpbench.execution.result_set import build_result_set
from fpbench.execution.run_definition import (
    DEFAULT_EXECUTION_PROFILE,
    create_run_definition,
)
from fpbench.execution.runner import SingleJobRunner
from fpbench.imaging.identity import IdentityImagePreparer
from fpbench.protocols.sd300_protocol import SD300Protocol
from fpbench.storage.manifest_store import ManifestStore
from fpbench.storage.plan_store import PlanStore
from fpbench.storage.result_set_store import ResultSetStore
from fpbench.storage.result_store import ResultStore
from fpbench.storage.runtime_bundle_store import RuntimeBundleStore
from fakes import CountingPreparer, sha256_of
from runworld import FAKE_ASSET_ROLE, research_provenance, write_fake_asset
from support import make_png

pytestmark = pytest.mark.full_run

REPO = Path(__file__).resolve().parents[2]
PROTOCOL_CONFIG = REPO / "configs" / "protocols" / "sd300_50_subjects.yaml"

SUBJECT_COUNT = 50
RELEASES = ("SD300A", "SD300B", "SD300C")
EFFECTIVE_PPI = {"SD300A": 500, "SD300B": 1000, "SD300C": 2000}

EXPECTED_JOBS = 6_000
EXPECTED_PER_STAGE = 1_500
EXPECTED_PER_RELEASE = 2_000


# ------------------------------------------------------------------ synthetic


def _shared_image(dataset_root: Path) -> str:
    """One tiny PNG that every synthetic record points at."""
    relative = "synthetic/shared.png"
    path = dataset_root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(make_png())
    return relative


def _images(dataset_root: Path) -> dict[ImageId, ImageRecord]:
    relative = _shared_image(dataset_root)
    records: dict[ImageId, ImageRecord] = {}
    for release in RELEASES:
        for index in range(SUBJECT_COUNT):
            subject = f"{1000 + index:08d}"
            for position in FingerprintPosition:
                for impression in (Impression.PLAIN, Impression.ROLL):
                    image_id = (
                        f"{release.lower()}_{subject}_{impression.value}_"
                        f"{position.label}"
                    )
                    records[ImageId(image_id)] = ImageRecord(
                        image_id=ImageId(image_id),
                        dataset_id="sd300",
                        release=release,
                        subject_id=SubjectId(subject),
                        impression=impression,
                        position=position,
                        is_multi_finger=False,
                        relative_path=relative,
                        effective_ppi=EFFECTIVE_PPI[release],
                        expected_sha256=sha256_of(image_id),
                        checksum_status=ChecksumStatus.VERIFIED,
                    )
    return records


def _subjects(images: dict[ImageId, ImageRecord]) -> list[SubjectRecord]:
    from fpbench.datasets.base import summarise_subjects

    return summarise_subjects(images.values())


@pytest.fixture(scope="module")
def protocol() -> SD300Protocol:
    return SD300Protocol.from_config_file(PROTOCOL_CONFIG)


@pytest.fixture(scope="module")
def world(tmp_path_factory, protocol):
    """The full protocol, planned but not yet executed."""
    root = tmp_path_factory.mktemp("full_run")
    dataset_root = root / "nist"
    workspace = root / "workspace"

    images = _images(dataset_root)
    manifest_store = ManifestStore(workspace)

    manifest_hashes = {}
    for release in RELEASES:
        release_images = [i for i in images.values() if i.release == release]
        release_subjects = [s for s in _subjects(images) if s.release == release]
        manifest_store.write_images(
            release_images, dataset_id="sd300", release=release
        )
        manifest_store.write_subjects(
            release_subjects, dataset_id="sd300", release=release
        )
        manifest_hashes[release] = manifest_store.image_manifest_hash("sd300", release)

    cohort = protocol.build_cohort(_subjects(images), manifest_hashes)
    pairs = protocol.build_pairs(cohort, list(images.values()))
    manifest_store.write_cohort(cohort)
    manifest_store.write_pairs(pairs, cohort=cohort)
    pair_metadata = manifest_store.pair_manifest_metadata(
        protocol.protocol_id, cohort.cohort_id
    )

    # The provenance chain, at scale. The bundle holds a stand-in file rather
    # than a jar: what is under test is that 6,000 results can be bound to one
    # identified executable, not what that executable does.
    software = research_provenance()
    bundle = RuntimeBundleStore(workspace).materialize(
        adapter_id=DummyShaAdapter().descriptor.adapter_id,
        assets={FAKE_ASSET_ROLE: write_fake_asset(root / "build")},
    )
    adapter = _adapter(software, bundle)

    run = create_run_definition(
        protocol_id=protocol.protocol_id,
        cohort_id=cohort.cohort_id,
        pair_manifest_hash=pair_metadata["pair_manifest_hash"],
        algorithm=adapter.descriptor,
        environment=adapter.validate_environment(),
        execution_profile=DEFAULT_EXECUTION_PROFILE,
    )
    plan = build_execution_plan(
        run=run, pairs=pairs, pair_manifest_metadata=pair_metadata
    )

    reference = RunRuntimeReference.create(
        run_id=run.run_id,
        run_fingerprint=run.run_fingerprint,
        environment_fingerprint=run.environment_fingerprint,
        bundle=bundle,
        created_utc="2026-07-30T00:00:00+00:00",
    )
    ResultStore(workspace).ensure_runtime_reference(reference)

    return {
        "dataset_root": dataset_root,
        "workspace": workspace,
        "images": images,
        "cohort": cohort,
        "pairs": pairs,
        "run": run,
        "plan": plan,
        "software": software,
        "bundle": bundle,
        "runtime_reference": reference,
    }


def _adapter(software, bundle) -> ResearchModeAdapter:
    return ResearchModeAdapter(
        delegate=DummyShaAdapter(), software=software, runtime_bundle=bundle
    )


def _executor(world, *, adapter=None, preparer=None):
    adapter = adapter or _adapter(world["software"], world["bundle"])
    preparer = preparer or IdentityImagePreparer()
    result_store = ResultStore(world["workspace"])
    job_runner = SingleJobRunner(
        run=world["run"],
        adapter=adapter,
        preparer=preparer,
        result_store=result_store,
        dataset_root=world["dataset_root"],
        image_index=world["images"],
        workspace_root=world["workspace"],
    )
    return SequentialRunExecutor(
        plan=world["plan"],
        pair_index={pair.pair_id: pair for pair in world["pairs"]},
        job_runner=job_runner,
        result_store=result_store,
        completion_service=RunCompletionService(result_store=result_store),
        plan_store=PlanStore(world["workspace"]),
    )


# ------------------------------------------------------------------- planning


def test_the_protocol_yields_exactly_six_thousand_pairs(world):
    assert len(world["pairs"]) == EXPECTED_JOBS
    assert len(world["cohort"].subject_ids) == SUBJECT_COUNT


def test_the_plan_covers_every_pair_once(world):
    plan = world["plan"]
    assert plan.total_jobs == EXPECTED_JOBS
    assert len(plan.jobs) == EXPECTED_JOBS
    assert len(set(plan.job_ids())) == EXPECTED_JOBS
    assert len(set(plan.pair_ids())) == EXPECTED_JOBS
    assert len({item.job.job_fingerprint for item in plan.jobs}) == EXPECTED_JOBS


def test_the_stage_counts_match_the_protocol(world):
    counts = world["plan"].definition.stage_counts
    assert counts == {stage.value: EXPECTED_PER_STAGE for stage in ProtocolStage}


def test_the_release_counts_match_the_protocol(world):
    counts = world["plan"].definition.release_counts
    assert counts == {release: EXPECTED_PER_RELEASE for release in RELEASES}


def test_the_ordinals_are_contiguous(world):
    assert [item.ordinal for item in world["plan"].jobs] == list(range(EXPECTED_JOBS))


# ------------------------------------------------------------------ execution


def test_a_full_run_executes_and_stores_without_declaring_itself_finished(world):
    """The single expensive test: 6,000 comparisons, once, with no completion.

    ``finalize=False`` is what a research run uses. Every result is present and
    the audit is clean, and the run is still not verified — because nothing has
    yet re-checked that the executable underneath it is the one it started with
    (docs/adr/0020).
    """
    summary = _executor(world).execute(finalize=False)

    assert summary.newly_executed_jobs == EXPECTED_JOBS
    assert summary.skipped_existing_jobs == 0
    assert summary.remaining_jobs == 0
    assert summary.successful_results_seen == EXPECTED_JOBS
    assert summary.failed_results_seen == 0
    assert summary.completed
    assert not summary.verified

    result_store = ResultStore(world["workspace"])
    assert len(result_store.stored_job_ids(world["run"].run_id)) == EXPECTED_JOBS
    assert not result_store.has_completion(world["run"].run_id)

    from fpbench.execution.audit import audit_run

    report = audit_run(
        run=world["run"], plan=world["plan"], result_store=result_store
    )
    assert report.is_clean
    assert report.planned_jobs == EXPECTED_JOBS
    assert report.valid_results == EXPECTED_JOBS
    assert report.success_count == EXPECTED_JOBS
    assert report.failure_count == 0
    assert report.missing_job_ids == ()
    assert report.extra_result_job_ids == ()

    progress = inspect_run_progress(
        run=world["run"], plan=world["plan"], result_store=result_store
    )
    assert progress.state is RunState.COMPLETE
    assert progress.stored_results == EXPECTED_JOBS
    assert progress.missing_results == 0


def test_a_second_run_does_nothing_at_all(world):
    """Depends on the run above; ordering within the module is deliberate."""
    # A resumed run must use an adapter whose descriptor matches the run
    # definition exactly, so the real matcher is wrapped rather than replaced.
    counting = _CountingWrapper(_adapter(world["software"], world["bundle"]))
    preparer = CountingPreparer()

    summary = _executor(world, adapter=counting, preparer=preparer).execute(
        finalize=False
    )

    assert summary.newly_executed_jobs == 0
    assert summary.skipped_existing_jobs == EXPECTED_JOBS
    assert summary.remaining_jobs == 0
    assert counting.compare_calls == 0
    assert preparer.calls == 0
    assert summary.completed and not summary.verified


# ------------------------------------------------------------- finalisation


def test_external_finalisation_produces_the_whole_evidence_chain(world):
    """Six thousand result hashes, one completion, one sanitised receipt."""
    from runworld import (
        RunWorld,
        finalise_research_world,
        structural_validation_report,
    )

    run_world = _as_run_world(world)
    receipt = finalise_research_world(run_world)

    result_store = ResultStore(world["workspace"])
    completion = result_store.read_completion(world["run"].run_id)
    assert completion.planned_jobs == EXPECTED_JOBS
    assert completion.success_count == EXPECTED_JOBS

    manifest, entries = ResultSetStore(world["workspace"]).read_result_set(
        world["run"].run_id
    )
    assert manifest.total_results == EXPECTED_JOBS
    assert len(entries) == EXPECTED_JOBS
    assert [entry.ordinal for entry in entries] == list(range(EXPECTED_JOBS))
    assert [entry.job_id for entry in entries] == list(world["plan"].job_ids())
    assert len({entry.result_hash for entry in entries}) == EXPECTED_JOBS

    assert receipt.planned_jobs == EXPECTED_JOBS
    assert receipt.stored_results == EXPECTED_JOBS
    assert receipt.blocking_failure_count == 0
    assert receipt.release_counts == {
        release: EXPECTED_PER_RELEASE for release in RELEASES
    }
    assert receipt.stage_counts == {
        stage.value: EXPECTED_PER_STAGE for stage in ProtocolStage
    }

    state = inspect_research_run(
        run=world["run"],
        plan=world["plan"],
        result_store=result_store,
        pairs=run_world.pair_index,
        algorithm_validation=structural_validation_report(run_world),
        primary_asset_role=next(
            iter(run_world.runtime_reference.asset_sha256s)
        ),
        verifier_software=run_world.software,
    )
    assert state.status is ResearchRunStatus.RESEARCH_READY


def test_one_changed_result_would_change_the_result_set_fingerprint(world):
    """The property that makes citing a result set worth anything."""
    from fpbench.core.result_set_models import ResultSetEntry, result_set_fingerprint

    manifest, entries = ResultSetStore(world["workspace"]).read_result_set(
        world["run"].run_id
    )
    mutated = (
        ResultSetEntry(entries[0].ordinal, entries[0].job_id, "a" * 64),
        *entries[1:],
    )
    assert (
        result_set_fingerprint(
            run_fingerprint=manifest.run_fingerprint,
            plan_fingerprint=manifest.plan_fingerprint,
            runtime_bundle_fingerprint=manifest.runtime_bundle_fingerprint,
            entries=mutated,
            success_count=manifest.success_count,
            failure_count=manifest.failure_count,
        )
        != manifest.result_set_fingerprint
    )


def test_the_receipt_carries_no_path_no_score_and_no_conclusion(world):
    path = ResultStore(world["workspace"]).research_receipt_path(
        world["run"].run_id
    )
    text = path.read_text(encoding="utf-8")
    assert str(world["workspace"]) not in text
    assert str(world["dataset_root"]) not in text
    for forbidden in ("raw_score", "subject_id", "image_id", "threshold", "eer"):
        assert forbidden not in text.lower()
    assert "no biometric performance conclusion" in text


def _as_run_world(world):
    """Adapt the dict fixture to the shape ``finalise_research_world`` expects."""
    from runworld import RunWorld

    return RunWorld(
        workspace=world["workspace"],
        dataset_root=world["dataset_root"],
        images=world["images"],
        pairs=world["pairs"],
        run=world["run"],
        plan=world["plan"],
        adapter=_adapter(world["software"], world["bundle"]),
        preparer=IdentityImagePreparer(),
        software=world["software"],
        bundle=world["bundle"],
        runtime_reference=world["runtime_reference"],
    )


class _CountingWrapper:
    """Delegates everything to a real adapter while counting comparisons.

    Needed because a resumed run must use an adapter whose descriptor matches
    the run definition exactly — a differently named fake would fail preflight,
    which is a different thing from what this test is checking.
    """

    def __init__(self, delegate) -> None:
        self._delegate = delegate
        self.compare_calls = 0

    @property
    def descriptor(self):
        return self._delegate.descriptor

    def validate_environment(self):
        return self._delegate.validate_environment()

    def compare(self, left, right, context):
        self.compare_calls += 1
        return self._delegate.compare(left, right, context)


def test_no_absolute_path_reached_any_stored_result(world):
    result_store = ResultStore(world["workspace"])
    dataset_root = str(world["dataset_root"])
    workspace = str(world["workspace"])
    for record in result_store.iter_raw_results(world["run"].run_id):
        rendered = repr(record)
        assert dataset_root not in rendered
        assert workspace not in rendered


def test_every_stored_result_carries_the_run_provenance(world):
    run = world["run"]
    result_store = ResultStore(world["workspace"])
    for record in result_store.iter_raw_results(run.run_id):
        assert record.run_id == run.run_id
        assert record.pair_manifest_hash == run.pair_manifest_hash
        assert record.algorithm_fingerprint == run.algorithm_fingerprint
        assert record.execution_profile_hash == run.execution_profile_hash
        assert record.attempt == 1


def test_no_stored_result_carries_a_decision(world):
    result_store = ResultStore(world["workspace"])
    record = next(iter(result_store.iter_raw_results(world["run"].run_id)))
    fields = set(type(record).__dataclass_fields__)
    assert {"threshold", "decision", "ground_truth", "protocol_stage"} & fields == set()
