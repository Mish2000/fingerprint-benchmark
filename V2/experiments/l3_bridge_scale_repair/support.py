"""Bindings and recoverable local source snapshots for the bounded repair."""

from __future__ import annotations

import csv
import difflib
import shutil
import subprocess
import sys
import zipfile
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
V1 = HERE.parent / "l3_bridge_v1"
sys.path.insert(0, str(V1))

from common import digest, fingerprint, native_xy, read_json, validate_xy, write_json
from pore_worker import read_image, runtime
from report import inspect as inspect_v1
from run import check_ignored_output, git, verify_assets

__all__ = [
    "HERE",
    "ROOT",
    "V1",
    "bind_prior",
    "check_ignored_output",
    "copy_new",
    "digest",
    "fingerprint",
    "freeze_source",
    "git",
    "inspect_v1",
    "native_xy",
    "read_image",
    "read_json",
    "runtime",
    "train_records",
    "validate_xy",
    "verify_assets",
    "verify_preserved",
    "verify_source",
    "write_csv",
    "write_json",
]


def write_csv(path, rows):
    if not rows:
        raise ValueError("Cannot silently produce an empty table")
    with path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def verify_preserved(out):
    files = read_json(out / "preserved_files.json")
    changed = [
        p for p, sha in files.items() if not Path(p).is_file() or digest(Path(p)) != sha
    ]
    if changed:
        raise ValueError(
            f"Preserved predecessor/source/evidence changed: {changed[:5]}"
        )
    return len(files)


def freeze_source(out, settings):
    """Archive actual bytes, including uncommitted additions, before estimates.

    This task's explicit no-commit instruction is confined to the local repair;
    neither ADR 0017 nor any existing research runner is given an override.
    """
    if git(ROOT, "rev-parse", "HEAD") != settings["base_revision"]:
        raise ValueError("Unexpected base revision")
    paths = set(HERE.glob("*.py")) | set(HERE.glob("*.json"))
    paths |= set(V1.glob("*.py")) | set(V1.glob("*.json"))
    changed = git(ROOT, "diff", "--name-only", "HEAD").splitlines()
    changed += git(ROOT, "ls-files", "--others", "--exclude-standard").splitlines()
    allowed = {
        "README.md",
        "docs/adr/README.md",
        "docs/adr/0142-l3-scale-repair-is-a-separate-development-variant.md",
        "tests/unit/test_l3_bridge_scale_repair.py",
    }
    for name in changed:
        if name not in allowed and not name.startswith(
            "V2/experiments/l3_bridge_scale_repair/"
        ):
            raise ValueError(f"Unrelated working change cannot enter this run: {name}")
        paths.add(ROOT / name)
    files = {p.relative_to(ROOT).as_posix(): digest(p) for p in sorted(paths)}
    archive = out / "source_snapshot.zip"
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as z:
        for relative in files:
            z.write(ROOT / relative, relative)
    patch = []
    for name in sorted(set(changed)):
        previous = subprocess.run(
            ["git", "show", f"HEAD:{name}"], cwd=ROOT, capture_output=True, check=False
        )
        before = (
            previous.stdout.decode("utf-8").splitlines(keepends=True)
            if previous.returncode == 0
            else []
        )
        after = (ROOT / name).read_text(encoding="utf-8").splitlines(keepends=True)
        patch.extend(
            difflib.unified_diff(
                before, after, fromfile=f"a/{name}", tofile=f"b/{name}"
            )
        )
    (out / "implementation.patch").write_text(
        "".join(patch), encoding="utf-8", newline="\n"
    )
    snapshot = {
        "schema": "l3_repair_local_source_snapshot_v1",
        "base_revision": settings["base_revision"],
        "source_clean": False,
        "execution_source": "archived working bytes, not the base commit alone",
        "authorization": "User requested this local continuation without commits",
        "files": files,
        "source_fingerprint": fingerprint(files),
        "archive_sha256": digest(archive),
        "patch_sha256": digest(out / "implementation.patch"),
    }
    write_json(out / "source_snapshot.json", snapshot)
    verify_source(out)
    return snapshot


def verify_source(out):
    snapshot = read_json(out / "source_snapshot.json")
    if git(ROOT, "rev-parse", "HEAD") != snapshot["base_revision"]:
        raise ValueError("Revision changed during the repair")
    for relative, sha in snapshot["files"].items():
        if digest(ROOT / relative) != sha:
            raise ValueError(f"Execution source changed after snapshot: {relative}")
    if digest(out / "source_snapshot.zip") != snapshot["archive_sha256"]:
        raise ValueError("Recoverable source archive changed")
    return snapshot


