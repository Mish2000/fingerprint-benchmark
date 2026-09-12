"""Repair-policy and descriptive-rate contracts without data or model runtimes."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

DIRECTORY = (
    Path(__file__).resolve().parents[2] / "V2/experiments/l3_bridge_scale_repair"
)
spec = importlib.util.spec_from_file_location(
    "l3_repair_analysis", DIRECTORY / "analysis.py"
)
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)


def rows(genuine, impostor):
    result = []
    for kind, scores, total in (("genuine", genuine, 50), ("impostor", impostor, 200)):
        for i in range(total):
            score = scores[i] if i < len(scores) else None
            result.append(
                {
                    "pair_id": f"{kind}-{i}",
                    "kind": kind,
                    "score": score,
                    "status": "failure" if score is None else "success",
                }
            )
    return result


def test_ties_cannot_be_split_to_meet_far():
    result = analysis.descriptive_points(rows([10] * 50, [10] * 3 + [0] * 197))
    one, five = result["points"]
    assert (one["TA"], one["FA"], one["accept_none"]) == (0, 0, True)
    assert (five["TA"], five["FA"], five["cut"]) == (50, 3, 10)


def test_failures_keep_attempt_denominators_and_are_not_matcher_rejections():
    result = analysis.descriptive_points(rows([10, 10, 1], [10, 0]))
    for point in result["points"]:
        assert (point["TA"], point["FA"], point["cut"]) == (3, 1, 1)
        assert (point["TAR"], point["FAR"], point["FRR"]) == (3 / 50, 1 / 200, 47 / 50)
        assert point["matcher_rejected_genuine"] == 0 and point["failed_genuine"] == 47
    assert result["coverage"]["impostor"]["failure"] == 198


def test_equal_tar_prefers_smaller_far_then_higher_cut():
    result = analysis.descriptive_points(rows([12], [11, 10, 0]))
    for point in result["points"]:
        assert (point["TA"], point["FA"], point["cut"]) == (1, 0, 12)


def test_zero_is_a_score_but_absent_class_is_unsupported():
    result = analysis.descriptive_points(rows([0], [-1]))
    assert result["points"][0]["cut"] == 0
    assert result["coverage"]["genuine"]["success"] == 1
    unsupported = analysis.descriptive_points(rows([], [10]))
    assert unsupported["status"] == "unsupported" and unsupported["points"] == []


def test_failures_cannot_acquire_zero_and_missing_pairs_are_rejected():
    data = rows([5], [3])
    data[-1]["score"] = 0
    with pytest.raises(ValueError, match="Failure cannot carry a score"):
        analysis.descriptive_points(data)
    with pytest.raises(ValueError, match="250 unique"):
        analysis.descriptive_points(data[:-1])


def test_scale_bands_keep_separate_eligibility_without_clipping():
    estimate = {"status": "OK", "period_px": 20}
    main = analysis.scale_policy(estimate, 34.0, (0.2, 1.5))
    wide = analysis.scale_policy(estimate, 34.0, (0.2, 3.0))
    assert main["status"] == "PREPROCESSING_FAILURE" and main["factor"] == 1.7
    assert wide["status"] == "OK" and wide["factor"] == 1.7
    failed = analysis.scale_policy(
        {"status": "UNRELIABLE_DISPERSION", "period_px": None}, 34, (0.2, 3)
    )
    assert failed["factor"] is None and failed["reason"] == "UNRELIABLE_DISPERSION"


@pytest.mark.parametrize("factor", [0.2, 1.5])
def test_frozen_band_endpoints_remain_inclusive(factor):
    assert (
        analysis.scale_policy(
            {"status": "OK", "period_px": 20}, 20 * factor, (0.2, 1.5)
        )["status"]
        == "OK"
    )


def test_exact_predeclared_scope_has_only_two_inference_policies():
    settings = json.loads((DIRECTORY / "settings.json").read_text())
    assert settings["train_images"] == 440 and settings["train_groups"] == 88
    assert settings["policies"] == {
        "rotation-only": {"target": 34.0, "band": [0.2, 1.5], "inference": False},
        "P2R": {"target": "T_train_fixed", "band": [0.2, 1.5], "inference": True},
        "P2R-wide": {"target": "T_train_fixed", "band": [0.2, 3.0], "inference": True},
    }
    assert settings["descriptive_far_targets"] == ["0.01", "0.05"]
    assert settings["denominators"] == {"genuine": 50, "impostor": 200}
