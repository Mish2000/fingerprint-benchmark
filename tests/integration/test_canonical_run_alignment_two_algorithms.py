"""Two algorithms, one set of inputs — proved without either algorithm.

Stage 7C's claim is a claim about *inputs*: that a second algorithm was handed
the first one's 6,000 pairs, in its order, over its 3,000 prepared images. That
claim is testable long before anybody runs 12,000 subprocesses, and this file is
where it is tested — over a real prepared-image set, a real pair manifest, real
run definitions and the real planner, in a workspace built from a handful of
synthetic rasters (spec section 43).

What is deliberately different between the two runs is the algorithm descriptor,
and that is the whole of it. It produces a different run fingerprint, therefore a
different run id, therefore different job ids and a different plan id — while the
pair ids and their order do not move at all. That separation is what makes stage
7D's eventual join by ``pair_id`` legitimate and a join by ``job_id`` impossible
(spec section 7).

Nothing here is NBIS. No executable is started, no template is extracted and no
score exists; the two "algorithms" are two descriptors. The route itself is
certified in ``tests/integration/test_nbis_upstream.py``.
"""

from __future__ import annotations

import datetime as _dt

import pytest

from fpbench.core.enums import (
    CohortRole,
    EnvironmentStatus,
    GroundTruth,
    Impression,
    ProtocolStage,
    ScoreDirection,
)
from fpbench.core.execution_models import (
    AlgorithmDescriptor,
    EnvironmentReport,
    ExecutionProfile,
)
from fpbench.core.identifiers import CohortId, ImageId, PairId, compose_id
from fpbench.core.models import Cohort, CohortSelection, ComparisonPair
from fpbench.execution.planner import build_execution_plan
from fpbench.execution.run_definition import create_run_definition
from fpbench.experiments.canonical_run_alignment import (
    ReferenceRunIdentity,
    AlignmentExpectations,
    build_canonical_run_alignment_report,
    load_candidate_alignment_side,
    load_reference_alignment_side,
    require_clean_alignment,
)
from fpbench.imaging.canonical500 import Canonical500ImagePreparer
from fpbench.storage.manifest_store import ManifestStore
from fpbench.storage.plan_store import PlanStore
from fpbench.storage.result_store import ResultStore
from canonicalworld import build_canonical_world, publish_receipt_and_marker

pytestmark = [pytest.mark.nbis_contract, pytest.mark.canonical500, pytest.mark.imaging]

RELEASES = ("SD300A", "SD300B", "SD300C")
SUBJECTS = 2
FINGERS = (1, 2)

#: One comparison per finger per stage per release, over the world built below.
PER_CELL = SUBJECTS * len(FINGERS)


def descriptor(name: str, version: str) -> AlgorithmDescriptor:
    return AlgorithmDescriptor(
        algorithm_id=name,
        display_name=name,
        adapter_id=f"{name}_subprocess",
        adapter_version="1",
        adapter_contract_version="1",
        implementation_version=version,
        score_direction=ScoreDirection.HIGHER_IS_BETTER,
        deterministic=True,
    )


def profile(world) -> ExecutionProfile:
    """The same execution profile for both runs, naming the same input set."""
    return ExecutionProfile(
        profile_id="canonical_500_lanczos3_60s_v1",
        preparer_id="canonical_500_png",
        timeout_seconds=60.0,
        deterministic_seed=0,
        parameters={
            "resolution_mode": "canonical_500",
            "target_ppi": "500",
            "transform_profile_id": world.profile.profile_id,
            "transform_profile_fingerprint": world.profile.profile_fingerprint,
            "preparation_set_id": world.preparation_set_id,
            "preparation_set_fingerprint": world.preparation_set_fingerprint,
        },
    )


def environment() -> EnvironmentReport:
    return EnvironmentReport(
        status=EnvironmentStatus.READY,
        implementation_version="1",
        runtime={"fpbench.source.revision": "a" * 40, "fpbench.source.clean": "true"},
        dependencies={"fpbench.package": "0.1.0"},
    )


def build_pairs(images) -> tuple[ComparisonPair, ...]:
    """The four protocol stages, over the world's own images.

    Written here rather than driven through ``SD300Protocol`` on purpose: this
    test is about the alignment check, and generating the pairs from the same
    protocol object twice would make "the two sides agree" true by construction.
    What the check is given is one stored manifest, read twice.
    """
    pairs: list[ComparisonPair] = []
    for release in RELEASES:
        plain = sorted(
            image_id
            for image_id, record in images.items()
            if record.release == release and record.impression is Impression.PLAIN
        )
        roll = sorted(
            image_id
            for image_id, record in images.items()
            if record.release == release and record.impression is Impression.ROLL
        )
        for index, (left, right) in enumerate(zip(plain, roll)):
            other = roll[(index + 1) % len(roll)]
            for stage, first, second, truth in (
                (ProtocolStage.PLAIN_SELF, left, left, GroundTruth.MATED),
                (ProtocolStage.ROLL_SELF, right, right, GroundTruth.MATED),
                (ProtocolStage.PLAIN_ROLL_MATED, left, right, GroundTruth.MATED),
                (
                    ProtocolStage.PLAIN_ROLL_NON_MATED,
                    left,
                    other,
                    GroundTruth.NON_MATED,
                ),
            ):
                pair_id = compose_id(release, stage.value, f"p{index:03d}")
                pairs.append(
                    ComparisonPair(
                        pair_id=PairId(pair_id),
                        dataset_id="sd300",
                        release=release,
                        left_image_id=ImageId(first),
                        right_image_id=ImageId(second),
                        ground_truth=truth,
                        protocol_stage=stage,
                    )
                )
    return tuple(pairs)


