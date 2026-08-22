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

#: The reasons this route has classified. Anything else a store carries is a
#: real failure the stage may not call itself complete over.
CLASSIFIED = frozenset(
    {
        "invalid_raster_dimensions",
        "minutiae_below_upstream_minimum",
        "minutiae_above_upstream_maximum",
    }
)


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
        classified_failure_reasons=CLASSIFIED,
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
    rows[0].update(
            {
                "status": "INFRASTRUCTURE_FAILURE",
                "raw_score": None,
                "failure_reason": "input_unreadable",
            }
        )
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
            classified_failure_reasons=CLASSIFIED,
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


# ------------------------------- the conclusion, not only the identity


def test_the_reasons_a_run_failed_are_counted_not_reported(tmp_path: Path) -> None:
    """The reviewer's second exploit.

    Six thousand canonical pairs, every one failed for
    ``minutiae_above_upstream_maximum``, and a diagnostics document saying
    ``failure_reasons: {}``. Stage 19B's fourth condition reads that field, so
    the run published ``capacity_failures_remaining=0`` and established an
    algorithm on zero usable results. Binding the pair ids proved *which*
    comparisons ran; it said nothing about what they produced.
    """
    pairs = _manifest()
    rows = [
        _row(pair, status="OPENAFIS_TEMPLATE_FAILED_LEFT", raw_score=None,
             failure_reason="minutiae_above_upstream_maximum")
        for pair in pairs
    ]
    diagnostics = _diagnostics(rows)
    diagnostics["failure_reasons"] = {}

    with pytest.raises(Stage19ResultIntegrityError, match="failure_reasons"):
        verify_outcome_store_integrity(
            _store(tmp_path, rows),
            diagnostics,
            expected_outcomes=len(pairs),
            manifest=pairs,
            algorithm_id=ALGORITHM,
            pair_manifest_hash=MANIFEST_HASH,
            classified_failure_reasons=CLASSIFIED,
        )


def test_the_derived_reasons_are_what_the_store_holds(tmp_path: Path) -> None:
    pairs = _manifest()
    rows = [_row(pair) for pair in pairs]
    rows[0].update({"status": "OPENAFIS_TEMPLATE_FAILED_LEFT", "raw_score": None,
                    "failure_reason": "minutiae_above_upstream_maximum"})
    rows[1].update({"status": "INFRASTRUCTURE_FAILURE", "raw_score": None,
                    "failure_reason": "workspace_not_visible"})
    diagnostics = _diagnostics(rows)
    diagnostics["failure_reasons"] = {
        "minutiae_above_upstream_maximum": 1,
        "workspace_not_visible": 1,
    }

    integrity = verify_outcome_store_integrity(
        _store(tmp_path, rows),
        diagnostics,
        expected_outcomes=len(pairs),
        manifest=pairs,
        algorithm_id=ALGORITHM,
        pair_manifest_hash=MANIFEST_HASH,
        classified_failure_reasons=CLASSIFIED,
    )
    assert integrity.capacity_failures("minutiae_above_upstream_maximum") == 1
    assert integrity.failure_reasons == {
        "minutiae_above_upstream_maximum": 1,
        "workspace_not_visible": 1,
    }
    assert integrity.score_bearing == len(pairs) - 2
    assert integrity.score_bearing_fraction == (len(pairs) - 2) / len(pairs)


def test_a_stage_population_the_store_contradicts_is_refused(tmp_path: Path) -> None:
    """The per-stage populations a conclusion divides by are counted, not read."""
    pairs = _manifest()
    rows = [_row(pair) for pair in pairs]
    diagnostics = _diagnostics(rows)
    diagnostics["by_protocol_stage"] = [
        {"label": "plain_self", "comparisons": 99, "score_bearing": 99}
    ]
    with pytest.raises(Stage19ResultIntegrityError, match="plain_self"):
        verify_outcome_store_integrity(
            _store(tmp_path, rows),
            diagnostics,
            expected_outcomes=len(pairs),
            manifest=pairs,
            algorithm_id=ALGORITHM,
            pair_manifest_hash=MANIFEST_HASH,
            classified_failure_reasons=CLASSIFIED,
        )


def test_a_stage_the_manifest_does_not_contain_is_refused(tmp_path: Path) -> None:
    pairs = _manifest()
    rows = [_row(pair) for pair in pairs]
    diagnostics = _diagnostics(rows)
    diagnostics["by_protocol_stage"] = [{"label": "invented_stage", "comparisons": 1}]
    with pytest.raises(Stage19ResultIntegrityError, match="invented_stage"):
        verify_outcome_store_integrity(
            _store(tmp_path, rows),
            diagnostics,
            expected_outcomes=len(pairs),
            manifest=pairs,
            algorithm_id=ALGORITHM,
            pair_manifest_hash=MANIFEST_HASH,
            classified_failure_reasons=CLASSIFIED,
        )


