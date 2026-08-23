"""Z1: a run that scored nothing is written down, and establishes nothing.

ADR 0128 says a result set with no score is not a raw matcher's output. What the
three stages did with that was three different things: 19A published
``RAW_COMPLETE`` with ``established: null``, 19B published ``RAW_COMPLETE`` with
``established: false``, and 20B raised and wrote no marker at all. One policy,
three behaviours, and two of them said the run was complete.

The line the stages now draw:

* the **validator** refuses a store no run could have produced — no marker,
  because there is nothing to record;
* a **machine condition** that comes out false is a real run that concluded
  nothing — full evidence, a ``..._RAW_NOT_COMPLETE`` outcome,
  ``failed_conditions`` naming what was not met, and nothing established.

The second is the part that was missing, and it is the part that matters: a run
of six thousand honest capacity failures is a finding about the route, and
throwing it away loses the finding.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

#: A binding for a run in which every comparison failed for a reason the route
#: has classified — legal, complete, and with nothing in the score column.
_ZERO_SCORE = {
    "expected_outcomes": 6000,
    "stored_outcomes": 6000,
    "unique_pair_ids": 6000,
    "unique_ordinals": 6000,
    "diagnostic_comparisons": 6000,
    "missing": 0,
    "outcome_store_sha256": "a" * 64,
    "outcome_counts": {"OPENAFIS_TEMPLATE_FAILED_LEFT": 6000},
    "failure_reasons": {"invalid_raster_dimensions": 6000},
    "unclassified_failures": 0,
    "capacity_failures_remaining": 0,
    "score_bearing": 0,
    "preparation_set_id": "prepset_be560e047991",
    "pair_manifest_hash": "e" * 64,
    "nbis_build_id": "658f9f54a8f2",
    "cross_impression": {},
}


def _stage19a(binding: dict) -> dict:
    from fpbench.experiments.stage19a_finalization import build_stage19a_finalization

    return build_stage19a_finalization(
        repository_root=REPOSITORY_ROOT,
        binding=binding,
        diagnostics={},
        evidence_hashes={},
        created_utc="2026-08-23T00:00:00Z",
    )


def _stage19b(binding: dict) -> dict:
    from fpbench.experiments.stage19b_finalization import build_stage19b_finalization

    return build_stage19b_finalization(
        repository_root=REPOSITORY_ROOT,
        gate_a={
            "outcome": "CAPACITY_EXTENSION_INERTNESS_PASS",
            "score_mismatches": 0,
            "status_regressions": 0,
            "exact_score_matches": 1583,
            "baseline_scored_pairs": 1583,
        },
        binding=binding,
        translator_inertness={"mismatches": 0, "lower_bound_still_enforced": True},
        evidence_hashes={},
        created_utc="2026-08-23T00:00:00Z",
    )


def _stage20b(binding: dict) -> dict:
    from fpbench.experiments import stage20b_identity as frozen
    from fpbench.experiments.stage20b_finalization import (
        GATE_A_PASS,
        GATE_B_PASS,
        build_stage20b_finalization,
    )

    integrity = {
        "every_attempt_stored": True,
        "duplicate_pair_ids": 0,
        "ordinals_are_complete": True,
        "ordinals_are_the_manifest_order": True,
        "algorithm_ids_present": [frozen.ALGORITHM_ID],
        "scores_outside_contract": 0,
        "failures_recorded_as_zero": 0,
        "successes_recorded_without_a_score": 0,
        "score_bearing": binding["score_bearing"],
    }
    mcc_binding = dict(binding)
    mcc_binding["pair_manifest_hash"] = frozen.REFERENCE_PAIR_MANIFEST_HASH
    mcc_binding.setdefault("pairs_regenerated", False)
    mcc_binding.setdefault("pair_order_changed", False)
    mcc_binding.setdefault("dataset_changed", False)
    mcc_binding.setdefault("calibration_performed", False)
    mcc_binding.setdefault("threshold_applied", None)
    return build_stage20b_finalization(
        repository_root=REPOSITORY_ROOT,
        gate_a={"outcome": GATE_A_PASS, "mismatches": 0},
        gate_b={"outcome": GATE_B_PASS, "mismatches": 0},
        binding=mcc_binding,
        integrity=integrity,
        diagnostics={"failure_reasons": binding["failure_reasons"]},
        evidence_hashes={},
        created_utc="2026-08-23T00:00:00Z",
    )


_STAGES = {"19A": _stage19a, "19B": _stage19b, "20B": _stage20b}


@pytest.mark.parametrize("label", sorted(_STAGES))
def test_a_zero_score_run_produces_a_marker(label: str) -> None:
    """It used to raise in 20B, which lost the run rather than recording it."""
    marker = _STAGES[label](dict(_ZERO_SCORE))
    assert marker["kind"].startswith("stage_")
    assert marker["created_utc"] == "2026-08-23T00:00:00Z"


@pytest.mark.parametrize("label", sorted(_STAGES))
def test_a_zero_score_run_is_not_complete(label: str) -> None:
    marker = _STAGES[label](dict(_ZERO_SCORE))
    assert marker["outcome"].endswith("_RAW_NOT_COMPLETE"), marker["outcome"]


@pytest.mark.parametrize("label", sorted(_STAGES))
def test_a_zero_score_run_names_what_it_failed(label: str) -> None:
    marker = _STAGES[label](dict(_ZERO_SCORE))
    assert "at_least_one_score" in marker["failed_conditions"]


@pytest.mark.parametrize("label", sorted(_STAGES))
def test_a_zero_score_run_establishes_nothing(label: str) -> None:
    """Including 19A, whose human determination is separately ``null``.

    A machine condition that is false decides the conjunction: ``null`` means
    nobody has ruled on the *last* condition, not that the ones already ruled on
    can be set aside.
    """
    marker = _STAGES[label](dict(_ZERO_SCORE))
    assert marker.get("publication_eligible") is False
    if "algorithm_5_established" in marker:
        assert marker["algorithm_5_established"] is False
    if "opens_common_calibration" in marker:
        assert marker["opens_common_calibration"] is False
    if "preferred_final_fifth" in marker:
        assert marker["preferred_final_fifth"] is not True


def test_stage19a_keeps_the_human_determination_separate() -> None:
    """The condition stays ``null``; only the conclusion is decided."""
    marker = _stage19a(dict(_ZERO_SCORE))
    conditions = marker["algorithm_5_conditions"]
    assert conditions["substantial_cross_impression_score_bearing"] is None
    assert conditions["at_least_one_score"] is False
    assert marker["algorithm_5_established"] is False


def test_a_scoring_run_is_unaffected() -> None:
    """The positive control: nothing about a real run changed."""
    binding = dict(_ZERO_SCORE)
    binding["score_bearing"] = 6000
    binding["outcome_counts"] = {"OK": 6000}
    binding["failure_reasons"] = {}
    for label, build in sorted(_STAGES.items()):
        marker = build(dict(binding))
        assert marker["failed_conditions"] == [], (label, marker["failed_conditions"])
        assert marker["outcome"].endswith("_RAW_COMPLETE"), (label, marker["outcome"])


def test_a_structural_defect_is_recorded_rather_than_raised() -> None:
    """The other half of the same policy, in the stage that used to raise.

    Six thousand copies of one pair is a store the validator refuses outright.
    A *binding* that fails a structural requirement — reached, say, from an
    older integrity document — is a run that happened and concluded nothing, so
    it is written down with the requirement it missed.
    """
    binding = dict(_ZERO_SCORE)
    binding["score_bearing"] = 6000
    binding["outcome_counts"] = {"OK": 6000}
    binding["failure_reasons"] = {}
    binding["missing"] = 4

    marker = _stage20b(binding)
    assert marker["outcome"].endswith("_RAW_NOT_COMPLETE")
    assert "canonical_run_complete" in marker["failed_conditions"]
    assert marker["unmet_structural_requirements"]["missing"] == {
        "found": 4,
        "required": 0,
    }
    assert marker["publication_eligible"] is False
