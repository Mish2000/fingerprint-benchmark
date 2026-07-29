"""Dataset scan -> subject summary -> cohort -> pairs -> manifests, end to end.

Runs against a synthetic SD300-shaped tree, so it exercises the real code path
without needing the 113 GB release.
"""

from __future__ import annotations

import pytest

from fpbench.core.enums import ChecksumStatus, ProtocolStage
from fpbench.core.errors import ManifestExistsError, StorageError
from fpbench.datasets.base import summarise_subjects
from fpbench.protocols.cohorts import CohortCriteria, select_cohort
from fpbench.protocols.pair_generation import PairPlan, generate_pairs
from fpbench.protocols.self_filtering import build_self_eligibility
from fpbench.storage import ManifestStore
from support import MULTI_FINGER_FRGPS, build_release

CRITERIA = CohortCriteria(size=3, seed=11, releases=("SD300A", "SD300B"))
IMAGE_HASHES = {"SD300A": "a" * 64, "SD300B": "b" * 64}


def test_scan_describes_every_file(synthetic_provider):
    images = list(synthetic_provider.scan("SD300A"))
    # 5 subjects x (10 plain + 10 roll + 2 simultaneous captures)
    assert len(images) == 5 * (10 + 10 + len(MULTI_FINGER_FRGPS))
    assert sum(1 for i in images if i.is_multi_finger) == 5 * len(MULTI_FINGER_FRGPS)
    assert all(i.effective_ppi == 500 for i in images)
    assert all(i.relative_path.startswith("sd300a/") for i in images)
    assert all(len(i.expected_sha256) == 64 for i in images)
    assert all(i.checksum_status is ChecksumStatus.NOT_VERIFIED for i in images)
    assert all(i.is_usable for i in images)


def test_a_clean_synthetic_release_validates(synthetic_provider):
    report = synthetic_provider.validate("SD300A")
    assert report.is_clean
    assert report.counts_by_code == {}


def test_validation_detects_a_file_declared_by_checksum_but_missing(tmp_path):
    from fpbench.datasets.sd300.catalog import SD300DatasetProvider, SD300ReleaseLayout
    from fpbench.datasets.sd300.validation import IssueCode

    build_release(tmp_path, "SD300A", 500, ["00001000"])
    missing = tmp_path / "sd300a/images/500/png/roll/00001000_roll_500_01.png"
    missing.unlink()
    provider = SD300DatasetProvider(
        tmp_path, [SD300ReleaseLayout("SD300A", "sd300a")]
    )
    report = provider.validate("SD300A")
    assert not report.is_clean
    assert report.counts_by_code[IssueCode.CHECKSUM_DECLARED_FILE_MISSING] == 1


def test_validation_report_is_persisted_for_audit(synthetic_provider, tmp_path):
    store = ManifestStore(tmp_path / "workspace")
    report = synthetic_provider.validate("SD300A")
    store.write_validation_report(
        report, dataset_id="sd300", release="SD300A"
    )
    persisted = store.read_validation_report("sd300", "SD300A")
    assert persisted["checked_files"] == report.checked_files
    assert persisted["issues"] == []


def test_a_declared_resolution_defect_is_reported_but_not_fatal(tmp_path):
    from fpbench.datasets.sd300.catalog import SD300DatasetProvider, SD300ReleaseLayout
    from fpbench.datasets.sd300.validation import IssueCode

    build_release(tmp_path, "SD300C", 2000, ["00001000"], declared_ppi=5080)
    provider = SD300DatasetProvider(
        tmp_path, [SD300ReleaseLayout("SD300C", "sd300c")]
    )

    report = provider.validate("SD300C")
    assert report.is_clean  # warnings only
    assert report.counts_by_code == {IssueCode.METADATA_PPI_ANOMALY: report.checked_files}

    images = list(provider.scan("SD300C"))
    assert all(i.effective_ppi == 2000 for i in images)
    assert all(i.metadata_ppi == 5080 for i in images)
    assert all(IssueCode.METADATA_PPI_ANOMALY in i.anomalies for i in images)
    assert all(i.is_usable for i in images)


