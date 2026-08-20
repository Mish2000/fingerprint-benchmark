"""The Stage 8D methodology, checked as structure rather than as prose.

Everything here is a *negative* requirement — a thing the calibration layer must
not be able to do — plus the vocabulary that makes each refusal expressible. All
of it holds from the first Stage 8D commit, before any selector exists, because
these are the constraints the selector is written under rather than properties
discovered afterwards.

The two that matter most:

* ``fpbench.calibration`` cannot see an algorithm. Not by import, not by a
  deferred import inside a function body, not by a module-level default that
  names one.
* nothing in the package normalizes a score. Absent, not disabled
  (docs/adr/0080).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import fpbench
from fpbench import calibration
from fpbench.core.enums import (
    CalibrationFailurePolicy,
    CalibrationInfrastructureStatus,
    CalibrationPairTruth,
    CalibrationTargetMetric,
    CalibrationTargetPopulation,
    CalibrationTiePolicy,
    CandidateBoundaryPolicy,
    CohortRole,
    ProtectedIdentityKind,
    ScoreDirection,
    ScoreNormalizationPolicy,
    ScorePopulationPolicy,
    ThresholdSelectionRule,
)
from fpbench.core.calibration_errors import (
    CalibrationError,
    CalibrationLeakageError,
    CalibrationSourceError,
)
from fpbench.core.errors import FpbenchError, StorageError

pytestmark = pytest.mark.stage8d_contract

SOURCE_ROOT = Path(fpbench.__file__).resolve().parent
CALIBRATION_ROOT = SOURCE_ROOT / "calibration"


def calibration_files() -> list[Path]:
    return sorted(CALIBRATION_ROOT.rglob("*.py"))


def imports_of(path: Path) -> set[str]:
    """Every module this file imports, including inside function bodies."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


def defined_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
    return names


# ------------------------------------------------------- the dependency rule


def test_the_calibration_package_exists_and_is_importable() -> None:
    assert CALIBRATION_ROOT.is_dir()
    assert calibration.CALIBRATION_SCHEMA_VERSION == "2"


@pytest.mark.parametrize("forbidden", calibration.FORBIDDEN_IMPORT_ROOTS)
def test_calibration_imports_no_algorithm_and_no_layer_above_it(forbidden) -> None:
    offenders: list[str] = []
    for path in calibration_files():
        for module in imports_of(path):
            if module == forbidden or module.startswith(f"{forbidden}."):
                offenders.append(f"{path.relative_to(SOURCE_ROOT)} -> {module}")
    assert offenders == [], f"calibration must not import {forbidden}: {offenders}"


def test_calibration_imports_core_and_itself_and_nothing_else_of_fpbench() -> None:
    """Stated positively, so a new forbidden package is covered automatically."""
    offenders: list[str] = []
    for path in calibration_files():
        for module in imports_of(path):
            if not module.startswith("fpbench"):
                continue
            if module.startswith(("fpbench.core", "fpbench.calibration")):
                continue
            if module == "fpbench":
                continue
            offenders.append(f"{path.relative_to(SOURCE_ROOT)} -> {module}")
    assert offenders == [], f"calibration reached outside core: {offenders}"


def test_calibration_never_names_an_algorithm_in_its_source() -> None:
    """Not in an import, not in a default value, not in an identifier.

    Prose is exempt: a docstring may say why the rule exists. So the check runs
    over the syntax tree's names and string constants rather than over the raw
    text, and the package's own forbidden-token tuple is assembled from parts so
    that this test does not find the list it is enforcing.
    """
    algorithms = ("".join(("source", "afis")), "nbis", "bozorth", "mindtct", "flx")
    offenders: list[str] = []
    for path in calibration_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.col_offset == 0:
                    continue  # a module docstring
                haystack = node.value.lower()
            elif isinstance(node, ast.Name):
                haystack = node.id.lower()
            elif isinstance(node, (ast.ClassDef, ast.FunctionDef)):
                haystack = node.name.lower()
            elif isinstance(node, ast.Attribute):
                haystack = node.attr.lower()
            else:
                continue
            for name in algorithms:
                if name in haystack:
                    offenders.append(f"{path.relative_to(SOURCE_ROOT)}: {name}")
    assert offenders == [], f"calibration names an algorithm: {sorted(set(offenders))}"


# --------------------------------------------------------- no normalization


@pytest.mark.parametrize("token", calibration.FORBIDDEN_NORMALIZATION_TOKENS)
def test_no_module_defines_a_score_normalizer(token) -> None:
    """docs/adr/0080: absent, not disabled."""
    offenders = [
        str(path.relative_to(SOURCE_ROOT))
        for path in calibration_files()
        if token in defined_names(path)
    ]
    assert offenders == [], f"{token!r} is defined in {offenders}"


def test_the_only_normalization_policy_is_none() -> None:
    assert [member.value for member in ScoreNormalizationPolicy] == ["none"]


def test_calibration_imports_no_numeric_library_that_could_reshape_a_score() -> None:
    """No numpy, no scipy, no sklearn. Exact integers need none of them."""
    forbidden = ("numpy", "scipy", "sklearn", "pandas", "statistics")
    offenders: list[str] = []
    for path in calibration_files():
        for module in imports_of(path):
            if module.split(".")[0] in forbidden:
                offenders.append(f"{path.relative_to(SOURCE_ROOT)} -> {module}")
    assert offenders == [], offenders


