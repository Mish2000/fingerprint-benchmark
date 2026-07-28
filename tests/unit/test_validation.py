from __future__ import annotations

from pathlib import Path

import pytest

from fpbench.datasets.base import Severity
from fpbench.datasets.sd300.filenames import parse_filename
from fpbench.datasets.sd300.validation import (
    IssueCode,
    PngHeaderError,
    metres_to_ppi,
    read_png_header,
    validate_file,
)
from support import make_png


def _write(tmp_path: Path, name: str, **kwargs) -> Path:
    path = tmp_path / name
    path.write_bytes(make_png(**kwargs))
    return path


def test_reads_dimensions_and_resolution(tmp_path):
    header = read_png_header(_write(tmp_path, "a.png", width=64, height=32, ppi=1000))
    assert (header.width, header.height) == (64, 32)
    assert header.ppi == 1000


def test_missing_phys_chunk_yields_no_resolution(tmp_path):
    header = read_png_header(_write(tmp_path, "a.png", ppi=None))
    assert header.ppi is None


def test_rejects_a_non_png(tmp_path):
    path = tmp_path / "a.png"
    path.write_bytes(b"not a png at all")
    with pytest.raises(PngHeaderError):
        read_png_header(path)


def test_phys_conversion_matches_the_values_seen_in_sd300():
    assert metres_to_ppi(19685) == 500
    assert metres_to_ppi(39370) == 1000
    assert metres_to_ppi(78740) == 2000
    assert metres_to_ppi(200000) == 5080


def _codes(issues):
    return {issue.code for issue in issues}


def test_a_clean_file_produces_no_findings(tmp_path):
    header = read_png_header(_write(tmp_path, "a.png", ppi=500))
    issues = validate_file(
        release="SD300A",
        relative_path="a.png",
        parsed=parse_filename("00001000_plain_500_11.png"),
        header=header,
    )
    assert issues == ()


def test_the_sd300c_defect_is_a_warning_not_an_error(tmp_path):
    header = read_png_header(_write(tmp_path, "a.png", ppi=5080))
    issues = validate_file(
        release="SD300C",
        relative_path="a.png",
        parsed=parse_filename("00001000_roll_2000_01.png"),
        header=header,
    )
    assert _codes(issues) == {IssueCode.METADATA_PPI_ANOMALY}
    assert all(issue.severity is Severity.WARNING for issue in issues)


def test_an_undocumented_resolution_is_an_error(tmp_path):
    header = read_png_header(_write(tmp_path, "a.png", ppi=1200))
    issues = validate_file(
        release="SD300C",
        relative_path="a.png",
        parsed=parse_filename("00001000_roll_2000_01.png"),
        header=header,
    )
    assert _codes(issues) == {IssueCode.UNEXPECTED_METADATA_PPI}
    assert all(issue.severity is Severity.ERROR for issue in issues)


def test_a_filename_from_the_wrong_release_is_an_error():
    issues = validate_file(
        release="SD300A",
        relative_path="a.png",
        parsed=parse_filename("00001000_plain_1000_11.png"),
    )
    assert _codes(issues) == {IssueCode.FILENAME_PPI_MISMATCH}


def test_an_unparseable_name_stops_further_checks():
    issues = validate_file(release="SD300A", relative_path="x.csv", parsed=None)
    assert _codes(issues) == {IssueCode.FILENAME_UNPARSEABLE}


def test_header_checks_are_skipped_when_no_header_is_supplied():
    issues = validate_file(
        release="SD300C",
        relative_path="a.png",
        parsed=parse_filename("00001000_roll_2000_01.png"),
    )
    assert issues == ()
