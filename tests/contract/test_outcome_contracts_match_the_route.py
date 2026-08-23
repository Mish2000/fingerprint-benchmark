"""Each stage's outcome contract is checked against the code that produces rows.

``OUTCOME_CONTRACT`` says what every status of a route requires of the rest of
its row: which ``failure_code`` it can carry, which ``failure_reason`` it owns,
and whether it means a score was produced. The validator refuses a row that
disagrees with it, so a table that has fallen behind the adapter would refuse
honest runs — and one that has run ahead would accept impossible ones.

So it is not maintained by hand and hoped over. The failure factories in each
route's ``failure_mapping`` set exactly two things this cares about: the status
they stamp on the row, and the ``FailureCode`` they carry. Both are literals in
the source, and both are read out of the AST here.

What is deliberately *not* derived is which reasons a status owns: those come
from several places (the translation's refusals, the bridge's own statuses, the
PNG input checks) and some are free text. Ownership is checked instead by the
property that matters — no two statuses may own the same reason, or the
cross-field check would refuse a row both of them could legitimately produce.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

#: ``stage module -> the failure mapping whose factories write its rows``.
_ROUTES = {
    "fpbench.experiments.stage19a_finalization": (
        "src/fpbench/adapters/openafis/failure_mapping.py"
    ),
    "fpbench.experiments.stage19b_finalization": (
        "src/fpbench/adapters/openafis/failure_mapping.py"
    ),
    "fpbench.experiments.stage20b_finalization": (
        "src/fpbench/adapters/mcc/failure_mapping.py"
    ),
}

#: The two sides a status can name. A factory writes ``f"..._{_side(side)}"``,
#: and the sides are the only thing that varies.
_SIDES = ("LEFT", "RIGHT", "BOTH")


def _status_codes(relative: str) -> dict[str, set[str]]:
    """``status -> the failure codes its factory can stamp``, from the source.

    The status is an f-string over ``_side(side)`` or a plain literal; the code
    is ``FailureCode.SOMETHING`` or the function's own ``code`` parameter, which
    is the one factory — ``infrastructure_failure`` — whose caller chooses.
    """
    tree = ast.parse((REPOSITORY_ROOT / relative).read_text(encoding="utf-8"))
    found: dict[str, set[str]] = {}
    for function in [n for n in tree.body if isinstance(n, ast.FunctionDef)]:
        statuses: set[str] = set()
        codes: set[str] = set()
        for node in ast.walk(function):
            if isinstance(node, ast.Attribute) and getattr(
                node.value, "id", None
            ) == "FailureCode":
                codes.add(node.attr.lower())
            if isinstance(node, ast.JoinedStr):
                literal = "".join(
                    part.value for part in node.values if isinstance(part, ast.Constant)
                )
                if literal.endswith("_"):
                    statuses.update(f"{literal}{side}" for side in _SIDES)
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                # A trailing underscore is an f-string prefix — the JoinedStr
                # branch above has already expanded it over the three sides.
                if (
                    node.value.isupper()
                    and "_" in node.value
                    and not node.value.endswith("_")
                ):
                    statuses.add(node.value)
        if not statuses:
            continue
        for status in statuses:
            found.setdefault(status, set()).update(codes)
    return found


def _contract(module_name: str):
    return getattr(importlib.import_module(module_name), "OUTCOME_CONTRACT")


@pytest.mark.parametrize("module_name, relative", sorted(_ROUTES.items()))
def test_the_contract_names_every_status_the_route_can_stamp(
    module_name: str, relative: str
) -> None:
    """A status the adapter can write and the contract does not know is refused."""
    contract = _contract(module_name)
    produced = set(_status_codes(relative))
    # ``_BOTH`` variants exist for every sided factory in the source; only the
    # ones a route actually declares are required here, because the adapter
    # decides which sides it can report.
    missing = sorted(
        status
        for status in produced
        if status not in contract and not status.endswith("_BOTH")
    )
    assert not missing, (
        f"{module_name}.OUTCOME_CONTRACT does not know {missing}, which "
        f"{relative} can stamp on a row. The validator would refuse an honest run"
    )


@pytest.mark.parametrize("module_name, relative", sorted(_ROUTES.items()))
def test_every_code_the_factories_stamp_is_allowed_by_the_contract(
    module_name: str, relative: str
) -> None:
    """The codes are literals in the source; the table has to agree with them."""
    contract = _contract(module_name)
    wrong: list[str] = []
    for status, codes in sorted(_status_codes(relative).items()):
        shape = contract.get(status)
        if shape is None or not codes:
            continue
        unlisted = sorted(codes - shape.codes)
        if unlisted:
            wrong.append(f"{status}: {relative} stamps {unlisted}, contract allows {sorted(shape.codes)}")
    assert not wrong, wrong


@pytest.mark.parametrize("module_name", sorted(_ROUTES))
def test_exactly_one_status_means_a_score_was_produced(module_name: str) -> None:
    contract = _contract(module_name)
    scored = sorted(status for status, shape in contract.items() if shape.scored)
    assert scored == ["OK"], scored


@pytest.mark.parametrize("module_name", sorted(_ROUTES))
def test_the_scoring_status_carries_no_failure_detail(module_name: str) -> None:
    """``OK`` explains nothing, because there is nothing to explain."""
    shape = _contract(module_name)["OK"]
    assert shape.codes == frozenset()
    assert shape.reasons == frozenset()
    assert shape.reason_pattern is None


@pytest.mark.parametrize("module_name", sorted(_ROUTES))
def test_every_failing_status_names_at_least_one_code(module_name: str) -> None:
    """A failure with no allowed code could never be recorded at all."""
    silent = sorted(
        status
        for status, shape in _contract(module_name).items()
        if not shape.scored and not shape.codes
    )
    assert not silent, silent


@pytest.mark.parametrize("module_name", sorted(_ROUTES))
def test_no_reason_is_owned_by_two_statuses(module_name: str) -> None:
    """Ownership is what makes the cross-field check meaningful.

    If two statuses owned ``invalid_raster_dimensions``, a row carrying it under
    either would pass — and the check that ``MINDTCT_FAILED_LEFT`` cannot carry
    it would silently stop working.
    """
    owners: dict[str, list[str]] = {}
    for status, shape in _contract(module_name).items():
        for reason in shape.reasons:
            owners.setdefault(reason, []).append(status)
    shared = {
        reason: sorted(statuses)
        for reason, statuses in owners.items()
        if len({s.rsplit("_", 1)[0] for s in statuses}) > 1
    }
    assert not shared, (
        f"{shared} are owned by more than one status family, so the "
        "cross-field check cannot tell them apart"
    )


@pytest.mark.parametrize("module_name", sorted(_ROUTES))
def test_the_classified_reasons_are_owned_by_a_template_status(
    module_name: str,
) -> None:
    """The translation refusals belong to the status the translation raises under.

    This is the link the reviewer's example turns on: a reason owned by the
    template family cannot appear under ``MINDTCT_FAILED_*``.
    """
    module = importlib.import_module(module_name)
    contract = module.OUTCOME_CONTRACT
    for reason in module.CLASSIFIED_FAILURE_REASONS:
        owners = sorted(
            status for status, shape in contract.items() if shape.owns(reason)
        )
        assert owners, f"{reason} is classified and owned by no status"
        assert all("TEMPLATE" in status or "REFUSAL" in status for status in owners), (
            f"{reason} is a translation refusal and is owned by {owners}"
        )
        extractor = [s for s in contract if s.startswith("MINDTCT_FAILED_")]
        assert not any(contract[s].owns(reason) for s in extractor), (
            f"{reason} can be carried by {extractor}, which is the exact "
            "mismatch the contract exists to refuse"
        )
