"""What the adapter exposes, and what it structurally cannot see."""

from __future__ import annotations

import inspect
from decimal import Decimal

import pytest

from fpbench.core.flx_errors import FlxError, FlxRuntimeError
from fpbench.flx import identity
from fpbench.flx.integration import (
    FORBIDDEN_INPUTS,
    FlxLearnedFingerprintIntegration,
    build_adapter_profile,
)
from fpbench.modern_matchers.base import LearnedFingerprintIntegration

pytestmark = pytest.mark.stage8b_contract


def test_the_adapter_implements_the_contract_stage8a_froze() -> None:
    assert isinstance(FlxLearnedFingerprintIntegration, type)
    for operation in (
        "load_runtime",
        "preprocess",
        "extract",
        "compare",
        "validate_runtime",
        "describe_operation",
    ):
        assert callable(getattr(FlxLearnedFingerprintIntegration, operation)), operation


def test_the_contract_signatures_match_the_frozen_protocol() -> None:
    for operation in ("preprocess", "extract", "compare", "validate_runtime", "describe_operation"):
        expected = tuple(
            inspect.signature(getattr(LearnedFingerprintIntegration, operation)).parameters
        )
        actual = tuple(
            inspect.signature(getattr(FlxLearnedFingerprintIntegration, operation)).parameters
        )
        assert actual == expected, operation


def test_no_operation_accepts_a_label_a_pair_or_a_threshold() -> None:
    # The exclusion is structural: these are not fields the adapter hides,
    # they are fields no signature can carry.
    for operation in ("preprocess", "extract", "compare", "describe_operation", "validate_runtime"):
        parameters = set(
            inspect.signature(getattr(FlxLearnedFingerprintIntegration, operation)).parameters
        )
        assert parameters.isdisjoint(set(FORBIDDEN_INPUTS)), operation
        assert parameters.isdisjoint({"pair", "pair_id", "label", "ground_truth", "image_id"})


def test_compare_returns_decimal_by_annotation() -> None:
    # `from __future__ import annotations` leaves annotations as strings, so
    # they are resolved rather than compared as text.
    from typing import get_type_hints

    hints = get_type_hints(FlxLearnedFingerprintIntegration.compare)
    assert hints["return"] is Decimal


def test_the_adapter_profile_names_the_frozen_identities() -> None:
    profile = build_adapter_profile()

    assert profile.adapter_id == identity.ADAPTER_ID
    assert profile.adapter_version == identity.ADAPTER_VERSION
    assert profile.algorithm_id == identity.ALGORITHM_ID
    assert profile.runtime_profile_id == identity.RUNTIME_PROFILE_ID
    assert profile.preprocessing_profile_id == identity.PREPROCESSING_PROFILE_ID
    assert profile.representation_profile_id == identity.REPRESENTATION_PROFILE_ID
    assert profile.score_profile_id == identity.SCORE_PROFILE_ID
    assert profile.score_serialization_profile_id == identity.SCORE_SERIALIZATION_PROFILE_ID


def test_the_adapter_profile_denies_caching_persistence_and_retries() -> None:
    profile = build_adapter_profile()

    assert profile.caches_representations is False
    assert profile.persists_representations is False
    assert profile.retries_failed_operations is False
    assert profile.loads_torch_in_parent is False


def test_the_adapter_profile_names_every_forbidden_input() -> None:
    assert build_adapter_profile().forbidden_inputs == FORBIDDEN_INPUTS
    assert {"subject_id", "mated", "threshold", "sourceafis_result", "nbis_result"} <= set(
        FORBIDDEN_INPUTS
    )


def test_describe_operation_publishes_identity_and_no_decision() -> None:
    # describe_operation is pure metadata, so it can be checked without a runtime.
    described = FlxLearnedFingerprintIntegration.describe_operation(
        object.__new__(FlxLearnedFingerprintIntegration)
    )

    assert described["algorithm_id"] == identity.ALGORITHM_ID
    assert described["adapter_version"] == identity.ADAPTER_VERSION
    assert described["checkpoint_sha256"] == identity.CHECKPOINT_SHA256
    assert described["weights_license_status"] == "unresolved"
    assert described["range_validation_tolerance"] == (
        identity.SCORE_RANGE_VALIDATION_TOLERANCE
    )
    assert described["range_validation_policy"] == identity.SCORE_RANGE_VALIDATION_POLICY
    for forbidden in (
        "threshold",
        "decision",
        "dataset",
        "dataset_name",
        "subject_id",
        "label",
        "ground_truth",
        "cache_state",
        "representation_path",
    ):
        assert forbidden not in described, forbidden


def test_describe_operation_carries_every_profile_fingerprint() -> None:
    described = FlxLearnedFingerprintIntegration.describe_operation(
        object.__new__(FlxLearnedFingerprintIntegration)
    )

    for key in (
        "preprocessing_profile_fingerprint",
        "representation_profile_fingerprint",
        "score_profile_fingerprint",
        "adapter_profile_fingerprint",
    ):
        assert len(described[key]) == 64, key


def test_an_operation_before_load_runtime_is_refused() -> None:
    adapter = object.__new__(FlxLearnedFingerprintIntegration)
    adapter._session = None

    with pytest.raises(FlxRuntimeError, match="load_runtime\\(\\) must succeed"):
        adapter._require_session()


def test_preprocess_takes_bytes_and_says_so() -> None:
    adapter = object.__new__(FlxLearnedFingerprintIntegration)
    adapter._session = None

    with pytest.raises(FlxError, match="takes image bytes"):
        adapter.preprocess("a path to an image")


def test_extract_takes_a_model_input_not_a_path() -> None:
    adapter = object.__new__(FlxLearnedFingerprintIntegration)
    adapter._session = None

    with pytest.raises(FlxError, match="takes a ModelInput"):
        adapter.extract(b"raw bytes")


def test_compare_takes_two_representations() -> None:
    adapter = object.__new__(FlxLearnedFingerprintIntegration)
    adapter._session = None

    with pytest.raises(FlxError, match="compare takes representations; left is"):
        adapter.compare("left", "right")


def test_the_adapter_module_never_imports_torch() -> None:
    import ast
    from pathlib import Path

    source = Path(
        Path(__file__).resolve().parents[2] / "src/fpbench/flx/integration.py"
    ).read_text(encoding="utf-8")
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not {name for name in imported if name.split(".")[0] in {"torch", "torchvision", "numpy"}}
