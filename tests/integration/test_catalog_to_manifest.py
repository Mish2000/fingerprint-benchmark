"""Dataset scan -> subject summary -> cohort -> pairs -> manifests, end to end.

Runs against a synthetic SD300-shaped tree, so it exercises the real code path
without needing the 113 GB release.
"""

from __future__ import annotations

import pytest

from fpbench.core.errors import ManifestExistsError
from fpbench.datasets.base import summarise_subjects
from fpbench.protocols.cohorts import CohortCriteria, select_cohort
from fpbench.protocols.pair_generation import PairPlan, generate_pairs
from fpbench.protocols.self_filtering import select_self_eligible_pairs
from fpbench.storage import ManifestStore
from support import MULTI_FINGER_FRGPS, build_release

CRITERIA = CohortCriteria(size=3, seed=11, releases=("SD300A", "SD300B"))


def test_scan_describes_every_file(synthetic_provider):
    images = list(synthetic_provider.scan("SD300A"))
    # 5 subjects x (10 plain + 10 roll + 2 simultaneous captures)
    assert len(images) == 5 * (10 + 10 + len(MULTI_FINGER_FRGPS))
    assert sum(1 for i in images if i.is_multi_finger) == 5 * len(MULTI_FINGER_FRGPS)
    assert all(i.effective_ppi == 500 for i in images)
    assert all(i.relative_path.startswith("sd300a/") for i in images)


def test_a_clean_synthetic_release_validates(synthetic_provider):
    report = synthetic_provider.validate("SD300A")
    assert report.is_clean
    assert report.counts_by_code == {}


def test_a_declared_resolution_defect_is_reported_but_not_fatal(tmp_path):
    from fpbench.datasets.sd300.catalog import SD300DatasetProvider, SD300ReleaseLayout
    from fpbench.datasets.sd300.validation import IssueCode

    build_release(tmp_path, "SD300C", 2000, ["00001000"], declared_ppi=5080)
    provider = SD300DatasetProvider(
        tmp_path, [SD300ReleaseLayout("SD300C", "sd300c")], read_png_metadata=True
    )

    report = provider.validate("SD300C")
    assert report.is_clean  # warnings only
    assert report.counts_by_code == {IssueCode.METADATA_PPI_ANOMALY: report.checked_files}

    images = list(provider.scan("SD300C"))
    assert all(i.effective_ppi == 2000 for i in images)
    assert all(i.metadata_ppi == 5080 for i in images)
    assert all(IssueCode.METADATA_PPI_ANOMALY in i.anomalies for i in images)


def test_the_incomplete_subject_is_excluded_from_the_cohort(synthetic_provider):
    subjects = [
        record
        for release in synthetic_provider.releases
        for record in summarise_subjects(synthetic_provider.scan(release))
    ]
    cohort = select_cohort(
        protocol_id="p",
        dataset_id="sd300",
        subjects=subjects,
        criteria=CRITERIA,
    )
    assert "00001004" not in cohort.selection.candidate_ids
    assert cohort.selection.candidate_count == 4


def test_full_pipeline_round_trips_through_the_store(synthetic_provider, tmp_path):
    store = ManifestStore(tmp_path / "workspace")

    images, subjects = [], []
    for release in synthetic_provider.releases:
        release_images = list(synthetic_provider.scan(release))
        release_subjects = summarise_subjects(release_images)
        store.write_images(release_images, dataset_id="sd300", release=release)
        store.write_subjects(release_subjects, dataset_id="sd300", release=release)
        assert store.read_images("sd300", release) == release_images
        assert store.read_subjects("sd300", release) == release_subjects
        images.extend(release_images)
        subjects.extend(release_subjects)

    cohort = select_cohort(
        protocol_id="p", dataset_id="sd300", subjects=subjects, criteria=CRITERIA
    )
    pairs = generate_pairs(cohort, images, PairPlan())

    store.write_cohort(cohort)
    store.write_pairs(pairs, protocol_id="p")
    assert store.read_cohort("p") == cohort
    assert store.read_pairs("p") == list(pairs)

    # 2 releases x 3 subjects x 10 fingers x 4 stages
    assert len(pairs) == 2 * 3 * 10 * 4


def test_manifests_refuse_to_be_overwritten_by_default(synthetic_provider, tmp_path):
    store = ManifestStore(tmp_path / "workspace")
    images = list(synthetic_provider.scan("SD300A"))
    store.write_images(images, dataset_id="sd300", release="SD300A")

    with pytest.raises(ManifestExistsError):
        store.write_images(images, dataset_id="sd300", release="SD300A")

    store.write_images(images, dataset_id="sd300", release="SD300A", overwrite=True)


def test_the_derived_view_lives_beside_the_manifest_and_does_not_replace_it(
    synthetic_provider, tmp_path
):
    store = ManifestStore(tmp_path / "workspace")
    images = [
        image
        for release in synthetic_provider.releases
        for image in synthetic_provider.scan(release)
    ]
    subjects = summarise_subjects(images)
    cohort = select_cohort(
        protocol_id="p", dataset_id="sd300", subjects=subjects, criteria=CRITERIA
    )
    pairs = generate_pairs(cohort, images, PairPlan())
    store.write_pairs(pairs, protocol_id="p")

    failed = {("SD300A", cohort.subject_ids[0], list(images)[0].position)}
    eligible = select_self_eligible_pairs(pairs, images, failed)
    store.write_derived_pairs(eligible, protocol_id="p")

    assert store.read_pairs("p") == list(pairs)  # untouched
    assert len(store.read_derived_pairs("p")) == len(eligible) < len(pairs)


def test_a_cohort_is_reproducible_from_its_recorded_seed(synthetic_provider):
    subjects = [
        record
        for release in synthetic_provider.releases
        for record in summarise_subjects(synthetic_provider.scan(release))
    ]
    first = select_cohort(
        protocol_id="p", dataset_id="sd300", subjects=subjects, criteria=CRITERIA
    )
    replayed = select_cohort(
        protocol_id="p",
        dataset_id="sd300",
        subjects=list(reversed(subjects)),
        criteria=CRITERIA,
    )
    assert replayed.subject_ids == first.subject_ids
