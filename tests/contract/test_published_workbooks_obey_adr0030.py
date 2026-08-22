"""The workbooks in ``outputs/`` are published results, and ADR 0030 binds them.

ADR 0030 names four enforcement points — metric ids, definitions, prose and
configuration — and the workbooks were outside all four. ``NonMatchedV1``
shipped a column headed ``FAR`` holding ``0`` and ``0.002``, with comments
reading ``0/500 = 0%``. Every one of those is the ADR's stated failure mode:
"the false-match rate was zero" states a probability no finite sample supports,
over a closed same-subject single-pairing set that was never designed for
estimation.

**This does not grep for ``FAR``.** ADR 0030 is explicit that a blunt substring
assertion is the wrong test, because the documents are *supposed* to be able to
say "this is not a general false-match rate" — and a test that forbids the
letters would push that sentence out of the file to stay green. What is checked
instead is the same thing the metric-id rule checks: the sanity fraction may not
be *named* as a rate, and may not be *valued* as one.

The workbooks are hand-authored, so this is the only thing standing between the
ADR and the deliverable a reader actually opens.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
OUTPUTS = REPOSITORY_ROOT / "outputs"
MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

#: The negative-sanity workbook. The mated workbook is a different population,
#: where FRR is a legitimate rate and ADR 0030 does not apply.
NEGATIVE_SANITY = "NonMatchedV1"

#: A column header that names the sanity fraction as a rate. ``FRR`` is allowed
#: through: the sheet carries it as "not applicable to pairs of different
#: fingers", which is a statement that no such rate exists here.
_RATE_NAME = re.compile(
    r"(?<![A-Za-z])(FAR|FMR|false[- ]match rate|false[- ]accept(?:ance)? rate)"
    r"(?![A-Za-z])",
    re.IGNORECASE,
)

#: The assertion forms ADR 0030 names, rather than the bare word.
_RATE_ASSERTION = re.compile(
    r"(?:FAR|FMR|false[- ]match rate|false[- ]accept(?:ance)? rate)\s*"
    r"(?:=|:|\bwas\b|\bis\b)\s*"
    r"(?:[0-9]|zero)",
    re.IGNORECASE,
)

#: ``0/500 = 0%`` — a count presented as a percentage is a rate whatever the
#: column is called.
_FRACTION_AS_PERCENT = re.compile(r"\d+\s*/\s*\d+\s*=\s*[\d.]+\s*%")


def _workbooks() -> list[Path]:
    if not OUTPUTS.is_dir():
        return []
    return sorted(
        path
        for path in OUTPUTS.iterdir()
        if path.suffix in {".xlsx", ".xlsm"} and not path.name.startswith("~$")
    )


def _shared_strings(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        if "xl/sharedStrings.xml" not in archive.namelist():
            return []
        root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return [
        "".join(node.text or "" for node in item.iter(f"{MAIN}t"))
        for item in root.findall(f"{MAIN}si")
    ]


def _cell_text(cell: ET.Element, strings: list[str]) -> str | None:
    """One cell's text, however the workbook chose to store it.

    Three storage forms, and reading only the first is how this test came to
    pass over an empty header row: a shared-string index, an inline string, or a
    plain value. A checker that silently sees nothing reports no violation,
    which is indistinguishable from a clean workbook.
    """
    if cell.get("t") == "inlineStr":
        node = cell.find(f"{MAIN}is")
        if node is None:
            return None
        return "".join(part.text or "" for part in node.iter(f"{MAIN}t"))
    value = cell.find(f"{MAIN}v")
    if value is None or value.text is None:
        return None
    if cell.get("t") == "s":
        return strings[int(value.text)]
    return str(value.text)


def _all_text(path: Path) -> list[str]:
    """Every string in the sheet, whichever form it is stored in."""
    strings = _shared_strings(path)
    with zipfile.ZipFile(path) as archive:
        sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    texts = [
        text
        for row in sheet.iter(f"{MAIN}row")
        for cell in row
        if (text := _cell_text(cell, strings)) is not None
    ]
    return texts + strings


def _header_row(path: Path) -> list[str]:
    strings = _shared_strings(path)
    with zipfile.ZipFile(path) as archive:
        sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    for row in sheet.iter(f"{MAIN}row"):
        if row.get("r") != "1":
            continue
        headers = [
            text for cell in row if (text := _cell_text(cell, strings)) is not None
        ]
        return headers
    return []


@pytest.mark.parametrize("workbook", _workbooks(), ids=lambda p: p.name)
def test_no_column_names_the_sanity_fraction_as_a_rate(workbook: Path) -> None:
    if NEGATIVE_SANITY not in workbook.stem:
        pytest.skip("ADR 0030 governs the same-subject different-finger set only")
    headers = _header_row(workbook)
    assert headers, (
        f"{workbook.name} yielded no header row. That is a fault in this "
        "reader, not a clean workbook — an empty scan finds no violation"
    )
    offending = [header for header in headers if _RATE_NAME.search(header)]
    assert not offending, (
        f"{workbook.name} heads a column {offending!r}. ADR 0030: the "
        "same-subject / different-finger sanity fraction is published as an "
        "observed count over a named population and is never labelled a rate"
    )


@pytest.mark.parametrize("workbook", _workbooks(), ids=lambda p: p.name)
def test_no_comment_states_the_sanity_fraction_as_a_rate(workbook: Path) -> None:
    if NEGATIVE_SANITY not in workbook.stem:
        pytest.skip("ADR 0030 governs the same-subject different-finger set only")
    for text in _all_text(workbook):
        assertion = _RATE_ASSERTION.search(text)
        assert assertion is None, (
            f"{workbook.name} states {assertion.group(0)!r}: "
            f"{text[:120]!r}. ADR 0030 forbids the assertion forms, not the "
            "words — the document may say it is *not* a general false-match rate"
        )
        percentage = _FRACTION_AS_PERCENT.search(text)
        assert percentage is None, (
            f"{workbook.name} renders the sanity count as a percentage "
            f"({percentage.group(0)!r}). A count over a named population is the "
            "published form; the percentage is the rate ADR 0030 refuses"
        )


# --------------------------------------------------------- the formatted form

#: Excel's built-in percentage formats: ``0%`` and ``0.00%``. A custom format is
#: caught by its format code instead.
_BUILT_IN_PERCENT = frozenset({9, 10})


def _percentage_styles(path: Path) -> frozenset[int]:
    """Which cell-style indices render their value as a percentage."""
    with zipfile.ZipFile(path) as archive:
        if "xl/styles.xml" not in archive.namelist():
            return frozenset()
        root = ET.fromstring(archive.read("xl/styles.xml"))
    custom = {
        int(node.get("numFmtId", "0"))
        for node in root.iter(f"{MAIN}numFmt")
        if "%" in (node.get("formatCode") or "")
    }
    percentage = _BUILT_IN_PERCENT | custom
    formats = root.find(f"{MAIN}cellXfs")
    if formats is None:
        return frozenset()
    return frozenset(
        index
        for index, xf in enumerate(formats.findall(f"{MAIN}xf"))
        if int(xf.get("numFmtId", "0")) in percentage
    )


@pytest.mark.parametrize("workbook", _workbooks(), ids=lambda p: p.name)
def test_no_cell_is_formatted_as_a_percentage(workbook: Path) -> None:
    """The prohibition survives the move from text to typed cells.

    The workbooks used to store all 128 cells as text, where a percentage could
    only arrive as the characters ``0%`` — which the comment test above catches.
    Now that counts are stored as numbers, a second route opened: the *same*
    stored ``0`` renders as ``0.00%`` if the cell carries a percentage format,
    and no string in the file records that it happened. One column specification
    in ``report_workbooks`` is all it would take.
    """
    if NEGATIVE_SANITY not in workbook.stem:
        pytest.skip("ADR 0030 governs the same-subject different-finger set only")
    percentage = _percentage_styles(workbook)
    with zipfile.ZipFile(workbook) as archive:
        sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    offending = [
        cell.get("r")
        for row in sheet.iter(f"{MAIN}row")
        for cell in row
        if int(cell.get("s") or "0") in percentage
    ]
    assert not offending, (
        f"{workbook.name} formats {offending!r} as a percentage. ADR 0030: the "
        "sanity fraction is published as a count over a named population — "
        "presenting the same number as a rate is the thing the ADR refuses, "
        "and a number format does it without changing a single character"
    )


@pytest.mark.parametrize("workbook", _workbooks(), ids=lambda p: p.name)
def test_counts_are_stored_as_numbers(workbook: Path) -> None:
    """The counts a supervisor is asked to check must be checkable.

    Not an ADR 0030 rule, but the reason the typed cells exist: a column of
    counts stored as text cannot be summed or sorted, and Excel flags every one
    of them. Both workbooks are covered — this is about the deliverable, not
    about the negative-sanity population.
    """
    with zipfile.ZipFile(workbook) as archive:
        sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    ordinals = [
        cell
        for row in sheet.iter(f"{MAIN}row")
        if row.get("r") != "1"
        for cell in row
        if (cell.get("r") or "").startswith("A")
    ]
    assert ordinals, f"{workbook.name} has no data rows to check"
    text_typed = [cell.get("r") for cell in ordinals if cell.get("t") is not None]
    assert not text_typed, (
        f"{workbook.name} stores the process numbers {text_typed!r} as text. "
        "A count is a number; storing it as a string is what the first, "
        "hand-authored workbooks did"
    )
