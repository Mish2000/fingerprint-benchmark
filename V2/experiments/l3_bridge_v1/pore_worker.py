"""Isolated detector/descriptor/matcher worker. Receives opaque inputs, never truth."""

from __future__ import annotations

import argparse
import importlib.metadata
import platform
import sys
import time
import types
from pathlib import Path

sys.dont_write_bytecode = True

from common import digest, native_xy, read_json, survey_xy, validate_xy, write_json


def tiled_survey(model, image, output_tile=256):
    """Tile the valid-convolution OUTPUT with a 16-pixel input overlap.

    Eight stride-one valid 3x3 convolutions have a 17x17 receptive field.
    No padding, resize, output overlap or per-tile NMS is introduced.
    """
    import numpy as np
    import torch

    height, width = image.shape
    if min(height, width) < 17:
        raise ValueError("Image is smaller than the Survey receptive field")
    result = torch.empty((1, 1, height - 16, width - 16), dtype=torch.float32)
    with torch.no_grad():
        for y in range(0, height - 16, output_tile):
            for x in range(0, width - 16, output_tile):
                end_y, end_x = (
                    min(y + output_tile, height - 16),
                    min(x + output_tile, width - 16),
                )
                tile = np.ascontiguousarray(
                    image[y : end_y + 16, x : end_x + 16], dtype=np.float32
                ) / np.float32(255)
                prediction = model(torch.from_numpy(tile)[None, None])
                if prediction.shape[-2:] != (end_y - y, end_x - x):
                    raise ValueError("Survey output geometry changed")
                result[:, :, y:end_y, x:end_x] = prediction.cpu()
    return result


def load_survey(path):
    import torch

    sys.path.insert(0, str(path))
    import entireImage
    from util.utils import loadModel

    torch.set_num_threads(4)
    model = loadModel(
        str(path / "out_of_the_box_detect/models/40"),
        torch.device("cpu"),
        8,
        40,
        False,
        17,
        False,
        False,
        False,
    )
    model.eval()
    return model, entireImage


def load_dahia(path):
    # Only the pure OpenCV/numpy SIFT route is used. No TensorFlow call is made.
    sys.modules.setdefault("tensorflow", types.ModuleType("tensorflow"))
    sys.path.insert(0, str(path))
    import matching
    import utils

    return utils, matching


