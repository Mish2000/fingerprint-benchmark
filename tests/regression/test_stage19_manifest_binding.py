"""A Stage 19 store must *be* the canonical run, not merely be the right size.

The reviewer's exploit, kept as a test. Six thousand rows carrying
``fabricated_0000`` upward, ordinals 0..5,999 and diagnostics that agreed with
them satisfied every check the validator made, and published
``CANONICAL_RAW_COMPLETE`` with ``algorithm_5_established: true``. Counting was
never the missing piece; comparing was.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fpbench.experiments.stage19_result_integrity import (
    CanonicalPair,
    Stage19ResultIntegrityError,
    bound_manifest_digest,
    verify_outcome_store_integrity,
)

ALGORITHM = "nbis_mindtct_openafis"
MANIFEST_HASH = "e" * 64


#: The three protocol stages a Stage 19 manifest actually mixes, and the ground
#: truth each one carries. Written out rather than generated, so a mutation in a
#: test below can never coincidentally equal the value it replaces.
_STAGES = (
    ("plain_self", "mated"),
    ("plain_roll_mated", "mated"),
    ("plain_roll_non_mated", "non_mated"),
)


def _manifest(count: int = 9) -> tuple[CanonicalPair, ...]:
    pairs = []
    for index in range(count):
        stage, truth = _STAGES[index % len(_STAGES)]
        pairs.append(
            CanonicalPair(
                ordinal=index,
                pair_id=f"sd300a_0000{index:04d}_f01_{stage}",
                release="SD300A",
                protocol_stage=stage,
                ground_truth=truth,
                left_image_id=f"sd300a_0000{index:04d}_plain_f01",
                right_image_id=f"sd300a_0000{index:04d}_roll_f01",
            )
        )
    return tuple(pairs)


def _row(pair: CanonicalPair, **overrides: object) -> dict:
    row = {
        "ordinal": pair.ordinal,
        "pair_id": pair.pair_id,
        "algorithm_id": ALGORITHM,
        "release": pair.release,
        "stage": pair.protocol_stage,
        "ground_truth": pair.ground_truth,
        "left_image_id": pair.left_image_id,
        "right_image_id": pair.right_image_id,
        "raw_score": 42,
        "status": "OK",
    }
    row.update(overrides)
    return row


def _store(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "pair-outcomes.jsonl"
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    return path


def _diagnostics(rows: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for row in rows:
        counts[str(row["status"])] = counts.get(str(row["status"]), 0) + 1
    return {
        "overall": {
            "comparisons": len(rows),
            "score_bearing": sum(1 for row in rows if row["status"] == "OK"),
        },
        "outcome_counts": counts,
    }


def _verify(tmp_path: Path, rows: list[dict], manifest=None):
    pairs = _manifest() if manifest is None else manifest
    return verify_outcome_store_integrity(
        _store(tmp_path, rows),
        _diagnostics(rows),
        expected_outcomes=len(pairs),
        manifest=pairs,
        algorithm_id=ALGORITHM,
        pair_manifest_hash=MANIFEST_HASH,
    )


def test_the_canonical_store_verifies(tmp_path: Path) -> None:
    pairs = _manifest()
    integrity = _verify(tmp_path, [_row(pair) for pair in pairs])
    assert integrity.stored_outcomes == len(pairs)
    assert integrity.missing == 0
    assert integrity.score_bearing == len(pairs)
    assert integrity.pair_manifest_hash == MANIFEST_HASH
    assert integrity.bound_manifest_digest == bound_manifest_digest(pairs)


def test_fabricated_pair_ids_are_refused(tmp_path: Path) -> None:
    """The reviewer's exploit: right cardinality, invented comparisons."""
    rows = [
        _row(pair, pair_id=f"fabricated_{index:04d}")
        for index, pair in enumerate(_manifest())
    ]
    with pytest.raises(Stage19ResultIntegrityError, match="pair_id"):
        _verify(tmp_path, rows)


