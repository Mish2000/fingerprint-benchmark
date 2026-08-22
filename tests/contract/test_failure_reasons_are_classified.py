"""A stage's classified-reason list is checked against the code that raises.

Each of Stages 19A, 19B and 20B declares ``CLASSIFIED_FAILURE_REASONS``: the
failure reasons its route produces *as an answer* rather than as a fault. The
condition ``no_unclassified_failure`` reads it, so the list decides whether a
run may call itself complete — which makes a hand-maintained list a liability.
A reason added to a translation module and forgotten here would silently start
blocking honest runs; one removed would silently stop blocking.

So the list is checked against the source that can raise it. The refusal classes
take the reason as their first positional argument, and the literals are read
out of the AST rather than out of anybody's memory.

**What is deliberately *not* required to be classified.** Everything a
comparison can fail with that is not one of those refusals: a mindtct exit code,
an unreadable bridge line, a timeout, a crash, an exception name, a free-text
vendor detail. Those failures are real and are stored honestly, and each one is
something a person has to read before the stage says it is done.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

#: ``stage module -> the sources whose refusals it must be able to name``.
#: A stage's route is its translation module, which is where a template that
#: cannot be represented at all is refused.
_ROUTES = {
    "fpbench.experiments.stage19a_finalization": (
        "src/fpbench/adapters/openafis/translation.py",
    ),
    "fpbench.experiments.stage19b_finalization": (
        "src/fpbench/adapters/openafis/capacity_extended.py",
    ),
    "fpbench.experiments.stage20b_finalization": (
        "src/fpbench/adapters/mcc/translation.py",
    ),
}

#: The exception classes whose first argument is the stored ``failure_reason``.
_REFUSAL_CLASSES = ("TranslationRefused", "MccTranslationRefused")


def _raised_reasons(relative: str) -> set[str]:
    tree = ast.parse((REPOSITORY_ROOT / relative).read_text(encoding="utf-8"))
    reasons: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id not in _REFUSAL_CLASSES:
            continue
        if node.args and isinstance(node.args[0], ast.Constant):
            reasons.add(node.args[0].value)
    return reasons


def _classified(module_name: str) -> frozenset[str]:
    import importlib

    return frozenset(
        getattr(importlib.import_module(module_name), "CLASSIFIED_FAILURE_REASONS")
    )


@pytest.mark.parametrize("module_name, sources", sorted(_ROUTES.items()))
def test_every_refusal_the_route_can_raise_is_classified(
    module_name: str, sources: tuple[str, ...]
) -> None:
    """The list cannot fall behind the code that produces the reasons."""
    raised: set[str] = set()
    for relative in sources:
        raised |= _raised_reasons(relative)
    assert raised, (
        f"{sources} raised no literal reason — the AST scan found nothing, which "
        "is a fault in this test rather than a clean route"
    )
    missing = sorted(raised - _classified(module_name))
    assert not missing, (
        f"{module_name}.CLASSIFIED_FAILURE_REASONS does not name {missing}, "
        f"which {sources} can raise. An unlisted reason makes an honest run "
        "fail no_unclassified_failure"
    )


@pytest.mark.parametrize("module_name", sorted(_ROUTES))
def test_no_stage_classifies_a_reason_that_is_a_fault(module_name: str) -> None:
    """The list is a vocabulary of *answers*, not an allowlist of excuses.

    Widening it is how ``no_unclassified_failure`` would be neutered: add
    ``bridge_crash_139`` and the condition stops noticing bridge crashes. These
    are the shapes that must never be in it — a crash, a timeout, a launch
    failure, an exception name.
    """
    forbidden = {
        "bridge_launch",
        "mindtct_launch",
        "mindtct_timeout",
        "mcc_bridge_timeout",
        "no_bridge_output",
        "unreadable_bridge_output",
        "unreadable_bridge_timings",
        "unknown_bridge_status",
        "unexpected_bridge_state",
        "unreadable_score",
        "sdk_refusal",
        "clr_failure",
        "bridge_refusal",
        "workspace_not_visible_to_windows",
    }
    named = sorted(forbidden & _classified(module_name))
    assert not named, (
        f"{module_name} classifies {named} as an upstream answer. Those are "
        "faults of ours or unread vendor text; a stage may not declare itself "
        "complete over them without somebody looking"
    )


@pytest.mark.parametrize("module_name", sorted(_ROUTES))
def test_the_condition_that_reads_the_list_exists(module_name: str) -> None:
    """A vocabulary nothing consults is decoration.

    The list only does anything because each stage's conditions include
    ``no_unclassified_failure``. This is the link between the two.
    """
    import importlib
    import inspect

    module = importlib.import_module(module_name)
    source = inspect.getsource(module)
    assert '"no_unclassified_failure"' in source, (
        f"{module_name} declares CLASSIFIED_FAILURE_REASONS and has no "
        "no_unclassified_failure condition to read it"
    )
