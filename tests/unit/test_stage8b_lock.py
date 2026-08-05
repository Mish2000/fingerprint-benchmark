"""The lock is only a lock if something refuses what disagrees with it."""

from __future__ import annotations

from pathlib import Path

import pytest

from fpbench.core.flx_errors import FlxRuntimeLockError
from fpbench.flx.lock import load_runtime_lock, unexpected_wheels, verify_wheel_directory

pytestmark = pytest.mark.stage8b_contract

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = REPOSITORY_ROOT / "configs" / "flx" / "flx_runtime_lock_v1.txt"


def test_the_committed_lock_parses_and_pins_the_runtime() -> None:
    lock = load_runtime_lock(LOCK_PATH)

    names = {item.canonical_name for item in lock.distributions}
    assert {"torch", "torchvision", "numpy"} <= names
    assert lock.require_version("torch") == "2.13.0+cpu"
    assert lock.require_version("torchvision") == "0.28.0+cpu"
    assert len(lock.sha256) == 64


def test_every_pin_names_its_exact_wheel_size_and_index() -> None:
    for distribution in load_runtime_lock(LOCK_PATH).distributions:
        assert distribution.filename.endswith(".whl")
        assert distribution.size_bytes > 0
        assert len(distribution.sha256) == 64
        assert distribution.index.startswith("https://")


def test_torch_comes_from_the_cpu_index_not_pypi() -> None:
    # docs/adr/0072: the PyPI wheels of the same version pull the CUDA runtime
    # into a profile that has no device.
    lock = load_runtime_lock(LOCK_PATH)
    for name in ("torch", "torchvision"):
        assert lock.by_name[name].index == "https://download.pytorch.org/whl/cpu"
        assert "+cpu" in lock.by_name[name].version


def test_a_version_without_the_bytes_it_names_is_not_a_lock(tmp_path: Path) -> None:
    path = tmp_path / "unpinned.txt"
    path.write_text("torch==2.13.0+cpu \\\n    --hash=sha256:" + "a" * 64 + "\n", encoding="utf-8")

    with pytest.raises(FlxRuntimeLockError, match="wheel filename, size and index"):
        load_runtime_lock(path)


def test_a_pin_without_a_hash_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "nohash.txt"
    path.write_text(
        "# torch-2.13.0+cpu-cp312-cp312-manylinux_2_28_x86_64.whl\n"
        "#   size: 1\n"
        "#   index: https://download.pytorch.org/whl/cpu\n"
        "torch==2.13.0+cpu \\\n",
        encoding="utf-8",
    )

    with pytest.raises(FlxRuntimeLockError, match="ends before the last --hash"):
        load_runtime_lock(path)


def test_a_lock_missing_torch_cannot_run_a_worker(tmp_path: Path) -> None:
    path = tmp_path / "partial.txt"
    path.write_text(
        "# numpy-2.5.1-cp312-cp312-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl\n"
        "#   size: 16672469\n"
        "#   index: https://pypi.org/simple\n"
        "numpy==2.5.1 \\\n    --hash=sha256:" + "b" * 64 + "\n",
        encoding="utf-8",
    )

    with pytest.raises(FlxRuntimeLockError, match="cannot run without torch pinned"):
        load_runtime_lock(path)


def test_a_missing_lock_names_the_path() -> None:
    with pytest.raises(FlxRuntimeLockError, match="runtime lock not found"):
        load_runtime_lock(Path("no-such-lock.txt"))


def test_an_installed_runtime_matching_the_lock_is_accepted() -> None:
    lock = load_runtime_lock(LOCK_PATH)
    observed = {item.name: item.version for item in lock.distributions}

    lock.verify_installed(observed)


def test_a_missing_distribution_is_refused() -> None:
    lock = load_runtime_lock(LOCK_PATH)
    observed = {item.name: item.version for item in lock.distributions}
    del observed["numpy"]

    with pytest.raises(FlxRuntimeLockError, match="missing=\\['numpy'\\]"):
        lock.verify_installed(observed)


def test_an_unpinned_distribution_is_refused_as_loudly_as_a_missing_one() -> None:
    # This is what --without-pip buys: an extra distribution in the runtime is
    # exactly how an unpinned dependency hides.
    lock = load_runtime_lock(LOCK_PATH)
    observed = {item.name: item.version for item in lock.distributions}
    observed["opencv-python"] = "4.10.0"

    with pytest.raises(FlxRuntimeLockError, match="unpinned=\\['opencv-python'\\]"):
        lock.verify_installed(observed)


def test_a_drifted_version_is_refused() -> None:
    lock = load_runtime_lock(LOCK_PATH)
    observed = {item.name: item.version for item in lock.distributions}
    observed["torch"] = "2.12.1+cpu"

    with pytest.raises(FlxRuntimeLockError, match="torch locked 2.13.0\\+cpu but installed 2.12.1"):
        lock.verify_installed(observed)


def test_distribution_names_are_compared_canonically() -> None:
    # typing_extensions and typing-extensions are the same distribution; a lock
    # that disagreed with importlib.metadata about that would be unusable.
    lock = load_runtime_lock(LOCK_PATH)
    observed = {item.name: item.version for item in lock.distributions}
    observed["typing-extensions"] = observed.pop("typing_extensions")

    lock.verify_installed(observed)


def test_wheel_verification_reports_a_missing_wheel(tmp_path: Path) -> None:
    lock = load_runtime_lock(LOCK_PATH)

    with pytest.raises(FlxRuntimeLockError, match="missing from the bundle"):
        verify_wheel_directory(lock, tmp_path)


def test_a_wheel_the_lock_does_not_name_is_reported(tmp_path: Path) -> None:
    lock = load_runtime_lock(LOCK_PATH)
    (tmp_path / "sneaky-1.0-py3-none-any.whl").write_bytes(b"")

    assert unexpected_wheels(lock, tmp_path) == ["sneaky-1.0-py3-none-any.whl"]


def test_a_resized_wheel_fails_before_it_is_hashed(tmp_path: Path) -> None:
    lock = load_runtime_lock(LOCK_PATH)
    for distribution in lock.distributions:
        (tmp_path / distribution.filename).write_bytes(b"not the real wheel")

    with pytest.raises(FlxRuntimeLockError, match="byte size changed"):
        verify_wheel_directory(lock, tmp_path)