@pytest.fixture(scope="module")
def shared(tmp_path_factory):
    """One workspace: one prepared set, one pair manifest, two runs."""
    world = build_canonical_world(
        tmp_path_factory.mktemp("alignment-two"),
        releases=RELEASES,
        subjects=SUBJECTS,
        fingers=FINGERS,
    )
    publish_receipt_and_marker(world)
    workspace = world.workspace

    manifests = ManifestStore(workspace)
    manifest_hashes: dict[str, str] = {}
    for release in RELEASES:
        release_images = [
            record for record in world.images.values() if record.release == release
        ]
        manifests.write_images(
            release_images, dataset_id="sd300", release=release, overwrite=True
        )
        manifest_hashes[release] = manifests.image_manifest_hash("sd300", release)

    subject_ids = tuple(sorted({record.subject_id for record in world.images.values()}))
    cohort = Cohort(
        cohort_id=CohortId("sd300_50_subjects_test_abcdef123456"),
        protocol_id="sd300_50_subjects",
        dataset_id="sd300",
        role=CohortRole.TEST,
        releases=RELEASES,
        subject_ids=subject_ids,
        selection=CohortSelection(
            seed=20260728,
            size=len(subject_ids),
            candidate_ids=subject_ids,
            criteria={"all_ten_plain": "false"},
            image_manifest_hashes=manifest_hashes,
        ),
    )
    manifests.write_cohort(cohort, overwrite=True)
    pairs = build_pairs(world.images)
    manifests.write_pairs(pairs, cohort=cohort, overwrite=True)
    metadata = manifests.pair_manifest_metadata(
        cohort.protocol_id, str(cohort.cohort_id)
    )

    runs = {}
    for label, algorithm in (
        ("reference", descriptor("first_matcher", "3.18.1")),
        ("candidate", descriptor("second_matcher", "5.0.0")),
    ):
        run = create_run_definition(
            protocol_id=cohort.protocol_id,
            cohort_id=cohort.cohort_id,
            pair_manifest_hash=metadata["pair_manifest_hash"],
            algorithm=algorithm,
            environment=environment(),
            execution_profile=profile(world),
            replicate_index=0,
            created_utc=_dt.datetime(2026, 8, 3, tzinfo=_dt.timezone.utc).isoformat(),
        )
        plan = build_execution_plan(
            run=run, pairs=pairs, pair_manifest_metadata=metadata
        )
        ResultStore(workspace).ensure_run(run)
        PlanStore(workspace).ensure_plan(plan)
        runs[label] = (run, plan)

    preparer = Canonical500ImagePreparer(
        store=world.store,
        preparation_set_id=world.preparation_set_id,
        preparation_set_fingerprint=world.preparation_set_fingerprint,
    )
    preparer.preflight()

    expectations = AlignmentExpectations(
        pair_count=PER_CELL * len(ProtocolStage) * len(RELEASES),
        prepared_entry_count=PER_CELL * 2 * len(RELEASES),
        pairs_per_release_stage=PER_CELL,
        prepared_entries_per_release=PER_CELL * 2,
        releases=RELEASES,
    )
    return {
        "world": world,
        "workspace": workspace,
        "cohort": cohort,
        "pairs": {pair.pair_id: pair for pair in pairs},
        "metadata": metadata,
        "runs": runs,
        "preparer": preparer,
        "expectations": expectations,
        "identity": ReferenceRunIdentity(
            run_id=runs["reference"][0].run_id,
            plan_id=runs["reference"][1].plan_id,
            result_set_id="resultset_000000000000",
            preparation_set_id=world.preparation_set_id,
            preparation_set_fingerprint=world.preparation_set_fingerprint,
        ),
    }


def sides(shared):
    reference = load_reference_alignment_side(
        workspace=shared["workspace"], expected=shared["identity"]
    )
    candidate_run, candidate_plan = shared["runs"]["candidate"]
    candidate = load_candidate_alignment_side(
        pairs=shared["pairs"],
        pair_manifest_hash=shared["metadata"]["pair_manifest_hash"],
        protocol_id=shared["cohort"].protocol_id,
        cohort_id=str(shared["cohort"].cohort_id),
        preparation_set_id=shared["world"].preparation_set_id,
        preparation_set_fingerprint=shared["world"].preparation_set_fingerprint,
        prepared_entries=shared["preparer"].prepared_entries(),
        images=shared["world"].images,
        plan=candidate_plan,
        run_id=candidate_run.run_id,
    )
    return reference, candidate


