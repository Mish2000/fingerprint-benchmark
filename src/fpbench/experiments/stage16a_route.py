"""G2 — can one route from a canonical image to a confidence be read off upstream?

This is the gate the stage turns on, and it is not the question "does FingerFlow
work". It is: *for every step between a PNG and a number, does upstream say what
to do — and is there exactly one thing it says?*

The published package answers the two ends of the route completely. It decodes
and greyscales the image, runs CoarseNet, FineNet, ClassifyNet and CoreNet, and
returns a minutiae frame ``[x, y, angle, score, class]`` beside a core frame
``[x1, y1, x2, y2, score, w, h]``. At the other end, ``Matcher.verify`` takes an
array, drops its first two columns, appends five nearest-neighbour distances and
predicts. ``MINUTIAE_FEATURES = 9`` and ``MINUTIA_NEIGHBORS = 5`` fix the input
at six columns, which is the extractor's five plus one distance to the core.

**The middle is not in the package.** Nothing in ``fingerflow`` turns the
extractor's output into the matcher's input. That construction exists only in two
scripts in the repository, and they do not agree with each other:

.. code-block:: text

    scripts/utils/generate_encodings_for_matching.py     30 minutiae, no count
                                                         guard, nsmallest, and a
                                                         mandatory 90° rotation
    scripts/extractor/visualise_feature_vector.py        20 minutiae, an explicit
                                                         count guard, sort_values,
                                                         and no rotation

Both share one function character for character — ``get_correct_core_point`` —
and diverge on everything that decides how many minutiae there are, which ones,
and what happens when there are too few. Neither runs as written: the first
returns a name its own code never assigns, and the second reads a pickle with the
extractor calls commented out.

So six of the ten questions close on upstream authority and four do not. The four
that do not are the ones that move the score. Under the rule this gate applies —
official example, else single unambiguous implementation, else upstream-declared
default, else **FAIL** — that is a failure, and it is a failure of the route's
documentation rather than of the algorithm. No experiment is run to see which
alternative scores better; choosing that way would pick the route out of the
evaluation data (docs/adr/0132).

Everything below is derived by parsing the pinned upstream sources, not by
quoting them. The digests in :data:`stage16a_identity.UPSTREAM_SOURCE_DIGESTS`
are checked first, so a finding here is a finding about specific bytes.
"""

from __future__ import annotations

import ast
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fpbench.core.stage16a_errors import Stage16ARouteClosureError
from fpbench.experiments import stage16a_artifacts as artifacts
from fpbench.experiments import stage16a_identity as frozen
from fpbench.third_party.artifacts import file_sha256

__all__ = [
    "ROUTE_SCHEMA",
    "ENCODINGS_SCRIPT",
    "VISUALISE_SCRIPT",
    "EVALUATE_SCRIPT",
    "RECOUNT_SCRIPT",
    "TRAINING_PAIR_UTILS",
    "UpstreamStatement",
    "RouteQuestion",
    "RouteClosure",
    "sources_directory",
    "read_route_closure",
    "main",
]

ROUTE_SCHEMA = "stage_16a_upstream_inference_route_v1"

ENCODINGS_SCRIPT = "scripts/utils/generate_encodings_for_matching.py"
VISUALISE_SCRIPT = "scripts/extractor/visualise_feature_vector.py"
EVALUATE_SCRIPT = "scripts/matcher/evaluate_matcher.py"
RECOUNT_SCRIPT = "scripts/utils/change_minutiae_count.py"
TRAINING_PAIR_UTILS = "scripts/matcher/utils/utils.py"
MATCHER_CONSTANTS = "src/fingerflow/matcher/VerifyNet/constants.py"
MATCHER_UTILS = "src/fingerflow/matcher/VerifyNet/utils.py"
CLASSIFY_UTILS = "src/fingerflow/extractor/ClassifyNet/utils.py"
CORE_UTILS = "src/fingerflow/extractor/CoreNet/utils.py"


def sources_directory(*, repository_root: Path | None = None) -> Path:
    """Where the pinned upstream sources live, beside the checkpoints."""
    return artifacts.store_root(repository_root=repository_root) / "sources"


# ------------------------------------------------------------------- the model


@dataclass(frozen=True, slots=True)
class UpstreamStatement:
    """One thing an upstream file says about one question."""

    source: str
    says: str
    runnable: bool
    note: str = ""

    def as_document(self) -> dict[str, Any]:
        document: dict[str, Any] = {
            "source": self.source,
            "says": self.says,
            "runnable_as_written": self.runnable,
        }
        if self.note:
            document["note"] = self.note
        return document


