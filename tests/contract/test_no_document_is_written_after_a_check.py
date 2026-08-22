"""No store may check whether a document exists and then write it with a replacer.

Thirty functions across the storage layer had this shape, because each was
copied from the last::

    if path.is_file():
        <compare what is stored against what I hold>
        return path
    return write_json(path, mine)          # <- replaces

Two publishers that both find the path absent both pass the check and both
write; the second silently overwrites the first, and the only comparison in the
function is on the branch neither of them took. The reviewer found it in
``ResultStore`` first and in ``DefinitionStore`` a round later — which is the
signal that finding them one at a time is the wrong method.

So the rule is checked over the whole layer at once, statically. A function that
tests a path's existence *and* calls a replacing writer is refused unless it also
claims the name first, through
:func:`fpbench.storage.immutable_publication.claim_document` or
:func:`fpbench.storage.set_publication.publish_set`.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE = REPOSITORY_ROOT / "src" / "fpbench"

#: Writers that replace whatever is already at the path.
_REPLACERS = frozenset(
    {"write_json", "replace_table", "replace_bytes", "replace_text", "replace_file"}
)

#: Calls that let the filesystem decide who owns a name.
_CLAIMS = frozenset(
    {
        "claim_document",
        "publish_set",
        "publish_json",
        "publish_bytes",
        "publish_table",
        "publish_file",
        "_claim_marker",
    }
)

#: Functions allowed to replace a document after checking for it, and why.
#:
#: The two ``_archive_*`` helpers are the deliberate replacement: they copy the
#: old bytes aside first, which is the only way a schema upgrade can keep the
#: document it supersedes. The two stores are pinned by Stage 8A's and Stage
#: 8B's published verifiers — see
#: tests/contract/test_pinned_verifier_sources_are_untouched.py, which records
#: what moving them costs.
_EXEMPT = {
    "storage/result_store.py::_archive_publication",
    "storage/prepared_image_set_store.py::_archive_preparation_publication",
    "storage/modern_matcher_store.py::_ensure",
    "storage/flx_store.py::_ensure",
}


def _called(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            name = getattr(func, "attr", None) or getattr(func, "id", None)
            if name:
                names.add(name)
    return names


def _tests_existence(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and getattr(child.func, "attr", None) in {
            "is_file",
            "exists",
        }:
            return True
    return False


def _opens_exclusively(node: ast.AST) -> bool:
    """``open(path, "xb")`` is create-if-absent by another name."""
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        if getattr(child.func, "attr", None) != "open":
            continue
        for argument in child.args:
            if isinstance(argument, ast.Constant) and "x" in str(argument.value):
                return True
    return False


def _offenders() -> list[str]:
    found: list[str] = []
    for path in sorted(SOURCE.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - the tree compiles in CI
            continue
        relative = path.relative_to(SOURCE.parent).as_posix().removeprefix("fpbench/")
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not _tests_existence(node):
                continue
            called = _called(node)
            if not called & _REPLACERS:
                continue
            if called & _CLAIMS or _opens_exclusively(node):
                continue
            found.append(f"{relative}::{node.name}")
    return found


def test_the_scan_finds_the_functions_it_is_meant_to_find() -> None:
    """A scanner that matches nothing reports a clean layer.

    The exemptions are the proof that the pattern is still recognised: if the
    scan stopped working, they would stop being found and this would fail
    before the real check below could pass vacuously.
    """
    found = set(_offenders())
    missing = sorted(_EXEMPT - found)
    assert not missing, (
        f"the scan no longer recognises {missing} — either they were fixed "
        "(remove them from _EXEMPT) or this test has stopped working"
    )


def test_no_store_replaces_a_document_it_only_checked_for() -> None:
    new = sorted(set(_offenders()) - _EXEMPT)
    assert not new, (
        f"{new} test whether a document exists and then write it with a "
        "replacing writer. Two publishers can pass that check together and the "
        "second overwrites the first. Claim the name with "
        "fpbench.storage.immutable_publication.claim_document, or — for a set "
        "that is more than one file — with set_publication.publish_set"
    )


@pytest.mark.parametrize("exempt", sorted(_EXEMPT))
def test_every_exemption_still_names_a_real_function(exempt: str) -> None:
    """An exemption for a function that moved is one nobody will remove."""
    relative, _, name = exempt.partition("::")
    path = SOURCE / relative
    assert path.is_file(), f"{relative} is exempted and does not exist"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert name in names, f"{exempt} is exempted and {relative} has no {name}"
