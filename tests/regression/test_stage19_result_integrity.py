"""Stage 19 completion counts come from the outcome store, never the CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fpbench.experiments.stage19_result_integrity import (
    Stage19ResultIntegrityError,
    canonical_source_sha256,
    verify_outcome_store_integrity,
)
from fpbench.experiments.stage19a_finalization import (
    Stage19AFinalizationError,
    build_canonical_run_binding as build_stage19a_binding,
)
from fpbench.experiments.stage19b_finalization import (
    Stage19BFinalizationError,
    build_canonical_run_binding as build_stage19b_binding,
)


def _write_outcomes(path: Path, rows: list[dict[str, object]]) -> Path:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    return path


def _diagnostics(comparisons: int, **counts: int) -> dict[str, object]:
    return {
        "overall": {"comparisons": comparisons},
        "outcome_counts": counts or {"OK": comparisons},
    }


def test_all_five_counts_and_the_store_digest_are_derived_together(
    tmp_path: Path,
) -> None:
    path = _write_outcomes(
        tmp_path / "pair-outcomes.jsonl",
        [
            {"ordinal": 0, "pair_id": "pair_0", "status": "OK"},
            {"ordinal": 1, "pair_id": "pair_1", "status": "FAILED"},
            {"ordinal": 2, "pair_id": "pair_2", "status": "OK"},
        ],
    )

    audit = verify_outcome_store_integrity(
        path,
        _diagnostics(3, OK=2, FAILED=1),
        expected_outcomes=3,
    )

    assert (
        audit.unique_pair_ids
        == audit.unique_ordinals
        == audit.diagnostic_comparisons
        == audit.stored_outcomes
        == audit.expected_outcomes
        == 3
    )
    assert audit.missing == 0
    assert len(audit.outcome_store_sha256) == 64


@pytest.mark.parametrize(
    "rows, diagnostics, message",
    [
        (
            [
                {"ordinal": 0, "pair_id": "same", "status": "OK"},
                {"ordinal": 1, "pair_id": "same", "status": "OK"},
            ],
            _diagnostics(2),
            "unique pair_ids",
        ),
        (
            [
                {"ordinal": 0, "pair_id": "pair_0", "status": "OK"},
                {"ordinal": 0, "pair_id": "pair_1", "status": "OK"},
            ],
            _diagnostics(2),
            "unique ordinals",
        ),
        (
            [{"ordinal": 0, "pair_id": "pair_0", "status": "OK"}],
            _diagnostics(2, OK=1),
            "diagnostic comparisons",
        ),
    ],
)
def test_no_independent_count_may_disagree(
    tmp_path: Path,
    rows: list[dict[str, object]],
    diagnostics: dict[str, object],
    message: str,
) -> None:
    path = _write_outcomes(tmp_path / "pair-outcomes.jsonl", rows)
    with pytest.raises(Stage19ResultIntegrityError, match=message):
        verify_outcome_store_integrity(path, diagnostics, expected_outcomes=2)


@pytest.mark.parametrize(
    "builder, error",
    [
        (build_stage19a_binding, Stage19AFinalizationError),
        (build_stage19b_binding, Stage19BFinalizationError),
    ],
)
def test_one_diagnostic_comparison_can_never_close_a_stage19_run(
    tmp_path: Path,
    builder,
    error: type[RuntimeError],
) -> None:
    path = _write_outcomes(
        tmp_path / "pair-outcomes.jsonl",
        [{"ordinal": 0, "pair_id": "pair_0", "status": "OK"}],
    )
    with pytest.raises(error, match="expected outcomes=6000"):
        builder(_diagnostics(1), outcomes=path)


def test_stage19_make_targets_do_not_accept_claimed_counters() -> None:
    makefile = (Path(__file__).resolve().parents[2] / "Makefile").read_text(
        encoding="utf-8"
    )
    for target in ("stage19a-documents", "stage19b-documents"):
        recipe = makefile.split(f"{target}:", 1)[1].split("\n\n", 1)[0]
        assert "--outcomes" in recipe
        assert "--stored" not in recipe
        assert "--missing" not in recipe


def test_source_hash_is_independent_of_checkout_line_endings(tmp_path: Path) -> None:
    source = tmp_path / "source.py"
    source.write_bytes(b"first line\nsecond line\n")
    lf_hash = canonical_source_sha256(source)

    source.write_bytes(b"first line\r\nsecond line\r\n")

    assert canonical_source_sha256(source) == lf_hash
