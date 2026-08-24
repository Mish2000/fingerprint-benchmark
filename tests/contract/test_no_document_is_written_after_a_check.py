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

**Two scans, because one function is not always where the defect is.** The
repository-wide scan below looks inside a single function, which is where this
family of defect was written. It also has a blind spot, and both halves of it
were occupied: ``ensure_report`` reached its replacing writer through a
one-line wrapper, and ``ManifestStore`` put the existence check in ``_guard``
and the replacement in ``_write_table``. Neither function *looked* like the
pattern and both were it.

Following calls fixes that and cannot be turned on everywhere: resolved
transitively, every stage publisher in ``experiments/`` matches, and those are
evidence markers, which ADR 0139 puts in the ``replace_*`` class deliberately —
a marker is *meant* to be regenerated. Exempting eighty-five of them would empty
this test of meaning. So the transitive scan is scoped to ``storage/``, which is
the layer that owns immutable artefacts, and the direct scan keeps covering the
rest of the tree.
"""

from __future__ import annotations

import ast
import sys
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
        "claim_text",
        "publish_set",
        "publish_json",
        "publish_bytes",
        "publish_table",
        "publish_text",
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

#: The layer whose artefacts are immutable, and the only one the transitive scan
#: is applied to. See the module docstring for why it is not the whole tree.
_STORAGE = "storage/"

#: Modules the transitive scan skips whole, because a published verifier pins
#: them byte-for-byte and the fix cannot land without re-issuing the stage.
#: One entry per module rather than one per wrapper: following calls makes every
#: ``ensure_*`` in these files match through their shared ``_ensure``, and a
#: dozen exemptions would say twelve times what this says once.
#: tests/contract/test_pinned_verifier_sources_are_untouched.py records the cost.
_PINNED_MODULES = frozenset(
    {
        "storage/modern_matcher_store.py",
        "storage/flx_store.py",
    }
)


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


def _functions(tree: ast.Module) -> dict[str, ast.AST]:
    return {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _reachable(direct: dict[str, set[str]], name: str) -> set[str]:
    """Every call ``name`` can reach without leaving its own module.

    Within the module, because that is where a wrapper hides — ``ensure_report``
    calling ``write_text_atomically`` five lines up, ``_write_table`` calling
    ``_guard``. Crossing modules would mean resolving imports, and the two
    functions this had to see are both one hop away in the same file.
    """
    seen: set[str] = set(direct.get(name, ()))
    frontier = set(seen)
    while frontier:
        following: set[str] = set()
        for call in frontier:
            following |= direct.get(call, set())
        following -= seen
        seen |= following
        frontier = following
    return seen


def _storage_offenders() -> list[str]:
    """The same rule as :func:`_offenders`, following calls inside the module."""
    found: list[str] = []
    for path in sorted((SOURCE / "storage").rglob("*.py")):
        relative = path.relative_to(SOURCE.parent).as_posix().removeprefix("fpbench/")
        if relative in _PINNED_MODULES:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - the tree compiles in CI
            continue
        functions = _functions(tree)
        direct = {name: _called(node) for name, node in functions.items()}
        checks = {name: _tests_existence(node) for name, node in functions.items()}
        exclusive = {name: _opens_exclusively(node) for name, node in functions.items()}
        for name in functions:
            reached = _reachable(direct, name)
            within = {call for call in reached if call in functions}
            if not (checks[name] or any(checks[call] for call in within)):
                continue
            if not reached & _REPLACERS:
                continue
            if reached & _CLAIMS:
                continue
            if exclusive[name] or any(exclusive[call] for call in within):
                continue
            found.append(f"{relative}::{name}")
    return found


def test_no_storage_function_reaches_a_replacing_writer_after_a_check() -> None:
    """The rule again, this time seeing through wrappers and helpers.

    Both blind spots of the direct scan were occupied when this was written:
    ``metric_set_store.ensure_report`` and ``paired_evaluation_store.ensure_report``
    replaced through a wrapper, and ``ManifestStore``'s six writers checked in
    ``_guard`` and replaced in ``_write_table``. All eight passed the scan below.
    """
    new = sorted(set(_storage_offenders()) - _EXEMPT)
    assert not new, (
        f"{new} reach a replacing writer, through their own module's helpers, on a "
        "path that first tests whether the document is there. Claim the name — "
        "claim_document, claim_text, or publish_set for a set that is more than "
        "one file — or make the replacement deliberate and separate, the way "
        "ManifestStore's overwrite=True is"
    )


#: The two shapes the direct scan cannot see, written out. Kept as source rather
#: than described in prose because a scanner is only worth what it still matches,
#: and the storage layer is clean — so with nothing left to find, this test is
#: the only thing standing between a broken scan and a green one.
_BLIND_SPOTS = '''
def write_text_atomically(path, text):
    return replace_text(path, text)

def ensure_report(self, path, markdown):
    if path.is_file():
        return path
    return write_text_atomically(path, markdown)

class Store:
    def _guard(self, path, overwrite):
        if path.exists() and not overwrite:
            raise Exists(path)

    def _write_table(self, path, table, overwrite):
        self._guard(path, overwrite)
        replace_table(path, table)

    def write_images(self, records, overwrite=False):
        return self._write_table(self.images_path(), to_table(records), overwrite)
'''


def test_the_transitive_scan_still_sees_through_a_wrapper_and_a_helper(
    tmp_path, monkeypatch
) -> None:
    """A scan that quietly stops matching reads exactly like a clean layer.

    Both shapes below were live in this repository and both passed the direct
    scan: a report replaced through a one-line wrapper, and a manifest checked in
    one helper and replaced in another.
    """
    storage = tmp_path / "fpbench" / "storage"
    storage.mkdir(parents=True)
    (storage / "blind_spots.py").write_text(_BLIND_SPOTS, encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "SOURCE", tmp_path / "fpbench")

    found = set(_storage_offenders())
    assert found == {
        "storage/blind_spots.py::ensure_report",
        "storage/blind_spots.py::_write_table",
        "storage/blind_spots.py::write_images",
    }, f"the transitive scan has stopped seeing its own examples: {sorted(found)}"


def test_every_pinned_module_skipped_by_the_transitive_scan_is_really_pinned() -> None:
    """An exemption nobody can lose track of.

    The skip is worth exactly as much as the pinning that justifies it. When a
    module leaves the pinned sets its ``_ensure`` becomes fixable, and the entry
    here has to go — so this fails the moment that happens rather than leaving a
    module quietly unscanned.
    """
    import importlib

    pinned: set[str] = set()
    for module_name in (
        "fpbench.modern_matchers.verify",
        "fpbench.flx.verify",
        "fpbench.experiments.stage8c_verify",
    ):
        pinned.update(importlib.import_module(module_name)._VERIFIER_AUTHORITY_PATHS)

    freed = sorted(
        relative
        for relative in _PINNED_MODULES
        if f"src/fpbench/{relative}" not in pinned
    )
    assert not freed, (
        f"{freed} are skipped by the transitive scan and are no longer pinned by "
        "any published verifier. Fix them and delete the entry"
    )


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