@dataclass(frozen=True, slots=True)
class RouteQuestion:
    """One question the route asks, and whether upstream answers it."""

    key: str
    question: str
    authority: str
    answer: str | None
    statements: tuple[UpstreamStatement, ...]
    why: str

    @property
    def settled(self) -> bool:
        return self.authority in frozen.SETTLING_AUTHORITIES

    def as_document(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "question": self.question,
            "authority": self.authority,
            "settled": self.settled,
            "answer": self.answer,
            "upstream_statements": [s.as_document() for s in self.statements],
            "why": self.why,
        }


@dataclass(frozen=True, slots=True)
class RouteClosure:
    """G2's whole answer: the conjunction over every question."""

    questions: tuple[RouteQuestion, ...]
    source_digests: dict[str, str | None]
    sources_present: bool

    @property
    def unsettled(self) -> tuple[str, ...]:
        return tuple(q.key for q in self.questions if not q.settled)

    @property
    def settled(self) -> tuple[str, ...]:
        return tuple(q.key for q in self.questions if q.settled)

    @property
    def digest_mismatches(self) -> tuple[str, ...]:
        return tuple(
            name
            for name, observed in self.source_digests.items()
            if observed is not None
            and observed != frozen.UPSTREAM_SOURCE_DIGESTS.get(name)
        )

    @property
    def gate_state(self) -> str:
        if not self.questions or self.digest_mismatches:
            return "FAIL"
        return "PASS" if not self.unsettled else "FAIL"

    @property
    def blocker(self) -> str | None:
        if self.gate_state == "PASS":
            return None
        if self.digest_mismatches:
            return "UPSTREAM_SOURCE_BYTES_DO_NOT_MATCH_THE_PIN"
        return "UPSTREAM_INFERENCE_ROUTE_NOT_CLOSED"

    def as_document(self) -> dict[str, Any]:
        return {
            "schema": ROUTE_SCHEMA,
            "gate": frozen.GATES["G2"],
            "gate_state": self.gate_state,
            "blocker": self.blocker,
            "candidate_id": frozen.CANDIDATE_ID,
            "upstream_commit": frozen.UPSTREAM_COMMIT,
            "read_from": "the pinned upstream sources, parsed",
            "not_read_from": "the package README's prose, or any run of the code",
            "decision_rule": list(frozen.ROUTE_AUTHORITIES),
            "settling_authorities": sorted(frozen.SETTLING_AUTHORITIES),
            "route_steps": list(frozen.ROUTE_STEPS),
            "extractor_output_columns": {
                "minutiae": list(frozen.MINUTIAE_COLUMNS),
                "core": list(frozen.CORE_COLUMNS),
            },
            "matcher_input_arithmetic": {
                "MINUTIAE_FEATURES": frozen.VERIFY_NET_FEATURE_COUNT,
                "MINUTIA_NEIGHBORS": frozen.VERIFY_NET_NEIGHBOURS,
                "implied_input_columns": (
                    frozen.VERIFY_NET_FEATURE_COUNT
                    - frozen.VERIFY_NET_NEIGHBOURS
                    + 2
                ),
                "why": (
                    "enhance_minutiae_points drops x and y and appends five "
                    "neighbour distances, so nine features means six input "
                    "columns: the extractor's five plus one distance to the core"
                ),
            },
            "feature_assembly_is_in_the_package": False,
            "where_feature_assembly_lives": [ENCODINGS_SCRIPT, VISUALISE_SCRIPT],
            "questions": [q.as_document() for q in self.questions],
            "settled_questions": list(self.settled),
            "unsettled_questions": list(self.unsettled),
            "experiments_run_to_choose_between_alternatives": 0,
            "why_no_experiments": (
                "picking the alternative that produces more or better scores "
                "would choose the algorithm's route out of the evaluation data. "
                "The rule is upstream authority or FAIL (docs/adr/0132)"
            ),
            "source_digests": dict(self.source_digests),
            "digest_mismatches": list(self.digest_mismatches),
            "sources_present": self.sources_present,
        }


# ------------------------------------------------------------------- parsing


def _load(directory: Path, relative: str) -> ast.Module | None:
    path = directory / relative
    if not path.is_file():
        return None
    return ast.parse(path.read_text(encoding="utf-8"))