def report_for(shared):
    reference, candidate = sides(shared)
    return build_canonical_run_alignment_report(
        reference=reference,
        candidate=candidate,
        expected_reference=shared["identity"],
        expectations=shared["expectations"],
    )


# ------------------------------------------------------------- what differs


def test_the_two_runs_have_different_identities(shared):
    reference_run, reference_plan = shared["runs"]["reference"]
    candidate_run, candidate_plan = shared["runs"]["candidate"]
    assert reference_run.run_id != candidate_run.run_id
    assert reference_run.run_fingerprint != candidate_run.run_fingerprint
    assert reference_plan.plan_id != candidate_plan.plan_id
    assert reference_run.algorithm.algorithm_id != candidate_run.algorithm.algorithm_id


def test_the_job_ids_differ_because_they_are_derived_from_the_run(shared):
    """Spec section 7: the join is by ``pair_id``, never by ``job_id``."""
    reference_plan = shared["runs"]["reference"][1]
    candidate_plan = shared["runs"]["candidate"][1]
    assert set(reference_plan.job_ids()).isdisjoint(candidate_plan.job_ids())


# ------------------------------------------------------------ what does not


def test_the_two_plans_hold_the_same_pair_ids_in_the_same_order(shared):
    reference_plan = shared["runs"]["reference"][1]
    candidate_plan = shared["runs"]["candidate"][1]
    assert list(reference_plan.pair_ids()) == list(candidate_plan.pair_ids())


def test_the_two_runs_name_one_pair_manifest_and_one_input_set(shared):
    reference_run = shared["runs"]["reference"][0]
    candidate_run = shared["runs"]["candidate"][0]
    assert reference_run.pair_manifest_hash == candidate_run.pair_manifest_hash
    assert dict(reference_run.execution_profile.parameters) == dict(
        candidate_run.execution_profile.parameters
    )
    assert reference_run.execution_profile_hash == candidate_run.execution_profile_hash


def test_the_alignment_is_clean(shared):
    report = report_for(shared)
    assert report.is_clean, [issue.message for issue in report.issues]
    require_clean_alignment(report)


def test_the_alignment_counts_every_row_of_both_sides(shared):
    report = report_for(shared)
    expected = shared["expectations"]
    assert report.reference_pair_count == expected.pair_count
    assert report.candidate_pair_count == expected.pair_count
    assert report.equal_pair_ids == expected.pair_count
    assert report.equal_pair_semantics == expected.pair_count
    assert report.reference_prepared_entries == expected.prepared_entry_count
    assert report.candidate_prepared_entries == expected.prepared_entry_count
    assert report.equal_prepared_entries == expected.prepared_entry_count


def test_the_alignment_names_both_runs(shared):
    report = report_for(shared)
    assert report.reference_run_id == shared["runs"]["reference"][0].run_id
    assert report.candidate_run_id == shared["runs"]["candidate"][0].run_id
    assert report.reference_plan_id == shared["runs"]["reference"][1].plan_id
    assert report.candidate_plan_id == shared["runs"]["candidate"][1].plan_id


def test_the_report_is_reproducible_from_the_same_workspace(shared):
    assert report_for(shared).alignment_fingerprint == (
        report_for(shared).alignment_fingerprint
    )


def test_the_reference_side_is_read_from_the_reference_runs_own_manifests(shared):
    """The set is the one the *run* names, not the one the workspace happens to hold."""
    reference, _ = sides(shared)
    assert reference.preparation_set_id == shared["world"].preparation_set_id
    assert reference.pair_manifest_hash == shared["metadata"]["pair_manifest_hash"]
    assert reference.protocol_id == shared["cohort"].protocol_id
    assert reference.cohort_id == str(shared["cohort"].cohort_id)
    assert len(reference.pair_sequence) == shared["expectations"].pair_count


def test_a_candidate_planned_from_a_different_order_would_be_caught(shared):
    """The guard is real: reversing the candidate's order breaks the alignment."""
    reference, candidate = sides(shared)
    reversed_side = load_candidate_alignment_side(
        pairs=shared["pairs"],
        pair_manifest_hash=shared["metadata"]["pair_manifest_hash"],
        protocol_id=shared["cohort"].protocol_id,
        cohort_id=str(shared["cohort"].cohort_id),
        preparation_set_id=shared["world"].preparation_set_id,
        preparation_set_fingerprint=shared["world"].preparation_set_fingerprint,
        prepared_entries=shared["preparer"].prepared_entries(),
        images=shared["world"].images,
    )
    import dataclasses

    reversed_side = dataclasses.replace(
        reversed_side, pair_sequence=tuple(reversed(reversed_side.pair_sequence))
    )
    report = build_canonical_run_alignment_report(
        reference=reference,
        candidate=reversed_side,
        expected_reference=shared["identity"],
        expectations=shared["expectations"],
    )
    assert not report.is_clean
