"""The two SourceAFIS derivation paths run one engine, not two copies of it.

This is the architectural condition stage 6B rests on, and it is checked
structurally rather than by counting lines. If the native and canonical
derivations were two implementations, then a difference between the native and
canonical numbers could be a difference in how they were derived — and the whole
paired comparison would be measuring the wrong thing.

Three properties, each testable:

*One engine.* Both wrappers call the same functions in the same module, and the
wrappers themselves contain no derivation logic.

*No cross-import.* Neither wrapper imports the other. A canonical derivation that
reached into the native experiment would couple two things the design keeps
apart, and it would also break the moment the native experiment moved.

*No engine-to-run-module import.* The shared engine resolves a run through the
shared research layer, never by importing either run experiment (spec section 12).
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

pytestmark = [pytest.mark.decisions, pytest.mark.metrics]

_MODULES = {
    "decision_engine": "fpbench.experiments.sourceafis_decisions",
    "evaluation_engine": "fpbench.experiments.sourceafis_evaluation",
    "native_decisions": "fpbench.experiments.sourceafis_native_decisions",
    "native_evaluation": "fpbench.experiments.sourceafis_native_evaluation",
    "canonical_decisions": "fpbench.experiments.sourceafis_canonical500_decisions",
    "canonical_evaluation": "fpbench.experiments.sourceafis_canonical500_evaluation",
}


def _source(name: str) -> str:
    module = importlib.import_module(_MODULES[name])
    return Path(module.__file__).read_text("utf-8")


def _imported_modules(name: str) -> set[str]:
    """Every module this one imports, including inside function bodies."""
    tree = ast.parse(_source(name))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


# ------------------------------------------------------------- one engine


def test_both_decision_wrappers_call_the_same_engine():
    from fpbench.experiments import sourceafis_canonical500_decisions as canonical
    from fpbench.experiments import sourceafis_decisions as engine
    from fpbench.experiments import sourceafis_native_decisions as native

    for wrapper in (native, canonical):
        for name in (
            "prepare_decision_derivation",
            "derive_decisions",
            "inspect_decisions",
            "finalize_decision_derivation",
        ):
            assert getattr(engine, name) is not None
        assert engine.__name__ in _imported_modules(
            "native_decisions" if wrapper is native else "canonical_decisions"
        )


def test_both_evaluation_wrappers_call_the_same_engine():
    from fpbench.experiments import sourceafis_evaluation as engine

    for key in ("native_evaluation", "canonical_evaluation"):
        assert engine.__name__ in _imported_modules(key)


def test_the_engines_are_the_only_place_derivation_logic_lives():
    """A wrapper that grew its own ``apply_decision_profile`` call is a copy.

    The names checked here are the ones that actually do the work. A wrapper
    naming any of them is deriving rather than configuring.
    """
    forbidden_in_decision_wrappers = (
        "apply_decision_profile",
        "derive_self_eligibility",
        "build_mated_unconditional_view",
        "build_mated_conditional_view",
        "build_non_mated_sanity_view",
        "build_derivation_receipt",
        "build_derivation_finalization_marker",
    )
    for key in ("native_decisions", "canonical_decisions"):
        source = _source(key)
        for name in forbidden_in_decision_wrappers:
            assert name not in source, f"{key} performs derivation itself: {name}"

    forbidden_in_evaluation_wrappers = (
        "aggregate_count_records",
        "build_observations",
        "render_report",
        "build_evaluation_receipt",
        "build_evaluation_finalization_marker",
        "verify_metric_set",
    )
    for key in ("native_evaluation", "canonical_evaluation"):
        source = _source(key)
        for name in forbidden_in_evaluation_wrappers:
            assert name not in source, f"{key} performs evaluation itself: {name}"


# ---------------------------------------------------------- no cross-import


def test_no_wrapper_imports_its_opposite_number():
    native = _imported_modules("native_decisions") | _imported_modules(
        "native_evaluation"
    )
    canonical = _imported_modules("canonical_decisions") | _imported_modules(
        "canonical_evaluation"
    )
    assert not any("canonical500" in module for module in native), (
        "a native wrapper imports a canonical one"
    )
    assert not any(
        module.endswith("sourceafis_native_decisions")
        or module.endswith("sourceafis_native_evaluation")
        or module.endswith("sourceafis_native_full")
        for module in canonical
    ), "a canonical wrapper imports a native one"


def test_the_shared_engines_import_neither_run_experiment():
    """Section 12: the engine resolves a run through the shared research layer."""
    for key in ("decision_engine", "evaluation_engine"):
        imported = _imported_modules(key)
        assert not any(
            module.endswith("sourceafis_native_full")
            or module.endswith("sourceafis_canonical500_full")
            for module in imported
        ), f"{key} imports a run experiment module"
    assert (
        "fpbench.experiments.sourceafis_research"
        in _imported_modules("decision_engine")
    )


def test_the_evaluation_engine_reuses_the_decision_engines_source_loader():
    """One implementation of "read the source chain", not two."""
    assert "fpbench.experiments.sourceafis_decisions" in _imported_modules(
        "evaluation_engine"
    )
    source = _source("evaluation_engine")
    assert "load_decision_source" in source


# ------------------------------------------------------- spec is data only


def test_the_two_decision_specs_differ_only_in_data():
    from fpbench.experiments.sourceafis_canonical500_decisions import (
        load_canonical_decision_spec,
    )
    from fpbench.experiments.sourceafis_native_decisions import (
        load_decision_experiment_config,
    )

    native = load_decision_experiment_config()
    canonical = load_canonical_decision_spec()

    assert type(native) is type(canonical)
    # The five things that may differ, and they are all data.
    assert native.experiment_id != canonical.experiment_id
    assert native.source_experiment_id != canonical.source_experiment_id
    assert native.decision_profile_config != canonical.decision_profile_config
    assert native.evidence_directory != canonical.evidence_directory
    # And the things that may not.
    assert native.expected_decisions == canonical.expected_decisions == 6000
    assert (
        native.expected_eligibility_units
        == canonical.expected_eligibility_units
        == 1500
    )
    assert native.expected_rows_per_view == canonical.expected_rows_per_view == 1500
    assert (
        native.non_mated_finger_shift == canonical.non_mated_finger_shift
    ), "the two derivations must be built over the same impostor strategy"
    # Only the canonical derivation checks results against a prepared-image set.
    assert native.preparation_expectations is None
    assert canonical.preparation_expectations is not None
