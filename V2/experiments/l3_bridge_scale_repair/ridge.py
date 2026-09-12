"""Versioned rotation-sign repair of Experiment 004's ridge-period estimator.

Source: fingerprint-new-method@732099d9faef124bd030be564c1e751faf1e9c72,
src/fingerprint_new_method/experiment004_transfer.py (SHA-256 in settings.json).
The tile estimator differs only at rotation_degrees. Image normalization,
tile placement, acceptance and median/MAD aggregation retain the original rules.
The original module is imported read-only and is never patched.
"""

from __future__ import annotations

import math

import cv2
import numpy as np
from fingerprint_new_method.experiment004 import robust_normalize_uint8
from fingerprint_new_method.experiment004_transfer import (
    RidgePeriodEstimate,
    _structure_tensor_orientation,
    _tile_starts,
)

ESTIMATOR_VERSION = "experiment004-ridge-rotation-sign-v1"


def estimate_tile_ridge_period(tile: np.ndarray) -> tuple[float, float] | None:
    """Estimate ridge-to-ridge period in one frozen 256-pixel tile."""
    if tile.shape != (256, 256):
        raise ValueError(f"Expected 256x256 tile, got {tile.shape}")
    values = tile.astype(np.float32)
    if float(np.std(values)) < 8.0:
        return None
    orientation, coherence = _structure_tensor_orientation(values)
    if coherence < 0.20:
        return None
    rotation_degrees = math.degrees(orientation) - 90.0
    matrix = cv2.getRotationMatrix2D((127.5, 127.5), rotation_degrees, 1.0)
    rotated = cv2.warpAffine(
        values,
        matrix,
        (256, 256),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REFLECT_101,
    )
    crop = rotated[32:224, 32:224]
    profile = np.mean(crop, axis=0).astype(np.float64)
    trend = cv2.GaussianBlur(profile.reshape(1, -1), (0, 0), sigmaX=24.0).reshape(-1)
    profile -= trend
    profile -= float(np.mean(profile))
    energy = float(np.dot(profile, profile))
    if energy <= 1e-9:
        return None
    autocorrelation = np.correlate(profile, profile, mode="full")[len(profile) - 1 :]
    normalizer = np.arange(len(profile), 0, -1, dtype=np.float64)
    autocorrelation = autocorrelation / normalizer
    autocorrelation /= max(float(autocorrelation[0]), 1e-12)
    candidates = [
        lag
        for lag in range(5, 65)
        if autocorrelation[lag] >= autocorrelation[lag - 1]
        and autocorrelation[lag] > autocorrelation[lag + 1]
    ]
    if not candidates:
        return None
    peak = max(float(autocorrelation[lag]) for lag in candidates)
    if peak < 0.15:
        return None
    selected = min(lag for lag in candidates if autocorrelation[lag] >= 0.90 * peak)
    return float(selected), float(autocorrelation[selected])


def aggregate(periods, correlations, candidate_tiles):
    """The historical minimum-five, median and MAD/median <= .25 rules."""
    if len(periods) < 5:
        return RidgePeriodEstimate(
            "UNRELIABLE_TOO_FEW_TILES",
            None,
            tuple(periods),
            tuple(correlations),
            candidate_tiles,
            len(periods),
            None,
        )
    median = float(np.median(periods))
    mad_ratio = float(np.median(np.abs(np.asarray(periods) - median)) / median)
    if mad_ratio > 0.25:
        return RidgePeriodEstimate(
            "UNRELIABLE_DISPERSION",
            None,
            tuple(periods),
            tuple(correlations),
            candidate_tiles,
            len(periods),
            mad_ratio,
        )
    return RidgePeriodEstimate(
        "OK",
        median,
        tuple(periods),
        tuple(correlations),
        candidate_tiles,
        len(periods),
        mad_ratio,
    )


def estimate_ridge_period(gray):
    """Estimate once per image; observational tile diagnostics do not filter it."""
    normalized = robust_normalize_uint8(gray)
    periods, correlations, tiles = [], [], []
    for y in _tile_starts(normalized.shape[0], 256, 128):
        for x in _tile_starts(normalized.shape[1], 256, 128):
            tile = normalized[y : y + 256, x : x + 256]
            result = estimate_tile_ridge_period(tile)
            # Coherence was not persisted by v1. Record it here for all candidates.
            _, coherence = _structure_tensor_orientation(tile)
            tiles.append(
                {
                    "x": x,
                    "y": y,
                    "coherence": coherence,
                    "period_px": result[0] if result else None,
                    "correlation": result[1] if result else None,
                }
            )
            if result is not None:
                periods.append(result[0])
                correlations.append(result[1])
    return {**aggregate(periods, correlations, len(tiles)).as_dict(), "tiles": tiles}


def resize_from_policy(gray, policy):
    """Use a saved estimate, without recomputation, clipping or fallback."""
    if policy["status"] != "OK":
        raise ValueError(policy["reason"])
    factor = policy["factor"]
    interpolation = cv2.INTER_AREA if factor < 1.0 else cv2.INTER_CUBIC
    return cv2.resize(gray, None, fx=factor, fy=factor, interpolation=interpolation)
