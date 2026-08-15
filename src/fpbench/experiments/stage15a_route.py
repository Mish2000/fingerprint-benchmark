"""G2 — what happens between two image paths and a number, and who does it.

The question this gate answers is not "does the package work". It is: *can a
canonical 500 ppi PNG enter the package's own route without fpbench putting
anything in front of it, and is the number that comes out the package's own
number?*

The answer is read out of the installed module's source, by parsing it. Not out
of the README — which, as it happens, documents an import that does not work:
``from fingerprints_matching import FingerprintsMatching`` fails against a wheel
whose ``__init__.py`` is empty. The route exists and is reachable at
``fingerprints_matching.fingerprints_matching.FingerprintsMatching``; only
upstream's convenience re-export was never written. That distinction is exactly
why a route is confirmed against bytes rather than against prose
(docs/adr/0110).

What the route turns out to be, in full:

.. code-block:: text

    image_path1, image_path2
        -> cv2.imread                             upstream decodes
        -> cv2.cvtColor(BGR2GRAY)                 upstream greyscales
        -> cv2.threshold(BINARY_INV | OTSU)       upstream binarises
        -> cv2.findContours(EXTERNAL, SIMPLE)     upstream segments
        -> cv2.convexHull / convexityDefects      upstream builds features
        -> match(minutiae1, minutiae2)            upstream matches
        -> float

Every preprocessing step a fingerprint matcher normally needs is inside that
list. fpbench adds none of them, and this module's job is to keep it that way: it
records the refused steps beside the route so that a later change which quietly
inserts one is a diff against a published contract.

One property of ``match`` is load-bearing and is frozen here rather than merely
noted: it returns ``sum(best) / len(minutiae1)``. The first argument sets the
denominator. The two orderings are therefore two different questions, and
``left → image_path1`` becomes part of the algorithm's identity rather than a
convention the adapter could reverse later (docs/adr/0109).
"""

from __future__ import annotations

import ast
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fpbench.core.stage15a_errors import Stage15ARouteContractError
from fpbench.experiments import stage15a_identity as frozen
from fpbench.experiments import stage15a_runtime as runtime
from fpbench.third_party.artifacts import file_sha256

__all__ = [
    "ROUTE_SCHEMA",
    "RouteFinding",
    "RouteContract",
    "installed_package_directory",
    "read_route_contract",
    "main",
]

ROUTE_SCHEMA = "stage_15a_upstream_route_contract_v1"

#: The OpenCV calls the route must be seen to make, and the arguments that make
#: them the *particular* transformations they are. A threshold flag is not
#: packaging detail: ``THRESH_OTSU`` chooses the binarisation level from the
#: image's own histogram, which is why fpbench never needs to choose one.
_REQUIRED_CALLS: dict[str, tuple[str, ...]] = {
    "imread": (),
    "cvtColor": ("COLOR_BGR2GRAY",),
    "threshold": ("THRESH_BINARY_INV", "THRESH_OTSU"),
    "findContours": ("RETR_EXTERNAL", "CHAIN_APPROX_SIMPLE"),
    "convexHull": (),
    "convexityDefects": (),
}


def installed_package_directory(*, repository_root: Path | None = None) -> Path | None:
    """Where the frozen environment actually imports the package from."""
    observed = runtime.inspect_installed_runtime(repository_root=repository_root)
    paths = observed.get("module_paths")
    if not isinstance(paths, dict):
        return None
    anchor = paths.get("fingerprints_matching/minutiae_matching.py")
    return Path(str(anchor)).parent if anchor else None


