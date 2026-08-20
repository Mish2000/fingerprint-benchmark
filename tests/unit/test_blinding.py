"""What an adapter can and cannot learn from the inputs it is handed.

The property under test is the one `PreparedImage` has always claimed: given two
prepared images, nothing on them says whether the comparison is mated. SD300's
`image_id` said exactly that, in plain text, and so did the filename.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from fpbench.core.enums import ChecksumStatus
from fpbench.core.execution_models import PreparedImage
from fpbench.core.identifiers import ImageId, validate_id
from fpbench.execution.blinding import BLIND_INPUT_DIRECTORY, RunBlinding

#: Two impressions of one subject's right index, and one of another subject's.
#: Written the way `fpbench.datasets.sd300.catalog` composes them.
MATED_LEFT = "sd300a_00002502_plain_right_index"
MATED_RIGHT = "sd300a_00002502_roll_right_index"
OTHER_SUBJECT = "sd300a_00009317_roll_right_index"


def _prepared(tmp_path: Path, image_id: str, payload: bytes = b"pixels") -> PreparedImage:
    path = tmp_path / f"{image_id}.png"
    path.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    return PreparedImage(
        image_id=ImageId(image_id),
        local_path=path.resolve(),
        effective_ppi=500,
        media_type="image/png",
        expected_sha256=digest,
        checksum_status=ChecksumStatus.VERIFIED,
        preparation_profile_id="identity",
        preparation_hash="0" * 64,
        prepared_sha256=digest,
        prepared_size_bytes=len(payload),
    )


def test_the_alias_carries_no_part_of_the_original_id(tmp_path: Path) -> None:
    blinding = RunBlinding()
    blinded = blinding.blind(_prepared(tmp_path, MATED_LEFT), tmp_path / "job")
    alias = str(blinded.image_id)
    for fragment in ("sd300a", "00002502", "plain", "right", "index"):
        assert fragment not in alias
    assert validate_id(alias) == alias


def test_two_impressions_of_one_finger_are_not_relatable_by_their_aliases(
    tmp_path: Path,
) -> None:
    """The whole point: an adapter cannot answer 'mated?' from the inputs.

    Before, the two ids shared the subject segment ``00002502`` and an adapter
    could read it off without doing any biometrics.
    """
    blinding = RunBlinding()
    job = tmp_path / "job"
    left = blinding.blind(_prepared(tmp_path, MATED_LEFT, b"a"), job)
    right = blinding.blind(_prepared(tmp_path, MATED_RIGHT, b"b"), job)
    other = blinding.blind(_prepared(tmp_path, OTHER_SUBJECT, b"c"), job)

    aliases = {str(image.image_id) for image in (left, right, other)}
    assert len(aliases) == 3

    # No shared substring longer than the constant ``img_`` prefix.
    stems = [str(image.image_id).removeprefix("img_") for image in (left, right)]
    assert not any(
        stems[0][index : index + 4] in stems[1] for index in range(len(stems[0]) - 3)
    ), "the mated pair's aliases share a run of characters"


def test_the_path_no_longer_names_the_subject(tmp_path: Path) -> None:
    blinding = RunBlinding()
    blinded = blinding.blind(_prepared(tmp_path, MATED_LEFT), tmp_path / "job")
    text = str(blinded.local_path)
    for fragment in ("00002502", "plain", "right_index"):
        assert fragment not in text
    assert BLIND_INPUT_DIRECTORY in blinded.local_path.parts


def test_the_alias_is_stable_within_a_run(tmp_path: Path) -> None:
    """A SELF pair is one image twice, and an adapter may cache by identity."""
    blinding = RunBlinding()
    job = tmp_path / "job"
    first = blinding.blind(_prepared(tmp_path, MATED_LEFT), job)
    second = blinding.blind(_prepared(tmp_path, MATED_LEFT), job)
    assert first.image_id == second.image_id


def test_aliases_do_not_carry_across_runs(tmp_path: Path) -> None:
    """Two runs' logs must not be joinable on an alias."""
    first = RunBlinding().blind(_prepared(tmp_path, MATED_LEFT), tmp_path / "a")
    second = RunBlinding().blind(_prepared(tmp_path, MATED_LEFT), tmp_path / "b")
    assert first.image_id != second.image_id


def test_the_alias_does_not_reveal_the_order_images_were_seen(
    tmp_path: Path,
) -> None:
    """A counter would have made the first image of the first pair ``img_1``."""
    blinding = RunBlinding(secret=b"pinned-for-this-test")
    job = tmp_path / "job"
    first = blinding.blind(_prepared(tmp_path, MATED_LEFT), job)

    reordered = RunBlinding(secret=b"pinned-for-this-test")
    reordered.blind(_prepared(tmp_path, OTHER_SUBJECT), job)
    later = reordered.blind(_prepared(tmp_path, MATED_LEFT), job)

    assert first.image_id == later.image_id


def test_the_bytes_the_adapter_opens_are_the_prepared_bytes(tmp_path: Path) -> None:
    """Blinding must not disturb the digest checks the NBIS input path performs."""
    prepared = _prepared(tmp_path, MATED_LEFT, b"exactly these pixels")
    blinded = RunBlinding().blind(prepared, tmp_path / "job")
    payload = blinded.local_path.read_bytes()
    assert payload == b"exactly these pixels"
    assert hashlib.sha256(payload).hexdigest() == blinded.prepared_sha256


def test_every_other_field_survives_untouched(tmp_path: Path) -> None:
    prepared = _prepared(tmp_path, MATED_LEFT)
    blinded = RunBlinding().blind(prepared, tmp_path / "job")
    for field in (
        "effective_ppi",
        "media_type",
        "expected_sha256",
        "checksum_status",
        "preparation_profile_id",
        "preparation_hash",
        "prepared_sha256",
        "prepared_size_bytes",
    ):
        assert getattr(blinded, field) == getattr(prepared, field), field


def test_a_missing_source_is_left_for_the_adapter_to_report(tmp_path: Path) -> None:
    """Blinding must not change which failure code a missing input produces."""
    prepared = _prepared(tmp_path, MATED_LEFT)
    prepared.local_path.unlink()
    blinded = RunBlinding().blind(prepared, tmp_path / "job")
    assert not blinded.local_path.exists()


def test_the_artefact_is_refreshed_per_job_so_drift_stays_visible(
    tmp_path: Path,
) -> None:
    """A link cached for the whole run would pin the old inode (ADR 0033)."""
    prepared = _prepared(tmp_path, MATED_LEFT, b"original")
    blinding = RunBlinding()
    job = tmp_path / "job"
    blinding.blind(prepared, job)

    prepared.local_path.unlink()
    prepared.local_path.write_bytes(b"replaced under the run")

    again = blinding.blind(prepared, job)
    assert again.local_path.read_bytes() == b"replaced under the run"
