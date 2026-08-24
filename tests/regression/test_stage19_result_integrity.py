"""Stage 19 completion counts come from the outcome store, never the CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import fpbench.experiments.stage19a_finalization as stage19a
import fpbench.experiments.stage19b_finalization as stage19b
from fpbench.experiments.stage19_pair_manifest import CanonicalPairManifest
from fpbench.experiments.stage19_result_integrity import (
    CanonicalPair,
    Stage19ResultIntegrityError,
    canonical_source_sha256,
    verify_outcome_store_integrity,
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


ALGORITHM = "nbis_mindtct_openafis"
MANIFEST_HASH = "e" * 64

#: The reasons this route has classified; see stage19a_finalization.
from fpbench.experiments.stage19a_finalization import OUTCOME_CONTRACT

#: The route's whole outcome contract.
CONTRACT = OUTCOME_CONTRACT

CLASSIFIED = frozenset(
    {
        "invalid_raster_dimensions",
        "minutiae_below_upstream_minimum",
        "minutiae_above_upstream_maximum",
    }
)


def _pair(ordinal: int, pair_id: str | None = None) -> CanonicalPair:
    identifier = pair_id if pair_id is not None else f"pair_{ordinal}"
    return CanonicalPair(
        ordinal=ordinal,
        pair_id=identifier,
        release="SD300A",
        protocol_stage="plain_self",
        ground_truth="mated",
        left_image_id=f"image_{ordinal}_left",
        right_image_id=f"image_{ordinal}_right",
    )


def _row(pair: CanonicalPair, status: str = "OK", **overrides: object) -> dict:
    """A store row that agrees with ``pair`` on everything but the overrides."""
    row: dict[str, object] = {
        "ordinal": pair.ordinal,
        "pair_id": pair.pair_id,
        "algorithm_id": ALGORITHM,
        "release": pair.release,
        "stage": pair.protocol_stage,
        "ground_truth": pair.ground_truth,
        "left_image_id": pair.left_image_id,
        "right_image_id": pair.right_image_id,
        "status": status,
        "raw_score": 7 if status == "OK" else None,
    }
    row.update(overrides)
    return row


def _verify(path: Path, diagnostics: dict, manifest, expected: int):
    return verify_outcome_store_integrity(
        path,
        diagnostics,
        expected_outcomes=expected,
        manifest=manifest,
        algorithm_id=ALGORITHM,
        pair_manifest_hash=MANIFEST_HASH,
        classified_failure_reasons=CLASSIFIED,
        outcome_contract=CONTRACT,
    )


def test_all_five_counts_and_the_store_digest_are_derived_together(
    tmp_path: Path,
) -> None:
    manifest = tuple(_pair(index) for index in range(3))
    path = _write_outcomes(
        tmp_path / "pair-outcomes.jsonl",
        [
            _row(manifest[0]),
            _row(
                manifest[1],
                status="OPENAFIS_TEMPLATE_FAILED_LEFT",
                failure_code="template_extraction_failed",
                failure_reason="minutiae_above_upstream_maximum",
            ),
            _row(manifest[2]),
        ],
    )

    audit = _verify(path, _diagnostics(3, OK=2, OPENAFIS_TEMPLATE_FAILED_LEFT=1), manifest, 3)

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


def test_a_manifest_naming_one_pair_twice_is_refused(tmp_path: Path) -> None:
    """Two ordinals, one pair id — the manifest cannot be an authority."""
    manifest = (_pair(0, "same"), _pair(1, "same"))
    path = _write_outcomes(
        tmp_path / "pair-outcomes.jsonl",
        [_row(manifest[0]), _row(manifest[1])],
    )
    with pytest.raises(Stage19ResultIntegrityError, match="same pair twice"):
        _verify(path, _diagnostics(2), manifest, 2)


def test_a_repeated_ordinal_is_refused(tmp_path: Path) -> None:
    manifest = tuple(_pair(index) for index in range(2))
    path = _write_outcomes(
        tmp_path / "pair-outcomes.jsonl",
        [_row(manifest[0]), _row(manifest[0])],
    )
    with pytest.raises(Stage19ResultIntegrityError, match="already stored"):
        _verify(path, _diagnostics(2), manifest, 2)


def test_a_short_store_cannot_be_closed_by_agreeable_diagnostics(
    tmp_path: Path,
) -> None:
    manifest = tuple(_pair(index) for index in range(2))
    path = _write_outcomes(tmp_path / "pair-outcomes.jsonl", [_row(manifest[0])])
    with pytest.raises(Stage19ResultIntegrityError, match="diagnostic comparisons"):
        _verify(path, _diagnostics(2, OK=1), manifest, 2)


@pytest.mark.parametrize(
    "module, error",
    [
        (stage19a, stage19a.Stage19AFinalizationError),
        (stage19b, stage19b.Stage19BFinalizationError),
    ],
)
def test_one_diagnostic_comparison_can_never_close_a_stage19_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    module,
    error: type[RuntimeError],
) -> None:
    manifest = CanonicalPairManifest(
        pairs=(_pair(0),),
        pair_manifest_hash=MANIFEST_HASH,
        protocol_id="sd300_50_subjects",
        cohort_id="sd300_50_subjects_test_22f8d52a7478",
        source_path=tmp_path / "pairs.parquet",
    )
    monkeypatch.setattr(module, "_pair_manifest", lambda workspace: manifest)
    path = _write_outcomes(
        tmp_path / "pair-outcomes.jsonl",
        [_row(_pair(0))],
    )
    # Supply the manifest explicitly: a clean CI checkout has no workspace, and
    # this test is about refusing a short store rather than about acquisition.
    with pytest.raises(error, match="6000"):
        module.build_canonical_run_binding(_diagnostics(1), outcomes=path)


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
