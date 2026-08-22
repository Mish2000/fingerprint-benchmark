"""Whether an adapter re-verifies its runtime before every comparison.

``ContentClosureBinding`` publishes ``rechecked_per_comparison``, and the value
came from ``getattr(adapter, "rechecks_runtime_per_comparison", False)`` — an
attribute no adapter has ever defined. So every research closure published
``false`` while all six adapters call ``check_runtime_integrity()`` inside
``compare``. A provenance claim that understates is still a claim that is wrong,
and this one understates the thing a reader would most want to be true.

**Derived rather than declared.** A class attribute would be a second place the
answer lives, and the first thing to fall out of step: an adapter that stopped
re-checking would go on publishing ``true``. This reads the adapter's own
``compare`` — and the helpers it calls in the same class — for the call, so the
published claim is a statement about the code that runs.

The cost is an ``inspect.getsource`` at preflight, once per adapter class, and
the result is cached. An adapter whose source cannot be read (a C extension, an
exec'd class) answers ``False``: unknown provenance is published as the weaker
claim, never the stronger one.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from functools import lru_cache

__all__ = ["RUNTIME_INTEGRITY_CHECK", "rechecks_runtime_per_comparison"]

#: The method an adapter calls to re-verify its pinned assets. Not part of the
#: abstract base — it is a convention six adapters follow — which is exactly why
#: the answer has to be read rather than asked for.
RUNTIME_INTEGRITY_CHECK = "check_runtime_integrity"

#: Where a comparison begins. ``compare`` is the contract; the others are the
#: names the adapters here use for the work it delegates to.
_ENTRY_POINTS = ("compare", "_compare", "_match", "_run_comparison")


def _called_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            name = getattr(func, "attr", None) or getattr(func, "id", None)
            if name:
                names.add(name)
    return names


@lru_cache(maxsize=None)
def _class_rechecks(cls: type) -> bool:
    for klass in cls.__mro__:
        if klass is object:
            continue
        try:
            source = inspect.getsource(klass)
        except (OSError, TypeError):
            continue
        try:
            # ``dedent`` and not ``cleandoc``: a class defined inside another
            # scope comes back indented, and ``cleandoc`` strips the *docstring*
            # convention instead, which turns the body into a syntax error and
            # would have made this function quietly answer False for everything.
            tree = ast.parse(textwrap.dedent(source))
        except SyntaxError:  # pragma: no cover - the class compiled to get here
            continue

        methods = {
            node.name: node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        # From ``compare`` outward: the check may sit in the method the entry
        # point delegates to, which is how five of the six adapters are written.
        seen: set[str] = set()
        frontier = [name for name in _ENTRY_POINTS if name in methods]
        while frontier:
            name = frontier.pop()
            if name in seen:
                continue
            seen.add(name)
            called = _called_names(methods[name])
            if RUNTIME_INTEGRITY_CHECK in called:
                return True
            frontier.extend(sorted(called & set(methods) - seen))
    return False


def rechecks_runtime_per_comparison(adapter: object) -> bool:
    """Does ``adapter`` re-verify its pinned runtime on every comparison?

    Args:
        adapter: The adapter itself, or a wrapper holding one. A wrapper is
            unwrapped through ``_delegate`` so a research wrapper does not
            answer for the adapter it wraps.
    """
    subject = adapter
    for _ in range(8):  # a wrapper chain, not a cycle
        delegate = getattr(subject, "_delegate", None)
        if delegate is None or delegate is subject:
            break
        subject = delegate
    return _class_rechecks(type(subject))