# ------------------------- conditions the publisher judges, rather than is told


def _stage19a_binding(**overrides) -> dict:
    from fpbench.experiments import stage19a_identity as frozen19a

    document = {
        "expected_outcomes": frozen19a.EXPECTED_OUTCOMES,
        "stored_outcomes": frozen19a.EXPECTED_OUTCOMES,
        "unique_pair_ids": frozen19a.EXPECTED_OUTCOMES,
        "unique_ordinals": frozen19a.EXPECTED_OUTCOMES,
        "diagnostic_comparisons": frozen19a.EXPECTED_OUTCOMES,
        "missing": 0,
        "outcome_store_sha256": "a" * 64,
        "outcome_counts": {"OK": frozen19a.EXPECTED_OUTCOMES},
    }
    document.update(overrides)
    return document


def _stage19a_marker(binding: dict) -> dict:
    from fpbench.experiments.stage19a_finalization import build_stage19a_finalization

    return build_stage19a_finalization(
        repository_root=Path(__file__).resolve().parents[2],
        binding=binding,
        diagnostics={},
        evidence_hashes={},
    )


def test_a_clean_stage19a_run_still_reports_no_systemic_defect() -> None:
    conditions = _stage19a_marker(_stage19a_binding())["algorithm_5_conditions"]
    assert conditions["no_systemic_implementation_defect"] is True
    assert conditions["failures_are_upstream_limits_not_the_bridge"] is True


@pytest.mark.parametrize("status", ["OPENAFIS_MATCH_FAILED", "INFRASTRUCTURE_FAILURE"])
def test_a_blocking_failure_is_a_systemic_defect_whatever_the_caller_says(
    status: str,
) -> None:
    """These two conditions used to be arguments.

    ``main`` counted the blocking statuses and passed two booleans in;
    ``build_stage19a_finalization`` published them. Any other caller — a script,
    a test, a future stage — could pass ``True`` over a run of nothing but
    matcher failures, and the marker would say the implementation is sound.
    There is no argument to pass now: the counts are in the binding, and the
    binding counts them off the verified store.
    """
    from fpbench.experiments import stage19a_identity as frozen19a

    binding = _stage19a_binding(
        outcome_counts={"OK": frozen19a.EXPECTED_OUTCOMES - 4, status: 4}
    )
    conditions = _stage19a_marker(binding)["algorithm_5_conditions"]
    assert conditions["no_systemic_implementation_defect"] is False
    assert conditions["failures_are_upstream_limits_not_the_bridge"] is False


def test_an_upstream_capacity_failure_is_not_a_defect_of_ours() -> None:
    """The distinction the second condition exists to draw.

    A template the build cannot hold is the route answering, not the bridge
    breaking, and Stage 19B is the whole stage about that answer.
    """
    from fpbench.experiments import stage19a_identity as frozen19a

    binding = _stage19a_binding(
        outcome_counts={
            "OK": frozen19a.EXPECTED_OUTCOMES - 4,
            "OPENAFIS_TEMPLATE_FAILED_LEFT": 4,
        }
    )
    conditions = _stage19a_marker(binding)["algorithm_5_conditions"]
    assert conditions["no_systemic_implementation_defect"] is True


@pytest.mark.parametrize(
    "field, value",
    [
        ("unique_pair_ids", 1),
        ("unique_ordinals", 1),
        ("diagnostic_comparisons", 1),
        ("stored_outcomes", 1),
        ("missing", 1),
    ],
)
def test_stage19a_names_the_count_that_stopped_the_publication(field, value) -> None:
    """A refusal that does not say what is wrong is a refusal nobody acts on.

    The old message was "this run stored 6000 with 0 missing" — true, and
    useless when what failed was that six thousand rows carried one pair id.
    """
    from fpbench.experiments.stage19a_finalization import (
        Stage19AFinalizationError,
        build_stage19a_finalization,
    )

    binding = _stage19a_binding(**{field: value})
    with pytest.raises(Stage19AFinalizationError) as refusal:
        build_stage19a_finalization(
            repository_root=Path(__file__).resolve().parents[2],
            binding=binding,
            diagnostics={},
            evidence_hashes={},
        )
    assert field in str(refusal.value), (
        f"the refusal does not name {field}: {refusal.value}"
    )


# ---------------------------- a failure that does not say why is not a failure


def test_a_failure_with_no_reason_at_all_is_refused(tmp_path: Path) -> None:
    """The reviewer's second store, kept as a test.

    Six thousand unique ordinals, every one ``OPENAFIS_TEMPLATE_FAILED_LEFT``,
    no score and no ``failure_reason`` key. The reason counter skipped rows
    without a reason, so ``failure_reasons`` came out ``{}``,
    ``capacity_failures_remaining`` came out 0, and a run that scored nothing
    was declared to have nothing left to fix.
    """
    pairs = _manifest()
    rows = [_row(pair) for pair in pairs]
    for row in rows:
        row.update({"status": "OPENAFIS_TEMPLATE_FAILED_LEFT", "raw_score": None})
        row.pop("failure_reason", None)
    with pytest.raises(Stage19ResultIntegrityError, match="states its cause"):
        _verify(tmp_path, rows)


