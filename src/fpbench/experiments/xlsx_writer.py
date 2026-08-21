"""Writing one sheet of text as a real ``.xlsx``, with no new dependency.

``openpyxl`` is not in this project's dependency set and adding it to write two
tables of fifteen rows would be the largest supply-chain decision in the
repository taken for the smallest reason — in a project whose whole Stage 8E is
about accounting for third-party bytes.

An ``.xlsx`` is a zip of a handful of XML parts. Everything below is one sheet
of inline strings, which Excel, LibreOffice and every reader this project has
been opened in accept. Deliberately absent: styles, formulas, numeric types,
merged cells, charts. The workbook is a table of text a supervisor reads, and a
value stored as text cannot be silently reinterpreted by a locale.

Determinism matters here. The archive is written with fixed timestamps and in a
fixed part order, so regenerating an unchanged workbook produces identical bytes
and a diff shows a content change or nothing at all.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Sequence
from xml.sax.saxutils import escape

from fpbench.core.atomic_write import replace_file

__all__ = ["write_sheet", "sheet_xml"]

#: A fixed DOS timestamp for every member, so two runs over the same content
#: produce the same archive. 1980-01-01, the earliest a zip can express.
_FIXED_TIME = (1980, 1, 1, 0, 0, 0)

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
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
</Relationships>"""


def _column(index: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    name = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(ord("A") + remainder) + name
    return name


def sheet_xml(rows: Sequence[Sequence[str]]) -> str:
    """One worksheet part, every cell an inline string.

    Inline rather than shared strings on purpose: a shared-string table is a
    second place the text lives, and the bug this whole module exists to stop
    was a workbook whose header said one thing and whose cells said another.
    """
    parts = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
        "<sheetData>",
    ]
    for row_index, row in enumerate(rows, start=1):
        parts.append(f'<row r="{row_index}">')
        for column_index, value in enumerate(row):
            reference = f"{_column(column_index)}{row_index}"
            text = escape(str(value))
            parts.append(
                f'<c r="{reference}" t="inlineStr">'
                f'<is><t xml:space="preserve">{text}</t></is></c>'
            )
        parts.append("</row>")
    parts.append("</sheetData></worksheet>")
    return "".join(parts)


def write_sheet(path: Path, rows: Sequence[Sequence[str]]) -> Path:
    """Write ``rows`` to ``path`` as a single-sheet xlsx, atomically."""
    members = (
        ("[Content_Types].xml", _CONTENT_TYPES),
        ("_rels/.rels", _ROOT_RELS),
        ("xl/workbook.xml", _WORKBOOK),
        ("xl/_rels/workbook.xml.rels", _WORKBOOK_RELS),
        ("xl/worksheets/sheet1.xml", sheet_xml(rows)),
    )

    def _write(temporary: Path) -> None:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, payload in members:
                info = zipfile.ZipInfo(name, date_time=_FIXED_TIME)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                archive.writestr(info, payload.encode("utf-8"))

    return replace_file(Path(path), _write, what="workbook")
