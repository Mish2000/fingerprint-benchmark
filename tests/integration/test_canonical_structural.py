"""The whole canonical chain at the shape of the real experiment, synthetically.

Three releases, four protocol stages, a full prepared-image set, a run over it,
and the same finalisation chain a real run goes through — with a matcher that
hashes bytes instead of extracting minutiae. Nothing here says anything about
fingerprints; everything here says whether the *structure* holds when every
piece is present at once.

It is deliberately smaller than 3,000 images and 6,000 comparisons: the same
shape at a size that runs in CI on every push. The real numbers are asserted by
the dataset-marked tests and by the run itself.
"""

from __future__ import annotations

import pytest

from fpbench.core.enums import (
    GroundTruth,
    PreparationStatus,
    ProtocolStage,
    ResearchRunStatus,
)
from fpbench.core.execution_models import ExecutionProfile
from fpbench.core.identifiers import PairId
from fpbench.core.models import ComparisonPair
from fpbench.execution.research import inspect_research_run
from fpbench.experiments.sourceafis_validation import (
    CanonicalPreparationExpectations,
    validate_sourceafis_result_set,
)
from fpbench.imaging.canonical500 import (
    PREPARER_ID,
    RESOLUTION_MODE,
    Canonical500ImagePreparer,
)
from fpbench.imaging.status import inspect_preparation
from canonicalworld import (
    SOURCE_PPI_BY_RELEASE,
    build_canonical_world,
    publish_receipt_and_marker,
)
from runworld import build_world, finalise_research_world, structural_validation_report

pytestmark = [pytest.mark.imaging, pytest.mark.canonical500]

SUBJECTS = 5
FINGERS = (1, 2, 3, 4)


def _four_stage_pairs(canonical):
    """The real protocol's four stages over the synthetic world.

    PLAIN SELF, ROLL SELF, PLAIN-ROLL mated, and PLAIN-ROLL non-mated with the
    finger shifted by one — the same shape the SD300 protocol generates, so the
    counts a real run asserts have a smaller sibling here.
    """
    by_key: dict[tuple[str, str, str, int], str] = {}
    for image_id, record in canonical.images.items():
        by_key[
            (record.release, str(record.subject_id), record.impression.value,
             int(record.position))
        ] = image_id

    releases = sorted({record.release for record in canonical.images.values()})
    subjects = sorted({str(record.subject_id) for record in canonical.images.values()})
    fingers = sorted({int(record.position) for record in canonical.images.values()})

    pairs: list[ComparisonPair] = []
    for release in releases:
        for subject in subjects:
            for index, finger in enumerate(fingers):
                plain = by_key[(release, subject, "plain", finger)]
                roll = by_key[(release, subject, "roll", finger)]
                impostor_finger = fingers[(index + 1) % len(fingers)]
                impostor = by_key[(release, subject, "roll", impostor_finger)]
                slug = f"{release.lower()}_{subject}_f{finger:02d}"
                pairs.extend(
                    [
                        ComparisonPair(
                            pair_id=PairId(f"{slug}_plainself"),
                            dataset_id="sd300",
                            release=release,
                            left_image_id=plain,
                            right_image_id=plain,
                            ground_truth=GroundTruth.MATED,
                            protocol_stage=ProtocolStage.PLAIN_SELF,
                        ),
                        ComparisonPair(
                            pair_id=PairId(f"{slug}_rollself"),
                            dataset_id="sd300",
                            release=release,
                            left_image_id=roll,
                            right_image_id=roll,
                            ground_truth=GroundTruth.MATED,
                            protocol_stage=ProtocolStage.ROLL_SELF,
                        ),
                        ComparisonPair(
                            pair_id=PairId(f"{slug}_mated"),
                            dataset_id="sd300",
                            release=release,
                            left_image_id=plain,
                            right_image_id=roll,
                            ground_truth=GroundTruth.MATED,
                            protocol_stage=ProtocolStage.PLAIN_ROLL_MATED,
                        ),
                        ComparisonPair(
                            pair_id=PairId(f"{slug}_nonmated"),
                            dataset_id="sd300",
                            release=release,
                            left_image_id=plain,
                            right_image_id=impostor,
                            ground_truth=GroundTruth.NON_MATED,
                            protocol_stage=ProtocolStage.PLAIN_ROLL_NON_MATED,
                        ),
                    ]
                )
    return pairs