def test_a_validation_error_is_audited_but_cannot_make_a_subject_complete(tmp_path):
    from fpbench.datasets.sd300.catalog import SD300DatasetProvider, SD300ReleaseLayout
    from fpbench.datasets.sd300.validation import IssueCode
    from fpbench.protocols.pair_generation import build_image_index
    from support import make_png

    build_release(tmp_path, "SD300A", 500, ["00001000"])
    bad = tmp_path / "sd300a/images/500/png/plain/00001000_plain_500_11.png"
    bad.write_bytes(make_png(ppi=1200))
    provider = SD300DatasetProvider(
        tmp_path, [SD300ReleaseLayout("SD300A", "sd300a")]
    )

    images = list(provider.scan("SD300A"))
    record = next(image for image in images if image.relative_path.endswith(bad.name))
    assert record.blocking_issues == (IssueCode.UNEXPECTED_METADATA_PPI,)
    assert not record.is_usable
    assert record.image_id not in {image.image_id for image in build_image_index(images).values()}
    [subject] = summarise_subjects(images)
    assert not subject.has_all_ten(record.impression)


def test_full_checksum_verification_is_persisted_and_mismatch_blocks_use(tmp_path):
    from fpbench.datasets.sd300.catalog import SD300DatasetProvider, SD300ReleaseLayout
    from fpbench.datasets.sd300.validation import IssueCode

    build_release(tmp_path, "SD300A", 500, ["00001000"])
    provider = SD300DatasetProvider(
        tmp_path, [SD300ReleaseLayout("SD300A", "sd300a")]
    )
    verified = list(provider.scan("SD300A", verify_checksums=True))
    assert all(image.checksum_status is ChecksumStatus.VERIFIED for image in verified)
    store = ManifestStore(tmp_path / "verified_workspace")
    store.write_images(verified, dataset_id="sd300", release="SD300A")
    assert store.read_images("sd300", "SD300A") == verified

    target = tmp_path / "sd300a/images/500/png/roll/00001000_roll_500_01.png"
    target.write_bytes(target.read_bytes() + b"tampered")
    rescanned = list(provider.scan("SD300A", verify_checksums=True))
    record = next(image for image in rescanned if image.relative_path.endswith(target.name))
    assert record.checksum_status is ChecksumStatus.MISMATCH
    assert IssueCode.CHECKSUM_MISMATCH in record.blocking_issues
    assert not record.is_usable
    audit_store = ManifestStore(tmp_path / "mismatch_workspace")
    with pytest.raises(StorageError, match="validation_override_reason"):
        audit_store.write_images(rescanned, dataset_id="sd300", release="SD300A")
    audit_store.write_images(
        rescanned,
        dataset_id="sd300",
        release="SD300A",
        validation_override_reason="retain checksum mismatch for investigation",
    )
    assert audit_store.image_manifest_metadata("sd300", "SD300A")[
        "validation_override_reason"
    ] == "retain checksum mismatch for investigation"
    assert audit_store.read_images("sd300", "SD300A") == rescanned


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
        image_manifest_hashes=IMAGE_HASHES,
    )
    assert "00001004" not in cohort.selection.candidate_ids
    assert cohort.selection.candidate_count == 4


def test_full_pipeline_round_trips_through_the_store(synthetic_provider, tmp_path):
    store = ManifestStore(tmp_path / "workspace")

    images, subjects = [], []
    image_manifest_hashes = {}
    for release in synthetic_provider.releases:
        release_images = list(synthetic_provider.scan(release))
        release_subjects = summarise_subjects(release_images)
        store.write_images(release_images, dataset_id="sd300", release=release)
        store.write_subjects(release_subjects, dataset_id="sd300", release=release)
        image_manifest_hashes[release] = store.image_manifest_hash("sd300", release)
        assert store.read_images("sd300", release) == release_images
        assert store.read_subjects("sd300", release) == release_subjects
        images.extend(release_images)
        subjects.extend(release_subjects)

    cohort = select_cohort(
        protocol_id="p", dataset_id="sd300", subjects=subjects, criteria=CRITERIA,
        image_manifest_hashes=image_manifest_hashes,
    )
    pairs = generate_pairs(cohort, images, PairPlan())

    store.write_cohort(cohort)
    store.write_pairs(pairs, cohort=cohort)
    assert store.read_cohort("p", cohort.cohort_id) == cohort
    assert store.read_pairs("p", cohort.cohort_id) == list(pairs)
    metadata = store.pair_manifest_metadata("p", cohort.cohort_id)
    assert metadata["protocol_id"] == "p"
    assert metadata["cohort_id"] == cohort.cohort_id
    assert len(metadata["image_manifest_hash"]) == 64
    assert len(metadata["pair_manifest_hash"]) == 64
    first_pair_hash = metadata["pair_manifest_hash"]
    store.write_pairs(pairs, cohort=cohort, overwrite=True)
    assert store.pair_manifest_metadata("p", cohort.cohort_id)[
        "pair_manifest_hash"
    ] == first_pair_hash

    # 2 releases x 3 subjects x 10 fingers x 4 stages
    assert len(pairs) == 2 * 3 * 10 * 4