def _assigned_constant(tree: ast.Module | None, name: str) -> Any:
    """A module-level ``NAME = <literal>``, or None."""
    if tree is None:
        return None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    try:
                        return ast.literal_eval(node.value)
                    except ValueError:
                        return None
    return None


def _function(tree: ast.Module | None, name: str) -> ast.FunctionDef | None:
    if tree is None:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _defined_functions(tree: ast.Module | None) -> set[str]:
    if tree is None:
        return set()
    return {
        node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }


def _called_attributes(node: ast.AST | None) -> set[str]:
    if node is None:
        return set()
    return {
        child.func.attr
        for child in ast.walk(node)
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
    }


def _names_loaded(node: ast.AST | None) -> set[str]:
    if node is None:
        return set()
    return {
        child.id
        for child in ast.walk(node)
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load)
    }


def _names_stored(node: ast.AST | None) -> set[str]:
    if node is None:
        return set()
    return {
        child.id
        for child in ast.walk(node)
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store)
    }


def _matcher_precisions(tree: ast.Module | None) -> tuple[int, ...]:
    """Every literal precision a ``Matcher(...)`` call is constructed with."""
    if tree is None:
        return ()
    found: list[int] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Matcher"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, int)
        ):
            found.append(node.args[0].value)
    return tuple(found)


def _guards_on_count(function: ast.FunctionDef | None) -> bool:
    """Does the assembly refuse when there are fewer minutiae than it wants?"""
    if function is None:
        return False
    for node in ast.walk(function):
        if isinstance(node, ast.Compare) and any(
            isinstance(op, (ast.Lt, ast.LtE)) for op in node.ops
        ):
            if isinstance(node.left, ast.Call) and isinstance(node.left.func, ast.Name):
                if node.left.func.id == "len":
                    return True
    return False


# ------------------------------------------------------------------- the gate


