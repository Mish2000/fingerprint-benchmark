"""G1 and G2 — the bytes, and the one question that decides the stage.

G2 asks two things of ``fingerprintMatcher.match_fingerprints``:

.. code-block:: text

    does it return a native scalar, before any decision is applied?
    is the direction of that scalar provable from the implementation?

Both are answered by parsing the published module. Nothing is installed, nothing
is executed, and no image is opened — which is the point: a package that cannot
hand back a number cannot be made to by any amount of harness, and finding that
out should cost one file read.

What the parse finds, and every one of these is derived rather than asserted:

.. code-block:: text

    return statements carrying a value      0
    the docstring's own Returns: section    "None"
    a literal threshold inside the function  match_ratio > 0.95
    the only observable                      print(...) on stdout
    the ratio that would have been a score   len(match_points) / keypoints_count

The ratio exists. It is computed, compared against ``0.95``, and discarded. In
the matching branch a *percentage* of it is printed; in the non-matching branch
no number is printed at all. So the callable's contract is a decision, announced
as text, on a threshold its author chose — and the package's own README confirms
it by calling ``match_fingerprints(...)`` as a bare statement with nothing on the
left of an ``=``.

That is ``BOOLEAN_OR_THRESHOLD_ONLY_OUTPUT``, the first of this stage's immediate
stop conditions, and the stage closes on it. Recovering the ratio would mean
re-implementing the function or scraping its stdout, and both are fpbench
inventing a score the package does not publish (docs/adr/0133).
"""

from __future__ import annotations

import ast
import json
import sys
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fpbench.core.stage17a_errors import (
    Stage17AArtifactIdentityError,
    Stage17AScoreContractError,
)
from fpbench.experiments import stage17a_identity as frozen
from fpbench.third_party.artifacts import (
    file_sha256,
    require_store_is_outside,
    resolve_third_party_root,
)

__all__ = [
    "ARTIFACT_SCHEMA",
    "SCORE_SCHEMA",
    "STORE_DIRECTORY",
    "ArtifactIdentity",
    "ScoreContract",
    "store_root",
    "read_published_module",
    "inspect_artifacts",
    "read_score_contract",
    "main",
]

ARTIFACT_SCHEMA = "stage_17a_artifact_identity_v1"
SCORE_SCHEMA = "stage_17a_score_contract_v1"
STORE_DIRECTORY = "fingerprintmatcher"


def store_root(*, repository_root: Path | None = None) -> Path:
    root = resolve_third_party_root(repository_root=repository_root)
    if repository_root is not None:
        require_store_is_outside(root, Path(repository_root))
    return root / STORE_DIRECTORY


# ------------------------------------------------------------------------- G1


