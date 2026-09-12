"""Explicit P2 environment checks, with synthetic pixels and no SD300 access."""

import os
import sys
from pathlib import Path

import numpy as np
import torch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(os.environ["FPBENCH_L3_METHOD_DIR"]) / "src"))
from fingerprint_new_method.experiment004 import extract_peaks
from fingerprint_new_method.experiment004_model import infer_heatmap, load_model
from fingerprint_new_method.experiment004_transfer import normalize_ridge_scale


def test_frozen_scale_guard_is_not_widened():
    _, x = np.mgrid[0:512, 0:768]
    image = np.clip(127 + 90 * np.cos(2 * np.pi * x / 20), 0, 255).astype(np.uint8)
    result = normalize_ridge_scale(image, 34.0, band=(0.2, 1.5))
    assert result.status == "PREPROCESSING_FAILURE" and result.image is None
    assert result.scale_factor > 1.5


def test_tiling_unpadding_and_peak_axes_on_non_square_image():
    image = np.random.default_rng(1).random((537, 719), dtype=np.float32)
    actual = infer_heatmap(torch.nn.Identity(), image, torch.device("cpu"))
    np.testing.assert_allclose(actual, 1 / (1 + np.exp(-image)), atol=2e-7)
    heatmap = np.zeros((31, 79), dtype=np.float32)
    heatmap[7, 63] = 0.8
    heatmap[7, 64] = 0.75
    peaks = extract_peaks(heatmap, threshold=0.72, nms_radius=2)
    np.testing.assert_array_equal(peaks.coordinates, [[63, 7]])


def test_requested_checkpoint_loads_without_training():
    checkpoint = (
        Path(os.environ["FPBENCH_L3_METHOD_DIR"])
        / "artifacts/experiment-004/local-large/checkpoints/seed-40401/best.pt"
    )
    model, device, _metadata = load_model(checkpoint)
    assert not model.training
    result = infer_heatmap(model, np.zeros((31, 79), dtype=np.float32), device)
    assert result.shape == (31, 79) and np.isfinite(result).all()