def _execution_profile(canonical) -> ExecutionProfile:
    return ExecutionProfile(
        profile_id="canonical_500_lanczos3_60s_v1",
        preparer_id=PREPARER_ID,
        timeout_seconds=60,
        deterministic_seed=0,
        parameters={
            "resolution_mode": RESOLUTION_MODE,
            "target_ppi": "500",
            "transform_profile_id": canonical.profile.profile_id,
            "transform_profile_fingerprint": canonical.profile.profile_fingerprint,
            "preparation_set_id": canonical.preparation_set_id,
            "preparation_set_fingerprint": canonical.preparation_set_fingerprint,
            "output_media_type": "image/png",
            "output_pixel_format": "gray8",
            "output_ppi_metadata_policy": "fixed_500",
        },
    )


@pytest.fixture(scope="module")
def chain(tmp_path_factory):
    root = tmp_path_factory.mktemp("canonical-structural")
    canonical = build_canonical_world(
        root, subjects=SUBJECTS, fingers=FINGERS, base_size=(24, 20)
    )
    publish_receipt_and_marker(canonical)

    preparer = Canonical500ImagePreparer(
        store=canonical.store,
        preparation_set_id=canonical.preparation_set_id,
        preparation_set_fingerprint=canonical.preparation_set_fingerprint,
    )
    world = build_world(
        root / "run",
        research=True,
        preparer=preparer,
        execution_profile=_execution_profile(canonical),
        image_index=canonical.images,
        pairs=_four_stage_pairs(canonical),
    )
    world.executor().execute(finalize=False)
    return canonical, world


# ------------------------------------------------------------ the input set


def test_the_prepared_set_covers_every_release_and_impression(chain):
    canonical, _ = chain
    expected = len(SOURCE_PPI_BY_RELEASE) * SUBJECTS * len(FINGERS) * 2
    assert len(canonical.entries) == expected

    per_release: dict[str, int] = {}
    for entry in canonical.entries:
        per_release.setdefault(
            canonical.images[entry.image_id].release, 0
        )
        per_release[canonical.images[entry.image_id].release] += 1
    assert set(per_release) == set(SOURCE_PPI_BY_RELEASE)
    assert set(per_release.values()) == {SUBJECTS * len(FINGERS) * 2}


def test_the_prepared_set_is_preparation_ready(chain):
    canonical, _ = chain
    state = inspect_preparation(
        store=canonical.store,
        definition=canonical.definition,
        images=canonical.images,
        dataset_root=canonical.dataset_root,
    )
    assert state.status is PreparationStatus.PREPARATION_READY
    assert state.missing_images == 0


def test_every_artefact_is_500_ppi_and_every_a_release_image_is_untouched(chain):
    canonical, _ = chain
    for entry in canonical.entries:
        assert entry.output_effective_ppi == 500
        release = canonical.images[entry.image_id].release
        assert entry.source_effective_ppi == SOURCE_PPI_BY_RELEASE[release]
        if release == "SD300A":
            assert entry.is_identity
            assert entry.source_pixel_sha256 == entry.output_pixel_sha256
        else:
            assert entry.transform_action.startswith("downsample")


# ----------------------------------------------------------------- the run


def test_every_job_used_the_canonical_set(chain):
    canonical, world = chain
    store = world.result_store
    for planned in world.plan.jobs:
        record = store.read_raw_result(world.run.run_id, planned.job.job_id)
        metadata = record.runner_metadata
        assert metadata["preparation_set_id"] == canonical.preparation_set_id
        assert metadata["left_output_ppi"] == "500"
        assert metadata["right_output_ppi"] == "500"


def test_the_stage_and_release_counts_are_what_the_protocol_implies(chain):
    _, world = chain
    stage_counts = dict(world.plan.definition.stage_counts)
    release_counts = dict(world.plan.definition.release_counts)
    per_stage = len(SOURCE_PPI_BY_RELEASE) * SUBJECTS * len(FINGERS)
    per_release = SUBJECTS * len(FINGERS) * len(ProtocolStage)

    assert stage_counts == {stage.value: per_stage for stage in ProtocolStage}
    assert release_counts == {
        release: per_release for release in SOURCE_PPI_BY_RELEASE
    }
    assert world.plan.total_jobs == per_stage * len(ProtocolStage)