def runtime():
    result = {"python": platform.python_version(), "platform": platform.platform()}
    for package in (
        "numpy",
        "torch",
        "torchvision",
        "opencv-contrib-python",
        "opencv-python-headless",
        "scipy",
    ):
        try:
            result[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            pass
    return result


def read_image(item):
    import cv2

    path = Path(item["path"])
    if digest(path) != item["sha256"]:
        raise ValueError("Input digest changed")
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is None or image.ndim != 2 or str(image.dtype) != "uint8":
        raise ValueError("Expected decodable native gray8 image")
    return image


def detect(args, inputs, out):
    import numpy as np

    started = time.perf_counter()
    if args.detector == "P1":
        model, entire = load_survey(args.survey_dir)
    else:
        sys.path.insert(0, str(args.method_dir / "src"))
        from fingerprint_new_method.experiment004 import extract_peaks, preprocess_image
        from fingerprint_new_method.experiment004_model import infer_heatmap, load_model
        from fingerprint_new_method.experiment004_transfer import normalize_ridge_scale

        manifest = read_json(
            args.method_dir / "artifacts/experiment-004/model_manifest.json"
        )
        settings = manifest["frozen_inference"]
        weight = next(w for w in manifest["weights"] if w["seed"] == 40401)
        checkpoint = args.method_dir / weight["relative_local_path"]
        if (
            digest(checkpoint) != weight["sha256"]
            or checkpoint.stat().st_size != weight["size_bytes"]
        ):
            raise ValueError("Experiment 004 seed 40401 checkpoint mismatch")
        model, device, _ = load_model(checkpoint)
    write_json(
        out / "runtime.json",
        {
            **runtime(),
            "model_load_seconds": time.perf_counter() - started,
            "device": "cpu" if args.detector == "P1" else str(device),
            "torch_threads": __import__("torch").get_num_threads(),
        },
    )
    for index, item in enumerate(inputs):
        record = {
            "alias": item["alias"],
            "status": "failure",
            "reason": None,
            "timings": {},
        }
        mark = time.perf_counter()
        stage = "input"
        try:
            image = read_image(item)
            record["timings"]["input_seconds"] = time.perf_counter() - mark
            record["native_shape"] = list(image.shape)
            mark = time.perf_counter()
            stage = "detection"
            if args.detector == "P1":
                prediction = tiled_survey(model, image)
                scratch = out / item["alias"]
                scratch.mkdir()
                entire.apply_nms(
                    prediction,
                    0.65,
                    17,
                    0.2,
                    str(scratch) + "/",
                    0,
                    str(scratch) + "/",
                    17,
                )
                rows = [
                    tuple(map(int, line.split(",")))
                    for line in (scratch / "0.txt").read_text().splitlines()
                ]
                points = np.asarray(survey_xy(rows), dtype=np.float32).reshape(-1, 2)
                transform = {
                    "detector_frame": "zero-based row,column with receptive-field centre +8 already included",
                    "native_xy": "swap columns; no subtraction",
                    "receptive_field": 17,
                    "output_tile": 256,
                    "input_overlap": 16,
                    "padding": 0,
                    "resize": None,
                    "nms": "global after stitching; upstream apply_nms",
                }
            else:
                stage = "preprocessing"
                ridge = settings["ridge_scale"]
                scaled = normalize_ridge_scale(
                    image,
                    ridge["target_period_px"],
                    band=tuple(ridge["allowed_scale_factor"]),
                )
                record["ridge_scale"] = {
                    "status": scaled.status,
                    "factor": scaled.scale_factor,
                    "estimate": scaled.estimate.as_dict(),
                    "allowed": ridge["allowed_scale_factor"],
                }
                if scaled.image is None:
                    reason = (
                        scaled.estimate.status
                        if scaled.estimate.status != "OK"
                        else "SCALE_OUTSIDE_FROZEN_BAND"
                    )
                    record["reason"] = reason
                    raise ValueError(reason)
                processed = preprocess_image(scaled.image)
                record["timings"]["preprocessing_seconds"] = time.perf_counter() - mark
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
                    native_xy(peaks.coordinates, scaled.scale_factor), dtype=np.float32
                ).reshape(-1, 2)
                transform = {
                    "detector_frame": "zero-based x=column,y=row in ridge-normalized image",
                    "native_xy": "(normalized_xy + 0.5) / factor - 0.5",
                    "factor": scaled.scale_factor,
                    "normalized_shape": list(scaled.image.shape),
                    "resize": "INTER_AREA if factor<1 else INTER_CUBIC; fx=fy=factor",
                    "tiled_inference": tiling,
                    "padding": "reflect bottom/right to at least 512; removed after blending",
                }
            record["timings"]["detection_seconds"] = time.perf_counter() - mark
            stage = "coordinate_validation"
            validate_xy(points, *image.shape)
            np.savez_compressed(out / f"{item['alias']}.npz", points_xy=points)
            record.update(status="success", pores=len(points), transform=transform)
        except Exception as exc:  # noqa: BLE001 -- retain each third-party failure as a result
            record.update(
                reason=record["reason"] or f"{stage.upper()}_{type(exc).__name__}",
                failure_stage=stage,
                detail=str(exc),
            )
            record["timings"]["failed_stage_seconds"] = time.perf_counter() - mark
        write_json(out / f"{item['alias']}.json", record)
        print(
            f"{args.detector} image {index + 1}/{len(inputs)} {record['status']} {record.get('reason') or ''}",
            flush=True,
        )


