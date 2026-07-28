"""Shared fixtures.

Tests never touch the real SD300 tree unless they are marked ``dataset``.
Everything else runs against a synthetic release built in a temp directory, so
the suite is fast and works on a machine that has no copy of the data.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from fpbench.datasets.sd300.catalog import SD300DatasetProvider, SD300ReleaseLayout
from support import build_release


@pytest.fixture
def synthetic_root(tmp_path: Path) -> Path:
    """Two releases, five subjects, one of them incomplete in SD300B."""
    subjects = [f"0000100{n}" for n in range(5)]
    build_release(tmp_path, "SD300A", 500, subjects)
    build_release(tmp_path, "SD300B", 1000, subjects, omit={("00001004", "roll", 7)})
    return tmp_path


@pytest.fixture
def synthetic_provider(synthetic_root: Path) -> SD300DatasetProvider:
    return SD300DatasetProvider(
        root=synthetic_root,
        layouts=[
            SD300ReleaseLayout("SD300A", "sd300a"),
            SD300ReleaseLayout("SD300B", "sd300b"),
        ],
        read_png_metadata=True,
    )


@pytest.fixture(scope="session")
def sd300_root() -> Path:
    """The real dataset root, or skip the test."""
    value = os.environ.get("FPBENCH_SD300_ROOT")
    if not value or not Path(value).is_dir():
        pytest.skip("FPBENCH_SD300_ROOT is not set to an existing directory")
    return Path(value)
