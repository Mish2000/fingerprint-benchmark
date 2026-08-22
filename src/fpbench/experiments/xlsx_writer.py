"""Writing one sheet as a real ``.xlsx``, with no new dependency.

``openpyxl`` is not in this project's dependency set, and adding it to write two
tables of fifteen rows would be the largest supply-chain decision in the
repository taken for the smallest reason — in a project whose whole Stage 8E is
about accounting for third-party bytes.

An ``.xlsx`` is a zip of a handful of XML parts, and what follows is the subset
a readable one-sheet workbook needs.

**Numbers are numbers.** The first version stored all 128 cells as inline
strings, which is what a spreadsheet does when it has given up: a column of
counts could not be summed, a rate could not be formatted, and Excel decorates
each one with a green triangle asking whether you meant a number. A cell whose
value parses as a number is written as one, with the percentage-shaped ones
carrying a percentage format so ``0.352`` reads as ``35.20%``.

**The layout is legible.** Column widths are computed from the content, headers
wrap and are bold, the header row freezes, and the long comment column wraps at
a fixed width instead of spilling across twenty columns. None of that changes a
value; all of it changes whether a supervisor can read the file without
reformatting it first.

Determinism still matters: fixed member timestamps and a fixed part order, so
regenerating an unchanged workbook produces identical bytes.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
from xml.sax.saxutils import escape

from fpbench.core.atomic_write import replace_file

__all__ = ["Column", "write_sheet", "sheet_xml"]

#: A fixed DOS timestamp for every member, so two runs over the same content
#: produce the same archive. 1980-01-01, the earliest a zip can express.
_FIXED_TIME = (1980, 1, 1, 0, 0, 0)

#: What counts as a number. Deliberately strict: ``N/A`` is text, ``500`` is a
#: count, ``0.3520`` is a rate. A value that merely starts with a digit — a pair
#: id, a version — stays text.
_NUMERIC = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")

#: Style indices, in the order they are declared in ``styles.xml`` below.
_STYLE_TEXT = 0
_STYLE_HEADER = 1
_STYLE_WRAPPED = 2
_STYLE_NUMBER = 3
_STYLE_RATE = 4


@dataclass(frozen=True, slots=True)
class Column:
    """One column's presentation. Width is in Excel's character units."""

    width: float
    #: Long prose that must wrap in place rather than run across the sheet.
    wrap: bool = False
    #: Render numeric cells as a percentage rather than a bare decimal.
    rate: bool = False


_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>"""

_ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

_WORKBOOK = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets><sheet name="results" sheetId="1" r:id="rId1"/></sheets>
</workbook>"""

_WORKBOOK_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

#: Five cell formats. ``numFmtId="10"`` is Excel's built-in ``0.00%``.
_STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<fonts count="2">
<font><sz val="11"/><name val="Calibri"/></font>
<font><b/><sz val="11"/><name val="Calibri"/></font>
</fonts>
<fills count="3">
<fill><patternFill patternType="none"/></fill>
<fill><patternFill patternType="gray125"/></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFEFEFEF"/><bgColor indexed="64"/></patternFill></fill>
</fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="5">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="top"/></xf>
<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="top" horizontal="right"/></xf>
<xf numFmtId="10" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyAlignment="1"><alignment vertical="top" horizontal="right"/></xf>
</cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""


def _column_name(index: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    name = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(ord("A") + remainder) + name
    return name


def _columns_xml(columns: Sequence[Column]) -> str:
    if not columns:
        return ""
    entries = "".join(
        f'<col min="{index + 1}" max="{index + 1}" '
        f'width="{column.width:.2f}" customWidth="1"/>'
        for index, column in enumerate(columns)
    )
    return f"<cols>{entries}</cols>"


def _cell_xml(reference: str, value: str, column: Column | None, header: bool) -> str:
    text = str(value)
    if header:
        return (
            f'<c r="{reference}" s="{_STYLE_HEADER}" t="inlineStr">'
            f'<is><t xml:space="preserve">{escape(text)}</t></is></c>'
        )
    if _NUMERIC.match(text):
        style = _STYLE_RATE if column is not None and column.rate else _STYLE_NUMBER
        return f'<c r="{reference}" s="{style}"><v>{text}</v></c>'
    style = _STYLE_WRAPPED if column is not None and column.wrap else _STYLE_TEXT
    return (
        f'<c r="{reference}" s="{style}" t="inlineStr">'
        f'<is><t xml:space="preserve">{escape(text)}</t></is></c>'
    )


def sheet_xml(
    rows: Sequence[Sequence[str]], columns: Sequence[Column] = ()
) -> str:
    """One worksheet part.

    Inline strings rather than a shared-string table: a shared table is a second
    place the text lives, and the bug this module exists downstream of was a
    workbook whose header said one thing and whose cells said another.
    """
    parts = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
        # The header stays on screen while a reader scrolls fifteen rows of
        # comments; without it the columns are unidentifiable after row 3.
        '<sheetViews><sheetView workbookViewId="0">'
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        "</sheetView></sheetViews>",
        _columns_xml(columns),
        "<sheetData>",
    ]
    for row_index, row in enumerate(rows, start=1):
        header = row_index == 1
        # Header rows carry two lines of text; give them the room.
        height = ' ht="42" customHeight="1"' if header else ""
        parts.append(f'<row r="{row_index}"{height}>')
        for column_index, value in enumerate(row):
            reference = f"{_column_name(column_index)}{row_index}"
            column = columns[column_index] if column_index < len(columns) else None
            parts.append(_cell_xml(reference, value, column, header))
        parts.append("</row>")
    parts.append("</sheetData></worksheet>")
    return "".join(parts)


def write_sheet(
    path: Path, rows: Sequence[Sequence[str]], columns: Sequence[Column] = ()
) -> Path:
    """Write ``rows`` to ``path`` as a single-sheet xlsx, atomically."""
    members = (
        ("[Content_Types].xml", _CONTENT_TYPES),
        ("_rels/.rels", _ROOT_RELS),
        ("xl/workbook.xml", _WORKBOOK),
        ("xl/_rels/workbook.xml.rels", _WORKBOOK_RELS),
        ("xl/styles.xml", _STYLES),
        ("xl/worksheets/sheet1.xml", sheet_xml(rows, columns)),
    )

    def _write(temporary: Path) -> None:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, payload in members:
                info = zipfile.ZipInfo(name, date_time=_FIXED_TIME)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                archive.writestr(info, payload.encode("utf-8"))

    return replace_file(Path(path), _write, what="workbook")
