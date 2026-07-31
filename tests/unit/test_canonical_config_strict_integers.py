"""Canonical integrity counts must be JSON integers, never coerced values."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from fpbench.experiments.sd300_canonical500_images import load_preparation_config
from fpbench.experiments.sourceafis_canonical500_full import (
    load_canonical_experiment_config,
)

REPO = Path(__file__).resolve().parents[2]
PREPARATION_CONFIG = (
    REPO / "configs" / "experiments" / "sd300_canonical500_images_v1.yaml"
)
CANONICAL_RUN_CONFIG = (
    REPO / "configs" / "experiments" / "sourceafis_canonical500_full_v1.yaml"
)
EXECUTION_PROFILE = (
    REPO / "configs" / "execution" / "canonical_500_lanczos3_60s_v1.yaml"
)
INVALID_INTEGERS = (2.5, "2", True, None)


def _document(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _write(tmp_path: Path, document) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


@pytest.mark.parametrize("value", INVALID_INTEGERS)
@pytest.mark.parametrize(
    "field",
    ("participating_images", "images_per_release", "comparisons"),
)
def test_preparation_shape_counts_require_exact_integers(tmp_path, field, value):
    document = _document(PREPARATION_CONFIG)
    document["expected_shape"][field] = value
    with pytest.raises(ValueError, match="exact integer"):
        load_preparation_config(_write(tmp_path, document), repository_root=REPO)


@pytest.mark.parametrize("value", INVALID_INTEGERS)
def test_preparation_source_ppi_requires_exact_integers(tmp_path, value):
    document = _document(PREPARATION_CONFIG)
    document["expected_shape"]["source_ppi"]["SD300A"] = value
    with pytest.raises(ValueError, match="exact integer"):
        load_preparation_config(_write(tmp_path, document), repository_root=REPO)


@pytest.mark.parametrize("value", INVALID_INTEGERS)
@pytest.mark.parametrize(
    "section,field",
    (
        ("experiment", "replicate_index"),
        ("execution", "retries"),
        ("expected_shape", "comparisons"),
        ("expected_shape", "per_release"),
        ("expected_shape", "per_stage"),
        ("expected_shape", "participating_images"),
    ),
)
def test_canonical_run_counts_require_exact_integers(
    tmp_path, section, field, value
):
    document = _document(CANONICAL_RUN_CONFIG)
    document[section][field] = value
    with pytest.raises(ValueError, match="exact integer"):
        load_canonical_experiment_config(
            _write(tmp_path, document),
            repository_root=REPO,
            execution_profile_config=EXECUTION_PROFILE,
        )


@pytest.mark.parametrize("value", INVALID_INTEGERS)
def test_canonical_run_source_ppi_requires_exact_integers(tmp_path, value):
    document = deepcopy(_document(CANONICAL_RUN_CONFIG))
    document["expected_shape"]["source_ppi"]["SD300C"] = value
    with pytest.raises(ValueError, match="exact integer"):
        load_canonical_experiment_config(
            _write(tmp_path, document),
            repository_root=REPO,
            execution_profile_config=EXECUTION_PROFILE,
        )
