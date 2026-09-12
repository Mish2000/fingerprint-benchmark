"""Prepare once, run two declared repair policies, and verify the local result."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

sys.dont_write_bytecode = True
from analysis import scale_policy
from support import (
    HERE,
    ROOT,
    V1,
    bind_prior,
    check_ignored_output,
    copy_new,
    digest,
    freeze_source,
    read_json,
    train_records,
    verify_preserved,
    verify_source,
    write_csv,
    write_json,
)


def prepare(args, local):
    import cv2
    import numpy as np

    sys.path.insert(0, str(Path(local["method_dir"]) / "src"))
    from fingerprint_new_method.experiment004 import resolve_source_id
    from ridge import ESTIMATOR_VERSION, estimate_ridge_period

    out, prior = args.out, args.prior
    settings = read_json(HERE / "settings.json")
    verify_preserved(out)
    plan, old_routes, _old_settings, inputs = bind_prior(prior, local, settings)
    probe = read_json(out / "rotation_probe_actual_source.json")
    comparison = read_json(out / "rotation_probe_source_comparison.json")
    if (
        probe["source_mode"] != "actual_local_source"
        or probe["test_cases"] != 60
        or probe["within_tolerance"] != {"original": 10, "sign_corrected": 60}
        or not comparison["actual_and_supplied_excerpt_ast_equal"]
        or comparison["local_source_byte_sha256"] != settings["estimator_source_sha256"]
    ):
        raise ValueError("Actual-source synthetic review has not passed")
    numeric = subprocess.run(
        [
            local["p2_python"],
            "-B",
            "-m",
            "pytest",
            str(HERE / "test_numerical.py"),
            "-q",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "FPBENCH_L3_METHOD_DIR": local["method_dir"]},
    )
    (out / "numerical_tests.log").write_text(
        numeric.stdout + numeric.stderr, encoding="utf-8"
    )
    if numeric.returncode:
        raise ValueError("Repair numerical regressions failed")
    records = train_records(Path(local["method_dir"]), settings)
    freeze_source(out, settings)
    copy_new(HERE / "settings.json", out / "settings.json")
    copy_new(prior / "plan.json", out / "plan.json")
    copy_new(prior / "worker-inputs.json", out / "worker-inputs.json")
    copy_new(prior / "worker-pairs.json", out / "worker-pairs.json")
    examples = {
        r: list(
            dict.fromkeys(
                plan["examples"] + ([s["first_failure"]] if s["first_failure"] else [])
            )
        )
        for r, (s, _) in old_routes.items()
    }
    examples.update({r: examples["P2"] for r in ("P2R", "P2R-wide")})
    write_json(out / "examples.json", examples)
    train_dir = out / "train-estimates"
    train_dir.mkdir()
    estimates = []
    for index, record in enumerate(records):
        path = resolve_source_id(record["image_source_id"])
        if digest(path) != record["image_sha256"]:
            raise ValueError("TRAIN image differs from the original split checksum")
        image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if image is None or image.shape != (record["height"], record["width"]):
            raise ValueError("TRAIN image is not the original annotated-512 input")
        estimate = estimate_ridge_period(image)
        row = {**record, "estimate": estimate}
        write_json(train_dir / f"train-{index:03d}.json", row)
        estimates.append(row)
        if (index + 1) % 40 == 0:
            print(f"TRAIN estimates {index + 1}/440", flush=True)
    accepted = [
        r["estimate"]["period_px"]
        for r in estimates
        if r["estimate"]["period_px"] is not None
    ]
    if not accepted:
        write_json(
            out / "blocked.json",
            {"reason": "NO_RELIABLE_TRAIN_ESTIMATE", "images": len(estimates)},
        )
        raise ValueError("P2 repair blocked: no reliable TRAIN target")
    target = float(statistics.median(accepted))
    model = read_json(
        Path(local["method_dir"]) / "artifacts/experiment-004/model_manifest.json"
    )
    manifest = {
        "schema": "l3_repair_train_preprocessing_v1",
        "created_utc": datetime.now(UTC).isoformat(),
        "source_partition": "train",
        "target_period_px": target,
        "historical_target_period_px": 34.0,
        "aggregation": settings["target_rule"],
        "estimator": ESTIMATOR_VERSION,
        "estimator_sha256": digest(HERE / "ridge.py"),
        "source_snapshot_sha256": digest(out / "source_snapshot.json"),
        "split_manifest_sha256": settings["split_manifest_sha256"],
        "model_manifest_sha256": digest(
            Path(local["method_dir"]) / "artifacts/experiment-004/model_manifest.json"
        ),
        "weight": next(w for w in model["weights"] if w["seed"] == 40401),
        "unchanged_inference": model["frozen_inference"],
        "image_count": len(records),
        "group_count": len({r["group_id"] for r in records}),
        "counts": dict(Counter(r["estimate"]["status"] for r in estimates)),
        "accepted_distribution": {
            "min": min(accepted),
            "p25": float(np.percentile(accepted, 25)),
            "median": target,
            "p75": float(np.percentile(accepted, 75)),
            "max": max(accepted),
            "histogram": dict(sorted(Counter(accepted).items())),
        },
        "train_images": [
            {
                k: r[k]
                for k in (
                    "canonical_image_id",
                    "group_id",
                    "image_source_id",
                    "image_sha256",
                )
            }
            for r in records
        ],
        "estimate_files": {p.name: digest(p) for p in sorted(train_dir.glob("*.json"))},
        "policies": {
            name: {
                **p,
                "target": target if p["target"] == "T_train_fixed" else p["target"],
            }
            for name, p in settings["policies"].items()
        },
        "validation_or_test_pixels_read": 0,
        "annotated_512_to_final_320_identity_inferred": False,
    }
    write_json(out / "preprocessing_manifest.json", manifest)
    print(f"T_train_fixed={target}; TRAIN counts={manifest['counts']}", flush=True)
    audits = out / "scale-estimates"
    audits.mkdir()
    rows = []
    from pore_worker import read_image

    for index, item in enumerate(inputs):
        estimate = estimate_ridge_period(read_image(item))
        previous = read_json(prior / "P2/detections" / f"{item['alias']}.json")
        policies = {
            name: scale_policy(estimate, p["target"], p["band"])
            for name, p in manifest["policies"].items()
        }
        audit = {
            "alias": item["alias"],
            "image_sha256": item["sha256"],
            "original": previous["ridge_scale"],
            "original_extraction_status": previous["status"],
            "original_reason": previous["reason"],
            "corrected": estimate,
            "policies": policies,
        }
        write_json(audits / f"{item['alias']}.json", audit)
        old = previous["ridge_scale"]["estimate"]
        row = {
            "image_alias": item["alias"],
            "image_sha256": item["sha256"],
            "original_extraction_status": previous["status"],
            "original_reason": previous["reason"],
            "original_estimate_status": old["status"],
            "original_period_px": old["period_px"],
            "original_factor": previous["ridge_scale"]["factor"],
            "original_tile_periods": json.dumps(old["tile_periods"]),
            "original_tile_correlations": json.dumps(old["tile_correlations"]),
            "original_candidate_tiles": old["candidate_tiles"],
            "original_accepted_tiles": old["accepted_tiles"],
            "original_mad_over_median": old["mad_over_median"],
            "original_coherences": "not recorded in v1",
            "corrected_estimate_status": estimate["status"],
            "corrected_period_px": estimate["period_px"],
            "corrected_tile_periods": json.dumps(estimate["tile_periods"]),
            "corrected_tile_correlations": json.dumps(estimate["tile_correlations"]),
            "corrected_tile_coherences": json.dumps(
                [t["coherence"] for t in estimate["tiles"]]
            ),
            "corrected_candidate_tiles": estimate["candidate_tiles"],
            "corrected_accepted_tiles": estimate["accepted_tiles"],
            "corrected_mad_over_median": estimate["mad_over_median"],
        }
        for name, policy in policies.items():
            row.update(
                {
                    f"{name}_{key}": policy[key]
                    for key in ("target", "factor", "status", "reason")
                }
            )
        rows.append(row)
        if (index + 1) % 10 == 0:
            print(f"Development scale estimates {index + 1}/100", flush=True)
    write_csv(out / "scale_audit.csv", rows)
    bindings = {
        "schema": "l3_scale_repair_prepared_v1",
        "prior_directory": str(prior.resolve()),
        "local_config_sha256": digest(args.local),
        "created_utc": datetime.now(UTC).isoformat(),
        "files": {
            p: digest(out / p)
            for p in (
                "plan.json",
                "worker-inputs.json",
                "worker-pairs.json",
                "settings.json",
                "source_snapshot.json",
                "preprocessing_manifest.json",
                "scale_audit.csv",
                "examples.json",
                "rotation_probe_actual_source.json",
                "rotation_probe_source_comparison.json",
            )
        },
        "scale_estimates": {p.name: digest(p) for p in sorted(audits.glob("*.json"))},
        "prior_routes": {
            r: {
                "identity_sha256": digest(prior / r / "identity.json"),
                "scores_sha256": digest(prior / r / "scores.csv"),
            }
            for r in old_routes
        },
    }
    write_json(out / "prepared.json", bindings)
    verify_ready(out, local, args.local)
    print("Prepared both declared policies; no detector inference yet", flush=True)


def verify_ready(out, local, config):
    verify_source(out)
    verify_preserved(out)
    prepared = read_json(out / "prepared.json")
    if digest(config) != prepared["local_config_sha256"]:
        raise ValueError("Local configuration changed")
    for name, sha in prepared["files"].items():
        if digest(out / name) != sha:
            raise ValueError(f"Prepared binding changed: {name}")
    for name, sha in prepared["scale_estimates"].items():
        if digest(out / "scale-estimates" / name) != sha:
            raise ValueError("A corrected development estimate changed")
    manifest = read_json(out / "preprocessing_manifest.json")
    sys.path.insert(0, str(Path(local["method_dir"]) / "src"))
    from fingerprint_new_method.experiment004 import resolve_source_id

    for record in manifest["train_images"]:
        if (
            digest(resolve_source_id(record["image_source_id"]))
            != record["image_sha256"]
        ):
            raise ValueError("TRAIN source bytes changed after target estimation")
    periods = []
    for name, sha in manifest["estimate_files"].items():
        if digest(out / "train-estimates" / name) != sha:
            raise ValueError("A training estimate changed")
        estimate = read_json(out / "train-estimates" / name)["estimate"]
        if estimate["period_px"] is not None:
            periods.append(estimate["period_px"])
    if not periods or statistics.median(periods) != manifest["target_period_px"]:
        raise ValueError(
            "TRAIN target does not equal the saved reliable-estimate median"
        )
    prior = Path(prepared["prior_directory"])
    bind_prior(prior, local, read_json(out / "settings.json"))
    return prepared


def invoke(command, log):
    with log.open("x", encoding="utf-8") as stream:
        result = subprocess.run(
            command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=False
        )
    if result.returncode:
        raise RuntimeError(f"Worker failed ({result.returncode}); see {log}")


def run(args, local):
    out = args.out
    prepared = verify_ready(out, local, args.local)
    manifest = read_json(out / "preprocessing_manifest.json")
    examples = read_json(out / "examples.json")
    for route in ("P2R", "P2R-wide"):
        directory = out / route
        directory.mkdir()
        write_json(
            directory / "identity.json",
            {
                "schema": "l3_scale_repair_execution_v1",
                "route": route,
                "prepared_sha256": digest(out / "prepared.json"),
                "source_snapshot_sha256": digest(out / "source_snapshot.json"),
                "preprocessing_manifest_sha256": digest(
                    out / "preprocessing_manifest.json"
                ),
                "plan_sha256": prepared["files"]["plan.json"],
                "policy": manifest["policies"][route],
                "weight_sha256": manifest["weight"]["sha256"],
                "started_utc": datetime.now(UTC).isoformat(),
                "descriptor_matcher": read_json(
                    Path(prepared["prior_directory"]) / "settings.json"
                )["shared_descriptor_matcher"],
                "shared_work": "P2R-wide physical inference/description/matching; P2R reuses identical intermediates only when independently eligible",
            },
        )
    invoke(
        [
            local["p2_python"],
            "-B",
            str(HERE / "worker.py"),
            "--out",
            str(out),
            "--method-dir",
            local["method_dir"],
        ],
        out / "detection.log",
    )
    verify_source(out)
    wide = out / "P2R-wide"
    invoke(
        [
            local["pore_python"],
            "-B",
            str(V1 / "pore_worker.py"),
            "describe",
            "--inputs",
            str(out / "worker-inputs.json"),
            "--out",
            str(wide / "templates"),
            "--detections",
            str(wide / "detections"),
            "--dahia-dir",
            local["dahia_dir"],
        ],
        out / "description.log",
    )
    main = out / "P2R"
    (main / "templates").mkdir()
    for item in read_json(out / "worker-inputs.json"):
        name = item["alias"]
        detection = read_json(main / "detections" / f"{name}.json")
        if detection["status"] == "success":
            record = read_json(wide / "templates" / f"{name}.json")
            record["shared_template"] = {
                "path": f"P2R-wide/templates/{name}.json",
                "sha256": digest(wide / "templates" / f"{name}.json"),
            }
            if record["status"] == "success":
                copy_new(
                    wide / "templates" / f"{name}.npz",
                    main / "templates" / f"{name}.npz",
                )
        else:
            record = {
                "alias": name,
                "status": "failure",
                "reason": detection["reason"],
                "failure_stage": detection["failure_stage"],
                "timings": {},
                "pores": None,
            }
        write_json(main / "templates" / f"{name}.json", record)
    invoke(
        [
            local["pore_python"],
            "-B",
            str(V1 / "pore_worker.py"),
            "match",
            "--out",
            str(wide / "pairs"),
            "--templates",
            str(wide / "templates"),
            "--pairs",
            str(out / "worker-pairs.json"),
            "--dahia-dir",
            local["dahia_dir"],
            "--examples",
            *examples["P2R-wide"],
        ],
        out / "matching.log",
    )
    (main / "pairs").mkdir()
    for pair in read_json(out / "worker-pairs.json"):
        metas = {
            s: read_json(main / "templates" / f"{pair[s]}.json")
            for s in ("left", "right")
        }
        failures = {
            s: m["reason"] for s, m in metas.items() if m["status"] != "success"
        }
        if failures:
            record = {
                **pair,
                "status": "failure",
                "score": None,
                "reason": "EXTRACTION_FAILURE",
                "matcher_invoked": False,
                "extraction_failures": failures,
            }
        else:
            for side in ("left", "right"):
                if digest(main / "templates" / f"{pair[side]}.npz") != digest(
                    wide / "templates" / f"{pair[side]}.npz"
                ):
                    raise ValueError(
                        "Shared matching requires byte-identical intermediate templates"
                    )
            path = wide / "pairs" / f"{pair['pair_id']}.json"
            record = read_json(path)
            record.update(
                shared_result={
                    "path": f"P2R-wide/pairs/{path.name}",
                    "sha256": digest(path),
                },
                matcher_invoked=False,
                shared_matcher_invoked=record["matcher_invoked"],
            )
        write_json(main / "pairs" / f"{pair['pair_id']}.json", record)
    verify_ready(out, local, args.local)
    write_json(
        out / "execution_complete.json",
        {
            "prepared_sha256": digest(out / "prepared.json"),
            "finished_utc": datetime.now(UTC).isoformat(),
            "files": {
                p.relative_to(out).as_posix(): digest(p)
                for route in (main, wide)
                for p in sorted(route.rglob("*"))
                if p.is_file()
            },
        },
    )
    print(
        "Completed both 250-pair policies; original routes were reused read-only",
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run", "verify"))
    parser.add_argument("--local", type=Path, required=True)
    parser.add_argument("--prior", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out = args.out.resolve()
    check_ignored_output(args.out)
    local = read_json(args.local)
    if args.action == "prepare":
        if args.prior is None:
            parser.error("prepare requires --prior")
        args.prior = args.prior.resolve()
        prepare(args, local)
    elif args.action == "run":
        run(args, local)
    else:
        verify_ready(args.out, local, args.local)
        from readout import verify_results

        verify_results(args.out)
        print("Source, predecessor, TRAIN, scale audit and all pair records verified")


if __name__ == "__main__":
    main()
