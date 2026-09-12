"""Frozen P2 inference on saved repaired scales; never receives pair truth."""

from __future__ import annotations

import argparse
import hashlib
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True
from support import (
    copy_new,
    digest,
    native_xy,
    read_image,
    read_json,
    runtime,
    validate_xy,
    verify_source,
    write_json,
)


def main():
    import numpy as np
    import torch

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--method-dir", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.method_dir / "src"))
    from fingerprint_new_method.experiment004 import extract_peaks, preprocess_image
    from fingerprint_new_method.experiment004_model import infer_heatmap, load_model
    from ridge import resize_from_policy

    verify_source(args.out)
    manifest = read_json(args.out / "preprocessing_manifest.json")
    settings = manifest["unchanged_inference"]
    checkpoint = args.method_dir / manifest["weight"]["relative_local_path"]
    if digest(checkpoint) != manifest["weight"]["sha256"]:
        raise ValueError("Frozen seed40401 checkpoint changed")
    started = time.perf_counter()
    model, device, _ = load_model(checkpoint)
    runtime_record = {
        **runtime(),
        "device": str(device),
        "torch_threads": torch.get_num_threads(),
        "model_load_seconds": time.perf_counter() - started,
    }
    for route in ("P2R", "P2R-wide"):
        directory = args.out / route / "detections"
        directory.mkdir()
        write_json(directory / "runtime.json", runtime_record)
    inputs = read_json(args.out / "worker-inputs.json")
    for index, item in enumerate(inputs):
        alias = item["alias"]
        audit = read_json(args.out / "scale-estimates" / f"{alias}.json")
        policy = audit["policies"]["P2R-wide"]
        record = {
            "alias": alias,
            "status": "failure",
            "reason": policy["reason"],
            "failure_stage": "preprocessing",
            "ridge_scale": policy,
            "timings": {},
        }
        mark = time.perf_counter()
        stage = "preprocessing"
        if policy["status"] == "OK":
            try:
                image = read_image(item)
                record["native_shape"] = list(image.shape)
                scaled = resize_from_policy(image, policy)
                processed = preprocess_image(scaled)
                record["timings"]["preprocessing_seconds"] = time.perf_counter() - mark
                record["scaled_pixels_sha256"] = hashlib.sha256(
                    scaled.tobytes()
                ).hexdigest()
                record["processed_pixels_sha256"] = hashlib.sha256(
                    processed.tobytes()
                ).hexdigest()
                mark = time.perf_counter()
                stage = "detection"
                tiling = settings["tiled_inference"]
                heatmap = infer_heatmap(
                    model,
                    processed,
                    device,
                    tile_size=tiling["tile_size"],
                    overlap=tiling["overlap"],
                )
                peaks = extract_peaks(
                    heatmap,
                    threshold=settings["threshold"],
                    nms_radius=settings["nms_radius_px"],
                )
                points = np.asarray(
                    native_xy(peaks.coordinates, policy["factor"]), dtype=np.float32
                ).reshape(-1, 2)
                record["timings"]["detection_seconds"] = time.perf_counter() - mark
                stage = "coordinate_validation"
                validate_xy(points, *image.shape)
                np.savez_compressed(
                    args.out / "P2R-wide/detections" / f"{alias}.npz", points_xy=points
                )
                record.update(
                    status="success",
                    reason=None,
                    failure_stage=None,
                    pores=len(points),
                    transform={
                        "native_xy": "(normalized_xy + 0.5) / factor - 0.5",
                        "factor": policy["factor"],
                        "normalized_shape": list(scaled.shape),
                        "tiled_inference": tiling,
                        "resize": "INTER_AREA if factor<1 else INTER_CUBIC; fx=fy=factor",
                        "padding": "unchanged upstream reflect bottom/right; removed after blending",
                    },
                )
            except Exception as exc:  # noqa: BLE001 -- preserve each attempted image failure
                record.update(
                    reason=f"{stage.upper()}_{type(exc).__name__}",
                    failure_stage=stage,
                    detail=str(exc),
                )
                record["timings"]["failed_stage_seconds"] = time.perf_counter() - mark
        wide_file = args.out / "P2R-wide/detections" / f"{alias}.json"
        write_json(wide_file, record)
        primary = audit["policies"]["P2R"]
        if primary["status"] != "OK":
            main_record = {
                "alias": alias,
                "status": "failure",
                "reason": primary["reason"],
                "failure_stage": "preprocessing",
                "ridge_scale": primary,
                "timings": {},
            }
        else:
            if primary["factor"] != policy["factor"] or policy["status"] != "OK":
                raise ValueError(
                    "Shared inference requires identical eligible input scales"
                )
            main_record = {
                **record,
                "ridge_scale": primary,
                "shared_detection": {
                    "path": f"P2R-wide/detections/{alias}.json",
                    "sha256": digest(wide_file),
                },
            }
            if record["status"] == "success":
                copy_new(
                    args.out / "P2R-wide/detections" / f"{alias}.npz",
                    args.out / "P2R/detections" / f"{alias}.npz",
                )
        write_json(args.out / "P2R/detections" / f"{alias}.json", main_record)
        print(
            f"image {index + 1}/100 main={main_record['status']}:{main_record['reason']} wide={record['status']}:{record['reason']}",
            flush=True,
        )
    verify_source(args.out)


if __name__ == "__main__":
    main()