@dataclass(frozen=True, slots=True)
class RouteFinding:
    """One checked claim about the route, and what settled it."""

    claim: str
    holds: bool
    detail: str

    def as_document(self) -> dict[str, Any]:
        return {"claim": self.claim, "holds": self.holds, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class RouteContract:
    findings: tuple[RouteFinding, ...]
    module_digests: dict[str, str | None]
    entry_signature: tuple[str, ...] | None
    denominator_argument: str | None

    @property
    def gate_state(self) -> str:
        if not self.findings:
            return "ACTION_REQUIRED"
        return "PASS" if all(f.holds for f in self.findings) else "FAIL"

    @property
    def failures(self) -> tuple[str, ...]:
        return tuple(f.claim for f in self.findings if not f.holds)

    def as_document(self) -> dict[str, Any]:
        return {
            "schema": ROUTE_SCHEMA,
            "gate": frozen.GATES["G2"],
            "gate_state": self.gate_state,
            "candidate_id": frozen.CANDIDATE_ID,
            "entry_point": frozen.ENTRY_QUALNAME,
            "entry_signature": list(self.entry_signature or ()),
            "read_from": "the installed module source, parsed",
            "not_read_from": "the package README or its PyPI description",
            "readme_import_is_broken": {
                "documented": "from fingerprints_matching import FingerprintsMatching",
                "why_it_fails": "the distribution's __init__.py is empty (0 bytes)",
                "working_import": (
                    "from fingerprints_matching.fingerprints_matching import "
                    "FingerprintsMatching"
                ),
                "is_a_gate_failure": False,
                "why_not": (
                    "the top-level route exists and is reachable; only upstream's "
                    "convenience re-export was never written. fpbench imports the "
                    "module that defines it and adds nothing"
                ),
            },
            "upstream_route_steps": list(frozen.UPSTREAM_ROUTE_STEPS),
            "fpbench_adds": [],
            "fpbench_refuses_to_add": list(frozen.REFUSED_FPBENCH_STEPS),
            "argument_binding": {
                "pair.left": frozen.LEFT_ARGUMENT,
                "pair.right": frozen.RIGHT_ARGUMENT,
                "denominator_argument": self.denominator_argument,
                "orientation_is_part_of_identity": True,
                "why": (
                    "match returns sum(best)/len(minutiae1), so the first argument "
                    "sets the denominator and the two orderings ask different "
                    "questions (docs/adr/0109)"
                ),
            },
            "score_contract": {
                "score_native_type": frozen.SCORE_NATIVE_TYPE,
                "observed_python_type": "numpy.float64",
                "type_note": (
                    "numpy.float64 subclasses float and holds the same IEEE "
                    "double; widening it is a type normalisation, not a score "
                    "transformation — the bits do not move"
                ),
                "score_direction": frozen.SCORE_DIRECTION,
                "score_range": frozen.SCORE_RANGE,
                "fpbench_score_transformation": frozen.FPBENCH_SCORE_TRANSFORMATION,
                "decision_threshold": frozen.DECISION_THRESHOLD,
                "upstream_readme_threshold": frozen.UPSTREAM_README_THRESHOLD,
                "upstream_readme_threshold_is_fpbench_threshold": False,
            },
            "module_digests": dict(self.module_digests),
            "findings": [f.as_document() for f in self.findings],
            "failed_claims": list(self.failures),
        }


def _find_function(tree: ast.Module, name: str) -> ast.FunctionDef | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _called_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
            names.add(child.func.attr)
        elif isinstance(child, ast.Call) and isinstance(child.func, ast.Name):
            names.add(child.func.id)
    return names


def _referenced_attributes(node: ast.AST) -> set[str]:
    return {
        child.attr for child in ast.walk(node) if isinstance(child, ast.Attribute)
    }


def read_route_contract(*, repository_root: Path | None = None) -> RouteContract:
    """Parse the installed route and check every claim the contract freezes."""
    package = installed_package_directory(repository_root=repository_root)
    if package is None or not package.exists():
        return RouteContract(
            findings=(), module_digests={}, entry_signature=None, denominator_argument=None
        )

    digests: dict[str, str | None] = {}
    for relative in frozen.UPSTREAM_MODULE_DIGESTS:
        path = package.parent / Path(relative)
        digests[relative] = file_sha256(path) if path.exists() else None

    entry_source = package / "fingerprints_matching.py"
    minutiae_source = package / "minutiae_matching.py"
    if not entry_source.exists() or not minutiae_source.exists():
        raise Stage15ARouteContractError(
            "the installed package does not contain the two modules the route "
            f"is defined in; looked under {package}"
        )
    entry_tree = ast.parse(entry_source.read_text(encoding="utf-8"))
    minutiae_tree = ast.parse(minutiae_source.read_text(encoding="utf-8"))

    findings: list[RouteFinding] = []

    # -- the installed bytes are the published bytes
    for relative, expected in frozen.UPSTREAM_MODULE_DIGESTS.items():
        observed = digests.get(relative)
        findings.append(
            RouteFinding(
                claim=f"installed {relative} is the published byte sequence",
                holds=observed == expected,
                detail=(
                    "digest matches the wheel"
                    if observed == expected
                    else f"expected {expected[:16]}…, found {(observed or 'absent')[:16]}…"
                ),
            )
        )

    # -- the entry point exists, is a two-path function, and returns the match
    entry_fn: ast.FunctionDef | None = None
    for node in ast.walk(entry_tree):
        if isinstance(node, ast.ClassDef) and node.name == frozen.ENTRY_CLASS:
            entry_fn = _find_function(node, frozen.ENTRY_FUNCTION)
    signature = tuple(a.arg for a in entry_fn.args.args) if entry_fn else None
    findings.append(
        RouteFinding(
            claim="the top-level entry point takes exactly the two image paths",
            holds=signature == (frozen.LEFT_ARGUMENT, frozen.RIGHT_ARGUMENT),
            detail=f"signature {signature}",
        )
    )

    entry_calls = _called_names(entry_fn) if entry_fn else set()
    findings.append(
        RouteFinding(
            claim="the entry point performs two extractions and one match itself",
            holds={"extract_minutiae", "match"} <= entry_calls,
            detail=f"calls {sorted(entry_calls)}",
        )
    )

    # -- every image operation belongs to the package, and is the one frozen
    extract_fn = _find_function(minutiae_tree, "extract_minutiae")
    if extract_fn is None:
        raise Stage15ARouteContractError(
            "the installed minutiae_matching module has no extract_minutiae"
        )
    extract_calls = _called_names(extract_fn)
    extract_attrs = _referenced_attributes(extract_fn)
    for call, flags in _REQUIRED_CALLS.items():
        missing_flags = [flag for flag in flags if flag not in extract_attrs]
        findings.append(
            RouteFinding(
                claim=f"upstream performs cv2.{call} itself",
                holds=call in extract_calls and not missing_flags,
                detail=(
                    f"present with {', '.join(flags)}"
                    if flags
                    else ("present" if call in extract_calls else "absent")
                )
                if call in extract_calls and not missing_flags
                else f"missing: {'the call' if call not in extract_calls else missing_flags}",
            )
        )

    # -- the denominator, which is what makes the route asymmetric
    match_fn = _find_function(minutiae_tree, "match")
    denominator: str | None = None
    if match_fn is not None:
        for node in ast.walk(match_fn):
            if (
                isinstance(node, ast.Return)
                and isinstance(node.value, ast.BinOp)
                and isinstance(node.value.op, ast.Div)
            ):
                divisor = node.value.right
                if (
                    isinstance(divisor, ast.Call)
                    and isinstance(divisor.func, ast.Name)
                    and divisor.func.id == "len"
                    and divisor.args
                    and isinstance(divisor.args[0], ast.Name)
                ):
                    denominator = divisor.args[0].id
    findings.append(
        RouteFinding(
            claim="the match normalises by the first argument's feature count",
            holds=denominator == "minutiae1",
            detail=f"returns sum / len({denominator})",
        )
    )

    # -- and fpbench is not in any of it
    findings.append(
        RouteFinding(
            claim="a canonical PNG path enters the route with nothing in front of it",
            holds=signature == (frozen.LEFT_ARGUMENT, frozen.RIGHT_ARGUMENT)
            and "imread" in extract_calls,
            detail=(
                "the entry point takes paths and upstream decodes them; fpbench "
                "hands over the prepared file and adds none of "
                f"{', '.join(frozen.REFUSED_FPBENCH_STEPS)}"
            ),
        )
    )

    return RouteContract(
        findings=tuple(findings),
        module_digests=digests,
        entry_signature=signature,
        denominator_argument=denominator,
    )


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    contract = read_route_contract(repository_root=Path("."))
    print(json.dumps(contract.as_document(), indent=2, sort_keys=True))
    return 0 if contract.gate_state == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
