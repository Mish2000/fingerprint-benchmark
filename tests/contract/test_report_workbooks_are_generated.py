"""The workbooks are derived from the evidence, not authored beside it.

They were hand-made, and the hand-made version headed a column ``FAR`` over the
same-subject different-finger set — the one thing ADR 0030 spends a page saying
that fraction may never be called. Nothing caught it because nothing produced
it: the spreadsheet was a fourth description of the runs, kept in step with the
other three by memory.

These tests check the property that makes the ADR enforceable at all: every
number in the workbooks comes from a published metric set or marker, so
regenerating them is a no-op and a drift is a diff.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from fpbench.experiments.report_workbooks import (
    MATCHED_WORKBOOK,
    NON_MATCHED_WORKBOOK,
    RELEASES,
    SANITY_COLUMN_HEADING,
    build_matched_rows,
    build_non_matched_rows,
    write_workbooks,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
OUTPUTS = REPOSITORY_ROOT / "outputs"


def test_both_workbooks_are_present() -> None:
    for name in (MATCHED_WORKBOOK, NON_MATCHED_WORKBOOK):
        assert (OUTPUTS / name).is_file(), (
            f"{name} is missing. Run `make report-workbooks`; it is generated, "
            "not stored by hand"
        )


@pytest.mark.parametrize("name", [MATCHED_WORKBOOK, NON_MATCHED_WORKBOOK])
def test_the_committed_workbook_regenerates_byte_for_byte(
    name: str, tmp_path: Path
) -> None:
    """The property the ADR check rests on.

    If regenerating produced different bytes, the workbook in ``outputs/`` would
    be somebody's edit rather than the evidence's rendering, and checking the
    rendering would prove nothing about the file a supervisor opens.
    """
    fresh = write_workbooks(outputs=tmp_path)[name]
    assert fresh.read_bytes() == (OUTPUTS / name).read_bytes(), (
        f"{name} in outputs/ is not what the evidence renders to. Either it was "
        "edited by hand, or the evidence moved and it was not regenerated"
    )


def test_every_row_traces_to_a_published_source() -> None:
    """Fifteen rows: five algorithms over three releases, and nothing invented."""
    for rows in (build_non_matched_rows(), build_matched_rows()):
        assert len(rows) == 15
        assert {row.release for row in rows} == set(RELEASES)
        assert len({row.system_name for row in rows}) == 5
        assert [row.ordinal for row in rows] == list(range(1, 16))


def test_the_sanity_column_is_a_count_and_says_so() -> None:
    """ADR 0030's enforcement point in this artefact."""
    assert "not a rate" in SANITY_COLUMN_HEADING
    assert "FAR" not in SANITY_COLUMN_HEADING
    assert "FMR" not in SANITY_COLUMN_HEADING

    for row in build_non_matched_rows():
        if row.far == "N/A":
            continue
        # A count, so it parses as a whole number of comparisons — never 0.002.
        assert row.far.isdigit(), f"{row.system_name} {row.release}: {row.far!r}"
        assert 0 <= int(row.far) <= int(row.attempts)


def test_the_sanity_counts_are_the_published_ones() -> None:
    """Read straight out of the metric set, not recomputed here."""
    metrics = json.loads(
        (
            REPOSITORY_ROOT
            / "evidence"
            / "sourceafis-canonical500-evaluation"
            / "metricset_b4c70fbfd1d3.json"
        ).read_text(encoding="utf-8")
    )["metrics"]["plain_roll_non_mated_sanity_match_rate_attempt"]

    rows = {
        (row.system_name, row.release): row
        for row in build_non_matched_rows()
        if row.system_name.startswith("SourceAFIS")
    }
    for release in RELEASES:
        row = rows[("SourceAFIS for Java 3.18.1", release)]
        assert row.far == str(metrics[release]["numerator"])
        assert row.attempts == str(metrics[release]["denominator"])


def test_a_route_with_no_decisions_reports_none() -> None:
    """Three of the five produced scores and no decision; none may show a rate."""
    for row in build_non_matched_rows() + build_matched_rows():
        if row.system_name.startswith(("SourceAFIS", "NBIS MINDTCT + BOZORTH3")):
            continue
        assert row.decisions == "N/A"
        assert row.far == "N/A"
        assert row.frr == "N/A"


@pytest.mark.parametrize("name", [MATCHED_WORKBOOK, NON_MATCHED_WORKBOOK])
def test_the_workbook_is_a_readable_archive(name: str) -> None:
    with zipfile.ZipFile(OUTPUTS / name) as archive:
        assert archive.testzip() is None
        assert "xl/worksheets/sheet1.xml" in archive.namelist()


# ------------------------------------------------- the header must be readable


def _header_row_xml(path: Path) -> str:
    import re
    import zipfile

    with zipfile.ZipFile(path) as archive:
        sheet = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
    match = re.search(r'<row r="1"[^>]*>', sheet)
    assert match, f"{path.name} has no header row"
    return match.group(0)


@pytest.mark.parametrize("name", [MATCHED_WORKBOOK, NON_MATCHED_WORKBOOK])
def test_the_header_row_is_tall_enough_for_the_header_it_holds(name: str) -> None:
    """A fixed height clipped the longest heading.

    The first styled version set ``ht="42"`` for every sheet — two and a half
    lines of 11pt text. ``NonMatchedV1``'s sanity column heading is two
    sentences in a twenty-character column and wraps to five lines, so the one
    heading a reader most needs to see was the one cut off. The height is
    measured from the content now.
    """
    from fpbench.experiments.report_workbooks import (
        _MATCHED_COLUMNS,
        _MATCHED_HEADERS,
        _NON_MATCHED_COLUMNS,
        _NON_MATCHED_HEADERS,
    )
    from fpbench.experiments.xlsx_writer import _header_height

    headers, columns = (
        (_MATCHED_HEADERS, _MATCHED_COLUMNS)
        if name == MATCHED_WORKBOOK
        else (_NON_MATCHED_HEADERS, _NON_MATCHED_COLUMNS)
    )
    needed = _header_height(list(headers), columns)
    row = _header_row_xml(OUTPUTS / name)
    stored = float(row.split('ht="', 1)[1].split('"', 1)[0])
    assert stored >= needed, (
        f"{name} gives its header {stored} points and the widest heading needs "
        f"{needed}. The heading is clipped in every viewer"
    )
    assert 'customHeight="1"' in row


def test_the_measured_height_grows_with_the_heading() -> None:
    """The measurement is a measurement, not a bigger constant."""
    from fpbench.experiments.xlsx_writer import Column, _header_height, _wrapped_lines

    narrow = (Column(width=12),)
    assert _wrapped_lines("Release", 12) == 1
    assert _wrapped_lines("Matching decisions in the negative sanity set", 12) > 3
    short = _header_height(["Release"], narrow)
    long = _header_height(["Matching decisions in the negative sanity set"], narrow)
    assert long > short


def test_an_explicit_line_break_takes_a_line_of_its_own() -> None:
    """Two of the headings carry a parenthetical on its own line."""
    from fpbench.experiments.xlsx_writer import _wrapped_lines

    assert _wrapped_lines("FAR\n(Not applicable)", 40) == 2
    assert _wrapped_lines("FAR (Not applicable)", 40) == 1
