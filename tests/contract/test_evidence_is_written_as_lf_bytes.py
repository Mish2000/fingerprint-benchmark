"""Evidence is hashed over raw bytes, so its line endings are load-bearing.

Stage 15A published six content hashes computed over CRLF. The gate was green
on the machine that wrote them and red in every clean checkout, because
``.gitattributes`` pins ``evidence/**`` to LF and the marker compares bytes.

Repairing the hashes did not repair the cause. The writer still reached the
disk through ``Path.write_text``, which translates ``\\n`` to ``\\r\\n`` on
Windows, so the next publication would have put them back. These three tests
are the three places the property can be checked: the writer, the module that
holds it, and the committed tree.
"""

from __future__ import annotations

import ast
import json
import tempfile
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = REPOSITORY_ROOT / "evidence"

#: Publishers whose output lands in ``evidence/``. A stage added later belongs
#: here; the test fails loudly if the module exists and the writer does not,
#: rather than skipping quietly.
_EVIDENCE_WRITERS = (
    ("fpbench.experiments.stage15a_finalization", "_write_json"),
    ("fpbench.experiments.stage8e_finalization", "write_evidence_json"),
)


@pytest.mark.parametrize("module_name,writer_name", _EVIDENCE_WRITERS)
def test_the_publisher_writes_lf_whatever_the_platform(
    module_name: str, writer_name: str
) -> None:
    """Run the writer and read back the bytes it actually produced."""
    import importlib

    module = importlib.import_module(module_name)
    writer = getattr(module, writer_name)

    document = {
        "a": 1,
        "nested": {"b": "two", "c": [1, 2, 3]},
        "text": "a value with no newline of its own",
    }
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory) / "probe.json"
        writer(target, document)
        raw = target.read_bytes()

    assert b"\r\n" not in raw, (
        f"{module_name}.{writer_name} emitted CRLF. Evidence is compared "
        "byte-for-byte against what a verifier re-derives, so this makes the "
        "marker agree with one machine and disagree with every other"
    )
    assert json.loads(raw.decode("utf-8")) == document


@pytest.mark.parametrize("module_name,writer_name", _EVIDENCE_WRITERS)
def test_no_evidence_writer_reaches_the_disk_through_write_text(
    module_name: str, writer_name: str
) -> None:
    """The writer above cannot pass by accident: check what it calls.

    A body that round-trips correctly today because the test happens to run on
    a machine with ``\\n`` line endings would pass the first test and fail in
    CI. This one reads the source.
    """
    import importlib

    module = importlib.import_module(module_name)
    source = Path(module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != writer_name:
            continue
        for call in ast.walk(node):
            if isinstance(call, ast.Call):
                attribute = getattr(call.func, "attr", None)
                assert attribute != "write_text", (
                    f"{module_name}.{writer_name} writes through write_text, "
                    "which emits CRLF on Windows. Encode and use write_bytes"
                )
        return

    raise AssertionError(f"{module_name} has no {writer_name}")


def test_no_committed_evidence_file_carries_a_carriage_return() -> None:
    """The property, checked over the tree rather than over one writer.

    Publisher-agnostic on purpose: a stage that grows its own writer, or an
    evidence file edited by hand, is caught here without anyone remembering to
    add it to the list above.

    Reads the **committed blob** rather than the working file, because those
    differ and it is the blob every other machine will read. ``.gitattributes``
    normalises on commit, so a publisher that emitted CRLF leaves a CRLF file
    in this checkout and an LF blob in the commit; checking the working copy
    would report an ordinary Windows checkout as broken, and would still miss a
    CRLF blob committed from a machine with no normalisation configured.
    """
    import subprocess

    if not EVIDENCE.is_dir():  # pragma: no cover - the tree carries evidence
        pytest.skip("no evidence directory in this checkout")

    listing = subprocess.run(
        ["git", "ls-files", "-z", "--", "evidence"],
        cwd=str(REPOSITORY_ROOT),
        capture_output=True,
        check=True,
    )
    offenders = []
    for relative in listing.stdout.decode("utf-8").split("\0"):
        if not relative or not relative.lower().endswith((".json", ".md")):
            continue
        blob = subprocess.run(
            ["git", "show", f"HEAD:{relative}"],
            cwd=str(REPOSITORY_ROOT),
            capture_output=True,
            check=True,
        )
        if b"\r\n" in blob.stdout:
            offenders.append(relative)

    assert not offenders, (
        "these evidence blobs carry CRLF in the commit, so their content "
        f"hashes differ between checkouts: {offenders}"
    )