@dataclass(frozen=True, slots=True)
class ArtifactIdentity:
    """Both published distributions, and the one module they agree on."""

    present: dict[str, bool]
    digests: dict[str, str | None]
    sizes: dict[str, int | None]
    module_digest_sdist: str | None
    module_digest_wheel: str | None

    @property
    def distributions_match(self) -> bool:
        return (
            self.digests.get(frozen.SOURCE_ARTIFACT_NAME) == frozen.SOURCE_ARTIFACT_SHA256
            and self.sizes.get(frozen.SOURCE_ARTIFACT_NAME)
            == frozen.SOURCE_ARTIFACT_SIZE_BYTES
            and self.digests.get(frozen.RUNTIME_ARTIFACT_NAME)
            == frozen.RUNTIME_ARTIFACT_SHA256
            and self.sizes.get(frozen.RUNTIME_ARTIFACT_NAME)
            == frozen.RUNTIME_ARTIFACT_SIZE_BYTES
        )

    @property
    def module_is_one_answer(self) -> bool:
        """The sdist and the wheel must ship the same module, byte for byte."""
        return (
            self.module_digest_sdist is not None
            and self.module_digest_sdist == self.module_digest_wheel
            and self.module_digest_sdist == frozen.MODULE_SHA256
        )

    @property
    def gate_state(self) -> str:
        if not all(self.present.values()):
            return "NOT_REACHED"
        return "PASS" if self.distributions_match and self.module_is_one_answer else "FAIL"

    def as_document(self) -> dict[str, Any]:
        return {
            "schema": ARTIFACT_SCHEMA,
            "gate": frozen.GATES["G1"],
            "gate_state": self.gate_state,
            "candidate_id": frozen.CANDIDATE_ID,
            "package": frozen.PACKAGE_REQUIREMENT,
            "license": frozen.LICENSE,
            "implementation_origin": frozen.IMPLEMENTATION_ORIGIN,
            "upstream_index": frozen.UPSTREAM_INDEX,
            "upstream_repository": frozen.UPSTREAM_REPOSITORY,
            "authority_is_the_distribution": frozen.AUTHORITY_IS_THE_DISTRIBUTION,
            "why_not_the_repository": frozen.WHY_NOT_THE_REPOSITORY,
            "published_distributions": [
                {
                    "name": name,
                    "role": role,
                    "expected_sha256": digest,
                    "expected_size_bytes": size,
                    "present": self.present.get(name, False),
                    "matches": self.digests.get(name) == digest
                    and self.sizes.get(name) == size,
                }
                for name, role, digest, size in (
                    (
                        frozen.SOURCE_ARTIFACT_NAME,
                        "published_sdist",
                        frozen.SOURCE_ARTIFACT_SHA256,
                        frozen.SOURCE_ARTIFACT_SIZE_BYTES,
                    ),
                    (
                        frozen.RUNTIME_ARTIFACT_NAME,
                        "published_wheel",
                        frozen.RUNTIME_ARTIFACT_SHA256,
                        frozen.RUNTIME_ARTIFACT_SIZE_BYTES,
                    ),
                )
            ],
            "module": {
                "name": frozen.MODULE_NAME,
                "expected_sha256": frozen.MODULE_SHA256,
                "sdist_sha256": self.module_digest_sdist,
                "wheel_sha256": self.module_digest_wheel,
                "sdist_and_wheel_are_identical": self.module_is_one_answer,
                "why_this_is_checked": (
                    "a package whose two distributions ship different modules has "
                    "no single answer to 'what does it do', and this stage's whole "
                    "method is to read one file"
                ),
            },
            "declared_dependencies": list(frozen.DECLARED_DEPENDENCIES),
            "declared_dependencies_are_contradictory": True,
            "why_contradictory": (
                "opencv-python and opencv-contrib-python are alternative builds of "
                "the same cv2 module and are not supported side by side. The entry "
                "point calls cv2.xfeatures2d.SIFT_create, which the main "
                "distribution does not provide: on opencv-python 5.0.0, cv2 exposes "
                "SIFT_create at the top level and has no xfeatures2d attribute at "
                "all. Recorded as an observation; the gate does not turn on it"
            ),
            "vendor_or_author_request_required": False,
            "self_service_acquisition": True,
            "store_is_outside_repository": True,
            "third_party_bytes_added_to_git": False,
        }


def read_published_module(*, repository_root: Path | None = None) -> tuple[str | None, str | None, str | None]:
    """Return (source_text, sdist_module_digest, wheel_module_digest).

    Read out of the archives themselves rather than out of an extracted copy, so
    that what is parsed is what was published.
    """
    directory = store_root(repository_root=repository_root) / "artifacts"
    sdist = directory / frozen.SOURCE_ARTIFACT_NAME
    wheel = directory / frozen.RUNTIME_ARTIFACT_NAME

    text: str | None = None
    sdist_digest: str | None = None
    wheel_digest: str | None = None

    if sdist.is_file():
        with tarfile.open(sdist, "r:gz") as archive:
            for member in archive.getmembers():
                if Path(member.name).name == frozen.MODULE_NAME:
                    handle = archive.extractfile(member)
                    if handle is not None:
                        raw = handle.read()
                        text = raw.decode("utf-8")
                        import hashlib

                        sdist_digest = hashlib.sha256(raw).hexdigest()
                    break

    if wheel.is_file():
        with zipfile.ZipFile(wheel) as archive:
            for name in archive.namelist():
                if Path(name).name == frozen.MODULE_NAME:
                    raw = archive.read(name)
                    import hashlib

                    wheel_digest = hashlib.sha256(raw).hexdigest()
                    if text is None:
                        text = raw.decode("utf-8")
                    break

    return text, sdist_digest, wheel_digest


def inspect_artifacts(*, repository_root: Path | None = None) -> ArtifactIdentity:
    directory = store_root(repository_root=repository_root) / "artifacts"
    present: dict[str, bool] = {}
    digests: dict[str, str | None] = {}
    sizes: dict[str, int | None] = {}
    for name in (frozen.SOURCE_ARTIFACT_NAME, frozen.RUNTIME_ARTIFACT_NAME):
        path = directory / name
        present[name] = path.is_file()
        digests[name] = file_sha256(path) if path.is_file() else None
        sizes[name] = path.stat().st_size if path.is_file() else None
    _, sdist_digest, wheel_digest = read_published_module(
        repository_root=repository_root
    )
    return ArtifactIdentity(
        present=present,
        digests=digests,
        sizes=sizes,
        module_digest_sdist=sdist_digest,
        module_digest_wheel=wheel_digest,
    )


