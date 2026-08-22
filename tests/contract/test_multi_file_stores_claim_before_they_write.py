"""Every store that publishes a manifest *and* a body claims the manifest first.

Five stores had the same shape, because each was written by copying the last
one: check for the manifest, write the body with a replacing writer, publish the
manifest create-if-absent. Two writers with different content both pass the
check, both replace the body, and one is then refused the manifest — leaving one
writer's manifest over the other writer's rows, with a fingerprint that
describes rows nobody can read any more.

The remedy is :func:`fpbench.storage.set_publication.publish_set`, and the
reason this is a contract test rather than five unit tests is that the defect
propagated by imitation. The next store will be written the same way.

What is checked is the *order*, statically: a module that writes a body before
it has a claim is the bug, whatever its tests happen to exercise.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
STORAGE = REPOSITORY_ROOT / "src" / "fpbench" / "storage"

#: The stores that publish a manifest describing a separate body file.
_MULTI_FILE_STORES = (
    "result_set_store.py",
    "decision_set_store.py",
    "eligibility_set_store.py",
    "evaluation_view_store.py",
    "metric_set_store.py",
)

#: Writers that replace whatever is there. Legitimate for a body a claim
#: already covers; never legitimate for the manifest that *is* the claim.
_REPLACING_WRITERS = frozenset({"write_json", "replace_table", "replace_bytes"})


def _module(name: str) -> ast.Module:
    return ast.parse((STORAGE / name).read_text(encoding="utf-8"))


def _calls(node: ast.AST) -> list[ast.Call]:
    return [child for child in ast.walk(node) if isinstance(child, ast.Call)]


def _name_of(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


@pytest.mark.parametrize("store", _MULTI_FILE_STORES)
def test_the_store_publishes_its_set_through_the_shared_claim(store: str) -> None:
    names = {_name_of(call) for call in _calls(_module(store))}
    assert "publish_set" in names, (
        f"{store} publishes a manifest and a body without claiming the set "
        "first. Use fpbench.storage.set_publication.publish_set: the manifest "
        "is the claim, and only its owner writes the body (docs/adr/0139)"
    )


@pytest.mark.parametrize("store", _MULTI_FILE_STORES)
def test_no_body_is_written_before_the_set_is_claimed(store: str) -> None:
    """Within one function: the claim, then the writes.

    A replacing write that runs before ``publish_set`` in the same function is
    the original order restored — the body goes down while the set is still
    unowned.
    """
    module = _module(store)
    for function in ast.walk(module):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        calls = _calls(function)
        claims = [call for call in calls if _name_of(call) == "publish_set"]
        if not claims:
            continue
        claimed_at = min(call.lineno for call in claims)
        early = sorted(
            {
                f"{_name_of(call)}:{call.lineno}"
                for call in calls
                if _name_of(call) in _REPLACING_WRITERS and call.lineno < claimed_at
            }
        )
        assert not early, (
            f"{store}.{function.name} writes {early} before publish_set on line "
            f"{claimed_at}. The body must not be written until the manifest has "
            "claimed the set"
        )


@pytest.mark.parametrize("store", _MULTI_FILE_STORES)
def test_the_manifest_itself_is_never_written_with_a_replacing_writer(
    store: str,
) -> None:
    """``write_json(manifest_path, ...)`` is the defect in one line.

    Whatever else a store does, the file that decides who owns the set is
    published exactly once or not at all.
    """
    module = _module(store)
    offending = []
    for call in _calls(module):
        if _name_of(call) not in _REPLACING_WRITERS or not call.args:
            continue
        target = call.args[0]
        text = ast.unparse(target)
        if "manifest_path" in text or "manifest_path" == text:
            offending.append(f"{_name_of(call)}({text}) on line {call.lineno}")
    assert not offending, (
        f"{store} replaces its own manifest: {offending}. The manifest is the "
        "claim over the set and is published create-if-absent"
    )
