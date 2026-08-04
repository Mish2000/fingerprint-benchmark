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
    # Stage 7D moved the orchestration out of the two SourceAFIS modules and
    # into engines that name no algorithm. The SourceAFIS modules kept their
    # names: one is now the SourceAFIS half of the seam, the other an import
    # surface (docs/adr/0056).
    "decision_engine": "fpbench.experiments.algorithm_decisions",
    "evaluation_engine": "fpbench.experiments.algorithm_evaluation",
    "decision_integration": "fpbench.experiments.sourceafis_decisions",
    "evaluation_surface": "fpbench.experiments.sourceafis_evaluation",
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
    """Section 12: the engine resolves a run through the shared research layer.

    Stronger since stage 7D: the engines import no *algorithm* module at all,
    which subsumes "neither run experiment". The SourceAFIS run pointer is now
    reached through ``algorithm_research``, and everything else algorithm-specific
    arrives through the integration (docs/adr/0056).
    """
    for key in ("decision_engine", "evaluation_engine"):
        imported = _imported_modules(key)
        assert not any(
            "sourceafis" in module or "nbis" in module for module in imported
        ), f"{key} imports an algorithm module"
    assert (
        "fpbench.experiments.algorithm_research"
        in _imported_modules("decision_engine")
    )


def test_the_evaluation_engine_reuses_the_decision_engines_source_loader():
    """One implementation of "read the source chain", not two."""
    assert "fpbench.experiments.algorithm_decisions" in _imported_modules(
        "evaluation_engine"
    )
    source = _source("evaluation_engine")
    assert "load_decision_source" in source


def test_the_sourceafis_modules_are_the_seam_rather_than_the_engine():
    """What is left in the two SourceAFIS modules is one question's answer.

    The decision module still knows what a bridge jar is and which validator to
    run — that is the algorithm-specific half. What it may not still hold is the
    orchestration.
    """
    integration = _source("decision_integration")
    for name in (
        "apply_decision_profile",
        "derive_self_eligibility",
        "build_mated_unconditional_view",
        "build_derivation_receipt",
    ):
        assert name not in integration, (
            f"the SourceAFIS integration performs derivation itself: {name}"
        )
    assert "validate_sourceafis_result_set" in integration
    assert "fpbench.experiments.algorithm_decisions" in _imported_modules(
        "decision_integration"
    )


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
    # Since stage 7D the binding hangs off the integration rather than the spec,
    # because "how do I verify this run's inputs?" is the one algorithm-specific
    # question and the spec is otherwise pure data (docs/adr/0056).
    assert native.integration.preparation_binding_factory is None
    assert canonical.integration.preparation_binding_factory is not None
    assert (
        native.integration.integration_id == canonical.integration.integration_id
    ), "both SourceAFIS derivations go through one seam"
    assert native.integration.algorithm_id == "sourceafis_java"


def test_both_sourceafis_wrappers_still_write_schema_one_receipts():
    """Section 25: no new SourceAFIS derivation, and no new SourceAFIS identity.

    A schema-2 receipt over the same chain would be a different artefact with a
    different digest, which is the one thing stage 7D may not produce.
    """
    from fpbench.core.derivation_models import DERIVATION_RECEIPT_SCHEMA_VERSION
    from fpbench.experiments.sourceafis_canonical500_decisions import (
        load_canonical_decision_spec,
    )
    from fpbench.experiments.sourceafis_native_decisions import (
        load_decision_experiment_config,
    )

    for spec in (load_decision_experiment_config(), load_canonical_decision_spec()):
        assert spec.receipt_schema_version == DERIVATION_RECEIPT_SCHEMA_VERSION == "1"
        assert not spec.extra_evidence