@pytest.mark.parametrize("reason", [None, "", "   "])
def test_an_empty_reason_is_the_same_as_no_reason(tmp_path: Path, reason) -> None:
    pairs = _manifest()
    rows = [_row(pair) for pair in pairs]
    rows[0].update(
        {
            "status": "OPENAFIS_TEMPLATE_FAILED_LEFT",
            "raw_score": None,
            "failure_reason": reason,
        }
    )
    with pytest.raises(Stage19ResultIntegrityError, match="states its cause"):
        _verify(tmp_path, rows)


def test_every_failing_row_is_counted_exactly_once(tmp_path: Path) -> None:
    """The total is now an identity, not an estimate.

    Because a row with no reason is refused, the reasons account for every
    comparison that did not produce a score. A stage can subtract.
    """
    pairs = _manifest()
    rows = [_row(pair) for pair in pairs]
    for row in rows[:4]:
        row.update(
            {
                "status": "OPENAFIS_TEMPLATE_FAILED_LEFT",
                "raw_score": None,
                "failure_reason": "minutiae_above_upstream_maximum",
            }
        )
    integrity = _verify(tmp_path, rows)
    assert sum(integrity.failure_reasons.values()) == (
        integrity.stored_outcomes - integrity.score_bearing
    )
    assert integrity.failure_reasons == {"minutiae_above_upstream_maximum": 4}


def test_a_reason_the_route_never_classified_is_counted_as_unclassified(
    tmp_path: Path,
) -> None:
    """A bridge crash is a real failure and an unread one.

    It is stored honestly and it is counted honestly; what it must not do is
    let a stage call itself complete. ``unclassified_failures`` is the field the
    stages' ``no_unclassified_failure`` condition reads.
    """
    pairs = _manifest()
    rows = [_row(pair) for pair in pairs]
    rows[0].update(
        {
            "status": "OPENAFIS_MATCH_FAILED",
            "raw_score": None,
            "failure_reason": "bridge_crash_139",
        }
    )
    rows[1].update(
        {
            "status": "OPENAFIS_TEMPLATE_FAILED_LEFT",
            "raw_score": None,
            "failure_reason": "minutiae_above_upstream_maximum",
        }
    )
    integrity = _verify(tmp_path, rows)
    assert integrity.unclassified_failure_reasons == {"bridge_crash_139": 1}
    assert integrity.unclassified_failures == 1
    # The classified one is not swept in with it.
    assert integrity.capacity_failures("minutiae_above_upstream_maximum") == 1


def test_a_store_of_only_classified_reasons_has_nothing_unclassified(
    tmp_path: Path,
) -> None:
    pairs = _manifest()
    rows = [_row(pair) for pair in pairs]
    for row in rows:
        row.update(
            {
                "status": "OPENAFIS_TEMPLATE_FAILED_LEFT",
                "raw_score": None,
                "failure_reason": "minutiae_above_upstream_maximum",
            }
        )
    integrity = _verify(tmp_path, rows)
    assert integrity.unclassified_failures == 0
    assert integrity.score_bearing == 0


# ------------------------------------- the reason a stored failure carries now


@pytest.mark.parametrize(
    "details, status, expected",
    [
        ({"reason": "minutiae_above_upstream_maximum"}, "X", "minutiae_above_upstream_maximum"),
        ({"kind": "malformed_xyt"}, "INVALID_XYT_LEFT", "malformed_xyt"),
        ({"detail": "mindtct_timeout"}, "INFRASTRUCTURE_FAILURE", "mindtct_timeout"),
        ({"exit_code": 2, "side": "left"}, "MINDTCT_FAILED_LEFT", "exit_code_2"),
        ({"observed_score": "nan"}, "MCC_INVALID_SCORE", "invalid_score"),
        ({}, "BRIDGE_FAILURE", "unclassified_bridge_failure"),
        ({"reason": "   "}, "BRIDGE_FAILURE", "unclassified_bridge_failure"),
    ],
)
def test_every_failure_shape_yields_a_reason(details, status, expected) -> None:
    """The producers only ever stored ``details["reason"]``.

    Only ``template_refused_failure`` sets that key, so a mindtct exit code, an
    invalid xyt, a timeout and a bridge crash were all written as
    ``failure_reason: null`` — and the validator, which now refuses those rows,
    would refuse a legitimate run. The fix is at both ends.
    """
    from fpbench.experiments.stage19_result_integrity import (
        failure_reason_from_details,
    )

    assert failure_reason_from_details(details, status=status) == expected
