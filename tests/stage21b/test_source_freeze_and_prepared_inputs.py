"""The two properties a 441,000-comparison run cannot discover late.

An execution-source identity that depends on the checkout binds six sealed
result sets to one machine, and a prepared-input gate that re-decodes 3,000
images 49 times per method spends hours proving what it proved on the first
pair.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pytest

from fpbench.stage21b.errors import Stage21BPreflightError
from fpbench.stage21b.errors import Stage21BIntegrityError
from fpbench.stage21b.evidence import _verify_source_map
from fpbench.stage21b.prepared import FrozenPreparedInputs
from fpbench.stage21b.source_freeze import (
    _SOURCE_DIRECTORIES,
    _SOURCE_FILES,
    execution_source_file_sha256s,
    source_file_sha256,
)

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.stage21b_contract

_BODY = "import os\nvalue = 1\n"


def test_the_execution_source_digest_does_not_depend_on_the_checkout(tmp_path) -> None:
    lf = tmp_path / "lf.py"
    crlf = tmp_path / "crlf.py"
    lf.write_bytes(_BODY.encode("utf-8"))
    crlf.write_bytes(_BODY.replace("\n", "\r\n").encode("utf-8"))

    assert lf.read_bytes() != crlf.read_bytes()
    assert source_file_sha256(lf) == source_file_sha256(crlf)
    assert (
        source_file_sha256(crlf)
        == hashlib.sha256(_BODY.encode("utf-8")).hexdigest()
    )


def test_a_real_content_change_still_moves_the_execution_source_digest(tmp_path) -> None:
    first = tmp_path / "a.py"
    second = tmp_path / "b.py"
    first.write_bytes(b"value = 1\n")
    second.write_bytes(b"value = 2\n")
    assert source_file_sha256(first) != source_file_sha256(second)


def test_every_closure_file_hashes_to_its_line_ending_normalised_bytes() -> None:
    """The property above, asserted over the files an actual run will hash.

    Ninety-five of these are CRLF in a ``core.autocrlf=true`` working copy and
    LF in the index, so this is the assertion that keeps ``stage21b-verify``
    reproducible off the machine that publishes the run.
    """
    paths: set[Path] = set()
    for relative in _SOURCE_DIRECTORIES:
        paths.update((ROOT / relative).rglob("*.py"))
    paths.update(ROOT / relative for relative in _SOURCE_FILES)
    assert paths
    for path in sorted(paths):
        assert path.is_file(), path
        normalised = path.read_bytes().replace(b"\r\n", b"\n")
        assert source_file_sha256(path) == hashlib.sha256(normalised).hexdigest()


def test_a_missing_execution_source_file_is_refused_not_skipped(tmp_path) -> None:
    with pytest.raises(Stage21BPreflightError, match="cannot hash execution source"):
        source_file_sha256(tmp_path / "absent.py")


def test_a_self_consistent_but_truncated_execution_closure_is_refused() -> None:
    files = execution_source_file_sha256s(
        repository_root=ROOT,
        algorithm_config=(
            ROOT / "configs/algorithms/sourceafis_java_3_18_1.yaml"
        ),
        include_flx=False,
    )
    files.pop("src/fpbench/stage21b/runner.py")
    with pytest.raises(Stage21BIntegrityError, match="closure is not exact"):
        _verify_source_map(
            ROOT,
            files,
            adapter_id="sourceafis_java_subprocess",
        )


@dataclass
class _Entry:
    image_id: str
    relative_path: str


class _CountingStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.calls: list[str] = []

    def verify_entry(self, entry, *, profile):  # noqa: ANN001 - storage shape
        self.calls.append(str(entry.image_id))
        return self.root / entry.relative_path


def _inputs(root: Path) -> tuple[FrozenPreparedInputs, _CountingStore]:
    store = _CountingStore(root)
    inputs = object.__new__(FrozenPreparedInputs)
    inputs.workspace = root
    inputs.store = store
    inputs.profile = object()
    inputs.verify_prepared_bytes = True
    inputs._verified = {}
    inputs._references = {}
    return inputs, store


def test_each_distinct_prepared_image_is_verified_once_not_once_per_pair(tmp_path) -> None:
    (tmp_path / "images").mkdir()
    entry = _Entry(image_id="img_a", relative_path="images/a.png")
    (tmp_path / entry.relative_path).write_bytes(b"canonical-bytes")
    inputs, store = _inputs(tmp_path)

    paths = {inputs._verified_path(entry) for _ in range(49)}

    assert store.calls == ["img_a"]
    assert paths == {(tmp_path / entry.relative_path).resolve()}


def test_a_prepared_artefact_replaced_mid_run_is_verified_again(tmp_path) -> None:
    (tmp_path / "images").mkdir()
    entry = _Entry(image_id="img_a", relative_path="images/a.png")
    target = tmp_path / entry.relative_path
    target.write_bytes(b"canonical-bytes")
    inputs, store = _inputs(tmp_path)

    inputs._verified_path(entry)
    target.write_bytes(b"canonical-bytes-but-longer")
    inputs._verified_path(entry)

    assert store.calls == ["img_a", "img_a"]


def test_a_prepared_artefact_that_vanished_is_an_infrastructure_refusal(tmp_path) -> None:
    (tmp_path / "images").mkdir()
    entry = _Entry(image_id="img_a", relative_path="images/a.png")
    inputs, _store = _inputs(tmp_path)
    with pytest.raises(Stage21BPreflightError, match="prepared input is unavailable"):
        inputs._verified_path(entry)