def describe(args, inputs, out):
    import numpy as np

    utils, _ = load_dahia(args.dahia_dir)
    write_json(out / "runtime.json", runtime())
    for item in inputs:
        record = {
            "alias": item["alias"],
            "status": "failure",
            "reason": None,
            "timings": {},
        }
        try:
            detection = read_json(args.detections / f"{item['alias']}.json")
            record["pores"] = detection.get("pores")
            if detection["status"] != "success":
                record.update(
                    reason=detection["reason"], failure_stage=detection["failure_stage"]
                )
            else:
                mark = time.perf_counter()
                image = read_image(item)
                points = np.load(
                    args.detections / f"{item['alias']}.npz", allow_pickle=False
                )["points_xy"]
                validate_xy(points, *image.shape)
                record["timings"]["input_seconds"] = time.perf_counter() - mark
                mark = time.perf_counter()
                # Dahia swaps row,column internally before constructing OpenCV x,y.
                descriptors = utils.sift_descriptors(
                    image, points[:, ::-1].copy(), scale=4, normalize=True
                )
                if len(points) == 0:
                    descriptors = np.empty((0, 128), dtype=np.float32)
                if descriptors is None or len(descriptors) != len(points):
                    raise ValueError("SIFT descriptor/coordinate count mismatch")
                np.savez_compressed(
                    out / f"{item['alias']}.npz",
                    points_xy=points,
                    descriptors=descriptors,
                )
                record.update(status="success", descriptors=len(descriptors))
                record["timings"]["descriptor_seconds"] = time.perf_counter() - mark
        except Exception as exc:  # noqa: BLE001 -- retain each third-party failure as a result
            record.update(
                reason=f"DESCRIPTOR_{type(exc).__name__}",
                failure_stage="description",
                detail=str(exc),
            )
        write_json(out / f"{item['alias']}.json", record)


def match(args, out):
    import numpy as np

    utils, matching = load_dahia(args.dahia_dir)
    cache = {}
    metadata = {}
    for pair in read_json(args.pairs):
        record = {
            "pair_id": pair["pair_id"],
            "left": pair["left"],
            "right": pair["right"],
            "status": "failure",
            "score": None,
            "reason": None,
            "matcher_invoked": False,
        }
        mark = time.perf_counter()
        try:
            for alias in (pair["left"], pair["right"]):
                if alias not in metadata:
                    metadata[alias] = read_json(args.templates / f"{alias}.json")
                if metadata[alias]["status"] == "success" and alias not in cache:
                    with np.load(
                        args.templates / f"{alias}.npz", allow_pickle=False
                    ) as data:
                        cache[alias] = (data["points_xy"], data["descriptors"])
            bad = {
                side: metadata[pair[side]]["reason"]
                for side in ("left", "right")
                if metadata[pair[side]]["status"] != "success"
            }
            record["pores_left"], record["pores_right"] = (
                metadata[pair[side]].get("pores") for side in ("left", "right")
            )
            if bad:
                record.update(reason="EXTRACTION_FAILURE", extraction_failures=bad)
            else:
                pts1, d1 = cache[pair["left"]]
                pts2, d2 = cache[pair["right"]]
                record["matcher_invoked"] = True
                score = float(matching.spatial(d1, d2, pts1, pts2, thr=0.7))
                if not np.isfinite(score):
                    raise ValueError("Nonfinite upstream spatial score")
                record.update(status="success", score=score)
                # No geometric registration or acceptance gate precedes scoring.
                if pair["pair_id"] in args.examples:
                    correspondences = (
                        utils.find_correspondences(d1, d2, thr=0.7)
                        if len(d1) and len(d2)
                        else []
                    )
                    write_json(
                        out / f"{pair['pair_id']}-correspondences.json",
                        [list(map(float, c)) for c in correspondences],
                    )
        except Exception as exc:  # noqa: BLE001 -- a runtime exception is never a score
            record.update(reason=f"MATCHING_{type(exc).__name__}", detail=str(exc))
        record["comparison_seconds"] = time.perf_counter() - mark
        write_json(out / f"{pair['pair_id']}.json", record)
        print(f"pair {pair['pair_id']} {record['status']}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("detect", "describe", "match"))
    parser.add_argument("--detector", choices=("P1", "P2"))
    for name in (
        "inputs",
        "out",
        "survey-dir",
        "dahia-dir",
        "method-dir",
        "detections",
        "templates",
        "pairs",
    ):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--examples", nargs="*", default=[])
    args = parser.parse_args()
    args.out.mkdir()
    if args.action == "detect":
        detect(args, read_json(args.inputs), args.out)
    elif args.action == "describe":
        describe(args, read_json(args.inputs), args.out)
    else:
        match(args, args.out)


if __name__ == "__main__":
    main()
