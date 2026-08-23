"""Each stage's outcome contract is checked against the code that produces rows.

``OUTCOME_CONTRACT`` says what every ``status + failure_code`` of a route
requires of the rest of its row: which reasons the pair owns, whether it accepts
text nobody owns, and — on the scoring status — what a score has to be. The
validator refuses a row that disagrees, so a table that has fallen behind the
adapter refuses honest runs, and one that has run ahead accepts impossible ones.

Both directions are checked here, because only one of them announces itself. An
over-strict contract shows up as a run that could not be published and nobody
files a report about that.

* the statuses and codes the factories stamp are read out of the AST;
* every reason in ``PRODUCIBLE_OUTCOMES`` is checked against the pair that
  claims it, and ``PRODUCIBLE_OUTCOMES`` is itself checked against the literals
  the route's source can raise;
* ownership is checked for the property that makes it mean anything — that no
  two *families* claim the same reason.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

#: ``stage module -> (failure mapping, the sources whose refusals it carries)``.
_ROUTES = {
    "fpbench.experiments.stage19a_finalization": (
        "src/fpbench/adapters/openafis/failure_mapping.py",
        ("src/fpbench/adapters/openafis/translation.py",),
    ),
    "fpbench.experiments.stage19b_finalization": (
        "src/fpbench/adapters/openafis/failure_mapping.py",
        ("src/fpbench/adapters/openafis/capacity_extended.py",),
    ),
    "fpbench.experiments.stage20b_finalization": (
        "src/fpbench/adapters/mcc/failure_mapping.py",
        ("src/fpbench/adapters/mcc/translation.py",),
    ),
}

_SIDES = ("LEFT", "RIGHT", "BOTH")
_REFUSAL_CLASSES = ("TranslationRefused", "MccTranslationRefused")


def _module(name: str):
    return importlib.import_module(name)


def _status_codes(relative: str) -> dict[str, set[str]]:
    """``status -> the failure codes its factory stamps``, from the source."""
    tree = ast.parse((REPOSITORY_ROOT / relative).read_text(encoding="utf-8"))
    found: dict[str, set[str]] = {}
    for function in [n for n in tree.body if isinstance(n, ast.FunctionDef)]:
        statuses: set[str] = set()
        codes: set[str] = set()
        for node in ast.walk(function):
            if (
                isinstance(node, ast.Attribute)
                and getattr(node.value, "id", None) == "FailureCode"
            ):
                codes.add(node.attr.lower())
            if isinstance(node, ast.JoinedStr):
                literal = "".join(
                    part.value
                    for part in node.values
                    if isinstance(part, ast.Constant)
                )
                if literal.endswith("_"):
                    statuses.update(f"{literal}{side}" for side in _SIDES)
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                # A trailing underscore is an f-string prefix, already expanded.
                if (
                    node.value.isupper()
                    and "_" in node.value
                    and not node.value.endswith("_")
                ):
                    statuses.add(node.value)
        for status in statuses:
            found.setdefault(status, set()).update(codes)
    return found


def _raised_reasons(relatives: tuple[str, ...]) -> set[str]:
    reasons: set[str] = set()
    for relative in relatives:
        tree = ast.parse((REPOSITORY_ROOT / relative).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and getattr(node.func, "id", None) in _REFUSAL_CLASSES
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                reasons.add(node.args[0].value)
    return reasons


def _pairs(module_name: str):
    """``(status, code, rule)`` for every pair the contract declares."""
    contract = _module(module_name).OUTCOME_CONTRACT
    return [
        (status, code, rule)
        for status, shape in sorted(contract.items())
        for code, rule in sorted(shape.codes.items())
    ]


# ------------------------------------------------- the contract knows the route


@pytest.mark.parametrize("module_name", sorted(_ROUTES))
def test_the_contract_names_every_status_the_route_can_stamp(module_name: str) -> None:
    contract = _module(module_name).OUTCOME_CONTRACT
    mapping, _sources = _ROUTES[module_name]
    produced = set(_status_codes(mapping))
    missing = sorted(
        status
        for status in produced
        if status not in contract and not status.endswith("_BOTH")
    )
    assert not missing, (
        f"{module_name}.OUTCOME_CONTRACT does not know {missing}, which "
        f"{mapping} can stamp. The validator would refuse an honest run"
    )


@pytest.mark.parametrize("module_name", sorted(_ROUTES))
def test_every_code_the_factories_stamp_is_in_the_contract(module_name: str) -> None:
    contract = _module(module_name).OUTCOME_CONTRACT
    mapping, _sources = _ROUTES[module_name]
    wrong: list[str] = []
    for status, codes in sorted(_status_codes(mapping).items()):
        shape = contract.get(status)
        if shape is None or not codes:
            continue
        unlisted = sorted(codes - set(shape.codes))
        if unlisted:
            wrong.append(
                f"{status}: {mapping} stamps {unlisted}, contract has "
                f"{sorted(shape.codes)}"
            )
    assert not wrong, wrong


@pytest.mark.parametrize("module_name", sorted(_ROUTES))
def test_every_translation_refusal_is_owned_by_a_template_pair(
    module_name: str,
) -> None:
    """The reason a route raises must be claimed by the status that raises it.

    This is the link the whole cross-field check turns on: unclaimed, the reason
    would be free text that any open pair could carry.
    """
    module = _module(module_name)
    _mapping, sources = _ROUTES[module_name]
    raised = _raised_reasons(sources)
    assert raised, f"{sources} raised no literal reason — the scan found nothing"
    for reason in sorted(raised):
        owners = [
            f"{status}+{code}"
            for status, code, rule in _pairs(module_name)
            if rule.owns(reason)
        ]
        assert owners, f"{reason} is raised by {sources} and owned by no pair"
        assert all(
            "TEMPLATE" in owner or "REFUSAL" in owner for owner in owners
        ), f"{reason} is a translation refusal and is owned by {owners}"
        extractor = [
            f"{status}+{code}"
            for status, code, rule in _pairs(module_name)
            if status.startswith("MINDTCT_FAILED_") and rule.owns(reason)
        ]
        assert not extractor, (
            f"{reason} can be carried by {extractor}, which is the mismatch the "
            "contract exists to refuse"
        )


# ---------------------------------------------------- the contract is not strict


@pytest.mark.parametrize("module_name", sorted(_ROUTES))
def test_every_producible_row_is_legal_under_the_contract(module_name: str) -> None:
    """The over-strict direction, which nobody reports.

    ``BRIDGE_FAILURE`` once owned a single reason and, being closed, refused the
    other six the adapter emits — a contract that would have failed an honest
    run and never been noticed.
    """
    module = _module(module_name)
    contract = module.OUTCOME_CONTRACT
    illegal: list[str] = []
    for status, code, reason in sorted(module.PRODUCIBLE_OUTCOMES):
        shape = contract.get(status)
        rule = shape.codes.get(code) if shape else None
        if rule is None:
            illegal.append(f"({status}, {code}) is not in the contract")
            continue
        if rule.owns(reason) or rule.allow_unowned:
            continue
        illegal.append(f"({status}, {code}) refuses {reason!r}")
    assert not illegal, illegal


@pytest.mark.parametrize("module_name", sorted(_ROUTES))
def test_the_producible_set_covers_every_pair_the_contract_declares(
    module_name: str,
) -> None:
    """Otherwise the walk above proves nothing about the pair it skipped."""
    declared = {(status, code) for status, code, _rule in _pairs(module_name)}
    walked = {
        (status, code)
        for status, code, _reason in _module(module_name).PRODUCIBLE_OUTCOMES
    }
    missing = sorted(declared - walked)
    assert not missing, (
        f"{missing} are declared and never exercised by PRODUCIBLE_OUTCOMES"
    )


@pytest.mark.parametrize("module_name", sorted(_ROUTES))
def test_the_producible_set_contains_every_refusal_the_route_raises(
    module_name: str,
) -> None:
    _mapping, sources = _ROUTES[module_name]
    raised = _raised_reasons(sources)
    walked = {reason for _s, _c, reason in _module(module_name).PRODUCIBLE_OUTCOMES}
    missing = sorted(raised - walked)
    assert not missing, (
        f"{sources} raises {missing} and PRODUCIBLE_OUTCOMES never walks them"
    )


# ------------------------------------------------------------- structural rules


@pytest.mark.parametrize("module_name", sorted(_ROUTES))
def test_exactly_one_status_scores_and_it_bounds_its_score(module_name: str) -> None:
    contract = _module(module_name).OUTCOME_CONTRACT
    scoring = sorted(status for status, shape in contract.items() if shape.scored)
    assert scoring == ["OK"], scoring
    shape = contract["OK"]
    assert shape.score is not None, "the scoring status declares no score contract"
    assert shape.score.minimum < shape.score.maximum
    assert not shape.codes, "OK explains nothing, so it carries no failure code"


@pytest.mark.parametrize("module_name", sorted(_ROUTES))
def test_every_failing_status_declares_at_least_one_code(module_name: str) -> None:
    silent = sorted(
        status
        for status, shape in _module(module_name).OUTCOME_CONTRACT.items()
        if not shape.scored and not shape.codes
    )
    assert not silent, silent


@pytest.mark.parametrize("module_name", sorted(_ROUTES))
def test_no_reason_is_owned_by_two_families(module_name: str) -> None:
    """Ownership is what makes the cross-field check meaningful.

    Sided variants of one family share a vocabulary — which template failed is
    the side, the kind is the same — so families are compared, not statuses.
    """
    owners: dict[str, set[str]] = {}
    for status, _code, rule in _pairs(module_name):
        family = status.rsplit("_", 1)[0] if status.endswith(_SIDES) else status
        for reason in rule.reasons:
            owners.setdefault(reason, set()).add(family)
    shared = {reason: sorted(f) for reason, f in owners.items() if len(f) > 1}
    assert not shared, (
        f"{shared} are owned by more than one family, so the cross-field check "
        "cannot tell them apart"
    )


def test_the_openafis_score_contract_is_the_bridges_own() -> None:
    """``uint8_t`` on OK, ``-1`` on everything else — from the bridge's source."""
    from fpbench.experiments.stage19a_finalization import OUTCOME_CONTRACT

    bridge = (
        REPOSITORY_ROOT / "integrations/openafis/src/fpbench_openafis_bridge.cpp"
    ).read_text(encoding="utf-8", errors="replace")
    assert "uint8_t score {}" in bridge
    assert 'score_native_type\\tuint8_t' in bridge

    score = OUTCOME_CONTRACT["OK"].score
    assert (score.minimum, score.maximum, score.integral) == (0, 255, True)
    assert score.refusal(-1) is not None
    assert score.refusal(256) is not None
    assert score.refusal(255.5) is not None
    assert score.refusal(0) is None
    assert score.refusal(255) is None


def test_the_mcc_score_contract_is_the_sdks_own() -> None:
    from fpbench.adapters.mcc.identity import SCORE_MAXIMUM, SCORE_MINIMUM
    from fpbench.experiments.stage20b_finalization import OUTCOME_CONTRACT

    score = OUTCOME_CONTRACT["OK"].score
    assert (score.minimum, score.maximum) == (SCORE_MINIMUM, SCORE_MAXIMUM)
    assert score.integral is False, "the SDK's similarity is a double"
    assert score.refusal(0.5) is None
    assert score.refusal(-0.1) is not None
    assert score.refusal(1.5) is not None
