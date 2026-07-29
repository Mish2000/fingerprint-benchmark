"""The preparer must refuse anything it cannot faithfully hand to an adapter."""

from __future__ import annotations

from pathlib import Path

import pytest

from fpbench.core.enums import ChecksumStatus
from fpbench.core.errors import ImagePreparationError
from fpbench.execution.run_definition import DEFAULT_EXECUTION_PROFILE
from fpbench.imaging.identity import IdentityImagePreparer
from fakes import image_record, sha256_of
from support import make_png

PROFILE = DEFAULT_EXECUTION_PROFILE


@pytest.fixture
def dataset_root(tmp_path: Path) -> Path:
    root = tmp_path / "nist"
    target = root / "sd300a" / "images" / "500" / "png" / "plain"
    target.mkdir(parents=True)
    (target / "00001000_plain_500_11.png").write_bytes(make_png())
    return root


RELATIVE = "sd300a/images/500/png/plain/00001000_plain_500_11.png"


def record(**overrides):
    defaults = dict(
        image_id="sd300a_00001000_plain_f01",
        relative_path=RELATIVE,
        expected_sha256=sha256_of(make_png()),
    )
    return image_record(**{**defaults, **overrides})


def test_prepares_a_usable_image(dataset_root):
    prepared = IdentityImagePreparer().prepare(record(), dataset_root, PROFILE)
    assert prepared.local_path == (dataset_root / RELATIVE).resolve()
    assert prepared.local_path.is_file()
    assert prepared.media_type == "image/png"
    assert prepared.preparation_profile_id == PROFILE.profile_id


def test_leaves_the_source_file_untouched(dataset_root):
    path = dataset_root / RELATIVE
    before = path.read_bytes()
    IdentityImagePreparer().prepare(record(), dataset_root, PROFILE)
    assert path.read_bytes() == before


def test_carries_the_resolution_and_digest_through(dataset_root):
    prepared = IdentityImagePreparer().prepare(
        record(effective_ppi=2000, checksum_status=ChecksumStatus.VERIFIED),
        dataset_root,
        PROFILE,
    )
    assert prepared.effective_ppi == 2000
    assert prepared.expected_sha256 == sha256_of(make_png())
    assert prepared.checksum_status is ChecksumStatus.VERIFIED


def test_rejects_a_blocked_image(dataset_root):
    blocked = record(blocking_issues=("filename_ppi_mismatch",))
    with pytest.raises(ImagePreparationError, match="blocked"):
        IdentityImagePreparer().prepare(blocked, dataset_root, PROFILE)


def test_rejects_an_image_whose_bytes_failed_verification(dataset_root):
    mismatched = record(checksum_status=ChecksumStatus.MISMATCH)
    with pytest.raises(ImagePreparationError, match="blocked"):
        IdentityImagePreparer().prepare(mismatched, dataset_root, PROFILE)


def test_rejects_a_missing_file(dataset_root):
    absent = record(relative_path="sd300a/images/500/png/plain/nope.png")
    with pytest.raises(ImagePreparationError, match="not found"):
        IdentityImagePreparer().prepare(absent, dataset_root, PROFILE)


def test_rejects_a_directory(dataset_root):
    directory = record(relative_path="sd300a/images/500/png/plain")
    with pytest.raises(ImagePreparationError):
        IdentityImagePreparer().prepare(directory, dataset_root, PROFILE)


@pytest.mark.parametrize(
    "relative", ["../secrets.png", "sd300a/../../secrets.png", "a/b/../../../x.png"]
)
def test_rejects_path_traversal(dataset_root, relative):
    with pytest.raises(ImagePreparationError):
        IdentityImagePreparer().prepare(
            record(relative_path=relative), dataset_root, PROFILE
        )


@pytest.mark.parametrize("relative", ["/etc/passwd", "C:\\Windows\\win.ini"])
def test_rejects_an_absolute_path(dataset_root, relative):
    with pytest.raises(ImagePreparationError, match="must be relative"):
        IdentityImagePreparer().prepare(
            record(relative_path=relative), dataset_root, PROFILE
        )


def test_rejects_a_format_it_cannot_pass_through(dataset_root):
    wsq = dataset_root / "sd300a" / "images" / "500" / "png" / "plain" / "x.wsq"
    wsq.write_bytes(b"not really wsq")
    with pytest.raises(ImagePreparationError, match="does not handle"):
        IdentityImagePreparer().prepare(
            record(relative_path="sd300a/images/500/png/plain/x.wsq"),
            dataset_root,
            PROFILE,
        )


def test_preparation_hash_is_deterministic(dataset_root):
    preparer = IdentityImagePreparer()
    first = preparer.prepare(record(), dataset_root, PROFILE)
    second = preparer.prepare(record(), dataset_root, PROFILE)
    assert first.preparation_hash == second.preparation_hash


def test_preparation_hash_does_not_depend_on_where_the_dataset_lives(tmp_path):
    """Two machines with the data unpacked differently must agree."""
    hashes = []
    for name in ("first-machine", "second-machine"):
        root = tmp_path / name / "deeper" / "still"
        target = root / "sd300a" / "images" / "500" / "png" / "plain"
        target.mkdir(parents=True)
        (target / "00001000_plain_500_11.png").write_bytes(make_png())
        hashes.append(
            IdentityImagePreparer().prepare(record(), root, PROFILE).preparation_hash
        )
    assert hashes[0] == hashes[1]


@pytest.mark.parametrize(
    "change",
    [
        {"effective_ppi": 1000},
        {"expected_sha256": sha256_of("something else")},
        {"checksum_status": ChecksumStatus.VERIFIED},
        {"image_id": "sd300a_00001000_plain_f02"},
    ],
)
def test_preparation_hash_tracks_what_the_adapter_will_receive(dataset_root, change):
    preparer = IdentityImagePreparer()
    base = preparer.prepare(record(), dataset_root, PROFILE).preparation_hash
    changed = preparer.prepare(record(**change), dataset_root, PROFILE)
    assert changed.preparation_hash != base


def test_preparer_id_matches_the_default_profile():
    assert IdentityImagePreparer().preparer_id == PROFILE.preparer_id