def test_manifests_refuse_to_be_overwritten_by_default(synthetic_provider, tmp_path):
    store = ManifestStore(tmp_path / "workspace")
    images = list(synthetic_provider.scan("SD300A"))
    store.write_images(images, dataset_id="sd300", release="SD300A")

    with pytest.raises(ManifestExistsError):
        store.write_images(images, dataset_id="sd300", release="SD300A")

    store.write_images(images, dataset_id="sd300", release="SD300A", overwrite=True)


def test_self_eligibility_is_scoped_to_the_run_and_decision_profile(
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
        protocol_id="p", dataset_id="sd300", subjects=subjects, criteria=CRITERIA,
        image_manifest_hashes=IMAGE_HASHES,
    )
    pairs = generate_pairs(cohort, images, PairPlan())
    store.write_pairs(pairs, cohort=cohort)

    failed_pair = next(
        pair
        for pair in pairs
        if pair.protocol_stage is ProtocolStage.PLAIN_SELF
        and pair.release == "SD300A"
    )
    eligibility = build_self_eligibility(pairs, images, {failed_pair.pair_id})
    path = store.write_self_eligibility(
        eligibility,
        run_id="run_001",
        decision_profile_id="native_threshold",
        cohort=cohort,
    )

    assert store.read_pairs("p", cohort.cohort_id) == list(pairs)  # untouched
    assert store.read_self_eligibility("run_001", "native_threshold") == list(
        eligibility
    )
    assert not next(record for record in eligibility if not record.eligible).plain_self_passed
    assert "results/run_001/decisions/native_threshold" in path.as_posix()


def test_a_cohort_is_reproducible_from_its_recorded_seed(synthetic_provider):
    subjects = [
        record
        for release in synthetic_provider.releases
        for record in summarise_subjects(synthetic_provider.scan(release))
    ]
    first = select_cohort(
        protocol_id="p", dataset_id="sd300", subjects=subjects, criteria=CRITERIA,
        image_manifest_hashes=IMAGE_HASHES,
    )
    replayed = select_cohort(
        protocol_id="p",
        dataset_id="sd300",
        subjects=list(reversed(subjects)),
        criteria=CRITERIA,
        image_manifest_hashes=IMAGE_HASHES,
    )
    assert replayed.subject_ids == first.subject_ids


def test_two_cohorts_of_one_protocol_coexist(synthetic_provider, tmp_path):
    images = [
        image
        for release in synthetic_provider.releases
        for image in synthetic_provider.scan(release)
    ]
    subjects = summarise_subjects(images)
    first = select_cohort(
        protocol_id="p", dataset_id="sd300", subjects=subjects,
        criteria=CRITERIA, image_manifest_hashes=IMAGE_HASHES,
    )
    second = select_cohort(
        protocol_id="p", dataset_id="sd300", subjects=subjects,
        criteria=CohortCriteria(
            size=CRITERIA.size, seed=12, releases=CRITERIA.releases
        ),
        image_manifest_hashes=IMAGE_HASHES,
    )
    store = ManifestStore(tmp_path / "workspace")
    for cohort in (first, second):
        store.write_cohort(cohort)
        store.write_pairs(generate_pairs(cohort, images, PairPlan()), cohort=cohort)

    assert first.cohort_id != second.cohort_id
    assert store.cohort_path("p", first.cohort_id).is_file()
    assert store.cohort_path("p", second.cohort_id).is_file()


def test_manifest_content_hash_ignores_creation_timestamp(synthetic_provider, tmp_path):
    store = ManifestStore(tmp_path / "workspace")
    images = list(synthetic_provider.scan("SD300A"))
    store.write_images(images, dataset_id="sd300", release="SD300A")
    first = store.image_manifest_hash("sd300", "SD300A")
    store.write_images(
        images, dataset_id="sd300", release="SD300A", overwrite=True
    )
    assert store.image_manifest_hash("sd300", "SD300A") == first
