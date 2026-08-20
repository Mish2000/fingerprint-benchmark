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


def _header_row(path: Path) -> list[str]:
    strings = _shared_strings(path)
    with zipfile.ZipFile(path) as archive:
        sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    for row in sheet.iter(f"{MAIN}row"):
        if row.get("r") != "1":
            continue
        headers = []
        for cell in row:
            value = cell.find(f"{MAIN}v")
            if value is None:
                continue
            headers.append(
                strings[int(value.text)] if cell.get("t") == "s" else str(value.text)
            )
        return headers
    return []


@pytest.mark.parametrize("workbook", _workbooks(), ids=lambda p: p.name)
def test_no_column_names_the_sanity_fraction_as_a_rate(workbook: Path) -> None:
    if NEGATIVE_SANITY not in workbook.stem:
        pytest.skip("ADR 0030 governs the same-subject different-finger set only")
    offending = [
        header for header in _header_row(workbook) if _RATE_NAME.search(header)
    ]
    assert not offending, (
        f"{workbook.name} heads a column {offending!r}. ADR 0030: the "
        "same-subject / different-finger sanity fraction is published as an "
        "observed count over a named population and is never labelled a rate"
    )


@pytest.mark.parametrize("workbook", _workbooks(), ids=lambda p: p.name)
def test_no_comment_states_the_sanity_fraction_as_a_rate(workbook: Path) -> None:
    if NEGATIVE_SANITY not in workbook.stem:
        pytest.skip("ADR 0030 governs the same-subject different-finger set only")
    for text in _shared_strings(workbook):
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
