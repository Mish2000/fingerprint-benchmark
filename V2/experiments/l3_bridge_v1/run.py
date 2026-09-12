"""Prepare, execute one bounded route, and report the local L3 bridge pilot."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import statistics
import subprocess
import sys
import time
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "src"))

from common import digest, read_json, score_sweep, write_json
from protocol import COHORT_ID, plan

COHORT = (
    Path("manifests/protocols/sd300_50_subjects/cohorts") / COHORT_ID / "cohort.json"
)
IMAGES = Path("manifests/datasets/sd300/SD300B/images.parquet")
P2_WEIGHT = "artifacts/experiment-004/local-large/checkpoints/seed-40401/best.pt"
P2_SHA = "06ce96be30f336b48ee19f9107cbd19c83f2b4253dc1aa62440f84f43b60cfcb"


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def check_ignored_output(out):
    out = out.resolve()
    if not out.is_relative_to(ROOT / "workspace"):
        raise ValueError("Local biometric outputs must be inside the ignored workspace")
    if subprocess.run(
        ["git", "check-ignore", "-q", str(out / "inputs" / "probe.npz")],
        cwd=ROOT,
        check=False,
    ).returncode:
        raise ValueError("Output is not ignored by Git")


def pins(local):
    """Read artifact identities only; called once before the execution commit."""
    paths = {key: Path(value) for key, value in local.items()}
    result = {
        "schema": "l3_bridge_v1_settings",
        "variant": "native-coordinate-corrected-v1",
        "routes": {
            "P1": "Survey FCN f40 -> Dahia SIFT -> spatial",
            "P2": "Experiment 004 seed40401 frozen scale -> native coordinates -> same Dahia SIFT -> spatial",
            "R": "existing SourceAFIS Java bridge, native SD300B at 1000 PPI",
        },
        "P1": {
            "features": 40,
            "window": 17,
            "nms_probability": 0.65,
            "nms_iou": 0.2,
            "output_tile": 256,
            "input_overlap": 16,
            "device": "cpu",
            "torch_threads": 4,
        },
        "shared_descriptor_matcher": {
            "sift_scale": 4,
            "median_blur": 3,
            "clahe_clip": 3,
            "ratio_threshold_on_squared_distance": 0.7,
            "opencv": "3.4.18",
        },
        "external": {},
    }
    groups = {
        "survey_dir": [
            "util/utils.py",
            "entireImage.py",
            "out_of_the_box_detect/models/40",
        ]
        + [
            p.relative_to(paths["survey_dir"]).as_posix()
            for p in sorted((paths["survey_dir"] / "architectures").glob("*.py"))
        ],
        "dahia_dir": ["utils.py", "matching.py"],
        "method_dir": [
            "src/fingerprint_new_method/" + p
            for p in (
                "__init__.py",
                "paths.py",
                "experiment004.py",
                "experiment004_model.py",
                "experiment004_transfer.py",
            )
        ]
        + ["artifacts/experiment-004/model_manifest.json", P2_WEIGHT],
    }
    for key, relatives in groups.items():
        base = paths[key]
        if base.is_relative_to(ROOT):
            raise ValueError(
                "Third-party source/weights must stay outside this repository"
            )
        result["external"][key] = {
            "revision": git(base, "rev-parse", "HEAD"),
            "files": {p: digest(base / p) for p in relatives},
        }
    weight = paths["method_dir"] / P2_WEIGHT
    if digest(weight) != P2_SHA or weight.stat().st_size != 28986281:
        raise ValueError("P2 is not the requested seed40401 checkpoint")
    result["P2"] = read_json(
        paths["method_dir"] / "artifacts/experiment-004/model_manifest.json"
    )["frozen_inference"]
    result["cohort_sha256"] = digest(paths["workspace"] / COHORT)
    result["images_sha256"] = digest(paths["workspace"] / IMAGES)
    result["sourceafis_jar_sha256"] = digest(paths["jar"])
    result["runtimes"] = {}
    for key in ("pore_python", "p2_python"):
        result["runtimes"][key] = environment_versions(str(paths[key]))
    result["upstream_urls"] = {
        "survey": "https://github.com/azimIbragimov/Fingerprint-Pore-Detection-A-Survey",
        "dahia_mirror": "https://github.com/xiaochengcike/high-res-fingerprint-recognition",
        "experiment004": "https://github.com/Mish2000/fingerprint-new-method",
    }
    return result


def environment_versions(python):
    code = "import sys; sys.path.insert(0, sys.argv[1]); from pore_worker import runtime; import json; print(json.dumps(runtime()))"
    return json.loads(
        subprocess.check_output([python, "-B", "-c", code, str(HERE)], text=True)
    )


def verify_assets(local, settings, route):
    keys = {
        "P1": ("survey_dir", "dahia_dir"),
        "P2": ("method_dir", "dahia_dir"),
        "R": (),
    }[route]
    for key in keys:
        base = Path(local[key])
        pin = settings["external"][key]
        if git(base, "rev-parse", "HEAD") != pin["revision"] or git(
            base, "status", "--porcelain"
        ):
            raise ValueError(f"{key}: source revision is not the clean pinned checkout")
        for relative, expected in pin["files"].items():
            if digest(base / relative) != expected:
                raise ValueError(f"{key}: asset changed: {relative}")
    if route == "R" and digest(Path(local["jar"])) != settings["sourceafis_jar_sha256"]:
        raise ValueError("SourceAFIS jar changed")
    for key in {"P1": ("pore_python",), "P2": ("pore_python", "p2_python"), "R": ()}[
        route
    ]:
        if environment_versions(local[key]) != settings["runtimes"][key]:
            raise ValueError(f"{key}: runtime versions changed")


def prepare(local, settings, out):
    import pyarrow.parquet as pq
    from PIL import Image

    check_ignored_output(out)
    workspace = Path(local["workspace"])
    if (
        digest(workspace / COHORT) != settings["cohort_sha256"]
        or digest(workspace / IMAGES) != settings["images_sha256"]
    ):
        raise ValueError("Original cohort/image manifest changed")
    cohort = read_json(workspace / COHORT)
    table = pq.read_table(workspace / IMAGES)
    if (
        table.schema.metadata[b"content_hash"].decode()
        != cohort["selection"]["image_manifest_hashes"]["SD300B"]
    ):
        raise ValueError("Cohort/image semantic binding mismatch")
    document = plan(cohort, table.to_pylist())
    document["sources"] = {
        "cohort_sha256": settings["cohort_sha256"],
        "images_sha256": settings["images_sha256"],
        "cohort_id": COHORT_ID,
        "image_manifest_hash": table.schema.metadata[b"content_hash"].decode(),
    }
    exposure = read_json(
        Path(local["method_dir"])
        / "artifacts/experiment-001/selection/selection_manifest.json"
    )
    historical = {row["subject_id"] for row in exposure["selected"]}
    document["known_exposure"] = {
        "experiment001_selection_sha256": digest(
            Path(local["method_dir"])
            / "artifacts/experiment-001/selection/selection_manifest.json"
        ),
        "protected_overlap": sorted(historical & set(cohort["subject_ids"])),
        "development_overlap": sorted(historical & set(document["selected_subjects"])),
        "historically_unexposed_claim": False,
    }
    if "reference_subject_manifest" in local:
        reference = Path(local["reference_subject_manifest"])
        with reference.open(encoding="utf-8-sig", newline="") as stream:
            subjects = {row["subject_id"] for row in csv.DictReader(stream)}
        if subjects != set(cohort["subject_ids"]):
            raise ValueError(
                "Local 50-subject delivery list and protected cohort disagree"
            )
        document["reference_subject_manifest"] = {
            "sha256": digest(reference),
            "subject_count": len(subjects),
            "exact_match": True,
        }
    out.mkdir(parents=True, exist_ok=False)
    # Freeze all selection/truth before opening any development image.
    write_json(out / "plan.json", document)
    write_json(out / "settings.json", settings)
    inputs_dir = out / "inputs"
    inputs_dir.mkdir()
    inputs = []
    for row in document["images"]:
        source = (Path(local["data_root"]) / row["relative_path"]).resolve()
        if not source.is_relative_to(Path(local["data_root"]).resolve()):
            raise ValueError("Input path escaped dataset root")
        if digest(source) != row["expected_sha256"]:
            raise ValueError(
                "Native delivery image failed its original manifest checksum"
            )
        target = inputs_dir / (row["alias"] + ".png")
        with source.open("rb") as src, target.open("xb") as dst:
            shutil.copyfileobj(src, dst)
        with Image.open(target) as image:
            if image.mode != "L":
                raise ValueError("SD300B original is not grayscale uint8")
            width, height = image.size
            header_dpi = image.info.get("dpi")
        inputs.append(
            {
                "alias": row["alias"],
                "path": str(target),
                "sha256": row["expected_sha256"],
                "width": width,
                "height": height,
                "header_dpi": header_dpi,
            }
        )
    write_json(out / "worker-inputs.json", inputs)
    write_json(
        out / "worker-pairs.json",
        [{k: p[k] for k in ("pair_id", "left", "right")} for p in document["pairs"]],
    )
    write_json(
        out / "prepared.json",
        {
            "plan_sha256": digest(out / "plan.json"),
            "settings_sha256": digest(out / "settings.json"),
            "inputs_sha256": digest(out / "worker-inputs.json"),
            "pairs_sha256": digest(out / "worker-pairs.json"),
            "image_count": len(inputs),
            "prepared_utc": datetime.now(UTC).isoformat(),
        },
    )
    print(
        {
            "selected": document["selected_subjects"],
            "active": document["active_subjects"],
            "overlap": [],
        }
    )


def verify_prepared(local, out, settings):
    receipt = read_json(out / "prepared.json")
    for name, key in (
        ("plan.json", "plan_sha256"),
        ("settings.json", "settings_sha256"),
        ("worker-inputs.json", "inputs_sha256"),
        ("worker-pairs.json", "pairs_sha256"),
    ):
        if digest(out / name) != receipt[key]:
            raise ValueError(f"Prepared artifact changed: {name}")
    if settings != read_json(out / "settings.json"):
        raise ValueError("Execution settings differ from preparation")
    if digest(Path(local["workspace"]) / COHORT) != settings["cohort_sha256"]:
        raise ValueError("Protected cohort changed")
    document = read_json(out / "plan.json")
    if len(document["pairs"]) != 250 or len(document["active_subjects"]) != 5:
        raise ValueError("Refusing an expanded execution")
    if set(document["selected_subjects"]) & set(
        read_json(Path(local["workspace"]) / COHORT)["subject_ids"]
    ):
        raise ValueError("Reserved subject leakage")
    for item in read_json(out / "worker-inputs.json"):
        if digest(Path(item["path"])) != item["sha256"]:
            raise ValueError("Prepared image changed")
    return document


def worker(python, arguments, logfile):
    with logfile.open("x", encoding="utf-8") as log:
        process = subprocess.run(
            [python, "-B", str(HERE / "pore_worker.py"), *map(str, arguments)],
            stdout=log,
            stderr=subprocess.STDOUT,
            cwd=ROOT,
            check=False,
        )
    if process.returncode:
        raise RuntimeError(f"Worker exited {process.returncode}; see {logfile.name}")


def run_pores(route, local, out, directory, document):
    common = ["--dahia-dir", local["dahia_dir"]]
    worker(
        local["pore_python"] if route == "P1" else local["p2_python"],
        [
            "detect",
            "--detector",
            route,
            "--inputs",
            out / "worker-inputs.json",
            "--out",
            directory / "detections",
            "--survey-dir",
            local["survey_dir"],
            "--method-dir",
            local["method_dir"],
        ],
        directory / "detect.log",
    )
    worker(
        local["pore_python"],
        [
            "describe",
            "--inputs",
            out / "worker-inputs.json",
            "--out",
            directory / "templates",
            "--detections",
            directory / "detections",
            *common,
        ],
        directory / "describe.log",
    )
    worker(
        local["pore_python"],
        [
            "match",
            "--pairs",
            out / "worker-pairs.json",
            "--out",
            directory / "pairs",
            "--templates",
            directory / "templates",
            *common,
            "--examples",
            *document["examples"],
        ],
        directory / "match.log",
    )


def run_reference(local, out, directory, document):
    from fpbench.adapters.sourceafis_java.bridge_client import BridgeClient
    from fpbench.adapters.sourceafis_java.config import SourceAfisJavaConfig

    mark = time.perf_counter()
    client = BridgeClient(
        SourceAfisJavaConfig(
            java_executable=Path(local["java"]), bridge_jar=Path(local["jar"])
        )
    )
    java, jar = client.resolve_java(), client.resolve_jar()
    version = client.version(java, jar)
    write_json(
        directory / "runtime.json",
        {
            "bridge": asdict(version),
            "jvm_args": list(client.config.jvm_args),
            "load_seconds": time.perf_counter() - mark,
            "cache": "disabled by existing integration",
        },
    )
    (directory / "pairs").mkdir()
    for index, pair in enumerate(document["pairs"]):
        mark = time.perf_counter()
        row = {k: pair[k] for k in ("pair_id", "left", "right")}
        row.update(status="failure", score=None, reason=None, matcher_invoked=True)
        try:
            response = client.compare(
                java=java,
                jar=jar,
                request_id=pair["pair_id"],
                left_path=out / "inputs" / (pair["left"] + ".png"),
                left_dpi=1000,
                right_path=out / "inputs" / (pair["right"] + ".png"),
                right_dpi=1000,
                working_directory=directory,
                timeout_seconds=120,
            )
            row.update(
                status="success" if response.succeeded else "failure",
                score=response.score,
                reason=response.code,
                failure_stage=response.stage,
                timings_ms=dict(response.timings_ms),
                extraction_count=response.extraction_count,
            )
        except Exception as exc:  # noqa: BLE001 -- preserve the attempted bridge outcome
            row.update(reason=type(exc).__name__, detail=str(exc))
        row["comparison_seconds"] = time.perf_counter() - mark
        write_json(directory / "pairs" / (pair["pair_id"] + ".json"), row)
        if (index + 1) % 25 == 0:
            print(f"R {index + 1}/250", flush=True)


def collect(route, out, directory, document, blocked_reason=None):
    identity = digest(directory / "identity.json")
    by_alias = {row["alias"]: row for row in document["images"]}
    rows = []
    for pair in document["pairs"]:
        path = directory / "pairs" / (pair["pair_id"] + ".json")
        result = (
            read_json(path)
            if path.exists()
            else {
                "status": "blocked",
                "score": None,
                "reason": blocked_reason or "NOT_EXECUTED",
                "matcher_invoked": False,
            }
        )
        if result["status"] == "success":
            if type(result["score"]) not in (float, int) or not __import__(
                "math"
            ).isfinite(result["score"]):
                raise ValueError("Scored result must carry a finite score")
        elif result.get("score") is not None:
            raise ValueError("A failure/blocked row cannot carry a score")
        row = {
            **pair,
            **result,
            "route": route,
            "identity_sha256": identity,
            "left_image_id": by_alias[pair["left"]]["image_id"],
            "right_image_id": by_alias[pair["right"]]["image_id"],
        }
        if route in ("P1", "P2"):
            row["per_image_records"] = {
                side: {
                    "detection": f"detections/{pair[side]}.json",
                    "description": f"templates/{pair[side]}.json",
                }
                for side in ("left", "right")
            }
        rows.append(row)
    fields = [
        "pair_id",
        "kind",
        "left_image_id",
        "right_image_id",
        "route",
        "identity_sha256",
        "score",
        "status",
        "reason",
        "pores_left",
        "pores_right",
        "comparison_seconds",
        "matcher_invoked",
        "details_json",
    ]
    with (directory / "scores.csv").open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    **{k: row.get(k) for k in fields[:-1]},
                    "details_json": __import__("json").dumps(
                        {k: v for k, v in row.items() if k not in fields}
                    ),
                }
            )
    counts = Counter(r["status"] for r in rows)
    extraction = []
    if (directory / "detections").is_dir():
        extraction = [
            read_json(p)
            for p in sorted((directory / "detections").glob("image-*.json"))
        ]
    distributions = {}
    scores = {}
    for kind in ("genuine", "impostor"):
        scores[kind] = [
            r["score"] for r in rows if r["kind"] == kind and r["status"] == "success"
        ]
        values = scores[kind]
        distributions[kind] = {
            "scored": len(values),
            "min": min(values) if values else None,
            "median": statistics.median(values) if values else None,
            "max": max(values) if values else None,
        }
    summary = {
        "route": route,
        "planned": len(rows),
        "executed": counts["success"] + counts["failure"],
        "scored": counts["success"],
        "failures": counts["failure"],
        "blocked": counts["blocked"],
        "matcher_invocations": sum(r["matcher_invoked"] for r in rows),
        "extraction_attempts": len(extraction),
        "extraction_successes": sum(r["status"] == "success" for r in extraction),
        "extraction_reasons": dict(
            Counter(r["reason"] for r in extraction if r.get("reason"))
        ),
        "reasons": dict(Counter(r["reason"] for r in rows if r["reason"])),
        "score_distributions_scored_only": distributions,
        "first_failure": next(
            (r["pair_id"] for r in rows if r["status"] != "success"), None
        ),
        "scores_sha256": digest(directory / "scores.csv"),
    }
    write_json(directory / "summary.json", summary)
    write_json(
        directory / "scored-only-sweep.json",
        {
            "description": "Exploratory >= boundaries with atomic ties; not an operating threshold or full-population performance estimate",
            "scored_genuine": len(scores["genuine"]),
            "scored_impostor": len(scores["impostor"]),
            "rows": score_sweep(scores["genuine"], scores["impostor"]),
        },
    )
    return summary


def execute(route, local, settings, out):
    document = verify_prepared(local, out, settings)
    if git(ROOT, "status", "--porcelain"):
        raise ValueError(
            "ADR 0017 requires committed, clean source before the research run"
        )
    revision = git(ROOT, "rev-parse", "HEAD")
    directory = out / route
    directory.mkdir()
    identity = {
        "schema": "l3_bridge_v1_execution",
        "route": route,
        "settings": settings,
        "source_revision": revision,
        "source_clean": True,
        "plan_sha256": digest(out / "plan.json"),
        "started_utc": datetime.now(UTC).isoformat(),
        "score_direction": "higher_is_more_similar",
    }
    write_json(directory / "identity.json", identity)
    problem = None
    try:
        verify_assets(local, settings, route)
        if route == "R":
            run_reference(local, out, directory, document)
        else:
            run_pores(route, local, out, directory, document)
    except Exception as exc:  # noqa: BLE001 -- retain partial work and account for unexecuted pairs
        problem = f"{type(exc).__name__}: {exc}"
        write_json(directory / "blocked.json", {"reason": problem})
    # Source/runtime drift invalidates evidence; it is never converted to a zero.
    if git(ROOT, "status", "--porcelain") or git(ROOT, "rev-parse", "HEAD") != revision:
        raise ValueError("Source changed during execution")
    verify_prepared(local, out, settings)
    if problem is None:
        verify_assets(local, settings, route)
    summary = collect(route, out, directory, document, problem)
    print(summary, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("pin", "prepare", "run"))
    parser.add_argument(
        "--local",
        type=Path,
        required=True,
        help="Ignored, machine-local path configuration",
    )
    parser.add_argument("--out", type=Path)
    parser.add_argument("--route", choices=("P1", "P2", "R"))
    args = parser.parse_args()
    local = read_json(args.local)
    if args.action == "pin":
        write_json(HERE / "settings.json", pins(local))
        return
    out = args.out.resolve()
    check_ignored_output(out)
    settings = read_json(HERE / "settings.json")
    if args.action == "prepare":
        prepare(local, settings, out)
    elif args.route:
        execute(args.route, local, settings, out)
    else:
        parser.error("run requires --route")


if __name__ == "__main__":
    main()
