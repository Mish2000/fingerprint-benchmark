"""Run explicitly in the pinned pore environment; only synthetic pixels are used."""

import os
import sys
from pathlib import Path

import cv2
import numpy as np
import torch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).parent))
from common import survey_xy
from pore_worker import load_dahia, load_survey, tiled_survey


def test_actual_fcn_tiling_matches_whole_non_square_image(tmp_path):
    model, entire = load_survey(Path(os.environ["FPBENCH_L3_SURVEY_DIR"]))
    image = np.random.default_rng(40401).integers(0, 256, (83, 147), dtype=np.uint8)
    with torch.no_grad():
        full = model(torch.from_numpy(image.astype(np.float32) / 255)[None, None])
    tiled = tiled_survey(model, image, output_tile=32)
    torch.testing.assert_close(full, tiled, atol=2e-6, rtol=2e-5)
    # A known heatmap peak proves the upstream writer is zero-based row,column +8.
    prediction = torch.zeros((1, 1, 31, 79))
    prediction[0, 0, 2, 60] = 0.9
    entire.apply_nms(
        prediction, 0.65, 17, 0.2, str(tmp_path) + "/", 0, str(tmp_path) + "/", 17
    )
    row = tuple(map(int, (tmp_path / "0.txt").read_text().strip().split(",")))
    assert row == (10, 68)
    assert survey_xy([row]) == [(68, 10)]


def test_dahia_sift_receives_original_xy_and_handles_empty_or_single_features():
    utils, matching = load_dahia(Path(os.environ["FPBENCH_L3_DAHIA_DIR"]))
    image = np.random.default_rng(7).integers(0, 256, (73, 159), dtype=np.uint8)
    xy = np.asarray([[123, 21], [89, 51]], dtype=np.float32)
    actual = utils.sift_descriptors(image, xy[:, ::-1].copy(), scale=4)
    preprocessed = cv2.createCLAHE(clipLimit=3).apply(cv2.medianBlur(image, 3))
    _, expected = cv2.xfeatures2d.SIFT_create().compute(
        preprocessed, [cv2.KeyPoint(float(x), float(y), 4) for x, y in xy]
    )
    np.testing.assert_array_equal(actual, expected)
    assert (
        matching.spatial(np.empty((0, 128), np.float32), actual, [], xy, thr=0.7) == 0
    )
    # One correspondence contributes no pairs of distances: native spatial zero.
    assert matching.spatial(actual[:1], actual[:1], xy[:1], xy[:1], thr=0.7) == 0
