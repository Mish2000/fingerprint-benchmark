"""A small, complete world to plan and execute runs against.

Building a run by hand takes a dataset root, image records, pairs, a manifest
hash, a run definition, a plan and three stores. Doing that inline in every
test would bury the thing each test is actually about, so it happens once here.

The world is deliberately tiny — a couple of subjects, a couple of fingers —
but structurally identical to the real protocol: four stages, the same pair
shapes, the same identity rules. The 6,000-job test uses the same builder with
bigger numbers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

import pyarrow.parquet as pq

from fpbench.adapters.dummy.adapter import DummyShaAdapter
from fpbench.core.enums import GroundTruth, Impression, ProtocolStage
from fpbench.core.execution_plan_models import ExecutionPlan
from fpbench.core.identifiers import CohortId, ImageId, PairId
from fpbench.core.models import ComparisonPair, ImageRecord
from fpbench.core.result_models import RawResultRecord, RunDefinition
from fpbench.execution.completion import RunCompletionService
from fpbench.execution.planner import build_execution_plan
from fpbench.execution.run_definition import (
    DEFAULT_EXECUTION_PROFILE,
    create_run_definition,
)
from fpbench.execution.runner import SingleJobRunner
from fpbench.imaging.identity import IdentityImagePreparer
from fpbench.storage.plan_store import PlanStore
from fpbench.storage.result_schemas import raw_results_to_table
from fpbench.storage.result_store import ResultStore
from fakes import image_record, sha256_of
from support import make_png

__all__ = [
    "RunWorld",
    "build_world",
    "PROTOCOL_ID",
    "COHORT_ID",
    "pair_manifest_hash_for",
    "write_result_file",
]

PROTOCOL_ID = "sd300_50_subjects"
COHORT_ID = CohortId("sd300_50_subjects_test_ab12cd34")


def pair_manifest_hash_for(pairs: Sequence[ComparisonPair]) -> str:
    """A stand-in for ``ManifestStore.pair_manifest_metadata``'s hash.

    Derived from the pairs themselves rather than being a constant, so that two
    fixtures with different comparisons get different runs — exactly as they
    would in the real pipeline. A shared constant would let a test pass while
    the run identity silently ignored the manifest.
    """
    from fpbench.core.serialization import stable_hash

    return stable_hash(
        {
            "schema": "test_pair_manifest_v1",
            "pairs": sorted(
                (
                    str(pair.pair_id),
                    pair.release,
                    str(pair.left_image_id),
                    str(pair.right_image_id),
                    pair.protocol_stage.value,
                )
                for pair in pairs
            ),
        },
        length=64,
    )

_PLAIN_DIR = "images/500/png/plain"
_ROLL_DIR = "images/500/png/roll"


@dataclass
class RunWorld:
    """Everything needed to plan and execute, wired together."""

    workspace: Path
    dataset_root: Path
    images: dict[ImageId, ImageRecord]
    pairs: tuple[ComparisonPair, ...]
    run: RunDefinition
    plan: ExecutionPlan
    adapter: object
    preparer: object
    pair_manifest_metadata: Mapping[str, str] = field(default_factory=dict)

    @property
    def pair_index(self) -> dict[PairId, ComparisonPair]:
        return {pair.pair_id: pair for pair in self.pairs}

    @property
    def result_store(self) -> ResultStore:
        return ResultStore(self.workspace)

    @property
    def plan_store(self) -> PlanStore:
        return PlanStore(self.workspace)

    @property
    def completion_service(self) -> RunCompletionService:
        return RunCompletionService(result_store=self.result_store)

    def job_runner(self) -> SingleJobRunner:
        return SingleJobRunner(
            run=self.run,
            adapter=self.adapter,
            preparer=self.preparer,
            result_store=self.result_store,
            dataset_root=self.dataset_root,
            image_index=self.images,
            workspace_root=self.workspace,
        )

    def executor(self, **overrides):
        from fpbench.execution.batch_runner import SequentialRunExecutor

        settings = dict(
            plan=self.plan,
            pair_index=self.pair_index,
            job_runner=self.job_runner(),
            result_store=self.result_store,
            completion_service=self.completion_service,
        )
        settings.update(overrides)
        return SequentialRunExecutor(**settings)


def build_world(
    tmp_path: Path,
    *,
    subjects: int = 2,
    fingers: int = 2,
    releases: Sequence[str] = ("SD300A",),
    adapter=None,
    preparer=None,
    replicate_index: int = 0,
) -> RunWorld:
    """Assemble a self-consistent run, plan and workspace.

    Args:
        fingers: At least two. The impostor stage pairs finger *i* with finger
            *i + 1*, so a one-finger world would produce a "non-mated" pair
            comparing a finger with itself — a fixture that quietly contradicts
            the protocol it is standing in for.
        replicate_index: Passed through to the run definition, so a test can
            obtain a genuinely different run over the same pairs.
    """
    if fingers < 2:
        raise ValueError("build_world needs at least two fingers per subject")

    adapter = adapter if adapter is not None else DummyShaAdapter()
    preparer = preparer if preparer is not None else IdentityImagePreparer()

    dataset_root = tmp_path / "nist"
    workspace = tmp_path / "workspace"

    images = _build_images(dataset_root, subjects, fingers, releases)
    pairs = _build_pairs(subjects, fingers, releases)
    manifest_hash = pair_manifest_hash_for(pairs)

    run = create_run_definition(
        protocol_id=PROTOCOL_ID,
        cohort_id=COHORT_ID,
        pair_manifest_hash=manifest_hash,
        algorithm=adapter.descriptor,
        environment=adapter.validate_environment(),
        execution_profile=DEFAULT_EXECUTION_PROFILE,
        replicate_index=replicate_index,
    )
    metadata = {
        "protocol_id": PROTOCOL_ID,
        "cohort_id": str(COHORT_ID),
        "pair_manifest_hash": manifest_hash,
    }
    plan = build_execution_plan(
        run=run, pairs=pairs, pair_manifest_metadata=metadata
    )

    return RunWorld(
        workspace=workspace,
        dataset_root=dataset_root,
        images=images,
        pairs=pairs,
        run=run,
        plan=plan,
        adapter=adapter,
        preparer=preparer,
        pair_manifest_metadata=metadata,
    )


# ------------------------------------------------------------------ builders


def _subject_id(index: int) -> str:
    return f"{1000 + index:08d}"


def _image_id(release: str, subject: str, impression: Impression, finger: int) -> str:
    return f"{release.lower()}_{subject}_{impression.value}_f{finger:02d}"


def _build_images(
    dataset_root: Path, subjects: int, fingers: int, releases: Sequence[str]
) -> dict[ImageId, ImageRecord]:
    """One record per (release, subject, impression, finger).

    Every record points at the same handful of tiny PNGs. Nothing here decodes
    a pixel, and the digests are per-image-id rather than per-file, so the
    records stay distinct without writing thousands of files. No biometric
    claim is made or could be.
    """
    records: dict[ImageId, ImageRecord] = {}
    payload = make_png()

    for release in releases:
        for directory in (_PLAIN_DIR, _ROLL_DIR):
            target = dataset_root / release.lower() / directory
            target.mkdir(parents=True, exist_ok=True)
            (target / "shared.png").write_bytes(payload)

    for release in releases:
        for subject_index in range(subjects):
            subject = _subject_id(subject_index)
            for finger in range(1, fingers + 1):
                for impression, directory in (
                    (Impression.PLAIN, _PLAIN_DIR),
                    (Impression.ROLL, _ROLL_DIR),
                ):
                    image_id = _image_id(release, subject, impression, finger)
                    record = image_record(
                        image_id=image_id,
                        relative_path=f"{release.lower()}/{directory}/shared.png",
                        expected_sha256=sha256_of(image_id),
                        subject_id=subject,
                        release=release,
                        impression=impression,
                    )
                    records[ImageId(image_id)] = record
    return records


def _build_pairs(
    subjects: int, fingers: int, releases: Sequence[str]
) -> tuple[ComparisonPair, ...]:
    """The protocol's four stages, at whatever scale the caller asked for."""
    pairs: list[ComparisonPair] = []
    for release in releases:
        lower = release.lower()
        for subject_index in range(subjects):
            subject = _subject_id(subject_index)
            for finger in range(1, fingers + 1):
                plain = _image_id(release, subject, Impression.PLAIN, finger)
                roll = _image_id(release, subject, Impression.ROLL, finger)
                other = (finger % fingers) + 1
                impostor = _image_id(release, subject, Impression.ROLL, other)

                pairs.append(
                    _pair(
                        f"{lower}_{subject}_f{finger:02d}_plain_self",
                        plain,
                        plain,
                        ProtocolStage.PLAIN_SELF,
                        GroundTruth.MATED,
                        release,
                    )
                )
                pairs.append(
                    _pair(
                        f"{lower}_{subject}_f{finger:02d}_roll_self",
                        roll,
                        roll,
                        ProtocolStage.ROLL_SELF,
                        GroundTruth.MATED,
                        release,
                    )
                )
                pairs.append(
                    _pair(
                        f"{lower}_{subject}_f{finger:02d}_mated",
                        plain,
                        roll,
                        ProtocolStage.PLAIN_ROLL_MATED,
                        GroundTruth.MATED,
                        release,
                    )
                )
                pairs.append(
                    _pair(
                        f"{lower}_{subject}_f{finger:02d}_vs_f{other:02d}_nonmated",
                        plain,
                        impostor,
                        ProtocolStage.PLAIN_ROLL_NON_MATED,
                        GroundTruth.NON_MATED,
                        release,
                    )
                )
    return tuple(pairs)