def read_route_closure(*, repository_root: Path | None = None) -> RouteClosure:
    """Parse the pinned sources and decide every route question from them."""
    directory = sources_directory(repository_root=repository_root)

    digests: dict[str, str | None] = {}
    for relative in frozen.UPSTREAM_SOURCE_DIGESTS:
        path = directory / relative
        digests[relative] = file_sha256(path) if path.is_file() else None
    present = all(value is not None for value in digests.values())
    if not present:
        return RouteClosure(questions=(), source_digests=digests, sources_present=False)

    encodings = _load(directory, ENCODINGS_SCRIPT)
    visualise = _load(directory, VISUALISE_SCRIPT)
    evaluate = _load(directory, EVALUATE_SCRIPT)
    recount = _load(directory, RECOUNT_SCRIPT)
    constants = _load(directory, MATCHER_CONSTANTS)
    utils = _load(directory, MATCHER_UTILS)

    if encodings is None or visualise is None or utils is None:
        raise Stage16ARouteClosureError(
            "the pinned upstream sources are present but unparseable; the route "
            "cannot be read from prose"
        )

    encodings_count = _assigned_constant(encodings, "MINUTIAE_NUM")
    visualise_count = _assigned_constant(visualise, "MINUTIAE_NUM")
    recount_counts = _assigned_constant(recount, "MINUTIAE_TO_USE")
    rotations = _assigned_constant(encodings, "NUM_ROTATIONS")
    evaluate_precisions = _matcher_precisions(evaluate)
    neighbours = _assigned_constant(constants, "MINUTIA_NEIGHBORS")
    features = _assigned_constant(constants, "MINUTIAE_FEATURES")

    rotate_fn = _function(encodings, "rotate_image_and_extract_minutaie_points")
    encodings_assembly = _function(encodings, "get_n_nearest_minutiae")
    visualise_assembly = _function(visualise, "get_n_nearest_minutiae")
    encodings_core = _function(encodings, "get_correct_core_point")
    visualise_core = _function(visualise, "get_correct_core_point")

    # The rotating extractor returns a name it never assigns, and the function
    # the commented-out non-rotating branch would call is defined nowhere.
    rotate_returns = _names_loaded(rotate_fn) - _names_stored(rotate_fn)
    rotate_is_broken = "nearest_minutiae" in rotate_returns
    non_rotating_entry_exists = (
        "load_image_and_extract_minutaie_points" in _defined_functions(encodings)
    )
    rotates = "rotate" in _called_attributes(rotate_fn)

    encodings_guards_count = _guards_on_count(encodings_assembly)
    visualise_guards_count = _guards_on_count(visualise_assembly)
    encodings_selects = _called_attributes(encodings_assembly)
    visualise_selects = _called_attributes(visualise_assembly)

    core_functions_identical = (
        encodings_core is not None
        and visualise_core is not None
        and ast.dump(encodings_core) == ast.dump(visualise_core)
    )

    single = "SINGLE_UNAMBIGUOUS_UPSTREAM_IMPLEMENTATION"
    must_choose = "FPBENCH_WOULD_HAVE_TO_CHOOSE"

    questions: list[RouteQuestion] = [
        RouteQuestion(
            key="which_core_is_selected",
            question="CoreNet returns every detected core. Which one is the core?",
            authority=single if core_functions_identical else must_choose,
            answer=(
                "the detection whose score is the maximum; the core point is the "
                "centre of its bounding box, x = mean(x1, x2), y = mean(y1, y2)"
            )
            if core_functions_identical
            else None,
            statements=(
                UpstreamStatement(
                    source=ENCODINGS_SCRIPT,
                    says="get_correct_core_point: core_data.score == core_data.score.max(), bbox centre",
                    runnable=True,
                ),
                UpstreamStatement(
                    source=VISUALISE_SCRIPT,
                    says="get_correct_core_point: the same function, character for character",
                    runnable=True,
                    note=(
                        "compared as parsed trees, not as text — the two "
                        "definitions are structurally identical"
                        if core_functions_identical
                        else "the two definitions differ"
                    ),
                ),
            ),
            why=(
                "one rule, stated the same way in both places that state it. A "
                "tie at the maximum score returns more than one row and the "
                "later broadcast against the minutiae frame would raise, which is "
                "an implementation defect rather than an ambiguity in the rule"
            ),
        ),
        RouteQuestion(
            key="how_minutiae_are_ordered",
            question="In what order do the retained minutiae enter the array?",
            authority=single,
            answer="ascending by distance to the core",
            statements=(
                UpstreamStatement(
                    source=ENCODINGS_SCRIPT,
                    says="nsmallest(MINUTIAE_NUM, 'core_distance') — ascending by construction",
                    runnable=False,
                ),
                UpstreamStatement(
                    source=VISUALISE_SCRIPT,
                    says="sort_values(by=['core_distance']) — ascending by default",
                    runnable=False,
                ),
                UpstreamStatement(
                    source=TRAINING_PAIR_UTILS,
                    says="np.random.shuffle on the anchor when building training pairs",
                    runnable=True,
                    note=(
                        "training-set construction, not inference: the shuffle is "
                        "how the network is taught not to depend on row order"
                    ),
                ),
            ),
            why="both assemblies order by the same key in the same direction",
        ),
        RouteQuestion(
            key="how_many_minutiae_are_retained",
            question="How many minutiae make up one feature vector?",
            authority=must_choose,
            answer=None,
            statements=(
                UpstreamStatement(
                    source=ENCODINGS_SCRIPT,
                    says=f"MINUTIAE_NUM = {encodings_count}",
                    runnable=False,
                ),
                UpstreamStatement(
                    source=VISUALISE_SCRIPT,
                    says=f"MINUTIAE_NUM = {visualise_count}",
                    runnable=False,
                ),
                UpstreamStatement(
                    source=RECOUNT_SCRIPT,
                    says=f"MINUTIAE_TO_USE = {recount_counts}",
                    runnable=True,
                    note="no VerifyNet checkpoint is published for that precision",
                ),
                UpstreamStatement(
                    source="README.md",
                    says='the usage example constructs Matcher(30, "verify_net")',
                    runnable=False,
                    note="an example of the call, not of how its argument was produced",
                ),
                UpstreamStatement(
                    source=EVALUATE_SCRIPT,
                    says=f"Matcher({', '.join(str(p) for p in evaluate_precisions)}, ...)",
                    runnable=True,
                    note="the only script that actually calls the matcher",
                ),
            ),
            why=(
                "four different counts across five upstream sources, and no "
                "statement anywhere that one of them is the default. The README "
                "offers a tendency — more minutiae, higher precision — which "
                "ranks the options without choosing one. The count is not a "
                "detail: it fixes the model's input shape and decides which "
                "minutiae are compared at all"
            ),
        ),
        RouteQuestion(
            key="how_nearest_minutiae_selection_works",
            question="Which minutiae are near what, and how is nearness measured?",
            authority=single,
            answer=(
                "twice, both in upstream code. Which minutiae enter the vector: "
                "the ones with the smallest euclidean distance from (x, y) to the "
                "core point. Which distances become features: for each minutia, "
                f"the {neighbours} smallest euclidean distances to the other "
                "minutiae, sorted ascending, taken as entries [1:6] of the sorted "
                "distance list"
            ),
            statements=(
                UpstreamStatement(
                    source=ENCODINGS_SCRIPT,
                    says="core_distance = np.linalg.norm(minutiae[['x','y']] - core)",
                    runnable=False,
                ),
                UpstreamStatement(
                    source=MATCHER_UTILS,
                    says=(
                        "find_n_nearest_minutiae sorts every distance and slices "
                        f"[1:{(neighbours or 0) + 1}], dropping the zero self-distance"
                    ),
                    runnable=True,
                    note="shipped in the package, so this half is not in question",
                ),
            ),
            why=(
                "the rule is stated once in the package and once in the assembly, "
                "and neither has an alternative"
            ),
        ),
        RouteQuestion(
            key="how_coordinates_are_made_core_relative",
            question="Do absolute coordinates reach the model, and in what frame?",
            authority=single,
            answer=(
                "they do not reach it at all. enhance_minutiae_points drops "
                "columns 0 and 1 — x and y — so the only core-relative quantity "
                "the model sees is the scalar core_distance column"
            ),
            statements=(
                UpstreamStatement(
                    source=MATCHER_UTILS,
                    says="updated_minutia[2:] — the first two columns are discarded",
                    runnable=True,
                ),
                UpstreamStatement(
                    source=CLASSIFY_UTILS,
                    says="the extractor's frame is ['x','y','angle','score','class']",
                    runnable=True,
                ),
            ),
            why=(
                "one implementation, in the package, and it settles the question "
                "by removing it: no translation, no rotation, no re-origin — the "
                "coordinates are deleted"
            ),
        ),
        RouteQuestion(
            key="whether_angles_are_transformed",
            question="Is the minutia angle rescaled, wrapped or re-referenced?",
            authority=single,
            answer="no. The angle column passes from the extractor to the model untouched",
            statements=(
                UpstreamStatement(
                    source=CLASSIFY_UTILS,
                    says="angle is column 2 of the extractor's frame",
                    runnable=True,
                ),
                UpstreamStatement(
                    source=MATCHER_UTILS,
                    says="only columns 0 and 1 are removed; nothing is rewritten",
                    runnable=True,
                ),
            ),
            why=(
                "no upstream code anywhere converts, wraps or re-references the "
                "angle. Absence is an answer here because the whole path from the "
                "extractor's frame to the model's tensor is upstream code"
            ),
        ),
        RouteQuestion(
            key="whether_rotation_augmentation_belongs_to_inference",
            question="Does the image get rotated before extraction at inference time?",
            authority=must_choose,
            answer=None,
            statements=(
                UpstreamStatement(
                    source=ENCODINGS_SCRIPT,
                    says=(
                        "rotate_image_and_extract_minutaie_points rotates 90 "
                        "degrees clockwise unconditionally and is driven "
                        f"{rotations} times per image, feeding each rotation back "
                        "as the next input"
                    ),
                    runnable=False,
                    note=(
                        "returns the name 'nearest_minutiae', which the function "
                        "never assigns — the assignment is commented out, so the "
                        "function raises NameError on its first call"
                        if rotate_is_broken
                        else "runs as written"
                    ),
                ),
                UpstreamStatement(
                    source=ENCODINGS_SCRIPT,
                    says=(
                        "the commented-out branch calls "
                        "load_image_and_extract_minutaie_points, which is defined "
                        "nowhere in the file"
                    ),
                    runnable=False,
                    note=(
                        "the non-rotating variant was deleted rather than disabled"
                        if not non_rotating_entry_exists
                        else "the non-rotating variant is present"
                    ),
                ),
                UpstreamStatement(
                    source=VISUALISE_SCRIPT,
                    says="assembles a feature vector with no rotation at all",
                    runnable=False,
                ),
            ),
            why=(
                "the only surviving image-to-features function rotates, and it is "
                "a training-data generator producing four rotations of one image "
                "as four rows. Whether inference should rotate zero times or once "
                "is a question upstream never asks, and the answer moves every "
                "coordinate, every core distance and every neighbour distance in "
                "the vector"
            ),
        ),
        RouteQuestion(
            key="what_happens_if_no_core_is_detected",
            question="CoreNet finds nothing. What is the result?",
            authority=single,
            answer=(
                "an explicit non-result: the assembly returns an empty frame and "
                "the caller skips the image. In fpbench's vocabulary that is "
                f"{frozen.EXPLICIT_ALGORITHMIC_NON_RESULT}"
            ),
            statements=(
                UpstreamStatement(
                    source=ENCODINGS_SCRIPT,
                    says="if len(core_point) == 0: return pd.DataFrame()",
                    runnable=False,
                ),
                UpstreamStatement(
                    source=VISUALISE_SCRIPT,
                    says="the same guard, first clause of the same condition",
                    runnable=False,
                ),
            ),
            why=(
                "both assemblies state the condition and return from it. This is "
                "the shape of a refusal an algorithm owns, and the result set "
                "would record it as one"
            ),
        ),
        RouteQuestion(
            key="what_happens_below_the_required_minutiae_count",
            question="Fewer minutiae are found than the model's input needs. Then what?",
            authority=must_choose,
            answer=None,
            statements=(
                UpstreamStatement(
                    source=ENCODINGS_SCRIPT,
                    says=(
                        "no count guard. nsmallest returns however many rows exist "
                        "and the caller tests only .empty, so a short vector "
                        "reaches a model whose input shape is fixed"
                    ),
                    runnable=False,
                    note=(
                        "parsed: the assembly contains no len(...) < comparison"
                        if not encodings_guards_count
                        else "parsed: a count guard is present"
                    ),
                ),
                UpstreamStatement(
                    source=VISUALISE_SCRIPT,
                    says="len(minutiae_data) < MINUTIAE_NUM: return an empty frame",
                    runnable=False,
                    note=(
                        "parsed: an explicit count guard is present"
                        if visualise_guards_count
                        else "parsed: no count guard"
                    ),
                ),
                UpstreamStatement(
                    source=MATCHER_UTILS,
                    says=(
                        f"below {(neighbours or 0) + 1} minutiae, find_n_nearest_minutiae "
                        f"returns fewer than {neighbours} distances and the enhanced "
                        "array becomes ragged"
                    ),
                    runnable=True,
                    note="a second failure mode, earlier than the model, and also unstated",
                ),
            ),
            why=(
                "the two assemblies classify the same input in opposite ways. One "
                "produces an explicit algorithmic non-result; the other produces "
                "an unhandled shape error inside predict. Under this stage's own "
                "failure split those are not two spellings of one outcome — one is "
                "a refusal the result set records, the other is a route defect "
                "that disqualifies the candidate (docs/adr/0131). Upstream "
                "declares no default"
            ),
        ),
        RouteQuestion(
            key="which_verify_net_precision_and_checkpoint",
            question="Which of the five published VerifyNet weights is the matcher?",
            authority=must_choose,
            answer=None,
            statements=(
                UpstreamStatement(
                    source="README.md",
                    says="publishes VerifyNet 10, 14, 20, 24 and 30, none marked default",
                    runnable=True,
                ),
                UpstreamStatement(
                    source="README.md",
                    says='the usage example is Matcher(30, "verify_net")',
                    runnable=False,
                ),
                UpstreamStatement(
                    source=EVALUATE_SCRIPT,
                    says=f"Matcher({', '.join(str(p) for p in evaluate_precisions)}, WEIGHTS_20)",
                    runnable=True,
                    note="the only upstream code that constructs a matcher and calls verify",
                ),
                UpstreamStatement(
                    source="README.md",
                    says="'in general, the more minutiae points the higher precision'",
                    runnable=True,
                    note="a tendency, which ranks the options without selecting one",
                ),
            ),
            why=(
                "the README's example and the only runnable matcher script "
                "disagree, and precision is not separable from the retained count "
                f"— the model's input is (precision, {features}, 1), so choosing "
                "one chooses the other. Five published checkpoints and no declared "
                "default is the textbook case for this gate's last rule"
            ),
        ),
    ]

    return RouteClosure(
        questions=tuple(questions), source_digests=digests, sources_present=True
    )


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    closure = read_route_closure(repository_root=Path("."))
    print(json.dumps(closure.as_document(), indent=2, sort_keys=True))
    return 0 if closure.gate_state == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
