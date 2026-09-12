"""Metadata-only development selection. No matcher or score reader is imported."""

from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path

from common import fingerprint

COHORT_ID = "sd300_50_subjects_test_22f8d52a7478"
SELECTION_PREFIX = "l3-bridge-v1-dev\0"


def select_subjects(cohort):
    if cohort["cohort_id"] != COHORT_ID or cohort["role"] != "test":
        raise ValueError("Wrong protected cohort")
    candidates, protected = cohort["selection"]["candidate_ids"], cohort["subject_ids"]
    if (
        len(candidates) != 832
        or len(set(candidates)) != 832
        or len(protected) != 50
        or len(set(protected)) != 50
    ):
        raise ValueError("Candidate/protected counts differ from the execution brief")
    if not set(protected) <= set(candidates):
        raise ValueError("Protected cohort is not contained in the candidates")

    def rank(subject):
        return hashlib.sha256(
            (SELECTION_PREFIX + subject).encode("utf-8")
        ).hexdigest(), subject

    return sorted(set(candidates) - set(protected), key=rank)[:20]


def plan(cohort, images):
    from fpbench.datasets.sd300.filenames import parse_filename
    from fpbench.datasets.sd300.finger_mapping import resolve_position

    selected = select_subjects(cohort)
    active = selected[:5]
    by_key = {}
    for image in images:
        if image["subject_id"] not in active or image["is_multi_finger"]:
            continue
        if (
            image["dataset_id"] != "sd300"
            or image["release"] != "SD300B"
            or image["effective_ppi"] != 1000
            or image["blocking_issues"]
            or image["checksum_status"] != "verified"
        ):
            raise ValueError("Invalid native SD300B input metadata")
        parsed = parse_filename(Path(image["relative_path"]).name)
        mapped = resolve_position(parsed.impression, parsed.frgp)
        if (
            not mapped.is_known
            or mapped.is_multi_finger
            or mapped.position is None
            or int(mapped.position) != image["position"]
            or parsed.ppi != 1000
            or parsed.subject != image["subject_id"]
            or parsed.impression.value != image["impression"]
        ):
            raise ValueError("Filename and anatomical mapping disagree")
        key = image["subject_id"], image["impression"], image["position"]
        if key in by_key:
            raise ValueError("Duplicate subject/impression/finger")
        by_key[key] = image
    inputs = []
    aliases = {}
    for subject in active:
        for impression in ("plain", "roll"):
            for finger in range(1, 11):
                image = by_key[(subject, impression, finger)]
                alias = f"image-{len(inputs):03d}"
                aliases[(subject, impression, finger)] = alias
                inputs.append(
                    {
                        k: image[k]
                        for k in (
                            "image_id",
                            "subject_id",
                            "impression",
                            "position",
                            "relative_path",
                            "expected_sha256",
                            "effective_ppi",
                        )
                    }
                    | {"alias": alias}
                )
    pairs = []
    for kind in ("genuine", "impostor"):
        for left in active:
            for right in active:
                if (left == right) != (kind == "genuine"):
                    continue
                for finger in range(1, 11):
                    pair = {
                        "kind": kind,
                        "left": aliases[(left, "plain", finger)],
                        "right": aliases[(right, "roll", finger)],
                        "finger": finger,
                    }
                    pair["pair_id"] = "l3b-" + fingerprint(pair)[:20]
                    pairs.append(pair)
    if len(inputs) != 100 or Counter(p["kind"] for p in pairs) != {
        "genuine": 50,
        "impostor": 200,
    }:
        raise ValueError("First execution must have exactly 100 images and 250 pairs")
    return {
        "schema": "l3_bridge_v1_plan",
        "role": "development",
        "selected_subjects": selected,
        "active_subjects": active,
        "protected_overlap": [],
        "candidate_count": 832,
        "eligible_outside_protected": 782,
        "selection_prefix": SELECTION_PREFIX,
        "selection_rule": "ascending SHA256(UTF8(prefix + subject_id)), then subject_id; first 20, execute first 5",
        "images": inputs,
        "pairs": pairs,
        "examples": [
            next(p["pair_id"] for p in pairs if p["kind"] == kind)
            for kind in ("genuine", "impostor")
        ],
    }
