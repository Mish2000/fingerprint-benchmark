"""The reviewer's acceptance matrix, at full scale against the real manifest.

``tests/regression/test_stage19_outcome_matrix.py`` holds the same table over a
nine-pair manifest, because every row states a property of a *row*. This runs it
over the 6,000 canonical pairs, which is the shape the scenarios were posed in
and the one that catches anything that only appears at size — a count that
overflows, a diagnostics document that has to agree, a store big enough to be
read in chunks.

It needs the canonical pair manifest under ``workspace/``, so it is a script and
not a test: the repository's test suite must run on a checkout with no dataset.

Usage::

    python scripts/stage19_acceptance_matrix.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from fpbench.experiments.stage19_pair_manifest import (  # noqa: E402
    load_canonical_pair_manifest,
    pairs_path_for,
)
from fpbench.experiments.stage19_result_integrity import (  # noqa: E402
    Stage19ResultIntegrityError,
    verify_outcome_store_integrity,
)

OPENAFIS = "nbis_mindtct_openafis"
MCC = "nbis_mindtct_mcc_sdk_v2"


def _route(name: str):
    if name == "openafis":
        from fpbench.experiments.stage19a_finalization import (
            CLASSIFIED_FAILURE_REASONS,
            OUTCOME_CONTRACT,
        )

        return OPENAFIS, OUTCOME_CONTRACT, CLASSIFIED_FAILURE_REASONS, 42
    from fpbench.experiments.stage20b_finalization import (
        CLASSIFIED_FAILURE_REASONS,
        OUTCOME_CONTRACT,
    )

    return MCC, OUTCOME_CONTRACT, CLASSIFIED_FAILURE_REASONS, 0.5


def _row(pair, algorithm, **overrides):
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


def _diagnostics(rows):
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


def _verify(directory, route, rows, pairs, manifest_hash):
    algorithm, contract, classified, _score = _route(route)
    path = Path(directory) / "pair-outcomes.jsonl"
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
        pair_manifest_hash=manifest_hash,
        classified_failure_reasons=classified,
        outcome_contract=contract,
    )


def main() -> int:
    manifest = load_canonical_pair_manifest(
        pairs_path_for(
            REPOSITORY_ROOT / "workspace",
            "sd300_50_subjects",
            "sd300_50_subjects_test_22f8d52a7478",
        )
    )
    pairs = manifest.pairs
    manifest_hash = manifest.pair_manifest_hash
    tmp = Path(tempfile.mkdtemp())
    print(f"manifest: {len(pairs)} pairs\n")

    def rows_of(route, **failure):
        algorithm, _c, _cl, score = _route(route)
        out = [_row(pairs[0], algorithm, status="OK", raw_score=score)]
        out += [_row(pair, algorithm, **failure) for pair in pairs[1:]]
        return out

    refusals = [
        ("R1", "openafis", rows_of(
            "openafis", status="MINDTCT_FAILED_LEFT",
            failure_code="template_extraction_failed",
            failure_reason="invalid_raster_dimensions")),
        ("R3", "openafis", rows_of(
            "openafis", status="OPENAFIS_MATCH_FAILED",
            failure_code="matching_failed",
            failure_reason="invalid_raster_dimensions")),
        ("R4", "mcc", rows_of(
            "mcc", status="MINDTCT_FAILED_LEFT",
            failure_code="template_extraction_failed",
            failure_reason="System.ArgumentException")),
        ("R5", "openafis", rows_of(
            "openafis", status="INFRASTRUCTURE_FAILURE",
            failure_code="timeout", failure_reason="input_unreadable")),
    ]
    for score in (-1, 256, 255.5):
        refusals.append(
            (
                f"R2 score={score}",
                "openafis",
                [_row(pair, OPENAFIS, status="OK", raw_score=score) for pair in pairs],
            )
        )

    failures = 0
    for index, (label, route, rows) in enumerate(refusals):
        directory = tmp / f"refuse{index}"
        directory.mkdir()
        try:
            _verify(directory, route, rows, pairs, manifest_hash)
        except Stage19ResultIntegrityError as exc:
            print(f"{label:16s} REFUSED  {str(exc).split(': ', 1)[-1][:96]}")
        else:
            print(f"{label:16s} !! ACCEPTED")
            failures += 1

    accepted = [
        ("A1", "mcc", "BRIDGE_FAILURE", "internal_error", "no_bridge_output", False),
        ("A2", "mcc", "MCC_TEMPLATE_REFUSAL_LEFT", "template_extraction_failed",
         "System.ArgumentException", False),
        ("A3", "mcc", "MCC_TEMPLATE_REFUSAL_LEFT", "template_extraction_failed",
         "invalid_raster_dimensions", True),
        ("A4", "openafis", "OPENAFIS_MATCH_FAILED", "matching_failed",
         "unreadable_bridge_output", False),
    ]
    print()
    for index, (label, route, status, code, reason, classified) in enumerate(accepted):
        directory = tmp / f"accept{index}"
        directory.mkdir()
        rows = rows_of(route, status=status, failure_code=code, failure_reason=reason)
        try:
            integrity = _verify(directory, route, rows, pairs, manifest_hash)
        except Stage19ResultIntegrityError as exc:
            print(f"{label:16s} !! REFUSED  {exc}")
            failures += 1
            continue
        unclassified = integrity.unclassified_failures
        expected = 0 if classified else len(pairs) - 1
        ok = "  " if unclassified == expected else "!!"
        print(
            f"{label:16s} ACCEPTED  score_bearing={integrity.score_bearing} "
            f"unclassified={unclassified} {ok}"
        )
        failures += unclassified != expected

    print()
    print("FAILURES:", failures)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
