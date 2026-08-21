"""Building the two supervisor workbooks from the published evidence.

They used to be authored by hand, and it showed. ``NonMatchedV1`` headed a
column ``FAR``, filled it with ``0`` and ``0.002``, and wrote the cells up as
``0/500 = 0%`` — the sanity fraction published as a rate, which ADR 0030 spends
a page explaining is the one thing it may never be. Nothing checked, because
nothing produced them: the spreadsheet was a fourth description of the runs,
kept in step with the other three by memory.

So they are generated, from the same evidence a reader can verify:

* the two algorithms that have metric sets — SourceAFIS and NBIS/BOZORTH3 —
  contribute their counts from ``metricset_*.json``, numerator and denominator
  as stored, with no arithmetic performed here that is not shown;
* the three raw-only routes — flx, VeriFinger and MINDTCT+MCC — contribute the
  fact that they produced no decision, taken from their own markers.

**What the negative-sanity column is.** A count of matching decisions over a
named population, never a rate, in ADR 0030's fixed wording. The mated
workbook's FRR is a different quantity over a different population and is a
legitimate rate; the ADR is about the impostor side only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from fpbench.experiments.stage18a_inputs import REPOSITORY_ROOT

__all__ = [
    "WorkbookRow",
    "MATCHED_WORKBOOK",
    "NON_MATCHED_WORKBOOK",
    "SANITY_COLUMN_HEADING",
    "build_matched_rows",
    "build_non_matched_rows",
    "write_workbooks",
]

MATCHED_WORKBOOK = "MatchedV1.xlsx"
NON_MATCHED_WORKBOOK = "NonMatchedV1.xlsx"

RELEASES = ("SD300A", "SD300B", "SD300C")

#: ADR 0030's enforcement point that this file is responsible for: the column
#: names a count over a named population. It is not "FAR", and it is not a rate.
SANITY_COLUMN_HEADING = (
    "Matching decisions in the negative sanity set\n(count out of 500; not a rate)"
)

#: ADR 0030's fixed wording, both forms.
_SANITY_ZERO = "Observed {matches}/{total} matching decisions in this sanity set."
_SANITY_NON_ZERO = (
    "Observed matches in the closed-set same-subject different-finger negative "
    "sanity check: {matches}/{total}."
)
_SANITY_CAVEAT = (
    " This set is closed, same-subject and single-pairing: finger i against "
    "finger i+1, one shift, one direction. The fraction must not be presented "
    "as a general false-match rate, and no interval can be placed on it "
    "(docs/adr/0030)."
)


@dataclass(frozen=True, slots=True)
class WorkbookRow:
    """One row: one algorithm over one release."""

    ordinal: int
    system_name: str
    release: str
    attempts: str
    decisions: str
    far: str
    frr: str
    comment: str


@dataclass(frozen=True, slots=True)
class _MetricSource:
    """An algorithm whose decisions were derived and whose metrics were published."""

    system_name: str
    metric_set: str
    profile: str


@dataclass(frozen=True, slots=True)
class _RawSource:
    """An algorithm that produced scores and no decision at all."""

    system_name: str
    marker: str
    note: str


#: Order is the order the workbooks have always used, and the order the
#: supervisor reads them in: the two decided algorithms first.
_METRIC_SOURCES: tuple[_MetricSource, ...] = (
    _MetricSource(
        "SourceAFIS for Java 3.18.1",
        "evidence/sourceafis-canonical500-evaluation/metricset_b4c70fbfd1d3.json",
        "score >= 40, transferred unchanged from the documented upstream "
        "criterion and not calibrated on this TEST cohort",
    ),
    _MetricSource(
        "NBIS MINDTCT + BOZORTH3 5.0.0",
        "evidence/nbis-canonical500-evaluation/metricset_614450282fdb.json",
        "strict score > 40 (score 40 is NON_MATCH), transferred unchanged from "
        "the documented NIST rule and not calibrated on this TEST cohort",
    ),
)

_RAW_SOURCES: tuple[_RawSource, ...] = (
    _RawSource(
        "flx DeepPrint TexMinu 512 (without localization)",
        "evidence/flx-canonical500-raw/stage-8c-finalization.json",
        "The upstream route supplies no operating point and the repository "
        "permits no decisions for this run. Calibrating on the TEST cohort is "
        "prohibited.",
    ),
    _RawSource(
        "VeriFinger 2025.2 1:1",
        "evidence/stage11b-verifinger-canonical500-raw/stage-11b-finalization.json",
        "Stage 11B adopted no threshold or decision profile and produced no "
        "metrics.",
    ),
    _RawSource(
        "NBIS MINDTCT + MCC SDK v2.0",
        "evidence/stage20b-mindtct-mcc-canonical500-raw/stage-20b-finalization.json",
        "Stage 20B produced no threshold, calibration, decision profile or "
        "metrics. This is the preferred final fifth method and uses the same "
        "certified MINDTCT 5.0.0 extractor as NBIS/BOZORTH3.",
    ),
)

_NO_DECISION = "N/A"


def _metrics(repository_root: Path, relative: str) -> Mapping[str, Mapping[str, Mapping[str, int]]]:
    payload = json.loads((Path(repository_root) / relative).read_text(encoding="utf-8"))
    return payload["metrics"]


def _marker(repository_root: Path, relative: str) -> Mapping[str, object]:
    return json.loads((Path(repository_root) / relative).read_text(encoding="utf-8"))


def _sanity_sentence(matches: int, total: int) -> str:
    template = _SANITY_ZERO if matches == 0 else _SANITY_NON_ZERO
    return template.format(matches=matches, total=total) + _SANITY_CAVEAT


def build_non_matched_rows(
    repository_root: Path = REPOSITORY_ROOT,
) -> tuple[WorkbookRow, ...]:
    """The same-subject different-finger sheet, under ADR 0030."""
    rows: list[WorkbookRow] = []
    ordinal = 1

    for source in _METRIC_SOURCES:
        metrics = _metrics(repository_root, source.metric_set)
        sanity = metrics["plain_roll_non_mated_sanity_match_rate_attempt"]
        for release in RELEASES:
            cell = sanity[release]
            matches = int(cell["numerator"])
            attempts = int(cell["denominator"])
            rows.append(
                WorkbookRow(
                    ordinal=ordinal,
                    system_name=source.system_name,
                    release=release,
                    attempts=str(attempts),
                    decisions=str(attempts - matches),
                    # A count, and the column heading says so.
                    far=str(matches),
                    frr=_NO_DECISION,
                    comment=(
                        _sanity_sentence(matches, attempts)
                        + f" Applied profile: {source.profile}."
                        " FRR is not applicable to pairs of different fingers."
                    ),
                )
            )
            ordinal += 1

    for raw in _RAW_SOURCES:
        marker = _marker(repository_root, raw.marker)
        for release in RELEASES:
            rows.append(
                WorkbookRow(
                    ordinal=ordinal,
                    system_name=raw.system_name,
                    release=release,
                    attempts="500",
                    decisions=_NO_DECISION,
                    far=_NO_DECISION,
                    frr=_NO_DECISION,
                    comment=(
                        "No benchmark decisions were produced, so the sanity "
                        f"count and FRR are both N/A. {raw.note} The protocol "
                        "uses the same-subject different-finger set. Outcome: "
                        f"{marker.get('outcome') or marker.get('kind')}."
                    ),
                )
            )
            ordinal += 1

    return tuple(rows)


def build_matched_rows(
    repository_root: Path = REPOSITORY_ROOT,
) -> tuple[WorkbookRow, ...]:
    """The same-finger PLAIN-ROLL sheet. FRR here is a rate over a mated set."""
    rows: list[WorkbookRow] = []
    ordinal = 1

    for source in _METRIC_SOURCES:
        metrics = _metrics(repository_root, source.metric_set)
        fnmr = metrics["plain_roll_mated_unconditional_fnmr_decided"]
        for release in RELEASES:
            cell = fnmr[release]
            non_matches = int(cell["numerator"])
            decided = int(cell["denominator"])
            rows.append(
                WorkbookRow(
                    ordinal=ordinal,
                    system_name=source.system_name,
                    release=release,
                    attempts=str(decided),
                    decisions=str(decided - non_matches),
                    far=_NO_DECISION,
                    frr=f"{non_matches / decided:.4f}" if decided else _NO_DECISION,
                    comment=(
                        f"FRR {non_matches}/{decided} over decided attempts. "
                        f"Applied profile: {source.profile}. FAR is undefined "
                        "on a mated set."
                    ),
                )
            )
            ordinal += 1

    for raw in _RAW_SOURCES:
        marker = _marker(repository_root, raw.marker)
        for release in RELEASES:
            rows.append(
                WorkbookRow(
                    ordinal=ordinal,
                    system_name=raw.system_name,
                    release=release,
                    attempts="500",
                    decisions=_NO_DECISION,
                    far=_NO_DECISION,
                    frr=_NO_DECISION,
                    comment=(
                        f"MATCH count, FAR and FRR are N/A. {raw.note} Outcome: "
                        f"{marker.get('outcome') or marker.get('kind')}."
                    ),
                )
            )
            ordinal += 1

    return tuple(rows)


# ------------------------------------------------------------------- writing


_MATCHED_HEADERS = (
    "Process #",
    "System name",
    "Release",
    "Identical fingers PLAIN-ROLL decided attempts",
    "MATCH decisions",
    "FAR\n(Not applicable to pairs of the same finger)",
    "FRR",
    "Comments",
)

_NON_MATCHED_HEADERS = (
    "Process #",
    "System name",
    "Release",
    "Different fingers PLAIN-ROLL attempts",
    "Correct NON_MATCH decisions",
    "FRR\n(Not applicable to pairs of different fingers)",
    SANITY_COLUMN_HEADING,
    "Comments",
)


def _sheet(headers: Sequence[str], rows: Sequence[WorkbookRow]) -> list[list[str]]:
    table = [list(headers)]
    for row in rows:
        if headers is _MATCHED_HEADERS:
            table.append(
                [
                    str(row.ordinal),
                    row.system_name,
                    row.release,
                    row.attempts,
                    row.decisions,
                    row.far,
                    row.frr,
                    row.comment,
                ]
            )
        else:
            table.append(
                [
                    str(row.ordinal),
                    row.system_name,
                    row.release,
                    row.attempts,
                    row.decisions,
                    row.frr,
                    row.far,
                    row.comment,
                ]
            )
    return table


def write_workbooks(
    *, repository_root: Path = REPOSITORY_ROOT, outputs: Path | None = None
) -> dict[str, Path]:
    """Write both workbooks. Returns ``name -> path``.

    Deliberately regenerating rather than editing: a workbook that is patched in
    place is one somebody has to remember to patch again.
    """
    from fpbench.experiments.xlsx_writer import write_sheet

    directory = Path(outputs) if outputs is not None else Path(repository_root) / "outputs"
    directory.mkdir(parents=True, exist_ok=True)

    written: dict[str, Path] = {}
    for name, headers, rows in (
        (MATCHED_WORKBOOK, _MATCHED_HEADERS, build_matched_rows(repository_root)),
        (
            NON_MATCHED_WORKBOOK,
            _NON_MATCHED_HEADERS,
            build_non_matched_rows(repository_root),
        ),
    ):
        written[name] = write_sheet(directory / name, _sheet(headers, rows))
    return written


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Regenerate the report workbooks")
    parser.add_argument("--outputs", type=Path, default=None)
    args = parser.parse_args(argv)
    for name, path in sorted(write_workbooks(outputs=args.outputs).items()):
        print(f"  {name}  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