def bind_prior(prior, local, settings):
    if digest(prior / "plan.json") != settings["plan_sha256"]:
        raise ValueError("The specified predecessor plan is not present")
    plan, routes = inspect_v1(prior)
    if set(routes) != {"P1", "P2", "R"}:
        raise ValueError("All original routes must be available for verification")
    from analysis import validate_pairs

    validate_pairs(plan["pairs"])
    if len(plan["images"]) != 100 or len(plan["active_subjects"]) != 5:
        raise ValueError("The bounded predecessor population changed")
    old_settings = read_json(prior / "settings.json")
    prepared = read_json(prior / "prepared.json")
    for name, key in (
        ("settings.json", "settings_sha256"),
        ("worker-inputs.json", "inputs_sha256"),
        ("worker-pairs.json", "pairs_sha256"),
    ):
        if digest(prior / name) != prepared[key]:
            raise ValueError(f"Predecessor binding changed: {name}")
    cohort_path = (
        Path(local["workspace"])
        / "manifests/protocols/sd300_50_subjects/cohorts"
        / plan["sources"]["cohort_id"]
        / "cohort.json"
    )
    if digest(cohort_path) != old_settings["cohort_sha256"]:
        raise ValueError("Protected cohort identity changed")
    protected = set(read_json(cohort_path)["subject_ids"])
    if protected & set(plan["active_subjects"]) or plan["protected_overlap"]:
        raise ValueError("Development population touches protected subjects")
    inputs = read_json(prior / "worker-inputs.json")
    if [i["alias"] for i in inputs] != [i["alias"] for i in plan["images"]]:
        raise ValueError("Predecessor image order changed")
    for item, planned in zip(inputs, plan["images"], strict=True):
        if item["sha256"] != planned["expected_sha256"]:
            raise ValueError("Predecessor input checksum differs from plan")
        native = (Path(local["data_root"]) / planned["relative_path"]).resolve()
        if not native.is_relative_to(Path(local["data_root"]).resolve()):
            raise ValueError("Native path escaped the dataset root")
        if (
            digest(native) != item["sha256"]
            or digest(Path(item["path"])) != item["sha256"]
        ):
            raise ValueError("Original native/prepared pixels changed")
    blinded = [{k: p[k] for k in ("pair_id", "left", "right")} for p in plan["pairs"]]
    if read_json(prior / "worker-pairs.json") != blinded:
        raise ValueError("Blinded pairs differ from the original plan")
    for route in routes:
        identity = read_json(prior / route / "identity.json")
        if (
            identity["settings"] != old_settings
            or identity["source_revision"] != settings["predecessor_execution_revision"]
        ):
            raise ValueError(
                "Original route identity differs from the declared execution"
            )
    verify_assets(local, old_settings, "P2")
    return plan, routes, old_settings, inputs


def train_records(method, settings):
    """Check the original split's metadata; open pixels only for TRAIN later."""
    from fingerprint_new_method.experiment004 import canonical_json_sha256

    directory = method / "artifacts/experiment-004"
    split_path = directory / "split_manifest.json"
    if digest(split_path) != settings["split_manifest_sha256"]:
        raise ValueError("Original training split bytes changed")
    split = read_json(split_path)
    if (
        canonical_json_sha256({k: v for k, v in split.items() if k != "content_sha256"})
        != split["content_sha256"]
    ):
        raise ValueError("Split content checksum mismatch")
    protocol = read_json(directory / "model_protocol.json")
    if canonical_json_sha256(split) != protocol["split_manifest_sha256"]:
        raise ValueError("Training protocol/split binding mismatch")
    images = split["images"]
    if len({i["canonical_image_id"] for i in images}) != 740:
        raise ValueError("Duplicate or missing split image identities")
    if Counter(i["partition"] for i in images) != {
        "train": 440,
        "validation": 150,
        "test": 150,
    }:
        raise ValueError("Original partition counts changed")
    groups = {g["group_id"]: g for g in split["groups"]}
    if len(groups) != 148 or Counter(g["partition"] for g in groups.values()) != {
        "train": 88,
        "validation": 30,
        "test": 30,
    }:
        raise ValueError("Original group counts changed")
    for group in groups.values():
        members = [i for i in images if i["group_id"] == group["group_id"]]
        if (
            sorted(i["run"] for i in members) != ["R1", "R2", "R3", "R4", "R5"]
            or {i["canonical_image_id"] for i in members}
            != set(group["canonical_image_ids"])
            or any(i["partition"] != group["partition"] for i in members)
        ):
            raise ValueError("Split leakage or group membership mismatch")
    records = [i for i in images if i["partition"] == "train"]
    train_hashes = {i["image_sha256"] for i in records}
    if train_hashes & {i["image_sha256"] for i in images if i["partition"] != "train"}:
        raise ValueError("Byte-identical image crosses the training boundary")
    original = read_json(directory / "ridge_period_train_estimates.json")
    if [i["canonical_image_id"] for i in records] != [
        i["canonical_image_id"] for i in original["per_image"]
    ]:
        raise ValueError("TRAIN population differs from historical target population")
    if (
        canonical_json_sha256(
            {k: v for k, v in original.items() if k != "content_sha256"}
        )
        != original["content_sha256"]
    ):
        raise ValueError("Historical training estimates checksum mismatch")
    model = read_json(directory / "model_manifest.json")
    if (
        original["content_sha256"]
        != model["frozen_inference"]["ridge_scale"]["train_estimates_sha256"]
    ):
        raise ValueError("Historical target is not model-bound")
    return records


def copy_new(source, target):
    with source.open("rb") as src, target.open("xb") as dst:
        shutil.copyfileobj(src, dst)