def test_the_canonical_validator_passes_over_the_whole_run(chain):
    canonical, world = chain
    preparer = Canonical500ImagePreparer(
        store=canonical.store,
        preparation_set_id=canonical.preparation_set_id,
        preparation_set_fingerprint=canonical.preparation_set_fingerprint,
    )
    preparer.preflight()

    report = validate_sourceafis_result_set(
        run=world.run,
        plan=world.plan,
        pairs=world.pair_index,
        images=world.images,
        result_store=world.result_store,
        runtime_reference=world.runtime_reference,
        preparation=CanonicalPreparationExpectations(
            execution_profile_id="canonical_500_lanczos3_60s_v1",
            preparer_id=preparer.preparer_id,
            preparer_version=preparer.preparer_version,
            runner_metadata_schema=preparer.runner_metadata_schema,
            preparation_set_id=canonical.preparation_set_id,
            preparation_set_fingerprint=canonical.preparation_set_fingerprint,
            transform_profile_id=canonical.profile.profile_id,
            transform_profile_fingerprint=canonical.profile.profile_fingerprint,
            transform_runtime_fingerprint=canonical.runtime.runtime_fingerprint,
            target_ppi=500,
            entries=preparer.prepared_entries(),
            expected_source_ppi=dict(SOURCE_PPI_BY_RELEASE),
        ),
    )
    # The dummy matcher is not SourceAFIS, so the algorithm-identity checks fire.
    # What matters here is that none of the *preparation* checks did.
    preparation_issues = [
        issue
        for issue in report.issues
        if "preparation" in issue.message
        or "prepared" in issue.message
        or "scaled from" in issue.message
        or "artefact" in issue.message
    ]
    assert preparation_issues == [], preparation_issues


def test_a_result_claiming_the_wrong_set_is_caught(chain):
    """The validator compares against the entries, not against another claim."""
    canonical, world = chain
    preparer = Canonical500ImagePreparer(
        store=canonical.store,
        preparation_set_id=canonical.preparation_set_id,
        preparation_set_fingerprint=canonical.preparation_set_fingerprint,
    )
    preparer.preflight()

    report = validate_sourceafis_result_set(
        run=world.run,
        plan=world.plan,
        pairs=world.pair_index,
        images=world.images,
        result_store=world.result_store,
        runtime_reference=world.runtime_reference,
        preparation=CanonicalPreparationExpectations(
            execution_profile_id="canonical_500_lanczos3_60s_v1",
            preparer_id=preparer.preparer_id,
            preparer_version=preparer.preparer_version,
            runner_metadata_schema=preparer.runner_metadata_schema,
            preparation_set_id="prepset_000000000000",
            preparation_set_fingerprint="a" * 64,
            transform_profile_id=canonical.profile.profile_id,
            transform_profile_fingerprint=canonical.profile.profile_fingerprint,
            transform_runtime_fingerprint=canonical.runtime.runtime_fingerprint,
            target_ppi=500,
            entries=preparer.prepared_entries(),
        ),
    )
    assert any(
        "preparation_set_id" in issue.message for issue in report.issues
    ), "the validator accepted results from a different input set"


def test_the_run_reaches_research_ready(chain):
    canonical, world = chain
    receipt = finalise_research_world(world)
    assert receipt.stored_results == world.plan.total_jobs

    state = inspect_research_run(
        run=world.run,
        plan=world.plan,
        result_store=world.result_store,
        pairs=world.pair_index,
        algorithm_validation=structural_validation_report(world),
        primary_asset_role=next(iter(world.runtime_reference.asset_sha256s)),
        verifier_software=world.software,
    )
    assert state.status is ResearchRunStatus.RESEARCH_READY


def test_the_prepared_set_is_still_valid_after_the_run(chain):
    """Executing over a set must not disturb it."""
    canonical, _ = chain
    state = inspect_preparation(
        store=canonical.store,
        definition=canonical.definition,
        images=canonical.images,
        dataset_root=canonical.dataset_root,
    )
    assert state.status is PreparationStatus.PREPARATION_READY
