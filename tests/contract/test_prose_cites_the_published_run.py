"""Prose about Stage 11B must name the run Stage 11B actually published.

Stage 11B's 6,000 comparisons were re-executed when Stage 11A's fingerprint
moved, and every published JSON document followed — because every one of them is
derived. Two documents are written by hand, and both kept describing the run
that had been replaced: the repository README named ``run_52731bb3407e`` and a
median of 1,775 ms, and the evidence README quoted a whole timing distribution
from the superseded execution. The marker, the operational summary and the
receipt all agreed with each other and disagreed with the two files a reader
opens first.

That is the failure this repository keeps finding in other shapes: a value
restated by hand beside the value it was copied from, with nothing checking that
the two still match. So the check is the same one used elsewhere — read the
authority, and hold the prose to it.

Two rules, and the second is the one that generalises:

*Identifiers.* Every ``run_``/``plan_``/``resultset_`` token in Stage 11B prose
must appear somewhere in Stage 11B's own published JSON. This needs no list of
superseded ids and no edit when a run is replaced: an id that no published
document mentions is either stale or invented, and both are the same defect.

*Timings.* Any figure the prose labels ``median``, ``p95``, ``p99``, ``max`` or
``Wall clock`` must equal what ``operational-summary.json`` records, to the
millisecond or second it is quoted in. A document may quote a subset — the
repository README quotes only the median — but it may not quote a different
number.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = REPOSITORY_ROOT / "evidence" / "stage11b-verifinger-canonical500-raw"
STAGE_HISTORY = REPOSITORY_ROOT / "docs" / "stage-history.md"
EVIDENCE_README = EVIDENCE / "README.md"

#: ``run_0123456789ab`` and its two siblings, as every document spells them.
_IDENTIFIER = re.compile(r"\b(?:run|plan|resultset)_[0-9a-f]{12}\b")

#: ``median 1,883 ms``, ``Wall clock 14,427 s``. The unit is captured so a
#: figure quoted in seconds is not compared against milliseconds.
_FIGURE = re.compile(
    r"\b(median|p95|p99|max|Wall clock)\s+([\d,]+)\s*(ms|s)\b", re.IGNORECASE
)


def _published_json() -> dict[str, object]:
    """Every published Stage 11B document, keyed by file name."""
    return {
        path.name: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(EVIDENCE.glob("*.json"))
    }


def _operational_summary() -> dict:
    return json.loads(
        (EVIDENCE / "operational-summary.json").read_text(encoding="utf-8")
    )


def _stage_11b_section(text: str) -> str:
    """The linked stage history's Stage 11B section, and nothing else.

    The file describes twenty stages; holding all of them to Stage 11B's
    published identifiers would fail on every other stage's run.
    """
    start = text.index("## Stage 11B")
    rest = text.index("\n## ", start + 1)
    return text[start:rest]


def _authoritative_figures() -> dict[str, tuple[float, str]]:
    timings = _operational_summary()["timings"]
    adapter = timings["adapter_ms"]
    return {
        "median": (adapter["median"], "ms"),
        "p95": (adapter["p95"], "ms"),
        "p99": (adapter["p99"], "ms"),
        "max": (adapter["max"], "ms"),
        "wall clock": (timings["wall_clock_span_seconds"], "s"),
    }


def _prose() -> list[tuple[str, str]]:
    return [
        ("evidence/.../README.md", EVIDENCE_README.read_text(encoding="utf-8")),
        (
            "docs/stage-history.md (Stage 11B section)",
            _stage_11b_section(STAGE_HISTORY.read_text(encoding="utf-8")),
        ),
    ]


@pytest.mark.parametrize("label,text", _prose(), ids=lambda item: str(item)[:40])
def test_every_identifier_in_the_prose_is_one_the_evidence_publishes(
    label: str, text: str
) -> None:
    published = json.dumps(_published_json(), sort_keys=True)
    unknown = sorted(
        {
            identifier
            for identifier in _IDENTIFIER.findall(text)
            if identifier not in published
        }
    )
    assert not unknown, (
        f"{label} names {unknown}, which no published Stage 11B document "
        "mentions. Either the run was replaced and the prose was not updated, "
        "or the prose invented an identifier"
    )


def test_the_prose_names_the_run_that_was_published() -> None:
    """The weaker rule above passes on prose that names no run at all."""
    summary = _operational_summary()
    text = EVIDENCE_README.read_text(encoding="utf-8") + _stage_11b_section(
        STAGE_HISTORY.read_text(encoding="utf-8")
    )
    for field in ("run_id", "plan_id"):
        assert summary[field] in text, (
            f"no Stage 11B prose names {field} {summary[field]!r}, which is what "
            "operational-summary.json records"
        )


@pytest.mark.parametrize("label,text", _prose(), ids=lambda item: str(item)[:40])
def test_every_timing_the_prose_quotes_matches_the_operational_summary(
    label: str, text: str
) -> None:
    authority = _authoritative_figures()
    quoted = _FIGURE.findall(text)
    assert quoted, f"{label} quotes no timing figure; this test would pass vacuously"
    for name, value, unit in quoted:
        key = name.lower()
        expected, expected_unit = authority[key]
        assert unit == expected_unit, (
            f"{label} quotes {key} in {unit}, and the operational summary "
            f"records it in {expected_unit}"
        )
        assert int(value.replace(",", "")) == round(expected), (
            f"{label} says {key} is {value} {unit}; operational-summary.json "
            f"records {expected} {expected_unit}. Re-derive the prose from the "
            "evidence rather than editing the number"
        )
