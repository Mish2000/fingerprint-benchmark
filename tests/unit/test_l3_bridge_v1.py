"""The bridge pilot's population and reporting contracts use synthetic records."""

import copy
import json
import sys
from pathlib import Path

import pytest

BRIDGE = Path(__file__).resolve().parents[2] / "V2/experiments/l3_bridge_v1"
sys.path.insert(0, str(BRIDGE))
from common import native_xy, score_sweep, survey_xy, validate_xy, write_json
from protocol import COHORT_ID, plan, select_subjects
from run import collect


def cohort():
    return {
        "cohort_id": COHORT_ID,
        "role": "test",
        "subject_ids": [f"{i:08d}" for i in range(50)],
        "selection": {"candidate_ids": [f"{i:08d}" for i in range(832)]},
    }


def images(c):
    rows = []
    for subject in select_subjects(c)[:5]:
        for impression in ("plain", "roll"):
            for finger in range(1, 11):
                frgp = (
                    {1: 11, 6: 12}.get(finger, finger)
                    if impression == "plain"
                    else finger
                )
                rows.append(
                    {
                        "image_id": f"{subject}-{impression}-{finger}",
                        "subject_id": subject,
                        "impression": impression,
                        "position": finger,
                        "dataset_id": "sd300",
                        "release": "SD300B",
                        "relative_path": f"sd300b/images/1000/png/{impression}/{subject}_{impression}_1000_{frgp:02d}.png",
                        "is_multi_finger": False,
                        "effective_ppi": 1000,
                        "checksum_status": "verified",
                        "blocking_issues": [],
                        "expected_sha256": "0" * 64,
                    }
                )
    return rows


def test_deterministic_subject_selection_and_complete_directed_pairs():
    c = cohort()
    selected = select_subjects(c)
    c["selection"]["candidate_ids"].reverse()
    assert select_subjects(c) == selected
    assert len(selected) == 20 and not set(selected) & set(c["subject_ids"])
    doc = plan(c, images(c))
    assert doc["active_subjects"] == selected[:5]
    assert len(doc["images"]) == 100 and len(doc["pairs"]) == 250
    assert len({p["pair_id"] for p in doc["pairs"]}) == 250
    lookup = {r["alias"]: r for r in doc["images"]}
    for pair in doc["pairs"]:
        left, right = (lookup[pair[s]] for s in ("left", "right"))
        assert left["impression"] == "plain" and right["impression"] == "roll"
        assert left["position"] == right["position"]
        assert (left["subject_id"] == right["subject_id"]) == (
            pair["kind"] == "genuine"
        )
    assert sum(p["kind"] == "impostor" for p in doc["pairs"]) == 200
    assert all(
        sum(p[side] == r["alias"] for p in doc["pairs"]) == 5
        for r in doc["images"]
        for side in ["left" if r["impression"] == "plain" else "right"]
    )


def test_wrong_thumb_duplicate_missing_and_reserved_role_refused():
    c = cohort()
    data = images(c)
    wrong = copy.deepcopy(data)
    wrong[0]["position"] = 6
    with pytest.raises(ValueError, match="mapping"):
        plan(c, wrong)
    with pytest.raises(ValueError, match="Duplicate"):
        plan(c, data + [data[0]])
    with pytest.raises(KeyError):
        plan(c, data[:-1])
    c["role"] = "development"
    with pytest.raises(ValueError, match="protected"):
        select_subjects(c)


def test_ties_move_together_including_zero_and_endpoints():
    rows = score_sweep([0, 0], [0, 0])
    assert len(rows) == 2
    assert rows[0]["accept_none"] and rows[0]["far"] == 0
    assert rows[1] == {
        "threshold": 0,
        "accept_none": False,
        "tar": 1,
        "far": 1,
        "frr": 0,
    }
    assert score_sweep([3, 2, 2], [2, 1]) == score_sweep([2, 3, 2], [1, 2])
    with pytest.raises(ValueError):
        score_sweep([float("nan")], [1])
    assert score_sweep([], [0]) == []


def test_coordinates_non_square_and_resize_pixel_centres():
    assert survey_xy([(10, 80)]) == [(80, 10)]
    validate_xy(survey_xy([(10, 80)]), 20, 100)
    with pytest.raises(ValueError):
        validate_xy([(10, 80)], 20, 100)
    assert native_xy([(10.5, 20.5)], 2) == [(5, 10)]
    with pytest.raises(ValueError):
        native_xy([(1, 2)], 0)


def test_zero_failure_and_blocked_keep_all_planned_rows(tmp_path):
    doc = plan(cohort(), images(cohort()))
    directory = tmp_path / "P1"
    (directory / "pairs").mkdir(parents=True)
    write_json(directory / "identity.json", {"route": "P1"})
    for pair, status, score, reason in zip(
        doc["pairs"][:2], ["success", "failure"], [0.0, None], [None, "RUNTIME_ERROR"]
    ):
        write_json(
            directory / "pairs" / (pair["pair_id"] + ".json"),
            {
                "status": status,
                "score": score,
                "reason": reason,
                "matcher_invoked": True,
            },
        )
    summary = collect("P1", tmp_path, directory, doc, "MISSING_RUNTIME")
    assert {
        k: summary[k] for k in ("planned", "executed", "scored", "failures", "blocked")
    } == {"planned": 250, "executed": 2, "scored": 1, "failures": 1, "blocked": 248}
    assert summary["score_distributions_scored_only"]["genuine"]["median"] == 0
    import csv

    rows = list(csv.DictReader((directory / "scores.csv").open()))
    assert len(rows) == 250 and rows[0]["score"] == "0.0" and rows[1]["score"] == ""


def test_results_cannot_be_overwritten(tmp_path):
    path = tmp_path / "result.json"
    write_json(path, {"score": 0})
    with pytest.raises(FileExistsError):
        write_json(path, {"score": 1})
    assert json.loads(path.read_text()) == {"score": 0}