def test_a_store_with_no_manifest_cannot_be_verified(tmp_path: Path) -> None:
    """An optional manifest is a manifest a publisher can omit."""
    rows = [_row(pair) for pair in _manifest()]
    with pytest.raises(Stage19ResultIntegrityError, match="pair manifest"):
        _verify(tmp_path, rows, manifest=())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("release", "SD300C"),
        ("stage", "plain_roll_non_mated"),
        ("ground_truth", "non_mated"),
        ("left_image_id", "sd300a_00009999_plain_f01"),
        ("right_image_id", "sd300a_00009999_roll_f01"),
    ],
)
def test_a_row_that_disagrees_with_the_manifest_is_refused(
    tmp_path: Path, field: str, value: str
) -> None:
    """Ground truth especially: a swapped label would invert every conclusion."""
    pairs = _manifest()
    rows = [_row(pair) for pair in pairs]
    rows[3][field] = value
    with pytest.raises(Stage19ResultIntegrityError, match=field):
        _verify(tmp_path, rows)


def test_a_row_from_another_algorithm_is_refused(tmp_path: Path) -> None:
    rows = [_row(pair) for pair in _manifest()]
    rows[2]["algorithm_id"] = "nbis_mindtct_bozorth3"
    with pytest.raises(Stage19ResultIntegrityError, match="algorithm_id"):
        _verify(tmp_path, rows)


def test_a_failure_carrying_a_score_is_refused(tmp_path: Path) -> None:
    """A failure stored with a score is a non-match nobody measured."""
    rows = [_row(pair) for pair in _manifest()]
    rows[1].update({"status": "OPENAFIS_TEMPLATE_FAILED_LEFT", "raw_score": 0})
    with pytest.raises(Stage19ResultIntegrityError, match="raw_score"):
        _verify(tmp_path, rows)


def test_a_success_without_a_score_is_refused(tmp_path: Path) -> None:
    rows = [_row(pair) for pair in _manifest()]
    rows[1]["raw_score"] = None
    with pytest.raises(Stage19ResultIntegrityError, match="raw_score"):
        _verify(tmp_path, rows)


def test_a_repeated_ordinal_is_refused(tmp_path: Path) -> None:
    pairs = _manifest()
    rows = [_row(pair) for pair in pairs]
    rows[5] = _row(pairs[4])
    with pytest.raises(Stage19ResultIntegrityError, match="already stored"):
        _verify(tmp_path, rows)


def test_an_ordinal_outside_the_manifest_is_refused(tmp_path: Path) -> None:
    pairs = _manifest()
    rows = [_row(pair) for pair in pairs]
    rows[0]["ordinal"] = len(pairs)
    with pytest.raises(Stage19ResultIntegrityError, match="outside the manifest"):
        _verify(tmp_path, rows)


def test_a_manifest_out_of_protocol_order_is_refused(tmp_path: Path) -> None:
    pairs = list(_manifest())
    pairs[2], pairs[3] = pairs[3], pairs[2]
    rows = [_row(pair) for pair in _manifest()]
    with pytest.raises(Stage19ResultIntegrityError, match="protocol order"):
        _verify(tmp_path, rows, manifest=tuple(pairs))


def test_diagnostics_that_overstate_the_scored_population_are_refused(
    tmp_path: Path,
) -> None:
    pairs = _manifest()
    rows = [_row(pair) for pair in pairs]
    rows[0].update({"status": "INFRASTRUCTURE_FAILURE", "raw_score": None})
    diagnostics = _diagnostics(rows)
    diagnostics["overall"]["score_bearing"] = len(pairs)
    with pytest.raises(Stage19ResultIntegrityError, match="score-bearing"):
        verify_outcome_store_integrity(
            _store(tmp_path, rows),
            diagnostics,
            expected_outcomes=len(pairs),
            manifest=pairs,
            algorithm_id=ALGORITHM,
            pair_manifest_hash=MANIFEST_HASH,
        )


def test_the_bound_digest_distinguishes_two_manifests() -> None:
    """Two runs that agree on this were bound to the same comparisons."""
    original = _manifest()
    other = list(original)
    assert original[0].ground_truth == "mated"
    other[0] = CanonicalPair(
        ordinal=0,
        pair_id=other[0].pair_id,
        release=other[0].release,
        protocol_stage=other[0].protocol_stage,
        ground_truth="non_mated",
        left_image_id=other[0].left_image_id,
        right_image_id=other[0].right_image_id,
    )
    assert bound_manifest_digest(original) != bound_manifest_digest(tuple(other))