# ------------------------------------------------------------------------- G2


@dataclass(frozen=True, slots=True)
class ScoreContract:
    """What the entry point actually hands back, parsed from its own source."""

    found: bool
    signature: tuple[str, ...]
    docstring_returns: str | None
    returns_with_a_value: int
    printed_observables: int
    internal_thresholds: tuple[str, ...]
    ratio_expression: str | None
    ratio_is_returned: bool
    unhandled_hazards: tuple[dict[str, str], ...]

    @property
    def returns_native_scalar(self) -> bool:
        return self.returns_with_a_value > 0

    @property
    def direction_is_provable(self) -> bool:
        """A direction can only be proved for a value that leaves the function."""
        return self.returns_native_scalar

    @property
    def gate_state(self) -> str:
        if not self.found:
            return "NOT_REACHED"
        return "PASS" if self.returns_native_scalar and self.direction_is_provable else "FAIL"

    @property
    def blocker(self) -> str | None:
        if self.gate_state != "FAIL":
            return None
        if self.internal_thresholds:
            return "BOOLEAN_OR_THRESHOLD_ONLY_OUTPUT"
        return "SCORE_DIRECTION_NOT_PROVABLE"

    def as_document(self) -> dict[str, Any]:
        return {
            "schema": SCORE_SCHEMA,
            "gate": frozen.GATES["G2"],
            "gate_state": self.gate_state,
            "blocker": self.blocker,
            "candidate_id": frozen.CANDIDATE_ID,
            "entry_point": frozen.ENTRY_QUALNAME,
            "entry_signature": list(self.signature),
            "read_from": "the published module, parsed out of the sdist and the wheel",
            "not_read_from": (
                "the project's GitHub repository, its PyPI description, or any "
                "execution of the code"
            ),
            "questions": list(frozen.SCORE_CONTRACT_QUESTIONS),
            "findings": {
                "return_statements_carrying_a_value": self.returns_with_a_value,
                "docstring_declares_returns": self.docstring_returns,
                "internal_decision_thresholds": list(self.internal_thresholds),
                "printed_observables": self.printed_observables,
                "ratio_expression": self.ratio_expression,
                "ratio_is_returned": self.ratio_is_returned,
            },
            "returns_native_scalar_before_decision": self.returns_native_scalar,
            "score_direction_provable_from_source": self.direction_is_provable,
            "score_direction": None,
            "what_the_callable_actually_publishes": (
                "a decision, announced on stdout, against a threshold its author "
                "chose. The similarity ratio is computed, compared with 0.95 and "
                "discarded; the matching branch prints a percentage of it and the "
                "non-matching branch prints no number at all"
            ),
            "upstream_readme_confirms_it": {
                "usage": (
                    'fingerprint_matcher.match_fingerprints("path/to/image1", '
                    '"path/to/image2")'
                ),
                "note": (
                    "a bare statement with nothing on the left of an =. Upstream's "
                    "own documentation captures no value, because there is none"
                ),
            },
            "what_recovering_a_score_would_require": [
                "re-implementing the function to return match_ratio",
                "or parsing the text it prints to stdout",
            ],
            "why_that_is_refused": (
                "both make fpbench the author of the number. A benchmark that "
                "reconstructs a score its candidate declined to publish is "
                "measuring its own harness (docs/adr/0133)"
            ),
            "fpbench_score_transformation": "NONE",
            "decision_threshold": "NONE",
            "calibration": "NONE",
            "additional_findings_not_gate_conclusions": list(self.unhandled_hazards),
        }


_PRINT_CALLS = {"print"}


