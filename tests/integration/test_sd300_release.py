"""Checks that only mean something against the real NIST release.

Skipped unless FPBENCH_SD300_ROOT points at a directory. These assertions
encode findings from the independent data-quality review of the delivered
release; if one of them starts failing, the data on disk has changed.
"""

from __future__ import annotations

import pytest

from fpbench.core.models import ImageRecord
from fpbench.datasets.base import summarise_subjects
from fpbench.datasets.sd300.catalog import SD300DatasetProvider, SD300ReleaseLayout
from fpbench.datasets.sd300.validation import IssueCode
from fpbench.protocols.cohorts import CohortCriteria, eligible_subjects

pytestmark = pytest.mark.dataset

RELEASES = ("SD300A", "SD300B", "SD300C")
IMAGES_PER_RELEASE = 19_435
SUBJECTS_PER_RELEASE = 888
SD300C_PPI_ANOMALIES = 10_115


@pytest.fixture(scope="module")
def provider(sd300_root) -> SD300DatasetProvider:
    return SD300DatasetProvider(
        root=sd300_root,
        layouts=[SD300ReleaseLayout(release, release.lower()) for release in RELEASES],
    )


@pytest.fixture(scope="module")
def images(provider) -> dict[str, list[ImageRecord]]:
    """Scanned once; every release is walked three times otherwise."""
    return {release: list(provider.scan(release)) for release in RELEASES}


@pytest.mark.parametrize("release", RELEASES)
def test_release_has_the_expected_number_of_images(images, release):
    assert len(images[release]) == IMAGES_PER_RELEASE


@pytest.mark.parametrize("release", ["SD300A", "SD300B"])
def test_a_and_b_declare_their_resolution_correctly(provider, release):
    assert provider.validate(release).counts_by_code == {}


def test_c_carries_exactly_the_known_ppi_defect(provider):
    report = provider.validate("SD300C")
    assert report.is_clean  # the defect is a warning, never an error
    assert report.counts_by_code == {
        IssueCode.METADATA_PPI_ANOMALY: SD300C_PPI_ANOMALIES
    }


def test_c_images_are_used_at_2000_ppi_regardless_of_their_metadata(images):
    records = images["SD300C"]
    assert all(record.effective_ppi == 2000 for record in records)
    assert sum(1 for r in records if r.metadata_ppi == 5080) == SD300C_PPI_ANOMALIES


def test_the_real_release_contains_no_frgp_15(images):
    assert all(
        record.metadata["frgp"] != "15"
        for records in images.values()
        for record in records
    )


@pytest.mark.parametrize("release", RELEASES)
def test_every_release_covers_the_same_subjects(images, release):
    assert len(summarise_subjects(images[release])) == SUBJECTS_PER_RELEASE


def test_enough_complete_subjects_exist_for_the_protocol(images):
    subjects = [
        record for release in RELEASES for record in summarise_subjects(images[release])
    ]
    criteria = CohortCriteria(size=50, seed=20260728, releases=RELEASES)
    assert len(eligible_subjects(subjects, criteria)) >= 50