def _pair(
    pair_id: str,
    left: str,
    right: str,
    stage: ProtocolStage,
    ground_truth: GroundTruth,
    release: str,
) -> ComparisonPair:
    return ComparisonPair(
        pair_id=PairId(pair_id),
        dataset_id="sd300",
        release=release,
        left_image_id=ImageId(left),
        right_image_id=ImageId(right),
        ground_truth=ground_truth,
        protocol_stage=stage,
    )


# --------------------------------------------------------------- corruption


def write_result_file(
    path: Path,
    record: RawResultRecord,
    *,
    metadata: Mapping[str, str] | None = None,
    drop_metadata: Sequence[str] = (),
) -> Path:
    """Write a result file directly, bypassing the store's no-overwrite rule.

    Tests need to forge damaged results — a wrong fingerprint, a stale hash, a
    missing header field — and the store exists precisely to make that
    impossible through its own API. Forging them here keeps the store honest
    while still letting the audit be exercised against every kind of damage it
    claims to detect.
    """
    from fpbench import __version__
    from fpbench.core.result_models import RESULT_SCHEMA_VERSION, raw_result_hash

    header = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "result_hash": raw_result_hash(record),
        "run_id": record.run_id,
        "job_id": record.job_id,
        "job_fingerprint": record.job_fingerprint,
        "pair_manifest_hash": record.pair_manifest_hash,
        "algorithm_fingerprint": record.algorithm_fingerprint,
        "execution_profile_hash": record.execution_profile_hash,
        "fpbench_version": __version__,
        "created_utc": "2026-07-30T00:00:00+00:00",
        "row_count": "1",
    }
    header.update(metadata or {})
    for key in drop_metadata:
        header.pop(key, None)

    table = raw_results_to_table([record])
    stamped = table.replace_schema_metadata(
        {key.encode(): value.encode() for key, value in header.items()}
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(stamped, path, compression="zstd")
    return path
