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
