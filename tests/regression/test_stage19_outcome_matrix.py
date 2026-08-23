"""The reviewer's acceptance matrix for the outcome contract, row by row.

Eleven scenarios, each naming the fields that vary and the verdict required. They
are written here *before* the contract that satisfies them, because the previous
round's tests were written from the implementation and so canonised its holes —
one of them asserted that a status owning nothing accepts any reason, which was
the defect.

The matrix distinguishes three verdicts, and the distinction is the design:

* **the validator refuses** — the store is not a thing any run could have
  produced, so nothing downstream may read it and no marker is written;
* **the validator accepts and the run does not publish** — the store is honest,
  the failures are real, and a condition stops the stage concluding over them;
* **the marker is written and says so** — a run that failed is still a run, and
  its evidence is worth keeping.

Scale is deliberately not 6,000 here: every row of the matrix states a property
of a *row*, and a per-row property is not better tested by repeating it six
thousand times. ``scripts/stage19_acceptance_matrix.py`` runs the same table at
full scale against the real canonical manifest.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fpbench.experiments.stage19_result_integrity import (
    CanonicalPair,
    Stage19ResultIntegrityError,
    verify_outcome_store_integrity,
)

MANIFEST_HASH = "e" * 64

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


# --------------------------------------------------------------- the two routes


def _route(name: str):
    """``(algorithm_id, contract, classified reasons, a valid score)``."""
    if name == "openafis":
        from fpbench.experiments.stage19a_finalization import (
            CLASSIFIED_FAILURE_REASONS,
            OUTCOME_CONTRACT,
        )

        return "nbis_mindtct_openafis", OUTCOME_CONTRACT, CLASSIFIED_FAILURE_REASONS, 42
    from fpbench.experiments.stage20b_finalization import (
        CLASSIFIED_FAILURE_REASONS,
        OUTCOME_CONTRACT,
    )

    return "nbis_mindtct_mcc_sdk_v2", OUTCOME_CONTRACT, CLASSIFIED_FAILURE_REASONS, 0.5


def _row(pair: CanonicalPair, algorithm: str, **overrides) -> dict:
    row = {
        "ordinal": pair.ordinal,
        "pair_id": pair.pair_id,
        "algorithm_id": algorithm,
        "release": pair.release,
        "stage": pair.protocol_stage,
        "ground_truth": pair.ground_truth,
        "left_image_id": pair.left_image_id,
        "right_image_id": pair.right_image_id,
        "status": "OK",
        "raw_score": None,
        "failure_code": None,
        "failure_reason": None,
    }
    row.update(overrides)
    return row


def _diagnostics(rows: list[dict]) -> dict:
    """Derived from the rows exactly, as the matrix requires."""
    counts: dict[str, int] = {}
    reasons: dict[str, int] = {}
    for row in rows:
        counts[str(row["status"])] = counts.get(str(row["status"]), 0) + 1
        if row["status"] != "OK" and row.get("failure_reason"):
            key = str(row["failure_reason"])
            reasons[key] = reasons.get(key, 0) + 1
    return {
        "overall": {
            "comparisons": len(rows),
            "score_bearing": sum(1 for row in rows if row["status"] == "OK"),
        },
        "outcome_counts": counts,
        "failure_reasons": reasons,
    }


def _verify(tmp_path: Path, route: str, rows: list[dict], pairs):
    algorithm, contract, classified, _score = _route(route)
    path = tmp_path / "pair-outcomes.jsonl"
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    return verify_outcome_store_integrity(
        path,
        _diagnostics(rows),
        expected_outcomes=len(pairs),
        manifest=pairs,
        algorithm_id=algorithm,
        pair_manifest_hash=MANIFEST_HASH,
        classified_failure_reasons=classified,
        outcome_contract=contract,
    )


def _store_of(route: str, pairs, **failure) -> list[dict]:
    """One scored row, and every other row carrying ``failure``."""
    algorithm, _c, _cl, score = _route(route)
    rows = [_row(pairs[0], algorithm, status="OK", raw_score=score)]
    rows += [_row(pair, algorithm, **failure) for pair in pairs[1:]]
    return rows


# =========================================================== the refusal rows


def test_R1_an_extractor_failure_blaming_the_translation(tmp_path: Path) -> None:
    """One score, the rest ``MINDTCT_FAILED_LEFT`` + ``invalid_raster_dimensions``."""
    pairs = _manifest()
    rows = _store_of(
        "openafis",
        pairs,
        status="MINDTCT_FAILED_LEFT",
        failure_code="template_extraction_failed",
        failure_reason="invalid_raster_dimensions",
    )
    with pytest.raises(Stage19ResultIntegrityError, match="different events"):
        _verify(tmp_path, "openafis", rows, pairs)


@pytest.mark.parametrize("score", [-1, 256, 255.5])
def test_R2_a_score_outside_the_openafis_contract(tmp_path: Path, score) -> None:
    """``uint8_t`` on OK and ``-1`` as the bridge's failure marker.

    The bridge prints ``score_native_type\\tuint8_t`` and documents ``-1`` on
    every status but OK, so a stored ``OK`` row carrying ``-1``, ``256`` or a
    fraction is a row the bridge cannot have produced.
    """
    pairs = _manifest()
    algorithm, _c, _cl, _s = _route("openafis")
    rows = [_row(pair, algorithm, status="OK", raw_score=score) for pair in pairs]
    with pytest.raises(Stage19ResultIntegrityError, match="score"):
        _verify(tmp_path, "openafis", rows, pairs)


def test_R3_a_match_failure_carrying_a_translation_reason(tmp_path: Path) -> None:
    """``OPENAFIS_MATCH_FAILED`` + ``invalid_raster_dimensions``.

    The matcher declining to run is open to the bridge's own free text, and that
    openness must not extend to a reason another status owns.
    """
    pairs = _manifest()
    rows = _store_of(
        "openafis",
        pairs,
        status="OPENAFIS_MATCH_FAILED",
        failure_code="matching_failed",
        failure_reason="invalid_raster_dimensions",
    )
    with pytest.raises(Stage19ResultIntegrityError, match="different events"):
        _verify(tmp_path, "openafis", rows, pairs)


def test_R4_an_extractor_failure_carrying_a_dotnet_exception(tmp_path: Path) -> None:
    """``MINDTCT_FAILED_LEFT`` + ``System.ArgumentException``.

    Unowned text, under a status whose reason is always an exit code. Closed by
    default is what refuses it.
    """
    pairs = _manifest()
    rows = _store_of(
        "mcc",
        pairs,
        status="MINDTCT_FAILED_LEFT",
        failure_code="template_extraction_failed",
        failure_reason="System.ArgumentException",
    )
    with pytest.raises(Stage19ResultIntegrityError, match="accepts only"):
        _verify(tmp_path, "mcc", rows, pairs)


def test_R5_an_input_rejection_under_the_wrong_code(tmp_path: Path) -> None:
    """``INFRASTRUCTURE_FAILURE`` + ``timeout`` + ``input_unreadable``.

    The one status whose code is a parameter rather than a constant, so
    ownership is per ``status+code``: the PNG rejections belong to
    ``input_invalid``, and a timeout cannot have read a malformed file.
    """
    pairs = _manifest()
    rows = _store_of(
        "openafis",
        pairs,
        status="INFRASTRUCTURE_FAILURE",
        failure_code="timeout",
        failure_reason="input_unreadable",
    )
    with pytest.raises(Stage19ResultIntegrityError, match="different events"):
        _verify(tmp_path, "openafis", rows, pairs)


# ========================================================== the acceptance rows


@pytest.mark.parametrize(
    "route, status, code, reason, classified",
    [
        ("mcc", "BRIDGE_FAILURE", "internal_error", "no_bridge_output", False),
        (
            "mcc",
            "MCC_TEMPLATE_REFUSAL_LEFT",
            "template_extraction_failed",
            "System.ArgumentException",
            False,
        ),
        (
            "mcc",
            "MCC_TEMPLATE_REFUSAL_LEFT",
            "template_extraction_failed",
            "invalid_raster_dimensions",
            True,
        ),
        (
            "openafis",
            "OPENAFIS_MATCH_FAILED",
            "matching_failed",
            "unreadable_bridge_output",
            False,
        ),
    ],
    ids=["A1", "A2", "A3", "A4"],
)
def test_the_accepted_rows_verify_and_are_counted_correctly(
    tmp_path: Path, route, status, code, reason, classified
) -> None:
    """A1-A4: real failures the routes produce. Accepted, and counted honestly.

    ``classified`` is a different question from ``owned``: a reason can belong
    to a status and still be one nobody has analysed. Only the translation
    refusals are classified, and only they leave ``unclassified`` at zero.
    """
    pairs = _manifest()
    rows = _store_of(
        route, pairs, status=status, failure_code=code, failure_reason=reason
    )
    integrity = _verify(tmp_path, route, rows, pairs)

    failures = len(pairs) - 1
    assert integrity.failure_reasons == {reason: failures}
    if classified:
        assert integrity.unclassified_failures == 0
    else:
        assert integrity.unclassified_failure_reasons == {reason: failures}


# ================================================== every producible row is legal


def test_every_row_the_routes_can_produce_verifies(tmp_path: Path) -> None:
    """The other direction, from the enumeration rather than from examples.

    The contract refusing an honest run is the failure mode that does not
    announce itself: nobody reports a run that could not be published. Every
    ``(status, code, reason)`` a route's own source can emit is walked here.
    """
    from fpbench.experiments.stage19a_finalization import PRODUCIBLE_OUTCOMES as OA
    from fpbench.experiments.stage20b_finalization import PRODUCIBLE_OUTCOMES as MCC

    for route, producible in (("openafis", OA), ("mcc", MCC)):
        for index, (status, code, reason) in enumerate(sorted(producible)):
            pairs = _manifest()
            rows = _store_of(
                route,
                pairs,
                status=status,
                failure_code=code,
                failure_reason=reason,
            )
            directory = tmp_path / f"{route}-{index}"
            directory.mkdir()
            try:
                _verify(directory, route, rows, pairs)
            except Stage19ResultIntegrityError as exc:
                pytest.fail(
                    f"{route} can produce ({status}, {code}, {reason}) and the "
                    f"contract refuses it: {exc}"
                )


def test_every_crossing_of_two_owning_statuses_is_refused(tmp_path: Path) -> None:
    """And the whole cross product, so the matrix is not four examples.

    Any reason owned by one ``(status, code)`` under a different one must be
    refused — that is the property R1, R3 and R5 each sample once.
    """
    from fpbench.experiments.stage19a_finalization import OUTCOME_CONTRACT

    reasons: set[str] = set()
    for shape in OUTCOME_CONTRACT.values():
        for rule in shape.codes.values():
            reasons |= rule.reasons

    checked = 0
    for reason in sorted(reasons):
        for status, shape in sorted(OUTCOME_CONTRACT.items()):
            for code, rule in sorted(shape.codes.items()):
                # The sided variants of one family share a vocabulary — which
                # template failed is the side, and the kind is the same — so a
                # pair that owns the reason itself is not a crossing.
                if rule.owns(reason):
                    continue
                pairs = _manifest(count=3)
                rows = _store_of(
                    "openafis",
                    pairs,
                    status=status,
                    failure_code=code,
                    failure_reason=reason,
                )
                directory = tmp_path / f"x{checked}"
                directory.mkdir()
                with pytest.raises(Stage19ResultIntegrityError):
                    _verify(directory, "openafis", rows, pairs)
                checked += 1
    assert checked > 40, f"only {checked} crossings were exercised"
