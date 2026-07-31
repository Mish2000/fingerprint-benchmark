"""Source paths are delivery-owned regular files, never followed links."""

from __future__ import annotations

import pytest

from fpbench.core.errors import ImagingError
from fpbench.imaging.source_records import resolve_source_path
from fakes import image_record


def _record(relative_path: str):
    return image_record(
        image_id="sd300a_00001000_plain_f01",
        relative_path=relative_path,
        expected_sha256="0" * 64,
    )


def _symlink(link, target, *, directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except OSError:
        pytest.skip("this platform does not allow creating symlinks here")


def test_regular_source_file_is_accepted(tmp_path):
    root = tmp_path / "dataset"
    path = root / "release" / "image.png"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"source")

    assert resolve_source_path(_record("release/image.png"), root) == path.resolve()


def test_final_component_symlink_to_in_root_file_is_rejected(tmp_path):
    root = tmp_path / "dataset"
    root.mkdir()
    target = root / "owned.png"
    target.write_bytes(b"source")
    link = root / "linked.png"
    _symlink(link, target)

    with pytest.raises(ImagingError, match="symlink"):
        resolve_source_path(_record("linked.png"), root)


def test_final_component_symlink_outside_root_is_rejected(tmp_path):
    root = tmp_path / "dataset"
    root.mkdir()
    target = tmp_path / "outside.png"
    target.write_bytes(b"source")
    link = root / "linked.png"
    _symlink(link, target)

    with pytest.raises(ImagingError, match="symlink"):
        resolve_source_path(_record("linked.png"), root)


def test_intermediate_directory_symlink_is_rejected(tmp_path):
    root = tmp_path / "dataset"
    real = root / "real"
    real.mkdir(parents=True)
    (real / "image.png").write_bytes(b"source")
    link = root / "linked-directory"
    _symlink(link, real, directory=True)

    with pytest.raises(ImagingError, match="symlink"):
        resolve_source_path(_record("linked-directory/image.png"), root)
