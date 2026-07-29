"""Reading NIST's digest manifests.

Regression coverage for a delivery quirk: SD300A and SD300C label the file-name
column ``filename``, SD300B labels it ``name``. A reader that knows only one
spelling finds no digests at all for the other release, and because an image
with no official digest is refused, the whole 1000 ppi release disappears from
the study without any obvious error.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fpbench.core.enums import Impression
from fpbench.core.errors import DatasetLayoutError
from fpbench.datasets.sd300.checksums import checksum_filename, load_checksums
from fakes import sha256_of

DIGEST = sha256_of("image bytes")


def write_csv(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "checksum_500_png_plain.csv"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize("column", ["filename", "name"])
def test_both_header_spellings_are_accepted(tmp_path, column):
    path = write_csv(tmp_path, f"sha256,{column}\n{DIGEST},00001000_plain_500_11.png\n")
    assert load_checksums(path) == {"00001000_plain_500_11.png": DIGEST}


def test_digests_are_lowercased(tmp_path):
    path = write_csv(
        tmp_path, f"sha256,filename\n{DIGEST.upper()},00001000_plain_500_11.png\n"
    )
    assert load_checksums(path)["00001000_plain_500_11.png"] == DIGEST


def test_an_unrecognised_header_is_rejected(tmp_path):
    path = write_csv(tmp_path, f"sha256,file\n{DIGEST},a.png\n")
    with pytest.raises(DatasetLayoutError, match="expected a 'sha256' column"):
        load_checksums(path)


def test_a_missing_digest_column_is_rejected(tmp_path):
    path = write_csv(tmp_path, "checksum,filename\nabc,a.png\n")
    with pytest.raises(DatasetLayoutError):
        load_checksums(path)


def test_a_malformed_digest_is_rejected(tmp_path):
    path = write_csv(tmp_path, "sha256,filename\nnot-a-digest,a.png\n")
    with pytest.raises(DatasetLayoutError, match="invalid checksum row"):
        load_checksums(path)


def test_a_duplicate_entry_is_rejected(tmp_path):
    path = write_csv(
        tmp_path, f"sha256,filename\n{DIGEST},a.png\n{DIGEST},a.png\n"
    )
    with pytest.raises(DatasetLayoutError, match="duplicate"):
        load_checksums(path)


def test_a_missing_manifest_is_reported_clearly(tmp_path):
    with pytest.raises(DatasetLayoutError, match="not found"):
        load_checksums(tmp_path / "absent.csv")


def test_the_manifest_name_follows_the_nist_convention():
    assert checksum_filename(1000, Impression.ROLL) == "checksum_1000_png_roll.csv"