def test_calibration_never_uses_binary_floating_point_for_a_rate() -> None:
    """No ``float(`` call and no float literal anywhere in the package.

    A target rate is a pair of integers and a score is a ``Decimal``. A single
    ``float`` in this package would be a place where one in a thousand stops
    being one in a thousand (docs/adr/0080).
    """
    offenders: list[str] = []
    for path in calibration_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and type(node.value) is float:
                offenders.append(f"{path.relative_to(SOURCE_ROOT)}:{node.lineno}")
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "float"
            ):
                offenders.append(f"{path.relative_to(SOURCE_ROOT)}:{node.lineno}")
    assert offenders == [], f"binary floating point in calibration: {offenders}"


# ------------------------------------------------------------- the vocabulary


def test_the_impostor_population_has_exactly_two_truths_and_no_sanity_member() -> None:
    """docs/adr/0079: the same-subject sanity set is not an impostor sample."""
    assert [member.value for member in CalibrationPairTruth] == [
        "mated",
        "cross_subject_impostor",
    ]
    spellings = {member.value for member in CalibrationPairTruth}
    assert not any("sanity" in value for value in spellings)
    assert not any("same_subject" in value for value in spellings)


def test_evaluation_is_an_alias_of_test_and_moves_no_stored_value() -> None:
    """docs/adr/0079: a spelling was added, not a role."""
    assert CohortRole.EVALUATION is CohortRole.TEST
    assert CohortRole.EVALUATION.value == "test"
    assert CohortRole("test") is CohortRole.TEST
    assert [member.value for member in CohortRole] == ["test", "development"]


def test_only_the_development_role_may_select_a_threshold() -> None:
    assert CohortRole.DEVELOPMENT.permits_threshold_selection is True
    assert CohortRole.TEST.permits_threshold_selection is False
    assert CohortRole.EVALUATION.permits_threshold_selection is False


def test_both_score_directions_are_first_class() -> None:
    """Algorithms 4 and 5 are not known, and neither is which way they run."""
    assert set(ScoreDirection) == {
        ScoreDirection.HIGHER_IS_BETTER,
        ScoreDirection.LOWER_IS_BETTER,
    }


def test_the_fixed_policies_each_have_exactly_one_member_in_v1() -> None:
    """A second member is a second protocol, not a setting on this one."""
    for enum in (
        CalibrationTargetMetric,
        CalibrationTargetPopulation,
        ThresholdSelectionRule,
        CandidateBoundaryPolicy,
        CalibrationTiePolicy,
        ScorePopulationPolicy,
        CalibrationFailurePolicy,
        ScoreNormalizationPolicy,
    ):
        assert len(list(enum)) == 1, enum


def test_the_target_population_is_scored_comparisons_not_all_attempts() -> None:
    """Spec section 17: the ceiling is over comparisons that produced a score."""
    assert (
        CalibrationTargetPopulation.SCORED_COMPARISONS.value == "scored_comparisons"
    )


def test_the_protected_identity_kinds_name_identities_and_never_scores() -> None:
    values = {member.value for member in ProtectedIdentityKind}
    assert values == {
        "dataset",
        "cohort",
        "pair_manifest",
        "preparation_set",
        "run",
        "result_set",
    }


def test_the_status_ladder_ends_at_infrastructure_and_not_at_calibration() -> None:
    terminal = CalibrationInfrastructureStatus.CALIBRATION_INFRASTRUCTURE_READY
    assert terminal.value == "calibration_infrastructure_ready"
    spellings = {member.value for member in CalibrationInfrastructureStatus}
    assert "calibrated" not in spellings
    assert "threshold_ready" not in spellings


# ---------------------------------------------------------------- the errors


def test_leakage_is_its_own_error_and_not_a_kind_of_malformed_input() -> None:
    """A caller handling parse failures must not swallow a leakage refusal."""
    assert issubclass(CalibrationLeakageError, CalibrationError)
    assert not issubclass(CalibrationLeakageError, CalibrationSourceError)
    assert not issubclass(CalibrationSourceError, CalibrationLeakageError)


def test_a_calibration_store_conflict_is_a_storage_error() -> None:
    from fpbench.core.calibration_errors import CalibrationConflictError

    assert issubclass(CalibrationConflictError, StorageError)


def test_the_calibration_vocabulary_lives_beside_the_pinned_one_not_inside_it():
    """Stage 8A pins ``core/errors.py`` byte for byte, so Stage 8D cannot edit it.

    The same constraint produced ``core/flx_errors.py`` one stage earlier. What
    matters for callers is that the roots are shared, so ``except FpbenchError``
    still catches everything this project raises.
    """
    from fpbench.core import calibration_errors, errors

    assert not hasattr(errors, "CalibrationError")
    assert issubclass(calibration_errors.CalibrationError, FpbenchError)
    exported = set(calibration_errors.__all__)
    assert exported == {
        name
        for name in dir(calibration_errors)
        if isinstance(getattr(calibration_errors, name), type)
        and issubclass(getattr(calibration_errors, name), FpbenchError)
        and getattr(calibration_errors, name).__module__ == calibration_errors.__name__
    }