def read_score_contract(*, repository_root: Path | None = None) -> ScoreContract:
    """Parse the entry point and decide G2 from what is in it."""
    text, _, _ = read_published_module(repository_root=repository_root)
    if text is None:
        return ScoreContract(
            found=False,
            signature=(),
            docstring_returns=None,
            returns_with_a_value=0,
            printed_observables=0,
            internal_thresholds=(),
            ratio_expression=None,
            ratio_is_returned=False,
            unhandled_hazards=(),
        )

    tree = ast.parse(text)
    entry: ast.FunctionDef | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == frozen.ENTRY_CLASS:
            for child in node.body:
                if (
                    isinstance(child, ast.FunctionDef)
                    and child.name == frozen.ENTRY_FUNCTION
                ):
                    entry = child
    if entry is None:
        raise Stage17AScoreContractError(
            f"the published module has no {frozen.ENTRY_QUALNAME}; the artifact "
            "does not contain the entry point its documentation names"
        )

    signature = tuple(argument.arg for argument in entry.args.args)

    docstring = ast.get_docstring(entry) or ""
    docstring_returns: str | None = None
    if "Returns:" in docstring:
        tail = docstring.split("Returns:", 1)[1].strip()
        docstring_returns = tail.splitlines()[0].strip() if tail else ""

    returns_with_a_value = sum(
        1
        for node in ast.walk(entry)
        if isinstance(node, ast.Return) and node.value is not None
    )

    printed = sum(
        1
        for node in ast.walk(entry)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in _PRINT_CALLS
    )

    thresholds: list[str] = []
    for node in ast.walk(entry):
        if isinstance(node, ast.If) and isinstance(node.test, ast.Compare):
            test = node.test
            if (
                isinstance(test.left, ast.Name)
                and len(test.comparators) == 1
                and isinstance(test.comparators[0], ast.Constant)
                and isinstance(test.comparators[0].value, (int, float))
            ):
                operator = {
                    ast.Gt: ">",
                    ast.GtE: ">=",
                    ast.Lt: "<",
                    ast.LtE: "<=",
                }.get(type(test.ops[0]))
                if operator:
                    thresholds.append(
                        f"{test.left.id} {operator} {test.comparators[0].value}"
                    )

    ratio_expression: str | None = None
    ratio_target: str | None = None
    for node in ast.walk(entry):
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.BinOp)
            and isinstance(node.value.op, ast.Div)
            and node.targets
            and isinstance(node.targets[0], ast.Name)
        ):
            ratio_target = node.targets[0].id
            ratio_expression = f"{ratio_target} = {ast.unparse(node.value)}"

    ratio_is_returned = any(
        isinstance(node, ast.Return)
        and node.value is not None
        and ratio_target is not None
        and ratio_target in {
            child.id for child in ast.walk(node) if isinstance(child, ast.Name)
        }
        for node in ast.walk(entry)
    )

    # Read while the function was open, and recorded because docs/adr/0131 makes
    # the distinction matter. Neither is the gate's reason.
    hazards: list[dict[str, str]] = []
    unpacked_pairs = any(
        isinstance(node, ast.For)
        and isinstance(node.target, ast.Tuple)
        and len(node.target.elts) == 2
        for node in ast.walk(entry)
    )
    if unpacked_pairs:
        hazards.append(
            {
                "hazard": "UNHANDLED_IMPLEMENTATION_EXCEPTION",
                "where": "for p, q in matches",
                "detail": (
                    "knnMatch(k=2) yields a shorter list for a query with fewer "
                    "than two neighbours, and unpacking it into two names raises "
                    "ValueError on a valid image"
                ),
            }
        )
    if ratio_expression and "keypoints_count" in ratio_expression:
        hazards.append(
            {
                "hazard": "UNHANDLED_IMPLEMENTATION_EXCEPTION",
                "where": "len(match_points) / keypoints_count",
                "detail": (
                    "keypoints_count is min(len(keypoints_1), len(keypoints_2)) "
                    "with no guard, so an image SIFT finds no keypoints in raises "
                    "ZeroDivisionError rather than producing a refusal"
                ),
            }
        )

    return ScoreContract(
        found=True,
        signature=signature,
        docstring_returns=docstring_returns,
        returns_with_a_value=returns_with_a_value,
        printed_observables=printed,
        internal_thresholds=tuple(thresholds),
        ratio_expression=ratio_expression,
        ratio_is_returned=ratio_is_returned,
        unhandled_hazards=tuple(hazards),
    )


def require_artifacts(*, repository_root: Path | None = None) -> ArtifactIdentity:
    identity = inspect_artifacts(repository_root=repository_root)
    if identity.gate_state == "FAIL":
        raise Stage17AArtifactIdentityError(
            "the local distributions are not the bytes PyPI publishes for 1.0.6"
        )
    return identity


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    command = argv[0] if argv else "score"
    root = Path(".")
    if command == "artifacts":
        document = inspect_artifacts(repository_root=root).as_document()
    else:
        document = read_score_contract(repository_root=root).as_document()
    print(json.dumps(document, indent=2, sort_keys=True))
    return 0 if document["gate_state"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
